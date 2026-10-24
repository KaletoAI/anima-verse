"""Taking photos, looped: both hands raise a camera to the eye, the right
index finger releases twice, the camera comes down to the chest to look at
the screen, and up again; a knee bends a little and the weight shifts.

Replaces `idle` for the poses `photography` and `filming` (filming takes
this clip too, re-pointed in the catalog). The camera at the eye: the eyes
of the 2 m rig at about 1.80 m, 10 cm in front of the head axis; the camera
body 7-9 cm in front of the face, the hands at its two ends — the right
hand on the grip, the left under the lens. The screen check: the hands at
1.45 m, 28 cm in front of the chest, the head bowed.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=1,
                               r_knee_flex=6, r_hip_flex=3,
                               l_fingers_curl=55, r_fingers_curl=50, l_thumb_curl=40,
                               r_thumb_curl=40,
                               l_arm_elev=-40, r_arm_elev=-35, l_arm_azim=70, r_arm_azim=60,
                               l_elbow_flex=120, r_elbow_flex=125)
EYE_R, EYE_L = (-0.08, 1.79, 0.19), (0.05, 1.76, 0.21)
LOOK_R, LOOK_L = (-0.07, 1.45, 0.29), (0.07, 1.45, 0.29)

ANIM = Animation(
    kind="photographing", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="photography", group="stand", repoint=True,
        prompt="standing and taking a photo, a camera held up to the eye with both hands, "
               "one knee slightly bent, focused",
        synonyms=("ein foto machen", "ein bild knipsen", "knipsen", "taking a picture",
                  "photographing")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_flex=-2, spine_flex=2, r_fingers_curl=50)),
          Key(1.2, Pose(r_fingers_curl=70)),
          Key(1.4, Pose(r_fingers_curl=50)),
          Key(2.0, Pose(r_fingers_curl=70)),
          Key(2.2, Pose(r_fingers_curl=50, neck_flex=-2)),
          Key(3.0, Pose(neck_flex=30, spine_flex=6)),
          Key(4.2, Pose(neck_flex=26, spine_flex=5)),
          Key(5.0, Pose(neck_flex=-2, spine_flex=2))],
    layers=[Breath(amp=0.7, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("r", at=((0.0, EYE_R), (2.4, EYE_R), (3.0, LOOK_R), (4.2, LOOK_R),
                            (5.0, EYE_R)), pole=(-1.0, -1.0, -0.2)),
        HandTarget("l", at=((0.0, EYE_L), (2.4, EYE_L), (3.0, LOOK_L), (4.2, LOOK_L),
                            (5.0, EYE_L)), pole=(1.0, -1.0, -0.2))],
)
