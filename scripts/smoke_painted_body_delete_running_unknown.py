#!/usr/bin/env python3
"""The painted-body Delete names the true reason when what runs cannot be read (app/core/outfit_bodies.py
``delete_texture``) — review 09#7 follow-up.

Usage:
    ./.venv/bin/python scripts/smoke_painted_body_delete_running_unknown.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no world, no
hub, no GPU, no server; ``get_image_service`` raises. Fixture cut from scripts/smoke_improvement_artefact_cleanup.py
[A5]: ``demo`` (human, legacy path stub) holds and wears ``dress`` -> worn W, model ``W.glb`` + sidecar naming
TK = ``figure.predicted_keys(demo, {top: dress}, [], bsig)[1]`` (what the worn outfit paints now); two painted
bodies ``model3d/texture/<tsig>.glb`` + ``.json`` (sidecar ``texture_signature``, the current base signature):
TK and TO = ``tex000000000000`` (named by nobody). Every file aged 11 min.
"What runs cannot be read" = ``hub_ops.list_ops`` raising.

Expected, by hand:
[1] ``list_ops`` raising: ``delete_texture(demo, TO)`` -> LookupError whose text is
    ``artefact_graph.RUNNING_UNKNOWN`` + "hub operations" (the collect aborted; before: PAINTED_NEEDED, which is
    false — nothing needs TO); TO's 2 files on disk.
[2] ``list_ops`` back: ``delete_texture(demo, TK)`` -> LookupError ``PAINTED_NEEDED`` (unchanged), TK on disk;
    ``delete_texture(demo, TO)`` -> a report, TO's 2 files gone; again -> ``UnknownBody`` (``NO_PAINTED_BODY``).
Fails on 85e4091cd in [1] (the text is PAINTED_NEEDED).
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


def outcome(fn):
    try:
        fn()
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="painted-body-running-unknown-") as tmp:
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
        from app.core import base_body
        base_body.is_base_pipeline = lambda *_a, **_k: False
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import artefact_graph as ag, figure, hub_ops, model_refs, outfit_bodies
        from app.core.task_queue import get_task_queue
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        def no_service(*a, **k):
            raise RuntimeError("the delete never calls the image service")
        service.get_image_service = no_service
        model_refs.schedule_outfit_render = lambda *a, **k: None
        get_task_queue()._started = True

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create demo", save_character_profile("demo", dict(human), create_new=True), True)
        piece = {"slots": ["top"], "covers": [], "outfit_types": ["casual"]}
        dress = inventory.add_item(name="Dress", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a green dress", outfit_piece=piece)["id"]
        inventory.add_to_inventory("demo", dress)
        inventory.equip_piece("demo", dress, source="smoke")
        W = model_refs.current_outfit_state("demo")[2]
        bsig = base_body.base_signature("demo")
        TK = figure.predicted_keys("demo", {"top": dress}, [], bsig=bsig)[1]
        TO = "tex000000000000"
        check("TK is a texture signature, not TO", (base_body.is_texture_signature(TK), TK != TO), (True, True))
        M = get_character_dir("demo") / "model3d"
        touch(M / f"{W}.glb")
        touch(M / f"{W}.json", {"pieces": {"top": dress}, "items": [], "texture_signature": TK})
        tex = {t: [touch(M / "texture" / f"{t}.glb", b"painted-" + t.encode()),
                   touch(M / "texture" / f"{t}.json", {"texture_signature": t, "base_signature": bsig})]
               for t in (TK, TO)}

        print("[1] what runs cannot be read")
        real = hub_ops.list_ops

        def broken(*_a, **_k):
            raise RuntimeError("hub operations unreadable")
        hub_ops.list_ops = broken
        try:
            got = outcome(lambda: outfit_bodies.delete_texture("demo", TO))
        finally:
            hub_ops.list_ops = real
        check("the true reason", got, "LookupError: " + ag.RUNNING_UNKNOWN + "hub operations")
        check("TO on disk", [p.exists() for p in tex[TO]], [True, True])

        print("[2] the normal path")
        check("TK still needed", outcome(lambda: outfit_bodies.delete_texture("demo", TK)),
              "LookupError: " + outfit_bodies.PAINTED_NEEDED)
        check("TK on disk", [p.exists() for p in tex[TK]], [True, True])
        check("TO deleted", outcome(lambda: outfit_bodies.delete_texture("demo", TO)), "ok")
        check("TO gone", [p.exists() for p in tex[TO]], [False, False])
        check("again: unknown", outcome(lambda: outfit_bodies.delete_texture("demo", TO)),
              "UnknownBody: " + outfit_bodies.NO_PAINTED_BODY)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
