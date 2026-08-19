"""Travel engine — server-authoritative journeys across the metre world.

A journey turns a cross-location move into elapsed GAME time instead of an
instant state switch: the position is a pure function of the game clock, so
a frozen world freezes every journey with it and all clients derive the
same position from the same payload ("the server computes, clients render").

Journey v2 (Seamless World, E3) — the grid is gone, a journey is a METRE
POLYLINE with baked times:

    profile["journey"] = {
        "target": "<location-id>",
        "waypoints": [[x, z, t_cum], ...],   # world metres + cumulative
                                             # GAME seconds since the start
                                             # (waypoint 0 carries 0.0)
        "started_at_game": "Y0002-D109T14:00:00",   # canonical GAME stamp
        "speed_m_s": 1.4,                    # world setting at journey start
        "entry_edge": 2,                     # BOUNDARY EDGE INDEX of the
                                             # target's opening the route
                                             # aims at (None = boundary-rim
                                             # fallback)
    }

``entry_edge`` is what lets the ARRIVAL route into the right room: a location
with several doors links each of them to its own room, and only the journey
knows which one it walked to. Baked at the start like ``t_cum``.

``t_cum`` is baked ONCE at the start from ``nav_grid.segment_costs`` (which
already carries the terrain ``speed_factor``) divided by the travel speed —
nothing is recomputed while walking, so a repainted meadow or a changed
setting never re-times someone already on the road.
``movement_target`` stays the plain target-id field existing readers use.

There is no migration: a stored OLD journey (the one with a ``path`` of
location ids) is discarded on read together with its movement target.
"""
import asyncio
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_speed_factor, game_time

logger = get_logger("travel_engine")

Point = Tuple[float, float]

# Metres per GAME second on neutral ground when the world setting
# `game.travel_speed_m_s` is missing or unusable — a human walking pace.
DEFAULT_SPEED_M_S = 1.4
_MIN_SPEED_M_S = 0.1
_MAX_SPEED_M_S = 20.0

# How often the TravelTicker settles journeys, in REAL seconds. It doubles as
# the arrival tolerance's unit (``_at_goal``) — and REAL seconds is exactly
# what it means there too, so the conversion into walked metres has to go
# through the game-clock factor (see ``_at_goal``).
_TICK_SECONDS = 5.0

# Floor for the game-clock factor in the goal window. A frozen world reports
# 0.0 (no game time passes at all), and a window of zero metres would call
# every crossing "not the final approach" — including the one the ticker was
# woken up for when the world thaws or an admin settles a journey by hand.
# A tenth of a tick's travel is small enough to stay honest and big enough to
# keep answering the question.
_GOAL_FACTOR_FLOOR = 0.1


def get_travel_speed_m_s() -> float:
    """Walking speed in metres per GAME second, from the world setting
    `game.travel_speed_m_s`.

    The boundary between "garbage" and "extreme but meant":
      * missing, non-numeric, bool, NaN/inf, **zero or negative** -> the
        default. Zero counts as garbage on purpose: an emptied admin field
        arrives as 0, and silently reading that as "stand still forever"
        would break every new journey without anyone asking for it.
      * 0 < value < 0.1 is absurdly slow but positive and deliberate ->
        clamped up to 0.1; anything above 20 m/s is clamped down.

    Read at journey START only: the speed is written onto the journey, so a
    running journey keeps the pace it started with and clients keep deriving
    the same position from the same payload.
    """
    from app.core import config
    raw = config.get("game.travel_speed_m_s", DEFAULT_SPEED_M_S)
    if raw is None:
        return DEFAULT_SPEED_M_S
    if isinstance(raw, bool):
        return _reject_speed(raw)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _reject_speed(raw)
    if not math.isfinite(value) or value <= 0:
        return _reject_speed(raw)
    return min(max(value, _MIN_SPEED_M_S), _MAX_SPEED_M_S)


_speed_warned = False


def _reject_speed(raw: Any) -> float:
    """Log the discarded setting ONCE and return the default — the fallback
    sits on the journey-start path, a warning per journey would spam."""
    global _speed_warned
    if not _speed_warned:
        _speed_warned = True
        logger.warning("Unusable game.travel_speed_m_s (%r) — using the "
                       "default %.2f m/s", raw, DEFAULT_SPEED_M_S)
    return DEFAULT_SPEED_M_S


def journey_state(waypoints: Sequence[Sequence[float]], started_at_game: str,
                  now_game: GameTime) -> Dict[str, Any]:
    """Position on ``waypoints`` at game time ``now_game`` — pure, no I/O.

    ``started_at_game`` is a canonical world-calendar stamp
    (``Y0002-D109T14:00:00``), ``now_game`` a :class:`GameTime`. The journey
    maths itself stays in plain GAME SECONDS — only the type at the edge is
    calendar-aware.

    Returns ``{pos, seg, arrived, eta_game, progress_m, total_m}``:

    pos         (x, z) in world metres, interpolated inside the segment the
                elapsed time falls into
    seg         index of the segment being walked (0-based); a waypoint's
                own instant belongs to the segment STARTING there
    arrived     the elapsed time has reached the last waypoint's ``t_cum``
    eta_game    canonical GAME stamp of the arrival (start + last ``t_cum``)
    progress_m  metres walked so far, ``total_m`` the polyline length

    Robustness the caller may rely on:
      * zero-LENGTH and zero-TIME segments are skipped, never divided by
        (``segment_costs`` legitimately returns 0.0 for waypoint pairs that
        round to the same point);
      * a time beyond the end stays at the LAST waypoint — a journey never
        walks past its goal;
      * a negative elapsed time (the game clock was set back) clamps to the
        start instead of walking backwards.
    """
    pts: List[Tuple[float, float, float]] = []
    for wp in waypoints or []:
        try:
            pts.append((float(wp[0]), float(wp[1]), float(wp[2])))
        except (TypeError, ValueError, IndexError):
            continue
    started = GameTime.parse(started_at_game)
    if not pts:
        # Nothing to walk: an empty polyline is an arrived journey at no
        # point at all — the callers treat `arrived` as "settle it".
        return {"pos": (0.0, 0.0), "seg": 0, "arrived": True,
                "eta_game": started.canonical(), "progress_m": 0.0,
                "total_m": 0.0}

    lengths = [math.dist((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]))
               for i in range(len(pts) - 1)]
    total_m = round(sum(lengths), 2)
    total_t = pts[-1][2]
    eta_game = (started + GameDuration.of(seconds=total_t)).canonical()
    elapsed = max(0.0, (now_game - started).seconds)

    if len(pts) == 1 or elapsed >= total_t:
        last = pts[-1]
        return {"pos": (round(last[0], 2), round(last[1], 2)),
                "seg": max(len(pts) - 2, 0), "arrived": True,
                "eta_game": eta_game, "progress_m": total_m,
                "total_m": total_m}

    walked = 0.0
    for i in range(len(pts) - 1):
        t0, t1 = pts[i][2], pts[i + 1][2]
        span = t1 - t0
        if span <= 0 or elapsed >= t1:
            # Zero-time segment (or one already behind us): its whole length
            # is walked in no time at all.
            walked += lengths[i]
            continue
        frac = (elapsed - t0) / span
        x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * frac
        z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * frac
        return {"pos": (round(x, 2), round(z, 2)), "seg": i, "arrived": False,
                "eta_game": eta_game,
                "progress_m": round(walked + lengths[i] * frac, 2),
                "total_m": total_m}

    # Unreachable in practice (elapsed < total_t means some segment still has
    # time left), kept as the honest fallback instead of an IndexError.
    last = pts[-1]
    return {"pos": (round(last[0], 2), round(last[1], 2)),
            "seg": max(len(pts) - 2, 0), "arrived": True,
            "eta_game": eta_game, "progress_m": total_m, "total_m": total_m}


def segment_pace_m_s(waypoints: Sequence[Sequence[float]],
                     st: Dict[str, Any]) -> Optional[float]:
    """The REAL pace of the segment being walked right now, in metres per
    GAME second — or ``None`` when there is no such segment.

    ``speed_m_s`` on the journey is the NOMINAL pace; the terrain's
    ``speed_factor`` (§ A1.5) lives only in the baked ``t_cum`` stamps, so the
    pace a figure actually keeps is read back out of them:

        |w[seg+1] − w[seg]| / (t[seg+1] − t[seg])

    ``None`` for an arrived journey (there is no current segment any more) and
    for degenerate geometry (a zero-length or zero-time segment — both legal,
    ``segment_costs`` produces them). The caller turns it into REAL seconds
    with the clock factor, exactly like ``speed_m_s_real``.

    CONTRACT — where the index comes from: ``st`` must be the answer of
    ``journey_state(waypoints, …)`` over the VERY waypoint list passed in here
    (the journey's own ``waypoints``, never a walked prefix or a re-sampled
    copy). ``st['seg']`` is an index INTO that list: segment ``seg`` runs from
    ``waypoints[seg]`` to ``waypoints[seg + 1]``, so it is 0-based over the
    SEGMENTS and never reaches ``len(waypoints) - 1``. Handing in a different
    list silently reads a different segment — the reason the out-of-range and
    type errors below answer ``None`` instead of raising: a mismatched pair is
    "no pace known", never a crash in the worldmap payload.
    """
    if st.get("arrived"):
        return None
    try:
        seg = int(st.get("seg") or 0)
        x0, z0, t0 = (float(waypoints[seg][0]), float(waypoints[seg][1]),
                      float(waypoints[seg][2]))
        x1, z1, t1 = (float(waypoints[seg + 1][0]), float(waypoints[seg + 1][1]),
                      float(waypoints[seg + 1][2]))
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    span = t1 - t0
    length = math.dist((x0, z0), (x1, z1))
    if span <= 0 or length <= 0:
        return None
    return length / span


def get_journey(character_name: str,
                profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any] | None:
    """The character's active journey dict, or None.

    A journey whose target does not match ``movement_target`` is stale (a
    manual teleport cleared the target, or another writer re-pointed it) and
    is treated as absent.

    An OLD-format journey (``path`` of location ids, v1) is discarded here —
    no migration by decision: the stored travel ends, and the movement target
    is cleared with it so nothing keeps pointing at a route that no longer
    exists. One write, on the first read after the format change.

    ``profile``: an already-loaded character profile to read from. Callers
    that hold one anyway (the worldmap loop) pass it and save a DB round-trip.
    """
    if not character_name:
        return None
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    j = profile.get("journey")
    if not isinstance(j, dict):
        return None
    if j.get("path") is not None:
        from app.models.character import clear_movement_target
        logger.info("Discarding a v1 journey of %s (no migration)",
                    character_name)
        clear_movement_target(character_name)   # drops the journey dict too
        profile.pop("journey", None)
        profile["movement_target"] = ""
        return None
    if not (j.get("waypoints") and j.get("target") and j.get("started_at_game")):
        return None
    if (profile.get("movement_target") or "").strip() != j.get("target"):
        return None
    return j


def _boundary_rim_point(loc: Dict[str, Any],
                        toward: Point) -> Optional[Point]:
    """The point on the location's BOUNDARY RIM nearest to ``toward``, or None
    when the location has no area at all.

    The fallback for a location without an authored opening: the journey still
    has to end somewhere on the place, and the closest rim point is where a
    traveller coming from ``toward`` would touch it. Deterministic by
    construction — ``toward`` is projected onto EVERY boundary edge (clamped to
    the edge, so a corner answers for the wedge beyond it) and the shortest of
    those projections wins; there is no candidate list to pick from and no
    dependence on the winding start. On a square this is the old facing-edge
    midpoint whenever the traveller stands straight in front of the edge, and a
    strictly better goal when it does not (contract v6 "Gebiete": concave
    outlines have no "facing edge" to speak of).

    (Whether a location may be entered at all is a gameplay question —
    ``boundary_entry.has_entrance`` and the access rules answer it, not this
    geometry.)
    """
    from app.core.world_geometry import boundary_world_points
    pts = boundary_world_points(loc)
    if not pts:
        return None
    tx, tz = float(toward[0]), float(toward[1])
    best: Optional[Point] = None
    best_d = 0.0
    j = len(pts) - 1
    for i, (xi, zi) in enumerate(pts):
        xj, zj = pts[j]
        j = i
        dx, dz = xi - xj, zi - zj
        length_sq = dx * dx + dz * dz
        if length_sq < 1e-18:
            px, pz = xj, zj                 # degenerate edge: its own vertex
        else:
            t = ((tx - xj) * dx + (tz - zj) * dz) / length_sq
            t = max(0.0, min(1.0, t))
            px, pz = xj + t * dx, zj + t * dz
        d = math.dist((px, pz), (tx, tz))
        if best is None or d < best_d:
            best, best_d = (round(px, 2), round(pz, 2)), d
    return best


def _opening_point(loc: Dict[str, Any],
                   toward: Point) -> Optional[Tuple[int, Point]]:
    """``(edge index, point)`` of the authored opening of ``loc`` nearest to
    ``toward``, or None when the location has none (or is unplaced).

    The EDGE travels with the point because the arrival needs it: an opening's
    room link is what routes the arriving character, and only the boundary
    edge it sits on identifies which of several openings the route aimed at.
    """
    from app.core.boundary_entry import opening_world_points
    points = opening_world_points(loc)
    if not points:
        return None
    return min(points, key=lambda ep: math.dist(ep[1], toward))


def _arrival_point(loc: Dict[str, Any],
                   toward: Point) -> Optional[Tuple[Optional[int], Point]]:
    """Where a journey ENDS on ``loc``, as ``(entry_edge, point)``: the
    authored opening nearest to ``toward``, else the nearest point on the
    boundary rim — the latter with edge ``None``, because a made-up geometric
    point is no authored entrance and makes no statement about the room.

    A location without an opening has a FREE boundary (E4 task 5) — it can be
    entered, it just never said where. The nearest rim point is then as good
    a goal as any, and the MISSING edge is what tells the arrival check that
    no authored opening was walked to (so the ordinary arrival room decides).
    The rule gates stay where they belong: at the arrival check, not here.
    """
    found = _opening_point(loc, toward)
    if found is not None:
        return found
    rim_point = _boundary_rim_point(loc, toward)
    return None if rim_point is None else (None, rim_point)


def start_journey(character_name: str,
                  target_id: str) -> Tuple[Dict[str, Any] | None, str]:
    """Begin a timed journey to ``target_id``.

    Returns ``(journey, reason)`` — exactly one of the two is filled:

    ``''``              the journey was stored and is running
    ``unknown_target``  no such location, or the character does not know it
                        (the knowledge gate sits on the TARGET only; the way
                        over open terrain is free)
    ``unplaced_target`` the location exists but stands on no map
    ``no_route``        no walkable polyline (terrain, buildings, or the
                        character has no point to start from)

    Leave/access checks are the CALLER's job (SetLocation already does them)
    — this only handles the mechanics. The route is
    ``position → own opening → target opening``: a character standing in a
    placed location leaves through ITS opening, exactly like every other way
    out. Where the journey ARRIVES (which room) is decided at arrival time by
    the ticker, not here.
    """
    from app.core.nav_grid import build_nav_context, route, segment_costs
    from app.core.world_geometry import effective_boundary
    from app.models.character import (get_character_current_location,
                                      get_character_pos, get_character_profile,
                                      get_known_locations,
                                      save_character_profile)
    from app.models.world import get_location_by_id

    if not character_name or not target_id:
        return None, "unknown_target"

    target = get_location_by_id(target_id)
    if not target:
        return None, "unknown_target"
    if target_id not in (get_known_locations(character_name) or []):
        return None, "unknown_target"
    if effective_boundary(target) is None:
        return None, "unplaced_target"

    current_id = (get_character_current_location(character_name) or "").strip()
    if current_id == target_id:
        # Already standing in the target — there is nothing to walk. The
        # callers guard this (SetLocation only journeys across locations), so
        # this is the belt, not the braces.
        return None, "no_route"

    pos = get_character_pos(character_name)
    current_loc = get_location_by_id(current_id) if current_id else None
    if pos is not None:
        start: Optional[Point] = (float(pos["x"]), float(pos["z"]))
    elif current_loc is not None and effective_boundary(current_loc) is not None:
        cx, cz, _yaw, _pts = effective_boundary(current_loc)
        start = (cx, cz)                    # never positioned: the anchor pin
    else:
        # No point and no placed location to derive one from: the character
        # is nowhere on the map, so no route can start. Not a knowledge or
        # placement problem of the TARGET — reported as no_route, the only
        # reason that describes "there is no walkable line".
        logger.info("No start point for %s (pos None, location %r) — "
                    "no journey", character_name, current_id or "")
        return None, "no_route"

    arrival = _arrival_point(target, start)
    if arrival is None:                     # placement was checked above
        return None, "no_route"
    entry_edge, goal = arrival

    ctx = build_nav_context()               # ONE context for the whole start
    legs: List[List[Point]] = []
    own_opening = (_opening_point(current_loc, goal)
                   if current_loc is not None else None)
    exit_point = None if own_opening is None else own_opening[1]
    if exit_point is not None and math.dist(exit_point, start) > 1e-9:
        # Leave through the own opening first. A location WITHOUT an opening
        # gets no such waypoint — the character then simply walks off its own
        # footprint (which the nav grid exempts for the start), same as one
        # standing in the wilderness.
        leg = route(start, exit_point, ctx)
        if leg is None:
            return None, "no_route"
        legs.append(leg)
        legs.append(route(exit_point, goal, ctx) or [])
        if not legs[-1]:
            return None, "no_route"
    else:
        leg = route(start, goal, ctx)
        if leg is None:
            return None, "no_route"
        legs.append(leg)

    points: List[Point] = []
    for leg in legs:
        for pt in leg:
            # The joint between two legs is the same point twice — drop it,
            # a zero-length segment carries no information (journey_state
            # tolerates one, but the payload should not invent it).
            if points and math.dist(points[-1], pt) <= 1e-9:
                continue
            points.append((float(pt[0]), float(pt[1])))
    if not points:
        return None, "no_route"

    speed = get_travel_speed_m_s()
    costs = segment_costs(points, ctx)      # game-seconds at 1 m/s
    waypoints: List[List[float]] = [[points[0][0], points[0][1], 0.0]]
    t_cum = 0.0
    for i, cost in enumerate(costs):
        # A cost of 0.0 is legal (two waypoints closer than a millimetre):
        # the next waypoint then simply carries the same t_cum.
        t_cum += max(cost, 0.0) / speed
        waypoints.append([points[i + 1][0], points[i + 1][1],
                          round(t_cum, 3)])

    journey = {"target": target_id, "waypoints": waypoints,
               "started_at_game": game_time().canonical(), "speed_m_s": speed,
               "entry_edge": entry_edge}
    profile = get_character_profile(character_name)
    profile["journey"] = journey
    profile["movement_target"] = target_id
    save_character_profile(character_name, profile)

    st = journey_state(waypoints, journey["started_at_game"], game_time())
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("travel_started", character_name, target_id=target_id,
                       total_m=st["total_m"], eta_game=st["eta_game"])
    except Exception:
        pass
    logger.info("Journey started: %s -> %s (%.1f m, %d waypoints, %.2f m/s)",
                character_name, target_id, st["total_m"], len(waypoints), speed)
    return journey, ""


def cancel_journey(character_name: str) -> None:
    """Drop journey + movement target — the character stays where they are."""
    from app.models.character import clear_movement_target
    clear_movement_target(character_name)   # clears journey too (see character.py)
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("travel_cancelled", character_name)
    except Exception:
        pass


# Lateral spacing of party followers next to their leader, in metres.
_FOLLOWER_SPACING_M = 1.2

# Arc-length step for walking a blocked journey back off the target, in metres.
_DOOR_STANDOFF_M = 0.5


def _point_back_along(pts: Sequence[Point], distance: float) -> Point:
    """The point ``distance`` metres back from the END of the polyline ``pts``.

    UNROUNDED — the caller decides when to snap, because rounding is what can
    push a point back onto a footprint boundary. Degenerate geometry is walked
    over, not divided by: zero-length segments are skipped (``segment_costs``
    legitimately produces them), a distance longer than the polyline ends at
    its first point.
    """
    remaining = distance
    for i in range(len(pts) - 1, 0, -1):
        start, end = pts[i - 1], pts[i]
        length = math.dist(start, end)
        if length <= 1e-9:
            continue
        if length >= remaining:
            frac = remaining / length
            return (end[0] + (start[0] - end[0]) * frac,
                    end[1] + (start[1] - end[1]) * frac)
        remaining -= length
    return pts[0]


def _standoff_point(waypoints: Sequence[Sequence[float]], fallback: Point,
                    target_id: str) -> Optional[Point]:
    """Where a REFUSED journey comes to rest — or None when there is no such
    point on the whole route.

    The route's goal is the target's OPENING, and that point lies ON the
    target's footprint (the footprint test is inclusive): a character parked
    there stands in the very location the rule just refused it, and the next
    ordinary position write derives exactly that and walks it in through the
    closed door.

    "One step back is outside" is FALSE, so nothing here is by construction —
    every candidate is VERIFIED. Two geometries put a fixed back-step inside
    the target: a final segment running collinear with a footprint wall (the
    nav grid's cell centre lines fall on the walls for common placements, so
    A* plus smoothing walks straight down one), and a route that legally cuts
    through the target's own footprint (the grid exempts it for its own
    route), which puts every approach from behind or beside it inside. So the
    walk continues backwards in ``_DOOR_STANDOFF_M`` steps until a point no
    longer DERIVES the target — measured the way the consumer measures it,
    with ``location_at_point`` over all locations. Landing inside a foreign
    third footprint on the way is accepted: that character really is standing
    in that place, and pretending otherwise would be the dishonest answer.

    Rounding is part of the test, not an afterthought: 94.997 snaps onto an
    inclusive boundary at 95.0, so a candidate is checked unrounded AND after
    the snap, and a snap that lands inside costs one more step back.

    None means not one point of the polyline lies outside the target (a route
    running entirely within its footprint — possible, see the exemption
    above). The caller owns that case; there is no honest "in front of the
    door" to report.
    """
    from app.core.world_geometry import location_at_point
    from app.models.world import list_locations

    pts: List[Point] = []
    for wp in waypoints or []:
        try:
            pts.append((float(wp[0]), float(wp[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if not pts:
        pts = [(float(fallback[0]), float(fallback[1]))]
    locations = list_locations()

    def outside(point: Point) -> bool:
        at = location_at_point(point[0], point[1], locations)
        return ((at.get("id") or "") if at else "") != target_id

    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    distance = _DOOR_STANDOFF_M
    while distance <= total + 1e-9:
        raw = _point_back_along(pts, distance)
        if outside(raw):
            snapped = (round(raw[0], 2), round(raw[1], 2))
            if outside(snapped):
                return snapped
            # The snap pushed it back onto the footprint — one more step.
        distance += _DOOR_STANDOFF_M
    # The steps may not have reached the very first waypoint (the polyline is
    # rarely a multiple of the step); it is the last candidate there is.
    start = (round(pts[0][0], 2), round(pts[0][1], 2))
    return start if outside(start) else None


def _follower_offsets(count: int) -> List[float]:
    """Signed lateral offsets for ``count`` followers, in metres.

    Index-based and deterministic — no shuffling, no per-tick randomness: the
    first follower walks 1.2 m to one side, the second the same distance to
    the other, the third 2.4 m out, and so on. A small marching column that
    every client derives identically, because it derives it from the index.
    """
    return [_FOLLOWER_SPACING_M * (i // 2 + 1) * (1 if i % 2 == 0 else -1)
            for i in range(count)]


def _segment_perpendicular(waypoints: Sequence[Sequence[float]],
                           seg: int) -> Point:
    """Unit vector perpendicular (left-hand) to segment ``seg``.

    Falls back to the +x axis when there is no direction to be perpendicular
    to: a zero-length segment is legal (``segment_costs`` returns 0.0 for
    waypoints closer than a millimetre) and a standing party still has to
    stand NEXT to its leader instead of inside them.
    """
    try:
        x0, z0 = float(waypoints[seg][0]), float(waypoints[seg][1])
        x1, z1 = float(waypoints[seg + 1][0]), float(waypoints[seg + 1][1])
    except (IndexError, TypeError, ValueError):
        return (1.0, 0.0)
    dx, dz = x1 - x0, z1 - z0
    length = math.hypot(dx, dz)
    if length <= 1e-9:
        return (1.0, 0.0)
    return (-dz / length, dx / length)


def _move_party_followers(leader: str, leader_location: str, pos: Point,
                          waypoints: Sequence[Sequence[float]],
                          seg: int) -> None:
    """Walk the leader's followers alongside them for this tick.

    Followers are a pure function of the leader's position, so nothing has to
    be settled for them and a follower joining mid-journey simply appears in
    formation on the next tick. Their LOCATION change is not done here: the
    arrival's ``_drag_party_followers_to_location`` hook owns that, unchanged.

    The formation NEVER puts a follower somewhere the leader is not. The
    offset point derives its own location like every other position write, and
    1.2 m beside the route is easily inside a shed the party merely walks
    past — which would run the whole location-change cascade (events, history,
    compliance, background renders) for a figure that is gone again on the
    next tick. When the offset point disagrees with the leader's own location,
    the formation yields and the follower stands on the leader's point: one
    deterministic answer, no shrink-until-it-fits search whose result would
    depend on the step size.
    """
    from app.core.party_engine import party_followers
    from app.core.world_geometry import location_at_point
    from app.models.character import set_character_pos
    from app.models.world import list_locations
    followers = [f for f in party_followers(leader) if f and f != leader]
    if not followers:
        return
    px, pz = _segment_perpendicular(waypoints, seg)
    locations = list_locations()
    for follower, offset in zip(followers, _follower_offsets(len(followers))):
        try:
            fx = round(pos[0] + px * offset, 2)
            fz = round(pos[1] + pz * offset, 2)
            at = location_at_point(fx, fz, locations)
            if ((at.get("id") or "") if at else "") != leader_location:
                fx, fz = round(pos[0], 2), round(pos[1], 2)
            # preserve_movement_target=True although a follower has nothing to
            # preserve: this IS a travel step, and the plain write would fire
            # the manual-teleport journey cancel on every single tick.
            set_character_pos(follower, fx, fz, preserve_movement_target=True)
        except Exception as e:
            logger.debug("party follow failed for %s: %s", follower, e)


def _cancel_follower_journeys(leader: str) -> None:
    """Followers do not travel on their own account.

    A follower that joined WHILE travelling keeps its own journey, and the
    ticker would otherwise advance it beside the formation write (which of the
    two lands last depending on the character order) and, worse, keep walking
    it after the party has long arrived somewhere else. A character loses
    SetLocation when it joins a party, so it loses the journey with it — on
    every tick the leader is on the road AND on the tick it arrives.
    """
    from app.core.party_engine import party_followers
    for follower in party_followers(leader):
        if follower and follower != leader \
                and get_journey(follower) is not None:
            cancel_journey(follower)


def _leave_still_allowed(name: str) -> bool:
    """Leave re-check for a traveller that has not left its start location yet.

    Returns False after cancelling the journey and recording the denial — the
    old walk step wrote it to state_history too, so diary and recent-activity
    surface the aborted trip in the next thought turn.
    """
    try:
        from app.models.rules import check_leave
        ok, reason = check_leave(name)
    except Exception:
        return True
    if ok:
        return True
    cancel_journey(name)
    try:
        from app.models.character import (get_character_current_location,
                                          record_access_denied)
        from app.models.world import get_location_name
        cur = (get_character_current_location(name) or "").strip()
        record_access_denied(name, cur, get_location_name(cur) or cur,
                             reason, action="leave")
    except Exception:
        logger.debug("record_access_denied(travel-leave) failed", exc_info=True)
    logger.info("Journey blocked (leave rule): %s — %s", name, reason)
    return False


def _arrival_gate(name: str, target_id: str, target: Dict[str, Any],
                  entry_room: str) -> Tuple[bool, str]:
    """The two walls in front of a journey's target — ``(ok, reason)``.

    ``rules.check_access`` is the rule engine's own gate. ``accessible_when``
    is the field the world map greys a place out with, and NO rule row backs
    it: it is enforced only where a movement path asks for it, and that is
    FOUR places — ``POST /play/travel`` and ``POST /play/pos`` (the free
    walker) in ``routes/play.py``, the SetLocation skill, and this arrival.
    All four read ``world_ops.conditions_pass``. This one is what makes the
    condition bite for every NPC and for every rule that flips while someone
    is already on the road.
    """
    from app.core.world_ops import conditions_pass
    from app.models.rules import check_access

    ok, reason = check_access(name, target_id, room_id=entry_room)
    if not ok:
        return False, reason
    if not conditions_pass(target.get("accessible_when") or [], name,
                           target_id):
        from app.core.i18n import t
        from app.models.character import get_character_language
        return False, t("This place is not accessible to you.",
                        get_character_language(name) or "de")
    return True, ""


def _walked_prefix(journey: Dict[str, Any],
                   st: Dict[str, Any]) -> List[List[float]]:
    """The route as far as it has actually been WALKED, ending on ``st['pos']``.

    The standoff of a refused arrival must never teleport anyone FORWARD: an
    EARLY arrival (the derived crossing, see ``advance_all_journeys``) is
    refused in the middle of the route, and stepping back from the polyline's
    END would drop the character next to a door it has not reached yet.
    Waypoints 0..``seg`` are behind the walker, ``pos`` is where it stands.

    For a real arrival this reproduces the full polyline exactly (``seg`` is
    then the last segment and ``pos`` its end point), so both paths share one
    standoff computation.
    """
    waypoints = journey.get("waypoints") or []
    try:
        seg = int(st.get("seg") or 0)
    except (TypeError, ValueError):
        seg = 0
    prefix: List[List[float]] = []
    for wp in waypoints[:max(seg, 0) + 1]:
        try:
            prefix.append([float(wp[0]), float(wp[1])])
        except (TypeError, ValueError, IndexError):
            continue
    prefix.append([float(st["pos"][0]), float(st["pos"][1])])
    return prefix


def _at_goal(journey: Dict[str, Any], st: Dict[str, Any]) -> bool:
    """Is the settling point on the FINAL APPROACH to the journey's own goal?

    Measured as REMAINING ROUTE (``total_m − progress_m``) against one
    ticker's worth of travel at the journey's own speed — not as the
    Euclidean distance to the last waypoint (E3 residual, decided in E4).

    The Euclidean radius was wrong for exactly the geometry the pathfinder
    produces most often: a final approach that runs COLLINEAR with the
    target's own wall. The footprint test is inclusive, so the route's last
    metres already lie IN the target, the ticker catches the crossing a few
    metres before the door — and a 0.5 m radius then called that "somewhere
    else entirely" and handed out the arrival room, although the traveller is
    walking to that very opening.

    One tick's travel is the honest bound: the ticker can never catch the
    crossing closer than the distance one tick covers, so anything within it
    IS the last leg. That distance is a THREE-factor product, and all three
    have to be there — the earlier docstring claimed the window was
    factor-independent, which it never was:

        window_m = _TICK_SECONDS (REAL seconds per tick)
                 × game_speed_factor() (GAME seconds per REAL second)
                 × speed_m_s (metres per GAME second)

    A world running at factor 4 walks four times as far between two ticks, so
    its final approach starts four times earlier; at factor 0.25 the window
    shrinks the same way. ``_GOAL_FACTOR_FLOOR`` catches the frozen world
    (factor 0.0), where the product would otherwise be 0 m and no crossing
    could ever be the goal.

    False for an early derived crossing far from the end (the route legally
    cuts through the target's footprint on its way to a door facing away):
    that figure entered the building somewhere else, and claiming the door's
    room for it would be a lie.
    """
    if not (journey.get("waypoints") or []):
        return False
    try:
        speed = float(journey.get("speed_m_s") or 0.0)
        remaining = (float(st.get("total_m") or 0.0)
                     - float(st.get("progress_m") or 0.0))
    except (TypeError, ValueError):
        return False
    if speed <= 0:                      # a journey without a usable speed
        speed = DEFAULT_SPEED_M_S       # still walks at the default pace
    factor = max(game_speed_factor(), _GOAL_FACTOR_FLOOR)
    return remaining <= _TICK_SECONDS * factor * speed


def _settle_arrival(name: str, journey: Dict[str, Any],
                    st: Dict[str, Any]) -> None:
    """The journey reaches its target: entry gate, then the crossing.

    Called for BOTH ways into the target — the ordinary arrival at the last
    waypoint AND the early derived crossing the ticker catches in flight (see
    ``advance_all_journeys``). Everything that differs between the two is
    derived from ``st`` here: which room the arrival lands in (the opening's
    only when the walker really stands at that opening) and how far back the
    standoff of a refusal may step (only over the walked prefix).
    """
    from app.core.boundary_entry import opening_entry_room
    from app.models.character import (clear_pose_intent, get_movement_target,
                                      record_access_denied,
                                      save_character_current_location,
                                      save_character_current_room,
                                      set_character_pos)
    from app.models.world import (get_arrival_room_id, get_location_by_id,
                                  get_location_name)

    target_id = journey["target"]
    target = get_location_by_id(target_id) or {}
    # The arrival room: an authored opening WITH a room link answers the
    # question by itself, and the journey remembers which opening it walked to
    # — a location with several doors therefore routes into the right room.
    # Everything else falls back to the one arrival rule (declared entry room,
    # otherwise the ground) — including a crossing that did NOT happen at that
    # opening, which has no claim on the room behind it.
    entry_edge = journey.get("entry_edge")
    at_goal = _at_goal(journey, st)
    entry_room = (opening_entry_room(target, entry_edge)
                  if isinstance(entry_edge, int)
                  and not isinstance(entry_edge, bool)
                  and at_goal else "")
    if not entry_room:
        entry_room = get_arrival_room_id(target)

    ok, reason = _arrival_gate(name, target_id, target, entry_room)
    if not ok:
        # Blocked at the door: the journey ends on the last point of its route
        # that does not lie in the refused location (see _standoff_point).
        # Cancel first, then write the position the ORDINARY way — the journey
        # is over, so this is no travel step any more, and letting the write
        # derive the location is the point: the standoff was verified against
        # the same reader, so it cannot walk anyone through the closed door.
        stand = _standoff_point(_walked_prefix(journey, st), st["pos"],
                                target_id)
        cancel_journey(name)
        if stand is not None:
            set_character_pos(name, stand[0], stand[1])
        else:
            # Not ONE point of the route lies outside the target — the whole
            # polyline runs within its footprint (the nav grid exempts a
            # route's own start/target footprints, so this is reachable, not
            # theoretical). There is no honest "in front of the door" to
            # stand on, so this is the one place a RAW position write is
            # right: the figure keeps the door point it walked to, and
            # location + room are cleared explicitly — the refusal must never
            # be readable as an entry, and no deriving write may re-invent one.
            from app.models.character import (_clear_location_and_room,
                                              _write_character_pos)
            _write_character_pos(name, st["pos"][0], st["pos"][1])
            _clear_location_and_room(name)
        try:
            record_access_denied(name, target_id,
                                 get_location_name(target_id) or target_id,
                                 reason, action="enter")
        except Exception:
            logger.debug("record_access_denied(travel-enter) failed",
                         exc_info=True)
        try:
            from app.core.state_events import publish as _publish_state
            _publish_state("travel_blocked", name, target_id=target_id,
                           reason=reason)
        except Exception:
            pass
        logger.info("Journey blocked at the door: %s -> %s (%s)",
                    name, target_id, reason)
        return

    # The crossing. _preserve_movement_target=True marks it as a PROGRAMMED
    # step: the setter clears target + journey precisely because the new
    # location IS the target, and drags the party followers along on the way.
    save_character_current_location(name, target_id,
                                    _preserve_movement_target=True)
    # Write the room explicitly: the opening may route somewhere other than
    # the arrival room the location write picks by itself, and only an
    # explicit write clears the room the character came from.
    save_character_current_room(name, entry_room)
    # The one case the setter cannot clear: the character ALREADY stood in the
    # target (an editor moved the location onto it mid-journey), so nothing
    # changed and the clearing branch never ran — without this the arrival
    # would be re-settled on every single tick, forever.
    if get_movement_target(name):
        cancel_journey(name)
    # The party ARRIVES in formation, not in a stack. The location write above
    # dragged every follower into the target and put them on its centre, i.e.
    # exactly on top of the leader — the same offsets the road used are the
    # honest end of the journey. Perpendicular to the LAST segment: the party
    # keeps facing the way it came in.
    try:
        from app.models.character import get_character_pos
        pos = get_character_pos(name)
        waypoints = journey.get("waypoints") or []
        if pos is not None and len(waypoints) >= 2:
            _move_party_followers(name, target_id,
                                  (float(pos["x"]), float(pos["z"])),
                                  waypoints, len(waypoints) - 2)
    except Exception:
        logger.debug("party arrival formation failed for %s", name,
                     exc_info=True)
    try:
        clear_pose_intent(name)   # D6: arrival = location change
    except Exception:
        logger.debug("clear pose on arrival failed for %s", name, exc_info=True)
    # Roll-on-entry, exactly like the avatar step: arriving somewhere is what
    # rolls for an event ("wolves block the path"). The v1 asymmetry (the step
    # rolled, the journey did not) is resolved in favour of the step.
    try:
        from app.core.random_events import try_roll_on_entry
        try_roll_on_entry(name, target_id, target)
    except Exception:
        logger.debug("try_roll_on_entry failed for %s", name, exc_info=True)
    # check_discover_rules is deliberately NOT called HERE: arriving already
    # discovers the target (``save_character_current_location``), and the
    # sight pass at the end of every tick (``_note_positions``) has long
    # revealed everything else within range. The rule's own roll belongs to
    # the thought turn, where its CONDITION is evaluated against a character
    # that is about to think. (Its message has no reader anywhere today — the
    # agent loop discards the return value; wiring it up as a perception
    # payload is an open follow-up.)
    try:
        from app.core.agent_loop import get_agent_loop
        get_agent_loop().bump(name)    # think at the destination
    except Exception:
        pass
    logger.info("Journey arrived: %s @ %s (room %s)", name, target_id,
                entry_room)


def advance_all_journeys() -> None:
    """Apply elapsed game time to every active journey: write the in-flight
    position, keep the party together, settle arrivals.

    Called by the TravelTicker; each call is cheap when no one travels.

    The in-flight write goes through ``set_character_pos(...,
    preserve_movement_target=True)``: the point DERIVES the location (walking
    over open terrain with an empty ``current_location`` is the normal state
    of a journey, not an error), and only the preserving variant survives the
    moment that derived location changes — the plain write would pop
    ``movement_target`` and the journey with it.

    **An in-flight point may never derive the journey's own TARGET.** The nav
    grid exempts the target's footprint for the target's own route, so a route
    to an opening that faces away legally crosses the building — and the first
    tick inside it would otherwise write the target as an ordinary derived
    location: entry cascade without the access gate, the ground room instead
    of the opening's, and the journey silently cleared halfway (the setter
    clears target + journey exactly when the new location IS the target).
    Such a tick is therefore treated as an EARLY ARRIVAL and settled through
    the same gate as the ordinary one — the crossing happens at most one tick
    late and never ungated. The check is skipped when the character already
    STANDS in the target: nothing is crossed then, and the write changes no
    location.

    The tick ALSO carries what a POSITION IMPLIES: after the positions are
    written, ``_note_positions`` reveals what everybody now stands close enough
    to (discovery by sight, E6) and records the ground they stand on in the
    exploration memory (2026-08-16). It runs as a second pass over the same
    character list and the same location snapshot — after, so a traveller sees
    what THIS tick walked it past, not what the last one did.
    """
    from app.core.world_geometry import location_at_point
    from app.models.character import (get_character_current_location,
                                      list_available_characters,
                                      set_character_pos)
    from app.models.world import list_locations
    # ONE snapshot per tick, shared by both passes — the locations do not move
    # while the ticker walks, and the discovery pass needs it every tick
    # anyway, so there is nothing left to be lazy about.
    locations: List[Dict[str, Any]] = list_locations()
    names = list_available_characters()
    now = game_time()
    for name in names:
        try:
            j = get_journey(name)
            if not j:
                continue
            st = journey_state(j["waypoints"], j["started_at_game"], now)
            current_id = (get_character_current_location(name) or "").strip()
            # Leave re-check — ONLY while the character still stands in the
            # location it set off from. A leave rule forbids stepping OUT of a
            # place; once the point has left that footprint (current_location
            # '', the wilderness that a journey spends most of its time in)
            # there is nothing left to leave, and asking again would strand
            # travellers halfway across the map whenever a rule flips.
            if current_id and current_id != j["target"] \
                    and not _leave_still_allowed(name):
                continue
            # Before the branch, so the ARRIVAL tick is covered too: a
            # follower that joined mid-journey must not walk on afterwards.
            _cancel_follower_journeys(name)
            if not st["arrived"]:
                if current_id != j["target"]:
                    at = location_at_point(st["pos"][0], st["pos"][1],
                                           locations)
                    if ((at.get("id") or "") if at else "") == j["target"]:
                        _settle_arrival(name, j, st)   # early, but gated
                        continue
                set_character_pos(name, st["pos"][0], st["pos"][1],
                                  preserve_movement_target=True)
                # Read the location back AFTER the write: it is what the
                # leader's own point just derived, and the formation is not
                # allowed to put a follower anywhere else.
                _move_party_followers(
                    name, (get_character_current_location(name) or "").strip(),
                    st["pos"], j["waypoints"], st["seg"])
                continue
            _settle_arrival(name, j, st)
        except Exception as e:
            logger.warning("advance journey failed for %s: %s", name, e)
    _note_positions(names, locations)


def _note_positions(names: List[str],
                    locations: List[Dict[str, Any]]) -> None:
    """What everybody's CURRENT point implies — the two additive records.

    1. DISCOVERY BY SIGHT (E6, ``core/discovery.py``): a place within sight
       range becomes known.
    2. The EXPLORATION MEMORY (2026-08-16, ``core/exploration.py``): the 3×3
       block of 64 m cells around the point is recorded as explored, so the
       overview veil spares walked ground. Marked for EVERY character, not only
       for the avatar — today's NPC is tomorrow's taken-over avatar, and the
       memory is per character either way. It is nearly free: a character that
       has not left its cell since the last tick costs no query at all.

    EVERY character with a point, not only the travellers: a scheduler jump, a
    teleport spell or an admin move puts someone beside a hut just as a road
    does, and the ticker is the one loop that sees all of them. Someone
    without a point (off-map) is not near anything and is skipped.

    Cheap by construction rather than by a special case: the location snapshot
    is the tick's, the POSITIONS are ONE bulk read for the whole cast
    (``list_character_positions`` — a SELECT per character per 5 s inside the
    event loop is what this loop used to cost), and ``discover_in_range`` drops
    the already-known ids BEFORE any distance is measured, so a character that
    knows its whole neighbourhood costs one blob read per tick and writes
    nothing.

    That known-locations blob is deliberately NOT bundled into a second bulk
    SELECT: it is served by ``get_character_config``, which falls back to a
    JSON file and may auto-CREATE (and write) a config for a character whose
    DB row is empty. A bulk ``SELECT config_json`` would answer differently for
    exactly the rows those branches exist for — that is a semantic change, not
    a read optimisation.

    ``names`` stays the roster: the position table can outlive a deleted
    character, and only the roster says who is still playable.
    """
    from app.core.discovery import discover_in_range
    from app.core.exploration import mark_explored
    from app.models.character import list_character_positions
    points = {p["name"]: p for p in list_character_positions()}
    for name in names:
        pos = points.get(name)
        if pos is None:
            continue
        try:
            discover_in_range(name, pos["x"], pos["z"], locations=locations)
        except Exception as e:
            logger.debug("sight discovery failed for %s: %s", name, e)
        mark_explored(name, pos["x"], pos["z"])


class TravelTicker:
    """Background loop that settles journeys every few seconds.

    Runs independently of the AgentLoop: positions must advance even while
    every character is idle or the loop is paused. A frozen world needs no
    special casing — the game clock stands still, so journey_state simply
    stops moving."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="travel-ticker")
            logger.info("TravelTicker started (%.0fs interval)", _TICK_SECONDS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("TravelTicker stopped")

    async def _run(self) -> None:
        while True:
            try:
                advance_all_journeys()
            except Exception:
                logger.exception("travel tick failed")
            await asyncio.sleep(_TICK_SECONDS)


_ticker: TravelTicker | None = None


def get_travel_ticker() -> TravelTicker:
    global _ticker
    if _ticker is None:
        _ticker = TravelTicker()
    return _ticker
