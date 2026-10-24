"""Freshening up at a mirror, looped: leaning a little toward a mirror in
front, both hands smoothing the hair at the sides of the head, then the
right hand dabs the cheek (make-up or a quick check), the head turning
left and right to look at itself; for the dab the left hand holds a small
mirror in front of the chest (1.45 m, 30 cm forward).

Replaces `idle` for the pose `freshening_up`. The hands stay 17 cm out
from the head's axis (the head centre of the 2 m rig ~1.85 m) and the
cheek dab 17 cm in front and 14 cm to the side of it, clear of the head.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=2,
                               body_pitch=4, spine_flex=6,
                               l_arm_elev=20, r_arm_elev=20, l_arm_azim=40, r_arm_azim=40,
                               l_elbow_flex=130, r_elbow_flex=130, l_fingers_curl=20,
                               r_fingers_curl=20)
L_HAIR = ((0.0, (0.17, 1.86, 0.06)), (0.8, (0.17, 1.76, 0.03)), (1.6, (0.17, 1.86, 0.06)),
          (2.4, (0.17, 1.76, 0.03)), (3.0, (0.08, 1.45, 0.30)), (4.6, (0.08, 1.45, 0.30)), (4.9, (0.22, 1.62, 0.14)),
          (5.2, (0.17, 1.86, 0.06)))
R_HAIR = ((0.0, (-0.17, 1.86, 0.06)), (0.8, (-0.17, 1.76, 0.03)), (1.6, (-0.17, 1.86, 0.06)),
          (2.4, (-0.17, 1.76, 0.03)), (3.0, (-0.17, 1.74, 0.19)), (3.4, (-0.16, 1.73, 0.20)),
          (3.8, (-0.17, 1.74, 0.19)), (4.2, (-0.16, 1.73, 0.20)), (4.6, (-0.17, 1.74, 0.19)),
          (5.2, (-0.17, 1.86, 0.06)))

ANIM = Animation(
    kind="freshening-up", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="freshening_up", group="stand", repoint=True,
        prompt="standing in front of a mirror freshening up, fixing the hair, checking the face",
        synonyms=("sich herrichten", "vor dem spiegel", "fixing one's hair",
                  "checking the mirror")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_rot=0, neck_flex=-2)), Key(1.2, Pose(neck_rot=12)),
          Key(2.4, Pose(neck_rot=-12)), Key(3.2, Pose(neck_rot=-8, neck_tilt=6)),
          Key(4.6, Pose(neck_rot=-8, neck_tilt=6)), Key(5.4, Pose(neck_rot=0, neck_tilt=0))],
    layers=[Breath(amp=0.8, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=L_HAIR, pole=(1.0, 0.0, -0.5)),
        HandTarget("r", at=R_HAIR, pole=(-1.0, 0.0, -0.5))],
)
