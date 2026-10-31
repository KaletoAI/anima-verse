"""Interact package — the pair-interaction verb.

``InteractWith`` proposes a PAIR animation clip
(``app/core/interaction_engine.py``) to a present partner: the action text is
resolved against the pose catalog like any pose, and only a catalog pose that
is marked ``solo: false`` AND whose ``animation`` is a complete pair clip
(``<kind>__a`` + ``<kind>__b``) qualifies. The partner name is matched exactly
(case-insensitive) — never by first name or substring.

A pair is ASKED, never imposed: the call records an invitation and the clip
starts only on the answer. The avatar answers through the player UI
(``/play/interact/respond``); an NPC gets a direct answer turn and calls this
same verb back, which the counter-invitation brake reads as consent — the
same shape the party's invite/join uses, and never a keyword match on prose.

The interaction ends through signals, including a participant walking away,
being moved, falling asleep, or taking another pose.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolRefusal, ToolSpec


#: The decision point of this package: an NPC invited to a pair activity
#: accepts or declines (registered in ``register.py``, docs/decision-models.md).
PAIR_INVITE = "pair_invite"

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


def _record_answer(invite_id: str, accepted: bool) -> None:
    """The invitee's own answer is the usual path the decision model of
    PAIR_INVITE is compared with. A no-op for an invitation the model was
    never asked about; never lets the verb fail."""
    try:
        from app.core import decision
        decision.record_outcome(PAIR_INVITE, invite_id,
                                {"answer": "accept" if accepted else "decline"})
    except Exception:  # noqa: BLE001
        pass


class InteractSkill(PluginSkill):
    SKILL_ID = "interact"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}

    def visible_for(self, character_name: str) -> bool:
        """No pair clip in the library → the verb is not offered at all."""
        try:
            from app.core.interaction_engine import partner_poses
            from app.core.prop_action_store import live_runs
            return bool(partner_poses() or any(run["partner"] == character_name and
                        run["status"] == "awaiting_consent" for run in live_runs()))
        except Exception:
            return False

    def as_tool(self, **kwargs) -> ToolSpec:
        try:
            from app.core.interaction_engine import partner_poses
            keys = ", ".join(sorted(k for k, _ in partner_poses()))
        except Exception:
            keys = ""
        extra = (f" Known free two-person actions: {keys}." if keys else "")
        extra += (' Answer an exact prop-action invitation with '
                  '{"execution_id":"<offered id>","answer":"yes" or "no"}; '
                  'never substitute a pose or a different object.')
        return ToolSpec(name=self.name, description=f"{self.description}{extra}",
                        func=self.execute)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return ToolRefusal(f"{self.name} skill is disabled.")
        data = self._parse_base_input(raw_input)
        actor = (data.get("agent_name") or "").strip()
        if not actor:
            return ToolRefusal("character_name missing.")
        if data.get("execution_id"):
            return self._answer_prop(actor, data)
        partner_raw = str(data.get("partner") or data.get("name")
                          or data.get("target") or "").strip()
        action = str(data.get("action") or data.get("pose") or "").strip()
        if not partner_raw or not action:
            return ToolRefusal('pass {"partner": "<name>", "action": "<what you do together>"}.')
        try:
            from app.core import interaction_engine as IE
            from app.core.pose_catalog import resolve_to_catalog
            from app.models.character import list_available_characters
            available = list_available_characters()
            partner = next((n for n in available
                            if n.lower() == partner_raw.lower()), "")
            if not partner:
                return ToolRefusal(f"Character '{partner_raw}' not found. Available: {', '.join(available)}")
            known = dict(IE.partner_poses())
            key, _how = resolve_to_catalog(action, "pose")
            if key not in known:
                return ToolRefusal(f"'{action}' is not a two-person action. "
                                   f"Known: {', '.join(sorted(known)) or 'none'}.")
            # The other one already asked US for this very thing: calling the
            # verb back is how a character says yes. Answering an invitation
            # with a counter-invitation would otherwise leave two open
            # questions and start nothing (the party has the same brake).
            open_ask = IE.find_pending_invite(partner, actor, key)
            other_ask = None if open_ask else IE.find_pending_invite(partner, actor)
            if other_ask and _is_refusal(data):
                # "No" to the one waiting is a no to the question they asked,
                # whatever action the answer happens to name.
                open_ask = other_ask
            elif other_ask:
                # Answering an open question with a different action used to
                # leave a counter-invitation and start nothing (an accepted
                # invitation once came back as the wrong pose three times).
                ask = other_ask["pose_key"]
                return ToolRefusal(
                    f"{partner} asked {actor} for \"{ask}\" and is waiting for the answer. "
                    f"To agree: {{\"partner\": \"{partner}\", \"action\": \"{ask}\"}}; "
                    f"to refuse, add \"answer\": \"no\". Propose something else only after answering.")
            if open_ask:
                _record_answer(open_ask["invite_id"], not _is_refusal(data))
                if _is_refusal(data):
                    IE.resolve_invite(open_ask["invite_id"], False)
                    return (f"{actor} turns {partner} down — no {open_ask['pose_key']}. "
                            f"Say why in character.")
                res = IE.resolve_invite(open_ask["invite_id"], True)
                if res.get("status") == "started":
                    inter = res.get("interaction") or {}
                    how_long = ("until one of them stops" if inter.get("loop") else
                                f"for about {float(inter.get('clip_duration_s') or 0):.0f} seconds")
                    return f"{actor} accepts: {actor} and {partner} now {key} ({how_long})."
                if res.get("status") == "approaching":
                    # Agreed, but not close enough yet — the walk over is
                    # already running and the pair starts on arrival.
                    return (f"{actor} agrees and walks over to {partner} "
                            f"— the {key} starts when they get there.")
                return ToolRefusal(f"Cannot: {res.get('reason') or res.get('status')}")
            if _is_refusal(data):
                # Nothing to refuse — never turn a "no" into a fresh proposal
                # of the very thing that was refused.
                return ToolRefusal(f"{partner} has not asked {actor} for anything.")
            blocked = IE.check_can_pair(actor, partner)
            if blocked:
                return ToolRefusal(f"Cannot: {blocked}")
            invite_id = IE.create_invite(actor, partner, key)
            if not invite_id:
                return ToolRefusal(f"Cannot ask {partner} right now.")
            return self._ask(actor, partner, key, invite_id)
        except ValueError as e:
            return ToolRefusal(f"Cannot: {e}")
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, actor, e)
            return ToolRefusal(f"Error in {self.name}: {e}")

    def _answer_prop(self, actor: str, data: Dict[str, Any]) -> str:
        from app.core import prop_action_engine as actions, prop_action_store as runs
        ref = data["execution_id"]
        if not isinstance(ref, str):
            return "Cannot: invalid execution_id."
        run = runs.get(ref)
        if not run or run["partner"] != actor:
            return "Cannot: this exact prop invitation is not addressed to you."
        if data.get("partner") and data["partner"] != run["actor"]:
            return "Cannot: invitation partner mismatch."
        answer = data.get("answer")
        accepted = answer is True or (isinstance(answer, str) and answer.strip().lower() in
                                      {"yes", "ja", "accept", "agree", "true"})
        refused = _is_refusal(data)
        if not accepted and not refused:
            return "Cannot: give an explicit answer=yes or answer=no for this execution_id."
        result = actions.respond(actor, ref, accepted)
        if result["status"] != "refused":
            _record_answer(ref, accepted)
        return f"Prop action {ref}: {result['status']} ({result['reason'] or 'explicit answer recorded'})."

    def _ask(self, actor: str, partner: str, key: str,
             invite_id: str = "") -> str:
        """Hand the recorded question to whoever has to answer it: the player
        sees it in the UI, an NPC is nudged to answer in its own turn.

        A decision model may already have explicitly answered inside the hook.
        Read the real row back rather than claiming a still-open question.
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
        """Describe an explicit decision already recorded, or an open question."""
        if not invite_id:
            return ""
        try:
            from app.core import interaction_engine as IE
            row = IE.get_invite(invite_id) or {}
            status = str(row.get("status") or "")
        except Exception as e:  # noqa: BLE001 — never lose the verb over this
            self.ctx.logger.debug("reading invite %s failed: %s", invite_id, e)
            return ""
        if status in ("accepted", "started"):
            return f"{partner} agrees; the {key} begins."
        if status == "approaching":
            return f"{partner} agrees and comes over for the {key}."
        if status == "declined":
            return ToolRefusal(f"{partner} does not want to {key} right now.")
        if status == "failed":
            return ToolRefusal(f"{partner} cannot right now: {row.get('reason') or 'The activity could not start'}.")
        if status in ("stale", "cancelled"):
            return ToolRefusal(f"{partner} cannot right now.")
        return ""
