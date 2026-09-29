"""Waving with the right hand, looped."""
from animstudio.dsl import Animation, Breath, Catalog, Key, Pose
from animstudio.rig import RELAXED

UP = Pose(r_arm_elev=60, r_arm_azim=20, r_elbow_flex=30, r_arm_twist=80)

ANIM = Animation(
    kind="wave", duration_s=2.0, loop=True,
    catalog=Catalog(key="waving", group="stand",
                    prompt="standing, right hand raised high and waving, friendly open posture",
                    synonyms=("winken", "winkt", "zuwinken", "wave", "waves hello")),
    base=Pose(**RELAXED) | UP,
    keys=[Key(0.0, Pose(r_wrist_dev=-20, r_elbow_flex=10)),
          Key(0.5, Pose(r_wrist_dev=20, r_elbow_flex=50)),
          Key(1.0, Pose(r_wrist_dev=-20, r_elbow_flex=10)),
          Key(1.5, Pose(r_wrist_dev=20, r_elbow_flex=50))],
    layers=[Breath(amp=1.5, period_s=2.0)],
)
