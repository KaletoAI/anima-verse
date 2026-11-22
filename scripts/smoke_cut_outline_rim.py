"""Smoke: the erosion before the bleed is the answer's own outline width (``cut_texture_post.outline_rim``,
POST_VERSION 7; the per-island thin rule of POST_VERSION 8 in case 5).

Usage: ./.venv/bin/python scripts/smoke_cut_outline_rim.py

No server, no world, no hub. Synthetic answers on a 200 x 200 canvas, the mask the square rows / cols 40..159
(L = 120 px a side), cloth (200, 180, 160), outline (100, 90, 80) — dE76 between the two ~37, far above ``RIM_DE`` 12.

Expected values, by hand:

1. A 2 px outline on every side, plus 3 more px (5 in all) on the LEFT side only (the registration shifted the
   answer by 3 px); the dark columns are 40..44.
   - rings 0, 1: every pixel dark -> share 1.0;
   - rings 2, 3, 4: ring k is the square of side S = L - 2k minus the one of side S - 2: S^2 - (S - 2)^2 = 4S - 4
     pixels, its left column at col 40 + k. Dark in it: that column (S pixels) plus, on its top and bottom rows, the
     dark columns right of it (cols 43, 44 for k = 2; col 44 for k = 3; none for k = 4):
     k = 2: (116 + 4) / 460 = 0.261; k = 3: (114 + 2) / 452 = 0.257; k = 4: 112 / 444 = 0.252; each > ref 0 +
     RIM_SHARE 0.05;
   - ring 5: no dark pixel -> 0.0; the run is 5 -> px = 5 + 1 = 6.
   ``cut_and_bleed`` with 6: every mask pixel is cloth (the refill seeds from cloth only); with the old fixed 3 the
   left column 3 px inside stays the outline colour (the line the live run showed along Tilda's side seams).
2. Plain cloth, no outline: every share 0 -> run 0 -> ``RIM_MIN_PX`` 3.
3. A 12 px outline on every side: rings 0..9 all 1.0 -> run 10 -> 11, clamped to ``RIM_MAX_PX`` 10. The reference
   band (layers 10..19 deep: the square of side 100 minus the one of side 80 = 3600 px) still holds the outline's
   rings 10, 11 (100^2 - 96^2 = 784 px): ref = 784 / 3600 = 0.218, the threshold 0.268, and every ring 0..9 (1.0)
   exceeds it -> 10.
4. An island too thin for the band: a 16 px square has no pixel 10 px deep (8 px at most) -> the band is empty ->
   ``{"px": RIM_MIN_PX 3, "share": [], "ref": None}``.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="smoke-rim-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
import numpy as np  # noqa: E402

from app.core import cut_texture_post as post  # noqa: E402

FAILS = []
CLOTH = (200, 180, 160)
LINE = (100, 90, 80)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def canvas(lo=40, hi=160):
    img = np.full((200, 200, 3), 255, np.uint8)
    mask = np.zeros((200, 200), bool)
    mask[lo:hi, lo:hi] = True
    img[mask] = CLOTH
    return img, mask


# 1 -------------------------------------------------------------------------------------------------------------
img, mask = canvas()
inner2 = post.erode(mask, 2)
img[mask & ~inner2] = LINE
img[40:160, 40:45] = LINE          # the left side 5 px deep
rim = post.outline_rim(img, mask)
check("1 shares rings 0..5", rim["share"][:6], [1.0, 1.0, 0.261, 0.257, 0.252, 0.0])
check("1 ref", rim["ref"], 0.0)
check("1 px", rim["px"], 6)
new = post.cut_and_bleed(img, mask, 4, erode_px=rim["px"])
check("1 every mask pixel is cloth with the measured rim", bool(np.all(new[mask] == CLOTH)), True)
old = post.cut_and_bleed(img, mask, 4, erode_px=3)
check("1 the old 3 px leave the left outline (col 43)", tuple(int(v) for v in old[100, 43]), LINE)

# 2 -------------------------------------------------------------------------------------------------------------
img, mask = canvas()
check("2 plain cloth -> RIM_MIN_PX", post.outline_rim(img, mask)["px"], post.RIM_MIN_PX)

# 3 -------------------------------------------------------------------------------------------------------------
img, mask = canvas()
img[mask & ~post.erode(mask, 12)] = LINE
rim = post.outline_rim(img, mask)
check("3 ref share", rim["ref"], 0.218)
check("3 clamped to RIM_MAX_PX", rim["px"], post.RIM_MAX_PX)

# 4 -------------------------------------------------------------------------------------------------------------
img, mask = canvas(92, 108)
check("4 too thin for the band -> RIM_MIN_PX", post.outline_rim(img, mask), {"px": 3, "share": [], "ref": None})

# 5 -------------------------------------------------------------------------------------------------------------
# A jagged border: the square (rows / cols 40..159) plus a TOOTH on its top edge, rows 34..39 x cols 80..82 (6 x 3 =
# 18 px), all of it outline colour, the square itself cloth; and a separate STRIP island rows 180..182 x cols 40..159
# (3 x 120 = 360 px, outline colour too). Erosion 3: the tooth (3 px wide) erodes away, the square keeps a core, so
# the tooth is regrown from that core: all 18 px cloth (the old per-pixel rule kept them: 18 px outline). The strip
# has no core at all (3 px thick < 2 * 3 + 1) and keeps its own 360 px of outline colour.
img, mask = canvas(40, 160)
mask[34:40, 80:83] = True
img[34:40, 80:83] = LINE
mask[180:183, 40:160] = True
img[180:183, 40:160] = LINE
out = post.cut_and_bleed(img, mask, 2, erode_px=3)
tooth = np.zeros_like(mask)
tooth[34:40, 80:83] = True
check("5 tooth regrown from the core (px of cloth colour)", int((np.all(out == CLOTH, axis=-1) & tooth).sum()), 18)
strip = np.zeros_like(mask)
strip[180:183, 40:160] = True
check("5 a coreless strip keeps its own pixels", int((np.all(out == LINE, axis=-1) & strip).sum()), 360)

check("POST_VERSION", post.POST_VERSION, 8)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
