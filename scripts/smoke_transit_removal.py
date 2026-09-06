#!/usr/bin/env python3
"""Smoke run for the transit-place removal (plan-rueckbau-2d-karte.md, Paket 2).

Hand-derived expectations, on a throwaway world with four records:
  * "Inn"    — ordinary location, placed at (10, 20)          -> stays
  * "Lake"   — map3d.area_model=True, placed                  -> stays, is_area_location True
  * "Forest" — passable=True, no clone marker (a template)    -> DELETED (E5)
  * "f-1"    — template_location_id="<Forest id>", (30, 40)   -> DELETED (E5)
  The Forest gallery dir holds one file; it is removed with the record.
  migrate_transit_places_once() -> {"deleted_locations": 2,
  "deleted_galleries": 1, "fields_stripped": 0}; a second run -> all zeros.
  After it, list_locations() has exactly the two survivors and neither
  carries "passable" or "template_location_id".
  is_area_location: {"map3d": {"area_model": True}} -> True;
  {"passable": True} -> False (the flag means nothing any more);
  {} -> False.
  world_ops.build_worldmap_payload(avatar_name=None)["locations"]: no row
  carries a key "passable".
Runs against a THROWAWAY storage directory.

Usage: ./.venv/bin/python scripts/smoke_transit_removal.py
"""
import sys, tempfile
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
tmp = Path(tempfile.mkdtemp(prefix="smoke_transit_"))
from app.core import paths
paths.init(str(tmp))
from app.core import db
db.init_schema()
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + " " + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


from app.models.world import (add_location, _load_world_data, _save_world_data,
                              get_gallery_dir, list_locations,
                              migrate_transit_places_once)
from app.core.world_geometry import is_area_location

inn = add_location("Inn", "", rooms=[{"name": "Bar", "description": ""}])
lake = add_location("Lake", "", rooms=[{"name": "Water", "description": ""}])
forest = add_location("Forest", "", rooms=[{"name": "Path", "description": ""}])
data = _load_world_data()
for l in data["locations"]:
    if l["id"] == inn["id"]:
        l.update({"pos_x": 10.0, "pos_z": 20.0})
    if l["id"] == lake["id"]:
        l.update({"pos_x": 0.0, "pos_z": 0.0, "map3d": {"area_model": True}})
    if l["id"] == forest["id"]:
        l["passable"] = True
data["locations"].append({"id": "f1clone", "template_location_id": forest["id"],
                          "pos_x": 30.0, "pos_z": 40.0, "rooms": [], "name": ""})
_save_world_data(data)
gdir = get_gallery_dir(forest["id"])
gdir.mkdir(parents=True, exist_ok=True)
(gdir / "x.png").write_bytes(b"\x89PNG")

r1 = migrate_transit_places_once()
check("first run", r1, {"deleted_locations": 2, "deleted_galleries": 1, "fields_stripped": 0})
ids = sorted(l["id"] for l in list_locations())
check("survivors", ids, sorted([inn["id"], lake["id"]]))
check("forest gallery gone", gdir.exists(), False)
check("no legacy keys", [k for l in list_locations() for k in ("passable", "template_location_id") if k in l], [])
check("second run no-op", migrate_transit_places_once(),
      {"deleted_locations": 0, "deleted_galleries": 0, "fields_stripped": 0})
check("area via area_model", is_area_location({"map3d": {"area_model": True}}), True)
check("passable means nothing", is_area_location({"passable": True}), False)
check("plain location", is_area_location({}), False)

from app.core.world_ops import build_worldmap_payload
rows = build_worldmap_payload(avatar_name=None).get("locations", [])
check("worldmap rows carry no passable", [r for r in rows if "passable" in r], [])

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
