"""Changing clothes, looped: grabbing the hem of a top at both sides,
pulling it up in front of the face and over the head, down again at the
sides of the head, smoothing it over the hips and straightening the collar.

Replaces the CMU clip `putting on a dress` the pose `changing_clothes`
played (a one-shot of 11.3 s that froze at its end, the motion hardly read
as dressing).

Hand path (metres, clip space; the rig is 2 m tall: shoulders 1.53 m, the
head centre about 1.85 m, an arm reaches 0.55 m): the hem at the hips
(y 1.02), up in front of the face (1.62, 30 cm forward — the forearms pass
the face, not through it), over the head (1.92) with the head bowed, down
at the sides of the head (1.74, 20 cm out), wide past the shoulders (1.52,
34 cm out — a hand passing close by the shoulder would fold the elbow shut)
and down the flanks to the hips (1.06); then the collar at the chest (1.44, 21 cm forward).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

BASE = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5, hips_drop_cm=1,
                              l_fingers_curl=55, r_fingers_curl=55, l_thumb_curl=40,
                              r_thumb_curl=40)

# (left, right) hand points.
HEM = ((0.15, 1.02, 0.14), (-0.15, 1.02, 0.14))
FACE = ((0.12, 1.62, 0.30), (-0.12, 1.62, 0.30))
OVER = ((0.10, 1.92, 0.14), (-0.10, 1.92, 0.14))
SIDES = ((0.20, 1.74, 0.05), (-0.20, 1.74, 0.05))
WIDE = ((0.34, 1.52, 0.12), (-0.34, 1.52, 0.12))    # past the shoulders, elbows open
HIPS = ((0.18, 1.06, 0.09), (-0.18, 1.06, 0.09))
COLLAR = ((0.07, 1.44, 0.21), (-0.07, 1.44, 0.21))
TIMES = (0.0, 0.9, 1.6, 2.2, 2.65, 3.1, 3.9)


def _path(side: int):
    return tuple((t, pts[side]) for t, pts in zip(TIMES, (HEM, FACE, OVER, SIDES, WIDE, HIPS, COLLAR)))


ANIM = Animation(
    kind="changing-clothes", duration_s=5.0, loop=True,
    catalog=Catalog(
        key="changing_clothes", group="stand", repoint=True,
        prompt="standing and changing clothes, pulling a top over the head",
        synonyms=("ein oberteil anziehen", "pulli anziehen", "getting dressed",
                  "putting on a top")),
    base=BASE,
    keys=[Key(0.0, Pose(neck_flex=10, spine_flex=4)),
          Key(1.6, Pose(neck_flex=24, spine_flex=6)),
          Key(2.3, Pose(neck_flex=8, spine_flex=2)),
          Key(3.1, Pose(neck_flex=12, spine_flex=4)),
          Key(3.9, Pose(neck_flex=18, spine_flex=3))],
    layers=[Breath(amp=1.0, period_s=2.5)],
    ik=[FeetPlanted(),
        HandTarget("l", at=_path(0), pole=(1.0, -0.3, -0.4)),
        HandTarget("r", at=_path(1), pole=(-1.0, -0.3, -0.4))],
)
