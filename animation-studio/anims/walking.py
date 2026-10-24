"""Walking, looped: an easy walk in place at 1.25 m/s — heel strike, roll
over the sole, push off from the ball, the swing foot lifted clear; the
hips sink at each double support, the pelvis turns with the legs and the
chest against it, the arms swing opposite to the legs, the head stays
level and looks ahead.

Replaces the CMU `walk` for the pose `walking`. One cycle (two steps) is
1.1 s. The foot paths come from ``animstudio.gait`` (belt speed =
``treadmill_mps``, so a planted ball stays on the moving floor); every
periodic value is keyed once per frame (exact at the frames, no easing
pauses between keys).

Arms: the wrist swings on an arc around the hanging position (rig wrist
at rest relaxed: x 26.3, y 100.6, z 0.7 cm) — 16 cm forward, 13 back, a
little higher and further in at the front.
"""
import math

from animstudio.dsl import Animation, Breath, Catalog, FootTarget, HandTarget, Key, Pose
from animstudio.gait import bob, gait
from animstudio.rig import RELAXED

T = 1.1
# the loop starts at the left foot's mid-contact (flat), the right in swing
PH = 0.3
SPEED = 1.25
G = gait(duration_s=T, speed_mps=SPEED, stance=0.6, heel_pitch=16, toe_pitch=-34, lift_cm=7,
         roll_in=0.12, roll_out=0.45, centre_cm=-8, knee_min_deg=5, phase=PH)
# deepest at double support: the left heel strikes at clip phase -PH
DROP = bob(G, low_phase=-PH, base_cm=2.0, margin_cm=1.5)

BASE = Pose(**RELAXED) | Pose(body_pitch=3, neck_flex=-3, l_arm_twist=15, r_arm_twist=15,
                              l_fingers_curl=25, r_fingers_curl=25)


def _frame(i: int, t: float) -> Pose:
    c = math.cos(2 * math.pi * (t / T + PH))          # +1: left foot forward
    roll = math.cos(2 * math.pi * (t / T + PH - 0.3))  # +1: left mid-stance
    return Pose(hips_drop_cm=DROP[i],
                body_yaw=-4.0 * c, spine_rot=7.0 * c, neck_rot=-3.0 * c,
                body_roll=-2.0 * roll, spine_tilt=2.5 * roll, neck_tilt=-0.5 * roll,
                l_toes_flex=G.toes["l"][i], r_toes_flex=G.toes["r"][i])


def _hand(side: str, t: float):
    # the left hand is forward when the right foot is (phase 0.5)
    c = math.cos(2 * math.pi * (t / T + PH)) * (-1.0 if side == "l" else 1.0)
    fwd = max(c, 0.0)
    sx = 1.0 if side == "l" else -1.0
    z = (0.007 + 0.16 * c) if c > 0 else (0.007 + 0.13 * c)
    return (sx * (0.25 - 0.03 * fwd), 1.0 + 0.035 * c * c + 0.02 * fwd, z)


ANIM = Animation(
    kind="walking", duration_s=T, loop=True, treadmill_mps=SPEED,
    catalog=Catalog(
        key="walking", group="stand", repoint=True,
        prompt="walking at an easy pace, arms swinging naturally, upright posture, "
               "looking ahead",
        synonyms=("laufen gehen", "schlendern", "strolling", "walking along")),
    base=BASE,
    keys=[Key(t, _frame(i, t), "linear") for i, t in enumerate(G.t)],
    layers=[Breath(amp=0.6, period_s=T)],
    ik=[FootTarget("l", at=tuple(zip(G.t, G.ankle["l"])), pitch=tuple(zip(G.t, G.pitch["l"])),
                   yaw=5),
        FootTarget("r", at=tuple(zip(G.t, G.ankle["r"])), pitch=tuple(zip(G.t, G.pitch["r"])),
                   yaw=5),
        HandTarget("l", at=tuple((t, _hand("l", t)) for t in G.t), pole=(0.4, -0.2, -1.0)),
        HandTarget("r", at=tuple((t, _hand("r", t)) for t in G.t), pole=(-0.4, -0.2, -1.0))],
)
