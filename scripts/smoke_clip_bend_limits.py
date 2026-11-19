"""Ruling A145 (+ A158 root angle): a pair clip's bend limits (``app.core.animation_clips``) — validation, inheritance, package default.

Usage: ./.venv/bin/python scripts/smoke_clip_bend_limits.py   (no server; a temp storage dir)

Expected, by hand:
[1] {} -> the core default raised 15/35, resting 45/120.
[2] {"raised": {"joint_deg": 20}} -> raised 20/35 (total from the default), resting 45/120.
[3] refused: joint_deg 91 (> 90), total_deg -1, an unknown state "soft", a bool, a key "angle".
[4] clip_bend_limits(None, k) without a package: source default, the core default.
[5] a package provider {"k": {"raised": {"total_deg": 25}}, "*": {"resting": {"joint_deg": 30}}}:
    kind k -> package, raised 15/25; kind other -> package via "*", resting 30/120.
[6] the clip's own {"raised": {"joint_deg": 10}} on kind k -> source clip, raised 10/25 (completed from the
    package value, not the core one).
[7] A158: the A150 root limit keys are gone — validate_bend_limits refuses {"raised": {"root_up_deg": 30}}; a
    stored clip value {"raised": {"joint_deg": 10, "root_up_deg": 30}} loads as source clip, raised 10/25 (the root key
    dropped, not the whole value); a package default {"x": {"resting": {"joint_deg": 25, "root_up_deg": 45}}} gives
    kind x resting 25/120 (not refused).
[8] A158 root angle: {} -> 0/0; {"pitch_deg": -30} -> pitch -30, yaw 0; refused: pitch 61, pitch -61, yaw 31,
    a bool, a key "roll_deg"; clip_root_angle(None) and of a junk stored value -> 0/0, of {"pitch_deg": 20,
    "yaw_deg": -15} -> 20/-15.
[9] A212 alignment range: 8 and 40 and 1 accepted as floats; refused 0.5, 41, a bool, "8", NaN;
    clip_align_range(None) -> 8 cm source default, of {"align_range_cm": 12} -> 12 source clip, of a junk 99 -> default.
[10] A212 align_applied: {"role_shift_cm": {"b": [1, 2, 3]}} -> turn_deg [0, 0] filled in, floats; refused a role
    "x", 2 numbers for a role, 101, a key "yaw"; clip_align_applied(None) -> None, of junk -> None.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="smoke-bend-")
from app.core import paths  # noqa: E402
paths.init(tmp)
from app.core import animation_clips as ac  # noqa: E402
from app.core import hooks  # noqa: E402

RR = {}
RS = {}
D = {"raised": {"joint_deg": 15.0, "total_deg": 35.0, **RR}, "resting": {"joint_deg": 45.0, "total_deg": 120.0, **RS}}
assert ac.validate_bend_limits({}) == D                                                  # [1]
assert ac.validate_bend_limits({"raised": {"joint_deg": 20}})["raised"] == {"joint_deg": 20.0, "total_deg": 35.0, **RR}  # [2]
for bad in ({"raised": {"joint_deg": 91}}, {"resting": {"total_deg": -1}}, {"soft": {}},     # [3]
            {"raised": {"joint_deg": True}}, {"raised": {"angle": 3}}):
    try:
        ac.validate_bend_limits(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_bend_limits(None, "k") == {"limits": D, "source": "default"}               # [4]
hooks.register_provider(ac.BEND_LIMIT_DEFAULTS_CAPABILITY,
                        lambda: {"k": {"raised": {"total_deg": 25}}, "*": {"resting": {"joint_deg": 30}}},
                        owner="smoke", multiple=True)
got = ac.clip_bend_limits(None, "k")                                                     # [5]
assert got["source"] == "package" and got["limits"]["raised"] == {"joint_deg": 15.0, "total_deg": 25.0, **RR}, got
other = ac.clip_bend_limits({}, "other")
assert other["source"] == "package" and other["limits"]["resting"] == {"joint_deg": 30.0, "total_deg": 120.0, **RS}, other
own = ac.clip_bend_limits({"bend_limits": {"raised": {"joint_deg": 10}}}, "k")            # [6]
assert own["source"] == "clip" and own["limits"]["raised"] == {"joint_deg": 10.0, "total_deg": 25.0, **RR}, own
try:                                                                                     # [7]
    ac.validate_bend_limits({"raised": {"root_up_deg": 30}})
    raise AssertionError("accepted root_up_deg")
except ac.ClipLibraryError:
    pass
old = ac.clip_bend_limits({"bend_limits": {"raised": {"joint_deg": 10, "root_up_deg": 30}}}, "k")
assert old["source"] == "clip" and old["limits"]["raised"] == {"joint_deg": 10.0, "total_deg": 25.0}, old
hooks.register_provider(ac.BEND_LIMIT_DEFAULTS_CAPABILITY,
                        lambda: {"x": {"resting": {"joint_deg": 25, "root_up_deg": 45}}}, owner="smoke2", multiple=True)
px = ac.clip_bend_limits(None, "x")
assert px["source"] == "package" and px["limits"]["resting"] == {"joint_deg": 25.0, "total_deg": 120.0}, px
assert ac.validate_root_angle({}) == {"pitch_deg": 0.0, "yaw_deg": 0.0}                  # [8]
assert ac.validate_root_angle({"pitch_deg": -30}) == {"pitch_deg": -30.0, "yaw_deg": 0.0}
for bad in ({"pitch_deg": 61}, {"pitch_deg": -61}, {"yaw_deg": 31}, {"pitch_deg": True}, {"roll_deg": 1}):
    try:
        ac.validate_root_angle(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_root_angle(None) == {"pitch_deg": 0.0, "yaw_deg": 0.0}
assert ac.clip_root_angle({"root_angle": "junk"}) == {"pitch_deg": 0.0, "yaw_deg": 0.0}
assert ac.clip_root_angle({"root_angle": {"pitch_deg": 20, "yaw_deg": -15}}) == {"pitch_deg": 20.0, "yaw_deg": -15.0}
assert [ac.validate_align_range(v) for v in (8, 40, 1)] == [8.0, 40.0, 1.0]               # [9]
for bad in (0.5, 41, True, "8", float("nan")):
    try:
        ac.validate_align_range(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_align_range(None) == {"cm": 8.0, "source": "default"}
assert ac.clip_align_range({"align_range_cm": 12}) == {"cm": 12.0, "source": "clip"}
assert ac.clip_align_range({"align_range_cm": 99}) == {"cm": 8.0, "source": "default"}
assert ac.validate_align_applied({"role_shift_cm": {"b": [1, 2, 3]}}) == {                # [10]
    "role_shift_cm": {"b": [1.0, 2.0, 3.0]}, "turn_deg": [0.0, 0.0]}
for bad in ({"role_shift_cm": {"x": [0, 0, 0]}}, {"role_shift_cm": {"b": [0, 0]}}, {"turn_deg": [101, 0]}, {"yaw": 1}):
    try:
        ac.validate_align_applied(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_align_applied(None) is None and ac.clip_align_applied({"align_applied": 5}) is None
shutil.rmtree(tmp, ignore_errors=True)
print("smoke_clip_bend_limits OK")
