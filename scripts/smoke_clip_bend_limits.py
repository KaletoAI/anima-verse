"""Ruling A145: a pair clip's bend limits (``app.core.animation_clips``) — validation, inheritance, package default.

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

D = {"raised": {"joint_deg": 15.0, "total_deg": 35.0}, "resting": {"joint_deg": 45.0, "total_deg": 120.0}}
assert ac.validate_bend_limits({}) == D                                                  # [1]
assert ac.validate_bend_limits({"raised": {"joint_deg": 20}})["raised"] == {"joint_deg": 20.0, "total_deg": 35.0}  # [2]
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
assert got["source"] == "package" and got["limits"]["raised"] == {"joint_deg": 15.0, "total_deg": 25.0}, got
other = ac.clip_bend_limits({}, "other")
assert other["source"] == "package" and other["limits"]["resting"] == {"joint_deg": 30.0, "total_deg": 120.0}, other
own = ac.clip_bend_limits({"bend_limits": {"raised": {"joint_deg": 10}}}, "k")            # [6]
assert own["source"] == "clip" and own["limits"]["raised"] == {"joint_deg": 10.0, "total_deg": 25.0}, own
shutil.rmtree(tmp, ignore_errors=True)
print("smoke_clip_bend_limits OK")
