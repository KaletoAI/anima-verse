"""The avatar's spoken phrases — ``play.say_intercept`` provider.

When the avatar says a persona's activation phrase (or, while wearing it,
its revert phrase) the message never reaches the room: the avatar's words
become a private line for the avatar and the present knowers, then the
transformation runs. A refusal (already transformed, cooldown, ...) adds a
storyteller hint for the avatar alone. Non-knowers perceive nothing of it.

Matching: message and phrase are casefolded, split on whitespace, each word
stripped of punctuation at both ends; the phrase must appear as a contiguous
word sequence of the message. An empty phrase never matches. Only personas
whose power item the avatar carries count (the revert phrase of the worn
persona counts as long as it is worn).
"""
from __future__ import annotations

import string
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.perception import addressable_for, record_private_line
from app.core.prompt_templates import render
from app.models.inventory import get_carried_item_ids

from plugins.transformation import definitions, engine, knowers, store
from plugins.transformation.definitions import Definition

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
    """``(definition, "transform" | "revert")`` for the first matching phrase."""
    defs = definitions.load()
    if not defs:
        return None
    row = store.get_active(avatar)
    worn = defs.get(row.persona_id) if row is not None else None
    if worn is not None and contains_phrase(message_words, worn.revert_phrase):
        return worn, "revert"
    carried = get_carried_item_ids(avatar)
    held = [d for d in defs.values() if d.item_id in carried]
    for d in held:
        if contains_phrase(message_words, d.activation_phrase):
            return d, "transform"
    for d in held:
        if contains_phrase(message_words, d.revert_phrase):
            return d, "revert"
    return None


def _act(avatar: str, d: Definition, action: str) -> Dict[str, Any]:
    if action == "transform":
        return engine.transform(avatar, d.id, source="phrase")
    row = store.get_active(avatar)
    if row is None or row.persona_id != d.id:
        return {"ok": False, "reason": "not_transformed", "alias": d.alias}
    ok = engine.revert(avatar, reason="phrase")
    return {"ok": ok, "reason": "" if ok else "not_transformed", "alias": d.alias}


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
    present = [n for n in addressable_for(avatar) if knowers.knows(n, avatar, d.id)]
    meta = {"transformation": "phrase", "persona_id": d.id}
    record_private_line(recipients=[avatar, *present], content=content, speaker=avatar,
                        location_id=location_id, room_id=room_id,
                        source="transformation:phrase", perception_meta=meta)
    result = _act(avatar, d, action)
    if not result.get("ok"):
        try:
            hint = render("transformation/phrase_refused.md",
                          reason=str(result.get("reason") or ""), alias=d.alias)
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
                                         "alias": str(result.get("alias") or d.alias)}}
