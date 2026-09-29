"""Sweeping the floor with a broom, looped: both hands on the handle.

One stroke from the figure's left (+X) to its right (-X) in 1.2 s, then the
same way back. The torso twist (spine_rot, body_yaw) runs in sync with the
hands. The two hand paths are laid out on one broom handle. The upper
(left) hand is at 121 cm, the lower (right) hand 18 cm further down it,
and the broom head sweeps x = +45 .. -55 cm about 70 cm in front of the
feet. The lower hand sits 18/121 = 0.15 of the way from the upper hand to
the head, so it travels x = 0.06 + 0.15 * (0.45 - 0.06) = +0.12 to
-0.12 + 0.15 * (-0.55 + 0.12) = -0.185 m.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

ANIM = Animation(
    kind="sweeping-floor", duration_s=2.4, loop=True,
    catalog=Catalog(key="sweeping", group="stand",
                    prompt="standing slightly bent forward, both hands on a broom handle, "
                           "sweeping the floor",
                    synonyms=("fegen", "den boden fegen", "fegt den boden", "kehrt",
                              "sweeping the floor")),
    base=Pose(**RELAXED) | Pose(spine_flex=25, neck_flex=15, hips_drop_cm=8,
                                l_hip_abduct=6, r_hip_abduct=6),
    keys=[Key(0.0, Pose(spine_rot=24, body_yaw=6)),
          Key(1.2, Pose(spine_rot=-24, body_yaw=-6))],
    layers=[Breath(amp=1.0, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("r", at=((0.0, (0.12, 1.03, 0.28)), (1.2, (-0.185, 1.03, 0.26)))),
        HandTarget("l", at=((0.0, (0.06, 1.21, 0.20)), (1.2, (-0.12, 1.21, 0.20))))],
)
