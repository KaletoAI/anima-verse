"""Relaxing on a couch, looped: reclined, the hands clasped behind the head,
the elbows out, the legs apart; a long slow breath, the head sinking back
into the hands, a small stretch of the back and a settle.

Replaces `sit` for the pose `relaxing`. Seat as in CLAUDE.md (hips 66 cm,
feet on the floor); the pelvis tilted back 20 deg with the thighs held
level. The hands: the wrists behind the head, either side of its axis
(placed from the compiled head position, see HANDS_L/HANDS_R).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

TILT = -20
SEAT = Pose(l_hip_flex=90 + TILT, r_hip_flex=90 + TILT, l_knee_flex=85, r_knee_flex=85,
            l_hip_abduct=14, r_hip_abduct=14, l_hip_rot=10, r_hip_rot=10, hips_drop_cm=47,
            body_pitch=TILT, spine_flex=-2, neck_flex=6)
ARMS = Pose(l_arm_elev=40, r_arm_elev=40, l_arm_azim=-15, r_arm_azim=-15,
            l_elbow_flex=140, r_elbow_flex=140, l_arm_twist=-30, r_arm_twist=-30,
            l_fingers_curl=50, r_fingers_curl=50)
HANDS_L, HANDS_R = (0.08, 1.26, -0.40), (-0.08, 1.26, -0.40)

ANIM = Animation(
    kind="relaxing", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="relaxing", group="seat", repoint=True,
        prompt="reclined on a couch with the hands clasped behind the head, elbows out, eyes "
               "half closed, completely at ease",
        synonyms=("die seele baumeln lassen", "hände hinter dem kopf", "kicking back",
                  "taking it easy")),
    base=Pose(**RELAXED) | SEAT | ARMS,
    keys=[Key(0.0, Pose(neck_flex=6, spine_flex=-2)),
          Key(3.0, Pose(neck_flex=0, spine_flex=-6)),
          Key(4.2, Pose(neck_flex=0, spine_flex=-6)),
          Key(6.0, Pose(neck_flex=6, spine_flex=-2))],
    layers=[Breath(amp=1.3, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=HANDS_L, pole=(1.0, 0.3, -0.2)),
        HandTarget("r", at=HANDS_R, pole=(-1.0, 0.3, -0.2))],
)
