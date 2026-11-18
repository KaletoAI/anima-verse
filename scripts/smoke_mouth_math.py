#!/usr/bin/env python3
"""Smoke: the pure maths of the mouth channel build (app/blender/scripts/mouth_math.py, Ruling A203).

Usage:
    ./.venv/bin/python scripts/smoke_mouth_math.py

No server, no world, no Blender. Every expected number is derived by hand here.

[1] ring_depths(0.02, first 0.003, growth 1.3): 0; +0.003 = 0.003; +0.0039 = 0.0069; +0.00507 = 0.01197; the
    next step 0.006591 would reach 0.018561, which is not under 0.02 - 0.006591/2 = 0.0167045, so the list ends
    with the depth itself: [0, 0.003, 0.0069, 0.01197, 0.02].
[2] lip_row, rows every 0.5 mm from 0 to 60 mm, chin 0, nose 0.06, luminance 0.7 with two dark lines (0.3) of two
    rows each at rows 40-41 (20 mm) and 80-81 (40 mm); redness constant. prior 0.5 puts the prior's centre at
    30 mm, between both. The running mean over 3 rows gives (0.7 + 0.3 + 0.3)/3 = 0.433333 on each line row; the
    rows 8 above and below (span 4 mm) are 0.7, so the line contrast is 0.266667 on all four. With equal redness
    the prior decides: rows 41 (20.5 mm) and 80 (40.0 mm) are 9.5 and 10 mm from the centre -> row 41.
    With the redness raised from 0.2 to 0.4 for rows 70..90 (around the upper line) the upper line wins: the
    redness smoothed over 6 mm (13 rows) is 0.4 at row 80 and 0.2 at row 41, the median between chin and nose is
    0.2 and the range 0.2, so q = 1 at row 80 (factor 2) and 0 at row 41 (factor 1); the priors
    exp(-0.5 (10/12)^2) = 0.706648 and exp(-0.5 (9.5/12)^2) = 0.731012 give 0.266667 x 0.706648 x 2 = 0.376879
    against 0.266667 x 0.731012 = 0.194937 -> row 80 (rows 80 and 81 share q; 80 is nearer the centre).
    A flat face (luminance 0.7 everywhere) has no lip line: a reason string.
[3] corners: columns 0..60 (1 mm apart), contrast 0.2 on columns 10..50 and 0.02 elsewhere, start 30, corner 0.3:
    the central contrast is 0.2, the limit 0.06; going out, column 10 / 50 is the last at or above it (the median
    of three at column 10 is median(0.02, 0.2, 0.2) = 0.2, at column 9 it is 0.02) -> (10, 50).
[4] jaw_hinge: opening (0, 0, 1.5), Hips (0, 0, 1.0), Head (0, 0, 1.54), back 0.085, up 0.03, reference 0.6, scale
    [0.8, 1.25]: k = 0.54/0.6 = 0.9 -> hinge (0, 0.0765, 1.527). Head at 1.9: 0.9/0.6 = 1.5 clamps to 1.25 ->
    (0, 0.10625, 1.5375).
[5] turned: (0, -0.1, 0) about the origin's side axis by 90 degrees: y' = y cos - z sin = 0, z' = y sin + z cos =
    -0.1 -> (0, 0, -0.1): the front goes DOWN (the jaw opens). The opening of [4] turned by 26 degrees about its
    hinge moves by the chord 2 r sin 13 = 2 x sqrt(0.0765^2 + 0.027^2) x 0.224951 = 2 x 0.081125 x 0.224951 =
    0.036498 m.
[6] lower_follow(d, 0.08): 1 at 0, 1 - smoothstep(0.5) = 0.5 at 0.04, 0 at 0.08; at 0.02: t = 0.25,
    smoothstep = 0.0625 x 2.5 = 0.15625 -> 0.84375.
[7] rim_share, ends at x = -0.025 and 0.025, corner 0.008: the middle (x = 0) is 8 mm+ from both ends -> lower 1,
    upper 0; an end -> 0.5 / 0.5; 4 mm from an end (t = 0.5, smoothstep 0.5) -> lower 0.75, upper 0.25: the
    opening there is half the full height.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/blender/scripts"))
import mouth_math as mm  # noqa: E402

failed = 0


def check(label, ok, got=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got})"))
    failed += 0 if ok else 1


LINE = {"prior": .5, "prior_sigma": .2, "red_gain": 1., "band": .008, "span": .004, "min_contrast": .03,
        "corner": .3, "half_min": .015, "half_max": .03}

got = mm.ring_depths(.02, {"first": .003, "growth": 1.3})
check("[1] ring depths", np.allclose(got, [0, .003, .0069, .01197, .02], atol=1e-12), got)

v = np.arange(0, .06 + 1e-9, .0005)
lum = np.full(len(v), .7)
lum[[40, 41, 80, 81]] = .3
red = np.full(len(v), .2)
row = mm.lip_row(lum, red, v, .06, 0., LINE)
check("[2] equal redness: the line nearer the prior, contrast 0.266667",
      row[0] == 41 and abs(row[1] - .2666667) < 1e-6, row)
red2 = red.copy()
red2[70:91] = .4
row = mm.lip_row(lum, red2, v, .06, 0., LINE)
check("[2] redder around the upper line: row 80", row[0] == 80, row)
check("[2] a flat face has no lip line", isinstance(mm.lip_row(np.full(len(v), .7), red, v, .06, 0., LINE), str))

cols = np.arange(61)
contrast = np.where((cols >= 10) & (cols <= 50), .2, .02)
check("[3] corners (10, 50)", mm.corners(cols, contrast, 30, LINE, .001) == (10, 50),
      mm.corners(cols, contrast, 30, LINE, .001))

JAW = {"back": .085, "up": .03, "open_deg": 26., "reference": .6, "scale": [.8, 1.25]}
hinge, k = mm.jaw_hinge([0, 0, 1.5], [0, 0, 1.0], [0, 0, 1.54], JAW)
check("[4] hinge (0, 0.0765, 1.527), k 0.9", np.allclose(hinge, [0, .0765, 1.527], atol=1e-9) and abs(k - .9) < 1e-9,
      (hinge, k))
hinge2, k2 = mm.jaw_hinge([0, 0, 1.5], [0, 0, 1.0], [0, 0, 1.9], JAW)
check("[4] clamped to 1.25", np.allclose(hinge2, [0, .10625, 1.5375], atol=1e-9) and k2 == 1.25, (hinge2, k2))

got = mm.turned(np.array([[0, -.1, 0]]), np.zeros(3), np.pi / 2)[0]
check("[5] the front goes down", np.allclose(got, [0, 0, -.1], atol=1e-12), got)
moved = np.linalg.norm(mm.turned(np.array([[0, 0, 1.5]]), hinge, np.radians(26.))[0] - [0, 0, 1.5])
check("[5] chord 0.036498 m", abs(moved - .036498) < 2e-6, moved)

got = [float(mm.lower_follow(d, .08)) for d in (0., .02, .04, .08)]
check("[6] lower wall follow", np.allclose(got, [1, .84375, .5, 0], atol=1e-12), got)

ends = (-.025, .025)
got = [float(mm.rim_share(x, ends, .008, low)) for x, low in ((0, True), (0, False), (.025, True), (.025, False),
                                                              (.021, True), (-.021, False))]
check("[7] rim shares", np.allclose(got, [1, 0, .5, .5, .75, .25], atol=1e-12), got)

print("FAILED (%d)" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
