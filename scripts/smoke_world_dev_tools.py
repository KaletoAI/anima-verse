#!/usr/bin/env python3
"""Smoke: World Dev free mode — tool registry: read tools, locations, terrain.

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 5. A temp
world (paths.init BEFORE any world-DB import); no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop
will call it.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: location M "Demo Mill" (description "old"), location G "Demo Inn"
with rooms Hall + Cellar, character "Demo Guest" standing in G's Cellar; a
pre-existing terrain area B (kind grass, z_order 0) whose meta carries one
scatter entry {"density_per_100m2": 2.0} and the label "Meadow".

Run 1, turn 1:

  (a) create_location{data: {name: "Demo Mill", rooms: [{name: "Hall",
      image_prompt: "a hall"}]}, x: 40, z: -310} -> ok. NAMES ARE NOT KEYS
      (create_new): a NEW id != M's id, M's stored record is unchanged. The
      room's "image_prompt" is renamed to "image_prompt_day" (today's apply
      normalisation) -> "a hall". The place stands at (40.0, -310.0)
      (update_location_position rounds to 2 decimals). The line says
      "created location <id>" and warns that the name already exists.
  (b) the first write took the backup: after create_location AND
      add_terrain_area exactly ONE directory under
      <storage>/.cache/world_dev_backups/ and the run's backup_path names it.
  (c) add_terrain_area{kind: "water", polygon: [[0,-400],[100,-400],
      [100,-300],[0,-300]]} -> ok; the stored polygon equals
      terrain.sanitize_area of the same square (the sanitizer rounds to 2
      decimals and keeps the 4 points: [[0.0,-400.0],[100.0,-400.0],
      [100.0,-300.0],[0.0,-300.0]]).
  (d) add_terrain_area{kind: "lava", ...} -> ok False, the journal's newest
      step has kind "refused", and no terrain row was added (count stays).
  (e) update_terrain_area{id: B, z_order: 3, label: "Reeds"} -> ok; stored
      z_order 3, meta.label "Reeds", meta.scatter still the one entry with
      density 2.0 (the stored row is merged, never rebuilt).
  (f) delete_created{kind: "terrain", id: B} -> refused (B was not created by
      this run); delete_created{kind: "terrain", id: <(c)'s area>} -> ok, the
      area is gone and the creating journal entry is marked undone.
  (i) create_location{data: {name: "Demo Bad", indoor: true}} -> refused
      ("indoor" must be a string; create_location_with_extras would call
      .strip() on it AFTER add_location stored the row), no location named
      "Demo Bad" exists and the newest journal step is kind "refused".
  (j) update_location{id: G, patch: {rooms: [Hall only, with its id]}} ->
      refused, the line names "Cellar" and "Demo Guest"; G keeps both rooms.
  (k) update_location{id: M, patch: {description: "agent"}} -> ok;
      place_location{id: M, x: 10, z: 20, yaw: 90} -> ok, stored (10.0, 20.0,
      90.0).
  undo(run, turn=1) newest-first: M back to unplaced and "old"; B back to
      z_order 0 with label "Meadow"; the (a) location gone; M and G untouched
      otherwise. The (f) entry was already undone -> not reversed again.

Run 2 (run 1 closed first), turn 1:

  (h) world_ops._sanitize_map3d is monkeypatched to raise RuntimeError; it
      runs inside create_location_with_extras AFTER add_location stored the
      row (map3d is set from the boundary argument). run_tool raises (a
      non-refusal exception is a hard failure); the place "Demo Crash"
      exists; the journal entry carries delete_location for it; undo(run,
      turn=1) removes it -> no "Demo Crash" left.

Run 3, read tools:

  (g) 40 locations "Demo Spot 00".."Demo Spot 39" -> find_locations{query:
      "Demo Spot"} = 30 location lines + one line "… 10 more — narrow the
      query" (40 - 30 = 10); world_overview{} is at most 1500 characters.
      Read calls are journaled as kind "read".

Run 4 (run 3 accepted first), turn 1:

  (l) add_height_area{polygon: 100 m square, height_m: 4, label: "Hill"} ->
      stored height_m 4.0; update_height_area{height_m: 7} -> 7.0;
      add_terrain_area{kind: "path", stroke: {points [[0,0],[100,0]],
      width_m 10}} -> one path area whose meta keeps the stroke recipe;
      arguments that are no object, an unknown tool name and a string
      coordinate are refused; undo(run) -> the hill and the path are gone,
      complete True (the update is reversed before the create, newest-first).

Run 5 (run 4 rolled back first), turn 1 — the findings of the Task 5 review:

  (m) Fixture "Demo Tower" written through update_location_with_extras:
      Hall {layout x 0, y 0, w 6, d 5 (level 0), activities [{"name": "Rest"}]},
      Attic {layout x 0, y 0, w 6, d 5, level 1}. floor_levels() -> {1}
      (level 0 has no corridor without map3d.ground_corridor), so the
      writer adds "__floor__1". update_location{patch: {rooms: [{id Hall,
      name, description "hall!"}, {id Attic, name, description "attic!"}]}}
      sends NO layout/activities -> ok; the kept rooms are the stored rooms
      with the sent keys laid over them, so Hall/Attic keep exactly their
      stored layout, Hall its activities, "__floor__1" is still stored, the
      descriptions are "hall!"/"attic!". undo -> the old descriptions.
  (n) create_location{data: {name: "Demo Null", description: null}} -> ok
      (null = "not given"), stored description "" — never an exception;
      update_location{patch: {description: null}} -> refused (nothing left).
  (o) create_location with rooms [{}] -> refused (a room needs a name);
      create_location with x 1e12 -> refused (beyond ±100 000 m); neither
      stores a place.
  (p) create_location "Demo Home"; save "Demo Guest"'s home_location = it;
      delete_created{location} -> refused, the line names "Demo Guest" and
      "home"; home cleared -> delete_created ok, the place is gone; a second
      delete_created -> refused (the creating entry is undone).

  (p) continued: home cleared, known_locations = [it] -> refused naming
      "known place"; cleared, a schedule slot {"hour": 8, "location": it} ->
      refused naming "schedule"; schedule cleared -> the delete goes through.

Run 7 (run 6 rolled back first), turn 1:

  (t) update_location / place_location on "loc_nope", update_terrain_area
      on "ta_nope", update_height_area on "ha_nope" as the run's FIRST write
      calls -> all refused ("no ..."), and the run has no backup_path and no
      new backup directory (the cheap existence pre-check runs before the
      backup).
  (q) create_location with rooms [{id a, A}, {id a, B}] -> refused ("repeats
      the id 'a'"); with a room id "__ground__" -> refused ("reserved");
      update_location on Demo Tower with Hall's id twice -> refused, the tower
      record unchanged; no location was added.
  (r) MAX_NAME_CHARS = 120: a 121-character location name and a
      121-character room name are refused ("at most 120"); a 120-character
      name is stored.
  (s) loc_m gets map3d {floors: 2} (the sanitizer keeps an int > 0);
      update_location map3d {floors: "many"} -> refused, the line names
      "floors", stored floors stays 2 (before the fix the merge dropped it);
      map3d {bogus: 1} -> refused (unknown key); {floors: 3} -> ok, stored 3.
      undo -> floors 2 again, the 120-character place gone.

Run 8, turn 1:

  (u) like (h), but the writer raises ValueError (a refusal type): run_tool
      returns ok False, wrote True, and the line is "error: simulated bad
      value; partly written: location <id> exists — ... delete_created ...";
      the place is stored; undo(run, turn=1) removes it.

(h)/(u) patch world_ops._sanitize_map3d so that only the WRITER's call fails;
the tool's own map3d pre-check calls the same function first and gets the
real one.

Run 2 additionally asserts for (h): the step is kind "write", state "done"
and its line starts "failed:" (the writing() reconcile found the row).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_tools.py
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_tools_clips_")

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_tools_"))
paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.character import (save_character_current_location,  # noqa: E402
                                  save_character_current_room,
                                  save_character_profile)
from app.models.world import (add_location, get_location_by_id,  # noqa: E402
                              list_locations, upsert_location)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def newest_step(run_id):
    return wr.steps(run_id)[-1]


def by_name(name):
    return [loc for loc in list_locations() if loc.get("name") == name]


# ── Fixture ──────────────────────────────────────────────────────────────
upsert_location({"id": "loc_m", "name": "Demo Mill", "description": "old",
                 "rooms": []}, sync_world=False)
inn = add_location("Demo Inn", "an inn", rooms=[{"name": "Hall"}, {"name": "Cellar"}])
hall = next(r for r in inn["rooms"] if r["name"] == "Hall")
cellar = next(r for r in inn["rooms"] if r["name"] == "Cellar")
save_character_profile("Demo Guest", {"name": "Demo Guest"}, create_new=True)
save_character_current_location("Demo Guest", inn["id"])
save_character_current_room("Demo Guest", cellar["id"])
area_b = terrain.save_area({"kind": "grass",
                            "polygon": [[200, 0], [300, 0], [300, 100], [200, 100]],
                            "meta": {"label": "Meadow",
                                     "scatter": [{"density_per_100m2": 2.0}]}})
B = area_b["id"]
m_before = copy.deepcopy(get_location_by_id("loc_m"))
inn_before = copy.deepcopy(get_location_by_id(inn["id"]))
b_before = copy.deepcopy(terrain.get_area(B))

# ── Run 1 ────────────────────────────────────────────────────────────────
print("run 1")
run = wr.create_run("build", "m", "p", "u", 40, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)

# (a)
res = wt.run_tool(ctx, "create_location",
                  {"data": {"name": "Demo Mill",
                            "rooms": [{"name": "Hall", "image_prompt": "a hall"}]},
                   "x": 40, "z": -310})
check("(a) create ok", res.ok and res.wrote, res)
mills = by_name("Demo Mill")
new = [l for l in mills if l["id"] != "loc_m"]
check("(a) a second place named Demo Mill", len(mills) == 2 and len(new) == 1,
      [l["id"] for l in mills])
new_id = new[0]["id"] if new else ""
check("(a) M untouched", get_location_by_id("loc_m") == m_before)
new_loc = get_location_by_id(new_id) or {}
hall_new = next((r for r in new_loc.get("rooms") or [] if r.get("name") == "Hall"), {})
check("(a) image_prompt -> image_prompt_day", hall_new.get("image_prompt_day") == "a hall",
      hall_new)
check("(a) placed at (40, -310)",
      (new_loc.get("pos_x"), new_loc.get("pos_z")) == (40.0, -310.0),
      (new_loc.get("pos_x"), new_loc.get("pos_z")))
check("(a) line names the id", f"created location {new_id}" in res.line, res.line)
check("(a) line warns about the taken name", "already exists" in res.line, res.line)

# (c)
square = [[0, -400], [100, -400], [100, -300], [0, -300]]
res = wt.run_tool(ctx, "add_terrain_area", {"kind": "water", "polygon": square})
check("(c) add_terrain_area ok", res.ok and res.wrote, res)
created_area = [e for e in wr.entries(run) if e["tool"] == "add_terrain_area"]
A = created_area[0]["target_id"] if created_area else ""
stored_a = terrain.get_area(A) or {}
expect_poly = terrain.sanitize_area({"kind": "water", "polygon": square})["polygon"]
check("(c) stored polygon == sanitize_area", stored_a.get("polygon") == expect_poly,
      (stored_a.get("polygon"), expect_poly))
check("(c) hand-derived polygon", expect_poly == [[0.0, -400.0], [100.0, -400.0],
                                                   [100.0, -300.0], [0.0, -300.0]],
      expect_poly)

# (b)
roots = STORAGE / ".cache" / "world_dev_backups"
dirs = [p for p in roots.iterdir() if p.is_dir()] if roots.is_dir() else []
check("(b) exactly one backup after two writes", len(dirs) == 1, dirs)
check("(b) run names the backup",
      dirs and (wr.get_run(run) or {}).get("backup_path") == str(dirs[0]),
      (wr.get_run(run) or {}).get("backup_path"))

# (d)
n_areas = len(terrain.list_areas())
res = wt.run_tool(ctx, "add_terrain_area", {"kind": "lava", "polygon": square})
check("(d) unknown kind refused", not res.ok and not res.wrote, res)
check("(d) journal kind refused", newest_step(run)["kind"] == "refused", newest_step(run))
check("(d) nothing written", len(terrain.list_areas()) == n_areas)

# (e)
res = wt.run_tool(ctx, "update_terrain_area", {"id": B, "z_order": 3, "label": "Reeds"})
check("(e) update ok", res.ok, res)
b_now = terrain.get_area(B) or {}
check("(e) z_order 3 + label Reeds",
      b_now.get("z_order") == 3 and (b_now.get("meta") or {}).get("label") == "Reeds", b_now)
check("(e) scatter kept",
      (b_now.get("meta") or {}).get("scatter") == b_before["meta"]["scatter"]
      and len(b_before["meta"]["scatter"]) == 1
      and b_before["meta"]["scatter"][0].get("density_per_100m2") == 2.0,
      (b_now.get("meta"), b_before.get("meta")))

# (f)
res = wt.run_tool(ctx, "delete_created", {"kind": "terrain", "id": B})
check("(f) delete_created of a pre-existing area refused", not res.ok, res)
check("(f) B still there", terrain.get_area(B) is not None)
res = wt.run_tool(ctx, "delete_created", {"kind": "terrain", "id": A})
check("(f) delete_created of the run's own area ok", res.ok, res)
check("(f) A gone", terrain.get_area(A) is None)
creating = [e for e in wr.steps(run) if e["tool"] == "add_terrain_area"
            and e["target_id"] == A]
check("(f) creating entry marked undone",
      creating and creating[0].get("undone_at"), creating)

# (i)
n_steps = len(wr.steps(run))
res = wt.run_tool(ctx, "create_location", {"data": {"name": "Demo Bad", "indoor": True}})
check("(i) indoor true refused", not res.ok and not res.wrote, res)
check("(i) nothing written", by_name("Demo Bad") == [])
check("(i) one refused step",
      len(wr.steps(run)) == n_steps + 1 and newest_step(run)["kind"] == "refused",
      newest_step(run))

# (j)
res = wt.run_tool(ctx, "update_location",
                  {"id": inn["id"], "patch": {"rooms": [{"id": hall["id"], "name": "Hall"}]}})
check("(j) removing an occupied room refused", not res.ok, res)
check("(j) line names room and character",
      "Cellar" in res.line and "Demo Guest" in res.line, res.line)
check("(j) G keeps both rooms",
      {r["id"] for r in get_location_by_id(inn["id"])["rooms"]}
      == {r["id"] for r in inn_before["rooms"]})

# (k)
res = wt.run_tool(ctx, "update_location", {"id": "loc_m", "patch": {"description": "agent"}})
check("(k) update_location ok", res.ok and get_location_by_id("loc_m")["description"] == "agent",
      res)
res = wt.run_tool(ctx, "place_location", {"id": "loc_m", "x": 10, "z": 20, "yaw": 90})
m_now = get_location_by_id("loc_m")
check("(k) place_location ok", res.ok and (m_now.get("pos_x"), m_now.get("pos_z"),
                                            m_now.get("yaw_deg")) == (10.0, 20.0, 90.0),
      (res, m_now.get("pos_x"), m_now.get("pos_z"), m_now.get("yaw_deg")))

rep = wu.undo(run, turn=1)
check("undo complete", rep["complete"], rep)
m_after = get_location_by_id("loc_m")
check("undo: M unplaced and 'old' again",
      m_after.get("description") == "old" and m_after.get("pos_x") is None, m_after)
b_after = terrain.get_area(B) or {}
check("undo: B back to z_order 0 / Meadow / scatter",
      b_after == b_before, (b_after, b_before))
check("undo: the new Demo Mill gone, M stays",
      [l["id"] for l in by_name("Demo Mill")] == ["loc_m"], by_name("Demo Mill"))
check("undo: (f) entry not reversed twice",
      all(s != creating[0]["seq"] for s in rep["reversed"]) if creating else False, rep)
check("undo: inn untouched", get_location_by_id(inn["id"]) == inn_before)
wr.set_status(run, "rolled_back")

# ── Run 2: (h) a writer failing after the row was stored ─────────────────
print("run 2")
run2 = wr.create_run("crash", "m", "p", "u", 40, 300000)
ctx2 = wt.ToolCtx(run_id=run2, turn=1)
from app.core import world_ops  # noqa: E402
_orig = world_ops._sanitize_map3d


def _boom(raw):
    # Only the writer's own call crashes; the tool's map3d pre-check
    # (world_dev_tools._map3d_dropped) calls the same sanitizer before the
    # write and gets the real one.
    if sys._getframe(1).f_globals.get("__name__") != "app.core.world_ops":
        return _orig(raw)
    raise RuntimeError("simulated writer crash")


world_ops._sanitize_map3d = _boom
raised = None
try:
    wt.run_tool(ctx2, "create_location",
                {"data": {"name": "Demo Crash"},
                 "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
except RuntimeError as e:
    raised = e
finally:
    world_ops._sanitize_map3d = _orig
check("(h) the hard failure propagates", raised is not None)
crash = by_name("Demo Crash")
check("(h) the row was stored", len(crash) == 1, crash)
ents = wr.entries(run2)
check("(h) journal carries delete_location for it",
      crash and ents and (ents[0].get("inverse") or {}).get("op") == "delete_location"
      and ents[0]["inverse"].get("id") == crash[0]["id"], ents)
wu.undo(run2, turn=1)
h_step = next((s for s in wr.steps(run2) if s["tool"] == "create_location"), {})
check("(h) step kind write / state done / line 'failed:'",
      h_step.get("kind") == "write" and h_step.get("state") == "done"
      and str(h_step.get("line") or "").startswith("failed:"), h_step)
check("(h) undo removed it", by_name("Demo Crash") == [])
wr.set_status(run2, "rolled_back")

# ── Run 3: read tools ────────────────────────────────────────────────────
print("run 3")
for i in range(40):
    upsert_location({"id": f"loc_s{i:02d}", "name": f"Demo Spot {i:02d}",
                     "description": "", "rooms": []}, sync_world=False)
run3 = wr.create_run("look", "m", "p", "u", 40, 300000)
ctx3 = wt.ToolCtx(run_id=run3, turn=1)
res = wt.run_tool(ctx3, "find_locations", {"query": "Demo Spot"})
lines = res.line.split("\n")
loc_lines = [ln for ln in lines if ln.startswith("loc_s")]
check("(g) 30 location lines", len(loc_lines) == 30, len(loc_lines))
check("(g) '10 more' line", any("… 10 more — narrow the query" in ln for ln in lines),
      lines[-2:])
check("(g) journaled as read", newest_step(run3)["kind"] == "read", newest_step(run3))
res = wt.run_tool(ctx3, "world_overview", {})
check("(g) world_overview <= 1500 chars", res.ok and len(res.line) <= 1500, len(res.line))
for name, args in (("get_location", {"id": "loc_m"}),
                   ("map_region", {"min_x": -50, "min_z": -50, "max_x": 400, "max_z": 400}),
                   ("find_characters", {}),
                   ("get_character", {"name": "Demo Guest"})):
    res = wt.run_tool(ctx3, name, args)
    check(f"(g) {name} ok and <= 1500 chars", res.ok and len(res.line) <= 1500, res)
check("(g) no backup for a read-only run", not (wr.get_run(run3) or {}).get("backup_path"))

# ── Run 4: height areas, a stroke, malformed calls ───────────────────────
print("run 4")
wr.set_status(run3, "accepted")
run4 = wr.create_run("hills", "m", "p", "u", 40, 300000)
ctx4 = wt.ToolCtx(run_id=run4, turn=1)
from app.models.heightfield import list_height_areas  # noqa: E402
res = wt.run_tool(ctx4, "add_height_area",
                  {"polygon": [[500, 500], [600, 500], [600, 600], [500, 600]],
                   "height_m": 4, "label": "Hill"})
hills = [h for h in list_height_areas() if (h.get("meta") or {}).get("label") == "Hill"]
check("(l) add_height_area stores height 4.0",
      res.ok and len(hills) == 1 and hills[0]["height_m"] == 4.0, (res, hills))
H = hills[0]["id"] if hills else ""
res = wt.run_tool(ctx4, "update_height_area", {"id": H, "height_m": 7})
check("(l) update_height_area -> 7.0",
      res.ok and next(h for h in list_height_areas() if h["id"] == H)["height_m"] == 7.0, res)
res = wt.run_tool(ctx4, "add_terrain_area",
                  {"kind": "path", "stroke": {"points": [[0, 0], [100, 0]], "width_m": 10}})
paths_ = [a for a in terrain.list_areas() if a["kind"] == "path"]
check("(l) stroke area stored with its recipe",
      res.ok and len(paths_) == 1 and "stroke" in paths_[0]["meta"], (res, paths_))
res = wt.run_tool(ctx4, "add_terrain_area", "not an object")
check("(l) non-object arguments refused", not res.ok and newest_step(run4)["kind"] == "refused",
      res)
res = wt.run_tool(ctx4, "no_such_tool", {})
check("(l) unknown tool refused", not res.ok and "unknown tool" in res.line, res)
res = wt.run_tool(ctx4, "place_location", {"id": "loc_m", "x": "10", "z": 0})
check("(l) a string coordinate refused", not res.ok, res)
rep = wu.undo(run4)
check("(l) undo removes hill and path",
      rep["complete"] and not [h for h in list_height_areas() if h["id"] == H]
      and not [a for a in terrain.list_areas() if a["kind"] == "path"], rep)
wr.set_status(run4, "rolled_back")

# ── Run 5: rooms merge, nulls, nameless rooms, delete with a reference ───
print("run 5")
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.models.character import (get_character_config,  # noqa: E402
                                  get_character_daily_schedule,
                                  save_character_config,
                                  save_character_daily_schedule)
tower = add_location("Demo Tower", "a tower", rooms=[{"name": "Hall"}, {"name": "Attic"}])
t_hall = next(r for r in tower["rooms"] if r["name"] == "Hall")["id"]
t_attic = next(r for r in tower["rooms"] if r["name"] == "Attic")["id"]
cur_rooms = get_location_by_id(tower["id"])["rooms"]
for r in cur_rooms:
    if r["id"] == t_hall:
        r["layout"] = {"x": 0, "y": 0, "w": 6, "d": 5}
        r["activities"] = [{"name": "Rest"}]
        r["description"] = "hall"
    elif r["id"] == t_attic:
        r["layout"] = {"x": 0, "y": 0, "w": 6, "d": 5, "level": 1}
        r["description"] = "attic"
update_location_with_extras(tower["id"], {"rooms": cur_rooms})
t_before = copy.deepcopy(get_location_by_id(tower["id"]))
rb = {r["id"]: r for r in t_before["rooms"]}
check("(m) fixture: layouts stored + corridor __floor__1",
      rb[t_hall].get("layout") and rb[t_attic].get("layout")
      and "__floor__1" in rb and rb[t_hall].get("activities") == [{"name": "Rest"}],
      t_before["rooms"])
run5 = wr.create_run("rooms", "m", "p", "u", 40, 300000)
ctx5 = wt.ToolCtx(run_id=run5, turn=1)
res = wt.run_tool(ctx5, "update_location",
                  {"id": tower["id"], "patch": {"rooms": [
                      {"id": t_hall, "name": "Hall", "description": "hall!"},
                      {"id": t_attic, "name": "Attic", "description": "attic!"}]}})
ra = {r["id"]: r for r in get_location_by_id(tower["id"])["rooms"]}
check("(m) rooms patch ok", res.ok and res.wrote, res)
check("(m) descriptions changed",
      ra.get(t_hall, {}).get("description") == "hall!"
      and ra.get(t_attic, {}).get("description") == "attic!", ra)
check("(m) layouts kept",
      ra.get(t_hall, {}).get("layout") == rb[t_hall]["layout"]
      and ra.get(t_attic, {}).get("layout") == rb[t_attic]["layout"], ra)
check("(m) Hall activities kept",
      ra.get(t_hall, {}).get("activities") == [{"name": "Rest"}], ra.get(t_hall))
check("(m) corridor __floor__1 still stored", "__floor__1" in ra, sorted(ra))
rep = wu.undo(run5, turn=1)
ru = {r["id"]: r for r in get_location_by_id(tower["id"])["rooms"]}
check("(m) undo restores the old descriptions",
      rep["complete"] and ru[t_hall].get("description") == "hall"
      and ru[t_attic].get("description") == "attic", (rep, ru))
wr.set_status(run5, "rolled_back")

run6 = wr.create_run("nulls", "m", "p", "u", 40, 300000)
ctx6 = wt.ToolCtx(run_id=run6, turn=1)
# (n)
raised = None
try:
    res = wt.run_tool(ctx6, "create_location",
                      {"data": {"name": "Demo Null", "description": None}})
except Exception as e:  # noqa: BLE001
    raised = e
check("(n) description null is no exception", raised is None, raised)
nulls = by_name("Demo Null")
check("(n) stored with description ''",
      raised is None and res.ok and len(nulls) == 1 and nulls[0].get("description") == "",
      (res, nulls))
res = wt.run_tool(ctx6, "update_location", {"id": "loc_m", "patch": {"description": None}})
check("(n) null-only patch refused", not res.ok and not res.wrote, res)
# (o)
res = wt.run_tool(ctx6, "create_location", {"data": {"name": "Demo Odd", "rooms": [{}]}})
check("(o) nameless room refused", not res.ok and by_name("Demo Odd") == [], res)
res = wt.run_tool(ctx6, "create_location", {"data": {"name": "Demo Far"}, "x": 1e12, "z": 5})
check("(o) x 1e12 refused", not res.ok and by_name("Demo Far") == [], res)
# (p)
res = wt.run_tool(ctx6, "create_location", {"data": {"name": "Demo Home"}})
home = by_name("Demo Home")
HID = home[0]["id"] if home else ""
check("(p) Demo Home created", res.ok and len(home) == 1, res)
check("(p) home reference saved",
      save_character_config("Demo Guest", {"home_location": HID})
      and get_character_config("Demo Guest").get("home_location") == HID)
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) delete with a home reference refused",
      not res.ok and "Demo Guest" in res.line and "home" in res.line
      and len(by_name("Demo Home")) == 1, res)
save_character_config("Demo Guest", {"home_location": ""})
check("(p) known place saved",
      save_character_config("Demo Guest", {"known_locations": [HID]})
      and get_character_config("Demo Guest").get("known_locations") == [HID])
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) delete with a known-place reference refused",
      not res.ok and "Demo Guest" in res.line and "known place" in res.line
      and len(by_name("Demo Home")) == 1, res)
save_character_config("Demo Guest", {"known_locations": []})
check("(p) schedule slot saved",
      save_character_daily_schedule("Demo Guest", {"enabled": True,
                                                    "slots": [{"hour": 8, "location": HID}]})
      and any(s.get("location") == HID
              for s in get_character_daily_schedule("Demo Guest").get("slots") or []),
      get_character_daily_schedule("Demo Guest"))
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) delete with a schedule reference refused",
      not res.ok and "Demo Guest" in res.line and "schedule" in res.line
      and len(by_name("Demo Home")) == 1, res)
save_character_daily_schedule("Demo Guest", {"enabled": False, "slots": []})
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) delete after clearing ok", res.ok and by_name("Demo Home") == [], res)
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) second delete refused", not res.ok, res)
wu.undo(run6, turn=1)
wr.set_status(run6, "rolled_back")

# ── Run 7: existence pre-check, room ids, name length, map3d ─────────────
print("run 7")
run7 = wr.create_run("checks", "m", "p", "u", 40, 300000)
ctx7 = wt.ToolCtx(run_id=run7, turn=1)
n_backups = len([p for p in roots.iterdir() if p.is_dir()])
# (t)
for name, args in (("update_location", {"id": "loc_nope", "patch": {"description": "x"}}),
                   ("place_location", {"id": "loc_nope", "x": 1, "z": 2}),
                   ("update_terrain_area", {"id": "ta_nope", "z_order": 1}),
                   ("update_height_area", {"id": "ha_nope", "height_m": 1})):
    res = wt.run_tool(ctx7, name, args)
    check(f"(t) {name} on a missing id refused", not res.ok and "no " in res.line, res)
check("(t) no backup taken for the refused first writes",
      not (wr.get_run(run7) or {}).get("backup_path")
      and len([p for p in roots.iterdir() if p.is_dir()]) == n_backups,
      (wr.get_run(run7) or {}).get("backup_path"))
# (q)
n_locs = len(list_locations())
res = wt.run_tool(ctx7, "create_location",
                  {"data": {"name": "Demo Twin", "rooms": [{"id": "a", "name": "A"},
                                                          {"id": "a", "name": "B"}]}})
check("(q) create with a repeated room id refused",
      not res.ok and "repeats the id 'a'" in res.line and by_name("Demo Twin") == [], res)
res = wt.run_tool(ctx7, "create_location",
                  {"data": {"name": "Demo Ground", "rooms": [{"id": "__ground__", "name": "G"}]}})
check("(q) create with a reserved room id refused",
      not res.ok and "reserved" in res.line and by_name("Demo Ground") == [], res)
tower_now = copy.deepcopy(get_location_by_id(tower["id"]))
res = wt.run_tool(ctx7, "update_location",
                  {"id": tower["id"], "patch": {"rooms": [
                      {"id": t_hall, "name": "Hall"}, {"id": t_hall, "name": "X"},
                      {"id": t_attic, "name": "Attic"}]}})
check("(q) update with a repeated room id refused, tower unchanged",
      not res.ok and "repeats the id" in res.line
      and get_location_by_id(tower["id"]) == tower_now, res)
check("(q) nothing created", len(list_locations()) == n_locs)
# (r) MAX_NAME_CHARS = 120: 121 refused, exactly 120 stored
res = wt.run_tool(ctx7, "create_location", {"data": {"name": "D" * 121}})
check("(r) 121-character name refused", not res.ok and "at most 120" in res.line
      and by_name("D" * 121) == [], res)
res = wt.run_tool(ctx7, "create_location",
                  {"data": {"name": "Demo Rooms", "rooms": [{"name": "R" * 121}]}})
check("(r) 121-character room name refused", not res.ok and by_name("Demo Rooms") == [], res)
res = wt.run_tool(ctx7, "create_location", {"data": {"name": "E" * 120}})
check("(r) 120-character name stored", res.ok and len(by_name("E" * 120)) == 1, res)
# (s) map3d: fixture floors 2 (sanitizer keeps int > 0)
update_location_with_extras("loc_m", {"map3d": {"floors": 2}})
check("(s) fixture floors 2", (get_location_by_id("loc_m").get("map3d") or {}).get("floors") == 2,
      get_location_by_id("loc_m").get("map3d"))
res = wt.run_tool(ctx7, "update_location", {"id": "loc_m", "patch": {"map3d": {"floors": "many"}}})
check("(s) floors 'many' refused and named",
      not res.ok and "floors" in res.line
      and (get_location_by_id("loc_m").get("map3d") or {}).get("floors") == 2, res)
res = wt.run_tool(ctx7, "update_location", {"id": "loc_m", "patch": {"map3d": {"bogus": 1}}})
check("(s) unknown map3d key refused", not res.ok and "bogus" in res.line, res)
res = wt.run_tool(ctx7, "update_location", {"id": "loc_m", "patch": {"map3d": {"floors": 3}}})
check("(s) floors 3 stored",
      res.ok and (get_location_by_id("loc_m").get("map3d") or {}).get("floors") == 3, res)
rep = wu.undo(run7, turn=1)
check("(s) undo: floors back to 2, the 120-char place gone",
      rep["complete"] and (get_location_by_id("loc_m").get("map3d") or {}).get("floors") == 2
      and by_name("E" * 120) == [], rep)
wr.set_status(run7, "rolled_back")

# ── Run 8: (u) a refusal-type exception after the row was stored ─────────
print("run 8")
run8 = wr.create_run("partial", "m", "p", "u", 40, 300000)
ctx8 = wt.ToolCtx(run_id=run8, turn=1)


def _bad(raw):
    if sys._getframe(1).f_globals.get("__name__") != "app.core.world_ops":
        return _orig(raw)  # the tool's pre-check, see _boom
    raise ValueError("simulated bad value")


world_ops._sanitize_map3d = _bad
try:
    res = wt.run_tool(ctx8, "create_location",
                      {"data": {"name": "Demo Partial"},
                       "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
finally:
    world_ops._sanitize_map3d = _orig
part = by_name("Demo Partial")
PID = part[0]["id"] if part else "?"
check("(u) ok False, wrote True", not res.ok and res.wrote, res)
check("(u) the row was stored", len(part) == 1, part)
check("(u) line names what stayed",
      res.line.startswith("error: simulated bad value")
      and f"partly written: location {PID} exists" in res.line
      and "delete_created" in res.line, res.line)
wu.undo(run8, turn=1)
check("(u) undo removed it", by_name("Demo Partial") == [])
wr.set_status(run8, "rolled_back")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
