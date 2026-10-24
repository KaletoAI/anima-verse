"""Gaming on a seat, looped: leaning forward, forearms near the knees, a
controller held in both hands between them, the thumbs working (small
hand jiggles), the torso swaying with the game and one sudden jolt back.

Replaces `sit` for the pose `gaming`. Seat as in CLAUDE.md (hips 66 cm);
the controller 26 cm in front of the hips at 0.80 m, the hands 13 cm apart
(its two grips), the torso pitched 18 deg so the forearms reach the knees.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90 + 18, r_hip_flex=90 + 18, l_knee_flex=95, r_knee_flex=95,
            l_hip_abduct=12, r_hip_abduct=12, hips_drop_cm=47, body_pitch=18)
ARMS = Pose(l_arm_elev=-65, r_arm_elev=-65, l_arm_azim=45, r_arm_azim=45,
            l_elbow_flex=100, r_elbow_flex=100, l_arm_twist=30, r_arm_twist=30,
            l_fingers_curl=60, r_fingers_curl=60, l_thumb_curl=30, r_thumb_curl=30)
PAD_L, PAD_R = (0.065, 0.80, 0.30), (-0.065, 0.80, 0.30)


def _jiggle(p, t0: float, n: int, dx: float):
    return [(t0 + 0.3 * k, (p[0] + (dx if k % 2 else 0.0), p[1] + (0.01 if k % 2 else 0.0), p[2]))
            for k in range(n)]


ANIM = Animation(
    kind="gaming", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="gaming", group="seat", repoint=True,
        prompt="sitting leaning forward with a game controller in both hands, elbows near the "
               "knees, intense focus on a screen",
        synonyms=("konsole spielen", "an der konsole", "playing video games", "console gaming")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=10, neck_flex=-12),
    keys=[Key(0.0, Pose(spine_tilt=0, l_thumb_curl=30, r_thumb_curl=30)),
          Key(0.6, Pose(spine_tilt=3, l_thumb_curl=45)), Key(1.2, Pose(spine_tilt=-2, r_thumb_curl=45)),
          Key(1.8, Pose(spine_tilt=4, l_thumb_curl=30, r_thumb_curl=30)),
          Key(3.0, Pose(spine_tilt=0, spine_flex=10, neck_flex=-12)),
          Key(3.3, Pose(spine_flex=2, neck_flex=-4)),
          Key(4.0, Pose(spine_flex=10, neck_flex=-12, spine_tilt=-3)),
          Key(5.2, Pose(spine_tilt=0))],
    layers=[Breath(amp=0.7, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=tuple(_jiggle(PAD_L, 0.0, 10, 0.01) + [(3.3, (PAD_L[0], PAD_L[1] + 0.06, PAD_L[2] - 0.04)), (4.0, PAD_L)]),
                   pole=(1.0, -0.5, -0.5)),
        HandTarget("r", at=tuple(_jiggle(PAD_R, 0.0, 10, -0.01) + [(3.3, (PAD_R[0], PAD_R[1] + 0.06, PAD_R[2] - 0.04)), (4.0, PAD_R)]),
                   pole=(-1.0, -0.5, -0.5))],
)
