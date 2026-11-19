#!/usr/bin/env python3
"""Smoke: the mouth channel's nose tip is searched near the head joint's midplane (A213).

Usage:
    ./.venv/bin/python scripts/smoke_mouth_nose.py

No server, no world, no Blender. Every expected number is derived by hand here. The pre-fix proof reads the pinned
commit 2a23beb00 (``git show``).

[1] mouth_math.nose_tip on a hand grid, head joint at side 0, height 1.5; window [-0.05, 0.08], reach 0.02.
    Columns S = -0.04, -0.02, 0, 0.02, 0.04; rows Z = 1.44, 1.48, 1.52, 1.58, 1.59 (heights -0.06, -0.02, 0.02,
    0.08, 0.09 around the joint). Depth (larger = further back):
      1.44: -0.30 everywhere                          (below the window: never the tip)
      1.48: -0.08 -0.09 -0.10  -0.09 -0.08
      1.52: -0.20 -0.10 -0.115 -0.10  NaN             (-0.20: a strand of hair 40 mm out, in front of the cheek)
      1.58: -0.20 -0.11 -0.114 -0.11 -0.09
      1.59: -0.50 everywhere                          (above the window)
    In the window and within 0.02 of side 0 (columns 1..3; |0.02| <= 0.02 counts) the smallest depth is -0.115
    at row 2, column 2 -> (2, 2), the nose. The pre-fix reach 0.045 also takes columns 0 and 4: -0.20 first at
    (2, 0), the hair -> that was the bug (the lip line was then searched from a point 40 mm out and 55 mm high).
    Reach 0.045 here -> (2, 0). Head joint at side 0.02 with reach 0.02: columns 2..4, smallest -0.115 -> (2, 2)
    (NaN at (2, 4) is skipped). A window without a face (all NaN) -> None.
[2] mouth_part's DEFAULTS carry ``'nose_reach': .02`` and measure() calls ``mouth_math.nose_tip``; the build stamp
    ``OP_BUILDS["mouth_part"]`` is at least 8 (a moved lip line is a new build).
[3] Pre-fix proof at 2a23beb00: the window was ``<= .045`` around the head joint and there was no ``nose_reach``.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import mouth_math as mm  # noqa: E402

PIN = "2a23beb00"
failed = 0


def check(label, ok, got=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "  got: %r" % (got,)))
    failed += 0 if ok else 1


nan = float("nan")
S = np.array([-.04, -.02, 0., .02, .04])
Z = np.array([1.44, 1.48, 1.52, 1.58, 1.59])
D = np.array([[-.30] * 5,
              [-.08, -.09, -.10, -.09, -.08],
              [-.20, -.10, -.115, -.10, nan],
              [-.20, -.11, -.114, -.11, -.09],
              [-.50] * 5])
W = [-.05, .08]
got = mm.nose_tip(D, S, Z, 0., 1.5, W, .02)
check("[1] reach 0.02 -> the nose (2, 2)", got == (2, 2), got)
got = mm.nose_tip(D, S, Z, 0., 1.5, W, .045)
check("[1] reach 0.045 -> the hair (2, 0)", got == (2, 0), got)
got = mm.nose_tip(D, S, Z, .02, 1.5, W, .02)
check("[1] joint at side 0.02 -> (2, 2), NaN skipped", got == (2, 2), got)
got = mm.nose_tip(np.full(D.shape, nan), S, Z, 0., 1.5, W, .02)
check("[1] no face -> None", got is None, got)

part = (ROOT / "app" / "blender" / "scripts" / "mouth_part.py").read_text()
check("[2] DEFAULTS nose_reach .02", "'nose_reach': .02" in part)
check("[2] measure uses mouth_math.nose_tip", "mouth_math.nose_tip(" in part)
rig = (ROOT / "app" / "core" / "extension_rig.py").read_text()
import re  # noqa: E402
m = re.search(r'"mouth_part": (\d+)\}', rig)
check("[2] mouth_part build >= 8", m is not None and int(m.group(1)) >= 8, m and m.group(1))


def show(path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN}:{path}"], capture_output=True, text=True,
                          check=True).stdout


old = show("app/blender/scripts/mouth_part.py")
check(f"[3] {PIN}: window <= .045", "(np.abs(S[None, :] - head.x) <= .045)" in old)
check(f"[3] {PIN}: no nose_reach", "nose_reach" not in old)

print("FAILED %d" % failed if failed else "all ok")
sys.exit(1 if failed else 0)
