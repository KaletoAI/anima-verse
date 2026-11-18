"""Smoke: the shell's body z-buffer is sampled by the views' mask pixel, not by 1/2500 of the body height
(A199, review 06#4; ``garment_shell.SHELL_VERSION`` 4).

Usage:
    ./.venv/bin/python scripts/smoke_shell_zbuf_spacing.py

No server, no world DB. Derived by hand from ``garment_shell.samples`` (about 4 points per ``px``²: per face
``ceil(area / px² · 4)``, 1..600):

  [1] SHELL_VERSION 4, ZBUF_SPACING_PX 1.0.
  [2] A flat 10 x 10 grid of unit squares, each split into two triangles of area 0.5, sampled at px = 1 (one mask
      pixel, ``ZBUF_SPACING_PX`` x the frame's units per pixel): ceil(0.5 · 4) = 2 per triangle -> 4 per pixel,
      400 in all. At the old spacing on a figure 1400 px high (px = 1400 / 2500 = 0.56 pixel):
      ceil(0.5 / 0.3136 · 4) = ceil(6.378) = 7 per triangle -> 14 per pixel, 1400 in all — 3.5x the samples.
  [3] ``build_shell`` reads the spacing from the frames (``ZBUF_SPACING_PX * min(frames[w][0] ...)``) and no longer
      from the body height: at 26977eda5 the call reads ``float(np.ptp(Pu[:, 1])) / 2500``.

Measured on a synthetic 1.75 m / 1.8 m² body, figure 1400 px (A199 report): 14.7 M -> 5.1 M samples, peak RSS of
the sampling + two z-buffers 1296 -> 570 MB; no empty pixel inside the silhouette after the 3x3 maximum filter.
"""
import inspect
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_shell as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


check("[1] SHELL_VERSION 4", gs.SHELL_VERSION == 4, gs.SHELL_VERSION)
check("[1] ZBUF_SPACING_PX 1.0", gs.ZBUF_SPACING_PX == 1.0, gs.ZBUF_SPACING_PX)

n = 10
idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
P = np.stack([*np.meshgrid(np.arange(n + 1.0), np.arange(n + 1.0), indexing="ij"), np.zeros((n + 1, n + 1))],
             -1).reshape(-1, 3)
a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[:-1, 1:], idx[1:, 1:]
F = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([b, d, c], -1).reshape(-1, 3)])
new = len(gs.samples(P, F, gs.ZBUF_SPACING_PX * 1.0)[0])
old = len(gs.samples(P, F, 1400 / 2500)[0])
check("[2] 4 per pixel at the mask spacing (400)", new == 400, new)
check("[2] 14 per pixel at the old spacing (1400)", old == 1400, old)

src = inspect.getsource(gs.build_shell)
check("[3] spacing from the frames", "ZBUF_SPACING_PX * min(frames[w][0] for w in keys)" in src)
check("[3] not from the body height", "/ 2500" not in src)

print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL OK")
sys.exit(1 if FAILED else 0)
