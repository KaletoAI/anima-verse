#!/usr/bin/env python3
"""Smoke run: ``places._compose`` and ``room_stand.room_geometry`` key their
caches on the props THEIR compose read — a new prop elsewhere recomposes
nothing, an edit of a read prop recomposes exactly the locations that read it.

THE FINDING (2026-11-11). Both caches were keyed on
``scene_recipe.scene_fingerprint``, which takes the props as ONE stat over the
whole library, and ``places.invalidate()`` — run by every prop sidecar write,
i.e. by every new prop — also dropped every composed location outright. A
prop generated nowhere near a location recomposed it (~0.5 s each) on the
next offer poll / approach tick / stand-up. The scene poll had already been
narrowed to its read set on 2026-11-07 (``smoke_scene_fingerprint_churn.py``).

THE FIX. Both composers run through ``scene_recipe.compose_recorded`` (key
captured BEFORE the reads, then restricted to the props the compose resolved)
and check a hit with ``scene_recipe.narrowed_fingerprint`` over the recorded
set. ``places.invalidate()`` keeps dropping the TTL inventory, no longer the
fingerprinted compositions.

Runs against a THROWAWAY storage directory — no real world, no server, no
LLM/image call.

The seed (the one of ``smoke_scene_fingerprint_churn.py``, minus the world
prop):

    prop "crate"    placed in "Warehouse" AND in "Shed"
    prop "barrel"   placed in "Shed"
    prop "rose"     created during the run, placed nowhere
    location "Warehouse"  a drawn 20 m square at (0, 0), room "hall"
                          (x=-8 z=-8 w=16 d=12) holding the crate at (2, 2)
    location "Shed"       the same square at (100, 0), room "hall" holding
                          the barrel at (2, 2) and the crate at (3, 2)

Hand-derived expectations
-------------------------

[0] at rest. Each location is composed until a repeat call composes
    nothing (the first read of a hand-written sidecar migrates it once — a
    write into a directory the key stats, so one more compose follows; the
    churn smoke records the same). Then the recorded read sets are exactly
    the props the rooms name:
        places   Warehouse {"crate"}           Shed {"barrel", "crate"}
        geometry Warehouse/hall {"crate"}      Shed/hall {"barrel", "crate"}
    and a hit inside an outer ``recording_reads`` block replays the cached
    set: Warehouse's places hit records {"crate"} there.

[1] a NEW prop "rose" (sidecar + source.png) plus ``places.invalidate()`` —
    what ``props._write_sidecar`` does for every new prop:
        places compose count      Warehouse 0, Shed 0
        geometry compose count    Warehouse 0, Shed 0
    while ``scene_fingerprint`` — the key both caches used before — moves
    for both locations (the BEFORE: each would have recomposed).

[2] the barrel's sidecar is edited (+ ``places.invalidate()``):
        places     Shed 1, Warehouse 0
        geometry   Shed/hall 1, Warehouse/hall 0
    and a second call composes 0 for both (the new key holds).

[3] the crate's sidecar is edited (+ ``places.invalidate()``): crate is in
    BOTH read sets, so places Warehouse 1 and Shed 1, geometry 1 and 1.

[4] the key is captured BEFORE the reads: a crate sidecar rewrite injected
    right after Warehouse's places compose (inside ``_compose_fresh``,
    before ``compose_recorded`` returns) leaves the stored key on the
    crate's OLD stats — the next call composes again (1), the one after
    that does not (0).

[5] the read set does not depend on warm caches: with ``terrain_sig``'s,
    the world-prop payload's and the prop token's caches dropped, the set
    ``compose_recorded`` returns for Warehouse's places and geometry equals
    the warm one ({"crate"} both times).

Usage:  ./.venv/bin/python scripts/smoke_places_read_set.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="places-read-set-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="places-read-set-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import places, room_stand  # noqa: E402
from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.models import terrain as terrain_model  # noqa: E402
from app.models import world_props  # noqa: E402
from app.models.world import (  # noqa: E402
    add_location, get_location_by_id, update_location_position,
    upsert_location)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def tick() -> None:
    """Let the clock move past the last write, so a rewrite is a new stat."""
    time.sleep(0.02)


PROPS = STORAGE / "props"


def write_prop(pid: str, tags, **extra) -> None:
    d = PROPS / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / prop_store.SIDECAR_NAME).write_text(json.dumps({
        "name": pid.title(), "category": "furniture",
        "width_m": 0.8, "depth_m": 0.8, "height_m": 0.6,
        "tags": list(tags), **extra}), encoding="utf-8")
    scene_recipe.invalidate_prop_lib_token()
    places.invalidate()          # what props._write_sidecar does


write_prop("crate", ["walkable"])
write_prop("barrel", [])

SQUARE = {"plan_width_m": 20.0,
          "boundary": [[-10.0, -10.0], [10.0, -10.0],
                       [10.0, 10.0], [-10.0, 10.0]]}
WAREHOUSE = add_location(name="Warehouse", description="read-set smoke",
                         rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(WAREHOUSE, 0.0, 0.0)
SHED = add_location(name="Shed", description="read-set smoke",
                    rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(SHED, 100.0, 0.0)


def lay_out(location_id: str, prop_ids) -> None:
    loc = get_location_by_id(location_id)
    loc["map3d"] = dict(SQUARE)
    loc["rooms"][0]["layout"] = {
        "x": -8, "y": -8, "w": 16, "d": 12,
        "props": [{"id": f"p{i}", "prop_id": pid, "at": [2.0 + i, 2.0],
                   "yaw": 0} for i, pid in enumerate(prop_ids)]}
    upsert_location(loc, sync_world=True)


lay_out(WAREHOUSE, ["crate"])
lay_out(SHED, ["barrel", "crate"])

# ── the counters ────────────────────────────────────────────────────────
_real_places_fresh = places._compose_fresh
_real_geometry_fresh = room_stand._room_geometry_fresh
_counts = {"places": 0, "geometry": 0}
_inject = {"after_places": None}


def _counting_places(location_id, loc):
    _counts["places"] += 1
    out = _real_places_fresh(location_id, loc)
    hook = _inject["after_places"]
    if hook:
        _inject["after_places"] = None
        hook()
    return out


def _counting_geometry(loc, room_id):
    _counts["geometry"] += 1
    return _real_geometry_fresh(loc, room_id)


places._compose_fresh = _counting_places
room_stand._room_geometry_fresh = _counting_geometry


def places_count(location_id: str) -> int:
    _counts["places"] = 0
    places._compose(location_id)
    return _counts["places"]


def geometry_count(location_id: str) -> int:
    _counts["geometry"] = 0
    room_stand.room_geometry(location_id, "hall")
    return _counts["geometry"]


def settle(location_id: str) -> None:
    for _ in range(4):
        if places_count(location_id) == 0 and geometry_count(location_id) == 0:
            return
        tick()
    raise SystemExit(f"FAIL: {location_id} never settled")


def old_key(location_id: str) -> str:
    scene_recipe.invalidate_prop_lib_token()   # no 5-second grace: measure
    return scene_recipe.scene_fingerprint(get_location_by_id(location_id),
                                          location_id)


def edit_sidecar(pid: str, **change) -> None:
    tick()
    path = PROPS / pid / prop_store.SIDECAR_NAME
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(change)
    path.write_text(json.dumps(meta), encoding="utf-8")
    scene_recipe.invalidate_prop_lib_token()
    places.invalidate()


# ── [0] at rest ─────────────────────────────────────────────────────────
print("[0] at rest")
settle(WAREHOUSE)
settle(SHED)
check("places read set, Warehouse", sorted(places._composed[WAREHOUSE][1]), ["crate"])
check("places read set, Shed", sorted(places._composed[SHED][1]), ["barrel", "crate"])
check("geometry read set, Warehouse/hall",
      sorted(room_stand._geometry_cache[(WAREHOUSE, "hall")][1]), ["crate"])
check("geometry read set, Shed/hall",
      sorted(room_stand._geometry_cache[(SHED, "hall")][1]), ["barrel", "crate"])
with prop_store.recording_reads() as outer:
    _counts["places"] = 0
    places._compose(WAREHOUSE)
check("a hit composes nothing", _counts["places"], 0)
check("a hit replays its read set to an outer recorder", sorted(outer), ["crate"])

# ── [1] an unrelated new prop ───────────────────────────────────────────
print("[1] a new prop placed nowhere")
before = {lid: old_key(lid) for lid in (WAREHOUSE, SHED)}
tick()
write_prop("rose", [])
(PROPS / "rose" / "source.png").write_bytes(b"\x89PNG fake")
scene_recipe.invalidate_prop_lib_token()
for lid, name in ((WAREHOUSE, "Warehouse"), (SHED, "Shed")):
    check(f"old key (scene_fingerprint) moves, {name}", old_key(lid) != before[lid], True)
    check(f"places composes, {name}", places_count(lid), 0)
    check(f"geometry composes, {name}", geometry_count(lid), 0)

# ── [2] a prop only Shed reads ──────────────────────────────────────────
print("[2] the barrel's sidecar is edited")
edit_sidecar("barrel", height_m=0.9)
check("places composes, Shed", places_count(SHED), 1)
check("places composes, Warehouse", places_count(WAREHOUSE), 0)
check("geometry composes, Shed", geometry_count(SHED), 1)
check("geometry composes, Warehouse", geometry_count(WAREHOUSE), 0)
check("places again, Shed", places_count(SHED), 0)
check("geometry again, Shed", geometry_count(SHED), 0)

# ── [3] a prop both read ────────────────────────────────────────────────
print("[3] the crate's sidecar is edited")
edit_sidecar("crate", height_m=0.7)
check("places composes, Warehouse", places_count(WAREHOUSE), 1)
check("places composes, Shed", places_count(SHED), 1)
check("geometry composes, Warehouse", geometry_count(WAREHOUSE), 1)
check("geometry composes, Shed", geometry_count(SHED), 1)

# ── [4] a write while the compose runs ──────────────────────────────────
print("[4] the key is captured before the reads")
edit_sidecar("crate", height_m=0.75)
_inject["after_places"] = lambda: edit_sidecar("crate", height_m=0.8)
check("places composes (the edit before)", places_count(WAREHOUSE), 1)
check("places composes again (the edit during)", places_count(WAREHOUSE), 1)
check("places then holds", places_count(WAREHOUSE), 0)

# ── [5] cold == warm ────────────────────────────────────────────────────
print("[5] the read set does not depend on warm caches")


def make_cold() -> None:
    terrain_model._sig_cache = (None, "")
    world_props._payload_cache = (None, [], "")
    scene_recipe.invalidate_prop_lib_token()


def recorded(fn):
    loc = get_location_by_id(WAREHOUSE)
    return sorted(scene_recipe.compose_recorded(loc, WAREHOUSE, lambda: fn(loc))[1])


for label, fn in (("places", lambda loc: _real_places_fresh(WAREHOUSE, loc)),
                  ("geometry", lambda loc: _real_geometry_fresh(loc, "hall"))):
    make_cold()
    cold = recorded(fn)
    warm = recorded(fn)
    check(f"{label} cold read set", cold, ["crate"])
    check(f"{label} warm read set", warm, ["crate"])

print()
if FAILURES:
    print(f"FAIL: {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"OK: all {CHECKED} checks passed")
