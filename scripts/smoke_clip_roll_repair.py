#!/usr/bin/env python3
"""Numeric check of the ROLL REDISTRIBUTION of `app/blender/scripts/clip_roll.py`
— the repair that moves a clip's forearm roll onto the upper arm.

Usage:
    ./.venv/bin/python scripts/smoke_clip_roll_repair.py

Needs Blender (auto-discovered, or image_generation.blender_executable, same
as the other blender smokes). No server, no world DB, no clip library: the
fixture is a synthetic Mixamo-named armature built here, written through the
same FBX exporter the library uses, and every file lives in a temp directory.

WHAT IS BEING PINNED
====================
Until 2026-09-04 the positional FBX retarget rolled every MOB1 clip's upper
arm about its own axis by the angle between the palm axis and the elbow's
bend normal, and the forearm rolled back by the same amount (measured on
MOB1_Stand_Relaxed_Idle_v2: upper arm +90.9/+35.7 deg, forearm -60.7/-57.6
deg, source +31.8/-23.0 and -0.4/+0.3). The converter is fixed; the files are
not, and 9 of 10 sources are gone. `clip_roll.py` rolls the upper arm about
its OWN axis by the forearm's twist and counter-rolls the forearm's local
rotation, so that every world orientation but the upper arm's own roll stays
and no joint moves. Measured on the real `mob1-walk` through the script:
forearm -110.8/-89.9 -> 0.0 deg, upper arm 130.6/99.4 -> 27.0/-39.3 deg,
every other bone within 0.025 deg, joints within 0.001 cm.

THE FIXTURE, AND THE EXPECTATIONS DERIVED BY HAND
=================================================
A T-pose in centimetres (armature space, the object carrying the library's
0.01 / +90 deg X): both arms along +-X, palms irrelevant (the repair reads
joints, not palms):

    LeftShoulder (5,150,0)   LeftArm (20,150,0)   LeftForeArm (45,150,0)
    LeftHand (70,150,0)      LeftHandMiddle1 (80,150,0);  right = x -> -x

Every bone points along its own local Y (Blender's convention) with roll 0,
so the upper arm and the forearm share ONE rest rotation and the forearm's
rest axis in the upper arm's frame is the upper arm's own axis: the case of
the Mixamo reference rig (elbow bend 0.0 deg), where a single roll settles
the twist exactly.

Five frames, 30 fps. Per frame the upper arm gets a pure SWING (rotation
about its local Z, 0/10/20/30/40 deg — an axis perpendicular to the bone
carries no twist), the forearm gets a ROLL of 60 deg about its local Y and
THEN a 30 deg bend about local Z: basis = Rz(30) . Ry(60). The right side
mirrors with -60 deg of roll.

[1] THE TWIST READS BACK AS WRITTEN. The forearm's rotation relative to the
    upper arm, conjugated into the upper arm's frame, is Rz(30) . Ry(60)
    itself (equal rest rotations), and the swing-twist decomposition with the
    twist applied first about the bone axis Y yields T = Ry(60), S = Rz(30):
    forearm twist = +60.0 deg (left) / -60.0 deg (right) in EVERY frame, the
    upper arm's twist against the clavicle 0.0 (pure swing).

[2] IT MOVES ENTIRELY. moved = +60.0 / -60.0 (min = max = mean), the forearm
    twist after = 0.0, and the upper arm now carries it: +60.0 / -60.0
    against the clavicle.

[3] NOTHING ELSE MOVES. A roll about the upper arm's own axis keeps the elbow
    on that axis, the forearm's world orientation is restored by the counter
    roll, and the hand hangs off the forearm: every bone but the two upper
    arms within 0.05 deg (the script's own limit), every joint within 0.001
    cm, the upper arms re-rolled by exactly 60.0 deg.

[4] A SECOND RUN IS A NO-OP. On the repaired file the forearm twist is 0, so
    the angle moved is 0 (|moved| <= 1e-3 deg allowing the FBX round trip) and
    the upper arm keeps its +60 / -60.

[5] THE WRITTEN FILE, RE-IMPORTED, MATCHES THE ORIGINAL bone for bone: a dry
    run of the repaired file against the fixture as ``ref`` reports every
    other bone within 0.05 deg and joints within 0.001 cm — the same check
    the CLI runs before it replaces a library file.

[6] FRAMES SURVIVE THE ROUND TRIP: 5 keys in, 5 keys out, in every run.

[7] A PER-ARM TARGET SPLITS THE TWIST WHERE IT IS TOLD TO. Rolls about one
    axis add, so with ``target_twist_deg`` {"L": 20, "R": -20} on the fixture
    the forearm keeps 20 / -20, the angle moved is 60 - 20 = 40 (left) and
    -60 + 20 = -40 (right), and the upper arm carries 40 / -40. This is the
    knob the Unity pairs need, whose two arms carry different constant
    offsets (-22.3 / -174.3 deg).

Tolerances: 1e-3 deg on angles (the FBX round trip goes through Euler
degrees in double precision; observed ~1e-5) and the script's own limits for
the deviations.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner            # noqa: E402

TOL_DEG = 1e-3

PROBE = r'''
import json, math, sys
sys.path.insert(0, {scripts!r})
import bpy
import cmu_clip, clip_roll
from mathutils import Quaternion, Vector

TMP = {tmp!r}
PREFIX = cmu_clip.PREFIX
BONES = [  # name, head, tail, parent
    ("Hips", (0, 100, 0), (0, 110, 0), None),
    ("Spine", (0, 110, 0), (0, 125, 0), "Hips"),
    ("Spine1", (0, 125, 0), (0, 140, 0), "Spine"),
    ("Spine2", (0, 140, 0), (0, 150, 0), "Spine1"),
    ("Neck", (0, 150, 0), (0, 160, 0), "Spine2"),
    ("Head", (0, 160, 0), (0, 175, 0), "Neck"),
    ("LeftUpLeg", (10, 100, 0), (10, 55, 0), "Hips"),
    ("LeftLeg", (10, 55, 0), (10, 10, 0), "LeftUpLeg"),
    ("LeftFoot", (10, 10, 0), (10, 0, 12), "LeftLeg"),
]
for side, sx in (("Left", 1.0), ("Right", -1.0)):
    BONES += [
        (side + "Shoulder", (sx * 5, 150, 0), (sx * 20, 150, 0), "Spine2"),
        (side + "Arm", (sx * 20, 150, 0), (sx * 45, 150, 0), side + "Shoulder"),
        (side + "ForeArm", (sx * 45, 150, 0), (sx * 70, 150, 0), side + "Arm"),
        (side + "Hand", (sx * 70, 150, 0), (sx * 80, 150, 0), side + "ForeArm"),
        (side + "HandMiddle1", (sx * 80, 150, 0), (sx * 85, 150, 0), side + "Hand"),
    ]
BONES += [("RightUpLeg", (-10, 100, 0), (-10, 55, 0), "Hips"),
          ("RightLeg", (-10, 55, 0), (-10, 10, 0), "RightUpLeg"),
          ("RightFoot", (-10, 10, 0), (-10, 0, 12), "RightLeg")]


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", data)
    scene.collection.objects.link(arm)
    arm.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    arm.scale = (0.01, 0.01, 0.01)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in BONES:
        eb = data.edit_bones.new(PREFIX + name)
        eb.head, eb.tail, eb.roll = Vector(head), Vector(tail), 0.0
        if parent:
            eb.parent = data.edit_bones[PREFIX + parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return arm


def export(arm, path):
    cmu_clip.DRIVEN.clear()
    cmu_clip.DRIVEN.update(n for n, *_ in BONES)
    cmu_clip._export(arm, path)


# the rig: the same skeleton at rest, no animation
rig = build()
scene = bpy.context.scene
scene.frame_start = scene.frame_end = 1
export(rig, TMP + "/rig.fbx")

# the fixture: five frames, swing on the upper arm, roll + bend on the forearm
fix = build()
fix.animation_data_create()
fix.animation_data.action = bpy.data.actions.new("Armature|solo")
for f in range(1, 6):
    swing = math.radians(10.0 * (f - 1))
    for name, *_ in BONES:
        pb = fix.pose.bones[PREFIX + name]
        q = Quaternion()
        if name == "LeftArm":
            q = Quaternion((0, 0, 1), swing)
        elif name == "RightArm":
            q = Quaternion((0, 0, 1), -swing)
        elif name == "LeftForeArm":
            q = Quaternion((0, 0, 1), math.radians(30.0)) @ Quaternion((0, 1, 0), math.radians(60.0))
        elif name == "RightForeArm":
            q = Quaternion((0, 0, 1), math.radians(-30.0)) @ Quaternion((0, 1, 0), math.radians(-60.0))
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=f)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 5
export(fix, TMP + "/fixture.fbx")

out = {{}}
for d in ("run1", "run2"):
    (Path(TMP) / d).mkdir()
d1, o1 = clip_roll.run({{"inputs": {{"rig": TMP + "/rig.fbx", "src": TMP + "/fixture.fbx"}},
                        "params": {{"fps": 30}}, "out_dir": TMP + "/run1"}})
out["run1"] = d1["clips"]["src"]
d2, o2 = clip_roll.run({{"inputs": {{"rig": TMP + "/rig.fbx", "src": o1["src"]}},
                        "params": {{"fps": 30}}, "out_dir": TMP + "/run2"}})
out["run2"] = d2["clips"]["src"]
d3, _ = clip_roll.run({{"inputs": {{"rig": TMP + "/rig.fbx", "src": o1["src"], "ref": TMP + "/fixture.fbx"}},
                       "params": {{"fps": 30, "dry_run": True}}, "out_dir": TMP}})
out["verify"] = d3["clips"]["src"]
(Path(TMP) / "run4").mkdir()
d4, _ = clip_roll.run({{"inputs": {{"rig": TMP + "/rig.fbx", "src": TMP + "/fixture.fbx"}},
                       "params": {{"fps": 30, "target_twist_deg": {{"L": 20.0, "R": -20.0}}}}, "out_dir": TMP + "/run4"}})
out["split"] = d4["clips"]["src"]
print("SMOKE_JSON " + json.dumps(out))
'''

failures = []


def check(label, got, want, tol=TOL_DEG):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.5f} (expected {want} ± {tol})")
    if not ok:
        failures.append(label)


def check_le(label, got, limit):
    ok = got <= limit
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.5f} (limit {limit})")
    if not ok:
        failures.append(label)


def main() -> int:
    from pathlib import Path as _P
    exe = runner.find_executable()
    if not exe:
        print("Blender not found — nothing was checked")
        return 1
    with tempfile.TemporaryDirectory(prefix="smoke-clip-roll-") as tmp:
        probe = _P(tmp) / "probe.py"
        probe.write_text("from pathlib import Path\n" + PROBE.format(
            scripts=str(_P(__file__).resolve().parents[1] / "app/blender/scripts"), tmp=tmp))
        res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(probe)],
                             capture_output=True, text=True, timeout=600)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("SMOKE_JSON ")), "")
    if not line:
        print(res.stdout[-3000:])
        print(res.stderr[-3000:])
        print("the probe produced no result")
        return 1
    d = json.loads(line[len("SMOKE_JSON "):])
    r1, r2, v = d["run1"], d["run2"], d["verify"]

    print("[1] the fixture reads back as written: forearm twist +60 / -60, upper arm 0")
    for side, want in (("L", 60.0), ("R", -60.0)):
        a = r1["arms"][side]
        check(f"{side}: forearm twist min", a["forearm_twist_before"]["min"], want)
        check(f"{side}: forearm twist max", a["forearm_twist_before"]["max"], want)
        check(f"{side}: upper arm twist (pure swing) max|.|", a["upper_twist_before"]["max_abs"], 0.0)

    print("\n[2] the whole twist moves onto the upper arm")
    for side, want in (("L", 60.0), ("R", -60.0)):
        a = r1["arms"][side]
        check(f"{side}: moved min", a["moved"]["min"], want)
        check(f"{side}: moved max", a["moved"]["max"], want)
        check(f"{side}: moved mean", a["moved"]["mean"], want)
        check(f"{side}: forearm twist after max|.|", a["forearm_twist_after"]["max_abs"], 0.0)
        check(f"{side}: upper arm twist after min", a["upper_twist_after"]["min"], want)
        check(f"{side}: upper arm twist after max", a["upper_twist_after"]["max"], want)

    print("\n[3] nothing else moves")
    check_le("other bones' world orientation deviation", r1["verify"]["max_other_rot_deg"], 0.05)
    check_le("joint position deviation (cm)", r1["verify"]["max_pos_cm"], 0.001)
    check("the upper arms re-rolled by exactly 60", r1["verify"]["max_arm_rot_deg"], 60.0)
    check("the script's own verdict", 1.0 if r1["limits_ok"] else 0.0, 1.0, 0.0)

    print("\n[4] a second run is a no-op")
    for side, want in (("L", 60.0), ("R", -60.0)):
        a = r2["arms"][side]
        check(f"{side}: forearm twist before max|.|", a["forearm_twist_before"]["max_abs"], 0.0)
        check(f"{side}: moved max|.|", a["moved"]["max_abs"], 0.0)
        check(f"{side}: upper arm keeps its twist (min)", a["upper_twist_after"]["min"], want)
        check(f"{side}: upper arm keeps its twist (max)", a["upper_twist_after"]["max"], want)
    check_le("second run: other bones' deviation", r2["verify"]["max_other_rot_deg"], 0.05)
    check_le("second run: upper arms' deviation (no roll left to move)", r2["verify"]["max_arm_rot_deg"], TOL_DEG)

    print("\n[5] the written file, re-imported, matches the original bone for bone")
    check_le("vs original: other bones' world orientation", v["vs_ref"]["max_other_rot_deg"], 0.05)
    check_le("vs original: joint positions (cm)", v["vs_ref"]["max_pos_cm"], 0.001)
    check("vs original: upper arms differ by the 60 moved", v["vs_ref"]["max_arm_rot_deg"], 60.0)

    print("\n[7] a per-arm target splits the twist where it is told to")
    sp = d["split"]
    for side, keep, mv in (("L", 20.0, 40.0), ("R", -20.0, -40.0)):
        a = sp["arms"][side]
        check(f"{side}: forearm keeps the target (min)", a["forearm_twist_after"]["min"], keep)
        check(f"{side}: forearm keeps the target (max)", a["forearm_twist_after"]["max"], keep)
        check(f"{side}: moved mean", a["moved"]["mean"], mv)
        check(f"{side}: upper arm after (min)", a["upper_twist_after"]["min"], mv)
        check(f"{side}: upper arm after (max)", a["upper_twist_after"]["max"], mv)
    check_le("split run: other bones' deviation", sp["verify"]["max_other_rot_deg"], 0.05)

    print("\n[6] five keys in, five keys out")
    for label, r in (("run 1", r1), ("run 2", r2), ("verify", v)):
        check(f"{label}: frames", float(r["frames"]), 5.0, 0.0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
