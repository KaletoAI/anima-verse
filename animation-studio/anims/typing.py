"""Working at a desk, looped: seated upright, both hands on a keyboard
typing in short bursts (the fingers and wrists bob), now and then the right
hand moves over to the mouse and clicks, the head steady on a screen,
a pause to read.

Replaces `sit` for the pose `working` (studying gets its own clip). Seat as
in CLAUDE.md (hips 66 cm); the keyboard on a desk about 0.86 m high, 38 cm
in front of the hips, the hands 26 cm apart; the mouse 22 cm to the right
of the keyboard.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-60, r_arm_elev=-60, l_arm_azim=50, r_arm_azim=50,
            l_elbow_flex=85, r_elbow_flex=85, l_arm_twist=0, r_arm_twist=0,
            l_wrist_flex=-10, r_wrist_flex=-10, l_fingers_curl=35, r_fingers_curl=35)
KEY_L, KEY_R = (0.13, 0.88, 0.38), (-0.13, 0.88, 0.38)
MOUSE = (-0.35, 0.87, 0.36)


def _bob(t0: float, n: int, side: str):
    """n finger strokes from t0 (0.2 s each): a small curl down and back —
    a fingertip turns through three joints, so 7 deg of curl already moves it
    about 19 deg (the jumps check reads the tip)."""
    s = "l" if side == "l" else "r"
    keys = []
    for k in range(n):
        t = t0 + 0.2 * k
        keys += [Key(t, Pose(**{f"{s}_fingers_curl": 42, f"{s}_wrist_flex": -6})),
                 Key(t + 0.1, Pose(**{f"{s}_fingers_curl": 35, f"{s}_wrist_flex": -10}))]
    return keys


KEYS = sorted([Key(0.0, Pose(neck_flex=8, l_fingers_curl=35, r_fingers_curl=35))]
              + _bob(0.3, 6, "l") + _bob(0.35, 6, "r")
              + _bob(2.6, 5, "l") + _bob(2.65, 5, "r")
              + [Key(5.6, Pose(neck_flex=8, neck_rot=-6)), Key(6.4, Pose(neck_rot=0))],
              key=lambda k: k.t)

ANIM = Animation(
    kind="typing", duration_s=7.2, loop=True,
    catalog=Catalog(
        key="working", group="seat", repoint=True,
        prompt="sitting at a desk working on a computer, hands on the keyboard, eyes on the "
               "screen, focused",
        synonyms=("am computer arbeiten", "tippen", "typing", "working on a laptop")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=6, neck_flex=8),
    keys=KEYS,
    layers=[Breath(amp=0.7, period_s=3.6)],
    ik=[FeetPlanted(),
        HandTarget("l", at=KEY_L, pole=(1.0, -0.8, -0.3)),
        HandTarget("r", at=((0.0, KEY_R), (4.0, KEY_R), (4.5, MOUSE), (5.4, MOUSE),
                            (5.9, KEY_R)), pole=(-1.0, -0.8, -0.3))],
)
