"""Standing, looped: a relaxed stand — the arms hang loose, the weight
moves from one leg to the other and back (the unloaded knee softens, the
pelvis tips toward the loaded side, the chest answers the other way), the
head looks about a little; a slow breath over everything.

Replaces the CMU `idle` for the pose `standing`.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Oscillator, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5, l_hip_rot=6, r_hip_rot=6,
                               hips_drop_cm=1, l_arm_twist=10, r_arm_twist=10,
                               l_arm_azim=4, r_arm_azim=4)
# weight on the LEFT leg: the right knee softens, the pelvis tips to the
# left (body_roll +), the chest leans back right, the left arm hangs a
# little further out
LEFT = Pose(body_roll=1.6, spine_tilt=-2.4, r_knee_flex=9, l_knee_flex=1, hips_drop_cm=1.6,
            neck_tilt=1.0)
RIGHT = Pose(body_roll=-1.6, spine_tilt=2.4, l_knee_flex=9, r_knee_flex=1, hips_drop_cm=1.6,
             neck_tilt=-1.0)
EVEN = Pose(body_roll=0, spine_tilt=0, l_knee_flex=3, r_knee_flex=3, hips_drop_cm=1,
            neck_tilt=0)

ANIM = Animation(
    kind="standing", duration_s=10.0, loop=True,
    catalog=Catalog(
        key="standing", group="stand", repoint=True,
        prompt="standing relaxed, arms hanging loosely at the sides, weight on one leg, "
               "calm and at ease",
        synonyms=("locker stehen", "entspannt stehen", "standing around")),
    base=STAND | EVEN,
    keys=[Key(0.0, EVEN | Pose(neck_rot=0, neck_flex=0)),
          Key(1.6, LEFT | Pose(neck_rot=8, neck_flex=2)),
          Key(4.2, LEFT | Pose(neck_rot=12, neck_flex=-2)),
          Key(5.4, EVEN | Pose(neck_rot=2, neck_flex=0)),
          Key(6.8, RIGHT | Pose(neck_rot=-8, neck_flex=3)),
          Key(9.0, RIGHT | Pose(neck_rot=-5, neck_flex=1))],
    layers=[Breath(amp=1.0, period_s=5.0),
            Oscillator("l_arm_azim", 1.5, 5.0, 0.1),
            Oscillator("r_arm_azim", 1.5, 5.0, 0.35),
            Oscillator("l_fingers_curl", 4.0, 10.0),
            Oscillator("r_fingers_curl", 4.0, 10.0, 0.5)],
    ik=[FeetPlanted()],
)
