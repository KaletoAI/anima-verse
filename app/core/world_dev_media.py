"""The media lane of a World Dev free-mode run (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md).

Task 2 — no automatic render during a turn. A character a run's write step
touches is DEFERRED from ``world_dev_tools._Step.begin`` / ``attach`` until the
turn ends: every automatic trigger the tool writers can reach returns without
arming or starting anything while the character is deferred, and records the call
it swallowed — both in ONE step, ``suppress_if_deferred`` (one entry per
(name, trigger), the latest arguments win), so a release between the check and
the record cannot lose the call. Those renders would otherwise land outside the run's
bookkeeping, so a Discard could not remove them.

The guarded triggers (``git grep -n "schedule_outfit_render(\|figure_build.request(\|
garment_assembly.schedule(\|submit_assets_job(\|trigger_generation(\|
generate_from_input(" -- app/core app/models``, followed through the writers the
tools call):

- ``model_refs.schedule_outfit_render`` — reached from
  ``inventory.apply_equipped_pieces`` (create_character's starting outfit,
  update_character's outfits/wear) and ``expression_regen``; it arms the
  reference-kind timers and, on the base-body pipeline, the Build timer.
- ``model_refs._fire_kind`` — the body of a timer armed BEFORE the run touched
  the character; while deferred it fires nothing and is recorded as
  ``model_refs._fire_kind:<kind>`` (the replay re-arms only that kind's timer,
  ``model_refs.rearm_timer``). The off-pipeline
  auto mesh (``model3d.maybe_auto_generate_for_outfit`` →
  ``model3d.trigger_generation``) runs only after such a T-pose pass, so it is
  covered by this guard.
- ``figure_build.request`` — every automatic Build request: garment_hair
  (hairstyle claim / wear), garments (body change), base_body (piece ready,
  detail change), outfit_bodies, hairstyle_delete, model3d's auto-mesh hook,
  the Build timer and generation_pause's Resume. ``figure_build.start`` (a
  click) stays unguarded.
- ``garment_assembly.schedule`` — recorded with ``signature=None`` (a later
  write of the turn may have changed the outfit; the replay re-resolves the
  serving model) — CPU fits of worn pieces (garments,
  garment_hair, garment_footwear, garment_cut_texture, fit_attempts,
  inventory, model3d, figure_build); its output lands in the character's
  media roots.

Not guarded, on purpose: ``npc_assets.submit_assets_job`` /
``on_outfit_description_changed`` / ``gate_placement`` act on temporary NPCs
only, which every World Dev tool refuses; ``generate_from_input``
(expression_regen, messaging_frame) and ``character_ops``'s
``model3d.trigger_generation`` are reached from chat/route paths, never from a
tool writer; ``location_model3d`` / ``props`` / ``surface_textures``
``trigger_generation`` are location/prop renders that no tool writer starts.

Interim (Fable review finding 9): until Task 9 lands, ``release_turn`` and
``release_all`` REPLAY the recorded suppressed calls for every released name
whose character still exists (the ordinary automatic path, so "Build
automatically" and the per-character pause still decide), so a free-mode
character never silently loses a Build or an outfit render. Known gap of the
interim: a replay at a turn end starts renders while the run is still
``awaiting_review``, outside its bookkeeping, so a later Discard cannot
remove them — Task 9 removes the replay from ``release_turn`` (keeping it
only for a discard); Tasks 2–9 land together.

State is in memory, guarded by one ``threading.Lock``: a restart ends every
turn anyway (``world_dev_agent.mark_interrupted_on_boot``).

Task 4 — element steps, fingerprints, baselines, the plan. Which media an
element needs is decided by FINGERPRINTS of the real render inputs, never by a
hand-kept list of "look keys": ``element_steps(kind, id)`` lists the steps of a
location or character with the sha256 / text of what each producer would read.
Every write step of a tool whose journal target kind is ``location`` or
``character`` calls ``note_touch`` from ``_Step.begin`` (when it has an id,
BEFORE the write) and from ``_Step.attach``; the first touch per (run, kind,
id) stores the element's BASELINE ``{step_id: fp}``. Creation is recognised by
the journal inverse (``CREATE_INVERSE_OPS``), never by whether the element
exists at that moment — the create paths (``git grep -n '"op": "delete_location"\|
"op": "delete_character"' app/core/world_dev_tools.py``):

- ``create_location`` — ``step.begin("location")`` WITHOUT an id, then
  ``step.attach(lid, {"op": "delete_location", ...})`` after
  ``create_location_with_extras`` has written the place (and the same inverse
  from the ``writing()`` reconcile after a failed write);
- ``create_character`` — ``step.begin("character", name, {"op":
  "delete_character", ...})`` before the write, then ``attach`` with the
  claimed inverse (same op, ``claimed: True``). Only the CLAIMED inverse
  marks the character created: the unclaimed one of the begin is no touch at
  all, because a same-name character someone else creates in the race window
  after the tool's re-check is never claimed — a NULL baseline there would
  plan every render of a character the run does not own.

A create-inverse sets the baseline to NULL (``wr.mark_created``, overriding an
earlier one): every step of a created element is due. ``plan(run_id)`` is pure
(no writes) and lists, for a run in review, the due steps per element.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
#: character name -> run id that deferred it (the last run that touched it).
_deferred: Dict[str, str] = {}
#: character name -> {trigger: (args, kwargs)} of the calls the guards swallowed
#: (insertion order = the order of the first suppressed call per trigger).
_suppressed: Dict[str, Dict[str, Tuple[tuple, dict]]] = {}


def defer(name: str, run_id: str) -> None:
    """Defer the automatic renders of ``name`` until ``run_id``'s turn ends."""
    if not name or not run_id:
        return
    with _lock:
        _deferred[str(name)] = str(run_id)


def is_deferred(name: str) -> bool:
    """Whether a World Dev run currently defers ``name``'s automatic renders."""
    with _lock:
        return str(name) in _deferred


def suppress_if_deferred(name: str, trigger: str, args: tuple = (),
                         kwargs: Dict[str, Any] | None = None) -> bool:
    """The guard of every automatic trigger: when a World Dev turn defers
    ``name``, record the call (deduplicated per (name, trigger), the latest
    arguments win) and return True — the caller then returns without doing
    anything. False = not deferred, the caller proceeds. The check and the
    record happen under ONE lock acquisition: a release in between would
    otherwise drop the record while the guard still swallowed the call.
    ``args`` / ``kwargs`` are the call's arguments after the character name."""
    with _lock:
        if str(name) not in _deferred:
            return False
        _suppressed.setdefault(str(name), {})[trigger] = (tuple(args), dict(kwargs or {}))
        return True


def suppressed_triggers(name: str) -> List[str]:
    """The triggers recorded for ``name`` (for checks and diagnostics)."""
    with _lock:
        return list(_suppressed.get(str(name), {}))


def _take(run_id: str) -> List[Tuple[str, Dict[str, Tuple[tuple, dict]]]]:
    with _lock:
        names = [n for n, r in _deferred.items() if r == str(run_id)]
        out = []
        for n in names:
            _deferred.pop(n, None)
            out.append((n, _suppressed.pop(n, {})))
        return out


def _replay_call(trigger: str) -> Callable[..., Any] | None:
    if trigger.startswith("model_refs._fire_kind:"):
        kind = trigger.split(":", 1)[1]
        from app.core import model_refs
        return lambda name: model_refs.rearm_timer(name, kind)
    if trigger == "model_refs.schedule_outfit_render":
        from app.core import model_refs
        return model_refs.schedule_outfit_render
    if trigger == "figure_build.request":
        from app.core import figure_build
        return figure_build.request
    if trigger == "garment_assembly.schedule":
        from app.core import garment_assembly
        return garment_assembly.schedule
    return None


def _replay(released: List[Tuple[str, Dict[str, Tuple[tuple, dict]]]]) -> None:
    """Re-issue the suppressed calls of each released character that still
    exists (interim, see the module docstring). Never raises."""
    for name, calls in released:
        if not calls:
            continue
        try:
            from app.models.character import character_row_exists
            if not character_row_exists(name):
                continue
        except Exception:  # noqa: BLE001 — an unreadable row: nothing is replayed
            logger.warning("World Dev media: %s not replayed (row check failed)", name,
                           exc_info=True)
            continue
        for trigger, (args, kwargs) in calls.items():
            fn = _replay_call(trigger)
            if fn is None:
                continue
            try:
                fn(name, *args, **kwargs)
            except Exception:  # noqa: BLE001 — one trigger never blocks the others
                logger.exception("World Dev media: replay of %s for %s failed", trigger, name)


def release_turn(run_id: str) -> List[str]:
    """End of a turn: drop ``run_id``'s deferrals and replay what they
    suppressed. Returns the released names (in deferral order)."""
    released = _take(run_id)
    _replay(released)
    return [n for n, _ in released]


def release_all(run_id: str) -> List[str]:
    """The run closes: drop all of its deferrals (with the same replay)."""
    released = _take(run_id)
    _replay(released)
    return [n for n, _ in released]


# ── Task 4: element steps, fingerprints, baselines, the plan ────────────

#: Journal inverse ops of the steps that CREATE a location / character
#: (module docstring): a touch carrying one marks the element as created by
#: the run (baseline NULL), whatever exists at that moment.
CREATE_INVERSE_OPS = frozenset({"delete_location", "delete_character"})
#: Journal target kinds whose elements get media.
MEDIA_KINDS = ("location", "character")
#: Run statuses in which ``plan`` (and the scheduling built on it) acts —
#: never during a running turn (M15).
PLAN_STATUSES = ("awaiting_review", "interrupted")
#: Row statuses whose steps "hold" a fingerprint (an equal step is not due).
HOLDING_ROW_STATUSES = ("queued", "running", "done")


@dataclass
class StepSpec:
    """One media step of an element: its id (unique per element), a label for
    the panel, the render occasions it routes (empty for the build / mesh /
    hairstyle steps — their gate derives them at gate time, Task 5), the
    fingerprint of its render inputs, and the producer key (``PRODUCERS``)."""
    id: str
    label: str
    occasions: Tuple[str, ...]
    fp: str
    producer: str


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _gallery_fp(loc: Dict[str, Any], room_id: str, prompt_type: str) -> str:
    """sha256 of what a gallery render of (room, type) reads: the composed
    subject and the use case (the same readers the gallery core calls)."""
    from app.core.world_ops import gallery_use_case, resolve_gallery_subject
    return _sha([prompt_type, room_id, resolve_gallery_subject(loc, room_id, prompt_type),
                 gallery_use_case(loc, room_id, prompt_type)])


def _image_rooms(loc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The rooms that get day/night images: every stored room except the
    ground and the corridors the server brings along (ImageSetDialog's set).

    The ``is_ground`` / ``is_floor`` flags exist only in the payloads the
    server builds for clients (scene recipe, location views); the STORED room
    dicts read here carry no such flag. On the server the reserved ids are the
    source of truth those flags are derived from, so this uses the same test
    as the world writers (``app.models.world``: ``GROUND_ROOM_ID`` and
    ``is_floor_room``)."""
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    out = []
    for room in loc.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        rid = str(room.get("id") or "")
        if rid and rid != GROUND_ROOM_ID and not is_floor_room(rid):
            out.append(room)
    return out


def _location_steps(loc: Dict[str, Any]) -> List[StepSpec]:
    front_fp = _gallery_fp(loc, "", "building-front")
    steps = [StepSpec("building-front", "building front", ("location",), front_fp, "gallery")]
    for room_id, label in [("", "")] + [(str(r["id"]), str(r.get("name") or r["id"]))
                                       for r in _image_rooms(loc)]:
        for kind in ("day", "night"):
            steps.append(StepSpec(f"{kind}:{room_id}",
                                  f"{kind} image" + (f" — {label}" if label else ""),
                                  ("location",), _gallery_fp(loc, room_id, kind), "gallery"))
    # The automatic mesh path meshes from the building front alone (M4).
    steps.append(StepSpec("mesh", "3D model", ("mesh_building",), front_fp, "location_mesh"))
    return steps


def _hairstyle_fp(name: str, profile: Dict[str, Any]) -> str:
    """The hair text a first hairstyle would start from — "" when the step does
    not apply (``ensure_hairstyle``'s own conditions: a hair slot, no
    hairstyle worn or owned, hair text present)."""
    from app.core import garment_hair
    from app.core.body_slots import mesh_item_slots
    if mesh_item_slots(name, profile=profile).get(garment_hair.HAIR_KIND) is None:
        return ""
    if garment_hair.worn_hair_id(name, profile) or garment_hair.hairstyles(name):
        return ""
    return garment_hair.appearance_hair_text(name, profile=profile)


def _figure_fp(name: str, profile: Dict[str, Any]) -> str:
    from app.core import figure
    wanted = figure.wanted_figure(name, profile=profile)
    return _sha(dataclasses.asdict(wanted) if dataclasses.is_dataclass(wanted) else wanted)


def _character_steps(name: str, profile: Dict[str, Any]) -> List[StepSpec]:
    from app.core import figure_build
    from app.core.character_ops import resolve_face_prompt
    from app.core.model_refs import current_outfit_state, is_humanoid
    from app.models.character_template import get_template
    steps: List[StepSpec] = []
    pipeline = bool(figure_build.on_pipeline(name, profile=profile))
    if pipeline and is_humanoid(name, profile=profile):
        hair = _hairstyle_fp(name, profile)
        if hair:
            steps.append(StepSpec("hairstyle", "hairstyle", (), hair, "hairstyle"))
    template = str(profile.get("template") or "")
    face = resolve_face_prompt(profile, name, get_template(template) if template else None)
    steps.append(StepSpec("portrait", "portrait", ("profile",), face, "portrait"))
    if pipeline:
        steps.append(StepSpec("build", "Figure Build", (), _figure_fp(name, profile), "build"))
    else:
        steps.append(StepSpec("mesh", "T-pose + 3D model", (),
                              str(current_outfit_state(name)[2]), "mesh"))
    return steps


def element_steps(kind: str, target_id: str) -> Optional[List[StepSpec]]:
    """The media steps of an element in run order, None when it does not
    exist (or is no media kind). Read-only; raises what the readers raise."""
    if kind == "location":
        from app.models.world import get_location_by_id
        loc = get_location_by_id(str(target_id))
        return _location_steps(loc) if loc else None
    if kind == "character":
        from app.models.character import (character_row_exists, get_character_profile,
                                          no_config_auto_create)
        if not character_row_exists(str(target_id)):
            return None
        # A pure read: the config reader would otherwise save the defaults of
        # a character without a stored config — a write outside the journal
        # (the baseline is read before the tool's own write).
        with no_config_auto_create():
            return _character_steps(str(target_id), get_character_profile(str(target_id)) or {})
    return None


def note_touch(run_id: str, kind: str, target_id: Optional[str],
               inverse: Optional[dict]) -> None:
    """Record the element's baseline at the run's first touch (before the
    write). A create-inverse marks it created (baseline NULL, overriding an
    earlier one, M13); an UNCLAIMED ``delete_character`` (the begin of
    create_character, before apply_character has claimed the name) records
    nothing — only the claimed attach does. Never raises: a fingerprint error stores ``{}`` (every
    step due) — it must never refuse a tool."""
    if kind not in MEDIA_KINDS or not target_id or not run_id:
        return
    from app.core import world_dev_runs as wr
    ident = str(target_id)
    if (isinstance(inverse, dict) and inverse.get("op") == "delete_character"
            and not inverse.get("claimed")):
        return
    try:
        if isinstance(inverse, dict) and inverse.get("op") in CREATE_INVERSE_OPS:
            wr.mark_created(run_id, kind, ident)
            return
        if (kind, ident) in wr.baselines(run_id):
            return
        steps = element_steps(kind, ident)
        if steps is None:
            logger.warning("World Dev media: %s %s touched by run %s does not exist and the "
                           "step is no create — baseline 'created'", kind, ident, run_id)
            wr.note_baseline(run_id, kind, ident, None)
            return
        wr.note_baseline(run_id, kind, ident, {s.id: s.fp for s in steps})
    except Exception:  # noqa: BLE001 — a fingerprint error never refuses a tool
        logger.exception("World Dev media: baseline of %s %s (run %s) failed — every step "
                         "counts as due", kind, ident, run_id)
        try:
            wr.note_baseline(run_id, kind, ident, {})
        except Exception:  # noqa: BLE001
            logger.exception("World Dev media: baseline {} of %s %s not stored", kind, ident)


#: Journal inverse ops of the steps that CREATE a catalog item (nobody wears it yet).
ITEM_CREATE_INVERSE_OPS = frozenset({"delete_items"})


def item_wearers(item_id: str) -> List[str]:
    """Every stored character (dormant and pooled ones included) that wears
    the catalog item: an equipped piece (``equipped_pieces``) or a worn mesh
    piece such as the hairstyle (``equipped_mesh_pieces``). Sorted by name;
    an unreadable profile is skipped with a warning."""
    from app.models.character import get_character_profile, list_available_characters
    ident = str(item_id)
    out: List[str] = []
    for name in list_available_characters(include_pooled=True, include_dormant=True):
        try:
            profile = get_character_profile(name) or {}
        except Exception:  # noqa: BLE001 — one unreadable profile never hides the rest
            logger.warning("World Dev media: profile of %s unreadable for the wearers of %s",
                           name, ident, exc_info=True)
            continue
        worn = set()
        for key in ("equipped_pieces", "equipped_mesh_pieces"):
            slots = profile.get(key)
            if isinstance(slots, dict):
                worn.update(str(v) for v in slots.values() if v)
        if ident in worn:
            out.append(name)
    return sorted(out, key=str.lower)


def note_item_touch(run_id: str, item_id: Optional[str], inverse: Optional[dict]) -> None:
    """A run step writes a shared catalog item (an outfit piece, a
    hairstyle): its render inputs are part of every wearer's build/mesh
    fingerprint, so each wearer is touched like a written character — its
    baseline taken now, before the write (``note_touch`` with no inverse:
    the wearer exists and is not created by this step). A create-inverse
    item is new and has no wearer. Never raises."""
    if not run_id or not item_id:
        return
    if isinstance(inverse, dict) and inverse.get("op") in ITEM_CREATE_INVERSE_OPS:
        return
    try:
        names = item_wearers(str(item_id))
    except Exception:  # noqa: BLE001 — a fingerprint error never refuses a tool
        logger.exception("World Dev media: wearers of item %s (run %s) not read — they get "
                         "no baseline from this step", item_id, run_id)
        return
    for name in names:
        note_touch(run_id, "character", name, None)


def _held(run_id: str, kind: str, target_id: str) -> set:
    """{(step id, fp)} held by the run's queued/running/done rows of the element."""
    from app.core import world_dev_runs as wr
    out = set()
    for row in wr.media_rows(run_id, kind=kind, target_id=target_id,
                             statuses=HOLDING_ROW_STATUSES):
        for step in row.get("steps") or []:
            if isinstance(step, dict) and step.get("id"):
                out.add((str(step["id"]), str(step.get("fp") or "")))
    return out


def plan(run_id: str) -> List[Tuple[str, str, List[StepSpec]]]:
    """The due steps per touched element (pure, no writes): [(kind, id,
    steps)] for every element with at least one due step, in first-touch
    order. A step is due when the element exists, its fingerprint differs from
    the baseline (always for a created element, NULL baseline) and no
    queued/running/done row of the run holds that step with that fp. [] when
    the run's media switch is off or the run is not in review (M15). An
    element whose steps cannot be read is logged and left out."""
    from app.core import world_dev_runs as wr
    run = wr.get_run(run_id)
    if not run or run.get("status") not in PLAN_STATUSES or not run.get("media_enabled"):
        return []
    out: List[Tuple[str, str, List[StepSpec]]] = []
    for (kind, ident), base in wr.baselines(run_id).items():
        try:
            steps = element_steps(kind, ident)
        except Exception:  # noqa: BLE001 — one element never blocks the others
            logger.exception("World Dev media: steps of %s %s not readable", kind, ident)
            continue
        if not steps:
            continue
        held = _held(run_id, kind, ident)
        due = [s for s in steps
               if (base is None or base.get(s.id) != s.fp) and (s.id, s.fp) not in held]
        if due:
            out.append((kind, ident, due))
    return out
