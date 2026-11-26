#!/usr/bin/env python3
"""Smoke: World Dev free mode — acceptance: a village with residents, ONE
create_character call per NPC.

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 12.
A temp world (paths.init BEFORE any world-DB import) whose config.json enables
the tracked ``rp`` package (packages.enabled = "rp") and switches discovery
off (game.discovery_range_m = 0, so no place becomes known by proximity), an
EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_village.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Packages. The registry is NOT cleared: the packages the world declares
(``loader.declared_packages()`` = the rp manifest, read without running any
package code) are registered first, then a FAKE species package in addition:

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      hair  color  select [blonde, red], allow_custom
            length select [short, long]

It declares no clothing slots, so outfits use the core slots (top, bottom,
feet are among them). rp gives human-roleplay the stats attention 50,
courage 50, stamina 80 (plugins/rp/templates/character/rp.json).

Soul fields of human-roleplay (shared/templates/character/base-character.json
merged into human-roleplay.json, template order): character_personality,
character_presence, character_task, character_soul, character_beliefs,
character_lessons, character_goals — every one is sent with text, so no
"soul sections without content" gap.

Run (one run; turn 1 = reads + locations, turn 2 = the two NPCs, turn 3 =
check_run):
  1. describe_template{human-roleplay, female} -> ok, a "read" row; the
     courage stat is listed as "- courage [status]: whole number 0-100" (rp)
     and the hair slot as "hair: color=- [blonde|red|other]; length=- [short|long]"
     (fake package) — i.e. both package sources are live at once.
  2. create_location x3, each with x/z (so no "unplaced" gap):
       Demo Cottage  rooms [Room]          at (0, 0)
       Demo Square   no rooms              at (60, 0)
       Demo Bakery   rooms [Shop, Oven]    at (120, 0)
     Demo Square's line ends "; complete"; the two places WITH rooms end
     "; missing: no floor plan (set_room_layout)" (E5 of plan
     2026-11-25-world-dev-free-p2-buildings-terrain.md: a run-created place
     with a real room and no room layout / outline / building model), so
     each gets set_room_layout right after its create — 4 × 4 m rooms side
     by side from x -2 (Cottage: Room at x -2) / x -4 (Bakery: Shop at -4,
     Oven at 0), y -2 — and that line ends "; complete".
  3. create_character Demo Miller, ONE call:
       data: name, gender female, importance 2, courage 60, all seven soul
             fields, body_slots hair {color red, length long},
             outfits Daily (top Demo Linen Shirt, bottom Demo Brown Trousers,
             feet Demo Leather Boots) and Work (top Demo Flour Smock, bottom
             Demo Work Trousers, feet Demo Clogs), wear "Work"
       home Demo Cottage / Room
       schedule [{0 sleep}, {6 Demo Bakery "baking"}, {12 Demo Square
                 "market"}, {20 Demo Cottage "evening"}]
       known_places [Demo Square]
     -> line ends "; missing: no secret (add_secret)" (home placed, placed
     at it, two outfits, one worn, schedule, every soul field, both hair
     attributes, knows more than its home — only the secret of plan
     2026-11-25-world-dev-free-complete-characters-budget Task 5 is missing;
     the skill manager's list is emptied, so no skill group is open).
  4. create_character Demo Weaver likewise:
       data: gender female, importance 2, courage 40, all soul fields,
             hair {blonde, short}, outfits Day (Demo Wool Dress on top+bottom,
             feet Demo Felt Shoes) and Night (Demo Night Gown on top+bottom),
             wear "Day"
       home Demo Cottage / Room
       schedule [{0 sleep}, {9 Demo Square "weaving"}]
       known_places [Demo Bakery]
     -> "; missing: no secret (add_secret)" (as Demo Miller).
  5. check_run{} -> exactly
       'character "Demo Miller": missing: no secret (add_secret) · media pending:
        no portrait; no base body'   (one line; the run's media is on —
        create_run's default — and temp storage holds no profile image and no
        base body for these humanoid human-roleplay characters on the
        base-body pipeline),
       the same line for Demo Weaver,
       "3 of 5 elements complete"   (3 created places complete, the 2 created
       characters lack their secret).

Assertions after the run:
  (a) Demo Miller current_location == Cottage id, current_room == the id of
      Cottage's room named "Room" (a new character is placed at its home and
      home room; ids are assigned by the writer, read back from the row).
  (b) get_equipped_pieces(Demo Miller) == outfit_set_pieces_by_slot(the
      stored "Work" set) and its slots are exactly {top, bottom, feet}; the
      three item ids are the catalog items named Demo Flour Smock / Demo
      Work Trousers / Demo Clogs (the worn set, not Daily).
      Demo Weaver: slots {top, bottom, feet}; top and bottom are the SAME
      item (Demo Wool Dress covers both), feet Demo Felt Shoes.
  (c) Demo Miller status_effects == {attention 50, courage 60, stamina 80}
      (two template defaults + the sent value); Weaver courage 40.
      config importance == 2 (an int).
  (d) known_locations(Demo Miller) == [Cottage, Bakery, Square]: home first,
      then the schedule places in hour order (Bakery 6, Square 12; Cottage
      at 20 is already known), then known_places — Square is already there,
      so it is not added twice. Demo Weaver == [Cottage, Square, Bakery]
      (home, schedule Square, known_places Bakery appended).
  (e) travel: travel_engine.start_journey(Demo Miller, Bakery) does not
      answer "unknown_target" (Bakery is known). (Its stored journey is
      removed with the character by the undo below.)
  (f) journal: rows of kind "write" == 7 (3 places + 2 floor plans +
      2 characters — one row per write call), kind "read" == 2
      (describe_template, check_run), no "refused" row.
  (g) discard_preview(run): 3 lines naming the three places and 2 lines
      naming the characters with their piece counts — Demo Miller brought
      6 pieces (3 + 3), Demo Weaver 3 (2 + 1): "6 outfit pieces it brought"
      / "3 outfit pieces it brought" (world_dev_undo.discard_preview wording).
  (h) undo(run) -> complete True, nothing skipped; afterwards the world.db
      dump equals the pre-run dump in every table except the journal
      (world_dev_journal, world_dev_runs), SQLite's own sqlite_sequence and
      the derived height raster world_heightfield (same skip set and reason
      as scripts/smoke_world_dev_tools.py db_dump).

Second part — exactness in a LIVED-IN world (the case the empty world above
cannot show). A setup run that is NOT undone builds:
  Demo Inn (rooms [Hall]) at (0, 200), Demo Market (no rooms) at (60, 200),
  Demo Resident (outfit Daily top/bottom/feet, worn) with home Demo Inn / Hall
  -> the resident stands in the Hall.
Then the notification window is filled to its cap MAX_NOTIFICATIONS = 200
(app/models/notifications.py) with raw rows, oldest first (ts
"2026-01-01T00:00:00.000" + i ms): 198 of kind "message" titled Demo
Resident ("old note <i>"), ONE of kind "room_furnish" titled "Demo Guest"
(a room label that happens to equal a character name; room_furnish stores the
room label in title) at i = 100, and ONE of kind "message" titled "Demo
Stranger" ("stranger note", a notice about a character that does not exist)
at i = 150. Then BEFORE2 = db_dump() and run 2:
  6. create_character Demo Lodger (outfit Daily top/bottom/feet, wear Daily),
     home Demo Inn / Hall — the resident already stands there; a first
     placement writes no leaves/enters line, so the resident perceives nothing.
  7. create_character Demo Guest with NO outfits, home Demo Market — no room,
     decency of a place without one = "public" (outfit_compliance
     .resolve_decency default), nothing worn, nothing in the inventory, so
     the compliance run finds real violations:
     -> the line carries "outfit does not fit the public place — missing:"
        (the compliance warning) and still names the gap "wears nothing";
     -> notifications still number 200 and none is of kind outfit_mismatch
        (the free-mode create writes no notice: it would evict "old note 0").
  8. create_character Demo Stranger -> refused: delete_character (the undo
     of a create) sweeps notifications titled with the name (kind other than
     room_furnish), so the existing "stranger note" would go with the undo;
     the line names "notifications: 1", no character row, the note stays.
  (i) undo(run 2) -> complete, nothing skipped, db_dump() == BEFORE2 — in
      particular the window keeps "old note 0" and the room_furnish row
      titled "Demo Guest" survives the delete of the character Demo Guest;
      the "stranger note" is still there.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_village_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_village_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.get_config_path().write_text(json.dumps(
    {"packages": {"enabled": "rp"}, "game": {"discovery_range_m": 0}}))

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import travel_engine  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.models import inventory as invmod  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  get_character_config,
                                  get_character_current_location,
                                  get_character_current_room,
                                  get_character_outfits, get_character_profile,
                                  get_known_locations)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.world import get_location_by_id  # noqa: E402
from app.plugins import loader, registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# The skill manager loads (and re-registers) the packages on its first use;
# the completeness line of a character write asks it for the skill groups
# (plan 2026-11-25-world-dev-free-complete-characters-budget, Task 5), so it
# is loaded first, and its list is emptied: the skill-group gap is covered by
# smoke_world_dev_completeness, this village has none.
from app.core.dependencies import get_skill_manager  # noqa: E402

get_skill_manager().skills[:] = []

# The world's own packages (rp) stay; the fake species package comes in addition.
for _pkg in loader.declared_packages():
    registry.register_package(_pkg)
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    body_slots=[
        BodySlotSpec(id="hair", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blonde", "red"], "allow_custom": True},
            "length": {"type": "select", "options": ["short", "long"]},
        }),
    ]))
clear_template_cache()
check("setup: rp is registered next to the fake package",
      {p.id for p in registry.packages()} >= {"rp", "smoke_species"},
      [p.id for p in registry.packages()])

#: As scripts/smoke_world_dev_tools.py: the journal, SQLite's counter and the
#: derived height raster.
_DUMP_SKIP = {"world_dev_journal", "world_dev_runs", "world_dev_media", "world_dev_media_baseline",
              "sqlite_sequence",
              "world_heightfield"}


def db_dump():
    """Every row of every table (skip set above), with its rowid."""
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


def dump_diff(a, b):
    return [t for t in sorted(set(a) | set(b)) if a.get(t) != b.get(t)]


SOUL_KEYS = ["character_personality", "character_presence", "character_task",
             "character_soul", "character_beliefs", "character_lessons",
             "character_goals"]


def soul(who):
    return {key: f"{who}: demo text of {key}." for key in SOUL_KEYS}


def piece(name, *slots):
    return {"name": name, "slots": list(slots), "prompt_fragment": name.lower()}


BEFORE = db_dump()
run = wr.create_run("village", "m", "p", "u", 40, 600000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


# ── 1. schema read ──────────────────────────────────────────────────────
res = call(1, "describe_template", {"template": "human-roleplay", "gender": "female"})
check("1 describe_template ok", res.ok, res.line)
check("1 lists the rp stat courage", "- courage [status]: whole number 0-100" in res.line,
      res.line[:400])
check("1 lists the fake hair slot",
      "hair: color=- [blonde|red|other]; length=- [short|long]" in res.line, res.line[:400])

# ── 2. three places ─────────────────────────────────────────────────────
PLACES = {}
for name, rooms, x in (("Demo Cottage", ["Room"], 0), ("Demo Square", [], 60),
                       ("Demo Bakery", ["Shop", "Oven"], 120)):
    data = {"name": name, "description": f"{name}, a demo place."}
    if rooms:
        data["rooms"] = [{"name": r} for r in rooms]
    res = call(1, "create_location", {"data": data, "x": x, "z": 0})
    tail = "; missing: no floor plan (set_room_layout)" if rooms else "; complete"
    check(f"2 create_location {name} -> {tail}", res.ok and res.line.endswith(tail),
          res.line)
    PLACES[name] = wr.entries(run)[0]["target_id"]
    if rooms:
        stored = (get_location_by_id(PLACES[name]) or {}).get("rooms") or []
        x0 = -2 * len(rooms)
        plan = [{"id": next(r["id"] for r in stored if r.get("name") == rn),
                 "x": x0 + 4 * i, "y": -2, "w": 4, "d": 4} for i, rn in enumerate(rooms)]
        res = call(1, "set_room_layout", {"location_id": PLACES[name],
                                          "layout": {"rooms": plan}})
        check(f"2 set_room_layout {name} -> complete",
              res.ok and res.line.endswith("; complete"), res.line)
COTTAGE, SQUARE, BAKERY = (PLACES[n] for n in ("Demo Cottage", "Demo Square", "Demo Bakery"))
ROOM = next((r.get("id") for r in (get_location_by_id(COTTAGE) or {}).get("rooms") or []
             if r.get("name") == "Room"), None)
check("2 Cottage has its room 'Room'", bool(ROOM), get_location_by_id(COTTAGE))

# ── 3. Demo Miller, one call ────────────────────────────────────────────
miller = {"name": "Demo Miller", "gender": "female", "importance": 2, "courage": 60,
          "body_slots": {"hair": {"color": "red", "length": "long"}},
          "outfits": [
              {"name": "Daily", "pieces": [piece("Demo Linen Shirt", "top"),
                                           piece("Demo Brown Trousers", "bottom"),
                                           piece("Demo Leather Boots", "feet")]},
              {"name": "Work", "pieces": [piece("Demo Flour Smock", "top"),
                                          piece("Demo Work Trousers", "bottom"),
                                          piece("Demo Clogs", "feet")]}],
          "wear": "Work", **soul("Demo Miller")}
res = call(2, "create_character", {
    "data": miller, "home": "Demo Cottage", "home_room": "Room",
    "schedule": [{"hour": 0, "sleep": True},
                 {"hour": 6, "location": "Demo Bakery", "role": "baking"},
                 {"hour": 12, "location": "Demo Square", "role": "market"},
                 {"hour": 20, "location": "Demo Cottage", "role": "evening"}],
    "known_places": ["Demo Square"]})
NO_SECRET = "; missing: no secret (add_secret)"
check("3 Demo Miller -> only the secret missing", res.ok and res.line.endswith(NO_SECRET),
      res.line)

# ── 4. Demo Weaver, one call ────────────────────────────────────────────
weaver = {"name": "Demo Weaver", "gender": "female", "importance": 2, "courage": 40,
          "body_slots": {"hair": {"color": "blonde", "length": "short"}},
          "outfits": [
              {"name": "Day", "pieces": [piece("Demo Wool Dress", "top", "bottom"),
                                         piece("Demo Felt Shoes", "feet")]},
              {"name": "Night", "pieces": [piece("Demo Night Gown", "top", "bottom")]}],
          "wear": "Day", **soul("Demo Weaver")}
res = call(2, "create_character", {
    "data": weaver, "home": COTTAGE, "home_room": "Room",
    "schedule": [{"hour": 0, "sleep": True},
                 {"hour": 9, "location": SQUARE, "role": "weaving"}],
    "known_places": ["Demo Bakery"]})
check("4 Demo Weaver -> only the secret missing", res.ok and res.line.endswith(NO_SECRET),
      res.line)

# ── 5. check_run ────────────────────────────────────────────────────────
res = call(3, "check_run", {})
check("5 check_run: 3 of 5 complete", res.ok and res.line.splitlines() == [
    f'character "{who}": missing: no secret (add_secret) · media pending: '
    "no portrait; no base body" for who in ("Demo Miller", "Demo Weaver")]
    + ["3 of 5 elements complete"], res.line)

# ── (a) position ────────────────────────────────────────────────────────
check("(a) Miller stands in the Cottage",
      get_character_current_location("Demo Miller") == COTTAGE,
      get_character_current_location("Demo Miller"))
check("(a) Miller stands in its room 'Room'",
      get_character_current_room("Demo Miller") == ROOM,
      (get_character_current_room("Demo Miller"), ROOM))

# ── (b) worn outfit ─────────────────────────────────────────────────────
items_by_name = {}
for it in invmod.list_items():
    items_by_name.setdefault(it.get("name"), []).append(it.get("id"))


def item_id(name):
    ids = items_by_name.get(name) or []
    return ids[0] if len(ids) == 1 else ids


eq_m = invmod.get_equipped_pieces("Demo Miller")
work = next((o for o in get_character_outfits("Demo Miller") if o.get("name") == "Work"), {})
check("(b) Miller wears exactly the stored Work set",
      eq_m == invmod.outfit_set_pieces_by_slot(work), (eq_m, work))
check("(b) Miller: Work pieces by slot", eq_m == {
    "top": item_id("Demo Flour Smock"), "bottom": item_id("Demo Work Trousers"),
    "feet": item_id("Demo Clogs")}, eq_m)
eq_w = invmod.get_equipped_pieces("Demo Weaver")
check("(b) Weaver: the dress covers top and bottom, shoes on feet", eq_w == {
    "top": item_id("Demo Wool Dress"), "bottom": item_id("Demo Wool Dress"),
    "feet": item_id("Demo Felt Shoes")}, eq_w)

# ── (c) stats and config ────────────────────────────────────────────────
se = (get_character_profile("Demo Miller") or {}).get("status_effects")
check("(c) Miller status_effects", se == {"attention": 50, "courage": 60, "stamina": 80}, se)
se_w = (get_character_profile("Demo Weaver") or {}).get("status_effects") or {}
check("(c) Weaver courage 40", se_w.get("courage") == 40, se_w)
imp = (get_character_config("Demo Miller") or {}).get("importance")
check("(c) Miller importance 2 (int)", imp == 2 and type(imp) is int, imp)

# ── (d) known places ────────────────────────────────────────────────────
check("(d) Miller knows [Cottage, Bakery, Square]",
      get_known_locations("Demo Miller") == [COTTAGE, BAKERY, SQUARE],
      get_known_locations("Demo Miller"))
check("(d) Weaver knows [Cottage, Square, Bakery]",
      get_known_locations("Demo Weaver") == [COTTAGE, SQUARE, BAKERY],
      get_known_locations("Demo Weaver"))

# ── (e) travel ──────────────────────────────────────────────────────────
_journey, reason = travel_engine.start_journey("Demo Miller", BAKERY)
check("(e) Miller -> Bakery is no unknown_target", reason != "unknown_target", reason)

# ── (f) journal ─────────────────────────────────────────────────────────
kinds = [s["kind"] for s in wr.steps(run)]
check("(f) 7 write rows", kinds.count("write") == 7, kinds)
check("(f) 2 read rows", kinds.count("read") == 2, kinds)
check("(f) no refused row", "refused" not in kinds, kinds)

# ── (g) discard_preview ─────────────────────────────────────────────────
preview = wu.discard_preview(run)
for name in ("Demo Cottage", "Demo Square", "Demo Bakery"):
    check(f"(g) preview names {name} once", sum(name in l for l in preview) == 1, preview)
check("(g) preview: Miller with 6 pieces",
      sum("Demo Miller" in l and "6 outfit pieces it brought" in l for l in preview) == 1,
      preview)
check("(g) preview: Weaver with 3 pieces",
      sum("Demo Weaver" in l and "3 outfit pieces it brought" in l for l in preview) == 1,
      preview)
check("(g) preview has exactly 5 lines", len(preview) == 5, preview)

# ── (h) undo ────────────────────────────────────────────────────────────
result = wu.undo(run)
check("(h) undo complete", result.get("complete") is True, result)
check("(h) nothing skipped", not result.get("skipped"), result.get("skipped"))
AFTER = db_dump()
diff = dump_diff(BEFORE, AFTER)
# Every table that differs, with ALL its extra rows (left behind by the
# undo) and all its missing rows (taken by the undo although they were there).
check("(h) world.db equals the pre-run dump", diff == [],
      {t: {"extra": [r for r in AFTER.get(t, []) if r not in BEFORE.get(t, [])],
           "missing": [r for r in BEFORE.get(t, []) if r not in AFTER.get(t, [])]}
       for t in diff})

# ── Second part: a lived-in world ──────────────────────────────────────
wr.set_status(run, "rolled_back")  # one open run at a time
setup = wr.create_run("village-setup", "m", "p", "u", 40, 600000)


def scall(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=setup, turn=1), tool, args)


SETUP_PLACES = {}
for name, rooms, x in (("Demo Inn", ["Hall"], 0), ("Demo Market", [], 60)):
    data = {"name": name, "description": f"{name}, a demo place."}
    if rooms:
        data["rooms"] = [{"name": r} for r in rooms]
    res = scall("create_location", {"data": data, "x": x, "z": 200})
    check(f"setup create_location {name}", res.ok, res.line)
    SETUP_PLACES[name] = wr.entries(setup)[0]["target_id"]
INN = SETUP_PLACES["Demo Inn"]
HALL = next((r.get("id") for r in (get_location_by_id(INN) or {}).get("rooms") or []
             if r.get("name") == "Hall"), None)


def dressed(who):
    return {"name": who, "gender": "female", "importance": 1,
            "outfits": [{"name": "Daily", "pieces": [
                piece(f"{who} Shirt", "top"), piece(f"{who} Trousers", "bottom"),
                piece(f"{who} Boots", "feet")]}],
            "wear": "Daily", **soul(who)}


res = scall("create_character", {"data": dressed("Demo Resident"),
                                 "home": "Demo Inn", "home_room": "Hall"})
check("setup Demo Resident created", res.ok, res.line)
check("setup the resident stands in the Hall",
      get_character_current_room("Demo Resident") == HALL,
      (get_character_current_room("Demo Resident"), HALL))

with db.transaction() as _c:
    for i in range(200):
        kind, title, body = (("room_furnish", "Demo Guest", "furnish note") if i == 100
                             else ("message", "Demo Stranger", "stranger note") if i == 150
                             else ("message", "Demo Resident", f"old note {i}"))
        _c.execute("INSERT INTO notifications (ts, kind, title, body, read, meta) "
                   "VALUES (?, ?, ?, ?, 0, ?)",
                   (f"2026-01-01T00:00:00.{i:03d}", kind, title, body,
                    json.dumps({"str_id": f"n{i}", "character": title, "metadata": {}})))


def notes():
    return [tuple(r) for r in get_connection().execute(
        "SELECT kind, title, body FROM notifications ORDER BY ts").fetchall()]


check("setup the window is full (200)", len(notes()) == 200, len(notes()))
wr.set_status(setup, "accepted")  # the setup stays; one open run at a time

BEFORE2 = db_dump()
run2 = wr.create_run("village-2", "m", "p", "u", 40, 600000)
res = wt.run_tool(wt.ToolCtx(run_id=run2, turn=1), "create_character", {
    "data": dressed("Demo Lodger"), "home": "Demo Inn", "home_room": "Hall"})
check("6 Demo Lodger created in the occupied Hall", res.ok, res.line)
check("6 the lodger stands in the Hall",
      get_character_current_room("Demo Lodger") == HALL,
      get_character_current_room("Demo Lodger"))
guest = {"name": "Demo Guest", "gender": "female", "importance": 1, **soul("Demo Guest")}
res = wt.run_tool(wt.ToolCtx(run_id=run2, turn=1), "create_character", {
    "data": guest, "home": "Demo Market"})
check("7 Demo Guest created", res.ok, res.line)
check("7 the line reports the violation",
      "outfit does not fit the public place — missing:" in res.line, res.line)
check("7 the line names the gap 'wears nothing'", "wears nothing" in res.line, res.line)
_n = notes()
check("7 the window still holds 200 notes", len(_n) == 200, len(_n))
check("7 no outfit_mismatch notice written",
      not any(k == "outfit_mismatch" for k, _t, _b in _n), [r for r in _n if r[0] != "message"])
check("7 'old note 0' is still there", ("message", "Demo Resident", "old note 0") in _n)
# A notice titled "Demo Stranger" exists, but no such character: the undo of
# a create (delete_character) would sweep it, so the create is refused.
res = wt.run_tool(wt.ToolCtx(run_id=run2, turn=1), "create_character", {
    "data": {"name": "Demo Stranger", "gender": "female", "importance": 1,
             **soul("Demo Stranger")}})
check("8 Demo Stranger refused: a notice already carries the name",
      not res.ok and not res.wrote and "notifications: 1" in res.line
      and not character_row_exists("Demo Stranger"), res)
check("8 the stranger note is still there",
      ("message", "Demo Stranger", "stranger note") in notes())

result2 = wu.undo(run2)
check("(i) undo complete", result2.get("complete") is True, result2)
check("(i) nothing skipped", not result2.get("skipped"), result2.get("skipped"))
AFTER2 = db_dump()
diff2 = dump_diff(BEFORE2, AFTER2)
check("(i) world.db equals the pre-run-2 dump", diff2 == [],
      {t: {"extra": [r for r in AFTER2.get(t, []) if r not in BEFORE2.get(t, [])],
           "missing": [r for r in BEFORE2.get(t, []) if r not in AFTER2.get(t, [])]}
       for t in diff2})
check("(i) the room_furnish row titled 'Demo Guest' survived",
      ("room_furnish", "Demo Guest", "furnish note") in notes())
check("(i) the stranger note survived",
      ("message", "Demo Stranger", "stranger note") in notes())

if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("smoke_world_dev_village: all checks passed")
