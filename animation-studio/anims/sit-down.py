"""Sitting down onto a seat behind the figure — the ENTRY bridge of every
`seat` place (rule walking -> @seat in clip_transitions.json).

The figure arrives standing with its back to the seat, facing the way it
will sit. Feet stay planted; the hips travel back and down onto the seat
while the torso leans forward for balance and straightens up again.

Geometry (rig, FK): standing, the ankle sits 3.0 cm behind the hips; in the
seat pose of CLAUDE.md (hip_flex 90, knee_flex 90, hips_drop_cm 47 -> hips
66 cm) it sits 42.7 cm in front of them. With the feet held where they
stand, the hips therefore end 3.0 + 42.7 = 45.7 cm behind their start:
root_z_cm = -45.7, and that is the travel the access point is derived from
(access = slot - travel, so the figure starts 45.7 cm in front of the seat).
"""
from animstudio.dsl import Animation, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47, root_z_cm=-45.7)
# Hands come to rest on the thighs once seated.
HANDS = Pose(l_arm_elev=-62, r_arm_elev=-62, l_arm_azim=38, r_arm_azim=38,
             l_elbow_flex=38, r_elbow_flex=38, l_arm_twist=15, r_arm_twist=15)

ANIM = Animation(
    kind="sit-down", duration_s=2.0, loop=False, bridge=True,
    base=Pose(**RELAXED),
    keys=[Key(0.0, Pose()),
          Key(0.45, Pose(l_hip_flex=18, r_hip_flex=18, l_knee_flex=22, r_knee_flex=22,
                         hips_drop_cm=6, root_z_cm=-4, spine_flex=12, neck_flex=-6,
                         l_arm_azim=15, r_arm_azim=15, l_arm_elev=-68, r_arm_elev=-68), "in"),
          Key(1.05, Pose(l_hip_flex=62, r_hip_flex=62, l_knee_flex=66, r_knee_flex=66,
                         hips_drop_cm=27, root_z_cm=-24, spine_flex=30, neck_flex=-14,
                         l_arm_azim=34, r_arm_azim=34, l_arm_elev=-58, r_arm_elev=-58,
                         l_elbow_flex=25, r_elbow_flex=25), "linear"),
          Key(1.55, SEAT | Pose(hips_drop_cm=46.5, root_z_cm=-45.0, spine_flex=16, neck_flex=-6)
              | HANDS, "out"),
          Key(2.0, SEAT | HANDS | Pose(spine_flex=4, neck_flex=0))],
    ik=[FeetPlanted()],
)
