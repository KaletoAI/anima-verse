"""Review round 2026-11-25 (Lirien's cupped top, live: the stripe check of the texture from cut failed at 2.07 % against
1 %, the streaks sat round the two upper cup parts): the overhang of a NARROW island is taken from the island itself
(``cut_texture_post.narrow_overhang``, ``NARROW_ISLAND_CM``). Every expectation is derived by hand below; pure numpy, no
server, no world DB, no image job.

Raster 100 x 100 px, ``px_per_cm`` 1 (so NARROW_ISLAND_CM 5 cm = 5 px), ``reach_px`` 3, background white:
* island 1: a strip of columns 10..13 x rows 10..49 (4 x 40 px), colour (200, 0, 0). Its largest inner distance to the
  background (``distance_transform_edt`` of the island) is 2 px (the two middle columns), so its width 2 x 2 = 4 < 5:
  narrow.
* island 2: a block of columns 50..79 x rows 10..39 (30 x 30 px), colour (0, 0, 200). Largest inner distance 15, width
  30 >= 5: not narrow.

[N1] ``islands`` == [1].
[N2] The ring of island 1 within 3 px (Euclidean) is its rectangle grown by 3 px with rounded corners:
     (4 + 6) x (40 + 6) = 460 px, less per corner the offsets (dx, dy) in 1..3 with dx^2 + dy^2 > 9 — (1, 3), (3, 1),
     (2, 3), (3, 2), (3, 3): 5 each, 20 in all — less the island's own 160 px: 460 - 20 - 160 = 280 = ``px``.
[N3] Pixel (row 30, column 8) — 2 px left of the strip — is (200, 0, 0); pixel (row 30, column 6) — 4 px left, past the
     reach — stays white.
[N4] Pixel (row 20, column 47) — 3 px left of the block — stays white (the block is not narrow); the block's own pixels
     are unchanged.
[N5] With ``px_per_cm`` 0 nothing changes and ``islands`` is [].

Usage: ./.venv/bin/python scripts/smoke_narrow_overhang.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import cut_texture_post as post  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        FAILS.append(name)


atlas = np.full((100, 100, 3), 255, np.uint8)
labels = np.zeros((100, 100), np.uint8)
labels[10:50, 10:14] = 1
atlas[10:50, 10:14] = (200, 0, 0)
labels[10:40, 50:80] = 2
atlas[10:40, 50:80] = (0, 0, 200)

out, info = post.narrow_overhang(atlas, labels, 1.0, 3)
check("[N1] only the strip is narrow", info["islands"] == [1], info)
check("[N2] its ring within 3 px is 280 px", info["px"] == 280, info["px"])
check("[N3] 2 px left of the strip takes its colour", tuple(out[30, 8]) == (200, 0, 0), tuple(out[30, 8]))
check("[N3] 4 px left of the strip stays white", tuple(out[30, 6]) == (255, 255, 255), tuple(out[30, 6]))
check("[N4] 3 px left of the block stays white", tuple(out[20, 47]) == (255, 255, 255), tuple(out[20, 47]))
check("[N4] the block is unchanged", bool(np.all(out[10:40, 50:80] == (0, 0, 200))))
same, info0 = post.narrow_overhang(atlas, labels, 0.0, 3)
check("[N5] px_per_cm 0 changes nothing", bool(np.array_equal(same, atlas)) and info0["islands"] == [], info0)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
