#!/usr/bin/env python3
"""Smoke recovery, submission and hand-derived measurement boundaries.

Usage: .venv/bin/python scripts/smoke_pose_animation_queue.py

Stand 1.058 and seat .657 are inside their intervals; stand 1.25 is outside.
Feet -.028 exceed -.035, -.04 do not. Loop seam 3.54 <= 4.1 < 4.2.
Recovery cancels j1 once and must never invoke the LLM or GPU again.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        os.environ.update({name: str(Path(tmp) / name) for name in (
            "ANIMATION_CLIPS_DIR", "ANIMATION_CLIPS_INBOX_DIR",
            "ANIMATION_RIG_FILE", "ANIMATION_PUPPET_FILE", "ANIMATION_CLIPS_LICENSED_DIR")})
        from app.core import pose_animation as pa
        def check(hip=1.058, foot=-.028, seam=3.54, group="stand", loop=True):
            return pa.check_clip({"geometry": {"loop": {"seam_distance": seam}}},
                                 {"hips_y": [hip], "min_foot_y": foot}, group, loop)
        assert not check() and not check(hip=.657, group="seat")
        assert check(hip=1.25) and check(foot=-.04) and check(seam=4.2)
        assert not check(seam=4.2, loop=False)
        assert not check(hip=.95, foot=-.035, seam=4.1)
        assert not check(hip=1.20)
        assert check(hip=float("nan")) and check(foot=float("inf"))
        assert check(seam=float("nan"))
        assert pa.check_clip({}, {}, "stand", True)
        queue = Mock()
        queue.get_task_progress.return_value = {"phase": "hub", "hub_job": "j1"}
        service = Mock()
        with patch.object(pa, "get_task_queue", return_value=queue), \
             patch.object(pa, "prepare_motion") as prepare, \
             patch.object(pa, "get_image_service", return_value=service), \
             patch.object(pa, "resolve_image_route", return_value=SimpleNamespace(backend="routed")), \
             patch.object(pa, "_cancel_lost_job") as cancel:
            try:
                pa._handle({"_task_id": "restart", "mode": "entry", "key": "waving"})
            except RuntimeError as exc:
                assert "interrupted by restart" in str(exc)
            else:
                raise AssertionError("restart accepted")
            prepare.assert_not_called()
            service.generate_mesh_animation.assert_not_called()
            cancel.assert_called_once_with("routed", "j1")
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
        print("PASS: recovery, pair rejection, submission and check boundaries")


if __name__ == "__main__":
    main()
