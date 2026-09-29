"""Source -> frames: sampling, forward kinematics (and IK, Task 5), the
take document proc_clip reads.

Per frame and bone: D = world rotation relative to the rest (armature
space) and pos = the bone's head in cm — exactly what ``_cmu.Pose`` carries
(``rot`` = world rotation from rest, ``pos`` = start point).
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from animstudio import rig
from animstudio.dsl import Animation, validate, values_at


@dataclass
class Frame:
    D: Dict[str, np.ndarray]
    pos: Dict[str, np.ndarray]


@dataclass
class Compiled:
    frames: List[Frame]
    fps: int
    loop: bool
    fingers: bool
    extrema: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    ik_error_cm: Dict[str, float] = field(default_factory=dict)
    max_bend_deg: float = 0.0
    max_step_deg: float = 0.0
    loop_problems: List[str] = field(default_factory=list)
    lift_cm: float = 0.0


def local_rotations(values: Dict[str, float]) -> Dict[str, np.ndarray]:
    angles: Dict[str, Dict[str, float]] = {}
    for dof, value in values.items():
        for bone, axis, k in rig.DRIVES.get(dof, ()):
            per = angles.setdefault(bone, {})
            per[axis] = per.get(axis, 0.0) + k * value
    rots: Dict[str, np.ndarray] = {}
    for bone, per in angles.items():
        R = np.eye(3)
        for axis in rig.ORDER.get(bone, rig.DEFAULT_ORDER):
            if axis in per:
                R = R @ rig.axis_rot(axis, per[axis])
        rots[bone] = R
    return rots


def fk(rest: rig.Rest, rots: Dict[str, np.ndarray], hips_drop_cm: float
       ) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    D: Dict[str, np.ndarray] = {}
    pos: Dict[str, np.ndarray] = {}
    for b in rest.order:
        R = rots.get(b, np.eye(3))
        p = rest.parent[b]
        if p is None:
            D[b] = R
            pos[b] = rest.head[b] - np.array([0.0, hips_drop_cm, 0.0])
        else:
            D[b] = D[p] @ R
            pos[b] = pos[p] + D[p] @ (rest.head[b] - rest.head[p])
    return D, pos


def _angle_deg(A: np.ndarray, B: np.ndarray) -> float:
    tr = float(np.trace(A.T @ B))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0))))


def compile_anim(anim: Animation, rest: rig.Rest) -> Compiled:
    validate(anim)
    n = int(round(anim.duration_s * anim.fps))
    frames: List[Frame] = []
    extrema: Dict[str, Tuple[float, float]] = {}
    used = set()
    for i in range(n + 1):
        t = i / anim.fps
        values = values_at(anim, t)
        for dof, v in values.items():
            lo, hi = extrema.get(dof, (v, v))
            extrema[dof] = (min(lo, v), max(hi, v))
            if abs(v) > 1e-9:
                used.add(dof)
        rots = local_rotations(values)
        D, pos = fk(rest, rots, values.get("hips_drop_cm", 0.0))
        frames.append(Frame(D, pos))
    compiled = Compiled(frames=frames, fps=anim.fps, loop=anim.loop,
                        fingers=any(d.endswith(("_fingers_curl", "_thumb_curl")) for d in used),
                        extrema=extrema, lift_cm=anim.lift_cm)
    if anim.loop:
        from animstudio.dsl import _layers
        for o in _layers(anim):
            cycles = anim.duration_s / o.period_s
            if abs(cycles - round(cycles)) > 1e-6:
                compiled.loop_problems.append(
                    f"layer {o.dof}: period {o.period_s}s does not divide the "
                    f"duration {anim.duration_s}s - the seam jumps")
    compiled.max_step_deg = max(
        (_angle_deg(a.D[b], c.D[b]) for a, c in zip(frames, frames[1:]) for b in a.D),
        default=0.0)
    return compiled


def take_document(rest: rig.Rest, compiled: Compiled) -> dict:
    """What proc_clip reads (short Mixamo names; proc_clip maps them)."""
    names = rig.CORE_BONES + (rig.FINGER_BONES if compiled.fingers else [])
    bones = {}
    for b in names:
        v = rest.tail[b] - rest.head[b]
        length = float(np.linalg.norm(v))
        bones[b] = {"direction": (v / length).tolist(), "length": length}
    h = rest.head
    leg = (float(np.linalg.norm(h["LeftUpLeg"] - h["Hips"]))
           + float(np.linalg.norm(h["LeftLeg"] - h["LeftUpLeg"]))
           + float(np.linalg.norm(h["LeftFoot"] - h["LeftLeg"])))
    # The leg ratio run_takes scales the hips by must be exactly 1: the actor
    # IS the rig. act_leg = lhipjoint + lfemur + ltibia, so lhipjoint takes
    # the rest.
    lhip = leg - bones["LeftUpLeg"]["length"] - bones["LeftLeg"]["length"]
    return {
        "fps": compiled.fps,
        "loop": compiled.loop,
        "lift_cm": compiled.lift_cm,
        "bones": bones,
        "lhipjoint_cm": lhip,
        "frames": [{b: {"rot": f.D[b].tolist(), "pos": f.pos[b].tolist()} for b in names}
                   for f in compiled.frames],
    }
