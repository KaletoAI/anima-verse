"""Party package — travel together, ONE class, three verbs (like WetSkill
enter/leave): PartySkill with verb='invite'|'join'|'leave'.

  invite_to_party (verb='invite'): the character invites someone present.
    - Target = avatar -> pending invite (question in the chat window, UI decides).
    - Target = NPC    -> the invitee is bumped and decides on its own via
      JoinParty in its own turn (no keyword matching).
  join_party (verb='join'): the character JOINS a present character's party —
    the robust path for "X invites me, I say yes": the tool LLM calls this in
    the normal reply turn (no keyword detection, no separate consent round).
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
        if P.get_party_of(target) is not None:
            return f"{target} is already in a party."
        try:
            from app.models.account import is_player_controlled
            _is_avatar = is_player_controlled(target)
        except Exception:
            _is_avatar = False
        if _is_avatar:
            # An avatar cannot decide via LLM -> pending invite (UI question).
            P.create_pending_invite(character_name, target)
            return (f"{character_name} invited {target} to the party "
                    f"— waiting for their answer.")
        # NPC target: NO keyword classification. The invitee decides on its
        # own via the JoinParty tool in its own turn — we only bump it (with a
        # hint) so it reacts soon.
        try:
            from app.core.agent_loop import get_agent_loop
            get_agent_loop().bump(
                target,
                hint=(f"{character_name} invites you to come along with the "
                      f"group. Decide in character whether to accept — if yes, "
                      f"call JoinParty with leader={character_name}."))
        except Exception as _be:
            self.ctx.logger.debug("invite bump failed: %s", _be)
        return f"{character_name} invites {target} to come along."

    def _join(self, character_name: str, data: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        leader = _resolve_target(data)
        if not leader or leader == character_name:
            return "Whose party to join? (no valid target)"
        if P.is_in_party(character_name):
            return f"{character_name} is already in a party."
        pid = P.add_to_party(leader, character_name)
        if not pid:
            return (f"{character_name} cannot join {leader}'s party "
                    f"(already in a party / invalid).")
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
            # sentinel (filtered out of participant lists everywhere).
            record_utterance(speaker=STORYTELLER_SPEAKER,
                             content=f"{character_name} joins {leader}'s party.",
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="party")
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
