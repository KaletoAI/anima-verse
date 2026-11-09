#!/usr/bin/env python3
"""Hair as its own mesh, task 4: the image gates (app/core/garment_gates.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_gates.py

Pure numpy on synthetic 100x100 RGB images — no world, no renderer, no GPU.
Every expectation below is derived by hand from plan
2026-11-09-base-body-phase4-hair (R7, Task 4).

Fixture (grey 128 background):
  Bald     body mask = head disc centre (50, 16) radius 6 ((x-50)^2 + (y-16)^2
           <= 36, rows 10..22) + torso rect x [40, 60) y [22, 95), skin
           (200, 160, 140).  y0 = 10, last row 94 -> Hb = 84.
           body zone row  int(10 + 0.30*84) = int(35.2)  = 35 (rows 35..94)
           shoulder row   int(10 + 0.19*84) = int(25.96) = 25 -> torso x 40..59,
                          cx = 49.5, half-width 9.5
           chest box rows int(10 + 0.17*84) = 24 .. 34,
                     cols int(49.5 - 5.7) = 43 .. int(49.5 + 5.7) = 55 (exclusive)
                     -> 11 x 12 = 132 base-mask pixels (all torso)
           chin row       int(10 + 0.13*84) = int(20.92) = 20
           hair_ref row   int(10 + 0.22*84) = int(28.48) = 28
           base body area = torso 20*73 = 1460 + the disc rows 10..21 (counted
                          from the fixture: 112) = 1572.
  Hair     block x [43, 57) y [8, 22), colour (90, 60, 30).
           |hair - skin| mean = (110 + 100 + 110) / 3 = 106.67;
           |hair - grey| mean = (38 + 68 + 98) / 3 = 68 — both > 20.

[1] Haired ok (bald + hair block): body_xor 0, body_dRGB 0 (zone rows 35..94
    untouched), chest_dRGB 0 (the box rows 24..34 hold no hair) -> pass on
    front and back.
[2] Hair over the chest (block y [8, 30)): chest box rows 24..29 x cols
    43..54 = 72 pixels at 106.67, the other 60 at 0 -> 72*106.67/132 = 58.18
    > 8 -> front FAILS; the back does not gate the chest -> passes.
[3] Haired shifted (torso x [41, 61)): XOR in the zone = cols 40 and 60 on
    60 rows = 120 / (20*60 = 1200) = 0.10 >= 0.015 -> fail.
[4] hair_ref of [1]: iterations max(1, round(2*100/1536)) = 1 and 1, minimum
    area 400*(100/1536)^2 = 1.7 px: the 14x14 block survives (the opening by
    the 3x3 cross only clips its 4 corner pixels) -> bbox [43, 8, 56, 21],
    area 196 - 4 = 192.
[5] Ghost ok (grey + the hair block, mask = the block): top_dy 0,
    centre_dx 0, w_ratio 1.0; body_left 0 (the block's rows 20..21 inside
    the disc differ by 106.67 from the skin) -> pass.
[6] Ghost with body left: + torso rows 40..94 in skin colour: body_left_px
    = 20*55 = 1100, share 1100/1572 = 0.6997 > 0.05 -> fail (the width also
    changes: ghost x 40..59 -> 19/13 = 1.462).
[7] bottoms_agree: ghost [5] has bottom 21/100 = 0.21, hair_h 13/100 = 0.13;
    against itself -> True; against a block y [8, 23) (bottom 0.22, hair_h
    0.14): |0.21 - 0.22| = 0.01 > 0.05*0.14 = 0.007 -> False.
[8] Inputs of different size -> ValueError. BODY_LEFT_MAX == 0.05 (ruling).

Calibration (Task 4 Step 0, spike images at H = 1536, BiRefNet-DIS masks;
recorded here, never read by this smoke):
  haired front s101 xor 0.0089 dRGB 3.56 chest 3.05 pass; s102 0.0098 pass;
         s103 xor 0.0206 FAIL; back s101 0.0067 / 4.14 pass, s102, s103 pass.
  hair_ref bbox front [659, 27, 876, 264], back [645, 30, 879, 339].
  ghostA front s201 top_dy 3, dx -1.0, w 1.000, body_left 0.0112 -> pass
         (s202 0.0120, s203 0.0186, ghostB 0.0087; back 0.0075..0.0127).
  direct front s201 top_dy 31, w 2.161, body_left 0.0479 -> fail (top/width);
         direct back top_dy 72, w 3.645, body_left 0.1734 -> fail.
  Body-left measures light hair over light skin as well: a synthetic real
  leftover (bald neck + shoulders pasted behind the hair) scores 0.174 front /
  0.160 back, a thin neck stub 0.0154 / 0.0122 — hence BODY_LEFT_MAX 0.05
  (ruling): large leftovers only.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []

GREY = (128, 128, 128)
SKIN = (200, 160, 140)
HAIR = (90, 60, 30)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def canvas():
    rgb = np.zeros((100, 100, 3), dtype=np.uint8)
    rgb[:] = GREY
    return rgb, np.zeros((100, 100), dtype=bool)


def paint(rgb, mask, region, colour):
    rgb[region] = colour
    mask |= region


def disc():
    yy, xx = np.mgrid[0:100, 0:100]
    return (xx - 50) ** 2 + (yy - 16) ** 2 <= 36


def rect(x0, x1, y0, y1):
    region = np.zeros((100, 100), dtype=bool)
    region[y0:y1, x0:x1] = True
    return region


def bald(torso_x0=40):
    rgb, mask = canvas()
    paint(rgb, mask, disc(), SKIN)
    paint(rgb, mask, rect(torso_x0, torso_x0 + 20, 22, 95), SKIN)
    return rgb, mask


def main() -> int:
    try:
        from app.core import garment_gates as gg
    except ImportError as e:
        check("garment_gates importable", str(e), "importable")
        print("FAILED: " + ", ".join(FAILS))
        return 1

    b_rgb, b_mask = bald()
    check("fixture base body area", int(b_mask.sum()), 1572)

    print("[1] haired ok")
    h_rgb, h_mask = bald()
    paint(h_rgb, h_mask, rect(43, 57, 8, 22), HAIR)
    for view in ("front", "back"):
        r = gg.haired_gate(b_rgb, b_mask, h_rgb, h_mask, view=view)
        check(f"{view} numbers", (r["body_xor"], r["body_dRGB"], r["chest_dRGB"]), (0.0, 0.0, 0.0))
        check(f"{view} zones", (r["head_top_bald"], r["body_h"]), (10, 84))
        check(f"{view} pass", (r["ok"], r["reasons"]), (True, []))

    print("[2] hair over the chest")
    c_rgb, c_mask = bald()
    paint(c_rgb, c_mask, rect(43, 57, 8, 30), HAIR)
    r = gg.haired_gate(b_rgb, b_mask, c_rgb, c_mask, view="front")
    check("chest dRGB", r["chest_dRGB"], round(72 * (320 / 3) / 132, 2))
    check("front fails", r["ok"], False)
    check("front reason", any("chest" in x for x in r["reasons"]), True)
    check("back passes", gg.haired_gate(b_rgb, b_mask, c_rgb, c_mask, view="back")["ok"], True)

    print("[3] haired shifted")
    s_rgb, s_mask = bald(torso_x0=41)
    paint(s_rgb, s_mask, rect(43, 57, 8, 22), HAIR)
    r = gg.haired_gate(b_rgb, b_mask, s_rgb, s_mask, view="front")
    check("body_xor", r["body_xor"], 0.1)
    check("shifted fails", r["ok"], False)

    print("[4] hair_ref")
    ref = gg.hair_ref(b_rgb, b_mask, h_rgb, h_mask)
    ys, xs = np.nonzero(ref)
    check("bbox", [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], [43, 8, 56, 21])
    check("area", int(ref.sum()), 192)

    print("[5] ghost ok")
    g_rgb, g_mask = canvas()
    paint(g_rgb, g_mask, rect(43, 57, 8, 22), HAIR)
    ok_gate = gg.ghost_gate(b_rgb, b_mask, ref, g_rgb, g_mask, view="front")
    check("framing", (ok_gate["top_dy"], ok_gate["centre_dx"], ok_gate["w_ratio"]), (0, 0.0, 1.0))
    check("chin row", ok_gate["chin_row"], 20)
    check("body left", (ok_gate["body_left_px"], ok_gate["body_left"]), (0, 0.0))
    check("ghost passes", (ok_gate["ok"], ok_gate["reasons"]), (True, []))

    print("[6] ghost with body left")
    l_rgb, l_mask = canvas()
    paint(l_rgb, l_mask, rect(43, 57, 8, 22), HAIR)
    paint(l_rgb, l_mask, rect(40, 60, 40, 95), SKIN)
    r = gg.ghost_gate(b_rgb, b_mask, ref, l_rgb, l_mask, view="front")
    check("body_left_px", r["body_left_px"], 1100)
    check("body_left share", r["body_left"], round(1100 / 1572, 5))
    check("w_ratio", r["w_ratio"], round(19 / 13, 3))
    check("fails on body left", any("body left" in x for x in r["reasons"]), True)
    check("fails", r["ok"], False)

    print("[7] bottoms_agree")
    check("bottom / hair_h", (ok_gate["bottom"], ok_gate["hair_h"]), (0.21, 0.13))
    check("same bottoms", gg.bottoms_agree(ok_gate, ok_gate), True)
    o_rgb, o_mask = canvas()
    paint(o_rgb, o_mask, rect(43, 57, 8, 23), HAIR)
    longer = gg.ghost_gate(b_rgb, b_mask, ref, o_rgb, o_mask, view="back")
    check("longer bottom", (longer["bottom"], longer["hair_h"]), (0.22, 0.14))
    check("bottoms differ", gg.bottoms_agree(ok_gate, longer), False)
    check("missing fields", gg.bottoms_agree({}, ok_gate), False)

    print("[8] limits and shapes")
    check("BODY_LEFT_MAX", gg.BODY_LEFT_MAX, 0.05)
    try:
        gg.haired_gate(b_rgb, b_mask, h_rgb[:50], h_mask[:50], view="front")
        check("size mismatch", "no error", "ValueError")
    except ValueError:
        check("size mismatch", "ValueError", "ValueError")

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
