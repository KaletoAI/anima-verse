#!/usr/bin/env python3
""""Re-apply face cleanup" (app/core/model3d.py ``face_cleanup_state`` /
``trigger_face_cleanup``, route POST /characters/{n}/model3d/face-cleanup)
on the base-body pipeline vs the old path.

Usage:
    ./.venv/bin/python scripts/smoke_face_cleanup_reapply.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server process (the
characters router in a bare FastAPI app, ``require_admin`` overridden).
``face_cleanup.clean_face`` appends b"-clean" and records ``applied`` at the
current VERSION; ``mesh_source.validate_source`` accepts; ``rerig_model``,
``face_retexture_model`` and ``after_base_face_change`` are recorders; the
face-retexture pre-checks and the rig route are stubs, ``get_image_service`` a bare pool holder (the real one
probes every backend). So nothing meshes,
rigs or reaches a hub.

Fixture: ``Demo`` (human-roleplay, base-body pipeline, BSIG =
base_signature(Demo)), ``Plain`` (same profile, off the pipeline, a model
0aaaaaaa). The retained source is model3d/unrigged/<sig>.glb + sidecar.

Expected, derived by hand from the rules in model3d's "Face cleanup
re-apply" block:
[1] Signature: Demo -> BSIG whatever is asked; Plain + "0aaaaaaa" ->
    "0aaaaaaa".
[2] State of Demo: no source -> status "none", blocked "No retained unrigged
    mesh — generate the model again."; source recorded skipped ("disabled for
    this character") with the switch off -> status "skipped", summary that
    reason, blocked "Switch the face cleanup on first."; switch on ->
    can_reapply, follow_up "rerig", jobs ["rig"]; with facefix/BSIG.glb ->
    "face_retexture" and its three jobs; without facefix but
    face_before_rig on -> "face_retexture"; recorded applied at the
    CURRENT version -> blocked "Already applied to the stored mesh."; at
    VERSION-1 without the mesher's original (unrigged/mesher/BSIG.glb) ->
    blocked (model3d.MESHER_MISSING, mesher_retained False); with it -> can
    run, mesher_retained True; required_rig "generic" -> blocked "Humanoid
    models only." and follow_up "rerig".
[3] Route refusals: unknown character 404; "?signature=../x" 400; switch
    off 409 "Switch the face cleanup on first."; no rig route 409 "No
    humanoid rig route is configured." (nothing cleaned); face path with a
    failing face check 409 naming its message (nothing cleaned). The route
    carries require_admin.
[4] Rerig path on Demo (source b"glTF-src", recorded skipped): 200
    {status generating, follow_up rerig, jobs [rig]}; afterwards the source
    is b"glTF-src-clean", its sidecar face_cleanup {status applied,
    reapplied True}, clean_face saw b"glTF-src" once, rerig_model(Demo,
    BSIG) once, face_retexture_model never, after_base_face_change(Demo,
    BSIG) once, the result {ok True, follow_up rerig}, the guard released;
    the mesher's bytes b"glTF-src" are retained as unrigged/mesher/BSIG.glb
    (the source was never cleaned before, so it WAS the mesher's output).
[5] Face path on Demo (facefix present, record at VERSION-1, the retained
    mesher file b"glTF-mesher"): clean_face saw b"glTF-mesher" (never the
    cleaned source), face_retexture_model(Demo, BSIG) once, rerig never.
[6] Old path, Plain "0aaaaaaa": rerig_model(Plain, "0aaaaaaa").
[7] clean_face raises "boom": result {ok False, error "Face cleanup failed:
    boom"}, the source bytes unchanged, no follow-up, guard released.
[8] GET extras: ``_base_body_model_extras`` gives face_cleanup.signature
    BSIG, collision_scales = collision.default_scales() (nothing saved),
    and the base model the face fields
    (face_retexture key) and a collision key.
"""
import json
import os
import shutil
import sys
import tempfile
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="face-cleanup-reapply-") as tmp:
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

        from app.core import base_body, collision, face_cleanup, face_retexture, mesh_source, model3d
        from app.imagegen import routing
        from app.models.character import get_character_dir, save_character_profile

        CLEANS, RERIGS, FACES, AFTER = [], [], [], []
        clean_raises = {"on": False}

        def fake_clean(blob):
            CLEANS.append(blob)
            if clean_raises["on"]:
                raise ValueError("boom")
            return blob + b"-clean", {"status": "applied", "version": face_cleanup.VERSION,
                                      "eyes": {"status": "skipped", "reason": "x"},
                                      "mouth": {"status": "skipped", "reason": "y"}}

        face_cleanup.clean_face = fake_clean
        mesh_source.validate_source = lambda blob: {"ok": True}
        model3d.rerig_model = lambda name, sig, **kw: RERIGS.append((name, sig)) or {"ok": True}
        model3d.face_retexture_model = lambda name, sig, **kw: FACES.append((name, sig)) or {"ok": True}
        model3d.after_base_face_change = lambda name, sig: AFTER.append((name, sig))
        face_problems = {"list": []}
        face_retexture.check = lambda name, sig, reference="", **kw: {"problems": list(face_problems["list"])}
        face_retexture.runnable = lambda name, backend_glob="": {"problems": []}
        rig_route = {"on": True}
        # The real service probes every mesh backend over the network on construction.
        from types import SimpleNamespace
        from app.imagegen import service
        service.get_image_service = lambda: SimpleNamespace(pool=None)
        routing.chain_candidates = lambda occasion, **kw: ["rigger"] if rig_route["on"] else []

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        for name in ("Demo", "Plain"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        bsig = base_body.base_signature("Demo")
        models = get_character_dir("Demo") / "model3d"
        (models / "unrigged").mkdir(parents=True, exist_ok=True)
        (models / f"{bsig}.glb").write_bytes(b"glTF-base")
        (models / f"{bsig}.json").write_text(json.dumps({"rig": "mixamo", "base": True}))
        source = models / "unrigged" / f"{bsig}.glb"
        version = face_cleanup.VERSION

        def write_source(record):
            source.write_bytes(b"glTF-src")
            source.with_suffix(".json").write_text(json.dumps({"rig": "none", "face_cleanup": record}))

        def wait_guard():
            for _ in range(300):
                with model3d._lock:
                    if "Demo" not in model3d._generating and "Plain" not in model3d._generating:
                        return
                time.sleep(0.02)
            FAILS.append("face cleanup thread did not finish")

        def state(name="Demo", sig=None):
            return model3d.face_cleanup_state(name, sig or bsig)

        print("[1] signature")
        check("Demo -> base", model3d.face_cleanup_signature("Demo", "0bbbbbbb"), bsig)
        check("Plain -> asked", model3d.face_cleanup_signature("Plain", "0aaaaaaa"), "0aaaaaaa")

        print("[2] state")
        s = state()
        check("no source", (s["status"], s["blocked"], s["can_reapply"]),
              ("none", "No retained unrigged mesh — generate the model again.", False))
        write_source({"status": "skipped", "reason": "disabled for this character"})
        s = state()
        check("switch off", (s["status"], s["summary"], s["blocked"]),
              ("skipped", "disabled for this character", "Switch the face cleanup on first."))
        model3d.set_model3d_options("Demo", {"face_cleanup": True})
        s = state()
        check("switch on", (s["can_reapply"], s["follow_up"], s["jobs"]), (True, "rerig", ["rig"]))
        (models / "facefix").mkdir(exist_ok=True)
        (models / "facefix" / f"{bsig}.glb").write_bytes(b"glTF-facefix")
        s = state()
        check("facefix", (s["follow_up"], s["jobs"]),
              ("face_retexture", ["upscale (front-view reference only)", "face retexture", "rig"]))
        (models / "facefix" / f"{bsig}.glb").unlink()
        model3d.set_model3d_options("Demo", {"face_before_rig": True})
        check("face before rig", state()["follow_up"], "face_retexture")
        model3d.set_model3d_options("Demo", {"face_before_rig": False})
        write_source({"status": "applied", "version": version})
        check("applied now", (state()["can_reapply"], state()["blocked"]), (False, "Already applied to the stored mesh."))
        write_source({"status": "applied", "version": version - 1})
        s = state()
        check("older version, no mesher file", (s["can_reapply"], s["blocked"], s["mesher_retained"]),
              (False, model3d.MESHER_MISSING, False))
        mesher = models / "unrigged" / "mesher" / f"{bsig}.glb"
        mesher.parent.mkdir(parents=True, exist_ok=True)
        mesher.write_bytes(b"glTF-mesher")
        s = state()
        check("older version, mesher retained", (s["can_reapply"], s["mesher_retained"]), (True, True))
        mesher.unlink()
        real_rig = model3d.required_rig
        model3d.required_rig = lambda name: "generic"
        s = state()
        check("not humanoid", (s["blocked"], s["follow_up"]), ("Humanoid models only.", "rerig"))
        model3d.required_rig = real_rig

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        from app.routes import characters as routes
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
        route = next(r for r in routes.router.routes if getattr(r, "path", "").endswith("/{character_name}/model3d/face-cleanup"))
        check("route is admin-only", any(d.call is require_admin for d in route.dependant.dependencies), True)

        with TestClient(app, raise_server_exceptions=False) as client:
            def post(url):
                r = client.post(url)
                try:
                    return r.status_code, r.json()
                except ValueError:
                    return r.status_code, None

            def detail(result):
                return result[0], (result[1] or {}).get("detail")

            print("[3] refusals")
            check("404", post("/characters/Nobody/model3d/face-cleanup")[0], 404)
            check("400", post("/characters/Demo/model3d/face-cleanup?signature=../x")[0], 400)
            model3d.set_model3d_options("Demo", {"face_cleanup": False})
            check("switch off", detail(post("/characters/Demo/model3d/face-cleanup")),
                  (409, "Switch the face cleanup on first."))
            model3d.set_model3d_options("Demo", {"face_cleanup": True})
            write_source({"status": "skipped", "reason": "disabled for this character"})
            rig_route["on"] = False
            check("no rig route", detail(post("/characters/Demo/model3d/face-cleanup")),
                  (409, "No humanoid rig route is configured."))
            rig_route["on"] = True
            (models / "facefix" / f"{bsig}.glb").write_bytes(b"glTF-facefix")
            face_problems["list"] = [{"code": "photo_changed", "message": "The reference photo has changed."}]
            check("face check", detail(post("/characters/Demo/model3d/face-cleanup")),
                  (409, "The reference photo has changed."))
            face_problems["list"] = []
            (models / "facefix" / f"{bsig}.glb").unlink()
            check("nothing cleaned", (CLEANS, source.read_bytes()), ([], b"glTF-src"))

            print("[4] rerig path (pipeline)")
            check("start", post("/characters/Demo/model3d/face-cleanup?signature=0bbbbbbb")[1] | {"task_id": ""},
                  {"status": "generating", "follow_up": "rerig", "jobs": ["rig"], "task_id": ""})
            wait_guard()
            meta = json.loads(source.with_suffix(".json").read_text())
            check("source cleaned", source.read_bytes(), b"glTF-src-clean")
            check("record", (meta["face_cleanup"]["status"], meta["face_cleanup"].get("reapplied")), ("applied", True))
            check("clean input", CLEANS, [b"glTF-src"])
            check("rerig", RERIGS, [("Demo", bsig)])
            check("no face", FACES, [])
            check("after", AFTER, [("Demo", bsig)])
            result = model3d._face_cleanup_results.get("Demo") or {}
            check("result", (result.get("ok"), result.get("follow_up")), (True, "rerig"))
            check("state result", state()["result"]["ok"], True)
            check("mesher retained", (mesher.is_file() and mesher.read_bytes(), state()["mesher_retained"]), (b"glTF-src", True))
            CLEANS.clear(); RERIGS.clear(); AFTER.clear()

            print("[5] face path (pipeline)")
            write_source({"status": "applied", "version": version - 1})
            mesher.write_bytes(b"glTF-mesher")
            (models / "facefix" / f"{bsig}.glb").write_bytes(b"glTF-facefix")
            check("start", post("/characters/Demo/model3d/face-cleanup")[1]["follow_up"], "face_retexture")
            wait_guard()
            check("clean input is the mesher file", CLEANS, [b"glTF-mesher"])
            check("source cleaned from it", source.read_bytes(), b"glTF-mesher-clean")
            check("face", FACES, [("Demo", bsig)])
            check("no rerig", RERIGS, [])
            (models / "facefix" / f"{bsig}.glb").unlink()
            CLEANS.clear(); FACES.clear(); AFTER.clear()

            print("[6] old path")
            plain = get_character_dir("Plain") / "model3d"
            (plain / "unrigged").mkdir(parents=True, exist_ok=True)
            (plain / "0aaaaaaa.glb").write_bytes(b"glTF-plain")
            (plain / "0aaaaaaa.json").write_text(json.dumps({"rig": "mixamo"}))
            (plain / "unrigged" / "0aaaaaaa.glb").write_bytes(b"glTF-plain-src")
            model3d.set_model3d_options("Plain", {"face_cleanup": True})
            check("start", post("/characters/Plain/model3d/face-cleanup?signature=0aaaaaaa")[1]["follow_up"], "rerig")
            wait_guard()
            check("rerig", RERIGS, [("Plain", "0aaaaaaa")])
            check("cleaned", (plain / "unrigged" / "0aaaaaaa.glb").read_bytes(), b"glTF-plain-src-clean")
            CLEANS.clear(); RERIGS.clear(); AFTER.clear()

            print("[7] cleanup fails")
            write_source({"status": "skipped", "reason": "disabled for this character"})
            clean_raises["on"] = True
            check("start", post("/characters/Demo/model3d/face-cleanup")[0], 200)
            wait_guard()
            result = model3d._face_cleanup_results.get("Demo") or {}
            check("result", (result.get("ok"), result.get("error")), (False, "Face cleanup failed: boom"))
            check("source unchanged", source.read_bytes(), b"glTF-src")
            check("no follow-up", (RERIGS, FACES, AFTER), ([], [], []))
            with model3d._lock:
                check("guard released", "Demo" in model3d._generating, False)
            clean_raises["on"] = False

        print("[8] base-body extras")
        info = routes._base_body_model_extras("Demo", {"signature": bsig, "humanoid": True,
                                                       "model": {"status": "ready", "signature": bsig}})
        check("cleanup signature", (info.get("face_cleanup") or {}).get("signature"), bsig)
        check("scales", info.get("collision_scales"), collision.default_scales())
        check("face fields", "face_retexture" in info["model"], True)
        check("collision key", "collision" in info["model"], True)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
