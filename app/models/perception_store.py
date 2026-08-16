"""DB access for the perception stream (plan-room-conversation phase 1).

Two tables (schema in ``app/core/world_db_schema.py``):

- ``utterances``   — canonical truth, one row per speech act.
- ``perceptions``  — fan-out, one row per perceiver, already filtered at write
                     time.

This layer does NO earshot logic — it only writes/reads. Earshot + distribution
live in ``app/core/perception.py``, and so does the retention POLICY: the prune
below is handed a cutoff, it does not pick one.

Important for confidentiality: ``get_character_stream`` reads exclusively from
``perceptions`` (never ``utterances.content``) — whispered content can this way
never be leaked to a third party through the subjective stream.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("perception_store")


def insert_utterance(*, ts: str, speaker: str, location_id: str, room_id: str,
                     volume: str, addressees: Sequence[str], content: str,
                     meta: Optional[Dict[str, Any]] = None,
                     pos_x: Optional[float] = None,
                     pos_z: Optional[float] = None) -> int:
    """Writes one speech act and returns its id.

    ``pos_x``/``pos_z`` belong to the wilderness only: a speaker outside every
    location has no room to name, so the metre point it spoke from is what
    later tells where the line was heard. Inside a location both stay NULL —
    the ``location_id``/``room_id`` pair already answers that question.
    """
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO utterances
               (ts, speaker, location_id, room_id, volume, addressees, content,
                meta, pos_x, pos_z)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, speaker, location_id or "", room_id or "", volume,
             json.dumps(list(addressees or []), ensure_ascii=False),
             content, json.dumps(meta or {}, ensure_ascii=False),
             pos_x, pos_z),
        )
        return int(cur.lastrowid)


def insert_perceptions(utterance_id: int, rows: Sequence[Dict[str, Any]]) -> None:
    """Bulk insert of the fan-out perceptions of one speech act."""
    if not rows:
        return
    with transaction() as conn:
        conn.executemany(
            """INSERT INTO perceptions
               (perceiver, utterance_id, ts, kind, content, meta)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(r["perceiver"], utterance_id, r["ts"], r["kind"],
              r.get("content", "") or "",
              json.dumps(r.get("meta", {}) or {}, ensure_ascii=False))
             for r in rows],
        )


def utterance_exists(speaker: str, ts: str, content: str) -> bool:
    """Is there an identical speech act already? (Shadow dedup — the same
    message can be stored in several histories.)"""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM utterances WHERE speaker=? AND ts=? AND content=? LIMIT 1",
        (speaker, ts, content)).fetchone()
    return row is not None


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    if isinstance(d.get("addressees"), str):
        try:
            d["addressees"] = json.loads(d["addressees"])
        except Exception:
            d["addressees"] = []
    if isinstance(d.get("meta"), str):
        try:
            d["meta"] = json.loads(d["meta"])
        except Exception:
            d["meta"] = {}
    return d


def get_room_utterances(location_id: str, room_id: str = "",
                        limit: int = 100) -> List[Dict[str, Any]]:
    """Objective room view (god view): raw speech acts, oldest first.

    An empty ``room_id`` means the whole location (all rooms).
    """
    conn = get_connection()
    if room_id:
        rows = conn.execute(
            "SELECT * FROM utterances WHERE location_id=? AND room_id=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (location_id, room_id, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM utterances WHERE location_id=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (location_id, limit)).fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


def get_room_utterances_since(location_id: str, room_id: str,
                              after_id: int,
                              limit: int = 50) -> List[Dict[str, Any]]:
    """Speech acts of ONE room newer than ``after_id``, oldest first.

    Ordering by id, not by ts: the caller (the storyteller silence check,
    ``app/core/silence_check.py``) asks "did anything happen AFTER this
    utterance", and only the id answers that without ties — several lines can
    share a timestamp.

    Both keys are matched exactly, empty included: an empty ``location_id``
    with an empty ``room_id`` is the wilderness bucket, not a wildcard.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM utterances WHERE location_id=? AND room_id=? AND id>? "
        "ORDER BY id ASC LIMIT ?",
        (location_id or "", room_id or "", int(after_id), limit)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_character_room_stream(perceiver: str, location_id: str, room_id: str,
                              limit: int = 100,
                              include_meta_lines: bool = False
                              ) -> List[Dict[str, Any]]:
    """A character's perceptions, filtered to one room (for the player's
    scene view). Joins ``utterances`` only for the room metadata — never for
    the content (that stays already filtered in ``perceptions``).

    include_meta_lines: display-only lines (meta.display_only, e.g.
    relationship-change notes) are for the PLAYER UI only — the default
    False keeps them out of every LLM-transcript consumer; only the
    /play/scene route opts in.

    Plain room equality: the location's ground is a room like any other
    (``world.GROUND_ROOM_ID``), so it needs no rule of its own here.

    EMPTY location_id = the WILDERNESS (E6), and there the room argument is
    ignored: outside there are no rooms, and a caller reading a character's
    ``current_room`` can still be handed a stale one. What comes back are the
    location-less lines this character PERCEIVED — nothing more:

    * no additional radius filter. Earshot was decided once, when the words
      were spoken (``perception.record_utterance``). Filtering again at read
      time by the CURRENT distance would delete what a character heard two
      steps ago the moment it walks on — a conversation while walking would
      erase itself. Heard is heard.
    * still a JOIN over ``perceptions``, so nothing reaches a character that
      it did not perceive; whispered content stays empty exactly as in a room.
    """
    conn = get_connection()
    # Include u.volume (whisper/normal/shout) — NOT secret content, just the
    # volume; the content itself stays filtered in p.content (whisper_meta = empty).
    if location_id:
        rows = conn.execute(
            "SELECT p.*, u.volume AS volume FROM perceptions p "
            "JOIN utterances u ON u.id = p.utterance_id "
            "WHERE p.perceiver=? AND u.location_id=? AND u.room_id=? "
            "ORDER BY p.ts DESC, p.id DESC LIMIT ?",
            (perceiver, location_id, room_id, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.*, u.volume AS volume FROM perceptions p "
            "JOIN utterances u ON u.id = p.utterance_id "
            "WHERE p.perceiver=? AND u.location_id='' "
            "ORDER BY p.ts DESC, p.id DESC LIMIT ?",
            (perceiver, limit)).fetchall()
    out = [_row_to_dict(r) for r in reversed(rows)]
    if not include_meta_lines:
        out = [r for r in out if not ((r.get("meta") or {}).get("display_only"))]
    return out


def get_followed_conversation_tail(perceiver: str, partner: str,
                                   cur_location_id: str, cur_room_id: str,
                                   limit: int = 20,
                                   max_age_min: int = 15) -> List[Dict[str, Any]]:
    """Carry the conversation along when FOLLOWING directly
    (plan-follow-room-conversation-bug B).

    Returns the tail of the round from the room ``perceiver`` was in
    IMMEDIATELY before the current one — but only if ``partner`` took part in
    it (= a direct follow with no other location in between). Otherwise ``[]``.

    Same return shape as ``get_character_room_stream`` (oldest first), so the
    caller can chain both streams seamlessly.

    Asymmetric towards the wilderness (E6), and deliberately so: whoever steps
    from a location into the open takes the thread along (the previous round
    has a location), whoever enters a location from the open does not — the
    location-less previous round drops out at the ``prior[0]`` check, because
    out there is no room key it could hang on.
    """
    if not (perceiver and partner and cur_location_id is not None):
        return []
    conn = get_connection()
    rows = conn.execute(
        "SELECT u.location_id AS loc, u.room_id AS room, u.speaker AS speaker, p.ts AS ts "
        "FROM perceptions p JOIN utterances u ON u.id = p.utterance_id "
        "WHERE p.perceiver=? ORDER BY p.ts DESC, p.id DESC LIMIT 120",
        (perceiver,)).fetchall()
    cur = (cur_location_id or "", cur_room_id or "")
    prior = None          # (loc, room) of the immediately previous round
    newest_ts = ""
    for r in rows:
        key = (r["loc"] or "", r["room"] or "")
        if key != cur:
            prior = key
            newest_ts = r["ts"] or ""
            break
    if not prior or not prior[0]:
        return []
    # The partner must have spoken in exactly that previous round.
    block = [r for r in rows if (r["loc"] or "", r["room"] or "") == prior]
    if not any((r["speaker"] or "") == partner for r in block):
        return []
    # Recency cap: the previous round must not be ancient.
    try:
        from app.core.timeutils import utc_now, parse_iso
        if newest_ts and (utc_now() - parse_iso(newest_ts)).total_seconds() > max_age_min * 60:
            return []
    except Exception:
        pass
    return get_character_room_stream(perceiver, prior[0], prior[1], limit=limit)


def get_character_stream(perceiver: str, limit: int = 100,
                         before: Optional[str] = None) -> List[Dict[str, Any]]:
    """A character's subjective perception stream, oldest first.

    Reads ONLY ``perceptions`` — never the canonical content from
    ``utterances``.
    """
    conn = get_connection()
    if before:
        rows = conn.execute(
            "SELECT * FROM perceptions WHERE perceiver=? AND ts<? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (perceiver, before, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM perceptions WHERE perceiver=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (perceiver, limit)).fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


def prune_wilderness_rows(cutoff_ts: str) -> Tuple[int, int]:
    """Delete LOCATION-LESS speech acts older than ``cutoff_ts`` together with
    their perceptions. Returns ``(utterances, perceptions)`` deleted.

    Why only the location-less ones: a located line is bounded by its scene —
    consolidation summarises it into the participants' memories and
    ``scene_store.prune_scene_perceptions`` drops the raw rows. Out in the open
    there is no scene (``scene_manager.touch`` skips it), so nothing ever ends
    those rows. WHEN they end is not this layer's call — the cutoff comes from
    ``scene_manager.prune_wilderness_stream``.

    Perceptions first, utterances second: the FK cascade is not relied upon
    (``PRAGMA foreign_keys`` is not guaranteed to be on for this connection),
    and doing it in one transaction means a half prune cannot leave orphans.
    The ``(location_id, room_id, ts)`` index serves the subquery.
    """
    if not cutoff_ts:
        return (0, 0)
    with transaction() as conn:
        cur_p = conn.execute(
            "DELETE FROM perceptions WHERE utterance_id IN ("
            "  SELECT id FROM utterances WHERE location_id='' AND ts<?)",
            (cutoff_ts,))
        n_p = cur_p.rowcount or 0
        cur_u = conn.execute(
            "DELETE FROM utterances WHERE location_id='' AND ts<?", (cutoff_ts,))
        return (cur_u.rowcount or 0, n_p)


def migrate_storyteller_speaker_once() -> None:
    """One-time, idempotent rename of the legacy narrator-speaker sentinel to the
    canonical ``perception.STORYTELLER_SPEAKER`` ("Storyteller") wherever it was
    persisted: ``utterances.speaker``, ``perceptions.meta.speaker``,
    ``scenes.participants`` and ``chat_messages.metadata.speaker``.

    Runs per world at boot, guarded by a world_kv marker. This is the ONLY place
    that still names the old value — it replaces the old rows outright (no
    backward-compat reader is kept; new code compares only STORYTELLER_SPEAKER).
    """
    legacy = "Erz" + "ähler"  # legacy German sentinel, migration-only
    new = "Storyteller"
    try:
        from app.models.world import get_world_setting, set_world_setting
    except Exception:
        return
    if get_world_setting("migration.storyteller_speaker_v1", "") == "done":
        return
    try:
        with transaction() as conn:
            conn.execute("UPDATE utterances SET speaker=? WHERE speaker=?", (new, legacy))
            conn.execute(
                "UPDATE perceptions SET meta=json_set(meta,'$.speaker',?) "
                "WHERE json_valid(meta) AND json_extract(meta,'$.speaker')=?",
                (new, legacy))
            conn.execute(
                "UPDATE scenes SET participants=replace(participants,?,?) "
                "WHERE participants LIKE ?",
                (f'"{legacy}"', f'"{new}"', f'%"{legacy}"%'))
            conn.execute(
                "UPDATE chat_messages SET metadata=json_set(metadata,'$.speaker',?) "
                "WHERE json_valid(metadata) AND json_extract(metadata,'$.speaker')=?",
                (new, legacy))
        set_world_setting("migration.storyteller_speaker_v1", "done")
        logger.info("storyteller-speaker migration applied (%s -> %s)", legacy, new)
    except Exception as e:
        logger.warning("storyteller-speaker migration failed: %s", e)
