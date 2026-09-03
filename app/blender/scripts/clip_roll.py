"""Moves the roll of a clip's FOREARMS onto the UPPER ARMS — the repair of
library clips the positional FBX retarget wrote before ``_elbow_axis``
(2026-09-04), whose sources are gone.

Invoked through ``app.blender.runner.run("clip_roll", inputs=…, params=…,
out_dir=…)``:

    inputs   rig            the T-pose reference skeleton the twist is
                            measured against (``shared/models/rig/reference.fbx``)
             src            the clip to repair — or ``src_0`` … ``src_n`` for
                            several in one Blender start (a library dry run)
             ref            OPTIONAL: a clip to compare the result against,
                            frame by frame and bone by bone — the CLI hands
                            the ORIGINAL here when it verifies a written file
    params   target_twist_deg   the forearm's roll against the upper arm that
                            is to remain, degrees (default 0.0) — one number
                            for both arms, or ``{"L": x, "R": y}`` per arm
                            (rolls about one axis add, so a target τ leaves
                            the upper arm with u + f − τ: the τ that makes
                            cos(shoulder/2) and cos(elbow/2) equal maximises
                            the smaller of the two, and the two arms of a
                            Unity pair need different ones — measured
                            resting-cowgir__b: L +46.5, R −70.5)
             dry_run        measure and report only, write nothing (default
                            False)
             fps            the library's frame rate (default 30)
             max_other_dev_deg  the world-orientation deviation any bone
                            OTHER than the two arm bones may show before /
                            after (default 0.05)
             max_pos_dev_cm the joint-position deviation any bone may show
                            (default 0.001). That is the IN-SCENE limit — the
                            strict check of the arithmetic, which measures
                            <= 0.0001 cm on the ten MOB1 clips. A caller that
                            compares a WRITTEN file against ``ref`` must allow
                            for Blender's float32 bone maths on the way
                            through the FBX: importing `mob1-walk` and
                            exporting it UNCHANGED already moves LeftFoot by
                            0.00122 cm, so the CLI passes 0.01 cm for that run
                            (0.1 mm on a 1.80 m figure).

The result's ``data["clips"][slot]`` carries per arm the roll before and
after, the angle moved (min/max/mean), and the verification numbers; a
verification limit that breaks fails the run (``ok`` False with the numbers
in the error) — no file is declared then.

Why this is a pure redistribution
---------------------------------
The positional retarget built the upper arm's rest frame on the palm axis and
its posed frame on the elbow's bend normal — 96.9 deg (left) / 77.0 deg
(right) apart on MOB1 — so the difference landed in the upper arm as a ROLL
about its own axis, and the forearm, whose rest and posed frames used the same
axis, was written correctly in the world and therefore rolled BACK against
the upper arm by the same amount. Measured on MOB1_Stand_Relaxed_Idle_v2
against its own source: upper arm +90.9/+35.7 deg, forearm -60.7/-57.6 deg,
where the source holds +31.8/-23.0 and -0.4/+0.3. Over all ten MOB1 clips the
forearm's roll against the upper arm is -51 … -114 deg, always the opposite
sign of the upper arm's, and the net roll of the forearm against the clavicle
matches the source.

So the world orientation of every bone but the upper arm is right, and the
fix is a roll of the upper arm about its OWN axis by the forearm's twist,
with the forearm's local rotation counter-rolled so its world orientation
stays put: ``P_arm' = Roll(axis, phi) · P_arm``, ``P_forearm' = P_forearm``.
A roll about the bone's own axis moves no joint (the elbow stays where it
is), so positions are untouched by construction; children of the forearm
hang off an unchanged forearm. Measured in memory before this script existed:
positions 0.0000 cm, every bone but the upper arms within 0.045 deg, the
upper arm re-rolled by up to 110.8 deg, `mob1-walk` shoulder pinch
cos(theta/2) 0.42 -> 0.97, elbow 0.57 -> 1.00; on `mob1-stand-relaxed-idle-v2`
the upper arm lands at +32.2/-22.9 deg — the source's own +31.8/-23.0.

The twist is the swing-twist decomposition of the CHANGE of the forearm's
rotation relative to the upper arm since the T-pose rest, twist about the
forearm's rest axis (the reference rig's, not the clip file's: a library clip
carries its first frame as node rest, so the file itself knows no T-pose).
On the Mixamo rest the elbow is straight (0.0 deg), so the forearm's rest
axis IS the upper arm's axis and one roll settles the twist exactly; for a
rest with a bent elbow the roll is iterated (secant) until the residual is
below 1e-6 deg.

Track shape and axes are ``cmu_clip``'s (``_export``): rotation curves for
every bone the clip already drives plus the hips translation, Y up, -Z
forward, the armature at 0.01 / +90 deg X — so the file goes back into the
library as it came out. The clip's animation is imported with ``anim_offset``
0 so the first key stays at t = 1/fps, as ``_bake`` writes it.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import cmu_clip                                               # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402

PREFIX = cmu_clip.PREFIX

# clavicle, upper arm, forearm, hand — the chain the twist is read on
ARMS = {"L": ("LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"),
        "R": ("RightShoulder", "RightArm", "RightForeArm", "RightHand")}

TWIST_EPS_DEG = 1e-6
MAX_ITER = 12


# ---------------------------------------------------------------- maths

def _rot(m: Matrix) -> Matrix:
    """The rotation part of a pose matrix, scale stripped."""
    return m.to_3x3().normalized()


def _wrap(deg: float) -> float:
    while deg > 180.0:
        deg -= 360.0
    while deg <= -180.0:
        deg += 360.0
    return deg


def _twist_deg(D: Matrix, axis: Vector) -> float:
    """Signed twist of rotation ``D`` about unit ``axis``, degrees in
    (-180, 180] — the twist of the swing·twist decomposition with the twist
    applied first, i.e. the projection of the quaternion onto the axis."""
    q = D.to_quaternion()
    p = q.x * axis.x + q.y * axis.y + q.z * axis.z
    return _wrap(math.degrees(2.0 * math.atan2(p, q.w)))


def _angle_deg(a: Matrix, b: Matrix) -> float:
    q = (_rot(a).inverted() @ _rot(b)).to_quaternion()
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, abs(q.w)))))


class _ArmFrames:
    """The rest-derived axes of one arm, all in armature space of the
    reference rig: the forearm's rest rotation relative to the upper arm and
    its axis in the upper arm's frame (the twist reference), the upper arm's
    own axis in its frame (the roll axis), and the same pair for the upper
    arm against the clavicle (reported, not repaired)."""

    def __init__(self, rest: dict, names):
        clav, arm, fore, hand = (PREFIX + n for n in names)
        C, A, F, H = (rest[n] for n in (clav, arm, fore, hand))
        C3, A3, F3 = _rot(C), _rot(A), _rot(F)
        hA, hF, hH = A.translation, F.translation, H.translation
        self.arm, self.fore = arm, fore
        self.rel_fore = A3.inverted() @ F3
        self.axis_fore_in_arm = (A3.inverted() @ (hH - hF)).normalized()
        self.axis_arm_in_arm = (A3.inverted() @ (hF - hA)).normalized()
        self.rel_arm = C3.inverted() @ A3
        self.axis_arm_in_clav = (C3.inverted() @ (hF - hA)).normalized()
        self.clav = clav

    def fore_twist(self, P_arm: Matrix, P_fore: Matrix) -> float:
        D = (_rot(P_arm).inverted() @ _rot(P_fore)) @ self.rel_fore.inverted()
        return _twist_deg(D, self.axis_fore_in_arm)

    def arm_twist(self, P_clav: Matrix, P_arm: Matrix) -> float:
        D = (_rot(P_clav).inverted() @ _rot(P_arm)) @ self.rel_arm.inverted()
        return _twist_deg(D, self.axis_arm_in_clav)

    def rolled(self, P_arm: Matrix, deg: float) -> Matrix:
        """``P_arm`` rolled by ``deg`` about its own posed axis; the joint
        stays where it is."""
        axis = _rot(P_arm) @ self.axis_arm_in_arm
        M = (Matrix.Rotation(math.radians(deg), 3, axis) @ _rot(P_arm)).to_4x4()
        M.translation = P_arm.translation
        return M


def _solve_roll(fr: _ArmFrames, P_arm: Matrix, P_fore: Matrix, target: float):
    """The roll of the upper arm that leaves the forearm's twist at
    ``target``: returns ``(deg, P_arm_new, residual_deg)``.

    With a straight rest elbow the forearm's rest axis is the upper arm's
    axis and one step is exact; otherwise the secant iteration closes the
    residual — the slope is -1 by construction (a roll of the upper arm
    about the shared axis subtracts from the forearm's twist one to one)."""
    deg = 0.0
    slope = -1.0
    prev = None
    for _ in range(MAX_ITER):
        P_new = fr.rolled(P_arm, deg)
        res = _wrap(fr.fore_twist(P_new, P_fore) - target)
        if abs(res) < TWIST_EPS_DEG:
            return deg, P_new, res
        if prev is not None and abs(prev[0] - deg) > 1e-12:
            s = (res - prev[1]) / (deg - prev[0])
            if abs(s) > 1e-6:
                slope = s
        prev = (deg, res)
        deg = deg - res / slope
    P_new = fr.rolled(P_arm, deg)
    return deg, P_new, _wrap(fr.fore_twist(P_new, P_fore) - target)


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


def _rest_of(arm) -> dict:
    return {b.name: b.matrix_local.copy() for b in arm.data.bones}


def _frames_of(arm):
    act = arm.animation_data.action if arm.animation_data else None
    if act is None:
        raise ValueError("the clip carries no action")
    f0, f1 = act.frame_range
    if abs(f0 - round(f0)) > 1e-6 or abs(f1 - round(f1)) > 1e-6:
        raise ValueError(f"keys are not on whole frames: {f0}..{f1}")
    return act, list(range(int(round(f0)), int(round(f1)) + 1))


def _sample(arm, frames) -> dict:
    """``{frame: {bone: pose matrix (armature space)}}`` for every frame."""
    scene = bpy.context.scene
    out = {}
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        out[f] = {pb.name: pb.matrix.copy() for pb in arm.pose.bones}
    return out


def _basis(P_parent, rest_parent, rest_b, P_b) -> Matrix:
    """The pose-bone basis that puts bone ``b`` at ``P_b`` under a parent
    at ``P_parent`` — ``_bake``'s formula."""
    return (P_parent @ rest_parent.inverted() @ rest_b).inverted() @ P_b


def _write_keys(arm, action, bone_name: str, values: dict):
    """``values``: {frame: Quaternion}; the bone's rotation curves get these
    keys (created if the clip did not drive the bone so far)."""
    path = f'pose.bones["{bone_name}"].rotation_quaternion'
    curves = []
    for i in range(4):
        fc = action.fcurves.find(path, index=i)
        if fc is None:
            fc = action.fcurves.new(data_path=path, index=i)
            fc.keyframe_points.add(len(values))
            for k, f in enumerate(sorted(values)):
                fc.keyframe_points[k].co = (float(f), 0.0)
        curves.append(fc)
    prev = None
    for f in sorted(values):
        q = values[f].copy()
        if prev is not None and q.dot(prev) < 0.0:
            q.negate()          # same rotation, continuous sign between keys
        prev = q
        for i, v in enumerate((q.w, q.x, q.y, q.z)):
            fc = curves[i]
            kp = next((k for k in fc.keyframe_points if abs(k.co[0] - f) < 1e-6), None)
            if kp is None:
                kp = fc.keyframe_points.insert(float(f), v, options={"FAST"})
            kp.co[1] = v
    for fc in curves:
        fc.update()
    arm.pose.bones[bone_name].rotation_mode = "QUATERNION"


def _stats(vals):
    if not vals:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "max_abs": 0.0, "mean_abs": 0.0}
    return {"min": round(min(vals), 3), "max": round(max(vals), 3),
            "mean": round(sum(vals) / len(vals), 3),
            "max_abs": round(max(abs(v) for v in vals), 3),
            "mean_abs": round(sum(abs(v) for v in vals) / len(vals), 3)}


def _deviation(P_a: dict, P_b: dict, frames, skip=()) -> dict:
    """Max world-orientation (deg) and position (cm) deviation per bone
    between two samplings, split into the skipped bones (the arm bones that
    are MEANT to move) and all others."""
    rot, pos = {}, {}
    for f in frames:
        A, B = P_a[f], P_b[f]
        for name, Ma in A.items():
            Mb = B.get(name)
            if Mb is None:
                continue
            rot[name] = max(rot.get(name, 0.0), _angle_deg(Ma, Mb))
            pos[name] = max(pos.get(name, 0.0), (Ma.translation - Mb.translation).length)
    others = {n: v for n, v in rot.items() if n not in skip}
    worst = max(others, key=others.get) if others else ""
    worst_pos = max(pos, key=pos.get) if pos else ""
    return {"max_other_rot_deg": round(max(others.values()), 4) if others else 0.0,
            "worst_other_bone": worst,
            "max_arm_rot_deg": round(max((rot[n] for n in skip if n in rot), default=0.0), 3),
            "max_pos_cm": round(max(pos.values()), 5) if pos else 0.0,
            "worst_pos_bone": worst_pos}


# ---------------------------------------------------------------- run

def _process(slot: str, src: str, rig_rest: dict, args: dict, ref_path):
    p = args.get("params") or {}
    fps = int(p.get("fps", 30) or 30)
    raw_target = p.get("target_twist_deg", 0.0)
    if isinstance(raw_target, dict):
        targets = {s_: float(raw_target.get(s_, 0.0) or 0.0) for s_ in ARMS}
    else:
        targets = {s_: float(raw_target or 0.0) for s_ in ARMS}
    dry = bool(p.get("dry_run", False))
    max_other = float(p.get("max_other_dev_deg", 0.05) or 0.05)
    max_pos = float(p.get("max_pos_dev_cm", 0.001) or 0.001)

    ref_frames = None
    if ref_path:
        ref_arm = _import_armature(ref_path, fps)
        _act, frames_r = _frames_of(ref_arm)
        ref_frames = _sample(ref_arm, frames_r)
        _remove(ref_arm)

    arm = _import_armature(src, fps)
    action, frames = _frames_of(arm)
    rest = _rest_of(arm)
    bones = arm.data.bones
    before = _sample(arm, frames)
    missing = [PREFIX + n for names in ARMS.values() for n in names
               if PREFIX + n not in bones]
    if missing or any(n not in rig_rest for n in (PREFIX + m for names in ARMS.values() for m in names)):
        raise ValueError(f"arm chain missing in clip or rig: {missing}")

    after = {f: dict(P) for f, P in before.items()}   # copies, arm bones replaced below
    arms_data = {}
    arm_bone_names = set()
    for side, names in ARMS.items():
        fr = _ArmFrames(rig_rest, names)
        target = targets[side]
        arm_bone_names.update((fr.arm, fr.fore))
        tw_before, tw_after, up_before, up_after, moved, resid = [], [], [], [], [], []
        new_arm_keys, new_fore_keys = {}, {}
        for f in frames:
            P = before[f]
            P_clav, P_arm, P_fore = P[fr.clav], P[fr.arm], P[fr.fore]
            tw_before.append(fr.fore_twist(P_arm, P_fore))
            up_before.append(fr.arm_twist(P_clav, P_arm))
            deg, P_arm_new, res = _solve_roll(fr, P_arm, P_fore, target)
            moved.append(deg)
            resid.append(abs(res))
            after[f][fr.arm] = P_arm_new
            tw_after.append(fr.fore_twist(P_arm_new, P_fore))
            up_after.append(fr.arm_twist(P_clav, P_arm_new))
            b_arm, b_fore = bones[fr.arm], bones[fr.fore]
            par = b_arm.parent.name
            new_arm_keys[f] = _rot(_basis(P[par], rest[par], rest[fr.arm], P_arm_new)).to_quaternion()
            new_fore_keys[f] = _rot(_basis(P_arm_new, rest[fr.arm], rest[fr.fore], P_fore)).to_quaternion()
        arms_data[side] = {
            "forearm_twist_before": _stats(tw_before),
            "forearm_twist_after": _stats(tw_after),
            "upper_twist_before": _stats(up_before),
            "upper_twist_after": _stats(up_after),
            "moved": _stats(moved),
            "target_twist_deg": target,
            # per-frame series (deg) — a caller can pick a balanced target
            # from them: rolls about one axis add, so with target τ the upper
            # arm ends at upper + forearm − τ
            "series": {"upper": [round(v, 2) for v in up_before],
                       "forearm": [round(v, 2) for v in tw_before]},
            "solve_residual_max_deg": round(max(resid), 6) if resid else 0.0,
        }
        if not dry:
            _write_keys(arm, action, fr.arm, new_arm_keys)
            _write_keys(arm, action, fr.fore, new_fore_keys)

    data = {"frames": len(frames), "fps": fps, "target_twist_deg": targets,
            "dry_run": dry, "arms": arms_data}
    reasons = []
    if not dry:
        # the scene re-evaluated from the written keys, against the sampling
        # before the edit: the intended change is the upper arms' roll only
        got = _sample(arm, frames)
        v = _deviation(before, got, frames, skip=arm_bone_names)
        planned = _deviation(after, got, frames)     # what was written vs what was solved
        v["max_rot_vs_solved_deg"] = planned["max_other_rot_deg"]
        data["verify"] = v
        if v["max_other_rot_deg"] > max_other:
            reasons.append(f"{v['worst_other_bone']} moved {v['max_other_rot_deg']} deg (limit {max_other})")
        if v["max_pos_cm"] > max_pos:
            reasons.append(f"{v['worst_pos_bone']} moved {v['max_pos_cm']} cm (limit {max_pos})")
        if planned["max_other_rot_deg"] > max_other:
            reasons.append(f"written keys deviate {planned['max_other_rot_deg']} deg from the solved pose")
    for side, d in arms_data.items():
        if d["solve_residual_max_deg"] > 1e-3:
            reasons.append(f"{side}: roll solve did not converge ({d['solve_residual_max_deg']} deg)")
    if ref_frames is not None:
        # the (repaired or, in a dry run, unchanged) clip against the given
        # reference clip — a written file verified against its original
        common = [f for f in frames if f in ref_frames]
        if len(common) != len(frames) or len(ref_frames) != len(frames):
            reasons.append(f"frame count differs from ref: {len(frames)} vs {len(ref_frames)}")
        src_frames = _sample(arm, frames) if not dry else before
        r = _deviation(ref_frames, src_frames, common, skip=arm_bone_names)
        data["vs_ref"] = r
        if r["max_other_rot_deg"] > max_other:
            reasons.append(f"vs ref: {r['worst_other_bone']} differs {r['max_other_rot_deg']} deg (limit {max_other})")
        if r["max_pos_cm"] > max_pos:
            reasons.append(f"vs ref: {r['worst_pos_bone']} differs {r['max_pos_cm']} cm (limit {max_pos})")
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
        raise ValueError("input 'rig' (the T-pose reference skeleton) is required")
    fps = int((args.get("params") or {}).get("fps", 30) or 30)
    _common.reset_scene()
    rig = _import_armature(inputs["rig"], fps, anim=False)
    rig_rest = _rest_of(rig)
    _remove(rig)
    slots = sorted(k for k in inputs if k == "src" or k.startswith("src_"))
    if not slots:
        raise ValueError("no 'src' input")
    clips, outputs, failed = {}, {}, []
    for slot in slots:
        data, out_path = _process(slot, inputs[slot], rig_rest, args, inputs.get("ref"))
        clips[slot] = data
        if out_path is not None:
            outputs[slot] = str(out_path)
        if not data["limits_ok"]:
            failed.append(f"{slot}: " + "; ".join(data["reasons"]))
    if failed:
        # Self-distrust: a broken limit fails the whole run and declares no
        # file, so nothing half-verified can be moved into a library.
        raise ValueError("verification failed — " + " | ".join(failed))
    return {"clips": clips}, outputs


if __name__ == "__main__":
    _common.main(run)
