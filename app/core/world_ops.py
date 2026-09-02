"""World-domain operations behind app/routes/world.py.

Logic moved 1:1 out of the route handlers (code-review section 5b); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
import asyncio
import math
import os
import re
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from app.core.log import get_logger
from app.core import scene_recipe
from app.core.scatter_curves import curve_map, tessellate
from app.core.world_geometry import polygon_plan_width_m, polygon_signed_area
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
    from app.core.world_geometry import polygon_self_intersects
    known_kinds = library_kinds()
    for loc in locations:
        loc_id = loc.get("id", "")
        loc["image_count"] = len(list_gallery_images(loc_id)) if loc_id else 0
        # Findings about the DRAWN boundary, for the surface that draws it
        # (contract v6 Nr. 1). The scene payload states the same thing in its
        # ``problems[]``, but a bare location — a pin with an outline and
        # nothing else — composes no scene at all, so the map editor would
        # never hear about a bow tie it just drew. Only set when non-empty:
        # an absent field is "nothing to report", one less thing to render.
        _m3 = loc.get("map3d")
        if isinstance(_m3, dict) and polygon_self_intersects(_m3.get("boundary")):
            loc["boundary_problems"] = ["boundary_self_intersection"]
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

def _place_payload(name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The worldmap's ``place`` block: the held place validated against the
    room's inventory, reduced to what a renderer needs (id, slot, the
    slot's metre point, facing, room). None when the character holds none."""
    from app.core import places
    p = places.place_of(name, profile)
    if not p:
        return None
    return {"id": p["id"], "slot": p["slot"], "x": p["x"], "z": p["z"],
            "facing": p.get("facing"), "room_id": p["room_id"]}


def build_worldmap_payload(avatar_name: Optional[str] = None,
                           show_all: bool = False) -> Dict[str, Any]:
    """Aggregated world map in METRES: locations (centre/rotation/footprint
    edge + optional map3d metadata), character positions (+avatar/activity/
    room/mood/travel target) and active disruption/danger events. One request
    instead of N fetches — read-only, for the player map panel and external
    map clients.

    Payload v2 (Seamless World, E1): the grid is gone. A location is the
    POLYGON ``map3d.boundary``, drawn in local metres around (``pos_x``,
    ``pos_z``) and rotated by ``yaw_deg`` (contract v6); every character
    carries its free metre point in ``pos``.
    Painted terrain is deliberately NOT in here — clients fetch
    ``GET /play/terrain`` once and refetch it whenever ``terrain_sig`` changes.
    The world RELIEF travels the same way: ``height_sig`` is the trigger,
    ``GET /play/heightfield`` the payload (§ A16), and so does the avatar's
    EXPLORATION MEMORY — ``explored_sig`` here, ``GET /play/explored`` there
    (§ A12).
    The AUTHORED world props (§ A9a) DO ride along — a hand-set list capped
    at 500 rows is not a raster, and it is never fogged: deco blocks nothing
    and belongs to no location, so it leaks no knowledge.
    The two walk limits (``max_step_height_m`` / ``max_slope_deg``) DO ride
    along: the client mirrors the height gate of ``POST /play/pos`` and needs
    the very numbers the server judges with. So do the location's authored
    pass-throughs (``openings``, contract v6): finished world points plus
    inward normals off ``boundary_entry.opening_world_frames``, so no client
    anchors an opening of its own any more.

    Fog of war (§ A12): with ``show_all=False`` the payload only carries what
    the avatar knows — placed locations pass through
    ``location_visible_to_character``, characters and events follow their
    location, and a character standing on ground the avatar has never
    EXPLORED (``core/exploration``, the 64 m cells the 3D client draws its
    haze over) is dropped as well unless it shares the avatar's location.
    ``show_all=True`` is the unfiltered admin view. ``world_bounds``
    is always computed BEFORE that filter, so the map keeps its extent no
    matter how much of it is still dark — and it is not boundaries alone: a
    placed location contributes the world-space box of its DRAWN boundary
    when it has one and its bare CENTRE POINT when it has none, and every
    painted terrain area contributes the box of its polygon (E4 finding B7).
    """
    from app.models.events import list_events
    from app.models.character import (
        list_available_characters, get_character_current_location,
        get_character_pos,
        get_effective_activity, get_effective_pose_key, get_movement_target,
        get_character_profile_image,
        get_character_current_room, get_character_current_feeling,
    )
    from app.core.discovery import get_discovery_range_m
    from app.core.exploration import explored_sig, point_explored, seen_cells
    from app.core.backdrop import get_backdrop
    from app.core.relief import get_max_slope_deg, get_max_step_height_m
    from app.core.expression_pose_maps import resolve_pose_animation
    from app.core.animation_sets import resolve_sets as resolve_animation_sets
    from app.core.interaction_engine import payload_for as _interaction_payload
    from app.core.world_geometry import (effective_boundary, local_to_world,
                                         polygon_plan_width_m)
    from app.core.boundary_entry import opening_world_frames
    from app.core.heightfield import current_sig as height_sig
    from app.models.terrain import list_areas, terrain_sig
    from app.models.world_props import payload_rows, world_props_sig

    # Built ONCE per payload: the signature below hashes the very rows that
    # are sent, so building them twice would also read the prop library twice.
    _world_props = payload_rows()

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
    # matter how much of it is still dark. A location with a drawn boundary
    # contributes the axis-aligned box of that outline IN WORLD SPACE (the
    # § A1.1 pin transform, rotation included): the extent is a viewport
    # hint, not a collision volume.
    # A placed location WITHOUT a boundary has no area, so it stretches the
    # bounds by its centre point alone — the map extent never misses a
    # location it shows.
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
        # ONE geometry source: the DRAWN boundary decides both the extent and
        # the width reported in the entry — never a second hand-parse of
        # map3d.plan_width_m (which would still answer for a location whose
        # outline was never drawn, i.e. one that has no area at all).
        _bd = effective_boundary(loc)
        if _bd is not None:
            _pts_w = [local_to_world(_lx, _lz, _bd[0], _bd[1], _bd[2])
                      for _lx, _lz in _bd[3]]
            _stretch(min(p[0] for p in _pts_w), max(p[0] for p in _pts_w),
                     min(p[1] for p in _pts_w), max(p[1] for p in _pts_w))
        elif loc.get("pos_x") is not None and loc.get("pos_z") is not None:
            _cx, _cz = float(loc["pos_x"]), float(loc["pos_z"])
            _stretch(_cx, _cx, _cz, _cz)
        if not _visible(loc):
            continue
        visible_ids.add(lid)
        # The boundary's bounding-box width is hoisted out of map3d: it is
        # the scale number every map client reads (loading radius, viewport,
        # backdrop), and none of them should have to dig for it. Derived
        # through the ONE rule the sanitizer stores it by, so the payload and
        # the stored field cannot disagree; None whenever there is no area.
        # The footprint travels with the row as a POLYGON, always (contract
        # v6 "Gebiete") — the DRAWN boundary or nothing. Since 2026-08-19 no
        # square is synthesized for a location that has none: it is then a
        # bare pin, and `boundary: null` is exactly that statement.
        _width = polygon_plan_width_m(_bd[3]) if _bd is not None else None
        entry = {
            "id": lid,
            "name": loc.get("name") or "",
            "pos_x": loc.get("pos_x"),
            "pos_z": loc.get("pos_z"),
            "yaw_deg": float(loc.get("yaw_deg") or 0.0),
            "plan_width_m": _width,
            "boundary": [[x, z] for x, z in _bd[3]] if _bd is not None else None,
            # The authored pass-throughs, COMPUTED (§ A1.3, § B1 Nr. 13): edge
            # index, world point, world inward normal and the room link. The
            # geometry is not re-derived here — ``opening_world_frames`` is the
            # very function the entry gate of ``POST /play/pos`` measures with,
            # so the offer a client renders and the crossing the server accepts
            # cannot drift. Empty list = this location has no authored way in,
            # which IS the free-boundary statement (E4 task 5).
            "openings": opening_world_frames(loc),
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
        # openings drawn in the floor-plan editor, rotation, size, the drawn
        # boundary, plan_width_m, storey_height_m, floors. A gate drawn
        # into the boundary changed nothing a running client could see.
        # ``entry["map3d"]`` is the sanitized object (sanitized on save) plus
        # the derived floors — deliberately the SAME object the entry ships,
        # never a second sanitize pass.
        # ONE signature function (``scene_recipe.layout_signature``): the
        # walking gate keys its height-field cache on the very same answer,
        # and two hashes over "what shapes this scene" would drift.
        _lay_rooms = [r for r in (loc.get("rooms") or [])
                      if isinstance(r, dict) and r.get("layout")]
        _lay_map3d = entry.get("map3d") or {}
        if _lay_rooms or _lay_map3d:
            from app.core.scene_recipe import layout_signature
            entry["layout_sig"] = layout_signature(_lay_map3d,
                                                   _lay_rooms)[:10]
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
    from app.core.game_time import GameTime
    from app.core.timeutils import game_speed_factor, game_time
    from app.core.travel_engine import (get_journey, journey_state,
                                        segment_pace_m_s)
    from app.models.character import get_character_language
    _now_game = game_time()
    _factor = game_speed_factor()
    # Display language for the ready-made time labels below — the avatar's,
    # like every other localized string this endpoint hands out. Without an
    # avatar (admin overview) the base language is what is left.
    _lang = (get_character_language(avatar) if avatar else "") or "en"

    # How far the avatar sees OUT IN THE OPEN (E6, § A12). Deliberately the
    # SAME number that discovers a place by coming close to it
    # (app/core/discovery.py) — one "how far do I see outdoors" setting, not a
    # second one beside it; 0 switches sight off. Read once per request, like
    # the avatar's own point the distance is measured from.
    _sight_m = get_discovery_range_m() if (fogged and avatar) else 0.0
    # The avatar's own point — read whenever there IS an avatar and a filter,
    # because the veil gate below needs it too (its near view), not only the
    # sight rule. `_in_sight` therefore says out loud that a range of 0 is no
    # sight line instead of leaning on a `None` point to mean it.
    _avatar_pos = get_character_pos(avatar) if (fogged and avatar) else None

    def _in_sight(p: Optional[Dict[str, float]]) -> bool:
        """Is a metre point within the avatar's sight range? False without a
        range (0 = off), without the avatar's own point, and for a character
        the map does not place — none of the three is a sight line."""
        if _sight_m <= 0 or not (_avatar_pos and p):
            return False
        return math.hypot(float(p["x"]) - float(_avatar_pos["x"]),
                          float(p["z"]) - float(_avatar_pos["z"])) <= _sight_m

    # THE VEIL HIDES FIGURES, TOO (plan-fog-schleier-v2.md § 2). The 3D client
    # hazes over every 64 m cell the avatar has not explored — and a figure
    # drawn crisply on hazed ground would be exactly the leak the haze is
    # there to prevent, so the SERVER decides it: a character standing in an
    # unexplored cell does not reach the player payload at all. It is the
    # same knowledge filter as the rest of § A12, one step finer — where
    # `known_locations` says which PLACES the avatar knows, the exploration
    # memory says which GROUND it has seen.
    #
    # Three exceptions, and there are no others:
    #   * the avatar itself (it is never hidden from itself),
    #   * anybody in the avatar's own location — a room-mate is not seen
    #     across the map but stood next to, and the veil is a map effect,
    #   * a character the map does not place (no point): nothing to haze.
    # The near view rides in through `seen_cells` — see there for why the
    # stored memory alone would blink.
    _seen: Optional[set] = None
    _avatar_loc = ""
    if fogged and avatar:
        _seen = seen_cells(avatar, _avatar_pos)
        _avatar_loc = get_character_current_location(avatar) or ""

    def _under_veil(loc_id: str, p: Optional[Dict[str, float]]) -> bool:
        """Is this character's ground still unexplored — and is it therefore
        under the haze? Always False without a filter or without an avatar;
        those two views have no veil to be under."""
        if _seen is None:
            return False
        if loc_id and loc_id == _avatar_loc:
            return False
        return not point_explored(_seen, p)

    characters = []
    for name in list_available_characters():
        loc_id = get_character_current_location(name) or ""
        pos = get_character_pos(name)
        if not loc_id and pos is None:
            continue  # offmap (e.g. avatar-only & uncontrolled) -> not on the map
        # ONE profile load per character, shared by the fog gate below, the
        # journey, the animation-set chain and the height — this loop runs per
        # character on every worldmap request.
        try:
            from app.models.character import get_character_profile as _gcp
            _prof = _gcp(name) or {}
        except Exception:
            _prof = {}
        # The active journey (or None), read BEFORE the fog gate because the
        # wilderness rule asks whether this character is travelling.
        # NOTE: this reader can WRITE — a stored v1 journey (cell path) is
        # discarded here together with its movement target, once, on the first
        # read after the format change (travel_engine.get_journey).
        try:
            _j = get_journey(name, profile=_prof)
        except Exception as e:
            _j = None
            # debug, not warning: this endpoint is polled every few seconds
            # per client — a broken journey would flood the log at warning
            # level for as long as it exists.
            logger.debug("journey read failed for %s: %s", name, e)
        if not loc_id:
            # Wilderness: a free point outside every footprint is a legal
            # place to be. Under fog the avatar always sees itself, a stranger
            # out there only within its SIGHT RANGE (§ A12).
            # Travellers are the exception: a journey runs through the
            # wilderness for most of its length, so the sight rule would make
            # a figure blink out for the whole trip — exactly what § A11 warns
            # against. Its row stays, but thinned (see the travel block).
            # WITHOUT an active avatar there is no exception either: that view
            # knows nothing at all (no location passes the filter), so a
            # traveller must not be the one thing it does see.
            # AND ONLY A JOURNEY TO A LOCATION counts (`target`). A POINT
            # journey is how a roaming NPC crosses its home area — it is
            # walking most of the time, so the exception would make every
            # circle/area NPC permanently visible across the whole map. § A11
            # is about a figure that would blink out mid-TRIP between places;
            # a wanderer inside its own patch of wood is not that figure.
            if (fogged and name != avatar
                    and not (avatar and _j and _j.get("target"))
                    and not _in_sight(pos)):
                continue
        # The avatar always sees itself; everyone else only where the avatar
        # can look. Standing in an unknown place hides a character entirely.
        elif fogged and name != avatar and loc_id not in visible_ids:
            continue
        # …and whatever the two gates above let through still has to stand on
        # ground the avatar has seen (see `_under_veil`). This is deliberately
        # the LAST word and applies to a traveller as well: § A11 keeps a
        # traveller's row so it does not blink out mid-trip under the SIGHT
        # rule, but a figure crossing ground that is drawn as haze is not a
        # figure the player may see — the veil would be a curtain with a hole
        # in it.
        if name != avatar and _under_veil(loc_id, pos):
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
        anim_sets = resolve_animation_sets(name, profile=_prof)
        # The journey read above as § A11's travel block: the metre polyline
        # plus the walked distance let a client interpolate the figure between
        # two polls instead of teleporting it. Isolated like the ticker's
        # per-character block: one malformed journey dict degrades to
        # travel=null, it never breaks the whole worldmap.
        #
        # FOG (§ A11/§ A12): a foreign traveller keeps its ROW — it is on the
        # map and must not blink out for the whole trip — but everything the
        # ROUTE could be reconstructed from goes. Not only the polyline: from
        # the walked distance, the total length, the arrival time and the two
        # paces a client triangulates the unknown destination just as well
        # (position + remaining distance + heading is a target). What stays is
        # `target_id`, an opaque id the fog never hid either (like
        # `movement_target_id`, whose NAME the roster does withhold below),
        # and the character's own `pos` — that is where the figure is drawn.
        _thin = fogged and name != avatar
        travel = None
        try:
            if _j:
                _st = journey_state(_j["waypoints"], _j["started_at_game"],
                                    _now_game)
                # The pace the journey was STARTED with (world setting at that
                # moment) — a later setting change never re-times it.
                _speed = float(_j.get("speed_m_s") or 0.0)
                # …and the pace this very segment is baked at (terrain).
                _pace = segment_pace_m_s(_j["waypoints"], _st)
                _eta = GameTime.parse(_st["eta_game"])
                travel = {
                    "target_id": _j["target"],
                    # x/z ONLY — the baked cumulative game seconds (t_cum) are
                    # server-internal. A client walks the line by DISTANCE
                    # (progress_m), never by re-deriving the timing.
                    # The route ENDS at the target's opening, so under fog it
                    # would be a metre-exact map marker for a place the avatar
                    # may not know (see the thinning note above).
                    "waypoints": (None if _thin else
                                  [[round(float(w[0]), 2), round(float(w[1]), 2)]
                                   for w in _j["waypoints"]]),
                    "progress_m": None if _thin else _st["progress_m"],
                    "total_m": None if _thin else _st["total_m"],
                    # Arrival on the WORLD CALENDAR (§ A11): the canonical
                    # stamp `Y0002-D109T14:00:00` — there is no world
                    # timezone any more. Clients never slice it: the two
                    # display fields beside it are computed here, server-side.
                    "eta_game": None if _thin else _st["eta_game"],
                    "eta_hhmm": None if _thin else _eta.time_hhmm(),
                    "eta_label": None if _thin else _eta.label(_lang),
                    # The journey's GAME pace as a REAL-seconds one — null on
                    # a frozen world (factor 0): nothing moves, so nothing may
                    # extrapolate. Successor of v1's cell_seconds_real, with
                    # the factor on the other side: a DURATION divides by it,
                    # a SPEED (metres per second) multiplies.
                    "speed_m_s_real": (round(_speed * _factor, 4)
                                       if not _thin and _factor > 0
                                       and _speed > 0 else None),
                    # The pace of the segment being walked RIGHT NOW (§ A11,
                    # E4): the terrain speed_factor sits in the baked stamps,
                    # not in speed_m_s, so THIS is what a client extrapolates
                    # with; speed_m_s_real above stays the nominal fallback.
                    # null on a frozen clock, after the arrival and for a
                    # degenerate segment — the three cases where the number
                    # would be a lie.
                    "pace_m_s_real": (round(_pace * _factor, 4)
                                      if not _thin and _factor > 0
                                      and _pace else None),
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
            # Running pair interaction (§ A8a): kind/role/partner/anchor and
            # the GAME-clock start, so both figures play their halves in
            # lockstep at one anchor; null when the character has none.
            # NOT behind _thin: that flag redacts a journey's ROUTE (see
            # above); a seat or a pair anchor sits inside a room the three
            # fog gates above already let through, so hiding it only broke
            # the rendering (the 2026-08-31 stone-bench finding: every NPC
            # lost its place in the fogged view and fell back to the
            # client's seat heuristic).
            "interaction": _interaction_payload(name, _prof, _now_game,
                                                _factor),
            # The place the server seated the character on (plan-posen-
            # plaetze.md § 4): the slot's metre point, so a client draws the
            # figure THERE and never picks a seat itself; null when it holds
            # none (or the marker vanished — place_of validates).
            "place": _place_payload(name, _prof),
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

    backdrop = get_backdrop()

    return {
        "avatar": avatar,
        "current_location_id": (get_character_current_location(avatar) if avatar else ""),
        "locations": locations,
        "characters": characters,
        "events_by_location": events_by_location,
        # The WORLD CLOCK this payload was computed with — the same instant
        # every journey above was placed on, handed over ready to render
        # (canonical stamp, calendar parts, hour_fraction for the sun, label).
        # Clients display it, they never derive a game hour themselves.
        "game_time": _now_game.to_dict(_lang),
        "world_bounds": world_bounds,
        # Signature of the painted terrain (areas + world type rows), read
        # ONCE per payload: when it changes, clients refetch /play/terrain.
        "terrain_sig": terrain_sig(),
        # Signature of the authored world RELIEF (E8 task 2). Same job as
        # `terrain_sig` and the same reason it rides here: when it changes,
        # clients refetch `GET /play/heightfield` — the one payload too big to
        # send with a 3-second poll.
        # Asked of the FIELD CACHE (`core.heightfield.current_sig`), not
        # recomputed: the raw `models.heightfield.height_sig` re-reads every
        # area and every location and hashes them, which on this poll is a
        # second full `list_locations()` per client every three seconds. The
        # cached answer is the same string whenever the cache is warm, and a
        # cold one falls back to the full computation.
        "height_sig": height_sig(),
        # Signature of the AVATAR's exploration memory (Fog-Gedaechtnis,
        # 2026-08-16). Third of the same kind: when it changes, clients refetch
        # `GET /play/explored` — the list of 64 m cells the overview veil spares
        # in addition to the known footprints. It is the row count of an
        # append-only table (`core/exploration.explored_sig`), so this poll pays
        # one indexed COUNT and never touches the cells themselves.
        # PER AVATAR, and empty without one: the memory is that character's, and
        # an unembodied session has nothing to spare (the admin's `show_all`
        # view draws no veil at all, so it needs none either).
        "explored_sig": explored_sig(avatar) if avatar else "",
        # The AUTHORED props on the world plane (§ A9a) — a landmark rock, a
        # signpost, a bench in the wilderness. They ride IN the payload rather
        # than behind a signature like the painted ground: this is a hand-set
        # list capped at 500 entries, not a raster.
        # NEVER FOGGED, and that is the decision, not an oversight: a world
        # prop is pure decoration, it blocks nothing and it belongs to no
        # location, so there is no knowledge for it to leak. Hiding it would
        # only make the wilderness change its furniture as the veil lifts.
        "world_props": _world_props,
        # Same job as `terrain_sig` one field up, over the FINISHED block: a
        # client rebuilds its meshes when this moves and never otherwise —
        # the list itself is on every poll, comparing 500 rows by hand is not.
        "world_props_sig": world_props_sig(_world_props),
        "fogged": fogged,
        # The two WALK LIMITS (§ A12, E8 task 1). They are world settings the
        # server judges every reported point with (`POST /play/pos`, § A15),
        # and the client has to hold the same two numbers or its figure walks
        # into refusals it could have avoided. This poll is the smallest
        # honest channel there is: it already runs, it is never fogged (a
        # limit reveals nothing about the world), and it carries the other
        # thing the walker needs — the map itself.
        "max_step_height_m": get_max_step_height_m(),
        "max_slope_deg": get_max_slope_deg(),
        # The FAR BACKDROP (§ A17), riding along for the same reasons as the
        # walk limits: it is a world setting, it reveals nothing about the
        # world (a silhouette at the horizon is visible from everywhere, so it
        # is never fogged), and this poll already runs. PURE OPTICS — no
        # collision, no routing, no height.
        # The compass segments of `game.backdrop_arc` are resolved to finished
        # degree ranges HERE, in this contract's figure compass (§ A1.8:
        # 0 = South, 90 = East, 180 = North, 270 = West); the renderer only
        # sweeps what it is given.
        # `None` = switched off, and the key then stays OUT of the payload —
        # exactly what an older server sends, so absent and off are one state.
        **({"backdrop": backdrop} if backdrop else {}),
    }


# Contract v6 Nr. 2 ("the metric wave"): every stored plan coordinate is a
# LENGTH IN METRES in the location's local frame (origin = the anchor pin,
# axes = § A1.1) or in a room's own frame (origin = the room's min corner).
# ONE clamp and ONE rounding for all of them: a location half a kilometre
# across in either direction is beyond anything the world map places, and the
# centimetre is the resolution ``boundary``/``plan_width_m`` already use.
_PLAN_MAX_M = 500.0


def _metre(value: Any, limit: float = _PLAN_MAX_M) -> Optional[float]:
    """One plan coordinate in metres — clamped to ±``limit``, rounded to the
    centimetre. ``None`` for anything that is not a finite number, so the
    caller can drop the whole point/entry instead of inventing a zero."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(min(max(v, -limit), limit), 2)


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
    # ``rotation`` — the building yaw on the map tile — is GONE with v6
    # (Nr. 5): it turned the mesh around the very axis the model sidecar's
    # own orientation fix (``fix_euler`` y) already turns, so it was a second
    # dial on one axis and nothing but a source of arithmetic error. The
    # location itself is turned by its anchor pin (§ A1.1), ``map_rotation_2d``
    # is strictly the 2D ICON artwork rotation. Nothing reads the field and
    # it is not kept here either: a location saved once drops it.
    # ``size`` — the model's ]0, 1] share of the location's bounding box — is
    # GONE with v6 (Nr. 3): a model scales through its DECLARED REAL WIDTH in
    # metres (sidecar ``width_m``), like every other model in the contract.
    # Nothing reads the field and it is not kept here either: a location saved
    # once drops it.
    # ``tile_rotation`` — the 90° turn of the FINISHED scene payload — is GONE
    # with v6 (Nr. 4): a location faces the way its anchor pin says (§ A1.1),
    # and there is no second rotation anywhere. Nothing reads the field and it
    # is not kept here either: a location saved once drops it.
    # ``extent_m`` — the world-metre size of the old reference square — is
    # GONE with E4: the footprint decides, so the width is
    # ``plan_width_m`` and k = 1 (scene_recipe.derive_scalars). Nothing reads
    # the field any more, and it is not kept here either: a location saved
    # once drops it.
    # ``plan_width_m`` IS NOT AN INPUT (closing wave, 2026-08-19). Since v6
    # (Nr. 2) it is a DERIVED quantity — the wider side of the drawn
    # boundary's bounding box — and since the transition square died it is
    # nothing else: a submitted value is ignored here, whatever it says, and
    # a location without a boundary has no width at all (as it has no area).
    # Room rects, props, markers and figures carry their own metres, so
    # nothing scales by it any more; it survives only because consumer
    # contracts do (loading radius, viewport, backdrop, ``scene.extent_m``).
    # It is written below, in the boundary block, and nowhere else.
    # Location boundary (contract v6 "Gebiete"): the DRAWN footprint as a
    # closed point sequence in LOCAL METRES around the pin — the square is
    # only its special case, and a location without a boundary has no area at
    # all (there is no 10 m fallback any more). Concave outlines are allowed
    # and a self-intersection is a WARNING, never a rejection
    # (scene_recipe.boundary_self_intersects), so nothing is dropped for it
    # here. Stored open (a repeated closing point is removed), at most 64
    # points, rounded to the centimetre.
    bd = raw.get("boundary")
    if isinstance(bd, list):
        bpts: List[List[float]] = []
        for pt in bd[:64]:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                continue
            try:
                bx, bz = float(pt[0]), float(pt[1])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(bx) and math.isfinite(bz)):
                continue
            bpts.append([round(bx, 2), round(bz, 2)])
        if len(bpts) >= 2 and bpts[0] == bpts[-1]:
            bpts = bpts[:-1]
        if len(bpts) >= 3:
            # ONE winding in storage: CLOCKWISE in map view, which with x
            # east and z south is a POSITIVE shoelace sum (world_geometry).
            # Everything downstream may therefore assume the direction
            # instead of measuring it.
            if polygon_signed_area(bpts) < 0:
                bpts.reverse()
            # v6 Nr. 2: ``plan_width_m`` is a COMPUTED quantity — the wider
            # side of the boundary's bounding box, by the ONE rule in
            # ``world_geometry.polygon_plan_width_m`` (the worldmap payload
            # reports the same answer). A boundary with no extent encloses
            # nothing — it is not an area, so neither it nor a width is kept.
            width = polygon_plan_width_m(bpts)
            if width > 0:
                out["boundary"] = bpts
                out["plan_width_m"] = width
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
    # the floor plan of the house INSIDE the plot, from which the client
    # renders floor plates + walls per used level.
    # SINCE v6 (Nr. 2) IN LOCAL METRES, like ``boundary``: points relative to
    # the anchor pin, negative values legal, rounded to the centimetre. The
    # fraction era is gone without a reader — an old blob's [0,1] points are
    # simply a one-metre building, which is the agreed rebuild semantics.
    ol = raw.get("outline")
    if isinstance(ol, list):
        pts = []
        for pt in ol[:64]:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                continue
            u, v = _metre(pt[0]), _metre(pt[1])
            if u is None or v is None:
                continue
            pts.append([u, v])
        if len(pts) >= 3:
            out["outline"] = pts
    # Elevator position (AV3D-12): placed once, valid for ALL levels — the
    # client builds a shaft with a platform per level. LOCAL METRES since v6.
    ev = raw.get("elevator")
    if isinstance(ev, (list, tuple)) and len(ev) == 2:
        ex, ez = _metre(ev[0]), _metre(ev[1])
        if ex is not None and ez is not None:
            out["elevator"] = [ex, ez]
    # Staircases (Nachtrag "Treppen (v4)"): one entry per FLIGHT, i.e. per
    # storey jump — a climb from the ground floor to the second is two of
    # them. ``at`` is the foot in LOCAL METRES like every other plan
    # coordinate, ``from_level`` the storey it starts on (a basement flight is
    # −1) and ``dir_deg`` the climb direction, one of the four quarter turns.
    # An entry that misses any of the three is DROPPED rather than repaired:
    # a flight whose direction nobody wrote down would point somewhere the
    # author never chose.
    st = raw.get("stairs")
    if isinstance(st, list):
        flights = []
        for item in st[:scene_recipe.STAIR_MAX]:
            if not isinstance(item, dict):
                continue
            at = item.get("at")
            if not isinstance(at, (list, tuple)) or len(at) != 2:
                continue
            sx, sz = _metre(at[0]), _metre(at[1])
            if sx is None or sz is None:
                continue
            try:
                lvl = int(float(item.get("from_level")))
                deg = int(float(item.get("dir_deg"))) % 360
            except (TypeError, ValueError, OverflowError):
                continue
            if deg not in scene_recipe.STAIR_DIRS_DEG:
                continue
            flights.append({"at": [sx, sz], "from_level": lvl,
                            "dir_deg": deg})
        if flights:
            out["stairs"] = flights
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
    # ``map3d.relief`` IS GONE ("Ein Boden" E5a, user decision 1). A location
    # used to carry a deterministic 17 x 17 height field of its OWN — amplitude,
    # seed and wave width — composed per scene and added on top of the world
    # relief. That was the second of the two grounds the whole plan was written
    # against. Local relief is authored as HEIGHT AREAS of the map now, so the
    # three dials have no reader left and are dropped on the next save without a
    # fallback (the "no backward-compat" rule).
    # Boundary openings (plan-area-detail-scenes.md): pass-throughs at the
    # LOCATION edge (a road crossing the cell east–west = two entries).
    # Geometry + room link only — entry_room stays the gameplay gate.
    # SINCE v6 (Nr. 5) AN EDGE IS AN INDEX: 0-based into the location
    # boundary (edge i = point i → i+1), with ``at`` running along that edge.
    # The letters N/S/E/W are deleted without an alias reader — worlds are
    # rebuilt — so an entry that still carries one is DROPPED, and so is an
    # index the outline does not have. Both cases are logged: an opening that
    # silently disappears costs the author their work, and the log line is
    # what says why. ``room`` is a format check, never an existence check
    # (same rule as prop ids).
    # The WIDTH lies on that edge, so the location's own width is its
    # maximum (a café in the middle of a city cell is entered along its whole
    # edge, not through a 10 m slot). That width is the DERIVED one above, so
    # a location without a drawn boundary has no known edge and 10 m stands
    # in. Out of range is CLAMPED, never dropped.
    max_width_m = float(out.get("plan_width_m") or 10.0)
    # How many edges there are to pick from. Without a boundary there is no
    # geometry to name — an opening authored on such a location is stored but
    # stays inert (``opening_world_frames`` finds no edge to sit on), which is
    # the same thing "no area" means everywhere else. The 4 keeps an outline
    # the author is halfway through drawing from losing its openings.
    edge_count = len(out.get("boundary") or []) or 4
    bo = raw.get("boundary_openings")
    if isinstance(bo, list):
        entries = []
        for op in bo[:8]:
            if not isinstance(op, dict):
                continue
            edge = op.get("edge")
            if isinstance(edge, bool) or not isinstance(edge, int):
                logger.info("boundary opening dropped: edge %r is no edge "
                            "index (v6 Nr. 5)", edge)
                continue
            if not 0 <= edge < edge_count:
                logger.info("boundary opening dropped: edge index %d outside "
                            "the boundary's %d edges", edge, edge_count)
                continue
            try:
                at = float(op.get("at"))
                width_m = float(op.get("width_m"))
            except (TypeError, ValueError):
                continue
            entry: Dict[str, Any] = {
                "edge": edge,
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
    it. A layout counts as set when x/y/w/d are all valid; ``level`` defaults
    to 0 and ``rotation`` (degrees yaw) is optional. Optional too: ``markers``
    (figure snap spots),
    ``surfaces`` ({floor?, wall?} surface-texture kinds), ``openings``
    (doors / windows / passages, see _sanitize_opening), ``outline``
    (drawn room hull) and ``props`` (prop-library placements). Empty result
    means "unset" → client auto-grid.

    EVERYTHING HERE IS METRES (contract v6 Nr. 2 — the fraction system is
    deleted, there is no reader for it left):

    * ``x``/``y`` = the room's MIN CORNER in the LOCATION-LOCAL frame (origin
      = the anchor pin, axes as § A1.1 — the frame ``map3d.boundary`` uses),
      so negative values are ordinary;
    * ``w``/``d`` = the rectangle's size in metres, both > 0;
    * ``outline`` points and their curve control points = metres relative to
      the room's OWN min corner, i.e. spanning 0…w / 0…d;
    * ``markers[].at``, ``props[].at`` and ``model_at`` = metres relative to
      that same min corner.

    Only the ``at`` of an OPENING stays a fraction: it runs along one edge,
    and an edge-relative ratio is not a world size.

    ``outline`` is auto-closed (no repeated closing point) and wound clockwise
    in screen coordinates (y down). Absent = the rectangle itself, i.e. the
    implicit box with edge indices 0=N, 1=E, 2=S, 3=W. x/y/w/d ALWAYS carry
    the derived bounding box, so a client that only knows rectangles keeps
    working.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    x, y = _metre(raw.get("x")), _metre(raw.get("y"))
    w, d = _metre(raw.get("w")), _metre(raw.get("d"))
    if x is None or y is None or w is None or d is None:
        return {}
    if not (w > 0 and d > 0):
        return {}
    out["x"] = x
    out["y"] = y
    out["w"] = w
    out["d"] = d
    # Drawn room hull (plan-room-props.md): a polygon that replaces the plain
    # rectangle. The points are METRES relative to the room's min corner and
    # the bounding box is x/y/w/d — a hand-posted payload whose points do not
    # span [0,w]×[0,d] is shifted/resized here and the difference folded into
    # x/y/w/d, so those ALWAYS describe the real bounding box.
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
                # per edge, in the room's own metres like the points). They
                # only survive when no outline point was dropped above — a
                # dropped point would silently shift every edge index under
                # them.
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
                if (abs(min_u) > 1e-6 or abs(max_u - out["w"]) > 1e-6
                        or abs(min_v) > 1e-6 or abs(max_v - out["d"]) > 1e-6):
                    # In metres the fold is a pure TRANSLATION: the hull keeps
                    # its size, only the origin of the room's own frame moves
                    # onto the hull's min corner (the fraction era had to
                    # rescale here, which is exactly the mechanic v6 deleted).
                    new_w = round(span_u, 2)
                    new_d = round(span_v, 2)
                    new_x = _metre(out["x"] + min_u)
                    new_y = _metre(out["y"] + min_v)
                    # A hull with no extent is not a room; a hull larger than
                    # the plan clamp is dropped, not silently cut.
                    if (0 < new_w <= _PLAN_MAX_M and 0 < new_d <= _PLAN_MAX_M
                            and new_x is not None and new_y is not None):
                        out["x"] = new_x
                        out["y"] = new_y
                        out["w"] = new_w
                        out["d"] = new_d
                        pts = [[p[0] - min_u, p[1] - min_v] for p in pts]
                        curves = {e: (c[0] - min_u, c[1] - min_v)
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
                    out["outline"] = [[round(p[0], 2), round(p[1], 2)]
                                      for p in pts]
                    if curves:
                        # A quadratic control point legitimately sits OUTSIDE
                        # the hull (a road bend), so it gets the plain plan
                        # clamp rather than the bbox — the same ±500 m every
                        # other stored length lives in.
                        out["outline_curves"] = [
                            {"edge": e, "c": [_metre(c[0]), _metre(c[1])]}
                            for e, c in sorted(curves.items())
                            if _metre(c[0]) is not None
                            and _metre(c[1]) is not None]
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
    # ``relief_flat`` IS GONE with the scene's own relief (E5a): there is no
    # per-location height field left for a room to opt out of, and a room that
    # wants level ground under it says so by being on a BUILT location, whose
    # plot the bake planes flat (§ G5).
    #
    # HOW WIDE THIS FLOOR'S TRANSITION IS, in metres (E5a, § G3): a level-0
    # room floor is a LAYER of the ground now (``core.terrain_layers``), and
    # ``edge_blend_m`` is the width over which it gives way to the layer under
    # it. 0…8 m, and the DEFAULT IS 0 — the hard cut, because a floor is drawn
    # and not grown. It goes through the layer module's own sanitizer rather
    # than ``_metre``: 0 is a VALUE here and has to survive a save.
    from app.core.terrain_layers import EDGE_BLEND_KEY, sanitize_edge_blend
    blend = sanitize_edge_blend(raw.get(EDGE_BLEND_KEY))
    if blend is not None:
        out[EDGE_BLEND_KEY] = blend
    # A ROOM HAS NO WATER FIELDS ANY MORE (W1, 2026-08-21). ``water_level``,
    # ``water_depth_m`` and ``shore_ramp_m`` were the E5b per-room sliders of the
    # zone-water carve; that carve is deleted, so the three keys are dropped on
    # the way in without a fallback reader. Water is painted on the MAP, where
    # one polygon owns its mirror, its bed and its flow — and a room that lies on
    # painted water shows a REFERENCE to it in the floor plan
    # (``scene_recipe._floor_plan`` → ``map_water``), derived by containment and
    # never stored, so there is no such thing as a dangling water reference.
    # No recipe walls for this room: open zones, pavilions, areas inside an
    # area model. The server then emits no `walls` entries for it at all, so
    # both renderers follow without knowing the flag. Openings stay editor
    # data (the 2D plan keeps drawing them), the plate is unaffected.
    if raw.get("no_walls"):
        out["no_walls"] = True
    # Diorama-model placement IN THE PLAN (2026-07-24): the room's 3D model
    # is positioned like a prop — ``model_at`` = anchor point in METRES from
    # the room's min corner (absent = centred, today's behaviour) and
    # ``model_offset_y`` = height in metres. This REPLACES the per-model
    # sidecar offset for rooms (values migrate by hand; buildings keep their
    # sidecar offsets).
    mat = raw.get("model_at")
    if isinstance(mat, (list, tuple)) and len(mat) == 2:
        mx, my = _metre(mat[0]), _metre(mat[1])
        if mx is not None and my is not None:
            out["model_at"] = [mx, my]
    moy = raw.get("model_offset_y")
    if moy is not None and f"{moy}".strip() != "":
        try:
            out["model_offset_y"] = round(max(-25.0, min(25.0, float(moy))), 3)
        except (TypeError, ValueError):
            pass
    # Where the room's FLOOR sits, in REAL metres relative to its storey.
    # Since "Ein Boden" (§ A16.9) this is its ONLY job: a FINE TRIM of one
    # room, lifting what stands in it. Its two old side jobs are gone — there
    # is no second ground left to compensate (storey 0 IS the terrain), and
    # the waterline of a water floor is ``water_level`` above, which actually
    # moves the bake. Everything in the room still rides along: walls, props,
    # markers and the diorama.
    fo = raw.get("floor_offset_y")
    if fo is not None and f"{fo}".strip() != "":
        try:
            v = round(max(-25.0, min(25.0, float(fo))), 3)
            if v:
                out["floor_offset_y"] = v
        except (TypeError, ValueError):
            pass
    markers = _sanitize_markers(raw.get("markers"))
    if markers:
        out["markers"] = markers
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
        # A FLOOR KIND MAY NOT BE WATER (W1, 2026-08-21). Water is a thing of
        # the MAP now: it carries its own mirror, bed and flow and it carves the
        # one heightfield. A room floor that named a water kind used to be a
        # second, weaker water with its own bake stage, and stripping it here —
        # loudly, at the one write path — is what makes that impossible rather
        # than merely discouraged. ONE predicate decides it, the same one the
        # layer table asks (``terrain_types.is_water_kind``).
        floor_kind = surfaces.get("floor")
        if floor_kind:
            from app.core.terrain_types import is_water_kind
            if is_water_kind(floor_kind):
                logger.warning("room layout: floor kind %r is water — dropped; "
                               "water belongs on the map (W1)", floor_kind)
                surfaces.pop("floor", None)
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
    placements = _sanitize_props(raw.get("props"))
    if placements:
        out["props"] = placements
    return out


def _place_id(raw: Any) -> str:
    """The stable id of a place (marker or placement): the stored one,
    lower-cased to ``[a-z0-9]`` and cut to 16 chars — or a fresh one when
    nothing usable was sent, so every stored place can be held by name."""
    from app.core.places_migration import new_place_id
    s = re.sub(r"[^a-z0-9]", "", str(raw or "").lower())[:16]
    return s or new_place_id()


def _capacity(raw: Any) -> int:
    """How many figures a marker seats, 1..8 (a bench, a row of stools)."""
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 1


def _spacing(raw: Any) -> float:
    """Metres between two slots of one marker, 0.2..3.0 (default 0.6 = one
    person's width on a bench)."""
    try:
        return round(max(0.2, min(3.0, float(raw))), 2)
    except (TypeError, ValueError):
        return 0.6


def _slot_axis(raw: Any) -> float:
    """Degrees the ROW of slots stands against the marker's facing, 0..180
    (default 90 = ACROSS it, a bench running sideways).

    It is a value and not a rule because "across the facing" only holds for a
    pose that stands or sits UPRIGHT. A lying pose puts the body itself across
    the facing, so a 90° row runs down the body and two sleepers land
    head-to-foot; 0° lays the row along the facing and puts them side by side.
    180° is 0° with the slots in the other order, which is why the range stops
    there — a row is an axis, not a direction."""
    try:
        return round(max(0.0, min(180.0, float(raw))), 1)
    except (TypeError, ValueError):
        return 90.0


def _sanitize_markers(raw: Any) -> List[Dict[str, Any]]:
    """Place markers (schnittstellen-3d.md § B, plan-posen-plaetze.md): the
    spots of a layout a figure can take. ``at`` = METRES in the frame of
    whatever carries the layout — the room's min corner for a room, the
    LOCATION's own frame for the ground (§ A13a) — and ``group`` the PLACE
    TYPE from the pose catalog (``pose_catalog.get_groups()``: seat, bed,
    floor, counter, stand, …). A marker no longer names a clip: which pose
    plays there is the character's business, the marker only says what kind
    of place it is. ``id`` is stable (kept verbatim, else generated) so a
    deleted neighbour never renumbers it.

    Optional per marker: ``capacity`` (2..8 → a bench; the scene composes
    that many slots ``spacing_m`` apart, in a row ``slot_axis`` degrees off
    the facing — 90° = across it), ``rotation`` =
    the figure's facing in degrees (0 = south, 90 = east, 180 = north, 270 =
    west; absent = the client's face-the-neighbours default), ``offset_y``
    (metres, ± — ADDITIVE to the client-sampled surface height under the
    marker) and the two TILT axes ``tilt``/``roll`` (degrees, ±90): a figure
    lying on a slope or leaning against something is not upright, and facing
    alone cannot say that (user finding 2026-07-28 — lying slightly angled on
    the sand). At most 50.
    """
    if not isinstance(raw, list):
        return []
    markers: List[Dict[str, Any]] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        at = m.get("at")
        group = str(m.get("group") or "").strip().lower()
        if not group or not isinstance(at, (list, tuple)) or len(at) != 2:
            continue
        au, av = _metre(at[0]), _metre(at[1])
        if au is None or av is None:
            continue
        entry: Dict[str, Any] = {"id": _place_id(m.get("id")), "group": group,
                                 "at": [au, av]}
        cap = _capacity(m.get("capacity"))
        if cap > 1:
            entry["capacity"] = cap
            entry["spacing_m"] = _spacing(m.get("spacing_m"))
            entry["slot_axis"] = _slot_axis(m.get("slot_axis"))
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
    return markers[:50]


def _sanitize_props(raw: Any) -> List[Dict[str, Any]]:
    """Prop placements (plan-room-props.md): the furnishing as single objects
    from the prop library. REAL-SIZE RULE — a placement never scales the prop;
    the client sizes it from the PROP's own dims, so only position/yaw/height
    live here — plus a stable ``id`` and an optional ``label`` (a placement is
    a place a character can hold by name, plan-posen-plaetze.md). ``at`` is METRES in the carrier's frame (room min corner, or
    the LOCATION frame on the ground — § A13a).

    A placement may additionally SCATTER (plan-area-detail-scenes.md,
    2026-08-02 redesign: scatter is a placement property, not a separate
    room list): ``scatter_count`` copies of the prop are thrown over the
    area from ``scatter_seed`` at compose time; the placement itself stays as
    the manually positioned anchor. Σ scatter_count ≤ 120 per carrier, on top
    of the ≤ 100 manual placements.

    It may also be CUT (``cut_keep``/``cut_side``, § B2 addendum 2026-08-23):
    half a table against a wall is this table with a clipping plane through it,
    not a second library entry.

    What a prop's texture slots SHOW is not a placement statement (D3): the
    picture is chosen where the prop is built, so a placement carries no
    values of its own and one that still brings some simply loses them here.
    """
    if not isinstance(raw, list):
        return []
    from app.core.props import CUT_KEEP_MIN, safe_prop_id
    placements: List[Dict[str, Any]] = []
    scatter_total = 0
    for p in raw:
        if not isinstance(p, dict):
            continue
        # Format check only, NEVER an existence check: the world lives in
        # the DB, props are files — a dangling id renders as a placeholder
        # on the client instead of silently losing the placement.
        pid = safe_prop_id(str(p.get("prop_id") or ""))
        at = p.get("at")
        if not pid or not isinstance(at, (list, tuple)) or len(at) != 2:
            continue
        au, av = _metre(at[0]), _metre(at[1])
        if au is None or av is None:
            continue
        entry: Dict[str, Any] = {"prop_id": pid, "at": [au, av]}
        # A placement is a PLACE too (plan-posen-plaetze.md): its markers are
        # addressed as "<placement.id>/<marker.id>", so the id must survive
        # every re-save, and an optional label names the piece in a chip.
        entry["id"] = _place_id(p.get("id"))
        label = str(p.get("label") or "").strip()[:60]
        if label:
            entry["label"] = label
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
        # THE DEPTH CUT (§ B2 addendum 2026-08-23): how much of the prop's
        # DEPTH survives, and from which side. Half a table against a wall is
        # a placement property, not a second prop — the mesh is cut by a
        # clipping plane at render time, so the library keeps ONE table.
        # A whole prop is the statement of ABSENCE: keep 1.0 (and anything
        # unusable) writes no key, exactly like ``ground_offset_m``.
        keep = p.get("cut_keep")
        if keep is not None and f"{keep}".strip() != "":
            try:
                v = round(max(CUT_KEEP_MIN, min(1.0, float(keep))), 3)
            except (TypeError, ValueError):
                v = 1.0
            if v < 1.0:
                entry["cut_keep"] = v
                # Which HALF REMAINS. "front" is the side the plan draws at
                # the top of an unturned footprint (local −z), "back" the
                # bottom (local +z); the plane turns with the placement yaw.
                entry["cut_side"] = ("front" if str(p.get("cut_side") or "")
                                     .strip().lower() == "front" else "back")
        # WHICH model variant this placement shows (E2.3): a POSITION in the
        # prop's active variant list, resolved by ``scene_recipe._variant_index``
        # (out of range wraps, so a deleted mesh never makes a placement
        # disappear). Only a manual placement carries it — a scattered copy
        # derives its variant from the seed at compose time.
        var = p.get("variant")
        if var is not None and f"{var}".strip() != "":
            try:
                entry["variant"] = max(0, int(var))
            except (TypeError, ValueError):
                pass
        # Scatter fields survive only complete (count + seed) and within
        # the budget — a truncated count keeps what still fits.
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
    return placements[:100]


# Everything a ROOM layout may carry and the ground layout may not (§ A13a).
# Named explicitly so the log line can say what was thrown away — a silently
# vanishing outline costs the author their work.
_GROUND_FORBIDDEN = (
    "x", "y", "w", "d", "outline", "outline_curves", "openings", "surfaces",
    "level", "rotation", "model_at", "model_offset_y", "floor_offset_y",
    "always_visible", "no_walls", "clip_model", "edge_blend_m",
)


def sanitize_ground_layout(raw: Any) -> Dict[str, Any]:
    """The REDUCED layout of the ground room (§ A13a) — props and markers,
    nothing else.

    The ground is the surface no room takes up: it has no rectangle, so it
    has no min corner either, and ``props[].at`` / ``markers[].at`` are
    LOCATION-LOCAL METRES directly (the frame ``map3d.boundary`` lives in).
    Everything a room's geometry consists of is meaningless here and is
    dropped WITH A LOG LINE — the placements survive; a hand-posted outline
    does not turn the yard into a room.

    Empty result means "no layout": a ground carrying neither a placement nor
    a marker is exactly the ground of § A13 and stores nothing at all.
    """
    if not isinstance(raw, dict):
        return {}
    stripped = [key for key in _GROUND_FORBIDDEN if key in raw]
    if stripped:
        logger.info("ground layout: dropped room-geometry field(s) %s — the "
                    "ground has no rect, its frame IS the location (§ A13a)",
                    ", ".join(stripped))
    out: Dict[str, Any] = {}
    placements = _sanitize_props(raw.get("props"))
    if placements:
        out["props"] = placements
    markers = _sanitize_markers(raw.get("markers"))
    if markers:
        out["markers"] = markers
    return out


def _sanitize_opening(raw: Any) -> Optional[Dict[str, Any]]:
    """Whitelist + coerce ONE wall opening (door / window / passage). Returns
    None for an invalid entry so the caller can drop it individually.

    - ``edge``: 'N'|'S'|'E'|'W' (rectangle) OR an int >= 0 (polygon edge index),
    - ``at``: 0..1 along the edge (centre of the opening) — the ONE ratio the
      metric wave (v6 Nr. 2) deliberately left alone: it is relative to an
      edge, not a size in the world,
    - ``width_m`` / ``height_m``: 0.4..10 m,
    - ``sill_m``: 0..3 m (door = 0, window ≈ 0.9), default 0,
    - ``type``: 'door' | 'window' | 'passage',
    - ``to`` (optional str): connectivity target (room id or 'outside'),
    - ``prop_id`` (optional str): a frame/leaf prop scaled onto the opening,
    - ``door_prop`` (optional): only ``'none'`` — "nothing in this door",
      which is what keeps the LOCATION's ``default_door_prop_id`` out of it
      AND, since 2026-08-29, the plain leaf with it: the hole stays an empty
      gap (``scene_recipe.door_has_leaf``). An absent field means "nothing
      chosen", i.e. the default applies — and where the location names no
      door prop, that is the plain leaf (``scene_recipe.door_prop_id``),
    - ``hinge`` (optional): ``'left'`` | ``'right'``, the side the door prop
      turns about, read against the doorway's own direction; absent = left.

    What the door prop SHOWS is no statement of the opening either (D3) — it
    belongs to the prop, so an opening that still brings ``slot_values`` loses
    them here, exactly like a room placement.
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
    # THE THREE-VALUED DOOR PROP (2026-08-27): only the explicit "none" is
    # stored — every other value is "nothing chosen", and that is the state
    # the location default fills.
    if str(raw.get("door_prop") or "").strip().lower() == "none":
        out["door_prop"] = "none"
    hinge = str(raw.get("hinge") or "").strip().lower()
    if hinge in ("left", "right"):
        out["hinge"] = hinge
    return out


def _sanitize_rooms_layout(rooms: Any) -> Any:
    """Apply the layout sanitizer to every room dict in place (rooms pass
    through add_location verbatim otherwise). Invalid layouts are dropped.

    THE GROUND ROOM CARRIES A REDUCED LAYOUT (§ A13a): props and markers only,
    positioned in LOCATION-LOCAL metres. It still has no geometry of its own —
    a rect, an outline or an opening on the ground would put walls, a plate
    and doorways on the location's open surface, which the contract says it
    has none of — so ``sanitize_ground_layout`` strips those fields and keeps
    the placements. The floor-plan editor offers exactly that reduced set;
    this is the same rule for a hand-made API call.
    """
    if not isinstance(rooms, list):
        return rooms
    for room in rooms:
        if not isinstance(room, dict) or "layout" not in room:
            continue
        if room.get("id") == GROUND_ROOM_ID:
            ground = sanitize_ground_layout(room.get("layout"))
            if ground:
                room["layout"] = ground
            else:
                room.pop("layout", None)
            continue
        lay = _sanitize_room_layout(room.get("layout"))
        if lay:
            room["layout"] = lay
        else:
            room.pop("layout", None)
    return rooms


# ``_require_scale_anchor`` is GONE with contract v6 Nr. 2: a room layout
# carries its own metres, so there is nothing left for a plan width to anchor.
# ``plan_width_m`` survives only as the DERIVED bounding-box width of the
# location boundary (see ``_sanitize_map3d``), never as a precondition.


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
    default_door_prop_id = data.get("default_door_prop_id")
    indoor = data.get("indoor")
    terrain = data.get("terrain")
    map3d = data.get("map3d")
    npc_slots = data.get("npc_slots")
    if not location_name:
        raise HTTPException(status_code=400, detail="Name missing")
    if not isinstance(rooms, list):
        raise HTTPException(status_code=400, detail="rooms must be a list")
    _sanitize_rooms_layout(rooms)

    location = add_location(location_name, description, rooms=rooms,
                            image_prompt_day=image_prompt_day,
                            image_prompt_night=image_prompt_night,
                            image_prompt_map=image_prompt_map,
                            image_prompt_map_2d=image_prompt_map_2d,
                            image_prompt_building=image_prompt_building,
                            # A caller that generates places in bulk (a map
                            # draft's stubs) says so: a name it repeats is a
                            # second place, not an edit of the first.
                            create_new=bool(data.get("create_new")))

    # Set extra fields directly in the location
    _has_extra = (danger_level is not None or event_settings is not None
                  or outfit_type is not None or knowledge_item_id is not None
                  or passable is not None
                  or entry_room is not None or indoor is not None
                  or default_door_prop_id is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None
                  or terrain is not None
                  or map3d is not None or npc_slots is not None)
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
                if default_door_prop_id is not None:
                    # THE PLACE'S OWN DOOR (2026-08-27): every door opening
                    # that names no prop of its own gets this one, unless it
                    # opts out with ``door_prop: "none"``. Normalized through
                    # the ONE prop-id rule, so a typo cannot become a
                    # directory name; empty = no default.
                    from app.core.props import safe_prop_id
                    _l["default_door_prop_id"] = safe_prop_id(
                        str(default_door_prop_id or ""))
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
                if npc_slots is not None:
                    # The NPC slots of this place (plan-npc-auto-spawn.md § 1).
                    # Sanitized by the one function the spawn logic reads them
                    # with, so what the editor saves and what the trigger
                    # counts can never be two different shapes.
                    from app.core.npc_spawn import normalize_slots
                    _slots = normalize_slots(npc_slots)
                    if _slots:
                        _l["npc_slots"] = _slots
                    else:
                        _l.pop("npc_slots", None)
                break
        _save_world_data(wdata)
        # The seat inventory reads this layout — drop the cached one.
        from app.core import places; places.invalidate()
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
    default_door_prop_id = data.get("default_door_prop_id")
    indoor = data.get("indoor")
    terrain = data.get("terrain")
    map3d = data.get("map3d")
    npc_slots = data.get("npc_slots")

    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    if new_name:
        rename_location(location_id, new_name)

    # Update description, rooms and image prompts if provided
    if rooms is not None:
        _sanitize_rooms_layout(rooms)
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
                  or default_door_prop_id is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None
                  or terrain is not None
                  or map3d is not None or npc_slots is not None)
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
                if default_door_prop_id is not None:
                    # THE PLACE'S OWN DOOR (2026-08-27): every door opening
                    # that names no prop of its own gets this one, unless it
                    # opts out with ``door_prop: "none"``. Normalized through
                    # the ONE prop-id rule, so a typo cannot become a
                    # directory name; empty = no default.
                    from app.core.props import safe_prop_id
                    _l["default_door_prop_id"] = safe_prop_id(
                        str(default_door_prop_id or ""))
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
                if npc_slots is not None:
                    # The NPC slots of this place (plan-npc-auto-spawn.md § 1).
                    # Sanitized by the one function the spawn logic reads them
                    # with, so what the editor saves and what the trigger
                    # counts can never be two different shapes.
                    from app.core.npc_spawn import normalize_slots
                    _slots = normalize_slots(npc_slots)
                    if _slots:
                        _l["npc_slots"] = _slots
                    else:
                        _l.pop("npc_slots", None)
                break
        _save_world_data(wdata)
        from app.core import places; places.invalidate()

    updated = get_location_by_id(location_id)
    return {"status": "success", "location": updated}


def seed_missing_boundaries() -> Dict[str, Any]:
    """Give every placed location that has no DRAWN boundary the centred
    square its legacy ``plan_width_m`` described — the repair gesture for
    worlds authored before contract v6.

    THE TRANSITION SQUARE IS GONE (2026-08-19): ``effective_boundary``
    synthesizes nothing any more, so a location that was never drawn has no
    area at all — it vanishes from the nav grid, from ``location_at_point``,
    from the plateau pass and from every renderer, and stands on the map as a
    bare pin. This turns that same square into a REAL, editable boundary, and
    it is an EXPLICIT user action ("Seed missing boundaries" in the map
    editor), never a fallback reader: after the run the shape is stored, the
    author can drag its vertices, and nothing is derived behind their back.

    Seeded is a location that is PLACED (finite ``pos_x``/``pos_z``), has no
    valid boundary, and carries a positive ``plan_width_m``. The square is
    the one the synthesis produced — corners (±w/2, ±w/2) in LOCAL metres,
    clockwise in map view — and it is written through the ordinary save path
    (``update_location_with_extras`` → ``_sanitize_map3d``), so the winding,
    the centimetre rounding and the derived width are the sanitizer's, not a
    second implementation's.

    A location without a width has nothing to seed FROM: an invented edge
    would be a shape the author never chose. It is reported separately so the
    editor can say why it was left alone.
    """
    from app.core.world_geometry import placed_boundary, polygon_points

    seeded: List[str] = []
    skipped: List[str] = []
    for loc in list_locations():
        loc_id = loc.get("id") or ""
        if not loc_id:
            continue
        px, pz = loc.get("pos_x"), loc.get("pos_z")
        if px is None or pz is None:
            continue                        # unplaced: not on the map at all
        try:
            if not (math.isfinite(float(px)) and math.isfinite(float(pz))):
                continue
        except (TypeError, ValueError):
            continue
        map3d = loc.get("map3d") if isinstance(loc.get("map3d"), dict) else {}
        if polygon_points(map3d.get("boundary")) is not None:
            continue                        # already drawn — never touched
        try:
            width = float(map3d.get("plan_width_m") or 0)
        except (TypeError, ValueError):
            width = 0.0
        if not (math.isfinite(width) and width > 0):
            skipped.append(loc_id)
            continue
        half = round(width / 2.0, 2)
        square = [[-half, -half], [half, -half], [half, half], [-half, half]]
        update_location_with_extras(loc_id, {"map3d": {**map3d,
                                                       "boundary": square}})
        # Measured at the consumer, not at the writer: the location counts as
        # seeded only when the stored world answers with a real area.
        if placed_boundary(get_location_by_id(loc_id) or {}) is not None:
            seeded.append(loc_id)
        else:
            skipped.append(loc_id)
    return {"status": "success", "seeded": seeded, "skipped": skipped}


# --- World-level settings ---------------------------------------------------

def build_world_settings_payload() -> Dict[str, Any]:
    """Return world settings (news channel).

    Temperature and weather used to live here as world-wide values; they are
    per-season now (`game_seasons` in the world config, Admin settings →
    Game calendar — seasons).
    """
    from app.models.world import get_world_setting
    return {
        "news": {
            # Presentation style of the player news channel.
            "style": get_world_setting("news.style", "modern") or "modern",
            "title": get_world_setting("news.title", "") or "",
        },
        "choices": {
            "news_style": ["modern", "newspaper", "flyer"],
        },
    }


def apply_world_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Set world settings from a parsed request body."""
    from app.models.world import set_world_setting
    news = data.get("news") or {}
    if "style" in news:
        v = (news.get("style") or "").strip().lower()
        if v in ("modern", "newspaper", "flyer"):
            set_world_setting("news.style", v)
    if "title" in news:
        set_world_setting("news.title", (news.get("title") or "").strip())
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
            # Purpose category (e.g. "inpaint") + default prompt — the render
            # dialogs filter on the category and prefill the prompt from it.
            "category": getattr(b, "category", "") or "",
            "image_family": getattr(b, "image_family", "") or "",
            "prompt": getattr(b, "default_prompt", "") or "",
            "ref_slot_count": int(getattr(b, "ref_slot_count", 0) or 0),
            # RESOLVED tri-state (auto/yes/no -> bool, one rule in
            # negation_fold.backend_supports_negative, read off the backend
            # instance). False = no negative input: the dialog hides the
            # field and the composer folds the negative into the prompt.
            "supports_negative_prompt": bool(
                getattr(b, "supports_negative_prompt", True)),
            "target_model": get_target_model(
                getattr(b, "image_family", "") or "", getattr(b, "model", "") or ""),
        }
        # Use-case styles resolved for THIS backend (family + model): the
        # dialogs show the style as an editable prompt part, so the FINAL
        # prompt is fully visible before generating (house rule) — submit
        # sets settings_applied and the server prepends nothing.
        from app.core.config import resolve_use_case_style as _rucs
        _styles = {}
        for _uc in ("location", "map", "building", "building_outdoor",
                    "room_model", "room_model_outdoor",
                    "building_back", "building_side",
                    "building_outdoor_back", "building_outdoor_side",
                    "room_model_back", "room_model_side",
                    "room_model_outdoor_back", "room_model_outdoor_side"):
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
    # Default preselection for locations
    loc_default = os.environ.get("LOCATION_IMAGEGEN_DEFAULT", "").strip()
    result = {"options": options}
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
    """Set the type of a gallery image (day/night/map_2d/building-<view> or
    empty)."""
    from app.core.view_prompts import BUILDING_TYPES
    if image_type and image_type not in ("day", "night", "map_2d", *BUILDING_TYPES):
        raise HTTPException(
            status_code=400,
            detail="Type must be 'day', 'night', 'map_2d', one of "
                   + ", ".join(f"'{t}'" for t in BUILDING_TYPES) + " or empty")

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
    from app.core.prompt_compose import outdoor_conditions as _conditions
    # An open-air location is painted in TODAY's weather; an interior is not
    # (its light comes from the use-case style, and there is no snow indoors).
    _composed = _compose(use_case="location", subject=prompt, backend=backend,
                         conditions=_conditions(is_outdoor_room(location, "")))
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
    from app.core.view_prompts import building_view
    description = ""
    if room_id:
        room = get_room_by_id(location, room_id)
        if room:
            # Room with prompt type: prefer the room's day/night prompt
            if prompt_type == "day":
                description = (room.get("image_prompt_day", "") or "").strip()
            elif prompt_type == "night":
                description = (room.get("image_prompt_night", "") or "").strip()
            elif building_view(prompt_type):
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
    elif not description and prompt_type == "map_2d":
        description = location.get("image_prompt_map_2d", "").strip()
    elif not description and building_view(prompt_type):
        description = location.get("image_prompt_building", "").strip()
    if not description:
        description = location.get("description", location.get("name", fallback))
    return description


def gallery_use_case(location: Dict[str, Any], room_id: str,
                     prompt_type: str) -> str:
    """The use case a gallery render belongs to.

    A building-view render FOR A ROOM is the room-model source — its own use
    case (open cutaway); the building exterior style would demand a "single
    building" even for a park room. Both split further on the indoor/outdoor
    flag (room overrides location): an outdoor location's building is a
    scene diorama, an outdoor room an open-air area. The VIEW the type names
    (``building-back`` …) then picks the base's back/side sibling
    (``view_prompts.view_use_case``); the front keeps the base.
    """
    from app.core.view_prompts import building_view, view_use_case
    view = building_view(prompt_type)
    if view:
        base = (("room_model_outdoor" if is_outdoor_room(location, room_id)
                 else "room_model") if room_id
                else ("building_outdoor" if is_outdoor_room(location, "")
                      else "building"))
        return view_use_case(base, view)
    return "map" if prompt_type == "map_2d" else "location"


def is_outdoor_room(location: Dict[str, Any], room_id: str) -> bool:
    """Indoor/outdoor of a room (falls back to the location's own flag)."""
    from app.models.world import resolve_indoor_flag
    room = get_room_by_id(location, room_id) if room_id else None
    return resolve_indoor_flag(location, room) == "outdoor"


def gallery_conditions(location: Dict[str, Any], room_id: str,
                       use_case: str) -> str:
    """The outdoor weather clause for a gallery render — ``""`` when none.

    Two conditions have to hold. The render must be a PICTURE OF THE WORLD
    (use case ``location``): the ``room_model*``/``building*``/``map`` cases
    are isolated 3D-asset renders on a plain ground with deliberately flat,
    shadowless lighting, and a snowstorm would wreck exactly that. And the
    place has to be open air — the room's flag wins over the location's.
    """
    from app.core.prompt_compose import outdoor_conditions
    return outdoor_conditions(use_case == "location"
                              and is_outdoor_room(location, room_id))


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
    prompt_type = (data.get("prompt_type") or "building-front").strip()
    use_case = ((data.get("use_case") or "").strip()
                or gallery_use_case(location, room_id, prompt_type))
    subject = (data.get("subject") or "").strip() or resolve_gallery_subject(
        location, room_id, prompt_type, location_id)

    # A back/side view says so at the head of the subject (the use case only
    # knows "back" or "side"; left vs right is this phrase).
    from app.core.view_prompts import building_view, view_subject
    _view = building_view(prompt_type)
    if _view:
        subject = view_subject(_view, subject)

    # The regenerate dialog needs the bare SUBJECT: its prompt is a literal
    # adjustment order, so it gets no style, no hint and no guard — but the
    # resolution chain must still live in exactly one place.
    if data.get("subject_only"):
        return {"prompt": subject, "negative": "", "warnings": [],
                "use_case": use_case, "llm_composed": False,
                "cache_hit": False, "supports_negative_prompt": True,
                "negative_folded": []}

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
                        hints=hints,
                        conditions=gallery_conditions(location, room_id,
                                                      use_case))

    # LLM stage: explicit request from the dialog button wins; without the
    # field the use-case flag decides (auto-prefill). Explicit false = off.
    from app.core import config as _cfg
    _want = data.get("llm")
    if (bool(_want) if _want is not None
            else _cfg.use_case_llm_compose(use_case)):
        from app.core.prompt_compose_llm import llm_compose
        composed = llm_compose(composed, use_case=use_case, subject=subject,
                               family=composed.meta.get("family", "keywords"),
                               force=bool(data.get("recompose")))

    # Backends without a negative input: the preview must show what the
    # engine will really see (final-prompt rule) — fold here, exactly like
    # the handoff does. The dialog then hides the negative field. Folding
    # twice is a no-op: the handoff skips every item the prompt already
    # negates, so the same terms are never appended a second time.
    prompt_out, negative_out = composed.prompt, composed.negative
    folded: List[str] = []
    supports_negative = True
    if backend is not None:
        supports_negative = bool(
            getattr(backend, "supports_negative_prompt", True))
    if negative_out and not supports_negative:
        from app.imagegen.negation_fold import fold_negatives
        prompt_out, folded = fold_negatives(
            prompt_out, negative_out, composed.meta.get("family", "keywords"))
        negative_out = ""

    return {"prompt": prompt_out, "negative": negative_out,
            "warnings": composed.warnings, "use_case": use_case,
            "llm_composed": bool(composed.meta.get("llm_composed")),
            "cache_hit": bool(composed.meta.get("cache_hit")),
            "supports_negative_prompt": supports_negative,
            "negative_folded": folded}


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

        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        # Prompt source: custom_prompt > room+type > room > prompt type > location description.
        # Subject only — framing/style come from the use case (map/location).
        prompt = custom_prompt or resolve_gallery_subject(
            location, room_id, prompt_type, location_name)
        from app.core.view_prompts import building_view, view_subject
        _view = building_view(prompt_type)
        # Composed subjects get the view phrase; a dialog prompt arrives final
        # (settings_applied) and already carries it from the preview.
        if _view and not custom_prompt:
            prompt = view_subject(_view, prompt)

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
        if workflow_name:
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
        # Use-case style/negative: a map tile -> "map", otherwise the
        # location background.
        from app.core import config as _cfg
        _uc_name = gallery_use_case(location, room_id, prompt_type)
        _ucp = _cfg.resolve_use_case_style(
            _uc_name, getattr(backend, "image_family", "") or "",
            backend_model=getattr(backend, "model", "") or "")
        _compose_meta: Dict[str, Any] = {}
        _warnings: List[str] = []
        if _is_regen:
            full_prompt = prompt
            negative = ""
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
            if room_id:
                _sh = room_shape_hint(location, get_room_by_id(location, room_id),
                                      outdoor=is_outdoor_room(location, room_id))
                if _sh:
                    _hints.append(_sh)
            _composed = _compose(use_case=_uc_name, subject=prompt,
                                 backend=backend, hints=_hints,
                                 conditions=gallery_conditions(
                                     location, room_id, _uc_name))
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
        elif _view:
            # Square so the whole subject fits with a margin — every building
            # view feeds the image-to-3D pass (like the T-pose reference), which
            # needs the full silhouette in frame, not a 16:9 crop.
            params["image_use_case"] = _uc_name
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

        # A back/side view may take the FRONT render as its appearance
        # reference (design 2026-09-02) — style stays, unlike the regenerate
        # self-reference above. Only where the backend has a slot and the
        # file exists; otherwise the view renders from text alone.
        _front_ref = (data.get("front_reference") or "").strip()
        if _view and _view != "front" and _front_ref:
            if "/" in _front_ref or ".." in _front_ref:
                logger.warning("front_reference rejected (path): %s", _front_ref)
            elif int(getattr(backend, "ref_slot_count", 0) or 0) < 1:
                logger.info("front_reference ignored: backend %s has no "
                            "reference slot", backend.name)
            else:
                _front_path = get_gallery_dir(location_name) / _front_ref
                if _front_path.exists():
                    params["reference_images"] = {
                        "input_reference_image_1": str(_front_path)}
                    logger.info("Front reference in slot 1 for %s view: %s",
                                _view, _front_ref)
                else:
                    logger.warning("front_reference missing: %s", _front_ref)

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
            if not _is_replace and prompt_type != "map_2d" and not _view:
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

            # Set the image type when prompt_type is given
            # (day/night/map_2d/building-<view>)
            if prompt_type in ("day", "night", "map_2d") or _view:
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

        # Weather of the current season on top — but ONLY outdoors and ONLY
        # the weather. The time of day is the one thing the user picked here
        # (target_type), so the clock's own day bucket must stay out of it or
        # a "night" variant would arrive carrying "morning".
        if is_outdoor_room(location, source_room_id):
            from app.core.timeutils import game_time as _gt
            prompt += f", {_gt().atmosphere()['label']}"


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
                                      is_character_sleeping, is_temporary_npc,
                                      set_is_sleeping)
    from app.models.account import is_player_controlled
    from app.models.world import (set_world_sleeping, set_world_setting,
                                  WORLD_SLEEP_PRIOR_KEY)
    prior, slept = [], []
    for name in list_available_characters():
        try:
            if is_player_controlled(name):
                continue
            # A temporary NPC has no RP layer to rest: no moods, no status
            # effects — and no way back up. Sleep/WakeUp are ALWAYS_LOAD
            # verbs, i.e. off until a character's own skill config switches
            # them on, and the standard set of a temporary NPC never does
            # (plan-npc-leben task 3). It stays awake at its standing task
            # for the handful of hours it exists.
            if is_temporary_npc(name):
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
