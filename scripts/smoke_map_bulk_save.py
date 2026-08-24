#!/usr/bin/env python3
"""Smoke run for the map editor's BATCH SAVE (plan-map-save-batch.md, B1).

Checks the three bulk writers without a server, against a throwaway storage:

    app/models/terrain.save_areas_bulk
    app/models/heightfield.save_height_areas_bulk
    app/models/world_props.save_world_props_bulk

and the splitter they share, ``app/core/bulk_edit.plan_batch``.

WHY THIS EXISTS. Every singular write pays three tolls: it opens its own
transaction, it settles water against a freshly built height model, and it
rings the world-write hook — which re-rasters the relief and moves the
signature every client polls. Painting a map is dozens of such writes for ONE
result. The batch pays each toll ONCE, and that is exactly what is measured
here: not "the batch works", but "the batch costs one where the singles cost
seven".

HAND-DERIVED EXPECTATIONS (derived from the code's contract, never recorded
from a run):

  [1] SEVEN OPERATIONS, ONE HOOK.
      The world starts with two painted areas (`a1`, `a2`). The edit is five
      new areas plus the deletion of both — seven operations.

      Run singly (the RED PROBE, i.e. today's editor):
        7 calls of save_area/delete_area  ->  7 x note_world_write.
        The signature is read before and after each one, so 8 readings; every
        one of the 8 world states is a different SET of areas
          {a1,a2} {a1,a2,n1} {a1,a2,n1,n2} {a1,a2,n1..n3} {a1,a2,n1..n4}
          {a1,a2,n1..n5} {a2,n1..n5} {n1..n5}
        so 8 DISTINCT signatures.

      Run as one batch (the same seven operations):
        1 x note_world_write, and 2 readings -> 2 distinct signatures.

      And the world ends up the same either way: the five areas carry the same
      kind/polygon/z_order/meta in the same order.

  [2] OPTIMISTIC CONCURRENCY, per object, HTTP-wise still a success.
      With `s` = the stamp an editor loaded and `s2` = the stamp after
      somebody else saved:
        upsert carrying s  (stored is s2)   -> rejected "changed on the server",
                                               the stored kind is UNCHANGED
        upsert carrying s2 (stored is s2)   -> saved
        upsert carrying no stamp at all     -> saved (a deliberate overwrite,
                                               exactly what the singular PUT
                                               has always done)
        upsert of a DELETED id              -> rejected "deleted on the
                                               server" — the singular PUT's
                                               404 guard, so a stale write
                                               cannot resurrect an area
        delete carrying the stale s         -> rejected "changed on the server"
        delete of an id already gone        -> reported as deleted (the goal
                                               state is what was asked for)
        delete without an id                -> rejected "delete needs an id"
        an upsert with a junk kind          -> rejected with the sanitizer's
                                               own sentence, and the REST OF
                                               THE BATCH still lands
      Every one of these answers, not raises: the request as a whole succeeds.
      The stamps are written to the MICROSECOND (``terrain._edit_stamp``): at
      the default second resolution the two saves below would produce the very
      same string, and a stale write would slip through the check unseen —
      which is exactly the burst of edits a batch save makes.

  [3] WATER SETTLES THE SAME IN A BATCH AS IT DOES ALONE.
      A 5 m plateau with no ramp covers the whole test ground
      ([-50,-50]..[150,150], height 5, falloff 0), so the natural height along
      any rim inside it is 5.0 m. A lake painted at [[0,0],[20,0],[20,20],
      [0,20]] with no authored level therefore settles at
        meta.water_level == 5.0
      whether it is saved singly or in a batch — the batch borrows the warm
      model instead of building its own, and a warm model that answered
      something else would be the bug this pins.

  [4] AN EMPTY BATCH MOVES NOTHING.
        {} / {"upserts": [], "deletes": []}   -> 0 x note_world_write,
                                                 the signature is unchanged
        a batch whose only delete names an already-gone id
                                              -> still 0 x note_world_write
                                                 (nothing was really removed),
                                                 signature unchanged
      This is what keeps a "Save" with an empty buffer from re-baking a world.

  [5] THE RELIEF BATCH, same arithmetic with the OTHER hook.
      Three new height areas plus one deletion = four operations.
        singly -> 4 x heightfield._invalidate (each re-rasters the whole grid)
        batch  -> 1 x heightfield._invalidate
      and 5 vs 2 distinct height signatures over the same readings.

  [6] THE PROP BATCH AND ITS CAP (MAX_WORLD_PROPS = 500).
        a batch of 500 new placements -> 500 saved, 0 rejected, count 500
        a batch of 1 delete + 2 new   -> the delete first leaves 499, so
                                          room is 1: the FIRST new one is
                                          saved, the second rejected with the
                                          cap sentence, count 500 again.
      The singular route could never do that — its delete and its creates were
      separate requests in an order nobody controlled.

  [7] THE ROUTES over them, called directly (no server, no HTTP):
        a body that is not an object      -> HTTPException 400
        an EMPTY body                     -> success with three empty lists,
                                             NOT a 400 (a Save with nothing
                                             buffered is not an error)
        the terrain route                 -> {"status": "success", saved…}
        the height route                  -> …plus `step_m` > 0, the step the
                                             world has after the batch
        the prop route, deletes only      -> empties the world in ONE request

Usage:  ./.venv/bin/python scripts/smoke_map_bulk_save.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="map-bulk-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="map-bulk-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core.bulk_edit import REASON_CHANGED, REASON_GONE  # noqa: E402
from app.models import heightfield as hf  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models import world_props as wp  # noqa: E402

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


# ── The two hooks, counted ──────────────────────────────────────────────────
# `note_world_write` is imported INSIDE `terrain._note_relief_write`, and
# `_invalidate` is looked up as a module global by both height writers — so
# replacing the attributes here counts every real call without touching the
# code under test.

HOOKS = {"note": 0, "invalidate": 0}
_real_note = hf.note_world_write
_real_invalidate = hf._invalidate


def _counting_note():
    HOOKS["note"] += 1
    _real_note()


def _counting_invalidate():
    HOOKS["invalidate"] += 1
    _real_invalidate()


hf.note_world_write = _counting_note
hf._invalidate = _counting_invalidate


def reset_hooks():
    HOOKS["note"] = 0
    HOOKS["invalidate"] = 0


def square(x, z, w=10):
    return [[x, z], [x + w, z], [x + w, z + w], [x, z + w]]


def shape_of(areas):
    """What an area IS, without its id or its stamp — so two runs can be
    compared even though the ids are minted fresh each time."""
    return [(a["kind"], a["polygon"], a["z_order"], a["meta"]) for a in areas]


NEW_FIVE = [{"kind": "grass", "polygon": square(100 + 20 * i, 0),
             "z_order": i} for i in range(5)]

print("[1] seven operations, one hook")

a1 = terrain.save_area({"kind": "grass", "polygon": square(0, 0)})
a2 = terrain.save_area({"kind": "grass", "polygon": square(20, 0)})

# — the RED PROBE: the same seven operations one by one —
reset_hooks()
sigs = [terrain.terrain_sig()]
for spec in NEW_FIVE:
    terrain.save_area(dict(spec))
    sigs.append(terrain.terrain_sig())
terrain.delete_area(a1["id"])
sigs.append(terrain.terrain_sig())
terrain.delete_area(a2["id"])
sigs.append(terrain.terrain_sig())
check("singly: seven writes ring the world hook seven times", HOOKS["note"], 7)
check("singly: eight signature readings, eight distinct signatures",
      (len(sigs), len(set(sigs))), (8, 8))
single_shape = shape_of(terrain.list_areas())
check("singly: five areas remain", len(single_shape), 5)

# — reset to the very same starting world —
for area in terrain.list_areas():
    terrain.delete_area(area["id"])
a1 = terrain.save_area({"kind": "grass", "polygon": square(0, 0)})
a2 = terrain.save_area({"kind": "grass", "polygon": square(20, 0)})
stamps = terrain.area_stamps()

# — the BATCH: seven operations, one call —
reset_hooks()
sig_before = terrain.terrain_sig()
result = terrain.save_areas_bulk(
    [dict(spec) | {"temp_id": f"t{i}"} for i, spec in enumerate(NEW_FIVE)],
    [{"id": a1["id"], "updated_at": stamps[a1["id"]]},
     {"id": a2["id"], "updated_at": stamps[a2["id"]]}])
sig_after = terrain.terrain_sig()
check("batch: seven operations ring the world hook ONCE", HOOKS["note"], 1)
check("batch: two signature readings, two distinct signatures",
      (2, len({sig_before, sig_after})), (2, 2))
check("batch: five saved, two deleted, none rejected",
      (len(result["saved"]), len(result["deleted"]), result["rejected"]),
      (5, 2, []))
check("batch: every new area answers under its temp id with a minted one",
      [(e["temp_id"], e["area"]["id"].startswith("ta_"))
       for e in result["saved"]],
      [(f"t{i}", True) for i in range(5)])
check("batch: the world it leaves is the world the singles left",
      shape_of(terrain.list_areas()), single_shape)

print("\n[2] optimistic concurrency — refusals are answers, not errors")

for area in terrain.list_areas():
    terrain.delete_area(area["id"])
live = terrain.save_area({"kind": "grass", "polygon": square(0, 0)})
stale = terrain.area_stamps()[live["id"]]
# Somebody else saves it: same id, new stamp.
terrain.save_area({"id": live["id"], "kind": "grass",
                   "polygon": square(0, 0), "z_order": 3})
fresh = terrain.area_stamps()[live["id"]]
check("the stamp really moved", stale != fresh, True)

gone = terrain.save_area({"kind": "grass", "polygon": square(60, 60)})
gone_stamp = terrain.area_stamps()[gone["id"]]
terrain.delete_area(gone["id"])

res = terrain.save_areas_bulk(
    [{"id": live["id"], "kind": "water", "polygon": square(0, 0),
      "updated_at": stale, "temp_id": ""},
     {"id": gone["id"], "kind": "grass", "polygon": square(60, 60),
      "updated_at": gone_stamp},
     {"kind": "nope_unknown", "polygon": square(80, 80), "temp_id": "tx"},
     {"kind": "grass", "polygon": square(40, 40), "temp_id": "tok"}],
    [{"id": live["id"], "updated_at": stale},
     {"id": gone["id"], "updated_at": gone_stamp},
     {"id": ""}])
check("the stale upsert is refused as changed",
      [r for r in res["rejected"] if r["id"] == live["id"]
       and r["op"] == "upsert"],
      [{"op": "upsert", "id": live["id"], "temp_id": "",
        "reason": REASON_CHANGED}])
check("...and the stored area kept its kind",
      [a["kind"] for a in terrain.list_areas() if a["id"] == live["id"]],
      ["grass"])
check("an upsert of a deleted id is refused, never resurrected",
      [r["reason"] for r in res["rejected"]
       if r["id"] == gone["id"] and r["op"] == "upsert"], [REASON_GONE])
check("a junk kind is refused with the sanitizer's own sentence",
      [r["reason"] for r in res["rejected"] if r["temp_id"] == "tx"],
      ["unknown terrain kind: 'nope_unknown'"])
check("the stale DELETE is refused as changed",
      [r["reason"] for r in res["rejected"]
       if r["id"] == live["id"] and r["op"] == "delete"], [REASON_CHANGED])
check("a delete of something already gone counts as deleted",
      (gone["id"] in res["deleted"],
       [r for r in res["rejected"]
        if r["id"] == gone["id"] and r["op"] == "delete"]),
      (True, []))
check("a delete without an id is refused",
      [r["reason"] for r in res["rejected"]
       if r["op"] == "delete" and r["id"] == ""], ["delete needs an id"])
check("and the healthy entry of the same batch still landed",
      [e["temp_id"] for e in res["saved"]], ["tok"])

res = terrain.save_areas_bulk(
    [{"id": live["id"], "kind": "water", "polygon": square(0, 0),
      "updated_at": terrain.area_stamps()[live["id"]]}], [])
check("an upsert with the CURRENT stamp is saved",
      (len(res["saved"]), res["rejected"],
       [a["kind"] for a in terrain.list_areas() if a["id"] == live["id"]]),
      (1, [], ["water"]))
res = terrain.save_areas_bulk(
    [{"id": live["id"], "kind": "grass", "polygon": square(0, 0)}], [])
check("an upsert with NO stamp is a deliberate overwrite and is saved",
      (len(res["saved"]), res["rejected"],
       [a["kind"] for a in terrain.list_areas() if a["id"] == live["id"]]),
      (1, [], ["grass"]))

print("\n[3] water settles the same in a batch as it does alone")

for area in terrain.list_areas():
    terrain.delete_area(area["id"])
plateau = hf.save_height_area({"polygon": [[-50, -50], [150, -50],
                                           [150, 150], [-50, 150]],
                               "height_m": 5.0, "falloff_m": 0.0})
LAKE = [[0, 0], [20, 0], [20, 20], [0, 20]]
single_lake = terrain.save_area({"kind": "water", "polygon": LAKE})
check("a lake in a 5 m plateau settles at the plateau, saved singly",
      single_lake["meta"].get("water_level"), 5.0)
terrain.delete_area(single_lake["id"])
batch_lake = terrain.save_areas_bulk(
    [{"kind": "water", "polygon": LAKE, "temp_id": "lake"}], [])
check("...and at exactly the same level in a batch",
      batch_lake["saved"][0]["area"]["meta"].get("water_level"),
      single_lake["meta"].get("water_level"))
check("the settled level is stored, not only answered",
      [a["meta"].get("water_level") for a in terrain.list_areas()
       if a["kind"] == "water"], [5.0])
# Two lakes at once: one warm model, two settled mirrors — the case a
# per-object save would have built two models for.
terrain.delete_area(batch_lake["saved"][0]["area"]["id"])
two = terrain.save_areas_bulk(
    [{"kind": "water", "polygon": LAKE, "temp_id": "l1"},
     {"kind": "water", "polygon": [[40, 40], [60, 40], [60, 60], [40, 60]],
      "temp_id": "l2"}], [])
check("two lakes in one batch both settle on the plateau",
      [e["area"]["meta"].get("water_level") for e in two["saved"]],
      [5.0, 5.0])

print("\n[4] an empty batch moves nothing")

reset_hooks()
sig_before = terrain.terrain_sig()
empty = terrain.save_areas_bulk(None, None)
check("an empty body is a success with nothing in it",
      (empty["saved"], empty["deleted"], empty["rejected"]), ([], [], []))
check("...it rings no hook and moves no signature",
      (HOOKS["note"], terrain.terrain_sig() == sig_before), (0, True))

reset_hooks()
sig_before = terrain.terrain_sig()
noop = terrain.save_areas_bulk([], [{"id": "ta_does_not_exist"}])
check("a delete of something already gone is reported…",
      noop["deleted"], ["ta_does_not_exist"])
check("…but changes nothing, so no hook and no signature move",
      (HOOKS["note"], terrain.terrain_sig() == sig_before), (0, True))

print("\n[5] the relief batch — four operations, one re-raster")

for area in hf.list_height_areas():
    hf.delete_height_area(area["id"])
h1 = hf.save_height_area({"polygon": square(0, 0), "height_m": 2.0,
                          "falloff_m": 1.0})
NEW_THREE = [{"polygon": square(100 + 20 * i, 0), "height_m": 1.0 + i,
              "falloff_m": 2.0} for i in range(3)]

reset_hooks()
hsigs = [hf.height_sig()]
for spec in NEW_THREE:
    hf.save_height_area(dict(spec))
    hsigs.append(hf.height_sig())
hf.delete_height_area(h1["id"])
hsigs.append(hf.height_sig())
check("singly: four relief writes re-raster four times",
      HOOKS["invalidate"], 4)
check("singly: five readings, five distinct height signatures",
      (len(hsigs), len(set(hsigs))), (5, 5))
single_relief = [(a["polygon"], a["height_m"], a["falloff_m"], a["meta"])
                 for a in hf.list_height_areas()]

for area in hf.list_height_areas():
    hf.delete_height_area(area["id"])
h1 = hf.save_height_area({"polygon": square(0, 0), "height_m": 2.0,
                          "falloff_m": 1.0})
reset_hooks()
hsig_before = hf.height_sig()
hres = hf.save_height_areas_bulk(
    [dict(spec) | {"temp_id": f"h{i}"} for i, spec in enumerate(NEW_THREE)],
    [{"id": h1["id"], "updated_at": hf.height_area_stamps()[h1["id"]]}])
hsig_after = hf.height_sig()
check("batch: four relief operations re-raster ONCE", HOOKS["invalidate"], 1)
check("batch: two readings, two distinct height signatures",
      (2, len({hsig_before, hsig_after})), (2, 2))
check("batch: three saved under their temp ids, one deleted, none rejected",
      ([e["temp_id"] for e in hres["saved"]], hres["deleted"] == [h1["id"]],
       hres["rejected"]),
      (["h0", "h1", "h2"], True, []))
check("batch: the relief it leaves is the relief the singles left",
      [(a["polygon"], a["height_m"], a["falloff_m"], a["meta"])
       for a in hf.list_height_areas()], single_relief)

print("\n[6] the prop batch and its cap")

rec = prop_store.create_prop(name="Boulder", width_m=2.0, height_m=3.0,
                             depth_m=1.0)
BOULDER = rec["id"]
gallery = prop_store.model_gallery(BOULDER, 0)
target = gallery.new_path()
target.write_bytes(b"not-a-real-glb")
gallery.select(target.name, "full")

full = wp.save_world_props_bulk(
    [{"prop_id": BOULDER, "x": float(i), "z": 0.0, "temp_id": f"p{i}"}
     for i in range(wp.MAX_WORLD_PROPS)], [])
check("a batch of 500 placements lands whole",
      (len(full["saved"]), full["rejected"], wp.count_world_props()),
      (wp.MAX_WORLD_PROPS, [], wp.MAX_WORLD_PROPS))

victim = full["saved"][0]["world_prop"]["id"]
swap = wp.save_world_props_bulk(
    [{"prop_id": BOULDER, "x": -1.0, "z": 0.0, "temp_id": "fits"},
     {"prop_id": BOULDER, "x": -2.0, "z": 0.0, "temp_id": "over"}],
    [{"id": victim}])
check("one delete makes room for exactly one new placement",
      ([e["temp_id"] for e in swap["saved"]],
       [(r["temp_id"], r["reason"]) for r in swap["rejected"]],
       wp.count_world_props()),
      (["fits"],
       [("over", f"at most {wp.MAX_WORLD_PROPS} world props per world")],
       wp.MAX_WORLD_PROPS))
check("the deleted placement is gone and the new one is there",
      (any(p["id"] == victim for p in wp.list_world_props()),
       any(p["x"] == -1.0 for p in wp.list_world_props()),
       any(p["x"] == -2.0 for p in wp.list_world_props())),
      (False, True, False))

stamped = wp.world_prop_stamps()
moved = [p for p in wp.list_world_props() if p["x"] == -1.0][0]
res = wp.save_world_props_bulk(
    [{"id": moved["id"], "prop_id": BOULDER, "x": 99.0, "z": 0.0,
      "updated_at": "1999-01-01T00:00:00+00:00"}], [])
check("a stale prop upsert is refused like every other object",
      ([r["reason"] for r in res["rejected"]], res["saved"]),
      ([REASON_CHANGED], []))
res = wp.save_world_props_bulk(
    [{"id": moved["id"], "prop_id": BOULDER, "x": 99.0, "z": 0.0,
      "updated_at": stamped[moved["id"]]}], [])
check("...and lands with the stamp it was loaded with",
      ([e["world_prop"]["x"] for e in res["saved"]], res["rejected"]),
      ([99.0], []))

print("\n[7] the three routes over them")

from fastapi import HTTPException  # noqa: E402
from app.routes.world import (_bulk_body,  # noqa: E402
                              _put_height_areas_bulk_sync,
                              _put_terrain_areas_bulk_sync,
                              _put_world_props_bulk_sync)

CHECKED += 1
try:
    _bulk_body(["not", "an", "object"])
    print("  ✗ a non-object body is a 400: no exception")
    FAILURES.append("bulk body 400")
except HTTPException as exc:
    ok = exc.status_code == 400
    print(f"  {'✓' if ok else '✗'} a non-object body is a 400: {exc.status_code}")
    if not ok:
        FAILURES.append("bulk body 400")

for area in terrain.list_areas():
    terrain.delete_area(area["id"])
route = _put_terrain_areas_bulk_sync(
    {"upserts": [{"kind": "grass", "polygon": square(0, 0), "temp_id": "r1"}]})
check("the terrain route answers success with the saved area",
      (route["status"], [e["temp_id"] for e in route["saved"]],
       route["deleted"], route["rejected"]),
      ("success", ["r1"], [], []))
check("an empty body is a success too, not a 400",
      _put_terrain_areas_bulk_sync({}),
      {"status": "success", "saved": [], "deleted": [], "rejected": []})

hroute = _put_height_areas_bulk_sync(
    {"upserts": [{"polygon": square(200, 200), "height_m": 3.0,
                  "falloff_m": 5.0, "temp_id": "r2"}]})
check("the height route answers the step the world has afterwards",
      (hroute["status"], [e["temp_id"] for e in hroute["saved"]],
       hroute["step_m"] > 0),
      ("success", ["r2"], True))

proute = _put_world_props_bulk_sync(
    {"deletes": [{"id": p["id"]} for p in wp.list_world_props()]})
check("the prop route empties the world in one request",
      (proute["status"], len(proute["deleted"]), wp.count_world_props()),
      ("success", wp.MAX_WORLD_PROPS, 0))

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
