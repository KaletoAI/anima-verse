"""Dancing together, looped: a salsa basic in place in closed hold — A's
right hand on B's left shoulder blade, B's left hand on A's right shoulder,
the other two hands clasped out to the side at shoulder height; on every
count the weight shifts, one knee bends, the hips sway, eight counts of
0.5 s. The two mirror each other, so both lean the same way in the world.

A's right hand: on B's `Spine1` frame 12.5 cm to B's left, 13 cm up, 5 cm
behind its axis — the side of the shoulder blade, which A's arm reaches
around B's flank at this distance (a hand further onto the back would
leave the arm 4.7 cm short).

Replaces the CMU pair `salsa` the pose `dancing together` played (35 s that
wandered 2 m across the floor, an arm 1.7 cm from the partner's head centre
and 0.9 deep in the partner's chest, a foot 17 cm under the floor, a loop
seam of 2 m and 176 deg).

The clasped hands meet in the pair frame at the middle between the two,
0.30 m out to A's left (= B's right) at 1.45 m: in A's own space that is
x = +0.30, z = distance/2, in B's x = −0.30, z = distance/2 — the same
point, so each role holds one HandTarget there (2.5 cm short of the middle:
the palms lie against each other). A's own left is the world's −Z, B's own
right as well, so A's "lean left" key is B's "lean right".
"""
from animstudio.dsl import (Breath, Catalog, FeetPlanted, HandTarget, Key, PairAnimation,
                            PartnerTarget, Pose, Role)
from animstudio.rig import RELAXED

DIST = 0.46
STAND = Pose(**RELAXED) | Pose(l_hip_abduct=6, r_hip_abduct=6, hips_drop_cm=3,
                               l_knee_flex=8, r_knee_flex=8, l_hip_flex=4, r_hip_flex=4)
HOLD_A = Pose(l_arm_elev=-10, l_arm_azim=35, l_elbow_flex=70, l_arm_twist=40,
              r_arm_elev=-25, r_arm_azim=70, r_elbow_flex=80, r_arm_twist=-10,
              l_fingers_curl=40, r_fingers_curl=20, neck_rot=-10)
HOLD_B = Pose(r_arm_elev=-10, r_arm_azim=35, r_elbow_flex=70, r_arm_twist=40,
              l_arm_elev=-15, l_arm_azim=75, l_elbow_flex=75, l_arm_twist=-10,
              l_fingers_curl=20, r_fingers_curl=40, neck_rot=10)


def _counts(side: int):
    """Eight counts; side +1 = start leaning to the own left."""
    keys = []
    for k in range(8):
        s = side if k % 2 == 0 else -side
        keys.append(Key(0.5 * k, Pose(body_roll=1.5 * s, spine_tilt=-2.5 * s,
                                      l_knee_flex=8 if s > 0 else 18,
                                      r_knee_flex=18 if s > 0 else 8,
                                      hips_drop_cm=3 if k % 2 == 0 else 4)))
    return keys


CLASP = 0.30, 1.45, DIST / 2 - 0.025

A = Role(
    base=STAND | HOLD_A,
    keys=_counts(+1),
    layers=[Breath(amp=0.8, period_s=2.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=(CLASP[0], CLASP[1], CLASP[2]), pole=(1.0, -1.0, -0.5)),
        PartnerTarget("r", "Spine1", (0.125, 0.13, -0.05), pole=(-1.0, -0.6, -0.1))],
)
B = Role(
    base=STAND | HOLD_B,
    keys=_counts(-1),
    layers=[Breath(amp=0.8, period_s=2.0)],
    ik=[FeetPlanted(),
        HandTarget("r", at=(-CLASP[0], CLASP[1], CLASP[2]), pole=(-1.0, -1.0, -0.5)),
        PartnerTarget("l", "Spine2", (-0.17, 0.16, 0.05), pole=(1.0, -0.6, -0.3))],
)

ANIM = PairAnimation(
    kind="dancing-together", duration_s=4.0, loop=True, distance_m=DIST, stagger_m=0.0,
    anchor_s=0.0,
    catalog=Catalog(
        label_de='Tanzen',
        key="dancing together", group="stand", repoint=True,
        prompt="a couple dancing salsa together in closed hold, one hand on the partner's back, "
               "the other hands clasped, hips swaying",
        synonyms=("miteinander tanzen", "salsa tanzen", "dancing salsa together")),
    a=A, b=B,
)
