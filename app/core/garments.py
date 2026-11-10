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
  only guesses it (its ends hang behind the body) — unless the kind's step
  names its own order (``EDIT_STEPS[step]["views"]``; clothing ``worn``: the
  front first, the back is drafted from it). The kind's pair step
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

Refit before re-render (``garment_source``, user decision 2026-11-10): a
default run whose current image group has none of its own images yet (new
base images name a new fsig) first copies in the item's last accepted
source — images + mesh made on an older base — and fits it onto the current
base on the CPU (edit chain ``_fit``; subtract hair the cut + fit), its ghost
registered from the source's base front onto the current one. Accepted: the
run ends there (``refit`` in the result, ``refitted`` in the fit record).
Refused: the copies go and the same run renders the chain. An explicit run of
an image step on such a group (Re-render) drops the copies and renders from
the first step.

A refusal ends the run (``{ok: False, step, error, gates}`` + the in-memory
status); nothing downstream runs, and an already accepted fit keeps being
served (R11 — a refused re-run never makes the figure bald).

Hair made by HairDeck (``garment_hair.hair_method``; plan
``docs/superpowers/plans/2026-11-09-hairdeck-hair.md``, Task 4) runs
``hairdeck → fit`` instead (``garment_store.steps_for``):

- ``hairdeck``: ``generate_hair`` on the profile picture, seed 42, into the
  job folder ``raw/{item}_{hsig}/`` (cached per ``hsig``, so a base or colour
  change runs only the fit). A character with facial hair
  (``garment_beard.has_facial_hair``) sends a gated beard-free edit of the
  picture instead (``garment_beard.beard_free_input``, cached in the job
  folder; refused -> the picture itself, noted in the record). A forced regenerate replaces the job with the
  next seed after the highest one the record has seen (43, 44, …), so it
  gives a new result. A job whose ``info.json`` notes "no hair found"
  or "no person found" refuses with ``NO_HAIR_ERROR``;
- ``fit``: ``garment_hairdeck.fit_hairdeck`` on the current rigged base, with
  the colour override (profile ``hair_colour``) or HairDeck's own colours.
  A gate refusal of the attempt-1 job re-runs ``hairdeck`` once with that
  job's seed + 1 and fits again; a second refusal refuses with both attempts.

Footwear (kind ``footwear``, method ``shoe``; plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``) runs
``garment_footwear.run_chain`` instead (``_run_locked`` dispatches it first):
the per-item source steps ``source → empty → cutout → mesh → insole`` under
the ITEM lock — two wearers never run a step twice, the later one finds it
done — then the wearer's ``fit`` (not wired yet; the chain ends after the
insole). Same queue, status and cancel as every garment; a failure that is
load or the media switch (``retry_later``) is not persisted.

The served fit follows the CURRENT method (``garment_store.accepted_fit``): a
switch never generates anything, and a method without an accepted fit yet
serves no hair.

One run per character at a time (``garment_store.char_lock``); ``run_garment``
blocks and is called from the character's worker thread — every generation
inside goes through the image service, the fit and the graft are CPU work on
that thread. No profile lock is held across a step. The worker drains a
per-character FIFO (``_queues``; the run in flight is ``_current``):
``start_garment`` (a click) appends the explicit run behind the character's
running one — an identical pending run is not added twice, a pending default
run of the item becomes the explicit one in its place — and
``enqueue_garment`` (the triggers: ``after_base_model``, the outfit build's
``run_queued``) appends a default run behind the others. Several garments of
one character run one after the other, each request once; a failed run never
holds the queue (the next one starts). ``queue_state`` is the UI view;
``cancel_garment`` takes an item's waiting runs out (never the one in flight).

An own-mesh outfit piece (kind ``clothing``) whose fit was accepted by a run
asks ``base_body.after_mesh_item_ready``: an outfit model that left it
painted on (no fit then) is rebuilt without it.

Pieces worn over each other (plan
``docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md``,
Task 2): the fit step of this chain always fits against the BODY alone, so the
runs of one character's pieces need no order and an inner piece's refit never
re-runs an outer piece's chain. The layer order and the outer piece's fit over
the inner ones are derived from the accepted body fits by ``garment_layers``
(``garment_set.layer_order``; keyed by the inner fits, CPU only, no hub job)
when the assembly is built; a new inner fit (this module's ``_publish_fit``
schedules the assembly) makes the outer piece's layered fit stale through its
key.
"""
import hashlib
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("garments")

#: The ``running_step`` of a run that has been started but not reached a step yet.
QUEUED = "queued"

_lock = threading.Lock()
# Characters with a garment worker (started or running).
_active: set = set()
# Per character the FIFO of runs its worker still has to do (``_Job``): the
# worker drains it one run after the other, so several garments of one
# character (hair + own-mesh outfit pieces) never run at once and each
# request runs exactly once.
_queues: Dict[str, Deque["_Job"]] = {}
# Per character the run its worker is doing (or about to do: the spawn takes
# the head job, so a character in ``_active`` always has one here).
_current: Dict[str, "_Job"] = {}
_ORDINALS = ("first", "second", "third")
#: The seed of the first HairDeck job of an hsig. A forced regenerate takes
#: the next seed after the highest one the job record has seen
#: (``_next_seed``); the refused-fit retry takes the attempt's seed + 1.
HAIRDECK_FIRST_SEED = 42
#: Automatic HairDeck jobs of an hsig: a new seed is requested by a refused
#: fit only while fewer seeds than this are stored (the job and one retry);
#: beyond it only an explicit regenerate asks HairDeck again.
HAIRDECK_ATTEMPTS = 2
#: HairDeck seeds kept per job folder: the newest ones (plus the chosen seed
#: when it is older), every fit step weighs all of them (``_hairdeck_fit_step``).
HAIRDECK_KEEP_SEEDS = 4
_SEED_FILE_RE = re.compile(r".*_seed(\d+)(?:_[a-z_]+)?\.(?:glb|json)")
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
    (``item.owner``); an own-mesh outfit piece (kind ``clothing`` or
    ``footwear``, ``garment_set.OWN_MESH_PIECE_KINDS``) must be HELD or worn
    by it — the flag is on the item, every wearer gets a fit of their own."""
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) if isinstance(item_id, str) and item_id else None
    piece_kind = garment_set.garment_kind_of(item) if item else None
    if piece_kind in garment_set.OWN_MESH_PIECE_KINDS:
        if not garment_set.holds(character_name, item_id):
            raise ValueError(f"{item_id} is not a garment of {character_name}")
        return item, piece_kind
    if not item or item.get("category") != "garment":
        raise ValueError(f"{str(item_id)[:80]!r} is no garment item")
    kind = str((item.get("garment") or {}).get("kind") or "")
    if piece_kind != garment_set.HAIR:
        raise ValueError(f"Unknown garment kind {kind!r}")
    if (item.get("owner") or "").strip() != character_name:
        raise ValueError(f"{item_id} is not a garment of {character_name}")
    return item, kind


def _footwear() -> str:
    from app.core.garment_set import FOOTWEAR
    return FOOTWEAR


def _check_view(kind: str, view: Optional[str]) -> None:
    """ValueError for a ``view`` that is no garment view, and for any view of
    footwear (its steps are per item, without views)."""
    from app.core.garment_store import GARMENT_VIEWS
    if view is None:
        return
    if kind == _footwear():
        raise ValueError("Footwear has no views")
    if view not in GARMENT_VIEWS:
        raise ValueError(f"Unknown garment view {view!r}")


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
    """``_Refused`` when the fsig of the run's images is no longer the
    current one (``garment_store.image_fsig``: the edit-chain fsig of the
    subtract method's haired views, ``garment_fsig`` otherwise)."""
    from app.core.garment_store import image_fsig
    if image_fsig(character_name, item_id) != fsig:
        raise _Refused(step, INPUTS_CHANGED_ERROR, None)


def _mesh_done(character_name: str, item_id: str, fsig: str) -> bool:
    from app.core.garment_store import garment_path
    return _accepted(garment_path(character_name, item_id, fsig, "prepared"))


def _fit_state(character_name: str, item_id: str, fsig: str, base_model_sha: str,
               method: str = "edit_chain") -> str:
    """``accepted`` (on the current base model, from the current prepared
    mesh — HairDeck: from its seed's hair, still stored unchanged under an
    accepted job), ``stale`` (accepted on another base model, or by an
    older fit algorithm: ``garment_fit.FIT_VERSION``), ``outdated``
    (accepted, but the prepared mesh / HairDeck hair it was fitted from was
    replaced or removed) or ``missing``. Footwear (method ``shoe``):
    ``garment_footwear.fit_state`` on the base."""
    from app.core.garment_store import HAIRDECK, SHOE, garment_path, read_record
    if method == SHOE:
        from app.core import garment_footwear
        return garment_footwear.fit_state(character_name, item_id, fsig, base_model_sha)
    fit = garment_path(character_name, item_id, fsig, "fit")
    record = read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    if not base_model_sha or record.get("base_model_sha256") != base_model_sha:
        return "stale"
    from app.core.garment_fit import FIT_VERSION
    if record.get("fit_version") != FIT_VERSION.get(str(record.get("kind"))):
        return "stale"  # fitted by an older fit algorithm: the chain re-runs the fit only
    if method == HAIRDECK:
        inputs = record.get("inputs") or {}
        try:
            nohead = _fit_hair_file(character_name, item_id, inputs)
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
    from app.core.garment_store import GARMENT_VIEWS, IMAGE_STEPS, SHOE, SUBTRACT, image_fsig
    if method == SHOE and step != "fit":
        # The shoe's item steps: per item under its current ssig (``footwear_source``).
        from app.core import garment_footwear
        return garment_footwear.step_done(item_id, step)
    if method == SUBTRACT and step != "fit":
        if step in IMAGE_STEPS:  # the haired views: the edit chain's own, under its fsig
            fsig = image_fsig(character_name, item_id)
        else:
            from app.core import garment_subtract
            return garment_subtract.step_done(character_name, item_id, step, fsig)
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


def _seed_files(folder: Path, seed: int) -> Tuple[Optional[Path], Optional[Path]]:
    """``(hair, proxy)`` = ``hair_seed<s>_nohead.glb`` / ``hair_seed<s>.glb``
    of one seed in a job folder, ``(None, None)`` when either is missing."""
    hair, proxy = folder / f"hair_seed{seed}_nohead.glb", folder / f"hair_seed{seed}.glb"
    return (hair, proxy) if hair.is_file() and proxy.is_file() else (None, None)


def _stored_seeds(character_name: str, item_id: str, hsig: str) -> List[int]:
    """Every seed of the job folder of ``hsig`` whose hair and proxy files are
    both on disk, ascending. Each HairDeck run writes its own
    ``*_seed<N>*`` files, so a new seed never overwrites an older one."""
    from app.core import garment_store as gs
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    if not folder.is_dir():
        return []
    seeds = set()
    for path in folder.iterdir():
        match = _SEED_FILE_RE.fullmatch(path.name)
        if match:
            seeds.add(int(match.group(1)))
    return [seed for seed in sorted(seeds) if _seed_files(folder, seed)[0] is not None]


def _served_seed(character_name: str, item_id: str, hsig: str) -> Optional[int]:
    """The seed of the newest accepted HairDeck fit made from the job of
    ``hsig`` (the hair most likely served), None without one."""
    from app.core.garment_store import HAIRDECK
    newest = _newest_fit(character_name, item_id, HAIRDECK)
    inputs = (newest[1].get("inputs") or {}) if newest else {}
    try:
        return int(inputs["seed"]) if inputs.get("hsig") == hsig else None
    except (KeyError, TypeError, ValueError):
        return None


def _prune_seeds(folder: Path, keep_also: Optional[int]) -> List[int]:
    """Delete the ``*_seed<N>*`` files of every seed but the newest
    ``HAIRDECK_KEEP_SEEDS`` and ``keep_also`` (the seed of the served fit —
    its hair stays fresh). Returns the deleted seeds."""
    by_seed: Dict[int, List[Path]] = {}
    for path in folder.iterdir():
        match = _SEED_FILE_RE.fullmatch(path.name)
        if match and path.is_file():
            by_seed.setdefault(int(match.group(1)), []).append(path)
    keep = set(sorted(by_seed)[-HAIRDECK_KEEP_SEEDS:]) | ({keep_also} if keep_also is not None else set())
    dropped = [seed for seed in sorted(by_seed) if seed not in keep]
    for seed in dropped:
        for path in by_seed[seed]:
            path.unlink(missing_ok=True)
    return dropped


def _hairdeck_files(character_name: str, item_id: str, hsig: str) -> Tuple[Optional[Path], Optional[Path]]:
    """``(hair, proxy)`` of the ACCEPTED HairDeck job of ``hsig`` —
    ``hair_seed<s>_nohead.glb`` and ``hair_seed<s>.glb`` of the record's seed
    (the newest HairDeck run; the seed a fit chose is in its own record) —
    or ``(None, None)`` without an accepted job or with a file missing.
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
    return _seed_files(folder, seed)


def _fit_hair_file(character_name: str, item_id: str, inputs: Dict[str, Any]) -> Optional[Path]:
    """The ``hair_seed<s>_nohead.glb`` a HairDeck fit was made from (its
    ``inputs.hsig`` / ``inputs.seed``), None when the job is not accepted or
    the seed's files are gone. ValueError for an invalid hsig."""
    from app.core import garment_store as gs
    folder = gs.hairdeck_dir(character_name, item_id, str(inputs.get("hsig") or ""))
    if gs.read_record(folder / gs.HAIRDECK_RECORD).get("accepted") is not True:
        return None
    try:
        seed = int(inputs.get("seed"))
    except (TypeError, ValueError):
        return None
    return _seed_files(folder, seed)[0]


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
    missing from the result. A character with facial hair sends the
    beard-free copy (``garment_beard.beard_free_input``); the record names
    the input (``input``: ``beard_free`` / ``profile``) and notes it.
    Returns the job folder."""
    import json as _json
    import shutil
    from app.core import base_body, garment_beard
    from app.core import garment_store as gs
    from app.core.model_refs import current_profile_image
    from app.core.timeutils import utc_now_iso
    from app.imagegen import service
    image = current_profile_image(character_name, profile=profile)
    if image is None:
        raise base_body.MissingInput("No profile picture — HairDeck makes the hair from it")
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    beard: Optional[Dict[str, Any]] = None
    send = image
    if garment_beard.has_facial_hair(character_name, profile=profile):
        send, beard = garment_beard.beard_free_input(character_name, image, folder)
    seeds = sorted(set(_job_seeds(gs.read_record(folder / gs.HAIRDECK_RECORD))) | {int(seed)})
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = folder.parent / f".{folder.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        result = service.get_image_service().generate_hair(
            str(send), str(staging), character_name=character_name, params={"seed": seed})
        names = [str(f.get("name") or "") for f in result.get("files") or []]
        try:
            info = _json.loads((staging / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        notes = [str(n) for n in (info.get("notes") or [])] if isinstance(info, dict) else []
        record: Dict[str, Any] = {
            "accepted": False, "attempt": attempt, "seed": seed, "seeds": seeds,
            "notes": notes + ([garment_beard.note(beard)] if beard is not None else []),
            "input": "beard_free" if send != image else "profile", "input_sha256": _sha(send),
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
        dropped = _prune_seeds(folder, _served_seed(character_name, item_id, hsig))
        if dropped:
            logger.info("HairDeck %s/%s (%s): dropped the files of seeds %s (keeping %s)", character_name,
                        item_id, hsig, dropped, HAIRDECK_KEEP_SEEDS)
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
    from app.core.garment_store import GARMENT_VIEWS, garment_path
    from app.core.model_refs import find_ref_image
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
    from app.core import garment_source
    base_images = {v: _sha(p) for v, p in base_views.items()}
    if fsig == _image_fsig_or_empty(character_name, item_id):
        # A group of the current fsig was made on exactly these base views: keep them with it (its frame).
        garment_source.ensure_base_copy(character_name, item_id, fsig, bsig=bsig, expected=base_images)
    # Masks in the frame of the bald front view the unrigged base was built
    # from (R6: the full-frame ghost mask, never the cut-out); a source made
    # on another base is registered onto it (``garment_source.fit_masks``).
    try:
        bald_mask, ghost_mask, frame = garment_source.fit_masks(character_name, item_id, fsig,
                                                                body_front=base_views["front"],
                                                                base_front=base_views["front"])
    except garment_source.FrameRefused as e:
        raise _Refused("fit", f"fit refused — {e}", {"ok": False, "reasons": [str(e)],
                                                      "registration": e.registration})
    from app.core import garment_set
    if kind == garment_set.CLOTHING:
        from app.models.inventory import get_item
        slots = list(((get_item(item_id) or {}).get("outfit_piece") or {}).get("slots") or [])
        # A refit aligns its sleeves / trouser legs onto this body's limbs (``garment_source`` LIMBS).
        limb_source = garment_source.limb_source(character_name, item_id, fsig) if frame.get("registered") else None
        result = garment_fit.fit_clothing(prepared_bytes, snapshot["unrigged"], snapshot["rigged"],
                                          masks={"body": bald_mask, "garment": ghost_mask}, slots=slots,
                                          limb_source=limb_source)
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
    # A refit's limbs sit on the body (``garment_source`` LIMBS).
    limbs = garment_source.check_limbs(character_name, item_id, fsig, result.garment.positions,
                                       snapshot["rigged"], frame)
    if limbs is not None and not limbs["ok"]:
        raise _Refused("fit", "refit refused — " + "; ".join(limbs["reasons"]),
                       {"ok": False, "reasons": limbs["reasons"], "limbs": limbs})
    if limbs is not None:
        frame = {**frame, "limbs": limbs}

    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig,
        "metrics": result.metrics, "gates": gates, "report": result.report,
        "base_signature": bsig, "base_model_sha256": base_sha, "body_id": bsig, "body_sha256": base_sha,
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": base_images,
                   "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
                   "ghost_front_sha256": _sha(ghost)},
        **garment_source.fit_source(character_name, item_id, fsig, base_images), "frame": frame,
        "created_at": utc_now_iso()}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def _image_fsig_or_empty(character_name: str, item_id: str) -> str:
    """``garment_store.image_fsig`` ("" when the item has none)."""
    from app.core import garment_store as gs
    try:
        return gs.image_fsig(character_name, item_id)
    except ValueError:
        return ""


def _publish_fit(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, rigged: bytes,
                 result: Any, record: Dict[str, Any], *, body: str = "", schedule: bool = True) -> Path:
    """Graft an accepted fit onto the rigged base (``body``: the rigged outfit
    body of that id), write the fit GLB and its ``record`` (to that body's
    folder, ``garment_store.body_root``), decimate the distance tier to
    ``low/`` and schedule the assembly (unless ``schedule`` is False: the
    assembly build itself fits). Shared by both hair methods and every body."""
    from app.blender import refine
    from app.core import garment_fit, glb_mesh
    from app.core.garment_store import garment_path, write_record
    record["fit_version"] = garment_fit.FIT_VERSION[kind]
    blob = glb_mesh.graft(rigged, result.garment, name=f"garment_{kind}_{item_id}",
                          extras={"kind": kind, "item_id": item_id, "fsig": fsig})
    fit = garment_path(character_name, item_id, fsig, "fit", body=body)
    low = garment_path(character_name, item_id, fsig, "low", body=body)
    # A distance tier of the previous fit must never pair with the new one.
    low.unlink(missing_ok=True)
    _write_atomic(fit, blob)
    write_record(fit.with_suffix(".json"), record)
    logger.info("Garment fit %s/%s (%s): accepted on %s, %s tris", character_name, item_id, fsig, body or bsig,
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
    if body:
        from app.core.garment_store import clear_failure_on_body
        clear_failure_on_body(character_name, item_id, fsig, body)
    if schedule:
        from app.core import garment_assembly
        garment_assembly.schedule(character_name)
    return fit


def _placement_summary(placement: Any) -> Optional[Dict[str, Any]]:
    """The fit record's ``placement``: what the fit's ``report.placement`` applied (forward/tilt and where they
    came from) and the hairline it reached against its target. None without a report section."""
    if not isinstance(placement, dict):
        return None
    keys = ("forward_m", "forward_source", "tilt_deg", "tilt_source", "tilt_solve", "hairline_target_y",
            "landmark_source")
    return {**{k: placement.get(k) for k in keys}, "hairline_y": placement.get("hairline_pushed_y")}


def _fit_seed(character_name: str, item_id: str, hsig: str, seed: int, attempt: int, rigged: bytes,
              profile: Dict[str, Any]) -> Dict[str, Any]:
    """Fit one stored HairDeck seed of ``hsig`` onto ``rigged`` (colour = the
    profile's override, else the profile's named hair colour, else HairDeck's
    own; gates = those of the hair's length class; placement = the profile's
    manual forward/tilt, else automatic) without publishing anything:
    ``{seed, result, hair_bytes, proxy_bytes, gates}`` — ``gates`` the
    verdict ``{attempt, seed, ok, reasons, limits, metrics}`` (``attempt`` =
    the seed's position among the stored seeds, 1-based)."""
    from app.core import garment_hair, garment_hairdeck
    from app.core import garment_store as gs
    hair, proxy = _seed_files(gs.hairdeck_dir(character_name, item_id, hsig), seed)
    if hair is None or proxy is None:
        raise RuntimeError(f"HairDeck seed {seed} has no hair/proxy file")
    hair_bytes, proxy_bytes = hair.read_bytes(), proxy.read_bytes()
    override = garment_hair.hair_colour_override(profile)
    named = garment_hair.profile_hair_colour(character_name, profile=profile)
    length_class = garment_hair.hair_length_class(character_name, profile=profile)
    result = garment_hairdeck.fit_hairdeck(hair_bytes, proxy_bytes, rigged,
                                           colour_target=garment_hair.colour_target(override),
                                           colour_profile=garment_hair.colour_target(named["hex"]) if named else None,
                                           length_class=length_class,
                                           **garment_hair.hair_placement(profile))
    gates = {"attempt": attempt, "seed": seed, "ok": bool(result.ok), "reasons": list(result.reasons),
             "limits": _hairdeck_limits(length_class), "metrics": result.metrics}
    return {"seed": seed, "result": result, "hair_bytes": hair_bytes, "proxy_bytes": proxy_bytes, "gates": gates}


def _hairdeck_limits(length_class: Optional[str]) -> Dict[str, List[Any]]:
    """``{key: [kind, limit]}`` of the HairDeck gates of a hair length class."""
    from app.core import garment_hairdeck
    return {key: [kind_, limit] for key, (kind_, limit, _label) in garment_hairdeck.gates_for(length_class).items()}


def _hairdeck_colour(override: str, named: Optional[Dict[str, str]], colour_report: Dict[str, Any]
                     ) -> Dict[str, Any]:
    """The fit record's ``colour``: ``{target, source, name, applied, delta_e_before, delta_e_after}`` —
    ``source`` ``"override"`` (the manual colour), ``"profile"`` (the profile's named colour, transferred unless
    HairDeck's own lay within ``AUTO_RECOLOUR_MIN_DE`` of it: ``applied`` False) or ``"hairdeck"``."""
    if override:
        out: Dict[str, Any] = {"target": override, "source": "override", "name": None, "applied": True}
    elif named:
        out = {"target": named["hex"], "source": "profile", "name": named["name"],
               "applied": bool(colour_report.get("applied"))}
    else:
        return {"target": None, "source": "hairdeck", "name": None, "applied": False,
                "delta_e_before": None, "delta_e_after": None}
    return {**out, "delta_e_before": colour_report.get("delta_e_before"),
            "delta_e_after": colour_report.get("delta_e_after")}


def _push_of(fit: Dict[str, Any]) -> float:
    try:
        return float(fit["result"].metrics.get("max_push_m"))
    except (TypeError, ValueError):
        return float("inf")


def _seed_summary(fits: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``[{seed, ok, max_push_m, reasons}]`` of every seed fitted in a fit step, by seed."""
    return [{"seed": seed, "ok": f["gates"]["ok"], "max_push_m": f["result"].metrics.get("max_push_m"),
             "reasons": f["gates"]["reasons"]} for seed, f in sorted(fits.items())]


def _choose_seed(fits: Dict[int, Dict[str, Any]]) -> Optional[int]:
    """The passing seed with the smallest ``max_push_m`` (tie: the lower
    seed); None when no seed passes."""
    passing = [seed for seed, f in fits.items() if f["gates"]["ok"]]
    return min(passing, key=lambda seed: (_push_of(fits[seed]), seed)) if passing else None


def _refused_gates(fits: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [f["gates"] for _seed, f in sorted(fits.items()) if not f["gates"]["ok"]]


def _publish_hairdeck(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, hsig: str,
                      profile: Dict[str, Any], snapshot: Dict[str, Any], fit: Dict[str, Any],
                      fits: Dict[int, Dict[str, Any]]) -> Path:
    """Publish the chosen seed's fit. Its record names that seed
    (``inputs.seed``) and every seed's verdict of this fit step (``seeds``);
    the job record keeps the verdicts too (``fitted_seeds``, ``fit_attempts``
    = the refused ones)."""
    from app.core import base_body, garment_hair
    from app.core import garment_store as gs
    from app.core.garment_store import GARMENT_VIEWS, HAIRDECK
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    result, seed = fit["result"], fit["seed"]
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    gs.write_record(folder / gs.HAIRDECK_RECORD,
                    {**gs.read_record(folder / gs.HAIRDECK_RECORD), "fitted_seeds": _seed_summary(fits),
                     "fit_attempts": _refused_gates(fits)})
    override = garment_hair.hair_colour_override(profile)
    length_class = garment_hair.hair_length_class(character_name, profile=profile)
    base_views = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in GARMENT_VIEWS}
    gates = {"ok": True, "reasons": [], "limits": _hairdeck_limits(length_class)}
    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "method": HAIRDECK,
        "metrics": result.metrics, "gates": gates, "report": result.report,
        "base_signature": bsig, "base_model_sha256": hashlib.sha256(snapshot["rigged"]).hexdigest(),
        "body_id": bsig, "body_sha256": hashlib.sha256(snapshot["rigged"]).hexdigest(),
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": {v: _sha(p) for v, p in base_views.items()},
                   "hsig": hsig, "attempt": fit["gates"]["attempt"], "seed": seed, "colour": override,
                   "placement": garment_hair.hair_placement(profile),
                   "nohead_sha256": hashlib.sha256(fit["hair_bytes"]).hexdigest(),
                   "proxy_sha256": hashlib.sha256(fit["proxy_bytes"]).hexdigest()},
        "colour": _hairdeck_colour(override, garment_hair.profile_hair_colour(character_name, profile=profile),
                                   result.report.get("colour") or {}),
        "length_class": length_class,
        "placement": _placement_summary(result.report.get("placement")),
        "seeds": _seed_summary(fits),
        "refused_attempts": _refused_gates(fits),
        "created_at": utc_now_iso()}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def _hairdeck_fit_step(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, hsig: str,
                       profile: Dict[str, Any], ran: List[str], prefer_seed: Optional[int] = None) -> Path:
    """The ``fit`` step of HairDeck hair. ``prefer_seed`` (the seed an
    explicit regenerate of this run just made) is fitted first and published
    when it passes — a regenerate asks for THAT result. Otherwise every
    stored seed of the job (``_stored_seeds``, at most
    ``HAIRDECK_KEEP_SEEDS``) is fitted on the current base model and the
    passing one with the smallest ``max_push_m`` is published (tie: the lower
    seed) — no HairDeck call. Only when none passes and fewer than
    ``HAIRDECK_ATTEMPTS`` seeds are stored does HairDeck run once more with
    the next seed, which is fitted too. Refuses with every seed's gates
    (``{attempts: [...]}``, also kept as ``fit_attempts`` in the job record)
    when none passes."""
    from app.core import base_body, garment_store as gs
    seeds = _stored_seeds(character_name, item_id, hsig)
    if _hairdeck_files(character_name, item_id, hsig)[0] is None or not seeds:
        raise base_body.MissingInput("The HairDeck hair is missing — run the hairdeck step first")
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    fits: Dict[int, Dict[str, Any]] = {}

    def fit(seed: int) -> None:
        stored = _stored_seeds(character_name, item_id, hsig)
        fits[seed] = _fit_seed(character_name, item_id, hsig, seed, stored.index(seed) + 1, snapshot["rigged"],
                               profile)

    if prefer_seed in seeds:
        fit(prefer_seed)
        if fits[prefer_seed]["gates"]["ok"]:
            return _publish_hairdeck(character_name, item_id, kind, fsig, bsig, hsig, profile, snapshot,
                                     fits[prefer_seed], fits)
    for seed in seeds:
        if seed not in fits:
            fit(seed)
    chosen = _choose_seed(fits)
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    if chosen is None and len(seeds) < HAIRDECK_ATTEMPTS:
        retry_seed = _next_seed(_hairdeck_record(character_name, item_id, hsig))
        logger.info("HairDeck fit %s/%s refused for seeds %s — HairDeck once more with seed %s",
                    character_name, item_id, seeds, retry_seed)
        gs.start(character_name, item_id, "hairdeck")
        try:
            _run_hairdeck(character_name, item_id, hsig, profile, len(seeds) + 1, retry_seed,
                          fit_attempts=_refused_gates(fits))
        except _Refused:
            raise
        except Exception as e:  # noqa: BLE001 — reported as the hairdeck step's failure (it is the running step)
            raise _Refused("hairdeck", str(e) or type(e).__name__, None) from e
        gs.end(character_name, item_id, "hairdeck")
        if "hairdeck" not in ran:
            ran.append("hairdeck")
        gs.start(character_name, item_id, "fit")
        fit(retry_seed)
        chosen = _choose_seed(fits)
    if chosen is None:
        attempts = _refused_gates(fits)
        gs.write_record(folder / gs.HAIRDECK_RECORD,
                        {**_hairdeck_record(character_name, item_id, hsig), "fit_attempts": attempts,
                         "fitted_seeds": _seed_summary(fits)})
        best = min(fits.values(), key=lambda f: (_push_of(f), f["seed"]))
        raise _Refused("fit", f"fit refused for every stored HairDeck seed ({', '.join(map(str, sorted(fits)))})"
                       f" — seed {best['seed']}: " + "; ".join(best["gates"]["reasons"]), {"attempts": attempts})
    logger.info("HairDeck fit %s/%s: seed %s chosen of %s", character_name, item_id, chosen,
                [(seed, f["result"].metrics.get("max_push_m"), f["gates"]["ok"]) for seed, f in sorted(fits.items())])
    return _publish_hairdeck(character_name, item_id, kind, fsig, bsig, hsig, profile, snapshot, fits[chosen], fits)


# --- Fits per body (plan 2026-11-10-outfit-body-mesh-mode, Task 2) -------------
#
# The chain's ``fit`` step fits onto the BASE model (the body of the retexture
# mode, body id = the base signature). An outfit model of the mesh mode stands
# on an OUTFIT BODY (``base_body.outfit_body_id``) whose geometry and head
# differ: every own-mesh piece and the hair it carries get a fit of their own
# on that body — key ``(item, fsig, body id)``, files under
# ``garments/bodies/<body id>/`` (``garment_store.body_root``). Such a fit is
# DERIVED from the fit served on the base model (``garment_store.accepted_fit``
# — the piece is a mesh at all only when it has one, ``base_body.resolve_mesh_items``):
# the same fsig, the same garment source (edit chain: the cached prepared mesh +
# ghost front; HairDeck: the seed of the base fit), fitted by the same fit and
# gates onto the body's rigged + unrigged GLB with the body's front view as the
# framing (the body was meshed from it). CPU only — no image, mesh or hub job.
#
# Current on a body = accepted, made on that body's bytes (``body_sha256``), by
# the current fit algorithm (``fit_version``) from the base fit served now
# (``base_fit_sha256``) — ``body_fit_state``. A refused or failed fit is
# recorded per body (``garment_store.record_body_failure``) and not retried
# while those three keys hold; an older fit accepted on the same body keeps
# being served meanwhile (R11). Who fits: the outfit model build on the body
# (``base_body._build_on_outfit_body`` → ``garment_assembly.body_fit_warning``)
# and lazily every assembly build (``garment_assembly._wanted`` with
# ``build_layers``: hair worn later, a new base fit); the boot sweep
# (``garment_refit``) refits an older ``fit_version`` on every stored body.

def _snapshot_body(character_name: str, body_id: str) -> Dict[str, Any]:
    """The stored outfit body ``body_id`` read under the publication lock of
    the REAL model directory: ``{rigged, unrigged, meta, sha}`` (``sha`` of
    the rigged bytes). ``MissingInput`` without a rigged body or its retained
    unrigged source."""
    from app.core import base_body
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _read_sidecar
    path = base_body.outfit_body_path(character_name, body_id)
    with keyed_lock("model3d_publication", str(path.parent)):
        meta = _read_sidecar(path)
        if (not path.is_file() or meta.get("rig") != "mixamo" or meta.get("rig_error")
                or not isinstance(meta.get("outfit_body"), dict)):
            raise base_body.MissingInput(base_body.OUTFIT_BODY_MISSING)
        unrigged = path.parent / "unrigged" / path.name
        if not unrigged.is_file():
            raise base_body.MissingInput("The outfit body has no unrigged source — rebuild the outfit body")
        rigged = path.read_bytes()
        source = unrigged.read_bytes()
    return {"rigged": rigged, "unrigged": source, "meta": meta, "sha": hashlib.sha256(rigged).hexdigest()}


def body_sha256(character_name: str, body_id: str) -> str:
    """Content identity of the stored rigged outfit body, "" without one."""
    from app.core import base_body
    try:
        return base_body.file_sha256(base_body.outfit_body_path(character_name, body_id))
    except ValueError:
        return ""


def body_fit_state(character_name: str, item_id: str, fsig: str, body_id: str, body_sha: str,
                   base_fit_sha: str) -> str:
    """``accepted`` (on the body ``body_sha``, by the current fit algorithm,
    from the base fit ``base_fit_sha``), ``stale`` (made on other body
    bytes, or by an older ``garment_fit.FIT_VERSION``), ``outdated``
    (accepted on this body from another base fit) or ``missing``."""
    from app.core.garment_fit import FIT_VERSION
    from app.core.garment_store import garment_path, read_record
    fit = garment_path(character_name, item_id, fsig, "fit", body=body_id)
    record = read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    if not body_sha or record.get("body_id") != body_id or record.get("body_sha256") != body_sha:
        return "stale"
    if record.get("fit_version") != FIT_VERSION.get(str(record.get("kind"))):
        return "stale"
    if not base_fit_sha or record.get("base_fit_sha256") != base_fit_sha:
        return "outdated"
    return "accepted"


def fit_on_body(character_name: str, item_id: str, *, body_id: str, base_fit: Tuple[Path, Dict[str, Any]],
                profile: Optional[Dict[str, Any]] = None, schedule: bool = True) -> Path:
    """Fit the garment of the base fit ``base_fit`` (``(fit GLB, record)``,
    the fit served on the base model) onto the outfit body ``body_id`` and
    publish it under ``(item, fsig, body id)`` (block above). ``_Refused``
    when the gate refuses, ``MissingInput`` when a source is gone (the
    prepared mesh / ghost front / HairDeck seed, the body or its front
    view). Never runs a generator."""
    from app.core import base_body, garment_fit, garment_set, glb_mesh
    from app.core import garment_store as gs
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    if not gs.is_body_id(body_id):
        raise ValueError(f"not an outfit body id: {str(body_id)[:40]!r}")
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    path, base_record = base_fit
    parsed = gs.parse_name(Path(path))
    if not parsed or parsed[0] != item_id:
        raise ValueError(f"{Path(path).name} is no fit of {item_id}")
    fsig = parsed[1]
    kind = str(base_record.get("kind") or "")
    if kind not in garment_fit.FIT_VERSION:
        raise ValueError(f"unknown garment kind {kind!r}")
    base_fit_sha = _sha(Path(path))
    body = _snapshot_body(character_name, body_id)
    bsig = str(body["meta"]["outfit_body"].get("base_signature") or base_record.get("base_signature") or "")
    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig,
        "body_id": body_id, "body_sha256": body["sha"], "base_signature": bsig,
        "texture_signature": body["meta"]["outfit_body"].get("texture_signature"),
        "base_fit_sha256": base_fit_sha}
    if gs.fit_method(base_record) == gs.SUBTRACT:
        from app.core import garment_subtract
        result, fields = garment_subtract.fit_on_body(character_name, item_id, body_id=body_id, body=body,
                                                      base_record=base_record, profile=profile)
        record.update({**fields, "created_at": utc_now_iso()})
    elif gs.fit_method(base_record) == gs.HAIRDECK:
        from app.core import garment_hair
        inputs = base_record.get("inputs") or {}
        hsig = str(inputs.get("hsig") or "")
        try:
            seed = int(inputs.get("seed"))
        except (TypeError, ValueError):
            raise base_body.MissingInput("The base fit names no HairDeck seed — run the hair chain")
        if _fit_hair_file(character_name, item_id, inputs) is None:
            raise base_body.MissingInput("The HairDeck hair of the base fit is gone — run the hair chain")
        fit = _fit_seed(character_name, item_id, hsig, seed, int(inputs.get("attempt") or 1), body["rigged"],
                        profile)
        if not fit["gates"]["ok"]:
            raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(fit["gates"]["reasons"]),
                           fit["gates"])
        result = fit["result"]
        override = garment_hair.hair_colour_override(profile)
        length_class = garment_hair.hair_length_class(character_name, profile=profile)
        record.update({
            "method": gs.HAIRDECK, "metrics": result.metrics, "report": result.report,
            "gates": {"ok": True, "reasons": [], "limits": _hairdeck_limits(length_class)},
            "inputs": {**_kind_inputs(kind, character_name, profile, item_id), "hsig": hsig, "seed": seed,
                       "attempt": fit["gates"]["attempt"], "colour": override,
                       "placement": garment_hair.hair_placement(profile),
                       "nohead_sha256": hashlib.sha256(fit["hair_bytes"]).hexdigest(),
                       "proxy_sha256": hashlib.sha256(fit["proxy_bytes"]).hexdigest()},
            "colour": _hairdeck_colour(override, garment_hair.profile_hair_colour(character_name, profile=profile),
                                       result.report.get("colour") or {}),
            "length_class": length_class, "placement": _placement_summary(result.report.get("placement")),
            "created_at": utc_now_iso()})
    else:
        prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
        if not _accepted(prepared):
            raise base_body.MissingInput("The garment mesh is missing — run the mesh step first")
        ghost = _image(character_name, item_id, fsig, "ghost", "front")
        if not _accepted(ghost):
            raise base_body.MissingInput("The ghost front image is missing — run the ghost step first")
        # The framing of the view the body was meshed from (its own copy of the dressed front).
        front = find_ref_image(character_name, base_body._kind("front"), body_id)
        if front is None:
            raise base_body.MissingInput("The outfit body's front view is missing — rebuild the outfit body")
        prepared_bytes = prepared.read_bytes()
        # The ghost's frame: the group's base copy, registered onto the base front of the body's base when it
        # was made on another base (``garment_source.fit_masks``).
        from app.core import garment_source
        base_front = find_ref_image(character_name, base_body._kind("front"), bsig) or front
        try:
            body_mask, ghost_mask, frame = garment_source.fit_masks(character_name, item_id, fsig,
                                                                    body_front=front, base_front=base_front)
        except garment_source.FrameRefused as e:
            raise _Refused("fit", f"fit on the outfit body refused — {e}",
                           {"ok": False, "reasons": [str(e)], "registration": e.registration})
        record["frame"] = frame
        limb_source = None
        if kind == garment_set.CLOTHING:
            from app.models.inventory import get_item
            slots = list(((get_item(item_id) or {}).get("outfit_piece") or {}).get("slots") or [])
            # The outfit body has its own framing, trunk and limbs: place the piece from the base fit of the same
            # prepared mesh (torso + sleeves / trouser legs, ``garment_source`` — outfit bodies).
            try:
                limb_source = garment_source.limb_source_from_fit(
                    Path(path).read_bytes(), skirt=bool((base_record.get("report") or {}).get("skirt")),
                    torso=True)
            except (OSError, ValueError, KeyError) as e:
                logger.warning("Garment fit %s/%s on %s: base fit unreadable for the limbs: %s", character_name,
                               item_id, body_id, e)
                limb_source = None
            result = garment_fit.fit_clothing(prepared_bytes, body["unrigged"], body["rigged"],
                                              masks={"body": body_mask, "garment": ghost_mask}, slots=slots,
                                              limb_source=limb_source)
            limits = garment_fit.CLOTHING_GATES
        else:
            result = garment_fit.fit_hair(prepared_bytes, body["unrigged"], body["rigged"], body_mask, ghost_mask)
            limits = garment_fit.GATES
        gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
                 "limits": {key: [kind_, limit] for key, (kind_, limit, _label) in limits.items()}}
        if not result.ok:
            raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(result.reasons),
                           {**gates, "metrics": result.metrics})
        limbs = garment_source.check_limbs(character_name, item_id, fsig, result.garment.positions,
                                           body["rigged"], frame, source=(limb_source or {}).get("numbers") or None)
        if limbs is not None and not limbs["ok"]:
            raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(limbs["reasons"]),
                           {"ok": False, "reasons": limbs["reasons"], "limbs": limbs})
        if limbs is not None:
            record["frame"] = {**frame, "limbs": limbs}
        if (limb_source or {}).get("torso_cover"):
            # The trunk the base fit covers stays covered (``garment_source`` TORSO) — never a torn piece.
            body_r = glb_mesh.body_arrays(body["rigged"])
            torso = garment_source.torso_gate(garment_source.torso_cover(result.garment.positions, body_r),
                                              limb_source["torso_cover"])
            if not torso["ok"]:
                raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(torso["reasons"]),
                               {"ok": False, "reasons": torso["reasons"], "torso": torso})
            record["frame"] = {**record["frame"], "torso": torso}
            # ... and no single hole opens in it (``garment_source`` TORSO holes).
            holes = garment_source.torso_holes(result.garment.positions, result.garment.indices,
                                               body_r, limb_source.get("torso_open"))
            hole_gate = garment_source.torso_hole_gate(holes)
            if not hole_gate["ok"]:
                raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(hole_gate["reasons"]),
                               {"ok": False, "reasons": hole_gate["reasons"], "holes": holes})
            record["frame"]["holes"] = holes
        record.update({
            "metrics": result.metrics, "gates": gates, "report": result.report,
            "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                       "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
                       "ghost_front_sha256": _sha(ghost), "body_front_sha256": _sha(front)},
            "created_at": utc_now_iso()})
    return _publish_fit(character_name, item_id, kind, fsig, bsig, body["rigged"], result, record,
                        body=body_id, schedule=schedule)


def body_fit(character_name: str, item_id: str, *, body_id: str, body_sha: str,
             base_fit: Tuple[Path, Dict[str, Any]], profile: Optional[Dict[str, Any]] = None,
             build: bool = False) -> Dict[str, Any]:
    """What an outfit model on the outfit body ``body_id`` (made of the body
    bytes ``body_sha``) carries of ``item_id`` whose base model is served
    ``base_fit``: ``{fit, low, record, fsig, pending, error}``.

    ``fit`` the body fit GLB to graft (None: nothing to graft), ``low`` its
    distance tier or None, ``pending`` True when a fit is still to be made
    (serving only reads: the assembly is then not current and a build is
    asked for), ``error`` why nothing current is grafted. ``build`` (the
    assembly build, never serving) fits a missing / stale / outdated one
    first — serialised per body; a refusal or failure is recorded per body
    and, like a persisted failure, leaves an older fit of the CURRENT
    ``garment_fit.FIT_VERSION`` accepted on these body bytes served (R11) or
    nothing: a fit of an older FIT_VERSION (or made on other body bytes) is
    never served once the fit that replaces it is refused — the piece is left
    off that body with the reason (coordinator ruling 2026-11-10, like mesh
    mode and footwear: a v5 blazer could be torn open). Nothing is fitted on a body whose stored bytes
    are no longer ``body_sha`` (the outfit model is stale; its rebuild copies
    the new body)."""
    from app.core import garment_fit, garment_store as gs
    from app.core.keyed_lock import keyed_lock
    path, base_record = base_fit
    parsed = gs.parse_name(Path(path))
    if not parsed or parsed[0] != item_id or not gs.is_body_id(body_id) or not body_sha:
        return {"fit": None, "low": None, "record": {}, "fsig": "", "pending": False,
                "error": "no fit to derive from"}
    fsig = parsed[1]
    fit_path = gs.garment_path(character_name, item_id, fsig, "fit", body=body_id)
    version = garment_fit.FIT_VERSION.get(str(base_record.get("kind") or ""))

    def current() -> Tuple[str, str, Optional[Dict[str, Any]]]:
        base_fit_sha = _sha(Path(path))
        state = body_fit_state(character_name, item_id, fsig, body_id, body_sha, base_fit_sha)
        failure = (gs.body_failure(character_name, item_id, fsig, body_id, body_sha=body_sha,
                                   base_fit_sha=base_fit_sha, fit_version=version)
                   if state != "accepted" else None)
        return state, base_fit_sha, failure

    state, base_fit_sha, failure = current()
    on_body = state != "accepted" and body_sha256(character_name, body_id) == body_sha
    if state != "accepted" and failure is None and on_body and build:
        with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
            state, base_fit_sha, failure = current()
            if state != "accepted" and failure is None:
                try:
                    fit_on_body(character_name, item_id, body_id=body_id, base_fit=base_fit, profile=profile,
                                schedule=False)
                except Exception as e:  # noqa: BLE001 — recorded per body, the assembly goes on
                    error = e.error if isinstance(e, _Refused) else (str(e) or type(e).__name__)
                    logger.warning("Garment fit %s/%s (%s) on outfit body %s failed: %s", character_name, item_id,
                                   fsig, body_id, error)
                    gs.record_body_failure(character_name, item_id, fsig, body_id, error=error, body_sha=body_sha,
                                           base_fit_sha=base_fit_sha, fit_version=version)
                state, base_fit_sha, failure = current()
    record = gs.read_record(fit_path.with_suffix(".json"))
    usable = (fit_path.is_file() and record.get("accepted") is True and record.get("body_id") == body_id
              and record.get("body_sha256") == body_sha
              and (failure is None or record.get("fit_version") == version))
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body_id)
    pending = state != "accepted" and failure is None and on_body and not build
    error = "" if state == "accepted" else str((failure or {}).get("error") or "") or (
        "not fitted on this outfit body yet" if pending or on_body else "the outfit body was rebuilt")
    return {"fit": fit_path if usable else None, "low": low if usable and low.is_file() else None,
            "record": record if usable else {}, "fsig": fsig, "pending": pending, "error": error}


def body_fit_info(character_name: str, item_id: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The fit of ``item_id`` on the body the CURRENT outfit model stands on
    (mesh mode): ``{body_id, status, error, fsig, created_at, metrics,
    gates}`` — ``status`` ``body_fit_state`` (``failed`` for a recorded
    refusal that holds, ``missing`` too without a base fit to derive from).
    None in retexture mode, for an outfit model on the base body, or when the
    current outfit model does not carry the item (neither its worn hair nor
    one of its own-mesh pieces)."""
    from app.core import base_body, garment_fit, garment_store as gs, model3d
    from app.core.garment_assembly import effective_mesh_items
    from app.core.model_refs import current_outfit_state
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
        return None
    path = model3d.find_model3d(character_name, current_outfit_state(character_name)[2], include_stale=True)
    meta = model3d._read_sidecar(path) if path is not None else {}
    body_id = str(meta.get("body_id") or "")
    if not gs.is_body_id(body_id):
        return None
    worn = profile.get("equipped_mesh_pieces")
    hair = {str(v) for v in worn.values() if v} if isinstance(worn, dict) else set()
    if item_id not in hair and item_id not in effective_mesh_items(meta):
        return None
    out: Dict[str, Any] = {"body_id": body_id, "status": "missing", "error": "", "fsig": None,
                           "created_at": None, "metrics": {}, "gates": {}}
    base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile) if base[1] else None
    parsed = gs.parse_name(base_fit[0]) if base_fit else None
    if not parsed:
        out["error"] = "no accepted fit on the base model to derive from"
        return out
    fsig = parsed[1]
    body_sha = str(meta.get("body_sha256") or "")
    base_fit_sha = _sha(base_fit[0])
    record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body_id).with_suffix(".json"))
    status = body_fit_state(character_name, item_id, fsig, body_id, body_sha, base_fit_sha)
    failure = (gs.body_failure(character_name, item_id, fsig, body_id, body_sha=body_sha, base_fit_sha=base_fit_sha,
                               fit_version=garment_fit.FIT_VERSION.get(str(base_fit[1].get("kind") or "")))
               if status != "accepted" else None)
    out.update(fsig=fsig, status="failed" if failure else status, error=str((failure or {}).get("error") or ""),
               created_at=record.get("created_at"), metrics=record.get("metrics") or {},
               gates=record.get("gates") or {})
    return out


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
    (``garment_store.steps_for``; hair by HairDeck: ``hairdeck``, ``fit``;
    footwear: the shoe chain, ``garment_footwear.run_chain``).

    Returns ``{ok: True, fsig, ran: [steps that produced output]}`` or
    ``{ok: False, fsig, step, error, gates}`` (also recorded as the item's
    failed status; not persisted for a footwear failure that is load,
    ``retry_later``). ValueError for an invalid item, step or view (any view
    of footwear)."""
    item, kind, order = _item_order(character_name, item_id)
    wanted = _steps(steps, order)
    _check_view(kind, view)
    from app.core import garment_store as gs
    with gs.char_lock(character_name):
        result = _run_locked(character_name, item, kind, wanted, view, bool(force))
        _note_outcome(character_name, item_id, result)
    if result.get("ok") and "fit" in (result.get("ran") or []) and kind == _clothing():
        # Outside the run lock: an outfit whose model left this piece painted
        # on (no fit then) is rebuilt without it (``mesh_item_ready``).
        try:
            from app.core import base_body
            base_body.after_mesh_item_ready(character_name, item_id)
        except Exception:  # noqa: BLE001 — the run itself succeeded
            logger.exception("Outfit rebuild after the fit of %s/%s failed", character_name, item_id)
    return result


def _note_outcome(character_name: str, item_id: str, result: Dict[str, Any]) -> None:
    """Persist a failed run's step + error under its fsig (automatic
    triggers skip it, ``cached_failure``); a successful run clears it. A
    failure that is load or the media switch (``retry_later``, footwear) is
    not persisted: automatic triggers try again."""
    from app.core import base_body, garment_store as gs
    fsig = str(result.get("fsig") or "")
    if not fsig:
        return  # failed before the fsig was known (off the pipeline, unknown item)
    try:
        if result.get("ok"):
            gs.clear_failure(character_name, item_id, fsig)
        elif result.get("step") and not result.get("retry_later"):
            base = base_body.current_base(character_name)
            gs.record_failure(character_name, item_id, fsig, step=str(result["step"]),
                              error=str(result.get("error") or ""), base_model_sha=base[1] if base else "")
    except (OSError, ValueError) as e:
        logger.warning("Garment failure record %s/%s not written: %s", character_name, item_id, e)


def cached_failure(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The persisted failure of the item's CURRENT fsig that automatic
    triggers honour (``garment_store.chain_failure``) — None when the chain
    may run. Only an explicit run (``start_garment``) or a changed fsig
    retries a failed chain (plan 2026-11-09-base-body-phase5-mesh-items,
    Task 4 fix round 1)."""
    from app.core import base_body, garment_store as gs
    try:
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
    except ValueError:
        return None
    base = base_body.current_base(character_name, profile=profile)
    return gs.chain_failure(character_name, item_id, fsig, base_model_sha=base[1] if base else "")


def _clothing() -> str:
    from app.core.garment_set import CLOTHING
    return CLOTHING


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
    if kind == _footwear():
        # The shoe chain: per-item steps under the item lock, then the wearer's fit (no base needed for the
        # item steps; the edit chain never runs for a feet piece).
        from app.core import garment_footwear
        return garment_footwear.run_chain(character_name, item, wanted, force)
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
        # The image steps' fsig: the subtract method's haired views are the edit chain's own.
        ifsig = gs.image_fsig(character_name, item_id, profile=profile)
        if method == gs.HAIRDECK:
            hsig = gs.garment_hsig(character_name, item_id, profile=profile)
        if wanted is None:
            first = next((s for s in order
                          if not _done(character_name, item_id, kind, fsig, s, base_sha, method, hsig)), None)
            if first is None:
                return {"ok": True, "fsig": fsig, "ran": []}
            if first in gs.IMAGE_STEPS:
                # Refit before re-render: the last accepted source onto the new base first (CPU).
                refit = _refit_from_source(character_name, item_id, kind, method, ifsig, bsig, profile)
                if refit is not None and refit.get("ok"):
                    return refit
        else:
            first = min(wanted, key=order.index)
            if first in gs.IMAGE_STEPS:
                from app.core import garment_source
                if garment_source.drop_materialized(character_name, item_id, ifsig):
                    # Re-render: images of two bases never mix in one group — the chain starts at its first step.
                    first = order[0]
        if first in gs.IMAGE_STEPS:
            from app.core import garment_source
            garment_source.ensure_current(character_name, item_id, ifsig, bsig)
        pair_step = _kind_module(kind).PAIR_STEP if method == gs.EDIT_CHAIN else None
        dirty = False  # an earlier step produced new output: every later step runs again
        regenerated_seed: Optional[int] = None  # the seed a forced HairDeck regenerate of this run made
        for step in order[order.index(first):]:
            forced = force and step == first
            gs.start(character_name, item_id, step)
            produced = False
            if method == gs.SUBTRACT and step not in gs.IMAGE_STEPS:
                # New haired views name a new subtract fsig (their sha256 is in it).
                fsig = gs.garment_fsig(character_name, item_id, profile=profile)
            if method == gs.SUBTRACT and step in ("mesh_source", "cut"):
                from app.core import garment_subtract
                ssig = gs.subtract_ssig(character_name, item_id, profile=profile)
                # The source mesh is keyed by the haired views alone: only a click re-runs it.
                if forced or not garment_subtract.step_done(character_name, item_id, step, fsig,
                                                            profile=profile) or (step == "cut" and dirty):
                    if step == "mesh_source":
                        garment_subtract.run_source(character_name, item_id, ifsig, ssig, force=forced)
                    else:
                        garment_subtract.run_cut(character_name, item_id, fsig, ifsig, ssig, bsig, profile,
                                                 force=True)
                    produced = True
            elif step in gs.IMAGE_STEPS:
                views = (gs.GARMENT_VIEWS if step == "cutout"
                         else _kind_module(kind).EDIT_STEPS[step].get("views", EDIT_VIEW_ORDER))
                for v in views:
                    f = forced and (view is None or v == view)
                    # Checked per view: a new front of a drafted step (clothing
                    # ``worn``) drops the back it was drafted from.
                    if not f and _accepted(_image(character_name, item_id, ifsig, step, v)):
                        continue
                    if step == "cutout":
                        garment_images.cut_out(character_name, item_id, ifsig, v, force=f)
                    else:
                        # The pair step's back is accepted before its front starts.
                        pair = (_pair_check(character_name, item_id, kind, ifsig)
                                if step == pair_step and v == "front" else None)
                        garment_images.run_edit_step(character_name, item_id, ifsig, step, v, force=f,
                                                     pair_check=pair,
                                                     prompt_hints=_front_hints(character_name, item_id, ifsig,
                                                                               kind, step, v))
                    produced = True
                    # Right away: a refusal of the next view must not leave a
                    # mesh behind that was built from the replaced image.
                    _drop_mesh(character_name, item_id, ifsig)
                    _inputs_unchanged(character_name, item_id, ifsig, step)
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
                    if forced:
                        regenerated_seed = seed
                    produced = True
            elif step == "fit":
                if forced or dirty or _fit_state(character_name, item_id, fsig, base_sha, method) != "accepted":
                    if method == gs.HAIRDECK:
                        _hairdeck_fit_step(character_name, item_id, kind, fsig, bsig, hsig, profile, ran,
                                           prefer_seed=regenerated_seed)
                    elif method == gs.SUBTRACT:
                        from app.core import garment_subtract
                        garment_subtract.run_fit(character_name, item_id, kind, fsig, bsig, profile)
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
        logger.warning("Garment run %s/%s failed at %s: %s", character_name, item_id, e.step, e)
        return _refusal(character_name, item_id, fsig, e.step, str(e), {"attempts": e.records}, ran)
    except _Refused as e:
        return _refusal(character_name, item_id, fsig, e.step, e.error, e.gates, ran)
    except Exception as e:  # noqa: BLE001 — reported as the step's failure
        logger.warning("Garment run %s/%s failed at %s: %s", character_name, item_id, step, e)
        return _refusal(character_name, item_id, fsig, step, str(e) or type(e).__name__, None, ran)


def _refit_from_source(character_name: str, item_id: str, kind: str, method: str, ifsig: str, bsig: str,
                       profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Refit before re-render (``garment_source``): when the image group ``ifsig`` has none of its own images
    and the item has an accepted source made on another base, copy it in and fit it onto the current base on the
    CPU — edit chain ``_fit``, subtract the cut + fit. ``{ok: True, fsig, ran, refit: {source…}}`` when accepted;
    ``{ok: False, error, refit}`` when refused (the copies are dropped again, the caller renders the chain); None
    when there is nothing to refit from."""
    from app.core import garment_source, garment_store as gs
    if method not in (gs.EDIT_CHAIN, gs.SUBTRACT):
        return None
    if garment_source.has_own_images(character_name, item_id, kind, method, ifsig):
        return None
    source = garment_source.find_source(character_name, item_id, kind, method, profile, ifsig)
    if source is None:
        return None
    step = "fit"
    gs.start(character_name, item_id, step)
    try:
        garment_source.materialize(character_name, item_id, kind, method, source["fsig"], ifsig)
        if method == gs.SUBTRACT:
            from app.core import garment_subtract
            fsig = gs.garment_fsig(character_name, item_id, profile=profile)  # names the copied haired views
            step = "cut"
            gs.start(character_name, item_id, step)
            garment_subtract.run_cut(character_name, item_id, fsig, ifsig,
                                     gs.subtract_ssig(character_name, item_id, profile=profile), bsig, profile,
                                     force=True)
            gs.end(character_name, item_id, step)
            step = "fit"
            gs.start(character_name, item_id, step)
            garment_subtract.run_fit(character_name, item_id, kind, fsig, bsig, profile)
            ran = ["cut", "fit"]
        else:
            fsig = ifsig
            _fit(character_name, item_id, kind, fsig, bsig, profile)
            ran = ["fit"]
    except Exception as e:  # noqa: BLE001 — any refusal or missing source: the chain is rendered instead
        error = e.error if isinstance(e, _Refused) else (str(e) or type(e).__name__)
        try:
            garment_source.drop_materialized(character_name, item_id, ifsig)
        except (OSError, ValueError):
            logger.exception("Garment %s/%s: dropping the copied source failed", character_name, item_id)
        gs.end(character_name, item_id, step)
        logger.info("Garment %s/%s: refit from %s (made on %s) refused at %s — %s; the chain is rendered",
                    character_name, item_id, source["fsig"], source.get("bsig"), step, error)
        return {"ok": False, "error": error, "refit": source}
    gs.end(character_name, item_id, step)
    logger.info("Garment %s/%s: refitted from %s (made on %s) onto %s — no image or mesh job", character_name,
                item_id, source["fsig"], source.get("bsig"), bsig)
    return {"ok": True, "fsig": fsig, "ran": ran, "refit": source}


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
    and a view of it (footwear has none)."""
    _item_, kind, order = _item_order(character_name, item_id)
    _steps(steps, order)
    _check_view(kind, view)


class _Job:
    """One queued run of a character's worker (``_queues``)."""

    def __init__(self, item_id: str, steps: Union[None, str, Iterable[str]], view: Optional[str],
                 force: bool):
        self.item_id, self.steps, self.view, self.force = item_id, steps, view, force
        self.done = threading.Event()
        self.result: Dict[str, Any] = {}

    @property
    def plain(self) -> bool:
        """A default run (first missing step on) — what a trigger asks for."""
        return self.steps is None and self.view is None and not self.force

    def key(self) -> Tuple[str, Any, Optional[str], bool]:
        """What makes two runs the same request (the steps as a tuple)."""
        steps = self.steps
        if steps is not None and not isinstance(steps, str):
            steps = tuple(steps)
        return self.item_id, steps, self.view, bool(self.force)


def _spawn_locked(character_name: str) -> None:
    """Start the worker of a character whose queue was just filled (caller
    holds ``_lock`` and has added the character to ``_active``). The head
    job becomes the character's ``_current`` run here, so the queue view
    never shows a run that is about to start as waiting."""
    queue = _queues[character_name]
    job = queue.popleft()
    _current[character_name] = job
    try:
        threading.Thread(target=_worker, args=(character_name,), daemon=True,
                         name=f"garment-{character_name}").start()
    except Exception:
        _current.pop(character_name, None)
        queue.appendleft(job)
        raise


def _abort_spawn_locked(character_name: str, item_id: str) -> None:
    """Undo a failed spawn: the character has no worker, nothing is queued."""
    from app.core import garment_store as gs
    for job in _queues.pop(character_name, None) or ():
        gs.end(character_name, job.item_id, QUEUED)
    _active.discard(character_name)
    gs.end(character_name, item_id, QUEUED)


def _worker(character_name: str) -> None:
    """Drain the character's FIFO, one run after the other: ``_current`` first
    (set by the spawn), then the head of the queue until it is empty. A run
    that fails or raises ends with its failure recorded; the next one starts."""
    from app.core import garment_store as gs
    while True:
        with _lock:
            job = _current.get(character_name)
        if job is None:  # defensive: the spawn always sets it
            with _lock:
                _queues.pop(character_name, None)
                _active.discard(character_name)
            return
        error: Optional[str] = None
        try:
            job.result = run_garment(character_name, job.item_id, steps=job.steps, view=job.view,
                                     force=job.force)
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.error("Garment run %s/%s failed: %s", character_name, job.item_id, e)
            error = str(e) or type(e).__name__
            job.result = {"ok": False, "error": error}
        with _lock:
            # Ends the ``queued`` mark of a run that had nothing to do or
            # failed before its first step (a step replaces the mark).
            gs.end(character_name, job.item_id, QUEUED, error=error)
            queue = _queues.get(character_name)
            if queue:
                _current[character_name] = queue.popleft()
                if job.item_id in {_current[character_name].item_id, *(j.item_id for j in queue)}:
                    # The item runs again (a click while it ran): it waits again.
                    gs.start(character_name, job.item_id, QUEUED)
            else:
                _queues.pop(character_name, None)
                _current.pop(character_name, None)
                _active.discard(character_name)
            job.done.set()
            if character_name not in _active:
                return


def _position_locked(character_name: str, job: "_Job") -> Dict[str, Any]:
    """``{started, queued, position, behind}`` of a job the caller just put
    into the character's FIFO (caller holds ``_lock``): ``position`` 0 and
    ``started`` True for the run in flight, else its 1-based place among the
    waiting runs, ``behind`` the item id in flight."""
    current = _current.get(character_name)
    if current is job:
        return {"started": True, "queued": False, "position": 0, "behind": None}
    queue = list(_queues.get(character_name) or ())
    return {"started": False, "queued": True, "position": queue.index(job) + 1,
            "behind": current.item_id if current is not None else None}


def start_garment(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
                  view: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Run ``run_garment`` in the character's worker thread — at once when
    the character has no garment run, else queued behind its runs (never
    refused). An identical waiting run (same item, steps, view, force) is not
    added twice; a waiting default run of the item becomes this explicit run
    in its place (its waiters get this run's result); the item's run IN
    FLIGHT does not count — this run is appended and runs after it. The item
    counts as running (``queued``) from THIS moment (the UI polls), unless it
    is in a step right now. Returns ``{started, queued, position, behind}``
    (``_position_locked``). ValueError for an invalid item, step or view
    (checked before anything is queued)."""
    from app.core import garment_store as gs
    check_run(character_name, item_id, steps=steps, view=view)
    wanted = _Job(item_id, steps, view, bool(force))
    with _lock:
        queue = _queues.setdefault(character_name, deque())
        job = next((j for j in queue if j.key() == wanted.key()), None)
        if job is None and not wanted.plain:
            job = next((j for j in queue if j.item_id == item_id and j.plain), None)
            if job is not None:
                # Explicit wins, the place in the queue stays.
                job.steps, job.view, job.force = wanted.steps, wanted.view, wanted.force
        if job is None:
            job = wanted
            queue.append(job)
        if not gs.status(character_name, item_id).get("running_step"):
            gs.start(character_name, item_id, QUEUED)
        if character_name not in _active:
            _active.add(character_name)
            try:
                _spawn_locked(character_name)
            except Exception:
                _abort_spawn_locked(character_name, item_id)
                raise
        return _position_locked(character_name, job)


def enqueue_garment(character_name: str, item_id: str) -> "_Job":
    """Queue a default run (first missing step on) of ``item_id`` behind the
    character's other runs — the per-character FIFO the triggers use
    (``after_base_model``, the outfit build). A default run of the same
    item that has not started yet is reused, never queued twice. Returns
    the job (``done`` / ``result``). ValueError like ``check_run``."""
    from app.core import garment_store as gs
    check_run(character_name, item_id)
    with _lock:
        queue = _queues.setdefault(character_name, deque())
        for job in queue:
            if job.item_id == item_id and job.plain:
                return job
        job = _Job(item_id, None, None, False)
        queue.append(job)
        if not gs.status(character_name, item_id).get("running_step"):
            gs.start(character_name, item_id, QUEUED)
        if character_name not in _active:
            _active.add(character_name)
            try:
                _spawn_locked(character_name)
            except Exception:
                _abort_spawn_locked(character_name, item_id)
                raise
    return job


class RunStarted(Exception):
    """``cancel_garment``: the item's run has started — it cannot be cancelled."""


#: ``cancel_garment``'s refusal (409) and the result a cancelled job's waiters get.
ALREADY_RUNNING = "The run has already started — a running run cannot be cancelled"
NOT_QUEUED = "No run of this item waits in the queue"
CANCELLED = "Cancelled while queued"


def cancel_garment(character_name: str, item_id: str) -> Dict[str, Any]:
    """Take the item's WAITING runs out of the character's FIFO (atomic under
    ``_lock``; the runs behind them move up). A run in flight is never
    touched: ``RunStarted`` when the item only has that one, ``LookupError``
    when the item has no run at all. The item's ``queued`` mark ends unless
    its run is in flight; a waiter of a cancelled job (``run_queued``) gets
    ``{ok: False, cancelled: True, error}``. Returns ``{item_id, cancelled
    (count), queue_running, queue}``."""
    from app.core import garment_store as gs
    with _lock:
        queue = _queues.get(character_name)
        dropped = [j for j in queue or () if j.item_id == item_id]
        current = _current.get(character_name)
        in_flight = current is not None and current.item_id == item_id
        if not dropped:
            if in_flight:
                raise RunStarted(ALREADY_RUNNING)
            raise LookupError(NOT_QUEUED)
        for job in dropped:
            queue.remove(job)
        if not in_flight:
            gs.end(character_name, item_id, QUEUED)
        for job in dropped:
            job.result = {"ok": False, "cancelled": True, "error": CANCELLED, "ran": []}
            job.done.set()
        waiting = [j.item_id for j in queue]
    logger.info("Garment %s/%s: %d waiting run(s) cancelled", character_name, item_id, len(dropped))
    return {"item_id": item_id, "cancelled": len(dropped),
            "queue_running": current.item_id if current is not None else None, "queue": waiting}


def queue_state(character_name: str, item_id: Optional[str] = None) -> Dict[str, Any]:
    """The character's garment queue for the UI: ``{queue_running, queue}``
    — the item id in flight (None when idle) and the waiting item ids in
    run order; with ``item_id`` also ``queue_position``: the 1-based place
    of the item's first waiting run (None when it waits for nothing)."""
    with _lock:
        current = _current.get(character_name)
        waiting = [j.item_id for j in _queues.get(character_name) or ()]
    out: Dict[str, Any] = {"queue_running": current.item_id if current is not None else None,
                           "queue": waiting}
    if item_id is not None:
        out["queue_position"] = waiting.index(item_id) + 1 if item_id in waiting else None
    return out


def run_queued(character_name: str, item_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Run the chains of ``item_ids`` through the character's FIFO and wait
    for every one (blocking — the outfit build calls it). item id ->
    ``run_garment``'s result, or ``{ok: False, error}`` for an item that
    could not be queued. An automatic trigger: an item whose chain failed
    for its current fsig (``cached_failure``) is not run — its result is
    that failure with ``cached: True``."""
    jobs: Dict[str, Any] = {}
    out: Dict[str, Dict[str, Any]] = {}
    for item_id in item_ids:
        failure = cached_failure(character_name, item_id)
        if failure is not None:
            # An automatic trigger: a chain that failed for this fsig waits
            # for an explicit run (Regenerate) or a new fsig.
            out[item_id] = {"ok": False, "fsig": failure.get("fsig"), "step": failure.get("step"),
                            "error": failure.get("error"), "cached": True, "ran": []}
            continue
        try:
            jobs[item_id] = enqueue_garment(character_name, item_id)
        except ValueError as e:
            out[item_id] = {"ok": False, "error": str(e)}
    for item_id, job in jobs.items():
        job.done.wait()
        out[item_id] = dict(job.result or {"ok": False, "error": "the run ended without a result"})
    return out


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
    """Hair + the own-mesh outfit pieces worn (``garment_set.worn_garments``)."""
    from app.core import garment_set
    return garment_set.worn_garments(character_name, profile=profile)


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
    """R14: after a successful base model run, every worn garment (hair and
    the own-mesh outfit pieces worn) whose fit is not accepted on the
    current base model gets a run through the character's FIFO
    (``enqueue_garment``; a run in progress may have used the old model, its
    item is queued again behind it) — when its fsig changed (new base
    signature or base images) a refit of its last accepted source first and
    the whole chain only when that is refused (``_refit_from_source``), the
    fit only when just the base model bytes changed (its images and mesh are
    cached under the unchanged fsig). A chain that failed for the current fsig is skipped
    (``garment_store.chain_failure``; a refused fit only on the base model
    it failed on). A character with hair text but no hair item gets one first
    (``_ensure_hair``). Footwear is not queued here: its fit is a Wardrobe
    preview until the body cut lands, so a shoe chain starts from the
    Wardrobe only (plan 2026-11-10-footwear-rigid-shoes Task 25 queues the
    refit of a shod wearer). True if a run was queued. Never raises."""
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
                if _item(character_name, item_id)[1] == _footwear():
                    continue  # started from the Wardrobe only (docstring)
                fsig = gs.garment_fsig(character_name, item_id, profile=profile)
                method = gs.garment_method(character_name, item_id, profile=profile)
            except ValueError:
                continue
            if _fit_state(character_name, item_id, fsig, base[1], method) == "accepted":
                continue
            if gs.chain_failure(character_name, item_id, fsig, base_model_sha=base[1]) is not None:
                logger.info("Garment %s/%s: failed for fsig %s — waits for an explicit run",
                            character_name, item_id, fsig)
                continue
            enqueue_garment(character_name, item_id)
            logger.info("Garment %s/%s: base model changed, chain queued", character_name, item_id)
            started = True
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
    return _image(character_name, item_id, gs.image_fsig(character_name, item_id), step, view, attempt)


def preview_path(character_name: str, item_id: str, method: str = "") -> Optional[Path]:
    """The GLB the Hair tab shows: the current-fsig fit when it exists, else
    the fit served on the current base model, else the newest accepted fit
    of the current method. None when there is no fit at all.

    ``method`` naming ANOTHER method than the current one: that method's
    newest accepted fit (on the current base model first, else on any) —
    the tab's "Other method" preview. ValueError for an unknown method."""
    from app.core import base_body, garment_store as gs
    from app.core.garment_hair import HAIR_METHODS
    from app.models.character import get_character_profile
    if method and method not in HAIR_METHODS:
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


def other_methods_info(character_name: str, item_id: str, *,
                       profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The Hair tab's collapsed "Other methods": one entry per hair method NOT
    selected that has a result — ``{method, preview_url, created_at, metrics,
    colour, on_current_base}`` of the accepted fit it would serve if selected
    (``_other_fit``) — newest first; ``[]`` when none has one (or the item is
    no hair). Selecting such a method generates nothing: its fit is served as
    it is (a fit on an older base model stays stale until the method runs)."""
    from app.core import garment_hair
    from app.core.http_files import content_version
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    _item_, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        return []
    current = garment_hair.hair_method(character_name, profile=profile)
    hits = [(m, _other_fit(character_name, item_id, m, profile)) for m in garment_hair.HAIR_METHODS if m != current]
    hits = [(m, h) for m, h in hits if h is not None]
    hits.sort(key=lambda mh: _stamp(mh[1][0]) or 0, reverse=True)
    out: List[Dict[str, Any]] = []
    for method, (path, record, on_base) in hits:
        try:
            url: Optional[str] = _url(character_name, item_id, "model", content_version(path), f"&method={method}")
        except OSError:
            url = None
        out.append({"method": method, "preview_url": url, "created_at": record.get("created_at"),
                    "metrics": record.get("metrics") or {}, "colour": record.get("colour"),
                    "on_current_base": on_base})
    return out


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
    what HairDeck gets — the accepted beard-free copy of the profile picture
    (``garment_beard.cached``) when there is one, else the current profile
    picture (the ``hsig`` is made from it), ``prep`` /
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
    folder = gs.hairdeck_dir(character_name, item_id, gs.garment_hsig(character_name, item_id, profile=profile))
    if which == "input":
        return _hairdeck_input(folder, current_profile_image(character_name, profile=profile))
    path = folder / f"{which}.png"
    return path if path.is_file() else None


def _hairdeck_input(folder: Path, source: Optional[Path]) -> Optional[Path]:
    """What HairDeck gets for ``source`` (the profile picture) in the job
    ``folder``: its accepted beard-free copy, else ``source``."""
    from app.core import garment_beard
    if source is None:
        return None
    return garment_beard.cached(folder, source) or source


def hairdeck_panel(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The Hair tab's HairDeck section for the CURRENT ``hsig`` (whichever
    method is selected): ``{hsig, status, attempt, seed, job_seed,
    seeds_tried, backend, created_at, error, notes, attempts, images, colour,
    placement}``.

    - ``seed``: the seed the fit chose (the current fsig's fit when it was
      made from this job, else the newest HairDeck fit of it), without such
      a fit the newest HairDeck run's seed (``job_seed``); ``seeds_tried``:
      how many seeds HairDeck has made for this hsig;
    - ``attempts``: the refused fit attempts of the job (gate records);
    - ``images``: ``input`` / ``prep`` / ``model_input`` -> ``{url, model,
      created_at}`` (tile meta for ``RefImage``) or None when absent;
      ``input_source``: ``beard_free`` when ``input`` is the beard-free copy
      of the profile picture (``garment_beard``), else ``profile``;
    - ``colour``: ``{target, source, auto, profile, fitted}`` — ``target``
      the manual ``#rrggbb`` or None, ``source`` ``"override"``,
      ``"profile"`` (automatic: the profile's named hair colour,
      ``garment_hair.profile_hair_colour``) or ``"hairdeck"`` (automatic
      without a named colour: HairDeck's own vertex colours), ``auto``
      HairDeck's own hair colour from the job's ``info.json`` as ``#rrggbb``
      (None without), ``profile`` ``{name, hex}`` of the named colour (None
      without), ``fitted`` the newest HairDeck fit's record ``colour``
      (``_hairdeck_colour``; None without a fit);
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
    sent = _hairdeck_input(folder, source)
    for which in HAIRDECK_IMAGES:
        path = sent if which == "input" else folder / f"{which}.png"
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
    named = garment_hair.profile_hair_colour(character_name, profile=profile)
    newest = _newest_fit(character_name, item_id, gs.HAIRDECK)
    colour = {"target": override or None,
              "source": "override" if override else ("profile" if named else "hairdeck"),
              "auto": _rgb_hex(info.get("hair_color")) if isinstance(info, dict) else None,
              "profile": named, "fitted": newest[1].get("colour") if newest else None}
    placement = {**garment_hair.hair_placement(profile),
                 "default_forward_m": garment_hairdeck.DEFAULT_FORWARD_M,
                 "limits": {"forward_m": garment_hairdeck.FORWARD_LIMIT_M,
                            "tilt_deg": garment_hairdeck.TILT_LIMIT_DEG},
                 "fitted": newest[1].get("placement") if newest else None}
    fitted_seed = None
    current = gs.read_record(gs.garment_path(character_name, item_id,
                                             gs.garment_fsig(character_name, item_id, profile=profile),
                                             "fit").with_suffix(".json"))
    for record in (current, newest[1] if newest else {}):
        inputs = record.get("inputs") or {}
        if record.get("accepted") is True and gs.fit_method(record) == gs.HAIRDECK and inputs.get("hsig") == hsig:
            fitted_seed = inputs.get("seed")
            break
    return {"hsig": hsig, "status": job["status"], "attempt": job["attempt"],
            "seed": fitted_seed if fitted_seed is not None else job["seed"], "job_seed": job["seed"],
            "seeds_tried": len(_job_seeds(_hairdeck_record(character_name, item_id, hsig))),
            "backend": job["backend"], "created_at": job["created_at"], "error": job["error"],
            "notes": job["notes"], "attempts": job["fit_attempts"], "images": images, "colour": colour,
            "placement": placement,
            "input_source": "beard_free" if sent is not None and sent != source else "profile"}


def _mm(value: Any) -> Optional[float]:
    """A stored thickness in mm, rounded to 0.01 (None when absent)."""
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def garment_info(character_name: str, item_id: str) -> Dict[str, Any]:
    """UI info of one garment (the Hair tab): fsig, the method and its
    source, description, every step's files and gate numbers (the steps of
    the CURRENT method; HairDeck adds ``hsig``), why the served fit is not
    the current one (``stale_reasons``), the run status and the preview URL.
    ``served_fsig`` None = no hair is served (e.g. the selected method has no
    accepted fit yet). Every kind may report ``fit_algorithm_updated`` (the
    served fit predates ``garment_fit.FIT_VERSION``; the boot sweep
    ``garment_refit`` refits it). HairDeck hair adds the stale reasons
    ``hairdeck_changed`` (another profile picture or HairDeck setting than
    the served fit's job), ``colour_changed`` (another colour override) and
    ``placement_changed`` (another manual forward/tilt, or a fit from before
    the placement correction). Subtract hair adds ``shape_changed`` (the
    served fit's cut has another shape than the current cut / shell) and
    ``shell_changed`` (a shell of another thickness) — the next run re-cuts
    on the CPU, no mesh job.
    ``failed`` also reports the persisted failure of the current fsig after
    a restart (automatic triggers skip it until an explicit run).
    ``queue_position`` / ``queue_running`` (``queue_state``): the 1-based
    place of the item's next waiting run in the character's garment queue
    (None = none waits) and the item id in flight (None = idle) — the UI's
    "Queued behind <item>" while ``running_step`` is ``queued``.
    ``refit`` (``garment_source``): the current fit was refitted from a source
    made on an older base — ``{source_bsig, source_fsig, materialized_from,
    registration {shift, scale} | None, first_step, created_at}`` (the tab
    shows "Refitted from the previous base" + Re-render = an explicit run of
    ``first_step``), None otherwise.
    ``body`` (mesh mode, plan 2026-11-10-outfit-body-mesh-mode Task 2): the
    piece's fit on the outfit body the CURRENT outfit model stands on
    (``body_fit_info``; ``body_id`` repeats its id), None on the base body —
    ``steps.fit`` stays the chain's fit on the base model.
    Footwear has its own panel (``garment_footwear.info``: the per-item
    source steps, the insole, the fit).
    ValueError for an invalid item."""
    from app.core import base_body, garment_hair, garment_store as gs
    from app.core.http_files import content_version
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_profile
    _item_, kind = _item(character_name, item_id)
    profile = get_character_profile(character_name) or {}
    if kind == _footwear():
        from app.core import garment_footwear
        return gs.finite_json(garment_footwear.info(character_name, item_id, profile=profile))
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
        ifsig = gs.image_fsig(character_name, item_id, profile=profile)
        for step in gs.steps_for(kind, method):
            if step in gs.IMAGE_STEPS:
                steps[step] = {v: _image_info(character_name, item_id, ifsig, step, v) for v in gs.GARMENT_VIEWS}
            elif step in ("mesh_source", "cut"):
                from app.core import garment_subtract
                steps[step] = garment_subtract.step_info(character_name, item_id, step, fsig, profile=profile)
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
            from app.core.garment_fit import FIT_VERSION
            if record.get("fit_version") != FIT_VERSION.get(str(record.get("kind"))):
                stale.append("fit_algorithm_updated")
            if method == gs.HAIRDECK and gs.fit_method(record) == gs.HAIRDECK:
                if used.get("hsig") != hsig:
                    stale.append("hairdeck_changed")
                if (used.get("colour") or "") != garment_hair.hair_colour_override(profile):
                    stale.append("colour_changed")
                if used.get("placement") != garment_hair.hair_placement(profile):
                    stale.append("placement_changed")
            if method == gs.SUBTRACT and gs.fit_method(record) == gs.SUBTRACT:
                shape = garment_hair.subtract_shape(character_name, profile=profile)
                if (used.get("shape") or record.get("shape")) != shape:
                    stale.append("shape_changed")
                elif shape == "shell" and _mm(used.get("shell_mm")) != _mm(garment_hair.shell_mm(profile)):
                    stale.append("shell_changed")
    preview = preview_path(character_name, item_id)
    preview_url = None
    if preview is not None:
        try:
            preview_url = _url(character_name, item_id, "model", content_version(preview))
        except OSError:
            preview_url = None
    try:
        body = body_fit_info(character_name, item_id, profile=profile)
    except Exception:  # noqa: BLE001 — the tab still shows the base chain
        logger.exception("Body fit info %s/%s failed", character_name, item_id)
        body = None
    refit = None
    if fsig:
        # Refitted from a source made on an older base (``garment_source``): the tab offers Re-render.
        fit_record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
        if fit_record.get("accepted") is True and fit_record.get("refitted") is True:
            source = fit_record.get("source") or {}
            frame = fit_record.get("frame") or (gs.read_record(gs.garment_path(
                character_name, item_id, fsig, "prepared").with_suffix(".json")).get("frame") or {})
            reg = frame.get("registration") or {}
            refit = {"source_bsig": source.get("bsig"), "source_fsig": source.get("fsig"),
                     "materialized_from": source.get("materialized_from"),
                     "registration": {"shift": reg.get("shift_abs"), "scale": reg.get("scale")} if reg else None,
                     "first_step": gs.steps_for(kind, method)[0], "created_at": fit_record.get("created_at")}
    status = gs.status(character_name, item_id)
    queue = queue_state(character_name, item_id)
    failed = status["failed"]
    if failed is None and not status["running_step"] and fsig:
        # After a restart the in-memory status is empty: the persisted
        # failure of the current fsig still holds the piece back.
        record = gs.chain_failure(character_name, item_id, fsig,
                                  base_model_sha=base[1] or "")
        if record is not None:
            failed = {"step": record.get("step"), "error": record.get("error"), "gates": None,
                      "failed_at": record.get("failed_at")}
    # finite_json: a NaN in an in-memory failure's gates must not fail the whole tab's JSON encoding
    return gs.finite_json({
        "item_id": item_id, "kind": kind, "fsig": fsig, "method": method, "method_source": method_source,
        "hsig": hsig, "description": inputs.get("description") or inputs.get("prompt_fragment") or "",
        "steps": steps, "stale_reasons": stale,
        "running_step": status["running_step"], "started_at": status["started_at"],
        "queue_position": queue["queue_position"], "queue_running": queue["queue_running"],
        "failed": failed, "preview_url": preview_url, "served_fsig": served_fsig, "refit": refit,
        "body": body, "body_id": body["body_id"] if body else None})

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
