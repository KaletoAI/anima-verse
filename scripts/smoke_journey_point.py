#!/usr/bin/env python3
"""Smoke run for the POINT journey (`start_journey_to_point`, E3-0).

Runs against a THROWAWAY storage directory — never touches a real world.

A point journey is the wilderness twin of the location journey: the goal is
a free (x, z) instead of a location id, so there is no knowledge gate, no
boundary to aim at and no ``movement_target`` to stamp. Everything else is
shared — the same nav grid, the same baked ``t_cum`` polyline, the same
``journey_state`` and the same ticker.

Rules every expectation below is derived from BY HAND:

  * ``nav_grid.route`` keeps the REAL start and the REAL goal as the first
    and last waypoint and smooths everything between them away when the
    straight line is clear (``nav_grid.route`` docstring). Over one flat
    grass rectangle the line from (0, 0) to (30, 0) is clear, so the route
    is exactly those two points.
  * ``nav_grid.segment_costs`` answers GAME SECONDS AT 1 m/s, i.e. the
    segment length divided by the terrain's ``speed_factor``. ``grass`` has
    ``speed_factor`` 1.0 (``shared/terrain/types.json``), so the cost of the
    single segment is its plain length, 30.0.
  * ``start_journey_to_point`` divides that by the world's travel speed
    (``game.travel_speed_m_s``, read ONCE at the start and written onto the
    journey). The smoke pins it to 3.0 m/s so every stamp is a whole number.
  * ``journey_state`` is a pure function of the GAME clock: the position is
    the linear interpolation inside the segment the elapsed time falls in.
  * ``deep_water`` is ``passable: false`` (``shared/terrain/types.json``) —
    the blocked kind this smoke paints its forbidden goal on.

Hand-derived expectations:

  [1] The journey from (0, 0) to (30, 0), speed 3.0 m/s:
        distance   = |(30,0) − (0,0)| = 30.0 m
        cost       = 30.0 / 1.0 (grass) = 30.0 game-seconds at 1 m/s
        travel time = 30.0 / 3.0 = 10.0 GAME seconds
      so the waypoints are [[0.0, 0.0, 0.0], [30.0, 0.0, 10.0]] — two of
      them, ``target`` empty, ``target_point`` {'x': 30.0, 'z': 0.0},
      ``entry_edge`` None, ``speed_m_s`` 3.0. NO ``movement_target`` is
      stamped (a free point has no id to stamp), and ``get_journey`` returns
      the dict anyway — a point journey identifies itself by its own goal.

  [2] Half way, at elapsed 5.0 s of the 10.0: 5.0 × 3.0 = 15.0 m walked, so
      the position is (15.0, 0.0), ``progress_m`` 15.0 of ``total_m`` 30.0
      and the journey is NOT arrived.

  [3] A goal on ``deep_water`` (impassable) → ``(None, 'unpassable')``, and
      nothing is stored. A character with neither a point nor a placed
      location has nowhere to start from → ``(None, 'no_route')``.

  [4] The ticker (``advance_all_journeys``, the entry ``get_travel_ticker``
      calls in its ``_run`` loop). The game clock is PINNED (factor 0) so
      "elapsed" is exact:
        T0 + 5 s  → an in-flight tick: the position is (15.0, 0.0), the
                    journey is STILL there and ``current_location`` is ''.
                    This is the regression that matters: out in the open
                    ``location_at_point`` answers '' — the very value a point
                    journey carries as its ``target`` — so an unguarded
                    early-arrival check would settle every single tick.
        T0 + 11 s → past the 10.0 s of travel: the arrival is settled, the
                    position is the goal (30.0, 0.0), the journey is gone and
                    ``current_location`` stays '' (the goal lies outside
                    every boundary, so ``location_at_point`` derives nothing).

  [5] Setting off FROM a placed location. HOME at (−40, 0), plan_width_m 10
      (so its footprint spans x −45…−35) with an opening on edge 1 (the east
      side) at 0.5 → the world point (−35, 0). A character standing on HOME's
      anchor walks ``position → own opening → goal``:
        waypoints[0]  = (−40, 0)   its real position
        waypoints[1]  = (−35, 0)   HOME's opening
        waypoints[-1] = (30, 0)    the goal
      The route between the opening and the goal may round HOME's corner on
      the 2 m nav raster, so the polyline is at least — and only at least —
      the straight 5 + 65 = 70 m; what IS exact is the baking rule, so the
      last ``t_cum`` equals that polyline's own length / 3.0 m/s.
      At elapsed 10.0 s the walker has covered 10.0 × 3.0 = 30.0 m of it
      (grass, factor 1.0), i.e. it stands past the opening and short of the
      goal, and ``current_location`` has become ''.
      THIS is the regression the guard in ``advance_all_journeys`` exists
      for: on that tick ``current_location`` is still HOME (the position is
      written after it is read) while ``location_at_point`` out in the open
      answers '' — the very value a point journey carries as its ``target``.
      Unguarded, the tick would settle the "arrival" 40 m early.

  [6] A TELEPORT ends a point journey. ``save_character_current_location``
      aborts a running trip on a manual location change, and it used to ask
      only whether ``movement_target`` was set — which a point journey never
      stamps. Teleporting the walker into HOME therefore has to drop the
      journey dict, and the next tick must leave it in HOME instead of
      pulling it back onto its polyline.

Usage:  ./.venv/bin/python scripts/smoke_journey_point.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="journey-point-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="journey-point-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config  # noqa: E402
config.load(STORAGE / "config.json")
from app.core import db  # noqa: E402
db.init_schema()
from app.core.task_queue import get_task_queue  # noqa: E402
get_task_queue()._started = True

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import (game_time, set_game_factor,  # noqa: E402
                                set_game_time)
from app.models import terrain  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_pos, get_movement_target,
    save_character_current_location, save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0

# The pinned instant every elapsed time below is measured from.
T0 = "Y0001-D010T12:00:00"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def approx(label, actual, expected, tol=1e-6):
    global CHECKED
    CHECKED += 1
    ok = isinstance(actual, (int, float)) and abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected ≈{expected!r} (tol {tol})"))
    if not ok:
        FAILURES.append(label)


def at(seconds):
    """Pin the game clock ``seconds`` GAME seconds after T0."""
    set_game_time(GameTime.parse(T0) + GameDuration.of(seconds=seconds))


def polyline_length(wps):
    return sum(math.dist((wps[i][0], wps[i][1]), (wps[i + 1][0], wps[i + 1][1]))
               for i in range(len(wps) - 1))


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (boundary, openings).

    A ``plan_width_m`` handed in is DRAWN as the centred square of that edge
    — since 2026-08-19 the width alone is no shape at all, so a fixture that
    wants ground has to say so (copied from ``smoke_journey_v2``).
    """
    width = fields.get("plan_width_m")
    if width:
        _h = round(float(width) / 2.0, 2)
        fields.setdefault("boundary", [[-_h, -_h], [_h, -_h],
                                       [_h, _h], [-_h, _h]])
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


# ── the world: one grass rectangle, one lake, no locations at all ───────
# No location is placed anywhere, so `location_at_point` answers '' for every
# point in this world — the wilderness the point journey is built for.
terrain.save_area({"kind": "grass",
                   "polygon": [[-60, -25], [60, -25], [60, 25], [-60, 25]],
                   "z_order": 0})
terrain.save_area({"kind": "deep_water",
                   "polygon": [[70, -10], [90, -10], [90, 10], [70, 10]],
                   "z_order": 0})

# The world speed, pinned so every hand-derived stamp is a whole number.
config._CONFIG.setdefault("game", {})["travel_speed_m_s"] = 3.0

set_game_factor(0.0)
at(0)

save_character_profile("demo_npc", {"current_location": ""}, create_new=True)
set_character_pos("demo_npc", 0.0, 0.0)

# ── [1] the journey ─────────────────────────────────────────────────────
print("[1] start_journey_to_point (0,0) → (30,0) over grass")
journey, reason = travel_engine.start_journey_to_point("demo_npc", 30.0, 0.0)
check("reason", reason, "ok")
check_true("journey created", isinstance(journey, dict), f"{journey}")
if isinstance(journey, dict):
    check("journey keys", sorted(journey),
          sorted(["target", "target_point", "waypoints", "started_at_game",
                  "speed_m_s", "entry_edge"]))
    check("target is empty (a free point has no location id)",
          journey["target"], "")
    check("target_point", journey["target_point"], {"x": 30.0, "z": 0.0})
    check("entry_edge", journey["entry_edge"], None)
    approx("speed_m_s", journey["speed_m_s"], 3.0)
    check("started_at_game is the pinned instant",
          journey["started_at_game"], T0)
    wps = journey["waypoints"]
    check_true("at least two waypoints", len(wps) >= 2, f"{len(wps)}")
    check("first waypoint is the real position",
          [round(wps[0][0], 2), round(wps[0][1], 2), wps[0][2]],
          [0.0, 0.0, 0.0])
    check("last waypoint is the goal", [round(wps[-1][0], 2),
                                        round(wps[-1][1], 2)], [30.0, 0.0])
    approx("the last t_cum is 30 m / 3.0 m/s", wps[-1][2], 10.0, tol=0.01)
check("NO movement_target is stamped", get_movement_target("demo_npc"), "")
check("get_journey returns the point journey",
      travel_engine.get_journey("demo_npc") is not None, True)

# ── [2] journey_state is unchanged for a point journey ──────────────────
print("[2] journey_state half way through")
st = travel_engine.journey_state(journey["waypoints"], journey["started_at_game"],
                                 GameTime.parse(T0) + GameDuration.of(seconds=5))
check("pos at 5 s", (round(st["pos"][0], 2), round(st["pos"][1], 2)),
      (15.0, 0.0))
check("not arrived", st["arrived"], False)
approx("progress_m", st["progress_m"], 15.0, tol=0.01)
approx("total_m", st["total_m"], 30.0, tol=0.01)

# ── [3] the gates ───────────────────────────────────────────────────────
print("[3] an impassable goal and a character with nowhere to start")
save_character_profile("wet_npc", {"current_location": ""}, create_new=True)
set_character_pos("wet_npc", 0.0, 0.0)
check("a goal on deep water",
      travel_engine.start_journey_to_point("wet_npc", 80.0, 0.0),
      (None, "unpassable"))
check("… and nothing is stored", travel_engine.get_journey("wet_npc"), None)
save_character_profile("nowhere_npc", {"current_location": ""}, create_new=True)
check("a character without a point and without a placed location",
      travel_engine.start_journey_to_point("nowhere_npc", 30.0, 0.0),
      (None, "no_route"))

# ── [4] the ticker ──────────────────────────────────────────────────────
print("[4] advance_all_journeys — in flight, then the arrival")
at(5)
travel_engine.advance_all_journeys()
pos = get_character_pos("demo_npc")
check("in-flight position", (pos["x"], pos["z"]), (15.0, 0.0))
check("the journey survives the in-flight tick",
      travel_engine.get_journey("demo_npc") is not None, True)
check("still in the wilderness",
      get_character_current_location("demo_npc"), "")

at(11)
travel_engine.advance_all_journeys()
pos = get_character_pos("demo_npc")
check("arrived at the goal point", (pos["x"], pos["z"]), (30.0, 0.0))
check("journey removed", travel_engine.get_journey("demo_npc"), None)
check("… and gone from the profile too",
      travel_engine.get_journey("demo_npc", profile=None), None)
check("current_location stays empty (outside every boundary)",
      get_character_current_location("demo_npc"), "")
check("movement_target is still empty",
      get_movement_target("demo_npc"), "")
# A second tick must not resurrect anything — the settle is idempotent.
at(20)
travel_engine.advance_all_journeys()
pos = get_character_pos("demo_npc")
check("a later tick leaves the arrived character alone",
      (pos["x"], pos["z"]), (30.0, 0.0))

# ── [5] setting off FROM a location ─────────────────────────────────────
print("[5] a point journey that starts inside a placed location")
HOME = add_location(name="Smoke Home", description="point journey smoke")["id"]
update_location_position(HOME, -40.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": 1, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
save_character_profile("home_npc", {"current_location": ""}, create_new=True)
save_character_current_location("home_npc", HOME)
set_character_pos("home_npc", -40.0, 0.0)
at(0)
journey_h, reason_h = travel_engine.start_journey_to_point("home_npc", 30.0, 0.0)
check("reason", reason_h, "ok")
if isinstance(journey_h, dict):
    wps_h = journey_h["waypoints"]
    check("first waypoint is the character's own position",
          [round(wps_h[0][0], 2), round(wps_h[0][1], 2)], [-40.0, 0.0])
    check("second waypoint is the OWN opening (E mid of HOME)",
          [round(wps_h[1][0], 2), round(wps_h[1][1], 2)], [-35.0, 0.0])
    check("last waypoint is the goal",
          [round(wps_h[-1][0], 2), round(wps_h[-1][1], 2)], [30.0, 0.0])
    length_h = polyline_length(wps_h)
    check_true("the route is at least the straight 5 + 65 m",
               length_h >= 70.0 - 1e-9, f"{length_h:.3f} m")
    approx("the last t_cum is that length / 3.0 m/s", wps_h[-1][2],
           length_h / 3.0, tol=0.01)
at(10)
# 10.0 GAME seconds at 3.0 m/s over factor-1.0 grass = 30.0 m walked — the
# figure is past HOME's opening at (−35, 0) and well short of the goal.
st = travel_engine.journey_state(journey_h["waypoints"],
                                 journey_h["started_at_game"], game_time())
approx("in-flight progress_m", st["progress_m"], 30.0, tol=0.01)
check("not arrived", st["arrived"], False)
travel_engine.advance_all_journeys()
pos = get_character_pos("home_npc")
check("the tick writes the interpolated position",
      (pos["x"], pos["z"]), (round(st["pos"][0], 2), round(st["pos"][1], 2)))
check_true("… which is past HOME's opening and short of the goal",
           -35.0 < pos["x"] < 30.0, f"x={pos['x']}")
check("left HOME behind", get_character_current_location("home_npc"), "")
# THE regression of this task: the tick above read current_location == HOME
# (the write happens after), and out in the open `location_at_point` answers
# '' — the very value a point journey carries as its `target`. Without the
# "only a journey WITH a target place can arrive early" guard in
# `advance_all_journeys`, this tick would have settled the arrival at the
# first step outside the footprint.
check("the journey survives leaving the footprint",
      travel_engine.get_journey("home_npc") is not None, True)
at(30)
travel_engine.advance_all_journeys()
pos = get_character_pos("home_npc")
check("arrived at the goal point", (pos["x"], pos["z"]), (30.0, 0.0))
check("journey removed", travel_engine.get_journey("home_npc"), None)
check("current_location stays empty",
      get_character_current_location("home_npc"), "")

# ── [6] a teleport ends a point journey ─────────────────────────────────
print("[6] a teleport (save_character_current_location) ends the trip")
at(0)
journey_t, reason_t = travel_engine.start_journey_to_point("home_npc", -20.0, 0.0)
check("reason", reason_t, "ok")
save_character_current_location("home_npc", HOME)
# The abort is keyed on the journey DICT, not only on `movement_target` — a
# point journey never stamps one, so the old target-only test would have let
# the journey survive the teleport and the very next tick would have dragged
# the character back onto its polyline.
check("the journey is gone", travel_engine.get_journey("home_npc"), None)
check("teleported into HOME", get_character_current_location("home_npc"), HOME)
at(20)
travel_engine.advance_all_journeys()
check("… and the ticker does not drag it back out",
      get_character_current_location("home_npc"), HOME)

print()
_ = game_time()   # the clock is still readable after all of the above
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
