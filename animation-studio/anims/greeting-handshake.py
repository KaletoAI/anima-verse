"""Two people shake hands in greeting, once: reach out, clasp, three pumps,
let go.

Both halves do the same with their RIGHT hand. The pair stands with a
negative stagger (each a little to its own left), so the two right hands
meet right of each body's midline, as people really stand for a handshake.
The clasped hands sit side by side: the wrists 10 cm apart along the line
between the two (each palm reaches over the other's), each 2.5 cm to its own
right of the contact plane (the palms touch). Turned into each role's own
space that is the SAME point for both, so both roles share one hand path —
the pumps of the two hands are one movement.

Timeline (3.5 s, one-shot, ends standing face to face):
  0.00-0.90  the right hand rises from the side to the meeting point,
             a slight bow and nod
  0.90-2.10  clasp, three pumps (0.4 s each)
  2.10-2.50  hold
  2.50-3.20  let go, the hand back to the side
  3.20-3.50  settle
"""
from animstudio.dsl import Breath, Catalog, FeetPlanted, HandTarget, Key, PairAnimation, Pose, Role
from animstudio.rig import RELAXED

DISTANCE = 0.72
STAGGER = -0.14
#: The meeting point in each role's own space (metres): right of the
#: midline by -STAGGER/2 + 2.5 cm, 5 cm short of the middle between the two.
MEET = (STAGGER / 2 - 0.025, 1.18, DISTANCE / 2 - 0.05)
#: The relaxed hanging hand (RELAXED arms; measured on the rest rig).
SIDE = (-0.263, 0.996, 0.007)


def _hand_path():
    x, y, z = MEET
    pumps = []
    for i in range(3):
        t = 1.0 + 0.4 * i
        pumps += [(t + 0.1, (x, y + 0.035, z)), (t + 0.3, (x, y - 0.035, z))]
    return ([(0.0, SIDE), (0.35, (-0.22, 1.06, 0.15)), (0.9, MEET)] + pumps
            + [(2.2, MEET), (2.5, MEET), (2.85, (-0.22, 1.06, 0.15)), (3.2, SIDE)])


STAND = Pose(**RELAXED) | Pose(l_hip_abduct=4, r_hip_abduct=4, hips_drop_cm=1)
# The twist and wrist values stand the hand upright, thumb up, palm towards
# the partner's palm (searched numerically on the clasp frame).
REACH = Pose(r_arm_elev=-55, r_arm_azim=55, r_elbow_flex=55,
             r_arm_twist=30, r_wrist_twist=30, r_wrist_flex=-20,
             r_fingers_curl=25, r_thumb_curl=10)
CLASP = Pose(r_fingers_curl=45, r_thumb_curl=30, body_pitch=2, spine_flex=4, neck_flex=8)
BACK = Pose(r_arm_elev=-75, r_arm_azim=0, r_elbow_flex=10, r_arm_twist=0, r_wrist_twist=0,
            r_wrist_flex=0, r_fingers_curl=15, r_thumb_curl=0,
            body_pitch=0, spine_flex=0, neck_flex=0)


def _role(delay):
    return Role(
        base=STAND,
        keys=[Key(0.0, Pose()),
              Key(0.6, REACH),
              Key(0.95, CLASP),
              Key(1.3 + delay, Pose(neck_flex=12)),
              Key(2.1, Pose(neck_flex=4)),
              Key(2.5, Pose(r_fingers_curl=40)),
              Key(3.2, BACK)],
        layers=[Breath(amp=1.0, period_s=3.5)],
        ik=[FeetPlanted(),
            HandTarget("r", at=_hand_path(), pole=(-0.4, -1.0, -0.3))],
    )


ANIM = PairAnimation(
    kind="greeting-handshake", duration_s=3.5, loop=False,
    distance_m=DISTANCE, stagger_m=STAGGER, anchor_s=1.5,
    catalog=Catalog(
        label_de='Händedruck',
        key="greeting handshake",
        group="stand",
        prompt="two people shaking hands in greeting, standing face to face, right hands "
               "clasped, a slight nod, friendly eye contact",
        synonyms=("handshake", "shake hands", "händeschütteln", "hände schütteln",
                  "die hand geben", "begrüßung per handschlag", "sich die hand geben",
                  "jemandem die hand schütteln", "hand geben", "handschlag",
                  "zur begrüßung die hand geben", "shaking hands in greeting",
                  "greet with a handshake"),
        take_over=("handshake", "shake hands", "händeschütteln", "hände schütteln",
                   "die hand geben", "begrüßung per handschlag", "sich die hand geben",
                   "jemandem die hand schütteln")),
    a=_role(0.0), b=_role(0.1),
)
