"""DB access for the thought journal (plan-thought-journal.md).

A thought turn's narrative — 700–1400 characters of inner monologue, plans and
judgements — used to be handed to the Tool-LLM once and then discarded. It is
stored here instead, so that inner life has continuity between turns, feeds the
daily consolidation and can be inspected.

**Privacy is the point of this module.** Thoughts have exactly three consumers:
the character's OWN next thought prompt, that character's own consolidation and
the admin UI. They never enter the perception stream, another character's
prompt, a chat history or a notification. Storing is storage, not delivery —
the verbs-only contract stays untouched.

Timestamps are SYSTEM time (``utc_now_iso``), like every other persistence
stamp; the retention cutoff is computed in system time too, not game time.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger("thought_store")


def add_thought(character_name: str, content: str, location_id: str = "",
                room_id: str = "", ts: Optional[str] = None) -> bool:
    """Journals one thought. Empty content is not stored (nothing to remember).

    Never raises: a failing journal write must not take down the thought turn
    it belongs to — the turn's world effects already happened through verbs.
    """
    text = (content or "").strip()
    if not character_name or not text:
        return False
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO thoughts (character_name, ts, location_id, room_id,"
                " content) VALUES (?, ?, ?, ?, ?)",
                (character_name, ts or utc_now_iso(), location_id or "",
                 room_id or "", text))
        return True
    except Exception as e:
        logger.warning("add_thought(%s) fehlgeschlagen: %s", character_name, e)
        return False


def list_thoughts(character_name: str, limit: int = 50,
                  before: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest first. ``before`` is a ts cursor for paging — pass the ts of the
    oldest row you already have and you get the next page."""
    if not character_name:
        return []
    limit = max(1, min(int(limit or 50), 200))
    sql = ("SELECT id, ts, location_id, room_id, content FROM thoughts"
           " WHERE character_name=?")
    params: List[Any] = [character_name]
    if before:
        sql += " AND ts < ?"
        params.append(before)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit)
    try:
        return [dict(r) for r in get_connection().execute(sql, params).fetchall()]
    except Exception as e:
        logger.warning("list_thoughts(%s) fehlgeschlagen: %s", character_name, e)
        return []


def thoughts_of_range(character_name: str, start_ts: str,
                      end_ts: str) -> List[Dict[str, Any]]:
    """Thoughts of a time window, OLDEST first — the order the consolidation
    wants (a day read from morning to evening). ``start_ts`` inclusive,
    ``end_ts`` exclusive."""
    if not character_name or not start_ts or not end_ts:
        return []
    try:
        rows = get_connection().execute(
            "SELECT id, ts, location_id, room_id, content FROM thoughts"
            " WHERE character_name=? AND ts >= ? AND ts < ?"
            " ORDER BY ts ASC, id ASC",
            (character_name, start_ts, end_ts)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("thoughts_of_range(%s) fehlgeschlagen: %s",
                       character_name, e)
        return []


def prune_before(character_name: str, cutoff_ts: str) -> int:
    """Deletes this character's thoughts older than ``cutoff_ts``; returns the
    number deleted. Raw thoughts are transient — what matters survives in the
    consolidated day (same pattern as chat-history summarization)."""
    if not character_name or not cutoff_ts:
        return 0
    try:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM thoughts WHERE character_name=? AND ts < ?",
                (character_name, cutoff_ts))
            return int(cur.rowcount or 0)
    except Exception as e:
        logger.warning("prune_before(%s) fehlgeschlagen: %s", character_name, e)
        return 0
