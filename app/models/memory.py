"""Character memory system — long-term memory per character.

Replaces the old knowledge system with context-based retrieval, natural decay
and memory types (episodic, semantic, commitment).

Storage: world.db — tables ``memories``, ``mood_history``.

**Two stamps per memory, and they are not interchangeable** (plan-game-calendar
.md §1): ``ts`` is SYSTEM time (ordering, decay, access bookkeeping), while
``game_ts`` is the canonical GAME time the memory was formed at. Everything the
character reads about WHEN something happened comes off ``game_ts`` — a real
date has no business inside the world. A row without a game stamp gets no time
prefix at all rather than falling back to the system stamp.
"""
import json
import math
import os
import re
import uuid

from app.core.game_time import GameTime
from app.core.timeutils import game_time, parse_iso, utc_now, utc_now_iso
from typing import Any, Dict, List, Optional

from app.core.i18n import t
from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("memory")


# ---------------------------------------------------------------------------
# Per-NPC amount caps (plan-memory-consolidation-npc-specific.md §4a)
# ---------------------------------------------------------------------------

def memory_amount(character_name: str, config_key: str,
                  global_key: str, default: int) -> int:
    """Amount-cap resolution: per-character config (>0) → global ``memory.*``
    → built-in default. The ONE read path for all memory amount caps
    (semantic/commitment/episodic counts, prompt top-K). Cadences and age
    thresholds stay global by design — only AMOUNTS are per NPC."""
    try:
        from app.models.character import get_character_config
        raw = (get_character_config(character_name) or {}).get(config_key)
        if raw not in (None, ""):
            v = int(raw)
            if v > 0:
                return v
    except Exception:
        pass
    try:
        from app.core import config as _cfg
        raw = _cfg.get(global_key)
        if raw not in (None, ""):
            v = int(raw)
            if v > 0:
                return v
    except Exception:
        pass
    return default


# ---------------------------------------------------------------------------
# MemoryEntry helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return f"mem_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return utc_now_iso()


def _row_to_entry(row) -> Dict[str, Any]:
    """Converts a DB row into the entry dict format."""
    d = dict(row)
    # Restore the fields that live in the meta JSON column
    meta = {}
    try:
        meta = json.loads(d.get("meta") or "{}")
    except Exception:
        pass
    entry = {
        "id": d.get("id", ""),
        "timestamp": d.get("ts", ""),
        "game_ts": d.get("game_ts", "") or "",
        "memory_type": d.get("tier", "semantic"),
        "content": d.get("content", ""),
        "tags": [],
        "source_ids": [],
        **meta,  # all meta fields (context, importance, access_count, ...)
    }
    try:
        entry["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        pass
    try:
        entry["source_ids"] = json.loads(d.get("source_ids") or "[]")
    except Exception:
        pass
    # Row-ID als Fallback-ID
    if not entry.get("id"):
        entry["id"] = f"mem_{d.get('id', '')}"
    return entry


# Everything an entry may carry into the `meta` JSON column. The list is a
# whitelist on purpose — a memory row must not become a dumping ground — but it
# used to be written out twice, and a key that was not in it vanished WITHOUT a
# trace. Two features died that way: the due hint of a commitment (handed in by
# apply_extracted_memories, dropped here → 0 rows carrying one in any world) and
# `summary`/`summary_stale` (the pairwise relationship summary, which could
# therefore never be stored and stayed permanently "stale").
META_KEYS = ("context", "importance", "access_count", "last_accessed",
             "decay_factor", "related_character", "delay_minutes",
             "summary", "summary_stale")

# Entry fields that are stored in their own columns, not in `meta` — knowing
# them is what lets the builder below tell "belongs elsewhere" from "typo".
_ROW_KEYS = ("id", "memory_type", "tier", "content", "timestamp", "ts",
             "game_ts", "tags", "source_ids")


def _build_meta(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Picks the meta fields out of an entry and complains about the rest.

    A silent drop is the worst outcome: the caller sees a successful save and
    the field is simply gone. Unknown keys are still not stored — but they now
    say so.
    """
    meta = {k: entry[k] for k in META_KEYS if k in entry}
    unknown = [k for k in entry
               if k not in META_KEYS and k not in _ROW_KEYS]
    if unknown:
        logger.warning(
            "memory entry carries unknown field(s) %s — not stored. Add them to "
            "META_KEYS in app/models/memory.py if they belong in meta.",
            ", ".join(sorted(unknown)))
    return meta


def _entry_to_row(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Converts an entry dict into DB fields."""
    meta = _build_meta(entry)
    return {
        "tier": entry.get("memory_type", "semantic"),
        "ts": entry.get("timestamp", _now_iso()),
        "game_ts": entry.get("game_ts", "") or "",
        "content": entry.get("content", ""),
        "source_ids": json.dumps(entry.get("source_ids", []), ensure_ascii=False),
        "tags": json.dumps(entry.get("tags", []), ensure_ascii=False),
        "meta": json.dumps(meta, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------

def load_memories(character_name: str) -> List[Dict[str, Any]]:
    """Laedt alle Memory-Eintraege eines Characters aus der DB."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM memories WHERE character_name=? ORDER BY ts DESC",
            (character_name,),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]
    except Exception as e:
        logger.error("load_memories Fehler fuer %s: %s", character_name, e)
        return []


def save_memories(character_name: str, entries: List[Dict[str, Any]]):
    """Ersetzt alle Memories eines Characters in der DB.

    Wird aufgerufen wenn eine oder mehrere Memories geaendert wurden
    (access_count, decay_factor, entfernte Eintraege etc.).
    """
    try:
        # Bestimme welche Entries neu/geaendert sind via ID-Vergleich
        conn = get_connection()
        existing_ids = {
            str(r[0])
            for r in conn.execute(
                "SELECT id FROM memories WHERE character_name=?", (character_name,)
            ).fetchall()
        }
        with transaction() as conn:
            entry_ids_seen = set()
            for entry in entries:
                row = _entry_to_row(entry)
                raw_id = entry.get("id", "")
                # Numeric row-id aus "mem_N" oder direkte int-ID
                row_id = None
                if raw_id and str(raw_id).isdigit():
                    row_id = int(raw_id)
                elif raw_id and raw_id.startswith("mem_") and raw_id[4:].isdigit():
                    row_id = int(raw_id[4:])

                if row_id and str(row_id) in existing_ids:
                    # Update of an existing row
                    conn.execute("""
                        UPDATE memories
                        SET tier=?, ts=?, game_ts=?, content=?, source_ids=?,
                            tags=?, meta=?
                        WHERE id=? AND character_name=?
                    """, (
                        row["tier"], row["ts"], row["game_ts"], row["content"],
                        row["source_ids"], row["tags"], row["meta"],
                        row_id, character_name,
                    ))
                    entry_ids_seen.add(str(row_id))
                elif not raw_id or raw_id.startswith("mem_") and not (raw_id[4:].isdigit()):
                    # New entry (hex id from the old system)
                    cur = conn.execute("""
                        INSERT INTO memories
                        (character_name, tier, ts, game_ts, content, source_ids, tags, meta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (character_name, row["tier"], row["ts"], row["game_ts"],
                          row["content"], row["source_ids"], row["tags"], row["meta"]))
                    entry_ids_seen.add(str(cur.lastrowid))
                else:
                    # Unknown or new entry
                    cur = conn.execute("""
                        INSERT INTO memories
                        (character_name, tier, ts, game_ts, content, source_ids, tags, meta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (character_name, row["tier"], row["ts"], row["game_ts"],
                          row["content"], row["source_ids"], row["tags"], row["meta"]))
                    entry_ids_seen.add(str(cur.lastrowid))

            # Remove deleted entries
            to_delete = existing_ids - entry_ids_seen
            for del_id in to_delete:
                conn.execute(
                    "DELETE FROM memories WHERE id=? AND character_name=?",
                    (del_id, character_name)
                )
    except Exception as e:
        logger.error("save_memories Fehler fuer %s: %s", character_name, e)


def add_memory(character_name: str,
    content: str,
    memory_type: str = "semantic",
    importance: int = 3,
    tags: Optional[List[str]] = None,
    context: str = "",
    related_character: str = "",
    timestamp: str = "",
    game_ts: str = "",
    extra_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Adds a new memory.

    Cap enforcement (MEMORY_MAX_SEMANTIC) happens exclusively in the background
    consolidation job (memory_service._cleanup_phase) — never synchronously on
    write, so callers (chat, room entry, ...) never block.

    ``timestamp`` is the SYSTEM stamp, ``game_ts`` the canonical GAME stamp;
    both default to "now" on their own clock. A caller that back-dates one
    should back-date the other too — they describe the same instant.
    """
    content = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', content).strip()
    if not content:
        return {}

    entry = {
        "id": _new_id(),
        "timestamp": timestamp or _now_iso(),
        "game_ts": game_ts or game_time().canonical(),
        "memory_type": memory_type,
        "content": content,
        "context": context,
        "importance": importance,
        "access_count": 0,
        "last_accessed": "",
        "decay_factor": 1.0,
        "tags": tags or [],
        "related_character": related_character,
    }
    row_id = 0
    try:
        meta = _build_meta(entry)
        if extra_meta:
            meta.update(extra_meta)
        with transaction() as conn:
            cur = conn.execute("""
                INSERT INTO memories
                (character_name, tier, ts, game_ts, content, source_ids, tags, meta)
                VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
            """, (
                character_name,
                memory_type,
                entry["timestamp"],
                entry["game_ts"],
                content,
                json.dumps(tags or [], ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
            ))
            row_id = int(cur.lastrowid or 0)
    except Exception as e:
        logger.error("add_memory DB error for %s: %s", character_name, e)

    # Keep the situational-memory vector cache warm. Fire-and-forget: the
    # first internal embedding loads an ONNX model, and add_memory runs inside
    # chat, thought and skill turns — none of them may wait for it. Only the
    # types the situational block considers are worth a vector.
    if row_id and memory_type in ("semantic", "commitment"):
        try:
            from app.core.memory_situational import schedule_embedding
            schedule_embedding(row_id, content)
        except Exception as e:
            logger.debug("scheduling memory embedding failed: %s", e)
    logger.debug("+1 memory [%s] for %s: %s", memory_type, character_name, content[:80])
    return entry


def delete_memory(character_name: str, entry_id: str) -> bool:
    """Loescht eine einzelne Memory."""
    try:
        # entry_id kann hex-String (mem_xxx) oder numeric sein
        conn = get_connection()
        # Versuche zuerst als numerische Row-ID
        if str(entry_id).isdigit():
            cur = conn.execute(
                "DELETE FROM memories WHERE id=? AND character_name=?",
                (int(entry_id), character_name),
            )
        elif entry_id.startswith("mem_") and entry_id[4:].isdigit():
            cur = conn.execute(
                "DELETE FROM memories WHERE id=? AND character_name=?",
                (int(entry_id[4:]), character_name),
            )
        else:
            # Hex-ID: suche in meta oder content (Legacy-Fallback)
            rows = conn.execute(
                "SELECT id FROM memories WHERE character_name=? AND meta LIKE ?",
                (character_name, f'%"{entry_id}"%'),
            ).fetchall()
            if not rows:
                return False
            cur = conn.execute(
                "DELETE FROM memories WHERE id=? AND character_name=?",
                (rows[0][0], character_name),
            )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_memory Fehler fuer %s id=%s: %s", character_name, entry_id, e)
        return False


def clear_memories(character_name: str) -> int:
    """Loescht alle Memories. Gibt Anzahl zurueck."""
    try:
        conn = get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE character_name=?", (character_name,)
        ).fetchone()[0]
        if count > 0:
            conn.execute(
                "DELETE FROM memories WHERE character_name=?", (character_name,)
            )
            conn.commit()
        return count
    except Exception as e:
        logger.error("clear_memories Fehler fuer %s: %s", character_name, e)
        return 0


def upsert_relationship_memory(character_name: str,
    related_character: str,
    new_fact: str,
    max_facts: int = 5,
    replace_prefix: str = "") -> Dict[str, Any]:
    """Aktualisiert den Beziehungs-Eintrag zu einem anderen Character.

    Aequivalent zu knowledge.upsert_character_relationship(), aber in memories.json.
    Pro related_character gibt es genau EINEN Eintrag (memory_type="semantic", tag="relationship").
    """
    new_fact = re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', new_fact).strip()
    if not new_fact:
        return {}

    entries = load_memories(character_name)

    # Bestehenden Relationship-Eintrag suchen
    existing = None
    for e in entries:
        if (
            "relationship" in e.get("tags", [])
            and e.get("related_character") == related_character
        ):
            existing = e
            break

    if existing:
        facts = [f.strip() for f in existing.get("content", "").split("\n") if f.strip()]
        if replace_prefix:
            facts = [f for f in facts if not f.startswith(replace_prefix)]
        if new_fact not in facts:
            facts.append(new_fact)
        if len(facts) > max_facts:
            facts = facts[-max_facts:]
        existing["content"] = "\n".join(facts)
        existing["timestamp"] = _now_iso()
        existing["game_ts"] = game_time().canonical()
        save_memories(character_name, entries)
        return existing
    else:
        return add_memory(
            character_name=character_name,
            content=new_fact,
            memory_type="semantic",
            importance=2,
            tags=["relationship"],
            related_character=related_character)


def delete_memories_by_source(character_name: str, tag: str, context: str = ""
) -> int:
    """Loescht Memories mit passendem Tag (und optional context)."""
    try:
        conn = get_connection()
        if context:
            # context ist in meta gespeichert — lade und filtere
            rows = conn.execute(
                "SELECT id, tags, meta FROM memories WHERE character_name=?",
                (character_name,),
            ).fetchall()
            to_del = []
            for r in rows:
                try:
                    tags_list = json.loads(r[1] or "[]")
                    meta_d = json.loads(r[2] or "{}")
                    if tag in tags_list and meta_d.get("context") == context:
                        to_del.append(r[0])
                except Exception:
                    pass
            if to_del:
                conn.execute(
                    f"DELETE FROM memories WHERE id IN ({','.join('?'*len(to_del))})",
                    to_del,
                )
                conn.commit()
            removed = len(to_del)
        else:
            # Tag-Match via JSON — SQLite json_each
            rows = conn.execute(
                "SELECT id, tags FROM memories WHERE character_name=?",
                (character_name,),
            ).fetchall()
            to_del = []
            for r in rows:
                try:
                    if tag in json.loads(r[1] or "[]"):
                        to_del.append(r[0])
                except Exception:
                    pass
            if to_del:
                conn.execute(
                    f"DELETE FROM memories WHERE id IN ({','.join('?'*len(to_del))})",
                    to_del,
                )
                conn.commit()
            removed = len(to_del)
        if removed > 0:
            logger.info("%d memories (tag=%s) geloescht fuer %s", removed, tag, character_name)
        return removed
    except Exception as e:
        logger.error("delete_memories_by_source Fehler fuer %s: %s", character_name, e)
        return 0


def get_memories_by_tag(character_name: str,
    tag: str,
    related_character: str = "",
    limit: int = 0) -> List[Dict[str, Any]]:
    """Gibt Memories zurueck die einen bestimmten Tag haben."""
    entries = load_memories(character_name)
    filtered = [e for e in entries if tag in e.get("tags", [])]
    if related_character:
        meta_key = "related_character"
        filtered = [e for e in filtered if e.get(meta_key) == related_character]
    if limit:
        filtered = filtered[-limit:]
    return filtered


# ---------------------------------------------------------------------------
# Scoring & Retrieval
# ---------------------------------------------------------------------------

def _recency_boost(age_days: float) -> float:
    """Gibt einen Multiplikator fuer sehr aktuelle Memories zurueck.

    Aktuelle Daten (< 2 Tage) bekommen einen deutlichen Boost,
    damit sie gegenueber aelteren Eintraegen bevorzugt werden.

    Kurve:
      0-1   Tage  ->  2.0  (doppelt gewichtet)
      1-2   Tage  ->  1.5-2.0  (linear abfallend)
      2-3   Tage  ->  1.0-1.5  (linear abfallend)
      3+    Tage  ->  1.0  (kein Boost)
    """
    if age_days <= 1.0:
        return 2.0
    elif age_days <= 2.0:
        # Linear von 2.0 auf 1.5
        return 2.0 - 0.5 * (age_days - 1.0)
    elif age_days <= 3.0:
        # Linear von 1.5 auf 1.0
        return 1.5 - 0.5 * (age_days - 2.0)
    else:
        return 1.0


def _compute_decay(entry: Dict[str, Any]) -> float:
    """Berechnet aktuellen Decay basierend auf Alter und Access-Count."""
    try:
        ts = parse_iso(entry.get("timestamp", ""))
    except (ValueError, TypeError):
        return 0.5
    age_days = max(0, (utc_now() - ts).total_seconds() / 86400)
    # Base decay: halbes Leben nach 30 Tagen
    base_decay = math.exp(-0.023 * age_days)
    # Access-Bonus: haeufig abgerufene Memories zerfallen langsamer
    access_bonus = min(0.3, entry.get("access_count", 0) * 0.05)
    return min(1.0, max(0.05, base_decay + access_bonus))


def _keyword_overlap(text: str, query: str) -> float:
    """Einfacher Keyword-Overlap-Score zwischen Text und Query."""
    if not text or not query:
        return 0.0
    text_words = set(text.lower().split())
    query_words = set(query.lower().split())
    # Stoppwoerter ignorieren
    stop = {"ich", "du", "er", "sie", "es", "wir", "ihr", "und", "oder", "der",
            "die", "das", "ein", "eine", "ist", "hat", "war", "wird", "the",
            "a", "an", "is", "was", "are", "i", "you", "he", "she", "it",
            "we", "they", "and", "or", "in", "on", "at", "to", "for", "of",
            "with", "nicht", "nicht", "aber", "auch", "dann", "wenn", "so",
            "ja", "nein", "mein", "dein", "sein", "ihr", "have", "had",
            "been", "be", "do", "did", "will", "would", "can", "could",
            "that", "this", "what", "how", "my", "your", "his", "her"}
    text_words -= stop
    query_words -= stop
    if not query_words:
        return 0.0
    overlap = text_words & query_words
    return len(overlap) / len(query_words)


def retrieve_relevant_memories(character_name: str,
    current_message: str = "",
    max_results: int = 0) -> List[Dict[str, Any]]:
    """Ruft die relevantesten Memories ab, gescort nach Kontext.

    Score = importance * decay * (1 + keyword_relevance + type_bonus)
    """
    if max_results <= 0:
        # Per-NPC prompt budget (empty = global memory.max_prompt_entries).
        max_results = memory_amount(character_name, "memory_max_prompt_entries",
                                    "memory.max_prompt_entries", 20)

    entries = load_memories(character_name)
    if not entries:
        return []

    scored = []
    for entry in entries:
        decay = _compute_decay(entry)
        importance = entry.get("importance", 3)

        # Keyword-Relevanz
        search_text = entry.get("content", "") + " " + " ".join(entry.get("tags", []))
        relevance = _keyword_overlap(search_text, current_message) if current_message else 0.0

        # Typ-Bonus: nur OFFENE Commitments bekommen Bonus
        type_bonus = 0.0
        if entry.get("memory_type") == "commitment":
            if "completed" not in entry.get("tags", []):
                type_bonus = 0.3
            # Completed commitments: kein Bonus, normales Decay
        elif entry.get("memory_type") == "episodic":
            type_bonus = 0.1

        # Recency-Boost: aktuelle Daten (< 2 Tage) deutlich bevorzugen
        try:
            ts = parse_iso(entry.get("timestamp", ""))
            age_days = max(0, (utc_now() - ts).total_seconds() / 86400)
        except (ValueError, TypeError):
            age_days = 30.0  # Unbekanntes Alter = kein Boost
        recency = _recency_boost(age_days)

        score = importance * decay * recency * (1.0 + relevance * 2.0 + type_bonus)
        scored.append((score, entry, decay))

    # Sortieren nach Score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Top-N zurueckgeben und Access-Count aktualisieren
    result = []
    changed = False
    for score, entry, decay in scored[:max_results]:
        entry["access_count"] = entry.get("access_count", 0) + 1
        entry["last_accessed"] = _now_iso()
        entry["decay_factor"] = round(decay, 3)
        result.append(entry)
        changed = True

    if changed:
        save_memories(character_name, entries)

    return result


# ---------------------------------------------------------------------------
# Prompt-Section Builder (ersetzt build_knowledge_prompt_section)
# ---------------------------------------------------------------------------

# Recency thresholds in GAME days — the difference of two ``day_index``
# values, so "1" means "yesterday or later", not "within 24 h".
_MARK_CURRENT_DAYS = 1
_MARK_RECENT_DAYS = 2
_RELATIVE_DAYS_LIMIT = 7   # beyond that the world date is more useful

# The two markers, as ONE definition — the header explains them and the entry
# lines carry them, and the two must never drift apart.
MARK_CURRENT = "[CURRENT]"
MARK_RECENT = "[RECENT]"


def _game_days_ago(game_ts: str) -> Optional[int]:
    """Whole GAME days between a canonical stamp and now (None if unusable)."""
    try:
        return game_time().day_index - GameTime.parse(game_ts).day_index
    except (ValueError, TypeError):
        return None


def _format_memory_timestamp(game_ts: str, lang: str = "en") -> str:
    """Compact, LLM-readable WORLD date of a memory.

    Reads the GAME stamp only. A row without one (pre-migration, or unparsable)
    yields "" and the entry goes into the prompt without a time prefix — the
    system stamp is deliberately NOT used as a fallback, because a real date
    inside the world is worse than no date at all.
    """
    try:
        gt = GameTime.parse(game_ts)
    except (ValueError, TypeError):
        return ""
    days = game_time().day_index - gt.day_index
    time_str = gt.time_hhmm()
    if days <= 0:
        return t("today {time}", lang).format(time=time_str)
    if days == 1:
        return t("yesterday {time}", lang).format(time=time_str)
    if days < _RELATIVE_DAYS_LIMIT:
        return t("{days} days ago", lang).format(days=days)
    return f"{gt.date_label(lang)} {time_str}"


def build_memory_prompt_section(character_name: str,
    partner_name: str = "",
    current_message: str = "") -> str:
    """Builds the memory section of the system prompt.

    Grouped by type: episodic, semantic, commitment, relationships. Retrieved
    by context instead of a static top-N.

    ``partner_name`` is the current conversation partner (a character name).
    When set, the header adds a disambiguation hint so the LLM does not read
    the wrong addressee as "the user" during a TalkTo.

    Every time reference is WORLD time (``game_ts``); entries without a game
    stamp appear undated rather than carrying a real-world date.
    """
    memories = retrieve_relevant_memories(character_name,
        current_message=current_message)
    if not memories:
        return ""

    try:
        from app.models.character import get_character_language
        lang = (get_character_language(character_name) or "en").strip() or "en"
    except Exception:
        lang = "en"
    mark_current = t(MARK_CURRENT, lang)
    mark_recent = t(MARK_RECENT, lang)

    # Group by memory_type
    episodic = []
    semantic = []
    commitments = []
    relationships = []

    try:
        from app.models.character import character_exists
    except Exception:
        character_exists = None  # type: ignore

    for mem in memories:
        ts = _format_memory_timestamp(mem.get("game_ts", ""), lang)
        ts_prefix = f"({ts}) " if ts else ""
        related = mem.get("related_character", "")
        content = mem.get("content", "")

        # Dangling filter: a memory/commitment referencing a character that
        # does not (or no longer) exists in the world is kept in storage but
        # not pulled into the prompt. Only applies with related_character set.
        if related and character_exists is not None and not character_exists(related):
            continue

        # Recency marker for very fresh entries — counted in GAME days.
        recency_marker = ""
        days_ago = _game_days_ago(mem.get("game_ts", ""))
        if days_ago is not None:
            if days_ago <= _MARK_CURRENT_DAYS:
                recency_marker = f"{mark_current} "
            elif days_ago <= _MARK_RECENT_DAYS:
                recency_marker = f"{mark_recent} "

        mtype = mem.get("memory_type", "semantic")
        if mtype == "episodic":
            episodic.append(f"- {recency_marker}{ts_prefix}{content}")
        elif mtype == "commitment":
            # Completed commitments nicht im Prompt anzeigen
            if "completed" in mem.get("tags", []):
                continue
            commitments.append(f"- {recency_marker}{ts_prefix}{content}")
        elif related:
            relationships.append(f"- {recency_marker}{ts_prefix}(about {related}) {content}")
        else:
            semantic.append(f"- {recency_marker}{ts_prefix}{content}")

    parts = []
    header = "\nYour memories"
    if partner_name:
        header += (
            f" (you are currently talking with {partner_name} — other names "
            f"are other characters you have met)"
        )
    header += (
        ". Only state what you actually know, never invent details.\n"
        f"Entries marked {mark_current} or {mark_recent} are very recent — "
        "prioritize them over older entries when relevant:"
    )
    parts.append(header)

    if episodic:
        parts.append("\nWhat you've experienced together:")
        parts.extend(episodic)

    if semantic:
        parts.append("\nFacts you remember:")
        parts.extend(semantic)

    if commitments:
        parts.append("\nOpen commitments & plans:")
        parts.extend(commitments)

    if relationships:
        parts.append("\nAbout other characters:")
        parts.extend(relationships)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Mood History
# ---------------------------------------------------------------------------

def load_mood_history(character_name: str) -> List[Dict[str, Any]]:
    """Laedt Mood-History eines Characters aus der DB."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT ts, mood, source FROM mood_history "
            "WHERE character_name=? ORDER BY ts ASC",
            (character_name,),
        ).fetchall()
        return [{"timestamp": r[0], "mood": r[1], "source": r[2]} for r in rows]
    except Exception as e:
        logger.error("load_mood_history Fehler fuer %s: %s", character_name, e)
        return []


def save_mood_history(character_name: str, entries: List[Dict[str, Any]]):
    """Ersetzt Mood-History in der DB (max 500 Eintraege, aelteste werden geloescht)."""
    max_entries = int(os.environ.get("MOOD_HISTORY_MAX_ENTRIES", "500"))
    # Nur letzte max_entries behalten — delete excess
    try:
        conn = get_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM mood_history WHERE character_name=?",
            (character_name,),
        ).fetchone()[0]
        if total > max_entries:
            # Aelteste loeschen
            excess = total - max_entries
            conn.execute("""
                DELETE FROM mood_history WHERE id IN (
                    SELECT id FROM mood_history
                    WHERE character_name=?
                    ORDER BY ts ASC LIMIT ?
                )
            """, (character_name, excess))
            conn.commit()
    except Exception as e:
        logger.error("save_mood_history Trim-Fehler fuer %s: %s", character_name, e)


def record_mood(character_name: str, mood: str, source: str = ""):
    """Zeichnet einen Mood-Datenpunkt auf."""
    if not mood:
        return
    try:
        with transaction() as conn:
            conn.execute("""
                INSERT INTO mood_history (character_name, ts, mood, source)
                VALUES (?, ?, ?, ?)
            """, (character_name, _now_iso(), mood.strip().lower(), source))
        logger.debug("Mood recorded for %s: %s", character_name, mood)
        # Trim falls noetig
        max_entries = int(os.environ.get("MOOD_HISTORY_MAX_ENTRIES", "500"))
        conn = get_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM mood_history WHERE character_name=?",
            (character_name,),
        ).fetchone()[0]
        if total > max_entries:
            excess = total - max_entries
            conn.execute("""
                DELETE FROM mood_history WHERE id IN (
                    SELECT id FROM mood_history
                    WHERE character_name=?
                    ORDER BY ts ASC LIMIT ?
                )
            """, (character_name, excess))
            conn.commit()
    except Exception as e:
        logger.error("record_mood Fehler fuer %s: %s", character_name, e)


# ---------------------------------------------------------------------------
# Migration: Knowledge -> Memory
# ---------------------------------------------------------------------------

def migrate_knowledge_to_memories(character_name: str) -> int:
    """Migriert bestehende knowledge.json Eintraege in die memories-Tabelle.

    Wird nur einmal ausgefuehrt (wenn keine Memories fuer den Character existieren).
    Bestehende knowledge.json bleibt erhalten (Backup).
    """
    # Bereits Daten in DB? -> Abbruch
    try:
        conn = get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE character_name=?", (character_name,)
        ).fetchone()[0]
        if count > 0:
            return 0  # Bereits migriert
    except Exception:
        return 0

    from app.core.paths import get_storage_dir
    knowledge_path = get_storage_dir() / "characters" / character_name / "knowledge.json"
    if not knowledge_path.exists():
        return 0

    try:
        data = json.loads(knowledge_path.read_text(encoding="utf-8"))
        k_entries = data.get("entries", [])
    except Exception:
        return 0

    if not k_entries:
        return 0

    # Mapping: source_type -> memory_type
    type_map = {
        "extraction": "semantic",
        "chat_extraction": "semantic",
        "user_info": "semantic",
        "character_relationship": "semantic",
        "file_extraction": "semantic",
        "instagram_reaction": "episodic",
        "instagram_comment": "episodic",
    }

    memories = []
    for ke in k_entries:
        memory_type = type_map.get(ke.get("source_type", ""), "semantic")
        # Relationship entries bekommen Tag
        tags = []
        related = ke.get("related_character", "")
        if related:
            tags.append("relationship")
        source_type = ke.get("source_type", "")
        if source_type:
            tags.append(source_type)

        memories.append({
            "id": _new_id(),
            "timestamp": ke.get("timestamp", _now_iso()),
            "memory_type": memory_type,
            "content": ke.get("content", ""),
            "context": ke.get("source", ""),
            "importance": ke.get("importance", 3),
            "access_count": 0,
            "last_accessed": "",
            "decay_factor": 1.0,
            "tags": tags,
            "related_character": related,
        })

    save_memories(character_name, memories)
    logger.info("Migriert %d knowledge -> memory fuer %s", len(memories), character_name)
    return len(memories)
