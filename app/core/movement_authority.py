"""Shared structured movement gates and authoritative movement handoff.

This has no chat/party-consent policy or avatar-follow side effects. Callers
supply the exact participants; every participant must pass all gates before the
leader may move. Cross-location moves are timed unless a caller explicitly
preserves an existing immediate-placement policy.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable


def _movement_gate(character_name: str, location_id: str, room_id: str = "") -> tuple[bool, str, str]:
    from app.core.danger_system import check_location_access
    from app.core.world_ops import conditions_pass
    from app.models.character import get_character_current_location
    from app.models.rules import check_access, check_leave
    from app.models.world import get_location_by_id, get_location_rooms

    location = get_location_by_id(location_id)
    if not location:
        return False, "unknown_target", "target"
    if room_id and not any(r.get("id") == room_id for r in get_location_rooms(location)):
        return False, "unknown_room", "room"
    current = get_character_current_location(character_name) or ""
    if current:
        ok, reason = check_leave(character_name, room_only=current == location_id,
                                 target_location_id=location_id, target_room_id=room_id)
        if not ok:
            return False, reason, "leave"
    ok, reason = check_location_access(character_name, location)
    if not ok:
        return False, reason, "danger"
    ok, reason = check_access(character_name, location_id)
    if not ok:
        return False, reason, "location"
    if not conditions_pass(location.get("accessible_when") or [], character_name, location_id):
        from app.core.i18n import t
        from app.models.character import get_character_language
        return False, t("This place is not accessible to you.",
                        get_character_language(character_name) or "de"), "condition"
    if room_id:
        ok, reason = check_access(character_name, location_id, room_id=room_id)
        return ok, reason, "" if ok else "room"
    return True, "", ""


def movement_allowed(character_name: str, location_id: str, room_id: str = "") -> tuple[bool, str]:
    """The shared predicate, without caller-specific denial side effects."""
    ok, reason, _ = _movement_gate(character_name, location_id, room_id)
    return ok, reason


def move_character(character_name: str, location_id: str, room_id: str = "",
                   target_pose: str = "", *, participants: Iterable[str] | None = None,
                   journey_id: str = "", execution_ref: str = "", timed: bool = True) -> Dict[str, Any]:
    """Validate the exact group, then start a journey or set the local room.

    Return ``status`` (travelling/arrived/blocked), ``reason``, and an optional
    ``journey``. Party drag stays in the existing character setters/ticker;
    membership is serialized across every member's gate and the movement write.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      save_character_current_location,
                                      save_character_current_room, set_pose_intent)
    from app.models.world import get_arrival_room_id, get_location_by_id
    from app.core.party_engine import is_party_follower, party_followers
    with keyed_lock("party_membership", "world"):
        if is_party_follower(character_name):
            return {"status": "blocked", "reason": "party_follower"}
        actual_members = [character_name, *party_followers(character_name)]
        if participants is not None and set(participants) != set(actual_members):
            return {"status": "blocked", "reason": "The party changed before movement could begin."}
        location = get_location_by_id(location_id)
        if not location:
            return {"status": "blocked", "reason": "unknown_target"}
        target_room = room_id or get_arrival_room_id(location)
        for name in actual_members:
            ok, reason, gate = _movement_gate(name, location_id, target_room)
            if not ok:
                return {"status": "blocked", "reason": reason if name == character_name else f"{name}: {reason}",
                        "gate": gate, "blocked_character": name}
        if timed and (get_character_current_location(character_name) or "") != location_id:
            from app.core.travel_engine import start_journey
            journey, reason = start_journey(character_name, location_id,
                                            target_room=target_room, target_pose=target_pose,
                                            journey_id=journey_id, execution_ref=execution_ref)
            return ({"status": "travelling", "journey": journey, "reason": ""} if journey
                    else {"status": "blocked", "reason": reason})
        if (get_character_current_location(character_name) or "") != location_id:
            save_character_current_location(character_name, location_id)
            if get_character_current_location(character_name) != location_id:
                return {"status": "blocked", "reason": "location_write_failed", "gate": "persistence"}
        if get_character_current_room(character_name) != target_room:
            save_character_current_room(character_name, target_room)
        if get_character_current_room(character_name) != target_room:
            return {"status": "blocked", "reason": "room_write_failed", "gate": "persistence"}
        if target_pose:
            from app.core.pose_catalog import PairPoseWithoutPartner
            try:
                set_pose_intent(character_name, target_pose)
            except PairPoseWithoutPartner:
                target_pose = ""
        return {"status": "arrived", "reason": "", "pose": target_pose}
