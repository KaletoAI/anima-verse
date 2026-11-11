#!/usr/bin/env python3
"""The ``hair_fill`` improvement type (app/core/improvements/types/hair_fill.py;
spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.5):
the hair mesh of characters on the pipeline that have hair text but none.

Usage:
    ./.venv/bin/python scripts/smoke_improvement_hair_fill.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. The
fixture follows scripts/smoke_hair_item.py: ``Kira`` (human-roleplay, on the
pipeline, hair slot {length medium, color blonde} → hair text "medium blonde
hair") and ``Bald`` (on the pipeline, no hair slot, no hair word in the
appearance → no hair text), both with a ready base (``model3d/<bsig>.glb`` +
sidecar rig mixamo, as smoke_improvement_garment_fill). The chain is a
recorder: ``garments.run_garment`` records ``(name, item_id)`` and answers
what the case scripts; on success it writes an ACCEPTED fit the way
``_fit_state`` reads it (fit + prepared file, record {accepted, kind hair,
fit_version FIT_VERSION["hair"], base_model_sha256 = the current base,
inputs.prepared_sha256 = the prepared file's sha256}).
``routing.explain_occasion`` resolves every occasion to "Fake" unless a case
empties one.

Expectations, derived by hand from § 6.5 and ``garments.HUB_JOBS``:

[H1] Kira has hair text and no hair item → exactly one candidate
     ``character:Kira`` (Bald is no subject: [H6]). World method edit_chain
     (the default): label "Kira · hair views", hub_jobs 2 + 2 + 0 + 1 + 0 = 5,
     note "new hair item: haired 2 + ghost 2 + mesh 1". World
     ``base_body.hair_method`` "hairdeck" → label "Kira · HairDeck", hub 1;
     "subtract" → hub 2 + 1 + 0 + 0 = 3. Back to edit_chain.
[H2] through the engine (``handle_step``) → {"ok": True}:
     ``ensure_hair_item`` created and wore the item (``find_hair_item`` not
     None, ``worn_hair_id`` = its id), run_garment called once with that
     item; ``hair_summary`` "ready"; rescan → no candidate; the one-shot
     worked itself off.
[H3] the fit deleted → hair_summary "missing" → the candidate is back with
     ``run_estimate``'s cost (nothing cached: 5, note "haired 2 + ghost 2 +
     mesh 1"); a persisted failure of the item's fsig (step "mesh",
     ``garment_store.record_failure``) → ``cached_failure`` → no candidate;
     cleared → back.
[H4] run_garment answers ``{ok False, step "haired", error "busy",
     retry_later True}`` → apply raises CandidateBusy. ``hair_views_mesh``
     resolving to nothing → CandidateBusy before any run (run_garment not
     called).
[H5] run_garment answers ``{ok False, step "hairdeck", error
     NO_HAIR_ERROR}`` → through the engine: "refused", the step skipped +
     refused, attempts 1, one run.
[H6] Bald (no hair text) → never a candidate (``character=Bald`` lists
     nothing).
[H7] Kira takes the hair item off (``unequip_mesh_piece``) → hair_summary
     None, but ``find_hair_item`` still finds the owned item → no candidate.

Fails on 505c3076: ModuleNotFoundError — app.core.improvements.types.hair_fill.
"""
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="improvement-hair-fill-") as tmp:
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

        from app.core import base_body, garment_assembly, garment_fit, garment_hair, garments, glb_delivery, model_refs
        from app.core import garment_store as gs
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import CandidateBusy
        from app.core.improvements.types.hair_fill import HairFill
        from app.core.task_queue import get_task_queue
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        get_task_queue()._started = True          # no worker threads: rows only
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda *a, **k: True
        glb_delivery.delivery_path = lambda path, **kw: path
        registry.clear()
        typ = HairFill()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, green eyes",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        bald = json.loads(json.dumps(human))
        bald["body_slots"].pop("hair")
        for name, profile in (("Kira", human), ("Bald", bald)):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(profile)), create_new=True),
                  True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
            bsig = base_body.base_signature(name)
            mdir = get_character_dir(name) / "model3d"
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / f"{bsig}.glb").write_bytes(f"glb-{name}".encode())
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            check(f"{name} base ready", (base_body.base_model_info(name) or {}).get("status"), "ready")
        check("Kira hair text", garment_hair.hair_description("Kira"), "medium blonde hair")
        check("Bald no hair text", garment_hair.hair_description("Bald"), "")

        RUNS = []
        ANSWER = {"result": None}

        def fit_paths(name, item_id):
            fsig = gs.garment_fsig(name, item_id)
            return gs.garment_path(name, item_id, fsig, "fit"), gs.garment_path(name, item_id, fsig, "prepared")

        def run_garment(name, item_id, **kw):
            RUNS.append((name, item_id))
            if ANSWER["result"] is not None:
                return dict(ANSWER["result"])
            fit, prepared = fit_paths(name, item_id)
            fit.parent.mkdir(parents=True, exist_ok=True)
            prepared.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(b"fit")
            prepared.write_bytes(b"prepared")
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": "hair", "item_id": item_id, "fit_version": garment_fit.FIT_VERSION["hair"],
                "base_model_sha256": base_body.current_base(name)[1],
                "inputs": {"prepared_sha256": base_body.file_sha256(prepared)}})
            return {"ok": True, "ran": ["fit"]}

        RESOLVE = {}

        def explain(occasion, character="", pool=None, **kw):
            return {"resolved": RESOLVE.get(occasion, "Fake")}

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def rows(**params):
            return [(c.key, c.label, c.hub_jobs, c.note) for c in cands(**params)]

        def run_step(entry, key):
            store.mark_running(entry, key)
            return engine.handle_step({"improvement_id": entry, "candidate_key": key, "_task_id": "t"})

        def world_method(method):
            config._CONFIG.setdefault("base_body", {})["hair_method"] = method

        with patch.object(garments, "run_garment", run_garment), \
             patch("app.imagegen.routing.explain_occasion", explain):

            # --- [H1] ---------------------------------------------------------------
            print("[H1] hair text, no item")
            check("edit chain", rows(),
                  [("character:Kira", "Kira · hair views", 5, "new hair item: haired 2 + ghost 2 + mesh 1")])
            world_method("hairdeck")
            check("hairdeck", [(c.label, c.hub_jobs) for c in cands()], [("Kira · HairDeck", 1)])
            world_method("subtract")
            check("subtract", [c.hub_jobs for c in cands()], [3])
            world_method("edit_chain")
            check("needs_media", typ.needs_media, True)

            # --- [H2] ---------------------------------------------------------------
            print("[H2] apply creates the item and runs the chain")
            entry = store.create(typ.id, "Hair", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            check("handle_step ok", run_step(entry, "character:Kira"), {"ok": True})
            item = garment_hair.find_hair_item("Kira", get_character_profile("Kira"))
            check("the item exists", item is not None, True)
            item_id = (item or {}).get("id")
            check("and is worn", garment_hair.worn_hair_id("Kira"), item_id)
            check("one run with that item", RUNS, [("Kira", item_id)])
            check("hair_summary ready", (garments.hair_summary("Kira") or {}).get("status"), "ready")
            check("rescan: no candidate", cands(), [])
            check("the one-shot worked itself off", store.get(entry), None)

            # --- [H3] ---------------------------------------------------------------
            print("[H3] a persisted failure is no candidate")
            fit, _prepared = fit_paths("Kira", item_id)
            fit.unlink()
            check("hair_summary missing", (garments.hair_summary("Kira") or {}).get("status"), "missing")
            check("candidate back with run_estimate's cost", rows(),
                  [("character:Kira", "Kira · hair views", 5, "haired 2 + ghost 2 + mesh 1")])
            fsig = gs.garment_fsig("Kira", item_id)
            gs.record_failure("Kira", item_id, fsig, step="mesh", error="refused",
                              base_model_sha=base_body.current_base("Kira")[1])
            check("cached_failure", (garments.cached_failure("Kira", item_id) or {}).get("step"), "mesh")
            check("no candidate", cands(), [])
            gs.clear_failure("Kira", item_id, fsig)
            check("cleared: back", [c.key for c in cands()], ["character:Kira"])

            # --- [H4] ---------------------------------------------------------------
            print("[H4] load is busy")
            RUNS.clear()
            ANSWER["result"] = {"ok": False, "step": "haired", "error": "busy", "retry_later": True}
            raises("retry_later → CandidateBusy", lambda: typ.apply(cands()[0], typ.validate({}), "t"), CandidateBusy)
            check("one run", len(RUNS), 1)
            RESOLVE["hair_views_mesh"] = ""
            raises("hair_views_mesh unresolved → CandidateBusy",
                   lambda: typ.apply(cands()[0], typ.validate({}), "t"), CandidateBusy)
            check("no further run", len(RUNS), 1)
            RESOLVE.clear()

            # --- [H5] ---------------------------------------------------------------
            print("[H5] HairDeck finds no hair: terminal")
            RUNS.clear()
            ANSWER["result"] = {"ok": False, "step": "hairdeck", "error": garments.NO_HAIR_ERROR}
            entry = store.create(typ.id, "Hair", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            result = run_step(entry, "character:Kira")
            check("engine reports the refusal", list(result.keys()), ["refused"])
            step = store.list_steps(entry)[0]
            check("step skipped + refused after one attempt",
                  (step["status"], step["refused"], step["attempts"]), ("skipped", 1, 1))
            check("the error names hairdeck", str(step["error"]).startswith("hairdeck — "), True)
            check("one run", len(RUNS), 1)
            ANSWER["result"] = None

            # --- [H6] ---------------------------------------------------------------
            print("[H6] bald")
            check("Bald lists nothing", cands(character="Bald"), [])

            # --- [H7] ---------------------------------------------------------------
            print("[H7] the item taken off")
            check("unequip", inventory.unequip_mesh_piece("Kira", garment_hair.HAIR_KIND), True)
            check("hair_summary None", garments.hair_summary("Kira"), None)
            check("the owned item is still found",
                  (garment_hair.find_hair_item("Kira", get_character_profile("Kira")) or {}).get("id"), item_id)
            check("no candidate", cands(), [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
