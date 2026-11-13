#!/usr/bin/env python3
"""The Game-Admin 3D tab's actions on the base-body pipeline vs the old path
(audit 2026-11-09, ``app/core/model3d_pipeline.py``).

Usage:
    ./.venv/bin/python scripts/smoke_model3d_tab_pipeline.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server process (the
characters router in a bare FastAPI app, ``require_admin`` overridden).
``model3d.trigger_generation``, ``model_refs.trigger_now``,
``figure_build.start``, ``model3d.trigger_rerig``, ``model3d.rerig_model`` and
``model3d.rebuild_extension_rig`` are recorders, so nothing renders, meshes
or rigs.

Fixture: ``Demo`` (human-roleplay, base-body pipeline), ``Plain``
(animal-default — off the pipeline; until Task 11h a human with the pipeline switch off, a state that no longer exists). BSIG = base_signature(Demo), OSIG = Demo's
current outfit signature. The rigged base model is model3d/BSIG.glb with
sidecar {rig: mixamo} (``base_model_info`` -> "ready"); its re-rig source is
model3d/unrigged/BSIG.glb. A dressed view counts as current when its ref
(model_refs/tpose[_back]_OSIG.png) has a sidecar with base_signature BSIG
and base_image_sha256 = sha256 of the base view it edits
(model_refs/tpose[_back]_BSIG.png) — ``base_body.dressed_image``; the
dressed views are front and back (side views off by default).

Expected, derived by hand from the rules in the module docstring:
[1] Off the pipeline (Plain): no T-pose ref -> POST generate 409 "No pose
    render for the current outfit — generate it first"; with
    model_refs/tpose_<Plain osig>.png -> 200 {status: generating}, one
    trigger_generation(Plain, force=False, backend_glob="").
    pipeline_state(Plain) is None.
[2] Ruling FR-I4 — on the pipeline POST generate IS the Build (``figure_build.start`` a recorder answering
    STARTED["answer"], default {status: started}; ``figure.start_manual_build`` maps it like POST
    …/figure/build): ?backend=x, ?face_num=5000, ?texture_size=1024 -> 400 NO_BACKEND, nothing started;
    generate and generate?force=1 -> 202 {status: started}, each one start(Demo, reason="manual"); no
    trigger_now and no trigger_generation (the old cascade is unreachable).
[3] The answers map like the Build route's, for both routes alike (POST generate and POST …/figure/build):
    queued -> 202 {status: queued}; current -> 202 {status: current}; base_busy (reason "B") -> 409 "B";
    off (reason "O") -> 409 "O"; failed (reason "F") -> 503 "F".
[4] Admin only on the pipeline: ``routes.require_admin`` answering 403 -> generate 403 "Admin role required",
    nothing started; Plain (off the pipeline, its T-pose ref stored in [1]) still reaches its own path:
    200 {status: generating} — not 403.
[5] Fails on the old code: at commit 5eab1741 the route called ``model3d_pipeline.rebuild_from_base`` (the
    cascade) and ``model3d_pipeline`` defined it.
[6] Base model and dressed views for the sections below: model3d/BSIG.glb with {rig: mixamo} -> pipeline
    base_model "ready"; the dressed views written -> dressed_current True.
[7] Refusals on the pipeline (409, REFUSED with the action):
    upload "Uploading a model", fetch-job "Fetching a mesh job",
    rig "Changing the rig label". Plain: upload of an invalid GLB -> 422
    (validation, not refused); fetch-job "!!" -> 400 "Not a job id"; rig
    {mixamo} -> 404 "No model".
[8] Re-rig: Demo without model3d/unrigged/BSIG.glb -> 409 "The base body has
    no retained unrigged mesh. ..."; with it and ?signature=OSIG ->
    trigger_rerig(Demo, BSIG) — the BASE, whatever was asked. Plain
    ?signature=OSIG_PLAIN without unrigged -> 409 "No retained unrigged mesh
    source. ..." (unchanged).
[9] trigger_rerig: rerig_model ok -> after_base_face_change(Demo, BSIG) once;
    rerig_model failed -> not called.
[10] Extension bones for all models (rebuild_character_extension_rigs):
    Demo has BSIG.glb (current base), base00000000.glb (older base),
    0aaaaaaa.glb (outfit built on BSIG + its sha256), 1bbbbbbb.glb (outfit
    built on base00000000) -> rebuilt in this order: [BSIG, 0aaaaaaa];
    base00000000 and 1bbbbbbb {ok: True, skipped: "stale"}. Plain with
    1ccccccc.glb and 0ddddddd.glb -> [0ddddddd, 1ccccccc] (sorted, all).
[12] Improvements "extension_rig_rebuild" completion (is_done) on the same
    Demo models: before any extension state -> False. After the rebuild
    wrote states on its TARGETS only — BSIG.glb (base, rig mixamo,
    status applied, fingerprint of the groups a base carries, no distance
    tier: a base body has none) and 0aaaaaaa.glb (applied + low/0aaaaaaa.glb
    with the same fingerprint) -> True, find_candidates -> [], although the
    stale 1bbbbbbb.glb and the older base00000000.glb carry no state at all
    (the old check looked at every *.glb and wanted a low tier for the base
    too, so it never reported done). Without low/0aaaaaaa.glb -> False.
[11] GET /model3d (get_model3d_info stubbed — it probes the mesh backends
    over the network): Demo carries pipeline {base_signature BSIG, base_model
    "ready", rerig_source True, dressed_current True, fallback None} — no
    rebuilding / queued keys (the cascade is gone, Ruling FR-I4);
    Plain carries pipeline None.
"""
import hashlib
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
    with tempfile.TemporaryDirectory(prefix="model3d-tab-pipeline-") as tmp:
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

        from app.core import base_body, model3d, model3d_pipeline, model_refs
        from app.models.character import get_character_dir, save_character_profile

        GENERATIONS, DRESS, RERIGS = [], [], []
        dress_writes = {"on": False}

        GEN_ANSWERS = []  # queued answers of the recorder; True when empty

        def fake_generation(name, **kw):
            GENERATIONS.append((name, kw.get("force", False), kw.get("backend_glob", ""), kw.get("followup", False)))
            return GEN_ANSWERS.pop(0) if GEN_ANSWERS else True

        def fake_trigger_now(name, kinds=None, **kw):
            DRESS.append((name, tuple(kinds or ()), kw.get("force"), kw.get("blocking")))
            if dress_writes["on"]:
                write_dressed()

        real_trigger_rerig = model3d.trigger_rerig
        model3d.trigger_generation = fake_generation
        model_refs.trigger_now = fake_trigger_now
        model3d.trigger_rerig = lambda name, sig, **kw: RERIGS.append((name, sig)) or {"status": "generating"}

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        check("create Plain", save_character_profile("Plain", {"template": "animal-default"}, create_new=True),
              True)
        bsig = base_body.base_signature("Demo")
        osig = model_refs.current_outfit_state("Demo")[2]
        psig = model_refs.current_outfit_state("Plain")[2]
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        models = get_character_dir("Demo") / "model3d"
        models.mkdir(parents=True, exist_ok=True)
        for view in ("front", "back", "left", "right"):
            stem = f"tpose_{bsig}" if view == "front" else f"tpose_{view}_{bsig}"
            (refs / f"{stem}.png").write_bytes(b"\x89PNG-base-" + view.encode())

        def write_dressed():
            for view in ("front", "back"):
                base = refs / (f"tpose_{bsig}.png" if view == "front" else f"tpose_{view}_{bsig}.png")
                stem = f"tpose_{osig}" if view == "front" else f"tpose_{view}_{osig}"
                (refs / f"{stem}.png").write_bytes(b"\x89PNG-dressed-" + view.encode())
                (refs / f"{stem}.json").write_text(json.dumps({
                    "base_signature": bsig, "dressed": True,
                    "base_image_sha256": hashlib.sha256(base.read_bytes()).hexdigest()}))

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        from app.routes import characters as routes
        from app.routes import figure as figure_routes
        from app.core import figure_build
        from fastapi import HTTPException
        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(figure_routes.router)
        app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
        ROLE = {"admin": True}

        def route_admin(_request):
            if not ROLE["admin"]:
                raise HTTPException(status_code=403, detail="Admin role required")
            return {"role": "admin"}
        routes.require_admin = route_admin
        STARTED = {"answer": {"status": "started"}, "calls": []}
        figure_build.start = lambda name, **kw: STARTED["calls"].append((name, kw)) or dict(STARTED["answer"])

        with TestClient(app, raise_server_exceptions=False) as client:
            def call(method, url, **kw):
                r = client.request(method, url, **kw)
                try:
                    body = r.json()
                except ValueError:
                    body = None
                return r.status_code, body

            def detail(result):
                return result[0], (result[1] or {}).get("detail")

            print("[1] off the pipeline")
            check("Plain state", model3d_pipeline.pipeline_state("Plain"), None)
            check("Plain no tpose", detail(call("POST", "/characters/Plain/model3d/generate")),
                  (409, "No pose render for the current outfit — generate it first"))
            prefs = get_character_dir("Plain") / "model_refs"
            prefs.mkdir(parents=True, exist_ok=True)
            (prefs / f"tpose_{psig}.png").write_bytes(b"\x89PNG-plain")
            check("Plain generate", call("POST", "/characters/Plain/model3d/generate"), (200, {"status": "generating"}))
            check("Plain trigger", GENERATIONS, [("Plain", False, "", False)])
            GENERATIONS.clear()

            print("[2] Ruling FR-I4: generate on the pipeline is the Build")
            for query in ("backend=x", "face_num=5000", "texture_size=1024"):
                check(f"400 {query}", detail(call("POST", f"/characters/Demo/model3d/generate?{query}")),
                      (400, model3d_pipeline.NO_BACKEND))
            check("nothing started", STARTED["calls"], [])
            for query in ("", "?force=1"):
                check(f"generate{query}", call("POST", f"/characters/Demo/model3d/generate{query}"),
                      (202, {"status": "started"}))
            check("two manual Builds", STARTED["calls"], [("Demo", {"reason": "manual"})] * 2)
            check("no cascade", (DRESS, GENERATIONS), ([], []))
            STARTED["calls"].clear()

            print("[3] the answers map like the Build route's")
            for answer, want in (({"status": "queued"}, (202, {"status": "queued"})),
                                 ({"status": "current"}, (202, {"status": "current"})),
                                 ({"status": "base_busy", "reason": "B"}, (409, "B")),
                                 ({"status": "off", "reason": "O"}, (409, "O")),
                                 ({"status": "failed", "reason": "F"}, (503, "F"))):
                STARTED["answer"] = answer
                for url in ("/characters/Demo/model3d/generate", "/characters/Demo/figure/build"):
                    got = call("POST", url)
                    if got[0] >= 400:
                        got = detail(got)
                    check(f"{answer['status']} {url.rsplit('/', 2)[-2]}", got, want)
            STARTED["answer"] = {"status": "started"}
            STARTED["calls"].clear()

            print("[4] admin only on the pipeline")
            ROLE["admin"] = False
            check("non-admin 403", detail(call("POST", "/characters/Demo/model3d/generate")),
                  (403, "Admin role required"))
            check("nothing started", STARTED["calls"], [])
            check("Plain keeps its own path", call("POST", "/characters/Plain/model3d/generate"),
                  (200, {"status": "generating"}))
            ROLE["admin"] = True
            GENERATIONS.clear()

            print("[5] fails on the old code (5eab1741)")
            import subprocess
            old_route = subprocess.run(["git", "-C", str(ROOT), "show", "5eab1741:app/routes/characters.py"],
                                       capture_output=True, text=True).stdout
            old_pipe = subprocess.run(["git", "-C", str(ROOT), "show", "5eab1741:app/core/model3d_pipeline.py"],
                                      capture_output=True, text=True).stdout
            check("5eab1741: the route ran the cascade", "model3d_pipeline.rebuild_from_base(character_name)"
                  in old_route, True)
            check("5eab1741: the cascade existed", "def rebuild_from_base" in old_pipe, True)
            check("the cascade is gone", hasattr(model3d_pipeline, "rebuild_from_base"), False)

            print("[6] base model and dressed views for the sections below")
            (models / f"{bsig}.glb").write_bytes(b"glTF-base")
            (models / f"{bsig}.json").write_text(json.dumps({"rig": "mixamo", "base": True}))
            check("base ready", model3d_pipeline.pipeline_state("Demo")["base_model"], "ready")
            write_dressed()
            check("dressed current", model3d_pipeline.pipeline_state("Demo")["dressed_current"], True)

            print("[7] refusals")
            glb = {"file": ("x.glb", b"not a glb", "model/gltf-binary")}
            check("Demo upload", detail(call("POST", "/characters/Demo/model3d/upload", files=glb)),
                  (409, model3d_pipeline.REFUSED.format(action="Uploading a model")))
            check("Plain upload validated", call("POST", "/characters/Plain/model3d/upload", files=glb)[0], 422)
            check("Demo fetch-job", detail(call("POST", "/characters/Demo/model3d/fetch-job?job=466a4e41b73d")),
                  (409, model3d_pipeline.REFUSED.format(action="Fetching a mesh job")))
            check("Plain fetch-job", detail(call("POST", "/characters/Plain/model3d/fetch-job?job=!!")),
                  (400, "Not a job id"))
            check("Demo rig", detail(call("POST", "/characters/Demo/model3d/rig", json={"rig": "mixamo"})),
                  (409, model3d_pipeline.REFUSED.format(action="Changing the rig label")))
            check("Plain rig", detail(call("POST", "/characters/Plain/model3d/rig", json={"rig": "mixamo"})),
                  (404, "No model"))

            print("[8] re-rig")
            check("Demo no base source", detail(call("POST", f"/characters/Demo/model3d/rerig?signature={osig}")),
                  (409, "The base body has no retained unrigged mesh. Generate the base model again (Base body tab)."))
            (models / "unrigged").mkdir(exist_ok=True)
            (models / "unrigged" / f"{bsig}.glb").write_bytes(b"glTF-unrigged")
            check("Demo re-rig", call("POST", f"/characters/Demo/model3d/rerig?signature={osig}")[0], 200)
            check("the base is re-rigged", RERIGS, [("Demo", bsig)])
            check("Plain unchanged", detail(call("POST", f"/characters/Plain/model3d/rerig?signature={psig}")),
                  (409, "No retained unrigged mesh source. Generate a new model to enable re-rigging."))

            print("[11] status payload")
            # The model part of the payload probes the mesh backends (network):
            # stubbed — only the route's pipeline annotation is under test.
            model3d.get_model3d_info = lambda name, preview_states=None: {"pending": False, "model": None}
            status = call("GET", "/characters/Demo/model3d")
            check("Demo GET", status[0], 200)
            check("Demo pipeline", (status[1] or {}).get("pipeline"),
                  {"base_signature": bsig, "base_model": "ready", "rerig_source": True,
                   "dressed_current": True, "fallback": None})
            # The current outfit has no model: the tab says so (model3d_pipeline.fallback_state).
            model3d.get_model3d_info = lambda name, preview_states=None: {"pending": False, "model": None,
                                                                          "signature": osig}
            fb = ((call("GET", "/characters/Demo/model3d")[1] or {}).get("pipeline") or {}).get("fallback") or {}
            check("Demo fallback without a model", (fb.get("current_signature"), fb.get("served_signature")),
                  (osig, ""))
            plain = call("GET", "/characters/Plain/model3d")
            check("Plain pipeline", (plain[0], "pipeline" in (plain[1] or {}), (plain[1] or {}).get("pipeline")),
                  (200, True, None))

        print("[9] trigger_rerig follow-up")
        real = model3d
        real.trigger_rerig = real_trigger_rerig  # the real one back
        HOOK = []
        real.after_base_face_change = lambda name, sig: HOOK.append((name, sig))
        for ok in (True, False):
            real.rerig_model = lambda name, sig, **kw: {"ok": ok, "error": "" if ok else "x"}
            started = real.trigger_rerig("Demo", bsig)
            check(f"started ({ok})", started.get("status"), "generating")
            for _ in range(200):
                with real._lock:
                    if "Demo" not in real._generating:
                        break
                time.sleep(0.02)
        check("hook only after success", HOOK, [("Demo", bsig)])

        print("[10] extension bones for all models")
        ORDER = []
        real.rebuild_extension_rig = lambda name, sig, **kw: ORDER.append((name, sig)) or {"ok": True}
        base_sha = hashlib.sha256((models / f"{bsig}.glb").read_bytes()).hexdigest()
        (models / "base00000000.glb").write_bytes(b"glTF-old-base")
        (models / "0aaaaaaa.glb").write_bytes(b"glTF-outfit")
        (models / "0aaaaaaa.json").write_text(json.dumps({"base_signature": bsig, "base_model_sha256": base_sha}))
        (models / "1bbbbbbb.glb").write_bytes(b"glTF-old-outfit")
        (models / "1bbbbbbb.json").write_text(json.dumps({"base_signature": "base00000000",
                                                         "base_model_sha256": "0" * 64}))
        result = real.rebuild_character_extension_rigs("Demo")
        check("Demo order", ORDER, [("Demo", bsig), ("Demo", "0aaaaaaa")])
        check("Demo skipped", {k: v for k, v in result["models"].items() if v.get("skipped")},
              {"base00000000": {"ok": True, "skipped": "stale"}, "1bbbbbbb": {"ok": True, "skipped": "stale"}})
        check("Demo ok", result["ok"], True)
        ORDER.clear()
        pmodels = get_character_dir("Plain") / "model3d"
        pmodels.mkdir(parents=True, exist_ok=True)
        (pmodels / "1ccccccc.glb").write_bytes(b"glTF")
        (pmodels / "0ddddddd.glb").write_bytes(b"glTF")
        real.rebuild_character_extension_rigs("Plain")
        check("Plain order", ORDER, [("Plain", "0ddddddd"), ("Plain", "1ccccccc")])

        print("[12] extension_rig_rebuild completion on the pipeline")
        from app.core.extension_rig import extension_rig_fingerprint, rig_groups_for
        from app.core.improvements.base import Candidate
        from app.core.improvements.types.extension_rig_rebuild import ExtensionRigRebuild
        improvement = ExtensionRigRebuild()
        params = {"character": "Demo"}
        candidate = Candidate("character:Demo", "Demo")
        check("not done before", improvement.is_done(candidate, params), False)
        groups = rig_groups_for("Demo")
        base_groups = [g for g in groups if g["op"] not in model3d.PART_OPS]

        def state(declared):
            return {"attempted": True, "status": "applied",
                    "fingerprint": extension_rig_fingerprint(declared, {})}

        (models / f"{bsig}.json").write_text(json.dumps({"rig": "mixamo", "base": True,
                                                          "extension_rig": state(base_groups)}))
        outfit_meta = {"base_signature": bsig, "base_model_sha256": base_sha, "rig": "mixamo",
                       "extension_rig": state(groups)}
        (models / "0aaaaaaa.json").write_text(json.dumps(outfit_meta))
        (models / "low").mkdir(exist_ok=True)
        (models / "low" / "0aaaaaaa.glb").write_bytes(b"glTF-low")
        (models / "low" / "0aaaaaaa.json").write_text(json.dumps({"extension_rig": state(groups)}))
        check("targets", [p.stem for p in model3d.extension_rebuild_targets("Demo")[0]], [bsig, "0aaaaaaa"])
        check("done after the rebuild", improvement.is_done(candidate, params), True)
        check("no candidates", improvement.find_candidates(params), [])
        (models / "low" / "0aaaaaaa.glb").unlink()
        check("outfit needs its distance tier", improvement.is_done(candidate, params), False)

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
