"""Singing, looped: standing, the left hand on the chest, the right hand
rising open and outward with the phrase, the head lifting and the chest
filling on the long notes, then settling for the next line; a slight sway.

Replaces `idle` for the pose `singing`. Pure DOF keys and one target: the
left hand on the sternum (12 cm in front of the chest axis at 1.38 m).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=1,
                               l_arm_elev=-55, l_arm_azim=70, l_elbow_flex=120, l_arm_twist=20,
                               l_fingers_curl=15,
                               r_arm_elev=-70, r_arm_azim=25, r_elbow_flex=40, r_fingers_curl=25)
OPEN = Pose(r_arm_elev=-10, r_arm_azim=55, r_elbow_flex=25, r_arm_twist=60, r_fingers_curl=8,
            r_wrist_flex=-15)
MID = Pose(r_arm_elev=-40, r_arm_azim=50, r_elbow_flex=60, r_arm_twist=40, r_fingers_curl=15)
CHEST = (0.04, 1.38, 0.13)

ANIM = Animation(
    kind="singing", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="singing", group="stand", repoint=True,
        prompt="standing and singing with feeling, one hand on the chest, the other open to the "
               "side, head raised",
        synonyms=("ein lied vortragen", "trällern", "singing a song", "performing a song")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_flex=2, spine_tilt=0, r_arm_elev=-70, r_arm_azim=25,
                        r_elbow_flex=40, r_arm_twist=0, r_wrist_flex=0, r_fingers_curl=25)),
          Key(1.0, MID | Pose(neck_flex=-6, spine_tilt=1.5)),
          Key(2.2, OPEN | Pose(neck_flex=-14, spine_flex=-4)),
          Key(3.2, OPEN | Pose(neck_flex=-12, spine_flex=-4, spine_tilt=-1.5)),
          Key(4.2, MID | Pose(neck_flex=0, spine_flex=0)),
          Key(5.2, Pose(r_arm_elev=-65, r_arm_azim=30, r_elbow_flex=45, r_arm_twist=10,
                        neck_flex=4, spine_tilt=0))],
    layers=[Breath(amp=1.6, period_s=3.0)],
    ik=[FeetPlanted(), HandTarget("l", at=CHEST, pole=(1.0, -1.0, -0.2))],
)
