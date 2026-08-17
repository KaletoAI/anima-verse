#!/usr/bin/env python3
"""Smoke run for the WORLD stamp on memories, events and diary entries
(plan-game-calendar.md, T2 group E).

Runs WITHOUT a server and WITHOUT a real world: a throwaway SQLite world is
created in a temp directory (``paths.init`` + ``db.init_schema``). ``worlds/``
is never touched.

The clock is PINNED: ``set_game_factor(0.0)`` first, then
``set_game_time(GameTime.parse(NOW))``. With factor 0 the game clock stands
still, so every expected value below is a fixed number and the run cannot
flake on wall-clock drift. No config is loaded, so the calendar is
``Calendar.default()`` — 4 seasons × 30 days, year_days = 120, season starts
(0, 30, 60, 90), and the display timezone is UTC.

THE HAND VALUES

  NOW = "Y0002-D109T14:00:00"
    day_index = (2−1)·120 + (109−1) = 120 + 108 = 228
    total     = 228·86400 + 14·3600 = 19 699 200 + 50 400 = 19 749 600 s
    doy0 108 ≥ 90 → season 3 (winter), day_of_season = 108 − 90 + 1 = 19
    date_label = "Winter, day 19 · Year 2"

  [1] add_memory writes exactly NOW into ``memories.game_ts`` (canonical
      string, byte-identical round trip through SQLite TEXT) and the entry it
      returns carries the same value. ``load_memories`` reads it back.

  [2] _format_memory_timestamp, by GAME-day difference (``day_index``):
        NOW             → 0 days  → "today 14:00"
        NOW − 1 day     → 1 day   → "yesterday 14:00"   (Y0002-D108T14:00:00)
        NOW − 3 days    → 3 days  → "3 days ago"        (Y0002-D106T14:00:00)
        NOW − 10 days   → 10 days → date_label + " HH:MM" of that day.
          day_index 228 − 10 = 218 → year 2, doy0 218 % 120 = 98 → day 99;
          98 ≥ 90 → winter, day_of_season = 98 − 90 + 1 = 9
          → "Winter, day 9 · Year 2 14:00"
        "" (no game stamp) → "" — never a fallback to the system stamp.

  [3] Recency markers run on the same day difference: 0 and 1 day → [CURRENT],
      2 days → [RECENT], 3 days → no marker, no stamp → no marker.

  [4] Migration group ``memories``: a row inserted the pre-column way (empty
      game_ts) with a SYSTEM ts of NOW_SYS − 2 h is back-projected at factor 1
      to the anchor − 2 h. Because ``game_time_at`` runs the CURRENT rate
      backwards and the anchor is pinned, that is exactly
      "Y0002-D109T12:00:00". Running the migration a SECOND time converts
      nothing (counter stays at the first run's value) — idempotent by filter.

  [5] ``_due_hint``: game_ts = NOW − 90 min ("Y0002-D109T12:30:00") with a
      delay of 120 min is due at 14:30, i.e. 30 min from NOW → "in 30 min".
      A promise 120 min old with a delay of 30 min is overdue → "overdue".
      An empty/garbage game stamp → "" (no guessing).

  [6] Diary: ``add_summary`` dates the entry by GAME day — game_ts is that
      day's start ("Y0002-D109T00:00:00"), metadata.date is the day key
      ("Y0002-D109"), and ``has_daily_summary`` finds it by day key while a
      different day key finds nothing.

  [7] Events: ``add_event`` stamps ``game_ts`` = NOW and computes
      ``expires_at`` as a GAME duration — ttl 6 h → "Y0002-D109T20:00:00".
      Its rendering is "today 14:00", and ``event_game_label`` is the full
      world label.

Usage:  ./.venv/bin/python scripts/smoke_memory_game_ts.py

Exit code 0 = all checks passed; any failure prints FAIL and exits 1.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="memory-game-ts-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="memory-game-ts-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import timeutils  # noqa: E402
from app.core.db import get_connection, transaction  # noqa: E402
from app.core.game_calendar_migration import (  # noqa: E402
    migrate_game_calendar_once)
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.thought_context import _due_hint  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

FAILURES = []
CHECKED = 0

CHAR = "Demo"
NOW = "Y0002-D109T14:00:00"
DAY_KEY = "Y0002-D109"
YESTERDAY = "Y0002-D108T14:00:00"
THREE_DAYS = "Y0002-D106T14:00:00"
TWO_DAYS = "Y0002-D107T14:00:00"
TEN_DAYS = "Y0002-D099T14:00:00"
GARBAGE = "not a stamp"


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


def pin_clock() -> None:
    """Stop the game clock and anchor it at NOW."""
    timeutils.set_game_factor(0.0)
    timeutils.set_game_time(GameTime.parse(NOW))


def main() -> int:
    from app.models import memory as mem_mod
    from app.models import diary as diary_mod
    from app.models import events as events_mod

    save_character_profile(CHAR, {"name": CHAR, "language": "en"},
                           create_new=True)

    print("\n[0] hand-derived anchor")
    pin_clock()
    check("game_time() is pinned at NOW", timeutils.game_time().canonical(), NOW)
    check("day_index of NOW", GameTime.parse(NOW).day_index, 228)
    check("total_seconds of NOW", GameTime.parse(NOW).total_seconds, 19_749_600)
    check("date_label of NOW", GameTime.parse(NOW).date_label("en"),
          "Winter, day 19 · Year 2")

    # ---------------------------------------------------------------- [1]
    print("\n[1] add_memory writes a canonical game stamp")
    entry = mem_mod.add_memory(CHAR, "the promise", memory_type="commitment",
                               tags=["promise"])
    check("returned entry game_ts", entry.get("game_ts"), NOW)
    rows = get_connection().execute(
        "SELECT game_ts FROM memories WHERE character_name=?", (CHAR,)).fetchall()
    check("stored game_ts", [r[0] for r in rows], [NOW])
    loaded = mem_mod.load_memories(CHAR)
    check("load_memories carries game_ts", loaded[0].get("game_ts"), NOW)
    # retrieve_relevant_memories writes the entries back (access_count/decay).
    # That round trip must not wipe the game stamp — the easiest regression to
    # introduce and the hardest to notice.
    mem_mod.retrieve_relevant_memories(CHAR, current_message="promise")
    check("game_ts survives the retrieval write-back", [
        r[0] for r in get_connection().execute(
            "SELECT game_ts FROM memories WHERE character_name=?",
            (CHAR,)).fetchall()], [NOW])

    # ---------------------------------------------------------------- [2]
    print("\n[2] _format_memory_timestamp on GAME-day distance")
    fmt = mem_mod._format_memory_timestamp
    check("0 days", fmt(NOW, "en"), "today 14:00")
    check("1 day", fmt(YESTERDAY, "en"), "yesterday 14:00")
    check("3 days", fmt(THREE_DAYS, "en"), "3 days ago")
    check("10 days", fmt(TEN_DAYS, "en"), "Winter, day 9 · Year 2 14:00")
    check("no game stamp", fmt("", "en"), "")
    check("garbage stamp", fmt(GARBAGE, "en"), "")

    # ---------------------------------------------------------------- [3]
    print("\n[3] recency markers on GAME-day distance")
    ago = mem_mod._game_days_ago
    check("today", ago(NOW), 0)
    check("yesterday", ago(YESTERDAY), 1)
    check("two days", ago(TWO_DAYS), 2)
    check("no stamp", ago(""), None)
    check_true("[CURRENT] threshold covers 0 and 1",
               ago(NOW) <= mem_mod._MARK_CURRENT_DAYS
               and ago(YESTERDAY) <= mem_mod._MARK_CURRENT_DAYS)
    check_true("[RECENT] threshold covers 2 but not 3",
               mem_mod._MARK_CURRENT_DAYS < ago(TWO_DAYS) <= mem_mod._MARK_RECENT_DAYS
               and ago(THREE_DAYS) > mem_mod._MARK_RECENT_DAYS)

    # ---------------------------------------------------------------- [4]
    print("\n[4] migration back-fills an empty game_ts (back-projection)")
    # Factor 1 for the projection: game_time_at runs the CURRENT rate
    # backwards, and a factor of 0 would collapse every distance to zero.
    timeutils.set_game_factor(1.0)
    timeutils.set_game_time(GameTime.parse(NOW))
    old_sys = (timeutils.utc_now()
               - __import__("datetime").timedelta(hours=2)).isoformat()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO memories (character_name, tier, ts, content) "
            "VALUES (?, 'semantic', ?, ?)", (CHAR, old_sys, "an old memory"))
    stats = migrate_game_calendar_once()
    check("memories converted", stats["memories"], 1)
    row = get_connection().execute(
        "SELECT game_ts FROM memories WHERE content='an old memory'").fetchone()
    projected = GameTime.parse(row[0])
    expected = GameTime.parse(NOW) - GameDuration.of(hours=2)
    check_true("back-projected to anchor − 2 h (±2 s)",
               abs(projected.total_seconds - expected.total_seconds) <= 2,
               f"{row[0]!r} vs {expected.canonical()!r}")
    stats2 = migrate_game_calendar_once()
    check("second run converts nothing", stats2["memories"], 0)
    check("second run leaves the stamp alone", get_connection().execute(
        "SELECT game_ts FROM memories WHERE content='an old memory'"
    ).fetchone()[0], row[0])

    # ---------------------------------------------------------------- [5]
    print("\n[5] _due_hint on the game clock")
    pin_clock()
    check("90 min old promise, 120 min delay",
          _due_hint("Y0002-D109T12:30:00", 120), "in 30 min")
    check("120 min old promise, 30 min delay",
          _due_hint("Y0002-D109T12:00:00", 30), "overdue")
    check("no game stamp", _due_hint("", 120), "")
    check("garbage stamp", _due_hint(GARBAGE, 120), "")

    # ---------------------------------------------------------------- [6]
    print("\n[6] diary entries are dated by GAME day")
    stored = diary_mod.add_summary(CHAR, "a quiet day", DAY_KEY)
    check("entry game_ts is the day start", stored["game_ts"],
          f"{DAY_KEY}T00:00:00")
    check("entry metadata.date is the day key",
          stored["metadata"]["date"], DAY_KEY)
    check("day label", diary_mod.day_label(DAY_KEY, "en"),
          "Winter, day 19 · Year 2")
    check("has_daily_summary finds that day",
          diary_mod.has_daily_summary(CHAR, DAY_KEY), True)
    check("has_daily_summary misses another day",
          diary_mod.has_daily_summary(CHAR, "Y0002-D108"), False)
    check("resolve_day_key defaults to today",
          diary_mod.resolve_day_key(None), DAY_KEY)

    # ---------------------------------------------------------------- [7]
    print("\n[7] events carry a game stamp and a WORLD ttl")
    evt = events_mod.add_event("a storm rolls in", location_id="loc1",
                               ttl_hours=6, category="danger")
    check("event game_ts", evt["game_ts"], NOW)
    check("expires 6 GAME hours later", evt["expires_at"], "Y0002-D109T20:00:00")
    check("not expired at NOW", events_mod._is_expired(evt), False)
    check("event time rendering", events_mod._format_event_timestamp(NOW, "en"),
          "today 14:00")
    check("event game label", events_mod.event_game_label(evt, "en"),
          "Winter, day 19 · 14:00 · Year 2")
    stored_evt = get_connection().execute(
        "SELECT game_ts FROM events WHERE kind='world_event'").fetchone()
    check("game_ts reached the column", stored_evt[0], NOW)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAILED: {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
