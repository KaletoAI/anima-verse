#!/usr/bin/env python3
"""Smoke recovery, submission and hand-derived measurement boundaries.

Usage: .venv/bin/python scripts/smoke_pose_animation_queue.py

Stand 1.058 and seat .657 are inside their intervals; stand 1.25 is outside.
Feet -.028 exceed -.035, -.04 do not. Loop seam 3.54 <= 4.1 < 4.2.
The reference mapping has 22 core + 30 driven finger bones and 12 end sites.
All 64 mapping bones are required; the 18 main body bones need rotation tracks.
Production measurements contain 69 bones and 40 tracks without finger tips/toes.
Only Hips may translate, no bone may scale, and duration must be positive.
Recovery cancels j1 on its saved, unavailable backend without rerouting.
The Blender importer invents loc/scale curves, so report authored FBX channels.
"""
import os
import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def structure():
    core = "Hips Spine Spine1 Spine2 Neck Head LeftShoulder LeftArm LeftForeArm LeftHand RightShoulder RightArm RightForeArm RightHand LeftUpLeg LeftLeg LeftFoot LeftToeBase RightUpLeg RightLeg RightFoot RightToeBase".split()
    fingers = [f"{side}Hand{finger}{part}" for side in ("Left", "Right")
               for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky") for part in (1, 2, 3)]
    ends = ["LeftToe_End", "RightToe_End"] + [f"{side}Hand{finger}4" for side in ("Left", "Right") for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky")]
    return {"bones": core + fingers + ends, "rot_tracks": core + fingers,
            "loc_tracks": ["Hips"], "scale_tracks": [], "duration_s": 1.3}

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        os.environ.update({name: str(Path(tmp) / name) for name in (
            "ANIMATION_CLIPS_DIR", "ANIMATION_CLIPS_INBOX_DIR",
            "ANIMATION_RIG_FILE", "ANIMATION_PUPPET_FILE", "ANIMATION_CLIPS_LICENSED_DIR")})
        from app.core import pose_animation as pa
        # Exercise the Blender measurement script with a tiny importer/scene double.
        class Matrix:
            def __matmul__(self, other):
                return other
        bones = [SimpleNamespace(name="mixamorig:" + name,
                                 matrix=SimpleNamespace(translation=SimpleNamespace(x=0, y=0, z=height)))
                 for name, height in (("Hips", 1.058), ("LeftFoot", -.028), ("LeftHandIndex4", 1))]
        curves = [SimpleNamespace(data_path=path, keyframe_points=[1, 40]) for path in (
            'pose.bones["mixamorig:Hips"].rotation_quaternion',
            'pose.bones["mixamorig:LeftFoot"].rotation_euler',
            'pose.bones["mixamorig:Hips"].location',
            'pose.bones["mixamorig:LeftFoot"].scale')]
        curves.append(SimpleNamespace(data_path='pose.bones["mixamorig:LeftHandIndex4"].rotation_quaternion', keyframe_points=[]))
        arm = SimpleNamespace(type="ARMATURE", matrix_world=Matrix(), pose=SimpleNamespace(bones=bones),
                              animation_data=SimpleNamespace(action=SimpleNamespace(frame_range=(1, 40), fcurves=curves)))
        scene = SimpleNamespace(render=SimpleNamespace(fps=30, fps_base=1), objects=[arm], frame_set=lambda f: None)
        bpy = SimpleNamespace(context=SimpleNamespace(scene=scene, view_layer=SimpleNamespace(update=lambda: None)),
                              ops=SimpleNamespace(wm=SimpleNamespace(read_factory_settings=lambda **kw: None),
                                                  import_scene=SimpleNamespace(fbx=lambda **kw: None)))
        def elem(kind, props=(), children=()):
            return SimpleNamespace(id=kind, props=list(props), elems=list(children))
        objects = [elem(b"Model", (1, b"mixamorig:Hips\x00\x01Model", b"LimbNode")),
                   elem(b"Model", (2, b"mixamorig:LeftFoot\x00\x01Model", b"LimbNode"))]
        connections = []
        for node, model, prop in ((10, 1, b"Lcl Rotation"), (20, 2, b"Lcl Rotation"), (30, 1, b"Lcl Translation")):
            objects.extend([elem(b"AnimationCurveNode", (node,)),
                            elem(b"AnimationCurve", (node + 1,), [elem(b"KeyTime", ([0, 1],)), elem(b"KeyValueFloat", ([0, 1],))])])
            connections.extend([elem(b"C", (b"OP", node + 1, node, b"d|X")),
                                elem(b"C", (b"OP", node, model, prop))])
        tree = elem(b"", children=[elem(b"Objects", children=objects), elem(b"Connections", children=connections)])
        parser = SimpleNamespace(parse=lambda path: (tree, 7400))
        spec = importlib.util.spec_from_file_location("measure_fixture", Path(__file__).resolve().parents[1] / "app/blender/scripts/clip_measure.py")
        measurement = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"bpy": bpy, "mathutils": SimpleNamespace(Vector=lambda xyz: SimpleNamespace(y=xyz[1])), "io_scene_fbx": SimpleNamespace(parse_fbx=parser)}):
            spec.loader.exec_module(measurement)
            data, outputs = measurement.run({"inputs": {"clip": "fixture.fbx"}})
            # Authored forbidden channels must survive even if their values are constant.
            tree.elems[1].elems.extend([elem(b"C", (b"OP", 20, 2, b"Lcl Scaling")),
                                       elem(b"C", (b"OP", 20, 2, b"Lcl Translation"))])
            forbidden = measurement._source_tracks("fixture.fbx")
            assert forbidden["scale_tracks"] == ["LeftFoot"]
            assert forbidden["loc_tracks"] == ["Hips", "LeftFoot"]
        assert data["bones"] == ["Hips", "LeftFoot", "LeftHandIndex4"]
        assert data["rot_tracks"] == ["Hips", "LeftFoot"]
        assert data["loc_tracks"] == ["Hips"] and data["scale_tracks"] == []
        assert abs(data["duration_s"] - 1.3) < 1e-9
        print("PASS measurement reports skeleton, keyed tracks and duration")
        def check(hip=1.058, foot=-.028, seam=3.54, group="stand", loop=True):
            return pa.check_clip({"geometry": {"loop": {"seam_distance": seam}}},
                                 {**structure(), "hips_y": [hip], "min_foot_y": foot}, group, loop)
        assert not check() and not check(hip=.657, group="seat")
        assert check(hip=1.25) and check(foot=-.04) and check(seam=4.2)
        assert not check(seam=4.2, loop=False)
        assert not check(hip=.95, foot=-.035, seam=4.1)
        assert not check(hip=1.20)
        assert check(hip=float("nan")) and check(foot=float("inf"))
        assert check(seam=float("nan"))
        assert pa.check_clip({}, {}, "stand", True)
        valid = {**structure(), "hips_y": [1.058], "min_foot_y": -.028}
        for field, value, reason in (
            ("bones", [b for b in valid["bones"] if b != "LeftHandIndex4"], "bone"),
            ("rot_tracks", [b for b in valid["rot_tracks"] if b != "LeftForeArm"], "rotation"),
            ("loc_tracks", ["Hips", "LeftArm"], "translation"),
            ("scale_tracks", ["Hips"], "scale"),
            ("duration_s", 0, "duration"), ("duration_s", -1, "duration"),
            ("duration_s", float("inf"), "duration"), ("duration_s", float("nan"), "duration")):
            reasons = pa.check_clip({}, {**valid, field: value}, "stand", False)
            assert any(reason in r.lower() for r in reasons), (field, reasons)
        optional = {f"{side}Hand{finger}3" for side in ("Left", "Right")
                    for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky")}
        optional.update(("LeftToeBase", "RightToeBase"))
        production = {**valid,
                      "bones": valid["bones"] + ["LeftEye", "RightEye", "Jaw", "HeadTop_End", "Root"],
                      "rot_tracks": [b for b in valid["rot_tracks"] if b not in optional]}
        assert len(production["bones"]) == 69 and len(production["rot_tracks"]) == 40
        assert not pa.check_clip({}, production, "stand", False)
        missing_arm = {**production, "rot_tracks": [b for b in production["rot_tracks"] if b != "LeftForeArm"]}
        assert pa.check_clip({}, missing_arm, "stand", False) == ["Missing rotation tracks: LeftForeArm."]
        main_body = "Hips Spine Spine1 Spine2 Neck Head LeftArm LeftForeArm LeftHand RightArm RightForeArm RightHand LeftUpLeg LeftLeg LeftFoot RightUpLeg RightLeg RightFoot".split()
        assert not pa.check_clip({}, {**production, "rot_tracks": main_body}, "stand", False)
        for bone in main_body:
            assert pa.check_clip({}, {**production, "rot_tracks": [b for b in main_body if b != bone]}, "stand", False) == [f"Missing rotation tracks: {bone}."]
        print("PASS production 69 bones / 40 tracks and required main body rotations")
        print("PASS structural boundaries")
        queue = Mock()
        queue.get_task_progress.return_value = {"phase": "hub", "hub_job": "j1", "backend": "original"}
        service = Mock()
        original = SimpleNamespace(name="original", available=False)
        service.pool.backends = [SimpleNamespace(name="new-route"), original]
        with patch.object(pa, "get_task_queue", return_value=queue), \
             patch.object(pa, "prepare_motion") as prepare, \
             patch.object(pa, "get_image_service", return_value=service), \
             patch("app.imagegen.routing.resolve_image_route", side_effect=AssertionError("restart must not reroute")), \
             patch.object(pa, "_cancel_lost_job") as cancel:
            try:
                pa._handle({"_task_id": "restart", "mode": "entry", "key": "waving"})
            except RuntimeError as exc:
                assert "interrupted by restart" in str(exc)
            else:
                raise AssertionError("restart accepted")
            prepare.assert_not_called()
            service.generate_mesh_animation.assert_not_called()
            cancel.assert_called_once_with(original, "j1")
            with patch.object(pa.pose_catalog, "get_catalog", return_value={"hug": {"solo": False}}):
                try:
                    pa.submit("entry", key="hug")
                except ValueError:
                    pass
                else:
                    raise AssertionError("pair accepted")
            queue.submit.assert_not_called()
            pa.submit("free", text="wave", seed=0)
            assert queue.submit.call_args.kwargs["max_retries"] == 0
            assert queue.submit.call_args.kwargs["queue_name"] == "pose_animation"
        queue.get_task_progress.return_value = {}
        queue.is_task_cancelled.return_value = False
        with patch.object(pa, "get_task_queue", return_value=queue), \
             patch.object(pa, "prepare_motion", side_effect=RuntimeError("stop after input")) as prepare:
            try:
                pa._handle({"_task_id": "candidate", "mode": "candidate", "raw_text": "wave the right hand", "text": "wrong fallback"})
            except RuntimeError as exc:
                assert str(exc) == "stop after input"
            assert prepare.call_args.kwargs["text"] == "wave the right hand"
        # The callback must save the actual submitting backend before a result exists.
        from app.imagegen.service import ImageService
        from app.imagegen.base import GenerationCancelled
        from app.imagegen import routing
        backend = SimpleNamespace(name="original", last_job_id="j2")
        observed = []
        def generate(prompt, negative, params, log_meta=None):
            params["on_job_id"]("j2")
            raise GenerationCancelled("j2")
        backend.generate = generate
        service = ImageService.__new__(ImageService)
        service._pool = SimpleNamespace(backends=[backend])
        def handoff(b, op):
            return op(b), b
        service.run_on_backend = handoff
        service.run_on_backend_channel = lambda b, fn, **kwargs: fn()
        def submitted(job_id, backend_name):
            observed.append((job_id, backend_name))
        with patch.object(routing, "resolve_image_route", return_value=SimpleNamespace(backend=backend)):
            try:
                service.generate_mesh_animation("puppet", ["An object waves."], 0,
                                                on_job_id=submitted)
            except GenerationCancelled:
                pass
            assert observed == [("j2", "original")], observed
            observed.clear()
            cancellation = {"requested": False}
            def channel_after_wait(b, fn, **kwargs):
                cancellation["requested"] = True
                return fn()
            service.run_on_backend_channel = channel_after_wait
            try:
                service.generate_mesh_animation("puppet", ["An object waves."], 0,
                                                should_cancel=lambda: cancellation["requested"], on_job_id=submitted)
            except GenerationCancelled:
                pass
            assert observed == [], "cancelled channel waiter submitted a job"
        print("PASS backend identity at submission and cancellation after channel wait")
        from app.core.db import init_schema
        init_schema()
        from app.routes import queue as queue_route
        from app.core import provider_manager
        tq = pa.get_task_queue()
        with patch.object(tq, "start"), patch.object(provider_manager, "get_provider_manager", return_value=SimpleNamespace(cancel_task=lambda tid: False)):
            for running in (False, True):
                tid = tq.submit("pose_animation", {}, max_retries=0)
                if running:
                    with tq._connect() as conn:
                        conn.execute("UPDATE tasks SET status='running' WHERE task_id=?", (tid,))
                        conn.commit()
                assert queue_route.cancel_task(tid)["status"] == "cancelled"
                assert tq.is_task_cancelled(tid)
                tq._finish_task(tid, "failed", error="late failure")
                assert tq.is_task_cancelled(tid)
            tracked = tq.track_start("image_generation", "tracked fixture", queue_name="fixture")
            with patch.object(tq, "cancel_task", side_effect=AssertionError("tracked tasks must keep track_cancel")):
                assert queue_route.cancel_task(tracked)["status"] == "cancelled"
            with tq._connect() as conn:
                row = conn.execute("SELECT status, error FROM tasks WHERE task_id=?", (tracked,)).fetchone()
                assert tuple(row) == ("cancelled", "Manuell abgebrochen")
        print("PASS route cancels pending/running queued pose tasks and preserves tracked-task behavior")
        print("PASS: recovery, pair rejection, submission and check boundaries")


if __name__ == "__main__":
    main()
