"""Root motion of a clip rebuilt from its FOOT CONTACTS — standard library only.

Imported by the bpy importer (``clip_root_motion.py``, Blender's own Python)
and by ``scripts/smoke_root_motion_math.py`` (no Blender), like ``_cmu``.

The input is a take whose horizontal root travel has been STRIPPED: the hips
stay at the origin, so a foot that stands still in the world slides backwards
here by exactly the travel. Wherever a foot is planted, the root is moved by
the opposite of that slide; where no foot is planted (the body rests on a
seat or a bed, or is in the air) the root holds still. That is the rule
"the planted foot is the fixed point".

Frame: clip frame, Y up, +Z forward, +X the figure's left, centimetres.
"""
import math
from typing import Dict, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]

MODES = ("strip", "keep", "foot_lock")
#: Ankle and ball of each foot: the heel strike pins the ankle, the toe-off
#: the ball — one rigid foot, two points, so a rolling foot stays pinned.
CONTACT_POINTS = ("LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase")
#: Height above a point's own ground at which contact fades out, cm.
BAND_LO_CM = 2.0
BAND_HI_CM = 5.0
#: Vertical speed at which contact fades out, cm/s — a foot coming down onto
#: the floor is not planted yet.
VY_LO_CM_S = 15.0
VY_HI_CM_S = 30.0
#: Percentile of a point's heights taken as its ground.
GROUND_PCT = 0.05
#: Below this summed weight a frame has no planted point.
MIN_WEIGHT = 1e-3
#: A frame pair at or above this weight counts as FULL contact (spans, drift).
FULL = 0.999


def ramp(v: float, lo: float, hi: float) -> float:
    """1 at or below ``lo``, 0 at or above ``hi``, linear in between; NaN → 0."""
    if not math.isfinite(v):
        return 0.0
    if v <= lo:
        return 1.0
    if v >= hi:
        return 0.0
    return (hi - v) / (hi - lo)


def _finite(p) -> bool:
    return p is not None and all(math.isfinite(c) for c in p)


def ground_heights(tracks: Dict[str, List[Vec3]],
                   rest_heights: Dict[str, float]) -> Dict[str, float]:
    """Per point the height it rests at when planted: the low percentile of
    its own heights, but never above its height in the rig's rest pose — a
    point that never touches the floor must not declare its lowest airborne
    height the ground."""
    out = {}
    for name, pts in tracks.items():
        ys = sorted(p[1] for p in pts if _finite(p))
        if not ys:
            continue
        pct = ys[min(len(ys) - 1, int(GROUND_PCT * (len(ys) - 1)))]
        out[name] = min(pct, rest_heights.get(name, math.inf))
    return out


def contact_weights(tracks: Dict[str, List[Vec3]], ground: Dict[str, float],
                    fps: float) -> Dict[str, List[float]]:
    """Per point and frame: how planted it is, 0..1 — height band times
    vertical-speed band (central difference, one-sided at the ends)."""
    out = {}
    for name, pts in tracks.items():
        n = len(pts)
        g = ground.get(name)
        w = []
        for f in range(n):
            p = pts[f]
            if g is None or not _finite(p):
                w.append(0.0)
                continue
            a, b = max(f - 1, 0), min(f + 1, n - 1)
            if b > a and _finite(pts[a]) and _finite(pts[b]):
                vy = (pts[b][1] - pts[a][1]) / ((b - a) / fps)
            else:
                vy = 0.0
            w.append(ramp(p[1] - g, BAND_LO_CM, BAND_HI_CM)
                     * ramp(abs(vy), VY_LO_CM_S, VY_HI_CM_S))
        out[name] = w
    return out


def foot_lock_path(tracks: Dict[str, List[Vec3]],
                   weights: Dict[str, List[float]]) -> List[Tuple[float, float]]:
    """Root XZ offset per frame (frame 0 = origin): each step moves the root
    by the weighted opposite of the planted points' horizontal slide."""
    n = max((len(p) for p in tracks.values()), default=0)
    if n == 0:
        return []
    path = [(0.0, 0.0)]
    for f in range(n - 1):
        sw = sx = sz = 0.0
        for name, pts in tracks.items():
            w = weights.get(name) or []
            if f + 1 >= len(pts) or f + 1 >= len(w):
                continue
            ws = min(w[f], w[f + 1])
            if ws <= 0 or not (_finite(pts[f]) and _finite(pts[f + 1])):
                continue
            sw += ws
            sx += ws * (pts[f + 1][0] - pts[f][0])
            sz += ws * (pts[f + 1][2] - pts[f][2])
        x, z = path[-1]
        if sw >= MIN_WEIGHT:
            x, z = x - sx / sw, z - sz / sw
        path.append((x, z))
    return path


def max_planted_drift(tracks: Dict[str, List[Vec3]],
                      weights: Dict[str, List[float]],
                      path: Sequence[Tuple[float, float]]) -> float:
    """Largest horizontal distance a point travels in the WORLD (track + path)
    during one unbroken run of full contact, cm. 0 = every planted point stood
    exactly still — the number the importer verifies and the sidecar keeps."""
    worst = 0.0
    for name, pts in tracks.items():
        w = weights.get(name) or []
        start = None
        for f in range(min(len(pts), len(w), len(path))):
            if w[f] >= FULL and _finite(pts[f]):
                wx, wz = pts[f][0] + path[f][0], pts[f][2] + path[f][1]
                if start is None:
                    start = (wx, wz)
                worst = max(worst, math.hypot(wx - start[0], wz - start[1]))
            else:
                start = None
    return worst


def contact_spans(weights: Dict[str, List[float]], fps: float) -> List[List[float]]:
    """Seconds [start, end] during which at least one point is in full
    contact (frame pairs, like ``foot_lock_path``) — for the sidecar."""
    n = max((len(w) for w in weights.values()), default=0)
    spans, start = [], None
    for f in range(n):
        on = any(f + 1 < len(w) and min(w[f], w[f + 1]) >= FULL
                 for w in weights.values())
        if on and start is None:
            start = f
        if not on and start is not None:
            spans.append([round(start / fps, 3), round(f / fps, 3)])
            start = None
    if start is not None:
        spans.append([round(start / fps, 3), round((n - 1) / fps, 3)])
    return spans


def rotate_travel(travel: Tuple[float, float], yaw_deg: float = 0.0,
                  tilt_deg: float = 0.0, roll_deg: float = 0.0) -> Tuple[float, float]:
    """The horizontal part of ``Ry(yaw)·Rx(tilt)·Rz(roll)·(x, 0, z)`` — what a
    clip's travel becomes when ``clip_orient`` turns the file (same order and
    signs as ``clip_orient.rotation``)."""
    x, y, z = float(travel[0]), 0.0, float(travel[1])
    r = math.radians(roll_deg)       # Rz
    x, y = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
    t = math.radians(tilt_deg)       # Rx
    y, z = y * math.cos(t) - z * math.sin(t), y * math.sin(t) + z * math.cos(t)
    a = math.radians(yaw_deg)        # Ry
    x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
    return (x, z)
