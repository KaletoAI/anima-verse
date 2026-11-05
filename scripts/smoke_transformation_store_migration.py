#!/usr/bin/env python3
"""Smoke: the schema migration of ``transformation_definitions`` — a live world
that already has the table from before the persona settings
(``plugins/transformation/store.py::ensure_schema``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_store_migration.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any world-DB module is
imported), no server, no real world DB, no LLM, the package is not loaded
(``ensure_schema`` is what its ``on_load`` runs first).

FIXTURE
    The OLD table, verbatim the CREATE of commit ede03740 (13 columns, id ..
    updated_at), with one row: id "moon", item "brooch", alias "Moonveil",
    description "A masked figure.", suit '["mask"]', every other column its
    default.

THE RULES (task brief), and what follows BY HAND
[A] ``ensure_schema()`` adds the three missing columns at the END (SQLite's
    ADD COLUMN appends), with NOT NULL and their defaults:
        prompt_overrides TEXT  DEFAULT '{}'
        pause_routine    INTEGER DEFAULT 1
        imagegen         TEXT  DEFAULT '{}'
    -> 16 columns; the old row reads raw ('{}', 1, '{}').
[B] The row still reads through the store: alias "Moonveil", description
    "A masked figure.", suit ["mask"], max 60, cooldown 30, enabled True,
    prompt_overrides {}, pause_routine True, imagegen = the full empty shape
    {"workflow": "", "tpose_workflow": "", "loras": [], "tpose_loras": []}.
    ``definitions.load()`` keeps it (no character "Moonveil" exists) with the
    same three values.
[C] A second ``ensure_schema()`` changes nothing (still 16 columns, row
    unchanged).
[D] A write of the new columns lands: update_definition(moon,
    {pause_routine: False, prompt_overrides: {character_goals: "Win."}}) ->
    raw (0, '{"character_goals": "Win."}').
[E] A FRESH table (dropped, ensure_schema again) has exactly the migrated
    column list — same names, order, types, NOT NULL and defaults — so a new
    world and a migrated one cannot drift.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-migration-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
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


def columns():
    """(name, type, notnull, default) per column, in table order."""
    return [(r[1], r[2], r[3], r[4]) for r in get_connection().execute(
        "PRAGMA table_info(transformation_definitions)").fetchall()]


def raw_new(pid="moon"):
    return tuple(get_connection().execute(
        "SELECT prompt_overrides, pause_routine, imagegen FROM transformation_definitions "
        "WHERE id=?", (pid,)).fetchone())


# The table as commit ede03740 created it (defaults 60 / 30 / 'transforming').
with transaction() as _conn:
    _conn.execute("""CREATE TABLE IF NOT EXISTS transformation_definitions (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL UNIQUE,
            alias TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            activation_phrase TEXT NOT NULL DEFAULT '',
            revert_phrase TEXT NOT NULL DEFAULT '',
            suit_items TEXT NOT NULL DEFAULT '[]',
            condition_id TEXT NOT NULL DEFAULT '',
            max_duration_minutes INTEGER NOT NULL DEFAULT 60,
            cooldown_minutes INTEGER NOT NULL DEFAULT 30,
            transform_activity TEXT NOT NULL DEFAULT 'transforming',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT '')""")
    _conn.execute("INSERT INTO transformation_definitions (id, item_id, alias, description, "
                  "suit_items) VALUES ('moon', 'brooch', 'Moonveil', 'A masked figure.', "
                  "'[\"mask\"]')")
check("old shape", len(columns()), 13)

from plugins.transformation import definitions, store  # noqa: E402

# ── [A] migration ───────────────────────────────────────────────────────────
print("[A] ensure_schema migrates")
store.ensure_schema()
_cols = columns()
check("column count", len(_cols), 16)
check("new columns at the end", _cols[13:], [
    ("prompt_overrides", "TEXT", 1, "'{}'"),
    ("pause_routine", "INTEGER", 1, "1"),
    ("imagegen", "TEXT", 1, "'{}'"),
])
check("old row raw", raw_new(), ("{}", 1, "{}"))

# ── [B] the row reads ───────────────────────────────────────────────────────
print("[B] old row reads")
_row = store.get_definition("moon")
check("old fields", {k: _row[k] for k in ("alias", "description", "suit_items",
                                          "max_duration_minutes", "cooldown_minutes", "enabled")},
      {"alias": "Moonveil", "description": "A masked figure.", "suit_items": ["mask"],
       "max_duration_minutes": 60, "cooldown_minutes": 30, "enabled": True})
_EMPTY_IMAGE = {"workflow": "", "tpose_workflow": "", "loras": [], "tpose_loras": []}
check("new fields", (_row["prompt_overrides"], _row["pause_routine"], _row["imagegen"]),
      ({}, True, _EMPTY_IMAGE))
_d = definitions.load().get("moon")
check("definitions.load keeps it", _d is not None, True)
check("definition values", (_d.prompt_overrides, _d.pause_routine, _d.imagegen),
      ({}, True, _EMPTY_IMAGE))

# ── [C] idempotent ──────────────────────────────────────────────────────────
print("[C] second ensure_schema")
store.ensure_schema()
check("still 16 columns", columns(), _cols)
check("row unchanged", raw_new(), ("{}", 1, "{}"))

# ── [D] writes ──────────────────────────────────────────────────────────────
print("[D] write the new columns")
check("update", store.update_definition(
    "moon", {"pause_routine": False, "prompt_overrides": {"character_goals": "Win."}}), True)
_po, _pr, _ig = raw_new()
check("raw after update", (json.loads(_po), _pr, json.loads(_ig)),
      ({"character_goals": "Win."}, 0, {}))

# ── [E] fresh = migrated ────────────────────────────────────────────────────
print("[E] fresh table")
with transaction() as _conn:
    _conn.execute("DROP TABLE transformation_definitions")
store.ensure_schema()
check("fresh columns = migrated columns", columns(), _cols)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
