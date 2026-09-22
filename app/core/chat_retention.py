"""Retention for the raw chat history (``chat_messages``).

Storage hygiene, not game logic: the table grows with every turn and nothing
pruned it before — ``delete_character``, the NPC-pool cleanup and the admin
rewind are the only deletes, and none of them is about age. So the horizon is
measured on the SYSTEM clock (``utc_now``, the ``ts`` column), exactly like
``scene_manager.WILDERNESS_RETENTION_DAYS``; a ``datetime`` here is not a game
stamp, it is a disk-space rule.

THE GUARD. Age alone is not enough. A message may only go once the world has
kept what it said — that is, once the GAME day it belongs to has been rolled
up into a summary. The rollup ladder is daily -> weekly -> seasonal, and each
step DELETES the tier below it (``memory_service._consolidate_daily_to_weekly``
calls ``delete_daily_summaries``), so "this day was rolled up" is true when

    * ``summaries`` holds a ``kind='daily'`` row for (character, day_key), OR
    * a ``kind='weekly'`` row for the week that day falls into, OR
    * a ``kind='monthly'`` row for the season that day falls into.

Checking only the daily tier would mean that every day old enough to be worth
pruning has already lost its daily row to the weekly fold — the pruner would
never delete anything.

THE DAY OF A ROW. ``chat_messages`` carries SYSTEM stamps only; there is no
game stamp column. The rollup turns a day key into a system window with
``timeutils.system_window_of_game_day`` and reads the rows inside it
(``history_manager._get_day_messages``). This module walks the other way, with
that function's own inverse — ``day_consolidation.game_day_of`` /
``timeutils.game_time_at``, the same projection ``memory_service.memory_day_key``
falls back to for stamp-less rows. Same anchor, same factor, so a row is
assigned to exactly the day whose window the rollup would have found it in.

BOTH DIRECTIONS OF A PAIR. A TalkTo turn is written into BOTH characters'
buckets (see ``UnifiedChatManager.get_chat_history``, which merges and dedups
them). Each copy is a row of its own ``character_name``, and each character
rolls up its own days, so judging every row by its own bucket's summaries is
right: A's copy goes when A's day was summarized, B's copy when B's was.
"""
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("chat_retention")

# How many rows one SELECT/DELETE round handles. The table is the largest in
# the world DB, so the pass is paged instead of running one DELETE with a
# subquery that would scan every row twice and hold a write lock throughout.
_BATCH_SIZE = 500


def _configured_days() -> int:
    """Configured horizon in SYSTEM days, 0 = keep forever."""
    try:
        from app.core import config
        val = config.get("memory.chat_retention_days")
        if val in (None, ""):
            return 90
        return max(0, int(val))
    except (TypeError, ValueError):
        return 90
    except Exception:  # noqa: BLE001 — a broken config must not break the tick
        return 90


def _summarized_keys(character_name: str) -> Tuple[Set[str], Set[str], Set[str]]:
    """The (daily, weekly, seasonal) ``date_key`` sets this character has."""
    daily: Set[str] = set()
    weekly: Set[str] = set()
    seasonal: Set[str] = set()
    try:
        rows = get_connection().execute(
            "SELECT kind, date_key FROM summaries "
            "WHERE character_name=? AND kind IN ('daily','weekly','monthly')",
            (character_name,)).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.debug("chat_retention: summary read failed for %s: %s",
                     character_name, e)
        return daily, weekly, seasonal
    for kind, date_key in rows:
        if not date_key:
            continue
        if kind == "daily":
            daily.add(date_key)
        elif kind == "weekly":
            weekly.add(date_key)
        else:
            seasonal.add(date_key)
    return daily, weekly, seasonal


def _day_is_rolled_up(day_key: str,
                      daily: Set[str],
                      weekly: Set[str],
                      seasonal: Set[str]) -> bool:
    """True when a summary of ANY tier covers that game day."""
    if not day_key:
        return False
    if day_key in daily:
        return True
    if not weekly and not seasonal:
        return False
    from app.core.day_consolidation import parse_day_key
    from app.core.memory_service import _season_key, _week_key
    day = parse_day_key(day_key)
    if day is None:
        return False
    if weekly and _week_key(day) in weekly:
        return True
    return bool(seasonal and _season_key(day) in seasonal)


def _characters_with_old_rows(cutoff: str) -> List[str]:
    """Characters that have at least one message older than the cutoff."""
    try:
        rows = get_connection().execute(
            "SELECT DISTINCT character_name FROM chat_messages WHERE ts < ?",
            (cutoff,)).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.debug("chat_retention: candidate scan failed: %s", e)
        return []
    return [r[0] for r in rows if r[0]]


def _prune_character(character_name: str, cutoff: str) -> Tuple[int, int, int]:
    """One character's pass. Returns (examined, deleted, kept_unsummarized)."""
    daily, weekly, seasonal = _summarized_keys(character_name)
    from app.core.day_consolidation import game_day_of

    examined = deleted = kept = 0
    verdicts: Dict[str, bool] = {}   # day_key -> may be deleted
    # Keyset cursor over (ts, id): deleted rows fall behind it, so paging
    # stays correct while rows disappear under us.
    last_ts, last_id = "", 0
    conn = get_connection()
    while True:
        try:
            rows = conn.execute("""
                SELECT id, ts FROM chat_messages
                WHERE character_name=? AND ts < ?
                  AND (ts > ? OR (ts = ? AND id > ?))
                ORDER BY ts ASC, id ASC
                LIMIT ?
            """, (character_name, cutoff, last_ts, last_ts, last_id,
                  _BATCH_SIZE)).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.debug("chat_retention: read failed for %s: %s",
                         character_name, e)
            break
        if not rows:
            break

        doomed: List[int] = []
        for row_id, ts in rows:
            examined += 1
            last_ts, last_id = ts or "", row_id
            day_key = game_day_of(ts)
            verdict = verdicts.get(day_key)
            if verdict is None:
                verdict = _day_is_rolled_up(day_key, daily, weekly, seasonal)
                verdicts[day_key] = verdict
            if verdict:
                doomed.append(row_id)
            else:
                kept += 1

        if doomed:
            placeholders = ",".join("?" for _ in doomed)
            try:
                with transaction() as wconn:
                    wconn.execute(
                        f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                        doomed)
                deleted += len(doomed)
            except Exception as e:  # noqa: BLE001
                logger.error("chat_retention: delete failed for %s: %s",
                             character_name, e)
                break

        if len(rows) < _BATCH_SIZE:
            break
    return examined, deleted, kept


def prune_chat_messages(retention_days: Optional[int] = None) -> Dict[str, int]:
    """Delete summarized chat rows older than the configured horizon.

    Returns ``{"examined", "deleted", "kept_unsummarized"}``. ``examined``
    counts the rows older than the cutoff that were looked at; the rest of the
    table is never read. A horizon of 0 disables the whole pass.
    """
    stats = {"examined": 0, "deleted": 0, "kept_unsummarized": 0}
    days = (_configured_days() if retention_days is None
            else max(0, int(retention_days)))
    if days <= 0:
        return stats

    cutoff = (utc_now() - timedelta(days=days)).isoformat(timespec="seconds")
    for name in _characters_with_old_rows(cutoff):
        examined, deleted, kept = _prune_character(name, cutoff)
        stats["examined"] += examined
        stats["deleted"] += deleted
        stats["kept_unsummarized"] += kept

    if stats["deleted"]:
        logger.info("chat_retention: %d message(s) older than %d days deleted, "
                    "%d kept (their game day has no summary yet), %d examined",
                    stats["deleted"], days, stats["kept_unsummarized"],
                    stats["examined"])
    return stats
