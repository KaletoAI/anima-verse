"""The reference skeleton and the anatomical degrees of freedom of the DSL.

Armature space of ``shared/models/rig/reference.fbx`` — the space every clip
is written in: Y up, +Z the figure's FRONT, +X the figure's LEFT, centimetres.
Rest = the T-pose (arms along ±X, palms down), hips at 113.03 cm.

EVERY degree of freedom is 0 at rest, so an animation without values is the
rest pose exactly. A DOF is a rotation about an ARMATURE axis applied in the
PARENT's moved frame: D_b = D_parent · Rot_b, Rot_b the product of the bone's
axis rotations in ``ORDER`` (leftmost applied last). That is Blender's
``P_b = P_p · Rest_p⁻¹ · Rest_b · Basis_b`` with ``Basis_b = Rest_bᵀ · Rot_b ·
Rest_b`` — the compiler needs no bone rolls. The table below is the sign
of every DOF — per DOF: bone(s) · axis · factor -> what a POSITIVE value
does; the numeric proof of the convention is scripts/smoke_animstudio_compile.py
(stage 3).
``s`` = l/r, ``S`` = Left/Right, ``m`` = +1 left / -1 right (the right side
is the mirror image, so + means the same movement on both sides):

  body_pitch        Hips·x·+1           torso forward (-90 = on the back, head to -Z)
  body_roll         Hips·z·-1           tip over to the figure's left
  body_yaw          Hips·y·+1           turn to the left
  spine_flex/_tilt/_rot  Spine·Spine1·Spine2 x/z/y, 0.4/0.3/0.3 × (+1/-1/+1)
                                        bend forward / lean left / chest turns left
  neck_flex/_tilt/_rot   Neck·Head x/z/y, 0.5/0.5 × (+1/-1/+1)
                                        head down / tilt left / look left
  s_clav_raise      SShoulder·z·m       shrug the shoulder up
  s_clav_forward    SShoulder·y·-m      shoulder forward
  s_arm_elev        SArm·z·m            raise the arm (0 = T-pose, -90 = hanging)
  s_arm_azim        SArm·y·-m           swing the arm forward (90 = pointing front)
  s_arm_twist       SArm·x·-1           turn the palm forward
  s_elbow_flex      SForeArm·y·-m       bend the elbow (hand towards the front)
  s_wrist_flex      SHand·z·-m          bend the hand towards the palm
  s_wrist_dev       SHand·y·-m          bend the hand towards the front
  s_wrist_twist     SHand·x·-1          turn the palm forward (like arm_twist)
  s_fingers_curl    SHand{Index,Middle,Ring,Pinky}{1,2,3}·z·-m × (1, 1, 0.7)
                                        make a fist (90)
  s_thumb_curl      SHandThumb{1,2,3}·z·-m × (0.3, 0.6, 0.6)   curl the thumb (rough)
  s_hip_flex        SUpLeg·x·-1         thigh forward (90 = seated)
  s_hip_abduct      SUpLeg·z·m          leg outwards
  s_hip_rot         SUpLeg·y·m          toes turn outwards
  s_knee_flex       SLeg·x·+1           bend the knee (shin backwards; 90 = seated)
  s_ankle_flex      SFoot·x·-1          toes up
  s_toes_flex       SToeBase·x·-1       toes up (toe joint)
  hips_drop_cm      —                   the hips sink by that many cm

Rotation order per bone (``ORDER``): Arm "yzx", UpLeg "xzy", Hand "zyx",
Shoulder "yz", every other bone "yxz". Limits: ``LIMITS`` below.

Lying convention: on the back is ``body_pitch = -90`` — head towards -Z,
face up (``LIE_HEAD``).
"""
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from animstudio import STUDIO, StudioError

REST_FILE = STUDIO / "rig_rest.json"
LIE_HEAD = "-z"

#: (dof prefix, bone prefix, mirror factor m): m = +1 left, -1 right — the
#: right side is the left mirrored across the YZ plane.
SIDES = (("l", "Left", 1.0), ("r", "Right", -1.0))

#: The 22 bones cmu_clip.BONE_MAP drives, in its order (fingers excluded).
CORE_BONES = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
              "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
              "RightShoulder", "RightArm", "RightForeArm", "RightHand",
              "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
              "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"]
FINGER_BONES = [f"{side}Hand{finger}{n}" for side in ("Left", "Right")
                for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky") for n in (1, 2, 3)]


def axis_rot(axis: str, deg: float) -> np.ndarray:
    """Right-handed rotation about an armature axis (Blender's convention)."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    if axis == "y":
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _drives() -> Dict[str, List[Tuple[str, str, float]]]:
    d: Dict[str, List[Tuple[str, str, float]]] = {
        "body_pitch": [("Hips", "x", 1.0)],
        "body_roll": [("Hips", "z", -1.0)],
        "body_yaw": [("Hips", "y", 1.0)],
    }
    for dof, axis, sign in (("flex", "x", 1.0), ("tilt", "z", -1.0), ("rot", "y", 1.0)):
        d[f"spine_{dof}"] = [("Spine", axis, 0.4 * sign), ("Spine1", axis, 0.3 * sign),
                             ("Spine2", axis, 0.3 * sign)]
        d[f"neck_{dof}"] = [("Neck", axis, 0.5 * sign), ("Head", axis, 0.5 * sign)]
    for s, S, m in SIDES:
        d[f"{s}_clav_raise"] = [(f"{S}Shoulder", "z", m)]
        d[f"{s}_clav_forward"] = [(f"{S}Shoulder", "y", -m)]
        d[f"{s}_arm_elev"] = [(f"{S}Arm", "z", m)]
        d[f"{s}_arm_azim"] = [(f"{S}Arm", "y", -m)]
        d[f"{s}_arm_twist"] = [(f"{S}Arm", "x", -1.0)]
        d[f"{s}_elbow_flex"] = [(f"{S}ForeArm", "y", -m)]
        d[f"{s}_wrist_flex"] = [(f"{S}Hand", "z", -m)]
        d[f"{s}_wrist_dev"] = [(f"{S}Hand", "y", -m)]
        d[f"{s}_wrist_twist"] = [(f"{S}Hand", "x", -1.0)]
        d[f"{s}_fingers_curl"] = [(f"{S}Hand{f}{n}", "z", -m * k)
                                  for f in ("Index", "Middle", "Ring", "Pinky")
                                  for n, k in ((1, 1.0), (2, 1.0), (3, 0.7))]
        d[f"{s}_thumb_curl"] = [(f"{S}HandThumb{n}", "z", -m * k)
                                for n, k in ((1, 0.3), (2, 0.6), (3, 0.6))]
        d[f"{s}_hip_flex"] = [(f"{S}UpLeg", "x", -1.0)]
        d[f"{s}_hip_abduct"] = [(f"{S}UpLeg", "z", m)]
        d[f"{s}_hip_rot"] = [(f"{S}UpLeg", "y", m)]
        d[f"{s}_knee_flex"] = [(f"{S}Leg", "x", 1.0)]
        d[f"{s}_ankle_flex"] = [(f"{S}Foot", "x", -1.0)]
        d[f"{s}_toes_flex"] = [(f"{S}ToeBase", "x", -1.0)]
    return d


DRIVES = _drives()

ORDER: Dict[str, str] = {}
for _s, _S, _m in SIDES:
    ORDER[f"{_S}Arm"] = "yzx"
    ORDER[f"{_S}UpLeg"] = "xzy"
    ORDER[f"{_S}Hand"] = "zyx"
    ORDER[f"{_S}Shoulder"] = "yz"
DEFAULT_ORDER = "yxz"


def _limits() -> Dict[str, Tuple[float, float]]:
    """Generous on purpose: they catch a wrong sign or a typo, not a style."""
    lim = {"body_pitch": (-95.0, 95.0), "body_roll": (-95.0, 95.0),
           "body_yaw": (-180.0, 180.0), "hips_drop_cm": (0.0, 113.0),
           "spine_flex": (-30.0, 90.0), "spine_tilt": (-40.0, 40.0), "spine_rot": (-50.0, 50.0),
           "neck_flex": (-50.0, 70.0), "neck_tilt": (-40.0, 40.0), "neck_rot": (-80.0, 80.0)}
    for s, _S, _m in SIDES:
        lim.update({
            f"{s}_clav_raise": (-10.0, 30.0), f"{s}_clav_forward": (-20.0, 30.0),
            f"{s}_arm_elev": (-95.0, 170.0), f"{s}_arm_azim": (-60.0, 140.0),
            f"{s}_arm_twist": (-90.0, 90.0), f"{s}_elbow_flex": (0.0, 150.0),
            f"{s}_wrist_flex": (-80.0, 80.0), f"{s}_wrist_dev": (-30.0, 30.0),
            f"{s}_wrist_twist": (-80.0, 80.0), f"{s}_fingers_curl": (0.0, 100.0),
            f"{s}_thumb_curl": (0.0, 90.0), f"{s}_hip_flex": (-30.0, 130.0),
            f"{s}_hip_abduct": (-30.0, 60.0), f"{s}_hip_rot": (-45.0, 45.0),
            f"{s}_knee_flex": (0.0, 150.0), f"{s}_ankle_flex": (-50.0, 30.0),
            f"{s}_toes_flex": (-30.0, 60.0),
        })
    return lim


LIMITS = _limits()

#: A standing figure with its arms down — a starting point for ``base``.
RELAXED = {"l_arm_elev": -75.0, "r_arm_elev": -75.0,
           "l_elbow_flex": 10.0, "r_elbow_flex": 10.0,
           "l_fingers_curl": 15.0, "r_fingers_curl": 15.0}


class Rest:
    """The rest pose read from rig_rest.json, as numpy arrays."""

    def __init__(self, doc: dict):
        bones = doc["bones"]
        self.parent: Dict[str, Optional[str]] = {b: v["parent"] for b, v in bones.items()}
        self.head = {b: np.array(v["head"], float) for b, v in bones.items()}
        self.tail = {b: np.array(v["tail"], float) for b, v in bones.items()}
        self.rot = {b: np.array(v["rot"], float) for b, v in bones.items()}
        order: List[str] = []
        todo = [b for b, p in self.parent.items() if p is None]
        children: Dict[str, List[str]] = {}
        for b, p in self.parent.items():
            if p is not None:
                children.setdefault(p, []).append(b)
        while todo:
            b = todo.pop(0)
            order.append(b)
            todo.extend(sorted(children.get(b, [])))
        self.order = order
        self.children = children


def load_rest(path: Path = REST_FILE) -> Rest:
    if not path.is_file():
        raise StudioError(f"{path} missing - run scripts/make_rig_rest.py")
    return Rest(json.loads(path.read_text(encoding="utf-8")))
