"""An authored take (animation studio) -> clip FBX + sidecar, through the
very run_takes every other source uses.

Invoked through ``app.blender.runner.run("proc_clip", inputs={"take": …,
"rig": …}, params={"kind": …, "source": {…}})``.

The take (``animstudio.compile.take_document``) carries per frame and bone
the WORLD rotation relative to the rig's rest and the bone's head in cm —
on the reference rig itself. So the adapter speaks cmu_clip's intermediate
names (BONE_MAP) with each bone's rest direction taken from the rig's own
tail - head: the alignment A in ``_solve`` is then the identity for every
bone, and ``lhipjoint`` is sized so the leg ratio is exactly 1.

Three parameters keep run_takes from re-interpreting an authored take:
``loops`` instead of ``loop_s`` (no loop cut, no tail blend — the source is
closed already), ``source_fps = fps`` (the sidecar says 120 otherwise) and
``yaw_deg`` = the take's own facing, which cancels the facing normalisation
(degenerate for a lying root).
"""
import json
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import _cmu                                                   # noqa: E402
import cmu_clip                                               # noqa: E402
from fbx_clip import _FakeBone, _FakeSkeleton, _FbxTake       # noqa: E402
sys.path.remove(_SCRIPTS_DIR)


def _take(doc):
    sk = _FakeSkeleton()
    for short, b in doc["bones"].items():
        inter = cmu_clip.BONE_MAP[short]
        sk.bones[inter] = _FakeBone(inter, tuple(b["direction"]), float(b["length"]))
    sk.bones["lhipjoint"] = _FakeBone("lhipjoint", (0.0, -1.0, 0.0), float(doc["lhipjoint_cm"]))
    poses = []
    for frame in doc["frames"]:
        pose = _cmu.Pose()
        for short, v in frame.items():
            inter = cmu_clip.BONE_MAP[short]
            pose.rot[inter] = [list(r) for r in v["rot"]]
            pose.pos[inter] = tuple(v["pos"])
        poses.append(pose)
    return _FbxTake("", sk, poses)


def run(job):
    inputs = job.get("inputs") or {}
    params = dict(job.get("params") or {})
    doc = json.loads(Path(inputs["take"]).read_text(encoding="utf-8"))
    take = _take(doc)
    fx, fz = _cmu.forward_xz(take.poses[0])
    fps = int(doc["fps"])
    args = {"kind": params["kind"], "rig": inputs["rig"], "out_dir": job["out_dir"],
            "fps": fps, "source_fps": float(fps), "root_motion": "strip",
            "loops": bool(doc["loop"]), "yaw_deg": math.degrees(math.atan2(fx, fz))}
    sidecar, outputs = cmu_clip.run_takes([take], args, fps, params["source"])
    sidecar, outputs = _finish(sidecar, outputs, params["kind"], fps,
                               float(doc.get("lift_cm") or 0.0))
    # Measured AFTER _finish: the checks read the clip as it is published.
    outputs["measure"] = _measure(outputs[params["kind"]], Path(job["out_dir"]), fps)
    return sidecar, outputs


MEASURED = ["Hips", "Spine2", "Head", "HeadTop_End",
            "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "LeftToe_End",
            "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase", "RightToe_End",
            "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]


def _measure(fbx: str, out_dir: Path, fps: int) -> str:
    """Joint heads per frame of the EXPORTED clip (armature space, cm) and
    the number of rotation tracks — what the studio's checks read.

    Imported like ``_finish`` does (scene fps first, ``anim_offset=0``), so
    row i is frame i of the clip."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = fps
    bpy.ops.import_scene.fbx(filepath=fbx, global_scale=1.0,
                             use_anim=True, anim_offset=0.0)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    act = arm.animation_data.action
    tracks = {fc.data_path.split('"')[1] for fc in act.fcurves
              if fc.data_path.endswith("rotation_quaternion")}
    missing = [s for s in MEASURED if arm.pose.bones.get(cmu_clip.PREFIX + s) is None]
    if missing:
        raise RuntimeError(f"measure: {Path(fbx).name} lacks the joints {', '.join(missing)}")
    f0, f1 = (int(round(v)) for v in act.frame_range)
    rows = []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        row = {}
        for short in MEASURED:
            row[short] = [float(v) for v in arm.pose.bones[cmu_clip.PREFIX + short].head]
        rows.append(row)
    path = out_dir / "measure.json"
    path.write_text(json.dumps({"tracks": len(tracks), "frames": rows}), encoding="utf-8")
    return str(path)


def _finish(sidecar, outputs, kind, fps, lift_cm):
    """Strip the yaw pass-through from the provenance (it is not a dial
    setting) and apply ``lift_cm``: the finished clip is re-imported, every
    key of the Hips LOCATION track is raised by lift_cm along ARMATURE +Y
    (converted into the Hips bone's rest frame, where the pose location
    lives), and the file is exported again with the same track shape.

    The re-import follows ``clip_orient._import_armature``: scene fps first
    and ``anim_offset=0`` (the importer's default offset of 1 puts the keys
    one frame late), and the scene range is set to the action's range before
    the export — an empty scene keeps its factory 1..250, and the exporter
    bakes the SCENE range, so the clip came back 250 frames long.
    ``cmu_clip.DRIVEN`` is still the set ``run_takes`` exported with, so the
    second ``_export`` writes the same tracks."""
    geometry = sidecar.setdefault("geometry", {})
    geometry.pop("yaw_deg", None)
    if lift_cm:
        import bpy
        from mathutils import Vector
        fbx = outputs[kind]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.fps = fps
        bpy.ops.import_scene.fbx(filepath=fbx, global_scale=1.0,
                                 use_anim=True, anim_offset=0.0)
        arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
        f0, f1 = arm.animation_data.action.frame_range
        scene.render.fps = fps
        scene.frame_start, scene.frame_end = int(round(f0)), int(round(f1))
        hips = arm.data.bones[cmu_clip.PREFIX + "Hips"]
        local = hips.matrix_local.to_3x3().inverted() @ Vector((0.0, lift_cm, 0.0))
        path = f'pose.bones["{cmu_clip.PREFIX}Hips"].location'
        for fc in arm.animation_data.action.fcurves:
            if fc.data_path == path:
                for k in fc.keyframe_points:
                    k.co[1] += local[fc.array_index]
                    k.handle_left[1] += local[fc.array_index]
                    k.handle_right[1] += local[fc.array_index]
        cmu_clip._export(arm, Path(fbx))
        geometry["lift_cm"] = round(float(lift_cm), 2)
    Path(outputs["sidecar"]).write_text(json.dumps(sidecar, indent=1), encoding="utf-8")
    return sidecar, outputs


if __name__ == "__main__":
    _common.main(run)
