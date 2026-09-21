#!/usr/bin/env python3
"""Smoke run for ``scene_recipe._map_water_ref`` (IMG-8): the pre-parsed ring
version must answer EXACTLY what the old ``point_in_polygon`` version answered,
and must be dramatically cheaper.

No server, no network, no world DB (``paths.init`` on a throwaway directory).
The old implementation is re-stated below, literally, and both are run over the
same synthetic hulls and water areas.

Usage:  ./.venv/bin/python scripts/smoke_map_water_ref.py

THE RULE
---------------------------------------------------------------------------
``_map_water_ref`` is a MAJORITY-AREA test: it samples the room hull's bounding
box on a fixed 32 x 32 lattice AT CELL CENTRES, keeps the probes inside the
hull, and reports the water area that holds STRICTLY more than half of them —
later paint order wins a tie.  Speeding it up must not move a single answer,
because the same rule is baked into the terrain layers next to it.

What changed: the rings are parsed ONCE (``heightfield._ring`` /
``_inside_ring``, the proven pre-parsed primitives) instead of once PER PROBE,
and a water area whose bounding box is strictly disjoint from the hull's box
skips its 1024 probes. Neither can change an answer:
  * ``_inside_ring`` is the same ray-casting expression, in the same order, on
    the same floats -> identical result per probe;
  * a point inside a ring lies inside that ring's bounding box, so a strictly
    disjoint box cannot hold one, i.e. the skipped share is 0 and 0 is never a
    majority.  Touching boxes are NOT skipped, so no borderline case moves.

Hand-derived expectations
---------------------------------------------------------------------------
Every case states what the MAJORITY RULE says, independently of both
implementations; the old version is then asserted to agree, so a case that
contradicts the rule shows up as two failures, not as a silent drift.

  [1] hull fully inside one lake            -> that lake (share 1.0)
  [2] hull fully outside every lake         -> None (share 0.0)
  [3] hull half on the lake (exactly half)  -> None (a majority is STRICTLY
      more than half; the lattice is symmetric here, so 512 of 1024 probes)
  [4] hull 3/4 on the lake                  -> that lake
  [5] two overlapping lakes, hull inside both -> the LATER one in paint order
  [6] concave (L-shaped) hull over a lake covering only the notch -> None; the
      probes outside the hull do not count, which is the whole point of the
      two-stage sampling
  [7] a hull point exactly ON the lake's edge (hull == lake) -> the lake:
      ray casting is half-open, both sides answer identically
  [8] a degenerate hull (zero area) -> None
  [9] a malformed ring in the water list is skipped, the good lake still wins
 [10] no water at all -> None

Timing: 5 lakes x 60 vertices x 10 rooms, the scale the finding measured.
"""
import os
import sys
import tempfile
import time
from math import cos, pi, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="water-ref-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="water-ref-storage-"))

from app.core import scene_recipe  # noqa: E402
from app.core.world_geometry import point_in_polygon  # noqa: E402

FAILED = []
SAMPLES = scene_recipe.MAP_WATER_SAMPLES


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


def old_map_water_ref(polygon, waters):
    """The implementation as of commit c7981bac — point_in_polygon per probe."""
    if not polygon or len(polygon) < 3 or not waters:
        return None
    xs = [float(p[0]) for p in polygon]
    zs = [float(p[1]) for p in polygon]
    min_x, max_x, min_z, max_z = min(xs), max(xs), min(zs), max(zs)
    if max_x <= min_x or max_z <= min_z:
        return None
    step_x = (max_x - min_x) / SAMPLES
    step_z = (max_z - min_z) / SAMPLES
    probes = []
    for j in range(SAMPLES):
        pz = min_z + (j + 0.5) * step_z
        for i in range(SAMPLES):
            px = min_x + (i + 0.5) * step_x
            if point_in_polygon(px, pz, polygon):
                probes.append((px, pz))
    if not probes:
        return None
    best = None
    best_share = 0.5
    for area in waters:
        ring = area.get("polygon")
        inside = sum(1 for px, pz in probes if point_in_polygon(px, pz, ring))
        share = inside / len(probes)
        if share > 0.5 and share >= best_share:
            best_share = share
            best = {"area_id": str(area.get("id") or ""),
                    "kind": str(area.get("kind") or "")}
    return best


def rect(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def lake(ident, poly, kind="water"):
    return {"id": ident, "kind": kind, "polygon": poly}


def circle(cx, cz, r, n):
    return [[cx + r * cos(2 * pi * k / n), cz + r * sin(2 * pi * k / n)]
            for k in range(n)]


CASES = [
    # label, hull, waters, expected id (None = no reference)
    ("1 inside one lake", rect(0, 0, 10, 10),
     [lake("L1", rect(-50, -50, 50, 50))], "L1"),
    ("2 outside every lake", rect(0, 0, 10, 10),
     [lake("L1", rect(100, 100, 150, 150))], None),
    ("3 exactly half", rect(0, 0, 10, 10),
     [lake("L1", rect(-5, -5, 5, 15))], None),
    ("4 three quarters", rect(0, 0, 10, 10),
     [lake("L1", rect(-5, -5, 7.5, 15))], "L1"),
    ("5 two overlapping lakes -> later wins", rect(0, 0, 10, 10),
     [lake("L1", rect(-50, -50, 50, 50)), lake("L2", rect(-40, -40, 40, 40))],
     "L2"),
    # L-shaped hull: the lake covers only the NOTCH that the hull cut away.
    ("6 concave hull, lake in the notch",
     [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]],
     [lake("L1", rect(4.5, 4.5, 9.5, 9.5))], None),
    ("7 hull == lake (points on the edge)", rect(0, 0, 10, 10),
     [lake("L1", rect(0, 0, 10, 10))], "L1"),
    ("8 degenerate hull", [[1, 1], [1, 1], [1, 1]],
     [lake("L1", rect(-50, -50, 50, 50))], None),
    ("9 malformed ring skipped", rect(0, 0, 10, 10),
     [lake("BAD", [["x", 0], [1, 1], [2, 2]]),
      lake("L1", rect(-50, -50, 50, 50))], "L1"),
    ("10 no water", rect(0, 0, 10, 10), [], None),
]

print("[A] old and new agree, and both follow the majority rule")
for label, hull, waters, expected_id in CASES:
    new = scene_recipe._map_water_ref(hull, waters)
    old = old_map_water_ref(hull, waters)
    check(f"{label}: new", (new or {}).get("area_id"), expected_id)
    check(f"{label}: old == new", old, new)

print("[B] randomised cross-check (200 hull/lake pairs)")
import random  # noqa: E402

random.seed(20260920)
mismatch = 0
for _ in range(200):
    hx, hz = random.uniform(-20, 20), random.uniform(-20, 20)
    hull = rect(hx, hz, hx + random.uniform(1, 25), hz + random.uniform(1, 25))
    waters = []
    for n in range(random.randint(0, 3)):
        lx, lz = random.uniform(-30, 30), random.uniform(-30, 30)
        waters.append(lake(f"R{n}", circle(lx, lz, random.uniform(2, 25), 12)))
    if scene_recipe._map_water_ref(hull, waters) != old_map_water_ref(hull, waters):
        mismatch += 1
check("B: mismatching pairs", mismatch, 0)

print("[C] timing — 5 lakes x 60 vertices x 10 rooms")
big_waters = [lake(f"T{k}", circle(30 * k, 0, 40, 60)) for k in range(5)]
rooms = [rect(6 * k, 0, 6 * k + 5, 5) for k in range(10)]


def _timed(fn):
    t0 = time.perf_counter()
    for hull in rooms:
        fn(hull, big_waters)
    return (time.perf_counter() - t0) * 1000.0


old_ms = _timed(old_map_water_ref)
new_ms = _timed(scene_recipe._map_water_ref)
print(f"     before: {old_ms:7.1f} ms per request")
print(f"     after:  {new_ms:7.1f} ms per request  "
      f"(factor {old_ms / max(new_ms, 1e-9):.1f})")
check("C: same answers on the timing fixture",
      [scene_recipe._map_water_ref(h, big_waters) for h in rooms],
      [old_map_water_ref(h, big_waters) for h in rooms])
check("C: the new version is faster", new_ms < old_ms, True)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
sys.exit(0)
