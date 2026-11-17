#!/usr/bin/env python3
"""Ruling A193: the channel axes follow the anatomy. Every expected number is derived BY HAND below (§ B5a).

Usage: ./.venv/bin/python scripts/smoke_channel_anatomy_axis.py   (no server, no world, no storage)

[1] pelvis_frame. Body frame side (1,0,0), up (0,1,0), front (0,0,1). Hips (0,1,0), Spine (0, 1.1, 0.1·tan 10°)
    = (0, 1.1, 0.017633): the pelvis leans 10° forward. up_p = (0, cos 10°, sin 10°) = (0, 0.984808, 0.173648);
    front_p = side × up_p = (1,0,0) × (0, c, s) = (0, −s, c) = (0, −0.173648, 0.984808) (dot with front > 0, kept).
[2] The pack's axis [0, cos 35°, −sin 35°] = [0, 0.819152, −0.573576] in that frame:
    0.819152·up_p − 0.573576·front_p = (0, 0.819152·0.984808 + 0.573576·0.173648,
    0.819152·0.173648 − 0.573576·0.984808) = (0, 0.906308, −0.422618) — 25° back from the body's up (35° − 10°):
    atan(0.422618 / 0.906308) = 25.000°.
[3] tilted: axis (0,1,0), side (1,0,0), tilt +30° → Rodrigues by −30° about x: (0, cos 30°, −sin 30°) =
    (0, 0.866025, −0.5) — toward the back (−front). Tilt −30° → (0, 0.866025, +0.5).
[4] validate_overrides: an entry without tilt_deg reads tilt 0 and writes it back; tilt 45 passes, 45.5 is refused;
    an unknown extra key is refused.
[5] locate_mouth on a synthetic head. Joints: Hips (0,1,0), Head (0,1.6,0), Neck (0,1.5,−0.01), LeftArm (0.2,1.4,0),
    RightArm (−0.2,1.4,0), LeftFoot (0.1,0.1,0), LeftToeBase (0.1,0,0.1) → side x, up y, front z. Body points on the
    mid-plane at the bin centres c_i = −0.1485 + 0.003·i (bins of 3 mm from −0.15 above the head joint):
    neck i = 0..29 at front 0.03, face i = 30..59 (c −0.0585 … 0.0285) at front 0.11, plus the nose tip at i = 53
    (c 0.0105) at front 0.14. Dilated profile (max over i ± 2): 0.14 on i 51..55, 0.11 on 28..50 and 56..61, 0.03
    below 28.
    Nose: the front-most raw bin in the window [−0.05, 0.08] → i 53, v_n = 0.0105. Chin: going down from 53 the
    first bin whose dilated profile is under 0.14 − 0.05 = 0.09 is i 27, moved up by DILATE 2 → i 29, v_c = −0.0615.
    Mouth v_m = −0.0615 + 0.75·(0.0105 + 0.0615) = −0.0075 → bin 47 (dilated window 45..49, no nose), front 0.11:
    O = (0, 1.6 − 0.0075, 0.11) = (0, 1.5925, 0.11).
    Axis toward the midpoint of Head and Neck (0, 1.55, −0.005): (0, −0.0425, −0.115), |·| = 0.122602 → u =
    (0, −0.346650, −0.937994), 20.28° below the horizontal; B = O + 0.1·u = (0, 1.557835, 0.016201).
[6] A head without a Neck joint → a reason, not a record.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.core.collision_channels import pelvis_frame, tilted, validate_overrides  # noqa: E402
from app.core.mouth_landmark import locate_mouth  # noqa: E402

failed = 0


def check(label, ok, got=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got})"))
    if not ok:
        failed += 1


def near(a, b, eps=1e-5):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=eps)


frame = {"side": np.array([1.0, 0, 0]), "up": np.array([0, 1.0, 0]), "front": np.array([0, 0, 1.0])}
# [1]
pv = pelvis_frame({"mixamorig:Hips": [0, 1, 0], "mixamorig:Spine": [0, 1.1, 0.1 * math.tan(math.radians(10))]}, frame)
check("[1] pelvis up", near(pv["up"], [0, 0.984808, 0.173648]), pv["up"])
check("[1] pelvis front", near(pv["front"], [0, -0.173648, 0.984808]), pv["front"])
# [2]
axis = np.array([0, 0.819152, -0.573576]) @ np.stack([pv["side"], pv["up"], pv["front"]])
check("[2] axis in the pelvis frame", near(axis, [0, 0.906308, -0.422618]), axis)
check("[2] 25° back from up", abs(math.degrees(math.atan2(-axis[2], axis[1])) - 25.0) < 1e-3, axis)
# [3]
check("[3] tilt +30 → back", near(tilted(np.array([0, 1.0, 0]), frame["side"], 30), [0, 0.866025, -0.5]))
check("[3] tilt −30 → front", near(tilted(np.array([0, 1.0, 0]), frame["side"], -30), [0, 0.866025, 0.5]))
# [4]
base = {"offset_mm": [0, 0, 0], "radius_scale": 1, "depth_scale": 1, "cone_deg": 30}
check("[4] tilt absent → 0", validate_overrides({"c": base})["c"]["tilt_deg"] == 0)
check("[4] tilt 45 passes", validate_overrides({"c": {**base, "tilt_deg": 45}})["c"]["tilt_deg"] == 45)
for bad, what in (({**base, "tilt_deg": 45.5}, "45.5"), ({**base, "other": 1}, "extra key")):
    try:
        validate_overrides({"c": bad})
        check(f"[4] {what} refused", False, "accepted")
    except ValueError:
        check(f"[4] {what} refused", True)
# [5]
joints = {"Hips": [0, 1, 0], "Head": [0, 1.6, 0], "Neck": [0, 1.5, -0.01], "LeftArm": [0.2, 1.4, 0],
          "RightArm": [-0.2, 1.4, 0], "LeftFoot": [0.1, 0.1, 0], "LeftToeBase": [0.1, 0, 0.1]}
names = [f"mixamorig:{n}" for n in joints]
index_of = {n.lower(): i for i, n in enumerate(joints)}
positions = np.array(list(joints.values()), float)
pts = []
for i in range(60):
    c = -0.1485 + 0.003 * i
    pts.append([0, 1.6 + c, 0.03 if i < 30 else 0.11])
pts.append([0, 1.6 + 0.0105, 0.14])
got = locate_mouth(names, index_of, positions, np.array(pts))
check("[5] a record", isinstance(got, dict), got)
if isinstance(got, dict):
    check("[5] joint", got["a"] == "mixamorig:Head", got["a"])
    check("[5] O", near(got["a_pos"], [0, 1.5925, 0.11], 1e-4), got["a_pos"])
    check("[5] B", near(got["b_pos"], [0, 1.557835, 0.016201], 1e-4), got["b_pos"])
    u = np.subtract(got["b_pos"], got["a_pos"])
    check("[5] 20.3° down", abs(math.degrees(math.asin(-u[1] / np.linalg.norm(u))) - 20.28) < 0.05, u)
# [6]
no_neck = {k: v for k, v in joints.items() if k != "Neck"}
got = locate_mouth([f"mixamorig:{n}" for n in no_neck], {n.lower(): i for i, n in enumerate(no_neck)},
                   np.array(list(no_neck.values()), float), np.array(pts))
check("[6] no Neck → reason", isinstance(got, str), got)

print("FAILED" if failed else "ALL OK")
sys.exit(1 if failed else 0)
