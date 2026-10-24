"""Lounging on a sofa, looped: slumped back deep into the cushions, the
arms spread out along the backrest, the legs apart, the head resting back;
now and then the head turns to follow something (a screen) and the body
shifts a little deeper into the seat.

Replaces `sit` for the poses `lounging` and `watching_tv` (watching_tv is
re-pointed to this clip in the catalog). Seat as in CLAUDE.md (hips 66 cm,
the feet on the floor — a seat clip's feet must reach it, or the floor
shift would lower the hips under the seat); the pelvis tilted back 18 deg
with the thighs held level (hip_flex = 90 − 18), the upper arms out and
back over where a backrest top lies, the forearms draped along it.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

TILT = -18
SEAT = Pose(l_hip_flex=90 + TILT, r_hip_flex=90 + TILT, l_knee_flex=85, r_knee_flex=85,
            l_hip_abduct=16, r_hip_abduct=16, l_hip_rot=12, r_hip_rot=12, hips_drop_cm=47,
            body_pitch=TILT, spine_flex=-4, neck_flex=8)
ARMS = Pose(l_arm_elev=-30, r_arm_elev=-30, l_arm_azim=-28, r_arm_azim=-28,
            l_elbow_flex=50, r_elbow_flex=50, l_arm_twist=30, r_arm_twist=30,
            l_fingers_curl=25, r_fingers_curl=25)

ANIM = Animation(
    kind="lounging", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="lounging", group="seat", repoint=True,
        prompt="slouched deep into a sofa, arms spread along the backrest, legs apart, relaxed, "
               "half watching something",
        synonyms=("auf dem sofa lümmeln", "abhängen", "lounging on the sofa", "slouching")),
    base=Pose(**RELAXED) | SEAT | ARMS,
    keys=[Key(0.0, Pose(neck_rot=0, neck_flex=8, spine_flex=-4)),
          Key(2.5, Pose(neck_rot=-14, neck_flex=6)),
          Key(4.0, Pose(neck_rot=-14, neck_flex=6, spine_flex=-6)),
          Key(5.5, Pose(neck_rot=6, neck_flex=9)),
          Key(7.0, Pose(neck_rot=0, spine_flex=-4))],
    layers=[Breath(amp=0.9, period_s=4.0)],
    ik=[FeetPlanted()],
)
