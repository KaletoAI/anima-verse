"""Sweeping the floor with a broom, looped: both hands on the handle."""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

ANIM = Animation(
    kind="sweeping-floor", duration_s=2.4, loop=True,
    catalog=Catalog(key="sweeping", group="stand",
                    prompt="standing slightly bent forward, both hands on a broom handle, "
                           "sweeping the floor",
                    synonyms=("fegen", "den boden fegen", "fegt den boden", "kehrt",
                              "sweeping the floor")),
    base=Pose(**RELAXED) | Pose(spine_flex=18, neck_flex=15, hips_drop_cm=4,
                                l_hip_abduct=6, r_hip_abduct=6),
    keys=[Key(0.0, Pose(spine_rot=12, body_yaw=4)),
          Key(1.2, Pose(spine_rot=-12, body_yaw=-4))],
    layers=[Breath(amp=1.0, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("r", at=(-0.12, 1.05, 0.26)),
        HandTarget("l", at=(0.02, 1.23, 0.24))],
)
