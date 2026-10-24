"""Running, looped: an easy jog in place at 2.6 m/s — a midfoot landing,
a short flight, the heel kicked up behind in the swing; the body leans a
little forward and bounces (deepest at mid-stance), the bent arms pump
opposite to the legs, the head looks ahead.

Replaces the CMU `run` for the pose `running`. One cycle (two steps) is
0.7 s (cadence 171). The foot paths come from ``animstudio.gait`` (belt
speed = ``treadmill_mps``); the flight is kept to about one frame per step
so a foot is always near the floor (``stand_contact``), and the foot comes
down onto the floor (``land_cm_s``) instead of gliding in. Every periodic
value is keyed once per frame.

Arms: elbows at about 90 degrees; the wrist swings from 26 cm in front at
chest height (in towards the midline) to 13 cm behind at the hip.
"""
import math

from animstudio.dsl import Animation, Breath, Catalog, FootTarget, HandTarget, Key, Pose
from animstudio.gait import bob, gait
from animstudio.rig import RELAXED

T = 0.7
STANCE = 0.46
# the loop starts at the left foot's mid-contact (flat), the right in swing
PH = STANCE / 2
SPEED = 2.6
G = gait(duration_s=T, speed_mps=SPEED, stance=STANCE, heel_pitch=4, toe_pitch=-32, lift_cm=24,
         roll_in=0.15, roll_out=0.45, centre_cm=-4, knee_min_deg=15, phase=PH, land_cm_s=60)
# deepest at mid-stance (clip phase 0 and 0.5)
DROP = bob(G, low_phase=0.0, base_cm=7.5, amp_cm=4.0)

BASE = Pose(**RELAXED) | Pose(body_pitch=6, spine_flex=2, neck_flex=-8,
                              l_elbow_flex=90, r_elbow_flex=90, l_arm_twist=30, r_arm_twist=30,
                              l_fingers_curl=55, r_fingers_curl=55, l_thumb_curl=30,
                              r_thumb_curl=30)


def _frame(i: int, t: float) -> Pose:
    c = math.cos(2 * math.pi * (t / T + PH))                   # +1: left foot forward
    roll = math.cos(2 * math.pi * (t / T + PH - STANCE / 2))   # +1: left mid-stance
    return Pose(hips_drop_cm=DROP[i],
                body_yaw=-5.0 * c, spine_rot=9.0 * c, neck_rot=-4.0 * c,
                body_roll=-2.0 * roll, spine_tilt=2.5 * roll, neck_tilt=-0.5 * roll,
                l_toes_flex=G.toes["l"][i], r_toes_flex=G.toes["r"][i])


def _hand(side: str, t: float):
    # the left hand is forward when the right foot is
    c = math.cos(2 * math.pi * (t / T + PH)) * (-1.0 if side == "l" else 1.0)
    fwd, back = max(c, 0.0), max(-c, 0.0)
    sx = 1.0 if side == "l" else -1.0
    return (sx * (0.19 - 0.06 * fwd + 0.03 * back),
            1.20 + 0.08 * fwd - 0.08 * back,
            0.06 + 0.20 * fwd - 0.19 * back)


ANIM = Animation(
    kind="running", duration_s=T, loop=True, treadmill_mps=SPEED,
    catalog=Catalog(
        key="running", group="stand", repoint=True,
        prompt="jogging at an easy pace, arms bent and swinging, leaning slightly forward, "
               "athletic stride",
        synonyms=("joggen gehen", "dauerlauf", "jogging along")),
    base=BASE,
    keys=[Key(t, _frame(i, t), "linear") for i, t in enumerate(G.t)],
    layers=[Breath(amp=0.8, period_s=T)],
    ik=[FootTarget("l", at=tuple(zip(G.t, G.ankle["l"])), pitch=tuple(zip(G.t, G.pitch["l"])),
                   yaw=4),
        FootTarget("r", at=tuple(zip(G.t, G.ankle["r"])), pitch=tuple(zip(G.t, G.pitch["r"])),
                   yaw=4),
        HandTarget("l", at=tuple((t, _hand("l", t)) for t in G.t), pole=(0.5, -0.3, -1.0)),
        HandTarget("r", at=tuple((t, _hand("r", t)) for t in G.t), pole=(-0.5, -0.3, -1.0))],
)
