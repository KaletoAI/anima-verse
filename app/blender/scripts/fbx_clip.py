"""Retargets a FOREIGN rig's FBX animation onto the Mixamo rig — clip files
the library can play, through the same pipeline as the CMU converter.

Invoked through ``app.blender.runner.run("fbx_clip", inputs=…, params=…)``:

    inputs   rig            the Mixamo skeleton to drive
                            (``shared/models/rig/reference.fbx``)
             src            the animation FBX (solo), or
             src_a, src_b   the two halves of a pair (same world space)
             rest           OPTIONAL: an FBX of the SAME rig in a reference
                            pose (T/A-pose export). With it the bones take
                            their real node rotations relative to that pose
                            — twist included — instead of the positional
                            reconstruction below
    params   kind, fps, start_s, end_s, anchor_s, in_place, loop_s — as in
             cmu_clip; plus
             bone_map       name of the skeleton family ("unity-humanoid",
                            "mixamo-noprefix"; "auto" detects it from the
                            node names)
             offset_b_m     [side, up, forward] metres added to every joint of
                            half B before the pair is framed — for packs whose
                            halves are NOT in one world space ("set the male
                            model to -0.3 on the forward axis": [0, 0, -0.3])
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
                 (the hand's index−pinky axis / pelvis axis when straight,
                 and a ROLL BLEND of the two in between — see
                 ``BEND_BLEND_LO_DEG``),
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

With a REST file (same rig, any well-defined pose — a T- or A-pose export)
the roll comes from the data: for every bone ``R = R_node(t) · R_node_restᵀ ·
A_rest`` with ``A_rest = F_source_rest · F_mixamo_restᵀ`` — the node's own
world rotation away from the reference pose, carried onto the Mixamo rest
through the positional frames built on both REST poses (where the anatomical
secondary axes are exact). Positions still come from the animation, so
lengths, anchor and floor are unchanged.

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


def _mixamo_noprefix():
    """The Mixamo bone names WITHOUT the ``mixamorig:`` prefix — what
    MocapOnline's MotusMan rig (the MOB1/Mobility packs) exports, and what
    every FBX carries that was baked out of a Mixamo skeleton with the
    namespace stripped.

    ``cmu_clip.BONE_MAP`` already IS that table (Mixamo short name → CMU
    intermediate name, fingers 1–3 as themselves); only the fourth finger
    joint and the toe end sites are added here. Everything the rig carries on
    top is DISCARDED by omission — MotusMan's ``Root`` above the hips, the
    ``hand_l_wep``/``hand_r_wep`` weapon sockets and the ``Leaf*Roll1`` twist
    helpers. The root is not lost with it: ``_load_source`` reads
    ``matrix_world``, so an animated parent is already folded into the hips.
    """
    m = dict(cmu_clip.BONE_MAP)
    for side in ("Left", "Right"):
        for mix in _FINGER_SRC.values():
            m[f"{side}Hand{mix}4"] = f"{side}Hand{mix}4"
    m["LeftToe_End"] = "ltoes_end"
    m["RightToe_End"] = "rtoes_end"
    return m


BONE_MAPS = {"unity-humanoid": _unity_humanoid,
             "mixamo-noprefix": _mixamo_noprefix}

# Signature node names per family — "auto" picks the first family whose
# signature is fully present.
SIGNATURES = {"unity-humanoid": ("Hips", "Left_UpperLeg", "Left_UpperArm", "Chest"),
              "mixamo-noprefix": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine2")}

# Node-name prefixes that DISQUALIFY a family. The unprefixed Mixamo names are
# a substring of the prefixed ones, so a plain Mixamo export must never be read
# as "mixamo-noprefix" — it has its own path through the library.
EXCLUDE_PREFIXES = {"mixamo-noprefix": ("mixamorig:",)}

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

# A limb's bend normal (thigh × shin, upper arm × forearm) is the secondary
# axis that carries the real roll — but its DIRECTION is only as good as the
# bend is large: the cross product's length goes with sin(bend), so a nearly
# straight limb yields noise. Below the band the anatomical fallback (pelvis /
# palm axis) is used alone, above it the bend normal alone, and IN BETWEEN the
# two are blended as a roll around the bone (``_blend_secondary``).
#
# A hard switch here was the cause of per-frame leg twitching: a relaxed idle
# holds the knee near the switch point, so the bend angle wanders across it and
# the roll reference jumped between two axes that are 17-40 deg apart —
# measured 20.5 deg/frame (left) and 34.7 deg/frame (right) on
# MOB1_Stand_Relaxed_Idle_v2 while hips and spine stayed below 0.2 deg/frame.
#
# LO sits ABOVE the reference rig's own knee bend (5.92 deg) on purpose: the
# Mixamo rest frames must keep using the pelvis axis exactly as before, so the
# rest side of ``R = F_source(t) · F_mixamo_rest^T`` is unchanged.
BEND_BLEND_LO_DEG = 8.0
BEND_BLEND_HI_DEG = 30.0
_DEG = 3.141592653589793 / 180.0


def _bend_weight(upper: Vector, lower: Vector) -> float:
    """How far the bend normal is trusted, 0..1, smoothstepped over the band.

    ``upper``/``lower`` are the two limb segments (thigh/shin, upper arm/
    forearm); the angle between them IS the bend. Smoothstep (not a linear
    ramp) so the weight's own derivative is zero at both ends — the blend
    enters and leaves without a kink.
    """
    if upper is None or lower is None:
        return 0.0
    if upper.length < 1e-9 or lower.length < 1e-9:
        return 0.0
    deg = upper.angle(lower, 0.0) / _DEG
    t = (deg - BEND_BLEND_LO_DEG) / (BEND_BLEND_HI_DEG - BEND_BLEND_LO_DEG)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def _blend_secondary(direction: Vector, bend: Vector, fallback: Vector,
                     w: float) -> Vector:
    """Rotate ``fallback`` a fraction ``w`` of the way towards ``bend``.

    Both candidates are projected into the plane perpendicular to the bone, so
    the blend is a pure ROLL around the bone and never degenerates into a short
    vector the way a straight lerp between two nearly opposite axes would.
    """
    if w <= 0.0 or bend is None or bend.length < 1e-9:
        return fallback
    if w >= 1.0 or fallback is None or fallback.length < 1e-9:
        return bend
    x = direction.normalized()
    a = bend - x * bend.dot(x)
    b = fallback - x * fallback.dot(x)
    if a.length < 1e-6:
        return fallback
    if b.length < 1e-6:
        return bend
    a.normalize()
    b.normalize()
    ang = b.angle(a, 0.0)
    if ang < 1e-6:
        return a
    sign = 1.0 if x.dot(b.cross(a)) >= 0.0 else -1.0
    return Matrix.Rotation(sign * ang * w, 3, x) @ b


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


def _secondary(name: str, P: dict, direction: Vector = None) -> Vector:
    """The anatomical secondary axis of a bone from joint positions P.

    ``direction`` is the bone's own axis (joint → child); the limb bones need
    it to blend their two candidate axes as a roll around the bone.
    """
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
        back = palm_axis or shoulders
        w = _bend_weight(up, fore)
        if w <= 0.0:
            return back
        return _blend_secondary(direction or up, up.cross(fore), back, w)
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
        w = _bend_weight(th, sh)
        if w <= 0.0:
            return pelvis
        return _blend_secondary(direction or th, th.cross(sh), pelvis, w)
    return pelvis        # feet, toes


def _frames_of(P: dict) -> dict:
    """Orthonormal frame per driven bone whose child is known in P."""
    out = {}
    for name, child in CHILD.items():
        if name in P and child in P:
            d = P[child] - P[name]
            if d.length > 1e-6:
                out[name] = _frame(d, _secondary(name, P, d))
    return out


# ------------------------------------------------------------------ source

def _detect_family(names) -> str:
    for fam, sig in SIGNATURES.items():
        if not all(n in names for n in sig):
            continue
        if any(n.startswith(p) for p in EXCLUDE_PREFIXES.get(fam, ()) for n in names):
            continue
        return fam
    raise ValueError("unknown skeleton — no bone map matches these node names: "
                     + ", ".join(sorted(names)[:20]))


def _blender_to_clip(v: Vector) -> Vector:
    """Blender world (Z up, metres) → clip space (Y up, centimetres)."""
    return Vector((v.x * 100.0, v.z * 100.0, -v.y * 100.0))


_C = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))      # Blender Z-up → clip Y-up


def _rot_to_clip(m: Matrix) -> Matrix:
    """A Blender world rotation expressed in clip space — the SCALE of the
    world matrix (the root node's 0.01) is stripped: a scaled 'rotation'
    shrank every bone offset to nothing."""
    return _C @ m.to_3x3().normalized() @ _C.transposed()


class _BoneNode:
    """A pose bone dressed as an object — only ``matrix_world`` is ever read.

    A file WITHOUT a bind pose (Unity/UMotion) imports as a hierarchy of plain
    objects; a file WITH one (a skinned character export, e.g. MocapOnline's
    MotusMan) imports as ONE armature object whose joints are bones. Both are
    the same thing here: a named node with a world transform per frame.
    """
    __slots__ = ("_arm", "_pb")

    def __init__(self, arm, pb):
        self._arm, self._pb = arm, pb

    @property
    def matrix_world(self):
        return self._arm.matrix_world @ self._pb.matrix


def _scene_nodes() -> dict:
    """Every named node of the imported scene: the objects first, then the
    pose bones of every armature (an object name wins on a collision)."""
    out = {o.name: o for o in bpy.data.objects}
    for o in bpy.data.objects:
        if o.type == "ARMATURE":
            for pb in o.pose.bones:
                out.setdefault(pb.name, _BoneNode(o, pb))
    return out


def _load_source(path: str, family: str):
    """Imports the FBX and returns ``(fps, frame_range, positions_by_frame)``
    with positions as ``{intermediate name: Vector(cm, Y up)}`` per frame,
    plus the family actually used."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
    scene_nodes = _scene_nodes()
    names = set(scene_nodes)
    if family == "auto":
        family = _detect_family(names)
    bone_map = BONE_MAPS[family]()
    nodes = {inter: scene_nodes[src] for src, inter in bone_map.items() if src in names}
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
    rot_frame = []
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        bpy.context.view_layer.update()
        P = {inter: _blender_to_clip(o.matrix_world.translation) for inter, o in nodes.items()}
        # head end site: no node — continue the neck direction by the
        # neck's own length
        if "upperneck" in P and "lowerneck" in P:
            P["head_end"] = P["upperneck"] + (P["upperneck"] - P["lowerneck"])
        by_frame.append(P)
        rot_frame.append({inter: _rot_to_clip(o.matrix_world) for inter, o in nodes.items()})
    return fps, (f0, f1), by_frame, family, rot_frame


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


def _rest_reference(path: str, family: str, mix_frames: dict):
    """From a rest-pose FBX of the source rig: per bone the rotation that
    carries the Mixamo rest onto the source's reference pose
    (``A_rest = F_src_rest · F_mix_restᵀ``) and the node's world rotation in
    that pose — what the delta mode needs."""
    _fps, _rng, by_frame, _fam, rot_frame = _load_source(path, family)
    P, R = by_frame[0], rot_frame[0]
    fr = _frames_of(P)
    return {name: (fr[name] @ mix_frames[name].transposed(), R[name])
            for name in fr if name in mix_frames and name in R}


def _build_take(role, fps, src_fps, by_frame, mix_pos, mix_frames, args,
                rot_frame=None, rest=None):
    start_s = float(args.get("start_s", 0) or 0)
    end_s = args.get("end_s")
    idx = _cmu.resample_indices(len(by_frame), src_fps, fps, start_s,
                                None if end_s is None else float(end_s),
                                float(args.get("speed") or 1.0))
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
                if rest and name in rest and rot_frame is not None:
                    a_rest, r_rest = rest[name]
                    R = rot_frame[i][name] @ r_rest.transposed() @ a_rest
                else:
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
    rest = _rest_reference(inputs["rest"], family, mix_frames) if inputs.get("rest") else None
    takes = []
    src_fps = None
    used = family
    off = [float(v) for v in (args.get("offset_b_m") or (0, 0, 0))]
    for role, path in entries:
        sfps, (f0, f1), by_frame, used, rot_frame = _load_source(path, family)
        src_fps = src_fps or sfps
        if role == "b" and any(off):
            shift = Vector((off[0] * 100.0, off[1] * 100.0, off[2] * 100.0))
            by_frame = [{k: v + shift for k, v in P.items()} for P in by_frame]
        takes.append(_build_take(role, fps, sfps, by_frame, mix_pos, mix_frames, args,
                                 rot_frame, rest))
    args["source_fps"] = src_fps
    source = {"format": "fbx", "bone_map": used,
              "files": list(args.get("source_name") or [Path(p).name for _r, p in entries]),
              "fingers": any("LeftHandIndex1" in t.sk.bones for t in takes),
              "rotation_mode": "rest-delta" if rest else "positional",
              "offset_b_m": off,
              "rest_file": Path(inputs["rest"]).name if inputs.get("rest") else ""}
    return cmu_clip.run_takes(takes, args, fps, source)


if __name__ == "__main__":
    _common.main(run)
