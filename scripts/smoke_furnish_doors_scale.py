#!/usr/bin/env python3
"""Smoke: mirrored doors, clear ceiling height, area-scaled kits, and World Dev guards.

A temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp dirs,
paths.init BEFORE any world-DB import); no server, no LLM.

Usage:
    ./.venv/bin/python scripts/smoke_furnish_doors_scale.py

Hand derivations
----------------
(a) Mirrored door kept free:
  Room A: x=0, y=0, w=7, d=10. Door on east edge (edge 1: (7,0)->(7,10),
  length 10 m) at=0.3, width_m=0.9, type="door", to="room_b".
  World midpoint of door: (7.0, 0.3 * 10) = (7.0, 3.0).
  Room B: x=7, y=0, w=5, d=6. Own opening: north window (edge 0, at=0.5,
  width_m=1.2, sill_m=0.9, height_m=1.4).
  B's west edge (edge 3) runs (7,6)->(7,0), length 6 m. Projecting (7,3) onto
  edge 3 gives t = 3.0 -> at = 3.0 / 6.0 = 0.5, mirrored=True, to="room_a".
  In B-local metres (0..5 x 0..6): edge 3 is (0,6)->(0,0), door midpoint
  (0.0, 3.0), inward normal (+1, 0).
  Solver keep-out zone (fg.opening_zones, DOOR_CLEAR_M=0.6):
    half-width = (0.9 + 0.4) / 2 = 0.65 m -> z in [2.35, 3.65]
    depth = max(0.6, 0.9) = 0.9 m         -> x in [0.0, 0.9]
    height interval [0.0, 2.1] m.
  Every placed floor piece in B with height_m > 0.05 must have zero overlap
  with [(0, 2.35), (0.9, 2.35), (0.9, 3.65), (0, 3.65)].

(b) Ceiling light under clear ceiling:
  storey = 2.8 m -> scene_recipe.ceiling_height_m(2.8) = max(0.6, 2.8 - 0.15)
  = 2.65 m.
  Lamp height_m = 0.5 m -> base = max(1.9, 2.65 - 0.5) = 2.15 m,
  offset_y + height_m = 2.65 m, within [2.65 - 0.4, 2.65 + 0.03] = [2.25, 2.68].

(c) Living kit scaling (20 m^2 = 5x4 vs 70 m^2 = 10x7):
  resolve_count per template entry:
    dining_table {base:0, per_m2:0.02, max:2}:
      20 m^2 -> floor(0.4) = 0;   70 m^2 -> floor(1.4) = 1
    chair {per_ref:4, max:8} (ref dining_table):
      20 m^2 -> 4 * 0 = 0;        70 m^2 -> 4 * 1 = 4
    chest {base:0, per_m2:0.025, max:2}:
      20 m^2 -> floor(0.5) = 0;   70 m^2 -> floor(1.75) = 1
    cupboard {base:0, per_m2:0.02, max:2}:
      20 m^2 -> floor(0.4) = 0;   70 m^2 -> floor(1.4) = 1
    ceiling_light {base:1, per_m2:0.02, max:4}:
      20 m^2 -> 1 + floor(0.4) = 1; 70 m^2 -> 1 + floor(1.4) = 2
  Total floor pieces: 20 m^2 places 6 (sofa, coffee_table, rug, 2 armchairs,
  shelf); 70 m^2 places strictly more floor pieces (13) and 2 ceiling lights.

(d) World Dev guards:
  - set_room_layout with two overlapping level-0 rooms -> ToolRefusal, nothing written.
  - set_room_layout with bedroom 6x6 = 36 m^2 (> max_m2 25) -> succeeds with warning.
  - place_room_prop at (0.5, 3.0) in B (inside mirrored door zone x in [0, 0.9],
    z in [2.35, 3.65]) -> ToolRefusal, nothing written.
  - set_room_layout with a closed room without any door -> result contains
    "room_unreachable".
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

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_doors_scale_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_doors_scale_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_doors_scale_inst_"))
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

from app.core import furnish_geometry as fg  # noqa: E402
from app.core import furniture_kits as fk  # noqa: E402
from app.core import props  # noqa: E402
from app.core import room_furnish as rf  # noqa: E402
from app.core import scene_recipe as sr  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def demo_library(rows):
    return {
        role: {
            "name": role, "width_m": w, "depth_m": d, "height_m": h,
            "mount": "ceiling" if role == "ceiling_light" else "floor",
            "tags": ["kit:rustic", f"role:{role}"],
        }
        for role, w, d, h in rows
    }


# ── (a) Mirrored door kept free ──────────────────────────────────────────
print("[a] mirrored door in _geometry and solve_kit")
room_a = {
    "id": "room_a", "name": "Stube",
    "layout": {
        "x": 0.0, "y": 0.0, "w": 7.0, "d": 10.0, "level": 0,
        "openings": [
            {"edge": 1, "at": 0.3, "width_m": 0.9, "type": "door", "to": "room_b"},
        ],
    },
}
room_b = {
    "id": "room_b", "name": "Elternkammer",
    "layout": {
        "x": 7.0, "y": 0.0, "w": 5.0, "d": 6.0, "level": 0,
        "openings": [
            {"edge": 0, "at": 0.5, "width_m": 1.2, "height_m": 1.4,
             "sill_m": 0.9, "type": "window"},
        ],
    },
}
loc_ab = {"id": "loc_ab", "rooms": [room_a, room_b]}
geom_b = rf._geometry(loc_ab, room_b)
mirrored = [op for op in geom_b["openings"] if op.get("mirrored")]
check("(a) _geometry(loc, B) contains mirrored door",
      len(mirrored) == 1
      and mirrored[0].get("edge") == 3
      and abs(float(mirrored[0].get("at") or 0) - 0.5) < 1e-4
      and mirrored[0].get("to") == "room_a",
      geom_b["openings"])

bed_lib = demo_library([
    ("bed", 1.8, 2.0, 0.6),
    ("nightstand", 0.5, 0.4, 0.6),
    ("rug", 2.0, 1.5, 0.02),
    ("wardrobe", 1.2, 0.6, 2.0),
    ("chest", 0.9, 0.5, 0.6),
    ("desk", 1.2, 0.6, 0.75),
    ("chair", 0.5, 0.5, 0.9),
    ("ceiling_light", 0.4, 0.4, 0.5),
])
res_b = fk.solve_kit(
    kit="rustic", room_type="bedroom", geom=geom_b, library=bed_lib,
    room_id="room_b", existing=[], storey_height_m=2.8,
)
door_zone = [(0.0, 2.35), (0.9, 2.35), (0.9, 3.65), (0.0, 3.65)]
blocked = []
for p in res_b["placed"]:
    spec = bed_lib[p["prop_id"]]
    if spec["mount"] != "floor" or spec["height_m"] <= 0.05:
        continue
    corners = fg.rect_corners(p["at"][0], p["at"][1],
                              spec["width_m"], spec["depth_m"], p["yaw"])
    if fg.rects_overlap(corners, door_zone):
        blocked.append(p)
check("(a) no floor piece (>0.05 m) in mirrored door keep-out zone",
      not blocked and len(res_b["placed"]) >= 5, (blocked, len(res_b["placed"])))

# ── (b) Ceiling height ───────────────────────────────────────────────────
print("[b] ceiling light hangs under clear ceiling (storey 2.8 -> 2.65)")
check("(b) ceiling_height_m(2.8) == 2.65",
      abs(sr.ceiling_height_m(2.8) - 2.65) < 1e-9, sr.ceiling_height_m(2.8))
lamps = [p for p in res_b["placed"] if p["prop_id"] == "ceiling_light"]
check("(b) ceiling light placed", len(lamps) == 1, lamps)
if lamps:
    top_y = float(lamps[0].get("offset_y") or 0.0) + bed_lib["ceiling_light"]["height_m"]
    check("(b) lamp top in [2.25, 2.68]",
          2.65 - 0.4 <= top_y <= 2.65 + 0.03 and abs(top_y - 2.65) < 1e-6,
          (lamps[0], top_y))

# ── (c) Scaling living 70 m² vs 20 m² ────────────────────────────────────
print("[c] living kit scales with area (20 m² vs 70 m²)")
living_tpl = {e["role"]: e.get("count", 1) for e in fk.load_room_types()["living"]["template"]}
check("(c) 20 m² dining_table count == 0",
      fk.resolve_count(living_tpl["dining_table"], area_m2=20, ref_instances=0) == 0)
check("(c) 70 m² dining_table count == 1",
      fk.resolve_count(living_tpl["dining_table"], area_m2=70, ref_instances=0) == 1)
check("(c) 20 m² chair count == 0",
      fk.resolve_count(living_tpl["chair"], area_m2=20, ref_instances=0) == 0)
check("(c) 70 m² chair count == 4",
      fk.resolve_count(living_tpl["chair"], area_m2=70, ref_instances=1) == 4)
check("(c) 20 m² chest count == 0",
      fk.resolve_count(living_tpl["chest"], area_m2=20, ref_instances=0) == 0)
check("(c) 70 m² chest count == 1",
      fk.resolve_count(living_tpl["chest"], area_m2=70, ref_instances=0) == 1)
check("(c) 20 m² cupboard count == 0",
      fk.resolve_count(living_tpl["cupboard"], area_m2=20, ref_instances=0) == 0)
check("(c) 70 m² cupboard count == 1",
      fk.resolve_count(living_tpl["cupboard"], area_m2=70, ref_instances=0) == 1)
check("(c) 20 m² ceiling_light count == 1",
      fk.resolve_count(living_tpl["ceiling_light"], area_m2=20, ref_instances=0) == 1)
check("(c) 70 m² ceiling_light count == 2",
      fk.resolve_count(living_tpl["ceiling_light"], area_m2=70, ref_instances=0) == 2)

living_lib = demo_library([
    ("sofa", 2.0, 0.9, 0.85),
    ("coffee_table", 1.0, 0.6, 0.45),
    ("rug", 2.0, 1.5, 0.02),
    ("armchair", 0.75, 0.75, 0.9),
    ("shelf", 1.2, 0.4, 1.8),
    ("dining_table", 1.6, 0.9, 0.75),
    ("chair", 0.5, 0.5, 0.9),
    ("chest", 0.9, 0.5, 0.6),
    ("cupboard", 1.2, 0.5, 1.8),
    ("ceiling_light", 0.4, 0.4, 0.5),
])
geom_20 = {"outline_m": [[0, 0], [5, 0], [5, 4], [0, 4]],
           "openings": [{"edge": 2, "at": 0.5, "width_m": 0.9, "type": "door"}],
           "area_m2": 20.0, "w_m": 5.0, "d_m": 4.0}
geom_70 = {"outline_m": [[0, 0], [10, 0], [10, 7], [0, 7]],
           "openings": [{"edge": 2, "at": 0.5, "width_m": 0.9, "type": "door"}],
           "area_m2": 70.0, "w_m": 10.0, "d_m": 7.0}
sol_20 = fk.solve_kit(kit="rustic", room_type="living", geom=geom_20,
                      library=living_lib, room_id="l20", existing=[], storey_height_m=3.0)
sol_70 = fk.solve_kit(kit="rustic", room_type="living", geom=geom_70,
                      library=living_lib, room_id="l70", existing=[], storey_height_m=3.0)
floor_20 = [p for p in sol_20["placed"] if living_lib[p["prop_id"]]["mount"] == "floor"]
floor_70 = [p for p in sol_70["placed"] if living_lib[p["prop_id"]]["mount"] == "floor"]
ceil_70 = [p for p in sol_70["placed"] if living_lib[p["prop_id"]]["mount"] == "ceiling"]
check("(c) 70 m² places more floor pieces than 20 m²",
      len(floor_70) > len(floor_20) and len(floor_20) == 6,
      (len(floor_20), len(floor_70)))
check("(c) 70 m² places 2 distinct ceiling lights",
      len(ceil_70) == 2 and ceil_70[0]["at"] != ceil_70[1]["at"], ceil_70)

# ── (d) World Dev guards & findings ──────────────────────────────────────
print("[d] World Dev overlap refusal, max_m2 warning, mirrored door block, findings")
run = wr.create_run("doors_scale", "m", "p", "u", 60, 600000)


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


res = call("create_location", {
    "data": {"name": "Farmhouse", "rooms": [
        {"name": "Stube"}, {"name": "Elternkammer"}, {"name": "Isolated"}]},
    "x": 0, "z": 0, "boundary": [[-2, -2], [20, -2], [20, 20], [-2, 20]]})
check("(d) fixture location created", res.ok and res.wrote, res)
LID = next(l["id"] for l in list_locations() if l.get("name") == "Farmhouse")
rooms_by_name = {r["name"]: r["id"] for r in get_location_by_id(LID)["rooms"]}
STUBE = rooms_by_name["Stube"]
KAMMER = rooms_by_name["Elternkammer"]
ISOLATED = rooms_by_name["Isolated"]

# d1: overlapping rooms -> ToolRefusal, nothing written
before = copy.deepcopy(get_location_by_id(LID))
res = call("set_room_layout", {"location_id": LID, "layout": {"rooms": [
    {"id": STUBE, "x": 0, "y": 0, "w": 6, "d": 6, "level": 0},
    {"id": KAMMER, "x": 3, "y": 0, "w": 5, "d": 6, "level": 0},
]}}, turn=2)
check("(d1) overlapping rooms refused", not res.ok and not res.wrote, res)
check("(d1) refusal names both rooms", "Stube" in res.line and "Elternkammer" in res.line, res.line)
check("(d1) nothing written", get_location_by_id(LID) == before)

# d2: room over max_m2 -> warning (bedroom max_m2=25, 6x6=36 m²)
# Also place STUBE with door to KAMMER (edge 1 at 0.3, w 0.9) and outside door on edge 0,
# and ISOLATED with no doors -> triggers room_unreachable finding.
res = call("set_room_layout", {"location_id": LID, "layout": {
    "entry_room": STUBE,
    "rooms": [
        {"id": STUBE, "x": 0, "y": 0, "w": 7, "d": 10, "level": 0, "room_type": "living",
         "openings": [
             {"edge": 0, "at": 0.5, "width_m": 1.0, "type": "door", "to": "outside"},
             {"edge": 1, "at": 0.3, "width_m": 0.9, "type": "door", "to": KAMMER},
         ]},
        {"id": KAMMER, "x": 7, "y": 0, "w": 6, "d": 6, "level": 0, "room_type": "bedroom",
         "openings": [
             {"edge": 0, "at": 0.5, "width_m": 1.2, "height_m": 1.4,
              "sill_m": 0.9, "type": "window"},
         ]},
        {"id": ISOLATED, "x": 14, "y": 0, "w": 3, "d": 3, "level": 0},
    ],
}}, turn=3)
check("(d2) oversized bedroom succeeds with warning",
      res.ok and res.wrote and "36 m²" in res.line and "25 m²" in res.line, res.line)
check("(d4) room without door reports room_unreachable finding",
      "findings:" in res.line and "room_unreachable" in res.line and "Isolated" in res.line,
      res.line)

# d3: place_room_prop in front of mirrored door in KAMMER -> ToolRefusal
CHEST = props.create_prop(name="Oak Chest", category="furniture",
                          width_m=0.8, depth_m=0.5, height_m=0.7, mount="floor")["id"]
before = copy.deepcopy(get_location_by_id(LID))
res = call("place_room_prop", {
    "location_id": LID, "room_id": KAMMER, "prop_id": CHEST,
    "x": 0.5, "z": 3.0, "yaw": 0,
}, turn=4)
check("(d3) place_room_prop in mirrored door zone refused",
      not res.ok and not res.wrote and "door" in res.line, res)
check("(d3) location unchanged after refusal", get_location_by_id(LID) == before)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
