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
      delete_created -> refused (the creating entry is undone). Before the
      successful delete (references cleared) "Demo Guest" is put INTO the
      place -> refused, the line names "Demo Guest (stands there)" (a
      character in a deleted place would be stranded); moved out (and the
      known place the visit added cleared again) -> ok.

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

Task 6 — character tools (runs 9-12):

  Fixture: "Demo Lakeside" with room Bedroom (add_location); "Demo Other"
  (human-roleplay, dialogue_style "terse", personality "calm" ->
  soul/personality.md = "calm\n"); a catalog piece "Demo Boots" (feet).
  (v) create_character{data: Demo Lake, human-roleplay, outfit "Daily" =
      2 NEW pieces (Tunic top, Trousers bottom) + {item_id: Boots}, home
      "Demo Lakeside", home_room "Bedroom"} -> row exists, home_location =
      Lakeside id, home_room = Bedroom id; the creating entry's inverse is
      delete_character with exactly 2 items (Tunic, Trousers — the reused
      Boots is not created, so not listed); Boots is in Demo Lake's
      inventory. Same name again -> refused "already exists"; "a/b" and an
      unknown item_id -> refused, nothing created.
      update_character{Demo Other, {dialogue_style: "chatty"}} -> one
      restore_character step, inverse profile {dialogue_style: "terse"},
      written profile {dialogue_style: "chatty"}. Refused: an unknown key,
      the soul field character_personality without "soul:", "soul:bogus",
      the readonly current_location, age "old" (a number field).
      undo(run) -> complete; Demo Lake gone, Tunic + Trousers deleted, Boots
      kept, dialogue_style "terse" again.
  (w) the same create, then one new piece added to Demo Other's inventory
      -> undo: Demo Lake gone, that piece and its inventory row stay with
      skip reason "item still in use", the other new piece is deleted.
  (x) soul: presence.md removed first, beliefs.md "beliefs before",
      tasks.md "tasks before". ONE update with soul:character_personality
      "bold and loud  \n\n", soul:character_presence, soul:character_task
      -> stored "bold and loud\n" (rstrip + newline); three restore_soul
      steps with before_text {personality "calm\n", presence None, tasks
      "tasks before\n"}. A human then writes beliefs.md and tasks.md ->
      undo: personality.md == "calm\n" exactly, presence.md absent again,
      beliefs.md is the human's text, tasks.md is the human's text with
      the one skip "changed since".
  (y) soul_owner patched to name a leader -> the shared section is refused
      naming the leader. update_character home/home_room/schedule [8
      Lakeside "fishing"] -> home = Lakeside/Bedroom, one slot at Lakeside,
      Lakeside known; one restore_home_schedule step. delete_created of the
      pre-existing Demo Other -> refused; of "Demo Brief" created in this
      turn -> ok, its one new piece deleted. undo -> home_schedule_state is
      the one read before.
  (z) apply_character contract: save_character_profile -> False (new
      "Demo Fail"), save_character_config -> False (a generable config
      field "popularity"; and a home_location edit, the save inside
      _apply_home_and_schedule) -> ValueError each, no Demo Fail row; the
      soul markdown of an apply goes through soul_writer.write_text.

Task 6 review findings (runs 13-16, after (z); Demo Other is human-roleplay):

  (aa) field values by template type: chat_mode is a select with the fixed
       options "" / "rp_first" -> "banana" refused, the line lists "rp_first";
       importance has the NUMBER options 1/2/3 -> "9", the string "2" and
       true refused, the number 2 stored as the int 2; gender "zzz" refused;
       birthday is a season_day -> [1, 2, {"x": 1}] refused, "spring:31"
       refused (the default calendar's spring has 30 days), "summer:14"
       stored. No refused call leaves a write row: 2 write rows in the run
       (importance, birthday). undo -> complete.
  (ab) one spelling per home value: patch {home: Demo Lakeside,
       home_location: Atlantis} -> refused "send 'home_location' as 'home'";
       {home: "Atlantis"} -> refused "no place", NO write row (the target is
       checked before anything is written); {home_room: "Bedroom"} while
       Demo Other has no home -> refused "needs a home"; {home: Demo
       Lakeside, home_room: "Cellar"} -> refused, the line lists "Bedroom";
       schedule [{hour 9, location "Atlantis"}] -> refused; create_character
       with the argument home AND data.home_location -> refused "given
       twice". Run 13 still has exactly its 2 write rows.
  (ac) templates: the offered ones are the selectable templates without the
       temporary_npc feature = animal-default, human-default, human-roleplay.
       create_character with template npc-temporary -> refused, the line
       names "human-roleplay"; base-character (not selectable) -> refused;
       neither creates a row.
  (ad) a foreign character must never be claimed (finding 2):
       1. a foreign "Demo Race" stored during step.prepare() (the backup
          window) -> the re-check refuses "already exists"; no write row
          names Demo Race; undo leaves Demo Race.
       2. a foreign "Demo Race Two" stored right AFTER step.begin (behind the
          tool's re-check) -> apply_character refuses "already exists" before
          on_claim, the reconcile finds the row but no claim -> ok False,
          wrote False, the begun row ends kind "refused", so undo() does not
          see it; Demo Race Two survives the undo (the old reconcile claimed
          it and the undo deleted it).
       3. the claim still works: _apply_body_slots raises ValueError for a
          NEW "Demo Claim" (after the profile save) -> ok False, wrote True,
          "partly written: character Demo Claim exists"; the write row's
          inverse is delete_character Demo Claim; undo removes it.
  (ae) one call, three groups: Demo Other has no profile "age", no config
       "popularity" and no soul/presence.md (removed first: the profile saves
       of (z)/(aa) recreated it from the soul scaffold). update {soul:character_presence
       "present", age 30, popularity 7, home Demo Lakeside} -> ok, 3 write
       rows oldest-first: restore_soul (before_text None),
       restore_character {profile {age: ABSENT}, config {popularity:
       ABSENT}}, restore_home_schedule. undo -> complete; age and popularity
       absent again, presence.md absent, home_schedule_state as before.
  (af) a later group failing: save_character_config patched to return False;
       update {soul:character_presence "x", popularity 9} -> the soul group
       is written and journaled, the config group raises ValueError and
       stores nothing -> ok False, wrote True, the line says "changed in
       part"; exactly 1 write row (restore_soul); undo -> presence.md
       absent again.
  (ag) apply_character reports a skipped item_id: an outfit with
       {item_id: "item_nope"} given straight to apply_character (the route
       path, no tool pre-check) -> a warning naming "item_nope".

Open points 1-3 of the plan (runs 17-21):

  (ah) cross-turn delete. Turn 1 creates "Demo Longhouse" (room Hall, at
       500/500), a water area TA, a 4 m height area HA and "Demo Ragna"
       (human-roleplay, one outfit with ONE new piece "Demo Fur Cloak"); Ragna
       gets one own memory plus a hand-inserted memory_embeddings row (no
       character column: it goes by ON DELETE CASCADE with the memory; vector
       BLOB 00 01 02 ff). D1 = every row of every table (rowid order; the
       journal tables, sqlite_sequence and the derived height raster
       world_heightfield left out), F1 = Ragna's directory
       bytes (it has soul/*.md files from the apply).
       Turn 2: delete_created of all four -> ok, each line "... an earlier
       turn"; all four absent, the embedding row gone with them; the turn-2
       journal holds exactly recreate_location, recreate_terrain_area,
       recreate_height_area, recreate_character (state done); the 4 turn-1
       creates are NOT undone.
       undo(run, turn=2) -> complete, 4 reversed; every table row-equal to
       D1 — except created_at/updated_at of locations/terrain_areas/
       height_areas, which their writers always set to "now" (technical
       stamps the readers do not return; the readers' records are compared
       in full: diff_keys empty);
       Ragna's files byte-equal to F1.
       Turn 3: delete_created of Ragna and the Longhouse again -> ok.
       discard_preview = exactly the two area lines ("terrain area TA
       (water)", "height area HA (4.0 m)"): the location and Ragna are net
       absent (re-created, then deleted by their creates). undo(run) ->
       complete; all four absent, Ragna's directory gone, the cloak deleted
       (held nowhere once Ragna is gone).
  (ai) the create claim is durable. wr.complete is patched to raise Crash
       (a BaseException: the process ends, the row stays pending):
       1. "Demo Unclaimed": world_dev_apply._row_exists raises Crash — the
          apply's first step, before the claim -> pending, no claim.
       2. "Demo Before": world_dev_apply.save_character_profile records the
          journal inverse and raises Crash -> at that moment the inverse
          already carries claimed true; no row stored.
       3. "Demo After": add_to_inventory (the hand-over right after add_item)
          records the inverse, stores, then raises Crash -> the inverse
          carries claimed true and the ONE new piece id; the row is stored.
       An admin then creates "Demo Unclaimed" by hand. undo(run) -> skips
       {Unclaimed: "not written", Before: "already gone"}, reversed = [the
       After row], complete True; Demo After and its piece gone, the admin's
       Demo Unclaimed kept.
  (aj) cross-turn refusals (created in turn 1, deleted in turn 2): "Demo
       Talker" with 1 chat message -> refused naming "1 chat messages";
       "Demo Remembered", named by 1 memory row of Demo Other -> refused
       naming "1 memory rows"; "Demo Gallery Hut" with a file in
       world_gallery/<id>/ -> refused naming that directory; the pre-existing
       Demo Other -> "not created by this run". No refused call adds a write
       row; all three stay.
  (ak) "Demo Twin" created in turn 1, deleted in turn 2; an admin creates a
       "Demo Twin" (dialogue_style "the admin's"). discard_preview = exactly
       the one line "character Demo Twin was deleted by this run and exists
       again — the discard leaves it alone". undo -> both rows skipped
       "changed since" (the re-creation finds the foreign row; the create's
       delete is skipped for the same target), reversed [], complete False;
       the admin's Demo Twin stays with its dialogue_style.
  (al) outfits. From shared/templates/character/*.json
       features.outfit_system_enabled: human-default false, human-roleplay
       true, animal-default true -> character_templates() says exactly that.
       create_character human-default with 2 outfits -> refused "no outfit
       system", the line names "animal-default, human-roleplay", no row, no
       write row; with outfits [] -> ok, nothing "dropped". update_character
       {outfits} on that human-default character -> "no outfit system"; on
       the human-roleplay Demo Other -> "not changed here". The template
       refusal (npc-temporary) lists "human-default (no outfits)" and
       "human-roleplay (outfits)"; read_manual characters contains
       "- `human-default` (Human Standard) — no outfits" (the label of
       human-default.json) and a human-roleplay line with "— outfits".
  (am) delete + re-create under the same name (the correction path: a
       character made on the wrong template is deleted and made again).
       Turn 1 create_character "Demo Again" (human-roleplay, no outfits);
       turn 2 delete_created it (cross-turn -> recreate_character row) and
       create_character "Demo Again" again with one outfit and one NEW piece
       "Demo Again Scarf". Journal newest-first: delete_character (items
       [scarf]), recreate_character, delete_character (items []). The
       undo's walk: the newest create deletes the row (absent), the
       re-creation finds it absent and re-creates it, the oldest create
       deletes it again -> Demo Again goes, nothing is foreign. So
       discard_preview = exactly ['character "Demo Again" — 0 chat
       messages, 0 memory rows of other characters name it, 1 outfit pieces
       it brought'] (one line for the two creating entries, the piece still
       in the catalog, NO "exists again" line); undo reverses all 3 rows,
       skipped [], complete True; afterwards Demo Again and the scarf are
       absent — what the preview announced.

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
from app.models.character import (list_character_places,  # noqa: E402
                                  save_character_current_location)
save_character_current_location("Demo Guest", HID)
check("(p) Demo Guest stands in it",
      list_character_places().get("Demo Guest", ("",))[0] == HID,
      list_character_places().get("Demo Guest"))
res = wt.run_tool(ctx6, "delete_created", {"kind": "location", "id": HID})
check("(p) delete with someone standing there refused",
      not res.ok and "Demo Guest (stands there)" in res.line
      and len(by_name("Demo Home")) == 1, res)
save_character_current_location("Demo Guest", "")
# Entering a place makes it a known place: clear that reference again.
save_character_config("Demo Guest", {"known_locations": []})
check("(p) Demo Guest left it",
      list_character_places().get("Demo Guest", ("",))[0] != HID,
      list_character_places().get("Demo Guest"))
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

# ── Task 6: character write tools ────────────────────────────────────────
print("run 9 (characters)")
from app.core import soul_writer  # noqa: E402
from app.core import world_dev_apply  # noqa: E402
from app.core.world_dev_apply import apply_character  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  delete_character)
from app.models.inventory import (add_item, add_to_inventory,  # noqa: E402
                                  get_carried_item_ids, get_item)

lakeside = add_location("Demo Lakeside", "a lake house", rooms=[{"name": "Bedroom"}])
LS = lakeside["id"]
bedroom = next(r for r in lakeside["rooms"] if r["name"] == "Bedroom")["id"]
apply_character({"character_name": "Demo Other", "template": "human-roleplay",
                 "dialogue_style": "terse", "character_personality": "calm"})
check("(v) fixture Demo Other", character_row_exists("Demo Other"))
boots = add_item(name="Demo Boots", description="", category="outfit_piece",
                 image_prompt="", prompt_fragment="sturdy leather boots",
                 outfit_piece={"slots": ["feet"], "covers": [], "partially_covers": []})
BOOTS = boots["id"]


def lake_draft():
    return {"character_name": "Demo Lake", "template": "human-roleplay",
            "dialogue_style": "warm",
            "outfits": [{"name": "Daily", "pieces": [
                {"slots": ["top"], "name": "Demo Tunic",
                 "prompt_fragment": "a green linen tunic"},
                {"slots": ["bottom"], "name": "Demo Trousers",
                 "prompt_fragment": "brown wool trousers"},
                {"item_id": BOOTS}]}]}


run9 = wr.create_run("chars", "m", "p", "u", 40, 300000)
ctx9 = wt.ToolCtx(run_id=run9, turn=1)
res = wt.run_tool(ctx9, "create_character",
                  {"data": lake_draft(), "home": "Demo Lakeside", "home_room": "Bedroom"})
check("(v) create_character ok", res.ok and res.wrote, res)
check("(v) Demo Lake exists", character_row_exists("Demo Lake"))
cfg_lake = get_character_config("Demo Lake") or {}
check("(v) home set (place + room)",
      cfg_lake.get("home_location") == LS and cfg_lake.get("home_room") == bedroom,
      cfg_lake)
create_e = next((e for e in wr.entries(run9) if e["tool"] == "create_character"), {})
inv_items = (create_e.get("inverse") or {}).get("items") or []
check("(v) inverse delete_character with the 2 new item ids",
      (create_e.get("inverse") or {}).get("op") == "delete_character"
      and len(inv_items) == 2 and BOOTS not in inv_items, create_e.get("inverse"))
TUNIC, TROUSERS = (inv_items + ["?", "?"])[:2]
check("(v) the existing piece is worn, not created",
      BOOTS in get_carried_item_ids("Demo Lake"), get_carried_item_ids("Demo Lake"))
res = wt.run_tool(ctx9, "create_character", {"data": lake_draft()})
check("(v) a taken name refused", not res.ok and "already exists" in res.line, res)
res = wt.run_tool(ctx9, "create_character", {"data": {"character_name": "a/b"}})
check("(v) an invalid name refused", not res.ok and not character_row_exists("a/b"), res)
res = wt.run_tool(ctx9, "create_character",
                  {"data": {"character_name": "Demo Odd", "template": "human-roleplay",
                            "outfits": [{"name": "X", "pieces": [{"item_id": "item_nope"}]}]}})
check("(v) an unknown item_id refused, nothing created",
      not res.ok and not character_row_exists("Demo Odd"), res)
res = wt.run_tool(ctx9, "update_character",
                  {"name": "Demo Other", "patch": {"dialogue_style": "chatty"}})
check("(v) update_character ok", res.ok and res.wrote, res)
from app.models.character import get_character_profile  # noqa: E402
check("(v) dialogue_style stored",
      get_character_profile("Demo Other").get("dialogue_style") == "chatty")
upd_e = [e for e in wr.entries(run9) if e["tool"] == "update_character"]
check("(v) journaled as restore_character with the stored diff",
      len(upd_e) == 1 and upd_e[0]["inverse"].get("op") == "restore_character"
      and upd_e[0]["inverse"].get("profile") == {"dialogue_style": "terse"}
      and (upd_e[0].get("written") or {}).get("profile") == {"dialogue_style": "chatty"},
      upd_e)
for bad, why in (({"bogus_field": "x"}, "unknown"),
                 ({"character_personality": "x"}, "soul:"),
                 ({"soul:bogus": "x"}, "no soul field"),
                 ({"current_location": LS}, "cannot be changed"),
                 ({"age": "old"}, "number")):
    res = wt.run_tool(ctx9, "update_character", {"name": "Demo Other", "patch": bad})
    check(f"(v) patch {sorted(bad)} refused ({why})", not res.ok and why in res.line, res)
rep = wu.undo(run9)
check("(v) undo complete", rep["complete"], rep)
check("(v) undo: Demo Lake gone", not character_row_exists("Demo Lake"))
check("(v) undo: both new items gone",
      get_item(TUNIC) is None and get_item(TROUSERS) is None, (TUNIC, TROUSERS))
check("(v) undo: the pre-existing piece stays", get_item(BOOTS) is not None)
check("(v) undo: Demo Other's dialogue_style restored",
      get_character_profile("Demo Other").get("dialogue_style") == "terse",
      get_character_profile("Demo Other").get("dialogue_style"))
wr.set_status(run9, "rolled_back")

# Variant: one new piece given to Demo Other before the undo.
print("run 10 (item still in use)")
run10 = wr.create_run("chars2", "m", "p", "u", 40, 300000)
ctx10 = wt.ToolCtx(run_id=run10, turn=1)
res = wt.run_tool(ctx10, "create_character", {"data": lake_draft()})
check("(w) create again ok", res.ok, res)
items10 = (next(e for e in wr.entries(run10)
                if e["tool"] == "create_character").get("inverse") or {}).get("items") or []
check("(w) two new items", len(items10) == 2, items10)
GIVEN, OTHER = (items10 + ["?", "?"])[:2]
add_to_inventory(character_name="Demo Other", item_id=GIVEN,
                 obtained_method="gift", obtained_from="smoke")
rep = wu.undo(run10)
check("(w) Demo Lake gone", not character_row_exists("Demo Lake"))
check("(w) the given item stays, with its inventory row",
      get_item(GIVEN) is not None and GIVEN in get_carried_item_ids("Demo Other"))
check("(w) skip reason 'item still in use' for it",
      any(s.get("item") == GIVEN and s.get("reason") == wu.REASON_ITEM_IN_USE
          for s in rep["skipped"]), rep)
check("(w) the other new item gone", get_item(OTHER) is None)
wr.set_status(run10, "rollback_incomplete")

# Soul sections.
print("run 11 (soul)")
P_REL, PR_REL, B_REL, T_REL = ("soul/personality.md", "soul/presence.md",
                               "soul/beliefs.md", "soul/tasks.md")
soul_writer.write_text("Demo Other", PR_REL, None)  # presence.md absent before
soul_writer.write_text("Demo Other", B_REL, "beliefs before")
soul_writer.write_text("Demo Other", T_REL, "tasks before")
p_before = soul_writer.read_text("Demo Other", P_REL)
check("(x) fixture personality.md", p_before == "calm\n", p_before)
check("(x) fixture presence.md absent", soul_writer.read_text("Demo Other", PR_REL) is None)
run11 = wr.create_run("soul", "m", "p", "u", 40, 300000)
ctx11 = wt.ToolCtx(run_id=run11, turn=1)
res = wt.run_tool(ctx11, "update_character",
                  {"name": "Demo Other",
                   "patch": {"soul:character_personality": "bold and loud  \n\n",
                             "soul:character_presence": "a quiet presence",
                             "soul:character_task": "agent tasks"}})
check("(x) soul update ok", res.ok and res.wrote, res)
check("(x) stored text = rstrip + newline",
      soul_writer.read_text("Demo Other", P_REL) == "bold and loud\n"
      and soul_writer.read_text("Demo Other", PR_REL) == "a quiet presence\n")
soul_steps = [e for e in wr.entries(run11) if (e.get("inverse") or {}).get("op") == "restore_soul"]
check("(x) one restore_soul step per section, before_text read from storage",
      len(soul_steps) == 3
      and {e["inverse"]["file_id"]: e["inverse"]["before_text"] for e in soul_steps}
      == {P_REL: "calm\n", PR_REL: None, T_REL: "tasks before\n"}, soul_steps)
# A human edits another section file and the agent-written tasks.md.
soul_writer.write_text("Demo Other", B_REL, "beliefs by a human")
soul_writer.write_text("Demo Other", T_REL, "tasks by a human")
rep = wu.undo(run11)
check("(x) personality.md exactly as before",
      soul_writer.read_text("Demo Other", P_REL) == "calm\n",
      soul_writer.read_text("Demo Other", P_REL))
check("(x) presence.md (absent before) gone again",
      soul_writer.read_text("Demo Other", PR_REL) is None)
check("(x) the human's beliefs.md untouched",
      soul_writer.read_text("Demo Other", B_REL) == "beliefs by a human\n")
check("(x) the human's tasks.md kept, skipped 'changed since'",
      soul_writer.read_text("Demo Other", T_REL) == "tasks by a human\n"
      and [s["reason"] for s in rep["skipped"]] == [wu.REASON_CHANGED], rep)
wr.set_status(run11, "rollback_incomplete")

# Shared soul section of a linked character -> refused.
from app.core import linked_characters  # noqa: E402
_orig_owner = linked_characters.soul_owner
linked_characters.soul_owner = (lambda n, s: "Demo Leader" if n == "Demo Other"
                                else _orig_owner(n, s))
run12 = wr.create_run("misc", "m", "p", "u", 40, 300000)
ctx12 = wt.ToolCtx(run_id=run12, turn=1)
try:
    res = wt.run_tool(ctx12, "update_character",
                      {"name": "Demo Other", "patch": {"soul:character_personality": "x"}})
finally:
    linked_characters.soul_owner = _orig_owner
check("(y) a linked character's shared section refused",
      not res.ok and "Demo Leader" in res.line
      and soul_writer.read_text("Demo Other", P_REL) == "calm\n", res)

# Home + schedule through update_character, then undo.
h0 = wu.home_schedule_state("Demo Other")
res = wt.run_tool(ctx12, "update_character",
                  {"name": "Demo Other",
                   "patch": {"home": "Demo Lakeside", "home_room": "Bedroom",
                             "schedule": [{"hour": 8, "location": "Demo Lakeside",
                                           "role": "fishing"}]}})
h1 = wu.home_schedule_state("Demo Other")
check("(y) home + schedule ok", res.ok and h1["home_location"] == LS
      and h1["home_room"] == bedroom
      and [s.get("location") for s in h1["daily_schedule"]["slots"]] == [LS]
      and LS in (h1["known_locations"] or []), (res, h1))
home_e = [e for e in wr.entries(run12) if (e.get("inverse") or {}).get("op")
          == "restore_home_schedule"]
check("(y) journaled restore_home_schedule", len(home_e) == 1, home_e)

# delete_created of a character created in this turn.
res = wt.run_tool(ctx12, "create_character",
                  {"data": {"character_name": "Demo Brief", "template": "human-roleplay",
                            "outfits": [{"name": "Plain", "pieces": [
                                {"slots": ["top"], "name": "Demo Smock",
                                 "prompt_fragment": "a plain grey smock"}]}]}})
brief_items = (next(e for e in wr.entries(run12)
                    if e["tool"] == "create_character").get("inverse") or {}).get("items") or []
res = wt.run_tool(ctx12, "delete_created", {"kind": "character", "id": "Demo Other"})
check("(y) delete_created of a pre-existing character refused",
      not res.ok and character_row_exists("Demo Other"), res)
res = wt.run_tool(ctx12, "delete_created", {"kind": "character", "id": "Demo Brief"})
check("(y) delete_created of the run's own character ok",
      res.ok and not character_row_exists("Demo Brief")
      and len(brief_items) == 1 and get_item(brief_items[0]) is None, (res, brief_items))
rep = wu.undo(run12)
check("(y) undo: home and schedule as before",
      rep["complete"] and wu.home_schedule_state("Demo Other") == h0,
      (rep, wu.home_schedule_state("Demo Other"), h0))
wr.set_status(run12, "rolled_back")

# apply_character contract (Task 1 acceptance): a False save is a ValueError;
# soul markdown goes through soul_writer.write_text.
print("apply_character contract")
for target, draft, label in (
        ("save_character_profile", {"character_name": "Demo Fail",
                                    "template": "human-roleplay"}, "profile"),
        ("save_character_config", {"character_name": "Demo Other",
                                   "template": "human-roleplay",
                                   "popularity": 5}, "config"),
        ("save_character_config", {"character_name": "Demo Other",
                                   "home_location": "Demo Lakeside"}, "home config")):
    _saved = getattr(world_dev_apply, target)
    setattr(world_dev_apply, target, lambda *a, **k: False)
    raised = None
    try:
        apply_character(dict(draft))
    except ValueError as e:
        raised = e
    finally:
        setattr(world_dev_apply, target, _saved)
    check(f"(z) {label} save False -> ValueError", raised is not None, raised)
check("(z) no Demo Fail row", not character_row_exists("Demo Fail"))
_calls = []
_orig_write_text = soul_writer.write_text


def _rec_write_text(name, rel, text):
    _calls.append((name, rel))
    return _orig_write_text(name, rel, text)


soul_writer.write_text = _rec_write_text
try:
    apply_character({"character_name": "Demo Other", "template": "human-roleplay",
                     "character_personality": "calm again"})
finally:
    soul_writer.write_text = _orig_write_text
check("(z) soul markdown written through soul_writer.write_text",
      ("Demo Other", P_REL) in _calls
      and soul_writer.read_text("Demo Other", P_REL) == "calm again\n", _calls)

# ── Task 6 review findings ───────────────────────────────────────────────
print("run 13 (field values, home spellings, templates)")
from app.models import character as character_model  # noqa: E402
run13 = wr.create_run("review", "m", "p", "u", 40, 300000)
ctx13 = wt.ToolCtx(run_id=run13, turn=1)
for bad, why in (({"chat_mode": "banana"}, "rp_first"),
                 ({"importance": "9"}, "one of"),
                 ({"importance": "2"}, "one of"),
                 ({"importance": True}, "one of"),
                 ({"gender": "zzz"}, "one of"),
                 ({"birthday": [1, 2, {"x": 1}]}, "season"),
                 ({"birthday": "spring:31"}, "season")):
    res = wt.run_tool(ctx13, "update_character", {"name": "Demo Other", "patch": bad})
    check(f"(aa) {bad} refused ({why})", not res.ok and why in res.line, res)
res = wt.run_tool(ctx13, "update_character", {"name": "Demo Other",
                                              "patch": {"importance": 2}})
imp = (get_character_config("Demo Other") or {}).get("importance")
check("(aa) importance 2 stored as the number 2",
      res.ok and imp == 2 and not isinstance(imp, str), (res, imp))
res = wt.run_tool(ctx13, "update_character", {"name": "Demo Other",
                                              "patch": {"birthday": "summer:14"}})
check("(aa) birthday summer:14 stored",
      res.ok and get_character_profile("Demo Other").get("birthday") == "summer:14", res)
check("(aa) only the two good calls left write rows", len(wr.entries(run13)) == 2,
      wr.entries(run13))

h_before13 = wu.home_schedule_state("Demo Other")
for bad, why in (({"home": "Demo Lakeside", "home_location": "Atlantis"},
                  "send 'home_location' as 'home'"),
                 ({"home": "Atlantis"}, "no place"),
                 ({"home_room": "Bedroom"}, "needs a home"),
                 ({"home": "Demo Lakeside", "home_room": "Cellar"}, "Bedroom"),
                 ({"schedule": [{"hour": 9, "location": "Atlantis"}]}, "no place")):
    res = wt.run_tool(ctx13, "update_character", {"name": "Demo Other", "patch": bad})
    check(f"(ab) {sorted(bad)} refused ({why})", not res.ok and why in res.line, res)
res = wt.run_tool(ctx13, "create_character",
                  {"data": {"character_name": "Demo Twice", "template": "human-roleplay",
                            "home_location": "Demo Lakeside"}, "home": "Demo Lakeside"})
check("(ab) home as argument AND data.home_location refused",
      not res.ok and "given twice" in res.line and not character_row_exists("Demo Twice"),
      res)
check("(ab) no write row, home unchanged",
      len(wr.entries(run13)) == 2 and wu.home_schedule_state("Demo Other") == h_before13)

for tpl, why in (("npc-temporary", "human-roleplay"), ("base-character", "cannot be created")):
    res = wt.run_tool(ctx13, "create_character",
                      {"data": {"character_name": "Demo Tmpl", "template": tpl}})
    check(f"(ac) template {tpl} refused", not res.ok and why in res.line
          and not character_row_exists("Demo Tmpl"), res)
rep = wu.undo(run13)
check("(aa) undo complete", rep["complete"], rep)
wr.set_status(run13, "rolled_back")

print("run 14 (a foreign character is never claimed)")
run14 = wr.create_run("race", "m", "p", "u", 40, 300000)
ctx14 = wt.ToolCtx(run_id=run14, turn=1)
_orig_prepare, _orig_begin = wt._Step.prepare, wt._Step.begin


def _prepare_then_foreign(self):
    _orig_prepare(self)
    apply_character({"character_name": "Demo Race", "template": "human-roleplay"})


wt._Step.prepare = _prepare_then_foreign
try:
    res = wt.run_tool(ctx14, "create_character",
                      {"data": {"character_name": "Demo Race", "template": "human-roleplay"}})
finally:
    wt._Step.prepare = _orig_prepare
check("(ad) 1. a name taken during the backup -> refused",
      not res.ok and not res.wrote and "already exists" in res.line, res)


def _begin_then_foreign(self, *a, **k):
    seq = _orig_begin(self, *a, **k)
    if self.tool == "create_character":
        apply_character({"character_name": "Demo Race Two", "template": "human-roleplay"})
    return seq


wt._Step.begin = _begin_then_foreign
try:
    res = wt.run_tool(ctx14, "create_character",
                      {"data": {"character_name": "Demo Race Two",
                                "template": "human-roleplay"}})
finally:
    wt._Step.begin = _orig_begin
check("(ad) 2. a name taken behind the re-check -> refused, nothing claimed",
      not res.ok and not res.wrote and "already exists" in res.line, res)
race_rows = [e for e in wr.steps(run14) if e["tool"] == "create_character"]
check("(ad) 2. the begun row ended as refused",
      race_rows and race_rows[-1]["kind"] == "refused", race_rows)
check("(ad) no write row names a race character",
      not any((e.get("inverse") or {}).get("name") in ("Demo Race", "Demo Race Two")
              for e in wr.entries(run14)), wr.entries(run14))

_orig_slots = world_dev_apply._apply_body_slots


def _slots_fail(*a, **k):
    raise ValueError("simulated body-slot failure")


world_dev_apply._apply_body_slots = _slots_fail
try:
    res = wt.run_tool(ctx14, "create_character",
                      {"data": {"character_name": "Demo Claim", "template": "human-roleplay"}})
finally:
    world_dev_apply._apply_body_slots = _orig_slots
check("(ad) 3. a failure after the own row was stored -> claimed",
      not res.ok and res.wrote and "partly written: character Demo Claim exists" in res.line,
      res)
claim_rows = wr.entries(run14)
check("(ad) 3. its write row carries delete_character Demo Claim",
      len(claim_rows) == 1 and claim_rows[0]["inverse"].get("op") == "delete_character"
      and claim_rows[0]["inverse"].get("name") == "Demo Claim", claim_rows)
rep = wu.undo(run14)
check("(ad) undo: Demo Claim gone, both foreign characters stay",
      rep["complete"] and not character_row_exists("Demo Claim")
      and character_row_exists("Demo Race") and character_row_exists("Demo Race Two"),
      rep)
wr.set_status(run14, "rolled_back")

print("run 15 (three groups in one call)")
# A profile save (z, aa) recreates a missing soul file from its scaffold:
# remove presence.md again so the fixture is "absent".
soul_writer.write_text("Demo Other", PR_REL, None)
check("(ae) fixture: age, popularity and presence.md absent",
      "age" not in (character_model.get_character_profile("Demo Other") or {})
      and "popularity" not in (get_character_config("Demo Other") or {})
      and soul_writer.read_text("Demo Other", PR_REL) is None)
h_before15 = wu.home_schedule_state("Demo Other")
run15 = wr.create_run("groups", "m", "p", "u", 40, 300000)
ctx15 = wt.ToolCtx(run_id=run15, turn=1)
res = wt.run_tool(ctx15, "update_character",
                  {"name": "Demo Other",
                   "patch": {"soul:character_presence": "present", "age": 30,
                             "popularity": 7, "home": "Demo Lakeside"}})
rows15 = list(reversed(wr.entries(run15)))  # oldest-first
check("(ae) ok, three write rows", res.ok and res.wrote and len(rows15) == 3,
      (res, rows15))
check("(ae) inverses: restore_soul / restore_character / restore_home_schedule",
      [e["inverse"].get("op") for e in rows15]
      == ["restore_soul", "restore_character", "restore_home_schedule"], rows15)
check("(ae) restore_soul before_text None",
      rows15 and rows15[0]["inverse"].get("before_text") is None, rows15[:1])
check("(ae) restore_character records the absent keys",
      len(rows15) > 1 and rows15[1]["inverse"].get("profile") == {"age": wu.ABSENT}
      and rows15[1]["inverse"].get("config") == {"popularity": wu.ABSENT}, rows15[1:2])
rep = wu.undo(run15)
check("(ae) undo complete", rep["complete"], rep)
check("(ae) undo: age and popularity absent again, presence.md gone, home as before",
      "age" not in (character_model.get_character_profile("Demo Other") or {})
      and "popularity" not in (get_character_config("Demo Other") or {})
      and soul_writer.read_text("Demo Other", PR_REL) is None
      and wu.home_schedule_state("Demo Other") == h_before15,
      (character_model.get_character_profile("Demo Other").get("age"),
       get_character_config("Demo Other").get("popularity"),
       soul_writer.read_text("Demo Other", PR_REL),
       wu.home_schedule_state("Demo Other"), h_before15))
wr.set_status(run15, "rolled_back")

print("run 16 (a later group fails)")
run16 = wr.create_run("partial", "m", "p", "u", 40, 300000)
ctx16 = wt.ToolCtx(run_id=run16, turn=1)
_orig_save_cfg = character_model.save_character_config
character_model.save_character_config = lambda *a, **k: False
try:
    res = wt.run_tool(ctx16, "update_character",
                      {"name": "Demo Other",
                       "patch": {"soul:character_presence": "x", "popularity": 9}})
finally:
    character_model.save_character_config = _orig_save_cfg
check("(af) ok False, wrote True, 'changed in part'",
      not res.ok and res.wrote and "changed in part" in res.line, res)
rows16 = wr.entries(run16)
check("(af) exactly the soul group journaled",
      [e["inverse"].get("op") for e in rows16] == ["restore_soul"]
      and "popularity" not in (get_character_config("Demo Other") or {}), rows16)
rep = wu.undo(run16)
check("(af) undo: presence.md absent again",
      rep["complete"] and soul_writer.read_text("Demo Other", PR_REL) is None,
      (rep, soul_writer.read_text("Demo Other", PR_REL)))
wr.set_status(run16, "rolled_back")

result_ag = apply_character({"character_name": "Demo Other", "template": "human-roleplay",
                             "outfits": [{"name": "Ghost", "pieces": [
                                 {"item_id": "item_nope"}]}]})
check("(ag) a skipped item_id is a warning in the apply result",
      any("item_nope" in w for w in result_ag.get("warnings") or []), result_ag)

# ── Open points 1-3 (cross-turn delete, durable claim, outfits) ─────────
import sqlite3  # noqa: E402

from app.core.db import get_connection  # noqa: E402
from app.models import chat as chat_model  # noqa: E402
from app.models import memory as memory_model  # noqa: E402
from app.models.character import get_user_characters_dir  # noqa: E402
from app.models.inventory import get_item as _get_item  # noqa: E402

#: Tables that are the journal itself, SQLite's own counter, or the derived
#: world height raster (a cache rastered from the terrain/height areas and
#: places — app/models/heightfield.py "The grid ... is derived from those
#: areas"; when it is rastered depends on which write came last).
_DUMP_SKIP = {"world_dev_journal", "world_dev_runs", "sqlite_sequence",
              "world_heightfield"}
#: Tables whose created_at/updated_at their writers always set to "now"
#: (upsert_location, terrain.save_area, heightfield.save_height_area):
#: technical SYSTEM stamps the readers do not return.
_STAMP_TABLES = ("locations", "terrain_areas", "height_areas")


def db_dump():
    """Every row of every table, with its rowid, in rowid order."""
    conn = get_connection()
    out = {}
    for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                               "ORDER BY name").fetchall():
        if tbl in _DUMP_SKIP:
            continue
        try:
            rows = conn.execute(f'SELECT rowid, * FROM "{tbl}" ORDER BY rowid').fetchall()
        except sqlite3.OperationalError:
            rows = sorted(conn.execute(f'SELECT * FROM "{tbl}"').fetchall(), key=repr)
        out[tbl] = [tuple(r) for r in rows]
    return out


def dump_diff(a, b, stamp_tables=()):
    """Tables whose rows differ. For a table in stamp_tables the
    created_at/updated_at columns are left out (see run 17)."""
    out = []
    for tbl in sorted(set(a) | set(b)):
        ra, rb = a.get(tbl), b.get(tbl)
        if tbl in stamp_tables and ra is not None and rb is not None:
            cols = [c[1] for c in get_connection().execute(
                f'PRAGMA table_info("{tbl}")').fetchall()]
            drop = {i + 1 for i, c in enumerate(cols) if c in ("created_at", "updated_at")}
            ra = [tuple(v for i, v in enumerate(r) if i not in drop) for r in ra]
            rb = [tuple(v for i, v in enumerate(r) if i not in drop) for r in rb]
        if ra != rb:
            out.append(tbl)
    return out


def files_of(name):
    root = get_user_characters_dir() / name
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))} if root.exists() else None


SQUARE = lambda x, z, s: [[x, z], [x + s, z], [x + s, z + s], [x, z + s]]  # noqa: E731

print("run 17 (cross-turn delete: exact rollback, then discard)")
run17 = wr.create_run("cross", "m", "p", "u", 40, 300000)
t1 = wt.ToolCtx(run_id=run17, turn=1)
res = wt.run_tool(t1, "create_location",
                  {"data": {"name": "Demo Longhouse", "description": "long",
                            "rooms": [{"name": "Hall"}]}, "x": 500, "z": 500})
LH = (by_name("Demo Longhouse") or [{}])[0].get("id")
res_a = wt.run_tool(t1, "add_terrain_area", {"kind": "water",
                                             "polygon": SQUARE(600, 600, 50)})
TA = (wr.entries(run17)[0].get("inverse") or {}).get("id")
res_h = wt.run_tool(t1, "add_height_area", {"polygon": SQUARE(700, 700, 100),
                                            "height_m": 4})
HA = (wr.entries(run17)[0].get("inverse") or {}).get("id")
res_c = wt.run_tool(t1, "create_character",
                    {"data": {"character_name": "Demo Ragna", "template": "human-roleplay",
                              "dialogue_style": "blunt", "character_personality": "proud",
                              "outfits": [{"name": "Winter", "pieces": [
                                  {"slots": ["outer"], "name": "Demo Fur Cloak",
                                   "prompt_fragment": "a grey fur cloak"}]}]}})
check("(ah) turn 1: four creates ok",
      res.ok and res_a.ok and res_h.ok and res_c.ok and LH and TA and HA,
      (res, res_a, res_h, res_c))
CLOAK = ((next(e for e in wr.entries(run17) if e["tool"] == "create_character")
          .get("inverse") or {}).get("items") or [None])[0]
# Ragna's own memory with an embedding row: memory_embeddings has no
# character column — it goes by ON DELETE CASCADE with its memory, and its
# vector is a BLOB. The snapshot has to bring both back.
memory_model.add_memory("Demo Ragna", "I came down from the north")
mem_rowid = get_connection().execute(
    "SELECT id FROM memories WHERE character_name='Demo Ragna'").fetchone()[0]
get_connection().execute(
    "INSERT INTO memory_embeddings (memory_id, model_id, vector, ts) VALUES (?, ?, ?, ?)",
    (int(mem_rowid), "demo-model", bytes([0, 1, 2, 255]), "2026-01-01T00:00:00"))
get_connection().commit()
D1, F1 = db_dump(), files_of("Demo Ragna")
check("(ah) fixture: one embedding row for Ragna's memory",
      len(D1.get("memory_embeddings") or []) == 1, D1.get("memory_embeddings"))
loc1, ta1, ha1 = (copy.deepcopy(get_location_by_id(LH)), terrain.get_area(TA),
                  wt._height_area(HA))
check("(ah) fixture: Ragna has a directory with soul files",
      bool(F1) and any(k.startswith("soul/") for k in F1), F1 and sorted(F1))

t2 = wt.ToolCtx(run_id=run17, turn=2)
dels = [wt.run_tool(t2, "delete_created", {"kind": k, "id": i})
        for k, i in (("location", LH), ("terrain", TA), ("height", HA),
                     ("character", "Demo Ragna"))]
check("(ah) turn 2: four cross-turn deletes ok, 'an earlier turn'",
      all(d.ok and d.wrote and "an earlier turn" in d.line for d in dels), dels)
check("(ah) all four gone, the embedding row with Ragna's memory",
      get_location_by_id(LH) is None and terrain.get_area(TA) is None
      and wt._height_area(HA) is None and not character_row_exists("Demo Ragna")
      and not db_dump().get("memory_embeddings"))
rows2 = wr.entries(run17, turn=2)
check("(ah) turn 2 journal: recreate_location/terrain/height/character, done",
      [e["inverse"].get("op") for e in reversed(rows2)]
      == ["recreate_location", "recreate_terrain_area", "recreate_height_area",
          "recreate_character"] and all(e["state"] == "done" for e in rows2), rows2)
check("(ah) the turn-1 creates are not undone",
      len(wr.entries(run17, turn=1)) == 4, wr.entries(run17, turn=1))
rep = wu.undo(run17, turn=2)
check("(ah) rollback of turn 2 complete, 4 reversed",
      rep["complete"] and len(rep["reversed"]) == 4, rep)
D2, F2 = db_dump(), files_of("Demo Ragna")
# Expected: byte-equal rows everywhere (same rowids). The ONE exception are
# the created_at/updated_at stamps of _STAMP_TABLES (see there); the
# readers' records are compared in full below.
check("(ah) rollback: every table row-equal (writer stamps aside)",
      dump_diff(D1, D2, stamp_tables=_STAMP_TABLES) == [],
      [(t, set(D1.get(t) or []) ^ set(D2.get(t) or [])) for t in
       dump_diff(D1, D2, stamp_tables=_STAMP_TABLES)])
check("(ah) rollback: the readers' records equal (diff_keys empty)",
      wu.diff_keys(loc1, get_location_by_id(LH)) == ({}, {})
      and wu.diff_keys(ta1, terrain.get_area(TA)) == ({}, {})
      and wu.diff_keys(ha1, wt._height_area(HA)) == ({}, {}),
      (wu.diff_keys(loc1, get_location_by_id(LH)),
       wu.diff_keys(ta1, terrain.get_area(TA)), wu.diff_keys(ha1, wt._height_area(HA))))
check("(ah) rollback: Ragna's files byte-equal", F2 == F1,
      (sorted(F1 or {}), sorted(F2 or {})))

t3 = wt.ToolCtx(run_id=run17, turn=3)
d3 = [wt.run_tool(t3, "delete_created", {"kind": k, "id": i})
      for k, i in (("character", "Demo Ragna"), ("location", LH))]
check("(ah) turn 3: cross-turn deletes again ok", all(d.ok for d in d3), d3)
prev17 = wu.discard_preview(run17)
check("(ah) preview: only the two areas (location and Ragna are net absent)",
      prev17 == [f"terrain area {TA} (water)", f"height area {HA} (4.0 m)"], prev17)
rep = wu.undo(run17)
check("(ah) discard complete", rep["complete"], rep)
check("(ah) discard: everything absent, the cloak deleted",
      get_location_by_id(LH) is None and terrain.get_area(TA) is None
      and wt._height_area(HA) is None and not character_row_exists("Demo Ragna")
      and files_of("Demo Ragna") is None and CLOAK and _get_item(CLOAK) is None,
      (CLOAK, files_of("Demo Ragna")))
wr.set_status(run17, "rolled_back")

print("run 18 (create_character: the claim is durable)")
run18 = wr.create_run("crash", "m", "p", "u", 40, 300000)
ctx18 = wt.ToolCtx(run_id=run18, turn=1)


class Crash(BaseException):
    """The process ends: nothing after this point runs."""


def journal_inverse(name):
    return next((e.get("inverse") for e in wr.entries(run18)
                 if (e.get("inverse") or {}).get("name") == name), None)


_orig_complete = wr.complete


def _complete_crashes(*a, **k):
    raise Crash()


def crash_call(name, patches):
    """run_tool with wr.complete crashing (the row stays pending) plus the
    given (module, attr, replacement) patches."""
    saved = [(m, a, getattr(m, a)) for m, a, _f in patches]
    wr.complete = _complete_crashes
    for m, a, f in patches:
        setattr(m, a, f)
    try:
        wt.run_tool(ctx18, "create_character",
                    {"data": {"character_name": name, "template": "human-roleplay",
                              "outfits": [{"name": "Daily", "pieces": [
                                  {"slots": ["top"], "name": f"{name} Shirt",
                                   "prompt_fragment": "a plain shirt"}]}]}})
        return False
    except Crash:
        return True
    finally:
        wr.complete = _orig_complete
        for m, a, f in saved:
            setattr(m, a, f)


seen = {}


def _before_generable(*a, **k):   # apply_character's first step, before the claim
    raise Crash()


def _save_sees_claim(name, profile, **k):   # the claim, then the save
    seen["at_save"] = copy.deepcopy(journal_inverse(name))
    raise Crash()


import app.models.inventory as inventory_model  # noqa: E402
_orig_add_inv = inventory_model.add_to_inventory


def _hand_over_sees_item(*a, **k):   # after add_item, at the hand-over
    seen["at_hand_over"] = copy.deepcopy(journal_inverse("Demo After"))
    _orig_add_inv(*a, **k)
    raise Crash()


c1 = crash_call("Demo Unclaimed", [(world_dev_apply, "_row_exists", _before_generable)])
c2 = crash_call("Demo Before", [(world_dev_apply, "save_character_profile",
                                 _save_sees_claim)])
c3 = crash_call("Demo After", [(inventory_model, "add_to_inventory",
                                _hand_over_sees_item)])
check("(ai) three simulated crashes", c1 and c2 and c3, (c1, c2, c3))
check("(ai) at the profile save the claim is already in the journal",
      (seen.get("at_save") or {}).get("claimed") is True, seen.get("at_save"))
items_c3 = (seen.get("at_hand_over") or {}).get("items") or []
check("(ai) at the hand-over the new piece is already in the journal",
      (seen.get("at_hand_over") or {}).get("claimed") is True and len(items_c3) == 1,
      seen.get("at_hand_over"))
pend = {e["inverse"]["name"]: e for e in wr.entries(run18)}
check("(ai) three pending rows; only the unclaimed one has no claim",
      sorted(pend) == ["Demo After", "Demo Before", "Demo Unclaimed"]
      and all(e["state"] == "pending" for e in pend.values())
      and not pend["Demo Unclaimed"]["inverse"].get("claimed")
      and pend["Demo Before"]["inverse"].get("claimed") is True
      and pend["Demo After"]["inverse"].get("claimed") is True, pend)
check("(ai) storage: no Demo Unclaimed / Demo Before row, Demo After stored",
      not character_row_exists("Demo Unclaimed") and not character_row_exists("Demo Before")
      and character_row_exists("Demo After"))
# An admin creates "Demo Unclaimed" by hand before the discard: never touched.
apply_character({"character_name": "Demo Unclaimed", "template": "human-roleplay"})
rep = wu.undo(run18)
reasons18 = {pend_name: [s["reason"] for s in rep["skipped"]
                         if s["seq"] == pend[pend_name]["seq"]] for pend_name in pend}
check("(ai) undo: unclaimed 'not written', before-save 'already gone', after-save deleted",
      reasons18 == {"Demo Unclaimed": ["not written"], "Demo Before": ["already gone"],
                    "Demo After": []}
      and rep["reversed"] == [pend["Demo After"]["seq"]], (reasons18, rep))
check("(ai) undo complete", rep["complete"], rep)
check("(ai) Demo After and its new piece gone; the admin's Demo Unclaimed stays",
      bool(items_c3) and not character_row_exists("Demo After")
      and _get_item(items_c3[0]) is None and character_row_exists("Demo Unclaimed"))
wr.set_status(run18, "rolled_back")

print("run 19 (cross-turn delete refusals)")
run19 = wr.create_run("refuse", "m", "p", "u", 40, 300000)
u1 = wt.ToolCtx(run_id=run19, turn=1)
u2 = wt.ToolCtx(run_id=run19, turn=2)
for nm in ("Demo Talker", "Demo Remembered"):
    wt.run_tool(u1, "create_character",
                {"data": {"character_name": nm, "template": "human-roleplay"}})
wt.run_tool(u1, "create_location", {"data": {"name": "Demo Gallery Hut",
                                             "rooms": [{"name": "Room"}]}})
GH = by_name("Demo Gallery Hut")[0]["id"]
chat_model.save_message({"role": "assistant", "content": "hello"},
                        character_name="Demo Talker")
memory_model.add_memory("Demo Other", "I met Demo Remembered at the lake")
gdir = STORAGE / "world_gallery" / GH
gdir.mkdir(parents=True)
(gdir / "day.png").write_bytes(b"png")
n19 = len(wr.entries(run19))
r_t = wt.run_tool(u2, "delete_created", {"kind": "character", "id": "Demo Talker"})
r_m = wt.run_tool(u2, "delete_created", {"kind": "character", "id": "Demo Remembered"})
r_g = wt.run_tool(u2, "delete_created", {"kind": "location", "id": GH})
check("(aj) a character with chat messages -> refused, stays",
      not r_t.ok and "1 chat messages" in r_t.line and character_row_exists("Demo Talker"),
      r_t)
check("(aj) a character other memories name -> refused, stays",
      not r_m.ok and "1 memory rows" in r_m.line
      and character_row_exists("Demo Remembered"), r_m)
check("(aj) a place with gallery images -> refused, stays",
      not r_g.ok and f"world_gallery/{GH}" in r_g.line
      and get_location_by_id(GH) is not None, r_g)
check("(aj) no refused call left a write row", len(wr.entries(run19)) == n19,
      wr.entries(run19))
r_p = wt.run_tool(u2, "delete_created", {"kind": "character", "id": "Demo Other"})
check("(aj) a pre-existing character -> refused", not r_p.ok
      and "not created by this run" in r_p.line, r_p)
rep = wu.undo(run19)
check("(aj) undo complete", rep["complete"], rep)
wr.set_status(run19, "rolled_back")

print("run 20 (a foreign character under a deleted name)")
run20 = wr.create_run("foreign", "m", "p", "u", 40, 300000)
v1 = wt.ToolCtx(run_id=run20, turn=1)
v2 = wt.ToolCtx(run_id=run20, turn=2)
wt.run_tool(v1, "create_character", {"data": {"character_name": "Demo Twin",
                                              "template": "human-roleplay"}})
res = wt.run_tool(v2, "delete_created", {"kind": "character", "id": "Demo Twin"})
check("(ak) cross-turn delete ok", res.ok and not character_row_exists("Demo Twin"), res)
apply_character({"character_name": "Demo Twin", "template": "human-roleplay",
                 "dialogue_style": "the admin's"})
prev20 = wu.discard_preview(run20)
check("(ak) preview names the foreign Twin, no deletion line",
      prev20 == ["character Demo Twin was deleted by this run and exists again — "
                 "the discard leaves it alone"], prev20)
rep = wu.undo(run20)
check("(ak) undo: both rows skipped 'changed since', not complete",
      [s["reason"] for s in rep["skipped"]] == ["changed since", "changed since"]
      and rep["reversed"] == [] and rep["complete"] is False, rep)
check("(ak) the admin's Demo Twin stays",
      character_row_exists("Demo Twin")
      and get_character_profile("Demo Twin").get("dialogue_style") == "the admin's")
wr.set_status(run20, "rollback_incomplete")

print("run 21 (outfits only on a template with the outfit system)")
# Expected from shared/templates/character/*.json features.outfit_system_enabled:
# human-default false, human-roleplay true, animal-default true.
check("(al) character_templates(): outfits per template",
      {t["name"]: t["outfits"] for t in wt.character_templates()}
      == {"animal-default": True, "human-default": False, "human-roleplay": True},
      wt.character_templates())
run21 = wr.create_run("outfits", "m", "p", "u", 40, 300000)
w1 = wt.ToolCtx(run_id=run21, turn=1)
res = wt.run_tool(w1, "create_character",
                  {"data": {"character_name": "Demo Plain", "template": "human-default",
                            "outfits": [{"name": "Daily", "pieces": [
                                {"slots": ["top"], "name": "Demo Plain Shirt"}]},
                                        {"name": "Work"}]}})
check("(al) human-default + outfits -> refused, names the templates with outfits",
      not res.ok and not res.wrote and "no outfit system" in res.line
      and "animal-default, human-roleplay" in res.line
      and not character_row_exists("Demo Plain"), res)
check("(al) no write row", wr.entries(run21) == [], wr.entries(run21))
res = wt.run_tool(w1, "create_character",
                  {"data": {"character_name": "Demo Plain", "template": "human-default",
                            "outfits": []}})
check("(al) human-default with an empty outfit list -> ok (nothing dropped)",
      res.ok and character_row_exists("Demo Plain") and "dropped" not in res.line, res)
res = wt.run_tool(w1, "update_character",
                  {"name": "Demo Plain", "patch": {"outfits": [{"name": "Daily"}]}})
check("(al) update_character outfits on human-default -> refused 'no outfit system'",
      not res.ok and "no outfit system" in res.line, res)
res = wt.run_tool(w1, "update_character",
                  {"name": "Demo Other", "patch": {"outfits": [{"name": "Daily"}]}})
check("(al) update_character outfits on human-roleplay -> refused 'not changed here'",
      not res.ok and "not changed here" in res.line, res)
res = wt.run_tool(w1, "create_character",
                  {"data": {"character_name": "Demo Nope", "template": "npc-temporary"}})
check("(al) the template refusal says per template whether it has outfits",
      not res.ok and "human-default (no outfits)" in res.line
      and "human-roleplay (outfits)" in res.line, res)
res = wt.run_tool(w1, "read_manual", {"section": "characters"})
check("(al) manual_characters lists the templates with/without outfits",
      res.ok and "- `human-default` (Human Standard) — no outfits" in res.line
      and "- `human-roleplay` (" in res.line and "— outfits" in res.line, res.line[:600])
rep = wu.undo(run21)
check("(al) undo complete, Demo Plain gone",
      rep["complete"] and not character_row_exists("Demo Plain"), rep)
wr.set_status(run21, "rolled_back")

print("run 22 (delete + re-create the same name: preview equals undo)")
run22 = wr.create_run("again", "m", "p", "u", 40, 300000)
x1 = wt.ToolCtx(run_id=run22, turn=1)
x2 = wt.ToolCtx(run_id=run22, turn=2)
r1 = wt.run_tool(x1, "create_character", {"data": {"character_name": "Demo Again",
                                                   "template": "human-roleplay"}})
r2 = wt.run_tool(x2, "delete_created", {"kind": "character", "id": "Demo Again"})
r3 = wt.run_tool(x2, "create_character",
                 {"data": {"character_name": "Demo Again", "template": "human-roleplay",
                           "outfits": [{"name": "Daily", "pieces": [
                               {"slots": ["neck"], "name": "Demo Again Scarf",
                                "prompt_fragment": "a red wool scarf"}]}]}})
check("(am) create, cross-turn delete, create again: all ok",
      r1.ok and r2.ok and r3.ok and character_row_exists("Demo Again"), (r1, r2, r3))
rows22 = wr.entries(run22)
check("(am) journal newest-first: delete_character, recreate_character, delete_character",
      [(e.get("inverse") or {}).get("op") for e in rows22]
      == ["delete_character", "recreate_character", "delete_character"], rows22)
SCARF = ((rows22[0].get("inverse") or {}).get("items") or [None])[0]
check("(am) the scarf is a new catalog piece", SCARF and _get_item(SCARF) is not None,
      SCARF)
prev22 = wu.discard_preview(run22)
check("(am) preview: Demo Again goes with its piece, no 'exists again' line",
      prev22 == ['character "Demo Again" — 0 chat messages, 0 memory rows of '
                 "other characters name it, 1 outfit pieces it brought"], prev22)
rep = wu.undo(run22)
check("(am) discard complete, 3 reversed, nothing skipped",
      rep["complete"] and len(rep["reversed"]) == 3 and rep["skipped"] == [], rep)
check("(am) what the preview announced: Demo Again and the scarf are gone",
      not character_row_exists("Demo Again") and _get_item(SCARF) is None,
      (character_row_exists("Demo Again"), _get_item(SCARF)))
wr.set_status(run22, "rolled_back")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
