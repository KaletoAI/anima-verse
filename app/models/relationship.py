"""Character Relationship / Social Graph Model.

Zentrales Beziehungsmodell zwischen Charakteren.  Speichert Typ, Staerke,
Sentiment (asymmetrisch) und eine kompakte Interaktions-History.

Storage: world.db — Tabelle relationships

Typ-Logik:
  - romantic_tension (0-1) unterscheidet romantische von rein freundschaftlichen
    Beziehungen.  Beide koennen hohe Staerke haben.
  - Typen: friend, romantic, rival, acquaintance, enemy, neutral
"""
import json
import uuid
from datetime import datetime

from app.core.timeutils import utc_now_iso
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("relationship")

# How many interaction events to keep per relationship
MAX_HISTORY_ENTRIES = 20

# Weekly decay amount when no interaction occurs (applied externally)
DECAY_PER_WEEK = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return utc_now_iso()


def _new_id() -> str:
    return f"rel_{uuid.uuid4().hex[:12]}"


def _sort_pair(a: str, b: str) -> Tuple[str, str]:
    """Canonical order so that (A,B) == (B,A)."""
    return (a, b) if a.lower() <= b.lower() else (b, a)


def _row_to_rel(row) -> Dict[str, Any]:
    """Konvertiert eine DB-Row in das Legacy-Dict-Format."""
    d = dict(row)
    meta = {}
    try:
        meta = json.loads(d.get("meta") or "{}")
    except Exception:
        pass
    content = {}
    try:
        content = json.loads(d.get("content") or "{}")
    except Exception:
        pass
    # Merge content + meta into rel dict
    rel = {**content, **meta}
    # Ensure canonical fields
    rel.setdefault("id", _new_id())
    rel["character_a"] = d.get("from_char", "")
    rel["character_b"] = d.get("to_char", "")
    rel.setdefault("type", "neutral")
    rel.setdefault("strength", 10)
    rel.setdefault("sentiment_a_to_b", 0.0)
    rel.setdefault("sentiment_b_to_a", 0.0)
    rel.setdefault("romantic_tension", 0.0)
    rel.setdefault("interaction_count", 0)
    rel.setdefault("last_interaction", d.get("ts", _now_iso()))
    rel.setdefault("history", [])
    rel.setdefault("created_at", d.get("ts", _now_iso()))
    rel["_db_id"] = d.get("id")
    return rel


# ---------------------------------------------------------------------------
# Romantic interest compatibility
# ---------------------------------------------------------------------------

def get_romantic_interests(character_name: str) -> str:
    """Return the romantic interests description for a character.

    Looks up character_config.json.
    Returns a free-text string. Empty string = no romantic interest.
    """
    try:
        from app.models.character import get_character_config
        config = get_character_config(character_name)
        val = config.get("romantic_interests", "")
        if isinstance(val, list):
            return ", ".join(val)
        if str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    return ""


def are_romantically_compatible(char_a: str, char_b: str) -> bool:
    """Whether two characters could be romantically interested in each other.

    The actual matching (preferences vs. appearance/anatomy) is NSFW-flavoured
    and lives in a separate ``attraction`` package, registered as the
    ``romantic_compatibility`` capability provider (app.core.hooks). The SFW
    core does not judge attraction: without the package installed the default
    is True — romantic tension may build freely from interactions/sentiment,
    ungated.
    """
    try:
        from app.core.hooks import get_provider
        fn = get_provider("romantic_compatibility")
        if fn is not None:
            return bool(fn(char_a, char_b))
    except Exception as e:
        logger.debug("romantic_compatibility provider failed: %s", e)
    return True


def extract_romantic_interests() -> Dict[str, str]:
    """Extract romantic interests from character personality texts via LLM.

    Reads each character's personality and uses a single LLM call to produce
    a short free-text description of each character's romantic/sexual interests.
    Saves the result to each character's config under 'romantic_interests'.

    Only runs if 'romantic_interests' is not yet set in any character config.
    Returns {character_name: description_string}.
    """
    from app.models.character import (
        list_available_characters,
        get_character_personality,
        get_character_config,
        save_character_config)

    characters = list_available_characters()
    if not characters:
        return {}

    # Check if already extracted (skip if ANY character has the field)
    for c in characters:
        cfg = get_character_config(c)
        if "romantic_interests" in cfg:
            return {}  # Already done

    # Build a summary of all characters
    char_descriptions = []
    for c in characters:
        personality = get_character_personality(c) or ""
        if personality:
            char_descriptions.append(f"- {c}: {personality[:300]}")

    if not char_descriptions:
        return {}

    try:
        from app.models.account import get_player_identity
        user_name = get_player_identity("")
    except Exception:
        user_name = ""

    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        import re as _re
        import json as _json

        sys_prompt, user_prompt = render_task(
            "relationship_summary_romantic_interests",
            char_descriptions="\n".join(char_descriptions))

        response = llm_call(
            task="relationship_summary",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name="system")

        raw = _re.sub(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>', '', response.content).strip()
        match = _re.search(r'\{[\s\S]+\}', raw)
        if not match:
            logger.warning("Could not parse romantic interests JSON")
            return {}

        data = _json.loads(match.group(0))
        result = {}

        for c in characters:
            desc = str(data.get(c, "")).strip()
            result[c] = desc
            cfg = get_character_config(c)
            cfg["romantic_interests"] = desc
            save_character_config(c, cfg)
            if desc:
                logger.info("Romantic interests for %s: %s", c, desc)

        return result

    except Exception as e:
        logger.error("Romantic interest extraction failed: %s", e)
        for c in characters:
            cfg = get_character_config(c)
            cfg["romantic_interests"] = ""
            save_character_config(c, cfg)
        return {}


# ---------------------------------------------------------------------------
# Relationship type classification
# ---------------------------------------------------------------------------

def classify_type(
    strength: float,
    sentiment_a: float,
    sentiment_b: float,
    romantic_tension: float,
    romantic_compatible: bool = True) -> str:
    """Determine relationship type from numeric signals.

    romantic_tension >= 0.5  AND  strength >= 30  AND compatible -> romantic
    strength >= 40  AND  avg_sentiment >= 0.2                    -> friend
    strength >= 20  AND  avg_sentiment <= -0.1                   -> rival
    avg_sentiment <= -0.25                                       -> enemy
    strength >= 15                                               -> acquaintance
    else                                                         -> neutral

    romantic_compatible: must be True (derived from character profiles) for
    the relationship to be classified as romantic.
    """
    avg_sent = (sentiment_a + sentiment_b) / 2.0

    if romantic_tension >= 0.5 and strength >= 30 and romantic_compatible:
        return "romantic"
    if avg_sent <= -0.25:
        return "enemy"
    if strength >= 20 and avg_sent <= -0.1:
        return "rival"
    if strength >= 40 and avg_sent >= 0.2:
        return "friend"
    if strength >= 15:
        return "acquaintance"
    return "neutral"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def load_relationships() -> List[Dict[str, Any]]:
    """Laedt alle Beziehungen aus der DB."""
    try:
        conn = get_connection()
        # Jede (from_char, to_char) Kombination ist eine Beziehungszeile
        # Gruppen nach (from_char, to_char) — neueste Row pro Paar
        rows = conn.execute("""
            SELECT DISTINCT from_char, to_char,
                MAX(id) as latest_id
            FROM relationships
            GROUP BY from_char, to_char
        """).fetchall()

        rels = []
        seen_pairs = set()
        for r in rows:
            a, b = _sort_pair(r[0], r[1])
            pair_key = (a, b)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            # Hole den neuesten Eintrag fuer das kanonische Paar
            row = conn.execute("""
                SELECT * FROM relationships
                WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?)
                ORDER BY id DESC LIMIT 1
            """, (a, b, b, a)).fetchone()
            if row:
                rels.append(_row_to_rel(row))
        return rels
    except Exception as e:
        logger.error("load_relationships DB-Fehler: %s", e)
        return []


def save_relationships(rels: List[Dict[str, Any]]):
    """Speichert alle Beziehungen in die DB (Upsert per Paar)."""
    for rel in rels:
        _save_relationship(rel)


def _save_relationship(rel: Dict[str, Any]):
    """Speichert/aktualisiert eine einzelne Beziehung."""
    a, b = _sort_pair(rel.get("character_a", ""), rel.get("character_b", ""))
    if not a or not b:
        return
    ts = rel.get("last_interaction", _now_iso())
    # Content: Kern-Felder die abfragbar sein sollen
    content = {k: rel[k] for k in
               ("type", "strength", "sentiment_a_to_b", "sentiment_b_to_a",
                "romantic_tension", "interaction_count")
               if k in rel}
    content["character_a"] = a
    content["character_b"] = b
    # Meta: Rest
    meta = {k: v for k, v in rel.items()
            if k not in ("character_a", "character_b", "_db_id",
                         "type", "strength", "sentiment_a_to_b", "sentiment_b_to_a",
                         "romantic_tension", "interaction_count")}

    db_id = rel.get("_db_id")
    try:
        if db_id:
            with transaction() as conn:
                conn.execute("""
                    UPDATE relationships
                    SET from_char=?, to_char=?, content=?, ts=?, meta=?
                    WHERE id=?
                """, (a, b, json.dumps(content, ensure_ascii=False),
                      ts, json.dumps(meta, ensure_ascii=False), db_id))
        else:
            # Suche bestehende Row fuer dieses Paar
            conn = get_connection()
            existing = conn.execute("""
                SELECT id FROM relationships
                WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?)
                ORDER BY id DESC LIMIT 1
            """, (a, b, b, a)).fetchone()
            if existing:
                rel["_db_id"] = existing[0]
                with transaction() as conn:
                    conn.execute("""
                        UPDATE relationships
                        SET from_char=?, to_char=?, content=?, ts=?, meta=?
                        WHERE id=?
                    """, (a, b, json.dumps(content, ensure_ascii=False),
                          ts, json.dumps(meta, ensure_ascii=False), existing[0]))
            else:
                with transaction() as conn:
                    cur = conn.execute("""
                        INSERT INTO relationships (from_char, to_char, content, ts, meta)
                        VALUES (?, ?, ?, ?, ?)
                    """, (a, b, json.dumps(content, ensure_ascii=False),
                          ts, json.dumps(meta, ensure_ascii=False)))
                    rel["_db_id"] = cur.lastrowid
    except Exception as e:
        logger.error("_save_relationship Fehler fuer %s/%s: %s", a, b, e)


def get_relationship(char_a: str, char_b: str
) -> Optional[Dict[str, Any]]:
    """Return the relationship between two characters (order-independent)."""
    a, b = _sort_pair(char_a, char_b)
    try:
        conn = get_connection()
        row = conn.execute("""
            SELECT * FROM relationships
            WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?)
            ORDER BY id DESC LIMIT 1
        """, (a, b, b, a)).fetchone()
        if row:
            return _row_to_rel(row)
    except Exception as e:
        logger.error("get_relationship DB-Fehler fuer %s/%s: %s", char_a, char_b, e)
    return None


def get_character_relationships(character_name: str
) -> List[Dict[str, Any]]:
    """All relationships involving *character_name*."""
    try:
        conn = get_connection()
        rows = conn.execute("""
            SELECT * FROM relationships
            WHERE from_char=? OR to_char=?
            ORDER BY ts DESC
        """, (character_name, character_name)).fetchall()
        # Deduplizieren nach Paar
        seen = set()
        result = []
        for row in rows:
            d = dict(row)
            a, b = _sort_pair(d["from_char"], d["to_char"])
            pk = (a, b)
            if pk not in seen:
                seen.add(pk)
                result.append(_row_to_rel(row))
        return result
    except Exception as e:
        logger.error("get_character_relationships DB-Fehler fuer %s: %s", character_name, e)
        return []


def get_all_relationships() -> List[Dict[str, Any]]:
    return load_relationships()


def _ensure_relationship(char_a: str, char_b: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (all_rels, target_rel), creating target if needed."""
    existing = get_relationship(char_a, char_b)
    if existing:
        # Gib eine Dummy-Liste zurueck damit der Aufrufer save_relationships aufrufen kann
        return [existing], existing

    a, b = _sort_pair(char_a, char_b)
    now = _now_iso()
    new_rel: Dict[str, Any] = {
        "id": _new_id(),
        "character_a": a,
        "character_b": b,
        "type": "neutral",
        "strength": 10,
        "sentiment_a_to_b": 0.0,
        "sentiment_b_to_a": 0.0,
        "romantic_tension": 0.0,
        "interaction_count": 0,
        "last_interaction": now,
        "history": [],
        "created_at": now,
    }
    # Direkt in DB schreiben
    _save_relationship(new_rel)
    return [new_rel], new_rel


# ---------------------------------------------------------------------------
# Update after an interaction
# ---------------------------------------------------------------------------

def record_interaction(char_a: str,
    char_b: str,
    interaction_type: str,
    summary: str = "",
    sentiment_delta_a: float = 0.0,
    sentiment_delta_b: float = 0.0,
    strength_delta: float = 2.0,
    # NOTE: self-relationships are silently ignored (see guard below)
    romantic_delta: float = 0.0) -> Dict[str, Any]:
    """Record an interaction and update relationship metrics.

    Parameters
    ----------
    char_a : initiator
    char_b : receiver
    interaction_type : e.g. "talkto", "instagram_like", "instagram_comment",
                       "social_dialog", "instagram_reply"
    summary : short human-readable description
    sentiment_delta_a : change in A's sentiment toward B  (-1..1 range, clamped)
    sentiment_delta_b : change in B's sentiment toward A
    strength_delta : how much strength increases (always positive, clamped 0-100)
    romantic_delta : nudge to romantic_tension (can be negative)
    """
    # Guard: no self-relationships
    if char_a.lower() == char_b.lower():
        return {}

    # Guard: reserved names (admin, user, system, default, player, "") are
    # NOT real characters — they're login accounts or sentinels. If the
    # caller falls back to the login name (e.g. when active_character is
    # empty), we must not record a relationship for it. Skip silently —
    # the chat itself still works, only the relationship metric is dropped.
    from app.models.character import _RESERVED_NAMES
    if char_a.lower() in _RESERVED_NAMES or char_b.lower() in _RESERVED_NAMES:
        return {}

    # Guard: check if relationships are enabled for both characters
    try:
        from app.models.character import get_character_config
        for name in (char_a, char_b):
            cfg = get_character_config(name)
            if str(cfg.get("relationships_enabled", "true")).lower() == "false":
                return {}
    except Exception:
        pass

    rels, rel = _ensure_relationship(char_a, char_b)

    # Determine which direction is a/b in the canonical pair
    ca, cb = _sort_pair(char_a, char_b)
    a_is_first = (char_a == ca)

    # Update strength (clamped 0-100)
    # Negative sentiment reduces strength — conflict pushes people apart
    avg_sentiment_delta = (sentiment_delta_a + sentiment_delta_b) / 2.0
    effective_strength_delta = strength_delta
    if avg_sentiment_delta < -0.01:
        # Strong negativity can reduce strength (e.g. -0.3 avg → -3.0 strength)
        effective_strength_delta = min(strength_delta, avg_sentiment_delta * 10)
    rel["strength"] = max(0, min(100, rel.get("strength", 10) + effective_strength_delta))

    # Update sentiments (clamped -1..1)
    if a_is_first:
        rel["sentiment_a_to_b"] = max(-1, min(1, rel.get("sentiment_a_to_b", 0) + sentiment_delta_a))
        rel["sentiment_b_to_a"] = max(-1, min(1, rel.get("sentiment_b_to_a", 0) + sentiment_delta_b))
    else:
        # char_a is actually character_b in canonical order
        rel["sentiment_b_to_a"] = max(-1, min(1, rel.get("sentiment_b_to_a", 0) + sentiment_delta_a))
        rel["sentiment_a_to_b"] = max(-1, min(1, rel.get("sentiment_a_to_b", 0) + sentiment_delta_b))

    # Romantic tension — only apply if characters are romantically compatible
    compatible = are_romantically_compatible(char_a, char_b)
    if compatible and romantic_delta != 0:
        rel["romantic_tension"] = max(0, min(1, rel.get("romantic_tension", 0) + romantic_delta))
    elif not compatible:
        # Actively decay romantic tension for incompatible pairs
        old_rt = rel.get("romantic_tension", 0)
        if old_rt > 0:
            rel["romantic_tension"] = max(0, old_rt - 0.05)

    # Interaction count
    rel["interaction_count"] = rel.get("interaction_count", 0) + 1
    rel["last_interaction"] = _now_iso()

    # Append to history (include per-entry sentiment delta for diary)
    avg_sent_delta = round((sentiment_delta_a + sentiment_delta_b) / 2.0, 3)
    history: list = rel.setdefault("history", [])
    history.append({
        "timestamp": _now_iso(),
        "type": interaction_type,
        "initiator": char_a,
        "summary": summary[:200] if summary else "",
        "sentiment_delta": avg_sent_delta,
    })
    if len(history) > MAX_HISTORY_ENTRIES:
        rel["history"] = history[-MAX_HISTORY_ENTRIES:]

    # Reclassify type
    rel["type"] = classify_type(
        rel["strength"],
        rel.get("sentiment_a_to_b", 0),
        rel.get("sentiment_b_to_a", 0),
        rel.get("romantic_tension", 0),
        romantic_compatible=compatible)

    save_relationships(rels)
    logger.debug(
        "Relationship %s <-> %s: type=%s str=%.0f sent=(%.2f,%.2f) rom=%.2f [%s]",
        char_a, char_b, rel["type"], rel["strength"],
        rel.get("sentiment_a_to_b", 0), rel.get("sentiment_b_to_a", 0),
        rel.get("romantic_tension", 0), interaction_type)
    return rel


def reclassify_all_relationships(*, decay_blocked_tension: bool = True
) -> Dict[str, Any]:
    """Re-run classify_type on every relationship using current compatibility.

    Used after changing romantic_blocked_with lists or other compatibility
    inputs — fixes stale "romantic" types whose pairs are now hard-blocked.

    If *decay_blocked_tension* is True, also resets romantic_tension to 0
    for any pair where are_romantically_compatible() is now False. Without
    this, a previously high tension would just slowly decay via
    record_interaction.

    Returns a summary dict with counts and a list of changed pairs.
    """
    rels = load_relationships()
    changed: list = []
    tension_reset = 0

    for rel in rels:
        a = rel.get("character_a", "")
        b = rel.get("character_b", "")
        if not a or not b:
            continue

        old_type = rel.get("type", "neutral")
        old_tension = rel.get("romantic_tension", 0)
        compatible = are_romantically_compatible(a, b)

        if decay_blocked_tension and not compatible and old_tension > 0:
            rel["romantic_tension"] = 0
            tension_reset += 1

        new_type = classify_type(
            rel.get("strength", 0),
            rel.get("sentiment_a_to_b", 0),
            rel.get("sentiment_b_to_a", 0),
            rel.get("romantic_tension", 0),
            romantic_compatible=compatible)

        if new_type != old_type or rel.get("romantic_tension", 0) != old_tension:
            rel["type"] = new_type
            _save_relationship(rel)
            changed.append({
                "character_a": a,
                "character_b": b,
                "old_type": old_type,
                "new_type": new_type,
                "old_romantic_tension": round(old_tension, 3),
                "new_romantic_tension": round(rel.get("romantic_tension", 0), 3),
                "compatible": compatible,
            })

    logger.info("reclassify_all: %d total, %d changed, %d tension reset",
                len(rels), len(changed), tension_reset)
    return {
        "total": len(rels),
        "changed": len(changed),
        "tension_reset": tension_reset,
        "details": changed,
    }


def update_relationship_manual(char_a: str,
    char_b: str,
    *,
    rel_type: Optional[str] = None,
    strength: Optional[float] = None,
    romantic_tension: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Manual override (from UI or admin)."""
    rels, rel = _ensure_relationship(char_a, char_b)
    if rel_type:
        rel["type"] = rel_type
    if strength is not None:
        rel["strength"] = max(0, min(100, strength))
    if romantic_tension is not None:
        rel["romantic_tension"] = max(0, min(1, romantic_tension))
    save_relationships(rels)
    return rel


# ---------------------------------------------------------------------------
# Prompt section builder (for system prompt injection)
# ---------------------------------------------------------------------------

def build_relationship_prompt_section(character_name: str
) -> str:
    """Build a short prompt section describing this character's relationships."""
    rels = get_character_relationships(character_name)
    if not rels:
        return ""

    account_names: set[str] = set()
    try:
        from app.models.account import get_user_profile
        from app.core.users import list_users
        acc = (get_user_profile().get("user_name") or "").strip().lower()
        if acc:
            account_names.add(acc)
        for u in list_users():
            uname = (u.get("username") or "").strip().lower()
            if uname:
                account_names.add(uname)
    except Exception:
        pass

    if account_names:
        def _other(r: Dict[str, Any]) -> str:
            a = (r.get("character_a") or "").lower()
            b = (r.get("character_b") or "").lower()
            return b if a == character_name.lower() else a
        rels = [r for r in rels if _other(r) not in account_names]
        if not rels:
            return ""

    # Dangling-Filter: Beziehungen zu nicht (mehr) in der Welt existierenden
    # Characters nicht in den Prompt ziehen (Daten bleiben in der DB erhalten und
    # tauchen wieder auf, sobald der referenzierte Character importiert wird).
    try:
        from app.models.character import character_exists
        def _other_name(r: Dict[str, Any]) -> str:
            a = r.get("character_a", "") or ""
            b = r.get("character_b", "") or ""
            return b if a.lower() == character_name.lower() else a
        rels = [r for r in rels if character_exists(_other_name(r))]
        if not rels:
            return ""
    except Exception:
        pass

    # Sort by strength descending, take top 8
    rels.sort(key=lambda r: r.get("strength", 0), reverse=True)
    rels = rels[:8]

    type_labels = {
        "friend": "Friend",
        "romantic": "Romantic interest",
        "rival": "Rival",
        "acquaintance": "Acquaintance",
        "enemy": "Enemy",
        "neutral": "Known",
    }

    lines = ["\nYour relationships with other characters:"]
    for rel in rels:
        a = rel.get("character_a", "")
        b = rel.get("character_b", "")
        other = b if a.lower() == character_name.lower() else a
        rtype = type_labels.get(rel.get("type", "neutral"), "Known")
        strength = int(rel.get("strength", 0))

        # Determine this character's sentiment toward the other
        if a.lower() == character_name.lower():
            my_sentiment = rel.get("sentiment_a_to_b", 0)
        else:
            my_sentiment = rel.get("sentiment_b_to_a", 0)

        if my_sentiment > 0.5:
            feeling = "very positive"
        elif my_sentiment > 0.1:
            feeling = "positive"
        elif my_sentiment < -0.5:
            feeling = "very negative"
        elif my_sentiment < -0.1:
            feeling = "negative"
        else:
            feeling = "neutral"

        lines.append(f"- {other}: {rtype} (closeness {strength}/100, feeling: {feeling})")

    return "\n".join(lines)

