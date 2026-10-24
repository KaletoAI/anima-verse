"""Washing the dishes at a sink, looped: standing close to the counter,
slightly bent over the basin, the left hand holding a plate, the right
scrubbing it in small circles with a sponge; halfway the plate is turned.

Replaces the CMU clip `standing washing` the pose `washing_dishes` played
(washing the face and hands, no work at a sink).

The basin: hands about 1.07 m over the floor and 27-35 cm in front of the
feet (a counter top near 1 m for the 2 m rig, the hands just inside the
basin). The right hand circles r = 4 cm around a point on the plate in 1.2 s,
eight keys per circle (target keys ease smoothly between them).
"""
import math

from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

BASE = Pose(**RELAXED) | Pose(body_pitch=6, spine_flex=18, neck_flex=28, hips_drop_cm=2,
                              l_hip_abduct=5, r_hip_abduct=5,
                              l_arm_elev=-55, r_arm_elev=-55, l_arm_azim=55, r_arm_azim=55,
                              l_elbow_flex=70, r_elbow_flex=70, l_arm_twist=20, r_arm_twist=10,
                              l_wrist_flex=10, r_wrist_flex=20,
                              l_fingers_curl=45, r_fingers_curl=55, l_thumb_curl=30,
                              r_thumb_curl=40)
PLATE = (0.07, 1.06, 0.31)        # the left hand's grip on the plate rim
SCRUB = (-0.03, 1.08, 0.31)       # centre of the right hand's circles


def _circle(t0: float, centre, r: float = 0.04, period: float = 1.2, n: int = 8):
    cx, cy, cz = centre
    return [(t0 + period * k / n,
             (cx + r * math.cos(2 * math.pi * k / n), cy, cz + r * math.sin(2 * math.pi * k / n)))
            for k in range(n)]


#: 0-2.4 s two circles, 2.4-3.0 the plate turned (left hand rolls, right
#: hand lifts off), 3.0-4.8 s 1.5 more circles, back to the start.
RIGHT = (_circle(0.0, SCRUB) + _circle(1.2, SCRUB)
         + [(2.7, (SCRUB[0] + 0.04, SCRUB[1] + 0.06, SCRUB[2]))]
         + _circle(3.0, SCRUB) + [(4.2, (SCRUB[0] + 0.04, SCRUB[1], SCRUB[2]))])
LEFT = [(0.0, PLATE), (2.4, PLATE), (2.7, (PLATE[0] - 0.02, PLATE[1] + 0.03, PLATE[2] + 0.02)),
        (3.0, PLATE)]

ANIM = Animation(
    kind="washing-dishes", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="washing_dishes", group="stand", repoint=True,
        prompt="standing at the kitchen sink washing dishes, one hand holding a wet plate, the "
               "other scrubbing it with a sponge, sleeves rolled up",
        synonyms=("teller spülen", "abspülen", "washing dishes", "doing the dishes")),
    base=BASE,
    keys=[Key(0.0, Pose(l_wrist_twist=0)),
          Key(2.4, Pose(l_wrist_twist=0)),
          Key(2.7, Pose(l_wrist_twist=-35)),
          Key(3.0, Pose(l_wrist_twist=0))],
    layers=[Breath(amp=0.8, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("l", at=LEFT, pole=(1.0, -0.6, -0.4)),
        HandTarget("r", at=RIGHT, pole=(-1.0, -0.6, -0.4))],
)
