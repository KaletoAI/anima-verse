"""Flirting, looped: standing with the weight on one leg and the hip out,
the head tilted, one hand playing with the hair at the side of the head,
the other hand at the hip; a small sway toward the partner and a coy look
away and back.

Replaces `idle` for the pose `flirting`. The hair hand: the right wrist
18 cm out from the head's axis, level with the ear (the head centre of the
2 m rig ~1.85 m), clear of the head sphere; the left hand on the hip.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=4, r_hip_abduct=8, hips_drop_cm=2,
                               l_knee_flex=14, l_hip_flex=6, body_roll=-2.5, spine_tilt=4,
                               r_arm_elev=30, r_arm_azim=30, r_elbow_flex=140, r_arm_twist=-20,
                               r_fingers_curl=40,
                               l_arm_elev=-55, l_arm_azim=-10, l_elbow_flex=95, l_arm_twist=-30,
                               l_fingers_curl=20)
HAIR = ((0.0, (-0.18, 1.80, 0.02)), (1.2, (-0.18, 1.74, 0.04)), (2.4, (-0.18, 1.80, 0.02)))
HIP = (0.22, 1.06, -0.02)

ANIM = Animation(
    kind="flirting", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="flirting", group="stand", repoint=True,
        prompt="standing flirtatiously, weight on one leg, playing with the hair, head tilted, "
               "a coy smile",
        synonyms=("anbandeln", "mit den haaren spielen", "flirting with someone",
                  "playing with the hair")),
    base=STAND | Pose(neck_tilt=-10, neck_rot=8),
    keys=[Key(0.0, Pose(neck_tilt=-10, neck_rot=8, spine_tilt=4)),
          Key(1.6, Pose(neck_tilt=-12, neck_rot=-14, spine_tilt=5)),
          Key(2.6, Pose(neck_tilt=-8, neck_rot=10, spine_tilt=3)),
          Key(3.8, Pose(neck_tilt=-11, neck_rot=6, spine_tilt=4.5))],
    layers=[Breath(amp=0.9, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("r", at=HAIR, pole=(-1.0, 0.2, -0.3)),
        HandTarget("l", at=HIP, pole=(1.0, 0.0, -0.8))],
)
