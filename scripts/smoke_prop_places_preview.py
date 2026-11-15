#!/usr/bin/env python3
"""Smoke: the Library place preview reads a prop's places A…X from the
draft scene preview (``POST /play/scene-preview``) — no route of its own.

Ruling A110 phase 0 (spec docs/superpowers/specs/2026-11-16-poses-tab-
redesign-design.md § 2.2 item 2). The admin sends a one-room draft that holds
ONLY the prop at the room origin; the composer answers with the same
``markers[].slots`` / ``facing`` / ``y_world`` / ``root_offset`` the game's
scene payload carries for that prop. Nothing geometric is derived in the
admin.

Usage:
    ./.venv/bin/python scripts/smoke_prop_places_preview.py

Runs WITHOUT the server against a throwaway storage dir.

Hand case: a bench, bbox 1.8 x 0.5 x 0.5 mesh units, dims 1.8 x 0.5 x 0.5 m,
no orientation fix, placement at the room origin with yaw 0.

    scale        = max(dims) / max(bbox) = 1.8 / 1.8           = 1.0
    marker m1    at frac [0.5, 1.0, 0.5] = the box centre on the top face
                 offset (0, 0); height 1.0 x 0.5 x 1.0          = 0.5 m
                 y_world = floor 0 + clearance 0.01 + 0.5       = 0.51
                 capacity 3, spacing 0.6, facing 0, row at 0+90 = east:
                 unit (sin 90, cos 90) = (1, 0)
                 slots = (i - 1) x 0.6 along x -> [-0.6,0] [0,0] [0.6,0]
    marker m2    at frac [1.0, 1.0, 0.5]: half the box (0.9 m) east of
                 the centre -> at_world [0.9, 0], capacity 1 -> one slot
                 = the marker; facing 90
    root_offset  seat root_drop 0.234 x 1.70 m = 0.3978 -> 0.398

The same prop placed the same way in a STORED location gives the identical
place list through ``scene_for_location`` (the game's payload).
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="prop-places-preview-"))
CLIPS = Path(tempfile.mkdtemp(prefix="prop-places-preview-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.models.world import (add_location, get_location_by_id,  # noqa: E402
                              update_location_position, upsert_location)
from app.routes import play as play_routes  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


PID = "bench"
(STORAGE / "props" / PID).mkdir(parents=True, exist_ok=True)
# A model file must exist: a prop without a measurable mesh has no places.
(STORAGE / "props" / PID / "model.glb").write_bytes(b"glTF")
prop_store._write_sidecar(PID, {
    "name": "Bench", "bbox": [1.8, 0.5, 0.5],
    "width_m": 1.8, "depth_m": 0.5, "height_m": 0.5,
    "model_variants": [{
        "stem": "model", "active": True,
        "width_m": 1.8, "depth_m": 0.5, "height_m": 0.5,
        "markers": [
            {"id": "m1", "group": "seat", "at": [0.5, 1.0, 0.5],
             "capacity": 3, "spacing_m": 0.6, "facing": 0},
            {"id": "m2", "group": "seat", "at": [1.0, 1.0, 0.5],
             "capacity": 1, "facing": 90},
        ]}]})
prop_store.read_sidecar(PID)
scene_recipe.invalidate_prop_lib_token()

ROOM = {"id": "r", "name": "Preview",
        "layout": {"x": -2, "y": -2, "w": 4, "d": 4,
                   "props": [{"id": "p", "prop_id": PID,
                              "at": [2, 2], "yaw": 0}]}}


def places(payload):
    keys = ("id", "group", "capacity", "at_world", "slots", "facing",
            "y_world", "root_offset")
    return [{k: m.get(k) for k in keys} for m in payload["markers"]]


def main() -> int:
    print("[1] the draft preview answers the bench's places")
    draft = play_routes._play_scene_preview_sync(None, {"rooms": [ROOM]})
    got = {p["id"]: p for p in places(draft)}
    check("two places", sorted(got), ["p/m1", "p/m2"])
    m1, m2 = got.get("p/m1", {}), got.get("p/m2", {})
    check("m1 slots", m1.get("slots"), [[-0.6, 0.0], [0.0, 0.0], [0.6, 0.0]])
    check("m1 facing", m1.get("facing"), 0.0)
    check("m1 y_world", m1.get("y_world"), 0.51)
    check("m1 root_offset", m1.get("root_offset"), 0.398)
    check("m1 capacity", m1.get("capacity"), 3)
    check("m2 at_world", m2.get("at_world"), [0.9, 0.0])
    check("m2 one slot = the marker", m2.get("slots"), [[0.9, 0.0]])
    check("m2 facing", m2.get("facing"), 90.0)

    print("[2] the game payload of a stored location says the same")
    loc_id = add_location(name="Shop", description="smoke",
                          rooms=[{"id": "r", "name": "Preview"}])["id"]
    update_location_position(loc_id, 0.0, 0.0)
    loc = get_location_by_id(loc_id)
    loc["map3d"] = {"plan_width_m": 10.0,
                    "boundary": [[-5.0, -5.0], [5.0, -5.0],
                                 [5.0, 5.0], [-5.0, 5.0]]}
    loc["rooms"][0]["layout"] = ROOM["layout"]
    upsert_location(loc, sync_world=True)
    game = scene_recipe.scene_for_location(get_location_by_id(loc_id), loc_id)
    check("identical place list", places(game), places(draft))

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
