"""Taking a bath, looped: sitting in the tub with the knees drawn up, the
back leaning a little against the end, the left forearm lying across the
knees while the right hand washes that forearm with a cloth — elbow
to wrist and back — then pours a scoop of water over it.

Replaces the CMU clip `standing wash-self` for the pose `bathing` (that clip
stays with `showering`): a bath is taken sitting, so the pose moves to the
place type `ground` — the figure sits on the floor of whatever it stands
in, inside a tub model that is the tub's floor.

Seat (searched numerically): hip_flex 130, knee_flex 115, ankle -10 with
the pelvis tilted back 12 deg puts the soles flat on the floor 48-70 cm in
front of the hips, the knees 48 cm high; hips_drop_cm 90 leaves the hip
joints 10 cm over the floor, the sitting bones on it.
"""
from animstudio.dsl import Animation, Breath, Catalog, HandTarget, Key, Pose
from animstudio.rig import RELAXED

SEAT = Pose(l_hip_flex=130, r_hip_flex=130, l_knee_flex=115, r_knee_flex=115,
            l_ankle_flex=-10, r_ankle_flex=-10, l_hip_abduct=8, r_hip_abduct=8,
            hips_drop_cm=90, body_pitch=-12, spine_flex=10, neck_flex=8)
ARMS = Pose(l_arm_elev=-35, l_arm_azim=55, l_elbow_flex=60, l_arm_twist=20,
            r_arm_elev=-30, r_arm_azim=80, r_elbow_flex=100, r_arm_twist=-10,
            l_fingers_curl=20, r_fingers_curl=55, r_thumb_curl=40)

KNEE_L = (0.08, 0.53, 0.34)                     # left wrist across the knees
#: On top of the left forearm, which lies across the knees from the elbow
#: (0.249, 0.500, 0.125) to the wrist (0.08, 0.53, 0.34): 45 % and 85 %
#: along it, 4 cm over its axis — the right hand reaches it in front of the
#: belly, elbow down.
ARM_TOP, ARM_LOW = (0.173, 0.554, 0.222), (0.105, 0.566, 0.308)
RINSE = (0.12, 0.70, 0.24)                      # a scoop of water poured over the arm

ANIM = Animation(
    kind="bathing", duration_s=6.0, loop=True,
    catalog=Catalog(
        key="bathing", group="ground", repoint=True,
        prompt="sitting in a bathtub with the knees drawn up, washing one forearm with a cloth, "
               "relaxed, steam rising",
        synonyms=("in der badewanne sitzen", "in der wanne", "badet in der wanne",
                  "taking a bath", "in the bathtub")),
    base=Pose(**RELAXED) | SEAT | ARMS,
    keys=[Key(0.0, Pose(neck_rot=10)), Key(3.0, Pose(neck_rot=4)), Key(4.5, Pose(neck_rot=14))],
    layers=[Breath(amp=1.0, period_s=3.0)],
    ik=[HandTarget("l", at=KNEE_L, pole=(1.0, -0.4, -0.5)),
        HandTarget("r", at=((0.0, ARM_TOP), (0.8, ARM_LOW), (1.6, ARM_TOP), (2.4, ARM_LOW),
                            (3.2, ARM_TOP), (4.2, RINSE), (5.2, RINSE)),
                   pole=(-0.5, -1.0, 0.3))],
)
