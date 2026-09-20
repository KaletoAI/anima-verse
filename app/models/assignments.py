"""Assignment-System — legacy remnant of the pre-intents task feature.

Only two pieces are still live: ``_load_all`` (read by the one-time
``intents.migrate_assignments_to_intents``) and ``strip_assignment_tags``
(text cleanup in the chat path). Everything else moved to
``app/models/intents.py``.

Storage: the ``assignments`` table in ``world.db``.
"""
import json

from pathlib import Path
from typing import Any, Dict, List

from app.core.log import get_logger
from app.core.db import get_connection

logger = get_logger("assignments")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _get_assignments_path() -> Path:
    """Returns path to the user's assignments.json file."""
    from app.core.paths import get_storage_dir
    return get_storage_dir() / "assignments.json"


def _load_all() -> List[Dict[str, Any]]:
    """Load all assignments from the DB.

    The full assignment dict is stored in the ``meta`` JSON column. We use
    that as the source of truth and only fall back to a minimal stub when
    meta is genuinely empty. Some legacy rows have a populated meta dict
    that's missing the redundant ``id`` key — for those we fill the id
    from the DB column instead of throwing the rest of the data away.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, character_name, task, status, due, meta, created_at, updated_at "
            "FROM assignments ORDER BY created_at ASC"
        ).fetchall()
        assignments = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r[5] or "{}")
            except Exception:
                pass
            if isinstance(meta, dict) and meta:
                # Patch missing id from the dedicated column, then trust meta
                # for everything else (description, participants, ...).
                meta.setdefault("id", r[0])
                meta.setdefault("title", r[2] or meta.get("title", ""))
                meta.setdefault("status", r[3] or meta.get("status", "active"))
                meta.setdefault("created_at", r[6] or meta.get("created_at", ""))
                assignments.append(meta)
            else:
                # Genuinely empty meta — fall back to a minimal stub so the
                # row is at least visible.
                assignments.append({
                    "id": r[0],
                    "title": r[2] or "",
                    "description": "",
                    "status": r[3] or "active",
                    "expires_at": r[4] or None,
                    "created_at": r[6] or "",
                    "participants": {},
                    "priority": 3,
                    "target_count": 0,
                    "source": "db",
                })
        return assignments
    except Exception as e:
        logger.warning("_load_all assignments DB-Fehler: %s", e)
        # Fallback: JSON-Datei
        path = _get_assignments_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to load assignments: %s", exc)
            return []


def strip_assignment_tags(text: str) -> str:
    """Remove all assignment marker tags from display text."""
    import re
    text = re.sub(r'\n?\[ASSIGNMENT_(?:UPDATE|DONE):\s*[^\]]+\]', '', text)
    text = re.sub(r'\n?\[NEW_ASSIGNMENT:\s*[^\]]+\]', '', text)
    return text.strip()
