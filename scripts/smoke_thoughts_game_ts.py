#!/usr/bin/env python3
"""Smoke check: the ``thoughts.game_ts`` migration + INSERT/SELECT round-trip.

Usage:
    ./.venv/bin/python scripts/smoke_thoughts_game_ts.py

Runs WITHOUT the server and WITHOUT a world DB: it builds a throw-away SQLite
file in a temp dir, replays exactly what ``db.init_schema()`` does for the
``thoughts`` table (the CREATE statement out of ``SCHEMA_STATEMENTS`` plus the
``ALTER_MIGRATIONS`` entries, the ALTER wrapped in the same
``sqlite3.OperationalError`` pass), and then exercises the two shapes the app
produces.

Expected values, derived by hand from the change (plan-parallel-bump-lane.md
Task 1, steps 1-3) — NOT recorded from a run:

  1. ``ALTER_MIGRATIONS`` contains the pair ("thoughts", "game_ts") exactly
     once, and the CREATE TABLE text does NOT mention game_ts (the column is
     migration-only, same convention as ``present``).
  2. Applying the migrations twice must not raise and must not duplicate the
     column: after two passes, PRAGMA table_info(thoughts) contains exactly one
     ``game_ts`` row. Column declaration is TEXT with default ''.
  3. Column set after migration ⊇ {id, character_name, ts, game_ts,
     location_id, room_id, content, present}.
  4. New row — the INSERT of ``thought_store.add_thought`` writes 7 values with
     ``game_ts`` in third position. ``game_ts`` is a CANONICAL game stamp
     (``Y0002-D109T14:23:45``), not an ISO datetime — the game clock runs on
     the world calendar and has no timezone. Inserting it must read back
     byte-identically (SQLite TEXT, no normalisation anywhere in the path).
  5. Old row — a row inserted the pre-migration way (columns listed WITHOUT
     game_ts) must yield '' for game_ts, never NULL: the ALTER declares
     ``DEFAULT ''``. The route maps with ``r.get("game_ts", "") or ""``, so ''
     is what the UI sees and the UI hides the game clock for it.
  6. The SELECT column list of ``list_thoughts`` (id, ts, game_ts,
     location_id, room_id, content, present) must execute against the migrated
     table and return, for the two rows above, game_ts values
     ['Y0002-D109T14:23:45', ''].

Exit code 0 = all checks passed; any failure prints FAIL and exits 1.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.world_db_schema import ALTER_MIGRATIONS, SCHEMA_STATEMENTS  # noqa: E402

GAME_TS = "Y0002-D109T14:23:45"   # canonical GameTime, not an ISO stamp

_failures: list[str] = []


def check(label: str, got, expected) -> None:
    ok = got == expected
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        _failures.append(label)


def thoughts_create_stmt() -> str:
    for stmt in SCHEMA_STATEMENTS:
        if "CREATE TABLE IF NOT EXISTS thoughts" in stmt:
            return stmt
    raise SystemExit("FAIL: no CREATE TABLE for 'thoughts' in SCHEMA_STATEMENTS")


def apply_alters(conn: sqlite3.Connection) -> None:
    """Same loop as db.init_schema() — an already-present column is a no-op."""
    for table, column, typedef in ALTER_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        except sqlite3.OperationalError:
            pass


def main() -> int:
    create = thoughts_create_stmt()

    # (1) declaration lives in ALTER_MIGRATIONS only
    entries = [e for e in ALTER_MIGRATIONS if e[0] == "thoughts" and e[1] == "game_ts"]
    check("game_ts entries in ALTER_MIGRATIONS", len(entries), 1)
    check("game_ts typedef", entries[0][2] if entries else None, "TEXT DEFAULT ''")
    check("game_ts absent from CREATE TABLE", "game_ts" in create, False)

    with tempfile.TemporaryDirectory() as tmp:
        conn = sqlite3.connect(os.path.join(tmp, "smoke.db"))
        conn.row_factory = sqlite3.Row
        conn.execute(create)

        # (5) an old row, written before the column existed
        conn.execute(
            "INSERT INTO thoughts (character_name, ts, location_id, room_id,"
            " content) VALUES (?, ?, ?, ?, ?)",
            ("demo", "2026-07-29T08:00:00+00:00", "loc1", "room1", "old row"))

        # (2) migrations are idempotent
        apply_alters(conn)
        apply_alters(conn)

        cols = [r["name"] for r in conn.execute("PRAGMA table_info(thoughts)")]
        check("game_ts column count after two passes", cols.count("game_ts"), 1)
        check("column set complete",
              {"id", "character_name", "ts", "game_ts", "location_id",
               "room_id", "content", "present"}.issubset(set(cols)), True)
        decl = {r["name"]: (r["type"], r["dflt_value"])
                for r in conn.execute("PRAGMA table_info(thoughts)")}
        check("game_ts declaration", decl.get("game_ts"), ("TEXT", "''"))

        # (4) a new row, written the way add_thought writes it
        conn.execute(
            "INSERT INTO thoughts (character_name, ts, game_ts, location_id,"
            " room_id, content, present) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("demo", "2026-07-30T12:23:45+00:00", GAME_TS, "loc1", "room1",
             "new row", ""))

        # (6) the SELECT column list of list_thoughts
        rows = conn.execute(
            "SELECT id, ts, game_ts, location_id, room_id, content, present"
            " FROM thoughts WHERE character_name=? ORDER BY ts DESC, id DESC",
            ("demo",)).fetchall()
        check("rows returned", len(rows), 2)
        check("game_ts values (newest first)",
              [r["game_ts"] for r in rows], [GAME_TS, ""])
        check("new row round-trips byte-identically", rows[0]["game_ts"], GAME_TS)
        check("old row is '' and not NULL",
              (rows[1]["game_ts"], rows[1]["game_ts"] is None), ("", False))
        conn.close()

    if _failures:
        print(f"\n{len(_failures)} check(s) FAILED: {', '.join(_failures)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
