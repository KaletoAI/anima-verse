#!/usr/bin/env python3
"""Smoke: World Dev free mode — one scripted town run end to end: the
discard_preview lines and the exact undo of every phase-2 write tool together
(decision E15, the end-to-end discard contract).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 12.
A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_town.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixtures (all OUTSIDE the run, so the undo must leave them exactly as they are):
  * Character templates come from a temp copy of the shipped template
    directory plus ONE extra template "demo-stats" with one field {key
    "stamina", store "status_effects"} (``character_template.get_templates_dir``
    patched, as in smoke_world_dev_editor_fields) — the shipped templates hold
    no status_effects field, so ``stat_hints.get_all_stat_keys()`` == ["stamina"]
    (asserted once); "human-roleplay" stays available for create_character.
  * Props through ``props.create_prop``: "Demo Bed" (furniture), "Demo Well",
    "Demo Tree"; TREE_URL = "/assets/props/<Demo Tree id>/model" (the URL
    find_props prints, E10).
  * ``furniture_kits.solve_kit`` monkeypatched to place ONE Demo Bed at [1, 1]
    per room (as in smoke_world_dev_furnish); KIT = the first id of
    ``furniture_kits.load_kits()`` (which one is irrelevant, the solver is patched).
  * A place "Demo Mill" with room "Mill room" (``create_location_with_extras``,
    then one ``update_location_with_extras`` description write that canonicalises the
    row, as in smoke_world_dev_editor_fields).
  * A character "Demo Miller" (``save_character_profile``, template
    human-roleplay) holding the item "Demo Sack" (``inventory.add_item``, category
    "tool", given with ``add_to_inventory``).
  * PRE = the pre-run dump, read through the model readers and normalised as
    JSON: ``list_locations()``, ``terrain.list_areas()``,
    ``heightfield.list_height_areas()``, the WORLD terrain kinds (``terrain_types.sources()``
    == "world" -> ``get_type``), ``list_world_props()``, ``inventory.list_items()`` and
    Demo Miller's inventory entries (``world_dev_undo.inventory_entries``),
    Demo Miller's profile (``get_character_profile(strict=True)``) and his RAW
    config_json column — raw, because the config reader fills the defaults in
    (and its plain form even writes them back), so a write that materialises
    the defaults into a '{}' row would compare equal through it. The fixture
    row holds '{}' (save_character_profile writes no config). On top, a
    whole-DB row dump (``db_rows``): every row of every world.db table except
    the SQLite internals and the run's own world_dev_journal / world_dev_runs
    rows, ``updated_at`` columns dropped, so a stray write into ANY other
    table (character_state, rooms, ...) fails the smoke as well.
  * Technical timestamps (a row's updated_at) are NOT part of the exactness
    claim: the restore of Demo Mill re-writes its row with a new updated_at;
    every data column is compared.

Turn 1 (the order system.md "How you work" names: ground -> places -> floor
plans -> furnishing -> world props / scatter -> items -> characters -> NPC slots):
  t1  add_terrain_type {demo_cobble, "Demo Cobble", #8a8378}          -> ok
  t2  add_terrain_area {demo_cobble, square 0..40 x 0..40}  = A_COBBLE -> ok
  t3  add_terrain_area {grass, square 100..140 x 0..40, scatter [TREE_URL,
      density 2]}                                             = A_WOOD  -> ok
  t4  add_height_area {square 200..240 x 0..40, height_m 3}   = H       -> ok
  t5  create_location "Demo Tavern" at (20, -100), boundary +-10 m, rooms
      Taproom (room_type tavern)                              = TAV     -> ok
  t6  create_location "Demo Smithy" at (-60, -100), boundary +-10 m, room
      Forge (room_type workshop)                              = SMI     -> ok
  t7  set_room_layout TAV {Taproom x -8 y -6 w 8 d 6, new room "Loft" level 1
      x -8 y -6 w 5 d 6, stairs [{at [-7.4, -5.5], from_level 0, dir_deg 0}]}
      (the stair case of smoke_world_dev_layout (c))                     -> ok
  t8  set_room_layout SMI {Forge x -4 y -4 w 8 d 8}                      -> ok
  t9  furnish_rooms {SMI, KIT}  (Forge has room_type + layout)           -> ok
  t10 place_world_prop {Demo Well, x 60, z 60}                = WP      -> ok
  t11 create_item {"Demo Lantern", tool}                      = LANTERN -> ok
  t12 give_items {Demo Miller, [LANTERN x1]} (R1: a new entry)           -> ok
  t13 add_room_item {TAV, Taproom, LANTERN}                              -> refused ("items in rooms are invisible in the world")
  t14 create_character {character_name "Demo Keeper", template
      human-roleplay}                                                     -> ok
  t15 update_location TAV {npc_slots [{role "Demo Barkeeper", count_min 1,
      count_max 1}]}                                                      -> ok
  After turn 1 the preview holds lines 1-8 below PLUS, between line 2 and
  line 3, f"terrain area {A_WOOD} (grass)" (t3, not yet deleted) = 9 lines.
Turn 2:
  t16 delete_created {kind "terrain", id A_WOOD}  (the run's own area, earlier
      turn; delete_created names a terrain area kind "terrain")
  t17 update_location "Demo Mill" {stat_rates [{stamina, 2}]}

discard_preview (world_dev_undo.discard_preview: one line per element the run
created that still exists, OLDEST first; restore_location / restore_inventory
/ restore_room_items create nothing and add no line; nobody stands in a
created place except Demo Keeper, whom the discard deletes itself — no
"stands in" line). Expected, by hand:
  1. 'terrain kind demo_cobble "Demo Cobble"'                       (t1)
  2. f"terrain area {A_COBBLE} (demo_cobble)" — no "still used" suffix on
     line 1: the undo deletes A_COBBLE before the kind              (t2)
     — A_WOOD: created (t3) and deleted again (t16) = net absent, no line
  3. f"height area {H} (3.0 m)" — heightfield stores height_m as float (t4)
  4. f'location {TAV} "Demo Tavern"'                                 (t5)
  5. f'location {SMI} "Demo Smithy"'                                 (t6)
  6. f"world prop {WP} ({WELL})"                                     (t10)
  7. f'item {LANTERN} "Demo Lantern"' — no "still held by": Demo Miller's
     entry is taken back by t12's inverse, the Taproom entry goes with the
     created place                                                   (t11)
  8. 'character "Demo Keeper" — 0 chat messages, 0 memory rows of other
     characters name it' — no outfits sent, so no outfit-piece count (t14)
undo(run) -> complete True; then every table of PRE equals its pre-run dump
(Demo Miller's raw config_json still '{}' — the place deletion's reference
sweep, world.purge_location_references, reads known_locations strictly and
writes nothing for a character whose list names no deleted place)
(JSON-equal), Demo Keeper's row is gone, the terrain kind demo_cobble is no
world kind any more, and discard_preview is [].
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

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_town_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_town_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_town_inst_"))
TEMPLATES = Path(tempfile.mkdtemp(prefix="smoke_wd_town_tpl_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
for _d in (CLIPS, STORAGE, INSTANCE, TEMPLATES):
    atexit.register(shutil.rmtree, _d, ignore_errors=True)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.models import character_template  # noqa: E402

_SHIPPED_TEMPLATES = Path(character_template.get_templates_dir())
for _src in _SHIPPED_TEMPLATES.glob("*.json"):
    shutil.copy2(_src, TEMPLATES / _src.name)
(TEMPLATES / "demo-stats.json").write_text(json.dumps({
    "name": "demo-stats", "template_type": "character",
    "sections": [{"id": "stats", "fields": [
        {"key": "stamina", "label": "Stamina", "type": "number",
         "store": "status_effects"}]}]}), encoding="utf-8")
character_template.get_templates_dir = lambda: TEMPLATES  # type: ignore[assignment]
character_template.clear_template_cache()

from app.core import furniture_kits, props  # noqa: E402
from app.core import terrain_types as tt  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.stat_hints import get_all_stat_keys  # noqa: E402
from app.core.world_ops import (create_location_with_extras,  # noqa: E402
                                update_location_with_extras)
from app.models import heightfield, terrain  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  get_character_profile, save_character_profile)
from app.models.inventory import add_item, add_to_inventory, list_items  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402
from app.models.world_props import list_world_props  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def norm(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def sq(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


MILLER = "Demo Miller"


def dump():
    world_kinds = {k: tt.get_type(k) for k, src in sorted(tt.sources().items())
                   if src == "world"}
    return norm({
        "locations": sorted(list_locations(), key=lambda r: str(r.get("id"))),
        "terrain_areas": terrain.list_areas(),
        "height_areas": heightfield.list_height_areas(),
        "terrain_types": world_kinds,
        "world_props": list_world_props(),
        "items": sorted(list_items(), key=lambda r: str(r.get("id"))),
        "inventory": wu.inventory_entries(MILLER),
        "miller_profile": get_character_profile(MILLER, strict=True),
        "miller_config_raw": (db.get_connection().execute(
            "SELECT config_json FROM characters WHERE name=?", (MILLER,)
        ).fetchone() or [None])[0],
        "db_rows": db_rows(),
    })


# The run's own bookkeeping, which the undo keeps on purpose.
DB_ROWS_SKIP_TABLES = {"world_dev_journal", "world_dev_runs", "world_dev_media",
                       "world_dev_media_baseline"}
DB_ROWS_SKIP_COLUMNS = {"updated_at"}


def db_rows():
    """Every row of every table of world.db (SQLite internals, the run's
    journal / run rows and ``updated_at`` columns excluded), so a stray write
    into a table the readers above do not cover fails the smoke too."""
    conn = db.get_connection()
    out = {}
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        if table in DB_ROWS_SKIP_TABLES:
            continue
        cur = conn.execute(f'SELECT * FROM "{table}"')
        cols = [d[0] for d in cur.description]
        keep = [i for i, c in enumerate(cols) if c not in DB_ROWS_SKIP_COLUMNS]
        rows = [[(r[i].hex() if isinstance(r[i], bytes) else r[i]) for i in keep]
                for r in cur.fetchall()]
        out[table] = sorted(rows, key=lambda r: json.dumps(r, default=str))
    return out


# Fixtures
check("fixture: stat keys == ['stamina']", get_all_stat_keys() == ["stamina"],
      get_all_stat_keys())
BED = props.create_prop(name="Demo Bed", category="furniture")["id"]
WELL = props.create_prop(name="Demo Well")["id"]
TREE = props.create_prop(name="Demo Tree")["id"]
TREE_URL = f"/assets/props/{TREE}/model"
KIT = list(furniture_kits.load_kits())[0]


def fake_solve_kit(**_kw):
    return {"placed": [{"prop_id": BED, "at": [1, 1], "rot": 0}],
            "unplaced": [], "missing_roles": []}


furniture_kits.solve_kit = fake_solve_kit

MILL = create_location_with_extras({"name": "Demo Mill", "create_new": True,
                                    "rooms": [{"name": "Mill room"}]})["location"]["id"]
update_location_with_extras(MILL, {"description": "A demo mill."})
save_character_profile(MILLER, {"name": MILLER, "template": "human-roleplay"},
                       create_new=True)
SACK = add_item(name="Demo Sack", category="tool")["id"]
add_to_inventory(character_name=MILLER, item_id=SACK, obtained_method="manual")
PRE = dump()
check("fixture: the miller holds the sack", SACK in PRE["inventory"], PRE["inventory"])
check("fixture: the miller's raw config is '{}'", PRE["miller_config_raw"] == "{}",
      PRE["miller_config_raw"])
check("fixture: one place, no areas, no world kinds, no world props",
      (len(PRE["locations"]), PRE["terrain_areas"], PRE["height_areas"],
       PRE["terrain_types"], PRE["world_props"]) == (1, [], [], {}, []),
      PRE)

run = wr.create_run("town", "m", "p", "u", 60, 600000)


def call(turn, tool, args):
    res = wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)
    check(f"{tool} (turn {turn}) ok", res.ok and res.wrote, res)
    return res


def new_ids(reader, fn):
    known = {r["id"] for r in reader()}
    fn()
    return [r["id"] for r in reader() if r["id"] not in known]


def named(name):
    return next((l for l in list_locations() if l.get("name") == name), {})


def room_id(lid, name):
    return next((r.get("id") for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if r.get("name") == name), "")


# Turn 1
call(1, "add_terrain_type", {"kind": "demo_cobble", "name": "Demo Cobble",
                             "color": "#8a8378"})
A_COBBLE = (new_ids(terrain.list_areas, lambda: call(1, "add_terrain_area", {
    "kind": "demo_cobble", "polygon": sq(0, 0, 40, 40)})) or [""])[0]
A_WOOD = (new_ids(terrain.list_areas, lambda: call(1, "add_terrain_area", {
    "kind": "grass", "polygon": sq(100, 0, 140, 40), "label": "Demo Wood",
    "scatter": [{"model": TREE_URL, "density_per_100m2": 2}]})) or [""])[0]
check("t3 scatter stored", ((terrain.get_area(A_WOOD) or {}).get("meta") or {})
      .get("scatter") == [{"model": TREE_URL, "density_per_100m2": 2.0}],
      terrain.get_area(A_WOOD))
H = (new_ids(heightfield.list_height_areas, lambda: call(1, "add_height_area", {
    "polygon": sq(200, 0, 240, 40), "height_m": 3})) or [""])[0]
BOUNDARY = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
call(1, "create_location", {"data": {"name": "Demo Tavern", "rooms": [
    {"name": "Taproom", "room_type": "tavern"}]}, "x": 20, "z": -100,
    "boundary": BOUNDARY})
call(1, "create_location", {"data": {"name": "Demo Smithy", "rooms": [
    {"name": "Forge", "room_type": "workshop"}]}, "x": -60, "z": -100,
    "boundary": BOUNDARY})
TAV = named("Demo Tavern").get("id") or ""
SMI = named("Demo Smithy").get("id") or ""
TAP = room_id(TAV, "Taproom")
FORGE = room_id(SMI, "Forge")
call(1, "set_room_layout", {"location_id": TAV, "layout": {
    "rooms": [{"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6},
              {"name": "Loft", "description": "Under the roof.",
               "x": -8, "y": -6, "w": 5, "d": 6, "level": 1}],
    "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0}]}})
check("t7 the stair is stored", len(((get_location_by_id(TAV) or {}).get("map3d") or {})
                                    .get("stairs") or []) == 1, get_location_by_id(TAV))
call(1, "set_room_layout", {"location_id": SMI, "layout": {
    "rooms": [{"id": FORGE, "x": -4, "y": -4, "w": 8, "d": 8}]}})
call(1, "furnish_rooms", {"location_id": SMI, "kit": KIT})
WP = (new_ids(list_world_props, lambda: call(1, "place_world_prop", {
    "prop_id": WELL, "x": 60, "z": 60})) or [""])[0]
LANTERN = (new_ids(list_items, lambda: call(1, "create_item", {
    "name": "Demo Lantern", "category": "tool"})) or [""])[0]
call(1, "give_items", {"character": MILLER, "items": [{"item_id": LANTERN}]})
res_ari = wt.run_tool(wt.ToolCtx(run_id=run, turn=1), "add_room_item",
                      {"location_id": TAV, "room_id": TAP, "item_id": LANTERN})
check("add_room_item (turn 1) refused",
      not res_ari.ok and not res_ari.wrote
      and "items in rooms are invisible in the world" in res_ari.line, res_ari)
call(1, "create_character", {"data": {"character_name": "Demo Keeper",
                                      "template": "human-roleplay"}})
call(1, "update_location", {"id": TAV, "patch": {"npc_slots": [
    {"role": "Demo Barkeeper", "count_min": 1, "count_max": 1}]}})
check("turn 1 ids", all((A_COBBLE, A_WOOD, H, TAV, SMI, TAP, FORGE, WP, LANTERN)),
      (A_COBBLE, A_WOOD, H, TAV, SMI, TAP, FORGE, WP, LANTERN))

EXPECTED_T1 = [
    'terrain kind demo_cobble "Demo Cobble"',
    f"terrain area {A_COBBLE} (demo_cobble)",
    f"terrain area {A_WOOD} (grass)",
    f"height area {H} (3.0 m)",
    f'location {TAV} "Demo Tavern"',
    f'location {SMI} "Demo Smithy"',
    f"world prop {WP} ({WELL})",
    f'item {LANTERN} "Demo Lantern"',
    'character "Demo Keeper" — 0 chat messages, 0 memory rows of other '
    "characters name it",
]
prev1 = wu.discard_preview(run)
check("discard_preview after turn 1 == the hand-written list (9 lines)",
      prev1 == EXPECTED_T1,
      [(i, a, b) for i, (a, b) in enumerate(zip(prev1 + [None] * 10,
                                                EXPECTED_T1 + [None] * 10)) if a != b])

# Turn 2
call(2, "delete_created", {"kind": "terrain", "id": A_WOOD})
call(2, "update_location", {"id": MILL, "patch": {
    "stat_rates": [{"stat": "stamina", "per_hour": 2}]}})
check("t17 stat_rates stored", (get_location_by_id(MILL) or {}).get("stat_rates")
      == [{"stat": "stamina", "per_hour": 2}], get_location_by_id(MILL))

EXPECTED = [
    'terrain kind demo_cobble "Demo Cobble"',
    f"terrain area {A_COBBLE} (demo_cobble)",
    f"height area {H} (3.0 m)",
    f'location {TAV} "Demo Tavern"',
    f'location {SMI} "Demo Smithy"',
    f"world prop {WP} ({WELL})",
    f'item {LANTERN} "Demo Lantern"',
    'character "Demo Keeper" — 0 chat messages, 0 memory rows of other '
    "characters name it",
]
prev = wu.discard_preview(run)
check("discard_preview == the hand-written list", prev == EXPECTED,
      [(i, a, b) for i, (a, b) in enumerate(zip(prev + [None] * 9, EXPECTED + [None] * 9))
       if a != b])

rep = wu.undo(run)
check("undo complete", rep.get("complete") is True, rep)
POST = dump()
for table in PRE:
    if table == "db_rows":
        differing = sorted(t for t in set(PRE[table]) | set(POST[table])
                           if PRE[table].get(t) != POST[table].get(t))
        check(f"{table} equals the pre-run dump ({len(PRE[table])} tables)",
              not differing, differing)
        continue
    check(f"{table} equals the pre-run dump", POST[table] == PRE[table],
          (PRE[table], POST[table]))
check("Demo Keeper gone", not character_row_exists("Demo Keeper"))
check("demo_cobble is no world kind", tt.sources().get("demo_cobble") != "world",
      tt.sources().get("demo_cobble"))
check("discard_preview after the undo is empty", wu.discard_preview(run) == [],
      wu.discard_preview(run))

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("\nall ok")
