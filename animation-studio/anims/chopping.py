"""Chopping with a knife at the counter, looped: the left hand holds the
food on the cutting board with curled fingers and creeps back along it, the
right hand chops in quick short strokes behind it; now and then the
cook scrapes the cut pieces aside with the blade.

Replaces `idle` for the pose `holding_knife`. Counter geometry as in
`cooking.py`: the board on a counter near 1 m, the hands at 1.15 m and 38 cm in
front of the feet; a chop is
7 cm up and down in 0.3 s.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

BASE = Pose(**RELAXED) | Pose(body_pitch=3, spine_flex=10, neck_flex=26, hips_drop_cm=2,
                              l_hip_abduct=6, r_hip_abduct=6,
                              l_arm_elev=-55, r_arm_elev=-50, l_arm_azim=55, r_arm_azim=55,
                              l_elbow_flex=85, r_elbow_flex=80, l_arm_twist=10, r_arm_twist=30,
                              l_fingers_curl=55, r_fingers_curl=75, r_thumb_curl=50)
HOLD = (0.08, 1.15, 0.38)
KNIFE = (-0.04, 1.16, 0.38)


def _chops(t0: float, n: int, x0: float):
    keys = []
    for k in range(n):
        x = x0 + 0.008 * k
        keys += [(t0 + 0.3 * k, (x, KNIFE[1] + 0.07, KNIFE[2])),
                 (t0 + 0.3 * k + 0.15, (x, KNIFE[1], KNIFE[2]))]
    return keys


RIGHT = (_chops(0.0, 8, KNIFE[0])
         + [(2.6, (KNIFE[0] + 0.04, KNIFE[1] + 0.02, KNIFE[2] + 0.04)),
            (3.2, (KNIFE[0] - 0.12, KNIFE[1] + 0.01, KNIFE[2] + 0.02)),
            (3.8, (KNIFE[0], KNIFE[1] + 0.07, KNIFE[2]))])
LEFT = ((0.0, HOLD), (2.4, (HOLD[0] + 0.06, HOLD[1], HOLD[2])), (3.8, HOLD))

ANIM = Animation(
    kind="chopping", duration_s=4.4, loop=True,
    catalog=Catalog(
        key="holding_knife", group="stand", repoint=True,
        prompt="standing at a kitchen counter chopping vegetables with a knife on a cutting board",
        synonyms=("gemüse schneiden", "klein schneiden", "chopping vegetables",
                  "cutting vegetables")),
    base=BASE,
    keys=[Key(0.0, Pose(neck_rot=0)), Key(2.6, Pose(neck_rot=-4)), Key(3.8, Pose(neck_rot=0))],
    layers=[Breath(amp=0.7, period_s=2.2)],
    ik=[FeetPlanted(),
        HandTarget("l", at=LEFT, pole=(1.0, -0.8, -0.4)),
        HandTarget("r", at=RIGHT, pole=(-1.0, -0.8, -0.4))],
)
