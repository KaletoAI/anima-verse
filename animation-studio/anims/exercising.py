"""Exercising, looped: bodyweight squats in place — feet shoulder-width
apart, arms stretched forward for balance, down until the thighs are
nearly level, up again; a breath out on every rise.

Replaces `idle` for the pose `exercising`. Squat geometry: the hips sink
42 cm (hips_drop_cm) with hip_flex 85 / knee_flex 100 and the torso
pitched forward 25 deg so the weight stays over the planted feet
(FeetPlanted solves the legs, so the DOF keys only shape the knees).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=9, r_hip_abduct=9, l_hip_rot=10, r_hip_rot=10,
                               hips_drop_cm=1, l_fingers_curl=20, r_fingers_curl=20)
UP = Pose(hips_drop_cm=1, l_hip_flex=0, r_hip_flex=0, l_knee_flex=0, r_knee_flex=0,
          body_pitch=0, spine_flex=0, neck_flex=0,
          l_arm_elev=-60, r_arm_elev=-60, l_arm_azim=40, r_arm_azim=40,
          l_elbow_flex=20, r_elbow_flex=20)
DOWN = Pose(hips_drop_cm=42, l_hip_flex=85, r_hip_flex=85, l_knee_flex=100, r_knee_flex=100,
            l_ankle_flex=20, r_ankle_flex=20, body_pitch=25, spine_flex=5, neck_flex=-20,
            l_arm_elev=-5, r_arm_elev=-5, l_arm_azim=85, r_arm_azim=85,
            l_elbow_flex=5, r_elbow_flex=5)

ANIM = Animation(
    kind="exercising", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="exercising", group="stand", repoint=True,
        prompt="doing bodyweight squats, arms stretched forward, athletic clothes, focused",
        synonyms=("kniebeugen", "kniebeugen machen", "squats", "workout")),
    base=STAND,
    keys=[Key(0.0, UP | Pose(l_ankle_flex=0, r_ankle_flex=0)),
          Key(0.3, UP | Pose(l_ankle_flex=0, r_ankle_flex=0)),
          Key(1.3, DOWN),
          Key(1.6, DOWN),
          Key(2.4, UP | Pose(l_ankle_flex=0, r_ankle_flex=0)),
          Key(2.7, UP | Pose(l_ankle_flex=0, r_ankle_flex=0)),
          Key(3.7, DOWN),
          Key(4.0, DOWN)],
    layers=[Breath(amp=1.4, period_s=2.4)],
    ik=[FeetPlanted()],
)
