"""The ``pair_reaction`` provider: how an NPC reacts to a furniture pair
action started WITHOUT asking (requested with ``consent="react"``).

The core starts the run at once and waits at the furniture for the answer
(``prop_action_engine.REACTION_WAIT_S``); this module asks the model in a
thread of its own and hands the answer to ``prop_action_engine.react``.
Anything that goes wrong just leaves the answer out — the run then goes on
as accepted once the wait runs out.
"""
import json
import threading

from app.core.log import get_logger

logger = get_logger("interact.reaction")

#: The answer is one sentence plus four JSON fields.
_MAX_TOKENS = 220


def ask_reaction(*, execution_id: str, actor: str, partner: str) -> None:
    """Provider entry: returns at once, the model runs in a thread."""
    threading.Thread(target=_react, args=(execution_id, actor, partner),
                     name=f"pair-reaction-{execution_id[:8]}", daemon=True).start()


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


def reaction_prompt(execution_id: str, actor: str, partner: str):
    """``(system, user)`` for the run, or None when it no longer waits."""
    from app.core import prop_action_store as runs
    from app.core.decision_points import invite_state
    from app.core.i18n import language_name, localized
    from app.core.prompt_templates import render_task
    from app.core.prop_actions import piece_label
    from app.core.stat_effects import build_stat_list
    from app.models.character import get_character_language
    run = runs.get(execution_id)
    if (not run or run["partner"] != partner or run["actor"] != actor
            or (run["data"].get("reaction") or {}).get("state") != "pending"):
        return None
    lang = get_character_language(actor)
    action = localized(run["definition"], "name", lang) or run["definition"].get("name") or ""
    piece = piece_label(run["target"], lang)
    state = invite_state(partner, actor, f'to "{action}"' + (f" on {piece}" if piece else ""))
    _, stats = build_stat_list(partner)
    return render_task("pair_reaction", actor=actor, partner=partner, action=action, piece=piece,
                       language=language_name(lang), situation=state["situation"],
                       relationship=state["relationship"], stats=stats)


def _react(execution_id: str, actor: str, partner: str) -> None:
    try:
        prompt = reaction_prompt(execution_id, actor, partner)
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
        from app.core import prop_action_engine
        result = prop_action_engine.react(partner, execution_id, accept, line=line,
                                          feeling=feeling, romantic=romantic)
        logger.info("pair reaction of %s to %s: %s (feeling %d) -> %s", partner, actor,
                    "accept" if accept else "resist", feeling, result.get("status"))
    except Exception as e:
        logger.warning("pair reaction of %s failed: %s", partner, e)
