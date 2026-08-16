"""DB access for scenes (plan-room-conversation §7).

A scene = one connected run of perception in a room. There is at most ONE open
scene per room; every utterance touches it (last_activity + participants). Once
the room falls silent (idle), the loop closes the scene, consolidates its raw
perceptions into a summary and prunes the perceptions.

This layer only reads/writes — idle detection + consolidation live in
``app/core/scene_manager.py``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("scene_store")


def _row(r) -> Dict[str, Any]:
    d = dict(r)
    if isinstance(d.get("participants"), str):
        try:
            d["participants"] = json.loads(d["participants"])
        except Exception:
            d["participants"] = []
    return d


def get_recent_scenes_for(character_name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Most recently consolidated scenes the character took part in — for the
    "the story so far" recap bar in the chat. Newest first."""
    if not character_name:
        return []
    conn = get_connection()
    # The name sits in participants as a JSON string (with quotes) → rough LIKE
    # pre-filter, then an exact check against the parsed list.
    like = f"%{json.dumps(character_name, ensure_ascii=False)}%"
    rows = conn.execute(
        "SELECT * FROM scenes WHERE status='consolidated' AND summary != '' "
        "AND participants LIKE ? ORDER BY last_activity_ts DESC LIMIT ?",
        (like, max(1, limit) * 3)).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = _row(r)
        if character_name in (d.get("participants") or []):
            out.append(d)
        if len(out) >= limit:
            break
    return out


def touch_scene(location_id: str, room_id: str, speaker: str, ts: str) -> int:
    """Opens the room's scene or refreshes it (last_activity + participants).
    Returns the scene id. No scene without a location."""
    if not location_id:
        return 0
    room_id = room_id or ""
    with transaction() as conn:
        row = conn.execute(
            "SELECT id, participants FROM scenes WHERE status='open' AND "
            "location_id=? AND room_id=? ORDER BY id DESC LIMIT 1",
            (location_id, room_id)).fetchone()
        if row:
            sid = row["id"]
            parts = []
            try:
                parts = json.loads(row["participants"]) or []
            except Exception:
                parts = []
            if speaker and speaker not in parts:
                parts.append(speaker)
            conn.execute(
                "UPDATE scenes SET last_activity_ts=?, participants=? WHERE id=?",
                (ts, json.dumps(parts, ensure_ascii=False), sid))
            return int(sid)
        cur = conn.execute(
            "INSERT INTO scenes (location_id, room_id, started_ts, last_activity_ts, "
            "participants, status) VALUES (?, ?, ?, ?, ?, 'open')",
            (location_id, room_id, ts, ts,
             json.dumps([speaker] if speaker else [], ensure_ascii=False)))
        return int(cur.lastrowid)


def get_open_scene(location_id: str, room_id: str) -> Optional[Dict[str, Any]]:
    """The currently open scene of a room (or None)."""
    if not location_id:
        return None
    conn = get_connection()
    r = conn.execute(
        "SELECT * FROM scenes WHERE status='open' AND location_id=? AND room_id=? "
        "ORDER BY id DESC LIMIT 1", (location_id, room_id or "")).fetchone()
    return _row(r) if r else None


def get_idle_open_scenes(cutoff_ts: str) -> List[Dict[str, Any]]:
    """Open scenes whose last activity is older than ``cutoff_ts`` (ebbed away)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scenes WHERE status='open' AND last_activity_ts < ? "
        "ORDER BY last_activity_ts", (cutoff_ts,)).fetchall()
    return [_row(r) for r in rows]


def get_aged_open_scenes(cutoff_ts: str) -> List[Dict[str, Any]]:
    """Open scenes that STARTED before ``cutoff_ts`` — the age half of the
    safety net (``memory.scene_max_hours``).

    Deliberately looks at ``started_ts``, not ``last_activity_ts``: a room with
    constant traffic refreshes its last activity with every utterance and would
    never show up in :func:`get_idle_open_scenes`. Same string comparison on the
    same ISO/UTC stamps as the idle query.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scenes WHERE status='open' AND started_ts < ? "
        "ORDER BY started_ts", (cutoff_ts,)).fetchall()
    return [_row(r) for r in rows]


# Perceptions of a scene = the perceptions of the utterances in the scene's
# room and time window — the exact set ``prune_scene_perceptions`` deletes.
_SCENE_PERCEPTION_COUNT_SQL = """
    SELECT COUNT(*) FROM perceptions p WHERE p.utterance_id IN (
        SELECT u.id FROM utterances u
        WHERE u.location_id = s.location_id AND u.room_id = s.room_id
          AND u.ts >= s.started_ts AND u.ts <= s.last_activity_ts)
"""


def get_oversized_open_scenes(min_perceptions: int) -> List[Dict[str, Any]]:
    """Open scenes holding at least ``min_perceptions`` raw perceptions — the
    size half of the safety net (``memory.scene_max_perceptions``).

    Each row carries an extra ``perception_count`` key.
    """
    if min_perceptions <= 0:
        return []
    conn = get_connection()
    rows = conn.execute(
        f"SELECT * FROM (SELECT s.*, ({_SCENE_PERCEPTION_COUNT_SQL}) AS perception_count "
        "FROM scenes s WHERE s.status='open') WHERE perception_count >= ? "
        "ORDER BY perception_count DESC", (min_perceptions,)).fetchall()
    return [_row(r) for r in rows]


def mark_consolidated(scene_id: int, summary: str) -> None:
    with transaction() as conn:
        conn.execute("UPDATE scenes SET status='consolidated', summary=? WHERE id=?",
                     (summary, scene_id))


def get_scene_utterances(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Raw utterances of a scene (room + time window started..last_activity)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, ts, speaker, addressees, content FROM utterances "
        "WHERE location_id=? AND room_id=? AND ts>=? AND ts<=? ORDER BY id",
        (scene["location_id"], scene.get("room_id", ""),
         scene["started_ts"], scene["last_activity_ts"])).fetchall()
    return [dict(r) for r in rows]


def prune_scene_perceptions(scene: Dict[str, Any]) -> int:
    """Drops the raw perceptions of a consolidated scene (room + time window).
    Utterances (the canonical truth) stay for the observer/god view."""
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM perceptions WHERE utterance_id IN ("
            "  SELECT id FROM utterances WHERE location_id=? AND room_id=? "
            "  AND ts>=? AND ts<=?)",
            (scene["location_id"], scene.get("room_id", ""),
             scene["started_ts"], scene["last_activity_ts"]))
        return cur.rowcount or 0
