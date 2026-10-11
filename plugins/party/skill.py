"""Party package — travel together, ONE class, three verbs (like WetSkill
enter/leave): PartySkill with verb='invite'|'join'|'leave'.

  invite_to_party (verb='invite'): the character invites someone present.
    - Target = avatar -> pending invite (question in the chat window, UI decides).
    - Target = ordinary NPC -> an agent turn obtains consent.
      A destination-bound trip requests a direct chat/tool answer, including
      temporary NPCs, without enabling thoughts or matching prose keywords.
      With the decision point ``party_join`` active, a confident decision settles
      an eligible invitation at once (register.py, docs/decision-models.md).
    Every invitation is recorded in ``party_invites`` — it is the direction
    record of the party: an invitation answered with a counter-invitation is
    turned into a JOIN, so whoever asked first stays the leader.
  join_party (verb='join'): the character ACCEPTS or REFUSES — it joins a
    present character's party (the robust path for "X invites me, I say
    yes": the tool LLM calls this in the normal reply turn, no keyword
    detection, no separate consent round), or, called with
    ``{"answer": "no"}``, turns an open invitation down explicitly.
  leave_party (verb='leave'): leaves its own party (a follower steps out, a
    leader dissolves it). Offered to followers in the agent loop.

visible_for encodes the party-role visibility (replaces the former hardcoded
whitelist in skill_manager). The party engine (app.core.party_engine) stays
core (R5 — leader-move drag hook in models/character, the /play route calls
the engine's leave_party directly, movement-skill visibility).

See development_instructions/done/plan-party-system.md.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext

_VERB_TO_ID = {"invite": "invite_to_party", "join": "join_party", "leave": "leave_party"}

#: The decision point of this package: an NPC invited to come along joins or
#: declines (registered in ``register.py``, docs/decision-models.md).
PARTY_JOIN = "party_join"

#: An answer of "no" — read only from the verb's own ``answer`` argument,
#: never from the character's reply text (same set as the interact package;
#: kept here so this package stands on its own).
_NO_ANSWERS = frozenset({"no", "nein", "decline", "refuse", "reject", "false"})


def _is_refusal(data: Dict[str, Any]) -> bool:
    """True when the call is a refusal: ``{"answer": "no"}``."""
    ans = data.get("answer")
    if isinstance(ans, bool):
        return not ans
    return str(ans or "").strip().lower() in _NO_ANSWERS


def _record_answer(invite_id: str, accepted: bool) -> None:
    """The invitee's own answer is the usual path the decision model of
    PARTY_JOIN is compared with. A no-op for an invitation the model was
    never asked about (or one it already settled); never lets the verb fail."""
    try:
        from app.core import decision
        decision.record_outcome(PARTY_JOIN, invite_id,
                                {"answer": "accept" if accepted else "decline"})
    except Exception:  # noqa: BLE001
        pass


def _resolve_target(data: Dict[str, Any]) -> str:
    target = (data.get("leader") or data.get("target") or data.get("partner")
              or data.get("partner_name") or "").strip()
    if target:
        return target
    text = (data.get("input") or "").strip()
    return text.split()[0] if text else ""


class PartySkill(PluginSkill):
    """Party verbs in one class. Subclass-free: a verb parameter picks the
    operation; SKILL_ID derives from it."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, verb: str):
        super().__init__(config, ctx)
        self._verb = verb
        self.SKILL_ID = _VERB_TO_ID[verb]
        # name/description/action_hint come from templates/llm/skills/<id>.md
        self._defaults = {"enabled": True}

    def default_enabled_for(self, character_name: str) -> bool:
        """Offer consent/membership verbs without changing character settings."""
        from app.core.party_engine import get_party_of, get_pending_invites_for
        if self._verb == "leave":
            return get_party_of(character_name) is not None
        if self._verb == "join":
            from app.models.intents import get_intent
            return any(inv.get("intent_id") and
                       (get_intent(inv["intent_id"]) or {}).get("status") == "active"
                       for inv in get_pending_invites_for(character_name))
        return False

    def visible_for(self, character_name: str) -> bool:
        """Party-role visibility: followers cannot invite (they are dragged
        along); join only outside a party; leave only inside one."""
        try:
            from app.core.party_engine import get_party_of
            party = get_party_of(character_name)
        except Exception:
            return True
        if self._verb == "invite":
            return not (party and party.get("role") == "follower")
        if self._verb == "join":
            return party is None
        if self._verb == "leave":
            return party is not None
        return True

    def thought_context_block(self, character_name: str) -> str:
        """Emit the live managed plan or ordinary party state exactly once."""
        from plugins.party.trip_intents import trip_context
        trip = trip_context(character_name, self._verb)
        if trip:
            return trip
        if self._verb != "leave":
            return ""
        from plugins.party.blocks import party_section
        return party_section(character_name)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} is disabled."
        data = self._parse_base_input(raw_input)
        char = (data.get("agent_name") or "").strip()
        if not char:
            return "Error: character_name missing."
        try:
            if self._verb == "invite":
                return self._invite(char, data)
            if self._verb == "join":
                return self._join(char, data)
            return self._leave(char, data)
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"

    # --- Verbs -----------------------------------------------------------

    def _invite(self, character_name: str, data: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        target = _resolve_target(data)
        if not target or target == character_name:
            return "Who exactly to invite? (no valid target)"
        if P.is_party_follower(character_name):
            return f"{character_name} is part of a party and cannot invite anyone."
        incoming = P.find_pending_invite(target, character_name)
        if incoming and (data.get("destination") or data.get("intent_id")):
            if not incoming.get("intent_id"):
                return "Answer the ordinary invitation before proposing a destination-bound trip."
            from app.models.intents import get_intent
            from app.models.world import get_arrival_room_id, get_location_by_id
            proposed = get_intent(incoming["intent_id"]) or {}
            action = proposed.get("action") or {}
            if data.get("intent_id") != incoming["intent_id"]:
                return "A shared-trip counter-proposal requires the exact intent reference."
            if data.get("scope") and data["scope"] != action.get("scope"):
                return "The counter-proposal differs from the agreed participant scope."
            if data.get("destination"):
                destination = data["destination"]
                location = get_location_by_id(destination.get("location_id", "")) or {}
                normalized = {"location_id": destination.get("location_id", ""),
                              "room_id": destination.get("room_id") or get_arrival_room_id(location)}
                if normalized != action.get("destination"):
                    return "The counter-proposal differs from the destination awaiting your answer."
            if data.get("after_arrival") is not None and data["after_arrival"] != action.get("after_arrival"):
                return "The counter-proposal differs from the activity awaiting your answer."
            return self._join(character_name, {**data, "leader": target,
                                                "invite_id": incoming["invite_id"]})
        if not P.same_location(character_name, target):
            # The tool description says "present at your current location" —
            # this is the enforcement. An RP turn that hallucinates someone
            # into the scene must not reach them across the map.
            return (f"{target} is not at your location. "
                    f"You can only invite someone who is here with you.")
        if data.get("destination") or data.get("intent_id"):
            from plugins.party.trip_intents import propose_trip
            intent = propose_trip(character_name, target, data.get("destination") or {},
                                  data.get("scope", "pair"),
                                  intent_id=str(data.get("intent_id") or ""),
                                  after_arrival=data.get("after_arrival"))
            travel = (intent.get("meta") or {}).get("travel") or {}
            return (f"Shared trip {intent['id']}: {travel.get('phase', 'waiting_consent')}"
                    f" — {travel.get('reason', '')}")
        # Role-inversion brake: the OTHER one has already invited us. Both
        # sides describe the same shared trip ("come along" / "fine, let's
        # go"), so a tool LLM readily answers an invitation with a counter-
        # invitation — and that would make the one who asked first the
        # FOLLOWER, stripping the movement from exactly the character whose
        # idea the trip was. The open invitation is the direction record:
        # whoever asked first leads, our invite is really an acceptance.
        if P.find_pending_invite(target, character_name) is not None:
            self.ctx.logger.info(
                "invite_to_party [%s -> %s]: open invitation the other way "
                "round — joining instead of counter-inviting", character_name,
                target)
            return self._join(character_name, {**data, "leader": target})
        if P.get_party_of(target) is not None:
            return f"{target} is already in a party."
        from app.models.character import is_temporary_npc
        from app.models.account import is_player_controlled
        _is_avatar = is_player_controlled(target)
        if not _is_avatar and is_temporary_npc(target):
            return "A temporary NPC needs a destination-bound trip, not a standing party invitation."
        # The invitation is recorded for EVERY target, avatar or NPC: it is
        # what the brake above reads when the invitee answers with an invite
        # of its own.
        invite_id = P.create_pending_invite(character_name, target)
        if not invite_id:
            return "The party invitation could not be saved."
        if _is_avatar:
            # An avatar cannot decide via LLM -> the pending invite is the UI
            # question.
            return (f"{character_name} invited {target} to the party "
                    f"— waiting for their answer.")
        from plugins.party.trip_intents import request_consent
        request_consent(invite_id)
        invitation = P.get_invite(invite_id) or {}
        return (f"{character_name} invites {target} to come along "
                f"— {invitation.get('status', 'pending')}.")


    def _join(self, character_name: str, data: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        leader = _resolve_target(data)
        if not leader or leader == character_name:
            return "Whose party to join? (no valid target)"
        reference = data.get("invite_id")
        if reference:
            invitation = P.get_invite(reference) if isinstance(reference, str) else None
            if not invitation or invitation["inviter"] != leader or invitation["invitee"] != character_name:
                return "This invitation does not belong to this answer."
        else:
            invitation = P.find_pending_invite(leader, character_name)
            if invitation and invitation.get("intent_id"):
                return "A shared trip requires the exact invite_id from its proposal."
        if invitation:
            accepted = not _is_refusal(data)
            result = P.resolve_pending_invite(invitation["invite_id"], accepted)
            if invitation["status"] == "pending" and result["status"] in {"accepted", "declined"}:
                _record_answer(invitation["invite_id"], result["status"] == "accepted")
            if result["status"] == "accepted":
                if invitation["status"] == "pending":
                    from plugins.party.trip_intents import _narrate_answer
                    _narrate_answer(invitation, True)
                return f"{character_name} joins {leader}'s party."
            if result["status"] == "declined":
                return f"{character_name} turns down {leader}'s invitation. Say why in character."
            return f"The invitation could not be answered: {result['status']}."
        if _is_refusal(data):
            return f"{leader} has not invited {character_name}."
        # An ordinary join without a recorded proposal keeps its existing
        # meaning. A managed trip always reaches the linked resolver above.
        if P.is_in_party(character_name):
            return f"{character_name} is already in a party."
        pid = P.add_to_party(leader, character_name)
        if not pid:
            return f"{character_name} cannot join {leader}'s party (not present / membership conflict)."
        P.clear_invites_for(character_name)
        from plugins.party.trip_intents import _narrate_answer
        _narrate_answer({"inviter": leader, "invitee": character_name}, True)
        return f"{character_name} joins {leader}'s party."

    def _leave(self, character_name: str, data: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        res = P.leave_party(character_name)
        if res.get("status") != "ok":
            return f"{character_name} is not in a party."
        try:
            P.clear_invites_for(character_name)
        except Exception:
            pass
        if res.get("disbanded"):
            return f"{character_name} leaves the party — it disbands."
        return f"{character_name} leaves the party."
