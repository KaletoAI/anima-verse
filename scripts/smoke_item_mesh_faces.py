#!/usr/bin/env python3
"""Smoke: per-item 3D mesh face count request, automatic post-generation LOD reduction, and manual reduce.

Usage:
    ./.venv/bin/python scripts/smoke_item_mesh_faces.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp directory
before importing any app module or app.server. Never touches worlds/ or instance/.

Hand-derived expectations:
[a] POST /inventory/items/{id}/mesh/generate without a JSON body queues generation
    and passes face_num == 20000 (DEFAULT_FACE_NUM) to get_image_service().generate_mesh.
[b] When generate_mesh delivers 100000 triangles and face_num == 20000
    (100000 > 20000 * 1.05 == 21000), app.blender.runner.run is called once with
    script == "lod", params["ratios"] == [0.2] (20000 / 100000) and
    params["merge_vertices"] is True. The reduced fixture (18400 tris, max_x=0.18)
    is published: meta has status == "done", face_num == 20000, tris_delivered == 100000,
    tris == 18400, bbox == [0.0, 0.0, 0.0, 0.18, 0.1, 0.05], and no reduce_error.
[c] When generate_mesh delivers 20800 triangles and face_num == 20000
    (20800 <= 21000 = 20000 * 1.05), runner.run is called 0 times and meta["tris"] == 20800.
[d] When runner.run fails during generation (ok=False, error="lod boom"), the delivered
    100000-triangle mesh is still published unreduced (post-steps never discard),
    meta["status"] == "done", meta["tris"] == 100000, and meta["reduce_error"] == "lod boom".
[e] normalize_face_num: None -> 20000, "30000" -> 30000; 499, 200001, True, 1.5 each
    raise ValueError naming the range [500, 200000].
[f] start_reduce / POST /mesh/reduce:
    - on a 15000-tri mesh with face_num=20000 -> {"status": "unchanged", "tris": 15000},
      0 lod calls;
    - on a 100000-tri mesh with face_num=20000 -> {"status": "queued"}, 1 lod call with
      ratios == [0.2] and merge_vertices is True; after joining item-mesh-reduce-* threads,
      meta has status == "done", reduced_from == 100000, tris == 18400, face_num == 20000,
      bbox == [0.0, 0.0, 0.0, 0.18, 0.1, 0.05], and prior backend == "fake-mesh" is kept;
    - when lod fails during an explicit reduce, old model.glb bytes stay untouched and
      meta has status == "failed" with error set and prior backend/bbox kept;
    - mesh_meta backfills tris from model.glb when an older model.json lacks tris.
[g] start_reduce on an item without model.glb raises LookupError (HTTP 404 on /mesh/reduce).
[h] Task queue tracking (monkeypatching app.core.task_queue.get_task_queue):
    - mesh generate -> 1 track_start("model3d_generation", "Item mesh: <name>",
      agent_name="<name>", start_running=True) + 1 track_finish(error=="");
      published mesh with reduce_error also finishes with error=="";
    - failing mesh generate -> 1 track_start + 1 track_finish with non-empty error;
    - mesh reduce -> 1 track_start("model3d_generation", "Item mesh reduce: <name>",
      agent_name="<name>", start_running=True) + 1 track_finish(error==""), and
      non-empty error when reduce fails;
    - generate_item_image_sync(..., track=False) -> 0 track_start / 0 track_finish;
    - generate_item_image_sync(...) default track=True -> 1 track_start("image_gen",
      "Item image: <name>", agent_name="<name>") + 1 track_finish(error==""),
      "no image produced" when False is returned, and exception text on failure.
"""
import json
import logging
import os
import struct
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []

# Minimal 1x1 transparent PNG (67 bytes).
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def check(label, actual, expected):
    ok = actual == expected
    status = "OK  " if ok else "FAIL"
    print(f"  {status} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def check_raises(label, exc_type, fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except exc_type as exc:
        print(f"  OK   {label}: raised {exc_type.__name__}({str(exc)!r})")
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {label}: raised {type(exc).__name__}({exc!r}) instead of {exc_type.__name__}")
        FAILURES.append(label)
        return ""
    print(f"  FAIL {label}: returned {res!r} instead of raising {exc_type.__name__}")
    FAILURES.append(label)
    return ""


def build_tris_glb(num_tris: int, max_x: float = 0.2) -> bytes:
    """Build a valid glTF 2.0 GLB with 3 vertices and ``num_tris`` triangles."""
    pos_bytes = struct.pack("<9f", 0.0, 0.0, 0.0, float(max_x), 0.0, 0.0, 0.0, 0.1, 0.05)
    idx_bytes = struct.pack("<3H", 0, 1, 2) * int(num_tris)
    bin_chunk = pos_bytes + idx_bytes
    bin_chunk += b"\x00" * (-len(bin_chunk) % 4)

    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [round(float(max_x), 6), 0.1, 0.05],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 3 * int(num_tris),
                "type": "SCALAR",
            },
        ],
    }
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)

    body = (
        struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def join_item_mesh_threads(timeout_s: float = 10.0) -> None:
    """Join all active item-mesh worker threads (both generate and reduce)."""
    for th in list(threading.enumerate()):
        if th is not threading.current_thread() and th.name.startswith("item-mesh-"):
            th.join(timeout=timeout_s)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="item-mesh-faces-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema
        init_schema()

        from app.blender import runner as blender_runner
        from app.core import auth_dependency, item_images, item_mesh, task_queue
        from app.imagegen import routing as imagegen_routing, service as imagegen_service
        from app.models import character as character_model
        from app.models.inventory import _get_item_dir, add_item, update_item

        # Pre-build fixture GLBs once.
        glb_100k = build_tris_glb(100000, max_x=0.25)
        glb_20800 = build_tris_glb(20800, max_x=0.22)
        glb_18400 = build_tris_glb(18400, max_x=0.18)
        glb_15000 = build_tris_glb(15000, max_x=0.15)

        check("triangle_count(100k)", item_mesh.triangle_count(glb_100k), 100000)
        check("triangle_count(18400)", item_mesh.triangle_count(glb_18400), 18400)

        # [e] normalize_face_num
        print("[e] normalize_face_num")
        check("[e] None -> 20000", item_mesh.normalize_face_num(None), 20000)
        check("[e] '30000' -> 30000", item_mesh.normalize_face_num("30000"), 30000)
        msg_low = check_raises("[e] 499 -> ValueError", ValueError, item_mesh.normalize_face_num, 499)
        check("[e] error names range", "500" in msg_low and "200000" in msg_low, True)
        check_raises("[e] 200001 -> ValueError", ValueError, item_mesh.normalize_face_num, 200001)
        check_raises("[e] True -> ValueError", ValueError, item_mesh.normalize_face_num, True)
        check_raises("[e] 1.5 -> ValueError", ValueError, item_mesh.normalize_face_num, 1.5)

        gen_calls = []
        lod_calls = []
        state = {
            "deliver_bytes": glb_15000,
            "gen_fail": False,
            "lod_fail": False,
            "lod_bytes": glb_18400,
            "lod_tris": 18400,
        }

        class FakeImageService:
            pool = None

            def generate_mesh(self, source_image_path, output_path, **kwargs):
                gen_calls.append({"source_image_path": source_image_path, "output_path": output_path, **kwargs})
                if state["gen_fail"]:
                    return {"ok": False, "error": "mesh backend down"}
                Path(output_path).write_bytes(state["deliver_bytes"])
                return {"ok": True, "path": output_path, "backend": "fake-mesh", "routing": {"chain": ["fake-mesh"]}}

        def fake_runner_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
            lod_calls.append({
                "script": script,
                "inputs": dict(inputs or {}),
                "params": dict(params or {}),
                "out_dir": out_dir,
                "timeout_s": timeout_s,
            })
            if state["lod_fail"]:
                return {"ok": False, "error": "lod boom", "data": {}, "outputs": {}}
            out_path = Path(out_dir) / f"model_lod{state['lod_tris']}.glb"
            out_path.write_bytes(state["lod_bytes"])
            return {
                "ok": True,
                "error": "",
                "data": {"stages": [{"tris": state["lod_tris"], "ratio": (params or {}).get("ratios", [0])[0]}]},
                "outputs": {f"lod{state['lod_tris']}": str(out_path)},
            }

        fake_service = FakeImageService()

        logging.disable(logging.INFO)
        from app.server import app as server_app
        from fastapi.testclient import TestClient

        def session_user(request):
            if request.headers.get("x-test-user") == "admin":
                return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
            return None

        def make_imaged_item(name: str) -> str:
            it = add_item(name=name, description=f"Item {name}")
            iid = it["id"]
            idir = _get_item_dir(iid, create=True)
            (idir / "image.png").write_bytes(TINY_PNG)
            update_item(iid, {"image": "image.png"})
            return iid

        item_a_id = make_imaged_item("Brass Key")
        item_b_id = make_imaged_item("Ornate Chalice")
        item_c_id = make_imaged_item("Simple Bowl")
        item_d_id = make_imaged_item("Carved Idol")
        item_no_mesh_id = make_imaged_item("Unmeshed Coin")

        admin_h = {"x-test-user": "admin"}

        with (
            patch.object(auth_dependency, "_get_session_user", side_effect=session_user),
            patch.object(imagegen_service, "get_image_service", return_value=fake_service),
            patch.object(blender_runner, "run", side_effect=fake_runner_run),
        ):
            client = TestClient(server_app)

            # [a] Generate without body -> face_num == 20000
            print("[a] Generate without body uses face_num=20000")
            state["deliver_bytes"] = glb_15000
            r_gen_a = client.post(f"/inventory/items/{item_a_id}/mesh/generate", headers=admin_h)
            join_item_mesh_threads()
            check("[a] HTTP 200", r_gen_a.status_code, 200)
            check("[a] queued response", r_gen_a.json(), {"status": "queued"})
            check("[a] generate_mesh face_num", gen_calls[-1].get("face_num"), 20000)
            check("[a] no lod needed for 15000 tris", len(lod_calls), 0)

            r_bad = client.post(
                f"/inventory/items/{item_a_id}/mesh/generate",
                json={"face_num": 499},
                headers=admin_h,
            )
            check("[a] invalid face_num -> HTTP 400", r_bad.status_code, 400)

            # [b] Delivered 100000 tris, face_num 20000 -> 1 lod call with ratios=[0.2], merge_vertices=True
            print("[b] Delivered 100000 tris reduced to ~20000 via Blender lod")
            lod_calls.clear()
            state["deliver_bytes"] = glb_100k
            state["lod_fail"] = False
            r_gen_b = client.post(
                f"/inventory/items/{item_b_id}/mesh/generate",
                json={"face_num": 20000},
                headers=admin_h,
            )
            join_item_mesh_threads()
            check("[b] HTTP 200", r_gen_b.status_code, 200)
            check("[b] exactly 1 lod call", len(lod_calls), 1)
            if lod_calls:
                check("[b] script == 'lod'", lod_calls[0]["script"], "lod")
                check("[b] ratios == [0.2]", lod_calls[0]["params"].get("ratios"), [0.2])
                check("[b] merge_vertices is True", lod_calls[0]["params"].get("merge_vertices") is True, True)
            meta_b = item_mesh.mesh_meta(item_b_id) or {}
            check("[b] status done", meta_b.get("status"), "done")
            check("[b] meta face_num", meta_b.get("face_num"), 20000)
            check("[b] meta tris_delivered", meta_b.get("tris_delivered"), 100000)
            check("[b] meta tris", meta_b.get("tris"), 18400)
            check("[b] meta bbox recomputed", meta_b.get("bbox"), [0.0, 0.0, 0.0, 0.18, 0.1, 0.05])
            check("[b] no reduce_error", "reduce_error" in meta_b, False)
            glb_b_path, _ = item_mesh.mesh_paths(item_b_id)
            check("[b] published bytes are reduced GLB", glb_b_path.read_bytes() == glb_18400, True)

            # [c] Delivered 20800 tris (<= 21000 = 20000 * 1.05) -> no lod call
            print("[c] Delivered 20800 tris within 1.05 tolerance -> no lod call")
            lod_calls.clear()
            state["deliver_bytes"] = glb_20800
            r_gen_c = client.post(
                f"/inventory/items/{item_c_id}/mesh/generate",
                json={"face_num": 20000},
                headers=admin_h,
            )
            join_item_mesh_threads()
            check("[c] HTTP 200", r_gen_c.status_code, 200)
            check("[c] 0 lod calls", len(lod_calls), 0)
            meta_c = item_mesh.mesh_meta(item_c_id) or {}
            check("[c] meta tris == 20800", meta_c.get("tris"), 20800)

            # [d] lod fails during generate -> unreduced GLB published, reduce_error set, status done
            print("[d] LOD failure during generate keeps delivered GLB")
            lod_calls.clear()
            state["deliver_bytes"] = glb_100k
            state["lod_fail"] = True
            r_gen_d = client.post(
                f"/inventory/items/{item_d_id}/mesh/generate",
                json={"face_num": 20000},
                headers=admin_h,
            )
            join_item_mesh_threads()
            check("[d] HTTP 200", r_gen_d.status_code, 200)
            check("[d] 1 lod call attempted", len(lod_calls), 1)
            meta_d = item_mesh.mesh_meta(item_d_id) or {}
            check("[d] status done", meta_d.get("status"), "done")
            check("[d] tris == 100000 (unreduced)", meta_d.get("tris"), 100000)
            check("[d] reduce_error set", meta_d.get("reduce_error"), "lod boom")
            glb_d_path, meta_d_path = item_mesh.mesh_paths(item_d_id)
            check("[d] published bytes unreduced", glb_d_path.read_bytes() == glb_100k, True)

            # [f] start_reduce: unchanged on 15000, queued & reduced on 100000, failed leaves old GLB intact
            print("[f] start_reduce & POST /mesh/reduce")
            lod_calls.clear()
            state["lod_fail"] = False
            res_unchanged = item_mesh.start_reduce(item_a_id, 20000)
            check("[f] 15000 tris unchanged", res_unchanged, {"status": "unchanged", "tris": 15000})
            check("[f] 0 lod calls on unchanged", len(lod_calls), 0)

            # Also verify mesh_meta backfills tris for legacy model.json lacking 'tris'
            raw_meta_d = json.loads(meta_d_path.read_text(encoding="utf-8"))
            raw_meta_d.pop("tris", None)
            meta_d_path.write_text(json.dumps(raw_meta_d), encoding="utf-8")
            check("[f] legacy mesh_meta backfills tris", (item_mesh.mesh_meta(item_d_id) or {}).get("tris"), 100000)

            # Reduce 100000-tri mesh on item_d via HTTP route
            lod_calls.clear()
            state["lod_fail"] = False
            r_red_ok = client.post(
                f"/inventory/items/{item_d_id}/mesh/reduce",
                json={"face_num": 20000},
                headers=admin_h,
            )
            join_item_mesh_threads()
            check("[f] POST /mesh/reduce 200", r_red_ok.status_code, 200)
            check("[f] POST /mesh/reduce queued", r_red_ok.json(), {"status": "queued"})
            check("[f] 1 lod call for reduce", len(lod_calls), 1)
            if lod_calls:
                check("[f] reduce ratios == [0.2]", lod_calls[0]["params"].get("ratios"), [0.2])
                check("[f] reduce merge_vertices is True", lod_calls[0]["params"].get("merge_vertices") is True, True)
            meta_d_after = item_mesh.mesh_meta(item_d_id) or {}
            check("[f] status done after reduce", meta_d_after.get("status"), "done")
            check("[f] reduced_from == 100000", meta_d_after.get("reduced_from"), 100000)
            check("[f] tris == 18400", meta_d_after.get("tris"), 18400)
            check("[f] face_num == 20000", meta_d_after.get("face_num"), 20000)
            check("[f] prior backend kept", meta_d_after.get("backend"), "fake-mesh")
            check("[f] fresh bbox", meta_d_after.get("bbox"), [0.0, 0.0, 0.0, 0.18, 0.1, 0.05])
            check("[f] reduce_error cleared", "reduce_error" in meta_d_after, False)
            check("[f] reduced bytes published", glb_d_path.read_bytes() == glb_18400, True)

            # Explicit reduce failure leaves old GLB untouched and sets status=failed
            lod_calls.clear()
            state["lod_fail"] = True
            bytes_before_fail = glb_d_path.read_bytes()
            res_fail_q = item_mesh.start_reduce(item_d_id, 5000)
            join_item_mesh_threads()
            check("[f] failing reduce queued", res_fail_q, {"status": "queued"})
            check("[f] old GLB bytes untouched on failed reduce", glb_d_path.read_bytes() == bytes_before_fail, True)
            meta_d_failed = item_mesh.mesh_meta(item_d_id) or {}
            check("[f] status failed on reduce error", meta_d_failed.get("status"), "failed")
            check("[f] error recorded on failed reduce", meta_d_failed.get("error"), "lod boom")
            check("[f] prior backend still kept on failure", meta_d_failed.get("backend"), "fake-mesh")
            check("[f] prior bbox still kept on failure", meta_d_failed.get("bbox"), [0.0, 0.0, 0.0, 0.18, 0.1, 0.05])

            # [g] start_reduce for an item without mesh -> LookupError / HTTP 404
            print("[g] start_reduce without mesh -> LookupError / 404")
            check_raises("[g] start_reduce LookupError", LookupError, item_mesh.start_reduce, item_no_mesh_id, 20000)
            r_red_404 = client.post(
                f"/inventory/items/{item_no_mesh_id}/mesh/reduce",
                json={"face_num": 20000},
                headers=admin_h,
            )
            check("[g] POST /mesh/reduce without mesh 404", r_red_404.status_code, 404)

            # [h] Task queue tracking for item mesh generate, mesh reduce, and item image
            print("[h] Task queue tracking")

            class FakeTaskQueue:
                def __init__(self):
                    self.starts = []
                    self.finishes = []
                    self._seq = 0

                def clear(self):
                    self.starts.clear()
                    self.finishes.clear()

                def track_start(self, task_type, label, agent_name="", provider="", queue_name="", start_running=True):
                    self._seq += 1
                    tid = f"track_fake_{self._seq}"
                    self.starts.append({
                        "task_id": tid,
                        "task_type": task_type,
                        "label": label,
                        "agent_name": agent_name,
                        "provider": provider,
                        "start_running": start_running,
                    })
                    return tid

                def track_finish(self, task_id, error=""):
                    self.finishes.append({"task_id": task_id, "error": error})

            class DummyImgBackend:
                name = "fake-img"
                api_type = "comfyui"
                model = "fake-model"
                last_used_checkpoint = ""
                checkpoint = ""

            fake_tq = FakeTaskQueue()
            img_state = {"mode": "ok"}

            def fake_run_routed(occasion, fn, **kwargs):
                if img_state["mode"] == "error":
                    raise RuntimeError("img backend crashed")
                if img_state["mode"] == "empty":
                    return ([], DummyImgBackend()), None
                return ([TINY_PNG], DummyImgBackend()), None

            with (
                patch.object(task_queue, "get_task_queue", return_value=fake_tq),
                patch.object(imagegen_routing, "run_routed", side_effect=fake_run_routed),
                patch.object(character_model, "postprocess_outfit_image", side_effect=lambda p: p),
            ):
                # (h1) Successful mesh generate -> 1 start + 1 finish(error="")
                fake_tq.clear()
                state["gen_fail"] = False
                state["lod_fail"] = False
                state["deliver_bytes"] = glb_15000
                item_mesh.start_generate(item_a_id, 20000)
                join_item_mesh_threads()
                check("[h] mesh gen starts == 1", len(fake_tq.starts), 1)
                check("[h] mesh gen finishes == 1", len(fake_tq.finishes), 1)
                if fake_tq.starts and fake_tq.finishes:
                    check("[h] mesh gen task_type", fake_tq.starts[0]["task_type"], "model3d_generation")
                    check("[h] mesh gen label", fake_tq.starts[0]["label"], "Item mesh: Brass Key")
                    check("[h] mesh gen agent_name", fake_tq.starts[0]["agent_name"], "Brass Key")
                    check("[h] mesh gen start_running", fake_tq.starts[0]["start_running"], True)
                    check("[h] mesh gen same task_id", fake_tq.finishes[0]["task_id"], fake_tq.starts[0]["task_id"])
                    check("[h] mesh gen finish error == ''", fake_tq.finishes[0]["error"], "")

                # Published mesh with reduce_error also finishes as completed (error == "")
                fake_tq.clear()
                state["deliver_bytes"] = glb_100k
                state["lod_fail"] = True
                item_mesh.start_generate(item_a_id, 20000)
                join_item_mesh_threads()
                check("[h] mesh gen w/ reduce_error finish error == ''", fake_tq.finishes[0]["error"], "")

                # (h2) Failing mesh generate -> finish with non-empty error
                fake_tq.clear()
                state["gen_fail"] = True
                state["lod_fail"] = False
                item_mesh.start_generate(item_a_id, 20000)
                join_item_mesh_threads()
                check("[h] failing mesh gen starts == 1", len(fake_tq.starts), 1)
                check("[h] failing mesh gen finishes == 1", len(fake_tq.finishes), 1)
                check("[h] failing mesh gen error non-empty", fake_tq.finishes[0]["error"], "mesh backend down")
                state["gen_fail"] = False

                # (h3) Mesh reduce -> 1 start/finish with reduce label
                fake_tq.clear()
                state["lod_fail"] = False
                # item_a currently holds 100k tris from the reduce_error run above
                item_mesh.start_reduce(item_a_id, 20000)
                join_item_mesh_threads()
                check("[h] mesh reduce starts == 1", len(fake_tq.starts), 1)
                check("[h] mesh reduce finishes == 1", len(fake_tq.finishes), 1)
                if fake_tq.starts and fake_tq.finishes:
                    check("[h] mesh reduce task_type", fake_tq.starts[0]["task_type"], "model3d_generation")
                    check("[h] mesh reduce label", fake_tq.starts[0]["label"], "Item mesh reduce: Brass Key")
                    check("[h] mesh reduce agent_name", fake_tq.starts[0]["agent_name"], "Brass Key")
                    check("[h] mesh reduce start_running", fake_tq.starts[0]["start_running"], True)
                    check("[h] mesh reduce finish error == ''", fake_tq.finishes[0]["error"], "")

                # Failing mesh reduce -> finish with non-empty error
                fake_tq.clear()
                state["lod_fail"] = True
                item_mesh.start_reduce(item_a_id, 5000)
                join_item_mesh_threads()
                check("[h] failing reduce error", fake_tq.finishes[0]["error"], "lod boom")
                state["lod_fail"] = False

                # (h4) generate_item_image_sync(..., track=False) -> no start
                fake_tq.clear()
                img_state["mode"] = "ok"
                ok_untracked = item_images.generate_item_image_sync(item_a_id, track=False)
                check("[h] untracked image returns True", ok_untracked, True)
                check("[h] untracked image starts == 0", len(fake_tq.starts), 0)
                check("[h] untracked image finishes == 0", len(fake_tq.finishes), 0)

                # (h5) generate_item_image_sync(...) default -> start label "Item image: <name>" + 1 finish
                fake_tq.clear()
                ok_tracked = item_images.generate_item_image_sync(item_a_id)
                check("[h] tracked image returns True", ok_tracked, True)
                check("[h] tracked image starts == 1", len(fake_tq.starts), 1)
                check("[h] tracked image finishes == 1", len(fake_tq.finishes), 1)
                if fake_tq.starts and fake_tq.finishes:
                    check("[h] tracked image task_type", fake_tq.starts[0]["task_type"], "image_gen")
                    check("[h] tracked image label", fake_tq.starts[0]["label"], "Item image: Brass Key")
                    check("[h] tracked image agent_name", fake_tq.starts[0]["agent_name"], "Brass Key")
                    check("[h] tracked image same task_id", fake_tq.finishes[0]["task_id"], fake_tq.starts[0]["task_id"])
                    check("[h] tracked image finish error == ''", fake_tq.finishes[0]["error"], "")

                # Returning False -> finish with "no image produced"
                fake_tq.clear()
                img_state["mode"] = "empty"
                ok_empty = item_images.generate_item_image_sync(item_a_id)
                check("[h] empty image returns False", ok_empty, False)
                check("[h] empty image finish error", fake_tq.finishes[0]["error"], "no image produced")

                # Exception in render -> finish with exception text
                fake_tq.clear()
                img_state["mode"] = "error"
                ok_err = item_images.generate_item_image_sync(item_a_id)
                check("[h] failing image returns False", ok_err, False)
                check("[h] failing image finish error", fake_tq.finishes[0]["error"], "img backend crashed")

    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
