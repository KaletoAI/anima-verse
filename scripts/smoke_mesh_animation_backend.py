#!/usr/bin/env python3
"""Standalone animation transport smoke, with no network or world writes.

Usage: ./.venv/bin/python scripts/smoke_mesh_animation_backend.py

Hand-derived expectations: missing, non-GLB and >64 MiB sources submit
nothing; captions join with a newline and seed 42 travels with the two
allowed alias settings and exactly one repetition. One verified GLB with a skin and exactly one animation returns
unchanged; absent skin, zero/two animations or a truncated container return nothing; absent, empty, null, malformed or mismatching hashes return nothing.
Downloads disable redirects and HTTP 302 or two GLBs return nothing. Caller cancellation
after one poll sends one cancel and raises; park timeout remains busy.
Additional checks cover caption/seed validation, output magic, safe download
URLs, ignored extra settings, availability and thread-local job identity.

Variant section (plan v3 Task 1), a reference-rig backend configured with
motion_source=reference_rig, source_slot=input_rig_path,
variant_param=input_num_samples, duration_param=input_duration and
segment_seconds=4: an FBX source travels as
files.input_rig_path = data:application/octet-stream;base64,<bytes>, the alias
gets input_num_samples=3 and input_duration=4.0, and neither
input_num_repetitions nor input_mesh_path. A GLB source is refused before the
POST (FBX magic required), and so is variants=5 against max_variants=4. Three
results where the third has no sha256 give 2 blobs in n order and a
last_result_meta of 3 entries, the third {ok: False, reason: "missing sha256"}.
A result whose bytes are neither glTF nor FBX is dropped with a reason; a
result beyond the requested count is dropped as "unrequested result"; a
non-model MIME (a preview PNG) is ignored without a meta entry. The puppet
backend's motion_meta carries the UniMate defaults.
"""
import base64
import hashlib
import json
import struct
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

def glb(document):
    chunk = json.dumps(document).encode()
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sII", b"glTF", 2, 20 + len(chunk)) + struct.pack("<II", len(chunk), 0x4E4F534A) + chunk


BLOB = glb({"asset": {"version": "2.0"}, "skins": [{}], "animations": [{}]})
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
            for document in ({"animations": [{}]}, {"skins": [{}]},
                             {"skins": [{}], "animations": []},
                             {"skins": [{}], "animations": [{}, {}]},
                             {"skins": [None], "animations": [{}]},
                             {"skins": [{}], "animations": [None]}):
                invalid = glb(document)
                assert run(blob=invalid, results=[{**result, "sha256": hashlib.sha256(invalid).hexdigest()}]) == [], document
            duplicate = glb(None) + BLOB[12:]
            duplicate = duplicate[:8] + struct.pack("<I", len(duplicate)) + duplicate[12:]
            for invalid in (duplicate, BLOB[:-1], BLOB[:4] + b"broken container"):
                assert run(blob=invalid, results=[{**result, "sha256": hashlib.sha256(invalid).hexdigest()}]) == []
            print("PASS structure: missing skin, zero/two animations and malformed GLB discarded")
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
            http.reset_mock()
            http.post.return_value = response({"job_id": JOB}, status=202)
            http.get.side_effect = [response({"status": "done", "results": [result, {**result, "n": 1}]}),
                                    response(content=BLOB)]
            assert backend.generate("ignored", "", params=params, log_meta=None) == [BLOB]
            assert http.get.call_count == 2
            assert [m["reason"] for m in backend.last_result_meta] == ["", "unrequested result"]
            print("PASS 6: a result beyond the requested count is not downloaded")
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
    variants_section()
    print("All animation backend smokes passed")


FBX = b"Kaydara FBX Binary  \x00\x1a\x00" + b"\x00" * 40


def variants_section():
    env = {"SKILL_IMAGEGEN_2_MODEL": "motion-kimodo",
           "SKILL_IMAGEGEN_2_API_KEY": "smoke-key",
           "SKILL_IMAGEGEN_2_POLL_INTERVAL": "0.001",
           "SKILL_IMAGEGEN_2_MOTION_SOURCE": "reference_rig",
           "SKILL_IMAGEGEN_2_SOURCE_SLOT": "input_rig_path",
           "SKILL_IMAGEGEN_2_CAPTION_STYLE": "person",
           "SKILL_IMAGEGEN_2_VARIANT_PARAM": "input_num_samples",
           "SKILL_IMAGEGEN_2_DURATION_PARAM": "input_duration",
           "SKILL_IMAGEGEN_2_SEGMENT_SECONDS": "4",
           "SKILL_IMAGEGEN_2_MAX_VARIANTS": "4",
           "SKILL_IMAGEGEN_2_GENERATOR": "kimodo",
           "SKILL_IMAGEGEN_2_LICENSE": "NVIDIA-Open-Model-License"}
    fbx1, fbx2 = FBX + b"one", FBX + b"two"
    sha = lambda b: hashlib.sha256(b).hexdigest()
    with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, env):
        rig = Path(td) / "reference.fbx"
        rig.write_bytes(FBX + b"rig")
        puppet = Path(td) / "puppet.glb"
        puppet.write_bytes(b"glTFsource")
        backend = OpenAIMeshAnimationBackend("kimodo", URL, 0, "SKILL_IMAGEGEN_2_")
        meta = backend.motion_meta
        assert meta["motion_source"] == "reference_rig" and meta["caption_style"] == "person"
        assert meta["segment_seconds"] == 4.0 and meta["max_variants"] == 4
        assert meta["generator"] == "kimodo" and meta["license"] == "NVIDIA-Open-Model-License"
        params = {"source_model_path": str(rig), "seed": 7, "captions": ["A person waves."],
                  "variants": 3}
        http = Mock()
        with patch("app.imagegen.backends._gateway_job.requests", http), \
             patch("app.imagegen.backends.openai_mesh_animation.requests", http), \
             patch("app.imagegen.backends._gateway_job.time.sleep"):
            def run(results, blobs, overrides=None):
                http.reset_mock()
                http.post.return_value = response({"job_id": JOB}, status=202)
                http.get.side_effect = ([response({"status": "done", "results": results})]
                                        + [response(content=b) for b in blobs])
                return backend.generate("ignored", "", params={**params, **(overrides or {})},
                                        log_meta=None)

            three = [{"n": 0, "mime": "application/octet-stream", "sha256": sha(fbx1)},
                     {"n": 1, "mime": "model/fbx", "sha256": sha(fbx2)},
                     {"n": 2, "mime": "model/fbx"}]
            assert run(three, [fbx1, fbx2]) == [fbx1, fbx2]
            body = http.post.call_args.kwargs["json"]
            assert body["params"] == {"seed": 7, "input_num_samples": 3, "input_duration": 4.0}, body["params"]
            assert body["files"] == {"input_rig_path": "data:application/octet-stream;base64,"
                                     + base64.b64encode(FBX + b"rig").decode()}
            assert body["model"] == "motion-kimodo" and body["prompt"] == "A person waves."
            got = backend.last_result_meta
            assert [m["ok"] for m in got] == [True, True, False], got
            assert got[2]["reason"] == "missing sha256" and got[2]["n"] == 2
            assert http.get.call_count == 3
            print("PASS V1: reference rig upload, variant + duration params, 2 of 3 results")
            for bad in ({"source_model_path": str(puppet)}, {"variants": 5}, {"variants": 0}):
                try:
                    run(three, [fbx1, fbx2], bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"accepted {bad}")
                assert http.post.call_count == 0
            print("PASS V2: GLB source and out-of-range variants refused before POST")
            junk = b"PK\x03\x04 not a model"
            mixed = [{"n": 0, "mime": "application/octet-stream", "sha256": sha(junk)},
                     {"n": 1, "mime": "image/png", "sha256": sha(b"png")},
                     {"n": 2, "mime": "model/fbx", "sha256": sha(fbx2)}]
            assert run(mixed, [junk, fbx2]) == [fbx2]
            got = backend.last_result_meta
            assert [m["n"] for m in got] == [0, 2], got
            assert got[0]["ok"] is False and "neither glTF nor FBX" in got[0]["reason"]
            print("PASS V3: foreign bytes dropped with a reason, preview PNG ignored")
            import requests as real_requests
            http.reset_mock()
            http.RequestException = real_requests.RequestException
            http.post.return_value = response({"job_id": JOB}, status=202)
            http.get.side_effect = [response({"status": "done", "results": three[:2] + [
                                        {"n": 2, "mime": "model/fbx", "sha256": sha(fbx1)}]}),
                                    response(content=fbx1),
                                    real_requests.Timeout("read timed out"),
                                    response(content=fbx1)]
            assert backend.generate("ignored", "", params=params, log_meta=None) == [fbx1, fbx1]
            got = backend.last_result_meta
            assert [m["ok"] for m in got] == [True, False, True], got
            assert "read timed out" in got[1]["reason"], got[1]
            print("PASS V3a: a download error on one variant does not stop its siblings")
            surplus = [{"n": 0, "mime": "model/fbx"},
                       {"n": 1, "mime": "model/fbx", "sha256": sha(fbx2)},
                       {"n": 2, "mime": "model/fbx", "sha256": sha(fbx1)}]
            assert run(surplus, [fbx2], {"variants": 1}) == [fbx2]
            got = backend.last_result_meta
            assert [(m["ok"], m["reason"]) for m in got] == [
                (False, "missing sha256"), (True, ""), (False, "unrequested result")], got
            assert http.get.call_count == 2
            print("PASS V3b: an invalid first result does not crowd out a valid later one")
    with tempfile.TemporaryDirectory() as td:
        plain = OpenAIMeshAnimationBackend("unimate", URL, 0, "SKILL_IMAGEGEN_9_")
        meta = plain.motion_meta
        assert meta["motion_source"] == "puppet" and meta["source_slot"] == "input_mesh_path"
        assert meta["caption_style"] == "object" and meta["variant_param"] == "input_num_repetitions"
        assert meta["duration_param"] == "" and meta["segment_seconds"] == 2.0
        assert meta["generator"] == "unimate" and meta["license"] == "CC-BY-NC-4.0"
        assert meta["credit"].startswith("UniMate:") and len(meta["model_revision"]) == 40
    print("PASS V4: puppet backend defaults are the UniMate values")
    from app.core import config as config_mod
    from app.core.config_schema import SECTIONS
    schema = SECTIONS["image_generation"]["sub_arrays"]["backends"]["fields"]
    fields = {"motion_source": "reference_rig", "source_slot": "input_rig_path",
              "caption_style": "person", "variant_param": "input_num_samples",
              "duration_param": "input_duration", "segment_seconds": 4.0, "max_variants": 3,
              "generator": "kimodo", "license": "NVIDIA-Open-Model-License",
              "credit": "Kimodo, NVIDIA", "model_revision": "v1.1"}
    with patch.dict(os.environ, {}, clear=False):
        config_mod._flatten_to_env({"image_generation": {"backends": [
            {"name": "kimodo", "api_type": "openai_mesh_animation", **fields}]}})
        bridged = OpenAIMeshAnimationBackend("kimodo", URL, 0, "SKILL_IMAGEGEN_1_").motion_meta
    assert bridged == {**fields, "segment_seconds": 4.0, "max_variants": 3}, bridged
    defaults = plain.motion_meta
    for key in fields:
        assert schema[key]["default"] == defaults[key], key
        assert schema[key]["applicable_for"] == ["openai_mesh_animation"], key
    print("PASS V5: config bridge carries every motion field; schema defaults = backend defaults")


if __name__ == "__main__":
    main()
