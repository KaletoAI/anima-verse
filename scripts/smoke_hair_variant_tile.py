#!/usr/bin/env python3
"""The tile of a HAAR variant (``app/core/hair_variant_tile.py``) — strand-hair plan 2026-11-13, Task 14 (spec
§ 6.3.4). Expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_hair_variant_tile.py

Pure numpy + PIL: no server, no world, no storage, no network.

Fixture: the body is a grey sphere of radius 0.09 m at (0, 1.60, 0) (``smoke_hair_strands_record.sphere``, 64 x 32
lat-long: its poles and its equator points at phi 0 / 180 deg are vertices); the hair is ONE red quad card (vertex
colour linear (1, 0, 0)) at z +0.1, x [-0.02, 0.02], y [1.55, 1.65] (two triangles); size 256.

Expected (by hand):
  [1] head_centre: the top is 1.69, every sphere point is within HEAD_DEPTH_M 0.22 of it, so the box is the sphere's
      x [-0.09, 0.09], y [1.51, 1.69] -> (0, 1.60).
  [2] the PNG is 512 x 256 RGBA (front left, back right).
  [3] front, column 128 / row 128: its centre is x = 0 - 0.25 + 128.5 * 0.5 / 256 = 0.00098, y = 1.60 + 0.25 -
      128.5 * 0.5 / 256 = 1.59902 — on the card (z 0.1), in front of the sphere (z <= 0.09): red. The card faces
      +z, so its shade is 1 and the pixel is sRGB (255, 0, 0), alpha 255.
  [4] back, the same pixel (column 256 + 128): x mirrored = 0 + 0.25 - 0.25098 = -0.00098; seen from -z the sphere
      (z -0.09) is nearer than the card (z +0.1): grey. BODY_GREY 0.42 linear = sRGB 1.055 * 0.42 ^ (1 / 2.4) -
      0.055 = 0.6799 -> 173 at shade 1; the sphere's facet there is a little off the axis (its normal within
      2.8 deg of -z: |n . view| >= 0.9988), so the pixel is grey, R = G = B in 170 .. 173.
  [5] the card's pixels in the front: u = (x + 0.25) * 512 -> [117.76, 138.24], centres c + 0.5 inside: columns
      118 .. 137 (20); v = (1.85 - y) * 512 -> [102.4, 153.6]: rows 102 .. 153 (52) -> exactly 20 x 52 = 1040 red
      pixels; column 117 of row 128 is the sphere (grey), column 118 red.
  [6] a corner pixel (0, 0) is outside the sphere (x -0.249, y 1.849): transparent (alpha 0).
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def main():
    from PIL import Image
    from smoke_hair_strands_record import sphere
    from app.core import hair_variant_tile as hvt
    BP, BF = sphere((0.0, 1.60, 0.0), 0.09, 64, 32)
    V = np.array([[-0.02, 1.55, 0.1], [0.02, 1.55, 0.1], [0.02, 1.65, 0.1], [-0.02, 1.65, 0.1]])
    F = np.array([[0, 1, 2], [0, 2, 3]])
    C = np.tile([1.0, 0.0, 0.0, 1.0], (4, 1))

    cx, cy = hvt.head_centre(BP)
    check(abs(cx) < 1e-9 and abs(cy - 1.60) < 1e-9, f"[1] head centre (0, 1.60) (got ({cx:.6f}, {cy:.6f}))")

    png = hvt.tile_png(V, F, C, BP, BF, size=256)
    im = Image.open(io.BytesIO(png))
    check(im.size == (512, 256) and im.mode == "RGBA", f"[2] PNG 512 x 256 RGBA (got {im.size} {im.mode})")
    a = np.asarray(im)
    check(tuple(a[128, 128]) == (255, 0, 0, 255), f"[3] front (128, 128) red (got {tuple(a[128, 128])})")
    b = a[128, 256 + 128]
    check(b[0] == b[1] == b[2] and 170 <= b[0] <= 173 and b[3] == 255,
          f"[4] back (128, 128) grey 170 .. 173 (got {tuple(b)})")
    red = (a[:, :256, 0] == 255) & (a[:, :256, 1] == 0) & (a[:, :256, 2] == 0) & (a[:, :256, 3] == 255)
    rows, cols = np.nonzero(red)
    check(int(red.sum()) == 1040 and (rows.min(), rows.max(), cols.min(), cols.max()) == (102, 153, 118, 137),
          f"[5] 1040 red pixels, rows 102 .. 153, columns 118 .. 137 (got {int(red.sum())}, "
          f"rows {rows.min()} .. {rows.max()}, columns {cols.min()} .. {cols.max()})")
    g = a[128, 117]
    check(g[0] == g[1] == g[2] and g[3] == 255 and tuple(a[128, 118][:3]) == (255, 0, 0),
          f"[5] column 117 grey ({tuple(g)}), 118 red ({tuple(a[128, 118])})")
    check(a[0, 0, 3] == 0 and a[0, 511, 3] == 0, "[6] the corners are transparent")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
