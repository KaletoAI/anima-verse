#!/usr/bin/env python3
"""Smoke: World Dev free mode — single room prop placement: place_room_prop.

A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop calls
it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_room_prop.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture (turn 1):
  Location "Demo Hall" (LID), boundary [[-10,-10],[10,-10],[10,10],[-10,10]]
  with rooms:
  - "Main Hall" (HALL), laid out at x 0, y 0, w 6, d 4 (room frame 0..6 x 0..4)
  - "Empty Store" (STORE), no floor plan

Library props (created via props.create_prop):
  - STATUE: "Demo Statue", width 0.8, depth 0.6, height 1.8, mount floor
      at yaw 0  -> ex 0.8, ez 0.6 -> hx 0.4, hz 0.3 -> x in [0.4, 5.6], z in [0.3, 3.7]
      at yaw 90 -> ex 0.6, ez 0.8 -> hx 0.3, hz 0.4 -> x in [0.3, 5.7], z in [0.4, 3.6]
  - BENCH:  "Demo Bench", width 2.0, depth 0.6, height 0.9, mount floor
      at yaw 0  -> ex 2.0, ez 0.6 -> hx 1.0, hz 0.3 -> x in [1, 5], z in [0.3, 3.7]
      at yaw 90 -> ex 0.6, ez 2.0 -> hx 0.3, hz 1.0 -> x in [0.3, 5.7], z in [1, 3]
  - RUG:    "Demo Rug", width 2.0, depth 1.5, height 0.02, mount floor (underlay <= 0.05 m)
  - QUEST_PROP: sidecar carries quest_run "qr_1"

Cases:
  (a) turn 2: place_room_prop STATUE in HALL at (2, 1.5) yaw 90 label "Founder Statue"
      -> ok, wrote True. Result line exact:
      'placed prop <STATUE> "Demo Statue" in room <HALL> "Main Hall" of <LID> at (2, 1.5) yaw 90'.
      Stored placement has prop_id STATUE, at [2.0, 1.5], yaw 90, label "Founder Statue", id set.
  (b) turn 2: place RUG by room NAME "Main Hall" at (2, 1.5) yaw 0 -> ok (rug is an underlay,
      does not collide with STATUE); 2 placements stored.
  (c) turn 3: out-of-room refusals (nothing written, journal kind "refused"):
      - STATUE at (5.8, 1.5) yaw 0 -> refused, names allowed x range "0.4…5.6"
      - BENCH at (3, 0.5) yaw 90 -> refused, names allowed z range "1…3"
  (d) turn 3: overlap refusal:
      - BENCH at (2.2, 1.5) yaw 0 overlaps STATUE at (2, 1.5) -> refused naming STATUE / "Demo Statue"
  (e) turn 3: unknown prop "prop_nope" and quest_run prop -> both refused with
      "find_props lists the props".
  (f) turn 3: unknown room "room_nope" -> refused naming "Main Hall";
      ground "__ground__" -> refused naming "place_world_prop";
      STORE (no floor plan) -> refused naming "set_room_layout first".
  (g) undo(run, 2) -> complete True; HALL layout equals LAYOUT_BEFORE (no "props")
      and whole location row equals ROW_BEFORE.
  (h) 100-placement limit: fill HALL with 100 rug placements, then place_room_prop
      -> refused naming "100 prop placements", count stays 100.
"""
from __future__ import annotations

import atexit
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_rprop_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_rprop_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_rprop_inst_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
for _d in (CLIPS, STORAGE, INSTANCE):
    atexit.register(shutil.rmtree, _d, ignore_errors=True)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import props  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models.world import append_room_props, get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("room_prop", "m", "p", "u", 60, 600000)


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def named(name):
    return [l for l in list_locations() if l.get("name") == name]


def room(lid, name):
    return next((r for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if r.get("name") == name), {})


STATUE = props.create_prop(name="Demo Statue", category="decoration",
                           width_m=0.8, depth_m=0.6, height_m=1.8, mount="floor")["id"]
BENCH = props.create_prop(name="Demo Bench", category="furniture",
                          width_m=2.0, depth_m=0.6, height_m=0.9, mount="floor")["id"]
RUG = props.create_prop(name="Demo Rug", category="decoration",
                        width_m=2.0, depth_m=1.5, height_m=0.02, mount="floor")["id"]
QUEST_PROP = props.create_prop(name="Demo Quest Idol", category="decoration",
                               width_m=0.5, depth_m=0.5, height_m=1.0, mount="floor")["id"]
_qmeta = props.read_sidecar(QUEST_PROP)
_qmeta["quest_run"] = "qr_1"
props._write_sidecar(QUEST_PROP, _qmeta)

# Fixture (turn 1)
res = call("create_location", {
    "data": {"name": "Demo Hall", "rooms": [{"name": "Main Hall"}, {"name": "Empty Store"}]},
    "x": 0, "z": 0, "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("fixture: hall created", res.ok and res.wrote, res)
LID = (named("Demo Hall") or [{}])[0].get("id") or ""
HALL = room(LID, "Main Hall").get("id")
STORE = room(LID, "Empty Store").get("id")

res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [{"id": HALL, "x": 0, "y": 0, "w": 6, "d": 4}]}})
check("fixture: Main Hall laid out", res.ok and res.wrote, res)

ROW_BEFORE = copy.deepcopy(get_location_by_id(LID))
LAYOUT_BEFORE = copy.deepcopy(room(LID, "Main Hall").get("layout"))
check("fixture: no props before", isinstance(LAYOUT_BEFORE, dict)
      and "props" not in LAYOUT_BEFORE, LAYOUT_BEFORE)


def refused(label, args, *needles, turn=3):
    n = len(wr.steps(run))
    before = copy.deepcopy(get_location_by_id(LID))
    res = call("place_room_prop", args, turn=turn)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    check(f"{label}: journal row refused",
          len(wr.steps(run)) == n + 1 and wr.steps(run)[-1]["kind"] == "refused")
    check(f"{label}: location unchanged", get_location_by_id(LID) == before)
    return res


# (a) place statue by room id
res = call("place_room_prop", {
    "location_id": LID, "room_id": HALL, "prop_id": STATUE,
    "x": 2, "z": 1.5, "yaw": 90, "label": "Founder Statue"}, turn=2)
check("(a) ok", res.ok and res.wrote, res)
expected_line = (f'placed prop {STATUE} "Demo Statue" in room {HALL} "Main Hall" '
                 f"of {LID} at (2, 1.5) yaw 90")
check("(a) result line exact", res.line == expected_line, (res.line, expected_line))
placed = (room(LID, "Main Hall").get("layout") or {}).get("props") or []
check("(a) one placement", len(placed) == 1, placed)
p0 = placed[0] if placed else {}
check("(a) stored fields exact",
      p0.get("prop_id") == STATUE and p0.get("at") == [2.0, 1.5]
      and p0.get("yaw") == 90 and p0.get("label") == "Founder Statue"
      and bool(p0.get("id")), p0)

# (b) place rug by room name under statue (underlay does not collide)
res = call("place_room_prop", {
    "location_id": LID, "room_id": "Main Hall", "prop_id": RUG,
    "x": 2, "z": 1.5}, turn=2)
check("(b) rug under statue ok", res.ok and res.wrote, res)
placed = (room(LID, "Main Hall").get("layout") or {}).get("props") or []
check("(b) two placements", len(placed) == 2 and placed[1].get("prop_id") == RUG
      and placed[1].get("at") == [2.0, 1.5] and placed[1].get("yaw") == 0, placed)

# (c) out-of-room refusals
refused("(c) out-of-room x",
        {"location_id": LID, "room_id": HALL, "prop_id": STATUE, "x": 5.8, "z": 1.5, "yaw": 0},
        "0.4…5.6")
refused("(c) out-of-room turned z",
        {"location_id": LID, "room_id": HALL, "prop_id": BENCH, "x": 3, "z": 0.5, "yaw": 90},
        "1…3")

# (d) overlap refusal
refused("(d) overlap with statue",
        {"location_id": LID, "room_id": HALL, "prop_id": BENCH, "x": 2.2, "z": 1.5, "yaw": 0},
        "overlaps", STATUE, "Demo Statue")

# (e) unknown prop and quest_run prop
refused("(e) unknown prop",
        {"location_id": LID, "room_id": HALL, "prop_id": "prop_nope", "x": 4, "z": 2},
        "find_props lists the props")
refused("(e) quest_run prop",
        {"location_id": LID, "room_id": HALL, "prop_id": QUEST_PROP, "x": 4, "z": 2},
        "find_props lists the props")

# (f) unknown room, ground room, room without layout
refused("(f) unknown room",
        {"location_id": LID, "room_id": "room_nope", "prop_id": STATUE, "x": 4, "z": 2},
        "Main Hall")
refused("(f) ground room",
        {"location_id": LID, "room_id": "__ground__", "prop_id": STATUE, "x": 4, "z": 2},
        "place_world_prop")
refused("(f) room without layout",
        {"location_id": LID, "room_id": STORE, "prop_id": STATUE, "x": 1, "z": 1},
        "set_room_layout first")

# (g) undo turn 2 restores room props exactly
rep = wu.undo(run, 2)
check("(g) undo turn 2 complete", rep.get("complete") is True, rep)
check("(g) room layout exact", room(LID, "Main Hall").get("layout") == LAYOUT_BEFORE,
      room(LID, "Main Hall").get("layout"))
check("(g) location row exact", get_location_by_id(LID) == ROW_BEFORE)

# (h) 100-placement limit
bulk = [{"prop_id": RUG, "at": [2.0, 2.0], "yaw": 0} for _ in range(100)]
ok_bulk = append_room_props(LID, HALL, bulk)
check("(h) seeded 100 props", ok_bulk
      and len((room(LID, "Main Hall").get("layout") or {}).get("props") or []) == 100)
refused("(h) 101st prop refused",
        {"location_id": LID, "room_id": HALL, "prop_id": STATUE, "x": 4, "z": 2},
        "100 prop placements", turn=5)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
