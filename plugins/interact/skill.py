"""Interact package — the pair-interaction verb.

``InteractWith`` proposes a PAIR animation clip
(``app/core/interaction_engine.py``) to a present partner: the action text is
resolved against the pose catalog like any pose, and only a catalog pose that
is marked ``solo: false`` AND whose ``animation`` is a complete pair clip
(``<kind>__a`` + ``<kind>__b``) qualifies. The partner name is matched exactly
(case-insensitive) — never by first name or substring.

A pair is ASKED, never imposed: the call records an invitation and the clip
starts only on the answer. The avatar answers through the player UI
(``/play/interact/respond``); an NPC is bumped and answers by calling this
same verb back, which the counter-invitation brake reads as consent — the
same shape the party's invite/join uses, and never a keyword match on prose.

The interaction itself ends on the game clock (travel ticker), or when either
participant walks away, is moved, or takes another pose.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


#: An answer of "no" — the ONE piece of prose this verb reads, and only from
#: its own ``answer`` argument, never from the character's reply text.
_NO_ANSWERS = frozenset({"no", "nein", "decline", "refuse", "reject", "false"})


def _is_refusal(data: Dict[str, Any]) -> bool:
    """True when the call is a refusal: ``{"answer": "no"}``.

    A character that does not want to has to be able to SAY so, or its
    partner's question stands open until the window expires. The tool's own
    argument is the only signal — reading the RP prose for a "no" would be
    the keyword classification this project does not do.
    """
    ans = data.get("answer")
    if isinstance(ans, bool):
        return not ans
    return str(ans or "").strip().lower() in _NO_ANSWERS


class InteractSkill(PluginSkill):
    SKILL_ID = "interact"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}

    def visible_for(self, character_name: str) -> bool:
        """No pair clip in the library → the verb is not offered at all."""
        try:
            from app.core.interaction_engine import partner_poses
            return bool(partner_poses())
        except Exception:
            return False

    def as_tool(self, **kwargs) -> ToolSpec:
        try:
            from app.core.interaction_engine import partner_poses
            keys = ", ".join(sorted(k for k, _ in partner_poses()))
        except Exception:
            keys = ""
        extra = f" Known two-person actions: {keys}." if keys else ""
        return ToolSpec(name=self.name, description=f"{self.description}{extra}",
                        func=self.execute)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        actor = (data.get("agent_name") or "").strip()
        if not actor:
            return "Error: character_name missing."
        partner_raw = str(data.get("partner") or data.get("name")
                          or data.get("target") or "").strip()
        action = str(data.get("action") or data.get("pose") or "").strip()
        if not partner_raw or not action:
            return "Error: pass {\"partner\": \"<name>\", \"action\": \"<what you do together>\"}."
        try:
            from app.core import interaction_engine as IE
            from app.core.pose_catalog import resolve_to_catalog
            from app.models.character import list_available_characters
            available = list_available_characters()
            partner = next((n for n in available
                            if n.lower() == partner_raw.lower()), "")
            if not partner:
                return f"Character '{partner_raw}' not found. Available: {', '.join(available)}"
            known = dict(IE.partner_poses())
            key, _how = resolve_to_catalog(action, "pose")
            if key not in known:
                return (f"'{action}' is not a two-person action. "
                        f"Known: {', '.join(sorted(known)) or 'none'}.")
            # The other one already asked US for this very thing: calling the
            # verb back is how a character says yes. Answering an invitation
            # with a counter-invitation would otherwise leave two open
            # questions and start nothing (the party has the same brake).
            open_ask = IE.find_pending_invite(partner, actor, key)
            if open_ask:
                if _is_refusal(data):
                    IE.resolve_invite(open_ask["invite_id"], False)
                    return (f"{actor} turns {partner} down — no {key}. "
                            f"Say why in character.")
                res = IE.resolve_invite(open_ask["invite_id"], True)
                if res.get("status") == "started":
                    return (f"{actor} accepts: {actor} and {partner} now "
                            f"{key} (for about "
                            f"{res['interaction']['duration_s']:.0f} seconds).")
                if res.get("status") == "approaching":
                    # Agreed, but not close enough yet — the walk over is
                    # already running and the pair starts on arrival.
                    return (f"{actor} agrees and walks over to {partner} "
                            f"— the {key} starts when they get there.")
                return f"Cannot: {res.get('reason') or res.get('status')}"
            if _is_refusal(data):
                # Nothing to refuse — never turn a "no" into a fresh proposal
                # of the very thing that was refused.
                return f"{partner} has not asked {actor} for anything."
            blocked = IE.check_can_pair(actor, partner)
            if blocked:
                return f"Cannot: {blocked}"
            invite_id = IE.create_invite(actor, partner, key)
            if not invite_id:
                return f"Cannot ask {partner} right now."
            return self._ask(actor, partner, key, invite_id)
        except ValueError as e:
            return f"Cannot: {e}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, actor, e)
            return f"Error in {self.name}: {e}"

    def _ask(self, actor: str, partner: str, key: str,
             invite_id: str = "") -> str:
        """Hand the recorded question to whoever has to answer it: the player
        sees it in the UI, an NPC is nudged to answer in its own turn.

        A TEMPORARY NPC has already answered by the time we get here: the
        hook in ``register.py`` resolves the invitation synchronously inside
        ``create_invite``. Telling the actor "X was asked" would be a lie the
        very next line contradicts, so the row is read back and the sentence
        says what actually happened.
        """
        try:
            from app.models.account import is_player_controlled
            is_avatar = is_player_controlled(partner)
        except Exception:
            is_avatar = False
        if is_avatar:
            # A player is not asked through an LLM — the recorded invitation
            # IS the question, and /play/interact/respond is the answer.
            return (f"{actor} asks {partner} to {key} together "
                    f"— waiting for their answer.")
        answered = self._answered_at_once(partner, invite_id, key)
        if answered:
            return answered
        # An NPC invitee gets its turn from this package's own hook handler
        # (register.py), which the core fires on every recorded invitation —
        # so the route and this verb nudge it in exactly one place.
        return f"{actor} asks {partner} to {key} together."

    def _answered_at_once(self, partner: str, invite_id: str,
                          key: str) -> str:
        """The sentence for an invitation that is ALREADY answered, or ``""``
        when it is still open (or the invitee is not a temporary NPC)."""
        if not invite_id:
            return ""
        try:
            from app.models.character import is_temporary_npc
            if not is_temporary_npc(partner):
                return ""
            from app.core import interaction_engine as IE
            status = str((IE.get_invite(invite_id) or {}).get("status") or "")
        except Exception as e:  # noqa: BLE001 — never lose the verb over this
            self.ctx.logger.debug("reading invite %s failed: %s", invite_id, e)
            return ""
        if status in ("accepted", "started"):
            return f"{partner} agrees; the {key} begins."
        if status == "approaching":
            return f"{partner} agrees and comes over for the {key}."
        if status in ("declined", "stale", "cancelled"):
            return f"{partner} cannot right now."
        return ""
