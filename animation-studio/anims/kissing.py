"""Two people kiss, once: step into each other's arms, kiss, part.

A puts both hands on B's waist; B lays both arms over A's shoulders, the
hands crossed behind A's neck. Both lean in, each head tilts and turns a
little to its own right, so the noses pass on opposite sides and the lips
meet in the middle.

Timeline (5.0 s, one-shot, ends standing face to face):
  0.00-0.90  arms rise; the hand goals fade in from 0.2 / 0.3 s
  0.90-1.60  lean in, heads tilt; the hands arrive only after the lean
             has closed the gap (out -> mid -> home over 1.1 s)
  1.60-3.40  the kiss, a slow sway
  3.40-4.10  heads part, lean back; the goals fade out by 4.5 s
  4.10-5.00  hands down, settle
The hips stand 0.44 m apart (toe tips about 7 cm clear). The heads stay
upright through the lean (neck_flex cancels it), so the crowns stay apart
(head centres about 22 cm) while the mouths meet; the head tilt to the own
right is countered by a turn to the own left, so the mouths line up.
"""
from animstudio.dsl import (Breath, Catalog, FeetPlanted, Key, PairAnimation, PartnerTarget,
                            Pose, Role)
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=4, r_hip_abduct=4, hips_drop_cm=1)

LEAN = Pose(body_pitch=5, spine_flex=10, hips_drop_cm=2, neck_flex=-12)
HEAD = Pose(neck_rot=14, neck_tilt=-24)
# A: both hands at the partner's waist.
WAIST = Pose(r_arm_elev=-45, r_arm_azim=35, r_elbow_flex=70, r_arm_twist=10,
             l_arm_elev=-45, l_arm_azim=35, l_elbow_flex=70, l_arm_twist=10,
             l_fingers_curl=10, r_fingers_curl=10)
# B: both arms over the partner's shoulders.
NECK = Pose(r_arm_elev=15, r_arm_azim=60, r_elbow_flex=90, r_arm_twist=-10,
            l_arm_elev=15, l_arm_azim=60, l_elbow_flex=90, l_arm_twist=-10,
            l_fingers_curl=15, r_fingers_curl=15)
PART = Pose(neck_rot=0, neck_tilt=0, neck_flex=2, body_pitch=1, spine_flex=3)
LET_GO = Pose(body_pitch=0, spine_flex=0, hips_drop_cm=1, neck_flex=0,
              r_arm_elev=-75, r_arm_azim=0, r_elbow_flex=10, r_arm_twist=0,
              l_arm_elev=-75, l_arm_azim=0, l_elbow_flex=10, l_arm_twist=0,
              l_fingers_curl=15, r_fingers_curl=15)

#: Partner-body points (metres, partner torso frame: x its left, z its
#: front). ``s`` = +1 for a right hand (the partner's left side), -1 left.
def _waist(s):
    return (s * 0.26, 0.00, 0.14), (s * 0.18, 0.02, 0.04), (s * 0.135, 0.03, -0.02)


def _neck(s):
    return (s * 0.30, 0.02, 0.12), (s * 0.20, 0.02, -0.02), (s * 0.06, 0.05, -0.08)


def _path(points, t0, t1):
    out, mid, home = points
    return [(t0, out), (t0 + 0.6, mid), (t0 + 1.1, home),
            (t1, home), (t1 + 0.25, mid), (t1 + 0.5, out)]


def _hands(bone, points, t0, t1, poles):
    return [PartnerTarget(side, bone, _path(points(s), t0, t1), span=(t0, t1 + 0.6),
                          pole=pole, fade_s=0.4)
            for side, s, pole in (("r", 1, poles[0]), ("l", -1, poles[1]))]


A = Role(
    base=STAND,
    keys=[Key(0.0, Pose()),
          Key(0.8, WAIST),
          Key(1.6, LEAN | HEAD),
          Key(2.5, Pose(spine_tilt=2)),
          Key(3.4, Pose(spine_tilt=-1)),
          Key(4.1, PART | Pose(spine_tilt=0)),
          Key(4.9, LET_GO)],
    layers=[Breath(amp=1.0, period_s=5.0)],
    ik=[FeetPlanted()] + _hands("Spine", _waist, 0.2, 3.9,
                                ((-0.6, -1.0, -0.3), (0.6, -1.0, -0.3))),
)

B = Role(
    base=STAND,
    keys=[Key(0.0, Pose()),
          Key(0.9, NECK),
          Key(1.6, LEAN | HEAD),
          Key(2.4, Pose(spine_tilt=-2, hips_drop_cm=1)),
          Key(3.4, Pose(spine_tilt=1, hips_drop_cm=2)),
          Key(4.1, PART | Pose(spine_tilt=0)),
          Key(4.9, LET_GO)],
    layers=[Breath(amp=1.0, period_s=5.0)],
    ik=[FeetPlanted()] + _hands("Neck", _neck, 0.3, 3.9,
                                ((-1.0, -0.2, 0.3), (1.0, -0.2, 0.3))),
)

ANIM = PairAnimation(
    kind="kissing", duration_s=5.0, loop=False, distance_m=0.44, stagger_m=0.0, anchor_s=2.5,
    catalog=Catalog(
        key="kissing",
        group="stand",
        prompt="two people kissing, standing close, one with hands on the other's waist, "
               "the other with arms around the partner's neck, eyes closed",
        synonyms=("kiss", "kissing", "kiss each other", "a kiss", "romantic kiss",
                  "küssen", "kuss", "sich küssen", "einen kuss geben", "jemanden küssen",
                  "küsst", "ein kuss", "innig küssen")),
    a=A, b=B,
)
