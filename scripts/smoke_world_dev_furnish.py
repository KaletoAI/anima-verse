#!/usr/bin/env python3
"""Smoke: World Dev free mode — kit furnishing: furnish_rooms (gap 2, decisions
E4, E6).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 5.
A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_furnish.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: turn 1 creates "Demo Cottage" through the tool (boundary
[[-10,-10],[10,-10],[10,10],[-10,10]]) with rooms Bedroom (room_type
"bedroom" — a shipped room type, ``furniture_kits.load_room_types()``) and
Store (no room_type; ``furniture_kits.guess_room_type`` finds no keyword
in "Store": the storage type's keywords are "storage", "storeroom", … — none
is contained in "store"), then lays Bedroom out with set_room_layout at x 2,
y 3, w 4, d 4. Store stays without a layout. A prop "Demo Bed" is created
through ``props.create_prop``; BED = its id. ``furniture_kits.solve_kit`` is
monkeypatched to return {"placed": [{"prop_id": BED, "at": [1, 1], "rot": 0}],
"unplaced": [], "missing_roles": []} for every room. KIT = the first id of
``furniture_kits.load_kits()`` (read at runtime: the shipped seed names the
kits; which one is irrelevant, the solver is patched).

  (a) turn 2: furnish_rooms{location_id, kit: KIT} -> ok. Bedroom
      layout.props has ONE placement, prop_id BED, at == [1.0, 1.0]:
      ``room_furnish._geometry`` returns origin [0.0, 0.0] for a real room
      (only the ground gets the boundary's min corner), ``furnish_location``
      adds that origin to the solver's at (1 + 0, 1 + 0), and
      ``world_ops._sanitize_room_layout`` stores a placement's at in metres
      relative to the room's min corner — so the room's x 2 / y 3 is NOT
      added (the plan's "[3, 4]" mixed the two frames). The line has
      "furnished 1 room with kit KIT", "Bedroom (1 piece)" and names Store
      with "set room_type" (reason no_room_type).
  (b) the same call again (turn 3) -> refused: Bedroom "already furnished"
      (has_furniture), Store "set room_type"; the journal row is "refused"
      and the location row is unchanged.
  (c) kit "nope" -> refused, the line names every id of load_kits() and
      "list_catalog furniture_kits".
  (c2) location "nope" -> refused "no location"; an unknown key -> refused.
  (d) "Demo Shed" (created in turn 1, room "Shed bedroom" with room_type
      "bedroom", no layout) -> refused, the line has "set_room_layout first"
      (reason no_layout: _geometry raises without x/y/w/d).
  (e1) discard_preview before any undo lists exactly two lines (the run
      created Demo Cottage and Demo Shed; restore_location is no creating
      op) and is the SAME list before and after (a) — furnishing creates
      nothing. undo(run, 2) -> complete; Bedroom's layout equals its layout
      before (a) byte-for-byte (no "props"), and the WHOLE location row
      equals its deep copy taken before (a) (restore_location restores every
      top-level key diff_keys saw change).
  (f) a foreign write between the dry run and the locked write: with
      ``world.append_rooms_props`` patched to store nothing and report every
      room refused ({} -> ``furnish_location`` moves each room to skipped
      with reason has_furniture), furnish_rooms (turn 3) -> refused, wrote
      False, the line has "nothing furnished" and "Bedroom: already
      furnished"; the journal row is "refused" and the row is unchanged.
  (e2) turn 4: furnish again, the patched solver now also reporting
      missing_roles ["seat"] -> ok, the line has "missing roles: Bedroom:
      seat" (furnish_location passes the solver's missing_roles through per
      room); an unrelated foreign edit of Store's
      description (``update_location_with_extras``, outside the run) ->
      undo(run, 4) reports "changed since" for "rooms" and leaves both: the
      Bedroom keeps its placement, Store keeps the foreign description
      (``diff_keys`` / restore_location work per TOP-LEVEL key — the
      existing restore_location rule of world_dev_undo).
  (f) also pins the skip ORDER: the line lists "Bedroom: already furnished"
      (refused during the write) before "Store: no room_type" (skipped up
      front) — the cottage's room order is [Bedroom, Store].

Second fixture: turn 5 creates "Demo House" (pin x -100, z -100, boundary
[[-10,-10],[10,-10],[10,10],[-10,10]]) with rooms "North room" and "South
room", both room_type "bedroom", laid out at x 1,y 1,w 4,d 4 and x 6,y 1,w 4,
d 4. HOUSE_ROW = its deep copy after turn 5; every case below ends with an
undo of its own turn, which must give back exactly HOUSE_ROW.
  (e3) turn 10, the seat inventory after an undo: furnish ok;
      ``places.room_places`` fills ``places._cache[HOUSE]``; a sentinel marker
      list is planted in that entry for North room (standing in for the
      furniture's seats) and is served from the cache; undo(run, 10) ->
      ``places._cache`` holds no entry for HOUSE and ``room_places`` no longer
      returns the sentinel (the restore calls ``places.invalidate()``, which
      clears the cache; without it the entry would live for the 300 s TTL).
  (g) turn 6, a partial foreign write: ``append_rooms_props`` patched to
      hand ONLY North room to the real writer and report South room False
      -> ok, the line has "furnished 1 room", "North room (1 piece)" and
      "skipped: South room: already furnished" (furnish_location moves a
      refused room to skipped as has_furniture).
  (h) turn 7, a writer that stores and then raises: the real writer runs,
      then RuntimeError("boom") -> run_tool re-raises it (no refusal type,
      the agent loop reports it), the journal row is kind
      "write" with a line starting "failed:" (``_Step.writing`` reconciles
      against storage and attaches the inverse).
  (i) turn 8, the stored piece count: the solver returns TWO placements per
      room ([1,1] and [2,2]) and ``world_ops._sanitize_room_layout`` is
      wrapped to drop the LAST prop of a layout holding more than one -> the
      solver reports 2 placed, storage holds 1, the line has "North room
      (1 piece)" and "South room (1 piece)" and no "2 pieces".
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

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_furn_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_furn_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_furn_inst_"))
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

from app.core import furniture_kits, props  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.models import world as world_model  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("furnish", "m", "p", "u", 60, 600000)


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def named(name):
    return [l for l in list_locations() if l.get("name") == name]


def room(lid, name):
    return next((r for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if r.get("name") == name), {})


BED = props.create_prop(name="Demo Bed", category="furniture")["id"]
KITS = list(furniture_kits.load_kits())
KIT = KITS[0]


def fake_solve_kit(**_kw):
    return {"placed": [{"prop_id": BED, "at": [1, 1], "rot": 0}],
            "unplaced": [], "missing_roles": []}


furniture_kits.solve_kit = fake_solve_kit

# Fixture (turn 1)
res = call("create_location", {
    "data": {"name": "Demo Cottage", "rooms": [
        {"name": "Bedroom", "room_type": "bedroom"}, {"name": "Store"}]},
    "x": 0, "z": 0, "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("fixture: cottage created", res.ok and res.wrote, res)
LID = (named("Demo Cottage") or [{}])[0].get("id") or ""
BEDROOM = room(LID, "Bedroom").get("id")
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [{"id": BEDROOM, "x": 2, "y": 3, "w": 4, "d": 4}]}})
check("fixture: bedroom laid out", res.ok and res.wrote, res)
res = call("create_location", {
    "data": {"name": "Demo Shed", "rooms": [{"name": "Shed bedroom", "room_type": "bedroom"}]},
    "x": 100, "z": 100})
check("fixture: shed created", res.ok and res.wrote, res)
SHED = (named("Demo Shed") or [{}])[0].get("id") or ""
LAYOUT_BEFORE = copy.deepcopy(room(LID, "Bedroom").get("layout"))
check("fixture: bedroom layout has no props", isinstance(LAYOUT_BEFORE, dict)
      and "props" not in LAYOUT_BEFORE, LAYOUT_BEFORE)


def refused(label, args, *needles, turn=3):
    n = len(wr.steps(run))
    before = [copy.deepcopy(get_location_by_id(x)) for x in (LID, SHED)]
    res = call("furnish_rooms", args, turn=turn)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    check(f"{label}: journal row refused",
          len(wr.steps(run)) == n + 1 and wr.steps(run)[-1]["kind"] == "refused")
    check(f"{label}: locations unchanged",
          [get_location_by_id(x) for x in (LID, SHED)] == before)
    return res


# (a)
ROW_BEFORE = copy.deepcopy(get_location_by_id(LID))
PREVIEW_BEFORE = wu.discard_preview(run)
res = call("furnish_rooms", {"location_id": LID, "kit": KIT}, turn=2)
check("(a) ok", res.ok and res.wrote, res)
check("(a) line", f"furnished 1 room with kit {KIT}" in res.line
      and "Bedroom (1 piece)" in res.line, res.line)
check("(a) line names Store with set room_type",
      "Store" in res.line and "set room_type" in res.line, res.line)
placed = (room(LID, "Bedroom").get("layout") or {}).get("props") or []
check("(a) one placement", len(placed) == 1 and placed[0].get("prop_id") == BED, placed)
check("(a) at relative to the room corner", placed and placed[0].get("at") == [1.0, 1.0],
      placed)
check("(a) store untouched", "layout" not in room(LID, "Store")
      or not (room(LID, "Store").get("layout") or {}).get("props"))

# (b)
refused("(b) second call", {"location_id": LID, "kit": KIT},
        "already furnished", "Bedroom", "set room_type", "Store")
# (c)
refused("(c) unknown kit", {"location_id": LID, "kit": "nope"},
        *KITS, "list_catalog furniture_kits")
refused("(c2) unknown place", {"location_id": "nope", "kit": KIT}, "no location")
refused("(c2) unknown key", {"location_id": LID, "kit": KIT, "rooms": []}, "rooms")
# (d)
refused("(d) no layout", {"location_id": SHED, "kit": KIT}, "set_room_layout first")

# (e1)
prev = wu.discard_preview(run)
check("(e1) discard_preview names the two created places", len(prev) == 2
      and any("Demo Cottage" in l for l in prev) and any("Demo Shed" in l for l in prev),
      prev)
check("(e1) discard_preview unchanged by the furnish step", prev == PREVIEW_BEFORE,
      (PREVIEW_BEFORE, prev))
rep = wu.undo(run, 2)
check("(e1) undo complete", rep.get("complete") is True, rep)
check("(e1) bedroom layout as before", room(LID, "Bedroom").get("layout") == LAYOUT_BEFORE,
      room(LID, "Bedroom").get("layout"))
check("(e1) whole location row as before", get_location_by_id(LID) == ROW_BEFORE,
      get_location_by_id(LID))

# (f)
_real_append = world_model.append_rooms_props
world_model.append_rooms_props = lambda _lid, _by_room: {}
try:
    refused("(f) foreign write before the locked span", {"location_id": LID, "kit": KIT},
            "nothing furnished", "Bedroom: already furnished")
    _f_line = wr.steps(run)[-1].get("line") or ""
    check("(f) skips in room order (Bedroom before Store)",
          0 <= _f_line.find("Bedroom: already") < _f_line.find("Store:"), _f_line)
finally:
    world_model.append_rooms_props = _real_append

# (e2)
furniture_kits.solve_kit = lambda **kw: {**fake_solve_kit(**kw), "missing_roles": ["seat"]}
res = call("furnish_rooms", {"location_id": LID, "kit": KIT}, turn=4)
check("(e2) furnish again ok", res.ok and res.wrote, res)
check("(e2) line names the missing role", "missing roles: Bedroom: seat" in res.line, res.line)
loc = get_location_by_id(LID)
rooms = copy.deepcopy(loc.get("rooms"))
for r in rooms:
    if r.get("name") == "Store":
        r["description"] = "A foreign edit."
update_location_with_extras(LID, {"rooms": rooms})
check("(e2) foreign edit stored", room(LID, "Store").get("description") == "A foreign edit.")
rep = wu.undo(run, 4)
text = repr(rep)
check("(e2) undo reports changed since rooms", rep.get("complete") is False
      and "changed since" in text and "rooms" in text, rep)
check("(e2) bedroom keeps its placement",
      len((room(LID, "Bedroom").get("layout") or {}).get("props") or []) == 1)
check("(e2) store keeps the foreign edit",
      room(LID, "Store").get("description") == "A foreign edit.")

# Second fixture (turn 5)
from app.core import places  # noqa: E402
from app.core import world_ops  # noqa: E402

res = call("create_location", {
    "data": {"name": "Demo House", "rooms": [
        {"name": "North room", "room_type": "bedroom"},
        {"name": "South room", "room_type": "bedroom"}]},
    "x": -100, "z": -100, "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]},
    turn=5)
check("fixture2: house created", res.ok and res.wrote, res)
HOUSE = (named("Demo House") or [{}])[0].get("id") or ""
NORTH = room(HOUSE, "North room").get("id")
SOUTH = room(HOUSE, "South room").get("id")
res = call("set_room_layout", {"location_id": HOUSE, "layout": {"rooms": [
    {"id": NORTH, "x": 1, "y": 1, "w": 4, "d": 4},
    {"id": SOUTH, "x": 6, "y": 1, "w": 4, "d": 4}]}}, turn=5)
check("fixture2: rooms laid out", res.ok and res.wrote, res)
HOUSE_ROW = copy.deepcopy(get_location_by_id(HOUSE))
furniture_kits.solve_kit = fake_solve_kit


def undone_exactly(label, turn):
    rep = wu.undo(run, turn)
    check(f"{label} undo complete", rep.get("complete") is True, rep)
    check(f"{label} row as before", get_location_by_id(HOUSE) == HOUSE_ROW,
          get_location_by_id(HOUSE))


# (e3) the seat cache after an undo
res = call("furnish_rooms", {"location_id": HOUSE, "kit": KIT}, turn=10)
check("(e3) furnish ok", res.ok and res.wrote, res)
places.room_places(HOUSE, NORTH)
check("(e3) cache filled", HOUSE in places._cache)
SENTINEL = [{"id": "stale-seat", "group": "seat"}]
with places._lock:
    _stamp, _by_room, _pack = places._cache[HOUSE]
    places._cache[HOUSE] = (_stamp, {**_by_room, NORTH: SENTINEL}, _pack)
check("(e3) sentinel served from the cache",
      places.room_places(HOUSE, NORTH) == SENTINEL)
undone_exactly("(e3)", 10)
check("(e3) cache entry dropped by the undo", HOUSE not in places._cache)
check("(e3) sentinel gone", places.room_places(HOUSE, NORTH) != SENTINEL)


# (g) a partial foreign write
def _partial(lid, by_room):
    got = _real_append(lid, {NORTH: by_room[NORTH]})
    return {NORTH: got.get(NORTH, False), SOUTH: False}


world_model.append_rooms_props = _partial
try:
    res = call("furnish_rooms", {"location_id": HOUSE, "kit": KIT}, turn=6)
finally:
    world_model.append_rooms_props = _real_append
check("(g) ok", res.ok and res.wrote, res)
for nd in ("furnished 1 room", "North room (1 piece)",
           "skipped: South room: already furnished"):
    check(f"(g) line has {nd!r}", nd in res.line, res.line)
undone_exactly("(g)", 6)


# (h) stores, then raises
def _store_then_raise(lid, by_room):
    _real_append(lid, by_room)
    raise RuntimeError("boom")


world_model.append_rooms_props = _store_then_raise
_raised = None
try:
    call("furnish_rooms", {"location_id": HOUSE, "kit": KIT}, turn=7)
except RuntimeError as exc:
    _raised = exc
finally:
    world_model.append_rooms_props = _real_append
check("(h) the writer's RuntimeError reaches the caller", str(_raised) == "boom", _raised)
_row = wr.steps(run)[-1]
check("(h) journal row kind write, line failed:",
      _row.get("kind") == "write" and str(_row.get("line") or "").startswith("failed:"),
      _row)
undone_exactly("(h)", 7)

# (i) the stored piece count
_real_sanitize = world_ops._sanitize_room_layout


def _drop_last(layout):
    props_ = list((layout or {}).get("props") or [])
    if len(props_) > 1:
        layout = {**layout, "props": props_[:-1]}
    return _real_sanitize(layout)


furniture_kits.solve_kit = lambda **_kw: {
    "placed": [{"prop_id": BED, "at": [1, 1], "rot": 0},
               {"prop_id": BED, "at": [2, 2], "rot": 0}],
    "unplaced": [], "missing_roles": []}
world_ops._sanitize_room_layout = _drop_last
try:
    res = call("furnish_rooms", {"location_id": HOUSE, "kit": KIT}, turn=8)
finally:
    world_ops._sanitize_room_layout = _real_sanitize
    furniture_kits.solve_kit = fake_solve_kit
check("(i) ok", res.ok and res.wrote, res)
for nd in ("North room (1 piece)", "South room (1 piece)"):
    check(f"(i) line has {nd!r}", nd in res.line, res.line)
check("(i) no '2 pieces'", "2 pieces" not in res.line, res.line)
undone_exactly("(i)", 8)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nall ok")
