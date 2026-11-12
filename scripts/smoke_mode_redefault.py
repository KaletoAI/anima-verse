"""The default mode of an outfit piece is "in the body", a mode is stored only
when someone picks it, and the one-time re-default clears the modes nobody
tests (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``,
Rulings A10 / A12 and fix round 1; ``app/core/figure_migration.py``
"RE-DEFAULT").

Usage:
    ./.venv/bin/python scripts/smoke_mode_redefault.py

Runs in temp worlds (``paths.init(<tmp>)`` before any world-DB import); the
shared item library is redirected to temp files
(``inventory._get_shared_items_file``), so the tracked
``shared/items/items.json`` is never read or written. No server, no hub.

Expected values, derived by hand from the rulings:
A10: ``default_mesh_mode(slots)`` is ``in_body`` for every slot set, footwear
included; a stored valid mode wins; a mode is stored only when the input names
a valid one. A12 + fix round 1: an outfit piece with a stored mode loses it
unless a TEST character wears it (``equipped_pieces``) or OWNS it (inventory)
— a test character is a humanoid whose STORED profile has ``model_pipeline:
"base_body"`` (``is_test_character``), every character row counted (dormant
and pooled too). The world's items: once per world (world_kv flag). The shared
library: once for ALL worlds (top-level key ``redefaulted_unworn_piece_modes``
in the shared items file, written with the cleared items), only by a world
WITH test characters; a world without any leaves the shared library untouched.
The re-default waits for the mode migration's flag.

World 1 characters (template human-roleplay unless named):
    T  model_pipeline base_body                          -> test character
    N  no model_pipeline                                 -> not one
    D  model_pipeline base_body, status dormant          -> test character
    A  template animal-default, model_pipeline base_body -> not one (no humanoid)
World 1 items (stored mode in brackets; ``-`` = no mode key):
    U  world,  outer, [painted],  unworn, unowned          -> cleared, mode in_body
    C  world,  top,   [painted],  worn by N only           -> cleared
    G  world,  top,   [painted],  owned by N only          -> cleared (N is no tester)
    K  shared, top,   [painted],  worn by T and N          -> kept painted
    O  world,  feet,  [own_mesh], worn by T                -> kept own_mesh
    H  world,  top,   [own_mesh], OWNED by T, not worn     -> kept own_mesh
    M  shared, top,   [painted],  owned by dormant D       -> kept painted
    Q  world,  top,   [in_body],  worn by dormant D        -> kept in_body
    Z  world,  top,   [painted],  worn by animal A         -> cleared
    S  shared, outer, [own_mesh], unworn, unowned          -> cleared
    L  world,  top,   -,          unworn                   -> untouched, mode in_body
    X  a tool                                              -> untouched
The shared file starts with an extra top-level key ``note: "keep me"``.
[1] A10 default: default_mesh_mode(["feet"]) == "in_body"; also ["outer"],
    ["top"], ["top","bottom"], ["legs","feet"], [] -> "in_body";
    mesh_mode_of({slots [feet]}) == "in_body"; mesh_mode_of({slots [top],
    mesh_mode painted}) == "painted".
[2] A10 store only choices: add_item {slots [feet]} stores NO mesh_mode key
    (mesh_mode_of in_body); {slots [top], mesh_mode painted} stores painted;
    {slots [top], mesh_mode "bogus"} stores no key. update_item of the painted
    piece without naming the mode keeps painted; naming mesh_mode None clears
    the key (mode in_body); a name-only update of the keyless piece writes no
    key.
[3] The re-default waits: with the mode migration's flag unset it returns
    None, neither marker is set and nothing changes.
[4] With the flag set: cleared == {U: painted, C: painted, G: painted, Z:
    painted, S: own_mesh}, kept == {K: painted, O: own_mesh, H: own_mesh, M:
    painted, Q: in_body}, world "done", shared "done"; stored modes match
    (U, C, G, Z, S, L without a key -> mesh_mode_of in_body); X has no
    outfit_piece. is_test_character: T True, N False, D True, A False. The
    shared file carries the marker key AND still ``note: "keep me"``. No Build
    started or requested, no outfit notification, no 2D invalidation, no hub
    operation.
[5] Once: the world flag is set; a second call returns None and the shared
    file bytes and the ``items`` rows are identical. A later ordinary shared
    save (update_item renames K) keeps the marker and the note.
[6] A world WITHOUT test characters boots first (world 2, new shared file F2:
    P1 shared top [painted] worn by N2; P2 shared top [own_mesh], used by
    nobody in world 2 — another world's tester may wear it; W world top
    [painted] unworn; N2 has no model_pipeline): result world "done", shared
    "waits", cleared == {W: painted}; F2 bytes identical (P2 keeps own_mesh,
    no marker). A second call: world "already", shared "waits", cleared {}.
    Then world 3 (tester T3 owns P2, flag of the mode migration set) boots
    with F2: shared "done", cleared == {P1: painted}, kept == {P2: own_mesh};
    F2 has the marker. Back in world 2: None (both scopes done).
[7] Old code and wiring: at 8e67362b (the task's BASE) garment_set's
    default_mesh_mode returns OWN_MESH for feet and figure_migration has no
    redefault_modes_once; app/server.py calls redefault_modes_once after
    stamp_figures_once and before the garment refit sweep.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "8e67362b"
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


def raw_piece(item_id: str, piece: dict, *, category: str = "outfit_piece"):
    """A world item row written RAW (exactly the stored piece, no normalisation)."""
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, ?, '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, item_id, category, json.dumps(piece)))
    from app.core.motion_item_cache import invalidate
    invalidate()


def shared(path: Path, items: list, **meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": [{"id": i, "name": i, "category": "outfit_piece", "outfit_piece": p}
                                          for i, p in items], **meta}, indent=2), encoding="utf-8")
    from app.core.motion_item_cache import invalidate
    invalidate()


def character(name: str, pieces: dict, *, pipeline: bool, status: str = "", template: str = "human-roleplay",
              owns=()):
    from app.core import db
    from app.models import inventory
    from app.models.character import save_character_profile
    profile = {"template": template, "gender": "female", "age": 30, "height": 168, "equipped_pieces": dict(pieces)}
    if pipeline:
        profile["model_pipeline"] = "base_body"
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)
    for item_id in owns:
        check(f"{name} owns {item_id}", inventory.add_to_inventory(name, item_id), True)
    if status:
        with db.transaction() as conn:
            conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))


def rows(table: str):
    from app.core import db
    return db.get_connection().execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def piece_of(item_id: str) -> dict:
    from app.models import inventory
    item = inventory.get_item(item_id) or {}
    return item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mode-redefault-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world1")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        shared_file = root / "shared1" / "items.json"
        shared(shared_file, [])
        open_world(root / "world1", shared_file)
        from app.core import garment_set
        from app.models import inventory

        print("[1] the default is in the body")
        d = garment_set.default_mesh_mode
        check("feet", d(["feet"]), "in_body")
        for slots in (["outer"], ["top"], ["top", "bottom"], ["legs", "feet"], []):
            check(f"{slots}", d(slots), "in_body")
        op = lambda p: {"category": "outfit_piece", "outfit_piece": p}  # noqa: E731
        check("mesh_mode_of keyless boots", garment_set.mesh_mode_of(op({"slots": ["feet"]})), "in_body")
        check("mesh_mode_of stored painted", garment_set.mesh_mode_of(op({"slots": ["top"], "mesh_mode": "painted"})),
              "painted")

        print("[2] only a choice is stored")

        def add(name, p):
            return inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a plain {name}",
                                      outfit_piece=p)["id"]

        boots = add("Boots", {"slots": ["feet"]})
        check("boots: no mode key", "mesh_mode" in piece_of(boots), False)
        check("boots: mode in_body", garment_set.mesh_mode_of(inventory.get_item(boots)), "in_body")
        shirt = add("Shirt", {"slots": ["top"], "mesh_mode": "painted"})
        check("shirt: painted stored", piece_of(shirt).get("mesh_mode"), "painted")
        bogus = add("Bogus", {"slots": ["top"], "mesh_mode": "bogus"})
        check("bogus: no mode key", "mesh_mode" in piece_of(bogus), False)
        inventory.update_item(shirt, {"outfit_piece": {"slots": ["top"]}})
        check("shirt: update without the mode keeps painted", piece_of(shirt).get("mesh_mode"), "painted")
        inventory.update_item(shirt, {"outfit_piece": {"slots": ["top"], "mesh_mode": None}})
        check("shirt: mode None clears the key", "mesh_mode" in piece_of(shirt), False)
        check("shirt: back to the default", garment_set.mesh_mode_of(inventory.get_item(shirt)), "in_body")
        inventory.update_item(boots, {"name": "Old boots"})
        check("boots: name update writes no key", "mesh_mode" in piece_of(boots), False)
        from app.core import db
        with db.transaction() as conn:  # [2]'s items leave before the fixture of [3]..[5]
            conn.execute("DELETE FROM items")
        from app.core.motion_item_cache import invalidate
        invalidate()

        # Fixture of [3]..[5].
        shared(shared_file, [("K", {"slots": ["top"], "mesh_mode": "painted"}),
                             ("M", {"slots": ["top"], "mesh_mode": "painted"}),
                             ("S", {"slots": ["outer"], "mesh_mode": "own_mesh"})], note="keep me")
        raw_piece("U", {"slots": ["outer"], "mesh_mode": "painted"})
        raw_piece("C", {"slots": ["top"], "mesh_mode": "painted"})
        raw_piece("G", {"slots": ["top"], "mesh_mode": "painted"})
        raw_piece("O", {"slots": ["feet"], "mesh_mode": "own_mesh"})
        raw_piece("H", {"slots": ["top"], "mesh_mode": "own_mesh"})
        raw_piece("Q", {"slots": ["top"], "mesh_mode": "in_body"})
        raw_piece("Z", {"slots": ["top"], "mesh_mode": "painted"})
        raw_piece("L", {"slots": ["top"]})
        raw_piece("X", {}, category="tool")
        character("T", {"top": "K", "feet": "O"}, pipeline=True, owns=("H",))
        character("N", {"top": "K", "outer": "C"}, pipeline=False, owns=("G",))
        character("D", {"top": "Q"}, pipeline=True, status="dormant", owns=("M",))
        character("A", {"top": "Z"}, pipeline=True, template="animal-default")

        from app.core import figure_migration as fm
        from app.models.character import get_character_profile
        from app.models.world import get_world_setting, set_world_setting

        def shared_meta(path):
            data = json.loads(path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k not in ("items", "last_updated")}

        print("[3] waits for the mode migration")
        before = (shared_file.read_bytes(), rows("items"))
        check("mode migration flag unset (fixture)", get_world_setting(fm.FLAG), "")
        check("waits", fm.redefault_modes_once(), None)
        check("world flag still unset", get_world_setting(fm.REDEFAULT_FLAG), "")
        check("shared marker still unset", fm.SHARED_REDEFAULT_KEY in shared_meta(shared_file), False)
        check("nothing changed while waiting", (shared_file.read_bytes(), rows("items")), before)

        print("[4] the re-default")
        for name, want in (("T", True), ("N", False), ("D", True), ("A", False)):
            check(f"is_test_character {name}", fm.is_test_character(name, get_character_profile(name)), want)
        calls = []
        from app.core import figure_build, hub_ops
        figure_build.start = lambda *a, **k: calls.append(("start", a)) or {}
        figure_build.request = lambda *a, **k: calls.append(("request", a)) or False
        inventory._notify_outfit_changed = lambda *a, **k: calls.append(("notify", a))
        inventory._invalidate_renders_for_item = lambda *a, **k: calls.append(("invalidate", a))
        set_world_setting(fm.FLAG, "1")
        result = fm.redefault_modes_once() or {}
        check("cleared", result.get("cleared"),
              {"U": "painted", "C": "painted", "G": "painted", "Z": "painted", "S": "own_mesh"})
        check("kept", result.get("kept"),
              {"K": "painted", "O": "own_mesh", "H": "own_mesh", "M": "painted", "Q": "in_body"})
        check("scopes", (result.get("world"), result.get("shared")), ("done", "done"))
        for item_id in ("U", "C", "G", "Z", "S", "L"):
            check(f"{item_id}: no stored mode", "mesh_mode" in piece_of(item_id), False)
            check(f"{item_id}: mode in_body", garment_set.mesh_mode_of(inventory.get_item(item_id)), "in_body")
        for item_id, want in (("K", "painted"), ("O", "own_mesh"), ("H", "own_mesh"), ("M", "painted"),
                              ("Q", "in_body")):
            check(f"{item_id}: stored mode kept", piece_of(item_id).get("mesh_mode"), want)
        check("U slots untouched", piece_of("U").get("slots"), ["outer"])
        check("tool has no outfit_piece", "outfit_piece" in (inventory.get_item("X") or {}), False)
        meta = shared_meta(shared_file)
        check("shared marker set", bool(meta.get(fm.SHARED_REDEFAULT_KEY)), True)
        check("shared note kept", meta.get("note"), "keep me")
        check("no Build, no notification, no invalidation", calls, [])
        check("no hub operation", hub_ops.list_ops(), [])
        check("T still wears K and O", get_character_profile("T").get("equipped_pieces"), {"top": "K", "feet": "O"})

        print("[5] once")
        check("world flag name", fm.REDEFAULT_FLAG, "redefaulted_unworn_piece_modes")
        check("shared key name", fm.SHARED_REDEFAULT_KEY, "redefaulted_unworn_piece_modes")
        check("world flag set", bool(get_world_setting(fm.REDEFAULT_FLAG)), True)
        before = (shared_file.read_bytes(), rows("items"))
        check("second call", fm.redefault_modes_once(), None)
        check("nothing changed", (shared_file.read_bytes(), rows("items")), before)
        marker = shared_meta(shared_file)[fm.SHARED_REDEFAULT_KEY]
        inventory.update_item("K", {"name": "Kept blouse"})
        check("ordinary shared save: renamed", (inventory.get_item("K") or {}).get("name"), "Kept blouse")
        check("ordinary shared save keeps marker + note", shared_meta(shared_file),
              {"note": "keep me", fm.SHARED_REDEFAULT_KEY: marker})

        print("[6] a world without test characters boots first")
        f2 = root / "shared2" / "items.json"
        shared(f2, [("P1", {"slots": ["top"], "mesh_mode": "painted"}),
                    ("P2", {"slots": ["top"], "mesh_mode": "own_mesh"})])
        os.environ["STORAGE_DIR"] = str(root / "world2")
        open_world(root / "world2", f2)
        raw_piece("W", {"slots": ["top"], "mesh_mode": "painted"})
        character("N2", {"top": "P1"}, pipeline=False)
        set_world_setting(fm.FLAG, "1")
        before2 = f2.read_bytes()
        r2 = fm.redefault_modes_once() or {}
        check("world 2: scopes", (r2.get("world"), r2.get("shared")), ("done", "waits"))
        check("world 2: cleared", r2.get("cleared"), {"W": "painted"})
        check("world 2: shared file untouched", f2.read_bytes(), before2)
        check("world 2: P2 keeps own_mesh", piece_of("P2").get("mesh_mode"), "own_mesh")
        r2b = fm.redefault_modes_once() or {}
        check("world 2 again: scopes", (r2b.get("world"), r2b.get("shared"), r2b.get("cleared")),
              ("already", "waits", {}))
        check("world 2 again: shared file untouched", f2.read_bytes(), before2)

        os.environ["STORAGE_DIR"] = str(root / "world3")
        open_world(root / "world3", f2)
        character("T3", {}, pipeline=True, owns=("P2",))
        set_world_setting(fm.FLAG, "1")
        r3 = fm.redefault_modes_once() or {}
        check("world 3: scopes", (r3.get("world"), r3.get("shared")), ("done", "done"))
        check("world 3: cleared", r3.get("cleared"), {"P1": "painted"})
        check("world 3: kept", r3.get("kept"), {"P2": "own_mesh"})
        check("world 3: F2 marker", bool(shared_meta(f2).get(fm.SHARED_REDEFAULT_KEY)), True)

        os.environ["STORAGE_DIR"] = str(root / "world2")
        open_world(root / "world2", f2)
        check("world 2 after world 3: nothing left", fm.redefault_modes_once(), None)
        reset_connections()

    print("[7] old code and wiring")
    base_set = git("show", f"{BASE}:app/core/garment_set.py").stdout
    check(f"old code {BASE}: feet -> own mesh", "if worn == {FOOTWEAR_SLOT}:\n        return OWN_MESH" in base_set, True)
    check(f"old code {BASE}: no re-default",
          "def redefault_modes_once" in git("show", f"{BASE}:app/core/figure_migration.py").stdout, False)
    server = (ROOT / "app/server.py").read_text(encoding="utf-8")
    at_stamp, at_redefault, at_refit = (server.find("stamp_figures_once()"), server.find("redefault_modes_once()"),
                                        server.find("from app.core.garment_refit import start_sweep"))
    check("server: stamp < re-default < refit sweep", 0 <= at_stamp < at_redefault < at_refit, True)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
