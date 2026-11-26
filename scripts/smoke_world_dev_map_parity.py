#!/usr/bin/env python3
"""Smoke: World Dev free mode — map parity (E13): everything the `map` schema
can do is reachable through the free tools, and `delete_area` removes ANY area.

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 11.
ONE temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no
server, no LLM. Tool calls go through world_dev_tools.run_tool exactly as the agent loop
calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_map_parity.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The example is the json block under "## Structure of a map layout" of
shared/world_dev_schemas/map.md, read from the file at runtime (the plan names it as the
source). Its "loc_abc123" is replaced by the id of a fixture place "Demo Square" created
through world_ops.create_location_with_extras before anything else (an unknown id would be
dropped by the sanitizer). From that block, by hand:
  terrain_areas: "Eastern woods" forest, polygon [[120,-200],[400,-180],[420,150],[140,120]],
    z_order 0; "The river" water, stroke {points [[-20,-600],[10,-300],[-30,0],[5,320],
    [-10,600]], width_m 14, style wavy, spacing_m 40, amplitude_m 8}, z_order 1.
  height_areas: "Watch hill", polygon [[300,300],[380,300],[380,380],[300,380]],
    height_m 12, falloff_m 40.
  locations: Demo Square at (120, -40) yaw 0; the stub "The Old Mill", description "A water
    mill on the river bend, its wheel still turning.", indoor "indoor", danger_level 0,
    boundary [[-8,-6],[8,-6],[8,6],[-8,6]], pos (-10, 60), yaw 90.

Schema side: map_layout_apply.map_snapshot() of the world, then
sanitize_map_layout(example, <world_dev_apply._map_world_context()>) + apply_map_layout(merge,
snapshot) — the rows are read through the model readers (terrain.list_areas,
heightfield.list_height_areas, world.get_location_by_id), then restore_snapshot puts the
world back (no area, no height area, Demo Square unplaced, the mill deleted — asserted).

Free side, run R, turn 1: add_terrain_area{forest, label, polygon, z_order 0};
add_terrain_area{water, label, stroke (the five keys as in the block), z_order 1,
water {flow_along ""}} — the map schema's river is still water (it has no flow key) and a
free water stroke flows forward unless "" is sent (E11), so "" is the same request;
add_height_area{polygon, height_m 12, falloff_m 40, label}; place_location{Demo Square,
x 120, z -40, yaw 0}; create_location{data {name, description, indoor "indoor",
danger_level 0}, x -10, z 60, yaw 90, boundary}.

  (a) terrain rows: two each side; per label the same kind, polygon, z_order and the
      WHOLE meta — so meta.stroke (the stroke recipe) is identical as well. The plan allowed
      meta.source to differ; it does not: add_terrain_area runs the area through the same
      sanitize_map_layout, which marks it map_layout_apply.SOURCE ("world_dev") on both
      sides, so the check is the stricter one. ids differ (fresh per write).
  (b) height row: polygon, height_m 12.0, falloff_m 40.0 and the label equal on both sides
      and equal to the block's values.
  (c) the stub: name, description, indoor, danger_level, map3d.boundary, pos_x -10,
      pos_z 60, yaw_deg 90 equal on both sides (and equal to the block's values);
      Demo Square: pos_x 120, pos_z -40, yaw_deg 0 on both sides.

Fixtures written through the core AFTER the restore and BEFORE the run: terrain area
"ta_pre" (grass, square (900,900)-(910,910), label "Demo Field") and height area "ha_pre"
(square (950,950)-(960,960), height_m 3, falloff_m 5); their rows PRE_T / PRE_H are read
back right after.

  (d) turn 2: delete_area{kind terrain, id ta_pre} -> ok, the line names ta_pre, the area
      is gone; delete_area{kind height, id ha_pre} -> ok, gone. delete_area{kind terrain,
      id <forest of turn 1>} -> ok (an area this run created in an EARLIER turn is a
      cross-turn delete: same journal shape as delete_created), gone.
  (e) turn 2: add_terrain_area{grass, square (500,500)-(510,510)} -> E; delete_area{kind
      terrain, id E} -> refused, the line has "use delete_created", E still exists, one
      "refused" journal row. delete_area{kind "lake", ...} -> refused ("kind");
      delete_area{terrain, "ta_nosuch"} -> refused ("does not exist").
  (f) discard_preview(R): no line names ta_pre, ha_pre or the forest (re-created and
      deleted again by the discard: net absent, or re-created: not "going"); each of
      river, run height area, E and the mill is named by exactly one line.
  (g) undo(R) complete; then terrain.get_area("ta_pre") and the height row "ha_pre" are
      JSON-equal (sort_keys) to PRE_T / PRE_H — byte-equal re-creation; the run's areas,
      height area and the mill are gone; Demo Square is unplaced again (pos_x None).

Each later run closes the previous one first (one open run at a time).
  (h) pre-run fixtures, written in this order, z_order 0: ta_a forest square
      (2000,2000)-(2020,2020), ta_b grass (2010,2010)-(2030,2030); height areas ha_a / ha_b
      on the same squares (4 m / 6 m). list_areas sorts by z_order, created_at, rowid and
      the LAST containing area wins: (2015,2015) lies in both -> ta_b, "grass";
      (2005,2005) only in ta_a -> "forest". Run 2 deletes the OLDER ta_a and ha_a, undo:
      complete, ta_a JSON-equal, the id order ta_a, ta_b and ha_a, ha_b again,
      (2015,2015) "grass" again (re-inserting "now" would make it "forest"), the order
      identity {created_at, updated_at, rowid} of both equal, height_sig() unchanged.
  (i) run 3: turn 1 adds grass E3 (2100,2100)-(2110,2110); turn 2 update_terrain_area
      {ta_a, label "Demo Grove"} then delete_area ta_a. undo(turn=2): complete, ta_a equal
      to its row before the update, created_at + rowid restored (updated_at is the version
      token; the undo of the update stamps it anew, as any write), (2015,2015) "grass",
      E3 still there; undo of the rest removes E3.
  (j) run 4 deletes ta_b, somebody stores ta_b anew (forest): the preview has exactly one
      line, "... exists again"; the undo skips it (changed since, not complete), the
      foreign row stays.
  (k) run 5: turn 1 add_terrain_type demo_moss; somebody paints ta_f with it; turn 2
      delete_area ta_f. The undo re-creates ta_f before it reaches the kind, so the kind
      stays (changed since, in use): the preview has exactly the kind line, saying it is
      still used by terrain area ta_f and the discard leaves it; the undo agrees.
  (l) delete_area of an area with one NPC slot (label "Demo Meadow") says "1 NPC slot went
      with it"; an area created and removed with delete_created in the same turn is
      answered "does not exist" (not "use delete_created").
  (q)-(r) (phase review) the swap the old free-rowid rule missed: the delete journals the
      tie siblings on either side (tie_before / tie_after of the order identity) and the
      re-created area is checked against them on BOTH branches; derived by hand next to
      the blocks below, terrain and height.
  (m)-(p) areas sharing one created_at (terrain.save_areas_bulk stamps a batch once), the
      cases derived by hand next to each block below: deleting the middle one restores order
      and rowid; a foreign area taking the old rowid without sharing the stamp is still an
      exact order (no false "paint order"); a same-stamp sibling between the old and the new
      rowid is REASON_INEXACT, keys ["paint order"], announced by the preview; a pending
      recreate entry (complete crashed) is undone exactly.
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_parity_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_parity_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import map_layout_apply as mla  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.world_dev_apply import _map_world_context  # noqa: E402
from app.core.world_ops import create_location_with_extras  # noqa: E402
from app.models import heightfield, terrain  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def js(value):
    return json.dumps(value, sort_keys=True)


def sq(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


# ── the example ──────────────────────────────────────────────────────────
text = (ROOT / "shared/world_dev_schemas/map.md").read_text(encoding="utf-8")
section = text[text.index("## Structure of a map layout"):]
EXAMPLE = json.loads(re.search(r"```json\n(.*?)\n```", section, re.S).group(1))
check("example: 2 areas, 1 height, 2 places",
      (len(EXAMPLE["terrain_areas"]), len(EXAMPLE["height_areas"]),
       len(EXAMPLE["locations"])) == (2, 1, 2), EXAMPLE)

SQUARE = str(((create_location_with_extras(
    {"name": "Demo Square", "description": "A demo square.", "rooms": [],
     "create_new": True}) or {}).get("location") or {}).get("id") or "")
check("fixture: Demo Square exists", bool(SQUARE))
for entry in EXAMPLE["locations"]:
    if entry.get("id") == "loc_abc123":
        entry["id"] = SQUARE

WOODS, RIVER = EXAMPLE["terrain_areas"]
HILL = EXAMPLE["height_areas"][0]
MILL = next(e for e in EXAMPLE["locations"] if not e.get("id"))
check("example values as quoted in the docstring",
      WOODS["polygon"] == [[120, -200], [400, -180], [420, 150], [140, 120]]
      and WOODS["z_order"] == 0 and RIVER["z_order"] == 1
      and RIVER["stroke"]["width_m"] == 14 and HILL["height_m"] == 12
      and HILL["falloff_m"] == 40 and MILL["name"] == "The Old Mill"
      and (MILL["pos_x"], MILL["pos_z"], MILL["yaw_deg"]) == (-10, 60, 90),
      EXAMPLE)


def by_label(rows):
    return {str((r.get("meta") or {}).get("label") or r.get("label") or ""): r for r in rows}


def mill_row():
    return next((l for l in list_locations() if l.get("name") == "The Old Mill"), None)


# ── schema side ──────────────────────────────────────────────────────────
snap = mla.map_snapshot()
catalog, locs, bounds, default_kind = _map_world_context()
normalized, _warnings = mla.sanitize_map_layout(
    copy.deepcopy(EXAMPLE), catalog=catalog, locations_by_id=locs, bounds=bounds,
    default_kind=default_kind)
counts = mla.apply_map_layout(normalized, "merge", snap)
check("schema apply wrote 2 / 1 / 1 / 1", counts == {"areas": 2, "heights": 1,
                                                     "positions": 1, "created": 1}, counts)
S_AREAS = by_label(terrain.list_areas())
S_HEIGHTS = heightfield.list_height_areas()
S_MILL = copy.deepcopy(mill_row())
S_SQUARE = copy.deepcopy(get_location_by_id(SQUARE))
mla.restore_snapshot(snap)
check("restore: world empty again",
      not terrain.list_areas() and not heightfield.list_height_areas()
      and mill_row() is None and (get_location_by_id(SQUARE) or {}).get("pos_x") is None,
      (terrain.list_areas(), heightfield.list_height_areas()))

# ── free side, turn 1 ───────────────────────────────────────────────────
run = wr.create_run("parity", "m", "p", "u", 60, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


r = call(1, "add_terrain_area", {"kind": WOODS["kind"], "label": WOODS["label"],
                                 "polygon": WOODS["polygon"], "z_order": WOODS["z_order"]})
check("free: woods ok", r.ok, r.line)
r = call(1, "add_terrain_area", {"kind": RIVER["kind"], "label": RIVER["label"],
                                 "stroke": RIVER["stroke"], "z_order": RIVER["z_order"],
                                 "water": {"flow_along": ""}})
check("free: river ok", r.ok, r.line)
r = call(1, "add_height_area", {"polygon": HILL["polygon"], "height_m": HILL["height_m"],
                                "falloff_m": HILL["falloff_m"], "label": HILL["label"]})
check("free: hill ok", r.ok, r.line)
r = call(1, "place_location", {"id": SQUARE, "x": 120, "z": -40, "yaw": 0})
check("free: square placed", r.ok, r.line)
r = call(1, "create_location", {"data": {"name": MILL["name"],
                                         "description": MILL["description"],
                                         "indoor": MILL["indoor"],
                                         "danger_level": MILL["danger_level"]},
                                "x": MILL["pos_x"], "z": MILL["pos_z"],
                                "yaw": MILL["yaw_deg"], "boundary": MILL["boundary"]})
check("free: mill created", r.ok, r.line)
F_AREAS = by_label(terrain.list_areas())
F_HEIGHTS = heightfield.list_height_areas()
F_MILL = mill_row() or {}
F_SQUARE = get_location_by_id(SQUARE) or {}


# (a)
check("(a) two terrain rows each side", len(S_AREAS) == 2 and len(F_AREAS) == 2,
      (list(S_AREAS), list(F_AREAS)))
for label in (WOODS["label"], RIVER["label"]):
    s, f = S_AREAS.get(label) or {}, F_AREAS.get(label) or {}
    for key in ("kind", "polygon", "z_order"):
        check(f"(a) {label}: {key} equal", js(s.get(key)) == js(f.get(key)),
              (s.get(key), f.get(key)))
    check(f"(a) {label}: meta equal (incl. source {mla.SOURCE!r})",
          js(s.get("meta")) == js(f.get("meta"))
          and (f.get("meta") or {}).get("source") == mla.SOURCE,
          (s.get("meta"), f.get("meta")))
    check(f"(a) {label}: ids differ", s.get("id") != f.get("id"))
sm, fm = (S_AREAS.get(RIVER["label"]) or {}).get("meta") or {}, \
    (F_AREAS.get(RIVER["label"]) or {}).get("meta") or {}
check("(a) stroke recipe identical", bool(sm.get("stroke"))
      and js(sm.get("stroke")) == js(fm.get("stroke")), (sm.get("stroke"), fm.get("stroke")))
check("(a) woods polygon is the block's", (S_AREAS.get(WOODS["label"]) or {}).get("polygon")
      == [[120, -200], [400, -180], [420, 150], [140, 120]])

# (b)
check("(b) one height row each side", len(S_HEIGHTS) == 1 and len(F_HEIGHTS) == 1,
      (S_HEIGHTS, F_HEIGHTS))
sh, fh = (S_HEIGHTS or [{}])[0], (F_HEIGHTS or [{}])[0]
for key in ("polygon", "height_m", "falloff_m", "label"):
    check(f"(b) height {key} equal", js(sh.get(key)) == js(fh.get(key)),
          (sh.get(key), fh.get(key)))
check("(b) height values are the block's",
      sh.get("polygon") == [[300, 300], [380, 300], [380, 380], [300, 380]]
      and sh.get("height_m") == 12 and sh.get("falloff_m") == 40, sh)

# (c)
for key in ("name", "description", "indoor", "danger_level", "pos_x", "pos_z", "yaw_deg"):
    check(f"(c) mill {key} equal", js((S_MILL or {}).get(key)) == js(F_MILL.get(key)),
          ((S_MILL or {}).get(key), F_MILL.get(key)))
check("(c) mill boundary equal",
      js(((S_MILL or {}).get("map3d") or {}).get("boundary"))
      == js((F_MILL.get("map3d") or {}).get("boundary")),
      ((S_MILL or {}).get("map3d"), F_MILL.get("map3d")))
check("(c) mill values are the block's",
      (F_MILL.get("pos_x"), F_MILL.get("pos_z"), F_MILL.get("yaw_deg")) == (-10, 60, 90)
      and F_MILL.get("indoor") == "indoor"
      and (F_MILL.get("map3d") or {}).get("boundary") == [[-8, -6], [8, -6], [8, 6], [-8, 6]],
      F_MILL)
for key in ("pos_x", "pos_z", "yaw_deg"):
    check(f"(c) Demo Square {key} equal", (S_SQUARE or {}).get(key) == F_SQUARE.get(key),
          ((S_SQUARE or {}).get(key), F_SQUARE.get(key)))
check("(c) Demo Square at (120,-40) yaw 0",
      (F_SQUARE.get("pos_x"), F_SQUARE.get("pos_z"), F_SQUARE.get("yaw_deg")) == (120, -40, 0),
      F_SQUARE)

FOREST = (F_AREAS.get(WOODS["label"]) or {}).get("id")
RIVER_ID = (F_AREAS.get(RIVER["label"]) or {}).get("id")
HILL_ID = (F_HEIGHTS or [{}])[0].get("id")
MILL_ID = F_MILL.get("id")

# ── pre-run fixtures (written now: they did not exist when the run began, but
#    no entry of the run created them — for the tools they are foreign rows) ──
terrain.save_area({"id": "ta_pre", "kind": "grass", "polygon": sq(900, 900, 910, 910),
                   "meta": {"label": "Demo Field"}})
heightfield.save_height_area({"id": "ha_pre", "polygon": sq(950, 950, 960, 960),
                              "height_m": 3, "falloff_m": 5})
PRE_T = terrain.get_area("ta_pre")
PRE_H = next((h for h in heightfield.list_height_areas() if h.get("id") == "ha_pre"), None)
check("fixture: pre-run rows exist", bool(PRE_T) and bool(PRE_H), (PRE_T, PRE_H))


def height_ids():
    return {h.get("id") for h in heightfield.list_height_areas()}


# (d)
r = call(2, "delete_area", {"kind": "terrain", "id": "ta_pre"})
check("(d) pre-run terrain area deleted", r.ok and "ta_pre" in r.line
      and terrain.get_area("ta_pre") is None, r.line)
r = call(2, "delete_area", {"kind": "height", "id": "ha_pre"})
check("(d) pre-run height area deleted", r.ok and "ha_pre" not in height_ids(), r.line)
r = call(2, "delete_area", {"kind": "terrain", "id": FOREST})
check("(d) earlier-turn run area deleted", r.ok and terrain.get_area(FOREST) is None, r.line)

# (e)
known = {a["id"] for a in terrain.list_areas()}
r = call(2, "add_terrain_area", {"kind": "grass", "polygon": sq(500, 500, 510, 510)})
E = next((a["id"] for a in terrain.list_areas() if a["id"] not in known), "")
check("(e) area of this turn added", r.ok and bool(E), r.line)
def refused_rows():
    return sum(1 for e in wr.entries(run, writes_only=False) if e.get("kind") == "refused")


refused_before = refused_rows()
r = call(2, "delete_area", {"kind": "terrain", "id": E})
check("(e) same-turn creation refused", not r.ok and not r.wrote
      and "use delete_created" in r.line and terrain.get_area(E) is not None, r.line)
check("(e) one refused journal row",
      refused_rows() == refused_before + 1)
r = call(2, "delete_area", {"kind": "lake", "id": E})
check("(e) bad kind refused", not r.ok and "kind" in r.line, r.line)
r = call(2, "delete_area", {"kind": "terrain", "id": "ta_nosuch"})
check("(e) unknown area refused", not r.ok and "does not exist" in r.line, r.line)

# (f)
prev = wu.discard_preview(run)
check("(f) no line for the pre-run areas or the forest",
      not any(x in ln for ln in prev for x in ("ta_pre", "ha_pre", str(FOREST))), prev)
for ident in (RIVER_ID, HILL_ID, E, MILL_ID):
    check(f"(f) one line names {ident}",
          sum(1 for ln in prev if str(ident) in ln) == 1, prev)

# (g)
rep = wu.undo(run)
check("(g) undo complete", rep.get("complete"), rep)
check("(g) ta_pre re-created byte-equal", js(terrain.get_area("ta_pre")) == js(PRE_T),
      terrain.get_area("ta_pre"))
NOW_H = next((h for h in heightfield.list_height_areas() if h.get("id") == "ha_pre"), None)
check("(g) ha_pre re-created byte-equal", js(NOW_H) == js(PRE_H), NOW_H)
check("(g) the run's areas are gone",
      {a["id"] for a in terrain.list_areas()} == {"ta_pre"}, terrain.list_areas())
check("(g) the run's height area is gone", height_ids() == {"ha_pre"}, height_ids())
check("(g) the mill is gone", get_location_by_id(MILL_ID) is None)
check("(g) Demo Square unplaced again",
      (get_location_by_id(SQUARE) or {}).get("pos_x") is None, get_location_by_id(SQUARE))

# ── (h)-(l): the paint order, per-turn undo, foreign returns, kind uses ────
# Overlapping pre-run fixtures, written in this order (the second one is the
# newer in created_at and rowid), both z_order 0:
#   ta_a forest square (2000,2000)-(2020,2020), ta_b grass (2010,2010)-(2030,2030);
#   ha_a square (2000,2000)-(2020,2020) height 4, ha_b (2010,2010)-(2030,2030) height 6.
terrain.save_area({"id": "ta_a", "kind": "forest", "polygon": sq(2000, 2000, 2020, 2020)})
terrain.save_area({"id": "ta_b", "kind": "grass", "polygon": sq(2010, 2010, 2030, 2030)})
heightfield.save_height_area({"id": "ha_a", "polygon": sq(2000, 2000, 2020, 2020),
                              "height_m": 4, "falloff_m": 2})
heightfield.save_height_area({"id": "ha_b", "polygon": sq(2010, 2010, 2030, 2030),
                              "height_m": 6, "falloff_m": 2})
from app.core import terrain_query  # noqa: E402

PRE_A = terrain.get_area("ta_a")
ID_A = terrain.area_order_identity("ta_a")
ID_HA = heightfield.height_area_order_identity("ha_a")
SIG_H = heightfield.height_sig()


def fresh_run(prev, name):
    """Close the previous run (one open run at a time) and open the next."""
    wr.set_status(prev, "rolled_back")
    return wr.create_run(name, "m", "p", "u", 60, 300000)


def order(ids, rows):
    return [r["id"] for r in rows if r["id"] in ids]


# By hand: (2015,2015) lies in both squares; the LAST containing area in list order
# (z_order, created_at, rowid) wins -> ta_b, grass. (2005,2005) lies only in ta_a -> forest.
check("(h) before: order ta_a, ta_b; overlap is grass",
      order({"ta_a", "ta_b"}, terrain.list_areas()) == ["ta_a", "ta_b"]
      and terrain_query.kind_at(2015, 2015) == "grass"
      and terrain_query.kind_at(2005, 2005) == "forest")
check("(h) before: height order ha_a, ha_b",
      order({"ha_a", "ha_b"}, heightfield.list_height_areas()) == ["ha_a", "ha_b"])

run2 = fresh_run(run, "parity-order")
r = wt.run_tool(wt.ToolCtx(run_id=run2, turn=1), "delete_area", {"kind": "terrain", "id": "ta_a"})
check("(h) delete the OLDER terrain area", r.ok and terrain.get_area("ta_a") is None, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=run2, turn=1), "delete_area", {"kind": "height", "id": "ha_a"})
check("(h) delete the OLDER height area", r.ok and "ha_a" not in height_ids(), r.line)
rep = wu.undo(run2)
check("(h) undo complete", rep.get("complete"), rep)
check("(h) ta_a back JSON-equal", js(terrain.get_area("ta_a")) == js(PRE_A))
check("(h) terrain order ta_a, ta_b again",
      order({"ta_a", "ta_b"}, terrain.list_areas()) == ["ta_a", "ta_b"],
      order({"ta_a", "ta_b"}, terrain.list_areas()))
check("(h) overlap (2015,2015) is grass again", terrain_query.kind_at(2015, 2015) == "grass",
      terrain_query.kind_at(2015, 2015))
check("(h) ta_a order identity (created_at, updated_at, rowid) restored",
      terrain.area_order_identity("ta_a") == ID_A, (terrain.area_order_identity("ta_a"), ID_A))
check("(h) height order ha_a, ha_b again",
      order({"ha_a", "ha_b"}, heightfield.list_height_areas()) == ["ha_a", "ha_b"])
check("(h) ha_a order identity restored",
      heightfield.height_area_order_identity("ha_a") == ID_HA)
check("(h) height_sig unchanged", heightfield.height_sig() == SIG_H)

# (i) per-turn undo of update_terrain_area + delete_area on the same pre-run area;
#     turn 1's area E3 (grass, square (2100,2100)-(2110,2110)) stays.
run3 = fresh_run(run2, "parity-turn")
known = {a["id"] for a in terrain.list_areas()}
r = wt.run_tool(wt.ToolCtx(run_id=run3, turn=1), "add_terrain_area",
                {"kind": "grass", "polygon": sq(2100, 2100, 2110, 2110)})
E3 = next((a["id"] for a in terrain.list_areas() if a["id"] not in known), "")
check("(i) turn 1 area added", r.ok and bool(E3), r.line)
r = wt.run_tool(wt.ToolCtx(run_id=run3, turn=2), "update_terrain_area",
                {"id": "ta_a", "label": "Demo Grove"})
check("(i) turn 2 update of ta_a", r.ok, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=run3, turn=2), "delete_area", {"kind": "terrain", "id": "ta_a"})
check("(i) turn 2 delete of ta_a", r.ok and terrain.get_area("ta_a") is None, r.line)
rep = wu.undo(run3, turn=2)
check("(i) undo(turn=2) complete", rep.get("complete"), rep)
check("(i) ta_a back as before the update", js(terrain.get_area("ta_a")) == js(PRE_A),
      terrain.get_area("ta_a"))
# created_at + rowid are the place in the order; updated_at is the batch save's version
# token, which the undo of the UPDATE stamps anew (save_area must_exist), as any write does.
check("(i) ta_a paint order (created_at, rowid) restored",
      {k: (terrain.area_order_identity("ta_a") or {}).get(k) for k in ("created_at", "rowid")}
      == {k: ID_A[k] for k in ("created_at", "rowid")}, terrain.area_order_identity("ta_a"))
check("(i) overlap is grass", terrain_query.kind_at(2015, 2015) == "grass")
check("(i) turn 1's area stays", terrain.get_area(E3) is not None)
rep = wu.undo(run3)
check("(i) rest undone, E3 gone", rep.get("complete") and terrain.get_area(E3) is None, rep)

# (j) deleted by the run, exists again (somebody stored ta_b anew): the preview says so,
#     the undo leaves the foreign row alone (changed since, not complete).
run4 = fresh_run(run3, "parity-again")
r = wt.run_tool(wt.ToolCtx(run_id=run4, turn=1), "delete_area", {"kind": "terrain", "id": "ta_b"})
check("(j) ta_b deleted", r.ok, r.line)
terrain.save_area({"id": "ta_b", "kind": "forest", "polygon": sq(2010, 2010, 2030, 2030)})
prev = wu.discard_preview(run4)
check("(j) one 'exists again' line for ta_b",
      [ln for ln in prev if "ta_b" in ln] == [ln for ln in prev if "exists again" in ln]
      and len(prev) == 1 and "ta_b" in prev[0], prev)
rep = wu.undo(run4)
check("(j) undo not complete, skipped as changed since",
      not rep.get("complete") and len(rep.get("skipped") or []) == 1
      and rep["skipped"][0].get("reason") == wu.REASON_CHANGED, rep)
check("(j) the foreign ta_b stays", (terrain.get_area("ta_b") or {}).get("kind") == "forest")

# (k) a kind the run created, used by a FOREIGN area the run then deletes: the undo
#     re-creates the area first, so the kind stays in use — preview and undo agree.
run5 = fresh_run(run4, "parity-kind")
r = wt.run_tool(wt.ToolCtx(run_id=run5, turn=1), "add_terrain_type",
                {"kind": "demo_moss", "name": "Demo Moss", "color": "#557744"})
check("(k) kind created", r.ok, r.line)
terrain.save_area({"id": "ta_f", "kind": "demo_moss", "polygon": sq(2200, 2200, 2210, 2210)})
r = wt.run_tool(wt.ToolCtx(run_id=run5, turn=2), "delete_area", {"kind": "terrain", "id": "ta_f"})
check("(k) foreign ta_f deleted", r.ok and terrain.get_area("ta_f") is None, r.line)
prev = wu.discard_preview(run5)
kline = [ln for ln in prev if ln.startswith('terrain kind demo_moss "Demo Moss"')]
check("(k) preview: the kind stays, used by ta_f",
      len(prev) == 1 and len(kline) == 1 and "still used by terrain area ta_f" in kline[0]
      and "the discard leaves it" in kline[0], prev)
rep = wu.undo(run5)
check("(k) undo: ta_f back, the kind skipped (changed since, in use)",
      terrain.get_area("ta_f") is not None and not rep.get("complete")
      and len(rep.get("skipped") or []) == 1
      and rep["skipped"][0].get("reason") == wu.REASON_CHANGED, rep)
check("(k) the kind stays", wu.terrain_type_row("demo_moss") is not None)

# (l) the npc-slot hint: an area with one NPC slot names it in the result line.
terrain.save_area({"id": "ta_s", "kind": "grass", "polygon": sq(2300, 2300, 2310, 2310),
                   "meta": {"label": "Demo Meadow", "npc_slots": [{"role": "demo"}]}})
SLOTS = len((terrain.get_area("ta_s") or {}).get("meta", {}).get("npc_slots") or [])
run6 = fresh_run(run5, "parity-slots")
r = wt.run_tool(wt.ToolCtx(run_id=run6, turn=1), "delete_area", {"kind": "terrain", "id": "ta_s"})
check("(l) slot hint", r.ok and SLOTS == 1 and "1 NPC slot went with it" in r.line,
      (SLOTS, r.line))
known = {a["id"] for a in terrain.list_areas()}
r = wt.run_tool(wt.ToolCtx(run_id=run6, turn=1), "add_terrain_area",
                {"kind": "grass", "polygon": sq(2400, 2400, 2410, 2410)})
E6 = next((a["id"] for a in terrain.list_areas() if a["id"] not in known), "")
r = wt.run_tool(wt.ToolCtx(run_id=run6, turn=1), "delete_created", {"kind": "terrain", "id": E6})
check("(l) same-turn area removed with delete_created", r.ok and terrain.get_area(E6) is None,
      r.line)
r = wt.run_tool(wt.ToolCtx(run_id=run6, turn=1), "delete_area", {"kind": "terrain", "id": E6})
check("(l) a gone same-turn area is answered 'does not exist'",
      not r.ok and "does not exist" in r.line and "delete_created" not in r.line, r.line)
check("(l) undo complete", wu.undo(run6).get("complete"))

# ── (m)-(p): areas sharing ONE created_at (a batch save stamps them all "now") ──
# terrain.save_areas_bulk writes b1, b2, b3 in one transaction with one stamp, so only
# the rowid separates them in list order (z_order, created_at, rowid): b1 < b2 < b3,
# consecutive rowids, and b3 holds the largest rowid of the table (nothing is inserted
# after it). Squares (3000,3000)-(3020,3020) forest, (3005,3005)-(3025,3025) grass,
# (3010,3010)-(3030,3030) forest; (3015,3015) lies in all three -> the last, b3.
class Crash(BaseException):
    """Ends a tool call the way a dying process would: the row stays pending."""


def triple(x0, kinds):
    res = terrain.save_areas_bulk(
        [{"temp_id": f"t{i}", "kind": k, "polygon": sq(x0 + 5 * i, x0 + 5 * i,
                                                      x0 + 20 + 5 * i, x0 + 20 + 5 * i)}
         for i, k in enumerate(kinds)], [])
    ids = [s["area"]["id"] for s in sorted(res["saved"], key=lambda s: s["temp_id"])]
    return ids, {i: terrain.area_order_identity(i) for i in ids}


B, IDB = triple(3000, ["forest", "grass", "forest"])
check("(m) fixtures: one created_at, consecutive rowids",
      len({IDB[i]["created_at"] for i in B}) == 1
      and [IDB[i]["rowid"] for i in B] == [IDB[B[0]]["rowid"] + k for k in range(3)], IDB)
PRE_B2 = terrain.get_area(B[1])

# (m) delete the MIDDLE one: its rowid is free at undo time -> order and rowid back,
#     the preview has no line (nothing goes, nothing comes back out of place).
run7 = fresh_run(run6, "parity-tie-middle")
r = wt.run_tool(wt.ToolCtx(run_id=run7, turn=1), "delete_area", {"kind": "terrain", "id": B[1]})
check("(m) middle deleted", r.ok and terrain.get_area(B[1]) is None, r.line)
check("(m) preview empty", wu.discard_preview(run7) == [], wu.discard_preview(run7))
rep = wu.undo(run7)
check("(m) undo complete", rep.get("complete"), rep)
check("(m) b2 JSON-equal", js(terrain.get_area(B[1])) == js(PRE_B2))
check("(m) order b1, b2, b3 and identities restored",
      order(set(B), terrain.list_areas()) == B
      and all(terrain.area_order_identity(i) == IDB[i] for i in B),
      ([terrain.area_order_identity(i) for i in B], IDB))
check("(m) (3015,3015) is b3's forest", terrain_query.kind_at(3015, 3015) == "forest")

# (n) the reviewer's probe: delete b3 (the largest rowid); a foreign area fx is saved
#     and takes that rowid (sqlite: largest + 1), with a NEW created_at. b3 comes back
#     with rowid old + 1; the only area in [old, old + 1) is fx, which does not share
#     b3's stamp -> the relative order is unchanged: complete, order b1, b2, b3.
run8 = fresh_run(run7, "parity-tie-last")
r = wt.run_tool(wt.ToolCtx(run_id=run8, turn=1), "delete_area", {"kind": "terrain", "id": B[2]})
check("(n) b3 deleted", r.ok, r.line)
terrain.save_area({"id": "ta_fx", "kind": "grass", "polygon": sq(3100, 3100, 3110, 3110)})
check("(n) fx took b3's rowid",
      (terrain.area_order_identity("ta_fx") or {}).get("rowid") == IDB[B[2]]["rowid"])
check("(n) preview empty", wu.discard_preview(run8) == [], wu.discard_preview(run8))
rep = wu.undo(run8)
check("(n) undo complete (no false 'paint order')", rep.get("complete"), rep)
check("(n) b3 at rowid old + 1, order b1, b2, b3",
      (terrain.area_order_identity(B[2]) or {}).get("rowid") == IDB[B[2]]["rowid"] + 1
      and order(set(B), terrain.list_areas()) == B)

# (o) a real tie: fresh triple c1, c2, c3 (largest rowids again). The run deletes c2,
#     then c3; afterwards the largest rowid is c1's, so a foreign area fy takes c2's
#     old rowid. The undo walks newest-first: c3 first (its rowid is free -> exact),
#     then c2: its rowid is taken, it gets largest + 1 = c3's + 1, and c3 (same stamp)
#     lies in [c2 old, c2 new) -> the order is c1, c3, c2: REASON_INEXACT, keys
#     ["paint order"]; the content is exact. The preview says so in exactly one line.
C, IDC = triple(3200, ["forest", "grass", "forest"])
PRE_C2 = terrain.get_area(C[1])
run9 = fresh_run(run8, "parity-tie-taken")
for cid in (C[1], C[2]):
    r = wt.run_tool(wt.ToolCtx(run_id=run9, turn=1), "delete_area", {"kind": "terrain", "id": cid})
    check(f"(o) {cid} deleted", r.ok, r.line)
terrain.save_area({"id": "ta_fy", "kind": "grass", "polygon": sq(3300, 3300, 3310, 3310)})
check("(o) fy took c2's rowid",
      (terrain.area_order_identity("ta_fy") or {}).get("rowid") == IDC[C[1]]["rowid"])
prev = wu.discard_preview(run9)
check("(o) preview: one paint-order line for c2",
      len(prev) == 1 and C[1] in prev[0] and "paint order" in prev[0], prev)
rep = wu.undo(run9)
sk = rep.get("skipped") or []
check("(o) undo: one inexact skip, key 'paint order'",
      not rep.get("complete") and len(sk) == 1 and sk[0].get("reason") == wu.REASON_INEXACT
      and sk[0].get("keys") == ["paint order"], rep)
# c3's tie siblings now read c2 AFTER it (c2 came back behind it), so its identity is
# compared on the stamps and the rowid.
check("(o) c2 content exact, c3 exact stamps and rowid",
      js(terrain.get_area(C[1])) == js(PRE_C2)
      and {k: (terrain.area_order_identity(C[2]) or {}).get(k)
           for k in ("created_at", "updated_at", "rowid")}
      == {k: IDC[C[2]][k] for k in ("created_at", "updated_at", "rowid")})
check("(o) order is c1, c3, c2 (what the skip reports)",
      order(set(C), terrain.list_areas()) == [C[0], C[2], C[1]],
      order(set(C), terrain.list_areas()))

# (p) a pending recreate entry: complete crashes after the delete -> the row stays
#     pending with its inverse; the undo re-creates the area exactly (rowid free).
D, IDD = triple(3400, ["forest", "grass"])
PRE_D1 = terrain.get_area(D[1])
run10 = fresh_run(run9, "parity-pending")
_orig_complete = wr.complete


def _crash(*a, **k):
    raise Crash()


wr.complete = _crash
try:
    wt.run_tool(wt.ToolCtx(run_id=run10, turn=1), "delete_area", {"kind": "terrain", "id": D[1]})
    crashed = False
except Crash:
    crashed = True
finally:
    wr.complete = _orig_complete
pend = [s for s in wr.steps(run10) if s.get("tool") == "delete_area"]
check("(p) crash leaves one pending row, area gone",
      crashed and len(pend) == 1 and pend[0]["state"] == "pending"
      and terrain.get_area(D[1]) is None, pend)
check("(p) preview empty", wu.discard_preview(run10) == [], wu.discard_preview(run10))
rep = wu.undo(run10)
check("(p) undo complete, d2 back exactly",
      rep.get("complete") and js(terrain.get_area(D[1])) == js(PRE_D1)
      and terrain.area_order_identity(D[1]) == IDD[D[1]], rep)

# (q) the phase review's swap probe (finding "Task 11 major"): ONE save_areas_bulk batch
#     q1, q2 (z_order 1) and q3, q4 (z_order 0), so rowids r, r+1, r+2, r+3 (the largest of
#     the table) and one created_at; list order (z_order, created_at, rowid) q3, q4, q1, q2.
#     The run deletes q2, q3, q1, q4 (in that order). Journalled tie siblings (same
#     created_at AND z_order, terrain.area_order_identity): q2 before [q1] after [];
#     q3 before [] after [q4]; q1 (q2 already gone) before [] after []; q4 (q3 gone) none.
#     A foreign save_area fq then takes rowid r (largest left is below r). The undo walks
#     newest-first: q4 -> r+3 free, no sibling present -> exact. q1 -> r taken by fq, gets
#     largest + 1 = r+4; no sibling present (q2 still gone) -> exact. q3 -> r+2 free, q4
#     (journalled after) at r+3 > r+2 -> exact. q2 -> r+1 free, but q1 (journalled BEFORE)
#     now sits at r+4 > r+1 -> the order of q1, q2 is swapped: REASON_INEXACT, keys
#     ["paint order"], exactly one skip; the preview says so in exactly one line, naming q2.
#     The old rule (free rowid = exact) reported complete with an empty preview.
#     Final rowids q2 r+1, q3 r+2, q4 r+3, q1 r+4; list order q3, q4, q2, q1.
def quad(x0):
    res = terrain.save_areas_bulk(
        [{"temp_id": f"t{i}", "kind": "grass", "z_order": z,
          "polygon": sq(x0 + 5 * i, x0 + 5 * i, x0 + 20 + 5 * i, x0 + 20 + 5 * i)}
         for i, z in enumerate((1, 1, 0, 0))], [])
    ids = [s["area"]["id"] for s in sorted(res["saved"], key=lambda s: s["temp_id"])]
    return ids, {i: terrain.area_order_identity(i) for i in ids}


Q, IDQ = quad(3600)
RQ = IDQ[Q[0]]["rowid"]
check("(q) fixtures: rowids r..r+3, one created_at, order q3, q4, q1, q2",
      [IDQ[i]["rowid"] for i in Q] == [RQ, RQ + 1, RQ + 2, RQ + 3]
      and len({IDQ[i]["created_at"] for i in Q}) == 1
      and order(set(Q), terrain.list_areas()) == [Q[2], Q[3], Q[0], Q[1]], IDQ)
check("(q) journalled tie siblings",
      (IDQ[Q[1]]["tie_before"], IDQ[Q[1]]["tie_after"]) == ([Q[0]], [])
      and (IDQ[Q[2]]["tie_before"], IDQ[Q[2]]["tie_after"]) == ([], [Q[3]]), IDQ)
PRE_Q = {i: terrain.get_area(i) for i in Q}
run11 = fresh_run(run10, "parity-tie-swap")
for qid in (Q[1], Q[2], Q[0], Q[3]):
    r = wt.run_tool(wt.ToolCtx(run_id=run11, turn=1), "delete_area", {"kind": "terrain", "id": qid})
    check(f"(q) {qid} deleted", r.ok, r.line)
terrain.save_area({"id": "ta_fq", "kind": "grass", "polygon": sq(3700, 3700, 3710, 3710)})
check("(q) fq took q1's rowid r", (terrain.area_order_identity("ta_fq") or {}).get("rowid") == RQ)
prev = wu.discard_preview(run11)
check("(q) preview: one paint-order line, for q2",
      len(prev) == 1 and Q[1] in prev[0] and "paint order" in prev[0], prev)
rep = wu.undo(run11)
sk = rep.get("skipped") or []
check("(q) undo: one inexact skip, key 'paint order'",
      not rep.get("complete") and len(sk) == 1 and sk[0].get("reason") == wu.REASON_INEXACT
      and sk[0].get("keys") == ["paint order"], rep)
check("(q) rowids q1 r+4, q2 r+1, q3 r+2, q4 r+3",
      [(terrain.area_order_identity(i) or {}).get("rowid") for i in Q]
      == [RQ + 4, RQ + 1, RQ + 2, RQ + 3],
      [terrain.area_order_identity(i) for i in Q])
check("(q) contents exact", all(js(terrain.get_area(i)) == js(PRE_Q[i]) for i in Q))
check("(q) order is q3, q4, q2, q1 (what the skip reports)",
      order(set(Q), terrain.list_areas()) == [Q[2], Q[3], Q[1], Q[0]],
      order(set(Q), terrain.list_areas()))

# (r) the height twin (height areas sort by created_at, rowid — no z_order): batch 1
#     h1, h2 (rowids r, r+1, one stamp), batch 2 h3, h4 (r+2, r+3, a LATER stamp) — they
#     play q3 / q4's part. The run deletes h2, h3, h1, h4; journalled: h2 before [h1],
#     h3 after [h4]. A foreign height area fh takes r. Undo: h4 r+3 exact; h1 r taken ->
#     r+4, no sibling present -> exact; h3 r+2, h4 after at r+3 -> exact; h2 r+1, h1
#     (before) at r+4 -> swapped: one inexact skip "paint order", one preview line (h2).
def hpair(x0):
    res = heightfield.save_height_areas_bulk(
        [{"temp_id": f"t{i}", "polygon": sq(x0 + 5 * i, x0 + 5 * i, x0 + 10 + 5 * i,
                                            x0 + 10 + 5 * i),
          "height_m": 2 + i, "falloff_m": 1} for i in range(2)], [])
    return [s["area"]["id"] for s in sorted(res["saved"], key=lambda s: s["temp_id"])]


HQ = hpair(3800) + hpair(3900)
IDH = {i: heightfield.height_area_order_identity(i) for i in HQ}
RH = IDH[HQ[0]]["rowid"]
check("(r) fixtures: rowids r..r+3, two stamps",
      [IDH[i]["rowid"] for i in HQ] == [RH, RH + 1, RH + 2, RH + 3]
      and IDH[HQ[0]]["created_at"] == IDH[HQ[1]]["created_at"]
      and IDH[HQ[2]]["created_at"] == IDH[HQ[3]]["created_at"]
      and IDH[HQ[0]]["created_at"] < IDH[HQ[2]]["created_at"], IDH)
check("(r) journalled tie siblings",
      (IDH[HQ[1]]["tie_before"], IDH[HQ[2]]["tie_after"]) == ([HQ[0]], [HQ[3]]), IDH)
run12 = fresh_run(run11, "parity-tie-swap-height")
for hid in (HQ[1], HQ[2], HQ[0], HQ[3]):
    r = wt.run_tool(wt.ToolCtx(run_id=run12, turn=1), "delete_area", {"kind": "height", "id": hid})
    check(f"(r) {hid} deleted", r.ok, r.line)
heightfield.save_height_area({"id": "ha_fh", "polygon": sq(3990, 3990, 3995, 3995),
                              "height_m": 1, "falloff_m": 1})
check("(r) fh took h1's rowid r",
      (heightfield.height_area_order_identity("ha_fh") or {}).get("rowid") == RH)
prev = wu.discard_preview(run12)
check("(r) preview: one paint-order line, for h2",
      len(prev) == 1 and HQ[1] in prev[0] and "paint order" in prev[0], prev)
rep = wu.undo(run12)
sk = rep.get("skipped") or []
check("(r) undo: one inexact skip, key 'paint order'",
      not rep.get("complete") and len(sk) == 1 and sk[0].get("reason") == wu.REASON_INEXACT
      and sk[0].get("keys") == ["paint order"], rep)
check("(r) rowids h1 r+4, h2 r+1, h3 r+2, h4 r+3",
      [(heightfield.height_area_order_identity(i) or {}).get("rowid") for i in HQ]
      == [RH + 4, RH + 1, RH + 2, RH + 3])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
