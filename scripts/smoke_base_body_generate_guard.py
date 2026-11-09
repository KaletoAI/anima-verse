#!/usr/bin/env python3
"""Base body: the Pose tab's Generate refuses without the base views
(``POST /characters/{n}/model-refs/generate``, bug E of 2026-11-09).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_generate_guard.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server process (the
characters router in a bare FastAPI app). ``model_refs.trigger_now`` is a
recorder, so nothing renders.

Before the fix, a pipeline character whose CURRENT base signature had no
base images got 200 from the route; the worker then found no base view,
logged "base images of <bsig> missing" and returned {} — the tab showed
nothing. Now the route answers 409 with BASE_FIRST before any thread starts.

Fixture: ``Demo`` (human-roleplay, base-body pipeline), ``Plain`` (the same
profile, NOT on the pipeline). BSIG = base_signature(Demo); base view files
are model_refs/tpose_BSIG.png (front) and tpose_<view>_BSIG.png.

Expected, derived by hand from the route rule "a T-pose render of a pipeline
character needs the base view(s) it edits: view None = all four, main = the
front, a view = that view; face is no edit of the base body":
[1] No base images: {kinds [tpose], view back} -> 409 BASE_FIRST;
    {kinds [tpose], view main} -> 409 BASE_FIRST; {kinds [tpose]} -> 409
    BASE_FIRST; no trigger_now call.
[2] {kinds [pose]} (the default-pose ref, no base edit) -> 200, one trigger
    with kinds ("pose",).
[3] {kinds [tpose], view face} -> not BASE_FIRST (the face view comes from
    the profile picture).
[4] Only the front base view written: view main -> 200 (trigger kinds
    ("tpose",), tpose_view "main"); view back -> 409 BASE_FIRST; no view ->
    409 BASE_FIRST (back/left/right missing).
[5] All four base views written: no view -> 200; view back without a
    dressed front -> 409 DRESSED_FRONT_FIRST "Render the dressed front
    first — the back draft is made from it" (2026-11-09: the back is a draft
    from the dressed front fitted onto the base back).
[6] Plain (off the pipeline), no base images: view main -> 200.
[7] Side views (2026-11-09: only front and back are dressed): Demo view
    left -> 409 SIDE_VIEW_NOT_DRESSED "On the base-body pipeline only the
    front and the back are dressed — the side views belong to the base body
    (Base body tab)", view right the same, no trigger; with a dressed front
    of the current outfit (tpose_<osig>.png, sidecar base_signature BSIG,
    base_image_sha256 = sha256 of tpose_BSIG.png) view back -> 200, trigger
    (Demo, ("tpose",), "back"). Plain view left -> never the side-view 409
    (it is off the pipeline).
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
    with tempfile.TemporaryDirectory(prefix="base-generate-guard-") as tmp:
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

        from app.core import base_body, model_refs
        from app.models.character import get_character_dir, save_character_profile
        TRIGGERS = []
        model_refs.trigger_now = lambda name, kinds=None, **kw: TRIGGERS.append(
            (name, tuple(kinds) if kinds is not None else None, kw.get("tpose_view")))

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        for name in ("Demo", "Plain"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True),
                  True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        bsig = base_body.base_signature("Demo")
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)

        def write_base(view):
            name = f"tpose_{bsig}.png" if view == "front" else f"tpose_{view}_{bsig}.png"
            (refs / name).write_bytes(b"\x89PNG-" + view.encode())

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes import characters as routes
        app = FastAPI()
        app.include_router(routes.router)
        url = "/characters/{}/model-refs/generate"
        want_msg = "Render the base body first (Base body tab) — the outfit views are edits of it"
        check("message", getattr(routes, "BASE_FIRST", None), want_msg)

        with TestClient(app, raise_server_exceptions=False) as client:
            def post(name, body):
                r = client.post(url.format(name), json=body)
                try:
                    detail = r.json().get("detail")
                except ValueError:
                    detail = None
                return r.status_code, detail

            print("[1] no base images")
            check("view back", post("Demo", {"kinds": ["tpose"], "view": "back"}), (409, want_msg))
            check("view main", post("Demo", {"kinds": ["tpose"], "view": "main"}), (409, want_msg))
            check("no view", post("Demo", {"kinds": ["tpose"]}), (409, want_msg))
            check("no thread started", TRIGGERS, [])

            print("[2] default pose")
            check("pose", post("Demo", {"kinds": ["pose"]})[0], 200)
            check("pose triggered", TRIGGERS, [("Demo", ("pose",), None)])
            TRIGGERS.clear()

            print("[3] face view")
            check("face not refused for the base", post("Demo", {"kinds": ["tpose"], "view": "face"})[1] != want_msg,
                  True)
            TRIGGERS.clear()

            print("[4] front base view only")
            write_base("front")
            check("main", post("Demo", {"kinds": ["tpose"], "view": "main"})[0], 200)
            check("main triggered", TRIGGERS, [("Demo", ("tpose",), "main")])
            TRIGGERS.clear()
            check("back", post("Demo", {"kinds": ["tpose"], "view": "back"}), (409, want_msg))
            check("all views", post("Demo", {"kinds": ["tpose"]}), (409, want_msg))
            check("nothing triggered", TRIGGERS, [])

            print("[5] all base views")
            for view in ("back", "left", "right"):
                write_base(view)
            check("all views", post("Demo", {"kinds": ["tpose"]})[0], 200)
            check("all triggered", TRIGGERS, [("Demo", ("tpose",), None)])
            TRIGGERS.clear()
            check("back without dressed front", post("Demo", {"kinds": ["tpose"], "view": "back"}),
                  (409, "Render the dressed front first — the back draft is made from it"))

            print("[6] off the pipeline")
            check("Plain main", post("Plain", {"kinds": ["tpose"], "view": "main"})[0], 200)
            check("Plain triggered", TRIGGERS, [("Plain", ("tpose",), "main")])
            TRIGGERS.clear()

            print("[7] side views")
            side = ("On the base-body pipeline only the front and the back are dressed — the side views "
                    "belong to the base body (Base body tab)")
            check("left", post("Demo", {"kinds": ["tpose"], "view": "left"}), (409, side))
            check("right", post("Demo", {"kinds": ["tpose"], "view": "right"}), (409, side))
            check("no side trigger", TRIGGERS, [])
            import hashlib
            osig = model_refs.current_outfit_state("Demo")[2]
            (refs / f"tpose_{osig}.png").write_bytes(b"\x89PNG-dressed")
            (refs / f"tpose_{osig}.json").write_text(json.dumps({
                "base_signature": bsig, "dressed": True,
                "base_image_sha256": hashlib.sha256((refs / f"tpose_{bsig}.png").read_bytes()).hexdigest()}))
            check("back with dressed front", post("Demo", {"kinds": ["tpose"], "view": "back"})[0], 200)
            check("back triggered", TRIGGERS, [("Demo", ("tpose",), "back")])
            check("Plain left not the side 409", post("Plain", {"kinds": ["tpose"], "view": "left"})[1] != side,
                  True)

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
