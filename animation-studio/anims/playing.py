"""Fooling around, looped: bouncing on the spot to a silly rhythm — knees
springing, arms flapping out and in, a wiggle of the hips, a shoulder
shimmy, the head bobbing; a big goofy arm wave at the end of the phrase.

Replaces `idle` for the pose `playing` ("herumtoben", "herumalbern"). The
feet stay planted (clips play in place); the bounce is the knees and
hips_drop_cm.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=8, r_hip_abduct=8, hips_drop_cm=2,
                               l_fingers_curl=10, r_fingers_curl=10)
DOWN = Pose(hips_drop_cm=8, l_knee_flex=22, r_knee_flex=22, l_hip_flex=12, r_hip_flex=12)
UP = Pose(hips_drop_cm=2, l_knee_flex=4, r_knee_flex=4, l_hip_flex=2, r_hip_flex=2)
FLAP_OUT = Pose(l_arm_elev=-25, r_arm_elev=-25, l_arm_azim=15, r_arm_azim=15,
                l_elbow_flex=70, r_elbow_flex=70)
FLAP_IN = Pose(l_arm_elev=-55, r_arm_elev=-55, l_arm_azim=20, r_arm_azim=20,
               l_elbow_flex=90, r_elbow_flex=90)
WAVE = Pose(l_arm_elev=70, r_arm_elev=70, l_arm_azim=5, r_arm_azim=5,
            l_elbow_flex=15, r_elbow_flex=15)      # a V over the shoulders (90 = straight up)

KEYS = []
for k in range(6):
    t = 0.4 * k
    s = 1 if k % 2 == 0 else -1
    KEYS.append(Key(t, DOWN | FLAP_OUT | Pose(body_roll=2.5 * s, spine_tilt=-4 * s,
                                              neck_tilt=6 * s, spine_rot=6 * s)))
    KEYS.append(Key(t + 0.2, UP | FLAP_IN | Pose(body_roll=0, spine_tilt=0, neck_tilt=0,
                                                 spine_rot=0)))
SIDE = Pose(l_arm_elev=15, r_arm_elev=15, l_arm_azim=-5, r_arm_azim=-5,
            l_elbow_flex=10, r_elbow_flex=10)   # up and down past the shoulders, not the face
KEYS += [Key(2.5, UP | SIDE),
         Key(2.8, DOWN | WAVE | Pose(spine_tilt=5, neck_tilt=-6)),
         Key(3.1, UP | WAVE | Pose(spine_tilt=-5, neck_tilt=6, l_elbow_flex=25, r_elbow_flex=5)),
         Key(3.4, DOWN | WAVE | Pose(spine_tilt=5, neck_tilt=-6)),
         Key(3.75, UP | SIDE | Pose(spine_tilt=0, neck_tilt=0)),
         Key(4.1, UP | FLAP_IN)]

ANIM = Animation(
    kind="playing", duration_s=4.4, loop=True,
    catalog=Catalog(
        key="playing", group="stand", repoint=True,
        prompt="fooling around, bouncing on the spot with flapping arms and a goofy grin",
        synonyms=("rumalbern", "quatsch machen", "fooling around", "goofing around")),
    base=STAND,
    keys=KEYS,
    layers=[Breath(amp=1.2, period_s=2.2)],
    ik=[FeetPlanted()],
)
