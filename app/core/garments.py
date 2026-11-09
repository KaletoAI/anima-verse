"""Garment chain orchestration — runs a character's own-mesh garment through
its steps, fits it onto the base body and starts the assembly (plan
``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R3, R8, R10,
R11, R13, R14, Task 8).

Steps of a kind (``garment_store.GARMENT_STEPS``; hair: ``haired → ghost →
cutout → mesh → fit``, clothing — an own-mesh outfit piece, plan
``2026-11-09-base-body-phase5-mesh-items.md``: ``worn → ghost → cutout → mesh
→ fit``). Every step caches its accepted output on disk under
the garment fingerprint ``fsig`` (R13), so a run starts at the first step
whose accepted output is missing — or at an explicit step. A step that
produced new output makes every later step run again (``force`` propagates
downstream); one that was served from the cache does not.

- image steps (``garment_images``): per view, the BACK first
  (``EDIT_VIEW_ORDER``): the back view sees how long the hair is, the front
  only guesses it (its ends hang behind the body). The kind's pair step
  (``PAIR_STEP`` of its module, ``garment_images.kind_module``; both kinds:
  ``ghost``) additionally needs front and back to agree (``pair_agree``:
  hair — the hair ends at the same height, ``bottoms_agree``; clothing — the
  hems, ``hems_agree``): a front attempt is gated against the accepted back
  (``_pair_check``), and a pair that still disagrees — a new back, or both
  views from before — renders the front again against the back, with its own
  attempts. A disagreeing pair never ends a run without a new attempt. The
  kind's ``front_hints`` give the front edit what the back shows (hair: where
  the accepted haired back's hair ends, ``garment_images.haired_length``, as
  a length phrase in the hair-only front prompt; clothing: nothing);
- every image step checks after each view that the run's inputs (base views,
  the kind's description: ``garment_fsig``) did not change meanwhile — a base view
  regenerated during the run refuses with ``INPUTS_CHANGED_ERROR`` instead of
  gating images of the new base against images of the old one;
- ``mesh`` (``garment_mesh.generate``): built from both cut-outs; a new
  accepted image deletes the prepared mesh of the same fsig (it was built
  from the replaced images);
- ``fit``: the CURRENT base model (rigged + unrigged, read under the
  publication lock), the kind's fit and gate (hair ``garment_fit.fit_hair`` /
  ``GATES``, clothing ``garment_fit.fit_clothing`` / ``CLOTHING_GATES`` with
  the piece's slots). On acceptance the
  fit GLB ``garments/{item}_{fsig}.glb`` (= the rigged base with the garment
  grafted on) and its record are written, the distance tier is decimated to
  ``low/``, and the assembly of the served outfit model is scheduled.

A refusal ends the run (``{ok: False, step, error, gates}`` + the in-memory
status); nothing downstream runs, and an already accepted fit keeps being
served (R11 — a refused re-run never makes the figure bald).

Hair made by HairDeck (``garment_hair.hair_method``; plan
``docs/superpowers/plans/2026-11-09-hairdeck-hair.md``, Task 4) runs
``hairdeck → fit`` instead (``garment_store.steps_for``):

- ``hairdeck``: ``generate_hair`` on the profile picture, seed 42, into the
  job folder ``raw/{item}_{hsig}/`` (cached per ``hsig``, so a base or colour
  change runs only the fit). A forced regenerate replaces the job with the
  next seed after the highest one the record has seen (43, 44, …), so it
  gives a new result. A job whose ``info.json`` notes "no hair found"
  or "no person found" refuses with ``NO_HAIR_ERROR``;
- ``fit``: ``garment_hairdeck.fit_hairdeck`` on the current rigged base, with
  the colour override (profile ``hair_colour``) or HairDeck's own colours.
  A gate refusal of the attempt-1 job re-runs ``hairdeck`` once with that
  job's seed + 1 and fits again; a second refusal refuses with both attempts.

The served fit follows the CURRENT method (``garment_store.accepted_fit``): a
switch never generates anything, and a method without an accepted fit yet
serves no hair.

One run per character at a time (``garment_store.char_lock``); ``run_garment``
blocks and is called from a worker thread (``start_garment``) — every
generation inside goes through the image service, the fit and the graft are
CPU work on that thread. No profile lock is held across a step.
"""
import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("garments")

#: The ``running_step`` of a run that has been started but not reached a step yet.
QUEUED = "queued"

_lock = threading.Lock()
# Characters with a ``start_garment`` worker (started or running).
_active: set = set()
# Characters whose base model changed while their worker ran: once it ends,
# ``after_base_model`` checks again (the run may have used the old model).
_followups: set = set()
_ORDINALS = ("first", "second", "third")
#: The seed of the first HairDeck job of an hsig. A forced regenerate takes
#: the next seed after the highest one the job record has seen
#: (``_next_seed``); the refused-fit retry takes the attempt's seed + 1.
HAIRDECK_FIRST_SEED = 42
#: HairDeck jobs per run: the job and one retry after a refused fit.
HAIRDECK_ATTEMPTS = 2
#: ``info.json`` notes of a HairDeck job that found nothing to make hair of.
NO_HAIR_NOTES = ("no hair found", "no person found")
NO_HAIR_ERROR = "HairDeck found no hair in the profile picture"
#: The view order of the edit steps: the back first, it gives the front its length.
EDIT_VIEW_ORDER: Tuple[str, ...] = ("back", "front")
INPUTS_CHANGED_ERROR = ("The base views or the garment's description changed during the run "
                        "— run the chain again to start from the new ones")


class _Refused(Exception):
    """A gate of the orchestration itself refused (bottoms, fit)."""

    def __init__(self, step: str, error: str, gates: Any):
        super().__init__(error)
        self.step, self.error, self.gates = step, error, gates


# --- Item and kind ------------------------------------------------------------

def _item(character_name: str, item_id: str) -> Tuple[Dict[str, Any], str]:
    """``(item, kind)`` of a garment item of the character; ValueError for
    anything else. A hair garment must be OWNED by the character
    (``item.owner``); an own-mesh outfit piece (kind ``clothing``,
    ``garment_set``) must be HELD or worn by it — the flag is on the item,
    every wearer gets a fit of their own."""
    from app.core import garment_set
    from app.core.garment_store import GARMENT_VERSION
    from app.models.inventory import get_item
    item = get_item(item_id) if isinstance(item_id, str) and item_id else None
    if item and garment_set.garment_kind_of(item) == garment_set.CLOTHING:
        if not garment_set.holds(character_name, item_id):
            raise ValueError(f"{item_id} is not a garment of {character_name}")
        return item, garment_set.CLOTHING
    if not item or item.get("category") != "garment":
        raise ValueError(f"{str(item_id)[:80]!r} is no garment item")
    kind = str((item.get("garment") or {}).get("kind") or "")
    if kind not in GARMENT_VERSION:
        raise ValueError(f"Unknown garment kind {kind!r}")
    if (item.get("owner") or "").strip() != character_name:
        raise ValueError(f"{item_id} is not a garment of {character_name}")
    return item, kind


def _steps(steps: Union[None, str, Iterable[str]], order: Tuple[str, ...]) -> Optional[List[str]]:
    if steps is None:
        return None
    wanted = [steps] if isinstance(steps, str) else list(steps)
    if not wanted:
        return None
    for step in wanted:
        if step not in order:
            raise ValueError(f"Unknown garment step {step!r}")
    return wanted


def _kind_inputs(kind: str, character_name: str, profile: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    from app.core import garment_store
    return garment_store._kind_inputs(kind, character_name, profile, item_id)


def _refresh_description(character_name: str, item: Dict[str, Any], kind: str,
                         profile: Dict[str, Any]) -> None:
    """R3, hair only: the item's ``prompt_fragment`` follows the derived
    description on every run; a description that became empty ends the run.
    Any other kind keeps its fragment — a clothing piece's is the user's."""
    from app.core.garment_hair import HAIR_KIND
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    if kind != HAIR_KIND:
        return
    description = str(_kind_inputs(kind, character_name, profile, item["id"]).get("description") or "")
    if not description:
        raise ValueError("No hair set — fill in the hair in Appearance")
    if (item.get("prompt_fragment") or "") == description:
        return
    with keyed_lock("garment_item", character_name):
        if inventory.update_item(item["id"], {"prompt_fragment": description}) is None:
            raise RuntimeError(f"Could not refresh the garment item {item['id']}")


# --- Step state ---------------------------------------------------------------

def _sha(path: Optional[Path]) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


def _image(character_name: str, item_id: str, fsig: str, step: str, view: str, attempt: int = 0) -> Path:
    from app.core.garment_store import garment_path
    return garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=attempt)


def _accepted(path: Path) -> bool:
    from app.core.garment_store import read_record
    return path.is_file() and read_record(path.with_suffix(".json")).get("accepted") is True


def _accepted_gate(path: Path) -> Optional[Dict[str, Any]]:
    """The gate record of the attempt an accepted image came from."""
    from app.core.garment_store import read_record
    record = read_record(path.with_suffix(".json"))
    try:
        ordinal = _ORDINALS[int(record.get("attempt") or 0) - 1]
    except (IndexError, TypeError, ValueError):
        return None
    gate = (record.get("gates") or {}).get(ordinal)
    return gate if isinstance(gate, dict) else None


def _kind_module(kind: str):
    from app.core.garment_images import kind_module
    return kind_module(kind)


def _pair(character_name: str, item_id: str, kind: str, fsig: str) -> Tuple[bool, Dict[str, Any]]:
    """Whether the accepted images of both views of the kind's pair step agree
    (the kind module's ``pair_agree``: hair ends / hems at the same height),
    with both gate records."""
    module = _kind_module(kind)
    gates = {view: _accepted_gate(_image(character_name, item_id, fsig, module.PAIR_STEP, view))
             for view in ("front", "back")}
    if not gates["front"] or not gates["back"]:
        return False, gates
    return module.pair_agree(gates["front"], gates["back"]), gates


def _pair_check(character_name: str, item_id: str, kind: str, fsig: str):
    """The pair check of a FRONT attempt of the pair step: against the
    accepted back's gate record (the kind module's ``pair_reason``)."""
    module = _kind_module(kind)
    back = _accepted_gate(_image(character_name, item_id, fsig, module.PAIR_STEP, "back")) or {}
    return lambda record: module.pair_reason(record, back)


def _front_hints(character_name: str, item_id: str, fsig: str, kind: str, step: str,
                 view: str) -> Optional[Dict[str, Any]]:
    """The prompt hints of an edit from what the back shows (the kind
    module's ``front_hints``; hair: the length for the hair-only front)."""
    return _kind_module(kind).front_hints(character_name, item_id, fsig, step, view)


def _inputs_unchanged(character_name: str, item_id: str, fsig: str, step: str) -> None:
    """``_Refused`` when the fsig of the run is no longer the current one."""
    from app.core.garment_store import garment_fsig
    if garment_fsig(character_name, item_id) != fsig:
        raise _Refused(step, INPUTS_CHANGED_ERROR, None)


def _mesh_done(character_name: str, item_id: str, fsig: str) -> bool:
    from app.core.garment_store import garment_path
    return _accepted(garment_path(character_name, item_id, fsig, "prepared"))


def _fit_state(character_name: str, item_id: str, fsig: str, base_model_sha: str,
               method: str = "edit_chain") -> str:
    """``accepted`` (on the current base model, from the current prepared
    mesh — HairDeck: from the current job's hair), ``stale`` (accepted on
    another base model), ``outdated`` (accepted, but the prepared mesh /
    HairDeck hair it was fitted from was replaced or removed) or
    ``missing``."""
    from app.core.garment_store import HAIRDECK, garment_path, read_record
    fit = garment_path(character_name, item_id, fsig, "fit")
    record = read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    if not base_model_sha or record.get("base_model_sha256") != base_model_sha:
        return "stale"
    if method == HAIRDECK:
        inputs = record.get("inputs") or {}
        try:
            nohead, _proxy = _hairdeck_files(character_name, item_id, str(inputs.get("hsig") or ""))
        except ValueError:
            return "outdated"
        if nohead is None or inputs.get("nohead_sha256") != _sha(nohead):
            return "outdated"
        return "accepted"
    prepared = garment_path(character_name, item_id, fsig, "prepared")
    if (record.get("inputs") or {}).get("prepared_sha256") != _sha(prepared) or not prepared.is_file():
        return "outdated"
    return "accepted"


def _done(character_name: str, item_id: str, kind: str, fsig: str, step: str, base_model_sha: str,
          method: str = "edit_chain", hsig: str = "") -> bool:
    from app.core.garment_store import GARMENT_VIEWS, IMAGE_STEPS
    if step in IMAGE_STEPS:
        if not all(_accepted(_image(character_name, item_id, fsig, step, v)) for v in GARMENT_VIEWS):
            return False
        return step != _kind_module(kind).PAIR_STEP or _pair(character_name, item_id, kind, fsig)[0]
    if step == "mesh":
        return _mesh_done(character_name, item_id, fsig)
    if step == "hairdeck":
        return _hairdeck_files(character_name, item_id, hsig)[0] is not None
    if step == "fit":
        return _fit_state(character_name, item_id, fsig, base_model_sha, method) == "accepted"
    return False


# --- HairDeck job ---------------------------------------------------------------

def _hairdeck_record(character_name: str, item_id: str, hsig: str) -> Dict[str, Any]:
    from app.core import garment_store as gs
    return gs.read_record(gs.hairdeck_dir(character_name, item_id, hsig) / gs.HAIRDECK_RECORD)


def _hairdeck_files(character_name: str, item_id: str, hsig: str) -> Tuple[Optional[Path], Optional[Path]]:
    """``(hair, proxy)`` of the ACCEPTED HairDeck job of ``hsig`` —
    ``hair_seed<s>_nohead.glb`` and ``hair_seed<s>.glb`` of the record's seed
    — or ``(None, None)`` without an accepted job or with a file missing.
    ValueError for an invalid hsig."""
    from app.core import garment_store as gs
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    record = gs.read_record(folder / gs.HAIRDECK_RECORD)
    if record.get("accepted") is not True:
        return None, None
    try:
        seed = int(record.get("seed"))
    except (TypeError, ValueError):
        return None, None
    hair, proxy = folder / f"hair_seed{seed}_nohead.glb", folder / f"hair_seed{seed}.glb"
    return (hair, proxy) if hair.is_file() and proxy.is_file() else (None, None)


def _no_hair(notes: List[str]) -> bool:
    return any(phrase in note.lower() for note in notes for phrase in NO_HAIR_NOTES)


def _job_seeds(record: Dict[str, Any]) -> List[int]:
    """Every seed the job record of an hsig has seen (``seeds`` + ``seed``)."""
    out = set()
    for value in [*(record.get("seeds") or []), record.get("seed")]:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _next_seed(record: Dict[str, Any]) -> int:
    """The seed of a forced regenerate: one after the highest seed the job
    record has seen, ``HAIRDECK_FIRST_SEED`` without a job (42 -> 43 -> 44 …)."""
    seeds = _job_seeds(record)
    return seeds[-1] + 1 if seeds else HAIRDECK_FIRST_SEED


def _run_hairdeck(character_name: str, item_id: str, hsig: str, profile: Dict[str, Any], attempt: int,
                  seed: int, fit_attempts: Optional[List[Any]] = None) -> Path:
    """Run HairDeck with ``seed`` (``attempt`` 1 = the job, 2 = the retry
    after a refused fit) on the profile picture into the job folder of
    ``hsig`` — replacing the job there — and write its record ``{accepted,
    attempt, seed, seeds (every seed of the hsig so far), notes, error,
    ...}``. The hsig does not depend on the seed. The job lands in
    a staging folder first; the record says ``accepted: False`` while the
    files move in, so a crash never leaves an accepted record over half a
    job. ``_Refused`` (step ``hairdeck``, ``NO_HAIR_ERROR``) when ``info.json``
    notes no hair / no person; RuntimeError when the hair or proxy file is
    missing from the result. Returns the job folder."""
    import json as _json
    import shutil
    from app.core import base_body
    from app.core import garment_store as gs
    from app.core.model_refs import current_profile_image
    from app.core.timeutils import utc_now_iso
    from app.imagegen import service
    image = current_profile_image(character_name, profile=profile)
    if image is None:
        raise base_body.MissingInput("No profile picture — HairDeck makes the hair from it")
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    seeds = sorted(set(_job_seeds(gs.read_record(folder / gs.HAIRDECK_RECORD))) | {int(seed)})
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = folder.parent / f".{folder.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        result = service.get_image_service().generate_hair(
            str(image), str(staging), character_name=character_name, params={"seed": seed})
        names = [str(f.get("name") or "") for f in result.get("files") or []]
        try:
            info = _json.loads((staging / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        notes = [str(n) for n in (info.get("notes") or [])] if isinstance(info, dict) else []
        record: Dict[str, Any] = {
            "accepted": False, "attempt": attempt, "seed": seed, "seeds": seeds, "notes": notes,
            "error": "moving files",
            "files": names, "backend": result.get("backend"), "job_id": result.get("job_id"),
            "route": result.get("route"), "profile_image_sha256": _sha(image),
            "fit_attempts": list(fit_attempts or []), "created_at": utc_now_iso()}
        folder.mkdir(exist_ok=True)
        gs.write_record(folder / gs.HAIRDECK_RECORD, record)
        for path in sorted(staging.iterdir()):
            if path.is_file():
                os.replace(path, folder / path.name)
        error: Optional[str] = None
        if _no_hair(notes):
            error = NO_HAIR_ERROR
        else:
            for name in (f"hair_seed{seed}_nohead.glb", f"hair_seed{seed}.glb"):
                if not (folder / name).is_file():
                    error = f"HairDeck delivered no {name}"
                    break
        record.update(accepted=error is None, error=error)
        gs.write_record(folder / gs.HAIRDECK_RECORD, record)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info("HairDeck %s/%s (%s): attempt %s seed %s, %s files, %s", character_name, item_id, hsig,
                attempt, seed, len(names), error or "accepted")
    if error == NO_HAIR_ERROR:
        raise _Refused("hairdeck", NO_HAIR_ERROR, {"notes": notes, "attempt": attempt, "seed": seed})
    if error:
        raise RuntimeError(error)
    return folder


def _drop_mesh(character_name: str, item_id: str, fsig: str) -> None:
    """New images replace the input of the mesh step: its raw + prepared mesh
    of this fsig go. The fit stays — it keeps being served until a new one is
    accepted (R11) and reads as ``outdated`` meanwhile."""
    from app.core.garment_store import garment_path
    for part in ("raw", "prepared"):
        path = garment_path(character_name, item_id, fsig, part)
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


# --- The fit step ---------------------------------------------------------------

def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _fit(character_name: str, item_id: str, kind: str, fsig: str, bsig: str,
         profile: Dict[str, Any]) -> Path:
    """Fit the prepared mesh onto the current base model and store it (see
    the module docstring). ``_Refused`` when the fit gate refuses."""
    from app.core import base_body, garment_fit
    from app.core import garment_images as gi
    from app.core.garment_store import GARMENT_VIEWS, garment_path
    from app.core.model_refs import find_ref_image, get_model_refs_dir, neutral_view_reference
    from app.core.timeutils import utc_now_iso

    prepared = garment_path(character_name, item_id, fsig, "prepared")
    if not _accepted(prepared):
        raise base_body.MissingInput("The garment mesh is missing — run the mesh step first")
    ghost = _image(character_name, item_id, fsig, "ghost", "front")
    if not _accepted(ghost):
        raise base_body.MissingInput("The ghost front image is missing — run the ghost step first")
    base_views = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in GARMENT_VIEWS}
    if base_views["front"] is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    base_sha = hashlib.sha256(snapshot["rigged"]).hexdigest()
    prepared_bytes = prepared.read_bytes()
    # Masks in the frame of the bald front view the unrigged base was built
    # from (R6: the full-frame ghost mask, never the cut-out).
    with neutral_view_reference(base_views["front"], get_model_refs_dir(character_name)) as flat:
        size = gi._image_size(flat)
        bald_mask = gi._mask(flat, size)
    ghost_mask = gi._mask(ghost, size)
    from app.core import garment_set
    if kind == garment_set.CLOTHING:
        from app.models.inventory import get_item
        slots = list(((get_item(item_id) or {}).get("outfit_piece") or {}).get("slots") or [])
        result = garment_fit.fit_clothing(prepared_bytes, snapshot["unrigged"], snapshot["rigged"],
                                          masks={"body": bald_mask, "garment": ghost_mask}, slots=slots)
        limits = garment_fit.CLOTHING_GATES
    else:
        result = garment_fit.fit_hair(prepared_bytes, snapshot["unrigged"], snapshot["rigged"], bald_mask,
                                      ghost_mask)
        limits = garment_fit.GATES
    gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
             "limits": {key: [kind_, limit] for key, (kind_, limit, _label) in limits.items()}}
    if not result.ok:
        raise _Refused("fit", "fit refused — " + "; ".join(result.reasons),
                       {**gates, "metrics": result.metrics})

    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig,
        "metrics": result.metrics, "gates": gates, "report": result.report,
        "base_signature": bsig, "base_model_sha256": base_sha,
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": {v: _sha(p) for v, p in base_views.items()},
                   "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
                   "ghost_front_sha256": _sha(ghost)},
        "created_at": utc_now_iso()}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def _publish_fit(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, rigged: bytes,
                 result: Any, record: Dict[str, Any]) -> Path:
    """Graft an accepted fit onto the rigged base, write the fit GLB and its
    ``record``, decimate the distance tier to ``low/`` and schedule the
    assembly. Shared by both hair methods."""
    from app.blender import refine
    from app.core import glb_mesh
    from app.core.garment_store import garment_path, write_record
    blob = glb_mesh.graft(rigged, result.garment, name=f"garment_{kind}_{item_id}",
                          extras={"kind": kind, "item_id": item_id, "fsig": fsig})
    fit = garment_path(character_name, item_id, fsig, "fit")
    low = garment_path(character_name, item_id, fsig, "low")
    # A distance tier of the previous fit must never pair with the new one.
    low.unlink(missing_ok=True)
    _write_atomic(fit, blob)
    write_record(fit.with_suffix(".json"), record)
    logger.info("Garment fit %s/%s (%s): accepted on %s, %s tris", character_name, item_id, fsig, bsig,
                result.metrics.get("tris"))

    tris = len(glb_mesh.static_arrays(blob)[1])
    target = max(1, int(round(refine.lod_ratio("character") * tris)))
    try:
        dec = refine.decimate_to(fit, target, low)
    except Exception as e:  # noqa: BLE001 — the distance tier falls back to the full fit
        dec = {"ok": False, "error": str(e) or type(e).__name__}
    if dec.get("ok"):
        record["low"] = {"ok": True, "tris": dec.get("tris"), "ratio": dec.get("ratio")}
    else:
        logger.warning("Garment fit %s/%s: distance tier failed: %s", character_name, item_id, dec.get("error"))
        record["low"] = {"ok": False, "error": dec.get("error") or "decimation failed"}
    write_record(fit.with_suffix(".json"), record)
    from app.core import garment_assembly
    garment_assembly.schedule(character_name)
    return fit


def _placement_summary(placement: Any) -> Optional[Dict[str, Any]]:
    """The fit record's ``placement``: what the fit's ``report.placement`` applied (forward/tilt and where they
    came from) and the hairline it reached against its target. None without a report section."""
    if not isinstance(placement, dict):
        return None
    keys = ("forward_m", "forward_source", "tilt_deg", "tilt_source", "tilt_solve", "hairline_target_y")
    return {**{k: placement.get(k) for k in keys}, "hairline_y": placement.get("hairline_pushed_y")}


def _fit_hairdeck(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, hsig: str,
                  profile: Dict[str, Any], refused: List[Dict[str, Any]]) -> Path:
    """Fit the accepted HairDeck job of ``hsig`` onto the current base model
    (``garment_hairdeck.fit_hairdeck``; colour = the profile's override, else
    HairDeck's own; placement = the profile's manual forward/tilt, else
    automatic) and store it. ``_Refused`` (step ``fit``) when the gate
    refuses — its gates carry ``{attempt, seed, ok, reasons, limits,
    metrics}``. ``refused``: the earlier refused attempts, kept in the
    record."""
    from app.core import base_body, garment_hair, garment_hairdeck
    from app.core.garment_store import GARMENT_VIEWS, HAIRDECK
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    hair, proxy = _hairdeck_files(character_name, item_id, hsig)
    if hair is None or proxy is None:
        raise base_body.MissingInput("The HairDeck hair is missing — run the hairdeck step first")
    job = _hairdeck_record(character_name, item_id, hsig)
    attempt, seed = int(job.get("attempt") or 1), job.get("seed")
    base_views = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in GARMENT_VIEWS}
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    base_sha = hashlib.sha256(snapshot["rigged"]).hexdigest()
    hair_bytes, proxy_bytes = hair.read_bytes(), proxy.read_bytes()
    override = garment_hair.hair_colour_override(profile)
    placement = garment_hair.hair_placement(profile)
    result = garment_hairdeck.fit_hairdeck(hair_bytes, proxy_bytes, snapshot["rigged"],
                                           colour_target=garment_hair.colour_target(override), **placement)
    gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
             "limits": {key: [kind_, limit] for key, (kind_, limit, _label) in garment_hairdeck.GATES.items()}}
    if not result.ok:
        raise _Refused("fit", "fit refused — " + "; ".join(result.reasons),
                       {"attempt": attempt, "seed": seed, **gates, "metrics": result.metrics})
    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "method": HAIRDECK,
        "metrics": result.metrics, "gates": gates, "report": result.report,
        "base_signature": bsig, "base_model_sha256": base_sha,
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": {v: _sha(p) for v, p in base_views.items()},
                   "hsig": hsig, "attempt": attempt, "seed": seed, "colour": override,
                   "placement": placement,
                   "nohead_sha256": hashlib.sha256(hair_bytes).hexdigest(),
                   "proxy_sha256": hashlib.sha256(proxy_bytes).hexdigest()},
        "colour": {"target": override or None, "source": "override" if override else "hairdeck"},
        "placement": _placement_summary(result.report.get("placement")),
        "refused_attempts": list(refused),
        "created_at": utc_now_iso()}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def _hairdeck_fit_step(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, hsig: str,
                       profile: Dict[str, Any], ran: List[str]) -> Path:
    """The ``fit`` step of HairDeck hair: fit; when the gate refuses the
    attempt-1 job, run ``hairdeck`` once more (the job's seed + 1) and fit again. A
    refusal of the last attempt refuses with every attempt's gates
    (``{attempts: [...]}``, also kept as ``fit_attempts`` in the job
    record)."""
    from app.core import garment_store as gs
    try:
        return _fit_hairdeck(character_name, item_id, kind, fsig, bsig, hsig, profile, [])
    except _Refused as e:
        first = e
    attempts = [first.gates]
    job = _hairdeck_record(character_name, item_id, hsig)
    attempt = int(job.get("attempt") or 1)
    retry_seed = int(job.get("seed") or HAIRDECK_FIRST_SEED) + 1
    if attempt >= HAIRDECK_ATTEMPTS:
        gs.write_record(gs.hairdeck_dir(character_name, item_id, hsig) / gs.HAIRDECK_RECORD,
                        {**job, "fit_attempts": attempts})
        raise _Refused("fit", first.error, {"attempts": attempts})
    logger.info("HairDeck fit %s/%s refused on attempt %s — HairDeck once more with seed %s",
                character_name, item_id, attempt, retry_seed)
    gs.start(character_name, item_id, "hairdeck")
    try:
        _run_hairdeck(character_name, item_id, hsig, profile, attempt + 1, retry_seed, fit_attempts=attempts)
    except _Refused:
        raise
    except Exception as e:  # noqa: BLE001 — reported as the hairdeck step's failure (it is the running step)
        raise _Refused("hairdeck", str(e) or type(e).__name__, None) from e
    gs.end(character_name, item_id, "hairdeck")
    if "hairdeck" not in ran:
        ran.append("hairdeck")
    gs.start(character_name, item_id, "fit")
    try:
        return _fit_hairdeck(character_name, item_id, kind, fsig, bsig, hsig, profile, attempts)
    except _Refused as e:
        attempts.append(e.gates)
        job = _hairdeck_record(character_name, item_id, hsig)
        gs.write_record(gs.hairdeck_dir(character_name, item_id, hsig) / gs.HAIRDECK_RECORD,
                        {**job, "fit_attempts": attempts})
        raise _Refused("fit", f"fit refused on both HairDeck attempts — {e.error}", {"attempts": attempts})


# --- The run --------------------------------------------------------------------

def run_garment(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
                view: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Run the garment chain of ``item_id`` (blocking, minutes; one run per
    character — waits for ``garment_store.char_lock``).

    ``steps`` None: from the first step whose accepted output for the current
    fsig is missing (the fit counts as missing on another base model or from
    a replaced prepared mesh). A step name (or several): from the earliest of
    them; with ``force`` that step re-runs — only for ``view`` when given —
    and every later step runs again. Without ``force`` a cached step is reused.

    The steps are those of the item's CURRENT method
    (``garment_store.steps_for``; hair by HairDeck: ``hairdeck``, ``fit``).

    Returns ``{ok: True, fsig, ran: [steps that produced output]}`` or
    ``{ok: False, fsig, step, error, gates}`` (also recorded as the item's
    failed status). ValueError for an invalid item, step or view."""
    from app.core.garment_store import GARMENT_VIEWS
    item, kind, order = _item_order(character_name, item_id)
    wanted = _steps(steps, order)
    if view is not None and view not in GARMENT_VIEWS:
        raise ValueError(f"Unknown garment view {view!r}")
    from app.core import garment_store as gs
    with gs.char_lock(character_name):
        return _run_locked(character_name, item, kind, wanted, view, bool(force))


def _item_order(character_name: str, item_id: str,
                profile: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str, Tuple[str, ...]]:
    """``(item, kind, steps of the current method)``; ValueError like ``_item``."""
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    item, kind = _item(character_name, item_id)
    if profile is None:
        profile = get_character_profile(character_name) or {}
    return item, kind, gs.steps_for(kind, gs.kind_method(kind, character_name, profile))


def _run_locked(character_name: str, item: Dict[str, Any], kind: str,
                wanted: Optional[List[str]], view: Optional[str], force: bool) -> Dict[str, Any]:
    from app.core import base_body, garment_images, garment_mesh
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    item_id = item["id"]
    profile = get_character_profile(character_name) or {}
    method = gs.kind_method(kind, character_name, profile)
    order = gs.steps_for(kind, method)
    step = order[0]  # a failure before the first step is that step's
    fsig = ""
    hsig = ""
    ran: List[str] = []
    try:
        # The method may have changed since the steps were checked.
        _steps(wanted, order)
        base = base_body.current_base(character_name, profile=profile)
        if base is None:
            raise ValueError(f"{character_name} is not on the base-body pipeline")
        bsig, base_sha = base
        _refresh_description(character_name, item, kind, profile)
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
        if method == gs.HAIRDECK:
            hsig = gs.garment_hsig(character_name, item_id, profile=profile)
        if wanted is None:
            first = next((s for s in order
                          if not _done(character_name, item_id, kind, fsig, s, base_sha, method, hsig)), None)
            if first is None:
                return {"ok": True, "fsig": fsig, "ran": []}
        else:
            first = min(wanted, key=order.index)
        pair_step = _kind_module(kind).PAIR_STEP if method == gs.EDIT_CHAIN else None
        dirty = False  # an earlier step produced new output: every later step runs again
        for step in order[order.index(first):]:
            forced = force and step == first
            gs.start(character_name, item_id, step)
            produced = False
            if step in gs.IMAGE_STEPS:
                views = gs.GARMENT_VIEWS if step == "cutout" else EDIT_VIEW_ORDER
                renders = [v for v in views
                           if (forced and (view is None or v == view))
                           or not _accepted(_image(character_name, item_id, fsig, step, v))]
                for v in renders:
                    f = forced and (view is None or v == view)
                    if step == "cutout":
                        garment_images.cut_out(character_name, item_id, fsig, v, force=f)
                    else:
                        # The back is done (accepted) before the front starts.
                        pair = (_pair_check(character_name, item_id, kind, fsig)
                                if step == pair_step and v == "front" else None)
                        garment_images.run_edit_step(character_name, item_id, fsig, step, v, force=f,
                                                     pair_check=pair,
                                                     prompt_hints=_front_hints(character_name, item_id, fsig,
                                                                               kind, step, v))
                    produced = True
                    # Right away: a refusal of the next view must not leave a
                    # mesh behind that was built from the replaced image.
                    _drop_mesh(character_name, item_id, fsig)
                    _inputs_unchanged(character_name, item_id, fsig, step)
                if step == pair_step and not _pair(character_name, item_id, kind, fsig)[0]:
                    # The back is the reference (the hair's length, the
                    # hem); the front renders again against it (two
                    # attempts; GateRefused when both miss).
                    garment_images.run_edit_step(character_name, item_id, fsig, step, "front", force=True,
                                                 pair_check=_pair_check(character_name, item_id, kind, fsig),
                                                 prompt_hints=_front_hints(character_name, item_id, fsig,
                                                                           kind, step, "front"))
                    produced = True
                    _drop_mesh(character_name, item_id, fsig)
                    _inputs_unchanged(character_name, item_id, fsig, step)
                    agree, gates = _pair(character_name, item_id, kind, fsig)
                    if not agree:
                        raise _Refused(step, _kind_module(kind).PAIR_REFUSED, gates)
            elif step == "mesh":
                f = forced or dirty
                if f or not _mesh_done(character_name, item_id, fsig):
                    garment_mesh.generate(character_name, item_id, fsig, force=f)
                    produced = True
            elif step == "hairdeck":
                if forced or not _done(character_name, item_id, kind, fsig, step, base_sha, method, hsig):
                    # A forced regenerate must give a NEW result: the next seed.
                    seed = (_next_seed(_hairdeck_record(character_name, item_id, hsig)) if forced
                            else HAIRDECK_FIRST_SEED)
                    _run_hairdeck(character_name, item_id, hsig, profile, 1, seed)
                    produced = True
            elif step == "fit":
                if forced or dirty or _fit_state(character_name, item_id, fsig, base_sha, method) != "accepted":
                    if method == gs.HAIRDECK:
                        _hairdeck_fit_step(character_name, item_id, kind, fsig, bsig, hsig, profile, ran)
                    else:
                        _fit(character_name, item_id, kind, fsig, bsig, profile)
                    produced = True
            gs.end(character_name, item_id, step)
            if produced:
                if step not in ran:
                    ran.append(step)
                dirty = True
        return {"ok": True, "fsig": fsig, "ran": ran}
    except garment_images.GateRefused as e:
        return _refusal(character_name, item_id, fsig, e.step, str(e),
                        {"view": e.view, "attempts": e.records}, ran)
    except garment_mesh.MeshGateRefused as e:
        # The prepared mesh of this fsig is gone (garment_mesh); an accepted
        # fit stays on disk and keeps being served (R11).
        return _refusal(character_name, item_id, fsig, "mesh", str(e), {"attempts": e.records}, ran)
    except garment_mesh.MeshAttemptFailed as e:
        # An attempt failed outright (no backend, worker crash, decimation):
        # the failure carries every attempt, an earlier refusal's numbers too.
        logger.warning("Garment run %s/%s failed at mesh: %s", character_name, item_id, e)
        return _refusal(character_name, item_id, fsig, "mesh", str(e), {"attempts": e.records}, ran)
    except _Refused as e:
        return _refusal(character_name, item_id, fsig, e.step, e.error, e.gates, ran)
    except Exception as e:  # noqa: BLE001 — reported as the step's failure
        logger.warning("Garment run %s/%s failed at %s: %s", character_name, item_id, step, e)
        return _refusal(character_name, item_id, fsig, step, str(e) or type(e).__name__, None, ran)


def _refusal(character_name: str, item_id: str, fsig: str, step: str, error: str, gates: Any,
             ran: List[str]) -> Dict[str, Any]:
    from app.core import garment_store as gs
    logger.info("Garment run %s/%s refused at %s: %s", character_name, item_id, step, error)
    gs.end(character_name, item_id, step, error=error, gates=gates)
    return {"ok": False, "fsig": fsig, "step": step, "error": error, "gates": gates, "ran": ran}


def check_run(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
              view: Optional[str] = None) -> None:
    """ValueError unless ``item_id`` is a garment of a known kind owned by
    the character and ``steps`` / ``view`` name steps of its current method
    and a view of it."""
    from app.core.garment_store import GARMENT_VIEWS
    _item_, _kind, order = _item_order(character_name, item_id)
    _steps(steps, order)
    if view is not None and view not in GARMENT_VIEWS:
        raise ValueError(f"Unknown garment view {view!r}")


def start_garment(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
                  view: Optional[str] = None, force: bool = False) -> bool:
    """Run ``run_garment`` in a worker thread. False when a run of the
    character is already going. The item counts as running (``queued``)
    from THIS moment (the UI polls). ValueError for an invalid item, step or
    view (checked before anything starts)."""
    from app.core import garment_store as gs
    check_run(character_name, item_id, steps=steps, view=view)
    with _lock:
        if character_name in _active:
            return False
        _active.add(character_name)
    gs.start(character_name, item_id, QUEUED)

    def run() -> None:
        followup = False
        error: Optional[str] = None
        try:
            run_garment(character_name, item_id, steps=steps, view=view, force=force)
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.error("Garment run %s/%s failed: %s", character_name, item_id, e)
            error = str(e) or type(e).__name__
        finally:
            # Ends the ``queued`` mark of a run that had nothing to do or
            # failed before its first step (a step replaces the mark).
            gs.end(character_name, item_id, QUEUED, error=error)
            with _lock:
                _active.discard(character_name)
                followup = character_name in _followups
                _followups.discard(character_name)
        if followup:
            after_base_model(character_name)

    try:
        threading.Thread(target=run, daemon=True, name=f"garment-{character_name}").start()
    except Exception:
        with _lock:
            _active.discard(character_name)
        gs.end(character_name, item_id, QUEUED)
        raise
    return True


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until no worker runs (smokes). True when idle."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if not _active:
                return True
        time.sleep(0.05)
    return False


# --- Triggers -------------------------------------------------------------------

def _worn_garments(character_name: str, profile: Dict[str, Any]) -> List[str]:
    worn = profile.get("equipped_mesh_pieces")
    if not isinstance(worn, dict):
        return []
    return sorted({str(v) for v in worn.values() if v})


def _ensure_hair(character_name: str, profile: Dict[str, Any]) -> bool:
    """Create and wear the hair item of a character on the pipeline that has
    hair text but no hair item at all — so the chain below starts without a
    click (R14; the phase-6 migration relies on it). A bald character gets
    no item; an item the character owns but does not wear (taken off in the
    Hair tab) is left off. True when an item was created."""
    from app.core import garment_hair
    if garment_hair.find_hair_item(character_name, profile) is not None:
        return False
    if not garment_hair.hair_description(character_name, profile=profile):
        return False
    try:
        item_id = garment_hair.ensure_hair_item(character_name)
    except (ValueError, RuntimeError) as e:
        logger.info("No hair item for %s after the base model: %s", character_name, e)
        return False
    logger.info("Hair item %s created for %s after the base model", item_id, character_name)
    return True


def after_base_model(character_name: str) -> bool:
    """R14: after a successful base model run, every worn garment whose fit
    is not accepted on the current base model gets a run — the whole chain
    when its fsig changed (new base signature or base images), the fit only
    when just the base model bytes changed (its images and mesh are cached
    under the unchanged fsig). A character with hair text but no hair item
    gets one first (``_ensure_hair``). True if a run was started. Never
    raises."""
    try:
        from app.core import base_body, garment_store as gs
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        base = base_body.current_base(character_name, profile=profile)
        if base is None:
            return False
        if _ensure_hair(character_name, profile):
            profile = get_character_profile(character_name) or {}
        started = False
        for item_id in _worn_garments(character_name, profile):
            try:
                _item(character_name, item_id)
                fsig = gs.garment_fsig(character_name, item_id, profile=profile)
                method = gs.garment_method(character_name, item_id, profile=profile)
            except ValueError:
                continue
            if _fit_state(character_name, item_id, fsig, base[1], method) == "accepted":
                continue
            if start_garment(character_name, item_id):
                logger.info("Garment %s/%s: base model changed, chain started", character_name, item_id)
                started = True
            else:
                with _lock:
                    if character_name in _active:
                        _followups.add(character_name)
        return started
    except Exception:  # noqa: BLE001 — a trigger never breaks the base model run
        logger.exception("Garment trigger after the base model of %s failed", character_name)
        return False


# --- Info -----------------------------------------------------------------------

def _url(character_name: str, item_id: str, tail: str, version: Any, extra: str = "") -> str:
    return (f"/characters/{quote(character_name, safe='')}/garments/{quote(item_id, safe='')}/{tail}"
            f"?v={version}{extra}")


def _stamp(path: Path) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _image_info(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Dict[str, Any]:
    from app.core.garment_images import ATTEMPTS
    from app.core.garment_store import read_record
    from app.core.model_refs import image_tile_meta
    final = _image(character_name, item_id, fsig, step, view)
    record = read_record(final.with_suffix(".json")) if final.is_file() else {}
    stamp = _stamp(final)
    attempts = []
    for n in range(1, ATTEMPTS + 1):
        path = _image(character_name, item_id, fsig, step, view, attempt=n)
        a_stamp = _stamp(path)
        if a_stamp is None:
            continue
        a_record = read_record(path.with_suffix(".json"))
        attempts.append({"attempt": n, "gate": a_record.get("gate"),
                         "url": _url(character_name, item_id, f"images/{step}/{view}", a_stamp, f"&attempt={n}"),
                         **image_tile_meta(path, a_record)})
    gates = record.get("gates")
    if not isinstance(gates, dict):
        gates = {_ORDINALS[i]: a["gate"] for i, a in enumerate(attempts) if a.get("gate") is not None}
    out = {"url": _url(character_name, item_id, f"images/{step}/{view}", stamp) if stamp is not None else None,
           "accepted": record.get("accepted") is True, "gates": gates, "attempts": attempts,
           **(image_tile_meta(final, record) if stamp is not None else {})}
    if step == "cutout" and record:
        out["upscale"] = record.get("upscale")
        out["side"] = record.get("side")
    return out


def _mesh_info(character_name: str, item_id: str, fsig: str) -> Dict[str, Any]:
    from app.core.garment_store import garment_path, read_record
    prepared = garment_path(character_name, item_id, fsig, "prepared")
    record = read_record(prepared.with_suffix(".json"))
    if prepared.is_file() and record.get("accepted") is True:
        status = "accepted"
    elif record:
        status = "refused"
    else:
        status = "missing"
    metrics = {k: record.get(k) for k in ("largest_component_share", "tris_raw", "tris_prepared", "ratio",
                                          "backend") if k in record}
    return {"status": status, "metrics": metrics, "gates": record.get("attempts") or [],
            "tris": record.get("tris_prepared"), "created_at": record.get("created_at")}


def _fit_info(character_name: str, item_id: str, fsig: str, base_model_sha: str,
              method: str = "edit_chain") -> Dict[str, Any]:
    from app.core.garment_store import garment_path, read_record
    record = read_record(garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
    metrics = record.get("metrics") or {}
    out = {"status": _fit_state(character_name, item_id, fsig, base_model_sha, method),
           "metrics": metrics, "gates": record.get("gates") or {}, "tris": metrics.get("tris"),
           "low": record.get("low"), "base_signature": record.get("base_signature"),
           "created_at": record.get("created_at")}
    if record.get("method"):
        out["colour"] = record.get("colour")
        out["refused_attempts"] = record.get("refused_attempts") or []
    return out


def _hairdeck_info(character_name: str, item_id: str, hsig: str) -> Dict[str, Any]:
    """The HairDeck job of ``hsig``: ``{hsig, status accepted|refused|missing,
    attempt, seed, notes, error, files, fit_attempts, created_at}``."""
    record = _hairdeck_record(character_name, item_id, hsig)
    if _hairdeck_files(character_name, item_id, hsig)[0] is not None:
        status = "accepted"
    elif record:
        status = "refused"
    else:
        status = "missing"
    return {"hsig": hsig, "status": status, "attempt": record.get("attempt"), "seed": record.get("seed"),
            "notes": record.get("notes") or [], "error": record.get("error"), "files": record.get("files") or [],
            "fit_attempts": record.get("fit_attempts") or [], "backend": record.get("backend"),
            "created_at": record.get("created_at")}


def _newest_fit(character_name: str, item_id: str,
                method: Optional[str] = None) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The newest accepted fit of the item on ANY base model (only fits made
    with ``method`` when given)."""
    from app.core import garment_store as gs
    root = gs._root(character_name)  # a read path never creates garments/
    best: Optional[Tuple[int, Path, Dict[str, Any]]] = None
    for (iid, _fsig), files in gs.stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = gs.read_record(path.with_suffix(".json"))
            if method is not None and gs.fit_method(record) != method:
                continue
            stamp = _stamp(path)
            if record.get("accepted") is True and stamp is not None and (best is None or stamp > best[0]):
                best = (stamp, path, record)
    return (best[1], best[2]) if best else None


def image_path(character_name: str, item_id: str, step: str, view: str, attempt: int = 0) -> Path:
    """The image file of one step/view (``attempt`` 0 = the final) under the
    CURRENT fsig — what ``garment_info``'s image URLs name. ValueError for an
    item that is no garment of the character, an unknown step/view, or a path
    outside ``garments/`` (``garment_store.garment_path``)."""
    from app.core import garment_store as gs
    _item(character_name, item_id)
    return _image(character_name, item_id, gs.garment_fsig(character_name, item_id), step, view, attempt)


def preview_path(character_name: str, item_id: str, method: str = "") -> Optional[Path]:
    """The GLB the Hair tab shows: the current-fsig fit when it exists, else
    the fit served on the current base model, else the newest accepted fit
    of the current method. None when there is no fit at all.

    ``method`` naming ANOTHER method than the current one: that method's
    newest accepted fit (on the current base model first, else on any) —
    the tab's "Other method" preview. ValueError for an unknown method."""
    from app.core import base_body, garment_store as gs
    from app.models.character import get_character_profile
    if method and method not in (gs.EDIT_CHAIN, gs.HAIRDECK):
        raise ValueError(f"unknown method {method[:40]!r}")
    profile = get_character_profile(character_name) or {}
    try:
        _item(character_name, item_id)
        current = gs.garment_method(character_name, item_id, profile=profile)
        if method and method != current:
            other = _other_fit(character_name, item_id, method, profile)
            return other[0] if other else None
        fit = gs.garment_path(character_name, item_id, gs.garment_fsig(character_name, item_id, profile=profile),
                              "fit")
    except ValueError:
        return None
    if fit.is_file():
        return fit
    base = base_body.current_base(character_name, profile=profile)
    served = gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile) if base else None
    if served:
        return served[0]
    newest = _newest_fit(character_name, item_id, current)
    return newest[0] if newest else None


def _other_fit(character_name: str, item_id: str, method: str,
               profile: Dict[str, Any]) -> Optional[Tuple[Path, Dict[str, Any], bool]]:
    """``(fit GLB, record, on the current base model)`` of the fit ``method``
    would serve if it were selected (``garment_store.accepted_fit`` with the
    method put into a profile copy: its current-fsig fit, else its newest
    accepted fit on the current base model), else its newest accepted fit on
    any base model; None without one."""
    from app.core import base_body, garment_store as gs
    base = base_body.current_base(character_name, profile=profile)
    if base and base[1]:
        hit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1],
                              profile={**profile, "hair_method": method})
        if hit and gs.fit_method(hit[1]) == method:
            return hit[0], hit[1], True
    hit = gs.newest_accepted_fits(character_name, item_id).get(method)
    return (hit[0], hit[1], False) if hit else None


def other_method_info(character_name: str, item_id: str, *,
                      profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The Hair tab's collapsed "Other method": the last result of the hair
    method NOT selected — ``{method, preview_url, created_at, metrics,
    colour, on_current_base}`` of its newest accepted fit — or None when that
    method has none (or the item is no hair)."""
    from app.core import garment_hair, garment_store as gs
    from app.core.http_files import content_version
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    _item_, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        return None
    current = garment_hair.hair_method(character_name, profile=profile)
    other = gs.HAIRDECK if current == gs.EDIT_CHAIN else gs.EDIT_CHAIN
    hit = _other_fit(character_name, item_id, other, profile)
    if hit is None:
        return None
    path, record, on_base = hit
    try:
        url: Optional[str] = _url(character_name, item_id, "model", content_version(path), f"&method={other}")
    except OSError:
        url = None
    return {"method": other, "preview_url": url, "created_at": record.get("created_at"),
            "metrics": record.get("metrics") or {}, "colour": record.get("colour"),
            "on_current_base": on_base}


#: The HairDeck images the Hair tab shows: the input (the profile picture
#: the job was made from) and two files of the job.
HAIRDECK_IMAGES: Tuple[str, ...] = ("input", "prep", "model_input")


def _rgb_hex(value: Any) -> Optional[str]:
    """sRGB 0..1 triple -> ``#rrggbb``; None for anything else."""
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        rgb = [max(0, min(255, round(float(v) * 255))) for v in value[:3]]
    except (TypeError, ValueError):
        return None
    return "#" + "".join(f"{c:02x}" for c in rgb)


def hairdeck_image_path(character_name: str, item_id: str, which: str) -> Optional[Path]:
    """The file behind one HairDeck tile of the CURRENT ``hsig``: ``input`` =
    the current profile picture (the ``hsig`` is made from it), ``prep`` /
    ``model_input`` = ``prep.png`` / ``model_input.png`` of the job folder.
    None when the file is not there. ValueError for an unknown ``which`` or
    an item that is no garment of the character."""
    from app.core import garment_store as gs
    from app.core.model_refs import current_profile_image
    from app.models.character import get_character_profile
    if which not in HAIRDECK_IMAGES:
        raise ValueError(f"image must be one of {', '.join(HAIRDECK_IMAGES)}")
    _item(character_name, item_id)
    profile = get_character_profile(character_name) or {}
    if which == "input":
        return current_profile_image(character_name, profile=profile)
    path = gs.hairdeck_dir(character_name, item_id,
                           gs.garment_hsig(character_name, item_id, profile=profile)) / f"{which}.png"
    return path if path.is_file() else None


def hairdeck_panel(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The Hair tab's HairDeck section for the CURRENT ``hsig`` (whichever
    method is selected): ``{hsig, status, attempt, seed, backend, created_at,
    error, notes, attempts, images, colour, placement}``.

    - ``attempts``: the refused fit attempts of the job (gate records);
    - ``images``: ``input`` / ``prep`` / ``model_input`` -> ``{url, model,
      created_at}`` (tile meta for ``RefImage``) or None when absent;
    - ``colour``: ``{target, source, auto}`` — ``target`` the manual
      ``#rrggbb`` or None, ``source`` ``"override"`` or ``"hairdeck"`` (R4:
      automatic = HairDeck's own vertex colours), ``auto`` HairDeck's own
      hair colour from the job's ``info.json`` as ``#rrggbb`` (None without);
    - ``placement``: ``{forward_m, tilt_deg, default_forward_m, limits,
      fitted}`` — the manual values (None = automatic,
      ``garment_hair.hair_placement``), the automatic forward shift, the
      bounds of a manual value and what the newest HairDeck fit applied
      (its record's ``placement``; None without a fit or from a fit before
      the placement correction).

    None for an item that is no hair."""
    import json as _json
    from app.core import garment_hair, garment_hairdeck, garment_store as gs
    from app.core.model_refs import current_profile_image, image_tile_meta
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    _item_, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        return None
    hsig = gs.garment_hsig(character_name, item_id, profile=profile)
    job = _hairdeck_info(character_name, item_id, hsig)
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    images: Dict[str, Optional[Dict[str, Any]]] = {}
    source = current_profile_image(character_name, profile=profile)
    for which in HAIRDECK_IMAGES:
        path = source if which == "input" else folder / f"{which}.png"
        stamp = _stamp(path) if path is not None else None
        if stamp is None:
            images[which] = None
            continue
        meta = (image_tile_meta(path) if which == "input"
                else image_tile_meta(path, {"model": job.get("backend") or "", "created_at": job.get("created_at")}))
        images[which] = {"url": _url(character_name, item_id, f"hairdeck/{which}", stamp), **meta}
    try:
        info = _json.loads((folder / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    override = garment_hair.hair_colour_override(profile)
    colour = {"target": override or None, "source": "override" if override else "hairdeck",
              "auto": _rgb_hex(info.get("hair_color")) if isinstance(info, dict) else None}
    newest = _newest_fit(character_name, item_id, gs.HAIRDECK)
    placement = {**garment_hair.hair_placement(profile),
                 "default_forward_m": garment_hairdeck.DEFAULT_FORWARD_M,
                 "limits": {"forward_m": garment_hairdeck.FORWARD_LIMIT_M,
                            "tilt_deg": garment_hairdeck.TILT_LIMIT_DEG},
                 "fitted": newest[1].get("placement") if newest else None}
    return {"hsig": hsig, "status": job["status"], "attempt": job["attempt"], "seed": job["seed"],
            "backend": job["backend"], "created_at": job["created_at"], "error": job["error"],
            "notes": job["notes"], "attempts": job["fit_attempts"], "images": images, "colour": colour,
            "placement": placement}


def garment_info(character_name: str, item_id: str) -> Dict[str, Any]:
    """UI info of one garment (the Hair tab): fsig, the method and its
    source, description, every step's files and gate numbers (the steps of
    the CURRENT method; HairDeck adds ``hsig``), why the served fit is not
    the current one (``stale_reasons``), the run status and the preview URL.
    ``served_fsig`` None = no hair is served (e.g. the selected method has no
    accepted fit yet). HairDeck hair adds the stale reasons
    ``hairdeck_changed`` (another profile picture or HairDeck setting than
    the served fit's job), ``colour_changed`` (another colour override) and
    ``placement_changed`` (another manual forward/tilt, or a fit from before
    the placement correction).
    ValueError for an invalid item."""
    from app.core import base_body, garment_hair, garment_store as gs
    from app.core.http_files import content_version
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_profile
    _item_, kind = _item(character_name, item_id)
    profile = get_character_profile(character_name) or {}
    inputs = _kind_inputs(kind, character_name, profile, item_id)
    method, method_source = (garment_hair.hair_method_source(character_name, profile=profile)
                             if kind == garment_hair.HAIR_KIND else (gs.EDIT_CHAIN, "world"))
    try:
        fsig: Optional[str] = gs.garment_fsig(character_name, item_id, profile=profile)
    except ValueError:
        fsig = None
    hsig = gs.garment_hsig(character_name, item_id, profile=profile) if fsig and method == gs.HAIRDECK else None
    base = base_body.current_base(character_name, profile=profile) or ("", "")
    steps: Dict[str, Any] = {}
    if fsig:
        for step in gs.steps_for(kind, method):
            if step in gs.IMAGE_STEPS:
                steps[step] = {v: _image_info(character_name, item_id, fsig, step, v) for v in gs.GARMENT_VIEWS}
            elif step == "mesh":
                steps[step] = _mesh_info(character_name, item_id, fsig)
            elif step == "hairdeck":
                steps[step] = _hairdeck_info(character_name, item_id, hsig or "")
            elif step == "fit":
                steps[step] = _fit_info(character_name, item_id, fsig, base[1], method)
    served = (gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
              if base[1] else None)
    served_fsig = (gs.parse_name(served[0]) or (None, None))[1] if served else None
    stale: List[str] = []
    if not (fsig and steps.get("fit", {}).get("status") == "accepted"):
        reference = served or _newest_fit(character_name, item_id, method)
        if reference:
            record = reference[1]
            used = dict(record.get("inputs") or {})
            used_images = used.pop("base_images", None)
            if any(used.get(k) != v for k, v in inputs.items()):
                stale.append("description_changed")
            images = ({v: _sha(find_ref_image(character_name, base_body._kind(v), base[0]))
                       for v in gs.GARMENT_VIEWS} if base[0] else {})
            if record.get("base_signature") != base[0] or used_images != images:
                stale.append("base_changed")
            elif record.get("base_model_sha256") != base[1]:
                stale.append("base_model_changed")
            if method == gs.HAIRDECK and gs.fit_method(record) == gs.HAIRDECK:
                if used.get("hsig") != hsig:
                    stale.append("hairdeck_changed")
                if (used.get("colour") or "") != garment_hair.hair_colour_override(profile):
                    stale.append("colour_changed")
                if used.get("placement") != garment_hair.hair_placement(profile):
                    stale.append("placement_changed")
    preview = preview_path(character_name, item_id)
    preview_url = None
    if preview is not None:
        try:
            preview_url = _url(character_name, item_id, "model", content_version(preview))
        except OSError:
            preview_url = None
    status = gs.status(character_name, item_id)
    return {"item_id": item_id, "kind": kind, "fsig": fsig, "method": method, "method_source": method_source,
            "hsig": hsig, "description": inputs.get("description") or inputs.get("prompt_fragment") or "",
            "steps": steps, "stale_reasons": stale,
            "running_step": status["running_step"], "started_at": status["started_at"],
            "failed": status["failed"], "preview_url": preview_url, "served_fsig": served_fsig}


def hair_summary(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """``{item_id, status}`` of the worn hair item for ``base_body.base_info``
    — status ``running`` / ``failed`` / ``ready`` (current fit accepted on
    the current base model) / ``stale`` (an older fit is served) /
    ``missing``; None without a worn hair item or off the pipeline."""
    from app.core import base_body, garment_store as gs
    from app.core.garment_hair import HAIR_KIND
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    item_id = (profile.get("equipped_mesh_pieces") or {}).get(HAIR_KIND) \
        if isinstance(profile.get("equipped_mesh_pieces"), dict) else None
    base = base_body.current_base(character_name, profile=profile)
    if not item_id or base is None:
        return None
    try:
        _item(character_name, item_id)
    except ValueError:
        return None
    status = gs.status(character_name, item_id)
    if status["running_step"]:
        state = "running"
    elif status["failed"]:
        state = "failed"
    else:
        try:
            fsig = gs.garment_fsig(character_name, item_id, profile=profile)
            method = gs.garment_method(character_name, item_id, profile=profile)
        except ValueError:
            fsig, method = "", gs.EDIT_CHAIN
        if fsig and _fit_state(character_name, item_id, fsig, base[1], method) == "accepted":
            state = "ready"
        elif base[1] and gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile):
            state = "stale"
        else:
            state = "missing"
    return {"item_id": item_id, "status": state}
