#!/usr/bin/env python3
"""Smoke: the transformation tables (``plugins/transformation/store.py``) and
the definition loader (``definitions.py``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_store.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world.

THE SPEC (``docs/superpowers/specs/2026-11-05-linked-characters-design.md`` →
"Transformation package"): a definition is ``{id, leader, body, item_id,
activation_phrase, revert_phrase, max_duration_minutes, cooldown_minutes,
transform_activity, condition_id, enabled}`` — ``alias``, ``description``,
``suit_items``, ``prompt_overrides``, ``pause_routine``, ``imagegen`` are gone.
The table is RE-CREATED in that shape (no data migration: a table of the old
shape is dropped). The active row is ``{leader, body, def_id, started_game,
...}``. The leader is stored in the column ``character_name`` of all three
tables, so the core's character-deletion sweep removes a deleted leader's rows.

THE RULES, and what follows BY HAND
[A] Old shape: the three tables as the reduced package (6f3278ad) created them
    — definitions with ``alias``, active with ``persona_id`` and
    ``outfit_snapshot``, cooldown with ``persona_id`` — each holding one row.
    ``ensure_schema()`` drops and re-creates them:
      definitions columns == [id, character_name, body, item_id,
        activation_phrase, revert_phrase, max_duration_minutes,
        cooldown_minutes, transform_activity, condition_id, enabled, updated_at]
      active columns == [character_name, body, def_id, started_game,
        until_game, snapshot]
      cooldown columns == [character_name, def_id, until_game]
    and all three are empty. A second ``ensure_schema()`` after a create keeps
    the row (idempotent, 1 row).
[B] create {"leader": "Tilda", "body": "Glut", "item_id": "amulet"} -> id
    "glut" (slug of the body). Stored dict: exactly the keys id, leader, body,
    item_id, activation_phrase "", revert_phrase "", max_duration_minutes 60,
    cooldown_minutes 30, transform_activity "transforming", condition_id "",
    enabled True, updated_at (non-empty).
    Tilda/Glut/ring -> "glut_2" (the slug repeats); Tilda/Ember/amulet ->
    sqlite3.IntegrityError (one definition per leader and item); Hans/Hero/
    amulet -> "hero" (another leader may use the same item).
[C] list_definitions() -> ids [glut, glut_2, hero] (creation order);
    list_definitions(leader="Tilda") -> [glut, glut_2].
    update glut activation_phrase "  by fire " -> True, stored "by fire";
    update "nope" -> False; glut_2 item -> amulet -> IntegrityError.
[D] definitions.load(): glut_2 disabled -> keys {glut, hero}. A row written
    by hand with body "" (id "broken", leader Tilda, item "token") -> skipped.
    glut == Definition(id glut, leader Tilda, body Glut, item_id amulet,
    activation_phrase "by fire", revert_phrase "", max 60, cooldown 30,
    transform_activity "transforming", condition_id "", enabled True).
    for_leader("Tilda") -> [glut]; for_body("Glut") -> [glut];
    for_leader("Glut") -> [].
[E] Active rows: set_active(Tilda, body Glut, def glut, 12:00, until 13:00,
    snapshot {"item_id": "amulet"}) -> get_active("Tilda") is that row,
    active_of_body("Glut") the same, get_active("Glut") None, all_active() 1.
    set_cooldown(Tilda, glut, "Y0002-D100T13:30:00") -> cooldown_until the
    same; delete_definition("glut") -> True and its cooldown is gone ("").
    set_cooldown(Tilda, glut_2, ...) then delete_character_rows(conn, Tilda)
    -> 2 (the active row + that cooldown); get_active("Tilda") None.
[F] Deletion sweep: delete_character("Hans") removes the definition "hero"
    (its leader column is character_name).
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-store-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.db import get_connection, transaction  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def columns(table):
    return [r[1] for r in get_connection().execute(f"PRAGMA table_info({table})")]


def count(table):
    return get_connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    return False


# ── [A] the old shape is dropped and re-created ────────────────────────────
print("[A] old shape -> re-created")
with transaction() as conn:
    conn.execute("""CREATE TABLE transformation_definitions (
        id TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE, alias TEXT NOT NULL DEFAULT '',
        activation_phrase TEXT NOT NULL DEFAULT '', revert_phrase TEXT NOT NULL DEFAULT '',
        condition_id TEXT NOT NULL DEFAULT '', max_duration_minutes INTEGER NOT NULL DEFAULT 60,
        cooldown_minutes INTEGER NOT NULL DEFAULT 30,
        transform_activity TEXT NOT NULL DEFAULT 'transforming',
        enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT '')""")
    conn.execute("INSERT INTO transformation_definitions (id, item_id, alias) "
                 "VALUES ('moonveil', 'amulet', 'Moonveil')")
    conn.execute("""CREATE TABLE transformation_active (
        character_name TEXT PRIMARY KEY, persona_id TEXT NOT NULL, started_game TEXT NOT NULL,
        until_game TEXT NOT NULL DEFAULT '', outfit_snapshot TEXT NOT NULL DEFAULT '{}')""")
    conn.execute("INSERT INTO transformation_active (character_name, persona_id, started_game) "
                 "VALUES ('Cara', 'moonveil', 'Y0002-D100T12:00:00')")
    conn.execute("""CREATE TABLE transformation_cooldown (
        character_name TEXT, persona_id TEXT, until_game TEXT NOT NULL,
        PRIMARY KEY(character_name, persona_id))""")
    conn.execute("INSERT INTO transformation_cooldown VALUES ('Cara', 'moonveil', 'x')")

from plugins.transformation import definitions, store  # noqa: E402
from plugins.transformation.definitions import Definition  # noqa: E402
from plugins.transformation.store import ActiveRow  # noqa: E402

store.ensure_schema()
store.invalidate()
definitions.invalidate()
check("definitions columns", columns("transformation_definitions"),
      ["id", "character_name", "body", "item_id", "activation_phrase", "revert_phrase",
       "max_duration_minutes", "cooldown_minutes", "transform_activity", "condition_id",
       "enabled", "updated_at"])
check("active columns", columns("transformation_active"),
      ["character_name", "body", "def_id", "started_game", "until_game", "snapshot"])
check("cooldown columns", columns("transformation_cooldown"),
      ["character_name", "def_id", "until_game"])
check("old rows gone", [count(t) for t in ("transformation_definitions", "transformation_active",
                                           "transformation_cooldown")], [0, 0, 0])

# ── [B] create ──────────────────────────────────────────────────────────────
print("[B] create")
check("first id", store.create_definition({"leader": "Tilda", "body": "Glut",
                                           "item_id": "amulet"}), "glut")
store.ensure_schema()
check("ensure_schema again keeps the row", count("transformation_definitions"), 1)
_g = store.get_definition("glut") or {}
check("stored keys", sorted(_g), sorted([
    "id", "leader", "body", "item_id", "activation_phrase", "revert_phrase",
    "max_duration_minutes", "cooldown_minutes", "transform_activity", "condition_id",
    "enabled", "updated_at"]))
check("stored values", {k: v for k, v in _g.items() if k != "updated_at"}, {
    "id": "glut", "leader": "Tilda", "body": "Glut", "item_id": "amulet",
    "activation_phrase": "", "revert_phrase": "", "max_duration_minutes": 60,
    "cooldown_minutes": 30, "transform_activity": "transforming", "condition_id": "",
    "enabled": True})
check("updated_at set", bool(_g.get("updated_at")), True)
check("second id for the same body", store.create_definition(
    {"leader": "Tilda", "body": "Glut", "item_id": "ring"}), "glut_2")
check("same leader + item refused", raises(lambda: store.create_definition(
    {"leader": "Tilda", "body": "Ember", "item_id": "amulet"}), sqlite3.IntegrityError), True)
check("another leader may use the item", store.create_definition(
    {"leader": "Hans", "body": "Hero", "item_id": "amulet"}), "hero")

# ── [C] list / update ───────────────────────────────────────────────────────
print("[C] list / update")
check("all ids", [d["id"] for d in store.list_definitions()], ["glut", "glut_2", "hero"])
check("Tilda's ids", [d["id"] for d in store.list_definitions(leader="Tilda")],
      ["glut", "glut_2"])
check("update", store.update_definition("glut", {"activation_phrase": "  by fire "}), True)
check("stored stripped", store.get_definition("glut")["activation_phrase"], "by fire")
check("update unknown", store.update_definition("nope", {"revert_phrase": "x"}), False)
check("update to a taken item refused", raises(lambda: store.update_definition(
    "glut_2", {"item_id": "amulet"}), sqlite3.IntegrityError), True)

# ── [D] load ────────────────────────────────────────────────────────────────
print("[D] definitions.load")
store.update_definition("glut_2", {"enabled": False})
with transaction() as conn:
    conn.execute("INSERT INTO transformation_definitions (id, character_name, body, item_id) "
                 "VALUES ('broken', 'Tilda', '', 'token')")
store._bump_definitions()
_defs = definitions.load()
check("usable ids", sorted(_defs), ["glut", "hero"])
check("glut parsed", _defs.get("glut"), Definition(
    id="glut", leader="Tilda", body="Glut", item_id="amulet", activation_phrase="by fire",
    revert_phrase="", max_duration_minutes=60, cooldown_minutes=30,
    transform_activity="transforming", condition_id="", enabled=True))
check("for_leader Tilda", [d.id for d in definitions.for_leader("Tilda")], ["glut"])
check("for_body Glut", [d.id for d in definitions.for_body("Glut")], ["glut"])
check("for_leader Glut", definitions.for_leader("Glut"), [])

# ── [E] active rows + cooldowns ─────────────────────────────────────────────
print("[E] active rows")
_row = ActiveRow(leader="Tilda", body="Glut", def_id="glut", started_game="Y0002-D100T12:00:00",
                 until_game="Y0002-D100T13:00:00", snapshot={"item_id": "amulet"})
store.set_active(_row)
check("get_active", store.get_active("Tilda"), _row)
check("active_of_body", store.active_of_body("Glut"), _row)
check("not keyed by the body", store.get_active("Glut"), None)
check("all_active", len(store.all_active()), 1)
store.set_cooldown("Tilda", "glut", "Y0002-D100T13:30:00")
check("cooldown", store.cooldown_until("Tilda", "glut"), "Y0002-D100T13:30:00")
check("delete glut", store.delete_definition("glut"), True)
check("its cooldown gone", store.cooldown_until("Tilda", "glut"), "")
store.set_cooldown("Tilda", "glut_2", "Y0002-D100T13:30:00")
with transaction() as conn:
    _n = store.delete_character_rows(conn, "Tilda")
store.invalidate()
check("reset rows", _n, 2)
check("active gone", store.get_active("Tilda"), None)

# ── [F] deletion sweep ──────────────────────────────────────────────────────
print("[F] deletion sweep")
from app.models.character import delete_character, save_character_profile  # noqa: E402
assert save_character_profile("Hans", {"character_name": "Hans", "template": "human-roleplay"},
                              create_new=True)
check("hero before", store.get_definition("hero") is not None, True)
delete_character("Hans")
store._bump_definitions()
check("hero swept with its leader", store.get_definition("hero"), None)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
