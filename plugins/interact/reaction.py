"""The ``pair_reaction`` provider: how an NPC reacts to a pair action
started WITHOUT asking (requested with ``consent="react"``) — a furniture
pair run (kind ``prop_action``) or a free pair pose (kind ``interaction``).

The core waits for the answer before the pair binds
(``pair_reaction.REACTION_WAIT_S``); this module asks the model in a thread
of its own and hands the answer to ``pair_reaction.answer``, which routes it
to the engine of that kind. Anything that goes wrong just leaves the answer
out — the pair then goes on as accepted once the wait runs out.
"""
import json
import threading

from app.core.log import get_logger

logger = get_logger("interact.reaction")

#: The answer is one sentence plus four JSON fields.
_MAX_TOKENS = 220


def ask_reaction(*, kind: str, reference: str, actor: str, partner: str) -> None:
    """Provider entry: returns at once, the model runs in a thread."""
    threading.Thread(target=_react, args=(kind, reference, actor, partner),
                     name=f"pair-reaction-{reference[-8:]}", daemon=True).start()


def parse_reaction(text: str):
    """``(accept, line, feeling, romantic)`` from the model's answer, or None.

    The first JSON object in the text counts; ``reaction`` must be accept or
    resist. ``feeling`` outside -2..2 is clamped, a missing one is 0."""
    start = (text or "").find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("reaction") not in ("accept", "resist"):
        return None
    line = value.get("line") if isinstance(value.get("line"), str) else ""
    try:
        feeling = max(-2, min(2, int(value.get("feeling", 0))))
    except (TypeError, ValueError):
        feeling = 0
    return value["reaction"] == "accept", line.strip(), feeling, value.get("romantic") is True


def reaction_prompt(kind: str, reference: str, actor: str, partner: str):
    """``(system, user)`` for the waiting pair action, or None when it no
    longer waits. A free pair pose has no piece (``piece`` "")."""
    from app.core import pair_reaction
    from app.core.decision_points import invite_state
    from app.core.i18n import language_name
    from app.core.prompt_templates import render_task
    from app.core.stat_effects import build_stat_list
    from app.models.character import get_character_language
    lang = get_character_language(actor)
    waiting = pair_reaction.pending(kind, reference, actor, partner, lang)
    if waiting is None:
        return None
    action, piece = waiting["action"], waiting["piece"]
    state = invite_state(partner, actor, f'to "{action}"' + (f" on {piece}" if piece else ""))
    _, stats = build_stat_list(partner)
    return render_task("pair_reaction", actor=actor, partner=partner, action=action, piece=piece,
                       language=language_name(lang), situation=state["situation"],
                       relationship=state["relationship"], stats=stats)


def _react(kind: str, reference: str, actor: str, partner: str) -> None:
    try:
        prompt = reaction_prompt(kind, reference, actor, partner)
        if prompt is None:
            return
        from app.core import llm_router
        response = llm_router.llm_call(task="pair_reaction", system_prompt=prompt[0], user_prompt=prompt[1],
                                       agent_name=partner, label=f"Pair reaction ({partner})",
                                       max_tokens=_MAX_TOKENS)
        text = getattr(response, "content", response)
        parsed = parse_reaction(text if isinstance(text, str) else "")
        if parsed is None:
            logger.warning("pair reaction of %s: no usable answer: %.200r", partner, text)
            return
        accept, line, feeling, romantic = parsed
        from app.core import pair_reaction
        result = pair_reaction.answer(kind, reference, partner, accept, line=line,
                                      feeling=feeling, romantic=romantic)
        logger.info("pair reaction of %s to %s: %s (feeling %d) -> %s", partner, actor,
                    "accept" if accept else "resist", feeling, result.get("status"))
    except Exception as e:
        logger.warning("pair reaction of %s failed: %s", partner, e)
