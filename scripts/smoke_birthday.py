#!/usr/bin/env python3
"""Smoke: a birthday as a day of the WORLD calendar (plan-geburtstag-spielkalender.md).

A birthday is ``"<season_key>:<day>"`` on the character profile — a season plus
the day within it, no year, no real date. Everything below is derived by hand
from the DEFAULT calendar, which ``Calendar.default()`` fixes as four seasons
of 30 days each with the keys/names spring/Spring, summer/Summer,
autumn/Autumn, winter/Winter (``game_time.py`` ``_DEFAULT_SEASONS``). The clock
is frozen (``set_game_factor(0.0)`` + ``set_game_time``) so every expectation
is a statement about one named game day, never about the machine's clock.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) THE PARSER, ``parse_season_day``. Summer is 30 days long, so day 1 and
      day 30 are inside it and 0 and 31 are not. The day is split off from the
      RIGHT, so a season key that itself contains a colon still parses — the
      case is built with a hand-made calendar whose season key is "a:b".
      Everything unusable (unknown key, no colon, digits only, empty, None,
      a non-string) is "no day", never an error.

  (b) THE LABEL, ``season_day_label``: "Summer, day 14" — the head of the full
      game-time label, without weekday, clock or year.

  (c) THE DAY ITSELF, ``is_season_day``. Day-of-year arithmetic, by hand from
      4 x 30:
          spring = days   1..30      summer = days  31..60
          autumn = days  61..90      winter = days  91..120
      So D044 = 44 - 30 = summer, day 14 — the day this whole smoke uses. The
      season borders are checked at both ends: D031 = summer 1, D060 = summer
      30, D061 = autumn 1, and D001 of year 1 = spring 1. The test is
      year-agnostic by design, which is why (f) repeats the sweep a year later.

  (d) THE SWEEP, ``run_birthday_sweep``. On D044 the character with
      ``birthday = "summer:14"`` gets exactly ONE event and ONE notification:
          * event: global (``location_id`` None), category "social",
            ``metadata.birthday_of`` = the name, text
            "Today is <name>'s birthday." (the character's language is "en",
            so ``t()`` hands back the English source string unchanged)
          * notification: type "birthday", on the birthday character itself
      The second character has no ``birthday`` field at all and gets nothing.

  (e) IDEMPOTENCE. A second sweep on the same game day writes nothing — the
      world_kv guard ``birthday_done:<name>`` holds D044's day key. The sweep
      runs every five minutes in production, so this is the whole difference
      between one greeting and 288 of them.

      On D045T12:00 the sweep is silent as well (wrong day), and the event of
      D044 is gone: it was created at D044T10:00 and runs to the END of D044
      (see (i)), i.e. it ran out at D045T00:00. The notification stays —
      notifications do not expire.

  (f) THE NEXT WORLD YEAR. At Y0003-D044 the very same character fires again:
      the guard holds a day KEY, not a "done" flag.

  (g) THE PROMPT. ``birthday_today`` is True on the day and False the day
      after, in BOTH data builders (``load_prompt_data`` and
      ``build_thought_context``) — always set, because the thought templates
      gate on it and StrictUndefined would raise on a missing key. Rendering
      ``chat/agent_thought.md`` therefore contains the line
      "- Today is your birthday." on D044 and not on D045.

      The STANDING line is not built by any of that: the character template
      carries ``prompt_format: "season_day"``, so ``build_prompt_section``
      renders "Birthday: Summer, day 14" generically — exactly once.

  (h) THE TEARDOWN of the system-calendar age computation (round 1):
      ``character_template`` has no ``_compute_age`` any more, and a template
      field asking for the old hooks is inert — ``prompt_compute: "age"``
      renders the raw value, ``replacement.compute: "age"`` passes the raw
      value through. No shim, no fallback.

  (i) THE LIFE SPAN OF THE ANNOUNCEMENT, ``birthday.event_ttl_hours``. The
      event says "Today is X's birthday.", so it has to end WITH the day — not
      24 hours after the sweep happened to notice. The sweep has no fixed
      hour: it fires on the first tick after the world is unfrozen, and the
      game clock is settable, so it can land on any second of the day. The TTL
      is therefore the REST of the day, taken in seconds and handed over as
      fractional GAME hours. By hand, against a 24 h = 86400 s day:

          sweep at 22:00  -> 79200 s gone, 86400 - 79200 = 7200 s = 2.0 h
                             -> alive at D044T23:59, gone at D045T01:00
                                (a flat 24 h would have held it to D045T22:00)
          sweep at 23:50  -> 85800 s gone, 86400 - 85800 =  600 s = 600/3600 h
                             -> alive at D044T23:55, gone at D045T00:05
                                (a whole-hour "24 - hour" would grant 1 h and
                                 overrun midnight by 50 minutes)

      The day checked in (d) is the same rule at 10:00: 86400 - 36000 =
      50400 s = 14.0 h. Years 4 and 5 are used so the per-day guard of (e) is
      out of the way; the birthday key comes round every world year anyway.

Usage:  ./.venv/bin/python scripts/smoke_birthday.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="birthday-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="birthday-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
from app.core import game_time as gt  # noqa: E402
from app.core.birthday import run_birthday_sweep  # noqa: E402
from app.core.game_time import (Calendar, GameTime, Season,  # noqa: E402
                                is_season_day, parse_season_day,
                                season_day_label)
from app.core.prompt_templates import render  # noqa: E402
from app.core.system_prompt_builder import load_prompt_data  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.thought_context import build_thought_context  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import character_template as ct  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.events import get_all_events  # noqa: E402
from app.models.notifications import get_notifications  # noqa: E402

# Offline: no embedding model is downloaded for the pose catalog.
embedding.embed = lambda text: None

# No worker threads in a smoke — nothing here executes a queued task.
get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


BDAY = "Tessa"
OTHER = "Bram"
# Derived in the docstring: 30 spring days + 14 = day-of-year 44.
DAY_OF_YEAR = 44


def at(year, day_of_year, hour=10, minute=0):
    """Freeze the clock on a named game day."""
    set_game_factor(0.0)
    set_game_time(GameTime.from_parts(year, day_of_year, hour, minute, 0))


def birthday_events():
    return [e for e in get_all_events()
            if (e.get("metadata") or {}).get("birthday_of") == BDAY]


def birthday_notifications():
    return [n for n in get_notifications(limit=200)
            if n.get("type") == "birthday"]


# --- (a) the parser ---------------------------------------------------------
print("\n(a) parse_season_day — summer is 30 days long")
check("summer:14", parse_season_day("summer:14"), ("summer", 14))
check("first day of the season", parse_season_day("summer:1"), ("summer", 1))
check("last day of the season", parse_season_day("summer:30"), ("summer", 30))
check("one day past the season", parse_season_day("summer:31"), None)
check("day zero", parse_season_day("summer:0"), None)
check("unknown season key", parse_season_day("monsoon:3"), None)
check("no colon", parse_season_day("summer"), None)
check("digits only", parse_season_day("14"), None)
check("empty", parse_season_day(""), None)
check("None", parse_season_day(None), None)
check("not a string", parse_season_day(14), None)
# The key is everything LEFT of the last colon, so a colon inside the key
# survives — shown against a calendar that actually has such a key.
_colon_cal = Calendar(seasons=(Season(key="a:b", name="Odd", days=10),),
                      week_days=(), year_label="Year", noon_hour=12,
                      evening_hour=18)
check("a key containing a colon", parse_season_day("a:b:5", _colon_cal),
      ("a:b", 5))

# --- (b) the label ----------------------------------------------------------
print("\n(b) season_day_label")
check("summer day 14", season_day_label("summer", 14, "en"), "Summer, day 14")
check("unknown key -> no line", season_day_label("monsoon", 3, "en"), "")

# --- (c) the day ------------------------------------------------------------
print("\n(c) is_season_day — 4 seasons x 30 days")
_d044 = GameTime.from_parts(2, DAY_OF_YEAR, 10, 0, 0)
check("D044 is summer 14", is_season_day(_d044, "summer", 14), True)
check("D044 is not summer 13", is_season_day(_d044, "summer", 13), False)
check("D044 is not spring 14", is_season_day(_d044, "spring", 14), False)
check("D031 is summer 1",
      is_season_day(GameTime.from_parts(2, 31), "summer", 1), True)
check("D031 is not spring 31",
      is_season_day(GameTime.from_parts(2, 31), "spring", 31), False)
check("D060 is summer 30",
      is_season_day(GameTime.from_parts(2, 60), "summer", 30), True)
check("D061 is autumn 1",
      is_season_day(GameTime.from_parts(2, 61), "autumn", 1), True)
check("D061 is not summer 31",
      is_season_day(GameTime.from_parts(2, 61), "summer", 31), False)
check("Y0001-D001 is spring 1",
      is_season_day(GameTime.from_parts(1, 1), "spring", 1), True)

# --- (d) the sweep ----------------------------------------------------------
print("\n(d) the sweep on the day itself")
at(2, DAY_OF_YEAR)
save_character_profile(BDAY, {"character_name": BDAY,
                              "template": "human-roleplay",
                              "language": "en",
                              "birthday": "summer:14"}, create_new=True)
save_character_profile(OTHER, {"character_name": OTHER,
                               "template": "human-roleplay",
                               "language": "en"}, create_new=True)
check("the sweep announces one character", run_birthday_sweep(), 1)
_events = birthday_events()
check("one global birthday event", len(_events), 1)
if _events:
    check("the event is global", _events[0].get("location_id"), None)
    check("the event is social", _events[0].get("category"), "social")
    check("the event lasts to the end of the day",
          _events[0].get("ttl_hours"), 14.0)
    check("the event names the character", _events[0].get("text"),
          f"Today is {BDAY}'s birthday.")
_notes = birthday_notifications()
check("one notification", len(_notes), 1)
if _notes:
    check("it goes to the birthday character", _notes[0].get("character"), BDAY)
    check("its text is the same sentence", _notes[0].get("content"),
          f"Today is {BDAY}'s birthday.")
check("nothing for the character without a birthday",
      [n for n in get_notifications(limit=200)
       if n.get("character") == OTHER], [])

# --- (e) idempotence --------------------------------------------------------
print("\n(e) the same game day, again")
check("the second sweep is silent", run_birthday_sweep(), 0)
check("still one event", len(birthday_events()), 1)
check("still one notification", len(birthday_notifications()), 1)

print("\n(e) the day after — wrong day, and the event has run out")
at(2, DAY_OF_YEAR + 1, hour=12)
check("the sweep is silent", run_birthday_sweep(), 0)
check("the event ended with its day", len(birthday_events()), 0)
check("the notification stays", len(birthday_notifications()), 1)

# --- (f) the next world year ------------------------------------------------
print("\n(f) the next world year")
at(3, DAY_OF_YEAR)
check("the birthday comes round again", run_birthday_sweep(), 1)
check("one live event again", len(birthday_events()), 1)
check("two notifications now", len(birthday_notifications()), 2)

# --- (g) the prompt ---------------------------------------------------------
print("\n(g) the prompt")
check("load_prompt_data on the day",
      load_prompt_data(BDAY, set()).get("birthday_today"), True)
check("load_prompt_data for the other character",
      load_prompt_data(OTHER, set()).get("birthday_today"), False)
_ctx = build_thought_context(BDAY)
check("thought context on the day", _ctx.get("birthday_today"), True)
check("the thought prompt says it",
      "- Today is your birthday." in render("chat/agent_thought.md", **_ctx),
      True)
check("the in-chat thought prompt says it too",
      "- Today is your birthday." in render("chat/agent_thought_in_chat.md",
                                            **_ctx), True)
at(3, DAY_OF_YEAR + 1)
check("load_prompt_data the day after",
      load_prompt_data(BDAY, set()).get("birthday_today"), False)
_ctx_after = build_thought_context(BDAY)
check("thought context the day after", _ctx_after.get("birthday_today"), False)
check("and the thought prompt is quiet",
      "- Today is your birthday." in render("chat/agent_thought.md",
                                            **_ctx_after), False)

print("\n(g) the standing line comes from the character template")
_tpl = ct.get_template("human-roleplay")
_lines = ct.build_prompt_section(_tpl, {"character_name": BDAY,
                                        "birthday": "summer:14"},
                                 character_name=BDAY)
check("Birthday: Summer, day 14, exactly once",
      _lines.count("Birthday: Summer, day 14"), 1)
_lines_empty = ct.build_prompt_section(_tpl, {"character_name": OTHER},
                                       character_name=OTHER)
check("no line without a birthday",
      [ln for ln in _lines_empty if ln.startswith("Birthday")], [])
_lines_stale = ct.build_prompt_section(_tpl, {"character_name": BDAY,
                                              "birthday": "monsoon:3"},
                                       character_name=BDAY)
check("no line for a season the calendar lost",
      [ln for ln in _lines_stale if ln.startswith("Birthday")], [])

# --- (h) the teardown of the system-calendar age ----------------------------
print("\n(h) the system-calendar age computation is gone")
check("no _compute_age left", hasattr(ct, "_compute_age"), False)
_age_tpl = {"sections": [{"key": "identity", "fields": [
    {"key": "age", "label": "Age", "in_prompt": True,
     "prompt_label": "Age", "prompt_compute": "age"},
    {"key": "born", "label": "Born",
     "replacement": {"target": "character_appearance", "token": "age",
                     "compute": "age"}},
]}]}
check("prompt_compute 'age' renders the raw value",
      ct.build_prompt_section(_age_tpl, {"age": "1999-04-02"}),
      ["Age: 1999-04-02"])
check("replacement compute 'age' passes the raw value through",
      ct.build_replacement_map(_age_tpl, {"born": "1999-04-02"},
                               "character_appearance"),
      {"age": "1999-04-02"})

# --- (i) a LATE sweep — the event ends at midnight, not 24h later -----------
print("\n(i) a late sweep — the announcement ends with its own day")
at(4, DAY_OF_YEAR, hour=22)
check("the birthday fires in year 4", run_birthday_sweep(), 1)
_late = birthday_events()
check("one live event", len(_late), 1)
if _late:
    # 22:00 -> 79200 s of the day gone, 86400 - 79200 = 7200 s = 2.0 hours.
    check("two game hours left of the day", _late[0].get("ttl_hours"), 2.0)
at(4, DAY_OF_YEAR, hour=23, minute=59)
check("still standing at 23:59 of its own day", len(birthday_events()), 1)
at(4, DAY_OF_YEAR + 1, hour=1)
check("gone at 01:00 the next day", len(birthday_events()), 0)

print("\n(i) the last ten minutes — the minute counts, not just the hour")
at(5, DAY_OF_YEAR, hour=23, minute=50)
check("the birthday fires in year 5", run_birthday_sweep(), 1)
_tail = birthday_events()
check("one live event", len(_tail), 1)
if _tail:
    # 23:50 -> 85800 s gone, 86400 - 85800 = 600 s = 600/3600 h (10 minutes).
    check("ten game minutes left of the day",
          _tail[0].get("ttl_hours"), 600 / 3600)
at(5, DAY_OF_YEAR, hour=23, minute=55)
check("still standing five minutes before midnight",
      len(birthday_events()), 1)
at(5, DAY_OF_YEAR + 1, hour=0, minute=5)
check("gone five minutes after midnight", len(birthday_events()), 0)

# The demo world is tracked in git — a smoke that touched it would show up as
# a diff. Everything above lives in the temp storage created at import time.
check("the smoke writes into its own temp storage",
      str(paths.get_storage_dir()), str(STORAGE))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
