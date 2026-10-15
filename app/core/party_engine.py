"""Persisted party membership and invitations.

A party has one leader and followers, who follow the leader's authoritative
location/room writes. Membership changes are serialized; invitation acceptance
and membership insertion commit together. Packages may attach an intent and
supply its consent continuation through the generic provider registry.
"""
from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.hooks import emit, get_provider
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now, utc_now_iso

logger = get_logger("party")
INVITE_MAX_AGE_MINUTES = 30


def _row_to_party(row) -> Dict:
    try:
        members = json.loads(row[2] or "[]")
    except (ValueError, TypeError):
        members = []
    return {"party_id": row[0], "leader": row[1],
            "members": [m for m in members if isinstance(m, str)],
            "created_at": row[3]}


def _all_parties() -> List[Dict]:
    rows = get_connection().execute(
        "SELECT party_id, leader, members, created_at FROM parties").fetchall()
    return [_row_to_party(r) for r in rows]


def get_party_of(character: str) -> Optional[Dict]:
    """Return the character's party with its leader/follower role."""
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
    return bool((get_party_of(character) or {}).get("role") == "leader")


def is_party_follower(character: str) -> bool:
    return bool((get_party_of(character) or {}).get("role") == "follower")


def party_followers(leader: str) -> List[str]:
    p = get_party_of(leader)
    return list(p["members"]) if p and p["role"] == "leader" else []


def same_location(a: str, b: str) -> bool:
    """Parties form face to face, never across an unknown location."""
    from app.models.character import get_character_current_location
    loc_a = (get_character_current_location(a) or "").strip()
    loc_b = (get_character_current_location(b) or "").strip()
    return bool(loc_a) and loc_a == loc_b


def _write_member(conn, leader: str, member: str) -> Optional[str]:
    """Membership mutation inside the caller's transaction and membership lock."""
    if not leader or not member or leader == member or not same_location(leader, member):
        return None
    if get_party_of(member):
        return None
    lp = get_party_of(leader)
    if lp and lp["role"] == "follower":
        return None
    pid = lp["party_id"] if lp else "party_" + uuid.uuid4().hex[:10]
    created = lp["created_at"] if lp else utc_now_iso()
    members = [*(lp["members"] if lp else []), member]
    conn.execute(
        "INSERT INTO parties (party_id, leader, members, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(party_id) DO UPDATE SET members=excluded.members",
        (pid, leader, json.dumps(members, ensure_ascii=False), created))
    return pid


def _cancel_joiner_journey(member: str) -> None:
    from app.core.travel_engine import cancel_journey, get_journey
    if get_journey(member):
        cancel_journey(member)


def add_to_party(leader: str, member: str) -> Optional[str]:
    """Add a present follower, creating a party if needed; reject conflicts."""
    with keyed_lock("party_membership", "world"):
        from app.core import sync_topics
        before = sync_topics.party_of(leader).names
        stored_tx_1 = False
        with transaction() as conn:
            pid = _write_member(conn, (leader or "").strip(), (member or "").strip())
            stored_tx_1 = True
        if pid:
            _cancel_joiner_journey(member)
    if pid:
        from app.core import sync_topics
        if stored_tx_1:
            sync_topics.avatars([*before, *sync_topics.party_of(leader).names, leader, member], ("presence", "notices"))
    return pid


def leave_party(character: str) -> Dict:
    """Leave freely; a leader leaving or last follower leaving disbands."""
    with keyed_lock("party_membership", "world"):
        p = get_party_of(character)
        if not p:
            return {"status": "not_in_party"}
        members = [m for m in p["members"] if m != character]
        disbanded = p["role"] == "leader" or not members
        stored_tx_1 = False
        with transaction() as conn:
            if disbanded:
                conn.execute("DELETE FROM parties WHERE party_id=?", (p["party_id"],))
            else:
                conn.execute("UPDATE parties SET members=? WHERE party_id=?",
                             (json.dumps(members, ensure_ascii=False), p["party_id"]))
            stored_tx_1 = True
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([p["leader"], *p["members"]], ("presence", "notices"))
    emit("party_membership_changed", party=p, character=character, reason="left")
    return {"status": "ok", "party_id": p["party_id"], "disbanded": disbanded,
            "freed": [p["leader"], *p["members"]] if disbanded else [character]}


def disband_party(party_id: str) -> None:
    with keyed_lock("party_membership", "world"):
        p = next((p for p in _all_parties() if p["party_id"] == party_id), None)
        if not p:
            return
        stored_tx_1 = False
        with transaction() as conn:
            conn.execute("DELETE FROM parties WHERE party_id=?", (party_id,))
            stored_tx_1 = True
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([p["leader"], *p["members"]], ("presence", "notices"))
    emit("party_membership_changed", party=p, character=p["leader"], reason="disbanded")


def _row_to_invite(row) -> Dict:
    return {"invite_id": row[0], "inviter": row[1], "invitee": row[2],
            "created_at": row[3], "status": row[4], "intent_id": row[5] or ""}


def invite_is_fresh(invite: Dict, max_age_minutes: int = INVITE_MAX_AGE_MINUTES) -> bool:
    try:
        return (utc_now() - parse_iso(invite["created_at"])).total_seconds() <= max_age_minutes * 60
    except (ValueError, TypeError, KeyError):
        return False


def create_pending_invite(inviter: str, invitee: str, intent_id: str = "") -> Optional[str]:
    """Persist a question; a linked intent gets one idempotent invitation."""
    inviter, invitee = (inviter or "").strip(), (invitee or "").strip()
    if not inviter or not invitee or inviter == invitee:
        return None
    stale = []
    with keyed_lock("party_membership", "world"):
        rows = get_connection().execute(
            "SELECT invite_id, inviter, invitee, created_at, status, intent_id "
            "FROM party_invites WHERE inviter=? AND invitee=? AND status='pending'",
            (inviter, invitee)).fetchall()
        for row in rows:
            inv = _row_to_invite(row)
            if intent_id and inv["intent_id"] == intent_id:
                return inv["invite_id"]
            stale.append(inv)
        iid = "pinv_" + uuid.uuid4().hex[:10]
        stored_tx_1 = False
        with transaction() as conn:
            conn.execute("UPDATE party_invites SET status='stale' "
                         "WHERE inviter=? AND invitee=? AND status='pending'", (inviter, invitee))
            conn.execute("INSERT INTO party_invites "
                         "(invite_id, inviter, invitee, created_at, status, intent_id) "
                         "VALUES (?, ?, ?, ?, 'pending', ?)",
                         (iid, inviter, invitee, utc_now_iso(), intent_id))
            stored_tx_1 = True
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([inviter, invitee], ("presence", "notices"))
    for inv in stale:
        emit("party_invite_closed", invite=inv, reason="superseded")
    return iid


def get_invite(invite_id: str) -> Optional[Dict]:
    if not invite_id:
        return None
    row = get_connection().execute(
        "SELECT invite_id, inviter, invitee, created_at, status, intent_id "
        "FROM party_invites WHERE invite_id=?", (invite_id,)).fetchone()
    return _row_to_invite(row) if row else None


def get_pending_invites_for(invitee: str) -> List[Dict]:
    rows = get_connection().execute(
        "SELECT invite_id, inviter, invitee, created_at, status, intent_id "
        "FROM party_invites WHERE invitee=? AND status='pending' ORDER BY created_at",
        ((invitee or "").strip(),)).fetchall()
    out = []
    projection = get_provider("party_invite_projection")
    for row in rows:
        inv = _row_to_invite(row)
        if not invite_is_fresh(inv) or not same_location(inv["inviter"], invitee):
            continue
        if inv["intent_id"]:
            if projection is None or get_provider("party_invite_respond") is None:
                continue
            inv.update(projection(inv) or {})
        out.append(inv)
    return out


def find_pending_invite(inviter: str, invitee: str,
                        max_age_minutes: int = INVITE_MAX_AGE_MINUTES) -> Optional[Dict]:
    row = get_connection().execute(
        "SELECT invite_id, inviter, invitee, created_at, status, intent_id "
        "FROM party_invites WHERE inviter=? AND invitee=? AND status='pending' "
        "ORDER BY created_at DESC LIMIT 1", (inviter, invitee)).fetchone()
    inv = _row_to_invite(row) if row else None
    return inv if inv and invite_is_fresh(inv, max_age_minutes) else None


def settle_pending_invite(invite_id: str, accept: bool) -> Dict:
    """Atomic consent/membership primitive; linked plans validate before this."""
    with keyed_lock("party_membership", "world"):
        inv = get_invite(invite_id)
        if not inv:
            return {"status": "not_found"}
        common = {"inviter": inv["inviter"], "invitee": inv["invitee"],
                  "intent_id": inv["intent_id"]}
        if inv["status"] != "pending":
            if inv["status"] == ("accepted" if accept else "declined"):
                party = get_party_of(inv["invitee"]) or {}
                if accept and party.get("leader") != inv["inviter"]:
                    return {"status": "not_found", **common}
                return {"status": inv["status"], **common,
                        "party_id": party.get("party_id", "")}
            return {"status": "not_found", **common}
        from app.core import sync_topics
        before = sync_topics.party_of(inv["inviter"]).names
        if not invite_is_fresh(inv):
            stored_tx_1 = False
            with transaction() as conn:
                conn.execute("UPDATE party_invites SET status='expired' WHERE invite_id=?", (invite_id,))
                stored_tx_1 = True
            from app.core import sync_topics
            if stored_tx_1:
                sync_topics.avatars([inv["inviter"], inv["invitee"]], ("presence", "notices"))
            return {"status": "expired", **common}
        if accept and not same_location(inv["inviter"], inv["invitee"]):
            return {"status": "not_present", **common}
        stored_tx_2 = False
        with transaction() as conn:
            pid = _write_member(conn, inv["inviter"], inv["invitee"]) if accept else ""
            if accept and not pid:
                return {"status": "join_conflict", **common}
            conn.execute("UPDATE party_invites SET status=? WHERE invite_id=? AND status='pending'",
                         ("accepted" if accept else "declined", invite_id))
            stored_tx_2 = True
        from app.core import sync_topics
        if stored_tx_2:
            sync_topics.avatars([*before, *sync_topics.party_of(inv["inviter"]).names, inv["inviter"], inv["invitee"]], ("presence", "notices"))
        if accept:
            _cancel_joiner_journey(inv["invitee"])
        return {"status": "accepted" if accept else "declined", "party_id": pid, **common}


def resolve_pending_invite(invite_id: str, accept: bool) -> Dict:
    """All avatar, NPC and decision answers use the same consent continuation."""
    inv = get_invite(invite_id)
    if not inv:
        return {"status": "not_found"}
    if inv["intent_id"]:
        handler = get_provider("party_invite_respond")
        if handler is None:
            return {"status": "unavailable", "intent_id": inv["intent_id"]}
        return handler(invite_id, bool(accept))
    return settle_pending_invite(invite_id, bool(accept))


def close_intent_invites(intent_id: str, status: str = "cancelled") -> None:
    """Close remaining questions without affecting unrelated invitations."""
    stored_tx_1 = False
    with keyed_lock("party_membership", "world"), transaction() as conn:
        affected = conn.execute(
            "SELECT inviter, invitee FROM party_invites WHERE intent_id=? AND status='pending'",
            (intent_id,)).fetchall()
        conn.execute("UPDATE party_invites SET status=? WHERE intent_id=? AND status='pending'",
                     (status, intent_id))
        stored_tx_1 = True
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([n for row in affected for n in row], ("presence", "notices"))


def clear_invites_for(character: str) -> None:
    """Detach invitations and publish lifecycle removal (also used by pooling)."""
    c = (character or "").strip()
    if not c:
        return
    stored_tx_1 = False
    with keyed_lock("party_membership", "world"), transaction() as conn:
        affected = conn.execute(
            "SELECT inviter, invitee FROM party_invites WHERE status='pending' "
            "AND (inviter=? OR invitee=?)", (c, c)).fetchall()
        conn.execute("UPDATE party_invites SET status='stale' WHERE status='pending' "
                     "AND (inviter=? OR invitee=?)", (c, c))
        stored_tx_1 = True
    from app.core import sync_topics
    if stored_tx_1:
        sync_topics.avatars([n for row in affected for n in row], ("presence", "notices"))
    emit("party_invites_cleared", character=c)
