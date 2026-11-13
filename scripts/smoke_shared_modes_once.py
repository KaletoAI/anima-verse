"""The shared item library's half of the worn-piece mode migration runs once per
INSTALLATION, not once per world (Ruling FR-C1 of the final review of plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``;
``app/core/figure_migration.py`` ``migrate_modes_once`` / ``shared_modes_done``).

Usage:
    ./.venv/bin/python scripts/smoke_shared_modes_once.py

Runs in temp worlds that share ONE temp shared items file
(``inventory._get_shared_items_file`` redirected), ``paths.init(<tmp>)`` before
any world-DB import; the tracked ``shared/items/items.json`` is never read or
written. No server, no hub, no network.

The rule, derived by hand: the world's items and profiles are judged once per
world (world_kv ``migrated_worn_piece_modes``); the shared library once — its
marker ``migrated_worn_piece_modes`` is a top-level key of the shared items
file, written in the same write as the judged items, and the shared re-default's
marker ``redefaulted_unworn_piece_modes`` counts as done too. Judgement (ruling
4): a stored mode is kept; else ``own_mesh`` flag → own_mesh; worn and every
wearer's stored ``outfit_body_mode`` is "mesh" → in_body; else painted.

Shared file at the start: ``{items: [U, W], note: "keep me"}``,
    U  top, no mode, unworn everywhere
    W  top, no mode, worn by world 1's tester T (no outfit_body_mode)
World 1: T (template human-roleplay, stored ``model_pipeline: base_body`` → a
test character for the re-default) wears W.
[1] migrate_modes_once() in world 1: items == {U: painted, W: painted} (both
    rule 4); the shared file now has ``migrated_worn_piece_modes`` and still
    ``note: "keep me"``.
[2] redefault_modes_once() in world 1: U loses its mode (no tester uses it), W
    keeps painted (T wears it); the shared file has both markers.
[3] World 2 (new storage, SAME shared file): M ``outfit_body_mode: "mesh"``
    wears U. Without FR-C1 the shared half re-judged U → in_body (M is the only
    wearer and wears it as "mesh"). Now: result items == {} (world 2 has no
    items of its own), the shared file BYTES are identical, U has no mode, the
    world 2 flag is set and M lost its ``outfit_body_mode``.
[4] Legacy file (what an installation migrated before FR-C1 holds): a fresh
    shared file with ONLY the re-default marker and U without a mode; world 3
    with M3 "mesh" wearing U: bytes identical, U has no mode.
[5] The halves run on their own markers: world 4 with a fresh shared file
    {V top, no mode, unworn} whose save RAISES once — the world flag is set,
    the shared marker is not, V has no mode; the next call (save works again)
    judges V → painted and writes the marker; a third call returns None.
[6] Fails on the old code: at commit 5eab1741 ``figure_migration.py`` has no
    ``SHARED_MODES_KEY`` (no installation marker existed).
"""
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


def reset_connections():
    from app.core import db
    for conn in list(db._connections.values()):
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    db._connections.clear()


def open_world(path: Path):
    from app.core import paths
    paths.init(path)
    reset_connections()
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    from app.core import config, db
    config.load(paths.get_config_path(), instance_path=path.parent / "instance" / "config.json")
    db.init_schema()
    from app.core.motion_item_cache import invalidate
    invalidate()


def character(name: str, extra: dict, pieces: dict):
    from app.models.character import save_character_profile
    profile = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
               "equipped_pieces": dict(pieces), **extra}
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)


def stored_profile(name: str) -> dict:
    from app.core import db
    row = db.get_connection().execute("SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
    return json.loads(row[0] or "{}") if row else {}


def shared_mode(path: Path, item_id: str):
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data["items"]:
        if item["id"] == item_id:
            return (item.get("outfit_piece") or {}).get("mesh_mode")
    raise KeyError(item_id)


def write_shared(path: Path, items: list, **meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items, **meta}, indent=2), encoding="utf-8")


def piece(item_id: str) -> dict:
    return {"id": item_id, "name": item_id, "category": "outfit_piece", "outfit_piece": {"slots": ["top"]}}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="shared-modes-once-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world1")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        open_world(root / "world1")
        from app.models import inventory
        shared = {"file": root / "shared" / "items" / "items.json"}
        inventory._get_shared_items_file = lambda: shared["file"]
        write_shared(shared["file"], [piece("U"), piece("W")], note="keep me")
        from app.core import figure_migration as fm
        from app.models.world import get_world_setting

        print("[1] world 1: the shared half runs and writes its marker")
        character("T", {"model_pipeline": "base_body"}, {"top": "W"})
        result = fm.migrate_modes_once()
        check("world 1 items", (result or {}).get("items"), {"U": "painted", "W": "painted"})
        meta = inventory.get_shared_items_meta(strict=True)
        check("shared marker written", bool(meta.get(fm.SHARED_MODES_KEY)), True)
        check("library meta kept", meta.get("note"), "keep me")
        check("shared_modes_done", fm.shared_modes_done(), True)

        print("[2] world 1: the re-default clears the untested shared piece")
        fm.redefault_modes_once()
        check("U cleared", shared_mode(shared["file"], "U"), None)
        check("W kept", shared_mode(shared["file"], "W"), "painted")
        meta = inventory.get_shared_items_meta(strict=True)
        check("both markers", (bool(meta.get(fm.SHARED_MODES_KEY)), bool(meta.get(fm.SHARED_REDEFAULT_KEY))),
              (True, True))

        print("[3] world 2 on the same shared file: the library is not judged again")
        os.environ["STORAGE_DIR"] = str(root / "world2")
        open_world(root / "world2")
        character("M", {"outfit_body_mode": "mesh"}, {"top": "U"})
        before = shared["file"].read_bytes()
        result = fm.migrate_modes_once()
        check("world 2 items", (result or {}).get("items"), {})
        check("shared bytes identical", shared["file"].read_bytes() == before, True)
        check("U still without a mode", shared_mode(shared["file"], "U"), None)
        check("world 2 flag set", bool(get_world_setting(fm.FLAG, strict=True)), True)
        check("M lost outfit_body_mode", "outfit_body_mode" in stored_profile("M"), False)
        check("second call in world 2", fm.migrate_modes_once(), None)

        print("[4] a legacy file with only the re-default marker counts as done")
        shared["file"] = root / "legacy" / "items.json"
        write_shared(shared["file"], [piece("U")], **{fm.SHARED_REDEFAULT_KEY: "2026-01-01T00:00:00+00:00"})
        os.environ["STORAGE_DIR"] = str(root / "world3")
        open_world(root / "world3")
        character("M3", {"outfit_body_mode": "mesh"}, {"top": "U"})
        before = shared["file"].read_bytes()
        result = fm.migrate_modes_once()
        check("world 3 items", (result or {}).get("items"), {})
        check("legacy bytes identical", shared["file"].read_bytes() == before, True)
        check("legacy U without a mode", shared_mode(shared["file"], "U"), None)

        print("[5] the shared half retries on its own marker after a failed write")
        shared["file"] = root / "fresh" / "items.json"
        write_shared(shared["file"], [piece("V")])
        os.environ["STORAGE_DIR"] = str(root / "world4")
        open_world(root / "world4")
        real_save = inventory._save_shared_items

        def failing_save(*_a, **_k):
            raise OSError("disk full (injected)")
        inventory._save_shared_items = failing_save
        try:
            result = fm.migrate_modes_once()
        finally:
            inventory._save_shared_items = real_save
        check("failed: shared not judged", (result or {}).get("items"), {})
        check("failed: world flag set", bool(get_world_setting(fm.FLAG, strict=True)), True)
        check("failed: shared marker unset", fm.shared_modes_done(), False)
        check("failed: V without a mode", shared_mode(shared["file"], "V"), None)
        result = fm.migrate_modes_once()
        check("retry: V judged", (result or {}).get("items"), {"V": "painted"})
        check("retry: no profile step again", (result or {}).get("profiles"), [])
        check("retry: marker written", fm.shared_modes_done(), True)
        check("third call", fm.migrate_modes_once(), None)

    print("[6] fails on the old code")
    old = subprocess.run(["git", "show", f"{OLD}:app/core/figure_migration.py"], cwd=ROOT,
                         capture_output=True, text=True)
    check(f"old code readable at {OLD}", old.returncode, 0)
    check(f"no SHARED_MODES_KEY at {OLD}", "SHARED_MODES_KEY" in old.stdout, False)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
