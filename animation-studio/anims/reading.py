"""Reading on a seat, looped: holding an open book in both hands over the
lap, the head bowed over it, the eyes running along the lines (small head
turns), and every cycle the right hand turns a page — across to the left
page and back.

Replaces `sit` for the pose `reading`. Seat as in CLAUDE.md (hip_flex 90,
knee_flex 90, hips_drop_cm 47 → hips 66 cm, the shoulders near 1.06 m);
the book 25 cm over the thighs at 0.92 m, 30 cm in front of the hips, the
two hands at its outer edges 20 cm apart.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=90, r_hip_flex=90, l_knee_flex=90, r_knee_flex=90,
            l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=47)
ARMS = Pose(l_arm_elev=-55, r_arm_elev=-55, l_arm_azim=55, r_arm_azim=55,
            l_elbow_flex=95, r_elbow_flex=95, l_arm_twist=40, r_arm_twist=40,
            l_fingers_curl=35, r_fingers_curl=35, l_thumb_curl=20, r_thumb_curl=20)
BOOK_L, BOOK_R = (0.10, 0.92, 0.30), (-0.10, 0.92, 0.30)
PAGE = (0.02, 0.95, 0.31)            # the right hand at the left page

ANIM = Animation(
    kind="reading", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="reading", group="seat", repoint=True,
        prompt="sitting and reading a book held open in both hands, head bowed over the pages, "
               "absorbed",
        synonyms=("in einem buch lesen", "schmökern", "reading a book")),
    base=Pose(**RELAXED) | SEAT | ARMS | Pose(spine_flex=12, neck_flex=30),
    keys=[Key(0.0, Pose(neck_rot=4)), Key(1.5, Pose(neck_rot=-4)), Key(1.7, Pose(neck_rot=4)),
          Key(3.2, Pose(neck_rot=-4)), Key(3.4, Pose(neck_rot=4)), Key(5.0, Pose(neck_rot=-4)),
          Key(6.4, Pose(neck_rot=0))],
    layers=[Breath(amp=0.8, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=BOOK_L, pole=(1.0, -0.8, -0.3)),
        HandTarget("r", at=((0.0, BOOK_R), (5.4, BOOK_R), (5.9, PAGE), (6.2, PAGE),
                            (6.9, BOOK_R)), pole=(-1.0, -0.8, -0.3))],
)
