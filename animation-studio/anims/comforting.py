"""Comforting someone, looped: A stands in front of B with both hands on
B's shoulders, head tilted, and slowly strokes down B's upper arms and up
again; B stands with the head bowed and the shoulders drawn in, hands
clasped in front of the belly, breathing unevenly.

Replaces the CMU pair `comfort` the pose `comforting` played (the two walked
up, hugged and walked apart; A floated 4-8 cm over the floor, an arm went
through B's chest, and the loop jumped 40-50 cm at its seam).

A's hands rest on B's upper chest frame (`Spine2`): the shoulder is about
17 cm up that bone and 17 cm out to the side. The wrist sits in FRONT of
it (z +0.08) so the hand lies on the shoulder instead of reaching past it:
the stroke runs from (±0.17, 0.17, 0.08) to (±0.20, 0.06, 0.06) on the
upper arm.
A's right hand lies on B's left shoulder (x > 0), the left on the right.
"""
from animstudio.dsl import (Breath, Catalog, FeetPlanted, HandTarget, Key, PairAnimation,
                            PartnerTarget, Pose, Role)
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=4, r_hip_abduct=4, hips_drop_cm=1)

A_POSE = Pose(body_pitch=3, spine_flex=12, neck_flex=-2, neck_tilt=10,
              l_arm_elev=-20, r_arm_elev=-20, l_arm_azim=75, r_arm_azim=75,
              l_elbow_flex=45, r_elbow_flex=45, l_arm_twist=-20, r_arm_twist=-20,
              l_wrist_flex=-10, r_wrist_flex=-10, l_fingers_curl=15, r_fingers_curl=15)
B_POSE = Pose(spine_flex=8, neck_flex=26, l_clav_forward=12, r_clav_forward=12,
              l_clav_raise=6, r_clav_raise=6,
              l_arm_elev=-65, r_arm_elev=-65, l_arm_azim=40, r_arm_azim=40,
              l_elbow_flex=70, r_elbow_flex=70, l_fingers_curl=45, r_fingers_curl=45)

SH, ARM = 0.17, 0.06            # shoulder / upper-arm height on B's Spine2


def _stroke(s: int):
    """s = +1: onto B's left shoulder (A's right hand), -1: the right."""
    top, low = (s * 0.17, SH, 0.08), (s * 0.20, ARM, 0.06)
    return ((0.0, top), (1.2, top), (2.4, low), (3.6, top))


A = Role(
    base=STAND | A_POSE,
    keys=[Key(0.0, Pose(neck_tilt=8)), Key(2.4, Pose(neck_tilt=4, spine_flex=14))],
    layers=[Breath(amp=1.0, period_s=4.8)],
    ik=[FeetPlanted(),
        PartnerTarget("r", "Spine2", _stroke(1), pole=(-1.0, -0.6, -0.2)),
        PartnerTarget("l", "Spine2", _stroke(-1), pole=(1.0, -0.6, -0.2))],
)

B = Role(
    base=STAND | B_POSE,
    keys=[Key(0.0, Pose(neck_flex=26)), Key(1.6, Pose(neck_flex=30, spine_flex=10)),
          Key(3.2, Pose(neck_flex=24, spine_flex=8))],
    layers=[Breath(amp=1.8, period_s=1.6)],
    ik=[FeetPlanted(),
        HandTarget("l", at=(0.03, 1.02, 0.20), pole=(1.0, -0.5, -0.5)),
        HandTarget("r", at=(-0.03, 1.02, 0.21), pole=(-1.0, -0.5, -0.5))],
)

ANIM = PairAnimation(
    kind="comforting", duration_s=4.8, loop=True, distance_m=0.60, stagger_m=0.0, anchor_s=1.2,
    catalog=Catalog(
        key="comforting", group="stand", repoint=True,
        prompt="one person comforting another, both hands on the sad person's shoulders, the "
               "other with the head bowed, consoling",
        synonyms=("consoling", "comforting someone", "jemandem trost spenden")),
    a=A, b=B,
)
