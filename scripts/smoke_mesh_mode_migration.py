"""The one-time boot migration of the worn-piece modes (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 3,
builder-check ruling 4): every stored outfit piece gets its
``outfit_piece.mesh_mode``, the per-item ``own_mesh`` flag and the
per-character ``outfit_body_mode`` leave the data.

Usage:
    ./.venv/bin/python scripts/smoke_mesh_mode_migration.py

Runs in temp worlds; the shared item library is redirected to a temp file
(``inventory._get_shared_items_file``), so the tracked
``shared/items/items.json`` is never read or written.

Expected values, derived from the rule (ruling 4), in this order: an item that
already carries a valid ``mesh_mode`` -> untouched; ``own_mesh`` true ->
``own_mesh``; worn (``equipped_pieces``) by at least one character and EVERY
wearer's stored profile ``outfit_body_mode`` is ``"mesh"`` -> ``in_body``;
else -> ``painted``. The wearers' value is the STORED profile key, not the
derived ``base_body.outfit_body_mode``. Fixtures are chosen so that the kind
default (``garment_set.default_mesh_mode``) disagrees with the rule wherever
it can:

World 1 characters (all stored with template human-roleplay):
    R  outfit_body_mode "retexture"
    M1 outfit_body_mode "mesh"
    M2 outfit_body_mode "mesh", status dormant (must still count)
    P  no outfit_body_mode key, status pooled (must still count)
Items (``{slots}`` as stored, without a mode unless named):
    A  world,  top,   own_mesh true,  worn by R        -> own_mesh (rule 2)
    B  shared, top,                   worn by M1, M2   -> in_body (rule 3;
       the kind default and the DERIVED mode of M1/M2 would say painted)
    C  shared, outer,                 worn by M1, R    -> painted (R is no
       mesh wearer; the kind default would say in_body)
    D  world,  outer,                 unworn           -> painted (default
       would say in_body)
    G  world,  top,                   worn by M1, P    -> painted (pooled P
       has no "mesh"; leaving P out would give in_body)
    E  shared, top, mesh_mode in_body, own_mesh true, worn by R
                                                       -> in_body, untouched
       (rule 1 before rule 2: the flag would say own_mesh)
    T  world,  a tool (no outfit piece)                -> no outfit_piece
[1] migrate_modes_once() returns items {A: own_mesh, B: in_body, C: painted,
    D: painted, G: painted} (E not judged), the stored modes match, E keeps
    in_body, NO item (world or shared) has an ``own_mesh`` key, T has no
    outfit_piece. judge_item directly: ({own_mesh true}, []) -> own_mesh;
    ({}, ["mesh","mesh"]) -> in_body; ({}, ["mesh", None]) -> painted;
    ({}, []) -> painted; ({mesh_mode painted, own_mesh true}, ["mesh"]) ->
    painted.
[2] profiles == [M1, M2, R] (sorted; P had no key); no stored profile_json
    and no get_character_profile has ``outfit_body_mode``; equipped_pieces
    unchanged.
[3] the world_kv flag ``migrated_worn_piece_modes`` is set; a second call
    returns None and changes nothing: the shared items file bytes, the
    ``items`` rows and the ``characters`` rows are identical.
[4] World 2 (new temp storage, SAME shared file, flag unset): M3 "mesh"
    wears B, C and a new world item F (top, no mode) alone; R3 "retexture"
    wears E. Result: items == {F: in_body}; B stays
    in_body, C stays painted (M3 alone would make it in_body if re-judged),
    E stays in_body; profiles == [M3, R3].
[5] update_item no longer carries a stored ``own_mesh`` through: a legacy
    item stored RAW as {slots [top], own_mesh true} (no mode) loses the key
    on a name update and still has no mode.
[6] Fails on the old code: ``app/core/figure_migration.py`` does not exist
    at BASE 2f1c2a94, whose inventory.py still carries the flag through
    (``prev_own_mesh_stored``); app/server.py calls migrate_modes_once
    after delete_all_hair_once and before the refit sweep.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "2f1c2a94"
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


def open_world(path: Path):
    from app.core import paths
    paths.init(path)
    reset_connections()
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    from app.core import config, db
    config.load(paths.get_config_path(), instance_path=path.parent / "instance" / "config.json")
    db.init_schema()


def raw_piece(item_id: str, piece: dict, *, category: str = "outfit_piece", name: str = ""):
    """A world item row written RAW (no normalisation: no mode, a flag)."""
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, ?, '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, name or item_id, category, json.dumps(piece)))
    from app.core.motion_item_cache import invalidate
    invalidate()


def character(name: str, mode, pieces: dict, status: str = ""):
    from app.core import db
    from app.models.character import save_character_profile
    profile = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
               "equipped_pieces": dict(pieces)}
    if mode is not None:
        profile["outfit_body_mode"] = mode
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)
    if status:
        with db.transaction() as conn:
            conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))


def stored_profile(name: str) -> dict:
    from app.core import db
    row = db.get_connection().execute("SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
    return json.loads(row[0] or "{}") if row else {}


def rows(table: str):
    from app.core import db
    return db.get_connection().execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def piece_of(item_id: str) -> dict:
    from app.models import inventory
    item = inventory.get_item(item_id) or {}
    return item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mesh-mode-migration-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world1")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        open_world(root / "world1")
        from app.models import inventory
        shared_file = root / "shared" / "items" / "items.json"
        shared_file.parent.mkdir(parents=True)
        inventory._get_shared_items_file = lambda: shared_file
        shared_file.write_text(json.dumps({"items": [
            {"id": "B", "name": "B", "category": "outfit_piece", "outfit_piece": {"slots": ["top"]}},
            {"id": "C", "name": "C", "category": "outfit_piece", "outfit_piece": {"slots": ["outer"]}},
            {"id": "E", "name": "E", "category": "outfit_piece",
             "outfit_piece": {"slots": ["top"], "mesh_mode": "in_body", "own_mesh": True}},
        ]}, indent=2), encoding="utf-8")
        raw_piece("A", {"slots": ["top"], "own_mesh": True})
        raw_piece("D", {"slots": ["outer"]})
        raw_piece("G", {"slots": ["top"]})
        raw_piece("T", {}, category="tool")
        character("R", "retexture", {"top": "A", "outer": "C", "neck": "E"})
        character("M1", "mesh", {"top": "B", "outer": "C", "legs": "G"})
        character("M2", "mesh", {"top": "B"}, status="dormant")
        character("P", None, {"top": "G"}, status="pooled")
        check("fixture: shared B readable", inventory.is_shared_item("B"), True)
        check("fixture: A stored raw", piece_of("A"), {"slots": ["top"], "own_mesh": True})

        from app.core import figure_migration as fm
        from app.core import garment_set
        print("[1] items")
        j = fm.judge_item
        op = lambda p: {"category": "outfit_piece", "outfit_piece": p}  # noqa: E731
        check("judge own_mesh flag", j(op({"slots": ["top"], "own_mesh": True}), []), "own_mesh")
        check("judge all mesh", j(op({"slots": ["top"]}), ["mesh", "mesh"]), "in_body")
        check("judge one non-mesh", j(op({"slots": ["top"]}), ["mesh", None]), "painted")
        check("judge unworn", j(op({"slots": ["outer"]}), []), "painted")
        check("judge mode kept", j(op({"slots": ["top"], "mesh_mode": "painted", "own_mesh": True}), ["mesh"]),
              "painted")
        result = fm.migrate_modes_once()
        check("result items", (result or {}).get("items"),
              {"A": "own_mesh", "B": "in_body", "C": "painted", "D": "painted", "G": "painted"})
        for item_id, want in (("A", "own_mesh"), ("B", "in_body"), ("C", "painted"), ("D", "painted"),
                              ("G", "painted"), ("E", "in_body")):
            check(f"stored mode {item_id}", piece_of(item_id).get("mesh_mode"), want)
            check(f"mesh_mode_of {item_id}", garment_set.mesh_mode_of(inventory.get_item(item_id)), want)
        world_pieces = [json.loads(r[0] or "{}") for r in
                        __import__("app.core.db", fromlist=["x"]).get_connection().execute(
                            "SELECT pieces FROM items").fetchall()]
        shared_pieces = [it.get("outfit_piece") or {} for it in json.loads(shared_file.read_text())["items"]]
        check("no own_mesh key anywhere", [p for p in world_pieces + shared_pieces if "own_mesh" in p], [])
        check("tool has no outfit_piece", "outfit_piece" in (inventory.get_item("T") or {}), False)

        print("[2] profiles")
        check("result profiles", sorted((result or {}).get("profiles") or []), ["M1", "M2", "R"])
        from app.models.character import get_character_profile
        for name in ("R", "M1", "M2", "P"):
            check(f"{name}: stored key gone", "outfit_body_mode" in stored_profile(name), False)
            check(f"{name}: profile key gone", "outfit_body_mode" in get_character_profile(name), False)
        check("M1 still wears", get_character_profile("M1").get("equipped_pieces"),
              {"top": "B", "outer": "C", "legs": "G"})

        print("[3] once")
        from app.models.world import get_world_setting
        check("flag set", bool(get_world_setting(fm.FLAG)), True)
        check("flag name", fm.FLAG, "migrated_worn_piece_modes")
        before = (shared_file.read_bytes(), rows("items"), rows("characters"))
        check("second call", fm.migrate_modes_once(), None)
        check("nothing changed", (shared_file.read_bytes(), rows("items"), rows("characters")), before)

        print("[4] second world, same shared items")
        os.environ["STORAGE_DIR"] = str(root / "world2")
        open_world(root / "world2")
        check("world 2: flag unset", get_world_setting(fm.FLAG), "")
        raw_piece("F", {"slots": ["top"]})
        character("M3", "mesh", {"top": "B", "outer": "C", "legs": "F"})
        character("R3", "retexture", {"top": "E"})
        result2 = fm.migrate_modes_once()
        check("world 2 items", (result2 or {}).get("items"), {"F": "in_body"})
        check("world 2 profiles", sorted((result2 or {}).get("profiles") or []), ["M3", "R3"])
        for item_id, want in (("B", "in_body"), ("C", "painted"), ("E", "in_body"), ("F", "in_body")):
            check(f"world 2 mode {item_id}", piece_of(item_id).get("mesh_mode"), want)

        print("[5] update_item drops a stored own_mesh")
        raw_piece("V", {"slots": ["top"], "own_mesh": True})
        inventory.update_item("V", {"name": "Old vest"})
        check("legacy vest: flag gone", "own_mesh" in piece_of("V"), False)
        check("legacy vest: still no mode", "mesh_mode" in piece_of("V"), False)
        check("legacy vest: name stored", (inventory.get_item("V") or {}).get("name"), "Old vest")
        reset_connections()

    print("[6] old code and wiring")
    check(f"old code {BASE}: no figure_migration",
          git("cat-file", "-e", f"{BASE}:app/core/figure_migration.py").returncode != 0, True)
    check(f"old code {BASE}: carry-through present",
          "prev_own_mesh_stored" in git("show", f"{BASE}:app/models/inventory.py").stdout, True)
    check("carry-through gone", "prev_own_mesh_stored" in (ROOT / "app/models/inventory.py").read_text(), False)
    server = (ROOT / "app/server.py").read_text(encoding="utf-8")
    at_hair, at_modes, at_refit = (server.find("delete_all_hair_once()"), server.find("migrate_modes_once()"),
                                   server.find("from app.core.garment_refit import start_sweep"))
    check("server: hair < modes < refit sweep", 0 <= at_hair < at_modes < at_refit, True)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
