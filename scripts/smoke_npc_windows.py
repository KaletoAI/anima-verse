#!/usr/bin/env python3
"""Smoke: the time window of an NPC slot (spec-npc-heimat-zeitfenster § E2).

A slot may carry a ``when``: empty = always, ``night``/``day`` = the season's
sun, or a literal ``HH:MM-HH:MM`` span in GAME time. Outside its window a slot
wants nobody (no spawn) and the NPCs standing in it go back into the pool.

WHAT IS CHECKED, and where every expected number comes from
-----------------------------------------------------------

The throwaway world runs a hand-written two-season calendar so the sun times
are known exactly and are NOT the shipped defaults (06:00/18:00) — a passing
run therefore proves the decision follows the SEASON, not a constant:

    season "shortday" (days 1-10):  sunrise 08:00 = 480 min, sunset 16:00 = 960
    season "longday"  (days 11-20): sunrise 04:00 = 240 min, sunset 22:00 = 1320

The clock is frozen (``set_game_factor(0.0)`` + ``set_game_time``), so every
minute below is exact.

  (a) THE WINDOW MATRIX, derived by hand from the rule
      ``from <= to`` → open iff ``from <= m < to`` (half-open);
      ``from >  to`` → open iff ``m >= from or m < to`` (spans midnight);
      with ``m = now.minutes_of_day``.

        ""            → open at every minute (no condition at all).
        "22:00-05:00" (1320 > 300, wraps): 23:00 = 1380 ≥ 1320 → open;
                       12:00 = 720 → neither ≥ 1320 nor < 300 → closed;
                       04:59 = 299 < 300 → open; 05:00 = 300 → closed
                       (the END is exclusive); 22:00 = 1320 ≥ 1320 → open
                       (the START is inclusive).
        "08:00-12:00" (480 < 720): 07:59 = 479 → closed; 08:00 = 480 → open;
                       11:59 = 719 → open; 12:00 = 720 → closed.
        "night" = ``is_night(now)`` = NOT (sunrise ≤ m < sunset). In
                       "shortday": 07:59 = 479 < 480 → night; 08:00 → day;
                       15:59 = 959 < 960 → day; 16:00 = 960 → night.
        "day"   = the exact complement of it at the same minutes.
        THE SEASON DECIDES: 07:00 = 420 is NIGHT in "shortday" (420 < 480) and
                       DAY in "longday" (240 ≤ 420 < 1320) — same minute of
                       day, opposite answer.
        ``parse_window`` returns ``None`` for anything that is not a real
        span ("25:00-01:00", "night", "junk"), and ``normalize_slot`` turns an
        unusable ``when`` into "" (= always) instead of a dead slot.

  (b) A CLOSED SLOT WANTS NOBODY. ``missing_slots`` with a slot
      ``when="22:00-05:00"`` and nobody there: at 12:00 the list is empty, at
      23:00 it reports the gap. Same location, same (empty) roster — only the
      clock differs. Without the ``now`` argument the game clock decides.

  (c) A CLOSED WINDOW SENDS THE NPCs HOME. ``sweep_closed_windows()`` pools
      the living NPCs of a slot whose window has closed —
      ``npc_slot_location`` + ``npc_slot_role`` resolve the slot, so it is the
      TAG that decides, never a name. Four cases, one clock (11:00 = 660, so
      the "22:00-05:00" slot is shut and the "08:00-12:00" one is open):

        * a slot NPC of the closed slot → status ``pooled``, reason
          "window closed";
        * the same NPC with a chat line from an AVATAR stamped NOW → stays.
          The player is mid-sentence; the same rule the action tick uses
          (``npc_actions._in_chat``);
        * an NPC of a slot whose window is OPEN (``"08:00-12:00"`` at 11:00)
          → stays;
        * a WANDERER carrying a slot stamp → never. It does not live at that
          place, it travels through; its lifetime is the TTL sweep's business.

  (d) THE NIGHT/DAY EXTRACTION IS BEHAVIOUR-PRESERVING. The rule condition
      ``night``/``day`` (``activity_engine.evaluate_condition``) now asks the
      SAME ``npc_windows.is_night`` — the ± minute offset stays in
      ``activity_engine``, on the same sunrise/sunset basis. Hand-derived in
      "shortday" (sunrise 480, sunset 960):

        night      window [960, 480) wrapping: 959 → False, 960 → True,
                   479 → True, 480 → False.
        night-30   start 30 min EARLIER = 930: 929 → False, 935 → True.
        night+30   start 30 min LATER  = 990: 970 → False, 995 → True.
        day        window [480, 960):  479 → False, 480 → True, 959 → True,
                   960 → False.
        day-30     start 450: 455 → True, 449 → False.
        day+30     start 510: 500 → False, 510 → True.

      These values are what the code produced BEFORE the extraction as well —
      that is the point of the case.

Usage:  ./.venv/bin/python scripts/smoke_npc_windows.py
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcwindows-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcwindows-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import activity_engine, embedding, npc_ops, npc_spawn  # noqa: E402
from app.core import npc_windows  # noqa: E402
from app.core.game_time import GameTime, get_calendar  # noqa: E402
from app.core.game_time import invalidate_calendar_cache  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.timeutils import (set_game_factor, set_game_time,  # noqa: E402
                                utc_now)
from app.core.users import create_user, update_user  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  get_character_status,
                                  save_character_profile)

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


# ── the calendar: two seasons with KNOWN, non-default sun times ─────────────

_cfg = config.get_all()
_cfg["game_seasons"] = [
    {"key": "shortday", "name": "Shortday", "days": 10,
     "sunrise": "08:00", "sunset": "16:00"},
    {"key": "longday", "name": "Longday", "days": 10,
     "sunrise": "04:00", "sunset": "22:00"},
]
config.save(_cfg, STORAGE / "config.json")
invalidate_calendar_cache()

_CAL = get_calendar()
check("the throwaway calendar's shortday sun",
      (_CAL.seasons[0].key, _CAL.seasons[0].sunrise_min,
       _CAL.seasons[0].sunset_min), ("shortday", 480, 960))
check("the throwaway calendar's longday sun",
      (_CAL.seasons[1].key, _CAL.seasons[1].sunrise_min,
       _CAL.seasons[1].sunset_min), ("longday", 240, 1320))

set_game_factor(0.0)


def at(hour: int, minute: int = 0, season: str = "shortday") -> GameTime:
    """A frozen game instant on day 1 of ``season``."""
    return GameTime.from_season(1, season, 1, hour, minute)


# ---------------------------------------------------------------------------
print("\n(a) the window matrix")

check("no window is always open",
      [npc_windows.slot_window_open("", at(h)) for h in (0, 6, 12, 18, 23)],
      [True] * 5)

WRAP = "22:00-05:00"
check("wrapping window at 23:00", npc_windows.slot_window_open(WRAP, at(23)), True)
check("wrapping window at 12:00", npc_windows.slot_window_open(WRAP, at(12)), False)
check("wrapping window at 04:59",
      npc_windows.slot_window_open(WRAP, at(4, 59)), True)
check("wrapping window at 05:00 (end is exclusive)",
      npc_windows.slot_window_open(WRAP, at(5)), False)
check("wrapping window at 22:00 (start is inclusive)",
      npc_windows.slot_window_open(WRAP, at(22)), True)

PLAIN = "08:00-12:00"
check("plain window at 07:59",
      npc_windows.slot_window_open(PLAIN, at(7, 59)), False)
check("plain window at 08:00", npc_windows.slot_window_open(PLAIN, at(8)), True)
check("plain window at 11:59",
      npc_windows.slot_window_open(PLAIN, at(11, 59)), True)
check("plain window at 12:00", npc_windows.slot_window_open(PLAIN, at(12)), False)

# night/day against the SEASON's sun, not a constant.
check("night in shortday (sunrise 08:00, sunset 16:00)",
      [npc_windows.is_night(at(*hm))
       for hm in ((7, 59), (8, 0), (15, 59), (16, 0))],
      [True, False, False, True])
check("the 'night' window is exactly is_night",
      [npc_windows.slot_window_open("night", at(*hm))
       for hm in ((7, 59), (8, 0), (15, 59), (16, 0))],
      [True, False, False, True])
check("the 'day' window is its complement",
      [npc_windows.slot_window_open("day", at(*hm))
       for hm in ((7, 59), (8, 0), (15, 59), (16, 0))],
      [False, True, True, False])
check("07:00 is night in shortday and day in longday",
      (npc_windows.is_night(at(7, 0, "shortday")),
       npc_windows.is_night(at(7, 0, "longday"))),
      (True, False))

check("a real span parses to minutes", npc_windows.parse_window(WRAP), (1320, 300))
check("an impossible hour is no window",
      npc_windows.parse_window("25:00-01:00"), None)
check("'night' is not a span", npc_windows.parse_window("night"), None)
check("junk is not a span", npc_windows.parse_window("junk"), None)

check("an unusable when is dropped to 'always'",
      npc_spawn.normalize_slot({"role": "guard", "when": "junk"})["when"], "")
check("a slot without a when is always open",
      npc_spawn.normalize_slot({"role": "guard"})["when"], "")
check("night survives normalization, case-insensitively",
      npc_spawn.normalize_slot({"role": "guard", "when": " NIGHT "})["when"],
      "night")
check("a span is stored canonically",
      npc_spawn.normalize_slot({"role": "guard", "when": "8:00-12:00"})["when"],
      "08:00-12:00")

# ---------------------------------------------------------------------------
print("\n(b) a closed slot wants nobody")

NIGHT_BAR = {"id": "forest", "name": "Dark Forest", "npc_slots": [
    {"role": "robber", "count_min": 2, "count_max": 3, "when": WRAP}]}
check("at 12:00 the slot is shut — no gap",
      npc_spawn.missing_slots(NIGHT_BAR, [], now=at(12)), [])
check("at 23:00 the very same slot is short two",
      [(g["role"], g["needed"])
       for g in npc_spawn.missing_slots(NIGHT_BAR, [], now=at(23))],
      [("robber", 2)])
set_game_time(at(23))
check("without an explicit moment the game clock decides",
      [g["role"] for g in npc_spawn.missing_slots(NIGHT_BAR, [])], ["robber"])
set_game_time(at(12))
check("… and it decides the other way at noon",
      npc_spawn.missing_slots(NIGHT_BAR, []), [])

# ---------------------------------------------------------------------------
print("\n(c) a closed window sends the NPCs home")

FOREST = world.add_location("Smoke Forest", "Black firs.",
                            rooms=[{"name": "Clearing", "description": "Moss."}])
FOREST_ID = FOREST["id"]
CLEARING = world.get_location_by_id(FOREST_ID)["rooms"][0]["id"]
update_location_with_extras(FOREST_ID, {"npc_slots": [
    {"role": "robber", "count_min": 1, "count_max": 2, "when": WRAP},
    {"role": "woodcutter", "count_min": 1, "count_max": 1, "when": PLAIN},
]})
check("the location stores both windows",
      [(s["role"], s["when"])
       for s in world.get_location_by_id(FOREST_ID).get("npc_slots") or []],
      [("robber", "22:00-05:00"), ("woodcutter", "08:00-12:00")])


def make_npc(name: str, *, role: str = "", wanderer: bool = False) -> str:
    """A living temporary NPC of this location, gate off."""
    cfg = config.get_all()
    cfg.setdefault("npc", {})["require_assets"] = False
    config.save(cfg, STORAGE / "config.json")
    apply_npc({"character_name": name,
               "character_appearance": "a lean figure in a patched coat",
               "face_appearance": "a narrow face, dark eyes",
               "outfit_description": "a patched brown coat",
               "standing_task": "watching the road"},
              FOREST_ID, room_id=CLEARING, ttl_hours=0,
              slot_role=role, wanderer=wanderer)
    return name


AVATAR = "Player"
save_character_profile(AVATAR, {"character_name": AVATAR,
                                "template": "human-roleplay"}, create_new=True)
_uid = create_user("demo", "smoke-password", allowed_characters=[AVATAR])
update_user(_uid, settings={"active_character": AVATAR})


def chat_row(character: str, partner: str, minutes_ago: float) -> None:
    """One chat_messages row, stamped in SYSTEM time — the clock the in-chat
    helper measures against (technical stamp, not game time)."""
    ts = (utc_now() - timedelta(minutes=minutes_ago)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chat_messages (character_name, partner, ts, role, "
            "content, channel) VALUES (?, ?, ?, 'user', 'Wait!', 'web')",
            (character, partner, ts))


set_game_time(at(11))     # robber slot shut, woodcutter slot open

ROBBER = make_npc("Smoke Robber", role="robber")
TALKER = make_npc("Smoke Talker", role="robber")
WOODIE = make_npc("Smoke Woodcutter", role="woodcutter")
ROAMER = make_npc("Smoke Roamer", role="robber", wanderer=True)
chat_row(TALKER, AVATAR, 0.0)

check("four NPCs are standing there",
      sorted(n for n in __import__(
          "app.models.character", fromlist=["x"]).list_temporary_npcs()),
      sorted([ROBBER, TALKER, WOODIE, ROAMER]))

POOLED = npc_ops.sweep_closed_windows()
check("exactly one NPC went back into the pool", POOLED, 1)
check("the robber of the shut slot is pooled",
      get_character_status(ROBBER), "pooled")
check("and it says why",
      (get_character_profile(ROBBER) or {}).get("npc_pooled_reason"),
      "window closed")
check("the one mid-conversation stays", get_character_status(TALKER), "")
check("the open slot's NPC stays", get_character_status(WOODIE), "")
check("a wanderer is never swept by the window",
      get_character_status(ROAMER), "")

with db.transaction() as _conn:
    _conn.execute("DELETE FROM chat_messages")
check("with the conversation cold the talker follows",
      (npc_ops.sweep_closed_windows(), get_character_status(TALKER)),
      (1, "pooled"))

set_game_time(at(23))     # robber slot open again, woodcutter shut
check("at 23:00 it is the woodcutter's turn",
      (npc_ops.sweep_closed_windows(), get_character_status(WOODIE)),
      (1, "pooled"))

# ---------------------------------------------------------------------------
print("\n(d) the night/day rule condition is unchanged")


def cond(text: str, minute_of_day: int) -> bool:
    set_game_time(at(minute_of_day // 60, minute_of_day % 60))
    return activity_engine.evaluate_condition(text, "Nobody")[0]


check("night", [cond("night", m) for m in (959, 960, 479, 480)],
      [False, True, True, False])
check("night-30 starts half an hour earlier",
      [cond("night-30", m) for m in (929, 935)], [False, True])
check("night+30 starts half an hour later",
      [cond("night+30", m) for m in (970, 995)], [False, True])
check("day", [cond("day", m) for m in (479, 480, 959, 960)],
      [False, True, True, False])
check("day-30 starts half an hour earlier",
      [cond("day-30", m) for m in (449, 455)], [False, True])
check("day+30 starts half an hour later",
      [cond("day+30", m) for m in (500, 510)], [False, True])
check("NOT night is day", [cond("NOT night", m) for m in (479, 480)],
      [False, True])

# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("smoke_npc_windows: OK")
