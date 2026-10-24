"""Thinking while standing, looped: the left forearm across the belly
holding the right elbow, the right hand at the chin, the head tilted and
the gaze going up and aside; the index finger taps the chin twice, the
weight shifts from one leg to the other.

Replaces `idle` for the pose `thinking`. The chin: the rig's Head joint
sits at 1.70 m, the chin about 9 cm in front of it and 3 cm lower. The
right wrist target is placed so the knuckles of the curled hand land on
it (measured on the compiled pose: wrist (-0.118, 1.632, 0.081)).
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, HandTarget, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5, hips_drop_cm=1)
ARMS = Pose(r_arm_elev=-55, r_arm_azim=55, r_elbow_flex=135, r_arm_twist=40,
            r_wrist_flex=35, r_fingers_curl=60, r_thumb_curl=30,
            l_arm_elev=-65, l_arm_azim=60, l_elbow_flex=95, l_arm_twist=10,
            l_fingers_curl=40)
CHIN_WRIST = (-0.118, 1.632, 0.081)
BELLY = (-0.11, 1.20, 0.16)          # the left hand under the right elbow

ANIM = Animation(
    kind="thinking", duration_s=8.0, loop=True,
    catalog=Catalog(
        key="thinking", group="stand", repoint=True,
        prompt="standing deep in thought, one hand on the chin, the other arm across the body, "
               "head tilted, looking up",
        synonyms=("überlegen", "überlegt", "hand am kinn", "pondering", "lost in thought")),
    base=STAND | ARMS | Pose(neck_tilt=8, neck_rot=-10, neck_flex=-6),
    keys=[Key(0.0, Pose(neck_rot=-10, neck_flex=-6, spine_tilt=0, r_fingers_curl=60)),
          Key(2.0, Pose(neck_rot=-16, neck_flex=-10, spine_tilt=1.5)),
          Key(3.0, Pose(r_fingers_curl=40)),
          Key(3.3, Pose(r_fingers_curl=60)),
          Key(3.6, Pose(r_fingers_curl=40)),
          Key(3.9, Pose(r_fingers_curl=60)),
          Key(5.0, Pose(neck_rot=-4, neck_flex=2, spine_tilt=-1.5)),
          Key(6.5, Pose(neck_rot=-8, neck_flex=-4, spine_tilt=0))],
    layers=[Breath(amp=0.9, period_s=4.0)],
    ik=[FeetPlanted(),
        HandTarget("r", at=CHIN_WRIST, pole=(-0.6, -1.0, 0.3)),
        HandTarget("l", at=BELLY, pole=(1.0, -0.6, -0.2))],
)
