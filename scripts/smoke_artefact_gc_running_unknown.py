#!/usr/bin/env python3
"""The artefact GC deletes nothing when it cannot tell what is running (app/core/artefact_graph.py
``running_state`` / ``collect`` / ``delete_body``; consumers ``sweep_all`` and the improvement type
``artefact_cleanup``) — review 09#7.

Usage:
    ./.venv/bin/python scripts/smoke_artefact_gc_running_unknown.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no world, no
hub, no GPU, no server; ``get_image_service`` raises (the GC never renders). Fixture cut from
scripts/smoke_artefact_gc_mesher.py: ``demo`` holds and wears ``dress`` -> worn W (``W.glb`` + manifest); an orphan
outfit group X = ``0123456789ab`` (``X.glb`` + ``X.json`` {pieces {top: old}}, an item nobody holds) and an outfit
body ``ob12345678`` (``model3d/ob12345678.glb`` + ``.json``). Every file aged 11 min (past GRACE_S = 10 min).
"A registry read that raises" = ``hub_ops.list_ops`` raising RuntimeError (a DB error; this registry is not
re-read inside ``_delete_node``, unlike the stage registry).

Expected, by hand from the rule "a run that cannot be seen may be writing — delete nothing":
[1] Normal: ``running_state`` -> ({}, {}, ""); the dry run's orphans contain X, ``aborted`` "".
[2] ``list_ops`` raising:
    a) ``running_state(demo)[2]`` == RUNNING_UNKNOWN + "hub operations"; ``running_keys`` still answers a pair.
    b) ``collect(explicit=True)`` -> aborted == that text, deleted_files 0, orphans []; X's 2 files on disk.
       The dry run: aborted the same.
    c) ``collect_quietly`` -> aborted the same, deleted 0; ``sweep_all()`` -> deleted_files 0; X on disk.
    d) ``delete_body(demo, ob12345678)`` -> deleted_files 0, skipped [{key ob12345678, why running}], its 2 files
       on disk.
    e) The improvement type: an entry scanned BEFORE the failure has step ``character:demo`` pending; a rescan
       under the failure -> {added 0, closed 0}, the step still pending; the candidate is listed as
       ``demo · size unknown``; ``apply`` -> CandidateBusy; X on disk.
[3] ``list_ops`` back: ``collect(explicit=True, keys=[X])`` -> aborted "", deleted_files 2, X gone, W stays.
Fails on 1dbf8d3af in [2] (aborted ""; b deletes X and the body; the rescan closes the step as done).
"""
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
AGED_S = 11 * 60


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    when = time.time() - AGED_S
    os.utime(path, (when, when))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="artefact-gc-running-unknown-") as tmp:
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
        from app.core import base_body as _legacy_bb
        _legacy_bb.is_base_pipeline = lambda *_a, **_k: False
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import artefact_graph as ag, hub_ops, model_refs
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import Candidate, CandidateBusy
        from app.core.improvements.types.artefact_cleanup import ArtefactCleanup
        from app.core.task_queue import get_task_queue
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        def no_service(*a, **k):
            raise RuntimeError("the GC never calls the image service")
        service.get_image_service = no_service
        model_refs.schedule_outfit_render = lambda *a, **k: None
        get_task_queue()._started = True
        registry.clear()
        typ = ArtefactCleanup()
        registry.register(typ)

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create demo", save_character_profile("demo", dict(human), create_new=True), True)
        piece = {"slots": ["top"], "covers": [], "outfit_types": ["casual"]}
        dress = inventory.add_item(name="Dress", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a green dress", outfit_piece=piece)["id"]
        inventory.add_to_inventory("demo", dress)
        inventory.equip_piece("demo", dress, source="smoke")
        W = model_refs.current_outfit_state("demo")[2]
        X, OB = "0123456789ab", "ob12345678"
        M = get_character_dir("demo") / "model3d"
        w_files = [touch(M / f"{W}.glb"), touch(M / f"{W}.json", {"pieces": {"top": dress}, "items": []})]
        x_files = [touch(M / f"{X}.glb"), touch(M / f"{X}.json", {"pieces": {"top": "old"}, "items": []})]
        ob_files = [touch(M / f"{OB}.glb"), touch(M / f"{OB}.json", {"body_id": OB})]

        print("[1] the normal path")
        check("running_state", ag.running_state("demo"), (set(), set(), ""))
        dry = ag.collect("demo", dry_run=True, explicit=True)
        check("X is an orphan, not aborted", (X in [o["key"] for o in dry["orphans"]], dry["aborted"]), (True, ""))
        entry = store.create(typ.id, "Cleanup", typ.validate({}), "standing")["id"]
        check("scan", engine.scan(entry)["added"], 1)

        print("[2] the hub operation registry raises")
        real = hub_ops.list_ops

        def broken(*_a, **_k):
            raise RuntimeError("registry broken")
        hub_ops.list_ops = broken
        want = ag.RUNNING_UNKNOWN + "hub operations"
        check("a) unknown", ag.running_state("demo")[2], want)
        check("a) running_keys a pair", len(ag.running_keys("demo")), 2)
        rep = ag.collect("demo", explicit=True, reason="smoke")
        check("b) collect", (rep["aborted"], rep["deleted_files"], rep["orphans"]), (want, 0, []))
        check("b) dry run aborted", ag.collect("demo", dry_run=True, explicit=True)["aborted"], want)
        quiet = ag.collect_quietly("demo", "smoke")
        check("c) collect_quietly", (quiet["aborted"], quiet["deleted_files"]), (want, 0))
        check("c) sweep_all deletes nothing", ag.sweep_all()["deleted_files"], 0)
        body = ag.delete_body("demo", OB)
        check("d) delete_body", (body["deleted_files"], body["skipped"]), (0, [{"key": OB, "why": "running"}]))
        check("d) body files stay", [p.exists() for p in ob_files], [True, True])
        check("e) rescan closes nothing", engine.scan(entry), {"added": 0, "closed": 0})
        check("e) step pending", [s["status"] for s in store.list_steps(entry)
                                  if s["candidate_key"] == "character:demo"], ["pending"])
        check("e) candidate", [(c.key, c.label) for c in typ.find_candidates(typ.validate({}))],
              [("character:demo", "demo · size unknown")])
        try:
            typ.apply(Candidate("character:demo", "demo"), typ.validate({}), "t")
            check("e) apply", "returned", "CandidateBusy")
        except CandidateBusy:
            check("e) apply", "CandidateBusy", "CandidateBusy")
        check("X on disk throughout", [p.exists() for p in x_files], [True, True])

        print("[3] the registry back")
        hub_ops.list_ops = real
        rep = ag.collect("demo", explicit=True, keys=[X], reason="smoke")
        check("collect X", (rep["aborted"], rep["deleted_files"]), ("", 2))
        check("X gone, W stays", [p.exists() for p in x_files + w_files], [False, False, True, True])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
