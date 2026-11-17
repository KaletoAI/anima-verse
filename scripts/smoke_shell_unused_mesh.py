#!/usr/bin/env python3
"""A171: a piece in mode "Shell from the body" whose generated mesh is still stored (made while it was an own-mesh
piece, before the A168 mode migration) showed BOTH meshes as green and "in use" in the piece dialog's Mesh row. The
fit of a shell piece never reads the generated mesh (``garments._fit_shell``), so the dialog now names which mesh the
fit uses (``mesh.view.in_use`` = ``garments.generated_or_shell``) and the generated mesh of a shell piece is deleted
without the in-use confirmation, leaving the shell and the fit untouched. (app/core/garments.py,
app/core/garment_mesh_delete.py; UI: frontend/src/tabs/characters/GarmentMeshView.tsx.)

Usage:
    ./.venv/bin/python scripts/smoke_shell_unused_mesh.py

Throwaway storage + instance (temp dirs, a copy of the ``human`` package); no hub, no server; ``requests`` patched
to raise. Stubs: ``base_body.current_base`` (a fixed base), ``garment_assembly.schedule``.

Fixture (character Demo): ``dress`` (slot top, mode own_mesh) and ``slip`` (slot underwear_bottom, mode shell), each
with, for the fsig of its worn state: prepared/<id>_F.glb + its record (accepted, no kept meshes), raw/<id>_F.glb,
the fit <id>_F.glb + .json; ``slip`` also shell/slip_F.glb.

Expected (derived from the rules above, not recorded):
[1] panel ``garment.steps.mesh.view.in_use``: dress "generated", slip "shell".
[2] dress slot 0 WITHOUT ``in_use`` -> 400 (the mesh in use still needs the confirmation).
[3] slip slot 0 WITHOUT ``in_use`` -> 200, ``in_use`` False, deleted 3 (prepared + raw + the record: no kept list).
[4] slip's fit GLB, fit JSON and shell GLB keep their exact bytes; dress's prepared mesh still exists.
[5] slip panel: ``in_use`` still "shell", the view's ``prepared`` and ``raw`` None, its ``shell`` still served.
[6] 0 outbound requests.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    outbound = []
    import requests

    def no_net(*args, **kwargs):
        outbound.append(args[1] if len(args) > 1 else kwargs.get("url"))
        raise AssertionError("outbound request in a smoke")
    requests.Session.request = no_net
    requests.request = no_net

    with tempfile.TemporaryDirectory(prefix="shell-unused-mesh-") as tmp:
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

        from app.core import base_body, garment_assembly, model_refs, sessions, users
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import save_character_profile
        garment_assembly.schedule = lambda name, signature=None: True
        model_refs.schedule_outfit_render = lambda *a, **k: None
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        items = {}
        for iid, slot, mode in (("dress", "top", "own_mesh"), ("slip", "underwear_bottom", "shell")):
            op = {"slots": [slot], "outfit_types": ["casual"], "mesh_mode": mode, "covers": []}
            items[iid] = inventory.add_item(name=iid, category="outfit_piece", item_id=iid,
                                            prompt_fragment=f"a plain {iid}", outfit_piece=op)["id"]
            inventory.add_to_inventory("Demo", iid)
            check(f"equip {iid}", inventory.equip_piece("Demo", iid, source="smoke")["status"], "ok")
        bsig = base_body.base_signature("Demo")
        base_body.current_base = lambda name, profile=None: (bsig, "body-sha")

        def put(path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path
        from app.core.glb_mesh import static_glb
        import numpy as np
        glb = static_glb(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), np.array([[0, 1, 2]]), np.zeros((3, 2)))
        files = {}
        for iid in items:
            F = gs.garment_fsig("Demo", iid)
            prepared = put(gs.garment_path("Demo", iid, F, "prepared"), glb)
            put(gs.garment_path("Demo", iid, F, "raw"), glb + b"R")
            gs.write_record(prepared.with_suffix(".json"), {
                "accepted": True, "kind": "clothing", "item_id": iid, "fsig": F, "tris_raw": 1, "tris_prepared": 1,
                "created_at": "2026-11-17T11:00:00+00:00", "attempts": [{"attempt": 1, "ok": True, "reasons": []}]})
            fit = put(gs.garment_path("Demo", iid, F, "fit"), glb + b"FIT")
            put(fit.with_suffix(".json"), b'{"accepted": true}')
            files[iid] = {"prepared": prepared, "fit": fit, "fit_json": fit.with_suffix(".json")}
        files["slip"]["shell"] = put(gs.garment_path("Demo", "slip", gs.garment_fsig("Demo", "slip"), "shell"),
                                     glb + b"SHELL")
        before = {k: p.read_bytes() for k, p in files["slip"].items() if k != "prepared"}

        uid = users.create_user("demo-admin", "temporary-smoke-password", users.ROLE_ADMIN, allowed_characters=["Demo"])
        token = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)

        def view(client, iid):
            panel = client.get(f"/characters/Demo/garments/{iid}").json()
            return (((panel.get("garment") or {}).get("steps") or {}).get("mesh") or {}).get("view") or {}

        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set(sessions.SESSION_COOKIE_NAME, token)
            print("[1] which mesh the fit uses")
            check("dress in_use", view(client, "dress").get("in_use"), "generated")
            check("slip in_use", view(client, "slip").get("in_use"), "shell")
            print("[2] the own-mesh piece's mesh in use still needs the confirmation")
            r = client.post("/characters/Demo/garments/dress/mesh/attempts/0/delete", json={})
            check("dress slot 0 without in_use", r.status_code, 400)
            print("[3] the shell piece's generated mesh goes without it")
            r = client.post("/characters/Demo/garments/slip/mesh/attempts/0/delete", json={})
            check("slip status", r.status_code, 200)
            body = r.json() if r.status_code == 200 else {}
            check("slip in_use", body.get("in_use"), False)
            check("slip deleted", body.get("deleted"), 3)
            print("[4] the shell and the fit are untouched")
            check("slip fit/shell bytes", {k: files["slip"][k].read_bytes() == v for k, v in before.items()},
                  {k: True for k in before})
            check("slip prepared gone", files["slip"]["prepared"].exists(), False)
            check("dress prepared stays", files["dress"]["prepared"].exists(), True)
            print("[5] the panel after the delete")
            v = view(client, "slip")
            check("slip view", (v.get("in_use"), v.get("prepared"), v.get("raw"), bool(v.get("shell"))),
                  ("shell", None, None, True))
        print("[6] outbound")
        check("outbound", outbound, [])
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
