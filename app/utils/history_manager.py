"""Chat history management — summaries, the time-based window and day summaries

Storage: world.db — Tabellen summaries, chat_messages
"""
import json
import os
import re
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("history_manager")


# ---------------------------------------------------------------------------
# Memory thresholds — central configuration of the three-tier system
# ---------------------------------------------------------------------------

def get_memory_thresholds() -> dict:
    """Three independently configurable limits of the memory system.

    Returns dict with:
        short_term_days: tier 1 (chat history in the prompt)
        mid_term_days:   tier 2 → 3 boundary (days → weeks)
        long_term_days:  weeks → season boundary
        max_messages:    safety cap for the chat history
        session_gap_hours: gap between turns that counts as a session break —
                           everything before the gap moves to old_history.
    """
    return {
        "short_term_days": int(os.environ.get("MEMORY_SHORT_TERM_DAYS", "3")),
        "mid_term_days": int(os.environ.get("MEMORY_MID_TERM_DAYS", "30")),
        "long_term_days": int(os.environ.get("MEMORY_LONG_TERM_DAYS", "90")),
        "max_messages": int(os.environ.get("CHAT_HISTORY_MAX_MESSAGES", "100")),
        "session_gap_hours": float(os.environ.get("CHAT_SESSION_GAP_HOURS", "4")),
    }


# ---------------------------------------------------------------------------
# Time-based history window
# ---------------------------------------------------------------------------

def get_time_based_history(
    full_history: List[Dict],
    days: int = 0,
    max_messages: int = 0) -> Tuple[List[Dict], List[Dict]]:
    """Return the chat history of the last N days.

    Filters by timestamp instead of a fixed count. Messages without a
    timestamp count as current.

    Additionally: the session gap. When two consecutive recent turns are more
    than ``session_gap_hours`` apart, every turn BEFORE the last such gap is
    moved to ``old``. The LLM thus sees only the current session verbatim —
    everything before goes into the session summary.

    Args:
        full_history: complete chat history (dicts with 'timestamp')
        days: time window in days (0 = from config)
        max_messages: safety cap (0 = from config)

    Returns:
        (recent_messages, old_messages)
        recent = in the prompt, old = for summary generation
    """
    if not days or not max_messages:
        thresholds = get_memory_thresholds()
        days = days or thresholds["short_term_days"]
        max_messages = max_messages or thresholds["max_messages"]
    else:
        thresholds = get_memory_thresholds()
    gap_hours = thresholds.get("session_gap_hours", 4.0)

    cutoff = utc_now() - timedelta(days=days)
    recent: List[Dict] = []
    old: List[Dict] = []

    for msg in full_history:
        ts_str = msg.get("timestamp", "")
        if ts_str:
            try:
                msg_time = parse_iso(ts_str)
                if msg_time < cutoff:
                    old.append(msg)
                    continue
            except (ValueError, TypeError):
                pass  # no valid timestamp → treat as current
        recent.append(msg)

    # Safety cap: when exceeded, cut the oldest recent messages
    if len(recent) > max_messages:
        overflow = recent[:-max_messages]
        old.extend(overflow)
        recent = recent[-max_messages:]

    # Session gap: cut at the last gap > gap_hours.
    if gap_hours > 0 and len(recent) >= 2:
        gap = timedelta(hours=gap_hours)
        for i in range(len(recent) - 1, 0, -1):
            try:
                prev_ts = parse_iso(recent[i - 1].get("timestamp") or "")
                cur_ts = parse_iso(recent[i].get("timestamp") or "")
            except (ValueError, TypeError):
                continue
            if cur_ts - prev_ts > gap:
                old.extend(recent[:i])
                recent = recent[i:]
                break

    return recent, old


_FUZZY_MARKER_RE = re.compile(
    r'\*\*I\s+(?:feel|do|am\s+at)\s+[^*]+\*\*', re.IGNORECASE)
_FUZZY_NONALNUM_RE = re.compile(r'[^a-z0-9äöüß]+')
# Sentence boundary: an end-of-sentence mark followed by whitespace, a line
# break, a dialogue quote or an asterisk (RP action markup). The quotes matter:
# in `„Deine Lippen sind kantig.“ Meine Finger gleiten …` the closing quote
# sits between the full stop and the space, so without them the spoken line
# and the narration that follows it were ONE part — and the same line followed
# by a different gesture never matched (measured 2026-10-23: a reply that
# reused 90% of the previous one counted as no repetition). The parts are only
# ever compared to each other, so a crude split is good enough.
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?…])\s+|\n+|[„“”"«»]|\*+')

# A verbatim sentence needs at least this many normalized characters before it
# counts as a repetition marker. 60 until 2026-10-23, from the echo measurement
# in task-A1.1-report.md section 2.5 — when the split still glued speech and
# narration together, so every part was long. With the quote split, RP lines
# are 30-50 characters; over the 121 logged chat calls that carried their
# message list, every sentence of >= 30 characters that recurred was a real
# verbatim repetition ("ich trete nah mein kern leuchtet sanft", "meine finger
# krallen sich in den teppich"). Truly short lines ("I nod slowly.", 12) stay
# below it.
REPETITION_SENTENCE_MIN_CHARS = 30

# Paraphrase loops: the same reply with its sentences re-ordered or one word
# changed shares no exact sentence, but most of its word 4-grams. A reply
# counts as a repetition when at least this share of its 4-grams already
# occurred in the window. Over the same 121 calls this flagged 11 calls the
# sentence keys missed, all of them genuine (a drunk NPC re-saying one line in
# a new order, a scene description copied into the next turn).
_WORD_RE = re.compile(r'[a-z0-9äöüß]+')
REPETITION_SHINGLE_WORDS = 4
REPETITION_SHINGLE_SHARE = 0.3

# Shipped defaults of the reactive repetition_penalty bump (config_schema
# ``chat.anti_rep_rp_step`` / ``chat.anti_rep_rp_max``).
RP_STEP_DEFAULT = 0.01
RP_MAX_DEFAULT = 1.05


def _normalize_fuzzy(text: str) -> str:
    """Lowercase and drop markers, whitespace and punctuation.

    Leaves only the letters/digits that carry the wording, so two renderings of
    the same sentence normalize to the same string.
    """
    return _FUZZY_NONALNUM_RE.sub("", _FUZZY_MARKER_RE.sub("", text).lower())


def fuzzy_signature(content: str, length: int = 60) -> str:
    """Fuzzy signature of a reply — the DEDUP KEY.

    Markers (`**I feel ...**`), whitespace and punctuation are filtered out;
    the first ``length`` alphanumeric characters are the signature. Replies
    that differ only in marker/whitespace/accents therefore match.

    This is deliberately narrow: a message whose signature is already known
    gets DELETED from the prompt (see ``chat_engine.dedupe_assistant_repeats``),
    so a false positive costs real context. The repetition COUNTER uses the
    wider ``repetition_keys`` instead, where a false positive only costs a bit
    of penalty.
    """
    if not content:
        return ""
    return _normalize_fuzzy(content)[:length]


def repetition_keys(
        content: str,
        min_sentence_chars: int = REPETITION_SENTENCE_MIN_CHARS) -> set:
    """Comparison keys of a reply — for the repetition COUNTER.

    Two replies count as a repetition as soon as they share one key:

    - the opening signature (``fuzzy_signature``) — catches the reply that
      restarts with the same phrase, i.e. the old whole-message behaviour;
    - every single sentence with at least ``min_sentence_chars`` normalized
      characters — catches the far more common case where a reply opens with a
      new sentence and only then falls back into the old text (measured in
      task-A1.1-report.md section 2.5: roughly half of the real repetitions are
      only visible at sentence level).

    Deliberately more sensitive than ``fuzzy_signature``: here a false positive
    only raises the penalty a notch, while a miss lets the loop run.
    """
    if not content:
        return set()
    keys = set()
    sig = fuzzy_signature(content)
    if sig:
        keys.add(sig)
    for part in _SENTENCE_SPLIT_RE.split(_FUZZY_MARKER_RE.sub("", content)):
        normalized = _normalize_fuzzy(part)
        if len(normalized) >= min_sentence_chars:
            keys.add(normalized)
    return keys


def repetition_shingles(content: str,
                        words: int = REPETITION_SHINGLE_WORDS) -> set:
    """Word n-grams of a reply (markers removed) — the paraphrase half of the
    repetition COUNTER. A reply shorter than ``words`` words has none; the
    opening signature carries those."""
    if not content:
        return set()
    tokens = _WORD_RE.findall(_FUZZY_MARKER_RE.sub("", content).lower())
    return {tuple(tokens[i:i + words]) for i in range(len(tokens) - words + 1)}


def count_assistant_repetitions(messages: List[Dict[str, str]],
                                 lookback: int = 6) -> int:
    """Counts how many of the last ``lookback`` assistant replies repeat
    something an earlier one in that window already said.

    A reply counts once, no matter how much of it is old — its opening
    signature or one of its sentences was seen before (see
    ``repetition_keys``), or at least ``REPETITION_SHINGLE_SHARE`` of its word
    4-grams were (``repetition_shingles``). Example: 4 replies opening the same
    way + 1 + 1 → 3 repetitions. The result drives the graduated penalty bump
    (base + step * count, see ``anti_repetition_overrides``).

    ``messages`` is a chat-ordered list (oldest first); only entries with
    ``role == "assistant"`` are looked at.
    """
    if not messages:
        return 0
    window: List[Tuple[set, set]] = []
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        keys = repetition_keys(content)
        if keys:
            window.append((keys, repetition_shingles(content)))
        if len(window) >= lookback:
            break
    window.reverse()  # oldest first again — "seen before" needs the real order

    seen: set = set()
    seen_shingles: set = set()
    repetitions = 0
    for keys, shingles in window:
        reused = (len(shingles & seen_shingles) / len(shingles)
                  if shingles else 0.0)
        if keys & seen or reused >= REPETITION_SHINGLE_SHARE:
            repetitions += 1
        seen |= keys
        seen_shingles |= shingles
    return repetitions


def anti_repetition_overrides(
        recent_outputs: List[Dict[str, str]],
        base_temperature: float,
        agent_name: str = "",
        with_frequency_penalty: bool = True,
        base_repetition_penalty: Optional[float] = None) -> Dict[str, Any]:
    """The reactive anti-loop net, shared by the chat and the thought path.

    A safety net, not a sampling setting: when a character starts repeating
    itself, the penalties are raised per detected repetition.

    - ``repetition_penalty`` (``chat.anti_rep_rp_step``, capped at
      ``chat.anti_rep_rp_max``) is the instrument that reaches an echo of the
      HISTORY: vLLM applies it to every token of the prompt and the reply.
      It is raised only from the base value of the LLM entry
      (``base_repetition_penalty``) — an entry without one is on a backend
      that may not know the parameter, so nothing is sent there.
    - ``frequency_penalty`` (``chat.anti_rep_penalty_step``, capped at
      ``chat.anti_rep_penalty_max``) is the OpenAI parameter every backend
      takes. vLLM counts only the tokens of the reply being generated, so it
      curbs a loop inside one reply and does not see a line copied from the
      history (measured 2026-10-23: at 0.45 a 111B model copied its own
      previous reply verbatim in 2 of 4 samples).

    Temperature is NOT that instrument and is off by default
    (``chat.anti_rep_step`` = 0). It was the only lever until 2026-08-03, and
    it is measurably destructive: at a raised temperature of 1.10, two out of
    two replies of one model collapsed into multi-script token salad, against
    zero of 26 at its configured 0.80 in the same window. Anyone switching it
    back on wants ``chat.top_p`` set as well — without a nucleus cut-off every
    temperature step lifts the least likely tokens the most.

    ``chat.top_p`` is applied on every call that goes through this net,
    repetition or not: it is the standing clamp, not a reaction.

    Args:
        recent_outputs: the character's own recent outputs as a chat-ordered
            message list (oldest first); only ``role == "assistant"`` counts.
            A caller with a different journal wraps its entries accordingly.
        base_temperature: the temperature configured in LLM Routing.
        agent_name: for the log line only.
        with_frequency_penalty: pass False for paths that are not a chat reply
            — the STATIC penalty is a configured chat-reply value and stays
            where it was configured for. The reactive bump crosses over
            regardless, starting from 0 instead of from the static value.
        base_repetition_penalty: the ``repetition_penalty`` of the LLM entry
            (``LLMInstance.repetition_penalty``); None = the entry sends none,
            and the net leaves it that way.

    Returns:
        kwargs for ``LLMInstance.create_llm``. An empty dict = change nothing.
    """
    from app.core import config

    overrides: Dict[str, Any] = {}

    top_p = float(config.get("chat.top_p", 0) or 0)
    if top_p > 0:
        overrides["top_p"] = top_p

    static_penalty = 0.0
    if with_frequency_penalty:
        static_penalty = float(config.get("chat.frequency_penalty", 0.3) or 0)
        if static_penalty > 0:
            overrides["frequency_penalty"] = static_penalty

    temp_step = float(config.get("chat.anti_rep_step", 0) or 0)
    pen_step = float(config.get("chat.anti_rep_penalty_step", 0.15) or 0)
    rp_step = (float(config.get("chat.anti_rep_rp_step", RP_STEP_DEFAULT) or 0)
               if base_repetition_penalty is not None else 0.0)
    if temp_step <= 0 and pen_step <= 0 and rp_step <= 0:
        return overrides  # reactive net disabled

    lookback = int(config.get("chat.anti_rep_lookback", 6) or 6)
    count = count_assistant_repetitions(recent_outputs, lookback)
    if count <= 0:
        return overrides

    parts = []
    if pen_step > 0:
        pen_ceiling = float(config.get("chat.anti_rep_penalty_max", 1.0) or 1.0)
        new_penalty = min(static_penalty + pen_step * count, pen_ceiling)
        overrides["frequency_penalty"] = new_penalty
        parts.append("penalty %.2f → %.2f" % (static_penalty, new_penalty))
    if rp_step > 0:
        rp_ceiling = float(config.get("chat.anti_rep_rp_max", RP_MAX_DEFAULT)
                           or RP_MAX_DEFAULT)
        # A ceiling below the entry's own base never LOWERS the base.
        new_rp = max(min(base_repetition_penalty + rp_step * count, rp_ceiling),
                     base_repetition_penalty)
        overrides["repetition_penalty"] = new_rp
        parts.append("repetition_penalty %.2f → %.2f"
                     % (base_repetition_penalty, new_rp))
    if temp_step > 0:
        ceiling = float(config.get("chat.anti_rep_max", 0.9) or 0.9)
        new_temp = min(base_temperature + temp_step * count, ceiling)
        overrides["temperature"] = new_temp
        parts.append("temperature %.2f → %.2f" % (base_temperature, new_temp))

    logger.info(
        "[%s] %d repetition(s) detected in the last %d turns → %s",
        agent_name or "?", count, lookback, ", ".join(parts))
    return overrides


def strip_history_artifacts(content: str) -> str:
    """Remove artifacts from chat content before it enters the messages array.

    Noise for the LLM that does not belong into the recent history:
    - Markdown image embeds ``![alt](url)`` — the LLM sees them as cryptic URL
      blocks and may imitate them in its own replies
    - generated-image markers / image URL leftovers

    The DB content stays unchanged; only the stream sent to the LLM is cleaned.
    """
    if not content:
        return content
    # Markdown image embeds on one or more lines
    content = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', content)
    # Normalise repeated blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


def resolve_speaker(msg: Dict[str, str],
                    partner: str,
                    character_name: str) -> str:
    """Determine the actual speaker of a chat_messages row.

    Priority:
      1. metadata.speaker  (set by TalkTo, group, inbox)
      2. partner           (role='user' = the counterpart spoke)
      3. character_name    (role='assistant' = the character itself spoke)

    Returns a character name, no "Player" fallback. An empty string only when
    neither partner nor character_name is known — callers skip such rows.
    """
    meta = msg.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    speaker = (meta.get("speaker") or "").strip() if isinstance(meta, dict) else ""
    if speaker:
        return speaker

    role = (msg.get("role") or "").strip().lower()
    if role == "user":
        return (partner or "").strip()
    if role == "assistant":
        return (character_name or "").strip()
    return (character_name or partner or "").strip()


def _clean_message_for_summary(content: str) -> str:
    """Strip tool calls, image URLs and technical artefacts from a message.

    Keeps old tool-call patterns out of the summary, where the LLM would
    otherwise hallucinate them as new tool calls.
    """
    # Tool-call patterns (every format)
    # Tag format: <tool name="...">...</tool>
    content = re.sub(r'<tool\s+name="[^"]*">[\s\S]*?</tool>', '', content)
    # Natural EN: Use ToolName for: ...
    content = re.sub(r'(?:I\s+)?[Uu]se\s+\w+\s+for:\s*.*?(?:\n|$)', '', content)
    # Natural DE: Ich nutze ToolName für: ...
    content = re.sub(r'(?:Ich\s+)?[Nn]utze\s+\w+\s+f(?:ü|ue)r:\s*.*?(?:\n|$)', '', content)

    # Markdown images: ![...](...)
    content = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', content)
    # Raw image URLs
    content = re.sub(r'/(?:characters|instagram)/\S+\.png\S*', '', content)

    # Technical artefacts — a tool's failure answer included, in either
    # spelling ("Error: …" today, the older German "Fehler: …")
    content = re.sub(r'Post-ID:\s*\S+', '', content)
    content = re.sub(r'(?:Fehler|Error):.*?(?:\n|$)', '', content)

    # LLM tokenizer artefacts (e.g. <SPECIAL_28>, <|END_OF_TURN_TOKEN|>)
    content = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', content)

    # Collapse runs of blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()


def _create_history_summary(
    old_history: List[Dict[str, str]],
    character_name: str = "",
    partner_name: str = "") -> str:
    """Summarise older chat messages between TWO characters via the router
    (task: consolidation).

    Args:
        old_history: older chat messages of this dyadic conversation. May
                     carry `partner`, `metadata` — used to resolve speakers.
        character_name: memory owner (speaker B)
        partner_name:   conversation partner (speaker A). When empty, derived
                        from the first message with role='user'.
    """
    if not old_history:
        return ""

    if not partner_name:
        for msg in old_history:
            p = (msg.get("partner") or "").strip() if isinstance(msg, dict) else ""
            if p:
                partner_name = p
                break

    if not partner_name or not character_name:
        return ""

    # Nachrichten bereinigen (Tool-Calls, Bild-URLs etc. entfernen).
    # Sprecher pro Zeile aus metadata/partner/role aufloesen — kein
    # globales user_display-Label mehr.
    cleaned_parts = []
    for msg in old_history:
        speaker = resolve_speaker(msg, partner_name, character_name)
        if not speaker:
            continue
        cleaned = _clean_message_for_summary(msg.get('content', ''))
        if cleaned:
            cleaned_parts.append(f"{speaker}: {cleaned}")

    if not cleaned_parts:
        return ""

    # Nachrichten begrenzen um extrem lange Prompts zu vermeiden
    max_parts = 60
    if len(cleaned_parts) > max_parts:
        cleaned_parts = cleaned_parts[-max_parts:]

    history_text = "\n".join(cleaned_parts)

    # Textlaenge hart begrenzen (ca. 8000 Tokens)
    max_chars = 24000
    if len(history_text) > max_chars:
        history_text = history_text[-max_chars:]

    # Sprache des Characters ermitteln
    lang_instruction = ""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) if character_name else {}
        lang_code = profile.get("language", "")
        if lang_code and lang_code != "en":
            from app.models.character import LANGUAGE_MAP
            lang_name = LANGUAGE_MAP.get(lang_code, lang_code)
            lang_instruction = f"\nWrite the summary in {lang_name}."
    except Exception:
        pass

    from app.core.prompt_templates import render_task

    def _build(text: str) -> tuple:
        return render_task(
            "consolidation_history_summary",
            speaker_a=partner_name,
            speaker_b=character_name,
            lang_instruction=lang_instruction,
            history_text=text)

    sys_prompt, summary_prompt = _build(history_text)

    try:
        from app.core.llm_router import llm_call
        response = llm_call(
            task="consolidation",
            system_prompt=sys_prompt,
            user_prompt=summary_prompt,
            agent_name=character_name)
        summary = (response.content or "").strip()

        # Safety net: strip tool-call patterns from the summary too
        summary = _clean_message_for_summary(summary)

        return summary
    except Exception as e:
        err_str = str(e)
        # Context-size error: shorten the prompt and retry
        if "exceed" in err_str and "context" in err_str:
            logger.warning("Context-size error, shortening the prompt and retrying...")
            shorter = "\n".join(cleaned_parts[-30:])
            if len(shorter) > 12000:
                shorter = shorter[-12000:]
            _, retry_prompt = _build(shorter)
            try:
                response = llm_call(
                    task="consolidation",
                    system_prompt=sys_prompt,
                    user_prompt=retry_prompt,
                    agent_name=character_name)
                summary = _clean_message_for_summary((response.content or "").strip())
                return summary
            except Exception as retry_e:
                logger.error("Summary retry auch fehlgeschlagen: %s", retry_e)
        else:
            logger.error("Summary creation error: %s", e)
        return ""


# === Cached Summary (non-blocking) ===

def get_cached_summary(character_name: str) -> str:
    """Read the cached history summary exclusively from the database."""
    try:
        conn = get_connection()
        row = conn.execute("""
            SELECT content FROM summaries
            WHERE character_name=? AND kind='history' AND date_key='current'
        """, (character_name,)).fetchone()
        if row:
            return row[0] or ""
    except Exception as e:
        logger.debug("get_cached_summary DB error for %s: %s", character_name, e)
    return ""


def _save_cached_summary(character_name: str, summary: str, message_count: int = 0):
    """Store a history summary in the DB."""
    now = utc_now_iso()
    try:
        with transaction() as conn:
            conn.execute("""
                INSERT INTO summaries (character_name, kind, date_key, partner, content, meta)
                VALUES (?, 'history', 'current', '', ?, ?)
                ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET
                    content=excluded.content,
                    meta=excluded.meta
            """, (
                character_name,
                summary,
                json.dumps({"message_count": message_count, "updated_at": now},
                           ensure_ascii=False),
            ))
    except Exception as e:
        logger.error("_save_cached_summary DB error for %s: %s", character_name, e)


_SUMMARY_THROTTLE_MINUTES = 30  # minimum gap between summary updates


def _is_summary_fresh(character_name: str) -> bool:
    """Whether the cached summary is younger than THROTTLE_MINUTES."""
    try:
        conn = get_connection()
        row = conn.execute("""
            SELECT meta FROM summaries
            WHERE character_name=? AND kind='history' AND date_key='current'
        """, (character_name,)).fetchone()
        if row:
            meta = json.loads(row[0] or "{}")
            updated = meta.get("updated_at", "")
            if updated:
                age = (utc_now() - parse_iso(updated)).total_seconds()
                return age < _SUMMARY_THROTTLE_MINUTES * 60
    except Exception:
        pass
    return False


def update_summary_background(character_name: str,
                              old_messages: List[Dict[str, str]],
                              partner_name: str = ""):
    """Update the session summary (the chat before the sliding window).

    Called after the chat, does NOT block it. Throttled: at most one update
    every 30 minutes.

    ONLY the history summary — day summaries are built by the consolidation
    pipeline (every 6h), not in the chat path.

    `partner_name` is optional — when empty, the first partner is derived
    from the messages.
    """
    if _is_summary_fresh(character_name):
        logger.debug("Summary for %s still fresh, skipping the update", character_name)
        return

    try:
        summary = _create_history_summary(old_messages,
                                          character_name=character_name,
                                          partner_name=partner_name)
        if summary:
            _save_cached_summary(character_name, summary, len(old_messages))
            logger.info("Session summary updated for %s (%d messages)", character_name, len(old_messages))
    except Exception as e:
        logger.error("Session summary failed: %s", e)


def _summary_updated_at(character_name: str) -> "datetime | None":
    """Liest updated_at-Timestamp der gecachten Summary."""
    try:
        conn = get_connection()
        row = conn.execute("""
            SELECT meta FROM summaries
            WHERE character_name=? AND kind='history' AND date_key='current'
        """, (character_name,)).fetchone()
        if row:
            meta = json.loads(row[0] or "{}")
            updated = meta.get("updated_at", "")
            if updated:
                return parse_iso(updated)
    except Exception:
        pass
    return None


def refresh_summary_if_uncovered(
    character_name: str,
    old_messages: List[Dict[str, str]]) -> str:
    """Synchronous refresh — returns the summary, regenerating it when the
    cached one does not cover the current ``old_messages``.

    Called before the system prompt is built. Does ``old_messages`` hold
    entries younger than the cached summary's ``updated_at``? Then the summary
    is stale (e.g. after a session-gap cut) and is regenerated via the LLM
    (~5-15s). The throttle is ignored here on purpose.

    Returns: the current (possibly regenerated) summary.
    """
    cached = get_cached_summary(character_name)
    if not old_messages:
        return cached

    updated_at = _summary_updated_at(character_name)

    # Juengsten Timestamp in old_messages finden
    newest_old = None
    for msg in old_messages:
        ts = msg.get("timestamp", "")
        if not ts:
            continue
        try:
            t = parse_iso(ts)
            if newest_old is None or t > newest_old:
                newest_old = t
        except (ValueError, TypeError):
            continue

    needs_refresh = (
        cached == ""
        or updated_at is None
        or (newest_old is not None and newest_old > updated_at)
    )
    if not needs_refresh:
        return cached

    try:
        summary = _create_history_summary(old_messages,
                                          character_name=character_name)
        if summary:
            _save_cached_summary(character_name, summary, len(old_messages))
            logger.info(
                "Session summary refreshed synchronously for %s (%d messages)",
                character_name, len(old_messages))
            return summary
    except Exception as e:
        logger.error("Synchronous summary refresh failed: %s", e)

    return cached


# === Daily Summaries ===

def load_daily_summaries(character_name: str,
                         partner: str = "") -> Dict[str, Dict[str, str]]:
    """Loads all day summaries from the DB. Keys are GAME days ("Y0002-D109").

    Returns:
        `partner` empty: {day_key: {partner_name: summary_text, ...}}
        `partner` set:   {day_key: summary_text} (single-partner form)

    Two owners (linked characters): the per-partner rows are the character's
    own (they follow its chat), the general slot (partner '') is its MIND's
    day entry — a linked body reads its leader's.
    """
    from app.core.linked_characters import mind_of
    try:
        conn = get_connection()
        if partner:
            rows = conn.execute("""
                SELECT date_key, content FROM summaries
                WHERE character_name=? AND kind='daily' AND partner=?
                ORDER BY date_key ASC
            """, (character_name, partner)).fetchall()
            return {r[0]: r[1] for r in rows} if rows else {}
        rows = conn.execute("""
            SELECT date_key, partner, content FROM summaries
            WHERE kind='daily' AND ((character_name=? AND partner<>'')
                                    OR (character_name=? AND partner=''))
            ORDER BY date_key ASC
        """, (character_name, mind_of(character_name))).fetchall()
        result: Dict[str, Dict[str, str]] = {}
        for date_key, p, content in rows:
            result.setdefault(date_key, {})[p or ""] = content
        return result
    except Exception as e:
        logger.debug("load_daily_summaries DB error for %s: %s", character_name, e)
        return {}


def load_daily_summaries_combined(character_name: str) -> Dict[str, str]:
    """Variant of load_daily_summaries for consumers that are not partner-aware
    (the week/season consolidation) — over the character's whole MIND.

    Folds all entries of a day into one combined string, the mind's general
    entry and per-partner entries first, then those of every linked body of
    the family marked "(as <body>)" (ruling R4):
        "<general>
         With Kahiro: ...
         (as Glut) With Rosi: ..."
    """
    from app.core.linked_characters import family_of, mind_of
    mind = mind_of(character_name)
    flat_parts: Dict[str, List[str]] = {}
    for member in family_of(mind):
        by_day = load_daily_summaries(member)  # {day_key: {partner: text}}
        mark = f"(as {member}) " if member != mind else ""
        for day_key, by_partner in by_day.items():
            for partner, text in sorted((by_partner or {}).items()):
                if not text or (member != mind and not partner):
                    continue  # a body's general slot is the mind's, counted once
                flat_parts.setdefault(day_key, []).append(
                    f"{mark}With {partner}: {text}" if partner else text)
    return {day_key: "\n".join(parts) for day_key, parts in flat_parts.items() if parts}


def save_daily_summary(character_name: str, day_key: str, summary: str,
                       partner: str = ""):
    """Stores/overwrites a day summary in the DB. ``day_key`` is a GAME day
    ("Y0002-D109").

    `partner` is the conversation partner (character name) — such a row is
    the character's own. Without a partner the row is the general day entry
    of the character's MIND (linked characters: a body writes its leader's).
    """
    if not partner:
        from app.core.linked_characters import mind_of
        character_name = mind_of(character_name)
    try:
        with transaction() as conn:
            conn.execute("""
                INSERT INTO summaries (character_name, kind, date_key, partner, content)
                VALUES (?, 'daily', ?, ?, ?)
                ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET
                    content=excluded.content
            """, (character_name, day_key, partner, summary))
    except Exception as e:
        logger.error("save_daily_summary DB error for %s/%s: %s",
                     character_name, partner, e)


def delete_daily_summaries(character_name: str, date_keys: List[str],
                           partner: str = "", *, partners_only: bool = False):
    """Delete day summaries of the character from the DB.

    `partner` set: only that partner's entries. `partners_only`: every
    per-partner entry, the general slot (partner '') stays — what a mind's
    rollup removes from a linked body. Otherwise every entry of the date keys.
    """
    if not date_keys:
        return
    try:
        with transaction() as conn:
            placeholders = ",".join("?" for _ in date_keys)
            if partner:
                conn.execute(
                    f"DELETE FROM summaries WHERE character_name=? AND "
                    f"kind='daily' AND partner=? AND "
                    f"date_key IN ({placeholders})",
                    (character_name, partner, *date_keys),
                )
            elif partners_only:
                conn.execute(
                    f"DELETE FROM summaries WHERE character_name=? AND "
                    f"kind='daily' AND partner<>'' AND "
                    f"date_key IN ({placeholders})",
                    (character_name, *date_keys),
                )
            else:
                conn.execute(
                    f"DELETE FROM summaries WHERE character_name=? AND "
                    f"kind='daily' AND date_key IN ({placeholders})",
                    (character_name, *date_keys),
                )
    except Exception as e:
        logger.error("delete_daily_summaries DB error for %s: %s", character_name, e)


def get_recent_daily_summaries(character_name: str,
                               days: int = 0,
                               partner: str = "") -> List[Dict[str, str]]:
    """The last N GAME days that have summaries (oldest first).

    Returns: [{"date": "Y0002-D109", "partner": "Kahiro", "summary": "..."}, ...]
    `partner` set: only that partner's summaries.
    """
    if days <= 0:
        from app.core import config
        days = int(config.get("knowledge.daily_summary_days", 7) or 7)

    summaries = load_daily_summaries(character_name)  # day_key -> {partner: text}
    if not summaries:
        return []

    from app.core.day_consolidation import recent_game_day_keys
    result: List[Dict[str, str]] = []
    for day_key in recent_game_day_keys(days, skip_today=True):
        per_partner = summaries.get(day_key) or {}
        if not per_partner:
            continue
        for p, text in per_partner.items():
            if partner and p != partner:
                continue
            result.append({"date": day_key, "partner": p, "summary": text})
    return result


def build_daily_summary_prompt_section(character_name: str,
                                       max_days: int = 0,
                                       partner: str = "") -> str:
    """Build the prompt section of the day summaries (tier 2: SHORT to MID).

    Loads day summaries from SHORT_TERM_DAYS (default 3) up to max_days. Days
    within SHORT_TERM_DAYS are skipped — the chat history covers them.

    max_days: 0 = MID_TERM_DAYS (default 30). May be reduced for
              TalkTo/social (e.g. 7 days).
    partner: when set, only the summaries with this conversation partner.
             Otherwise summaries are rendered per day/partner.

    Format:
    Recent days:
    - Winter, day 17 · Year 2 with Kahiro: Summary text...
    - Winter, day 17 · Year 2 with Rosi:   Summary text...
    - Winter, day 18 · Year 2 with Kahiro: Summary text...
    """
    from app.core.day_consolidation import parse_day_key
    from app.core.game_time import GameDuration
    from app.core.timeutils import game_time

    thresholds = get_memory_thresholds()
    if max_days <= 0:
        max_days = thresholds["mid_term_days"]
    short = thresholds["short_term_days"]

    recent = get_recent_daily_summaries(character_name, days=max_days,
                                        partner=partner)
    if not recent:
        return ""

    # Only days older than SHORT_TERM_DAYS (the chat history covers the rest)
    cutoff = game_time().minus_clamped(GameDuration.of(days=short))
    lines = []
    for entry in recent:
        day = parse_day_key(entry["date"])
        if day is not None:
            if day > cutoff:
                continue  # inside the short term — the chat history is enough
            label = day.date_label()
        else:
            label = entry["date"]
        partner_label = entry.get("partner") or ""
        if partner_label:
            lines.append(f"- {label} with {partner_label}: {entry['summary']}")
        else:
            lines.append(f"- {label}: {entry['summary']}")

    if not lines:
        return ""
    return "\nRecent days:\n" + "\n".join(lines)


def build_longterm_summary_prompt_section(character_name: str,
                                          lang: str = "en") -> str:
    """Prompt section for long-term memory (tier 3: weeks + seasons).

    ``lang`` localizes the season names, so the section speaks the same
    language as the rest of the prompt.

    Format:
    Long-term memories:
    Seasons:
    - Winter · Year 2: Summary...
    Weeks:
    - Y0002-W016: Summary...
    """
    from app.core.memory_service import (season_label, load_monthly_summaries,
                                         load_weekly_summaries)

    monthly = load_monthly_summaries(character_name)
    weekly = load_weekly_summaries(character_name)

    if not monthly and not weekly:
        return ""

    parts = ["\nLong-term memories:"]

    if monthly:
        parts.append("Seasons:")
        for season_key in sorted(monthly.keys()):
            parts.append(f"- {season_label(season_key, lang)}: {monthly[season_key]}")

    if weekly:
        parts.append("Weeks:")
        for week_key in sorted(weekly.keys()):
            parts.append(f"- {week_key}: {weekly[week_key]}")

    return "\n".join(parts)


def _get_day_messages(character_name: str, day_key: str) -> List[Dict[str, str]]:
    """Messages of ONE GAME day ("Y0002-D109") from the DB.

    Chat messages carry SYSTEM stamps only (``chat_messages.ts``) — there is
    no game stamp on the chat storage path — so the game day is turned into a
    system window by ``timeutils.system_window_of_game_day``. With a game
    factor > 1 that window is correspondingly shorter than a real day, which
    is exactly the point of decision E4: a rollup per day the world
    experienced, not per day the server ran.
    """
    from app.core.timeutils import system_window_of_game_day
    window = system_window_of_game_day(day_key)
    if window is None:
        logger.debug("_get_day_messages: %r is not a game day key", day_key)
        return []
    try:
        conn = get_connection()
        rows = conn.execute("""
            SELECT role, content, partner, metadata, ts FROM chat_messages
            WHERE character_name=?
              AND ts >= ? AND ts < ?
            ORDER BY ts ASC
        """, (character_name, window[0], window[1])).fetchall()
        result = []
        for r in rows:
            role, content, partner, metadata, ts = r
            if not role or not content:
                continue
            result.append({
                "role": role,
                "content": content,
                "partner": partner or "",
                "metadata": metadata or "{}",
                "ts": ts or "",
            })
        return result
    except Exception as e:
        logger.debug("_get_day_messages DB error for %s/%s: %s", character_name, day_key, e)
        return []


def _group_by_partner(messages: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Group a day's messages by partner character.

    The partner is the actual conversation partner. Group-chat rows (several
    speakers) go under the row's `partner` field. Rows without a partner are
    skipped.
    """
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for msg in messages:
        partner = (msg.get("partner") or "").strip()
        if not partner:
            continue
        grouped.setdefault(partner, []).append(msg)
    return grouped


def _create_daily_summary(messages: List[Dict[str, str]],
                          character_name: str = "",
                          partner_name: str = "") -> str:
    """Create a day summary for one conversation partner.

    Args:
        messages: the day's messages BETWEEN character_name and partner_name,
                  already filtered by the caller via `_group_by_partner`.
        character_name: memory owner (speaker B)
        partner_name:   conversation partner (speaker A). Mandatory — without
                        a partner there is no dyadic summary.
    """
    if not messages:
        return ""
    if not partner_name or not character_name:
        logger.debug("daily_summary skip: partner_name=%r char=%r",
                     partner_name, character_name)
        return ""

    # Sprecher pro Zeile aufloesen — KEIN globales user_display-Label.
    cleaned_parts = []
    for msg in messages:
        speaker = resolve_speaker(msg, partner_name, character_name)
        if not speaker:
            continue
        cleaned = _clean_message_for_summary(msg.get("content", ""))
        if cleaned:
            cleaned_parts.append(f"{speaker}: {cleaned}")

    if not cleaned_parts:
        return ""

    # Nachrichten begrenzen
    max_parts = 80
    if len(cleaned_parts) > max_parts:
        cleaned_parts = cleaned_parts[-max_parts:]

    history_text = "\n".join(cleaned_parts)

    # Textlaenge hart begrenzen (ca. 8000 Tokens)
    max_chars = 24000
    if len(history_text) > max_chars:
        history_text = history_text[-max_chars:]

    # Sprache des Characters ermitteln
    lang_instruction = ""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) if character_name else {}
        lang_code = profile.get("language", "")
        if lang_code and lang_code != "en":
            from app.models.character import LANGUAGE_MAP
            lang_name = LANGUAGE_MAP.get(lang_code, lang_code)
            lang_instruction = f"\nWrite the summary in {lang_name}."
    except Exception:
        pass

    from app.core.prompt_templates import render_task
    sys_prompt, summary_prompt = render_task(
        "consolidation_today",
        speaker_a=partner_name,
        speaker_b=character_name,
        lang_instruction=lang_instruction,
        history_text=history_text)

    try:
        from app.core.llm_router import llm_call
        response = llm_call(
            task="consolidation",
            system_prompt=sys_prompt,
            user_prompt=summary_prompt,
            agent_name=character_name)
        summary = (response.content or "").strip()
        summary = _clean_message_for_summary(summary)
        return summary
    except Exception as e:
        logger.error("Daily summary Erstellung fehlgeschlagen: %s", e)
        return ""


def _update_daily_summary(character_name: str):
    """Updates today's day summary — one per conversation partner.

    "Today" is the GAME day (decision E4), so the entry is keyed and rewritten
    per game day, not per real day.
    """
    from app.core.timeutils import game_time
    today_key = game_time().day_key()
    today_messages = _get_day_messages(character_name, today_key)
    if not today_messages:
        return

    grouped = _group_by_partner(today_messages)
    for partner, msgs in grouped.items():
        if len(msgs) < 4:
            # too few messages for a meaningful summary
            continue
        summary = _create_daily_summary(msgs,
                                        character_name=character_name,
                                        partner_name=partner)
        if summary:
            save_daily_summary(character_name, today_key, summary,
                               partner=partner)
            logger.info("Daily summary %s↔%s %s: updated (%d messages)",
                        character_name, partner, today_key, len(msgs))


def _is_bad_summary(summary: str) -> bool:
    """Whether a summary is obviously broken and should be regenerated."""
    if not summary or len(summary) < 30:
        return True
    s = summary.lower()
    bad_patterns = [
        "it seems like you",
        "it looks like you",
        "end of extract",
        "i can't help",
        "i cannot help",
        "as an ai",
        "as a language model",
    ]
    return any(p in s for p in bad_patterns)


def backfill_missing_daily_summaries(character_name: str):
    """Creates missing day summaries for past GAME days — one per partner.

    Checks the last ``knowledge.daily_summary_days`` game days (default 7).
    Skips today (updated separately) and (day, partner) pairs that already
    have a summary.
    """
    from app.core.day_consolidation import recent_game_day_keys

    existing = load_daily_summaries(character_name)  # {day_key: {partner: text}}
    from app.core import config
    days = int(config.get("knowledge.daily_summary_days", 7) or 7)

    backfilled = 0
    max_backfill_per_run = 2  # cap per run so the queue does not block

    # newest first — the recent days matter most when the cap cuts the run off
    for day_key in reversed(recent_game_day_keys(days, skip_today=True)):
        if backfilled >= max_backfill_per_run:
            break

        messages = _get_day_messages(character_name, day_key)
        if not messages:
            continue

        grouped = _group_by_partner(messages)
        if not grouped:
            continue

        existing_for_day = existing.get(day_key) or {}

        for partner, msgs in grouped.items():
            if backfilled >= max_backfill_per_run:
                break
            if len(msgs) < 4:
                continue
            # already there and clean → skip
            if (partner in existing_for_day
                    and not _is_bad_summary(existing_for_day[partner])):
                continue

            summary = _create_daily_summary(msgs,
                                            character_name=character_name,
                                            partner_name=partner)
            if summary:
                save_daily_summary(character_name, day_key, summary,
                                   partner=partner)
                logger.info("Daily summary backfill %s↔%s %s (%d messages)",
                            character_name, partner, day_key, len(msgs))
                backfilled += 1
