#!/usr/bin/env python3
"""The ``artefact_cleanup`` improvement type (app/core/improvements/types/artefact_cleanup.py;
spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.6): orphaned derived
files, dry run first, removed through the ONE collector (``artefact_graph.collect``).

Usage:
    ./.venv/bin/python scripts/smoke_improvement_artefact_cleanup.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` first) with a copy of the repo's
``human`` package — no world, no hub, no GPU, no server. Fixture cut from scripts/smoke_artefact_gc.py and
scripts/smoke_footwear_gc.py: character ``demo`` (human, NOT on the base-body pipeline — the type takes
every character with derived directories) holding and wearing ``dress`` (slot top) → worn signature W.
Synthetic bytes everywhere; only names and JSON sidecars matter to the collector.
``get_image_service`` is patched to raise in every case: the cleanup never touches the image service.

Expectations, by hand from § 6.6 and artefact_graph's module docstring:

[A1] The worn outfit model group ``model3d/W.glb`` + ``W.json`` (2 files, manifest {top: dress}) and ONE
     orphan outfit group ``model3d/X.glb`` (2 000 000 bytes) + ``X.json`` (24 bytes, manifest
     {top: old} — an item nobody holds: "no producible outfit"), every mtime 11 min back (past
     ``GRACE_S`` = 10 min) → exactly one candidate ``character:demo``, label
     ``demo · 1 node · 2 file(s) · 2.0 MB`` (2 000 024 bytes / 1e6 = 2.0), hub_jobs 0, note
     ``meshes 1 (2.0 MB)`` (the category of a model group). No world candidate: no ``footwear/`` yet.
[A2] Through the engine (``handle_step``) → {"ok": True}; X's 2 files are gone, W's 2 files on disk;
     the step's note becomes the result note ``deleted 2 file(s), freed 2.0 MB, 0 skipped``;
     rescan → no candidate.
[A3] X planted again with FRESH mtimes: grace ``on`` → the dry run lists X as protected "grace" →
     no candidate; grace ``off`` (explicit) → the candidate is back (same label as A1).
[A4] A manifest-less outfit entry ``model3d/cccccccccccc.glb`` + ``.json`` (no pieces: the only
     shape that forces the reachable set) and ``artefact_graph.HOOK_BUDGET_S`` patched to 0 →
     the dry run is ``aborted`` → no candidate; ``apply`` on ``character:demo`` → CandidateBusy, and
     nothing was deleted (X still there). Budget back, the entry and X removed by hand.
[A5] Painted bodies — a consumer of the painted-body reachability fix (commit 72e260fb: a texture lives
     while a live outfit would paint it NOW; a tsig a live outfit only names is outdated). TK =
     ``figure.predicted_keys(demo, {top: dress}, [], bsig=bsig)[1]`` (what the worn
     outfit would paint now), named by W's model sidecar (``texture_signature``); TO =
     ``tex000000000000`` named by nobody. Both as ``model3d/texture/<tsig>.glb`` + ``.json`` (sidecar
     ``texture_signature``, the current ``base_signature``), aged 11 min. The dry run lists
     ``texture:TO`` (reason "no live outfit names it", category textures) and not ``texture:TK``; the
     candidate label ``demo · 1 node · 2 file(s) · …``; after apply TO's 2 files are gone, TK's 2 files
     and W's group stay. Then TN = ``tex111111111111``, stored the same way and NAMED by the worn
     outfit's front reference sidecar ``model_refs/tpose_W.json`` (no base views: that front builds
     nothing now) — named but not painted now → an orphan, reason ``artefact_graph.OUTDATED_TEXTURE``,
     parent ``built_on`` [W] (before 72e260fb a named tsig was kept); apply removes it, TK stays.
[A6] World shoe sources: item ``heels`` (feet, own mesh, held by nobody) with its CURRENT ssig folder
     (``footwear_source.current_ssig``) holding one file, and a folder ``000000000000`` nobody names
     holding one 16-byte file → candidate ``footwear_sources``, label
     ``Shoe sources · 1 folder(s) · 0.0 MB``, hub_jobs 0; with a character chosen it is not listed;
     apply removes the stale folder, the current one stays; rescan → no world candidate.
[A7] Media off (``media_generation_enabled`` False), engine enabled, idle 960 s, an orphan X planted
     (aged) and an entry scanned → ``engine.tick()`` submits the step (reason "ok", payload names the
     entry and ``character:demo``) — ``needs_media`` is False.

Fails on 193321cf: ModuleNotFoundError — app.core.improvements.types.artefact_cleanup.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
AGED_S = 11 * 60


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


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def age(paths, seconds):
    when = time.time() - seconds
    for p in paths:
        os.utime(p, (when, when))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="improvement-artefact-cleanup-") as tmp:
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
        # The legacy whole-body path this smoke covers: since Task 11h (Ruling A13) every humanoid is on
        # the base-body pipeline and only a non-humanoid takes it; the humanoid fixture keeps it via this stub.
        from app.core import base_body as _legacy_bb
        _legacy_bb.is_base_pipeline = lambda *_a, **_k: False
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import artefact_graph as ag, base_body, footwear_source as fs, model_refs, user_activity
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import Candidate, CandidateBusy
        from app.core.improvements.types.artefact_cleanup import ArtefactCleanup
        from app.core.task_queue import get_task_queue
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        def no_service(*a, **k):
            raise RuntimeError("the cleanup never calls the image service")
        service.get_image_service = no_service
        model_refs.schedule_outfit_render = lambda *a, **k: None
        get_task_queue()._started = True          # no worker threads: rows only
        queue_db = paths.get_storage_dir() / "task_queue.db"
        registry.clear()
        typ = ArtefactCleanup()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create demo", save_character_profile("demo", dict(human), create_new=True), True)
        piece = {"slots": ["top"], "covers": [], "outfit_types": ["casual"]}
        dress = inventory.add_item(name="Dress", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a green dress", outfit_piece=piece)["id"]
        check("demo holds the dress", inventory.add_to_inventory("demo", dress), True)
        check("demo wears it", inventory.equip_piece("demo", dress, source="smoke")["status"], "ok")
        W = model_refs.current_outfit_state("demo")[2]
        M = get_character_dir("demo") / "model3d"
        worn = [touch(M / f"{W}.glb", b"worn-model"),
                touch(M / f"{W}.json", {"pieces": {"top": dress}, "items": []})]
        X = "0123456789ab"
        X_JSON = b'{"pieces":{"top":"old"}}'

        def plant_x(aged=True):
            files = [touch(M / f"{X}.glb", b"\0" * 2_000_000), touch(M / f"{X}.json", X_JSON)]
            if aged:
                age(files, AGED_S)
            return files

        def cands(**params):
            return typ.find_candidates(typ.validate(params))

        def run_step(entry, key):
            store.mark_running(entry, key)
            return engine.handle_step({"improvement_id": entry, "candidate_key": key, "_task_id": "t"})

        def step_of(entry, key):
            return [s for s in store.list_steps(entry) if s["candidate_key"] == key][0]

        # --- [A1] ---------------------------------------------------------------
        print("[A1] one orphan outfit group, aged past the grace window")
        check("X sidecar is 24 bytes", len(X_JSON), 24)
        x_files = plant_x()
        age(worn, AGED_S)
        found = cands()
        check("one candidate", [(c.key, c.label, c.hub_jobs, c.note) for c in found],
              [("character:demo", "demo · 1 node · 2 file(s) · 2.0 MB", 0, "meshes 1 (2.0 MB)")])
        check("needs_media", typ.needs_media, False)

        # --- [A2] ---------------------------------------------------------------
        print("[A2] apply through the engine")
        entry = store.create(typ.id, "Cleanup", typ.validate({}), "standing")["id"]
        check("scan", engine.scan(entry), {"added": 1, "closed": 0})
        check("handle_step ok", run_step(entry, "character:demo"), {"ok": True})
        check("X gone", [p.exists() for p in x_files], [False, False])
        check("the worn group stays", [p.exists() for p in worn], [True, True])
        check("the result note", step_of(entry, "character:demo")["note"],
              "deleted 2 file(s), freed 2.0 MB, 0 skipped")
        check("rescan: no candidate", cands(), [])
        store.delete(entry)

        # --- [A3] ---------------------------------------------------------------
        print("[A3] the grace window")
        x_files = plant_x(aged=False)
        dry = ag.collect("demo", dry_run=True, explicit=False)
        check("young X protected 'grace'", [(o["key"], o["protected"]) for o in dry["orphans"]], [(X, "grace")])
        check("grace on: no candidate", cands(), [])
        check("grace off: the candidate", [c.label for c in cands(grace="off")],
              ["demo · 1 node · 2 file(s) · 2.0 MB"])

        # --- [A4] ---------------------------------------------------------------
        print("[A4] over the time budget")
        age(x_files, AGED_S)
        bare = [touch(M / "cccccccccccc.glb"), touch(M / "cccccccccccc.json", {"rig": "mixamo"})]
        age(bare, AGED_S)
        with patch.object(ag, "HOOK_BUDGET_S", 0):
            check("the dry run is aborted",
                  bool(ag.collect("demo", dry_run=True, budget_s=ag.HOOK_BUDGET_S)["aborted"]), True)
            check("no candidate", cands(), [])
            raises("apply → CandidateBusy",
                   lambda: typ.apply(Candidate("character:demo", "demo"), typ.validate({}), "t"), CandidateBusy)
        check("nothing deleted", [p.exists() for p in x_files + bare], [True] * 4)
        for p in x_files + bare:
            p.unlink()

        # --- [A5] ---------------------------------------------------------------
        print("[A5] painted bodies (commit 72e260fb's rule, through collect's report)")
        bsig = base_body.base_signature("demo")
        from app.core import figure
        TK = figure.predicted_keys("demo", {"top": dress}, [], bsig=bsig)[1]
        TO = "tex000000000000"
        check("TK is a texture signature, not TO", (base_body.is_texture_signature(TK), TK != TO), (True, True))
        worn[1].write_text(json.dumps({"pieces": {"top": dress}, "items": [], "texture_signature": TK}))
        tex = {t: [touch(M / "texture" / f"{t}.glb", b"painted-" + t.encode()),
                   touch(M / "texture" / f"{t}.json", {"texture_signature": t, "base_signature": bsig})]
               for t in (TK, TO)}
        age(worn + tex[TK] + tex[TO], AGED_S)
        dry = ag.collect("demo", dry_run=True, explicit=False)
        check("only texture:TO is an orphan",
              [(o["key"], o["category"], o["reason"]) for o in dry["orphans"]],
              [(f"texture:{TO}", "textures", "no live outfit names it")])
        found = cands()
        check("candidate", [(c.key, c.label.startswith("demo · 1 node · 2 file(s) · ")) for c in found],
              [("character:demo", True)])
        typ.apply(found[0], typ.validate({}), "t")
        check("TO gone", [p.exists() for p in tex[TO]], [False, False])
        check("TK and the worn group stay", [p.exists() for p in tex[TK] + worn], [True] * 4)
        TN = "tex111111111111"
        R = get_character_dir("demo") / "model_refs"
        front = [touch(R / f"tpose_{W}.png", b"png"),
                 touch(R / f"tpose_{W}.json", {"equipped_pieces": {"top": dress}, "equipped_items": [],
                                              "texture_signature": TN})]
        tex[TN] = [touch(M / "texture" / f"{TN}.glb", b"painted-tn"),
                   touch(M / "texture" / f"{TN}.json", {"texture_signature": TN, "base_signature": bsig})]
        age(front + tex[TN], AGED_S)
        dry = ag.collect("demo", dry_run=True, explicit=False)
        check("TN named, not painted now: outdated",
              [(o["key"], o["reason"], o["parents"].get("built_on")) for o in dry["orphans"]],
              [(f"texture:{TN}", ag.OUTDATED_TEXTURE, [W])])
        typ.apply(cands()[0], typ.validate({}), "t")
        check("TN gone, TK stays", [p.exists() for p in tex[TN] + tex[TK]], [False, False, True, True])

        # --- [A6] ---------------------------------------------------------------
        print("[A6] the world shoe sources")
        heels = inventory.add_item(name="Heels", category="outfit_piece", item_id="heels",
                                   prompt_fragment="black heels",
                                   outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
        S = fs.current_ssig(heels)
        current = touch(fs.source_dir(heels, S) / "upscaled.png", b"png")
        stale = fs.source_dir(heels, "000000000000")
        touch(stale / "upscaled.png")
        found = cands()
        check("world candidate", [(c.key, c.label, c.hub_jobs) for c in found],
              [("footwear_sources", "Shoe sources · 1 folder(s) · 0.0 MB", 0)])
        check("not with a character chosen", cands(character="demo"), [])
        typ.apply(found[0], typ.validate({}), "t")
        check("stale gone, current stays", (stale.exists(), current.exists()), (False, True))
        check("rescan: nothing", cands(), [])

        # --- [A7] ---------------------------------------------------------------
        print("[A7] media off: the tick still submits the cleanup")
        plant_x()
        for row in store.list_all():
            store.delete(row["id"])
        entry = store.create(typ.id, "Cleanup", typ.validate({}), "one_shot")["id"]
        check("scan", engine.scan(entry), {"added": 1, "closed": 0})
        store.set_settings(True, 15)
        user_activity._set_for_test(960)
        with patch("app.core.improvements.engine.media_generation_enabled", return_value=False):
            check("submit_allowed names the switch", engine.submit_allowed()[1], "media_off")
            result = engine.tick()
        conn = sqlite3.connect(f"file:{queue_db}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT payload FROM tasks WHERE task_type=? ORDER BY created_at, rowid",
                                (engine.TASK_TYPE,)).fetchall()
        finally:
            conn.close()
        check("submitted", (result["reason"], bool(result["submitted"]), json.loads(rows[-1][0])),
              ("ok", True, {"improvement_id": entry, "candidate_key": "character:demo"}))

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
