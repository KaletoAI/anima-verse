#!/usr/bin/env python3
"""Smoke: the studio's numeric checks on HAND-MADE measurements (no Blender).

Usage: ./.venv/bin/python scripts/smoke_animstudio_checks.py

Every case builds a tiny measure dict whose numbers are chosen so exactly
one check trips; the expectation is written next to it:
- clean standing (feet at y 0/1 cm, still)           -> every check ok
- a toe at y -2.0 cm                                  -> floor fails (-2.0 < -1.0)
- left ball in contact (y 1 cm) sliding 0 -> 3 cm in x -> slide fails (3.0 > 2.0)
- loop with last frame's hand 1.5 cm off frame 0      -> loop fails (1.5 > 1.0)
- tracks 7                                            -> tracks fails (7 < 8)
- seat with hips at 80 cm                             -> seat fails (80 not in 61..71)
- lie with hips at 20 cm                              -> lie ok
- compiled ik error 5 cm                              -> ik fails
- compiled loop_problems ["..."]                      -> loop_layers fails
- compiled extrema l_elbow_flex (0, 170)              -> limits fails (170 > 150)
- a measure whose frame 3 lacks LeftToeBase           -> StudioError naming
  LeftToeBase and the frame (not a bare KeyError)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "animation-studio"))

from animstudio.checks import run_checks                              # noqa: E402
from animstudio.compile import Compiled                               # noqa: E402
from animstudio.dsl import Animation, Catalog                         # noqa: E402

FAIL = []


def frame(**over):
    f = {"Hips": [0, 100, 0], "LeftUpLeg": [9, 95, 0], "RightUpLeg": [-9, 95, 0],
         "LeftLeg": [9, 50, 0], "RightLeg": [-9, 50, 0],
         "LeftFoot": [9, 8, 0], "RightFoot": [-9, 8, 0],
         "LeftToeBase": [9, 1, 12], "RightToeBase": [-9, 1, 12],
         "LeftToe_End": [9, 0, 20], "RightToe_End": [-9, 0, 20],
         "LeftHand": [70, 100, 0], "RightHand": [-70, 100, 0], "Head": [0, 160, 0]}
    f.update(over)
    return f


def anim(group="stand", loop=False):
    return Animation(kind="s", duration_s=1.0, loop=loop,
                     catalog=Catalog(key="s", group=group, prompt="p"))


def comp(**kw):
    c = Compiled(frames=[], fps=30, loop=False, fingers=False)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def failing(checks):
    return sorted(c.name for c in checks if not c.ok)


def expect(name, checks, want):
    got = failing(checks)
    if got != want:
        FAIL.append(f"{name}: failing {got}, expected {want}")


still = {"tracks": 22, "frames": [frame() for _ in range(10)]}
expect("clean", run_checks(anim(), comp(), still), [])
expect("floor", run_checks(anim(), comp(), {"tracks": 22, "frames":
       [frame(LeftToe_End=[9, -2.0, 20])] + [frame()] * 9}), ["floor"])
slide = [frame(LeftToeBase=[9 + 3.0 * i / 9, 1, 12]) for i in range(10)]
expect("slide", run_checks(anim(), comp(), {"tracks": 22, "frames": slide}), ["foot_slide"])
lp = [frame()] * 9 + [frame(LeftHand=[71.5, 100, 0])]
expect("loop", run_checks(anim(loop=True), comp(), {"tracks": 22, "frames": lp}), ["loop_seam"])
expect("tracks", run_checks(anim(), comp(), {"tracks": 7, "frames": still["frames"]}), ["tracks"])
seat = [frame(Hips=[0, 80, 0], LeftUpLeg=[9, 78, 0], RightUpLeg=[-9, 78, 0],
              LeftLeg=[9, 78, 40], RightLeg=[-9, 78, 40])] * 10
expect("seat", run_checks(anim("seat"), comp(), {"tracks": 22, "frames": seat}), ["seat_height"])
lie = [frame(Hips=[0, 20, 0])] * 10
expect("lie", run_checks(anim("lie"), comp(), {"tracks": 22, "frames": lie}), [])
expect("ik", run_checks(anim(), comp(ik_error_cm={"l_hand": 5.0}), still), ["ik"])
expect("loop_layers", run_checks(anim(), comp(loop_problems=["x"]), still), ["loop_layers"])
expect("limits", run_checks(anim(), comp(extrema={"l_elbow_flex": (0.0, 170.0)}), still), ["limits"])

from animstudio import StudioError                                    # noqa: E402

gap = [frame() for _ in range(10)]
del gap[3]["LeftToeBase"]
try:
    run_checks(anim(), comp(), {"tracks": 22, "frames": gap})
    FAIL.append("missing joint: run_checks accepted it")
except StudioError as e:
    if "LeftToeBase" not in str(e) or "3" not in str(e):
        FAIL.append(f"missing joint: message does not name it: {e}")
except Exception as e:                                                # noqa: BLE001
    FAIL.append(f"missing joint: {e!r} instead of StudioError")

print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_animstudio_checks")
sys.exit(1 if FAIL else 0)
