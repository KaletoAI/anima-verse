#!/usr/bin/env python3
"""Smoke: texture from cut, group B phases C / D — a jacket's / dress's names and families, and the placket painted by
code along the cut's marks (plan ``docs/superpowers/plans/2026-11-22-schnitt-gruppe-b.md`` C3 / C4 / D2).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_placket.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job. Every expectation is derived by hand:

[1] Names (``piece_name_of``): a jacket with a lapel collar "blazer"; a leather fabric "leather jacket" (Kai: open,
    crew, no collar, leather_glossy); an open front without a collar "cardigan" (Tilda: open, V, wool); otherwise
    "jacket" (Kira today: closed, V 0.26, no collar). A dress by its length — 0.30 "mini dress", 0.50 "knee-length
    dress", 0.80 "midi dress", 0.95 "long dress" — and its sleeves on covered shoulders: long "long-sleeve ", elbow
    "short-sleeve "; straps no sleeve word. ``held_trims`` of "jacket" / "dress" with plain sleeves True (the sleeves,
    neckband, collar get the fabric patch), ``prompt_family`` "fitted".
[2] ``button_centres``: a line 600 px long at 10 px/cm is 60 cm; a jacket's pitch 10 cm -> round(6.0) = 6 buttons at
    (j + 0.5) x 100 = 50, 150, ..., 550; ``buttons`` 4 -> 75, 225, 375, 525; a dress's pitch 7 cm -> round(8.57) = 9.
    A 3 cm line still gets one (max(1, round(0.3)) = 1).
[3] ``button_colours`` (B13): on a fabric of L* 80 the disc is L* 80 - 25 = 55, the rim 80 - 40 = 40; on L* 20 they
    are 20 + 25 = 45 and 20 + 40 = 60 (each within 0.6: rounding to 8-bit sRGB).
[4] A closed front: a 200 x 200 grey (128) atlas at 10 px/cm, the island the pixels x < 150, a red stripe x >= 150
    (another island), the ``centre_front`` line x = 100.5 from y = 20 to y = 180 (16 cm). Jacket buttons, automatic:
    round(1.6) = 2 buttons at arc 40 and 120 -> centres (100.5, 60) and (100.5, 140); the pixel (100, 60) lies 0.5 px
    from the centre, inside the disc (r = 0.82 x 9 = 7.38 px, the holes 0.11 x 18 = 1.98 px either side of it) and is
    the disc colour of the grey; the placket's stitch lines lie 15 px either side (3 cm / 2): pixel (85, 100) is the
    stitch shade (L* 53.6 - 12); every pixel x >= 150 is unchanged (red), and so is the corner (5, 5); "none" returns
    the atlas unchanged.
[5] An open front: left island x < 100, right island x >= 100 (both grey); ``edge_right`` on the right island at
    x = 100.5 top-down. The left normal of a downward tangent (0, 1) is (-1, 0), which points out of the island, so
    the inward side is -1 and the buttons sit width / 2 = 15 px inside: x = 115.5 — 2 buttons at y 60 / 140 (16 cm);
    ``edge_left`` on the left island at x = 99.5: no disc, two holes (slits across the edge) — info ``holes`` 2,
    ``buttons`` 2, and the button disc centre (115, 60) is the disc colour.
[6] A zip on the closed front of [4]: the pixel (100, 100) on the line is the metal L* 60 (a tooth row or the band:
    L* 50 or 60, a* = b* ~ 0) and (110, 100) 9.5 px off — beyond the band's 0.4 cm half width — stays grey.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-cut-placket-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402

paths.init(TEMP.name)
from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def lab(rgb):
    return post.srgb_to_lab(np.asarray(rgb, float))


# [1]
names = {
    "blazer": {"kind": "jacket", "collar": "lapel", "front": "closed", "fabric": "wool"},
    "leather jacket": {"kind": "jacket", "collar": "none", "front": "open", "fabric": "leather_glossy"},
    "cardigan": {"kind": "jacket", "collar": "none", "front": "open", "fabric": "wool"},
    "jacket": {"kind": "jacket", "collar": "none", "front": "closed", "fabric": "wool"},
    "mini dress": {"kind": "dress", "length_m": 0.30, "shoulders": "straps"},
    "knee-length dress": {"kind": "dress", "length_m": 0.50, "shoulders": "straps"},
    "midi dress": {"kind": "dress", "length_m": 0.80, "shoulders": "straps"},
    "long dress": {"kind": "dress", "length_m": 0.95, "shoulders": "straps"},
    "long-sleeve long dress": {"kind": "dress", "length_m": 0.95, "shoulders": "covered", "sleeves": "long"},
    "short-sleeve knee-length dress": {"kind": "dress", "length_m": 0.50, "shoulders": "covered", "sleeves": "elbow"},
}
for want, p in names.items():
    got = gct.piece_name_of(p)
    check(f"[1] piece_name_of -> {want!r}", got == want, got)
for k in ("jacket", "dress"):
    check(f"[1] held_trims({k}, plain) True, family fitted",
          gct.held_trims(k, "plain") is True and gct.prompt_family(k) == "fitted",
          (gct.held_trims(k, "plain"), gct.prompt_family(k)))

# [2]
check("[2] jacket 60 cm: 6 buttons 50..550", post.button_centres(600, 10, "jacket") == [50, 150, 250, 350, 450, 550],
      post.button_centres(600, 10, "jacket"))
check("[2] buttons 4: 75/225/375/525", post.button_centres(600, 10, "jacket", 4) == [75, 225, 375, 525])
check("[2] dress 60 cm: 9 buttons", len(post.button_centres(600, 10, "dress")) == 9)
check("[2] a 3 cm line: one button", len(post.button_centres(30, 10, "jacket")) == 1)

# [3]
for l_, disc, rim in ((80.0, 55.0, 40.0), (20.0, 45.0, 60.0)):
    c = post.button_colours(np.array([l_, 0.0, 0.0]))
    check(f"[3] fabric L* {l_}: disc {disc}, rim {rim}", abs(c["disc_l"] - disc) <= 0.6 and abs(c["rim_l"] - rim) <= 0.6,
          (c["disc_l"], c["rim_l"]))

# [4]
atlas = np.full((200, 200, 3), 128, np.uint8)
atlas[:, 150:] = (200, 0, 0)
isl = np.zeros((200, 200), bool)
isl[:, :150] = True
marks = {"centre_front": {"island": "front", "px": [[100.5, 20.0], [100.5, 180.0]]}}
out, info = post.draw_placket(atlas, {"front": isl}, marks, kind="jacket", style="buttons", buttons=0, px_per_cm=10)
grey_l = float(lab([128, 128, 128])[0])
col = post.button_colours(np.array([grey_l, 0.0, 0.0]))
check("[4] two buttons at (100.5, 60) / (100.5, 140)", info["buttons"] == [[100.5, 60.0], [100.5, 140.0]], info["buttons"])
check("[4] pixel (100, 60) is the disc colour", tuple(out[60, 100]) == tuple(col["disc"]), (out[60, 100], col["disc"]))
stitch_l = float(lab(out[100, 85])[0])
check("[4] pixel (85, 100) is the stitch line, L* fabric - 12", abs(stitch_l - (grey_l - 12.0)) <= 0.6, (stitch_l, grey_l))
check("[4] the other island and the corner unchanged",
      (out[:, 150:] == atlas[:, 150:]).all() and tuple(out[5, 5]) == (128, 128, 128))
same, _ = post.draw_placket(atlas, {"front": isl}, marks, kind="jacket", style="none", buttons=0, px_per_cm=10)
check("[4] none: unchanged", (same == atlas).all())

# [5]
atlas2 = np.full((200, 200, 3), 128, np.uint8)
left = np.zeros((200, 200), bool)
left[:, :100] = True
marks2 = {"edge_left": {"island": "left_front", "px": [[99.5, 20.0], [99.5, 180.0]]},
          "edge_right": {"island": "right_front", "px": [[100.5, 20.0], [100.5, 180.0]]}}
out2, info2 = post.draw_placket(atlas2, {"left_front": left, "right_front": ~left}, marks2, kind="jacket",
                                style="buttons", buttons=0, px_per_cm=10)
check("[5] buttons 15 px inside the right edge", info2["buttons"] == [[115.5, 60.0], [115.5, 140.0]], info2["buttons"])
check("[5] two holes on the left front", len(info2["holes"]) == 2, info2["holes"])
check("[5] pixel (115, 60) is the disc colour", tuple(out2[60, 115]) == tuple(col["disc"]), tuple(out2[60, 115]))

# [6]
out3, _ = post.draw_placket(atlas, {"front": isl}, marks, kind="jacket", style="zip", buttons=0, px_per_cm=10)
z = lab(out3[100, 100])
check("[6] the line is metal (L* 50 / 60, neutral)", min(abs(z[0] - 60), abs(z[0] - 50)) <= 1.0
      and abs(z[1]) < 1 and abs(z[2]) < 1, tuple(z))
check("[6] 9.5 px off the line stays grey", tuple(out3[100, 110]) == (128, 128, 128), tuple(out3[100, 110]))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
