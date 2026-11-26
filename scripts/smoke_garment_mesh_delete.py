#!/usr/bin/env python3
"""Ruling A128: the meshes of an own-mesh clothing piece can be deleted from the piece dialog's Mesh row — one kept
mesh, the mesh in use (only with the confirmation; the mesh step becomes due), or every mesh, kept mesh, shell, fit
and failure record of the piece (its images only when ticked). (app/core/garment_mesh_delete.py; the routes
``GET …/garments/{item}/mesh-delete-preview``, ``POST …/mesh/attempts/{n}/delete``, ``POST …/mesh/delete-all`` in
app/routes/characters.py.)

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh_delete.py

Throwaway storage + instance (STORAGE_DIR / INSTANCE_DIR temp dirs, a copy of the ``human`` package); no hub, no
server; ``requests`` patched to raise. Stubs: ``base_body.current_base`` (a fixed base), ``garment_assembly.schedule``.

Fixture (character Demo, own-mesh clothing piece ``dress``, fsig F of its worn state; ``box(n)`` = 12 n² triangles):
    images/   cutout front, cutout back, worn front                       -> 3 images
    prepared/ dress_F.glb (box 2, in use) + dress_F.json (record, kept slots 1 and 2)
    raw/      dress_F.glb                                                  -> 3 mesh-step files
    attempts/mesh/ dress_F.try1.glb + .try1.raw.glb, dress_F.try2.glb      -> 3 kept-mesh files
    dress_F.glb + dress_F.json (the fit), bodies/ob0000aaaa/dress_F.glb, failed/dress_F.json -> 4 files
    prepared/other_F.glb (another item)                                    -> must stay
  mesh+fit files = 3 + 3 + 4 = 10, images = 3.
HUB_JOBS clothing: worn 2, ghost 2, cutout 2, mesh 1, fit 0 -> rebuild from the mesh = 1, from the first step = 7.

[1] preview -> files {meshes 10, images 3}; rebuild_mesh 1 hub job, steps [mesh, fit]; rebuild_all 7, first step worn.
[2] a user-role session -> 403 on all three routes.
[3] slot 0 without in_use -> 400; slot 7 -> 404; slot 3 (empty) -> 409.
[4] delete slot 1 -> 200, deleted 2, record kept = [2]; slot-1 files gone; the mesh in use untouched; the panel shows
    one kept tile (2) and the mesh status "accepted".
[5] a run holding the piece's run lock -> 409, nothing deleted.
[6] delete slot 0 with in_use -> deleted 2 (prepared + raw); the record stays (kept [2]) without accepted/attempts;
    the panel's mesh status "missing"; the fit file still exists; follow_up steps start with "worn" (the fixture
    has no ghost image) and include "mesh".
[7] delete-all without images -> {meshes: 6 (record, try2, fit glb+json, body fit, failed), images: 0}; 3 images
    remain; other_F.glb remains.
[8] delete-all with images -> {meshes 0, images 3}; images/ holds no dress file.
[9] ``_unlink`` of a path outside garments/ -> ValueError.
[10] 0 outbound requests.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def box(n):
    """The six faces of the cube [-1, 1]³, each an n × n quad grid (two triangles per quad), unwelded."""
    import numpy as np
    P, F = [], []
    for axis in range(3):
        u, v = [a for a in range(3) if a != axis]
        for side in (-1.0, 1.0):
            base = sum(len(p) for p in P)
            g = np.linspace(-1, 1, n + 1)
            pts = np.zeros(((n + 1) ** 2, 3))
            uu, vv = np.meshgrid(g, g, indexing="ij")
            pts[:, axis] = side
            pts[:, u] = uu.ravel()
            pts[:, v] = vv.ravel()
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1) + base
            a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
            F.append(np.stack([a, b, c], -1).reshape(-1, 3))
            F.append(np.stack([a, c, d], -1).reshape(-1, 3))
            P.append(pts)
    from app.core.glb_mesh import static_glb
    pos = np.concatenate(P)
    return static_glb(pos, np.concatenate(F), np.zeros((len(pos), 2)))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    outbound = []
    import requests

    def no_net(*args, **kwargs):
        outbound.append(args[1] if len(args) > 1 else kwargs.get("url"))
        raise AssertionError("outbound request in a smoke")
    requests.Session.request = no_net
    requests.request = no_net

    with tempfile.TemporaryDirectory(prefix="garment-mesh-delete-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, garment_assembly, garment_mesh, garment_mesh_delete, model_refs, sessions, users
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import save_character_profile
        garment_assembly.schedule = lambda name, signature=None: True
        model_refs.schedule_outfit_render = lambda *a, **k: None

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        op = {"slots": ["top"], "outfit_types": ["casual"], "mesh_mode": "own_mesh", "covers": []}
        dress = inventory.add_item(name="Blazer", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a plain blazer", outfit_piece=op)["id"]
        check("give", inventory.add_to_inventory("Demo", dress), True)
        check("equip", inventory.equip_piece("Demo", dress, source="smoke")["status"], "ok")
        bsig = base_body.base_signature("Demo")
        base_body.current_base = lambda name, profile=None: (bsig, "body-sha")
        F = gs.garment_fsig("Demo", dress)

        def put(path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path
        images = [put(gs.garment_path("Demo", dress, F, "image", step=s, view=v), b"\x89PNG-" + f"{s}{v}".encode())
                  for s, v in (("cutout", "front"), ("cutout", "back"), ("worn", "front"))]
        prepared = put(gs.garment_path("Demo", dress, F, "prepared"), box(2))
        raw = put(gs.garment_path("Demo", dress, F, "raw"), box(2) + b"R0")
        record_path = prepared.with_suffix(".json")
        slot1 = put(gs.garment_path("Demo", dress, F, "mesh_attempt", attempt=1), box(3))
        slot1_raw = put(gs.garment_path("Demo", dress, F, "mesh_attempt_raw", attempt=1), box(3) + b"K1")
        put(gs.garment_path("Demo", dress, F, "mesh_attempt", attempt=2), box(4))
        fit = put(gs.garment_path("Demo", dress, F, "fit"), box(2))
        put(fit.with_suffix(".json"), b"{}")
        put(gs.garment_path("Demo", dress, F, "fit", body="ob0000aaaa"), box(2))
        put(gs.garment_path("Demo", dress, F, "failed"), b'{"step": "fit"}')
        other = put(gs.garments_dir("Demo") / "prepared" / f"other_{F}.glb", box(2))
        entry = {"ok": True, "reasons": [], "tris_raw": 108, "tris_prepared": 108, "largest_component_share": 1.0,
                 "backend": "stub", "created_at": "2026-11-14T15:50:00+00:00"}
        gs.write_record(record_path, {
            "accepted": True, "kind": "clothing", "item_id": dress, "fsig": F, "tris_raw": 48, "tris_prepared": 48,
            "ratio": 1.0, "backend": "stub", "routing": {}, "largest_component_share": 1.0,
            "gate_version": garment_mesh.GATE_VERSION, "created_at": "2026-11-14T19:45:00+00:00",
            "attempts": [{"attempt": 1, "ok": True, "reasons": []}],
            "kept": [{"n": 1, "origin": "previous", **entry}, {"n": 2, "origin": "attempt", **entry, "ok": False}]})

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role, allowed_characters=["Demo"])
            tokens[role] = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)
        base = f"/characters/Demo/garments/{dress}/mesh"

        def mesh_panel(client):
            panel = client.get(f"/characters/Demo/garments/{dress}").json()
            return ((panel.get("garment") or {}).get("steps") or {}).get("mesh") or {}

        with TestClient(app, raise_server_exceptions=False) as client:
            print("[2] a user-role session is refused")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            check("user 403", [client.get(f"/characters/Demo/garments/{dress}/mesh-delete-preview").status_code,
                               client.post(f"{base}/attempts/1/delete", json={}).status_code,
                               client.post(f"{base}/delete-all", json={}).status_code], [403, 403, 403])
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            print("[1] preview")
            p = client.get(f"/characters/Demo/garments/{dress}/mesh-delete-preview").json()
            check("files", p.get("files"), {"meshes": 10, "images": 3})
            check("rebuild mesh", (p["rebuild_mesh"]["hub_jobs"], p["rebuild_mesh"]["steps"]), (1, ["mesh", "fit"]))
            check("rebuild all", (p["rebuild_all"]["hub_jobs"], p["rebuild_all"]["steps"][:1]), (7, ["worn"]))

            print("[3] refusals")
            check("slot 0 without confirm", client.post(f"{base}/attempts/0/delete", json={}).status_code, 400)
            check("slot 7", client.post(f"{base}/attempts/7/delete", json={}).status_code, 404)
            check("slot 3 empty", client.post(f"{base}/attempts/3/delete", json={}).status_code, 409)

            print("[4] delete kept slot 1")
            r = client.post(f"{base}/attempts/1/delete", json={})
            check("200 deleted", (r.status_code, r.json().get("deleted")), (200, 2))
            check("kept", [e["n"] for e in gs.read_record(record_path)["kept"]], [2])
            check("slot 1 files gone", (slot1.exists(), slot1_raw.exists()), (False, False))
            check("in use untouched", (prepared.read_bytes() == box(2), raw.exists()), (True, True))
            m = mesh_panel(client)
            check("panel", (m.get("status"), [a.get("attempt") for a in (m.get("view") or {}).get("attempts") or []]),
                  ("accepted", [2]))

            print("[5] busy")
            lock = gs.run_item_lock("Demo", dress)
            lock.acquire()
            try:
                check("409 while a run holds the piece", client.post(f"{base}/delete-all", json={}).status_code, 409)
            finally:
                lock.release()
            check("nothing deleted", prepared.exists(), True)

            print("[6] delete the mesh in use")
            r = client.post(f"{base}/attempts/0/delete", json={"in_use": True})
            d = r.json()
            check("200 deleted", (r.status_code, d.get("deleted")), (200, 2))
            rec = gs.read_record(record_path)
            check("record", (sorted(rec), [e["n"] for e in rec["kept"]]),
                  (["deleted_at", "fsig", "item_id", "kept", "kind"], [2]))
            check("mesh missing", mesh_panel(client).get("status"), "missing")
            check("fit stays", fit.exists(), True)
            # The fixture holds no ghost image, so a plain run starts at the first step and runs through the mesh.
            check("due", ((d["follow_up"]["steps"] or [""])[0], "mesh" in d["follow_up"]["steps"]), ("worn", True))

            print("[7] delete all, images kept")
            r = client.post(f"{base}/delete-all", json={})
            check("counts", (r.status_code, r.json().get("deleted")), (200, {"meshes": 6, "images": 0}))
            check("images stay", [p.exists() for p in images], [True, True, True])
            check("other item stays", other.exists(), True)

            print("[8] delete all with images")
            r = client.post(f"{base}/delete-all", json={"include_images": True})
            check("counts", (r.status_code, r.json().get("deleted")), (200, {"meshes": 0, "images": 3}))
            check("no dress image", [p.name for p in (gs.garments_dir("Demo") / "images").iterdir()
                                     if p.name.startswith(dress)], [])

        print("[9] containment")
        try:
            garment_mesh_delete._unlink(gs.garments_dir("Demo"), root / "outside.txt")
            check("outside refused", False, True)
        except ValueError:
            check("outside refused", True, True)
    check("[10] outbound", outbound, [])
    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
