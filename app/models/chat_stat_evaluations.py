"""Durable, atomic chat-stat evaluation receipts, independent of history TTL."""
import json

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso
from app.models.character import insert_state_history_row, trim_state_history_rows

logger = get_logger("chat_stat_evaluations")


def has_evaluation(event_id: str, recipient: str) -> bool:
    """Return whether this exact event/recipient pair was committed."""
    return get_connection().execute(
        "SELECT 1 FROM chat_stat_evaluations WHERE event_id=? AND recipient=?",
        (event_id, recipient),
    ).fetchone() is not None


def commit_evaluation(event_id: str, recipient: str, deltas: dict[str, int], *,
                      game_ts: str, metadata: dict) -> dict:
    """Commit one pair's status, receipt and effects history atomically.

    The caller holds its chat budget reservation, then the recipient's
    ``character_profile`` lock. This leaf starts its OWN transaction and
    never calls a profile saver or another committing history writer.
    ``unchanged`` still receipts a valid evaluation, including empty input;
    unknown recipients and failed writes receipt nothing. Only existing
    stored status keys are eligible. No unrelated state/profile data is
    rewritten, and no sync/trim happens before the successful commit.
    """
    changes = {}
    try:
        conn = get_connection()
        if conn.in_transaction:
            # db.transaction() commits/rolls back its whole connection: do
            # not accidentally commit or roll back an enclosing caller.
            logger.error("Chat evaluation cannot nest a transaction (%s, %s)",
                         event_id, recipient)
            return {"status": "failed", "changes": {}}
        with transaction() as conn:
            # Establish the write transaction BEFORE checking the receipt,
            # so its check and INSERT also agree across SQLite connections.
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                    "SELECT 1 FROM chat_stat_evaluations WHERE event_id=? AND recipient=?",
                    (event_id, recipient)).fetchone() is not None:
                return {"status": "duplicate", "changes": {}}
            row = conn.execute(
                "SELECT s.meta FROM characters c "
                "LEFT JOIN character_state s ON s.character_name=c.name WHERE c.name=?",
                (recipient,),
            ).fetchone()
            if row is None:
                return {"status": "failed", "changes": {}}
            state_meta = json.loads(row[0] or "{}")
            if not isinstance(state_meta, dict):
                raise ValueError("Character state metadata must be an object")
            status = state_meta.get("status_effects") or {}
            if not isinstance(status, dict):
                raise ValueError("Character status effects must be an object")
            for key, delta in deltas.items():
                if key not in status:
                    continue
                try:
                    old = int(status[key])
                    delta = int(delta)
                except (TypeError, ValueError, OverflowError):
                    continue
                new = max(0, min(100, old + delta))
                if delta and new != old:
                    status[key] = new
                    changes[key] = {"old": old, "new": new}
            if changes:
                state_meta["status_effects"] = status
                conn.execute(
                    "UPDATE character_state SET meta=? WHERE character_name=?",
                    (json.dumps(state_meta, ensure_ascii=False), recipient),
                )
            ts = utc_now_iso()
            conn.execute(
                "INSERT INTO chat_stat_evaluations (event_id, recipient, evaluated_at) VALUES (?, ?, ?)",
                (event_id, recipient, ts),
            )
            if changes:
                history_metadata = dict(metadata)
                source = history_metadata.get("source") or "chat"
                history_metadata["source"] = source
                history_metadata["changes"] = changes
                insert_state_history_row(
                    conn, recipient, "effects", source, ts=ts,
                    game_ts=game_ts, metadata=history_metadata)
    except Exception:
        logger.error("Chat evaluation commit failed for %s (%s)",
                     recipient, event_id, exc_info=True)
        return {"status": "failed", "changes": {}}

    if changes:
        # Housekeeping failure cannot undo the already committed evaluation
        # or incorrectly tell its caller to leave the budget unpublished.
        try:
            with transaction() as conn:
                trim_state_history_rows(conn, recipient)
        except Exception:
            logger.warning("Chat evaluation history trim failed for %s",
                           recipient, exc_info=True)
        from app.core import sync_topics
        sync_topics.changed_at(recipient, topics=("presence", "self"))
    return {"status": "applied" if changes else "unchanged", "changes": changes}
