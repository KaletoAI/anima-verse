"""Party package — travel together, ONE class, three verbs (like WetSkill
enter/leave): PartySkill with verb='invite'|'join'|'leave'.

  invite_to_party (verb='invite'): the character invites someone present.
    - Target = avatar -> pending invite (question in the chat window, UI decides).
    - Target = NPC    -> the invitee is bumped and decides on its own via
      JoinParty in its own turn (no keyword matching). With the decision
      point ``party_join`` active, a confident decision model settles the
      invitation at once instead (register.py, docs/decision-models.md).
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

See development_instructions/plan-party-system.md.
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
        """The party section — emitted by the LEAVE verb only.

        All three verbs live in this one class, so a naive block would reach
        the prompt up to three times. ``leave`` is the verb whose visibility
        is exactly "this character is in a party" (see visible_for above),
        which makes it the one place the section belongs.
        """
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
        if not P.same_location(character_name, target):
            # The tool description says "present at your current location" —
            # this is the enforcement. An RP turn that hallucinates someone
            # into the scene must not reach them across the map.
            return (f"{target} is not at your location. "
                    f"You can only invite someone who is here with you.")
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
        # The invitation is recorded for EVERY target, avatar or NPC: it is
        # what the brake above reads when the invitee answers with an invite
        # of its own.
        invite_id = P.create_pending_invite(character_name, target)
        try:
            from app.models.account import is_player_controlled
            _is_avatar = is_player_controlled(target)
        except Exception:
            _is_avatar = False
        if _is_avatar:
            # An avatar cannot decide via LLM -> the pending invite is the UI
            # question.
            return (f"{character_name} invited {target} to the party "
                    f"— waiting for their answer.")
        # NPC target: a configured decision model may settle it at once.
        settled = self._decide_join(invite_id, character_name, target)
        if settled:
            return settled
        # NO keyword classification. The invitee decides on its own via the
        # JoinParty tool in its own turn — we only bump it (with a hint) so it
        # reacts soon.
        try:
            from app.core.agent_loop import get_agent_loop
            get_agent_loop().bump(
                target,
                hint=(f"{character_name} invites you to come along with the "
                      f"group. Decide in character whether to accept — if yes, "
                      f"call JoinParty with leader={character_name}; to "
                      f"refuse, call it with leader={character_name}, "
                      f"answer=no."))
        except Exception as _be:
            self.ctx.logger.debug("invite bump failed: %s", _be)
        return f"{character_name} invites {target} to come along."

    def _decide_join(self, invite_id: str, inviter: str, invitee: str) -> str:
        """Ask the decision model of PARTY_JOIN whether the NPC joins.

        Returns the verb's result sentence when the invitation is settled
        (the NPC must NOT be woken), ``""`` for the usual path (the bump):
        point inactive, no confident answer, or an accept whose join failed.
        A decline does not bump the inviter — it is the one running this
        verb, the sentence is its tool result — and the room hears it as
        one narrator line. Never raises.
        """
        try:
            from app.core import decision, decision_points
            from app.core import party_engine as P
            if not invite_id or not decision.is_active(PARTY_JOIN):
                return ""
            offer = "to come along with the group"
            party = P.get_party_of(inviter)
            members = list((party or {}).get("members") or [])
            if members:
                offer += f" (the group: {', '.join(members)})"
            d = decision.decide(PARTY_JOIN,
                                decision_points.invite_state(invitee, inviter, offer),
                                decision_points.invite_questions(invitee, inviter),
                                key=invite_id)
            ans = d.answers.get("answer") if d else None
            if ans is None:
                return ""
            if ans.value == "accept":
                # mark_taken FIRST: _join records an outcome for the open
                # invitation, and while the prediction is still open that
                # would count the decider's OWN action as agreement with the
                # usual path. Once taken, the entry counts as "taken" only
                # (decision_log._count checks taken first), so _join's
                # record_outcome no longer counts. A join that then fails
                # stays "taken" — the NPC is woken and answers itself.
                decision.mark_taken(PARTY_JOIN, invite_id)
                self._join(invitee, {"leader": inviter})
                if P.is_in_party(invitee):
                    self.ctx.logger.info(
                        "party invite %s: decision model — %s joins %s",
                        invite_id, invitee, inviter)
                    return (f"{inviter} invites {invitee} to come along — "
                            f"{invitee} agrees and joins.")
                self.ctx.logger.info(
                    "party invite %s: decision model said accept, but %s could "
                    "not join %s — waking the NPC instead", invite_id, invitee,
                    inviter)
                return ""
            if ans.value == "decline":
                P.resolve_pending_invite(invite_id, False)
                decision.mark_taken(PARTY_JOIN, invite_id)
                self._narrate_decline(inviter, invitee)
                self.ctx.logger.info(
                    "party invite %s: decision model — %s declines %s",
                    invite_id, invitee, inviter)
                return (f"{inviter} invites {invitee} to come along — "
                        f"{invitee} declines.")
        except Exception as e:
            self.ctx.logger.debug("party_join decision failed for %s: %s",
                                  invitee, e)
        return ""

    def _narrate_decline(self, inviter: str, invitee: str) -> None:
        """One narrator line in the invitee's room for a decline the decision
        model settled — the counterpart of the join's own narrator line.
        Without it the refusal happens in no one's perception stream. Never
        raises."""
        try:
            from app.core.i18n import t
            from app.core.perception import (STORYTELLER_SPEAKER, VOLUME_NORMAL,
                                             record_utterance)
            from app.models.character import (get_character_current_location,
                                              get_character_current_room,
                                              get_character_language)
            lang = get_character_language(invitee) or "de"
            record_utterance(
                speaker=STORYTELLER_SPEAKER,
                content=t("{invitee} does not want to come along with {inviter}.",
                          lang).format(invitee=invitee, inviter=inviter),
                volume=VOLUME_NORMAL,
                location_id=get_character_current_location(invitee) or "",
                room_id=get_character_current_room(invitee) or "",
                source="party", anchor=invitee)
        except Exception as e:
            self.ctx.logger.debug("party decline narration failed for %s: %s",
                                  invitee, e)

    def _join(self, character_name: str, data: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        leader = _resolve_target(data)
        if not leader or leader == character_name:
            return "Whose party to join? (no valid target)"
        if _is_refusal(data):
            # The explicit "no": a character that does not want to must be
            # able to SAY so, or the invitation stands open until it ages out.
            inv = P.find_pending_invite(leader, character_name)
            if not inv:
                return f"{leader} has not invited {character_name}."
            _record_answer(inv["invite_id"], False)
            P.resolve_pending_invite(inv["invite_id"], False)
            return (f"{character_name} turns down {leader}'s invitation. "
                    f"Say why in character.")
        if P.is_in_party(character_name):
            return f"{character_name} is already in a party."
        if not P.same_location(character_name, leader):
            return (f"{leader} is not at your location — you cannot join "
                    f"their party from here.")
        pid = P.add_to_party(leader, character_name)
        if not pid:
            return (f"{character_name} cannot join {leader}'s party "
                    f"(already in a party / invalid).")
        try:
            inv = P.find_pending_invite(leader, character_name)
            if inv:
                _record_answer(inv["invite_id"], True)
        except Exception:  # noqa: BLE001
            pass
        try:
            P.clear_invites_for(character_name)
        except Exception:
            pass
        # Make the join visible in the room (narrator line); the character's own
        # RP reply runs separately via the reply turn.
        try:
            from app.models.character import (get_character_current_location,
                                              get_character_current_room)
            from app.core.perception import (record_utterance, VOLUME_NORMAL,
                                             STORYTELLER_SPEAKER)
            _loc = get_character_current_location(character_name) or ""
            _room = get_character_current_room(character_name) or ""
            # Narrator line — STORYTELLER_SPEAKER is the core narrator-speaker
            # sentinel (filtered out of participant lists everywhere). The
            # anchor lends it the joiner's point: parties form on the road just
            # as often as in a room, and out there a pointless speaker is heard
            # by nobody.
            record_utterance(speaker=STORYTELLER_SPEAKER,
                             content=f"{character_name} joins {leader}'s party.",
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="party", anchor=character_name)
        except Exception as _re:
            self.ctx.logger.debug("join_party record failed: %s", _re)
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
