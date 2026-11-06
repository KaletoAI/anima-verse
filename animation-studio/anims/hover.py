"""Hovering, looped: the figure floats weightlessly about 30 cm above the
ground — legs hanging loose with pointed toes (one knee a little more bent
than the other), arms drifting slightly away from the body, a slow bob of
6 cm with the limbs trailing it, an easy breath.

Made as a LOCOMOTION override (a state's "walk animation override": a
transformed hero glides instead of walking) and as the pose ``hovering``.
It plays on the spot like every gait; the client moves the figure.

``airborne``: the feet never touch the floor; the clip is lifted by
``lift_cm`` after the importer floors its lowest point (the toe tips at the
deepest moment of the bob). The toes point down on purpose — the importer's
foot plant only acts on a foot standing on its sole.

One bob is 3 s; every oscillator runs at 3 s or 1.5 s (divides the loop).
"""
from animstudio.dsl import Animation, Breath, Catalog, Oscillator, Pose
from animstudio.rig import RELAXED

T = 3.0

BASE = Pose(**RELAXED) | Pose(
    body_pitch=4, neck_flex=-4,
    l_arm_elev=-62, r_arm_elev=-62, l_arm_azim=-6, r_arm_azim=-6,
    l_arm_twist=10, r_arm_twist=10, l_elbow_flex=22, r_elbow_flex=22,
    l_wrist_flex=8, r_wrist_flex=8, l_fingers_curl=12, r_fingers_curl=12,
    l_hip_flex=14, r_hip_flex=4, l_knee_flex=28, r_knee_flex=14,
    l_hip_abduct=3, r_hip_abduct=3,
    l_ankle_flex=-40, r_ankle_flex=-34, l_toes_flex=-10, r_toes_flex=-10,
    hips_drop_cm=3)

# The bob: hips_drop 3 + 3·sin — the body sinks during the first half.
# Limbs trail it by a sixth to a quarter of a cycle (they lag the body).
LAYERS = [
    Oscillator("hips_drop_cm", 3.0, T),
    Oscillator("body_pitch", 1.0, T, 0.1),
    Oscillator("l_hip_flex", 4.0, T, -0.15), Oscillator("r_hip_flex", 4.0, T, 0.35),
    Oscillator("l_knee_flex", 5.0, T, -0.2), Oscillator("r_knee_flex", 5.0, T, 0.3),
    Oscillator("l_ankle_flex", 3.0, T, -0.25), Oscillator("r_ankle_flex", 3.0, T, 0.25),
    Oscillator("l_arm_elev", 4.0, T, -0.15), Oscillator("r_arm_elev", 4.0, T, -0.18),
    Oscillator("l_elbow_flex", 5.0, T, -0.25), Oscillator("r_elbow_flex", 5.0, T, -0.28),
    Oscillator("l_wrist_flex", 6.0, T, -0.3), Oscillator("r_wrist_flex", 6.0, T, -0.33),
    Oscillator("neck_flex", 1.5, T / 2, 0.0),
]

ANIM = Animation(
    kind="hover", duration_s=T, loop=True, lift_cm=30.0, airborne=True,
    catalog=Catalog(
        key="hovering", group="stand",
        prompt="hovering weightlessly in mid-air above the ground, legs hanging loose with "
               "pointed toes, arms floating slightly away from the body",
        synonyms=("schweben", "in der luft schweben", "levitieren", "hovering", "levitating",
                  "floating in the air")),
    base=BASE,
    keys=[],
    layers=[*LAYERS, Breath(amp=0.6, period_s=T)],
)
