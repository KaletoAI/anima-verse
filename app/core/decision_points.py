"""The core's decision points (development_instructions/plan-decision-models.md § 4).

Imported once at boot (app/server.py); registration happens at import. Each
point keeps its question and state builders here, so the call sites stay a
few lines. Plugins register their own points from their ``on_load`` module.
"""
from typing import Any, Dict

from app.core.decision import Choice, register_point

THOUGHT_SKIP = "thought_skip"
THOUGHT_STATE_MAX_CHARS = 2500

register_point(
    THOUGHT_SKIP,
    label="Idle thought: skip?",
    description=("Before an idle thought turn of the agent loop (no perception, no hint, "
                 "nothing unread): will the turn end with SKIP? In mode 'on' an 'idle' "
                 "answer with enough confidence skips the LLM turn."),
    default_min_confidence=0.8,
    default_timeout_s=2.0,
)

# Order the blocks appear in (chat last: the newest context closest to the end).
_THOUGHT_BLOCKS = ("present_people_block", "elsewhere_block", "daily_schedule_block",
                   "recent_thoughts", "recent_chat_block")
# Order they are CUT in when the state is too long — least important first.
_THOUGHT_CUT_ORDER = ("recent_thoughts", "daily_schedule_block", "elsewhere_block",
                      "present_people_block", "recent_chat_block")


def _cut_front(block: str, over: int) -> str:
    """Drop whole lines from the FRONT (oldest first) until ``over`` chars are gone."""
    lines = block.splitlines()
    removed = 0
    while lines and removed < over:
        removed += len(lines.pop(0)) + 1
    return "\n".join(lines)


def thought_state(ctx: Dict[str, Any]) -> Dict[str, str]:
    """The situation of an idle thought turn as ONE text, at most
    THOUGHT_STATE_MAX_CHARS — built from the thought context the turn already has."""
    header = "\n".join([
        f"Character: {ctx.get('character_name') or ''}",
        f"Place: {ctx.get('location_name') or ''}",
        f"Doing: {ctx.get('activity') or ''}",
        f"Mood: {ctx.get('feeling') or ''}",
        f"Time: {ctx.get('time_of_day') or ''}, {ctx.get('game_date') or ''}",
    ])
    blocks = {k: str(ctx.get(k) or "").strip() for k in _THOUGHT_BLOCKS}

    def compose() -> str:
        return "\n\n".join([header] + [blocks[k] for k in _THOUGHT_BLOCKS if blocks[k]])

    text = compose()
    for k in _THOUGHT_CUT_ORDER:
        over = len(text) - THOUGHT_STATE_MAX_CHARS
        if over <= 0:
            break
        blocks[k] = _cut_front(blocks[k], over)
        text = compose()
    return {"situation": text[:THOUGHT_STATE_MAX_CHARS]}


def thought_questions(name: str) -> Dict[str, Choice]:
    """Neutral keys instead of a yes/no question: Laya's noul can follow its
    own true/false labels rather than the state (model card, issue #156)."""
    return {"turn": Choice(
        instructions=f"Does {name} have a reason to act or speak right now?",
        options={
            "act": f"yes: someone addressed {name}, something new happened, or a plan is due now",
            "idle": f"no: nothing new, {name} would not do anything meaningful right now",
        })}
