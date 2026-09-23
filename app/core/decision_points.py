"""The core's decision points (development_instructions/plan-decision-models.md § 4).

Imported once at boot (app/server.py); registration happens at import. Each
point keeps its question and state builders here, so the call sites stay a
few lines. Plugins register their own points from their ``on_load`` module.
"""
from typing import Any, Callable, Dict, Optional, Tuple

from app.core.decision import Answer, Choice, register_point

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


# ── Catalog matching (§ 4.2) ─────────────────────────────────────────────

POSE_MATCH = "pose_match"
EXPRESSION_MATCH = "expression_match"
CATALOG_POINTS = {"pose": POSE_MATCH, "expression": EXPRESSION_MATCH}
NONE_KEY = "none"
_OPTION_DESC_MAX = 80
_ENTRY_INSTRUCTIONS = {
    "pose": "Which pose fits the text best?",
    "expression": "Which facial expression fits the text best?",
}

register_point(
    POSE_MATCH,
    label="Pose text → catalog key",
    description=("Maps a free pose text onto a pose catalog key (body position first, then "
                 "the pose). In mode 'on' a confident key wins over the embedding match; "
                 "'none' records the text as a catalog candidate."),
    default_min_confidence=0.6,
    default_timeout_s=6.0,
)
register_point(
    EXPRESSION_MATCH,
    label="Mood text → expression key",
    description=("Maps a free mood text onto an expression catalog key. In mode 'on' a "
                 "confident key wins over the embedding match."),
    default_min_confidence=0.6,
    default_timeout_s=6.0,
)


def _catalog_option(key: str, entry: Dict[str, Any]) -> str:
    syn = ", ".join((entry.get("synonyms") or [])[:3])
    return (f"{key}: {syn}" if syn else key)[:_OPTION_DESC_MAX]


def catalog_questions(axis: str) -> Tuple[Dict[str, Choice], Optional[Callable]]:
    """Questions for mapping a text onto the catalog of ``axis``. With place
    groups (pose): step 1 asks the group, ``then`` asks the entries of THAT
    group (openjev scores every option on its own, so fewer options = faster).
    Without groups: one question over all entries. Every entry question offers
    NONE_KEY ("none of these fits")."""
    from app.core.pose_catalog import get_catalog, get_groups
    entries = get_catalog(axis)
    grouped: Dict[str, Dict[str, Any]] = {}
    for k, e in entries.items():
        grouped.setdefault(e.get("group") or "", {})[k] = e

    def entry_question(subset: Dict[str, Any]) -> Dict[str, Choice]:
        opts = {k: _catalog_option(k, e) for k, e in subset.items()}
        if NONE_KEY not in opts:
            opts[NONE_KEY] = "none of these fits"
        return {"entry": Choice(instructions=_ENTRY_INSTRUCTIONS.get(axis, "Which entry fits best?"),
                                options=opts)}

    groups = get_groups() if axis == "pose" else {}
    usable = {g: spec for g, spec in groups.items() if g in grouped}
    if len(usable) >= 2 and "" not in grouped:
        first = {"group": Choice(
            instructions="Which body position does the text describe?",
            options={g: str(spec.get("label") or g) for g, spec in usable.items()})}

        def then(answers: Dict[str, Answer]) -> Optional[Dict[str, Choice]]:
            g = answers.get("group")
            if g is None or g.value not in grouped:
                return None
            return entry_question(grouped[g.value])

        return first, then
    return entry_question(entries), None
