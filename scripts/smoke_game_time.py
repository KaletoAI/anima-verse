#!/usr/bin/env python3
"""Smoke run for the world calendar and the GameTime/GameDuration types
(plan-game-calendar.md, T0).

Runs WITHOUT a server, without a world DB and without a config: every
calendar is built explicitly (``Calendar.default()`` or a hand-written one)
and ``game_time.get_calendar`` is monkeypatched, so nothing here can reach
``worlds/``.

Rules every expectation below is derived from BY HAND:

  * A GameTime is whole GAME seconds since the epoch = Year 1, Day 1,
    00:00:00. One day is 86400 s, no exceptions (no DST, no leap anything).
  * ``day_index = total // 86400`` (0-based), ``year = day_index //
    year_days + 1``, ``day_of_year = day_index % year_days + 1`` (1-based).
  * A season owns the day range ``[start, start + days)`` where ``start`` is
    the sum of the lengths of the seasons before it;
    ``day_of_season = day_of_year − start``.
  * Default calendar: spring/summer/autumn/winter, 30 days each →
    year_days = 120, season starts (0, 30, 60, 90), sunrise 06:00 (360 min),
    sunset 18:00 (1080 min), morning ends 12, afternoon ends 17.
  * Night = ``minutes_of_day < sunrise`` OR ``>= sunset`` (of the CURRENT
    season). Only daylight is split further: morning < noon_hour ≤
    afternoon < evening_hour ≤ evening.
  * Canonical string ``Y%04d-D%03dT%02d:%02d:%02d``.

Hand-derived expectations:

  [1] Epoch, total_seconds = 0
        day_index 0 → year 1, day_of_year 1, season_index 0 (spring,
        start 0) → day_of_season 1, time 00:00:00
        → canonical "Y0001-D001T00:00:00", day_key "Y0001-D001"
        minutes_of_day 0 < 360 → night, bucket "night"
        label "Spring, day 1 · 00:00 · Year 1"

  [2] Season and year boundaries (default calendar)
        86400·30 = 2592000 → day_index 30 → day_of_year 31; 31 > 30, so the
          season is summer (start 30) and day_of_season = 31 − 30 = 1
          → "Y0001-D031T00:00:00"
        86400·119 + 23·3600 + 59·60 + 59 = 10281600 + 86399 = 10367999
          → day_index 119 → day_of_year 120, winter (start 90) day 30,
          23:59:59 → "Y0001-D120T23:59:59"  (the last second of year 1)
        +1 s = 10368000 = 86400·120 → day_index 120 → year 120//120 + 1 = 2,
          day_of_year 1, spring day 1 → "Y0002-D001T00:00:00"

  [3] Canonical string
        Y0003-D047T14:23:45 → day_index = 2·120 + 46 = 286
          → 286·86400 = 24710400, plus 14·3600 + 23·60 + 45 = 51825
          → total 24762225; parse → canonical is the identity
        Sorting the five stamps of [1]–[3] as STRINGS must equal sorting the
        five GameTimes numerically (that is why SQL comparisons keep working)
        A day_of_year beyond the year is NOT clamped, it rolls over:
          "Y0001-D200T00:00:00" → day_index = 0·120 + 199 = 199
          → year 199//120 + 1 = 2, day_of_year 199 − 120 + 1 = 80
          → canonical "Y0002-D080T00:00:00"
        is_canonical is a pure format probe: an ISO datetime
          "2026-08-17T14:00:00+00:00" is False, so is "Y1-D1T00:00:00"

  [4] Day buckets, default calendar (sunrise 06:00, sunset 18:00, 12/17)
        05:59 night · 06:00 morning · 11:59 morning · 12:00 afternoon
        16:59 afternoon · 17:00 evening · 17:59 evening · 18:00 night
      Season with sunrise 08:00 (480) / sunset 16:00 (960)
        07:00 → 420 < 480 → night   (although the hour would say "morning")
        16:00 → 960 ≥ 960 → night   (although the hour would say "afternoon")
        08:00 → morning · 15:59 → afternoon

  [5] A custom calendar: 3 seasons of 10 / 20 / 5 days, 7 weekday names
        year_days = 10 + 20 + 5 = 35, season starts (0, 10, 30)
        day_of_year 11 → 0-based 10 → season_index 1 (10 ≤ 10 < 30)
        day_index 8 → weekday 8 mod 7 = 1 → the second weekday name
        the same instant on a calendar WITHOUT week_days → weekday None,
        weekday_name ""

  [6] Durations
        t1 = epoch, t2 = t1 + 3 h 30 min → (t2 − t1).hours = 3.5,
          .minutes = 210.0, .days = 12600/86400 = 0.1458333…
        epoch + 25 h = 90000 s → day_index 1, 01:00 → "Y0001-D002T01:00:00"
        epoch − 1 h would be < 0 → ValueError; minus_clamped → epoch
        str(of(days=2, hours=3, minutes=15)) = "2d 03:15:00";
        str(of(hours=3, minutes=15)) = "03:15:00";
        str(of(minutes=-90)) = "-01:30:00"
        of(hours=1) · 2 = of(hours=2); ZERO is falsy, 1 s is truthy

  [7] Construction from calendar parts
        from_season(1, "winter", 30) → day_of_year = 90 + 30 = 120
          → "Y0001-D120T00:00:00"; day 31 is out of winter's range →
          ValueError; an unknown key → ValueError
        from_parts(1, 1, 24, 0, 0) → ValueError (hour is 0..23),
          from_parts(0, 1) → ValueError (year is 1-based)

  [8] from_config tolerance
        (None, None) → exactly Calendar.default()
        garbage: week_days 123 → no weeks; year_label None → "Year {n}";
        day_bucket_noon "x" → 12; day_bucket_evening 99 → clamped to 23;
        a season without a key → key slugged from the name ("wet_season"),
        days 0 → 1, sunrise "25:00"/sunset "18:61" invalid → 06:00/18:00;
        a second season with the SAME key → suffixed "wet_season_2"
        → year_days = 1 + 30 = 31

  [9] Labels
        default calendar, Y0003-D047T14:23:45 → "Summer, day 17 · 14:23 ·
          Year 3"; date_label drops the time → "Summer, day 17 · Year 3"
        year_label "" → the year part disappears → "Summer, day 17 · 14:23"
        with weekdays, day_index 8 on the [5] calendar → day_of_year 9,
          season "Alpha" day 9, weekday 1 → "Tirsday, Alpha, day 9 · 00:00"
        to_dict hour_fraction for 14:23:45 = 14 + 23/60 + 45/3600
          = 14.395833…
        the season's atmosphere rides along in both payloads: the default
          calendar ships summer hot/dry, so to_dict()["atmosphere"] is
          {"season": "summer", "temperature": "hot", "weather": "dry",
           "note": "", "label": "hot, dry"} and calendar_to_dict lists
          temperature/weather/weather_note per season

Usage:  ./.venv/bin/python scripts/smoke_game_time.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import game_time  # noqa: E402
from app.core.game_time import (  # noqa: E402
    EPOCH,
    Calendar,
    GameDuration,
    GameTime,
    Season,
)

CHECKED = 0
FAILURES = []


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
          + ("" if ok else f" — expected ≈{expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_raises(label, fn, exc=ValueError):
    global CHECKED
    CHECKED += 1
    try:
        result = fn()
    except exc:
        print(f"  ✓ {label}: raised {exc.__name__}")
        return
    except Exception as e:  # wrong exception type
        print(f"  ✗ {label}: raised {type(e).__name__} — expected {exc.__name__}")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: returned {result!r} — expected {exc.__name__}")
    FAILURES.append(label)


def use(calendar):
    """Monkeypatch the module-level calendar lookup (no config, no world)."""
    game_time.get_calendar = lambda: calendar


DEFAULT = Calendar.default()
use(DEFAULT)


# ── [1] the epoch ───────────────────────────────────────────────────────
print("[1] epoch = Year 1, Day 1, 00:00:00")
check("total_seconds", EPOCH.total_seconds, 0)
check("year", EPOCH.year, 1)
check("day_of_year", EPOCH.day_of_year, 1)
check("day_index", EPOCH.day_index, 0)
check("season", EPOCH.season, "spring")
check("season_name", EPOCH.season_name(), "Spring")
check("day_of_season", EPOCH.day_of_season, 1)
check("canonical", EPOCH.canonical(), "Y0001-D001T00:00:00")
check("str(EPOCH)", str(EPOCH), "Y0001-D001T00:00:00")
check("day_key", EPOCH.day_key(), "Y0001-D001")
check("time_hhmm", EPOCH.time_hhmm(), "00:00")
check("is_night (00:00 < 06:00)", EPOCH.is_night(), True)
check("is_day", EPOCH.is_day(), False)
check("day_bucket", EPOCH.day_bucket(), "night")
check("label", EPOCH.label(), "Spring, day 1 · 00:00 · Year 1")
check("year_days of the default calendar", DEFAULT.year_days, 120)
check("season_starts", DEFAULT.season_starts, (0, 30, 60, 90))
check_raises("negative seconds", lambda: GameTime(-1))


# ── [2] season and year boundaries ──────────────────────────────────────
print("[2] season and year boundaries")
summer_1 = GameTime(86400 * 30)
check("86400*30 canonical", summer_1.canonical(), "Y0001-D031T00:00:00")
check("… season", summer_1.season, "summer")
check("… day_of_season", summer_1.day_of_season, 1)
check("… day_of_year", summer_1.day_of_year, 31)

last = GameTime(86400 * 119 + 23 * 3600 + 59 * 60 + 59)
check("last second of year 1 (total)", last.total_seconds, 10367999)
check("… canonical", last.canonical(), "Y0001-D120T23:59:59")
check("… season", last.season, "winter")
check("… day_of_season", last.day_of_season, 30)

new_year = GameTime(last.total_seconds + 1)
check("+1 s → new year", new_year.canonical(), "Y0002-D001T00:00:00")
check("… year", new_year.year, 2)
check("… season", new_year.season, "spring")
check("… day_of_season", new_year.day_of_season, 1)


# ── [3] the canonical string ────────────────────────────────────────────
print("[3] canonical string: roundtrip, sorting, rollover")
t3 = GameTime.parse("Y0003-D047T14:23:45")
check("parsed total_seconds", t3.total_seconds, 24762225)
check("roundtrip", t3.canonical(), "Y0003-D047T14:23:45")
check("… season", t3.season, "summer")
check("… day_of_season", t3.day_of_season, 17)

stamps = [
    "Y0002-D001T00:00:00",
    "Y0001-D120T23:59:59",
    "Y0003-D047T14:23:45",
    "Y0001-D001T00:00:00",
    "Y0001-D031T00:00:00",
]
times = [GameTime.parse(s) for s in stamps]
check("lexicographic order == chronological order",
      sorted(stamps),
      [t.canonical() for t in sorted(times)])

rolled = GameTime.parse("Y0001-D200T00:00:00")
check("day_of_year beyond the year rolls over, never clamps",
      rolled.canonical(), "Y0002-D080T00:00:00")
check("… day_index", rolled.day_index, 199)

check("is_canonical(valid)", GameTime.is_canonical("Y0001-D001T00:00:00"), True)
check("is_canonical(ISO datetime)",
      GameTime.is_canonical("2026-08-17T14:00:00+00:00"), False)
check("is_canonical(short digits)",
      GameTime.is_canonical("Y1-D1T00:00:00"), False)
check("is_canonical(space instead of T)",
      GameTime.is_canonical("Y0001-D001 00:00:00"), False)
check("is_canonical('')", GameTime.is_canonical(""), False)
check("is_canonical(None)", GameTime.is_canonical(None), False)
check_raises("parse(ISO datetime)",
             lambda: GameTime.parse("2026-08-17T14:00:00+00:00"))
check_raises("parse(hour 24)", lambda: GameTime.parse("Y0001-D001T24:00:00"))
check_raises("parse(year 0)", lambda: GameTime.parse("Y0000-D001T00:00:00"))


# ── [4] day buckets ─────────────────────────────────────────────────────
print("[4] day buckets and night")


def at(hour, minute=0, second=0, day_index=0):
    return GameTime(day_index * 86400 + hour * 3600 + minute * 60 + second)


for hh, mm, expected in [
    (5, 59, "night"), (6, 0, "morning"), (11, 59, "morning"),
    (12, 0, "afternoon"), (16, 59, "afternoon"), (17, 0, "evening"),
    (17, 59, "evening"), (18, 0, "night"),
]:
    check(f"default calendar {hh:02d}:{mm:02d}", at(hh, mm).day_bucket(), expected)

dark = Calendar(seasons=(Season("dark", "Dark", 30, 8 * 60, 16 * 60),))
check("short-day season sunrise_min", dark.seasons[0].sunrise_min, 480)
check("short-day season sunset_min", dark.seasons[0].sunset_min, 960)
check("short day 07:00 (before sunrise 08:00)",
      at(7).day_bucket(calendar=dark), "night")
check("short day 16:00 (at sunset 16:00)",
      at(16).day_bucket(calendar=dark), "night")
check("short day 08:00", at(8).day_bucket(calendar=dark), "morning")
check("short day 15:59", at(15, 59).day_bucket(calendar=dark), "afternoon")
check("short day 07:00 is_night", at(7).is_night(calendar=dark), True)
check("short day 12:00 is_day", at(12).is_day(calendar=dark), True)


# ── [5] a custom calendar: 3 seasons + weekdays ─────────────────────────
print("[5] custom calendar 10/20/5 days, 7 weekdays")
WEEK = ("Moonday", "Tirsday", "Wodensday", "Thorsday",
        "Freyday", "Sunsday", "Starday")
custom = Calendar(
    seasons=(Season("a", "Alpha", 10), Season("b", "Beta", 20),
             Season("c", "Gamma", 5)),
    week_days=WEEK,
)
check("year_days", custom.year_days, 35)
check("season_starts", custom.season_starts, (0, 10, 30))
check("season_index for day 11 (0-based 10)",
      custom.season_index_for_day(10), 1)
check("season_index for day 10 (0-based 9)",
      custom.season_index_for_day(9), 0)
check("season_index for day 31 (0-based 30)",
      custom.season_index_for_day(30), 2)
check("season_by_key('b')", custom.season_by_key("b").name, "Beta")
check("season_by_key(unknown)", custom.season_by_key("zz"), None)

use(custom)
d8 = GameTime(8 * 86400)
check("day_index 8 → weekday", d8.weekday, 1)
check("… weekday_name", d8.weekday_name, "Tirsday")
check("… day_of_year", d8.day_of_year, 9)
check("… season", d8.season, "a")
check("… day_of_season", d8.day_of_season, 9)
check("… canonical", d8.canonical(), "Y0001-D009T00:00:00")

use(DEFAULT)
check("no week_days → weekday None", GameTime(8 * 86400).weekday, None)
check("no week_days → weekday_name ''", GameTime(8 * 86400).weekday_name, "")


# ── [6] durations ───────────────────────────────────────────────────────
print("[6] GameDuration arithmetic")
t1 = EPOCH
t2 = t1 + GameDuration.of(hours=3, minutes=30)
check("t2 canonical", t2.canonical(), "Y0001-D001T03:30:00")
approx("(t2 - t1).hours", (t2 - t1).hours, 3.5)
approx("(t2 - t1).minutes", (t2 - t1).minutes, 210.0)
approx("(t2 - t1).days", (t2 - t1).days, 12600 / 86400)
check("(t2 - t1).total_seconds", (t2 - t1).total_seconds, 12600)
check("(t1 - t2) is negative",
      (t1 - t2).total_seconds, -12600)

check("epoch + 25 h", (EPOCH + GameDuration.of(hours=25)).canonical(),
      "Y0001-D002T01:00:00")
check_raises("epoch - 1 h → below the epoch",
             lambda: EPOCH - GameDuration.of(hours=1))
check("minus_clamped stops at the epoch",
      EPOCH.minus_clamped(GameDuration.of(days=3)), EPOCH)
check("minus_clamped inside the world",
      GameTime(86400 * 5).minus_clamped(GameDuration.of(days=3)),
      GameTime(86400 * 2))

check("str(2d 3h 15m)", str(GameDuration.of(days=2, hours=3, minutes=15)),
      "2d 03:15:00")
check("str(3h 15m)", str(GameDuration.of(hours=3, minutes=15)), "03:15:00")
check("str(-90 min)", str(GameDuration.of(minutes=-90)), "-01:30:00")
check("of(hours=1) * 2", GameDuration.of(hours=1) * 2, GameDuration.of(hours=2))
check("2 * of(hours=1)", 2 * GameDuration.of(hours=1), GameDuration.of(hours=2))
check("-of(hours=1)", -GameDuration.of(hours=1), GameDuration(-3600))
check("abs(-of(hours=1))", abs(GameDuration.of(hours=-1)), GameDuration(3600))
check("of(hours=1) + of(minutes=30)",
      GameDuration.of(hours=1) + GameDuration.of(minutes=30),
      GameDuration.of(minutes=90))
check("of() rounds to whole seconds",
      GameDuration.of(seconds=1.6).total_seconds, 2)
check("ZERO is falsy", bool(GameDuration.ZERO), False)
check("1 s is truthy", bool(GameDuration.of(seconds=1)), True)
check("durations compare",
      GameDuration.of(hours=1) < GameDuration.of(hours=2), True)

check("start_of_day", at(14, 30).start_of_day().canonical(),
      "Y0001-D001T00:00:00")
check("next_day_start", at(14, 30).next_day_start().canonical(),
      "Y0001-D002T00:00:00")
check("replace(hour=9, minute=5)",
      at(14, 30, 30).replace(hour=9, minute=5).canonical(),
      "Y0001-D001T09:05:30")
check_raises("replace(hour=24)", lambda: at(12).replace(hour=24))


# ── [7] construction from calendar parts ────────────────────────────────
print("[7] from_parts / from_season")
check("from_parts(3, 47, 14, 23, 45)",
      GameTime.from_parts(3, 47, 14, 23, 45).canonical(), "Y0003-D047T14:23:45")
check("from_season(1, 'winter', 30)",
      GameTime.from_season(1, "winter", 30).canonical(), "Y0001-D120T00:00:00")
check("from_season(2, 'summer', 1, 6, 30)",
      GameTime.from_season(2, "summer", 1, 6, 30).canonical(),
      "Y0002-D031T06:30:00")
check_raises("from_season(1, 'winter', 31) — past the season's last day",
             lambda: GameTime.from_season(1, "winter", 31))
check_raises("from_season(1, 'winter', 0)",
             lambda: GameTime.from_season(1, "winter", 0))
check_raises("from_season(1, 'monsoon', 1) — unknown key",
             lambda: GameTime.from_season(1, "monsoon", 1))
check_raises("from_parts(1, 1, 24)", lambda: GameTime.from_parts(1, 1, 24))
check_raises("from_parts(0, 1) — year is 1-based",
             lambda: GameTime.from_parts(0, 1))
check_raises("from_parts(1, 0) — day is 1-based",
             lambda: GameTime.from_parts(1, 0))


# ── [8] from_config tolerance ───────────────────────────────────────────
print("[8] Calendar.from_config is tolerant")
check("from_config(None, None) == default",
      Calendar.from_config(None, None), Calendar.default())
check("from_config('nope', []) == default",
      Calendar.from_config("nope", []), Calendar.default())
check("from_config with a non-list season section == default seasons",
      Calendar.from_config({}, "seasons?").seasons, Calendar.default().seasons)

junk = Calendar.from_config(
    {"week_days": 123, "year_label": None,
     "day_bucket_noon": "x", "day_bucket_evening": 99},
    [{"name": "Wet Season", "days": 0, "sunrise": "25:00", "sunset": "18:61"},
     {"key": "wet_season"}],
)
check("garbage week_days → no weeks", junk.week_days, ())
check("garbage year_label → default", junk.year_label, "Year {n}")
check("garbage noon hour → 12", junk.noon_hour, 12)
check("out-of-range evening hour → clamped to 23", junk.evening_hour, 23)
check("season keys (slugged + de-duplicated)",
      [s.key for s in junk.seasons], ["wet_season", "wet_season_2"])
check("days 0 → 1", junk.seasons[0].days, 1)
check("invalid sunrise → 06:00", junk.seasons[0].sunrise, "06:00")
check("invalid sunset → 18:00", junk.seasons[0].sunset, "18:00")
check("missing days → 30", junk.seasons[1].days, 30)
check("year_days", junk.year_days, 31)

parsed = Calendar.from_config(
    {"week_days": " Moonday , Tirsday ,, Wodensday ", "year_label": "",
     "day_bucket_noon": "11", "day_bucket_evening": 16},
    [{"key": "wet", "name": "Wet", "name_de": "Regenzeit", "days": 12,
      "sunrise": "05:30", "sunset": "20:15"}],
)
check("week_days split/trimmed, empties dropped",
      parsed.week_days, ("Moonday", "Tirsday", "Wodensday"))
check("empty year_label stays empty (year hidden)", parsed.year_label, "")
check("noon hour from string", parsed.noon_hour, 11)
check("sunrise minutes", parsed.seasons[0].sunrise_min, 330)
check("sunset minutes", parsed.seasons[0].sunset_min, 1215)
check("localized season name", parsed.seasons[0].name_for("de"), "Regenzeit")
check("season name falls back to en", parsed.seasons[0].name_for("fr"), "Wet")


# ── [9] labels and the API payload ──────────────────────────────────────
print("[9] labels and to_dict")
use(DEFAULT)
check("label", t3.label(), "Summer, day 17 · 14:23 · Year 3")
check("date_label", t3.date_label(), "Summer, day 17 · Year 3")

no_year = Calendar(seasons=DEFAULT.seasons, year_label="")
check("year_label '' hides the year",
      t3.label(calendar=no_year), "Summer, day 17 · 14:23")

check("weekday prefix",
      d8.label(calendar=Calendar(seasons=custom.seasons, week_days=WEEK,
                                 year_label="")),
      "Tirsday, Alpha, day 9 · 00:00")

payload = t3.to_dict()
check("to_dict canonical", payload["canonical"], "Y0003-D047T14:23:45")
check("to_dict total_seconds", payload["total_seconds"], 24762225)
check("to_dict season", payload["season"], "summer")
check("to_dict season_name", payload["season_name"], "Summer")
check("to_dict day_of_season", payload["day_of_season"], 17)
check("to_dict time", payload["time"], "14:23")
check("to_dict is_night", payload["is_night"], False)
check("to_dict day_bucket", payload["day_bucket"], "afternoon")
check("to_dict weekday (no weeks)", payload["weekday"], None)
approx("to_dict hour_fraction", payload["hour_fraction"],
       14 + 23 / 60 + 45 / 3600)

check("to_dict atmosphere", payload["atmosphere"],
      {"season": "summer", "temperature": "hot", "weather": "dry",
       "note": "", "label": "hot, dry"})

cal_payload = game_time.calendar_to_dict(DEFAULT)
check("calendar_to_dict year_days", cal_payload["year_days"], 120)
check("calendar_to_dict week_days", cal_payload["week_days"], [])
check("calendar_to_dict first season",
      cal_payload["seasons"][0],
      {"key": "spring", "name": "Spring", "days": 30,
       "sunrise": "06:00", "sunset": "18:00",
       "temperature": "mild", "weather": "rain", "weather_note": ""})

check("no datetime lookalikes on GameTime",
      [n for n in ("strftime", "month", "date", "astimezone", "isoformat",
                   "timestamp", "tzinfo")
       if hasattr(GameTime, n)], [])
check_true("weekday is a property, not a datetime-style method",
           isinstance(GameTime.__dict__.get("weekday"), property))

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
