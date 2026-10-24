"""Commanding attention, looped: a tall wide stance, chest out, the hands
on the hips; then the right arm points firmly forward, comes back as a
chopping gesture, the left hand opens out, and both return to the hips;
the chin stays up.

Replaces `idle` for the pose `commanding_attention`. Hands on the hips:
the wrists at the iliac crests, 22 cm out to each side at 1.08 m.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=12, r_hip_abduct=12, hips_drop_cm=2,
                               spine_flex=-4, neck_flex=-6,
                               l_arm_elev=-50, r_arm_elev=-50, l_arm_azim=-15, r_arm_azim=-15,
                               l_elbow_flex=100, r_elbow_flex=100, l_arm_twist=-30,
                               r_arm_twist=-30, l_fingers_curl=30, r_fingers_curl=30)
HIP_L, HIP_R = (0.22, 1.08, -0.02), (-0.22, 1.08, -0.02)
POINT = (-0.08, 1.52, 0.48)
CHOP_UP, CHOP_DOWN = (-0.10, 1.48, 0.36), (-0.08, 1.20, 0.40)
OPEN_L = (0.40, 1.25, 0.25)

ANIM = Animation(
    kind="commanding", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="commanding_attention", group="stand", repoint=True,
        prompt="standing tall in a wide stance, chest out, pointing firmly forward, commanding "
               "attention",
        synonyms=("befehlen", "anweisungen geben", "giving orders", "taking charge")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_rot=0, r_fingers_curl=30)),
          Key(1.2, Pose(r_fingers_curl=75, r_thumb_curl=40)),
          Key(2.2, Pose(r_fingers_curl=10, r_thumb_curl=0)),
          Key(4.6, Pose(r_fingers_curl=30, neck_rot=0))],
    layers=[Breath(amp=1.2, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("r", at=((0.0, HIP_R), (0.6, HIP_R), (1.2, POINT), (2.0, POINT),
                            (2.4, CHOP_UP), (2.8, CHOP_DOWN), (3.2, CHOP_UP), (3.6, CHOP_DOWN),
                            (4.6, HIP_R)), pole=(-1.0, -0.6, -0.3)),
        HandTarget("l", at=((0.0, HIP_L), (2.6, HIP_L), (3.2, OPEN_L), (4.0, OPEN_L),
                            (4.8, HIP_L)), pole=(1.0, -0.6, -0.3))],
)
