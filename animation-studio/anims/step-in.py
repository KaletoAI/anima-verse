"""Arriving at a standing place — the ENTRY bridge of every `stand` place
(rule walking -> @stand in clip_transitions.json).

The figure comes out of its walk on the spot: the weight settles, the knees
give a little, the arms swing in to hang. No travel — the access point is
the place itself.

The hips end 1 cm lower than they start on purpose: the 3D client raises a
figure onto a raised stand place (a treadmill deck, a shower tray) in
proportion to how far the hips have moved from their first towards their
last height, and a bridge whose hips end where they started gives that
proportion no span.
"""
from animstudio.dsl import Animation, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

ANIM = Animation(
    kind="step-in", duration_s=0.8, loop=False, bridge=True,
    base=Pose(**RELAXED),
    keys=[Key(0.0, Pose(l_arm_azim=14, r_arm_azim=-10, spine_flex=3)),
          Key(0.3, Pose(hips_drop_cm=3.0, l_knee_flex=7, r_knee_flex=7, l_hip_flex=4, r_hip_flex=4,
                        l_arm_azim=4, r_arm_azim=-2, spine_flex=1), "out"),
          Key(0.8, Pose(hips_drop_cm=1.0, l_knee_flex=3, r_knee_flex=3, l_hip_flex=2, r_hip_flex=2,
                        l_arm_azim=0, r_arm_azim=0, spine_flex=0))],
    ik=[FeetPlanted()],
)
