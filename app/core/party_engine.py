"""Party-System — gemeinsam reisen.

Eine Party hat genau einen *Leader* und N *Follower*. Nur der Leader bewegt sich
selbst; Follower verlieren SetLocation (NPC) bzw. den Kompass (Avatar) und
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


def same_location(a: str, b: str) -> bool:
    """True when both characters stand at the same location.

    A party is formed face to face — you cannot invite or join across the map
    (same rule TalkTo enforces). Without this brake an LLM that hallucinates a
    person into its scene can pull a character from anywhere in the world into
    its party, and the leader-move drag would then teleport them over.
    An unknown location counts as "not together".
    """
    from app.models.character import get_character_current_location
    loc_a = (get_character_current_location(a) or "").strip()
    loc_b = (get_character_current_location(b) or "").strip()
    return bool(loc_a) and loc_a == loc_b


def _save_party(party_id: str, leader: str, members: List[str], created_at: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parties (party_id, leader, members, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(party_id) DO UPDATE SET "
            "leader=excluded.leader, members=excluded.members",
            (party_id, leader, json.dumps(members, ensure_ascii=False), created_at))


def add_to_party(leader: str, member: str) -> Optional[str]:
    """Adds ``member`` as a follower to ``leader``'s party; creates the party if
    ``leader`` has none yet. Returns the party_id, or None on conflict (member
    already in a party, leader is a follower himself, leader == member, or the
    two are not at the same location)."""
    leader = (leader or "").strip()
    member = (member or "").strip()
    if not leader or not member or leader == member:
        return None
    if not same_location(leader, member):
        return None  # central brake: no party across locations
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
    # A follower does not travel on its own account — it is dragged along by
    # the leader, and it loses SetLocation with the join. Its own journey has
    # to end HERE, at the one choke point every join passes (the JoinParty
    # verb AND the avatar's accepted invite): the travel ticker only cancels
    # follower journeys while the LEADER is on the road, so a joiner whose
    # leader stands still would keep walking away from the party it just
    # joined.
    try:
        from app.core.travel_engine import cancel_journey, get_journey
        if get_journey(member) is not None:
            cancel_journey(member)
    except Exception as e:
        logger.debug("journey cancel on party join failed for %s: %s",
                     member, e)
    logger.info("Party %s: %s becomes a follower of %s (members=%s)",
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


# --- Pending-Einladungen (NPC laedt Avatar ein) ---------------------------

def create_pending_invite(inviter: str, invitee: str) -> Optional[str]:
    """Legt eine offene Einladung an (NPC -> Avatar). Verwirft bestehende
    pending-Einladungen desselben Paars vorher (kein Stau). Gibt invite_id."""
    inviter = (inviter or "").strip()
    invitee = (invitee or "").strip()
    if not inviter or not invitee or inviter == invitee:
        return None
    invite_id = "pinv_" + uuid.uuid4().hex[:10]
    try:
        with transaction() as conn:
            conn.execute(
                "DELETE FROM party_invites WHERE inviter=? AND invitee=? AND status='pending'",
                (inviter, invitee))
            conn.execute(
                "INSERT INTO party_invites (invite_id, inviter, invitee, created_at, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (invite_id, inviter, invitee, utc_now_iso()))
    except Exception as e:
        logger.debug("create_pending_invite fehlgeschlagen: %s", e)
        return None
    logger.info("Party-Einladung %s: %s -> %s (pending)", invite_id, inviter, invitee)
    return invite_id


def get_pending_invites_for(invitee: str) -> List[Dict]:
    """Open invitations for ``invitee`` (for the UI question).

    Invitations from someone who is no longer at the same location are dropped
    from the list: accepting them would fail anyway, so the UI must not offer a
    dead Join button."""
    invitee = (invitee or "").strip()
    if not invitee:
        return []
    try:
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, created_at FROM party_invites "
            "WHERE invitee=? AND status='pending' ORDER BY created_at ASC",
            (invitee,)).fetchall()
    except Exception:
        return []
    return [{"invite_id": r[0], "inviter": r[1], "invitee": r[2], "created_at": r[3]}
            for r in rows if same_location(r[1], invitee)]


def get_invite(invite_id: str) -> Optional[Dict]:
    if not invite_id:
        return None
    try:
        r = get_connection().execute(
            "SELECT invite_id, inviter, invitee, created_at, status FROM party_invites "
            "WHERE invite_id=?", (invite_id,)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    return {"invite_id": r[0], "inviter": r[1], "invitee": r[2],
            "created_at": r[3], "status": r[4]}


def resolve_pending_invite(invite_id: str, accept: bool) -> Dict:
    """Beantwortet eine Pending-Einladung. Bei Ja -> invitee tritt der Party des
    inviter bei. Markiert die Row als accepted/declined. Returns Status-Dict."""
    inv = get_invite(invite_id)
    if not inv or inv["status"] != "pending":
        return {"status": "not_found"}
    if accept and not same_location(inv["inviter"], inv["invitee"]):
        # The inviter has moved on in the meantime (or was never here) — say so
        # instead of failing with a generic conflict.
        return {"status": "not_present", "inviter": inv["inviter"],
                "invitee": inv["invitee"]}
    try:
        with transaction() as conn:
            conn.execute("UPDATE party_invites SET status=? WHERE invite_id=?",
                         ("accepted" if accept else "declined", invite_id))
    except Exception as e:
        logger.debug("resolve_pending_invite update fehlgeschlagen: %s", e)
    if not accept:
        return {"status": "declined", "inviter": inv["inviter"], "invitee": inv["invitee"]}
    pid = add_to_party(inv["inviter"], inv["invitee"])
    if not pid:
        return {"status": "join_conflict", "inviter": inv["inviter"], "invitee": inv["invitee"]}
    return {"status": "accepted", "party_id": pid,
            "inviter": inv["inviter"], "invitee": inv["invitee"]}


def clear_invites_for(character: str) -> None:
    """Verwirft alle offenen Einladungen, an denen ``character`` beteiligt ist
    (z.B. wenn er einer Party beitritt oder eine verlaesst)."""
    c = (character or "").strip()
    if not c:
        return
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE party_invites SET status='stale' WHERE status='pending' "
                "AND (inviter=? OR invitee=?)", (c, c))
    except Exception as e:
        logger.debug("clear_invites_for(%s) fehlgeschlagen: %s", c, e)
