"""Read-only, same-room approaches to a current composed action binding.

XZ is world metres, Y is the existing scene floor datum (terrain-relative on
storey zero). Geometry deliberately shares room_stand's conservative grown
footprints and keep-clear opening zones. A door never grants a same-room route
permission to cross the room boundary. There is no world-navigation fallback.
"""
import heapq
import math
from typing import Optional, Sequence

from app.core import furnish_geometry as fg
from app.core.room_stand import BODY_R_M, ACCESS_BODY_R_M, WALL_CLEAR_M, footprint_corners

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
    def __init__(self, polygon, blockers, zones, *, furniture_radius=BODY_R_M):
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
                self.keepouts.append(footprint_corners(box, furniture_radius))
                self.candidates.extend(footprint_corners(box, furniture_radius + _VERTEX_SLACK_M))
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
        # A space never changes after construction, and the planners ask about
        # the same corners and ring samples thousands of times per read.
        try:
            key = (float(p[0]), float(p[1])) if len(p) == 2 else None
        except (TypeError, ValueError, OverflowError):
            key = None
        if key is None:
            return self._free(p)
        cache = self.__dict__.setdefault("_free_cache", {})
        if key not in cache:
            cache[key] = self._free(p)
        return cache[key]

    def _free(self, p: Point) -> bool:
        if not self.valid or not all(math.isfinite(v) for v in p) or not fg.point_in_poly(p, self.poly):
            return False
        if min(fg.point_segment_distance(p, a, b) for a, b in _edges(self.poly)) < WALL_CLEAR_M - _EPS:
            return False
        return not any(fg.point_in_poly(p, ring) or any(fg.point_segment_distance(p, a, b) <= _EPS
                                                       for a, b in _edges(ring)) for ring in self.keepouts)

    def inside_segment(self, a: Point, b: Point) -> bool:
        """Room-only check for an escape leg; keepouts may be crossed."""
        return bool(self.valid and fg.point_in_poly(a, self.poly) and fg.point_in_poly(b, self.poly)
                    and not any(_intersects(a, b, c, d) for c, d in _edges(self.poly)))

    def step_out(self, start: Point) -> Point | None:
        """Nearest sampled free point within 1.5 m, ties by polar angle.

        Candidates must also be free after centimetre-rounded persistence.
        Fixed .05 m rings and five-degree angles keep admission deterministic.
        """
        return next((p for p in self.nearby_free(start) if p != start and self.inside_segment(start, p)), None)

    def nearby_free(self, start: Point):
        """Free, centimetre-safe candidates within 1.5m, nearest then angle."""
        candidates = [start, *self.candidates]
        for radius_step in range(1, 31):
            radius = radius_step * .05
            for degrees in range(0, 360, 5):
                angle = math.radians(degrees)
                candidates.append((start[0] + radius * math.cos(angle),
                                   start[1] + radius * math.sin(angle)))
        ranked = []
        for raw in candidates:
            p = (round(raw[0], 9), round(raw[1], 9))
            distance = math.dist(start, p)
            if distance <= 1.5 + _EPS:
                angle = math.atan2(p[1] - start[1], p[0] - start[0]) % math.tau
                ranked.append((round(distance, 9), angle, p))
        for _, _, p in sorted(set(ranked)):
            persisted = (round(p[0], 2), round(p[1], 2))
            if self.free(p) and self.free(persisted):
                yield p

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


class _VisibilityGraph:
    """Lazy static corner graph; endpoints keep the original ordering/tie rules."""

    def __init__(self, geometry):
        self.space = _Space(*geometry)
        self.nodes = None
        self.edges = {}

    def _build_graph(self):
        candidates = {(round(p[0], 2), round(p[1], 2)) for p in self.space.candidates}
        self.nodes = sorted(p for p in candidates if self.space.free(p))
        for i, a in enumerate(self.nodes):
            for b in self.nodes[i + 1:]:
                if self.space.visible(a, b):
                    self.edges[a, b] = math.dist(a, b)

    def route(self, start, goal, *, final_space=None):
        final = final_space or self.space
        try:
            start, goal = tuple(map(float, start)), tuple(map(float, goal))
            if len(start) != 2 or len(goal) != 2 or not self.space.free(start) or not final.free(goal):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        if start == goal:
            return [start]
        if final.visible(start, goal):
            return [start, goal]
        if self.nodes is None:
            self._build_graph()
        nodes = [start, goal] + [p for p in self.nodes if p not in (start, goal)]
        graph = [[] for _ in nodes]
        for i, a in enumerate(nodes):
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                edge_space = final if i == 1 or j == 1 else self.space
                cost = (math.dist(a, b) if edge_space.visible(a, b) else None) if i < 2 else self.edges.get((a, b))
                if cost is not None:
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


class _Reachability:
    """One source Dijkstra; candidate goals only link to reached vertices.

    Distance/path tuples retain route()'s shortest-path and lexical tie rules.
    The direct edge still wins immediately, exactly as in route().
    """

    def __init__(self, graph, start):
        self.graph = graph
        try:
            self.start = tuple(map(float, start))
            if len(self.start) != 2:
                self.start = None
        except (TypeError, ValueError, OverflowError):
            self.start = None
        self.best = None

    def _distances(self):
        if self.best is not None:
            return self.best
        graph, start = self.graph, self.start
        self.best = {}
        if start is None or not graph.space.free(start):
            return self.best
        if graph.nodes is None:
            graph._build_graph()
        nodes = [start] + [p for p in graph.nodes if p != start]
        edges = {p: [] for p in nodes}
        for (a, b), cost in graph.edges.items():
            if start not in (a, b):
                edges[a].append((b, cost))
                edges[b].append((a, cost))
        for point in nodes[1:]:
            if graph.space.visible(start, point):
                edges[start].append((point, math.dist(start, point)))
        best = self.best
        best[start] = (0.0, (start,))
        queue = [(0.0, (start,), start)]
        while queue:
            distance, path, point = heapq.heappop(queue)
            if best.get(point) != (distance, path):
                continue
            for neighbor, cost in edges[point]:
                candidate = (distance + cost, path + (neighbor,))
                if neighbor not in best or candidate < best[neighbor]:
                    best[neighbor] = candidate
                    heapq.heappush(queue, (*candidate, neighbor))
        return best

    def route(self, goal, *, final_space=None):
        final = final_space or self.graph.space
        start = self.start
        try:
            goal = tuple(map(float, goal))
            if len(goal) != 2:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        if start is None or not self.graph.space.free(start) or not final.free(goal):
            return None
        if start == goal:
            return [start]
        if final.visible(start, goal):
            return [start, goal]
        choices = []
        for point, (distance, path) in self._distances().items():
            if point == start:
                continue  # Already checked the direct edge.
            if point == goal:
                choices.append((distance, path))
            elif final.visible(point, goal):
                choices.append((distance + math.dist(point, goal), path + (goal,)))
        return list(min(choices)[1]) if choices else None


def visibility_path(start: Sequence[float], goal: Sequence[float], polygon,
                    blockers, door_zones=(), *, _graph=None) -> list[Point] | None:
    """Shortest deterministic visibility path; reuse a graph only for its geometry."""
    graph = _graph if _graph is not None else _VisibilityGraph((polygon, blockers, door_zones))
    return graph.route(start, goal)


def access_space(geometry, placement_id):
    """Final approach/entry: exempt target, reduce OTHER furniture only."""
    polygon, blockers, zones = geometry
    return _Space(polygon, [b for b in blockers if not (
        placement_id and b.get("placement_id") == placement_id)], zones,
        furniture_radius=ACCESS_BODY_R_M)


def slot_route(start, access, anchor, geometry, placement_id, *, graph=None, reachability=None, _candidates=None):
    """Shared runtime/report planner. Direct candidates use full walking rules."""
    graph = graph or _VisibilityGraph(geometry)
    reached = reachability or _Reachability(graph, start)
    final = access_space(geometry, placement_id)
    goal = (access["x"], access["z"])
    if not final.free(goal):
        reason = "access_not_walkable"
    elif not final.visible(goal, anchor):
        reason = "entry_transition_blocked"
    else:
        route = reached.route(goal, final_space=final)
        if route is not None:
            return route, "bridge", ""
        reason = "no_route"
    found_free = False
    candidates = _candidates() if _candidates is not None else graph.space.nearby_free(anchor)
    for point in candidates:
        found_free = True
        route = reached.route(point)
        if route is not None:
            return route, "direct", reason
    return None, "blocked", "no_route" if found_free else "no_free_direct_point"


class _LazySequence:
    """Replayable view of a generator: computes each item once, only on demand.

    The first free anchor sample usually routes, so the full ~2000-point ring
    is only evaluated for an anchor that really needs it.
    """

    def __init__(self, source):
        self._source = source
        self._items = []

    def __iter__(self):
        index = 0
        while True:
            if index < len(self._items):
                yield self._items[index]
            else:
                item = next(self._source, _LazySequence)
                if item is _LazySequence:
                    return
                self._items.append(item)
                yield item
            index += 1


def _query_slot_route(query, geometry_key, start, access, anchor, geometry,
                      placement_id, graph, reached):
    """Reuse exact slot work and nearest free anchor samples within one read."""
    key = (geometry_key, tuple(start), round(access["x"], 9), round(access["z"], 9),
           tuple(anchor), placement_id)
    if key not in query._action_slot_routes:
        def candidates():
            anchor_key = (geometry_key, tuple(anchor))
            if anchor_key not in query._action_direct_candidates:
                query._action_direct_candidates[anchor_key] = _LazySequence(graph.space.nearby_free(anchor))
            return iter(query._action_direct_candidates[anchor_key])

        query._action_slot_routes[key] = slot_route(
            start, access, anchor, geometry, placement_id, graph=graph,
            reachability=reached, _candidates=candidates)
    route, mode, reason = query._action_slot_routes[key]
    # A caller may prepend step-out or otherwise consume its own route list.
    return (list(route) if route is not None else None), mode, reason


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


def seat_escape_ok(seat: Point, stand: Point, out: Point, geometry, placement_id: str) -> bool:
    """A seated actor's walk from where its exit clip set it down (``stand``)
    to the free standing point ``out``: only the furniture it is leaving may
    hold ``stand`` (exempt as in :func:`_departure_walkable`), and with that
    furniture exempt the walk must be clear. Planner and arrival revalidation
    share it."""
    from app.core.room_stand import _in_footprint
    polygon, blockers, zones = geometry
    try:
        others = [box for box in blockers if not (
            placement_id and box.get("placement_id") == placement_id
            and _in_footprint(seat[0], seat[1], box, BODY_R_M))]
        own = _Space(polygon, others, zones)
        return len(others) < len(blockers) and own.free(stand) and own.visible(stand, out)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _seat_step_out(actor: str, location: str, room: str, seat: Point, stand: Point,
                   space, geometry, placement_id: str) -> Optional[Point]:
    """Where a seated actor walks after its exit clip when the clip sets it
    down inside the keepout of the furniture it is leaving (a sofa's stand
    point lies ~0.5 m in front of the seat, its keepout reaches further, and
    a coffee table can close the gap): the free standing point a plain
    stand-up picks near the clip's end (``room_stand.pick_stand``), so
    leaving for another action ends where standing up would. None when that
    point is not free for the planner or the walk there is blocked."""
    from app.core.room_stand import _mates, pick_stand
    polygon, blockers, zones = geometry
    out = pick_stand(polygon, blockers, zones, _mates(location, room, actor), stand)
    if out is None or not space.free(out) or not space.free((round(out[0], 2), round(out[1], 2))):
        return None
    return out if seat_escape_ok(seat, stand, out, geometry, placement_id) else None


def _blocked(reason: str) -> dict:
    return dict(status="blocked", reason=reason, waypoints=[], access=None, entry_anchor=None)


def plan_approach(actor: str, target: dict, role: str, *, _query=None) -> dict:
    """Resolve current server geometry, never trust client-supplied access/route.

    target requires location_id, room_id, placement_id, variant_uid, action_id,
    definition_revision. Optional marker_id/slot pins an executor's reservation;
    otherwise choose the shortest reachable alternative, ties by marker ID.
    Optional ``point`` [x, z] (location metres, only with a pinned slot) is the
    entry target instead of the slot position — a pair sharing one place
    enters at its clip role point.
    role is actor or partner. This function reserves/writes/activates nothing.
    """
    return _plan_approach(actor, target, role, _query=_query)


def _plan_approach(actor: str, target: dict, role: str, *, departure=None,
                   departure_placement_id: str = "", _query=None, route_start=None) -> dict:
    """Internal revalidation can reuse the persisted, measured seat exit."""
    from app.core import places
    from app.core.room_stand import approach_departure

    required = ("location_id", "room_id", "placement_id", "variant_uid", "action_id", "definition_revision")
    if not actor or not isinstance(target, dict) or any(not isinstance(target.get(k), str) or not target[k] for k in required):
        return _blocked("invalid_target")
    if role not in ("actor", "partner"):
        return _blocked("invalid_role")
    query = _query if _query is not None else places._GeometryQuery()
    profile = query.profile(actor)
    if not profile:
        return _blocked("unknown_actor")
    location, room = places.where(actor, profile=profile)
    if (target["location_id"], target["room_id"]) != (location, room):
        return _blocked("target_not_in_actor_room")
    # Explicit reuse is bounded to this read operation. Standalone arrival
    # revalidation starts fresh, never from the shared places TTL cache.
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
    # These caches belong to the explicit query, never to a process-wide TTL.
    if not hasattr(query, "_action_graphs"):
        query._action_graphs = {}
        query._action_starts = {}
        query._action_reached = {}
        query._action_slot_routes = {}
        query._action_direct_candidates = {}
    geometry_key = (location, room, id(geometry))
    if geometry_key not in query._action_graphs:
        query._action_graphs[geometry_key] = _VisibilityGraph(geometry)
    graph = query._action_graphs[geometry_key]
    space = graph.space
    if not space.valid:
        return _blocked("invalid_room_geometry")
    start_key = (geometry_key, actor)
    reusable = departure is None and route_start is None

    def blocked_start(reason):
        if reusable:
            query._action_starts[start_key] = (None, None, None, None, "", reason)
        return _blocked(reason)

    if reusable and start_key in query._action_starts:
        start, real_start, seat, step_out, departing_placement, departure_reason = query._action_starts[start_key]
    else:
        start, seat, departure_reason = departure if departure is not None else approach_departure(
            actor, profile=profile, _places=inventory)
        if departure_reason:
            return blocked_start(departure_reason)
        if route_start is not None:
            start = tuple(route_start)
        real_start = start
        step_out = None
        departing_placement = departure_placement_id if departure is not None else (
            (places.place_of(actor, profile=profile, _places=inventory) or {}).get("placement_id", "") if seat is not None else "")
        if not space.free(start):
            step_out = (space.step_out(start) if seat is None
                        else _seat_step_out(actor, location, room, seat, start, space, geometry,
                                            departing_placement))
            if step_out is None:
                return blocked_start("start_not_walkable")
            start = step_out
        if seat is not None and not _departure_walkable(seat, start, geometry, departing_placement):
            return blocked_start("departure_not_walkable")
        if reusable:
            query._action_starts[start_key] = (start, real_start, seat, step_out, departing_placement, "")
    if departure_reason:
        return _blocked(departure_reason)
    reached_key = (geometry_key, tuple(start))
    if reached_key not in query._action_reached:
        query._action_reached[reached_key] = _Reachability(graph, start)
    reached = query._action_reached[reached_key]
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
            document = query.prop_document(place["prop_id"])
            action = next((a for a in document.get("actions", [])
                           if a["id"] == target["action_id"]), None)
            if not action:
                reason = "binding_not_found"
                continue
            if role == "partner" and action.get("participants") != 2:
                reason = "missing_role_access"
                continue
            slots = [target["slot"]] if "slot" in target else range(len(place["slots"]))
            point = target.get("point") if "slot" in target else None
            for slot in slots:
                try:
                    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(place["slots"]):
                        reason = "invalid_entry_slot"
                        continue
                    from app.core.prop_action_access import slot_access
                    if point is not None and not (
                            len(point) == 2 and all(math.isfinite(float(v)) for v in point)):
                        raise ValueError("invalid entry point")
                    access, reason = slot_access(place, slot, role, action, profile, point=point)
                    if reason:
                        continue
                    if not all(math.isfinite(float(access[k])) for k in ("x", "z", "y", "yaw")):
                        raise ValueError("nonfinite access")
                    sx, sz = place["slots"][slot] if point is None else (float(point[0]), float(point[1]))
                except (KeyError, TypeError, ValueError, OverflowError):
                    reason = "invalid_binding_geometry"
                    continue
                route, mode, route_reason = _query_slot_route(
                    query, geometry_key, start, access, (sx, sz), geometry,
                    target["placement_id"], graph, reached)
                if route is None:
                    reason = route_reason
                    continue
                authored_access = dict(access)
                if mode == "direct":
                    access = dict(access, x=route[-1][0], z=route[-1][1])
                if step_out is not None:
                    route = [real_start] + route
                length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
                anchor = dict(location_id=location, room_id=room, placement_id=target["placement_id"],
                              prop_id=place["prop_id"], variant_uid=place["variant_uid"],
                              marker_id=place["marker_id"], place_id=place["id"], slot=slot,
                              x=sx, z=sz, y=place["y_world"], yaw=place.get("facing"),
                              root_offset=place.get("root_offset", 0))
                choices.append((mode == "direct", length, place["id"], dict(status="ok", entry_mode=mode,
                                                         bridge_access=authored_access, bridge_reason=route_reason, reason="", waypoints=[list(p) for p in route],
                                                         access=dict(access), entry_anchor=anchor,
                                                         step_out=list(step_out) if step_out is not None else None,
                                                         departure_seat=list(seat) if seat is not None else None,
                                                         departure_placement_id=departing_placement)))
    return min(choices, key=lambda row: row[:3])[3] if choices else _blocked(reason)


def access_obstructions(access, anchor, geometry, placement_id, *, final_rules=True):
    """Explain final-space collisions using the planner's actual boundaries.

    Deficit is the displacement to leave a grown keepout (or reach the wall
    margin), in metres. For a bridge we report the deepest penetration sampled
    at <=1mm intervals; this diagnostic sampling NEVER decides admission.
    The exempt own footprint is included as context, explicitly marked exempt.
    """
    polygon, blockers, zones = geometry
    final = access_space(geometry, placement_id) if final_rules else _Space(*geometry)
    if not final.valid:
        return [dict(kind="invalid_room_geometry", missing_m=None)]
    a = (access["x"], access["z"])
    points = [a]
    if not final.visible(a, anchor):
        steps = max(1, math.ceil(math.dist(a, anchor) / .001))
        points += [(a[0] + (anchor[0] - a[0]) * i / steps,
                    a[1] + (anchor[1] - a[1]) * i / steps) for i in range(1, steps + 1)]

    def gap(p, ring):
        distance = min(fg.point_segment_distance(p, u, v) for u, v in _edges(ring))
        return -distance if fg.point_in_poly(p, ring) else distance

    result = []
    wall_missing = max(WALL_CLEAR_M + gap(p, final.poly) for p in points)
    if wall_missing > _EPS:
        result.append(dict(kind="wall", missing_m=max(0, wall_missing)))
    other_boxes = [box for box in blockers if not final_rules or box.get("placement_id") != placement_id or not placement_id]
    for box, ring in zip(other_boxes, final.keepouts):
        missing = max(-gap(p, ring) for p in points)
        if missing >= -_EPS:
            result.append(dict(kind="own footprint" if box.get("placement_id") == placement_id else "furniture",
                               placement_id=box.get("placement_id", ""),
                               missing_m=max(0, missing)))
    for ring in final.keepouts[len(other_boxes):]:
        missing = max(-gap(p, ring) for p in points)
        if missing >= -_EPS:
            result.append(dict(kind="door zone", missing_m=max(0, missing)))
    for box in blockers:
        if final_rules and placement_id and box.get("placement_id") == placement_id:
            missing = -gap(a, footprint_corners(box, BODY_R_M))
            if missing >= -_EPS:
                result.append(dict(kind="own footprint (exempt)", missing_m=max(0, missing)))
    return result
