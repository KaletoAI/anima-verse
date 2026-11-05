"""Character Relationship / Social Graph Model.

The central relationship model between characters. Stores type, strength,
sentiment (asymmetric) and a compact interaction history.

Storage: world.db — table ``relationships``

Type logic:
  - ``romantic_tension`` (0-1) separates romantic from purely friendly
    relationships. Both can have a high strength.
  - types: friend, romantic, rival, acquaintance, enemy, neutral

Two clocks, two stamps: ``last_interaction`` is the SYSTEM stamp and only
answers technical questions (it becomes the row's ``ts`` column, which orders
the rows), while ``last_interaction_game`` is the canonical GAME stamp of the
same event — everything the world says about WHEN two characters last met, and
the only span the decay job measures (``app/core/relationship_decay.py``).

Linked characters (ruling R1 of
``docs/superpowers/specs/2026-11-05-linked-characters-design.md``): a body
shares its leader's mind, so the OWN side of a body's relationship — its
feeling toward X and its form of address for X — lives on the LEADER row
(leader, X); everything else (X's feeling toward the body, strength, type,
tension, history) stays on the body row (body, X), whose body->X sentiment is
never written nor read. :func:`own_sentiment` is the one reader of "how does
this speaker feel about X"; members of one family never get a row with each
other. A leader row that only exists because a body acted carries
``mind_only`` (the minds whose side it is): X has not met that leader, so X's
own views skip it (:func:`visible_to`).
"""
import json
import uuid
from datetime import datetime

from app.core.timeutils import game_time, utc_now_iso
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("relationship")

# How many interaction events to keep per relationship
MAX_HISTORY_ENTRIES = 20

# Human-readable label per relationship type (used in every prompt section)
TYPE_LABELS = {
    "friend": "Friend",
    "romantic": "Romantic interest",
    "rival": "Rival",
    "acquaintance": "Acquaintance",
    "enemy": "Enemy",
    "neutral": "Known",
}


def sentiment_label(value: float) -> str:
    """Map an asymmetric sentiment (-1..1) to the word used in prompts."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v > 0.5:
        return "very positive"
    if v > 0.1:
        return "positive"
    if v < -0.5:
        return "very negative"
    if v < -0.1:
        return "negative"
    return "neutral"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """SYSTEM stamp — row ordering and other technical questions."""
    return utc_now_iso()


def _now_game() -> str:
    """GAME stamp — the world's own answer to "when did this happen?"."""
    return game_time().canonical()


def _new_id() -> str:
    return f"rel_{uuid.uuid4().hex[:12]}"


def _sort_pair(a: str, b: str) -> Tuple[str, str]:
    """Canonical order so that (A,B) == (B,A)."""
    return (a, b) if a.lower() <= b.lower() else (b, a)


def _sentiment_key(speaker: str, other: str) -> str:
    """The content key of *speaker*'s own feeling toward *other* in their row.

    Rows are stored in ``_sort_pair`` order: ``sentiment_a_to_b`` is the
    feeling of the name that sorts first.
    """
    first, _second = _sort_pair(speaker, other)
    return ("sentiment_a_to_b" if first.lower() == speaker.lower()
            else "sentiment_b_to_a")


def _row_key(rel: Dict[str, Any], speaker: str, other: str) -> str:
    """:func:`_sentiment_key` read off the row's own ``character_a`` when it
    names one of the two (a hand-built row need not be in sort order)."""
    a = str(rel.get("character_a") or "").lower()
    b = str(rel.get("character_b") or "").lower()
    if a == speaker.lower() and b != speaker.lower():
        return "sentiment_a_to_b"
    if b == speaker.lower() and a != speaker.lower():
        return "sentiment_b_to_a"
    return _sentiment_key(speaker, other)


def _mind_of(name: str) -> str:
    """The mind owner of *name* (its leader for a linked body)."""
    from app.core.linked_characters import mind_of
    return mind_of(name)


def _one_family(a: str, b: str) -> bool:
    """Whether *a* and *b* share one mind (or are the same character)."""
    return _mind_of(a).lower() == _mind_of(b).lower()


#: Meta key of a leader row that only carries a mind's side (see module note).
MIND_ONLY_KEY = "mind_only"


def visible_to(rel: Dict[str, Any], name: str) -> bool:
    """Whether the row is a relationship *name* has (not only another mind's side).

    A ``mind_only`` row was created because a BODY acted: it carries that
    mind's own side toward X, but X never met the leader — so it belongs to
    the views of that mind's family only.
    """
    owners = rel.get(MIND_ONLY_KEY) or []
    if not owners:
        return True
    mind = _mind_of(name).lower()
    return any(str(o).lower() == mind for o in owners)


def own_sentiment(speaker: str, other: str, *,
                  rel: Optional[Dict[str, Any]] = None) -> float:
    """How *speaker* feels about *other* (-1..1; 0.0 without a row).

    A linked body feels with its mind: the value is read from the leader row
    (leader, other). Only the speaker side is mapped — *other* is taken as
    named. Two members of one family have no feeling toward each other here.
    *rel* is the (speaker, other) row when the caller already holds it — it
    saves the read for a speaker that is no linked body.
    """
    if not speaker or not other or _one_family(speaker, other):
        return 0.0
    mind = _mind_of(speaker)
    if rel is None or mind != speaker:
        rel = get_relationship(mind, other)
    if not rel:
        return 0.0
    try:
        return float(rel.get(_row_key(rel, mind, other)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def row_sentiments(rel: Dict[str, Any]) -> Tuple[float, float]:
    """``(a_to_b, b_to_a)`` as ``classify_type`` reads them for this row.

    A side that is a linked body has no stored feeling of its own on its row;
    its own sentiment (the leader value) stands in for it.
    """
    from app.core.linked_characters import is_linked
    a = rel.get("character_a", "") or ""
    b = rel.get("character_b", "") or ""
    a_to_b = (own_sentiment(a, b) if a and is_linked(a)
              else rel.get("sentiment_a_to_b", 0) or 0)
    b_to_a = (own_sentiment(b, a) if b and is_linked(b)
              else rel.get("sentiment_b_to_a", 0) or 0)
    return float(a_to_b), float(b_to_a)


def _row_to_rel(row, *, strict: bool = False) -> Dict[str, Any]:
    """Convert a DB row into the dict format the callers use."""
    d = dict(row)
    meta = {}
    try:
        meta = json.loads(d.get("meta") or "{}")
    except Exception:
        if strict:
            raise
        pass
    content = {}
    try:
        content = json.loads(d.get("content") or "{}")
    except Exception:
        if strict:
            raise
        pass
    if strict and (not isinstance(meta, dict) or not isinstance(content, dict)):
        raise ValueError("Relationship metadata and content must be objects")
    # Merge content + meta into rel dict
    rel = {**content, **meta}
    # Ensure canonical fields
    rel.setdefault("id", _new_id())
    rel["character_a"] = d.get("from_char", "")
    rel["character_b"] = d.get("to_char", "")
    rel.setdefault("type", "neutral")
    # Strict consumers need to distinguish absent measurements from real zeroes.
    # Preserve the historical defaults only for ordinary, nonstrict readers.
    if not strict:
        rel.setdefault("strength", 10)
        rel.setdefault("sentiment_a_to_b", 0.0)
        rel.setdefault("sentiment_b_to_a", 0.0)
        rel.setdefault("romantic_tension", 0.0)
        rel.setdefault("interaction_count", 0)
    rel.setdefault("last_interaction", d.get("ts", _now_iso()))
    # ``last_interaction_game`` deliberately gets NO default here: its absence
    # is what marks a pair written before the game stamps existed, and the
    # decay job stamps such a pair once instead of charging it a backlog.
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
    """Load all relationships from the DB."""
    try:
        conn = get_connection()
        # Each directed pair has a relationship row.
        # Group by pair and select its newest row.
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
            # Load the newest entry for the canonical pair.
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
    """Upsert all relationships by pair."""
    for rel in rels:
        _save_relationship(rel)


def _save_relationship(rel: Dict[str, Any]):
    """Insert or update one relationship."""
    a, b = _sort_pair(rel.get("character_a", ""), rel.get("character_b", ""))
    if not a or not b:
        return
    # The row's ``ts`` column orders the rows — a technical question, so it
    # carries the SYSTEM stamp. The world stamp travels in the meta blob.
    ts = rel.get("last_interaction", _now_iso())
    # Content: the core fields that must stay queryable
    content = {k: rel[k] for k in
               ("type", "strength", "sentiment_a_to_b", "sentiment_b_to_a",
                "romantic_tension", "interaction_count")
               if k in rel}
    content["character_a"] = a
    content["character_b"] = b
    # Meta: everything else
    meta = {k: v for k, v in rel.items()
            if k not in ("character_a", "character_b", "_db_id",
                         "type", "strength", "sentiment_a_to_b", "sentiment_b_to_a",
                         "romantic_tension", "interaction_count")}

    def differs(conn, row_id):
        row = conn.execute(
            "SELECT from_char, to_char, content, ts, meta FROM relationships WHERE id=?",
            (row_id,)).fetchone()
        if row is None:
            return False
        try:
            old_content = json.loads(row["content"] or "{}")
            old_meta = json.loads(row["meta"] or "{}")
        except (TypeError, ValueError):
            # Preserve the writer's ability to replace a malformed old row.
            return True
        return (row["from_char"] != a or row["to_char"] != b
                or old_content != content or row["ts"] != ts or old_meta != meta)

    changed = True
    db_id = rel.get("_db_id")
    try:
        if db_id:
            with transaction() as conn:
                changed = differs(conn, db_id)
                conn.execute("""
                    UPDATE relationships
                    SET from_char=?, to_char=?, content=?, ts=?, meta=?
                    WHERE id=?
                """, (a, b, json.dumps(content, ensure_ascii=False),
                      ts, json.dumps(meta, ensure_ascii=False), db_id))
        else:
            # Find the existing row for this pair.
            conn = get_connection()
            existing = conn.execute("""
                SELECT id FROM relationships
                WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?)
                ORDER BY id DESC LIMIT 1
            """, (a, b, b, a)).fetchone()
            if existing:
                rel["_db_id"] = existing[0]
                with transaction() as conn:
                    changed = differs(conn, existing[0])
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
        return
    if changed:
        try:
            from app.core import sync_topics
            sync_topics.avatars([a, b], ("self", "presence"))
        except Exception as e:
            logger.debug("relationship sync failed: %s", e)


def get_relationship(char_a: str, char_b: str, *, strict: bool = False) -> Optional[Dict[str, Any]]:
    """Return the pair row, or None for no row; strict reads propagate DB/JSON failures."""
    a, b = _sort_pair(char_a, char_b)
    try:
        conn = get_connection()
        row = conn.execute("""
            SELECT * FROM relationships
            WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?)
            ORDER BY id DESC LIMIT 1
        """, (a, b, b, a)).fetchone()
        if row:
            return _row_to_rel(row, strict=strict)
    except Exception as e:
        if strict:
            raise
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
        # Deduplicate by pair.
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


def _ensure_relationship(char_a: str, char_b: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (all_rels, target_rel), creating target if needed."""
    existing = get_relationship(char_a, char_b)
    if existing:
        # Hand back a one-element list so the caller can call save_relationships
        return [existing], existing

    a, b = _sort_pair(char_a, char_b)
    now = _now_iso()
    now_game = _now_game()
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
        "last_interaction_game": now_game,
        "history": [],
        "created_at": now,
    }
    # Write straight to the DB
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

    A linked body's OWN delta goes to its leader row instead (ruling R1, see
    :func:`_touch_mind_side`); the pair's row keeps everything else. Two
    members of one family never get a row.
    """
    # Guard: no self-relationships, none inside one family (one mind)
    if char_a.lower() == char_b.lower() or _one_family(char_a, char_b):
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

    # The minds' sides first, so the classification below reads the new value.
    mind_a, mind_b = _mind_of(char_a), _mind_of(char_b)
    if mind_a != char_a:
        _touch_mind_side(mind_a, char_b, sentiment_delta_a)
    if mind_b != char_b:
        _touch_mind_side(mind_b, char_a, sentiment_delta_b)

    rels, rel = _ensure_relationship(char_a, char_b)
    # The two stand face to face: whatever only a mind carried is a meeting now.
    rel.pop(MIND_ONLY_KEY, None)

    # Update strength (clamped 0-100)
    # Negative sentiment reduces strength — conflict pushes people apart
    avg_sentiment_delta = (sentiment_delta_a + sentiment_delta_b) / 2.0
    effective_strength_delta = strength_delta
    if avg_sentiment_delta < -0.01:
        # Strong negativity can reduce strength (e.g. -0.3 avg → -3.0 strength)
        effective_strength_delta = min(strength_delta, avg_sentiment_delta * 10)
    rel["strength"] = max(0, min(100, rel.get("strength", 10) + effective_strength_delta))

    # Update sentiments (clamped -1..1). A linked body's own direction on this
    # row is never written: its feeling went to the leader row above.
    for speaker, other, delta, mind in ((char_a, char_b, sentiment_delta_a, mind_a),
                                        (char_b, char_a, sentiment_delta_b, mind_b)):
        if mind != speaker:
            continue
        key = _sentiment_key(speaker, other)
        rel[key] = max(-1, min(1, rel.get(key, 0) + delta))

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
    rel["last_interaction_game"] = _now_game()

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

    # Reclassify type (a body side reads its own sentiment from the leader row)
    sent_ab, sent_ba = row_sentiments(rel)
    rel["type"] = classify_type(
        rel["strength"],
        sent_ab,
        sent_ba,
        rel.get("romantic_tension", 0),
        romantic_compatible=compatible)

    save_relationships(rels)
    logger.debug(
        "Relationship %s <-> %s: type=%s str=%.0f sent=(%.2f,%.2f) rom=%.2f [%s]",
        char_a, char_b, rel["type"], rel["strength"],
        rel.get("sentiment_a_to_b", 0), rel.get("sentiment_b_to_a", 0),
        rel.get("romantic_tension", 0), interaction_type)
    return rel


def _touch_mind_side(mind: str, other: str, delta: float) -> None:
    """A body of *mind* interacted with *other*: the mind's own side moves.

    Adds *delta* to the leader row's mind->other sentiment and touches its
    ``last_interaction_game`` (decay must not erode a feeling the mind keeps
    exercising) — nothing else on that row (ruling R1). A row created here,
    or one that so far only carried other minds' sides, is ``mind_only``.
    """
    existing = get_relationship(mind, other)
    rels, rel = _ensure_relationship(mind, other)
    owners = rel.get(MIND_ONLY_KEY)
    if existing is None:
        rel[MIND_ONLY_KEY] = [mind]
    elif owners and mind not in owners:
        rel[MIND_ONLY_KEY] = list(owners) + [mind]
    key = _sentiment_key(mind, other)
    rel[key] = max(-1, min(1, rel.get(key, 0) + delta))
    rel["last_interaction_game"] = _now_game()
    save_relationships(rels)


def update_relationship_manual(char_a: str,
    char_b: str,
    *,
    rel_type: Optional[str] = None,
    strength: Optional[float] = None,
    romantic_tension: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Manual override (from UI or admin). None inside one family."""
    if _one_family(char_a, char_b):
        return None
    rels, rel = _ensure_relationship(char_a, char_b)
    # Authored by hand: a relationship of both sides from now on.
    rel.pop(MIND_ONLY_KEY, None)
    if rel_type:
        rel["type"] = rel_type
    if strength is not None:
        rel["strength"] = max(0, min(100, strength))
    if romantic_tension is not None:
        rel["romantic_tension"] = max(0, min(1, romantic_tension))
    save_relationships(rels)
    return rel


# ---------------------------------------------------------------------------
# Form of address (per pair, per direction)
# ---------------------------------------------------------------------------
#
# Free text, one note per DIRECTION of a pair: how A addresses B and how B
# addresses A ("formal, calls her Doctor" / "informal, nickname Pip"). The
# speaking character's prompt carries its own direction, which is what keeps a
# German world from wobbling between "Sie" and "du" from turn to turn.
#
# Stored in the relationship row's meta blob like the other non-numeric fields
# (``history``, ``last_interaction_game``): ``address_a_to_b`` /
# ``address_b_to_a``, oriented exactly like the sentiments — ``a`` is the name
# that sorts first (``_sort_pair``).

# One prompt LINE, so a note is capped and single-line on purpose.
ADDRESS_MAX_LEN = 120


class AddressTextError(ValueError):
    """A form-of-address note violates the field contract."""


def _clean_address(text: Any) -> str:
    """Normalise + validate a form-of-address note.

    Blank clears the field. Control characters (newlines included) are
    rejected because the note is rendered as ONE prompt line; more than
    ADDRESS_MAX_LEN characters is rejected as well.
    """
    s = "" if text is None else str(text)
    s = s.strip()
    if not s:
        return ""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in s):
        raise AddressTextError(
            "form of address must not contain line breaks or control characters")
    if len(s) > ADDRESS_MAX_LEN:
        raise AddressTextError(
            f"form of address is limited to {ADDRESS_MAX_LEN} characters")
    return s


def _address_keys(speaker: str, addressee: str) -> Tuple[str, str]:
    """(outgoing_key, incoming_key) for *speaker* in this pair.

    The ONE place the a/b orientation is resolved. A row is always stored in
    ``_sort_pair`` order, so ``address_a_to_b`` is the speaker's own direction
    exactly when the speaker is the name that sorts first — the same rule
    ``record_interaction`` applies to the sentiments.
    """
    first, _second = _sort_pair(speaker, addressee)
    if first.lower() == speaker.lower():
        return "address_a_to_b", "address_b_to_a"
    return "address_b_to_a", "address_a_to_b"


def get_address(speaker: str, addressee: str) -> str:
    """How *speaker* addresses *addressee*. Empty string when unset.

    A linked body addresses others as its mind does: the leader's direction.
    """
    if not speaker or not addressee or _one_family(speaker, addressee):
        return ""
    speaker = _mind_of(speaker)
    rel = get_relationship(speaker, addressee)
    if not rel:
        return ""
    out_key, _in_key = _address_keys(speaker, addressee)
    return str(rel.get(out_key) or "").strip()


def set_address(speaker: str, addressee: str, text: Any) -> bool:
    """Set how *speaker* addresses *addressee*; empty text clears it.

    Creates the pair when it does not exist yet. Raises ``AddressTextError``
    when the text violates the field contract. Returns False for an empty or
    self-directed pair and for two members of one family.

    A linked body's address is its mind's: it lands on the leader row (a row
    created that way is ``mind_only``).
    """
    if not speaker or not addressee or _one_family(speaker, addressee):
        return False
    value = _clean_address(text)
    mind = _mind_of(speaker)
    created = mind != speaker and get_relationship(mind, addressee) is None
    speaker = mind
    out_key, _in_key = _address_keys(speaker, addressee)
    rels, rel = _ensure_relationship(speaker, addressee)
    if created:
        rel[MIND_ONLY_KEY] = [mind]
    if value:
        rel[out_key] = value
    else:
        rel.pop(out_key, None)
    save_relationships(rels)
    return True


def address_line(speaker: str, addressee: str) -> str:
    """The one prompt line, or "" when nothing is set for this direction."""
    text = get_address(speaker, addressee)
    return f"Form of address: {text}" if text else ""


# ---------------------------------------------------------------------------
# Prompt section builder (for system prompt injection)
# ---------------------------------------------------------------------------

def _account_names() -> set:
    """Lower-cased login names — never a relationship partner in a prompt."""
    names: set = set()
    try:
        from app.models.account import get_user_profile
        from app.core.users import list_users
        acc = (get_user_profile().get("user_name") or "").strip().lower()
        if acc:
            names.add(acc)
        for u in list_users():
            uname = (u.get("username") or "").strip().lower()
            if uname:
                names.add(uname)
    except Exception:
        pass
    return names


def _other_side(rel: Dict[str, Any], name: str) -> str:
    a = rel.get("character_a", "") or ""
    b = rel.get("character_b", "") or ""
    return b if a.lower() == name.lower() else a


def _drop_absent(names: List[str]) -> List[str]:
    """Omit partners no longer present in this world (the rows stay in the DB
    and come back with a re-import). A dormant character exists."""
    try:
        from app.models.character import character_exists
        return [n for n in names if character_exists(n)]
    except Exception:
        return names


def build_relationship_prompt_section(character_name: str
) -> str:
    """Build a short prompt section describing this character's relationships.

    A member of a linked family (one mind, several bodies) gets the union of
    the whole family's partners: per partner the mind's own feeling and the
    leader's own row as today, then one "as <body>" line per body row with
    that body's closeness, type and the partner's view of it (ruling R1).
    """
    from app.core.linked_characters import family_of
    family = family_of(character_name)
    if len(family) > 1:
        return _family_prompt_section(family)

    rels = [r for r in get_character_relationships(character_name)
            if visible_to(r, character_name)]
    if not rels:
        return ""

    account_names = _account_names()
    if account_names:
        rels = [r for r in rels
                if _other_side(r, character_name).lower() not in account_names]
        if not rels:
            return ""

    present = set(_drop_absent([_other_side(r, character_name) for r in rels]))
    rels = [r for r in rels if _other_side(r, character_name) in present]
    if not rels:
        return ""

    # Sort by strength descending, take top 8
    rels.sort(key=lambda r: r.get("strength", 0), reverse=True)
    rels = rels[:8]

    lines = ["\nYour relationships with other characters:"]
    for rel in rels:
        other = _other_side(rel, character_name)
        rtype = TYPE_LABELS.get(rel.get("type", "neutral"), "Known")
        strength = int(rel.get("strength", 0))
        feeling = sentiment_label(rel.get(_row_key(rel, character_name, other), 0))
        lines.append(f"- {other}: {rtype} (closeness {strength}/100, feeling: {feeling})")

    return "\n".join(lines)


def _family_prompt_section(family: List[str]) -> str:
    """The relationship section of every member of one linked family."""
    mind = family[0]
    in_family = {m.lower() for m in family}
    # partner -> {"mind": the leader's own row or None, "bodies": [(body, row)]}
    partners: Dict[str, Dict[str, Any]] = {}
    for member in family:
        for rel in get_character_relationships(member):
            other = _other_side(rel, member)
            if not other or other.lower() in in_family or not visible_to(rel, member):
                continue
            entry = partners.setdefault(other, {"mind": None, "bodies": []})
            if member == mind:
                entry["mind"] = rel
            else:
                entry["bodies"].append((member, rel))
    if not partners:
        return ""

    account_names = _account_names()
    names = [n for n in partners if n.lower() not in account_names]
    names = _drop_absent(names)
    if not names:
        return ""

    def met_in_person(rel: Optional[Dict[str, Any]]) -> bool:
        return bool(rel) and not rel.get(MIND_ONLY_KEY)

    def closeness(name: str) -> float:
        entry = partners[name]
        values = [r.get("strength", 0) or 0 for _b, r in entry["bodies"]]
        if met_in_person(entry["mind"]):
            values.append(entry["mind"].get("strength", 0) or 0)
        return max(values or [0])

    names.sort(key=lambda n: (-closeness(n), n.lower()))
    lines = ["\nYour relationships with other characters:"]
    for other in names[:8]:
        entry = partners[other]
        lead = entry["mind"]
        feeling = sentiment_label(
            lead.get(_row_key(lead, mind, other), 0) if lead else 0)
        if met_in_person(lead):
            rtype = TYPE_LABELS.get(lead.get("type", "neutral"), "Known")
            lines.append(f"- {other}: {rtype} (closeness {int(lead.get('strength', 0))}/100, "
                         f"feeling: {feeling})")
        else:
            lines.append(f"- {other} (feeling: {feeling})")
        for body, rel in sorted(entry["bodies"], key=lambda br: family.index(br[0])):
            rtype = TYPE_LABELS.get(rel.get("type", "neutral"), "Known")
            view = sentiment_label(rel.get(_row_key(rel, other, body), 0))
            lines.append(f"  - as {body}: {rtype} (closeness {int(rel.get('strength', 0))}/100), "
                         f"their view of you: {view}")
    return "\n".join(lines)
