#!/usr/bin/env python3
"""Smoke: the composed cut atlas fills its background pockets (``cut_texture_post.fill_pockets``, POST_VERSION 9) and a
sheer lace atlas is keyed into alpha at assembly (``cut_texture_post.lace_alpha``, ``garment_assembly._lace_keyed``) —
review 2026-11-22: a white notch between Lirien's two front leg islands at the crotch, skin painted into the gaps of
Kira's lace tights.

No server, no world, no hub. Usage: ./.venv/bin/python scripts/smoke_cut_texture_pockets_lace.py

Expected values, by hand:

1. ``fill_pockets`` on a 100 x 100 white canvas: the left leg island rows 10..89 x cols 10..39 red (200, 0, 0), the
   right one rows 10..89 x cols 60..89 blue (0, 0, 200), a crotch bridge rows 10..19 x cols 40..59 green (0, 200, 0)
   — a notch between the legs open at the bottom (not enclosed), 20 px wide (cols 40..59).
   a. reach 5: pixel (50, 50) is 50 - 39 = 11 px from the left island, 60 - 50 = 10 px from the right one, 50 - 19 =
      31 px from the bridge -> nearest 10 > 5 -> stays white; (50, 42) is 3 px from the left -> red; (50, 57) 3 px
      from the right -> blue; (50, 95) 95 - 89 = 6 > 5 -> white.
   b. reach 12: (50, 50) -> blue (10 <= 12, the right island is nearest); (50, 95) -> blue (6); (95, 50): 95 - 89 = 6
      from both legs' bottom rows (cols 39 / 60 are 11 / 10 px aside: sqrt(6² + 10²) = 11.66 to the right one,
      sqrt(6² + 11²) = 12.53 to the left) -> blue.
   c. Closing the notch with a bottom bridge rows 80..89 x cols 40..59 (green) encloses rows 20..79 x cols 40..59: at
      reach 5 every one of those 60 x 20 = 1200 pixels is filled anyway (a hole), (50, 50) -> blue (right 10 < left
      11 < bridges 30 / 31); (50, 49) -> red (left 10 < right 11).
2. ``compose`` with ``px_per_cm`` 4.0 (``POCKET_CM`` 3.0 -> reach round(12.0) = 12) on the open-notch canvas as the
   front job's result (grown = mask = the islands): (50, 50) blue as in 1b; without ``px_per_cm`` (0) it stays white.
3. ``lace_alpha`` on a 10 x 10 picture: cols 0..5 thread (30, 30, 30), cols 6..9 skin (224, 172, 140). Skin: Y = 0.299 *
   224 + 0.587 * 172 + 0.114 * 140 = 183.9 >= 25, Cr = 128 + 112 - 72.02 - 11.38 = 156.6 in [133, 180], Cb = 128 -
   37.79 - 56.98 + 70 = 103.2 in [77, 127]; the thread's Cr = 128 + 15 - 12.56 - 2.44 = 128.0 < 133 is no skin. All
   100 pixels are fabric (min channel < 235): share 40 / 100 = 0.4 in [0.10, 0.70] -> lace; thread median (30, 30,
   30); opacity 0.4.
   - col 9 (its 3 x 3 box, edge-padded, all skin): soft 1 -> alpha 1 - 0.6 * 1 = 0.4 -> 102, colour the thread (30,
     30, 30);
   - col 6 (box cols 5..7: 6 of 9 skin): soft 0.667 -> alpha 1 - 0.6 * 0.667 = 0.6 -> 153, colour 224 / 3 + 20 =
     94.67 -> 95, 172 / 3 + 20 = 77.33 -> 77, 140 / 3 + 20 = 66.67 -> 67;
   - col 5 (a thread pixel, box 3 of 9 skin = 0.333 <= 0.5): alpha 255, colour unchanged (30, 30, 30); col 0: 255.
   All thread -> share 0 < 0.10 -> None; all skin -> share 1.0 > 0.70 (a skin-coloured cloth) -> None.
4. ``garment_assembly._lace_keyed`` with the 3. picture as PNG bytes and opacity 0.4: an RGBA PNG whose pixel (0, 9)
   has alpha 102, ``info["lace"]["skin_share"]`` 0.4; the all-thread picture comes back as the SAME bytes with
   ``info["lace"]`` None.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_T = Path(tempfile.mkdtemp(prefix="smoke-pockets-lace-"))
os.environ.setdefault("STORAGE_DIR", str(_T / "world"))
os.environ.setdefault("INSTANCE_DIR", str(_T / "instance"))
from app.core import paths  # noqa: E402
paths.init(_T / "world")
paths.init_instance(_T / "instance")
from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_assembly, garment_template  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"   [got {got!r}, want {want!r}]"))
    if not ok:
        FAILS.append(name)


RED, BLUE, GREEN, WHITE = (200, 0, 0), (0, 0, 200), (0, 200, 0), (255, 255, 255)


def canvas(closed=False):
    img = np.full((100, 100, 3), 255, np.uint8)
    m = np.zeros((100, 100), bool)
    for rows, cols, col in ((slice(10, 90), slice(10, 40), RED), (slice(10, 90), slice(60, 90), BLUE),
                            (slice(10, 20), slice(40, 60), GREEN)) + (((slice(80, 90), slice(40, 60), GREEN),)
                                                                     if closed else ()):
        img[rows, cols] = col
        m[rows, cols] = True
    return img, m


def px(img, r, c):
    return tuple(int(v) for v in img[r, c])


# 1a / 1b
img, m = canvas()
out, _ = post.fill_pockets(img, m, 5)
check("1a (50,50) white at reach 5", px(out, 50, 50), WHITE)
check("1a (50,42) red", px(out, 50, 42), RED)
check("1a (50,57) blue", px(out, 50, 57), BLUE)
check("1a (50,95) white", px(out, 50, 95), WHITE)
out, _ = post.fill_pockets(img, m, 12)
check("1b (50,50) blue at reach 12", px(out, 50, 50), BLUE)
check("1b (50,95) blue", px(out, 50, 95), BLUE)
check("1b (95,50) blue", px(out, 95, 50), BLUE)
# 1c
img_c, m_c = canvas(closed=True)
out, pocket = post.fill_pockets(img_c, m_c, 5)
check("1c the enclosed pocket filled whole", int(pocket[20:80, 40:60].sum()), 1200)
check("1c (50,50) blue", px(out, 50, 50), BLUE)
check("1c (50,49) red", px(out, 50, 49), RED)
# 2
res = {"front": {"_image": img, "_grown": m.copy(), "_mask": m.copy()}}
check("2 compose fills at px_per_cm 4", px(gct.compose(res, 100, 4.0), 50, 50), BLUE)
check("2 compose without px_per_cm leaves it", px(gct.compose(res, 100), 50, 50), WHITE)
# 3
lace = np.zeros((10, 10, 3), np.uint8)
lace[:, :6] = (30, 30, 30)
lace[:, 6:] = (224, 172, 140)
rgba, info = post.lace_alpha(lace, 0.4, garment_template.skin_mask)
check("3 skin share", info["skin_share"], 0.4)
check("3 thread colour", info["thread_rgb"], [30, 30, 30])
check("3 col 9", tuple(int(v) for v in rgba[4, 9]), (30, 30, 30, 102))
check("3 col 6", tuple(int(v) for v in rgba[4, 6]), (95, 77, 67, 153))
check("3 col 5", tuple(int(v) for v in rgba[4, 5]), (30, 30, 30, 255))
check("3 col 0 alpha", int(rgba[4, 0, 3]), 255)
check("3 all thread -> no lace", post.lace_alpha(np.full((10, 10, 3), 30, np.uint8), 0.4,
                                                  garment_template.skin_mask)[0] is None, True)
skin = np.zeros((10, 10, 3), np.uint8)
skin[:] = (224, 172, 140)
check("3 all skin -> no lace", post.lace_alpha(skin, 0.4, garment_template.skin_mask)[0] is None, True)


# 4
def png(a, mode):
    buf = io.BytesIO()
    Image.fromarray(a, mode).save(buf, format="PNG")
    return buf.getvalue()


keyed, kinfo = garment_assembly._lace_keyed(png(lace, "RGB"), 0.4, {"texture": "cut"})
with Image.open(io.BytesIO(keyed)) as im:
    check("4 keyed atlas is RGBA", im.mode, "RGBA")
    check("4 alpha at (0, 9)", int(np.asarray(im)[0, 9, 3]), 102)
check("4 info lace share", (kinfo.get("lace") or {}).get("skin_share"), 0.4)
plain = png(np.full((10, 10, 3), 30, np.uint8), "RGB")
same, pinfo = garment_assembly._lace_keyed(plain, 0.4, {"texture": "cut"})
check("4 no lace: same bytes", same == plain, True)
check("4 no lace: info lace None", pinfo.get("lace", "missing"), None)

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
