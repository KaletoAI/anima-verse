"""Where a character STANDS in a room when no place marker holds it
(plan-animationen-echtzeit-stehplatz.md T4, decision E2).

Until now the server knew no room position at all for an unseated character:
``places.release`` left the point where it was and ``save_character_current_room``
wrote none, so every client had to invent one. The 3D client did — a 6 x 6
raster over the room's bounding box, handed out by the character's alphabetical
index, blind to furniture — which put figures into tables and, on an L-shaped
room, against the wall nearest the bounding-box middle. Two renderers would
have had to invent the same thing twice, so the rule moved here: the SERVER
picks a free standing point and writes it into ``pos``; a client draws the
figure there (contract § A1.4).

THE RULE, in four constants and one order:

* candidates lie on a :data:`STAND_GRID_M` raster over the bounding box of the
  room polygon, in WORLD metres;
* a candidate is FREE when it is inside the polygon and at least
  :data:`WALL_CLEAR_M` from every polygon edge, outside every floor prop's
  turned footprint grown by :data:`BODY_R_M`, outside every door zone, and at
  least :data:`MATE_CLEAR_M` from everybody else standing in the room;
* the free candidate NEAREST to ``near`` wins; a tie falls to the larger wall
  clearance, then to the smallest x, then to the smallest z;
* ``near`` itself, when it is free, wins outright — nobody walks for nothing.

``near`` is the character's current point: the arrival point when it enters
a room, the seat it just left when a pose ends. One rule, and both "stands up
and stays beside the chair" and "comes in and stops near the door" fall out of
it. The one refinement (plan-bruecken-root-motion Task 7): when the pose's
EXIT clip carries the figure off the seat (a bridge with root motion,
``get-up-chair``), ``near`` is where that clip sets it down —
:func:`bridge_stand_point`, the seat plus the clip's travel turned by the
seat's facing — because that is where the client's figure already stands
when the clip ends.

:func:`pick_stand` is PURE — polygon, blockers, door zones, mates, near in, a
point out — so ``scripts/smoke_room_stand.py`` can check it without a world.
The loader below is the thin half: it composes the room's recipe, turns
polygon, footprints and door zones into world metres, and :func:`stand_up`
writes the result through ``set_character_pos``.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core import furnish_geometry as fg
from app.core.log import get_logger

logger = get_logger("room_stand")

#: Raster step of the candidate grid, in metres.
STAND_GRID_M = 0.25
#: How far a standing figure keeps off every polygon edge, in metres.
WALL_CLEAR_M = 0.35
#: The radius a standing body occupies — every prop footprint grows by it.
BODY_R_M = 0.30
#: How far two characters in one room keep apart, in metres.
MATE_CLEAR_M = 0.70

Point = Tuple[float, float]
#: A blocker is the prop's stored footprint box: ``{"at": [x, z], "yaw": deg,
#: "width_m": w, "depth_m": d}`` — the very shape ``props._footprint_contains``
#: tests against.
Blocker = Dict[str, Any]


def _in_footprint(px: float, pz: float, box: Blocker, grow: float) -> bool:
    """Is the point inside the prop's TURNED footprint, grown by ``grow``?

    The same arithmetic as ``props._footprint_contains`` (§ A1.1 / § B2 step 3):
    a prop is drawn with ``rotation.y = +rad(yaw)``, so a WORLD point is tested
    by applying the INVERSE turn and comparing against the half extents. Point
    and box are in one frame — here both are world metres.

    ``grow`` widens the box by the body radius on every side, which is the
    Minkowski sum with a square rather than with a disc: a figure standing
    diagonally off a corner is refused a few centimetres earlier than the
    circle would refuse it. Deliberate — it is the cheap, deterministic
    over-approximation, and it never lets a body into the table.
    """
    th = math.radians(float(box.get("yaw") or 0.0))
    dx = px - float(box["at"][0])
    dz = pz - float(box["at"][1])
    cos, sin = math.cos(th), math.sin(th)
    lx = dx * cos - dz * sin
    lz = dx * sin + dz * cos
    return (abs(lx) <= float(box.get("width_m") or 0.0) / 2.0 + grow
            and abs(lz) <= float(box.get("depth_m") or 0.0) / 2.0 + grow)


def _edge_clearance(pt: Point, poly: Sequence[Point]) -> float:
    """Distance to the NEAREST polygon edge — unsigned, so it says the same
    just inside and just outside the wall (like ``scene_recipe._ring_clearance``)."""
    return min(fg.point_segment_distance(pt, poly[i], poly[(i + 1) % len(poly)])
               for i in range(len(poly)))


def _free(pt: Point, poly: Sequence[Point], blockers: Sequence[Blocker],
          door_zones: Sequence[Sequence[Point]],
          mates: Sequence[Point]) -> Optional[float]:
    """The candidate's wall clearance when it is free, else None.

    The four conditions in the order they get cheaper to fail on: inside the
    hull with wall clearance, out of the furniture, out of the door zones, away
    from the neighbours.
    """
    if not fg.point_in_poly(pt, poly):
        return None
    clear = _edge_clearance(pt, poly)
    if clear < WALL_CLEAR_M:
        return None
    for box in blockers:
        if _in_footprint(pt[0], pt[1], box, BODY_R_M):
            return None
    for zone in door_zones:
        if len(zone) >= 3 and fg.point_in_poly(pt, zone):
            return None
    for m in mates:
        if math.dist(pt, m) < MATE_CLEAR_M:
            return None
    return clear


def pick_stand(polygon: Sequence[Sequence[float]],
               blockers: Sequence[Blocker],
               door_zones: Sequence[Sequence[Sequence[float]]],
               mates: Sequence[Sequence[float]],
               near: Sequence[float]) -> Optional[Point]:
    """The free standing point nearest ``near``, or None when the room has
    none. PURE — every argument is plain geometry in ONE frame (world metres
    in the running server).

    ``near`` unchanged when it is itself free: standing up must not make a
    figure walk across the room, and entering a room must not pull it off the
    doorstep it arrived on.
    """
    poly: List[Point] = [(float(p[0]), float(p[1])) for p in polygon]
    if len(poly) < 3:
        return None
    pins: List[Point] = [(float(m[0]), float(m[1])) for m in mates]
    zones = [[(float(p[0]), float(p[1])) for p in z] for z in door_zones]
    at = (float(near[0]), float(near[1]))
    if _free(at, poly, blockers, zones, pins) is not None:
        return at
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    # The raster is anchored on the grid itself (``floor(min / step) * step``),
    # not on the bounding box, so the same room yields the same candidates
    # whatever its polygon's first vertex is.
    x0 = math.floor(min(xs) / STAND_GRID_M) * STAND_GRID_M
    z0 = math.floor(min(zs) / STAND_GRID_M) * STAND_GRID_M
    nx = int((max(xs) - x0) / STAND_GRID_M) + 1
    nz = int((max(zs) - z0) / STAND_GRID_M) + 1
    best: Optional[Tuple[Tuple[float, float, float, float], Point]] = None
    for i in range(nx + 1):
        x = x0 + i * STAND_GRID_M
        for j in range(nz + 1):
            z = z0 + j * STAND_GRID_M
            clear = _free((x, z), poly, blockers, zones, pins)
            if clear is None:
                continue
            # Nearest to `near` first; a tie goes to the larger wall clearance,
            # then to the smallest x, then to the smallest z. Rounded so that
            # two candidates the same distance away really compare equal.
            key = (round(math.dist((x, z), at), 6), -round(clear, 6),
                   round(x, 6), round(z, 6))
            if best is None or key < best[0]:
                best = (key, (x, z))
    return best[1] if best else None


# ------------------------------------------------------------------ the loader


#: A floor prop no higher than this is stepped over, not walked around
#: (plan-prop-collision.md) — a rug, a threshold, a flat kerb.
_BLOCKER_MIN_H_M = 0.3


def _blockers(recipe: Dict[str, Any], cx: float, cz: float,
              yaw: float) -> List[Blocker]:
    """The room's floor props as WORLD-metre footprint boxes.

    The selection is the one ``plan-prop-collision.md`` states for its
    ``blockers[]``: mount ``floor``, no ``walkable`` tag, higher than
    :data:`_BLOCKER_MIN_H_M`. A rug is walked over, a walkable platform is
    stood on, a table is not.

    A placement's ``at``/``yaw`` are recipe-local (the scene frame IS the
    location's local frame), so the point goes through ``local_to_world`` and
    the turn simply adds — ``R_y(a)·R_y(b) = R_y(a+b)``, the same composition
    ``places._compose`` applies to a marker's compass facing.
    """
    from app.core import props as prop_store
    from app.core.world_geometry import local_to_world
    # ONE library record per prop for the whole room — a scattered wood is
    # twenty placements of one pine.
    records: Dict[str, Dict[str, Any]] = {}
    out: List[Blocker] = []
    for p in recipe.get("placements") or []:
        dims = p.get("dims") or {}
        try:
            w = float(dims.get("width_m") or 0.0)
            d = float(dims.get("depth_m") or 0.0)
            h = float(dims.get("height_m") or 0.0)
        except (TypeError, ValueError):
            continue
        if w <= 0 or d <= 0 or h <= _BLOCKER_MIN_H_M:
            continue
        pid = str(p.get("prop_id") or "")
        if pid not in records:
            records[pid] = prop_store.get_prop(pid) or {}
        prop = records[pid]
        if (str(prop.get("mount") or "floor").strip().lower() or "floor") != "floor":
            continue
        if "walkable" in [str(t).lower() for t in (prop.get("tags") or [])]:
            continue
        at = p.get("at") or [0.0, 0.0]
        wx, wz = local_to_world(float(at[0]), float(at[1]), cx, cz, yaw)
        out.append({"at": [wx, wz], "yaw": (float(p.get("yaw") or 0.0) + yaw) % 360.0,
                    "width_m": w, "depth_m": d})
    return out


def _interior_ref(poly: Sequence[Point]) -> Point:
    """A point that is really INSIDE the polygon — what ``opening_zones`` needs
    to turn an edge normal inwards.

    The area centroid where it lies inside (which it does for every rectangle
    and most drawn rooms), else the raster point with the largest wall
    clearance, else the vertex mean. An L-shaped room is exactly why the first
    answer is checked instead of trusted: its centroid can fall in the notch,
    and every door of that room would then get its zone pushed through the wall
    instead of into the room.
    """
    n = len(poly)
    twice = cx = cz = 0.0
    for i in range(n):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % n]
        cross = x0 * z1 - x1 * z0
        twice += cross
        cx += (x0 + x1) * cross
        cz += (z0 + z1) * cross
    if abs(twice) > 1e-9:
        cand = (cx / (3 * twice), cz / (3 * twice))
        if fg.point_in_poly(cand, poly):
            return cand
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    x0 = math.floor(min(xs) / STAND_GRID_M) * STAND_GRID_M
    z0 = math.floor(min(zs) / STAND_GRID_M) * STAND_GRID_M
    best: Optional[Tuple[float, Point]] = None
    for i in range(int((max(xs) - x0) / STAND_GRID_M) + 2):
        for j in range(int((max(zs) - z0) / STAND_GRID_M) + 2):
            pt = (x0 + i * STAND_GRID_M, z0 + j * STAND_GRID_M)
            if not fg.point_in_poly(pt, poly):
                continue
            clear = _edge_clearance(pt, poly)
            if best is None or clear > best[0] + 1e-9:
                best = (clear, pt)
    if best is not None:
        return best[1]
    return (sum(xs) / n, sum(zs) / n)


def room_geometry(location_id: str, room_id: str
                  ) -> Optional[Tuple[List[Point], List[Blocker], List[List[Point]]]]:
    """``(polygon, blockers, door_zones)`` of one room in WORLD metres, or None.

    None for a room the recipe gives no hull — an unplaced location (no pin, no
    world frame, exactly as in ``places._compose``), the yard (``__ground__``,
    which IS the plot and has no hull) and a storey corridor (its outline is
    the storey's, not a room's). Nobody is moved in those: the position stays
    what it was.
    """
    from app.core.room_recipe import compose_recipe
    from app.core.world_geometry import local_to_world
    from app.models.world import get_location_by_id
    loc = get_location_by_id(location_id)
    if not loc or loc.get("pos_x") is None or loc.get("pos_z") is None:
        return None
    rooms = [r for r in (loc.get("rooms") or []) if isinstance(r, dict)]
    room = next((r for r in rooms if str(r.get("id") or "") == room_id), None)
    if room is None:
        return None
    recipe = compose_recipe(room, [r for r in rooms if r is not room],
                            map3d=loc.get("map3d") or {})
    if not recipe or recipe.get("is_ground"):
        return None
    cx, cz = float(loc["pos_x"]), float(loc["pos_z"])
    yaw = float(loc.get("yaw_deg") or 0.0)
    poly = [local_to_world(float(p[0]), float(p[1]), cx, cz, yaw)
            for p in (recipe.get("outline") or [])]
    if len(poly) < 3:
        return None
    # The door zones are built on the WORLD polygon: ``local_to_world`` is a
    # turn plus a shift, so edge order and winding survive it and an opening's
    # ``edge``/``at`` still address the same stretch of wall.
    zones = [list(z.corners) for z in fg.opening_zones(
        poly, _interior_ref(poly), recipe.get("openings") or [])]
    return poly, _blockers(recipe, cx, cz, yaw), zones


def _mates(location_id: str, room_id: str, exclude: str) -> List[Point]:
    """Where everybody ELSE in the room stands — a character on a place marker
    counts with its SLOT, everybody else with its own point (``places._present``
    is the census: same location, same room, on the roster)."""
    from app.core import places
    from app.models.character import list_character_positions
    known = {p["id"]: p for p in places.room_places(location_id, room_id)}
    points = {r["name"]: (float(r["x"]), float(r["z"]))
              for r in list_character_positions()}
    out: List[Point] = []
    for name, prof in places._present(location_id, room_id):
        if name == exclude:
            continue
        held = prof.get("place")
        place = known.get(held.get("id")) if isinstance(held, dict) else None
        slot = places._held_slot(held, place, room_id) if place else None
        if slot == places.PAIR_SLOT:
            out.append(places.centre_of(place))
        elif isinstance(slot, int):
            sx, sz = place["slots"][slot]
            out.append((float(sx), float(sz)))
        elif name in points:
            out.append(points[name])
    return out


def free_stand_point(location_id: str, room_id: str, near: Sequence[float],
                     exclude: str = "") -> Optional[Point]:
    """The free standing point of ``location_id``/``room_id`` nearest ``near``,
    or None when the room offers none (and then nobody is moved).

    ``exclude`` is the character being placed — it must not keep itself out of
    its own room.
    """
    if not location_id or not room_id or near is None:
        return None
    try:
        geo = room_geometry(location_id, room_id)
    except Exception as e:                 # a broken layout must not break a move
        logger.warning("room_stand: geometry failed for %s/%s: %s",
                       location_id, room_id, e)
        return None
    if geo is None:
        return None
    poly, blockers, zones = geo
    return pick_stand(poly, blockers, zones, _mates(location_id, room_id, exclude),
                      near)


def bridge_offset(travel_m: Sequence[float], facing_deg: float,
                  scale: float) -> Tuple[float, float]:
    """World XZ by which a bridge clip carries a figure that faces
    ``facing_deg`` (compass: 0 = south +z, 90 = east +x) — the clip's travel
    (+Z forward, +X the figure's left) turned by the facing and scaled to
    the figure. PURE; the client turns its own offset the same way
    (``client3d/src/scene/bridgeTravel.ts`` ``toWorld``)."""
    a = math.radians(float(facing_deg or 0.0))
    tx, tz = float(travel_m[0]) * scale, float(travel_m[1]) * scale
    return (tx * math.cos(a) + tz * math.sin(a), -tx * math.sin(a) + tz * math.cos(a))


def bridge_scale(height_cm: Optional[float], ref_height_m: Optional[float]) -> float:
    """Figure size over the reference rig the clip was measured on; 1.0 when
    either number is unknown. PURE."""
    if not height_cm or not ref_height_m or height_cm <= 0 or ref_height_m <= 0:
        return 1.0
    return (float(height_cm) / 100.0) / float(ref_height_m)


def bridge_stand_point(name: str, place: Dict[str, Any], pose_key: str,
                       profile: Optional[Dict[str, Any]] = None
                       ) -> Optional[Tuple[float, float]]:
    """Where ``name`` stands once the exit clip of ``pose_key`` has carried it
    off ``place`` (a place as ``places.place_of`` returns it: ``facing``,
    ``x``, ``z``) — None when that clip stays on the spot, ramps (it walks
    off by itself) or nothing is configured. ``profile`` is loaded when not
    given."""
    from app.core.animation_clips import clip_ref_height_m, clip_travel_m
    from app.core.height import height_cm
    from app.core.travel_engine import exit_bridge_for_pose
    kind, _s = exit_bridge_for_pose(pose_key)
    if not kind:
        return None
    travel = clip_travel_m(kind)
    if travel == (0.0, 0.0):
        return None
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(name) or {}
    scale = bridge_scale(height_cm(profile), clip_ref_height_m(kind))
    dx, dz = bridge_offset(travel, float(place.get("facing") or 0.0), scale)
    return (float(place["x"]) + dx, float(place["z"]) + dz)


def stand_up(name: str, *, from_place: Optional[Dict[str, Any]] = None,
             from_pose_key: str = "") -> Optional[Point]:
    """THE WRITE PATH: put ``name`` on a free standing point of the room it is
    in, starting from where it stands right now — or, when it has just left
    a seat (``from_place``, the old profile field ``{"id", "slot",
    "room_id"}``, and ``from_pose_key``, the pose it held there) and that
    pose's exit clip carries the figure off the seat, from where the clip
    sets it down (:func:`bridge_stand_point`). Returns the point written, or
    None when nothing was written.

    Called from the three places a character ends up standing with no marker —
    ``places.release``, ``clear_pose_intent`` and ``interaction_engine.end_interaction``
    — plus every real room change (``save_character_current_room``). NEVER from
    a read path: a payload build must not move anybody.

    The write is ``set_character_pos(..., preserve_movement_target=True)``, the
    very call ``places.assign`` makes for a seat, and for the same two reasons:
    a journey that has just arrived must not cancel itself on its own standing
    point, and the point is checked with :func:`places.inside` first — a room
    authored past its location's boundary would otherwise EVICT the character
    from the location the write derives. Inside the current location the setter
    writes the two position columns and nothing else, so this cannot re-enter
    the caller (no location change, no pose reset, no party drag).
    """
    from app.core import places
    from app.models.character import get_character_pos, set_character_pos
    loc, room = places.where(name)
    if not loc or not room:
        return None
    pos = get_character_pos(name)
    if pos is None:
        return None
    here = (float(pos["x"]), float(pos["z"]))
    near = here
    if from_place and from_pose_key:
        # The seat is resolved from the field the caller just cleared — the
        # profile no longer holds it, so ``place_of`` would answer None.
        seat = places.resolve_place(name, from_place)
        stand = bridge_stand_point(name, seat, from_pose_key) if seat else None
        if stand is not None:
            near = stand
    point = free_stand_point(loc, room, near, exclude=name)
    # Nothing to write when the answer is where the character already stands
    # — compared with the CURRENT position, not with `near`: from a stand
    # point `near` is not where the character is.
    if point is None or (round(point[0], 2), round(point[1], 2)) == (
            round(here[0], 2), round(here[1], 2)):
        return None
    if not places.inside(loc, point[0], point[1]):
        logger.warning("room_stand: %s's stand point (%.2f, %.2f) in %s/%s lies "
                       "outside the location — not moved",
                       name, point[0], point[1], loc, room)
        return None
    set_character_pos(name, point[0], point[1], preserve_movement_target=True)
    return point
