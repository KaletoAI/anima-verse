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

Location gaps for a location the run CREATED also check: places whose rooms are
all open (and that have an open room or a drawn plot) with no props in any room
or world props inside their boundary
(``no props on the open ground (place_world_prop, or place_room_prop in an open room)``),
placed entrances without a path terrain area within 10 m, and settlement spacing when
the run created at least three placed places (gap > 25 m and <= 150 m).

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


def _is_open_room(room: Dict[str, Any]) -> bool:
    """True when a room has no walls (open / no_walls / always_visible)."""
    lay = room.get("layout") if isinstance(room.get("layout"), dict) else {}
    return bool(lay.get("open") or lay.get("no_walls") or lay.get("always_visible"))


#: Terrain kinds that count as a walkway/road for the entrance-path gap.
#: The terrain catalog carries no path/road flag, so this set is explicit;
#: an area counts only when its kind is in PATH_KINDS AND defined in the
#: world's effective terrain catalog.
PATH_KINDS = frozenset({"path", "road"})


def _is_path_area(area: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> bool:
    """True when a terrain area's kind is in :data:`PATH_KINDS` and defined in
    the world's effective terrain catalog (``effective_catalog()``)."""
    kind = str(area.get("kind") or "")
    return kind in PATH_KINDS and kind in catalog


def _missing_entrance_path(loc: Dict[str, Any]) -> bool:
    """True when a placed location's entrance points (level-0 outside doorways
    plus boundary_openings, or its boundary rim when neither exists) have no
    path area within 10 m. Read / compose errors are logged and return False."""
    if loc.get("pos_x") is None or loc.get("pos_z") is None:
        return False
    try:
        from app.core.boundary_entry import opening_world_points
        from app.core.scene_recipe import compose_scene
        from app.core.terrain_types import effective_catalog
        from app.core.world_dev_tools import _edge_gap_m
        from app.core.world_geometry import (boundary_world_points,
                                             local_to_world, polygon_distance,
                                             polygon_points)
        from app.models.terrain import list_areas
        cx, cz = float(loc["pos_x"]), float(loc["pos_z"])
        yaw = float(loc.get("yaw_deg") or 0.0)
        catalog = effective_catalog()
        path_polys = [
            a["polygon"] for a in list_areas()
            if _is_path_area(a, catalog) and polygon_points(a.get("polygon"))
        ]
        try:
            scene = compose_scene(loc, read_only=True)
        except Exception as exc:  # noqa: BLE001 — a compose error is no gap
            _log().warning("path check of %s: compose_scene failed: %s",
                           loc.get("id"), exc)
            return False
        entrances: List[Tuple[float, float]] = []
        for d in scene.get("doorways") or []:
            if not isinstance(d, dict):
                continue
            if int(d.get("level") or 0) != 0 or not d.get("outside"):
                continue
            at = d.get("at_world")
            if isinstance(at, (list, tuple)) and len(at) >= 2:
                entrances.append(local_to_world(float(at[0]), float(at[1]), cx, cz, yaw))
        for _edge, pt in opening_world_points(loc):
            entrances.append((float(pt[0]), float(pt[1])))
        if entrances:
            return not any(
                polygon_distance(px, pz, poly) <= 10.0
                for px, pz in entrances for poly in path_polys
            )
        rim = boundary_world_points(loc) or [(cx, cz)]
        return not any(_edge_gap_m(rim, poly) <= 10.0 for poly in path_polys)
    except Exception as exc:  # noqa: BLE001 — a read error is no gap
        _log().warning("path check of %s failed: %s", loc.get("id"), exc)
        return False


def run_placed_locations(run_id: str) -> List[Dict[str, Any]]:
    """Every still-existing placed location created by ``run_id`` (journal
    scope None, with finite pos_x and pos_z). Shared between completeness
    (:func:`_settlement_spacing_gap`) and ``world_dev_tools._spacing_note``."""
    from app.models.world import get_location_by_id
    out: List[Dict[str, Any]] = []
    for kind, ident, scope in run_elements(run_id):
        if kind != "location" or scope is not None:
            continue
        row = get_location_by_id(ident)
        if row is not None and row.get("pos_x") is not None and row.get("pos_z") is not None:
            out.append(row)
    return out


def _settlement_spacing_gap(loc: Dict[str, Any], run_id: str) -> Optional[str]:
    """Spacing gap when the run created >= 3 placed locations and the nearest
    other run-created placed location is > 25 m and <= 150 m away edge to edge.
    Beyond 150 m edge to edge a place is treated as a separate site and no
    spacing gap is reported."""
    if not run_id or loc.get("pos_x") is None or loc.get("pos_z") is None:
        return None
    try:
        from app.core.world_dev_tools import (SETTLEMENT_GAP_MAX_M,
                                              SETTLEMENT_RADIUS_M, _edge_gap_m,
                                              _entry_world_shape,
                                              _placement_entry)
        this_id = str(loc.get("id") or "")
        run_placed = run_placed_locations(run_id)
        if len(run_placed) < 3:
            return None
        this_shape = _entry_world_shape(
            _placement_entry(loc, loc["pos_x"], loc["pos_z"], loc.get("yaw_deg")))
        nearest: Optional[float] = None
        for other in run_placed:
            if str(other.get("id") or "") == this_id:
                continue
            oshape = _entry_world_shape(
                _placement_entry(other, other["pos_x"], other["pos_z"],
                                 other.get("yaw_deg")))
            gap = _edge_gap_m(this_shape, oshape)
            if nearest is None or gap < nearest:
                nearest = gap
        if nearest is not None and SETTLEMENT_GAP_MAX_M < nearest <= SETTLEMENT_RADIUS_M:
            return (f"stands {round(nearest)} m from the nearest place of this run — "
                    f"a village's houses stand 3–10 m apart")
        return None
    except Exception as exc:  # noqa: BLE001 — a read error is no gap
        _log().warning("spacing check of %s failed: %s", loc.get("id"), exc)
        return None


def location_gaps(loc: Dict[str, Any], created: bool = True,
                  floor_plan: bool = True,
                  run_id: Optional[str] = None) -> List[str]:
    """The gaps of a stored location. ``created`` False (the run only updated
    it and wrote no x/z for it) = nothing is checked. ``floor_plan`` False
    (the run did not create it) skips the created-only gaps: ``no floor plan``
    (E5), outdoor open-ground props, entrance path within 10 m, and settlement
    spacing (when ``run_id`` is given)."""
    if not created:
        return []
    from app.core.world_geometry import polygon_points
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    gaps: List[str] = []
    if loc.get("pos_x") is None or loc.get("pos_z") is None:
        gaps.append("unplaced (no x/z) — not a travel target")
    rooms = [r for r in loc.get("rooms") or [] if isinstance(r, dict)]
    real_rooms = [r for r in rooms
                  if str(r.get("id") or "") != GROUND_ROOM_ID
                  and not is_floor_room(str(r.get("id") or ""))]
    if floor_plan and real_rooms and not _has_floor_plan(loc):
        gaps.append("no floor plan (set_room_layout)")
    if floor_plan:
        has_outline = bool(polygon_points((loc.get("map3d") or {}).get("boundary")))
        # Only a place the model can furnish: an open room of its own
        # (place_room_prop) or a drawn plot (place_world_prop inside it). A bare
        # pin with only the ground room has neither, so the gap could never close.
        if (real_rooms or has_outline) and all(_is_open_room(r) for r in real_rooms):
            has_prop = any(
                isinstance(r.get("layout"), dict) and bool(r["layout"].get("props"))
                for r in rooms
            )
            if not has_prop:
                try:
                    from app.core.world_geometry import boundary_contains
                    from app.models.world_props import list_world_props
                    has_prop = any(
                        p.get("x") is not None and p.get("z") is not None
                        and boundary_contains(loc, float(p["x"]), float(p["z"]))
                        for p in list_world_props()
                    )
                except Exception as exc:  # noqa: BLE001 — a read error is no prop
                    _log().warning("world-prop check of %s failed: %s", loc.get("id"), exc)
            if not has_prop:
                gaps.append(
                    "no props on the open ground "
                    "(place_world_prop, or place_room_prop in an open room)"
                )
        if _missing_entrance_path(loc):
            gaps.append("entrance without a path within 10 m (add_terrain_area kind path)")
        if run_id:
            spacing_gap = _settlement_spacing_gap(loc, run_id)
            if spacing_gap:
                gaps.append(spacing_gap)
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
                                floor_plan=scope is None, run_id=run_id))


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
    from app.models.character import no_config_auto_create
    lines: List[str] = []
    total = complete = 0
    media_on: Optional[bool] = None
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
                                 floor_plan=scope is None, run_id=run_id)
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
