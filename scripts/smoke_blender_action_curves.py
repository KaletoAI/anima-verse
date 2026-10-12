#!/usr/bin/env python3
"""Smoke: _action.curves() reads and writes F-curves on Blender 5 slotted actions.

Usage:
    ./.venv/bin/python scripts/smoke_blender_action_curves.py

Runs the Blender the runner picks (runner.find_executable()) on an embedded
script that imports app/blender/scripts/_action.py. Expected by hand:
  H1  Fresh action on a new armature (no slot yet): curves(arm) creates ONE
      slot; find('pose.bones["Bone"].location', 1) is None before new();
      after new() with keys (1, 0.0) and (5, 2.0) the bone's location.y
      evaluates to 2.0 at frame 5 and the action's frame_range is (1, 5).
  H2  Imported shared/models/clips/celebrating.fbx: the action keeps exactly
      one slot after curves(arm); the number of curves equals the curves of
      anim_utils.action_get_channelbag_for_slot(action, assigned slot) —
      i.e. the assigned slot is used, not one looked up by object name.
  H3  action = None, then the same action again: curves(arm) returns the
      same curve count as before and the action still has one slot.
  H4  An armature without animation data -> ValueError.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.blender import runner  # noqa: E402

PROBE = r'''
import json, sys
import bpy
from bpy_extras import anim_utils
sys.path.insert(0, {scripts!r})
from _action import curves

out = {{}}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add()
arm = bpy.context.object
act = bpy.data.actions.new("fresh")
arm.animation_data_create()
arm.animation_data.action = act
fcs = curves(arm)
path = 'pose.bones["Bone"].location'
out["h1_find_before"] = fcs.find(path, index=1) is None
fc = fcs.new(data_path=path, index=1)
fc.keyframe_points.add(2)
fc.keyframe_points[0].co = (1.0, 0.0)
fc.keyframe_points[1].co = (5.0, 2.0)
fc.update()
bpy.context.scene.frame_set(5)
out["h1_loc_y"] = round(arm.pose.bones["Bone"].location[1], 6)
out["h1_range"] = [float(v) for v in act.frame_range]
out["h1_slots"] = len(act.slots)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath={clip!r})
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = arm.animation_data.action
n = len(curves(arm))
bag = anim_utils.action_get_channelbag_for_slot(act, arm.animation_data.action_slot)
out["h2_count"] = n
out["h2_expected"] = len(bag.fcurves)
out["h2_slots"] = len(act.slots)
arm.animation_data.action = None
arm.animation_data.action = act
out["h3_count"] = len(curves(arm))
out["h3_slots"] = len(act.slots)

bpy.ops.object.armature_add()
bare = bpy.context.object
try:
    curves(bare)
    out["h4"] = "no error"
except ValueError:
    out["h4"] = "ValueError"
json.dump(out, open(sys.argv[-1], "w"))
'''


def main():
    exe = runner.find_executable()
    if not exe:
        print("SKIP smoke_blender_action_curves (no usable Blender)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "probe.py"
        result = Path(tmp) / "out.json"
        script.write_text(PROBE.format(scripts=str(ROOT / "app/blender/scripts"),
                                       clip=str(ROOT / "shared/models/clips/celebrating.fbx")))
        proc = subprocess.run([exe, "-b", "--factory-startup", "--python", str(script), "--", str(result)],
                              capture_output=True, text=True, timeout=300)
        if not result.is_file():
            print(proc.stdout[-3000:], proc.stderr[-3000:])
            raise SystemExit("FAIL: probe produced no result")
        out = json.loads(result.read_text())
    assert out["h1_find_before"] is True, out
    assert out["h1_loc_y"] == 2.0 and out["h1_range"] == [1.0, 5.0] and out["h1_slots"] == 1, out
    print("PASS H1: a fresh action gets one slot and writable curves")
    assert out["h2_count"] == out["h2_expected"] > 0 and out["h2_slots"] == 1, out
    print("PASS H2: an imported action is read on its assigned slot")
    assert out["h3_count"] == out["h2_count"] and out["h3_slots"] == 1, out
    print("PASS H3: reassigning the action keeps its slot")
    assert out["h4"] == "ValueError", out
    print("PASS H4: no action is an error")
    print("all checks passed")


if __name__ == "__main__":
    main()
