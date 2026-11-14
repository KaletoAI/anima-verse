"""Garment chain orchestration — runs a character's own-mesh garment through
its steps, fits it onto the base body and starts the assembly (plan
``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R3, R8, R10,
R11, R13, R14, Task 8).

Steps of a kind (``garment_store.GARMENT_STEPS``; clothing — an own-mesh
outfit piece, plan ``2026-11-09-base-body-phase5-mesh-items.md``: ``worn →
ghost → cutout → mesh → fit``; hair by HairDeck: ``hairdeck → fit``, below;
hair in the body mesh has no steps). Every step caches its accepted output on disk under
the garment fingerprint ``fsig`` (R13), so a run starts at the first step
whose accepted output is missing — or at an explicit step. A step that
produced new output makes every later step run again (``force`` propagates
downstream); one that was served from the cache does not.

- image steps (``garment_images``): per view, the BACK first
  (``EDIT_VIEW_ORDER``) unless the kind's step names its own order
  (``EDIT_STEPS[step]["views"]``; clothing ``worn``: the front first, the
  back is drafted from it). The kind's pair step (``PAIR_STEP`` of its
  module, ``garment_images.kind_module``: ``ghost``) additionally needs front
  and back to agree (``pair_agree``: the hems, ``hems_agree``): a front
  attempt is checked against the accepted back's record (``_pair_check``;
  clothing since Ruling A17: the WORN back's hem, never the ghost back's),
  and a pair that still disagrees — a new back, or both views from before —
  renders again the view the kind's ``pair_redo`` names (clothing: the back
  when its hem is farther from its worn back than the front's from its worn
  front), then, still disagreeing, the front against the back, with its own
  attempts. A disagreeing pair never ends a run without a new attempt. The
  accepted images of the kind's ``REGATE_ACCEPTED_STEPS`` are re-gated from
  their files when their record predates the gate (``_regate_accepted``);
  one the current gate refuses is stale (``garment_images.stale_accepted``),
  never done and rendered again. Ruling A46b: the garment payload re-gates
  them as well, once and in the background (``regate_shown``), so the
  Wardrobe and Auto follow the current verdict before any run. The kind's ``front_hints`` give the
  front edit what the back shows (clothing: nothing);
- every image step checks after each view that the run's inputs (base views,
  the kind's description: ``garment_fsig``) did not change meanwhile — a base view
  regenerated during the run refuses with ``INPUTS_CHANGED_ERROR`` instead of
  gating images of the new base against images of the old one;
- ``mesh`` (``garment_mesh.generate``): built from both cut-outs; a new
  accepted image deletes the prepared mesh of the same fsig (it was built
  from the replaced images);
- ``fit``: the CURRENT base model (rigged + unrigged, read under the
  publication lock), ``garment_fit.fit_clothing`` and ``CLOTHING_GATES``
  with the piece's slots. On acceptance the
  fit GLB ``garments/{item}_{fsig}.glb`` (= the rigged base with the garment
  grafted on) and its record are written, the distance tier is decimated to
  ``low/``, and the assembly of the served outfit model is scheduled.

Refit before re-render (``garment_source``, user decision 2026-11-10): a
default run whose current image group has none of its own images yet (new
base images name a new fsig) first copies in the item's last accepted
source — images + mesh made on an older base — and fits it onto the current
base on the CPU (``_fit``), its ghost
registered from the source's base front onto the current one. Accepted: the
run ends there (``refit`` in the result, ``refitted`` in the fit record).
Refused: the copies go and the same run renders the chain. An explicit run of
an image step on such a group (Re-render) drops the copies and renders from
the first step.

A refusal ends the run (``{ok: False, step, error, gates}`` + the in-memory
status); nothing downstream runs, and an already accepted fit keeps being
served (R11 — a refused re-run never makes the figure bald).

A hairstyle made by HairDeck (``garment_hair.hairstyle_mode``; plan
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

A hairstyle made by HAAR (strand-hair spec 2026-11-13 § 6.3) runs ``haar → fit``:

- ``haar``: ``HAAR_SEEDS`` strand jobs (``generate_strands``, the hairstyle's text as the prompt, seeds 1, 2, 3,
  then 4, 5, 6 …) into ``raw/{item}_{ssig}/s{seed}/`` — a plain run only when no seed is stored, the step's own
  button always (the next seeds; the older ones stay variants). One hub operation per run, resumed after a
  restart by collecting its submitted jobs (``HAAR_OP_KIND``);
- ``fit``: ``garment_haar.fit_haar`` (CPU) of every seed without a current verdict, the verdicts in the
  folder's record, the SERVED seed (the user's ``haar_seed`` while stored, else the best passing one) published
  under the fsig that names it (``_haar_fit_step``). No passing seed and no pick refuses with
  ``NO_VARIANT_PASSED``.

Footwear (kind ``footwear``, method ``shoe``; plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``) runs
``garment_footwear.run_chain`` instead (``_run_locked`` dispatches it first):
the per-item source steps ``source → empty → cutout → mesh → insole`` under
the ITEM lock — two wearers never run a step twice, the later one finds it
done — then the wearer's ``fit`` (not wired yet; the chain ends after the
insole). Same queue, status and cancel as every garment.

Load is never a failure record (every chain): a step that ends in a
``BackendBusyError`` or ``MediaGenerationDisabled`` — directly, or as the
cause of a ``MeshAttemptFailed`` — answers ``{ok: False, …, retry_later:
True}``, the in-memory status shows it and nothing is persisted, so
``cached_failure`` stays None and automatic triggers try again. A refusal by
a gate, and any other defect, is persisted as before.

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
``enqueue_garment`` (the Build's ``run_queued`` — every automatic trigger
reaches the chains through the Build, ``after_base_model`` included)
appends a default run behind the others. Several garments of
one character run one after the other, each request once; a failed run never
holds the queue (the next one starts). ``queue_state`` is the UI view;
``cancel_garment`` takes an item's waiting runs out (never the one in flight).

Ruling A30: a CPU refit (a run of the fit step alone, ``_fit_only``) of an
item that has no run in flight or waiting does NOT queue behind the
character's run of ANOTHER item — it starts at once on a thread of its own
(``_side``, "beside" the FIFO) and computes on a ``refit_pool`` slot. It
holds only the item's run lock (``garment_store.run_item_lock``), never the
character's (``char_lock``), which a chain waiting on hub work holds for
minutes. Runs of the same item stay serialized (every run holds the item
lock; an item with a run in flight or waiting queues as before), and
nothing that changes or depends on the base body is passed: while a
base-body step is in flight (``figure_build.base_step_in_flight``) or the
character's 3D generation guard is held (``model3d.generation_running``:
a base model run, the Build's model steps) the refit queues behind the
FIFO's run as before. The character-wide refit sweep
(``garment_refit.refit_character``) never runs beside one (``hold_all``).

Ruling A33: a per-view button (the step grid's Generate / Regenerate of one
view) runs ONLY that view of that step — no other view of the step, not even
a stale one, no later step, no pair repair. The views it reads first
(``view_needs``: the previous step's same view, a drafted back's front, the
pair step's back) must be accepted: ``check_run`` refuses with
``PrerequisiteMissing`` (409) before anything is queued or spent, unless the
caller asks for them (``prerequisites``, the button's explicit "first"
action): then the run makes them first, in chain order. A new front of a
drafted step re-drafts its back in the same run (``_follow_ups``).
``view_plans`` states each button's jobs, follow-up and prerequisites before
the click. Run all is unchanged: the chain, accepted views skipped.

An own-mesh outfit piece (kind ``clothing``) whose fit was accepted by a run
asks ``base_body.after_mesh_item_ready``: a "piece ready" request of the
character's Build, which builds the figure with the piece grafted.

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
from contextvars import ContextVar
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
# Ruling A30: per character the CPU refits running beside its FIFO, item id -> job (each on a thread of its
# own, holding only the item's run lock).
_side: Dict[str, Dict[str, "_Job"]] = {}
# Characters whose refit sweep holds every garment of theirs (``hold_all``): no refit starts beside the FIFO.
_held: set = set()
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
#: Ruling A20: checked BEFORE each composite onto a base view (``garment_images._drafted_back``) — a base view
#: rendered again while the chain ran (a live test's jacket, 2026-11-13: attempt 2 composited onto the base back
#: re-rendered meanwhile and was refused for "drift"). The true reason, before any composite of the new base.
BASE_VIEW_CHANGED_ERROR = ("Base view changed meanwhile ({views}) — the base body was rendered again while the "
                           "chain ran; run the chain again")


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


def _check_view_steps(wanted: Optional[List[str]], view: Optional[str]) -> None:
    """Ruling A33: a ``view`` names ONE image step (the step grid's per-view buttons) — ValueError otherwise."""
    from app.core.garment_store import IMAGE_STEPS
    if view is not None and (wanted is None or len(wanted) != 1 or wanted[0] not in IMAGE_STEPS):
        raise ValueError("A view runs one image step")


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


def _kind_inputs(kind: str, character_name: str, profile: Dict[str, Any], item_id: str,
                 state: Optional[str] = None) -> Dict[str, Any]:
    from app.core import garment_store
    return garment_store._kind_inputs(kind, character_name, profile, item_id, state)


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
    from app.core.garment_store import accepted_image
    return accepted_image(path)


def _accepted_gate(path: Path) -> Optional[Dict[str, Any]]:
    """The gate record of the attempt an accepted image came from. A view made from the worn view (Ruling A46,
    ``attempt`` 0, ``source`` ``garment_from_worn.RECORD_SOURCE``) keeps its one gate record as ``first``
    (Ruling A46c: before, attempt 0 read ``_ORDINALS[-1]`` — nothing — so its pair never counted as agreeing)."""
    from app.core.garment_from_worn import RECORD_SOURCE
    from app.core.garment_store import read_record
    record = read_record(path.with_suffix(".json"))
    try:
        attempt = int(record.get("attempt") or 0)
    except (TypeError, ValueError):
        return None
    if attempt < 1:
        ordinal = _ORDINALS[0] if record.get("source") == RECORD_SOURCE else None
    else:
        ordinal = _ORDINALS[attempt - 1] if attempt <= len(_ORDINALS) else None
    gate = (record.get("gates") or {}).get(ordinal) if ordinal else None
    return gate if isinstance(gate, dict) else None


def _kind_module(kind: str):
    from app.core.garment_images import kind_module
    return kind_module(kind)


def _pair(character_name: str, item_id: str, kind: str, fsig: str) -> Tuple[bool, Dict[str, Any]]:
    """Whether the accepted images of both views of the kind's pair step agree
    (the kind module's ``pair_agree``: hair ends / hems at the same height),
    with both gate records."""
    from app.core.garment_images import skipped_view
    module = _kind_module(kind)
    assumed = _ASSUMED.get() or {}
    gates: Dict[str, Any] = {}
    by_user = False
    for view in ("front", "back"):
        key = (module.PAIR_STEP, view)
        if key in assumed:   # ``use_plans``: the view as it would be after a "Use this"
            gates[view] = (assumed[key] or {}).get("gate")
            by_user = by_user or bool((assumed[key] or {}).get("user"))
            continue
        path = _image(character_name, item_id, fsig, module.PAIR_STEP, view)
        gates[view] = _accepted_gate(path) if _accepted(path) else None
        by_user = by_user or (gates[view] is not None and _user_taken(path))
    if gates["front"] and skipped_view(character_name, item_id, fsig, module.PAIR_STEP, "back"):
        return True, gates  # no back to agree with (an empty drafted back)
    if not gates["front"] or not gates["back"]:
        return False, gates
    if by_user:
        return True, gates  # Ruling A37: a view the user took by hand is never rendered again for the pair
    return module.pair_agree(gates["front"], gates["back"]), gates


def _user_taken(path: Path) -> bool:
    """Whether the accepted image at ``path`` was taken by the user against its gate (Ruling A37)."""
    from app.core.garment_store import read_record
    return isinstance(read_record(path.with_suffix(".json")).get("user_accepted"), dict)


def _pair_check(character_name: str, item_id: str, kind: str, fsig: str, *, repair: bool = False):
    """The pair check of a FRONT attempt of the pair step: against the
    accepted back's gate record (the kind module's ``pair_reason`` —
    clothing: the WORN back's hem, Ruling A17 b); ``repair`` (a front
    rendered again because the pair disagrees, the back staying) the kind's
    ``pair_repair_reason`` (the ghost back's hem as well). None without a
    back (an empty drafted back, ``garment_images.skipped_view``)."""
    from app.core.garment_images import skipped_view
    module = _kind_module(kind)
    if skipped_view(character_name, item_id, fsig, module.PAIR_STEP, "back"):
        return lambda record: None
    back = _accepted_gate(_image(character_name, item_id, fsig, module.PAIR_STEP, "back")) or {}
    reason = getattr(module, "pair_repair_reason", None) if repair else None
    return lambda record: (reason or module.pair_reason)(record, back)


def _pair_redo(kind: str, gates: Dict[str, Any]) -> str:
    """The view a disagreeing pair renders again: the kind's ``pair_redo``
    (clothing: the one farther from its worn view, Ruling A17 c), else the
    front."""
    redo = getattr(_kind_module(kind), "pair_redo", None)
    if redo is None or not gates.get("front") or not gates.get("back"):
        return "front"
    return redo(gates["front"], gates["back"])


def _regate_accepted(character_name: str, item_id: str, kind: str, fsig: str, state: Optional[str]) -> None:
    """Ruling A17 (d): the accepted images of the kind's
    ``REGATE_ACCEPTED_STEPS`` whose records predate the gate are gated again
    from their files before the run decides what is done
    (``garment_images.regate_accepted``); one refused by the rules the kind
    names for the step is stale and renders again. A failure only logs —
    the step reports its own."""
    from app.core import garment_images
    from app.core.garment_store import GARMENT_VIEWS
    for step in getattr(_kind_module(kind), "REGATE_ACCEPTED_STEPS", ()) or ():
        for v in GARMENT_VIEWS:
            try:
                garment_images.regate_accepted(character_name, item_id, fsig, step, v, state=state)
            except Exception as e:  # noqa: BLE001 — the step itself reports a missing input
                logger.warning("Garment %s/%s: re-gating the accepted %s %s failed: %s", character_name, item_id,
                               step, v, e)


# --- Ruling A46b: an accepted image gated under an older version is re-gated when it is shown ---------------
#
# A gate version change (A46: 6 -> 7, added parts) used to reach an accepted image only when a run started
# (``_regate_accepted``), so the Wardrobe showed the old verdict meanwhile — and Auto, which follows the
# verdict (``garment_from_worn.resolve``), kept naming the generated view of a view the current gate refuses.
# Now the garment payload (``garment_info``) asks ``regate_shown``: an accepted image of the kind's
# ``REGATE_ACCEPTED_STEPS`` whose record predates the gate is gated again ONCE, on a background thread — a
# re-gate is CPU image work (Glut's scale top, 2026-11-14, copies: 0.40-0.68 s per view with the cached masks,
# 25-35 s with a cold mask cache), too slow for a GET. The new record carries the current ``gate_version``,
# so it is never judged again; the payload names the views in ``regate_checking`` (the UI: "Checking…") until
# it is written. Nothing is rendered and no image changes: a record the hem snap would correct is left for the
# next run (``regate_accepted(snap=False)``), and so is any view while a run of the item holds its lock (the
# run re-gates it first).
_regate_lock = threading.Lock()
# (character, item, fsig) whose re-gate is queued or running.
_regate_pending: set = set()
# (character, item, fsig, step, view) -> the sidecar stamp a re-gate left unchanged (a hem snap left for the
# run, a missing input, a failure): not asked again until the sidecar changes or the server restarts.
_regate_left: Dict[Tuple[str, str, str, str, str], Tuple[int, int]] = {}
_regate_worker = None


def _sidecar_stamp(path: Path) -> Tuple[int, int]:
    try:
        st = path.with_suffix(".json").stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def _regate_wanted(character_name: str, item_id: str, kind: str, fsig: str) -> List[Tuple[str, str]]:
    """``[(step, view)]`` whose accepted image ``regate_shown`` would gate again (``garment_images.regate_due``,
    minus the ones a re-gate left unchanged at the same sidecar). Sidecar reads only."""
    from app.core import garment_images
    from app.core.garment_store import GARMENT_VIEWS
    out: List[Tuple[str, str]] = []
    for step in getattr(_kind_module(kind), "REGATE_ACCEPTED_STEPS", ()) or ():
        for view in GARMENT_VIEWS:
            if not garment_images.regate_due(character_name, item_id, fsig, step, view):
                continue
            stamp = _sidecar_stamp(_image(character_name, item_id, fsig, step, view))
            with _regate_lock:
                if _regate_left.get((character_name, item_id, fsig, step, view)) == stamp:
                    continue
            out.append((step, view))
    return out


def _regate_shown_task(character_name: str, item_id: str, kind: str, fsig: str) -> None:
    """The background half of ``regate_shown``: under the item's run lock (taken without waiting — a run that
    holds it re-gates on its own), for the image group that is still the item's current one."""
    from app.core import garment_images
    from app.core.garment_store import garment_fsig, run_item_lock
    key = (character_name, item_id, fsig)
    lock = run_item_lock(character_name, item_id)
    try:
        if not lock.acquire(blocking=False):
            return
        try:
            try:
                current = garment_fsig(character_name, item_id)
            except ValueError:
                current = None
            if current != fsig:
                return
            for step, view in _regate_wanted(character_name, item_id, kind, fsig):
                final = _image(character_name, item_id, fsig, step, view)
                try:
                    record = garment_images.regate_accepted(character_name, item_id, fsig, step, view, snap=False)
                except Exception as e:  # noqa: BLE001 — shown as it was; the next run re-gates and reports
                    logger.warning("Garment %s/%s: re-gating the shown %s %s failed: %s", character_name, item_id,
                                   step, view, e)
                    record = None
                if record is None:
                    with _regate_lock:
                        _regate_left[(character_name, item_id, fsig, step, view)] = _sidecar_stamp(final)
        finally:
            lock.release()
    finally:
        with _regate_lock:
            _regate_pending.discard(key)


def regate_shown(character_name: str, item_id: str, kind: str, fsig: Optional[str]) -> List[Dict[str, str]]:
    """Ruling A46b (the block above): the accepted images of the item whose gate record predates the gate,
    queued for one re-gate on the background worker; returns them as ``[{step, view}]`` — the payload's
    ``regate_checking`` ([] when none is due). Called by every garment payload; cheap when nothing is due."""
    if not fsig or not getattr(_kind_module(kind), "REGATE_ACCEPTED_STEPS", None):
        return []
    try:
        wanted = _regate_wanted(character_name, item_id, kind, fsig)
    except Exception:  # noqa: BLE001 — the payload still shows the stored records
        logger.exception("Garment %s/%s: reading the records to re-gate failed", character_name, item_id)
        return []
    if not wanted:
        return []
    key = (character_name, item_id, fsig)
    with _regate_lock:
        if key not in _regate_pending:
            global _regate_worker
            if _regate_worker is None:
                from concurrent.futures import ThreadPoolExecutor
                _regate_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="garment-regate")
            _regate_pending.add(key)
            _regate_worker.submit(_regate_shown_task, character_name, item_id, kind, fsig)
    return [{"step": step, "view": view} for step, view in wanted]


def _front_hints(character_name: str, item_id: str, fsig: str, kind: str, step: str,
                 view: str) -> Optional[Dict[str, Any]]:
    """The prompt hints of an edit from what the back shows (the kind
    module's ``front_hints``)."""
    return _kind_module(kind).front_hints(character_name, item_id, fsig, step, view)


def _inputs_unchanged(character_name: str, item_id: str, fsig: str, step: str, state: Optional[str] = None) -> None:
    """``_Refused`` when the fsig of the run's images is no longer the
    current one (``garment_store.garment_fsig`` in the run's open / closed
    ``state`` — a run of the state the piece is not worn in now is judged by
    its own inputs, never aborted for the worn state's)."""
    from app.core.garment_store import garment_fsig
    if garment_fsig(character_name, item_id, state=state) != fsig:
        raise _Refused(step, INPUTS_CHANGED_ERROR, None)


def _base_view_shas(character_name: str, bsig: str) -> Dict[str, str]:
    """sha256 of the plain body's ``GARMENT_VIEWS`` now (what the fsig of a run hashes as ``base_images``)."""
    from app.core import base_body
    from app.core.garment_store import GARMENT_VIEWS
    from app.core.model_refs import find_ref_image
    return {view: base_body.file_sha256(find_ref_image(character_name, base_body._kind(view), bsig))
            for view in GARMENT_VIEWS}


def _composite_guard(character_name: str, bsig: str, shas: Dict[str, str], step: str):
    """The check a drafted back runs before each composite (Ruling A20): ``_Refused(step,
    BASE_VIEW_CHANGED_ERROR)`` when a base view differs from the one the run started on (``shas``)."""
    def check() -> None:
        now = _base_view_shas(character_name, bsig)
        changed = [view for view, sha in shas.items() if now.get(view) != sha]
        if changed:
            logger.info("Garment run %s: base view %s changed meanwhile — no composite onto it",
                        character_name, ", ".join(changed))
            raise _Refused(step, BASE_VIEW_CHANGED_ERROR.format(views=", ".join(changed)), None)
    return check


def _mesh_done(character_name: str, item_id: str, fsig: str) -> bool:
    from app.core.garment_store import garment_path
    return _accepted(garment_path(character_name, item_id, fsig, "prepared"))


def _fit_state(character_name: str, item_id: str, fsig: str, base_model_sha: str,
               method: str = "edit_chain", profile: Optional[Dict[str, Any]] = None) -> str:
    """``accepted`` (on the current base model, from the current prepared
    mesh — HairDeck: from its seed's hair, still stored unchanged under an
    accepted job; HAAR: from its seed's strands, still stored unchanged),
    ``stale`` (accepted on another base model, or by an
    older fit algorithm: ``garment_fit.expected_fit_version``), ``outdated``
    (accepted, but the prepared mesh / HairDeck hair / HAAR strands it was fitted from was
    replaced or removed) or ``missing``. Footwear (method ``shoe``):
    ``garment_footwear.fit_state`` on the base (``outdated`` there: the shoe
    source mesh or its insole was replaced). A clothing fit made with other fit settings than the piece's current
    ones (Ruling A47, ``garment_fit_settings``; ``profile`` read when not given) is ``stale`` too."""
    from app.core.garment_store import HAAR, HAIRDECK, SHOE, garment_path, read_record
    if method == SHOE:
        from app.core import garment_footwear
        return garment_footwear.fit_state(character_name, item_id, fsig, base_model_sha)
    fit = garment_path(character_name, item_id, fsig, "fit")
    record = read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    if not base_model_sha or record.get("base_model_sha256") != base_model_sha:
        return "stale"
    from app.core.garment_fit import expected_fit_version
    if record.get("fit_version") != expected_fit_version(record):
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
    if method == HAAR:
        strands = _haar_strands_file(character_name, item_id, record.get("inputs") or {})
        if strands is None or (record.get("inputs") or {}).get("strands_sha256") != _sha(strands):
            return "outdated"
        return "accepted"
    prepared = garment_path(character_name, item_id, fsig, "prepared")
    if (record.get("inputs") or {}).get("prepared_sha256") != _sha(prepared) or not prepared.is_file():
        return "outdated"
    if _settings_changed(character_name, item_id, record, profile):
        return "stale"  # Ruling A47: the fit settings changed — the chain re-runs the fit only (CPU)
    return "accepted"


def _settings_changed(character_name: str, item_id: str, record: Dict[str, Any],
                      profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a clothing fit ``record`` was made with other fit settings than the piece's current ones
    (``garment_fit_settings.changed``; other kinds have none)."""
    from app.core import garment_fit_settings, garment_set
    if str(record.get("kind") or "") != garment_set.CLOTHING:
        return False
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    return garment_fit_settings.changed(record, profile, item_id)


#: ``use_plans`` (Ruling A37): image views assumed as they would be after a "Use this" — ``{(step, view):
#: None (dropped: not done) | {gate, user} (accepted with that gate record; ``user`` = taken against it)}``.
#: Read by ``_view_done``, ``_done`` and ``_pair``, so ``run_estimate`` prices the state after the click.
_ASSUMED: ContextVar[Optional[Dict[Tuple[str, str], Optional[Dict[str, Any]]]]] = ContextVar(
    "garment_assumed_views", default=None)


def _view_done(character_name: str, item_id: str, fsig: str, step: str, view: str) -> bool:
    """Whether one view of an image step is accepted and current (or skipped) — ``_done``'s rule per view."""
    from app.core.garment_images import skipped_view, source_due, stale_accepted, stale_model_fit
    assumed = _ASSUMED.get()
    if assumed and (step, view) in assumed:
        return assumed[(step, view)] is not None
    return ((_accepted(_image(character_name, item_id, fsig, step, view))
             and not stale_model_fit(character_name, item_id, fsig, step, view)
             and not stale_accepted(character_name, item_id, fsig, step, view)
             # Ruling A46: made from another source than the piece-only setting names now.
             and not source_due(character_name, item_id, fsig, step, view))
            or skipped_view(character_name, item_id, fsig, step, view))


def _done(character_name: str, item_id: str, kind: str, fsig: str, step: str, base_model_sha: str,
          method: str = "edit_chain", hsig: str = "") -> bool:
    from app.core.garment_store import GARMENT_VIEWS, IMAGE_STEPS, SHOE
    if method == SHOE and step != "fit":
        # The shoe's item steps: per item under its current ssig (``footwear_source``).
        from app.core import garment_footwear
        return garment_footwear.step_done(item_id, step)
    if step in IMAGE_STEPS:
        if not all(_view_done(character_name, item_id, fsig, step, v) for v in GARMENT_VIEWS):
            return False
        return step != _kind_module(kind).PAIR_STEP or _pair(character_name, item_id, kind, fsig)[0]
    if step == "mesh":
        return _mesh_done(character_name, item_id, fsig)
    if step == "hairdeck":
        return _hairdeck_files(character_name, item_id, hsig)[0] is not None
    if step == "haar":
        # ``hsig`` carries the HAAR ssig: the step is done once any seed is stored for it.
        from app.core.garment_store import haar_seeds
        return bool(haar_seeds(character_name, item_id, hsig))
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


# --- HAAR (strand-hair spec 2026-11-13 § 6.3) ------------------------------------
#
# The hairstyle's text goes to HAAR as the prompt; each seed is one hub job (``ImageService.generate_strands``)
# whose files land in ``raw/{item}_{ssig}/s{seed}/`` (``garment_store.haar_dir``). The ``haar`` step makes the
# NEXT ``HAAR_SEEDS`` seeds — a plain run only when none is stored, the step's own button (forced) always,
# keeping the older ones. The ``fit`` step (CPU) fits every stored seed that has no current result on the base
# model, records each verdict in the folder's record (``results``) and publishes the SERVED seed
# (``garment_store.haar_served_seed``: the user's pick while it is stored, else the best passing one) under the
# fsig that names it. A run's jobs are one hub operation (``hub_ops``, kind ``HAAR_OP_KIND``, one stage per
# seed): after a restart the resumer collects the jobs already submitted into their seed folders — it never
# submits a new one and never fits.

#: Seeds per HAAR run (spec § 6.3.1): three hub jobs give a choice without spending four.
HAAR_SEEDS = 3
#: The ``hub_ops`` kind of a HAAR run's strand jobs.
HAAR_OP_KIND = "garment_haar"
#: The fit step's refusal when no stored seed passes and none is picked (the Steps row's words).
NO_VARIANT_PASSED = "no variant passed"


def _haar_strands_file(character_name: str, item_id: str, inputs: Dict[str, Any]) -> Optional[Path]:
    """The strand file a HAAR fit was made from (its ``inputs.ssig`` / ``inputs.seed``), None when it is gone."""
    from app.core import garment_store as gs
    from app.core import strand_file
    try:
        folder = gs.haar_seed_dir(gs.haar_dir(character_name, item_id, str(inputs.get("ssig") or "")),
                                  int(inputs.get("seed")))
    except (TypeError, ValueError):
        return None
    if not folder.is_dir():
        return None
    hits = sorted(p for p in folder.iterdir() if p.is_file() and p.name.endswith(strand_file.STRANDS_SUFFIXES))
    return hits[0] if len(hits) == 1 else None


def _haar_next_seeds(character_name: str, item_id: str, ssig: str) -> List[int]:
    """The next ``HAAR_SEEDS`` seeds of ``ssig``: after the highest one stored or ever asked for (1, 2, 3 first)."""
    from app.core import garment_store as gs
    seen = set(gs.haar_seeds(character_name, item_id, ssig))
    for value in gs.haar_record(character_name, item_id, ssig).get("seeds") or []:
        try:
            seen.add(int(value))
        except (TypeError, ValueError):
            continue
    start = max(seen) + 1 if seen else 1
    return list(range(start, start + HAAR_SEEDS))


def _write_haar_record(character_name: str, item_id: str, ssig: str, change) -> Dict[str, Any]:
    """Read-modify-write of the HAAR folder's record (``change(record)`` edits it in place; the caller holds the
    item's run lock). Returns the record written."""
    from app.core import garment_store as gs
    folder = gs.haar_dir(character_name, item_id, ssig)
    folder.mkdir(parents=True, exist_ok=True)
    record = gs.read_record(folder / gs.HAAR_RECORD)
    change(record)
    gs.write_record(folder / gs.HAAR_RECORD, record)
    return record


def _haar_stages(op: Any, *, resume: bool = False) -> Dict[str, Any]:
    """The strand jobs of a HAAR operation (fresh run and resume): per seed of ``op.inputs["seeds"]`` whose folder
    is not stored yet, one ``generate_strands`` with the stage ``s{seed}`` into a staging folder, checked by the
    reader (``strand_file.read_strand_job``) and renamed into ``s{seed}/`` whole. A resume only collects a stage
    that reached the hub (a job id, a collected result or the posting gap) — never a new submission. Load,
    the media switch and a cancel end the run at once (the seeds stored so far stay); any other failure of a
    seed is recorded (``jobs[seed].error``) and the next seed runs. ``{ok, stored, errors}``; RuntimeError when
    a fresh run stored no seed at all."""
    import shutil
    from app.core import garment_store as gs
    from app.core import strand_file
    from app.core.timeutils import utc_now_iso
    from app.imagegen import service
    from app.imagegen.base import GenerationCancelled, GpuTaskCancelled
    character_name, item_id, ssig = op.inputs["character"], op.inputs["item_id"], op.inputs["ssig"]
    prompt = str(op.inputs.get("prompt") or "")
    folder = gs.haar_dir(character_name, item_id, ssig)
    folder.mkdir(parents=True, exist_ok=True)
    stored: List[int] = []
    errors: Dict[str, str] = {}
    for seed in [int(s) for s in op.inputs.get("seeds") or []]:
        target = gs.haar_seed_dir(folder, seed)
        if target.is_dir():
            continue
        stage = op.stage(f"s{seed}")
        if resume:
            job = stage.job
            if not (job.get("job_id") or job.get("collected") or job.get("collection_error")
                    or job.get("phase") == "posting"):
                continue  # never reached the hub: a resume submits nothing
        staging = folder / f".s{seed}.{os.getpid()}.{threading.get_ident()}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        try:
            result = service.get_image_service().generate_strands(
                prompt, str(staging), character_name=character_name, params={"seed": seed}, hub_stage=stage)
            summary = strand_file.strand_summary(strand_file.read_strand_job(staging)["strands"])
            os.replace(staging, target)
        except Exception as e:  # noqa: BLE001 — sorted below: load / cancel end the run, the rest is per seed
            shutil.rmtree(staging, ignore_errors=True)
            if _is_load(e) or isinstance(e, (GenerationCancelled, GpuTaskCancelled)):
                raise
            errors[str(seed)] = str(e) or type(e).__name__
            logger.warning("HAAR %s/%s (%s): seed %s failed: %s", character_name, item_id, ssig, seed,
                           errors[str(seed)])
            _write_haar_record(character_name, item_id, ssig, lambda r: r.setdefault("jobs", {}).update(
                {str(seed): {"error": errors[str(seed)], "created_at": utc_now_iso()}}))
            continue
        stored.append(seed)
        entry = {"backend": result.get("backend"), "job_id": result.get("job_id"), "route": result.get("route"),
                 "files": [str(f.get("name") or "") for f in result.get("files") or []], "strands": summary,
                 "error": None, "created_at": utc_now_iso()}
        _write_haar_record(character_name, item_id, ssig,
                           lambda r: r.setdefault("jobs", {}).update({str(seed): entry}))
        logger.info("HAAR %s/%s (%s): seed %s stored, %s strands x %s points", character_name, item_id, ssig, seed,
                    summary["strands"], summary["points"])
    if not stored and errors and not resume:
        raise RuntimeError("HAAR delivered no strands — " + "; ".join(f"seed {s}: {e}" for s, e in errors.items()))
    return {"ok": True, "stored": stored, "errors": errors}


def _run_haar(character_name: str, item_id: str, ssig: str, seeds: List[int]) -> List[int]:
    """Ask HAAR for ``seeds`` of the hairstyle's text as ONE hub operation (``HAAR_OP_KIND``, a stage per seed;
    ``_haar_stages``). The record's ``seeds`` names every seed ever asked for (the next run continues after
    them). ``MissingInput`` for a hairstyle without text. Returns the seeds stored by this run."""
    from app.core import base_body, hub_ops
    from app.core import garment_store as gs
    prompt = gs.haar_prompt(item_id)
    if not prompt:
        raise base_body.MissingInput("The hairstyle has no text — HAAR makes the hair from it")

    def asked(record: Dict[str, Any]) -> None:
        known = {int(s) for s in record.get("seeds") or [] if str(s).isdigit()}
        record["seeds"] = sorted(known | set(seeds))

    _write_haar_record(character_name, item_id, ssig, asked)
    op = hub_ops.create(HAAR_OP_KIND, f"garment_haar:{character_name}:{item_id}:{ssig}",
                        {"character": character_name, "item_id": item_id, "ssig": ssig, "seeds": list(seeds),
                         "prompt": prompt},
                        label=f"HAAR strands · {character_name}")
    result = hub_ops.execute(op, lambda: _haar_stages(op))
    return list(result.get("stored") or [])


def _haar_resume(op: Any) -> Any:
    from app.core import hub_ops
    return hub_ops.resume(op, lambda: _haar_stages(op, resume=True), agent_name=op.inputs.get("character", ""))


def _haar_reserve(op: Any):
    """The resumer's guard: the item's run lock (a plain ``threading.Lock``), so no chain run of the item starts
    while its jobs are collected."""
    from app.core import garment_store as gs
    lock = gs.run_item_lock(op.inputs["character"], op.inputs["item_id"])
    lock.acquire()
    return lock.release


def _register_hub_kinds() -> None:
    from app.core import hub_ops
    hub_ops.register_kind(HAAR_OP_KIND, resume=_haar_resume, track_type="garment_haar", reserve=_haar_reserve)


_register_hub_kinds()


def _haar_colour(character_name: str, item_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The HAAR hair colour: ``{target, source, name, linear}`` — the override (``source`` "override"), else the
    hairstyle text's named colour ("profile"), else none ("atlas": the strip atlas white); ``linear`` the linear
    RGB the cards get (None for the atlas)."""
    from app.core import garment_hair
    from app.core.garment_hairdeck import srgb_to_linear
    settings, text = _hair_of(character_name, item_id)
    override = garment_hair.hair_colour_override(settings)
    named = garment_hair.profile_hair_colour(character_name, profile=profile, text=text)
    target = override or (named["hex"] if named else "")
    linear = (tuple(round(float(v), 6) for v in srgb_to_linear(garment_hair.colour_target(target)))
              if target else None)
    return {"target": target or None, "source": "override" if override else "profile" if named else "atlas",
            "name": None if override or not named else named["name"], "linear": linear}


#: The tile of a fitted HAAR seed in its seed folder (``hair_variant_tile.tile_png``, the "HAAR variants" sub-tab).
HAAR_TILE = "tile.png"


def _haar_tile(folder: Path, seed: int, result: Any, body: Any) -> Optional[str]:
    """Render the tile of a fitted seed into ``s{seed}/HAAR_TILE`` (CPU, ``hair_variant_tile``) -> its name; a seed
    without a fit loses an older tile (None). A failed render is logged and never fails the fit (None)."""
    import numpy as np
    from app.core import garment_store as gs, hair_variant_tile
    path = gs.haar_seed_dir(folder, seed) / HAAR_TILE
    try:
        if result is None:
            path.unlink(missing_ok=True)
            return None
        g = result.garment
        _write_atomic(path, hair_variant_tile.tile_png(
            np.asarray(g.positions), np.asarray(g.indices).reshape(-1, 3), np.asarray(g.colors),
            body.positions, body.faces))
        return HAAR_TILE
    except Exception:  # noqa: BLE001 — a tile is a picture of the fit, never a reason to lose it
        logger.exception("HAAR tile of seed %s in %s failed", seed, folder)
        return None


def _fit_haar_seeds(character_name: str, item_id: str, ssig: str, seeds: List[int], rigged: bytes,
                    profile: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Fit each stored seed of ``ssig`` onto ``rigged`` (``garment_haar.fit_haar`` on the refit pool; colour
    ``_haar_colour``, gate of the hairstyle's length class) without publishing: seed -> ``{seed, result,
    strands_sha256, length_class, colour, error, tile}`` — ``result`` None and ``error`` the reason when the fit
    itself refused the strands (a ValueError); ``tile`` the name of the tile rendered into the seed folder
    (``_haar_tile``; None without)."""
    from app.core import garment_hair, garment_haar, refit_pool, strand_file
    from app.core import garment_store as gs
    folder = gs.haar_dir(character_name, item_id, ssig)
    _settings, text = _hair_of(character_name, item_id)
    length_class = garment_hair.hair_length_class(character_name, profile=profile, text=text)
    colour = _haar_colour(character_name, item_id, profile)
    out: Dict[int, Dict[str, Any]] = {}
    body = None
    for seed in seeds:
        job = strand_file.read_strand_job(gs.haar_seed_dir(folder, seed))
        if job["head_V"] is None:
            from app.core import base_body
            raise base_body.MissingInput(f"HAAR seed {seed} has no head file")
        entry: Dict[str, Any] = {"seed": seed, "result": None, "error": None, "length_class": length_class,
                                 "colour": colour, "strands_sha256": _sha(Path(job["strands_path"]))}
        try:
            entry["result"] = refit_pool.run(garment_haar.fit_haar, job["strands"], job["head_V"], rigged,
                                             colour_linear=colour["linear"], length_class=length_class,
                                             template_faces=job["head_F"])
        except ValueError as e:
            entry["error"] = str(e) or type(e).__name__
        if entry["result"] is not None and body is None:
            from app.core.glb_mesh import body_arrays
            body = body_arrays(rigged)
        entry["tile"] = _haar_tile(folder, seed, entry["result"], body)
        out[seed] = entry
    return out


def _haar_result(fit: Dict[str, Any], base_sha: str) -> Dict[str, Any]:
    """The record's ``results[seed]`` of one fitted seed: ``{accepted, reasons, metrics, tile, length_class,
    base_model_sha256, fit_version, strands_sha256}`` (``tile`` the tile's name in the seed folder, None without)."""
    from app.core.garment_haar import HAAR_FIT_VERSION
    from app.core.timeutils import utc_now_iso
    result = fit["result"]
    return {"accepted": bool(result.ok) if result is not None else False,
            "reasons": list(result.reasons) if result is not None else [fit["error"]],
            "metrics": dict(result.metrics) if result is not None else {}, "tile": fit.get("tile"),
            "length_class": fit["length_class"], "base_model_sha256": base_sha, "fit_version": HAAR_FIT_VERSION,
            "strands_sha256": fit["strands_sha256"], "fitted_at": utc_now_iso()}


def _haar_result_current(result: Any, base_sha: str, strands_sha: str) -> bool:
    """A stored seed result still holds: made on ``base_sha`` by the current HAAR fit from these strands."""
    from app.core.garment_haar import HAAR_FIT_VERSION
    return (isinstance(result, dict) and result.get("base_model_sha256") == base_sha
            and result.get("fit_version") == HAAR_FIT_VERSION and result.get("strands_sha256") == strands_sha)


def _haar_due(character_name: str, item_id: str, ssig: str, base_sha: str) -> List[int]:
    """The stored seeds of ``ssig`` whose result does not hold on ``base_sha`` (``_haar_result_current``)."""
    from app.core import garment_store as gs
    results = gs.haar_record(character_name, item_id, ssig).get("results") or {}
    out = []
    for seed in gs.haar_seeds(character_name, item_id, ssig):
        strands = _haar_strands_file(character_name, item_id, {"ssig": ssig, "seed": seed})
        if strands is None or not _haar_result_current(results.get(str(seed)), base_sha, _sha(strands)):
            out.append(seed)
    return out


def _haar_seed_summary(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``[{seed, ok, reasons, face_cards, tip_p50_rel_shoulder_cm}]`` of every seed result, by seed."""
    out = []
    for key, r in sorted(results.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        if not isinstance(r, dict):
            continue
        m = r.get("metrics") or {}
        out.append({"seed": int(key), "ok": r.get("accepted") is True, "reasons": list(r.get("reasons") or []),
                    "face_cards": m.get("face_cards"), "tip_p50_rel_shoulder_cm": m.get("tip_p50_rel_shoulder_cm")})
    return out


def _haar_fit_step(character_name: str, item_id: str, kind: str, bsig: str, profile: Dict[str, Any]) -> str:
    """The ``fit`` step of HAAR hair (CPU, never a hub job): every stored seed of the current ``ssig`` without a
    current result on the base model is fitted (``_fit_haar_seeds``) and its verdict recorded; then the SERVED
    seed (``garment_store.haar_served_seed``) is published — fitted once more with the current colour when this
    step did not just fit it — under the fsig that names it, which is returned. ``MissingInput`` without a
    stored seed; ``_Refused`` (``NO_VARIANT_PASSED`` + every seed's reasons) when none passes and none is
    picked. A picked seed is served even when its gate refused it (its record says ``gates.ok`` False,
    ``gates.picked`` True)."""
    from app.core import base_body
    from app.core import garment_store as gs
    from app.models.inventory import get_item
    ssig = gs.garment_ssig(character_name, item_id, profile=profile)
    seeds = gs.haar_seeds(character_name, item_id, ssig)
    if not seeds:
        raise base_body.MissingInput("The HAAR strands are missing — run the haar step first")
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    base_sha = hashlib.sha256(snapshot["rigged"]).hexdigest()
    due = _haar_due(character_name, item_id, ssig, base_sha)
    fits = _fit_haar_seeds(character_name, item_id, ssig, due, snapshot["rigged"], profile)
    record = _write_haar_record(character_name, item_id, ssig, lambda r: r.setdefault("results", {}).update(
        {str(seed): _haar_result(fit, base_sha) for seed, fit in fits.items()}))
    item = get_item(item_id)
    served = gs.haar_served_seed(character_name, item_id, ssig, item=item)
    results = record.get("results") or {}
    if served is None:
        summary = _haar_seed_summary({str(s): results.get(str(s)) for s in seeds})
        _write_haar_record(character_name, item_id, ssig, lambda r: r.update(chosen=None))
        raise _Refused("fit", f"{NO_VARIANT_PASSED} — " + "; ".join(
            f"seed {e['seed']}: " + ("; ".join(e["reasons"]) or "refused") for e in summary),
            {"attempts": summary})
    fit = fits.get(served)
    if fit is None or fit["result"] is None:
        fit = _fit_haar_seeds(character_name, item_id, ssig, [served], snapshot["rigged"], profile)[served]
    if fit["result"] is None:
        raise _Refused("fit", f"HAAR seed {served}: {fit['error']}", {"seed": served, "reasons": [fit["error"]]})
    _write_haar_record(character_name, item_id, ssig, lambda r: r.update(chosen=served))
    fsig = gs.garment_fsig(character_name, item_id, profile=profile)
    _publish_haar(character_name, item_id, kind, fsig, bsig, ssig, profile, snapshot, fit,
                  picked=gs.haar_pick(item) == served, seeds=_haar_seed_summary(
                      {str(s): results.get(str(s)) for s in seeds}))
    logger.info("HAAR fit %s/%s: seed %s served of %s", character_name, item_id, served,
                [(e["seed"], e["ok"], e["face_cards"]) for e in _haar_seed_summary(
                    {str(s): results.get(str(s)) for s in seeds})])
    return fsig


def _haar_fit_record(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, ssig: str,
                     profile: Dict[str, Any], fit: Dict[str, Any], *, picked: bool) -> Dict[str, Any]:
    """The fit record of a HAAR fit (base model or outfit body; the caller adds its body keys)."""
    from app.core import base_body, garment_hair
    from app.core.garment_store import GARMENT_VIEWS, HAAR
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    result = fit["result"]
    settings, _text = _hair_of(character_name, item_id)
    base_views = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in GARMENT_VIEWS}
    colour = dict(fit["colour"])
    colour.pop("linear", None)
    return {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "method": HAAR,
        "metrics": result.metrics, "report": result.report,
        "gates": {"ok": bool(result.ok), "reasons": list(result.reasons), "picked": bool(picked)},
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": {v: _sha(p) for v, p in base_views.items()},
                   "ssig": ssig, "seed": fit["seed"], "colour": garment_hair.hair_colour_override(settings),
                   "strands_sha256": fit["strands_sha256"]},
        "colour": colour, "length_class": fit["length_class"], "created_at": utc_now_iso()}


def _publish_haar(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, ssig: str,
                  profile: Dict[str, Any], snapshot: Dict[str, Any], fit: Dict[str, Any], *, picked: bool,
                  seeds: List[Dict[str, Any]]) -> Path:
    """Publish the served seed's fit on the base model (``_publish_fit``)."""
    rigged_sha = hashlib.sha256(snapshot["rigged"]).hexdigest()
    record = {**_haar_fit_record(character_name, item_id, kind, fsig, bsig, ssig, profile, fit, picked=picked),
              "base_signature": bsig, "base_model_sha256": rigged_sha, "body_id": bsig, "body_sha256": rigged_sha,
              "seeds": seeds}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], fit["result"], record)


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
    """Fit the prepared mesh of an own-mesh outfit piece onto the current
    base model and store it (see the module docstring). ``_Refused`` when
    the fit gate refuses; ValueError for any other kind (hair is HairDeck's
    or the body mesh's)."""
    from app.core import base_body, garment_fit, garment_set
    if kind != garment_set.CLOTHING:
        raise ValueError(f"The edit-chain fit is for clothing, not {kind!r}")
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
    if fsig == _fsig_or_empty(character_name, item_id, _state_in(character_name, item_id, profile)):
        # A group of the current fsig was made on exactly these base views: keep them with it (its frame).
        garment_source.ensure_base_copy(character_name, item_id, fsig, bsig=bsig, expected=base_images)
    # Masks in the frame of the bald front view the unrigged base was built
    # from (R6: the full-frame ghost mask, never the cut-out); a source made
    # on another base is registered onto it (``garment_source.fit_masks``).
    from app.core import fit_attempts
    attempt_base = {"kind": kind, "item_id": item_id, "fsig": fsig, "base_signature": bsig,
                    "base_model_sha256": base_sha, "body_id": bsig, "body_sha256": base_sha,
                    "fit_version": garment_fit.FIT_VERSION[kind]}
    try:
        bald_mask, ghost_mask, frame = garment_source.fit_masks(character_name, item_id, fsig,
                                                                body_front=base_views["front"],
                                                                base_front=base_views["front"])
    except garment_source.FrameRefused as e:
        gates = {"ok": False, "reasons": [str(e)], "registration": e.registration}
        # Ruling A31: the refusal is the body's last attempt (no mesh to show: nothing was fitted).
        fit_attempts.store(character_name, item_id, fsig, body="", kind=kind, record=attempt_base,
                           error=f"fit refused — {e}", gates=gates)
        raise _Refused("fit", f"fit refused — {e}", gates)
    from app.models.inventory import get_item
    slots = list(((get_item(item_id) or {}).get("outfit_piece") or {}).get("slots") or [])
    # A refit aligns its sleeves / trouser legs onto this body's limbs (``garment_source`` LIMBS).
    limb_source = garment_source.limb_source(character_name, item_id, fsig) if frame.get("registered") else None
    # The compute (pure: bytes, masks, slots in — the fit out) runs on the refit pool when it is on
    # (``refit_pool``); everything around it reads and publishes here, under the caller's locks.
    from app.core import garment_fit_settings, refit_pool
    # Ruling A47: the piece's fit settings (sleeves per side, the width allowance) — recorded with the fit.
    fit_settings = garment_fit_settings.fit_settings(profile, item_id)
    result = refit_pool.run(garment_fit.fit_clothing, prepared_bytes, snapshot["unrigged"], snapshot["rigged"],
                            masks={"body": bald_mask, "garment": ghost_mask,
                                   "opening": garment_source.opening_masks(character_name, item_id, fsig)},
                            slots=slots,
                            limb_source=limb_source, settings=fit_settings)
    limits = garment_fit.CLOTHING_GATES
    gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
             "limits": {key: [kind_, limit] for key, (kind_, limit, _label) in limits.items()}}

    def record_of(accepted: bool, frame_: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "accepted": accepted, "kind": kind, "item_id": item_id, "fsig": fsig,
            "metrics": result.metrics, "gates": gates, "report": result.report,
            "base_signature": bsig, "base_model_sha256": base_sha, "body_id": bsig, "body_sha256": base_sha,
            "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                       "base_images": base_images,
                       "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
                       "ghost_front_sha256": _sha(ghost), "fit_settings": fit_settings},
            **garment_source.fit_source(character_name, item_id, fsig, base_images), "frame": frame_,
            "created_at": utc_now_iso()}

    def refuse(error: str, refusal: Dict[str, Any], marks: Optional[Dict[str, Any]] = None) -> None:
        # Ruling A31: the refused fit is kept as the plain body's last attempt (mesh, record, marked region).
        record = record_of(False, frame)
        if record.get("inputs", {}).get("state") == "open":
            record["state"] = "open"
        fit_attempts.store(character_name, item_id, fsig, body="", kind=kind,
                           record={**record, "fit_version": garment_fit.FIT_VERSION[kind]}, error=error,
                           gates=refusal, rigged=snapshot["rigged"], garment=result.garment, marks=marks)
        raise _Refused("fit", error, refusal)

    if not result.ok:
        refuse("fit refused — " + "; ".join(result.reasons), {**gates, "metrics": result.metrics})
    # A refit's limbs sit on the body (``garment_source`` LIMBS).
    limb_marks: Dict[str, Any] = {}
    limbs = garment_source.check_limbs(character_name, item_id, fsig, result.garment.positions,
                                       snapshot["rigged"], frame, marks=limb_marks)
    if limbs is not None and not limbs["ok"]:
        refuse("refit refused — " + "; ".join(limbs["reasons"]),
               {"ok": False, "reasons": limbs["reasons"], "limbs": limbs},
               {"limb": fit_attempts.mesh_marks(result.garment, garment_source.limb_marks(limb_marks, limbs))})
    if limbs is not None:
        frame = {**frame, "limbs": limbs}
    else:
        # A native fit has no source to hold its sleeves to: they sit on the arms (Ruling A35).
        sleeve_marks: Dict[str, Any] = {}
        sleeves = garment_source.check_sleeves(result.garment.positions, snapshot["rigged"], marks=sleeve_marks)
        if sleeves is not None and not sleeves["ok"]:
            refuse("fit refused — " + "; ".join(sleeves["reasons"]),
                   {"ok": False, "reasons": sleeves["reasons"], "sleeves": sleeves},
                   {"limb": fit_attempts.mesh_marks(result.garment,
                                                    garment_source.limb_marks(sleeve_marks, sleeves))})
        if sleeves is not None:
            frame = {**frame, "sleeves": sleeves}

    record: Dict[str, Any] = record_of(True, frame)
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def _fsig_or_empty(character_name: str, item_id: str, state: Optional[str] = None) -> str:
    """``garment_store.garment_fsig`` in ``state`` (None: the worn state; "" when the item has none)."""
    from app.core import garment_store as gs
    try:
        return gs.garment_fsig(character_name, item_id, state=state)
    except ValueError:
        return ""


def _state_in(character_name: str, item_id: str, profile: Dict[str, Any]) -> str:
    """``garment_store.item_state`` of the profile (a run's profile: the state the run is for)."""
    from app.core import garment_store as gs
    return gs.item_state(character_name, item_id, profile)


def _publish_fit(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, rigged: bytes,
                 result: Any, record: Dict[str, Any], *, body: str = "", schedule: bool = True) -> Path:
    """Graft an accepted fit onto the rigged base (``body``: the rigged outfit
    body of that id), write the fit GLB and its ``record`` (to that body's
    folder, ``garment_store.body_root``), decimate the distance tier to
    ``low/`` and schedule the assembly (unless ``schedule`` is False: the
    assembly build itself fits). Shared by both hair methods and every body.
    A clothing fit made for a piece worn OPEN (its inputs say ``state:
    "open"``) records ``state: "open"``; a closed fit records no state, as
    every fit before the option (plan Task 11b)."""
    from app.blender import refine
    from app.core import garment_fit, refit_pool
    from app.core.garment_store import garment_path, write_record
    record["fit_version"] = garment_fit.fit_version_for(kind, str(record.get("method") or ""))
    if (record.get("inputs") or {}).get("state") == "open":
        record["state"] = "open"
    fit = garment_path(character_name, item_id, fsig, "fit", body=body)
    low = garment_path(character_name, item_id, fsig, "low", body=body)
    # The graft is compute (``refit_pool.graft_file``: a worker writes it to a private temp path beside the fit);
    # the rename into place, the record and the distance tier are published here.
    tmp = refit_pool.temp_path(fit)
    # Hair cards are alpha-tested (``hair_cards.alpha_overrides``: MASK at the world cutoff, read here, in the
    # publishing process); every other garment stays OPAQUE.
    overrides = None
    if kind == "hair":
        from app.core import hair_cards
        overrides = hair_cards.alpha_overrides()
    try:
        tris = refit_pool.run(refit_pool.graft_file, rigged, result.garment, f"garment_{kind}_{item_id}",
                              {"kind": kind, "item_id": item_id, "fsig": fsig}, str(tmp),
                              material_overrides=overrides)
        # A distance tier of the previous fit must never pair with the new one.
        low.unlink(missing_ok=True)
        os.replace(tmp, fit)
    finally:
        tmp.unlink(missing_ok=True)
    write_record(fit.with_suffix(".json"), record)
    logger.info("Garment fit %s/%s (%s): accepted on %s, %s tris", character_name, item_id, fsig, body or bsig, tris)

    target = max(1, int(round(refine.lod_ratio("character") * tris)))
    try:
        dec = refine.decimate_to(fit, target, low, tris=tris)
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
    # Ruling A31: the accepted fit is now the body's last attempt — a kept refused one (and a user's acceptance of
    # it, overwritten above) goes.
    from app.core import fit_attempts
    fit_attempts.drop(character_name, item_id, body=body)
    if schedule:
        from app.core import garment_assembly
        garment_assembly.schedule(character_name)
    return fit


def _placement_summary(placement: Any) -> Optional[Dict[str, Any]]:
    """The fit record's ``placement``: what the fit's ``report.placement`` applied (forward/tilt and where they
    came from) and the hairline it reached against its target. None without a report section."""
    if not isinstance(placement, dict):
        return None
    keys = ("forward_m", "forward_source", "tilt_deg", "tilt_source", "tilt_solve", "width_scale", "width_source",
            "hairline_target_y", "landmark_source")
    return {**{k: placement.get(k) for k in keys}, "hairline_y": placement.get("hairline_pushed_y")}


def _hair_of(character_name: str, item_id: str) -> Tuple[Dict[str, Any], str]:
    """``(settings, text)`` of the hairstyle ``item_id``: its HairDeck settings
    (``garment_hair.hairstyle_settings`` — colour, placement, Swing) and its
    description (the named colour and the length class come from it)."""
    from app.core import garment_hair
    from app.models.inventory import get_item
    item = get_item(item_id)
    return garment_hair.hairstyle_settings(item), garment_hair.hairstyle_description(item)


def _fit_seed(character_name: str, item_id: str, hsig: str, seed: int, attempt: int, rigged: bytes,
              profile: Dict[str, Any]) -> Dict[str, Any]:
    """Fit one stored HairDeck seed of ``hsig`` onto ``rigged`` (colour = the
    hairstyle's override, else its text's named hair colour, else HairDeck's
    own; gates = those of its length class; placement = the hairstyle's
    manual forward/tilt, else automatic) without publishing anything:
    ``{seed, result, hair_bytes, proxy_bytes, gates}`` — ``gates`` the
    verdict ``{attempt, seed, ok, reasons, limits, metrics}`` (``attempt`` =
    the seed's position among the stored seeds, 1-based). The seed's spring
    chains (``chains_seed<s>.json`` + ``cards_seed<s>.json``) go to the fit
    only when both files are there; they bind the hair only with Swing on
    (``hair_motion.swing_on``, Ruling H11)."""
    from app.core import garment_hair, garment_hairdeck, hair_motion
    from app.core import garment_store as gs
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    hair, proxy = _seed_files(folder, seed)
    if hair is None or proxy is None:
        raise RuntimeError(f"HairDeck seed {seed} has no hair/proxy file")
    hair_bytes, proxy_bytes = hair.read_bytes(), proxy.read_bytes()
    chains_file, cards_file = folder / f"chains_seed{seed}.json", folder / f"cards_seed{seed}.json"
    chains = ({"chains_json": chains_file.read_bytes(), "cards_json": cards_file.read_bytes()}
              if chains_file.is_file() and cards_file.is_file() else {})
    settings, text = _hair_of(character_name, item_id)
    override = garment_hair.hair_colour_override(settings)
    named = garment_hair.profile_hair_colour(character_name, profile=profile, text=text)
    length_class = garment_hair.hair_length_class(character_name, profile=profile, text=text)
    # The compute runs on the refit pool when it is on (``refit_pool``): bytes and plain values in, the fit out.
    from app.core import refit_pool
    result = refit_pool.run(garment_hairdeck.fit_hairdeck, hair_bytes, proxy_bytes, rigged,
                            colour_target=garment_hair.colour_target(override),
                            colour_profile=garment_hair.colour_target(named["hex"]) if named else None,
                            length_class=length_class, swing=hair_motion.swing_on(settings),
                            **garment_hair.hair_placement(settings), **chains)
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
    from app.core import base_body, garment_hair, hair_motion
    from app.core import garment_store as gs
    from app.core.garment_store import GARMENT_VIEWS, HAIRDECK
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    result, seed = fit["result"], fit["seed"]
    folder = gs.hairdeck_dir(character_name, item_id, hsig)
    gs.write_record(folder / gs.HAIRDECK_RECORD,
                    {**gs.read_record(folder / gs.HAIRDECK_RECORD), "fitted_seeds": _seed_summary(fits),
                     "fit_attempts": _refused_gates(fits)})
    settings, text = _hair_of(character_name, item_id)
    override = garment_hair.hair_colour_override(settings)
    length_class = garment_hair.hair_length_class(character_name, profile=profile, text=text)
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
                   "placement": garment_hair.hair_placement(settings),
                   "swing": hair_motion.swing_on(settings),
                   "nohead_sha256": hashlib.sha256(fit["hair_bytes"]).hexdigest(),
                   "proxy_sha256": hashlib.sha256(fit["proxy_bytes"]).hexdigest()},
        "colour": _hairdeck_colour(override, garment_hair.profile_hair_colour(character_name, profile=profile,
                                                                              text=text),
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
# on an OUTFIT BODY (``figure.shape_key``) whose geometry and head
# differ: every own-mesh piece and the hair it carries get a fit of their own
# on that body — key ``(item, fsig, body id)``, files under
# ``garments/bodies/<body id>/`` (``garment_store.body_root``). Such a fit is
# DERIVED from the fit served on the base model (``garment_store.accepted_fit``
# — the piece is a mesh at all only when it has one, ``figure.delivered_figure``):
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
# (``base_body.build_outfit_model`` → ``garment_assembly.body_fit_warning``)
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
                   base_fit_sha: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """``accepted`` (on the body ``body_sha``, by the current fit algorithm,
    from the base fit ``base_fit_sha``), ``stale`` (made on other body
    bytes, or by an older ``garment_fit.FIT_VERSION``, or — clothing — with
    other fit settings, Ruling A47), ``outdated`` (accepted on this body
    from another base fit) or ``missing``."""
    from app.core.garment_fit import expected_fit_version
    from app.core.garment_store import garment_path, read_record
    fit = garment_path(character_name, item_id, fsig, "fit", body=body_id)
    record = read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    if not body_sha or record.get("body_id") != body_id or record.get("body_sha256") != body_sha:
        return "stale"
    if record.get("fit_version") != expected_fit_version(record):
        return "stale"
    if _settings_changed(character_name, item_id, record, profile):
        return "stale"
    if not base_fit_sha or record.get("base_fit_sha256") != base_fit_sha:
        return "outdated"
    return "accepted"


def fit_on_body(character_name: str, item_id: str, *, body_id: str, base_fit: Tuple[Path, Dict[str, Any]],
                profile: Optional[Dict[str, Any]] = None, schedule: bool = True) -> Path:
    """Fit the garment of the base fit ``base_fit`` (``(fit GLB, record)``,
    the fit served on the base model) onto the outfit body ``body_id`` and
    publish it under ``(item, fsig, body id)`` (block above). ``_Refused``
    when the gate refuses (HAAR: not for a seed the user picked against its gate), ``MissingInput`` when a
    source is gone (the prepared mesh / ghost front / HairDeck seed / HAAR strands, the body or its front
    view). Never runs a generator."""
    from app.core import base_body, garment_fit, garment_set, glb_mesh, hair_motion
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
    if gs.fit_method(base_record) == gs.HAIRDECK:
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
        settings, text = _hair_of(character_name, item_id)
        override = garment_hair.hair_colour_override(settings)
        length_class = garment_hair.hair_length_class(character_name, profile=profile, text=text)
        record.update({
            "method": gs.HAIRDECK, "metrics": result.metrics, "report": result.report,
            "gates": {"ok": True, "reasons": [], "limits": _hairdeck_limits(length_class)},
            "inputs": {**_kind_inputs(kind, character_name, profile, item_id), "hsig": hsig, "seed": seed,
                       "attempt": fit["gates"]["attempt"], "colour": override,
                       "placement": garment_hair.hair_placement(settings),
                       "swing": hair_motion.swing_on(settings),
                       "nohead_sha256": hashlib.sha256(fit["hair_bytes"]).hexdigest(),
                       "proxy_sha256": hashlib.sha256(fit["proxy_bytes"]).hexdigest()},
            "colour": _hairdeck_colour(override, garment_hair.profile_hair_colour(character_name, profile=profile,
                                                                                  text=text),
                                       result.report.get("colour") or {}),
            "length_class": length_class, "placement": _placement_summary(result.report.get("placement")),
            "created_at": utc_now_iso()})
    elif gs.fit_method(base_record) == gs.HAAR:
        inputs = base_record.get("inputs") or {}
        ssig = str(inputs.get("ssig") or "")
        try:
            seed = int(inputs.get("seed"))
        except (TypeError, ValueError):
            raise base_body.MissingInput("The base fit names no HAAR seed — run the hair chain")
        if _haar_strands_file(character_name, item_id, inputs) is None:
            raise base_body.MissingInput("The HAAR strands of the base fit are gone — run the hair chain")
        fit = _fit_haar_seeds(character_name, item_id, ssig, [seed], body["rigged"], profile)[seed]
        picked = bool((base_record.get("gates") or {}).get("picked"))
        if fit["result"] is None or (not fit["result"].ok and not picked):
            reasons = [fit["error"]] if fit["result"] is None else list(fit["result"].reasons)
            raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(reasons),
                           {"ok": False, "reasons": reasons, "seed": seed})
        result = fit["result"]
        record.update({k: v for k, v in _haar_fit_record(character_name, item_id, kind, fsig, bsig, ssig, profile,
                                                         fit, picked=picked).items()
                       if k not in ("accepted", "kind", "item_id", "fsig")})
    elif kind != garment_set.CLOTHING:
        # Hair fits of the removed methods (hair views → mesh, subtract): nothing refits them any more.
        raise ValueError(f"No fit on an outfit body for a {kind} fit by {gs.fit_method(base_record)!r}")
    else:
        from app.core import fit_attempts
        record["fit_version"] = garment_fit.FIT_VERSION[kind]
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
            refusal = {"ok": False, "reasons": [str(e)], "registration": e.registration}
            fit_attempts.store(character_name, item_id, fsig, body=body_id, kind=kind, record=dict(record),
                               error=f"fit on the outfit body refused — {e}", gates=refusal)
            raise _Refused("fit", f"fit on the outfit body refused — {e}", refusal)
        record["frame"] = frame
        from app.models.inventory import get_item
        slots = list(((get_item(item_id) or {}).get("outfit_piece") or {}).get("slots") or [])
        # The outfit body has its own framing, trunk and limbs: place the piece from the base fit of the same
        # prepared mesh (torso + sleeves / trouser legs, ``garment_source`` — outfit bodies).
        limb_source = None
        try:
            limb_source = garment_source.limb_source_from_fit(
                Path(path).read_bytes(), skirt=bool((base_record.get("report") or {}).get("skirt")),
                torso=True)
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Garment fit %s/%s on %s: base fit unreadable for the limbs: %s", character_name,
                           item_id, body_id, e)
            limb_source = None
        from app.core import garment_fit_settings, refit_pool
        fit_settings = garment_fit_settings.fit_settings(profile, item_id)
        result = refit_pool.run(garment_fit.fit_clothing, prepared_bytes, body["unrigged"], body["rigged"],
                                masks={"body": body_mask, "garment": ghost_mask,
                                       "opening": garment_source.opening_masks(character_name, item_id, fsig)},
                                slots=slots,
                                limb_source=limb_source, settings=fit_settings)
        limits = garment_fit.CLOTHING_GATES
        gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
                 "limits": {key: [kind_, limit] for key, (kind_, limit, _label) in limits.items()}}
        record.update({
            "metrics": result.metrics, "gates": gates, "report": result.report,
            # The state of the base fit it derives from (its own fsig), never the live worn state.
            "inputs": {**_kind_inputs(kind, character_name, profile, item_id, gs.fit_state(base_record)),
                       "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
                       "ghost_front_sha256": _sha(ghost), "body_front_sha256": _sha(front),
                       "fit_settings": fit_settings},
            "created_at": utc_now_iso()})

        def refuse(reasons: List[str], refusal: Dict[str, Any], marks: Optional[Dict[str, Any]] = None) -> None:
            # Ruling A31: the refused fit is kept as this body's last attempt (mesh, record, marked region).
            error = "fit on the outfit body refused — " + "; ".join(reasons)
            attempt = {**record, "accepted": False}
            if attempt.get("inputs", {}).get("state") == "open":
                attempt["state"] = "open"
            fit_attempts.store(character_name, item_id, fsig, body=body_id, kind=kind, record=attempt, error=error,
                               gates=refusal, rigged=body["rigged"], garment=result.garment, marks=marks)
            raise _Refused("fit", error, refusal)

        if not result.ok:
            refuse(list(result.reasons), {**gates, "metrics": result.metrics})
        limb_marks: Dict[str, Any] = {}
        limbs = garment_source.check_limbs(character_name, item_id, fsig, result.garment.positions,
                                           body["rigged"], frame, source=(limb_source or {}).get("numbers") or None,
                                           marks=limb_marks)
        if limbs is not None and not limbs["ok"]:
            refuse(limbs["reasons"], {"ok": False, "reasons": limbs["reasons"], "limbs": limbs},
                   {"limb": fit_attempts.mesh_marks(result.garment, garment_source.limb_marks(limb_marks, limbs))})
        if limbs is not None:
            record["frame"] = {**frame, "limbs": limbs}
        if (limb_source or {}).get("torso_cover"):
            # The trunk the base fit covers stays covered (``garment_source`` TORSO) — never a torn piece.
            body_r = glb_mesh.body_arrays(body["rigged"])
            torso_marks: Dict[str, Any] = {}
            torso = garment_source.torso_gate(garment_source.torso_cover(result.garment.positions, body_r,
                                                                         marks=torso_marks),
                                              limb_source["torso_cover"])
            if not torso["ok"]:
                refuse(torso["reasons"], {"ok": False, "reasons": torso["reasons"], "torso": torso},
                       {"torso": fit_attempts.mesh_marks(body_r, garment_source.torso_marks(
                           torso_marks, limb_source["torso_cover"], torso))})
            record["frame"] = {**record["frame"], "torso": torso}
            # ... and no single hole opens in it (``garment_source`` TORSO holes).
            holes = garment_source.torso_holes(result.garment.positions, result.garment.indices,
                                               body_r, limb_source.get("torso_open"))
            hole_gate = garment_source.torso_hole_gate(holes)
            if not hole_gate["ok"]:
                refuse(hole_gate["reasons"], {"ok": False, "reasons": hole_gate["reasons"], "holes": holes})
            record["frame"]["holes"] = holes
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
    the new body).

    Footwear dispatches to ``garment_footwear.body_fit``: the shoe source is
    fitted on the outfit body directly, ``base_fit`` is not read."""
    from app.core import garment_fit, garment_store as gs
    from app.core.keyed_lock import keyed_lock
    try:
        footwear = gs._garment_kind(item_id) == _footwear()
    except ValueError:
        footwear = False
    if footwear:
        from app.core import garment_footwear
        if profile is None:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        return garment_footwear.body_fit(character_name, item_id, body_id=body_id, body_sha=body_sha,
                                         profile=profile, build=build)
    path, base_record = base_fit
    parsed = gs.parse_name(Path(path))
    if not parsed or parsed[0] != item_id or not gs.is_body_id(body_id) or not body_sha:
        return {"fit": None, "low": None, "record": {}, "fsig": "", "pending": False,
                "error": "no fit to derive from"}
    fsig = parsed[1]
    fit_path = gs.garment_path(character_name, item_id, fsig, "fit", body=body_id)
    version = garment_fit.expected_fit_version(base_record)

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
    # A fit the USER accepted (Ruling A31) serves only while it is the accepted fit by today's state (body, base
    # fit, fit version) — a changed input voids it, it never stands in like a stale gate-accepted fit.
    usable = (fit_path.is_file() and record.get("accepted") is True and record.get("body_id") == body_id
              and record.get("body_sha256") == body_sha
              and (failure is None or record.get("fit_version") == version)
              and (not isinstance(record.get("user_accepted"), dict) or state == "accepted"))
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body_id)
    pending = state != "accepted" and failure is None and on_body and not build
    error = "" if state == "accepted" else str((failure or {}).get("error") or "") or (
        "not fitted on this outfit body yet" if pending or on_body else "the outfit body was rebuilt")
    return {"fit": fit_path if usable else None, "low": low if usable and low.is_file() else None,
            "record": record if usable else {}, "fsig": fsig, "pending": pending, "error": error}


def body_fit_info(character_name: str, item_id: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The fit of ``item_id`` on the body the CURRENT outfit model stands on
    (a meshed shape): ``{body_id, status, error, fsig, created_at, metrics,
    gates}`` — ``status`` ``body_fit_state`` (``failed`` for a recorded
    refusal that holds, ``missing`` too without a base fit to derive from).
    None off the pipeline, for an outfit model on the plain body, or when the
    current outfit model does not carry the item (neither its worn hair nor
    one of its own-mesh pieces)."""
    from app.core import base_body, garment_fit, garment_store as gs, model3d
    from app.core.garment_assembly import effective_mesh_items
    from app.core.model_refs import current_outfit_state
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None:
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
                               fit_version=garment_fit.expected_fit_version(base_fit[1]))
               if status != "accepted" else None)
    out.update(fsig=fsig, status="failed" if failure else status, error=str((failure or {}).get("error") or ""),
               created_at=record.get("created_at"), metrics=record.get("metrics") or {},
               gates=record.get("gates") or {})
    return out


# --- The run --------------------------------------------------------------------

def run_garment(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
                view: Optional[str] = None, force: bool = False, state: Optional[str] = None,
                only: bool = False, beside: bool = False, prerequisites: bool = False) -> Dict[str, Any]:
    """Run the garment chain of ``item_id`` (blocking, minutes; one run per
    character — waits for ``garment_store.char_lock``, then for the item's
    ``garment_store.run_item_lock``).

    ``beside`` (Ruling A30, ``start_garment`` only): a CPU refit of the fit
    step alone that runs beside the character's FIFO — it takes the item's
    run lock and NOT the character's, so it never waits behind another
    item's chain (one waiting on hub work holds the character lock for
    minutes).

    ``steps`` None: from the first step whose accepted output for the current
    fsig is missing (the fit counts as missing on another base model or from
    a replaced prepared mesh). A step name (or several): from the earliest of
    them; with ``force`` that step re-runs — only for ``view`` when given —
    and every later step runs again. Without ``force`` a cached step is reused.

    ``only`` (the steps dialog's step buttons, fix round T12-F1 ruling F13 d):
    the named steps and nothing after them — the run ends at the LAST named
    step. A new image already drops the later image steps of its view when it
    is published (``garment_images._drop_later``) and the mesh with it
    (``_drop_mesh``); the fit then reads ``outdated`` and stays served (R11)
    until a chain run ("Run all", the Build) makes the rest again. A group
    whose images were copied from the previous base still restarts at its
    first step (two bases never mix) and runs up to the named step.

    ``view`` (Ruling A33, the step grid's per-view buttons): ONE image step
    of an edit chain, that view alone (``only`` implied) — no other view of
    the step (not even a stale one) and no later step. The views it needs
    (``view_needs``: the previous step's same view, a drafted back's front,
    the pair step's back) must be accepted: a run that finds one missing
    renders nothing and answers ``{ok: False, prerequisite: [...]}``
    (unpersisted) — unless ``prerequisites`` (the button's explicit "first"
    action): then they render first, in chain order, never forced. The view's
    follow-up (``_follow_ups``: a new front of a drafted step re-drafts its
    back) runs in the same run. The pair repair of the chain does not run: a
    pair step whose views disagree afterwards says so (``pair`` in the result)
    and Run all repairs it. ValueError for a view with anything but one image
    step.

    The steps are those of the item's CURRENT method
    (``garment_store.steps_for``; hair by HairDeck: ``hairdeck``, ``fit``; by HAAR: ``haar``, ``fit``;
    footwear: the shoe chain, ``garment_footwear.run_chain``).

    Returns ``{ok: True, fsig, ran: [steps that produced output]}`` or
    ``{ok: False, fsig, step, error, gates}`` (also recorded as the item's
    failed status; a failure that is load or the media switch — a
    ``BackendBusyError`` / ``MediaGenerationDisabled`` in the exception chain
    of any step, footwear's ``RETRY_LATER_ERRORS`` — carries ``retry_later:
    True`` and is not persisted). ValueError for an invalid item, step or
    view (any view of footwear).

    ``state`` (plan 2026-11-12-unified-worn-pieces Task 11b): the open /
    closed state of a closable clothing piece the chain is made for — its own
    image group, mesh and fit; None = the state the piece is worn in when the
    run starts. The run's profile is the live one with the piece in that
    state (``outfit_options.with_item_state``): every text, fingerprint and
    source of the run reads it, so an open run while the piece is worn closed
    never aborts as "inputs changed". An open run of a piece not worn now is
    refused (its texts need the piece worn)."""
    item, kind, order = _item_order(character_name, item_id)
    _require_steps(kind, order)
    wanted = _steps(steps, order)
    _check_view(kind, view)
    _check_view_steps(wanted, view)
    if view is not None:
        only = True  # Ruling A33: a view runs its step alone
    from app.core import garment_store as gs
    if beside and wanted != ["fit"]:
        raise ValueError("Only a run of the fit step alone runs beside the character's other garment runs")
    import contextlib
    with (contextlib.nullcontext() if beside else gs.char_lock(character_name)), \
            gs.run_item_lock(character_name, item_id):
        result = _run_locked(character_name, item, kind, wanted, view, bool(force), state, only=bool(only),
                             **({"prerequisites": True} if prerequisites else {}))
        _note_outcome(character_name, item_id, result)
    if result.get("ok") and "fit" in (result.get("ran") or []) and kind in _grafted_kinds():
        # Outside the run lock: the piece is ready — a "piece_ready" request of the
        # character's Build (``after_mesh_item_ready``) grafts it onto the figure.
        try:
            from app.core import base_body
            base_body.after_mesh_item_ready(character_name, item_id)
        except Exception:  # noqa: BLE001 — the run itself succeeded
            logger.exception("Outfit rebuild after the fit of %s/%s failed", character_name, item_id)
    return result


def _note_outcome(character_name: str, item_id: str, result: Dict[str, Any]) -> None:
    """Persist a failed run's step + error under its fsig (automatic
    triggers skip it, ``cached_failure``); a successful run clears it. A
    failure that is load or the media switch (``retry_later``, every chain)
    is not persisted: automatic triggers try again."""
    from app.core import base_body, garment_store as gs
    fsig = str(result.get("fsig") or "")
    if not fsig:
        return  # failed before the fsig was known (off the pipeline, unknown item)
    try:
        if result.get("ok"):
            gs.clear_failure(character_name, item_id, fsig)
        elif result.get("step") and not result.get("retry_later") and not result.get("prerequisite"):
            # A per-view run refused for a missing prerequisite spent nothing and is no defect (Ruling A33).
            base = base_body.current_base(character_name)
            gs.record_failure(character_name, item_id, fsig, step=str(result["step"]),
                              error=str(result.get("error") or ""), base_model_sha=base[1] if base else "",
                              stamp=result.get("refusal_stamp"))
    except (OSError, ValueError) as e:
        logger.warning("Garment failure record %s/%s not written: %s", character_name, item_id, e)


def cached_failure(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None,
                   state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The persisted failure of the item's CURRENT fsig that automatic
    triggers honour (``garment_store.chain_failure``) — None when the chain
    may run. Only an explicit run (``start_garment``) or a changed fsig
    retries a failed chain (plan 2026-11-09-base-body-phase5-mesh-items,
    Task 4 fix round 1). ``state``: the open / closed state whose fsig is
    judged (None: the worn state)."""
    from app.core import base_body, garment_store as gs
    try:
        fsig = gs.garment_fsig(character_name, item_id, profile=profile, state=state)
    except ValueError:
        return None
    base = base_body.current_base(character_name, profile=profile)
    failure = gs.chain_failure(character_name, item_id, fsig, base_model_sha=base[1] if base else "")
    if failure is not None and _rejudge_pending(character_name, item_id, fsig, str(failure.get("step") or "")):
        # Ruling A27: the refusal was recorded under an older gate and a stored attempt passes the current one
        # (the hem snap) — it no longer holds; the run takes that attempt without a render.
        failure = None
    if failure is not None:
        return failure
    # Footwear: the source is ONE per item, whoever wears it, so a refused
    # source step blocks every wearer's automatic run — not only the wearer
    # whose run recorded it (``footwear_source.refused_step``).
    try:
        if _item(character_name, item_id)[1] == _footwear():
            from app.core import footwear_source
            refused = footwear_source.refused_step(item_id)
            if refused is not None:
                return {"item_id": item_id, "fsig": fsig, "step": refused["step"], "error": refused["error"],
                        "source_refused": True, "ssig": refused["ssig"]}
    except ValueError:
        return None
    return None


#: Hub jobs per step of a plain run on its FIRST attempt (spec
#: 2026-11-11-improvements-figure-pipeline § 6.1 / § 6.5), keyed ``<kind>:<method>``:
#: the clothing ``worn`` = the front edit + the back draft (its composite is CPU, Task 11g); a
#: two-view image step = one edit per view; ``mesh`` = one img2mesh job;
#: HairDeck = its one job, HAAR = one per seed. The clothing ``cutout`` = one routed upscale per view (front + back: a cut-out below
#: ``garment_images.CUTOUT_MIN_SIDE`` goes through the ``upscale`` occasion — counted on first attempts, Ruling A25);
#: the insole and every fit are CPU work. Footwear ``source`` is computed per item (the
#: upscale, only for an item image below ``footwear_source.MIN_SIDE``). A
#: chain may spend one more per refused attempt (R5) — this is the estimate
#: ``run_estimate`` hands the improvements queue, not a cap.
HUB_JOBS: Dict[str, Dict[str, int]] = {
    "clothing:edit_chain": {"worn": 2, "ghost": 2, "cutout": 2, "mesh": 1, "fit": 0},
    "hair:hairdeck": {"hairdeck": 1, "fit": 0},
    # HAAR: one strand job per seed (``HAAR_SEEDS``); the fit of every seed is CPU work.
    "hair:haar": {"haar": HAAR_SEEDS, "fit": 0},
    # Hair in the body mesh: no steps, no job (the base views carry the hair).
    "hair:body": {},
    "footwear:shoe": {"source": 0, "empty": 1, "cutout": 0, "mesh": 1, "insole": 0, "fit": 0},
}


#: Hub jobs of an edit step's BACK view on first attempts (part of ``HUB_JOBS``): the worn back is a draft (its
#: composite is CPU), the ghost back one edit. The OPEN state of a closable piece copies them from the closed state when it
#: has them (``garment_images.closed_back``, ruling F15 i-1) — 0 jobs.
BACK_JOBS: Dict[str, int] = {"worn": 1, "ghost": 1}


def _rejudge_pending(character_name: str, item_id: str, fsig: str, step: str) -> bool:
    """Ruling A27: whether a view of the image ``step`` is taken from a stored attempt the run judges again
    under the current gate (``garment_images.rejudge_expected``: refused by an older gate for its hem alone,
    within the snap) — read from the sidecars only."""
    from app.core import garment_images
    from app.core.garment_store import GARMENT_VIEWS, IMAGE_STEPS
    if step not in IMAGE_STEPS:
        return False
    return any(garment_images.rejudge_expected(character_name, item_id, fsig, step, v) for v in GARMENT_VIEWS)


def _unknown_estimate(note: str) -> Dict[str, Any]:
    return {"steps": [], "hub_jobs": None, "note": note, "refit": False}


def run_estimate(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None, state: Optional[str] = None,
                 from_step: str = "") -> Dict[str, Any]:
    """The hub cost of a plain ``run_garment(character_name, item_id)`` BEFORE
    it runs: ``{steps, hub_jobs, note, refit}`` — ``steps`` the steps of the
    item's current method from the first one not ``_done`` under the current
    fsig (footwear: the item steps under the current ssig, then the fit),
    ``hub_jobs`` the sum of ``HUB_JOBS`` over them on first attempts (None
    when it cannot be estimated: an unknown item, a character off the
    pipeline, a shoe without an item image — ``note`` says why), ``note`` the
    parts ("worn 3 + ghost 2 + mesh 1"). ``refit`` True when the run would
    start at an image step but ``garment_source.find_source`` has a source
    made on another base and the current group holds no own images: the
    chain refits on the CPU first (``_refit_from_source``), so ``hub_jobs``
    is 0 and the note names the full cost a refused refit falls back to.
    ``state``: the open / closed state of a closable clothing piece whose
    chain is estimated (None: the worn state) — its own fsig, its own
    source (``outfit_options.with_item_state``). The OPEN state's image
    steps lose their ``BACK_JOBS`` where the closed state has the back
    (ruling F15 i-1: copied, never rendered with state words).
    ``from_step``: the run FORCED from that step on with its chain (the
    Figure tab's "Regenerate mesh", ``{step, force, chain}`` — Ruling
    FR-minors: its button states this cost); unknown when the item's chain
    has no such step."""
    from app.core import base_body, garment_source
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    try:
        item, kind, order = _item_order(character_name, item_id, profile)
    except ValueError as e:
        return _unknown_estimate(str(e))
    if profile is None:
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None:
        return _unknown_estimate(f"{character_name} is not on the base-body pipeline")
    bsig, base_sha = base
    method = gs.kind_method(kind, character_name, profile, item_id=item_id)
    if not order:
        # Hair in the body mesh (``garment_store.BODY``): nothing to run, ever.
        return {"steps": [], "hub_jobs": 0, "note": _no_steps_note(kind, method), "refit": False}
    costs = dict(HUB_JOBS.get(f"{kind}:{method}") or {})
    if not costs:
        return _unknown_estimate(f"no cost table for {kind} by {method}")
    if kind == _footwear():
        from app.core import footwear_source
        image = footwear_source._item_image(item_id)
        if image is None or not image.is_file():
            return _unknown_estimate(f"{item.get('name') or item_id} has no item image")
        from PIL import Image
        try:
            with Image.open(image) as im:
                costs["source"] = 1 if max(im.size) < footwear_source.MIN_SIDE else 0
        except OSError as e:  # PIL's UnidentifiedImageError included: an estimate never raises on a bad file
            return _unknown_estimate(f"{item.get('name') or item_id}: item image unreadable ({e})")
    try:
        state = gs.item_state(character_name, item_id, profile, state)
        fsig = gs.garment_fsig(character_name, item_id, profile=profile, state=state)
        hsig = (gs.garment_hsig(character_name, item_id, profile=profile) if method == gs.HAIRDECK
                else gs.garment_ssig(character_name, item_id, profile=profile) if method == gs.HAAR else "")
        if from_step and from_step not in order:
            return _unknown_estimate(f"no step {from_step} for {kind} by {method}")
        first = from_step or next((s for s in order
                                   if not _done(character_name, item_id, kind, fsig, s, base_sha, method, hsig)),
                                  None)
    except ValueError as e:
        return _unknown_estimate(str(e))
    run_profile = _run_profile(profile, item_id, state)
    if first is None:
        return {"steps": [], "hub_jobs": 0, "note": "nothing to run", "refit": False}
    steps = list(order[order.index(first):])
    parts = [(s, int(costs.get(s, 0))) for s in steps]
    if first in gs.IMAGE_STEPS and method == gs.EDIT_CHAIN and not from_step:
        # The first step re-makes only its views that are not done (one job per view): a view kept accepted and
        # current costs nothing (Ruling A25 — the estimate is what the run spends on first attempts), nor does
        # one a stored attempt passes once judged again with the hem snap (Ruling A27).
        from app.core.garment_images import rejudge_expected
        assumed = _ASSUMED.get() or {}
        kept = sum(1 for v in gs.GARMENT_VIEWS if _view_done(character_name, item_id, fsig, first, v)
                   or ((first, v) not in assumed and rejudge_expected(character_name, item_id, fsig, first, v)))
        parts[0] = (first, max(parts[0][1] - kept, 0))
    if method == gs.EDIT_CHAIN and not from_step:
        # Ruling A46: a piece-only view made from the worn view costs no job (the run makes the views that are not
        # done; a later step's views all — less the ones from the worn view). When the setting alone makes the
        # step with the choice due, a later step's view whose own and earlier views stay done is kept too: a new image
        # drops only the later images of ITS view (``garment_images._drop_later``) — a setting change of the back
        # re-makes the back's cut-out, not the front's.
        from app.core import garment_images
        choice_step = getattr(_kind_module(kind), "FROM_WORN_STEP", None)
        image_order = [s for s, _n in parts if s in gs.IMAGE_STEPS]
        # Only when the setting alone makes the first step due: every view of it that is not done was made from
        # another source (no re-judged attempt, no stale image — those keep the whole later step).
        setting_only = first == choice_step and all(
            _view_done(character_name, item_id, fsig, first, v)
            or (garment_images.source_due(character_name, item_id, fsig, first, v)
                and not garment_images.rejudge_expected(character_name, item_id, fsig, first, v))
            for v in gs.GARMENT_VIEWS)
        for i, (s, n) in enumerate(parts):
            if n and s in gs.IMAGE_STEPS and setting_only and s != first:
                upto = image_order[:image_order.index(s) + 1]
                kept_later = sum(1 for v in gs.GARMENT_VIEWS
                                 if all(_view_done(character_name, item_id, fsig, e, v) for e in upto))
                parts[i] = (s, max(n - kept_later, 0))
                n = parts[i][1]
            if n and s in gs.IMAGE_STEPS:
                worn_views = [v for v in gs.GARMENT_VIEWS
                              if (garment_images.piece_source(character_name, item_id, fsig, s, v) or {})
                              .get("source") == "worn"
                              and not (s == first and (_view_done(character_name, item_id, fsig, s, v)
                                                       or garment_images.rejudge_expected(
                                                           character_name, item_id, fsig, s, v)))]
                parts[i] = (s, max(n - len(worn_views), 0))
    reused = []
    if kind == _clothing() and method == gs.EDIT_CHAIN and state == "open":
        # Ruling F15 i-1: the open state's backs are the closed state's — copied when it has them.
        from app.core import garment_images
        reused = [s for s in steps if s in BACK_JOBS
                  and garment_images.closed_back(character_name, item_id, s, profile=profile) is not None]
        parts = [(s, max(n - BACK_JOBS[s], 0) if s in reused else n) for s, n in parts]
    full = sum(n for _s, n in parts)
    note = " + ".join(f"{s} {n}" for s, n in parts if n) or "no hub job"
    cpu_fits = None
    if method == gs.HAAR:
        note, cpu_fits = _haar_estimate_note(character_name, item_id, hsig, base_sha, steps,
                                             int(costs.get("haar", 0)))
    if reused:
        note += " (backs from the closed state)"
    if first in gs.IMAGE_STEPS and method == gs.EDIT_CHAIN and not from_step:
        if (run_profile is not None
                and not garment_source.has_own_images(character_name, item_id, kind, method, fsig)
                and garment_source.find_source(character_name, item_id, kind, method, run_profile, fsig)
                is not None):
            return {"steps": steps, "hub_jobs": 0, "refit": True,
                    "note": f"refit from the previous base; up to {full} if the refit is refused"}
    if cpu_fits is not None:
        # A HAAR run's CPU fits (``_haar_estimate_note``): the tab names them beside its hub jobs.
        return {"steps": steps, "hub_jobs": full, "note": note, "refit": False, "cpu_fits": cpu_fits}
    return {"steps": steps, "hub_jobs": full, "note": note, "refit": False}


def _haar_estimate_note(character_name: str, item_id: str, ssig: str, base_sha: str, steps: List[str],
                        jobs: int) -> Tuple[str, int]:
    """The estimate's words for a HAAR run and its CPU fits: "k hub jobs (~30–55 s each) + k CPU fits (~25 s
    each)" with the strand step, else the CPU fits the fit step makes (the seeds without a current result, at
    least the served one)."""
    if "haar" in steps:
        return f"haar {jobs} hub jobs (~30–55 s each) + {jobs} CPU fits (~25 s each)", jobs
    try:
        fits = max(1, len(_haar_due(character_name, item_id, ssig, base_sha)))
    except ValueError:
        fits = 1
    return f"fit: {fits} CPU fit{'s' if fits != 1 else ''} (~25 s each), no hub job", fits


# --- A per-view run (Ruling A33) ---------------------------------------------------

#: Why a view needs another view (``view_needs``; the UI words each code): ``source`` the step edits the
#: previous step's image of the same view, ``draft`` a drafted back is made from its step's front, ``pair``
#: the pair step's front is matched to the accepted back's length.
NEEDS_SOURCE, NEEDS_DRAFT, NEEDS_PAIR = "source", "draft", "pair"
_NEEDS_TEXT = {NEEDS_SOURCE: "the {view} is made from the {need} image",
               NEEDS_DRAFT: "the {view} is drafted from the {need}",
               NEEDS_PAIR: "the {view} is matched to the {need}'s length"}
#: How the refusals name a step (the UI's own labels are its step names).
_STEP_WORDS = {"worn": "worn", "ghost": "piece-only", "cutout": "cut-out"}
#: A per-view run's refusal when a view it needs is not accepted (``PrerequisiteMissing``; 409).
PREREQUISITE_ERROR = "Needs {what} first — {why}. Nothing was rendered"


class PrerequisiteMissing(Exception):
    """Ruling A33: a per-view run whose prerequisite views are not accepted, refused before anything is
    spent (``check_run`` → 409; a queued run that finds it at its start answers the same, unpersisted).
    ``missing`` = the plan's ``missing`` entries."""

    def __init__(self, message: str, missing: List[Dict[str, Any]]):
        super().__init__(message)
        self.missing = missing


def _view_order(kind: str, step: str) -> Tuple[str, ...]:
    """The render order of the views of image ``step``: the cut-out front first, an edit step its own
    (``EDIT_STEPS[step]["views"]``: clothing ``worn`` the front first) or ``EDIT_VIEW_ORDER``."""
    from app.core.garment_store import GARMENT_VIEWS
    if step == "cutout":
        return GARMENT_VIEWS
    return tuple(_kind_module(kind).EDIT_STEPS[step].get("views", EDIT_VIEW_ORDER))


def view_needs(kind: str, step: str, view: str) -> List[Tuple[str, str, str]]:
    """The views (``(step, view, why)``) that ``view`` of image ``step`` reads before it renders — each must be
    accepted first (Ruling A33): the previous image step's same view (``source``: an edit's
    ``EDIT_STEPS[step]["source"]``, the cut-out's ghost), a drafted step's front for its back (``draft``,
    ``garment_images._drafted_back``) and the pair step's back for its front (``pair``, ``_pair_check``)."""
    from app.core.garment_store import image_steps
    module = _kind_module(kind)
    order = image_steps(kind)
    out: List[Tuple[str, str, str]] = []
    if step == "cutout":
        out.append((order[order.index(step) - 1], view, NEEDS_SOURCE))
    else:
        spec = module.EDIT_STEPS[step]
        if spec.get("source") not in (None, "base"):
            out.append((spec["source"], view, NEEDS_SOURCE))
        if view == "back" and spec.get("back") == "draft":
            out.append((step, "front", NEEDS_DRAFT))
        if view == "front" and step == module.PAIR_STEP:
            out.append((step, "back", NEEDS_PAIR))
    return out


def _view_cost(character_name: str, item_id: str, kind: str, fsig: str, step: str, view: str, *,
               costs: Dict[str, int], forced: bool, open_state: bool, profile: Dict[str, Any],
               front_changes: bool = False) -> int:
    """Hub jobs of rendering ``view`` of image ``step`` on first attempts: one per view (``HUB_JOBS`` split by
    ``BACK_JOBS``); 0 for a view a stored attempt passes once judged again (Ruling A27) — never for a drafted
    back whose front ``front_changes``: its attempts follow the old front — and for an OPEN back copied from the
    closed state (ruling F15 i-1; a forced back is rendered from the closed texts instead)."""
    from app.core import garment_images
    total = int(costs.get(step, 0))
    back = BACK_JOBS.get(step, total // 2)
    jobs = back if view == "back" else total - back
    if (garment_images.piece_source(character_name, item_id, fsig, step, view) or {}).get("source") == "worn":
        return 0  # Ruling A46: made from the worn view minus the base view — no render
    if not front_changes and garment_images.rejudge_expected(character_name, item_id, fsig, step, view):
        return 0
    if (open_state and view == "back" and not forced and step in BACK_JOBS
            and garment_images.closed_back(character_name, item_id, step, profile=profile) is not None):
        return 0
    return jobs


def _copied_view(character_name: str, item_id: str, fsig: str, step: str, view: str) -> bool:
    """Whether the final of ``view`` was copied from the previous base's group (``garment_source.materialize``)
    — a run of a view drops those copies first (``garment_source.drop_materialized``), so it counts missing."""
    from app.core import garment_source
    from app.core.garment_store import read_record
    record = read_record(_image(character_name, item_id, fsig, step, view).with_suffix(".json"))
    return bool(record.get(garment_source.COPIED) or record.get(garment_source.MATERIALIZED))


def _view_ready(character_name: str, item_id: str, fsig: str, step: str, view: str, materialized: bool) -> bool:
    """A view a per-view run may read: accepted and current (``_view_done``), or left out (``skipped_view``);
    in a group holding copies of the previous base's images, never a copy."""
    if materialized and _copied_view(character_name, item_id, fsig, step, view):
        return False
    return _view_done(character_name, item_id, fsig, step, view)


def _missing_views(character_name: str, item_id: str, kind: str, fsig: str, step: str, view: str,
                   materialized: bool) -> List[Dict[str, Any]]:
    """Every view ``view`` of ``step`` needs, directly or through another, that is not ready — in run order
    (chain step, then the step's view order). Each ``{step, view, why, for: [step, view]}`` (``for`` = the
    view that needs it)."""
    from app.core.garment_store import image_steps
    from app.core.garment_images import skipped_view
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}
    todo = [(step, view)]
    seen = set(todo)
    while todo:
        s, v = todo.pop()
        for ns, nv, why in view_needs(kind, s, v):
            if (ns, nv) in seen:
                continue
            seen.add((ns, nv))
            if skipped_view(character_name, item_id, fsig, ns, nv):
                continue  # an empty drafted back: nothing to wait for
            if _view_ready(character_name, item_id, fsig, ns, nv, materialized):
                continue
            found[(ns, nv)] = {"step": ns, "view": nv, "why": why, "for": [s, v]}
            todo.append((ns, nv))
    order = image_steps(kind)
    return sorted(found.values(), key=lambda m: (order.index(m["step"]),
                                                 _view_order(kind, m["step"]).index(m["view"])))


def _follow_ups(kind: str, step: str, view: str) -> List[Tuple[str, str, str]]:
    """The views a new ``view`` of ``step`` renders again in the same run (Ruling A33 c): a new front of a
    DRAFTED step drops the back drafted from it (``garment_images._publish``), which is drafted again from the
    new front. A new image's LATER steps and the mesh are only dropped — Run all makes them again."""
    if view == "front" and (_kind_module(kind).EDIT_STEPS.get(step) or {}).get("back") == "draft":
        return [(step, "back", NEEDS_DRAFT)]
    return []


def _view_words(step: str, view: str) -> str:
    """"piece-only back" — a view as the refusals name it."""
    return f"{_STEP_WORDS.get(step, step)} {view}"


def _what(missing: List[Dict[str, Any]]) -> str:
    """The refusal's words for the missing views ("the piece-only back", "2 views (worn front, worn back)")."""
    names = [_view_words(m["step"], m["view"]) for m in missing]
    return f"the {names[0]}" if len(names) == 1 else f"{len(names)} views ({', '.join(names)})"


def _view_context(character_name: str, item_id: str, profile: Optional[Dict[str, Any]],
                  state: Optional[str]) -> Optional[Dict[str, Any]]:
    """What a per-view plan reads once per item: ``{kind, method, fsig, costs, open, profile, materialized}``;
    None when the item has no per-view runs (no edit chain, off the pipeline, no fsig)."""
    from app.core import base_body, garment_source
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    try:
        _item_, kind, _order = _item_order(character_name, item_id, profile)
    except ValueError:
        return None
    if profile is None:
        profile = get_character_profile(character_name) or {}
    if kind == _footwear() or base_body.current_base(character_name, profile=profile) is None:
        return None
    method = gs.kind_method(kind, character_name, profile, item_id=item_id)
    if method != gs.EDIT_CHAIN:
        return None
    try:
        state = gs.item_state(character_name, item_id, profile, state)
        fsig = gs.garment_fsig(character_name, item_id, profile=profile, state=state)
    except ValueError:
        return None
    run_profile = _run_profile(profile, item_id, state) or profile
    return {"kind": kind, "method": method, "fsig": fsig, "costs": dict(HUB_JOBS.get(f"{kind}:{method}") or {}),
            "open": kind == _clothing() and state == "open", "profile": run_profile,
            "materialized": garment_source.is_materialized(character_name, item_id, fsig)}


def _plan_of(character_name: str, item_id: str, ctx: Dict[str, Any], step: str, view: str) -> Dict[str, Any]:
    from app.core.garment_images import skipped_view
    kind, fsig = ctx["kind"], ctx["fsig"]
    args = {"costs": ctx["costs"], "open_state": ctx["open"], "profile": ctx["profile"]}
    skipped = skipped_view(character_name, item_id, fsig, step, view)
    missing = _missing_views(character_name, item_id, kind, fsig, step, view, ctx["materialized"])
    drafted = {s for s, spec in (getattr(_kind_module(kind), "EDIT_STEPS", {}) or {}).items()
               if spec.get("back") == "draft"}
    for m in missing:
        # A drafted back whose front renders first is drafted from the NEW front: no stored attempt counts.
        front_changes = (m["view"] == "back" and m["step"] in drafted
                         and any(o["step"] == m["step"] and o["view"] == "front" for o in missing))
        m["jobs"] = _view_cost(character_name, item_id, kind, fsig, m["step"], m["view"], forced=False,
                               front_changes=front_changes, **args)
    follow = [{"step": s, "view": v, "why": why,
               "jobs": _view_cost(character_name, item_id, kind, fsig, s, v, forced=False, front_changes=True,
                                  **args)}
              for s, v, why in _follow_ups(kind, step, view)]
    jobs = 0 if skipped else _view_cost(character_name, item_id, kind, fsig, step, view, forced=True, **args)
    return {"step": step, "view": view, "jobs": jobs, "skipped": skipped or None,
            "missing": missing, "prerequisite_jobs": sum(m["jobs"] for m in missing),
            "follow_up": follow, "follow_up_jobs": sum(f["jobs"] for f in follow)}


def view_plan(character_name: str, item_id: str, step: str, view: str, *,
              profile: Optional[Dict[str, Any]] = None, state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """What the per-view button of ``view`` of image ``step`` spends BEFORE the click (Ruling A33): ``{step,
    view, jobs, skipped, missing, prerequisite_jobs, follow_up, follow_up_jobs}`` — ``jobs`` this view on first
    attempts (forced, as the button runs it), ``missing`` the views it needs that are not accepted, in run order
    (``{step, view, why, for, jobs}``; the button is refused with 409 while any is — its "first" action runs
    them, ``prerequisite_jobs``), ``follow_up`` the views the same run renders again after it (a drafted step's
    back; ``follow_up_jobs``), ``skipped`` why the view is not made (an empty drafted back's later views).
    None when the item has no per-view runs. Read from the files only."""
    ctx = _view_context(character_name, item_id, profile, state)
    if ctx is None or (step != "cutout" and step not in getattr(_kind_module(ctx["kind"]), "EDIT_STEPS", {})):
        return None
    return _plan_of(character_name, item_id, ctx, step, view)


def view_plans(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
               state: Optional[str] = None) -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
    """``{step: {view: view_plan}}`` for every image step and view of the item (the Wardrobe's step grid);
    None when the item has no per-view runs."""
    from app.core.garment_store import GARMENT_VIEWS, image_steps
    ctx = _view_context(character_name, item_id, profile, state)
    if ctx is None:
        return None
    return {step: {view: _plan_of(character_name, item_id, ctx, step, view) for view in GARMENT_VIEWS}
            for step in image_steps(ctx["kind"])}


# --- "Use this" on a stored attempt (Ruling A37) -----------------------------------------

class UseBusy(RuntimeError):
    """A garment run of the piece holds its run lock: "Use this" waits for it to end (409)."""


def _use_assumption(kind: str, step: str, view: str, gate: Optional[Dict[str, Any]],
                    passing: bool) -> Dict[Tuple[str, str], Optional[Dict[str, Any]]]:
    """The views as they are after "Use this" on ``view`` of ``step`` (``garment_images._publish``): that view
    accepted with ``gate`` (taken by the user unless ``passing``), its later image steps dropped, and for a
    new front of a drafted step its back and the back's later steps too."""
    from app.core.garment_store import image_steps
    order = image_steps(kind)
    later = order[order.index(step) + 1:]
    out: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {(step, view): {"gate": gate, "user": not passing}}
    out.update({(s, view): None for s in later})
    if view == "front" and (_kind_module(kind).EDIT_STEPS.get(step) or {}).get("back") == "draft":
        out.update({(s, "back"): None for s in (step, *later)})
    return out


def use_plans(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None
              ) -> Optional[Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]]:
    """Ruling A37: what "Use this" does on every stored attempt of the item's edit steps BEFORE the click —
    ``{step: {view: {attempt: {passing, in_use, block, follow_up}}}}``: ``passing`` its gate record passes (else
    the click is an acceptance by the user), ``in_use`` it is the view's accepted image now, ``block`` why it
    cannot be used ("" when it can: ``garment_images.attempt_inputs``), ``follow_up`` the estimate of the chain
    after the click (``run_estimate`` with the view taken and its later images dropped: ``{steps, hub_jobs,
    note}``; None when in use or blocked). The worn state's group; None when the item has no per-view runs.
    Read from the files only."""
    from app.core import garment_images
    from app.core.garment_store import GARMENT_VIEWS, garment_path, read_record
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    ctx = _view_context(character_name, item_id, profile, None)
    if ctx is None:
        return None
    kind, fsig = ctx["kind"], ctx["fsig"]
    out: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    for step in getattr(_kind_module(kind), "EDIT_STEPS", {}) or {}:
        for view in GARMENT_VIEWS:
            final = _image(character_name, item_id, fsig, step, view)
            final_record = read_record(final.with_suffix(".json")) if final.is_file() else {}
            for n in range(1, garment_images.ATTEMPTS + 1):
                target = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=n)
                if not target.is_file():
                    continue
                sidecar = read_record(target.with_suffix(".json"))
                gate = sidecar.get("gate") if isinstance(sidecar.get("gate"), dict) else None
                passing = bool(gate and gate.get("ok") is True)
                in_use = (_accepted(final) and int(final_record.get("attempt") or 0) == n
                          and _sha(final) == _sha(target))
                block = "" if in_use else garment_images.attempt_inputs(character_name, item_id, fsig, step, view,
                                                                        sidecar)[0]
                follow = None
                if not in_use and not block:
                    token = _ASSUMED.set(_use_assumption(kind, step, view, gate, passing))
                    try:
                        estimate = run_estimate(character_name, item_id, profile=profile)
                    finally:
                        _ASSUMED.reset(token)
                    follow = {k: estimate.get(k) for k in ("steps", "hub_jobs", "note")}
                out.setdefault(step, {}).setdefault(view, {})[str(n)] = {
                    "passing": passing, "in_use": in_use, "block": block, "follow_up": follow}
    return out


def use_attempt(character_name: str, item_id: str, step: str, view: str, attempt: int, *,
                profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ruling A37, "Use this": the stored ``attempt`` of ``view`` of edit ``step`` becomes the view's accepted
    image (``garment_images.use_attempt``: a refused one accepted by the user) — no job. Under the item's run
    lock (``garment_store.run_item_lock``, never waiting: ``UseBusy`` while a run holds it). The later images
    of the view go, the mesh with them (``_drop_mesh``: the fit reads outdated and stays served until a new one
    is accepted); a recorded refusal of this step or a later one is answered (the chain may run again).
    ``{item_id, step, view, attempt, changed, passing, user_accepted, follow_up}`` — ``follow_up`` the chain's
    estimate now (``run_estimate``). ``garment_images.AttemptUnusable`` / ValueError for a bad request."""
    from app.core import garment_images
    from app.core import garment_store as gs
    from app.core.garment_store import GARMENT_VIEWS, image_steps
    from app.models.character import get_character_profile
    if view not in GARMENT_VIEWS:
        raise ValueError(f"invalid view {view!r}")
    if profile is None:
        profile = get_character_profile(character_name) or {}
    ctx = _view_context(character_name, item_id, profile, None)
    if ctx is None:
        raise ValueError("This piece has no image steps to take an attempt from")
    kind, fsig = ctx["kind"], ctx["fsig"]
    lock = gs.run_item_lock(character_name, item_id)
    if not lock.acquire(blocking=False):
        raise UseBusy("A garment run of this piece is in progress — use the attempt after it")
    try:
        result = garment_images.use_attempt(character_name, item_id, fsig, step, view, attempt)
        if result["changed"]:
            _drop_mesh(character_name, item_id, fsig)
            order = image_steps(kind)
            due = set(order[order.index(step):]) | {"mesh", "fit"}
            failure = gs.chain_failure(character_name, item_id, fsig)
            if failure is not None and failure.get("step") in due:
                gs.clear_failure(character_name, item_id, fsig)
            failed = gs.status(character_name, item_id).get("failed") or {}
            if failed.get("step") in due:
                gs.end(character_name, item_id, str(failed["step"]))
    finally:
        lock.release()
    estimate = run_estimate(character_name, item_id, profile=profile)
    return {"item_id": item_id, "step": step, "view": view, "attempt": attempt, **result,
            "follow_up": {k: estimate.get(k) for k in ("steps", "hub_jobs", "note")}}


def _check_view_run(character_name: str, item_id: str, step: str, view: str, *, state: Optional[str],
                    prerequisites: bool) -> None:
    """``check_run``'s per-view rule (Ruling A33): ValueError for a view that is not made (an empty drafted
    back's later views); ``PrerequisiteMissing`` while a view it needs is not accepted, unless the caller
    allows the run to make them first (``prerequisites``)."""
    plan = view_plan(character_name, item_id, step, view, state=state)
    if plan is None:
        return
    if plan["skipped"]:
        raise ValueError(f"The {_STEP_WORDS.get(step, step)} {view} is not made: {plan['skipped']}")
    if plan["missing"] and not prerequisites:
        raise PrerequisiteMissing(_prerequisite_error(plan["missing"]), plan["missing"])


def _prerequisite_error(missing: List[Dict[str, Any]]) -> str:
    """The refusal text: the missing views and why the last of them — the one nearest the clicked view in run
    order — is needed."""
    last = missing[-1]
    why = _NEEDS_TEXT.get(last["why"], "the {view} reads the {need}").format(
        view=_view_words(*last["for"]), need=_view_words(last["step"], last["view"]))
    return PREREQUISITE_ERROR.format(what=_what(missing), why=why)


def _clothing() -> str:
    from app.core.garment_set import CLOTHING
    return CLOTHING


def _grafted_kinds() -> Tuple[str, ...]:
    from app.core.garment_set import GRAFTED_PIECE_KINDS
    return GRAFTED_PIECE_KINDS


def _no_steps_note(kind: str, method: str) -> str:
    """Why a garment of ``kind`` made with ``method`` has no steps (hair in the body mesh)."""
    from app.core import garment_hair
    if method == garment_hair.BODY_MODE:
        return garment_hair.HAIR_IN_BODY
    return f"no steps for {kind} by {method}"


def _require_steps(kind: str, order: Tuple[str, ...], method: str = "") -> None:
    """ValueError when the item's current method has no steps — hair in the
    body mesh never runs (no click, no trigger, no improvement)."""
    if not order:
        from app.core import garment_hair
        raise ValueError(_no_steps_note(kind, method or garment_hair.BODY_MODE))


def _item_order(character_name: str, item_id: str,
                profile: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str, Tuple[str, ...]]:
    """``(item, kind, steps of the current method)``; ValueError like ``_item``."""
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    item, kind = _item(character_name, item_id)
    if profile is None:
        profile = get_character_profile(character_name) or {}
    return item, kind, gs.steps_for(kind, gs.kind_method(kind, character_name, profile, item_id=item_id))


def _run_profile(profile: Dict[str, Any], item_id: str, state: str) -> Optional[Dict[str, Any]]:
    """The profile a run (or an estimate) of ``item_id`` in ``state`` reads: the live ``profile`` with the piece
    in that state (``outfit_options.with_item_state``); None when the profile cannot wear it in that state — an
    OPEN state of a piece it does not wear (its texts would say closed)."""
    from app.core import garment_store as gs
    from app.core.outfit_options import with_item_state
    out = with_item_state(profile, item_id, state)
    return out if gs.item_state("", item_id, out) == state else None


#: The refusal of an open run of a piece that is not worn (``run_garment``, ``check_run``).
NOT_WORN_OPEN_ERROR = "{name} is not worn now — its open mesh is made while it is worn"


def _run_locked(character_name: str, item: Dict[str, Any], kind: str,
                wanted: Optional[List[str]], view: Optional[str], force: bool,
                state: Optional[str] = None, *, only: bool = False,
                prerequisites: bool = False) -> Dict[str, Any]:
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
    try:
        state = gs.item_state(character_name, item_id, profile, state)
    except ValueError as e:
        return {"ok": False, "fsig": "", "step": "", "error": str(e), "ran": []}
    run_profile = _run_profile(profile, item_id, state)
    if run_profile is None:
        return {"ok": False, "fsig": "", "step": "", "ran": [],
                "error": NOT_WORN_OPEN_ERROR.format(name=item.get("name") or item_id)}
    profile = run_profile
    method = gs.kind_method(kind, character_name, profile, item_id=item_id)
    order = gs.steps_for(kind, method)
    if not order:
        # The method changed to one without steps (hair in the body mesh) while the run waited.
        return {"ok": False, "fsig": "", "step": "", "error": _no_steps_note(kind, method), "ran": []}
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
        base_views = _base_view_shas(character_name, bsig)   # Ruling A20: what each composite checks against
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
        if method == gs.HAIRDECK:
            hsig = gs.garment_hsig(character_name, item_id, profile=profile)
        elif method == gs.HAAR:
            hsig = gs.garment_ssig(character_name, item_id, profile=profile)  # the HAAR job's fingerprint
        if method == gs.EDIT_CHAIN:
            _regate_accepted(character_name, item_id, kind, fsig, state if kind == _clothing() else None)
        if wanted is None:
            first = next((s for s in order
                          if not _done(character_name, item_id, kind, fsig, s, base_sha, method, hsig)), None)
            if first is None:
                return {"ok": True, "fsig": fsig, "ran": []}
            if first in gs.IMAGE_STEPS:
                # Refit before re-render: the last accepted source onto the new base first (CPU).
                refit = _refit_from_source(character_name, item_id, kind, method, fsig, bsig, profile)
                if refit is not None and refit.get("ok"):
                    return refit
        else:
            first = min(wanted, key=order.index)
            scoped = view is not None and method == gs.EDIT_CHAIN
            if scoped:
                # Ruling A33: a view run checks the views it needs BEFORE anything is spent or dropped.
                from app.core import garment_source
                step = first
                materialized = garment_source.is_materialized(character_name, item_id, fsig)
                missing = _missing_views(character_name, item_id, kind, fsig, first, view, materialized)
                if missing and not prerequisites:
                    error = _prerequisite_error(missing)
                    return {**_refusal(character_name, item_id, fsig, first, error, None, ran), "prerequisite": missing}
                if materialized:
                    # Copies of the previous base's images never mix with a new render (counted missing above).
                    garment_source.drop_materialized(character_name, item_id, fsig)
            elif first in gs.IMAGE_STEPS:
                from app.core import garment_source
                if garment_source.drop_materialized(character_name, item_id, fsig):
                    # Re-render: images of two bases never mix in one group — the chain starts at its first step.
                    first = order[0]
        if first in gs.IMAGE_STEPS:
            from app.core import garment_source
            garment_source.ensure_current(character_name, item_id, fsig, bsig)
        image_state = state if kind == _clothing() else None
        pair_step = _kind_module(kind).PAIR_STEP if method == gs.EDIT_CHAIN else None
        if view is not None and method == gs.EDIT_CHAIN:
            # Ruling A33: the views it needs (allowed: ``prerequisites``), the view, its follow-up — nothing else.
            targets = ([(m["step"], m["view"]) for m in missing] + [(first, view)]
                       + [(s, v) for s, v, _why in _follow_ups(kind, first, view)])
            for step, v in targets:
                f = force and (step, v) == (first, view)
                if not f and _view_done(character_name, item_id, fsig, step, v):
                    continue
                if garment_images.skipped_view(character_name, item_id, fsig, step, v):
                    continue  # an empty drafted back: no later back image
                gs.start(character_name, item_id, step)
                if step == "cutout":
                    garment_images.cut_out(character_name, item_id, fsig, v, force=f)
                else:
                    # A front of the pair step is checked against the accepted back (``_pair_check``).
                    pair = (_pair_check(character_name, item_id, kind, fsig)
                            if step == pair_step and v == "front" else None)
                    garment_images.run_edit_step(character_name, item_id, fsig, step, v, force=f, pair_check=pair,
                                                 prompt_hints=_front_hints(character_name, item_id, fsig, kind,
                                                                           step, v),
                                                 state=image_state,
                                                 before_composite=_composite_guard(character_name, bsig,
                                                                                   base_views, step))
                _drop_mesh(character_name, item_id, fsig)
                _inputs_unchanged(character_name, item_id, fsig, step, state)
                gs.end(character_name, item_id, step)
                if step not in ran:
                    ran.append(step)
            out: Dict[str, Any] = {"ok": True, "fsig": fsig, "ran": ran}
            if first == pair_step:
                agree, gates = _pair(character_name, item_id, kind, fsig)
                if not agree and gates.get("front") and gates.get("back"):
                    # No pair repair here (it would render the other view): the step reads not done, Run all
                    # repairs it, the grid names the view to regenerate.
                    out["pair"] = {"agree": False, "redo": _pair_redo(kind, gates),
                                   "error": _kind_module(kind).PAIR_REFUSED}
            return out
        dirty = False  # an earlier step produced new output: every later step runs again
        regenerated_seed: Optional[int] = None  # the seed a forced HairDeck regenerate of this run made
        # ``only``: up to the last named step (ruling F13 d), else the rest of the chain.
        last = max(wanted, key=order.index) if only and wanted else order[-1]
        run_steps = order[order.index(first):order.index(last) + 1]
        for step in run_steps:
            forced = force and step == first
            gs.start(character_name, item_id, step)
            produced = False
            if step in gs.IMAGE_STEPS:
                for v in _view_order(kind, step):
                    # Ruling A17 (d): an accepted view the current gate refuses is rendered again, not reused.
                    stale = (garment_images.stale_accepted(character_name, item_id, fsig, step, v)
                             # Ruling A46: the piece-only setting names another source than the image's.
                             or garment_images.source_due(character_name, item_id, fsig, step, v))
                    f = (forced and (view is None or v == view)) or stale
                    # Checked per view: a new front of a drafted step (clothing
                    # ``worn``) drops the back it was drafted from.
                    if not f and _accepted(_image(character_name, item_id, fsig, step, v)) and \
                            not garment_images.stale_model_fit(character_name, item_id, fsig, step, v):
                        continue  # a model fit of before Task 11g is re-made (Ruling C2)
                    if garment_images.skipped_view(character_name, item_id, fsig, step, v):
                        continue  # an empty drafted back: no later back image
                    if step == "cutout":
                        garment_images.cut_out(character_name, item_id, fsig, v, force=f)
                    else:
                        # The pair step's back is accepted before its front starts.
                        pair = (_pair_check(character_name, item_id, kind, fsig)
                                if step == pair_step and v == "front" else None)
                        garment_images.run_edit_step(character_name, item_id, fsig, step, v, force=f,
                                                     pair_check=pair,
                                                     prompt_hints=_front_hints(character_name, item_id, fsig,
                                                                               kind, step, v),
                                                     state=image_state,
                                                     before_composite=_composite_guard(character_name, bsig,
                                                                                       base_views, step))
                    produced = True
                    # Right away: a refusal of the next view must not leave a
                    # mesh behind that was built from the replaced image.
                    _drop_mesh(character_name, item_id, fsig)
                    _inputs_unchanged(character_name, item_id, fsig, step, state)
                agree, gates = (_pair(character_name, item_id, kind, fsig) if step == pair_step
                                else (True, None))
                if not agree and _pair_redo(kind, gates) == "back":
                    # Ruling A17 (c): the back is farther from its worn back than the
                    # front from its worn front — the BACK renders again (its gate
                    # holds its hem to the worn back's).
                    garment_images.run_edit_step(character_name, item_id, fsig, step, "back", force=True,
                                                 prompt_hints=_front_hints(character_name, item_id, fsig,
                                                                           kind, step, "back"),
                                                 state=image_state)
                    produced = True
                    _drop_mesh(character_name, item_id, fsig)
                    _inputs_unchanged(character_name, item_id, fsig, step, state)
                    agree, gates = _pair(character_name, item_id, kind, fsig)
                if not agree:
                    # The back is the reference (the hem); the front renders
                    # again against it (two attempts; GateRefused when both miss).
                    garment_images.run_edit_step(character_name, item_id, fsig, step, "front", force=True,
                                                 pair_check=_pair_check(character_name, item_id, kind, fsig,
                                                                        repair=True),
                                                 prompt_hints=_front_hints(character_name, item_id, fsig,
                                                                           kind, step, "front"),
                                                 state=image_state)
                    produced = True
                    _drop_mesh(character_name, item_id, fsig)
                    _inputs_unchanged(character_name, item_id, fsig, step, state)
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
            elif step == "haar":
                # A plain run asks HAAR only when no seed is stored; the step's own (forced) run always asks for
                # the NEXT seeds and keeps the older ones (spec § 6.3.1).
                if forced or not _done(character_name, item_id, kind, fsig, step, base_sha, method, hsig):
                    _run_haar(character_name, item_id, hsig, _haar_next_seeds(character_name, item_id, hsig))
                    produced = True
            elif step == "fit":
                if forced or dirty or _fit_state(character_name, item_id, fsig, base_sha, method) != "accepted":
                    if method == gs.HAIRDECK:
                        _hairdeck_fit_step(character_name, item_id, kind, fsig, bsig, hsig, profile, ran,
                                           prefer_seed=regenerated_seed)
                    elif method == gs.HAAR:
                        # The fsig names the served seed: the fit is published under the one it names now.
                        fsig = _haar_fit_step(character_name, item_id, kind, bsig, profile)
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
        # Chained to load or the media switch it is neither: retry later.
        if _is_load(e):
            return _retry_later(character_name, item_id, fsig, e.step, e, ran)
        logger.warning("Garment run %s/%s failed at %s: %s", character_name, item_id, e.step, e)
        return _refusal(character_name, item_id, fsig, e.step, str(e), {"attempts": e.records}, ran)
    except _Refused as e:
        return _refusal(character_name, item_id, fsig, e.step, e.error, e.gates, ran)
    except Exception as e:  # noqa: BLE001 — reported as the step's failure
        if _is_load(e):
            return _retry_later(character_name, item_id, fsig, step, e, ran)
        logger.warning("Garment run %s/%s failed at %s: %s", character_name, item_id, step, e)
        return _refusal(character_name, item_id, fsig, step, str(e) or type(e).__name__, None, ran)


def _refit_from_source(character_name: str, item_id: str, kind: str, method: str, fsig: str, bsig: str,
                       profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Refit before re-render (``garment_source``): when the image group ``fsig`` has none of its own images
    and the item has an accepted source made on another base, copy it in and fit it onto the current base on the
    CPU (``_fit``; edit chain only). ``{ok: True, fsig, ran, refit: {source…}}`` when accepted; ``{ok: False,
    error, refit}`` when refused (the copies are dropped again, the caller renders the chain); None when there
    is nothing to refit from."""
    from app.core import garment_source, garment_store as gs
    if method != gs.EDIT_CHAIN:
        return None
    if garment_source.has_own_images(character_name, item_id, kind, method, fsig):
        return None
    source = garment_source.find_source(character_name, item_id, kind, method, profile, fsig)
    if source is None:
        return None
    step = "fit"
    gs.start(character_name, item_id, step)
    try:
        garment_source.materialize(character_name, item_id, kind, method, source["fsig"], fsig)
        _fit(character_name, item_id, kind, fsig, bsig, profile)
        ran = ["fit"]
    except Exception as e:  # noqa: BLE001 — any refusal or missing source: the chain is rendered instead
        error = e.error if isinstance(e, _Refused) else (str(e) or type(e).__name__)
        try:
            garment_source.drop_materialized(character_name, item_id, fsig)
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


def _is_load(e: BaseException) -> bool:
    """Whether a failed step is load or the media switch — a ``BackendBusyError``
    or ``MediaGenerationDisabled`` anywhere in the exception chain
    (``footwear_source.failure_of``'s walk of ``__cause__`` / ``__context__``)
    — and so no defect of the item: nothing to persist, try again later."""
    from app.core import footwear_source
    return footwear_source.failure_of(e)[0] == footwear_source.LOAD


def _retry_later(character_name: str, item_id: str, fsig: str, step: str, e: BaseException,
                 ran: List[str]) -> Dict[str, Any]:
    """The result of a step that met load or the media switch: ``retry_later``
    — the item's status shows the text (the Wardrobe), ``_note_outcome``
    persists nothing, so automatic triggers (the outfit build, the
    improvements queue) try again instead of honouring a failure record. The
    footwear chain answers the same way (``garment_footwear.RETRY_LATER_ERRORS``)."""
    from app.core import footwear_source, garment_store as gs
    error = footwear_source.failure_of(e)[1]
    logger.info("Garment run %s/%s deferred at %s (load or the media switch): %s",
                character_name, item_id, step, error)
    gs.end(character_name, item_id, step, error=error, gates=None)
    return {"ok": False, "fsig": fsig, "step": step, "error": error, "gates": None, "ran": ran,
            "retry_later": True}


def check_run(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
              view: Optional[str] = None, state: Optional[str] = None, prerequisites: bool = False) -> None:
    """ValueError unless ``item_id`` is a garment of a known kind owned by
    the character and ``steps`` / ``view`` name steps of its current method
    and a view of it (footwear has none; a view only with one image step,
    Ruling A33); a ``state`` only for a closable
    clothing piece (``open`` / ``closed``), ``open`` only while it is worn
    (``NOT_WORN_OPEN_ERROR``). A view run whose prerequisite views are not
    accepted raises ``PrerequisiteMissing`` (the route's 409) unless
    ``prerequisites`` lets the run make them first; a view that is not made
    (``skipped_view``) is a ValueError."""
    item, kind, order = _item_order(character_name, item_id)
    _require_steps(kind, order)
    wanted = _steps(steps, order)
    _check_view(kind, view)
    _check_view_steps(wanted, view)
    if state is not None:
        from app.core import garment_set
        from app.core.outfit_options import normalise_piece_state
        from app.models.character import get_character_profile
        value = normalise_piece_state(state)
        if kind != _clothing() or not garment_set.closable_of(item):
            raise ValueError(f"{item.get('name') or item_id} has no open / closed state")
        if _run_profile(get_character_profile(character_name) or {}, item_id, value) is None:
            raise ValueError(NOT_WORN_OPEN_ERROR.format(name=item.get("name") or item_id))
    if view is not None and wanted:
        _check_view_run(character_name, item_id, wanted[0], view, state=state, prerequisites=prerequisites)


class _Job:
    """One queued run of a character's worker (``_queues``)."""

    def __init__(self, item_id: str, steps: Union[None, str, Iterable[str]], view: Optional[str],
                 force: bool, automatic: bool = False, state: Optional[str] = None, only: bool = False,
                 prerequisites: bool = False):
        self.item_id, self.steps, self.view, self.force = item_id, steps, view, force
        #: Only the named steps, nothing after them (``run_garment(only=…)``, ruling F13 d); a view run always.
        self.only = (bool(only) or view is not None) and steps is not None
        #: A view run that makes its missing prerequisite views first (Ruling A33, the explicit "first" action).
        self.prerequisites = bool(prerequisites) and view is not None
        #: The open / closed state the run is for; None = the worn state when it starts (``run_garment``).
        self.state = state
        #: Queued by a trigger (``enqueue_garment`` / ``run_queued``), not by a
        #: click: re-checked against ``cached_failure`` when it STARTS, because
        #: the failure it must honour may have been recorded by the run it
        #: waited behind (Task 21 fix round).
        self.automatic = automatic
        #: A click asked for this run (it started it, or attached to it while it waited): never held by the
        #: character's pause of automatic generation (Ruling A42).
        self.clicked = not automatic
        self.done = threading.Event()
        self.result: Dict[str, Any] = {}
        #: The tracked CPU task of a fit-only run (``refit_pool.track``), "" for any other run.
        self.track = ""
        #: Runs beside the character's FIFO (Ruling A30, ``_side``): a CPU refit of an item nothing else runs.
        self.beside = False

    @property
    def plain(self) -> bool:
        """A default run (first missing step on, the worn state) — what a trigger asks for."""
        return self.steps is None and self.view is None and not self.force and self.state is None

    def key(self) -> Tuple[str, Any, Optional[str], bool, Optional[str], bool, bool]:
        """What makes two runs the same request (the steps as a tuple, the state, ``only``, ``prerequisites``)."""
        steps = self.steps
        if steps is not None and not isinstance(steps, str):
            steps = tuple(steps)
        return self.item_id, steps, self.view, bool(self.force), self.state, self.only, self.prerequisites


def _fit_only(steps: Union[None, str, Iterable[str]]) -> bool:
    """A run of the fit step alone (the Wardrobe's fit-only run): a CPU refit, tracked."""
    if steps is None:
        return False
    return ([steps] if isinstance(steps, str) else list(steps)) == ["fit"]


def _end_track(job: "_Job", error: str = "", *, discard: bool = False) -> None:
    """Finish (or, for a run that never ran, discard) the job's tracked CPU task."""
    if not job.track:
        return
    from app.core import refit_pool
    if discard:
        refit_pool.discard(job.track)
    else:
        refit_pool.finish(job.track, error=error)
    job.track = ""


def _held_locked(character_name: str, job: "_Job") -> bool:
    """Ruling A42: an automatic run no click asked for waits while the character's automatic generation is
    paused (``generation_pause``) — it stays in the FIFO, the worker passes over it."""
    if job.clicked or not job.automatic:
        return False
    from app.core import generation_pause
    return generation_pause.is_paused(character_name)


def _pop_runnable_locked(character_name: str) -> Optional["_Job"]:
    """Take the first job of the character's FIFO that is not held (Ruling A42; caller holds ``_lock``). The
    held ones keep their places. None when every waiting job is held (or none waits)."""
    queue = _queues.get(character_name)
    for job in list(queue or ()):
        if not _held_locked(character_name, job):
            queue.remove(job)
            return job
    return None


def held_items(character_name: str) -> List[str]:
    """The item ids of the character's held runs (Ruling A42), in FIFO order, each once."""
    with _lock:
        return list(dict.fromkeys(j.item_id for j in _queues.get(character_name) or ()
                                  if _held_locked(character_name, j)))


def release_held(character_name: str) -> None:
    """Resume (Ruling A42): start the worker for the runs that were held, in their FIFO order."""
    with _lock:
        if character_name in _active or not _queues.get(character_name):
            return   # a worker runs (it takes them next) or nothing waits
        _active.add(character_name)
        try:
            _spawn_locked(character_name)
        except Exception:
            _active.discard(character_name)
            raise


def cancel_held(character_name: str, item_id: str) -> int:
    """The Figure tab's Cancel of a held run (Ruling A42): only the item's HELD runs leave the FIFO (a click's
    run of it stays) — like ``cancel_garment``: their waiters get the cancelled result, their ``queued`` mark
    ends unless the item still has a run. The number of runs taken out."""
    from app.core import garment_store as gs
    with _lock:
        queue = _queues.get(character_name)
        dropped = [j for j in queue or () if j.item_id == item_id and _held_locked(character_name, j)]
        for job in dropped:
            queue.remove(job)
        current = _current.get(character_name)
        still = (current is not None and current.item_id == item_id) or any(
            j.item_id == item_id for j in queue or ()) or item_id in (_side.get(character_name) or {})
        if dropped and not still:
            gs.end(character_name, item_id, QUEUED)
        if queue is not None and not queue and character_name not in _active:
            _queues.pop(character_name, None)
        for job in dropped:
            job.result = {"ok": False, "cancelled": True, "error": CANCELLED, "ran": []}
            job.done.set()
            _end_track(job, discard=True)
    if dropped:
        logger.info("Garment %s/%s: %d held run(s) cancelled", character_name, item_id, len(dropped))
    return len(dropped)


def _spawn_locked(character_name: str) -> None:
    """Start the worker of a character whose queue was just filled (caller
    holds ``_lock`` and has added the character to ``_active``). The first
    job that is not held (Ruling A42) becomes the character's ``_current``
    run here, so the queue view never shows a run that is about to start as
    waiting. When every waiting job is held no worker starts (the character
    leaves ``_active``; ``release_held`` starts it on Resume)."""
    queue = _queues[character_name]
    job = _pop_runnable_locked(character_name)
    if job is None:
        _active.discard(character_name)
        return
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
        _end_track(job, discard=True)
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
        error = _execute(character_name, job)
        with _lock:
            # Ends the ``queued`` mark of a run that had nothing to do or
            # failed before its first step (a step replaces the mark).
            gs.end(character_name, job.item_id, QUEUED, error=error)
            queue = _queues.get(character_name)
            # Ruling A42: the next run that is not held; held runs keep their places in the FIFO.
            nxt = _pop_runnable_locked(character_name) if queue else None
            if nxt is not None:
                _current[character_name] = nxt
                if job.item_id in {nxt.item_id, *(j.item_id for j in queue)}:
                    # The item runs again (a click while it ran): it waits again.
                    gs.start(character_name, job.item_id, QUEUED)
            else:
                if queue:
                    if job.item_id in {j.item_id for j in queue}:
                        gs.start(character_name, job.item_id, QUEUED)   # a held run of the same item waits
                else:
                    _queues.pop(character_name, None)
                _current.pop(character_name, None)
                _active.discard(character_name)
            job.done.set()
            if character_name not in _active:
                return


def _execute(character_name: str, job: "_Job") -> Optional[str]:
    """Run one job (the FIFO worker's and a refit's beside it): ``job.result`` is set, the tracked CPU task
    ends; returns the error of a run that raised, else None."""
    error: Optional[str] = None
    if job.track:
        from app.core import refit_pool
        refit_pool.activate(job.track)
    try:
        failure = cached_failure(character_name, job.item_id) if job.automatic else None
        if failure is not None:
            # The run this job waited behind refused the same input: an
            # automatic run never spends the chain on it again.
            logger.info("Garment run %s/%s skipped: %s refused for this input (%s) — waits for an"
                        " explicit run", character_name, job.item_id, failure.get("step"),
                        str(failure.get("error") or "")[:120])
            job.result = {"ok": False, "fsig": failure.get("fsig"), "step": failure.get("step"),
                          "error": failure.get("error"), "cached": True, "ran": []}
        elif job.beside:
            job.result = run_garment(character_name, job.item_id, steps=job.steps, view=job.view,
                                     force=job.force, state=job.state, only=job.only, beside=True)
        else:
            # ``prerequisites`` only when asked (Ruling A33): every other run keeps its call as before.
            job.result = run_garment(character_name, job.item_id, steps=job.steps, view=job.view,
                                     force=job.force, state=job.state, only=job.only,
                                     **({"prerequisites": True} if job.prerequisites else {}))
    except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
        logger.error("Garment run %s/%s failed: %s", character_name, job.item_id, e)
        error = str(e) or type(e).__name__
        job.result = {"ok": False, "error": error}
    _end_track(job, "" if job.result.get("ok") else str(job.result.get("error") or "the fit was refused"))
    return error


def _side_worker(character_name: str, job: "_Job") -> None:
    """Ruling A30: run a CPU refit beside the character's FIFO (``start_garment``), then take it out of
    ``_side``. When the item has a run in the FIFO by then (queued while this one ran) it waits again."""
    from app.core import garment_store as gs
    error: Optional[str] = None
    try:
        error = _execute(character_name, job)
    finally:
        with _lock:
            gs.end(character_name, job.item_id, QUEUED, error=error)
            side = _side.get(character_name) or {}
            if side.get(job.item_id) is job:
                side.pop(job.item_id, None)
            if not side:
                _side.pop(character_name, None)
            current = _current.get(character_name)
            if (current is not None and current.item_id == job.item_id) or any(
                    j.item_id == job.item_id for j in _queues.get(character_name) or ()):
                gs.start(character_name, job.item_id, QUEUED)
            job.done.set()


def _base_in_flight(character_name: str) -> str:
    """What changes or holds the character's base body now (Ruling A30: no refit runs beside the FIFO then):
    a base-body step (``figure_build.base_step_in_flight``, Ruling A26) or the 3D generation guard
    (``model3d.generation_running`` — a base model run, the Build's model steps). "" when none."""
    from app.core import figure_build, model3d
    step = figure_build.base_step_in_flight(character_name)
    if step:
        return step
    return "3D generation" if model3d.generation_running(character_name) else ""


def _beside_ok_locked(character_name: str, item_id: str) -> bool:
    """Whether a CPU refit of ``item_id`` may start beside the FIFO (Ruling A30; caller holds ``_lock`` and has
    checked the base, ``_base_in_flight``): the FIFO runs ANOTHER item, and the item has no run in flight,
    waiting or beside, and no refit sweep holds the character."""
    current = _current.get(character_name)
    if character_name not in _active or current is None or current.item_id == item_id:
        return False
    if character_name in _held or item_id in (_side.get(character_name) or {}):
        return False
    return all(j.item_id != item_id for j in _queues.get(character_name) or ())


def busy(character_name: str) -> bool:
    """A garment run of the character runs or waits — in its FIFO or beside it (Ruling A30)."""
    with _lock:
        return character_name in _active or bool(_side.get(character_name))


def hold_all(character_name: str) -> bool:
    """Take the character's garment run lock WITHOUT waiting for a character-wide pass (the refit sweep,
    ``garment_refit.refit_character``): False when a garment run of the character runs or waits — in the FIFO
    or beside it — or the lock is held. While held no refit starts beside the FIFO (Ruling A30): such a click
    queues as before. Release with ``release_all``."""
    from app.core import garment_store as gs
    with _lock:
        if character_name in _active or _side.get(character_name) or character_name in _held:
            return False
        if not gs.char_lock(character_name).acquire(blocking=False):
            return False
        _held.add(character_name)
    return True


def release_all(character_name: str) -> None:
    """End ``hold_all``."""
    from app.core import garment_store as gs
    gs.char_lock(character_name).release()
    with _lock:
        _held.discard(character_name)


def _position_locked(character_name: str, job: "_Job") -> Dict[str, Any]:
    """``{started, queued, position, behind}`` of a job the caller just put
    into the character's FIFO (caller holds ``_lock``): ``position`` 0 and
    ``started`` True for the run in flight, else its 1-based place among the
    waiting runs, ``behind`` the item id in flight. A refit beside the FIFO
    (Ruling A30) has started and waits behind nothing: ``beside`` True."""
    if job.beside:
        return {"started": True, "queued": False, "position": 0, "behind": None, "beside": True}
    current = _current.get(character_name)
    if current is job:
        return {"started": True, "queued": False, "position": 0, "behind": None}
    queue = list(_queues.get(character_name) or ())
    return {"started": False, "queued": True, "position": queue.index(job) + 1,
            "behind": current.item_id if current is not None else None}


def start_garment(character_name: str, item_id: str, *, steps: Union[None, str, Iterable[str]] = None,
                  view: Optional[str] = None, force: bool = False,
                  state: Optional[str] = None, only: bool = False,
                  prerequisites: bool = False) -> Dict[str, Any]:
    """Run ``run_garment`` in the character's worker thread — at once when
    the character has no garment run, else queued behind its runs (never
    refused). An identical waiting run (same item, steps, view, force) is not
    added twice; a waiting default run of the item becomes this explicit run
    in its place (its waiters get this run's result); the item's run IN
    FLIGHT does not count — this run is appended and runs after it. The item
    counts as running (``queued``) from THIS moment (the UI polls), unless it
    is in a step right now. Returns ``{started, queued, position, behind}``
    (``_position_locked``). ValueError for an invalid item, step or view
    (checked before anything is queued).

    ``state`` (plan Task 11b): the open / closed state the run is for (the
    piece details' "Build the open mesh"); None = the state the piece is
    worn in when the run STARTS. It is part of the request: a waiting
    default run of the item is replaced only by an explicit run of the state
    the piece is worn in now (a default run builds that state).

    ``only`` (ruling F13 d): the named steps alone, nothing after them
    (``run_garment``) — the steps dialog's step buttons; without ``steps``
    it means nothing (a default run is the chain).

    ``view`` (Ruling A33): the step's view alone (``run_garment``);
    ``PrerequisiteMissing`` before anything is queued while a view it needs
    is not accepted, unless ``prerequisites`` (the button's explicit "first"
    action) lets the run make them first.

    Ruling A30: a fit-only run (a CPU refit) of an item with no run in
    flight, waiting or beside starts at once BESIDE the character's run of
    another item (``_side_worker``, ``_beside_ok_locked``) — ``{started True,
    queued False, position 0, behind None, beside True}`` — unless a base-body
    step or the 3D generation guard is in flight (``_base_in_flight``) or a
    refit sweep holds the character: then it queues as before."""
    from app.core import garment_store as gs
    check_run(character_name, item_id, steps=steps, view=view, state=state,
              **({"prerequisites": True} if prerequisites else {}))
    wanted = _Job(item_id, steps, view, bool(force), state=state, only=only, prerequisites=prerequisites)
    # A default run builds the worn state: an explicit run of the OTHER state never takes its place.
    takes_default = wanted.state is None or wanted.state == _worn_state(character_name, item_id)
    # A fit-only run is a CPU refit: tracked from the click on (pending while it waits behind other runs).
    track = ""
    beside = False
    if _fit_only(steps):
        from app.core import refit_pool
        track = refit_pool.track(character_name, refit_pool.fits_label(character_name, 1), pending=True)
        # Read before ``_lock`` (its registries have locks of their own): a base step that starts right after
        # is the same as one started while the refit computes — as with an idle FIFO today.
        beside = not _base_in_flight(character_name)
    with _lock:
        if beside and _beside_ok_locked(character_name, item_id):
            wanted.beside = True
            wanted.track, track = track, ""
            _side.setdefault(character_name, {})[item_id] = wanted
            if not gs.status(character_name, item_id).get("running_step"):
                gs.start(character_name, item_id, QUEUED)
            try:
                threading.Thread(target=_side_worker, args=(character_name, wanted), daemon=True,
                                 name=f"garment-refit-{character_name}-{item_id}").start()
            except Exception:
                side = _side.get(character_name) or {}
                side.pop(item_id, None)
                if not side:
                    _side.pop(character_name, None)
                gs.end(character_name, item_id, QUEUED)
                _end_track(wanted, discard=True)
                raise
            return _position_locked(character_name, wanted)
        queue = _queues.setdefault(character_name, deque())
        job = next((j for j in queue if j.key() == wanted.key()), None)
        if job is None and not wanted.plain and takes_default:
            job = next((j for j in queue if j.item_id == item_id and j.plain), None)
            if job is not None:
                # Explicit wins, the place in the queue stays.
                job.steps, job.view, job.force, job.state = wanted.steps, wanted.view, wanted.force, wanted.state
                job.only, job.prerequisites = wanted.only, wanted.prerequisites
        if job is None:
            job = wanted
            queue.append(job)
        # A click is never held by the pause (Ruling A42) — nor the waiting run it attached to.
        job.clicked = True
        if track and not job.track:
            job.track, track = track, ""
        if not gs.status(character_name, item_id).get("running_step"):
            gs.start(character_name, item_id, QUEUED)
        if character_name not in _active:
            _active.add(character_name)
            try:
                _spawn_locked(character_name)
            except Exception:
                _abort_spawn_locked(character_name, item_id)
                raise
        position = _position_locked(character_name, job)
    if track:
        # An identical fit-only run already waits with its own track.
        from app.core import refit_pool
        refit_pool.discard(track)
    return position


def _worn_state(character_name: str, item_id: str) -> str:
    """The state the piece is worn in now (``garment_store.item_state`` of the live profile)."""
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    return gs.item_state(character_name, item_id, get_character_profile(character_name) or {})


def enqueue_garment(character_name: str, item_id: str, *, automatic: bool = True) -> "_Job":
    """Queue a default run (first missing step on) of ``item_id`` behind the
    character's other runs — the per-character FIFO the triggers use
    (the Build's ``run_queued``). A default run of the same item that has
    not started yet is reused, never queued twice (``automatic`` False — a
    manual Build — makes it explicit: it no longer honours a cached
    failure). Returns the job (``done`` / ``result``). ValueError like
    ``check_run``."""
    from app.core import garment_store as gs
    check_run(character_name, item_id)
    with _lock:
        queue = _queues.setdefault(character_name, deque())
        job = next((j for j in queue if j.item_id == item_id and j.plain), None)
        if job is not None:
            job.automatic = job.automatic and automatic
            if not automatic:
                job.clicked = True   # a manual Build asked: never held (Ruling A42)
        else:
            job = _Job(item_id, None, None, False, automatic=automatic)
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
        # A refit beside the FIFO (Ruling A30) is in flight as well.
        in_flight = (current is not None and current.item_id == item_id) or \
            item_id in (_side.get(character_name) or {})
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
            _end_track(job, discard=True)
        waiting = [j.item_id for j in queue]
    logger.info("Garment %s/%s: %d waiting run(s) cancelled", character_name, item_id, len(dropped))
    return {"item_id": item_id, "cancelled": len(dropped),
            "queue_running": current.item_id if current is not None else None, "queue": waiting}


def queue_state(character_name: str, item_id: Optional[str] = None) -> Dict[str, Any]:
    """The character's garment queue for the UI: ``{queue_running, queue,
    beside}`` — the item id in flight in the FIFO (None when idle), the
    waiting item ids in run order and the item ids of the CPU refits running
    beside the FIFO (Ruling A30, sorted); with ``item_id`` also
    ``queue_position``: the 1-based place of the item's first waiting run
    (None when it waits for nothing), and ``queue_beside``: the item's refit
    runs beside the FIFO — it waits behind nothing (the UI never says
    "Queued behind …" for it)."""
    with _lock:
        current = _current.get(character_name)
        waiting = [j.item_id for j in _queues.get(character_name) or ()]
        beside = sorted(_side.get(character_name) or {})
    out: Dict[str, Any] = {"queue_running": current.item_id if current is not None else None,
                           "queue": waiting, "beside": beside}
    if item_id is not None:
        out["queue_position"] = waiting.index(item_id) + 1 if item_id in waiting else None
        out["queue_beside"] = item_id in beside
    return out


def run_queued(character_name: str, item_ids: Iterable[str], *,
               explicit: bool = False) -> Dict[str, Dict[str, Any]]:
    """Run the chains of ``item_ids`` through the character's FIFO and wait
    for every one (blocking — the Build calls it). item id ->
    ``run_garment``'s result, or ``{ok: False, error}`` for an item that
    could not be queued, or ``{ok: False, paused: True, error}`` for an
    automatic run held by the character's pause (Ruling A42: it stays in the
    FIFO, Resume runs it; the caller stops waiting). An automatic trigger: an item whose chain failed
    for its current fsig (``cached_failure``) is not run — its result is
    that failure with ``cached: True``. ``explicit`` (a manual Build, ruling
    7a of plan 2026-11-12-unified-worn-pieces): the persisted failure of the
    item's current fsig is cleared and the default run goes as an explicit
    one — from the failed step (the first without accepted output; the
    chain re-judges stored attempts under the current gate versions
    first)."""
    jobs: Dict[str, Any] = {}
    out: Dict[str, Dict[str, Any]] = {}
    for item_id in item_ids:
        if explicit:
            _clear_cached_failure(character_name, item_id)
            try:
                jobs[item_id] = enqueue_garment(character_name, item_id, automatic=False)
            except ValueError as e:
                out[item_id] = {"ok": False, "error": str(e)}
            continue
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
        while not job.done.wait(HELD_POLL_S):
            if _job_held(character_name, job):
                # Ruling A42: the character's automatic generation was paused while this run waited — it stays
                # in the FIFO (Resume runs it), the caller does not wait for it.
                out[item_id] = {"ok": False, "paused": True, "error": HELD_ERROR, "ran": []}
                from app.core import generation_pause
                generation_pause.notify_waiting(character_name)
                break
        else:
            out[item_id] = dict(job.result or {"ok": False, "error": "the run ended without a result"})
    return out


#: How often ``run_queued`` looks whether a waiting automatic run became held (Ruling A42).
HELD_POLL_S = 0.5
#: ``run_queued``'s result of a run held by the pause (Ruling A42, ``generation_pause``).
HELD_ERROR = "Held — automatic generation of this character is paused"


def _job_held(character_name: str, job: "_Job") -> bool:
    """Whether ``job`` waits in the character's FIFO and is held (Ruling A42)."""
    with _lock:
        return job in (_queues.get(character_name) or ()) and _held_locked(character_name, job)


def _clear_cached_failure(character_name: str, item_id: str) -> None:
    """Drop the persisted failure of the item's CURRENT fsig (a manual Build retries it)."""
    from app.core import garment_store as gs
    try:
        fsig = gs.garment_fsig(character_name, item_id)
    except ValueError:
        return
    gs.clear_failure(character_name, item_id, fsig)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until no worker runs (smokes). True when idle."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if not _active and not _side:
                return True
        time.sleep(0.05)
    return False


# --- Collecting a finished mesh job ------------------------------------------------

class StepBusy(RuntimeError):
    """``collect_mesh_job``: the lock its mesh step runs under is held — a run is going (a route answers 409)."""


#: ``collect_mesh_job``'s refusal while a garment run of the character holds its run lock.
RUN_GOING = "A garment run of this character is going — fetch the job once it has ended"


def _clear_failure_from(character_name: str, item_id: str, fsig: str, step: str, order: Tuple[str, ...]) -> None:
    """Drop the persisted failure of ``(item_id, fsig)`` when it names ``step`` or a later step (a new
    accepted mesh makes those run again anyway); a failure before it stays."""
    from app.core import garment_store as gs
    try:
        failed = str(gs.read_record(gs.garment_path(character_name, item_id, fsig, "failed")).get("step") or "")
    except ValueError:
        return
    if failed and failed in order and order.index(failed) >= order.index(step):
        gs.clear_failure(character_name, item_id, fsig)


def collect_mesh_job(character_name: str, item_id: str, job_id: str, *, footwear: bool) -> Dict[str, Any]:
    """Collect a FINISHED gateway mesh job by its id as the item's mesh step — for a mesh whose run outlived
    our own poll (timeout, server restart) but finished on the gateway. Reuses the character models' fetch
    (``ImageService.fetch_mesh_job``: each mesh gateway asked once, checksums verified, rig ``none``).

    The mesh step of the item's CURRENT method, under the lock that step runs under, taken WITHOUT waiting
    (``StepBusy`` while it is held — a collected job never races a running step):

    - edit chain (clothing): ``garment_mesh.collect_job`` under the character's run lock
      (``garment_store.char_lock``) and the item's (``run_item_lock``, Ruling A30), step ``mesh``;
    - footwear: ``footwear_source.collect_mesh_job`` under the ITEM lock, step ``mesh`` of the shoe source.

    Each runs the SAME prepare + gates as a fresh attempt and writes the same record plus ``collected_job``.
    Accepted: the step's failure (persisted, in memory) ends when it named this step or a later one. Refused
    (gate) or failed (decimation, an unreadable delivery): an ACCEPTED mesh of the step is never touched —
    nothing is written, nothing recorded (``kept: True``, the reasons in the answer); without one it is
    recorded as the step's failure like a run's. A job
    that is not done, unknown, someone else's or failed changes nothing. Nothing starts a run: the next run
    reuses the accepted mesh and runs only what follows (CPU).

    Returns the store's answer plus ``step`` (and ``fsig``): ``status`` ``accepted`` / ``refused`` /
    ``step_failed`` / ``queued`` / ``running`` / ``unknown`` / ``forbidden`` / ``failed`` / ``rig_mismatch``
    / ``error``. ValueError for an item that is no garment of the character, a footwear piece on the
    garment route (or the reverse, ``footwear``), or hair (HairDeck, HAAR or the body mesh: no mesh job);
    ``base_body.MissingInput`` / FileNotFoundError when the step's input is missing. Blocking."""
    from app.core import base_body, garment_mesh, garment_store as gs
    from app.models.character import get_character_profile
    _item_, kind = _item(character_name, item_id)
    if (kind == _footwear()) != bool(footwear):
        raise ValueError(f"{item_id} is {'no' if footwear else 'a'} footwear piece"
                         + ("" if footwear else " — its mesh is the shoe source's"))
    profile = get_character_profile(character_name) or {}
    method = gs.kind_method(kind, character_name, profile, item_id=item_id)
    order = gs.steps_for(kind, method)
    if method in (gs.HAIRDECK, gs.HAAR):
        raise ValueError(f"Hair made by {'HairDeck' if method == gs.HAIRDECK else 'HAAR'} has no mesh job to fetch")
    _require_steps(kind, order, method)
    step = "mesh"
    if kind == _footwear():
        from app.core import footwear_source
        try:
            res = footwear_source.collect_mesh_job(item_id, job_id)
        except footwear_source.SourceBusy as e:
            raise StepBusy(str(e)) from e
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
    else:
        lock = gs.char_lock(character_name)
        if not lock.acquire(blocking=False):
            raise StepBusy(RUN_GOING)
        try:
            # The item's run lock too (Ruling A30): a refit of this item beside the FIFO reads its mesh.
            item_lock = gs.run_item_lock(character_name, item_id)
            if not item_lock.acquire(blocking=False):
                raise StepBusy(RUN_GOING)
            try:
                fsig = gs.garment_fsig(character_name, item_id, profile=profile)
                res = garment_mesh.collect_job(character_name, item_id, fsig, job_id)
            finally:
                item_lock.release()
        finally:
            lock.release()
    status = res.get("status")
    out = {**res, "step": step, "fsig": fsig}
    if status == "accepted":
        gs.end(character_name, item_id, step)
        _clear_failure_from(character_name, item_id, fsig, step, order)
    elif status in ("refused", garment_mesh.STEP_FAILED) and not res.get("kept"):
        # Recorded like the step's own refusal only when no accepted mesh was there: a refused fetch next to an
        # accepted mesh changed nothing (the stores wrote nothing), so the step has not failed.
        error = str(res.get("error") or status)
        gates = res.get("gates") if kind == _footwear() else {"attempts": (res.get("record") or {}).get("attempts")
                                                                           or []}
        gs.end(character_name, item_id, step, error=error, gates=gates)
        base = base_body.current_base(character_name, profile=profile)
        gs.record_failure(character_name, item_id, fsig, step=step, error=error,
                          base_model_sha=base[1] if base else "")
    logger.info("Garment %s/%s: mesh job %s collected for %s: %s", character_name, item_id, job_id, step, status)
    return out


# --- Triggers -------------------------------------------------------------------

def after_base_model(character_name: str) -> bool:
    """R14: a successful base model run changed the body every worn garment
    is fitted on — a BODY CHANGE for the character's Build (plan
    2026-11-12-unified-worn-pieces Task 8, ``figure_build.request(name,
    "body_change")``). With "Build automatically" on, the Build plans and
    runs what the new body needs: the chains of the worn garments (hair and
    own-mesh pieces, footwear fit-only: its item steps are cached under its
    ssig) whose fit is not accepted on it — a refit of the last accepted
    source first when the fsig changed — through the character's FIFO
    (``run_queued``; a chain that failed for its current fsig is skipped,
    ``cached_failure``), the first hairstyle of a character with hair text but
    none (``garment_hair.ensure_hairstyle``), the CPU refits, the assembly.
    Off, nothing runs and the change stays marked
    (``figure.pending_changes``). A request during a running Build becomes
    its one follow-up. True when a Build was started or kept. Never raises."""
    try:
        from app.core import base_body, figure_build
        if base_body.current_base(character_name) is None:
            return False
        return figure_build.request(character_name, "body_change")
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
    from app.core.garment_images import ATTEMPTS, skipped_view
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
    block = record.get("user_accepted") if isinstance(record.get("user_accepted"), dict) else None
    out = {"url": _url(character_name, item_id, f"images/{step}/{view}", stamp) if stamp is not None else None,
           "accepted": _accepted(final), "gates": gates, "attempts": attempts,
           # Ruling A37: taken by the user against its gate; ``holds`` False once an input changed.
           "user_accepted": ({"at": block.get("at"), "attempt": block.get("attempt"),
                              "reasons": block.get("reasons") or [], "holds": _accepted(final)}
                             if block and stamp is not None else None),
           **(image_tile_meta(final, record) if stamp is not None else {})}
    # Ruling A46c: a piece-only view made from the worn view carries its mask numbers (the cell's light).
    if isinstance(record.get("from_worn"), dict) and stamp is not None:
        out["from_worn"] = record["from_worn"]
    # An empty drafted back (the base back unchanged) and the views it leaves out.
    if record.get("composite") == "empty":
        out["empty"] = True
    skipped = skipped_view(character_name, item_id, fsig, step, view)
    if skipped:
        out["skipped"] = skipped
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
            "tris": record.get("tris_prepared"), "created_at": record.get("created_at"),
            "view": _mesh_view_info(character_name, item_id, fsig, record, accepted=status == "accepted")}


def _mesh_view_info(character_name: str, item_id: str, fsig: str, record: Dict[str, Any], *,
                    accepted: bool) -> Dict[str, Any]:
    """The Mesh row's 3D view (Ruling A48a, ``garment_mesh_view``): ``{prepared, raw, attempts}`` — each mesh
    file ``{url, body_url, tris}`` (``url`` versioned by content; ``body_url`` the body view's JSON; ``tris``
    counted in the file, ``garment_mesh_view.file_triangles``) or None, and
    every refused or failed attempt of the step record's last run ``{attempt, ok, reasons, error, tris_raw,
    tris_prepared, largest_component_share, prepared, raw}`` with its kept files (``garment_mesh.attempt_files``;
    None when nothing was kept — a failed attempt has no mesh)."""
    from app.core import garment_mesh, garment_mesh_view
    from app.core.garment_store import garment_path
    from app.core.http_files import content_version

    def file(path: Optional[Path], which: str, attempt: int, tris: Any) -> Optional[Dict[str, Any]]:
        if path is None or not path.is_file():
            return None
        try:
            version = content_version(path)
        except OSError:
            return None
        extra = f"&attempt={attempt}" if attempt else ""
        body = (f"/characters/{quote(character_name, safe='')}/garments/{quote(item_id, safe='')}/mesh/{which}/body"
                + (f"?attempt={attempt}" if attempt else ""))
        return {"url": _url(character_name, item_id, f"mesh/{which}", version, extra), "body_url": body,
                "tris": garment_mesh_view.file_triangles(path, version) or tris}

    out: Dict[str, Any] = {
        "prepared": file(garment_path(character_name, item_id, fsig, "prepared"), "prepared", 0,
                         record.get("tris_prepared")) if accepted else None,
        "raw": file(garment_path(character_name, item_id, fsig, "raw"), "raw", 0, record.get("tris_raw")),
        "attempts": [],
    }
    for entry in record.get("attempts") or []:
        if not isinstance(entry, dict) or entry.get("ok") is True:
            continue
        try:
            number = int(entry.get("attempt") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= number <= garment_mesh.MAX_ATTEMPTS:
            continue
        kept = garment_mesh.attempt_files(character_name, item_id, fsig, number)
        out["attempts"].append({
            "attempt": number, "ok": False, "reasons": list(entry.get("reasons") or []),
            "error": entry.get("error") or "",
            **{k: entry.get(k) for k in ("tris_raw", "tris_prepared", "largest_component_share")},
            "prepared": file(kept["prepared"], "prepared", number, entry.get("tris_prepared")),
            "raw": file(kept["raw"], "raw", number, entry.get("tris_raw")),
        })
    return out


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
    """The hair preview GLB: the current-fsig fit when it exists, else
    the fit served on the current base model, else the newest accepted fit
    of the current method. None when there is no fit at all.

    ``method`` naming ANOTHER method than the current one: that method's
    newest accepted fit (on the current base model first, else on any) —
    the tab's "Other method" preview. ValueError for an unknown method."""
    from app.core import base_body, garment_store as gs
    from app.core.garment_hair import HAIR_MODES
    from app.models.character import get_character_profile
    if method and method not in HAIR_MODES:
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
    """``(fit GLB, record, on the current base model)`` of the fit the
    hairstyle would serve in ``method`` (a mode it no longer has): its
    fit under the fingerprint of that mode (``garment_store.garment_fsig``
    with ``method``), else the newest accepted fit of that mode on the
    current base model, else on any base model; None without one."""
    from app.core import base_body, garment_store as gs
    base = base_body.current_base(character_name, profile=profile)
    if base and base[1]:
        path = gs.garment_path(character_name, item_id,
                               gs.garment_fsig(character_name, item_id, profile=profile, method=method), "fit")
        record = gs.read_record(path.with_suffix(".json"))
        if path.is_file() and gs._accepted_on(record, base[1]) and gs.fit_method(record) == method:
            return path, record, True
        hit = gs.newest_accepted_fits(character_name, item_id, base_model_sha=base[1]).get(method)
        if hit:
            return hit[0], hit[1], True
    hit = gs.newest_accepted_fits(character_name, item_id).get(method)
    return (hit[0], hit[1], False) if hit else None


def other_methods_info(character_name: str, item_id: str, *,
                       profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The hair GET's "Other methods": one entry per hair mode the hairstyle
    does NOT have that kept a result — ``{method, preview_url, created_at, metrics,
    colour, on_current_base}`` of the accepted fit it would serve if selected
    (``_other_fit``) — newest first; ``[]`` when none has one (or the item is
    no hair). Selecting such a method generates nothing: its fit is served as
    it is (a fit on an older base model stays stale until the method runs)."""
    from app.core import garment_hair
    from app.core.hair_strands import preview_version
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    _item_, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        return []
    current = garment_hair.hairstyle_mode(_item_)
    hits = [(m, _other_fit(character_name, item_id, m, profile)) for m in garment_hair.HAIR_MODES if m != current]
    hits = [(m, h) for m, h in hits if h is not None]
    hits.sort(key=lambda mh: _stamp(mh[1][0]) or 0, reverse=True)
    out: List[Dict[str, Any]] = []
    for method, (path, record, on_base) in hits:
        try:
            url: Optional[str] = _url(character_name, item_id, "model", preview_version(path), f"&method={method}")
        except OSError:
            url = None
        out.append({"method": method, "preview_url": url, "created_at": record.get("created_at"),
                    "metrics": record.get("metrics") or {}, "colour": record.get("colour"),
                    "on_current_base": on_base})
    return out


#: The HairDeck images the hair row shows: the input (the profile picture
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
    """The hair row's HairDeck details for the CURRENT ``hsig`` (whichever
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
    - ``placement``: ``{forward_m, tilt_deg, width_scale, default_forward_m,
      limits, fitted}`` — the manual values (None = automatic,
      ``garment_hair.hair_placement``), the automatic forward shift, the
      bounds of a manual value and what the newest HairDeck fit applied
      (its record's ``placement``; None without a fit or from a fit before
      the placement correction), ``pivot`` the point that fit tilted the hair about (``[x, y, z]`` metres,
      its report's ``placement.pivot``; None without);
    - ``chains``: the spring chains of the newest HairDeck fit and the
      Swing/Stiffness settings (``hair_motion.panel``).

    None for an item that is no hair."""
    import json as _json
    from app.core import garment_hair, garment_hairdeck, hair_motion, garment_store as gs
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
    settings, text = _hair_of(character_name, item_id)
    override = garment_hair.hair_colour_override(settings)
    named = garment_hair.profile_hair_colour(character_name, profile=profile, text=text)
    newest = _newest_fit(character_name, item_id, gs.HAIRDECK)
    colour = {"target": override or None,
              "source": "override" if override else ("profile" if named else "hairdeck"),
              "auto": _rgb_hex(info.get("hair_color")) if isinstance(info, dict) else None,
              "profile": named, "fitted": newest[1].get("colour") if newest else None}
    placement = {"width_scale": None, **garment_hair.hair_placement(settings),
                 "default_forward_m": garment_hairdeck.DEFAULT_FORWARD_M,
                 "limits": garment_hair.placement_limits(),
                 "fitted": newest[1].get("placement") if newest else None,
                 # The point the fit pitched the hair about (its report's placement): the Hairstyles tab's live
                 # placement preview turns the fitted hair about it; None without a fit or from an older one.
                 "pivot": ((newest[1].get("report") or {}).get("placement") or {}).get("pivot") if newest else None}
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
            "chains": hair_motion.panel(character_name, settings, newest[1] if newest else None,
                                       newest[0] if newest else None, profile=profile),
            "input_source": "beard_free" if sent is not None and sent != source else "profile"}


def _haar_info(character_name: str, item_id: str, ssig: str) -> Dict[str, Any]:
    """The HAAR step of ``ssig``: ``{ssig, status accepted|refused|missing, seeds, failed, created_at}`` —
    ``accepted`` with a stored seed, ``refused`` when every job asked for failed, ``missing`` otherwise."""
    from app.core import garment_store as gs
    if not ssig:
        return {"ssig": ssig, "status": "missing", "seeds": [], "failed": {}, "created_at": None}
    seeds = gs.haar_seeds(character_name, item_id, ssig)
    record = gs.haar_record(character_name, item_id, ssig)
    jobs = record.get("jobs") or {}
    failed = {k: v.get("error") for k, v in jobs.items() if isinstance(v, dict) and v.get("error")}
    stamps = [v.get("created_at") for v in jobs.values() if isinstance(v, dict) and v.get("created_at")]
    return {"ssig": ssig, "status": "accepted" if seeds else "refused" if failed else "missing", "seeds": seeds,
            "failed": failed, "created_at": max(stamps) if stamps else None}


def haar_panel(character_name: str, item_id: str, *,
               profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The HAAR variants of a hairstyle under its CURRENT ``ssig`` (whichever mode it has): ``{ssig, status,
    seeds: [{seed, passed, reasons, metrics, tile_url, served, picked}], next_seeds, jobs, picked, served}``.

    - ``status``: ``missing`` (no seed stored), ``unfitted`` (seeds without a fit verdict yet), ``passed`` (a
      seed passes), ``no variant passed`` (every fitted seed refused — a pick still serves one);
    - per seed: ``passed`` None until it is fitted; ``reasons`` the gate's words; ``metrics`` the fit's numbers
      (mouse-over); ``tile_url`` the seed's tile (``HAAR_TILE``, rendered at fit time; None without one);
      ``served`` the seed the fsig names (``garment_store.haar_served_seed``: the one a Re-fit serves);
      ``picked`` the hairstyle's ``haar_seed``; ``in_use`` the seed of the fit the preview shows (its record's
      ``inputs.seed`` when it was made from this ``ssig``);
    - ``in_use``: that seed (None without such a fit);
    - ``next_seeds``: the seeds the step's button asks for; ``jobs``: ``HAAR_SEEDS`` (its hub jobs);
    - ``route``: ``{routed, backend}`` — the backend the ``hair_strands`` occasion is meant to run on for the
      character (``routing.intended_backend``: configuration only); ``routed`` False when there is none, so the
      tab says so and spends nothing.

    None for an item that is no hair."""
    from app.core import garment_hair, garment_store as gs
    from app.models.character import get_character_profile
    if profile is None:
        profile = get_character_profile(character_name) or {}
    item, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        return None
    ssig = gs.garment_ssig(character_name, item_id, profile=profile)
    stored = gs.haar_seeds(character_name, item_id, ssig)
    results = gs.haar_record(character_name, item_id, ssig).get("results") or {}
    served = gs.haar_served_seed(character_name, item_id, ssig, item=item)
    pick = gs.haar_pick(item)
    in_use = _haar_in_use(character_name, item_id, ssig)
    folder = gs.haar_dir(character_name, item_id, ssig)
    seeds = []
    for seed in stored:
        r = results.get(str(seed))
        r = r if isinstance(r, dict) else None
        stamp = _stamp(gs.haar_seed_dir(folder, seed) / HAAR_TILE) if r and r.get("tile") else None
        seeds.append({"seed": seed, "passed": (r.get("accepted") is True) if r else None,
                      "reasons": list(r.get("reasons") or []) if r else [],
                      "metrics": dict(r.get("metrics") or {}) if r else {},
                      "tile_url": _url(character_name, item_id, f"haar/{seed}/{HAAR_TILE}", stamp)
                      if stamp is not None else None,
                      "served": seed == served, "picked": seed == pick, "in_use": seed == in_use})
    fitted = [e for e in seeds if e["passed"] is not None]
    if not seeds:
        status = "missing"
    elif any(e["passed"] for e in fitted):
        status = "passed"
    elif len(fitted) < len(seeds):
        status = "unfitted"
    else:
        status = NO_VARIANT_PASSED
    return gs.finite_json({"ssig": ssig, "status": status, "seeds": seeds,
                           "next_seeds": _haar_next_seeds(character_name, item_id, ssig), "jobs": HAAR_SEEDS,
                           "picked": pick, "served": served, "in_use": in_use,
                           "route": haar_route(character_name)})


def haar_route(character_name: str) -> Dict[str, Any]:
    """``{routed, backend}``: the backend the ``hair_strands`` occasion is meant to run on for the character
    (``routing.intended_backend``, configuration only — no availability probe, no rotation turn); ``routed`` False
    and ``backend`` None when there is none (no txt2hair backend entry, or a chain whose every entry is skipped)."""
    from app.imagegen import routing, service
    try:
        backend = routing.intended_backend("hair_strands", character_name,
                                           pool=getattr(service.get_image_service(), "pool", None))
    except Exception:  # noqa: BLE001 — a label of the tab, never a failure of the GET
        logger.exception("hair_strands route of %s unresolvable", character_name)
        backend = None
    name = getattr(backend, "name", None) if backend is not None else None
    return {"routed": bool(name), "backend": name or None}


def _haar_in_use(character_name: str, item_id: str, ssig: str) -> Optional[int]:
    """The seed of the HAAR fit the hair preview shows (``preview_path``), when it was made from ``ssig``."""
    from app.core import garment_store as gs
    path = preview_path(character_name, item_id)
    if path is None:
        return None
    record = gs.read_record(path.with_suffix(".json"))
    inputs = record.get("inputs") or {}
    if gs.fit_method(record) != gs.HAAR or inputs.get("ssig") != ssig:
        return None
    try:
        return int(inputs.get("seed"))
    except (TypeError, ValueError):
        return None


def haar_tile_path(character_name: str, item_id: str, seed: int) -> Optional[Path]:
    """The tile of HAAR seed ``seed`` under the hairstyle's CURRENT ``ssig``; None when it is not there. ValueError
    for an item that is no hair of the character."""
    from app.core import garment_hair, garment_store as gs
    _item_, kind = _item(character_name, item_id)
    if kind != garment_hair.HAIR_KIND:
        raise ValueError(f"{item_id[:80]!r} is no hair")
    path = gs.haar_seed_dir(gs.haar_dir(character_name, item_id, gs.garment_ssig(character_name, item_id)),
                            int(seed)) / HAAR_TILE
    return path if path.is_file() else None


def _piece_view_due(view: str, source: str, made: Optional[str]) -> List[Dict[str, Any]]:
    """What becomes due when the accepted piece-only ``view`` (made from ``made``) is to come from ``source``
    (Ruling A46): nothing when they agree; else the view again (0 jobs from the worn view, 1 rendered), its
    cut-out (its routed upscale), the mesh and the fit (CPU) — first attempts, ``HUB_JOBS``."""
    if made is None or made == source:
        return []
    costs = HUB_JOBS["clothing:edit_chain"]
    ghost = 0 if source == "worn" else (BACK_JOBS["ghost"] if view == "back" else costs["ghost"] - BACK_JOBS["ghost"])
    return [{"step": "ghost", "view": view, "jobs": ghost},
            {"step": "cutout", "view": view, "jobs": costs["cutout"] // 2},
            {"step": "mesh", "jobs": costs["mesh"]}, {"step": "fit", "jobs": costs["fit"]}]


def fit_settings_info(character_name: str, item_id: str, fsig: str, base_model_sha: str,
                      profile: Dict[str, Any]) -> Dict[str, Any]:
    """Ruling A47 — the fit settings of a clothing piece for the Wardrobe dialog: ``{settings (current), recorded
    (those of the shown fit, None without one), due (a fit exists and was made with other settings: the next run
    refits on the CPU, no hub job), sleeves {left, right: {setting, applied, reason, why, numbers}}, allowance
    {setting, factor, trigger, numbers, attempts, inherited}, arm_light {state, sides, worst_cm2}, numbers
    {deep_push_share, torso_tight_share, sleeve_shards, sleeve_skin_left_cm2, sleeve_skin_right_cm2, scale},
    accepted (the shown fit passed its gates), built_at}``. The shown fit: the current fingerprint's fit on the
    base model, else its newest refused attempt (``fit_attempts``)."""
    from app.core import fit_attempts, garment_fit, garment_fit_settings, garment_store as gs
    current = garment_fit_settings.fit_settings(profile, item_id)
    record: Dict[str, Any] = {}
    accepted = False
    if fsig:
        record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
        accepted = record.get("accepted") is True
    if not record:
        found = fit_attempts.attempt_of(character_name, item_id, "")
        if found and found[1].get("fsig") == fsig:
            record = found[1]
    report = record.get("report") or {}
    metrics = record.get("metrics") or {}
    retry = report.get("scale_retry") or {}
    numbers = {k: metrics.get(k) for k in ("deep_push_share", "torso_tight_share", "sleeve_shards",
                                            "sleeve_skin_left_cm2", "sleeve_skin_right_cm2")}
    numbers["scale"] = metrics.get("scale_retry")
    made_with = garment_fit_settings.recorded(record) if record else None
    return {
        "settings": current, "recorded": made_with,
        "due": bool(record) and made_with != current,
        "sleeves": (report.get("transfer") or {}).get("sleeves") or {},
        "allowance": retry.get("allowance"),
        "arm_light": report.get("arm_light"),
        "numbers": numbers, "accepted": accepted,
        "built_at": record.get("created_at") or ((record.get("attempt") or {}).get("at") if record else None),
        "choices": {"sleeves": list(garment_fit.SLEEVE_CHOICES), "allowance": list(garment_fit.ALLOWANCE_CHOICES)},
        "limits": {"red_cm2": garment_fit.SKIN_RED_CM2, "deep": garment_fit.ALLOWANCE_DEEP,
                   "tight": garment_fit.ALLOWANCE_TIGHT, "tight_m": garment_fit.TORSO_TIGHT_M,
                   "max_factor": max(garment_fit.SCALE_RETRY_STEPS)},
    }


def piece_views_info(character_name: str, item_id: str, fsig: str,
                     item: Optional[Dict[str, Any]] = None, *,
                     checking: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """Ruling A46, the Wardrobe's "Piece-only views from" per view: ``{view: {choice, source, reason, auto,
    made_from, due, options}}`` — ``choice`` the setting (auto / generated / worn), ``source`` what the view
    is made from now and ``why`` / ``detail`` / ``reason`` why (``garment_from_worn.resolve``), ``made_from`` the
    source of the accepted piece-only image (None without one), ``due`` what is due because they differ
    (``_piece_view_due``: ``[{step, view?, jobs}]``), ``options`` the same for every choice
    (``{choice: {source, why, detail, reason, due}}`` — what a change would make due, before it is saved); ``skipped`` for
    a view that is not made (an empty drafted back); ``checking`` True while its accepted image is re-gated under
    the current gate version (Ruling A46b, ``regate_shown`` — asked here unless the caller passes ``checking``):
    the source shown is the stored verdict's until then. None for a kind without the choice. Read from the
    files and the item only."""
    from app.core import garment_from_worn as fw
    from app.core import garment_images
    from app.core.garment_store import GARMENT_VIEWS, read_record
    from app.models.inventory import get_item
    if getattr(_kind_module(garment_images._item_kind(item_id)), "FROM_WORN_STEP", None) != fw.STEP:
        return None
    item = item if item is not None else (get_item(item_id) or {})
    if checking is None:
        checking = regate_shown(character_name, item_id, garment_images._item_kind(item_id), fsig)
    checked = {c["view"] for c in checking if c.get("step") == fw.STEP}
    out: Dict[str, Dict[str, Any]] = {}
    for view in GARMENT_VIEWS:
        skipped = garment_images.skipped_view(character_name, item_id, fsig, fw.STEP, view)
        if skipped:
            out[view] = {"choice": fw.choice_of(item, view), "skipped": skipped}
            continue
        final = _image(character_name, item_id, fsig, fw.STEP, view)
        made = fw.made_from(read_record(final.with_suffix(".json"))) if _accepted(final) else None
        options: Dict[str, Dict[str, Any]] = {}
        for choice in fw.CHOICES:
            piece = dict(item.get("outfit_piece") or {})
            setting = fw.clean_setting(piece.get(fw.SETTING_KEY))
            setting.pop(view, None)
            if choice != fw.AUTO:
                setting[view] = choice
            piece[fw.SETTING_KEY] = setting
            r = fw.resolve(character_name, item_id, fsig, view, item={**item, "outfit_piece": piece})
            options[choice] = {"source": r["source"], "why": r["why"], "detail": r["detail"],
                               "reason": r["reason"], "due": _piece_view_due(view, r["source"], made)}
        now = fw.resolve(character_name, item_id, fsig, view, item=item)
        out[view] = {**now, "made_from": made, "due": _piece_view_due(view, now["source"], made),
                     "options": options, "checking": view in checked}
    return out


def garment_info(character_name: str, item_id: str) -> Dict[str, Any]:
    """UI info of one garment (the hair row, the own-mesh dialog): fsig, the method and its
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
    the placement correction). HAAR hair adds ``ssig`` and the stale reasons ``haar_changed`` (another
    text or HAAR setting), ``seed_changed`` (another served seed: a pick or a better seed) and
    ``colour_changed``.
    ``failed`` also reports the persisted failure of the current fsig after
    a restart (automatic triggers skip it until an explicit run).
    ``queue_position`` / ``queue_running`` (``queue_state``): the 1-based
    place of the item's next waiting run in the character's garment queue
    (None = none waits) and the item id in flight (None = idle) — the UI's
    "Queued behind <item>" while ``running_step`` is ``queued``;
    ``queue_beside`` True for a refit running beside the FIFO (Ruling A30):
    it waits behind nothing.
    ``refit`` (``garment_source``): the current fit was refitted from a source
    made on an older base — ``{source_bsig, source_fsig, materialized_from,
    registration {shift, scale} | None, first_step, created_at}`` (the tab
    shows "Refitted from the previous base" + Re-render = an explicit run of
    ``first_step``), None otherwise.
    ``pair`` (an edit chain whose pair step has both views accepted, Ruling
    A33): ``{step, agree, redo, error}`` — ``redo`` the view a disagreeing
    pair renders again (``_pair_redo``); None otherwise.
    ``body`` (mesh mode, plan 2026-11-10-outfit-body-mesh-mode Task 2): the
    piece's fit on the outfit body the CURRENT outfit model stands on
    (``body_fit_info``; ``body_id`` repeats its id), None on the base body —
    ``steps.fit`` stays the chain's fit on the base model.
    Footwear has its own panel (``garment_footwear.info``: the per-item
    source steps, the insole, the fit of the current fsig on the base model
    and the width cap).
    ValueError for an invalid item."""
    from app.core import base_body, garment_hair, hair_motion, garment_store as gs
    from app.core.hair_strands import preview_version
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_profile
    _item_, kind = _item(character_name, item_id)
    profile = get_character_profile(character_name) or {}
    if kind == _footwear():
        from app.core import garment_footwear
        return gs.finite_json(garment_footwear.info(character_name, item_id, profile=profile))
    inputs = _kind_inputs(kind, character_name, profile, item_id)
    method, method_source = ((garment_hair.hairstyle_mode(_item_), "hairstyle")
                             if kind == garment_hair.HAIR_KIND else (gs.EDIT_CHAIN, "world"))
    try:
        fsig: Optional[str] = gs.garment_fsig(character_name, item_id, profile=profile)
    except ValueError:
        fsig = None
    hsig = gs.garment_hsig(character_name, item_id, profile=profile) if fsig and method == gs.HAIRDECK else None
    ssig = gs.garment_ssig(character_name, item_id, profile=profile) if fsig and method == gs.HAAR else None
    base = base_body.current_base(character_name, profile=profile) or ("", "")
    # Ruling A46b: accepted images gated under an older version are re-gated in the background (once).
    checking = regate_shown(character_name, item_id, kind, fsig) if fsig and method == gs.EDIT_CHAIN else []
    steps: Dict[str, Any] = {}
    if fsig:
        for step in gs.steps_for(kind, method):
            if step in gs.IMAGE_STEPS:
                steps[step] = {v: _image_info(character_name, item_id, fsig, step, v) for v in gs.GARMENT_VIEWS}
            elif step == "mesh":
                steps[step] = _mesh_info(character_name, item_id, fsig)
            elif step == "hairdeck":
                steps[step] = _hairdeck_info(character_name, item_id, hsig or "")
            elif step == "haar":
                steps[step] = _haar_info(character_name, item_id, ssig or "")
            elif step == "fit":
                steps[step] = _fit_info(character_name, item_id, fsig, base[1], method)
    pair = None
    if fsig and method == gs.EDIT_CHAIN and _kind_module(kind).PAIR_STEP in steps:
        # Ruling A33: a view run never repairs a disagreeing pair (that renders the other view) — say which one.
        agree, pair_gates = _pair(character_name, item_id, kind, fsig)
        if pair_gates.get("front") and pair_gates.get("back"):
            pair = {"step": _kind_module(kind).PAIR_STEP, "agree": agree,
                    "redo": None if agree else _pair_redo(kind, pair_gates),
                    "error": None if agree else _kind_module(kind).PAIR_REFUSED}
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
            from app.core.garment_fit import expected_fit_version
            if record.get("fit_version") != expected_fit_version(record):
                stale.append("fit_algorithm_updated")
            if _settings_changed(character_name, item_id, record, profile):
                stale.append("fit_settings_changed")
            if method == gs.HAIRDECK and gs.fit_method(record) == gs.HAIRDECK:
                if used.get("hsig") != hsig:
                    stale.append("hairdeck_changed")
                settings = garment_hair.hairstyle_settings(_item_)
                if (used.get("colour") or "") != garment_hair.hair_colour_override(settings):
                    stale.append("colour_changed")
                if used.get("placement") != garment_hair.hair_placement(settings):
                    stale.append("placement_changed")
                if bool(used.get("swing")) != hair_motion.swing_on(settings):
                    stale.append("swing_changed")
            if method == gs.HAAR and gs.fit_method(record) == gs.HAAR:
                if used.get("ssig") != ssig:
                    stale.append("haar_changed")
                elif used.get("seed") != gs.haar_served_seed(character_name, item_id, ssig or "", item=_item_):
                    stale.append("seed_changed")
                if (used.get("colour") or "") != garment_hair.hair_colour_override(
                        garment_hair.hairstyle_settings(_item_)):
                    stale.append("colour_changed")
    preview = preview_path(character_name, item_id)
    preview_url = None
    if preview is not None:
        try:
            preview_url = _url(character_name, item_id, "model", preview_version(preview))
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
                     "first_step": next(iter(gs.steps_for(kind, method)), None),
                     "created_at": fit_record.get("created_at")}
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
    from app.core import model_overview
    # finite_json: a NaN in an in-memory failure's gates must not fail the whole tab's JSON encoding
    return gs.finite_json({
        "item_id": item_id, "kind": kind, "fsig": fsig, "method": method, "method_source": method_source,
        "hsig": hsig, "ssig": ssig, "description": inputs.get("description") or inputs.get("prompt_fragment") or "",
        "steps": steps, "stale_reasons": stale, "pair": pair,
        "running_step": status["running_step"], "started_at": status["started_at"],
        "queue_position": queue["queue_position"], "queue_running": queue["queue_running"],
        "queue_beside": queue["queue_beside"],
        "failed": failed, "preview_url": preview_url,
        # Ruling UI3 a: when the previewed fit was made (the 3D preview's caption).
        "preview_built_at": model_overview.built_at(preview) if preview_url else None,
        "served_fsig": served_fsig, "refit": refit,
        # Ruling A46: where each piece-only view comes from (the setting, the reason, what is due).
        "piece_views": (piece_views_info(character_name, item_id, fsig, _item_, checking=checking)
                        if fsig and method == gs.EDIT_CHAIN and kind == _clothing() else None),
        # Ruling A47: sleeves per side, the width allowance, the arm light of the shown fit.
        "fit_settings": (fit_settings_info(character_name, item_id, fsig, base[1], profile)
                         if fsig and method == gs.EDIT_CHAIN and kind == _clothing() else None),
        # Ruling A46b: the accepted images being re-gated under the current gate version now ([{step, view}]).
        "regate_checking": checking,
        "body": body, "body_id": body["body_id"] if body else None})

def hair_summary(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """``{item_id, status}`` of the worn hair item for ``base_body.base_info``
    — status ``running`` / ``failed`` / ``ready`` (current fit accepted on
    the current base model) / ``stale`` (an older fit is served) /
    ``missing``; None without a worn hairstyle, off the pipeline, or for a
    worn hairstyle in the body mesh (HairDeck and HAAR hair have a mesh)."""
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
    from app.core.garment_hair import HAAR_MODE, HAIRDECK_MODE, hairstyle_mode
    try:
        worn_item, _kind = _item(character_name, item_id)
    except ValueError:
        return None
    if hairstyle_mode(worn_item) not in (HAIRDECK_MODE, HAAR_MODE):
        return None  # in the body mesh: no hair mesh is wanted or served
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
