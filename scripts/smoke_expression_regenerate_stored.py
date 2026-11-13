#!/usr/bin/env python3
"""The Expressions tab's per-image Regenerate re-renders exactly that file from its STORED inputs (Task UI2 gap 2 of
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md; rule R2 "a single step re-does its step even when current;
a step whose inputs are missing is disabled with the reason").

Usage:
    ./.venv/bin/python scripts/smoke_expression_regenerate_stored.py

Runs against a THROWAWAY storage + instance (``paths.init`` before any world-DB import; the pose/expression catalogs
copied into it) — no world, no GPU, no server. ``expression_regen.render_character_image`` is a stub that records
its call and writes an 8×8 PNG whose colour counts the renders, plus the sidecar the real renderer writes
(prompt, equipped_pieces, equipped_items).

Fixture: character "demo" (animal-default template, the "animal" set: default member "animal_neutral" = the outfit's BASE
image — the mood "neutral" resolves to it — "animal_relaxed" a member DERIVED from it); item "Demo coat" (slot top).

Expected, by hand from ``expression_regen``'s Regenerate block comment and ``_execute``:

[1] Renders of the current state: R = "neutral" wearing {top: coat} (a base image), X = "animal_relaxed" wearing
    {top: coat} (derived: its base R is cached, so one render). Then the character's CURRENT outfit is changed to
    nothing worn and its mood to "animal_relaxed" — neither may leak into a Regenerate.
[2] ``stored_snapshot(meta of R)`` → its stem == R's file stem, pieces (("top", coat),), items (), key "neutral",
    is_base True (key "animal_neutral"). ``regenerate_plan`` of R → ok, 1 job; of X → ok, 1 job (base cached); with R's files moved
    away → X: ok, 2 jobs, base_first True; moved back.
[3] ``regenerate_stored("demo", R.name)`` → one render whose ``equipped_pieces`` are {top: coat} (the stored ones,
    not the current {}) and ``expression_prompt`` the "animal_neutral" member's prompt; the attempt ends "ready"; the file
    keeps its NAME and its bytes change (render counter 3 → a new colour); X, edited from the old base, is
    dropped (``_drop_stale_derived`` — the tab's "the expressions edited from it render again when used").
[4] Refusals with the reasons the tab shows: a sidecar without schema 2 (a legacy image) → REGEN_NO_INPUTS; a stored
    set that does not exist → REGEN_NOT_CURRENT; a stored ``outfit_raw`` that the pieces no longer give (identity
    differs) → REGEN_NOT_CURRENT; R copied under another name with its sidecar → REGEN_OLD_NAME; a missing file →
    LookupError.
[5] ``expression_cleanup.inventory`` (the tab's list): R carries ``regenerate`` {ok True, jobs 1}; the legacy
    copy {ok False, reason REGEN_NO_INPUTS} (whatever the cleanup calls it); the renamed copy (adopt or redundant)
    is not ok.
[6] Route POST /characters/demo/expressions/{file}/regenerate (``require_admin`` overridden): R → 202 or 200 with the
    attempt; the legacy file → 409 with REGEN_NO_INPUTS as detail; an unknown file → 404.

Fails on 55a2a478: AttributeError — module ``expression_regen`` has no attribute ``stored_snapshot``.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-regen-")
STORAGE = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()
from app.core import pose_catalog as pc  # noqa: E402
catalog_paths = {}
for axis in ("pose", "expression"):
    target = STORAGE / f"{axis}.json"
    shutil.copyfile(pc.catalog_path(axis), target)
    catalog_paths[axis] = target
pc.catalog_path = lambda axis: catalog_paths[axis]
pc.reload_catalogs()
from app.core.expression_sets_migration import migrate_catalog_metadata  # noqa: E402
migrate_catalog_metadata()

from PIL import Image  # noqa: E402
from app.core import expression_regen as er  # noqa: E402
from app.core.expression_cleanup import inventory  # noqa: E402
from app.core.expression_sets import catalog_snapshot  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.inventory import add_item, add_to_inventory, equip_piece  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


assert save_character_profile("demo", {"template": "animal-default", "species": "cat",
                                       "character_appearance": "a brown cat"}, create_new=True)
coat = add_item(name="Demo coat", category="outfit_piece", prompt_fragment="a linen coat",
                outfit_piece={"slots": ["top"]})["id"]
calls = []
renders = [0]


def render(character, *, output_stem, **kwargs):
    calls.append(kwargs)
    renders[0] += 1
    p = output_stem.with_suffix(".png")
    Image.new("RGB", (8, 8), (10 * renders[0], 80, 120)).save(p)
    p.with_suffix(".json").write_text(json.dumps({"prompt": kwargs["expression_prompt"],
                                                  "equipped_pieces": kwargs["equipped_pieces"],
                                                  "equipped_items": kwargs["equipped_items"]}))
    return p


def meta_of(path):
    return json.loads(path.with_suffix(".json").read_text())


def wait(attempt):
    for _ in range(500):
        current = er.get_expression_attempt("demo", attempt.attempt_id)
        if current.state not in ("pending", "running"):
            return current
        time.sleep(0.01)
    return er.get_expression_attempt("demo", attempt.attempt_id)


cat = catalog_snapshot()
spec = cat.sets["animal"]
check("[0] the animal set's default member", spec.default, "animal_neutral")
check("[0] animal_relaxed is a member", "animal_relaxed" in spec.members)

with patch.object(er, "render_character_image", render):
    # [1]
    worn = {"top": coat}
    R = er.generate_expression_image(er.expression_snapshot("demo", "neutral", equipped_pieces=worn, equipped_items=[]))
    X = er.generate_expression_image(er.expression_snapshot("demo", "animal_relaxed", equipped_pieces=worn,
                                                            equipped_items=[]))
    check("[1] two renders (X edited from the cached R)", len(calls), 2)
    check("[1] the current outfit stays empty", add_to_inventory("demo", coat), True)
    from app.models.character import save_character_current_feeling
    save_character_current_feeling("demo", "animal_relaxed")

    # [2]
    request, reason = er.stored_snapshot("demo", meta_of(R))
    check("[2] stored request of R", [reason, request.stem if request else None, request.pieces if request else None,
                                      request.items if request else None, request.expression_key if request else None,
                                      request.is_base if request else None],
          ["", R.stem, (("top", coat),), (), "animal_neutral", True])
    check("[2] plan R", er.regenerate_plan("demo", meta_of(R), file_stem=R.stem),
          {"ok": True, "reason": "", "jobs": 1, "base_first": False})
    check("[2] plan X (base cached)", er.regenerate_plan("demo", meta_of(X), file_stem=X.stem),
          {"ok": True, "reason": "", "jobs": 1, "base_first": False})
    away = STORAGE / "away"
    away.mkdir()
    for p in (R, R.with_suffix(".json")):
        shutil.move(str(p), away / p.name)
    check("[2] plan X without its base", er.regenerate_plan("demo", meta_of(X), file_stem=X.stem),
          {"ok": True, "reason": "", "jobs": 2, "base_first": True})
    for p in away.iterdir():
        shutil.move(str(p), R.parent / p.name)

    # [3]
    before = R.read_bytes()
    calls.clear()
    attempt = wait(er.regenerate_stored("demo", R.name))
    check("[3] ready", attempt.state, "ready")
    check("[3] one render", len(calls), 1)
    check("[3] the stored pieces, not the current ones", calls[0]["equipped_pieces"] if calls else None, worn)
    check("[3] the stored member's prompt", calls[0]["expression_prompt"] if calls else None,
          cat.entries["animal_neutral"]["prompt"])
    check("[3] same file name", R.is_file() and meta_of(R).get("identity") == R.stem)
    check("[3] new bytes", R.read_bytes() != before)
    check("[3] X, edited from the old base, is dropped (renders again when used)", X.exists(), False)

    # [4]
    folder = R.parent
    legacy = folder / "demo_legacy.png"
    shutil.copy2(R, legacy)
    legacy.with_suffix(".json").write_text(json.dumps({"expression_key": "neutral", "equipped_pieces": {},
                                                       "equipped_items": []}))
    try:
        er.regenerate_stored("demo", legacy.name)
        check("[4] legacy refused", False)
    except ValueError as exc:
        check("[4] legacy refused", str(exc), er.REGEN_NO_INPUTS)
    check("[4] unknown set", er.stored_snapshot("demo", {**meta_of(R), "expression_set": "nope"})[1],
          er.REGEN_NOT_CURRENT)
    check("[4] outfit_raw the pieces no longer give", er.stored_snapshot(
        "demo", {**meta_of(R), "equipped_pieces": {}})[1], er.REGEN_NOT_CURRENT)
    renamed = folder / "demo_renamed.png"
    shutil.copy2(R, renamed)
    shutil.copy2(R.with_suffix(".json"), renamed.with_suffix(".json"))
    try:
        er.regenerate_stored("demo", renamed.name)
        check("[4] renamed refused", False)
    except ValueError as exc:
        check("[4] renamed refused", str(exc), er.REGEN_OLD_NAME)
    try:
        er.regenerate_stored("demo", "demo_missing.png")
        check("[4] missing file", False)
    except LookupError:
        check("[4] missing file", True)

    # [5]
    rows = {row["file"]: row.get("regenerate") for row in inventory("demo")}
    check("[5] R", rows.get(R.name), {"ok": True, "reason": "", "jobs": 1, "base_first": False})
    check("[5] legacy", (rows.get(legacy.name) or {}).get("reason"), er.REGEN_NO_INPUTS)
    check("[5] renamed copy not ok", (rows.get(renamed.name) or {}).get("ok"), False)

    # [6]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth_dependency import require_admin
    from app.routes import characters as characters_route
    app = FastAPI()
    app.include_router(characters_route.router)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    client = TestClient(app)
    r = client.post(f"/characters/demo/expressions/{R.name}/regenerate")
    check("[6] R accepted", r.status_code in (200, 202) and r.json().get("identity") == R.stem)
    if r.status_code == 202:
        wait(er.get_expression_attempt("demo", r.json()["attempt_id"]))
    r = client.post(f"/characters/demo/expressions/{legacy.name}/regenerate")
    check("[6] legacy → 409", [r.status_code, r.json().get("detail")], [409, er.REGEN_NO_INPUTS])
    r = client.post("/characters/demo/expressions/demo_missing.png/regenerate")
    check("[6] unknown → 404", r.status_code, 404)

print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
