"""Source -> frames: sampling, forward kinematics, the IK goals, the take
document proc_clip reads.

Per frame and bone: D = world rotation relative to the rest (armature
space) and pos = the bone's head in cm — exactly what ``_cmu.Pose`` carries
(``rot`` = world rotation from rest, ``pos`` = start point).
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from animstudio import rig
from animstudio.dsl import Animation, _layers, validate, values_at
import sys as _sys
from animstudio import REPO

_sys.path.insert(0, str(REPO / "app" / "blender" / "scripts"))
from _foot_plant import two_bone_ik   # noqa: E402  (stdlib-only by contract)
_sys.path.pop(0)

FADE_S = 0.15


def _qmat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def _qslerp_identity(q, w: float):
    """slerp((1,0,0,0), q, w) — the fade of an IK correction."""
    qw = max(-1.0, min(1.0, q[0]))
    if qw < 0:
        q = tuple(-c for c in q)
        qw = -qw
    ang = math.acos(qw)
    if ang < 1e-9:
        return (1.0, 0.0, 0.0, 0.0)
    s0 = math.sin((1 - w) * ang) / math.sin(ang)
    s1 = math.sin(w * ang) / math.sin(ang)
    return (s0 + s1 * q[0], s1 * q[1], s1 * q[2], s1 * q[3])


def _subtree(rest, bone):
    out, todo = [], [bone]
    while todo:
        b = todo.pop(0)
        out.append(b)
        todo.extend(rest.children.get(b, []))
    return out


def _repose(rest, D, pos, top):
    """Recompute the heads below ``top`` from the (changed) rotations."""
    for b in _subtree(rest, top)[1:]:
        p = rest.parent[b]
        pos[b] = pos[p] + D[p] @ (rest.head[b] - rest.head[p])


def _chain_ik(rest, D, pos, upper, lower, end, target, pole_point, weight, keep_end):
    qu, ql = two_bone_ik(tuple(pos[upper]), tuple(pos[lower]), tuple(pos[end]),
                         tuple(target), tuple(pole_point))
    Qu = _qmat(_qslerp_identity(qu, weight))
    Ql = _qmat(_qslerp_identity(ql, weight))
    kept = {b: D[b].copy() for b in _subtree(rest, end)} if keep_end else {}
    for b in _subtree(rest, upper):
        D[b] = (Ql @ Qu @ D[b]) if b in _subtree(rest, lower) else (Qu @ D[b])
    D.update(kept)
    _repose(rest, D, pos, upper)


def _weight(span, t, duration):
    if span is None:
        return 1.0
    a, b = span
    if t < a or t > b:
        return 0.0
    w = 1.0
    if a > 0:
        w = min(w, (t - a) / FADE_S)
    if b < duration:
        w = min(w, (b - t) / FADE_S)
    return max(0.0, min(1.0, w))


def _bend(pos, a, b, c):
    u, v = pos[b] - pos[a], pos[c] - pos[b]
    return math.degrees(math.acos(max(-1.0, min(1.0, float(
        np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))))))


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
    anchors: Dict[str, np.ndarray] = {}
    ik_err: Dict[str, float] = {}
    max_bend = 0.0
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
        for goal in anim.ik:
            if type(goal).__name__ == "FeetPlanted":
                for s in goal.sides:
                    S = "Left" if s == "l" else "Right"
                    if i == 0:
                        anchors[S] = np.array([pos[f"{S}Foot"][0], rest.head[f"{S}Foot"][1],
                                               pos[f"{S}Foot"][2]])
                    pole = pos[f"{S}Leg"] + D[f"{S}UpLeg"] @ np.array([0.0, 0.0, 30.0])
                    _chain_ik(rest, D, pos, f"{S}UpLeg", f"{S}Leg", f"{S}Foot",
                              anchors[S], pole, 1.0, keep_end=True)
            elif type(goal).__name__ == "HandTarget":
                S = "Left" if goal.side == "l" else "Right"
                w = _weight(goal.span, t, anim.duration_s)
                if w <= 0.0:
                    continue
                target = np.array(goal.at, float) * 100.0
                pole_dir = np.array(goal.pole, float)
                pole = pos[f"{S}Arm"] + 50.0 * pole_dir / (np.linalg.norm(pole_dir) or 1.0)
                _chain_ik(rest, D, pos, f"{S}Arm", f"{S}ForeArm", f"{S}Hand",
                          target, pole, w, keep_end=False)
                if w >= 1.0:
                    err = float(np.linalg.norm(pos[f"{S}Hand"] - target))
                    key = f"{goal.side}_hand"
                    ik_err[key] = max(ik_err.get(key, 0.0), err)
        for S in ("Left", "Right"):
            max_bend = max(max_bend, _bend(pos, f"{S}Arm", f"{S}ForeArm", f"{S}Hand"),
                           _bend(pos, f"{S}UpLeg", f"{S}Leg", f"{S}Foot"))
        frames.append(Frame(D, pos))
    compiled = Compiled(frames=frames, fps=anim.fps, loop=anim.loop,
                        fingers=any(d.endswith(("_fingers_curl", "_thumb_curl")) for d in used),
                        extrema=extrema, lift_cm=anim.lift_cm,
                        ik_error_cm=ik_err, max_bend_deg=max_bend)
    if anim.loop:
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
