"""Talking while standing, looped: relaxed stance, the hands gesturing in
front of the body — the right hand opens palm up on a point, beats twice,
the left joins with an open "you see" gesture, both settle — with small
nods, a weight shift and the head turning a little to the listener and back.

Replaces `idle` for the pose `talking` (until now it played the plain
standing idle). Pure DOF keys, no targets: the hands stay 25-35 cm in front
of the belly, clear of the body (checked numerically against the torso).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5, hips_drop_cm=1)
REST = Pose(l_arm_elev=-70, r_arm_elev=-70, l_arm_azim=25, r_arm_azim=25,
            l_elbow_flex=55, r_elbow_flex=55, l_arm_twist=20, r_arm_twist=20,
            l_fingers_curl=30, r_fingers_curl=30)
R_OPEN = Pose(r_arm_elev=-50, r_arm_azim=45, r_elbow_flex=80, r_arm_twist=55,
              r_wrist_flex=-15, r_fingers_curl=10)
R_BEAT = Pose(r_arm_elev=-55, r_elbow_flex=72, r_wrist_flex=-5)
L_OPEN = Pose(l_arm_elev=-48, l_arm_azim=40, l_elbow_flex=78, l_arm_twist=60,
              l_wrist_flex=-15, l_fingers_curl=10)
BOTH_OPEN = R_OPEN | L_OPEN | Pose(r_arm_azim=30, l_arm_azim=30, r_arm_elev=-45, l_arm_elev=-45)

ANIM = Animation(
    kind="talking", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="talking", group="stand", repoint=True,
        prompt="standing and talking, one hand gesturing with an open palm, engaged expression, "
               "mid-sentence",
        synonyms=("gestikulieren", "erzählt", "erklärt etwas", "gesturing while talking")),
    base=STAND | REST,
    keys=[Key(0.0, Pose(neck_rot=0, neck_flex=2, spine_tilt=0)),
          Key(0.7, R_OPEN | Pose(neck_rot=8, neck_flex=-2)),
          Key(1.1, R_BEAT | Pose(neck_flex=4)),
          Key(1.4, R_OPEN | Pose(neck_flex=0)),
          Key(1.7, R_BEAT | Pose(neck_flex=4)),
          Key(2.4, BOTH_OPEN | Pose(neck_rot=12, neck_tilt=4, spine_tilt=2)),
          Key(3.4, BOTH_OPEN | Pose(r_arm_twist=45, l_arm_twist=50, neck_flex=6, neck_tilt=0)),
          Key(4.2, REST | Pose(r_wrist_flex=0, l_wrist_flex=0, r_fingers_curl=30,
                               l_fingers_curl=30, neck_rot=4, spine_tilt=-1.5)),
          Key(5.2, L_OPEN | Pose(neck_rot=-4, neck_flex=0)),
          Key(5.7, REST | Pose(l_wrist_flex=0, l_fingers_curl=30, neck_rot=0))],
    layers=[Breath(amp=1.0, period_s=3.0)],
    ik=[FeetPlanted()],
)
