#!/usr/bin/env python3
"""Smoke run for IMG-10: the scene poll is cheap — ETag/304 and an input
fingerprint instead of a full compose per poll.

``GET /play/locations/{id}/scene`` is polled by every connected 3D client, once
a minute per cached location (``client3d/src/scene/sceneRecipe.ts``:
``SceneLibrary.sweep``), and the client compares exactly ONE field of the
answer: ``signature``. That field is built LAST, after the whole composition,
and the route sent no cache headers at all — so the unchanged case (nearly
every case) paid a full compose AND a full serialization of a payload that
carries the baked walking lattices.

Two additions, neither of which changes the payload:

  * ``scene_recipe.scene_for_location`` holds the composed payload per
    location under ``scene_fingerprint`` — a hash over the INPUTS (the
    location record, the terrain and relief signatures, the surface library,
    the place-type catalog, the season, the code version, plus one ``stat``
    per file in the props and the location's model directory).
  * the route sends ``ETag: "<fingerprint>"`` + ``Cache-Control: no-cache``
    and answers ``304`` to a matching ``If-None-Match`` — the fingerprint, not
    the payload's ``signature``, because it is known BEFORE anything is
    composed and because it is the stricter of the two (see [2b]).

Runs against a THROWAWAY storage directory — it never touches a real world,
never starts a server and makes no LLM/image call. The route function is
called DIRECTLY with a stand-in request object; nothing is served over HTTP.

The seed (hand-built, so every expectation below is derived from it):

    prop "crate"          sidecar-only prop, tagged ``walkable``
    location "Warehouse"  a drawn 20 m square (corners ±10), one room
                          "hall" with layout x=-8 z=-8 w=16 d=12 and one
                          placement of "crate" at (2, 2)
    location "Pin"        placed, but no room layout, no outline, no model
                          — the legacy auto-grid case

Hand-derived expectations
-------------------------

[1] the cache. Two calls of ``scene_for_location`` with nothing changed in
    between:

      call 1 -> 1 compose_scene, 1 scene_inputs
      call 2 -> 0 compose_scene, 0 scene_inputs, and the very same payload
                object (it is handed out, not copied — every caller
                serializes it and none writes to it)

    Before the fix there was no cache at all, so call 2 cost exactly what
    call 1 cost: that is the "fails before" half, and it is measured here by
    driving the pre-fix path (``scene_inputs`` + ``compose_scene``, the two
    calls the route used to make) side by side.

[2] every input invalidates. One change at a time, each followed by a call
    that must compose again (+1):

      a) a LOCATION write — the room layout gains a second placement. The
         payload and its ``signature`` both move.
      b) a PROP edit — the crate's sidecar loses its ``walkable`` tag, the
         very field ``_prop_models`` reads off the record. The payload moves
         (the two crates stop carrying ``walkable``) and ``signature`` moves
         with it: since the superset round the flag of every placed prop is a
         signature input (``_signature``'s ``walkable_props``). It used to be
         a GAP — no room-recipe signature covers a prop's tags — and it is
         guarded in ``scripts/smoke_scene_signature_superset.py`` now.
         Props are still the one input with no signature of their own, which
         is what the fingerprint's per-file ``stat`` over
         ``<storage>/props/<id>/`` is for.
      c) a TERRAIN change FAR AWAY — a painted water area at (40…50, 40…50),
         nowhere near the 20 m square. The fingerprint is a deliberate
         SUPERSET, so this recomposes; the payload is byte-identical apart
         from its ``signature``, which moves with the painted world
         (``terrain_sig`` covers the world, not a bounding box) — a superset
         may, and that is the price of never being stale.
      d) a TERRAIN change UNDER the location — water painted over the whole
         square. ``floor_plan`` gains its ``map_water`` reference, so the
         payload really moves, and ``signature`` moves with it: the painted
         terrain is a signature input since the superset round. Second
         former gap, same conclusion as (b).

    WHAT THE FINGERPRINT-ETag PRESERVES. Both gaps used to be papered over by
    the poll itself: the client refetched the whole payload every minute and
    stored it, remounting only on a ``signature`` change. A ``304`` keyed on
    ``signature`` would have taken that away. Keyed on the fingerprint it does
    not: whenever the payload can have changed, the fingerprint has moved and
    a full answer goes out — the client stores it and remounts only where the
    signature says so. The ETag stays the FINGERPRINT even now that the two
    gaps are closed: it is known before anything is composed, so a ``304``
    costs no composition, and it is the stricter of the two.

[3] the route. ``play_location_scene`` with a stand-in request:

      no If-None-Match          -> 200, ETag == '"<fingerprint>"',
                                   Cache-Control "no-cache", body = payload
      If-None-Match = that ETag -> 304, no body, same two headers
      If-None-Match = stale     -> 200 again
      after a location write    -> the ETag has moved, so the client's old
                                   tag yields 200 with the new scene
      the location with nothing to compose -> 404 ("No scene")
      an unknown id                        -> 404 ("Location not found")

[4] the DRAFT preview stays uncached (``POST /play/scene-preview``): two
    identical calls compose twice. A draft has no stored inputs to
    fingerprint, so caching it would be caching a guess.

Usage:  ./.venv/bin/python scripts/smoke_scene_cache.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-cache-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="scene-cache-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.models.terrain import save_area  # noqa: E402
from app.models.world import (  # noqa: E402
    add_location, get_location_by_id, update_location_position,
    upsert_location)
from app.routes import play as play_routes  # noqa: E402

FAILURES = []
CHECKED = 0


def without_sig(payload: dict) -> str:
    """The payload as canonical JSON WITHOUT its own ``signature`` field — the
    dump that answers "did anything ELSE move?"."""
    return json.dumps({k: v for k, v in payload.items() if k != "signature"},
                      sort_keys=True, default=str)


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the prop ────────────────────────────────────────────────────────────
CRATE = "crate"
CRATE_DIR = STORAGE / "props" / CRATE
CRATE_DIR.mkdir(parents=True, exist_ok=True)


def write_crate(tags) -> None:
    (CRATE_DIR / prop_store.SIDECAR_NAME).write_text(json.dumps({
        "name": "Crate", "category": "furniture",
        "width_m": 0.8, "depth_m": 0.8, "height_m": 0.6,
        "tags": list(tags)}), encoding="utf-8")


write_crate(["walkable"])

# ── the world ───────────────────────────────────────────────────────────
WAREHOUSE = add_location(name="Warehouse", description="scene cache smoke",
                         rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(WAREHOUSE, 0.0, 0.0)
PIN = add_location(name="Pin", description="nothing to compose")["id"]
update_location_position(PIN, 100.0, 0.0)


def shape(placements) -> None:
    """The warehouse's drawn square plus the hall's layout with ``placements``
    crates in it."""
    loc = get_location_by_id(WAREHOUSE)
    loc["map3d"] = {"plan_width_m": 20.0,
                    "boundary": [[-10.0, -10.0], [10.0, -10.0],
                                 [10.0, 10.0], [-10.0, 10.0]]}
    loc["rooms"][0]["layout"] = {
        "x": -8, "y": -8, "w": 16, "d": 12,
        "props": [{"id": f"c{i}", "prop_id": CRATE,
                   "at": [2.0 + i, 2.0], "yaw": 0}
                  for i in range(placements)]}
    upsert_location(loc)


shape(1)

# ── the counters ────────────────────────────────────────────────────────
_real_compose = scene_recipe.compose_scene
_real_inputs = scene_recipe.scene_inputs
_counts = {"compose": 0, "inputs": 0}


def _counting_compose(*a, **kw):
    _counts["compose"] += 1
    return _real_compose(*a, **kw)


def _counting_inputs(*a, **kw):
    _counts["inputs"] += 1
    return _real_inputs(*a, **kw)


scene_recipe.compose_scene = _counting_compose
scene_recipe.scene_inputs = _counting_inputs



def counted(fn, *args, **kwargs):
    """``fn(*args)`` with compose_scene / scene_inputs calls counted."""
    _counts["compose"] = _counts["inputs"] = 0
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    dt = time.perf_counter() - t0
    return out, dict(_counts), dt


class Req:
    """Just enough of ``fastapi.Request`` for this route: its headers."""

    def __init__(self, if_none_match: str = ""):
        self.headers = ({"if-none-match": if_none_match}
                        if if_none_match else {})


def scene(location_id: str = WAREHOUSE):
    return scene_recipe.scene_for_location(get_location_by_id(location_id),
                                           location_id)


def main() -> int:
    print("[1] the cache: the second call composes nothing")
    first, c1, dt1 = counted(scene, WAREHOUSE)
    second, c2, dt2 = counted(scene, WAREHOUSE)
    check("the scene exists", isinstance(first, dict), True)
    check("call 1 composes once", c1, {"compose": 1, "inputs": 1})
    check("call 2 composes nothing", c2, {"compose": 0, "inputs": 0})
    check("…and hands out the very same payload", second is first, True)
    check("one crate in the scene",
          len([m for m in first["models"] if m.get("role") == "prop"]), 1)
    print(f"  --  {dt1 * 1000:.1f} ms (compose)  ->  {dt2 * 1000:.1f} ms "
          f"(fingerprint only)")
    # What the route used to do, for the record: inputs + compose, every time.
    _, c_old, dt_old = counted(
        lambda: _real_compose(get_location_by_id(WAREHOUSE),
                              **dict(zip(("plan_width_m", "building_meta",
                                          "room_metas"),
                                         _real_inputs(
                                             get_location_by_id(WAREHOUSE),
                                             WAREHOUSE)))))
    print(f"  --  the pre-fix path (no cache) costs {dt_old * 1000:.1f} ms "
          f"per poll, every poll")

    print("\n[2] every input invalidates")
    sig0 = first["signature"]

    shape(2)                       # (a) a location write
    after_loc, c3, _ = counted(scene, WAREHOUSE)
    check("a location write composes again", c3["compose"], 1)
    check("…and moves the signature", after_loc["signature"] != sig0, True)
    check("…with the second crate in it",
          len([m for m in after_loc["models"] if m.get("role") == "prop"]), 2)

    check("…the two crates are walkable before the edit",
          [m.get("walkable") for m in after_loc["models"]
           if m.get("role") == "prop"], [True, True])

    write_crate(["decor"])         # (b) a prop edit
    after_prop, c4, _ = counted(scene, WAREHOUSE)
    check("a prop edit composes again", c4["compose"], 1)
    check("…the crates are no longer walkable",
          [m.get("walkable") for m in after_prop["models"]
           if m.get("role") == "prop"], [None, None])
    # …and `signature` moves with it (see the docstring, [2b]): the walkable
    # flag of every placed prop is a signature input since the superset round.
    check("…and `signature` moves with it — the closed gap",
          after_prop["signature"] != after_loc["signature"], True)

    save_area({"kind": "water",    # (c) a terrain change far away
               "polygon": [[40.0, 40.0], [50.0, 40.0], [50.0, 50.0]],
               "z_order": 0})
    far, c5, _ = counted(scene, WAREHOUSE)
    check("a terrain change composes again (the superset)", c5["compose"], 1)
    # Everything BUT the signature: the painted world is a signature input, so
    # a lake 40 m away moves the hash without moving a byte of the scene. A
    # superset may — the dump that answers "did anything else move?" must not
    # contain the answer.
    check("…and 40 m away it changes nothing in the scene",
          without_sig(far) == without_sig(after_prop), True)

    save_area({"kind": "water",    # (d) water UNDER the location
               "polygon": [[-12.0, -12.0], [12.0, -12.0],
                           [12.0, 12.0], [-12.0, 12.0]],
               "z_order": 1})
    under, c5b, _ = counted(scene, WAREHOUSE)
    check("water under the square composes again", c5b["compose"], 1)
    check("…and the floor plan names it",
          bool((under["floor_plan"] or [{}])[0].get("map_water")), True)
    # …and `signature` moves here too: the painted terrain is an input of
    # `_signature` since the superset round. Second closed gap, same
    # conclusion as (b).
    check("…and `signature` moves again",
          under["signature"] != far["signature"], True)
    check("…because the payload really moved",
          without_sig(under) != without_sig(far), True)

    _, c6, _ = counted(scene, WAREHOUSE)
    check("and it is cached again right after", c6["compose"], 0)

    print("\n[3] the route: ETag and 304")
    res200 = play_routes.play_location_scene(WAREHOUSE, Req())
    etag = ('"' + scene_recipe.scene_fingerprint(
        get_location_by_id(WAREHOUSE), WAREHOUSE) + '"')
    check("200 carries the input fingerprint as ETag",
          res200.headers.get("etag"), etag)
    check("…and asks for revalidation",
          res200.headers.get("cache-control"), "no-cache")
    check("…and really is the payload",
          json.loads(res200.body)["signature"], under["signature"])
    res304 = play_routes.play_location_scene(WAREHOUSE, Req(etag))
    check("a matching If-None-Match is 304", res304.status_code, 304)
    check("…with no body at all", len(res304.body), 0)
    check("…and the same two headers",
          (res304.headers.get("etag"), res304.headers.get("cache-control")),
          (etag, "no-cache"))
    stale = play_routes.play_location_scene(WAREHOUSE, Req('"nonsense"'))
    check("a stale tag is answered in full", stale.status_code, 200)

    shape(3)
    moved = play_routes.play_location_scene(WAREHOUSE, Req(etag))
    check("after a write the old tag no longer matches", moved.status_code,
          200)
    check("…and the new ETag is the new fingerprint",
          moved.headers.get("etag"),
          '"' + scene_recipe.scene_fingerprint(
              get_location_by_id(WAREHOUSE), WAREHOUSE) + '"')
    check("…carrying the scene with three crates",
          len([m for m in json.loads(moved.body)["models"]
               if m.get("role") == "prop"]), 3)

    for label, loc_id, detail in (("nothing to compose", PIN, "No scene"),
                                  ("unknown id", "nope",
                                   "Location not found")):
        try:
            play_routes.play_location_scene(loc_id, Req())
            check(f"{label} -> 404", "no exception", detail)
        except HTTPException as e:
            check(f"{label} -> 404", (e.status_code, e.detail), (404, detail))
    check("scene_for_location says None for it", scene(PIN), None)

    print("\n[4] the draft preview stays uncached")
    draft = {"id": WAREHOUSE, "terrain": "",
             "map3d": {"plan_width_m": 20.0,
                       "boundary": [[-10.0, -10.0], [10.0, -10.0],
                                    [10.0, 10.0], [-10.0, 10.0]]},
             "rooms": [{"id": "hall", "name": "Hall",
                        "layout": {"x": -8, "y": -8, "w": 16, "d": 12}}]}
    _, p1, _ = counted(play_routes._play_scene_preview_sync, None, draft)
    _, p2, _ = counted(play_routes._play_scene_preview_sync, None, draft)
    check("preview call 1 composes", p1["compose"], 1)
    check("preview call 2 composes again", p2["compose"], 1)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
