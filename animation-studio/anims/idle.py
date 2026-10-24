"""Standing, looped: a relaxed stand — the arms hang loose, the weight
moves from one leg to the other and back (the unloaded knee softens, the
pelvis tips toward the loaded side, the chest answers the other way), the
head looks about a little; a slow breath over everything.

Replaces the CMU `idle` (same kind) for the pose `standing`; `idle` is also the
idle role's default kind in the game (`shared/config/locomotion_clips.json`).
The knees stay a little soft (hips median ~110 cm, like the clip it
replaces) and the thighs unturned: the bridge clips hand over into this
stance. Largest foot step in the first frame after get-up-chair on the
reference rig (client3d/scripts/smoke_bridge_root.mjs [B14]): straight legs
(hips 112.3) 1.61 cm, toes out by hip_rot 6 1.61 cm, this stance 1.25 cm,
the CMU idle it replaces 1.69 cm.
"""
from animstudio.dsl import Animation, Breath, Catalog, FeetPlanted, Key, Oscillator, Pose
from animstudio.rig import RELAXED

STAND = Pose(**RELAXED) | Pose(l_hip_abduct=5, r_hip_abduct=5,
                               hips_drop_cm=2.0, l_arm_twist=10, r_arm_twist=10,
                               # the planted feet keep their frame-0 rotation: the
                               # ankle cancels the soft knee (7) so the soles lie flat
                               l_ankle_flex=7, r_ankle_flex=7,
                               l_arm_azim=4, r_arm_azim=4)
# weight on the LEFT leg: the right knee softens, the pelvis tips to the
# left (body_roll +), the chest leans back right, the left arm hangs a
# little further out
LEFT = Pose(body_roll=1.6, spine_tilt=-2.4, r_knee_flex=12, l_knee_flex=5, hips_drop_cm=2.6,
            neck_tilt=1.0)
RIGHT = Pose(body_roll=-1.6, spine_tilt=2.4, l_knee_flex=12, r_knee_flex=5, hips_drop_cm=2.6,
             neck_tilt=-1.0)
EVEN = Pose(body_roll=0, spine_tilt=0, l_knee_flex=7, r_knee_flex=7, hips_drop_cm=2.0,
            neck_tilt=0)

ANIM = Animation(
    kind="idle", duration_s=10.0, loop=True,
    catalog=Catalog(
        key="standing", group="stand", repoint=True,
        # The catalog's DEFAULT pose: its prompt is every render's fallback
        # pose (pose_catalog.default_pose_prompt), so it stays as it was.
        prompt="standing with one hand on hip, weight shifted to one leg, shoulder slightly "
               "raised, chin up",
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
