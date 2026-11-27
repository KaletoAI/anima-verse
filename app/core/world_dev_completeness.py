"""World Dev free mode — what an element the agent built or changed still lacks.

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 9
(gap 8). The result lines of the character and location write tools end with
:func:`suffix` of these gaps, and the read tool ``check_run`` lists them for
every element of the run.

Scope. A character or location the run CREATED is checked in full. One the run
only UPDATED is checked only in the gap groups the run's own journal touched
(:data:`GROUP_OF_OP`), so a hand-made character the agent merely edited is
never asked for a home, a schedule or clothes the task did not ask about.
A journal row counts for its group only when its inverse names something the
call really changed (a no-op step, such as known places that were already
known, widens nothing). Adding known places is its own group (``known``),
which reports only ``knows only its home``.
``wears nothing`` belongs to no group: the free tools cannot change what an
existing character wears (D6), so it is reported only for created characters.

Ownership follows world_dev_undo.discard_preview: an element the run deleted
(a done ``recreate_*`` row of a cross-turn delete, or the inverse-less done
row of a same-turn ``delete_created``, which marked the creating row undone)
and that exists again is somebody else's unless a NEWER creating row of this
run made it again; the rows before that delete widen nothing.

An element counts (in ``check_run``'s "k of n") only when the run created it
or one of its live rows after the last such delete changed something, so a
no-op update or a deleted element does not inflate n.

"Complete" is what the character editor shows (plan
2026-11-25-world-dev-free-complete-characters-budget, Task 5, C1): besides
the groups above, at least one secret (group ``secrets``; secrets are
journaled under target kind ``secret``, so only a created character or
``check_character`` reports it) and a decision on every skill GROUP that is
not on (group ``skills``, widened by a run's set_skill). The read tool
``check_character`` always checks in full.

Media gaps (no portrait, no base body) are not agent gaps: the agent has no
tool for them, so they never make an element incomplete; they are listed
apart (:func:`media_gaps`), in ``check_run`` also on the line of a complete
character. With the run's media on, a check records the baseline of a
character the run has not touched yet with its missing outputs marked due
(:func:`media_split`) and says "pending" only for a gap whose step is due in
the run's media plan, so the lane really renders what the line promises;
with media off the line says nothing will be rendered.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

#: Inverse op of a journal row -> the gap group of a character it touches.
#: restore_status_effects touches no group.
GROUP_OF_OP = {
    "restore_character": "appearance",
    "restore_home_schedule": "home",
    "remove_known_places": "known",
    "remove_outfits": "outfits",
    "restore_soul": "soul",
    "restore_body_slots": "body_slots",
    # A set_skill row is never a no-op (it is refused otherwise), so it has
    # no _CHANGE_KEYS entry.
    "restore_skill_config": "skills",
}

#: Inverse ops of a location write that make an UPDATED location's
#: placement part of the run's change.
_POSITION_OPS = ("restore_position",)

#: Keys of a character group inverse that name what the call changed; a row
#: whose keys are all empty was a no-op. restore_soul is absent: its
#: before_text is None for a file that did not exist, so it always counts.
_CHANGE_KEYS = {
    "restore_home_schedule": ("before",),
    "remove_known_places": ("ids",),
    "remove_outfits": ("outfits", "inventory", "items", "names"),
    "restore_body_slots": ("before",),
    # An update that changed nothing attaches an empty diff.
    "restore_character": ("profile", "config"),
    "restore_location": ("before",),
    "restore_status_effects": ("before",),
}


_ALL_CHANGE_KEYS = tuple(sorted({k for keys in _CHANGE_KEYS.values() for k in keys}))


def _changed_something(row: Dict[str, Any]) -> bool:
    """A journal digest (world_dev_runs.entry_digests) changed something."""
    keys = _CHANGE_KEYS.get(str(row.get("op") or ""))
    return keys is None or any(row["changed"].get(k) for k in keys)

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _soul_without_content(text: Optional[str]) -> bool:
    """True when a soul text holds nothing but headings: every heading line,
    blank line and HTML comment (the scaffold's writing hints) removed, it is
    empty. An absent file is empty too."""
    body = _COMMENT.sub("", text or "")
    return not any(line.strip() and not line.lstrip().startswith("#")
                   for line in body.splitlines())


def character_gaps(name: str, scope: Optional[Set[str]] = None) -> List[str]:
    """The gaps of a stored character, in a fixed order. ``scope`` None = all
    (a character this run created); otherwise only the gaps of these groups
    (``home``, ``known``, ``outfits``, ``soul``, ``body_slots``, ``appearance``,
    ``secrets``, ``skills``; ``known`` reports only ``knows only its
    home``). Media gaps are not here (:func:`media_gaps`)."""
    from app.core import soul_writer
    from app.core.world_dev_apply import _template_has_wardrobe
    from app.core.world_dev_tools import (_appearance_lead_error, _field_store,
                                          _missing_body_attrs, _template_fields)
    from app.models.character import (get_character_config,
                                      get_character_current_location,
                                      get_character_daily_schedule,
                                      get_character_outfits, get_character_profile,
                                      get_known_locations)
    from app.models.inventory import get_equipped_pieces
    from app.models.world import get_location_by_id

    def wanted(group: str) -> bool:
        return scope is None or group in scope

    prof = get_character_profile(name) or {}
    template = str(prof.get("template") or "human-default")
    wardrobe = _template_has_wardrobe(template)
    gaps: List[str] = []
    home = None
    if wanted("home") or wanted("known"):
        cfg = get_character_config(name) or {}
        home_id = str(cfg.get("home_location") or "").strip()
        home = get_location_by_id(home_id) if home_id else None
    if wanted("home"):
        if home is None:
            gaps.append("no home — not in the world")
        else:
            if home.get("pos_x") is None or home.get("pos_z") is None:
                gaps.append(f"home {home_id} is unplaced (no x/z)")
            if not str(get_character_current_location(name) or "").strip():
                gaps.append("not placed")
    if wardrobe and wanted("outfits") and not get_character_outfits(name):
        gaps.append("no outfits")
    if wardrobe and scope is None and not get_equipped_pieces(name):
        gaps.append("wears nothing")
    if wanted("home"):
        schedule = get_character_daily_schedule(name) or {}
        if not schedule.get("slots"):
            gaps.append("no daily schedule")
    if wanted("soul"):
        empty = [key for key, field in _template_fields(template).items()
                 if field.get("source_file")
                 and _soul_without_content(soul_writer.read_text(name, str(field["source_file"])))]
        if empty:
            gaps.append("soul sections without content: " + ", ".join(empty))
    if wanted("body_slots"):
        missing = _missing_body_attrs(name)
        if missing:
            gaps.append("body slots unset: " + ", ".join(missing))
    if wanted("appearance"):
        bad_leads: List[str] = []
        cfg_app: Optional[Dict[str, Any]] = None
        for key, field in _template_fields(template).items():
            if not str(field.get("lead") or "").strip():
                continue
            if _field_store(field) == "config":
                if cfg_app is None:
                    cfg_app = get_character_config(name) or {}
                val = cfg_app.get(key)
            else:
                val = prof.get(key)
            if _appearance_lead_error(key, field, val):
                bad_leads.append(key)
        if bad_leads:
            gaps.append("appearance without placeholders: " + ", ".join(bad_leads))
    if (wanted("home") or wanted("known")) and home is not None:
        known = set(get_known_locations(name))
        if known <= {str(home.get("id"))}:
            gaps.append("knows only its home")
    # The secrets and skills readers run after a write too (create_character's
    # line, update_character's suffix): a reader error is logged and is no gap,
    # never a tool error for a write that already happened.
    if wanted("secrets"):
        try:
            from app.models.secrets import list_secrets
            if not list_secrets(name):
                gaps.append("no secret (add_secret)")
        except Exception as exc:  # noqa: BLE001
            _log().warning("gaps of %s: secrets not readable: %s", name, exc)
    if wanted("skills"):
        try:
            from app.core.world_dev_tools import _open_skill_decisions
            open_groups = _open_skill_decisions(name)
        except Exception as exc:  # noqa: BLE001
            _log().warning("gaps of %s: skill decisions not readable: %s", name, exc)
            open_groups = []
        if open_groups:
            gaps.append("skills not decided (set_skill on or off): "
                        + ", ".join(str(g["text"]) for g in open_groups))
    return gaps


def _log():
    from app.core.log import get_logger
    return get_logger("world_dev_completeness")


#: :func:`media_gaps` text -> the media step (``world_dev_media``) that renders it.
MEDIA_GAP_STEPS = {"no portrait": "portrait", "no base body": "build"}


def media_gaps(name: str) -> List[str]:
    """What the media lane renders for a character and it does not have yet:
    ``no portrait`` (no ``profile_image``, or its file is gone) and
    ``no base body`` (on the base-body pipeline, no base body stored —
    ``world_dev_media._base_body_present``). Read-only — no directory is
    created and no default config saved (callers wrap it in
    ``no_config_auto_create``); a reader error is no gap (logged)."""
    from app.core.log import get_logger
    from app.models.character import get_character_dir, get_character_profile
    log = get_logger("world_dev_completeness")
    gaps: List[str] = []
    try:
        prof = get_character_profile(name) or {}
    except Exception as exc:  # noqa: BLE001 — a read error is no gap
        log.warning("media gaps of %s: profile not readable: %s", name, exc)
        return gaps
    try:
        image = str(prof.get("profile_image") or "").strip()
        if (not image or Path(image).name != image
                or not (get_character_dir(name) / "images" / image).is_file()):
            gaps.append("no portrait")
    except Exception as exc:  # noqa: BLE001
        log.warning("media gaps of %s: portrait check failed: %s", name, exc)
    try:
        from app.core import base_body
        from app.core.world_dev_media import _base_body_present
        if (base_body.is_base_pipeline(name, profile=prof)
                and not _base_body_present(name, prof)):
            gaps.append("no base body")
    except Exception as exc:  # noqa: BLE001
        log.warning("media gaps of %s: base body check failed: %s", name, exc)
    return gaps


def _media_enabled(run_id: str) -> bool:
    from app.core import world_dev_runs as wr
    run = wr.get_run(run_id)
    return bool(run and run.get("media_enabled"))


def media_split(run_id: str, name: str, media: List[str]) -> Tuple[List[str], List[str]]:
    """(pending, not due) of a character's media gaps with the run's media
    on. A character the run has not touched yet gets its media baseline
    here, its missing outputs marked due
    (``world_dev_media.note_check_touch`` — run bookkeeping, not world data;
    never raises), otherwise ``world_dev_media.plan`` would never see a
    character the run only checked. A gap is pending only when its step is
    due in the run's media plan (``due_step_ids``, which counts a missing
    output as due — world_dev_media Task 6); a gap whose step a queued or
    running row of the run already holds (or whose step the plan otherwise
    does not list) gets it under "not due" — no promise the lane does not
    keep.

    The recorded baseline OUTLIVES a per-turn rollback on purpose: it is no
    journal row, so ``world_dev_undo.undo`` never sees it (like the baseline
    a write step's ``note_touch`` records), and the lane then renders after
    the next turn exactly what the check found missing — what a run with
    media on is meant to do anyway; the world itself carries no trace of the
    rolled-back turn."""
    from app.core import world_dev_media
    steps = {gap: MEDIA_GAP_STEPS.get(gap) for gap in media}
    world_dev_media.note_check_touch(run_id, "character", name,
                                     {s for s in steps.values() if s})
    due = world_dev_media.due_step_ids(run_id, "character", name)
    pending = [gap for gap in media if steps[gap] and steps[gap] in due]
    return pending, [gap for gap in media if gap not in pending]


#: Line texts of the media gaps of ``check_character`` (one line each).
MEDIA_PENDING = "media pending (rendered after the turn): "
MEDIA_NOT_DUE = "media missing (not due in this run's media plan — not rendered): "
MEDIA_OFF = "media missing (Generate media is off for this run — not rendered): "
#: The shorter suffixes ``check_run`` hangs on a character's line.
RUN_MEDIA_PENDING = " · media pending: "
RUN_MEDIA_NOT_DUE = " · media missing (not due — not rendered): "
RUN_MEDIA_OFF = " · media missing (Generate media is off): "


def check_character_lines(run_id: str, name: str) -> List[str]:
    """The read tool ``check_character``: every gap of a stored character in
    full scope, then its media gaps — with the run's media on split into
    pending and not due (:func:`media_split`, which records the baseline of
    a character the run only checked), with it off one "not rendered"
    line. A pure read: a character without a stored config is read with
    its defaults in memory (``no_config_auto_create``), never saved — a
    write outside the journal that Discard could not take back."""
    from app.models.character import no_config_auto_create
    with no_config_auto_create():
        gaps = character_gaps(name)
        media = media_gaps(name)
    lines = [f'character "{name}": ' + (("missing: " + "; ".join(gaps)) if gaps
                                        else "complete")]
    if media:
        if _media_enabled(run_id):
            pending, not_due = media_split(run_id, name, media)
            if pending:
                lines.append(MEDIA_PENDING + "; ".join(pending))
            if not_due:
                lines.append(MEDIA_NOT_DUE + "; ".join(not_due))
        else:
            lines.append(MEDIA_OFF + "; ".join(media))
    return lines


def _has_floor_plan(loc: Dict[str, Any]) -> bool:
    """What the scene composer needs to draw a place
    (``scene_recipe._compose_stored``): a room with a layout, a building
    outline (``map3d.outline``, 3+ points) or a building model. A model
    lookup that fails counts as present — never a gap the agent cannot fix."""
    if any(isinstance(r, dict) and r.get("layout") for r in loc.get("rooms") or []):
        return True
    if len((loc.get("map3d") or {}).get("outline") or []) >= 3:
        return True
    from app.core.location_model3d import find_building_model
    try:
        return find_building_model(str(loc.get("id") or "")) is not None
    except Exception as exc:  # noqa: BLE001 — a read error is no gap
        from app.core.log import get_logger
        get_logger("world_dev_completeness").warning(
            "building model lookup of %s failed: %s", loc.get("id"), exc)
        return True


def _location_needs_hull(loc: Dict[str, Any]) -> bool:
    """True when the location has at least one closed above-ground room
    (layout dict, not no_walls, level >= 0, not ground/corridor) and no stored
    ``map3d.hull_description`` with a non-empty style."""
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    has_closed = False
    for r in loc.get("rooms") or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if not rid or rid == GROUND_ROOM_ID or is_floor_room(rid):
            continue
        lay = r.get("layout")
        if not isinstance(lay, dict) or lay.get("no_walls"):
            continue
        try:
            if int(lay.get("level", 0) or 0) < 0:
                continue
        except (TypeError, ValueError):
            continue
        has_closed = True
        break
    if not has_closed:
        return False
    hd = (loc.get("map3d") or {}).get("hull_description")
    return not (isinstance(hd, dict) and isinstance(hd.get("style"), str) and hd["style"].strip())


def _wants_hull(run_id: str, scope: Optional[Set[str]],
                building_models: Optional[str] = None) -> bool:
    """True when this run expects a building hull for the location: the run's
    mode is ``hull`` and the run created or re-laid out the location."""
    if building_models is None:
        from app.core import world_dev_runs as wr
        building_models = wr.building_models_of(run_id)
    return building_models == "hull" and (scope is None or "layout" in scope)


def location_gaps(loc: Dict[str, Any], created: bool = True,
                  floor_plan: bool = True,
                  check_hull: bool = False) -> List[str]:
    """The gaps of a stored location. ``created`` False (the run only updated
    it and wrote no x/z for it) skips placement and floor-plan checks.
    ``floor_plan`` False (the run did not create it) skips ``no floor plan``
    (E5): a place with at least one real room (not the ground, not a storey
    corridor) and nothing the scene composer can draw. ``check_hull`` True
    (run in ``hull`` mode and created or re-laid out by this run) reports
    ``no building hull (build_hull)`` when closed rooms exist without a
    ``map3d.hull_description``."""
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    gaps: List[str] = []
    if created:
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            gaps.append("unplaced (no x/z) — not a travel target")
        real_rooms = [r for r in loc.get("rooms") or [] if isinstance(r, dict)
                      and str(r.get("id") or "") != GROUND_ROOM_ID
                      and not is_floor_room(str(r.get("id") or ""))]
        if floor_plan and real_rooms and not _has_floor_plan(loc):
            gaps.append("no floor plan (set_room_layout)")
    if check_hull and _location_needs_hull(loc):
        gaps.append("no building hull (build_hull)")
    return gaps


def suffix(gaps: List[str]) -> str:
    return ("; missing: " + "; ".join(gaps)) if gaps else "; complete"


# ── Scope from the run's journal ─────────────────────────────────────────

def run_elements(run_id: str) -> List[Tuple[str, str, Optional[Set[str]]]]:
    """(kind, id, scope) of every element the run's journal names, in the
    order of its first write. scope None = created by the run (a creating
    row that is not undone and not followed by the run's own done delete);
    else the set of touched groups — for a location {"position"} when the run
    wrote its x/z. Existence is NOT checked here."""
    from app.core import world_dev_runs as wr
    from app.core.world_dev_tools import _CREATE_OPS
    order: List[Tuple[str, str]] = []
    created: Set[Tuple[str, str]] = set()
    touched: Set[Tuple[str, str]] = set()
    groups: Dict[Tuple[str, str], Set[str]] = {}
    for row in reversed(wr.entry_digests(run_id, _ALL_CHANGE_KEYS)):
        kind = str(row.get("target_kind") or "")
        ident = str(row.get("target_id") or "")
        if kind not in _CREATE_OPS or not ident:
            continue
        key = (kind, ident)
        if key not in groups:
            order.append(key)
            groups[key] = set()
        op = str(row.get("op") or "")
        done = row.get("state") == "done"
        if op == _CREATE_OPS[kind][0]:
            created.add(key)
        elif done and (op.startswith("recreate_") or (
                row.get("tool") == "delete_created" and not row.get("has_inverse"))):
            # The run deleted it — cross-turn (recreate_* row) or same-turn
            # (no inverse; the creating row is undone): what stands under
            # this name now is somebody else's until a newer creating row of
            # the run makes it again; older rows widen nothing.
            created.discard(key)
            touched.discard(key)
            groups[key] = set()
        elif not _changed_something(row):
            continue
        else:
            touched.add(key)
            if kind == "character" and op in GROUP_OF_OP:
                groups[key].add(GROUP_OF_OP[op])
            elif kind == "location":
                if op in _POSITION_OPS:
                    groups[key].add("position")
                if done and row.get("tool") == "set_room_layout":
                    groups[key].add("layout")
    # A terrain or height area is an element only when the run created it
    # (it has no gaps); an updated one is not listed. A character or
    # location counts when created or really changed (see the module doc).
    return [(k, i, None if (k, i) in created else groups[(k, i)]) for k, i in order
            if (k, i) in created
            or (k in ("character", "location") and (k, i) in touched)]


def element_scope(run_id: str, kind: str, ident: str) -> Optional[Set[str]]:
    """The scope of one element (see run_elements); an element the journal
    does not name has the empty scope."""
    for k, i, scope in run_elements(run_id):
        if k == kind and i == str(ident):
            return scope
    return set()


def character_suffix(run_id: str, name: str) -> str:
    return suffix(character_gaps(name, element_scope(run_id, "character", name)))


def location_suffix(run_id: str, loc: Dict[str, Any]) -> str:
    scope = element_scope(run_id, "location", str(loc.get("id") or ""))
    return suffix(location_gaps(loc, scope is None or "position" in scope,
                                floor_plan=scope is None,
                                check_hull=_wants_hull(run_id, scope)))


def _exists(kind: str, ident: str) -> Optional[Dict[str, Any]]:
    """The stored element, or None when it is gone (a character as {})."""
    if kind == "character":
        from app.models.character import character_row_exists
        return {} if character_row_exists(ident) else None
    if kind == "location":
        from app.models.world import get_location_by_id
        return get_location_by_id(ident)
    if kind == "terrain":
        from app.models.terrain import get_area
        return get_area(ident)
    if kind == "world_prop":
        from app.core.world_dev_undo import world_prop_row
        return world_prop_row(ident)
    if kind == "terrain_type":
        from app.core.world_dev_undo import terrain_type_row
        return terrain_type_row(ident)
    if kind == "item":
        from app.core.world_dev_undo import item_row
        return item_row(ident)
    from app.core.world_dev_tools import _height_area
    return _height_area(ident)


def check_run_lines(run_id: str) -> Tuple[List[str], int, int]:
    """(one line per element with gaps, complete count, element count) of
    every element the run created or changed that still exists."""
    from app.core import world_dev_runs as wr
    from app.models.character import no_config_auto_create
    lines: List[str] = []
    total = complete = 0
    media_on: Optional[bool] = None
    building_models = wr.building_models_of(run_id)
    for kind, ident, scope in run_elements(run_id):
        row = _exists(kind, ident)
        if row is None:
            continue
        if kind == "character":
            # A pure read (see check_character_lines).
            with no_config_auto_create():
                gaps = character_gaps(ident, scope)
                media = media_gaps(ident)
            label = f'character "{ident}"'
        elif kind == "location":
            gaps = location_gaps(row, scope is None or "position" in scope,
                                 floor_plan=scope is None,
                                 check_hull=_wants_hull(run_id, scope, building_models))
            label = f'location {ident} "{row.get("name") or ""}"'
        elif kind == "world_prop":
            gaps, label = [], f"world prop {ident}"
        elif kind == "terrain_type":
            gaps, label = [], f"terrain kind {ident}"
        elif kind == "item":
            gaps, label = [], f"item {ident}"
        else:
            gaps, label = [], f"{kind} area {ident}"
        total += 1
        line = f"{label}: missing: " + "; ".join(gaps) if gaps else f"{label}: complete"
        if gaps and kind == "character" and scope is not None:
            line += " (only what this run changed — check_character lists all)"
        media_suffix = ""
        if kind == "character":
            if media:
                if media_on is None:
                    media_on = _media_enabled(run_id)
                if media_on:
                    pending, not_due = media_split(run_id, ident, media)
                    if pending:
                        media_suffix += RUN_MEDIA_PENDING + "; ".join(pending)
                    if not_due:
                        media_suffix += RUN_MEDIA_NOT_DUE + "; ".join(not_due)
                else:
                    media_suffix = RUN_MEDIA_OFF + "; ".join(media)
        if gaps:
            lines.append(line + media_suffix)
        else:
            # Media gaps never lower "complete" (the agent cannot fix them), but a
            # complete character still shows them.
            complete += 1
            if media_suffix:
                lines.append(line + media_suffix)
    return lines, complete, total
