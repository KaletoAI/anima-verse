#!/usr/bin/env python3
"""3D tab: an outfit model built on an older base body keeps its details
(``model3d.get_model3d_info``, bug F of 2026-11-09).

Usage:
    ./.venv/bin/python scripts/smoke_model3d_stale_base.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server. The backend
listings of the info are stubbed empty (no network probe), the delivery
copy is the file itself (no meshopt thread); the model is the
synthetic rigged body of ``smoke_glb_graft.py``.

Fixture: ``Demo`` (human-roleplay, base-body pipeline). BSIG =
base_signature(Demo), the base model model3d/BSIG.glb = b"base-model" ->
SHA. OSIG = the current outfit signature; model3d/OSIG.glb = the body
fixture with a sidecar {rig mixamo, base_signature, base_model_sha256} that
the cases below rewrite.

Expected, derived by hand from the serving rule (find_model3d_serving keeps
an older-base model of THIS combination on screen as match "stale") and the
fix (the info says so instead of the tab losing the model):
[1] sidecar on another base (base_signature "base0ld00000", sha "0"*64):
    info.model present, signature OSIG, match "stale", stale_base True,
    stale_reason "older_base"; the face-retexture keys are there
    (face_retexture_revert is a key of the model).
[2] sidecar without any base identity (a whole-body model from before the
    pipeline): match "stale", stale_base True, stale_reason
    "before_pipeline".
[3] sidecar on the current base (BSIG, SHA): match "exact", stale_base
    False, no stale_reason.
[4] off the pipeline, sidecar of [1]: no stale rule -> match "exact",
    stale_base False.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="model3d-stale-base-") as tmp:
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

        import hashlib
        import smoke_glb_graft as fx
        from app.core import base_body, model3d, model_refs
        from app.imagegen import routing, service
        from app.models.character import save_character_profile

        class _NoBackends:
            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []
        service.get_image_service = lambda: _NoBackends()
        model3d.list_mesh_backends = lambda *a, **k: {}
        model3d.list_rig_backends = lambda *a, **k: []
        model3d.request_lod = lambda *a, **k: False
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, source=None: path  # no meshopt thread past teardown
        routing.explain_occasion = lambda *a, **k: {}

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        bsig = base_body.base_signature("Demo")
        osig = model_refs.current_outfit_state("Demo")[2]
        mdir = model3d.get_model3d_dir("Demo")
        (mdir / f"{bsig}.glb").write_bytes(b"base-model")
        base_sha = hashlib.sha256(b"base-model").hexdigest()
        body, _names = fx.body_fixture()
        bare = mdir / f"{osig}.glb"
        bare.write_bytes(body)
        meta = {"rig": "mixamo", "format": "glb", "signature": osig, "source": "base_body",
                "pieces": {}, "items": []}

        def sidecar(**extra):
            bare.with_suffix(".json").write_text(json.dumps({**meta, **extra}))

        def model():
            return model3d.get_model3d_info("Demo").get("model") or {}

        print("[1] older base")
        sidecar(base_signature="base0ld00000", base_model_sha256="0" * 64)
        m = model()
        check("model present", (m.get("signature"), m.get("match")), (osig, "stale"))
        check("flag + reason", (m.get("stale_base"), m.get("stale_reason")), (True, "older_base"))
        check("face retexture keys", "face_retexture_revert" in m, True)

        print("[2] before the pipeline")
        sidecar()
        m = model()
        check("before pipeline", (m.get("match"), m.get("stale_base"), m.get("stale_reason")),
              ("stale", True, "before_pipeline"))

        print("[3] current base")
        sidecar(base_signature=bsig, base_model_sha256=base_sha)
        m = model()
        check("current", (m.get("match"), m.get("stale_base"), "stale_reason" in m), ("exact", False, False))

        print("[4] off the pipeline")
        sidecar(base_signature="base0ld00000", base_model_sha256="0" * 64)
        check("pipeline off", base_body.set_pipeline("Demo", False), True)
        m = model()
        check("off pipeline", (m.get("match"), m.get("stale_base")), ("exact", False))

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
