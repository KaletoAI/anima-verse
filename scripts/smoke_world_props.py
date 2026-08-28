#!/usr/bin/env python3
"""Smoke run for the WORLD PROPS of the world plane (§ A9a).

Checks ``app/models/world_props.py`` end to end without a server: the CRUD and
its validation, the 500-cap, the worldmap payload block, and the variant
formula against numbers derived BY HAND here (§ B5a — never recorded from an
implementation run).

Runs against a THROWAWAY storage directory; it never touches a real world.

THE SEED (hand-built, so every expectation below follows from it):

    prop "Boulder"  — ONE active variant with a mesh  (stem `model`)
    prop "Fence"    — TWO active variants with meshes (`model`, `model-v2`)
    prop "Ghost"    — a record with NO mesh at all
    prop "Doomed"   — one mesh; deleted again in section [6]

    dims of every prop: width 2.0, height 3.0, depth 1.0  ->  max_m = 3.0
    rotation of "Fence": {x: 0, y: 90, z: 0}

HAND-DERIVED EXPECTATIONS

  [1] sanitize / CRUD
        x = 12.345          -> 12.35   (rounded to centimetres)
        z = -40.0           -> -40.0
        yaw_deg = 370.0     -> 10.0    (a full turn is the same turn)
        yaw_deg = -15.0     -> 345.0
        offset_y = 99.0     -> 50.0    (clamped to MAX_OFFSET_Y)
        offset_y = -99.0    -> -50.0
        variant absent      -> None    ("let the formula decide")
        variant = 2         -> 2
        unknown prop_id     -> ValueError
        x = NaN / 1e9       -> ValueError
        variant = -1        -> ValueError
        update keeps the id and does NOT create a second row

        and the PUT's rule (must_exist=True, core.bulk_edit.GoneError):
          on a stored id      -> replaces it, still one row
          on an unknown id    -> GoneError, and nothing is created
          on an id a DELETE removes BETWEEN the call and the write (injected
          through the sanitizer, which runs in exactly that window)
                              -> GoneError, and the row stays gone. The old
                                 check-then-write (world_prop_exists in the
                                 route, upsert in the model) resurrected it.

  [2] the variant formula   variant_index(id, n) = int(md5(id)[:8], 16) mod n

        md5 of the four ids used here, first 8 hex digits and their value:

          wp_00000001  9b65e854  2607147092
          wp_1a2b3c4d  e3f1ba37  3824269879
          wp_deadbeef  f33a24d6  4080674006
          wp_c0ffee01  ee5538df  3998562527

        2607147092 = 3·869049030 + 2        -> mod 3 = 2 ;  mod 2 = 0
        3824269879 = 3·1274756626 + 1       -> mod 3 = 1 ;  mod 2 = 1
        4080674006 = 3·1360224668 + 2       -> mod 3 = 2 ;  mod 2 = 0
        3998562527 = 3·1332854175 + 2       -> mod 3 = 2 ;  mod 2 = 1

        (the mod-2 column is the low bit of the value: even, odd, even, odd)

        n = 0 or junk -> 0, never a crash: a prop with nothing to choose from
        still has to render its primary variant.

  [3] the payload block (§ A9a)
        - a placement of "Boulder" carries `variants` and NO `model_variants`
          (one variant is one variant — the same fact twice would ride in
          every payload of every world)
        - a placement of "Fence" carries `model_variants` with 2 entries and
          a resolved `variant`; the FIRST entry keeps the bare URL, the second
          carries `?variant=1`
        - `max_m` = 3.0 (largest real edge) and `measure` = "xyz"
        - `fix_euler` of "Fence" = {x: 0, y: 90, z: 0}
        - a placement of "Ghost" (no mesh) is DROPPED from the block
        - `ground_offset_m` (the sink of the VARIANT the row draws — the
          prop's own until 2026-08-25) rides the row ONLY when it is not 0.0 —
          the client seats a world prop itself, so the bottom is
          `heightAt(x, z) + offset_y + ground_offset_m`. It is derived per poll
          like `max_m`: setting variant 0 to −0.2 changes the rows and the
          signature without a single placement being rewritten, and the
          placement's own `offset_y` stays what it was. A row that draws
          ANOTHER variant reads THAT variant's sink: the "Fence" placement
          resolves to variant 1, so setting variant 1 to −0.4 and variant 0 to
          −0.2 must put −0.4 on it, never −0.2.
        - nothing is fogged away: the block is identical for the avatar view
          and for the admin view of `build_worldmap_payload`

  [4] the variant of a stored index wraps MODULO
        "Fence" has 2 variants; a placement stored with `variant = 5`
        renders 5 mod 2 = 1 — a stored index must not make a prop vanish when
        an admin deletes a mesh.

  [5] the cap
        MAX_WORLD_PROPS = 500, WARN_WORLD_PROPS = 200.
        Seeded to exactly 500 rows -> the 501st CREATE raises ValueError,
        while an UPDATE of an existing row still goes through (a full world
        must keep the right to move what it has).

  [6] a deleted prop takes its placements with it
        `delete_world_props_of` removes exactly the rows of that prop and
        reports the count; the others are untouched.

  [7] the signature
        `world_props_sig` is stable over a re-read and MOVES when a placement
        moves — that is the whole contract a client rebuilds on. Since E2c it
        must move with the CLOCK as well: the rows carry the prop's ACTIVE
        variants, and a season-tagged one leaves and re-enters them without a
        single DB row changing. Hand fixture (the shipped calendar, 4 × 30
        days, season starts 0/30/60/90): day-of-year 35 = day 5 of summer,
        95 = day 5 of winter. A fence with an untagged second variant answers
        identically in both; tag that variant "Winter" and summer publishes no
        `model_variants` at all while winter publishes two — and the two
        signatures differ. Clearing the tag restores the untagged answer byte
        for byte, which is the inertness rule.

  [8] the EDITOR listing (`GET /world/world-props`)
        A second shape beside the payload block, and deliberately so: the map
        editor has to see what the renderers cannot draw.
          - the two cap numbers ride along, so the badge holds no ceiling of
            its own
          - `name` and `variant_count` come from the library
          - `missing` is TRUE only when the prop record itself is gone — a
            prop that merely has no mesh yet is a normal placement waiting
            for a generation, not a broken one

  [9] the GROUND BOXES (§ A9b, user finding 2026-08-23)
        `prop_boxes` is the block both scatter samplers keep clear — one row
        per placement, `{id, x, z, yaw_deg, half_w, half_d}` in world metres,
        served by `GET /play/terrain` (3D client) and `GET /world/world-props`
        (map editor) out of this one function. The half-extents are half the
        prop's REAL width and depth plus `PROP_BOX_MARGIN_M` = 0.25 on both.
        Every seeded prop here is 2.0 wide and 1.0 deep:

            half_w = 2.0 / 2 + 0.25 = 1.25
            half_d = 1.0 / 2 + 0.25 = 0.75

        and the 4.0 x 2.0 sapling of this section gives 2.25 / 1.25.

        - a placement whose prop RECORD is gone has no size and no box (it
          renders nothing either)
        - a placement whose prop merely has no MESH yet DOES get its box: the
          author placed it and that ground is spoken for
        - a placement inside a placed location's boundary gets no box — the
          outline already excludes the scatter over its whole area, and the
          box would be the same answer a second time in every payload. Fixture:
          a location at (100, 100) with a 20 m square boundary, i.e. world
          90..110 in both axes; a prop at (105, 100) is inside it, one at
          (130, 100) is not.
        - `terrain_sig` MOVES when a box moves: that is the signature the 3D
          client refetches its ground on, and nothing else in the worldmap
          poll covers a world prop's geometry.

  [10] A VARIANT MAY BE ITS OWN SIZE (2026-08-24)
        A variant may override `width_m`/`depth_m`/`height_m` of its prop, and
        a placement is scaled to — and keeps clear the ground of — the variant
        it really shows. Fixture: a pine of 2.0 x 1.0 x 3.0 m whose variant 1
        is the grown tree, 4.0 m wide and 6.0 m tall (depth inherited):

            row of variant 0   max_m = max(2.0, 3.0, 1.0) = 3.0
            row of variant 1   max_m = max(4.0, 6.0, 1.0) = 6.0
            box of variant 0   half_w = 2.0/2 + 0.25 = 1.25 ; half_d = 0.75
            box of variant 1   half_w = 4.0/2 + 0.25 = 2.25 ; half_d = 0.75

        A placement without a stored variant is resolved by the formula of [2]
        and its box follows THAT mesh: `wp_deadbeef` gives 4080674006 mod 2 = 0,
        the sapling, so 1.25.

  [11] ONE RESOLUTION RULE (`resolved_variant`, 2026-08-24)
        Which mesh a placement shows is asked by three consumers — the payload
        row, the ground box and the editor listing — and answered by ONE
        function, so a variant picked in the map editor cannot mean one mesh
        in the 3D client and another in the scatter. The rule:

            an AUTHORED index wins        variant = 1  -> 1
            otherwise the formula of [2]  variant = -  -> md5 mod count
            and either way it WRAPS       variant = 5, count 2 -> 1
            (never clamps, so switching a mesh off never hides a prop)
            junk falls back to the formula (the sanitizer refuses it on the
            way IN; this is the last line for a row written past it)
            count 0 has nothing to choose from      -> 0

        Hand-derived from md5("wp_deadbeef")[:8] = 4080674006: mod 2 = 0,
        mod 3 = 2, and −1 mod 2 = 1 (Python's modulo answers non-negative).

        End to end on the pine of [10]: pinning its auto placement to the
        grown variant moves the payload row to `max_m` 6.0 and its box to
        half_w 2.25 in the same breath. And because a placement stores a
        POSITION in the PUBLISHED list, switching variant 0 off leaves one
        position that IS the grown tree — every placement of the pine then
        keeps 2.25 clear, the sapling-pinned one included.

        The editor listing carries what the picker needs and nothing it would
        have to compute: `variant_indices` (the store index behind each
        position, so its label reads like the prop page's chip) and
        `variant_auto` (what "Auto" resolves to for THIS placement, whatever
        is stored — an unsaved draft switching back to Auto can name its mesh
        before the save).

Usage:  ./.venv/bin/python scripts/smoke_world_props.py
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="world-props-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="world-props-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models import world_props as wp  # noqa: E402
from app.routes.world import get_world_props_route  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def raises(label: str, fn) -> None:
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({e})")
        return
    print(f"  ✗ {label}: no ValueError")
    FAILURES.append(label)


def raises_gone(label: str, fn) -> None:
    """The singular PUT's refusal — ``core.bulk_edit.GoneError``, nothing else
    (a ValueError here would be a 400 and would hide the resurrection)."""
    global CHECKED
    CHECKED += 1
    from app.core.bulk_edit import GoneError
    try:
        fn()
    except GoneError as e:
        print(f"  ✓ {label}: GoneError({e})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected GoneError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no GoneError")
    FAILURES.append(label)


def seed_prop(name: str, variants: int = 1, rotation=None) -> str:
    """A prop record with `variants` active variants, each carrying ONE mesh.

    The bytes are not a real GLB — nothing here parses one. What matters is
    that the gallery HAS a selected file per variant, because that is what
    ``active_variant_tiers`` reads and what decides whether a placement
    renders at all.
    """
    rec = prop_store.create_prop(name=name, width_m=2.0, height_m=3.0,
                                 depth_m=1.0)
    pid = rec["id"]
    for i in range(variants):
        if i > 0:
            prop_store.add_variant(pid)
        g = prop_store.model_gallery(pid, i)
        target = g.new_path()
        target.write_bytes(b"not-a-real-glb")
        g.select(target.name, "full")
    if rotation:
        # The fix is the FILE's (spec-bild-props-v2.md E1): the primary
        # variant's active full mesh carries it, so it is dialled once the
        # mesh exists — and the world-prop row reads that primary file.
        prop_store.set_rotation(pid, rotation)
    return pid


BOULDER = seed_prop("Boulder")
FENCE = seed_prop("Fence", variants=2, rotation={"x": 0, "y": 90, "z": 0})
GHOST = prop_store.create_prop(name="Ghost", width_m=1.0, height_m=1.0,
                               depth_m=1.0)["id"]
DOOMED = seed_prop("Doomed")

print("\n[0] the seed")
check("Boulder active variants with a mesh",
      len(prop_store.active_variant_tiers(BOULDER)), 1)
check("Fence active variants with a mesh",
      len(prop_store.active_variant_tiers(FENCE)), 2)
check("Ghost active variants with a mesh",
      len(prop_store.active_variant_tiers(GHOST)), 0)

print("\n[1] sanitize / CRUD")
a = wp.save_world_prop({"prop_id": BOULDER, "x": 12.345, "z": -40.0,
                        "yaw_deg": 370.0, "offset_y": 99.0})
check("x rounded to centimetres", a["x"], 12.35)
check("z untouched", a["z"], -40.0)
check("yaw wrapped", a["yaw_deg"], 10.0)
check("offset clamped up", a["offset_y"], 50.0)
check("variant absent means auto", a["variant"], None)

b = wp.save_world_prop({"prop_id": FENCE, "x": 0.0, "z": 0.0,
                        "yaw_deg": -15.0, "offset_y": -99.0, "variant": 2})
check("negative yaw wrapped", b["yaw_deg"], 345.0)
check("offset clamped down", b["offset_y"], -50.0)
check("explicit variant kept", b["variant"], 2)

check("two rows stored", wp.count_world_props(), 2)
wp.save_world_prop({**a, "x": 5.0})
check("update keeps the row count", wp.count_world_props(), 2)
check("update moved the row",
      [r["x"] for r in wp.list_world_props() if r["id"] == a["id"]], [5.0])
check("a replacing write updates the row",
      wp.save_world_prop({**a, "x": 6.0}, must_exist=True)["x"], 6.0)
check("...and there is still one of it", wp.count_world_props(), 2)
raises_gone("a replacing write on an unknown id",
            lambda: wp.save_world_prop({**a, "id": "wp_nope"},
                                       must_exist=True))
check("...and it created nothing", wp.count_world_props(), 2)

# THE RACE the 404 exists for: the store is an upsert, so a stale PUT that
# arrives after a DELETE would put the placement back under its old id. The
# rule sits in the WRITE (an UPDATE matching no row), not in a lookup before
# it — a check-then-write leaves exactly this window, and since the route runs
# in the threadpool it is a real one. The delete is injected through the
# sanitizer, which runs after the route entered and before the transaction.
_racer = wp.save_world_prop({"prop_id": BOULDER, "x": 30.0, "z": 30.0})
_real_sanitize = wp.sanitize_world_prop


def _delete_mid_write(raw):
    """Stands in for the sanitizer: deletes the row on its way past."""
    wp.delete_world_prop(_racer["id"])
    return _real_sanitize(raw)


wp.sanitize_world_prop = _delete_mid_write
try:
    raises_gone("PUT while a DELETE lands mid-write",
                lambda: wp.save_world_prop({**_racer, "x": 31.0},
                                           must_exist=True))
finally:
    wp.sanitize_world_prop = _real_sanitize
check("the raced placement was NOT resurrected",
      [r["id"] for r in wp.list_world_props()].count(_racer["id"]), 0)
check("two rows again", wp.count_world_props(), 2)

raises("unknown prop", lambda: wp.save_world_prop({"prop_id": "nope",
                                                   "x": 0, "z": 0}))
raises("NaN coordinate", lambda: wp.save_world_prop(
    {"prop_id": BOULDER, "x": float("nan"), "z": 0}))
raises("coordinate out of range", lambda: wp.save_world_prop(
    {"prop_id": BOULDER, "x": 1e9, "z": 0}))
raises("negative variant", lambda: wp.save_world_prop(
    {"prop_id": BOULDER, "x": 0, "z": 0, "variant": -1}))

print("\n[2] the variant formula")
IDS = ["wp_00000001", "wp_1a2b3c4d", "wp_deadbeef", "wp_c0ffee01"]
check("md5 prefixes", [hashlib.md5(i.encode()).hexdigest()[:8] for i in IDS],
      ["9b65e854", "e3f1ba37", "f33a24d6", "ee5538df"])
check("as integers", [int(hashlib.md5(i.encode()).hexdigest()[:8], 16)
                      for i in IDS],
      [2607147092, 3824269879, 4080674006, 3998562527])
check("mod 3", [wp.variant_index(i, 3) for i in IDS], [2, 1, 2, 2])
check("mod 2", [wp.variant_index(i, 2) for i in IDS], [0, 1, 0, 1])
check("nothing to choose from", wp.variant_index("wp_00000001", 0), 0)
check("junk count", wp.variant_index("wp_00000001", "x"), 0)

print("\n[3] the payload block")
for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])
one = wp.save_world_prop({"prop_id": BOULDER, "x": 1.0, "z": 2.0,
                          "yaw_deg": 45.0})
two = wp.save_world_prop({"prop_id": FENCE, "x": 3.0, "z": 4.0,
                          "yaw_deg": 0.0, "variant": 1})
wp.save_world_prop({"prop_id": GHOST, "x": 9.0, "z": 9.0})
rows = wp.payload_rows()
check("the mesh-less prop is dropped", len(rows), 2)
by_id = {r["id"]: r for r in rows}
r1 = by_id[one["id"]]
r2 = by_id[two["id"]]
check("one variant carries no model_variants", "model_variants" in r1, False)
check("one variant carries no variant index", "variant" in r1, False)
check("primary tier map", r1["variants"],
      {"full": f"/assets/props/{BOULDER}/model?tier=full"})
check("max_m is the largest real edge", r1["max_m"], 3.0)
check("measure", r1["measure"], "xyz")
check("two variants are published", len(r2["model_variants"]), 2)
check("the primary keeps the bare URL", r2["model_variants"][0],
      {"full": f"/assets/props/{FENCE}/model?tier=full"})
check("the second carries its index", r2["model_variants"][1],
      {"full": f"/assets/props/{FENCE}/model?variant=1&tier=full"})
check("variants == model_variants[0]", r2["variants"], r2["model_variants"][0])
check("resolved variant", r2["variant"], 1)
check("fix_euler", r2["fix_euler"], {"x": 0.0, "y": 90.0, "z": 0.0})
check("point and yaw", (r1["x"], r1["z"], r1["yaw_deg"]), (1.0, 2.0, 45.0))

# THE SINK OF THE VARIANT THE ROW DRAWS rides along, and only when it is not
# 0.0 — the client seats a world prop itself, so the value has to travel or a
# sunk boulder stands on the grass out here while it is buried in every room.
check("a prop on the ground sends no key", "ground_offset_m" in r1, False)
sig_before = wp.world_props_sig()
prop_store.set_variant_ground_offset(BOULDER, 0, -0.2)
sunk = {r["id"]: r for r in wp.payload_rows()}[one["id"]]
check("the sink reaches the row", sunk["ground_offset_m"], -0.2)
check("…without touching the placement's own trim", sunk["offset_y"], 0.0)
check("it is derived per poll, not stored on the placement row",
      "ground_offset_m" in next(r for r in wp.list_world_props()
                                if r["id"] == one["id"]), False)
check("the signature moves with it", wp.world_props_sig() == sig_before, False)
# A row that draws variant 1 reads VARIANT 1's sink (2026-08-25). The "Fence"
# placement resolved to variant 1 above, so −0.4 there and −0.2 on variant 0
# must come out as −0.4: the size and the sink of a row belong to the same
# mesh, or the fence floats at the other version's depth.
prop_store.set_variant_ground_offset(FENCE, 0, -0.2)
prop_store.set_variant_ground_offset(FENCE, 1, -0.4)
fence_row = {r["id"]: r for r in wp.payload_rows()}[two["id"]]
check("the row draws variant 1", fence_row["variant"], 1)
check("…so it carries variant 1's sink, not variant 0's",
      fence_row["ground_offset_m"], -0.4)
prop_store.set_variant_ground_offset(FENCE, 0, 0)
prop_store.set_variant_ground_offset(FENCE, 1, 0)
prop_store.set_variant_ground_offset(BOULDER, 0, 0)
check("cleared again, the key is gone once more",
      "ground_offset_m" in {r["id"]: r for r in wp.payload_rows()}[one["id"]],
      False)

fogged = build_worldmap_payload("nobody", show_all=False)
admin = build_worldmap_payload(None, show_all=True)
check("the block is in the worldmap payload", len(fogged["world_props"]), 2)
check("deco is never fogged", fogged["world_props"], admin["world_props"])
check("the signature rides along",
      fogged["world_props_sig"] == wp.world_props_sig(), True)

print("\n[4] a stored index wraps")
wp.save_world_prop({**two, "variant": 5})
check("5 mod 2", {r["id"]: r for r in wp.payload_rows()}[two["id"]]["variant"], 1)

print("\n[5] the cap")
check("cap constants", (wp.MAX_WORLD_PROPS, wp.WARN_WORLD_PROPS), (500, 200))
while wp.count_world_props() < wp.MAX_WORLD_PROPS:
    wp.save_world_prop({"prop_id": BOULDER,
                        "x": float(wp.count_world_props()), "z": 0.0})
check("seeded to the cap", wp.count_world_props(), 500)
raises("the 501st is refused", lambda: wp.save_world_prop(
    {"prop_id": BOULDER, "x": 0.0, "z": 0.0}))
moved = wp.save_world_prop({**one, "x": 7.0})
check("an update at the cap still works", moved["x"], 7.0)
check("still at the cap", wp.count_world_props(), 500)

print("\n[6] a deleted prop takes its placements")
for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])
wp.save_world_prop({"prop_id": DOOMED, "x": 1.0, "z": 1.0})
wp.save_world_prop({"prop_id": DOOMED, "x": 2.0, "z": 2.0})
wp.save_world_prop({"prop_id": BOULDER, "x": 3.0, "z": 3.0})
check("three placements", wp.count_world_props(), 3)
check("removed with the prop", wp.delete_world_props_of(DOOMED), 2)
check("the others stay", wp.count_world_props(), 1)
check("an unknown prop removes nothing", wp.delete_world_props_of("nope"), 0)

print("\n[7] the signature")
sig_a = wp.world_props_sig()
check("stable over a re-read", wp.world_props_sig(), sig_a)
last = wp.list_world_props()[0]
wp.save_world_prop({**last, "x": last["x"] + 1.0})
check("moves when a placement moves", wp.world_props_sig() != sig_a, True)
check("delete works", wp.delete_world_prop(last["id"]), True)
check("deleting twice is False", wp.delete_world_prop(last["id"]), False)

# ── SEASONS (E2c): the signature has to move with the CLOCK too ──
# The rows are derived from `props.active_variant_tiers`, so a season swap
# changes the payload without touching a single DB row. Fixture (a smoke has
# no world clock): the shipped calendar — 4 seasons × 30 days, season starts
# 0/30/60/90 — plus a hand-picked instant, day-of-year 35 = day 5 of SUMMER
# and 95 = day 5 of WINTER, at noon: (D-1) × 86400 + 43200.
from app.core import game_time as _gt  # noqa: E402
from app.core import timeutils as _tu  # noqa: E402


def _set_season(day_of_year: int) -> None:
    _gt._CALENDAR_CACHE = _gt.Calendar.default()
    now = _gt.GameTime((day_of_year - 1) * _gt.DAY_SECONDS + 12 * 3600)
    _tu.game_time = lambda: now


for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])
wp.save_world_prop({"prop_id": FENCE, "x": 5.0, "z": 5.0})
_set_season(95)
check("the fence has both variants while nothing is tagged",
      len(wp.payload_rows()[0]["model_variants"]), 2)
sig_untagged_winter = wp.world_props_sig()
_set_season(35)
check("an untagged prop gives the SAME signature in another season",
      wp.world_props_sig(), sig_untagged_winter)
prop_store.set_variant_seasons(FENCE, 1, ["Winter"])
sig_summer = wp.world_props_sig()
check("summer: the winter variant is gone from the row",
      "model_variants" in wp.payload_rows()[0], False)
_set_season(95)
check("winter: both are published again",
      len(wp.payload_rows()[0]["model_variants"]), 2)
check("...and the signature moved with the season, not with a row",
      wp.world_props_sig() != sig_summer, True)
prop_store.set_variant_seasons(FENCE, 1, [])
check("clearing the tag restores the summer answer byte for byte",
      (_set_season(35) or wp.world_props_sig()), sig_untagged_winter)
for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])

print("\n[8] the editor listing")
for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])
keep = wp.save_world_prop({"prop_id": FENCE, "x": 1.0, "z": 1.0})
gone = wp.save_world_prop({"prop_id": GHOST, "x": 2.0, "z": 2.0})
listing = get_world_props_route()
check("cap numbers travel", (listing["max"], listing["warn_at"]), (500, 200))
check("count", listing["count"], 2)
rows_by_id = {r["id"]: r for r in listing["world_props"]}
check("name of a live prop", rows_by_id[keep["id"]]["name"], "Fence")
check("variant count of a live prop",
      rows_by_id[keep["id"]]["variant_count"], 2)
check("a mesh-less prop is NOT missing (it is only unrendered)",
      rows_by_id[gone["id"]]["missing"], False)
check("…but it has no variant to choose from",
      rows_by_id[gone["id"]]["variant_count"], 0)
prop_store.delete_prop(GHOST)
check("a deleted prop shows as missing",
      get_world_props_route()["world_props"][1]["missing"], True)

print("\n[9] the ground boxes (§ A9b)")
from app.models.terrain import terrain_sig  # noqa: E402
from app.models.world import (_load_world_data, _save_world_data,  # noqa: E402
                              add_location, update_location_position)

# [8] left exactly two placements standing: the live Fence at (1, 1) and the
# one whose prop record it deleted in its last line.
boxes = {b["id"]: b for b in wp.prop_boxes()}
check("a placement whose prop record is gone has no box",
      gone["id"] in boxes, False)
check("…so one box is left", len(boxes), 1)
check("half the real width plus the margin", boxes[keep["id"]]["half_w"], 1.25)
check("half the real depth plus the margin", boxes[keep["id"]]["half_d"], 0.75)
check("anchor and turn travel unchanged",
      (boxes[keep["id"]]["x"], boxes[keep["id"]]["z"],
       boxes[keep["id"]]["yaw_deg"]), (1.0, 1.0, 0.0))

# A prop with a RECORD but no mesh: placed ground is spoken for, mesh or not.
SAPLING = prop_store.create_prop(name="Sapling", width_m=4.0, height_m=2.0,
                                 depth_m=2.0)["id"]
sapling = wp.save_world_prop({"prop_id": SAPLING, "x": 50.0, "z": 50.0,
                              "yaw_deg": 30.0})
boxes = {b["id"]: b for b in wp.prop_boxes()}
check("a prop with no mesh yet still keeps its ground clear",
      (boxes[sapling["id"]]["half_w"], boxes[sapling["id"]]["half_d"]),
      (2.25, 1.25))

# …and a placement inside a location's own outline needs no box of its own.
camp = add_location(name="Alder Camp", description="Boundary fixture.")["id"]
update_location_position(camp, 100.0, 100.0)
_world = _load_world_data()
for _entry in _world.get("locations", []):
    if _entry.get("id") == camp:
        # The drawn outline of contract v6, in LOCAL metres around the pin.
        _entry["map3d"] = {"boundary": [[-10, -10], [10, -10],
                                        [10, 10], [-10, 10]]}
        break
_save_world_data(_world)
inside = wp.save_world_prop({"prop_id": FENCE, "x": 105.0, "z": 100.0})
outside = wp.save_world_prop({"prop_id": FENCE, "x": 130.0, "z": 100.0})
boxes = {b["id"]: b for b in wp.prop_boxes()}
check("a placement inside a location boundary gets no box",
      inside["id"] in boxes, False)
check("…one outside it does", outside["id"] in boxes, True)

_sig_before = terrain_sig()
wp.save_world_prop({**outside, "x": 131.0})
check("terrain_sig moves when a box moves", terrain_sig() != _sig_before, True)

print("\n[10] a variant may be its own size (2026-08-24)")
for row in wp.list_world_props():
    wp.delete_world_prop(row["id"])
# The seed of this section, and every number below follows from it: a pine of
# 2.0 x 1.0 x 3.0 m (w x d x h, like every prop here) whose SECOND variant is
# the grown tree — 4.0 m wide and 6.0 m tall, depth inherited.
PINE = seed_prop("Pine", variants=2)
prop_store.set_variant_dims(PINE, 1, {"width_m": 4.0, "height_m": 6.0})
check("the size is stored on variant 1 alone",
      [v["dims"] for v in prop_store.list_variants(PINE)],
      [{"width_m": 2.0, "depth_m": 1.0, "height_m": 3.0},
       {"width_m": 4.0, "depth_m": 1.0, "height_m": 6.0}])
small = wp.save_world_prop({"prop_id": PINE, "x": 200.0, "z": 0.0,
                            "variant": 0})
big = wp.save_world_prop({"prop_id": PINE, "x": 210.0, "z": 0.0,
                          "variant": 1})
rows = {r["id"]: r for r in wp.payload_rows()}
# max_m = the largest edge of the variant THIS row shows:
#   variant 0  max(2.0, 3.0, 1.0) = 3.0
#   variant 1  max(4.0, 6.0, 1.0) = 6.0
check("max_m of the sapling variant", rows[small["id"]]["max_m"], 3.0)
check("max_m of the grown variant", rows[big["id"]]["max_m"], 6.0)
check("...and both rows still name the same prop",
      (rows[small["id"]]["prop_id"], rows[big["id"]]["prop_id"]), (PINE, PINE))
# The ground box follows the same size:
#   variant 0  half_w = 2.0 / 2 + 0.25 = 1.25 ; half_d = 1.0 / 2 + 0.25 = 0.75
#   variant 1  half_w = 4.0 / 2 + 0.25 = 2.25 ; half_d unchanged at 0.75
boxes = {b["id"]: b for b in wp.prop_boxes()}
check("the sapling keeps its own ground clear",
      (boxes[small["id"]]["half_w"], boxes[small["id"]]["half_d"]),
      (1.25, 0.75))
check("the grown one keeps more of it",
      (boxes[big["id"]]["half_w"], boxes[big["id"]]["half_d"]),
      (2.25, 0.75))
# A placement with NO stored variant is resolved by the formula, and the box
# has to follow THAT mesh — md5("wp_deadbeef")[:8] = 4080674006, mod 2 = 0,
# so this one shows the sapling.
auto = wp.save_world_prop({"id": "wp_deadbeef", "prop_id": PINE,
                           "x": 220.0, "z": 0.0})
check("an auto-picked variant lands on 0 here",
      wp.variant_index(auto["id"], 2), 0)
check("...so its box is the sapling's",
      ({b["id"]: b for b in wp.prop_boxes()}[auto["id"]]["half_w"]), 1.25)

print("\n[11] the ONE resolution rule")
# `resolved_variant` is the single function the payload row, the ground box and
# the editor listing run through. Every number below follows from the formula
# of [2]: md5("wp_deadbeef")[:8] = 4080674006, mod 2 = 0, mod 3 = 2.
check("no stored index: the formula picks",
      wp.resolved_variant("wp_deadbeef", None, 2), 0)
check("...and it follows the published count",
      wp.resolved_variant("wp_deadbeef", None, 3), 2)
check("a stored index WINS over the formula",
      wp.resolved_variant("wp_deadbeef", 1, 2), 1)
check("...also when it names what the formula would have picked",
      wp.resolved_variant("wp_deadbeef", 0, 2), 0)
check("an out-of-range index wraps instead of hiding the prop",
      wp.resolved_variant("wp_deadbeef", 5, 2), 1)
check("a negative one wraps into the list too",
      wp.resolved_variant("wp_deadbeef", -1, 2), 1)
check("junk written past the sanitizer falls back to the formula",
      wp.resolved_variant("wp_deadbeef", "x", 2), 0)
check("nothing to choose from", wp.resolved_variant("wp_deadbeef", 7, 0), 0)

# End to end: the auto placement of [10] showed the sapling; pinning it to the
# grown variant has to move the payload row AND the ground box.
wp.save_world_prop({**auto, "variant": 1})
rows = {r["id"]: r for r in wp.payload_rows()}
check("the payload row of a pinned placement names the pinned position",
      rows[auto["id"]]["variant"], 1)
check("...is scaled to that variant", rows[auto["id"]]["max_m"], 6.0)
check("...and keeps that variant's ground clear",
      {b["id"]: b for b in wp.prop_boxes()}[auto["id"]]["half_w"], 2.25)

# The editor listing: what the variant picker reads, without a second lookup.
listing = {r["id"]: r for r in get_world_props_route()["world_props"]}
check("the listing names the store index behind every position",
      listing[auto["id"]]["variant_indices"], [0, 1])
check("...how many there are", listing[auto["id"]]["variant_count"], 2)
check("...and what Auto resolves to, whatever is stored",
      listing[auto["id"]]["variant_auto"], 0)

# A placement stores a POSITION in the PUBLISHED list: switching variant 0 off
# leaves ONE position, and it is the grown tree — so every placement of the
# pine keeps 2.25 clear, the one pinned to the sapling included.
prop_store.set_variant_active(PINE, 0, False)
check("one variant switched off, one position published",
      len(prop_store.active_variant_tiers(PINE)), 1)
boxes = {b["id"]: b for b in wp.prop_boxes()}
check("the pinned placement wraps onto it",
      boxes[auto["id"]]["half_w"], 2.25)
check("...and so does the one pinned to the position that is gone",
      boxes[small["id"]]["half_w"], 2.25)
prop_store.set_variant_active(PINE, 0, True)
check("switching it back on restores the sapling's box",
      {b["id"]: b for b in wp.prop_boxes()}[small["id"]]["half_w"], 1.25)

shutil.rmtree(STORAGE, ignore_errors=True)
shutil.rmtree(CLIPS, ignore_errors=True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("smoke_world_props: OK")
