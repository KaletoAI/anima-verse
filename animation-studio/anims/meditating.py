"""Meditating on the floor, looped: an easy cross-legged seat (knees wide,
the feet close together in front of the pelvis), upright back, hands
resting palms up on the knees, eyes down, slow deep breathing.

Replaces the CMU clip `sit-ground` the pose `meditating` played (one knee
up, leaning back on one hand — not a meditation seat).

A full cross with each foot under the other knee needs more outward hip
rotation than the rig's limit (±45 deg): the feet would point through the
floor. So the seat keeps the shins in front, the left foot 6 cm ahead of the
right so they do not overlap (searched numerically: hip_flex 125/120,
abduct 55, rot 45, knee 145 puts the knees about 22 cm high and the feet at
the floor). Hip joints 5.7 cm over the floor (hips_drop_cm 95:
113 − 95 − 12.3), the sitting bones on it.
"""
from animstudio.dsl import Animation, Breath, Catalog, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=125, r_hip_flex=120, l_hip_abduct=55, r_hip_abduct=55,
            l_hip_rot=45, r_hip_rot=45, l_knee_flex=145, r_knee_flex=145,
            l_ankle_flex=20, r_ankle_flex=20, hips_drop_cm=95)
# An upright back over the pelvis, the head a little bowed.
BACK = Pose(body_pitch=-4, spine_flex=4, neck_flex=12)
ARMS = Pose(l_arm_elev=-60, r_arm_elev=-60, l_arm_azim=25, r_arm_azim=25,
            l_elbow_flex=25, r_elbow_flex=25, l_arm_twist=60, r_arm_twist=60,
            l_wrist_twist=30, r_wrist_twist=30, l_fingers_curl=20, r_fingers_curl=20,
            l_thumb_curl=40, r_thumb_curl=40)
KNEE_L, KNEE_R = (0.36, 0.28, 0.20), (-0.36, 0.28, 0.20)

ANIM = Animation(
    kind="meditating", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="meditating", group="ground", repoint=True,
        prompt="sitting cross-legged on the floor in meditation, upright back, hands resting "
               "palms up on the knees, eyes closed, serene expression",
        synonyms=("in meditation", "meditation", "sitting cross-legged")),
    base=Pose(**RELAXED) | SEAT | BACK | ARMS,
    keys=[Key(0.0, Pose(neck_flex=12)),
          Key(4.0, Pose(neck_flex=14))],
    layers=[Breath(amp=1.6, period_s=4.0)],
    ik=[HandTarget("l", at=KNEE_L, pole=(1.0, -0.3, -0.6)),
        HandTarget("r", at=KNEE_R, pole=(-1.0, -0.3, -0.6))],
)
