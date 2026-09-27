"""on_load entry: wire the pair-interaction package into the core.

The core records an invitation and emits ``interaction.invited`` — it must
not know that the answer is given by a tool called InteractWith (R1). This
module is where that knowledge lives:

* the hook nudges an NPC invitee to answer in its own turn, phrased with
  THIS package's verb name;
* the ``pair_verb_name`` provider lets the core (and other packages) name
  the verb in a message without importing it. Without this package the
  provider is absent, ``/play/interact/options`` offers nothing, and the
  player UI stops proposing pairs nobody could accept;
* the decision point ``pair_invite``: with a decision model configured, an
  ordinary NPC's accept/decline may be settled at once instead of waking it
  (docs/decision-models.md). Off by default — then nothing changes.
"""
from app.core import decision, decision_points
from app.core.hooks import register, register_provider
from app.core.log import get_logger
from plugins.interact.skill import PAIR_INVITE

logger = get_logger("interact")

#: The tool name the LLM sees — the template's frontmatter `name`.
VERB_NAME = "InteractWith"

#: Longest pose description handed to the decision model as part of the offer.
_OFFER_DESC_MAX = 160


def pair_verb_name() -> str:
    return VERB_NAME


def _on_invited(invite_id: str = "", inviter: str = "", invitee: str = "",
                pose_key: str = "", **_kwargs) -> None:
    """An invitation was recorded. A player answers it in the UI; an ordinary
    NPC is given a turn with a hint that names the verb and the arguments —
    consent is a tool call, never a keyword match on its prose.

    A TEMPORARY NPC has no thought turns (``thoughts_enabled`` is off, so
    ``bump`` refuses it) and no will system to consult: it says yes at once,
    and the engine's own state check decides whether the pair can start
    (asleep, travelling, occupied -> ``cannot``). A ``cannot`` that leaves the
    question OPEN is closed here: the engine keeps "not yet" questions alive
    for a second answer, and a temporary NPC never gives one.
    """
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
            # "cannot" with the row back on `pending` is the engine's "ask
            # again in a minute" (a taken seat, a missing clip). For a
            # temporary NPC nobody ever will: it has no thought turns, so the
            # question would sit open until the sweep. Close it here.
            if res.get("status") == "cannot":
                row = IE.get_invite(invite_id) or {}
                if row.get("status") == "pending":
                    logger.info("interaction invite %s: %s cannot (%s) and "
                                "nobody re-answers a temporary NPC — cancelled",
                                invite_id, invitee,
                                res.get("reason") or "no reason given")
                    IE.cancel_invite(invite_id)
            return
    except Exception as e:
        logger.debug("temporary-NPC acceptance failed for %s: %s", invitee, e)
    if invite_id and _decide_invite(invite_id, inviter, invitee, pose_key):
        return
    try:
        from app.core.agent_loop import get_agent_loop
        get_agent_loop().bump(
            invitee,
            hint=(f"{inviter} asks you to {pose_key} together. Decide in "
                  f"character whether you want to. To agree, call "
                  f"{VERB_NAME} with partner={inviter}, action={pose_key}; "
                  f"to refuse, call it with partner={inviter}, "
                  f"action={pose_key}, answer=no."))
    except Exception as e:
        logger.debug("interaction invite bump failed: %s", e)


def _offer(pose_key: str) -> str:
    """What is offered, in words: the key plus the catalog's own description."""
    offer = f"to {pose_key} together"
    try:
        from app.core.pose_catalog import get_catalog
        desc = str(get_catalog("pose").get(pose_key, {}).get("prompt") or "").strip()
    except Exception:
        desc = ""
    if desc:
        offer += f" ({desc[:_OFFER_DESC_MAX]})"
    return offer


def _narrate_decline(inviter: str, invitee: str, pose_key: str) -> None:
    """One narrator line in the invitee's room for a decline the decision
    model settled — the counterpart of start_interaction's line for a pair
    that starts. Without it the refusal happens in no one's perception
    stream. Never raises."""
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
            content=t("{invitee} does not want to {pose} with {inviter} right now.",
                      lang).format(invitee=invitee, inviter=inviter, pose=pose_key),
            volume=VOLUME_NORMAL,
            location_id=get_character_current_location(invitee) or "",
            room_id=get_character_current_room(invitee) or "",
            source="interaction", anchor=invitee)
    except Exception as e:
        logger.debug("pair decline narration failed for %s: %s", invitee, e)


def _decide_invite(invite_id: str, inviter: str, invitee: str,
                   pose_key: str) -> bool:
    """Ask the decision model of PAIR_INVITE whether the NPC accepts.

    True = the invitation is settled and the NPC must NOT be woken. False =
    take the usual path (the bump): point inactive, no confident answer, or
    an accept the engine turned into a "not yet". Never raises.

    No record_outcome here: resolve_invite never records one, so the
    decider's own action cannot be counted as agreement with the usual path
    — the outcome comes only from the NPC's own counter-call (skill.py).
    A decline does not bump the inviter: it learns the answer from its own
    tool result or the /play response, both of which read the row back —
    and the room hears it as one narrator line (_narrate_decline), which is
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
            if res.get("status") == "cannot":
                # A "cannot" with the row back on `pending` is the engine's
                # "ask again in a minute": the NPC answers in its own turn
                # and the outcome is recorded then. Any closed state (stale,
                # or a row that moved on meanwhile) has nobody left to
                # answer — waking the NPC would only turn its call-back into
                # a counter-invitation.
                row = IE.get_invite(invite_id) or {}
                if row.get("status") == "pending":
                    return False
            decision.mark_taken(PAIR_INVITE, invite_id)
            logger.info("interaction invite %s: decision model — %s accepts -> %s",
                        invite_id, invitee, res.get("status"))
            return True
        if ans.value == "decline":
            res = IE.resolve_invite(invite_id, accept=False)
            if res.get("status") == "declined":
                _narrate_decline(inviter, invitee, pose_key)
            decision.mark_taken(PAIR_INVITE, invite_id)
            logger.info("interaction invite %s: decision model — %s declines -> %s",
                        invite_id, invitee, res.get("status"))
            return True
    except Exception as e:
        logger.debug("pair_invite decision failed for %s: %s", invitee, e)
    return False


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
register("interaction.invited", _on_invited, tag="interact.bump_invitee")
