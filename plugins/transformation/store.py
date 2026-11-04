"""Active transformations and cooldowns, in the world DB.

Two package tables (prefix ``transformation_``). The character column is
named ``character_name`` so the character-deletion sweep
(``app.models.character.delete_character``) removes the rows like every other
per-character table; the API calls that character the ``bearer``.

Reads go through an in-memory ``{bearer: ActiveRow}`` cache (the identity
providers ask for every name of every prompt). Every write invalidates it
AFTER its commit; a rebuild captures the generation before it reads the table
and publishes only when no write happened meanwhile, so a stale snapshot never
lands in the cache.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction


@dataclass(frozen=True)
class ActiveRow:
    """One character's current transformation."""
    bearer: str
    persona_id: str
    started_game: str                      # GameTime canonical stamp
    until_game: str = ""                   # GameTime canonical stamp; "" = until reverted
    outfit_snapshot: Dict[str, Any] = field(default_factory=dict)
    granted_items: Tuple[str, ...] = ()
    lock_before: bool = False


_lock = threading.Lock()
_generation = 0
_cache: Optional[Dict[str, ActiveRow]] = None


def ensure_schema() -> None:
    with transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS transformation_active (
            character_name TEXT PRIMARY KEY,
            persona_id TEXT NOT NULL,
            started_game TEXT NOT NULL,
            until_game TEXT NOT NULL DEFAULT '',
            outfit_snapshot TEXT NOT NULL DEFAULT '{}',
            granted_items TEXT NOT NULL DEFAULT '[]',
            lock_before INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transformation_cooldown (
            character_name TEXT,
            persona_id TEXT,
            until_game TEXT NOT NULL,
            PRIMARY KEY(character_name, persona_id))""")


def invalidate() -> None:
    """Drop the cache; the next read rebuilds it from the table."""
    global _cache, _generation
    with _lock:
        _generation += 1
        _cache = None


def _json(text: Any, fallback: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _row(r) -> ActiveRow:
    return ActiveRow(
        bearer=r[0], persona_id=r[1], started_game=r[2] or "", until_game=r[3] or "",
        outfit_snapshot=_json(r[4], {}),
        granted_items=tuple(str(i) for i in _json(r[5], [])),
        lock_before=bool(r[6]))


def _active_map() -> Dict[str, ActiveRow]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        generation = _generation
    rows = get_connection().execute(
        "SELECT character_name, persona_id, started_game, until_game, outfit_snapshot, "
        "granted_items, lock_before FROM transformation_active").fetchall()
    built = {r[0]: _row(r) for r in rows}
    with _lock:
        if _generation == generation:
            _cache = built
    return built


def get_active(bearer: str) -> Optional[ActiveRow]:
    """The character's current transformation, or ``None``."""
    if not bearer:
        return None
    return _active_map().get(bearer)


def all_active() -> List[ActiveRow]:
    return list(_active_map().values())


def set_active(row: ActiveRow) -> None:
    """Insert or replace the character's active transformation."""
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO transformation_active (character_name, persona_id, "
                "started_game, until_game, outfit_snapshot, granted_items, lock_before) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row.bearer, row.persona_id, row.started_game, row.until_game,
                 json.dumps(row.outfit_snapshot, ensure_ascii=False),
                 json.dumps(list(row.granted_items), ensure_ascii=False),
                 1 if row.lock_before else 0))
    finally:
        invalidate()


def clear_active(bearer: str) -> None:
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM transformation_active WHERE character_name=?", (bearer,))
    finally:
        invalidate()


def cooldown_until(bearer: str, persona_id: str) -> str:
    """The GameTime canonical stamp the cooldown runs until, or ``""``."""
    r = get_connection().execute(
        "SELECT until_game FROM transformation_cooldown WHERE character_name=? AND persona_id=?",
        (bearer, persona_id)).fetchone()
    return (r[0] or "") if r else ""


def set_cooldown(bearer: str, persona_id: str, until_game: str) -> None:
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO transformation_cooldown (character_name, persona_id, until_game) "
                "VALUES (?, ?, ?)", (bearer, persona_id, until_game))
    finally:
        invalidate()


def delete_character_rows(conn, bearer: str) -> int:
    """Delete the character's rows of both tables on ``conn`` (no commit) and
    return how many went. For the character-reset handler."""
    count = 0
    for table in ("transformation_active", "transformation_cooldown"):
        count += conn.execute(f"DELETE FROM {table} WHERE character_name=?", (bearer,)).rowcount
    return count
