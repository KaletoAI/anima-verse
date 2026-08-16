#!/usr/bin/env python3
"""Smoke check for the scene safety net (plan-room-conversation, task R3).

Usage:
    ./.venv/bin/python scripts/smoke_scene_safety_net.py

No server, no world DB, no LLM: it exercises the pure decision function
``scene_manager.classify_scene`` plus the two config getters (with a stubbed
``config.get``).

The rule, and every expectation below derived from it BY HAND:

  * ``classify_scene(opened_ts, last_activity_ts, perception_count, now,
    idle_minutes, max_hours, max_perceptions, in_skip)`` answers with the reason
    to consolidate an OPEN scene, or ``None`` to leave it open.
  * ``"idle"``   — ``last_activity_ts < now - idle_minutes`` AND NOT ``in_skip``
    (a room with a pending obligatory answer keeps its perceptions).
  * ``"max_age"`` — ``max_hours > 0`` AND ``opened_ts < now - max_hours``.
    Beats ``in_skip`` — that is the point of the net.
  * ``"max_len"`` — ``max_perceptions > 0`` AND
    ``perception_count >= max_perceptions``. Beats ``in_skip`` too.
  * Precedence idle → max_age → max_len; all comparisons are STRICT ``<``
    (SYSTEM time), unparsable stamps never trigger their rule.

Fixed clock for the table: now = 2026-08-17T12:00:00Z, idle 30 min,
max_hours 6 (→ age threshold 06:00Z), cap 400.

  #   opened   last act.  count  skip   expected   why (by hand)
  1   11:00    11:00       10    no     idle       silent for 60 min > 30
  2   09:00    11:59       10    no     None       3 h old < 6 h, 1 min silent, 10 < 400
  3   05:00    11:59       10    no     max_age    7 h old > 6 h, never idle
  4   10:00    11:59      400    no     max_len    400 >= 400
  5   10:00    11:59      399    no     None       399 < 400
  6   10:00    11:00       10    YES    None       idle, but the skip wins
  7   04:00    11:59       10    YES    max_age    8 h old — the net wins over the skip
  8   10:00    11:59      400    YES    max_len    the net wins over the skip
  9   11:00    11:00       10    YES    None       idle only, skipped (= #6 with another start)
 10   05:00    11:00       10    no     idle       idle AND too old → idle reported first

  Off switches (same clock):
 11   2026-08-10 11:59  10  no, max_hours=0        → None (7 days old, age net off)
 12   11:00    11:59     5000  no, cap=0           → None (size net off)

  Boundaries (strict <):
 13   last activity exactly 11:30:00 (= now − 30 min)      → None
 14   last activity 11:29:59                               → idle
 15   opened exactly 06:00:00 (= now − 6 h), never silent  → None
 16   opened 05:59:59, never silent                        → max_age

  Robustness:
 17   opened "", last "" , count 0                         → None (nothing parses)
 18   opened "garbage", last "11:00", count 0              → idle (only the
      readable half decides; the age rule cannot fire)

  SQL/decision agreement: ``run_idle_consolidation`` passes the cutoff to SQLite
  as ``(now - idle).isoformat(timespec="seconds")`` — TRUNCATED to whole
  seconds, therefore never LATER than the real threshold. So every row the query
  returns is also idle for ``classify_scene``:
 19   now = 12:00:00.750, cutoff string 11:30:00, row at 11:29:59 → idle

  Config getters (``config.get`` stubbed, no world):
 20   scene_max_hours: unset → 6, "" → 6, 12 → 12, "3" → 3, 0 → 0 (off),
      -5 → 0 (clamped, never negative), "abc" → 6
 21   scene_max_perceptions: unset → 400, 0 → 0, "900" → 900, "x" → 400,
      and the result is an int
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.core import config  # noqa: E402
from app.core.scene_manager import (  # noqa: E402
    classify_scene, scene_max_hours, scene_max_perceptions)

FAILED = 0
NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


def check(name: str, got, expected) -> None:
    global FAILED
    ok = got == expected
    if not ok:
        FAILED += 1
    print(f"{'PASS  ' if ok else 'FAIL  '}{name}  (got {got!r}, expected {expected!r})")


def at(hour: int, minute: int = 0, second: int = 0, day: int = 17) -> str:
    return datetime(2026, 8, day, hour, minute, second,
                    tzinfo=timezone.utc).isoformat(timespec="seconds")


def decide(opened, last, count=0, skip=False, now=NOW,
           idle=30.0, max_hours=6.0, cap=400):
    return classify_scene(opened_ts=opened, last_activity_ts=last,
                          perception_count=count, now=now, idle_minutes=idle,
                          max_hours=max_hours, max_perceptions=cap, in_skip=skip)


print("— classify_scene (now = 2026-08-17T12:00:00Z, idle 30 min, 6 h, 400) —")
check("1  plain idle", decide(at(11), at(11), 10), "idle")
check("2  constant traffic, young scene", decide(at(9), at(11, 59), 10), None)
check("3  constant traffic, too old", decide(at(5), at(11, 59), 10), "max_age")
check("4  perception cap reached", decide(at(10), at(11, 59), 400), "max_len")
check("5  one below the cap", decide(at(10), at(11, 59), 399), None)
check("6  idle room in skip", decide(at(10), at(11), 10, skip=True), None)
check("7  too old room in skip", decide(at(4), at(11, 59), 10, skip=True), "max_age")
check("8  over cap in skip", decide(at(10), at(11, 59), 400, skip=True), "max_len")
check("9  idle only, in skip", decide(at(11), at(11), 10, skip=True), None)
check("10 idle and too old → idle first", decide(at(5), at(11), 10), "idle")

print("— off switches —")
check("11 max_hours=0 disables the age net",
      decide(at(11, 59, 0, day=10), at(11, 59), 10, max_hours=0), None)
check("12 cap=0 disables the size net",
      decide(at(11), at(11, 59), 5000, cap=0), None)

print("— boundaries (strict <) —")
check("13 exactly at the idle threshold", decide(at(10), at(11, 30), 10), None)
check("14 one second past it", decide(at(10), at(11, 29, 59), 10), "idle")
check("15 exactly at the age threshold", decide(at(6), at(11, 59), 10), None)
check("16 one second past it", decide(at(5, 59, 59), at(11, 59), 10), "max_age")

print("— robustness —")
check("17 empty stamps decide nothing", decide("", "", 0), None)
check("18 unreadable start, readable silence", decide("garbage", at(11), 0), "idle")

print("— SQL cutoff agrees with the decision —")
_now = NOW.replace(microsecond=750000)
_cutoff = (_now - timedelta(minutes=30)).isoformat(timespec="seconds")
check("19a cutoff is truncated to whole seconds", _cutoff, at(11, 30))
check("19b a row below the cutoff classifies as idle",
      decide(at(10), at(11, 29, 59), 10, now=_now), "idle")

print("— config getters (stubbed config) —")


def with_cfg(getter, key: str, value):
    orig = config.get
    config.get = lambda k, default=None: value if k == key else orig(k, default)
    try:
        return getter()
    finally:
        config.get = orig


K_H, K_P = "memory.scene_max_hours", "memory.scene_max_perceptions"
check("20a default 6 h", with_cfg(scene_max_hours, K_H, None), 6.0)
check("20b empty falls back", with_cfg(scene_max_hours, K_H, ""), 6.0)
check("20c configured wins", with_cfg(scene_max_hours, K_H, 12), 12.0)
check("20d string coerced", with_cfg(scene_max_hours, K_H, "3"), 3.0)
check("20e zero means off", with_cfg(scene_max_hours, K_H, 0), 0.0)
check("20f negative clamped to off", with_cfg(scene_max_hours, K_H, -5), 0.0)
check("20g garbage falls back", with_cfg(scene_max_hours, K_H, "abc"), 6.0)
check("21a default 400", with_cfg(scene_max_perceptions, K_P, None), 400)
check("21b zero means off", with_cfg(scene_max_perceptions, K_P, 0), 0)
check("21c string coerced", with_cfg(scene_max_perceptions, K_P, "900"), 900)
check("21d garbage falls back", with_cfg(scene_max_perceptions, K_P, "x"), 400)
check("21e result is an int",
      isinstance(with_cfg(scene_max_perceptions, K_P, "900"), int), True)

print(f"\n{'FAILED: ' + str(FAILED) + ' check(s)' if FAILED else 'OK — all checks passed'}")
sys.exit(1 if FAILED else 0)
