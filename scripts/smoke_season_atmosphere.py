#!/usr/bin/env python3
"""Smoke run for the SEASON atmosphere (temperature / weather / note) and the
one-time move of the old world-wide atmosphere onto the seasons.

Runs WITHOUT a server: a throwaway world (config.json + SQLite world.db) is
created in a temp directory via ``paths.init`` + ``db.init_schema`` + a
``config.load`` against THAT path, and the game clock is pinned (factor 0) so
nothing here reads the wall clock or touches ``worlds/``.

Rules every expectation below is derived from BY HAND:

  * The atmosphere belongs to the SEASON, not to the world: a
    :class:`~app.core.game_time.Season` carries ``temperature`` (one of
    freezing / cold / mild / hot), ``weather`` (dry / rain / snow) and a free
    ``weather_note``. There is no world-level temperature/weather any more.
  * ``Calendar.default()`` ships 4 seasons × 30 days with
    spring mild/rain · summer hot/dry · autumn cold/rain · winter
    freezing/snow, so the season starts are (0, 30, 60, 90) and winter owns
    the days 91..120 of a 120-day year.
  * A world without a ``game_seasons`` section gets that default list
    MATERIALIZED into the config in memory at load time (nothing written) —
    what the admin page lists is then what the calendar actually runs on.
  * ``GameTime.atmosphere()`` returns
    ``{season, temperature, weather, note, label}``; the label is
    ``"<temperature>, <weather>"`` plus ``" — <note>"`` when a note is set.
  * ``Calendar.from_config`` is tolerant: an unknown level falls back to the
    shipped default (``mild`` / ``dry``), it never raises.

Hand-derived expectations:

  [1] Materialized defaults on a config-less world
        config.get("game_seasons") has 4 entries, in the shipped order
        spring / summer / autumn / winter; the 4th reads
        temperature "freezing", weather "snow", weather_note ""
        config.get("game_calendar") = the schema defaults
        (week_days "", year_label "Year {n}", noon 12, evening 17)
        get_calendar() == Calendar.default()

  [2] atmosphere() picks the season the instant falls into
        "Y0002-D109T14:00:00" → day_index = (2−1)·120 + 109 − 1 = 228
          → doy0 = 228 mod 120 = 108; 108 ≥ 90 → season index 3 = winter
        → {"season": "winter", "temperature": "freezing",
           "weather": "snow", "note": "", "label": "freezing, snow"}
        "Y0002-D001T12:00:00" → doy0 = 0 → spring → "mild, rain"
        to_dict()["atmosphere"] is the same dict.

  [3] The note is passed through raw and only joined into the label
        winter note "often fog in the morning"
        → note  = "often fog in the morning"
        → label = "freezing, snow — often fog in the morning"

  [4] Unknown levels fall back, they do not raise
        temperature "tropical" → "mild", weather "hail" → "dry",
        weather_note 42 (not a string) → ""

  [5] Migration ``atmosphere`` (world_kv → per-season config)
        world_kv holds world.temperature "mild" and world.weather "rain";
        the season list is the materialized default, i.e. NO season has an
        own value → all 4 seasons end up mild/rain, the config file on disk
        now carries them, and both world_kv keys are gone.
        The counter counts fields that ACTUALLY changed, so from the shipped
        defaults (spring mild/rain · summer hot/dry · autumn cold/rain ·
        winter freezing/snow) towards mild/rain that is
        0 (spring, both already right) + 2 (summer) + 1 (autumn, rain stays)
        + 2 (winter) = 5.
        A SECOND run finds no keys → stats["atmosphere"] == 0 and the
        seasons are untouched (idempotence).

Usage:  ./.venv/bin/python scripts/smoke_season_atmosphere.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="season-atmosphere-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="season-atmosphere-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
db.init_schema()

from app.core.game_calendar_migration import (  # noqa: E402
    migrate_game_calendar_once)
from app.core.game_time import (  # noqa: E402
    Calendar, GameTime, calendar_to_dict, get_calendar,
    invalidate_calendar_cache)
from app.core.db import get_connection  # noqa: E402
from app.models.world import set_world_setting  # noqa: E402

FAILURES = []
CHECKED = 0

WINTER_DAY = "Y0002-D109T14:00:00"     # winter, day 19 of year 2
SPRING_DAY = "Y0002-D001T12:00:00"     # spring, day 1 of year 2


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
    """Freeze the game clock at the winter instant (factor 0 = no drift)."""
    from app.core import timeutils
    set_world_setting(timeutils._KEY_ANCHOR_GAME, WINTER_DAY)
    set_world_setting(timeutils._KEY_ANCHOR_REAL,
                      timeutils.utc_now().isoformat(timespec="seconds"))
    set_world_setting(timeutils._KEY_FACTOR, "0")
    timeutils.invalidate_game_clock_cache()


def case_1_materialized_defaults():
    print("[1] Defaults materialized into a config-less world")
    config.load(paths.get_config_path())
    seasons = config.get("game_seasons")
    check("season count", len(seasons), 4)
    check("season keys", [s["key"] for s in seasons],
          ["spring", "summer", "autumn", "winter"])
    check("winter temperature", seasons[3]["temperature"], "freezing")
    check("winter weather", seasons[3]["weather"], "snow")
    check("winter note", seasons[3]["weather_note"], "")
    check("spring atmosphere", (seasons[0]["temperature"], seasons[0]["weather"]),
          ("mild", "rain"))
    check("summer atmosphere", (seasons[1]["temperature"], seasons[1]["weather"]),
          ("hot", "dry"))
    check("autumn atmosphere", (seasons[2]["temperature"], seasons[2]["weather"]),
          ("cold", "rain"))
    check("game_calendar", config.get("game_calendar"),
          {"week_days": "", "year_label": "Year {n}",
           "day_bucket_noon": 12, "day_bucket_evening": 17})
    check_true("calendar equals Calendar.default()",
               get_calendar() == Calendar.default())
    check_true("flagged as shipped defaults", config.game_seasons_are_defaults())


def case_2_atmosphere_by_season():
    print("[2] atmosphere() resolves the season of the instant")
    winter = GameTime.parse(WINTER_DAY)
    check("winter season", winter.season, "winter")
    check("winter atmosphere", winter.atmosphere(),
          {"season": "winter", "temperature": "freezing", "weather": "snow",
           "note": "", "label": "freezing, snow"})
    spring = GameTime.parse(SPRING_DAY)
    check("spring atmosphere", spring.atmosphere(),
          {"season": "spring", "temperature": "mild", "weather": "rain",
           "note": "", "label": "mild, rain"})
    check("to_dict carries it", winter.to_dict()["atmosphere"],
          winter.atmosphere())


def case_3_note_passed_through():
    print("[3] The weather note reaches the label verbatim")
    note = "often fog in the morning"
    cal = Calendar.from_config(
        None,
        [{"key": "winter", "name": "Winter", "days": 30,
          "temperature": "freezing", "weather": "snow", "weather_note": note}])
    atmo = GameTime.parse("Y0001-D001T09:00:00").atmosphere(calendar=cal)
    check("note", atmo["note"], note)
    check("label", atmo["label"], f"freezing, snow — {note}")
    payload = calendar_to_dict(cal)["seasons"][0]
    check("calendar payload note", payload["weather_note"], note)
    check("calendar payload levels",
          (payload["temperature"], payload["weather"]), ("freezing", "snow"))


def case_4_unknown_levels_fall_back():
    print("[4] Unknown levels fall back instead of raising")
    cal = Calendar.from_config(
        None,
        [{"key": "odd", "name": "Odd", "days": 10,
          "temperature": "tropical", "weather": "hail", "weather_note": 42}])
    season = cal.seasons[0]
    check("temperature", season.temperature, "mild")
    check("weather", season.weather, "dry")
    check("note", season.weather_note, "")


def _season_atmospheres():
    return [(s.get("key"), s.get("temperature"), s.get("weather"))
            for s in config.get("game_seasons")]


def _world_kv_atmosphere_keys():
    rows = get_connection().execute(
        "SELECT key FROM world_kv WHERE key IN ('world.temperature','world.weather')"
    ).fetchall()
    return sorted(r[0] for r in rows)


def case_5_migration():
    print("[5] Migration: world-wide atmosphere → every season")
    invalidate_calendar_cache()
    config.load(paths.get_config_path())
    pin_clock()
    set_world_setting("world.temperature", "mild")
    set_world_setting("world.weather", "rain")
    check("world_kv seeded", _world_kv_atmosphere_keys(),
          ["world.temperature", "world.weather"])

    stats = migrate_game_calendar_once()
    check("changed fields counted", stats["atmosphere"], 5)
    check("all seasons mild/rain", _season_atmospheres(),
          [("spring", "mild", "rain"), ("summer", "mild", "rain"),
           ("autumn", "mild", "rain"), ("winter", "mild", "rain")])
    check("world_kv keys removed", _world_kv_atmosphere_keys(), [])

    on_disk = json.loads(paths.get_config_path().read_text(encoding="utf-8"))
    check("persisted to config.json",
          [(s["key"], s["temperature"], s["weather"])
           for s in on_disk["game_seasons"]],
          [("spring", "mild", "rain"), ("summer", "mild", "rain"),
           ("autumn", "mild", "rain"), ("winter", "mild", "rain")])
    invalidate_calendar_cache()
    check("calendar reads the new values",
          GameTime.parse(WINTER_DAY).atmosphere()["label"], "mild, rain")

    stats2 = migrate_game_calendar_once()
    check("second run changes nothing", stats2["atmosphere"], 0)
    check("seasons unchanged", _season_atmospheres(),
          [("spring", "mild", "rain"), ("summer", "mild", "rain"),
           ("autumn", "mild", "rain"), ("winter", "mild", "rain")])


def main():
    print(f"Throwaway world: {STORAGE}")
    case_1_materialized_defaults()
    case_2_atmosphere_by_season()
    case_3_note_passed_through()
    case_4_unknown_levels_fall_back()
    case_5_migration()
    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKED}: {', '.join(FAILURES)}")
        return 1
    print(f"All {CHECKED} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
