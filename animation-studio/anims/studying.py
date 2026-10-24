"""Studying at a desk, looped: hunched over notes, the left elbow on the
desk and the chin resting on the left hand, the right hand writing in short
lines (a small zigzag across the page, then back to the next line), now and
then a pause with the pen lifted while reading.

Replaces `sit` for the pose `studying`. Seat as in CLAUDE.md (hips 66 cm);
the notes on a desk about 0.86 m high, 36 cm in front of the hips. The
chin hand: the left wrist placed so the knuckles of the curled hand meet the
chin of the hunched head (measured on the compiled pose).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-50, l_arm_azim=65, l_elbow_flex=135, l_arm_twist=40,
            l_wrist_flex=35, l_fingers_curl=60, l_thumb_curl=30,
            r_arm_elev=-60, r_arm_azim=55, r_elbow_flex=85, r_arm_twist=10,
            r_fingers_curl=55, r_thumb_curl=45)
CHIN_L = (0.096, 1.052, 0.27)
PAGE = (-0.06, 0.88, 0.36)


def _line(t0: float, y: float):
    """One written line: 4 strokes left to right, 0.25 s each."""
    x0, _, z = PAGE
    return [(t0 + 0.25 * k, (x0 + 0.02 * k, y + (0.006 if k % 2 else 0.0), z)) for k in range(5)]


RIGHT = (_line(0.0, PAGE[1]) + [(1.3, (PAGE[0], PAGE[1] + 0.01, PAGE[2] - 0.015))]
         + _line(1.6, PAGE[1]) + [(2.9, (PAGE[0] + 0.04, PAGE[1] + 0.06, PAGE[2]))]
         + [(4.4, (PAGE[0] + 0.04, PAGE[1] + 0.06, PAGE[2]))])

ANIM = Animation(
    kind="studying", duration_s=5.4, loop=True,
    catalog=Catalog(
        key="studying", group="seat", repoint=True,
        prompt="sitting hunched over books at a desk, writing with a pen, the chin resting on "
               "the other hand",
        synonyms=("notizen machen", "mitschreiben", "taking notes", "doing homework")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=22, neck_flex=22, body_pitch=4),
    keys=[Key(0.0, Pose(neck_rot=0)), Key(2.9, Pose(neck_rot=-5)), Key(4.4, Pose(neck_rot=0))],
    layers=[Breath(amp=0.7, period_s=2.7)],
    ik=[FeetPlanted(),
        HandTarget("l", at=CHIN_L, pole=(0.6, -1.0, 0.2)),
        HandTarget("r", at=RIGHT, pole=(-1.0, -0.8, -0.3))],
)
