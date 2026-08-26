#!/usr/bin/env python3
"""Smoke: the ``activity_home_enabled`` feature gate (spec § E2, item 6).

A temporary NPC gets its timing and its whereabouts from the slot windows and
(later) a home area, never from the per-character "Activity & Home" sub-tab.
The template therefore switches the whole subject off — ``npc-temporary.json``
declares ``features.activity_home_enabled: false`` — and every surface that
belongs to it follows that ONE truth: the sub-tab (frontend, not testable
here), the prompt consumer, the daily-schedule write side and the
home-location write route.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The clock is frozen (``set_game_factor(0.0)`` + ``set_game_time``) at
Y0002-D100T10:00, so "the current hour" is exactly 10 and the next one 11.

  (a) THE FLAG ITSELF, read through ``is_feature_enabled`` (fail-open, step 2
      = template default):

        * ``npc-temporary`` declares the key ``false`` →
          ``bool(features.get(...)) is False``.
        * ``human-roleplay`` does not declare it at all →
          ``features.get(feature, True)`` → True. No shipped template but
          ``npc-temporary`` carries the key, so every full character keeps
          the tab exactly as before.
        * The gate is the FEATURE, not the template name: a per-character
          config override (step 1, which wins over the template) flips the
          same temp NPC back to True.

  (b) THE PROMPT CONSUMER. Both characters get the IDENTICAL schedule rows,
      enabled, two slots — the full character through the model API, the temp
      NPC through a direct row write (``force_schedule``), because the model
      API refuses it since (c) and this section is about the READING side:

          {"hour": 10, "location": <Crossroads Inn id>, "role": "sweeping"}
          {"hour": 11, "sleep": True}

      ``_build_daily_schedule_block`` formats the slot of the current hour and
      the one of the next hour (``thought_context.py`` ``_fmt``): a placed slot
      as ``"  HH:00 — location: <name>, role: <role>"`` (the location ID is
      resolved to the location NAME), a sleep slot as
      ``"  HH:00 — you usually sleep around now"``, joined with "\\n". By hand,
      for the full character:

          "  10:00 — location: Crossroads Inn, role: sweeping\\n"
          "  11:00 — you usually sleep around now"

      The temp NPC has the very same rows in the DB and gets ``""`` — that is
      the gate talking and not missing data, which is the whole point of
      saving the same fixture twice. With the config override on, the temp
      NPC renders the full character's block, character for character.

  (c) THE WRITE SIDE, and the gate sits in the MODEL FUNCTION —
      ``save_character_daily_schedule`` itself, not in a route. That closes
      every surface at once: the POST route (which used to persist the rows
      before the refused sync), the DELETE asymmetry, and the ``schedule:``
      rule condition that reads these rows (``activity_engine``). For a temp
      NPC the call answers False and writes nothing — asked at the TABLE
      (``SELECT COUNT(*) FROM daily_schedules``, 0 rows), because
      ``get_character_daily_schedule`` reports a missing row as
      ``{"enabled": False, "slots": []}`` and would hide the difference. For
      a full character it answers True and leaves the rows exactly as before.

      ``sync_daily_schedule`` persists a marker job per
      character (``daily_schedule_<name>``, source ``daily_schedule``) and
      answers 1 for an active schedule. For the temp NPC it answers 0 and
      writes NOTHING — asked at the consumer, i.e. the ``scheduler_jobs``
      rows the manager saved (``get_character_scheduler_jobs``): the full
      character has exactly one job with that id, the temp NPC has none.
      The refusal also comes FIRST, before the legacy-job cleanup, so a gated
      call cannot delete rows either.

  (d) THE WRITE ROUTE. ``POST /characters/{name}/home-location`` (the blocking
      body ``_save_home_location_route_sync``) answers 409 for the temp NPC
      and writes no ``home_location`` into the character config; for the full
      character it stays a plain success. The READ route is deliberately not
      gated — an existing value must stay visible.

Usage:  ./.venv/bin/python scripts/smoke_activity_home_gate.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="activityhome-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="activityhome-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import embedding  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.thought_context import _build_daily_schedule_block  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (get_character_config,  # noqa: E402
                                  get_character_daily_schedule,
                                  get_character_scheduler_jobs,
                                  save_character_config,
                                  save_character_daily_schedule,
                                  save_character_profile)
from app.models.character_template import is_feature_enabled  # noqa: E402
from app.routes.characters import (  # noqa: E402
    _save_home_location_route_sync, get_home_location_route)
from app.scheduler.scheduler_manager import SchedulerManager  # noqa: E402

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


def raises_status(label, status, fn):
    """``fn`` must raise an ``HTTPException`` carrying ``status``."""
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except HTTPException as e:
        if e.status_code != status:
            print(f"  FAIL {label}: HTTP {e.status_code} — expected {status}")
            FAILURES.append(label)
            return
        print(f"  OK  {label}: HTTP {e.status_code} ({str(e.detail)[:80]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception")
    FAILURES.append(label)


# ── the world: one location, two characters ─────────────────────────────────

set_game_factor(0.0)
set_game_time(GameTime.from_parts(2, 100, 10, 0, 0))

LOC = world.add_location("Crossroads Inn", "A stone house at the fork.",
                         rooms=[{"name": "Taproom", "description": "Benches."}])
LOC_ID = LOC["id"]

NPC = "Smoke Temp"
FULL = "Smoke Full"
save_character_profile(NPC, {"character_name": NPC,
                             "template": "npc-temporary",
                             "outfit_description": "a grey linen apron",
                             "standing_task": "sweeping the yard"},
                       create_new=True)
save_character_profile(FULL, {"character_name": FULL,
                              "template": "human-roleplay"}, create_new=True)

SCHEDULE = {"enabled": True, "slots": [
    {"hour": 10, "location": LOC_ID, "role": "sweeping", "sleep": False},
    {"hour": 11, "location": "", "role": "", "sleep": True},
]}
EXPECTED_BLOCK = ("  10:00 — location: Crossroads Inn, role: sweeping\n"
                  "  11:00 — you usually sleep around now")

# ---------------------------------------------------------------------------
print("\n(a) the flag")

check("the temp NPC has the subject switched off",
      is_feature_enabled(NPC, "activity_home_enabled"), False)
check("a full character keeps it (template omits the key)",
      is_feature_enabled(FULL, "activity_home_enabled"), True)

# ---------------------------------------------------------------------------
print("\n(b) the prompt consumer")


def force_schedule(name, schedule):
    """Write a schedule row PAST the gate — the fixture for (b).

    Section (b) is about the READING side: both characters must carry the
    identical rows so an empty block can only be the gate talking and never
    missing data. Since the write side is gated (see (c)), the temp NPC's
    fixture has to be written the way a pre-gate world's row got there.
    """
    import json as _json

    from app.core.db import transaction
    with transaction() as conn:
        conn.execute(
            "INSERT INTO daily_schedules (character_name, enabled, slots, meta)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(character_name) DO UPDATE SET"
            " enabled=excluded.enabled, slots=excluded.slots,"
            " meta=excluded.meta",
            (name, 1 if schedule.get("enabled") else 0,
             _json.dumps(schedule.get("slots", [])), _json.dumps(schedule)))


force_schedule(NPC, dict(SCHEDULE))
save_character_daily_schedule(FULL, dict(SCHEDULE))
check("both characters really carry the same schedule rows",
      (get_character_daily_schedule(NPC)["slots"]
       == get_character_daily_schedule(FULL)["slots"],
       get_character_daily_schedule(NPC)["enabled"]),
      (True, True))
check("the full character's block renders as before",
      _build_daily_schedule_block(FULL), EXPECTED_BLOCK)
check("the temp NPC's block is empty despite the saved schedule",
      _build_daily_schedule_block(NPC), "")

# ---------------------------------------------------------------------------
print("\n(c) the daily-schedule write side")

NPC2 = "Smoke Temp Two"
save_character_profile(NPC2, {"character_name": NPC2,
                             "template": "npc-temporary",
                             "outfit_description": "a canvas smock",
                             "standing_task": "carrying water"},
                       create_new=True)
check("the model function refuses to write for a temp NPC",
      save_character_daily_schedule(NPC2, dict(SCHEDULE)), False)
check("… and the table is untouched — no row at all, asked at the table",
      db.get_connection().execute(
          "SELECT COUNT(*) FROM daily_schedules WHERE character_name=?",
          (NPC2,)).fetchone()[0], 0)
check("… while the same call for a full character answers True",
      save_character_daily_schedule(FULL, dict(SCHEDULE)), True)
check("… and the full character's rows are unchanged",
      get_character_daily_schedule(FULL)["slots"], SCHEDULE["slots"])

MANAGER = SchedulerManager()
try:
    check("the full character's schedule is synced",
          MANAGER.sync_daily_schedule(FULL, dict(SCHEDULE)), 1)
    check("… and left a marker job",
          [j["id"] for j in get_character_scheduler_jobs(FULL)],
          [f"daily_schedule_{FULL}"])
    check("the temp NPC's schedule is refused",
          MANAGER.sync_daily_schedule(NPC, dict(SCHEDULE)), 0)
    check("… and wrote nothing", get_character_scheduler_jobs(NPC), [])

    # ---------------------------------------------------------------------
    print("\n(d) the home-location write route")

    check("the full character can be given a home",
          _save_home_location_route_sync(
              FULL, {"home_location": LOC_ID, "home_room": ""}),
          {"status": "success"})
    check("… and it is readable again",
          get_home_location_route(FULL)["home_location"], LOC_ID)
    raises_status("the temp NPC's home is refused", 409,
                  lambda: _save_home_location_route_sync(
                      NPC, {"home_location": LOC_ID, "home_room": ""}))
    check("… and no home was written",
          (get_character_config(NPC) or {}).get("home_location", ""), "")

    # ---------------------------------------------------------------------
    print("\n(e) the gate is the FEATURE, not the template name")

    cfg = get_character_config(NPC) or {}
    cfg["activity_home_enabled"] = True
    save_character_config(NPC, cfg)
    check("a per-character override switches the subject back on",
          is_feature_enabled(NPC, "activity_home_enabled"), True)
    check("… the same NPC now renders the block",
          _build_daily_schedule_block(NPC), EXPECTED_BLOCK)
    check("… the sync goes through",
          MANAGER.sync_daily_schedule(NPC, dict(SCHEDULE)), 1)
    check("… and the home route answers success",
          _save_home_location_route_sync(
              NPC, {"home_location": LOC_ID, "home_room": ""}),
          {"status": "success"})
finally:
    MANAGER.scheduler.shutdown(wait=False)

# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("ALL GREEN")
