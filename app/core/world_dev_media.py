r"""The media lane of a World Dev free-mode run (plan
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

Release (Task 9): ``release_turn`` (every turn end) drops the turn's
deferrals and what they suppressed WITHOUT a replay — the turn-end
``schedule`` renders the run's elements instead, inside its bookkeeping.
``release_all(run, replay=...)`` closes the run: a Discard / terminal
rollback defers the run's characters again before its journal undo
(``defer_run``) and replays afterwards what the undo suppressed, for the
characters that still exist (the ordinary automatic path, so "Build
automatically" and the per-character pause still decide); an Accept releases
without a replay.

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

Task 5 — the cost gate. Before every step the lane asks ``step_gate``: the
run's media switch, the media master switch, the character's pause of
automatic generation, "Build automatically" for a Build, then ``route_check``
for EVERY occasion the step routes — an empty chain or a chain without a
usable entry is a visible skip note, never the empty-chain cheapest (possibly
paid) pick. A Build's occasions are those of the character's OWN
``figure_build.plan`` steps (``BUILD_STEP_OCCASIONS``), so an occasion no step
of this Build routes never skips it; the off-pipeline mesh step checks only
the rig occasion of the character's own rig.

Task 7 — producers and exact capture/removal. ``PRODUCERS`` maps each
``StepSpec.producer`` to a thin adapter over the EXISTING entry point (gallery
core, ``subjects.generate_building_model``, ``npc_assets.render_profile_image`` /
``render_mesh``, ``figure_build.request`` + ``state``, ``make_hairstyle``). Every
artefact is recorded when it appears: gallery images and the portrait by name
(size + mtime_ns), the mesh / Build / off-pipeline mesh steps by a before/after
diff of the element's ``media_roots`` (created files and dirs, modified small
JSON sidecars with a backup of the pre-step bytes, other modified files
report-only), the portrait's ``profile_image`` as a before/after pair. A step
that fails still hands over what it wrote (``StepError.artefacts``).
``remove_artefacts`` / ``preview_artefacts`` share ONE decision (``_decide``):
removed only while unchanged since, a missing file or element is "already
gone"; ``sweep_orphan_dirs`` clears the dirs of a created element that is gone.

Task 9 — the run lifecycle (driven by ``world_dev_agent.RunManager``):
``cancel_queued`` at a follow-up turn's start, ``release_turn`` + ``schedule`` at
every turn end in review, ``close_run_media`` before a Discard's journal undo
and ``finish_closed_run`` after it, ``finish_accepted_run`` on Accept;
``sweep_backups`` drops a closed / accepted run's sidecar backups once no row
of it is queued or running (also from the lane after each row). A
cross-turn ``delete_created`` removes the element's media first
(``remove_element_media``, ``world_dev_tools._remove_earlier_media``).

Task 8 — the ONE global lane. ``schedule(run_id)`` (review only, media state
open, switch on) adds one ``queued`` row per element with due steps and
ensures the lane task (``TASK_TYPE``, payload ``{}``); ``run_lane`` works the
queued rows of ALL runs oldest first, one at a time. Every media-state
transition — the pick, the exit check, insert+ensure, cancel / remove — runs
under the global media lock. A task is submitted only when no lane is active
in this process and no lane task is PENDING: a RUNNING task does not count,
because its handler may already be past its exit check (the plain
``submit(deduplicate=True)`` would strand the row there); a duplicate lane
task returns at once while another one is active. Each step re-reads the
element's steps just before its producer and stores the then-current fp
(M14); a cancel / remove flag stops a running row after its current step.
``remove_run_media`` waits at most ``DISCARD_WAIT_S`` for a running row and
reports it under ``pending`` (the lane removes its output when the step
ends); ``reset_on_boot`` re-queues rows a restart left running.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
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
    """End of a turn: drop ``run_id``'s deferrals and what they suppressed —
    WITHOUT a replay (Task 9): the turn-end ``schedule`` renders the run's
    elements instead, inside the run's bookkeeping. Returns the released names
    (in deferral order)."""
    return [n for n, _ in _take(run_id)]


def release_all(run_id: str, *, replay: bool) -> List[str]:
    """The run closes: drop all of its deferrals. ``replay`` re-issues the
    suppressed calls of every released character that still exists — a
    Discard / terminal rollback (Task 9: the journal undo ran while the run's
    characters were deferred, ``defer_run``; its triggers bring a
    pre-existing character's renders back to the restored state through the
    ordinary automatic path). An Accept releases without a replay (nothing
    was suppressed since the last turn end; the lane renders the rest)."""
    released = _take(run_id)
    if replay:
        _replay(released)
    return [n for n, _ in released]


def run_characters(run_id: str) -> List[str]:
    """Every character a run's journal or media baselines touched (first
    seen first): the targets of its write rows of kind ``character`` — the
    lane's hairstyle rows included — and the characters with a baseline."""
    from app.core import world_dev_runs as wr
    names: List[str] = []
    for entry in reversed(wr.entries(run_id, include_undone=True)):
        name = str(entry.get("target_id") or "")
        if entry.get("target_kind") == "character" and name and name not in names:
            names.append(name)
    for (kind, ident) in wr.baselines(run_id):
        if kind == "character" and ident and ident not in names:
            names.append(str(ident))
    return names


def defer_run(run_id: str) -> List[str]:
    """Defer every character the run touched (``run_characters``) under the
    run — before a Discard's journal undo, so the automatic triggers the undo
    reaches are recorded instead of started outside any bookkeeping; the
    close then replays them (``release_all(replay=True)``). Returns the names."""
    names = run_characters(run_id)
    for name in names:
        defer(name, run_id)
    return names


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
    """{(step id, fp)} held by the element's rows of the run: every step of a
    queued/running/done row, and the DONE steps of a cancelled / failed /
    skipped row (Task 8: a row stopped after some steps — a turn start, a
    failure — keeps what it rendered; only what it left open is due again).
    A removed row holds nothing (its output is gone)."""
    from app.core import world_dev_runs as wr
    out = set()
    for row in wr.media_rows(run_id, kind=kind, target_id=target_id):
        if row.get("status") == "removed":
            continue
        whole = row.get("status") in HOLDING_ROW_STATUSES
        for step in row.get("steps") or []:
            if (isinstance(step, dict) and step.get("id")
                    and (whole or step.get("status") == "done")):
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


# ── Task 5: the cost gate ────────────────────────────────────────────────

#: ``route_check``'s notes (shown on the step in the panel).
ROUTE_NO_CHAIN = ("no routing chain for {occasion} — configure it in /admin/settings → Media "
                  "Generation → Routing")
ROUTE_NO_ENTRY = "no usable entry in the {occasion} chain"
ROUTE_UNREADABLE = "the routing of {occasion} could not be read ({error})"
#: ``step_gate``'s notes, in the order the gate checks them.
GATE_RUN_OFF = "media generation is off for this run"
GATE_RUN_UNREADABLE = "the run's media switch could not be read ({error})"
GATE_DISABLED = "media generation is disabled (image_generation.enabled)"
GATE_SWITCH_UNREADABLE = "the media master switch could not be read ({error})"
GATE_PAUSED = "automatic generation of {name} is paused — Retry media after Resume"
GATE_PAUSE_UNREADABLE = "the pause of automatic generation of {name} could not be read ({error})"
GATE_AUTO_BUILD_OFF = "Build automatically is off for {name}"
GATE_AUTO_BUILD_UNREADABLE = "the \"Build automatically\" switch of {name} could not be read ({error})"
GATE_BUILT = "the figure is already built"
#: A Build whose plan holds only steps the lane's Build mode does not run: a manual step
#: (``Step.manual``, e.g. the plain body of a character without one, ruling 8a) names its own reason.
GATE_MANUAL = "{name}: {reason} (Characters → Figure)"
GATE_ONLY_FAILED = ("{name}: only failed steps are left ({labels}) — a manual Build retries them "
                    "(Characters → Figure)")
GATE_PLAN_UNREADABLE = "the Build plan of {name} could not be read ({error})"

#: The Build mode of the media lane's ``build`` step: the producer (Task 7) asks for an AUTOMATIC
#: Build (``figure_build.request``), so the gate reads the plan of the same mode and keeps only the
#: steps that mode runs (``figure_build.planned_work``). Whoever switches the producer to a manual
#: Build switches it HERE (and the producer reads it), so the gate follows.
BUILD_EXPLICIT = False

#: The render occasions each Figure Build step can route (keyed by every
#: name of ``figure_build.STEP_ORDER``; a step that routes nothing maps to
#: ()). Derived from the step runners (``figure_build._RUNNERS``) and what
#: they reach — the base-body pipeline is humanoid only
#: (``base_body.is_base_pipeline``), so the mesh and rig occasions are the
#: humanoid ones and no step routes ``mesh_creature`` / ``rig_creature``:
#:
#: - plain_body — ``base_body.generate_base_images`` (``base_front``,
#:   ``base_view``), the skin step ``base_skin.SKIN_OCCASION`` (``outfit_front``),
#:   ``generate_base_model`` -> ``model3d`` mesh + rig (``mesh_occasion_for_rig
#:   ("mixamo")``, ``rig_humanoid``) and its face correction before the rig
#:   (``face_retexture``, the face view on ``tpose_view`` and the face
#:   reference's ``upscale`` — conditional).
#: - shape — ``base_body.prepare_shape``: the dressed front (``outfit_front``),
#:   per dressed view the turn (``TURN_OCCASION``) and the draft
#:   (``DRAFT_OCCASIONS``; the side draft only with the side views on —
#:   conditional), then mesh + rig + face like the plain body.
#: - pieces — the own-mesh garment chain (``garments.run_queued``):
#:   clothing ``garment_view`` + ``mesh_garment`` (``garment_images``,
#:   ``garment_mesh.mesh_occasion``) + the cut-out's ``upscale``, footwear
#:   ``footwear_empty`` + ``mesh_footwear`` (``footwear_source``) + ``upscale``;
#:   narrowed per piece (``piece_occasions``): to its kind
#:   (``garment_fill.OCCASIONS``, the improvements engine's same rule), a
#:   clothing piece in mode shell (made from the body on the CPU) to
#:   ``garment_view`` alone.
#: - cut_texture — ``garment_cut_texture.CUT_OCCASION``, the piece's back
#:   view (``garment_template_views``: ``garment_view``) and ``upscale``.
#: - pendant — ``accessory_pendant.MESH_OCCASION`` (``jewellery_mesh``); every
#:   real pendant / part step is manual (``figure_build.PART_MANUAL``), so an
#:   automatic Build never runs it.
#: - hair — the worn hairstyle's chain (``garments``), narrowed by its mode
#:   (``hair_occasions``): HairDeck ``hair_mesh`` (``ImageService.generate_hair``)
#:   plus the beard-free picture (``garment_beard``: ``garment_view``) only with
#:   facial hair; HAAR ``hair_strands`` (``ImageService.generate_strands``);
#:   mode body nothing (the hair is part of the body mesh).
#: - base_repair, tip_smoothing, template, accessory, views (A224: copies),
#:   fits, assemble (CPU retexture + garment assembly), collision — local.
#:
#: ``upscale`` has a catalog ``default_chain``, but an explicit ``"upscale": []``
#: in the routing empties it — and with ``requires_chain`` False the render would
#: take the empty-chain cheapest pick. So it is gated where a step uses it, but
#: only for an EMPTY chain (``SOFT_OCCASIONS``): an unusable entry fails that one
#: upscale alone (the callers fall back to Lanczos), never the whole Build.
BUILD_STEP_OCCASIONS: Dict[str, Tuple[str, ...]] = {
    "plain_body": ("base_front", "base_view", "outfit_front", "mesh_humanoid", "rig_humanoid",
                   "face_retexture", "tpose_view", "upscale"),
    "base_repair": (),
    "tip_smoothing": (),
    "shape": ("outfit_front", "outfit_back_turn", "outfit_back_draft", "outfit_side_draft",
              "mesh_humanoid", "rig_humanoid", "face_retexture", "tpose_view", "upscale"),
    "pieces": ("garment_view", "mesh_garment", "footwear_empty", "mesh_footwear", "upscale"),
    "template": (),
    "cut_texture": ("garment_cut_texture", "garment_view", "upscale"),
    "pendant": ("jewellery_mesh",),
    "accessory": (),
    "hair": ("hair_mesh", "garment_view", "hair_strands"),
    "views": (),
    "fits": (),
    "assemble": (),
    "collision": (),
}

#: Occasions checked only for an empty chain (see ``BUILD_STEP_OCCASIONS``).
SOFT_OCCASIONS = frozenset({"upscale"})

#: Occasion literals of the scanned Build modules that no Build step reaches:
#: the off-pipeline T-pose pass of ``model_refs.generate_model_ref_images``
#: (``tpose`` / the default-pose ``expression``) — on the pipeline its tpose
#: kind becomes the dressed copies (``generate_dressed_images``), and no
#: Build step calls it. The drift guard of the routes smoke names them.
OFF_BUILD_OCCASIONS: Tuple[str, ...] = ("tpose", "expression")


def _face_planned(name: str) -> bool:
    from app.core import model3d
    return bool(model3d.face_before_rig_planned(name))


def _side_views_on(_name: str) -> bool:
    from app.core import base_body
    return bool(base_body.side_views_dressed())


#: (step, occasion) pairs of ``BUILD_STEP_OCCASIONS`` a step routes only while
#: a setting asks for them — gated only then, so an install that never
#: configured the optional feature keeps its Builds: the face correction before
#: the rig (the character's "Improve face before rigging",
#: ``face_before_rig_planned``: its retexture, face view and reference upscale)
#: and the dressed side views (world setting ``base_body.dressed_side_views``).
CONDITIONAL_OCCASIONS: Dict[Tuple[str, str], Callable[[str], bool]] = {
    **{(step, occ): _face_planned for step in ("plain_body", "shape")
       for occ in ("face_retexture", "tpose_view", "upscale")},
    ("shape", "outfit_side_draft"): _side_views_on,
}


def route_check(occasion: str, character: str = "", *, chain_only: bool = False) -> Optional[str]:
    """None when the occasion's routing has an intended entry; otherwise the
    note why the step is skipped — never the empty-chain cheapest pick (an
    empty chain is "no routing chain", whatever the occasion's
    ``requires_chain``). Configuration only (``routing.intended_spec_for``:
    availability and cooldowns are ignored — those are load, not a reason to
    skip). ``chain_only``: only an empty chain is a note (``SOFT_OCCASIONS``).
    An error reading the routing is a note too: unreadable never means
    routable."""
    from app.imagegen import routing
    try:
        if not routing.chain_for(occasion, character):
            return ROUTE_NO_CHAIN.format(occasion=occasion)
        if not chain_only and not routing.intended_spec_for(occasion, character):
            return ROUTE_NO_ENTRY.format(occasion=occasion)
    except Exception as e:  # noqa: BLE001 — UnknownOccasionError included
        logger.warning("World Dev media: routing of %s (%s) not readable", occasion, character,
                       exc_info=True)
        return ROUTE_UNREADABLE.format(occasion=occasion, error=str(e) or type(e).__name__)
    return None


def _ordered(occasions) -> List[str]:
    return list(dict.fromkeys(o for o in occasions if o))


def piece_occasions(item_id: str) -> Tuple[str, ...]:
    """The occasions of one own-mesh piece's chain: its kind's pair
    (``garment_fill.OCCASIONS``) plus the cut-out's ``upscale``; a clothing
    piece in mode shell only ``garment_view`` (its mesh is made from the body
    on the CPU). Raises ``ValueError`` for a kind the table does not know —
    the gate turns it into the plan-unreadable note, never a guess."""
    from app.core import garment_set, garment_shell
    from app.core.improvements.types.garment_fill import KIND_CLOTHING, OCCASIONS as KIND_OCCASIONS
    from app.models.inventory import get_item
    item = get_item(item_id) if item_id else None
    kind = garment_set.garment_kind_of(item) if item else None
    if kind not in KIND_OCCASIONS:
        raise ValueError(f"the piece {item_id or '?'} has no known garment kind ({kind!r})")
    if kind == KIND_CLOTHING and garment_shell.shape_of(item) == garment_shell.SHELL:
        return ("garment_view",)
    return tuple(KIND_OCCASIONS[kind]) + ("upscale",)


def hair_occasions(name: str, item_id: str) -> Tuple[str, ...]:
    """The occasions of the worn hairstyle's chain, by its mode
    (``garment_hair.hairstyle_mode``): HairDeck ``hair_mesh`` (+ ``garment_view``
    for the beard-free picture while ``garment_beard.has_facial_hair``), HAAR
    ``hair_strands``, body nothing."""
    from app.core import garment_beard, garment_hair
    from app.models.inventory import get_item
    mode = garment_hair.hairstyle_mode(get_item(item_id) if item_id else None)
    if mode == garment_hair.HAAR_MODE:
        return ("hair_strands",)
    if mode == garment_hair.HAIRDECK_MODE:
        return ("hair_mesh",) + (("garment_view",) if garment_beard.has_facial_hair(name) else ())
    return ()


def _step_occs(name: str, step: Any) -> Tuple[str, ...]:
    if step.name == "pieces":
        return piece_occasions(step.item_id)
    if step.name == "hair":
        return hair_occasions(name, step.item_id)
    return BUILD_STEP_OCCASIONS.get(step.name, ())


def build_gate(name: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """``(occasions, note)`` of the character's Build in the lane's mode
    (``BUILD_EXPLICIT``): the plan of that mode, cut to the steps it runs
    (``figure_build.planned_work`` — the predicate ``figure_build.start`` uses);
    the occasions are the union of ``BUILD_STEP_OCCASIONS`` over those steps,
    pieces and hair narrowed (``piece_occasions`` / ``hair_occasions``), a
    conditional (step, occasion) only while its setting asks for it. ``note``
    instead when nothing would run: an empty plan "already built"; only manual
    steps left — the first one's own ``manual`` reason; only failed ones —
    their labels. Raises what the plan raises."""
    from app.core import figure_build
    planned, steps = figure_build.planned_work(name, explicit=BUILD_EXPLICIT)
    if not planned:
        return None, GATE_BUILT
    if not steps:
        manual = [s for s in planned if s.manual]
        if manual:
            return None, GATE_MANUAL.format(name=name, reason=manual[0].manual)
        return None, GATE_ONLY_FAILED.format(
            name=name, labels="; ".join(s.label for s in planned if s.failed) or "?")
    out: List[str] = []
    for step in steps:
        for occ in _step_occs(name, step):
            test = CONDITIONAL_OCCASIONS.get((step.name, occ))
            if test is None or test(name):
                out.append(occ)
    return _ordered(out), None


def build_occasions(name: str) -> Optional[List[str]]:
    """The occasions of ``build_gate`` (None when nothing would run)."""
    return build_gate(name)[0]


def character_mesh_occasions(name: str) -> List[str]:
    """The occasions of the off-pipeline mesh step (T-pose references, then
    ``model3d.generate_for_current_outfit``): ``tpose``; ``tpose_view`` when an
    extra reference view is on (``enabled_tpose_views``, the face view for a
    humanoid) or the face correction is planned; the mesh occasion of the
    character's rig (``mesh_occasion_for_rig``); ONLY the rig occasion of that
    rig (the mesh2rig occasion the catalog declares for it — none for rig
    "none"); ``face_retexture`` and the face reference's ``upscale`` (soft)
    when the face correction is planned."""
    from app.core import model3d
    from app.core.model_refs import enabled_tpose_views, get_view_kinds, is_humanoid
    from app.imagegen.occasions import OCCASIONS, mesh_occasion_for_rig
    rig = model3d.required_rig(name)
    face = bool(model3d.face_before_rig_planned(name, rig))
    views = [v for v in enabled_tpose_views(name) if v != "face"]
    face_view = bool(is_humanoid(name) and get_view_kinds(name).get("face"))
    out = ["tpose"]
    if views or face_view or face:
        out.append("tpose_view")
    out.append(mesh_occasion_for_rig(rig))
    out.extend(occ for occ, d in OCCASIONS.items()
               if d.get("category") == "mesh2rig" and d.get("rig") == rig)
    if face:
        out.extend(("face_retexture", "upscale"))
    return _ordered(out)


def step_occasions(kind: str, target_id: str, step: StepSpec) -> Tuple[Optional[List[str]], Optional[str]]:
    """``(occasions, note)``: every occasion the step routes, read at gate time —
    the Build's per-plan set (``build_gate``, with its note when nothing would
    run), the off-pipeline mesh's set, else the step's own ``occasions``."""
    if kind == "character" and step.id == "build":
        return build_gate(str(target_id))
    if kind == "character" and step.id == "mesh":
        return character_mesh_occasions(str(target_id)), None
    return list(step.occasions), None


def _err(e: BaseException) -> str:
    return str(e) or type(e).__name__


def step_gate(run: Any, kind: str, target_id: str, step: StepSpec) -> Optional[str]:
    """None = the step may run; else the note it is skipped with (never a
    retry). In order: the run's media switch, the media master switch
    (``image_generation.enabled``), for a character its pause of automatic
    generation, for a Build "Build automatically", then ``route_check`` for
    every occasion of ``step_occasions`` (the first failing one wins; a Build
    with nothing to run gives ``build_gate``'s note). ``run`` is the run dict
    or its id. Never raises: a reader error is a note."""
    name = str(target_id)
    character = name if kind == "character" else ""
    try:
        from app.core import world_dev_runs as wr
        row = run if isinstance(run, dict) else wr.get_run(str(run))
    except Exception as e:  # noqa: BLE001
        logger.warning("World Dev media: run %s not readable", run, exc_info=True)
        return GATE_RUN_UNREADABLE.format(error=_err(e))
    if not row or not row.get("media_enabled"):
        return GATE_RUN_OFF
    try:
        from app.imagegen.base import media_generation_enabled
        enabled = media_generation_enabled()
    except Exception as e:  # noqa: BLE001
        logger.warning("World Dev media: media master switch not readable", exc_info=True)
        return GATE_SWITCH_UNREADABLE.format(error=_err(e))
    if not enabled:
        return GATE_DISABLED
    if character:
        try:
            from app.core import generation_pause
            paused = generation_pause.is_paused(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("World Dev media: pause of %s not readable", name, exc_info=True)
            return GATE_PAUSE_UNREADABLE.format(name=name, error=_err(e))
        if paused:
            return GATE_PAUSED.format(name=name)
        if step.id == "build":
            try:
                from app.core import figure_build
                auto = figure_build.auto_build_on(name)
            except Exception as e:  # noqa: BLE001
                logger.warning("World Dev media: auto-build switch of %s not readable", name,
                               exc_info=True)
                return GATE_AUTO_BUILD_UNREADABLE.format(name=name, error=_err(e))
            if not auto:
                return GATE_AUTO_BUILD_OFF.format(name=name)
    try:
        occasions, note = step_occasions(kind, name, step)
    except Exception as e:  # noqa: BLE001 — never a render on an unread plan
        logger.warning("World Dev media: occasions of %s %s step %s not readable", kind, name,
                       step.id, exc_info=True)
        return GATE_PLAN_UNREADABLE.format(name=name, error=_err(e))
    if note:
        return note
    for occasion in occasions or []:
        note = route_check(occasion, character, chain_only=occasion in SOFT_OCCASIONS)
        if note:
            return note
    return None


# ── Task 6: the server's hairstyle as a journal op ───────────────────────

#: The ONE global media lock (``keyed_lock(*MEDIA_LOCK_KEY)``): every
#: media-state transition — the lane's pick and exit check, ``schedule``'s
#: insert+submit, cancel/remove, ``set_media_state``, ``make_hairstyle`` — runs
#: under it. Taken BEFORE ``garment_item`` / ``character_profile``, never held
#: across a render, an LLM call or a Build wait.
MEDIA_LOCK_KEY = ("world_dev_media", "lane")
#: The journal tool name of the lane's hairstyle write (M10).
HAIRSTYLE_TOOL = "media:hairstyle"


def set_media_state(run_id: str, state: str) -> None:
    """The run's media state (open · accepted · closed) under the global
    media lock, so it never changes between a lane step's state check and
    its write. ValueError for an unknown state."""
    from app.core import world_dev_runs as wr
    from app.core.keyed_lock import keyed_lock
    with keyed_lock(*MEDIA_LOCK_KEY):
        wr.set_media_state(run_id, state)


def _hairstyle_keys(name: str) -> Dict[str, Any]:
    """{BASE_HAIRSTYLE_KEY, "equipped_mesh_pieces"}: value or ABSENT (deep
    copies, read under the profile lock)."""
    import copy
    from app.core import garment_hair
    from app.core.keyed_lock import keyed_lock
    from app.core.world_dev_undo import ABSENT
    from app.models.character import get_character_profile
    with keyed_lock("character_profile", name):
        prof = get_character_profile(name) or {}
        return {k: (copy.deepcopy(prof[k]) if k in prof else ABSENT)
                for k in (garment_hair.BASE_HAIRSTYLE_KEY, "equipped_mesh_pieces")}


def make_hairstyle(run_id: str, name: str) -> Tuple[str, str]:
    """The lane's hairstyle step: ``garment_hair.ensure_hairstyle(name)`` (the
    first hairstyle from the hair body slot, worn and the plain body's) as a
    journal write of the run (M10, tool ``media:hairstyle``, inverse
    ``remove_hairstyle``), so the discard and a rollback take it back like any
    other write. Returns ``(status, note)``.

    The global media lock is held from the media-state check through
    ``complete``: a Discard (which sets the state ``closed`` under the same lock)
    cannot close and undo between the journal ``begin`` and the write. Holding
    it is safe because ``ensure_hairstyle`` renders nothing, calls no LLM and
    waits on no Build (it mints an item and claims it under ``garment_item`` ->
    ``character_profile``; its ``garment_assembly.schedule`` only queues a CPU
    job, deferred like every other trigger while a turn defers the character).

    Media state ``closed`` -> ("cancelled", "run closed"), nothing written;
    ``accepted`` -> the write WITHOUT a journal row (the run is terminal, nothing
    will undo it) -> ("done", ""), a ValueError -> ("skipped", reason) as in
    ``open``; ``open`` -> journalled: ``before`` = the two
    profile keys (value or ABSENT), the item id attached once known, written =
    {"item": ``item_row``, "keys": the two keys re-read}. No hairstyle needed
    (``ensure_hairstyle`` returned "" or the worn one) -> the row becomes a read,
    ("skipped", note); ValueError -> refused, ("skipped", reason). Any other
    error propagates (the row stays pending, with the item id attached when a
    new hairstyle was minted before the failure — the undo then removes it;
    such a pending row restores a key only while it still equals ``before``
    or what the step would have written, see
    ``world_dev_undo._hairstyle_decision``).
    Called by the lane only, never by a tool."""
    from app.core import garment_hair
    from app.core import world_dev_runs as wr
    from app.core.keyed_lock import keyed_lock
    from app.core.world_dev_undo import item_row
    with keyed_lock(*MEDIA_LOCK_KEY):
        run = wr.get_run(run_id)
        if not run:
            raise KeyError(f"unknown world-dev run: {run_id}")
        state = run.get("media_state") or "open"
        if state == "closed":
            return "cancelled", "run closed"
        if state == "accepted":
            try:
                garment_hair.ensure_hairstyle(name)
            except ValueError as e:
                return "skipped", str(e)
            return "done", ""
        before = _hairstyle_keys(name)
        owned = {str(i.get("id")) for i in garment_hair.hairstyles(name)}
        inverse = {"op": "remove_hairstyle", "name": name, "item_id": None, "before": before}
        seq = wr.begin(run_id, int(run.get("turn") or 0), "write", HAIRSTYLE_TOOL,
                       {"name": name}, "character", name, inverse=inverse)
        try:
            item_id = garment_hair.ensure_hairstyle(name)
        except ValueError as e:
            wr.complete(run_id, seq, None, f"hairstyle of {name} refused: {e}", kind="refused")
            return "skipped", str(e)
        except Exception:
            new = sorted({str(i.get("id")) for i in garment_hair.hairstyles(name)} - owned)
            if len(new) == 1:
                wr.attach(run_id, seq, name, {**inverse, "item_id": new[0]})
            raise
        if not item_id or item_id in owned:
            # "" = bald or one was taken off; an owned id = worn already.
            wr.complete(run_id, seq, None, f"{name}: no hairstyle needed", kind="read")
            return "skipped", "no hairstyle needed"
        wr.attach(run_id, seq, name, {**inverse, "item_id": item_id})
        row = item_row(item_id)
        wr.complete(run_id, seq, {"item": row, "keys": _hairstyle_keys(name)},
                    f'hairstyle {item_id} "{(row or {}).get("name") or ""}" worn by {name} '
                    "(from the hair slot)")
        return "done", ""



# ── Task 7: producers and the exact capture / removal of their media ────

#: The profile keys the producers write (``profile_image``: the portrait —
#: ``set_profile``). The Build / mesh producers write no profile key: the
#: profile writers of figure_build / base_body / model3d / model_refs are
#: settings setters (auto-build, model options, reference toggles), never part
#: of a render. No World Dev tool writes these keys (smoke).
MEDIA_PROFILE_KEYS: Tuple[str, ...] = ("profile_image",)
#: The character media roots below the character dir (``media_roots``).
CHARACTER_MEDIA_DIRS = ("model3d", "model_refs", "images", "garments", "jewellery", "template_front")
#: A modified ``.json`` up to this size is a SIDECAR: backed up and restored.
SIDECAR_MAX_BYTES = 256 * 1024
#: The gallery's own meta files — a gallery dir holding nothing else is an orphan.
GALLERY_META_FILES = frozenset({"gallery_meta.json", "prompts.json"})
#: The Build producer's trigger name and its wait.
BUILD_TRIGGER = "world_dev"
BUILD_WAIT_S = 6 * 3600
BUILD_POLL_S = 5.0
#: Image suffixes of a character image (the gallery readers' set).
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
#: Kept reasons.
KEPT_CHANGED = "changed since"
KEPT_GONE = "already gone"
KEPT_MODIFIED = "modified, not restored"
KEPT_NOT_EMPTY = "not empty"
KEPT_FOREIGN = "not the run's"
KEPT_UNSAFE = "unsafe path"
KEPT_ERROR = "could not be removed ({error})"


@dataclass
class ProduceCtx:
    """What a producer needs besides the element: the run (the hairstyle step
    journals into it) and the media row (its sidecar backups live under
    ``<storage>/.world_dev_media/<run>/<row>/``)."""
    run_id: str
    row_id: int

    def backup_dir(self) -> Path:
        from app.core.media_cleanup import safe_key
        from app.core.paths import get_storage_dir
        run = safe_key(str(self.run_id))
        if not run:
            raise ValueError(f"unsafe run id: {self.run_id!r}")
        return Path(get_storage_dir()) / ".world_dev_media" / run / str(int(self.row_id))


class StepError(Exception):
    """A producer's step did not end ``done``: ``status`` ``failed`` or
    ``skipped``, ``note`` the reason, ``artefacts`` what it produced anyway
    (always recorded — a failed Build still wrote files)."""

    def __init__(self, status: str, note: str, artefacts: Optional[List[dict]] = None):
        super().__init__(note)
        self.status = status
        self.note = note
        self.artefacts = list(artefacts or [])


def _storage() -> Path:
    from app.core.paths import get_storage_dir
    return Path(get_storage_dir())


def _rel(path) -> str:
    import os
    return os.path.relpath(os.path.abspath(str(path)), os.path.abspath(str(_storage()))).replace(os.sep, "/")


def _abs(rel: str):
    """The absolute path of a recorded storage-relative path; None when it
    would leave the storage dir (a damaged record)."""
    from pathlib import PurePosixPath
    p = PurePosixPath(str(rel or ""))
    if not str(rel or "") or p.is_absolute() or ".." in p.parts:
        return None
    return _storage().joinpath(*p.parts)


def media_roots(kind: str, target_id: str) -> List[Path]:
    """The directories whose before/after diff is a manifest step's output.

    location -> its building-model dir ``locations/<id>/model3d``
    (``location_model3d.model_dir``; gallery images are recorded by name).
    character -> ``characters/<name>/`` + ``CHARACTER_MEDIA_DIRS``:
    ``model3d`` (meshes, rigs, unrigged/texture/geometry sub dirs: model3d,
    base_body, garments, figure_build, face_retexture, outfit_bodies),
    ``model_refs`` (T-pose / view references, base drafts, skin textures:
    model_refs, base_body, base_skin), ``images`` (the portrait),
    ``garments`` (garment_store), ``jewellery`` (accessory_build.DIR_NAME) and
    ``template_front`` (garment_preview_front.DIR_NAME). Collected with
    `git grep -n "get_character_dir(" -- app/core`. The paths are built from
    ``get_character_dir`` directly, never through the readers that create
    their dir — a snapshot must not conjure one. Never the soul / skills
    files, the character dir itself or ``pending_reports.json``.

    Concurrent-writer limit: a diff attributes EVERY change under its roots
    in the step's window to the step — the TaskQueue and admin actions keep
    running while the world is frozen, so a foreign write into a diffed root
    during a long step (a Build waits up to ``BUILD_WAIT_S``) is recorded as
    the run's own and removed by a discard. Each producer therefore diffs
    only the roots it writes: the portrait ``images`` alone, the Build and
    the off-pipeline mesh ``producer_roots`` (everything but ``images``, and
    no ``MEDIA_PROFILE_KEYS`` — they write none). A concurrent writer into a
    root a step does diff stays attributed to the step (inherent to
    snapshot diffing)."""
    if kind == "location":
        from app.core import location_model3d
        return [location_model3d.model_dir(str(target_id))]
    if kind == "character":
        from app.models.character import get_character_dir
        base = get_character_dir(str(target_id))
        return [base / d for d in CHARACTER_MEDIA_DIRS]
    raise ValueError(f"no media roots for kind {kind!r}")


#: The character roots the portrait alone writes (``_produce_portrait``).
PORTRAIT_DIRS = ("images",)


def producer_roots(name: str) -> List[Path]:
    """The character roots the Build and the off-pipeline mesh write: every
    ``CHARACTER_MEDIA_DIRS`` entry but the portrait's ``images`` — a portrait
    rendered by hand while a Build runs is not the run's."""
    return [r for r in media_roots("character", name) if r.name not in PORTRAIT_DIRS]


def snapshot(roots) -> Dict[str, Any]:
    """``{"files": {rel: (size, mtime_ns, inode)}, "dirs": set(rel), "blobs":
    {rel: bytes}}`` of every regular file and dir under ``roots`` (the roots
    included; symlinks are neither followed nor recorded). ``blobs`` holds the
    bytes of every ``.json`` up to ``SIDECAR_MAX_BYTES`` — the pre-step
    content a sidecar is restored to, and how a same-size rewrite within one
    clock tick (equal mtime_ns) is still seen."""
    import os
    import stat as stat_mod
    files: Dict[str, Tuple[int, int]] = {}
    dirs: set = set()
    blobs: Dict[str, bytes] = {}
    for root in roots:
        root = str(root)
        if os.path.islink(root) or not os.path.isdir(root):
            continue
        dirs.add(_rel(root))
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for d in list(dirnames):
                full = os.path.join(dirpath, d)
                if os.path.islink(full):
                    dirnames.remove(d)
                    continue
                dirs.add(_rel(full))
            for f in filenames:
                full = os.path.join(dirpath, f)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if not stat_mod.S_ISREG(st.st_mode):
                    continue
                rel = _rel(full)
                files[rel] = (st.st_size, st.st_mtime_ns, st.st_ino)
                if f.lower().endswith(".json") and st.st_size <= SIDECAR_MAX_BYTES:
                    try:
                        with open(full, "rb") as fh:
                            blobs[rel] = fh.read()
                    except OSError:
                        pass
    return {"files": files, "dirs": dirs, "blobs": blobs}


def _sha256_file(path) -> Optional[str]:
    if path is None:
        return None
    try:
        with open(str(path), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def diff(before: Dict[str, Any], after: Dict[str, Any], backup_dir) -> List[dict]:
    """The artefacts between two snapshots, in path order: created dirs
    ``{"type": "dir", "path"}``, created files ``{"type": "file", "path",
    "size", "mtime_ns"}``, modified small JSON ``{"type": "sidecar", "path",
    "backup", "sha256", "size", "mtime_ns"}`` (the PRE-step bytes copied to
    ``backup_dir``, the POST-step sha256 and stat) and every other modified or
    vanished file ``{"type": "modified", "path"[, "size", "mtime_ns"]}``
    (recorded, never touched; the stat while the file still exists — what
    ``merge_artefacts`` folds into a run-created file record). Paths are
    relative to the storage dir. A file counts as modified when its size,
    mtime_ns or inode (an atomic replace) differ, or — for a JSON blob — its
    bytes; a same-size in-place rewrite of a binary within one clock tick is
    the one change this cannot see."""
    import os
    out: List[dict] = []
    bfiles, afiles = before["files"], after["files"]
    for d in sorted(after["dirs"] - before["dirs"]):
        out.append({"type": "dir", "path": d})
    n_backup = 0
    for rel in sorted(set(afiles) | set(bfiles)):
        now, was = afiles.get(rel), bfiles.get(rel)
        if was is None:
            out.append({"type": "file", "path": rel, "size": now[0], "mtime_ns": now[1]})
            continue
        blob = before["blobs"].get(rel)
        if now == was and (blob is None or after["blobs"].get(rel) == blob):
            continue
        if now is not None and blob is not None and now[0] <= SIDECAR_MAX_BYTES:
            sha = _sha256_file(_abs(rel))
            if sha is not None:
                os.makedirs(str(backup_dir), exist_ok=True)
                while True:  # never reuse a name: an earlier step's backup in this dir stays
                    n_backup += 1
                    target = os.path.join(str(backup_dir), f"{n_backup:04d}_{os.path.basename(rel)}")
                    try:
                        with open(target, "xb") as fh:
                            fh.write(blob)
                        break
                    except FileExistsError:
                        continue
                out.append({"type": "sidecar", "path": rel, "backup": _rel(target), "sha256": sha,
                            "size": now[0], "mtime_ns": now[1]})
                continue
        out.append({"type": "modified", "path": rel} if now is None else
                   {"type": "modified", "path": rel, "size": now[0], "mtime_ns": now[1]})
    out.sort(key=lambda a: a["path"])
    return out


def _stat(path) -> Optional[Tuple[int, int]]:
    import os
    import stat as stat_mod
    if path is None:
        return None
    try:
        st = os.lstat(str(path))
    except OSError:
        return None
    if not stat_mod.S_ISREG(st.st_mode):
        return None
    return st.st_size, st.st_mtime_ns


def merge_artefacts(existing: List[dict], new: List[dict], *,
                    superseded: Optional[List[str]] = None) -> List[dict]:
    """Fold a later step's artefacts into the ones recorded before (same row,
    or an element's rows in row-id order — ``_fold_rows``). A file the run
    CREATED and a later step rewrote stays one ``file`` record with the
    newest size/mtime (the later record's own stat, else the file's stat now;
    it is still the run's own file — a sidecar/modified record of it would
    make the removal keep it); a sidecar keeps its FIRST backup (the pre-run
    bytes) with the newest sha256; profile keys keep the first ``before`` and
    the latest ``after`` per key; exact duplicates go. A new sidecar record
    the merge drops (its path is already recorded) has its backup file
    unlinked — nothing would reference it and no removal would ever delete
    it; with ``superseded`` the backup is appended there instead (a pure
    fold: the preview must not write, the removal unlinks them after it)."""
    out = [dict(a) for a in existing]
    by_path = {a.get("path"): a for a in out if a.get("path") and a.get("type") != "profile_keys"}
    profiles = {a.get("name"): a for a in out if a.get("type") == "profile_keys"}
    for art in new:
        art = dict(art)
        typ = art.get("type")
        if typ == "profile_keys":
            old = profiles.get(art.get("name"))
            if old is None:
                out.append(art)
                profiles[art.get("name")] = art
            else:
                for k, v in (art.get("before") or {}).items():
                    old.setdefault("before", {}).setdefault(k, v)
                old.setdefault("after", {}).update(art.get("after") or {})
            continue
        old = by_path.get(art.get("path"))
        if old is None:
            out.append(art)
            by_path[art.get("path")] = art
            continue
        otyp = old.get("type")
        if typ == "sidecar" and art.get("backup") and art.get("backup") != old.get("backup") \
                and otyp in ("file", "gallery_image", "character_image", "sidecar", "modified"):
            if superseded is None:
                _drop_backup(art.get("backup"))
            else:
                superseded.append(str(art.get("backup")))
        if otyp in ("file", "gallery_image", "character_image") and typ in ("file", "sidecar", "modified"):
            if art.get("size") is not None and art.get("mtime_ns") is not None:
                old["size"], old["mtime_ns"] = art["size"], art["mtime_ns"]
            else:
                stat = _stat(_abs(old["path"]))
                if stat is not None:
                    old["size"], old["mtime_ns"] = stat
        elif otyp == "sidecar" and typ == "sidecar":
            old["sha256"] = art.get("sha256")
            for k in ("size", "mtime_ns"):
                if art.get(k) is not None:
                    old[k] = art[k]
        elif otyp == typ or (otyp == "modified" and typ == "sidecar"):
            pass  # a duplicate; an unrestorable first change stays "modified"
        else:
            out.append(art)
    return out


def _drop_backup(rel: Optional[str]) -> None:
    """Unlink one unreferenced sidecar backup (a missing one is fine)."""
    import os
    path = _abs(str(rel or ""))
    if path is None or _stat(path) is None:
        return
    try:
        os.unlink(str(path))
    except OSError as e:
        logger.warning("World Dev media: backup %s not removed: %s", rel, _err(e))


def _unchanged(art: dict) -> Optional[bool]:
    """None = the file is gone; else whether size+mtime_ns still match."""
    stat = _stat(_abs(art.get("path")))
    if stat is None:
        return None
    return stat == (art.get("size"), art.get("mtime_ns"))


def _profile_values(name: str) -> Dict[str, Any]:
    import copy
    from app.core.keyed_lock import keyed_lock
    from app.core.world_dev_undo import ABSENT
    from app.models.character import get_character_profile
    with keyed_lock("character_profile", name):
        prof = get_character_profile(name) or {}
        return {k: (copy.deepcopy(prof[k]) if k in prof else ABSENT) for k in MEDIA_PROFILE_KEYS}


def _profile_artefact(name: str, before: Dict[str, Any]) -> List[dict]:
    after = _profile_values(name)
    changed = [k for k in MEDIA_PROFILE_KEYS if after.get(k) != before.get(k)]
    if not changed:
        return []
    return [{"type": "profile_keys", "name": name, "before": {k: before[k] for k in changed},
             "after": {k: after[k] for k in changed}}]


def _as_step_error(e: BaseException, artefacts: List[dict]) -> StepError:
    """Map a producer's exception: a StepError keeps its status (the capture
    added), ``MediaGenerationDisabled`` is a skip with the disabled note, an
    HTTPException fails with its detail, anything else fails with its text."""
    if isinstance(e, StepError):
        return StepError(e.status, e.note, e.artefacts + list(artefacts))
    from fastapi import HTTPException
    from app.imagegen.base import MediaGenerationDisabled
    if isinstance(e, MediaGenerationDisabled):
        return StepError("skipped", GATE_DISABLED, artefacts)
    if isinstance(e, HTTPException):
        return StepError("failed", str(e.detail or "") or _err(e), artefacts)
    return StepError("failed", _err(e), artefacts)


def _captured(ctx: ProduceCtx, kind: str, target_id: str, fn: Callable[[], str], *,
              roots=None, profile: bool = False) -> Tuple[str, List[dict]]:
    """Run ``fn`` between two snapshots of the element's roots (and, for a
    character with ``profile``, the ``MEDIA_PROFILE_KEYS``); the diff is
    recorded even when ``fn`` raises (then raised as a StepError carrying
    it). Returns ``(note, artefacts)``."""
    roots = media_roots(kind, target_id) if roots is None else roots
    before = snapshot(roots)
    pbefore = _profile_values(str(target_id)) if profile else None
    error: Optional[BaseException] = None
    note = ""
    try:
        note = fn() or ""
    except Exception as e:  # noqa: BLE001 — re-raised below with the capture
        error = e
    arts = diff(before, snapshot(roots), ctx.backup_dir())
    if pbefore is not None:
        arts += _profile_artefact(str(target_id), pbefore)
    if error is not None:
        raise _as_step_error(error, arts) from error
    return note, arts


def _gallery_target(step: StepSpec) -> Tuple[str, str]:
    """(prompt_type, room_id) of a gallery step id (``building-front``,
    ``day:<room>``, ``night:<room>``)."""
    if ":" in step.id:
        kind, room = step.id.split(":", 1)
        return kind, room
    return step.id, ""


def _produce_gallery(ctx: ProduceCtx, kind: str, target_id: str, step: StepSpec) -> Tuple[str, List[dict]]:
    """A location gallery image through the routed gallery core
    (``world_ops.generate_gallery_image_core``, the batch path: no backend
    pick, the "location" occasion), recorded by the name it returns. Runs the
    async core with ``asyncio.run`` — the lane is a queue worker thread."""
    import asyncio
    from app.core import world_ops
    from app.models.world import get_gallery_dir
    prompt_type, room_id = _gallery_target(step)
    try:
        result = asyncio.run(world_ops.generate_gallery_image_core(
            str(target_id), {"prompt_type": prompt_type, "room_id": room_id}))
    except Exception as e:  # noqa: BLE001 — the core writes its image only on success
        raise _as_step_error(e, []) from e
    image = str((result or {}).get("image") or "")
    loc_id = str((result or {}).get("location_id") or target_id)
    if not image:
        raise StepError("failed", "the gallery core returned no image")
    path = get_gallery_dir(loc_id) / image
    stat = _stat(path)
    if stat is None:
        raise StepError("failed", f"the gallery image {image} is missing")
    warnings = "; ".join(str(w) for w in (result or {}).get("warnings") or [])
    return warnings, [{"type": "gallery_image", "location_id": loc_id, "image": image,
                       "path": _rel(path), "size": stat[0], "mtime_ns": stat[1]}]


def _produce_location_mesh(ctx: ProduceCtx, kind: str, target_id: str,
                           step: StepSpec) -> Tuple[str, List[dict]]:
    """The building mesh through the improvements engine's routed, blocking
    path (``subjects.generate_building_model(loc, "")``, source =
    ``building_source_image``); the model dir's diff is the output."""
    from app.core.improvements.types import subjects

    def run() -> str:
        subjects.generate_building_model(str(target_id), "")
        return ""
    return _captured(ctx, kind, target_id, run)


def _produce_portrait(ctx: ProduceCtx, kind: str, target_id: str,
                      step: StepSpec) -> Tuple[str, List[dict]]:
    """The portrait (``npc_assets.render_profile_image``: the request of the
    profile-image route). Each new image in ``images/`` is a
    ``character_image`` (removed through ``delete_character_image``) with its
    same-stem companions (meta JSON, video); the ``profile_image`` change is a
    ``profile_keys`` artefact. A producer complaint without an image fails."""
    from app.core import npc_assets
    from app.models.character import get_character_dir
    name = str(target_id)
    images = get_character_dir(name) / "images"

    def run() -> str:
        return npc_assets.render_profile_image(name) or ""

    try:
        note, raw = _captured(ctx, kind, name, run, roots=[images], profile=True)
    except StepError as e:
        raise StepError(e.status, e.note, _portrait_artefacts(name, e.artefacts)) from e
    arts = _portrait_artefacts(name, raw)
    if note and not any(a["type"] == "character_image" for a in arts):
        raise StepError("failed", note, arts)
    return note, arts


def _portrait_artefacts(name: str, raw: List[dict]) -> List[dict]:
    from pathlib import PurePosixPath
    new_files = [a for a in raw if a["type"] == "file"]
    images = [a for a in new_files if PurePosixPath(a["path"]).suffix.lower() in _IMAGE_SUFFIXES]
    taken = set()
    out: List[dict] = []
    for img in images:
        p = PurePosixPath(img["path"])
        companions = sorted(a["path"] for a in new_files
                            if a is not img and PurePosixPath(a["path"]).parent == p.parent
                            and PurePosixPath(a["path"]).stem == p.stem)
        taken.update(companions)
        taken.add(img["path"])
        out.append({"type": "character_image", "name": name, "file": p.name, "path": img["path"],
                    "size": img["size"], "mtime_ns": img["mtime_ns"], "companions": companions})
    out += [a for a in raw if a.get("path") not in taken]
    return out


def _produce_build(ctx: ProduceCtx, kind: str, target_id: str, step: StepSpec) -> Tuple[str, List[dict]]:
    """The Figure Build in the lane's mode (``BUILD_EXPLICIT`` False: an
    automatic ``figure_build.request(name, BUILD_TRIGGER)``), then a wait on
    ``figure_build.state`` every ``BUILD_POLL_S`` until nothing runs, is
    queued or deferred (at most ``BUILD_WAIT_S``). The character's media roots
    but ``images`` (``producer_roots``) are the output — no profile key (the
    Build writes none; a hand-rendered portrait in the window is not the run's). Not started -> skipped; a failed Build step
    or the timeout -> failed (with what was written so far)."""
    import time
    from app.core import figure_build
    name = str(target_id)

    def run() -> str:
        if BUILD_EXPLICIT:
            status = (figure_build.start(name, reason=BUILD_TRIGGER, automatic=False) or {}).get("status")
            started = status in ("started", "queued", "deferred")
        else:
            started = bool(figure_build.request(name, BUILD_TRIGGER))
        if not started:
            raise StepError("skipped", f"the Build of {name} was not started (off the pipeline, "
                                       "not automatic, paused or deferred by a running turn)")
        deadline = time.monotonic() + BUILD_WAIT_S
        while True:
            st = figure_build.state(name) or {}
            if not st.get("running") and not st.get("queued") and not st.get("deferred"):
                break
            if time.monotonic() > deadline:
                raise StepError("failed", f"the Build of {name} did not finish within "
                                          f"{BUILD_WAIT_S // 3600} h")
            time.sleep(BUILD_POLL_S)
        failed = st.get("failed") or {}
        if failed:
            raise StepError("failed", "Build failed: " + "; ".join(
                f"{k}: {v}" for k, v in sorted(failed.items(), key=lambda kv: str(kv[0]))))
        for key in ("paused", "superseded"):
            if st.get(key):
                info = st[key] or {}
                return f"Build {key}: " + str(info.get("note") or info.get("label") or "")
        return ""
    return _captured(ctx, kind, name, run, roots=producer_roots(name))


def _produce_mesh(ctx: ProduceCtx, kind: str, target_id: str, step: StepSpec) -> Tuple[str, List[dict]]:
    """Off the pipeline: T-pose references + the mesh of the worn outfit
    (``npc_assets.render_mesh``); its complaint fails the step."""
    from app.core import npc_assets
    name = str(target_id)

    def run() -> str:
        note = npc_assets.render_mesh(name) or ""
        if note:
            raise StepError("failed", note)
        return ""
    return _captured(ctx, kind, name, run, roots=producer_roots(name))


def _produce_hairstyle(ctx: ProduceCtx, kind: str, target_id: str,
                       step: StepSpec) -> Tuple[str, List[dict]]:
    """The server's first hairstyle (``make_hairstyle``): world data, so a
    JOURNAL row of the run, never an artefact."""
    status, note = make_hairstyle(ctx.run_id, str(target_id))
    if status == "done":
        return note, []
    raise StepError("failed" if status == "failed" else "skipped", note)


#: Producer key (``StepSpec.producer``) -> adapter ``(ctx, kind, target_id,
#: step) -> (note, artefacts)``; a step that does not end done raises
#: ``StepError`` (status, note, the artefacts produced anyway). Smokes replace
#: entries (or the entry points the adapters call) — no check renders.
PRODUCERS: Dict[str, Callable[[ProduceCtx, str, str, StepSpec], Tuple[str, List[dict]]]] = {
    "gallery": _produce_gallery,
    "location_mesh": _produce_location_mesh,
    "portrait": _produce_portrait,
    "build": _produce_build,
    "mesh": _produce_mesh,
    "hairstyle": _produce_hairstyle,
}


_TYPE_ORDER = {"profile_keys": 0, "gallery_image": 1, "character_image": 1, "file": 2, "sidecar": 3,
               "modified": 4, "dir": 5}


def _ordered_artefacts(artefacts: List[dict]) -> List[dict]:
    """Removal order: profile keys first (so ``delete_character_image`` no
    longer finds the portrait set and leaves the restored key alone), then
    images and files, sidecars, the report-only records, dirs deepest first."""
    def key(a):
        depth = -str(a.get("path") or "").count("/") if a.get("type") == "dir" else 0
        return (_TYPE_ORDER.get(a.get("type"), 9), depth, str(a.get("path") or a.get("name") or ""))
    return sorted((a for a in artefacts if isinstance(a, dict)), key=key)


def _decide(artefacts: List[dict], apply: bool) -> Tuple[List[str], List[dict]]:
    """THE decision of ``preview_artefacts`` and ``remove_artefacts`` (one
    function, so both agree): per artefact removed (its path, or
    ``profile <name>.<key>``) or kept ``{path|item, reason}``. With ``apply``
    the removal is carried out."""
    import os
    removed: List[str] = []
    kept: List[dict] = []
    gone: set = set()

    def keep(art, reason):
        kept.append({"path": art.get("path"), "reason": reason})

    for art in _ordered_artefacts(artefacts):
        typ = art.get("type")
        if typ == "profile_keys":
            _decide_profile(art, apply, removed, kept)
            continue
        path = _abs(art.get("path"))
        if path is None:
            keep(art, KEPT_UNSAFE)
            continue
        if typ == "modified":
            keep(art, KEPT_MODIFIED)
            continue
        if typ == "dir":
            if path.is_symlink() or not path.is_dir():
                keep(art, KEPT_GONE)
                continue
            try:
                entries = [_rel(os.path.join(str(path), e)) for e in os.listdir(str(path))]
            except OSError as e:
                keep(art, KEPT_ERROR.format(error=_err(e)))
                continue
            if any(e not in gone for e in entries):
                keep(art, KEPT_NOT_EMPTY)
                continue
            if apply:
                try:
                    os.rmdir(str(path))
                except OSError as e:
                    keep(art, KEPT_ERROR.format(error=_err(e)))
                    continue
            gone.add(art["path"])
            removed.append(art["path"])
            continue
        if typ == "sidecar":
            if _stat(path) is None:
                keep(art, KEPT_GONE)
                continue
            if _sha256_file(path) != art.get("sha256"):
                keep(art, KEPT_CHANGED)
                continue
            backup = _abs(art.get("backup"))
            if backup is None or _stat(backup) is None:
                keep(art, KEPT_ERROR.format(error="backup missing"))
                continue
            if apply:
                try:
                    tmp = str(path) + ".wdm-restore"
                    with open(str(backup), "rb") as src, open(tmp, "wb") as dst:
                        dst.write(src.read())
                    os.replace(tmp, str(path))
                    os.unlink(str(backup))
                except OSError as e:
                    keep(art, KEPT_ERROR.format(error=_err(e)))
                    continue
            removed.append(art["path"])
            continue
        # file / gallery_image / character_image
        state = _unchanged(art)
        if state is None:
            gone.add(art["path"])
            gone.update(art.get("companions") or [])
            keep(art, KEPT_GONE)
            continue
        if not state:
            keep(art, KEPT_CHANGED)
            continue
        if apply:
            try:
                _remove_file_artefact(art, path)
            except Exception as e:  # noqa: BLE001 — one artefact never blocks the others
                logger.exception("World Dev media: %s not removed", art.get("path"))
                keep(art, KEPT_ERROR.format(error=_err(e)))
                continue
        gone.add(art["path"])
        gone.update(art.get("companions") or [])
        removed.append(art["path"])
    return removed, kept


def _decide_profile(art: dict, apply: bool, removed: List[str], kept: List[dict]) -> None:
    """A profile key goes back to its before-value only while it still holds
    the after-value the step wrote (read and written under the profile lock)."""
    from app.core.keyed_lock import keyed_lock
    from app.core.world_dev_undo import ABSENT
    from app.models.character import character_row_exists, get_character_profile, save_character_profile
    name = str(art.get("name") or "")
    keys = [k for k in (art.get("after") or {}) if k in MEDIA_PROFILE_KEYS]
    if not name or not character_row_exists(name):
        kept.extend({"item": f"profile {name}.{k}", "reason": KEPT_GONE} for k in keys)
        return
    with keyed_lock("character_profile", name):
        prof = get_character_profile(name) or {}
        restore = []
        for k in keys:
            now = prof[k] if k in prof else ABSENT
            if now == art["after"][k]:
                restore.append(k)
            else:
                kept.append({"item": f"profile {name}.{k}", "reason": KEPT_CHANGED})
        if apply and restore:
            for k in restore:
                before = (art.get("before") or {}).get(k, ABSENT)
                if before == ABSENT:
                    prof.pop(k, None)
                else:
                    prof[k] = before
            if not save_character_profile(name, prof):
                kept.extend({"item": f"profile {name}.{k}",
                             "reason": KEPT_ERROR.format(error="profile not saved")} for k in restore)
                return
    removed.extend(f"profile {name}.{k}" for k in restore)


def _drop_gallery_image_meta(location_id: str, image_name: str) -> None:
    """Remove one image's ``image_metas`` entry (the generation metadata
    ``generate_gallery_image_core`` wrote) from the gallery's
    ``gallery_meta.json``; nothing is written when there is no entry."""
    from app.models.world import _load_gallery_meta, _save_gallery_meta
    meta = _load_gallery_meta(location_id)
    metas = meta.get("image_metas")
    if not isinstance(metas, dict) or image_name not in metas:
        return
    metas.pop(image_name, None)
    meta["image_metas"] = metas
    _save_gallery_meta(location_id, meta)


def _remove_file_artefact(art: dict, path) -> None:
    """Delete one unchanged file artefact: a gallery image through the
    gallery deleter while its location exists (a 404 = already gone), a
    character image through ``delete_character_image`` while the character
    exists; otherwise — and for plain files — unlink by the recorded path
    (with the companions of a character image)."""
    import os
    typ = art.get("type")
    if typ == "gallery_image":
        from app.models.world import get_location_by_id
        _forget_thumb(path)
        if get_location_by_id(str(art.get("location_id") or "")):
            from fastapi import HTTPException
            from app.core import world_ops
            from app.models.world import _drop_gallery_prompt, get_gallery_dir
            try:
                world_ops.delete_gallery_image(str(art["location_id"]), str(art["image"]))
            except HTTPException as e:
                if e.status_code != 404:
                    raise
            # The gallery deleter leaves the image's prompts.json entry and its
            # gallery_meta.json image_metas entry behind.
            _drop_gallery_prompt(get_gallery_dir(str(art["location_id"])), str(art["image"]))
            _drop_gallery_image_meta(str(art["location_id"]), str(art["image"]))
            return
        os.unlink(str(path))
        return
    if typ == "character_image":
        from app.models.character import character_row_exists, delete_character_image
        if character_row_exists(str(art.get("name") or "")):
            delete_character_image(str(art["name"]), str(art["file"]))
        elif _stat(path) is not None:
            _forget_thumb(path)
            os.unlink(str(path))
        for comp in art.get("companions") or []:
            cp = _abs(comp)
            if cp is not None and _stat(cp) is not None:
                os.unlink(str(cp))
        return
    os.unlink(str(path))


def _fold_rows(rows: List[Dict[str, Any]]) -> Tuple[List[dict], List[str]]:
    """ONE artefact list for one element's rows: their ``produced`` folded
    with ``merge_artefacts`` in row-id order (a file an earlier row created
    and a later row rewrote is still the run's own file; a sidecar goes back
    to the FIRST row's backup, checked against the LAST row's sha256), and
    the later rows' superseded sidecar backups (unlinked after a removal).
    Removing the rows one by one would restore an intermediate state."""
    merged: List[dict] = []
    superseded: List[str] = []
    for row in sorted(rows, key=lambda r: int(r["id"])):
        merged = merge_artefacts(merged, list(row.get("produced") or []), superseded=superseded)
    return merged, superseded


def _remove_folded(rows: List[Dict[str, Any]]) -> Tuple[List[str], List[dict]]:
    """``remove_artefacts`` over the folded artefacts of one element's rows,
    then the superseded backups go (no row references them any more)."""
    merged, superseded = _fold_rows(rows)
    removed, kept = remove_artefacts(merged)
    for rel in superseded:
        _drop_backup(rel)
    return removed, kept


def _forget_thumb(path) -> None:
    try:
        from app.core import thumbnails
        thumbnails.forget_sources([path])
    except Exception:  # noqa: BLE001 — a stale thumbnail cache entry is harmless
        logger.debug("World Dev media: thumbnail of %s not forgotten", path, exc_info=True)


def preview_artefacts(artefacts: List[dict]) -> Tuple[List[str], List[dict]]:
    """What ``remove_artefacts`` would do, without writing: (removed, kept)."""
    return _decide(artefacts, apply=False)


def remove_artefacts(artefacts: List[dict]) -> Tuple[List[str], List[dict]]:
    """Remove exactly what a run's steps produced, each only while unchanged
    since (size+mtime_ns / sidecar sha256 / profile after-value); a missing
    file or element is "already gone", never an error. Returns (removed
    paths / ``profile <name>.<key>``, kept ``{path|item, reason}``)."""
    return _decide(artefacts, apply=True)


def _element_exists(kind: str, ident: str) -> bool:
    if kind == "location":
        from app.models.world import get_location_by_id
        return bool(get_location_by_id(ident))
    if kind == "character":
        from app.models.character import character_row_exists
        return bool(character_row_exists(ident))
    return True


def _orphan_dirs(kind: str, ident: str) -> List[Tuple[Path, frozenset]]:
    """(dir, meta file names allowed at its top) of a vanished element,
    inner dirs before their parent."""
    from app.core.media_cleanup import safe_key
    storage = _storage()
    if kind == "location":
        key = safe_key(ident)
        if not key:
            return []
        return [(storage / "world_gallery" / key, GALLERY_META_FILES),
                (storage / "locations" / key / "model3d", frozenset()),
                (storage / "locations" / key, frozenset())]
    if kind == "character":
        from app.models.character import get_character_dir
        return [(r, frozenset()) for r in media_roots("character", ident)] + \
            [(get_character_dir(ident), frozenset())]
    return []


def sweep_orphan_dirs(run_id: str) -> Dict[str, List]:
    """After a discard: the gallery / model dirs of every element the run
    CREATED (baseline NULL) that no longer exists are removed when they hold
    nothing but empty dirs and the gallery meta files; anything else in one
    -> kept ``not the run's``. Only dirs strictly inside the storage dir, never
    a symlink. Returns ``{"removed": [paths], "kept": [{path, reason}]}``."""
    import os
    import shutil
    from app.core import world_dev_runs as wr
    from app.core.media_cleanup import contained
    removed: List[str] = []
    kept: List[dict] = []
    storage = _storage()
    for (kind, ident), base in wr.baselines(run_id).items():
        if base is not None:
            continue
        try:
            if _element_exists(kind, ident):
                continue
            dirs = _orphan_dirs(kind, ident)
        except Exception:  # noqa: BLE001 — one element never blocks the others
            logger.exception("World Dev media: orphan dirs of %s %s not read", kind, ident)
            continue
        for path, allowed in dirs:
            if path.is_symlink() or not path.is_dir() or not contained(storage, path):
                continue
            foreign = False
            for dirpath, dirnames, filenames in os.walk(str(path), followlinks=False):
                top = os.path.abspath(dirpath) == os.path.abspath(str(path))
                if (any(os.path.islink(os.path.join(dirpath, d)) for d in dirnames)
                        or any(not (top and f in allowed) for f in filenames)):
                    foreign = True
                    break
            if foreign:
                kept.append({"path": _rel(path), "reason": KEPT_FOREIGN})
                continue
            try:
                shutil.rmtree(str(path))
            except OSError as e:
                kept.append({"path": _rel(path), "reason": KEPT_ERROR.format(error=_err(e))})
                continue
            removed.append(_rel(path))
    return {"removed": removed, "kept": kept}


# ── Task 8: the lane ─────────────────────────────────────────────────────

#: The ONE global lane task type (payload ``{}``, no run id).
TASK_TYPE = "world_dev_media"
#: How long a Discard waits for a running row to stop before it reports the
#: row under ``pending`` (the lane removes that row's output when the step ends).
DISCARD_WAIT_S = 30.0
DISCARD_POLL_S = 0.05
#: Row statuses whose produced artefacts are no longer the run's to remove.
_FINISHED_STEP_STATUSES = ("done", "skipped", "failed")

#: In-process lane state, read and written under the global media lock only:
#: ``active`` while a lane handler is between its first pick and its exit
#: check; ``flags`` row id -> ("cancel" | "stop" | "remove", note) for a
#: RUNNING row (checked by the lane after every step; "stop" = a removal is
#: waiting for it and removes its output together with its element's rows). In memory on purpose: a restart
#: ends every lane (``reset_on_boot``).
_lane: Dict[str, Any] = {"active": False}
_row_flags: Dict[int, Tuple[str, str]] = {}
#: running row id -> the ids of the same element's other rows whose removal
#: waits for it (one fold over all of them when it ends — ``_fold_rows``).
_remove_with: Dict[int, set] = {}


def _media_lock():
    from app.core.keyed_lock import keyed_lock
    return keyed_lock(*MEDIA_LOCK_KEY)


def _notify_generation() -> None:
    """Push "generation" to the admins (the FreeModePanel re-reads the rows)."""
    from app.core import sync_topics
    sync_topics.notify("generation", to=sync_topics.Admins())


def _step_dict(spec: StepSpec) -> Dict[str, Any]:
    return {"id": spec.id, "label": spec.label, "status": "queued", "note": "", "fp": spec.fp}


def _pending_lane_task() -> bool:
    """True while a lane task is still PENDING (it will run the lane later).
    A RUNNING task does not count: its handler may already be past its exit
    check (the queue marks the task completed only after the handler returns)."""
    from app.core.task_queue import get_task_queue
    return any(t.get("status") == "pending"
               for t in get_task_queue().list_tasks_of_type(TASK_TYPE))


def _ensure_lane_locked() -> bool:
    """Under the global media lock: make sure some lane will see the queued
    rows. An active lane in this process picks them at its next pick (its exit
    check runs under the same lock); else a pending lane task will; else one
    is submitted. Returns True when a task was submitted."""
    if _lane["active"] or _pending_lane_task():
        return False
    from app.core.task_queue import get_task_queue
    get_task_queue().submit(TASK_TYPE, {}, queue_name="background")
    return True


def schedule(run_id: str) -> List[int]:
    """Queue the standard media chains of the run's touched elements (M1):
    under the global media lock, when the run is in review (``PLAN_STATUSES``,
    M15), its media state is ``open`` and its media switch on, one ``queued``
    row per element of ``plan(run_id)`` with due steps (each with its planned
    fp; ``scheduled_turn`` = the run's turn), then — still under the lock —
    the one global lane is ensured (``_ensure_lane_locked``). Returns the new
    row ids ([] = nothing due or not schedulable)."""
    from app.core import world_dev_runs as wr
    added: List[int] = []
    with _media_lock():
        run = wr.get_run(run_id)
        if (not run or run.get("status") not in PLAN_STATUSES
                or (run.get("media_state") or "open") != "open" or not run.get("media_enabled")):
            return []
        for kind, ident, steps in plan(run_id):
            added.append(wr.add_media_row(run_id, kind, ident, [_step_dict(s) for s in steps],
                                          scheduled_turn=int(run.get("turn") or 0)))
        if added:
            _ensure_lane_locked()
    if added:
        _notify_generation()
    return added


def _row_final_status(steps: List[dict]) -> str:
    states = [str(s.get("status") or "") for s in steps]
    if any(s == "failed" for s in states):
        return "failed"
    if states and all(s == "skipped" for s in states):
        return "skipped"
    return "done"


def _stop_flagged_locked(row: Dict[str, Any], steps: List[dict], produced: List[dict]) -> Optional[str]:
    """Under the media lock, after a step: a flagged row stops here. "remove"
    -> its produced artefacts are removed, status ``removed``; "cancel" ->
    status ``cancelled`` (its done steps keep holding their fingerprints).
    Returns the new status or None (not flagged)."""
    from app.core import world_dev_runs as wr
    flag, note = _row_flags.pop(int(row["id"]), (None, ""))
    if flag == "remove":
        _remove_ended_locked(row, steps, produced)
        return "removed"
    _remove_with.pop(int(row["id"]), None)
    if flag == "stop":
        wr.update_media_row(row["id"], status="cancelled", steps=steps, produced=produced,
                            note="stopped for its removal")
        return "cancelled"
    if flag == "cancel":
        wr.update_media_row(row["id"], status="cancelled", steps=steps, produced=produced,
                            note=note or "cancelled")
        return "cancelled"
    return None


def _remove_ended_locked(row: Dict[str, Any], steps: Optional[List[dict]],
                         produced: List[dict]) -> None:
    """Under the media lock: a row flagged "remove" has ended — its
    ``produced`` (the in-memory list, newer than the stored one) and the
    produced of the element's rows whose removal waited for it
    (``_remove_with``) are removed in ONE fold; every one of them becomes
    ``removed``."""
    from app.core import world_dev_runs as wr
    row_id = int(row["id"])
    others = [r for r in (wr.media_row(i) for i in sorted(_remove_with.pop(row_id, set())))
              if r is not None and r.get("status") != "removed" and int(r["id"]) != row_id]
    removed, kept = _remove_folded(others + [dict(row, produced=produced)])
    wr.update_media_row(row_id, status="removed", steps=steps, produced=produced,
                        note=f"removed after it ended: {len(removed)} removed, "
                             f"{len([k for k in kept if k.get('reason') != KEPT_GONE])} kept")
    for r in others:
        wr.update_media_row(r["id"], status="removed")


def _run_row(row: Dict[str, Any], live: Optional[Dict[str, Any]] = None) -> str:
    """Run the steps of one picked (``running``) row in order. Per step not
    yet finished: the element's CURRENT steps are re-read (M14 — the step
    stores the fp read just before its producer), ``step_gate`` -> skipped,
    else the producer -> done / failed / skipped; the artefacts are stored
    after EVERY step; after every step a cancel/remove flag stops the row.
    Returns the row's final status. ``live`` (the lane's) always holds the
    artefacts recorded so far and those of the step in progress, so an
    unexpected error outside a producer loses none of them."""
    from app.core import world_dev_runs as wr
    live = {} if live is None else live
    row_id, run_id = int(row["id"]), str(row["run_id"])
    kind, ident = str(row["kind"]), str(row["target_id"])
    steps: List[dict] = [dict(s) for s in row.get("steps") or [] if isinstance(s, dict)]
    produced: List[dict] = list(row.get("produced") or [])
    live.update(produced=produced, arts=[], steps=steps)
    ctx = ProduceCtx(run_id, row_id)
    for step in steps:
        if step.get("status") in _FINISHED_STEP_STATUSES:
            continue
        with _media_lock():
            status = _stop_flagged_locked(row, steps, produced)
            if status:
                return status
        try:
            current = element_steps(kind, ident)
        except Exception as e:  # noqa: BLE001 — a reader error skips the step, never renders
            logger.warning("World Dev media: steps of %s %s not readable", kind, ident, exc_info=True)
            current, note = [], f"the media steps could not be read ({_err(e)})"
        else:
            note = "" if current is not None else f"the {kind} no longer exists"
        spec = next((s for s in current or [] if s.id == step.get("id")), None)
        if spec is None and not note:
            note = "no longer needed"
        if spec is not None:
            step["fp"] = spec.fp
            note = step_gate(wr.get_run(run_id), kind, ident, spec) or ""
        if note:
            step.update(status="skipped", note=note)
        else:
            step.update(status="running", note="")
            with _media_lock():
                wr.update_media_row(row_id, steps=steps)
            _notify_generation()
            arts: List[dict] = []
            try:
                fn = PRODUCERS[spec.producer]
                step_note, arts = fn(ctx, kind, ident, spec)
                step.update(status="done", note=step_note or "")
            except Exception as e:  # noqa: BLE001 — a step never ends the lane
                err = _as_step_error(e, [])
                if not isinstance(e, StepError):
                    logger.warning("World Dev media: step %s of %s %s failed", step.get("id"), kind,
                                   ident, exc_info=True)
                arts = err.artefacts
                step.update(status=err.status if err.status in ("failed", "skipped") else "failed",
                            note=err.note)
            live["arts"] = list(arts or [])
            produced = merge_artefacts(produced, arts or [])
            live.update(produced=produced, arts=[])
        with _media_lock():
            wr.update_media_row(row_id, steps=steps, produced=produced)
        _notify_generation()
    with _media_lock():
        status = _stop_flagged_locked(row, steps, produced)
        if status:
            return status
        final = _row_final_status(steps)
        wr.update_media_row(row_id, status=final, steps=steps, produced=produced)
    return final


def _row_failed_locked(row: Dict[str, Any], live: Dict[str, Any], e: BaseException) -> None:
    """Under the media lock: ``_run_row`` raised outside a producer. The
    row's artefacts (``live``: the recorded ones plus those of the step in
    progress) are kept on the row; when a removal flagged it, or its run's
    media state is closed by now, they are removed (status ``removed``),
    else the row is ``failed``."""
    from app.core import world_dev_runs as wr
    row_id = int(row["id"])
    produced = list(live.get("produced") or row.get("produced") or [])
    arts = list(live.get("arts") or [])
    if arts:
        try:
            produced = merge_artefacts(produced, arts)
        except Exception:  # noqa: BLE001 — keep both lists; the removal folds them again
            logger.exception("World Dev media: artefacts of row %s not merged", row_id)
            produced = produced + arts
    flag, _note = _row_flags.pop(row_id, (None, ""))
    run = wr.get_run(str(row["run_id"])) or {}
    if flag == "remove" or (run.get("media_state") or "open") == "closed":
        try:
            _remove_ended_locked(row, live.get("steps"), produced)
            return
        except Exception:  # noqa: BLE001 — fall through: recorded as failed, artefacts kept on the row
            logger.exception("World Dev media: artefacts of failed row %s not removed", row_id)
    _remove_with.pop(row_id, None)
    wr.update_media_row(row_id, status="failed", produced=produced, note=_err(e))


def run_lane(payload: Optional[dict] = None) -> Dict[str, Any]:
    """The queue handler of the ONE global lane (payload ignored): oldest
    queued row of ALL runs first, one at a time, until none is left. The pick
    and the exit check ("no queued row left -> return") run under the global
    media lock, so a row ``schedule`` inserts is either seen by the next pick
    or finds the lane gone and ensures a new task — never stranded. A second
    lane task while one is active in this process returns at once (the active
    one sees every queued row). Never holds the lock across a step."""
    from app.core import world_dev_runs as wr
    processed: List[int] = []
    with _media_lock():
        if _lane["active"]:
            return {"status": "busy", "rows": []}
        _lane["active"] = True
    try:
        while True:
            with _media_lock():
                row = wr.oldest_queued_row()
                if row is None:
                    _lane["active"] = False
                    return {"status": "idle", "rows": processed}
                run = wr.get_run(str(row["run_id"])) or {}
                if (run.get("media_state") or "open") == "closed":
                    wr.update_media_row(row["id"], status="cancelled", note="run closed")
                    continue
                wr.update_media_row(row["id"], status="running")
            _notify_generation()
            processed.append(int(row["id"]))
            live: Dict[str, Any] = {}
            try:
                _run_row(row, live)
            except Exception as e:  # noqa: BLE001 — one row never ends the lane
                logger.exception("World Dev media: row %s failed", row["id"])
                with _media_lock():
                    _row_failed_locked(row, live, e)
            _notify_generation()
            try:
                # The last row of a closed / accepted run: its backups are
                # no longer needed (Task 9).
                sweep_backups(str(row["run_id"]))
            except Exception:  # noqa: BLE001 — a leftover backup dir only
                logger.exception("World Dev media: backups of run %s not swept", row["run_id"])
    finally:
        with _media_lock():
            _lane["active"] = False


def register_world_dev_media_handler() -> None:
    """Register the lane's queue handler (server startup)."""
    from app.core.task_queue import get_task_queue
    get_task_queue().register_handler(TASK_TYPE, run_lane)


def cancel_queued(run_id: str, note: str) -> int:
    """Under the global media lock: the run's queued rows -> ``cancelled``
    with ``note``; its running row is flagged and stops after its CURRENT
    step (status ``cancelled``, done steps keep their fingerprints). Returns
    the number of queued rows cancelled."""
    from app.core import world_dev_runs as wr
    n = 0
    with _media_lock():
        for row in wr.media_rows(run_id, statuses=("queued", "running")):
            if row["status"] == "queued":
                wr.update_media_row(row["id"], status="cancelled", note=note)
                n += 1
            elif _row_flags.get(int(row["id"]), ("", ""))[0] not in ("remove", "stop"):
                _row_flags[int(row["id"])] = ("cancel", note)
    if n:
        _notify_generation()
    return n


def _running_step(row: Dict[str, Any]) -> str:
    return next((str(s.get("id")) for s in row.get("steps") or []
                 if isinstance(s, dict) and s.get("status") == "running"), "")


def _element_groups(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """The rows per element (first-row order), each group in row-id order."""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: int(r["id"])):
        groups.setdefault((str(row["kind"]), str(row["target_id"])), []).append(row)
    return list(groups.values())


def _remove_locked(rows: List[Dict[str, Any]]) -> Dict[str, List]:
    """Under the media lock, per element of the listed rows (re-read): a
    queued row with nothing produced becomes ``cancelled``; the produced
    artefacts of the element's other rows are removed in ONE fold
    (``_fold_rows`` — the exact inverse even when two rows rewrote the same
    file), each of them ``removed``. When one of the element's rows is
    running it is flagged "remove" and listed under ``pending``, and the
    element's other rows wait for it (a queued one becomes ``cancelled``):
    the lane removes all of them in one fold when it ends."""
    from app.core import world_dev_runs as wr
    out: Dict[str, List] = {"removed": [], "kept": [], "pending": []}
    current = [wr.media_row(int(r["id"])) or r for r in rows]
    for group in _element_groups([r for r in current if r.get("status") != "removed"]):
        running = [r for r in group if r.get("status") == "running"]
        rest = []
        for row in group:
            if row.get("status") == "running":
                continue
            if row.get("status") == "queued" and not row.get("produced"):
                wr.update_media_row(row["id"], status="cancelled", note="removed before it ran")
                continue
            rest.append(row)
        if running:
            for row in running:
                _row_flags[int(row["id"])] = ("remove", "")
                out["pending"].append({"row": int(row["id"]), "kind": row["kind"],
                                       "id": row["target_id"], "step": _running_step(row)})
            _remove_with.setdefault(int(running[0]["id"]), set()).update(int(r["id"]) for r in rest)
            for row in rest:
                if row.get("status") == "queued":
                    wr.update_media_row(row["id"], status="cancelled",
                                        note="removal waits for the running render")
            continue
        if not rest:
            continue
        removed, kept = _remove_folded(rest)
        out["removed"] += removed
        out["kept"] += kept
        for row in rest:
            wr.update_media_row(row["id"], status="removed")
    return out


def _remove_rows_waiting(run_id: str, select: Callable[[Dict[str, Any]], bool],
                         wait_s: Optional[float]) -> Dict[str, List]:
    """Flag a running selected row "stop" (it ends after its current step as
    ``cancelled``, removing nothing itself), wait (at most ``wait_s``) for it,
    then ``_remove_locked``: one fold per element over every selected row
    that is not running — so a row that ended during the wait is removed and
    reported together with its element's other rows; one still running is
    flagged "remove" and reported pending."""
    import time
    from app.core import world_dev_runs as wr
    with _media_lock():
        rows = [r for r in wr.media_rows(run_id) if select(r)]
        for row in rows:
            if row["status"] == "running" and _row_flags.get(int(row["id"]), ("", ""))[0] != "remove":
                _row_flags[int(row["id"])] = ("stop", "")
    running_ids = {int(r["id"]) for r in rows if r["status"] == "running"}
    if running_ids and wait_s:
        deadline = time.monotonic() + float(wait_s)
        while time.monotonic() < deadline:
            if all((wr.media_row(i) or {}).get("status") != "running" for i in running_ids):
                break
            time.sleep(DISCARD_POLL_S)
    with _media_lock():
        report = _remove_locked(rows)
    _notify_generation()
    return report


def remove_rows(run_id: str, row_ids) -> Dict[str, List]:
    """Remove the media of the given rows of the run now (no wait): a
    running row is flagged and reported ``pending`` (the lane removes its
    output when the current step returns). Returns
    ``{"removed", "kept", "pending"}``."""
    ids = {int(i) for i in row_ids}
    return _remove_rows_waiting(run_id, lambda r: int(r["id"]) in ids, None)


def remove_run_media(run_id: str) -> Dict[str, List]:
    """Every media row of the run: queued -> cancelled, running -> flagged and
    waited for up to ``DISCARD_WAIT_S`` (still running -> ``pending``), every
    other row's artefacts removed (``remove_artefacts``, status ``removed``).
    Returns ``{"removed": [...], "kept": [...], "pending": [{row, kind, id,
    step}]}`` — removed equals what ``preview_run_media`` listed."""
    return _remove_rows_waiting(run_id, lambda r: True, DISCARD_WAIT_S)


def remove_element_media(run_id: str, kind: str, target_id: str) -> Dict[str, List]:
    """``remove_run_media`` narrowed to one element of the run (cross-turn
    ``delete_created``, Task 9)."""
    return _remove_rows_waiting(
        run_id, lambda r: r["kind"] == kind and str(r["target_id"]) == str(target_id), DISCARD_WAIT_S)


# ── Task 9: the run lifecycle ────────────────────────────────────────────

def sweep_backups(run_id: str) -> bool:
    """Remove ``<storage>/.world_dev_media/<run>/`` (the pre-step copies of
    rewritten sidecars, Task 7 deviation 6) once the run is closed or accepted
    and none of its rows is queued or running any more — nothing can restore
    from them then (a discard has removed what it could; an accepted run
    keeps everything). Under the global media lock, so a row cannot start
    between the check and the removal. True when the dir was removed."""
    from app.core import world_dev_runs as wr
    from app.core.media_cleanup import remove_owned_dir
    with _media_lock():
        run = wr.get_run(run_id)
        if not run or (run.get("media_state") or "open") == "open":
            return False
        if wr.media_rows(run_id, statuses=("queued", "running")):
            return False
        root = _storage() / ".world_dev_media"
        if not root.is_dir():
            return False
        return remove_owned_dir(root, str(run_id))


def close_run_media(run_id: str) -> Dict[str, List]:
    """Discard / terminal rollback, BEFORE the journal undo (Architecture,
    Discard steps 1-3): the media state becomes ``closed`` (no row of the
    run starts any more, no hairstyle is journaled), every character the run
    touched is deferred again (``defer_run`` — the undo's automatic
    triggers are recorded, ``finish_closed_run`` replays them), then
    ``remove_run_media``: queued rows cancelled, a running row flagged and
    waited for at most ``DISCARD_WAIT_S`` (still running -> ``pending``; the
    lane removes its output when the step returns), every produced artefact
    removed while unchanged since. Returns ``{"removed", "kept", "pending"}``."""
    set_media_state(run_id, "closed")
    defer_run(run_id)
    return remove_run_media(run_id)


def finish_closed_run(run_id: str) -> Dict[str, List]:
    """Discard / terminal rollback, AFTER the journal undo (Discard steps
    5-6): ``sweep_orphan_dirs`` (the gallery / model dirs of created elements
    the undo deleted), then the deferral is released WITH the replay of the
    triggers the undo suppressed (characters that still exist only), then
    the run's backup dir is swept when no row is running. Returns the sweep
    ``{"removed", "kept"}``."""
    try:
        swept = sweep_orphan_dirs(run_id)
    finally:
        release_all(run_id, replay=True)
    sweep_backups(run_id)
    return swept


def finish_accepted_run(run_id: str) -> None:
    """Accept (M12): nothing is cancelled — the media state becomes
    ``accepted`` (queued rows keep running, a hairstyle is written without a
    journal row), the deferral is released without a replay, and the backup
    dir is swept once the lane holds no row of the run any more (else the
    lane sweeps it after the run's last row)."""
    set_media_state(run_id, "accepted")
    release_all(run_id, replay=False)
    sweep_backups(run_id)


def _element_name(kind: str, ident: str) -> str:
    """The display name of an element: a location's stored name (its id when
    it is gone or unreadable); a character's id IS its name."""
    if kind == "location":
        try:
            from app.models.world import get_location_by_id
            return str((get_location_by_id(ident) or {}).get("name") or ident)
        except Exception:  # noqa: BLE001 — the label only
            return ident
    return ident


def _element_label(kind: str, ident: str) -> str:
    return f'{kind} {ident} "{_element_name(kind, ident)}"'


def _preview_elements(run_id: str) -> List[Dict[str, Any]]:
    """Per element (first-row order): what ``remove_run_media`` would remove
    and keep now — one ``preview_artefacts`` over the folded artefacts
    (``_fold_rows``) of the element's rows that are not removed — and the
    running step, if any (then nothing of the element is removed now: its
    rows wait for the running one, ``_remove_locked``)."""
    from app.core import world_dev_runs as wr
    out = []
    for group in _element_groups(wr.media_rows(run_id)):
        live = [r for r in group if r["status"] != "removed"]
        running = [_running_step(r) or "starting" for r in live if r["status"] == "running"]
        artefacts = [] if running else _fold_rows(live)[0]
        removed, kept = preview_artefacts(artefacts)
        out.append({"kind": str(group[0]["kind"]), "id": str(group[0]["target_id"]),
                    "artefacts": artefacts, "running": running, "removed": removed, "kept": kept})
    return out


def preview_run_media(run_id: str) -> Dict[str, List]:
    """``{"removed", "kept", "pending"}`` as ``remove_run_media`` would
    report them now, without writing."""
    out: Dict[str, List] = {"removed": [], "kept": [], "pending": []}
    for el in _preview_elements(run_id):
        out["removed"] += el["removed"]
        out["kept"] += el["kept"]
        out["pending"] += [{"kind": el["kind"], "id": el["id"], "step": s} for s in el["running"]]
    return out


def _count_phrase(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def media_preview_lines(run_id: str) -> List[str]:
    """The discard preview's media lines: per element one
    ``media of <kind> <id> "<name>": 3 images, 2 model files — removed``, one
    ``... a render is running (<step>) — its output is removed when it ends``
    per running row, and one line per kept artefact (``<path> — <reason>,
    kept``; "already gone" records are nothing to remove and get no line)."""
    lines: List[str] = []
    for el in _preview_elements(run_id):
        label = f"media of {_element_label(el['kind'], el['id'])}"
        types = {}
        for art in el["artefacts"]:
            if isinstance(art, dict) and art.get("path"):
                types[str(art["path"])] = art.get("type")
        n_img = n_file = n_side = n_prof = 0
        for item in el["removed"]:
            if item.startswith("profile "):
                n_prof += 1
                continue
            typ = types.get(item)
            if typ in ("gallery_image", "character_image"):
                n_img += 1
            elif typ == "file":
                n_file += 1
            elif typ == "sidecar":
                n_side += 1
        parts = [p for n, p in ((n_img, _count_phrase(n_img, "image")),
                                (n_file, _count_phrase(n_file, "model file")),
                                (n_side, _count_phrase(n_side, "sidecar") + " restored"),
                                (n_prof, _count_phrase(n_prof, "profile key") + " restored")) if n]
        if parts:
            lines.append(f"{label}: {', '.join(parts)} — removed")
        for step in el["running"]:
            lines.append(f"{label}: a render is running ({step}) — its output is removed when it ends")
        for k in el["kept"]:
            if k.get("reason") == KEPT_GONE:
                continue
            lines.append(f"{label}: {k.get('path') or k.get('item')} — {k.get('reason')}, kept")
    return lines


# ── Task 10: what the routes call (status, run switch, retry) ────────────

class MediaConflict(RuntimeError):
    """A media action the run's state refuses (the route answers 409)."""


SWITCH_OFF_NOTE = "media switched off"
#: Step statuses a retry makes due again (their fingerprints are cleared).
RETRY_STEP_STATUSES = ("failed", "skipped")
#: Rows whose failed/skipped steps a retry clears (a queued/running row is
#: still working; a cancelled row's undone steps hold nothing anyway; a
#: removed row holds nothing at all — ``_held``).
RETRY_ROW_STATUSES = ("done", "failed", "skipped")
_STEP_STATUS_KEYS = ("id", "label", "status", "note")


def media_status(run_id: str) -> Optional[Dict[str, Any]]:
    """The panel's view of the run's media, None for an unknown run:
    ``{"enabled", "state", "elements": [{"kind", "id", "name", "row_id",
    "status", "note", "steps": [{"id", "label", "status", "note"}],
    "produced": <count>}]}`` — the NEWEST row per element, elements in
    first-row order. Read-only."""
    from app.core import world_dev_runs as wr
    run = wr.get_run(run_id)
    if run is None:
        return None
    elements = []
    for group in _element_groups(wr.media_rows(run_id)):
        row = group[-1]
        kind, ident = str(row["kind"]), str(row["target_id"])
        elements.append({
            "kind": kind, "id": ident, "name": _element_name(kind, ident),
            "row_id": int(row["id"]), "status": str(row.get("status") or ""),
            "note": str(row.get("note") or ""),
            "steps": [{k: step.get(k, "") for k in _STEP_STATUS_KEYS}
                      for step in row.get("steps") or [] if isinstance(step, dict)],
            "produced": len(row.get("produced") or [])})
    return {"enabled": bool(run.get("media_enabled")),
            "state": str(run.get("media_state") or "open"), "elements": elements}


def _live_run_locked(run_id: str, *, media_open: bool = False) -> Dict[str, Any]:
    """Under the media lock: the run, KeyError when unknown, MediaConflict
    when it is closed. With ``media_open`` also MediaConflict when the run's
    media state is no longer ``open`` (a discard/accept in progress has
    already closed or accepted its media before the run's terminal status
    lands): an action that would schedule must not answer 200 for nothing."""
    from app.core import world_dev_runs as wr
    run = wr.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    if run.get("status") in wr.TERMINAL_STATUSES:
        raise MediaConflict(f"run is {run['status']}: its media can no longer change")
    state = run.get("media_state") or "open"
    if media_open and state != "open":
        raise MediaConflict(f"the run's media are {state}: they can no longer change")
    return run


def set_run_switch(run_id: str, on: bool) -> Dict[str, Any]:
    """The run's media switch. Off — allowed on any open run, also while a
    turn runs: the switch goes off first (under the media lock, so no
    ``schedule`` adds a row after it), then ``cancel_queued`` cancels the
    queued rows and stops the running one after its current step. On — only
    in review (``PLAN_STATUSES``): MediaConflict while a turn runs (nothing
    changes), else the switch goes on and ``schedule`` queues what is due.
    KeyError for an unknown run, MediaConflict for a closed one. Returns
    ``{"enabled", "cancelled", "queued"}``."""
    from app.core import world_dev_runs as wr
    with _media_lock():
        run = _live_run_locked(run_id, media_open=bool(on))
        if on and run.get("status") not in PLAN_STATUSES:
            raise MediaConflict(f"run is {run['status']}: media can be switched on "
                                "only while the run waits for review")
        wr.set_media_enabled(run_id, bool(on))
    if not on:
        return {"enabled": False, "cancelled": cancel_queued(run_id, SWITCH_OFF_NOTE),
                "queued": []}
    # Outside the lock on purpose: a turn that starts in between makes
    # schedule refuse (it re-checks the status under the lock); its turn end
    # schedules with the switch already on.
    return {"enabled": True, "cancelled": 0, "queued": schedule(run_id)}


def retry(run_id: str) -> List[int]:
    """Retry what failed or was skipped, only in review (``PLAN_STATUSES``;
    MediaConflict otherwise — running or closed; KeyError for an unknown
    run; MediaConflict too when the run's media switch is off or its media
    state is not ``open`` — checked under the media lock BEFORE any
    fingerprint is cleared, since ``schedule`` would add nothing and a
    cleared fingerprint would make the step due at a later turn end without
    any retry). Under the media lock every failed/skipped STEP of a done / failed /
    skipped row is superseded: its fingerprint is cleared, the row's status
    and its done steps stay (they keep holding what they rendered). A done
    row holds all its steps (``_held``), so without the cleared fingerprint
    a step it skipped would never be due again. Then ``schedule`` queues
    what ``plan`` now sees due; returns the new row ids."""
    from app.core import world_dev_runs as wr
    marked = 0
    with _media_lock():
        run = _live_run_locked(run_id, media_open=True)
        if run.get("status") not in PLAN_STATUSES:
            raise MediaConflict(f"run is {run['status']}: media can be retried "
                                "only while the run waits for review")
        if not run.get("media_enabled"):
            raise MediaConflict("media are switched off: switch them on to retry")
        for row in wr.media_rows(run_id, statuses=RETRY_ROW_STATUSES):
            steps = list(row.get("steps") or [])
            changed = False
            for i, step in enumerate(steps):
                if (isinstance(step, dict) and step.get("status") in RETRY_STEP_STATUSES
                        and step.get("fp")):
                    steps[i] = dict(step, fp="")
                    changed = True
            if changed:
                wr.update_media_row(row["id"], steps=steps)
                marked += 1
    if marked:
        _notify_generation()
    return schedule(run_id)


def reset_on_boot() -> Dict[str, int]:
    """Boot: a row left ``running`` by the last process becomes ``queued``
    again (its running step too; done steps are skipped by the lane) when its
    run's media state is open or accepted; for a closed run its produced
    artefacts are removed (status ``removed`` — the discard reported it
    pending and its lane is gone). Then the one lane task is ensured when a
    queued row exists. Called after the task queue started (its own stale
    ``running`` tasks are pending again by then, so no duplicate is made)."""
    from app.core import world_dev_runs as wr
    counts = {"requeued": 0, "removed": 0, "submitted": 0}
    with _media_lock():
        _remove_with.clear()
        for row in wr.media_rows_with_status(("running",)):
            run = wr.get_run(str(row["run_id"])) or {}
            if (run.get("media_state") or "open") == "closed":
                # The discard left the element's other rows waiting for this
                # one: one fold over all of them (their wait list was in memory).
                group = [r for r in wr.media_rows(str(row["run_id"]), kind=str(row["kind"]),
                                                  target_id=str(row["target_id"]))
                         if r["status"] != "removed"]
                _remove_folded(group)
                for r in group:
                    if int(r["id"]) != int(row["id"]):
                        wr.update_media_row(r["id"], status="removed")
                wr.update_media_row(row["id"], status="removed", note="removed at boot (run closed)")
                counts["removed"] += 1
                continue
            steps = [dict(s, status="queued") if isinstance(s, dict) and s.get("status") == "running"
                     else s for s in row.get("steps") or []]
            wr.update_media_row(row["id"], status="queued", steps=steps)
            counts["requeued"] += 1
        _row_flags.clear()
        if wr.oldest_queued_row() is not None and _ensure_lane_locked():
            counts["submitted"] = 1
    return counts
