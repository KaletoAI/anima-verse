#!/usr/bin/env python3
"""Smoke run: the scene poll's ETag moves when THIS location's scene can
change — and not when an unrelated file is written.

THE FINDING (live server, 2026-11-07). ``GET /play/locations/{id}/scene``
answers ``304`` from an input fingerprint. Its props input was ONE stat over
the whole prop library (``scene_recipe.prop_lib_token``), so generating five
new props — a source image and a sidecar each, placed nowhere — moved the
ETag of all 18 locations a browser had loaded, seven times in six minutes:
93 full answers, each a full recompose, for payloads that had not changed.
Expression images, character models and gallery images were NOT inputs and
moved nothing; the props were the churn.

THE FIX. While ``scene_and_etag`` composes, ``props.recording_reads`` collects
the id of every prop whose directory the composer resolves
(``props._prop_dir`` is the one door to a prop's files). ``scene_etag`` hashes
the other inputs as before plus exactly those directories and the read set
itself. ``scene_fingerprint`` keeps the library-wide token — it is still the
key of ``places`` and ``room_stand``, which compose on their own — and serves
here as the BEFORE: it is what the ETag used to be.

Runs against a THROWAWAY storage directory — no real world, no server, no
LLM/image call. The route function is called directly with a stand-in request.

The seed (hand-built; every expectation below is derived from it):

    prop "crate"    placed in "Warehouse" AND in "Shed" (the shared prop)
    prop "barrel"   placed in "Shed"
    prop "lamp"     a WORLD prop at (50, 50), outside both squares — it
                    reaches a scene only through ``terrain_sig`` (its ground
                    box, ``world_props.prop_boxes``), whose value is cached
    prop "rose"     created during the run, placed nowhere
    location "Warehouse"   a drawn 20 m square, room "hall" (x=-8 z=-8 w=16
                           d=12) holding the crate at (2, 2). No openings, so
                           no door prop; no painted terrain at first.
    location "Shed"        the same square 100 m east, room "hall" holding
                           the barrel at (2, 2) and the crate at (3, 2).

Hand-derived expectations
-------------------------

[0] at rest. Each location is composed until its ETag stops moving (the
    first read of a hand-written sidecar migrates it once — a write into the
    very directory the ETag stats, so the first compose is followed by one
    more; ``smoke_scene_cache.py`` [1] records the same on the old code).
    Then: the read set of Warehouse is exactly {"crate"} and of Shed exactly
    {"barrel", "crate"} — the rooms name no other prop, and the lamp is read
    only inside ``terrain_sig``, which is not recorded (see [5]). The held ETag answers 304.

[1] unrelated writes leave the ETag where it is — for BOTH locations, with
    a 304 to the held tag and 0 compositions — while ``scene_fingerprint``
    (the old ETag) moves wherever the write lands in ``<storage>/props/``:

      a) a NEW prop "rose" (sidecar + source.png)     old moves, new stays
      b) rose's source image regenerated + sidecar    old moves, new stays
      c) an expression image under characters/<c>/    both stay (never an
         input — the reported hypothesis, measured)
      d) a gallery image under world_gallery/<loc>/   both stay
      e) barrel's sidecar edited: Shed's ETag MOVES (barrel is in its read
         set), Warehouse's stays (it is not in Warehouse's).

    And the scene a fresh compose yields after all of it is byte-identical
    to the one the 304 stands for — the 304 hid nothing.

[2] every relevant input still moves Warehouse's ETag, and the next poll
    with the old tag is a 200 that composes once:

      a) the crate's sidecar loses its ``walkable`` tag   (a read prop)
      b) a file appears in the crate's directory          (a read prop)
      c) a second crate is placed                         (the location)
      d) a placement of "ghost", a prop with no directory yet — then the
         directory appears: ``""`` -> its files, so the ETag moves again
      e) a painted area far away                          (terrain_sig)
      f) a file appears in locations/<id>/model3d/        (the models dir)

[3] the key is captured BEFORE the reads. A crate sidecar rewrite that lands
    WHILE the compose runs (injected after the compose, before the route
    returns): the stored key carries the crate's PRE-compose stat, so the next
    poll's ETag differs from it and the scene composes again (1) instead of
    serving a payload that may predate the write.

[4] a library LISTING during a compose records ``props.ALL_PROPS``, and then
    ``scene_etag`` is ``scene_fingerprint`` — the library-wide superset.

[5] the read set does not depend on which caches are warm. Per location,
    composed inside ``props.recording_reads``:
      cold (terrain_sig / world-prop payload / prop token caches dropped),
      warm (right after), warm after composing every other location first,
      warm after composing ALL locations in reverse order
    -> all four equal the hand-derived set: Warehouse {"crate", "ghost"} (its
    layout since [2c]/[2d]), Shed {"barrel", "crate"}.
    And the check is discriminating: a cold ``terrain_sig()`` inside a
    recording block DOES read "lamp" — that is the cache-dependent read
    ``_signature`` now takes under ``props.not_recording``.
    FAILS ON 61dd7ac4 (measured with this file on that commit): cold
    Warehouse ["crate", "ghost", "lamp"] vs warm ["crate", "ghost"], cold
    Shed ["barrel", "crate", "lamp"] vs warm ["barrel", "crate"].

[6] end to end, both kinds of dependency, from warm caches only:
      a) Shed is composed first (the shared crate is warm), then Warehouse;
         the crate's sidecar changes -> Warehouse's ETag moves, 200, 1 compose.
      b) the lamp's primary-variant width changes (its ground box, i.e.
         terrain_sig; the top-level ``width_m`` is not what the box reads) ->
         Warehouse's ETag moves although "lamp" is in no read set: the value
         of ``terrain_sig`` is a fingerprint input of its own.

Usage:  ./.venv/bin/python scripts/smoke_scene_fingerprint_churn.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-churn-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="scene-churn-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.models import terrain as terrain_model  # noqa: E402
from app.models import world_props  # noqa: E402
from app.models.terrain import save_area  # noqa: E402
from app.models.world import (  # noqa: E402
    add_location, get_location_by_id, update_location_position,
    upsert_location)
from app.routes import play as play_routes  # noqa: E402

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


# ── the props ───────────────────────────────────────────────────────────
PROPS = STORAGE / "props"


def write_prop(pid: str, tags, **extra) -> None:
    d = PROPS / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / prop_store.SIDECAR_NAME).write_text(json.dumps({
        "name": pid.title(), "category": "furniture",
        "width_m": 0.8, "depth_m": 0.8, "height_m": 0.6,
        "tags": list(tags), **extra}), encoding="utf-8")
    scene_recipe.invalidate_prop_lib_token()


write_prop("crate", ["walkable"])
write_prop("barrel", [])
write_prop("lamp", [])
world_props.save_world_prop({"id": "wp_lamp", "prop_id": "lamp",
                             "x": 50.0, "z": 50.0})

# ── the world ───────────────────────────────────────────────────────────
SQUARE = {"plan_width_m": 20.0,
          "boundary": [[-10.0, -10.0], [10.0, -10.0],
                       [10.0, 10.0], [-10.0, 10.0]]}
WAREHOUSE = add_location(name="Warehouse", description="churn smoke",
                         rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(WAREHOUSE, 0.0, 0.0)
SHED = add_location(name="Shed", description="churn smoke",
                    rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(SHED, 100.0, 0.0)
PIN = add_location(name="Pin", description="nothing to compose")["id"]
update_location_position(PIN, 200.0, 0.0)


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
_real_compose = scene_recipe.compose_scene
_counts = {"compose": 0}


def _counting_compose(*a, **kw):
    _counts["compose"] += 1
    return _real_compose(*a, **kw)


scene_recipe.compose_scene = _counting_compose


class Req:
    """Just enough of ``fastapi.Request`` for this route: its headers."""

    def __init__(self, if_none_match: str = ""):
        self.headers = ({"if-none-match": if_none_match}
                        if if_none_match else {})


def poll(location_id: str, held: str = ""):
    """One poll through the route: ``(status, etag, compositions)``."""
    _counts["compose"] = 0
    res = play_routes.play_location_scene(location_id, Req(held))
    return res.status_code, res.headers.get("etag"), _counts["compose"]


def etag(location_id: str) -> str:
    return '"' + scene_recipe.scene_etag(get_location_by_id(location_id),
                                         location_id) + '"'


def old(location_id: str) -> str:
    scene_recipe.invalidate_prop_lib_token()   # no 5-second grace: measure
    return scene_recipe.scene_fingerprint(get_location_by_id(location_id),
                                          location_id)


def canonical(location_id: str) -> str:
    """A fresh, uncached composition, canonically dumped."""
    loc = get_location_by_id(location_id)
    plan, building, rooms = scene_recipe.scene_inputs(loc, location_id)
    return json.dumps(_real_compose(loc, plan_width_m=plan,
                                    building_meta=building, room_metas=rooms),
                      sort_keys=True, default=str)


def settle(location_id: str) -> str:
    """Poll until the answer is a 304 to the tag the previous poll handed
    out; returns that tag."""
    held = ""
    for _ in range(4):
        status, tag, _ = poll(location_id, held)
        if status == 304:
            return held
        held = tag
    raise SystemExit(f"{location_id}: the ETag never settled")


def main() -> int:
    print("[0] at rest")
    held = {WAREHOUSE: settle(WAREHOUSE), SHED: settle(SHED)}
    check("Warehouse read set", sorted(scene_recipe._remembered_reads(WAREHOUSE)),
          ["crate"])
    check("Shed read set", sorted(scene_recipe._remembered_reads(SHED)),
          ["barrel", "crate"])
    check("the held Warehouse tag is answered 304, composing nothing",
          poll(WAREHOUSE, held[WAREHOUSE])[0::2], (304, 0))
    scene_before = {lid: canonical(lid) for lid in held}

    print("\n[1] unrelated writes")

    def unrelated(label: str, write, *, old_moves: bool) -> None:
        old_before = {lid: old(lid) for lid in held}
        tick()
        write()
        scene_recipe.invalidate_prop_lib_token()
        for lid, name in ((WAREHOUSE, "Warehouse"), (SHED, "Shed")):
            check(f"{label}: {name} answers 304 with 0 compositions",
                  poll(lid, held[lid])[0::2], (304, 0))
            check(f"{label}: {name}'s old fingerprint moved",
                  old(lid) != old_before[lid], old_moves)

    def new_rose() -> None:
        write_prop("rose", [])
        (PROPS / "rose" / "source.png").write_bytes(b"\x89PNG rose v1")

    def regenerate_rose() -> None:
        (PROPS / "rose" / "source.png").write_bytes(b"\x89PNG rose v2, longer")
        write_prop("rose", [], source_generated_at="2026-11-07T20:32:45+00:00")

    def expression() -> None:
        d = STORAGE / "characters" / "demo" / "expressions"
        d.mkdir(parents=True, exist_ok=True)
        (d / "demo_happy.png").write_bytes(b"\x89PNG happy")

    def gallery() -> None:
        d = STORAGE / "world_gallery" / WAREHOUSE
        d.mkdir(parents=True, exist_ok=True)
        (d / "warehouse_1.png").write_bytes(b"\x89PNG gallery")

    unrelated("a) new prop 'rose', placed nowhere", new_rose, old_moves=True)
    unrelated("b) rose's source image regenerated", regenerate_rose,
              old_moves=True)
    unrelated("c) an expression image", expression, old_moves=False)
    unrelated("d) a gallery image", gallery, old_moves=False)

    tick()
    write_prop("barrel", ["decor"])                       # e)
    check("e) barrel edited: Warehouse answers 304 with 0 compositions",
          poll(WAREHOUSE, held[WAREHOUSE])[0::2], (304, 0))
    status, _, composed = poll(SHED, held[SHED])
    check("e) barrel edited: Shed answers 200 and composes once",
          (status, composed), (200, 1))
    check("the Warehouse scene is byte-identical to the one the 304 stands for",
          canonical(WAREHOUSE) == scene_before[WAREHOUSE], True)

    print("\n[2] relevant inputs still move Warehouse's ETag")

    def relevant(label: str, write) -> None:
        tag = held[WAREHOUSE]
        tick()
        write()
        scene_recipe.invalidate_prop_lib_token()
        check(f"{label}: the ETag moved", etag(WAREHOUSE) != tag, True)
        status, _, composed = poll(WAREHOUSE, tag)
        check(f"{label}: the old tag gets a 200 that composes once",
              (status, composed), (200, 1))
        held[WAREHOUSE] = settle(WAREHOUSE)

    relevant("a) crate loses 'walkable'", lambda: write_prop("crate", []))
    relevant("b) a file in the crate's directory",
             lambda: (PROPS / "crate" / "model_1.json").write_text("{}"))
    relevant("c) a second crate placed",
             lambda: lay_out(WAREHOUSE, ["crate", "crate"]))
    relevant("d1) a placement of 'ghost' (no directory)",
             lambda: lay_out(WAREHOUSE, ["crate", "crate", "ghost"]))
    check("d1) ghost is in the read set although it has no directory",
          "ghost" in scene_recipe._remembered_reads(WAREHOUSE), True)
    relevant("d2) ghost's directory appears",
             lambda: write_prop("ghost", []))
    relevant("e) a painted area 40 m away",
             lambda: save_area({"kind": "water", "z_order": 0, "polygon":
                                [[40.0, 40.0], [50.0, 40.0], [50.0, 50.0]]}))

    def model_file() -> None:
        d = STORAGE / "locations" / WAREHOUSE / "model3d"
        d.mkdir(parents=True, exist_ok=True)
        (d / "selection.json").write_text("{}")

    relevant("f) a file in the location's model3d dir", model_file)

    print("\n[3] the key is captured before the reads")
    real = scene_recipe._compose_stored

    def compose_then_write(location, location_id):
        out = real(location, location_id)
        tick()
        write_prop("crate", ["late"])   # lands after the read, before return
        return out

    scene_recipe.invalidate_scene_cache(WAREHOUSE)   # force a compose
    scene_recipe._compose_stored = compose_then_write
    try:
        _, issued, _ = poll(WAREHOUSE, '"stale"')
    finally:
        scene_recipe._compose_stored = real
    check("the issued tag is not the post-write ETag", issued != etag(WAREHOUSE),
          True)
    status, _, composed = poll(WAREHOUSE, issued)
    check("so the next poll recomposes", (status, composed), (200, 1))
    held[WAREHOUSE] = settle(WAREHOUSE)

    print("\n[4] a library listing falls back to the library-wide token")

    def compose_listing(location, location_id):
        prop_store._all_prop_ids()
        return real(location, location_id)

    scene_recipe.invalidate_scene_cache(WAREHOUSE)
    scene_recipe._compose_stored = compose_listing
    try:
        poll(WAREHOUSE, '"stale"')
    finally:
        scene_recipe._compose_stored = real
    check("ALL_PROPS was recorded",
          prop_store.ALL_PROPS in scene_recipe._remembered_reads(WAREHOUSE),
          True)
    check("scene_etag == scene_fingerprint",
          etag(WAREHOUSE).strip('"'), old(WAREHOUSE))

    print("\n[5] the read set does not depend on warm caches")
    # Warehouse holds crate, crate, ghost since [2c]/[2d].
    expected = {WAREHOUSE: ["crate", "ghost"], SHED: ["barrel", "crate"]}
    order = [WAREHOUSE, SHED, PIN]

    def reads_of(lid: str):
        with prop_store.recording_reads() as seen:
            real(get_location_by_id(lid), lid)
        return sorted(seen)

    def make_cold() -> None:
        terrain_model._sig_cache = (None, "")
        world_props._payload_cache = (None, [], "")
        scene_recipe.invalidate_prop_lib_token()

    for lid, name in ((WAREHOUSE, "Warehouse"), (SHED, "Shed")):
        make_cold()
        cold = reads_of(lid)
        warm = reads_of(lid)
        for other in order:
            if other != lid:
                real(get_location_by_id(other), other)
        after_others = reads_of(lid)
        for other in reversed(order):
            real(get_location_by_id(other), other)
        after_reverse = reads_of(lid)
        check(f"{name}: cold / warm / after the others / after all reversed",
              (cold, warm, after_others, after_reverse),
              (expected[lid],) * 4)
    make_cold()
    with prop_store.recording_reads() as seen:
        terrain_model.terrain_sig()
    check("a cold terrain_sig() itself reads the lamp (the check bites)",
          "lamp" in seen, True)

    print("\n[6] end to end from warm caches")
    scene_recipe.invalidate_scene_cache()
    settle(SHED)                      # the shared crate is composed first
    held[WAREHOUSE] = settle(WAREHOUSE)
    tag = held[WAREHOUSE]
    tick()
    write_prop("crate", ["walkable"], width_m=1.2)
    check("a) the shared crate changes: Warehouse's ETag moved",
          etag(WAREHOUSE) != tag, True)
    check("a) ...and the old tag gets a 200 that composes once",
          poll(WAREHOUSE, tag)[0::2], (200, 1))
    held[WAREHOUSE] = settle(WAREHOUSE)
    tag = held[WAREHOUSE]
    reads = scene_recipe._remembered_reads(WAREHOUSE)
    check("b) the lamp is in no read set (and no library fallback)",
          ("lamp" in reads, prop_store.ALL_PROPS in reads), (False, False))
    tick()
    write_prop("lamp", [], model_variants=[{"stem": "model", "active": True,
                                           "width_m": 3.0, "depth_m": 1.0,
                                           "height_m": 1.0}])
    check("b) the lamp's ground box changes: Warehouse's ETag moved",
          etag(WAREHOUSE) != tag, True)
    check("b) ...and the old tag gets a 200 that composes once",
          poll(WAREHOUSE, tag)[0::2], (200, 1))

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
