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


# --- NPC-Consent (LLM-Entscheidung) --------------------------------------

def ask_to_join_party(inviter: str, invitee: str,
                      invitation_text: str = "") -> "tuple[bool, str]":
    """Fragt ``invitee`` per LLM, ob er der Party von ``inviter`` beitritt, und
    fuegt ihn bei Ja hinzu. Klon der Logik aus partner_consent.ask_partner_to_join
    (Pre-Checks -> run_chat_turn -> Keyword-Klassifikation, default-NO).

    Nur fuer NPC-Entscheidungen: ein vom User gesteuerter Avatar wird hier NICHT
    entschieden (der bekommt eine Pending-Einladung + UI-Frage). Returns
    ``(accepted, preview)``.
    """
    from app.core.partner_consent import _classify_response
    inviter = (inviter or "").strip()
    invitee = (invitee or "").strip()
    # Das zweite Tuple-Element ist die ECHTE NPC-Antwort (oder "") — Reason-Codes
    # gehen nur ins Log, damit der Aufrufer sie nicht faelschlich als Sprechzeile
    # in den Raum schreibt.
    if not inviter or not invitee or inviter == invitee:
        return False, ""
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(invitee):
            logger.info("Party-Consent: %s ist Avatar — uebersprungen", invitee)
            return False, ""
    except Exception:
        pass
    if get_party_of(invitee) is not None:
        return False, ""
    try:
        from app.models.character import is_character_sleeping
        if is_character_sleeping(invitee):
            logger.info("Party-Consent: %s schlaeft — auto-declined", invitee)
            return False, ""
    except Exception:
        pass
    try:
        from app.core.activity_engine import is_character_interruptible
        can_interrupt, busy = is_character_interruptible(invitee)
        if not can_interrupt:
            logger.info("Party-Consent: %s nicht unterbrechbar (%s)", invitee, busy)
            return False, ""
    except Exception:
        pass

    invitation = (invitation_text or "").strip() \
        or f"{inviter} fragt: Komm mit, lass uns zusammen losziehen!"

    # Raum-Kontext des invitee holen und run_chat_turn im RAUM-MODUS laufen lassen
    # — so schreibt run_chat_turn die Antwort NICHT zusaetzlich in chat_messages
    # (sonst doppelte Anzeige: Raum-Stream UND Telefon/Inbox). Die Antwort machen
    # wir danach selbst im Raum sichtbar (run_chat_turn tut das im Raum-Modus nicht).
    _loc = _room = ""
    room_stream = None
    try:
        from app.models.character import (get_character_current_location,
                                           get_character_current_room)
        from app.models import perception_store
        _loc = get_character_current_location(invitee) or ""
        _room = get_character_current_room(invitee) or ""
        if _loc:
            room_stream = perception_store.get_character_room_stream(
                invitee, _loc, _room, 40)
    except Exception:
        room_stream = None

    try:
        from app.core.chat_engine import run_chat_turn
        reply = run_chat_turn(
            owner_id="", responder=invitee, speaker=inviter,
            incoming_message=invitation, medium="in_person",
            task_type="party_invite", room_stream=room_stream)
    except Exception as e:
        logger.warning("Party-Consent fehlgeschlagen (%s) — default No", e)
        return False, ""
    if not reply:
        return False, ""

    accepted = _classify_response(reply)
    full_reply = reply.strip()

    # NPC-Antwort sichtbar im Raum (einmalig, kein chat_messages-Doppel).
    try:
        from app.core.perception import record_utterance, VOLUME_NORMAL
        record_utterance(speaker=invitee, content=full_reply, volume=VOLUME_NORMAL,
                         location_id=_loc, room_id=_room, source="party_invite")
    except Exception as _re:
        logger.debug("Party-Antwort record fehlgeschlagen: %s", _re)

    if accepted:
        pid = add_to_party(inviter, invitee)
        if not pid:
            logger.info("Party-Consent: %s sagte Ja, aber Beitritt scheiterte (Konflikt)",
                        invitee)
            return False, full_reply
        try:
            clear_invites_for(invitee)
        except Exception:
            pass
        try:
            from app.core.perception import record_utterance, VOLUME_NORMAL
            record_utterance(speaker="Erzähler",
                             content=f"{invitee} schließt sich {inviter}s Party an.",
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="party")
        except Exception:
            pass
        try:
            from app.models.relationship import record_interaction
            record_interaction(inviter, invitee, "party_join",
                summary=f"{invitee} schloss sich {inviter}s Party an",
                strength_delta=1.0)
        except Exception:
            pass
    logger.info("Party-Consent: %s %s (preview: %s)",
                invitee, "JA" if accepted else "NEIN", full_reply[:60])
    return accepted, full_reply


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
    """Offene Einladungen an ``invitee`` (fuer die UI-Frage)."""
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
            for r in rows]


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
