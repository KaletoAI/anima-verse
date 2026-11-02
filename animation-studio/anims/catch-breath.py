"""Catching breath standing, looped: bent forward after an effort, the hands
braced on the thighs just above the knees, the knees soft, breathing hard —
the back heaves with every breath, the head drops and comes up again to look
ahead, once per cycle a deeper breath straightens the back a little.

The follow pose after a dance or an effort (plan-folge-pose.md, F4): the
pose `catching breath` (group `stand`), which `dancing` names as its
`follow_pose`.

Geometry, searched numerically on the reference rig (forward kinematics,
pelvis pitched 55 deg): hip_flex 92 and knee_flex 52 with the hips 18.3 cm
lower put the ankle 3 cm in front of the hips at its rest height and the
knee 18 cm in front at 52 cm — the hips pushed back over the feet, the
knees forward; ankle_flex 14 lays the toes on the floor (y 0). The spine
curls 26..33 deg: the shoulders sit at 1.08..1.11 m, 0.37 m in front of the
hips. The wrists rest 12 cm up the thigh from the knee and 8 cm off its
axis (0.149, 0.658, 0.173), 47..50 cm from the shoulder — inside the arm's
~55 cm reach in every key.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

PITCH = 55
LEGS = Pose(l_hip_flex=92, r_hip_flex=92, l_knee_flex=52, r_knee_flex=52,
            l_ankle_flex=14, r_ankle_flex=14,
            l_hip_abduct=8, r_hip_abduct=8, l_hip_rot=6, r_hip_rot=6, hips_drop_cm=18.3)
BEND = Pose(body_pitch=PITCH, spine_flex=30, neck_flex=-30)
ARMS = Pose(l_arm_elev=-60, r_arm_elev=-60, l_arm_azim=50, r_arm_azim=50,
            l_elbow_flex=15, r_elbow_flex=15, l_fingers_curl=25, r_fingers_curl=25)

#: The wrists on the thighs above the knees (metres, clip space).
HAND_L, HAND_R = (0.149, 0.658, 0.173), (-0.149, 0.658, 0.173)

ANIM = Animation(
    kind="catch-breath", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="catching breath", group="stand",
        prompt="standing bent forward, out of breath, hands braced on the thighs above the knees, "
               "flushed face, breathing hard",
        synonyms=("durchatmen", "außer atem", "luft holen", "out of breath",
                  "catching breath"),
        take_over=("catching breath",),
        label_de="Durchatmen"),
    base=Pose(**RELAXED) | LEGS | BEND | ARMS,
    keys=[Key(0.0, Pose(neck_flex=-30, spine_flex=30)),
          Key(1.2, Pose(neck_flex=-10, spine_flex=33)),
          Key(2.4, Pose(neck_flex=-34, spine_flex=29)),
          # the deeper breath: the back straightens a little, the head comes up
          Key(3.6, Pose(neck_flex=-38, spine_flex=26)),
          Key(4.8, Pose(neck_flex=-14, spine_flex=32))],
    layers=[Breath(amp=2.8, period_s=1.5)],
    ik=[FeetPlanted(),
        HandTarget("l", at=HAND_L, pole=(0.8, 0.0, -0.6)),
        HandTarget("r", at=HAND_R, pole=(-0.8, 0.0, -0.6))],
)
