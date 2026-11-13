"""The "Use base body pipeline" switch is gone: every humanoid is on the
base-body pipeline, the route and the ``model_pipeline`` profile key leave
(plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``, Task 11h,
Ruling A13; ``app/core/figure_migration.py`` "The removed ... switch").

Usage:
    ./.venv/bin/python scripts/smoke_pipeline_switch_removed.py

Runs in temp worlds (``paths.init(<tmp>)`` before any world-DB import); the
shared item library is redirected to temp files
(``inventory._get_shared_items_file``), so the tracked
``shared/items/items.json`` is never read or written. No server, no hub.

Expected values, derived by hand from Ruling A13 and the ordering rule (the
re-default of Rulings A10 / A12 reads the STORED key to find the test
characters, so the key may only go once the re-default is done):

[1] Predicate: ``base_body.is_base_pipeline`` with a human-roleplay profile
    and no key -> True; the same with a stale ``model_pipeline: "base_body"``
    -> True; an animal-default profile -> False, with the stale key too ->
    False; an npc-temporary profile (template feature ``temporary_npc``,
    humanoid) -> False, with the stale key too -> False (Ruling A13a: a
    temporary NPC keeps the direct T-pose path that ``npc_assets`` finishes
    it with); the stored temporary NPC Tmp -> False through its stored
    profile as well. ``base_body`` has no ``set_pipeline`` any more.
[2] World 1 never booted since the re-default landed: the mode migration's
    flag is set, the re-default's world flag is NOT. Characters: T (humanoid,
    key "base_body", wears the shared piece K [painted]), N (humanoid, no
    key), A (animal-default, key "base_body"). World item U [painted],
    unworn.
    (a) ``drop_pipeline_key_once`` FIRST -> None: T and A keep their key, the
        flag ``dropped_model_pipeline_key`` stays unset, one INFO line
        "Pipeline switch removal waits ... the world's mode re-default has not
        run yet".
    (b) ``redefault_modes_once`` -> cleared {U: painted}, kept {K: painted}
        (T is found as a test character through its stored key).
    (c) ``drop_pipeline_key_once`` -> {A: "base_body", T: "base_body"}; the
        key is gone from T and A, N's profile is unchanged, the flag is set;
        exactly ONE INFO line "Pipeline switch removed: profile key
        model_pipeline dropped from 2 character(s): A (base_body), T
        (base_body) — every humanoid is on the base-body pipeline, nothing
        rebuilt". After it: T and N on the pipeline (humanoids, no key), A
        not; ``_tested_pieces`` finds no tester any more — which is why the
        drop must wait (run first, it would have hidden T and K would have
        been cleared). K keeps painted.
    (d) A second call -> None, no log line, the profiles unchanged.
[3] World 2: re-default world flag set, shared marker NOT set, a tester T2
    (key "base_body") -> the drop waits (None, T2 keeps the key) and the log
    names "the shared library's mode re-default still needs this world's test
    characters (T2)". Once the shared file carries the marker
    ``redefaulted_unworn_piece_modes`` -> {T2: "base_body"}.
[4] World 3 without any tester, the shared marker NOT set, an animal A3 with
    the stale key: nothing to wait for (this world has nothing to give the
    shared re-default) -> {A3: "base_body"}.
[5] The route is gone: no route of ``app.routes.characters.router`` has the
    path ``/characters/{character_name}/base-body/pipeline``; POST
    /characters/T/base-body/pipeline on a bare app with that router answers
    404 or 405 (no handler). ``character_ops`` no longer names
    ``model_pipeline``; ``FieldFigure.tsx`` no longer posts
    ``base-body/pipeline``.
[6] Wiring and the old code: ``app/server.py`` calls
    ``drop_pipeline_key_once()`` AFTER ``redefault_modes_once()``; at
    ff011edf (this task's BASE) ``app/routes/characters.py`` still had the
    route and ``base_body.is_base_pipeline`` read ``model_pipeline``.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "ff011edf"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def reset_connections():
    from app.core import db
    for conn in list(db._connections.values()):
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    db._connections.clear()


def open_world(path: Path, shared_file: Path):
    os.environ["STORAGE_DIR"] = str(path)
    from app.core import paths
    paths.init(path)
    reset_connections()
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    from app.core import config, db
    config.load(paths.get_config_path(), instance_path=path.parent / "instance" / "config.json")
    db.init_schema()
    from app.models import inventory
    inventory._get_shared_items_file = lambda: shared_file
    from app.core.motion_item_cache import invalidate
    invalidate()


def raw_piece(item_id: str, piece: dict):
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, 'outfit_piece', '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, item_id, json.dumps(piece)))
    from app.core.motion_item_cache import invalidate
    invalidate()


def shared(path: Path, items: list, **meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": [{"id": i, "name": i, "category": "outfit_piece", "outfit_piece": p}
                                          for i, p in items], **meta}, indent=2), encoding="utf-8")
    from app.core.motion_item_cache import invalidate
    invalidate()


def character(name: str, pieces: dict, *, key: bool, template: str = "human-roleplay"):
    from app.models.character import save_character_profile
    profile = {"template": template, "gender": "female", "age": 30, "height": 168, "equipped_pieces": dict(pieces)}
    if key:
        profile["model_pipeline"] = "base_body"
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pipeline-switch-") as tmp:
        root = Path(tmp)
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        shared1 = root / "shared1" / "items.json"
        shared(shared1, [("K", {"slots": ["top"], "mesh_mode": "painted"})])
        open_world(root / "world1", shared1)
        from app.core import base_body
        from app.core import figure_migration as fm
        from app.models.character import get_character_profile, list_available_characters, save_character_profile
        from app.models.world import get_world_setting, set_world_setting
        log = Lines()
        fm.logger.addHandler(log)
        fm.logger.setLevel(logging.INFO)

        print("[1] every humanoid is on the pipeline")
        human = {"template": "human-roleplay", "gender": "female", "age": 30}
        animal = {"template": "animal-default"}
        check("humanoid, no key", base_body.is_base_pipeline("x", profile=human), True)
        check("humanoid, stale key", base_body.is_base_pipeline("x", profile=dict(human, model_pipeline="base_body")),
              True)
        check("animal", base_body.is_base_pipeline("x", profile=animal), False)
        check("animal, stale key", base_body.is_base_pipeline("x", profile=dict(animal, model_pipeline="base_body")),
              False)
        npc = {"template": "npc-temporary", "gender": "female"}
        from app.core.model_refs import is_humanoid
        check("npc-temporary is humanoid (why it needs the exclusion)", is_humanoid("x", profile=npc), True)
        check("temporary NPC", base_body.is_base_pipeline("x", profile=npc), False)
        check("temporary NPC, stale key", base_body.is_base_pipeline("x", profile=dict(npc, model_pipeline="base_body")),
              False)
        check("create Tmp", save_character_profile("Tmp", dict(npc), create_new=True), True)
        check("stored temporary NPC", base_body.is_base_pipeline("Tmp"), False)
        check("no set_pipeline", hasattr(base_body, "set_pipeline"), False)

        print("[2] the drop waits for the re-default (a world that never booted since it landed)")
        raw_piece("U", {"slots": ["outer"], "mesh_mode": "painted"})
        character("T", {"top": "K"}, key=True)
        character("N", {}, key=False)
        character("A", {}, key=True, template="animal-default")
        set_world_setting(fm.FLAG, "1")
        n_before = get_character_profile("N")
        log.lines.clear()
        check("(a) drop first", fm.drop_pipeline_key_once(), None)
        check("(a) T keeps the key", get_character_profile("T").get("model_pipeline"), "base_body")
        check("(a) A keeps the key", get_character_profile("A").get("model_pipeline"), "base_body")
        check("(a) flag unset", get_world_setting(fm.PIPELINE_KEY_FLAG), "")
        check("(a) one waits line", [ln for ln in log.lines if ln.startswith("Pipeline switch")],
              ["Pipeline switch removal waits (retried at the next start): the world's mode re-default has not "
               "run yet"])
        result = fm.redefault_modes_once() or {}
        check("(b) re-default cleared", result.get("cleared"), {"U": "painted"})
        check("(b) re-default kept K for the tester T", result.get("kept"), {"K": "painted"})
        log.lines.clear()
        check("(c) drop", fm.drop_pipeline_key_once(), {"A": "base_body", "T": "base_body"})
        check("(c) T without the key", "model_pipeline" in get_character_profile("T"), False)
        check("(c) A without the key", "model_pipeline" in get_character_profile("A"), False)
        check("(c) N unchanged", get_character_profile("N"), n_before)
        check("(c) T still wears K", get_character_profile("T").get("equipped_pieces"), {"top": "K"})
        check("(c) flag set", get_world_setting(fm.PIPELINE_KEY_FLAG), "1")
        check("(c) exactly one log line", [ln for ln in log.lines if "model_pipeline" in ln or "Pipeline" in ln],
              ["Pipeline switch removed: profile key model_pipeline dropped from 2 character(s): A (base_body), "
               "T (base_body) — every humanoid is on the base-body pipeline, nothing rebuilt"])
        check("(c) T on the pipeline", base_body.is_base_pipeline("T"), True)
        check("(c) N on the pipeline", base_body.is_base_pipeline("N"), True)
        check("(c) A off the pipeline", base_body.is_base_pipeline("A"), False)
        names = list_available_characters(include_pooled=True, include_dormant=True)
        check("(c) no tester left — why the drop must wait", fm._tested_pieces(names)[0], [])
        from app.models import inventory
        check("(c) K keeps painted", ((inventory.get_item("K") or {}).get("outfit_piece") or {}).get("mesh_mode"),
              "painted")
        profiles = {n: get_character_profile(n) for n in ("T", "N", "A")}
        log.lines.clear()
        check("(d) second call", fm.drop_pipeline_key_once(), None)
        check("(d) no log line", log.lines, [])
        check("(d) profiles unchanged", {n: get_character_profile(n) for n in ("T", "N", "A")}, profiles)

        print("[3] the shared re-default still needs this world's tester")
        shared2 = root / "shared2" / "items.json"
        shared(shared2, [])
        open_world(root / "world2", shared2)
        character("T2", {}, key=True)
        set_world_setting(fm.FLAG, "1")
        set_world_setting(fm.REDEFAULT_FLAG, "1")
        log.lines.clear()
        check("waits", fm.drop_pipeline_key_once(), None)
        check("T2 keeps the key", get_character_profile("T2").get("model_pipeline"), "base_body")
        check("the waits line names T2", log.lines,
              ["Pipeline switch removal waits (retried at the next start): the shared library's mode re-default "
               "still needs this world's test characters (T2)"])
        shared(shared2, [], **{fm.SHARED_REDEFAULT_KEY: "2026-11-13T00:00:00+00:00"})
        check("runs once the shared marker is set", fm.drop_pipeline_key_once(), {"T2": "base_body"})

        print("[4] a world without testers does not wait for the shared library")
        shared3 = root / "shared3" / "items.json"
        shared(shared3, [])
        open_world(root / "world3", shared3)
        character("A3", {}, key=True, template="animal-default")
        set_world_setting(fm.FLAG, "1")
        set_world_setting(fm.REDEFAULT_FLAG, "1")
        check("runs", fm.drop_pipeline_key_once(), {"A3": "base_body"})

        print("[5] the route is gone")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        paths_ = sorted(getattr(r, "path", "") for r in router.routes)
        check("no pipeline route", [p for p in paths_ if p.endswith("/base-body/pipeline")], [])
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            status = client.post("/characters/T/base-body/pipeline", json={"enabled": True}).status_code
        check("POST answers 404/405", status in (404, 405), True)
        check("character_ops names no model_pipeline",
              "model_pipeline" in (ROOT / "app/core/character_ops.py").read_text(encoding="utf-8"), False)
        check("FieldFigure posts no base-body/pipeline", "base-body/pipeline" in (
            ROOT / "frontend/src/tabs/characters/FieldFigure.tsx").read_text(encoding="utf-8"), False)

        print("[6] wiring and the old code")
        server = (ROOT / "app/server.py").read_text(encoding="utf-8")
        a, b = server.find("redefault_modes_once()"), server.find("drop_pipeline_key_once()")
        check("server: drop after the re-default", 0 < a < b, True)
        old = git("show", f"{BASE}:app/routes/characters.py").stdout
        check(f"{BASE}: the route existed", '"/{character_name}/base-body/pipeline"' in old, True)
        old_bb = git("show", f"{BASE}:app/core/base_body.py").stdout
        check(f"{BASE}: the predicate read the key", 'profile.get("model_pipeline") != "base_body"' in old_bb, True)
        fm.logger.removeHandler(log)
        reset_connections()

    print("\nALL OK" if not FAILS else f"\nFAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
