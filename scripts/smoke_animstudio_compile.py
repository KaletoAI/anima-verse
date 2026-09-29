#!/usr/bin/env python3
"""Smoke: the animation studio's DSL + forward kinematics, WITHOUT Blender.

Usage: ./.venv/bin/python scripts/smoke_animstudio_compile.py

Pure Python on animation-studio/rig_rest.json (the reference rig's rest,
armature space: Y up, +Z front, +X the figure's LEFT, cm). Every expectation
is derived by hand from the convention table in animstudio/rig.py.

Stage 1 - the rest file: 69 bones; Hips has no parent; the 22 CORE_BONES
  equal the non-finger keys of cmu_clip.BONE_MAP (read with ast, cmu_clip
  imports bpy); every DRIVES bone exists in the rest.
Stage 2 - rest in, rest out: an Animation with no values compiles to frames
  whose every D is the identity (max |D - I| < 1e-12) and whose every pos
  equals the rest head (< 1e-9 cm).
Stage 3 - one joint, by hand:
  l_arm_elev = 90: the left upper arm rest direction (1,0,0) turns about +Z
    by +90 deg -> (0,1,0); the ELBOW head sits at shoulder head + L*(0,1,0)
    with L = |head(LeftForeArm) - head(LeftArm)| (tolerance 1e-4 cm - the
    rest numbers are float32 from Blender).
  l_elbow_flex = 90 (arm at rest): forearm (1,0,0) -> Ry(-90) -> (0,0,1):
    hand head = elbow head + L2*(0,0,1).
  spine_flex = 50: Spine/Spine1/Spine2 turn 20/15/15 deg about +X, so their
    world rotations are Rx(20), Rx(35), Rx(50) and the Neck head sits at
    Spine + Rx(20)(h[Spine1]-h[Spine]) + Rx(35)(h[Spine2]-h[Spine1])
    + Rx(50)(h[Neck]-h[Spine2]); D[Spine2] == Rx(50).
  hips_drop_cm = 30: every pos.y is the rest y - 30.
  r_arm_elev = -90: right arm hangs: RightForeArm head = RightArm head +
    L*(0,-1,0) (mirror: factor -1 on z, Rz(+90)(-1,0,0) = (0,-1,0)).
Stage 4 - sampling:
  keys at 0 s (spine_flex 0) and 1 s (spine_flex 40, ease "linear"):
    t = 0.5 -> 20.0; with ease "in_out" (smoothstep, u = 0.5 -> 0.5) also
    20.0, at t = 0.25 in_out: u=0.25 -> 0.15625 -> 6.25.
  carry-forward: a key that does not name a DOF keeps the previous value.
  a DOF first named in a LATER key starts at its rest value 0: keys at 0 s
    (spine_flex 0) and 1 s (neck_rot 30, in_out): neck_rot at t = 0 / 0.5 /
    1 = 0 / 30*0.5 = 15 / 30. With loop=True and duration 2 s the closing key
    repeats key 0 (neck_rot 0 there), so neck_rot(2.0) = 0.0 and
    neck_rot(1.5) = 30 + (0 - 30)*0.5 = 15.0.
  loop=True, duration 2 s, keys at 0 (a=0) and 1 (a=40): the implicit closing
    key at 2 s repeats key 0, so t=1.5 linear-in_out -> 20.0 and the frame
    count is duration*fps + 1 = 61 with frame 60 == frame 0.
  Oscillator(spine_rot, amp 10, period 2.0): at t = 0.5 (a quarter period)
    +10.0; at t = 1.0 0.0 (|x| < 1e-9).
  validate: an unknown DOF, a key at t >= duration on a loop, an unknown
    ease, an unknown group and a loop whose duration*fps is no integer
    (1.01 s * 30 = 30.3 frames: the last frame misses the closing key) each
    raise StudioError.
"""
import ast
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "animation-studio"))

import numpy as np                                            # noqa: E402

from animstudio import StudioError                            # noqa: E402
from animstudio import rig                                    # noqa: E402
from animstudio.compile import compile_anim, fk, local_rotations  # noqa: E402
from animstudio.dsl import Animation, Catalog, Key, Oscillator, Pose, values_at, validate  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)


def near(a, b, tol):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float)))) <= tol


CAT = Catalog(key="smoke", group="stand", prompt="standing", synonyms=())
rest = rig.load_rest()

# -- stage 1
check(len(rest.head) == 69, f"rest has {len(rest.head)} bones")
check(rest.parent["Hips"] is None, "Hips has a parent")
tree = ast.parse((ROOT / "app/blender/scripts/cmu_clip.py").read_text())
bone_map = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BONE_MAP"
                and isinstance(n.value, ast.Dict))
check(list(bone_map) == rig.CORE_BONES, "CORE_BONES differ from cmu_clip.BONE_MAP")
for dof, drives in rig.DRIVES.items():
    for bone, _axis, _k in drives:
        check(bone in rest.head, f"{dof}: bone {bone} not in rest")
print("OK stage 1" if not FAIL else "FAIL stage 1")

# -- stage 2
anim = Animation(kind="smoke", duration_s=1.0, loop=False, catalog=CAT)
c = compile_anim(anim, rest)
for f in c.frames:
    for b, D in f.D.items():
        check(near(D, np.eye(3), 1e-12), f"rest D {b}")
    for b, p in f.pos.items():
        check(near(p, rest.head[b], 1e-9), f"rest pos {b}")
print("OK stage 2" if not FAIL else "FAIL stage 2")


# -- stage 3
def pose_of(values, drop=0.0):
    return fk(rest, local_rotations(values), drop)


D, P = pose_of({"l_arm_elev": 90})
L = np.linalg.norm(rest.head["LeftForeArm"] - rest.head["LeftArm"])
check(near(P["LeftForeArm"], P["LeftArm"] + L * np.array([0, 1, 0]), 1e-4), "l_arm_elev 90")
D, P = pose_of({"l_elbow_flex": 90})
L2 = np.linalg.norm(rest.head["LeftHand"] - rest.head["LeftForeArm"])
check(near(P["LeftHand"], P["LeftForeArm"] + L2 * np.array([0, 0, 1]), 1e-4), "l_elbow_flex 90")
D, P = pose_of({"spine_flex": 50})
h = rest.head
exp = (rig.axis_rot("x", 20) @ (h["Spine1"] - h["Spine"])
       + rig.axis_rot("x", 35) @ (h["Spine2"] - h["Spine1"])
       + rig.axis_rot("x", 50) @ (h["Neck"] - h["Spine2"]))
check(near(P["Neck"] - P["Spine"], exp, 1e-4), "spine_flex 50 split")
check(near(D["Spine2"], rig.axis_rot("x", 50), 1e-12), "spine_flex 50 D[Spine2]")
D, P = pose_of({}, drop=30.0)
check(all(abs(P[b][1] - (rest.head[b][1] - 30.0)) < 1e-9 for b in P), "hips_drop 30")
D, P = pose_of({"r_arm_elev": -90})
Lr = np.linalg.norm(rest.head["RightForeArm"] - rest.head["RightArm"])
check(near(P["RightForeArm"], P["RightArm"] + Lr * np.array([0, -1, 0]), 1e-4), "r_arm_elev -90")
print("OK stage 3" if not FAIL else "FAIL stage 3")

# -- stage 4
a = Animation(kind="s", duration_s=1.0, loop=False, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=0)), Key(1.0, Pose(spine_flex=40), ease="linear")])
check(abs(values_at(a, 0.5)["spine_flex"] - 20.0) < 1e-9, "linear 0.5")
a = Animation(kind="s", duration_s=1.0, loop=False, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=0)), Key(1.0, Pose(spine_flex=40))])
check(abs(values_at(a, 0.5)["spine_flex"] - 20.0) < 1e-9, "in_out 0.5")
check(abs(values_at(a, 0.25)["spine_flex"] - 6.25) < 1e-9, "in_out 0.25")
a = Animation(kind="s", duration_s=2.0, loop=False, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=10, neck_rot=5)), Key(1.0, Pose(spine_flex=30))])
check(abs(values_at(a, 1.5)["neck_rot"] - 5.0) < 1e-9, "carry-forward")
a = Animation(kind="s", duration_s=1.0, loop=False, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=0)), Key(1.0, Pose(neck_rot=30))])
got = [values_at(a, t).get("neck_rot") for t in (0.0, 0.5, 1.0)]
check(got[0] is not None and near(got, [0.0, 15.0, 30.0], 1e-9), f"late DOF ramps from 0: {got}")
a = Animation(kind="s", duration_s=2.0, loop=True, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=0)), Key(1.0, Pose(neck_rot=30))])
check(abs(values_at(a, 2.0)["neck_rot"]) < 1e-9, "late DOF loop closes to 0")
check(abs(values_at(a, 1.5)["neck_rot"] - 15.0) < 1e-9, "late DOF loop 1.5")
a = Animation(kind="s", duration_s=2.0, loop=True, catalog=CAT,
              keys=[Key(0.0, Pose(spine_flex=0)), Key(1.0, Pose(spine_flex=40))])
check(abs(values_at(a, 1.5)["spine_flex"] - 20.0) < 1e-9, "loop closing key")
c = compile_anim(a, rest)
check(len(c.frames) == 61, f"loop frames {len(c.frames)}")
check(near(c.frames[60].pos["LeftHand"], c.frames[0].pos["LeftHand"], 1e-9), "loop seam")
a = Animation(kind="s", duration_s=2.0, loop=True, catalog=CAT,
              layers=[Oscillator("spine_rot", amp=10.0, period_s=2.0)])
check(abs(values_at(a, 0.5)["spine_rot"] - 10.0) < 1e-9, "osc quarter")
check(abs(values_at(a, 1.0)["spine_rot"]) < 1e-9, "osc half")
for bad in (
    Animation(kind="s", duration_s=1.0, loop=False, catalog=CAT, keys=[Key(0.0, Pose(nope=1))]),
    Animation(kind="s", duration_s=1.0, loop=True, catalog=CAT, keys=[Key(1.0, Pose(spine_flex=1))]),
    Animation(kind="s", duration_s=1.0, loop=False, catalog=CAT, keys=[Key(0.0, Pose(), ease="wobble")]),
    Animation(kind="s", duration_s=1.0, loop=False,
              catalog=Catalog(key="x", group="sofa", prompt="p")),
    Animation(kind="s", duration_s=1.01, loop=True, catalog=CAT),
):
    try:
        validate(bad)
        FAIL.append("validate accepted a bad animation")
    except StudioError:
        pass
print("OK stage 4" if not FAIL else "FAIL stage 4")

print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_animstudio_compile")
sys.exit(1 if FAIL else 0)
