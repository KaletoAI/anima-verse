#!/usr/bin/env python3
"""Numeric check of the ROLL REFERENCE the FBX clip converter builds —
`_secondary` / `_elbow_axis` in `app/blender/scripts/fbx_clip.py`.

Usage:
    ./.venv/bin/python scripts/smoke_clip_roll.py

Needs Blender (auto-discovered, or image_generation.blender_executable, same
as the other blender smokes) because the converter's maths runs on
`mathutils`. No server, no world DB, no clip library — the joint positions
below are written out by hand here.

WHAT IS BEING PINNED
====================
A bone's frame needs a SECONDARY axis to fix its roll. For a limb the honest
one is the bend normal (upper x lower), but it vanishes on a straight limb —
so below 8 deg of bend an anatomical fallback is used, above 30 deg the bend
normal, and in between the two are blended (`_bend_weight`).

The clip's rotation is `R = F_source(t) . F_mixamo_rest^T`. The reference rig
`shared/models/rig/reference.fbx` stands with STRAIGHT elbows, so its frames
are always built from the fallback, while a bent source frame is built from
the bend normal. If the two do not point the same way, their difference lands
in R as a ROLL — invisible on a rigid skeleton (the hand still arrives, within
1.0 deg measured) and ruinous on skin, because linear blend skinning pinches a
joint to cos(twist/2) of its radius.

That is what happened until 2026-09-04. The arms' fallback was the raw PALM
axis (pinky -> index), which in the Mixamo rest runs FORWARD, while the bend
normal runs UP/DOWN — 90 deg apart. Measured on the MOB1 pack, converted vs.
its own source:

    upper arm roll   +90.9 / +35.7 deg     source  +31.8 / -23.0
    forearm roll     -60.7 / -57.6 deg     source   -0.4 /  +0.3

The forearm undid what the upper arm invented, so the net was right and only
the SPLIT was wrong: a 111 deg shoulder pinched to cos(55.5) = 0.57 of its
radius and a 100 deg elbow to 0.64. `_elbow_axis` derives the fallback FROM
the palm — `bone x palm` — so that it lands on the bend normal instead.

THE EXPECTATIONS, DERIVED BY HAND
=================================
A synthetic Mixamo-style T-pose, centimetres, Y up, the figure facing +Z:

    rfemur (-10, 90, 0)   lfemur (10, 90, 0)      -> pelvis axis = +X
    lhumerus (20,150,0)  lradius (45,150,0)  lhand (70,150,0)   -> arm +X
    LeftHandPinky1 (75,150,-3)  LeftHandIndex1 (75,150,3)
                                            -> palm axis = index - pinky = +Z
    the right side mirrored through x -> -x  -> arm -X, palm axis STILL +Z
    (both palms face down, so both index fingers lie forward)

[1] THE FALLBACK IS THE HINGE, NOT THE PALM.
    `_elbow_axis(bone, palm)` = bone x palm:
        left   +X x +Z = -Y        right   -X x +Z = +Y
    So the straight arm's secondary is (0,-1,0) / (0,+1,0) — and 90.0 deg away
    from the palm axis the old code returned. Both must hold, the second one
    is what makes this a real change.

[2] AND IT IS WHERE THE BEND NORMAL POINTS.
    Bend the left elbow 90 deg forward: lhand -> (45,150,25), so the forearm
    runs +Z. The bend normal is
        up x fore = +X x +Z = -Y                 (right: -X x +Z = +Y)
    identical to [1]. Bend weight at 90 deg is 1.0 (band 8..30), so the frame
    takes the bend normal alone — and rest and pose read the SAME axis. The
    angle between the straight-arm secondary and the bent-arm secondary is
    therefore 0.0 deg, where the palm fallback gave 90.0.

[3] MID-BAND, THE BLEND IS A NO-OP TOO.
    Bend the elbow 19 deg (the middle of the 8..30 band, w = 0.5): the two
    candidates coincide, so any blend of them is the same axis again. 0.0 deg
    against [1]. This is the case the blend was introduced for — a relaxed
    idle sitting ON the band — and it now costs nothing.

[4] THE LEGS ARE UNTOUCHED, and were never wrong: in a T-pose the knee's bend
    normal already runs along the pelvis axis. Thigh -Y, shin bent 42 deg
    BACKWARD (foot -> (10,45,-36) from tibia (10,45,0), i.e. the shin runs
    (0,-40,-36) from the knee... written out below), so
        thigh x shin = -Y x shin, which has NO Y component and points +X
    the same +X the straight leg's pelvis fallback gives. 0.0 deg either way,
    with and without this change.

[5] A DEGENERATE PALM (missing hand joints, or a palm parallel to the bone)
    must not produce a zero axis: `_elbow_axis` answers None and `_secondary`
    falls back to the shoulder axis, as before.

WHAT THIS DOES NOT PROMISE
==========================
The fixture is an IDEAL rest — palm exactly forward, arm exactly along x — so
`bone x palm` lands exactly on the bend normal and the residual is 0.0 deg. A
real pack's palms are pronated: on MOB1 the true hinge sits 96.9 deg (left)
and 77.0 deg (right) from the palm rather than 90, so a fully bent arm keeps
a CONSTANT +7 / -13 deg of roll. Measured end to end on
MOB1_Stand_Relaxed_Idle_v2, converted against its own source:

    upper arm   +90.9 / +35.7  ->  +35.8 / -32.3      source  +31.8 / -23.0
    forearm     -60.7 / -57.6  ->   -3.8 / +10.1      source   -0.4 /  +0.3

which takes the shoulder's pinch from cos = 0.70 to 0.95 and the elbow's from
0.86 to 0.999. Closing the last few degrees needs twist bones, not a better
proxy axis.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner            # noqa: E402

TOL_DEG = 1e-4

# The joint positions of the fixtures, by hand (see the module docstring).
FIXTURES = {
    "straight": {
        "rfemur": [-10, 90, 0], "lfemur": [10, 90, 0],
        "lhumerus": [20, 150, 0], "lradius": [45, 150, 0], "lhand": [70, 150, 0],
        "LeftHandPinky1": [75, 150, -3], "LeftHandIndex1": [75, 150, 3],
        "rhumerus": [-20, 150, 0], "rradius": [-45, 150, 0], "rhand": [-70, 150, 0],
        "RightHandPinky1": [-75, 150, -3], "RightHandIndex1": [-75, 150, 3],
        "ltibia": [10, 45, 0], "lfoot": [10, 5, 0],
        "rtibia": [-10, 45, 0], "rfoot": [-10, 5, 0],
    },
    # elbows 90 deg forward: the forearm runs +Z from the elbow
    "bent90": {
        "lhand": [45, 150, 25], "LeftHandPinky1": [45, 147, 30],
        "LeftHandIndex1": [45, 153, 30],
        "rhand": [-45, 150, 25], "RightHandPinky1": [-45, 147, 30],
        "RightHandIndex1": [-45, 153, 30],
    },
    # elbows 19 deg — the middle of the 8..30 blend band
    "bent19": {},
    # knees bent backward; the shin leaves the knee downward AND backward
    "knees": {"lfoot": [10, 5, -36], "rfoot": [-10, 5, -36]},
    # a palm parallel to the arm: bone x palm degenerates
    "flatpalm": {
        "LeftHandPinky1": [72, 150, 0], "LeftHandIndex1": [78, 150, 0],
        "RightHandPinky1": [-72, 150, 0], "RightHandIndex1": [-78, 150, 0],
    },
}

PROBE = r'''
import json, math, sys
sys.path.insert(0, {scripts!r})
import fbx_clip
from mathutils import Vector

FIX = json.loads({fixtures!r})
TOL = 1e-9


def pose(name):
    P = {{k: Vector(v) for k, v in FIX["straight"].items()}}
    if name == "bent19":
        # 19 deg of elbow bend: the forearm leaves the elbow rotated 19 deg
        # towards +Z, length kept at 25 cm.
        a = math.radians(19.0)
        for side, sx in (("l", 1.0), ("r", -1.0)):
            el = P[side + "radius"]
            P[side + "hand"] = el + Vector((sx * 25.0 * math.cos(a), 0.0,
                                            25.0 * math.sin(a)))
    else:
        for k, v in FIX.get(name, {{}}).items():
            P[k] = Vector(v)
    return P


def sec(name, bone, direction=None):
    P = pose(name)
    child = fbx_clip.CHILD[bone]
    d = direction or (P[child] - P[bone])
    v = fbx_clip._secondary(bone, P, d)
    return list(v.normalized())


def ang(a, b):
    va, vb = Vector(a), Vector(b)
    return math.degrees(va.angle(vb, 0.0))


out = {{}}
for bone in ("lhumerus", "rhumerus"):
    out[bone] = {{k: sec(k, bone) for k in ("straight", "bent90", "bent19", "flatpalm")}}
for bone in ("lfemur", "rfemur"):
    out[bone] = {{k: sec(k, bone) for k in ("straight", "knees")}}
P0 = pose("straight")
out["palm"] = list((P0["LeftHandIndex1"] - P0["LeftHandPinky1"]).normalized())
out["shoulders"] = list((P0["lhumerus"] - P0["rhumerus"]).normalized())
out["bend_w"] = {{
    "straight": fbx_clip._bend_weight(Vector((1, 0, 0)), Vector((1, 0, 0))),
    "bent90": fbx_clip._bend_weight(Vector((1, 0, 0)), Vector((0, 0, 1))),
    "bent19": fbx_clip._bend_weight(
        Vector((1, 0, 0)),
        Vector((math.cos(math.radians(19.0)), 0.0, math.sin(math.radians(19.0))))),
}}
out["elbow_axis_parallel"] = fbx_clip._elbow_axis(Vector((1, 0, 0)), Vector((2, 0, 0)))
print("SMOKE_JSON " + json.dumps(out))
'''

failures = []


def check(label, got, want, tol=TOL_DEG):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.4f} (expected {want})")
    if not ok:
        failures.append(label)


def angle(a, b):
    import math
    dot = sum(x * y for x, y in zip(a, b))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def main() -> int:
    exe = runner.find_executable()
    if not exe:
        print("Blender not found — nothing was checked")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(PROBE.format(
            scripts=str(Path(__file__).resolve().parents[1] / "app/blender/scripts"),
            fixtures=json.dumps(FIXTURES)))
        res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(probe)],
                             capture_output=True, text=True, timeout=300)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("SMOKE_JSON ")), "")
    if not line:
        print(res.stdout[-2000:])
        print(res.stderr[-2000:])
        print("the probe produced no result")
        return 1
    d = json.loads(line[len("SMOKE_JSON "):])

    print("[0] the fixture is the T-pose the expectations were derived on")
    check("palm axis is +Z", angle(d["palm"], [0, 0, 1]), 0.0)
    check("shoulder axis is +X", angle(d["shoulders"], [1, 0, 0]), 0.0)
    check("bend weight, straight", d["bend_w"]["straight"], 0.0, 1e-12)
    # smoothstep at t = (19-8)/(30-8) = 0.5 is 0.5*0.5*(3-2*0.5) = 0.5 exactly;
    # the fixture reaches 19 deg through cos/sin, so the angle it measures back
    # carries ~1e-7 rad of float noise and the weight ~1e-8 of it.
    check("bend weight, 19 deg (band middle)", d["bend_w"]["bent19"], 0.5, 1e-6)
    check("bend weight, 90 deg", d["bend_w"]["bent90"], 1.0, 1e-12)

    print("\n[1] the straight arm's fallback is the HINGE, not the palm")
    check("left  = -Y", angle(d["lhumerus"]["straight"], [0, -1, 0]), 0.0)
    check("right = +Y", angle(d["rhumerus"]["straight"], [0, 1, 0]), 0.0)
    check("and 90 deg off the palm axis the old code used",
          angle(d["lhumerus"]["straight"], d["palm"]), 90.0)

    print("\n[2] a bent elbow reads the SAME axis — no roll enters R")
    for side, bone in (("left", "lhumerus"), ("right", "rhumerus")):
        check(f"{side}: 90 deg bend vs. straight",
              angle(d[bone]["bent90"], d[bone]["straight"]), 0.0)

    print("\n[3] and so does the middle of the blend band")
    for side, bone in (("left", "lhumerus"), ("right", "rhumerus")):
        check(f"{side}: 19 deg bend vs. straight",
              angle(d[bone]["bent19"], d[bone]["straight"]), 0.0)

    print("\n[4] the legs are unchanged — pelvis axis and knee normal agree")
    for side, bone in (("left", "lfemur"), ("right", "rfemur")):
        check(f"{side}: straight leg is the pelvis axis +X",
              angle(d[bone]["straight"], [1, 0, 0]), 0.0)
        check(f"{side}: bent knee vs. straight",
              angle(d[bone]["knees"], d[bone]["straight"]), 0.0)

    print("\n[5] a degenerate palm falls back instead of producing nothing")
    check("_elbow_axis of two parallel vectors is None",
          0.0 if d["elbow_axis_parallel"] is None else 1.0, 0.0)
    check("and the arm then takes the shoulder axis",
          angle(d["lhumerus"]["flatpalm"], d["shoulders"]), 0.0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
