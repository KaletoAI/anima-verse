"""Smoke: "texture from cut" post-processing (``app/core/cut_texture_post.py``, plan Task 7).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_post.py

No server, no world DB, no hub job, no BiRefNet session: pure numpy + PIL on synthetic pictures. ``colour_match`` gets
a matte stub (``matte=None``: the plain key cut of ``garment_matte.cut``), so nothing loads a model. Every
expectation is derived by hand below.

Frame: arrays are (rows, cols), row 0 at the TOP (the template / atlas frame). "Foreground" = a pixel whose largest
channel distance from white exceeds ``WHITE_TOL`` (24); the synthetic answers paint grey 190 (distance 65).

[1] Register. mask = the rectangle cols 100..499, rows 100..699 (400 x 600 = 240 000 px) in a 1024 x 1024 frame.
    (a) The answer is the same picture rendered at 1072 x 976 (the 2144 x 1952-for-2300 x 2080 kind of answer: scales
        1072/1024 = 1.046875 and 976/1024 = 0.953125). Resizing it back to the mask frame undoes that by itself; the
        rectangle edges may smear by one pixel on each side, so the registered IoU is at least
        (398 * 598) / (402 * 602) = 238 004 / 242 004 = 0.9835.
    (b) The answer is the rectangle shrunk by 0.97 about its own centre (300, 400): 0.97 * 400 = 388 wide
        (cols 106..493), 0.97 * 600 = 582 high (rows 109..690), at 1024 x 1024 — the model drawing the islands a little
        small. Before registration it lies inside the mask: IoU = 388 * 582 / 240 000 = 225 816 / 240 000 = 0.9409.
        After ``resample_register`` the IoU is >= 0.98 and the map template -> answer has the scales 0.97 +- 0.01 per
        axis (u = sx * x + ox: the answer is 0.97 times the template).
    (c) The box fit is not the answer: two islands (cols 100..299 and 400..599, rows 100..399; 2 * 60 000 =
        120 000 px), the answer draws them 1.03 times larger about (0, 0) and 12 px right / 8 px up
        (u = 1.03 x + 12, v = 1.03 y - 8), plus a stray 20 x 20 blob at rows 450..469, cols 330..349 (a label the model added below the islands).
        The blob stretches the answer's box from rows 95..404 down to row 469 (375 instead of 309 px high: the box
        fit's y scale is 1.25, not 1.03 — inside SCALE_LIMIT 1.6 of it), so the box fit is off (its IoU is lower). The search
        finds the true map: the mapped mask then covers the drawn islands up to edge rounding, and the only
        foreground outside it is the blob (400 px): IoU >= (123 600 - 2 * 2 * (206 + 309)) / (123 600 + 400)
        = 121 540 / 124 000 = 0.98 on the islands' own pixels; checked as >= 0.97 against the full mask after
        resampling, the scales 1.03 +- 0.01, and the grid IoU above the box-fit IoU.
[2] Gate coverage. Two equal islands (labels 1 and 2, 100 x 100 each, 20 000 px of mask), the answer fills only
    island 1: coverage = 10 000 / 20 000 = 0.50 < 0.97 -> rejected; the reason (the first failing gate in the order
    coverage, island_coverage, iou, spill) reads exactly "coverage 0.50 < 0.97".
[3] Gate spill. One 400 x 600 island (cols 100..499, rows 100..699) filled, plus a strip painted OUTSIDE its right
    (long) side, rows 100..699. px_per_cm = 10 -> the spill zone starts 1 cm = 10 px out. A 20 px strip
    (cols 500..519): 10 * 600 = 6 000 px lie beyond the 10 px dilation -> spill = 6 000 / 240 000 = 0.025 <= 0.03 ->
    passes (coverage 1.00, iou = 240 000 / 252 000 = 0.952 >= 0.90). A 30 px strip: 20 * 600 / 240 000 = 0.05 > 0.03
    -> rejected with "spill 0.05 > 0.03" (iou 240 000 / 258 000 = 0.930 still passes).
[4] Bleed. A 100 x 50 mask (cols 50..149, rows 40..89) in a 200 x 200 frame, bleed 4, erode 0: an 8-neighbour
    dilation 4 times grows the rectangle by 4 px on every side, square corners -> (100 + 8) * (50 + 8) = 6 264 filled
    px, the rest white. The island's left column is red (220, 30, 30), the rest blue (30, 30, 220): every bleed pixel
    left of the island (cols 46..49) on a row away from the corners (rows 45..84) is exactly the red edge colour, every
    one right of it (cols 150..153) the blue edge colour. With erode 3 the outline ring (3 px) is cut away first and
    regrown from the interior: the filled area is unchanged (6 264) and the left bleed is blue now (the red column was
    eroded).
[5] Colour match. A uniform island (200, 60, 60) and a uniform item fabric (150, 40, 40) (64 x 64 on white, key cut).
    sigma = 0 on both sides; the atlas floor 1.0 makes the transfer a pure mean shift. That shift is
    dE76((200,60,60), (150,40,40)) = 16.53 < 25 (not clamped) -> the island becomes (150, 40, 40) +-1 per channel,
    ``de_before`` = 16.53 (+-0.05), ``de_after`` <= 0.5, ``clamped`` False, no NaN anywhere; outside the mask the
    pixels are unchanged.
[5b] Empty answer: an all-white answer -> ``resample_register`` returns ``registered`` False, ``iou`` 0.0;
    ``gate`` rejects with "coverage 0.00 < 0.97"; nothing raises.
[6] dE anchor: sRGB grey 128 -> linear 0.2158605 -> Y = 0.2158605 -> f = 0.6000 -> L* = 116 * 0.6000 - 16 = 53.59,
    a* = b* = 0. dE76(white, grey 128) = 100 - 53.59 = 46.41 (+-0.05).
[7] Clamp: island (250, 250, 250) against item (20, 20, 20): L* 98.27 against 7.0, a shift of ~91 > 25 -> clamped to
    25 along the shift (greys: only L* moves), ``clamped`` True, the island's L* = L*(250) - 25 = 73.27 (+-0.5).
[8] Seam continuity: an atlas whose left half is (200, 60, 60), right half white, lower-right quarter grey 128.
    Seam 0: three pairs, both points in the red half -> median 0.0. Seam 1: three pairs, white against grey 128 ->
    median 46.41 (+-0.05). Overall median over the six pairs = (0 + 46.41) / 2 = 23.21 (+-0.05).
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_cut_post_")
os.environ.setdefault("STORAGE_DIR", _TMP)
os.environ.setdefault("INSTANCE_DIR", _TMP)

from app.core import cut_texture_post as ctp  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


def iou(a, b):
    return float((a & b).sum() / max(1, (a | b).sum()))


GREY = 190

# [1] register
mask = np.zeros((1024, 1024), bool)
mask[100:700, 100:500] = True
pic = np.full((1024, 1024, 3), 255, np.uint8)
pic[mask] = GREY
big = Image.fromarray(pic).resize((1072, 976), Image.NEAREST)
img_a, info_a = ctp.resample_register(big, mask)
iou_a = iou(ctp.foreground(img_a), mask)
check("[1a] answer at 1072x976 -> registered IoU >= 0.9835", info_a["registered"] and iou_a >= 0.9835,
      f"iou {iou_a:.4f}, info iou {info_a['iou']}")
check("[1a] image back in the mask frame", img_a.shape == (1024, 1024, 3) and img_a.dtype == np.uint8,
      str(img_a.shape))
small = np.full((1024, 1024, 3), 255, np.uint8)
small[109:691, 106:494] = GREY
before = iou(ctp.foreground(small), mask)
check("[1b] before registration IoU = 0.9409", abs(before - 0.9409) < 0.0005, f"{before:.4f}")
img_b, info_b = ctp.resample_register(Image.fromarray(small), mask)
iou_b = iou(ctp.foreground(img_b), mask)
sx, ox, sy, oy = info_b["map"]
check("[1b] after resample_register IoU >= 0.98", iou_b >= 0.98, f"{iou_b:.4f}")
check("[1b] map scales 0.97 +- 0.01", abs(sx - 0.97) <= 0.01 and abs(sy - 0.97) <= 0.01, f"{sx:.4f} {sy:.4f}")
check("[1b] info iou = measured IoU", abs(info_b["iou"] - iou_b) < 1e-3, f"{info_b['iou']} vs {iou_b:.4f}")

mask_c = np.zeros((1024, 1024), bool)
mask_c[100:400, 100:300] = True
mask_c[100:400, 400:600] = True
pic_c = np.full((1024, 1024, 3), 255, np.uint8)
yy, xx = np.mgrid[0:1024, 0:1024]
src = np.zeros((1024, 1024), bool)
xs_, ys_ = ((xx + 0.5) - 12) / 1.03, ((yy + 0.5) + 8) / 1.03
inside = (xs_ >= 0) & (xs_ < 1024) & (ys_ >= 0) & (ys_ < 1024)
src[inside] = mask_c[np.floor(ys_[inside]).astype(int), np.floor(xs_[inside]).astype(int)]
pic_c[src] = GREY
pic_c[450:470, 330:350] = GREY
img_c, info_c = ctp.resample_register(Image.fromarray(pic_c), mask_c)
check("[1c] grid IoU above the box-fit IoU", info_c["grid_iou"] > info_c["box_iou"], str(info_c))
check("[1c] registered IoU >= 0.97 despite the stray blob", info_c["iou"] >= 0.97, str(info_c))
check("[1c] map scales 1.03 +- 0.01", abs(info_c["map"][0] - 1.03) <= 0.01 and abs(info_c["map"][2] - 1.03) <= 0.01,
      str(info_c["map"]))

# [2] gate coverage
labels = np.zeros((300, 300), np.uint8)
labels[50:150, 20:120] = 1
labels[50:150, 180:280] = 2
m2 = labels > 0
out2 = np.full((300, 300, 3), 255, np.uint8)
out2[labels == 1] = GREY
ok2, met2, why2 = ctp.gate(out2, m2, labels, 10.0)
check("[2] one of two islands -> coverage 0.50, rejected", (not ok2) and abs(met2["coverage"] - 0.5) < 1e-6,
      str(met2))
check("[2] reason text", why2 == "coverage 0.50 < 0.97", repr(why2))

# [3] gate spill
lab3 = np.zeros((800, 700), np.uint8)
lab3[100:700, 100:500] = 1
m3 = lab3 > 0
for width, want_ok, want_spill in ((20, True, 0.025), (30, False, 0.05)):
    out3 = np.full((800, 700, 3), 255, np.uint8)
    out3[m3] = GREY
    out3[100:700, 500:500 + width] = GREY
    ok3, met3, why3 = ctp.gate(out3, m3, lab3, 10.0)
    check(f"[3] strip {width} px -> spill {want_spill}", abs(met3["spill"] - want_spill) < 1e-6
          and ok3 is want_ok, f"{met3}, {why3!r}")
    if not want_ok:
        check("[3] reason text", why3 == "spill 0.05 > 0.03", repr(why3))
    else:
        check("[3] passing gate has an empty reason", why3 == "", repr(why3))

# [4] bleed
m4 = np.zeros((200, 200), bool)
m4[40:90, 50:150] = True
img4 = np.full((200, 200, 3), 255, np.uint8)
img4[40:90, 50:150] = (30, 30, 220)
img4[40:90, 50] = (220, 30, 30)
b4 = ctp.cut_and_bleed(img4, m4, 4, erode_px=0)
filled = (b4 != 255).any(-1)
check("[4] bleed 4 -> 6264 filled px", int(filled.sum()) == 6264, str(int(filled.sum())))
check("[4] filled area is the grown rectangle", bool(filled[36:94, 46:154].all()), "")
check("[4] left bleed = red edge colour", bool((b4[45:85, 46:50] == (220, 30, 30)).all()), str(b4[60, 46]))
check("[4] right bleed = blue edge colour", bool((b4[45:85, 150:154] == (30, 30, 220)).all()), str(b4[60, 152]))
check("[4] inside unchanged", bool((b4[40:90, 50:150] == img4[40:90, 50:150]).all()), "")
b4e = ctp.cut_and_bleed(img4, m4, 4, erode_px=3)
filled_e = (b4e != 255).any(-1)
check("[4] erode 3 + bleed 4 -> still 6264 filled px", int(filled_e.sum()) == 6264, str(int(filled_e.sum())))
check("[4] erode 3: the eroded red column is regrown blue", bool((b4e[45:85, 46:54] == (30, 30, 220)).all()),
      str(b4e[60, 50]))

# [5] colour match
item = np.zeros((96, 96, 4), np.uint8)
item[..., :3] = 255
item[..., 3] = 255
item[16:80, 16:80, :3] = (150, 40, 40)
m5 = np.zeros((128, 128), bool)
m5[20:100, 30:90] = True
img5 = np.full((128, 128, 3), 255, np.uint8)
img5[m5] = (200, 60, 60)
out5, inf5 = ctp.colour_match(img5, m5, item, matte=None)
diff = np.abs(out5[m5].astype(int) - np.array([150, 40, 40])).max()
check("[5] island becomes (150,40,40) +-1", diff <= 1, f"max diff {diff}, {out5[m5][0]}")
check("[5] de_before 16.53", abs(inf5["de_before"] - 16.53) <= 0.05, str(inf5))
check("[5] de_after <= 0.5, not clamped", inf5["de_after"] <= 0.5 and inf5["clamped"] is False, str(inf5))
check("[5] no NaN", not any(isinstance(v, float) and np.isnan(v) for v in inf5.values()), str(inf5))
check("[5] outside the mask unchanged", bool((out5[~m5] == 255).all()), "")

# [5b] empty answer
white = Image.new("RGB", (1072, 976), (255, 255, 255))
img_w, inf_w = ctp.resample_register(white, mask)
check("[5b] empty answer -> registered False, iou 0.0", inf_w["registered"] is False and inf_w["iou"] == 0.0,
      str(inf_w))
okw, metw, whyw = ctp.gate(img_w, mask, mask.astype(np.uint8), 19.59)
check("[5b] gate rejects 'coverage 0.00 < 0.97'", (not okw) and whyw == "coverage 0.00 < 0.97", repr(whyw))

# [6] dE anchor
L128 = ctp.srgb_to_lab(np.array([128, 128, 128], float))
check("[6] L*(grey 128) = 53.59, a* = b* = 0", abs(L128[0] - 53.59) <= 0.01 and abs(L128[1]) < 1e-3
      and abs(L128[2]) < 1e-3, str(L128))
de6 = ctp.delta_e((255, 255, 255), (128, 128, 128))
check("[6] dE(white, grey128) = 46.41", abs(de6 - 46.41) <= 0.05, f"{de6:.3f}")

# [7] clamp
item7 = item.copy()
item7[16:80, 16:80, :3] = (20, 20, 20)
img7 = np.full((128, 128, 3), 255, np.uint8)
img7[m5] = (250, 250, 250)
out7, inf7 = ctp.colour_match(img7, m5, item7, matte=None)
L7 = ctp.srgb_to_lab(out7[m5].astype(float))[:, 0].mean()
want7 = ctp.srgb_to_lab(np.array([250, 250, 250], float))[0] - 25.0
check("[7] clamped", inf7["clamped"] is True, str(inf7))
check("[7] island L* = L*(250) - 25", abs(L7 - want7) <= 0.5, f"{L7:.2f} vs {want7:.2f}")

# [8] seam continuity
atlas = np.full((200, 200, 3), 255, np.uint8)
atlas[:, :100] = (200, 60, 60)
atlas[100:, 100:] = 128
seams = [{"seam": 0, "a": "front", "uv_a_px": [10.5 + k, 20.5], "b": "back", "uv_b_px": [60.5, 30.5 + k]}
         for k in range(3)]
seams += [{"seam": 1, "a": "front", "uv_a_px": [150.5, 20.5 + k], "b": "back", "uv_b_px": [150.5, 150.5 + k]}
          for k in range(3)]
sc = ctp.seam_continuity(atlas, seams)
check("[8] seam 0 median 0.0", abs(sc["per_seam"]["0"]) < 1e-6, str(sc))
check("[8] seam 1 median 46.41", abs(sc["per_seam"]["1"] - 46.41) <= 0.05, str(sc))
check("[8] overall median 23.21", abs(sc["median"] - 23.21) <= 0.05 and sc["pairs"] == 6, str(sc))
check("[8] no seams -> median None", ctp.seam_continuity(atlas, [])["median"] is None, "")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("ALL PASS")
