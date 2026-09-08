#!/usr/bin/env python3
"""Smoke check: a location pack from the FRACTION ERA is refused on import.

Runs against a THROWAWAY storage directory — never touches a real world.

Usage:
    ./.venv/bin/python scripts/smoke_content_location_fraction_era.py

Background (bug 2026-09-08, "Bernstein Academy"): before contract v6
(Meter-Welle, 2026-08-19) a room rectangle was stored as a SHARE 0…1 of
``map3d.plan_width_m``, and ``map3d.outline`` was a fraction polygon. Since
v6 everything is metres, ``plan_width_m`` is DERIVED from ``map3d.boundary``
and never stored without one. The importer runs an archive through the v6
sanitizers and does not migrate — so a fraction-era pack was read as METRES:
a 22.91 m academy arrived as rooms of 0.26 m × 0.25 m around the pin, with
no warning at all, because 0.26 is a perfectly valid metre. That must be a
refusal with a plain message, like the grid-era refusal of the map layout
import.

Seed — a fraction-era location dict, exactly the shape the real pack had:
    map3d = {"plan_width_m": 22.91, "floors": 2,
             "outline": [[0.278, 0.0262], [0.9706, 0.0238],
                         [0.9684, 0.6347], [0.278, 0.6347]]}     (no boundary)
    rooms  = Hall  layout x 0.625, y 0.3953, w 0.2596, d 0.2476, level 0
             Park  layout x 0.03,  y 0.5147, w 0.3732, d 0.4518, level 0
             __ground__ (no layout)

Expectations, derived by hand:
  [1] import_location_from_zip(fraction pack) raises ValueError whose message
      names the cause ("fraction") and the remedy ("export ... again"), and
      the world gains NO location (the refusal comes before the first write).
  [2] The METRE twin of the same pack — every room coordinate × 22.91, the
      outline turned into a ``boundary`` in metres, ``plan_width_m`` left in
      (the sanitizer recomputes it) — imports fine: 2 rooms with a layout,
      Hall w == round(0.2596 × 22.91, 2) == 5.95 and d == 5.67.
  [3] A metre pack WITHOUT any map3d and with an ordinary room
      (x 3, y -2, w 4, d 3) imports fine — no map3d is not "fraction era".
  [4] A metre pack with no boundary but one legitimately small room
      (x 0.5, y 0.5, w 0.8, d 0.6, a garden shed) imports fine as long as it
      does NOT carry a stored ``plan_width_m``: the shed alone is not proof.
  [5] A pack that stores ``plan_width_m`` and has NO boundary is refused even
      when its rooms happen to be larger than 1 (the value cannot come from a
      v6 save; the rooms are then fractions of an unknown scale or the
      pack was hand-edited — either way not importable without a re-export).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-fraction-clips-")
STORAGE = Path(tempfile.mkdtemp(prefix="content-fraction-storage-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)
from app.core import db  # noqa: E402

db.init_schema()

from app.core.content_io import import_location_from_zip  # noqa: E402
from app.models.world import GROUND_ROOM_ID, list_locations  # noqa: E402

FAILS = 0


def check(label: str, actual, expected) -> None:
    global FAILS
    ok = actual == expected
    print(f"  [{'OK' if ok else 'FAIL'}] {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILS += 1


def make_zip(loc: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "version": 1, "type": "location", "location_id": loc["id"],
            "location_name": loc["name"], "room_count": len(loc["rooms"]),
            "files": [],
        }))
        zf.writestr("db/location.json", json.dumps(loc))
    return buf.getvalue()


def room(rid: str, name: str, layout: dict | None) -> dict:
    r = {"id": rid, "name": name, "description": ""}
    if layout is not None:
        r["layout"] = layout
    return r


W = 22.91
FRACTION = {
    "id": "frac0001", "name": "Fraction Academy", "description": "",
    "entry_room": "hall0001",
    "map3d": {
        "plan_width_m": W, "floors": 2,
        "outline": [[0.278, 0.0262], [0.9706, 0.0238],
                    [0.9684, 0.6347], [0.278, 0.6347]],
    },
    "rooms": [
        room("hall0001", "Hall", {"x": 0.625, "y": 0.3953, "w": 0.2596,
                                  "d": 0.2476, "level": 0}),
        room("park0001", "Park", {"x": 0.03, "y": 0.5147, "w": 0.3732,
                                  "d": 0.4518, "level": 0}),
        room(GROUND_ROOM_ID, "", None),
    ],
}


def metre_twin(src: dict) -> dict:
    loc = json.loads(json.dumps(src))
    loc["id"] = "metr0001"
    loc["name"] = "Metre Academy"
    for r in loc["rooms"]:
        lay = r.get("layout")
        if lay:
            for k in ("x", "y", "w", "d"):
                lay[k] = round(lay[k] * W, 2)
    m3 = loc["map3d"]
    m3["boundary"] = [[round(u * W, 2), round(v * W, 2)] for u, v in m3.pop("outline")]
    return loc


def import_or_error(loc: dict):
    try:
        return import_location_from_zip(make_zip(loc)), None
    except ValueError as e:
        return None, str(e)


def layouts(result: dict) -> dict:
    for entry in list_locations():
        if entry.get("id") == result["location_id"]:
            return {r.get("name"): r.get("layout") for r in entry.get("rooms") or []}
    return {}


try:
    print("[1] fraction-era pack is refused before the first write")
    before = len(list_locations())
    res, err = import_or_error(FRACTION)
    check("import raised", res is None and err is not None, True)
    check("message names the cause", "fraction" in (err or "").lower(), True)
    check("message names the remedy", "export" in (err or "").lower()
          and "again" in (err or "").lower(), True)
    check("no location was written", len(list_locations()), before)

    print("[2] the metre twin imports")
    res, err = import_or_error(metre_twin(FRACTION))
    check("no error", err, None)
    lays = layouts(res) if res else {}
    check("Hall w", (lays.get("Hall") or {}).get("w"), 5.95)
    check("Hall d", (lays.get("Hall") or {}).get("d"), 5.67)
    check("Park kept", bool(lays.get("Park")), True)

    print("[3] a metre pack without map3d imports")
    plain = {
        "id": "plain001", "name": "Plain", "description": "",
        "rooms": [room("r1", "Room", {"x": 3, "y": -2, "w": 4, "d": 3}),
                  room(GROUND_ROOM_ID, "", None)],
    }
    res, err = import_or_error(plain)
    check("no error", err, None)
    check("room layout w", (layouts(res).get("Room") or {}).get("w") if res else None, 4.0)

    print("[4] a small metre room alone is no proof of the fraction era")
    shed = {
        "id": "shed0001", "name": "Shed", "description": "",
        "map3d": {"floors": 1},
        "rooms": [room("r1", "Shed", {"x": 0.5, "y": 0.5, "w": 0.8, "d": 0.6}),
                  room(GROUND_ROOM_ID, "", None)],
    }
    res, err = import_or_error(shed)
    check("no error", err, None)
    check("shed w", (layouts(res).get("Shed") or {}).get("w") if res else None, 0.8)

    print("[5] stored plan_width_m without a boundary is refused regardless of room size")
    stale = {
        "id": "stal0001", "name": "Stale", "description": "",
        "map3d": {"plan_width_m": 12.0, "floors": 1},
        "rooms": [room("r1", "Big", {"x": 2, "y": 2, "w": 5, "d": 4}),
                  room(GROUND_ROOM_ID, "", None)],
    }
    res, err = import_or_error(stale)
    check("import raised", res is None and err is not None, True)
finally:
    shutil.rmtree(STORAGE, ignore_errors=True)
    shutil.rmtree(os.environ["ANIMATION_CLIPS_DIR"], ignore_errors=True)

if FAILS:
    print(f"\n{FAILS} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
