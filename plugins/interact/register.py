"""on_load entry: wire the pair-interaction package into the core.

The core records an invitation and emits ``interaction.invited`` — it must
not know that the answer is given by a tool called InteractWith (R1). This
module is where that knowledge lives:

* the hook nudges an NPC invitee to answer in its own turn, phrased with
  THIS package's verb name;
* the ``pair_verb_name`` provider lets the core (and other packages) name
  the verb in a message without importing it. Without this package the
  provider is absent, ``/play/interact/options`` offers nothing, and the
  player UI stops proposing pairs nobody could accept.
"""
from app.core.hooks import register, register_provider
from app.core.log import get_logger

logger = get_logger("interact")

#: The tool name the LLM sees — the template's frontmatter `name`.
VERB_NAME = "InteractWith"


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


register_provider("pair_verb_name", pair_verb_name)
register("interaction.invited", _on_invited, tag="interact.bump_invitee")
