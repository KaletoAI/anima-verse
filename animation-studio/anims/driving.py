"""Driving, looped: seated upright, both hands on the steering wheel at ten
to two, small corrections left and right, one longer curve, a glance to the
rear-view mirror and over the shoulder.

Replaces `sit` for the pose `driving`. Seat as in CLAUDE.md (hips 66 cm);
the wheel centre 42 cm in front of the hips at 1.00 m, radius 0.17 m, tilted
back 25 deg; the hands at ±50 deg from the top of the rim. Steering turns
the two hand points about the wheel's axis together.
"""
import math

from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47, body_pitch=-6, spine_flex=4)
ARMS = Pose(l_arm_elev=-35, r_arm_elev=-35, l_arm_azim=65, r_arm_azim=65,
            l_elbow_flex=70, r_elbow_flex=70, l_arm_twist=20, r_arm_twist=20,
            l_fingers_curl=65, r_fingers_curl=65, l_thumb_curl=40, r_thumb_curl=40)
CENTRE, R, TILT = (0.0, 1.00, 0.42), 0.17, math.radians(25)


def rim(deg: float):
    """A point on the rim, ``deg`` from the top (positive = figure's left)."""
    a = math.radians(deg)
    x, up = R * math.sin(a), R * math.cos(a)
    return (CENTRE[0] + x, CENTRE[1] + up * math.cos(TILT), CENTRE[2] - up * math.sin(TILT))


def _hand(base: float):
    steer = ((0.0, 0), (1.0, 6), (2.0, -5), (3.0, 0), (4.0, 28), (5.4, 28), (6.4, 0))
    return tuple((t, rim(base + s)) for t, s in steer)


ANIM = Animation(
    kind="driving", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="driving", group="seat", repoint=True,
        prompt="sitting behind the steering wheel driving a car, both hands on the wheel, eyes "
               "on the road",
        synonyms=("lenken", "am lenkrad", "steering", "driving a car")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(neck_flex=-4),
    keys=[Key(0.0, Pose(neck_rot=0, neck_flex=-4)),
          Key(2.4, Pose(neck_rot=0)), Key(2.8, Pose(neck_rot=8, neck_flex=-10)),
          Key(3.4, Pose(neck_rot=0, neck_flex=-4)),
          Key(6.6, Pose(neck_rot=0)), Key(7.0, Pose(neck_rot=-55)), Key(7.6, Pose(neck_rot=0))],
    layers=[Breath(amp=0.6, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=_hand(50), pole=(1.0, -1.0, -0.2)),
        HandTarget("r", at=_hand(-50), pole=(-1.0, -1.0, -0.2))],
)
