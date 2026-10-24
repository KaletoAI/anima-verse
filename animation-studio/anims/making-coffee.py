"""Making coffee at a machine, looped: standing at the counter, the left
hand holding a cup under the spout, the right hand presses the button on
the machine front, waits, then takes a milk jug and pours a little into
the cup, and sets it back.

Replaces `idle` for the pose `making_coffee`. Counter geometry as in
`cooking.py`: the cup at 1.14 m, 34 cm in front; the machine's button at
1.34 m, 40 cm in front; the jug to the right on the counter.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

BASE = Pose(**RELAXED) | Pose(body_pitch=3, spine_flex=8, neck_flex=18, hips_drop_cm=2,
                              l_hip_abduct=6, r_hip_abduct=6,
                              l_arm_elev=-55, r_arm_elev=-45, l_arm_azim=55, r_arm_azim=60,
                              l_elbow_flex=85, r_elbow_flex=75, l_arm_twist=20, r_arm_twist=20,
                              l_fingers_curl=60, r_fingers_curl=40, l_thumb_curl=40)
CUP = (0.06, 1.14, 0.34)
BUTTON = (-0.04, 1.34, 0.40)
JUG_DOWN, JUG_POUR = (-0.24, 1.10, 0.30), (-0.02, 1.24, 0.34)
REST = (-0.12, 1.15, 0.30)

ANIM = Animation(
    kind="making-coffee", duration_s=7.2, loop=True,
    catalog=Catalog(
        key="making_coffee", group="stand", repoint=True,
        prompt="standing at a counter making coffee, holding a cup under the machine, pouring "
               "milk",
        synonyms=("kaffee kochen", "einen kaffee machen", "brewing coffee",
                  "at the coffee machine")),
    base=BASE,
    keys=[Key(0.0, Pose(r_fingers_curl=40, neck_rot=0)), Key(3.0, Pose(r_fingers_curl=70)),
          Key(5.6, Pose(r_fingers_curl=70)), Key(6.4, Pose(r_fingers_curl=40))],
    layers=[Breath(amp=0.8, period_s=3.6)],
    ik=[FeetPlanted(),
        HandTarget("l", at=((0.0, CUP), (5.0, CUP), (5.6, (CUP[0] - 0.02, CUP[1] + 0.06, CUP[2] - 0.02)),
                            (6.6, CUP)), pole=(1.0, -0.8, -0.4)),
        HandTarget("r", at=((0.0, REST), (0.8, BUTTON), (1.2, BUTTON), (1.8, REST), (2.6, REST),
                            (3.0, JUG_DOWN), (3.6, JUG_POUR), (4.6, JUG_POUR), (5.2, JUG_DOWN),
                            (6.0, REST)), pole=(-1.0, -0.8, -0.4))],
)
