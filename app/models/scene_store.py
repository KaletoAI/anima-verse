"""DB-Zugriff für Szenen (plan-room-conversation §7).

Eine Szene = zusammenhängender Wahrnehmungs-Lauf in einem Raum. Pro Raum gibt es
höchstens EINE offene Szene; sie wird bei jeder Äußerung getoucht (last_activity +
Teilnehmer). Verstummt der Raum (Idle), schließt der Loop die Szene, konsolidiert
ihre Roh-Wahrnehmungen in eine Summary und prunt die Perceptions.

Diese Schicht schreibt/liest nur — Idle-Erkennung + Konsolidierung liegen in
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


def touch_scene(location_id: str, room_id: str, speaker: str, ts: str) -> int:
    """Öffnet die Szene des Raums oder aktualisiert sie (last_activity + Teilnehmer).
    Gibt die scene-id zurück. Keine Szene ohne Location."""
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
    """Die aktuell offene Szene eines Raums (oder None)."""
    if not location_id:
        return None
    conn = get_connection()
    r = conn.execute(
        "SELECT * FROM scenes WHERE status='open' AND location_id=? AND room_id=? "
        "ORDER BY id DESC LIMIT 1", (location_id, room_id or "")).fetchone()
    return _row(r) if r else None


def get_idle_open_scenes(cutoff_ts: str) -> List[Dict[str, Any]]:
    """Offene Szenen, deren letzte Aktivität älter als ``cutoff_ts`` ist (verebbt)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scenes WHERE status='open' AND last_activity_ts < ? "
        "ORDER BY last_activity_ts", (cutoff_ts,)).fetchall()
    return [_row(r) for r in rows]


def mark_consolidated(scene_id: int, summary: str) -> None:
    with transaction() as conn:
        conn.execute("UPDATE scenes SET status='consolidated', summary=? WHERE id=?",
                     (summary, scene_id))


def get_scene_utterances(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Roh-Äußerungen einer Szene (Raum + Zeitfenster started..last_activity)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, ts, speaker, addressees, content FROM utterances "
        "WHERE location_id=? AND room_id=? AND ts>=? AND ts<=? ORDER BY id",
        (scene["location_id"], scene.get("room_id", ""),
         scene["started_ts"], scene["last_activity_ts"])).fetchall()
    return [dict(r) for r in rows]


def prune_scene_perceptions(scene: Dict[str, Any]) -> int:
    """Verwirft die Roh-Perceptions einer konsolidierten Szene (Raum + Zeitfenster).
    Utterances (kanonische Wahrheit) bleiben für die Beobachter-/Gott-Sicht."""
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM perceptions WHERE utterance_id IN ("
            "  SELECT id FROM utterances WHERE location_id=? AND room_id=? "
            "  AND ts>=? AND ts<=?)",
            (scene["location_id"], scene.get("room_id", ""),
             scene["started_ts"], scene["last_activity_ts"]))
        return cur.rowcount or 0
