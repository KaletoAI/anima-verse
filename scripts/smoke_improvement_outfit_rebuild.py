#!/usr/bin/env python3
"""The ``outfit_rebuild`` improvement type (app/core/improvements/types/outfit_rebuild.py;
spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.4):
stale outfit models rebuilt on the current base, the cost shown before start.

Usage:
    ./.venv/bin/python scripts/smoke_improvement_outfit_rebuild.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. The
fixture is a slim cut of scripts/smoke_base_body_outfit.py (as
scripts/smoke_outfit_rebuild_cost.py): Kira on the pipeline with a ready base
and the four base views, wearing a plain Dress (slot top) → worn signature
``sig``; she also holds a Scarf (slot neck). Both are ``mesh_mode: painted`` (painted on the plain body;
since 9788164d the default mode is ``in_body``, which would mesh a shape). The producers are recorders:

* ``model_refs.trigger_now`` records ``(kinds, blocking, force, signature)``
  and writes the outfit's dressed front + back CURRENT for the base
  (``base_signature`` bsig, ``base_image_sha256`` of the base view);
* ``model_refs.generate_model_ref_images`` (the non-worn path) records
  ``(kinds, force, pieces, signature)`` and writes the same views;
* ``model3d.generate_for_current_outfit`` records ``(force, signature)`` and
  writes the model's sidecar naming the CURRENT base (``base_signature`` bsig,
  ``base_model_sha256``) and the figure delivered now (``figure``, as a real
  build records it since Task 6 of plan 2026-11-12-unified-worn-pieces) →
  ``{"ok": True}``; in [B5] it answers
  ``{"ok": False, "error": "worker"}`` without writing.
* ``routing.explain_occasion`` resolves every occasion to "Fake" unless a
  case empties one.

"Stale model" = ``model3d/<sig>.glb`` whose sidecar names ``base00000000``
(an older base); every hand-written model records the figure its pieces are
delivered as now (Task 6: a model without one is stale "figure" — the boot
stamp of smoke_figure_stamp.py gives the pre-Task-6 ones theirs). Expectations derived by hand from § 6.4 and rebuild_cost's
table (front 1 + 2 per other dressed view; retexture repaint = CPU):

[B1] the worn model stale, no dressed view → one candidate
     ``outfit:Kira:<sig>``, label "Kira · Dress · older base" (the outfit's
     piece name, no saved set matches; the reason text of "older_base"),
     hub_jobs 3, note "older base: views 3 (first attempts)".
[B2] through the engine (``handle_step``) → {"ok": True}; the calls in order
     trigger_now(("tpose",), blocking True, force False, signature sig), then
     generate_for_current_outfit(force True, signature sig); rescan → no
     candidate; the one-shot worked itself off.
[B3] the model stale again, ``base_body._outfit_failed[("Kira", sig)]`` set →
     outfit_info "failed" → no candidate; cleared → the candidate is back.
[B4] ``model3d._generating`` holds Kira → apply raises CandidateBusy, no
     producer called; the occasion ``outfit_back`` resolving to nothing with
     views needed → CandidateBusy too, no producer called.
[B5] views current (B2's recorder wrote them), the model stale, the build
     recorder answers ok False "worker" → through the engine: "refused", the
     step skipped + refused, attempts 1; trigger_now NOT called (views
     current: retexture cost 0, nothing to render), the build once.
[B6] ``model_ref_auto.tpose`` off + views needed (views dropped) → no
     candidate; views current + the model on the current base with
     ``variant_current`` patched False (detail_changed) → candidate, hub_jobs
     0, label ends "other body detail".
[B7] a saved set "Evening" = [Scarf] (signature sig2 =
     ``outfit_batch._signature({"neck": scarf})``) with a stale model, and a
     set "Day" = [Dress, Scarf] without a model; the worn model current:
     scope worn → nothing; scope saved → exactly ``outfit:Kira:<sig2>``,
     label "Kira · Evening · older base", hub 3; "Day" never. Its apply
     renders through generate_model_ref_images (pieces {"neck": scarf}, the
     model's manifest, force False, signature sig2) — trigger_now not called —
     then the build for sig2.
[B8] views needed, the render recorder writes nothing (a refused or failed
     edit) → apply raises CandidateRefused "views front, back — …" after the
     one trigger_now; the build is never called (it would render the views
     again in mesh mode, or repaint from a partial set).

[B9] (ruling 9a) load during the dressed views is busy, never a failure. The
     REAL render path: ``model_refs.trigger_now`` (blocking) →
     ``generate_model_ref_images`` → ``base_body.generate_dressed_images`` →
     ``expression_regen.render_character_image`` → the service's string
     facade ``generate_from_input`` (a real ``ImageService`` with no
     instances, switched on by hand) → the routing, where a fake backend
     records the occasion and raises ``BackendBusyError``. Views needed, the
     model stale (cost 3), only the build recorder stays.
     [B9a] through the engine → {"busy": …}, NOT "refused"; the step
     pending, attempts 0, refused 0; ONE routed render, occasion
     "outfit_front" (the front is the first view; the pass stops there); the
     build never called; ``base_body._outfit_failed`` holds nothing for
     (Kira, sig), outfit_info still "stale" (the candidate stays listed),
     the images stage no longer running.
     [B9b] the media switch off at the facade (``media_generation_enabled``
     False) → apply raises CandidateBusy, no render reached the routing,
     nothing recorded as a failure.
     [B9c] the saved set "Evening" (sig2, B7) stale with its views dropped,
     scope saved → the non-worn path (``generate_model_ref_images``) →
     CandidateBusy, one routed render "outfit_front", no failure recorded.
     [B9d] the worn front current, only the back missing (cost still 3:
     ``rebuild_cost`` counts the whole view set, an upper bound) → the back's
     draft (``_dress_view`` → ``render_draft``) meets the
     busy backend → CandidateBusy, one routed render "outfit_back_draft", no
     failure recorded, the build never called.

Fails on 505c3076: ModuleNotFoundError — app.core.improvements.types.outfit_rebuild.
Fails on f4c5dc6d (before fix 9a): [B9a] the facade answers the busy backend
with an "Error: …" string, the front edit becomes "Dressed front edit
failed", ``_outfit_failed`` records it and the engine reports "refused".
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


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


def png(rgb) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (8, 8), rgb).save(out, "PNG")
    return out.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="improvement-outfit-rebuild-") as tmp:
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

        from app.core import base_body, figure, glb_delivery, model3d, model_refs, outfit_batch
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import CandidateBusy, CandidateRefused
        from app.core.improvements.types.outfit_rebuild import OutfitRebuild
        from app.core.task_queue import get_task_queue
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_outfits, save_character_profile

        get_task_queue()._started = True          # no worker threads: rows only
        model_refs.schedule_outfit_render = lambda *a, **k: None
        glb_delivery.delivery_path = lambda path, **kw: path
        registry.clear()
        typ = OutfitRebuild()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create Kira", save_character_profile("Kira", dict(human), create_new=True), True)
        check("pipeline Kira", base_body.set_pipeline("Kira", True), True)
        bsig = base_body.base_signature("Kira")
        cdir = get_character_dir("Kira")
        mdir, refs = cdir / "model3d", cdir / "model_refs"
        mdir.mkdir(parents=True, exist_ok=True)
        refs.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        check("base ready", (base_body.base_model_info("Kira") or {}).get("status"), "ready")
        base_sha = base_body.base_model_sha256("Kira", bsig)
        shas = {}
        for i, v in enumerate(base_body.BASE_VIEWS):
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png((10 * i, 20, 30)))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            shas[v] = hashlib.sha256((refs / f"{stem}.png").read_bytes()).hexdigest()

        # Painted on the plain body (since 9788164d the default mode is in_body — that would mesh a shape).
        piece = {"covers": [], "outfit_types": ["casual"], "mesh_mode": "painted"}
        dress = inventory.add_item(name="Dress", category="outfit_piece", prompt_fragment="a green dress",
                                   outfit_piece={"slots": ["top"], **piece})["id"]
        scarf = inventory.add_item(name="Scarf", category="outfit_piece", prompt_fragment="a red scarf",
                                   outfit_piece={"slots": ["neck"], **piece})["id"]
        for item in (dress, scarf):
            check(f"Kira holds {item}", inventory.add_to_inventory("Kira", item), True)
        check("Kira wears the dress", inventory.equip_piece("Kira", dress, source="smoke")["status"], "ok")
        pieces, items, sig = model_refs.current_outfit_state("Kira")

        def write_model(s, model_pieces, **extra):
            (mdir / f"{s}.glb").write_bytes(b"outfit-model")
            (mdir / f"{s}.json").write_text(json.dumps({
                "character": "Kira", "signature": s, "pieces": dict(model_pieces), "items": [],
                "dressed": True, "base_signature": "base00000000", "base_model_sha256": "old",
                "figure": figure.delivered_figure("Kira", pieces=dict(model_pieces), items=[]).as_dict(),
                **extra}))

        def write_views(s, view_pieces):
            for v in ("front", "back"):
                stem = f"tpose_{s}" if v == "front" else f"tpose_{v}_{s}"
                (refs / f"{stem}.png").write_bytes(png((99, 1 if v == "front" else 2, 3)))
                (refs / f"{stem}.json").write_text(json.dumps({
                    "base_signature": bsig, "base_image_sha256": shas[v], "dressed": True,
                    "equipped_pieces": dict(view_pieces), "equipped_items": [], "mesh_variant": ""}))

        def drop_views(s):
            for p in refs.glob(f"tpose*_{s}.*"):
                p.unlink()

        CALLS = []
        BUILD = {"fail": False}
        RENDER = {"write": True}

        def trigger_now(name, kinds=None, *, force=True, blocking=False, pieces=None, items=None,
                        signature=None, **kw):
            CALLS.append(("trigger_now", tuple(kinds or ()), blocking, force, signature))
            if RENDER["write"]:
                write_views(signature, pieces or {})

        def ref_images(name, kinds=None, force=False, *, pieces=None, items=None, signature=None, **kw):
            CALLS.append(("generate_model_ref_images", tuple(kinds or ()), force, dict(pieces or {}), signature))
            write_views(signature, pieces or {})
            return {}

        def build(name, *, force=False, signature=None, **kw):
            CALLS.append(("generate_for_current_outfit", force, signature))
            if BUILD["fail"]:
                return {"ok": False, "error": "worker"}
            meta = json.loads((mdir / f"{signature}.json").read_text())
            meta.update(base_signature=bsig, base_model_sha256=base_sha,
                        figure=figure.delivered_figure("Kira", pieces=dict(meta.get("pieces") or {}),
                                                       items=list(meta.get("items") or [])).as_dict())
            (mdir / f"{signature}.json").write_text(json.dumps(meta))
            return {"ok": True}

        RESOLVE = {}

        def explain(occasion, character="", pool=None, **kw):
            return {"resolved": RESOLVE.get(occasion, "Fake")}

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def run_step(entry, key):
            store.mark_running(entry, key)
            return engine.handle_step({"improvement_id": entry, "candidate_key": key, "_task_id": "t"})

        key = f"outfit:Kira:{sig}"
        with patch.object(model_refs, "trigger_now", trigger_now), \
             patch.object(model_refs, "generate_model_ref_images", ref_images), \
             patch.object(model3d, "generate_for_current_outfit", build), \
             patch("app.imagegen.routing.explain_occasion", explain):

            # --- [B1] ---------------------------------------------------------------
            print("[B1] a worn model on an older base")
            write_model(sig, pieces)
            found = cands()
            check("one candidate", [(c.key, c.label, c.hub_jobs, c.note) for c in found],
                  [(key, "Kira · Dress · older base", 3, "older base: views 3 (first attempts)")])
            check("needs_media", typ.needs_media, True)

            # --- [B2] ---------------------------------------------------------------
            print("[B2] apply renders the views, then builds")
            entry = store.create(typ.id, "Rebuild", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            check("the step carries the cost", (store.list_steps(entry)[0]["hub_jobs"],
                                                store.list_steps(entry)[0]["note"]),
                  (3, "older base: views 3 (first attempts)"))
            check("handle_step ok", run_step(entry, key), {"ok": True})
            check("calls in order", CALLS, [("trigger_now", ("tpose",), True, False, sig),
                                            ("generate_for_current_outfit", True, sig)])
            check("the guard released", "Kira" in model3d._generating, False)
            check("outfit ready", base_body.outfit_info("Kira", signature=sig)["status"], "ready")
            check("rescan: no candidate", cands(), [])
            check("the one-shot worked itself off", store.get(entry), None)

            # --- [B3] ---------------------------------------------------------------
            print("[B3] a failed last build is not a candidate")
            write_model(sig, pieces)
            with base_body._status_lock:
                base_body._outfit_failed[("Kira", sig)] = {"error": "worker"}
            check("outfit_info failed", base_body.outfit_info("Kira", signature=sig)["status"], "failed")
            check("no candidate", cands(), [])
            with base_body._status_lock:
                base_body._outfit_failed.pop(("Kira", sig), None)
            check("cleared: the candidate is back", [c.key for c in cands()], [key])

            # --- [B4] ---------------------------------------------------------------
            print("[B4] the model guard held / no route is load")
            CALLS.clear()
            cand = cands()[0]
            with model3d._lock:
                model3d._generating.add("Kira")
            try:
                raises("guard held → CandidateBusy", lambda: typ.apply(cand, typ.validate({}), "t"), CandidateBusy)
            finally:
                with model3d._lock:
                    model3d._generating.discard("Kira")
            drop_views(sig)
            RESOLVE["outfit_back"] = ""
            raises("outfit_back unresolved → CandidateBusy", lambda: typ.apply(cands()[0], typ.validate({}), "t"),
                   CandidateBusy)
            RESOLVE.clear()
            check("no producer called", CALLS, [])

            # --- [B5] ---------------------------------------------------------------
            print("[B5] a refused build is terminal")
            write_views(sig, pieces)
            write_model(sig, pieces)
            check("views current: cost 0", [c.hub_jobs for c in cands()], [0])
            BUILD["fail"] = True
            entry = store.create(typ.id, "Rebuild", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            result = run_step(entry, key)
            check("engine reports the refusal", list(result.keys()), ["refused"])
            step = store.list_steps(entry)[0]
            check("step skipped + refused after one attempt",
                  (step["status"], step["refused"], step["attempts"]), ("skipped", 1, 1))
            check("the build once, no render", CALLS, [("generate_for_current_outfit", True, sig)])
            check("retry refused", store.retry_step(entry, key), False)
            BUILD["fail"] = False
            CALLS.clear()

            # --- [B6] ---------------------------------------------------------------
            print("[B6] the T-pose auto toggle")
            model_refs.set_auto_kinds("Kira", {"tpose": False})
            drop_views(sig)
            check("views needed + toggle off: no candidate", cands(), [])
            write_views(sig, pieces)
            write_model(sig, pieces, base_signature=bsig, base_model_sha256=base_sha)
            with patch.object(base_body, "variant_current", return_value=False):
                found = cands()
            check("views current (detail_changed): candidate at 0",
                  [(c.key, c.hub_jobs, c.label.endswith("other body detail")) for c in found], [(key, 0, True)])
            model_refs.set_auto_kinds("Kira", {"tpose": True})

            # --- [B7] ---------------------------------------------------------------
            print("[B7] saved outfit sets")
            sig2 = outfit_batch._signature({"neck": scarf}, "Kira")
            sig3 = outfit_batch._signature({"top": dress, "neck": scarf}, "Kira")
            save_character_outfits("Kira", [
                {"id": "ev", "name": "Evening", "pieces": [scarf], "locations": [], "activities": [],
                 "excluded_locations": [], "image": "", "options": {}},
                {"id": "dy", "name": "Day", "pieces": [dress, scarf], "locations": [], "activities": [],
                 "excluded_locations": [], "image": "", "options": {}}])
            from app.core.improvements.types import subjects
            check("saved_outfit_signatures", subjects.saved_outfit_signatures("Kira"),
                  [(sig2, "Evening"), (sig3, "Day")])
            write_model(sig2, {"neck": scarf})
            check("worn scope: nothing (the worn model is current)", cands(), [])
            found = cands(scope="saved")
            check("saved scope: Evening only", [(c.key, c.label, c.hub_jobs) for c in found],
                  [(f"outfit:Kira:{sig2}", "Kira · Evening · older base", 3)])
            typ.apply(found[0], typ.validate({"scope": "saved"}), "t")
            check("non-worn: rendered the batch way, then built", CALLS,
                  [("generate_model_ref_images", ("tpose",), False, {"neck": scarf}, sig2),
                   ("generate_for_current_outfit", True, sig2)])
            check("rescan saved: nothing", cands(scope="saved"), [])

            # --- [B8] ---------------------------------------------------------------
            print("[B8] views that do not land stop before the build")
            CALLS.clear()
            drop_views(sig)
            write_model(sig, pieces)
            RENDER["write"] = False
            e = raises("CandidateRefused", lambda: typ.apply(cands()[0], typ.validate({}), "t"), CandidateRefused)
            check("the error names the views", str(e).startswith("views front, back — "), True)
            check("render once, no build", CALLS, [("trigger_now", ("tpose",), True, False, sig)])
            RENDER["write"] = True

        # --- [B9] -------------------------------------------------------------------
        print("[B9] load during the dressed views is busy, never a failure (ruling 9a)")
        from app.imagegen import service
        from app.imagegen.base import BackendBusyError
        svc = service.ImageService({})
        svc.enabled = True          # no instances configured: the routing below stands in for the backend
        routed = []

        def busy_backend(occasion, render, **kw):
            routed.append(occasion)
            raise BackendBusyError("gpu busy")

        def failure(s):
            with base_body._status_lock:
                return (base_body._outfit_failed.get(("Kira", s)),
                        base_body._outfit_running.get(("Kira", "images")))

        CALLS.clear()
        drop_views(sig)
        write_model(sig, pieces)
        with patch.object(model3d, "generate_for_current_outfit", build), \
             patch("app.imagegen.routing.explain_occasion", explain), \
             patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", busy_backend):
            check("views needed: cost 3", [(c.key, c.hub_jobs) for c in cands()], [(key, 3)])
            print("[B9a] a busy backend through the engine")
            entry = store.create(typ.id, "Rebuild", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            result = run_step(entry, key)
            check("busy, not refused", list(result.keys()), ["busy"])
            step = store.list_steps(entry)[0]
            check("step pending, no attempt, not refused",
                  (step["status"], step["attempts"], step["refused"]), ("pending", 0, 0))
            check("one routed render, the dressed front", routed, ["outfit_front"])
            check("the build never called", CALLS, [])
            check("no failure recorded, the stage ended", failure(sig), (None, None))
            check("still a candidate", [c.key for c in cands()], [key])
            store.delete(entry)

            print("[B9b] the media switch off")
            del routed[:]
            with patch("app.imagegen.service.media_generation_enabled", lambda: False):
                raises("media off → CandidateBusy", lambda: typ.apply(cands()[0], typ.validate({}), "t"),
                       CandidateBusy)
            check("no render reached the routing", routed, [])
            check("no failure recorded", failure(sig), (None, None))

            print("[B9c] a saved set (the non-worn path)")
            del routed[:]
            write_views(sig, pieces)
            write_model(sig, pieces, base_signature=bsig, base_model_sha256=base_sha)
            drop_views(sig2)
            write_model(sig2, {"neck": scarf})
            found = cands(scope="saved")
            check("saved scope: Evening, views needed", [(c.key, c.hub_jobs) for c in found],
                  [(f"outfit:Kira:{sig2}", 3)])
            raises("busy → CandidateBusy", lambda: typ.apply(found[0], typ.validate({"scope": "saved"}), "t"),
                   CandidateBusy)
            check("one routed render, the dressed front", routed, ["outfit_front"])
            check("no failure recorded", failure(sig2), (None, None))
            check("the build never called", CALLS, [])

            print("[B9d] the back's draft meets the busy backend")
            del routed[:]
            for p in refs.glob(f"tpose_back_{sig}.*"):
                p.unlink()
            write_model(sig, pieces)
            found = cands()
            check("worn: only the back missing, cost 3 (whole set)", [(c.key, c.hub_jobs) for c in found], [(key, 3)])
            raises("busy → CandidateBusy", lambda: typ.apply(found[0], typ.validate({}), "t"), CandidateBusy)
            check("one routed render, the back's draft", routed, ["outfit_back_draft"])
            check("no failure recorded", failure(sig), (None, None))
            check("the build never called", CALLS, [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
