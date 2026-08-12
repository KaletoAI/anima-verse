"""World-domain operations behind app/routes/world.py.

Logic moved 1:1 out of the route handlers (code-review section 5b); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
import asyncio
import math
import os
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from app.core.log import get_logger
from app.core.scatter_curves import curve_map, tessellate
from app.imagegen.base import BackendBusyError

if TYPE_CHECKING:  # type-only — the composer is imported where it is used
    from app.core.prompt_compose import ShapeHint

logger = get_logger("world")

from app.models.world import (
    GROUND_ROOM_ID,
    list_locations, add_location, location_visible_to_character,
    visibility_context,
    rename_location, resolve_location, get_location_by_id,
    get_background_path, get_background_file_path,
    get_background_images, remove_background_image,
    get_gallery_dir, list_gallery_images,
    save_gallery_prompt, get_all_gallery_prompts,
    set_gallery_image_room, get_gallery_image_rooms, remove_gallery_image_room,
    set_gallery_image_type, get_gallery_image_types, remove_gallery_image_type,
    set_gallery_image_meta, get_gallery_image_metas,
    get_room_by_id,
    toggle_background_image,
    clear_room_prompt_changed, clear_location_prompt_changed)


# === Rooms of a location, as the avatar sees them ===

def build_avatar_rooms(avatar: str, location: Optional[Dict[str, Any]],
                       lang: str = "") -> List[Dict[str, Any]]:
    """The rooms of ``location`` with the lock state for ONE avatar.

    Entry: ``{id, name, is_entry, is_ground, enterable, reason}``. ``is_ground``
    marks the location's ground so a client can label it without knowing the
    reserved id — it is a room like any other: addressed by this id, entered
    through ``/play/enter-room``, and CHECKED like any other, so a rule may
    lock it too.

    ``enterable`` comes from the same ``check_access`` that route refuses
    with, so a room the UI offers and a room the server accepts can never
    drift apart; ``reason`` is the rule's own message and empty when the room
    is open. Per avatar and changing with events, therefore NEVER part of the
    signature-cached scene recipe (plan-betreten-und-tueren.md § 5).
    """
    from app.models.rules import check_access
    from app.models.world import (
        GROUND_ROOM_ID, get_entry_room_id, get_ground_name)

    loc_id = (location or {}).get("id", "") or ""
    entry_id = get_entry_room_id(location) if location else ""
    out: List[Dict[str, Any]] = []
    for room in ((location.get("rooms") if location else None) or []):
        rid = room.get("id", "") or ""
        name = room.get("name", "") or ""
        if rid == GROUND_ROOM_ID and not name:
            # The ground room may stay unnamed — then it falls back to the
            # same translated word in every location.
            name = get_ground_name(loc_id, lang)
        enterable, reason = check_access(avatar, loc_id, room_id=rid)
        out.append({"id": rid, "name": name, "is_entry": rid == entry_id,
                    "is_ground": rid == GROUND_ROOM_ID,
                    "enterable": enterable, "reason": reason})
    return out


# === Locations ===

def conditions_pass(conditions: Any, character_name: str,
                    location_id: str) -> bool:
    """Do ALL authored conditions hold for this character (AND semantics)?

    Takes a list or a single string; an empty entry is skipped, an empty list
    passes. Used for both ``visible_when`` and ``accessible_when`` — the map
    filter and the entry gate must read the same field the same way, and the
    travel route reads it as the ENTRY gate (``accessible_when`` is a wall,
    not a hint: backend-status-3d.md, commit bdd8598). Public because that
    consumer lives in another module.
    """
    from app.core.activity_engine import evaluate_condition
    if not conditions:
        return True
    if isinstance(conditions, str):
        conditions = [conditions]
    for c in conditions:
        if not c:
            continue
        ok, _ = evaluate_condition(str(c), character_name, location_id)
        if not ok:
            return False
    return True


def build_locations_payload(character_name: str) -> Dict[str, Any]:
    """List locations from a character's point of view.

    If ``character_name`` is set, locations with ``visible_when``/
    ``accessible_when`` are filtered against the character inventory/state.
    Invisible locations (visible_when fails) are removed; inaccessible
    locations (accessible_when fails) get an ``accessible: false`` flag.
    Without ``character_name`` all locations are returned unfiltered
    (admin view).
    """
    locations = list_locations()

    if character_name:
        filtered = []
        for loc in locations:
            loc_id = loc.get("id", "")
            vw = loc.get("visible_when") or []
            if vw and not conditions_pass(vw, character_name, loc_id):
                continue  # location not visible
            aw = loc.get("accessible_when") or []
            loc["accessible"] = (conditions_pass(aw, character_name, loc_id)
                                 if aw else True)
            filtered.append(loc)
        locations = filtered

    from app.core.boundary_entry import has_entrance
    from app.core.surface_textures import library_kinds, resolve_terrain_kind
    known_kinds = library_kinds()
    for loc in locations:
        loc_id = loc.get("id", "")
        loc["image_count"] = len(list_gallery_images(loc_id)) if loc_id else 0
        # A HINT for the editor, not a reachability verdict: openings channel
        # entry (with them, they are the only ways in — decision 2026-08-04),
        # and WITHOUT any the boundary is free (E4 task 5). The rule lives in
        # ONE function; the editor only displays what it says.
        loc["has_entrance"] = has_entrance(loc)
        # The ground outside, resolved (plan-grundflaeche.md § 5): '' means
        # the terrain names no library entry — the renderers keep their
        # procedural ground for it and the editor marks the miss.
        loc["surface_kind"] = resolve_terrain_kind(loc.get("terrain"),
                                                   known_kinds)
    return {"locations": locations}


# === Worldmap payload (player map panel + 3D client) ===

def build_worldmap_payload(avatar_name: Optional[str] = None,
                           show_all: bool = False) -> Dict[str, Any]:
    """Aggregated world map in METRES: locations (centre/rotation/footprint
    edge + optional map3d metadata), character positions (+avatar/activity/
    room/mood/travel target) and active disruption/danger events. One request
    instead of N fetches — read-only, for the player map panel and external
    map clients.

    Payload v2 (Seamless World, E1): the grid is gone. A location is a square
    of edge ``plan_width_m`` centred on (``pos_x``, ``pos_z``) and rotated by
    ``yaw_deg``; every character carries its free metre point in ``pos``.
    Painted terrain is deliberately NOT in here — clients fetch
    ``GET /play/terrain`` once and refetch it whenever ``terrain_sig`` changes.

    Fog of war (§ A12): with ``show_all=False`` the payload only carries what
    the avatar knows — placed locations pass through
    ``location_visible_to_character``, characters and events follow their
    location. ``show_all=True`` is the unfiltered admin view. ``world_bounds``
    is always computed over ALL placed footprints, so the map keeps its extent
    no matter how much of it is still dark.
    """
    from app.models.events import list_events
    from app.models.character import (
        list_available_characters, get_character_current_location,
        get_character_pos,
        get_effective_activity, get_effective_pose_key, get_movement_target,
        get_character_profile_image,
        get_character_current_room, get_character_current_feeling,
    )
    from app.core.expression_pose_maps import resolve_pose_animation
    from app.core.animation_sets import resolve_sets as resolve_animation_sets
    from app.core.world_geometry import placed_footprint
    from app.models.terrain import list_areas, terrain_sig

    avatar = (avatar_name or "").strip()
    fogged = not show_all
    # The fog predicate runs once per placed location on a 3-second poll —
    # read the avatar's known_locations/inventory ONCE and hand them to the
    # predicate instead of letting it re-read them per location.
    _vis_ctx = visibility_context(avatar) if (fogged and avatar) else None

    def _visible(loc: Dict[str, Any]) -> bool:
        """Fog predicate. An unplaced location (no metre position) is not on
        the map at all — template placeholders always pass, they hide
        nothing."""
        if not fogged:
            return True
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            return True
        if not avatar:
            return False
        return location_visible_to_character(avatar, loc, context=_vis_ctx)

    locations = []
    name_by_id = {}
    visible_ids = set()
    # Map extent in metres over ALL placed locations AND all painted terrain
    # areas — computed BEFORE the fog filter, so the map keeps its extent no
    # matter how much of it is still dark. With a scale anchor a location
    # contributes its whole footprint (centre ± half the edge), deliberately
    # the axis-aligned box of the UNROTATED square: the extent is a viewport
    # hint, not a collision volume.
    # A placed location WITHOUT a scale anchor stretches the bounds by its
    # centre point, so the map extent never misses a location it shows.
    _min_x = _min_z = _max_x = _max_z = None

    def _stretch(x0: float, x1: float, z0: float, z1: float) -> None:
        nonlocal _min_x, _max_x, _min_z, _max_z
        _min_x = x0 if _min_x is None else min(_min_x, x0)
        _max_x = x1 if _max_x is None else max(_max_x, x1)
        _min_z = z0 if _min_z is None else min(_min_z, z0)
        _max_z = z1 if _max_z is None else max(_max_z, z1)

    for loc in list_locations():
        lid = loc.get("id") or ""
        name_by_id[lid] = loc.get("name") or ""
        # ONE geometry source: the footprint decides both the extent and the
        # scale anchor reported in the entry — never a second hand-parse of
        # map3d.plan_width_m (which would disagree on a width <= 0).
        _fp = placed_footprint(loc)
        if _fp is not None:
            _cx, _cz, _w, _ = _fp
            _half = _w / 2.0
            _stretch(_cx - _half, _cx + _half, _cz - _half, _cz + _half)
        elif loc.get("pos_x") is not None and loc.get("pos_z") is not None:
            _cx, _cz = float(loc["pos_x"]), float(loc["pos_z"])
            _stretch(_cx, _cx, _cz, _cz)
        if not _visible(loc):
            continue
        visible_ids.add(lid)
        # The footprint edge is hoisted out of map3d: it is the scale anchor
        # every map client needs, and none of them should have to dig for it.
        # None whenever the geometry has no usable anchor.
        _width = _fp[2] if _fp is not None else None
        entry = {
            "id": lid,
            "name": loc.get("name") or "",
            "pos_x": loc.get("pos_x"),
            "pos_z": loc.get("pos_z"),
            "yaw_deg": float(loc.get("yaw_deg") or 0.0),
            "plan_width_m": _width,
            # A transit tile (a road cell) is walked THROUGH, never travelled
            # TO — the flag lets a client's destination list drop them, the
            # way the LLM's target list does (movement/blocks.py). Same field
            # for the map itself: a road may be drawn differently to a place.
            "passable": bool(loc.get("passable")),
        }
        map3d = loc.get("map3d")
        if isinstance(map3d, dict) and map3d:
            entry["map3d"] = map3d
        # Derived floors fallback: map3d.style/floors only matter for the
        # client's PROCEDURAL rendering (no building model). Without an
        # explicit floors value the storey count comes from the room layouts
        # (highest above-ground level + 1) — one field less to maintain.
        if "floors" not in (entry.get("map3d") or {}):
            _levels = [int((r.get("layout") or {}).get("level") or 0)
                       for r in (loc.get("rooms") or [])
                       if isinstance(r, dict) and r.get("layout")]
            _top = max([l for l in _levels if l >= 0], default=None)
            if _top is not None:
                entry["map3d"] = {**(entry.get("map3d") or {}), "floors": _top + 1}
        # Layout signature (AV3D-2 addendum): a running client loads
        # /world/locations only once — this bump tells it that something which
        # SHAPES THE SCENE of this location changed, so it can re-fetch
        # specifically. Room layouts alone were not enough (E5 finding B11):
        # the scene payload is shaped by ``map3d`` just as much — boundary
        # openings drawn in the floor-plan editor, rotation, size,
        # tile_rotation, plan_width_m, storey_height_m, floors. A gate drawn
        # into the boundary changed nothing a running client could see.
        # ``entry["map3d"]`` is the sanitized object (sanitized on save) plus
        # the derived floors — deliberately the SAME object the entry ships,
        # never a second sanitize pass.
        _lay_rooms = [(r.get("id"), r.get("layout"))
                      for r in (loc.get("rooms") or [])
                      if isinstance(r, dict) and r.get("layout")]
        _lay_map3d = entry.get("map3d") or {}
        if _lay_rooms or _lay_map3d:
            import hashlib as _hashlib
            import json as _json
            entry["layout_sig"] = _hashlib.md5(_json.dumps(
                [_lay_rooms, _lay_map3d],
                sort_keys=True, default=str).encode()).hexdigest()[:10]
        locations.append(entry)

    # The painted map is part of the world frame too (E4 finding B7). Without
    # this a largely painted world with few placed locations gets cropped to
    # their box by everything that follows the frame (base plane, fog blanket,
    # camera fit, minimap). Each area contributes the axis-aligned box of its
    # polygon; malformed or non-finite points are skipped rather than poisoning
    # the extent with NaN.
    for _area in list_areas():
        for _pt in (_area.get("polygon") or []):
            if not isinstance(_pt, (list, tuple)) or len(_pt) < 2:
                continue
            try:
                _px, _pz = float(_pt[0]), float(_pt[1])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(_px) and math.isfinite(_pz)):
                continue
            _stretch(_px, _px, _pz, _pz)

    world_bounds = ({"min_x": round(_min_x, 2), "min_z": round(_min_z, 2),
                     "max_x": round(_max_x, 2), "max_z": round(_max_z, 2)}
                    if _min_x is not None else None)

    # Journeys are a pure function of the GAME clock — read it ONCE for the
    # whole payload so every character in one response shares the same now.
    from app.core.timeutils import game_now, game_speed_factor, to_world_tz
    from app.core.travel_engine import (get_journey, journey_state,
                                        segment_pace_m_s)
    _now_game = game_now()
    _factor = game_speed_factor()

    characters = []
    for name in list_available_characters():
        loc_id = get_character_current_location(name) or ""
        pos = get_character_pos(name)
        if not loc_id and pos is None:
            continue  # offmap (e.g. avatar-only & uncontrolled) -> not on the map
        if not loc_id:
            # Wilderness: a free point outside every footprint is a legal
            # place to be. Under fog only the avatar itself is shown there —
            # the sight-radius rule that lets it see OTHERS out in the open
            # lands with E6.
            if fogged and name != avatar:
                continue
        # The avatar always sees itself; everyone else only where the avatar
        # can look. Standing in an unknown place hides a character entirely.
        elif fogged and name != avatar and loc_id not in visible_ids:
            continue
        mt = get_movement_target(name) or ""
        prof = get_character_profile_image(name) or ""
        activity = get_effective_activity(name) or ""
        # The DISPLAY text above, the render KEY here — the animation is
        # resolved from the catalog key, never from the free-text flavor.
        pose_key = get_effective_pose_key(name) or ""
        # AV3D-6: which clip a 3D figure plays. The KIND comes from the pose
        # catalog entry's `animation`, the SET from the character (its clip
        # family: lady/man/dog/…). Both may be empty — then the client keeps
        # guessing from the text, exactly as before.
        # Travel is deliberately NOT forced to "walk": the activity is
        # reported honestly, the client has movement_target_id anyway.
        # The set chain, most specific first: explicit attribute, then the one
        # derived from the character (animal / female / male). The client walks
        # it per kind and only falls back to the plain <kind>.fbx when neither
        # set has that clip — an explicit set may be incomplete.
        # ONE profile load per character, shared by the set chain and the
        # height — this loop runs per character on every worldmap request.
        try:
            from app.models.character import get_character_profile as _gcp
            _prof = _gcp(name) or {}
        except Exception:
            _prof = {}
        anim_sets = resolve_animation_sets(name, profile=_prof)
        # Active journey (or None), § A11: the metre polyline plus the walked
        # distance let a client interpolate the figure between two polls
        # instead of teleporting it. Reads the profile loaded above — no
        # second load on this hot endpoint. Isolated like the ticker's
        # per-character block: one malformed journey dict degrades to
        # travel=null, it never breaks the whole worldmap.
        travel = None
        try:
            # NOTE: this reader can WRITE — a stored v1 journey (cell path) is
            # discarded here together with its movement target, once, on the
            # first read after the format change (travel_engine.get_journey).
            _j = get_journey(name, profile=_prof)
            if _j:
                _st = journey_state(_j["waypoints"], _j["started_at_game"],
                                    _now_game)
                # The pace the journey was STARTED with (world setting at that
                # moment) — a later setting change never re-times it.
                _speed = float(_j.get("speed_m_s") or 0.0)
                # …and the pace this very segment is baked at (terrain).
                _pace = segment_pace_m_s(_j["waypoints"], _st)
                travel = {
                    "target_id": _j["target"],
                    # x/z ONLY — the baked cumulative game seconds (t_cum) are
                    # server-internal. A client walks the line by DISTANCE
                    # (progress_m), never by re-deriving the timing.
                    #
                    # FOG (§ A12): the route ENDS at the target's opening, so
                    # it is a metre-exact map marker for a place the avatar
                    # may not know — a far worse leak than the opaque
                    # target_id. Under fog only the avatar gets its own
                    # waypoints; for everyone else the field is null and the
                    # figure is drawn at its `pos` (which the fog already
                    # limits to visible locations).
                    "waypoints": ([[round(float(w[0]), 2), round(float(w[1]), 2)]
                                   for w in _j["waypoints"]]
                                  if (not fogged or name == avatar) else None),
                    "progress_m": _st["progress_m"],
                    "total_m": _st["total_m"],
                    # Same instant, WORLD-timezone offset: clients slice the
                    # HH:MM out of this, which must be game wall-clock — the
                    # engine stores the stamp in UTC (§ A11).
                    "eta_game": to_world_tz(_st["eta_game"]).isoformat(),
                    # The journey's GAME pace as a REAL-seconds one — null on
                    # a frozen world (factor 0): nothing moves, so nothing may
                    # extrapolate. Successor of v1's cell_seconds_real, with
                    # the factor on the other side: a DURATION divides by it,
                    # a SPEED (metres per second) multiplies.
                    "speed_m_s_real": (round(_speed * _factor, 4)
                                       if _factor > 0 and _speed > 0 else None),
                    # The pace of the segment being walked RIGHT NOW (§ A11,
                    # E4): the terrain speed_factor sits in the baked stamps,
                    # not in speed_m_s, so THIS is what a client extrapolates
                    # with; speed_m_s_real above stays the nominal fallback.
                    # null on a frozen clock, after the arrival and for a
                    # degenerate segment — the three cases where the number
                    # would be a lie.
                    "pace_m_s_real": (round(_pace * _factor, 4)
                                      if _factor > 0 and _pace else None),
                }
        except Exception as e:
            travel = None
            # debug, not warning: this endpoint is polled every few seconds
            # per client — a broken journey would flood the log at warning
            # level for as long as it exists.
            logger.debug("travel payload failed for %s: %s", name, e)
        # Body height in cm — the 3D client scales the figures against each
        # other with it (a 155 cm character must not tower over a 190 cm one).
        # None when unset: the client keeps its own default scale.
        try:
            from app.core.height import height_cm as _height_cm
            cm = _height_cm(_prof)
        except Exception:
            cm = None
        # The travel target itself stays in the payload (the client draws the
        # direction), but an unknown destination stays NAMELESS — otherwise
        # the fog would leak place names through the roster.
        target_name = name_by_id.get(mt, "") or mt
        if fogged and mt and mt not in visible_ids:
            target_name = ""
        characters.append({
            "name": name,
            "location_id": loc_id,
            # Free metre point, or null when the character has none (its
            # location is unplaced). Clients place the figure by `pos` and
            # only fall back to the location centre when it is null.
            "pos": pos,
            "height_cm": cm,
            "room_id": get_character_current_room(name) or "",
            "activity": activity,
            "activity_animation": resolve_pose_animation(pose_key),
            "animation_set": (anim_sets[0] if anim_sets else ""),
            "animation_sets": anim_sets,
            "mood": get_character_current_feeling(name) or "",
            "movement_target_id": mt,
            "movement_target_name": target_name,
            "travel": travel,
            "avatar_url": (f"/characters/{name}/images/{prof}" if prof else ""),
        })

    events_by_location = {}
    for ev in list_events():
        if ev.get("resolved"):
            continue
        cat = ev.get("category") or ""
        if cat not in ("disruption", "danger"):
            continue
        lid = ev.get("location_id") or ""
        if not lid:
            continue
        if fogged and lid not in visible_ids:
            continue
        events_by_location.setdefault(lid, []).append({
            "category": cat,
            "text": ev.get("text") or "",
        })

    return {
        "avatar": avatar,
        "current_location_id": (get_character_current_location(avatar) if avatar else ""),
        "locations": locations,
        "characters": characters,
        "events_by_location": events_by_location,
        "world_bounds": world_bounds,
        # Signature of the painted terrain (areas + world type rows), read
        # ONCE per payload: when it changes, clients refetch /play/terrain.
        "terrain_sig": terrain_sig(),
        "fogged": fogged,
    }


def _sanitize_map3d(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce the optional 3D-map metadata object (AV3D-1).

    Consumed by external 3D map clients; the 2D UI stores/edits but never
    renders it. Unknown keys are dropped, invalid values skipped; an empty
    result means "unset"."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    try:
        floors = int(raw.get("floors"))
        if floors > 0:
            out["floors"] = floors
    except (TypeError, ValueError):
        pass
    fp = raw.get("footprint")
    if isinstance(fp, (list, tuple)) and len(fp) == 2:
        try:
            w, d = int(fp[0]), int(fp[1])
            if w > 0 and d > 0:
                out["footprint"] = [w, d]
        except (TypeError, ValueError):
            pass
    for key in ("style", "color"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    # Building placement on the map tile (docs/schnittstellen-3d.md):
    # rotation = yaw in degrees (explicit 0 is meaningful — absent falls back
    # to map_rotation_2d on the client), size = the model's share of the
    # location's reference square (]0, 1]; 1 = edge to edge, absent = 1).
    # A model can no longer be LARGER than its location — a location that
    # needs more room is WIDER (plan_width_m), which keeps the promise
    # "plan edge == model edge".
    rot = raw.get("rotation")
    if rot is not None and f"{rot}".strip() != "":
        try:
            out["rotation"] = int(round(float(rot))) % 360
        except (TypeError, ValueError):
            pass
    size = raw.get("size")
    if size is not None and f"{size}".strip() != "":
        try:
            s = float(size)
            if 0 < s <= 1:
                out["size"] = round(s, 3)
        except (TypeError, ValueError):
            pass
    # Tile rotation (contract v5.2 Nr. 15): 90 / 180 / 270 degrees clockwise,
    # anything else dropped (absent = unrotated). This does NOT rotate the
    # stored plan — it rotates the COMPOSED scene payload around the tile
    # centre, so ONE template location (a road running east–west) can be
    # cloned onto several map cells with each clone facing a different way.
    # The floor-plan editor keeps editing the template in its base
    # orientation; both renderers stay dumb.
    trot = raw.get("tile_rotation")
    if trot is not None and f"{trot}".strip() != "":
        try:
            snapped = int(round(float(trot) / 90.0)) * 90 % 360
        except (TypeError, ValueError):
            snapped = 0
        if snapped in (90, 180, 270):
            out["tile_rotation"] = snapped
    # ``extent_m`` — the world-metre size of the reference square — is GONE
    # with E4: the reference square IS the footprint, so its edge is
    # ``plan_width_m`` and k = 1 (scene_recipe.derive_scalars). Nothing reads
    # the field any more, and it is not kept here either: a location saved
    # once drops it.
    # The width of the location in metres — THE scale anchor and the ONE
    # length everything derives from: the footprint on the world map
    # (§ A1.1), the reference square of the scene, room rects, figures
    # (1.70 m), props and the storey height. Absent = no anchor; floor-plan
    # geometry cannot be saved (see _require_scale_anchor).
    pw = raw.get("plan_width_m")
    if pw is not None and f"{pw}".strip() != "":
        try:
            v = float(pw)
            if 0.5 <= v <= 500:
                out["plan_width_m"] = round(v, 2)
        except (TypeError, ValueError):
            pass
    # Storey height in REAL metres — stacks the room-layout levels. One dial
    # in the same unit as every other length (× k at render time); it
    # replaced the pair "model height ÷ model storeys" (real) and
    # "level_height" (world metres), which were the last per-axis scaling
    # inputs. Absent = 3.
    sh = raw.get("storey_height_m")
    if sh is not None and f"{sh}".strip() != "":
        try:
            v = float(sh)
            if 0.5 <= v <= 50:
                out["storey_height_m"] = round(v, 2)
        except (TypeError, ValueError):
            pass
    # Building outline (AV3D-12): a drawn polygon replacing the rectangle —
    # points as fractions of the 8×8 reference square (auto-closed), the
    # client renders floor plates + walls per used level from it.
    ol = raw.get("outline")
    if isinstance(ol, list):
        pts = []
        for pt in ol[:64]:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                continue
            try:
                pts.append([round(min(max(float(pt[0]), 0.0), 1.0), 4),
                            round(min(max(float(pt[1]), 0.0), 1.0), 4)])
            except (TypeError, ValueError):
                continue
        if len(pts) >= 3:
            out["outline"] = pts
    # Elevator position (AV3D-12): placed once, valid for ALL levels — the
    # client builds a shaft with a platform per level.
    ev = raw.get("elevator")
    if isinstance(ev, (list, tuple)) and len(ev) == 2:
        try:
            out["elevator"] = [round(min(max(float(ev[0]), 0.0), 1.0), 4),
                               round(min(max(float(ev[1]), 0.0), 1.0), 4)]
        except (TypeError, ValueError):
            pass
    # Floor texture per LEVEL: surface-texture kind for each storey's floor
    # plate ({"0": "parquet", "-1": "stone"}). A room's own surfaces.floor
    # overrides it for the room area only — this fills the REST of the plate
    # (rooms rarely cover a whole storey).
    lf = raw.get("level_floors")
    if isinstance(lf, dict):
        floors: Dict[str, str] = {}
        for key, val in list(lf.items())[:32]:
            try:
                lvl = int(float(key))
            except (TypeError, ValueError):
                continue
            if isinstance(val, str) and val.strip():
                floors[str(lvl)] = val.strip()[:60]
        if floors:
            out["level_floors"] = floors
    # Wall texture of the WHOLE building shell: ONE surface-texture kind for
    # every contour wall — the wall counterpart of level_floors. Deliberately
    # not per level (decision 2026-07-27): one shell, one kind. A room's own
    # surfaces.wall still wins wherever a room wall owns the contour stretch.
    wk = raw.get("wall_kind")
    if isinstance(wk, str) and wk.strip():
        out["wall_kind"] = wk.strip()[:60]
    # Area location (plan-area-locations.md): the location model STAYS in the
    # interior view instead of fading out — the building outline and any
    # indoor rooms placed outside it are cut out of it, outdoor rooms outside
    # it become walkable zones ON its surface. Only set when true; absent =
    # today's behaviour (single building, model fades).
    if bool(raw.get("area_model")):
        out["area_model"] = True
    # Detail scene (plan-area-detail-scenes.md): ON TOP of area_model — the
    # location model becomes a FADING shell (display "shell_area") and the
    # rooms compose like a building interior (plates/textures instead of
    # cutouts/overlay zones). Only set when true; meaningless without
    # area_model, so it is dropped there.
    if out.get("area_model") and bool(raw.get("area_detail")):
        out["area_detail"] = True
    # Terrain relief (plan-area-detail-scenes.md, contract v5.2 Nr. 14): a
    # deterministic height field over the reference square, so a detail scene
    # is not a billiard table. Only meaningful ON TOP of a detail scene —
    # without ``area_detail`` there is no composed ground to lift and no
    # relief plates to drape, so it is dropped there (same gate style as
    # area_detail itself, which already implies area_model). ``amplitude_m``
    # is REAL metres (× k when composing); ``seed`` is mandatory — a relief
    # without a stored seed would re-roll the whole terrain on every edit.
    # ``wave_m`` is the second axis: how WIDE one swell is, also in REAL
    # metres (1…200 — narrower than a stride is noise, wider than a couple of
    # map tiles is a single slope). It is optional; without it the composer
    # uses the default grid, which is the field every location had before the
    # wave width existed.
    rel = raw.get("relief")
    if out.get("area_detail") and isinstance(rel, dict):
        try:
            amplitude = float(rel.get("amplitude_m"))
            seed = int(rel.get("seed")) & 0xFFFFFFFF
        except (TypeError, ValueError):
            amplitude = None
        if amplitude is not None and 0.05 <= amplitude <= 5.0:
            entry: Dict[str, Any] = {"amplitude_m": round(amplitude, 2),
                                     "seed": seed}
            try:
                wave = float(rel.get("wave_m"))
            except (TypeError, ValueError):
                wave = None
            if wave is not None and 1.0 <= wave <= 200.0:
                entry["wave_m"] = round(wave, 2)
            out["relief"] = entry
    # Boundary openings (plan-area-detail-scenes.md): pass-throughs at the
    # LOCATION edge (a road crossing the cell east–west = two entries).
    # Geometry + room link only — entry_room stays the gameplay gate. The
    # reference square is a rectangle by definition, so edges are letters,
    # never polygon indices; ``at`` follows the room-opening convention
    # (left→right on N/S, top→bottom on E/W). ``room`` is a format check,
    # never an existence check (same rule as prop ids).
    # The WIDTH lies on that edge, so the edge is its maximum: the reference
    # square is a square, hence ``plan_width_m`` metres per side (a café in
    # the middle of a city cell is entered along its whole edge, not through
    # a 10 m slot). Without the anchor no edge length is known and 10 m
    # stands in. Out of range is CLAMPED, never dropped — a saved opening
    # that silently disappears costs the author their work.
    max_width_m = float(out.get("plan_width_m") or 10.0)
    bo = raw.get("boundary_openings")
    if isinstance(bo, list):
        entries = []
        for op in bo[:8]:
            if not isinstance(op, dict):
                continue
            edge = op.get("edge")
            if not (isinstance(edge, str)
                    and edge.strip().upper() in ("N", "S", "E", "W")):
                continue
            try:
                at = float(op.get("at"))
                width_m = float(op.get("width_m"))
            except (TypeError, ValueError):
                continue
            entry: Dict[str, Any] = {
                "edge": edge.strip().upper(),
                "at": round(min(max(at, 0.0), 1.0), 4),
                "width_m": round(min(max(width_m, 0.5), max_width_m), 3),
                "type": "passage",
            }
            room = op.get("room")
            if isinstance(room, str) and room.strip():
                entry["room"] = room.strip()[:64]
            entries.append(entry)
        if entries:
            out["boundary_openings"] = entries
    return out


def _sanitize_room_layout(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce a room's floor-plan placement (AV3D-2).

    Consumed by external 3D clients; the 2D UI stores/edits but never renders
    it. A layout counts as set when x/y/w/d are all valid (fractions of the
    building footprint, top-left corner + size); ``level`` defaults to 0 and
    ``rotation`` (degrees yaw) is optional. Optional too: ``markers``
    (figure snap spots),
    ``surfaces`` ({floor?, wall?} surface-texture kinds), ``openings``
    (doors / windows / passages, see _sanitize_opening), ``outline``
    (drawn room hull) and ``props`` (prop-library placements). Empty result
    means "unset" → client auto-grid.

    ``outline`` = polygon points as fractions of the room BBOX, auto-closed
    (no repeated closing point), winding clockwise in screen coordinates
    (y down), bbox spanning [0,1]². Absent = the rectangle itself, i.e. the
    implicit unit square with edge indices 0=N, 1=E, 2=S, 3=W. x/y/w/d ALWAYS
    carry the derived bbox, so a client that only knows rectangles keeps
    working.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    try:
        x = float(raw.get("x"))
        y = float(raw.get("y"))
        w = float(raw.get("w"))
        d = float(raw.get("d"))
    except (TypeError, ValueError):
        return {}
    if not (0 < w <= 1 and 0 < d <= 1):
        return {}
    out["x"] = round(min(max(x, 0.0), 1.0), 4)
    out["y"] = round(min(max(y, 0.0), 1.0), 4)
    out["w"] = round(w, 4)
    out["d"] = round(d, 4)
    # Drawn room hull (plan-room-props.md): a polygon that replaces the plain
    # rectangle. The points are BBOX-local fractions and the bbox is x/y/w/d —
    # a hand-posted payload whose points do not span [0,1]² is renormalized
    # here and the difference folded into x/y/w/d, so those ALWAYS describe the
    # real bounding box.
    ol = raw.get("outline")
    if isinstance(ol, list) and 3 <= len(ol) <= 32:
        pts: List[List[float]] = []
        ok = True
        for pt in ol:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                ok = False
                break
            try:
                p = [float(pt[0]), float(pt[1])]
            except (TypeError, ValueError):
                ok = False
                break
            prev = pts[-1] if pts else None
            if prev and abs(p[0] - prev[0]) < 1e-6 and abs(p[1] - prev[1]) < 1e-6:
                continue
            pts.append(p)
        # The hull is auto-closed — an explicit closing point is redundant.
        while len(pts) > 1 and abs(pts[-1][0] - pts[0][0]) < 1e-6 \
                and abs(pts[-1][1] - pts[0][1]) < 1e-6:
            pts.pop()
        if ok and len(pts) >= 3:
            shoelace = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                           - pts[(i + 1) % len(pts)][0] * pts[i][1]
                           for i in range(len(pts)))
            if abs(shoelace) / 2 >= 1e-4:
                # Curved edges (plan-area-detail-scenes.md): the outline stays
                # the plain CONTROL polygon; curves are the parallel sparse
                # list ``outline_curves`` (one quadratic-bezier control point
                # per edge, bbox-local like the points). They only survive
                # when no outline point was dropped above — a dropped point
                # would silently shift every edge index under them.
                curves = curve_map(raw.get("outline_curves"), len(pts)) \
                    if len(pts) == len(ol) else {}
                # The bbox invariant covers the DELIVERED geometry: fold over
                # the TESSELLATED points, so a curve bulging past the control
                # polygon still ends up inside x/y/w/d.
                shape, _ = tessellate(
                    pts, [{"edge": e, "c": list(c)} for e, c in curves.items()])
                min_u = min(p[0] for p in shape)
                max_u = max(p[0] for p in shape)
                min_v = min(p[1] for p in shape)
                max_v = max(p[1] for p in shape)
                span_u = max_u - min_u
                span_v = max_v - min_v
                folded = True
                if (abs(min_u) > 1e-6 or abs(max_u - 1) > 1e-6
                        or abs(min_v) > 1e-6 or abs(max_v - 1) > 1e-6):
                    new_w = round(out["w"] * span_u, 4)
                    new_d = round(out["d"] * span_v, 4)
                    # Folding must keep the layout invariant 0 < w/d <= 1 —
                    # points far outside the bbox would inflate it past the
                    # footprint, so such an outline is dropped, not clamped.
                    if (span_u > 0 and span_v > 0
                            and 0 < new_w <= 1 and 0 < new_d <= 1):
                        out["x"] = round(min(max(out["x"] + min_u * out["w"], 0.0), 1.0), 4)
                        out["y"] = round(min(max(out["y"] + min_v * out["d"], 0.0), 1.0), 4)
                        out["w"] = new_w
                        out["d"] = new_d
                        pts = [[(p[0] - min_u) / span_u, (p[1] - min_v) / span_v]
                               for p in pts]
                        curves = {e: ((c[0] - min_u) / span_u,
                                      (c[1] - min_v) / span_v)
                                  for e, c in curves.items()}
                    else:
                        folded = False
                if folded:
                    # Clockwise in screen coordinates (y down) = positive
                    # shoelace sum.
                    if shoelace < 0:
                        pts.reverse()
                        # Edge i (v[i]→v[i+1]) becomes edge n-2-i in the
                        # reversed indexing; the control point itself is a
                        # position and stays.
                        n = len(pts)
                        curves = {(n - 2 - e) % n: c for e, c in curves.items()}
                    out["outline"] = [[round(p[0], 4), round(p[1], 4)] for p in pts]
                    if curves:
                        # With endpoints and curve inside the folded [0,1]²
                        # bbox a quadratic control point lies in [-1, 2]
                        # (C = 2·B(½) − (P0+P1)/2) — clamp to that, not to
                        # [0,1]: a road bend's control point legitimately
                        # sits outside the hull.
                        out["outline_curves"] = [
                            {"edge": e,
                             "c": [round(min(max(c[0], -1.0), 2.0), 4),
                                   round(min(max(c[1], -1.0), 2.0), 4)]}
                            for e, c in sorted(curves.items())]
    try:
        out["level"] = int(raw.get("level") or 0)
    except (TypeError, ValueError):
        out["level"] = 0
    rot = raw.get("rotation")
    if rot is not None and f"{rot}".strip() != "":
        try:
            out["rotation"] = int(round(float(rot))) % 360
        except (TypeError, ValueError):
            pass
    # AV3D-12: the room is shown permanently, independent of the interior
    # view — for outdoor rooms that are not part of the building model.
    if raw.get("always_visible"):
        out["always_visible"] = True
    # Diorama clipping (§ B1 ``clip_outline``): opt-in per room — the renderer
    # discards model fragments outside the room's shell, so a diorama that
    # overhangs its floor plan (it scales by its real width, § B2a) is cut
    # at the shell.
    if raw.get("clip_model"):
        out["clip_model"] = True
    # Relief opt-out (v5.2 Nr. 14): this room stays EVEN even when the
    # location carries a terrain relief — a road, a paved square, a clearing.
    # Indoor rooms (not ``always_visible``) are flat anyway, walls need a
    # level floor, so the flag only says anything for outdoor rooms. Only
    # stored when true, like always_visible.
    if raw.get("relief_flat"):
        out["relief_flat"] = True
    # No recipe walls for this room: open zones, pavilions, areas inside an
    # area model. The server then emits no `walls` entries for it at all, so
    # both renderers follow without knowing the flag. Openings stay editor
    # data (the 2D plan keeps drawing them), the plate is unaffected.
    if raw.get("no_walls"):
        out["no_walls"] = True
    # Diorama-model placement IN THE PLAN (2026-07-24): the room's 3D model
    # is positioned like a prop — ``model_at`` = anchor point as fractions of
    # the room rectangle (absent = centred, today's behaviour) and
    # ``model_offset_y`` = height in metres. This REPLACES the per-model
    # sidecar offset for rooms (values migrate by hand; buildings keep their
    # sidecar offsets).
    mat = raw.get("model_at")
    if isinstance(mat, (list, tuple)) and len(mat) == 2:
        try:
            out["model_at"] = [round(min(max(float(mat[0]), 0.0), 1.0), 4),
                               round(min(max(float(mat[1]), 0.0), 1.0), 4)]
        except (TypeError, ValueError):
            pass
    moy = raw.get("model_offset_y")
    if moy is not None and f"{moy}".strip() != "":
        try:
            out["model_offset_y"] = round(max(-25.0, min(25.0, float(moy))), 3)
        except (TypeError, ValueError):
            pass
    # Where the room's FLOOR sits, in REAL metres relative to its storey
    # (± , × k at render time). Inside a building every room shares the
    # storey and this stays 0; it earns its keep where a room cuts a hole
    # into a LOCATION model — terrain is not flat, so the hut halfway up the
    # slope needs its floor at the height the ground has THERE (user finding
    # 2026-07-28, Willowbrook). Everything in the room rides along: plate,
    # walls, props, markers and the diorama.
    fo = raw.get("floor_offset_y")
    if fo is not None and f"{fo}".strip() != "":
        try:
            v = round(max(-25.0, min(25.0, float(fo))), 3)
            if v:
                out["floor_offset_y"] = v
        except (TypeError, ValueError):
            pass
    # Animation markers (schnittstellen-3d.md): optional spots in the room a
    # figure with a matching active animation snaps to. ``at`` = fraction of
    # the ROOM rectangle, ``animation`` = a clip kind from the OPEN clip
    # vocabulary (nothing hardcoded — the editor offers what exists).
    # Optional per marker: ``rotation`` = the figure's facing in degrees
    # (0 = south, 90 = east, 180 = north, 270 = west; absent = the client's
    # face-the-neighbours default), ``offset_y`` (metres, ± — ADDITIVE to
    # the client-sampled seat height under the marker) and the two TILT axes
    # ``tilt``/``roll`` (degrees, ±90): a figure lying on a slope or leaning
    # against something is not upright, and facing alone cannot say that
    # (user finding 2026-07-28 — lying slightly angled on the sand).
    mk = raw.get("markers")
    if isinstance(mk, list):
        markers = []
        for m in mk:
            if not isinstance(m, dict):
                continue
            at = m.get("at")
            anim = str(m.get("animation") or "").strip()
            if not anim or not isinstance(at, (list, tuple)) or len(at) != 2:
                continue
            try:
                entry = {
                    "at": [round(min(max(float(at[0]), 0.0), 1.0), 4),
                           round(min(max(float(at[1]), 0.0), 1.0), 4)],
                    "animation": anim,
                }
            except (TypeError, ValueError):
                continue
            rot = m.get("rotation")
            if rot is not None and f"{rot}".strip() != "":
                try:
                    entry["rotation"] = int(round(float(rot))) % 360
                except (TypeError, ValueError):
                    pass
            off = m.get("offset_y")
            if off is not None and f"{off}".strip() != "":
                try:
                    entry["offset_y"] = round(max(-5.0, min(5.0, float(off))), 3)
                except (TypeError, ValueError):
                    pass
            for axis in ("tilt", "roll"):
                val = m.get(axis)
                if val is None or f"{val}".strip() == "":
                    continue
                try:
                    deg = round(max(-90.0, min(90.0, float(val))), 1)
                except (TypeError, ValueError):
                    continue
                if deg:
                    entry[axis] = deg
            markers.append(entry)
        if markers:
            out["markers"] = markers[:50]
    # Room shell (plan-room-props.md): per-room surface kinds + openings. Both
    # are deterministic + admin-edited (no LLM); the client derives walls from
    # the rectangle/polygon edges × storey height and splits them around the
    # openings.
    surf = raw.get("surfaces")
    if isinstance(surf, dict):
        surfaces: Dict[str, str] = {}
        for key in ("floor", "wall"):
            val = surf.get(key)
            if isinstance(val, str) and val.strip():
                surfaces[key] = val.strip()
        if surfaces:
            out["surfaces"] = surfaces
    ops = raw.get("openings")
    if isinstance(ops, list):
        openings = []
        for op in ops:
            clean = _sanitize_opening(op)
            if clean:
                openings.append(clean)
        if openings:
            out["openings"] = openings[:50]
    # An integer edge is a polygon edge INDEX — it only exists if the hull has
    # that many edges (n points = n edges; without an outline the implicit unit
    # square has 4). Letter edges ('N'|'S'|'E'|'W') are untouched. Openings on
    # CURVED edges are rejected (v1 decision, plan-area-detail-scenes.md) —
    # boundary pass-throughs handle the road case.
    if out.get("openings"):
        edge_count = len(out["outline"]) if out.get("outline") else 4
        curved = {c["edge"] for c in out.get("outline_curves") or []}
        kept = [o for o in out["openings"]
                if not (isinstance(o.get("edge"), int)
                        and (o["edge"] >= edge_count or o["edge"] in curved))]
        if kept:
            out["openings"] = kept
        else:
            out.pop("openings")
    # Prop placements (plan-room-props.md): the room's furnishing as single
    # objects from the prop library. REAL-SIZE RULE — a placement never
    # scales the prop; the client sizes it from the PROP's own dims × the
    # plan's scale factor, so only position/yaw/height live here.
    # A placement may additionally SCATTER (plan-area-detail-scenes.md,
    # 2026-08-02 redesign: scatter is a placement property, not a separate
    # room list): ``scatter_count`` copies of the prop are thrown over the
    # room area from ``scatter_seed`` at compose time; the placement itself
    # stays as the manually positioned anchor. Σ scatter_count ≤ 120 per
    # room, on top of the ≤ 100 manual placements.
    pr = raw.get("props")
    if isinstance(pr, list):
        from app.core.props import safe_prop_id
        placements = []
        scatter_total = 0
        for p in pr:
            if not isinstance(p, dict):
                continue
            # Format check only, NEVER an existence check: the world lives in
            # the DB, props are files — a dangling id renders as a placeholder
            # on the client instead of silently losing the placement.
            pid = safe_prop_id(str(p.get("prop_id") or ""))
            at = p.get("at")
            if not pid or not isinstance(at, (list, tuple)) or len(at) != 2:
                continue
            try:
                entry: Dict[str, Any] = {
                    "prop_id": pid,
                    "at": [round(min(max(float(at[0]), 0.0), 1.0), 4),
                           round(min(max(float(at[1]), 0.0), 1.0), 4)],
                }
            except (TypeError, ValueError):
                continue
            yaw = p.get("yaw")
            if yaw is not None and f"{yaw}".strip() != "":
                try:
                    v = round(float(yaw) % 360, 1)
                    entry["yaw"] = int(v) if float(v).is_integer() else v
                except (TypeError, ValueError):
                    pass
            off = p.get("offset_y")
            if off is not None and f"{off}".strip() != "":
                try:
                    entry["offset_y"] = round(max(-5.0, min(5.0, float(off))), 3)
                except (TypeError, ValueError):
                    pass
            # Scatter fields survive only complete (count + seed) and within
            # the room budget — a truncated count keeps what still fits.
            try:
                sc_count = int(p.get("scatter_count"))
                sc_seed = int(p.get("scatter_seed")) & 0xFFFFFFFF
            except (TypeError, ValueError):
                sc_count = 0
                sc_seed = 0
            if sc_count >= 1:
                sc_count = min(sc_count, 120 - scatter_total)
                if sc_count >= 1:
                    entry["scatter_count"] = sc_count
                    entry["scatter_seed"] = sc_seed
                    scatter_total += sc_count
                    sp = p.get("scatter_spacing_m")
                    if sp is not None and f"{sp}".strip() != "":
                        try:
                            v = round(max(0.0, min(5.0, float(sp))), 2)
                            if v:
                                entry["scatter_spacing_m"] = v
                        except (TypeError, ValueError):
                            pass
            placements.append(entry)
        if placements:
            out["props"] = placements[:100]
    return out


def _sanitize_opening(raw: Any) -> Optional[Dict[str, Any]]:
    """Whitelist + coerce ONE wall opening (door / window / passage). Returns
    None for an invalid entry so the caller can drop it individually.

    - ``edge``: 'N'|'S'|'E'|'W' (rectangle) OR an int >= 0 (polygon edge index),
    - ``at``: 0..1 along the edge (centre of the opening),
    - ``width_m`` / ``height_m``: 0.4..10 m,
    - ``sill_m``: 0..3 m (door = 0, window ≈ 0.9), default 0,
    - ``type``: 'door' | 'window' | 'passage',
    - ``to`` (optional str): connectivity target (room id or 'outside'),
    - ``prop_id`` (optional str): a frame/leaf prop scaled onto the opening.
    """
    if not isinstance(raw, dict):
        return None
    edge = raw.get("edge")
    edge_val: Any = None
    if isinstance(edge, str) and edge.strip().upper() in ("N", "S", "E", "W"):
        edge_val = edge.strip().upper()
    else:
        try:
            ei = int(edge)
        except (TypeError, ValueError):
            return None
        if ei < 0:
            return None
        edge_val = ei
    typ = str(raw.get("type") or "").strip().lower()
    if typ not in ("door", "window", "passage"):
        return None
    try:
        at = float(raw.get("at"))
        width_m = float(raw.get("width_m"))
        height_m = float(raw.get("height_m"))
    except (TypeError, ValueError):
        return None
    if not (0.4 <= width_m <= 10.0 and 0.4 <= height_m <= 10.0):
        return None
    sill = raw.get("sill_m", 0)
    try:
        sill_m = float(sill) if sill is not None and f"{sill}".strip() != "" else 0.0
    except (TypeError, ValueError):
        sill_m = 0.0
    sill_m = min(max(sill_m, 0.0), 3.0)
    out: Dict[str, Any] = {
        "edge": edge_val,
        "at": round(min(max(at, 0.0), 1.0), 4),
        "width_m": round(width_m, 3),
        "height_m": round(height_m, 3),
        "sill_m": round(sill_m, 3),
        "type": typ,
    }
    to = raw.get("to")
    if isinstance(to, str) and to.strip():
        out["to"] = to.strip()
    prop_id = raw.get("prop_id")
    if isinstance(prop_id, str) and prop_id.strip():
        out["prop_id"] = prop_id.strip()
    return out


def _sanitize_rooms_layout(rooms: Any) -> Any:
    """Apply the layout sanitizer to every room dict in place (rooms pass
    through add_location verbatim otherwise). Invalid layouts are dropped.

    THE GROUND ROOM NEVER CARRIES A LAYOUT. It is the location's open surface,
    and its geometry comes from the scene recipe, not from a floor plan — a
    layout on it would put ``GROUND_ROOM_ID`` into the recipe's rooms and give
    it walls and doorways, which the contract says it has none of. The
    floor-plan editor already refuses to draw one; this is the same refusal for
    a hand-made API call.
    """
    if not isinstance(rooms, list):
        return rooms
    for room in rooms:
        if not isinstance(room, dict) or "layout" not in room:
            continue
        if room.get("id") == GROUND_ROOM_ID:
            room.pop("layout", None)
            continue
        lay = _sanitize_room_layout(room.get("layout"))
        if lay:
            room["layout"] = lay
        else:
            room.pop("layout", None)
    return rooms


# The layout fields that carry REAL-WORLD SIZE. Openings, markers and
# surfaces ride along on whatever scale already applies, so editing them is
# not "geometry work" and never trips the scale-anchor requirement.
_LAYOUT_GEOMETRY_KEYS = ("level", "x", "y", "w", "d", "rotation", "outline",
                         "outline_curves", "props", "floor_offset_y")


def _layout_geometry(layout: Any) -> Optional[Dict[str, Any]]:
    """The geometry part of a room layout, or None when the room has none."""
    if not isinstance(layout, dict):
        return None
    return {key: layout.get(key) for key in _LAYOUT_GEOMETRY_KEYS}


def _require_scale_anchor(location_id: str, rooms: Any, map3d: Any,
                          stored: Optional[Dict[str, Any]]) -> None:
    """Reject a save that ADDS or CHANGES floor-plan geometry while the
    location has no scale anchor (Abnahme round 4).

    Without ``map3d.plan_width_m`` a layout has no real size and everything
    derived from it (figure size, prop size, storey height) falls back to a
    meaningless legacy scale. Since 2026-07-28 it is the ONLY anchor — the
    derivation from a model's declared height went with the per-axis
    scaling. Existing data stays saveable: only rooms whose geometry differs
    from the stored one count.
    ``map3d`` is the INCOMING object (the same request may set the anchor);
    None means "unchanged", so the stored one decides.
    """
    if not isinstance(rooms, list):
        return
    before = {}
    for room in (stored or {}).get("rooms") or []:
        if isinstance(room, dict) and room.get("id"):
            before[room["id"]] = _layout_geometry(room.get("layout"))
    changed = False
    for room in rooms:
        if not isinstance(room, dict):
            continue
        geometry = _layout_geometry(room.get("layout"))
        if geometry is not None and geometry != before.get(room.get("id")):
            changed = True
            break
    if not changed:
        return
    effective = _sanitize_map3d(map3d) if map3d is not None \
        else (stored or {}).get("map3d")
    from app.core.location_model3d import has_scale_anchor
    if has_scale_anchor(location_id, effective):
        return
    raise HTTPException(status_code=400, detail=(
        "Room layouts need a scale anchor: set map3d.plan_width_m "
        "(how many REAL metres the location is wide)"))


def create_location_with_extras(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a location from a parsed request body (incl. extra fields)."""
    user_id = data.get("user_id", "").strip()
    location_name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    rooms = data.get("rooms", [])
    image_prompt_day = data.get("image_prompt_day")
    image_prompt_night = data.get("image_prompt_night")
    image_prompt_map = data.get("image_prompt_map")
    image_prompt_map_2d = data.get("image_prompt_map_2d")
    image_prompt_building = data.get("image_prompt_building")
    danger_level = data.get("danger_level")
    event_settings = data.get("event_settings")
    outfit_type = data.get("outfit_type")
    decency = data.get("decency")
    style_hint = data.get("style_hint")
    swim_allowed = data.get("swim_allowed")
    activity_hint = data.get("activity_hint")
    knowledge_item_id = data.get("knowledge_item_id")
    passable = data.get("passable")
    entry_room = data.get("entry_room")
    indoor = data.get("indoor")
    terrain = data.get("terrain")
    map3d = data.get("map3d")
    if not location_name:
        raise HTTPException(status_code=400, detail="Name missing")
    if not isinstance(rooms, list):
        raise HTTPException(status_code=400, detail="rooms must be a list")
    _sanitize_rooms_layout(rooms)
    # add_location updates an EXISTING location of the same name, so the
    # anchor check has to look at that one (a genuinely new location has no
    # building model — only an explicit plan width can anchor it).
    _existing = next((l for l in list_locations()
                      if (l.get("name") or "").lower() == location_name.lower()), None)
    _require_scale_anchor(str((_existing or {}).get("id") or ""), rooms, map3d,
                          _existing)

    location = add_location(location_name, description, rooms=rooms,
                            image_prompt_day=image_prompt_day,
                            image_prompt_night=image_prompt_night,
                            image_prompt_map=image_prompt_map,
                            image_prompt_map_2d=image_prompt_map_2d,
                            image_prompt_building=image_prompt_building)

    # Set extra fields directly in the location
    _has_extra = (danger_level is not None or event_settings is not None
                  or outfit_type is not None or knowledge_item_id is not None
                  or passable is not None
                  or entry_room is not None or indoor is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None
                  or terrain is not None
                  or map3d is not None)
    if _has_extra and location:
        from app.models.world import _load_world_data, _save_world_data
        wdata = _load_world_data()
        for _l in wdata.get("locations", []):
            if _l.get("id") == location.get("id"):
                if danger_level is not None:
                    try:
                        _l["danger_level"] = max(0, min(5, int(danger_level)))
                    except (TypeError, ValueError):
                        pass
                if event_settings is not None:
                    _l["event_settings"] = event_settings
                if outfit_type is not None:
                    _l["outfit_type"] = (outfit_type or "").strip()
                if decency is not None:
                    _v = (decency or "").strip().lower()
                    _l["decency"] = _v if _v in ("public", "private", "nude_ok") else ""
                if style_hint is not None:
                    _l["style_hint"] = (style_hint or "").strip()
                if swim_allowed is not None:
                    _l["swim_allowed"] = bool(swim_allowed)
                if activity_hint is not None:
                    _l["activity_hint"] = (activity_hint or "").strip()
                if knowledge_item_id is not None:
                    _l["knowledge_item_id"] = (knowledge_item_id or "").strip()
                if passable is not None:
                    _l["passable"] = bool(passable)
                if entry_room is not None:
                    _l["entry_room"] = (entry_room or "").strip()
                if indoor is not None:
                    _v = (indoor or "").strip().lower()
                    _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                if terrain is not None:
                    _l["terrain"] = (terrain or "").strip()
                if map3d is not None:
                    _m3 = _sanitize_map3d(map3d)
                    if _m3:
                        _l["map3d"] = _m3
                    else:
                        _l.pop("map3d", None)
                break
        _save_world_data(wdata)
        location = get_location_by_id(location["id"])

    return {"status": "success", "location": location}


def update_location_with_extras(location_id: str,
                                data: Dict[str, Any]) -> Dict[str, Any]:
    """Update a location by id from a parsed request body (incl. extra fields)."""
    user_id = data.get("user_id", "").strip()
    new_name = data.get("name", "").strip()
    description = data.get("description")
    rooms = data.get("rooms")
    image_prompt_day = data.get("image_prompt_day")
    image_prompt_night = data.get("image_prompt_night")
    image_prompt_map = data.get("image_prompt_map")
    image_prompt_map_2d = data.get("image_prompt_map_2d")
    image_prompt_building = data.get("image_prompt_building")
    danger_level = data.get("danger_level")
    event_settings = data.get("event_settings")
    outfit_type = data.get("outfit_type")
    decency = data.get("decency")
    style_hint = data.get("style_hint")
    swim_allowed = data.get("swim_allowed")
    activity_hint = data.get("activity_hint")
    knowledge_item_id = data.get("knowledge_item_id")
    passable = data.get("passable")
    entry_room = data.get("entry_room")
    indoor = data.get("indoor")
    terrain = data.get("terrain")
    map3d = data.get("map3d")

    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    if new_name:
        rename_location(location_id, new_name)

    # Update description, rooms and image prompts if provided
    if rooms is not None:
        _sanitize_rooms_layout(rooms)
        _require_scale_anchor(location_id, rooms, map3d, loc)
    has_updates = any(v is not None for v in [description, rooms, image_prompt_day, image_prompt_night, image_prompt_map, image_prompt_map_2d, image_prompt_building])
    if has_updates:
        loc = get_location_by_id(location_id)
        if loc:
            add_location(loc["name"],
                description if description is not None else loc.get("description", ""),
                rooms=rooms if rooms is not None else loc.get("rooms", []),
                image_prompt_day=image_prompt_day if image_prompt_day is not None else loc.get("image_prompt_day", ""),
                image_prompt_night=image_prompt_night if image_prompt_night is not None else loc.get("image_prompt_night", ""),
                image_prompt_map=image_prompt_map if image_prompt_map is not None else loc.get("image_prompt_map", ""),
                image_prompt_map_2d=image_prompt_map_2d if image_prompt_map_2d is not None else loc.get("image_prompt_map_2d", ""),
                image_prompt_building=image_prompt_building if image_prompt_building is not None else loc.get("image_prompt_building", ""),
                location_id=location_id)  # update by id — unambiguous with duplicate names

    # Set extra fields (incl. knowledge_item_id) directly in the location
    _has_extra = (danger_level is not None or event_settings is not None
                  or outfit_type is not None or knowledge_item_id is not None
                  or passable is not None
                  or entry_room is not None or indoor is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None
                  or terrain is not None
                  or map3d is not None)
    if _has_extra:
        from app.models.world import _load_world_data, _save_world_data
        wdata = _load_world_data()
        for _l in wdata.get("locations", []):
            if _l.get("id") == location_id:
                if danger_level is not None:
                    try:
                        _l["danger_level"] = max(0, min(5, int(danger_level)))
                    except (TypeError, ValueError):
                        pass
                if event_settings is not None:
                    _l["event_settings"] = event_settings
                if outfit_type is not None:
                    _l["outfit_type"] = (outfit_type or "").strip()
                if decency is not None:
                    _v = (decency or "").strip().lower()
                    _l["decency"] = _v if _v in ("public", "private", "nude_ok") else ""
                if style_hint is not None:
                    _l["style_hint"] = (style_hint or "").strip()
                if swim_allowed is not None:
                    _l["swim_allowed"] = bool(swim_allowed)
                if activity_hint is not None:
                    _l["activity_hint"] = (activity_hint or "").strip()
                if knowledge_item_id is not None:
                    _l["knowledge_item_id"] = (knowledge_item_id or "").strip()
                if passable is not None:
                    _l["passable"] = bool(passable)
                if entry_room is not None:
                    _l["entry_room"] = (entry_room or "").strip()
                if indoor is not None:
                    _v = (indoor or "").strip().lower()
                    _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                if terrain is not None:
                    _l["terrain"] = (terrain or "").strip()
                if map3d is not None:
                    _m3 = _sanitize_map3d(map3d)
                    if _m3:
                        _l["map3d"] = _m3
                    else:
                        _l.pop("map3d", None)
                break
        _save_world_data(wdata)

    updated = get_location_by_id(location_id)
    return {"status": "success", "location": updated}


# --- World-level settings ---------------------------------------------------

def build_world_settings_payload() -> Dict[str, Any]:
    """Return world settings (atmosphere + news channel)."""
    from app.models.world import (
        get_world_temperature, get_world_weather,
        get_world_setting,
        WORLD_TEMPERATURE_VALUES, WORLD_WEATHER_VALUES,
    )
    return {
        "world": {
            "temperature": get_world_temperature(),
            "weather": get_world_weather(),
        },
        "news": {
            # Presentation style of the player news channel.
            "style": get_world_setting("news.style", "modern") or "modern",
            "title": get_world_setting("news.title", "") or "",
        },
        "choices": {
            "temperature": list(WORLD_TEMPERATURE_VALUES),
            "weather":     list(WORLD_WEATHER_VALUES),
            "news_style":  ["modern", "newspaper", "flyer"],
        },
    }


def apply_world_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Set world settings from a parsed request body."""
    from app.models.world import (
        set_world_temperature, set_world_weather,
        set_world_setting, WORLD_TEMPERATURE_VALUES, WORLD_WEATHER_VALUES,
    )
    world = data.get("world") or {}
    news = data.get("news") or {}
    if "style" in news:
        v = (news.get("style") or "").strip().lower()
        if v in ("modern", "newspaper", "flyer"):
            set_world_setting("news.style", v)
    if "title" in news:
        set_world_setting("news.title", (news.get("title") or "").strip())
    if "temperature" in world:
        v = (world.get("temperature") or "").strip().lower()
        if v in WORLD_TEMPERATURE_VALUES:
            set_world_temperature(v)
    if "weather" in world:
        v = (world.get("weather") or "").strip().lower()
        if v in WORLD_WEATHER_VALUES:
            set_world_weather(v)
    return {"status": "ok"}


def list_condition_filters() -> Dict[str, Any]:
    """List all filter ids from prompt_filters (shared + world overlay).

    The filter ``id`` is at the same time the canonical condition name:
    as soon as it appears as a tag in the profile (active_conditions), the
    corresponding filter triggers implicitly. An additional ``condition``
    expression on the filter (e.g. ``stamina<10``) acts as a second
    auto-trigger.

    Returns: {"conditions": [{"name": "drunk", "label": "...", "icon": "🍺"}, ...]}
    """
    from app.core.prompt_filters import load_filters
    seen: Dict[str, Dict[str, Any]] = {}
    for f in load_filters():
        if not f.get("enabled", True):
            continue
        fid = (f.get("id") or "").strip().lower()
        if not fid or fid in seen:
            continue
        seen[fid] = {
            "name": fid,
            "label": (f.get("label") or "").strip(),
            "icon": (f.get("icon") or "").strip(),
        }
    return {"conditions": sorted(seen.values(), key=lambda e: e["name"])}


# === Location gallery ===

def build_gallery_payload(location_name: str) -> Dict[str, Any]:
    """List all gallery images of a location (with background status)."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name
    images = list_gallery_images(location_name)
    bg_images = get_background_images(loc_id)
    image_rooms = get_gallery_image_rooms(loc_id)
    image_types = get_gallery_image_types(loc_id)
    image_metas = get_gallery_image_metas(loc_id)
    prompts = get_all_gallery_prompts(loc_id)
    # Rooms for the dropdown in the frontend
    location_rooms = []
    if loc:
        for room in loc.get("rooms", []):
            location_rooms.append({
                "id": room.get("id", ""),
                "name": room.get("name", ""),
            })
    return {
        "images": images,
        "background_images": bg_images,
        "image_prompts": prompts,
        "image_rooms": image_rooms,
        "image_types": image_types,
        "image_metas": image_metas,
        "location_rooms": location_rooms,
        "location": location_name,
    }


def build_imagegen_options() -> Dict[str, Any]:
    """Returns available image-generation backends (without character binding)."""
    from app.core.prompt_adapters import get_target_model

    from app.imagegen.service import get_image_service
    imagegen = get_image_service()
    if not imagegen.enabled:
        return {"options": []}

    options = []
    # Backends (CivitAI, Together, LocalAI, …). Every ENABLED backend is
    # offered — availability is resolved by the server at generation time via
    # match_backend. Do NOT pre-filter on b.available, otherwise a freshly
    # configured / not-yet-probed cloud backend disappears from the
    # "Service (match)" selection.
    for b in imagegen.backends:
        if not b.instance_enabled:
            continue
        # IMAGE options only — video backends have their own selection
        # surface (animate dialog) and must not appear as image targets.
        if getattr(b, "MEDIA_TYPE", "image") != "image":
            continue
        opt = {
            "type": "backend",
            "name": b.name,
            "label": b.name if b.available else f"{b.name} (offline?)",
            "available": b.available,
            # Purpose category (e.g. "inpaint") + default prompt — lets the
            # Fit/Edge dialog offer inpaint backends and prefill the prompt.
            "category": getattr(b, "category", "") or "",
            "image_family": getattr(b, "image_family", "") or "",
            "prompt": getattr(b, "default_prompt", "") or "",
            "ref_slot_count": int(getattr(b, "ref_slot_count", 0) or 0),
            "target_model": get_target_model(
                getattr(b, "image_family", "") or "", getattr(b, "model", "") or ""),
            # Terrain-hint parameter — the dialog only appends the hint if True.
            "terrain_hint": bool(getattr(b, "terrain_hint", False)),
        }
        # Use-case styles resolved for THIS backend (family + model): the
        # dialogs show the style as an editable prompt part, so the FINAL
        # prompt is fully visible before generating (house rule) — submit
        # sets settings_applied and the server prepends nothing.
        from app.core.config import resolve_use_case_style as _rucs
        _styles = {}
        for _uc in ("location", "map", "building", "building_outdoor",
                    "room_model", "room_model_outdoor"):
            try:
                _styles[_uc] = _rucs(
                    _uc, opt["image_family"],
                    backend_model=getattr(b, "model", "") or "").get("prompt_style", "")
            except Exception:
                _styles[_uc] = ""
        opt["prompt_styles"] = _styles
        # Backend with a model list (e.g. Together.ai) — offer as a selection.
        backend_models = getattr(b, 'available_models', [])
        if backend_models:
            opt["models"] = backend_models
            opt["default_model"] = getattr(b, 'model', backend_models[0])
        # LoRA selection in the image-gen dialog — fed from the consolidated
        # LoRA library, the single source (the endpoint's live listing only
        # feeds the discovery sync). Backend-scoped (user decision 2026-07-16):
        # only THIS backend's LoRAs are offered, as [{name, missing}] — manual
        # entries whose LoRA vanished stay offered, marked missing. Transfer:
        # localai as <lora:> prompt tag, openai_diffusion as
        # lora_NN/strength_NN params.
        if b.api_type in ("localai", "openai_diffusion"):
            opt["has_loras"] = True
            from app.core.config import get_lora_options
            opt["lora_options"] = get_lora_options(
                b.name, lora_filter=getattr(b, "lora_filter", "") or "")
        options.append(opt)
    # mapfit default prompts per family — the Fit/Edge dialog prefills the
    # prompt field with these (instead of the former terrain/edge hint).
    from app.core import config as _cfg
    mapfit_prompts = {}
    for _fam in ("natural", "keywords"):
        try:
            _r = _cfg.resolve_use_case_style("mapfit", _fam)
            mapfit_prompts[_fam] = _r.get("prompt_style", "")
        except Exception:
            mapfit_prompts[_fam] = ""
    # Default preselection for locations
    loc_default = os.environ.get("LOCATION_IMAGEGEN_DEFAULT", "").strip()
    result = {"options": options, "mapfit_prompts": mapfit_prompts}
    # Fit/match-edges: imagegen target (backend match spec, read-only in the Fit dialog).
    result["mapfit_imagegen_default"] = (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "").strip()
    # Global outfit default (match spec, e.g. "backend:LocalAI-Flux") — the
    # character-render match UI shows it when no override is set.
    result["outfit_imagegen_default"] = (os.environ.get("OUTFIT_IMAGEGEN_DEFAULT") or "").strip()
    if loc_default:
        result["default_location"] = loc_default
    return result


def delete_gallery_image(location_name: str, image_name: str) -> Dict[str, Any]:
    """Delete a gallery image (by id or name); the route checks path traversal."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    image_path.unlink()

    # If the image was marked as a background, remove the marker
    remove_background_image(loc_id, image_name)
    remove_gallery_image_room(loc_id, image_name)
    remove_gallery_image_type(loc_id, image_name)
    # Detach any dangling map_image/map_image_2d choice of this image from all
    # cells (otherwise the cell shows the first tile instead of the chosen one).
    from app.models.world import clear_map_image_references
    clear_map_image_references(image_name)

    return {"status": "success", "deleted": image_name}


def toggle_gallery_background(location_name: str, image_name: str) -> Dict[str, Any]:
    """Toggle whether a gallery image is eligible as a background."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    is_eligible = toggle_background_image(loc_id, image_name)

    return {"status": "success", "image": image_name, "is_background": is_eligible}


def assign_gallery_image_room(location_name: str, image_name: str,
                              room_id: str) -> Dict[str, Any]:
    """Set the room of a gallery image."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    set_gallery_image_room(loc_id, image_name, room_id)
    return {"status": "success", "image": image_name, "room": room_id}


def assign_gallery_image_type(location_name: str, image_name: str,
                              image_type: str) -> Dict[str, Any]:
    """Set the type of a gallery image (day/night/map_2d/map_3x3/building or empty)."""
    if image_type and image_type not in ("day", "night", "map_2d", "map_3x3", "building"):
        raise HTTPException(status_code=400, detail="Type must be 'day', 'night', 'map_2d', 'map_3x3', 'building' or empty")

    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    set_gallery_image_type(loc_id, image_name, image_type)
    return {"status": "success", "image": image_name, "type": image_type}


# === Background images ===

def _location_image_width() -> int:
    try:
        return int(os.environ.get("LOCATION_IMAGE_WIDTH", "1280"))
    except (TypeError, ValueError):
        return 1280


def _location_image_height() -> int:
    try:
        return int(os.environ.get("LOCATION_IMAGE_HEIGHT", "720"))
    except (TypeError, ValueError):
        return 720


# Free image resolution + floor-plan proportions (2026-07-25). A 2 x 5 m room
# rendered at 1024² becomes an unusably square diorama — the fix pulls on two
# ropes at once: the caller may pick the pixel size, and the prompt states the
# footprint the floor plan actually has.
IMAGE_DIM_MIN = 256
IMAGE_DIM_MAX = 2048
IMAGE_DIM_GRID = 64
# Up to this ratio a room is called "square", above it "rectangular". The
# threshold for the length CLAUSE lives in prompt_compose (RATIO_MIN) — this
# one only picks the shape word.
ROOM_SQUARE_MAX_RATIO = 1.05


def _clamp_image_dim(value: Any) -> int:
    """A caller-supplied image edge in pixels, rounded to the 64-px grid every
    diffusion backend expects and clamped to 256..2048. 0 = nothing usable was
    passed (the use-case/backend default stays)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    v = round(v / IMAGE_DIM_GRID) * IMAGE_DIM_GRID
    return int(max(IMAGE_DIM_MIN, min(IMAGE_DIM_MAX, v)))


def room_shape_hint(location: Optional[Dict[str, Any]],
                    room: Optional[Dict[str, Any]],
                    outdoor: bool = False) -> Optional["ShapeHint"]:
    """The room's footprint as a :class:`ShapeHint`, or None when there is
    nothing worth saying (no layout rectangle, or square without a scale
    anchor).

    This is a BUILDER, not a renderer: the wording per prompt family lives in
    ``prompt_compose.render_hint``. The rectangle (``layout.w`` x ``layout.d``)
    is the only place that knows a room is long and narrow — without the hint
    the generator answers every room with the same square box. The real
    metres come from ``scene_recipe.room_size_m`` (geometry lives in exactly
    one place); a location without a scale anchor keeps the bare proportion.
    """
    from app.core.prompt_compose import RATIO_MIN, ShapeHint
    lay = (room or {}).get("layout") or {}
    try:
        w = float(lay.get("w") or 0)
        d = float(lay.get("d") or 0)
    except (TypeError, ValueError):
        return None
    lo, hi = min(w, d), max(w, d)
    if lo <= 0:
        return None
    ratio = hi / lo
    from app.core.scene_recipe import room_size_m
    size = room_size_m(location or {}, room or {})
    if not size and ratio < RATIO_MIN:
        return None  # square-ish and sizeless — the style says it all
    long_m = short_m = None
    if size:
        long_m, short_m = max(size), min(size)
    return ShapeHint(
        shape="square" if ratio < ROOM_SQUARE_MAX_RATIO else "rectangular",
        long_m=long_m, short_m=short_m,
        surface="ground base" if outdoor else "floor slab",
        ratio=ratio)


def resolve_background_path(location_name: str, room: str = "", hour: int = -1,
                            file: str = "") -> Optional[Path]:
    """Resolve the background image of a location (by id or name).

    With an active disruption/danger event that has a rendered image_path,
    the event image is served. Within the resolve-linger window the
    resolved_image_path. Otherwise the normal location background.
    Multi-room: the swap applies to all rooms of the location (consistent
    with the location-wide block rule).

    ``file`` pins a concrete background image (used by the /play frontend so
    that figure positions stick to the exact displayed image). An active
    event image takes precedence and ignores ``file``.
    """
    # location_name can be an id or a name — the event swap needs the id.
    bg_path: Optional[Path] = None
    try:
        from app.core.event_images import get_effective_background_event
        from app.models.world import resolve_location
        _loc = resolve_location(location_name)
        _loc_id = _loc.get("id", "") if _loc else ""
        if _loc_id:
            bg_path = get_effective_background_event(_loc_id)
    except Exception as _e:
        logger.debug("event-bg lookup failed: %s", _e)

    if (not bg_path or not bg_path.exists()) and file:
        bg_path = get_background_file_path(location_name, file)
    if not bg_path or not bg_path.exists():
        bg_path = get_background_path(location_name, room=room, hour=hour)
    return bg_path


def save_uploaded_background(location_name: str, filename: str, content: bytes,
                             room_id: str) -> Dict[str, Any]:
    """Store an uploaded background image for a location (optional room).

    Saves into the location's gallery, registers it as a background and maps
    it to the room if given — the same save/register path as generation.
    """
    from app.models.world import (get_gallery_dir, toggle_background_image,
                                   set_gallery_image_room)
    from app.core.timeutils import utc_now
    from pathlib import Path as _Path

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")
    loc_id = location.get("id") or location_name

    fname = (filename or "").lower()
    ext = _Path(fname).suffix or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Format nicht unterstützt")

    gallery_dir = get_gallery_dir(loc_id)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{loc_id}_{utc_now().strftime('%Y%m%d%H%M%S')}{ext}"
    (gallery_dir / image_name).write_bytes(content)

    toggle_background_image(loc_id, image_name)
    if room_id:
        try:
            set_gallery_image_room(location_name, image_name, room_id)
        except Exception as e:
            logger.debug("set_gallery_image_room beim Upload fehlgeschlagen: %s", e)
    return {"status": "success", "image": image_name, "room_id": room_id}


async def generate_location_background(location_name: str,
                                       custom_prompt: str) -> Dict[str, Any]:
    """Generate a background image for a location via an image backend (by id or name)."""
    # Resolve the location by id or name
    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

    description = location.get("description", location_name)

    # SUBJECT only — the framing tail ("wide angle establishing shot, no
    # people, … 16:9 aspect ratio") is what the location style already says;
    # as a second copy it fought the real canvas size (legacy tail, N7).
    prompt = custom_prompt or description

    # Get the image backend (cheapest available one)

    # Core image SERVICE (wave-6 split) — NOT the skill-manager lookup: the
    # TakePhoto VERB kept SKILL_ID "image_generation" for its per-character
    # config, but has no backends/pool (crashed with AttributeError and left
    # the "Ort-Bild" track pending forever).
    from app.imagegen.service import get_image_service
    img_skill = get_image_service()
    if not img_skill or not img_skill.enabled:
        raise HTTPException(status_code=503, detail="Image service nicht verfuegbar")

    backend = img_skill._select_backend()
    if not backend:
        raise HTTPException(status_code=503, detail="Kein Image-Backend verfuegbar")

    # Generate image (blocking, in a thread) — style/negative from the use case.
    from app.core.prompt_compose import compose as _compose
    _composed = _compose(use_case="location", subject=prompt, backend=backend)
    full_prompt = _composed.prompt
    negative = _composed.negative
    for _w in _composed.warnings:
        logger.info("Prompt composer (location/background): %s", _w)
    # Location background: full resolution — used as a background scene
    # image, no downscale.
    params = {"width": _location_image_width(), "height": _location_image_height()}

    # Fresh seed per call — avoids backend-side cache hits
    # (memory: feedback_no_new_image_sentinel).
    import random as _rnd
    params["seed"] = _rnd.randint(1, 2**31 - 1)

    # Backend fallback engine: tries primary, falls back to the next
    # available backend on failure. Local GPU backends go through the
    # GPU provider queue → never two in parallel per backend.
    _log_meta = {"agent_name": location.get("name", location_name),
                 "original_prompt": prompt, "auto_enhance": False,
                 "compose": _composed.meta}
    def _op(b):
        if getattr(b, "api_type", "") == "a1111":
            from app.core.llm_queue import get_llm_queue, Priority as _P
            return get_llm_queue().submit_gpu_task(
                provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                callable_fn=lambda: b.generate(full_prompt, negative, params,
                                               log_meta=_log_meta),
                agent_name=location.get("name", location_name), gpu_type=b.api_type)
        return b.generate(full_prompt, negative, params, log_meta=_log_meta)
    try:
        images, backend = await asyncio.to_thread(
            lambda: img_skill.run_on_backend(backend, op=_op))
    except BackendBusyError as _busy:
        raise HTTPException(status_code=503,
                            detail=f"{backend.name} ist ausgelastet — bitte später erneut versuchen ({_busy})")
    except RuntimeError as _err:
        raise HTTPException(status_code=500, detail=str(_err))

    if not images:
        raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

    # Save into the gallery + reference as background
    import time
    loc_id = location.get("id", location_name)
    gallery_dir = get_gallery_dir(loc_id)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{int(time.time())}.png"
    image_path = gallery_dir / image_name
    image_path.write_bytes(images[0])

    # Automatically mark as background
    toggle_background_image(loc_id, image_name)

    logger.info("Bild generiert + als Hintergrund markiert: %s (%s) -> gallery/%s/%s", location['name'], loc_id, loc_id, image_name)
    return {"status": "success", "location": location["name"], "location_id": loc_id}


def clear_location_backgrounds(location_name: str) -> Dict[str, Any]:
    """Delete the background-image references of a location (by id or name)."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name
    # Remove all background markers
    for img in get_background_images(loc_id):
        toggle_background_image(loc_id, img)
    return {"status": "success", "location": location_name}


# === Map / tiles / map-fit helpers ===

_MAP_MEDIA_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def _serve_map_icon(location_name: str, image_type: str, override_field: str):
    """Serves the map icon of a location for the given gallery type.

    Per-cell choice: if ``override_field`` is set on the (cloned) location and
    the file exists in the owner gallery, EXACTLY this image is served — so
    with several images every map cell can show its own one. Otherwise fall
    back to the first image tagged as ``image_type``.
    """
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    loc_id = loc.get("id", "")
    if not loc_id:
        raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")

    # Per-cell off switch: the admin explicitly hid this cell's own tile
    # (usually because a multi-tile patch covers it) — no fallback either.
    if override_field == "map_image_2d" and loc.get("map_image_off"):
        raise HTTPException(status_code=404, detail="Kartenbild deaktiviert")

    # Clones share the gallery of their template (owner_id = template id).
    from app.models.world import _gallery_owner_id
    owner_id = _gallery_owner_id(location_name) or loc_id
    gallery_dir = get_gallery_dir(owner_id)

    # 1) Image explicitly chosen per location/clone (if set + file exists).
    chosen = (loc.get(override_field) or "").strip()
    if chosen:
        p = gallery_dir / chosen
        if p.exists():
            return FileResponse(str(p),
                                media_type=_MAP_MEDIA_TYPES.get(p.suffix.lower(), 'image/png'),
                                headers={"Cache-Control": "no-cache"})

    # 2) Fallback: first image tagged as image_type.
    image_types = get_gallery_image_types(owner_id)
    map_images = [img for img, t in image_types.items() if t == image_type]
    if not map_images:
        raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")
    for img_name in map_images:
        img_path = gallery_dir / img_name
        if img_path.exists():
            return FileResponse(str(img_path),
                                media_type=_MAP_MEDIA_TYPES.get(img_path.suffix.lower(), 'image/png'),
                                headers={"Cache-Control": "max-age=300"})
    raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")


def _serve_map_patch(location_name: str):
    """Serves the multi-tile map patch anchored at this cell (``map_patch_2d``,
    gallery type ``map_3x3``). No fallback — a cell either anchors a patch or
    this is a plain 404 (the frontends hide the layer then)."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    chosen = (loc.get("map_patch_2d") or "").strip()
    if not chosen:
        raise HTTPException(status_code=404, detail="Kein Patch gesetzt")
    from app.models.world import _gallery_owner_id
    owner_id = _gallery_owner_id(loc.get("id") or location_name) or (loc.get("id") or "")
    p = get_gallery_dir(owner_id) / chosen
    if not p.exists():
        raise HTTPException(status_code=404, detail="Patch-Datei fehlt")
    return FileResponse(str(p),
                        media_type=_MAP_MEDIA_TYPES.get(p.suffix.lower(), 'image/png'),
                        headers={"Cache-Control": "no-cache"})


# Map fit (neighbor inpaint): generation canvas size (16-GB-friendly) + target
# tile size the cut-out center is upscaled to.
# Default output size: the fit/edge result (center cell) is ALWAYS scaled to
# this edge length (1024). The 3x3 canvas, however, is composed in the
# ORIGINAL resolution of the source tiles (see _place_neighbors) — the input
# is NOT reduced anymore; only the cropped center is normalized to
# MAP_FIT_OUT_TILE at the end. (Previously the whole canvas was capped at
# 1024, i.e. every tile shrunk to ~341px.)
MAP_FIT_OUT_TILE = 1024
# Safety cap per tile (prevents an absurdly large canvas/OOM with unusually
# high-resolution source tiles). 0 = no limit.
MAP_FIT_MAX_TILE = 1536
# Fit: fraction of the neighbor tile placed as context border around the
# center. Smaller = closer to native and sharper, but less blend context.
# Flexible. 0.1875 → with a native 1024 tile the center stays full 1024 and
# the canvas ~1408.
MAP_FIT_NEIGHBOR_FRAC = 0.1875
# Fit: Flux-friendly upper bound for the WHOLE canvas (generation
# resolution). Flux is optimal around ~1 MP (1024px); noticeably above that
# the image gets soft. The tile is chosen so that tile + 2*border <= this
# value (center as large as possible, at most native). Rounded to a multiple
# of 16 (Flux/VAE requirement). 1408 = ~2 MP, matches frac 0.1875 with a full
# 1024 center. Fit only — edge keeps using full tiles.
MAP_FIT_CANVAS_MAX = 1408
# Fit (edit models like Qwen only): cut out only the inner fraction of the
# center. Edit models invent "more surroundings" at the border of the
# regenerated area — the inner core is clean. 1.0 = whole center (like fill
# models), 0.7 = inner 70 %.
MAP_FIT_INNER_CROP = 0.7
# The inpaint workflows no longer receive a crop mask — the workflow returns
# the full (inpainted) canvas and the BACKEND cuts out the center and scales
# it to MAP_FIT_OUT_TILE.
# Mask margin beyond the gray area (so the model blends in the edges) —
# tested: gray-fill/edit models (Qwen/Flux2) +5%, Flux-Dev-Fill (fill model)
# +2% (slightly better).
MAP_BLEND_MASK_GROW_GRAY = 1.05
MAP_BLEND_MASK_GROW_FILL = 1.02


def _resolve_map_icon_path(loc: Dict[str, Any], field: str = "map_image_2d",
                           image_type: str = "map_2d"):
    """Path of the per-cell chosen 2D map tile (otherwise first tagged one).
    Reused logic from :func:`_serve_map_icon`, without FileResponse."""
    from app.models.world import _gallery_owner_id, get_gallery_image_types
    loc_id = loc.get("id", "")
    if not loc_id:
        return None
    # A hidden cell (map_image_off, e.g. covered by a 3x3 patch) contributes
    # no tile — neither to serving nor to the blend/fit neighbor context.
    if field == "map_image_2d" and loc.get("map_image_off"):
        return None
    owner_id = _gallery_owner_id(loc_id) or loc_id
    gallery_dir = get_gallery_dir(owner_id)
    chosen = (loc.get(field) or "").strip()
    if chosen and (gallery_dir / chosen).exists():
        return gallery_dir / chosen
    for fn, tp in (get_gallery_image_types(owner_id) or {}).items():
        if tp == image_type and (gallery_dir / fn).exists():
            return gallery_dir / fn
    return None


def _place_neighbors(location: Dict[str, Any], border_frac: float = 1.0,
                     canvas_max: Optional[int] = None):
    """Builds the canvas (gray, center = own tile) with the neighbor tiles around it.

    ``border_frac`` = fraction of the neighbor tile used as context border
    (1.0 = whole tile → classic 3*tile canvas; 0.25 = narrow border).
    Per neighbor ONLY the strip facing the center (orthogonal) or the corner
    (diagonal) is inserted — this keeps the generation closer to the native
    resolution and therefore sharper.

    ``canvas_max`` (optional): upper bound for the WHOLE canvas (tile + 2*border).
    If set, the tile is chosen so the canvas stays below it (center as large
    as possible, at most native) and tile/border are rounded to multiples of
    16 (Flux/VAE-compatible). None = old behavior (edge).

    Returns ``(canvas, tile, border, present)`` or ``None``. ``border`` =
    border in px, ``present`` = set of the present neighbor directions (dx, dy)."""
    from PIL import Image
    from app.models.world import list_locations
    gx, gy = location.get("grid_x"), location.get("grid_y")
    if gx is None or gy is None:
        return None
    by_pos = {}
    for loc in list_locations():
        lx, ly = loc.get("grid_x"), loc.get("grid_y")
        if lx is not None and ly is not None:
            by_pos[(lx, ly)] = loc
    # Load tiles in ORIGINAL resolution (no downscale). Uniform cell size
    # = largest native edge length (own tile + neighbors); smaller ones are
    # upscaled.
    loaded = {}   # (dx, dy) -> (img, rot)
    native_max = 0
    own_p = _resolve_map_icon_path(location)
    if own_p:
        try:
            with Image.open(own_p) as _o:
                native_max = max(native_max, _o.width, _o.height)
        except Exception:
            pass
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nb = by_pos.get((gx + dx, gy + dy))
            p = _resolve_map_icon_path(nb) if nb else None
            if not p:
                continue
            try:
                img = Image.open(p).convert("RGB")
                native_max = max(native_max, img.width, img.height)
                loaded[(dx, dy)] = (img, int(nb.get("map_rotation_2d") or 0))
            except Exception as _e:
                logger.warning("Nachbar-Tile %s nicht ladbar: %s", p, _e)
    if not loaded:
        return None
    tile = native_max or MAP_FIT_OUT_TILE
    if MAP_FIT_MAX_TILE and tile > MAP_FIT_MAX_TILE:
        logger.info("Map-Fit: Tile-Aufloesung %dpx auf MAP_FIT_MAX_TILE=%dpx begrenzt",
                    tile, MAP_FIT_MAX_TILE)
        tile = MAP_FIT_MAX_TILE
    frac = max(0.05, min(1.0, border_frac))
    if canvas_max:
        # Cap the tile so the whole canvas (tile + 2*border) stays <= canvas_max
        # → Flux-compatible generation resolution. Center as large as
        # possible (at most native). Multiples of 16 (Flux/VAE).
        tile = min(tile, int(canvas_max / (1 + 2 * frac)))
        tile = max(256, (tile // 16) * 16)
        border = max(16, (int(round(tile * frac)) // 16) * 16)
    else:
        border = max(1, int(round(tile * frac)))
    csize = tile + 2 * border
    canvas = Image.new("RGB", (csize, csize), (128, 128, 128))
    present = set()
    for (dx, dy), (img, rot) in loaded.items():
        im = img if img.size == (tile, tile) else img.resize((tile, tile))
        if rot:
            im = im.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
        # Source crop: only the neighbor's strip/corner facing the center.
        sx0 = (tile - border) if dx < 0 else 0
        sx1 = tile if dx < 0 else (border if dx > 0 else tile)
        sy0 = (tile - border) if dy < 0 else 0
        sy1 = tile if dy < 0 else (border if dy > 0 else tile)
        strip = im.crop((sx0, sy0, sx1, sy1))
        # Target position in the canvas (left/top = 0, center = border, right/bottom = border+tile).
        px = 0 if dx < 0 else (border + tile if dx > 0 else border)
        py = 0 if dy < 0 else (border + tile if dy > 0 else border)
        canvas.paste(strip, (px, py))
        present.add((dx, dy))
    logger.info("Map-Fit: Canvas komponiert — Tile %dpx, Border %dpx (frac %.2f), Canvas %dpx",
                tile, border, frac, csize)
    return canvas, tile, border, present


def _finalize_blend(canvas, inpaint_mask, tile, border, present, crop_empty: bool,
                    inner_crop: float = 1.0):
    """Common finish for fit/edge. With ``crop_empty`` cuts off COMPLETELY
    empty outer borders (also for edge at the map border) and saves:
      - canvas (pure RGB)          -> cpath  (input_reference_image)
      - inpaint mask as L          -> mpath  (input_mask)
    NO crop mask anymore — the center is NOT cut out in the workflow anymore
    but by the backend from the returned image. Instead we deliver the center
    cell as FRACTIONS (x0,y0,x1,y1) of the (possibly trimmed) canvas, robust
    against the workflow's output resolution.

    ``inner_crop`` < 1.0 cuts out only the inner fraction of the center
    (around the midpoint) — against the "invented outside" ring of edit models.

    Geometry: center (own tile) sits at ``border``, canvas = tile + 2*border.
    Returns ``(cpath, mpath, tile, crop_frac)``."""
    import tempfile
    csize = tile + 2 * border
    left, top, right, bottom = 0, 0, csize, csize
    if crop_empty:
        # Only cut off the outer border if NO neighbor lies on that side
        # (orthogonal or diagonal) — otherwise corners would remain.
        left = 0 if any(d[0] < 0 for d in present) else border
        right = csize if any(d[0] > 0 for d in present) else csize - border
        top = 0 if any(d[1] < 0 for d in present) else border
        bottom = csize if any(d[1] > 0 for d in present) else csize - border
        if (left, top, right, bottom) != (0, 0, csize, csize):
            canvas = canvas.crop((left, top, right, bottom))
            inpaint_mask = inpaint_mask.crop((left, top, right, bottom))
            logger.info("Map-Blend: leere Raender abgeschnitten -> Canvas %dx%d",
                        right - left, bottom - top)
    # Center cell (middle) as fractions of the trimmed canvas — optionally
    # only the inner fraction (inner_crop) around the midpoint.
    cw, ch = canvas.size  # = (right-left, bottom-top)
    cx0, cy0 = border - left, border - top
    _icf = max(0.05, min(1.0, inner_crop))
    _cxc, _cyc = cx0 + tile / 2.0, cy0 + tile / 2.0
    _half = (tile / 2.0) * _icf
    crop_frac = ((_cxc - _half) / cw, (_cyc - _half) / ch,
                 (_cxc + _half) / cw, (_cyc + _half) / ch)
    cpath = tempfile.NamedTemporaryFile(suffix="_mapblend_canvas.png", delete=False).name
    mpath = tempfile.NamedTemporaryFile(suffix="_mapblend_mask.png", delete=False).name
    canvas.convert("RGB").save(cpath)
    inpaint_mask.save(mpath)
    return cpath, mpath, tile, crop_frac


def _compose_neighbor_canvas(location: Dict[str, Any], crop_empty: bool = False,
                             mask_grow: float = MAP_BLEND_MASK_GROW_GRAY,
                             border_frac: float = MAP_FIT_NEIGHBOR_FRAC,
                             full_mask: bool = False,
                             inner_crop: float = MAP_FIT_INNER_CROP):
    """Fit: canvas (neighbor borders, gray center) + inpaint mask = center * mask_grow.
    ``border_frac`` controls the border width (smaller = closer to native,
    sharper). With ``crop_empty`` cuts off empty outer borders. Returns
    ``(cpath, mpath, tile, crop_frac)`` or ``None``.

    ``mask_grow``: how far the mask extends beyond the center cell
    (1.05 = +5% for gray-fill/edit models, 1.02 = +2% for Flux-Dev-Fill).
    ``full_mask``: mask the WHOLE area instead of only the center — needed for
    edit models (Qwen-Edit), which with a partial mask copy the narrow
    neighbor strip into the center ("neighbor border pulled into the image")."""
    from PIL import Image, ImageDraw
    placed = _place_neighbors(location, border_frac=border_frac,
                             canvas_max=MAP_FIT_CANVAS_MAX)
    if not placed:
        return None
    canvas, tile, border, present = placed
    if full_mask:
        # Edit model (Qwen): whole area editable → coherent regeneration
        # instead of strip copy. The center crop (crop_frac) stays unchanged.
        mask = Image.new("L", canvas.size, 255)
    else:
        mask = Image.new("L", canvas.size, 0)
        # The mask slightly overlaps into the neighbors so the model blends
        # the tile edges. Still only the EXACT center is cut out.
        _m = int(round(tile * (mask_grow - 1) / 2))
        ImageDraw.Draw(mask).rectangle(
            [border - _m, border - _m, border + tile - 1 + _m, border + tile - 1 + _m], fill=255)
    # inner_crop: cut out only the inner core of the center (freely
    # configurable per backend). With a partial mask (full_mask=False) the
    # ring is real anyway → 1.0.
    _inner = inner_crop if full_mask else 1.0
    return _finalize_blend(canvas, mask, tile, border, present, crop_empty, inner_crop=_inner)


def build_fit_canvas_png(loc: Dict[str, Any]) -> bytes:
    """Preview PNG of the 3x3 neighbor canvas that goes into the workflow as
    input_reference_image for "fit to neighbors" (gray center = gets
    inpainted). 404 if no neighbors with a tile / no grid position."""
    comp = _compose_neighbor_canvas(loc)
    if not comp:
        raise HTTPException(status_code=404, detail="Keine Nachbarn mit Tile")
    cpath = comp[0]
    try:
        data = Path(cpath).read_bytes()
    finally:
        for _p in comp[:2]:  # cpath, mpath (paths; comp[3] is the crop fraction)
            try:
                os.remove(_p)
            except Exception:
                pass
    return data


# Edge match (align edges): frame mask width + solid core at the edge.
# BLEND_FRAC = how far the inpaint band reaches inward from each chosen edge
# (fraction of the tile width). Keep it low — with SEVERAL edges the bands
# overlap; a band that is too wide (0.45) eats ~70% of the tile with 2
# neighbors (everything gray). 0.22 -> narrow edge frame, center is kept.
MAP_EDGE_BLEND_FRAC = 0.22
MAP_EDGE_CORE_FRAC = 0.30
_EDGE_DIRS = (("north", 0, -1), ("south", 0, 1), ("east", 1, 0), ("west", -1, 0))


def _analyze_tile_terrain(loc: Dict[str, Any]):
    """Vision terrain phrase of the CURRENT 2D tile, cached per tile filename
    in the gallery meta. ``None`` if vision is off / no tile / error. This way
    north/south/east/west describe the real image, not the possibly outdated
    text description. Re-analysis only for a new tile (different filename)."""
    if str(os.environ.get("MAP_TILE_VISION_ANALYSIS", "")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    tp = _resolve_map_icon_path(loc)
    if not tp:
        return None
    from app.models.world import (_gallery_owner_id, get_gallery_image_metas,
                                  set_gallery_image_meta)
    owner_id = _gallery_owner_id(loc.get("id", "")) or loc.get("id", "")
    fname = tp.name
    metas = get_gallery_image_metas(owner_id) or {}
    cached = (metas.get(fname) or {}).get("terrain")
    if cached:
        return cached
    from app.imagegen.service import get_image_service
    skill = get_image_service()
    if not skill.enabled:
        return None
    term = skill.describe_map_tile(str(tp))
    if term:
        _m = dict(metas.get(fname) or {})
        _m["terrain"] = term
        set_gallery_image_meta(owner_id, fname, _m)
        logger.info("Map-Tile-Vision: %s -> %s", fname, term)
    return term


def _terrain_term(loc: Dict[str, Any]) -> str:
    """Short terrain term of a tile: vision analysis of the CURRENT tile (if
    enabled), otherwise the structured ``terrain`` field, otherwise its own 2D
    map prompt, otherwise description, otherwise name — first statement, ~80
    chars at a word boundary, without dangling function words."""
    term = " ".join((_analyze_tile_terrain(loc) or loc.get("terrain")
                     or loc.get("image_prompt_map_2d")
                     or loc.get("description") or loc.get("name") or "").split())
    for _sep in (".", ";"):
        if _sep in term:
            term = term.split(_sep)[0]
    if len(term) > 80:
        _head = term[:80]
        term = _head.rsplit(",", 1)[0] if "," in _head else _head.rsplit(" ", 1)[0]
    term = term.rstrip(",.; ")
    _fw = {"with", "on", "in", "a", "an", "the", "of", "and", "to", "at",
           "for", "from", "by", "as", "or"}
    _words = term.split()
    while _words and _words[-1].lower() in _fw:
        _words.pop()
    return " ".join(_words)


def _neighbor_sides(location: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{side: neighbor-loc} for the 4 orthogonal sides with a neighbor that
    has a 2D tile (no entry otherwise)."""
    from app.models.world import list_locations
    gx, gy = location.get("grid_x"), location.get("grid_y")
    if gx is None or gy is None:
        return {}
    by_pos = {(l.get("grid_x"), l.get("grid_y")): l for l in list_locations()
              if l.get("grid_x") is not None and l.get("grid_y") is not None}
    out: Dict[str, Dict[str, Any]] = {}
    for side, dx, dy in _EDGE_DIRS:
        nb = by_pos.get((gx + dx, gy + dy))
        if nb and _resolve_map_icon_path(nb):
            out[side] = nb
    return out


def _neighbor_terrain_hint(location: Dict[str, Any]) -> str:
    """Auto prompt for map fit (regenerate the gray center): one tile that
    merges all neighbor terrains — same quality language as the edge prompt
    (color/tone/style alignment), just for the whole tile instead of only the
    edges."""
    parts = [f"{_terrain_term(nb)} to the {side}" for side, nb in _neighbor_sides(location).items()
             if _terrain_term(nb)]
    if not parts:
        return ""
    return ("top-down orthographic map tile blending together the surrounding "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the whole tile, cohesive unified palette and lighting, "
            "no hard seams")


def _edge_transition_prompt(location: Dict[str, Any], sides=None) -> str:
    """Prompt for "align edges": the existing center tile whose borders
    transition into the chosen neighbor terrains (color/tone/style merge)."""
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    if not use:
        return ""
    parts = [f"{_terrain_term(avail[s])} to the {s}" for s in use if _terrain_term(avail[s])]
    return ("top-down orthographic map tile; its edges blend into the adjacent "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the edges, cohesive unified palette and lighting, no hard seams")


# Edge match (new model): EXACTLY two adjacent tiles side by side, the seam
# filled hard gray; mask = gray strip + 5%. The workflow returns ONE image
# (same size), the backend cuts it in the middle and stores both halves in
# their respective locations. NO fill model anymore.
def _compose_edge_pair(location: Dict[str, Any], side: str,
                       mask_grow: float = MAP_BLEND_MASK_GROW_GRAY):
    """Builds the 2-tile canvas (location + neighbor in ``side``) in display
    orientation, fills the seam hard gray and creates the inpaint mask
    (gray strip + 5%). Returns ``(cpath, mpath, info)`` or None.

    ``info`` = dict(axis='x'|'y', a_first(bool), a_loc, b_loc, a_rot, b_rot, tile):
      - axis: seam axis (x = vertical seam, tiles left/right; y = horizontal).
      - a_first: is ``location`` the first half (left resp. top)?
    """
    import tempfile
    from PIL import Image
    import numpy as np
    avail = _neighbor_sides(location)
    nb = avail.get(side)
    if not nb:
        return None
    pa = _resolve_map_icon_path(location)
    pb = _resolve_map_icon_path(nb)
    if not pa or not pb:
        return None
    ia = Image.open(pa).convert("RGB")
    ib = Image.open(pb).convert("RGB")
    tile = max(ia.width, ia.height, ib.width, ib.height)
    if MAP_FIT_MAX_TILE and tile > MAP_FIT_MAX_TILE:
        tile = MAP_FIT_MAX_TILE
    a_rot = int(location.get("map_rotation_2d") or 0)
    b_rot = int(nb.get("map_rotation_2d") or 0)

    def _disp(img, rot):
        im = img if img.size == (tile, tile) else img.resize((tile, tile))
        return im.rotate(-rot, expand=False, fillcolor=(128, 128, 128)) if rot else im
    a_img = _disp(ia, a_rot)
    b_img = _disp(ib, b_rot)

    horizontal = side in ("east", "west")  # tiles left/right -> vertical seam
    if horizontal:
        canvas = Image.new("RGB", (tile * 2, tile), (128, 128, 128))
        a_first = (side == "east")           # east: neighbor right -> A left
        canvas.paste(a_img, (0, 0) if a_first else (tile, 0))
        canvas.paste(b_img, (tile, 0) if a_first else (0, 0))
        axis, W_, H_, seam = "x", tile * 2, tile, tile
    else:
        canvas = Image.new("RGB", (tile, tile * 2), (128, 128, 128))
        a_first = (side == "south")          # south: neighbor below -> A on top
        canvas.paste(a_img, (0, 0) if a_first else (0, tile))
        canvas.paste(b_img, (0, tile) if a_first else (0, 0))
        axis, W_, H_, seam = "y", tile, tile * 2, tile

    blend = max(1, int(tile * MAP_EDGE_BLEND_FRAC))
    coord = np.mgrid[0:H_, 0:W_][1 if axis == "x" else 0]
    dist = np.abs(coord - seam)
    # Fill the seam hard gray (gray strip ±blend).
    gray_band = dist < blend
    arr = np.array(canvas)
    arr[gray_band] = (128, 128, 128)
    canvas = Image.fromarray(arr, "RGB")
    # Mask = strip * mask_grow (hard).
    mask_w = blend * mask_grow
    mask = Image.fromarray(np.where(dist < mask_w, 255, 0).astype("uint8"), "L")

    cpath = tempfile.NamedTemporaryFile(suffix="_edgepair_canvas.png", delete=False).name
    mpath = tempfile.NamedTemporaryFile(suffix="_edgepair_mask.png", delete=False).name
    canvas.save(cpath)
    mask.save(mpath)
    info = {"axis": axis, "a_first": a_first, "a_loc": location, "b_loc": nb,
            "a_rot": a_rot, "b_rot": b_rot, "tile": tile}
    logger.info("Edge-Pair: %s <-%s-> %s | Canvas %dx%d, Naht %s",
                location.get("name"), side, nb.get("name"), W_, H_, axis)
    return cpath, mpath, info


# === prompt-changed flag ===

def set_location_prompt_changed(location_id: str, room_id: str,
                                value: Any) -> Dict[str, Any]:
    """Sets or removes the prompt_changed flag for a location or a room.

    Without ``room_id`` the flag is set/removed at location level.
    """
    from app.models.world import _load_world_data, _save_world_data

    if not value:
        # Remove the flag
        if room_id:
            ok = clear_room_prompt_changed(location_id, room_id)
        else:
            ok = clear_location_prompt_changed(location_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Location/Raum nicht gefunden")
        return {"status": "success", "prompt_changed": False}
    else:
        # Set the flag
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                if room_id:
                    for room in loc.get("rooms", []):
                        if room.get("id") == room_id:
                            room["prompt_changed"] = True
                            _save_world_data(data)
                            return {"status": "success", "prompt_changed": True}
                    raise HTTPException(status_code=404, detail="Raum nicht gefunden")
                else:
                    loc["prompt_changed"] = True
                    _save_world_data(data)
                    return {"status": "success", "prompt_changed": True}
        raise HTTPException(status_code=404, detail="Location nicht gefunden")


# === Gallery image generation ===

def resolve_gallery_subject(location: Dict[str, Any], room_id: str,
                            prompt_type: str, fallback: str = "") -> str:
    """The SUBJECT text of a gallery render — room+type > room > location+type
    > location description. One chain, used by the generate path and by the
    compose preview, so the dialog never has to guess it client-side.
    """
    description = ""
    if room_id:
        room = get_room_by_id(location, room_id)
        if room:
            # Room with prompt type: prefer the room's day/night prompt
            if prompt_type == "day":
                description = (room.get("image_prompt_day", "") or "").strip()
            elif prompt_type == "night":
                description = (room.get("image_prompt_night", "") or "").strip()
            elif prompt_type == "building":
                # Room-model source image: dedicated per-room prompt,
                # else the room text (mirrors the gallery dialog).
                description = ((room.get("image_prompt_building", "") or "").strip()
                               or (room.get("description", "") or "").strip())
            if not description:
                description = room.get("image_prompt_day", "") or room.get("description", "")
    if not description and prompt_type == "day":
        description = location.get("image_prompt_day", "").strip()
    elif not description and prompt_type == "night":
        description = location.get("image_prompt_night", "").strip()
    elif not description and prompt_type in ("map_2d", "map_3x3"):
        description = location.get("image_prompt_map_2d", "").strip()
    elif not description and prompt_type == "building":
        description = location.get("image_prompt_building", "").strip()
    if not description:
        description = location.get("description", location.get("name", fallback))
    return description


def gallery_use_case(location: Dict[str, Any], room_id: str, prompt_type: str,
                     map_blend: bool = False) -> str:
    """The use case a gallery render belongs to.

    A building-type render FOR A ROOM is the room-model source — its own use
    case (open cutaway); the building exterior style would demand a "single
    building" even for a park room. Both split further on the indoor/outdoor
    flag (room overrides location): an outdoor location's "building" is a
    scene diorama, an outdoor room an open-air area.
    """
    model_uc = ""
    if prompt_type == "building":
        model_uc = (("room_model_outdoor" if is_outdoor_room(location, room_id)
                     else "room_model") if room_id
                    else ("building_outdoor" if is_outdoor_room(location, "")
                          else "building"))
    return ("mapfit" if map_blend
            else "map" if prompt_type in ("map_2d", "map_3x3")
            else model_uc if model_uc
            else "location")


def is_outdoor_room(location: Dict[str, Any], room_id: str) -> bool:
    """Indoor/outdoor of a room (falls back to the location's own flag)."""
    from app.models.world import resolve_indoor_flag
    room = get_room_by_id(location, room_id) if room_id else None
    return resolve_indoor_flag(location, room) == "outdoor"


def compose_preview_core(data: Dict[str, Any]) -> Dict[str, Any]:
    """The finished prompt for a render occasion, without generating it.

    Feeds the render dialog's prefill so dialog and batch go through the SAME
    composer (the dialog used to concatenate style + subject itself and
    guessed the use case client-side). Request:
    ``{use_case?, subject?, location_id, room_id?, backend}``.
    """
    location_id = (data.get("location_id") or "").strip()
    location = resolve_location(location_id)
    if not location:
        raise HTTPException(status_code=404,
                            detail=f"Ort '{location_id}' nicht gefunden")
    room_id = (data.get("room_id") or "").strip()
    prompt_type = (data.get("prompt_type") or "building").strip()
    use_case = ((data.get("use_case") or "").strip()
                or gallery_use_case(location, room_id, prompt_type))
    subject = (data.get("subject") or "").strip() or resolve_gallery_subject(
        location, room_id, prompt_type, location_id)

    # The regenerate dialog needs the bare SUBJECT: its prompt is a literal
    # adjustment order, so it gets no style, no hint and no guard — but the
    # resolution chain must still live in exactly one place.
    if data.get("subject_only"):
        return {"prompt": subject, "negative": "", "warnings": [],
                "use_case": use_case, "llm_composed": False,
                "cache_hit": False}

    # The backend only supplies the family (image_family/model) — availability
    # does not matter for a text preview, so take the configured instance by
    # name instead of probing it.
    backend = None
    backend_name = (data.get("backend") or "").strip()
    if backend_name:
        from app.imagegen.service import get_image_service
        _svc = get_image_service()
        backend = next((b for b in (getattr(_svc, "backends", None) or [])
                        if b.name == backend_name), None)

    hints = []
    if room_id:
        _sh = room_shape_hint(location, get_room_by_id(location, room_id),
                              outdoor=is_outdoor_room(location, room_id))
        if _sh:
            hints.append(_sh)
    from app.core.prompt_compose import compose as _compose
    composed = _compose(use_case=use_case, subject=subject, backend=backend,
                        hints=hints)

    # LLM stage: explicit request from the dialog button wins; without the
    # field the use-case flag decides (auto-prefill). Explicit false = off.
    from app.core import config as _cfg
    _want = data.get("llm")
    if (bool(_want) if _want is not None
            else _cfg.use_case_llm_compose(use_case)):
        from app.core.prompt_compose_llm import llm_compose
        composed = llm_compose(composed, use_case=use_case, subject=subject,
                               family=composed.meta.get("family", "keywords"))

    return {"prompt": composed.prompt, "negative": composed.negative,
            "warnings": composed.warnings, "use_case": use_case,
            "llm_composed": bool(composed.meta.get("llm_composed")),
            "cache_hit": bool(composed.meta.get("cache_hit"))}


async def generate_gallery_image_core(location_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Actual generation logic — fired by the single mode as a background
    task and awaited directly by the batch mode (dispatchers in
    app/routes/world.py).
    """
    import time

    try:
        custom_prompt = data.get("prompt", "").strip()
        room_id = data.get("room_id", "").strip()
        # A regenerate/adjust is a VARIANT of its source image: without an
        # explicit room_id it inherits the source's room assignment — the
        # adjust dialog never sends one, and the result silently landed as a
        # location-level image (finding 2026-07-26, "Adjust image — Küche").
        if not room_id and (data.get("reference_image") or "").strip():
            from app.models.world import get_gallery_image_rooms
            room_id = get_gallery_image_rooms(location_name).get(
                (data.get("reference_image") or "").strip(), "")
        prompt_type = data.get("prompt_type", "").strip()  # day/night/map/description
        workflow_name = data.get("workflow", "").strip()
        backend_name = data.get("backend", "").strip()
        loras_override = data.get("loras")
        model_override = data.get("model_override", "").strip()
        batch_track_id = data.get("_batch_track_id", "")
        fit_neighbors = bool(data.get("fit_neighbors"))
        # Edge matching: same mapfit workflow as Fit, only the mask (frame)
        # + prompt (transition) differ. edge_sides = the selected sides.
        edge_match = bool(data.get("edge_match"))
        edge_sides = data.get("edge_sides") or None
        _map_blend = fit_neighbors or edge_match

        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        # Prompt source: custom_prompt > room+type > room > prompt type > location description.
        # Subject only — framing/style come from the use case (map/location).
        prompt = custom_prompt or resolve_gallery_subject(
            location, room_id, prompt_type, location_name)

        # The map/location style now comes from the use case (applied below
        # via resolve_use_case_style) — no separate suffix anymore.

        # Core image SERVICE — not the skill-manager lookup (see the
        # generate_location_image comment; TakePhoto has no backends).
        from app.imagegen.service import get_image_service
        img_skill = get_image_service()
        if not img_skill or not img_skill.enabled:
            raise HTTPException(status_code=503, detail="Image service nicht verfuegbar")

        # Freshly check the availability of all backends — network calls go into
        # a thread, otherwise they block the event loop (the watchdog trips).
        await asyncio.to_thread(
            lambda: [b.check_availability()
                     for b in img_skill.backends if b.instance_enabled])

        # Backend selection: map-blend (inpaint) > match spec > explicit > auto (cheapest)
        backend = None
        if _map_blend:
            # Fit AND edge blending need an inpaint-capable backend. The backend
            # picked in the dialog (data["backend"]) has priority; without a
            # pick fall back to MAPFIT_IMAGEGEN_DEFAULT (a backend match spec).
            # Legacy "workflow:*" specs resolve to None and drop through.
            _fit_spec = ((data.get("backend") or "").strip()
                         or (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "").strip())
            if _fit_spec:
                backend = img_skill.resolve_imagegen_target(_fit_spec)
            if not backend:
                # No (usable) spec — cheapest available inpaint-category backend.
                _inpaint = [b for b in img_skill.backends
                            if b.available and b.instance_enabled
                            and (getattr(b, "category", "") or "") == "inpaint"]
                backend = img_skill.pick_lowest_cost(_inpaint, rotation_key="mapfit")
            if not backend:
                raise HTTPException(
                    status_code=503,
                    detail="Kein Inpaint-faehiges Backend fuer Map-Fit/Edge verfuegbar")
            logger.info("Map-Blend (%s): spec=%s -> Backend=%s",
                        "edge" if edge_match else "fit", _fit_spec, backend.name)
        elif workflow_name:
            # Match concept: glob + availability instead of an exact name.
            # An additionally pinned endpoint (backend_name) forces that instance.
            backend = img_skill.resolve_imagegen_target(
                workflow_name, preferred_backend=backend_name)
            if not backend and backend_name:
                # Explicitly pinned endpoint not available -> CLEAR error
                # instead of a silent fallback to another instance.
                raise HTTPException(
                    status_code=503,
                    detail=f"Gewaehltes Backend '{backend_name}' ist nicht verfuegbar")
            if not backend:
                logger.warning(
                    "Imagegen-Spec '%s' ergab kein verfuegbares Backend", workflow_name)
            else:
                logger.info("Imagegen-Spec (match): %s -> Backend: %s",
                            workflow_name, backend.name)
        elif backend_name:
            # Backend glob via the match concept. _wait_for_explicit_backend probes
            # the matching backends FRESH (instead of trusting stale b.available) —
            # needed for freshly configured cloud backends (CivitAI/Together).
            backend = (img_skill._wait_for_explicit_backend(backend_name)
                       or img_skill.match_backend(backend_name))
            logger.debug("Explizites Backend: %s -> %s", backend_name, backend.name if backend else 'nicht verfuegbar')
            # Explicit choice + not available -> CLEAR error instead of a silent
            # ComfyUI fallback (otherwise the user thinks CivitAI was used).
            if not backend:
                raise HTTPException(
                    status_code=503,
                    detail=f"Gewaehltes Backend '{backend_name}' ist nicht verfuegbar "
                           f"(z.B. ungueltiger API-Key / offline). Kein automatischer Fallback.")

        if not backend:
            backend = img_skill._select_backend()
        if not backend:
            raise HTTPException(status_code=503, detail="Kein Image-Backend verfuegbar")

        # Map blend: auto-prompt only as a fallback when NO prompt came along (the
        # dialog already delivers it editable via .../fit-prompt or .../edge-prompt).
        # Terrain hint only when the backend wants it (terrain_hint) — otherwise the
        # prompt only describes the target style, the gray canvas supplies the context itself.
        if _map_blend and not custom_prompt and getattr(backend, "terrain_hint", False):
            # The terrain analysis makes blocking LLM submits (describe_map_tile,
            # up to one per neighbor side) → into a thread so the event loop
            # stays free. This was the cause of the watchdog block.
            if edge_match:
                _ep = await asyncio.to_thread(_edge_transition_prompt, location, edge_sides)
                if _ep:
                    prompt = _ep
                    logger.info("Edge-Match Auto-Prompt: %s", _ep)
            else:
                _hint = await asyncio.to_thread(_neighbor_terrain_hint, location)
                if _hint:
                    prompt = _hint
                    logger.info("Map-Fit Auto-Prompt: %s", _hint)

        # Regenerate (self-reference): the prompt is a literal adjustment
        # instruction for the reference workflow (e.g. "road turns right") — NO
        # use-case prefix, NO use-case negative, no other manipulation.
        _is_regen = bool(data.get("use_source_as_reference"))
        # Optional "what do you want to change" request: the same LLM function
        # as in the character/Instagram regenerate builds the final prompt from
        # it. Left empty -> the prompt stays literal.
        _improve = (data.get("improvement_request") or "").strip()
        if _is_regen and _improve:
            from app.skills.image_regenerate import enhance_prompt
            prompt = await asyncio.to_thread(enhance_prompt, prompt, _improve, None)
            logger.info("Regenerate-Prompt via enhance_prompt umgeschrieben: %s", prompt[:120])
        # Use-case style/negative: map blend (inpaint) -> "mapfit" (fill gray
        # areas seamlessly, no "new tile" style), normal tile -> "map",
        # otherwise location background.
        from app.core import config as _cfg
        _uc_name = gallery_use_case(location, room_id, prompt_type, _map_blend)
        _ucp = _cfg.resolve_use_case_style(
            _uc_name, getattr(backend, "image_family", "") or "",
            backend_model=getattr(backend, "model", "") or "")
        _compose_meta: Dict[str, Any] = {}
        _warnings: List[str] = []
        if _is_regen:
            full_prompt = prompt
            negative = ""
        elif _map_blend and custom_prompt:
            # The Fit/Edge dialog delivers the (mapfit) prompt already fully edited
            # — take it literally, do NOT double the style prefix. The negative
            # still comes from the mapfit use case. Without a dialog prompt (batch)
            # it falls back to style+auto-hint below.
            full_prompt = prompt
            negative = _ucp.get("prompt_negative", "")
        elif bool(data.get("settings_applied")):
            # The dialog already composed the FULL prompt (use-case style +
            # shape hint woven in by /world/compose-preview — the rule: the
            # dialog always shows the final prompt). Composing again would
            # double both. A negative from the dialog wins: it carries the
            # items the composer's negation guard moved out of the subject.
            full_prompt = prompt
            negative = ((data.get("negative_prompt") or "").strip()
                        or _ucp.get("prompt_negative", ""))
            # Dialog renders were unmarked in the JSONL — a minimal metablock
            # says where the prompt came from. The dialog reports whether its
            # prefill went through the LLM stage.
            _compose_meta = {"use_case": _uc_name, "settings_applied": True,
                             "llm_composed": bool(data.get("llm_composed")),
                             "cache_hit": bool(data.get("cache_hit"))}
        else:
            # ONE composer for the dialog prefill and this (batch/auto) path:
            # style + subject slot + shape hints + negation guard, in
            # app/core/prompt_compose.py. The hint is PREPENDED there — early
            # tokens steer diffusion (finding 2026-07-26, café kitchen).
            from app.core.prompt_compose import compose as _compose
            _hints = []
            if room_id and not _map_blend:
                _sh = room_shape_hint(location, get_room_by_id(location, room_id),
                                      outdoor=is_outdoor_room(location, room_id))
                if _sh:
                    _hints.append(_sh)
            _composed = _compose(use_case=_uc_name, subject=prompt,
                                 backend=backend, hints=_hints)
            # Opt-in LLM stage on top of the mechanical result. Blocking call
            # -> thread. The cache makes a batch/regenerate series ONE call.
            if _cfg.use_case_llm_compose(_uc_name):
                from app.core.prompt_compose_llm import llm_compose
                _composed = await asyncio.to_thread(
                    llm_compose, _composed, use_case=_uc_name, subject=prompt,
                    family=_composed.meta.get("family", "keywords"))
            full_prompt = _composed.prompt
            negative = _composed.negative
            _compose_meta = _composed.meta
            _warnings = _composed.warnings
            for _w in _warnings:
                logger.info("Prompt composer (%s): %s", _uc_name, _w)
        # Map icons are small thumbnails for the world overview and get
        # downscaled. Day/night/description stay at full resolution
        # as background images.
        params: Dict[str, Any] = {"width": _location_image_width(), "height": _location_image_height()}
        if prompt_type == "map_2d":
            params["image_use_case"] = "map"
            # Generate 2D map tiles square (1:1, Flux-native 1024) instead of
            # the 16:9 location format — fills the tile. Otherwise landscape.
            params["width"] = 1024
            params["height"] = 1024
        elif prompt_type == "map_3x3":
            # Multi-tile ground patch: same top-down map style (use case
            # "map"), but generated and stored larger — it spans 3x3 cells, so
            # it gets its OWN downscale cap (map_3x3, 1200 default = 400/cell)
            # instead of the 400px single-tile thumbnail.
            params["image_use_case"] = "map_3x3"
            params["width"] = 1536
            params["height"] = 1536
        elif prompt_type == "building":
            # Square so the whole building fits with a margin — this image also
            # feeds the image-to-3D pass (like the T-pose reference), which needs
            # the full silhouette in frame, not a 16:9 crop.
            params["image_use_case"] = "building"
            params["width"] = 1024
            params["height"] = 1024
        # Caller-picked resolution beats every use-case default (2026-07-25):
        # a 2 x 5 room needs a 2 x 5 image, not the square building format.
        # Rounded/clamped above; unset keeps the default. Backends without a
        # free size ignore the values — best effort, never an error. The
        # map-blend canvas below still overrides both: its size is geometry.
        _req_w = _clamp_image_dim(data.get("width"))
        _req_h = _clamp_image_dim(data.get("height"))
        if _req_w:
            params["width"] = _req_w
        if _req_h:
            params["height"] = _req_h
        if _req_w or _req_h:
            logger.info("Caller-picked image size: %sx%s",
                        params["width"], params["height"])
        # Model override from the dialog — backends read params["model"].
        if model_override:
            params["model"] = model_override
        # LoRA selection from the dialog. The dialog is backend-scoped (LoRA
        # library entries of the chosen backend only); this is the server-side
        # safety net for direct API calls. Library entries flagged missing
        # pass — the flag can be stale, a wrong pick fails visibly in the
        # render result.
        if loras_override is not None:
            params["lora_inputs"] = loras_override
            from app.core.config import get_lora_options
            _allowed = {o["name"] for o in get_lora_options(
                backend.name,
                lora_filter=getattr(backend, "lora_filter", "") or "")}
            _wanted = [str(l.get("name") or "").strip() for l in loras_override
                       if isinstance(l, dict)]
            _absent = [n for n in _wanted if n and n != "None" and n not in _allowed]
            if _absent:
                raise HTTPException(
                    status_code=400,
                    detail=f"The LoRA library does not associate backend "
                           f"'{backend.name}' with: {', '.join(_absent)}")

        # Fresh seed per call so a regenerate produces a new image.
        import random as _rnd
        params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Self-reference: the existing (map) image as reference in slot 1 —
        # for "regenerate with current image" (e.g. so 2D tiles fit together
        # better). Only if the backend has reference slots.
        if (data.get("use_source_as_reference") and data.get("reference_image")
                and int(getattr(backend, "ref_slot_count", 0) or 0) >= 1):
            _ref_name = (data.get("reference_image") or "").strip()
            if _ref_name and "/" not in _ref_name and ".." not in _ref_name:
                # get_gallery_dir is imported module-wide (top). NO local import
                # here — it would turn get_gallery_dir into a function-wide local
                # variable and blow up the save path (below) with an
                # UnboundLocalError as soon as this block does not run.
                _ref_path = get_gallery_dir(location_name) / _ref_name
                if _ref_path.exists():
                    params["reference_images"] = {"input_reference_image_1": str(_ref_path)}
                    logger.info("Map-Selbst-Referenz in Slot 1: %s", _ref_name)

        # Neighbor-context inpainting: build the 3x3 canvas + mask and inject
        # them as input_reference_image/input_mask. Fit = gray center (whole
        # tile new); Edge = real tile + frame mask of the selected sides.
        _fit_comp = None
        _edge_pair = None
        _cpath = _mpath = None
        # Inpaint mask parameters come purely from the backend fields (no flag,
        # no per-model special casing). Only applies when the backend is an
        # inpaint backend (category=="inpaint").
        if getattr(backend, "category", "") == "inpaint":
            _grow = float(getattr(backend, "mask_grow", MAP_BLEND_MASK_GROW_GRAY))
            _full = bool(getattr(backend, "full_mask", True))
            _inner = float(getattr(backend, "inner_crop", MAP_FIT_INNER_CROP))
        else:
            _grow = MAP_BLEND_MASK_GROW_FILL
            _full = False
            _inner = MAP_FIT_INNER_CROP
        if edge_match:
            # EXACTLY two adjacent tiles, ONE edge. Seam hard gray, mask =
            # strip * mask_grow. The backend returns ONE image — this module
            # cuts it down the middle and puts both halves into the neighbor locations.
            _side = (edge_sides[0] if isinstance(edge_sides, (list, tuple)) and edge_sides
                     else (edge_sides if isinstance(edge_sides, str) else ""))
            _ep = _compose_edge_pair(location, _side, mask_grow=_grow)
            if _ep:
                _cpath, _mpath, _edge_pair = _ep
                params["image_use_case"] = "mapfit"  # bypass the 400 cap: full output for cutting
        elif fit_neighbors:
            _fit_comp = _compose_neighbor_canvas(location, crop_empty=True, mask_grow=_grow,
                                                 full_mask=_full, inner_crop=_inner)
            if _fit_comp:
                _cpath, _mpath, _ctile, _cfrac = _fit_comp
                # Bypass the 400 cap: the backend shall return the FULL canvas so
                # that the center is cropped out at full resolution. Without this
                # the output is shrunk to 400px (map cap) beforehand → the
                # center crop yields only ~290px upscaled (blurry).
                params["image_use_case"] = "mapfit"
        if _cpath and _mpath:
            # Canvas (pure RGB) -> input_reference_image, inpaint mask -> input_mask.
            # Both at original resolution; give the workflow the real canvas dimensions.
            params["reference_images"] = {
                "input_reference_image": _cpath, "input_mask": _mpath}
            from PIL import Image as _ImgSz
            with _ImgSz.open(_cpath) as _cv:
                _cw, _ch = _cv.size
            params["width"] = _cw
            params["height"] = _ch
            logger.info("Map-Blend: Canvas + Inpaint-Maske injiziert (%dx%d)", _cw, _ch)
            try:
                import shutil as _sh
                from app.core.paths import get_storage_dir as _gsd
                _dbg = _gsd() / "mapblend_debug"
                _dbg.mkdir(parents=True, exist_ok=True)
                _sh.copy(_cpath, _dbg / "last_canvas.png")
                _sh.copy(_mpath, _dbg / "last_mask.png")
                (_dbg / "last_prompt.txt").write_text(
                    f"mode: {'edge' if edge_match else 'fit'}\n"
                    f"location: {location.get('name', '')} ({location.get('id', '')})\n"
                    f"edge_sides: {edge_sides}\n\n"
                    f"PROMPT:\n{full_prompt}\n\nNEGATIVE:\n{negative}\n",
                    encoding="utf-8")
                # Log the md5 too → 1:1 comparison with the backend's "Ref-Inject"
                # log line: this proves that the mapblend_debug files are exactly
                # the ones that go to ComfyUI.
                import hashlib as _hl
                _cmd5 = _hl.md5(Path(_cpath).read_bytes()).hexdigest()[:12]
                _mmd5 = _hl.md5(Path(_mpath).read_bytes()).hexdigest()[:12]
                logger.info("Map-Blend Debug (%s): %s | canvas md5=%s mask md5=%s",
                            "edge" if edge_match else "fit", _dbg, _cmd5, _mmd5)
            except Exception as _de:
                logger.debug("Map-Blend Debug-Copy fehlgeschlagen: %s", _de)
        elif _map_blend:
            logger.info("Map-Fit/Edge: kein Nachbar/Grid-Position — normaler Lauf")

        from app.core.task_queue import get_task_queue
        _tq = get_task_queue()
        if batch_track_id:
            _track_id = batch_track_id
        else:
            _track_id = _tq.track_start(
                "image_gen", "Ort-Bild", agent_name=location.get("name", location_name),
                provider=backend.name, start_running=False)

        _gen_start = time.time()
        try:
            # Generate via the GPU provider queue — serialized per backend
            # (never two in parallel); activates the track only once the channel
            # picks up the work; waiting world gens thus stay correctly "pending".
            # Context for the CENTRAL logging in backend.generate() (final_prompt,
            # backend, model, LoRAs, refs, duration are set by generate() itself).
            _log_meta = {"agent_name": location.get("name", location_name),
                         "original_prompt": prompt, "auto_enhance": False}
            if _compose_meta:
                # Numeric verification runs over logs/image_prompts.jsonl —
                # the composer states which family, slot and hint produced
                # the final prompt.
                _log_meta["compose"] = _compose_meta
            def _op(b):
                def _gen():
                    try:
                        from app.core.task_router import match_queue_name
                        _tq.track_activate(_track_id, queue_name=match_queue_name(b.name) or "", provider=b.name)
                    except Exception:
                        pass
                    return b.generate(full_prompt, negative, params, log_meta=_log_meta)
                if getattr(b, "api_type", "") == "a1111":
                    from app.core.llm_queue import get_llm_queue, Priority as _P
                    return get_llm_queue().submit_gpu_task(
                        provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                        callable_fn=_gen, agent_name=location.get("name", location_name),
                        gpu_type=b.api_type)
                return _gen()
            try:
                images, backend = await asyncio.to_thread(
                    lambda: img_skill.run_on_backend(backend, op=_op))
            except BackendBusyError as _busy:
                _tq.track_finish(_track_id, error=f"{backend.name} ausgelastet")
                raise HTTPException(status_code=503,
                                    detail=f"{backend.name} ist ausgelastet — bitte später erneut versuchen ({_busy})")
            except RuntimeError as _err:
                _tq.track_finish(_track_id, error=str(_err)[:200])
                raise HTTPException(status_code=500, detail=str(_err))

            if not images:
                _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
                raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

            # Edge pair (new model): cut the returned ONE image down the middle,
            # rotate each half back to north by its own rotation, bring it to the
            # map thumbnail (400) and store it in the respective location as a
            # new map_2d tile. Then done immediately.
            if _edge_pair:
                import io as _io2
                from PIL import Image as _ImgE
                from app.core.image_postprocess import downscale_bytes
                from app.models.world import set_location_map_image
                _full = _ImgE.open(_io2.BytesIO(images[0])).convert("RGB")
                _W, _H = _full.size
                if _edge_pair["axis"] == "x":
                    _mid = _W // 2
                    _first = _full.crop((0, 0, _mid, _H))
                    _second = _full.crop((_mid, 0, _W, _H))
                else:
                    _mid = _H // 2
                    _first = _full.crop((0, 0, _W, _mid))
                    _second = _full.crop((0, _mid, _W, _H))
                _a_half = _first if _edge_pair["a_first"] else _second
                _b_half = _second if _edge_pair["a_first"] else _first
                _saved = []
                for _hl, _loc2, _rot2 in ((_a_half, _edge_pair["a_loc"], _edge_pair["a_rot"]),
                                          (_b_half, _edge_pair["b_loc"], _edge_pair["b_rot"])):
                    if _rot2:
                        _hl = _hl.rotate(_rot2, expand=False)  # back to north
                    _bb = _io2.BytesIO(); _hl.save(_bb, format="PNG")
                    _png = downscale_bytes(_bb.getvalue(), "map")  # map thumbnail (400)
                    _lid2 = _loc2.get("id", "")
                    _gd2 = get_gallery_dir(_lid2); _gd2.mkdir(parents=True, exist_ok=True)
                    _nm2 = f"{int(time.time())}_{_lid2[:6]}.png"
                    (_gd2 / _nm2).write_bytes(_png)
                    save_gallery_prompt(_lid2, _nm2, full_prompt)
                    set_gallery_image_type(_lid2, _nm2, "map_2d")
                    set_gallery_image_meta(_lid2, _nm2, {
                        "backend": backend.name, "backend_type": backend.api_type,
                        "model": (getattr(backend, 'model', '') or ''), "loras": []})
                    set_location_map_image(_lid2, "map_image_2d", _nm2)  # show the new tile
                    _saved.append({"location_id": _lid2, "image": _nm2})
                for _tmp in (_cpath, _mpath):
                    try:
                        os.remove(_tmp)
                    except Exception:
                        pass
                _tq.track_finish(_track_id)
                logger.info("Edge-Pair gespeichert: %s", _saved)
                return {"status": "success", "edge": True, "saved": _saved}

            # Map-Fit/Edge: the backend crops the center (the new tile) out of the
            # returned full canvas (via a fraction box, robust against the output
            # resolution) and scales it to MAP_FIT_OUT_TILE. The workflow no
            # longer gets a crop mask.
            if _fit_comp:
                try:
                    import io as _io
                    from PIL import Image as _Img
                    _full = _Img.open(_io.BytesIO(images[0])).convert("RGB")
                    _w, _h = _full.size
                    _fx0, _fy0, _fx1, _fy1 = _cfrac
                    _box = (round(_fx0 * _w), round(_fy0 * _h),
                            round(_fx1 * _w), round(_fy1 * _h))
                    _crop = _full.crop(_box)
                    if _crop.size != (MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE):
                        _crop = _crop.resize((MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE), _Img.LANCZOS)
                    _buf = _io.BytesIO()
                    _crop.save(_buf, format="PNG")
                    images = [_buf.getvalue()]
                    logger.info("Map-Fit: Mitte %s aus %dx%d -> %dpx", _box, _w, _h, MAP_FIT_OUT_TILE)
                except Exception as _ce:
                    logger.warning("Map-Fit Crop fehlgeschlagen: %s", _ce)
                finally:
                    for _tmp in (_fit_comp[0], _fit_comp[1]):
                        try:
                            os.remove(_tmp)
                        except Exception:
                            pass

            # Map blend: the canvas is built in DISPLAY orientation (center + neighbors
            # each rotated by their map_rotation_2d). The result tile therefore must be
            # rotated BACK to north by exactly this rotation BEFORE saving, otherwise
            # the display (map_rotation_2d) rotates it a second time -> doubly twisted.
            _rot = int(location.get("map_rotation_2d") or 0) if _map_blend else 0
            if _rot:
                try:
                    import io as _io3
                    from PIL import Image as _Img3
                    _im = _Img3.open(_io3.BytesIO(images[0])).rotate(_rot, expand=False)
                    _b = _io3.BytesIO()
                    _im.save(_b, format="PNG")
                    images = [_b.getvalue()]
                    logger.info("Map-Blend: Ergebnis um %d° nach Norden zurueckgedreht", _rot)
                except Exception as _re:
                    logger.warning("Map-Blend Rueckdrehung fehlgeschlagen: %s", _re)

            loc_id = location.get("id", location_name)
            gallery_dir = get_gallery_dir(loc_id)
            gallery_dir.mkdir(parents=True, exist_ok=True)
            # Replace ("new image" checkbox off): overwrite the source image
            # in place — keeps the file name and thus the room/type/map assignment
            # and the background flag. Otherwise a new image with a timestamp.
            _replace_src = (data.get("reference_image") or "").strip() if data.get("replace_source") else ""
            _is_replace = bool(
                _replace_src and "/" not in _replace_src and ".." not in _replace_src
                and (gallery_dir / _replace_src).exists())
            image_name = _replace_src if _is_replace else f"{int(time.time())}.png"
            image_path = gallery_dir / image_name
            image_path.write_bytes(images[0])

            # Save the prompt for a later upgrade
            save_gallery_prompt(loc_id, image_name, full_prompt)

            # Mark the new image as background by default — do NOT toggle on an
            # in-place replace (otherwise an already-set flag flips over), and
            # NOT for map tiles (map_2d) or building renders: those are map/mesh
            # art, never a room background — flagged tiles used to leak into the
            # room-reference slot of chat images.
            if not _is_replace and prompt_type not in ("map_2d", "map_3x3", "building"):
                toggle_background_image(loc_id, image_name)

            # Set the room assignment when room_id is given
            if room_id:
                set_gallery_image_room(loc_id, image_name, room_id)
                # Remove the prompt_changed flag — the image was created from the prompt
                from app.models.world import clear_room_prompt_changed
                clear_room_prompt_changed(loc_id, room_id)
            elif not custom_prompt:
                # Location-level prompt was used — remove the flag there
                from app.models.world import clear_location_prompt_changed
                clear_location_prompt_changed(loc_id)

            # Save generation metadata (service + model + LoRAs)
            _model_used = (getattr(backend, 'last_used_checkpoint', '')
                           or getattr(backend, 'model', '')
                           or getattr(backend, 'checkpoint', '') or '')
            _loras_used = [str(l.get("name")).strip()
                           for l in (params.get("lora_inputs") or params.get("loras") or [])
                           if isinstance(l, dict) and (l.get("name") or "").strip()
                           and l.get("name") != "None"]
            set_gallery_image_meta(loc_id, image_name, {
                "backend": backend.name,
                "backend_type": backend.api_type,
                "model": _model_used,
                "loras": _loras_used,
            })

            # Set the image type when prompt_type is given (day/night/map_2d/map_3x3/building)
            if prompt_type in ("day", "night", "map_2d", "map_3x3", "building"):
                set_gallery_image_type(loc_id, image_name, prompt_type)
            # Set the newly created map tile as the displayed map item right away
            # (fit/neighbor + normal map_2d gen) — otherwise the old tile would stay active.
            if prompt_type == "map_2d":
                from app.models.world import set_location_map_image
                set_location_map_image(loc_id, "map_image_2d", image_name)

            _tq.track_finish(_track_id)
            _gen_duration = time.time() - _gen_start
            logger.info("Bild generiert: %s (%s)/%s%s", location['name'], loc_id, image_name,
                        f" room={room_id}" if room_id else "")

            # Image-prompt logging now happens CENTRALLY in backend.generate()
            # (with the final, trigger-injected prompt) — via log_meta below.
            return {"status": "success", "location": location["name"],
                    "location_id": loc_id, "image": image_name,
                    "warnings": _warnings}
        except HTTPException:
            raise
        except Exception as e:
            _tq.track_finish(_track_id, error=str(e))
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Gallery Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Time-of-day clauses for the day/night variant, keyed (is_room, is_night).
# Interiors get no sky or stars — their light changes, not the weather.
_TIME_VARIANT_CLAUSES = {
    (True, True): ("at night, dim warm lamp light, evening atmosphere, "
                   "cozy shadows, dark sky outside the windows"),
    (True, False): ("in daytime, bright natural light, sunlight through the "
                    "windows, warm daylight atmosphere"),
    (False, True): ("at night, dark sky, moonlight, stars, dim lighting, "
                    "evening mood"),
    (False, False): ("in daytime, bright sunlight, clear sky, natural "
                     "lighting, warm daylight atmosphere"),
}


async def generate_time_variant_core(location_name: str, image_name: str,
                                     target_type: str, workflow_name: str,
                                     backend_name: str,
                                     custom_prompt: str) -> Dict[str, Any]:
    """Logic core of the day/night time variant (img2img with the source
    image as the reference). The route keeps parsing/traversal/HTTP mapping;
    the 404 guards for location/source image sit mid-logic here.
    """
    import time

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

    loc_id = location.get("id", location_name)
    gallery_dir = get_gallery_dir(loc_id)
    source_path = gallery_dir / image_name
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Quellbild nicht gefunden")

    # Prompt: custom or automatically from the day/night prompt / description
    prompt_field = f"image_prompt_{target_type}"
    if custom_prompt:
        prompt = custom_prompt
    else:
        # Check the room assignment of the source image
        image_rooms = get_gallery_image_rooms(loc_id)
        source_room_id = image_rooms.get(image_name, "")
        description = ""
        is_room = False
        if source_room_id:
            room = get_room_by_id(location, source_room_id)
            if room:
                is_room = True
                description = (room.get(prompt_field, "") or
                               room.get("description", ""))
        if not description:
            description = (location.get(prompt_field, "") or
                           location.get("description", location.get("name", location_name)))

        # SUBJECT + time-of-day clause only. Framing, "no people" and the
        # photographic tail come from the location use-case style (composed
        # below) — repeating them here doubled the frame, and the literal
        # "16:9 aspect ratio" fought the real canvas from params.width/height.
        prompt = f"{description}, {_TIME_VARIANT_CLAUSES[(is_room, target_type == 'night')]}"


    # Core image SERVICE (wave-6 split) — NOT the skill-manager lookup: the
    # TakePhoto VERB kept SKILL_ID "image_generation" for its per-character
    # config, but has no backends/pool (crashed with AttributeError and left
    # the "Ort-Bild" track pending forever).
    from app.imagegen.service import get_image_service
    img_skill = get_image_service()
    if not img_skill or not img_skill.enabled:
        raise HTTPException(status_code=503, detail="Image service nicht verfuegbar")

    # Check availability — network calls go into a thread, otherwise
    # they block the event loop (the watchdog trips).
    await asyncio.to_thread(
        lambda: [b.check_availability()
                 for b in img_skill.backends if b.instance_enabled])

    # Backend selection: explicit spec > explicit backend > configured
    # time-variant default (image_generation.timevariant_imagegen_default)
    # > reference-capable auto (cheapest).
    backend = None
    if workflow_name:
        # Match concept: glob + availability instead of an exact name.
        # Legacy "workflow:*" specs resolve to None and drop through.
        backend = img_skill.resolve_imagegen_target(workflow_name)
    elif backend_name:
        backend = img_skill.match_backend(backend_name)  # backend glob via match concept

    if not backend:
        from app.core import config as _cfg
        _tv_default = (_cfg.get("image_generation.timevariant_imagegen_default") or "").strip()
        if _tv_default:
            backend = img_skill.resolve_imagegen_target(_tv_default)

    if not backend:
        # Prefer an edit-capable backend with at least one reference-image
        # slot. NO inpaint backends: they expect a mask, which the
        # day/night convert does not provide.
        candidates = [b for b in img_skill.list_available_backends()
                      if int(getattr(b, "ref_slot_count", 0) or 0) >= 1
                      and (getattr(b, "category", "") or "") != "inpaint"]
        backend = img_skill.pick_lowest_cost(candidates, rotation_key="time_variant")

    # No fallback to backends without reference-image support — the
    # time-variant convert strictly needs img2img with a local reference image.
    if not backend:
        raise HTTPException(
            status_code=503,
            detail="Kein Image-Backend mit Referenzbild-Support verfuegbar. "
                   "Bitte ein Backend mit Referenz-Slots konfigurieren/starten.")

    # The time variant needs an edit backend with a reference-image slot.
    # An inpaint backend does NOT fit — it expects mask inputs.
    if ((getattr(backend, "category", "") or "") == "inpaint"
            or int(getattr(backend, "ref_slot_count", 0) or 0) < 1):
        raise HTTPException(
            status_code=400,
            detail=(f"Backend '{backend.name}' ist fuer Tag/Nacht-Varianten "
                    "ungeeignet (Inpaint bzw. ohne Referenzbild-Slot)."))

    from app.core.prompt_compose import compose as _compose
    _composed = _compose(use_case="location", subject=prompt, backend=backend)
    full_prompt = _composed.prompt
    negative = _composed.negative
    for _w in _composed.warnings:
        logger.info("Prompt composer (location/time-variant): %s", _w)
    # Day/night variants are background images — full size, no downscale.
    params = {"width": _location_image_width(), "height": _location_image_height()}

    # Fresh seed per call — the time variant should always produce a new
    # image instead of hitting a backend-side prompt+seed cache.
    import random as _rnd
    params["seed"] = _rnd.randint(1, 2**31 - 1)

    # The source image is the image being edited (primary edit reference)
    # in reference slot 1.
    params["reference_images"] = {
        "input_reference_image_1": str(source_path),
    }

    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _variant_label = "Nachtansicht" if target_type == "night" else "Tagansicht"
    _track_id = _tq.track_start(
        "image_gen", _variant_label, agent_name=location.get("name", location_name),
        provider=backend.name, start_running=False)

    _gen_start = time.time()
    try:
        # GPU provider queue: serialized per backend + track only active
        # once the channel picks up the work (waiting ones stay "pending").
        _log_meta = {"agent_name": location.get("name", location_name),
                     "original_prompt": prompt, "auto_enhance": False,
                     "compose": _composed.meta}
        def _op(b):
            def _gen():
                try:
                    from app.core.task_router import match_queue_name
                    _tq.track_activate(_track_id, queue_name=match_queue_name(b.name) or "", provider=b.name)
                except Exception:
                    pass
                return b.generate(full_prompt, negative, params, log_meta=_log_meta)
            if getattr(b, "api_type", "") == "a1111":
                from app.core.llm_queue import get_llm_queue, Priority as _P
                return get_llm_queue().submit_gpu_task(
                    provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                    callable_fn=_gen, agent_name=location.get("name", location_name),
                    gpu_type=b.api_type)
            return _gen()
        try:
            images, backend = await asyncio.to_thread(
                lambda: img_skill.run_on_backend(backend, op=_op))
        except BackendBusyError as _busy:
            _tq.track_finish(_track_id, error=f"{backend.name} ausgelastet")
            raise HTTPException(status_code=503,
                                detail=f"{backend.name} ist ausgelastet — bitte später erneut versuchen ({_busy})")
        except RuntimeError as _err:
            _tq.track_finish(_track_id, error=str(_err)[:200])
            raise HTTPException(status_code=500, detail=str(_err))

        if not images:
            _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
            raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

        gallery_dir.mkdir(parents=True, exist_ok=True)
        new_image_name = f"{int(time.time())}.png"
        new_image_path = gallery_dir / new_image_name
        new_image_path.write_bytes(images[0])

        # Save the prompt
        save_gallery_prompt(loc_id, new_image_name, full_prompt)

        # Mark as background
        toggle_background_image(loc_id, new_image_name)

        # Set the type (day/night)
        set_gallery_image_type(loc_id, new_image_name, target_type)

        # Take over the room assignment from the source image
        image_rooms = get_gallery_image_rooms(loc_id)
        source_room = image_rooms.get(image_name, "")
        if source_room:
            set_gallery_image_room(loc_id, new_image_name, source_room)

        # Save the meta
        _model_used = (getattr(backend, 'last_used_checkpoint', '')
                       or getattr(backend, 'model', '')
                       or getattr(backend, 'checkpoint', '') or '')
        _loras_used = [str(l.get("name")).strip()
                       for l in (params.get("lora_inputs") or params.get("loras") or [])
                       if isinstance(l, dict) and (l.get("name") or "").strip()
                       and l.get("name") != "None"]
        set_gallery_image_meta(loc_id, new_image_name, {
            "backend": backend.name,
            "backend_type": backend.api_type,
            "model": _model_used,
            "loras": _loras_used,
            "source": image_name,
        })

        _tq.track_finish(_track_id)
        _gen_duration = time.time() - _gen_start
        logger.info("%s generiert: %s (%s)/%s -> %s", _variant_label, location['name'], loc_id, image_name, new_image_name)

        # Image-prompt logging now happens CENTRALLY in backend.generate()
        # (final, trigger-injected) — via log_meta on the generate call.
        return {"status": "success", "location_id": loc_id, "image": new_image_name, "source": image_name}
    except HTTPException:
        raise
    except Exception as e:
        _tq.track_finish(_track_id, error=str(e))
        raise


# ═══════════════════════════════════════════════════════════════════════════
# World sleep mode — all NPCs really fall asleep (plan-game-time.md)
# ═══════════════════════════════════════════════════════════════════════════

def sleep_world() -> Dict[str, Any]:
    """Sleep mode ON: every awake NPC falls asleep in place (real
    ``is_sleeping``; no off-map move, no location change). NPCs that were
    already sleeping naturally are remembered (``world_sleep_prior``) so
    ``wake_world`` leaves them asleep. The avatar is untouched. While the
    mode is on, NPC LLM-chat triggers are gated (agent loop, telegram,
    direct chat); ticks/memory/scheduler/task queue keep running and the
    game clock keeps moving (unlike freeze)."""
    import json as _json
    from app.models.character import (list_available_characters,
                                      is_character_sleeping, set_is_sleeping)
    from app.models.account import is_player_controlled
    from app.models.world import (set_world_sleeping, set_world_setting,
                                  WORLD_SLEEP_PRIOR_KEY)
    prior, slept = [], []
    for name in list_available_characters():
        try:
            if is_player_controlled(name):
                continue
            if is_character_sleeping(name):
                prior.append(name)
                continue
            set_is_sleeping(name, True)
            slept.append(name)
        except Exception as e:
            logger.warning("sleep_world: %s fehlgeschlagen: %s", name, e)
    set_world_setting(WORLD_SLEEP_PRIOR_KEY, _json.dumps(prior))
    set_world_sleeping(True)
    logger.info("World sleep AKTIVIERT: %d eingeschlafen, %d schliefen schon",
                len(slept), len(prior))
    return {"sleeping": True, "slept": slept, "already_asleep": prior}


def wake_world() -> Dict[str, Any]:
    """Sleep mode OFF: wakes every NPC the sleep mode put to sleep. NPCs from
    the prior list (asleep before the button) stay asleep — natural sleep is
    not interrupted."""
    import json as _json
    from app.models.character import (list_available_characters,
                                      is_character_sleeping, set_is_sleeping)
    from app.models.account import is_player_controlled
    from app.models.world import (set_world_sleeping, get_world_setting,
                                  set_world_setting, WORLD_SLEEP_PRIOR_KEY)
    try:
        prior = set(_json.loads(get_world_setting(WORLD_SLEEP_PRIOR_KEY, "[]")))
    except Exception:
        prior = set()
    woken = []
    for name in list_available_characters():
        try:
            if is_player_controlled(name) or name in prior:
                continue
            if is_character_sleeping(name):
                set_is_sleeping(name, False)
                woken.append(name)
        except Exception as e:
            logger.warning("wake_world: %s fehlgeschlagen: %s", name, e)
    set_world_setting(WORLD_SLEEP_PRIOR_KEY, "[]")
    set_world_sleeping(False)
    logger.info("World sleep DEAKTIVIERT: %d aufgeweckt (%d schlafen natuerlich weiter)",
                len(woken), len(prior))
    return {"sleeping": False, "woken": woken, "still_asleep": sorted(prior)}


# === Player quest book + relationship summary (Others panel) ===

# Fields the player payload of a story arc may EVER carry. Everything the
# arc knows beyond this stays on the server: seed, next_beat_hint,
# character_outcomes and sequel_seed are the plot the player is supposed to
# discover by playing, not to read in a panel.
_ARC_PUBLIC_FIELDS = ("id", "title", "status", "current_state", "tension",
                      "participants", "updated_at")
_ARC_BEAT_FIELDS = ("beat", "timestamp", "summary")

# How many finished arcs the quest book keeps as a chronicle.
_RESOLVED_LIMIT = 10


def _public_arc(arc: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist one arc for the player. Building UP from the allowed keys
    (instead of deleting the forbidden ones) means a new model field can
    never leak by omission."""
    out: Dict[str, Any] = {}
    for key in _ARC_PUBLIC_FIELDS:
        out[key] = arc.get(key, "")
    out["tension"] = arc.get("tension", 1)
    out["participants"] = list(arc.get("participants") or [])
    out["beats"] = [
        {field: beat.get(field, "") for field in _ARC_BEAT_FIELDS}
        for beat in (arc.get("beats") or []) if isinstance(beat, dict)
    ]
    if arc.get("status") != "active" and arc.get("resolution"):
        out["resolution"] = arc.get("resolution")
    return out


def build_player_story_arcs(avatar: str) -> Dict[str, Any]:
    """The quest book of the avatar: its running arcs first (newest change
    first), then the last finished ones as a chronicle."""
    avatar = (avatar or "").strip()
    if not avatar:
        return {"arcs": []}
    from app.models.story_arcs import get_all_arcs
    try:
        arcs = get_all_arcs()
    except Exception as e:
        logger.warning("build_player_story_arcs: %s", e)
        return {"arcs": []}
    mine = [a for a in arcs if avatar in (a.get("participants") or [])]
    mine.sort(key=lambda a: a.get("updated_at", ""), reverse=True)
    active = [a for a in mine if a.get("status") == "active"]
    resolved = [a for a in mine if a.get("status") != "active"]
    return {"arcs": [_public_arc(a)
                     for a in active + resolved[:_RESOLVED_LIMIT]]}


def build_relation_map(avatar: str) -> Dict[str, Dict[str, Any]]:
    """Partner -> the short relationship summary the Others panel shows.

    ONE relationship read per request; the caller looks the present
    characters up in the returned dict.

    Reads the relationship rows directly instead of going through the Mind
    panel's `build_memory_relationships`: that one additionally loads the
    WHOLE memory table (only to count memories per partner, a field nobody
    here wants) and scans the character list to drop ghost partners — far
    too much for a path `/play/others` polls every 5 seconds.

    No ghost filter is needed here: this returns a map, and the caller only
    looks up characters that are PRESENT in the room. A relationship row
    pointing at a deleted character therefore has no key anyone asks for.
    """
    avatar = (avatar or "").strip()
    if not avatar:
        return {}
    from app.models.relationship import get_character_relationships
    try:
        rels = get_character_relationships(avatar)
    except Exception as e:
        logger.warning("build_relation_map(%s): %s", avatar, e)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rels:
        # Partner = the other side. _row_to_rel fills character_a/b with
        # from_char/to_char (DB order); we want the non-self name.
        a = r.get("character_a") or ""
        b = r.get("character_b") or ""
        partner = (b if a == avatar else a).strip()
        if not partner:
            continue
        # a_to_b is the sentiment from a towards b — flip it to the avatar's
        # point of view when the avatar is the b side.
        sentiment = (r.get("sentiment_a_to_b", 0.0) if a == avatar
                     else r.get("sentiment_b_to_a", 0.0))
        out[partner] = {
            "type": r.get("type", "neutral"),
            "strength": r.get("strength", 10),
            "sentiment": round(sentiment, 3),
        }
    return out


def relation_summary(avatar: str, other: str) -> Optional[Dict[str, Any]]:
    """The avatar's relationship to ONE other character, or None if there is
    none. For a whole room use build_relation_map."""
    return build_relation_map(avatar).get((other or "").strip())
