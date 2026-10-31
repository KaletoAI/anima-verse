"""on_load entry: wire the pair-interaction package into the core.

The core records an invitation and emits ``interaction.invited`` — it must
not know that the answer is given by a tool called InteractWith (R1). This
module is where that knowledge lives:

* the hook queues a direct answer from an NPC invitee, phrased with
  THIS package's verb name;
* the ``pair_verb_name`` provider lets the core (and other packages) name
  the verb in a message without importing it. Without this package the
  provider is absent, ``/play/interact/options`` offers nothing, and the
  player UI stops proposing pairs nobody could accept;
* the decision point ``pair_invite``: with a decision model configured, an
  ordinary NPC's accept/decline may be settled at once instead of waking it
  (docs/decision-models.md). Off by default — then nothing changes.
* the ``shared_activity_*`` providers expose exact, consent-bound pair
  continuations without another package importing this verb directly;
* the ``tool_decision.open_questions`` provider names every open invitation
  to a character with the exact yes/no call — what a tool-calling reader
  needs, while the invitee's own roleplay prompt only hears the question.
"""
from app.core import decision, decision_points
from app.core.hooks import register, register_provider
from app.core.log import get_logger
from plugins.interact.skill import PAIR_INVITE
from plugins.interact.undertakings import (shared_activity_cancel,
                                          shared_activity_options,
                                          shared_activity_request,
                                          shared_activity_status,
                                          shared_activity_validate)

logger = get_logger("interact")

#: The tool name the LLM sees — the template's frontmatter `name`.
VERB_NAME = "InteractWith"

#: Longest pose description handed to the decision model as part of the offer.
_OFFER_DESC_MAX = 160


def pair_verb_name() -> str:
    return VERB_NAME


def open_questions(agent_name: str, tool_names: list) -> list:
    """One line per open pair invitation to ``agent_name`` (only while it
    has the verb): who asks, the exact action, the yes and the no call."""
    if VERB_NAME not in (tool_names or []):
        return []
    from app.core import interaction_engine as IE
    from app.core.prop_action_engine import state_for
    from app.core.prop_actions import piece_label
    lines = []
    try:
        incoming = state_for(agent_name)["incoming"]
    except Exception as exc:  # noqa: BLE001 — the pair questions still count
        logger.debug("furniture questions for %s unavailable: %s", agent_name, exc)
        incoming = []
    for run in incoming:
        piece = piece_label(run["target"])
        lines.append(
            f'{run["actor"]} invited {agent_name} to "{run["label"]}"'
            + (f" on {piece}" if piece else "")
            + f'. Yes: {VERB_NAME} {{"partner": "{run["actor"]}", "answer": "yes"}}. '
            f'No: {VERB_NAME} {{"partner": "{run["actor"]}", "answer": "no"}}.')
    for invite in IE.pending_invites_for(agent_name):
        call = f'{{"partner": "{invite["inviter"]}", "action": "{invite["pose_key"]}"}}'
        lines.append(
            f'{invite["inviter"]} invited {agent_name} to "{invite["pose_key"]}". '
            f'Yes: {VERB_NAME} {call} — exactly this action, even if the reply '
            f'describes it in other words. No: {VERB_NAME} '
            f'{call[:-1]}, "answer": "no"}}.')
    return lines


def _on_invited(invite_id: str = "", inviter: str = "", invitee: str = "",
                pose_key: str = "", **_kwargs) -> None:
    """Preserve general Together policy; semantic prop consent is separate."""
    if not inviter or not invitee:
        return
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(invitee):
            return
    except Exception:
        return
    try:
        from app.models.character import is_temporary_npc
        if invite_id and is_temporary_npc(invitee):
            from app.core import interaction_engine as IE
            res = IE.resolve_invite(invite_id, accept=True)
            logger.info("interaction invite %s: temporary NPC %s says yes -> %s",
                        invite_id, invitee, res.get("status"))
            return
    except Exception as exc:
        logger.debug("temporary-NPC acceptance failed for %s: %s", invitee, exc)
    if invite_id and _decide_invite(invite_id, inviter, invitee, pose_key):
        return
    try:
        from app.core.agent_loop import get_agent_loop
        from app.core.pose_catalog import pose_label
        from app.models.character import get_character_language
        label = pose_label(pose_key, get_character_language(invitee))
        # Prose only: the roleplay reply of an rp_first character calls no
        # tool. The exact yes/no call reaches whoever does (tool decision,
        # or a single-mode chat) through open_questions.
        get_agent_loop().bump_respond(
            invitee, speaker=inviter,
            content=f"{inviter} suggests {label} to you.",
            on_demand=True,
            hint=(f"{inviter} suggests {label} to you. Decide in "
                  f"character whether you want to, and make your answer clear."))
    except Exception as e:
        logger.debug("interaction invite bump failed: %s", e)


def _offer(pose_key: str) -> str:
    """What is offered, in words: the English pose label plus the catalog's
    own description. English on purpose — it completes the decision state's
    English sentence "<inviter> invites <invitee> <offer>"."""
    from app.core.pose_catalog import pose_label
    offer = f"to join in {pose_label(pose_key, 'en')}"
    try:
        from app.core.pose_catalog import get_catalog
        desc = str(get_catalog("pose").get(pose_key, {}).get("prompt") or "").strip()
    except Exception:
        desc = ""
    if desc:
        offer += f" ({desc[:_OFFER_DESC_MAX]})"
    return offer


def _decide_invite(invite_id: str, inviter: str, invitee: str,
                   pose_key: str) -> bool:
    """Ask the decision model of PAIR_INVITE whether the NPC accepts.

    True = the invitation is settled and the NPC must NOT be woken. False =
    take the usual path (the bump): point inactive, no confident answer, or
    an exception before the answer settled. Never raises.

    No record_outcome here: resolve_invite never records one, so the
    decider's own action cannot be counted as agreement with the usual path
    — the outcome comes only from the NPC's own counter-call (skill.py).
    A decline does not bump the inviter: it learns the answer from its own
    tool result or the /play response, both of which read the row back —
    and the room hears it as one engine narrator line, which is
    also how a temporary-NPC inviter that never reads the row learns it.
    """
    try:
        if not decision.is_active(PAIR_INVITE):
            return False
        d = decision.decide(PAIR_INVITE,
                            decision_points.invite_state(invitee, inviter, _offer(pose_key)),
                            decision_points.invite_questions(invitee, inviter),
                            key=invite_id)
        ans = d.answers.get("answer") if d else None
        if ans is None:
            return False
        from app.core import interaction_engine as IE
        if ans.value == "accept":
            res = IE.resolve_invite(invite_id, accept=True)
            decision.mark_taken(PAIR_INVITE, invite_id)
            logger.info("interaction invite %s: decision model — %s accepts -> %s",
                        invite_id, invitee, res.get("status"))
            return True
        if ans.value == "decline":
            res = IE.resolve_invite(invite_id, accept=False)
            decision.mark_taken(PAIR_INVITE, invite_id)
            logger.info("interaction invite %s: decision model — %s declines -> %s",
                        invite_id, invitee, res.get("status"))
            return True
    except Exception as e:
        logger.debug("pair_invite decision failed for %s: %s", invitee, e)
    return False


def _on_prop_invited(execution_id: str = "", inviter: str = "", invitee: str = "", **_kwargs) -> None:
    """Explicit exact-run consent, including temporary NPCs without thoughts."""
    from app.core import prop_action_engine as actions, prop_action_store as runs
    from app.models.account import is_player_controlled
    run = runs.get(execution_id)
    if (not run or run["status"] != "awaiting_consent" or run["actor"] != inviter
            or run["partner"] != invitee or is_player_controlled(invitee)):
        return
    from app.core.prop_actions import piece_label
    piece = piece_label(run["target"])
    offer = f"to {run['definition']['name']}" + (f" on {piece}" if piece else "")
    try:
        if decision.is_active(PAIR_INVITE):
            d = decision.decide(PAIR_INVITE,
                decision_points.invite_state(invitee, inviter, offer),
                decision_points.invite_questions(invitee, inviter), key=execution_id)
            answer = d.answers.get("answer") if d else None
            if answer and answer.value in ("accept", "decline"):
                result = actions.respond(invitee, execution_id, answer.value == "accept")
                if result["status"] != "refused":
                    decision.mark_taken(PAIR_INVITE, execution_id)
                    return
    except Exception as exc:
        logger.debug("prop consent decision failed for %s: %s", invitee, exc)
    try:
        from app.core.agent_loop import get_agent_loop
        get_agent_loop().bump_respond(
            invitee, speaker=inviter, content=f"{inviter} invites you {offer}.", on_demand=True,
            # Prose only, like the pair invitation: the exact yes/no call
            # reaches the tool-calling reader through open_questions.
            hint=(f"{inviter} invites you {offer}. Decide in character whether you "
                  f"want to, and make your answer clear."))
    except Exception as exc:
        logger.debug("prop consent respond request failed for %s: %s", invitee, exc)


decision.register_point(
    PAIR_INVITE,
    label="Pair invitation: accept?",
    description=("An NPC invited to a two-person action decides whether it accepts; "
                 "in mode 'on' a confident answer settles the invitation at once, "
                 "otherwise the NPC is woken as before."),
    default_min_confidence=0.75,
    default_timeout_s=3.0,
    origin="interact",
)
register_provider("pair_verb_name", pair_verb_name)
register_provider("tool_decision.open_questions", open_questions)
register_provider("shared_activity_options", shared_activity_options)
register_provider("shared_activity_validate", shared_activity_validate)
register_provider("shared_activity_request", shared_activity_request)
register_provider("shared_activity_status", shared_activity_status)
register_provider("shared_activity_cancel", shared_activity_cancel)
register("interaction.invited", _on_invited, tag="interact.bump_invitee")
register("prop_action.invited", _on_prop_invited, tag="interact.prop_consent")
