#!/usr/bin/env python3
"""Real-Blender check of review 04#4: an alt half imported AFTER its pair was
oriented carries the same correction as the pair's half, and covers the
pair's import window.

Usage: ALSOFT_DRIVERS=null ./.venv/bin/python scripts/smoke_clip_alt_follow_blender.py
Skips (exit 0) when no usable Blender (>= 5.2) is installed. No server, no
world DB: the clip libraries, the inbox and the rig are TEMP paths
(ANIMATION_CLIPS_DIR, ANIMATION_CLIPS_LICENSED_DIR, ANIMATION_CLIPS_INBOX_DIR,
ANIMATION_RIG_FILE = a temp COPY of shared/models/rig/reference.fbx); the real
clips are never read or written. Pure-Python side: scripts/smoke_clip_alt_follow.py.

THE FIXTURE (built in Blender here): the reference rig with the ``mixamorig:``
prefix stripped (family ``mixamo-noprefix``), 60 frames at 30 fps, both
forearms and the left knee bent, the hips walking +0.3 cm/frame forward with
a small bob. ``a.fbx`` stands at x 0, ``b.fbx`` at x +80 cm, ``alt.fbx`` is
b's take again under another name — so the alt half must come out IDENTICAL
to the b half.

THE CHAIN, with the numbers it must produce:
1. ``import_fbx("duo", [a, b], start_s 0.5, end_s 1.5)``. The window in
   source frames (``_cmu.resample_indices``, 30 -> 30 fps, step 1):
   first = round(0.5 . 30) = 15, last = round(1.5 . 30) = 45 -> indices
   15..44 = 30 frames. The sidecar says frames 30 and records
   source.rebuild = {window_s [0.5, 1.5], yaw_deg 0, level_head false,
   orient_bakes []}. (The whole take would be 60 frames.)
2. The b half's root is measured (a dry ``clip_orient`` run) at frame 0 and
   at frame 20 -> P0, P20 (two different poses: the hips walk and bob).
3. ``orient_clip`` on the pair: tilt 10, height 5. Recorded:
   orient_bakes = [{yaw 0, tilt 10, roll 0, height 5}].
   The rule (clip_orient docstring), written out by hand: Rx(10) . p + (0, 5, 0),
   y' = y cos 10 - z sin 10 + 5, z' = y sin 10 + z cos 10, x' = x
   (cos 10 = 0.984808, sin 10 = 0.173648).
4. ``import_alt("duo", "b", "wave", alt.fbx)`` -> succeeds, replays 1 bake.
5. Measured on the written ``duo__b~wave.fbx``: 30 frames; its root at frame 0
   equals Rx(10) . P0 + (0, 5, 0) and at frame 20 Rx(10) . P20 +
   (0, 5, 0), each within 0.01 cm (float32 bone maths through FBX round
   trips); and it equals the oriented ``duo__b.fbx`` at both frames within
   the same limit. Unreplayed (the old code) the alt's root would sit at P0 /
   P20 — off by the 5 cm lift plus the tilt, three orders above the limit —
   and without the window it would have had 60 frames.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ALSOFT_DRIVERS", "null")

TMP = Path(tempfile.mkdtemp(prefix="clip-alt-follow-blender-"))
FREE, LICENSED, INBOX = TMP / "free", TMP / "licensed", TMP / "inbox"
RIG = TMP / "rig" / "reference.fbx"
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_RIG_FILE"] = str(RIG)

from app.blender import runner  # noqa: E402
from app.core import paths  # noqa: E402

TOL_CM = 0.01
FAIL = []

BUILD = r'''
import bpy, math, json
from mathutils import Matrix, Quaternion, Vector
RIG, OUT = {rig!r}, {out!r}

def build(name, dx):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.fbx_import(filepath=RIG, global_scale=1.0)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in list(bpy.data.objects):
        if o is not arm:
            bpy.data.objects.remove(o, do_unlink=True)
    arm.animation_data_clear()
    arm.name = arm.data.name = "Actor"
    for b in arm.data.bones:
        b.name = b.name.replace("mixamorig:", "")
    rest = {{b.name: b.matrix_local.copy() for b in arm.data.bones}}
    arm.animation_data_create()
    arm.animation_data.action = bpy.data.actions.new(name="take")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    bends = {{"LeftForeArm": ("Z", 40.0), "RightForeArm": ("Z", -40.0), "LeftLeg": ("X", 25.0)}}
    for f in range(1, 61):
        M = rest["Hips"].copy()
        M.translation = M.translation + Vector((dx, 2.0 * math.sin(f / 6.0), 0.3 * (f - 1)))
        hips = arm.pose.bones["Hips"]
        hips.matrix_basis = rest["Hips"].inverted() @ M
        hips.keyframe_insert("location", frame=f)
        hips.keyframe_insert("rotation_quaternion", frame=f)
        for bone, (axis, deg) in bends.items():
            pb = arm.pose.bones[bone]
            pb.rotation_quaternion = Matrix.Rotation(math.radians(deg + 0.2 * f), 3, axis).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=f)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start, scene.frame_end = 1, 60
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(filepath=OUT + "/" + name, use_selection=True,
                             object_types={{"ARMATURE"}}, add_leaf_bones=False, bake_anim=True,
                             bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
                             bake_anim_force_startend_keying=True, armature_nodetype="NULL",
                             axis_forward="-Z", axis_up="Y")

for name, dx in (("a.fbx", 0.0), ("b.fbx", 80.0), ("alt.fbx", 80.0)):
    build(name, dx)
print("SMOKE_JSON " + json.dumps({{"built": True}}))
'''


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def tilt_lift(p, tilt=10.0, h=5.0):
    """Rx(tilt) . p + (0, h, 0), by hand."""
    c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    return [p[0], p[1] * c - p[2] * s + h, p[1] * s + p[2] * c]


#: The second frame measured (``clip_orient``'s ``anchor_frame`` only names
#: which frame it reports besides frame 0 — a dry run moves nothing).
FRAME = 20


def measure(files, frame=FRAME):
    """Dry clip_orient run: per file the root at frame 0 and at ``frame``,
    and the frame count — nothing written."""
    inputs = {"rig": RIG}
    inputs.update({f"src_{i}": Path(f) for i, f in enumerate(files)})
    res = runner.run("clip_orient", inputs=inputs,
                     params={"dry_run": True, "anchor_frame": frame}, timeout_s=900)
    if not res["ok"]:
        raise RuntimeError(res.get("error"))
    clips = res["data"]["clips"]
    return [clips[f"src_{i}"] for i in range(len(files))]


def dist(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def main():
    if not runner.status().get("usable"):
        print("SKIP: no usable Blender")
        return 0
    RIG.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "shared/models/rig/reference.fbx", RIG)
    INBOX.mkdir(parents=True)
    paths.init(TMP / "world")
    from app.core import db
    db.init_schema()
    from app.core import animation_clips as clips
    from app.core import fbx_import

    script = TMP / "build.py"
    script.write_text(BUILD.format(rig=str(RIG), out=str(INBOX)), encoding="utf-8")
    res = subprocess.run([runner.find_executable(), "-b", "--factory-startup", "--python", str(script)],
                         capture_output=True, text=True, timeout=900)
    if "SMOKE_JSON " not in res.stdout:
        print(res.stdout[-3000:], res.stderr[-3000:])
        check("fixture built", False)
        return 1
    print(f"Blender {runner.version(runner.find_executable())} — fixture built")

    print("[1] import the pair with a window")
    fbx_import.import_fbx("duo", [{"name": "a.fbx", "take": None}, {"name": "b.fbx", "take": None}],
                          start_s=0.5, end_s=1.5, target="licensed")
    meta = json.loads((LICENSED / "duo.json").read_text(encoding="utf-8"))
    check("sidecar frames 30", meta.get("frames") == 30, str(meta.get("frames")))
    rebuild = (meta.get("source") or {}).get("rebuild")
    check("source.rebuild recorded", rebuild == {"window_s": [0.5, 1.5], "yaw_deg": 0.0,
                                                 "level_head": False, "orient_bakes": []}, str(rebuild))

    print("[2] measure the b half before the orient")
    (pre_b,) = measure([LICENSED / "duo__b.fbx"])
    p0, pa = pre_b["root_before"], pre_b["root_after_anchor"]
    print(f"     P0 = {p0}, P{FRAME} = {pa}")

    print("[3] orient the pair: tilt 10, height 5")
    clips.orient_clip("licensed", "duo__a.fbx", tilt_deg=10.0, height_cm=5.0, with_finales=False)
    meta = json.loads((LICENSED / "duo.json").read_text(encoding="utf-8"))
    bakes = meta["source"]["rebuild"]["orient_bakes"]
    check("the bake is recorded", bakes == [{"yaw_deg": 0.0, "tilt_deg": 10.0, "roll_deg": 0.0,
                                             "height_cm": 5.0}], str(bakes))

    print("[4] import the alt half")
    out = fbx_import.import_alt("duo", "b", "wave", {"name": "alt.fbx", "take": None}, target="licensed")
    check("one bake replayed", out.get("orient_bakes_replayed") == 1, str(out))

    print("[5] the alt carries the correction")
    alt, post_b = measure([LICENSED / "duo__b~wave.fbx", LICENSED / "duo__b.fbx"])
    check("the alt has 30 frames", alt["frames"] == 30, str(alt["frames"]))
    want0, wanta = tilt_lift(p0), tilt_lift(pa)
    print(f"     expected frame 0 {[round(v, 4) for v in want0]}, frame {FRAME} {[round(v, 4) for v in wanta]}")
    d = dist(alt["root_before"], want0)
    check(f"alt root frame 0 = Rx(10).P0 + 5 up (off {d:.5f} cm)", d <= TOL_CM, str(alt["root_before"]))
    d = dist(alt["root_after_anchor"], wanta)
    check(f"alt root frame {FRAME} = Rx(10).P{FRAME} + 5 up (off {d:.5f} cm)", d <= TOL_CM, str(alt["root_after_anchor"]))
    d = max(dist(alt["root_before"], post_b["root_before"]),
            dist(alt["root_after_anchor"], post_b["root_after_anchor"]))
    check(f"alt root = oriented b root (off {d:.5f} cm)", d <= TOL_CM)
    d = dist(alt["root_before"], p0)
    check(f"the unreplayed position P0 is far off ({d:.3f} cm > 1)", d > 1.0)
    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
