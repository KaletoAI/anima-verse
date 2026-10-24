"""Serving, looped: a tray balanced on the flat left hand at shoulder height,
the right hand takes a glass off it, leans in and sets it down on a table
in front, straightens up and comes back to steady the tray.

Replaces `idle` for the pose `serving`. The tray hand: palm up (arm twist
-60, wrist bent back 70 and turned 60 — searched numerically for the palm
normal pointing up), 1.45 m high and 24 cm out to the left, 25 cm forward; the
glass set down at about 1.02 m (a table near 0.85 m for the 2 m rig plus
the glass's grip height), 38 cm in front of the feet, reached with the
pelvis pitched 12 deg and the spine bent 18.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5, hips_drop_cm=1,
                               l_arm_elev=-45, l_arm_azim=40, l_elbow_flex=95, l_arm_twist=-60,
                               l_wrist_flex=-70, l_wrist_twist=60, l_fingers_curl=10,
                               r_arm_elev=-55, r_arm_azim=55, r_elbow_flex=80,
                               r_fingers_curl=55, r_thumb_curl=40)
TRAY = (0.24, 1.45, 0.25)
GLASS = (0.10, 1.52, 0.27)           # the right hand on a glass on the tray
TABLE = (-0.08, 1.02, 0.38)
LIFT = (-0.04, 1.14, 0.36)

ANIM = Animation(
    kind="serving", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="serving", group="stand", repoint=True,
        prompt="waiter serving, a tray balanced on one hand, the other hand setting a glass down "
               "on a table, polite smile",
        synonyms=("servieren", "ein getränk servieren", "kellnern", "waiting tables")),
    base=STAND,
    keys=[Key(0.0, Pose(body_pitch=0, spine_flex=2, neck_flex=4)),
          Key(1.0, Pose(body_pitch=0, spine_flex=2, neck_flex=4)),
          Key(2.0, Pose(body_pitch=12, spine_flex=18, neck_flex=22)),
          Key(2.5, Pose(body_pitch=12, spine_flex=18, neck_flex=22)),
          Key(3.4, Pose(body_pitch=0, spine_flex=2, neck_flex=4))],
    layers=[Breath(amp=0.8, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("l", at=TRAY, pole=(1.0, -1.0, -0.3)),
        HandTarget("r", at=((0.0, GLASS), (0.8, GLASS), (1.5, LIFT), (2.0, TABLE), (2.5, TABLE),
                            (3.0, LIFT), (3.8, GLASS)), pole=(-1.0, -0.8, -0.3))],
)
