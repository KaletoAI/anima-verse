"""Retargets a FOREIGN rig's FBX animation onto the Mixamo rig — clip files
the library can play, through the same pipeline as the CMU converter.

Invoked through ``app.blender.runner.run("fbx_clip", inputs=…, params=…)``:

    inputs   rig            the Mixamo skeleton to drive (library idle.fbx)
             src            the animation FBX (solo), or
             src_a, src_b   the two halves of a pair (same world space)
    params   kind, fps, start_s, end_s, anchor_s, in_place, loop_s — as in
             cmu_clip; plus
             bone_map       name of the skeleton family ("unity-humanoid";
                            "auto" detects it from the node names)
             source_name    free text for the sidecar (file names)

How it works — positions, not rotations
---------------------------------------
Files exported from Unity/UMotion (and many others) carry NO bind pose: the
skeleton is a hierarchy of plain transform nodes whose defaults equal the
first animation frame, so a rotation DELTA from rest — what the CMU path
uses — cannot be formed. What every file has is the world POSITION of every
joint per frame. So a bone's orientation is rebuilt from geometry:

    direction  = joint → child joint
    secondary  = an anatomical axis that is defined in every pose:
                 the pelvis axis (left hip − right hip) for legs and feet,
                 the shoulder axis for the spine, neck and clavicles, the
                 elbow/knee bend normal for the limbs when they are bent
                 (the hand's index−pinky axis / pelvis axis when straight),
                 the palm (index − pinky) for the hand, the palm normal for
                 the fingers.

``F = [direction, secondary ⟂, cross]`` is an orthonormal frame. The SAME
frame is built on the Mixamo rig's rest pose, and the rotation handed to the
shared pipeline is ``R = F_source(t) · F_mixamo_restᵀ`` — the rotation that
carries the Mixamo rest frame onto the source's current frame. In the CMU
pose space of ``cmu_clip`` that is exactly "world rotation away from a rest
that equals the Mixamo rest", so ``_solve`` applies it with an identity
alignment and everything after it (pair anchor, contact fit, leg ratio,
floor, loop cut, track shape, export) runs unchanged. Fingers come along
when the source has them.

Limits: a bone's roll about its own axis is whatever the secondary axis
says — the thigh's twist follows the pelvis, the forearm's the hand. Real
for a hand on a shoulder, approximate for a thigh rolled in isolation.

Units/axes: Blender imports the FBX into a Z-up world in metres (the root
node's 0.01 scale applied); positions are converted back to the clip space
(Y up, centimetres) before any frame is built.
"""
import json
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

# ---------------------------------------------------------------- bone maps
# Source node name → intermediate name (CMU names for the 22 core bones,
# Mixamo short names for the fingers — what cmu_clip.BONE_MAP expects).
_FINGER_SRC = {"Thumb": "Thumb", "Index": "Index", "Middle": "Middle",
               "Ring": "Ring", "Pinky": "Pinky"}


def _unity_humanoid():
    m = {
        "Hips": "root", "Spine": "lowerback", "Chest": "upperback", "UpperChest": "thorax",
        "Neck": "lowerneck", "Head": "upperneck",
        "Left_Shoulder": "lclavicle", "Left_UpperArm": "lhumerus",
        "Left_LowerArm": "lradius", "Left_Hand": "lhand",
        "Right_Shoulder": "rclavicle", "Right_UpperArm": "rhumerus",
        "Right_LowerArm": "rradius", "Right_Hand": "rhand",
        "Left_UpperLeg": "lfemur", "Left_LowerLeg": "ltibia",
        "Left_Foot": "lfoot", "Left_Toes": "ltoes",
        "Right_UpperLeg": "rfemur", "Right_LowerLeg": "rtibia",
        "Right_Foot": "rfoot", "Right_Toes": "rtoes",
        # end sites (direction targets only, never driven)
        "Left_ToesEnd": "ltoes_end", "Right_ToesEnd": "rtoes_end",
    }
    for side, s in (("Left", "Left"), ("Right", "Right")):
        for src, mix in _FINGER_SRC.items():
            for n, part in enumerate(("Proximal", "Intermediate", "Distal", "DistalEnd"), 1):
                m[f"{side}_{src}{part}"] = f"{s}Hand{mix}{n}"
    return m


BONE_MAPS = {"unity-humanoid": _unity_humanoid}

# Signature node names per family — "auto" picks the first family whose
# signature is fully present.
SIGNATURES = {"unity-humanoid": ("Hips", "Left_UpperLeg", "Left_UpperArm", "Chest")}

# Mixamo rig: intermediate name → rig bone (short) — the 22 core bones plus
# the end sites the direction targets need.
MIX_OF = {cmu: mix for mix, cmu in cmu_clip.BONE_MAP.items()}
MIX_OF.update({"ltoes_end": "LeftToe_End", "rtoes_end": "RightToe_End",
               "head_end": "HeadTop_End"})
for _side in ("Left", "Right"):
    for _f in _FINGER_SRC.values():
        MIX_OF[f"{_side}Hand{_f}4"] = f"{_side}Hand{_f}4"

# Direction target (child joint) per driven intermediate bone.
CHILD = {
    "root": "lowerback", "lowerback": "upperback", "upperback": "thorax",
    "thorax": "lowerneck", "lowerneck": "upperneck", "upperneck": "head_end",
    "lclavicle": "lhumerus", "lhumerus": "lradius", "lradius": "lhand", "lhand": "LeftHandMiddle1",
    "rclavicle": "rhumerus", "rhumerus": "rradius", "rradius": "rhand", "rhand": "RightHandMiddle1",
    "lfemur": "ltibia", "ltibia": "lfoot", "lfoot": "ltoes", "ltoes": "ltoes_end",
    "rfemur": "rtibia", "rtibia": "rfoot", "rfoot": "rtoes", "rtoes": "rtoes_end",
}
for _side in ("Left", "Right"):
    for _f in _FINGER_SRC.values():
        for _n in (1, 2, 3):
            CHILD[f"{_side}Hand{_f}{_n}"] = f"{_side}Hand{_f}{_n + 1}"

BEND_MIN_DEG = 12.0


def _frame(direction: Vector, secondary: Vector) -> Matrix:
    x = direction.normalized()
    y = secondary - x * secondary.dot(x)
    if y.length < 1e-6:
        y = Vector((0.0, 1.0, 0.0)) - x * x.y
        if y.length < 1e-6:
            y = Vector((1.0, 0.0, 0.0)) - x * x.x
    y.normalize()
    z = x.cross(y)
    return Matrix((x, y, z)).transposed()      # columns x, y, z


def _secondary(name: str, P: dict) -> Vector:
    """The anatomical secondary axis of a bone from joint positions P."""
    def v(a, b):
        return (P[b] - P[a]) if a in P and b in P else None
    pelvis = v("rfemur", "lfemur") or Vector((1.0, 0.0, 0.0))
    shoulders = v("rhumerus", "lhumerus") or pelvis
    side = "l" if name.startswith("l") or name.startswith("Left") else "r"
    hand = "lhand" if side == "l" else "rhand"
    idx, pky = (f"{'Left' if side == 'l' else 'Right'}Hand{f}1" for f in ("Index", "Pinky"))
    palm_axis = v(pky, idx)
    if name in ("root", "lowerback"):
        return pelvis
    if name in ("upperback", "thorax", "lowerneck", "upperneck", "lclavicle", "rclavicle"):
        return shoulders if name != "lclavicle" and name != "rclavicle" else (
            v("thorax", "lowerneck") or Vector((0.0, 1.0, 0.0)))
    if name in ("lhumerus", "rhumerus"):
        up = v(name, "lradius" if side == "l" else "rradius")
        fore = v("lradius" if side == "l" else "rradius", hand)
        if up and fore and up.angle(fore, 0.0) > BEND_MIN_DEG * 3.14159 / 180:
            return up.cross(fore)
        return palm_axis or shoulders
    if name in ("lradius", "rradius", "lhand", "rhand"):
        return palm_axis or shoulders
    if name.startswith("LeftHand") or name.startswith("RightHand"):
        hd = v(hand, CHILD[hand])
        if hd and palm_axis:
            return hd.cross(palm_axis)
        return palm_axis or shoulders
    if name in ("lfemur", "rfemur", "ltibia", "rtibia"):
        th = v("lfemur" if side == "l" else "rfemur", "ltibia" if side == "l" else "rtibia")
        sh = v("ltibia" if side == "l" else "rtibia", "lfoot" if side == "l" else "rfoot")
        if th and sh and th.angle(sh, 0.0) > BEND_MIN_DEG * 3.14159 / 180:
            return th.cross(sh)
        return pelvis
    return pelvis        # feet, toes


def _frames_of(P: dict) -> dict:
    """Orthonormal frame per driven bone whose child is known in P."""
    out = {}
    for name, child in CHILD.items():
        if name in P and child in P:
            d = P[child] - P[name]
            if d.length > 1e-6:
                out[name] = _frame(d, _secondary(name, P))
    return out


# ------------------------------------------------------------------ source

def _detect_family(names) -> str:
    for fam, sig in SIGNATURES.items():
        if all(n in names for n in sig):
            return fam
    raise ValueError("unknown skeleton — no bone map matches these node names: "
                     + ", ".join(sorted(names)[:20]))


def _blender_to_clip(v: Vector) -> Vector:
    """Blender world (Z up, metres) → clip space (Y up, centimetres)."""
    return Vector((v.x * 100.0, v.z * 100.0, -v.y * 100.0))


def _load_source(path: str, family: str):
    """Imports the FBX and returns ``(fps, frame_range, positions_by_frame)``
    with positions as ``{intermediate name: Vector(cm, Y up)}`` per frame,
    plus the family actually used."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
    names = {o.name for o in bpy.data.objects}
    if family == "auto":
        family = _detect_family(names)
    bone_map = BONE_MAPS[family]()
    nodes = {inter: bpy.data.objects[src] for src, inter in bone_map.items() if src in names}
    missing = [c for c in ("root", "lfemur", "ltibia", "lfoot", "lhumerus", "lradius", "lhand")
               if c not in nodes]
    if missing:
        raise ValueError(f"{family}: essential bones missing in the file: {missing}")
    scene = bpy.context.scene
    fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
    frames = set()
    for o in bpy.data.objects:
        if o.animation_data and o.animation_data.action:
            r = o.animation_data.action.frame_range
            frames.update((int(r[0]), int(r[1])))
    f0, f1 = (min(frames), max(frames)) if frames else (1, 1)
    by_frame = []
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        bpy.context.view_layer.update()
        P = {inter: _blender_to_clip(o.matrix_world.translation) for inter, o in nodes.items()}
        # head end site: no node — continue the neck direction by the
        # neck's own length
        if "upperneck" in P and "lowerneck" in P:
            P["head_end"] = P["upperneck"] + (P["upperneck"] - P["lowerneck"])
        by_frame.append(P)
    return fps, (f0, f1), by_frame, family


class _FakeBone:
    __slots__ = ("name", "direction", "length", "dof")

    def __init__(self, name, direction, length):
        self.name, self.direction, self.length, self.dof = name, direction, length, []


class _FakeSkeleton:
    """What ``cmu_clip`` reads off a take's skeleton: bones with a rest
    direction (the Mixamo rest direction, so the alignment is identity) and a
    length (the SOURCE segment length, cm), ``unit_cm`` 1."""

    def __init__(self):
        self.bones = {}
        self.unit_cm = 1.0


class _FbxTake:
    """The duck-typed take ``cmu_clip`` works on (see ``_Take`` there)."""

    def __init__(self, role, sk, poses):
        self.role, self.sk, self.poses = role, sk, poses

    def root_xz(self, i):
        p = self.poses[i].pos["root"]
        return (p[0], p[2])

    def lowest(self):
        return min(_cmu.lowest_point_cm(self.sk, p) for p in self.poses)


def _mixamo_rest(rig_path: str):
    """Joint positions (armature space, cm, Y up) and frames of the Mixamo
    rest pose, by intermediate name."""
    arm = cmu_clip._load_rig(rig_path)
    bones = arm.data.bones
    P = {}
    for inter, short in MIX_OF.items():
        b = bones.get(PREFIX + short)
        if b is not None:
            P[inter] = b.head_local.copy()
    if "upperneck" in P and "lowerneck" in P and "head_end" not in P:
        P["head_end"] = P["upperneck"] + (P["upperneck"] - P["lowerneck"])
    return P, _frames_of(P)


def _build_take(role, fps, src_fps, by_frame, mix_pos, mix_frames, args):
    start_s = float(args.get("start_s", 0) or 0)
    end_s = args.get("end_s")
    idx = _cmu.resample_indices(len(by_frame), src_fps, fps, start_s,
                                None if end_s is None else float(end_s))
    sk = _FakeSkeleton()
    first = by_frame[idx[0]] if idx else by_frame[0]
    for name, child in CHILD.items():
        if name in mix_frames and name in first and child in first:
            d = mix_pos[child] - mix_pos[name]
            sk.bones[name] = _FakeBone(name, tuple(d.normalized()),
                                       (first[child] - first[name]).length)
    # leg chain for the leg-length ratio (hips → thigh offset + thigh + shin)
    sk.bones["lhipjoint"] = _FakeBone("lhipjoint", (0, -1, 0),
                                      (first["lfemur"] - first["root"]).length)
    poses = []
    for i in idx:
        P = by_frame[i]
        fr = _frames_of(P)
        pose = _cmu.Pose()
        for name in sk.bones:
            if name in fr and name in mix_frames:
                R = fr[name] @ mix_frames[name].transposed()
                pose.rot[name] = [[R[r][c] for c in range(3)] for r in range(3)]
                pose.pos[name] = tuple(P[name])
        if "root" not in pose.rot:
            raise ValueError("hips frame undefined in a frame")
        # the contact fit looks for a "head" joint (CMU's skull bone)
        if "head_end" in P:
            pose.pos["head"] = tuple(P["head_end"])
        poses.append(pose)
    return _FbxTake(role, sk, poses)


def run(job):
    args = dict(job.get("params") or {})
    inputs = job.get("inputs") or {}
    args["rig"] = inputs["rig"]
    args["out_dir"] = job["out_dir"]
    fps = int(args.get("fps", 30))
    family = str(args.get("bone_map") or "auto")
    entries = ([("", inputs["src"])] if "src" in inputs
               else [("a", inputs["src_a"]), ("b", inputs["src_b"])])
    mix_pos, mix_frames = _mixamo_rest(args["rig"])
    takes = []
    src_fps = None
    used = family
    for role, path in entries:
        sfps, (f0, f1), by_frame, used = _load_source(path, family)
        src_fps = src_fps or sfps
        takes.append(_build_take(role, fps, sfps, by_frame, mix_pos, mix_frames, args))
    args["source_fps"] = src_fps
    source = {"format": "fbx", "bone_map": used,
              "files": list(args.get("source_name") or [Path(p).name for _r, p in entries]),
              "fingers": any("LeftHandIndex1" in t.sk.bones for t in takes)}
    return cmu_clip.run_takes(takes, args, fps, source)


if __name__ == "__main__":
    _common.main(run)
