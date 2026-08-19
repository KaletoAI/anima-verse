#!/usr/bin/env python3
"""Smoke run for the map-layout export/import on METRES (Seamless World, E7 T1).

Runs against a THROWAWAY storage directory — never touches a real world.

The grid is gone, so the layout snapshot is metres too: a row is
``{id, name, pos_x, pos_z, yaw_deg}``. The manifest keeps its type
(``map_layout``) and its version (1) — the ROW format changed, and grid-era
ZIPs have no reader left, so they are refused with a clear message instead of
being half-applied. Import touches EXISTING ids only and never writes a
position by hand: it goes through ``update_location_position``, which is the
path that takes the occupants along.

Seed (hand-built, so every expectation below is derived from it and not
recorded from an implementation run):

    Inn   at (10, 20),  yaw 0,  map3d.plan_width_m 12  -> footprint +-6
    Farm  at (-40.5, 8.25), yaw 270
    Ghost unplaced (no pos_x/pos_z at all)
    demo_guest at world (14, 20) -> inside the Inn's footprint, so its
        current_location is the Inn; local offset (4, 0) from the centre

Hand-derived expectations:

  [1] Export shape. Manifest: version 1, type "map_layout", count 3 (every
      location, placed or not). Rows carry EXACTLY the five keys
      id/name/pos_x/pos_z/yaw_deg and no grid key at all. The Inn row reads
      pos_x 10.0, pos_z 20.0, yaw_deg 0.0; Ghost, never placed, reads
      pos_x None / pos_z None — "unplaced" is a null VALUE here, not a
      missing key (that distinction is what [4] rests on). Its yaw_deg is
      0.0 and not None: the column is ``REAL NOT NULL DEFAULT 0``
      (world_db_schema.py) and the loader reads it as ``float(... or 0.0)``,
      so no location ever has a null rotation. Placement is answered by
      pos_x/pos_z alone.

  [2] Metre round trip. Move the Inn to (100, 200) yaw 90 and the Farm to
      (0, 0) yaw 0 by hand, then import the ZIP from [1]: both are back at
      their seeded values, Inn (10.0, 20.0, 0.0) and Farm (-40.5, 8.25,
      270.0). Report: applied == ["Farm", "Ghost", "Inn"] — the row order,
      which is the export's order, which is the store's
      ``ORDER BY name ASC``. skipped_unknown == [].

  [3] Unknown ids are skipped, not invented. A hand-built ZIP with the Inn
      moved to (7, 7) yaw 180 plus a row for id "nope-404":
      applied == ["Inn"], skipped_unknown == [{"id": "nope-404",
      "name": "Nowhere"}], and the Inn really sits at (7.0, 7.0, 180.0)
      afterwards. Location count is unchanged (3) — nothing was created.

  [4] Grid-era ZIP refused. Rows of the old shape ({id, name, grid_x,
      grid_y}) raise ValueError, the message says "grid", and NOTHING is
      written: the Inn still sits at [3]'s (7.0, 7.0, 180.0). The test is
      the MISSING pos_x KEY, not a null value — [1] proves a null pos_x is
      the legitimate "unplaced" row.

  [5] Occupants come along, because the import re-places through
      ``update_location_position``. demo_guest sits at (14, 20), i.e. local
      (4, 0) in the Inn's frame (yaw 0: world_to_local(14,20,10,20,0) =
      (4, 0)).
      (a) Move the Inn by hand to (100, 200) yaw 90:
          local_to_world(4, 0, 100, 200, 90)
            = (100 + 4*cos90 + 0*sin90, 200 - 4*sin90 + 0*cos90)
            = (100.0, 196.0)                       [cos90 = 0, sin90 = 1]
      (b) Import the [1] ZIP -> the Inn returns to (10, 20) yaw 0:
          world_to_local(100, 196, 100, 200, 90) = (4, 0)   (back to local)
          local_to_world(4, 0, 10, 20, 0)        = (14.0, 20.0)
          The guest is at (14.0, 20.0) again — it rode the rotation there
          and back, which a direct position write would have skipped.

  [6] A null-position row UNPLACES. Import a ZIP whose Inn row has
      pos_x/pos_z None: the Inn has no pos_x/pos_z afterwards (yaw_deg falls
      back to the column default 0.0, see [1]), and the guest's point stays
      where it was (unplacing leaves occupants standing —
      ``_shift_location_occupants`` returns early). It is still one applied
      row, not a skip.

  [7] Both routes are admin-gated. ``/world/map/export`` and
      ``/world/map/import`` carry the same ``require_admin`` dependency as
      the location export route next to them — the layout writer used to be
      the one ungated map route.

  [8] ALL OR NOTHING on a junk coordinate. Every write persists on its own,
      so a bad row found halfway would leave half a layout behind. Seed the
      Inn at (5, 5) yaw 0 and import a THREE-row ZIP whose middle row is the
      Farm with ``pos_x: "abc"``: the first row (the Inn, at (60, 60)) must
      NOT have been written — the Inn still stands at (5.0, 5.0, 0.0), the
      Farm too is untouched. The ValueError names the offending row: it
      contains "row 1" (0-based index of the middle row) and the Farm's name.
      Same for the two other shapes of "not a finite number": a NaN literal
      (JSON accepts it, ``float`` produces nan, ``math.isfinite`` refuses it)
      and an over-large literal (1e999 -> inf).

  [9] Non-object rows are reported, not swallowed. A ZIP of
      ["nope", {Inn at (3, 4) yaw 90}, 42] applies the one real row and
      reports skipped_invalid == [{"index": 0, "type": "str"},
      {"index": 2, "type": "int"}] — the indices are positions in the FILE,
      so they point at the offending lines. The Inn really lands at
      (3.0, 4.0, 90.0).

Usage:  ./.venv/bin/python scripts/smoke_map_layout.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="map-layout-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="map-layout-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.content_io import (  # noqa: E402
    export_map_layout_to_zip, import_map_layout_from_zip)
from app.models.character import (  # noqa: E402
    get_character_pos, save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, get_location_by_id,
    list_locations, update_location_position)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def set_plan_width(location_id: str, width: float) -> None:
    """DRAW the location's boundary as the centred square of edge ``width``
    (contract v6) and store the width the sanitizer derives from its bounding
    box. Since 2026-08-19 the width alone is no shape: without a drawn outline
    a location has no area anywhere. The square's corners are the ones the
    deleted synthesis produced, so every hand-derived number stays put."""
    half = round(float(width) / 2.0, 2)
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            map3d["boundary"] = [[-half, -half], [half, -half],
                                 [half, half], [-half, half]]
            loc["map3d"] = map3d
    _save_world_data(data)


def place(location_id: str):
    """(pos_x, pos_z, yaw_deg) of a location as stored — None where unset."""
    loc = get_location_by_id(location_id) or {}
    return (loc.get("pos_x"), loc.get("pos_z"), loc.get("yaw_deg"))


def rows_of(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return json.loads(zf.read("db/map_layout.json"))


def manifest_of(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return json.loads(zf.read("manifest.json"))


def build_zip(rows) -> bytes:
    """A hand-written layout ZIP — the manifest stays type/version-correct so
    the tests below exercise the ROW check, not the manifest check."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("db/map_layout.json", json.dumps(rows, ensure_ascii=False))
        zf.writestr("manifest.json", json.dumps(
            {"version": 1, "type": "map_layout", "count": len(rows)}))
    return buf.getvalue()


def row_for(rows, loc_id):
    for r in rows:
        if r.get("id") == loc_id:
            return r
    return {}


# ── Seed ────────────────────────────────────────────────────────────────
INN = add_location(name="Inn", description="map layout smoke")["id"]
update_location_position(INN, 10.0, 20.0, 0.0)
set_plan_width(INN, 12.0)

FARM = add_location(name="Farm", description="map layout smoke")["id"]
update_location_position(FARM, -40.5, 8.25, 270.0)

GHOST = add_location(name="Ghost", description="map layout smoke")["id"]

save_character_profile("demo_guest", {"current_location": ""}, create_new=True)
set_character_pos("demo_guest", 14.0, 20.0)


print("\n[1] Export shape (metres, no grid keys)")
LAYOUT = export_map_layout_to_zip()
man = manifest_of(LAYOUT)
rows = rows_of(LAYOUT)
check("manifest version", man.get("version"), 1)
check("manifest type", man.get("type"), "map_layout")
check("manifest count", man.get("count"), 3)
check("row count", len(rows), 3)
check("row keys", sorted(rows[0].keys()),
      ["id", "name", "pos_x", "pos_z", "yaw_deg"])
check("inn row", {k: v for k, v in row_for(rows, INN).items() if k != "id"},
      {"name": "Inn", "pos_x": 10.0, "pos_z": 20.0, "yaw_deg": 0.0})
check("ghost row (unplaced = null, not missing)",
      {k: v for k, v in row_for(rows, GHOST).items() if k != "id"},
      {"name": "Ghost", "pos_x": None, "pos_z": None, "yaw_deg": 0.0})


print("\n[2] Metre round trip")
update_location_position(INN, 100.0, 200.0, 90.0)
update_location_position(FARM, 0.0, 0.0, 0.0)
check("inn moved away", place(INN), (100.0, 200.0, 90.0))
res = import_map_layout_from_zip(LAYOUT)
check("inn restored", place(INN), (10.0, 20.0, 0.0))
check("farm restored", place(FARM), (-40.5, 8.25, 270.0))
check("applied", res.get("applied"), ["Farm", "Ghost", "Inn"])
check("skipped_unknown", res.get("skipped_unknown"), [])


print("\n[3] Unknown ids are skipped, never invented")
res = import_map_layout_from_zip(build_zip([
    {"id": INN, "name": "Inn", "pos_x": 7.0, "pos_z": 7.0, "yaw_deg": 180.0},
    {"id": "nope-404", "name": "Nowhere",
     "pos_x": 1.0, "pos_z": 1.0, "yaw_deg": 0.0},
]))
check("applied", res.get("applied"), ["Inn"])
check("skipped_unknown", res.get("skipped_unknown"),
      [{"id": "nope-404", "name": "Nowhere"}])
check("inn applied", place(INN), (7.0, 7.0, 180.0))
check("no location created", len(list_locations()), 3)


print("\n[4] Grid-era rows are refused, nothing written")
err = ""
try:
    import_map_layout_from_zip(build_zip([
        {"id": INN, "name": "Inn", "grid_x": 3, "grid_y": 4},
        {"id": FARM, "name": "Farm", "grid_x": 4, "grid_y": 4},
    ]))
except ValueError as e:
    err = str(e)
check("raised ValueError", bool(err), True)
check("message names the grid", "grid" in err.lower(), True)
check("inn untouched", place(INN), (7.0, 7.0, 180.0))


print("\n[5] Occupants ride along (import goes through update_location_position)")
update_location_position(INN, 10.0, 20.0, 0.0)
set_character_pos("demo_guest", 14.0, 20.0)
check("guest seeded in the inn", get_character_pos("demo_guest"),
      {"x": 14.0, "z": 20.0})
update_location_position(INN, 100.0, 200.0, 90.0)
check("guest carried by the hand-move", get_character_pos("demo_guest"),
      {"x": 100.0, "z": 196.0})
import_map_layout_from_zip(LAYOUT)
check("inn back", place(INN), (10.0, 20.0, 0.0))
check("guest carried by the import", get_character_pos("demo_guest"),
      {"x": 14.0, "z": 20.0})


print("\n[6] A null-position row unplaces")
res = import_map_layout_from_zip(build_zip([
    {"id": INN, "name": "Inn", "pos_x": None, "pos_z": None, "yaw_deg": None},
]))
check("applied (an unplace is applied, not skipped)", res.get("applied"), ["Inn"])
check("inn unplaced", place(INN), (None, None, 0.0))
check("guest left standing", get_character_pos("demo_guest"),
      {"x": 14.0, "z": 20.0})


print("\n[7] Both routes are admin-gated")
from app.core.auth_dependency import require_admin  # noqa: E402
from app.routes import world as world_routes  # noqa: E402


def gated(path: str, method: str) -> bool:
    for r in world_routes.router.routes:
        if getattr(r, "path", "") == path and method in getattr(r, "methods", ()):
            return any(d.call is require_admin
                       for d in r.dependant.dependencies)
    return False


check("GET /map/export gated", gated("/world/map/export", "GET"), True)
check("POST /map/import gated", gated("/world/map/import", "POST"), True)
# Control: the location export next door is the gating this copies.
check("reference route gated",
      gated("/world/locations/{location_id}/export", "GET"), True)


print("\n[8] All or nothing: a junk coordinate applies NOTHING")
update_location_position(INN, 5.0, 5.0, 0.0)
update_location_position(FARM, -40.5, 8.25, 270.0)
for label, junk in (("string", "abc"),
                    ("NaN", float("nan")),
                    ("overflow", 1e999)):
    err = ""
    try:
        import_map_layout_from_zip(build_zip([
            {"id": INN, "name": "Inn", "pos_x": 60.0, "pos_z": 60.0, "yaw_deg": 0.0},
            {"id": FARM, "name": "Farm", "pos_x": junk, "pos_z": 1.0, "yaw_deg": 0.0},
            {"id": GHOST, "name": "Ghost", "pos_x": 1.0, "pos_z": 1.0, "yaw_deg": 0.0},
        ]))
    except ValueError as e:
        err = str(e)
    check(f"{label}: raised", bool(err), True)
    check(f"{label}: names the row", ("row 1" in err and "Farm" in err), True)
    check(f"{label}: earlier row NOT written", place(INN), (5.0, 5.0, 0.0))
    check(f"{label}: later row NOT written", place(FARM), (-40.5, 8.25, 270.0))


print("\n[9] Non-object rows are reported, not swallowed")
res = import_map_layout_from_zip(build_zip([
    "nope",
    {"id": INN, "name": "Inn", "pos_x": 3.0, "pos_z": 4.0, "yaw_deg": 90.0},
    42,
]))
check("applied", res.get("applied"), ["Inn"])
check("skipped_invalid", res.get("skipped_invalid"),
      [{"index": 0, "type": "str"}, {"index": 2, "type": "int"}])
check("skipped_invalid_count", res.get("skipped_invalid_count"), 2)
check("inn applied", place(INN), (3.0, 4.0, 90.0))


print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
shutil.rmtree(STORAGE, ignore_errors=True)
shutil.rmtree(CLIPS, ignore_errors=True)
sys.exit(1 if FAILURES else 0)
