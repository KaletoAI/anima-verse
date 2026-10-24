"""Two people hug in greeting, once: lean in, embrace, two pats, let go.

Both halves hold the classic "one over, one under" embrace, which is
the same for both bodies: the RIGHT arm goes high over the partner's left
shoulder onto the upper back, the LEFT arm goes low under the partner's
right arm around the lower back, and each head turns to its own right,
over the partner's left shoulder. The two heads end up on opposite sides.
A pats twice with its high hand; B only squeezes a little tighter.

Timeline (4.0 s, one-shot, ends standing face to face):
  0.00-0.95  lean in, arms rise; the hand goals fade in from 0.35 s
  0.95-2.85  embrace, sway; A pats at 1.5 s and 1.9 s
  2.85-3.70  let go: goals fade out by 3.5 s, lean back, arms down
  3.70-4.00  settle
The hips stand ``distance_m`` = 0.48 m apart, so the toes stay clear
(toe tip about 20 cm in front of the ankle). The chests meet through the
lean: body_pitch 6 + spine_flex 16 at the embrace.
"""
from animstudio.dsl import (Breath, Catalog, FeetPlanted, Key, PairAnimation, PartnerTarget,
                            Pose, Role)
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=4, r_hip_abduct=4, hips_drop_cm=1)

LEAN = Pose(body_pitch=6, spine_flex=18, hips_drop_cm=3, neck_flex=4)
HEAD = Pose(neck_rot=-35, neck_tilt=-8)
# The arms open first, then wrap: the DOF shapes stay near the goals, so the
# IK only corrects and never swings an arm through the partner.
OPEN = Pose(r_arm_elev=5, r_arm_azim=40, r_elbow_flex=35, r_arm_twist=20,
            l_arm_elev=-30, l_arm_azim=35, l_elbow_flex=35, l_arm_twist=20,
            l_fingers_curl=8, r_fingers_curl=8, body_pitch=3, spine_flex=8, neck_flex=2)
ARMS = Pose(r_arm_elev=20, r_arm_azim=75, r_elbow_flex=95, r_arm_twist=-20,
            l_arm_elev=-35, l_arm_azim=65, l_elbow_flex=85, l_arm_twist=10,
            l_fingers_curl=10, r_fingers_curl=10,
            # the hands lie flat on the back instead of going on past it
            # (searched numerically against the partner's torso frame)
            l_wrist_flex=45, l_wrist_dev=30, r_wrist_dev=20)
EMBRACE = LEAN | HEAD | ARMS
LET_GO = Pose(body_pitch=0, spine_flex=0, hips_drop_cm=1, neck_flex=0, neck_rot=0,
              neck_tilt=0, r_arm_elev=-75, r_arm_azim=0, r_elbow_flex=10, r_arm_twist=0,
              l_arm_elev=-75, l_arm_azim=0, l_elbow_flex=10, l_arm_twist=0,
              l_fingers_curl=15, r_fingers_curl=15,
              l_wrist_flex=0, l_wrist_dev=0, r_wrist_dev=0)

#: Partner-body points (metres, the partner's torso frame — x its left,
#: z its front). The high hand: from above the partner's left shoulder,
#: behind it, onto the upper back at the spine. The low hand: from beside
#: the partner's right flank, behind it, onto the lower back.
HIGH_OUT, HIGH_MID, HIGH = (0.30, 0.20, 0.08), (0.18, 0.17, -0.12), (0.06, 0.10, -0.14)
LOW_OUT, LOW_MID, LOW = (-0.24, 0.02, 0.06), (-0.21, 0.03, -0.10), (-0.10, 0.02, -0.11)
POLE_HIGH = (-1.0, 0.4, 0.6)
POLE_LOW = (1.0, -0.3, -0.1)


def _path(out, mid, home, t0, t1, extra=()):
    """In along out -> mid -> home from t0 (home at t0 + 0.75, after the
    lean has closed the gap), out again the same way from t1."""
    return ([(t0, out), (t0 + 0.45, mid), (t0 + 0.75, home)] + list(extra)
            + [(t1, home), (t1 + 0.25, mid), (t1 + 0.5, out)])


def _pat(t):
    """Off the back and down again, 0.3 s."""
    off = (HIGH[0], HIGH[1], HIGH[2] - 0.06)
    return [(t, HIGH), (t + 0.15, off), (t + 0.3, HIGH)]


def _goals(t0, t1, pats=()):
    span = (t0, t1 + 0.65)
    extra = [k for t in pats for k in _pat(t)]
    return [FeetPlanted(),
            PartnerTarget("r", "Spine2", _path(HIGH_OUT, HIGH_MID, HIGH, t0, t1, extra),
                          span=span, pole=POLE_HIGH, fade_s=0.6),
            PartnerTarget("l", "Spine", _path(LOW_OUT, LOW_MID, LOW, t0, t1),
                          span=span, pole=POLE_LOW, fade_s=0.35)]


A = Role(
    base=STAND,
    keys=[Key(0.0, Pose()),
          Key(0.5, OPEN),
          Key(1.0, EMBRACE),
          Key(1.9, Pose(spine_tilt=3)),
          Key(2.85, Pose(spine_tilt=-2)),
          Key(3.75, LET_GO | Pose(spine_tilt=0))],
    layers=[Breath(amp=1.0, period_s=4.0)],
    ik=_goals(0.35, 2.85, pats=(1.45, 1.85)),
)

B = Role(
    base=STAND,
    keys=[Key(0.0, Pose()),
          Key(0.55, OPEN),
          Key(1.1, EMBRACE),
          Key(1.9, Pose(spine_tilt=-3, l_elbow_flex=95, r_elbow_flex=105)),
          Key(2.9, Pose(spine_tilt=2)),
          Key(3.8, LET_GO | Pose(spine_tilt=0))],
    layers=[Breath(amp=1.0, period_s=4.0)],
    ik=_goals(0.4, 2.9),
)

ANIM = PairAnimation(
    kind="greeting-hug", duration_s=4.0, loop=False, distance_m=0.40, stagger_m=0.14, anchor_s=1.8,
    catalog=Catalog(
        label_de='Umarmung',
        key="hugging",
        group="stand",
        prompt="two people hugging in greeting, arms wrapped around each other, "
               "one arm over the shoulder and one around the waist, heads side by side, "
               "warm smiles",
        synonyms=("hug", "hugging", "embrace", "hug hello", "greeting hug",
                  "umarmen", "umarmung", "jemanden umarmen", "eine umarmung",
                  "in den arm nehmen", "zur begrüßung umarmen", "umarmt",
                  "sich umarmen", "fest umarmen"),
        take_over=("umarmen", "jemanden umarmen", "eine umarmung", "in den arm nehmen")),
    a=A, b=B,
)
