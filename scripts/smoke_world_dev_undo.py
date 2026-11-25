#!/usr/bin/env python3
"""Smoke: World Dev free mode — journal undo with storage-read exactness check.

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 3. A temp
world (paths.init BEFORE any world-DB import); no server, no LLM. The forward
writes are done BY HAND here with the plan's write protocol (read 'before'
from storage -> begin -> write -> attach -> re-read -> complete), because the
write tools come in Task 5/6.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Run 1, all turn 1 (seq = journal order):

  seq 1  create location L (inverse delete_location{L}).
  seq 2  add terrain area A (inverse delete_terrain_area{A}).
  seq 3  pre-existing M, description "old" -> "agent". before/written come
         from diff_keys(stored before, stored after) -- the ONLY differing
         top-level key is "description" (the location record is the stored
         meta JSON, nothing else changes), so before = {"description":
         "old"}, written = {"description": "agent"}. Afterwards a "human"
         sets it to "human".
  seq 4  pre-existing P placed at (10, 20, yaw 0), moved by
         update_location_position(P, 40.123456, -5, 370). Stored values
         (world.py rounds x/z to 2 decimals, yaw to 1 decimal then % 360):
         x = round(40.123456, 2) = 40.12, z = -5.0, yaw = 370.0 % 360 = 10.0.
         written = {x: 40.12, z: -5.0, yaw: 10.0}; before = {x: 10.0,
         z: 20.0, yaw: 0.0}.
  seq 5  PENDING create of location Q with its inverse given at begin,
         never completed; Q exists in storage.
  seq 6  PENDING write WITHOUT inverse (hand-built).

  undo(run) walks newest-first 6..1:
    6 -> skipped, reason "may have written, no inverse — see backup"
    5 -> Q deleted                          (reversed)
    4 -> P back at (10.0, 20.0) yaw 0.0     (reversed)
    3 -> current "human" != written "agent" -> skipped "changed since",
         keys ["description"]; M stays "human"
    2 -> A deleted                          (reversed)
    1 -> L deleted                          (reversed)
  => reversed == [5, 4, 2, 1], skipped seqs == [6, 3].
  A second undo(run) finds every entry undone: reversed [], skipped [].

Run 2 (run 1 closed as rollback_incomplete first):

  turn 1: seq 1 update terrain area B (z_order 0 -> 3; inverse
          restore_terrain_area{full before row}, meta.scatter []);
          seq 2 add height area H (delete_height_area{H}); seq 3 profile of
          "Demo Other" personality "calm" -> "x" (restore_character);
          seq 4 soul file "soul/notes.md" absent -> "agent text"
          (restore_soul, before_text None); seq 5 soul file "soul/extra.md"
          "before text" -> "agent two"; then a HUMAN writes "human two".
  turn 2: seq 6 create character "Demo Lake" (delete_character{items:
          [I1, I2]}); I2 is then given to "Demo Other"; one chat row of
          "Demo Lake" is inserted.
          seq 7 home/schedule of "Demo Other": home_location "" -> M,
          known_locations None (key absent) -> [M].

  One memory row of "Demo Other" reads "Met Demo Lake at the pier" -> the
  memory count of other characters naming "Demo Lake" is 1. The count takes
  the name literally: "Demo%" and "Demo_Lake" match NO row (unescaped they
  would be wildcards and match the same row).

  discard_preview(run) names "Demo Lake" with "1 chat messages" (the one
  hand-inserted chat row), "1 memory rows" and the height area H.
  undo(run, turn=2) only touches turn 2 (7, 6):
    7 -> home_location "" again, known_locations key absent again (reversed)
    6 -> "Demo Lake" gone, I1 deleted (not shared, nowhere held), I2 skipped
         "item still in use" (held by "Demo Other") -> reversed [7, 6],
         skipped [(6, "item still in use", I2)]; the 5 turn-1 entries stay.
  undo(run) then does turn 1 (5..1):
    5 -> current "human two" != written "agent two" -> skipped "changed
         since", the file keeps "human two\n" (write_text stores
         text.rstrip() + "\n")
    4 -> notes.md gone again (before_text None)
    3 -> personality "calm"
    2 -> H gone
    1 -> B back to z_order 0 with its meta.scatter
  => reversed [4, 3, 2, 1], skipped [(5, "changed since")].
  "complete" is False in every report above that holds a skip other than
  "already gone" (run 1: no inverse / changed since; run 2: item still in
  use, changed since).

Run 3, all turn 1:

  seq 1  delete_location of "loc_missing", which never existed -> "already
         gone".
  seq 2  P (back at 10, 20, yaw 0) moved by the agent to (50, 50, 90),
         written {50.0, 50.0, 90.0}; a human then moves it to (60, 60, 90) ->
         "changed since", keys ["position"]; P stays at (60, 60).
  seq 3  height area H2 (height_m 4) updated to 7 (restore_height_area{row
         before}) -> back to 4.
  seq 4  location M gets a NEW key "agent_note" -> diff_keys before =
         {"agent_note": ABSENT}; undo removes the key again.
  seq 5  profile of "Demo Other" gets a NEW key "hobby" -> removed again.
  seq 6  create location loc_r; its delete is made to return False while
         loc_r still exists -> "delete refused"; loc_r stays.
  undo: 6 refused, 5/4/3 reversed, 2 changed since, 1 already gone
  => reversed [5, 4, 3], skipped seqs [6, 2, 1], complete False.

Run 4: only seq 1, a delete_height_area of an id that never existed ->
  skipped [(1, "already gone")], reversed [], complete True (the plan's
  state machine: "already gone" does not count toward rollback_incomplete).

Run 5: seq 1 restore_character of "Demo Other" while the character-row read
  raises -> the skip reason starts with "undo failed:" (a read error is never
  reported as "already gone"); complete False.

Run 6 (home keys ABSENT): "Demo Bare" has a config WITHOUT home_location and
  home_room. home_schedule_state reads both as ABSENT (not ""). seq 1 sets
  home_location "loc_m", home_room "r_keep" -> diff_keys before = {home_location:
  ABSENT, home_room: ABSENT}, written = {"loc_m", "r_keep"}. undo -> reversed
  [1], complete True, and the config has NEITHER key again (before the fix it
  carried "" for both).

Run 7 (occupants are reported, never "incomplete"): pre-existing loc_s with
  room r_keep "Demo Hall".
  seq 1  create location loc_n "Demo Nook" (delete_location{loc_n}).
  seq 2  loc_s gets a second room r_new "Demo Attic" -> diff_keys: the only
         differing key is "rooms" (restore_location{before: {rooms: [...]}}).
  Then "Demo Walker" is put into loc_n and "Demo Roomer" into loc_s / r_new.
  discard_preview, in its order (created elements oldest-first, then the
  occupants sorted by name):
    'location loc_n "Demo Nook"'
    'character "Demo Roomer" stands in room "Demo Attic" (r_new) of location
     loc_s, which the undo removes — stays there, place them anew'
    'character "Demo Walker" stands in location loc_n "Demo Nook" — stays
     there, place them anew'
  undo newest-first: 2 -> rooms back to [r_keep] (+ ground), r_new gone,
  occupant record '"Demo Roomer" stands in the removed place — place them
  anew' (room r_new); 1 -> loc_n deleted, occupant record for "Demo Walker".
  => reversed [2, 1], skipped == those two records (seqs [2, 1], keys
  occupant = Roomer / Walker), complete True (informational only). Nobody is
  moved: Walker still points at loc_n, Roomer at loc_s / r_new.

Run 8 (pending create_character without written, the crash case): the
  stored profile carries no "created by" marker (save_character_profile
  stores created_by "" whatever it is given), so such a row is NEVER deleted:
  seq 1  pending delete_character{"Demo Crash"} -> skipped "may have written,
         no inverse — see backup", the character stays.
  seq 2  pending delete_character{"Demo Manual"} (made by hand under that
         name) -> skipped the same way, the character stays.
  discard_preview lists neither (the discard would not delete them) -> [].
  => reversed [], skipped [(2, no inverse), (1, no inverse)], complete False.

Run 9 (a created character standing in a created place — the usual free-mode
  run, apply_home_schedule puts a new character at its new home). The
  discard deletes that character itself, so it is NOT an occupant to place
  anew, in either journal order:
  9a  seq 1 create location loc_p "Demo Patch"; seq 2 create character
      "Demo New" (delete_character{items: []}), then "Demo New" is put into
      loc_p. Preview (oldest-first, no chat rows, no memory rows naming it):
        'location loc_p "Demo Patch"'
        'character "Demo New" — 0 chat messages, 0 memory rows of other
         characters name it'
      and NO occupant line. undo: 2 -> Demo New deleted; 1 -> loc_p deleted,
      nobody stands in it any more. => reversed [2, 1], skipped [], complete.
  9b  seq 1 create character "Demo Early"; seq 2 create location loc_q
      "Demo Quay"; "Demo Early" and the pre-existing "Demo Stayer" are put
      into loc_q. Preview:
        'character "Demo Early" — 0 chat messages, 0 memory rows of other
         characters name it'
        'location loc_q "Demo Quay"'
        'character "Demo Stayer" stands in location loc_q "Demo Quay" — stays
         there, place them anew'
      undo: 2 -> loc_q deleted while both stand in it (two occupant records
      at seq 2: Early, Stayer); 1 -> Demo Early deleted, so its record is
      dropped. => reversed [2, 1], skipped == [(2, "Demo Stayer")] only,
      complete True; Demo Stayer still points at loc_q.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_undo.py
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_undo_clips_")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_wd_undo_"))

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core import soul_writer  # noqa: E402
from app.core.terrain_types import effective_catalog  # noqa: E402
from app.models import heightfield, memory, terrain  # noqa: E402
from app.models import character as character_model  # noqa: E402
from app.models import world as world_model  # noqa: E402
from app.models.world import (get_location_by_id, update_location_position,  # noqa: E402
                              upsert_location)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def loc(lid, name, description="", **extra):
    row = {"id": lid, "name": name, "description": description, "rooms": []}
    row.update(extra)
    upsert_location(row, sync_world=False)
    return get_location_by_id(lid)


# ── Run 1 ────────────────────────────────────────────────────────────────
loc("loc_m", "Demo Mill", "old")
loc("loc_p", "Demo Pier")
update_location_position("loc_p", 10, 20, 0)
run = wr.create_run("build", "m", "p", "u", 40, 300000)

# seq 1: create L
s = wr.begin(run, 1, "write", "create_location", {"data": {"name": "L"}}, "location")
loc("loc_l", "Demo Lakehouse")
wr.attach(run, s, "loc_l", {"op": "delete_location", "id": "loc_l"})
wr.complete(run, s, get_location_by_id("loc_l"), "created location loc_l")

# seq 2: add terrain area A
kind = sorted(effective_catalog())[0]
s = wr.begin(run, 1, "write", "add_terrain_area", {"kind": kind}, "terrain")
area = terrain.save_area({"kind": kind,
                          "polygon": [[0, -400], [100, -400], [100, -300], [0, -300]]})
wr.attach(run, s, area["id"], {"op": "delete_terrain_area", "id": area["id"]})
wr.complete(run, s, terrain.get_area(area["id"]), "added area")

# seq 3: M description old -> agent, then human
before_m = get_location_by_id("loc_m")
s = wr.begin(run, 1, "write", "update_location", {"id": "loc_m"}, "location", "loc_m")
cur = copy.deepcopy(before_m)
cur["description"] = "agent"
upsert_location(cur, sync_world=False)
b, w = wu.diff_keys(before_m, get_location_by_id("loc_m"))
check("(1) M diff is exactly description",
      (b, w) == ({"description": "old"}, {"description": "agent"}), (b, w))
wr.attach(run, s, "loc_m", {"op": "restore_location", "id": "loc_m", "before": b}, before=b)
wr.complete(run, s, w, "updated loc_m")
human = get_location_by_id("loc_m")
human["description"] = "human"
upsert_location(human, sync_world=False)

# seq 4: P moved
pos_before = wu.position_of(get_location_by_id("loc_p"))
check("(1) P before = (10, 20, 0)", pos_before == {"x": 10.0, "z": 20.0, "yaw": 0.0}, pos_before)
s = wr.begin(run, 1, "write", "place_location", {"id": "loc_p"}, "location", "loc_p",
             {"op": "restore_position", "id": "loc_p", "before": pos_before})
update_location_position("loc_p", 40.123456, -5, 370)
pos_written = wu.position_of(get_location_by_id("loc_p"))
check("(1) P stored (40.12, -5, 10)", pos_written == {"x": 40.12, "z": -5.0, "yaw": 10.0},
      pos_written)
wr.complete(run, s, pos_written, "placed loc_p")

# seq 5: pending create Q (inverse at begin, never completed)
wr.begin(run, 1, "write", "create_location", {"data": {"name": "Q"}}, "location", "loc_q",
         {"op": "delete_location", "id": "loc_q"})
loc("loc_q", "Demo Quay")

# seq 6: pending write without inverse
wr.begin(run, 1, "write", "update_location", {"id": "loc_m"}, "location", "loc_m")

rep = wu.undo(run)
check("(1) reversed [5, 4, 2, 1]", rep["reversed"] == [5, 4, 2, 1], rep)
check("(1) skipped seqs [6, 3]", [x["seq"] for x in rep["skipped"]] == [6, 3], rep["skipped"])
reasons = {x["seq"]: x["reason"] for x in rep["skipped"]}
check("(1) seq 6 reason no inverse",
      reasons.get(6) == "may have written, no inverse — see backup", reasons)
check("(1) seq 3 reason changed since", reasons.get(3) == "changed since", reasons)
check("(1) seq 3 names the key",
      next((x.get("keys") for x in rep["skipped"] if x["seq"] == 3), None) == ["description"])
check("(1) L gone", get_location_by_id("loc_l") is None)
check("(1) Q gone (pending create undone)", get_location_by_id("loc_q") is None)
check("(1) A gone", terrain.get_area(area["id"]) is None)
check("(1) M stays human", (get_location_by_id("loc_m") or {}).get("description") == "human")
check("(1) P back at (10, 20, 0)", wu.position_of(get_location_by_id("loc_p")) == pos_before,
      wu.position_of(get_location_by_id("loc_p")))
check("(1) not complete", rep["complete"] is False, rep)
check("(1) every write entry undone", wr.entries(run) == [])
rep2 = wu.undo(run)
check("(1) second undo reverses nothing",
      rep2 == {"reversed": [], "skipped": [], "complete": True}, rep2)
wr.set_status(run, "rollback_incomplete")

# ── Run 2 ────────────────────────────────────────────────────────────────
from app.models import inventory  # noqa: E402
from app.models.character import (get_character_config,  # noqa: E402
                                  get_character_profile, save_character_config,
                                  save_character_profile)

check("(2) fixture Demo Other created",
      save_character_profile("Demo Other", {"name": "Demo Other", "personality": "calm"},
                             create_new=True))
cfg = get_character_config("Demo Other")
cfg.pop("known_locations", None)
cfg["home_location"] = ""
save_character_config("Demo Other", cfg)
soul_writer.write_text("Demo Other", "soul/extra.md", "before text")

b_area = terrain.save_area({"kind": kind, "polygon": [[0, 0], [10, 0], [10, 10]],
                            "meta": {"scatter": []}})
run2 = wr.create_run("build 2", "m", "p", "u", 40, 300000)

# seq 1: update B
before_b = terrain.get_area(b_area["id"])
s = wr.begin(run2, 1, "write", "update_terrain_area", {"id": b_area["id"]}, "terrain",
             b_area["id"], {"op": "restore_terrain_area", "row": before_b})
terrain.save_area(dict(before_b, z_order=3), must_exist=True)
wr.complete(run2, s, terrain.get_area(b_area["id"]), "updated B")

# seq 2: add height area H
s = wr.begin(run2, 1, "write", "add_height_area", {}, "height")
h = heightfield.save_height_area({"polygon": [[0, 0], [20, 0], [20, 20]], "height_m": 4})
wr.attach(run2, s, h["id"], {"op": "delete_height_area", "id": h["id"]})
wr.complete(run2, s, h, "added H")

# seq 3: profile personality
pb = get_character_profile("Demo Other")
s = wr.begin(run2, 1, "write", "update_character", {"name": "Demo Other"}, "character",
             "Demo Other")
save_character_profile("Demo Other", dict(pb, personality="x"))
bp, wp = wu.diff_keys(pb, get_character_profile("Demo Other"))
check("(2) profile diff is personality", bp == {"personality": "calm"}, (bp, wp))
wr.attach(run2, s, "Demo Other", {"op": "restore_character", "name": "Demo Other",
                                  "profile": bp, "config": {}})
wr.complete(run2, s, {"profile": wp, "config": {}}, "updated Demo Other")

# seq 4: soul notes.md absent -> agent text
nb = soul_writer.read_text("Demo Other", "soul/notes.md")
check("(2) notes.md absent before", nb is None, nb)
s = wr.begin(run2, 1, "write", "update_character", {}, "character", "Demo Other",
             {"op": "restore_soul", "name": "Demo Other", "file_id": "soul/notes.md",
              "before_text": nb})
soul_writer.write_text("Demo Other", "soul/notes.md", "agent text")
wr.complete(run2, s, soul_writer.read_text("Demo Other", "soul/notes.md"), "soul notes")

# seq 5: soul extra.md -> agent two, then human two
eb = soul_writer.read_text("Demo Other", "soul/extra.md")
s = wr.begin(run2, 1, "write", "update_character", {}, "character", "Demo Other",
             {"op": "restore_soul", "name": "Demo Other", "file_id": "soul/extra.md",
              "before_text": eb})
soul_writer.write_text("Demo Other", "soul/extra.md", "agent two")
wr.complete(run2, s, soul_writer.read_text("Demo Other", "soul/extra.md"), "soul extra")
soul_writer.write_text("Demo Other", "soul/extra.md", "human two")

# seq 6 (turn 2): create Demo Lake with two new items
s = wr.begin(run2, 2, "write", "create_character", {"data": {"name": "Demo Lake"}},
             "character", "Demo Lake",
             {"op": "delete_character", "name": "Demo Lake", "items": []})
save_character_profile("Demo Lake", {"name": "Demo Lake"}, create_new=True)
i1 = inventory.add_item("Demo Scarf", category="outfit")["id"]
i2 = inventory.add_item("Demo Hat", category="outfit")["id"]
wr.attach(run2, s, "Demo Lake",
          {"op": "delete_character", "name": "Demo Lake", "items": [i1, i2]})
wr.complete(run2, s, {"name": "Demo Lake"}, "created Demo Lake")
inventory.add_to_inventory("Demo Other", i2)
with db.transaction() as conn:
    conn.execute("INSERT INTO chat_messages (character_name, partner, ts, role, content) "
                 "VALUES (?, ?, ?, ?, ?)", ("Demo Lake", "Demo Other", "t", "user", "hi"))

# seq 7 (turn 2): home/schedule of Demo Other
hb = wu.home_schedule_state("Demo Other")
check("(2) home before empty, known absent",
      hb["home_location"] == "" and hb["known_locations"] is None, hb)
s = wr.begin(run2, 2, "write", "update_character", {}, "character", "Demo Other")
c = get_character_config("Demo Other")
c["home_location"] = "loc_m"
c["known_locations"] = ["loc_m"]
save_character_config("Demo Other", c)
hb2, hw = wu.diff_keys(hb, wu.home_schedule_state("Demo Other"))
wr.attach(run2, s, "Demo Other", {"op": "restore_home_schedule", "name": "Demo Other",
                                  "before": hb2})
wr.complete(run2, s, hw, "home")

# Inserted by hand: add_memory would also embed the row (loads an ONNX model).
with db.transaction() as conn:
    conn.execute("INSERT INTO memories (character_name, tier, ts, content) "
                 "VALUES (?, ?, ?, ?)",
                 ("Demo Other", "episodic", "t", "Met Demo Lake at the pier"))
check("(2) memory count naming Demo Lake = 1",
      memory.count_other_memories_naming("Demo Lake") == 1,
      memory.count_other_memories_naming("Demo Lake"))
check("(2) % is literal", memory.count_other_memories_naming("Demo%") == 0,
      memory.count_other_memories_naming("Demo%"))
check("(2) _ is literal", memory.count_other_memories_naming("Demo_Lake") == 0,
      memory.count_other_memories_naming("Demo_Lake"))

preview = wu.discard_preview(run2)
check("(2) preview names Demo Lake with 1 chat message",
      any("Demo Lake" in ln and "1 chat messages" in ln for ln in preview), preview)
check("(2) preview names Demo Lake with 1 memory row",
      any("Demo Lake" in ln and "1 memory rows" in ln for ln in preview), preview)
check("(2) preview names height area", any(h["id"] in ln for ln in preview), preview)

rep = wu.undo(run2, turn=2)
check("(2) turn 2 reversed [7, 6]", rep["reversed"] == [7, 6], rep)
check("(2) I2 skipped item still in use",
      [(x["seq"], x["reason"], x.get("item")) for x in rep["skipped"]]
      == [(6, "item still in use", i2)], rep["skipped"])
check("(2) item in use -> not complete", rep["complete"] is False, rep)
c = get_character_config("Demo Other")
check("(2) home restored", c.get("home_location") == "", c.get("home_location"))
check("(2) known_locations absent again", "known_locations" not in c, c.get("known_locations"))
check("(2) Demo Lake gone", not character_model.character_row_exists("Demo Lake"))
check("(2) I1 deleted", inventory.get_item(i1) is None)
check("(2) I2 kept", inventory.get_item(i2) is not None)
check("(2) turn 1 untouched", len(wr.entries(run2, turn=1)) == 5)

rep = wu.undo(run2)
check("(2) turn 1 reversed [4, 3, 2, 1]", rep["reversed"] == [4, 3, 2, 1], rep)
check("(2) skipped [5] changed since",
      [(x["seq"], x["reason"]) for x in rep["skipped"]] == [(5, "changed since")],
      rep["skipped"])
check("(2) extra.md keeps human",
      soul_writer.read_text("Demo Other", "soul/extra.md") == "human two\n")
check("(2) notes.md gone", soul_writer.read_text("Demo Other", "soul/notes.md") is None)
check("(2) personality calm",
      get_character_profile("Demo Other").get("personality") == "calm")
check("(2) H gone", not any(x["id"] == h["id"] for x in heightfield.list_height_areas()))
rb = terrain.get_area(b_area["id"])
check("(2) B restored with scatter", rb == before_b, (rb, before_b))
wr.set_status(run2, "rollback_incomplete")

# ── Run 3 ────────────────────────────────────────────────────────────────
h2 = heightfield.save_height_area({"polygon": [[100, 100], [120, 100], [120, 120]],
                                   "height_m": 4})
run3 = wr.create_run("build 3", "m", "p", "u", 40, 300000)

# seq 1: delete of a location that never existed
s = wr.begin(run3, 1, "write", "create_location", {}, "location", "loc_missing",
             {"op": "delete_location", "id": "loc_missing"})
wr.complete(run3, s, None, "created loc_missing")

# seq 2: P moved by agent, then by a human
pb3 = wu.position_of(get_location_by_id("loc_p"))
check("(3) P starts at (10, 20, 0)", pb3 == {"x": 10.0, "z": 20.0, "yaw": 0.0}, pb3)
s = wr.begin(run3, 1, "write", "place_location", {"id": "loc_p"}, "location", "loc_p",
             {"op": "restore_position", "id": "loc_p", "before": pb3})
update_location_position("loc_p", 50, 50, 90)
wr.complete(run3, s, wu.position_of(get_location_by_id("loc_p")), "placed loc_p")
update_location_position("loc_p", 60, 60, 90)

# seq 3: height area H2 4 -> 7
h2_before = next(a for a in heightfield.list_height_areas() if a["id"] == h2["id"])
s = wr.begin(run3, 1, "write", "update_height_area", {"id": h2["id"]}, "height", h2["id"],
             {"op": "restore_height_area", "row": h2_before})
heightfield.save_height_area(dict(h2_before, height_m=7), must_exist=True)
h2_written = next(a for a in heightfield.list_height_areas() if a["id"] == h2["id"])
check("(3) H2 stored at 7", h2_written.get("height_m") == 7, h2_written)
wr.complete(run3, s, h2_written, "updated H2")

# seq 4: M gets a new key
mb = get_location_by_id("loc_m")
check("(3) M has no agent_note before", "agent_note" not in mb, mb)
s = wr.begin(run3, 1, "write", "update_location", {"id": "loc_m"}, "location", "loc_m")
upsert_location(dict(copy.deepcopy(mb), agent_note="n"), sync_world=False)
b, w = wu.diff_keys(mb, get_location_by_id("loc_m"))
check("(3) M diff is the absent agent_note",
      (b, w) == ({"agent_note": wu.ABSENT}, {"agent_note": "n"}), (b, w))
wr.attach(run3, s, "loc_m", {"op": "restore_location", "id": "loc_m", "before": b}, before=b)
wr.complete(run3, s, w, "updated loc_m")

# seq 5: profile gets a new key
pb = get_character_profile("Demo Other")
check("(3) profile has no hobby before", "hobby" not in pb, pb.get("hobby"))
s = wr.begin(run3, 1, "write", "update_character", {}, "character", "Demo Other")
save_character_profile("Demo Other", dict(pb, hobby="sailing"))
bp, wp = wu.diff_keys(pb, get_character_profile("Demo Other"))
check("(3) profile diff is the absent hobby",
      bp == {"hobby": wu.ABSENT} and wp == {"hobby": "sailing"}, (bp, wp))
wr.attach(run3, s, "Demo Other", {"op": "restore_character", "name": "Demo Other",
                                  "profile": bp, "config": {}})
wr.complete(run3, s, {"profile": wp, "config": {}}, "updated Demo Other")

# seq 6: create loc_r; its delete will be refused
s = wr.begin(run3, 1, "write", "create_location", {}, "location", "loc_r",
             {"op": "delete_location", "id": "loc_r"})
loc("loc_r", "Demo Ridge")
wr.complete(run3, s, get_location_by_id("loc_r"), "created loc_r")

_real_delete = world_model.delete_location
world_model.delete_location = lambda lid, *a, **k: False
try:
    rep = wu.undo(run3)
finally:
    world_model.delete_location = _real_delete
check("(3) reversed [5, 4, 3]", rep["reversed"] == [5, 4, 3], rep)
check("(3) skipped [6 refused, 2 changed, 1 gone]",
      [(x["seq"], x["reason"]) for x in rep["skipped"]]
      == [(6, "delete refused"), (2, "changed since"), (1, "already gone")], rep["skipped"])
check("(3) seq 2 names position",
      next((x.get("keys") for x in rep["skipped"] if x["seq"] == 2), None) == ["position"])
check("(3) not complete", rep["complete"] is False, rep)
check("(3) loc_r stays", get_location_by_id("loc_r") is not None)
check("(3) P stays at the human's (60, 60)",
      wu.position_of(get_location_by_id("loc_p")) == {"x": 60.0, "z": 60.0, "yaw": 90.0},
      wu.position_of(get_location_by_id("loc_p")))
h2_after = next(a for a in heightfield.list_height_areas() if a["id"] == h2["id"])
check("(3) H2 back at 4", h2_after.get("height_m") == 4, h2_after)
check("(3) agent_note removed", "agent_note" not in get_location_by_id("loc_m"))
check("(3) hobby removed", "hobby" not in get_character_profile("Demo Other"))
wr.set_status(run3, "rollback_incomplete")

# ── Run 4: only "already gone" -> complete ─────────────────────────────────
run4 = wr.create_run("build 4", "m", "p", "u", 40, 300000)
s = wr.begin(run4, 1, "write", "add_height_area", {}, "height", "ha_missing",
             {"op": "delete_height_area", "id": "ha_missing"})
wr.complete(run4, s, None, "added ha_missing")
rep = wu.undo(run4)
check("(4) only already gone, complete",
      [(x["seq"], x["reason"]) for x in rep["skipped"]] == [(1, "already gone")]
      and rep["reversed"] == [] and rep["complete"] is True, rep)
wr.set_status(run4, "rolled_back")

# ── Run 5: a read error is "undo failed", never "already gone" ─────────────
run5 = wr.create_run("build 5", "m", "p", "u", 40, 300000)
s = wr.begin(run5, 1, "write", "update_character", {}, "character", "Demo Other",
             {"op": "restore_character", "name": "Demo Other",
              "profile": {"hobby": wu.ABSENT}, "config": {}})
wr.complete(run5, s, {"profile": {"hobby": wu.ABSENT}, "config": {}}, "noop")
_real_exists = character_model.character_row_exists


def _boom(name):
    raise RuntimeError("disk read failed")


character_model.character_row_exists = _boom
try:
    rep = wu.undo(run5)
finally:
    character_model.character_row_exists = _real_exists
reason5 = (rep["skipped"] or [{}])[0].get("reason", "")
check("(5) read error -> undo failed", reason5.startswith("undo failed:"), rep)
check("(5) not complete", rep["complete"] is False, rep)
wr.set_status(run5, "rollback_incomplete")

# ── Run 6: absent home keys stay absent ───────────────────────────────────
check("(6) fixture Demo Bare created",
      save_character_profile("Demo Bare", {"name": "Demo Bare"}, create_new=True))
c6 = get_character_config("Demo Bare")
c6.pop("home_location", None)
c6.pop("home_room", None)
save_character_config("Demo Bare", c6)
c6 = get_character_config("Demo Bare")
check("(6) config has no home keys",
      "home_location" not in c6 and "home_room" not in c6, c6)
hb6 = wu.home_schedule_state("Demo Bare")
check("(6) state reads ABSENT for both",
      hb6["home_location"] == wu.ABSENT and hb6["home_room"] == wu.ABSENT, hb6)
run6 = wr.create_run("build 6", "m", "p", "u", 40, 300000)
s = wr.begin(run6, 1, "write", "update_character", {}, "character", "Demo Bare")
c6["home_location"] = "loc_m"
c6["home_room"] = "r_keep"
save_character_config("Demo Bare", c6)
b6, w6 = wu.diff_keys(hb6, wu.home_schedule_state("Demo Bare"))
check("(6) diff before = both ABSENT",
      b6 == {"home_location": wu.ABSENT, "home_room": wu.ABSENT}
      and w6 == {"home_location": "loc_m", "home_room": "r_keep"}, (b6, w6))
wr.attach(run6, s, "Demo Bare", {"op": "restore_home_schedule", "name": "Demo Bare",
                                 "before": b6})
wr.complete(run6, s, w6, "home")
rep = wu.undo(run6)
check("(6) reversed [1], complete",
      rep["reversed"] == [1] and rep["skipped"] == [] and rep["complete"] is True, rep)
c6 = get_character_config("Demo Bare")
check("(6) both keys absent again (not \"\")",
      "home_location" not in c6 and "home_room" not in c6,
      (c6.get("home_location"), c6.get("home_room")))
wr.set_status(run6, "rolled_back")

# ── Run 7: occupants of removed places are reported, never incomplete ────
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_current_room,
                                  save_character_current_location,
                                  save_character_current_room)

loc("loc_s", "Demo Shed", rooms=[{"id": "r_keep", "name": "Demo Hall"}])
for who in ("Demo Walker", "Demo Roomer"):
    check(f"(7) fixture {who} created",
          save_character_profile(who, {"name": who}, create_new=True))
run7 = wr.create_run("build 7", "m", "p", "u", 40, 300000)

# seq 1: create loc_n
s = wr.begin(run7, 1, "write", "create_location", {}, "location")
loc("loc_n", "Demo Nook")
wr.attach(run7, s, "loc_n", {"op": "delete_location", "id": "loc_n"})
wr.complete(run7, s, get_location_by_id("loc_n"), 'created location loc_n "Demo Nook"')

# seq 2: loc_s gets room r_new
sb = get_location_by_id("loc_s")
s = wr.begin(run7, 1, "write", "update_location", {"id": "loc_s"}, "location", "loc_s")
cur7 = copy.deepcopy(sb)
cur7["rooms"] = list(cur7.get("rooms") or []) + [{"id": "r_new", "name": "Demo Attic"}]
upsert_location(cur7, sync_world=False)
b7, w7 = wu.diff_keys(sb, get_location_by_id("loc_s"))
check("(7) loc_s diff is exactly rooms", sorted(b7) == ["rooms"], sorted(b7))
check("(7) r_new stored",
      any(r.get("id") == "r_new" for r in get_location_by_id("loc_s").get("rooms") or []))
wr.attach(run7, s, "loc_s", {"op": "restore_location", "id": "loc_s", "before": b7},
          before=b7)
wr.complete(run7, s, w7, "updated loc_s")

save_character_current_location("Demo Walker", "loc_n")
save_character_current_location("Demo Roomer", "loc_s")
save_character_current_room("Demo Roomer", "r_new")
places = character_model.list_character_places()
check("(7) Walker in loc_n, Roomer in loc_s/r_new",
      places.get("Demo Walker", ("",))[0] == "loc_n"
      and places.get("Demo Roomer") == ("loc_s", "r_new"), places)

preview7 = wu.discard_preview(run7)
check("(7) preview lists the place and both occupants, in order",
      preview7 == [
          'location loc_n "Demo Nook"',
          'character "Demo Roomer" stands in room "Demo Attic" (r_new) of location '
          "loc_s, which the undo removes — stays there, place them anew",
          'character "Demo Walker" stands in location loc_n "Demo Nook" — stays '
          "there, place them anew"], preview7)

rep = wu.undo(run7)
check("(7) reversed [2, 1]", rep["reversed"] == [2, 1], rep)
check("(7) two occupant records, seqs [2, 1]",
      [(x["seq"], x.get("occupant"), x["reason"]) for x in rep["skipped"]] == [
          (2, "Demo Roomer", '"Demo Roomer" stands in the removed place — place them anew'),
          (1, "Demo Walker", '"Demo Walker" stands in the removed place — place them anew')],
      rep["skipped"])
check("(7) Roomer record names room r_new",
      rep["skipped"][0].get("room") == "r_new" if rep["skipped"] else False, rep["skipped"])
check("(7) complete (occupants are informational)", rep["complete"] is True, rep)
check("(7) is_complete accepts occupant records", wu.is_complete(rep["skipped"]))
check("(7) loc_n gone", get_location_by_id("loc_n") is None)
check("(7) r_new gone, r_keep kept",
      sorted(r.get("id") for r in get_location_by_id("loc_s").get("rooms") or []
             if not str(r.get("id")).startswith("__")) == ["r_keep"],
      get_location_by_id("loc_s").get("rooms"))
check("(7) nobody moved: Walker still points at loc_n",
      get_character_current_location("Demo Walker") == "loc_n",
      get_character_current_location("Demo Walker"))
check("(7) nobody moved: Roomer still in r_new",
      get_character_current_room("Demo Roomer") == "r_new",
      get_character_current_room("Demo Roomer"))
wr.set_status(run7, "rolled_back")

# ── Run 8: a pending create_character is never deleted on a guess ─────────
run8 = wr.create_run("build 8", "m", "p", "u", 40, 300000)
wr.begin(run8, 1, "write", "create_character", {}, "character", "Demo Crash",
         {"op": "delete_character", "name": "Demo Crash", "items": []})
save_character_profile("Demo Crash", {"name": "Demo Crash", "created_by": "world_dev"},
                       create_new=True)
check("(8) the saver drops created_by",
      get_character_profile("Demo Crash").get("created_by") == "",
      get_character_profile("Demo Crash").get("created_by"))
wr.begin(run8, 1, "write", "create_character", {}, "character", "Demo Manual",
         {"op": "delete_character", "name": "Demo Manual", "items": []})
save_character_profile("Demo Manual", {"name": "Demo Manual"}, create_new=True)
check("(8) both entries pending without written",
      [(e["seq"], e["state"], e.get("written")) for e in wr.entries(run8)]
      == [(2, "pending", None), (1, "pending", None)], wr.entries(run8))
check("(8) preview lists neither", wu.discard_preview(run8) == [],
      wu.discard_preview(run8))
rep = wu.undo(run8)
check("(8) reversed []", rep["reversed"] == [], rep)
check("(8) skipped [(2, no inverse), (1, no inverse)]",
      [(x["seq"], x["reason"]) for x in rep["skipped"]]
      == [(2, "may have written, no inverse — see backup"),
          (1, "may have written, no inverse — see backup")], rep["skipped"])
check("(8) not complete", rep["complete"] is False, rep)
check("(8) Demo Crash kept", character_model.character_row_exists("Demo Crash"))
check("(8) Demo Manual kept", character_model.character_row_exists("Demo Manual"))
wr.set_status(run8, "rollback_incomplete")


# ── Run 9: a created character in a created place is no occupant ─────────
def _create_char(run, name):
    s = wr.begin(run, 1, "write", "create_character", {"data": {"name": name}},
                 "character", name, {"op": "delete_character", "name": name, "items": []})
    check(f"(9) {name} created",
          save_character_profile(name, {"name": name}, create_new=True))
    wr.complete(run, s, {"name": name}, f"created {name}")


def _create_loc(run, lid, name):
    s = wr.begin(run, 1, "write", "create_location", {}, "location")
    loc(lid, name)
    wr.attach(run, s, lid, {"op": "delete_location", "id": lid})
    wr.complete(run, s, get_location_by_id(lid), f'created location {lid} "{name}"')


def _char_line(name):
    return (f'character "{name}" — 0 chat messages, '
            "0 memory rows of other characters name it")


# 9a: place first, then the character
run9a = wr.create_run("build 9a", "m", "p", "u", 40, 300000)
_create_loc(run9a, "loc_p", "Demo Patch")
_create_char(run9a, "Demo New")
save_character_current_location("Demo New", "loc_p")
check("(9a) Demo New stands in loc_p",
      character_model.list_character_places().get("Demo New", ("",))[0] == "loc_p")
preview9a = wu.discard_preview(run9a)
check("(9a) preview: place + character, no occupant line",
      preview9a == ['location loc_p "Demo Patch"', _char_line("Demo New")], preview9a)
rep = wu.undo(run9a)
check("(9a) reversed [2, 1], skipped [], complete",
      rep["reversed"] == [2, 1] and rep["skipped"] == [] and rep["complete"] is True, rep)
check("(9a) loc_p and Demo New gone",
      get_location_by_id("loc_p") is None
      and not character_model.character_row_exists("Demo New"))
wr.set_status(run9a, "rolled_back")

# 9b: character first, then the place
check("(9b) fixture Demo Stayer created",
      save_character_profile("Demo Stayer", {"name": "Demo Stayer"}, create_new=True))
run9b = wr.create_run("build 9b", "m", "p", "u", 40, 300000)
_create_char(run9b, "Demo Early")
_create_loc(run9b, "loc_q", "Demo Quay")
save_character_current_location("Demo Early", "loc_q")
save_character_current_location("Demo Stayer", "loc_q")
places = character_model.list_character_places()
check("(9b) Early and Stayer stand in loc_q",
      places.get("Demo Early", ("",))[0] == "loc_q"
      and places.get("Demo Stayer", ("",))[0] == "loc_q", places)
preview9b = wu.discard_preview(run9b)
check("(9b) preview: character, place, only Stayer as occupant",
      preview9b == [_char_line("Demo Early"), 'location loc_q "Demo Quay"',
                    'character "Demo Stayer" stands in location loc_q "Demo Quay" '
                    "— stays there, place them anew"], preview9b)
rep = wu.undo(run9b)
check("(9b) reversed [2, 1]", rep["reversed"] == [2, 1], rep)
check("(9b) only Demo Stayer's occupant record is left",
      [(x["seq"], x.get("occupant")) for x in rep["skipped"]] == [(2, "Demo Stayer")],
      rep["skipped"])
check("(9b) complete", rep["complete"] is True, rep)
check("(9b) Demo Early gone, Demo Stayer kept and not moved",
      not character_model.character_row_exists("Demo Early")
      and get_character_current_location("Demo Stayer") == "loc_q",
      get_character_current_location("Demo Stayer"))
wr.set_status(run9b, "rolled_back")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all ok")
