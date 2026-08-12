#!/usr/bin/env python3
"""Smoke run for Journey v2 + the travel-speed setting
(Seamless World, E3 Task 2).

Runs against a THROWAWAY storage directory — never touches a real world.

Rules every expectation below is derived from BY HAND:

  * A journey on the profile is
    ``{target, waypoints: [[x, z, t_cum], …], started_at_game, speed_m_s}``.
    ``t_cum`` = cumulative GAME seconds since the start, waypoint 0 is 0.0.
  * The OLD format (a journey dict carrying ``path``) is discarded silently
    on read, and ``movement_target`` is cleared with it — no migration.
  * ``journey_state`` is a pure function of the game clock: the position is
    the linear interpolation inside the segment the elapsed time falls in.
  * An opening's world point: the location square has edge
    ``map3d.plan_width_m`` around (``pos_x``, ``pos_z``), turned by
    ``yaw_deg``. In the LOCAL frame (x east, z south before the turn) the
    N edge is z = −w/2, S is z = +w/2, W is x = −w/2, E is x = +w/2, and
    ``at`` runs left→right on N/S and top→bottom on E/W, i.e. the free
    coordinate is ``(at − 0.5)·w``. ``map3d.tile_rotation`` turns the
    stored opening into the location frame first (N→E→S→W, with
    ``at → 1 − at`` on the E/W steps), ``yaw_deg`` then maps local→world
    per § A1.1: ``x = cx + lx·cos(yaw) + lz·sin(yaw)``,
    ``z = cz − lx·sin(yaw) + lz·cos(yaw)``.

Hand-derived expectations:

  [1] ``get_travel_speed_m_s``: unset → 1.4; 3.0 → 3.0; 0.05 → 0.1 and
      50 → 20.0 (clamped); 0, −2, "fast", True, NaN → 1.4 (garbage, and an
      emptied admin field arrives as 0 — silently reading that as "fastest
      legal pace" would re-time every new journey).

  [2] ``journey_state`` with waypoints [[0,0,0], [10,0,10], [10,20,40]]
      (10 m in 10 s, then 20 m in 30 s — factor ⅔):
      total_m = 30.0, eta = start + 40 s.
        t = 0  → (0,0),  seg 0, progress_m 0
        t = 5  → (5,0),  seg 0, progress_m 5   (half of segment 0)
        t = 10 → (10,0), seg 1, progress_m 10  (the joint belongs to seg 1)
        t = 25 → (10,10) — 15 of 30 s into segment 1, so half of its 20 m
                 → progress_m 20
        t = 40 → arrived, (10,20), progress_m 30
        t = 99 → arrived (beyond the end never runs past the last waypoint)
        t = −5 → clamped to the start (a game clock set back must not walk
                 the figure backwards)
      Zero-length / zero-time segments are skipped, not divided by:
      [[0,0,0], [10,0,10], [10,0,10], [10,20,40]] answers exactly like the
      3-waypoint case at t = 10 and t = 25.
      A single waypoint [[7,8,0]] is an arrived journey at (7,8),
      total_m 0.

  [3] Format discard: a profile carrying the OLD journey
      ({target, path, started_at_game, seconds_per_cell}) plus a matching
      ``movement_target`` → ``get_journey`` is None, ``movement_target``
      is empty afterwards and the journey dict is gone from the profile.

  [4] ``opening_world_point`` at a location (50, 50), plan_width_m 10:
        yaw 0,  N at 0.5 → local (0, −5)     → (50.0, 45.0)
        yaw 0,  N at 0.2 → local (−3, −5)    → (47.0, 45.0)
        yaw 0,  E at 0.5 → local (5, 0)      → (55.0, 50.0)
        yaw 0,  S at 0.5 → local (0, 5)      → (50.0, 55.0)
        yaw 90, N at 0.5 → x = 50 + 0·cos90 + (−5)·sin90 = 45,
                           z = 50 − 0·sin90 + (−5)·cos90 = 50 → (45.0, 50.0)
        yaw 180, N at 0.5 → (50.0, 55.0)
        tile_rotation 90 turns a stored N at 0.2 into E at 0.2
        (no flip on the N step) → local (5, −3) → (55.0, 47.0), and the
        location then has NO opening on N any more.
        An edge without an opening → None; an unplaced location → None;
        a location without a scale anchor → None.

  [5] Gates of ``start_journey`` (character "demo_npc" at HOME):
        unknown id                        → (None, 'unknown_target')
        placed, but not in known_locations→ (None, 'unknown_target')
        known, but unplaced               → (None, 'unplaced_target')
        known + placed + walkable         → journey, reason ''
        known + placed, drowned in a lake → (None, 'no_route')
      The last one is asked from wild_npc at (40,40) — a character standing
      IN the target would be answered by the same-target early return and
      would never reach the router at all.

  [6] The journey itself. HOME at (0,0) w 10 (opening S at 0.5 → (0,5)),
      MARKET at (100,0) w 10 (opening W at 0.5 → (95,0)), all grass,
      speed 1.4 m/s:
        waypoints[0] = [0, 0, 0.0]        (the character's real position)
        waypoints[1] = [0, 5, …]          (leaves through its OWN opening)
        waypoints[-1] = [95, 0, …]        (the target's opening point)
        every t_cum is non-decreasing, the last equals
        (polyline length) / 1.4 within 0.05 s (grass = factor 1.0, so the
        cost is pure length), and journey_state at the start stamp reports
        the start point with progress_m 0.
      ``movement_target`` is the target, the entry-room pre-set is GONE
      (the character stays in the room it was in) and the stored dict has
      exactly the five v2 keys — the fifth is ``entry_edge``, the WORLD edge
      of the opening the route aims at ("W" here), which the ARRIVAL needs to
      pick the room that opening links to (E3 Task 3).
      A character standing in the WILDERNESS (no location) starts at its
      own position — its first waypoint is that point, and no opening of
      any location is inserted.

  [7] The ticker: a journey whose start stamp lies an hour in the past is
      finished, so ``advance_all_journeys`` settles the arrival — the
      character stands in MARKET, movement_target and journey are gone.
      (The in-flight position write is Task 3's; this only pins that an
      arrival never hangs.)

Usage:  ./.venv/bin/python scripts/smoke_journey_v2.py
"""
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="journey-v2-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="journey-v2-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import config, travel_engine  # noqa: E402
from app.core.boundary_entry import opening_world_point  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.timeutils import game_now, parse_iso  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_profile, get_movement_target,
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models import terrain  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0

START_ISO = "2026-08-09T12:00:00+00:00"
START_DT = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


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


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (scale anchor, openings)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def state_at(waypoints, seconds):
    return travel_engine.journey_state(waypoints, START_ISO,
                                       START_DT + timedelta(seconds=seconds))


def loc_dict(cx, cz, width, yaw=0.0, openings=None, tile_rotation=0):
    """A minimal location dict — opening_world_point is a PURE function."""
    map3d = {"plan_width_m": width}
    if openings is not None:
        map3d["boundary_openings"] = openings
    if tile_rotation:
        map3d["tile_rotation"] = tile_rotation
    return {"id": "lit", "pos_x": cx, "pos_z": cz, "yaw_deg": yaw,
            "map3d": map3d}


def polyline_length(wps):
    return sum(math.dist((wps[i][0], wps[i][1]), (wps[i + 1][0], wps[i + 1][1]))
               for i in range(len(wps) - 1))


def rounded(point, nd=2):
    return (round(point[0], nd), round(point[1], nd))


# ── [1] the travel-speed setting ────────────────────────────────────────
print("[1] game.travel_speed_m_s: default, clamps, garbage")
config._CONFIG.setdefault("game", {}).pop("travel_speed_m_s", None)
approx("unset → default", travel_engine.get_travel_speed_m_s(), 1.4)
for raw, expected in ((3.0, 3.0), (0.05, 0.1), (50, 20.0), (0, 1.4),
                      (-2, 1.4), ("fast", 1.4), (True, 1.4),
                      (float("nan"), 1.4), (None, 1.4)):
    config._CONFIG["game"]["travel_speed_m_s"] = raw
    approx(f"{raw!r} → {expected}", travel_engine.get_travel_speed_m_s(),
           expected)
config._CONFIG["game"].pop("travel_speed_m_s", None)
check("the old key is gone from the schema",
      "travel_seconds_per_cell" in SECTIONS["game"]["fields"], False)
check("the new key is in the schema",
      "travel_speed_m_s" in SECTIONS["game"]["fields"], True)

# ── [2] journey_state ───────────────────────────────────────────────────
print("[2] journey_state — pure interpolation over cumulative game seconds")
WPS = [[0, 0, 0], [10, 0, 10], [10, 20, 40]]
st = state_at(WPS, 0)
check("t=0 pos", rounded(st["pos"]), (0.0, 0.0))
check("t=0 arrived", st["arrived"], False)
approx("t=0 progress_m", st["progress_m"], 0.0)
approx("total_m", st["total_m"], 30.0)
check("eta_game", st["eta_game"], (START_DT + timedelta(seconds=40)).isoformat())
st = state_at(WPS, 5)
check("t=5 pos", rounded(st["pos"]), (5.0, 0.0))
check("t=5 seg", st["seg"], 0)
approx("t=5 progress_m", st["progress_m"], 5.0)
st = state_at(WPS, 10)
check("t=10 pos", rounded(st["pos"]), (10.0, 0.0))
check("t=10 seg (the joint belongs to the next segment)", st["seg"], 1)
approx("t=10 progress_m", st["progress_m"], 10.0)
st = state_at(WPS, 25)
check("t=25 pos", rounded(st["pos"]), (10.0, 10.0))
check("t=25 seg", st["seg"], 1)
approx("t=25 progress_m", st["progress_m"], 20.0)
st = state_at(WPS, 40)
check("t=40 arrived", st["arrived"], True)
check("t=40 pos", rounded(st["pos"]), (10.0, 20.0))
approx("t=40 progress_m", st["progress_m"], 30.0)
st = state_at(WPS, 99)
check("t=99 stays at the last waypoint", rounded(st["pos"]), (10.0, 20.0))
check("t=99 arrived", st["arrived"], True)
st = state_at(WPS, -5)
check("a clock set back clamps to the start", rounded(st["pos"]), (0.0, 0.0))
check("… and is not arrived", st["arrived"], False)

ZERO = [[0, 0, 0], [10, 0, 10], [10, 0, 10], [10, 20, 40]]
check("zero-length segment: t=10 pos", rounded(state_at(ZERO, 10)["pos"]),
      (10.0, 0.0))
check("zero-length segment: t=25 pos", rounded(state_at(ZERO, 25)["pos"]),
      (10.0, 10.0))
approx("zero-length segment: total_m", state_at(ZERO, 0)["total_m"], 30.0)

ONE = [[7, 8, 0]]
st = state_at(ONE, 0)
check("single waypoint is an arrived journey", st["arrived"], True)
check("single waypoint pos", rounded(st["pos"]), (7.0, 8.0))
approx("single waypoint total_m", st["total_m"], 0.0)

# ── [3] the old format is discarded ─────────────────────────────────────
print("[3] an old journey (path key) is dropped on read, target cleared")
save_character_profile("legacy_npc", {"current_location": ""}, create_new=True)
prof = get_character_profile("legacy_npc")
prof["movement_target"] = "loc_old"
prof["journey"] = {"target": "loc_old", "path": ["loc_a", "loc_old"],
                   "started_at_game": START_ISO, "seconds_per_cell": 60.0}
save_character_profile("legacy_npc", prof)
check("old journey is not returned",
      travel_engine.get_journey("legacy_npc"), None)
check("movement_target cleared", get_movement_target("legacy_npc"), "")
check("journey dict removed from the profile",
      "journey" in get_character_profile("legacy_npc"), False)

# ── [4] opening world points ────────────────────────────────────────────
print("[4] opening_world_point — hand-derived")
N_MID = [{"edge": "N", "at": 0.5, "width_m": 4.0}]
check("yaw 0, N mid", opening_world_point(loc_dict(50, 50, 10, 0, N_MID), "N"),
      (50.0, 45.0))
check("yaw 0, N at 0.2",
      opening_world_point(loc_dict(50, 50, 10, 0,
                                   [{"edge": "N", "at": 0.2}]), "N"),
      (47.0, 45.0))
check("yaw 0, E mid",
      opening_world_point(loc_dict(50, 50, 10, 0,
                                   [{"edge": "E", "at": 0.5}]), "E"),
      (55.0, 50.0))
check("yaw 0, S mid",
      opening_world_point(loc_dict(50, 50, 10, 0,
                                   [{"edge": "S", "at": 0.5}]), "S"),
      (50.0, 55.0))
check("yaw 90, N mid", opening_world_point(loc_dict(50, 50, 10, 90, N_MID),
                                           "N"), (45.0, 50.0))
check("yaw 180, N mid", opening_world_point(loc_dict(50, 50, 10, 180, N_MID),
                                            "N"), (50.0, 55.0))
rot = loc_dict(50, 50, 10, 0, [{"edge": "N", "at": 0.2}], tile_rotation=90)
check("tile_rotation 90: stored N at 0.2 becomes E at 0.2",
      opening_world_point(rot, "E"), (55.0, 47.0))
check("… and N carries no opening any more",
      opening_world_point(rot, "N"), None)
check("an edge without an opening",
      opening_world_point(loc_dict(50, 50, 10, 0, N_MID), "S"), None)
check("an unplaced location",
      opening_world_point({"map3d": {"plan_width_m": 10,
                                     "boundary_openings": N_MID}}, "N"), None)
check("a location without a scale anchor",
      opening_world_point({"pos_x": 50, "pos_z": 50,
                           "map3d": {"boundary_openings": N_MID}}, "N"), None)

# ── seed for [5]/[6] ────────────────────────────────────────────────────
HOME = add_location(name="Smoke Home", description="journey v2 smoke")["id"]
update_location_position(HOME, 0.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": "S", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
MARKET = add_location(name="Smoke Market", description="journey v2 smoke")["id"]
update_location_position(MARKET, 100.0, 0.0)
set_map3d(MARKET, plan_width_m=10.0,
          boundary_openings=[{"edge": "W", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
SECRET = add_location(name="Smoke Secret", description="unknown to the npc")["id"]
update_location_position(SECRET, 0.0, 100.0)
set_map3d(SECRET, plan_width_m=10.0)
GHOST = add_location(name="Smoke Ghost", description="never placed")["id"]

save_character_profile("demo_npc", {"current_location": ""}, create_new=True)
save_character_current_location("demo_npc", HOME)
set_character_pos("demo_npc", 0.0, 0.0)
set_known_locations("demo_npc", [HOME, MARKET, GHOST])

# ── [5] gates ───────────────────────────────────────────────────────────
print("[5] start_journey gates")
check("unknown id", travel_engine.start_journey("demo_npc", "loc_nope"),
      (None, "unknown_target"))
check("placed but not known",
      travel_engine.start_journey("demo_npc", SECRET),
      (None, "unknown_target"))
check("known but unplaced", travel_engine.start_journey("demo_npc", GHOST),
      (None, "unplaced_target"))

# ── [6] the journey ─────────────────────────────────────────────────────
print("[6] a real journey HOME → MARKET")
room_before = get_character_current_room("demo_npc")
journey, reason = travel_engine.start_journey("demo_npc", MARKET)
check("reason", reason, "")
check_true("journey created", isinstance(journey, dict), f"{journey}")
if isinstance(journey, dict):
    check("journey keys", sorted(journey),
          sorted(["target", "waypoints", "started_at_game", "speed_m_s",
                  "entry_edge"]))
    check("target", journey["target"], MARKET)
    check("entry_edge is the aimed-at opening (MARKET's W gate)",
          journey["entry_edge"], "W")
    approx("speed_m_s", journey["speed_m_s"], 1.4)
    wps = journey["waypoints"]
    check("first waypoint is the real position",
          [round(wps[0][0], 2), round(wps[0][1], 2), wps[0][2]], [0.0, 0.0, 0.0])
    check("second waypoint is the OWN opening (S mid of HOME)",
          rounded(wps[1]), (0.0, 5.0))
    check("last waypoint is the target's opening (W mid of MARKET)",
          rounded(wps[-1]), (95.0, 0.0))
    ts = [w[2] for w in wps]
    check_true("t_cum is non-decreasing", all(ts[i] <= ts[i + 1]
                                              for i in range(len(ts) - 1)),
               f"{ts}")
    approx("the last t_cum is the polyline length / 1.4",
           ts[-1], polyline_length(wps) / 1.4, tol=0.05)
    st = travel_engine.journey_state(wps, journey["started_at_game"],
                                     parse_iso(journey["started_at_game"]))
    check("state at the start stamp is the start point", rounded(st["pos"]),
          (0.0, 0.0))
    approx("progress_m at the start", st["progress_m"], 0.0)
    approx("total_m equals the polyline length", st["total_m"],
           polyline_length(wps), tol=0.01)
check("movement_target", get_movement_target("demo_npc"), MARKET)
check("the journey survives get_journey",
      travel_engine.get_journey("demo_npc") is not None, True)
check("no entry-room pre-set (the room is untouched)",
      get_character_current_room("demo_npc"), room_before)

print("[6b] a wilderness character starts at its own point")
save_character_profile("wild_npc", {"current_location": ""}, create_new=True)
set_character_pos("wild_npc", 40.0, 40.0)
set_known_locations("wild_npc", [MARKET])
journey_w, reason_w = travel_engine.start_journey("wild_npc", MARKET)
check("wilderness reason", reason_w, "")
if isinstance(journey_w, dict):
    check("wilderness first waypoint", rounded(journey_w["waypoints"][0]),
          (40.0, 40.0))
    check("wilderness last waypoint", rounded(journey_w["waypoints"][-1]),
          (95.0, 0.0))

print("[6c] cancel_journey clears journey and target")
travel_engine.cancel_journey("wild_npc")
check("journey gone", travel_engine.get_journey("wild_npc"), None)
check("target gone", get_movement_target("wild_npc"), "")

# ── [7] the ticker still settles arrivals ───────────────────────────────
print("[7] a finished journey is settled by the ticker (Task 3 rebuilds it)")
prof = get_character_profile("demo_npc")
# Back-date the start so the whole route lies in the past — the position is
# a pure function of the game clock, so this IS "the journey has finished".
prof["journey"] = dict(prof["journey"],
                       started_at_game=(game_now() - timedelta(hours=1)
                                        ).isoformat())
save_character_profile("demo_npc", prof)
travel_engine.advance_all_journeys()
check("arrived at the target", get_character_current_location("demo_npc"),
      MARKET)
check("movement_target cleared on arrival",
      get_movement_target("demo_npc"), "")
check("journey gone on arrival", travel_engine.get_journey("demo_npc"), None)

# ── [5b] the drowned target ─────────────────────────────────────────────
print("[5b] a target surrounded by water is unreachable")
# wild_npc stands at (40,40) in the wilderness — NOT in MARKET, so the
# same-target early return cannot answer for the router. Its journey was
# cancelled in [6c], and its route to MARKET was walkable a moment ago
# ([6b]) — the water ring below is the ONLY new fact.
check("the route was walkable before the water",
      travel_engine.get_journey("wild_npc"), None)
terrain.save_area({"kind": "water",
                   "polygon": [[85, -20], [125, -20], [125, 20], [85, 20]],
                   "z_order": 0})
check("no_route", travel_engine.start_journey("wild_npc", MARKET),
      (None, "no_route"))
check("a failed start leaves no target behind",
      get_movement_target("wild_npc"), "")
check("… and stores no journey", travel_engine.get_journey("wild_npc"), None)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
