#!/usr/bin/env python3
"""The ``garment_fill`` improvement type (app/core/improvements/types/garment_fill.py;
spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.1):
missing own-mesh garment meshes, one shoe chain per item, clothing per wearer.

Usage:
    ./.venv/bin/python scripts/smoke_improvement_garment_fill.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no server. The footwear chain
is REAL up to the fit: the stubs and counters ``(upscale, edit, mesh)`` of
scripts/smoke_footwear_chain.py (fake edit backend, fake service, fake rembg,
fake decimation, the wedge mesh), the routing answering a table
(``routing.explain_occasion`` patched), and ``garment_footwear.fit`` a
recorder that writes an honest fit record (the real ``_source_parents``, the
current fit version, the base sha) — the rigid-foot geometry is
smoke_footwear_fit's business. Kira and Mira are on the pipeline with a ready
base (``model3d/<bsig>.glb`` + sidecar rig mixamo). Clothing [G7] patches
``garments.run_garment`` with a recorder that writes an accepted fit.

Derived by hand from the candidate rule and the chain:

[G1] Both wear the heels, no source yet → exactly one candidate
     ``footwear:<heels>`` (one chain per item), label "Heels · 2 wearers",
     hub_jobs 3 (the fixture image is 232 px, below MIN_SIDE 1024: source 1
     + empty 1 + mesh 1), the note names "Kira, Mira".
[G2] apply → counters (1, 1, 1): Kira's run spends the chain, Mira's finds
     the item steps done and fits (0 jobs); ``fit_state`` accepted for BOTH;
     rescan → no candidate; the engine step is done.
[G3] A fresh item (pumps), the mesher fails outright → apply raises
     ``CandidateRefused`` starting "mesh — "; the counters moved by exactly
     (1, 1, 1); ``refused_step(pumps)`` names mesh; through the engine
     (``handle_step``) the step is skipped, refused 1, attempts 1; rescan →
     no candidate, the step still skipped; the mesher counter did not move
     after the first refusal (no second attempt, no re-spend).
[G4] A fresh item (boots), the mesher raises ``BackendBusyError`` → apply
     raises ``CandidateBusy``; ``refused_step`` None (load does not count);
     the candidate is listed again on rescan.
[G5] ``mesh_footwear`` absent from the routing table → ``CandidateBusy("no
     backend available for mesh_footwear right now")`` BEFORE any hub call:
     counters unchanged.
[G6] A fourth item (clogs): Kira wears it, Mira only holds it (inventory):
     scope worn → label "Clogs · 1 wearer", note starts "Kira"; scope held →
     "Clogs · 2 wearers".
[G7] Clothing: a dress worn by Kira with an accepted fit on the current base
     → not a candidate; no fit + a persisted failure at ``ghost`` → not a
     candidate; nothing → candidate ``clothing:Kira:<dress>`` with hub_jobs
     6 and note "worn 3 + ghost 2 + mesh 1"; apply calls ``run_garment``
     (the recorder, once) → rescan → gone. A character off the pipeline is
     never a subject (Nora, a plain profile, lists nothing even wearing the
     dress).

Fails on 193321cf: ModuleNotFoundError — app.core.improvements.types.garment_fill.
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
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_footwear_chain import (EditBackend, Service, fake_decimate, fake_rembg, flat_x4,  # noqa: E402
                                  png, shoe, silhouette_crop, wedge_glb)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, text=""):
    try:
        fn()
    except exc as e:
        ok = text in str(e)
        print(("  OK   " if ok else "  FAIL ") + f"{label}: {exc.__name__}({str(e)[:120]!r})"
              + ("" if ok else f" — expected {text!r} in the message"))
        if not ok:
            FAILS.append(label)
        return e
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILS.append(label)
    else:
        print(f"  FAIL {label}: no exception")
        FAILS.append(label)
    return None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="improvement-garment-fill-") as tmp:
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

        from app.core import base_body, footwear_source, garment_assembly, garment_fit, garment_footwear, garments
        from app.core import garment_store as gs
        from app.core import glb_delivery, model_refs
        from app.core.base_body import file_sha256
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import CandidateBusy, CandidateRefused
        from app.core.improvements.types import subjects
        from app.core.improvements.types.garment_fill import GarmentFill
        from app.core.task_queue import get_task_queue
        from app.imagegen.base import BackendBusyError
        from app.imagegen.routing import Route
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        get_task_queue()._started = True
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda *a, **k: True
        base_body.after_mesh_item_ready = lambda *a, **k: None   # the outfit rebuild is not under test
        glb_delivery.delivery_path = lambda path, **kw: path   # no delivery copies of the dummy base
        registry.clear()
        typ = GarmentFill()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        for name in ("Kira", "Mira", "Nora"):
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
        for name in ("Kira", "Mira"):
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
            bsig = base_body.base_signature(name)
            mdir = get_character_dir(name) / "model3d"
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / f"{bsig}.glb").write_bytes(b"glb-" + name.encode())
            (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                           "format": "glb", "source": "generated"}))
            check(f"{name} base ready", (base_body.base_model_info(name) or {}).get("status"), "ready")
        check("pipeline roster", subjects.pipeline_characters(), ["Kira", "Mira"])

        crop = silhouette_crop()
        edit = EditBackend(png(flat_x4(shoe(crop, False))))
        svc = Service(edit, wedge_glb())

        def shoe_item(name):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"black {name.lower()}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"],
                                                   "mesh_mode": "own_mesh"})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            shoe(crop, True).save(folder / "image.png", format="PNG")
            check(f"{name} image set", inventory.set_item_image(iid, "image.png"), True)
            return iid

        def wear(name, iid):
            check(f"{name} holds {iid}", inventory.add_to_inventory(name, iid), True)
            check(f"{name} wears {iid}", inventory.equip_piece(name, iid, source="smoke")["status"], "ok")

        heels = shoe_item("Heels")
        wear("Kira", heels)
        wear("Mira", heels)

        def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
            return render(edit), Route(occasion=occasion, backend=edit, position=1, spec="FakeEdit*",
                                       intended_spec="FakeEdit*", first_position=1)

        fits = []

        def fake_fit(character_name, item_id, fsig, *, body="", profile, schedule=False):
            """The fit as a recorder: the honest record ``fit_state`` reads."""
            fits.append((character_name, item_id))
            base = base_body.current_base(character_name, profile=profile)
            ssig = footwear_source.current_ssig(item_id)
            path = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fit")
            gs.write_record(path.with_suffix(".json"), {
                "accepted": True, "kind": "footwear", "fit_version": garment_fit.FIT_VERSION["footwear"],
                "base_model_sha256": base[1], "base_signature": base[0], "ssig": ssig,
                "parents": {"source": garment_footwear._source_parents(item_id, ssig)}})
            return path

        TABLE = {"footwear_empty": "FakeEdit", "mesh_footwear": "FakeMesh", "garment_view": "FakeEdit",
                 "mesh_garment": "FakeMesh"}

        def explain(occasion, character="", pool=None, **kw):
            return {"resolved": TABLE.get(occasion, "")}

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def fit_state(name, iid):
            base = base_body.current_base(name)
            return garment_footwear.fit_state(name, iid, gs.garment_fsig(name, iid), base[1])

        with patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", fake_run_routed), \
             patch("app.imagegen.routing.explain_occasion", explain), \
             patch("app.models.character.run_rembg", fake_rembg), \
             patch("app.blender.refine.decimate_to", fake_decimate), \
             patch.object(garment_footwear, "fit", fake_fit):

            print("[G1] one candidate per footwear item")
            found = cands()
            check("exactly one candidate", [c.key for c in found], [f"footwear:{heels}"])
            c = found[0]
            check("label counts the wearers", c.label, "Heels · 2 wearers")
            check("hub_jobs: source 1 + empty 1 + mesh 1", c.hub_jobs, 3)
            check("note names the wearers", c.note.startswith("Kira, Mira"), True)
            check("kind clothing lists nothing", cands(kind="clothing"), [])

            print("[G2] apply runs the chain once and fits both wearers")
            entry = store.create(typ.id, "Fill", typ.validate({}), "one_shot")["id"]
            check("scan", engine.scan(entry), {"added": 1, "closed": 0})
            store.mark_running(entry, c.key)
            result = engine.handle_step({"improvement_id": entry, "candidate_key": c.key, "_task_id": "t"})
            check("handle_step ok", result, {"ok": True})
            check("counters (upscale, edit, mesh)", svc.counts(), (1, 1, 1))
            check("fits in wearer order", fits, [("Kira", heels), ("Mira", heels)])
            check("fit_state accepted for both", (fit_state("Kira", heels), fit_state("Mira", heels)),
                  ("accepted", "accepted"))
            check("rescan: no candidate", cands(), [])
            check("the one-shot worked itself off", store.get(entry), None)

            print("[G3] a refused mesh is terminal")
            pumps = shoe_item("Pumps")
            wear("Kira", pumps)
            svc.mesh_fails = True
            before = svc.counts()
            found = cands()
            check("pumps listed", [c.key for c in found], [f"footwear:{pumps}"])
            e = raises("apply raises CandidateRefused", lambda: typ.apply(found[0], typ.validate({}), "t"),
                       CandidateRefused, "mesh — ")
            check("counters moved by (1, 1, 1)",
                  tuple(a - b for a, b in zip(svc.counts(), before)), (1, 1, 1))
            check("refused_step names mesh", (footwear_source.refused_step(pumps) or {}).get("step"), "mesh")
            check("cached_failure honours it for the wearer",
                  (garments.cached_failure("Kira", pumps) or {}).get("step"), "mesh")
            check("rescan: no candidate", cands(), [])
            # Through the engine, on a fresh item: the step row is skipped +
            # refused after ONE attempt, and a rescan leaves it so.
            mules = shoe_item("Mules")
            wear("Mira", mules)
            entry = store.create(typ.id, "Fill", typ.validate({}), "one_shot")["id"]
            check("scan lists the mules", engine.scan(entry), {"added": 1, "closed": 0})
            store.mark_running(entry, f"footwear:{mules}")
            meshes_before = svc.meshes
            result = engine.handle_step({"improvement_id": entry, "candidate_key": f"footwear:{mules}",
                                         "_task_id": "t"})
            check("engine reports the refusal", list(result.keys()), ["refused"])
            step = store.list_steps(entry)[0]
            check("step skipped + refused after one attempt",
                  (step["status"], step["refused"], step["attempts"]), ("skipped", 1, 1))
            check("one mesh attempt", svc.meshes - meshes_before, 1)
            check("rescan closes nothing, the step stays skipped",
                  (engine.scan(entry), store.list_steps(entry)[0]["status"]),
                  ({"added": 0, "closed": 0}, "skipped"))
            check("retry refused", store.retry_step(entry, f"footwear:{mules}"), False)
            check("the entry is done, not deleted", store.get(entry)["status"], "done")
            check("no further mesh call", svc.meshes - meshes_before, 1)
            svc.mesh_fails = False

            print("[G4] a busy mesher is load")
            boots = shoe_item("Boots")
            wear("Mira", boots)
            svc.mesh_raise = BackendBusyError("FakeMesh is busy")
            found = cands()
            check("boots listed", [c.key for c in found], [f"footwear:{boots}"])
            raises("apply raises CandidateBusy", lambda: typ.apply(found[0], typ.validate({}), "t"),
                   CandidateBusy, "busy")
            check("refused_step None", footwear_source.refused_step(boots), None)
            check("listed again on rescan", [c.key for c in cands()], [f"footwear:{boots}"])
            svc.mesh_raise = None

            print("[G5] an unresolved occasion waits before any hub call")
            before = svc.counts()
            saved = TABLE.pop("mesh_footwear")
            raises("CandidateBusy names the occasion", lambda: typ.apply(found[0], typ.validate({}), "t"),
                   CandidateBusy, "no backend available for mesh_footwear right now")
            check("counters unchanged", svc.counts(), before)
            TABLE["mesh_footwear"] = saved
            typ.apply(found[0], typ.validate({}), "t")
            check("boots fitted once the route is back", fit_state("Mira", boots), "accepted")

            print("[G6] scope: worn vs held")
            clogs = shoe_item("Clogs")
            wear("Kira", clogs)
            check("Mira holds the clogs", inventory.add_to_inventory("Mira", clogs), True)
            worn = [c for c in cands(scope="worn") if c.key == f"footwear:{clogs}"]
            check("worn: one wearer", (worn[0].label, worn[0].note.split(" · ")[0]), ("Clogs · 1 wearer", "Kira"))
            held = [c for c in cands(scope="held") if c.key == f"footwear:{clogs}"]
            check("held: two wearers", (held[0].label, held[0].note.split(" · ")[0]),
                  ("Clogs · 2 wearers", "Kira, Mira"))
            check("kind footwear only", {c.key.split(":")[0] for c in cands(kind="footwear")}, {"footwear"})

            print("[G7] clothing per wearer")
            dress = inventory.add_item(name="Dress", category="outfit_piece", prompt_fragment="a green dress",
                                       outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                                     "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
            wear("Kira", dress)
            wear("Nora", dress)
            fsig = gs.garment_fsig("Kira", dress)
            base = base_body.current_base("Kira")

            def write_fit(name):
                prepared = gs.garment_path(name, dress, fsig, "prepared")
                prepared.parent.mkdir(parents=True, exist_ok=True)
                prepared.write_bytes(b"prepared")
                gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
                fit = gs.garment_path(name, dress, fsig, "fit")
                fit.parent.mkdir(parents=True, exist_ok=True)
                fit.write_bytes(b"fit")
                gs.write_record(fit.with_suffix(".json"), {
                    "accepted": True, "kind": "clothing", "fit_version": garment_fit.FIT_VERSION["clothing"],
                    "base_model_sha256": base[1], "inputs": {"prepared_sha256": file_sha256(prepared)}})

            write_fit("Kira")
            clothing = lambda **p: [c for c in cands(kind="clothing", **p)]  # noqa: E731
            check("an accepted fit is no candidate", clothing(), [])
            for part in ("fit", "prepared"):
                p = gs.garment_path("Kira", dress, fsig, part)
                p.unlink()
                p.with_suffix(".json").unlink()
            gs.record_failure("Kira", dress, fsig, step="ghost", error="hem", base_model_sha=base[1])
            check("a persisted failure is no candidate", clothing(), [])
            gs.clear_failure("Kira", dress, fsig)
            found = clothing()
            check("nothing cached: the dress is a candidate",
                  [(c.key, c.label, c.hub_jobs, c.note) for c in found],
                  [(f"clothing:Kira:{dress}", "Kira · Dress", 6, "worn 3 + ghost 2 + mesh 1")])
            check("Nora (off the pipeline) is never a subject", clothing(character="Nora"), [])
            runs = []

            def fake_run_garment(name, item_id, **kw):
                runs.append((name, item_id))
                write_fit(name)
                return {"ok": True, "fsig": fsig, "ran": ["worn", "ghost", "cutout", "mesh", "fit"]}

            with patch.object(garments, "run_garment", fake_run_garment):
                typ.apply(found[0], typ.validate({"kind": "clothing"}), "t")
            check("run_garment called once", runs, [("Kira", dress)])
            check("rescan: gone", clothing(), [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
