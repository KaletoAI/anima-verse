"""Casting a spell, looped (3.0 s per cast): a planted, slightly wide stance;
the hands gather energy in front of the chest as if cupping a glowing ball,
draw it in close, then thrust both arms forward with open palms to release
it, hold the push for a beat and sink back to the ready stance.

Replaces the CMU take 12_04 under the SAME kind `spell_casting` — the kind
the worlds' pose layers already name, so nothing has to be re-pointed.

Timing: 0.0 ready (hands low in front of the belly) -> 0.8 gather (wrists
26 cm in front of the chest at 1.30 m, palms facing each other) -> 1.25
charge (drawn in to 20 cm, slight crouch, head down to the hands) -> 1.55
release (wrists 44 cm out at 1.45 m, palms forward, fingers spread, chest
forward) -> 1.95 the push held -> 2.5 hands sinking -> 3.0 = 0.0.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=8, r_hip_abduct=8, hips_drop_cm=2,
                               l_fingers_curl=20, r_fingers_curl=20)

READY_L, READY_R = (0.15, 1.02, 0.16), (-0.15, 1.02, 0.16)
GATHER_L, GATHER_R = (0.08, 1.30, 0.26), (-0.08, 1.30, 0.26)
CHARGE_L, CHARGE_R = (0.07, 1.31, 0.20), (-0.07, 1.31, 0.20)
PUSH_L, PUSH_R = (0.11, 1.38, 0.48), (-0.11, 1.38, 0.48)
HOLD_L, HOLD_R = (0.12, 1.37, 0.46), (-0.12, 1.37, 0.46)
SINK_L, SINK_R = (0.15, 1.15, 0.24), (-0.15, 1.15, 0.24)

READY = Pose(spine_flex=0, neck_flex=0, hips_drop_cm=2,
             l_arm_twist=0, r_arm_twist=0, l_wrist_flex=0, r_wrist_flex=0,
             l_wrist_twist=0, r_wrist_twist=0, l_wrist_dev=0, r_wrist_dev=0,
             l_fingers_curl=20, r_fingers_curl=20, l_thumb_curl=0, r_thumb_curl=0)
GATHER = Pose(neck_flex=14, spine_flex=4,
              l_arm_twist=15, r_arm_twist=15, l_wrist_flex=-30, r_wrist_flex=-30,
              l_wrist_dev=20, r_wrist_dev=20,
              l_fingers_curl=40, r_fingers_curl=40, l_thumb_curl=25, r_thumb_curl=25)
CHARGE = Pose(neck_flex=12, spine_flex=7, hips_drop_cm=6,
              l_fingers_curl=45, r_fingers_curl=45)
PUSH = Pose(neck_flex=-6, spine_flex=8, hips_drop_cm=4,
            l_arm_twist=-60, r_arm_twist=-60, l_wrist_twist=-20, r_wrist_twist=-20,
            l_wrist_flex=-80, r_wrist_flex=-80, l_wrist_dev=0, r_wrist_dev=0,
            l_fingers_curl=0, r_fingers_curl=0, l_thumb_curl=0, r_thumb_curl=0)

ANIM = Animation(
    kind="spell_casting", duration_s=3.0, loop=True,
    catalog=Catalog(
        key="casting a spell", group="stand",
        prompt="standing in a firm stance, both arms thrust forward with open palms, "
               "releasing a spell, focused gaze",
        synonyms=("zaubern", "zaubert", "einen zauber wirken", "wirkt einen zauber",
                  "zauberspruch sprechen", "casting a spell", "casts a spell",
                  "spellcasting", "using magic")),
    base=STAND,
    keys=[Key(0.0, READY),
          Key(0.8, GATHER),
          Key(1.25, CHARGE),
          Key(1.65, PUSH),
          Key(2.0, Pose(spine_flex=6, l_wrist_flex=-78, r_wrist_flex=-78)),
          Key(2.5, Pose(neck_flex=6, spine_flex=2, hips_drop_cm=3,
                        l_arm_twist=-20, r_arm_twist=-20, l_wrist_twist=-5, r_wrist_twist=-5,
                        l_wrist_flex=-15, r_wrist_flex=-15,
                        l_fingers_curl=15, r_fingers_curl=15))],
    layers=[Breath(amp=1.0, period_s=3.0)],
    ik=[FeetPlanted(),
        HandTarget("l", at=((0.0, READY_L), (0.8, GATHER_L), (1.25, CHARGE_L),
                            (1.65, PUSH_L), (2.0, HOLD_L), (2.5, SINK_L)),
                   pole=(1.0, -1.0, -0.3)),
        HandTarget("r", at=((0.0, READY_R), (0.8, GATHER_R), (1.25, CHARGE_R),
                            (1.65, PUSH_R), (2.0, HOLD_R), (2.5, SINK_R)),
                   pole=(-1.0, -1.0, -0.3))],
)
