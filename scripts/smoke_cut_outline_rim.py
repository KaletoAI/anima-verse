"""Smoke: the erosion before the bleed is the answer's own outline width (``cut_texture_post.outline_rim``,
POST_VERSION 7; the per-island thin rule of POST_VERSION 8 in case 5; the fine pass of POST_VERSION 10 in case 6; 11 mirrors the bleed, ``smoke_cut_texture_post`` [4b]; 12 adds ``busy_halo``).

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
   The fine pass (dE 5 against the band 20..30 deep, plain cloth: ref 0) sees the same rings (the outline is dE ~37
   off) -> also run 5.
   ``cut_and_bleed`` with 6: every mask pixel is cloth (the refill seeds from cloth only); with the old fixed 3 the
   left column 3 px inside stays the outline colour (the line the live run showed along Tilda's side seams).
2. Plain cloth, no outline: every share 0 -> run 0 -> ``RIM_MIN_PX`` 3.
3. A 12 px outline on every side. The coarse reference band (layers 10..19 deep: the square of side 100 minus the
   one of side 80 = 3600 px) still holds the outline's rings 10, 11 (100^2 - 96^2 = 784 px): ref = 784 / 3600 =
   0.218, the threshold 0.268, and rings 0..11 (1.0) exceed it, ring 12 (0.0) does not -> run 12; the fine band
   (20..30 deep) is clean cloth (ref 0) -> run 12 as well -> px 13 (under ``RIM_MAX_PX`` 20).
   A 21 px outline: the coarse band (10..19) is all outline, its median the outline colour -> no coarse run. The fine
   band (20..30 deep: side 80 minus side 60 = 2800 px) holds the outline's ring 20 (80^2 - 78^2 = 316 px), its median
   is the cloth, ref = 316 / 2800 = 0.113; rings 0..19 (1.0) all exceed 0.163 -> the run fills the loop, 20 -> 21,
   clamped to ``RIM_MAX_PX`` 20.
4. An island too thin for the band: a 16 px square has no pixel 10 px deep (8 px at most) -> the band is empty ->
   ``{"px": RIM_MIN_PX 3, "share": [], "ref": None, "fine": None}``.
6. A SOFT band (Lirien's leather, 2026-11-22): a 2 px outline (dE ~37) and inside it rings 2..10 of
   (180, 162, 144) — dE76 6.88 from the cloth, under ``RIM_DE`` 12, over ``RIM_DE_FINE`` 5. Coarse: rings 0, 1 at 1.0,
   ring 2 at 0.0 -> run 2; fine (band 20..30 clean, ref 0): rings 0..10 at 1.0, ring 11 at 0.0 -> run 11 -> px 12.
   ``cut_and_bleed`` with 12: every mask pixel is cloth; with the coarse run's 3 the band's ring 3 stays (180, 162,
   144).
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
check("3 px 13", rim["px"], 13)
check("3 fine ref", rim["fine"]["ref"], 0.0)
img, mask = canvas()
img[mask & ~post.erode(mask, 21)] = LINE
rim21 = post.outline_rim(img, mask)
check("3 a 21 px outline: fine ref 0.113", rim21["fine"]["ref"], 0.113)
check("3 a 21 px outline: clamped to RIM_MAX_PX 20", rim21["px"], post.RIM_MAX_PX)
check("RIM_MAX_PX", post.RIM_MAX_PX, 20)

# 4 -------------------------------------------------------------------------------------------------------------
img, mask = canvas(92, 108)
check("4 too thin for the band -> RIM_MIN_PX", post.outline_rim(img, mask),
      {"px": 3, "share": [], "ref": None, "fine": None})

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

# 6 -------------------------------------------------------------------------------------------------------------
SOFT = (180, 162, 144)
img, mask = canvas()
img[mask & ~post.erode(mask, 11)] = SOFT
img[mask & ~post.erode(mask, 2)] = LINE
check("6 dE76 of the soft band 6.88", round(post.delta_e(CLOTH, SOFT), 2), 6.88)
rim = post.outline_rim(img, mask)
check("6 coarse shares rings 0..3", rim["share"][:4], [1.0, 1.0, 0.0, 0.0])
check("6 fine shares rings 0..11", rim["fine"]["share"][:12], [1.0] * 11 + [0.0])
check("6 px 12", rim["px"], 12)
check("6 every mask pixel cloth with 12", bool(np.all(post.cut_and_bleed(img, mask, 4, erode_px=12)[mask] == CLOTH)),
      True)
check("6 the coarse 3 leave ring 3 soft", tuple(int(v) for v in post.cut_and_bleed(img, mask, 4, erode_px=3)[100, 43]),
      SOFT)

check("POST_VERSION (12 since busy_halo cleans the dot grid; 11 mirrored the bleed)", post.POST_VERSION, 12)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
