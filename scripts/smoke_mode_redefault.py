"""The default mode of an outfit piece is "in the body", a mode is stored only
when someone picks it, and the one-time re-default clears the modes nobody
tests (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``,
Rulings A10 / A12; ``app/core/figure_migration.py`` "RE-DEFAULT").

Usage:
    ./.venv/bin/python scripts/smoke_mode_redefault.py

Runs in a temp world (``paths.init(<tmp>)`` before any world-DB import); the
shared item library is redirected to a temp file
(``inventory._get_shared_items_file``), so the tracked
``shared/items/items.json`` is never read or written. No server, no hub.

Expected values, derived by hand from the rulings:
A10: ``default_mesh_mode(slots)`` is ``in_body`` for every slot set, footwear
included; a stored valid mode wins; a mode is stored only when the input names
a valid one. A12: an outfit piece with a stored mode loses it unless a TEST
character wears it — a humanoid whose STORED profile has ``model_pipeline:
"base_body"`` (``is_test_character``), every character row counted (dormant
and pooled too). The re-default waits for the mode migration's flag.

Characters (template human-roleplay unless named):
    T  model_pipeline base_body                         -> test character
    N  no model_pipeline                                -> not one
    D  model_pipeline base_body, status dormant         -> test character
    A  template animal-default, model_pipeline base_body -> not one (no humanoid)
Items (stored mode in brackets; ``-`` = no mode key):
    U  world,  outer,  [painted],  unworn                  -> cleared, mode in_body
    C  world,  top,    [painted],  worn by N only          -> cleared
    K  shared, top,    [painted],  worn by T and N         -> kept painted
    O  world,  feet,   [own_mesh], worn by T               -> kept own_mesh
    Q  world,  top,    [in_body],  worn by dormant D       -> kept in_body
    Z  world,  top,    [painted],  worn by animal A        -> cleared
    S  shared, outer,  [own_mesh], unworn                  -> cleared (shared file written)
    L  world,  top,    -,          unworn                  -> untouched, mode in_body
    X  a tool                                              -> untouched
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
[3] The re-default waits: with the mode migration's flag unset it returns None,
    the redefault flag stays unset and nothing changes.
[4] With the flag set: result cleared == {U: painted, C: painted, Z: painted,
    S: own_mesh}, kept == {K: painted, O: own_mesh, Q: in_body}; stored modes:
    U, C, Z, S, L without a key, K painted, O own_mesh, Q in_body; mesh_mode_of
    of U, C, Z, S, L == in_body; X has no outfit_piece. is_test_character:
    T True, N False, D True, A False. No Build started or requested
    (figure_build.start / request patched to record), no outfit notification,
    no 2D invalidation, no hub operation (hub_ops.list_ops() empty).
[5] Once: the flag ``redefaulted_unworn_piece_modes`` is set; a second call
    returns None and the shared file bytes and the ``items`` rows are identical.
[6] Old code and wiring: at 8e67362b (the task's BASE) garment_set's
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


def raw_piece(item_id: str, piece: dict, *, category: str = "outfit_piece"):
    """A world item row written RAW (exactly the stored piece, no normalisation)."""
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, ?, '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, item_id, category, json.dumps(piece)))
    from app.core.motion_item_cache import invalidate
    invalidate()


def character(name: str, pieces: dict, *, pipeline: bool, status: str = "", template: str = "human-roleplay"):
    from app.core import db
    from app.models.character import save_character_profile
    profile = {"template": template, "gender": "female", "age": 30, "height": 168, "equipped_pieces": dict(pieces)}
    if pipeline:
        profile["model_pipeline"] = "base_body"
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)
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
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        from app.models import inventory
        shared_file = root / "shared" / "items" / "items.json"
        shared_file.parent.mkdir(parents=True)
        inventory._get_shared_items_file = lambda: shared_file
        from app.core import garment_set

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
        with db.transaction() as conn:  # [2]'s items leave before the fixture of [3]..[5]
            conn.execute("DELETE FROM items")
        from app.core.motion_item_cache import invalidate
        invalidate()

        # Fixture of [3]..[5].
        shared_file.write_text(json.dumps({"items": [
            {"id": "K", "name": "K", "category": "outfit_piece",
             "outfit_piece": {"slots": ["top"], "mesh_mode": "painted"}},
            {"id": "S", "name": "S", "category": "outfit_piece",
             "outfit_piece": {"slots": ["outer"], "mesh_mode": "own_mesh"}},
        ]}, indent=2), encoding="utf-8")
        raw_piece("U", {"slots": ["outer"], "mesh_mode": "painted"})
        raw_piece("C", {"slots": ["top"], "mesh_mode": "painted"})
        raw_piece("O", {"slots": ["feet"], "mesh_mode": "own_mesh"})
        raw_piece("Q", {"slots": ["top"], "mesh_mode": "in_body"})
        raw_piece("Z", {"slots": ["top"], "mesh_mode": "painted"})
        raw_piece("L", {"slots": ["top"]})
        raw_piece("X", {}, category="tool")
        character("T", {"top": "K", "feet": "O"}, pipeline=True)
        character("N", {"top": "K", "outer": "C"}, pipeline=False)
        character("D", {"top": "Q"}, pipeline=True, status="dormant")
        character("A", {"top": "Z"}, pipeline=True, template="animal-default")

        from app.core import figure_migration as fm
        from app.models.character import get_character_profile
        from app.models.world import get_world_setting, set_world_setting

        print("[3] waits for the mode migration")
        before = (shared_file.read_bytes(), rows("items"))
        check("mode migration flag unset (fixture)", get_world_setting(fm.FLAG), "")
        check("waits", fm.redefault_modes_once(), None)
        check("redefault flag still unset", get_world_setting(fm.REDEFAULT_FLAG), "")
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
              {"U": "painted", "C": "painted", "Z": "painted", "S": "own_mesh"})
        check("kept", result.get("kept"), {"K": "painted", "O": "own_mesh", "Q": "in_body"})
        for item_id in ("U", "C", "Z", "S", "L"):
            check(f"{item_id}: no stored mode", "mesh_mode" in piece_of(item_id), False)
            check(f"{item_id}: mode in_body", garment_set.mesh_mode_of(inventory.get_item(item_id)), "in_body")
        for item_id, want in (("K", "painted"), ("O", "own_mesh"), ("Q", "in_body")):
            check(f"{item_id}: stored mode kept", piece_of(item_id).get("mesh_mode"), want)
        check("U slots untouched", piece_of("U").get("slots"), ["outer"])
        check("shared file: S without a mode",
              [it.get("outfit_piece") for it in json.loads(shared_file.read_text())["items"] if it["id"] == "S"],
              [{"slots": ["outer"]}])
        check("tool has no outfit_piece", "outfit_piece" in (inventory.get_item("X") or {}), False)
        check("no Build, no notification, no invalidation", calls, [])
        check("no hub operation", hub_ops.list_ops(), [])
        check("T still wears K and O", get_character_profile("T").get("equipped_pieces"), {"top": "K", "feet": "O"})

        print("[5] once")
        check("flag name", fm.REDEFAULT_FLAG, "redefaulted_unworn_piece_modes")
        check("flag set", bool(get_world_setting(fm.REDEFAULT_FLAG)), True)
        before = (shared_file.read_bytes(), rows("items"))
        check("second call", fm.redefault_modes_once(), None)
        check("nothing changed", (shared_file.read_bytes(), rows("items")), before)
        for conn in list(db._connections.values()):
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        db._connections.clear()

    print("[6] old code and wiring")
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
