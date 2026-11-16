#!/usr/bin/env python3
"""Smoke: the colour of a painted piece (Ruling A148, ``app/core/paint_colour.py``).

Usage:  ./.venv/bin/python scripts/smoke_paint_colour_a148.py

No server, no world DB (``paths.init`` on a temp dir first), no network.

Expected values, derived by hand:
[1] ``validate``: ("#ABCDEF", 0.5) -> {"hex": "#abcdef", "strength": 0.5}; ("", 1) -> None (clears);
    "red" -> ValueError; strength 2 -> ValueError; strength None -> 1.0 (the default).
[2] ``wanted``: profile {garment_paint_colours: {A: {#112233, 0.8}}}, pieces {top: A, legs: B}, painted [A, B] ->
    {"version": 1, "pieces": {A: {"hex": "#112233", "strength": 0.8, "regions": ["forearm", "shoulder", "spine",
    "upper_arm"]}}, "painted": ["A", "B"]} (paint_region.SLOT_REGIONS["top"], sorted). A not painted -> {}.
    No colour stored -> {}.
[3] ``recolour_texels`` at strength 1 of three identical texels (50, 50, 200) to #ff0000: every texel's Lab moves by
    target - median = target - itself, so each lands on #ff0000 -> (255, 0, 0) exactly (round trip of an sRGB
    primary). Strength 0 -> the bytes unchanged.
[4] Shading kept: texels (100, 100, 100) and (150, 150, 150) to #3366cc at strength 1: the CIELAB L* difference
    of the two (grey 100 -> L* 42.37, grey 150: (0.5882+0.055)/1.055 = 0.6097, ^2.4 = 0.3050, cbrt 0.6732, L* = 116*0.6732-16 = 62.09; so 19.71) is kept within the 8-bit rounding (±1.0),
    and their median (the mean of two) lands on the target within ΔE 1.5.
[5] ``recolour_atlas`` with ONE painted piece (the mask is the changed texels, no regions): a 4x4 plain atlas of
    (200, 150, 120, 255) with three texels painted (50, 50, 200, 255) -> those three become (255, 0, 0, 255); the
    13 others are byte-identical (0 diff) and no alpha changes.
[6] ``bone_region`` (the worker's rule): "mixamorig:LeftForeArm" -> forearm, "mixamorig:Spine2" -> spine,
    "mixamorig:LeftUpLeg" -> upper_leg, "mixamorig:RightHand" -> hand, "tail_01" -> None.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke-a148-"))

import numpy as np  # noqa: E402

from app.core import paint_colour as pc  # noqa: E402

failures = []


def check(label, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(label)


# [1]
check("[1] validate normalises", pc.validate("#ABCDEF", 0.5) == {"hex": "#abcdef", "strength": 0.5})
check("[1] empty clears", pc.validate("", 1) is None)
check("[1] default strength", pc.validate("#000000", None) == {"hex": "#000000", "strength": 1.0})
for bad in (("red", 1), ("#000000", 2)):
    try:
        pc.validate(*bad)
        check(f"[1] {bad} refused", False)
    except ValueError:
        check(f"[1] {bad} refused", True)

# [2]
profile = {pc.SETTINGS_KEY: {"A": {"hex": "#112233", "strength": 0.8}}}
w = pc.wanted(profile, {"top": "A", "legs": "B"}, ["A", "B"])
check("[2] wanted", w == {"version": 1, "pieces": {"A": {"hex": "#112233", "strength": 0.8,
                                                         "regions": ["forearm", "shoulder", "spine", "upper_arm"]}},
                          "painted": ["A", "B"]}, str(w))
check("[2] not painted -> {}", pc.wanted(profile, {"top": "A"}, ["B"]) == {})
check("[2] no colour -> {}", pc.wanted({}, {"top": "A"}, ["A"]) == {})

# [3]
rgb = np.array([[50, 50, 200]] * 3, np.uint8)
out, rec = pc.recolour_texels(rgb, "#ff0000", 1.0)
check("[3] lands on #ff0000", (out == np.array([255, 0, 0], np.uint8)).all(), str(out.tolist()))
out0, _ = pc.recolour_texels(rgb, "#ff0000", 0.0)
check("[3] strength 0 unchanged", (out0 == rgb).all())

# [4]
greys = np.array([[100, 100, 100], [150, 150, 150]], np.uint8)
g_out, g_rec = pc.recolour_texels(greys, "#3366cc", 1.0)
lab_in, lab_out = pc.rgb8_to_lab(greys), pc.rgb8_to_lab(g_out)
check("[4] L* of grey 100 / 150", abs(lab_in[0, 0] - 42.37) < 0.05 and abs(lab_in[1, 0] - 62.09) < 0.05,
      str(lab_in[:, 0]))
dl = lab_out[1, 0] - lab_out[0, 0]
check("[4] L* difference kept (19.71 ± 1.0)", abs(dl - 19.71) <= 1.0, f"{dl:.2f}")
check("[4] median on target (ΔE ≤ 1.5)", g_rec["delta_e_after"] <= 1.5, str(g_rec["delta_e_after"]))

# [5]
plain = np.zeros((4, 4, 4), np.uint8)
plain[...] = (200, 150, 120, 255)
atlas = plain.copy()
painted = [(0, 1), (2, 2), (3, 0)]
for y, x in painted:
    atlas[y, x] = (50, 50, 200, 255)
colours = {"version": 1, "painted": ["A"], "pieces": {"A": {"hex": "#ff0000", "strength": 1.0, "regions": ["spine"]}}}
after, proof = pc.recolour_atlas(atlas, plain, b"", colours)
check("[5] painted texels red", all(tuple(after[y, x]) == (255, 0, 0, 255) for y, x in painted),
      str([after[y, x].tolist() for y, x in painted]))
outside = np.ones((4, 4), bool)
for y, x in painted:
    outside[y, x] = False
check("[5] 13 texels byte-identical", int(outside.sum()) == 13 and (after[outside] == atlas[outside]).all())
check("[5] alpha unchanged", (after[..., 3] == atlas[..., 3]).all())
check("[5] proof counts 3 texels", proof["pieces"]["A"]["texels"] == 3, str(proof))

# [6]
for name, want in (("mixamorig:LeftForeArm", "forearm"), ("mixamorig:Spine2", "spine"),
                   ("mixamorig:LeftUpLeg", "upper_leg"), ("mixamorig:RightHand", "hand"), ("tail_01", None)):
    check(f"[6] bone_region({name})", pc.bone_region(name) == want, str(pc.bone_region(name)))

print("ALL OK" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
