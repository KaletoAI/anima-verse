#!/usr/bin/env python3
"""The ``fit_refit`` improvement type (app/core/improvements/types/fit_refit.py;
spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.2):
fits a version bump made stale, refitted at idle time on the CPU, one
candidate per character, never a hub job.

Usage:
    ./.venv/bin/python scripts/smoke_improvement_fit_refit.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. The
fixture follows scripts/smoke_garment_refit_sweep.py: the fit itself is
stubbed (``garments._fit``: a recorder that rewrites the fit record with the
current ``FIT_VERSION``), every hub path is a counting stub that raises
(``service.get_image_service``, ``garment_images.run_edit_step``,
``garment_mesh.generate``, ``garments._run_hairdeck``). Kira is on the
pipeline with a ready base (``model3d/<bsig>.glb`` + sidecar rig mixamo, as
smoke_improvement_garment_fill) and wears an own-mesh Dress; FV = the
CURRENT ``garment_fit.FIT_VERSION["clothing"]``, read, never pinned.
``outfit_bodies.match_stale_postures`` is wrapped by a counter that calls the
real one (Kira has no outfit body: it matches nothing).

Derived by hand from the candidate rule and ``refit_character``:

[F1] An accepted clothing fit of the Dress on the current base sha under the
     current fsig with ``fit_version`` FV - 1 → ``outdated_fits`` lists it →
     exactly one candidate ``character:Kira``, label "Kira · 1 fit: Dress"
     (one unit → singular), hub_jobs 0, note "CPU only — no hub job".
     ``needs_media`` False. The parameter ``character=Kira`` lists the same;
     ``character=Nora`` (a plain profile, off the pipeline) lists nothing.
[F3] ``garments._active`` holds Kira (a garment chain runs) → through the
     engine (``handle_step``) the step answers busy, stays ``pending`` with
     attempts 0; neither the posture match nor ``_fit`` ran (0 / 0).
[F4] The media switch OFF (``engine.media_generation_enabled`` False), the
     engine enabled (idle 15 min = 900 s), the user idle 960 s →
     ``engine.tick()`` submits THIS entry's step (reason "ok", the task
     payload ``{improvement_id, candidate_key: "character:Kira"}``)
     — ``needs_media`` False lets it pass the switch.
[F2] That task handled (``handle_step``) with the switch still off →
     {"ok": True}: the posture match ran once, ``_fit`` once for the Dress,
     the record now reads FV; 0 hub calls; rescan → no candidate; the one-shot
     worked itself off (``store.get`` None).
[F5] A refused refit: the old record back at FV - 1 (still ``accepted``) +
     a failure record step "fit" on the current base sha (what
     ``_note_outcome`` writes) → ``garment_refit.outdated_fits`` STILL lists
     the Dress (the lister does not read failure records), but
     ``chain_failure`` honours it → no candidate. The same failure recorded on
     ANOTHER base sha does not hold (``chain_failure`` ignores a fit failure
     of another base) → the candidate is back.
[F6] An outfit body ob0000000a (``garments.body_sha256`` = "BODY"), the base
     fit at FV again, a body fit of the Dress at FV - 1 on body sha "BODY" →
     ``outdated_body_fits`` lists it → label "Kira · 1 fit: Dress@ob0000000a".
     A body failure on "BODY" from the current base fit (its sha) at FV
     (what ``_refit_bodies`` records for a refused body refit) → no
     candidate; the same failure at FV - 1 (an older algorithm) does not hold
     → the candidate is back.
0 hub calls throughout.

Fails on d4c95738: ModuleNotFoundError — app.core.improvements.types.fit_refit.
"""
import json
import os
import shutil
import sqlite3
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="improvement-fit-refit-") as tmp:
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

        from app.core import (base_body, garment_assembly, garment_fit, garment_images, garment_mesh,
                              garment_refit, garments, glb_delivery, model_refs, outfit_bodies, user_activity)
        from app.core import garment_store as gs
        from app.core.improvements import engine, registry, store
        from app.core.improvements.types.fit_refit import FitRefit
        from app.core.task_queue import get_task_queue
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        get_task_queue()._started = True          # no worker threads: rows only
        queue_db = root / "world" / "task_queue.db"
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda *a, **k: True
        glb_delivery.delivery_path = lambda path, **kw: path
        registry.clear()
        typ = FitRefit()
        registry.register(typ)

        # --- hub paths: counting stubs that raise ------------------------------------
        HUB = []

        def hub(name):
            def stub(*a, **k):
                HUB.append(name)
                raise RuntimeError(f"hub call {name} in fit_refit")
            return stub

        service.get_image_service = hub("image_service")
        garment_images.run_edit_step = hub("run_edit_step")
        garment_mesh.generate = hub("generate_mesh")
        garments._run_hairdeck = hub("run_hairdeck")

        POSTURE = []
        real_match = outfit_bodies.match_stale_postures

        def match(name):
            POSTURE.append(name)
            return real_match(name)
        outfit_bodies.match_stale_postures = match

        # --- the character ---------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        for name in ("Kira", "Nora"):
            check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
        check("pipeline Kira", base_body.set_pipeline("Kira", True), True)
        bsig = base_body.base_signature("Kira")
        mdir = get_character_dir("Kira") / "model3d"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        check("Kira base ready", (base_body.base_model_info("Kira") or {}).get("status"), "ready")

        dress = inventory.add_item(name="Dress", category="outfit_piece", prompt_fragment="a green dress",
                                   outfit_piece={"slots": ["top", "bottom"], "covers": ["legs"],
                                                 "outfit_types": ["casual"], "own_mesh": True})["id"]
        for name in ("Kira", "Nora"):
            check(f"{name} holds the dress", inventory.add_to_inventory(name, dress), True)
            check(f"{name} wears the dress", inventory.equip_piece(name, dress, source="smoke")["status"], "ok")
        fsig = gs.garment_fsig("Kira", dress)
        base = base_body.current_base("Kira")
        FV = garment_fit.FIT_VERSION["clothing"]
        fit = gs.garment_path("Kira", dress, fsig, "fit")
        fit.parent.mkdir(parents=True, exist_ok=True)
        fit.write_bytes(b"OLD-FIT")

        def write_fit(version):
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": "clothing", "item_id": dress, "fsig": fsig,
                "base_signature": base[0], "base_model_sha256": base[1], "fit_version": version})

        FITS = []

        def fit_stub(name, item_id, kind, fsig_, bsig_, profile):
            """The fit as a recorder: the record rewritten with the current version."""
            FITS.append(item_id)
            record = gs.read_record(fit.with_suffix(".json"))
            record["fit_version"] = garment_fit.FIT_VERSION[kind]
            gs.write_record(fit.with_suffix(".json"), record)
        garments._fit = fit_stub

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def step_tasks():
            conn = sqlite3.connect(f"file:{queue_db}?mode=ro", uri=True)
            try:
                rows = conn.execute("SELECT task_id, payload FROM tasks WHERE task_type=? ORDER BY created_at, rowid",
                                    (engine.TASK_TYPE,)).fetchall()
            finally:
                conn.close()
            return [{"task_id": r[0], "payload": json.loads(r[1])} for r in rows]

        def worker_done(task_id):
            conn = sqlite3.connect(queue_db)
            try:
                conn.execute("UPDATE tasks SET status='completed' WHERE task_id=?", (task_id,))
                conn.commit()
            finally:
                conn.close()

        # --- [F1] -------------------------------------------------------------------
        print("[F1] a clothing fit one version behind is a candidate")
        write_fit(FV - 1)
        check("outdated_fits lists the dress", garment_refit.outdated_fits("Kira"),
              [(dress, "clothing", fsig, gs.EDIT_CHAIN)])
        found = cands()
        check("one candidate", [(c.key, c.label, c.hub_jobs, c.note) for c in found],
              [("character:Kira", "Kira · 1 fit: Dress", 0, "CPU only — no hub job")])
        check("needs_media False", typ.needs_media, False)
        check("character=Kira lists the same", [c.key for c in cands(character="Kira")], ["character:Kira"])
        check("Nora (off the pipeline) is never a subject", cands(character="Nora"), [])

        # --- [F3] -------------------------------------------------------------------
        print("[F3] a running garment chain is load")
        entry = store.create(typ.id, "Refit", typ.validate({}), "one_shot")["id"]
        check("scan", engine.scan(entry), {"added": 1, "closed": 0})
        with garments._lock:
            garments._active.add("Kira")
        try:
            store.mark_running(entry, "character:Kira")
            result = engine.handle_step({"improvement_id": entry, "candidate_key": "character:Kira",
                                         "_task_id": "t"})
        finally:
            with garments._lock:
                garments._active.discard("Kira")
        check("handle_step answers busy", list(result), ["busy"])
        step = store.list_steps(entry)[0]
        check("step pending, attempts 0", (step["status"], step["attempts"]), ("pending", 0))
        check("nothing touched (posture match, _fit)", (len(POSTURE), len(FITS)), (0, 0))

        # --- [F4] + [F2] ------------------------------------------------------------
        print("[F4] the media switch off: the tick submits this CPU-only step")
        store.set_order([entry])
        engine._undefer(entry, "character:Kira")     # [F3]'s busy deferral (BUSY_DEFER_S) is over
        store.set_settings(True, 15)                 # the engine on, idle threshold 15 min = 900 s
        user_activity._set_for_test(960)             # idle 960 s > 900 s
        with patch("app.core.improvements.engine.media_generation_enabled", return_value=False):
            check("submit_allowed names the switch", engine.submit_allowed(), (False, "media_off"))
            result = engine.tick()
            tasks = step_tasks()
            check("submitted, reason ok",
                  (result["reason"], bool(result["submitted"]), tasks[-1]["payload"] if tasks else None),
                  ("ok", True, {"improvement_id": entry, "candidate_key": "character:Kira"}))

            print("[F2] apply refits on the CPU, no service call")
            worker_done(result["submitted"])
            done = engine.handle_step({"improvement_id": entry, "candidate_key": "character:Kira",
                                       "_task_id": result["submitted"]})
        check("handle_step ok", done, {"ok": True})
        check("posture match ran once", POSTURE, ["Kira"])
        check("_fit ran once for the dress", FITS, [dress])
        check("the record reads FV", gs.read_record(fit.with_suffix(".json")).get("fit_version"), FV)
        check("no hub call", HUB, [])
        check("rescan: no candidate", cands(), [])
        check("the one-shot worked itself off", store.get(entry), None)

        # --- [F5] -------------------------------------------------------------------
        print("[F5] a refused refit is held back by its failure record")
        write_fit(FV - 1)
        gs.record_failure("Kira", dress, fsig, step="fit", error="fit refused — x", base_model_sha=base[1])
        check("outdated_fits still lists the dress", [i for i, *_ in garment_refit.outdated_fits("Kira")], [dress])
        check("chain_failure honours it",
              (gs.chain_failure("Kira", dress, fsig, base_model_sha=base[1]) or {}).get("step"), "fit")
        check("no candidate", cands(), [])
        gs.record_failure("Kira", dress, fsig, step="fit", error="fit refused — x", base_model_sha="o" * 64)
        check("a failure on another base does not hold", [c.label for c in cands()], ["Kira · 1 fit: Dress"])
        gs.clear_failure("Kira", dress, fsig)

        # --- [F6] -------------------------------------------------------------------
        print("[F6] a fit on an outfit body")
        BODY = "ob0000000a"
        write_fit(FV)
        garments.body_sha256 = lambda name, body_id: "BODY"
        body_fit = gs.garment_path("Kira", dress, fsig, "fit", body=BODY)
        body_fit.parent.mkdir(parents=True, exist_ok=True)
        body_fit.write_bytes(b"OLD-BODY-FIT")
        gs.write_record(body_fit.with_suffix(".json"), {
            "accepted": True, "kind": "clothing", "item_id": dress, "fsig": fsig, "body_id": BODY,
            "body_sha256": "BODY", "fit_version": FV - 1})
        check("outdated_body_fits lists it", garment_refit.outdated_body_fits("Kira"),
              [(dress, "clothing", fsig, BODY)])
        check("label names the body", [c.label for c in cands()], [f"Kira · 1 fit: Dress@{BODY}"])
        base_fit_sha = garments._sha(fit)
        gs.record_body_failure("Kira", dress, fsig, BODY, error="fit refused — y", body_sha="BODY",
                               base_fit_sha=base_fit_sha, fit_version=FV)
        check("a holding body failure: no candidate", cands(), [])
        gs.record_body_failure("Kira", dress, fsig, BODY, error="fit refused — y", body_sha="BODY",
                               base_fit_sha=base_fit_sha, fit_version=FV - 1)
        check("a failure of an older algorithm does not hold", [c.label for c in cands()],
              [f"Kira · 1 fit: Dress@{BODY}"])
        check("still no hub call", HUB, [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
