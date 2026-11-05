"""The avatar's spoken phrases — ``play.say_intercept`` provider.

When the avatar — a LEADER holding the power item of one of its definitions
— says that definition's activation phrase, or the avatar is a BODY standing
in the world for its leader and says the revert phrase of the running
transformation, the message never reaches the room: the avatar's words become
a private line for the avatar and the present knowers, then the swap runs (the
player is switched to the other family member by the swap itself). A refusal
(already transformed, cooldown, a swap refusal state, ...) adds a storyteller
hint for the avatar alone. Non-knowers perceive nothing of it.

Matching: message and phrase are casefolded, split on whitespace, each word
stripped of punctuation at both ends; the phrase must appear as a contiguous
word sequence of the message. An empty phrase never matches.
"""
from __future__ import annotations

import string
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.perception import addressable_for, record_private_line
from app.core.prompt_templates import render

from plugins.transformation import definitions, engine, knowers
from plugins.transformation.definitions import Definition
from plugins.transformation.skill import held_definitions, present_body_row

logger = get_logger("transformation")

_PUNCT = string.punctuation + "…‘’“”«»„¡¿–—"


def words(text: str) -> List[str]:
    """The normalized words of ``text`` (casefold, punctuation-trimmed)."""
    return [w for w in (t.strip(_PUNCT) for t in (text or "").casefold().split()) if w]


def contains_phrase(message_words: List[str], phrase: str) -> bool:
    """Whether ``phrase`` appears as a contiguous word run of the message."""
    needle = words(phrase)
    if not needle:
        return False
    n = len(needle)
    return any(message_words[i:i + n] == needle for i in range(len(message_words) - n + 1))


def _match(avatar: str, message_words: List[str]) -> Optional[tuple]:
    """``(definition, action)`` for the first matching phrase — action
    ``transform``, ``revert`` or ``refuse:<reason>`` (a phrase that cannot act)."""
    row = present_body_row(avatar)
    if row is not None:
        worn = definitions.load().get(row.def_id)
        for d in [worn] if worn else []:
            if contains_phrase(message_words, d.revert_phrase):
                return d, "revert"
        for d in definitions.for_body(avatar):
            if contains_phrase(message_words, d.activation_phrase):
                return d, "refuse:already_transformed"
        return None
    held = held_definitions(avatar)
    for d in held:
        if contains_phrase(message_words, d.activation_phrase):
            return d, "transform"
    for d in held:
        if contains_phrase(message_words, d.revert_phrase):
            return d, "refuse:not_transformed"
    return None


def _act(avatar: str, d: Definition, action: str) -> Dict[str, Any]:
    if action == "transform":
        return engine.transform(avatar, d.id, source="phrase")
    if action == "revert":
        return engine.revert(d.leader, reason="phrase")
    return {"ok": False, "reason": action.split(":", 1)[1], "error": ""}


def say_intercept(*, avatar: str, content: str, volume: str, addressees: List[str],
                  location_id: str, room_id: str) -> Optional[Dict[str, Any]]:
    """Consume a phrase message; ``None`` lets the message go the ordinary way."""
    if not avatar or not content:
        return None
    message_words = words(content)
    if not message_words:
        return None
    found = _match(avatar, message_words)
    if found is None:
        return None
    d, action = found
    present = [n for n in addressable_for(avatar) if knowers.knows(n, d.body)]
    meta = {"transformation": "phrase", "def_id": d.id}
    record_private_line(recipients=[avatar, *present], content=content, speaker=avatar,
                        location_id=location_id, room_id=room_id,
                        source="transformation:phrase", perception_meta=meta)
    result = _act(avatar, d, action)
    if not result.get("ok"):
        try:
            hint = render("transformation/phrase_refused.md",
                          reason=str(result.get("reason") or ""), body=d.body,
                          error=str(result.get("error") or ""))
        except Exception as e:  # noqa: BLE001 — the refusal stands without its hint
            logger.warning("phrase refusal hint for %s failed: %s", avatar, e)
            hint = ""
        if hint:
            record_private_line(recipients=[avatar], content=hint,
                                location_id=location_id, room_id=room_id,
                                source="transformation:phrase",
                                perception_meta={**meta, "reason": result.get("reason", "")})
    logger.info("%s said the %s phrase of %s (ok=%s, reason=%s)", avatar, action, d.id,
                result.get("ok"), result.get("reason"))
    return {"consumed": True, "result": {"kind": "transformation",
                                         "ok": bool(result.get("ok")),
                                         "reason": str(result.get("reason") or ""),
                                         "body": d.body,
                                         "error": str(result.get("error") or "")}}
