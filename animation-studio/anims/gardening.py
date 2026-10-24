"""Gardening on the knees, looped: kneeling in the bed, bent forward over
it, the hands pressing soil down around a plant — left, right, then both
together — and a small shift of weight with each press.

Replaces the CMU clip `plant` the pose `gardening` played (standing, arms
held forward at chest height), so the pose now matches its synonyms
("kniet im beet", "im beet arbeiten") and moves to the place type `ground`.

Geometry: the upright kneel of `kneeling.py` (thighs 8 deg forward, shins
on the floor, hips_drop_cm 58.5), the pelvis pitched 55 deg forward with the
thighs held where they were (body_pitch tilts the legs back, so
hip_flex = 8 + 55), the spine curled 70 deg: the shoulders come down to
about 47 cm over the floor, 37 cm in front of the hips, and the soil 42 cm
in front of the knees lies inside the arm's 54 cm reach (searched
numerically).
"""
from animstudio.dsl import Animation, Breath, Catalog, HandTarget, Key, Pose
from animstudio.rig import RELAXED

PITCH = 55
KNEEL = Pose(l_hip_flex=8 + PITCH, r_hip_flex=8 + PITCH, l_knee_flex=98, r_knee_flex=98,
             l_ankle_flex=-50, r_ankle_flex=-50, l_toes_flex=-20, r_toes_flex=-20,
             l_hip_abduct=9, r_hip_abduct=9, hips_drop_cm=58.5)
BEND = Pose(body_pitch=PITCH, spine_flex=70, neck_flex=-25)
ARMS = Pose(l_arm_elev=-50, r_arm_elev=-50, l_arm_azim=70, r_arm_azim=70,
            l_elbow_flex=30, r_elbow_flex=30, l_wrist_flex=-75, r_wrist_flex=-75,
            l_fingers_curl=5, r_fingers_curl=5)

#: Soil points (metres, clip space). Each press: down onto the soil, hold,
#: up 7 cm. The plant stands between the hands at x = 0, z = 0.44.
DOWN_L, UP_L = (0.11, 0.05, 0.42), (0.10, 0.12, 0.40)
DOWN_R, UP_R = (-0.11, 0.05, 0.44), (-0.10, 0.12, 0.42)

ANIM = Animation(
    kind="gardening", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="gardening", group="ground", repoint=True,
        prompt="kneeling in a flower bed, bent forward, both hands pressing the soil around a "
               "young plant, gardening gloves",
        synonyms=("pflanzen", "einpflanzen", "erde andrücken", "planting", "kneeling in the garden")),
    base=Pose(**RELAXED) | KNEEL | BEND | ARMS,
    keys=[Key(0.0, Pose(spine_tilt=0.0)),
          Key(0.6, Pose(spine_tilt=2.0)),
          Key(1.8, Pose(spine_tilt=-2.0)),
          Key(3.0, Pose(spine_tilt=0.0, spine_flex=74)),
          Key(3.6, Pose(spine_flex=70))],
    layers=[Breath(amp=0.8, period_s=2.4)],
    ik=[HandTarget("l", at=((0.0, UP_L), (0.4, DOWN_L), (1.0, DOWN_L), (1.4, UP_L),
                            (2.8, UP_L), (3.2, DOWN_L), (3.8, DOWN_L), (4.2, UP_L)),
                   pole=(1.0, 0.2, -0.5)),
        HandTarget("r", at=((0.0, UP_R), (1.2, UP_R), (1.6, DOWN_R), (2.2, DOWN_R),
                            (2.6, UP_R), (2.8, UP_R), (3.2, DOWN_R), (3.8, DOWN_R),
                            (4.2, UP_R)),
                   pole=(-1.0, 0.2, -0.5))],
)
