"""Persona definitions, active transformations and cooldowns, in the world DB.

Three package tables (prefix ``transformation_``):

* ``transformation_definitions`` — the personas (world content, edited in
  Game-Admin → Characters → <character> → Skills → Transformation). One row
  per persona, bound to its power item (``item_id`` is UNIQUE). Not part of
  the reset store: a memory wipe of a character never touches world content.
  Rows are stored as written; the usability rules (disabled, incomplete)
  belong to ``definitions.load()``, the save rules to the panel.
* ``transformation_active`` / ``transformation_cooldown`` — per-character
  state. The character column is named ``character_name`` so the
  character-deletion sweep (``app.models.character.delete_character``)
  removes the rows like every other per-character table; the API calls that
  character the ``bearer``.

Tables created by an earlier version of the package carry further columns
(definitions: ``description``, ``suit_items``, ``prompt_overrides``,
``pause_routine``, ``imagegen``; active: ``granted_items``, ``lock_before``).
They have defaults and are neither read nor written.

Reads go through an in-memory ``{bearer: ActiveRow}`` cache (the verbs ask
on every turn). Every write invalidates it
AFTER its commit; a rebuild captures the generation before it reads the table
and publishes only when no write happened meanwhile, so a stale snapshot never
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
from app.core.timeutils import utc_now_iso


@dataclass(frozen=True)
class ActiveRow:
    """One character's current transformation."""
    bearer: str
    persona_id: str
    started_game: str                      # GameTime canonical stamp
    until_game: str = ""                   # GameTime canonical stamp; "" = until reverted
    #: What a revert needs even when the persona was edited or removed
    #: meanwhile (column ``outfit_snapshot``): ``condition_id`` and ``alias``
    #: as applied, ``pose_key`` the transform activity resolved to.
    snapshot: Dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_generation = 0
_cache: Optional[Dict[str, ActiveRow]] = None


def ensure_schema() -> None:
    from plugins.transformation.definitions import (DEFAULT_COOLDOWN_MINUTES,
                                                    DEFAULT_MAX_DURATION_MINUTES,
                                                    DEFAULT_TRANSFORM_ACTIVITY)
    activity = DEFAULT_TRANSFORM_ACTIVITY.replace("'", "''")
    with transaction() as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS transformation_definitions (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL UNIQUE,
            alias TEXT NOT NULL DEFAULT '',
            activation_phrase TEXT NOT NULL DEFAULT '',
            revert_phrase TEXT NOT NULL DEFAULT '',
            condition_id TEXT NOT NULL DEFAULT '',
            max_duration_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_MAX_DURATION_MINUTES)},
            cooldown_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_COOLDOWN_MINUTES)},
            transform_activity TEXT NOT NULL DEFAULT '{activity}',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT '')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transformation_active (
            character_name TEXT PRIMARY KEY,
            persona_id TEXT NOT NULL,
            started_game TEXT NOT NULL,
            until_game TEXT NOT NULL DEFAULT '',
            outfit_snapshot TEXT NOT NULL DEFAULT '{}')""")
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
        snapshot=_json(r[4], {}))


def _active_map() -> Dict[str, ActiveRow]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        generation = _generation
    rows = get_connection().execute(
        "SELECT character_name, persona_id, started_game, until_game, outfit_snapshot "
        "FROM transformation_active").fetchall()
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
                "started_game, until_game, outfit_snapshot) VALUES (?, ?, ?, ?, ?)",
                (row.bearer, row.persona_id, row.started_game, row.until_game,
                 json.dumps(row.snapshot, ensure_ascii=False)))
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


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

#: The written columns of a definition row (all but ``id`` and ``updated_at``).
DEFINITION_FIELDS = (
    "item_id", "alias", "activation_phrase", "revert_phrase", "condition_id",
    "max_duration_minutes", "cooldown_minutes", "transform_activity", "enabled",
)
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


def _column_value(name: str, value: Any) -> Any:
    if name == "enabled":
        return 1 if value else 0
    if name in _INT_FIELDS:
        return max(0, int(value))
    return "" if value is None else str(value).strip()


def _definition_row(r) -> Dict[str, Any]:
    c = dict(zip(("id",) + DEFINITION_FIELDS + ("updated_at",), r))
    return {
        "id": c["id"], "item_id": c["item_id"] or "", "alias": c["alias"] or "",
        "activation_phrase": c["activation_phrase"] or "", "revert_phrase": c["revert_phrase"] or "",
        "condition_id": c["condition_id"] or "",
        "max_duration_minutes": int(c["max_duration_minutes"] or 0),
        "cooldown_minutes": int(c["cooldown_minutes"] or 0),
        "transform_activity": c["transform_activity"] or "", "enabled": bool(c["enabled"]),
        "updated_at": c["updated_at"] or "",
    }


_SELECT_DEFINITIONS = ("SELECT id, " + ", ".join(DEFINITION_FIELDS)
                       + ", updated_at FROM transformation_definitions")


def list_definitions() -> List[Dict[str, Any]]:
    """Every stored definition as a dict, in creation order (rowid)."""
    rows = get_connection().execute(_SELECT_DEFINITIONS + " ORDER BY rowid").fetchall()
    return [_definition_row(r) for r in rows]


def get_definition(persona_id: str) -> Optional[Dict[str, Any]]:
    """One stored definition, or ``None``."""
    if not persona_id:
        return None
    r = get_connection().execute(_SELECT_DEFINITIONS + " WHERE id=?", (persona_id,)).fetchone()
    return _definition_row(r) if r else None


def _slug(alias: str) -> str:
    text = unicodedata.normalize("NFKD", alias or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "persona"


def create_definition(record: Dict[str, Any], *, persona_id: str = "") -> str:
    """Insert a definition and return its id.

    ``persona_id`` empty = a slug of the alias, made unique with ``_2``,
    ``_3``, ...; stable afterwards. Missing columns take the table defaults
    (the constants in ``definitions``). Raises ``sqlite3.IntegrityError`` for
    an id or an item that is already taken. No usability checks here."""
    cols = [c for c in DEFINITION_FIELDS if c in record]
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pid = (persona_id or "").strip()
            if not pid:
                base = _slug(str(record.get("alias") or ""))
                taken = {r[0] for r in conn.execute(
                    "SELECT id FROM transformation_definitions").fetchall()}
                pid, n = base, 1
                while pid in taken:
                    n += 1
                    pid = f"{base}_{n}"
            conn.execute(
                "INSERT INTO transformation_definitions (id, " + "".join(c + ", " for c in cols)
                + "updated_at) VALUES (" + "?, " * (len(cols) + 1) + "?)",
                (pid, *[_column_value(c, record[c]) for c in cols], utc_now_iso()))
    finally:
        _bump_definitions()
    return pid


def update_definition(persona_id: str, changes: Dict[str, Any]) -> bool:
    """Write the given columns of one definition. False when it does not exist.
    Raises ``sqlite3.IntegrityError`` for an item already bound elsewhere."""
    cols = [c for c in DEFINITION_FIELDS if c in changes]
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE transformation_definitions SET " + "".join(c + "=?, " for c in cols)
                + "updated_at=? WHERE id=?",
                (*[_column_value(c, changes[c]) for c in cols], utc_now_iso(), persona_id))
            return cur.rowcount > 0
    finally:
        _bump_definitions()


def delete_definition(persona_id: str) -> bool:
    """Delete one definition and every bearer's cooldown for it. False when
    it did not exist. The knower secrets are the caller's (they are owned by
    the characters, through ``app.models.secrets``)."""
    try:
        with transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM transformation_definitions WHERE id=?", (persona_id,))
            conn.execute("DELETE FROM transformation_cooldown WHERE persona_id=?", (persona_id,))
            return cur.rowcount > 0
    finally:
        _bump_definitions()
        invalidate()
