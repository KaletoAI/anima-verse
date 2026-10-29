"""Sitting down onto the floor — the ENTRY bridge of every `ground` place
(rule walking -> @ground in clip_transitions.json): kneeling, a cross-legged
seat, a bath tub. The figure squats with the feet planted and lowers itself
back onto the floor, knees up; the place's own clip takes over from there.

Geometry (rig, FK): the end pose hip_flex 128 (the limit is 130), knee_flex
79, hips_drop_cm 97 puts the hips 16 cm over the floor (the hip joints at
3.7 cm, the lowest joints of the clip) and the ankle 68.6 cm in front of them.
Standing, the ankle sits 3.0 cm behind the hips. With the feet held where they
stand the hips therefore end 68.6 + 3.0 = 71.6 cm behind their start:
root_z_cm = -71.6 is the travel, and the access point lies 71.6 cm in front of
the place.
"""
from animstudio.dsl import Animation, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

def legs(hip, knee):
    return Pose(l_hip_flex=hip, r_hip_flex=hip, l_knee_flex=knee, r_knee_flex=knee)

ANIM = Animation(
    kind="sit-down-floor", duration_s=2.4, loop=False, bridge=True,
    base=Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6),
    keys=[Key(0.0, Pose()),
          Key(0.5, legs(40, 50) | Pose(hips_drop_cm=18, root_z_cm=-6, spine_flex=22, neck_flex=-10,
                                        l_arm_azim=30, r_arm_azim=30, l_arm_elev=-62, r_arm_elev=-62),
              "in"),
          Key(1.1, legs(105, 125) | Pose(hips_drop_cm=60, root_z_cm=-24, spine_flex=34, neck_flex=-20,
                                          l_arm_azim=62, r_arm_azim=62, l_arm_elev=-38, r_arm_elev=-38,
                                          l_elbow_flex=20, r_elbow_flex=20), "linear"),
          Key(1.7, legs(124, 92) | Pose(hips_drop_cm=94, root_z_cm=-64, spine_flex=18, neck_flex=-8,
                                         l_arm_azim=50, r_arm_azim=50, l_arm_elev=-48, r_arm_elev=-48,
                                         l_elbow_flex=35, r_elbow_flex=35), "out"),
          Key(2.4, legs(128, 79) | Pose(hips_drop_cm=97, root_z_cm=-71.6, spine_flex=8, neck_flex=0,
                                         l_arm_azim=45, r_arm_azim=45, l_arm_elev=-50, r_arm_elev=-50,
                                         l_elbow_flex=40, r_elbow_flex=40))],
    ik=[FeetPlanted()],
)
