#!/usr/bin/env python3
"""Smoke: World Dev free mode — floor plans, doors, storeys: set_room_layout
(gap 1, decisions E1-E3, E5, E17).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 4.
A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop calls it.
Runs use building_models "mesh" (the image-based building path = building_models
'mesh'; the hull path is covered by smoke_world_dev_build.py).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_layout.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: the temp world has no surface library, so
``surface_textures.library_kinds()`` is empty and ``sanitize_layout`` skips the
surface check (its docstring: "surface_kinds empty/None disables the surface
check entirely"). A pre-existing terrain area ``ta_fix_tavern_path`` of kind
"path" (x -15..15, z 11..13, 3 m south of the tavern's south rim z = 8, within
10 m) is saved before run 1 so check_run (g) does not report the path gap and
undo never touches it. Turn 1 creates "Demo Tavern" through the tool at x 0, z 0
with boundary [[-10,-8],[10,-8],[10,8],[-10,8]] and rooms Taproom, Kitchen;
TAP / KIT = the ids the writer gave them (read back by name). POST_CREATE =
its rooms, map3d and entry_room right after the create.

The 17 warning codes of ``sanitize_layout`` (found with
`git grep -a '_warn(' app/core/layout_apply.py`): unknown_room,
reserved_room, nameless_room, duplicate_room, unknown_surface, invalid_layout,
opening_dropped, room_type_dropped, room_not_placed, unknown_opening_target,
room_outside_boundary, no_boundary, room_overlap, unknown_entry_room,
boundary_opening_dropped, stair_dropped, hull_style_unknown. KEPT (warn) are
exactly three: unknown_opening_target, room_outside_boundary, no_boundary;
every other code (including room_overlap) refuses.

  (g) the create line ends "missing: no floor plan" — a run-created place with
      a real room (Taproom), no room layout, no map3d.outline and no building
      model (scene_recipe._compose_stored would return None -> 404).
  (a) turn 2: layout {rooms [{id TAP, x -8, y -6, w 8, d 6, openings [{edge 1,
      at 0.5, width_m 0.9, type door, to KIT}]}, {id KIT, x 0, y -6, w 4,
      d 6}], entry_room TAP} -> ok. Stored Taproom layout x -8, y -6, w 8,
      d 6 and ONE opening with height_m 2.1 and sill_m 0 — the door's
      OPENING_DEFAULTS (2.1, 0.0) that layout_apply._coerce_opening fills in
      for a door without height_m / sill_m; entry_room == TAP. The line names
      "2 rooms (0 new) with 1 opening" (counts of the sent plan; the stair
      count "the place has 0 stair flights" is what is stored). After it, check_run no longer names
      Demo Tavern (both rooms have a layout now).
  (b) a room {id "r_nope", x 0, y 0, w 2, d 2} -> refused, the line has
      "has no room with id 'r_nope'" (unknown_room message); the location
      row is equal to before and the journal row is "refused".
  (d) stairs [{at [-7.4,-5.5], from_level 0, dir_deg 45}] -> refused, the
      line has "staircase(s) were refused" (stair_dropped: dir_deg must be
      0/90/180/270).
  (d2) a layout room {id TAP, ..., room_type "nope"} -> refused, the line has
      "Unknown room type" (room_type_dropped message) and
      "list_catalog room_types"; row unchanged.
  (d3) storey_height_m 6 -> refused, "would be stored as 4.5" — sanitize_layout
      clamps a sent height with round(max(2.6, min(4.5, height)), 2)
      (layout_apply.py, the "storey_height_m" in data branch), 6 -> 4.5.
      storey_height_m 3.2 (turn 3) -> ok, map3d.storey_height_m == 3.2.
  (d4) world_dev_tools._LAYOUT_KEPT_CODES == {"unknown_opening_target",
      "room_outside_boundary", "no_boundary"} (hand-written; room_overlap now
      refuses).
  (d5) a layout with "hull" -> refused ("building panel"); an unknown layout
      key "foo" -> refused; set_room_layout on "nope" -> refused
      "no location".
  (c) turn 3: a new room {name "Guest room", description "A low chamber.",
      x -8, y -6, w 5, d 6, level 1} plus stairs [{at [-7.4,-5.5],
      from_level 0, dir_deg 0}] -> ok; a room named Guest room exists with
      layout.level == 1, map3d.stairs has 1 flight, the line has "(1 new)".
      Taproom and Kitchen keep their (a) layouts (a room the plan omits
      keeps what it had).
  (e) turn 4: the plan names Taproom (x -8, w 8, as in (a)) and Kitchen moved
      to x -2, w 4 (Taproom spans x -8…0, Kitchen -2…2 -> 2 m shared floor,
      both y -6…0, level 0) -> refused naming both rooms ("share floor on
      level 0"), nothing written. And an omitted-room overlap (Kitchen alone
      moved to x -3, w 4, overlapping stored Taproom) is also refused naming
      both rooms, nothing written.
  (f) update_location patch map3d {stairs []} -> refused "use set_room_layout";
      map3d {wall_kind "x"} -> refused "floor-plan editor".
  (j) every sent value the sanitizer would REWRITE refuses (row unchanged),
      each expected stored value derived from world_ops by hand:
      level 1.5 -> int(1.5) = 1 ("would be stored as 1");
      w 5000 -> _metre clamps to +-500 ("would be stored as 500.0");
      opening at 1.7 -> min(max(at, 0), 1) = 1.0; sill_m 9 -> clamp 0…3 = 3.0;
      opening type "gate" -> "must be one of: door, window, passage" (the
      sanitizer would turn it into a door); outline of 2 points -> "outline'
      is unusable" (3…32 points); unknown room key "colour" -> stored as
      "dropped"; boundary opening width_m 50 -> clamp to plan_width_m = 20
      (the boundary spans x -10…10) "would be stored as 20.0"; boundary at 3
      -> 1.0; boundary room "r_nope" -> "is no room of this place"; a room with
      id AND name -> "gives both"; description on an existing room ->
      "use update_location"; storey_height_m "x" and null -> "must be a
      number"; rooms [] and a layout without rooms -> "carries no rooms"
      (sanitize_layout's ValueError). A value within rounding (x -7.999)
      passes (turn 2, the (a) Taproom entry with x -7.999: ok, stored -8.0).
      Shapes the sanitizer would silently ignore or crash on refuse up front
      (_layout_shapes): boundary_openings / stairs as ONE object, and
      boundary_openings as a string -> "must be a list" (sanitize_layout reads
      only lists, so the object would be stored nowhere); a room's openings 5
      -> "must be a list" (len(5) raised a TypeError in sanitize_layout);
      openings [5] -> "must be an object" (_coerce_opening drops a non-dict
      before the drop count); open "false" -> "must be true or false" (a
      truthy string set always_visible/no_walls); props on a room -> "not
      written by a floor plan"; a NEW room named 121 x "a" -> "121 characters
      long" (MAX_NAME_CHARS 120). storey_height_m 3.333 -> ok, stored 3.33
      (round(.., 2), within _LAYOUT_TOL 0.006 = centimetre rounding).
  (k) reach warnings (turn 4, kept, written): only Kitchen sent at x -3
      (Taproom omitted, x -8…0) -> "'Kitchen' shares floor on level 0 with
      'Taproom', which this plan does not name"; stairs replaced by
      [{from_level 7}] -> "from level 7 to level 8, but level 7 has no room"
      and "level 1 has rooms but no stair flight reaches it" (Guest room is
      on level 1, the only flight now starts on 7); then stairs restored to
      the (c) flight -> neither warning. boundary_openings [{edge 0, at 0.5,
      width_m 3, room "Taproom"}] -> stored room == TAP (name resolved).
      A new room Attic on level 2 with flights from 0 and 2 -> "level 2 has
      rooms but no stair flight reaches it" (a flight leads UP from its
      storey; level 2 is reached only by a flight from 1 — the flight from 2
      leads away) and "from level 2 to level 3, but level 3 has no room";
      flights from 0 and 1 -> no "no stair flight reaches".
  (h) discard_preview before the undo lists exactly one line, naming Demo
      Tavern (the only created element). undo turns 4, 3, 2 (newest first)
      -> each complete; Demo Tavern's WHOLE row equals POST_CREATE_ROW; no
      room named Guest room. undo turn 1 -> the place is gone.
  (m) a PRE-EXISTING place Demo Mill (upsert_location outside the run, room
      Mill room without layout, boundary 20 x 16) in a second run: check_run
      before any write does not name it (the run did not create it); turn 1
      lays out Mill room and a new Loft; Demo Walker is put into the Loft.
      discard_preview = exactly the occupant line of Demo Walker in Loft
      (the run created no element; the restore would take the Loft away).
      undo -> complete True, one occupant record (Demo Walker, room = Loft
      id); the Mill row equals PRE_ROW (whole row), no Loft.
  (n) a PRE-EXISTING place Demo Shed (upsert_location outside any run, which
      stores the layout raw; the location write path later mints the
      placement's id) whose
      room Shed room carries a layout with props [{prop_id "demo_crate", at
      [1, 1]}] and model_at [2, 2]; in a third run, a plan moving Shed room to
      x 0 keeps the stored props and model_at unchanged (_carry_room_content;
      the plan names geometry only) and stores x 0; undo -> the whole row
      equals the pre-existing row.
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

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_lay_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_lay_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_lay_inst_"))
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

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


from app.models import terrain  # noqa: E402

terrain.save_area({
    "id": "ta_fix_tavern_path", "kind": "path",
    "polygon": [[-15, 11], [15, 11], [15, 13], [-15, 13]],
})
run = wr.create_run("layout", "m", "p", "u", 60, 600000, building_models="mesh")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def named(name):
    return [l for l in list_locations() if l.get("name") == name]


def plan_state(lid):
    loc = get_location_by_id(lid) or {}
    return copy.deepcopy({"rooms": loc.get("rooms"), "map3d": loc.get("map3d"),
                          "entry_room": loc.get("entry_room")})


def room(lid, rid=None, name=None):
    return next((r for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if (rid and r.get("id") == rid) or (name and r.get("name") == name)), {})


# (g) create
res = call("create_location", {
    "data": {"name": "Demo Tavern", "rooms": [{"name": "Taproom"}, {"name": "Kitchen"}]},
    "x": 0, "z": 0, "boundary": [[-10, -8], [10, -8], [10, 8], [-10, 8]]})
check("(g) create ok", res.ok and res.wrote, res)
check("(g) create line names no floor plan", "missing: no floor plan" in res.line, res.line)
LID = (named("Demo Tavern") or [{}])[0].get("id") or ""
TAP = room(LID, name="Taproom").get("id")
KIT = room(LID, name="Kitchen").get("id")
check("fixture: tavern with two rooms", bool(LID and TAP and KIT))
POST_CREATE = plan_state(LID)
POST_CREATE_ROW = copy.deepcopy(get_location_by_id(LID))


def refused(label, args, *needles, turn=2):
    n = len(wr.steps(run))
    before = get_location_by_id(LID)
    res = call("set_room_layout", args, turn=turn)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    check(f"{label}: journal row refused",
          len(wr.steps(run)) == n + 1 and wr.steps(run)[-1]["kind"] == "refused")
    check(f"{label}: location unchanged", get_location_by_id(LID) == before)
    return res


# (d4)
check("(d4) kept codes", getattr(wt, "_LAYOUT_KEPT_CODES", None) == {
    "unknown_opening_target", "room_outside_boundary", "no_boundary"},
    getattr(wt, "_LAYOUT_KEPT_CODES", None))

# (a)
LAYOUT_A = {"rooms": [
    {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6,
     "openings": [{"edge": 1, "at": 0.5, "width_m": 0.9, "type": "door", "to": KIT}]},
    {"id": KIT, "x": 0, "y": -6, "w": 4, "d": 6}], "entry_room": TAP}
res = call("set_room_layout", {"location_id": LID, "layout": copy.deepcopy(LAYOUT_A)}, turn=2)
check("(a) ok", res.ok and res.wrote, res)
check("(a) line counts", "2 rooms (0 new) with 1 opening;" in res.line
      and "the place has 0 stair flights" in res.line, res.line)
lay = room(LID, rid=TAP).get("layout") or {}
check("(a) taproom rect", (lay.get("x"), lay.get("y"), lay.get("w"), lay.get("d"))
      == (-8, -6, 8, 6), lay)
ops = lay.get("openings") or []
check("(a) one door with defaults", len(ops) == 1 and ops[0].get("height_m") == 2.1
      and ops[0].get("sill_m") == 0, ops)
check("(a) entry_room", (get_location_by_id(LID) or {}).get("entry_room") == TAP)
res = call("check_run", {}, turn=2)
check("(g) check_run no longer names the tavern", res.ok and "Demo Tavern" not in res.line,
      res.line)
AFTER_A = plan_state(LID)

# (b) (d) (d2) (d3) (d5)
refused("(b) unknown room id", {"location_id": LID, "layout": {"rooms": [
    {"id": "r_nope", "x": 0, "y": 0, "w": 2, "d": 2}]}}, "has no room with id 'r_nope'")
refused("(d) stair 45 deg", {"location_id": LID, "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}],
    "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 45}]}},
    "staircase(s) were refused")
refused("(d2) room_type nope", {"location_id": LID, "layout": {"rooms": [
    {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6, "room_type": "nope"}]}},
    "Unknown room type", "list_catalog room_types")
refused("(d3) storey 6", {"location_id": LID, "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}], "storey_height_m": 6}},
    "would be stored as 4.5")
refused("(d5) hull", {"location_id": LID, "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}], "hull": {"style": "x"}}},
    "building panel")
refused("(d5) unknown key", {"location_id": LID, "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}], "foo": 1}}, "foo")
TAP_RECT = {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}
for label, rooms_or_layout, needle in [
    ("(j) level 1.5", [dict(TAP_RECT, level=1.5)], "would be stored as 1"),
    ("(j) w 5000", [dict(TAP_RECT, w=5000)], "would be stored as 500.0"),
    ("(j) opening at 1.7", [dict(TAP_RECT, openings=[
        {"edge": 1, "at": 1.7, "width_m": 0.9}])], "would be stored as 1.0"),
    ("(j) sill 9", [dict(TAP_RECT, openings=[
        {"edge": 0, "at": 0.5, "width_m": 1.2, "type": "window", "sill_m": 9}])],
     "would be stored as 3.0"),
    ("(j) type gate", [dict(TAP_RECT, openings=[
        {"edge": 1, "at": 0.5, "width_m": 0.9, "type": "gate"}])],
     "must be one of: door, window, passage"),
    ("(j) outline 2 points", [dict(TAP_RECT, outline=[[0, 0], [8, 0]])],
     "outline' is unusable"),
    ("(j) unknown room key", [dict(TAP_RECT, colour="red")],
     "'rooms[0].colour' would be stored as \"dropped\""),
    ("(j) id and name", [dict(TAP_RECT, name="Taproom")], "gives both"),
    ("(j) description on existing", [dict(TAP_RECT, description="x")],
     "use update_location"),
    ("(j) bo width 50", {"rooms": [TAP_RECT], "boundary_openings": [
        {"edge": 0, "at": 0.5, "width_m": 50}]}, "would be stored as 20.0"),
    ("(j) bo at 3", {"rooms": [TAP_RECT], "boundary_openings": [
        {"edge": 0, "at": 3, "width_m": 3}]}, "would be stored as 1.0"),
    ("(j) storey x", {"rooms": [TAP_RECT], "storey_height_m": "x"}, "must be a number"),
    ("(j) storey null", {"rooms": [TAP_RECT], "storey_height_m": None},
     "must be a number"),
    ("(j) rooms []", {"rooms": []}, "carries no rooms"),
    ("(j) bo one object", {"rooms": [TAP_RECT], "boundary_openings":
        {"edge": 0, "at": 0.5, "width_m": 3}}, "'boundary_openings' must be a list"),
    ("(j) bo string", {"rooms": [TAP_RECT], "boundary_openings": "gate"},
     "'boundary_openings' must be a list"),
    ("(j) stairs one object", {"rooms": [TAP_RECT], "stairs":
        {"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0}}, "'stairs' must be a list"),
    ("(j) openings 5", [dict(TAP_RECT, openings=5)], "'rooms[0].openings' must be a list"),
    ("(j) openings true", [dict(TAP_RECT, openings=True)],
     "'rooms[0].openings' must be a list"),
    ("(j) openings [5]", [dict(TAP_RECT, openings=[5])],
     "'rooms[0].openings[0]' must be an object"),
    ("(j) open 'false'", [dict(TAP_RECT, open="false")],
     "'rooms[0].open' must be true or false"),
    ("(j) props on a room", [dict(TAP_RECT, props=[{"prop_id": "nope", "at": [1, 1]}])],
     "not written by a floor plan"),
    ("(j) new room name 121", [{"name": "a" * 121, "x": 0, "y": 0, "w": 2, "d": 2}],
     "121 characters long"),
    ("(j) no rooms", {"entry_room": TAP}, "carries no rooms"),
]:
    lay_j = rooms_or_layout if isinstance(rooms_or_layout, dict) else {"rooms": rooms_or_layout}
    r_j = refused(label, {"location_id": LID, "layout": copy.deepcopy(lay_j)}, needle)
    if "storey" in label:
        check(f"{label}: no 'stored as \"dropped\"' invitation",
              "would be stored as \"dropped\"" not in r_j.line, r_j.line)
res = call("set_room_layout", {"location_id": LID, "layout": {"rooms": [
    dict(copy.deepcopy(LAYOUT_A["rooms"][0]), x=-7.999)]}}, turn=2)
check("(j) rounding passes", res.ok and room(LID, rid=TAP)["layout"]["x"] == -8.0, res)
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [dict(copy.deepcopy(LAYOUT_A["rooms"][0]))], "storey_height_m": 3.333}}, turn=2)
check("(j) storey 3.333 passes as 3.33", res.ok and ((get_location_by_id(LID) or {})
      .get("map3d") or {}).get("storey_height_m") == 3.33, res)
refused("(d5) unknown place", {"location_id": "nope", "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6}]}}, "no location")

# (c) + (d3 ok)
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [{"name": "Guest room", "description": "A low chamber.",
               "x": -8, "y": -6, "w": 5, "d": 6, "level": 1}],
    "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0}],
    "storey_height_m": 3.2}}, turn=3)
check("(c) ok", res.ok and res.wrote, res)
check("(c) line names 1 new", "(1 new)" in res.line, res.line)
guest = room(LID, name="Guest room")
check("(c) guest room on level 1", (guest.get("layout") or {}).get("level") == 1, guest)
m3 = (get_location_by_id(LID) or {}).get("map3d") or {}
check("(c) one flight", len(m3.get("stairs") or []) == 1, m3.get("stairs"))
check("(d3) storey 3.2 stored", m3.get("storey_height_m") == 3.2, m3.get("storey_height_m"))
check("(c) taproom kept its layout",
      room(LID, rid=TAP).get("layout") == next(r for r in AFTER_A["rooms"]
                                               if r.get("id") == TAP).get("layout"))

# (e)
refused("(e) overlap refused", {"location_id": LID, "layout": {"rooms": [
    {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6},
    {"id": KIT, "x": -2, "y": -6, "w": 4, "d": 6}]}},
    "Taproom", "Kitchen", "share floor on level 0")

# (k)
refused("(k) omitted-room overlap refused", {"location_id": LID, "layout": {"rooms": [
    {"id": KIT, "x": -3, "y": -6, "w": 4, "d": 6}]}},
    "'Kitchen' shares floor on level 0 with 'Taproom', which this plan does not name")
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [TAP_RECT], "stairs": [{"at": [-7.4, -5.5], "from_level": 7, "dir_deg": 0}]}},
    turn=4)
check("(k) dangling flight warns", res.ok
      and "from level 7 to level 8, but level 7 has no room" in res.line, res.line)
check("(k) unreached level warns",
      "level 1 has rooms but no stair flight reaches it" in res.line, res.line)
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [TAP_RECT], "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0}],
    "boundary_openings": [{"edge": 0, "at": 0.5, "width_m": 3, "room": "Taproom"}]}},
    turn=4)
check("(k) restored flight: no reach warning", res.ok and "stair flight from" not in res.line
      and "no stair flight reaches" not in res.line, res.line)
bo = ((get_location_by_id(LID) or {}).get("map3d") or {}).get("boundary_openings") or []
check("(k) plot opening stored without room", bo == [{"edge": 0, "at": 0.5, "width_m": 3.0, "type": "passage"}], bo)
check("(k) dropped boundary_openings[].room noted in tool result",
      "boundary_openings[].room is gone" in res.line, res.line)
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [{"name": "Attic", "description": "Under the roof.",
               "x": -8, "y": -6, "w": 5, "d": 6, "level": 2}],
    "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0},
               {"at": [-7.4, -5.5], "from_level": 2, "dir_deg": 0}]}}, turn=4)
check("(k) level 2 with only a flight FROM 2 warns", res.ok
      and "level 2 has rooms but no stair flight reaches it" in res.line
      and "from level 2 to level 3, but level 3 has no room" in res.line, res.line)
res = call("set_room_layout", {"location_id": LID, "layout": {
    "rooms": [{"name": "Attic", "x": -8, "y": -6, "w": 5, "d": 6, "level": 2}],
    "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0},
               {"at": [-7.4, -5.5], "from_level": 1, "dir_deg": 0}]}}, turn=4)
check("(k) flights 0 and 1: every level reached", res.ok
      and "no stair flight reaches" not in res.line, res.line)

# (f)
res = call("update_location", {"id": LID, "patch": {"map3d": {"stairs": []}}}, turn=4)
check("(f) stairs refused", not res.ok and "use set_room_layout" in res.line, res)
res = call("update_location", {"id": LID, "patch": {"map3d": {"wall_kind": "x"}}}, turn=4)
check("(f) wall_kind refused", not res.ok and "floor-plan editor" in res.line, res)

# (h)
prev = wu.discard_preview(run)
check("(h) preview names only the tavern",
      len(prev) == 1 and "Demo Tavern" in prev[0], prev)
for turn in (4, 3, 2):
    rep = wu.undo(run, turn)
    check(f"(h) undo turn {turn} complete", rep.get("complete"), rep)
check("(h) plan == post-create", plan_state(LID) == POST_CREATE,
      (plan_state(LID), POST_CREATE))
check("(h) whole row == post-create", get_location_by_id(LID) == POST_CREATE_ROW,
      (get_location_by_id(LID), POST_CREATE_ROW))
check("(h) guest room gone", not room(LID, name="Guest room"))
rep = wu.undo(run, 1)
check("(h) undo turn 1 complete", rep.get("complete"), rep)
check("(h) tavern gone", not named("Demo Tavern"))

# (m) a pre-existing place, an occupant of a layout-created room
from app.models.character import (save_character_current_location,  # noqa: E402
                                  save_character_current_room, save_character_profile)
from app.models.world import upsert_location  # noqa: E402

upsert_location({"id": "loc_mill", "name": "Demo Mill", "description": "",
                 "rooms": [{"id": "r_mill", "name": "Mill room"}],
                 "map3d": {"boundary": [[-10, -8], [10, -8], [10, 8], [-10, 8]]}},
                sync_world=False)
PRE_ROW = copy.deepcopy(get_location_by_id("loc_mill"))
check("(m) fixture: Demo Mill stored", bool(PRE_ROW))
wr.set_status(run, "accepted")
run = wr.create_run("layout 2", "m", "p", "u", 60, 600000, building_models="mesh")
res = call("check_run", {}, turn=1)
check("(m) check_run does not name a place the run did not create",
      res.ok and "Demo Mill" not in res.line, res.line)
res = call("set_room_layout", {"location_id": "loc_mill", "layout": {"rooms": [
    {"id": "r_mill", "x": -8, "y": -6, "w": 8, "d": 6},
    {"name": "Loft", "description": "A dusty loft.", "x": 0, "y": -6, "w": 4, "d": 6}]}},
    turn=1)
check("(m) layout ok", res.ok and res.wrote and "(1 new)" in res.line, res)
LOFT = room("loc_mill", name="Loft").get("id")
check("(m) Loft created", bool(LOFT))
check("(m) Demo Walker created",
      save_character_profile("Demo Walker", {"name": "Demo Walker"}, create_new=True))
save_character_current_location("Demo Walker", "loc_mill")
save_character_current_room("Demo Walker", LOFT)
prev = wu.discard_preview(run)
check("(m) preview = the occupant line only",
      len(prev) == 1 and "Demo Walker" in prev[0] and "Loft" in prev[0], prev)
rep = wu.undo(run, 1)
check("(m) undo complete", rep.get("complete") is True, rep)
check("(m) one occupant record in the Loft",
      [(s.get("occupant"), s.get("room")) for s in rep.get("skipped") or []]
      == [("Demo Walker", LOFT)], rep.get("skipped"))
check("(m) whole row == pre-existing row", get_location_by_id("loc_mill") == PRE_ROW,
      (get_location_by_id("loc_mill"), PRE_ROW))
check("(m) Loft gone", not room("loc_mill", name="Loft"))

# (n) a named room keeps the props / model anchor other editors placed
upsert_location({"id": "loc_shed", "name": "Demo Shed", "description": "",
                 "rooms": [{"id": "r_shed", "name": "Shed room", "layout": {
                     "x": -4, "y": -3, "w": 4, "d": 3,
                     "props": [{"prop_id": "demo_crate", "at": [1, 1]}],
                     "model_at": [2, 2]}}],
                 "map3d": {"boundary": [[-10, -8], [10, -8], [10, 8], [-10, 8]]}},
                sync_world=False)
SHED_ROW = copy.deepcopy(get_location_by_id("loc_shed"))
shed_pre = room("loc_shed", rid="r_shed").get("layout") or {}
check("(n) fixture: stored props and model_at",
      bool(shed_pre.get("props")) and shed_pre.get("model_at") == [2, 2], shed_pre)
wr.set_status(run, "accepted")
run = wr.create_run("layout 3", "m", "p", "u", 60, 600000, building_models="mesh")
res = call("set_room_layout", {"location_id": "loc_shed", "layout": {"rooms": [
    {"id": "r_shed", "x": 0, "y": -3, "w": 4, "d": 3}]}}, turn=1)
shed = room("loc_shed", rid="r_shed").get("layout") or {}
check("(n) plan ok, moved", res.ok and res.wrote and shed.get("x") == 0, (res, shed))
# upsert_location stores the fixture raw; the write path's _sanitize_props
# mints a placement id for a placement without one — so compare without it.
check("(n) props and model_at carried over",
      [{k: v for k, v in p.items() if k != "id"} for p in shed.get("props") or []]
      == [{"prop_id": "demo_crate", "at": [1.0, 1.0]}]
      and shed.get("model_at") == [2.0, 2.0], shed)
rep = wu.undo(run, 1)
check("(n) undo complete", rep.get("complete") is True, rep)
check("(n) whole row == pre-existing row", get_location_by_id("loc_shed") == SHED_ROW,
      (get_location_by_id("loc_shed"), SHED_ROW))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
