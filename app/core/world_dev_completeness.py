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
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

#: Inverse op of a journal row -> the gap group of a character it touches.
#: restore_character / restore_status_effects touch no group.
GROUP_OF_OP = {
    "restore_home_schedule": "home",
    "remove_known_places": "known",
    "remove_outfits": "outfits",
    "restore_soul": "soul",
    "restore_body_slots": "body_slots",
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
    (``home``, ``known``, ``outfits``, ``soul``, ``body_slots``;
    ``known`` reports only ``knows only its home``)."""
    from app.core import soul_writer
    from app.core.world_dev_apply import _template_has_wardrobe
    from app.core.world_dev_tools import _missing_body_attrs, _template_fields
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
    if (wanted("home") or wanted("known")) and home is not None:
        known = set(get_known_locations(name))
        if known <= {str(home.get("id"))}:
            gaps.append("knows only its home")
    return gaps


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


def location_gaps(loc: Dict[str, Any], created: bool = True,
                  floor_plan: bool = True) -> List[str]:
    """The gaps of a stored location. ``created`` False (the run only updated
    it and wrote no x/z for it) = nothing is checked. ``floor_plan`` False
    (the run did not create it) skips ``no floor plan`` (E5): a place with
    at least one real room (not the ground, not a storey corridor) and
    nothing the scene composer can draw."""
    if not created:
        return []
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    gaps: List[str] = []
    if loc.get("pos_x") is None or loc.get("pos_z") is None:
        gaps.append("unplaced (no x/z) — not a travel target")
    real_rooms = [r for r in loc.get("rooms") or [] if isinstance(r, dict)
                  and str(r.get("id") or "") != GROUND_ROOM_ID
                  and not is_floor_room(str(r.get("id") or ""))]
    if floor_plan and real_rooms and not _has_floor_plan(loc):
        gaps.append("no floor plan (set_room_layout)")
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
            elif kind == "location" and op in _POSITION_OPS:
                groups[key].add("position")
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
                                floor_plan=scope is None))


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
    lines: List[str] = []
    total = complete = 0
    for kind, ident, scope in run_elements(run_id):
        row = _exists(kind, ident)
        if row is None:
            continue
        if kind == "character":
            gaps = character_gaps(ident, scope)
            label = f'character "{ident}"'
        elif kind == "location":
            gaps = location_gaps(row, scope is None or "position" in scope,
                                 floor_plan=scope is None)
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
        if gaps:
            lines.append(f"{label}: missing: " + "; ".join(gaps))
        else:
            complete += 1
    return lines, complete, total
