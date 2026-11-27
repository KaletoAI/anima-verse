#!/usr/bin/env python3
"""Smoke: World Dev free mode — item catalog, inventory, room items (gap 12, E14).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 10.
A temp world (paths.init BEFORE any world-DB import; STORAGE_DIR / INSTANCE_DIR
temp), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool call goes
through world_dev_tools.run_tool exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_items.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixtures (before any run, through the core directly):
  character "Demo Smith" (save_character_profile, template human-roleplay) —
  an empty inventory; SECRET = add_item("Demo Letter", category "document",
  reveals_secret {...}); SMOCK = add_item("Demo Smock", category
  "outfit_piece", slots ["top"]); ANVIL = add_item("Demo Anvil", "tool");
  BUCKET = add_item("Demo Bucket", "tool"); a pre-existing place
  loc_demo_barn "Demo Barn" (upsert_location, pin (200, 200), a 10 m square
  boundary = map_layout_apply.seed_boundary(), room "room_barn" "Barn" WITHOUT
  an "items" key); PRE_BARN = get_location_by_id(loc_demo_barn) read after it.

Item ids: create_item mints "item_" + 8 hex digits (world_dev_tools._new_id)
BEFORE the journal row is begun; the stored item carries exactly that id.

Run 1 (turn 1 unless named):
  (a) create_item{name "Demo Hammer", category "tool"} -> ok, the line names
      the id; get_item(id).name == "Demo Hammer"; the journal row's target is
      ("item", id) with inverse {"op": "delete_items", "ids": [id]}.
      create_item{name "demo hammer"} -> refused naming that id + "reuse it",
      without "outfit piece" (a tool cannot be one); "demo smock" -> refused
      naming SMOCK + "an outfit piece {item_id}" (it is clothing).
  (a3) CHARM = add_item("Demo Charm", outfit_piece, slots ["neck"], jewellery
      kind "charm" — a part item (accessory_parts.is_part; skipped when the
      catalog does not store it as one); create_item{name "demo charm"} ->
      refused naming CHARM + "part item" + "another name" (find_items hides
      part items; the name is still taken).
  (a2) find_items{query "demo hammer"} -> one line, starting
      '<id> "Demo Hammer" tool'; find_items{slot "top", query "demo smock"} ->
      one line containing '"Demo Smock" outfit_piece [top]'. A shared item
      (shared/items/items.json read at runtime with list_shared_items(); the
      case is skipped when the library is empty) is listed with "shared".
  (b) create_item{category "outfit_piece"} -> refused, the line lists
      "tool" (VALID_ITEM_CATEGORIES minus outfit_piece and garment); category
      "garment" -> refused the same way; list_catalog item_categories names
      "tool" but neither "garment" nor "outfit_piece"; rarity "epic" ->
      refused; stackable true without max_stack -> refused; max_stack 5 without
      stackable -> refused. None stored a catalog row (list_items count same).
  (c) give_items{Demo Smith, [{hammer, 1}]} -> ok; the entry has quantity 1
      and obtained_method "manual".
  (c2) the hammer (non-stackable) again -> refused "already holds it"; the
      stored entry (incl. obtained_at) equals the one read after (c).
  (c3) CHISEL = create_item "Demo Chisel" (tool, non-stackable); give
      quantity 2 -> refused "not stackable"; nothing held.
  (c4) NAILS = create_item{"Demo Nails", "consumable", stackable true,
      max_stack 10}; give 6 -> ok (6, R1); give 5 -> refused (6 + 5 = 11 > 10,
      the line names "max_stack 10"); give 4 -> ok (6 + 4 = 10, R2).
      The same item twice in one call -> refused "twice"; quantity 0 ->
      refused; an unknown character -> refused.
  (d) SECRET -> refused "reveals a secret" in give_items.
  (e) create_location "Demo Forge" with room "Forge"; add_room_item is always
      refused in World Dev with "items in rooms are invisible in the world"
      (nothing written to the room; journal row "refused").
  (e2) the PRE-EXISTING barn: set_room_layout{room_barn at x -4, y -4, w 8,
      d 8} -> ok; add_room_item on the barn is refused likewise.
  (i) RAG = create_item "Demo Rag"; delete_created{item, RAG} in the same turn
      -> ok, RAG gone. RAG2 = create_item "Demo Rag2" in turn 1;
      delete_created{item, RAG2} in turn 2 -> refused "earlier turn" (an
      earlier-turn item delete has no exact re-creation); delete_created of
      the held hammer in turn 1 -> refused "still held".
  (i2) BOOK = create_item "Demo Book" (document); update_location{barn, patch
      {knowledge_item_id BOOK}} -> ok; delete_created{item, BOOK} -> refused
      "knowledge item" naming loc_demo_barn (a delete would leave the barn
      naming a missing id); BOOK stays.
  discard_preview -> contains 'item <id> "<name>"' for HAMMER, NAILS, CHISEL,
      RAG2, BOOK and the Demo Forge location line; no line names "Demo Rag"" (gone).
      Every holder of them is one the undo takes back (Smith's gives undone
      newest-first, NAILS 10 -> 6 -> gone; the created forge), so the lines
      carry no "still held" suffix.
  (f) undo(run) -> complete; Demo Smith holds nothing; HAMMER, NAILS, CHISEL,
      RAG2, BOOK are gone from the catalog (the barn's restore_location of
      (i2) is newer than BOOK's create, so the barn no longer names it); Demo
      Forge is gone; the barn row equals PRE_BARN (JSON) and its room has NO
      "items" key.

Run 2 (foreign changes; run 1 is set to "accepted" first — one open run):
  (g) TONGS = create_item "Demo Tongs"; give to Demo Smith -> ok; the admin
      edits the entry (update_inventory_entry notes "x"). PLIERS = create_item
      "Demo Pliers"; the admin lays it in the barn room (add_item_to_room, not
      journaled). discard_preview lists 'item <TONGS> "Demo Tongs" is still
      held by character "Demo Smith" — stays' (the give's undo is changed
      since) and 'item <PLIERS> "Demo Pliers" is still held by room room_barn
      "Barn" of location loc_demo_barn — stays'.
  (h) add_room_item{barn, BUCKET, 1} -> refused ("items in rooms are invisible
      in the world"); the admin adds ANVIL to the barn room directly
      (add_item_to_room).
  undo(run) -> complete False; a skip "changed since" with keys [TONGS] (the
      inventory step), a skip "item still in use" with item TONGS, a skip
      "item still in use" with item PLIERS. The entry keeps notes "x"; the barn
      room keeps ANVIL and PLIERS.

Runs 3-5 — a holder the run created, kept holding by a foreign change; the
order of creation decides when the undo walk (newest-first) meets the item:
  run 3 (S1): create_location "Demo Smithy" (room "Shop"), THEN create_item
      INGOT; the admin lays INGOT in the shop (add_item_to_room). The walk
      reaches INGOT's delete_items while the smithy still exists (skip "item
      still in use"), then deletes the smithy; undo()'s final cleanup pass
      deletes INGOT, which nothing holds any more, and drops that skip. So:
      preview has the plain line 'item <INGOT> "Demo Ingot"' (the created
      place lets go); undo complete, no item-in-use skip, INGOT and the
      smithy gone.
  run 4 (S6): create_character "Demo Apprentice", THEN create_item COINS
      (stackable, max_stack 10); give 3; play takes 1
      (remove_from_inventory) -> 2. Preview: plain 'item <COINS> "Demo
      Coins"' (the character the discard deletes lets go). Undo: the give is
      "changed since" (keys [COINS]: written 3, now 2) so not complete; the
      character goes, the cleanup pass deletes COINS: no item-in-use skip,
      COINS gone, the apprentice gone.
  run 5 (S2): create_item ORE, THEN create_location "Demo Mine" (room
      "Shaft"); the admin lays ORE there. The walk deletes the mine first,
      then ORE is held nowhere: preview plain line, undo complete, both gone.

Run 6 (S7, phase review) — a room the run ADDED to the pre-existing barn
(update_location with the stored rooms by id + name and a new "Loft"), then
create_item LAMP: (s7a) the admin lays LAMP in the Loft -> the barn's rooms no
longer equal what the run wrote, so the undo skips "rooms" (changed since,
keys ["rooms"]) and LAMP (item still in use); the preview line reads
'item <LAMP> "<name>" is still held by room <LOFT> "Loft" of location
loc_demo_barn — stays' (it used to read as going).
Run 7 (S8) — the admin sets the barn's knowledge_item_id to a created SCROLL:
preview 'item <SCROLL> "Demo Scroll" is still held by location loc_demo_barn
"Demo Barn" (its knowledge item) — stays'; undo not complete (item still in
use), SCROLL and the barn's reference stay.
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_items_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_items_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_items_inst_"))
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
from app.core.db import get_connection, transaction  # noqa: E402
from app.core.map_layout_apply import seed_boundary  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.inventory import (add_item, add_item_to_room, get_item,  # noqa: E402
                                  list_items, list_shared_items,
                                  update_inventory_entry)
from app.models.world import get_location_by_id, list_locations, upsert_location  # noqa: E402
from app.core.accessory_parts import is_part  # noqa: E402
from app.models.inventory import remove_from_inventory  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def norm(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


SMITH = "Demo Smith"
save_character_profile(SMITH, {"name": SMITH, "template": "human-roleplay"}, create_new=True)
SECRET = add_item(name="Demo Letter", category="document",
                  reveals_secret={"owner": "Demo Smith", "secret": "x"})["id"]
SMOCK = add_item(name="Demo Smock", category="outfit_piece",
                 outfit_piece={"slots": ["top"]})["id"]
ANVIL = add_item(name="Demo Anvil", category="tool")["id"]
BUCKET = add_item(name="Demo Bucket", category="tool")["id"]
BARN = "loc_demo_barn"
BARN_ROOM = "room_barn"
upsert_location({"id": BARN, "name": "Demo Barn", "pos_x": 200.0, "pos_z": 200.0,
                 "yaw_deg": 0.0, "map3d": {"boundary": seed_boundary()},
                 "rooms": [{"id": BARN_ROOM, "name": "Barn"}]}, sync_world=False)
PRE_BARN = norm(get_location_by_id(BARN))
check("fixture: barn room has no items key",
      all("items" not in r for r in PRE_BARN.get("rooms") or []), PRE_BARN)

run = wr.create_run("items", "m", "p", "u", 60, 600000)


def call(turn, tool, args, rid=None):
    return wt.run_tool(wt.ToolCtx(run_id=rid or run, turn=turn), tool, args)


def held(name=SMITH):
    return wu.inventory_entries(name)


def room_of(lid, rid):
    return next((r for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if r.get("id") == rid), None)


def room_entry(lid, rid, iid):
    return next((e for e in (room_of(lid, rid) or {}).get("items") or []
                 if e.get("item_id") == iid), None)


def last_row(rid=None):
    return wr.steps(rid or run)[-1]


def created_id(res):
    tok = [w for w in res.line.replace('"', " ").split() if w.startswith("item_")]
    return tok[0] if tok else ""


def refused(label, tool, args, *needles, turn=1, rid=None):
    n = len(wr.steps(rid or run))
    res = call(turn, tool, args, rid)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    rows = wr.steps(rid or run)
    check(f"{label}: one refused journal row",
          len(rows) == n + 1 and rows[-1]["kind"] == "refused", rows[-1])
    return res


print("(a) create_item")
res = call(1, "create_item", {"name": "Demo Hammer", "category": "tool"})
HAMMER = created_id(res)
check("(a) ok", res.ok and res.wrote, res)
check("(a) minted id shape", len(HAMMER) == len("item_") + 8, HAMMER)
check("(a) stored under that id", (get_item(HAMMER) or {}).get("name") == "Demo Hammer")
row = last_row()
check("(a) journal target", (row.get("target_kind"), row.get("target_id")) == ("item", HAMMER),
      row)
check("(a) journal inverse", (row.get("inverse") or {}) == {"op": "delete_items",
                                                           "ids": [HAMMER]}, row.get("inverse"))
res = refused("(a) duplicate name", "create_item", {"name": "demo hammer", "category": "tool"},
              HAMMER, "reuse it")
check("(a) a tool is no outfit piece", "outfit piece" not in res.line, res.line)
refused("(a) duplicate clothing name", "create_item", {"name": "demo smock", "category": "tool"},
        SMOCK, "an outfit piece {item_id}")
print("(a3) a part item's name is taken too")
CHARM = add_item(name="Demo Charm", category="outfit_piece",
                 outfit_piece={"slots": ["neck"], "jewellery": {"kind": "charm"}})["id"]
if is_part(get_item(CHARM)):
    refused("(a3) part item name", "create_item", {"name": "demo charm", "category": "tool"},
            CHARM, "part item", "another name")
else:
    print("  skip (a3): the catalog did not store a part item")

print("(a2) find_items")
res = call(1, "find_items", {"query": "demo hammer"})
check("(a2) one hammer line", res.ok and res.line.count("\n") == 0
      and res.line.startswith(f'{HAMMER} "Demo Hammer" tool'), res.line)
res = call(1, "find_items", {"slot": "top", "query": "demo smock"})
check("(a2) smock with its slot", res.ok and '"Demo Smock" outfit_piece [top]' in res.line,
      res.line)
shared = [s for s in list_shared_items() if s.get("id") and s.get("name")]
if shared:
    s0 = shared[0]
    res = call(1, "find_items", {"query": str(s0["id"])})
    line = next((l for l in res.line.splitlines() if l.startswith(str(s0["id"]) + " ")), "")
    check("(a2) shared item marked", "shared" in line, res.line)
refused("(a2) unknown key", "find_items", {"foo": 1}, "foo")

print("(b) create_item refusals")
n_items = len(list_items())
refused("(b) outfit_piece", "create_item", {"name": "Demo Shirt", "category": "outfit_piece"},
        "tool")
refused("(b) garment", "create_item", {"name": "Demo Wig", "category": "garment"},
        "tool")
res = call(1, "list_catalog", {"name": "item_categories"})
check("(b) catalog lists tool, not garment / outfit_piece",
      res.ok and "tool" in res.line.split() and "garment" not in res.line
      and "outfit_piece" not in res.line, res.line)
refused("(b) rarity", "create_item", {"name": "Demo Gem", "category": "tool",
                                      "rarity": "epic"}, "common")
refused("(b) stackable without max_stack", "create_item",
        {"name": "Demo Pegs", "category": "tool", "stackable": True}, "max_stack")
refused("(b) max_stack without stackable", "create_item",
        {"name": "Demo Pegs", "category": "tool", "max_stack": 5}, "stackable")
refused("(b) unknown key", "create_item", {"name": "Demo Pegs", "category": "tool",
                                           "weight": 3}, "weight")
check("(b) nothing stored", len(list_items()) == n_items, len(list_items()))

print("(c) give_items")
res = call(1, "give_items", {"character": SMITH, "items": [{"item_id": HAMMER, "quantity": 1}]})
check("(c) ok", res.ok and res.wrote, res)
entry_c = held().get(HAMMER) or {}
check("(c) quantity 1, manual", entry_c.get("quantity") == 1
      and entry_c.get("obtained_method") == "manual", entry_c)
row = last_row()
check("(c) journal target + inverse", (row.get("target_kind"), row.get("target_id"))
      == ("character", SMITH) and (row.get("inverse") or {}).get("op") == "restore_inventory"
      and wu.is_absent((row.get("inverse") or {}).get("before", {}).get(HAMMER)),
      row.get("inverse"))

print("(c2) non-stackable already held")
refused("(c2) again", "give_items", {"character": SMITH, "items": [{"item_id": HAMMER}]},
        "already holds it")
check("(c2) entry unchanged", held().get(HAMMER) == entry_c, held().get(HAMMER))

print("(c3) non-stackable quantity 2")
CHISEL = created_id(call(1, "create_item", {"name": "Demo Chisel", "category": "tool"}))
check("(c3) chisel created", bool(get_item(CHISEL)))
refused("(c3) quantity 2", "give_items",
        {"character": SMITH, "items": [{"item_id": CHISEL, "quantity": 2}]}, "not stackable")
check("(c3) not held", CHISEL not in held())

print("(c4) stack within max_stack")
NAILS = created_id(call(1, "create_item", {"name": "Demo Nails", "category": "consumable",
                                           "stackable": True, "max_stack": 10}))
check("(c4) nails created stackable 10", (get_item(NAILS) or {}).get("max_stack") == 10
      and (get_item(NAILS) or {}).get("stackable") is True, get_item(NAILS))
res = call(1, "give_items", {"character": SMITH, "items": [{"item_id": NAILS, "quantity": 6}]})
check("(c4) give 6 ok", res.ok and (held().get(NAILS) or {}).get("quantity") == 6, res)
refused("(c4) give 5", "give_items",
        {"character": SMITH, "items": [{"item_id": NAILS, "quantity": 5}]}, "max_stack 10")
check("(c4) still 6", (held().get(NAILS) or {}).get("quantity") == 6)
res = call(1, "give_items", {"character": SMITH, "items": [{"item_id": NAILS, "quantity": 4}]})
check("(c4) give 4 ok -> 10", res.ok and (held().get(NAILS) or {}).get("quantity") == 10, res)
check("(c4) R2 before is 6", (last_row().get("inverse") or {}).get("before") == {NAILS: 6},
      last_row().get("inverse"))
refused("(c4) same item twice", "give_items",
        {"character": SMITH, "items": [{"item_id": CHISEL}, {"item_id": CHISEL}]}, "twice")
refused("(c4) quantity 0", "give_items",
        {"character": SMITH, "items": [{"item_id": CHISEL, "quantity": 0}]}, "quantity")
refused("(c4) unknown character", "give_items",
        {"character": "Demo Nobody", "items": [{"item_id": CHISEL}]}, "Demo Nobody")
refused("(c4) unknown item", "give_items",
        {"character": SMITH, "items": [{"item_id": "item_nope"}]}, "item_nope")

print("(d) reveals_secret")
refused("(d) give secret", "give_items", {"character": SMITH, "items": [{"item_id": SECRET}]},
        "reveals a secret")

print("(e) room items refused in World Dev")
res = call(1, "create_location", {"data": {"name": "Demo Forge", "rooms": [{"name": "Forge"}]},
                                  "x": 0, "z": 0})
check("(e) forge created", res.ok, res)
FORGE = next((l["id"] for l in list_locations() if l.get("name") == "Demo Forge"), "")
FORGE_ROOM = next((r["id"] for r in (get_location_by_id(FORGE) or {}).get("rooms") or []
                   if r.get("name") == "Forge"), "")
check("(e) forge room", bool(FORGE and FORGE_ROOM))
refused("(e) add_room_item refused (secret)", "add_room_item",
        {"location_id": FORGE, "room_id": FORGE_ROOM, "item_id": SECRET},
        "items in rooms are invisible in the world")
refused("(e) add_room_item refused (hammer)", "add_room_item",
        {"location_id": FORGE, "room_id": FORGE_ROOM, "item_id": HAMMER, "quantity": 2},
        "items in rooms are invisible in the world")
check("(e) forge room has no items", "items" not in (room_of(FORGE, FORGE_ROOM) or {}),
      room_of(FORGE, FORGE_ROOM))

print("(e2) pre-existing place: layout ok, add_room_item refused")
res = call(1, "set_room_layout", {"location_id": BARN, "layout": {
    "rooms": [{"id": BARN_ROOM, "x": -4, "y": -4, "w": 8, "d": 8}]}})
check("(e2) layout ok", res.ok and res.wrote, res)
refused("(e2) add_room_item on barn refused", "add_room_item",
        {"location_id": BARN, "room_id": BARN_ROOM, "item_id": BUCKET},
        "items in rooms are invisible in the world")

print("(i) delete_created item")
RAG = created_id(call(1, "create_item", {"name": "Demo Rag", "category": "tool"}))
res = call(1, "delete_created", {"kind": "item", "id": RAG})
check("(i) same-turn delete ok", res.ok and get_item(RAG) is None, res)
RAG2 = created_id(call(1, "create_item", {"name": "Demo Rag2", "category": "tool"}))
refused("(i) earlier turn", "delete_created", {"kind": "item", "id": RAG2}, "earlier turn",
        turn=2)
check("(i) rag2 stays", get_item(RAG2) is not None)
refused("(i) held hammer", "delete_created", {"kind": "item", "id": HAMMER}, "still held")
BOOK = created_id(call(1, "create_item", {"name": "Demo Book", "category": "document"}))
res = call(1, "update_location", {"id": BARN, "patch": {"knowledge_item_id": BOOK}})
check("(i2) barn names the book", res.ok
      and (get_location_by_id(BARN) or {}).get("knowledge_item_id") == BOOK, res)
refused("(i2) knowledge item", "delete_created", {"kind": "item", "id": BOOK},
        "knowledge item", BARN)
check("(i2) book stays", get_item(BOOK) is not None)

print("discard_preview")
prev = wu.discard_preview(run)
for iid, name in ((HAMMER, "Demo Hammer"), (NAILS, "Demo Nails"), (CHISEL, "Demo Chisel"),
                  (RAG2, "Demo Rag2"), (BOOK, "Demo Book")):
    # Held only where the undo takes it back (Smith's gives, the created
    # forge, the barn's restore_room_items): the plain going line.
    check(f"preview names {name}", f'item {iid} "{name}"' in prev, prev)
check("preview names the forge", any(l.startswith(f'location {FORGE} "Demo Forge"')
                                     for l in prev), prev)
check("preview omits the deleted rag", not any('"Demo Rag"' in l for l in prev), prev)

print("(f) undo run 1")
rep = wu.undo(run)
check("(f) complete", rep["complete"], rep["skipped"])
check("(f) inventory empty", held() == {}, held())
for iid in (HAMMER, NAILS, CHISEL, RAG2, BOOK):
    check(f"(f) {iid} gone", get_item(iid) is None)
check("(f) fixtures stay", all(get_item(i) for i in (SECRET, SMOCK, ANVIL, BUCKET)))
check("(f) forge gone", get_location_by_id(FORGE) is None)
check("(f) barn row equals the pre-run row", norm(get_location_by_id(BARN)) == PRE_BARN,
      norm(get_location_by_id(BARN)))
check("(f) barn room has no items key", "items" not in (room_of(BARN, BARN_ROOM) or {"items": 1}),
      room_of(BARN, BARN_ROOM))
n_disc = get_connection().execute(
    "SELECT COUNT(*) FROM item_discoveries WHERE location_id=? AND room_id=?",
    (BARN, BARN_ROOM)).fetchone()[0]
check("(f) no discovery row left", n_disc == 0, n_disc)
wr.set_status(run, "accepted")

print("run 2: (g) foreign inventory edit, (h) foreign room change")
run2 = wr.create_run("items2", "m", "p", "u", 60, 600000)
TONGS = created_id(call(1, "create_item", {"name": "Demo Tongs", "category": "tool"}, run2))
res = call(1, "give_items", {"character": SMITH, "items": [{"item_id": TONGS}]}, run2)
check("(g) give ok", res.ok, res)
check("(g) admin edit", update_inventory_entry(SMITH, TONGS, {"notes": "x"}))
PLIERS = created_id(call(1, "create_item", {"name": "Demo Pliers", "category": "tool"}, run2))
check("(g) admin lays the pliers in the barn", add_item_to_room(BARN, BARN_ROOM, PLIERS))
prev = wu.discard_preview(run2)
check("(g) preview: tongs stay with Smith",
      f'item {TONGS} "Demo Tongs" is still held by character "{SMITH}" — stays' in prev, prev)
check("(g) preview: pliers stay in the barn",
      f'item {PLIERS} "Demo Pliers" is still held by room {BARN_ROOM} "Barn" of location '
      f'{BARN} — stays' in prev, prev)
res = call(1, "add_room_item", {"location_id": BARN, "room_id": BARN_ROOM, "item_id": BUCKET},
           run2)
check("(h) add_room_item refused",
      not res.ok and not res.wrote and "items in rooms are invisible in the world" in res.line,
      res)
check("(h) admin adds the anvil", add_item_to_room(BARN, BARN_ROOM, ANVIL))
rep = wu.undo(run2)
skips = rep["skipped"]
check("(g/h) not complete", rep["complete"] is False, rep)
check("(g) inventory changed since", any(s.get("reason") == wu.REASON_CHANGED
                                         and s.get("keys") == [TONGS] for s in skips), skips)
check("(g) tongs in use", any(s.get("reason") == wu.REASON_ITEM_IN_USE
                              and s.get("item") == TONGS for s in skips), skips)
check("(g) entry keeps notes x", (held().get(TONGS) or {}).get("notes") == "x", held())
check("(g) tongs stay in the catalog", get_item(TONGS) is not None)
check("(g) pliers in use, stay", get_item(PLIERS) is not None
      and any(s.get("reason") == wu.REASON_ITEM_IN_USE and s.get("item") == PLIERS
              for s in skips), skips)
ids = sorted(e.get("item_id") for e in (room_of(BARN, BARN_ROOM) or {}).get("items") or [])
check("(h) barn keeps anvil and pliers", ids == sorted([ANVIL, PLIERS]), ids)
wr.set_status(run2, "accepted")


print("run 3 (S1): place created BEFORE the item, admin lays the item there")
run3 = wr.create_run("items3", "m", "p", "u", 60, 600000)
res = call(1, "create_location", {"data": {"name": "Demo Smithy", "rooms": [{"name": "Shop"}]},
                                  "x": 40, "z": 0}, run3)
SMITHY = next((l["id"] for l in list_locations() if l.get("name") == "Demo Smithy"), "")
SMITHY_ROOM = next((r["id"] for r in (get_location_by_id(SMITHY) or {}).get("rooms") or []
                    if r.get("name") == "Shop"), "")
check("(s1) smithy created", res.ok and bool(SMITHY and SMITHY_ROOM), res)
INGOT = created_id(call(1, "create_item", {"name": "Demo Ingot", "category": "tool"}, run3))
check("(s1) admin lays the ingot in the smithy", add_item_to_room(SMITHY, SMITHY_ROOM, INGOT))
prev = wu.discard_preview(run3)
check("(s1) preview: plain going line", f'item {INGOT} "Demo Ingot"' in prev, prev)
rep = wu.undo(run3)
check("(s1) undo complete", rep["complete"], rep["skipped"])
check("(s1) no item-in-use skip", not any(s.get("reason") == wu.REASON_ITEM_IN_USE
                                          for s in rep["skipped"]), rep["skipped"])
check("(s1) ingot gone", get_item(INGOT) is None)
check("(s1) smithy gone", get_location_by_id(SMITHY) is None)
wr.set_status(run3, "accepted")

print("run 4 (S6): character created BEFORE the item, play takes one piece")
run4 = wr.create_run("items4", "m", "p", "u", 60, 600000)
APPR = "Demo Apprentice"
res = call(1, "create_character", {"data": {"name": APPR}}, run4)
check("(s6) apprentice created", res.ok, res)
COINS = created_id(call(1, "create_item", {"name": "Demo Coins", "category": "consumable",
                                           "stackable": True, "max_stack": 10}, run4))
res = call(1, "give_items", {"character": APPR, "items": [{"item_id": COINS, "quantity": 3}]},
           run4)
check("(s6) give 3 ok", res.ok, res)
check("(s6) play takes one", remove_from_inventory(APPR, COINS, quantity=1)
      and (held(APPR).get(COINS) or {}).get("quantity") == 2, held(APPR))
prev = wu.discard_preview(run4)
check("(s6) preview: plain going line", f'item {COINS} "Demo Coins"' in prev, prev)
rep = wu.undo(run4)
# The give is changed since (3 -> 2), so the undo is not complete; the
# character goes and the item with it — no item-in-use record.
check("(s6) give changed since", any(s.get("reason") == wu.REASON_CHANGED
                                     and s.get("keys") == [COINS] for s in rep["skipped"]),
      rep["skipped"])
check("(s6) no item-in-use skip", not any(s.get("reason") == wu.REASON_ITEM_IN_USE
                                          for s in rep["skipped"]), rep["skipped"])
check("(s6) coins gone", get_item(COINS) is None)
from app.models.character import character_row_exists  # noqa: E402
check("(s6) apprentice gone", not character_row_exists(APPR))
wr.set_status(run4, "accepted")

print("run 5 (S2): item created BEFORE the place, admin lays the item there")
run5 = wr.create_run("items5", "m", "p", "u", 60, 600000)
ORE = created_id(call(1, "create_item", {"name": "Demo Ore", "category": "tool"}, run5))
res = call(1, "create_location", {"data": {"name": "Demo Mine", "rooms": [{"name": "Shaft"}]},
                                  "x": -40, "z": 0}, run5)
MINE = next((l["id"] for l in list_locations() if l.get("name") == "Demo Mine"), "")
MINE_ROOM = next((r["id"] for r in (get_location_by_id(MINE) or {}).get("rooms") or []
                  if r.get("name") == "Shaft"), "")
check("(s2) mine created", res.ok and bool(MINE and MINE_ROOM), res)
check("(s2) admin lays the ore in the mine", add_item_to_room(MINE, MINE_ROOM, ORE))
prev = wu.discard_preview(run5)
check("(s2) preview: plain going line", f'item {ORE} "Demo Ore"' in prev, prev)
rep = wu.undo(run5)
check("(s2) undo complete", rep["complete"], rep["skipped"])
check("(s2) ore gone", get_item(ORE) is None)
check("(s2) mine gone", get_location_by_id(MINE) is None)
wr.set_status(run5, "accepted")

print("run 6 (S7): a room the run ADDED to a pre-existing place holds the item")
# The run adds room "Loft" to the pre-existing barn (update_location: its
# restore_location journals the barn's rooms before and as written), THEN
# creates LAMP. (s7a) the admin lays LAMP in the Loft (add_item_to_room, not
# journaled): the barn's rooms no longer equal what the run wrote, so
# _undo_restore_location skips "rooms" (changed since) and the Loft stays —
# and with it LAMP (item still in use). The preview must not count the Loft
# as removed: the LAMP line names the Loft as its holder and says it stays.
# (s7b) the same, but the RUN lays LAMP2 in the Loft (add_room_item, a newer
# restore_room_items row): the undo walks newest-first, takes LAMP2 out of the
# Loft first, so the rooms equal what update_location wrote again, the
# restore applies and the Loft goes — plain going line, undo complete.
def loft_of(loc):
    return next((r["id"] for r in (get_location_by_id(loc) or {}).get("rooms") or []
                 if r.get("name") == "Loft"), "")


run6 = wr.create_run("items6s7a", "m", "p", "u", 60, 600000)
# The stored rooms are sent by id and name (the tool merges each sent room
# onto its stored row, so the barn room keeps its items), plus the new one.
barn_rooms = [{"id": r["id"], "name": r.get("name") or r["id"]}
              for r in (get_location_by_id(BARN) or {}).get("rooms") or []
              if r.get("id") != "__ground__" and not r.get("is_floor")]
res = call(1, "update_location", {"id": BARN, "patch": {"rooms": barn_rooms + [{"name": "Loft"}]}},
           run6)
LOFT = loft_of(BARN)
check("(s7a) loft added to the barn", res.ok and bool(LOFT), res)
LAMP = created_id(call(1, "create_item", {"name": "Probe Lamp s7a",
                                          "category": "tool"}, run6))
check("(s7a) admin lays the lamp in the loft", add_item_to_room(BARN, LOFT, LAMP))
prev = wu.discard_preview(run6)
check("(s7a) preview: the lamp stays in the loft",
      f'item {LAMP} "Probe Lamp s7a" is still held by room {LOFT} "Loft" of location '
      f'{BARN} — stays' in prev, prev)
rep = wu.undo(run6)
skips = rep["skipped"]
check("(s7a) undo not complete", rep["complete"] is False, rep)
check("(s7a) rooms changed since", any(s.get("reason") == wu.REASON_CHANGED
                                       and s.get("keys") == ["rooms"] for s in skips),
      skips)
check("(s7a) lamp in use", any(s.get("reason") == wu.REASON_ITEM_IN_USE
                               and s.get("item") == LAMP for s in skips), skips)
check("(s7a) loft and lamp stay", loft_of(BARN) == LOFT and get_item(LAMP) is not None)
loc = copy.deepcopy(get_location_by_id(BARN))
loc["rooms"] = [r for r in loc["rooms"] if r.get("id") != LOFT]
from app.models.world import upsert_location  # noqa: E402
check("(s7a) cleanup", upsert_location(loc, sync_world=True) and not loft_of(BARN))
wr.set_status(run6, "accepted")

print("run 7 (S8): a place names the created item as its knowledge item")
# The run creates SCROLL; the admin sets the barn's knowledge_item_id to it
# (upsert_location, not journaled). The undo must not delete SCROLL (the barn
# would name a missing id): skip "item still in use"; the preview names the barn.
run7 = wr.create_run("items7", "m", "p", "u", 60, 600000)
SCROLL = created_id(call(1, "create_item", {"name": "Demo Scroll", "category": "document"},
                         run7))
from app.models.world import upsert_location  # noqa: E402
loc = copy.deepcopy(get_location_by_id(BARN))
loc["knowledge_item_id"] = SCROLL
check("(s8) admin sets the barn's knowledge item", upsert_location(loc, sync_world=True))
prev = wu.discard_preview(run7)
check("(s8) preview: the scroll stays with the barn",
      f'item {SCROLL} "Demo Scroll" is still held by location {BARN} "Demo Barn" '
      '(its knowledge item) — stays' in prev, prev)
rep = wu.undo(run7)
check("(s8) undo not complete, scroll in use",
      rep["complete"] is False and any(s.get("reason") == wu.REASON_ITEM_IN_USE
                                       and s.get("item") == SCROLL for s in rep["skipped"]),
      rep)
check("(s8) scroll stays, barn still names it",
      get_item(SCROLL) is not None
      and (get_location_by_id(BARN) or {}).get("knowledge_item_id") == SCROLL)
wr.set_status(run7, "accepted")

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nall ok")
