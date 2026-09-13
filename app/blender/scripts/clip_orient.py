"""Turns and lifts a FINISHED library clip — the import's orientation dial,
applied after the fact to the file itself.

The import bakes ``yaw_deg`` into the take before it writes the FBX
(``cmu_clip._frame_takes`` / ``_apply_rigid``); afterwards there was no way
back, and the mocap sources of most library clips are long gone. This script
is that way back: it rewrites the clip in place, rigidly, with three angles
instead of one plus a height.

Invoked through ``app.blender.runner.run("clip_orient", inputs=…, params=…,
out_dir=…)``:

    inputs   rig            the reference skeleton (``shared/models/rig/
                            reference.fbx``); its ONE parentless bone is the
                            root a library clip has to carry, and the run
                            refuses a file that does not
             src            the clip to turn — or ``src_0`` … ``src_n`` for
                            several in one Blender start; the two halves of a
                            pair go in together so both get the SAME rotation
                            from the same numbers
    params   yaw_deg        turn about the vertical (default 0)
             tilt_deg       tip the standing figure head-forward/down (0)
             roll_deg       tip it to its right (0)
             height_cm      lift after the turn (0)
             fps            the library's frame rate (default 30)
             anchor_frame   0-based index into the take whose root position is
                            reported as well — a pair's sidecar anchor, so the
                            caller can re-measure ``anchor_xz_m`` from the
                            written file (default 0)
             dry_run        measure and report only, write nothing (False)
             max_pos_dev_cm joint-position deviation the rewritten take may
                            show against the arithmetic (default 0.01)
             max_rot_dev_deg  the same for the root's orientation (0.05)

THE ROTATION, WRITTEN OUT
=========================
Everything happens in ARMATURE SPACE, which for a library clip is the clip's
own frame: Y up, +Z forward, +X to the actor's left, centimetres, and the
floor at y = 0 (the import already shifted it there, ``floor_shift_cm``). The
origin of that frame is therefore the point on the FLOOR the clip is placed
by, and the rigid transform turns about exactly it::

    R = Ry(yaw) · Rx(tilt) · Rz(roll)          (roll first, then tilt, then yaw)
    p' = R · p + (0, height_cm, 0)
    rot' = R · rot

The three matrices are Blender's own ``Matrix.Rotation(a, 3, axis)``, so the
signs are the ones every other surface here already uses:

* **yaw** about +Y — ``x' = x cos a + z sin a``, ``z' = -x sin a + z cos a``:
  +Z turns onto +X at 90°. That is the import dial's rotation
  (``scripts/smoke_clip_yaw.py`` [2]) and three.js' ``rotation.y``, so dialling
  the angle in the preview and baking it here is the same turn.
* **tilt** about +X — the head of a standing figure, at (0, h, 0), lands at
  (0, h cos a, h sin a): it tips towards +Z, i.e. FORWARD and down. Positive
  tilt bows the figure.
* **roll** about +Z — the same head lands at (-h sin a, h cos a, 0): towards
  -X, and +X is the actor's LEFT, so positive roll tips it to its RIGHT.

Written as a Euler triple that is the order ``YXZ``, which is what the admin
preview turns the clip frame by while the angles are being dialled.

WHY ONLY THE ROOT BONE IS REWRITTEN
===================================
A pose bone's channel is its basis RELATIVE to its parent. Turning the whole
take is therefore one edit: the root's rotation and translation curves. Every
child hangs off the root by an unchanged local rotation and follows it exactly
— which is also why the run verifies the OTHER bones instead of assuming it:
if a child had moved by anything but ``R``, the take would not be rigid and
the file is not declared.

Track shape and axes are ``cmu_clip``'s (``_export``): rotation curves for
every bone the clip already drives plus the root translation, Y up, -Z
forward. The clip is imported with ``anim_offset`` 0 so the first key stays
where ``_bake`` wrote it.

The result's ``data["clips"][slot]`` carries the root position before and
after (frame 0 and the anchor frame), the lowest point of the figure after
the turn — a tilt can push a shoulder through the floor, and the caller
compensates with ``height_cm`` — and the verification numbers. A broken limit
fails the whole run (``ok`` False) and declares no file.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import _cmu                                                   # noqa: E402
import cmu_clip                                               # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402

PREFIX = cmu_clip.PREFIX

#: Joint-position deviation of the rewritten take against the arithmetic, cm.
#: The check runs IN THE SCENE (no FBX round trip), so it measures Blender's
#: float32 bone maths alone — micrometres on a 170 cm figure. 0.01 cm is
#: 0.1 mm, far below anything a renderer shows and far above the noise.
MAX_POS_DEV_CM = 0.01
#: The same for the root's orientation, degrees.
MAX_ROT_DEV_DEG = 0.05


# ---------------------------------------------------------------- maths

def _rot3(m: Matrix) -> Matrix:
    """The rotation part of a pose matrix, scale stripped."""
    return m.to_3x3().normalized()


def _angle_deg(a: Matrix, b: Matrix) -> float:
    q = (_rot3(a).inverted() @ _rot3(b)).to_quaternion()
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, abs(q.w)))))


def rotation(yaw_deg: float, tilt_deg: float, roll_deg: float) -> Matrix:
    """``Ry(yaw) · Rx(tilt) · Rz(roll)`` — roll applied first, then tilt,
    then yaw (Euler order ``YXZ``)."""
    return (Matrix.Rotation(math.radians(yaw_deg), 3, "Y")
            @ Matrix.Rotation(math.radians(tilt_deg), 3, "X")
            @ Matrix.Rotation(math.radians(roll_deg), 3, "Z"))


def _moved(M: Matrix, R4: Matrix, lift: Vector) -> Matrix:
    """One pose matrix under the rigid transform."""
    N = R4 @ M
    N.translation = N.translation + lift
    return N


class _FloorPose:
    """Duck-typed ``_cmu.Pose`` over a posed Blender armature: ``pos`` are the
    bone HEADS, ``end()`` the tails — all ``_cmu.lowest_point_cm`` reads."""

    def __init__(self, joints):
        self.pos = {n: tuple(h) for n, (h, _t) in joints.items()}
        self.rot = {n: None for n in joints}
        self._tails = {n: tuple(t) for n, (_h, t) in joints.items()}

    def end(self, _sk, name):
        return self._tails[name]


def _floor_min_cm(joints_per_frame) -> float:
    """Lowest point of the figure over the whole take, cm."""
    lows = [_cmu.lowest_point_cm(None, _FloorPose(j)) for j in joints_per_frame]
    return min(lows) if lows else 0.0


# ---------------------------------------------------------------- scene

def _import_armature(path: str, fps: int, anim: bool = True):
    """Imports an FBX into the current scene and returns the ONE armature it
    brought (other new objects are dropped)."""
    before = set(bpy.data.objects)
    bpy.context.scene.render.fps = fps
    bpy.ops.import_scene.fbx(filepath=str(path), global_scale=1.0,
                             use_anim=anim, anim_offset=0.0)
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError(f"{Path(path).name}: expected one armature, found {len(arms)}")
    for o in new:
        if o is not arms[0]:
            bpy.data.objects.remove(o, do_unlink=True)
    return arms[0]


def _remove(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.armatures.remove(data)


def _frames_of(arm):
    act = arm.animation_data.action if arm.animation_data else None
    if act is None:
        raise ValueError("the clip carries no action")
    f0, f1 = act.frame_range
    if abs(f0 - round(f0)) > 1e-6 or abs(f1 - round(f1)) > 1e-6:
        raise ValueError(f"keys are not on whole frames: {f0}..{f1}")
    return act, list(range(int(round(f0)), int(round(f1)) + 1))


def _sample(arm, frames):
    """Per frame the pose matrices in armature space AND every bone's posed
    head/tail — the first for the rigid check, the second for the floor."""
    scene = bpy.context.scene
    mats, joints = {}, {}
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        mats[f] = {pb.name: pb.matrix.copy() for pb in arm.pose.bones}
        joints[f] = {pb.name: (pb.head.copy(), pb.tail.copy())
                     for pb in arm.pose.bones}
    return mats, joints


def _write_track(action, path: str, values: dict, size: int) -> None:
    """``values``: {frame: tuple of ``size`` floats} onto the curves of one
    data path — created when the clip did not drive them so far."""
    curves, points = [], []
    order = sorted(values)
    for i in range(size):
        fc = action.fcurves.find(path, index=i)
        if fc is None:
            fc = action.fcurves.new(data_path=path, index=i)
            fc.keyframe_points.add(len(order))
            for k, f in enumerate(order):
                fc.keyframe_points[k].co = (float(f), 0.0)
        curves.append(fc)
        points.append({int(round(kp.co[0])): kp for kp in fc.keyframe_points})
    for f in order:
        for i, v in enumerate(values[f]):
            kp = points[i].get(int(f))
            if kp is None:
                kp = curves[i].keyframe_points.insert(float(f), v, options={"FAST"})
                points[i][int(f)] = kp
            kp.co[1] = v
    for fc in curves:
        fc.update()


def _write_root(arm, action, bone: str, mats: dict, rest: Matrix) -> None:
    """Puts the transformed root poses back as keys: the bone has no parent,
    so its basis is ``rest⁻¹ · M`` (``cmu_clip._bake``'s formula)."""
    quats, locs = {}, {}
    prev = None
    for f in sorted(mats):
        basis = rest.inverted() @ mats[f]
        q = basis.to_quaternion()
        if prev is not None and q.dot(prev) < 0.0:
            q.negate()          # same rotation, continuous sign between keys
        prev = q
        quats[f] = (q.w, q.x, q.y, q.z)
        t = basis.to_translation()
        locs[f] = (t.x, t.y, t.z)
    arm.pose.bones[bone].rotation_mode = "QUATERNION"
    _write_track(action, f'pose.bones["{bone}"].rotation_quaternion', quats, 4)
    _write_track(action, f'pose.bones["{bone}"].location', locs, 3)


# ---------------------------------------------------------------- run

def _process(slot: str, src: str, root_name: str, args: dict):
    p = args.get("params") or {}
    fps = int(p.get("fps", 30) or 30)
    yaw = float(p.get("yaw_deg", 0.0) or 0.0)
    tilt = float(p.get("tilt_deg", 0.0) or 0.0)
    roll = float(p.get("roll_deg", 0.0) or 0.0)
    height = float(p.get("height_cm", 0.0) or 0.0)
    dry = bool(p.get("dry_run", False))
    max_pos = float(p.get("max_pos_dev_cm", MAX_POS_DEV_CM) or MAX_POS_DEV_CM)
    max_rot = float(p.get("max_rot_dev_deg", MAX_ROT_DEV_DEG) or MAX_ROT_DEV_DEG)

    arm = _import_armature(src, fps)
    action, frames = _frames_of(arm)
    if root_name not in arm.data.bones:
        raise ValueError(f"{Path(src).name}: no bone '{root_name}' — not a library clip")
    rest = arm.data.bones[root_name].matrix_local.copy()
    before, before_joints = _sample(arm, frames)

    R3 = rotation(yaw, tilt, roll)
    R4 = R3.to_4x4()
    lift = Vector((0.0, height, 0.0))
    planned = {f: {n: _moved(M, R4, lift) for n, M in before[f].items()}
               for f in frames}

    def point(v):
        return R3 @ v + lift

    anchor = int(p.get("anchor_frame", 0) or 0)
    anchor = max(0, min(anchor, len(frames) - 1))
    reasons = []
    if dry:
        after = planned
        joints_after = [{n: (point(h), point(t))
                         for n, (h, t) in before_joints[f].items()} for f in frames]
    else:
        _write_root(arm, action, root_name, {f: planned[f][root_name] for f in frames}, rest)
        after, joints = _sample(arm, frames)
        joints_after = [joints[f] for f in frames]
        # The take must have moved RIGIDLY: every bone where the arithmetic
        # puts it, the root also turned the way it was told.
        worst_pos, worst_bone, worst_root, worst_rot = 0.0, "", 0.0, 0.0
        for f in frames:
            for name, want in planned[f].items():
                d = (after[f][name].translation - want.translation).length
                if d > worst_pos:
                    worst_pos, worst_bone = d, name
            worst_root = max(worst_root,
                             (after[f][root_name].translation
                              - planned[f][root_name].translation).length)
            worst_rot = max(worst_rot, _angle_deg(after[f][root_name],
                                                  planned[f][root_name]))
        if worst_root > max_pos:
            reasons.append(f"the root landed {worst_root:.5f} cm off the "
                           f"arithmetic (limit {max_pos})")
        if worst_pos > max_pos:
            reasons.append(f"{worst_bone} landed {worst_pos:.5f} cm off the "
                           f"arithmetic (limit {max_pos}) — the take did not move rigidly")
        if worst_rot > max_rot:
            reasons.append(f"the root's orientation is {worst_rot:.4f} deg off "
                           f"the arithmetic (limit {max_rot})")

    def xyz(M):
        return [round(v, 4) for v in M.translation]

    data = {
        "frames": len(frames), "fps": fps, "dry_run": dry,
        "yaw_deg": yaw, "tilt_deg": tilt, "roll_deg": roll, "height_cm": height,
        "root_bone": root_name,
        "root_before": xyz(before[frames[0]][root_name]),
        "root_after": xyz(after[frames[0]][root_name]),
        "anchor_frame": anchor,
        "root_after_anchor": xyz(after[frames[anchor]][root_name]),
        "floor_min_cm_after": round(_floor_min_cm(joints_after), 3),
        "floor_min_cm_before": round(_floor_min_cm(
            [before_joints[f] for f in frames]), 3),
    }
    if not dry:
        data["verify"] = {"max_pos_dev_cm": round(worst_pos, 6),
                          "worst_bone": worst_bone,
                          "max_root_pos_dev_cm": round(worst_root, 6),
                          "max_root_rot_dev_deg": round(worst_rot, 5)}
    data["limits_ok"] = not reasons
    data["reasons"] = reasons

    out_path = None
    if not dry and not reasons:
        driven = sorted({fc.data_path.split('"')[1][len(PREFIX):]
                         for fc in action.fcurves
                         if fc.data_path.endswith("rotation_quaternion")
                         and fc.data_path.split('"')[1].startswith(PREFIX)})
        cmu_clip.DRIVEN.clear()
        cmu_clip.DRIVEN.update(driven)
        scene = bpy.context.scene
        scene.render.fps = fps
        scene.frame_start, scene.frame_end = frames[0], frames[-1]
        out_path = Path(args["out_dir"]) / f"{slot}.fbx"
        cmu_clip._export(arm, out_path)
    _remove(arm)
    return data, out_path


def run(job):
    args = dict(job)
    inputs = args.get("inputs") or {}
    if "rig" not in inputs:
        raise ValueError("input 'rig' (the reference skeleton) is required")
    fps = int((args.get("params") or {}).get("fps", 30) or 30)
    _common.reset_scene()
    rig = _import_armature(inputs["rig"], fps, anim=False)
    roots = [b.name for b in rig.data.bones if b.parent is None]
    _remove(rig)
    if len(roots) != 1:
        raise ValueError(f"the reference rig has {len(roots)} root bones, expected one")
    slots = sorted(k for k in inputs if k == "src" or k.startswith("src_"))
    if not slots:
        raise ValueError("no 'src' input")
    clips, outputs, failed = {}, {}, []
    for slot in slots:
        data, out_path = _process(slot, inputs[slot], roots[0], args)
        clips[slot] = data
        if out_path is not None:
            outputs[slot] = str(out_path)
        if not data["limits_ok"]:
            failed.append(f"{slot}: " + "; ".join(data["reasons"]))
    if failed:
        # Self-distrust, as in clip_roll: a broken limit fails the WHOLE run
        # and declares no file, so a pair can never end up half turned.
        raise ValueError("verification failed — " + " | ".join(failed))
    return {"clips": clips}, outputs


if __name__ == "__main__":
    _common.main(run)
