"""Facts about THIS moment that shape how long a reply should be.

This module only collects and formats FACTS — how big the incoming line was,
what role the character carries, its mood, how it stands to the partner.
The interpretation ("a brief line deserves a brief answer") lives exactly once
in the chat template (``shared/templates/llm/chat/chat_stream.md``); no
threshold and no length instruction is written here.

Two asymmetries are deliberate:

* **Popularity is the PARTNER's** — it says how much attention the speaker
  draws from the responder, so it is read from the partner's config.
* **Trustworthiness is the responder's OWN** — it is rendered as discretion
  about third parties, i.e. how freely this character talks about others.

The incoming message is classified by SIZE only (plus a trailing question
mark). Never by keywords: whether a line is an order, a plea or small talk
the LLM reads from the message itself.

Every world read is guarded — a missing fact yields an empty section, never
an exception, because the chat must not die over a fact.
"""
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Tier boundaries for 0-100 character values (popularity, trustworthiness)
TIER_LOW_BELOW = 34      # value < 34  -> low
TIER_HIGH_FROM = 67      # value >= 67 -> high

# Size classes of the incoming message, counted in spoken words
BRIEF_MAX_WORDS = 12     # <= 12 spoken words -> "brief"
LONG_MIN_WORDS = 45      # >= 45 spoken words -> "long"

# *action* segments are not spoken words
_ACTION_RE = re.compile(r"\*[^*]*\*", re.DOTALL)

# Wording for the partner's pull on this character's attention
_ATTENTION_WORDS = {
    "low": "little",
    "average": "somewhat",
    "high": "a lot",
}


def classify_incoming(text: str) -> dict:
    """Size class of the incoming message.

    Returns ``{"kind": "" | "brief" | "normal" | "long", "question": bool}``.
    Spoken words = whitespace tokens after removing *action* segments
    (asterisk-delimited). Empty/whitespace text -> kind "". Non-empty text
    whose spoken words are all inside ``*…*`` (a pure action) -> "brief".
    ``question`` = the spoken text (after stripping) ends with "?".
    """
    raw = (text or "").strip()
    if not raw:
        return {"kind": "", "question": False}

    spoken = _ACTION_RE.sub(" ", raw).strip()
    count = len(spoken.split())

    if count <= BRIEF_MAX_WORDS:
        kind = "brief"
    elif count >= LONG_MIN_WORDS:
        kind = "long"
    else:
        kind = "normal"

    return {"kind": kind, "question": spoken.endswith("?")}


def tier(value: Any, default: int = 50) -> str:
    """"low" | "average" | "high" for a 0-100 number; None/invalid -> default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if number < TIER_LOW_BELOW:
        return "low"
    if number >= TIER_HIGH_FROM:
        return "high"
    return "average"


def compose_reply_shape(facts: Dict[str, Any]) -> str:
    """Format the facts as the 'This moment' bullet list (English).

    facts keys (all optional, missing/empty -> line omitted):
      incoming_kind: "brief"|"normal"|"long"    incoming_question: bool
      on_duty: str (role tags / standing task)  activity: str
      mood: str
      partner: str
      relationship: {"type": str, "closeness": int, "feeling": str}
                     (None -> "no relationship yet" line when partner given)
      partner_attention: "low"|"average"|"high"
      discretion: "low"|"average"|"high"
    Returns "" when no line at all would be emitted.
    """
    facts = facts or {}
    partner = (facts.get("partner") or "").strip()
    question = bool(facts.get("incoming_question"))
    lines = []

    kind = (facts.get("incoming_kind") or "").strip()
    if kind == "brief":
        lines.append("- The incoming line is a brief question."
                     if question else "- The incoming line is brief.")
    elif kind == "normal":
        lines.append("- The incoming line is a question of normal length."
                     if question else "- The incoming line is of normal length.")
    elif kind == "long":
        who = partner or "the other person"
        line = f"- The incoming line is long — {who} had a lot to say."
        if question:
            line += " It ends in a question."
        lines.append(line)

    on_duty = (facts.get("on_duty") or "").strip()
    if on_duty:
        line = f"- Your role: {on_duty}."
        activity = (facts.get("activity") or "").strip()
        if activity:
            line += f" Right now: {activity}."
        lines.append(line)

    mood = (facts.get("mood") or "").strip()
    if mood:
        lines.append(f"- Your mood: {mood}.")

    if partner:
        rel = facts.get("relationship")
        if rel:
            lines.append(
                f"- Relationship with {partner}: {rel.get('type', '')}, "
                f"closeness {rel.get('closeness', 0)}/100, "
                f"you feel {rel.get('feeling', '')} about them."
            )
        else:
            lines.append(f"- You have no relationship with {partner} yet — a stranger.")

        attention = _ATTENTION_WORDS.get((facts.get("partner_attention") or "").strip())
        if attention:
            lines.append(f"- {partner} draws your attention: {attention}.")

    discretion = (facts.get("discretion") or "").strip()
    if discretion:
        lines.append(f"- Your discretion about other people: {discretion}.")

    return "\n".join(lines)


def build_reply_shape_section(character_name: str, partner_name: str = "",
                              incoming_text: str = "") -> str:
    """Load the facts from the world (profile, config, relationship) and
    return compose_reply_shape(...). Never raises."""
    try:
        from app.models.character import get_character_config, get_character_profile

        profile = get_character_profile(character_name) or {}
        config = get_character_config(character_name) or {}

        roles = (config.get("roles") or "").strip()
        if roles:
            on_duty = ", ".join(part.strip() for part in roles.split(",") if part.strip())
        else:
            on_duty = (profile.get("standing_task") or "").strip()

        incoming = classify_incoming(incoming_text)
        facts: Dict[str, Any] = {
            "incoming_kind": incoming["kind"],
            "incoming_question": incoming["question"],
            "on_duty": on_duty,
            "activity": (profile.get("current_activity") or "").strip(),
            "mood": (profile.get("current_feeling") or "").strip(),
            "discretion": tier(config.get("trustworthiness")),
        }

        if partner_name and partner_name.lower() != character_name.lower():
            from app.models.relationship import (
                TYPE_LABELS,
                get_relationship,
                sentiment_label,
            )

            partner_config = get_character_config(partner_name) or {}
            facts["partner"] = partner_name
            facts["partner_attention"] = tier(partner_config.get("popularity"))

            rel = get_relationship(character_name, partner_name)
            if rel:
                if (rel.get("character_a") or "").lower() == character_name.lower():
                    my_sentiment = rel.get("sentiment_a_to_b", 0)
                else:
                    my_sentiment = rel.get("sentiment_b_to_a", 0)
                facts["relationship"] = {
                    "type": TYPE_LABELS.get(rel.get("type", "neutral"), "Known"),
                    "closeness": int(rel.get("strength", 0) or 0),
                    "feeling": sentiment_label(my_sentiment),
                }
            else:
                facts["relationship"] = None

        return compose_reply_shape(facts)
    except Exception as exc:  # pragma: no cover - a missing fact must never break chat
        logger.debug("reply shape unavailable for %s: %s", character_name, exc)
        return ""
