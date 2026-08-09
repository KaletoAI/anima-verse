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
        "started_at_game": "<iso>",          # GAME clock stamp
        "speed_m_s": 1.4,                    # world setting at journey start
    }

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
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger
from app.core.timeutils import parse_iso

logger = get_logger("travel_engine")

Point = Tuple[float, float]

# Metres per GAME second on neutral ground when the world setting
# `game.travel_speed_m_s` is missing or unusable — a human walking pace.
DEFAULT_SPEED_M_S = 1.4
_MIN_SPEED_M_S = 0.1
_MAX_SPEED_M_S = 20.0


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
                  now_game) -> Dict[str, Any]:
    """Position on ``waypoints`` at game time ``now_game`` — pure, no I/O.

    Returns ``{pos, seg, arrived, eta_game, progress_m, total_m}``:

    pos         (x, z) in world metres, interpolated inside the segment the
                elapsed time falls into
    seg         index of the segment being walked (0-based); a waypoint's
                own instant belongs to the segment STARTING there
    arrived     the elapsed time has reached the last waypoint's ``t_cum``
    eta_game    ISO stamp of the arrival (start + the last ``t_cum``)
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
    started = parse_iso(started_at_game)
    if not pts:
        # Nothing to walk: an empty polyline is an arrived journey at no
        # point at all — the callers treat `arrived` as "settle it".
        return {"pos": (0.0, 0.0), "seg": 0, "arrived": True,
                "eta_game": started.isoformat(), "progress_m": 0.0,
                "total_m": 0.0}

    lengths = [math.dist((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]))
               for i in range(len(pts) - 1)]
    total_m = round(sum(lengths), 2)
    total_t = pts[-1][2]
    eta_game = (started + timedelta(seconds=total_t)).isoformat()
    elapsed = max(0.0, (now_game - started).total_seconds())

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


def _footprint_edge_point(loc: Dict[str, Any],
                          toward: Point) -> Optional[Point]:
    """Midpoint of the footprint edge FACING ``toward``, or None when the
    location has no footprint.

    The fallback for a location without an authored opening: the journey
    still has to end somewhere on the building, and the edge the traveller
    approaches from is the honest guess. (Whether a location may be entered
    at all is a gameplay question — ``boundary_entry.has_entrance`` and the
    access rules answer it, not this geometry.)
    """
    from app.core.world_geometry import local_to_world, placed_footprint
    fp = placed_footprint(loc)
    if fp is None:
        return None
    cx, cz, width, yaw = fp
    half = width / 2.0
    best: Optional[Point] = None
    best_d = 0.0
    for lx, lz in ((0.0, -half), (0.0, half), (-half, 0.0), (half, 0.0)):
        x, z = local_to_world(lx, lz, cx, cz, yaw)
        d = math.dist((x, z), toward)
        if best is None or d < best_d:
            best, best_d = (round(x, 2), round(z, 2)), d
    return best


def _opening_point(loc: Dict[str, Any], toward: Point) -> Optional[Point]:
    """The authored opening of ``loc`` nearest to ``toward``, or None when the
    location has none (or is unplaced)."""
    from app.core.boundary_entry import opening_world_points
    points = [pt for _edge, pt in opening_world_points(loc)]
    if not points:
        return None
    return min(points, key=lambda p: math.dist(p, toward))


def _arrival_point(loc: Dict[str, Any], toward: Point) -> Optional[Point]:
    """Where a journey ENDS on ``loc``: the authored opening nearest to
    ``toward``, else the footprint edge midpoint facing it.

    A location without an opening cannot be entered by the gameplay rules
    (``boundary_entry.has_entrance``), but the journey still needs a goal
    point — the gate belongs to the arrival check, not to the geometry.
    """
    return _opening_point(loc, toward) or _footprint_edge_point(loc, toward)


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
    from app.core.timeutils import game_now_iso
    from app.core.world_geometry import placed_footprint
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
    if placed_footprint(target) is None:
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
    elif current_loc is not None and placed_footprint(current_loc) is not None:
        cx, cz, _w, _yaw = placed_footprint(current_loc)
        start = (cx, cz)                    # never positioned: the centre
    else:
        # No point and no placed location to derive one from: the character
        # is nowhere on the map, so no route can start. Not a knowledge or
        # placement problem of the TARGET — reported as no_route, the only
        # reason that describes "there is no walkable line".
        logger.info("No start point for %s (pos None, location %r) — "
                    "no journey", character_name, current_id or "")
        return None, "no_route"

    goal = _arrival_point(target, start)
    if goal is None:                        # placement was checked above
        return None, "no_route"

    ctx = build_nav_context()               # ONE context for the whole start
    legs: List[List[Point]] = []
    exit_point = (_opening_point(current_loc, goal)
                  if current_loc is not None else None)
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
               "started_at_game": game_now_iso(), "speed_m_s": speed}
    profile = get_character_profile(character_name)
    profile["journey"] = journey
    profile["movement_target"] = target_id
    save_character_profile(character_name, profile)

    st = journey_state(waypoints, journey["started_at_game"], _game_now())
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


def _game_now():
    from app.core.timeutils import game_now
    return game_now()


def advance_all_journeys() -> None:
    """Apply elapsed game time to every active journey and settle arrivals.

    Called by the TravelTicker; each call is cheap when no one travels.

    TODO(Task 3): this is the v1 ticker minimally adapted to v2 — it only
    settles ARRIVALS. The in-flight position write is missing: v2 walks over
    free terrain, so the ticker has to write the interpolated point via
    ``set_character_pos`` every tick (the v1 intermediate hop through
    ``save_character_current_location`` had grid cells to hop between and is
    meaningless now). Task 3 also moves the leave re-check to the phase where
    it still means something (before the character has left its start
    location), drops the dead ``check_discover_rules`` call (grid neighbours,
    dead until E6) and adds the party-follower offsets.
    """
    from app.models.character import list_available_characters
    now = _game_now()
    for name in list_available_characters():
        try:
            j = get_journey(name)
            if not j:
                continue
            st = journey_state(j["waypoints"], j["started_at_game"], now)
            if not st["arrived"]:
                # TODO(Task 3): write st["pos"] here — but NOT with a plain
                # ``set_character_pos``: as soon as the interpolated point
                # enters ANY footprint, that function routes through
                # ``save_character_current_location`` without
                # ``_preserve_movement_target``, which clears movement_target
                # and the journey with it — the journey would kill itself on
                # the first tick it touches a building. Task 3 needs a
                # preserve-aware write (a ``preserve_movement_target``
                # passthrough on set_character_pos, or a dedicated ticker
                # writer) before it can move anyone in flight.
                continue
            try:
                from app.models.rules import check_leave
                leave_ok, leave_reason = check_leave(name)
            except Exception:
                leave_ok, leave_reason = True, ""
            if not leave_ok:
                cancel_journey(name)
                # Make the cancel visible to the character: the old walk-step
                # recorded the denial into state_history, diary/recent-activity
                # surface it in the next thought turn.
                try:
                    from app.models.character import (
                        get_character_current_location, record_access_denied)
                    from app.models.world import get_location_name
                    cur = (get_character_current_location(name) or "").strip()
                    cur_name = get_location_name(cur) or cur
                    record_access_denied(name, cur, cur_name,
                                         leave_reason, action="leave")
                except Exception:
                    logger.debug("record_access_denied(travel-leave) failed",
                                 exc_info=True)
                logger.info("Journey blocked (leave rule): %s — %s",
                            name, leave_reason)
                continue
            # Arrival: save_… clears movement_target (location == target) and
            # the journey dict with it; the arrival room is decided inside.
            from app.models.character import save_character_current_location
            save_character_current_location(name, j["target"],
                                            _preserve_movement_target=True)
            try:
                from app.models.character import clear_pose_intent
                clear_pose_intent(name)   # D6: arrival = location change
            except Exception:
                logger.debug("clear pose on arrival failed for %s", name,
                             exc_info=True)
            try:
                from app.models.rules import check_discover_rules
                check_discover_rules(name)
            except Exception:
                logger.debug("discover check failed for %s", name,
                             exc_info=True)
            try:
                from app.core.agent_loop import get_agent_loop
                get_agent_loop().bump(name)    # think at the destination
            except Exception:
                pass
            logger.info("Journey arrived: %s @ %s", name, j["target"])
        except Exception as e:
            logger.warning("advance journey failed for %s: %s", name, e)


_TICK_SECONDS = 5.0


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
