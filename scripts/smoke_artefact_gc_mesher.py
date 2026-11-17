#!/usr/bin/env python3
"""The artefact GC takes the mesher original (``model3d/unrigged/mesher/<sig>.glb``, ``model3d.MESHER_DIR``) with
its signature — review 09#3 (``outfit_cache_gc._mesh_files``; ``model3d._purge_combination`` already does, A38).

Usage:
    ./.venv/bin/python scripts/smoke_artefact_gc_mesher.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no world, no
hub, no GPU, no server; ``get_image_service`` raises (the GC never renders). Fixture cut from
scripts/smoke_improvement_artefact_cleanup.py: ``demo`` holds and wears ``dress`` (slot top) -> worn signature W.
Every file aged 11 min (past ``artefact_graph.GRACE_S`` = 10 min); synthetic bytes, only names and sidecars matter.

Planted under ``model3d/``:
  W (worn):   W.glb, W.json {pieces {top: dress}}, unrigged/W.glb, unrigged/mesher/W.glb
  X (orphan): X.glb, X.json {pieces {top: old}} (an item nobody holds), unrigged/X.glb, unrigged/mesher/X.glb
  Y:          unrigged/mesher/Y.glb only — the original a GC run before this fix left behind (its model gone)

Expected, by hand from the rule "a signature's files go and stay together" (the mesher original is read only
through its own signature: ``face_cleanup_state`` / ``_reclean_face_source`` beside ``unrigged/<sig>.glb``):
[1] ``_mesh_files(demo)[X]`` = X.glb, X.json, unrigged/X.glb, unrigged/mesher/X.glb (4 files); W likewise 4;
    Y = [unrigged/mesher/Y.glb].
[2] The dry run (``collect(dry_run=True)``): orphan keys {X, Y} (Y: no top-level model, a signature nothing
    produces); W is not an orphan; no ``unrigged/mesher/`` path in ``unknown``.
[3] ``collect`` (not dry): X's 4 files and Y's file are gone; W's 4 files stay, its mesher original included.
Fails on 3f2ce338e: [1] X has 3 files, [2] orphans {X} and both mesher files ``unknown``, [3] mesher/X.glb and
mesher/Y.glb stay.
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
    with tempfile.TemporaryDirectory(prefix="artefact-gc-mesher-") as tmp:
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

        from app.core import artefact_graph as ag, model_refs, outfit_cache_gc as ocg
        from app.core.task_queue import get_task_queue
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        def no_service(*a, **k):
            raise RuntimeError("the GC never calls the image service")
        service.get_image_service = no_service
        model_refs.schedule_outfit_render = lambda *a, **k: None
        get_task_queue()._started = True

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create demo", save_character_profile("demo", dict(human), create_new=True), True)
        piece = {"slots": ["top"], "covers": [], "outfit_types": ["casual"]}
        dress = inventory.add_item(name="Dress", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a green dress", outfit_piece=piece)["id"]
        check("demo holds the dress", inventory.add_to_inventory("demo", dress), True)
        check("demo wears it", inventory.equip_piece("demo", dress, source="smoke")["status"], "ok")
        W = model_refs.current_outfit_state("demo")[2]
        X, Y = "0123456789ab", "fedcba987654"
        check("three distinct signatures", len({W, X, Y}), 3)
        M = get_character_dir("demo") / "model3d"

        def group(sig, manifest):
            return [touch(M / f"{sig}.glb", b"model-" + sig.encode()), touch(M / f"{sig}.json", manifest),
                    touch(M / "unrigged" / f"{sig}.glb", b"source-" + sig.encode()),
                    touch(M / "unrigged" / "mesher" / f"{sig}.glb", b"mesher-" + sig.encode())]
        w_files = group(W, {"pieces": {"top": dress}, "items": []})
        x_files = group(X, {"pieces": {"top": "old"}, "items": []})
        y_files = [touch(M / "unrigged" / "mesher" / f"{Y}.glb", b"mesher-" + Y.encode())]

        def rel(files):
            return sorted(p.relative_to(M).as_posix() for p in files)

        print("[1] the mesh groups")
        groups = ocg._mesh_files("demo")
        check("X", rel(groups.get(X, [])), rel(x_files))
        check("W", rel(groups.get(W, [])), rel(w_files))
        check("Y", rel(groups.get(Y, [])), rel(y_files))

        print("[2] the dry run")
        dry = ag.collect("demo", dry_run=True, explicit=False)
        check("orphans", sorted(o["key"] for o in dry["orphans"]), sorted([X, Y]))
        check("no mesher path unknown", [u for u in dry["unknown"] if "/mesher/" in u], [])

        print("[3] the collect")
        ag.collect("demo", dry_run=False, explicit=False, reason="smoke")
        check("X gone", [p.exists() for p in x_files], [False] * 4)
        check("Y gone", [p.exists() for p in y_files], [False])
        check("W stays", [p.exists() for p in w_files], [True] * 4)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
