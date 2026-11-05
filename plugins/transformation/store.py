"""Transformation definitions, active transformations and cooldowns, in the world DB.

Three package tables (prefix ``transformation_``); the LEADER is stored in the
column ``character_name`` of all three, so the core's character-deletion sweep
(``app.models.character.delete_character``) removes a deleted leader's rows
like every other per-character table. The API calls that column ``leader``.

* ``transformation_definitions`` — world content, edited on the leader's
  Transformation panel (Game-Admin → Characters → <leader> → Skills). One row
  per (leader, power item) — ``UNIQUE(character_name, item_id)`` — naming the
  linked character (``body``) the leader turns into. Not part of the reset
  store. Rows are stored as written; the usability rules (disabled,
  incomplete) belong to ``definitions.load()``, the save rules to the panel.
* ``transformation_active`` — the family's current transformation, keyed by
  the leader: ``{leader, body, def_id, started_game, until_game, snapshot}``.
* ``transformation_cooldown`` — per (leader, definition): until when a new
  transformation is refused (GAME time).

A table of an earlier shape (persona definitions with ``alias``; active and
cooldown rows keyed by ``persona_id``) is DROPPED and re-created — there is no
data migration (user decision: no compatibility with the persona test data).

Reads of the active rows go through an in-memory ``{leader: ActiveRow}``
cache (the verbs ask on every turn). Every write invalidates it AFTER its
commit; a rebuild captures the generation before it reads the table and
publishes only when no write happened meanwhile, so a stale snapshot never
lands in the cache.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger("transformation")


@dataclass(frozen=True)
class ActiveRow:
    """A family's current transformation (keyed by the leader)."""
    leader: str
    body: str
    def_id: str
    started_game: str                      # GameTime canonical stamp
    until_game: str = ""                   # GameTime canonical stamp; "" = until reverted
    #: What a revert needs even when the definition was edited meanwhile:
    #: ``item_id`` and ``condition_id`` as applied, ``pose_key`` the transform
    #: activity resolved to on the body.
    snapshot: Dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_generation = 0
_cache: Optional[Dict[str, ActiveRow]] = None

#: The columns each table must have — a table missing one is of an older
#: shape (the persona era) and is re-created.
_SHAPE = {
    "transformation_definitions": ("character_name", "body", "item_id"),
    "transformation_active": ("character_name", "body", "def_id", "snapshot"),
    "transformation_cooldown": ("character_name", "def_id"),
}


def _drop_old_shapes(conn) -> None:
    for table, needed in _SHAPE.items():
        have = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if have and any(c not in have for c in needed):
            logger.warning("transformation: table %s has an old shape — dropped and re-created "
                           "(no data migration)", table)
            conn.execute(f"DROP TABLE {table}")


def ensure_schema() -> None:
    from plugins.transformation.definitions import (DEFAULT_COOLDOWN_MINUTES,
                                                    DEFAULT_MAX_DURATION_MINUTES,
                                                    DEFAULT_TRANSFORM_ACTIVITY)
    activity = DEFAULT_TRANSFORM_ACTIVITY.replace("'", "''")
    with transaction() as conn:
        _drop_old_shapes(conn)
        conn.execute(f"""CREATE TABLE IF NOT EXISTS transformation_definitions (
            id TEXT PRIMARY KEY,
            character_name TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            item_id TEXT NOT NULL,
            activation_phrase TEXT NOT NULL DEFAULT '',
            revert_phrase TEXT NOT NULL DEFAULT '',
            max_duration_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_MAX_DURATION_MINUTES)},
            cooldown_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_COOLDOWN_MINUTES)},
            transform_activity TEXT NOT NULL DEFAULT '{activity}',
            condition_id TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT '',
            UNIQUE(character_name, item_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transformation_active (
            character_name TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            def_id TEXT NOT NULL,
            started_game TEXT NOT NULL,
            until_game TEXT NOT NULL DEFAULT '',
            snapshot TEXT NOT NULL DEFAULT '{}')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transformation_cooldown (
            character_name TEXT,
            def_id TEXT,
            until_game TEXT NOT NULL,
            PRIMARY KEY(character_name, def_id))""")
    _bump_definitions()


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


_ACTIVE_COLS = "character_name, body, def_id, started_game, until_game, snapshot"


def _row(r) -> ActiveRow:
    return ActiveRow(leader=r[0], body=r[1] or "", def_id=r[2] or "", started_game=r[3] or "",
                     until_game=r[4] or "", snapshot=_json(r[5], {}))


def _active_map() -> Dict[str, ActiveRow]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        generation = _generation
    rows = get_connection().execute(
        f"SELECT {_ACTIVE_COLS} FROM transformation_active").fetchall()
    built = {r[0]: _row(r) for r in rows}
    with _lock:
        if _generation == generation:
            _cache = built
    return built


def get_active(leader: str) -> Optional[ActiveRow]:
    """The leader's current transformation, or ``None``."""
    if not leader:
        return None
    return _active_map().get(leader)


def active_of_body(body: str) -> Optional[ActiveRow]:
    """The transformation that put ``body`` into the world, or ``None``."""
    if not body:
        return None
    return next((r for r in _active_map().values() if r.body == body), None)


def all_active() -> List[ActiveRow]:
    return list(_active_map().values())


def set_active(row: ActiveRow) -> None:
    """Insert or replace the leader's active transformation."""
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"INSERT OR REPLACE INTO transformation_active ({_ACTIVE_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row.leader, row.body, row.def_id, row.started_game, row.until_game,
                 json.dumps(row.snapshot, ensure_ascii=False)))
    finally:
        invalidate()


def clear_active(leader: str) -> None:
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM transformation_active WHERE character_name=?", (leader,))
    finally:
        invalidate()


def cooldown_until(leader: str, def_id: str) -> str:
    """The GameTime canonical stamp the cooldown runs until, or ``""``."""
    r = get_connection().execute(
        "SELECT until_game FROM transformation_cooldown WHERE character_name=? AND def_id=?",
        (leader, def_id)).fetchone()
    return (r[0] or "") if r else ""


def set_cooldown(leader: str, def_id: str, until_game: str) -> None:
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO transformation_cooldown (character_name, def_id, "
                "until_game) VALUES (?, ?, ?)", (leader, def_id, until_game))
    finally:
        invalidate()


def delete_character_rows(conn, name: str) -> int:
    """Delete the leader's active row and cooldowns on ``conn`` (no commit) and
    return how many went. For the character-reset handler (a body owns no rows)."""
    count = 0
    for table in ("transformation_active", "transformation_cooldown"):
        count += conn.execute(f"DELETE FROM {table} WHERE character_name=?", (name,)).rowcount
    return count


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

#: The written fields of a definition (all but ``id`` and ``updated_at``), in
#: column order, as ``(dict key, column)``.
DEFINITION_COLUMNS = (
    ("leader", "character_name"), ("body", "body"), ("item_id", "item_id"),
    ("activation_phrase", "activation_phrase"), ("revert_phrase", "revert_phrase"),
    ("max_duration_minutes", "max_duration_minutes"), ("cooldown_minutes", "cooldown_minutes"),
    ("transform_activity", "transform_activity"), ("condition_id", "condition_id"),
    ("enabled", "enabled"),
)
#: The dict keys of :data:`DEFINITION_COLUMNS`.
DEFINITION_FIELDS = tuple(key for key, _col in DEFINITION_COLUMNS)
_COLUMN = dict(DEFINITION_COLUMNS)
_INT_FIELDS = frozenset({"max_duration_minutes", "cooldown_minutes"})

_def_lock = threading.Lock()
_def_generation = 0


def definitions_generation() -> int:
    """Bumped after every definition write (after its commit) — the cache key
    of ``definitions.load()``."""
    with _def_lock:
        return _def_generation


def _bump_definitions() -> None:
    global _def_generation
    with _def_lock:
        _def_generation += 1


def _column_value(key: str, value: Any) -> Any:
    if key == "enabled":
        return 1 if value else 0
    if key in _INT_FIELDS:
        return max(0, int(value))
    return "" if value is None else str(value).strip()


def _definition_row(r) -> Dict[str, Any]:
    c = dict(zip(("id",) + DEFINITION_FIELDS + ("updated_at",), r))
    out: Dict[str, Any] = {"id": c["id"]}
    for key in DEFINITION_FIELDS:
        if key == "enabled":
            out[key] = bool(c[key])
        elif key in _INT_FIELDS:
            out[key] = int(c[key] or 0)
        else:
            out[key] = c[key] or ""
    out["updated_at"] = c["updated_at"] or ""
    return out


_SELECT_DEFINITIONS = ("SELECT id, " + ", ".join(col for _k, col in DEFINITION_COLUMNS)
                       + ", updated_at FROM transformation_definitions")


def list_definitions(*, leader: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every stored definition (or only ``leader``'s) as a dict, in creation order."""
    if leader is None:
        rows = get_connection().execute(_SELECT_DEFINITIONS + " ORDER BY rowid").fetchall()
    else:
        rows = get_connection().execute(
            _SELECT_DEFINITIONS + " WHERE character_name=? ORDER BY rowid", (leader,)).fetchall()
    return [_definition_row(r) for r in rows]


def get_definition(def_id: str) -> Optional[Dict[str, Any]]:
    """One stored definition, or ``None``."""
    if not def_id:
        return None
    r = get_connection().execute(_SELECT_DEFINITIONS + " WHERE id=?", (def_id,)).fetchone()
    return _definition_row(r) if r else None


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "transformation"


def create_definition(record: Dict[str, Any], *, def_id: str = "") -> str:
    """Insert a definition and return its id.

    ``def_id`` empty = a slug of the body's name, made unique with ``_2``,
    ``_3``, ...; stable afterwards. Missing columns take the table defaults
    (the constants in ``definitions``). Raises ``sqlite3.IntegrityError`` for
    an id that is taken or an item the leader already uses. No usability
    checks here."""
    keys = [k for k in DEFINITION_FIELDS if k in record]
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            did = (def_id or "").strip()
            if not did:
                base = _slug(str(record.get("body") or ""))
                taken = {r[0] for r in conn.execute(
                    "SELECT id FROM transformation_definitions").fetchall()}
                did, n = base, 1
                while did in taken:
                    n += 1
                    did = f"{base}_{n}"
            conn.execute(
                "INSERT INTO transformation_definitions (id, "
                + "".join(_COLUMN[k] + ", " for k in keys)
                + "updated_at) VALUES (" + "?, " * (len(keys) + 1) + "?)",
                (did, *[_column_value(k, record[k]) for k in keys], utc_now_iso()))
    finally:
        _bump_definitions()
    return did


def update_definition(def_id: str, changes: Dict[str, Any]) -> bool:
    """Write the given fields of one definition. False when it does not exist.
    Raises ``sqlite3.IntegrityError`` for an item the leader already uses."""
    keys = [k for k in DEFINITION_FIELDS if k in changes]
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE transformation_definitions SET "
                + "".join(_COLUMN[k] + "=?, " for k in keys) + "updated_at=? WHERE id=?",
                (*[_column_value(k, changes[k]) for k in keys], utc_now_iso(), def_id))
            return cur.rowcount > 0
    finally:
        _bump_definitions()


def delete_definition(def_id: str) -> bool:
    """Delete one definition and its cooldowns. False when it did not exist.
    The knower secrets belong to the BODY (``knowers``) and stay."""
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM transformation_definitions WHERE id=?", (def_id,))
            conn.execute("DELETE FROM transformation_cooldown WHERE def_id=?", (def_id,))
            return cur.rowcount > 0
    finally:
        _bump_definitions()
        invalidate()
