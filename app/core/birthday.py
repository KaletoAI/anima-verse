"""Birthdays — one day of the WORLD calendar, once per world year.

A birthday is stored on the character profile as ``birthday``, the string
``"<season_key>:<day>"`` that :mod:`app.core.game_time` owns
(``parse_season_day`` / ``is_season_day``). There is no year in it and no real
date anywhere: the day comes round once per world year, and a value the
calendar no longer knows (season deleted or shortened) is simply "no birthday".

Two things happen on the day, and nothing else:

* **The character knows it.** The prompt data builders set ``birthday_today``
  (see ``system_prompt_builder.load_prompt_data``, ``thought_context`` and the
  chat situation block) — that is a pure read of the profile and needs no
  bookkeeping here.
* **The world knows it.** :func:`run_birthday_sweep` writes ONE global event
  plus one notification to the character itself, once per GAME day.

Deliberately absent: the age is never written. ``age`` stays the hand-kept
number it has always been — a birthday is an occasion, not a bookkeeper.

Why the event is GLOBAL (``location_id=None``): everyone in the world should
be able to congratulate, including whoever lives on the other side of the map.
A location-bound event would leave the news behind the moment the character
walks out of the room.

The sweep runs as a sub-task of the world-admin tick
(``app/core/periodic_jobs.py``). Two world states matter:

* **Frozen** (``world_frozen``): the tick loop skips EVERY sub-task while the
  world is frozen (``periodic_jobs._is_paused``), so the sweep is off with the
  rest of the autonomous simulation — exactly like the random events, the NPC
  ticks and the day consolidation. Nothing is gated a second time here.
* **Sleeping** (``world_sleeping``): the sweep keeps running, like every other
  sub-task (only the agent loop and the Telegram poll stand down while the
  world sleeps). The game clock runs during sleep, so the day really does
  happen; gating the sweep would swallow a birthday whose whole day fell into
  one long night, and the guard below would not offer it again until the next
  world year. The event and the notification simply wait for the world to wake.
"""
from typing import Any, Dict, Optional

from app.core.db import get_connection, transaction
from app.core.game_time import GameTime, is_season_day, parse_season_day
from app.core.log import get_logger

logger = get_logger("birthday")

#: The happening is a social one, and it lasts the whole world day.
EVENT_CATEGORY = "social"
EVENT_TTL_GAME_HOURS = 24
#: Notification kind — the birthday child's own line in the notification list.
NOTIFICATION_KIND = "birthday"
#: world_kv guard, ``birthday_done:<name>`` -> the GAME day key it last fired
#: on. Same shape as ``day_cursor:<name>`` in the day consolidation.
GUARD_PREFIX = "birthday_done:"


# --- world_kv (key/value) ---------------------------------------------------

def _kv_get(key: str) -> str:
    try:
        row = get_connection().execute(
            "SELECT value FROM world_kv WHERE key=?", (key,)).fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        return ""


def _kv_set(key: str, value: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO world_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
    except Exception as e:
        logger.debug("kv_set %s failed: %s", key, e)


# --- The day ----------------------------------------------------------------

def is_birthday_today(profile: Optional[Dict[str, Any]],
                      now: Optional[GameTime] = None) -> bool:
    """Whether this profile's ``birthday`` falls on the current GAME day.

    Tolerant by design: a missing, empty or no-longer-valid field is simply
    "no birthday" — never an error and never a repaired value.
    """
    if not profile:
        return False
    parsed = parse_season_day(profile.get("birthday"))
    if not parsed:
        return False
    if now is None:
        from app.core.timeutils import game_time
        now = game_time()
    return is_season_day(now, parsed[0], parsed[1])


def run_birthday_sweep() -> int:
    """Announce every birthday that falls on the current GAME day.

    Returns how many characters were announced in this run. Idempotent per
    GAME day through the ``birthday_done:<name>`` guard: the sweep runs far
    more often than once a day, and fires at most once. The guard holds the
    day KEY, not a flag, so the same birthday fires again next world year.
    """
    from app.core.i18n import t
    from app.core.timeutils import game_time
    from app.models.character import (get_character_language,
                                      get_character_profile,
                                      list_available_characters)
    from app.models.events import add_event
    from app.models.notifications import create_notification

    now = game_time()
    day = now.day_key()
    fired = 0
    for name in list_available_characters():
        try:
            profile = get_character_profile(name)
        except Exception as e:
            logger.debug("birthday: profile %s unreadable: %s", name, e)
            continue
        if not is_birthday_today(profile, now):
            continue
        guard = f"{GUARD_PREFIX}{name}"
        if _kv_get(guard) == day:
            continue
        lang = get_character_language(name) or "de"
        text = t("Today is {name}'s birthday.", lang).format(name=name)
        try:
            # The event goes out FIRST and the guard only afterwards: a write
            # that fails leaves the day unmarked and the next run retries,
            # which is the better half of the trade — a birthday that is
            # silently skipped cannot be noticed until the next world year.
            add_event(text, location_id=None, ttl_hours=EVENT_TTL_GAME_HOURS,
                      category=EVENT_CATEGORY, metadata={"birthday_of": name})
            create_notification(name, text, NOTIFICATION_KIND,
                                metadata={"birthday_of": name})
        except Exception as e:
            logger.error("birthday sweep for %s failed: %s", name, e)
            continue
        _kv_set(guard, day)
        fired += 1
        logger.info("birthday: %s (%s)", name, day)
    return fired
