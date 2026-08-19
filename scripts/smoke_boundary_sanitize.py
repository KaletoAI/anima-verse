#!/usr/bin/env python3
"""Smoke check: the location boundary — sanitizer + the two v6 problems.

Usage:
    ./.venv/bin/python scripts/smoke_boundary_sanitize.py

Standalone — no server, no world DB. It calls ``world_ops._sanitize_map3d``
and the pure helpers of ``scene_recipe`` directly. Every expected number is
derived BY HAND from the v6 preamble of docs/schnittstellen-3d.md, never
read back out of a run.

WINDING (v6 Nr. 1: stored clockwise in map view). With x east and z south a
POSITIVE shoelace sum Σ(x_j·z_i − x_i·z_j)/2 means clockwise — the
convention documented in ``world_geometry``. Hand-derived on the two square
orderings of the 4 × 4 square:

  CW  (0,0) (4,0) (4,4) (0,4): terms 0, 0, 4·4−4·0 = 16, 4·4−0·4 = 16
                               → Σ = 32 → +16, kept as submitted.
  CCW (0,0) (0,4) (4,4) (4,0): terms 4·0−0·0 = 0, 0·4−0·0 = 0,
                               0·4−4·4 = −16, 4·0−4·4 = −16
                               → Σ = −32 → −16, so the list is REVERSED to
                               (4,0) (4,4) (0,4) (0,0).

CAP at 64 points — a plain head slice, the tail is dropped, nothing is
resampled. The 66-point fixture is a 32 × 5 rectangle drawn with 33 points
along each long edge: (0,0)…(32,0) eastwards at z = 0, then (32,5)…(0,5)
westwards at z = 5 (east along the top, west along the bottom = clockwise in
map view). Index 63 is the 31st point of the lower edge, x = 32 − 30 = 2, so
the survivor list ends at (2,5) and the two points (1,5) and (0,5) are gone.
The bounding box still spans x 0…32 and z 0…5 (the top edge keeps x = 0), so
the derived width is max(32, 5) = 32.

CLOSING POINT: (0,0) (4,0) (4,4) (0,4) (0,0) stores as the first four points
— the ring is closed implicitly, never by a repeated point.

CENTIMETRES: 0.004 → 0.0, 0.006 → 0.01, 4.567 → 4.57, 3.211 → 3.21.
The resulting triangle (0,0.01) (4.57,0) (4,3.21) has the shoelace terms
4·0.01 − 0·3.21 = 0.04, 0·0 − 4.57·0.01 = −0.0457 and
4.57·3.21 − 4·0 = 14.6697 → Σ = 14.664 → +7.332, i.e. already clockwise.
Its bounding box is 4.57 × 3.21, so the derived width is 4.57.

DERIVED plan_width_m (v6 Nr. 2: computed, never a dial). The L-shape
(0,0) (4,0) (4,2) (2,2) (2,4) (0,4) has the bounding box x 0…4, z 0…4 →
max(4, 4) = 4.0, and a submitted 99 is overwritten by it.

SELF-INTERSECTION (warning, not a rejection). The bow tie (0,0) (4,4) (4,0)
(0,4) has exactly two non-adjacent edge pairs: e0 (0,0)→(4,4) against e2
(4,0)→(0,4), and e1 (4,4)→(4,0) against e3 (0,4)→(0,0). e0 is the line
z = x, e2 the line x + z = 4 — they meet at (2,2), inside both segments →
self-intersecting. Its shoelace sum is 0 + 0 + (4·0 − 4·4) + (4·4 − 0·0) = 0,
so the sanitizer neither reverses nor drops it; the bounding box is 4 × 4 →
width 4.0. The L-shape has no crossing pair.

ROOM OUTSIDE THE BOUNDARY. Rooms are stored in LOCAL METRES since v6 Nr. 2,
the same frame the boundary uses — so both sides of the test arrive without
conversion and ``rooms_outside_boundary`` needs no ``extent`` any more. The
fixture is the L CENTRED on the pin: (−2,−2) (2,−2) (2,0) (0,0) (0,2) (−2,2)
— the same polygon translated by (−2,−2), so bounding box, winding (+12) and
derived width 4.0 are unchanged. Its interior is the 4 × 4 square MINUS the
notch quadrant x ∈ [0,2], z ∈ [0,2].

The three rooms below are the METRIC equivalents of the fractions this file
used before the metric wave (f → (f − 0.5) × 4 for x/y, f × 4 for w/d), i.e.
exactly the same rectangles — the expected verdicts are unchanged:

  room "notch"  x 0.4 y 0.4 w 1.2 d 1.2 → 0.4 … 1.6 on both axes, i.e.
                entirely inside the notch → all four corners out → reported.
  room "wide"   x −1.8 y −1.8 w 1.2 d 1.2 → −1.8 … −0.6 on both axes,
                deep inside the wide arm → silent.
  room "flush"  x −2 y −2 w 2 d 2 → −2 … 0 on both axes: two corners
                lie ON the boundary and one is the notch corner (0,0), also
                ON it. Edge-inclusive → silent (a plan drawn flush against
                the boundary is legal).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import scene_recipe, world_geometry  # noqa: E402
from app.core.world_ops import _sanitize_map3d  # noqa: E402

FAILURES = []

L_SHAPE = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]
L_CENTRED = [[-2, -2], [2, -2], [2, 0], [0, 0], [0, 2], [-2, 2]]
BOW_TIE = [[0, 0], [4, 4], [4, 0], [0, 4]]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def sanitize(**map3d):
    return _sanitize_map3d(map3d)


# ── A: winding, cap, closing point, centimetres ────────────────────────────

def test_winding() -> None:
    print("Winding — clockwise in map view = positive shoelace")
    cw = sanitize(boundary=[[0, 0], [4, 0], [4, 4], [0, 4]])
    check("a clockwise ring is stored as submitted",
          cw["boundary"] == [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]],
          str(cw.get("boundary")))
    ccw = sanitize(boundary=[[0, 0], [0, 4], [4, 4], [4, 0]])
    check("a counter-clockwise ring is reversed",
          ccw["boundary"] == [[4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]],
          str(ccw.get("boundary")))


def test_cap_and_closing_point() -> None:
    print("Cap at 64 points, implicit closing")
    ring = ([[float(i), 0.0] for i in range(33)]
            + [[32.0 - i, 5.0] for i in range(33)])
    check("fixture really has 66 points", len(ring) == 66, str(len(ring)))
    out = sanitize(boundary=ring)
    check("capped to 64 points", len(out["boundary"]) == 64,
          str(len(out["boundary"])))
    check("the head survives unchanged, the tail is dropped",
          out["boundary"][0] == [0.0, 0.0]
          and out["boundary"][63] == [2.0, 5.0], str(out["boundary"][-3:]))
    check("derived width = max(32, 5) = 32", out["plan_width_m"] == 32.0,
          str(out.get("plan_width_m")))
    closed = sanitize(boundary=[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]])
    check("an explicit closing point is dropped",
          closed["boundary"] == [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0],
                                 [0.0, 4.0]], str(closed.get("boundary")))


def test_centimetres() -> None:
    print("Rounding to the centimetre")
    out = sanitize(boundary=[[0.004, 0.006], [4.567, 0.0], [4.0, 3.211]])
    check("points round to 2 decimals",
          out["boundary"] == [[0.0, 0.01], [4.57, 0.0], [4.0, 3.21]],
          str(out.get("boundary")))
    check("derived width = max(4.57, 3.21) = 4.57",
          out["plan_width_m"] == 4.57, str(out.get("plan_width_m")))


def test_malformed() -> None:
    print("Malformed input drops the field, never the rest")
    for label, value in (("two points", [[0, 0], [1, 1]]),
                         ("not a list", "0,0 1,1 2,2"),
                         ("empty", []),
                         ("non-numeric points", [["a", "b"], [1, 1], [2, 2]]),
                         ("infinities", [[float("inf"), 0], [1, 1], [2, 2]])):
        out = sanitize(plan_width_m=12, boundary=value)
        check(f"{label}: no boundary, submitted plan_width_m untouched",
              "boundary" not in out and out.get("plan_width_m") == 12.0,
              str(out))
    zero = sanitize(plan_width_m=12, boundary=[[3, 3], [3, 3], [3, 3]])
    check("a boundary without extent encloses nothing and is dropped",
          "boundary" not in zero and zero.get("plan_width_m") == 12.0,
          str(zero))


# ── B: plan_width_m is derived, not submitted ──────────────────────────────

def test_derived_width() -> None:
    print("plan_width_m is a computed quantity (v6 Nr. 2)")
    out = sanitize(plan_width_m=99, boundary=L_SHAPE)
    check("the L-shape derives 4.0 and overwrites the submitted 99",
          out["plan_width_m"] == 4.0, str(out.get("plan_width_m")))
    check("the L-shape keeps its 6 points and its winding",
          out["boundary"] == [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0],
                              [2.0, 2.0], [2.0, 4.0], [0.0, 4.0]],
          str(out.get("boundary")))
    plain = sanitize(plan_width_m=99)
    check("without a boundary the submitted width stands",
          plain["plan_width_m"] == 99.0, str(plain.get("plan_width_m")))


# ── C: the two problems ────────────────────────────────────────────────────

def test_self_intersection() -> None:
    print("boundary_self_intersection")
    check("the bow tie crosses itself",
          world_geometry.polygon_self_intersects(BOW_TIE) is True)
    check("the L-shape does not",
          world_geometry.polygon_self_intersects(L_SHAPE) is False)
    check("a square does not",
          world_geometry.polygon_self_intersects(
              [[0, 0], [4, 0], [4, 4], [0, 4]]) is False)
    check("a degenerate outline reports nothing",
          world_geometry.polygon_self_intersects([[0, 0], [1, 1]]) is False)
    saved = sanitize(boundary=BOW_TIE)
    check("the sanitizer stores the bow tie unchanged (warning, not error)",
          saved["boundary"] == [[0.0, 0.0], [4.0, 4.0], [4.0, 0.0],
                                [0.0, 4.0]]
          and saved["plan_width_m"] == 4.0, str(saved))


def _recipe(room_id: str, x: float, y: float, w: float, d: float) -> dict:
    """A room recipe as ``compose_recipe`` leaves it: the rectangle already
    resolved into an outline of absolute LOCAL METRES."""
    return {"room_id": room_id, "level": 0,
            "outline": [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]}


def test_room_outside_boundary() -> None:
    print("room_outside_boundary")
    notch = _recipe("notch", 0.4, 0.4, 1.2, 1.2)
    wide = _recipe("wide", -1.8, -1.8, 1.2, 1.2)
    flush = _recipe("flush", -2.0, -2.0, 2.0, 2.0)
    check("the room in the notch is reported",
          scene_recipe.rooms_outside_boundary([notch], L_CENTRED)
          == ["notch"])
    check("the room in the wide arm is not",
          scene_recipe.rooms_outside_boundary([wide], L_CENTRED) == [])
    check("a room flush against the boundary is not (edge-inclusive)",
          scene_recipe.rooms_outside_boundary([flush], L_CENTRED) == [])
    check("ids come back in recipe order",
          scene_recipe.rooms_outside_boundary(
              [wide, notch, flush], L_CENTRED) == ["notch"])
    check("without a boundary nothing is checked",
          scene_recipe.rooms_outside_boundary([notch], None) == []
          and scene_recipe.rooms_outside_boundary([notch], [[0, 0]]) == [])


def test_problems_wiring() -> None:
    print("_problems reports both findings")
    location = {"id": "loc"}
    recipes = [_recipe("notch", 0.4, 0.4, 1.2, 1.2),
               _recipe("wide", -1.8, -1.8, 1.2, 1.2)]
    ok = scene_recipe._problems(location, {"boundary": L_CENTRED,
                                           "plan_width_m": 4.0},
                                set(), [], [recipes[1]])
    check("a clean location has no problem", ok == [], str(ok))
    out = scene_recipe._problems(location, {"boundary": L_CENTRED,
                                            "plan_width_m": 4.0},
                                 set(), [], recipes)
    kinds = [p["kind"] for p in out]
    check("the stray room is reported once", kinds == ["room_outside_boundary"],
          str(kinds))
    if kinds == ["room_outside_boundary"]:
        entry = out[0]
        check("entry carries location, ids and count",
              entry["location_id"] == "loc" and entry["room_ids"] == ["notch"]
              and entry["room_count"] == 1, str(entry))
        check("the message stays free of numbers and ids",
              "notch" not in entry["message"]
              and not any(c.isdigit() for c in entry["message"]),
              entry["message"])
    bow = scene_recipe._problems(location, {"boundary": BOW_TIE},
                                 set(), [], [])
    check("the bow tie is reported as a self-intersection",
          [p["kind"] for p in bow] == ["boundary_self_intersection"], str(bow))


def main() -> int:
    test_winding()
    test_cap_and_closing_point()
    test_centimetres()
    test_malformed()
    test_derived_width()
    test_self_intersection()
    test_room_outside_boundary()
    test_problems_wiring()
    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
        return 1
    print("all boundary checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
