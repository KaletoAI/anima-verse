"""Puts a foot the ACTOR planted onto the RIG's floor — standard library only.

Imported by the bpy importer (``cmu_clip.py``, Blender's own Python) and by
``scripts/smoke_foot_plant_math.py`` (no Blender), like ``_cmu`` and
``_root_motion``.

The rule: an actor's legs and the rig's differ in length; the importer copies
ROTATIONS, so a foot the actor planted can stand off the rig's floor (CMU
subject 111: right leg 2.69 cm longer → right foot ~2.4 cm up on the rig).
Where the SOURCE says a foot is planted, the rig's foot is pulled onto the
rig floor by a two-bone IK on UpLeg/Leg, the Foot keeping its world rotation
so the toes stay flat. How far is the foot's LIFT (``foot_lift``): the lowest
of its points — ankle, ball, toe tip — over that point's own height in the
rig's rest pose, so a flat foot lands with its ball at rest height and a foot
rolled onto its ball keeps its heel up. Detection reads the SOURCE, so a foot
the actor really lifts (drinking, 13_09: ball 3.5 cm) is never pulled down.

Detection (``foot_planted_frames``) per foot and frame: a point is planted
when it is at most ``PLANT_BAND_CM`` over the floor it rests on (ramp to
``PLANT_BAND_HI_CM``) and moves vertically at most ``PLANT_VY_CM_S`` (ramp to
``PLANT_VY_HI_CM_S``). The ball rests on the source floor; the ankle rests
higher, at its own height while the same foot's ball is planted
(``ankle_floor``). A foot is planted when EITHER point is; the full condition
has to hold for ``PLANT_MIN_S`` in one piece (a shorter touch is a step, not
a stand; a foot hovering inside the ramps never stands), and the weight
fades in and out over ``PLANT_FADE_S``.

Frame: clip frame, Y up, centimetres. The module knows no clip names.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

from _root_motion import FULL, ramp

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]      # (w, x, y, z)

#: Height over the floor a point rests on up to which it is planted, cm —
#: fading out at PLANT_BAND_HI_CM.
PLANT_BAND_CM = 1.5
PLANT_BAND_HI_CM = 3.0
#: Vertical speed up to which a point is planted, cm/s — fading out at
#: PLANT_VY_HI_CM_S.
PLANT_VY_CM_S = 15.0
PLANT_VY_HI_CM_S = 30.0
#: Shortest contact that counts, s.
PLANT_MIN_S = 0.2
#: Fade-in/out of a contact's weight, s.
PLANT_FADE_S = 0.1


def median(values: Sequence[float]) -> Optional[float]:
    """Upper median of the finite values (the importer's floor rule); None
    when there are none."""
    vals = sorted(v for v in values if math.isfinite(v))
    return vals[len(vals) // 2] if vals else None


def _raw(heights: Sequence[float], floor: float, fps: float) -> List[float]:
    """Per frame: height band times vertical-speed band (central difference,
    one-sided at the ends), before the run rule."""
    n = len(heights)
    out = []
    for f in range(n):
        h = heights[f]
        if not math.isfinite(h):
            out.append(0.0)
            continue
        a, b = max(f - 1, 0), min(f + 1, n - 1)
        vy = 0.0
        if b > a and math.isfinite(heights[a]) and math.isfinite(heights[b]):
            vy = (heights[b] - heights[a]) / ((b - a) / fps)
        out.append(ramp(h - floor, PLANT_BAND_CM, PLANT_BAND_HI_CM)
                   * ramp(abs(vy), PLANT_VY_CM_S, PLANT_VY_HI_CM_S))
    return out


def foot_planted_frames(points: Sequence[Tuple[Sequence[float], float]],
                        fps: float) -> List[float]:
    """Weight 0..1 per frame in which a FOOT is planted in the source.

    ``points``: per detection point its source heights per frame and the
    floor it rests on. The points are ORed per frame (the larger raw weight)
    BEFORE the run rule, so a heel strike that rolls onto the ball is one
    contact. A run of frames with a raw weight > 0 counts only when it holds
    the full condition (raw 1: within PLANT_BAND_CM and PLANT_VY_CM_S) for
    PLANT_MIN_S in one piece — a foot hovering inside the ramps is not
    standing (drinking's right ball at 2.6 … 3.0 cm); the ramps only soften
    the edges of a real contact. A counted run keeps its raw weights, faded
    in and out over PLANT_FADE_S: ``w(f) = raw(f) · min(1, (f − a + 1)/(F + 1),
    (b − f + 1)/(F + 1))`` for the run [a, b], F = round(PLANT_FADE_S · fps)
    — except on a side where the run touches the take's first or last frame:
    the take's start is no touchdown, and its last frame is the pose a bridge
    clip holds, so it keeps the full correction.
    """
    n = max((len(h) for h, _ in points), default=0)
    raws = [_raw(h, floor, fps) for h, floor in points]
    raw = [max((r[f] for r in raws if f < len(r)), default=0.0) for f in range(n)]
    fade = int(round(PLANT_FADE_S * fps))
    out = [0.0] * n
    f = 0
    while f < n:
        if raw[f] <= 0.0:
            f += 1
            continue
        a = f
        while f < n and raw[f] > 0.0:
            f += 1
        b = f - 1
        if _longest_full(raw, a, b) / fps < PLANT_MIN_S - 1e-9:
            continue
        for g in range(a, b + 1):
            fade_in = 1.0 if a == 0 else (g - a + 1) / (fade + 1)
            fade_out = 1.0 if b == n - 1 else (b - g + 1) / (fade + 1)
            out[g] = raw[g] * min(1.0, fade_in, fade_out)
    return out


def _longest_full(raw: Sequence[float], a: int, b: int) -> int:
    """Longest stretch of full-weight frames inside [a, b]."""
    best = cur = 0
    for g in range(a, b + 1):
        cur = cur + 1 if raw[g] >= FULL else 0
        best = max(best, cur)
    return best


def planted_frames(src_heights: Sequence[float], src_floor: float,
                   fps: float) -> List[float]:
    """Weight 0..1 per frame in which ONE point stands on ``src_floor`` in
    the source (``foot_planted_frames`` with a single point)."""
    return foot_planted_frames([(src_heights, src_floor)], fps)


def ankle_floor(ankle_heights: Sequence[float],
                ball_weights: Sequence[float]) -> Optional[float]:
    """The height the ankle rests at: its median over the frames in which
    the SAME foot's ball is fully planted. None when the ball never is —
    then the ankle is no detection point (a foot held up for the whole take
    must not declare its own height the ground)."""
    return median([h for h, w in zip(ankle_heights, ball_weights) if w >= FULL])


def foot_lift(heights: Dict[str, float], rest: Dict[str, float]) -> float:
    """How far a foot stands off the floor: the least of its points' heights
    over their own rest heights (points missing on either side are skipped)."""
    return min(heights[p] - rest[p] for p in heights if p in rest)


# ---------------------------------------------------------------- vectors

def _sub(a, b) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _len(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a) -> Vec3:
    n = _len(a)
    return _scale(a, 1.0 / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def rotation_between(a, b) -> Quat:
    """Shortest rotation taking direction ``a`` onto direction ``b``."""
    a, b = _unit(a), _unit(b)
    c = _dot(a, b)
    if c < -1.0 + 1e-12:                      # opposite: 180° about any normal
        axis = _cross(a, (1.0, 0.0, 0.0))
        if _len(axis) < 1e-6:
            axis = _cross(a, (0.0, 1.0, 0.0))
        axis = _unit(axis)
        return (0.0, axis[0], axis[1], axis[2])
    x = _cross(a, b)
    q = (1.0 + c, x[0], x[1], x[2])
    n = math.sqrt(sum(v * v for v in q))
    return tuple(v / n for v in q)


def two_bone_ik(hip, knee, ankle, target, pole) -> Tuple[Quat, Quat]:
    """World-space rotation deltas (Δupper, Δlower) that bend or stretch the
    chain hip→knee→ankle so the ankle reaches ``target``.

    Δupper turns the thigh about the hip; Δlower turns the shin — already
    carried along by Δupper — about the new knee. Both segment lengths stay.
    The knee stays in the plane of the hip→target line and ``pole`` (the
    current knee: its own bending plane), on the pole's side. A target out
    of reach stretches the leg along the hip→target line as far as it goes;
    one closer than |l1 − l2| folds it as far as it goes. A pole on the
    hip→target line has no side; the plane then falls back to one through
    the world X axis (Z when the line is X)."""
    l1 = _len(_sub(knee, hip))
    l2 = _len(_sub(ankle, knee))
    to_t = _sub(target, hip)
    d = _len(to_t)
    if l1 < 1e-9 or l2 < 1e-9 or d < 1e-9:
        return (1.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)
    t = _scale(to_t, 1.0 / d)
    d = min(max(d, abs(l1 - l2) + 1e-9), l1 + l2)
    p = _sub(pole, hip)
    u = _sub(p, _scale(t, _dot(p, t)))
    if _len(u) < 1e-9:
        u = _cross(t, (1.0, 0.0, 0.0))
        if _len(u) < 1e-6:
            u = _cross(t, (0.0, 0.0, 1.0))
    u = _unit(u)
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2.0 * l1 * d)))
    sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
    new_knee = _add(hip, _add(_scale(t, l1 * cos_a), _scale(u, l1 * sin_a)))
    reach = _add(hip, _scale(t, d))
    d_upper = rotation_between(_sub(knee, hip), _sub(new_knee, hip))
    shin = _qrot(d_upper, _sub(ankle, knee))
    d_lower = rotation_between(shin, _sub(reach, new_knee))
    return d_upper, d_lower


def _qrot(q: Quat, v) -> Vec3:
    """``v`` turned by the unit quaternion ``q``."""
    w, x, y, z = q
    qv = (x, y, z)
    t = _scale(_cross(qv, v), 2.0)
    return _add(_add(v, _scale(t, w)), _cross(qv, t))
