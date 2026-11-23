"""Ruling A145 (+ A158 root angle): a pair clip's bend limits (``app.core.animation_clips``) — validation, inheritance, package default.

Usage: ./.venv/bin/python scripts/smoke_clip_bend_limits.py   (no server; a temp storage dir)

Expected, by hand:
Owner decision 2026-11-20: ONE value per state, the TOTAL (degrees); no per-joint value any more.
[1] {} -> the core default raised 15, resting 120.
[2] {"raised": {"total_deg": 20}} -> raised 20, resting 120 (from the default).
[3] refused: total_deg 361 (> 360), total_deg -1, an unknown state "soft", a bool, a key "angle", and the old
    per-joint key {"raised": {"joint_deg": 10}} (no fallback reader).
[4] clip_bend_limits(None, k) without a package: source default, the core default.
[5] a package provider {"k": {"raised": {"total_deg": 25}}, "*": {"resting": {"total_deg": 30}}}:
    kind k -> package, raised 25 / resting 120; kind other -> package via "*", raised 15 / resting 30.
[6] the clip's own {"resting": {"total_deg": 40}} on kind k -> source clip, raised 25 (completed from the package
    value, not the core one), resting 40.
[7] A158: the A150 root limit keys are gone — validate_bend_limits refuses {"raised": {"root_up_deg": 30}}; a
    stored clip value {"raised": {"total_deg": 10, "root_up_deg": 30}} loads as source clip, raised 10 (the root key
    dropped, not the whole value); a package default {"x": {"resting": {"total_deg": 25, "root_up_deg": 45}}} gives
    kind x resting 25 (not refused).
[8] A158 root angle: {} -> 0/0; {"pitch_deg": -30} -> pitch -30, yaw 0; refused: pitch 61, pitch -61, yaw 31,
    a bool, a key "roll_deg"; clip_root_angle(None) and of a junk stored value -> 0/0, of {"pitch_deg": 20,
    "yaw_deg": -15} -> 20/-15.
[9] A212 alignment range: 8 and 40 and 1 accepted as floats; refused 0.5, 41, a bool, "8", NaN;
    clip_align_range(None) -> 8 cm source default, of {"align_range_cm": 12} -> 12 source clip, of a junk 99 -> default.
[10] A212 align_applied: {"role_shift_cm": {"b": [1, 2, 3]}} -> role_turn_deg {} filled in, floats (owner 2026-11-23:
    every role's turn [tilt, roll, yaw]); refused a role "x", 2 numbers for a role, a turn of 181, the gone key
    "turn_deg", a key "yaw"; clip_align_applied(None) -> None, of junk -> None.
[11] the boot migration migrate_bend_limits_total (temp clip libraries via ANIMATION_CLIPS_DIR /
    ANIMATION_CLIPS_LICENSED_DIR; rule: raised total = min(old joint, old total), resting total = old total):
    free/p.json raised {joint 15, total 35, root_up 60}, resting {joint 25, total 75} -> raised 15 (min 15/35),
      resting 75, the dead root key gone;
    licensed/set/q.json raised {joint 40, total 30}, resting {joint 45} -> raised 30 (min 40/30); the resting row
      held no total -> dropped (it inherits, as its total did);
    free/r.json resting {joint 10} only -> nothing left -> the bend_limits key removed, kind/fps kept;
    free/s.json already {raised: {total 12}} and free/walk.json without bend limits -> byte-identical.
    Returns 3; a second run returns 0; clip_bend_limits of the migrated p -> source clip, raised 15 / resting 75.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="smoke-bend-")
os.environ["ANIMATION_CLIPS_DIR"] = os.path.join(tmp, "clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = os.path.join(tmp, "clips-licensed")
os.environ["ANIMATION_RIG_FILE"] = os.path.join(tmp, "rig.fbx")
from app.core import paths  # noqa: E402
paths.init(tmp)
from app.core import animation_clips as ac  # noqa: E402
from app.core import hooks  # noqa: E402

D = {"raised": {"total_deg": 15.0}, "resting": {"total_deg": 120.0}}
assert ac.validate_bend_limits({}) == D                                                  # [1]
assert ac.validate_bend_limits({"raised": {"total_deg": 20}}) == {"raised": {"total_deg": 20.0},  # [2]
                                                                 "resting": {"total_deg": 120.0}}
for bad in ({"raised": {"total_deg": 361}}, {"resting": {"total_deg": -1}}, {"soft": {}},     # [3]
            {"raised": {"total_deg": True}}, {"raised": {"angle": 3}}, {"raised": {"joint_deg": 10}}):
    try:
        ac.validate_bend_limits(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_bend_limits(None, "k") == {"limits": D, "source": "default"}               # [4]
hooks.register_provider(ac.BEND_LIMIT_DEFAULTS_CAPABILITY,
                        lambda: {"k": {"raised": {"total_deg": 25}}, "*": {"resting": {"total_deg": 30}}},
                        owner="smoke", multiple=True)
got = ac.clip_bend_limits(None, "k")                                                     # [5]
assert got["source"] == "package" and got["limits"] == {"raised": {"total_deg": 25.0}, "resting": {"total_deg": 120.0}}, got
other = ac.clip_bend_limits({}, "other")
assert other["source"] == "package" and other["limits"] == {"raised": {"total_deg": 15.0}, "resting": {"total_deg": 30.0}}, other
own = ac.clip_bend_limits({"bend_limits": {"resting": {"total_deg": 40}}}, "k")            # [6]
assert own["source"] == "clip" and own["limits"] == {"raised": {"total_deg": 25.0}, "resting": {"total_deg": 40.0}}, own
try:                                                                                     # [7]
    ac.validate_bend_limits({"raised": {"root_up_deg": 30}})
    raise AssertionError("accepted root_up_deg")
except ac.ClipLibraryError:
    pass
old = ac.clip_bend_limits({"bend_limits": {"raised": {"total_deg": 10, "root_up_deg": 30}}}, "k")
assert old["source"] == "clip" and old["limits"]["raised"] == {"total_deg": 10.0}, old
hooks.register_provider(ac.BEND_LIMIT_DEFAULTS_CAPABILITY,
                        lambda: {"x": {"resting": {"total_deg": 25, "root_up_deg": 45}}}, owner="smoke2", multiple=True)
px = ac.clip_bend_limits(None, "x")
assert px["source"] == "package" and px["limits"]["resting"] == {"total_deg": 25.0}, px
# [11] the boot migration of stored per-joint values
FREE, LIC = os.environ["ANIMATION_CLIPS_DIR"], os.environ["ANIMATION_CLIPS_LICENSED_DIR"]
os.makedirs(os.path.join(LIC, "set"), exist_ok=True)
os.makedirs(FREE, exist_ok=True)
seed = {
    os.path.join(FREE, "p.json"): {"kind": "p", "pair": True, "bend_limits": {
        "raised": {"joint_deg": 15, "total_deg": 35, "root_up_deg": 60}, "resting": {"joint_deg": 25, "total_deg": 75}}},
    os.path.join(LIC, "set", "q.json"): {"kind": "q", "bend_limits": {
        "raised": {"joint_deg": 40, "total_deg": 30}, "resting": {"joint_deg": 45}}},
    os.path.join(FREE, "r.json"): {"kind": "r", "fps": 30, "bend_limits": {"resting": {"joint_deg": 10}}},
    os.path.join(FREE, "s.json"): {"kind": "s", "bend_limits": {"raised": {"total_deg": 12}}},
    os.path.join(FREE, "walk.json"): {"kind": "walk", "fps": 30},
}
for path, data in seed.items():
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
untouched = {p: open(p, "rb").read() for p in (os.path.join(FREE, "s.json"), os.path.join(FREE, "walk.json"))}
assert ac.migrate_bend_limits_total() == 3


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


p = _read(os.path.join(FREE, "p.json"))
assert p == {"kind": "p", "pair": True, "bend_limits": {"raised": {"total_deg": 15.0}, "resting": {"total_deg": 75.0}}}, p
q = _read(os.path.join(LIC, "set", "q.json"))
assert q == {"kind": "q", "bend_limits": {"raised": {"total_deg": 30.0}}}, q
r = _read(os.path.join(FREE, "r.json"))
assert r == {"kind": "r", "fps": 30}, r
for path, raw in untouched.items():
    assert open(path, "rb").read() == raw, path
assert ac.migrate_bend_limits_total() == 0                                               # idempotent
mp = ac.clip_bend_limits(p, "p")
assert mp == {"limits": {"raised": {"total_deg": 15.0}, "resting": {"total_deg": 75.0}}, "source": "clip"}, mp
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
    "role_shift_cm": {"b": [1.0, 2.0, 3.0]}, "role_turn_deg": {}}
for bad in ({"role_shift_cm": {"x": [0, 0, 0]}}, {"role_shift_cm": {"b": [0, 0]}}, {"role_turn_deg": {"b": [181, 0, 0]}},
            {"turn_deg": [1, 0]}, {"yaw": 1}):
    try:
        ac.validate_align_applied(bad)
    except ac.ClipLibraryError:
        continue
    raise AssertionError(f"accepted {bad}")
assert ac.clip_align_applied(None) is None and ac.clip_align_applied({"align_applied": 5}) is None
shutil.rmtree(tmp, ignore_errors=True)
print("smoke_clip_bend_limits OK")
