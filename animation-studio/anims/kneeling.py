"""Kneeling upright on the floor, looped: thighs nearly vertical, shins and
insteps on the floor behind, hands resting on the thighs, a slow breath and
a small weight shift from one knee to the other.

The default pose of the place type `ground`, so it replaces the CMU crawl
cycle the pose `kneeling` played (hands on the floor, crawling in place).

Geometry (rig: hip joint 12.3 cm under the Hips head, thigh and shin 46.7 cm
each): with the thigh tilted hip_flex = 8 deg forward and the knee bent so
the shin lies along the floor, the hips stand about 12.3 + 46.7·cos(8°) =
58.5 cm over the knee joint; ``hips_drop_cm`` puts the knee joints a few
centimetres over the floor (a skeleton has no kneecap), and the plantar-flexed
feet bring the toes down onto it.
"""
from animstudio.dsl import Animation, Breath, Catalog, HandTarget, Key, Pose
from animstudio.rig import RELAXED

KNEEL = Pose(l_hip_flex=8, r_hip_flex=8, l_knee_flex=98, r_knee_flex=98,
             l_ankle_flex=-50, r_ankle_flex=-50, l_toes_flex=-20, r_toes_flex=-20,
             l_hip_abduct=5, r_hip_abduct=5, hips_drop_cm=53)
# The arms hang onto the fronts of the upper thighs (the hanging arm reaches
# about 47 cm over the floor here); HandTargets hold the palms there.
HANDS = Pose(l_arm_elev=-75, r_arm_elev=-75, l_arm_azim=20, r_arm_azim=20,
             l_elbow_flex=30, r_elbow_flex=30, l_arm_twist=10, r_arm_twist=10,
             l_wrist_flex=20, r_wrist_flex=20, l_fingers_curl=25, r_fingers_curl=25)
THIGH_L, THIGH_R = (0.13, 0.475, 0.10), (-0.13, 0.475, 0.10)

ANIM = Animation(
    kind="kneeling", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="kneeling", group="ground", repoint=True,
        prompt="kneeling upright on the floor, shins on the ground, hands resting on the "
               "thighs, calm posture",
        synonyms=("auf dem boden knien", "hinknien", "kniet sich hin", "kneeling down",
                  "on one's knees")),
    base=Pose(**RELAXED) | KNEEL | HANDS | Pose(spine_flex=4, neck_flex=6),
    keys=[Key(0.0, Pose(body_roll=0.0, spine_tilt=0.0)),
          Key(1.5, Pose(body_roll=1.2, spine_tilt=-1.5, neck_tilt=1.0)),
          Key(3.0, Pose(body_roll=0.0, spine_tilt=0.0, neck_tilt=0.0)),
          Key(4.5, Pose(body_roll=-1.2, spine_tilt=1.5, neck_tilt=-1.0))],
    layers=[Breath(amp=1.2, period_s=3.0)],
    ik=[HandTarget("l", at=THIGH_L, pole=(0.6, -0.2, -1.0)),
        HandTarget("r", at=THIGH_R, pole=(-0.6, -0.2, -1.0))],
)
