#!/usr/bin/env python3
"""Private event-controlled prop allocation/publish regressions; no media jobs.

Run: ./.venv/bin/python scripts/smoke_prop_generation_concurrency.py
The real allocator, worker, hub record and galleries run in temporary storage;
only the image/mesh provider and external geometry hooks are replaced.
Expected by hand: regenerate UID A leaves 1 record; while A runs, 0 further
requests start. Explicit append below cap 2 adds exactly 1 record (B); at
cap 2, 0 records are added and neither existing mesh is replaced. Dismissal
removes 1 repair from the listing, retaining all staged/gallery bytes.
A stored second slot, even inactive, moves the append index from 1 to 2;
a previously confirmed index 1 must be rejected without a provider call.
The dismiss route depends on require_admin: anonymous=401, player=403, admin=allowed.
"""
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PRIVATE = tempfile.TemporaryDirectory(prefix="prop-generation-concurrency-")
WORLD = Path(PRIVATE.name)
os.environ["STORAGE_DIR"] = str(WORLD)
os.environ["INSTANCE_DIR"] = str(WORLD / "instance")
from app.core import paths
paths.init(WORLD)
paths.init_instance(WORLD / "instance")
from app.core import props as store
from PIL import Image
REAL_RENDER_SOURCE = store._render_source


def png(color):
    out = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(out, "PNG")
    return out.getvalue()


class ControlledMesh:
    def __init__(self):
        self.started = [threading.Event(), threading.Event()]
        self.release = [threading.Event(), threading.Event()]
        self.lock = threading.Lock()
        self.inputs = []

    def generate_mesh(self, **kw):
        with self.lock:
            index = len(self.inputs)
            self.inputs.append(Path(kw["source_image_path"]).read_bytes())
        if index >= 2:
            raise AssertionError("a refused request must not reach the provider")
        self.started[index].set()
        if not self.release[index].wait(10):
            raise AssertionError("test did not release the mesh provider")
        target = Path(kw["output_path"])
        target.write_bytes(b"glTF-private-" + str(index).encode())
        return {"ok": True, "path": str(target), "format": "glb", "backend": "private-mesh"}


class GenerationConcurrency(unittest.TestCase):
    def setUp(self):
        self.mesh = ControlledMesh()
        self.threads = []
        real_thread = threading.Thread

        def tracked_thread(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            self.threads.append(thread)
            return thread

        def render(pid, backend, prompt, negative, variant=None, **kwargs):
            color = (30 + int(variant or 0) * 80, 60, 90)
            return store.save_source_image(pid, png(color), variant, backend="private-image", prompt=prompt,
                                           variant_uid=kwargs.get("variant_uid", ""))

        self.patches = [
            patch.object(store, "variant_max", return_value=2),
            patch.object(store.threading, "Thread", side_effect=tracked_thread),
            patch.object(store, "_render_source", side_effect=render),
            patch.object(store, "_extract_bbox", return_value=None),
            patch.object(store, "_areas_after_landing"),
            patch.object(store, "_autofill_slots"),
            patch.object(store, "bake_surfaces"),
            patch("app.imagegen.service.get_image_service", return_value=self.mesh),
            patch("app.blender.runner.is_available", return_value=False),
            patch("app.blender.runner.run", side_effect=AssertionError("external Blender work is forbidden")),
            patch("app.blender.refine.auto_retexture_enabled", return_value=False),
            patch("app.blender.refine.auto_lod_enabled", return_value=False),
            patch("app.blender.refine.auto_bake_vc_enabled", return_value=False),
            patch("app.blender.refine.measure_file", return_value=None),
            patch("app.core.task_queue.get_task_queue", return_value=SimpleNamespace(
                track_start=lambda *a, **kw: "", track_finish=lambda *a, **kw: None)),
        ]
        for item in self.patches:
            item.start()
        self.pid = store.create_prop(name="Private concurrency " + uuid4().hex[:8],
                                     description="authored subject", width_m=2, height_m=3, depth_m=1)["id"]

    def tearDown(self):
        for release in self.mesh.release:
            release.set()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(10)
        for item in reversed(self.patches):
            item.stop()
        self.assertFalse(any(thread.is_alive() for thread in self.threads))

    def start(self, **kwargs):
        return store.trigger_generation(self.pid, mesh_backend_glob="private-mesh", **kwargs)

    def finish(self, index):
        self.mesh.release[index].set()
        self.threads[index].join(10)
        self.assertFalse(self.threads[index].is_alive())

    def test_selected_regeneration_never_appends_and_running_prop_is_gated(self):
        row = store.list_variants(self.pid)[0]
        self.assertTrue(self.start(variant=0, variant_uid=row["uid"], prompt="first"))
        self.assertTrue(self.mesh.started[0].wait(5))
        self.assertFalse(self.start(prompt="second"))
        self.assertFalse(self.start(variant=0))
        self.assertEqual(store.pending_variants(self.pid), {self.pid: [0]})
        self.assertEqual(len(store.list_variants(self.pid)), 1)
        self.finish(0)
        self.assertEqual(store.model_path(self.pid, variant=0).read_bytes(), b"glTF-private-0")
        plan = {"kind": "append", "index": 1, "sourceUid": row["uid"], "sourceIndex": 0}
        self.assertTrue(self.start(generation_target=plan))
        self.assertTrue(self.mesh.started[1].wait(5))
        self.assertEqual(len(store.list_variants(self.pid)), 2)
        self.finish(1)
        with self.assertRaises(store.PropGenerationUnavailable):
            self.start(generation_target={"kind": "append", "index": 2,
                                         "sourceUid": row["uid"], "sourceIndex": 0})
        self.assertEqual(len(store.list_variants(self.pid)), 2)
        self.assertEqual(store.model_path(self.pid, variant=0).read_bytes(), b"glTF-private-0")
        self.assertEqual(store.model_path(self.pid, variant=1).read_bytes(), b"glTF-private-1")

    def test_explicit_append_does_not_fill_an_existing_empty_variant(self):
        row = store.list_variants(self.pid)[0]
        self.assertTrue(self.start(generation_target={"kind": "append", "index": 1,
                                  "sourceUid": row["uid"], "sourceIndex": 0}))
        self.assertTrue(self.mesh.started[0].wait(5))
        self.finish(0)
        self.assertIsNone(store.model_path(self.pid, variant=0))
        self.assertIsNotNone(store.model_path(self.pid, variant=1))
        self.assertEqual(len(store.list_variants(self.pid)), 2)

    def test_confirmation_revision_and_uid_refuse_before_starting_work(self):
        row = store.list_variants(self.pid)[0]
        revision = store.get_prop(self.pid)["revision"]
        store.set_variant_description(self.pid, 0, "changed after confirmation")
        with self.assertRaises(store.PropRevisionConflict):
            self.start(variant=0, variant_uid=row["uid"], base_revision=revision)
        with self.assertRaises(store.PropRevisionConflict):
            self.start(variant=0, variant_uid=str(uuid4()))
        self.assertEqual(store.pending_variants(self.pid), {})
        self.assertEqual(self.mesh.inputs, [])

    def test_changed_allocation_is_rejected_before_appending_or_charging(self):
        row = store.list_variants(self.pid)[0]
        confirmed = {"kind": "append", "index": 1, "sourceUid": row["uid"], "sourceIndex": 0}
        added = store.add_variant(self.pid)
        store.set_variant_active(self.pid, added, False)
        from fastapi import HTTPException
        from app.routes.world import _start_prop_generation
        before = store.read_sidecar(self.pid)
        with self.assertRaises(HTTPException) as caught:
            _start_prop_generation(self.pid, {"generation_target": confirmed},
                                   mesh_backend_glob="private-mesh")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(store.read_sidecar(self.pid), before)
        self.assertEqual(self.mesh.inputs, [])
        self.assertEqual(self.threads, [])

    def test_late_source_render_does_not_replace_another_uid_image(self):
        entered, release = threading.Event(), threading.Event()
        old_image = png((10, 20, 30))
        replacement_image = png((70, 80, 90))
        store.save_source_image(self.pid, old_image, 0)

        def generate(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release the image provider")
            return [png((200, 210, 220))]

        backend = SimpleNamespace(name="private-image", ref_slot_count=0, generate=generate)
        service = SimpleNamespace(
            _wait_for_explicit_backend=lambda pick: backend,
            run_on_backend=lambda selected, op: (op(selected), selected),
            run_on_backend_channel=lambda selected, run, **kw: run())
        try:
            with patch.object(store, "_render_source", REAL_RENDER_SOURCE), patch(
                    "app.imagegen.service.get_image_service", return_value=service):
                self.assertTrue(self.start(variant=0, image_only=True, image_backend_glob="private-image",
                                           prompt="explicit final prompt"))
                self.assertTrue(entered.wait(5))
                with store._author_mutex(self.pid):
                    meta = store.read_sidecar(self.pid)
                    meta[store.VARIANTS_KEY][0]["uid"] = str(uuid4())
                    store._write_sidecar(self.pid, meta)
                    store.save_source_image(self.pid, replacement_image, 0)
                replacement = store.source_path(self.pid, 0).read_bytes()
                release.set()
                self.threads[0].join(10)
                self.assertFalse(self.threads[0].is_alive())
                self.assertEqual(store.source_path(self.pid, 0).read_bytes(), replacement)
                self.assertEqual(self.mesh.inputs, [])
        finally:
            release.set()

    def test_late_mesh_does_not_publish_into_replacement_uid(self):
        self.assertTrue(self.start())
        self.assertTrue(self.mesh.started[0].wait(5))
        with store._author_mutex(self.pid):
            meta = store.read_sidecar(self.pid)
            meta[store.VARIANTS_KEY][0]["uid"] = str(uuid4())
            meta[store.VARIANTS_KEY][0]["description"] = "replacement identity"
            store._write_sidecar(self.pid, meta)
        self.finish(0)
        self.assertIsNone(store.model_path(self.pid, variant=0))
        self.assertEqual(store.list_variants(self.pid)[0]["description"], "replacement identity")
        self.assertEqual(store.pending_variants(self.pid), {})

    def legacy_mesh_op(self, *, ready=True):
        from app.core import hub_ops
        op = hub_ops.create("prop_mesh", "prop:" + self.pid + "|0|private-mesh|", {
            "prop_id": self.pid, "variant": 0, "name": "Legacy paid mesh",
            "guard_key": self.pid + "|0|private-mesh|", "mesh_backend_glob": "private-mesh",
            "src": "inputs/source.png", "tier": "full",
        }, label="Legacy paid mesh", thread_owned=True)
        op.path("inputs", "source.png").write_bytes(png((11, 22, 33)))
        if ready:
            built = op.path("mesh", "model.glb")
            built.write_bytes(b"glTF-already-paid-legacy")
            op.complete("mesh", {"path": op.rel(built), "format": "glb", "backend": "private-mesh"})
        return op

    def test_legacy_ready_mesh_survives_resume_and_replacement_until_explicit_repair(self):
        from app.core import hub_ops
        from app.routes.world import _start_prop_generation
        from fastapi import HTTPException
        op = self.legacy_mesh_op()
        old_uid = store.list_variants(self.pid)[0]["uid"]
        with store._author_mutex(self.pid):
            meta = store.read_sidecar(self.pid)
            meta[store.VARIANTS_KEY][0]["uid"] = str(uuid4())
            meta[store.VARIANTS_KEY][0]["description"] = "replacement must not receive an inferred result"
            store._write_sidecar(self.pid, meta)
        with self.assertRaises(hub_ops.HubOpDeferred):
            store._resume_open(op)
        retained = hub_ops.get(op.op_id)
        self.assertIsNotNone(retained)
        self.assertEqual(retained.status, hub_ops.DEFERRED)
        self.assertEqual(store.generation_repairs(self.pid)[0]["op_id"], op.op_id)
        self.assertEqual(store.generation_repairs(self.pid)[0]["status"], "ready")
        self.assertEqual(store.generation_repairs(self.pid)[0]["backend"], "private-mesh")
        self.assertEqual(store.generation_repairs(self.pid)[0]["original_name"], "Legacy paid mesh")
        self.assertEqual(retained.abs("mesh/model.glb").read_bytes(), b"glTF-already-paid-legacy")
        self.assertEqual(retained.abs("inputs/source.png").read_bytes(), png((11, 22, 33)))
        self.assertIsNone(store.model_path(self.pid, variant=0))
        self.assertEqual(hub_ops._resume_one(retained, SimpleNamespace(task_status=lambda _: "")), "skipped")
        row = store.list_variants(self.pid)[0]
        revision = store.get_prop(self.pid)["revision"]
        for body in [
            {"resume_op_id": op.op_id, "variant_uid": old_uid, "base_revision": revision},
            {"resume_op_id": op.op_id, "variant_uid": row["uid"], "base_revision": "stale"},
        ]:
            with self.assertRaises(HTTPException) as caught:
                _start_prop_generation(self.pid, body, variant=0)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIsNotNone(hub_ops.get(op.op_id))
        # Retention releases the old running claim. A different live operation
        # may take it, and explicit repair must then fail without losing bytes.
        competing = hub_ops.create("prop_mesh", "prop:" + self.pid + "|0|private-mesh|", {
            "prop_id": self.pid, "variant": 0, "variant_uid": row["uid"],
        }, thread_owned=True)
        with self.assertRaises(HTTPException) as caught:
            _start_prop_generation(self.pid, {
                "resume_op_id": op.op_id, "variant_uid": row["uid"], "base_revision": revision,
            }, variant=0)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(hub_ops.get(op.op_id).status, hub_ops.DEFERRED)
        self.assertTrue(retained.abs("mesh/model.glb").exists())
        self.assertEqual(self.threads, [])
        hub_ops.delete(competing)
        self.assertTrue(_start_prop_generation(self.pid, {
            "resume_op_id": op.op_id, "variant_uid": row["uid"], "base_revision": revision,
        }, variant=0))
        self.threads[0].join(10)
        self.assertFalse(self.threads[0].is_alive())
        self.assertEqual(store.model_path(self.pid, variant=0).read_bytes(), b"glTF-already-paid-legacy")
        self.assertEqual(store.list_variants(self.pid)[0]["uid"], row["uid"])
        self.assertEqual(store.list_variants(self.pid)[0]["description"],
                         "replacement must not receive an inferred result")
        self.assertIsNone(hub_ops.get(op.op_id))
        self.assertEqual(self.mesh.inputs, [])

    def test_discard_route_requires_admin(self):
        from app.core import auth_dependency
        from app.routes.prop_variants import router
        from fastapi import HTTPException
        from starlette.requests import Request
        route = next(route for route in router.routes
                     if route.path.endswith("/generation-repairs/{op_id}/dismiss"))
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        self.assertIn(auth_dependency.require_admin, dependencies)
        request = Request({"type": "http", "headers": []})
        for user, status in [(None, 401), ({"role": "user"}, 403)]:
            with patch.object(auth_dependency, "_get_session_user", return_value=user):
                with self.assertRaises(HTTPException) as caught:
                    auth_dependency.require_admin(request)
                self.assertEqual(caught.exception.status_code, status)
        with patch.object(auth_dependency, "_get_session_user", return_value={"role": "admin"}):
            self.assertEqual(auth_dependency.require_admin(request)["role"], "admin")

    def test_dismissed_repair_is_hidden_and_never_resumed_or_deleted(self):
        from app.core import hub_ops
        op = self.legacy_mesh_op()
        with self.assertRaises(hub_ops.HubOpDeferred):
            store._resume_open(op)
        self.assertEqual(len(store.generation_repairs(self.pid)), 1)
        with self.assertRaises(store.PropRevisionConflict):
            store.dismiss_generation_repair("other-prop", op.op_id)
        store.dismiss_generation_repair(self.pid, op.op_id)
        self.assertEqual(store.generation_repairs(self.pid), [])
        retained = hub_ops.get(op.op_id)
        self.assertTrue(retained.state["dismissed_at"])
        self.assertEqual(retained.abs("mesh/model.glb").read_bytes(), b"glTF-already-paid-legacy")
        self.assertEqual(hub_ops._resume_one(retained, SimpleNamespace(task_status=lambda _: "")), "skipped")
        row = store.list_variants(self.pid)[0]
        with self.assertRaises(store.PropRevisionConflict):
            store.trigger_generation_repair(self.pid, op.op_id, variant=0, variant_uid=row["uid"],
                                           base_revision=store.get_prop(self.pid)["revision"])
        self.assertEqual(self.mesh.inputs, [])

    def test_explicit_legacy_repair_uses_confirmed_gallery_not_old_publish_path(self):
        from app.core import hub_ops
        op = self.legacy_mesh_op()
        old_path = hub_ops.gallery_path(op, store.model_gallery(self.pid, 0), "path", ".glb")
        with self.assertRaises(hub_ops.HubOpDeferred):
            store._resume_open(op)
        target_index = store.add_variant(self.pid)
        self.assertEqual(target_index, 1)
        target = store.list_variants(self.pid)[1]
        revision = store.get_prop(self.pid)["revision"]
        self.assertTrue(store.trigger_generation_repair(
            self.pid, op.op_id, variant=1, variant_uid=target["uid"], base_revision=revision))
        self.threads[0].join(10)
        self.assertFalse(self.threads[0].is_alive())
        self.assertEqual(store.model_path(self.pid, variant=1).read_bytes(), b"glTF-already-paid-legacy")
        self.assertIsNone(store.model_path(self.pid, variant=0))
        self.assertFalse(old_path.exists())
        self.assertEqual(self.mesh.inputs, [])

    def test_legacy_submitted_job_is_collected_not_cancelled_before_identity_repair(self):
        from app.core import hub_ops
        from app.core.timeutils import utc_now_iso
        op = self.legacy_mesh_op(ready=False)
        op.update_state(lambda state: state.update(jobs={"mesh": {
            "pid": "previous-process", "phase": "submitted", "job_id": "already-paid-job",
            "backend": "private-legacy", "api_url": "https://private.invalid",
            "submitted_at": utc_now_iso(), "attach_params": {},
        }}))
        backend = SimpleNamespace(name="private-legacy", api_url="https://private.invalid",
                                  attach=lambda *a, **kw: [b"glTF-collected-legacy"])
        with patch.object(hub_ops, "find_backend", return_value=backend), patch.object(
                hub_ops, "_cancel_jobs", side_effect=AssertionError("must not cancel retained paid work")):
            with self.assertRaises(hub_ops.HubOpDeferred):
                store._resume_open(op)
        retained = hub_ops.get(op.op_id)
        self.assertIsNotNone(retained)
        self.assertEqual(retained.stage("mesh").collected()["blobs"], [b"glTF-collected-legacy"])
        self.assertEqual(retained.stage("mesh").job["job_id"], "already-paid-job")
        self.assertEqual(store.generation_repairs(self.pid)[0]["status"], "collected")
        self.assertFalse(store.generation_repairs(self.pid)[0]["mesh_ready"])
        self.assertTrue(store.generation_repairs(self.pid)[0]["can_resume"])
        self.assertIsNone(store.model_path(self.pid, variant=0))
        self.assertEqual(self.mesh.inputs, [])

    def test_manual_legacy_repair_collection_failure_retains_paid_work_until_recovery(self):
        from app.core import hub_ops
        from app.core.timeutils import utc_now_iso
        op = self.legacy_mesh_op(ready=False)
        op.update_state(lambda state: state.update(jobs={"mesh": {
            "pid": "previous-process", "phase": "submitted", "job_id": "same-paid-job",
            "backend": "private-legacy", "api_url": "https://private.invalid",
            "submitted_at": utc_now_iso(), "attach_params": {},
        }}))
        second_started, release_second = threading.Event(), threading.Event()
        attempts = []

        def attach(job_id, *args, **kwargs):
            attempts.append(job_id)
            if len(attempts) == 1:
                raise RuntimeError("provider result is not available yet")
            if len(attempts) == 2:
                second_started.set()
                if not release_second.wait(10):
                    raise AssertionError("test did not release collection")
                raise RuntimeError("provider still temporarily unavailable")
            return [b"glTF-paid-recovered-once"]

        def finish_attached_mesh(**kwargs):
            stage = kwargs["hub_stage"]
            if stage.prepare() != "attach":
                raise AssertionError("legacy repair must never submit a new provider job")
            blobs = (stage.collected() or stage.collect())["blobs"]
            Path(kwargs["output_path"]).write_bytes(blobs[0])
            return {"ok": True, "path": kwargs["output_path"], "format": "glb", "backend": "private-legacy"}

        backend = SimpleNamespace(name="private-legacy", api_url="https://private.invalid", attach=attach)
        source = op.abs("inputs/source.png").read_bytes()
        try:
            with patch.object(hub_ops, "find_backend", return_value=backend), patch.object(
                    hub_ops, "_cancel_jobs", side_effect=AssertionError("retained repair must not cancel")), patch(
                    "app.imagegen.service.get_image_service",
                    return_value=SimpleNamespace(generate_mesh=finish_attached_mesh)):
                with self.assertRaises(hub_ops.HubOpDeferred):
                    store._resume_open(op)
                self.assertEqual(store.generation_repairs(self.pid)[0]["status"], "waiting_provider")
                row = store.list_variants(self.pid)[0]
                revision = store.get_prop(self.pid)["revision"]
                self.assertTrue(store.trigger_generation_repair(
                    self.pid, op.op_id, variant=0, variant_uid=row["uid"], base_revision=revision))
                self.assertTrue(second_started.wait(5))
                release_second.set()
                self.threads[0].join(10)
                self.assertFalse(self.threads[0].is_alive())
                retained = hub_ops.get(op.op_id)
                self.assertIsNotNone(retained)
                self.assertEqual(retained.status, hub_ops.DEFERRED)
                self.assertEqual(retained.abs("inputs/source.png").read_bytes(), source)
                self.assertEqual(retained.stage("mesh").job["job_id"], "same-paid-job")
                self.assertIsNone(store.model_path(self.pid, variant=0))
                self.assertEqual(attempts, ["same-paid-job", "same-paid-job"])
                self.assertTrue(store.trigger_generation_repair(
                    self.pid, op.op_id, variant=0, variant_uid=row["uid"], base_revision=revision))
                self.threads[1].join(10)
                self.assertFalse(self.threads[1].is_alive())
                self.assertEqual(store.model_path(self.pid, variant=0).read_bytes(), b"glTF-paid-recovered-once")
                self.assertIsNone(hub_ops.get(op.op_id))
                self.assertEqual(attempts, ["same-paid-job"] * 3)
        finally:
            release_second.set()

    def test_deferred_legacy_task_release_preserves_files_without_starting_a_worker(self):
        from app.core import hub_ops
        op = self.legacy_mesh_op()
        op.set_fields(owner_kind="task", owner="old-task")
        with self.assertRaises(hub_ops.HubOpDeferred):
            store._resume_open(op)
        hub_ops.release_task_ops("old-task")
        retained = hub_ops.get(op.op_id)
        self.assertIsNotNone(retained)
        self.assertEqual(retained.owner_kind, "thread")
        self.assertTrue(retained.abs("mesh/model.glb").exists())
        self.assertEqual(self.threads, [])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        PRIVATE.cleanup()
