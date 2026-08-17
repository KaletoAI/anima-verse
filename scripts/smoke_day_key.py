#!/usr/bin/env python3
"""Checks the GAME-day keys of the consolidation ladder (plan-game-calendar E4).

Usage:
    ./.venv/bin/python scripts/smoke_day_key.py

Runs without the server and without a world DB: the game clock is replaced by
a fixed instant, so every function under test becomes pure. No world DB is
opened — the calendar falls back to the shipped default (4 seasons × 30 days,
no weekdays), which is what the hand values below are derived from.

WHY these expectations (derived by hand from the calendar, not recorded from
current output). Default calendar: year_days = 4 × 30 = 120, season starts at
day-of-year 1 / 31 / 61 / 91, week length = 7 (the world has no weekdays).

1. day_key of Y0002-D109
   day_index = (2-1)·120 + (109-1) = 228 → total = 228·86400 = 19 699 200 s.
   Key is "Y0002-D109"; its date_label puts day 109 in the 4th season
   (108 ≥ 90) at day_of_season 108 − 90 + 1 = 19 → "Winter, day 19 · Year 2".

2. week key of that day
   (109 − 1) // 7 + 1 = 108 // 7 + 1 = 15 + 1 = 16 → "Y0002-W016", and that
   week starts at day-of-year (16 − 1)·7 + 1 = 106 → "Y0002-D106".
   The last week of a year is SHORT: day 120 → (119 // 7) + 1 = 18, and week
   18 starts at day 120 — only one day fits before the year rolls over, which
   is why weeks are counted inside the year instead of across it.

3. season key
   day 109 sits in season index 3 (0-based) → "Y0002-S04", labelled
   "Winter · Year 2".

4. lexicographic order = chronological order
   That is the whole reason the keys are zero-padded: "Y0002-D099" <
   "Y0002-D100" < "Y0002-D109" < "Y0003-D001" as plain strings, so the SQL
   ORDER BY and the ">= cutoff" comparisons of the rollup keep working.

5. recent_game_day_keys(3) at Y0002-D109T14:00
   The three days before today, oldest first: D106, D107, D108 (+ D109 when
   today is not skipped). Near the world epoch the list is SHORTER instead of
   reaching behind Year 1 Day 1: at Y0001-D002 (day_index 1) asking for 5 days
   yields only "Y0001-D001".

6. timeutils.game_time_at() with factor 60
   A system stamp 5 real hours old is 5·3600·60 = 1 080 000 game seconds back.
   19 699 200 + 14·3600 = 19 749 600 minus that = 18 669 600 s = day_index 216
   remainder 7200 s → year 2 (216 − 120 = 96 → day 97), 02:00 →
   "Y0002-D097T02:00:00".

7. timeutils.system_window_of_game_day("Y0002-D109") with factor 60
   The game day started 14 game hours ago = 14·3600 / 60 = 840 real seconds
   ago, and ends 10 game hours ahead = 600 real seconds from now. So the SQL
   window around a real "now" T is [T − 840 s, T + 600 s) — 24 real minutes,
   one game day at factor 60.
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import day_consolidation as dc  # noqa: E402
from app.core import memory_service as ms  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core import timeutils as tu  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

FAILED = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILED.append(label)


def freeze_clock(when: GameTime, factor: float, now=None):
    """Replace the game clock in the modules under test — no DB, no world.

    ``timeutils`` has to be patched as well: the back-projection
    (``game_time_at`` / ``system_window_of_game_day``) lives there and reads
    the clock out of its OWN module globals, so patching only the callers
    would leave it on the real clock.
    """
    now = now or utc_now()
    for module in (dc, ms, tu):
        module.game_time = lambda w=when: w
    for module in (dc, tu):
        module.game_speed_factor = lambda f=factor: f
        module.utc_now = lambda n=now: n
    return now


DAY = GameTime.from_parts(2, 109, 14, 0, 0)

# 1 — the day key itself
check("total_seconds of Y0002-D109T14:00", DAY.total_seconds, 19_749_600)
check("day_key", DAY.day_key(), "Y0002-D109")
check("date_label", DAY.date_label(), "Winter, day 19 · Year 2")
check("parse_day_key round trip",
      dc.parse_day_key("Y0002-D109").total_seconds, 19_699_200)
check("parse_day_key rejects a real date", dc.parse_day_key("2026-08-17"), None)

# 2 — week keys
check("week key", ms._week_key(DAY), "Y0002-W016")
check("week start", ms._week_start("Y0002-W016").day_key(), "Y0002-D106")
check("last week of the year",
      ms._week_key(GameTime.from_parts(2, 120)), "Y0002-W018")
check("short last week starts on day 120",
      ms._week_start("Y0002-W018").day_key(), "Y0002-D120")
check("first week of the next year",
      ms._week_key(GameTime.from_parts(3, 1)), "Y0003-W001")
check("week start rejects a real week", ms._week_start("2026-W33"), None)

# 3 — season keys
check("season key", ms._season_key(DAY), "Y0002-S04")
check("season key of day 1", ms._season_key(GameTime.from_parts(2, 1)), "Y0002-S01")
check("season label", ms.season_label("Y0002-S04"), "Winter · Year 2")

# 4 — sortability of all three tiers
check("days sort chronologically",
      sorted(["Y0003-D001", "Y0002-D100", "Y0002-D099", "Y0002-D109"]),
      ["Y0002-D099", "Y0002-D100", "Y0002-D109", "Y0003-D001"])
check("weeks sort chronologically",
      sorted(["Y0003-W001", "Y0002-W016", "Y0002-W002"]),
      ["Y0002-W002", "Y0002-W016", "Y0003-W001"])
check("seasons sort chronologically",
      sorted(["Y0003-S01", "Y0002-S04", "Y0002-S01"]),
      ["Y0002-S01", "Y0002-S04", "Y0003-S01"])

# 5 — the N-game-day window
now = freeze_clock(DAY, 60.0)
check("last 3 game days (today skipped)",
      dc.recent_game_day_keys(3, skip_today=True),
      ["Y0002-D106", "Y0002-D107", "Y0002-D108"])
check("last 3 game days (today included)",
      dc.recent_game_day_keys(3),
      ["Y0002-D106", "Y0002-D107", "Y0002-D108", "Y0002-D109"])
check("zero days", dc.recent_game_day_keys(0), [])

freeze_clock(GameTime.from_parts(1, 2, 8, 0, 0), 60.0)
check("window does not reach behind the epoch",
      dc.recent_game_day_keys(5, skip_today=True), ["Y0001-D001"])

# 6 — system stamp → game day
now = freeze_clock(DAY, 60.0)
check("5 real hours ago at factor 60",
      tu.game_time_at(now - timedelta(hours=5)).canonical(),
      "Y0002-D097T02:00:00")
check("its day key", dc.game_day_of(now - timedelta(hours=5)), "Y0002-D097")
check("2 real minutes ago stays on the same game day",
      dc.game_day_of(now - timedelta(minutes=2)), "Y0002-D109")
check("unusable stamp", dc.game_day_of("not a date"), "")

freeze_clock(DAY, 1.0, now)
check("at factor 1 a real day back is a game day back",
      dc.game_day_of(now - timedelta(days=1)), "Y0002-D108")

# 7 — game day → system window
now = freeze_clock(DAY, 60.0)
start, end = tu.system_window_of_game_day("Y0002-D109")
check("window start = 840 real seconds ago",
      start, (now - timedelta(seconds=840)).isoformat())
check("window end = 600 real seconds ahead",
      end, (now + timedelta(seconds=600)).isoformat())
check("window of a non-game key", tu.system_window_of_game_day("2026-08-17"), None)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("all checks passed")
