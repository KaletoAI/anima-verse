#!/usr/bin/env python3
"""Task 11g-fix6 of the unified worn pieces (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``; ledger rulings
A18, A19, A20): a Build step that finds its figure moved ends "superseded"
(no failure) with ONE follow-up; a shape no longer wanted stops before its
next hub stage; a distance mesh is built from the path it is handed and its
failure is a warning; the base body's own actions are refused while a Build
runs; a garment chain refuses a composite onto a base view rendered again
meanwhile — with that reason.

Why (audit 2026-11-13, ~/claude-out/build-audit-2026-11-13.md):
- D1: Kai's interim shape was meshed (5 hub jobs), then a jeans fit was
  accepted in a parallel chain, the step re-judged the figure of NOW and
  failed "Views missing: front, back"; the follow-up started from zero, three
  times. Ylva's face and rig ran on a shape the hair change had made obsolete,
  and the assembly failed "the body shape is not built".
- D2: ``request_lod`` looked the just-staged model up with the stale rules,
  found "no_model" and the whole outfit model was never delivered.
- D4: base views re-rendered by hand while a Build / a garment chain ran:
  meshes from replaced fronts, a composite onto the new base back refused
  for a misleading "drift".

Usage:
    ./.venv/bin/python scripts/smoke_build_superseded.py

Throwaway storage + instance, a copy of the ``human`` package; no world, no
hub, no GPU, no server.

Expected, derived by hand from the rulings:

[1] (removed with Ruling A119: Kai's case was the interim step, which no
    longer exists — a piece not ready is left off, no shape is meshed for
    it; the superseded shape step stays covered by [1b].)
[1b] Ylva's hair switch during the shape's mesh (A18). Plan [shape,
    assemble], wanted shape "obHAIR"; inside ``prepare_shape`` the hair moves
    to HairDeck: wanted shape "obBALD"; the stub returns what the real one
    does when the guard says no (``{ok: False, superseded: True}``) ->
    superseded at "shape", why ``SHAPE_MOVED`` (obHAIR, now obBALD); no
    assembly, no failure.
[1c] The wanted figure moves between steps (Y2): plan [shape, fits,
    assemble]; the shape builds, during the CPU fits the hair moves (shape
    obHAIR -> obBALD, hair body -> hairdeck). Before the assembly the pin is
    checked: superseded at "assemble", why ``WANTED_MOVED`` with the moved
    ``Figure.as_dict`` keys in their order: "shape, hair".
[1d] A plain body step waits for reserved base views first: plan
    [plain_body]; call order ["wait", "plain_body"]; no pin check before it.
[2] The shape guard between hub stages (A18; model3d, the real staged
    chain with a fake hub). Guard False from the start, face before rig ON:
    mesh 1, upscale 0, face 0, rig 0, result ``{ok: False, superseded:
    True}`` with ``SHAPE_NOT_WANTED`` stage "face". Face OFF: mesh 1, rig 0,
    stage "rig". Face ON, wanted until the face ran: face 1, rig 0, stage
    "rig". Guard True: one rig, ok.
[3] The distance mesh (A19). A staged model whose lookup counts it as stale
    (``find_model3d`` None — the D2 case): ``request_lod`` builds the low
    tier from the handed path (True, ``low/sig.glb`` = the Blender output,
    its sidecar names ``sig.glb``). Blender fails ("blender down"): no
    exception, False, the sidecar carries ``lod_error`` "blender down", the
    low tier of the file is gone, the model stays.
[4] Base routes while a Build runs (A20): images, model and skin step ->
    409 ``BASE_BUILD_RUNNING``; with no Build the images route starts the
    render (``{"started": True}``, one call). ``_wait_base_views``: a view
    reserved and released after 0.3 s -> returns [] after >= 0.25 s; still
    reserved at a 0.2 s timeout -> returns ["front"].
[5] A garment chain whose base back is rendered again while the back's
    draft renders (Kai's jacket, 12:46): ``run_garment`` -> ok False, step
    "worn", error ``BASE_VIEW_CHANGED_ERROR`` with "back"; the composite
    never ran. ``_composite_guard`` on unchanged views raises nothing.
"""
import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []
BSIG = "base0123abcd"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


# --- [1] the Build's pins ----------------------------------------------------------------------------------------

def section_pins() -> None:
    from app.core import base_body, figure, figure_build, model3d
    from app.core.figure import Figure

    def fig(shape, *, in_body=("tshirt",), own=("jacket", "jeans"), hair="body", signature="sigK"):
        return Figure(signature=signature, bsig=BSIG, shape=shape, texture="", in_body=tuple(in_body), painted=(),
                      own=tuple(own), hair=hair, pieces={"top": "tshirt", "outer": "jacket", "legs": "jeans"})

    state = {}
    calls = []

    @contextlib.contextmanager
    def slot(_c, poll_s=1.0):
        yield

    def run(name, steps):
        with figure_build._lock:
            figure_build._queues[name] = deque()
            figure_build._active.add(name)
        try:
            figure_build._run_planned(name, "body_change", {}, automatic=True)
        finally:
            with figure_build._lock:
                queued = list(figure_build._queues.pop(name, ()))
                figure_build._active.discard(name)
        return figure_build.state(name), queued

    runners = dict(figure_build._RUNNERS)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(figure, "_delivered", lambda c, profile, **kw: (state["wanted"], state["delivered"])))
        stack.enter_context(patch.object(figure, "_shape_stored", lambda *a, **k: False))
        stack.enter_context(patch.object(figure_build, "_read_profile", lambda c: {}))
        stack.enter_context(patch.object(figure_build, "_tracked", lambda c, label: (None, "")))
        stack.enter_context(patch.object(figure_build, "_dressed", lambda c, w: calls.append("views") or ""))
        stack.enter_context(patch.object(figure_build, "_outfit_model", lambda c, s: calls.append("outfit_model") or ""))
        stack.enter_context(patch.object(model3d, "generation_slot", slot))
        stack.enter_context(patch.dict(figure_build._RUNNERS, {
            "assemble": lambda c, s, e=False: calls.append("assemble") or "",
            "fits": lambda c, s, e=False: (state.update(state.get("during_fits") or {}), calls.append("fits"))[1] or "",
            "plain_body": lambda c, s, e=False: calls.append("plain_body") or ""}))
        stack.enter_context(patch.object(figure_build, "_wait_base_views", lambda c, **k: calls.append("wait") or []))
        step = figure_build.Step

        print("[1b] Ylva: the hair switched while the shape is meshed")
        state.update(wanted=fig("obHAIR", own=()), delivered=fig(BSIG, own=()))
        calls.clear()

        def prepare_shape(c, f, **kw):
            calls.append(("prepare_shape", f.shape))
            state["wanted"] = fig("obBALD", own=(), hair="hairdeck")
            if not model3d.shape_still_wanted(c, f.shape):
                return {"ok": False, "superseded": True, "error": "stub: not wanted", "body_id": f.shape}
            return {"ok": True}

        with patch.object(base_body, "prepare_shape", prepare_shape), \
                patch.object(figure_build, "plan", lambda *a, **k: [step("shape", "Body shape", 4),
                                                                    step("assemble", "Assemble the figure", 0)]):
            got, queued = run("Ylva", None)
        check("the shape stopped, no assembly", calls, [("prepare_shape", "obHAIR")])
        check("superseded at the shape, no failure",
              (got["failed"], got["superseded"] and got["superseded"]["step"], got["superseded"]
               and got["superseded"]["note"], queued),
              ({}, "shape", figure_build.SUPERSEDED.format(
                  why=figure_build.SHAPE_MOVED.format(shape="obHAIR", now="obBALD"),
                  new="figure sigK (shape obBALD)"), [(figure_build.SUPERSEDED_REASON, True)]))

        print("[1c] the wanted figure moves between steps: the assembly is superseded, not 'shape not built'")
        state.update(wanted=fig("obHAIR", own=()), delivered=fig(BSIG, own=()),
                     during_fits={"wanted": fig("obBALD", own=(), hair="hairdeck")})
        calls.clear()
        with patch.object(base_body, "prepare_shape", lambda c, f, **kw: calls.append(("prepare_shape", f.shape))
                          or {"ok": True}), \
                patch.object(figure_build, "plan", lambda *a, **k: [step("shape", "Body shape", 4),
                                                                    step("fits", "Fits on the CPU", 0),
                                                                    step("assemble", "Assemble the figure", 0)]):
            got, queued = run("Ylva", None)
        state.pop("during_fits")
        check("shape and fits ran, the assembly did not", calls, [("prepare_shape", "obHAIR"), "fits"])
        check("superseded at the assembly: shape and hair moved",
              (got["failed"], got["superseded"] and got["superseded"]["note"]),
              ({}, figure_build.SUPERSEDED.format(why=figure_build.WANTED_MOVED.format(fields="shape, hair"),
                                                  new="figure sigK (shape obBALD)")))

        print("[1d] the plain body step waits for reserved base views first")
        calls.clear()
        with patch.object(figure_build, "plan", lambda *a, **k: [step("plain_body", "Plain body", 4)]):
            got, queued = run("Kai", None)
        check("wait, then the plain body; nothing kept", (calls, got["failed"], got["superseded"], queued),
              (["wait", "plain_body"], {}, None, []))
    check("runners restored", figure_build._RUNNERS == runners, True)


# --- [2] the shape guard between hub stages (model3d) ------------------------------------------------------------

def section_stage_guard(root: Path) -> None:
    from smoke_face_retexture_rollback import fixture, photo
    from smoke_face_retexture_check import glb
    from app.core import base_body, face_retexture, model3d
    # A163: these fixtures exercise the FRONT source (no face view) — the stored setting, not a fallback.
    face_retexture.stored_source = lambda _c: 'front'
    from app.models.character import save_character_profile

    model_root = root / "world" / "characters" / "guard" / "model3d"
    model_root.mkdir(parents=True)
    sig = "0123456789ab"
    image = model_root.parent / "model_refs" / f"tpose_{sig}.png"
    image.parent.mkdir()
    image.write_bytes(photo())
    counts = {"mesh": 0, "upscale": 0, "face": 0, "rig": 0}

    class Service:
        def generate_mesh(self, **kw):
            counts["mesh"] += 1
            Path(kw["output_path"]).write_bytes(fixture())
            return dict(ok=True, path=kw["output_path"], backend="mesh-fixture", format="glb")

        def upscale_image(self, raw, **kw):
            counts["upscale"] += 1
            return dict(bytes=raw, status="applied", backend="up-fixture", **{"in": [16, 16], "out": [16, 16]})

        def generate_face_retexture(self, source, raw, target, *args, **kw):
            counts["face"] += 1
            out = Path(target) / "corrected.glb"
            out.write_bytes(fixture(corrected=True))
            out.with_suffix(".png").write_bytes(photo())
            return dict(ok=True, path=str(out), compare_path=str(out.with_suffix(".png")), backend="face-fixture")

        def generate_rig(self, **kw):
            counts["rig"] += 1
            from app.core.model_validate import parse_glb
            from app.core.rig_contract import BASE_JOINT_NAMES
            parsed = parse_glb(Path(kw["mesh_path"]).read_bytes())
            doc = parsed["gltf"]
            doc["nodes"] = [{"name": n} for n in BASE_JOINT_NAMES]
            doc["skins"] = [{"joints": list(range(52))}]
            Path(kw["output_path"]).write_bytes(glb(doc, parsed["bin"]))
            return dict(ok=True, path=kw["output_path"], rig="mixamo", backend="rig-fixture")

    svc = Service()
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("app.imagegen.service.get_image_service", return_value=svc))
        stack.enter_context(patch.object(base_body, "is_base_pipeline", lambda *a, **k: False))
        stack.enter_context(patch.object(model3d, "required_rig", return_value="mixamo"))
        stack.enter_context(patch.object(model3d, "find_ref_image", return_value=image))
        stack.enter_context(patch("app.core.model_refs.enabled_tpose_views", return_value=[]))
        stack.enter_context(patch.object(model3d, "_ref_manifest", return_value={"pieces": {}, "items": []}))
        for name in ("_auto_retexture", "_auto_normalize", "_attach_measurement", "request_lod"):
            stack.enter_context(patch.object(model3d, name))
        stack.enter_context(patch.object(model3d, "_auto_extension_rig", return_value={"ok": True}))
        stack.enter_context(patch.object(face_retexture, "runnable", return_value={"ok": True, "problems": []}))
        stack.enter_context(patch.object(face_retexture, "photo_controls_supported", return_value=False))
        check("guard character", save_character_profile("guard", {}, create_new=True), True)

        def generate(face, wanted):
            model3d.set_model3d_options("guard", {"face_before_rig": face})
            for k in counts:
                counts[k] = 0
            with model3d.shape_guard("guard", sig, wanted):
                result = model3d.generate_for_current_outfit("guard", signature=sig, force=True,
                                                             backend_glob="mesh-fixture")
            return result, dict(counts)

        print("[2] the shape is no longer wanted after its mesh")
        result, got = generate(True, lambda: False)
        check("face before rig: the mesh only", got, {"mesh": 1, "upscale": 0, "face": 0, "rig": 0})
        check("stopped before the face, superseded",
              (result.get("ok"), result.get("superseded"), result.get("error")),
              (False, True, model3d.SHAPE_NOT_WANTED.format(stage="face", signature=sig)))
        result, got = generate(False, lambda: False)
        check("no face step: the mesh only", got, {"mesh": 1, "upscale": 0, "face": 0, "rig": 0})
        check("stopped before the rig", (result.get("superseded"), result.get("error")),
              (True, model3d.SHAPE_NOT_WANTED.format(stage="rig", signature=sig)))
        result, got = generate(True, lambda: counts["face"] == 0)
        check("unwanted after the face: no rig", got, {"mesh": 1, "upscale": 1, "face": 1, "rig": 0})
        check("stopped before the rig (face path)", (result.get("superseded"), result.get("error")),
              (True, model3d.SHAPE_NOT_WANTED.format(stage="rig", signature=sig)))
        result, got = generate(False, lambda: True)
        check("still wanted: one rig, delivered", (result.get("ok"), got["rig"]), (True, 1))
        check("no guard left behind", model3d.shape_still_wanted("guard", sig), True)


# --- [3] the distance mesh from the handed path ------------------------------------------------------------------

def section_lod(root: Path) -> None:
    from app.core import model3d
    stage = root / "stage"
    stage.mkdir()
    model = stage / "sig.glb"
    model.write_bytes(b"full-model")
    model3d._publish_sidecar(model, {"rig": "mixamo", "character": "Demo", "signature": "sig"})
    blender = {"fail": False}

    def run(operation, *, inputs, params, out_dir, timeout_s=0):
        if blender["fail"]:
            return {"ok": False, "error": "blender down"}
        check("Blender reads the handed model", Path(inputs["model"]), model)
        out = Path(out_dir) / "low.glb"
        out.write_bytes(b"low-model")
        return {"ok": True, "outputs": {"model": str(out)}, "data": {"stages": [{"tris": 10, "tris_before": 40}]}}

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(model3d, "_auto_lod_enabled", return_value=True))
        stack.enter_context(patch.object(model3d, "_auto_lod_ratio", return_value=0.25))
        stack.enter_context(patch.object(model3d, "find_model3d", return_value=None))   # stale by the lookup (D2)
        stack.enter_context(patch.object(model3d, "find_model3d_serving", return_value=(None, "")))
        stack.enter_context(patch.object(model3d, "_validator_for", return_value=lambda blob: {"ok": True}))
        stack.enter_context(patch("app.blender.runner.run", side_effect=run))
        stack.enter_context(patch("app.blender.refine.unavailable_reason", return_value=None))
        stack.enter_context(patch("app.core.model_validate.rig_frames_preserved", return_value={"ok": True}))
        stack.enter_context(patch("app.core.extension_rig.resolved_extension_groups", return_value=[]))
        stack.enter_context(patch("app.core.extension_rig.extension_metadata", return_value={"fingerprint": "f"}))
        stack.enter_context(patch("app.core.garment_assembly.schedule", return_value=None))
        model3d._staging.directories = {"Demo": stage}
        try:
            print("[3] the distance mesh of a staged model")
            check("built from the handed path although the lookup calls it stale",
                  (model3d.request_lod("Demo", model), (stage / "low" / "sig.glb").read_bytes(),
                   model3d._read_sidecar(stage / "low" / "sig.glb").get("source_file")),
                  (True, b"low-model", "sig.glb"))
            blender["fail"] = True
            try:
                answer = model3d.request_lod("Demo", model)
            except Exception as e:  # noqa: BLE001 — the old behaviour
                answer = f"raised {e}"
            check("Blender down: a warning, no exception", answer, False)
            check("the model stays, its sidecar names the LOD error, the old low tier is gone",
                  (model.read_bytes(), model3d._read_sidecar(model).get("lod_error"),
                   (stage / "low" / "sig.glb").exists()),
                  (b"full-model", "blender down", False))
        finally:
            model3d._staging.directories = {}


# --- [4] the base body while a Build runs --------------------------------------------------------------------------

def section_routes() -> None:
    from fastapi import HTTPException
    from app.core import base_body, figure_build
    from app.routes import characters as routes

    def status(fn):
        try:
            fn()
        except HTTPException as e:
            return e.status_code, e.detail
        return 200, None

    started = []
    print("[4] base routes while a Build runs")
    with patch.object(base_body, "check_renderable", lambda *a, **k: {}), \
            patch.object(base_body, "check_model_ready", lambda *a, **k: None), \
            patch.object(base_body, "start_base_images", lambda c, **k: started.append(("images", c))), \
            patch.object(base_body, "start_base_model", lambda c, **k: started.append(("model", c)) or True):
        with figure_build._lock:
            figure_build._active.add("Demo")
        try:
            refused = (409, figure_build.BASE_BUILD_RUNNING)
            check("images: 409", status(lambda: routes.generate_character_base_body_images(
                "Demo", routes.BaseBodyImagesRequest(view="front", force=True), {})), refused)
            check("model: 409", status(lambda: routes.generate_character_base_body_model(
                "Demo", routes.BaseBodyModelRequest(force=True), {})), refused)
            check("skin step: 409", status(lambda: routes.rerun_character_base_body_skin_step("Demo", {})), refused)
            check("nothing started", started, [])
        finally:
            with figure_build._lock:
                figure_build._active.discard("Demo")
        check("no Build: the render starts", (routes.generate_character_base_body_images(
            "Demo", routes.BaseBodyImagesRequest(view="front"), {}), started), ({"started": True}, [("images", "Demo")]))

    print("[4b] the plain body step waits for reserved base views")
    base_body.reserve_views("Demo", ["front"])
    timer = threading.Timer(0.3, lambda: base_body.release_views("Demo", ["front"]))
    t0 = time.monotonic()
    timer.start()
    left = figure_build._wait_base_views("Demo", timeout_s=5.0, poll_s=0.05)
    waited = time.monotonic() - t0
    timer.join()
    check("released after 0.3 s: waited, nothing left", (left, waited >= 0.25), ([], True))
    base_body.reserve_views("Demo", ["front"])
    try:
        check("still reserved at the timeout", figure_build._wait_base_views("Demo", timeout_s=0.2, poll_s=0.05),
              ["front"])
    finally:
        base_body.release_views("Demo", ["front"])


# --- [5] a garment composite onto a base back rendered again meanwhile ------------------------------------------

def section_composite(root: Path) -> None:
    import numpy as np
    import smoke_garment_clothing_back as gcb
    from app.core import base_body, expression_regen, garment_assembly, garment_images, garment_mesh, garments
    from app.core import garment_store as gs
    from app.core import view_composite
    from app.models import character as charmod
    from app.models import inventory
    from app.models.character import get_character_dir

    jid = inventory.add_item(name="Black Blazer", category="outfit_piece", prompt_fragment=gcb.FRAGMENT,
                             outfit_piece={"slots": ["top"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
    check("inventory", inventory.add_to_inventory("Demo", jid), True)
    refs = get_character_dir("Demo") / "model_refs"
    refs.mkdir(parents=True, exist_ok=True)
    bsig = base_body.base_signature("Demo")
    for v in base_body.BASE_VIEWS:
        stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
        (refs / f"{stem}.png").write_bytes(gcb.png(gcb.BASE))
        (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
    base_back = refs / f"tpose_back_{bsig}.png"
    composites = []

    def recorder(character_name, *, output_stem, **kw):
        g = kw["sidecar_extra"]["garment"]
        if g.get("stage") == "draft":
            # The user renders the base back again while the draft renders (Kai, 12:46-12:47).
            base_back.write_bytes(gcb.png(gcb.BACK_OK))
        arr = gcb.FRONT
        out = np.full((kw["override_height"], kw["override_width"], 3), 128, dtype=np.uint8)
        dy, dx = (out.shape[0] - arr.shape[0]) // 2, (out.shape[1] - arr.shape[1]) // 2
        out[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
        path = Path(str(output_stem) + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gcb.png(out))
        path.with_suffix(".json").write_text(json.dumps(kw["sidecar_extra"]))
        return path

    def compose(base_view, draft_file, target, **kw):
        composites.append(Path(target).name)
        raise AssertionError("no composite onto a base view rendered again meanwhile")

    print("[5] the base back rendered again while the chain drafts its back")
    with patch.object(expression_regen, "render_character_image", recorder), \
            patch.object(view_composite, "compose", compose), \
            patch.object(charmod, "run_rembg", gcb.rembg_stub), \
            patch.object(garment_assembly, "schedule", lambda *a, **k: False), \
            patch.object(garment_mesh, "generate", lambda *a, **k: None), \
            patch.object(garments, "_fit", lambda *a, **k: None), \
            patch("app.imagegen.service.get_image_service", side_effect=AssertionError("no hub call")):
        shas = garments._base_view_shas("Demo", bsig)
        garments._composite_guard("Demo", bsig, shas, "worn")()   # unchanged: nothing raised
        res = garments.run_garment("Demo", jid)
    check("refused at the worn step with the true reason",
          (res.get("ok"), res.get("step"), res.get("error")),
          (False, "worn", garments.BASE_VIEW_CHANGED_ERROR.format(views="back")))
    check("no composite ran", composites, [])
    check("the worn front was accepted before", gs.read_record(
        gs.garment_path("Demo", jid, res.get("fsig"), "image", step="worn", view="front").with_suffix(".json"))
          .get("accepted"), True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="build-superseded-") as tmp:
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
        from _figure_build_fixtures import record_requests
        record_requests()   # no automatic Build beside the producers measured here
        from app.models.character import save_character_profile
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)

        section_pins()
        section_stage_guard(root)
        section_lod(root)
        section_routes()
        section_composite(root)

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
