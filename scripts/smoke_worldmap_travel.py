#!/usr/bin/env python3
"""Smoke run for the v2 travel block in the worldmap payload (E3, Task 6).
Checks that route JSON is encoded in the endpoint, off the event loop.

Checks the ``travel`` block of ``world_ops.build_worldmap_payload`` against
docs/schnittstellen-3d.md § A11 (metre polyline): the block carries
``{target_id, waypoints, progress_m, total_m, eta_game, eta_hhmm, eta_label,
starts_in_s, speed_m_s_real, pace_m_s_real}`` and NOTHING else — every cell field of v1 (``path``/``seg``/
``frac``/``progress_cells``/``cell_seconds_real``) is gone without
replacement.

MOVEMENT RUNS IN REAL TIME (user decision 2026-11-05,
plan-bewegung-echtzeit.md): a journey is timed on the MOTION clock
(``timeutils.motion_time`` — real seconds the world has run unfrozen), its
``started_at_s`` and baked ``t_cum`` are real seconds, and the game clock's
factor no longer scales any pace. Only the calendar arrival (``eta_game``) is
a projection at the configured factor (``travel_engine.journey_eta``).

``starts_in_s`` joined the block with the DEPARTURE BRIDGE (transition clips,
``travel_engine.departure_bridge``): a journey whose ``started_at_s`` lies
ahead of the motion clock has not begun, and this is the real-seconds
countdown until it does. It is the one number fog does NOT withhold — see [6].

Runs against a THROWAWAY storage directory — it never touches a real world.
The SYSTEM clock is pinned (``timeutils.utc_now`` replaced by a hand-moved
one), so the running-world numbers below are exact, not tolerances.
The journey is written onto the profile BY HAND, so no expectation below
depends on the pathfinder: this is a payload check, not a routing check
(routing is scripts/smoke_journey_v2.py).

The seed:

    location A "Alder Camp"   (0, 0)     10 m footprint  <- known to the avatar
    location B "Birch Hollow" (30, 40)   10 m footprint  <- UNKNOWN, the target

    demo_avatar  in A, known_locations = [A], journey -> B
    npc_walker   in B, journey -> B (same polyline; it is the FOG probe)
    npc_near     in A, journey -> B (VISIBLE under fog — it stands in the
                 known A, so it probes what a fogged payload tells about
                 SOMEONE ELSE's journey)
    npc_idle     in A, movement_target = B but NO journey dict
    npc_slow     in A, journey -> B on the SLOW polyline (see below) — the
                 probe that tells `speed_m_s_real` (nominal) and
                 `pace_m_s_real` (this segment) apart

    server.timezone = Europe/Berlin  (the DISPLAY timezone of system stamps;
                                      the game clock has none, so it must not
                                      shift the arrival stamp by one minute)

The hand-built journey (identical for the fast travellers):

    waypoints = [[0, 0, 0.0], [30, 0, 30.0], [30, 40, 70.0]]
    speed_m_s = 1.0        started_at_s = motion now − elapsed

``stage(elapsed, frozen, factor)`` puts every traveller ``elapsed`` REAL
seconds into its walk and stands the game CALENDAR at
Y0001-D001T12:00:00 + ``elapsed`` game seconds with the given factor — the
calendar is placed independently of the walk (they no longer share a clock).

    leg 1: (0,0) -> (30,0)   = 30 m, baked at t_cum 30 s
    leg 2: (30,0) -> (30,40) = 40 m, baked at t_cum 70 s
    total                    = 70 m over 70 REAL seconds

The SLOW polyline (npc_slow) — same points, same nominal ``speed_m_s`` 1.0,
but leg 2 runs over soft ground and was baked at HALF the pace (that is what
the terrain ``speed_factor`` does to ``t_cum``, § A1.5):

    waypoints = [[0, 0, 0.0], [30, 0, 30.0], [30, 40, 110.0]]

    leg 1: 30 m in 30 real s  -> 1.0 m per REAL second
    leg 2: 40 m in 80 real s  -> 0.5 m per REAL second

Hand-derived expectations:

  [1] frozen world, every traveller 35 real s into its walk, calendar at
      12:00:35, factor 1
      elapsed 35 s falls into leg 2 (t0 30, t1 70, span 40):
        frac       = (35 − 30) / 40           = 0.125
        progress_m = 30 + 40 × 0.125          = 35.0
        total_m    = 30 + 40                  = 70.0
        remaining  = 70 − 35                  = 35 real s
        eta_game   = 12:00:35 + 35 × factor 1 = Y0001-D001T12:01:10
                     — canonical, and unmoved by server.timezone; frozen,
                     the projection keeps the CONFIGURED factor
        eta_hhmm   = "12:01"   (rendered server-side; no client slices a
                     stamp any more, § A11)
        eta_label  = "Spring, day 1 · 12:01 · Year 1" — the default calendar
                     (4 seasons × 30 days, year_label "Year {n}") applied to
                     day 1 of year 1
        waypoints  = [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]]  — x/z ONLY,
                     the baked t_cum stays server-internal
        speed_m_s_real = null — the motion clock stands (rate 0), so nothing
                     may be extrapolated
        pace_m_s_real  = null — same reason, same clock

  [2] running world, 35 real s in, at factor 2.0 AND factor 0.5
        speed_m_s_real = 1.0 at BOTH — the walk is real time, the factor
                     scales nothing (the game-clock model said 2.0 / 0.5)
        progress_m     = 35.0 at both (exact: the system clock is pinned)
        pace_m_s_real  = 1.0 at both (this leg IS the nominal one)
        eta_game at factor 2: 12:00:35 + 35 × 2 = 12:01:45 — the calendar
                     runs faster, so the walker arrives at a LATER calendar
                     time; the walker itself did not move. (Factor 0.5 gives
                     35 + 17.5 = 52.5 s — a half second, not checked.)

  [2b] the SEGMENT pace (E4) — ``pace_m_s_real`` is the pace of the segment
      the figure is walking RIGHT NOW, straight out of the baked stamps:
        |w[seg+1] − w[seg]| / (t[seg+1] − t[seg])      (real seconds)
      On the fast polyline every segment runs at the nominal 1.0 m/s,
      so both fields agree — that proves nothing. npc_slow does:
        35 real s in  -> elapsed 35 falls into leg 2 (t0 30, t1 110, span 80)
        frac       = (35 − 30) / 80          = 0.0625
        progress_m = 30 + 40 × 0.0625        = 32.5
        pace       = 40 m / 80 s             = 0.5 m/s
        at factor 2.0 -> pace_m_s_real  = 0.5   (no factor)
                         speed_m_s_real = 1.0   (nominal, no factor)
      Its FIRST leg is the nominal one: 10 real s in, the two agree again
      (pace 30 m / 30 s = 1.0 m/s).

  [2c] ``pace_m_s_real`` is null wherever an extrapolation would be a lie:
      frozen clock (see [1]) and after the arrival — a journey walked past
      its end has no current segment. ``speed_m_s_real`` stays filled there
      (it is the journey's nominal pace, not a statement about a segment):
      200 real s in, running, factor 1 -> pace null, speed 1.0.

  [3] a movement target alone is NOT a journey
        npc_idle carries movement_target = B but no journey dict
          -> travel is null, movement_target_id is still B

  [4] a journey walked past its end (200 real s in, still frozen, calendar
      at 12:03:20)
        progress_m = total_m = 70.0, and the block stays until the ticker
        settles the arrival ("field gone" is the arrival signal, § A11)
        remaining 0 -> eta_game = the calendar itself = Y0001-D001T12:03:20

  [5] fog (§ A12) holds for travellers too
        fogged view : npc_walker stands in the unknown B -> gone entirely,
                      travelling or not; the avatar sees its OWN block
        the avatar's movement_target_name stays "" (B is unknown) while
        travel.target_id names the id — exactly like movement_target_id,
        which fog never hid either
        admin view  : npc_walker is back, with the same travel block

  [6] fog does not hand out the ROUTE of SOMEONE ELSE — nor the numbers it
      could be reconstructed from (E6)
        The polyline ends at the target's opening — metre-exact map markers
        for a place the avatar may not know (a far worse leak than the
        opaque target_id, which fog never hid either). The walked distance,
        the total length, the arrival time and the two paces say the same
        thing indirectly: position + remaining distance + heading is a
        target. So in a FOGGED payload a foreign traveller keeps its ROW and
        its ``target_id``, and everything else in the block is null:
          fogged, npc_near (visible, travelling) -> waypoints, progress_m,
                    total_m, eta_game, eta_hhmm, eta_label, speed_m_s_real,
                    pace_m_s_real, paces_m_s_real ALL null; target_id still B; the keys all stay (so "not
                    told" stays distinguishable from "empty")
        ``starts_in_s`` is deliberately NOT among them (§ A11): it is a
        countdown to a DEPARTURE, not route knowledge — it says nothing about
        where the figure is heading, and a client needs it to hold a figure
        still that is not walking yet. In this fixture every journey has
        already begun, so it is null on both sides anyway.
          fogged, demo_avatar (itself)           -> the full block
          show_all, npc_near                     -> the full block

  [7] through the /play/worldmap route, the avatar on the SLOW polyline:
        paces_m_s_real = [30/30, 40/80] = [1.0, 0.5] at factor 1, 2 and 0
        (factor 0 stops the calendar, not the walk — only the freeze does);
        null while frozen and for a foreign row under fog; kept after the
        arrival (100 real s in).
        started at S, +10.3 real s at factor 2 -> progress 10.3 m (the
        game-clock model said 20.6).
        started 5 real s AHEAD of the clock, +0.1 real s -> pending 4.9 ->
        starts_in_s 4.9 at factor 1 AND factor 2, progress 0.0, paces null.
        started 0.5 s ahead, +0.3 -> starts_in_s 0.2 and the exit clip
        ("standup") still plays as activity_animation.
        a 0.6 m lead at zero time and a zero-length segment each give a null
        entry: [None, 30/30] = [None, 1.0].
        Identity is 32 hex characters for the avatar and null for every
        foreign row. Both monotonic ages are nonnegative, with builder
        build_ms initially zero.
  [8] at 1 m/s, thinning 0,10,10.01,20 leaves 0,10,20 with times 0,10,20;
      15 real s in gives 15 m. Goal 10.015 replaces 10, so duration is
      10.015 s. 0 -> 0.001 collapses to the goal at t0, already arrived; the
      separate seat leg still survives. For 10000 seeded pairs 2-5 cm apart,
      one axis differs by at least 2/sqrt(2) = 1.414 cm > 1 cm: rounding
      cannot merge a pair.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_travel.py
"""
import json
from datetime import datetime, timedelta, timezone
from starlette.responses import JSONResponse
import os
import math
import random
import re
from unittest.mock import patch
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-travel-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="worldmap-travel-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import config, travel_engine, nav_grid, timeutils  # noqa: E402

# Pin the SYSTEM clock: the motion clock and the game clock both read
# `timeutils.utc_now`, so every running-world number below is exact.
R0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
_now = [R0]
timeutils.utc_now = lambda: _now[0]
timeutils.invalidate_game_clock_cache()


def advance(seconds: float) -> None:
    """Move the pinned system clock forward by ``seconds`` real seconds."""
    _now[0] = _now[0] + timedelta(seconds=seconds)
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_profile, save_character_profile, set_known_locations,
    set_movement_target)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, set_world_frozen,
    update_location_position)

FAILURES = []
CHECKED = 0

START = "Y0001-D001T12:00:00"
START_GT = GameTime.parse(START)
ETA = "Y0001-D001T12:01:10"
ETA_FACTOR2 = "Y0001-D001T12:01:45"
ETA_ARRIVED = "Y0001-D001T12:03:20"
ETA_LABEL = "Spring, day 1 · 12:01 · Year 1"
WAYPOINTS = [[0.0, 0.0, 0.0], [30.0, 0.0, 30.0], [30.0, 40.0, 70.0]]
# Same points, same nominal speed — leg 2 baked at half the pace (soft ground).
SLOW_WAYPOINTS = [[0.0, 0.0, 0.0], [30.0, 0.0, 30.0], [30.0, 40.0, 110.0]]
SPEED = 1.0
# Exactly the fields § A11 lists — no more, no less.
FIELDS = {"target_id", "waypoints", "progress_m", "total_m", "eta_game",
          "eta_hhmm", "eta_label", "starts_in_s", "speed_m_s_real",
          "pace_m_s_real", "paces_m_s_real", "journey_id", "floor_y", "gait"}
# Route details withheld from foreign travellers; the departure countdown stays.
THIN_NUMBERS = ("progress_m", "total_m", "eta_game", "eta_hhmm", "eta_label",
                "speed_m_s_real", "pace_m_s_real", "paces_m_s_real", "floor_y")
# The v1 cell vocabulary, dropped without replacement.
V1_FIELDS = ("path", "seg", "frac", "progress_cells", "cell_seconds_real")


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def route_json(result):
    check("JSONResponse encoded in the endpoint, off the event loop",
          isinstance(result, JSONResponse), True)
    return json.loads(result.body)


def place(name: str, x: float, z: float) -> str:
    """A location placed at a world-METRE point with a 10 m footprint edge."""
    loc = add_location(name=name, description=f"{name} for the travel smoke.")
    loc_id = loc["id"]
    update_location_position(loc_id, x, z)
    data = _load_world_data()
    for entry in data.get("locations", []):
        if entry.get("id") == loc_id:
            entry["map3d"] = {**(entry.get("map3d") or {}),
                              "plan_width_m": 10.0}
    _save_world_data(data)
    return loc_id


def seed_character(name: str, location_id: str) -> None:
    save_character_profile(name, {"current_location": location_id},
                           create_new=True)


def give_journey(name: str, target: str, waypoints=None,
                 started_at_s: float | None = None) -> None:
    """Write journey + movement target in ONE profile save — the two live and
    die together, and a mismatch would make ``get_journey`` call it stale.
    ``started_at_s`` is a MOTION-clock stamp (default: the clock's now)."""
    from app.core.keyed_lock import keyed_lock
    if started_at_s is None:
        started_at_s = timeutils.motion_time()
    with keyed_lock("character_profile", name):
        prof = get_character_profile(name)
        prof["journey"] = {"target": target,
                           "waypoints": [list(w) for w in (waypoints or WAYPOINTS)],
                           "started_at_s": float(started_at_s), "speed_m_s": SPEED,
                           "entry_edge": "", "journey_id": "a" * 32}
        prof["movement_target"] = target
        save_character_profile(name, prof)


# Every traveller and its polyline — `stage` re-stamps them all.
TRAVELLERS = (("demo_avatar", WAYPOINTS), ("npc_walker", WAYPOINTS),
              ("npc_near", WAYPOINTS), ("npc_slow", SLOW_WAYPOINTS))


def stage(elapsed: float, *, frozen: bool, factor: float = 1.0) -> None:
    """Every traveller ``elapsed`` REAL seconds into its walk; the calendar at
    START + ``elapsed`` game seconds with ``factor``. Freeze FIRST: the freeze
    hook re-anchors both clocks, so what is set afterwards is what stays."""
    set_world_frozen(frozen)
    set_game_factor(factor)
    set_game_time(START_GT + GameDuration.of(seconds=elapsed))
    began = timeutils.motion_time() - elapsed
    for name, wps in TRAVELLERS:
        give_journey(name, B, wps, started_at_s=began)


def freeze_at(seconds: float) -> None:
    """Frozen world, every traveller ``seconds`` real seconds in, factor 1."""
    stage(seconds, frozen=True)


def char(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


def names(payload) -> list:
    return sorted(c["name"] for c in payload["characters"])


# The DISPLAY timezone of SYSTEM stamps is deliberately not UTC here: the
# game clock has no timezone, so this must not move the arrival stamp.
config._CONFIG.setdefault("server", {})["timezone"] = "Europe/Berlin"

A = place("Alder Camp", 0.0, 0.0)
B = place("Birch Hollow", 30.0, 40.0)

seed_character("demo_avatar", A)
seed_character("npc_walker", B)
seed_character("npc_near", A)
seed_character("npc_idle", A)
seed_character("npc_slow", A)
set_known_locations("demo_avatar", [A])
give_journey("demo_avatar", B)
give_journey("npc_walker", B)
give_journey("npc_near", B)
give_journey("npc_slow", B, waypoints=SLOW_WAYPOINTS)
set_movement_target("npc_idle", B)


def contract_checks():
    """Hand-derived cases are listed in the module docstring."""
    print("\n[7] exact instant, per-segment paces, identity and payload ages")
    from app.routes.play import play_worldmap
    from app.models.account import set_active_character

    set_active_character("demo_avatar")
    freeze_at(35)
    give_journey("demo_avatar", B, SLOW_WAYPOINTS,
                 started_at_s=timeutils.motion_time() - 35)
    frozen = route_json(play_worldmap(user={"role": "admin"}, show_all=1))
    check("route sync keys", sorted(frozen["sync"]), ["build_ms", "clock_age_ms"])
    check("route sync nonnegative", all(isinstance(v, (int, float)) and v >= 0
          for v in frozen["sync"].values()), True)
    check("builder has complete sync", build_worldmap_payload()["sync"]["build_ms"], 0.0)
    check("frozen paces null", char(frozen, "demo_avatar")["travel"]["paces_m_s_real"], None)
    check("own ID is 32 hex", bool(re.fullmatch(r"[0-9a-f]{32}",
          char(frozen, "demo_avatar")["travel"]["journey_id"] or "")), True)
    check("foreign ID is null even show_all", char(frozen, "npc_near")["travel"]["journey_id"], None)

    def own_at(ahead, delta, factor=1.0, waypoints=SLOW_WAYPOINTS, exit_clip=None):
        """The avatar's row: a journey starting ``ahead`` real s after the
        motion clock's now, read ``delta`` real s later at ``factor``."""
        set_world_frozen(False)
        set_game_factor(factor)
        give_journey("demo_avatar", B, waypoints,
                     started_at_s=timeutils.motion_time() + ahead)
        if exit_clip:
            from app.core.keyed_lock import keyed_lock
            with keyed_lock("character_profile", "demo_avatar"):
                prof = get_character_profile("demo_avatar")
                prof["journey"]["exit_clip"] = exit_clip
                save_character_profile("demo_avatar", prof)
        advance(delta)
        return char(route_json(play_worldmap(user={"role": "admin"}, show_all=1)),
                    "demo_avatar")

    for factor in (1.0, 2.0, 0.0):
        check(f"paces at factor {factor} = [30/30, 40/80]",
              own_at(0, 1, factor)["travel"]["paces_m_s_real"], [1.0, 0.5])
    check("real +10.3 s at factor 2 walks 10.3 m (not 20.6)",
          own_at(0, 10.3, 2.0)["travel"]["progress_m"], 10.3)
    check("paces after arrival", own_at(0, 100)["travel"]["paces_m_s_real"], [1.0, 0.5])
    for factor in (1.0, 2.0):
        pending = own_at(5, 0.1, factor)["travel"]
        check(f"factor {factor}: starts_in_s = 5 − 0.1", pending["starts_in_s"], 4.9)
        check(f"factor {factor}: pending paces null", pending["paces_m_s_real"], None)
        check(f"factor {factor}: not started, progress 0", pending["progress_m"], 0.0)
    boundary = own_at(0.5, 0.3, exit_clip="standup")
    check("still pending by 0.2 real s", boundary["travel"]["starts_in_s"], 0.2)
    check("pending start keeps the departure clip", boundary["activity_animation"], "standup")
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("foreign fog paces", char(fog, "npc_near")["travel"]["paces_m_s_real"], None)
    check("zero-time lead",
          own_at(0, 1, waypoints=[[-0.6, 0, 0], [0, 0, 0], [30, 0, 30]])["travel"]["paces_m_s_real"],
          [None, 1.0])
    check("zero-length segment",
          own_at(0, 1, waypoints=[[0, 0, 0], [0, 0, 1], [30, 0, 31]])["travel"]["paces_m_s_real"],
          [None, 1.0])

    print("\n[8] thinning precedes costs and retains the goal")
    def bake(points):
        with patch.object(nav_grid, "build_nav_context", return_value=None), \
             patch.object(nav_grid, "route", return_value=points), \
             patch.object(nav_grid, "segment_costs", side_effect=lambda pts, ctx:
                          [math.dist(a, b) for a, b in zip(pts, pts[1:])]), \
             patch.object(travel_engine, "get_travel_speed_m_s", return_value=1.0):
            return travel_engine._bake_route(points[0], points[-1], None)[0]

    wps = bake([(0, 0), (10, 0), (10.01, 0), (20, 0)])
    check("thin before costing", wps, [[0, 0, 0], [10, 0, 10], [20, 0, 20]])
    check("thinned paces", travel_engine.segment_paces_m_s_real(wps, 1), [1.0, 1.0])
    check("same time axis at t15", travel_engine.journey_state(wps, 0.0, 15.0)["progress_m"],
          15.0)
    check("close goal replaces predecessor", bake([(0, 0), (10, 0), (10.015, 0)]),
          [[0, 0, 0], [10.015, 0, 10.015]])
    collapsed = bake([(0, 0), (0.001, 0)])
    check("collapse keeps only goal", collapsed, [[0.001, 0, 0]])
    check("collapse arrived", travel_engine.journey_state(collapsed, 0.0, 0.0)["arrived"], True)
    check("seat leg remains below 2cm", travel_engine._with_seat_leg([[0.001, 0, 0]], (0, 0)),
          [[0, 0, 0], [0.001, 0, 0]])
    rng = random.Random(2043)
    collapsed_pairs = 0
    for _ in range(10000):
        a = (rng.uniform(-1000, 1000), rng.uniform(-1000, 1000))
        gap, angle = rng.uniform(0.02, 0.05), rng.uniform(0, 2 * math.pi)
        b = (a[0] + gap * math.cos(angle), a[1] + gap * math.sin(angle))
        collapsed_pairs += tuple(round(v, 2) for v in a) == tuple(round(v, 2) for v in b)
    check("rounding proof 10000 pairs", collapsed_pairs, 0)


def main() -> int:
    print("\n[1] a running journey on a FROZEN clock — field for field")
    freeze_at(35.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    tr = char(allv, "demo_avatar").get("travel")
    check("the block exists", isinstance(tr, dict), True)
    tr = tr or {}
    check("exactly the § A11 fields", sorted(tr), sorted(FIELDS))
    for f in V1_FIELDS:
        check(f"no v1 cell field {f!r}", f in tr, False)
    check("target_id", tr.get("target_id"), B)
    # A seeded journey without a stored gait (an older one) walks.
    check("gait", tr.get("gait"), "walk")
    check("waypoints (x/z only, no t_cum)", tr.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("progress_m = 30 + 40 × 0.125", tr.get("progress_m"), 35.0)
    check("total_m = 30 + 40", tr.get("total_m"), 70.0)
    check("eta_game is canonical and timezone-free", tr.get("eta_game"), ETA)
    check("… with the HH:MM rendered server-side", tr.get("eta_hhmm"), "12:01")
    check("… and the calendar label beside it", tr.get("eta_label"), ETA_LABEL)
    # The journey started at the clock's own instant, so the departure bridge
    # is behind it: nothing is pending, and the countdown says so.
    check("starts_in_s is null once under way", tr.get("starts_in_s"), None)
    check("speed_m_s_real is null while frozen", tr.get("speed_m_s_real"), None)
    check("pace_m_s_real is null while frozen", tr.get("pace_m_s_real"), None)

    print("\n[2] a running clock — the pace is real metres per second at EVERY factor")
    for factor in (2.0, 0.5):
        stage(35.0, frozen=False, factor=factor)
        run = build_worldmap_payload("demo_avatar", show_all=True)
        rtr = char(run, "demo_avatar").get("travel") or {}
        check(f"factor {factor} → speed_m_s_real (no factor)",
              rtr.get("speed_m_s_real"), 1.0)
        check(f"factor {factor} → progress_m = 35.0 exactly",
              rtr.get("progress_m"), 35.0)
        check(f"factor {factor} → pace_m_s_real (this leg IS the nominal one)",
              rtr.get("pace_m_s_real"), 1.0)
        if factor == 2.0:
            check("factor 2 → eta = 12:00:35 + 35 × 2 (a projection)",
                  rtr.get("eta_game"), ETA_FACTOR2)

    print("\n[2b] the segment pace tells a slow leg from the nominal speed")
    stage(35.0, frozen=False, factor=2.0)
    slow = char(build_worldmap_payload("demo_avatar", show_all=True),
                "npc_slow").get("travel") or {}
    check("progress_m = 30 + 40 × 0.0625", slow.get("progress_m"), 32.5)
    check("speed_m_s_real stays the NOMINAL 1.0", slow.get("speed_m_s_real"), 1.0)
    check("pace_m_s_real = 40 m / 80 s", slow.get("pace_m_s_real"), 0.5)
    stage(10.0, frozen=False, factor=2.0)
    fast_leg = char(build_worldmap_payload("demo_avatar", show_all=True),
                    "npc_slow").get("travel") or {}
    check("on ITS first leg the two agree again (30 m / 30 s)",
          fast_leg.get("pace_m_s_real"), 1.0)

    print("\n[2c] past the end there is no current segment any more")
    stage(200.0, frozen=False, factor=1.0)
    done = char(build_worldmap_payload("demo_avatar", show_all=True),
                "demo_avatar").get("travel") or {}
    check("pace_m_s_real is null after the arrival", done.get("pace_m_s_real"),
          None)
    check("… while speed_m_s_real (nominal) still stands",
          done.get("speed_m_s_real"), 1.0)

    print("\n[3] a movement target alone is no journey")
    freeze_at(35.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    idle = char(allv, "npc_idle")
    check("npc_idle.travel", idle.get("travel"), None)
    check("… but the target is still reported",
          idle.get("movement_target_id"), B)

    print("\n[4] past the end the block stands until the ticker settles it")
    freeze_at(200.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    tr = char(allv, "demo_avatar").get("travel") or {}
    check("progress_m = total_m", (tr.get("progress_m"), tr.get("total_m")),
          (70.0, 70.0))
    check("arrived: eta_game is the calendar itself", tr.get("eta_game"),
          ETA_ARRIVED)

    print("\n[5] fog holds for travellers too")
    freeze_at(35.0)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("a traveller in an unknown place is gone", names(fog),
          ["demo_avatar", "npc_idle", "npc_near", "npc_slow"])
    ftr = char(fog, "demo_avatar").get("travel") or {}
    check("the avatar sees its own journey", ftr.get("target_id"), B)
    check("… the destination stays nameless",
          char(fog, "demo_avatar").get("movement_target_name"), "")
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    check("admin view has the traveller back", names(allv),
          ["demo_avatar", "npc_idle", "npc_near", "npc_slow", "npc_walker"])
    check("… with the same block",
          (char(allv, "npc_walker").get("travel") or {}).get("progress_m"),
          35.0)

    print("\n[6] fog withholds the ROUTE of everyone but the avatar — and "
          "every number it could be rebuilt from")
    freeze_at(35.0)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    near = char(fog, "npc_near").get("travel") or {}
    check("someone else's waypoints are withheld", near.get("waypoints"), None)
    check("… and the eight fields with them",
          [f for f in THIN_NUMBERS if near.get(f) is not None], [])
    check("… the opaque target_id stays", near.get("target_id"), B)
    # The gait is not thinned: it is what the figure's legs visibly do.
    check("… and so does the gait", near.get("gait"), "walk")
    check("… and every key is there, only null", sorted(near), sorted(FIELDS))
    own = char(fog, "demo_avatar").get("travel") or {}
    check("the avatar keeps its own route", own.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("… and its own numbers",
          (own.get("progress_m"), own.get("total_m")), (35.0, 70.0))
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    other = char(allv, "npc_near").get("travel") or {}
    check("the admin view hides no route", other.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("… and thins no number",
          (other.get("progress_m"), other.get("total_m")), (35.0, 70.0))

    contract_checks()

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
