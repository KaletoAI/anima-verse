#!/usr/bin/env python3
"""Smoke run for the game clock on GameTime + the one-time boot migration
(plan-game-calendar.md, T1).

Runs WITHOUT a server and WITHOUT a real world: a throwaway SQLite world is
created in a temp directory (``paths.init`` + ``db.init_schema``), seeded with
LEGACY ISO stamps, and then migrated. ``worlds/`` is never touched.

No config is loaded, so two things are the shipped defaults and every number
below is derived from them:
  * display timezone = UTC (``server.timezone`` unset), i.e. the migration's
    ``EPOCH_REAL`` is 2026-01-01T00:00:00 UTC;
  * calendar = ``Calendar.default()`` — 4 seasons × 30 days, so year_days=120
    and the season starts are (0, 30, 60, 90); winter owns days 91..120.

THE MAPPING (§2.4 / decision E2), by hand:

    total_seconds = int((stamp in display tz) − 2026-01-01T00:00:00)
    negative → 0 (counted as ``clamped``)

2026 is NOT a leap year, so the day-of-year table is
Jan 31 → 31, Feb 28 → 59, Mar → 90, Apr → 120, May → 151, Jun → 181,
Jul → 212. Hence 10 Aug = 222, 16 Aug = 228, 17 Aug = 229, 18 Aug = 230.

    17 Aug 2026, 14:00 UTC
      → days since 1 Jan 00:00 = 229 − 1 = 228, plus 14 h
      → total = 228·86400 + 14·3600 = 19 699 200 + 50 400 = 19 749 600 s
      → day_index 228 → year = 228//120 + 1 = 2, doy0 = 228 % 120 = 108
      → day_of_year 109; 108 ≥ 90 → season index 3 (winter),
        day_of_season = 108 − 90 + 1 = 19
      → canonical "Y0002-D109T14:00:00", label "Winter, day 19 · 14:00 · Year 2"

The other seeded stamps by the same rule:

    16 Aug 22:00 → day_index 227 → year 2, doy0 107 → "Y0002-D108T22:00:00"
    17 Aug 06:15 →                                    "Y0002-D109T06:15:00"
    17 Aug 07:00 →                                    "Y0002-D109T07:00:00"
    17 Aug 13:00 →                                    "Y0002-D109T13:00:00"
    17 Aug 15:30 →                                    "Y0002-D109T15:30:00"
    17 Aug 18:45 →                                    "Y0002-D109T18:45:00"
    17 Aug 20:00 →                                    "Y0002-D109T20:00:00"
    10 Aug 09:00 → day_index 221 → year 2, doy0 101 → "Y0002-D102T09:00:00"
    18 Aug 08:00 → day_index 229 → year 2, doy0 109 → "Y0002-D110T08:00:00"
    31 Dec 2025 23:00 → NEGATIVE → clamped to 0     → "Y0001-D001T00:00:00"

Cases:
  [1] world_kv anchor: ISO "2026-08-17T14:00:00+00:00" → "Y0002-D109T14:00:00",
      season winter, day_of_season 19 (the hand calculation above).
  [2] thoughts.game_ts: two rows 90 minutes apart, one written with a
      "+02:00" offset (16:00+02:00 IS 14:00 UTC — the offset must be honoured,
      not stripped). After the migration both are canonical AND
      parse(b) − parse(a) == GameDuration.of(minutes=90): distances survive
      the migration EXACTLY, which is the whole point of E2.
  [3] Character profile: ``active_conditions[0].started_at``,
      ``state_flag_since[*]`` and ``journey.started_at_game`` all canonical;
      plus scheduler job (``last_execution.game_timestamp``,
      ``_registered_game``, ``trigger.run_date``) and an intent
      (``expires_at``, ``trigger.run_date``). A SECOND run changes nothing —
      every counter is 0 (idempotence by format probe).
  [4] A stamp before 2026 clamps to the epoch and is counted as ``clamped``.
  [5] Garbage stays untouched and is counted as ``unparsable``.
  [6] The clock: with factor 0 ``game_time()`` returns EXACTLY the anchor and
      does not drift; ``set_game_time(GameTime)`` round-trips through
      ``get_game_clock_info()["anchor_game"]``; ``set_game_time("2026-…")``
      and a ``datetime`` raise TypeError (game time is not a datetime).

Usage:  ./.venv/bin/python scripts/smoke_game_time_migration.py
"""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="game-time-migration-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="game-time-migration-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import timeutils  # noqa: E402
from app.core.game_time import EPOCH, GameDuration, GameTime  # noqa: E402

from app.core.db import get_connection, transaction  # noqa: E402
from app.core.game_calendar_migration import (  # noqa: E402
    migrate_game_calendar_once)
from app.models.character import (  # noqa: E402
    get_character_profile, get_character_scheduler_jobs,
    save_character_profile, save_character_scheduler_jobs)
from app.models.intents import create_intent, list_intents  # noqa: E402
from app.models.world import get_world_setting, set_world_setting  # noqa: E402

FAILURES = []
CHECKED = 0

CHAR = "Demo"

ISO_ANCHOR = "2026-08-17T14:00:00+00:00"
ISO_THOUGHT_A = "2026-08-17T16:00:00+02:00"   # == 14:00 UTC
ISO_THOUGHT_B = "2026-08-17T15:30:00+00:00"   # 90 min after A
ISO_SLEEP = "2026-08-17T06:15:00+00:00"
ISO_ANCIENT = "2025-12-31T23:00:00+00:00"     # before EPOCH_REAL → clamped
ISO_COND = "2026-08-17T13:00:00+00:00"
ISO_FLAG = "2026-08-16T22:00:00+00:00"
ISO_JOURNEY = "2026-08-17T14:30:00+00:00"
ISO_JOB_LAST = "2026-08-17T07:00:00+00:00"
ISO_JOB_REG = "2026-08-10T09:00:00+00:00"
ISO_JOB_RUN = "2026-08-18T08:00:00+00:00"
ISO_INTENT_EXP = "2026-08-17T20:00:00+00:00"
ISO_INTENT_RUN = "2026-08-17T18:45:00+00:00"
GARBAGE = "irgendwann am Nachmittag"

GT_ANCHOR = "Y0002-D109T14:00:00"
GT_THOUGHT_A = "Y0002-D109T14:00:00"
GT_THOUGHT_B = "Y0002-D109T15:30:00"
GT_SLEEP = "Y0002-D109T06:15:00"
GT_EPOCH = "Y0001-D001T00:00:00"
GT_COND = "Y0002-D109T13:00:00"
GT_FLAG = "Y0002-D108T22:00:00"
GT_JOURNEY = "Y0002-D109T14:30:00"
GT_JOB_LAST = "Y0002-D109T07:00:00"
GT_JOB_REG = "Y0002-D102T09:00:00"
GT_JOB_RUN = "Y0002-D110T08:00:00"
GT_INTENT_EXP = "Y0002-D109T20:00:00"
GT_INTENT_RUN = "Y0002-D109T18:45:00"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'OK' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Seed the throwaway world with LEGACY (ISO) stamps
# ---------------------------------------------------------------------------

def seed() -> None:
    set_world_setting("game_time.anchor_real",
                      timeutils.utc_now().isoformat(timespec="seconds"))
    set_world_setting("game_time.anchor_game", ISO_ANCHOR)
    set_world_setting("game_time.factor", "1.0")
    set_world_setting(f"sleep_start:{CHAR}", ISO_SLEEP)
    set_world_setting("sleep_start:Ancient", ISO_ANCIENT)

    now_sys = timeutils.utc_now_iso()
    with transaction() as conn:
        conn.executemany(
            "INSERT INTO thoughts (character_name, ts, game_ts, content)"
            " VALUES (?, ?, ?, ?)",
            [(CHAR, now_sys, ISO_THOUGHT_A, "first thought"),
             (CHAR, now_sys, ISO_THOUGHT_B, "second thought"),
             (CHAR, now_sys, GARBAGE, "unparsable stamp")])

    save_character_profile(CHAR, {
        "name": CHAR,
        "active_conditions": [
            {"name": "tired", "duration_hours": 6, "started_at": ISO_COND}],
        "state_flag_since": {"is_sleeping": ISO_FLAG},
        "journey": {"target": "somewhere", "waypoints": [[0, 0], [10, 10]],
                    "started_at_game": ISO_JOURNEY, "speed_m_s": 1.0},
    }, create_new=True)

    save_character_scheduler_jobs(CHAR, [{
        "id": "job_demo_1",
        "character": CHAR,
        "source": "smoke",
        "created_at": now_sys,
        "action": {"type": "send_message", "message": "hi"},
        "trigger": {"type": "date", "run_date": ISO_JOB_RUN, "one_time": True},
        "last_execution": {"timestamp": now_sys, "game_timestamp": ISO_JOB_LAST},
        "_registered_game": ISO_JOB_REG,
    }])

    create_intent(owner=CHAR, title="Smoke intent",
                  trigger={"kind": "at_time", "run_date": ISO_INTENT_RUN},
                  expires_at=ISO_INTENT_EXP)


def thought_stamps():
    rows = get_connection().execute(
        "SELECT game_ts FROM thoughts ORDER BY id ASC").fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def case_migration() -> None:
    print("\n[1-5] Boot migration: ISO stamps → canonical GameTime")
    stats = migrate_game_calendar_once()
    print(f"       counters: {stats}")

    check("anchor counter", stats["anchor"], 1)
    check("sleep_start counter", stats["sleep_start"], 2)
    check("thoughts counter", stats["thoughts"], 2)
    check("profiles counter", stats["profiles"], 1)
    check("scheduler counter", stats["scheduler"], 1)
    check("intents counter", stats["intents"], 1)
    check("clamped counter", stats["clamped"], 1)
    check("unparsable counter", stats["unparsable"], 1)

    # [1] anchor
    anchor = get_world_setting("game_time.anchor_game", "")
    check("anchor canonical", anchor, GT_ANCHOR)
    gt = GameTime.parse(anchor)
    check("anchor total_seconds", gt.total_seconds, 228 * 86400 + 14 * 3600)
    check("anchor season", gt.season, "winter")
    check("anchor day_of_season", gt.day_of_season, 19)
    check("anchor year", gt.year, 2)
    check("anchor day_of_year", gt.day_of_year, 109)
    check("anchor label", gt.label(), "Winter, day 19 · 14:00 · Year 2")

    # [2] thoughts — distances stay exact
    stamps = thought_stamps()
    check("thought A canonical", stamps[0], GT_THOUGHT_A)
    check("thought B canonical", stamps[1], GT_THOUGHT_B)
    check("thought B − A", GameTime.parse(stamps[1]) - GameTime.parse(stamps[0]),
          GameDuration.of(minutes=90))
    # [5] garbage untouched
    check("garbage stamp untouched", stamps[2], GARBAGE)

    # [3] profile / scheduler / intent
    profile = get_character_profile(CHAR)
    check("condition started_at", profile["active_conditions"][0]["started_at"], GT_COND)
    check("state_flag_since", profile["state_flag_since"]["is_sleeping"], GT_FLAG)
    check("journey started_at_game", profile["journey"]["started_at_game"], GT_JOURNEY)

    job = get_character_scheduler_jobs(CHAR)[0]
    check("job last game_timestamp", job["last_execution"]["game_timestamp"], GT_JOB_LAST)
    check("job _registered_game", job["_registered_game"], GT_JOB_REG)
    check("job trigger run_date", job["trigger"]["run_date"], GT_JOB_RUN)
    check("job last timestamp (SYSTEM) still ISO",
          job["last_execution"]["timestamp"].startswith("20"), True)

    intent = list_intents()[0]
    check("intent expires_at", intent["expires_at"], GT_INTENT_EXP)
    check("intent trigger run_date", intent["trigger"]["run_date"], GT_INTENT_RUN)

    # [4] clamped
    check("sleep_start (in range)", get_world_setting(f"sleep_start:{CHAR}", ""), GT_SLEEP)
    check("sleep_start (pre-2026, clamped)",
          get_world_setting("sleep_start:Ancient", ""), GT_EPOCH)
    check("clamped stamp is the epoch", GameTime.parse(GT_EPOCH), EPOCH)


def case_idempotent() -> None:
    print("\n[3b] Second run changes nothing (format probe)")
    stats = migrate_game_calendar_once()
    print(f"       counters: {stats}")
    for key in ("anchor", "sleep_start", "thoughts", "profiles", "scheduler",
                "intents", "clamped"):
        check(f"second run {key}", stats[key], 0)
    # The garbage row is still seen and still refused — never guessed at.
    check("second run unparsable", stats["unparsable"], 1)
    check("anchor unchanged", get_world_setting("game_time.anchor_game", ""), GT_ANCHOR)
    check("thoughts unchanged", thought_stamps()[:2], [GT_THOUGHT_A, GT_THOUGHT_B])


def case_clock() -> None:
    print("\n[6] The clock itself")
    timeutils.invalidate_game_clock_cache()
    running = timeutils.game_time()
    anchor = GameTime.parse(GT_ANCHOR)
    check_true("clock runs from the migrated anchor",
               anchor <= running <= anchor + GameDuration.of(minutes=5),
               f"{running.canonical()} vs anchor {GT_ANCHOR}")

    # Factor 0: the clock stands exactly on its anchor, no drift at all.
    timeutils.set_game_factor(0.0)
    frozen = timeutils.game_time()
    info = timeutils.get_game_clock_info()
    check("factor 0 → anchor == now", info["anchor_game"], frozen.canonical())
    check("factor 0 → no drift", timeutils.game_time(), frozen)
    check("factor persisted", info["factor"], 0.0)

    # Round-trip a GameTime through the anchor.
    target = GameTime.parse(GT_ANCHOR)
    timeutils.set_game_time(target)
    info = timeutils.get_game_clock_info()
    check("set_game_time round-trip", info["anchor_game"], GT_ANCHOR)
    check("game_time after set", timeutils.game_time(), target)
    check("clock info season", info["game"]["season"], "winter")
    check("clock info day_of_season", info["game"]["day_of_season"], 19)
    check("clock info canonical", info["game"]["canonical"], GT_ANCHOR)
    check("clock info calendar year_days", info["calendar"]["year_days"], 120)
    check_true("clock info system_now is ISO", info["system_now"].endswith("+00:00"),
               info["system_now"])

    # Strict type: no silent parsing of legacy values.
    for bad in (ISO_ANCHOR, datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc), 0):
        try:
            timeutils.set_game_time(bad)          # type: ignore[arg-type]
            check(f"set_game_time({type(bad).__name__}) raises", "no raise", "TypeError")
        except TypeError:
            check(f"set_game_time({type(bad).__name__}) raises", "TypeError", "TypeError")
    check("anchor survived the rejected sets",
          timeutils.get_game_clock_info()["anchor_game"], GT_ANCHOR)


def main() -> int:
    print(f"Throwaway world: {STORAGE}")
    seed()
    case_migration()
    case_idempotent()
    case_clock()
    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
