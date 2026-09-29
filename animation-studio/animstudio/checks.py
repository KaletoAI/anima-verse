"""Numeric checks — the gate a clip has to pass before it may be published.

Two inputs: the compiled source (DOF extrema, IK error, bends, per-frame
rotation steps, loop layer periods) and the MEASUREMENT of the baked clip
(proc_clip re-imports the exported FBX: after hips pin, foot plant and floor
normalisation — foot sliding is only meaningful there).
"""
import math
import statistics
from dataclasses import dataclass
from typing import Dict, List

from animstudio import rig
from animstudio.compile import Compiled
from animstudio.dsl import Animation

FLOOR_CM = -1.0
CONTACT_CM = 2.5
SLIDE_CM = 2.0
STAND_CM = 3.0
STEP_DEG = 30.0
SEAM_CM = 1.0
MIN_TRACKS = 8
IK_CM = 3.0
BEND_DEG = 155.0
SEAT_HIPS_CM = (61.0, 71.0)
SEAT_THIGH_DEG = 20.0
LIE_HIPS_CM = (15.0, 25.0)


@dataclass
class Check:
    name: str
    ok: bool
    value: float
    limit: str
    detail: str = ""


def _dist(a, b) -> float:
    return math.dist(a, b)


def run_checks(anim: Animation, compiled: Compiled, measure: Dict) -> List[Check]:
    frames = measure["frames"]
    out: List[Check] = []
    bad = [f"{d} {lo:.0f}..{hi:.0f}" for d, (lo, hi) in compiled.extrema.items()
           if d in rig.LIMITS and (lo < rig.LIMITS[d][0] - 1e-6 or hi > rig.LIMITS[d][1] + 1e-6)]
    out.append(Check("limits", not bad, float(len(bad)), "0 violations", "; ".join(bad)))
    out.append(Check("bend", compiled.max_bend_deg <= BEND_DEG, round(compiled.max_bend_deg, 1),
                     f"<= {BEND_DEG}"))
    out.append(Check("jumps", compiled.max_step_deg <= STEP_DEG, round(compiled.max_step_deg, 1),
                     f"<= {STEP_DEG} deg/frame"))
    ik = max(compiled.ik_error_cm.values(), default=0.0)
    out.append(Check("ik", ik <= IK_CM, round(ik, 2), f"<= {IK_CM} cm",
                     ", ".join(f"{k} {v:.1f}" for k, v in compiled.ik_error_cm.items())))
    out.append(Check("loop_layers", not compiled.loop_problems, float(len(compiled.loop_problems)),
                     "0", "; ".join(compiled.loop_problems)))
    low = min(p[1] for f in frames for p in f.values())
    out.append(Check("floor", low >= FLOOR_CM, round(low, 2), f">= {FLOOR_CM} cm"))
    worst = 0.0
    for S in ("Left", "Right"):
        run_start = None
        for f in frames:
            ball = f[f"{S}ToeBase"]
            if ball[1] <= CONTACT_CM:
                if run_start is None:
                    run_start = ball
                worst = max(worst, math.hypot(ball[0] - run_start[0], ball[2] - run_start[2]))
            else:
                run_start = None
    out.append(Check("foot_slide", worst <= SLIDE_CM, round(worst, 2), f"<= {SLIDE_CM} cm"))
    group = anim.catalog.group
    if group == "stand":
        gap = max(min(f["LeftToeBase"][1], f["RightToeBase"][1],
                      f["LeftFoot"][1], f["RightFoot"][1]) for f in frames)
        out.append(Check("stand_contact", gap <= STAND_CM, round(gap, 2), f"<= {STAND_CM} cm"))
    if anim.loop:
        seam = max(_dist(frames[0][j], frames[-1][j]) for j in frames[0])
        out.append(Check("loop_seam", seam <= SEAM_CM, round(seam, 2), f"<= {SEAM_CM} cm"))
    out.append(Check("tracks", measure["tracks"] >= MIN_TRACKS, float(measure["tracks"]),
                     f">= {MIN_TRACKS}"))
    hips = statistics.median(f["Hips"][1] for f in frames)
    if group == "seat":
        thigh = statistics.median(
            math.degrees(math.atan2(abs(f[f"{S}Leg"][1] - f[f"{S}UpLeg"][1]),
                                    math.hypot(f[f"{S}Leg"][0] - f[f"{S}UpLeg"][0],
                                               f[f"{S}Leg"][2] - f[f"{S}UpLeg"][2])))
            for f in frames for S in ("Left", "Right"))
        ok = SEAT_HIPS_CM[0] <= hips <= SEAT_HIPS_CM[1] and thigh <= SEAT_THIGH_DEG
        out.append(Check("seat_height", ok, round(hips, 1),
                         f"hips {SEAT_HIPS_CM} cm, thigh <= {SEAT_THIGH_DEG}",
                         f"thigh {thigh:.1f} deg"))
    if group == "lie":
        ok = LIE_HIPS_CM[0] <= hips <= LIE_HIPS_CM[1]
        out.append(Check("lie_height", ok, round(hips, 1), f"hips {LIE_HIPS_CM} cm"))
    return out
