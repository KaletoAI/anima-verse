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


_MODE_IN_CHAT = ("Mode: in the middle of a conversation with the player — by default the "
                 "character stays quiet (SKIP) unless a clear step in the conversation is needed.")
_MODE_OWN = ("Mode: on their own — the character acts only if something relevant is there "
             "to do or say.")


def thought_state(ctx: Dict[str, Any], *, in_chat: Optional[bool] = False) -> Dict[str, str]:
    """The situation of an idle thought turn as ONE text, at most
    THOUGHT_STATE_MAX_CHARS — built from the thought context the turn already has.
    ``in_chat``: True = the turn runs on the in-chat template, whose default is
    SKIP; False = the character is on their own — the mode line tells the model
    (a header line, never cut). None = no mode line (a state that is not an idle
    thought turn, e.g. an invitation)."""
    lines = [
        f"Character: {ctx.get('character_name') or ''}",
        f"Place: {ctx.get('location_name') or ''}",
        f"Doing: {ctx.get('activity') or ''}",
        f"Mood: {ctx.get('feeling') or ''}",
        f"Time: {ctx.get('time_of_day') or ''}, {ctx.get('game_date') or ''}",
    ]
    if in_chat is not None:
        lines.append(_MODE_IN_CHAT if in_chat else _MODE_OWN)
    header = "\n".join(lines)
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
    own true/false labels rather than the state (model card, issue #156). The
    texts ask the thought template's own question — act, or reply SKIP."""
    return {"turn": Choice(
        instructions=f"Would {name} do or say something now, or reply SKIP?",
        options={
            "act": (f"act: something relevant is there for {name} to do or say right now "
                    f"(a message to answer, a due plan, someone addressing {name}, "
                    f"something new)"),
            "idle": (f"SKIP: nothing relevant right now — {name} would stay quiet and "
                     f"let the moment pass"),
        })}


# ── Catalog matching (§ 4.2) ─────────────────────────────────────────────

POSE_MATCH = "pose_match"
EXPRESSION_MATCH = "expression_match"
CATALOG_POINTS = {"pose": POSE_MATCH, "expression": EXPRESSION_MATCH}
NONE_KEY = "none"
_NONE_TEXT = "none of these fits the text"
# An entry's description (``prompt``) is offered only in questions this small —
# a big question (the pose groups) keeps its options short.
_PROMPT_MAX_OPTIONS = 12
_GROUP_EXAMPLES_MAX = 10  # the default included
_GROUP_INSTRUCTIONS = ("Which body position does the text describe? "
                       "Each option lists poses of that position.")
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


def _option_budget(n: int) -> int:
    """Characters one option text may use in a question of ``n`` options:
    few options get room for a real description, many stay short."""
    return max(80, min(220, 1400 // max(1, n)))


def _cut_words(text: str, budget: int) -> str:
    """``text`` within ``budget`` chars, cut at a word boundary when possible."""
    if len(text) <= budget:
        return text
    cut = text[:budget]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:")


def _fit_list(prefix: str, items, budget: int) -> str:
    """``prefix`` + as many of ``items`` (", "-joined, in order) as fit ``budget``;
    stops at the first one that does not fit."""
    text, used = prefix, 0
    for item in items:
        nxt = text + (", " if used else "") + str(item)
        if len(nxt) > budget:
            break
        text, used = nxt, used + 1
    return text


def _catalog_option(key: str, entry: Dict[str, Any], budget: int, with_prompt: bool) -> str:
    """``<key>: <prompt>; e.g. <synonyms>`` when ``with_prompt`` and the entry has
    a prompt, else ``<key>: <synonyms>`` — as many synonyms as fit ``budget``."""
    synonyms = entry.get("synonyms") or []
    prompt = str(entry.get("prompt") or "").strip() if with_prompt else ""
    if prompt:
        head = _cut_words(f"{key}: {prompt}", budget)
        text = _fit_list(f"{head}; e.g. ", synonyms, budget)
        return head if text.endswith("; e.g. ") else text
    text = _fit_list(f"{key}: ", synonyms, budget)
    return key if text == f"{key}: " else text


def _spread(keys, k: int) -> list:
    """``k`` of ``keys`` spread evenly from the first to the last (index
    i * (n-1) / (k-1), rounded half up) — a sample of the whole list, not its head."""
    n = len(keys)
    if k <= 0 or n == 0:
        return []
    if k == 1:
        return [keys[0]]
    return [keys[(2 * i * (n - 1) + (k - 1)) // (2 * (k - 1))] for i in range(k)]


def _group_option(label: str, examples, budget: int) -> str:
    """``<label>: <default>, <pose>, …`` — the group named by its poses: the
    default (first of ``examples``) and up to _GROUP_EXAMPLES_MAX - 1 of the
    rest spread evenly over it, as many as fit ``budget``."""
    keys = [k for k in examples if k != NONE_KEY]
    if not keys:
        return label
    head, rest = keys[0], keys[1:]
    for k in range(min(_GROUP_EXAMPLES_MAX - 1, len(rest)), -1, -1):
        text = f"{label}: " + ", ".join([head] + _spread(rest, k))
        if len(text) <= budget:
            return text
    return label


def catalog_questions(axis: str) -> Tuple[Dict[str, Choice], Optional[Callable]]:
    """Questions for mapping a text onto the catalog of ``axis``. With place
    groups (pose): step 1 asks the group, ``then`` asks the entries of THAT
    group (openjev scores every option on its own, so fewer options = faster).
    Without groups: one question over all entries. Every entry question offers
    NONE_KEY. Option texts share the budget of ``_option_budget(n)``: a group is
    described by its poses, an entry by its ``prompt`` + synonyms in a small
    question (≤ _PROMPT_MAX_OPTIONS options), by its synonyms alone otherwise."""
    from app.core.pose_catalog import get_catalog, get_groups, poses_in_group
    entries = get_catalog(axis)
    grouped: Dict[str, Dict[str, Any]] = {}
    for k, e in entries.items():
        grouped.setdefault(e.get("group") or "", {})[k] = e

    def entry_question(subset: Dict[str, Any]) -> Dict[str, Choice]:
        n = len(subset) + (0 if NONE_KEY in subset else 1)
        budget, with_prompt = _option_budget(n), n <= _PROMPT_MAX_OPTIONS
        opts = {k: _catalog_option(k, e, budget, with_prompt) for k, e in subset.items()}
        if NONE_KEY not in opts:
            opts[NONE_KEY] = _NONE_TEXT
        return {"entry": Choice(instructions=_ENTRY_INSTRUCTIONS.get(axis, "Which entry fits best?"),
                                options=opts)}

    groups = get_groups() if axis == "pose" else {}
    usable = {g: spec for g, spec in groups.items() if g in grouped}
    if len(usable) >= 2 and "" not in grouped:
        budget = _option_budget(len(usable))
        first = {"group": Choice(
            instructions=_GROUP_INSTRUCTIONS,
            options={g: _group_option(str(spec.get("label") or g), poses_in_group(g), budget)
                     for g, spec in usable.items()})}

        def then(answers: Dict[str, Answer]) -> Optional[Dict[str, Choice]]:
            g = answers.get("group")
            if g is None or g.value not in grouped:
                return None
            return entry_question(grouped[g.value])

        return first, then
    return entry_question(entries), None


# ── Invitations (helpers for the packages' accept/decline points) ─────

def _strength_band(strength: int) -> str:
    """Decision models are weak with numbers — the strength also as a word."""
    if strength >= 60:
        return "strong"
    if strength >= 30:
        return "moderate"
    return "weak"


def _relationship_line(invitee: str, inviter: str) -> str:
    """How the INVITEE stands with the INVITER, in one sentence. Never raises."""
    neutral = f"{invitee} and {inviter} do not know each other well yet."
    try:
        from app.models.relationship import (TYPE_LABELS, get_relationship,
                                             sentiment_label)
        rel = get_relationship(invitee, inviter)
        if not rel:
            return neutral
        # The row keeps the pair in stored order: a_to_b is character_a's
        # feeling toward character_b. Pick the invitee's own direction.
        if str(rel.get("character_a") or "").lower() == invitee.lower():
            sentiment = rel.get("sentiment_a_to_b", 0.0)
        else:
            sentiment = rel.get("sentiment_b_to_a", 0.0)
        rtype = str(rel.get("type") or "neutral")
        label = TYPE_LABELS.get(rtype, rtype).lower()
        strength = int(rel.get("strength") or 0)
        return (f"{invitee} toward {inviter}: {label}, {_strength_band(strength)} bond "
                f"({strength}/100), feels {sentiment_label(sentiment)} about {inviter}.")
    except Exception:
        return neutral


def invite_state(invitee: str, inviter: str, offer: str) -> Dict[str, str]:
    """State for an accept/decline decision of an invited NPC: its own
    situation (thought_state), the offer, and how it stands with the inviter."""
    from app.core.thought_context import build_thought_context
    state = thought_state(build_thought_context(invitee), in_chat=None)
    state["offer"] = f"{inviter} invites {invitee} {offer}"
    state["relationship"] = _relationship_line(invitee, inviter)
    return state


def invite_questions(invitee: str, inviter: str) -> Dict[str, Choice]:
    """One Choice 'answer' with the neutral keys accept / decline."""
    return {"answer": Choice(
        instructions=f"Does {invitee} accept {inviter}'s invitation?",
        options={"accept": f"yes: {invitee} wants to and agrees",
                 "decline": f"no: {invitee} would rather not and refuses"})}
