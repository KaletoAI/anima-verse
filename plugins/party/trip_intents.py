"""Consent-bound shared trips backed by the existing persisted intent store.

Only this one structured action is executable. Parties own consent; movement
uses the same authority as SetLocation. Every reconciliation is serialized by
intent id, and startup ownership is persisted before any movement is attempted.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict
from contextlib import contextmanager, nullcontext

from app.core import hooks, party_engine as P
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.movement_authority import move_character, movement_allowed
from app.core.prompt_templates import render
from app.core.timeutils import game_time, utc_now
from app.core.game_time import GameTime
from app.core.travel_engine import cancel_journey, get_journey
from app.models import intents as I
from app.models.character import (get_character_current_location,
                                  get_character_current_room,
                                  get_character_profile, get_character_status,
                                  is_character_sleeping, list_available_characters,
                                  get_character_skill_config)
from app.models.world import (get_arrival_room_id, get_location_by_id,
                              get_location_rooms, is_world_frozen,
                              is_world_sleeping, list_locations_for_character)

logger = get_logger("party_trips")
ACTION = "travel_together"
_CONSENT_SESSION = uuid.uuid4().hex


def intent_action_managed(intent: Dict) -> bool:
    return (intent.get("action") or {}).get("type") == ACTION


def _state(intent: Dict) -> Dict:
    return dict((intent.get("meta") or {}).get("travel") or {})


def _members(owner: str, participants: Dict, scope: str) -> tuple[list[str], str]:
    if not isinstance(participants, dict) or owner not in participants:
        raise ValueError("The trip owner must be an explicit leader participant.")
    if not isinstance(participants[owner], dict) or participants[owner].get("role") != "leader":
        raise ValueError("The owner must have the leader role.")
    proposed = [name for name in participants if name != owner]
    if len(proposed) != 1:
        raise ValueError("A shared trip proposes exactly one new companion.")
    invitee = proposed[0]
    if not isinstance(participants[invitee], dict) or participants[invitee].get("role") != "follower":
        raise ValueError("The proposed companion must have the follower role.")
    party = P.get_party_of(owner)
    if party and party["role"] != "leader":
        raise ValueError("Leave your current party before proposing a trip as its leader.")
    existing = list((party or {}).get("members") or [])
    if existing and scope != "party":
        raise ValueError("Pair scope conflicts with existing companions. Choose party scope or leave first.")
    if P.get_party_of(invitee):
        raise ValueError("The proposed companion already belongs to a party.")
    return [owner, *existing, invitee], invitee


def intent_action_validate(owner: str, participants: Dict, action: Dict) -> Dict:
    with keyed_lock("party_membership", "world"):
        return _validate_action(owner, participants, action)


def _validate_action(owner: str, participants: Dict, action: Dict, exclude_id: str = "") -> Dict:
    if not isinstance(action, dict) or action.get("type") != ACTION:
        raise ValueError("Unknown executable intent action.")
    scope = action.get("scope", "pair")
    if not isinstance(scope, str) or scope not in {"pair", "party"}:
        raise ValueError("Travel scope must be pair or party.")
    dest = action.get("destination")
    if not isinstance(dest, dict) or not isinstance(dest.get("location_id"), str):
        raise ValueError("A structured destination location_id is required.")
    location_id = dest["location_id"].strip()
    room_id = dest.get("room_id", "")
    if not isinstance(room_id, str):
        raise ValueError("Destination room_id must be a string.")
    location = get_location_by_id(location_id)
    if not location:
        raise ValueError("Destination does not exist.")
    room_id = room_id.strip() or get_arrival_room_id(location)
    if not any(room.get("id") == room_id for room in get_location_rooms(location)):
        raise ValueError("Destination room does not exist at this location.")
    members, _ = _members(owner, participants, scope)
    followup = action.get("after_arrival")
    if followup is not None:
        if len(members) != 2:
            raise ValueError("A paired activity requires exactly two trip members.")
        from plugins.party.undertakings import validate
        followup = validate(owner, members[1], followup)
    available = set(list_available_characters())
    origin = _position(owner)
    if not origin["location_id"]:
        raise ValueError("A shared trip requires a known origin location.")
    for name in members:
        if name not in available or get_character_status(name):
            raise ValueError(f"{name} is not available in the world.")
        if _position(name) != origin:
            raise ValueError(f"{name} is not present in the same room.")
        if get_journey(name):
            raise ValueError(f"{name} is already travelling for another reason.")
        if not _action_available(name, exclude_id):
            raise ValueError(f"{name} already has an active shared trip.")
    normalized = {"type": ACTION, "destination": {"location_id": location_id, "room_id": room_id},
                  "scope": scope}
    if followup is not None:
        normalized["after_arrival"] = followup
    return normalized


def intent_action_change_validate(intent: Dict, changes: Dict) -> Dict:
    if not intent_action_managed(intent):
        return changes
    for field in ("owner", "participants", "action", "trigger", "location_id"):
        if field in changes and changes[field] != intent.get(field):
            raise ValueError("Cancel the shared trip before proposing a different destination or group.")
    if changes.get("status") == "done":
        raise ValueError("A shared trip completes only after everyone actually arrives.")
    if "status" in changes and changes["status"] != intent.get("status") and changes["status"] != "cancelled":
        raise ValueError("A shared trip may only be cancelled manually.")
    if int(changes.get("target_count") or 0) != 0:
        raise ValueError("Shared trips do not use counted progress.")
    if "meta" in changes and (changes["meta"] or {}).get("travel") != (intent.get("meta") or {}).get("travel"):
        raise ValueError("Shared-trip runtime metadata is server-owned.")
    return {**changes, "target_count": 0}


def _position(name: str) -> Dict[str, str]:
    profile = get_character_profile(name)
    return {"location_id": get_character_current_location(name, profile=profile) or "",
            "room_id": get_character_current_room(name, profile=profile) or ""}


def _save(intent: Dict, state: Dict, **changes) -> Dict:
    meta = {**(intent.get("meta") or {}), "travel": state}
    if meta == (intent.get("meta") or {}) and not intent.get("target_count") \
            and all(intent.get(key) == value for key, value in changes.items()):
        return intent
    updated = I.update_intent(intent["id"], meta=meta, target_count=0, **changes)
    if not updated:
        raise RuntimeError("Shared-trip state could not be persisted.")
    return updated


def _cancel_owned(intent: Dict) -> None:
    claim = _state(intent).get("claim_id")
    if claim:
        cancel_journey(intent["owner"], journey_id=claim, execution_ref=intent["id"])
    from plugins.party.undertakings import cancel
    cancel(intent)


def _terminate(intent: Dict, reason: str, status: str = "cancelled") -> None:
    state = {**_state(intent), "phase": "cancelled", "reason": reason}
    if intent.get("status") == "active":
        intent = _save(intent, state, status=status)
    elif _state(intent) != state:
        intent = _save(intent, state)
    _cancel_owned(intent)
    P.close_intent_invites(intent["id"], status)


def _expired(intent: Dict) -> bool:
    expires = intent.get("expires_at")
    try:
        return bool(expires) and GameTime.parse(expires) <= game_time()
    except (ValueError, TypeError):
        return False


def _gated() -> str:
    if is_world_frozen():
        return "World is frozen; the agreed trip will resume after thaw."
    if is_world_sleeping():
        return "World is sleeping; the agreed trip will resume when awake."
    from app.core.task_queue import get_task_queue
    if get_task_queue().is_paused("default"):
        return "Simulation queue is paused; the agreed trip will resume when unpaused."
    return ""


def _group_matches(intent: Dict, accepted: bool) -> bool:
    state = _state(intent)
    expected = set(state["expected_members"])
    owner, invitee = intent["owner"], state["invitee"]
    party = P.get_party_of(owner)
    actual = {owner, *(party or {}).get("members", [])}
    if party and party["role"] != "leader":
        return False
    if accepted:
        return actual == expected and (P.get_party_of(invitee) or {}).get("leader") == owner
    return actual == expected - {invitee} and P.get_party_of(invitee) is None


def intent_completion_allowed(intent: Dict) -> bool:
    if not intent_action_managed(intent):
        return True
    if intent.get("action", {}).get("after_arrival") and not (_state(intent).get("activity") or {}).get("ended"):
        return False
    return _arrived(intent)


def _arrived(intent: Dict) -> bool:
    state = _state(intent)
    if not state.get("consent") or not state.get("expected_members"):
        return False
    if not _group_matches(intent, True):
        return False
    destination = intent["action"]["destination"]
    return all(_position(name) == destination and not get_journey(name)
               for name in state["expected_members"])


def _initialize(intent: Dict) -> Dict:
    with keyed_lock("party_membership", "world"):
        action = _validate_action(intent["owner"], intent.get("participants") or {},
                                  intent["action"], intent["id"])
        owner = intent["owner"]
        members, invitee = _members(owner, intent.get("participants") or {}, action["scope"])
        state = {"phase": "waiting_consent", "reason": "Waiting for the companion's explicit answer.",
                 "origin": _position(owner), "expected_members": members, "invitee": invitee,
                 "consent": False}
        if _state(intent).get("announcement"):
            state["announcement"] = _state(intent)["announcement"]
        intent = _save(intent, state, action=action)
        iid = P.create_pending_invite(owner, invitee, intent_id=intent["id"])
        if not iid:
            raise RuntimeError("Shared-trip invitation could not be persisted.")
        return _save(intent, {**state, "invite_id": iid})


def reconcile(intent_id: str, *, request: bool = True) -> None:
    if _reconcile(intent_id, request=request) and request:
        from plugins.party.undertakings import request as request_activity
        request_activity(intent_id)


def _reconcile(intent_id: str, *, request: bool = True) -> bool | None:
    """Recover consent/startup and settle arrival without a process-local cache."""
    ask = None
    with keyed_lock("intent_execution", intent_id):
        intent = I.get_intent(intent_id)
        if not intent or not intent_action_managed(intent):
            return
        if intent.get("status") != "active":
            if intent.get("status") != "done":
                state = _state(intent)
                reason = (state.get("reason") if state.get("phase") == "cancelled"
                          else "The shared trip was cancelled or expired.")
                _terminate(intent, reason)
            elif _state(intent).get("phase") not in {"arrived", "completed"} and not intent_completion_allowed(intent):
                # A non-API writer must not present an unexecuted trip as done.
                _cancel_owned(intent)
                _save(intent, {**_state(intent), "phase": "cancelled",
                               "reason": "Trip was ended before actual arrival."}, status="cancelled")
            return
        if _expired(intent):
            _terminate(intent, "The shared trip expired.", "expired")
            return
        state = _state(intent)
        if not state.get("expected_members"):
            try:
                intent = _initialize(intent)
                state = _state(intent)
            except (ValueError, RuntimeError) as e:
                _terminate(intent, f"The proposed trip could not be initialized: {e}")
                return
        if not state.get("expected_members"):
            _terminate(intent, "The persisted trip has no agreed participants.")
            return
        announcement = state.get("announcement")
        if announcement and not announcement.get("recorded"):
            from app.core.perception import record_utterance
            from app.models.perception_store import utterance_exists
            if not utterance_exists(intent["owner"], announcement["ts"], announcement["line"]):
                uid = record_utterance(
                    speaker=intent["owner"], content=announcement["line"],
                    addressees=[state["invitee"]], location_id=state["origin"]["location_id"],
                    room_id=state["origin"]["room_id"], source="npc_action",
                    ts=announcement["ts"], perception_meta={"intent_id": intent_id})
                if uid is None:
                    _terminate(intent, "The invitation could not be recorded.")
                    return
            intent = _save(intent, {**state, "announcement": {**announcement, "recorded": True}})
            state = _state(intent)
        available = set(list_available_characters())
        for member in state["expected_members"]:
            if member not in available or get_character_status(member):
                _terminate(intent, f"{member} disappeared or left the active NPC pool.")
                return
        invitation = P.get_invite(state.get("invite_id", ""))
        if invitation is None:
            iid = P.create_pending_invite(intent["owner"], state["invitee"], intent_id=intent_id)
            if not iid:
                _terminate(intent, "The linked invitation is unavailable.")
                return
            intent = _save(intent, {**state, "invite_id": iid})
            state = _state(intent)
            invitation = P.get_invite(iid)
        if invitation["status"] == "pending":
            if not P.invite_is_fresh(invitation):
                _terminate(intent, "The invitation expired without consent.", "expired")
                return
            if not _group_matches(intent, False):
                _save(intent, {**state, "phase": "blocked", "reason": "Party membership changed before consent."})
                return
            if any(_position(name) != state["origin"] for name in state["expected_members"]):
                _terminate(intent, "A participant moved away before consent.")
                return
            if state.get("phase") != "waiting_consent":
                intent = _save(intent, {**state, "phase": "waiting_consent",
                                       "reason": "Waiting for the companion's explicit answer."})
                state = _state(intent)
            if state.get("consent_request_session") != _CONSENT_SESSION and not is_world_sleeping():
                ask = invitation
        elif invitation["status"] != "accepted":
            _terminate(intent, "The companion declined or the invitation was withdrawn.",
                       "expired" if invitation["status"] == "expired" else "cancelled")
            return
        else:
            if not state.get("consent"):
                intent = _save(intent, {**state, "consent": True, "phase": "ready", "reason": ""})
                state = _state(intent)
            with keyed_lock("party_membership", "world"):
                if not _group_matches(intent, True):
                    _terminate(intent, "The agreed party lost or gained a participant.")
                    return
                if state.get("activity"):
                    from plugins.party.undertakings import arrive
                    return arrive(intent)
                journey = get_journey(intent["owner"])
                claim = state.get("claim_id")
                if journey:
                    if not claim or journey.get("journey_id") != claim:
                        _terminate(intent, "A participant started a different journey.")
                        return
                    sleeping = next((m for m in state["expected_members"] if is_character_sleeping(m)), "")
                    if is_world_sleeping() or sleeping:
                        _terminate(intent, f"{sleeping or 'The world'} went to sleep during the trip.")
                        return
                    if state.get("phase") != "travelling":
                        _save(intent, {**state, "phase": "travelling", "reason": ""})
                    return
                if _arrived(intent):
                    from plugins.party.undertakings import arrive
                    return arrive(intent)
                if state.get("phase") == "travelling":
                    _terminate(intent, "The owned journey ended without everyone arriving at the agreed destination.")
                    return
                for member in state["expected_members"]:
                    if get_journey(member):
                        _save(intent, {**state, "phase": "blocked", "reason": f"{member} is travelling independently."})
                        return
                    if _position(member) != state["origin"]:
                        _terminate(intent, "A participant left the agreed origin before departure.")
                        return
                gated = _gated()
                sleeping = next((name for name in state["expected_members"] if is_character_sleeping(name)), "")
                if gated or sleeping:
                    _save(intent, {**state, "phase": "ready", "reason": gated or f"{sleeping} is sleeping."})
                    return
                claim = claim or "trip_" + uuid.uuid4().hex
                intent = _save(intent, {**state, "phase": "starting", "claim_id": claim, "reason": ""})
                result = move_character(intent["owner"], **intent["action"]["destination"],
                                        participants=state["expected_members"], journey_id=claim,
                                        execution_ref=intent_id)
                state = _state(intent)
                if result["status"] == "blocked":
                    _save(intent, {**state, "phase": "blocked", "reason": result["reason"]})
                elif result["status"] == "travelling":
                    _save(intent, {**state, "phase": "travelling", "reason": ""})
                elif _arrived(intent):
                    from plugins.party.undertakings import arrive
                    return arrive(intent)
                else:
                    _save(intent, {**state, "phase": "blocked", "reason": "A participant could not enter the destination room."})
    if ask and request:
        request_consent(ask["invite_id"])


def respond(invite_id: str, accept: bool) -> Dict:
    invitation = P.get_invite(invite_id)
    if not invitation or not invitation.get("intent_id"):
        return {"status": "not_found"}
    iid = invitation["intent_id"]
    with keyed_lock("intent_execution", iid), keyed_lock("party_membership", "world"):
        invitation = P.get_invite(invite_id)
        if not invitation or invitation.get("intent_id") != iid:
            return {"status": "not_found"}
        intent = I.get_intent(iid)
        if not intent or intent.get("status") != "active" or not intent_action_managed(intent):
            # A repeated successful answer remains successful, never moves again.
            if invitation["status"] == "accepted" and accept and intent and intent.get("status") == "done" \
                    and (P.get_party_of(invitation["invitee"]) or {}).get("leader") == invitation["inviter"]:
                return {"status": "accepted", "intent_id": iid,
                        "party_id": (P.get_party_of(invitation["invitee"]) or {}).get("party_id", "")}
            return {"status": "not_found", "intent_id": iid}
        state = _state(intent)
        if state.get("invite_id") != invite_id:
            return {"status": "not_found", "intent_id": iid}
        if state.get("announcement") and not state["announcement"].get("recorded"):
            return {"status": "not_ready", "intent_id": iid}
        if _expired(intent):
            _terminate(intent, "The shared trip expired before its answer.", "expired")
            return {"status": "expired", "intent_id": iid}
        if accept and invitation["status"] == "pending":
            if not _group_matches(intent, False):
                _save(intent, {**state, "phase": "blocked", "reason": "Party membership conflicts with the agreed scope."})
                return {"status": "join_conflict", "intent_id": iid}
            for name in state["expected_members"]:
                if get_character_status(name) or name not in list_available_characters() or _position(name) != state["origin"]:
                    _terminate(intent, "A participant is no longer present for consent.")
                    return {"status": "not_present", "intent_id": iid}
                if get_journey(name):
                    _save(intent, {**state, "phase": "blocked", "reason": f"{name} is already travelling."})
                    return {"status": "join_conflict", "intent_id": iid}
        result = P.settle_pending_invite(invite_id, accept)
    reconcile(iid)
    return result


def invite_projection(invitation: Dict) -> Dict:
    intent = I.get_intent(invitation.get("intent_id", ""))
    if not intent or not intent_action_managed(intent):
        return {}
    dest = intent["action"]["destination"]
    location = get_location_by_id(dest["location_id"]) or {}
    room = next((r for r in get_location_rooms(location) if r.get("id") == dest.get("room_id")), {})
    label = location.get("name") or dest["location_id"]
    if room.get("name"):
        label += " / " + room["name"]
    followup = intent["action"].get("after_arrival") or {}
    return {"destination_label": label, "participants": _state(intent).get("expected_members", []),
            "after_arrival_label": followup.get("pose_key", "")}


def request_consent(invite_id: str) -> bool:
    """Request a real chat/tool answer, including temporary NPCs, never thoughts."""
    invitation = P.get_invite(invite_id)
    if not invitation or invitation["status"] != "pending":
        return False
    if not P.invite_is_fresh(invitation):
        return False
    from app.models.character import is_temporary_npc
    if not invitation.get("intent_id") and is_temporary_npc(invitation["invitee"]):
        from app.models.account import is_player_controlled
        if not is_player_controlled(invitation["invitee"]):
            return False
    from app.core.task_queue import get_task_queue
    if is_world_sleeping() or get_task_queue().is_paused("default") or is_character_sleeping(invitation["invitee"]):
        return False
    if invitation.get("intent_id"):
        with keyed_lock("intent_execution", invitation["intent_id"]):
            intent = I.get_intent(invitation["intent_id"])
            if not intent or intent["status"] != "active":
                return False
            if _state(intent).get("consent_request_session") == _CONSENT_SESSION:
                return True
            _save(intent, {**_state(intent), "consent_request_session": _CONSENT_SESSION})
    from app.models.account import is_player_controlled
    if is_player_controlled(invitation["invitee"]):
        return True
    details = invite_projection(invitation)
    if not invitation.get("intent_id"):
        party = P.get_party_of(invitation["inviter"]) or {}
        details = {"participants": [invitation["inviter"],
                                    *(party.get("members") or []), invitation["invitee"]]}
    variables = {**invitation, **details, "destination_label": details.get("destination_label", ""),
                 "participants": details.get("participants", []),
                 "after_arrival_label": details.get("after_arrival_label", "")}
    content = render("party/consent.md", **variables)
    from app.core import decision, decision_points
    if decision.is_active("party_join"):
        try:
            result = decision.decide("party_join", decision_points.invite_state(
                invitation["invitee"], invitation["inviter"], content),
                decision_points.invite_questions(invitation["invitee"], invitation["inviter"]), key=invite_id)
            answer = result.answers.get("answer") if result else None
            if answer and answer.value in {"accept", "decline"}:
                decision.mark_taken("party_join", invite_id)
                settled = P.resolve_pending_invite(invite_id, answer.value == "accept")
                if settled["status"] in {"accepted", "declined"}:
                    _narrate_answer(invitation, answer.value == "accept")
                    return True
        except Exception as e:
            logger.warning("party_join decision failed for %s: %s", invitation["invitee"], e)
    from app.core.agent_loop import get_agent_loop
    if not invitation.get("intent_id"):
        return get_agent_loop().bump(invitation["invitee"], hint=content)
    requested = get_agent_loop().bump_respond(invitation["invitee"], speaker=invitation["inviter"],
                                             content=content, hint=content, on_demand=True,
                                             request_id=invite_id)
    if not requested and invitation.get("intent_id"):
        with keyed_lock("intent_execution", invitation["intent_id"]):
            intent = I.get_intent(invitation["intent_id"])
            if intent and intent.get("status") == "active":
                _save(intent, {**_state(intent), "consent_request_session": ""})
    return requested


def _on_response_finished(character_name: str, request_id: str, outcome: str) -> None:
    invitation = P.get_invite(request_id)
    if not invitation or not invitation.get("intent_id") or invitation["invitee"] != character_name \
            or invitation["status"] != "pending":
        return
    with keyed_lock("intent_execution", invitation["intent_id"]):
        intent = I.get_intent(invitation["intent_id"])
        if not intent or intent["status"] != "active" or _state(intent).get("invite_id") != request_id:
            return
        _save(intent, {**_state(intent), "consent_request_session": "",
                       "reason": "No explicit answer was received; the next world check asks again."})


def _narrate_answer(invitation: Dict, accepted: bool) -> None:
    from app.core.perception import STORYTELLER_SPEAKER, record_utterance
    name = invitation["invitee"]
    record_utterance(speaker=STORYTELLER_SPEAKER,
                     content=(f"{name} joins {invitation['inviter']}'s party." if accepted else
                              f"{name} declines {invitation['inviter']}'s invitation."),
                     location_id=get_character_current_location(name) or "",
                     room_id=get_character_current_room(name) or "", source="party", anchor=name)


def propose_trip(owner: str, target: str, destination: Dict, scope: str = "pair", *,
                 intent_id: str = "", announcement: str = "", after_arrival: Dict | None = None) -> Dict:
    if intent_id:
        intent = I.get_intent(intent_id)
        if not intent or intent["owner"] != owner or not intent_action_managed(intent) or intent["status"] != "active":
            raise ValueError("No matching active shared-trip intent belongs to the inviter.")
        if target != _state(intent).get("invitee"):
            raise ValueError("The invitation target differs from the persisted shared trip.")
        if destination:
            location = get_location_by_id(destination.get("location_id", "")) or {}
            normalized = {"location_id": destination.get("location_id", ""),
                          "room_id": destination.get("room_id") or get_arrival_room_id(location)}
            if normalized != intent["action"]["destination"]:
                raise ValueError("The destination differs from the persisted shared trip.")
        if after_arrival is not None and after_arrival != intent["action"].get("after_arrival"):
            raise ValueError("The activity differs from the persisted shared trip.")
        reconcile(intent_id)
        return I.get_intent(intent_id) or {}
    participants = {owner: {"role": "leader", "progress": []}, target: {"role": "follower", "progress": []}}
    proposed_action = {"type": ACTION, "destination": destination, "scope": scope}
    if after_arrival is not None:
        proposed_action["after_arrival"] = after_arrival
    action = intent_action_validate(owner, participants, proposed_action)
    meta = {"travel": {"announcement": {
        "line": announcement, "ts": utc_now().isoformat(timespec="microseconds")
    }}} if announcement else {}
    trigger = {"kind": "standing"}
    intent = I.create_intent(owner=owner, title="Travel together", participants=participants,
                             source="character", action=action, target_count=0, meta=meta,
                             trigger=trigger, expires_at=I.default_intent_expiry(trigger, "character"))
    if not intent:
        raise RuntimeError("The proposed shared trip could not be saved.")
    return intent


def npc_action_available(name: str) -> bool:
    return _action_available(name)


def _action_available(name: str, exclude_id: str = "") -> bool:
    for intent in I.list_intents(status="active"):
        if intent["id"] == exclude_id or not intent_action_managed(intent):
            continue
        # Initialization claims the group under the membership lock.
        if exclude_id and not _state(intent).get("expected_members"):
            continue
        members = _state(intent).get("expected_members") or list((intent.get("participants") or {}).keys())
        if name in members:
            return False
    return True


def _destinations(name: str) -> list[Dict]:
    return [{"location_id": loc["id"], "name": loc.get("name", loc["id"]),
             "rooms": [{"room_id": r["id"], "name": r.get("name", r["id"])}
                       for r in get_location_rooms(loc)]}
            for loc in list_locations_for_character(name)]

def _can_propose(name: str) -> bool:
    return get_character_skill_config(name, "invite_to_party").get("enabled", True) is not False



def trip_context(name: str, verb: str) -> str:
    """Render one live plan section through its currently visible party verb."""
    for intent in I.list_intents(status="active"):
        if not intent_action_managed(intent):
            continue
        members = _state(intent).get("expected_members") or list(intent["participants"])
        if name not in members:
            continue
        emitter = "leave" if P.is_in_party(name) else ("invite" if name == intent["owner"] else "join")
        if verb != emitter:
            return ""
        state = _state(intent)
        projection = invite_projection({"intent_id": intent["id"]})
        if not projection:
            continue
        return render("party/trip_context.md", character_name=name,
                      intent_id=intent["id"], owner=intent["owner"],
                      invite_id=state.get("invite_id", ""),
                      destination_label=projection.get("destination_label", ""),
                      participants=members, phase=state.get("phase", "blocked"),
                      reason=state.get("reason", ""), after_arrival_label=projection.get("after_arrival_label", ""))
    return ""


def npc_action_context(name: str, variables: Dict) -> str:
    if not _can_propose(name) or not variables.get("talk_allowed") or not variables.get("present") or not npc_action_available(name):
        return ""
    activities = hooks.get_provider("shared_activity_options")
    return render("party/npc_action.md", destinations=_destinations(name),
                  present=variables["present"], npc_name=name,
                  shared_activities=activities() if activities else [])


def npc_action_execute(name: str, action: Any, variables: Dict, *, moved: bool = False) -> Dict:
    if moved or not variables.get("talk_allowed") or not isinstance(action, dict) or action.get("type") != ACTION:
        return {}
    if not _can_propose(name) or not npc_action_available(name) or _gated():
        return {}
    position = _position(name)
    if ("location_id" in variables and variables["location_id"] != position["location_id"]) \
            or ("current_room_id" in variables and variables["current_room_id"] != position["room_id"]):
        return {}
    present = {p["name"].casefold(): p["name"] for p in variables.get("present") or []}
    target = present.get(str(action.get("target") or "").strip().casefold())
    line = str(action.get("line") or "").strip()[:600]
    if not target or not line:
        return {}
    destination = action.get("destination")
    if not isinstance(destination, dict) or destination.get("location_id") not in {d["location_id"] for d in _destinations(name)}:
        return {}
    # The persisted announcement is written under the execution lock before consent.
    from app.core.agent_loop import get_agent_loop
    try:
        intent = propose_trip(name, target, destination, action.get("scope", "pair"),
                              announcement=line, after_arrival=action.get("after_arrival"))
    except ValueError:
        return {}
    if intent.get("status") not in {"active", "done"} or not _state(intent).get("invite_id"):
        return {}
    get_agent_loop().reset_room_energy(get_character_current_location(name) or "",
                                       get_character_current_room(name) or "", name)
    invitation = P.get_invite(_state(intent).get("invite_id", ""))
    if not invitation:
        return {}
    return {"invited": target, "said_to": target, "intent_id": intent["id"]}


def journey_execution_context(name: str, journey: Dict):
    """Guard only explicitly owned journeys; ordinary journeys are neutral."""
    ref = journey.get("execution_ref")
    return _guard_execution(name, journey, ref) if ref else nullcontext(True)


@contextmanager
def _guard_execution(name: str, journey: Dict, ref: str):
    with keyed_lock("intent_execution", ref):
        with keyed_lock("party_membership", "world"):
            intent = I.get_intent(ref)
            current = get_journey(name)
            if not intent or intent["status"] != "active" or not intent_action_managed(intent) \
                    or intent["owner"] != name:
                cancel_journey(name, journey_id=journey.get("journey_id"), execution_ref=ref)
                yield False
                return
            if _expired(intent):
                _terminate(intent, "The shared trip expired.", "expired")
                yield False
                return
            if not current or current != journey:
                yield False
                return
            state = _state(intent)
            if journey.get("journey_id") != state.get("claim_id"):
                _terminate(intent, "A different journey replaced the owned trip.")
                yield False
                return
            available = set(list_available_characters())
            position = _position(name)
            if not _group_matches(intent, True) or any(
                    member not in available or get_character_status(member)
                    or (member != name and (get_journey(member) or _position(member) != position))
                    for member in state["expected_members"]):
                _terminate(intent, "An agreed participant withdrew, disappeared or moved away.")
                yield False
                return
            sleeping = next((m for m in state["expected_members"] if is_character_sleeping(m)), "")
            if is_world_sleeping() or sleeping:
                _terminate(intent, f"{sleeping or 'The world'} went to sleep during the trip.")
                yield False
                return
            if is_world_frozen():
                yield False
                return
            if position["location_id"] == state["origin"]["location_id"]:
                from app.models.rules import check_leave
                destination = intent["action"]["destination"]
                for member in state["expected_members"]:
                    allowed, reason = check_leave(
                        member, room_only=False,
                        target_location_id=destination["location_id"],
                        target_room_id=destination["room_id"])
                    if not allowed:
                        _terminate(intent, f"{member}: {reason}")
                        yield False
                        return
            yield True
    reconcile(ref)


def journey_arrival_validate(name: str, journey: Dict, entry_room: str) -> tuple[bool, str]:
    intent = I.get_intent(journey.get("execution_ref", ""))
    if not intent or intent["status"] != "active" or not intent_action_managed(intent):
        return False, "The agreed trip is no longer active."
    if not _group_matches(intent, True):
        return False, "The agreed group changed."
    dest = intent["action"]["destination"]
    if journey.get("target") != dest["location_id"] or entry_room != dest["room_id"]:
        return False, "The agreed destination room is no longer accessible."
    for member in _state(intent)["expected_members"]:
        allowed, reason = movement_allowed(member, dest["location_id"], dest["room_id"])
        if not allowed:
            return False, f"{member}: {reason}"
    return True, ""


def _on_changed(intent: Dict, previous: Dict) -> None:
    with keyed_lock("intent_execution", intent["id"]):
        if not intent_action_managed(intent) and intent_action_managed(previous):
            _cancel_owned(previous)
            P.close_intent_invites(previous["id"])
            return
        if not intent_action_managed(intent):
            return
        if previous.get("status") != "active" and intent.get("status") == "active":
            _terminate(intent, "An ended shared trip cannot be reactivated.")
            return
        if _state(intent) != _state(previous) and intent.get("status") == previous.get("status"):
            return  # Runtime normalization/phase writes do not recurse.
        previous_roles = {name: value.get("role") for name, value in (previous.get("participants") or {}).items()}
        roles = {name: value.get("role") for name, value in (intent.get("participants") or {}).items()}
        if _state(previous) and (intent.get("owner") != previous.get("owner")
                                or intent.get("action") != previous.get("action")
                                or roles != previous_roles):
            _cancel_owned(previous)
            _terminate(intent, "The persisted destination or agreed participants were changed.")
            return
        if any(intent.get(k) != previous.get(k) for k in
               ("status", "action", "participants", "owner", "expires_at", "target_count")):
            reconcile(intent["id"], request=False)


def _on_deleted(intent: Dict) -> None:
    if intent_action_managed(intent):
        with keyed_lock("intent_execution", intent["id"]):
            _cancel_owned(intent)
            P.close_intent_invites(intent["id"])


def _on_detached(character: str, **kwargs) -> None:
    for intent in I.list_intents(status="active"):
        if intent_action_managed(intent) and character in (_state(intent).get("expected_members") or intent.get("participants") or {}):
            with keyed_lock("intent_execution", intent["id"]):
                current = I.get_intent(intent["id"])
                if current and current["status"] == "active":
                    _terminate(current, f"{character} withdrew, was pooled or was removed.")


def _on_invite_closed(invite: Dict, reason: str) -> None:
    if invite.get("intent_id"):
        existing = I.get_intent(invite["intent_id"])
        if not existing or existing["status"] != "active":
            return
        with keyed_lock("intent_execution", invite["intent_id"]):
            intent = I.get_intent(invite["intent_id"])
            if intent and intent["status"] == "active":
                _terminate(intent, f"Invitation was {reason}.")


def world_tick() -> None:
    for intent in I.list_intents(status="active"):
        if intent_action_managed(intent):
            reconcile(intent["id"])


def intent_action_types() -> list[str]:
    return [ACTION]


def register() -> None:
    providers = {"intent_action_types": intent_action_types,
                 "intent_action_validate": intent_action_validate,
                 "intent_action_change_validate": intent_action_change_validate,
                 "intent_action_managed": intent_action_managed,
                 "intent_completion_allowed": intent_completion_allowed,
                 "npc_action_context": npc_action_context,
                 "npc_action_execute": npc_action_execute,
                 "npc_action_available": npc_action_available,
                 "party_invite_respond": respond,
                 "party_invite_projection": invite_projection,
                 "journey_execution_context": journey_execution_context,
                 "journey_arrival_validate": journey_arrival_validate}
    for capability, fn in providers.items():
        hooks.register_provider(capability, fn)
    hooks.register("intent_created", lambda intent: reconcile(intent["id"]),
                   tag="party.trip.created")
    hooks.register("intent_changed", _on_changed, tag="party.trip.changed")
    hooks.register("intent_deleted", _on_deleted, tag="party.trip.deleted")
    hooks.register("world_tick", world_tick, tag="party.trip.tick")
    hooks.register("party_membership_changed", _on_detached, tag="party.trip.membership")
    hooks.register("party_invites_cleared", _on_detached, tag="party.trip.detached")
    hooks.register("party_invite_closed", _on_invite_closed, tag="party.trip.invite_closed")
    hooks.register("respond_finished", _on_response_finished, tag="party.trip.response_finished")
    from plugins.party.undertakings import started, ended, invited, failed
    hooks.register("interaction.invite_started", started, tag="party.activity.started")
    hooks.register("interaction.ended", ended, tag="party.activity.ended")
    hooks.register("interaction.invited", invited, tag="party.activity.invited")
    hooks.register("interaction.invite_failed", failed, tag="party.activity.failed")
