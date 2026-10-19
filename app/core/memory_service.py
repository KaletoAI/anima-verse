"""Memory service — extraction, consolidation and background worker.

Extracts memories from a chat exchange (both sides) and periodically
consolidates older memories.

The rollup ladder runs on the GAME calendar (plan-game-calendar.md, decision
E4): day → week → season, keyed ``Y0002-D109`` / ``Y0002-W016`` / ``Y0002-S01``.
A week is a block of ``len(week_days)`` game days (7 when the world has no
weekdays), a "monthly" summary is one SEASON of the world calendar — the
calendar has no months. All three keys sort lexicographically in chronological
order, so the plain SQL ordering keeps working.
"""
import json
import re
from datetime import timedelta

from app.core.game_time import GameDuration, GameTime, get_calendar
from app.core.timeutils import game_time, parse_iso, utc_now
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("memory_service")


# ---------------------------------------------------------------------------
# Game-calendar keys of the rollup ladder
# ---------------------------------------------------------------------------

_WEEK_KEY_RE = re.compile(r"^Y(\d{4,})-W(\d{3,})$")


def _week_length() -> int:
    """Days per week — the world's weekday count, 7 when it has none."""
    return len(get_calendar().week_days) or 7


def _week_key(when: GameTime) -> str:
    """``Y0002-W016`` — the week of the year the given instant falls into.

    Weeks are counted inside the year (the last one is short when the year
    length is not a multiple of the week length), which keeps the key sortable
    and readable without needing a year-crossing week index.
    """
    parts = when.parts()
    index = (parts.day_of_year - 1) // _week_length() + 1
    return f"Y{parts.year:04d}-W{index:03d}"


def _week_start(week_key: str) -> Optional[GameTime]:
    """First day of the week a ``_week_key`` names, or ``None``."""
    match = _WEEK_KEY_RE.match(week_key or "")
    if not match:
        return None
    year, index = int(match.group(1)), int(match.group(2))
    if year < 1 or index < 1:
        return None
    try:
        return GameTime.from_parts(year, (index - 1) * _week_length() + 1)
    except ValueError:
        return None


def _season_key(when: GameTime) -> str:
    """``Y0002-S01`` — the season the given instant falls into.

    The season is the world calendar's counterpart of a month; it is what the
    ``kind='monthly'`` rollup collapses into.
    """
    parts = when.parts()
    return f"Y{parts.year:04d}-S{parts.season_index + 1:02d}"


def memory_day_key(entry: Dict[str, Any]) -> str:
    """Game day a memory belongs to ("" when it cannot be told).

    Exact, not projected: a memory row carries its own canonical ``game_ts``,
    written when it was formed, so the rollup groups by the world day the
    memory actually happened on.

    ``day_consolidation.game_day_of`` (back-projecting the SYSTEM stamp) is
    only the fallback for rows that predate the calendar migration and were
    not backfilled — after the migration there should be none. The projection
    re-derives the game time from the CURRENT anchor and factor, so it drifts
    for old rows as soon as the world clock is set or sped up; that is why it
    is the fallback and not the source.
    """
    from app.core.day_consolidation import game_day_of
    raw = (entry.get("game_ts") or "").strip()
    if raw:
        try:
            return GameTime.parse(raw).day_key()
        except (ValueError, TypeError):
            pass
    return game_day_of(entry.get("timestamp", ""))


def season_label(season_key: str, lang: str = "en") -> str:
    """Readable name of a season key for the prompt ("Winter · Year 2").

    The season name is localized through the calendar, so a prompt written in
    the character's language does not carry an English season into it.
    """
    try:
        year, index = season_key.split("-S")
        seasons = get_calendar().seasons
        name = seasons[(int(index) - 1) % len(seasons)].name_for(lang) if seasons else ""
        return f"{name} · Year {int(year[1:])}" if name else season_key
    except (ValueError, IndexError, ZeroDivisionError):
        return season_key


# ---------------------------------------------------------------------------
# Memory extraction from chat exchanges
# ---------------------------------------------------------------------------

def extract_memories_from_exchange(character_name: str,
    partner_name: str,
    partner_message: str,
    own_message: str,
    llm) -> List[Dict[str, Any]]:
    """Extract memories from a character-to-character exchange.

    Args:
        character_name: Memory owner (speaker B in the template)
        partner_name:   Conversation partner (speaker A in the template) — an
                        avatar or another NPC name. EMPTY means a thought turn:
                        the monologue template is used, no addressee is
                        invented, and related_character stays empty unless the
                        text itself names someone.
        partner_message: What the partner said (text_a)
        own_message:    What the memory owner said (text_b)

    Returns list of extracted memory dicts.
    """
    from app.models.character import get_character_config
    config = get_character_config(character_name)

    if not config.get("extraction_enabled", True):
        return []

    # No partner = a thought turn, not a dyadic exchange. That is the ONLY
    # path this function still gets called on since the per-turn chat
    # extraction was retired (chat_engine, "if _is_thought"), so refusing it
    # meant refusing everything: no semantic fact and no commitment has been
    # written since 2026-06-07. A monologue gets its own template — naming an
    # absent partner as the other speaker would invent an addressee, and
    # related_character below would then attribute every fact to them.
    partner_name = (partner_name or "").strip()
    monologue = not partner_name

    # Existing memories for fact deduplication.
    # load_memories sorts ts DESC, so the NEWEST entries are at the front —
    # a [-15:] slice would hand the model the fifteen OLDEST memories as its
    # "do not repeat" context, which is the opposite of what it needs.
    from app.models.memory import load_memories
    existing = load_memories(character_name)
    existing_summary = "\n".join(
        f"- {e['content']}" for e in existing[:15]
    ) if existing else "(none yet)"

    from app.models.intents import build_open_intents_brief, complete_intent_as
    plans = build_open_intents_brief(character_name)
    open_plans_block = (
        "Open plans (id | title) — do not extract one of these again; "
        "if this thought finishes one, list its id in completed_ids:\n" + plans
    ) if plans else ""

    # Clean own message (remove meta-tags)
    clean_own = re.sub(r'\*\*I\s+feel\s+[^*]+\*\*', '', own_message, flags=re.IGNORECASE)
    clean_own = re.sub(r'\*\*I\s+am\s+at\s+[^*]+\*\*', '', clean_own, flags=re.IGNORECASE)
    clean_own = re.sub(r'\*\*I\s+do\s+[^*]+\*\*', '', clean_own, flags=re.IGNORECASE)
    clean_own = re.sub(r'\[INTENT:[^\]]+\]', '', clean_own)
    clean_own = clean_own.strip()

    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task

        shared = dict(
            speaker_b=character_name,
            text_b=clean_own[:1500],
            existing_summary=existing_summary,
            open_plans_block=open_plans_block,
            lang_instruction=_lang_instruction(character_name, "memory contents"))
        if monologue:
            from app.models.character import get_character_profile
            from app.core.thought_context import room_presence_names, absent_named_people
            profile = get_character_profile(character_name)
            location_id = profile.get("current_location") or ""
            room_id = profile.get("current_room") or ""
            presence = room_presence_names(character_name, location_id, room_id)
            shared.update(
                presence_known=presence is not None,
                present_names=", ".join(presence[0]) if presence is not None else "",
                absent_names=", ".join(absent_named_people(
                    character_name, location_id, room_id, texts=[clean_own])))
            sys_prompt, user_prompt = render_task("extraction_thought", **shared)
        else:
            sys_prompt, user_prompt = render_task(
                "extraction_memory", speaker_a=partner_name,
                text_a=partner_message, **shared)

        response = llm_call(
            task="extraction",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name=character_name)
        content = response.content.strip() if response.content else ""
        if not content:
            return []

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed = json.loads(json_match.group(0))
        else:
            parsed = json.loads(content)

        raw_memories = parsed.get("memories", [])
        if not isinstance(raw_memories, list):
            return []

        valid = []
        for item in raw_memories:
            if not isinstance(item, dict):
                continue
            mem_content = (item.get("content") or "").strip()
            mem_type = item.get("memory_type", "semantic")
            if not mem_content:
                continue
            if mem_type not in ("semantic", "commitment"):
                # Episodic memories come from daily chat-history consolidation,
                # so they are no longer extracted here.
                if mem_type == "episodic":
                    continue
                mem_type = "semantic"
            importance = item.get("importance", 3)
            if not isinstance(importance, int) or importance < 1:
                importance = 3
            importance = min(5, importance)
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [str(t).strip() for t in tags if t]

            entry = {
                "memory_type": mem_type,
                "content": mem_content,
                "importance": importance,
                "tags": tags,
            }
            # Prefer the model's named addressee, otherwise use the conversation
            # partner so a promise is attributed to an actual character.
            related = (item.get("related_character") or "").strip()
            if not related and not monologue:
                related = partner_name
            # Filter generic labels; never store them as addressees.
            if related.lower() in {"user", "player", "spieler", "the user",
                                    "assistant", "character"}:
                related = partner_name  # empty in a monologue: no addressee
            if related:
                entry["related_character"] = related
            # Due hint for commitments — a number of minutes from now.
            if mem_type == "commitment":
                entry["title"] = _plan_title(item.get("title"), mem_content)
                try:
                    minutes = int(item.get("delay_minutes") or 0)
                except (TypeError, ValueError):
                    minutes = 0
                if minutes > 0:
                    entry["delay_minutes"] = minutes
            valid.append(entry)

        # Complete plans named by their hex ids.
        completed_ids = parsed.get("completed_ids", [])
        if isinstance(completed_ids, list) and completed_ids:
            for intent_id in completed_ids:
                complete_intent_as(character_name, str(intent_id).strip())

        return valid

    except Exception as e:
        logger.error("Memory extraction error: %s", e)
        return []


def _plan_title(title: Any, content: str) -> str:
    """Use an explicit title, or at most 60 characters ending at a word boundary."""
    title = str(title or "").strip()
    if title:
        return title
    content = content.strip()
    if len(content) <= 60:
        return content
    boundary = re.match(r"^.{0,60}(?=\s|$)", content, flags=re.DOTALL)
    return boundary.group(0).rstrip() if boundary else content[:60]


def apply_extracted_memories(character_name: str,
    extracted: List[Dict[str, Any]],
    extraction_context: Optional[Dict[str, Any]] = None) -> int:
    """Store facts as memories and promises as capped own intents.

    The semantic dedup window uses SYSTEM timestamps. Extraction context
    supplies source/event provenance for memories.
    """
    from app.models.memory import add_memory, load_memories, _keyword_overlap

    ctx = extraction_context or {}
    event_id = ctx.get("event_id") or ""
    source = ctx.get("source") or ""

    # Recent-memory pool for the dedup check: everything younger than 14 days.
    recent_cutoff = utc_now() - timedelta(days=14)
    recent_contents: List[str] = []
    for e in load_memories(character_name):
        try:
            ts = parse_iso(e.get("timestamp", ""))
        except (ValueError, TypeError):
            continue
        if e.get("memory_type") == "semantic" and ts >= recent_cutoff:
            recent_contents.append(e.get("content", ""))

    count = 0
    for item in extracted:
        tags = item.get("tags", [])
        mem_type = item.get("memory_type", "semantic")
        try:
            delay_minutes = int(item.get("delay_minutes") or 0)
        except (TypeError, ValueError):
            delay_minutes = 0
        if delay_minutes < 0:
            delay_minutes = 0
        new_content = item.get("content", "")

        if mem_type == "commitment":
            from app.models.intents import create_own_intent
            from app.models.character import character_exists
            trigger = ({"kind": "at_time", "run_date": (
                game_time() + GameDuration.of(minutes=delay_minutes)).canonical()}
                if delay_minutes > 0 else {"kind": "standing"})
            related = (item.get("related_character") or "").strip()
            participants = {}
            if related and related != character_name:
                if related.lower() not in {"user", "player", "spieler", "the user",
                                           "assistant", "character"} and character_exists(related):
                    participants[related] = {
                        "role": f"{character_name} promised this to you", "progress": []}
                else:
                    logger.debug("Ignoring unknown plan addressee %r", related)
            created = create_own_intent(
                character_name, _plan_title(item.get("title"), new_content),
                description=new_content, trigger=trigger, priority=3,
                source="character", extra_participants=participants)
            if created:
                count += 1
            continue

        # Semantic facts alone use memory keyword deduplication.
        if mem_type == "semantic" and new_content and any(
                _keyword_overlap(c, new_content) > 0.5 for c in recent_contents):
            continue
        importance = item.get("importance", 3)

        # Provenance into the meta — for the later event cleanup and debugging.
        extra_meta: Dict[str, Any] = {}
        if source:
            extra_meta["source"] = source
        if event_id:
            extra_meta["event_id"] = event_id
        if delay_minutes:
            extra_meta["delay_minutes"] = delay_minutes
        result = add_memory(
            character_name=character_name,
            content=item["content"],
            memory_type=mem_type,
            importance=importance,
            tags=tags,
            related_character=item.get("related_character", ""),
            extra_meta=extra_meta or None)
        if result:
            count += 1
            if mem_type == "semantic":
                recent_contents.append(new_content)
    return count


# ---------------------------------------------------------------------------
# Trace cleanup for disposable characters
# ---------------------------------------------------------------------------

def cleanup_npc_traces(npc_name: str) -> Dict[str, int]:
    """Delete what OTHER characters remember ABOUT a disposable character.

    ``delete_character`` sweeps every table keyed by ``character_name``, i.e.
    the NPC's own rows. What it cannot reach are the rows that belong to
    someone else and merely talk about the NPC — those are what this removes:

    * ``memories`` rows whose ``meta.related_character`` is the NPC, and rows
      whose ``content`` names it as a whole word. Both are entries ABOUT the
      NPC, so they go with it.
    * ``summaries`` rows whose ``partner`` is the NPC — a per-partner summary
      has no meaning once the partner is gone.

    Deliberately NOT touched: daily/weekly/season summaries and diary entries
    that merely *mention* the name. Those are about the DAY, not about the NPC;
    dropping them would destroy unrelated history. The decision is deletion
    without substitution — no "a stranger" rewriting.

    Returns ``{"memories": n, "summaries": n}``.
    """
    from app.core.db import transaction

    removed = {"memories": 0, "summaries": 0}
    name = (npc_name or "").strip()
    if not name:
        return removed

    # Whole-word match: "Mara" must not hit "Maranta". Applied in Python so
    # the SQL stays a plain LIKE pre-filter on any SQLite build.
    word_re = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)

    try:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT id, character_name, content, meta FROM memories "
                "WHERE character_name <> ?", (name,)).fetchall()
            doomed = []
            for row in rows:
                related = ""
                try:
                    related = str((json.loads(row[3] or "{}") or {}).get(
                        "related_character") or "")
                except Exception:
                    related = ""
                if related.strip().lower() == name.lower():
                    doomed.append(row[0])
                elif word_re.search(row[2] or ""):
                    doomed.append(row[0])
            for mid in doomed:
                # memory_embeddings cascades on the FK (PRAGMA foreign_keys=ON)
                conn.execute("DELETE FROM memories WHERE id=?", (mid,))
            removed["memories"] = len(doomed)

            cur = conn.execute("DELETE FROM summaries WHERE partner=?", (name,))
            removed["summaries"] = int(cur.rowcount or 0)
    except Exception as e:
        logger.error("cleanup_npc_traces failed for %s: %s", name, e)
        return removed

    if removed["memories"] or removed["summaries"]:
        logger.info("NPC trace cleanup '%s': %d memories, %d partner summaries",
                    name, removed["memories"], removed["summaries"])
    return removed


# ---------------------------------------------------------------------------
# Consolidation (background worker)
# ---------------------------------------------------------------------------

def consolidate_memories(character_name: str) -> int:
    """Consolidate old memories: apply decay and merge duplicates.

    Called periodically in the background.
    Return the number of removed/archived entries.
    """
    from app.models.memory import (load_memories, save_memories, _compute_decay,
                                   memory_amount)

    entries = load_memories(character_name)
    if len(entries) < 30:
        return 0  # Too few entries to consolidate

    removed = 0
    # Configuration. Age thresholds are GLOBAL by design; the AMOUNT caps are
    # per NPC (character config → global memory.* → default), see
    # plan-memory-consolidation-npc-specific.md §4a.
    semantic_max = memory_amount(character_name, "memory_max_semantic",
                                 "memory.max_semantic", 50)
    episodic_max = memory_amount(character_name, "memory_max_episodic",
                                 "memory.max_episodic", 60)

    # 1. Compute decay and archive very weak entries
    active = []
    for entry in entries:
        decay = _compute_decay(entry)
        entry["decay_factor"] = round(decay, 3)
        if decay < 0.1 and entry.get("importance", 3) <= 2:
            removed += 1
            continue  # Archive (remove)
        active.append(entry)

    # 2. Detect duplicate content
    seen_content = set()
    deduped = []
    for entry in active:
        content_key = entry.get("content", "").strip().lower()
        if content_key in seen_content:
            removed += 1
            continue
        seen_content.add(content_key)
        deduped.append(entry)

    # 3. Amount-cap enforcement per memory type: backlog over cap → weakest
    #    out (score = importance × decay × (1 + access bonus)). The reactive
    #    cap check on add only sees new adds; this trues up old backlogs once
    #    per consolidation. Protected entries ('important' tag / importance
    #    ≥ 4) count toward the cap but are never auto-removed.
    def _score(e):
        imp = e.get("importance", 3)
        decay = e.get("decay_factor", 1.0)
        access = min(0.3, e.get("access_count", 0) * 0.05)
        return imp * decay * (1.0 + access)

    def _is_protected(e):
        return "important" in (e.get("tags") or []) or e.get("importance", 3) >= 4

    def _enforce_cap(pool_entries, mem_type, cap, label, exclude=None, protect=None):
        nonlocal deduped, removed
        pool = [e for e in pool_entries if e.get("memory_type") == mem_type
                and not (exclude and exclude(e))]
        excess = len(pool) - cap
        if excess <= 0:
            return
        removable = sorted((e for e in pool if not (protect and protect(e))),
                           key=_score)
        kill_ids = {e.get("id") for e in removable[:excess]}
        if not kill_ids:
            return
        deduped = [e for e in deduped if e.get("id") not in kill_ids]
        removed += len(kill_ids)
        logger.info("%s-Cap [%s]: %d Eintraege ueber Cap (%d) entfernt",
                    label, character_name, len(kill_ids), cap)

    # Semantic facts (relationship-tagged entries are structural — excluded,
    # no protection: identical to the previous behavior).
    _enforce_cap(deduped, "semantic", semantic_max, "Semantic",
                 exclude=lambda e: "relationship" in (e.get("tags") or []))
    # Episodics awaiting the daily rollup — protects prompt + rollup volume.
    _enforce_cap(deduped, "episodic", episodic_max, "Episodic",
                 protect=_is_protected)

    if removed > 0:
        save_memories(character_name, deduped)
        logger.info("Konsolidiert %s: %d Memories entfernt", character_name, removed)

    return removed


def handle_memory_consolidation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Task-queue handler for the character memory consolidation ladder.

    Pipeline:
      Phase 1: Cleanup (duplicates, decay)
      Phase 2: Daily consolidation (episodes → day summary, delete originals)
      Phase 3: Weekly consolidation (day summaries → week summary)
      Phase 4: Season consolidation (week summaries → season summary)
      Phase 5: Update daily summaries and backfill
    """
    character_name = payload.get("character_name", "")
    if not character_name:
        return {"error": "character_name missing"}

    total = 0

    # Phase 1: Cleanup
    try:
        removed = consolidate_memories(character_name)
        total += removed
    except Exception as e:
        logger.error("Consolidation Phase 1 error %s: %s", character_name, e)

    # Phase 2: Daily consolidation (episodes → day summary)
    try:
        removed_daily = _consolidate_episodics_to_daily(character_name)
        total += removed_daily
    except Exception as e:
        logger.error("Consolidation Phase 2 error %s: %s", character_name, e)

    # Phase 3: Weekly consolidation
    try:
        removed_weekly = _consolidate_daily_to_weekly(character_name)
        total += removed_weekly
    except Exception as e:
        logger.error("Consolidation Phase 3 error %s: %s", character_name, e)

    # Phase 4: Season consolidation
    try:
        removed_monthly = _consolidate_weekly_to_monthly(character_name)
        total += removed_monthly
    except Exception as e:
        logger.error("Consolidation Phase 4 error %s: %s", character_name, e)

    # Phase 5: Update daily summaries and backfill (via Router/Task=consolidation)
    try:
        from app.utils.history_manager import _update_daily_summary, backfill_missing_daily_summaries
        _update_daily_summary(character_name)
        backfill_missing_daily_summaries(character_name)
    except Exception as e:
        logger.error("Consolidation Phase 5 (daily summaries) error %s: %s", character_name, e)

    return {"success": True, "character": character_name, "removed": total}


def submit_consolidation_for_all():
    """Submits a consolidation task for every character to the task queue."""
    from app.models.character import list_available_characters
    from app.core.task_queue import get_task_queue

    tq = get_task_queue()
    count = 0
    for char_name in list_available_characters():
        tq.submit(
            task_type="memory_consolidation",
            payload={"character_name": char_name},
            priority=30,
            agent_name=char_name,
            deduplicate=True)
        count += 1

    if count:
        logger.info("Memory consolidation: %d tasks submitted", count)


def register_consolidation_handler():
    """Registers the consolidation handler in the task queue."""
    from app.core.task_queue import get_task_queue
    tq = get_task_queue()
    tq.register_handler("memory_consolidation", handle_memory_consolidation)
    logger.info("Memory consolidation handler registered")


# Legacy wrapper (for existing callers)
def run_consolidation_for_all_users():
    """Submits the consolidation tasks to the queue (non-blocking)."""
    submit_consolidation_for_all()


def _lang_instruction(character_name: str, noun: str = "summary") -> str:
    """Stored text in the character's language — the LLM defaults to English
    otherwise. Empty string for English characters (and when the profile is
    unreadable), so the instruction is simply absent instead of wrong.

    ``noun`` names what is being written, so the sentence fits the task
    ("summary" for the rollups, "memory contents" for the extraction).
    """
    try:
        from app.models.character import get_character_profile, LANGUAGE_MAP
        code = (get_character_profile(character_name) or {}).get("language", "")
        if code and code != "en":
            return f"\nWrite the {noun} in {LANGUAGE_MAP.get(code, code)}."
    except Exception:
        pass
    return ""


def _llm_summarize(system_prompt: str, user_prompt: str, character_name: str) -> str:
    """Calls the LLM for a summary. Returns an empty string on failure."""
    try:
        from app.core.llm_router import llm_call
        response = llm_call(
            task="consolidation",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            agent_name=character_name)
        result = (response.content or "").strip() if response else ""
        # Clean up LLM artifacts
        result = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', result).strip()
        return result if len(result) >= 20 else ""
    except Exception as e:
        logger.error("LLM-Summarize Fehler fuer %s: %s", character_name, e)
        return ""


# ---------------------------------------------------------------------------
# Phase 2: Daily consolidation (episodes → day summary)
# ---------------------------------------------------------------------------

def _consolidate_episodics_to_daily(character_name: str) -> int:
    """Collapses episodic memories older than SHORT_TERM_DAYS into day summaries.

    Per GAME day: episodic memories + the existing day summary → a new day
    summary; the episodic originals are then deleted. The day comes from the
    memory's own canonical ``game_ts`` (:func:`memory_day_key`), and the age
    threshold is counted in GAME days as well, so the whole ladder moves at
    the speed of the world.
    """
    from app.core.day_consolidation import parse_day_key
    from app.models.memory import load_memories, save_memories
    from app.utils.history_manager import (get_memory_thresholds,
                                            load_daily_summaries_combined,
                                            save_daily_summary)

    thresholds = get_memory_thresholds()
    cutoff = game_time().minus_clamped(
        GameDuration.of(days=thresholds["short_term_days"])).day_key()

    entries = load_memories(character_name)

    # Episodic memories older than the short term, grouped by game day
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        if e.get("memory_type") != "episodic":
            continue
        day_key = memory_day_key(e)
        if not day_key or day_key >= cutoff:
            continue  # unusable stamp, or still inside the short term
        by_day.setdefault(day_key, []).append(e)

    if not by_day:
        return 0

    # Episodic → day consolidation writes into the partner-empty slot ('') of
    # the summaries table. Existing texts (all partners combined) are read as
    # context so the episodics do not contradict them.
    existing_daily = load_daily_summaries_combined(character_name)
    removed_total = 0
    ids_to_remove = set()

    # At most 3 days per run (LLM budget)
    days_processed = 0
    for day_key, day_entries in sorted(by_day.items()):
        if days_processed >= 3:
            break

        contents = "\n".join(f"- {e.get('content', '')}" for e in day_entries if e.get('content', '').strip())
        if not contents:
            # Every episodic of that day is empty → just delete
            for e in day_entries:
                ids_to_remove.add(e.get("id"))
            removed_total += len(day_entries)
            continue
        existing = existing_daily.get(day_key, "")

        lang_instruction = _lang_instruction(character_name)

        # Inner life of that day (plan-thought-journal.md) — private to this
        # character, empty when the journal has nothing for the date.
        try:
            from app.core.day_consolidation import thoughts_of_date
            thoughts_of_day = thoughts_of_date(character_name, day_key)
        except Exception:
            thoughts_of_day = ""

        day_start = parse_day_key(day_key)
        game_date = day_start.date_label() if day_start else day_key

        from app.core.prompt_templates import render_task
        sys_prompt, user_prompt = render_task(
            "consolidation_daily",
            game_date=game_date,
            character_name=character_name,
            existing=existing,
            lang_instruction=lang_instruction,
            contents=contents,
            thoughts_of_day=thoughts_of_day)

        summary = _llm_summarize(sys_prompt, user_prompt, character_name)
        if summary:
            save_daily_summary(character_name, day_key, summary)
            for e in day_entries:
                ids_to_remove.add(e.get("id"))
            removed_total += len(day_entries)
            days_processed += 1
            logger.info("Day consolidation %s [%s]: %d episodics → summary",
                        character_name, day_key, len(day_entries))

    # Delete the episodic originals
    if ids_to_remove:
        new_entries = [e for e in entries if e.get("id") not in ids_to_remove]
        save_memories(character_name, new_entries)

    return removed_total


# ---------------------------------------------------------------------------
# Phase 3: Weekly consolidation (day summaries → week summary)
# ---------------------------------------------------------------------------

def load_weekly_summaries(character_name: str) -> Dict[str, str]:
    """Weekly summaries from the ``summaries`` table (kind='weekly',
    partner=''). Returns {week_key: summary_text}, key = 'Y0002-W016'."""
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT date_key, content FROM summaries "
            "WHERE character_name=? AND kind='weekly' AND partner=''",
            (character_name,)).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        logger.error("load_weekly_summaries failed for %s: %s", character_name, e)
        return {}


def save_weekly_summary(character_name: str, week_key: str, summary: str):
    _save_rollup_summary(character_name, "weekly", week_key, summary)


def _save_rollup_summary(character_name: str, kind: str, date_key: str,
                         content: str) -> None:
    from app.core.db import transaction
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
                "VALUES (?, ?, ?, '', ?) "
                "ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET "
                "content=excluded.content",
                (character_name, kind, date_key, content))
    except Exception as e:
        logger.error("save %s summary failed for %s/%s: %s",
                     kind, character_name, date_key, e)


def delete_weekly_summaries(character_name: str, week_keys) -> None:
    """Removes weekly rows that were rolled up into a monthly summary."""
    keys = [k for k in (week_keys or []) if k]
    if not keys:
        return
    from app.core.db import transaction
    try:
        with transaction() as conn:
            ph = ",".join("?" for _ in keys)
            conn.execute(
                f"DELETE FROM summaries WHERE character_name=? AND kind='weekly' "
                f"AND partner='' AND date_key IN ({ph})",
                (character_name, *keys))
    except Exception as e:
        logger.error("delete weekly summaries failed for %s: %s", character_name, e)


def _consolidate_daily_to_weekly(character_name: str) -> int:
    """Collapses day summaries older than MID_TERM_DAYS into week summaries.

    A "week" is a block of game days (``_week_key``); the age threshold counts
    GAME days.
    """
    from app.core.day_consolidation import parse_day_key
    from app.utils.history_manager import (get_memory_thresholds,
                                            load_daily_summaries_combined)

    thresholds = get_memory_thresholds()
    cutoff = game_time().minus_clamped(
        GameDuration.of(days=thresholds["mid_term_days"]))

    # The weekly consolidation condenses across all partners — one combined
    # text per day (all partner slots together).
    daily = load_daily_summaries_combined(character_name)
    if not daily:
        return 0

    # Group day summaries by game week (skipping empty ones)
    by_week: Dict[str, Dict[str, str]] = {}  # {week_key: {day_key: summary}}
    empty_days = []  # empty entries, to be cleaned up
    for day_key, summary in daily.items():
        day = parse_day_key(day_key)
        if day is None:
            logger.warning("daily summary of %s has a non-game day key %r — skipped",
                           character_name, day_key)
            continue
        if day >= cutoff:
            continue  # too fresh
        if not summary or not summary.strip():
            empty_days.append(day_key)
            continue
        by_week.setdefault(_week_key(day), {})[day_key] = summary

    if not by_week and not empty_days:
        return 0

    existing_weekly = load_weekly_summaries(character_name)
    removed_total = 0
    days_to_remove = list(empty_days)  # empty entries always go

    # At most 2 weeks per run
    weeks_processed = 0
    for week_key, week_days in sorted(by_week.items()):
        if weeks_processed >= 2:
            break
        if week_key in existing_weekly:
            # Already consolidated — drop the day summaries
            days_to_remove.extend(week_days.keys())
            removed_total += len(week_days)
            continue

        entries_text = "\n".join(
            f"- {d}: {s}" for d, s in sorted(week_days.items()) if s and s.strip()
        )
        if not entries_text:
            # Every entry of that week is empty → just delete
            days_to_remove.extend(week_days.keys())
            removed_total += len(week_days)
            continue

        from app.core.prompt_templates import render_task
        sys_prompt, user_prompt = render_task(
            "consolidation_weekly",
            week_key=week_key,
            character_name=character_name,
            lang_instruction=_lang_instruction(character_name),
            entries_text=entries_text)

        summary = _llm_summarize(sys_prompt, user_prompt, character_name)
        if summary:
            save_weekly_summary(character_name, week_key, summary)
            days_to_remove.extend(week_days.keys())
            removed_total += len(week_days)
            weeks_processed += 1
            logger.info("Week consolidation %s [%s]: %d days → summary",
                        character_name, week_key, len(week_days))

    if days_to_remove:
        from app.utils.history_manager import delete_daily_summaries
        delete_daily_summaries(character_name, days_to_remove)

    return removed_total


# ---------------------------------------------------------------------------
# Phase 4: Season consolidation (week summaries → season summary)
# ---------------------------------------------------------------------------

def load_monthly_summaries(character_name: str) -> Dict[str, str]:
    """Season summaries from the ``summaries`` table (kind='monthly',
    partner=''). Returns {season_key: summary_text}, key = 'Y0002-S01'.

    The DB ``kind`` stays 'monthly' — it names the TIER (the coarsest one),
    and the world calendar's coarsest bucket below a year is the season.
    """
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT date_key, content FROM summaries "
            "WHERE character_name=? AND kind='monthly' AND partner=''",
            (character_name,)).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        logger.error("load_monthly_summaries failed for %s: %s", character_name, e)
        return {}


def save_monthly_summary(character_name: str, season_key: str, summary: str):
    _save_rollup_summary(character_name, "monthly", season_key, summary)


def _consolidate_weekly_to_monthly(character_name: str) -> int:
    """Collapses week summaries older than LONG_TERM_DAYS into SEASON summaries.

    The world calendar has no months, so the coarsest tier is the season the
    week started in; the age threshold counts GAME days.
    """
    from app.utils.history_manager import get_memory_thresholds

    thresholds = get_memory_thresholds()
    cutoff = game_time().minus_clamped(
        GameDuration.of(days=thresholds["long_term_days"]))

    weekly = load_weekly_summaries(character_name)
    if not weekly:
        return 0

    # Group weeks by season
    by_season: Dict[str, Dict[str, str]] = {}  # {season_key: {week_key: summary}}
    for week_key, summary in weekly.items():
        start = _week_start(week_key)
        if start is None:
            logger.warning("weekly summary of %s has a non-game week key %r — skipped",
                           character_name, week_key)
            continue
        if start >= cutoff:
            continue
        by_season.setdefault(_season_key(start), {})[week_key] = summary

    if not by_season:
        return 0

    existing_seasons = load_monthly_summaries(character_name)
    removed_total = 0
    weeks_to_remove = []

    # At most 1 season per run
    for season_key, season_weeks in sorted(by_season.items()):
        if season_key in existing_seasons:
            weeks_to_remove.extend(season_weeks.keys())
            removed_total += len(season_weeks)
            continue

        entries_text = "\n".join(
            f"- {w}: {s}" for w, s in sorted(season_weeks.items())
        )

        from app.core.prompt_templates import render_task
        sys_prompt, user_prompt = render_task(
            "consolidation_monthly",
            season_key=season_key,
            season_label=season_label(season_key),
            character_name=character_name,
            lang_instruction=_lang_instruction(character_name),
            entries_text=entries_text)

        summary = _llm_summarize(sys_prompt, user_prompt, character_name)
        if summary:
            save_monthly_summary(character_name, season_key, summary)
            weeks_to_remove.extend(season_weeks.keys())
            removed_total += len(season_weeks)
            logger.info("Season consolidation %s [%s]: %d weeks → summary",
                        character_name, season_key, len(season_weeks))
        break  # at most 1 season per run

    # Delete the week entries (folded into a season)
    if weeks_to_remove:
        delete_weekly_summaries(character_name, weeks_to_remove)

    return removed_total
