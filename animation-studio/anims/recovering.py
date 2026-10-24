"""Recovering on a seat, looped: sitting slumped back, exhausted, the hands
resting on the thighs, breathing heavily — the chest heaves, the head rolls
back and drops forward again — then a long breath out.

Replaces the CMU clip `sitting-in-chair` the pose `recovering` played (a
0.8 s cycle, almost still, legs crossed, the hips 75 cm high — 9 cm over
the seat height every place uses).

Seat as in CLAUDE.md (hip_flex 90, knee_flex 90, hips_drop_cm 47 → hips
near 66 cm); the pelvis tilted back 10 deg with the thighs held level
(body_pitch tilts the legs along, so hip_flex = 90 − 10).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

TILT = -10
SEAT = Pose(l_hip_flex=90 + TILT, r_hip_flex=90 + TILT, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=10, r_hip_abduct=10, l_hip_rot=8, r_hip_rot=8, hips_drop_cm=47,
            body_pitch=TILT, spine_flex=14)
ARMS = Pose(l_arm_elev=-70, r_arm_elev=-70, l_arm_azim=30, r_arm_azim=30,
            l_elbow_flex=40, r_elbow_flex=40, l_arm_twist=10, r_arm_twist=10,
            l_fingers_curl=30, r_fingers_curl=30)
THIGH_L, THIGH_R = (0.16, 0.64, 0.30), (-0.16, 0.64, 0.30)

ANIM = Animation(
    kind="recovering", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="recovering", group="seat", repoint=True,
        prompt="sitting slumped back, exhausted, catching breath, hands resting on the thighs, "
               "flushed face",
        synonyms=("nach luft schnappen", "durchschnaufen", "catching breath")),
    base=Pose(**RELAXED) | SEAT | ARMS,
    keys=[Key(0.0, Pose(neck_flex=-10)),
          Key(1.5, Pose(neck_flex=-18, spine_flex=10)),
          Key(3.0, Pose(neck_flex=8, spine_flex=16)),
          Key(4.5, Pose(neck_flex=22, spine_flex=20)),
          Key(5.4, Pose(neck_flex=4, spine_flex=15))],
    layers=[Breath(amp=2.6, period_s=1.5)],
    ik=[FeetPlanted(),
        HandTarget("l", at=THIGH_L, pole=(0.8, -0.3, -0.6)),
        HandTarget("r", at=THIGH_R, pole=(-0.8, -0.3, -0.6))],
)
