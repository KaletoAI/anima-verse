"""Per-world overrides of the shipped LLM prompt templates (world.db).

The shipped templates (shared/templates/llm/, plugin template roots) are
code and change only by commit. A world can replace one template as a whole
— the prompt_templates loader asks this module first, for top-level renders
and for every {% include %}. Keyed by the Jinja template name.

The table is small (a handful of rows) and read on every render, so it is
held in memory per world DB and dropped on every write of this process; the
server is the only writer of its world.db.
"""
import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.core import paths
from app.core.log import get_logger

logger = get_logger("template_overrides")


@dataclass(frozen=True)
class Override:
    name: str
    content: str
    base_hash: str
    updated_at: str


_lock = threading.Lock()
_cache: Tuple[Optional[str], Optional[Dict[str, Override]]] = (None, None)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _db_key() -> Optional[str]:
    try:
        from app.core.db import get_db_path
        return str(get_db_path())
    except paths.StorageNotInitialised:
        return None


def all_overrides() -> Dict[str, Override]:
    global _cache
    key = _db_key()
    if key is None:
        return {}
    with _lock:
        cached_key, table = _cache
        if table is not None and cached_key == key:
            return table
        from app.core.db import get_connection
        try:
            rows = get_connection().execute(
                "SELECT path, content, base_hash, updated_at FROM llm_template_overrides"
            ).fetchall()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            rows = []
        table = {r[0]: Override(r[0], r[1], r[2], r[3]) for r in rows}
        _cache = (key, table)
        return table


def lookup(name: str) -> Optional[Override]:
    return all_overrides().get(name)


def fingerprint() -> str:
    """Stable across restarts: changes exactly when any override of this
    world is added, changed or removed. "" without overrides."""
    table = all_overrides()
    if not table:
        return ""
    joined = "\n".join(f"{n}\x1f{content_hash(o.content)}" for n, o in sorted(table.items()))
    return content_hash(joined)


_generation = 0


def revision() -> tuple:
    """Changes on every override write of this process (and with the world
    DB) — the prompt_templates loader stamps every source with it."""
    return (_db_key(), _generation)


def _invalidate() -> None:
    global _cache, _generation
    with _lock:
        _cache = (None, None)     # first drop the table ...
        _generation += 1          # ... then mark every earlier read stale
    from app.core import prompt_templates
    prompt_templates.clear_caches()


def set_override(name: str, content: str, base_hash: str) -> Override:
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    ov = Override(name, content, base_hash, utc_now_iso())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO llm_template_overrides (path, content, base_hash, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
            "content=excluded.content, base_hash=excluded.base_hash, "
            "updated_at=excluded.updated_at",
            (ov.name, ov.content, ov.base_hash, ov.updated_at))
    _invalidate()
    logger.info("Template override saved: %s", name)
    return ov


def delete_override(name: str) -> bool:
    from app.core.db import transaction
    with transaction() as conn:
        cur = conn.execute("DELETE FROM llm_template_overrides WHERE path = ?", (name,))
        removed = cur.rowcount > 0
    _invalidate()
    if removed:
        logger.info("Template override deleted: %s", name)
    return removed
