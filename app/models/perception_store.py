"""DB-Zugriff fuer den Wahrnehmungs-Stream (plan-room-conversation Phase 1).

Zwei Tabellen (Schema in ``app/core/world_db_schema.py``):

- ``utterances``   — kanonische Wahrheit, eine Zeile pro Sprechakt.
- ``perceptions``  — Fan-Out, eine Zeile pro Wahrnehmendem, beim Schreiben
                     bereits gefiltert.

Diese Schicht macht KEINE Hoerweite-Logik — sie schreibt/liest nur. Hoerweite +
Verteilung liegen in ``app/core/perception.py``.

Wichtig fuer die Vertraulichkeit: ``get_character_stream`` liest ausschliesslich
aus ``perceptions`` (nie ``utterances.content``) — gefluesterter Inhalt kann so
einem Dritten nie ueber den subjektiven Stream zugespielt werden.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("perception_store")


def insert_utterance(*, ts: str, speaker: str, location_id: str, room_id: str,
                     volume: str, addressees: Sequence[str], content: str,
                     meta: Optional[Dict[str, Any]] = None) -> int:
    """Schreibt einen Sprechakt und gibt seine id zurueck."""
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO utterances
               (ts, speaker, location_id, room_id, volume, addressees, content, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, speaker, location_id or "", room_id or "", volume,
             json.dumps(list(addressees or []), ensure_ascii=False),
             content, json.dumps(meta or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def insert_perceptions(utterance_id: int, rows: Sequence[Dict[str, Any]]) -> None:
    """Bulk-Insert der Fan-Out-Wahrnehmungen zu einem Sprechakt."""
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
    """Gibt es schon einen identischen Sprechakt? (Shadow-Dedup — dieselbe
    Nachricht kann in mehreren Historien gespeichert werden.)"""
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
    """Objektive Raum-Sicht (Gott-Sicht): rohe Sprechakte, aelteste zuerst.

    Bei leerem ``room_id`` die ganze Location (alle Raeume).
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


def get_character_room_stream(perceiver: str, location_id: str, room_id: str,
                              limit: int = 100,
                              include_meta_lines: bool = False
                              ) -> List[Dict[str, Any]]:
    """Wahrnehmungen eines Characters, gefiltert auf einen Raum (fuer die
    Player-Szenen-Ansicht). Join auf ``utterances`` nur fuer die Raum-Metadaten —
    nie fuer den Inhalt (der bleibt in ``perceptions`` schon gefiltert).

    include_meta_lines: display-only lines (meta.display_only, e.g.
    relationship-change notes) are for the PLAYER UI only — the default
    False keeps them out of every LLM-transcript consumer; only the
    /play/scene route opts in."""
    conn = get_connection()
    # u.volume mitliefern (whisper/normal/shout) — KEIN geheimer Inhalt, nur die
    # Lautstärke; der Inhalt bleibt in p.content schon gefiltert (whisper_meta = leer).
    rows = conn.execute(
        "SELECT p.*, u.volume AS volume FROM perceptions p "
        "JOIN utterances u ON u.id = p.utterance_id "
        "WHERE p.perceiver=? AND u.location_id=? AND u.room_id=? "
        "ORDER BY p.ts DESC, p.id DESC LIMIT ?",
        (perceiver, location_id, room_id, limit)).fetchall()
    out = [_row_to_dict(r) for r in reversed(rows)]
    if not include_meta_lines:
        out = [r for r in out if not ((r.get("meta") or {}).get("display_only"))]
    return out


def get_followed_conversation_tail(perceiver: str, partner: str,
                                   cur_location_id: str, cur_room_id: str,
                                   limit: int = 20,
                                   max_age_min: int = 15) -> List[Dict[str, Any]]:
    """Gespräch beim DIREKTEN Folgen mitnehmen (plan-follow-room-conversation-bug B).

    Liefert den Tail der Runde aus dem Raum, in dem ``perceiver`` UNMITTELBAR
    vor dem aktuellen war — aber nur, wenn ``partner`` dort beteiligt war
    (= direkter Follow ohne andere Location dazwischen). Sonst ``[]``.

    Rückgabe identisch zu ``get_character_room_stream`` (älteste zuerst), damit
    der Aufrufer beide Streams nahtlos verketten kann.
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
    prior = None          # (loc, room) der unmittelbar vorherigen Runde
    newest_ts = ""
    for r in rows:
        key = (r["loc"] or "", r["room"] or "")
        if key != cur:
            prior = key
            newest_ts = r["ts"] or ""
            break
    if not prior or not prior[0]:
        return []
    # Partner muss in genau dieser vorherigen Runde gesprochen haben.
    block = [r for r in rows if (r["loc"] or "", r["room"] or "") == prior]
    if not any((r["speaker"] or "") == partner for r in block):
        return []
    # Aktualitäts-Cap: die vorherige Runde darf nicht uralt sein.
    try:
        from app.core.timeutils import utc_now, parse_iso
        if newest_ts and (utc_now() - parse_iso(newest_ts)).total_seconds() > max_age_min * 60:
            return []
    except Exception:
        pass
    return get_character_room_stream(perceiver, prior[0], prior[1], limit=limit)


def get_character_stream(perceiver: str, limit: int = 100,
                         before: Optional[str] = None) -> List[Dict[str, Any]]:
    """Subjektiver Wahrnehmungs-Stream eines Characters, aelteste zuerst.

    Liest NUR ``perceptions`` — nie den kanonischen Inhalt aus ``utterances``.
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
