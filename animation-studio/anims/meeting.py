"""Sitting in a meeting, looped: upright at a table, the hands folded on
it, listening with small nods; then the right hand lifts off to make a
point (an open gesture over the table), the head turns to another person,
and the hands fold again.

Replaces `sit` for the pose `meeting`. Seat as in CLAUDE.md (hips 66 cm);
the folded hands on a table about 0.88 m high, 36 cm in front of the hips.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-55, r_arm_elev=-55, l_arm_azim=60, r_arm_azim=60,
            l_elbow_flex=90, r_elbow_flex=90, l_arm_twist=20, r_arm_twist=20,
            l_fingers_curl=55, r_fingers_curl=55)
FOLD_L, FOLD_R = (0.05, 0.90, 0.36), (-0.04, 0.90, 0.37)
POINT = (-0.10, 1.02, 0.44)

ANIM = Animation(
    kind="meeting", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="meeting", group="seat", repoint=True,
        prompt="sitting at a conference table in a meeting, hands folded, attentive, making a "
               "point",
        synonyms=("am tisch besprechen", "in der sitzung", "in a meeting",
                  "discussing at a table")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=4, neck_flex=6),
    keys=[Key(0.0, Pose(neck_flex=6, neck_rot=0, r_fingers_curl=55)),
          Key(0.8, Pose(neck_flex=12)), Key(1.4, Pose(neck_flex=5)),
          Key(2.0, Pose(neck_flex=12)), Key(2.6, Pose(neck_flex=6)),
          Key(3.6, Pose(neck_rot=-18, r_fingers_curl=10)),
          Key(5.6, Pose(neck_rot=-14, r_fingers_curl=10)),
          Key(6.6, Pose(neck_rot=0, r_fingers_curl=55))],
    layers=[Breath(amp=0.7, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=FOLD_L, pole=(1.0, -0.8, -0.3)),
        HandTarget("r", at=((0.0, FOLD_R), (3.0, FOLD_R), (3.6, POINT), (4.2, (POINT[0] - 0.04, POINT[1] + 0.03, POINT[2])),
                            (4.8, POINT), (5.6, POINT), (6.4, FOLD_R)), pole=(-1.0, -0.8, -0.3))],
)
