"""Furnishing and reachability FINDINGS of one composed scene (2026-10-20).

The composer's ``problems`` (``scene_recipe._problems``) only ever looked at the
BUILDING: contour, doors, stairs, corridors. Everything a room holds went
unchecked, and a walk-through of Anima Divide found what that costs — mirrors
and towel racks hanging at floor height, ceiling lights lying on the wall
crowns, shelves turned to face the wall, a shower reaching half a metre through
the bathroom wall, a bed in front of a door and a cellar nobody could reach.
Every one of them was visible in 3D and none of them was said anywhere.

THE SAME LAW AS THE BUILDING FINDINGS: state, never repair. The composer hands
this module the recipes, walls and thresholds it has already built; the module
only measures them and answers a list of findings in the ``problems`` shape.
Nothing here moves a placement.

WHO SEES THEM. Furnishing findings carry ``scope: "editor"`` — they belong in
the floor-plan editor's findings list, not in a toast that greets a PLAYER
entering the location (``client3d`` skips that scope). ``room_unreachable`` is
a building finding and has no scope.

ONE FINDING PER ROOM AND KIND, with the placements it is about as their own
fields (``prop_ids`` = the placement ids, ``prop_names`` = their names): the
``message`` is translated as a whole sentence and must stay free of names and
numbers.

WHAT COUNTS (all measured on the recipe — ``at``/``yaw``/``offset_y`` already
composed, ``dims`` the placement's own variant, location-local metres):

* ``prop_outside_room`` — the footprint of a piece in a WALLED room reaches
  more than ``OUTSIDE_TOL_M2`` past the room's outline (through a wall).
* ``wall_prop_on_floor`` — ``mount: wall`` hanging lower than
  ``WALL_LOW_M`` (fireplaces, doors and curtains reach the floor on purpose;
  so does a wall piece taller than ``WALL_TALL_M``).
* ``wall_prop_facing_wall`` — a wall piece whose front (model +Z) does not
  point into the room from the wall it hangs on.
* ``wall_prop_off_wall`` — a wall piece whose back is more than
  ``WALL_GAP_M`` in front of the wall surface.
* ``ceiling_prop_through_ceiling`` / ``ceiling_prop_not_hanging`` —
  ``mount: ceiling`` whose top is above the room's wall top, or more than
  ``CEILING_DROP_M`` below it.
* ``prop_in_doorway`` — a floor piece in the metre in front of a door or
  passage on the room's side.
* ``prop_in_elevator`` — a floor piece inside the elevator shaft.
* ``prop_without_model`` — a placement whose prop is missing or has no mesh:
  the 3D client draws nothing there.
* ``room_unreachable`` — a room no chain of doors, passages, stairs, elevator
  halts, corridors and outdoor zones connects to the outside.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

WALL_HALF_M = 0.035          # half the room wall thickness (walls straddle the edge)
OUTSIDE_TOL_M2 = 0.02
WALL_LOW_M = 0.3
WALL_TALL_M = 1.6
WALL_GAP_M = 0.12
WALL_NEAR_M = 0.6            # how far a wall piece may be from an edge to "hang" on it
FACING_TOL_DEG = 30.0
CEILING_POKE_M = 0.03
CEILING_DROP_M = 0.4
DOOR_ZONE_M = 1.0
DOOR_ZONE_TOL_M2 = 0.03
ELEVATOR_TOL_M2 = 0.02
FLAT_M = 0.1                 # rugs and mats: walked over, never "in the way"
FLOOR_ON_PURPOSE = {"fireplace", "door", "curtain"}

MESSAGES = {
    "prop_outside_room":
        "Furniture in this room reaches through its walls. Move it back "
        "inside the floor plan.",
    "wall_prop_on_floor":
        "A wall-mounted piece hangs at floor height. Raise its height above "
        "the floor to where it would be mounted.",
    "wall_prop_facing_wall":
        "A wall-mounted piece faces the wall it hangs on. Turn it so its back "
        "is against the wall.",
    "wall_prop_off_wall":
        "A wall-mounted piece floats in front of the wall. Move it back onto "
        "the wall surface.",
    "ceiling_prop_through_ceiling":
        "A ceiling-mounted piece pokes through the ceiling. Lower it so its "
        "top sits just below the ceiling.",
    "ceiling_prop_not_hanging":
        "A ceiling-mounted piece does not reach the ceiling and floats in the "
        "room. Raise it until its top touches the ceiling.",
    "prop_in_doorway":
        "Furniture stands in front of a door and blocks the way through. Keep "
        "the metre in front of every door free.",
    "prop_in_elevator":
        "Furniture stands in the elevator shaft.",
    "prop_without_model":
        "A placed prop has no 3D model and is invisible in 3D. Give it a "
        "model or replace it.",
    "room_unreachable":
        "This room cannot be reached: no door, passage, stair or elevator "
        "connects it to the outside.",
}


# ── geometry (pure, location-local metres, x/z) ──────────────────────────

def _pt(value: Any) -> Optional[Tuple[float, float]]:
    """A stored ``[x, z]`` as two finite floats, or ``None`` for anything
    malformed — hand-edited data must not take the whole scene down."""
    try:
        x, z = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (x, z) if math.isfinite(x) and math.isfinite(z) else None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _area(poly: List[List[float]]) -> float:
    return abs(_signed(poly))


def _signed(poly: List[List[float]]) -> float:
    n = len(poly)
    if n < 3:
        return 0.0
    return sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
               for i in range(n)) / 2.0


def footprint(x: float, z: float, w: float, d: float, yaw: float) -> List[List[float]]:
    """The turned rectangle of a placement — three's Ry, the scene's own sense
    (``x = lx·cos θ + lz·sin θ``, ``z = −lx·sin θ + lz·cos θ``)."""
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    return [[x + lx * c + lz * s, z - lx * s + lz * c]
            for lx, lz in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def _overlap(convex: List[List[float]], subject: List[List[float]]) -> float:
    """Area of ``subject`` inside the CONVEX polygon ``convex`` — the
    composer's own Sutherland–Hodgman (exact for a convex clipper)."""
    from app.core.scene_recipe import clip_ring_to_outline
    return _area(clip_ring_to_outline(convex, subject))


def _front(yaw: float) -> Tuple[float, float]:
    a = math.radians(yaw)
    return math.sin(a), math.cos(a)


def _nearest_wall(x: float, z: float, outline: List[List[float]]
                  ) -> Optional[Tuple[float, Tuple[float, float]]]:
    """``(distance, inward normal)`` of the outline edge nearest to a point
    that projects onto it — ``None`` when there is none."""
    from app.core.scene_recipe import _point_in_polygon
    best = None
    n = len(outline)
    for i in range(n):
        ax, az = outline[i]
        bx, bz = outline[(i + 1) % n]
        ex, ez = bx - ax, bz - az
        length = math.hypot(ex, ez)
        if length < 1e-6:
            continue
        ux, uz = ex / length, ez / length
        t = (x - ax) * ux + (z - az) * uz
        if t < -1e-6 or t > length + 1e-6:
            continue
        nx, nz = -uz, ux
        mx, mz = ax + ux * length / 2, az + uz * length / 2
        if not _point_in_polygon(mx + nx * 0.05, mz + nz * 0.05, outline):
            nx, nz = -nx, -nz
        dist = (x - ax) * nx + (z - az) * nz
        if dist < -0.05:
            continue
        if best is None or dist < best[0]:
            best = (dist, (nx, nz))
    return best


# ── the placement facts ──────────────────────────────────────────────────

def _dims(placement: Dict[str, Any]) -> Tuple[float, float, float]:
    """Width/depth/height AS DRAWN: the variant's orientation fix turns the
    mesh before the uniform fit, so a fix of 90°/270° about y swaps the
    footprint's two sides (the library keeps them in the mesh's axes)."""
    raw = placement.get("dims") or {}
    w = _f(raw.get("width_m"), 0.6) or 0.6
    d = _f(raw.get("depth_m"), 0.6) or 0.6
    h = _f(raw.get("height_m"), 0.6) or 0.6
    from app.core.scene_recipe import _placement_entry
    entries = placement.get("variant_tiers") or []
    rot = (_placement_entry(placement, len(entries)).get("rotation") or {}) \
        if entries else {}
    try:
        if round(float(rot.get("y") or 0)) % 180 == 90:
            w, d = d, w
    except (TypeError, ValueError):
        pass
    return w, d, h


class _Collector:
    def __init__(self, location_id: str):
        self.location_id = location_id
        self.found: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add(self, kind: str, room_id: str, placement: Dict[str, Any]) -> None:
        key = (room_id, kind)
        entry = self.found.get(key)
        if entry is None:
            entry = self.found[key] = {
                "kind": kind, "location_id": self.location_id,
                "room_id": room_id, "scope": "editor",
                "prop_ids": [], "prop_names": [], "message": MESSAGES[kind]}
        pid = str(placement.get("id") or placement.get("prop_id") or "")
        if pid not in entry["prop_ids"]:
            entry["prop_ids"].append(pid)
            entry["prop_names"].append(str(placement.get("prop_name")
                                           or placement.get("prop_id") or ""))

    def out(self) -> List[Dict[str, Any]]:
        return list(self.found.values())


def _ceilings(walls: Iterable[Dict[str, Any]], storey: float) -> Dict[str, float]:
    """The wall TOP of every walled room over its own storey's floor."""
    top: Dict[str, float] = {}
    for w in walls:
        rid = str(w.get("room_id") or "")
        if not rid:
            continue
        floor = int(_f(w.get("level"))) * storey
        h = _f(w.get("base_y")) + _f(w.get("height")) - floor
        top[rid] = max(top.get(rid, 0.0), h)
    return top


def furnishing_problems(location_id: str, recipes: List[Dict[str, Any]],
                        walls: List[Dict[str, Any]],
                        doorways: List[Dict[str, Any]],
                        elevator: Any, storey: float,
                        prop_record: Callable[[str], Dict[str, Any]],
                        ) -> List[Dict[str, Any]]:
    """The furnishing findings of one scene (see the module docstring)."""
    found = _Collector(location_id)
    ceilings = _ceilings(walls, storey)
    shaft = None
    lift = _pt(elevator)
    if lift:
        from app.core.scene_recipe import ELEVATOR_SHAFT_M
        (ex, ez), half = lift, ELEVATOR_SHAFT_M / 2
        shaft = [[ex - half, ez - half], [ex + half, ez - half],
                 [ex + half, ez + half], [ex - half, ez + half]]
    for recipe in recipes:
        if recipe.get("is_ground"):
            continue
        room_id = str(recipe.get("room_id") or "")
        level = int(recipe.get("level") or 0)
        outline = recipe.get("outline") or []
        walled = not (recipe.get("always_visible") or recipe.get("no_walls"))
        ceiling = ceilings.get(room_id) if walled else None
        zones = _door_zones(doorways, level, outline) if walled else []
        for p in recipe.get("placements") or []:
            if p.get("scattered"):
                continue
            pid = str(p.get("prop_id") or "")
            if p.get("missing") or not p.get("has_model"):
                found.add("prop_without_model", room_id, p)
            if p.get("on"):
                continue          # stands on another piece — that one is measured
            record = prop_record(pid) or {}
            mount = str(record.get("mount") or "floor")
            category = str(record.get("category") or "").lower()
            w, d, h = _dims(p)
            at = _pt(p.get("at"))
            if at is None:
                continue
            x, z = at
            yaw = _f(p.get("yaw"))
            oy = _f(p.get("offset_y"))
            fp = footprint(x, z, w, d, yaw)
            flat = h < FLAT_M
            if walled and len(outline) >= 3 and not flat:
                if _area(fp) - _overlap(fp, outline) > OUTSIDE_TOL_M2:
                    found.add("prop_outside_room", room_id, p)
            if mount == "wall" and walled and len(outline) >= 3 \
                    and category not in ("door", "curtain"):
                if oy < WALL_LOW_M and h < WALL_TALL_M \
                        and category not in FLOOR_ON_PURPOSE:
                    found.add("wall_prop_on_floor", room_id, p)
                wall = _nearest_wall(x, z, outline)
                if wall and wall[0] <= WALL_NEAR_M + d / 2:
                    dist, (nx, nz) = wall
                    fx, fz = _front(yaw)
                    if fx * nx + fz * nz < math.cos(math.radians(FACING_TOL_DEG)):
                        found.add("wall_prop_facing_wall", room_id, p)
                    elif dist - d / 2 - WALL_HALF_M > WALL_GAP_M:
                        found.add("wall_prop_off_wall", room_id, p)
                elif wall and category not in FLOOR_ON_PURPOSE:
                    found.add("wall_prop_off_wall", room_id, p)
            elif mount == "ceiling" and ceiling:
                if oy + h > ceiling + CEILING_POKE_M:
                    found.add("ceiling_prop_through_ceiling", room_id, p)
                elif oy + h < ceiling - CEILING_DROP_M:
                    found.add("ceiling_prop_not_hanging", room_id, p)
            if mount != "floor" or flat:
                continue
            if any(_overlap(zone, fp) > DOOR_ZONE_TOL_M2 for zone in zones):
                found.add("prop_in_doorway", room_id, p)
            if shaft and _overlap(shaft, fp) > ELEVATOR_TOL_M2:
                found.add("prop_in_elevator", room_id, p)
    return found.out()


def _door_zones(doorways: List[Dict[str, Any]], level: int,
                outline: List[List[float]]) -> List[List[List[float]]]:
    """The metre in front of every door/passage of the storey, on the side
    that lies inside this room's outline."""
    from app.core.scene_recipe import _point_in_polygon
    zones: List[List[List[float]]] = []
    if len(outline) < 3:
        return zones
    for dw in doorways:
        if int(dw.get("level") or 0) != level \
                or dw.get("type") not in ("door", "passage"):
            continue
        centre, along = _pt(dw.get("at_world")), _pt(dw.get("along"))
        if centre is None or along is None:
            continue
        (cx, cz), (ax, az) = centre, along
        nx, nz = -az, ax
        half = (_f(dw.get("width_m"), 1.0) or 1.0) / 2
        for sign in (1, -1):
            if not _point_in_polygon(cx + sign * nx * 0.5, cz + sign * nz * 0.5,
                                     outline):
                continue
            ox, oz = sign * nx * DOOR_ZONE_M, sign * nz * DOOR_ZONE_M
            ring = [[cx + ax * half, cz + az * half], [cx - ax * half, cz - az * half],
                    [cx - ax * half + ox, cz - az * half + oz],
                    [cx + ax * half + ox, cz + az * half + oz]]
            if _signed(ring) < 0:
                ring.reverse()
            zones.append(ring)
    return zones


# ── reachability ─────────────────────────────────────────────────────────

def reachability_problems(location_id: str, recipes: List[Dict[str, Any]],
                          doorways: List[Dict[str, Any]],
                          stairs: List[Dict[str, Any]], elevator: Any,
                          corridors: List[Dict[str, Any]],
                          ) -> List[Dict[str, Any]]:
    """``room_unreachable`` for every room no chain of thresholds, flights,
    elevator halts, corridors and outdoor zones ties to the outside.

    A corridor counts as a place only on storeys that HAVE one (the payload's
    ``corridors``); on storey 0 a point in no room is outside. A wall-less or
    outdoor room is open to its storey: outside on 0, its corridor above.
    """
    from app.core.scene_recipe import _point_in_polygon
    rooms = [r for r in recipes if not r.get("is_ground")]
    # No door outside at all is the BUILDING's finding
    # (``no_building_entrance``); repeating it for every room would bury it.
    if not rooms or not any(dw.get("outside") for dw in doorways):
        return []
    corridor_ids = {int(c.get("level") or 0): str(c.get("room_id") or "")
                    for c in corridors or []}
    graph: Dict[str, set] = defaultdict(set)

    def link(a: Optional[str], b: Optional[str]) -> None:
        if a and b and a != b:
            graph[a].add(b)
            graph[b].add(a)

    def place(x: float, z: float, level: int) -> Optional[str]:
        for r in rooms:
            if int(r.get("level") or 0) == level and len(r.get("outline") or []) >= 3 \
                    and _point_in_polygon(x, z, r["outline"]):
                return str(r.get("room_id") or "")
        if level in corridor_ids:
            return corridor_ids[level]
        return "outside" if level == 0 else None

    for dw in doorways:
        ids = [str(i) for i in dw.get("rooms") or []]
        if dw.get("outside"):
            ids.append("outside")
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                link(ids[i], ids[j])
    for r in rooms:
        if r.get("always_visible") or r.get("no_walls"):
            lv = int(r.get("level") or 0)
            link(str(r.get("room_id") or ""),
                 corridor_ids.get(lv) or ("outside" if lv == 0 else None))
    for st in stairs or []:
        foot, head = st.get("foot") or [], st.get("head") or []
        if len(foot) == 3 and len(head) == 3:
            a, b = _pt([foot[0], foot[2]]), _pt([head[0], head[2]])
            if a and b:
                link(place(*a, int(_f(st.get("from_level")))),
                     place(*b, int(_f(st.get("to_level")))))
    lift = _pt(elevator)
    if lift:
        levels = sorted({int(r.get("level") or 0) for r in rooms} | set(corridor_ids))
        halts = [h for h in (place(lift[0], lift[1], lv) for lv in levels) if h]
        for a, b in zip(halts, halts[1:]):
            link(a, b)
    seen, queue = {"outside"}, deque(["outside"])
    while queue:
        for nxt in graph[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return [{"kind": "room_unreachable", "location_id": location_id,
             "room_id": str(r.get("room_id") or ""),
             "level": int(r.get("level") or 0),
             "message": MESSAGES["room_unreachable"]}
            for r in rooms if str(r.get("room_id") or "") not in seen]
