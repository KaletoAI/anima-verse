#!/usr/bin/env python3
"""The split gate of the texture from cut (``cut_texture_post.split_gate``, live run 2026-11-22: MiniMax painted
Gelina's front skirt panel as two pieces with a white line between them, and the island gates passed it).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_split.py

No server, no world, no hub: synthetic 200 x 200 answers. Hand-derived expectations, ``SPLIT_GATE`` =
{edge_cm 1.0, length 0.4, width_cm 3.0, item_share 0.02}, ``px_per_cm`` 10, the answer's foreground threshold 11:

The island: rows 20..179, cols 20..179 (160 x 160 px), filled with a mid grey (128). Erosion r = round(1.0 x 10)
= 10 px -> the inner island rows 30..169, cols 30..169: 140 px both ways. A line's width limit 3.0 x 10 = 30 px.

[1] the plain panel: no background pixel inside -> ok, value 0.0, no line.
[2] a white vertical line cols 95..104 (10 px), rows 0..199 (through the whole panel): inside the inner island
    rows 30..169 -> length 140, the island's extent along the rows 140 -> share 140 / 140 = 1.0 >= 0.4; width =
    area / length = (10 x 140) / 140 = 10 px = 1.0 cm <= 3.0 -> REJECTED, value 1.0, one line {island 1, length 1.0,
    width_cm 1.0}, text "split line through a panel: 1.00 of its extent".
[3] the same line rows 60..109 only (50 px): share 50 / 140 = 0.357 < 0.4 -> ok, value 0.357.
[4] rows 60..119 (60 px): share 60 / 140 = 0.4286 -> 0.429 >= 0.4 -> rejected.
[5] a horizontal line rows 95..104, cols 0..199: the box is 10 x 140 inside -> along the cols, 140 / 140 = 1.0 ->
    rejected (a split in either direction).
[6] a white hole 100 tall x 40 wide (rows 50..149, cols 80..119): width 40 x 100 / 100 = 40 px > 30 -> not a line;
    value 0.0 (a wide hole is the coverage gate's business), ok.
[7] 200 white single pixels on a 7-px lattice inside the inner island (no two touching): each 1 px long, share
    1 / 140 = 0.00714 -> 0.007, ok — a sparkle is not a line.
[8] a light-grey (240) line: its distance from white 15 > 11 is foreground -> no background inside -> value 0.0, ok
    (only background-coloured lines count).
[9] the item guard with the line of [2]: item fabric of 1000 pixels, 50 of them white (5 % >= 2 %) -> skipped, ok,
    note names 0.050; 10 white (1 % < 2 %) -> not skipped, rejected as in [2].
[10] two islands (ids 1 and 2, the right half labelled 2 at cols 100..179): the line of [2] at cols 95..104 lies in
    island 1 cols 95..99 (5 px) and island 2 cols 100..104 (5 px); island 1 is cols 20..99 -> inner cols 30..89, the
    line's island-1 part (cols 95..99) is OUTSIDE the inner island -> nothing in 1; island 2 cols 100..179 -> inner
    cols 110..169, the line part cols 100..104 outside too -> ok. A line ALONG a seam between two islands is no split.
[11] no island (all labels 0) -> None.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app.core import cut_texture_post as post  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


PPC, TOL = 10.0, 11


def panel(fill=128):
    img = np.full((200, 200, 3), 255, np.uint8)
    img[20:180, 20:180] = fill
    lab = np.zeros((200, 200), np.int32)
    lab[20:180, 20:180] = 1
    return img, lab


check("[0] SPLIT_GATE constants", post.SPLIT_GATE == {"edge_cm": 1.0, "length": 0.4, "width_cm": 3.0,
                                                      "item_share": 0.02}, str(post.SPLIT_GATE))

img, lab = panel()
g = post.split_gate(img, lab, PPC, TOL)
check("[1] plain panel ok, value 0", g["ok"] and g["value"] == 0.0 and g["lines"] == [], str(g))

img, lab = panel()
img[:, 95:105] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[2] full line rejected, value 1.0", (not g["ok"]) and g["value"] == 1.0, str(g))
check("[2] one line, width 1.0 cm", g["lines"] == [{"island": 1, "length": 1.0, "width_cm": 1.0}], str(g["lines"]))
check("[2] text", g["text"] == "split line through a panel: 1.00 of its extent", g["text"])

img, lab = panel()
img[60:110, 95:105] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[3] 50 px line ok, value 0.357", g["ok"] and g["value"] == 0.357, str(g))

img, lab = panel()
img[60:120, 95:105] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[4] 60 px line rejected, value 0.429", (not g["ok"]) and g["value"] == 0.429, str(g))

img, lab = panel()
img[95:105, :] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[5] horizontal line rejected, value 1.0", (not g["ok"]) and g["value"] == 1.0, str(g))

img, lab = panel()
img[50:150, 80:120] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[6] wide hole is no line: ok, value 0.0", g["ok"] and g["value"] == 0.0, str(g))

img, lab = panel()
pts = [(30 + 7 * (k // 20), 30 + 7 * (k % 20)) for k in range(200)]
for y, x in pts:
    img[y, x] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[7] 200 sparkles ok, value 0.007", g["ok"] and g["value"] == 0.007, str(g))

img, lab = panel()
img[:, 95:105] = 240
g = post.split_gate(img, lab, PPC, TOL)
check("[8] light-grey line is foreground: ok, value 0.0", g["ok"] and g["value"] == 0.0, str(g))

img, lab = panel()
img[:, 95:105] = 255
fabric = np.full((1000, 3), 128.0)
fabric[:50] = 255.0
g = post.split_gate(img, lab, PPC, TOL, fabric)
check("[9] item with 5 % white fabric: skipped, ok", g["ok"] and g.get("skipped") and "0.050" in g["note"], str(g))
fabric = np.full((1000, 3), 128.0)
fabric[:10] = 255.0
g = post.split_gate(img, lab, PPC, TOL, fabric)
check("[9] item with 1 % white fabric: rejected", (not g["ok"]) and not g.get("skipped"), str(g))

img, lab = panel()
lab[20:180, 100:180] = 2
img[:, 95:105] = 255
g = post.split_gate(img, lab, PPC, TOL)
check("[10] a line along the seam of two islands is no split", g["ok"] and g["value"] == 0.0, str(g))

check("[11] no island -> None", post.split_gate(img, np.zeros((200, 200), np.int32), PPC, TOL) is None)

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
