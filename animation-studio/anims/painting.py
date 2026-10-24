"""Painting at an easel, looped: the left hand holds a palette at the hip,
the right hand dips the brush on it and paints strokes on a canvas in
front at chest-to-head height; after a few strokes the painter leans back,
tilts the head and looks at the picture, then paints on.

Replaces `idle` for the pose `painting`. The canvas 48 cm in front of the
feet, 1.35-1.65 m high (an easel for the 2 m rig); the palette 24 cm out to
the left at 1.14 m and 30 cm forward, dipped at its inner front corner (6 cm left of
the midline, 40 cm forward) so the brush arm crosses in front of the chest, not through it. Strokes: four short diagonal lines, 0.35 s each.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=1,
                               l_arm_elev=-55, l_arm_azim=40, l_elbow_flex=85, l_arm_twist=50,
                               l_wrist_flex=-20, l_fingers_curl=30,
                               r_arm_elev=-35, r_arm_azim=65, r_elbow_flex=70,
                               r_fingers_curl=70, r_thumb_curl=50)
PALETTE = (0.24, 1.14, 0.30)
DIP = (0.06, 1.22, 0.40)
CANVAS = [(-0.10, 1.58, 0.45), (-0.02, 1.50, 0.46), (-0.08, 1.45, 0.45), (0.02, 1.38, 0.46)]

RIGHT = ([(0.0, DIP), (0.5, CANVAS[0])]
         + [(0.5 + 0.35 * k, p) for k, p in enumerate(CANVAS)][1:]
         + [(2.0, CANVAS[3]), (2.5, DIP), (3.0, CANVAS[1]), (3.35, CANVAS[2]),
            (3.8, (0.0, 1.35, 0.30)), (5.6, (0.0, 1.35, 0.30))])

ANIM = Animation(
    kind="painting", duration_s=6.4, loop=True,
    catalog=Catalog(
        key="painting", group="stand", repoint=True,
        prompt="standing at an easel painting, a brush in one hand, a palette in the other, "
               "concentrated",
        synonyms=("an der staffelei", "ein gemälde malen", "painting a picture",
                  "at the easel")),
    base=STAND,
    keys=[Key(0.0, Pose(neck_flex=4, body_pitch=2, spine_flex=4, neck_tilt=0)),
          Key(3.4, Pose(neck_flex=4, body_pitch=2, spine_flex=4)),
          Key(4.2, Pose(neck_flex=-2, body_pitch=-3, spine_flex=-2, neck_tilt=10)),
          Key(5.4, Pose(neck_flex=-2, body_pitch=-3, spine_flex=-2, neck_tilt=8)),
          Key(6.0, Pose(neck_flex=4, body_pitch=2, spine_flex=4, neck_tilt=0))],
    layers=[Breath(amp=0.8, period_s=3.2)],
    ik=[FeetPlanted(),
        HandTarget("l", at=PALETTE, pole=(1.0, -0.8, -0.4)),
        HandTarget("r", at=RIGHT, pole=(-1.0, -0.8, -0.3))],
)
