#!/usr/bin/env python3
"""Review 2026-11-23 (Rosi's Red Corset Top): white-pink rays round the front island of the cut atlas, on the figure
pale streaks on the flank. The zoomed job's image went back into the atlas frame by a Lanczos downscale
(``garment_cut_texture.unzoom``) that mixed the white outside its grown area into the outer grown pixels, and the
pocket fill (``cut_texture_post.fill_pockets``) drew those pale pixels out as rays. Now the outside takes the nearest
grown colour before the scale, and the record carries ``bleed_streaks`` (checked by ``scripts/e2e_cut_texture.py``).

Usage:
    ./.venv/bin/python scripts/smoke_cut_atlas_streaks.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job. Every number derived by hand:

[1] ``unzoom``: a 200 x 200 frame, grown = the square [50, 150) x [50, 150) in red (200, 20, 30), white outside;
    frame side 100 at (ox, oy) = (10, 20) in a 200 atlas — the scale halves it, the grown square lands on
    [35, 85) x [45, 95) in the atlas (x 10 + 25 .. 10 + 75, y 20 + 25 .. 20 + 75). Every pixel the nearest-neighbour
    mask calls grown must be exactly the red: the outside of the grown area is red now, so no kernel tap sees white
    (Lanczos of a constant is the constant; 0 pale pixels). The old code (pinned 4ee6ac1ab) left the grown border's
    pixels pale: its green channel over 20 on the border ring (white 255 mixed into 20).
[2] ``bleed_streaks``: islands = the block [40, 60) x [40, 60) of a 100 x 100 atlas in red (200, 20, 30), the rest
    red too except the column x = 70 white for y in [40, 60): bleed_px 15 -> the ring = the pixels outside the block
    within Euclidean 15 px. The white column at x = 70 lies 70 - 59 = 11 px from the block (inside the ring): 20
    pixels, each L* 100 against red's L* ~43 (> STREAK_DL 20) -> light 20, dark 0. The ring holds
    (20 + 2*15)^2 - 20^2 minus the rounded corners: share = 20 / ring; ring < 2000 -> share > 0.01 -> not ok. All red
    -> 0 streaks, ok. A dark column (20, 5, 5) instead -> dark 20. No bleed (0 px) -> ok, ring 0.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_streaks_")
os.environ["STORAGE_DIR"] = TMP
os.environ["INSTANCE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


RED = (200, 20, 30)
# [1]
img = np.full((200, 200, 3), 255, np.uint8)
grown = np.zeros((200, 200), bool)
grown[50:150, 50:150] = True
img[grown] = RED
frame = {"side": 100, "ox": 10, "oy": 20}
out, g = gct.unzoom(img, grown, frame, 200)
ys, xs = np.where(g)
check("[1] the grown square lands on [35, 85) x [45, 95)",
      (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) == (35, 85, 45, 95), (xs.min(), xs.max(), ys.min(), ys.max()))
pale = int((out[g][:, 1] > 20).sum())
check("[1] every grown pixel is the red (0 pale)", pale == 0 and bool(np.all(out[g] == RED)), pale)

# the old code, pinned: its border pixels were pale
try:
    src = subprocess.run(["git", "show", "4ee6ac1ab:app/core/garment_cut_texture.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    start = src.index("def unzoom(")
    end = src.index("\ndef ", start + 1)
    ns = {"np": np, "Image": Image}
    exec(src[start:end], ns)
    old_out, old_g = ns["unzoom"](img, grown, frame, 200)
    old_pale = int((old_out[old_g][:, 1] > 20).sum())
    check("[1] the old unzoom (4ee6ac1ab) left pale border pixels", old_pale > 0, old_pale)
except (subprocess.CalledProcessError, ValueError) as e:
    print(f"SKIP [1] old-code proof: {e}")

# [2]
at = np.zeros((100, 100, 3), np.uint8)
at[:] = RED
isl = np.zeros((100, 100), bool)
isl[40:60, 40:60] = True
clean = post.bleed_streaks(at, isl, 15)
check("[2] all red: 0 streaks, ok", clean["light"] == 0 and clean["dark"] == 0 and clean["ok"], clean)
white = at.copy()
white[40:60, 70] = 255
w = post.bleed_streaks(white, isl, 15)
check("[2] a white column 11 px out: light 20", w["light"] == 20 and w["dark"] == 0, w)
check("[2] ring < 2000 -> share > 0.01 -> not ok", w["ring"] < 2000 and w["share"] > 0.01 and not w["ok"], w)
dark = at.copy()
dark[40:60, 70] = (20, 5, 5)
d = post.bleed_streaks(dark, isl, 15)
check("[2] a dark column: dark 20", d["dark"] == 20 and d["light"] == 0, d)
z = post.bleed_streaks(white, isl, 0)
check("[2] no bleed: ok, ring 0", z["ok"] and z["ring"] == 0, z)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
