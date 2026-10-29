"""Numeric checks — the gate a clip has to pass before it may be published.

Three inputs: the compiled source (DOF extrema, IK error, bends, per-frame
rotation steps, loop layer periods), the MEASUREMENT of the baked clip
(proc_clip re-imports the exported FBX: after hips pin, foot plant and floor
normalisation — foot sliding is only meaningful there) and, optionally, the
baked clip's SIDECAR (fps / frames / loop / duration must agree with the
measurement and the source).
"""
import math
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from animstudio import StudioError, rig
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
FPS = 30


@dataclass
class Check:
    name: str
    ok: bool
    value: float
    limit: str
    detail: str = ""


def _dist(a, b) -> float:
    return math.dist(a, b)


#: The joints the checks read in every frame (the loop seam reads all of
#: frame 0's joints in the last frame as well).
REQUIRED = ("Hips", "LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg",
            "LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase")


def _require(frames: List[Dict]) -> None:
    """A measurement without a joint the checks read is a named error."""
    if not frames:
        raise StudioError("measure: no frames")
    need = set(REQUIRED) | set(frames[0])
    for i, f in enumerate(frames):
        missing = sorted(need - set(f))
        if missing:
            raise StudioError(f"measure: frame {i} lacks {', '.join(missing)}")


def _sidecar_check(anim: Animation, frames: List[Dict], sidecar: Dict) -> Check:
    """fps is the library's 30, the frame count is the measured one, the
    loop flag is the source's, and duration_s = frames / fps (3 decimals,
    the way cmu_clip writes it)."""
    fps, n = sidecar.get("fps"), sidecar.get("frames")
    bad = []
    if fps != FPS:
        bad.append(f"fps {fps} != {FPS}")
    if n != len(frames):
        bad.append(f"frames {n} != measured {len(frames)}")
    if bool(sidecar.get("loop")) != bool(anim.loop):
        bad.append(f"loop {sidecar.get('loop')} != source {anim.loop}")
    dur = sidecar.get("duration_s")
    if not isinstance(fps, (int, float)) or not fps or not isinstance(n, int) \
            or not isinstance(dur, (int, float)) or abs(dur - round(n / fps, 3)) > 1e-9:
        bad.append(f"duration_s {dur} != frames / fps")
    return Check("sidecar", not bad, float(len(bad)), "0 mismatches", "; ".join(bad))


def run_checks(anim: Animation, compiled: Compiled, measure: Dict,
               sidecar: Optional[Dict] = None) -> List[Check]:
    """``sidecar`` (the baked clip's JSON) adds the ``sidecar`` check; a
    real build always passes it."""
    frames = measure["frames"]
    _require(frames)
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
    # An in-place gait: the floor runs back (-Z) at treadmill_mps, so a ball
    # that stays on it moves back by that much per second.
    belt = anim.treadmill_mps * 100.0 / FPS
    worst = 0.0
    for S in ("Left", "Right"):
        run_start = None
        for i, f in enumerate(frames):
            ball = f[f"{S}ToeBase"]
            if ball[1] <= CONTACT_CM:
                if run_start is None:
                    run_start = (i, ball)
                i0, b0 = run_start
                worst = max(worst, math.hypot(ball[0] - b0[0],
                                              ball[2] - (b0[2] - belt * (i - i0))))
            else:
                run_start = None
    out.append(Check("foot_slide", worst <= SLIDE_CM, round(worst, 2), f"<= {SLIDE_CM} cm",
                     f"against a floor running back at {anim.treadmill_mps:g} m/s"
                     if anim.treadmill_mps else ""))
    group = anim.catalog.group if anim.catalog else None
    if group == "stand":
        gap = max(min(f["LeftToeBase"][1], f["RightToeBase"][1],
                      f["LeftFoot"][1], f["RightFoot"][1]) for f in frames)
        out.append(Check("stand_contact", gap <= STAND_CM, round(gap, 2), f"<= {STAND_CM} cm"))
    if group == "ground":
        # Kneeling / sitting on the floor: a foot, a toe OR a knee (the head
        # of LeftLeg/RightLeg) touches the floor in every frame.
        gap = max(min(f[j][1] for j in ("LeftToeBase", "RightToeBase", "LeftFoot", "RightFoot",
                                         "LeftLeg", "RightLeg")) for f in frames)
        out.append(Check("ground_contact", gap <= STAND_CM, round(gap, 2),
                         f"<= {STAND_CM} cm (foot, toe or knee)"))
    if anim.loop:
        seam = max(_dist(frames[0][j], frames[-1][j]) for j in frames[0])
        out.append(Check("loop_seam", seam <= SEAM_CM, round(seam, 2), f"<= {SEAM_CM} cm"))
    out.append(Check("tracks", measure["tracks"] >= MIN_TRACKS, float(measure["tracks"]),
                     f">= {MIN_TRACKS}"))
    if sidecar is not None:
        out.append(_sidecar_check(anim, frames, sidecar))
    if anim.bridge and sidecar is not None:
        rm = sidecar.get("geometry", {}).get("root_motion", {})
        # Authored takes use the reference rig itself: importer leg ratio = 1.
        a, b = compiled.frames[0].pos["Hips"], compiled.frames[-1].pos["Hips"]
        expected = [(b[i] - a[i]) / 100 for i in (0, 2)]
        travel = rm.get("travel_m", [])
        error = (math.dist(travel, expected) if len(travel) == 2 else float("inf"))
        out.append(Check("bridge_travel", rm.get("mode") == "keep" and error <= .01,
                         error, "<= 0.01 m", f"expected {expected}"))
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


# --- pair clips -------------------------------------------------------------
#
# The bodies are read from the COMPILED frames in the pair frame (rotations
# and heads of every bone; the bake only shifts both halves by the same
# floor). A torso is a stack of elliptic cross-sections riding on its spine
# bones — deliberately SMALLER than a real body (half-width TORSO_A_CM,
# half-depth TORSO_B_CM against the rig's shoulder joints at ±12 cm), so a
# failure means a limb or a chest really is inside the other figure.

TORSO_A_CM = 11.0
TORSO_B_CM = 9.0
#: Bone -> (lowest, highest) local height of its cross-section (cm along
#: the bone's rest +Y from its head): the pelvis reaches below the Hips head.
TORSO_SPANS = {"Hips": (-8.0, 7.3), "Spine": (0.0, 7.4), "Spine1": (0.0, 8.6),
               "Spine2": (0.0, 20.8)}
HEAD_R_CM = 9.0
HEAD_GAP_CM = 2.0 * HEAD_R_CM
#: Arm segments sampled against the partner (shoulder -> elbow -> wrist ->
#: knuckles).
ARM_CHAIN = ("Arm", "ForeArm", "Hand", "HandMiddle1")
SAMPLES = 6


def _inside(frame, pt, a: float, b: float) -> float:
    """How deep ``pt`` lies inside ``frame``'s torso (> 0 = inside; the
    elliptic radius minus 1, negated), max over the spine sections."""
    import numpy as np
    worst = -1e9
    for bone, (lo, hi) in TORSO_SPANS.items():
        q = frame.D[bone].T @ (np.asarray(pt) - frame.pos[bone])
        if lo <= q[1] <= hi:
            worst = max(worst, 1.0 - math.hypot(q[0] / a, q[2] / b))
    return worst


def _head_center(frame):
    return (frame.pos["Head"] + frame.pos["HeadTop_End"]) / 2.0


def pair_checks(pair_frames: Dict[str, List]) -> List[Check]:
    """``pair_frames`` = role -> compiled frames in the pair frame."""
    import numpy as np
    A, B = pair_frames["a"], pair_frames["b"]
    arm_in, chest_in, head_gap, arm_head = -1e9, -1e9, 1e9, 1e9
    where = {"arm": "", "chest": ""}
    for i, (fa, fb) in enumerate(zip(A, B)):
        for me, other, role in ((fa, fb, "a"), (fb, fa, "b")):
            for S in ("Left", "Right"):
                chain = [me.pos[f"{S}{j}"] for j in ARM_CHAIN]
                for p0, p1 in zip(chain, chain[1:]):
                    for k in range(SAMPLES + 1):
                        pt = p0 + (p1 - p0) * (k / SAMPLES)
                        d = _inside(other, pt, TORSO_A_CM, TORSO_B_CM)
                        if d > arm_in:
                            arm_in, where["arm"] = d, f"{role} {S} arm, frame {i}"
                        arm_head = min(arm_head, float(np.linalg.norm(pt - _head_center(other))))
            # My chest line against the other's torso grown by my own
            # cross-section: two bodies facing each other touch when their
            # spine lines are a + a' / b + b' apart.
            for bone in ("Spine1", "Spine2"):
                for k in range(SAMPLES + 1):
                    up = TORSO_SPANS[bone][1] * k / SAMPLES
                    pt = me.pos[bone] + me.D[bone] @ np.array([0.0, up, 0.0])
                    d = _inside(other, pt, 2 * TORSO_A_CM, 2 * TORSO_B_CM)
                    if d > chest_in:
                        chest_in, where["chest"] = d, f"{role} {bone}, frame {i}"
        head_gap = min(head_gap, float(np.linalg.norm(_head_center(fa) - _head_center(fb))))
    return [
        Check("pair_arms", arm_in <= 0.0, round(max(arm_in, -1.0), 3),
              "<= 0 (no arm inside the partner's torso)", where["arm"] if arm_in > 0 else ""),
        Check("pair_chests", chest_in <= 0.0, round(max(chest_in, -1.0), 3),
              "<= 0 (chests touch, never overlap)", where["chest"] if chest_in > 0 else ""),
        Check("pair_heads", head_gap >= HEAD_GAP_CM, round(head_gap, 1), f">= {HEAD_GAP_CM} cm"),
        Check("pair_arm_head", arm_head >= HEAD_R_CM, round(arm_head, 1),
              f">= {HEAD_R_CM} cm (no arm through the partner's head)"),
    ]
