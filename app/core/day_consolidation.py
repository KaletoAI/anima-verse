"""Day consolidation (plan-history-consolidation-cleanup.md, phase 2).

On the main sleep — or as a backlog fallback — a character's scenes of one
wake block are condensed into ONE day entry (table ``summaries``, kind='daily',
partner=''). From then on a day reads as one entry instead of several scenes.

The trigger criterion is the SLEEP LENGTH (not the clock time — that would tip
over on a night shift). Scenes are shared (several participants), so we do NOT
delete them; instead every character carries a cursor (world_kv): scenes up to
the cursor are folded into day entries, newer ones are still shown one by one.

**The day is the GAME day** (plan-game-calendar.md, decision E4): keys are
``Y0002-D109`` (``GameTime.day_key``), never a real calendar date. Rows the
world writes with SYSTEM stamps (scenes, chat messages, memories) are sorted
into game days by :func:`game_time_at` — see its docstring for what that
projection can and cannot promise.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.game_time import DAY_SECONDS, GameTime
from app.core.log import get_logger
from app.core.timeutils import (_start_of_day_key, game_time, game_time_at,
                                parse_iso, utc_now, utc_now_iso)

logger = get_logger("day_consolidation")

# Config defaults (admin-overridable via memory.*)
_DEFAULT_MAIN_SLEEP_MIN_HOURS = 4
_DEFAULT_MAX_BLOCK_OPEN_HOURS = 30

# Thought journal (plan-thought-journal.md): character budget of the inner-life
# block handed to a daily consolidation, and how long RAW thoughts survive.
# Raw is transient, the consolidated day is permanent — the same deal chat
# history has. Both in SYSTEM time; module constants, no config sprawl.
THOUGHTS_OF_DAY_CHARS = 2000
THOUGHT_RETENTION_DAYS = 7


# --- system stamp → game day ------------------------------------------------
#
# The projection itself (``game_time_at``, ``system_window_of_game_day``) is
# clock mathematics and lives in ``app.core.timeutils`` next to the clock. What
# stays here are the day-KEY helpers the consolidation speaks in.


def game_day_of(when: Any) -> str:
    """``day_key`` of the game day a SYSTEM stamp falls into ("" if unusable)."""
    gt = game_time_at(when)
    return gt.day_key() if gt is not None else ""


def parse_day_key(day_key: str) -> Optional[GameTime]:
    """Start of the game day named by a ``day_key``, or ``None``.

    The counterpart of :meth:`GameTime.day_key` — ``Y0002-D109`` becomes the
    :class:`GameTime` of that day at 00:00:00.
    """
    return _start_of_day_key(day_key)


def recent_game_day_keys(days: int, skip_today: bool = False) -> List[str]:
    """The last ``days`` game days as ``day_key``s, oldest first.

    ``skip_today`` leaves out the day currently running (used where today is
    handled separately). Days before the world epoch are not produced.
    """
    if days <= 0:
        return []
    today_index = game_time().day_index
    keys: List[str] = []
    for i in range(days, 0, -1):
        index = today_index - i
        if index < 0:
            continue  # before the world epoch — the world is not that old yet
        keys.append(GameTime(index * DAY_SECONDS).day_key())
    if not skip_today:
        keys.append(GameTime(today_index * DAY_SECONDS).day_key())
    return keys


def thoughts_of_day_block(character_name: str, start_ts: str,
                          end_ts: str) -> str:
    """The character's thoughts of a window as a compact line list, oldest
    first, hard-capped at ``THOUGHTS_OF_DAY_CHARS``.

    Formatting only — WHAT a consolidation does with the inner life is decided
    by the templates, not here. Empty window → empty string, and the templates
    then render no block at all.
    """
    try:
        from app.models.thought_store import thoughts_of_range
        rows = thoughts_of_range(character_name, start_ts, end_ts)
    except Exception as e:
        logger.debug("thoughts_of_day_block(%s): %s", character_name, e)
        return ""
    return _thought_lines(rows)


def _thought_lines(rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    used = 0
    for row in rows:
        text = " ".join((row.get("content") or "").split())
        if not text:
            continue
        overhead = 2 + (1 if lines else 0)
        room = THOUGHTS_OF_DAY_CHARS - used - overhead
        if room <= 0:
            break
        if len(text) > room:
            text = text[:room - 1].rstrip() + "…"
            if len(text) <= 1:
                break
        lines.append(f"- {text}")
        used += overhead + len(text)
    return "\n".join(lines)


def thoughts_of_date(character_name: str, day_key: str) -> str:
    """``thoughts_of_day_block`` for one GAME day (``Y0002-D109``) — the shape
    the memory consolidations work in.

    Thoughts carry their own game stamp (``thoughts.game_ts``), so this is an
    exact window, not a projection. A key that is not a game day yields "" and
    says so in the log — a real date reaching here is a defect, not a case to
    fall back for.
    """
    if not character_name or not day_key:
        return ""
    start = parse_day_key(day_key)
    if start is None:
        logger.warning("thoughts_of_date(%s): %r is not a game day key",
                       character_name, day_key)
        return ""
    try:
        from app.models.thought_store import thoughts_of_game_range
        rows = thoughts_of_game_range(character_name, start.canonical(),
                                      start.next_day_start().canonical())
    except Exception as e:
        logger.debug("thoughts_of_date(%s, %s): %s", character_name, day_key, e)
        return ""
    return _thought_lines(rows)


def _cfg(key: str, default):
    try:
        from app.core import config
        val = config.get(key)
        return val if val not in (None, "") else default
    except Exception:
        return default


# --- world_kv (key/value) ---------------------------------------------------

def _kv_get(key: str) -> str:
    try:
        row = get_connection().execute(
            "SELECT value FROM world_kv WHERE key=?", (key,)).fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        return ""


def _kv_set(key: str, value: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO world_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    except Exception as e:
        logger.debug("kv_set %s failed: %s", key, e)


def get_cursor(character_name: str) -> str:
    return _kv_get(f"day_cursor:{character_name}")


def set_cursor(character_name: str, ts: str) -> None:
    _kv_set(f"day_cursor:{character_name}", ts or "")


# --- Consolidation ----------------------------------------------------------

def consolidate_block_for(character_name: str, reason: str = "") -> int:
    """Condenses the character's not-yet-folded scenes into one day entry.
    Returns the number of scenes folded (0 = nothing)."""
    if not character_name:
        return 0
    from app.models import scene_store
    cursor = get_cursor(character_name)
    scenes = [s for s in scene_store.get_recent_scenes_for(character_name, limit=50)
              if (s.get("last_activity_ts") or "") > cursor
              and (s.get("summary") or "").strip()]
    now = utc_now_iso()
    if not scenes:
        set_cursor(character_name, now)  # empty block closed
        return 0
    scenes.sort(key=lambda s: s.get("last_activity_ts") or "")
    new_cursor = scenes[-1].get("last_activity_ts") or now
    # The day of the block is the GAME day its last scene happened in (E4).
    # Scenes carry SYSTEM stamps, so the game day is projected — see
    # game_time_at(); the cursor and all storage stay SYSTEM time.
    date_key = game_day_of(new_cursor) or game_time().day_key()
    # Inner life of the same wake block — the window this consolidation
    # already knows (cursor → new cursor). Private to this character.
    thoughts_block = thoughts_of_day_block(character_name, cursor or "", new_cursor) \
        if cursor else thoughts_of_day_block(character_name, scenes[0].get(
            "started_ts") or scenes[0].get("last_activity_ts") or "", new_cursor)
    summary = _summarize_day(character_name, scenes, thoughts_block)
    if summary:
        _save_daily(character_name, date_key, summary)
        # Store the day entry as a (coarser) memory as well → the
        # memory_service rollup (daily→weekly→monthly) picks it up, sourced
        # from scenes instead of chat_messages.
        try:
            from app.models.memory import add_memory
            add_memory(character_name, summary, memory_type="daily", importance=2,
                       tags=["day"], context="day",
                       extra_meta={"date_key": date_key})
        except Exception as e:
            logger.debug("daily memory add failed for %s: %s", character_name, e)
    set_cursor(character_name, new_cursor)
    _prune_thoughts(character_name)
    logger.info("Day consolidated: %s (%d scenes, day=%s, reason=%s)",
                character_name, len(scenes), date_key, reason or "?")
    return len(scenes)


def _prune_thoughts(character_name: str) -> int:
    """Retention after a successful consolidation: raw thoughts older than
    ``THOUGHT_RETENTION_DAYS`` go. What mattered lives on in the day entry —
    same deal as chat-history summarization. System time, like the stamps."""
    try:
        from app.models.thought_store import prune_before
        cutoff = (utc_now() - timedelta(days=THOUGHT_RETENTION_DAYS)).isoformat()
        gone = prune_before(character_name, cutoff)
        if gone:
            logger.info("Thought retention %s: %d raw thoughts older than %d days removed",
                        character_name, gone, THOUGHT_RETENTION_DAYS)
        return gone
    except Exception as e:
        logger.debug("thought retention for %s failed: %s", character_name, e)
        return 0


def _summarize_day(character_name: str, scenes: List[Dict[str, Any]],
                   thoughts_block: str = "") -> str:
    """LLM condensation of several scene summaries of one day into ONE entry.

    ``thoughts_block`` is the inner life of the wake block (private, this
    character only) — it colours the recap but does not replace the scenes.
    """
    try:
        from app.core.llm_router import llm_call
        from app.models.character import get_character_language, LANGUAGE_MAP
        code = (get_character_language(character_name) or "en").strip()
        lang = LANGUAGE_MAP.get(code, "English")
        bullets = "\n".join(f"- {(s.get('summary') or '').strip()}"
                            for s in scenes if (s.get("summary") or "").strip())
        sys_prompt = (
            f"You compress a character's day into ONE short recap from the scene "
            f"summaries below. Write 2-4 sentences in {lang}, past tense, from "
            f"{character_name}'s perspective. Keep only what matters for later; drop "
            f"filler. No lists, no preamble — just the recap.")
        user_prompt = f"Scenes of the day for {character_name}:\n{bullets}"
        if thoughts_block:
            user_prompt += (f"\n\nWhat {character_name} thought during that time "
                            f"(private inner life — nobody else knows it):\n"
                            f"{thoughts_block}")
        resp = llm_call(task="consolidation", system_prompt=sys_prompt,
                        user_prompt=user_prompt, agent_name=character_name)
        return (resp.content or "").strip() if resp else ""
    except Exception as e:
        logger.warning("day summary LLM failed for %s: %s", character_name, e)
        return ""


def _save_daily(character_name: str, date_key: str, content: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
                "VALUES (?, 'daily', ?, '', ?) "
                "ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET "
                "content=excluded.content", (character_name, date_key, content))
    except Exception as e:
        logger.error("save daily entry failed for %s/%s: %s", character_name, date_key, e)


def recent_daily_entries(character_name: str, limit: int = 7) -> List[Tuple[str, str]]:
    """(day_key, content) of the most recent day entries, newest first.

    ``day_key`` sorts lexicographically in chronological order, so the plain
    ``ORDER BY`` keeps working on the game calendar.
    """
    try:
        rows = get_connection().execute(
            "SELECT date_key, content FROM summaries WHERE character_name=? "
            "AND kind='daily' AND partner='' AND content!='' "
            "ORDER BY date_key DESC LIMIT ?", (character_name, max(1, limit))).fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


# --- Trigger (called by the periodic job) -----------------------------------

def maybe_consolidate(character_name: str) -> int:
    """Checks the triggers and consolidates if due:
      1) main sleep: on waking, `woke_main_sleep:<c>` was set.
      2) backlog fallback: open block (cursor) older than max_block_open_hours.
    """
    flag_key = f"woke_main_sleep:{character_name}"
    if _kv_get(flag_key):
        _kv_set(flag_key, "")
        return consolidate_block_for(character_name, "main_sleep")

    # Fallback: is the oldest not-yet-folded block too old?
    cursor = get_cursor(character_name)
    max_hours = int(_cfg("memory.max_block_open_hours", _DEFAULT_MAX_BLOCK_OPEN_HOURS))
    try:
        from app.models import scene_store
        scenes = [s for s in scene_store.get_recent_scenes_for(character_name, limit=50)
                  if (s.get("last_activity_ts") or "") > cursor
                  and (s.get("summary") or "").strip()]
        if not scenes:
            return 0
        oldest = min(s.get("last_activity_ts") or "" for s in scenes)
        if oldest and (utc_now() - parse_iso(oldest)).total_seconds() >= max_hours * 3600:
            return consolidate_block_for(character_name, f"fallback_{max_hours}h")
    except Exception as e:
        logger.debug("maybe_consolidate fallback check failed for %s: %s", character_name, e)
    return 0


def note_sleep_start(character_name: str) -> None:
    """On falling asleep: remember the start time (for the sleep-length
    measurement). GAME time — sleeping is an in-world duration; with a game
    factor >1 a real-time measurement would never reach the main-sleep
    threshold (an in-game night lasts minutes of real time)."""
    _kv_set(f"sleep_start:{character_name}", game_time().canonical())


def note_wake(character_name: str) -> None:
    """On waking: was this the main sleep (≥ threshold)? Then set the flag for
    the periodic job that runs the day consolidation (the LLM call is there)."""
    start = _kv_get(f"sleep_start:{character_name}")
    _kv_set(f"sleep_start:{character_name}", "")
    if not start:
        return
    try:
        # GAME hours (see note_sleep_start).
        slept_h = (game_time() - GameTime.parse(start)).hours
    except ValueError:
        logger.warning("%s: sleep_start %r is not a game stamp — sleep length unknown",
                       character_name, start)
        return
    min_h = float(_cfg("memory.main_sleep_min_hours", _DEFAULT_MAIN_SLEEP_MIN_HOURS))
    if slept_h >= min_h:
        _kv_set(f"woke_main_sleep:{character_name}", utc_now_iso())
        logger.info("%s: main sleep detected (%.1fh ≥ %.1fh) → day consolidation queued",
                    character_name, slept_h, min_h)
