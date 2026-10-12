#!/usr/bin/env python3
"""Smoke the complete job with disposable storage and stubbed generation.

Usage: .venv/bin/python scripts/smoke_pose_animation_publish.py

Every run ends in awaiting_choice and is published by choose(tid, 0) (plan v3
Task 5); the publish properties below hold for that choice.
A foreign waving clip forces waving-u. A second run replaces that owned clip.
Catalog failure restores byte-identical files; cancellation publishes nothing.
Stand hips 1.058, feet -.028 and loop seam 3.54 pass the specified limits.
A failed check keeps staging and leaves both catalog and library unchanged.
A competing rename waits on the same RLock through installation and commit.
"""
import errno
from copy import deepcopy
import fcntl
import threading
from contextlib import contextmanager
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from smoke_pose_animation_queue import structure
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(tmp)
        os.environ.update({name: str(root / suffix) for name, suffix in {
            "ANIMATION_CLIPS_DIR": "free", "ANIMATION_CLIPS_INBOX_DIR": "inbox",
            "ANIMATION_RIG_FILE": "rig.fbx", "ANIMATION_PUPPET_FILE": "puppet.glb",
            "ANIMATION_CLIPS_LICENSED_DIR": "licensed"}.items()})
        from app.core import pose_animation as pa, pose_catalog as pc, pose_catalog_edit as editor
        from app.core.db import init_schema
        init_schema()
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"groups": {"stand": {"default": "waving", "needs_place": False}},
            "entries": {"waving": {"prompt": "waving", "solo": True, "group": "stand", "animation": "waving"}}}))
        original_path = pc.catalog_path
        pc.catalog_path = lambda axis: catalog if axis == "pose" else original_path(axis)
        pc.reload_catalogs()
        free = paths.get_animation_clips_dir()
        free.mkdir()
        (free / "waving.fbx").write_bytes(b"foreign")
        paths.get_puppet_file().write_bytes(b"puppet")
        tq = pa.get_task_queue()
        pa.register()
        state = {"version": 0, "cancel": False, "bad": False}
        def generate(puppet, captions, seed, **kwargs):
            assert seed == 0 and captions == ["An object waves."] and kwargs["variants"] == 1
            assert puppet == str(paths.get_puppet_file())
            kwargs["on_job_id"]("j1", "fixture")
            assert tq.get_task_progress(state["tid"])["backend"] == "fixture"
            return {"ok": True, "blobs": [b"glTF-clip"], "results": [{"n": 0, "ok": True, "reason": ""}],
                    "backend": "fixture", "job_id": "j1"}
        from app.imagegen.backends import openai_mesh_animation as uni
        fixture = SimpleNamespace(name="fixture", motion_meta={
            "motion_source": "puppet", "caption_style": "object", "segment_seconds": 2.0,
            "max_variants": 4, "generator": "unimate", "license": uni.DEFAULT_LICENSE,
            "credit": uni.DEFAULT_CREDIT, "model_revision": uni.DEFAULT_MODEL_REVISION})
        def run(script, *, inputs, out_dir, **kwargs):
            if script == "clip_measure":
                if state["cancel"]:
                    tq.cancel_task(state["tid"])
                return {"ok": True, "data": {**structure(), "frames": 40, "hips_y": [1.25 if state["bad"] else 1.058],
                    "min_foot_y": -.028, "head_tilt_deg_median": 0}}
            assert script == "glb_to_ref_fbx" and kwargs["params"] == {"ref_hips_m": 1.13032, "format": "glb"}
            for name in ("motion", "rest"):
                (out_dir / (name + ".fbx")).write_bytes(b"source")
            return {"ok": True, "outputs": {name: out_dir / (name + ".fbx") for name in ("motion", "rest")}}
        def importing(kind, src, rest, *, out_dir, source_extra, **kwargs):
            assert kwargs["loop_s"] == 1.333 and kwargs["root_motion"] == "strip"
            out_dir.mkdir(parents=True)
            fbx, sidecar = out_dir / (kind + ".fbx"), out_dir / (kind + ".json")
            state["version"] += 1
            fbx.write_bytes(str(state["version"]).encode())
            meta = {"source": source_extra, "geometry": {"loop": {"seam_distance": 3.54}}}
            sidecar.write_text(json.dumps(meta))
            return {"fbx": fbx, "sidecar": sidecar, "meta": meta}
        def snapshot():
            return ({p.name: p.read_bytes() for p in free.iterdir()}, hashlib.sha256(catalog.read_bytes()).hexdigest())
        def execute(error=""):
            tid = pa.submit("entry", key="waving", seed=0)
            state["tid"] = tid
            try:
                result = pa._handle({"mode": "entry", "key": "waving", "seed": 0, "_task_id": tid})
                tq._finish_task(tid, "completed", result=result)
                assert result["state"] == "awaiting_choice"
                pa.choose(tid, 0)
                assert not error
            except RuntimeError as exc:
                assert error and error in str(exc), str(exc)
                tq._finish_task(tid, "failed", error=str(exc))
            return tid
        try:
            with patch.object(tq, "start"), patch.object(pa, "prepare_motion", return_value=pa.PreparedMotion(["An object waves."], True, None)), \
                 patch.object(pa, "get_image_service", return_value=SimpleNamespace(generate_mesh_animation=generate,
                                                           resolve_animation_backend=lambda name="": SimpleNamespace(backend=fixture))), \
                 patch.object(pa.runner, "run", side_effect=run), patch.object(pa, "import_source", side_effect=importing):
                untouched = snapshot()
                with patch.object(pa, "apply_generated_entry", side_effect=RuntimeError("catalog refused")):
                    execute("catalog refused")
                assert snapshot() == untouched
                state["cancel"] = True
                execute("cancelled")
                assert snapshot() == untouched
                state["cancel"] = False
                first = execute()
                assert not (paths.get_clips_inbox_dir() / ".pose_animation" / first).exists()
                assert json.loads(catalog.read_text())["entries"]["waving"]["animation"] == "waving-u"
                meta = json.loads((free / "waving-u.json").read_text())
                assert meta["license"] == "CC-BY-NC-4.0" and meta["credit"] == uni.DEFAULT_CREDIT
                assert meta["source"] == {"generator": "unimate", "generated_for_pose": "waving", "captions": ["An object waves."],
                    "seed": 0, "hub_job": "j1", "backend": "fixture", "model_revision": "174fc755ec248d0c98f27759b7a95648e7f05905",
                    "variant_index": 0, "puppet_sha256": hashlib.sha256(b"puppet").hexdigest()}
                execute()
                assert (free / "waving-u.fbx").read_bytes() == b"4" and not (free / "waving-u2.fbx").exists()
                before = snapshot()
                with patch.object(pa, "apply_generated_entry", side_effect=RuntimeError("catalog refused")):
                    execute("catalog refused")
                assert snapshot() == before
                apply = pa.apply_generated_entry
                def partial_edit(**kwargs):
                    apply(**kwargs)
                    document = json.loads(catalog.read_text())
                    document["entries"]["waving"]["animation"] = "partial"
                    editor.write_store("pose", document)
                    editor.write_store("pose", {"entries": {
                        "waving": dict(document["entries"]["waving"], animation="partial-world")}}, "world")
                    assert pc.get_catalog("pose")["waving"]["animation"] == "partial-world"
                    raise RuntimeError("partial catalog failure")
                with patch.object(pa, "apply_generated_entry", side_effect=partial_edit):
                    execute("partial catalog failure")
                assert snapshot() == before
                replace = os.replace
                def fail_fbx(source, target):
                    if Path(target).parent == free and Path(target).suffix == ".fbx" and (Path(source).parent.name == "clip" or Path(source).name != Path(target).name):
                        raise RuntimeError("fbx move failed")
                    return replace(source, target)
                with patch.object(pa.os, "replace", side_effect=fail_fbx):
                    execute("fbx move failed")
                assert snapshot() == before
                # A rename must wait until publish has finished the catalog commit.
                from app.core.keyed_lock import keyed_lock
                blocked, finished = threading.Event(), threading.Event()
                errors, threads = [], []
                class ObservedLock:
                    def __init__(self, namespace, key):
                        self.lock = keyed_lock(namespace, key)
                    def __enter__(self):
                        if not self.lock.acquire(blocking=False):
                            blocked.set()
                            assert self.lock.acquire(timeout=5)
                        return self
                    def __exit__(self, *args):
                        self.lock.release()
                def rename():
                    try:
                        pa.animation_clips.rename_clip("free", "waving.fbx", kind="foreign-renamed")
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        finished.set()
                def publish_while_rename_waits(**kwargs):
                    thread = threading.Thread(target=rename)
                    threads.append(thread)
                    thread.start()
                    assert blocked.wait(2), "rename did not contend on the publish library lock"
                    assert not finished.is_set(), "rename passed a publishing writer"
                    return apply(**kwargs)
                try:
                    with patch.object(pa.animation_clips, "keyed_lock", side_effect=ObservedLock, create=True), \
                         patch.object(pa, "apply_generated_entry", side_effect=publish_while_rename_waits):
                        execute()
                finally:
                    for thread in threads:
                        thread.join(5)
                assert finished.is_set() and not errors and all(not t.is_alive() for t in threads), errors
                assert (free / "foreign-renamed.fbx").read_bytes() == b"foreign"
                pa.animation_clips.rename_clip("free", "foreign-renamed.fbx", kind="waving")
                before = snapshot()
                print("PASS concurrent rename waits through publish installation and catalog commit")

                txn = editor.catalog_txn
                # Reject groups changed after the measurement check, without undoing the edit.
                publish = pa._publish
                for group in ("seat", "unsupported"):
                    changed = []
                    def stale_publish(**kwargs):
                        with txn("pose"):
                            document = json.loads(catalog.read_text())
                            document["entries"]["waving"]["group"] = group
                            editor.write_store("pose", document)
                        changed.append(snapshot())
                        return publish(**kwargs)
                    with patch.object(pa, "_publish", side_effect=stale_publish):
                        execute("place type")
                    assert snapshot() == changed[0]
                    document = json.loads(catalog.read_text())
                    document["entries"]["waving"]["group"] = "stand"
                    with txn("pose"):
                        editor.write_store("pose", document)
                before = snapshot()

                # Independent lock descriptors contend just like another process.
                def assert_file_locked():
                    with catalog.with_name(catalog.name + ".lock").open("a") as lock:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            return
                        fcntl.flock(lock, fcntl.LOCK_UN)
                        raise AssertionError("publish must hold the catalog file lock")
                read_store = pa.read_store
                def locked_snapshot(*args, **kwargs):
                    assert_file_locked()
                    return read_store(*args, **kwargs)
                def locked_partial_edit(**kwargs):
                    assert_file_locked()
                    assert kwargs["_locked"] is True
                    partial_edit(**kwargs)
                def same_device_replace(source, target):
                    if Path(source).parent != Path(target).parent:
                        raise OSError(errno.EXDEV, "simulated cross-device replace")
                    if Path(target) == catalog:
                        assert_file_locked()
                    return replace(source, target)
                catalog.chmod(0o640)
                with patch.object(pa.os, "replace", side_effect=same_device_replace):
                    execute()
                    before = snapshot()
                    world_before = deepcopy(editor.read_store("pose", "world")["entries"])
                    merged_before = deepcopy(pc.get_catalog("pose")["waving"])
                    reload_states = []
                    after_write = editor.after_write
                    def observed_after_write():
                        reload_states.append((snapshot(), deepcopy(editor.read_store("pose", "world")["entries"])))
                        after_write()
                    with patch.object(pa, "read_store", side_effect=locked_snapshot), \
                         patch.object(pa, "apply_generated_entry", side_effect=locked_partial_edit), \
                         patch.object(pa.animation_clips, "reload_clip_caches") as reload_clips, \
                         patch.object(editor, "after_write", side_effect=observed_after_write) as reload_catalog:
                        execute("partial catalog failure")
                        reload_clips.assert_not_called()
                        assert reload_catalog.call_count == 4, "three writes followed by exactly one rollback reload"
                        assert reload_states[-2] != (before, world_before)
                        assert reload_states[-1] == (before, world_before), "last reload must follow all restoration"
                        assert pc.get_catalog("pose")["waving"] == merged_before
                    assert snapshot() == before
                    assert catalog.stat().st_mode & 0o777 == 0o640

                # Cleanup is after commit: its failure cannot fail the job.
                with patch.object(pa.shutil, "rmtree", side_effect=OSError("staging removal failed")):
                    cleaned = execute()
                assert (free / "waving-u.fbx").exists()
                assert json.loads(catalog.read_text())["entries"]["waving"]["animation"] == "waving-u"
                assert {j["task_id"]: j for j in pa.recent_jobs()}[cleaned]["status"] == "completed"
                before = snapshot()
                state["cancel"] = True
                cancelled = execute("cancelled")
                assert snapshot() == before
                state["cancel"] = False
                state["bad"] = True
                failed = execute("no variant passed the check")
                assert snapshot() == before
                assert (paths.get_clips_inbox_dir() / ".pose_animation" / failed).exists()
                jobs = {j["task_id"]: j for j in pa.recent_jobs()}
                assert jobs[failed]["status"] == "failed" and jobs[cancelled]["status"] == "cancelled"
        finally:
            pc.catalog_path = original_path
            pc.reload_catalogs()
        print("PASS: publish, replacement, rollback, stale groups, EXDEV, caches, cleanup and failed check")


if __name__ == "__main__":
    main()
