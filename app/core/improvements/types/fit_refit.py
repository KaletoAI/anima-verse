"""``fit_refit`` — every fit a version bump made stale, refitted at idle time
on the CPU (spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md
§ 6.2). Never a hub job: ``needs_media`` is False, so the entry keeps running
with the media switch off.

One candidate per character — the boot sweep's unit of work:
``garment_refit.refit_character`` takes the character's run lock and does
everything of one character in order (base fits, too-small retries, body
fits, footwear fits and insole re-analyses); ``outfit_bodies.
match_stale_postures`` runs first, as in the sweep. The label carries what
the read-only listers found.

A refused refit is recorded by the sweep's own bookkeeping
(``garments._note_outcome`` / ``record_body_failure``) and the old fit stays
served (R11): the step is done. The old fit record stays ``accepted`` with its
old ``fit_version``, so the listers keep naming it; this type leaves out
every entry whose fit holds a persisted failure that automatic triggers honour
(``garment_store.chain_failure`` on the current base / ``body_failure`` on the
body as stored). Only the explicit paths (the Wardrobe) spend such a fit
again, as everywhere else. The too-small refusals of ``refused_fits`` /
``refused_body_fits`` ARE failure records; they are listed by those listers
until their one widened retry stamps them.

The key is ``character:<name>:<token>``; the token (``version_token``) is
what the listers compare the stored records against: the code versions
(``garment_fit.FIT_VERSION``, ``SCALE_RETRY_VERSION``,
``footwear_insole.INSOLE_VERSION``, ``outfit_body_posture.
POSTURE_MATCH_VERSION``) and the current base model. A standing entry
therefore offers a character again after a version bump or a new base made
its fits stale AGAIN, never while those stay (the face_cleanup_rerun
pattern). Not covered: a refusal recorded later under the same versions and
base (an explicit Wardrobe run) — the boot sweep retries it. A key of the
older shape ``character:<name>`` still parses (``_name``).
"""
import hashlib
import json
from typing import Any, Dict, List, Tuple

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects

# A unit of work: (item id, body id) — body "" = the base model; item "" =
# the posture of the outfit body.
_Work = Tuple[str, str]


def _base_failed(name: str, item_id: str, fsig: str, base_sha: str) -> bool:
    """The item's fsig carries a persisted failure automatic triggers honour."""
    from app.core import garment_store as gs
    return gs.chain_failure(name, item_id, fsig, base_model_sha=base_sha) is not None


def _body_failed(name: str, item_id: str, kind: str, fsig: str, body_id: str, base_sha: str,
                 profile: Dict[str, Any]) -> bool:
    """The fit on the outfit body carries a failure that still holds (the same
    body, base fit and fit version — ``garment_store.body_failure``). A shoe is
    fitted on the body directly, its failure names no base fit."""
    from app.core import garment_fit, garment_set, garments, garment_store as gs
    base_fit_sha = ""
    version = garment_fit.FIT_VERSION.get(kind)
    if kind != garment_set.FOOTWEAR:
        hit = gs.accepted_fit(name, item_id, base_model_sha=base_sha, profile=profile)
        if hit is None:
            return False
        base_fit_sha = garments._sha(hit[0])
        version = garment_fit.expected_fit_version(hit[1])
    return gs.body_failure(name, item_id, fsig, body_id, body_sha=garments.body_sha256(name, body_id),
                           base_fit_sha=base_fit_sha, fit_version=version) is not None


def _units(name: str, profile: Dict[str, Any]) -> List[_Work]:
    """What the sweep would refit for the character and the improvement may
    spend: the union of the read-only listers in sweep order, deduplicated,
    without the fits a persisted failure holds back (see the module
    docstring)."""
    from app.core import base_body, garment_refit, garment_store as gs, outfit_bodies
    base = base_body.current_base(name, profile=profile)
    base_sha = str(base[1] or "") if base else ""
    units: List[_Work] = []

    def add(unit: _Work) -> None:
        if unit not in units:
            units.append(unit)

    for item_id, _kind, fsig, _method in garment_refit.outdated_fits(name, profile=profile):
        if not _base_failed(name, item_id, fsig, base_sha):
            add((item_id, ""))
    for item_id, _kind, _fsig, _method in garment_refit.refused_fits(name, profile=profile):
        add((item_id, ""))
    for item_id, kind, fsig, body_id in garment_refit.outdated_body_fits(name, profile=profile):
        if not _body_failed(name, item_id, kind, fsig, body_id, base_sha, profile):
            add((item_id, body_id))
    for item_id, _kind, _fsig, body_id in garment_refit.refused_body_fits(name, profile=profile):
        add((item_id, body_id))
    for item_id, _old, current in garment_refit.outdated_footwear_fits(name, profile=profile):
        if not _base_failed(name, item_id, current, base_sha):
            add((item_id, ""))
    for item_id in garment_refit.outdated_footwear_sources(name, profile=profile):
        try:
            fsig = gs.garment_fsig(name, item_id, profile=profile)
        except ValueError:
            continue
        if not _base_failed(name, item_id, fsig, base_sha):
            add((item_id, ""))
    for body_id in outfit_bodies.stale_posture_bodies(name, profile=profile):
        add(("", body_id))
    return units


def _work(name: str, profile: Dict[str, Any]) -> List[str]:
    """``_units`` as labels: ``<item>``, ``<item>@<body>`` for a fit on an
    outfit body, ``posture@<body>`` for a stale posture (the sweep's words)."""
    out: List[str] = []
    for item_id, body_id in _units(name, profile):
        label = subjects.item_name(item_id) if item_id else "posture"
        out.append(f"{label}@{body_id}" if body_id else label)
    return out


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _name(key: str) -> str:
    """``character:<name>[:<token>]`` → ``name`` (a name holds no ":")."""
    return key.split(":")[1]


def version_token(name: str, profile: Dict[str, Any]) -> str:
    """12 hex over the versions the listers compare and the current base model's sha."""
    from app.core import base_body, footwear_insole, garment_fit, outfit_body_posture
    base = base_body.current_base(name, profile=profile)
    inputs = [garment_fit.FIT_VERSION, garment_fit.SCALE_RETRY_VERSION, footwear_insole.INSOLE_VERSION,
              outfit_body_posture.POSTURE_MATCH_VERSION, str(base[1] or "") if base else ""]
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _names(params: Dict[str, Any]) -> List[str]:
    """The pipeline roster (a ready base model), narrowed to the chosen one."""
    wanted = params.get("character") or ""
    return [n for n in subjects.pipeline_characters() if not wanted or n == wanted]


class FitRefit(ImprovementType):
    id = "fit_refit"
    label = "Refit stale fits (CPU)"
    needs_media = False

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField("character", "Character", "enum",
                           [{"value": "", "label": "All characters"}] +
                           [{"value": n, "label": n} for n in subjects.characters()], required=False)]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        out: List[Candidate] = []
        for name in _names(params):
            profile = _profile(name)
            work = _work(name, profile)
            if not work:
                continue
            n = len(work)
            out.append(Candidate(f"character:{name}:{version_token(name, profile)}",
                                 f"{name} · {n} fit{'' if n == 1 else 's'}: {', '.join(work)}",
                                 hub_jobs=0, note="CPU only — no hub job"))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name = _name(candidate.key)
        return not _work(name, _profile(name))

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import garment_refit, outfit_bodies, refit_pool
        name = _name(candidate.key)
        # A garment chain of the character runs or waits: load, and nothing
        # is touched — the posture match below refits garments on the body.
        if garment_refit._busy(name):
            raise CandidateBusy(f"{name}: garment run in progress")
        # The sweep's order: stale postures first (the bodies are turned and
        # their garments refitted inside), then the character's fits — one
        # tracked CPU task, like the sweep's (Game-Admin's header).
        busy: List[bool] = []

        def run():
            postures = outfit_bodies.match_stale_postures(name)
            done = garment_refit.refit_character(name)
            if done is None:
                # The chain started meanwhile: busy. Posture work that was done keeps its row (review 01#6).
                busy.append(True)
                return [f"posture@{body_id}" for body_id in postures] or None
            return done
        try:
            garment_refit.tracked(name, run)
        except refit_pool.RefitInterrupted as e:
            # The refit pool ended the run (the server stops): no defect of the subject — it stays due.
            raise CandidateBusy(f"{name}: {e}") from e
        if busy:
            raise CandidateBusy(f"{name}: garment run in progress")
