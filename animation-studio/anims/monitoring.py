"""Monitoring screens, looped: sitting upright and alert at a desk, the
right hand on a mouse, the left resting on the desk, the head scanning
from one screen to the next and back; once the body leans in to look
closer and the mouse hand clicks.

Replaces `sit` for the pose `monitoring`. Seat as in CLAUDE.md (hips
66 cm); the desk about 0.86 m, the mouse 36 cm in front and 22 cm to the
right, the left hand on the desk 30 cm in front.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-60, r_arm_elev=-60, l_arm_azim=45, r_arm_azim=50,
            l_elbow_flex=85, r_elbow_flex=85, l_fingers_curl=30, r_fingers_curl=40)
MOUSE = (-0.22, 0.88, 0.36)
DESK_L = (0.16, 0.88, 0.30)

ANIM = Animation(
    kind="monitoring", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="monitoring", group="seat", repoint=True,
        prompt="sitting alert at a desk watching several screens, one hand on the mouse, eyes "
               "scanning",
        synonyms=("bildschirme beobachten", "monitore überwachen", "watching the screens",
                  "monitoring screens")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=4, neck_flex=2),
    keys=[Key(0.0, Pose(neck_rot=0, spine_flex=4, r_fingers_curl=40)),
          Key(1.5, Pose(neck_rot=22)), Key(2.6, Pose(neck_rot=22)),
          Key(3.6, Pose(neck_rot=-22)), Key(4.6, Pose(neck_rot=-22)),
          Key(5.4, Pose(neck_rot=0, spine_flex=14, neck_flex=8)),
          Key(6.0, Pose(r_fingers_curl=55)), Key(6.2, Pose(r_fingers_curl=40)),
          Key(7.0, Pose(spine_flex=4, neck_flex=2))],
    layers=[Breath(amp=0.7, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=DESK_L, pole=(1.0, -0.8, -0.3)),
        HandTarget("r", at=MOUSE, pole=(-1.0, -0.8, -0.3))],
)
