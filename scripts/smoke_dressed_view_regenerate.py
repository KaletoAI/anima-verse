#!/usr/bin/env python3
"""Ruling A70: a dressed view's Regenerate says what it does — an edit (1 image job) or a copy of the body
shape's view (no job).

Usage:
    ./.venv/bin/python scripts/smoke_dressed_view_regenerate.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no server process (the characters router in a bare FastAPI app). The image render
(``expression_regen.render_character_image``) is a recorder that writes a PNG, so nothing reaches a backend.

The bug (user 2026-11-14, Kai): "Regenerate this view — 1 image job" on the Pose tab ran no job. Kai's figure
stands on a meshed body shape (``ob…``) with nothing painted on it (texture ""), so
``base_body.generate_dressed_images`` takes its copy branch: the outfit's view is the shape's own view copied
again — the same bytes, no render. The route still answered ``{"status": "generating"}`` and the button's
"1 image job" was a constant.

Fixture: ``Demo`` (human-roleplay, base-body pipeline). BSIG = base_signature(Demo), OB = "ob0a1b2c3d" (a meshed
shape), OSIG = "smokeosig" (the outfit's signature). ``figure.delivered_figure`` / ``delivered_figure_cached`` are
stubbed to return Figure(shape=SHAPE, texture=TEX, bsig=BSIG); ``base_body.figure_texts`` to {view: TEXT}.
The shape's views model_refs/tpose_<OB>.png and tpose_back_<OB>.png are 8x8 PNGs of grey 40 and 90.

Expected, derived by hand from the rule "a meshed shape paints exactly when the figure has a texture (Ruling A50);
the plain body paints when the front's dress text is not empty; what does not paint is a copy, no job":
[1] dressed_view_source(Demo):
      SHAPE=OB, TEX=""          -> {source "shape",   shape OB,   jobs 0}
      SHAPE=OB, TEX="texabc"    -> {source "painted", shape OB,   jobs 1}
      SHAPE=BSIG, TEXT ""       -> {source "plain",   shape BSIG, jobs 0}
      SHAPE=BSIG, TEXT "a dress" -> {source "painted", shape BSIG, jobs 1}
[2] generate_dressed_images(OSIG, view "back", force True) with SHAPE=OB, TEX="": 0 renders; the result names
    tpose_back; model_refs/tpose_back_<OSIG>.png has the bytes of tpose_back_<OB>.png; its sidecar dressed False,
    base_signature OB.
[3] the same with TEX="texabc", TEXT "a red dress", view "main", force True: exactly 1 render, occasion "outfit_front", output stem
    model_refs/tpose_<OSIG>.
[4] POST /characters/Demo/model-refs/generate (trigger_now a recorder, the base-image guards passed):
      {kinds [tpose], view main}, TEX=""        -> 200 {status "copying", jobs 0, source "shape"}
      {kinds [tpose], view main}, TEX="texabc"  -> 200 {status "generating", jobs 1, source "painted"}
      {kinds [tpose], view main}, SHAPE=BSIG, TEXT "" -> 200 {status "copying", jobs 0, source "plain"}
      {kinds [tpose]} (all views)               -> 200 {status "generating"} (no per-view claim)
      {kinds [pose]}                            -> 200 {status "generating"}
    every call reached trigger_now once (5 calls); get_model_refs_info(Demo)["dressed_source"]["source"] with
    TEX="" is "shape".
[5] Fails on the old code (commit 2c743fb54, before A70): the route's only answer was {"status": "generating"}
    (no "copying", no "jobs") and FieldModelRefs labelled every view's Regenerate singleAction('view', 1, t) —
    the [4] expectation "copying, jobs 0" cannot hold there.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "2c743fb54"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(grey: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (grey, grey, grey)).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dressed-view-regen-") as tmp:
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

        from app.core import base_body, expression_regen, figure, model_refs
        from app.models.character import get_character_dir, save_character_profile
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        check("Demo on the pipeline", base_body.is_base_pipeline("Demo"), True)
        bsig = base_body.base_signature("Demo")
        ob, osig = "ob0a1b2c3d", "smokeosig"
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        for view, grey in (("front", 40), ("back", 90)):
            stem = "tpose" if view == "front" else f"tpose_{view}"
            for on in (ob, bsig):
                (refs / f"{stem}_{on}.png").write_bytes(png(grey))

        state = {"shape": ob, "tex": "", "text": ""}

        def fig(*_a, **_kw):
            return figure.Figure(signature=osig, bsig=bsig, shape=state["shape"], texture=state["tex"],
                                 in_body=("dress",) if state["shape"] == ob else (), painted=(), own=())
        figure.delivered_figure = fig
        figure.delivered_figure_cached = fig
        base_body.figure_texts = lambda c, f, items, profile=None: {v: state["text"] for v in base_body.dressed_views()}
        model_refs.current_outfit_state = lambda c: ({}, [], osig)

        print("[1] dressed_view_source")
        for shape, tex, text, want in ((ob, "", "", {"source": "shape", "shape": ob, "jobs": 0}),
                                       (ob, "texabc", "", {"source": "painted", "shape": ob, "jobs": 1}),
                                       (bsig, "", "", {"source": "plain", "shape": bsig, "jobs": 0}),
                                       (bsig, "", "a dress", {"source": "painted", "shape": bsig, "jobs": 1})):
            state.update(shape=shape, tex=tex, text=text)
            check(f"{'OB' if shape == ob else 'BSIG'} tex={tex!r} text={text!r}",
                  base_body.dressed_view_source("Demo"), want)

        renders = []

        def render(name, *, output_stem, occasion="", **kw):
            renders.append((occasion, Path(output_stem).name))
            out = Path(output_stem).with_suffix(".png")
            out.write_bytes(png(200))
            return out
        expression_regen.render_character_image = render

        print("[2] copy branch: no render")
        state.update(shape=ob, tex="", text="")
        got = base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig, force=True, view="back")
        check("renders", renders, [])
        check("result kinds", sorted(k for k, v in got.items() if v), ["tpose_back"])
        target = refs / f"tpose_back_{osig}.png"
        check("copied bytes", target.is_file() and target.read_bytes() == (refs / f"tpose_back_{ob}.png").read_bytes(),
              True)
        meta = json.loads(target.with_suffix(".json").read_text()) if target.with_suffix(".json").is_file() else {}
        check("sidecar dressed / base_signature", (meta.get("dressed"), meta.get("base_signature")), (False, ob))

        print("[3] painted: exactly one render")
        state.update(tex="texabc", text="a red dress")
        renders.clear()
        base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig, force=True, view="front")
        check("renders", renders, [("outfit_front", f"tpose_{osig}")])

        print("[4] the route answers what the click does")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes import characters as routes
        triggers = []
        model_refs.trigger_now = lambda name, kinds=None, **kw: triggers.append((name, kinds, kw.get("tpose_view")))
        routes._require_dressable_view = lambda *a, **kw: None
        routes._require_base_images = lambda *a, **kw: None
        app = FastAPI()
        app.include_router(routes.router)
        url = "/characters/Demo/model-refs/generate"
        with TestClient(app, raise_server_exceptions=False) as client:
            def post(body):
                r = client.post(url, json=body)
                return r.status_code, r.json()
            state.update(shape=ob, tex="", text="")
            check("main, shape copy", post({"kinds": ["tpose"], "view": "main"}),
                  (200, {"status": "copying", "jobs": 0, "source": "shape"}))
            state.update(tex="texabc")
            check("main, painted", post({"kinds": ["tpose"], "view": "main"}),
                  (200, {"status": "generating", "jobs": 1, "source": "painted"}))
            state.update(shape=bsig, tex="", text="")
            check("main, plain copy", post({"kinds": ["tpose"], "view": "main"}),
                  (200, {"status": "copying", "jobs": 0, "source": "plain"}))
            check("all views", post({"kinds": ["tpose"]}), (200, {"status": "generating"}))
            check("default pose", post({"kinds": ["pose"]}), (200, {"status": "generating"}))
        check("trigger calls", len(triggers), 5)
        state.update(shape=ob, tex="", text="")
        check("info dressed_source", (model_refs.get_model_refs_info("Demo").get("dressed_source") or {}).get("source"),
              "shape")

    print(f"[5] fails on the old code ({OLD})")

    def old(path):
        return subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True,
                              check=True).stdout
    route = old("app/routes/characters.py")
    body = route.split("async def generate_character_model_refs", 1)[1].split("\ndef ", 1)[0]
    check("old route: one answer, generating", body.count("return {"), 1)
    check("old route: no copying / jobs", ("copying" in body, "jobs" in body), (False, False))
    refs_old = old("frontend/src/tabs/characters/FieldModelRefs.tsx")
    check("old button: 1 image job for every view", "singleAction('view', 1, t)" in refs_old, True)

    if FAILS:
        print(f"\nFAILED: {len(FAILS)} — {FAILS}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
