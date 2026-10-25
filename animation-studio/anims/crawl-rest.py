"""Resting on hands and knees, looped: on all fours, the thighs vertical
under the hips, the shins and insteps on the floor behind, the arms straight
under the shoulders with the palms flat; a slow breath, a small shift of
weight from side to side and the head looking around a little.

The stop state of the movement type `crawl` (pose `crawling_rest`): a figure
that halts while crawling holds this instead of standing up.

Geometry (searched numerically on the compiled pose): the pelvis pitched
80 deg forward with the thighs held vertical (hip_flex = 80, body_pitch tilts
the legs along), knees bent 92 deg — the knee joints 1.9 cm over the floor,
the hip joints 48.7 cm, the shoulders 61 cm. The feet are plantar-flexed to
the limit and the toes curled up (toes_flex -30: on an upturned foot "toes
up" points them at the floor), so the instep hangs a few centimetres over
the floor and the knee is the lowest joint. The wrists sit 5.5 cm over the
floor slightly ahead of and outside the shoulders; wrist_flex -80 lays the
palm flat (knuckles 2 cm under the wrist).
"""
from animstudio.dsl import Animation, Breath, Catalog, HandTarget, Key, Pose
from animstudio.rig import RELAXED

PITCH = 80
FOURS = Pose(body_pitch=PITCH, l_hip_flex=PITCH, r_hip_flex=PITCH,
             l_knee_flex=92, r_knee_flex=92, l_ankle_flex=-50, r_ankle_flex=-50,
             l_toes_flex=-30, r_toes_flex=-30, hips_drop_cm=62.5, neck_flex=-40)
ARMS = Pose(l_arm_elev=-10, r_arm_elev=-10, l_arm_azim=80, r_arm_azim=80,
            l_elbow_flex=5, r_elbow_flex=5, l_wrist_flex=-80, r_wrist_flex=-80,
            l_fingers_curl=10, r_fingers_curl=10)
HAND_L, HAND_R = (0.17, 0.055, 0.40), (-0.17, 0.055, 0.40)

ANIM = Animation(
    kind="crawl-rest", duration_s=4.0, loop=True,
    catalog=Catalog(
        key="crawling_rest", group="ground",
        prompt="resting on hands and knees on the ground, arms straight under the shoulders, "
               "head raised, looking around",
        synonyms=("im vierfüßlerstand", "auf allen vieren innehalten", "on all fours",
                  "resting on hands and knees")),
    base=Pose(**RELAXED) | FOURS | ARMS,
    keys=[Key(0.0, Pose(body_roll=0.0, spine_tilt=0.0, neck_rot=0.0)),
          Key(1.0, Pose(body_roll=1.5, spine_tilt=-2.0, neck_rot=12.0)),
          Key(2.0, Pose(body_roll=0.0, spine_tilt=0.0, neck_rot=0.0)),
          Key(3.0, Pose(body_roll=-1.5, spine_tilt=2.0, neck_rot=-12.0))],
    layers=[Breath(amp=0.8, period_s=2.0)],
    ik=[HandTarget("l", at=HAND_L, pole=(0.3, 0.0, -1.0)),
        HandTarget("r", at=HAND_R, pole=(-0.3, 0.0, -1.0))],
)
