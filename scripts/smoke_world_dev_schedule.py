#!/usr/bin/env python3
"""Smoke: World Dev free mode — a bad daily schedule is refused, not warned (gap 24).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 6.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_schedule.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture (turn 1): create_location "Demo Bakery" (B), placed with a 10 m square
boundary; its id is read back by name.

(v) create_character{data: {name: "Demo Baker"}, schedule: [{hour 18, role
    "rest"}, {hour 0, sleep true}, {hour 9, location "Demo Bakery", role
    "work"}]} -> ok. The stored slots (get_character_daily_schedule) are exactly
    these three, sorted by hour, in the shape
    world_dev_apply._apply_home_and_schedule writes:
      {hour 0, location "", role "", sleep True}
      {hour 9, location B, role "work", sleep False}
      {hour 18, location "", role "rest", sleep False}
    The slots are sent out of order on purpose (18, 0, 9) so the sort shows.

Refusals (plan Task 6 "Produces", the message text is quoted from there; <i>
is the slot index in the list sent):
  R1 hour 24              -> "schedule[0]: 'hour' must be a whole number 0-23"
     (also checked for -1, 9.5, "9" and true: each is no whole number 0-23 —
     a JSON boolean is no number, although Python's bool is an int)
  R2 {hour 9}             -> "schedule[0] needs a location, a role or \"sleep\": true"
  R3 {hour 0, sleep true, role "dream"}
                          -> "schedule[0]: a sleep slot takes no location or role"
  R4 [{hour 9, role "a"}, {hour 9, role "b"}]
                          -> "schedule[1] repeats hour 9 of schedule[0]"
  R5 {hour 0, sleep true, location "Demo Bakery"}
                          -> "schedule[0]: a sleep slot takes no location or role"
     (R3's rule through the other key: a sleep slot names no place either)
  R6 {hour 3, location "  ", role "x"}
                          -> "schedule[0]: 'location' is blank — name a place or
                              leave the key out"
     (a whitespace-only location names no place; without this own message
     the place check would quote '  ' as "no place of this world")
  R6b {hour 3, location "", role "x"} -> the same message (an empty string
     is as blank as whitespace; it used to be dropped silently)
  R7 [{hour 5, role "ok"}, {hour 24, role "x"}]
                          -> "schedule[1]: 'hour' must be a whole number 0-23"
     (a bad SECOND slot refuses the whole list, naming index 1)
  R8 []                   -> "'schedule' must not be empty — leave the key out"
     (an empty list would be accepted and store nothing; update_character
     refused it before too, create_character now agrees)
Each refusal is sent once via create_character (turn 2, name "Demo Refused
<k>") -> ok False, wrote False, no character row, newest journal step kind
"refused"; and once via update_character{name: "Demo Baker", patch:
{schedule: ...}} (turn 3) -> ok False, wrote False, newest step kind
"refused", and Demo Baker's stored schedule equal to the one read after (v).
That is 8 x 2 = 16 calls for R1-R8, plus the four extra hour values via
create_character, and hour -1 once more via update_character.

(f) hour 9.0 is a whole number: create_character "Demo Float" with
    [{hour 9.0, role "work"}] -> ok, stored slots exactly
    [{hour 9, location "", role "work", sleep False}] and the stored hour is
    an int (type check, not only ==).

(h) a blank home / home_room is refused, not dropped: create_character with
    home "  " -> "'home' must not be empty — name a place or leave the key
    out"; update_character patch {home_room: "  "} -> "'home_room' must not be
    empty — name a place or leave the key out" (both ok False, wrote False,
    newest step "refused", no character row / Baker's schedule unchanged).
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_sched_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_sched_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.get_config_path().write_text(json.dumps({"game": {"discovery_range_m": 0}}))

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  get_character_daily_schedule)
from app.models.world import list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("schedule", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def newest():
    return wr.steps(run)[-1]


SQUARE = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
res = call(1, "create_location", {"data": {"name": "Demo Bakery"}, "x": 0, "z": 0,
                                  "boundary": SQUARE})
check("fixture Demo Bakery created", res.ok, res)
B = next((l["id"] for l in list_locations() if l.get("name") == "Demo Bakery"), "")
check("fixture Demo Bakery has an id", bool(B), B)

# ── (v) a valid schedule ────────────────────────────────────────────────
BAKER = "Demo Baker"
res = call(1, "create_character", {"data": {"name": BAKER}, "schedule": [
    {"hour": 18, "role": "rest"},
    {"hour": 0, "sleep": True},
    {"hour": 9, "location": "Demo Bakery", "role": "work"}]})
check("(v) valid schedule accepted", res.ok, res)
stored = get_character_daily_schedule(BAKER).get("slots")
want = [{"hour": 0, "location": "", "role": "", "sleep": True},
        {"hour": 9, "location": B, "role": "work", "sleep": False},
        {"hour": 18, "location": "", "role": "rest", "sleep": False}]
check("(v) stored slots exactly the three, sorted by hour", stored == want, stored)
before = json.dumps(get_character_daily_schedule(BAKER), sort_keys=True)

CASES = [
    ("R1 hour 24", [{"hour": 24, "role": "x"}],
     "schedule[0]: 'hour' must be a whole number 0-23"),
    ("R2 empty slot", [{"hour": 9}],
     'schedule[0] needs a location, a role or "sleep": true'),
    ("R3 sleep with role", [{"hour": 0, "sleep": True, "role": "dream"}],
     "schedule[0]: a sleep slot takes no location or role"),
    ("R4 repeated hour", [{"hour": 9, "role": "a"}, {"hour": 9, "role": "b"}],
     "schedule[1] repeats hour 9 of schedule[0]"),
    ("R5 sleep with location", [{"hour": 0, "sleep": True, "location": "Demo Bakery"}],
     "schedule[0]: a sleep slot takes no location or role"),
    ("R6 blank location", [{"hour": 3, "location": "  ", "role": "x"}],
     "schedule[0]: 'location' is blank — name a place or leave the key out"),
    ("R6b empty location", [{"hour": 3, "location": "", "role": "x"}],
     "schedule[0]: 'location' is blank — name a place or leave the key out"),
    ("R7 bad second slot", [{"hour": 5, "role": "ok"}, {"hour": 24, "role": "x"}],
     "schedule[1]: 'hour' must be a whole number 0-23"),
    ("R8 empty list", [], "'schedule' must not be empty — leave the key out"),
]
EXTRA = [
    ("R1 hour -1", [{"hour": -1, "role": "x"}],
     "schedule[0]: 'hour' must be a whole number 0-23"),
    ("R1 hour 9.5", [{"hour": 9.5, "role": "x"}],
     "schedule[0]: 'hour' must be a whole number 0-23"),
    ("R1 hour '9'", [{"hour": "9", "role": "x"}],
     "schedule[0]: 'hour' must be a whole number 0-23"),
    ("R1 hour true", [{"hour": True, "role": "x"}],
     "schedule[0]: 'hour' must be a whole number 0-23"),
]

for k, (label, sched, msg) in enumerate(CASES + EXTRA):
    name = f"Demo Refused {k}"
    res = call(2, "create_character", {"data": {"name": name}, "schedule": sched})
    check(f"create {label}: refused with the plan message",
          not res.ok and not res.wrote and msg in res.line, res)
    check(f"create {label}: no character", not character_row_exists(name))
    check(f"create {label}: newest step refused", newest()["kind"] == "refused",
          newest())

for label, sched, msg in CASES + EXTRA[:1]:
    res = call(3, "update_character", {"name": BAKER, "patch": {"schedule": sched}})
    check(f"update {label}: refused with the plan message",
          not res.ok and not res.wrote and msg in res.line, res)
    check(f"update {label}: newest step refused", newest()["kind"] == "refused",
          newest())
    after = json.dumps(get_character_daily_schedule(BAKER), sort_keys=True)
    check(f"update {label}: schedule unchanged", after == before, after)

# ── (f) a float hour that is a whole number ──────────────────────────────
res = call(4, "create_character", {"data": {"name": "Demo Float"},
                                   "schedule": [{"hour": 9.0, "role": "work"}]})
check("(f) hour 9.0 accepted", res.ok, res)
fslots = get_character_daily_schedule("Demo Float").get("slots")
check("(f) stored as hour 9", fslots == [{"hour": 9, "location": "", "role": "work",
                                         "sleep": False}], fslots)
check("(f) stored hour is an int", bool(fslots) and type(fslots[0]["hour"]) is int,
      fslots)

# ── (h) a blank home / home_room ─────────────────────────────────────────
res = call(4, "create_character", {"data": {"name": "Demo Homeless"}, "home": "  "})
check("(h) create blank home refused",
      not res.ok and not res.wrote
      and "'home' must not be empty — name a place or leave the key out" in res.line, res)
check("(h) create blank home: no character", not character_row_exists("Demo Homeless"))
check("(h) create blank home: newest step refused", newest()["kind"] == "refused", newest())
res = call(4, "update_character", {"name": BAKER, "patch": {"home_room": "  "}})
check("(h) update blank home_room refused",
      not res.ok and not res.wrote
      and "'home_room' must not be empty — name a place or leave the key out" in res.line,
      res)
check("(h) update blank home_room: newest step refused", newest()["kind"] == "refused",
      newest())
check("(h) update blank home_room: schedule unchanged",
      json.dumps(get_character_daily_schedule(BAKER), sort_keys=True) == before)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
