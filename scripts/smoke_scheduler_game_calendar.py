#!/usr/bin/env python3
"""Smoke run for the scheduler on the WORLD CALENDAR (plan-game-calendar.md
§2.6, task T3).

Runs WITHOUT a world, without a DB and without starting APScheduler: the
matcher functions are pure, the SchedulerManager instance is built via
``__new__`` (no ``__init__``, so no background scheduler, no job loading), and
the calendar comes from a monkeypatched ``app.core.game_time.get_calendar``.

The calendar used below is ``Calendar.default()``:
4 seasons x 30 days = 120 days a year, no week days.

    season   day-of-year range
    spring     1 ..  30
    summer    31 ..  60
    autumn    61 ..  90
    winter    91 .. 120

So **winter day 19 = day-of-year 109**, and ``Y0002-D109`` has the day index
(2 - 1) * 120 + (109 - 1) = 228 days since the epoch.

Cron fields are ``minute``, ``hour``, ``day_of_season`` (1..season length),
``season`` (season KEY) and ``weekday`` (index or week-day name; only valid
in a world that HAS weeks). ``day``/``month``/``day_of_week`` are gone.

Hand-derived expectations:

  [a] cron {hour: 8, minute: 0}, no date fields:
        now Y0002-D109T14:00:00 → Y0002-D109T08:00:00 (same day, earlier)
        now Y0002-D109T07:59:00 → Y0002-D108T08:00:00 (08:00 is still ahead,
                                  so the occurrence is yesterday's)

  [b] cron {season: "winter", day_of_season: 19, hour: 8, minute: 0}:
        now Y0002-D109T14:00:00 → Y0002-D109T08:00:00 (today IS winter 19)
        now Y0002-D108T14:00:00 → Y0001-D109T08:00:00
      The second one is the iteration-cap check: winter day 19 exists once a
      year, so the walk goes from day index 227 (Y0002-D108) back to day
      index 108 (Y0001-D109) — 119 day steps. The cap is
      ``year_days + 100`` = 220 day steps, which covers it; the old flat 400
      steps of ONE HOUR each would have stopped after 16 days.

  [c] weekday:
        no week days configured → constraint dropped with a warning, so
          {weekday: 1, hour: 8} answers exactly like [a]: Y0002-D109T08:00:00
        week_days = 7 names, {weekday: 1, hour: 8}, now Y0002-D109T14:00:00:
          day index 228, 228 mod 7 = 4, so 3 days back → day index 225
          → year 2 (225 // 120 = 1), day-of-year 225 - 120 + 1 = 106
          → Y0002-D106T08:00:00

  [d] _date_ok boundaries with {day_of_season: N, hour: 8},
      now Y0002-D109T14:00:00 (winter day 19):
        N = 1  → the 1st of a season: doy 1/31/61/91 → Y0002-D091T08:00:00
        N = 30 → the 30th: doy 30/60/90/120 → Y0002-D090T08:00:00
                 (winter's 30th is doy 120 and still ahead)
        N = 31 → no season has 31 days → None, ever

  [e] migrate_cron_fields({day: 15, month: 2, day_of_week: 3}) on the default
      calendar → ({day_of_season: 15, season: "summer"}, True):
        month 2 → season index (2 - 1) % 4 = 1 → "summer"
        day 15 ≤ 30 (summer's length) → day_of_season 15
        day_of_week 3 → dropped, the default calendar has no weeks
      Running it again over the result changes nothing (idempotent).

  [f] interval dueness with a canonical anchor: period 3600 s,
      anchor Y0002-D109T08:00:00
        now Y0002-D109T08:59:59 (3599 s) → not due
        now Y0002-D109T09:00:00 (3600 s) → due

Usage:  ./.venv/bin/python scripts/smoke_scheduler_game_calendar.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import game_time as game_time_mod  # noqa: E402
from app.core.game_time import Calendar, GameTime  # noqa: E402

DEFAULT_CAL = Calendar.default()
WEEK_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEK_CAL = Calendar(seasons=DEFAULT_CAL.seasons, week_days=WEEK_NAMES)

_active_cal = [DEFAULT_CAL]
game_time_mod.get_calendar = lambda: _active_cal[0]

from app.core.game_calendar_migration import migrate_cron_fields  # noqa: E402
from app.scheduler import scheduler_manager as sm_mod  # noqa: E402
from app.scheduler.scheduler_manager import SchedulerManager  # noqa: E402

# The manager's module-level imports bound the ORIGINAL get_calendar, so the
# patch has to land there too (the matcher looks the calendar up by name).
sm_mod.get_calendar = lambda: _active_cal[0]

# No __init__: no BackgroundScheduler, no world, no job loading.
MANAGER = SchedulerManager.__new__(SchedulerManager)

FAILURES = []
CHECKED = 0


class _WarningTrap(logging.Handler):
    """Collects the scheduler's warnings so a check can assert on them."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


TRAP = _WarningTrap()
logging.getLogger("scheduler").addHandler(TRAP)


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def occurrence(cfg, now_canonical):
    """_last_cron_occurrence as a canonical string (or None)."""
    occ = MANAGER._last_cron_occurrence(cfg, GameTime.parse(now_canonical))
    return occ.canonical() if occ is not None else None


# ── [a] plain daily schedule ────────────────────────────────────────────
print("[a] cron hour=8 minute=0 without date fields")
DAILY = {"type": "cron", "hour": 8, "minute": 0}
check("14:00 → today 08:00", occurrence(DAILY, "Y0002-D109T14:00:00"),
      "Y0002-D109T08:00:00")
check("07:59 → yesterday 08:00", occurrence(DAILY, "Y0002-D109T07:59:00"),
      "Y0002-D108T08:00:00")

# ── [b] season + day-of-season, one occurrence a year ───────────────────
print("[b] cron season=winter day_of_season=19 hour=8")
WINTER19 = {"type": "cron", "season": "winter", "day_of_season": 19,
            "hour": 8, "minute": 0}
check("winter day 19, 14:00 → today 08:00",
      occurrence(WINTER19, "Y0002-D109T14:00:00"), "Y0002-D109T08:00:00")
check("winter day 18 → last year's winter day 19 (119 day steps back)",
      occurrence(WINTER19, "Y0002-D108T14:00:00"), "Y0001-D109T08:00:00")

# ── [c] weekday, with and without weeks ─────────────────────────────────
print("[c] weekday only means something in a world with weeks")
TRAP.messages.clear()
check("no week days → constraint dropped, same as [a]",
      occurrence({"type": "cron", "weekday": 1, "hour": 8, "minute": 0},
                 "Y0002-D109T14:00:00"), "Y0002-D109T08:00:00")
check("… and it warned",
      any("no week days" in m for m in TRAP.messages), True)

_active_cal[0] = WEEK_CAL
TRAP.messages.clear()
check("7 week days, weekday=1 → 3 days back",
      occurrence({"type": "cron", "weekday": 1, "hour": 8, "minute": 0},
                 "Y0002-D109T14:00:00"), "Y0002-D106T08:00:00")
check("weekday by NAME resolves the same",
      occurrence({"type": "cron", "weekday": "Tue", "hour": 8, "minute": 0},
                 "Y0002-D109T14:00:00"), "Y0002-D106T08:00:00")
check("… without warnings", TRAP.messages, [])
_active_cal[0] = DEFAULT_CAL

# ── [d] day_of_season boundaries ────────────────────────────────────────
print("[d] day_of_season boundaries (seasons are 30 days long)")
for day, expected in ((1, "Y0002-D091T08:00:00"),
                      (30, "Y0002-D090T08:00:00"),
                      (31, None)):
    check(f"day_of_season={day}",
          occurrence({"type": "cron", "day_of_season": day, "hour": 8,
                      "minute": 0}, "Y0002-D109T14:00:00"), expected)

# ── [e] job migration of the old real-date fields ───────────────────────
print("[e] migrate_cron_fields: day/month/day_of_week → world calendar")
migrated, changed = migrate_cron_fields({"day": 15, "month": 2,
                                         "day_of_week": 3}, DEFAULT_CAL)
check("migrated trigger", migrated, {"day_of_season": 15, "season": "summer"})
check("changed", changed, True)
check("idempotent (second run is a no-op)",
      migrate_cron_fields(migrated, DEFAULT_CAL), (migrated, False))
check("a trigger without old fields is untouched",
      migrate_cron_fields({"type": "cron", "hour": 8}, DEFAULT_CAL),
      ({"type": "cron", "hour": 8}, False))
check("with weeks, day_of_week survives as weekday",
      migrate_cron_fields({"day_of_week": 3}, WEEK_CAL), ({"weekday": 3}, True))
check("day is clamped to the shortest season without a season field",
      migrate_cron_fields({"day": 99}, DEFAULT_CAL),
      ({"day_of_season": 30}, True))

# ── [f] interval dueness off a canonical anchor ─────────────────────────
print("[f] interval job, period 3600 s, anchor Y0002-D109T08:00:00")
JOB = {"id": "smoke_interval", "trigger": {"type": "interval", "seconds": 3600},
       "_registered_game": "Y0002-D109T08:00:00"}
for now_str, expected in (("Y0002-D109T08:59:59", False),
                          ("Y0002-D109T09:00:00", True)):
    sm_mod.game_time = lambda s=now_str: GameTime.parse(s)
    check(f"now {now_str}", MANAGER._job_due(JOB), expected)

print("[f2] cron job dueness against the anchor + catch-up window")
CRON_JOB = {"id": "smoke_cron", "trigger": DAILY,
            "_registered_game": "Y0002-D109T08:00:00"}
sm_mod.game_time = lambda: GameTime.parse("Y0002-D109T14:00:00")
check("occurrence == anchor → already covered",
      MANAGER._job_due(CRON_JOB), False)
sm_mod.game_time = lambda: GameTime.parse("Y0002-D110T09:00:00")
check("next day's 08:00 is due", MANAGER._job_due(CRON_JOB), True)
sm_mod.game_time = lambda: GameTime.parse("Y0002-D115T09:00:00")
check("… but an occurrence older than 3 game days is skipped",
      MANAGER._job_due({"id": "smoke_cron_stale", "trigger": WINTER19,
                        "_registered_game": "Y0002-D100T00:00:00"}),
      False)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
