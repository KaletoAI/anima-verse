"""The minor findings of the final review of plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` (Rulings
FR-minors and UI3c) that no other smoke covers.

Usage:
    ./.venv/bin/python scripts/smoke_figure_review_minors.py

Runs in a temp world (``paths.init(<tmp>)`` before any world-DB import), no
server process (routes through a bare FastAPI app), no hub, no network.

Expected, derived by hand from the rulings:
[1] M1 — the Figure tab's memo key (``figure_build._info_key``) stands for the
    worn hairstyle: profile {equipped_mesh_pieces {hair: H}, base_hairstyle
    H}, ``inventory.get_item`` a table; H's mode changed (an item edit) ->
    another key; an unrelated item U changed -> the same key. Old code
    (5eab1741): ``_info_key`` named neither ``equipped_mesh_pieces`` nor the
    base hairstyle.
[2] M4 — GET /characters/{c}/hairstyles is admin only like its sibling hair
    routes: with ``require_admin`` answering 403 -> 403; as admin -> 200.
    Old code (5eab1741): the route had no ``require_admin``.
[3] M5 — the hairstyle migration is done only when every character went
    through: two characters A and B, the hair migration's flag set;
    ``_migrate_hairstyle`` raising for B -> {A: "hA"}, the flag unset; the
    next call (no failure) -> {A: "hA", B: "hB"}, the flag set; a third ->
    None. The real ``_migrate_hairstyle`` of a character with the legacy
    key ``hair_method`` and ``save_character_profile`` answering False ->
    RuntimeError (a failure, not a silent "done").
[4] M3 — "Regenerate mesh" states its cost: ``_regenerate_jobs`` asks
    ``garments.run_estimate(…, from_step="mesh")`` (recorded) and answers
    its hub_jobs (4); an estimate that raises -> None.
[5] UI3c — ``figure_build._plain_jobs``: ``mesh_hub_stages`` a table
    [mesh, face, rig], the skin step off, BASE_VIEW_JOBS 1: no base model
    stored -> model_followup None; a stored base model -> {jobs 3, stages
    [mesh, face, rig]} (the model's rebuild a step that changes a view in
    place makes due); after_front 3 x 1 + 3 = 6 (a new front: the three
    other views and the model).
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "5eab1741"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def old_source(rel: str) -> str:
    return subprocess.run(["git", "show", f"{OLD}:{rel}"], cwd=ROOT, capture_output=True, text=True).stdout


def function_of(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.find("\ndef ", start + 1)
    return source[start:end if end > 0 else None]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-review-minors-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        from app.models.character import save_character_profile
        for name in ("A", "B"):
            check(f"create {name}", save_character_profile(name, {"template": "human-roleplay", "gender": "female",
                                                                   "age": 30, "height": 168}, create_new=True),
                  True)
        from app.core import figure_build
        from app.models import inventory

        print("[1] M1: the memo key stands for the worn hairstyle")
        items = {"H": {"id": "H", "garment": {"kind": "hair", "mesh_mode": "body"}},
                 "U": {"id": "U", "name": "unrelated"}}
        real_get_item = inventory.get_item
        inventory.get_item = lambda item_id, **_kw: copy.deepcopy(items.get(str(item_id)))
        try:
            profile = {"equipped_mesh_pieces": {"hair": "H"}, "base_hairstyle": "H"}
            before = figure_build._info_key("A", profile, {})
            items["U"]["name"] = "changed"
            check("an unrelated item: same key", figure_build._info_key("A", profile, {}), before)
            items["H"]["garment"]["mesh_mode"] = "hairdeck"
            check("the hairstyle's mode changed: another key", figure_build._info_key("A", profile, {}) != before,
                  True)
        finally:
            inventory.get_item = real_get_item
        old = function_of(old_source("app/core/figure_build.py"), "_info_key")
        check(f"{OLD}: the key named no hairstyle", ("equipped_mesh_pieces" in old, "BASE_HAIRSTYLE" in old),
              (False, False))

        print("[2] M4: the hairstyles list is admin only")
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        from app.routes import characters as routes
        app = FastAPI()
        app.include_router(routes.router)
        role = {"admin": False}

        def admin_only():
            if not role["admin"]:
                raise HTTPException(status_code=403, detail="Admin role required")
            return {"role": "admin"}
        app.dependency_overrides[require_admin] = admin_only
        with TestClient(app, raise_server_exceptions=False) as client:
            check("player: 403", client.get("/characters/A/hairstyles").status_code, 403)
            role["admin"] = True
            check("admin: 200", client.get("/characters/A/hairstyles").status_code, 200)
        old = function_of(old_source("app/routes/characters.py"), "get_character_hairstyles")
        check(f"{OLD}: no require_admin on the route", "require_admin" in old.split(")")[0], False)

        print("[3] M5: the hairstyle migration is done only when every character went through")
        from app.core import figure_migration as fm
        from app.core.hair_migration import HAIR_FLAG
        from app.models.world import get_world_setting, set_world_setting
        set_world_setting(HAIR_FLAG, "1")
        real_migrate = fm._migrate_hairstyle
        failing = {"B"}

        def migrate(name):
            if name in failing:
                raise RuntimeError("profile not saved (injected)")
            return f"h{name}", []
        fm._migrate_hairstyle = migrate
        try:
            check("B fails: A migrated", fm.migrate_hairstyles_once(), {"A": "hA"})
            check("B fails: flag unset", bool(get_world_setting(fm.HAIRSTYLE_FLAG)), False)
            failing.clear()
            check("next start: both", fm.migrate_hairstyles_once(), {"A": "hA", "B": "hB"})
            check("next start: flag set", bool(get_world_setting(fm.HAIRSTYLE_FLAG)), True)
            check("third call", fm.migrate_hairstyles_once(), None)
        finally:
            fm._migrate_hairstyle = real_migrate
        from app.models import character as character_model
        profile = dict(character_model.get_character_profile("A") or {}, hair_method="body")
        check("legacy key stored", save_character_profile("A", profile), True)
        real_save = character_model.save_character_profile
        character_model.save_character_profile = lambda *_a, **_kw: False
        try:
            fm._migrate_hairstyle("A")
            check("a profile not saved raises", "no error", "RuntimeError")
        except RuntimeError:
            check("a profile not saved raises", "RuntimeError", "RuntimeError")
        finally:
            character_model.save_character_profile = real_save

        print("[4] M3: Regenerate mesh states its cost")
        from app.core import garments
        asked = []
        real_estimate = garments.run_estimate
        garments.run_estimate = lambda c, item, **kw: asked.append((c, item, kw.get("from_step"))) or {"hub_jobs": 4}
        try:
            check("hub jobs", figure_build._regenerate_jobs("A", "jacket", {}), 4)
            check("asked from the mesh", asked, [("A", "jacket", figure_build.REGENERATE_STEP)])
            check("the step is the mesh", figure_build.REGENERATE_STEP, "mesh")

            def broken(*_a, **_kw):
                raise RuntimeError("x")
            garments.run_estimate = broken
            check("an estimate that raises", figure_build._regenerate_jobs("A", "jacket", {}), None)
        finally:
            garments.run_estimate = real_estimate

        print("[5] UI3c: the follow-up cost of a base step")
        from app.core import base_body, base_skin, model3d
        model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "face", "rig"]
        base_skin.enabled = lambda *_a, **_kw: False
        stored = {"path": None}
        model3d.find_model3d = lambda *_a, **_kw: stored["path"]
        jobs = figure_build._plain_jobs("A", "base0123abcd")
        check("no base model: no follow-up", jobs.get("model_followup"), None)
        check("after a new front", jobs.get("after_front"), 3 * base_body.BASE_VIEW_JOBS + 3)
        stored["path"] = root / "base.glb"
        check("a stored base model: its rebuild", figure_build._plain_jobs("A", "base0123abcd").get("model_followup"),
              {"jobs": 3, "stages": ["mesh", "face", "rig"]})

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
