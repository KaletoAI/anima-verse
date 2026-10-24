#!/usr/bin/env python3
"""Smoke: ``_cmu.despike`` — the glitch repair of a joint's rotation series
(the converter's ``_bake`` and ``scripts/repair_clip_spikes.py`` share it).
No Blender: ``_cmu`` is standard library only.

Usage: ./.venv/bin/python scripts/smoke_clip_despike.py

Every series is a rotation about the X axis, written as the angle per frame
(deg) and turned into quaternions (w, x, y, z) = (cos(a/2), sin(a/2), 0, 0),
so the angle between two keys is exactly the difference of the angles.
Threshold SPIKE_DEG = 10, CALM = 0.5, SNAP_FACTOR = 2, SNAP_SPREAD = 3.

[1] single spike: 0 0 0 30 0 0 0 → into 30 > 10, out 30 > 10, frames 2/4
    0 apart (< 0.5·30), the steps 1→2 and 4→5 are 0 (calm) → frame 3
    repaired to the blend of 0 and 0 = 0; returns [3].
[2] double spike: 0 0 0 25 25 0 0 0 → into 25, out (4→5) 25, frames 2/5 0
    apart, calm around → frames 3, 4 become the 1/3 and 2/3 blends of 0 and
    0 = 0; returns [3, 4].
[3] fast real motion untouched: a sine of amplitude 60 deg and period 8
    frames (angles 0, 42.4, 60, 42.4, 0, …; steps 42.4, 17.6, 17.6, 42.4):
    at the peak the joint turns 17.6 in and 17.6 out and frames i-1/i+1 are
    equal — out and back — but the step before (42.4) is far above
    CALM·17.6 = 8.8, so the event is not isolated → returns [], nothing
    changes. A real turning point is surrounded by motion, a glitch by rest.
[4] snap: 0 0 0 0 0 40 40 40 40 40 → one step of 40 > 2·10 that stays, the
    steps before (0) and after (0) below 0.5·10 → with the step between
    frames 4 and 5 the keys from lo = 4 − 3 + 1 = 2 to hi = 4 + 3 = 7 are
    re-blended from 0 to 40: frames 3..6 become 8, 16, 24, 32 deg (40·k/5,
    k = 1..4) — the snap now takes 5 steps of 8 deg; returns [3, 4, 5, 6].
[5] edge: 30 0 0 0 0 → the first key jumps 30 onto a neighbour that moves
    0 onwards (< 0.25·30) → it takes the neighbour's value 0; returns [0].
[6] below threshold untouched: 0 0 0 8 0 0 0 → 8 < 10 → returns [].
[7] a flip is no snap: 0 0 0 0 0 120 120 120 120 120 → the step of 120 is
    above SNAP_MAX_DEG 90 (a wrong solution, spreading it would make a
    spin) → returns [] and nothing changes.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/blender/scripts"))
import _cmu  # noqa: E402

FAIL = []


def series(degs):
    return [[math.cos(math.radians(a) / 2), math.sin(math.radians(a) / 2), 0.0, 0.0] for a in degs]


def angles(qs):
    # sign-aligned to the x-rotation family: angle = 2·atan2(x, w)
    return [round(math.degrees(2 * math.atan2(q[1], q[0])), 6) for q in qs]


def case(label, degs, want_fixed, want_angles):
    qs = series(degs)
    got = _cmu.despike(qs)
    a = angles(qs)
    ok = got == want_fixed and all(abs(x - y) < 1e-6 for x, y in zip(a, want_angles))
    print(f"[{label}] fixed {got} angles {[round(x, 3) for x in a]}")
    if not ok:
        FAIL.append(f"{label}: fixed {got} (want {want_fixed}), angles {a} (want {want_angles})")


case("1 single", [0, 0, 0, 30, 0, 0, 0], [3], [0] * 7)
case("2 double", [0, 0, 0, 25, 25, 0, 0, 0], [3, 4], [0] * 8)
sine = [60 * math.sin(2 * math.pi * k / 8) for k in range(32)]
case("3 fast motion", sine, [], sine)
case("4 snap", [0, 0, 0, 0, 0, 40, 40, 40, 40, 40], [3, 4, 5, 6],
     [0, 0, 0, 8, 16, 24, 32, 40, 40, 40])
case("5 edge", [30, 0, 0, 0, 0], [0], [0] * 5)
case("6 below threshold", [0, 0, 0, 8, 0, 0, 0], [], [0, 0, 0, 8, 0, 0, 0])
case("7 flip", [0] * 5 + [120] * 5, [], [0] * 5 + [120] * 5)

if FAIL:
    print("FAIL smoke_clip_despike")
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("OK smoke_clip_despike")
