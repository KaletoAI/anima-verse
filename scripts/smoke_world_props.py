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
        - `ground_offset_m` (the PROP's own sink, 2026-08-20) rides the row
          ONLY when it is not 0.0 — the client seats a world prop itself, so
          the bottom is `heightAt(x, z) + offset_y + ground_offset_m`. It is
          derived per poll like `max_m`: setting the prop to −0.2 changes the
          rows and the signature without a single placement being rewritten,
          and the placement's own `offset_y` stays what it was.
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
    if rotation:
        prop_store.set_rotation(pid, rotation)
    for i in range(variants):
        if i > 0:
            prop_store.add_variant(pid)
        g = prop_store.model_gallery(pid, i)
        target = g.new_path()
        target.write_bytes(b"not-a-real-glb")
        g.select(target.name, "full")
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
check("exists", wp.world_prop_exists(a["id"]), True)
check("does not exist", wp.world_prop_exists("wp_nope"), False)

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

# THE PROP'S OWN SINK rides the row, and only when it is not 0.0 — the client
# seats a world prop itself, so the value has to travel or a sunk boulder
# stands on the grass out here while it is buried in every room.
check("a prop on the ground sends no key", "ground_offset_m" in r1, False)
sig_before = wp.world_props_sig()
prop_store.update_prop(BOULDER, {"ground_offset_m": -0.2})
sunk = {r["id"]: r for r in wp.payload_rows()}[one["id"]]
check("the sink reaches the row", sunk["ground_offset_m"], -0.2)
check("…without touching the placement's own trim", sunk["offset_y"], 0.0)
check("it is derived per poll, not stored on the placement row",
      "ground_offset_m" in next(r for r in wp.list_world_props()
                                if r["id"] == one["id"]), False)
check("the signature moves with it", wp.world_props_sig() == sig_before, False)
prop_store.update_prop(BOULDER, {"ground_offset_m": 0})
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

shutil.rmtree(STORAGE, ignore_errors=True)
shutil.rmtree(CLIPS, ignore_errors=True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("smoke_world_props: OK")
