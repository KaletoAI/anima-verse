#!/usr/bin/env python3
"""Smoke: per-item 3D mesh occasion, generation, copy, delete, serve and auth gate.

Usage:
    ./.venv/bin/python scripts/smoke_item_mesh.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp directory
before importing any app module or app.server. Never touches worlds/ or instance/.

Hand-derived expectations:
[a] `mesh_item` is declared in `app.imagegen.occasions.OCCASIONS` with
    media == "mesh", category == "img2mesh" and rig == "none".
[b] Generating a mesh for an item with an image (a tiny PNG saved as image.png)
    via POST /inventory/items/{id}/mesh/generate returns 200 {"status": "queued"}.
    The background worker writes a valid 1-triangle GLB with vertices
    (0, 0, 0), (0.2, 0, 0), (0, 0.1, 0.05) -> model.json reaches status "done"
    with bbox == [0.0, 0.0, 0.0, 0.2, 0.1, 0.05].
    GET /inventory/items/{id}/model/meta returns 200 with version == content_version(glb).
    GET /inventory/items/{id}/model?v=<version> returns 200 with immutable caching
    and exact GLB bytes; GET /inventory/items/{id}/model returns 200 with no-cache.
[c] Generating a mesh on an item without an image returns 400 with detail
    "Generate the item image first" and calls the fake backend 0 times.
[d] Copying the mesh onto a second item via POST /inventory/items/{id2}/mesh/copy
    produces identical GLB bytes and sets copied_from == id1.
    Copying from an item without a mesh returns 404.
[e] DELETE /inventory/items/{id2}/mesh returns 200 {"deleted": True};
    subsequent GET /model/meta returns 404 and GET /mesh/status returns {"status": "none"}.
[f] delete_item() of an item with a mesh removes model.glb and model.json.
[g] With image_generation.enabled == False, POST /mesh/generate returns 409
    and the fake backend is not called.
[h] Auth gate: a player POST /mesh/generate returns 403; a player GET /model/meta
    and GET /model return 200 when a mesh exists.
"""
import json
import logging
import os
import struct
import sys
import tempfile
import time
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


def build_triangle_glb() -> bytes:
    """Build a minimal valid glTF 2.0 GLB with one triangle: (0,0,0), (0.2,0,0), (0,0.1,0.05)."""
    pos_bytes = struct.pack("<9f", 0.0, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.1, 0.05)
    idx_bytes = struct.pack("<3H", 0, 1, 2)
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
                "max": [0.2, 0.1, 0.05],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 3,
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


def wait_for_mesh(item_mesh_mod, item_id: str, timeout_s: float = 10.0):
    deadline = time.monotonic() + timeout_s
    meta = None
    while time.monotonic() < deadline:
        meta = item_mesh_mod.mesh_meta(item_id)
        if meta and meta.get("status") in ("done", "failed"):
            return meta
        time.sleep(0.05)
    return meta


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="item-mesh-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema
        init_schema()

        from app.imagegen import occasions, service as imagegen_service
        from app.core import auth_dependency, config, http_files, item_mesh
        from app.core.users import create_user, get_user_by_id
        from app.models.inventory import _get_item_dir, add_item, delete_item, update_item

        # [a] Occasion catalog entry
        print("[a] Occasion catalog")
        occ = occasions.OCCASIONS.get("mesh_item")
        check("[a] mesh_item in OCCASIONS", occ is not None, True)
        if occ is not None:
            check("[a] mesh_item media", occ.get("media"), "mesh")
            check("[a] mesh_item category", occ.get("category"), "img2mesh")
            check("[a] mesh_item rig", occ.get("rig"), "none")

        glb_bytes = build_triangle_glb()
        calls = []

        class FakeImageService:
            def generate_mesh(self, source_image_path, output_path, **kwargs):
                calls.append({"source_image_path": source_image_path, "output_path": output_path, **kwargs})
                Path(output_path).write_bytes(glb_bytes)
                return {"ok": True, "path": output_path, "backend": "fake", "routing": {}}

        fake_service = FakeImageService()

        logging.disable(logging.INFO)
        from app.server import app as server_app
        from fastapi.testclient import TestClient

        player_id = create_user("player_mesh_smoke", "smoke-password", allowed_characters=[])

        def session_user(request):
            who = request.headers.get("x-test-user", "")
            if who == "admin":
                return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
            if who == "player":
                return get_user_by_id(player_id)
            return None

        item_a = add_item(name="Silver Goblet", description="A silver goblet")
        item_a_id = item_a["id"]
        item_a_dir = _get_item_dir(item_a_id, create=True)
        (item_a_dir / "image.png").write_bytes(TINY_PNG)
        update_item(item_a_id, {"image": "image.png"})

        item_no_img = add_item(name="Blank Token", description="No image yet")
        item_no_img_id = item_no_img["id"]

        item_b = add_item(name="Second Goblet", description="Target for copy")
        item_b_id = item_b["id"]

        admin_h = {"x-test-user": "admin"}
        player_h = {"x-test-user": "player"}

        with (
            patch.object(auth_dependency, "_get_session_user", side_effect=session_user),
            patch.object(imagegen_service, "get_image_service", return_value=fake_service),
        ):
            client = TestClient(server_app)

            # [b] Generate on an item with an image
            print("[b] Generate mesh on item with image")
            r_gen = client.post(f"/inventory/items/{item_a_id}/mesh/generate", headers=admin_h)
            check("[b] POST generate status", r_gen.status_code, 200)
            check("[b] POST generate body", r_gen.json(), {"status": "queued"})

            meta = wait_for_mesh(item_mesh, item_a_id, timeout_s=10.0)
            check("[b] worker finished done", meta.get("status") if meta else None, "done")
            check("[b] bbox exact", meta.get("bbox") if meta else None, [0.0, 0.0, 0.0, 0.2, 0.1, 0.05])
            check("[b] occasion passed", calls[-1].get("occasion") if calls else None, "mesh_item")

            glb_a, _ = item_mesh.mesh_paths(item_a_id)
            expected_ver = http_files.content_version(glb_a)

            r_meta = client.get(f"/inventory/items/{item_a_id}/model/meta", headers=admin_h)
            check("[b] GET model/meta 200", r_meta.status_code, 200)
            check("[b] model/meta version", r_meta.json().get("version"), expected_ver)

            r_model_v = client.get(f"/inventory/items/{item_a_id}/model?v={expected_ver}", headers=admin_h)
            check("[b] GET model?v= 200", r_model_v.status_code, 200)
            check("[b] GET model?v= immutable", "immutable" in r_model_v.headers.get("cache-control", ""), True)
            check("[b] GET model?v= bytes", r_model_v.content, glb_bytes)

            r_model = client.get(f"/inventory/items/{item_a_id}/model", headers=admin_h)
            check("[b] GET model 200", r_model.status_code, 200)
            check("[b] GET model no-cache", r_model.headers.get("cache-control"), "no-cache")

            # [c] Generate on an item without an image
            print("[c] Generate without image")
            calls_before = len(calls)
            r_no_img = client.post(f"/inventory/items/{item_no_img_id}/mesh/generate", headers=admin_h)
            check("[c] POST generate no image 400", r_no_img.status_code, 400)
            check("[c] error detail", r_no_img.json().get("detail"), "Generate the item image first")
            check("[c] fake not called", len(calls) - calls_before, 0)

            # [d] Copy onto second item + copy from item without mesh
            print("[d] Copy mesh")
            r_copy = client.post(
                f"/inventory/items/{item_b_id}/mesh/copy",
                json={"from_item_id": item_a_id},
                headers=admin_h,
            )
            check("[d] POST copy 200", r_copy.status_code, 200)
            check("[d] copied_from set", r_copy.json().get("copied_from"), item_a_id)
            glb_b, _ = item_mesh.mesh_paths(item_b_id)
            check("[d] copied bytes identical", glb_b.read_bytes(), glb_a.read_bytes())

            r_copy_missing = client.post(
                f"/inventory/items/{item_b_id}/mesh/copy",
                json={"from_item_id": item_no_img_id},
                headers=admin_h,
            )
            check("[d] copy from item without mesh 404", r_copy_missing.status_code, 404)

            # [e] DELETE mesh
            print("[e] Delete mesh")
            r_del = client.delete(f"/inventory/items/{item_b_id}/mesh", headers=admin_h)
            check("[e] DELETE mesh 200", r_del.status_code, 200)
            check("[e] DELETE mesh body", r_del.json(), {"deleted": True})
            r_meta_after = client.get(f"/inventory/items/{item_b_id}/model/meta", headers=admin_h)
            check("[e] model/meta after delete 404", r_meta_after.status_code, 404)
            r_status_after = client.get(f"/inventory/items/{item_b_id}/mesh/status", headers=admin_h)
            check("[e] mesh/status after delete", r_status_after.json(), {"status": "none"})

            # [g] Media switch off -> 409, fake not called
            print("[g] Media switch off")
            calls_before = len(calls)
            real_get = config.get
            with patch.object(
                config,
                "get",
                side_effect=lambda key, default=None: False if key == "image_generation.enabled" else real_get(key, default),
            ):
                r_off = client.post(f"/inventory/items/{item_a_id}/mesh/generate", headers=admin_h)
            check("[g] generate with media off 409", r_off.status_code, 409)
            check("[g] fake not called when off", len(calls) - calls_before, 0)

            # [h] Auth gate: player POST 403, player GET model/meta & model 200
            print("[h] Auth gate")
            r_player_post = client.post(f"/inventory/items/{item_a_id}/mesh/generate", headers=player_h)
            check("[h] player POST generate 403", r_player_post.status_code, 403)
            r_player_meta = client.get(f"/inventory/items/{item_a_id}/model/meta", headers=player_h)
            check("[h] player GET model/meta 200", r_player_meta.status_code, 200)
            r_player_model = client.get(f"/inventory/items/{item_a_id}/model", headers=player_h)
            check("[h] player GET model 200", r_player_model.status_code, 200)

            # [f] delete_item leaves no model.glb behind
            print("[f] delete_item cleanup")
            check("[f] glb exists before delete_item", glb_a.exists(), True)
            check("[f] delete_item returns True", delete_item(item_a_id), True)
            check("[f] model.glb removed", glb_a.exists(), False)
            _, meta_a = item_mesh.mesh_paths(item_a_id)
            check("[f] model.json removed", meta_a.exists(), False)

    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
