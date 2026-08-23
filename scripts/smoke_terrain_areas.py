#!/usr/bin/env python3
"""Smoke run for painted terrain areas (Seamless World, E1 Task 4).

Throwaway storage. Hand-derived expectations:

  [1] save_area({kind: "water", polygon: [[0,0],[10,0],[10,10],[0,10]]})
      -> id starts with "ta_", z_order 0, polygon values rounded floats.
  [2] save_area with kind "nope_unknown" -> ValueError (kind must exist in
      the effective catalog).
  [3] save_area with 2 points -> ValueError; MAX_POINTS + 1 = 2051 points ->
      ValueError; coordinate 1e9 -> ValueError. The ceiling is 2050 =
      2 · MAX_DECORATED_POINTS + 2 since 2026-08-23: a `wavy` line is sampled
      every 3 m so that its sine reads as a curve, a kilometre of river is 335
      centre points, and the mitred ribbon around a centre line is twice as
      wide plus the two points one bevelled join adds. The centre LINE of a
      stroke recipe has its own, half as high (MAX_STROKE_POINTS = 1024) —
      it is what the outline is generated from.
  [4] Update: save_area({id: <id1>, kind: "water", polygon: ...,
      z_order: 5}) -> list_areas() returns it LAST (highest z_order).
  [5] delete_area(<id1>) -> True; second delete -> False.
  [6] terrain_sig() changes when an area is saved and when a world type is
      saved (compare three signatures: empty, after area, after
      save_world_type("grass", ...)); it is 10 chars long.
  [7] Junk vertices that are not a 2-number sequence raise ValueError, not
      an uncaught exception. A dict vertex {"x": 1, "z": 2} raises KeyError
      on pt[0] — a class the naive (TypeError, ValueError, IndexError)
      catch misses, so it would escape the sanitizer as a 500 instead of a
      400. world_geometry.point_in_polygon fails CLOSED on malformed
      vertices without logging, so garbage must never reach the DB.
  [8] Non-finite coordinates raise ValueError. A range check alone does NOT
      catch NaN: abs(nan) > MAX_COORD is False (every NaN comparison is),
      so NaN would sail through and poison every later JSON response
      (Starlette encodes with allow_nan=False -> 500). Hence the explicit
      isfinite guard; inf and -inf are covered by the range check too, but
      are pinned here as well.
  [9] Numeric coercion never raises OverflowError out of the sanitizer.
      Starlette parses bodies with stdlib json.loads, which accepts the
      `Infinity` literal and unbounded integer literals, and there is no
      global exception handler — so an uncaught OverflowError is a 500 on
      a junk body. Two vectors: z_order inf (int(inf) raises, and it raises
      BEFORE the clamp) -> falls back to z_order 0 like any other junk;
      a coordinate of 10**400, the json-integer analogue (float(10**400)
      raises) -> ValueError. Plus the clamp itself: z_order 99999 -> 10000,
      so an absurd layer number cannot exceed SQLite's 64-bit INTEGER.
 [10] A PUT never resurrects a deleted area. save_area is an upsert
      (INSERT … ON CONFLICT DO UPDATE), so the id in the body decides — a
      client repeating a stale PUT after the area was deleted would recreate
      it under exactly its old id. The route therefore checks first:
        area_exists(<fresh id>)      -> True
        area_exists(<deleted id>)    -> False
        area_exists("")              -> False (no id is not an existing id)
      and the route itself, called directly with a fake Request:
        PUT on the deleted id  -> HTTPException 404, list_areas() unchanged
        PUT on the live id     -> {"status": "success"}, kind updated to
                                  "grass" (so the 404 guard is not simply
                                  rejecting everything)
      POST stays create-only, so this closes the only resurrection path.

 [11] meta.scatter whitelist (finding B17 — moved here from the terrain
      TYPE, where it lived as ONE block; an area carries a LIST, because a
      wood with two kinds of tree is one painted shape).
      Per entry, exactly four fields survive: density_per_100m2 (float,
      always present, junk/negative -> 0.0), height_m (float > 0, optional
      — the TARGET height the prop is scaled to), model (non-empty
      string, optional, never truncated) and min_spacing_m (float > 0,
      optional — the least distance the row's OWN instances keep from each
      other). Junk keys inside an entry are dropped.
      The spacing is a knob, so it is CLAMPED and never refused:
        2.5      -> 2.5          (a plain value survives)
        "3.456"  -> 3.46         (coerced, two decimals — a scatter is not
                                  authored in millimetres and the number
                                  travels to every client)
        3.455    -> 3.46         (round-half-up on the .005, the same
                                  banker-free rounding every metre here uses;
                                  pinned so a change of rule is visible)
        150      -> 100.0        (MIN_SPACING_MAX_M; 100 m is a scatter cell
                                  and a half, so a bigger gap cannot be met
                                  inside the cell it is sampled in anyway)
        100      -> 100.0        (exactly at the limit, untouched)
        0 / -1 / NaN / inf / "wide" / None -> the KEY IS DROPPED, which is
                                  how both renderers read "no constraint". The list itself: a non-list raises (the field moved AS a
      list, so a bare object is an old client, not a guess), an entry that
      is not an object raises, more than MAX_SCATTER_ENTRIES (8) raises, an
      empty list is kept as sent ("authored to nothing"). Foreign meta keys
      next to scatter survive untouched, and the list survives a save/read
      round trip.

 [12] meta.scatter enrichment (`terrain.with_scatter_props`) — what the
      entry's PROP knows, added when the areas are handed out
      (GET /play/terrain) and never stored: `variants` (the resolution tiers
      it HAS, plan-scatter-lod.md Task 1) and `prop_height_m` (its REAL
      height, acceptance finding 12). Prop fixtures are built in the same
      throwaway storage with the real props/model_store APIs:
        smoke-tree  height_m 8.5; two gallery files, the second selected for
                    tier "low"                             -> tiers [full, low]
        smoke-rock  no dims given; one gallery file, no selection at all —
                    the default tier resolves to the newest unclaimed file
                                                           -> tiers [full]
        smoke-ghost no dims given, a prop record without any mesh -> tiers []
      DEFAULT_DIM_M IS THE REALITY, and the test pins it: `create_prop` writes
      the 1 m placeholder cube when no dim is given, and `_effective_dims`
      derives one for a legacy `size_m` sidecar — so EVERY prop record answers
      with a height > 0. There is no "prop without a height"; a missing
      `prop_height_m` means "no prop record behind that URL", full stop.
      Hand-derived expectations per scatter entry:
        model /assets/props/<tree>/model  -> variants with EXACTLY two URLs,
              "/assets/props/<tree>/model?tier=full" and "...?tier=low",
              and prop_height_m 8.5 (the sidecar's, not the entry's)
        model /assets/props/<rock>/model  -> exactly one URL, ?tier=full,
              and prop_height_m 1.0 (DEFAULT_DIM_M, nothing was authored)
        no model                          -> neither key
        model of the mesh-less prop       -> no "variants" (an invented tier
              is a 404 dressed up as a model) but prop_height_m 1.0: the two
              keys are independent, the height is a fact about the RECORD
        an unknown prop id                -> neither key
        an absolute/foreign URL, and the canonical path WITH a query string
                                          -> neither key (parsing is strict)
        the tree AGAIN with height_m 3    -> prop_height_m still 8.5; the
              enrichment reports the LIBRARY height and never echoes the
              authored one, which is what makes the precedence a precedence
      The stored area is unchanged afterwards: a fresh read has exactly the
      authored fields per entry (the entry with a height: exactly those
      three).
      Both lookups are cached TOGETHER per call: seven parsable mentions
      across two areas do FOUR props.active_variant_tiers and FOUR
      props.prop_scatter_facts reads — one per DISTINCT prop, and the sidecar
      facts are not a second walk of the directory (counted with wrappers).

 [12b] MODEL VARIANTS of a scattered prop (§ B2 addendum, 2026-08-20). A prop
      may carry several meshes of the same object; the entry then also gets
      `model_variants`, one tier map per ACTIVE variant WITH a mesh, in the
      prop's own order. Fixture `smoke-bush`: variant 0 with tiers [full, low],
      variant 1 with [full], variant 2 active but EMPTY.
        model_variants -> [{full: ".../model?tier=full",
                            low:  ".../model?tier=low"},
                           {full: ".../model?variant=1&tier=full"}]
        variants       -> element 0, character for character — the primary
                          variant keeps its query-less URL, so no client cache
                          is invalidated by the feature existing
        the EMPTY slot -> dropped; a map with no tier is a placement that
                          renders nothing
        the tree (ONE variant) -> NO `model_variants` key at all
      Payload only, like every other addition: a fresh read of both entries
      carries no `model_variants`.
      WHICH instance shows which variant is deliberately NOT here. The painted
      scatter's instances are sampled client-side in a camera window, so the
      one formula runs in the renderers over the cell seed
      (`@anima/scene-render scatterVariantIndex`); its numbers are checked in
      `client3d/scripts/smoke_scatter_math.mjs` section (N).
      RED COUNTER-PROBES, EXECUTED, all built from the module's own pieces:
      a "loose URL" mutant (anything containing /assets/props/) hands the
      foreign URL a variants map, a "no tier parameter" mutant builds
      "/assets/props/<id>/model" without "?tier=", and an "echo the entry"
      mutant reports entry.height_m as prop_height_m (3 instead of 8.5) —
      every answer differs from the real one at exactly the checked spot.

 [13] `sway_factor` — how much of its ground's wind ONE prop takes part in
      (2026-08-14). It lives on the PROP sidecar, not on the scatter entry and
      not in the terrain catalog: how hard it blows is the kind's business,
      how far a boulder moves in it is the boulder's.
      (13a) The sanitizer, driven through `props.update_prop` and read back out
      of the sidecar FILE, so "the key is gone" is a statement about storage:
        fresh prop        -> no key
        0        -> stored 0.0   (0 is LEGAL here; it is what the field is for)
        0.333    -> stored 0.33  (two decimals, the step the admin field offers)
        5        -> clamped to 1.0, which is the default -> NO key
        -2       -> clamped to the legal 0.0
        1        -> no key (an absent key and a stored 1.0 would be two
                    spellings of one behaviour, so only one may exist)
        "junk"   -> no key;  ""  -> no key (the emptied admin field)
        a patch without the key -> the stored 0.25 survives untouched
        0.004    -> stored 0.0: it rounds to zero, and unlike the terrain
                    catalog numbers zero is an answer here, not a silence
      Reading is forgiving where writing is strict: `sway_factor_of({NaN})` is
      the default 1.0, and the admin record (`get_prop`) always reports the
      EFFECTIVE factor rather than the raw key.
      (13b) The payload, same enrichment as [12] and equally PAYLOAD ONLY.
      With the stone at 0.0 and the tree untouched:
        stone entry   -> sway_factor 0.0
        tree entry    -> NO key (the default travels as absence)
        tuft entry, foreign URL -> no key either
      the stored area still has exactly its authored fields, and setting the
      stone to 0.4 afterwards reaches the NEXT payload without the area being
      rewritten.
      RED COUNTER-PROBE, EXECUTED: the terrain catalog's own number rule
      (`_clamped_meta_number`, "a value that rounds to zero says nothing")
      applied unchanged to this field answers "no key" for 0 where the truth is
      a stored 0.0 — and a missing key means the default, so that mutant's
      stone waves along with the meadow. Pinned from both sides.

 [15] `ground_offset_m` — how deep ONE prop stands in the ground (2026-08-20).
      The same sidecar/payload pair as [13], with the default at the other end
      of the range: 0.0 is what says nothing, so 0.0 is the value that must NOT
      be stored, and ABSENCE is the statement.
      (15a) The sanitizer, driven through `props.update_prop` and read back out
      of the sidecar FILE:
        fresh prop -> no key
        -0.2       -> stored -0.2
        -0.207     -> stored -0.21   (centimetres, the dial's own step)
         0.354     -> stored  0.35
        -99 / 99   -> clamped to -5.0 / 5.0 (a typing slip costs the limit,
                      never the record)
         0         -> NO key;  -0.004 -> rounds to 0 -> no key either
        "junk", "" -> no key (junk is no statement; the emptied field clears)
        a patch without the key -> the stored -0.2 survives untouched
      Reading is forgiving where writing is strict: `ground_offset_of({NaN})`
      is 0.0 and `get_prop` always reports the EFFECTIVE offset.
      (15b) The payload, same enrichment as [12]/[13] and equally PAYLOAD ONLY.
      With the fir at −0.2 and the tree untouched:
        fir entry     -> ground_offset_m −0.2  (the client seats every instance
                         of it at heightAt(x, z) − 0.2)
        tree entry    -> NO key (the default travels as absence)
        tuft entry, foreign URL -> no key either
      the stored area keeps exactly its authored fields, and moving the fir to
      −0.35 reaches the NEXT payload without the area being rewritten.
      RED COUNTER-PROBE, EXECUTED: the wind factor's own rule copied one field
      over (default 1.0) answers "no key" for a real one-metre lift and keeps a
      0.0 the payload law forbids — wrong at both ends at once.

 [14] meta.stroke whitelist — the RECIPE of an area drawn with the line
      tool (`mapMath.decorateStroke` -> `strokeToPolygon`). The polygon next
      to it stays the truth, but the editor REGENERATES that polygon from
      these fields, so a stray key or a NaN spacing would reshape ground on
      the next edit.
      Required, or the recipe is refused outright (ValueError): `points`
      (2..MAX_STROKE_POINTS = 1024 [x, z] numbers, rounded and range-checked
      exactly like an outline, only capped at half its 2050 because the
      outline is GENERATED from this line — one point is not a line) and
      `width_m` (a positive number).
      Optional and whitelisted:
        style       "straight"/"jagged"/"wavy", trimmed; anything else loses
                    the key, and a missing style IS straight — the state of
                    every line drawn before the styles existed
        spacing_m   clamped to 2..100 m: 0.5 -> 2.0, 500 -> 100.0, and
                    10.567 -> 10.57 on the 2-decimal grid
        amplitude_m clamped to 0.5..30 m: 0 -> 0.5, -3 -> 0.5, 100 -> 30.0
      Junk (NaN, None, a word) loses the key, and then the client's own
      default applies; junk keys inside the recipe are dropped; foreign meta
      keys next to `stroke` survive; and the recipe survives a save/read
      round trip.

 [16] SEASON-tagged model variants (E2c, 2026-08-20). A variant may name the
      seasons it depicts, so the ENRICHED entry changes while every stored row
      stays put — and `terrain_sig`, which hashes that enriched block, has to
      follow or a running client keeps the wrong wood. Fixture: the shipped
      calendar (4 seasons × 30 days -> season starts 0/30/60/90) and a
      hand-picked instant, day-of-year 35 = day 5 of SUMMER and 95 = day 5 of
      WINTER, both at noon ((D - 1) × 86400 + 43200 seconds).
      With `smoke-bush` from [12b] (two meshed variants):
        untagged            -> 2 maps, and ONE signature for both seasons
        variant 1 "Winter"  -> summer publishes 1 map, and the signature moved
        the same in winter  -> 2 maps again, and the signature is character for
                               character the untagged one, because the payload
                               is the same payload

Usage:  ./.venv/bin/python scripts/smoke_terrain_areas.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="terrain-area-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="terrain-area-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import terrain_types  # noqa: E402
from app.models import terrain  # noqa: E402

FAILURES = []
CHECKED = 0

SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def differs(label, actual, forbidden):
    """A red counter-probe: the mutant's answer must NOT be the real one."""
    global CHECKED
    CHECKED += 1
    ok = actual != forbidden
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else " — the mutant agrees, so the check proves nothing"))
    if not ok:
        FAILURES.append(label)


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({str(e)!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


SIG_EMPTY = terrain.terrain_sig()

print("[1] saving one area")
area1 = terrain.save_area({"kind": "water", "polygon": SQUARE})
check("id prefix", area1["id"][:3], "ta_")
check("z_order default", area1["z_order"], 0)
check("polygon rounded", area1["polygon"],
      [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
check("polygon all floats",
      all(isinstance(c, float) for pt in area1["polygon"] for c in pt), True)
# SINCE "EIN BODEN" E1 (§ G4): "water" is a kind the catalog flags as a WATER
# SURFACE, and saving a water area SETTLES its mirror height — the median of
# the natural ground along its rim, written down so it stops following the
# landscape around it. This world has no height area at all, so that ground is
# flat and the median is exactly 0.0. The two widths keep their defaults and
# are only stored when authored.
check("meta default — the settled mirror of a water area on flat ground",
      area1["meta"], {"water_level": 0.0})
check("...and the plain sanitizer adds nothing (settling is a SAVE step)",
      terrain.sanitize_area({"kind": "water", "polygon": SQUARE})["meta"], {})
_authored = terrain.save_area({"kind": "water", "polygon": SQUARE,
                               "meta": {"water_level": -1.5}})
check("an AUTHORED mirror is never overwritten by the settle step",
      _authored["meta"], {"water_level": -1.5})
terrain.delete_area(_authored["id"])   # …and out again: [2] counts the rows
check("listed once", [a["id"] for a in terrain.list_areas()], [area1["id"]])

SIG_AFTER_AREA = terrain.terrain_sig()

print("[2] unknown kind")
raises_value_error("unknown kind raises",
                   lambda: terrain.save_area({"kind": "nope_unknown",
                                              "polygon": SQUARE}))

print("[3] polygon size + range")
raises_value_error("2 points raises",
                   lambda: terrain.save_area({"kind": "water",
                                              "polygon": [[0, 0], [1, 1]]}))
raises_value_error(
    "MAX_POINTS + 1 points raises",
    lambda: terrain.save_area(
        {"kind": "water",
         "polygon": [[i, i] for i in range(terrain.MAX_POINTS + 1)]}))
raises_value_error(
    "1e9 coordinate raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [[0, 0], [1e9, 0], [1, 1]]}))
check("MAX_POINTS = 2050 = 2 · MAX_DECORATED_POINTS + 2", terrain.MAX_POINTS,
      2050)
check("...and exactly that many points are accepted",
      len(terrain.sanitize_area(
          {"kind": "water",
           "polygon": [[i, i] for i in range(terrain.MAX_POINTS)]})["polygon"]),
      2050)
check("the CENTRE LINE of a recipe is capped at half that",
      terrain.MAX_STROKE_POINTS, 1024)

print("[4] update lifts the area to the top")
area2 = terrain.save_area({"kind": "grass", "polygon": SQUARE})
check("paint order before update",
      [a["id"] for a in terrain.list_areas()], [area1["id"], area2["id"]])
updated = terrain.save_area({"id": area1["id"], "kind": "water",
                             "polygon": SQUARE, "z_order": 5})
check("update keeps id", updated["id"], area1["id"])
check("z_order stored", updated["z_order"], 5)
areas = terrain.list_areas()
check("no duplicate row", len(areas), 2)
check("highest z_order last", areas[-1]["id"], area1["id"])

print("[5] delete")
check("delete once", terrain.delete_area(area1["id"]), True)
check("delete twice", terrain.delete_area(area1["id"]), False)
check("remaining areas", [a["id"] for a in terrain.list_areas()], [area2["id"]])

print("[6] change signature")
terrain_types.save_world_type({"kind": "grass", "name": "Dry Grass",
                               "color": "#aaaa00", "passable": True,
                               "speed_factor": 0.9})
SIG_AFTER_TYPE = terrain.terrain_sig()
check("sig length", len(SIG_EMPTY), 10)
check("sig changes on area save", SIG_EMPTY != SIG_AFTER_AREA, True)
check("sig changes on type save", SIG_AFTER_AREA != SIG_AFTER_TYPE, True)
check("all three distinct",
      len({SIG_EMPTY, SIG_AFTER_AREA, SIG_AFTER_TYPE}), 3)
check("sig stable without change", terrain.terrain_sig(), SIG_AFTER_TYPE)

print("[7] junk vertices raise ValueError, never a raw crash")
raises_value_error(
    "dict vertex raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [{"x": 1, "z": 2}, [1, 1], [2, 2]]}))
raises_value_error(
    "string vertex raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": ["ab", [1, 1], [2, 2]]}))
raises_value_error(
    "None vertex raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [None, [1, 1], [2, 2]]}))
raises_value_error(
    "one-element vertex raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [[1], [1, 1], [2, 2]]}))
raises_value_error("polygon not a list",
                   lambda: terrain.save_area({"kind": "water",
                                              "polygon": "square"}))
raises_value_error("area not an object",
                   lambda: terrain.save_area(["water"]))

print("[8] non-finite coordinates raise ValueError")
for bad in ("nan", float("nan"), float("inf"), float("-inf")):
    raises_value_error(
        f"{bad!r} coordinate raises",
        lambda bad=bad: terrain.save_area(
            {"kind": "water", "polygon": [[0, 0], [bad, 1], [2, 2]]}))
# Nothing non-finite may have reached storage: Starlette encodes responses
# with allow_nan=False, so one NaN would 500 the whole endpoint.
check("areas render under allow_nan=False",
      bool(json.dumps(terrain.list_areas(), allow_nan=False)), True)

print("[9] OverflowError never escapes the numeric coercions")
# int(inf) raises OverflowError, and it raises BEFORE the clamp — junk
# z_order must degrade to the default layer, not 500 the route.
inf_area = terrain.save_area({"kind": "water", "polygon": SQUARE,
                              "z_order": float("inf")})
check("inf z_order falls back to 0", inf_area["z_order"], 0)
check("inf z_order stored",
      [a["z_order"] for a in terrain.list_areas() if a["id"] == inf_area["id"]],
      [0])
# float(10**400) raises OverflowError, not ValueError — a JSON body may
# legitimately carry an integer literal of that size.
raises_value_error(
    "huge integer coordinate raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [[0, 0], [10 ** 400, 1], [2, 2]]}))
# The clamp keeps a plausible-but-absurd layer inside SQLite's INTEGER range.
check("z_order 99999 clamps",
      terrain.sanitize_area({"kind": "water", "polygon": SQUARE,
                             "z_order": 99999})["z_order"], 10000)
check("z_order -99999 clamps",
      terrain.sanitize_area({"kind": "water", "polygon": SQUARE,
                             "z_order": -99999})["z_order"], -10000)
terrain.delete_area(inf_area["id"])

print("[10] PUT never resurrects a deleted area")
from fastapi import HTTPException  # noqa: E402
from app.routes.world import put_terrain_area_route  # noqa: E402


class _FakeRequest:
    """Minimal stand-in: the route only ever awaits ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


live = terrain.save_area({"kind": "water", "polygon": SQUARE})
gone = terrain.save_area({"kind": "water", "polygon": SQUARE})
gone_id = gone["id"]
terrain.delete_area(gone_id)
check("exists for a live area", terrain.area_exists(live["id"]), True)
check("gone after delete", terrain.area_exists(gone_id), False)
check("empty id is not an existing id", terrain.area_exists(""), False)

_ids_before = [a["id"] for a in terrain.list_areas()]
CHECKED += 1
try:
    asyncio.run(put_terrain_area_route(
        gone_id, _FakeRequest({"kind": "water", "polygon": SQUARE})))
    print("  ✗ PUT on a deleted id: returned instead of raising 404")
    FAILURES.append("PUT on a deleted id")
except HTTPException as e:
    ok = e.status_code == 404
    print(f"  {'✓' if ok else '✗'} PUT on a deleted id: {e.status_code} {e.detail!r}")
    if not ok:
        FAILURES.append("PUT on a deleted id")
check("deleted area stayed deleted", terrain.area_exists(gone_id), False)
check("area list untouched", [a["id"] for a in terrain.list_areas()], _ids_before)

_res = asyncio.run(put_terrain_area_route(
    live["id"], _FakeRequest({"kind": "grass", "polygon": SQUARE})))
check("PUT on a live id succeeds", _res["status"], "success")
check("PUT on a live id updates", _res["area"]["kind"], "grass")
check("still one row for that id",
      [a["id"] for a in terrain.list_areas()].count(live["id"]), 1)
terrain.delete_area(live["id"])

print("[11] meta.scatter whitelist (moved from the terrain type, B17)")


def scatter_of(meta):
    return terrain.sanitize_area(
        {"kind": "water", "polygon": SQUARE, "meta": meta})["meta"]


check("a valid list is kept verbatim",
      scatter_of({"scatter": [{"density_per_100m2": 12.5, "height_m": 4.0,
                               "min_spacing_m": 3.0,
                               "model": "/assets/props/tree/model"}]}),
      {"scatter": [{"density_per_100m2": 12.5, "height_m": 4.0,
                    "min_spacing_m": 3.0,
                    "model": "/assets/props/tree/model"}]})
check("several entries on one area — the point of the move",
      scatter_of({"scatter": [{"density_per_100m2": 3},
                              {"density_per_100m2": 1,
                               "model": "/assets/props/rock/model"}]}),
      {"scatter": [{"density_per_100m2": 3.0},
                   {"density_per_100m2": 1.0,
                    "model": "/assets/props/rock/model"}]})
check("junk keys inside an entry are dropped",
      scatter_of({"scatter": [{"density_per_100m2": 3, "colour": "red"}]}),
      {"scatter": [{"density_per_100m2": 3.0}]})
for bad in (-5, "lots", float("nan"), float("inf"), None):
    check(f"density {bad!r} -> 0.0",
          scatter_of({"scatter": [{"density_per_100m2": bad}]}),
          {"scatter": [{"density_per_100m2": 0.0}]})
check("numeric strings are coerced",
      scatter_of({"scatter": [{"density_per_100m2": "2.5", "height_m": "1.5"}]}),
      {"scatter": [{"density_per_100m2": 2.5, "height_m": 1.5}]})
for bad in (0, -1, float("inf"), float("nan"), "tall"):
    check(f"height {bad!r} loses the key",
          scatter_of({"scatter": [{"density_per_100m2": 1, "height_m": bad}]}),
          {"scatter": [{"density_per_100m2": 1.0}]})
check("a spacing survives as authored",
      scatter_of({"scatter": [{"density_per_100m2": 1, "min_spacing_m": 2.5}]}),
      {"scatter": [{"density_per_100m2": 1.0, "min_spacing_m": 2.5}]})
check("a spacing is coerced and kept to two decimals",
      scatter_of({"scatter": [{"density_per_100m2": 1,
                               "min_spacing_m": "3.456"}]}),
      {"scatter": [{"density_per_100m2": 1.0, "min_spacing_m": 3.46}]})
check("…and .455 rounds up, not to even",
      scatter_of({"scatter": [{"density_per_100m2": 1, "min_spacing_m": 3.455}]}),
      {"scatter": [{"density_per_100m2": 1.0, "min_spacing_m": 3.46}]})
check(f"a spacing past {terrain.MIN_SPACING_MAX_M} m is clamped, not refused",
      scatter_of({"scatter": [{"density_per_100m2": 1, "min_spacing_m": 150}]}),
      {"scatter": [{"density_per_100m2": 1.0,
                    "min_spacing_m": terrain.MIN_SPACING_MAX_M}]})
check("a spacing exactly at the limit is untouched",
      scatter_of({"scatter": [{"density_per_100m2": 1,
                               "min_spacing_m": terrain.MIN_SPACING_MAX_M}]}),
      {"scatter": [{"density_per_100m2": 1.0,
                    "min_spacing_m": terrain.MIN_SPACING_MAX_M}]})
for bad in (0, -1, float("inf"), float("nan"), "wide", None, [4]):
    check(f"spacing {bad!r} loses the key (no constraint)",
          scatter_of({"scatter": [{"density_per_100m2": 1,
                                   "min_spacing_m": bad}]}),
          {"scatter": [{"density_per_100m2": 1.0}]})
for bad in (42, "   ", None, ["a"]):
    check(f"model {bad!r} loses the key",
          scatter_of({"scatter": [{"density_per_100m2": 1, "model": bad}]}),
          {"scatter": [{"density_per_100m2": 1.0}]})
check("model is stripped",
      scatter_of({"scatter": [{"density_per_100m2": 1,
                               "model": "  /assets/props/p/model  "}]}),
      {"scatter": [{"density_per_100m2": 1.0, "model": "/assets/props/p/model"}]})
# MODEL_URL_MAX + 1 characters: a truncated URL is a 404 that LOOKS like a
# configured model, so the key goes instead. The URL at the limit stays.
_long = "/assets/props/" + "x" * (terrain.MODEL_URL_MAX - 13)
check("over-long model loses the key (never truncated)",
      scatter_of({"scatter": [{"density_per_100m2": 1, "model": _long}]}),
      {"scatter": [{"density_per_100m2": 1.0}]})
check("model exactly at the limit survives",
      scatter_of({"scatter": [{"density_per_100m2": 1, "model": _long[:-1]}]}),
      {"scatter": [{"density_per_100m2": 1.0, "model": _long[:-1]}]})
check("an empty list is kept as sent", scatter_of({"scatter": []}),
      {"scatter": []})
check("foreign meta keys survive next to scatter",
      scatter_of({"foo": 1, "scatter": [{"density_per_100m2": 4}]}),
      {"foo": 1, "scatter": [{"density_per_100m2": 4.0}]})
check("meta without scatter is untouched", scatter_of({"foo": 1}), {"foo": 1})
raises_value_error("a bare object instead of a list raises",
                   lambda: scatter_of({"scatter": {"density_per_100m2": 1}}))
raises_value_error("a string instead of a list raises",
                   lambda: scatter_of({"scatter": "trees"}))
raises_value_error("an entry that is not an object raises",
                   lambda: scatter_of({"scatter": [1, 2]}))
raises_value_error(
    f"more than {terrain.MAX_SCATTER_ENTRIES} entries raises",
    lambda: scatter_of({"scatter": [{"density_per_100m2": 1}]
                        * (terrain.MAX_SCATTER_ENTRIES + 1)}))
check(f"exactly {terrain.MAX_SCATTER_ENTRIES} entries pass",
      len(scatter_of({"scatter": [{"density_per_100m2": 1}]
                      * terrain.MAX_SCATTER_ENTRIES})["scatter"]),
      terrain.MAX_SCATTER_ENTRIES)

_scat = terrain.save_area(
    {"kind": "water", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 9, "height_m": 6,
                           "min_spacing_m": 1.25,
                           "model": "/assets/props/fern/model"}],
              "note": "free form"}})
# ``water_level`` rides along because "water" is a water kind here (see [1]).
check("the list survives the save/read round trip",
      next(a["meta"] for a in terrain.list_areas() if a["id"] == _scat["id"]),
      {"scatter": [{"density_per_100m2": 9.0, "height_m": 6.0,
                    "min_spacing_m": 1.25,
                    "model": "/assets/props/fern/model"}],
       "note": "free form", "water_level": 0.0})
terrain.delete_area(_scat["id"])

print("[12] scatter enrichment — the tiers and the height the prop HAS")
from app.core import props  # noqa: E402


def make_prop(name, tiers, height_m=None):
    """A prop with real gallery files, built through the props API.

    The default tier needs no selection entry (the gallery answers it with the
    newest unclaimed file); every further tier is selected explicitly, which is
    exactly what the admin's "create low variant" does. Without ``height_m``
    the record takes the DEFAULT_DIM_M cube — the "nobody authored dims" case.
    """
    pid = props.create_prop(name=name, height_m=height_m)["id"]
    for tier in tiers:
        gallery = props.model_gallery(pid)
        path = gallery.new_path(".glb")
        path.write_bytes(b"glTF-smoke")
        if tier != "full":
            gallery.select(path.name, tier)
    return pid


TREE = make_prop("smoke tree", ["full", "low"], height_m=8.5)
ROCK = make_prop("smoke rock", ["full"])
GHOST = make_prop("smoke ghost", [])
check("tree tiers", props.model_tiers(TREE), ["full", "low"])
check("rock tiers", props.model_tiers(ROCK), ["full"])
check("mesh-less prop has no tier", props.model_tiers(GHOST), [])
# The DEFAULT_DIM_M reality: a record ALWAYS answers with a height, and 0.0
# is reserved for "no such prop".
check("authored height comes back",
      props.prop_scatter_facts(TREE).get("height_m"), 8.5)
check("no dims authored -> the DEFAULT_DIM_M cube",
      props.prop_scatter_facts(ROCK).get("height_m"), 1.0)
check("no mesh is still a record with a height",
      props.prop_scatter_facts(GHOST).get("height_m"), 1.0)
check("unknown prop -> {}, the 'no such prop' answer",
      props.prop_scatter_facts("nope"), {})

# Same prop id, foreign host: the strict parse must still refuse it — and it
# is what makes the "loose URL" mutant below produce a real variants map.
FOREIGN = f"https://cdn.example.org/assets/props/{TREE}/model"
WITH_QUERY = f"/assets/props/{TREE}/model?tier=low"
_va = terrain.save_area(
    {"kind": "water", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 2,
                           "model": f"/assets/props/{TREE}/model"},
                          {"density_per_100m2": 2,
                           "model": f"/assets/props/{ROCK}/model"},
                          {"density_per_100m2": 2},
                          {"density_per_100m2": 2,
                           "model": f"/assets/props/{GHOST}/model"},
                          {"density_per_100m2": 2,
                           "model": "/assets/props/nope/model"},
                          {"density_per_100m2": 2, "model": FOREIGN},
                          {"density_per_100m2": 2, "model": WITH_QUERY},
                          {"density_per_100m2": 2, "height_m": 3,
                           "model": f"/assets/props/{TREE}/model"}]}})


def served_scatter():
    """The entries as GET /play/terrain hands them out."""
    areas = terrain.with_scatter_props(terrain.list_areas())
    return next(a["meta"]["scatter"] for a in areas if a["id"] == _va["id"])


entries = served_scatter()
check("prop with two tiers -> two URLs", entries[0].get("variants"),
      {"full": f"/assets/props/{TREE}/model?tier=full",
       "low": f"/assets/props/{TREE}/model?tier=low"})
check("prop with one tier -> one URL", entries[1].get("variants"),
      {"full": f"/assets/props/{ROCK}/model?tier=full"})
check("no model -> no variants key", "variants" in entries[2], False)
check("prop without a mesh -> no variants key", "variants" in entries[3], False)
check("unknown prop id -> no variants key", "variants" in entries[4], False)
check("foreign URL -> no variants key", "variants" in entries[5], False)
check("canonical path with a query -> no variants key",
      "variants" in entries[6], False)
check("model itself is untouched", entries[0]["model"],
      f"/assets/props/{TREE}/model")
# The height half — same reach, own answer.
check("the tree's real height rides along", entries[0].get("prop_height_m"), 8.5)
check("the rock's DEFAULT_DIM_M height rides along",
      entries[1].get("prop_height_m"), 1.0)
check("no model -> no prop_height_m key", "prop_height_m" in entries[2], False)
check("no mesh but a record -> the height still rides along",
      entries[3].get("prop_height_m"), 1.0)
check("unknown prop id -> no prop_height_m key",
      "prop_height_m" in entries[4], False)
check("foreign URL -> no prop_height_m key",
      "prop_height_m" in entries[5], False)
check("canonical path with a query -> no prop_height_m key",
      "prop_height_m" in entries[6], False)
check("an authored height does not change the reported library height",
      (entries[7].get("height_m"), entries[7].get("prop_height_m")), (3.0, 8.5))
_stored = next(a["meta"]["scatter"] for a in terrain.list_areas()
               if a["id"] == _va["id"])
check("a fresh read carries neither key (payload only)",
      [sorted(e) for e in (_stored[0], _stored[1], _stored[7])],
      [["density_per_100m2", "model"], ["density_per_100m2", "model"],
       ["density_per_100m2", "height_m", "model"]])

# [12b] THE MODEL VARIANTS of a scattered prop (§ B2 addendum). A prop with
# several meshes of the same object ships one tier map per ACTIVE variant that
# HAS a mesh, in the prop's own order — and only when there really is more than
# one, because a one-element list beside an identical `variants` map would be
# the same fact twice in every payload of every world.
#
# WHICH instance shows which variant is NOT resolved here and cannot be: the
# instances of a painted scatter are sampled in the client's camera window, so
# the renderers run the shared formula over the cell seed
# (`@anima/scene-render scatterVariantIndex`, checked numerically in
# `client3d/scripts/smoke_scatter_math.mjs` section N). The server's whole job
# is the LIST.
BUSH = make_prop("smoke bush", ["full", "low"], height_m=1.4)
_bush_v1 = props.add_variant(BUSH)
_bush_g1 = props.model_gallery(BUSH, _bush_v1)
_bush_p1 = _bush_g1.new_path(".glb")
_bush_p1.write_bytes(b"glTF-smoke")
# A third variant that stays EMPTY: an active slot without a mesh renders
# nothing, so it must not appear in the list — a copy picking it would simply
# be missing from the wood.
_bush_v2 = props.add_variant(BUSH)
check("the bush has two meshed variants and one empty slot",
      [e["variant"] for e in props.active_variant_tiers(BUSH)],
      [0, _bush_v1])
_vb = terrain.save_area(
    {"kind": "grass", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 4,
                           "model": f"/assets/props/{BUSH}/model"},
                          {"density_per_100m2": 4,
                           "model": f"/assets/props/{TREE}/model"}]}})
_bush_entries = next(a["meta"]["scatter"]
                     for a in terrain.with_scatter_props(terrain.list_areas())
                     if a["id"] == _vb["id"])
check("two variants -> one tier map each, the primary one first",
      _bush_entries[0].get("model_variants"),
      [{"full": f"/assets/props/{BUSH}/model?tier=full",
        "low": f"/assets/props/{BUSH}/model?tier=low"},
       {"full": f"/assets/props/{BUSH}/model?variant={_bush_v1}&tier=full"}])
check("…and `variants` IS element 0, the primary variant's map",
      _bush_entries[0].get("variants"),
      _bush_entries[0]["model_variants"][0])
check("…so the primary variant keeps its query-less URL and every cache",
      _bush_entries[0]["variants"]["full"],
      f"/assets/props/{BUSH}/model?tier=full")
check("the empty variant slot is dropped, not shipped as a mesh-less map",
      len(_bush_entries[0]["model_variants"]), 2)
check("a prop with ONE variant says nothing at all",
      "model_variants" in _bush_entries[1], False)
check("…and still gets the `variants` map it always got",
      _bush_entries[1].get("variants"),
      {"full": f"/assets/props/{TREE}/model?tier=full",
       "low": f"/assets/props/{TREE}/model?tier=low"})
check("model_variants is payload only, never stored",
      ["model_variants" in e
       for e in next(a["meta"]["scatter"] for a in terrain.list_areas()
                     if a["id"] == _vb["id"])],
      [False, False])
terrain.delete_area(_vb["id"])

# One read per DISTINCT prop, however often it is named: the payload is
# refetched on every terrain_sig change, and each read walks a prop directory.
# All sidecar facts come out of ONE call — a second walk per mention for the
# height or the wind factor would undo exactly what the cache is there for.
_calls = []
_facts_calls = []
_real_tiers = props.model_tiers
_real_variant_tiers = props.active_variant_tiers
_real_facts = props.prop_scatter_facts


def counting_tiers(prop_id):
    _calls.append(prop_id)
    return _real_variant_tiers(prop_id)


def counting_facts(prop_id):
    _facts_calls.append(prop_id)
    return _real_facts(prop_id)


_va2 = terrain.save_area(
    {"kind": "grass", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 1,
                           "model": f"/assets/props/{TREE}/model"},
                          {"density_per_100m2": 1,
                           "model": f"/assets/props/{TREE}/model"}]}})
props.active_variant_tiers = counting_tiers
props.prop_scatter_facts = counting_facts
try:
    served = terrain.with_scatter_props(terrain.list_areas())
finally:
    props.active_variant_tiers = _real_variant_tiers
    props.prop_scatter_facts = _real_facts
# Seven parsable mentions across the two areas, four distinct props (the two
# without a mesh are looked up once as well and then remembered as "none").
check("seven mentions of four props -> four variant-tier lookups",
      sorted(_calls), sorted([TREE, ROCK, GHOST, "nope"]))
check("…and four sidecar reads, one per distinct prop for BOTH facts",
      sorted(_facts_calls), sorted([TREE, ROCK, GHOST, "nope"]))
_by_id = {a["id"]: (a["meta"].get("scatter") or []) for a in served}
check("every mention still got its variants",
      [len(e.get("variants") or {})
       for e in _by_id[_va["id"]] + _by_id[_va2["id"]]],
      [2, 1, 0, 0, 0, 0, 0, 2, 2, 2])
check("every mention of a KNOWN prop still got its height",
      [e.get("prop_height_m")
       for e in _by_id[_va["id"]] + _by_id[_va2["id"]]],
      [8.5, 1.0, None, 1.0, None, None, None, 8.5, 8.5, 8.5])

# Red counter-probes, built from the module's own pieces.
from app.core.model_store import variant_urls  # noqa: E402


def mutant_loose(entry):
    """Mutant: "URL contains /assets/props/" instead of the strict match."""
    url = str(entry.get("model") or "")
    if "/assets/props/" not in url:
        return None
    pid = url.split("/assets/props/", 1)[1].split("/", 1)[0]
    return variant_urls(f"/assets/props/{pid}/model", _real_tiers(pid)) or None


def mutant_no_tier(entry):
    """Mutant: the variants map without the ?tier= parameter."""
    pid = props.prop_id_from_model_url(entry.get("model"))
    tiers = _real_tiers(pid) if pid else []
    return {t: f"/assets/props/{pid}/model" for t in tiers} or None


def mutant_echo_entry(entry):
    """Mutant: the enrichment reads the ENTRY's height instead of the prop's
    sidecar — the precedence collapses into "whatever is already there"."""
    pid = props.prop_id_from_model_url(entry.get("model"))
    return float(entry.get("height_m") or 0) if pid else None


differs("mutant 'loose URL' invents variants for the foreign URL",
        mutant_loose({"model": FOREIGN}), entries[5].get("variants"))
differs("mutant 'no tier parameter' names the same URL twice",
        mutant_no_tier({"model": f"/assets/props/{TREE}/model"}),
        entries[0].get("variants"))
differs("mutant 'echo the entry' reports the authored 3 m as the prop height",
        mutant_echo_entry({"model": f"/assets/props/{TREE}/model",
                           "height_m": 3}),
        entries[7].get("prop_height_m"))
check("the loose mutant would really answer the foreign URL",
      bool(mutant_loose({"model": FOREIGN})), True)
check("the echoing mutant would really answer 3 m",
      mutant_echo_entry({"model": f"/assets/props/{TREE}/model",
                         "height_m": 3}), 3.0)

print("[13] sway_factor — the sidecar sanitizer and the payload it feeds")
# (13a) The sanitizer, through the real update path. Every case is read back
# out of the sidecar FILE, so "the key is gone" is a fact about storage and
# not about a return value.
STONE = make_prop("smoke stone", ["full"], height_m=0.6)


def stored_factor(pid):
    """The RAW sidecar value, or the string 'absent' — the two states the rule
    distinguishes, in one comparable answer."""
    meta = props.read_sidecar(pid)
    return meta["sway_factor"] if "sway_factor" in meta else "absent"


# Since 66b4b7d8 creation writes an EXPLICIT 0.0 (furniture is the normal
# case; the absent-key 1.0 default is the vegetation-era LEGACY reading).
check("a fresh prop stores the explicit 0.0", stored_factor(STONE), 0.0)
props.update_prop(STONE, {"sway_factor": 0})
check("0.0 is a legal, STORED value — the whole point of the field",
      stored_factor(STONE), 0.0)
props.update_prop(STONE, {"sway_factor": 0.333})
check("three decimals round to two", stored_factor(STONE), 0.33)
props.update_prop(STONE, {"sway_factor": 5})
check("above the range clamps to 1.0 — and 1.0 is the DEFAULT, so the key goes",
      stored_factor(STONE), "absent")
props.update_prop(STONE, {"sway_factor": -2})
check("below the range clamps to the legal 0.0", stored_factor(STONE), 0.0)
props.update_prop(STONE, {"sway_factor": 1})
check("an exact 1.0 is never stored", stored_factor(STONE), "absent")
props.update_prop(STONE, {"sway_factor": 0.25})
props.update_prop(STONE, {"sway_factor": "junk"})
check("junk clears the key instead of storing NaN",
      stored_factor(STONE), "absent")
props.update_prop(STONE, {"sway_factor": 0.25})
props.update_prop(STONE, {"sway_factor": ""})
check("the emptied admin field clears the key too",
      stored_factor(STONE), "absent")
props.update_prop(STONE, {"sway_factor": 0.25})
props.update_prop(STONE, {"name": "smoke stone"})
check("a patch that does not name the field leaves it alone",
      stored_factor(STONE), 0.25)
# 0.004 rounds to 0.0 — legal here, unlike the terrain catalog numbers, where a
# value that rounds to zero says nothing. Zero IS the statement in this field.
props.update_prop(STONE, {"sway_factor": 0.004})
check("a value that rounds to zero really becomes the stored 0.0",
      stored_factor(STONE), 0.0)
props.update_prop(STONE, {"sway_factor": 0.25})
check("the effective read answers the stored value",
      props.prop_scatter_facts(STONE).get("sway_factor"), 0.25)
# A LEGACY sidecar has no key at all — modelled by writing the default,
# which the sanitizer stores as absence (the one-representation rule).
props.update_prop(TREE, {"sway_factor": 1})
check("…and the legacy DEFAULT where nothing is stored",
      props.prop_scatter_facts(TREE).get("sway_factor"),
      props.SWAY_FACTOR_DEFAULT)
check("a hand-edited NaN bends at the default, not at NaN",
      props.sway_factor_of({"sway_factor": float("nan")}),
      props.SWAY_FACTOR_DEFAULT)
check("the admin record always reports the EFFECTIVE factor",
      props.get_prop(TREE).get("sway_factor"), props.SWAY_FACTOR_DEFAULT)

# (13b) The payload. Same enrichment as [12], PAYLOAD ONLY, and the default
# travels as ABSENCE so no client has to tell "no factor" from "the full one".
props.update_prop(STONE, {"sway_factor": 0.0})
_vs = terrain.save_area(
    {"kind": "grass", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 3,
                           "model": f"/assets/props/{STONE}/model"},
                          {"density_per_100m2": 3,
                           "model": f"/assets/props/{TREE}/model"},
                          {"density_per_100m2": 3},
                          {"density_per_100m2": 3, "model": FOREIGN}]}})
_sway_entries = next(
    a["meta"]["scatter"] for a in terrain.with_scatter_props(terrain.list_areas())
    if a["id"] == _vs["id"])
check("the stone's 0.0 rides along", _sway_entries[0].get("sway_factor"), 0.0)
check("a prop at the default sends no key",
      "sway_factor" in _sway_entries[1], False)
check("a plain tuft entry sends no key", "sway_factor" in _sway_entries[2], False)
check("a foreign URL sends no key", "sway_factor" in _sway_entries[3], False)
_stored_sway = next(a["meta"]["scatter"] for a in terrain.list_areas()
                    if a["id"] == _vs["id"])
check("nothing of it is stored on the area",
      [sorted(e) for e in _stored_sway],
      [["density_per_100m2", "model"], ["density_per_100m2", "model"],
       ["density_per_100m2"], ["density_per_100m2", "model"]])
props.update_prop(STONE, {"sway_factor": 0.4})
_again = next(
    a["meta"]["scatter"] for a in terrain.with_scatter_props(terrain.list_areas())
    if a["id"] == _vs["id"])
check("a changed factor reaches the next payload without touching the area",
      _again[0].get("sway_factor"), 0.4)


# RED COUNTER-PROBE: the rule that makes 0.0 legal is exactly the one a
# copy of the terrain-catalog sanitizer would get wrong — there a value of 0
# says nothing and loses its key, which is how a still stone starts waving.
def mutant_zero_says_nothing(value):
    """Mutant: the `_clamped_meta_number` rule, applied unchanged."""
    num = float(value)
    if num <= 0:
        return "absent"
    v = round(min(max(num, 0.0), 1.0), 2)
    return "absent" if v <= 0 else v


props.update_prop(STONE, {"sway_factor": 0})
differs("mutant 'zero says nothing' drops the very value the field is for",
        mutant_zero_says_nothing(0), stored_factor(STONE))
check("the mutant would really leave no key", mutant_zero_says_nothing(0),
      "absent")
check("…so its stone would take the default and wave",
      props.sway_factor_of({}), props.SWAY_FACTOR_DEFAULT)

print("[14] meta.stroke whitelist — the recipe of a line-drawn area")

LINE = [[0, 0], [10, 0]]


def stroke_of(recipe):
    return terrain.sanitize_area(
        {"kind": "water", "polygon": SQUARE,
         "meta": {"stroke": recipe}})["meta"]["stroke"]


check("the bare recipe survives as sent",
      stroke_of({"points": LINE, "width_m": 3}),
      {"points": [[0.0, 0.0], [10.0, 0.0]], "width_m": 3.0})
check("junk keys inside the recipe are dropped",
      stroke_of({"points": LINE, "width_m": 3, "colour": "red"}),
      {"points": [[0.0, 0.0], [10.0, 0.0]], "width_m": 3.0})
for style in terrain.STROKE_STYLES:
    check(f"style {style!r} is kept",
          stroke_of({"points": LINE, "width_m": 3, "style": style}).get("style"),
          style)
check("a style is trimmed",
      stroke_of({"points": LINE, "width_m": 3, "style": "  wavy  "})["style"],
      "wavy")
for bad in ("dotted", "", 7, None, ["jagged"]):
    check(f"style {bad!r} loses the key",
          "style" in stroke_of({"points": LINE, "width_m": 3, "style": bad}),
          False)
for raw, want in ((0.5, 2.0), (2, 2.0), (10.567, 10.57), (100, 100.0),
                  (500, 100.0), ("8", 8.0)):
    check(f"spacing {raw!r} -> {want}",
          stroke_of({"points": LINE, "width_m": 3, "spacing_m": raw})["spacing_m"],
          want)
for raw, want in ((0, 0.5), (-3, 0.5), (0.789, 0.79), (30, 30.0), (100, 30.0)):
    check(f"amplitude {raw!r} -> {want}",
          stroke_of({"points": LINE, "width_m": 3,
                     "amplitude_m": raw})["amplitude_m"], want)
for bad in (float("nan"), float("inf"), None, "wide", ["2"]):
    check(f"spacing/amplitude {bad!r} lose their keys",
          [k for k in stroke_of({"points": LINE, "width_m": 3,
                                 "spacing_m": bad, "amplitude_m": bad})],
          ["points", "width_m"])
check("a full recipe travels whole",
      stroke_of({"points": LINE, "width_m": 3.456, "style": "jagged",
                 "spacing_m": 12, "amplitude_m": 1.5}),
      {"points": [[0.0, 0.0], [10.0, 0.0]], "width_m": 3.46,
       "style": "jagged", "spacing_m": 12.0, "amplitude_m": 1.5})
raises_value_error("a recipe that is not an object raises",
                   lambda: stroke_of("a line"))
raises_value_error("a recipe without a width raises",
                   lambda: stroke_of({"points": LINE}))
for bad in (0, -2, float("nan"), "wide"):
    raises_value_error(f"width {bad!r} raises",
                       lambda bad=bad: stroke_of({"points": LINE, "width_m": bad}))
raises_value_error("one point is not a line",
                   lambda: stroke_of({"points": [[0, 0]], "width_m": 3}))
check("MAX_STROKE_POINTS line points accepted",
      len(stroke_of({"points": [[i, i]
                                for i in range(terrain.MAX_STROKE_POINTS)],
                     "width_m": 3})["points"]), 1024)
raises_value_error(
    "one line point more raises",
    lambda: stroke_of({"points": [[i, i]
                                  for i in range(terrain.MAX_STROKE_POINTS + 1)],
                       "width_m": 3}))
raises_value_error("a junk vertex raises",
                   lambda: stroke_of({"points": [[0, 0], {"x": 1}], "width_m": 3}))
raises_value_error(
    "a line coordinate out of range raises",
    lambda: stroke_of({"points": [[0, 0], [1e9, 0]], "width_m": 3}))
raises_value_error(
    "a non-finite line coordinate raises",
    lambda: stroke_of({"points": [[0, 0], [float("nan"), 0]], "width_m": 3}))
check("foreign meta keys survive next to the recipe",
      terrain.sanitize_area({"kind": "water", "polygon": SQUARE,
                             "meta": {"foo": 1,
                                      "stroke": {"points": LINE,
                                                 "width_m": 3}}})["meta"],
      {"foo": 1, "stroke": {"points": [[0.0, 0.0], [10.0, 0.0]],
                            "width_m": 3.0}})

_str = terrain.save_area(
    {"kind": "water", "polygon": SQUARE,
     "meta": {"stroke": {"points": LINE, "width_m": 3, "style": "wavy",
                         "spacing_m": 8, "amplitude_m": 2}}})
check("the recipe survives the save/read round trip",
      next(a["meta"] for a in terrain.list_areas() if a["id"] == _str["id"]),
      {"stroke": {"points": [[0.0, 0.0], [10.0, 0.0]], "width_m": 3.0,
                  "style": "wavy", "spacing_m": 8.0, "amplitude_m": 2.0},
       "water_level": 0.0})

for _a in terrain.list_areas():
    terrain.delete_area(_a["id"])

print("[15] ground_offset_m — the prop's own sink, stored and shipped")
# (15a) The sanitizer, again through the real update path and read back out of
# the sidecar FILE. Same one-representation law as [13], with the default at
# the OTHER end of the range: here 0.0 is what says nothing, so 0.0 is the
# value that must NOT be stored.
SINKER = make_prop("smoke fir", ["full"], height_m=8.0)


def stored_sink(pid):
    meta = props.read_sidecar(pid)
    return meta["ground_offset_m"] if "ground_offset_m" in meta else "absent"


check("a fresh prop stores no offset at all", stored_sink(SINKER), "absent")
props.update_prop(SINKER, {"ground_offset_m": -0.2})
check("a real sink is stored as it was typed", stored_sink(SINKER), -0.2)
props.update_prop(SINKER, {"ground_offset_m": -0.207})
check("three decimals round to centimetres", stored_sink(SINKER), -0.21)
props.update_prop(SINKER, {"ground_offset_m": 0.354})
check("…and a lift the same way", stored_sink(SINKER), 0.35)
props.update_prop(SINKER, {"ground_offset_m": -99})
check("below the range clamps to the limit, never refuses the record",
      stored_sink(SINKER), -5.0)
props.update_prop(SINKER, {"ground_offset_m": 99})
check("above the range clamps too", stored_sink(SINKER), 5.0)
props.update_prop(SINKER, {"ground_offset_m": 0})
check("an exact 0.0 is never stored — absence IS the statement",
      stored_sink(SINKER), "absent")
props.update_prop(SINKER, {"ground_offset_m": -0.004})
check("a value that rounds to zero is zero, and zero is absence",
      stored_sink(SINKER), "absent")
props.update_prop(SINKER, {"ground_offset_m": -0.2})
props.update_prop(SINKER, {"ground_offset_m": "junk"})
check("junk clears the key instead of storing NaN", stored_sink(SINKER), "absent")
props.update_prop(SINKER, {"ground_offset_m": -0.2})
props.update_prop(SINKER, {"ground_offset_m": ""})
check("the emptied admin field clears the key too", stored_sink(SINKER), "absent")
props.update_prop(SINKER, {"ground_offset_m": -0.2})
props.update_prop(SINKER, {"name": "smoke fir"})
check("a patch that does not name the field leaves it alone",
      stored_sink(SINKER), -0.2)
check("a hand-edited NaN stands ON the ground, not at NaN",
      props.ground_offset_of({"ground_offset_m": float("nan")}),
      props.GROUND_OFFSET_DEFAULT)
check("the effective read answers the stored value",
      props.prop_scatter_facts(SINKER).get("ground_offset_m"), -0.2)
check("a prop without the key reads the default",
      props.prop_scatter_facts(TREE).get("ground_offset_m"),
      props.GROUND_OFFSET_DEFAULT)
check("the admin record always reports the EFFECTIVE offset",
      props.get_prop(TREE).get("ground_offset_m"), props.GROUND_OFFSET_DEFAULT)

# (15b) The payload. The same absence law as the wind factor: with the fir at
# −0.2 and the tree untouched, only the fir's entry carries a key, and the
# client seats every instance of it at heightAt(x, z) − 0.2.
_gs = terrain.save_area(
    {"kind": "grass", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 3,
                           "model": f"/assets/props/{SINKER}/model"},
                          {"density_per_100m2": 3,
                           "model": f"/assets/props/{TREE}/model"},
                          {"density_per_100m2": 3},
                          {"density_per_100m2": 3, "model": FOREIGN}]}})
_sink_entries = next(
    a["meta"]["scatter"] for a in terrain.with_scatter_props(terrain.list_areas())
    if a["id"] == _gs["id"])
check("the fir's −0.2 rides along", _sink_entries[0].get("ground_offset_m"), -0.2)
check("a prop that stands on the ground sends no key",
      "ground_offset_m" in _sink_entries[1], False)
check("a plain tuft entry sends no key",
      "ground_offset_m" in _sink_entries[2], False)
check("a foreign URL sends no key",
      "ground_offset_m" in _sink_entries[3], False)
_stored_sink = next(a["meta"]["scatter"] for a in terrain.list_areas()
                    if a["id"] == _gs["id"])
check("nothing of it is stored on the area",
      [sorted(e) for e in _stored_sink],
      [["density_per_100m2", "model"], ["density_per_100m2", "model"],
       ["density_per_100m2"], ["density_per_100m2", "model"]])
props.update_prop(SINKER, {"ground_offset_m": -0.35})
_sink_again = next(
    a["meta"]["scatter"] for a in terrain.with_scatter_props(terrain.list_areas())
    if a["id"] == _gs["id"])
check("a changed offset reaches the next payload without touching the area",
      _sink_again[0].get("ground_offset_m"), -0.35)


# RED COUNTER-PROBE: the wind factor's rule, copied one field over. There the
# DEFAULT is 1.0 and 0.0 is a real answer; here it is the other way round, so
# the copy stores a 0.0 and drops a 1.0 — a prop dialled a metre up would lose
# its offset, and one dialled to 0 would carry a key that means nothing.
def mutant_sway_rule(value):
    """Mutant: `_coerce_sway_factor`'s default applied to this field."""
    v = round(min(max(float(value), -5.0), 5.0), 2)
    return "absent" if v == 1.0 else v


props.update_prop(SINKER, {"ground_offset_m": 1.0})
differs("mutant 'the default is 1.0' throws away a real one-metre lift",
        mutant_sway_rule(1.0), stored_sink(SINKER))
check("the mutant would really leave no key", mutant_sway_rule(1.0), "absent")
check("the truth stores the metre", stored_sink(SINKER), 1.0)
differs("…and it keeps a 0.0 the payload law forbids",
        mutant_sway_rule(0), "absent")

for _a in terrain.list_areas():
    terrain.delete_area(_a["id"])

# ── [16] SEASON-tagged variants move terrain_sig (E2c) ──────────────────
# The scatter entry carries the prop's ACTIVE variants, and since E2c a
# variant may be tagged for a season — so the served block changes while every
# stored row stays put. `terrain_sig` hashes the ENRICHED block, so it has to
# follow. Fixture (a smoke has no world clock): the shipped calendar — 4
# seasons × 30 days, season starts 0/30/60/90 — and a hand-picked instant,
# day-of-year 35 = day 5 of SUMMER, 95 = day 5 of WINTER, each at noon:
# (D - 1) × 86400 + 43200.
print("\n[16] season-tagged variants reach a polling client (E2c)")
from app.core import game_time as _gt  # noqa: E402
from app.core import timeutils as _tu  # noqa: E402


def _set_season(day_of_year):
    _gt._CALENDAR_CACHE = _gt.Calendar.default()
    _now = _gt.GameTime((day_of_year - 1) * _gt.DAY_SECONDS + 12 * 3600)
    _tu.game_time = lambda: _now


_season_area = terrain.save_area(
    {"kind": "grass", "polygon": SQUARE,
     "meta": {"scatter": [{"density_per_100m2": 4,
                           "model": f"/assets/props/{BUSH}/model"}]}})


def _bush_maps():
    entry = next(a["meta"]["scatter"][0]
                 for a in terrain.with_scatter_props(terrain.list_areas())
                 if a["id"] == _season_area["id"])
    return entry.get("model_variants") or [entry.get("variants")]


_set_season(95)
_sig_untagged = terrain.terrain_sig()
check("untagged: both bush variants are published", len(_bush_maps()), 2)
_set_season(35)
check("…and the signature does not care which season it is",
      terrain.terrain_sig(), _sig_untagged)
props.set_variant_seasons(BUSH, _bush_v1, ["Winter"])
_sig_summer = terrain.terrain_sig()
check("summer: the winter variant leaves the entry", len(_bush_maps()), 1)
check("…and the signature moved, without a row being touched",
      _sig_summer != _sig_untagged, True)
_set_season(95)
check("winter: it is back", len(_bush_maps()), 2)
check("…and the winter signature is the untagged one again "
      "(the payload is identical)", terrain.terrain_sig(), _sig_untagged)
props.set_variant_seasons(BUSH, _bush_v1, [])
terrain.delete_area(_season_area["id"])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
