#!/usr/bin/env python3
"""Smoke run for painted terrain areas (Seamless World, E1 Task 4).

Throwaway storage. Hand-derived expectations:

  [1] save_area({kind: "water", polygon: [[0,0],[10,0],[10,10],[0,10]]})
      -> id starts with "ta_", z_order 0, polygon values rounded floats.
  [2] save_area with kind "nope_unknown" -> ValueError (kind must exist in
      the effective catalog).
  [3] save_area with 2 points -> ValueError; 257 points -> ValueError;
      coordinate 1e9 -> ValueError.
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
      Per entry, exactly three fields survive: density_per_100m2 (float,
      always present, junk/negative -> 0.0), height_m (float > 0, optional
      — the TARGET height the prop is scaled to) and model (non-empty
      string, optional, never truncated). Junk keys inside an entry are
      dropped. The list itself: a non-list raises (the field moved AS a
      list, so a bare object is an old client, not a guess), an entry that
      is not an object raises, more than MAX_SCATTER_ENTRIES (8) raises, an
      empty list is kept as sent ("authored to nothing"). Foreign meta keys
      next to scatter survive untouched, and the list survives a save/read
      round trip.

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
check("meta default", area1["meta"], {})
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
    "257 points raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [[i, i] for i in range(257)]}))
raises_value_error(
    "1e9 coordinate raises",
    lambda: terrain.save_area({"kind": "water",
                               "polygon": [[0, 0], [1e9, 0], [1, 1]]}))
check("256 points accepted",
      len(terrain.sanitize_area({"kind": "water",
                                 "polygon": [[i, i] for i in range(256)]})["polygon"]),
      256)

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
                               "model": "/assets/props/tree/model"}]}),
      {"scatter": [{"density_per_100m2": 12.5, "height_m": 4.0,
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
                           "model": "/assets/props/fern/model"}],
              "note": "free form"}})
check("the list survives the save/read round trip",
      next(a["meta"] for a in terrain.list_areas() if a["id"] == _scat["id"]),
      {"scatter": [{"density_per_100m2": 9.0, "height_m": 6.0,
                    "model": "/assets/props/fern/model"}],
       "note": "free form"})
terrain.delete_area(_scat["id"])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
