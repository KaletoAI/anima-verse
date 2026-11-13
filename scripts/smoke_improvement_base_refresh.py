#!/usr/bin/env python3
"""The ``base_refresh`` improvement type (app/core/improvements/types/base_refresh.py;
spec docs/superpowers/specs/2026-11-11-hair-from-body-design.md § Design 5):
base bodies rendered with older prompt texts, rebuilt at idle time, the cost
shown before start.

Usage:
    ./.venv/bin/python scripts/smoke_improvement_base_refresh.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server.

Fixture: Kira (human-roleplay, female, 30, 168 cm, profile picture
``Kira_1.png``) on the base-body pipeline; Mira (same, on the pipeline too —
every humanoid is since Task 11h, Ruling A13 — but WITHOUT a base body; was:
off the pipeline through the removed switch).
``bsig`` = base_signature(Kira), ``fp`` = prompt_fingerprint(Kira). Kira's
four base views ``model_refs/tpose[_<view>]_<bsig>.png`` carry sidecars with
``prompt_fingerprint`` "000000000000" (older prompts; the front stamped
2026-11-01T10:00:00+00:00, the others five minutes later), and a ready base
model ``model3d/<bsig>.glb`` (rig mixamo, ``base: true``) whose sidecar
records the sha256 of exactly these four views — the model is current
against its views, only the prompts are old.

The producers below the real ``generate_base_images`` / ``generate_base_model``
are recorders: ``expression_regen.render_character_image`` writes an 8x8
image (one opaque pixel, a new colour per call — so every render has a new
sha) and a sidecar ``{**sidecar_extra, "created_at": now}``; it answers None
for a view named in FAIL_VIEWS. ``model3d.generate_for_current_outfit``
records ``(force, signature, base)`` and writes the base model's sidecar with
the sha256 of the views stored NOW → ``{"ok": True}`` (MODEL["mode"] "fail":
``{"ok": False, "error": "rig failed"}``; "busy" raises BackendBusyError;
"hubop" raises HubOpBusy). ``garments.after_base_model`` and
``artefact_graph.collect_quietly`` are recorders (the after-base hooks).
``routing.explain_occasion`` resolves every occasion to "Fake" unless a case
empties one. Face before rig is off unless a case turns it on.

Cost, by hand from the refresh's step list (``base_body.base_rebuild_steps``:
one image job per view in BASE_VIEWS = front, back, left, right; then the
hub stages of a fresh mesh run, ``model3d.mesh_hub_stages``: mesh; with face
before rig on a mixamo rig and a face route: upscale when the reference is
the front view, face; rig — normalize and the other Blender steps are CPU):

* older prompts, face off: 4 + mesh + rig = 6, note "older prompts: views 4
  + mesh + rig = 6 hub jobs (first attempts; the hand gate may render the
  front up to 2 more times)".

[B1] the note → exactly one candidate ``base:Kira``, label "Kira · base body
     · older prompts", hub_jobs 6, the note above; needs_media True.
     Through the engine (one_shot): handle_step → {"ok": True}; four renders
     in BASE_VIEWS order with occasions base_front, base_view ×3 and the
     sidecar fingerprint fp; then ONE model build (force True, bsig, base
     True); after-base hooks: after_base_model ["Kira"], collect_quietly
     reasons ["base images rendered", "base model generated"]; the guard
     released; base_prompts_freshness "current"; base_signature unchanged
     (prompts are not identity — the files replaced in place); rescan → no
     candidate; is_done True; the one-shot worked itself off.
[B2] no note → no candidate: the refreshed Kira; Mira (on the pipeline, no base model → off the roster);
     Kira's base model file gone (not ready → off the figure roster); the
     front gone (missing is not older). Params: character "Kira" narrows,
     "Mira" → [], "Nope" → ValueError "invalid value for 'character'" (the
     enum's own check, before the type's).
[B3] a failed last attempt is excluded, a failure during apply is terminal:
     (a) ``_failed[("Kira","left")]`` = error → no candidate; apply →
     CandidateRefused naming "left"; a hand-gate WARNING on the front is no
     failure → the candidate is back. (b) the base model's failure record
     → base_model_info "failed" → no candidate. (c) the old fingerprint again,
     FAIL_VIEWS {"back"} through the engine → "refused", step skipped +
     refused, attempts 1, the error "views back — render failed"; the build
     never called; afterwards no candidate (the back's failure record).
     (d) the views current, the model stale, MODEL "fail" → CandidateRefused
     "model — rig failed"; then no candidate (the model failed).
[B4] busy: (a) a base view reserved running → no candidate; apply →
     CandidateBusy. (b) the generation guard held → no candidate; apply →
     CandidateBusy, nothing rendered. (c) the occasion base_view resolving to
     nothing → CandidateBusy, nothing rendered. (d) the REAL render path
     (``render_character_image`` → the service facade → a routed backend
     raising BackendBusyError), through the engine → {"busy": …}, step
     pending, attempts 0, refused 0; ONE routed render "base_front"; no view
     failure recorded, nothing running; still a candidate (older prompts).
     (e) the views current, the model stale; MODEL "busy" → CandidateBusy,
     NO base model failure (status "ready"), still a candidate (reason
     model); MODEL "hubop" → CandidateBusy likewise.
[B5] cost: (a) face before rig on, face route ok, no face view (reference
     front → upscale): 4 + mesh + upscale + face + rig = 8, the note adds
     "the dark-face gate may retry the face once"; (b) the reference "face"
     (patched): 7; (c) no face route (runnable not ok): 6; (d) face on but a
     non-mixamo rig: face_before_rig_planned False. (e) only the back's
     fingerprint old (the front current) → reason "views", label "Kira ·
     base body · views not refreshed yet", hub 1 + 2 = 3, note "views not
     refreshed yet: views 1 + mesh + rig = 3 hub jobs (first attempts)"; the
     apply renders the back ALONE (one call, base_view), then builds.
     (f) every view current, the model's recorded front sha another one →
     reason "model", hub 2, note "model built from older views: mesh + rig =
     2 hub jobs (first attempts)"; the apply renders nothing, builds once.
     (g) hub_jobs == the sum over base_rebuild_steps in every case above.

Fails on f16bdcb3: ModuleNotFoundError — app.core.improvements.types.base_refresh
(and ``generate_base_images`` takes no ``raise_load`` there); checked below
against that commit's files when git is available.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
BASELINE = "f16bdcb3"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc):
    try:
        fn()
    except exc as e:
        check(label, type(e).__name__, exc.__name__)
        return e
    except Exception as e:  # noqa: BLE001
        check(label, f"{type(e).__name__}: {e}", exc.__name__)
        return None
    check(label, "no exception", exc.__name__)
    return None


def tiny_png(path: Path, rgb=(200, 100, 50)) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), (*rgb, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def baseline_proof() -> None:
    """The type and the opt-in do not exist at the baseline commit."""
    def show(path):
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:{path}"],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None
    init = show("app/core/improvements/types/__init__.py")
    if init is None:
        print(f"  SKIP baseline proof (git show {BASELINE} unavailable)")
        return
    check(f"{BASELINE}: no base_refresh module", show("app/core/improvements/types/base_refresh.py"), None)
    check(f"{BASELINE}: base_refresh not registered", "base_refresh" in init, False)
    body = show("app/core/base_body.py") or ""
    check(f"{BASELINE}: no base_rebuild_cost", "def base_rebuild_cost" in body, False)
    check(f"{BASELINE}: generate_base_images without raise_load",
          "force: bool = False, raise_load" in body, False)


def main() -> int:
    print("[0] fails on the baseline")
    baseline_proof()
    with tempfile.TemporaryDirectory(prefix="improvement-base-refresh-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        # The base front's skin detail step (base_skin) is off here: these
        # checks count the base renders; smoke_base_skin_step.py covers the step.
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                       "base_body": {"skin_detail_step": False}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import artefact_graph, base_body, expression_regen, face_retexture, garments, model3d
        from app.core.hub_ops import HubOpBusy
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import CandidateBusy, CandidateRefused
        from app.core.improvements.types.base_refresh import BaseRefresh
        from app.core.improvements.types import subjects
        from app.core.task_queue import get_task_queue
        from app.core.timeutils import utc_now_iso
        from app.imagegen.base import BackendBusyError
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        get_task_queue()._started = True          # no worker threads: rows only
        registry.clear()
        typ = BaseRefresh()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        for name in ("Kira", "Mira"):
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
            tiny_png(get_character_images_dir(name) / f"{name}_1.png")
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)
        bsig = base_body.base_signature("Kira")
        fp = base_body.prompt_fingerprint("Kira")
        cdir = get_character_dir("Kira")
        mdir, refs = cdir / "model3d", cdir / "model_refs"
        mdir.mkdir(parents=True, exist_ok=True)
        refs.mkdir(parents=True, exist_ok=True)

        def stem(view):
            return refs / (f"tpose_{bsig}" if view == "front" else f"tpose_{view}_{bsig}")

        def view_sha(view):
            return hashlib.sha256(stem(view).with_suffix(".png").read_bytes()).hexdigest()

        def write_view(view, fingerprint, created, rgb):
            tiny_png(stem(view).with_suffix(".png"), rgb)
            stem(view).with_suffix(".json").write_text(json.dumps({
                "base_signature": bsig, "base_identity": bsig, "prompt_fingerprint": fingerprint,
                "created_at": created}))

        def old_base():
            for i, view in enumerate(base_body.BASE_VIEWS):
                write_view(view, "000000000000",
                           "2026-11-01T10:00:00+00:00" if view == "front" else "2026-11-01T10:05:00+00:00",
                           (10 * i, 20, 30))

        def write_model(front_sha=None):
            (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
            (mdir / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated",
                "source_image": f"tpose_{bsig}.png",
                "source_image_sha256": front_sha or view_sha("front"),
                "view_images_sha256": {v: view_sha(v) for v in base_body.BASE_VIEWS if v != "front"}}))

        old_base()
        write_model()
        check("base ready", (base_body.base_model_info("Kira") or {}).get("status"), "ready")
        check("the note", base_body.base_prompts_freshness("Kira"),
              {"state": "stale", "reason": base_body.OLDER_PROMPTS})

        RENDERS = []
        BUILDS = []
        HOOKS = []
        FAIL_VIEWS = set()
        MODEL = {"mode": "ok"}
        RESOLVE = {}
        colour = [0]

        def recorder(character_name, *, output_stem, sidecar_extra=None, occasion="", **kw):
            view = "front" if output_stem.name.startswith(f"tpose_{bsig}") else output_stem.name.split("_")[1]
            RENDERS.append((view, occasion, (sidecar_extra or {}).get("prompt_fingerprint")))
            if view in FAIL_VIEWS:
                return None
            colour[0] += 1
            path = output_stem.with_suffix(".png")
            tiny_png(path, (colour[0] % 250, 99, 7))
            path.with_suffix(".json").write_text(json.dumps({**(sidecar_extra or {}), "created_at": utc_now_iso()}))
            return path

        def build(name, *, force=False, signature=None, base=False, **kw):
            BUILDS.append((force, signature, base))
            if MODEL["mode"] == "busy":
                raise BackendBusyError("gpu busy")
            if MODEL["mode"] == "hubop":
                raise HubOpBusy("target in flight")
            if MODEL["mode"] == "fail":
                return {"ok": False, "error": "rig failed"}
            write_model()
            return {"ok": True}

        def explain(occasion, character="", pool=None, **kw):
            return {"resolved": RESOLVE.get(occasion, "Fake")}

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def summary(**params):
            return [(c.key, c.label, c.hub_jobs, c.note) for c in cands(**params)]

        def run_step(entry, key):
            store.mark_running(entry, key)
            return engine.handle_step({"improvement_id": entry, "candidate_key": key, "_task_id": "t"})

        def clear_status():
            with base_body._status_lock:
                base_body._failed.clear()
                base_body._model_failed.clear()
                base_body._running.clear()

        def reset_calls():
            del RENDERS[:], BUILDS[:], HOOKS[:]

        key = "base:Kira"
        note6 = ("older prompts: views 4 + mesh + rig = 6 hub jobs "
                 "(first attempts; the hand gate may render the front up to 2 more times)")
        real_render = expression_regen.render_character_image
        with patch.object(expression_regen, "render_character_image", recorder), \
             patch.object(model3d, "generate_for_current_outfit", build), \
             patch.object(garments, "after_base_model", lambda name: HOOKS.append(("after_base_model", name))), \
             patch.object(artefact_graph, "collect_quietly",
                          lambda name, reason, **kw: HOOKS.append(("collect", reason))), \
             patch("app.imagegen.routing.explain_occasion", explain):

            # --- [B1] ---------------------------------------------------------------
            print("[B1] a base with the OLDER_PROMPTS note")
            check("one candidate", summary(), [(key, "Kira · base body · older prompts", 6, note6)])
            check("needs_media", typ.needs_media, True)
            entry = store.create(typ.id, "Refresh", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            step = store.list_steps(entry)[0]
            check("the step carries the cost", (step["hub_jobs"], step["note"]), (6, note6))
            check("handle_step ok", run_step(entry, key), {"ok": True})
            check("four renders, BASE_VIEWS order, current fingerprint", RENDERS,
                  [("front", "base_front", fp), ("back", "base_view", fp),
                   ("left", "base_view", fp), ("right", "base_view", fp)])
            check("one model build", BUILDS, [(True, bsig, True)])
            check("the after-base hooks", HOOKS, [("collect", "base images rendered"),
                                                 ("after_base_model", "Kira"),
                                                 ("collect", "base model generated")])
            check("the guard released", model3d.generation_running("Kira"), False)
            check("the note is gone", base_body.base_prompts_freshness("Kira")["state"], "current")
            check("same base signature (replaced in place)", base_body.base_signature("Kira"), bsig)
            check("rescan: no candidate", cands(), [])
            check("is_done", typ.is_done(Candidate_(key), typ.validate({})), True)
            check("the one-shot worked itself off", store.get(entry), None)

            # --- [B2] ---------------------------------------------------------------
            print("[B2] no note, no candidate")
            check("Mira on the pipeline (humanoid)", base_body.is_base_pipeline("Mira"), True)
            check("Mira off the roster (no base model)", "Mira" in subjects.pipeline_characters(), False)
            check("refreshed Kira: nothing", cands(), [])
            old_base()
            write_model()
            check("filter Kira", [c.key for c in cands(character="Kira")], [key])
            check("filter Mira", cands(character="Mira"), [])
            e = raises("filter Nope", lambda: typ.validate({"character": "Nope"}), ValueError)
            check("filter Nope message", str(e), "invalid value for 'character'")
            (mdir / f"{bsig}.glb").rename(mdir / "hidden.glb")
            check("no base model: not on the figure roster", cands(), [])
            (mdir / "hidden.glb").rename(mdir / f"{bsig}.glb")
            front_files = [stem("front").with_suffix(s) for s in (".png", ".json")]
            for p in front_files:
                p.rename(p.with_name("hidden" + p.suffix))
            check("no front: missing is not older", cands(), [])
            for p in front_files:
                p.with_name("hidden" + p.suffix).rename(p)
            check("restored: the candidate is back", [c.key for c in cands()], [key])

            # --- [B3] ---------------------------------------------------------------
            print("[B3] a failed last attempt is excluded; a failure in apply is terminal")
            reset_calls()
            cand = cands()[0]
            base_body._record("Kira", "left", "backend error")
            check("(a) a view's failure record: no candidate", cands(), [])
            e = raises("(a) apply → CandidateRefused", lambda: typ.apply(cand, typ.validate({}), "t"),
                       CandidateRefused)
            check("(a) names the view", "left" in str(e), True)
            clear_status()
            base_body._record("Kira", "front", base_body.hand_gate_warning(3), warning=True)
            check("(a) a hand-gate warning is no failure", [c.key for c in cands()], [key])
            clear_status()
            with base_body._status_lock:
                base_body._model_failed["Kira"] = {"signature": bsig, "error": "rig failed"}
            check("(b) model failed", base_body.base_model_info("Kira")["status"], "failed")
            check("(b) no candidate", cands(), [])
            clear_status()
            check("calls so far", (RENDERS, BUILDS), ([], []))

            FAIL_VIEWS.add("back")
            entry = store.create(typ.id, "Refresh", typ.validate({}), "one_shot")["id"]
            check("(c) scan", engine.scan(entry), {"added": 1, "closed": 0})
            result = run_step(entry, key)
            check("(c) the engine reports the refusal", list(result.keys()), ["refused"])
            step = store.list_steps(entry)[0]
            check("(c) skipped + refused after one attempt",
                  (step["status"], step["refused"], step["attempts"], step["error"]),
                  ("skipped", 1, 1, "views back — render failed"))
            check("(c) the build never called", BUILDS, [])
            check("(c) no candidate (the back's failure record)", cands(), [])
            store.delete(entry)
            FAIL_VIEWS.clear()
            clear_status()

            reset_calls()
            for v in base_body.BASE_VIEWS:
                write_view(v, fp, "2026-11-02T10:00:00+00:00", (1, 2, base_body.BASE_VIEWS.index(v)))
            write_model(front_sha="0" * 64)
            check("(d) model stale only", [(c.key, c.hub_jobs) for c in cands()], [(key, 2)])
            MODEL["mode"] = "fail"
            e = raises("(d) apply → CandidateRefused", lambda: typ.apply(cands()[0], typ.validate({}), "t"),
                       CandidateRefused)
            check("(d) the error", str(e), "model — rig failed")
            check("(d) no render, one build", (RENDERS, BUILDS), ([], [(True, bsig, True)]))
            check("(d) no candidate (the model failed)", cands(), [])
            MODEL["mode"] = "ok"
            clear_status()

            # --- [B4] ---------------------------------------------------------------
            print("[B4] busy")
            reset_calls()
            old_base()
            write_model()
            cand = cands()[0]
            base_body.reserve_views("Kira", ("back",))
            check("(a) a view running: no candidate", cands(), [])
            raises("(a) apply → CandidateBusy", lambda: typ.apply(cand, typ.validate({}), "t"), CandidateBusy)
            base_body.release_views("Kira", ("back",))
            with model3d._lock:
                model3d._generating.add("Kira")
            try:
                check("(b) the guard held: no candidate", cands(), [])
                raises("(b) apply → CandidateBusy", lambda: typ.apply(cand, typ.validate({}), "t"), CandidateBusy)
            finally:
                with model3d._lock:
                    model3d._generating.discard("Kira")
            RESOLVE["base_view"] = ""
            raises("(c) base_view unresolved → CandidateBusy",
                   lambda: typ.apply(cand, typ.validate({}), "t"), CandidateBusy)
            RESOLVE.clear()
            check("(a–c) nothing rendered or built", (RENDERS, BUILDS), ([], []))

        # [B4d] the real render path: render_character_image → the facade → a busy backend.
        print("[B4d] a busy backend on the real render path")
        from app.imagegen import service
        svc = service.ImageService({})
        svc.enabled = True          # no instances: the routing below stands in for the backend
        routed = []

        def busy_backend(occasion, render, **kw):
            routed.append(occasion)
            raise BackendBusyError("gpu busy")

        check("the real renderer is back", expression_regen.render_character_image is real_render, True)
        with patch.object(model3d, "generate_for_current_outfit", build), \
             patch("app.imagegen.routing.explain_occasion", explain), \
             patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", busy_backend):
            reset_calls()
            entry = store.create(typ.id, "Refresh", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            result = run_step(entry, key)
            check("busy, not refused", list(result.keys()), ["busy"])
            step = store.list_steps(entry)[0]
            check("step pending, no attempt, not refused",
                  (step["status"], step["attempts"], step["refused"]), ("pending", 0, 0))
            check("one routed render, the front", routed, ["base_front"])
            status = base_body.base_status("Kira")
            check("no view failure, nothing running",
                  [(v, s["failed"], s["running"]) for v, s in status.items()],
                  [(v, False, False) for v in base_body.BASE_VIEWS])
            check("the build never called", BUILDS, [])
            check("still a candidate (older prompts)",
                  [(c.key, c.label) for c in cands()], [(key, "Kira · base body · older prompts")])
            store.delete(entry)

        with patch.object(expression_regen, "render_character_image", recorder), \
             patch.object(model3d, "generate_for_current_outfit", build), \
             patch.object(garments, "after_base_model", lambda name: HOOKS.append(("after_base_model", name))), \
             patch.object(artefact_graph, "collect_quietly",
                          lambda name, reason, **kw: HOOKS.append(("collect", reason))), \
             patch("app.imagegen.routing.explain_occasion", explain):
            print("[B4e] load in the model stage")
            reset_calls()
            for v in base_body.BASE_VIEWS:
                write_view(v, fp, "2026-11-02T10:00:00+00:00", (3, 4, base_body.BASE_VIEWS.index(v)))
            write_model(front_sha="0" * 64)
            for mode in ("busy", "hubop"):
                MODEL["mode"] = mode
                raises(f"{mode} → CandidateBusy", lambda: typ.apply(cands()[0], typ.validate({}), "t"),
                       CandidateBusy)
                check(f"{mode}: no model failure", base_body.base_model_info("Kira")["status"], "ready")
                check(f"{mode}: still a candidate (model)",
                      [(c.key, c.label) for c in cands()], [(key, "Kira · base body · model built from older views")])
            MODEL["mode"] = "ok"
            check("built twice, nothing rendered", (RENDERS, BUILDS), ([], [(True, bsig, True)] * 2))

            # --- [B5] ---------------------------------------------------------------
            print("[B5] the cost")
            old_base()
            write_model()
            check("(a) face option on", model3d.set_model3d_options("Kira", {"face_before_rig": True})
                  .get("face_before_rig"), True)
            check("(a) planned", model3d.face_before_rig_planned("Kira"), True)
            check("(d) not on a generic rig", model3d.face_before_rig_planned("Kira", "generic"), False)
            with patch.object(face_retexture, "runnable", lambda *a, **k: {"ok": True, "problems": []}):
                check("(a) reference front (no face view) → upscale",
                      [(c.hub_jobs, c.note) for c in cands()],
                      [(8, "older prompts: views 4 + mesh + upscale + face + rig = 8 hub jobs (first attempts; "
                           "the hand gate may render the front up to 2 more times; "
                           "the dark-face gate may retry the face once)")])
                # The stages are memoised under the figure generation and the face view's file
                # (model3d.mesh_hub_stages): a patched reference needs a fresh generation.
                from app.core import figure as figure_mod
                figure_mod.invalidate()
                with patch.object(face_retexture, "reference_info", lambda *a, **k: {"reference": "face"}):
                    check("(b) reference face → no upscale", [c.hub_jobs for c in cands()], [7])
            # The face route's probe is memoised under the figure generation (model3d._face_route_ok): a route
            # going away shows after the next write or ``figure.MEMO_TTL_S`` — here at once.
            figure_mod.invalidate()
            with patch.object(face_retexture, "runnable", lambda *a, **k: {"ok": False, "problems": [{}]}):
                check("(c) no face route → skipped", [c.hub_jobs for c in cands()], [6])
            model3d.set_model3d_options("Kira", {"face_before_rig": False})

            reset_calls()
            for v in base_body.BASE_VIEWS:
                write_view(v, "000000000000" if v == "back" else fp, "2026-11-02T10:00:00+00:00",
                           (5, 6, base_body.BASE_VIEWS.index(v)))
            write_model()
            check("(e) only the back old", summary(),
                  [(key, "Kira · base body · views not refreshed yet", 3,
                    "views not refreshed yet: views 1 + mesh + rig = 3 hub jobs (first attempts)")])
            check("(e) apply", typ.apply(cands()[0], typ.validate({}), "t"), None)
            check("(e) the back alone, then the model", (RENDERS, BUILDS),
                  ([("back", "base_view", fp)], [(True, bsig, True)]))
            check("(e) done", cands(), [])

            reset_calls()
            write_model(front_sha="0" * 64)
            check("(f) the model alone", summary(),
                  [(key, "Kira · base body · model built from older views", 2,
                    "model built from older views: mesh + rig = 2 hub jobs (first attempts)")])
            typ.apply(cands()[0], typ.validate({}), "t")
            check("(f) nothing rendered, one build", (RENDERS, BUILDS), ([], [(True, bsig, True)]))
            check("(f) done", cands(), [])

            old_base()
            write_model()
            for label, face, runnable in (("face off", False, True), ("face on", True, True),
                                          ("no route", True, False)):
                model3d.set_model3d_options("Kira", {"face_before_rig": face})
                with patch.object(face_retexture, "runnable",
                                  lambda *a, _ok=runnable, **k: {"ok": _ok, "problems": []}):
                    cost = base_body.base_rebuild_cost("Kira")
                    check(f"(g) {label}: hub_jobs = sum of the steps",
                          cost["hub_jobs"], sum(jobs for _s, jobs in cost["steps"]))
            model3d.set_model3d_options("Kira", {"face_before_rig": False})

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


def Candidate_(key):
    from app.core.improvements.base import Candidate
    return Candidate(key, "")


if __name__ == "__main__":
    sys.exit(main())
