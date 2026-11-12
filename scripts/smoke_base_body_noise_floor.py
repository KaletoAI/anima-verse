#!/usr/bin/env python3
"""Smoke: the back-fit noise gate judges the figure's noise FLOOR, so hair in the base body no longer blinds it
(``base_body_gates.noise_gate``, version 2; Task 6 fix 1 of the plan "hair from the body mesh", 2026-11-12).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_noise_floor.py

No world, no server, no real images: 1024 x 1024 RGBA fixtures saved as PNG (height 1024 = the work height, so
nothing is resampled; R = G = B, so the grey image is the value itself).

Fixture: alpha 255 on x 300..699, y 100..899 (the rest 0, grey 0). Inside, every texture is a checkerboard
128 +/- a; every 3x3 box inside one texture holds 5 pixels of the centre's sign and 4 of the other, so the residual
is exactly 8a/9 there (``smoke_base_body_back_fit.py`` [5]). "Hair" = rows 100..199 (a_h), "skin" = rows 200..899
(a), "outfit" = an optional band of rows with its own a_o.

Hand-derived:
- Blocks (NOISE_BLOCK 8) wholly inside the figure eroded by 4: x 304..695 -> block columns 38..86 (49), y 104..895
  -> block rows 13..111 (99): 4851 blocks. Block rows 13..23 are pure hair, 24 (rows 192..199) and 25 (200..207)
  touch the hair/skin seam (their residual is larger than the skin's), 26..111 pure skin: 86 x 49 = 4214 = 86.9 %.
  The floor (NOISE_QUANTILE 10th percentile) lies among the equal skin blocks: exactly 8a/9.
- Head (rows 100 .. 100 + int(0.12 * 800) = 195, eroded: rows 104..191): pure hair, mean 8a_h/9.
- Base: a_h = 36, a = 1 -> floor 0.8889, head 32.0.
  * fit with restyled hair a_h = 45, skin a = 1: floor 0.8889 -> score 1.0, ok (head ratio 40/32 = 1.25);
  * fit with grain on the skin a = 3, hair unchanged: floor 2.6667 -> score 3.0, refused;
  * a = 2: floor 1.7778 -> 2.0, refused.
  On 16fd3d2a (version 1, the head mean) both grainy fits read 32/32 = 1.0 and PASS — the blind spot of a haired
  head (proof below, the old module loaded from that commit).
- Bald base (a_h = a = 1: the head is skin): fit a = 2 everywhere -> floor and head both 1.7778 / 0.8889 = 2.0,
  refused by both versions (the verdict on a bald head stays as it was).
- Textured outfit: base a_h = 36, a = 1; fit with rows 500..899 a_o = 9 (residual 8.0), rows 200..499 skin a = 1:
  skin-only block rows 26..61 (rows 208..495; block 62 = rows 496..503 touches the outfit) = 36 x 49 = 1764 =
  36.4 % of the blocks > 10 % -> floor 0.8889, score 1.0, ok. The whole-figure mean (recorded only, ``figure_score``)
  does see the outfit: eroded rows 104..895 = 792, base (96 x 32 + 696 x 0.8889) / 792 = 4.66, fit (96 x 32 +
  300 x 0.8889 + 396 x 8) / 792 = 8.22 -> 1.76 (the two seams move it a little: 1.70 .. 1.85).
- Black outfit (NOISE_BLOCK_GREY 32..235): base as above; fit with skin grain a = 3 on rows 200..499 and a flat
  black outfit (grey 10, residual 0) on rows 500..899. Block rows 63..111 (mean grey 10) do not count; counted are
  rows 13..62 = 50 x 49 = 2450 blocks, 1764 of them (72 %) skin at 2.6667 -> floor 2.6667, score 3.0, refused.
  Counting the black blocks too (2401 of 4851 = 49.5 % at 0) would put the floor at 0 and pass the grain.
- A figure of 20 x 40 px (eroded 12 x 32): at most 1 x 4 whole blocks < NOISE_MIN_BLOCKS 20 -> not measurable,
  the gate passes with score None and reason "fit not measurable".
- Every result carries version 2.
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

OLD_COMMIT = "16fd3d2a"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def board(a, rows, size=1024):
    yy, xx = np.mgrid[0:size, 0:size]
    sign = np.where((yy + xx) % 2 == 0, 1, -1)
    return np.where(rows, 128 + a * sign, 0)


def fixture(path, hair, skin, outfit=None, box=(300, 700, 100, 900)):
    """Save the RGBA fixture: hair rows 100..199, skin below, ``outfit`` = (a_o, first row) overriding the skin."""
    from PIL import Image
    size = 1024
    x0, x1, y0, y1 = box
    yy, xx = np.mgrid[0:size, 0:size]
    inside = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    grey = np.zeros((size, size), np.int64)
    sign = np.where((yy + xx) % 2 == 0, 1, -1)
    grey = np.where(inside & (yy < 200), 128 + hair * sign, grey)
    grey = np.where(inside & (yy >= 200), 128 + skin * sign, grey)
    if outfit is not None:
        a_o, first, *level = outfit
        grey = np.where(inside & (yy >= first), (level[0] if level else 128) + a_o * sign, grey)
    grey = grey.astype(np.uint8)
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    Image.fromarray(np.dstack([grey, grey, grey, alpha]), "RGBA").save(path)
    return path


def old_gates(tmp):
    """``base_body_gates`` as of OLD_COMMIT, loaded from git."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/base_body_gates.py"],
                            capture_output=True, text=True, check=True).stdout
    path = tmp / "old_base_body_gates.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("old_base_body_gates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    from app.core import base_body_gates as gates
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("[1] the floor of the fixture")
        base = fixture(tmp / "base.png", 36, 1)
        n = gates.figure_noise(base)
        check("base floor", round(n["floor"], 4), 0.8889)
        check("base head", round(n["head"], 4), 32.0)

        print("[2] haired base")
        g = gates.noise_gate(fixture(tmp / "restyled.png", 45, 1), base)
        check("restyled hair", (g["ok"], g["score"], g["head_score"], g["version"]), (True, 1.0, 1.25, 2))
        g3 = gates.noise_gate(fixture(tmp / "grain3.png", 36, 3), base)
        check("skin grain a=3", (g3["ok"], g3["score"], g3["noise"], g3["reference_noise"]), (False, 3.0, 2.6667, 0.8889))
        g2 = gates.noise_gate(fixture(tmp / "grain2.png", 36, 2), base)
        check("skin grain a=2", (g2["ok"], g2["score"]), (False, 2.0))

        print("[3] bald base")
        bald = fixture(tmp / "bald.png", 1, 1)
        g = gates.noise_gate(fixture(tmp / "bald2.png", 2, 2), bald)
        check("bald, grain a=2", (g["ok"], g["score"], g["head_score"]), (False, 2.0, 2.0))
        g = gates.noise_gate(bald, bald)
        check("bald, clean", (g["ok"], g["score"]), (True, 1.0))

        print("[4] textured outfit")
        g = gates.noise_gate(fixture(tmp / "outfit.png", 36, 1, outfit=(9, 500)), base)
        check("outfit texture", (g["ok"], g["score"], 1.70 <= g["figure_score"] <= 1.85), (True, 1.0, True))

        g = gates.noise_gate(fixture(tmp / "black.png", 36, 3, outfit=(0, 500, 10)), base)
        check("black outfit, skin grain", (g["ok"], g["score"]), (False, 3.0))
        real = gates.NOISE_BLOCK_GREY
        gates.NOISE_BLOCK_GREY = (0.0, 255.0)
        try:
            g = gates.noise_gate(tmp / "black.png", base)
            check("... counting black blocks too", (g["ok"], g["score"]), (True, 0.0))
        finally:
            gates.NOISE_BLOCK_GREY = real

        print("[5] too small a figure")
        g = gates.noise_gate(fixture(tmp / "tiny.png", 1, 1, box=(500, 520, 100, 140)), base)
        check("tiny figure", (g["ok"], g["score"], g.get("reason")), (True, None, "fit not measurable"))

        print(f"[6] fails on the old code ({OLD_COMMIT})")
        old = old_gates(tmp)
        o3 = old.noise_gate(tmp / "grain3.png", base)
        o2 = old.noise_gate(tmp / "grain2.png", base)
        check("old: grain a=3 passes (blind)", (o3["ok"], o3["score"]), (True, 1.0))
        check("old: grain a=2 passes (blind)", (o2["ok"], o2["score"]), (True, 1.0))
        o = old.noise_gate(tmp / "bald2.png", bald)
        check("old: bald grain refused as now", (o["ok"], o["score"]), (False, 2.0))

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
