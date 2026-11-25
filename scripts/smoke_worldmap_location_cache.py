#!/usr/bin/env python3
"""Smoke run for the WORLDMAP LOCATION BLOCK cache (server hot paths, stage 1,
task 2).

``build_worldmap_payload`` used to rebuild every location entry (boundary in
world space, openings, layout signature, world bounds) on EVERY 2-3 s poll of
every client. The block that does not depend on the viewer is now built once
per (storage dir, world generation, terrain areas key) in
``world_ops._location_block`` and only the fog filter runs per request.

Runs against THROWAWAY storage directories — never a real world, no server,
no LLM.

Fixture (hand-placed)
---------------------
  a: pin (0, 0), yaw 0, drawn boundary = centred 10 m square
     (-5,-5) (5,-5) (5,5) (-5,5), one opening {edge 0, at 0.5}
  b: pin (100, 0), NO boundary (a bare pin)
  one terrain area (water), polygon (-50,-50) (-40,-50) (-40,-40) (-50,-40)

Counters wrap ``scene_recipe.layout_signature`` (total calls) and
``boundary_entry.opening_world_frames`` (calls per location id).

Hand-derived expectations
-------------------------
[L1] two ``build_worldmap_payload(show_all=True)`` calls build the block once:
     opening_world_frames for a = 1 (the old code: 2, one per call),
     total opening_world_frames = 2 (a and b, once each; old: 4),
     layout_signature total = 1 (only a has map3d; old: 2);
     ``locations`` of both answers equal.
[L2] world_bounds = min/max over the area box (-50..-40, -50..-40), a's world
     box (-5..5, -5..5) and b's pin (100, 0):
     {"min_x": -50.0, "min_z": -50.0, "max_x": 100.0, "max_z": 5.0}
[L3] a's opening: edge 0 runs (-5,-5) -> (5,-5); at 0.5 is local (0, -5);
     the polygon is clockwise in map view, its inward normal on that edge is
     (0, 1) (the hand example in boundary_entry.opening_world_frames); yaw 0
     and pin (0, 0) leave both unchanged -> at_world [0.0, -5.0],
     inward [0.0, 1.0].
[L4] upsert_location moves a to (20, 0) -> the world generation moves, the
     next call rebuilds (opening_world_frames for a = 2): at_world
     [20.0, -5.0]; max_x stays 100.0 (b's pin beats a's box 15..25).
[L5] a second area (150,-2) (200,-2) (200,0) (150,0) -> the terrain
     generation moves -> rebuild; max_x 200.0.
[R1] race: a is re-saved at (20, 0) (the generation moves to g0, so the next
     call builds); ``world_ops._before_publish`` (runs after the build,
     before the publish) upserts a to (30, 0). That call answers the state it READ
     (at_world [20.0, -5.0]); the cache carries the key captured BEFORE the
     read (world generation g0, not g0+1); the next call rebuilds and shows
     [30.0, -5.0].
[R4] after [L1] the entry dicts of both answers are the same objects (is),
     the two lists are distinct, and json.dumps of the first answer's
     locations is unchanged by the second call.
[R3] a back to (0, 0), the L5 area deleted (bounds = [L2] again).
     Avatar kim knows a, lou knows b: kim's locations = [a], lou's = [b];
     world_bounds of both = [L2]; layout_signature calls for the two
     requests together = 1 (one rebuild, after the restoring writes).
[R2] paths.init(tmp2), a second world with one location c at (7, 7), the
     world generation forced back to the cached key's number -> no hit:
     locations = [c].

Usage:  ./.venv/bin/python scripts/smoke_worldmap_location_cache.py
"""
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-locblock-smoke-"))
STORAGE2 = Path(tempfile.mkdtemp(prefix="worldmap-locblock-smoke2-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="worldmap-locblock-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import boundary_entry, scene_recipe, world_ops  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models import world as W  # noqa: E402
from app.models.character import (  # noqa: E402
    save_character_profile, set_known_locations)

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


OWF = Counter()
LAYOUT = Counter()
_real_owf = boundary_entry.opening_world_frames
_real_layout = scene_recipe.layout_signature


def _counting_owf(location):
    OWF[(location or {}).get("id") or ""] += 1
    OWF["total"] += 1
    return _real_owf(location)


def _counting_layout(map3d, rooms):
    LAYOUT["total"] += 1
    return _real_layout(map3d, rooms)


boundary_entry.opening_world_frames = _counting_owf
scene_recipe.layout_signature = _counting_layout


def place(loc_id, x, z):
    loc = W.get_location_by_id(loc_id)
    loc["pos_x"], loc["pos_z"] = float(x), float(z)
    assert W.upsert_location(loc, sync_world=False)


def entry(payload, loc_id):
    for e in payload["locations"]:
        if e["id"] == loc_id:
            return e
    return {}


def ids(payload):
    return sorted(e["id"] for e in payload["locations"])


def at_world(payload, loc_id):
    return (entry(payload, loc_id).get("openings") or [{}])[0].get("at_world")


def build(avatar=None, show_all=True):
    return world_ops.build_worldmap_payload(avatar, show_all=show_all)


# ── Seed ────────────────────────────────────────────────────────────────
A = W.add_location(name="Square A", description="loc block smoke")["id"]
B = W.add_location(name="Pin B", description="loc block smoke")["id"]
_a = W.get_location_by_id(A)
_a.update({"pos_x": 0.0, "pos_z": 0.0, "yaw_deg": 0.0})
_a["map3d"] = {"boundary": [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]],
               "plan_width_m": 10.0,
               "boundary_openings": [{"edge": 0, "at": 0.5}]}
assert W.upsert_location(_a, sync_world=False)
_b = W.get_location_by_id(B)
_b.update({"pos_x": 100.0, "pos_z": 0.0, "yaw_deg": 0.0})
_b.pop("map3d", None)
assert W.upsert_location(_b, sync_world=False)
AREA1 = terrain.save_area({"kind": "water", "z_order": 0,
                           "polygon": [[-50, -50], [-40, -50], [-40, -40],
                                       [-50, -40]]})["id"]

BOUNDS = {"min_x": -50.0, "min_z": -50.0, "max_x": 100.0, "max_z": 5.0}


def main() -> int:
    print("\n[L1] two admin calls, one build")
    OWF.clear()
    LAYOUT.clear()
    first = build()
    snap = json.dumps(first["locations"], sort_keys=True)
    second = build()
    check("opening_world_frames(a) calls", OWF[A], 1)
    check("opening_world_frames total", OWF["total"], 2)
    check("layout_signature calls", LAYOUT["total"], 1)
    check("locations equal", first["locations"] == second["locations"], True)
    check("ids", ids(first), sorted([A, B]))

    print("\n[R4] shared entries, never mutated")
    same = [entry(first, i) is entry(second, i) for i in (A, B)]
    check("entry dicts are the same objects", same, [True, True])
    check("locations lists are distinct",
          first["locations"] is second["locations"], False)
    check("first answer unchanged after the second call",
          json.dumps(first["locations"], sort_keys=True) == snap, True)

    print("\n[L2] world bounds before the fog")
    check("world_bounds", first["world_bounds"], BOUNDS)

    print("\n[L3] a's opening")
    ops = entry(first, A).get("openings") or [{}]
    check("at_world", ops[0].get("at_world"), [0.0, -5.0])
    check("inward", ops[0].get("inward"), [0.0, 1.0])

    print("\n[L4] moving a rebuilds")
    place(A, 20, 0)
    p = build()
    check("opening_world_frames(a) calls", OWF[A], 2)
    check("at_world", at_world(p, A), [20.0, -5.0])
    check("max_x", p["world_bounds"]["max_x"], 100.0)

    print("\n[L5] a new terrain area rebuilds")
    area2 = terrain.save_area({"kind": "water", "z_order": 0,
                               "polygon": [[150, -2], [200, -2], [200, 0],
                                           [150, 0]]})["id"]
    p = build()
    check("max_x", p["world_bounds"]["max_x"], 200.0)

    print("\n[R1] a write between build and publish")
    place(A, 20, 0)  # same spot, but the generation moves: next call builds
    g0 = W.world_generation()
    fired = []

    def _race():
        if not fired:
            fired.append(True)
            place(A, 30, 0)

    world_ops._before_publish = _race
    try:
        racing = build()
    finally:
        world_ops._before_publish = None
    check("hook fired", fired, [True])
    check("racing answer = state read", at_world(racing, A), [20.0, -5.0])
    cache = getattr(world_ops, "_loc_block_cache", None)
    check("cache key generation = captured before the read",
          cache[0][1] if cache else None, g0)
    after = build()
    check("next call shows the new state", at_world(after, A), [30.0, -5.0])

    print("\n[R3] two avatars share one block")
    place(A, 0, 0)
    terrain.delete_area(area2)
    for name, known in (("kim", A), ("lou", B)):
        save_character_profile(name, {"current_location": ""}, create_new=True)
        set_known_locations(name, [known])
    LAYOUT.clear()
    kim = build("kim", show_all=False)
    lou = build("lou", show_all=False)
    check("kim locations", ids(kim), [A])
    check("lou locations", ids(lou), [B])
    check("kim world_bounds", kim["world_bounds"], BOUNDS)
    check("lou world_bounds", lou["world_bounds"], BOUNDS)
    check("layout_signature calls for both", LAYOUT["total"], 1)

    print("\n[R2] another world never hits")
    gen = W.world_generation()
    paths.init(STORAGE2)
    # Connections are thread-local and keep their file; drop them so the
    # second world's DB is the one opened.
    for conn in list(db._connections.values()):
        conn.close()
    db._connections.clear()
    db.init_schema()
    C = W.add_location(name="Other C", description="second world")["id"]
    W.update_location_position(C, 7.0, 7.0)
    W._world_generation = gen
    p = build()
    check("second world locations", ids(p), [C])

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
