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
    helpers. The root is not lost with it: ``_Source`` reads
    ``matrix_world``, so an animated parent is already folded into the hips.
    """
    m = dict(cmu_clip.BONE_MAP)
    for side in ("Left", "Right"):
        for mix in _FINGER_SRC.values():
            m[f"{side}Hand{mix}4"] = f"{side}Hand{mix}4"
    m["LeftToe_End"] = "ltoes_end"
    m["RightToe_End"] = "rtoes_end"
    return m


def _meshy_biped():
    """Meshy AI's rigged biped export — 24 nodes, no fingers.

    Twenty-one names are Mixamo's own (``Hips``, both leg chains down to
    ``ToeBase``, both arm chains including ``Shoulder`` and ``Hand``), so this
    map differs from :func:`_mixamo_noprefix` in exactly four places, and one
    of them is a trap:

    * THE SPINE IS NUMBERED THE OTHER WAY ROUND. Meshy counts DOWNWARDS from
      the chest — ``Spine`` is the top segment (it carries the shoulders and
      the neck), ``Spine01`` sits below it and ``Spine02`` is the child of the
      hips. Mixamo counts upwards, so ``Spine`` is its LOWEST. Read off the
      rest pose of a Meshy export, the three heads sit at 0.917 / 1.011 /
      1.107 m for Spine02 / Spine01 / Spine. Mapping ``Spine01`` to
      ``upperback`` because the digits line up would twist the torso; the
      mapping below follows the anatomy, not the name.
    * ``neck`` is lowercase.
    * No toe end sites. ``ltoes``/``rtoes`` therefore get no direction target
      and stay unanimated (``_frames_of`` skips a bone whose child is absent)
      — the toes keep the rig's rest, which is what a source without that
      joint can honestly deliver.
    * No fingers at all, exactly like a CMU take: the hands keep the model's
      own pose instead of being overwritten at rest.

    ``head_end`` and ``headfront`` are discarded by omission, like MotusMan's
    ``Root`` and weapon sockets — the head end site is reconstructed from the
    neck direction in ``_Source.sample`` regardless of what the file carries.
    """
    return {
        "Hips": "root",
        # anatomy, not digits — see the docstring
        "Spine02": "lowerback", "Spine01": "upperback", "Spine": "thorax",
        "neck": "lowerneck", "Head": "upperneck",
        "LeftShoulder": "lclavicle", "LeftArm": "lhumerus",
        "LeftForeArm": "lradius", "LeftHand": "lhand",
        "RightShoulder": "rclavicle", "RightArm": "rhumerus",
        "RightForeArm": "rradius", "RightHand": "rhand",
        "LeftUpLeg": "lfemur", "LeftLeg": "ltibia",
        "LeftFoot": "lfoot", "LeftToeBase": "ltoes",
        "RightUpLeg": "rfemur", "RightLeg": "rtibia",
        "RightFoot": "rfoot", "RightToeBase": "rtoes",
    }


def _autorig_pro():
    """A rig generated by Auto-Rig Pro — 56 nodes, fingers, no end sites.

    Recognisable by the ``.x``/``.l``/``.r`` side suffixes and the
    ``*_stretch`` limb names. The torso is Mixamo-shaped for once: three spine
    segments numbered UPWARDS from the hips (``spine_01`` is the lowest, and
    ``spine_03`` carries both clavicles and the neck), so the digits and the
    anatomy agree here — unlike :func:`_meshy_biped`.

    Two joints the rig does NOT have, and what that costs:

    * No finger end sites. The third phalanx (``c_*3``) therefore has no
      direction target and stays in the rig's rest, exactly like the toes of a
      Meshy export — ``_frames_of`` skips a bone whose child is absent. The
      first two phalanges carry the pose, which is the honest maximum for a
      source with three finger joints.
    * No toe end site. ``ltoes``/``rtoes`` stay unanimated for the same reason.

    Discarded by omission, like MotusMan's weapon sockets: the ``Root`` null
    above the hips (``_Source`` reads ``matrix_world``, so an animated
    parent is already folded into the hips anyway) and the ``Jaw_ref.x`` /
    ``eyes_ref.x`` / ``eye_ref.L`` / ``eye_ref.R`` control nodes, which drive a
    face the clip library does not carry.
    """
    m = {
        "root.x": "root",
        "spine_01.x": "lowerback", "spine_02.x": "upperback",
        "spine_03.x": "thorax",
        "neck.x": "lowerneck", "head.x": "upperneck",
        "shoulder.l": "lclavicle", "arm_stretch.l": "lhumerus",
        "forearm_stretch.l": "lradius", "hand.l": "lhand",
        "shoulder.r": "rclavicle", "arm_stretch.r": "rhumerus",
        "forearm_stretch.r": "rradius", "hand.r": "rhand",
        "thigh_stretch.l": "lfemur", "leg_stretch.l": "ltibia",
        "foot.l": "lfoot", "toes_01.l": "ltoes",
        "thigh_stretch.r": "rfemur", "leg_stretch.r": "rtibia",
        "foot.r": "rfoot", "toes_01.r": "rtoes",
    }
    for side, s in (("l", "Left"), ("r", "Right")):
        for src, mix in _FINGER_SRC.items():
            for n in (1, 2, 3):
                m[f"c_{src.lower()}{n}.{side}"] = f"{s}Hand{mix}{n}"
    return m


BONE_MAPS = {"unity-humanoid": _unity_humanoid,
             "mixamo-noprefix": _mixamo_noprefix,
             "meshy-biped": _meshy_biped,
             "autorig-pro": _autorig_pro}

# Signature node names per family — "auto" picks the first family whose
# signature is fully present.
# ``Spine02``/``Spine2`` is what keeps the two Mixamo-shaped families apart:
# the three tokens before it are common to both, and neither spelling ever
# appears in the other rig.
SIGNATURES = {"unity-humanoid": ("Hips", "Left_UpperLeg", "Left_UpperArm", "Chest"),
              "mixamo-noprefix": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine2"),
              "meshy-biped": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine02"),
              # The side suffixes and the "_stretch" limb names share no token
              # with any Mixamo-shaped rig, so this one cannot be confused with
              # the three above and its order among them does not matter.
              "autorig-pro": ("root.x", "spine_01.x", "arm_stretch.l",
                              "thigh_stretch.l")}

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
#
# THE FALLBACK HAS TO POINT WHERE THE BEND NORMAL POINTS, or the blend is not
# a blend but a 90 deg step. For the LEGS the two agree by luck: in a T-pose
# thigh × shin runs along the pelvis axis, so a knee crossing the band changes
# nothing. For the ARMS they did NOT — the raw palm axis (pinky → index) runs
# FORWARD while upper arm × forearm runs UP/DOWN, 96.9 deg (left) and 77.0 deg
# (right) apart on MOB1. The reference rig's elbow is straight (0.0 deg, w = 0)
# and so took the palm axis, while any bent source frame took the bend normal,
# and the difference landed in ``R`` as a ROLL of the upper arm that the
# forearm then undid: measured on MOB1_Stand_Relaxed_Idle_v2, upper arm
# +90.9/+35.7 deg and forearm -60.7/-57.6 deg against a source that holds
# +31.8/-23.0 and -0.4/+0.3. Invisible on a rigid skeleton — the hand lands
# within 1.0 deg either way — and ruinous on skin: linear blend skinning
# pinches a joint to cos(twist/2) of its radius, so a 100 deg elbow collapsed
# to 0.64 and a 111 deg shoulder to 0.57. ``_elbow_axis`` removes the step by
# deriving the fallback FROM the palm so that it lands on the bend normal.
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


def _elbow_axis(axis: Vector, palm: Vector) -> Vector:
    """The elbow's hinge direction, synthesised from the palm — a straight
    arm's stand-in for ``upper × forearm``.

    Bending the elbow swings the forearm in the plane spanned by the upper arm
    and the palm NORMAL, so the hinge is perpendicular to both the bone and the
    palm axis, which is exactly where ``upper × forearm`` points once there is
    a bend to measure. In the Mixamo rest (arms along ±X, palms down, palm axis
    forward) it gives ∓Y on the two sides, the same signs the bend normal takes
    there — so rest and pose read the same axis and the blend adds no roll.

    ``None`` when the two are parallel or missing; the caller falls back to the
    shoulder axis as before.
    """
    if axis is None or palm is None:
        return None
    if axis.length < 1e-9 or palm.length < 1e-9:
        return None
    out = axis.cross(palm)
    return out if out.length > 1e-6 else None


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
        axis = direction or up
        back = _elbow_axis(axis, palm_axis) or shoulders
        w = _bend_weight(up, fore)
        if w <= 0.0:
            return back
        return _blend_secondary(axis, up.cross(fore), back, w)
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


#: Weight above which a vertex counts as "on this bone" for the palm plane. A
#: knuckle vertex shared with a neighbour must not tilt the fit.
_PALM_WEIGHT_MIN = 0.5
#: Fewest vertices a hand has to contribute before its plane is believed.
_PALM_MIN_VERTS = 50
#: Percentile the hand's REACH along the palm axis is read at, instead of the
#: bare extremes: one stray vertex weighted to the hand must not decide a sign.
#: The verdict barely moves with it — the four hands measured give -0.146 /
#: -0.133 / -0.171 / -0.167 raw and -0.144 / -0.131 / -0.178 / -0.172 at 5 %.
_PALM_REACH_PCT = 0.05
#: Smallest thumb reach — how far the hand stands off the wrist on the one side
#: against the other, as a fraction of its full width along the palm axis —
#: that may decide the axis' SIGN. Measured 0.144 / 0.131 (MotusMan, hand and
#: fingers) and 0.178 / 0.172 (Meshy); a floor of 0.03 keeps a fourfold margin
#: and still refuses a hand the mesh cannot decide.
_PALM_SKEW_MIN = 0.03


def _pca_smallest(points) -> Vector:
    """The axis of SMALLEST spread of a point cloud — a flat slab's normal.

    Jacobi on the 3x3 covariance, written out rather than pulled in: the
    Blender side has mathutils and nothing else, and three dimensions do not
    justify a dependency.
    """
    n = len(points)
    c = [sum(p[i] for p in points) / n for i in range(3)]
    A = [[sum((p[i] - c[i]) * (p[j] - c[j]) for p in points) / n
          for j in range(3)] for i in range(3)]
    V = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(60):
        p_, q_, best = 0, 1, 0.0
        for i in range(3):
            for j in range(i + 1, 3):
                if abs(A[i][j]) > best:
                    best, p_, q_ = abs(A[i][j]), i, j
        if best < 1e-14:
            break
        th = 0.5 * math.atan2(2 * A[p_][q_], A[q_][q_] - A[p_][p_])
        cs, sn = math.cos(th), math.sin(th)
        for M in (A, V):
            for k in range(3):
                u, w = M[k][p_], M[k][q_]
                M[k][p_], M[k][q_] = cs * u - sn * w, sn * u + cs * w
        for k in range(3):
            u, w = A[p_][k], A[q_][k]
            A[p_][k], A[q_][k] = cs * u - sn * w, sn * u + cs * w
    lo = min(range(3), key=lambda i: A[i][i])
    return Vector((V[0][lo], V[1][lo], V[2][lo])).normalized()


def _hand_direction(bones, src_of: dict, inter: str, bone) -> Vector:
    """The hand's own axis, expressed in the hand bone's LOCAL rest frame.

    The middle-finger root when the rig has one, the bone's local Y otherwise
    — the same axis :func:`_synth_hand_targets` walks its synthetic finger root
    along, so measurement and use read the hand the same way.

    Local Y alone would not do. Blender's FBX importer orients a bone from the
    node's OWN axes, not from where its child lies, and that is not always the
    hand: MotusMan's imported hand bones point straight down while the hand
    points sideways (84.0 deg on the left, 96.0 on the right), so ``normal x Y``
    would be a cross product of two nearly parallel vectors there.
    """
    child = src_of.get(CHILD[inter])
    if child and child in bones:
        d = bone.matrix_local.to_3x3().inverted() @ (
            bones[child].matrix_local.translation - bone.matrix_local.translation)
        if d.length > 1e-6:
            return d.normalized()
    return Vector((0.0, 1.0, 0.0))


def _palm_axes(bone_map: dict) -> dict:
    """``{"lhand"/"rhand": palm axis in that hand's OWN rest frame}`` measured
    off the SKINNED HAND MESH — ``{}`` when the file carries none.

    WHY THIS EXISTS. A forearm's roll — and with it where the palm faces —
    comes from the palm axis, which :func:`_secondary` reads as "pinky knuckle
    to index knuckle". A rig without finger joints has neither, and the axis
    falls back to the SHOULDER LINE. Measured on a Meshy take of someone
    wiping a table, that fallback stands 69 deg away from the real palm axis,
    and the imported clip wiped with the hand on edge instead of flat.

    The hand's own bone axes are not a way out: they are not the palm's. On
    the target rig the knuckle line runs along the hand's local X (measured:
    -0.978, +0.210, +0.007 on the left), but a Meshy hand's axes sit about 38
    deg rotated about the bone, so reading local X as the palm axis would trade
    a 69 deg error for a 38 deg one.

    The palm itself is the only honest source, and it is right there in the
    rest file: a hand is a FLAT SLAB, so the axis of smallest spread of the
    vertices weighted to the hand IS the palm normal, and the palm axis is
    perpendicular to it and to the bone (:func:`_hand_direction`). Both come
    out in the hand's own rest frame, which is what makes the number reusable
    on the animation file — a ``_without_skin`` export has no mesh to measure.

    ONE SPACE, NOT TWO. The vertices arrive in Blender's WORLD space while the
    bone matrices are ARMATURE space, and the FBX importer keeps the two apart:
    the Y-up -> Z-up conversion (rot X 90 deg) and the unit scale sit on the
    ARMATURE OBJECT. The scale and the wrong-space ``head`` fall out of the fit
    — a covariance is centred, and a uniform scale does not turn an eigenvector
    — but the rotation does not. Measured on MotusMan, whose armature carries
    the full 90 deg, the palm normal came out 80.6 / 81.8 deg from the truth
    before ``arm.matrix_world.inverted()`` went in front of the vertices and
    10.2 / 10.0 deg after (and the axis with it: 107.6 / 102.5 deg off the real
    knuckle line before, 15.9 / 15.0 after). On the Meshy rig the importer left
    the conversion on the MESH instead and the armature is rotation-free, so the
    same code was right there all along — which is why the defect survived: the
    one rig the feature was written for could not show it.

    THE SIGN is the one thing the plane cannot say: a normal has two
    directions, and picking the wrong one turns the palm over. It is decided by
    the THUMB, the one asymmetry of a hand that no pose can move — the thumb
    hangs off the INDEX side and REACHES FURTHER from the wrist than the little
    finger's edge does, so the side the hand stands off further on is the index
    side. Measured as (near + far) / width at the 5th/95th percentile of the
    projection: -0.144 and -0.131 on MotusMan (8.0 cm against 6.0), -0.178 and
    -0.172 on the Meshy hand (8.7 against 6.1) — four hands, two rigs, the same
    verdict, and on MotusMan it is the verdict the real knuckle line gives.

    That REACH is read on the hand AND everything hanging off it, while the
    PLANE is fitted on the hand bone alone. The two clouds are one and the same
    on the rigs this exists for (a fingerless rig weights the whole hand to the
    one bone), and they have to differ on a rig with fingers: the palm alone is
    the only flat thing to fit a plane to, but it is also the one part of the
    hand the thumb has been cut out of, and it then decides NOTHING — the mean
    of MotusMan's palm-only cloud sits 0.033 to the PINKY side, i.e. wrong, and
    its reach 0.02 off centre. Add the digits back and both hands answer with
    the knuckle line. (An empty measure is the honest reading of a symmetric
    cloud; a wrong one is not, which is why the rule is the reach of the whole
    hand and not the mean of anything.)

    THE SHOULDER LINE, which used to decide this, cannot — it is not merely
    weak at rest but wrong by construction. Two hands are MIRROR images, so
    whatever component their palm axes have along the shoulder line they have
    with OPPOSITE signs, while the rule sent both to the same side: it was
    bound to turn exactly one of them over, and it did. On MotusMan's real
    knuckle lines the two axes dot the shoulder line at +0.274 and -0.274, and
    the rule flipped the right hand. (The old note read the two hands' 69.2 /
    68.7 deg as agreement and called it decided "with room to spare"; the flip
    point is 90 deg, not 111, so the margin was 21 deg — and the number was the
    fallback's own error, not a margin.)

    THE MIRROR IS THE CHECK. Both axes are carried back to armature space and
    the left one is mirrored through the sagittal plane (the shoulder line is
    its normal); the two must then point the same way, and do on both rigs
    measured (dot +1.000). If they do not, the mesh has decided nothing and the
    import stops: a forearm rolled 180 deg for a whole take is worse than a
    loud failure.
    """
    src_of = {inter: src for src, inter in bone_map.items()}
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms or not meshes:
        return {}
    arm = arms[0]
    bones = arm.data.bones
    lh, rh = src_of.get("lhumerus"), src_of.get("rhumerus")
    if not lh or not rh or lh not in bones or rh not in bones:
        return {}
    lateral = (bones[lh].matrix_local.translation
               - bones[rh].matrix_local.translation)
    if lateral.length < 1e-6:
        return {}
    lateral.normalize()
    to_arm = arm.matrix_world.inverted()
    out, in_arm, skews = {}, {}, {}
    for inter in ("lhand", "rhand"):
        name = src_of.get(inter)
        if not name or name not in bones:
            continue
        bone = bones[name]
        rest = bone.matrix_local.to_3x3()
        inv = rest.inverted()
        head = bone.matrix_local.translation
        digits = {name} | {c.name for c in bone.children_recursive}
        palm, whole = [], []
        for ob in meshes:
            group = ob.vertex_groups.get(name)
            if group is None:
                continue
            hand = {ob.vertex_groups[g].index for g in digits if g in ob.vertex_groups}
            to_bone = to_arm @ ob.matrix_world
            for v in ob.data.vertices:
                on_hand = sum(g.weight for g in v.groups if g.group in hand)
                if on_hand <= _PALM_WEIGHT_MIN:
                    continue
                p = inv @ (to_bone @ v.co - head)
                whole.append(p)
                if next((g.weight for g in v.groups
                         if g.group == group.index), 0.0) > _PALM_WEIGHT_MIN:
                    palm.append(p)
        if len(palm) < _PALM_MIN_VERTS:
            continue
        axis = _pca_smallest(palm).cross(_hand_direction(bones, src_of, inter, bone))
        if axis.length < 1e-6:
            continue
        axis.normalize()
        # The thumb reaches further off the wrist than the little finger, so
        # the side the WHOLE hand stands off further on is the index side.
        proj = sorted(p.dot(axis) for p in whole)
        near = proj[int(_PALM_REACH_PCT * (len(proj) - 1))]
        far = proj[len(proj) - 1 - int(_PALM_REACH_PCT * (len(proj) - 1))]
        skew = (far + near) / (far - near) if far - near > 1e-9 else 0.0
        if abs(skew) < _PALM_SKEW_MIN:
            continue
        axis = axis if skew > 0.0 else -axis
        out[inter], skews[inter] = axis, skew
        in_arm[inter] = (rest @ axis).normalized()
    if len(in_arm) == 2:
        left = in_arm["lhand"]
        mirrored = left - lateral * (2.0 * left.dot(lateral))
        if mirrored.dot(in_arm["rhand"]) <= 0.0:
            raise ValueError(
                "the two palm axes are not mirror images "
                f"({math.degrees(mirrored.angle(in_arm['rhand'], 0.0)):.1f} deg "
                "apart; against the shoulder line "
                f"{math.degrees(left.angle(lateral, 0.0)):.1f} and "
                f"{math.degrees(in_arm['rhand'].angle(lateral, 0.0)):.1f} deg, "
                f"thumb reach {skews['lhand']:+.3f} and {skews['rhand']:+.3f}) "
                "— the hand mesh cannot say which way the palm faces")
    return out


def _synth_hand_targets(P: dict, nodes: dict, palm: dict = None) -> None:
    """Give a FINGERLESS hand its direction target, from its own axis, IN PLACE.

    A bone is oriented here by where its CHILD lies, and the hand's child is
    the middle-finger root (``CHILD["lhand"]``). A source rig without fingers
    therefore drops out of :func:`_frames_of` at both hands: they get no frame,
    are never driven, and keep the TARGET rig's rest wrist for the whole take
    however the source's hand was held. Measured on a Meshy take, the hand sat
    at exactly the rig's rest — [0.2, 0.0, -0.1] deg against the forearm — in
    all 92 frames while every other bone carried the motion faithfully.

    The information is not missing, only the JOINT is: the hand node has a full
    orientation of its own. So the absent finger root is placed along the
    node's own bone axis, a third of the forearm ahead of the wrist — the same
    move :meth:`_Source.sample` already makes for ``head_end``, which has no node
    either. The length is arbitrary (a frame normalises its direction) and only
    kept plausible so a dump of ``P`` stays readable.

    A source WITH fingers never reaches this: its real joint is already in
    ``P`` and is left alone. Which is also why the assumption behind it — that
    the node's local Y runs along the bone, true for an armature bone and for
    every FBX joint written by a rigger — is only ever leaned on where there is
    nothing else at all.

    ``palm`` (:func:`_palm_axes`) adds the two KNUCKLES beside it, and they
    matter more than the middle one: ``_secondary`` reads the index and pinky
    roots as the palm axis, for the FOREARM as much as for the hand, and
    without them the forearm's roll is taken from the shoulder line. Only their
    difference is ever read, so they are placed symmetrically about the wrist
    and their distance is a readability choice, not a measurement.

    THE TWO ARE GATED SEPARATELY. The middle root is placed when the middle
    root is missing, the knuckles when the KNUCKLES are missing — one absence
    does not imply the other. A source that names a middle-finger root but no
    index and pinky (a one-bone-per-hand rig with a weapon socket under it, a
    map that carries only the middle chain) used to get its hand direction and
    keep the shoulder line for the roll, because the knuckles hung off the
    middle root's gate.
    """
    palm = palm or {}
    for hand, fore in (("lhand", "lradius"), ("rhand", "rradius")):
        if hand not in P or hand not in nodes:
            continue
        rot = nodes[hand].matrix_world.to_3x3()
        reach = (P[hand] - P[fore]).length / 3.0 if fore in P else 5.0
        reach = max(reach, 1.0)
        child = CHILD[hand]
        if child not in P:
            axis = _blender_to_clip(rot.col[1].to_3d())
            if axis.length > 1e-6:
                P[child] = P[hand] + axis.normalized() * reach
        side = "Left" if hand == "lhand" else "Right"
        index, pinky = f"{side}HandIndex1", f"{side}HandPinky1"
        # One real knuckle beside one invented one would be worse than neither.
        if index in P or pinky in P:
            continue
        across = palm.get(hand)
        if across is None:
            continue
        wide = _blender_to_clip(rot @ across)
        if wide.length < 1e-6:
            continue
        wide = wide.normalized() * (reach / 2.0)
        P[index] = P[hand] + wide
        P[pinky] = P[hand] - wide


class _Source:
    """ONE imported FBX, sampled take by take.

    Importing is what a pack file costs — measured on a 87 MB file with 121
    takes: 6.5 s and 850 MB for the import, 0.01 s to sample one 30-frame take
    off it. So the file is opened ONCE and every take the job needs is read
    from that one scene; opening per take would turn a scene of five roles
    into half a minute of re-reading the same bytes.

    Only one FBX can be open at a time (the importer resets the scene), so an
    instance is valid until the next one is created. :func:`run` respects that
    by grouping its entries per file.
    """

    def __init__(self, path: str, family: str, palm: dict = None):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
        scene_nodes = _scene_nodes()
        names = set(scene_nodes)
        if family == "auto":
            family = _detect_family(names)
        self.family = family
        self.path = path
        bone_map = BONE_MAPS[family]()
        self.nodes = {inter: scene_nodes[src]
                      for src, inter in bone_map.items() if src in names}
        # Measured HERE, while this file's mesh is still in the scene.
        self.palm = palm if palm is not None else _palm_axes(bone_map)
        missing = [c for c in ("root", "lfemur", "ltibia", "lfoot",
                               "lhumerus", "lradius", "lhand")
                   if c not in self.nodes]
        if missing:
            raise ValueError(
                f"{family}: essential bones missing in the file: {missing}")
        scene = bpy.context.scene
        self.fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)
        # File order — the n-th action is the n-th take of the file. Blender
        # creates one per animation stack as it reads them, and session_uid
        # counts up in creation order. The NAME cannot be used: it is
        # "<object>|<stack>|<layer>" capped at 63 characters, so a long take
        # name arrives here truncated.
        self.actions = sorted(bpy.data.actions, key=lambda a: a.session_uid)

    def select(self, take, take_count=0, take_name=""):
        """Makes take number ``take`` (an index into the file's stacks) the
        active animation. ``None`` keeps whatever the importer assigned, which
        is the first stack — right for a single-take file and for nothing else.

        ``take_count`` and ``take_name`` are the server's reading of the same
        file, checked against Blender's. They disagree when the file has more
        than one animated object (then the actions are stacks TIMES objects and
        the index means something else) — a mismatch that would otherwise
        surface as a clip with the wrong motion in it.
        """
        if take is None:
            return
        if take_count and len(self.actions) != take_count:
            raise ValueError(
                f"take {take}: the file lists {take_count} animations but "
                f"Blender made {len(self.actions)} actions — the index is not "
                "a take number here (several animated objects?)")
        if not 0 <= take < len(self.actions):
            raise ValueError(
                f"take {take} out of range: the file has {len(self.actions)}")
        action = self.actions[take]
        # A prefix long enough to catch a wrong index, short enough to survive
        # the 63-character cap in front of it.
        head = str(take_name or "")[:16]
        if head and head not in action.name:
            raise ValueError(
                f"take {take} is {action.name!r}, which does not carry "
                f"{head!r} — the file order and the listing disagree")
        for o in bpy.data.objects:
            if o.animation_data:
                o.animation_data.action = action

    def sample(self):
        """The active take as ``(fps, frame_range, positions_by_frame,
        rotations_by_frame)``, positions as ``{intermediate name: Vector(cm,
        Y up)}`` per frame."""
        scene = bpy.context.scene
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
            P = {inter: _blender_to_clip(o.matrix_world.translation)
                 for inter, o in self.nodes.items()}
            # head end site: no node — continue the neck direction by the
            # neck's own length
            if "upperneck" in P and "lowerneck" in P:
                P["head_end"] = P["upperneck"] + (P["upperneck"] - P["lowerneck"])
            _synth_hand_targets(P, self.nodes, self.palm)
            by_frame.append(P)
            rot_frame.append({inter: _rot_to_clip(o.matrix_world)
                              for inter, o in self.nodes.items()})
        return self.fps, (f0, f1), by_frame, rot_frame


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


def _rest_reference(by_frame, rot_frame, mix_frames: dict):
    """From the FIRST frame of a reference-pose take: per bone the rotation
    that carries the Mixamo rest onto the source's reference pose
    (``A_rest = F_src_rest · F_mix_restᵀ``) and the node's world rotation in
    that pose — what the delta mode needs.

    Takes the sampled frames rather than a path, because the reference pose is
    just as often a TAKE of the animation file itself as a file of its own —
    a pack ships its T-pose as one stack among the movements.
    """
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
    # Per role: which FILE, and which TAKE inside it. A single-take export
    # passes take None and behaves exactly as before; a pack file names the
    # index the server read off its stacks.
    picks = list(args.get("takes") or [])

    def _pick(i):
        """(take index, take count, take name) for entry i — all optional."""
        spec = picks[i] if i < len(picks) else None
        if not isinstance(spec, dict):
            return None, 0, ""
        take = spec.get("take")
        return (None if take is None else int(take),
                int(spec.get("take_count") or 0), str(spec.get("take_name") or ""))

    # A pair whose halves are two takes of ONE file arrives with src_a only.
    entries = ([("", inputs["src"])] if "src" in inputs
               else [("a", inputs["src_a"]),
                     ("b", inputs.get("src_b") or inputs["src_a"])])
    entries = [(role, path) + _pick(i) for i, (role, path) in enumerate(entries)]
    mix_pos, mix_frames = _mixamo_rest(args["rig"])

    # The reference pose is either its own input, or a TAKE of one of the
    # sources — a pack ships its T-pose as one stack among the movements, and
    # then there is no second file to hand over.
    rest_from = str(args.get("rest_from") or "")
    rest_path = inputs.get(rest_from) if rest_from else inputs.get("rest")
    rest_spec = args.get("rest_take") or {}
    rest_pick = (rest_spec.get("take"), int(rest_spec.get("take_count") or 0),
                 str(rest_spec.get("take_name") or ""))

    # One open per FILE, the rest file first: it is the one with the skinned
    # mesh, so the palm axes of a fingerless rig are measured there and handed
    # to the animation files, which carry no mesh of their own. A file that is
    # both the rest source and an animation source is opened once for both.
    order = ([rest_path] if rest_path else [])
    for _role, path, _t, _c, _n in entries:
        if path not in order:
            order.append(path)

    rest = None
    palm = None
    sampled = {}
    used = family
    for path in order:
        src = _Source(path, family, palm)
        used = src.family
        if path == rest_path and rest is None:
            src.select(rest_pick[0], rest_pick[1], rest_pick[2])
            _fps, _rng, r_by, r_rot = src.sample()
            rest = _rest_reference(r_by, r_rot, mix_frames)
            # ``palm`` is NEVER rebound from an animation source: without a
            # rest file it stays None and every file measures its own mesh.
            # Taking A's answer — {} for a mesh-less export, which reads as
            # "already measured" — would rob B of its measurement, and B is a
            # different body.
            palm = src.palm
        for role, p, take, count, name in entries:
            if p != path:
                continue
            src.select(take, count, name)
            sampled[role] = src.sample()

    takes = []
    src_fps = None
    off = [float(v) for v in (args.get("offset_b_m") or (0, 0, 0))]
    for role, _path, _t, _c, _n in entries:
        sfps, (f0, f1), by_frame, rot_frame = sampled[role]
        src_fps = src_fps or sfps
        if role == "b" and any(off):
            shift = Vector((off[0] * 100.0, off[1] * 100.0, off[2] * 100.0))
            by_frame = [{k: v + shift for k, v in P.items()} for P in by_frame]
        takes.append(_build_take(role, fps, sfps, by_frame, mix_pos, mix_frames, args,
                                 rot_frame, rest))
    args["source_fps"] = src_fps
    source = {"format": "fbx", "bone_map": used,
              "files": list(args.get("source_name")
                            or [Path(p).name for _r, p, _t, _c, _n in entries]),
              "takes": [t for _r, _p, t, _c, _n in entries],
              "fingers": any("LeftHandIndex1" in t.sk.bones for t in takes),
              "rotation_mode": "rest-delta" if rest else "positional",
              "offset_b_m": off,
              "rest_file": str(args.get("rest_name") or "")}
    return cmu_clip.run_takes(takes, args, fps, source)


if __name__ == "__main__":
    _common.main(run)
