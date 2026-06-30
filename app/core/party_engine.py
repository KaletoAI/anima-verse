"""Party-System — gemeinsam reisen.

Eine Party hat genau einen *Leader* und N *Follower*. Nur der Leader bewegt sich
selbst; Follower verlieren SetLocation/Move (NPC) bzw. den Kompass (Avatar) und
werden beim Zug des Leaders mitgezogen (siehe ``save_character_current_location``
/ ``save_character_current_room`` in app/models/character.py). Verlassen ist
jederzeit moeglich; verlaesst der Leader, loest sich die Party auf.

Mitgliedschaft liegt in world.db (Tabelle ``parties``, Schema in
world_db_schema.py). Ein Character ist in hoechstens einer Party.

Siehe development_instructions/plan-party-system.md.
"""
from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger("party")


def _row_to_party(row) -> Dict:
    try:
        members = json.loads(row[2] or "[]")
    except Exception:
        members = []
    return {
        "party_id": row[0],
        "leader": row[1],
        "members": [m for m in members if isinstance(m, str)],
        "created_at": row[3],
    }


def _all_parties() -> List[Dict]:
    try:
        rows = get_connection().execute(
            "SELECT party_id, leader, members, created_at FROM parties").fetchall()
    except Exception:
        return []
    return [_row_to_party(r) for r in rows]


def get_party(party_id: str) -> Optional[Dict]:
    if not party_id:
        return None
    try:
        row = get_connection().execute(
            "SELECT party_id, leader, members, created_at FROM parties WHERE party_id=?",
            (party_id,)).fetchone()
    except Exception:
        return None
    return _row_to_party(row) if row else None


def get_party_of(character: str) -> Optional[Dict]:
    """Party, in der ``character`` Leader ODER Follower ist — inkl. ``role``-Feld
    ("leader"/"follower"). None, wenn er in keiner Party ist."""
    c = (character or "").strip()
    if not c:
        return None
    for p in _all_parties():
        if p["leader"] == c:
            return {**p, "role": "leader"}
        if c in p["members"]:
            return {**p, "role": "follower"}
    return None


def is_in_party(character: str) -> bool:
    return get_party_of(character) is not None


def is_party_leader(character: str) -> bool:
    p = get_party_of(character)
    return bool(p and p["role"] == "leader")


def is_party_follower(character: str) -> bool:
    p = get_party_of(character)
    return bool(p and p["role"] == "follower")


def party_followers(leader: str) -> List[str]:
    """Follower-Liste der Party, die ``leader`` anfuehrt. [] wenn ``leader`` keine
    Party anfuehrt (z.B. selbst Follower oder partylos)."""
    p = get_party_of(leader)
    if not p or p["role"] != "leader":
        return []
    return list(p["members"])


def _save_party(party_id: str, leader: str, members: List[str], created_at: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parties (party_id, leader, members, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(party_id) DO UPDATE SET "
            "leader=excluded.leader, members=excluded.members",
            (party_id, leader, json.dumps(members, ensure_ascii=False), created_at))


def add_to_party(leader: str, member: str) -> Optional[str]:
    """Fuegt ``member`` als Follower zur Party von ``leader`` hinzu; legt die Party
    an, falls ``leader`` noch keine hat. Gibt die party_id zurueck oder None bei
    Konflikt (member schon in einer Party, leader ist selbst Follower, oder
    leader == member)."""
    leader = (leader or "").strip()
    member = (member or "").strip()
    if not leader or not member or leader == member:
        return None
    if get_party_of(member) is not None:
        return None  # member kann nicht in zwei Parties sein
    lp = get_party_of(leader)
    if lp is not None and lp["role"] == "follower":
        return None  # ein Follower kann nicht selbst einladen
    if lp is None:
        party_id = "party_" + uuid.uuid4().hex[:10]
        created = utc_now_iso()
        members = [member]
    else:
        party_id = lp["party_id"]
        created = lp["created_at"]
        members = list(lp["members"])
        if member not in members:
            members.append(member)
    _save_party(party_id, leader, members, created)
    logger.info("Party %s: %s wird Follower von %s (members=%s)",
                party_id, member, leader, members)
    return party_id


def leave_party(character: str) -> Dict:
    """Entfernt ``character`` aus seiner Party.

    - Leader verlaesst -> Party loest sich auf (alle Follower frei).
    - Letzter Follower weg -> Party loest sich auf (keine 1-Personen-Party).

    Returns ``{"status", "party_id", "disbanded", "freed": [...]}`` oder
    ``{"status": "not_in_party"}``.
    """
    p = get_party_of(character)
    if not p:
        return {"status": "not_in_party"}
    pid = p["party_id"]
    if p["role"] == "leader":
        disband_party(pid)
        return {"status": "ok", "party_id": pid, "disbanded": True,
                "freed": [p["leader"], *p["members"]]}
    members = [m for m in p["members"] if m != character]
    if not members:
        disband_party(pid)
        return {"status": "ok", "party_id": pid, "disbanded": True,
                "freed": [p["leader"], character]}
    _save_party(pid, p["leader"], members, p["created_at"])
    return {"status": "ok", "party_id": pid, "disbanded": False, "freed": [character]}


def disband_party(party_id: str) -> None:
    if not party_id:
        return
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM parties WHERE party_id=?", (party_id,))
        logger.info("Party %s aufgeloest", party_id)
    except Exception as e:
        logger.debug("disband_party(%s) fehlgeschlagen: %s", party_id, e)
