#!/usr/bin/env python3
"""Boot migrations that run again — after one character failed, after a failed write, after a failed flag read —
never touch what an earlier pass finished (review units 08 #1 / 08 #4 / 07 #1):
``figure_migration.migrate_hairstyles_once``, ``figure_migration.migrate_modes_once`` and
``hair_migration.delete_all_hair_once``.

Usage:
    ./.venv/bin/python scripts/smoke_migration_reruns.py

Runs in THROWAWAY worlds under one temp directory (``paths.init(<tmp>)`` before any world-DB import; a new world per
part, connections reset between them) with a copy of the repo's ``human`` package; the shared item library is
redirected to a temp file, so the tracked ``shared/items/items.json`` is never read or written. No server, no hub,
no GPU. ``figure_build.request`` and ``garment_assembly.schedule`` are recorders (nothing is built). "Byte-identical"
compares the raw ``characters`` / ``items`` rows (``SELECT *`` — ``profile_json``, ``meta``, ``updated_at``
included), so any write shows.

The old-code proofs run the functions of commit OLD = 3f2ce338 (the code the review read, before these fixes)
loaded from git as a module, on a world of their own.

EXPECTED, BY HAND
Human package: the hair slot fragment is "{length} {color} hair"; a profile's hair text (``appearance_hair_text``) is
that fragment plus every Appearance clause with the word "hair". The world names no hairstyle default mode, so
``garment_hair.default_mode()`` is "body".

[1] migrate_hairstyles_once. Characters (human-roleplay, age 30), the hair migration's flag set:
      Kai  hair short/black, appearance "athletic, wavy hair with a side parting", hair_method "body",
           hair_colour "#112233", no hair item -> text "short black hair, wavy hair with a side parting";
      Lea  hair long/red, appearance "slender", hair_method "hairdeck", no hair item -> text "long red hair";
      Ana  hair long/blonde, appearance "slender", hair_method "hairdeck", hair_forward_m 0.004, owns the hair
           item hair_ana (no mode) and wears it -> text "long blonde hair";
      Bom  no hair slot values, appearance "tall" -> no hair text, no hairstyle.
    Pass 1, Ana's profile save answering False: Kai and Lea get a minted hairstyle (worn, plain), Ana fails ->
      result names Kai and Lea only; the flag stays unset; Ana's profile keeps hair_method; hair_ana already holds
      mode "hairdeck", description "long blonde hair", hair_forward_m 0.004 (item first, profile second).
    Between the boots the user changes Kai's hairstyle (mode "hairdeck", description "a short bob") and takes Lea's
      hairstyle off (equipped_mesh_pieces without "hair").
    Pass 2, nothing failing: result {"Ana": "hair_ana"} — Kai and Lea have no legacy key left and own a hairstyle
      that names its mode, so they are skipped; their characters + items rows are byte-identical to before pass 2.
      Ana: no hair_method / hair_forward_m in the profile, wears hair_ana, base_hairstyle hair_ana; hair_ana keeps
      mode "hairdeck" and description "long blonde hair". The flag is set.
    Pass 3, the flag cleared by hand (a re-run on a finished world): result {} and every characters / items row
      byte-identical; the flag is set again. Pass 4: None.
    OLD code (3f2ce338) on a world of its own with the same Kai and a failing Zed (hair_method "body", hair
      long/brown): pass 1 migrates Kai; the same user change; pass 2 rewrites Kai's hairstyle to mode "body" (the
      world default — the legacy key is gone) and description "short black hair, wavy hair with a side parting":
      the finding.

[2] migrate_modes_once. World items (raw rows, no mode): X (top) worn by A, Y (outer) worn by B; A and B store
    outfit_body_mode "mesh"; the shared library is an empty list.
    Pass 1, the save of X answering False: result items {"Y": "in_body"} (rule 3: every wearer "mesh"),
      profiles ["B"]; A KEEPS outfit_body_mode "mesh" (the only record its judgement needs); X has no stored mode;
      the world flag stays unset.
    Pass 2, nothing failing: items {"X": "in_body"} (A's kept "mesh"), profiles ["A"]; the flag is set; B's
      characters row and Y's items row byte-identical to after pass 1.
    Pass 3, the flag cleared by hand: items {}, profiles [], every row byte-identical.
    OLD code (3f2ce338) on a world of its own, X failing: pass 1 drops A's key anyway and sets the flag; the next
      call returns None, X never gets a mode — A's choice is lost.

[3] delete_all_hair_once. Kai owns and wears the hairstyle hair_kai (mode "hairdeck"); no legacy key (the profile of
    a hairstyle-era world); both flags set.
    The world_kv read fails ("database is locked", injected at ``world.get_connection``): the call RAISES
      sqlite3.OperationalError — hair_kai still exists, Kai's row byte-identical. The boot call in app/server.py
      sits in a ``try`` that logs it (checked on the source: the line before the import is ``try:``).
      The OLD guard read the flag without ``strict``: under the same failure ``get_world_setting(HAIR_FLAG)`` is ""
      (falsy), so the old code went on — and what it then does on this world: the flag cleared, one run ->
      hair_kai deleted (legacy_hair_method of a profile without hair_method = the default "body" -> every own
      hair item goes).
    Run twice with a readable flag: None, every row byte-identical.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "3f2ce338"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def old_module(rel: str, name: str) -> types.ModuleType:
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{rel}"], check=True, capture_output=True,
                            text=True).stdout
    module = types.ModuleType(name)
    exec(compile(source, f"{OLD}:{rel}", "exec"), module.__dict__)
    return module


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


def rows(table: str, key: str = "", values=()):
    from app.core import db
    conn = db.get_connection()
    if values:
        marks = ",".join("?" * len(values))
        found = conn.execute(f"SELECT * FROM {table} WHERE {key} IN ({marks}) ORDER BY 1", tuple(values)).fetchall()
    else:
        found = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    return [tuple(row) for row in found]


def human(name, **extra):
    from app.models.character import save_character_profile
    profile = {"template": "human-roleplay", "age": 30, "gender": "female", "height": 168, **extra}
    check(f"create {name}", save_character_profile(name, profile, create_new=True), True)


def wear(name, item_id):
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name)
        worn = dict(profile.get("equipped_mesh_pieces") or {})
        if item_id:
            worn["hair"] = item_id
        else:
            worn.pop("hair", None)
        profile["equipped_mesh_pieces"] = worn
        check(f"{name} wears {item_id or 'no hair'}", save_character_profile(name, profile), True)


def hair_item(owner, item_id, **garment):
    from app.models import inventory
    inventory.add_item(name="Hair", category="garment", owner=owner, item_id=item_id,
                       garment={"kind": "hair", "slot": "hair", "body_slot": "hair", **garment},
                       transferable=False, portable=False)


def user_edits_hairstyle(item_id, mode, description):
    from app.models import inventory
    item = inventory.get_item(item_id)
    garment = dict(item["garment"], mesh_mode=mode, description=description)
    check(f"user edits {item_id}", inventory.update_item(item_id, {"garment": garment}) is not None, True)


def failing_profile_save(names):
    """``save_character_profile`` answering False for ``names`` (the migrations import it at call time)."""
    from app.models import character
    real = character.save_character_profile

    def save(name, *a, **kw):
        return False if name in names else real(name, *a, **kw)
    character.save_character_profile = save
    return lambda: setattr(character, "save_character_profile", real)


KAI = dict(gender="male", height=180, character_appearance="athletic, wavy hair with a side parting",
           body_slots={"hair": {"length": "short", "color": "black"}}, hair_method="body", hair_colour="#112233")
KAI_TEXT = "short black hair, wavy hair with a side parting"


def part_hairstyles(root: Path):
    print("[1] migrate_hairstyles_once")
    open_world(root / "w1")
    from app.core import figure_migration as fm, garment_hair
    from app.core.hair_migration import HAIR_FLAG
    from app.models import inventory
    from app.models.character import get_character_profile
    from app.models.world import get_world_setting, set_world_setting
    human("Kai", **KAI)
    human("Lea", character_appearance="slender", body_slots={"hair": {"length": "long", "color": "red"}},
          hair_method="hairdeck")
    human("Ana", character_appearance="slender", body_slots={"hair": {"length": "long", "color": "blonde"}},
          hair_method="hairdeck", hair_forward_m=0.004)
    hair_item("Ana", "hair_ana")
    wear("Ana", "hair_ana")
    human("Bom", gender="male", height=175, character_appearance="tall")
    set_world_setting(HAIR_FLAG, "1")

    restore = failing_profile_save({"Ana"})
    try:
        first = fm.migrate_hairstyles_once() or {}
    finally:
        restore()
    check("pass 1: Kai and Lea migrated, Ana failed", sorted(first), ["Kai", "Lea"])
    check("pass 1: flag unset", bool(get_world_setting(fm.HAIRSTYLE_FLAG)), False)
    check("pass 1: Ana keeps hair_method", get_character_profile("Ana").get("hair_method"), "hairdeck")
    ana = inventory.get_item("hair_ana")["garment"]
    check("pass 1: hair_ana already a hairstyle",
          (ana.get("mesh_mode"), ana.get("description"), ana.get("hair_forward_m")),
          ("hairdeck", "long blonde hair", 0.004))
    kai_id, lea_id = first["Kai"], first["Lea"]
    check("pass 1: Kai's minted hairstyle", (inventory.get_item(kai_id)["garment"].get("mesh_mode"),
                                             inventory.get_item(kai_id)["garment"].get("description")),
          ("body", KAI_TEXT))

    user_edits_hairstyle(kai_id, "hairdeck", "a short bob")
    wear("Lea", "")
    before = (rows("characters", "name", ("Kai", "Lea")), rows("items", "id", (kai_id, lea_id)))
    second = fm.migrate_hairstyles_once()
    check("pass 2: only Ana", second, {"Ana": "hair_ana"})
    check("pass 2: Kai and Lea byte-identical",
          (rows("characters", "name", ("Kai", "Lea")), rows("items", "id", (kai_id, lea_id))) == before, True)
    profile = get_character_profile("Ana")
    check("pass 2: Ana's profile finished",
          ("hair_method" in profile, "hair_forward_m" in profile, profile.get("equipped_mesh_pieces", {}).get("hair"),
           profile.get(garment_hair.BASE_HAIRSTYLE_KEY)), (False, False, "hair_ana", "hair_ana"))
    ana = inventory.get_item("hair_ana")["garment"]
    check("pass 2: hair_ana kept", (ana.get("mesh_mode"), ana.get("description")), ("hairdeck", "long blonde hair"))
    check("pass 2: flag set", bool(get_world_setting(fm.HAIRSTYLE_FLAG)), True)

    set_world_setting(fm.HAIRSTYLE_FLAG, "")
    everything = (rows("characters"), rows("items"))
    check("pass 3 (flag cleared): nothing to do", fm.migrate_hairstyles_once(), {})
    check("pass 3: every row byte-identical", (rows("characters"), rows("items")) == everything, True)
    check("pass 3: flag set again", bool(get_world_setting(fm.HAIRSTYLE_FLAG)), True)
    check("pass 4: None", fm.migrate_hairstyles_once(), None)

    print(f"[1] old code ({OLD})")
    open_world(root / "w1old")
    old = old_module("app/core/figure_migration.py", "figure_migration_old")
    human("Kai", **KAI)
    human("Zed", character_appearance="slender", body_slots={"hair": {"length": "long", "color": "brown"}},
          hair_method="body")
    set_world_setting(HAIR_FLAG, "1")
    restore = failing_profile_save({"Zed"})
    try:
        first = old.migrate_hairstyles_once() or {}
    finally:
        restore()
    check("old pass 1: Kai migrated", sorted(first), ["Kai"])
    user_edits_hairstyle(first["Kai"], "hairdeck", "a short bob")
    old.migrate_hairstyles_once()
    garment = inventory.get_item(first["Kai"])["garment"]
    check("old pass 2 overwrites Kai's hairstyle (the finding)",
          (garment.get("mesh_mode"), garment.get("description")), ("body", KAI_TEXT))


def raw_piece(item_id, slots):
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, 'outfit_piece', '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, item_id, json.dumps({"slots": slots})))
    from app.core.motion_item_cache import invalidate
    invalidate()


def modes_world(path: Path):
    open_world(path)
    raw_piece("X", ["top"])
    raw_piece("Y", ["outer"])
    human("A", outfit_body_mode="mesh", equipped_pieces={"top": "X"})
    human("B", outfit_body_mode="mesh", equipped_pieces={"outer": "Y"})


def failing_item_save(item_ids):
    from app.models import inventory
    real = inventory._save_items

    def save(items):
        if any(str(i.get("id")) in item_ids for i in items):
            return False
        return real(items)
    inventory._save_items = save
    return lambda: setattr(inventory, "_save_items", real)


def stored_piece(item_id):
    from app.models import inventory
    return (inventory.get_item(item_id) or {}).get("outfit_piece") or {}


def part_modes(root: Path):
    print("[2] migrate_modes_once")
    from app.models import inventory
    shared_file = root / "shared" / "items" / "items.json"
    shared_file.parent.mkdir(parents=True)
    shared_file.write_text(json.dumps({"items": []}), encoding="utf-8")
    inventory._get_shared_items_file = lambda: shared_file
    modes_world(root / "w2")
    from app.core import figure_migration as fm
    from app.models.character import get_character_profile
    from app.models.world import get_world_setting, set_world_setting
    restore = failing_item_save({"X"})
    try:
        first = fm.migrate_modes_once() or {}
    finally:
        restore()
    check("pass 1: Y judged, X not", first.get("items"), {"Y": "in_body"})
    check("pass 1: only B's key dropped", first.get("profiles"), ["B"])
    check("pass 1: A keeps outfit_body_mode", get_character_profile("A").get("outfit_body_mode"), "mesh")
    check("pass 1: X has no stored mode", stored_piece("X").get("mesh_mode"), None)
    check("pass 1: flag unset", bool(get_world_setting(fm.FLAG)), False)
    before = (rows("characters", "name", ("B",)), rows("items", "id", ("Y",)))
    second = fm.migrate_modes_once() or {}
    check("pass 2: X judged from A's kept key", second.get("items"), {"X": "in_body"})
    check("pass 2: A's key dropped", second.get("profiles"), ["A"])
    check("pass 2: flag set", bool(get_world_setting(fm.FLAG)), True)
    check("pass 2: B and Y byte-identical",
          (rows("characters", "name", ("B",)), rows("items", "id", ("Y",))) == before, True)
    set_world_setting(fm.FLAG, "")
    everything = (rows("characters"), rows("items"))
    third = fm.migrate_modes_once() or {}
    check("pass 3 (flag cleared): nothing", (third.get("items"), third.get("profiles")), ({}, []))
    check("pass 3: every row byte-identical", (rows("characters"), rows("items")) == everything, True)

    print(f"[2] old code ({OLD})")
    modes_world(root / "w2old")
    old = old_module("app/core/figure_migration.py", "figure_migration_old_modes")
    restore = failing_item_save({"X"})
    try:
        old.migrate_modes_once()
    finally:
        restore()
    check("old pass 1: A's key dropped anyway", "outfit_body_mode" in get_character_profile("A"), False)
    check("old pass 1: flag set", bool(get_world_setting(fm.FLAG)), True)
    check("old: the next call does nothing", old.migrate_modes_once(), None)
    check("old: X never gets a mode", stored_piece("X").get("mesh_mode"), None)


def part_hair_flag(root: Path):
    print("[3] delete_all_hair_once")
    open_world(root / "w3")
    from app.core import hair_migration
    from app.core.figure_migration import HAIRSTYLE_FLAG
    from app.models import inventory, world
    from app.models.world import get_world_setting, set_world_setting
    human("Kai", gender="male", height=180, body_slots={"hair": {"length": "short", "color": "black"}})
    hair_item("Kai", "hair_kai", mesh_mode="hairdeck", description="short black hair")
    wear("Kai", "hair_kai")
    set_world_setting(hair_migration.HAIR_FLAG, "1")
    set_world_setting(HAIRSTYLE_FLAG, "1")
    before = (rows("characters"), rows("items"))

    real_conn = world.get_connection

    class Locked:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *a, **kw):
            if "world_kv" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._conn.execute(sql, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    world.get_connection = lambda *a, **kw: Locked(real_conn(*a, **kw))
    try:
        try:
            hair_migration.delete_all_hair_once()
            check("a failed flag read raises", "no error", "OperationalError")
        except sqlite3.OperationalError:
            check("a failed flag read raises", "OperationalError", "OperationalError")
        old_guard = get_world_setting(hair_migration.HAIR_FLAG)
    finally:
        world.get_connection = real_conn
    check("hair_kai still there", inventory.get_item("hair_kai") is not None, True)
    check("nothing written", (rows("characters"), rows("items")) == before, True)
    check("old guard (non-strict read) is falsy under the same failure", bool(old_guard), False)
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(server) if "delete_all_hair_once()" in line and "import" not in line)
    check("the boot call sits in a try", server[at - 2].strip(), "try:")

    check("readable flag: None", hair_migration.delete_all_hair_once(), None)
    check("readable flag again: None", hair_migration.delete_all_hair_once(), None)
    check("run twice: every row byte-identical", (rows("characters"), rows("items")) == before, True)

    # What the old code did after its falsy read: the migration runs on this hairstyle-era world.
    set_world_setting(hair_migration.HAIR_FLAG, "")
    hair_migration.delete_all_hair_once()
    check("a run on this world deletes hair_kai (what the old read led to)", inventory.get_item("hair_kai"), None)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="migration-reruns-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "w1")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        (root / "instance").mkdir()
        from app.core import paths
        paths.init(root / "w1")
        paths.init_instance(root / "instance")
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        open_world(root / "w1")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)
        from app.core import figure_build, garment_assembly
        figure_build.request = lambda *a, **k: True
        garment_assembly.schedule = lambda *a, **k: True
        part_hairstyles(root)
        part_modes(root)
        part_hair_flag(root)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
