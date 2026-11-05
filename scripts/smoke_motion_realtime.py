#!/usr/bin/env python3
"""Movement runs in REAL time — the game clock's factor never scales walking.

Usage:
    ./.venv/bin/python scripts/smoke_motion_realtime.py

Runs on a throwaway storage (``paths.init`` before any world-DB import); the
SYSTEM clock is pinned (``timeutils.utc_now`` replaced by a hand-moved one), so
every number below is exact. No server, no LLM, no real world.

The rule (user decision 2026-11-05, plan-bewegung-echtzeit.md): a journey's
position is a pure function of the MOTION clock (``timeutils.motion_time`` —
real seconds the world has run unfrozen). The game clock's factor and a time
jump leave it alone; the world freeze stops it.

Hand-derived expectations. One journey, one straight leg of 14 m baked at
1.4 m/s: waypoints ``[[0, 0, 0], [14, 0, 10]]`` (14 / 1.4 = 10 s), started at
the motion instant S of the pinned real instant R0.

  [1] Factor 1 and factor 4, 4 real seconds after the start:
        factor 1  -> 4 game s pass,  progress 4 × 1.4 = 5.6 m, pos (5.6, 0)
        factor 4  -> 16 game s pass, progress STILL 5.6 m, pos (5.6, 0)
      metres per real second: 5.6 / 4 = 1.4 at both factors — the same.
      (Under the old game-clock model factor 4 would have walked 16 × 1.4 =
      22.4 m > 14 m, i.e. already arrived.)
  [2] Factor change mid-journey: factor 1, +2 real s -> 2.8 m; the factor is
      set to 4 at that instant -> still 2.8 m (no jump); +2 real s more ->
      5.6 m; the game clock meanwhile advanced 2 × 1 + 2 × 4 = 10 game s.
  [3] Freeze: at +4 real s (5.6 m) the world is frozen; +10 real s later the
      journey still stands at 5.6 m and ``motion_rate()`` is 0.0; thawed, +2
      real s -> 5.6 + 2 × 1.4 = 8.4 m (the frozen span is not counted).
      A repeated freeze/unfreeze call does not move the motion clock.
  [4] A time jump (``set_game_time`` +1 game hour) at +4 real s leaves the
      journey at 5.6 m.
  [5] The payload paces: ``segment_paces_m_s_real(wps, motion_rate())`` =
      [1.4] at factor 1 AND factor 4 (14 m / 10 s); None while frozen.
  [6] The calendar arrival is a projection: at +4 real s, factor 4, 6 real s
      remain -> ``journey_eta`` = game now + 6 × 4 = game now + 24 s; at
      factor 1 -> game now + 6 s. While frozen at factor 4 the projection
      keeps the configured factor: game now + 24 s.
  [7] The approach start of a prop action (``_approach_start``) and the
      departure delay are real seconds: exit clip 2.23 s -> start =
      motion now + 2.23 at factor 1 AND factor 10; no clip -> + 0.3 s lead.
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

paths.init(Path(tempfile.mkdtemp(prefix="smoke-motion-realtime-")))

from app.core import db, timeutils  # noqa: E402

db.init_schema()

from app.core import travel_engine as T  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.models.world import set_world_frozen  # noqa: E402

FAILS = []
CHECKS = 0
R0 = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
_now = [R0]
timeutils.utc_now = lambda: _now[0]


def advance(seconds: float) -> None:
    _now[0] = _now[0] + timedelta(seconds=seconds)


def check(label, actual, expected, tol=1e-6):
    global CHECKS
    CHECKS += 1
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        ok = abs(actual - expected) <= tol
    else:
        ok = actual == expected
    print(f"  {'ok ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


WPS = [[0.0, 0.0, 0.0], [14.0, 0.0, 10.0]]


def reset(factor: float) -> float:
    """Thawed world at R0, game clock at day 1 noon with ``factor``; returns S."""
    set_world_frozen(False)
    _now[0] = R0
    timeutils.invalidate_game_clock_cache()
    timeutils.set_game_time(GameTime.parse("Y0001-D001T12:00:00"))
    timeutils.set_game_factor(factor)
    return timeutils.motion_time()


def walked(start: float) -> float:
    return T.journey_state(WPS, start, timeutils.motion_time())["progress_m"]


print("[1] the same metres per real second at factor 1 and factor 4")
for factor in (1.0, 4.0):
    s = reset(factor)
    g0 = timeutils.game_time()
    advance(4)
    st = T.journey_state(WPS, s, timeutils.motion_time())
    check(f"factor {factor}: game seconds passed", (timeutils.game_time() - g0).seconds, 4.0 * factor)
    check(f"factor {factor}: progress after 4 real s", st["progress_m"], 5.6)
    check(f"factor {factor}: position", st["pos"], (5.6, 0.0))
    check(f"factor {factor}: metres per real second", st["progress_m"] / 4, 1.4)
    check(f"factor {factor}: remaining real seconds", st["remaining_s"], 6.0)

print("[2] a factor change mid-journey does not move the walker")
s = reset(1.0)
g0 = timeutils.game_time()
advance(2)
check("factor 1, +2 s", walked(s), 2.8)
timeutils.set_game_factor(4.0)
check("factor set to 4 at that instant: no jump", walked(s), 2.8)
advance(2)
check("+2 s at factor 4", walked(s), 5.6)
check("game clock meanwhile: 2×1 + 2×4 game s", (timeutils.game_time() - g0).seconds, 10.0)

print("[3] the freeze stops the motion clock, the frozen span is not counted")
s = reset(1.0)
advance(4)
set_world_frozen(True)
check("frozen at 5.6 m", walked(s), 5.6)
advance(10)
check("+10 real s frozen: still 5.6 m", walked(s), 5.6)
check("motion_rate frozen", timeutils.motion_rate(), 0.0)
timeutils._motion_on_freeze_change(True)        # a repeated freeze call
check("a repeated freeze does not move the clock", walked(s), 5.6)
set_world_frozen(False)
check("thawed: still 5.6 m", walked(s), 5.6)
check("motion_rate running", timeutils.motion_rate(), 1.0)
advance(2)
check("+2 real s after the thaw: 5.6 + 2.8", walked(s), 8.4)
timeutils._motion_on_freeze_change(False)       # a repeated unfreeze call
check("a repeated unfreeze does not move the clock", walked(s), 8.4)

print("[4] a game-clock time jump leaves the journey alone")
s = reset(1.0)
advance(4)
timeutils.set_game_time(GameTime(timeutils.game_time().total_seconds + 3600))
check("+1 game hour: still 5.6 m", walked(s), 5.6)

print("[5] the payload paces are real metres per second at every factor")
for factor in (1.0, 4.0):
    reset(factor)
    check(f"factor {factor}: paces", T.segment_paces_m_s_real(WPS, timeutils.motion_rate()), [1.4])
reset(4.0)
set_world_frozen(True)
check("frozen: paces None", T.segment_paces_m_s_real(WPS, timeutils.motion_rate()), None)

print("[6] the calendar arrival is a projection of the real remainder")
for factor, ahead in ((4.0, 24), (1.0, 6)):
    s = reset(factor)
    advance(4)
    st = T.journey_state(WPS, s, timeutils.motion_time())
    now = timeutils.game_time()
    check(f"factor {factor}: eta = now + 6 × {factor}", (T.journey_eta(st) - now).seconds, float(ahead))
s = reset(4.0)
advance(4)
set_world_frozen(True)
st = T.journey_state(WPS, s, timeutils.motion_time())
check("frozen at factor 4: eta keeps the configured factor",
      (T.journey_eta(st) - timeutils.game_time()).seconds, 24.0)

print("[7] departure and approach delays are the clip's real seconds")
for factor in (1.0, 10.0):
    reset(factor)
    m = timeutils.motion_time()
    check(f"factor {factor}: exit 2.23 s", T._departure_start(2.23) - m, 2.23, tol=1e-3)
    check(f"factor {factor}: approach, no clip -> 0.3 s lead", T._approach_start(0.0) - m, 0.3, tol=1e-3)
    check(f"factor {factor}: approach, clip 2.23 s", T._approach_start(2.23) - m, 2.23, tol=1e-3)

print()
if FAILS:
    print(f"FAILED {len(FAILS)}/{CHECKS}: {FAILS}")
    sys.exit(1)
print(f"OK — {CHECKS} checks passed")
