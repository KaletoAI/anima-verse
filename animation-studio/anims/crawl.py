"""Crawling on hands and knees, looped: an easy crawl in place at
0.25 m/s — the diagonal pairs move together (left hand with right knee,
right hand with left knee, the knee a little after its hand), the back
level, the arms nearly straight under the shoulders, the shins and insteps
low over the floor behind, the head up and looking ahead.

The move state of the movement type `crawl` (pose `crawling`). One cycle is
1.2 s; every pad (hand, knee) is in contact for 70 % of it, so two to four
pads carry the body at any moment. The pad paths come from
``animstudio.gait.pad`` (belt speed = ``treadmill_mps``): a hand or knee in
contact rides back with the floor.

Geometry (compiled pose, searched numerically): pelvis pitched 84 deg with
hips_drop_cm 63.5 puts the hip joints 48.5 cm and the shoulders 57.8 cm over
the floor, so the arms stay nearly straight over the whole ±10.5 cm hand
contact (shoulder to wrist at most 53.8 cm of the arm's 54.8). A knee in
contact lies on the circle of the thigh around its hip joint: 1.8 cm over
the floor under the hip, 3.0 cm at the ends of its contact. The ankle
continues the knee 46.7 cm back along a shin raised 6.6 deg (20.6 deg at
mid-swing, the foot stepping while the knee brushes forward), the foot
pitched to lie along it (world pitch -142: toes back, sole up) with the toes
curled away from the floor. The wrist rides 5.5 cm over the floor, 5 cm
outside the shoulder.
"""
import math

import numpy as np

from animstudio import rig
from animstudio.compile import fk, local_rotations
from animstudio.dsl import Animation, Breath, Catalog, FootTarget, HandTarget, Key, Pose
from animstudio.gait import pad
from animstudio.rig import RELAXED

T = 1.2
SPEED = 0.25
STANCE = 0.7
PITCH = 84
SHIN = 46.7                    # cm, knee joint -> ankle joint (rig rest)
SHIN_DEG = 6.6                 # shin raised towards the ankle
FOOT_PITCH = -142.0
HAND_Y = 5.5                   # cm, wrist over the floor in contact
KNEE_LIFT = 4.0                # cm, the knee pads' lift profile (drives the foot)
FOOT_LIFT_DEG = 14.0           # extra shin raise at mid-swing

BASE = Pose(**RELAXED) | Pose(
    body_pitch=PITCH, l_hip_flex=PITCH, r_hip_flex=PITCH, l_knee_flex=92, r_knee_flex=92,
    l_toes_flex=-30, r_toes_flex=-30, hips_drop_cm=63.5, neck_flex=-45,
    l_arm_elev=-10, r_arm_elev=-10, l_arm_azim=80, r_arm_azim=80,
    l_elbow_flex=10, r_elbow_flex=10, l_wrist_flex=-80, r_wrist_flex=-80,
    l_fingers_curl=10, r_fingers_curl=10)

_REST = rig.load_rest()
_D, _POS = fk(_REST, local_rotations(dict(BASE)), BASE["hips_drop_cm"])
HIP = {s: _POS[f"{S}UpLeg"] for s, S in (("l", "Left"), ("r", "Right"))}
SHOULDER = {s: _POS[f"{S}Arm"] for s, S in (("l", "Left"), ("r", "Right"))}

# phase at t = 0 (0 = touchdown): left hand, then right knee a little later;
# the other diagonal half a cycle on
PHASE = {"lh": 0.0, "rk": -0.05, "rh": 0.5, "lk": 0.45}
HANDS = {s: pad(duration_s=T, speed_mps=SPEED, stance=STANCE, phase=PHASE[f"{s}h"],
                centre_cm=float(SHOULDER[s][2]) + 2.0, lift_cm=7.0) for s in ("l", "r")}
KNEES = {s: pad(duration_s=T, speed_mps=SPEED, stance=STANCE, phase=PHASE[f"{s}k"],
                centre_cm=float(HIP[s][2]), lift_cm=KNEE_LIFT) for s in ("l", "r")}


def _knee(s: str, i: int) -> np.ndarray:
    """Knee joint (cm): on the thigh's circle around the hip joint. It cannot
    rise in the swing — that would need the pelvis to bank sideways, and at
    a pitch near 90 deg body_roll and body_yaw both turn about the vertical
    (gimbal) — so the knee brushes forward over the floor, as it does in a
    real crawl, and the foot lifts instead."""
    hip = HIP[s]
    z = KNEES[s].z[i]
    dz = z - float(hip[2])
    y = float(hip[1]) - math.sqrt(SHIN * SHIN - dz * dz)
    return np.array([float(hip[0]), y, z])


def _ankle(s: str, i: int):
    """Ankle target (m): the knee plus the shin, raised SHIN_DEG and up to
    FOOT_LIFT_DEG more in the swing (the pad's lift profile)."""
    k = _knee(s, i)
    raise_deg = SHIN_DEG + FOOT_LIFT_DEG * KNEES[s].lift[i] / KNEE_LIFT
    a = math.radians(raise_deg)
    p = k + SHIN * np.array([0.0, math.sin(a), -math.cos(a)])
    return tuple(float(c) / 100.0 for c in p)


def _hand(s: str, i: int):
    x = float(SHOULDER[s][0]) + (5.0 if s == "l" else -5.0)
    return (x / 100.0, (HAND_Y + HANDS[s].lift[i]) / 100.0, HANDS[s].z[i] / 100.0)


def _frame(i: int, t: float) -> Pose:
    c = math.cos(2 * math.pi * (t / T))               # +1: left hand just down
    # the wrist relaxes in the swing (palm no longer pressed flat)
    wl = -80.0 + 35.0 * HANDS["l"].lift[i] / 7.0
    wr = -80.0 + 35.0 * HANDS["r"].lift[i] / 7.0
    return Pose(body_roll=1.5 * c, spine_rot=-4.0 * c, neck_rot=2.0 * c,
                l_wrist_flex=wl, r_wrist_flex=wr)


G_T = HANDS["l"].t

ANIM = Animation(
    kind="crawl", duration_s=T, loop=True, treadmill_mps=SPEED,
    catalog=Catalog(
        key="crawling", group="ground",
        prompt="crawling on hands and knees across the ground, back level, head raised, "
               "looking ahead",
        synonyms=("kriechen", "krabbeln", "auf allen vieren kriechen", "crawling",
                  "crawling on hands and knees")),
    base=BASE,
    keys=[Key(t, _frame(i, t), "linear") for i, t in enumerate(G_T)],
    layers=[Breath(amp=0.5, period_s=T)],
    ik=[FootTarget(s, at=tuple((t, _ankle(s, i)) for i, t in enumerate(G_T)),
                   pitch=FOOT_PITCH, pole=(0.0, -1.0, 0.3)) for s in ("l", "r")]
    + [HandTarget(s, at=tuple((t, _hand(s, i)) for i, t in enumerate(G_T)),
                  pole=((0.3 if s == "l" else -0.3), 0.0, -1.0)) for s in ("l", "r")],
)
