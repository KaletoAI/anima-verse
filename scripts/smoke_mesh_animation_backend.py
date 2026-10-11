#!/usr/bin/env python3
"""Standalone animation transport smoke, with no network or world writes.

Usage: ./.venv/bin/python scripts/smoke_mesh_animation_backend.py

Hand-derived expectations: missing, non-GLB and >64 MiB sources submit
nothing; captions join with a newline and seed 42 travels with the two
allowed alias settings and exactly one repetition. One verified GLB returns
unchanged; absent, empty, null, malformed or mismatching hashes return nothing.
Downloads disable redirects and HTTP 302 or two GLBs return nothing. Caller cancellation
after one poll sends one cancel and raises; park timeout remains busy.
Additional checks cover caption/seed validation, output magic, safe download
URLs, ignored extra settings, availability and thread-local job identity.
"""
import base64
import hashlib
import os
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.imagegen.backends.openai_mesh_animation import OpenAIMeshAnimationBackend
from app.imagegen.base import BackendBusyError, GenerationCancelled

BLOB = b"glTF" + b"animated fixture" * 10
JOB = "animation-job-1"
URL = "https://hub.invalid"


def response(body=None, content=b"json", status=200):
    return SimpleNamespace(status_code=status, content=content, text="", headers={},
                           json=lambda: body)


def main():
    env = {"SKILL_IMAGEGEN_1_MODEL": "mesh-unimate",
           "SKILL_IMAGEGEN_1_API_KEY": "smoke-key",
           "SKILL_IMAGEGEN_1_CATEGORY": "",
           "SKILL_IMAGEGEN_1_POLL_INTERVAL": "0.001",
           "SKILL_IMAGEGEN_1_EXTRA_PARAMS":
           '{"input_cfg_scale":3.0,"input_chain_overlap":10,"input_num_repetitions":9,"seed":99}'}
    result = {"n": 0, "mime": "model/gltf-binary",
              "sha256": hashlib.sha256(BLOB).hexdigest(),
              "url": "https://foreign.invalid/steal-key"}
    with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, env):
        source = Path(td) / "source.glb"
        source.write_bytes(b"glTFsource")
        backend = OpenAIMeshAnimationBackend("animation", URL, 0, "SKILL_IMAGEGEN_1_")
        params = {"source_model_path": str(source), "seed": 42,
                  "captions": ["walk forward", "wave hello"]}
        http = Mock()
        with patch("app.imagegen.backends._gateway_job.requests", http), \
             patch("app.imagegen.backends.openai_mesh_animation.requests", http), \
             patch("app.imagegen.backends._gateway_job.time.sleep"):
            def run(overrides=None, results=None, blob=BLOB, status=None, download_status=200):
                http.reset_mock()
                http.post.return_value = response({"job_id": JOB}, status=202)
                http.get.side_effect = [response(status or {"status": "done", "results":
                                        [result] if results is None else results}),
                                        response(content=blob, status=download_status)]
                return backend.generate("ignored", "", params={**params, **(overrides or {})},
                                        log_meta=None)

            def rejects(overrides, message=None, exc=ValueError):
                try:
                    run(overrides)
                except exc as error:
                    if message is not None:
                        assert str(error) == message, str(error)
                else:
                    raise AssertionError("invalid request accepted")
                assert http.post.call_count == 0

            rejects({"source_model_path": ""}, "source model missing")
            print("PASS 1: missing source, no POST")
            bad = Path(td) / "bad.glb"
            bad.write_bytes(b"invalid")
            rejects({"source_model_path": str(bad)})
            print("PASS 2: non-GLB source, no POST")
            large = Path(td) / "large.glb"
            with large.open("wb") as f:
                f.truncate(64 * 1024 * 1024 + 1)
            rejects({"source_model_path": str(large)})
            print("PASS 3: oversized sparse source, no POST")
            ids = []
            assert run({"on_job_id": ids.append}) == [BLOB]
            body = http.post.call_args.kwargs["json"]
            assert body == {"model": "mesh-unimate", "mode": "async",
                            "prompt": "walk forward\nwave hello",
                            "params": {"seed": 42, "input_cfg_scale": 3.0,
                                       "input_chain_overlap": 10, "input_num_repetitions": 1},
                            "files": {"input_mesh_path": "data:model/gltf-binary;base64," +
                                      base64.b64encode(b"glTFsource").decode()}}
            assert ids == [JOB] and backend.last_job_id == JOB
            assert http.get.call_args.args[0] == URL + "/v1/jobs/" + JOB + "/result/0"
            assert http.get.call_args.kwargs["headers"] == {"Authorization": "Bearer smoke-key"}
            assert http.get.call_args.kwargs.get("allow_redirects") is False
            print("PASS 4: async payload, callback, verified result, safe URL, redirects disabled")
            assert run(download_status=302) == []
            assert http.get.call_args.kwargs.get("allow_redirects") is False
            assert http.get.call_count == 2
            print("PASS 4a: HTTP 302 download discarded")
            assert run(results=[{**result, "sha256": "0" * 64}]) == []
            print("PASS 5: hash mismatch discarded")
            absent_checksum = {k: v for k, v in result.items() if k != "sha256"}
            assert run(results=[absent_checksum]) == [], "absent checksum accepted"
            print("PASS 5a: absent checksum discarded")
            for checksum in ("", None, "abc", "g" * 64, 123, " " + result["sha256"]):
                with patch("app.imagegen.backends.openai_mesh_animation.logger") as log:
                    assert run(results=[{**result, "sha256": checksum}]) == [], repr(checksum)
                    assert log.error.called
            print("PASS 5b: empty, null and malformed checksums discarded")
            assert run(results=[{**result, "sha256": result["sha256"].upper()}]) == [BLOB]
            with patch("app.imagegen.backends.openai_mesh_animation.logger") as log:
                assert run(results=[result, {**result, "n": 1}]) == []
                assert any("expected exactly one result" in c.args[0]
                           for c in log.error.call_args_list)
            assert http.get.call_count == 1
            print("PASS 6: two GLBs discarded before download")
            checks = iter([False, True])
            try:
                run({"should_cancel": lambda: next(checks)}, status={"status": "running"})
            except GenerationCancelled as error:
                assert str(error) == JOB
            else:
                raise AssertionError("cancel did not propagate")
            assert http.get.call_count == 1
            assert http.post.call_count == 2
            assert http.post.call_args.args[0] == URL + "/v1/jobs/" + JOB + "/cancel"
            print("PASS 7: cancellation after one poll, one cancel POST")
            try:
                run(status={"status": "failed", "error": "park timeout: backend busy for >600s"})
            except BackendBusyError:
                pass
            else:
                raise AssertionError("park timeout lost busy classification")
            print("PASS 8: park timeout remains BackendBusyError")
            for captions in ([], ["a", "b", "c", "d"]):
                rejects({"captions": captions})
            rejects({"seed": None}, exc=TypeError)
            assert run(blob=b"invalid", results=[{**result, "sha256": hashlib.sha256(b"invalid").hexdigest()}]) == []
            assert run(results=[]) == []
            assert backend.category == "mesh2anim" and backend.MEDIA_TYPE == "animation"
            other_thread = []
            t = threading.Thread(target=lambda: other_thread.append(backend.last_job_id))
            t.start()
            t.join()
            assert other_thread == [""] and backend.last_job_id == JOB
            http.get.side_effect = None
            http.get.return_value = response({"data": []})
            assert backend.check_availability()
            assert http.get.call_args.args[0] == URL + "/v1/models"
            http.get.return_value = response(status=403)
            assert not backend.check_availability()
            print("PASS extras: validation, output magic, availability, thread-local ID")
    print("All animation backend smokes passed")


if __name__ == "__main__":
    main()
