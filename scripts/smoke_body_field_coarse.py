#!/usr/bin/env python3
"""Smoke: the body solid of a COARSE mesh is filled — its inside reads negative (app/core/body_field.py
``_dense_samples``, review 06 part C #2).

Usage:  ./.venv/bin/python scripts/smoke_body_field_coarse.py

No storage, no world DB, no server: numpy on closed cubes (12 triangles, outward winding) at ``garment_fit.VOX_M``
= 3.4 mm.

The surface used to be voxelised only at the 5 x 5 barycentric samples of every triangle: spacing = edge / 4. A cube
of edge 4 cm has face triangles with legs 4 cm and a hypotenuse of 5.66 cm -> sample gaps of 10 - 14 mm, ~3 - 4
voxels, which one dilation does not close; the 3-D and slice fills leaked and the centre read +19 mm (OUTSIDE).

Expected, by hand:
[1] cubes centred at (0, 1, 0) with half-edge h = 0.02, 0.05, 0.10 m: the centre is h from every face, so the field
    there is -h (inside); allowed error one voxel (3.4 mm — the EDT inside is voxel-exact to about a voxel, spheres
    measured ±1.4 mm).
[2] the point (h + 0.005, 1.0, 0.0) — 5 mm outside the +x face, opposite the face's middle — lies in the exact band
    (5 mm = 1.5 voxels <= SDF_EXACT_BAND_VOX 6): its value is the exact distance to the nearest triangle, 0.005 m
    (± 1e-6): the added samples carry the right triangle index.
[3] a fine body is untouched: a cube whose face hypotenuse (its longest triangle edge) is 0.999 * 4 voxels =
    13.586 mm (edge 13.586 / sqrt 2 = 9.607 mm) needs ceil(13.586 / 3.4) = 4 steps, not more than ``SAMPLE_STEPS``
    (4): its samples are exactly ``garment_fit._surface_samples`` (same points, same order, same triangle indices).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import body_field  # noqa: E402
from app.core.garment_fit import VOX_M, _surface_samples  # noqa: E402

FAILS: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def cube(h: float, centre=(0.0, 1.0, 0.0)):
    V = np.array([[x, y, z] for x in (-h, h) for y in (-h, h) for z in (-h, h)], float) + np.array(centre)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    F = np.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))], np.int64)
    return V, F


def main() -> int:
    print("[1] + [2] coarse cubes")
    for h in (0.02, 0.05, 0.10):
        P, F = cube(h)
        solid = body_field.body_solid(P, F, vox=VOX_M)
        sdf = body_field.field(solid, (P.min(0) - 0.03, P.max(0) + 0.03))
        centre = float(sdf.sample(np.array([[0.0, 1.0, 0.0]]))[0])
        check(f"edge {2 * h:.2f} m: centre {centre * 1000:+.1f} mm = {-h * 1000:.0f} mm ± {VOX_M * 1000:.1f}",
              abs(centre + h) <= VOX_M)
        out = float(sdf.sample(np.array([[h + 0.005, 1.0, 0.0]]))[0])
        check(f"edge {2 * h:.2f} m: 5 mm outside the +x face = {out * 1000:.4f} mm", abs(out - 0.005) <= 1e-6)

    print("[3] a cube whose longest edge is 4 voxels: the 5 x 5 samples unchanged")
    P, F = cube(4 * VOX_M / math.sqrt(2) / 2 * 0.999)
    pts, tri_of = body_field._dense_samples(P, F, VOX_M)
    ref_pts, ref_tri = _surface_samples(P, F)
    check("same points, same order, same triangles", np.array_equal(pts, ref_pts) and np.array_equal(tri_of, ref_tri),
          f"{len(pts)} vs {len(ref_pts)} samples")

    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
