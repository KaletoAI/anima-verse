"""Presenting, looped: standing before an audience, the left hand holding
notes at the waist, the right hand gesturing — open toward the audience,
then pointing out to a screen on the right, the head turning between the
two; a step of weight from one leg to the other.

Replaces `idle` for the pose `presenting`. The notes 25 cm in front of the
belly at 1.12 m; the pointing hand reaches out to the right at shoulder
height (a screen beside the speaker).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=7, r_hip_abduct=7, hips_drop_cm=1,
                               l_arm_elev=-60, l_arm_azim=55, l_elbow_flex=85, l_arm_twist=40,
                               l_fingers_curl=55, l_thumb_curl=40,
                               r_arm_elev=-65, r_arm_azim=30, r_elbow_flex=50, r_fingers_curl=25)
OPEN = Pose(r_arm_elev=-35, r_arm_azim=55, r_elbow_flex=60, r_arm_twist=60, r_fingers_curl=10)
POINT = Pose(r_arm_elev=5, r_arm_azim=-10, r_elbow_flex=10, r_arm_twist=0, r_fingers_curl=70,
             r_thumb_curl=40)
NOTES = (0.06, 1.12, 0.25)

ANIM = Animation(
    kind="presenting", duration_s=7.0, loop=True,
    catalog=Catalog(
        key="presenting", group="stand", repoint=True,
        prompt="standing and giving a presentation, notes in one hand, the other pointing to a "
               "screen, confident",
        synonyms=("vor publikum sprechen", "eine rede halten", "giving a talk",
                  "giving a presentation")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_rot=0, spine_tilt=0, r_arm_elev=-65, r_arm_azim=30,
                        r_elbow_flex=50, r_arm_twist=0, r_fingers_curl=25)),
          Key(1.0, OPEN | Pose(neck_rot=4)),
          Key(2.0, OPEN | Pose(r_arm_twist=45, neck_rot=-6, spine_tilt=1)),
          Key(3.0, POINT | Pose(neck_rot=-45, spine_rot=-8)),
          Key(4.4, POINT | Pose(neck_rot=-40, spine_rot=-8)),
          Key(5.4, OPEN | Pose(neck_rot=0, spine_rot=0, spine_tilt=-1)),
          Key(6.3, Pose(r_arm_elev=-62, r_arm_azim=35, r_elbow_flex=55, r_arm_twist=10,
                        neck_rot=0, spine_tilt=0))],
    layers=[Breath(amp=0.9, period_s=3.5)],
    ik=[FeetPlanted(), HandTarget("l", at=NOTES, pole=(1.0, -1.0, -0.3))],
)
