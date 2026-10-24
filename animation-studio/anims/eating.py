"""Eating at a table, looped: seated, leaning a little over the plate, the
left hand holding the knife on the table, the right bringing the fork from
the plate to the mouth, chewing with small head nods, back to the plate.

Replaces `sit` for the pose `eating`. Seat as in CLAUDE.md (hips 66 cm);
the plate on a table about 0.86 m high (0.75 m for a 1.75 m person, scaled
to the 2 m rig) 40 cm in front of the hips; the mouth of the seated rig at
about 1.25 m, the fork hand's wrist 9 cm under it and 6 cm in front.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-55, r_arm_elev=-50, l_arm_azim=55, r_arm_azim=60,
            l_elbow_flex=90, r_elbow_flex=110, l_arm_twist=20, r_arm_twist=40,
            l_fingers_curl=60, r_fingers_curl=60, l_thumb_curl=40, r_thumb_curl=40)
KNIFE = (0.13, 0.90, 0.38)
PLATE = (-0.07, 0.91, 0.40)
MOUTH = (-0.04, 1.16, 0.22)

ANIM = Animation(
    kind="eating", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="eating", group="seat", repoint=True,
        prompt="sitting at a table eating, fork raised to the mouth, the other hand holding a "
               "knife, a plate in front",
        synonyms=("speisen", "eine mahlzeit essen", "having a meal", "eating a meal")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=10, neck_flex=18),
    keys=[Key(0.0, Pose(neck_flex=22, spine_flex=12)),
          Key(1.0, Pose(neck_flex=22, spine_flex=12)),
          Key(1.6, Pose(neck_flex=6, spine_flex=8)),
          Key(2.2, Pose(neck_flex=10)), Key(2.6, Pose(neck_flex=6)),
          Key(3.0, Pose(neck_flex=10)), Key(3.4, Pose(neck_flex=6)),
          Key(4.2, Pose(neck_flex=22, spine_flex=12))],
    layers=[Breath(amp=0.7, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=KNIFE, pole=(1.0, -0.8, -0.3)),
        HandTarget("r", at=((0.0, PLATE), (0.8, PLATE), (1.6, MOUTH), (2.0, MOUTH),
                            (2.6, (MOUTH[0] - 0.02, MOUTH[1] - 0.12, MOUTH[2] + 0.08)),
                            (3.6, (PLATE[0], PLATE[1] + 0.05, PLATE[2])), (4.2, PLATE)),
                   pole=(-1.0, -0.8, -0.2))],
)
