"""Cooking at the stove, looped: standing at the counter, the left hand on
the handle of a pot, the right stirring with a spoon in slow circles; once
per cycle the right hand lifts out and sprinkles a pinch of salt over the
pot, then stirs on.

Replaces `idle` for the pose `cooking`. A stove top near 1 m for the 2 m
rig with a pot on it: the rim, where the spoon stirs, at 1.20 m and 0.38 m
in front of the feet, the handle at the pot's side; the stirring circle
r = 5 cm in 1.5 s, eight keys per circle.
"""
import math

from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

BASE = Pose(**RELAXED) | Pose(body_pitch=3, spine_flex=10, neck_flex=26, hips_drop_cm=2,
                              l_hip_abduct=6, r_hip_abduct=6,
                              l_arm_elev=-55, r_arm_elev=-50, l_arm_azim=45, r_arm_azim=55,
                              l_elbow_flex=70, r_elbow_flex=80, l_arm_twist=10, r_arm_twist=20,
                              l_fingers_curl=70, r_fingers_curl=70, l_thumb_curl=40,
                              r_thumb_curl=50)
HANDLE = (0.22, 1.16, 0.36)          # the left hand on the pot handle
POT = (-0.02, 1.20, 0.38)            # centre of the stirring circle
SALT = (-0.10, 1.31, 0.36)           # the pinch over the pot


def _circle(t0: float, r: float = 0.05, period: float = 1.5, n: int = 8):
    cx, cy, cz = POT
    return [(t0 + period * k / n,
             (cx + r * math.cos(2 * math.pi * k / n), cy, cz + r * math.sin(2 * math.pi * k / n)))
            for k in range(n)]


#: Two circles (0-3.0 s), out to the salt and back (3.0-4.5 s), one circle.
RIGHT = (_circle(0.0) + _circle(1.5)
         + [(3.4, SALT), (3.7, (SALT[0] + 0.01, SALT[1] + 0.02, SALT[2])), (4.0, SALT),
            (4.5, (POT[0] + 0.05, POT[1], POT[2]))]
         + _circle(4.5)[1:])

ANIM = Animation(
    kind="cooking", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="cooking", group="stand", repoint=True,
        prompt="standing at the stove cooking, stirring a pot with a wooden spoon, the other hand "
               "on the pot handle, steam rising",
        synonyms=("umrühren", "rührt im topf", "am herd stehen", "stirring a pot")),
    base=BASE,
    keys=[Key(0.0, Pose(neck_rot=0, spine_tilt=0)),
          Key(3.0, Pose(neck_rot=-6, spine_tilt=1)),
          Key(4.5, Pose(neck_rot=0, spine_tilt=0))],
    layers=[Breath(amp=0.8, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=HANDLE, pole=(1.0, -0.6, -0.4)),
        HandTarget("r", at=RIGHT, pole=(-1.0, -0.6, -0.4))],
)
