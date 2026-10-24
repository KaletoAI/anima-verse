"""Shooting, looped: an aiming stance with a handgun in both hands — knees
slightly bent, torso leaning into it, the arms stretched forward at eye
level; a slow aiming sway, and twice per cycle a shot whose recoil kicks
the hands up and back before they settle on the target again.

Replaces `idle` for the pose `shooting`. The grip: 48 cm in front of the
chest at 1.66 m (the line of sight of the 2 m rig, the head bowed a little
onto the sights); the left hand wraps the right one, 2 cm to its left and
1 cm lower. A shot: 0.1 s up 5 cm and 3 cm back, 0.3 s back down.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STANCE = Pose(**RELAXED) | Pose(l_hip_abduct=8, r_hip_abduct=8, l_hip_flex=6, r_hip_flex=6,
                                l_knee_flex=12, r_knee_flex=12, hips_drop_cm=4,
                                body_pitch=4, spine_flex=6, neck_flex=8,
                                l_arm_elev=-5, r_arm_elev=-5, l_arm_azim=80, r_arm_azim=85,
                                l_elbow_flex=20, r_elbow_flex=12,
                                l_fingers_curl=70, r_fingers_curl=75, l_thumb_curl=50,
                                r_thumb_curl=50)
AIM = (-0.02, 1.66, 0.51)


def _hand(dx: float, dy: float):
    def at(off=(0.0, 0.0, 0.0)):
        return (AIM[0] + dx + off[0], AIM[1] + dy + off[1], AIM[2] + off[2])
    kick, sway_l, sway_r = (0.0, 0.05, -0.03), (0.01, 0.005, 0.0), (-0.01, -0.005, 0.0)
    return ((0.0, at()), (0.8, at(sway_l)), (1.2, at()), (1.3, at(kick)), (1.6, at()),
            (2.6, at(sway_r)), (3.2, at()), (3.3, at(kick)), (3.6, at()))


ANIM = Animation(
    kind="shooting", duration_s=4.8, loop=True,
    catalog=Catalog(
        key="shooting", group="stand", repoint=True,
        prompt="standing in an aiming stance, a handgun held with both hands at eye level, arms "
               "extended, knees slightly bent, focused",
        synonyms=("anlegen", "die waffe anlegen", "aiming", "aiming a gun")),
    base=STANCE,
    keys=[Key(0.0, Pose(neck_flex=8)), Key(2.4, Pose(neck_flex=9))],
    layers=[Breath(amp=0.5, period_s=2.4)],
    ik=[FeetPlanted(),
        HandTarget("r", at=_hand(0.0, 0.0), pole=(-1.0, -1.0, 0.0)),
        HandTarget("l", at=_hand(0.02, -0.01), pole=(1.0, -1.0, 0.0))],
)
