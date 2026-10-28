"""Read-only, same-room approaches to a current composed action binding.

XZ is world metres, Y is the existing scene floor datum (terrain-relative on
storey zero). Geometry deliberately shares room_stand's conservative grown
footprints and keep-clear opening zones. A door never grants a same-room route
permission to cross the room boundary. There is no world-navigation fallback.
"""
import heapq
import math
from typing import Sequence

from app.core import furnish_geometry as fg
from app.core.room_stand import BODY_R_M, WALL_CLEAR_M, footprint_corners

Point = tuple[float, float]
_EPS = 1e-9
# Positions/journey_state are centimetre-rounded. Candidate vertices keep enough
# slack that that projection cannot put a body back inside a wall/footprint.
_VERTEX_SLACK_M = .02


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    if ((ab_c > _EPS and ab_d < -_EPS) or (ab_c < -_EPS and ab_d > _EPS)) and (
            (cd_a > _EPS and cd_b < -_EPS) or (cd_a < -_EPS and cd_b > _EPS)):
        return True
    return any(abs(cross) <= _EPS and fg.point_segment_distance(p, u, v) <= _EPS
               for cross, p, u, v in ((ab_c, c, a, b), (ab_d, d, a, b),
                                      (cd_a, a, c, d), (cd_b, b, c, d)))


def _edges(poly):
    return zip(poly, poly[1:] + poly[:1])


def _polygon(raw) -> list[Point] | None:
    try:
        poly = [(float(p[0]), float(p[1])) for p in raw]
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if len(poly) < 3 or any(not math.isfinite(v) for p in poly for v in p):
        return None
    if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in _edges(poly))) <= _EPS:
        return None
    edges = list(_edges(poly))
    for i, (a, b) in enumerate(edges):
        if math.dist(a, b) <= _EPS:
            return None
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _intersects(a, b, *edges[j]):
                return None
    return poly


def _offset_vertices(poly: list[Point], distance: float) -> list[Point]:
    """Miter vertices of an inward (+) or outward (-) parallel polygon.

    These are graph candidates, never an unchecked new collision boundary.
    Every vertex and every edge is validated against the ORIGINAL geometry;
    concave inset self-intersections/narrow corridors cannot admit shortcuts.
    """
    sign = 1 if sum(a[0] * b[1] - b[0] * a[1] for a, b in _edges(poly)) > 0 else -1
    lines = []
    for a, b in _edges(poly):
        dx, dz = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dz)
        nx, nz = -dz / length * sign, dx / length * sign
        lines.append(((a[0] + distance * nx, a[1] + distance * nz), (dx, dz)))
    out = []
    for i, (b, v) in enumerate(lines):
        a, u = lines[i - 1]
        den = u[0] * v[1] - u[1] * v[0]
        if abs(den) <= _EPS:
            out.append(b)
        else:
            t = ((b[0] - a[0]) * v[1] - (b[1] - a[1]) * v[0]) / den
            out.append((a[0] + t * u[0], a[1] + t * u[1]))
    return out


class _Space:
    def __init__(self, polygon, blockers, zones):
        self.poly = _polygon(polygon)
        self.keepouts = []
        self.candidates = []
        self.valid = self.poly is not None
        if not self.valid:
            return
        self.candidates.extend(_offset_vertices(self.poly, WALL_CLEAR_M + _VERTEX_SLACK_M))
        try:
            for box in blockers:
                values = [float(box[key]) for key in ("width_m", "depth_m")]
                values += [float(v) for v in box["at"]]
                values.append(float(box.get("yaw", 0)))
                if any(not math.isfinite(v) for v in values) or min(values[:2]) <= 0 or len(box["at"]) != 2:
                    self.valid = False
                    return
                self.keepouts.append(footprint_corners(box, BODY_R_M))
                self.candidates.extend(footprint_corners(box, BODY_R_M + _VERTEX_SLACK_M))
            for zone in zones:
                ring = _polygon(zone)
                if ring is None:
                    self.valid = False
                    return
                grown = _offset_vertices(ring, -BODY_R_M)
                self.keepouts.append(grown)
                self.candidates.extend(_offset_vertices(ring, -BODY_R_M - _VERTEX_SLACK_M))
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            self.valid = False

    def free(self, p: Point) -> bool:
        if not self.valid or not all(math.isfinite(v) for v in p) or not fg.point_in_poly(p, self.poly):
            return False
        if min(fg.point_segment_distance(p, a, b) for a, b in _edges(self.poly)) < WALL_CLEAR_M - _EPS:
            return False
        return not any(fg.point_in_poly(p, ring) or any(fg.point_segment_distance(p, a, b) <= _EPS
                                                       for a, b in _edges(ring)) for ring in self.keepouts)

    def visible(self, a: Point, b: Point) -> bool:
        # Exact segment/edge checks, NOT sparse point sampling: even a very thin
        # barrier or a concave wall crossing between samples invalidates a leg.
        if not self.free(a) or not self.free(b):
            return False
        for c, d in _edges(self.poly):
            if _intersects(a, b, c, d):
                return False
            gap = min(fg.point_segment_distance(a, c, d), fg.point_segment_distance(b, c, d),
                      fg.point_segment_distance(c, a, b), fg.point_segment_distance(d, a, b))
            if gap < WALL_CLEAR_M - _EPS:
                return False
        for ring in self.keepouts:
            if any(_intersects(a, b, c, d) for c, d in _edges(ring)):
                return False
        return True


def visibility_path(start: Sequence[float], goal: Sequence[float], polygon,
                    blockers, door_zones=()) -> list[Point] | None:
    """Shortest deterministic visibility-graph path, or None; no fallback.

    Graph vertices are safe centimetre-rounded inset room and grown furniture/
    opening-zone corners. Equal-length routes break ties by lexicographic node
    sequence, independent of footprint enumeration and polygon winding.
    """
    space = _Space(polygon, blockers, door_zones)
    try:
        start, goal = tuple(map(float, start)), tuple(map(float, goal))
        if len(start) != 2 or len(goal) != 2 or not space.free(start) or not space.free(goal):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    if start == goal:
        return [start]
    if space.visible(start, goal):
        return [start, goal]
    candidates = {(round(p[0], 2), round(p[1], 2)) for p in space.candidates}
    nodes = [start, goal] + sorted(p for p in candidates if p not in (start, goal) and space.free(p))
    graph = [[] for _ in nodes]
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if space.visible(a, b):
                cost = math.dist(a, b)
                graph[i].append((j, cost))
                graph[j].append((i, cost))
    best = {0: (0.0, (start,))}
    queue = [(0.0, (start,), 0)]
    while queue:
        distance, path, i = heapq.heappop(queue)
        if best.get(i) != (distance, path):
            continue
        if i == 1:
            return list(path)
        for j, cost in graph[i]:
            candidate = (distance + cost, path + (nodes[j],))
            if j not in best or candidate < best[j]:
                best[j] = candidate
                heapq.heappush(queue, (*candidate, j))
    return None


def _departure_walkable(seat: Point, start: Point, geometry, placement_id: str) -> bool:
    """Check the whole measured exit, exempting only its occupied furniture.

    A body's seat may legitimately start inside its OWN grown footprint. That
    one placement is exempt only if it actually contains the seat. All other
    furniture (even another copy of the same prop), walls and opening zones
    constrain the complete bridge, not just its free endpoint.
    """
    from app.core.room_stand import _in_footprint
    polygon, blockers, zones = geometry
    try:
        others = [box for box in blockers if not (
            placement_id and box.get("placement_id") == placement_id
            and _in_footprint(seat[0], seat[1], box, BODY_R_M))]
        return _Space(polygon, others, zones).visible(seat, start)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _blocked(reason: str) -> dict:
    return dict(status="blocked", reason=reason, waypoints=[], access=None, entry_anchor=None)


def plan_approach(actor: str, target: dict, role: str, *, _query=None) -> dict:
    """Resolve current server geometry, never trust client-supplied access/route.

    target requires location_id, room_id, placement_id, variant_uid, action_id,
    definition_revision. Optional marker_id/slot pins an executor's reservation;
    otherwise choose the shortest reachable alternative, ties by marker ID.
    role is actor or partner. This function reserves/writes/activates nothing.
    """
    return _plan_approach(actor, target, role, _query=_query)


def _plan_approach(actor: str, target: dict, role: str, *, departure=None,
                   departure_placement_id: str = "", _query=None) -> dict:
    """Internal revalidation can reuse the persisted, measured seat exit."""
    from app.core import places
    from app.core.room_stand import approach_departure
    from app.models.character import get_character_profile

    required = ("location_id", "room_id", "placement_id", "variant_uid", "action_id", "definition_revision")
    if not actor or not isinstance(target, dict) or any(not isinstance(target.get(k), str) or not target[k] for k in required):
        return _blocked("invalid_target")
    if role not in ("actor", "partner"):
        return _blocked("invalid_role")
    profile = get_character_profile(actor)
    if not profile:
        return _blocked("unknown_actor")
    location, room = places.where(actor, profile=profile)
    if (target["location_id"], target["room_id"]) != (location, room):
        return _blocked("target_not_in_actor_room")
    # Explicit reuse is bounded to this read operation. Standalone arrival
    # revalidation starts fresh, never from the shared places TTL cache.
    query = _query if _query is not None else places._GeometryQuery()
    inventory = query.room_places(location, room)
    candidates = [p for p in inventory if p.get("placement_id") == target["placement_id"]]
    if not candidates:
        return _blocked("placement_not_found")
    candidates = [p for p in candidates if p.get("variant_uid") == target["variant_uid"]]
    if not candidates:
        return _blocked("stale_variant")
    geometry = query.room_geometry(location, room)
    if geometry is None:
        return _blocked("room_geometry_unavailable")
    space = _Space(*geometry)
    if not space.valid:
        return _blocked("invalid_room_geometry")
    start, seat, departure_reason = departure if departure is not None else approach_departure(
        actor, profile=profile, _places=inventory)
    if departure_reason:
        return _blocked(departure_reason)
    if not space.free(start):
        return _blocked("start_not_walkable")
    departing_placement = departure_placement_id if departure is not None else (
        (places.place_of(actor, profile=profile, _places=inventory) or {}).get("placement_id", "") if seat is not None else "")
    if seat is not None and not _departure_walkable(seat, start, geometry, departing_placement):
        return _blocked("departure_not_walkable")
    choices = []
    reason = "binding_not_found"
    for place in sorted(candidates, key=lambda p: p["id"]):
        if target.get("marker_id") and target["marker_id"] != place["marker_id"]:
            continue
        for binding in place.get("action_bindings", []):
            if binding.get("action_id") != target["action_id"]:
                continue
            if binding.get("definition_revision") != target["definition_revision"]:
                reason = "stale_definition"
                continue
            if not binding.get("supported") or binding.get("validation") != "local_valid":
                reason = binding.get("reason") or "binding_not_supported"
                continue
            access = binding.get("access_points", {}).get(role)
            if access is None:
                reason = "missing_role_access"
                continue
            try:
                if not all(math.isfinite(float(access[k])) for k in ("x", "z", "y", "yaw")):
                    raise ValueError("nonfinite access")
                goal = (float(access["x"]), float(access["z"]))
                slot = target.get("slot", 0 if role == "actor" else 1)
                if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(place["slots"]):
                    reason = "invalid_entry_slot"
                    continue
                sx, sz = place["slots"][slot]
            except (KeyError, TypeError, ValueError, OverflowError):
                reason = "invalid_binding_geometry"
                continue
            if not space.free(goal):
                reason = "access_not_walkable"
                continue
            route = visibility_path(start, goal, *geometry)
            if route is None:
                reason = "no_route"
                continue
            length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
            anchor = dict(location_id=location, room_id=room, placement_id=target["placement_id"],
                          prop_id=place["prop_id"], variant_uid=place["variant_uid"],
                          marker_id=place["marker_id"], place_id=place["id"], slot=slot,
                          x=sx, z=sz, y=place["y_world"], yaw=place.get("facing"),
                          root_offset=place.get("root_offset", 0))
            choices.append((length, place["id"], dict(status="ok", reason="", waypoints=[list(p) for p in route],
                                                     access=dict(access), entry_anchor=anchor,
                                                     departure_seat=list(seat) if seat is not None else None,
                                                     departure_placement_id=departing_placement)))
    return min(choices, key=lambda row: row[:2])[2] if choices else _blocked(reason)
