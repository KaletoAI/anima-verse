"""Boot migration: strip DEAD appearance tokens out of stored prompt texts.

Why this exists
---------------
The body-slot migration bc98b6a (2026-07-08) deleted the appearance select
fields and their ``replacement`` blocks from the character templates — the
body slots carry hair/eyes/skin/build now. Its on-demand tool cleaned the
already-stored texts of the worlds it ran on, but the templates' field
``default`` strings kept naming the removed tokens. Every character created
after that day inherited a default full of tokens nobody resolves, so
``{skin_color}``/``{size}``/... reached previews, image prompts and (via the
default fallback in ``build_prompt_section``) the chat system prompt
literally. The defaults are fixed; this migration repairs what was saved.

The retired tool (app/core/body_slot_migration.py, removed in a297c3b)
derived its token list from the packages' ``migrate_from`` declarations,
which are gone as well — so the list below is pinned to what the shipped
templates actually seeded, and the segment cleanup keeps that tool's logic:
the texts are comma-segment lists, a segment that carries nothing but the
dead token plus attribute glue words is dropped whole, a segment with real
content of its own keeps that content.

Idempotent, world_kv-marked (own guard key — the retired tool had none),
never renames: ``{size}`` is dropped, NOT turned into the living ``{height}``
token; the body slots and the height field supply that information now.
"""
import re
from typing import Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("appearance_token_migration")

_GUARD_KEY = "migrated_dead_appearance_tokens"

_TEXT_FIELDS = ("character_appearance", "face_appearance")

# Exactly the tokens the shipped templates seeded and no template declares
# any more: human-roleplay (character_appearance + face_appearance) and
# animal-default (character_appearance). A living token — gender, age,
# height, species, breed — is never in this set.
DEAD_TOKENS = (
    "animal_size", "body_type", "eye_color", "fur_type", "hair_color",
    "hair_length", "pattern", "primary_color", "size", "skin_color",
)

# Glue words carry no information without their token ("{hair_color} hair"
# -> "hair"): a segment whose remainder is only glue is dropped entirely.
# Taken from the retired body-slot migration, trimmed to the vocabulary the
# dead tokens above appear with.
_GLUE_WORDS = {
    "hair", "haare", "haar", "eyes", "eye", "augen", "auge", "skin", "haut",
    "colored", "coloured", "color", "colour", "farbe", "farbene", "farbige",
    "build", "built", "body", "frame", "height", "figur", "statur",
    "körperbau", "koerperbau",
    "fur", "fell", "pelz", "ears", "ohren", "tail", "schwanz", "markings",
}

_PATTERNS = [re.compile(r"\{" + re.escape(t) + r"\}") for t in DEAD_TOKENS]


def strip_dead_tokens(text: str) -> Tuple[str, List[str]]:
    """Remove the dead tokens from one appearance text.

    Splits on ", " only (a decimal comma like "1,20" stays intact). Returns
    the cleaned text plus a human-readable list of what happened per segment.
    Running it again on its own output changes nothing.
    """
    if not text or "{" not in text:
        return text, []
    keep: List[str] = []
    dropped: List[str] = []
    changed = False
    for seg in re.split(r",\s", text):
        if not any(p.search(seg) for p in _PATTERNS):
            keep.append(seg.strip())
            continue
        changed = True
        cleaned = seg
        for p in _PATTERNS:
            cleaned = p.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—")
        words = re.findall(r"[\wäöüÄÖÜß{}]+", cleaned)
        substantial = [w for w in words if w.lower() not in _GLUE_WORDS]
        if cleaned and substantial:
            keep.append(cleaned)
            dropped.append(f"{seg.strip()} → {cleaned}")
        else:
            dropped.append(seg.strip())
    if not changed:
        return text, []
    return ", ".join(s for s in keep if s), dropped


def migrate_dead_appearance_tokens_once() -> Dict[str, int]:
    """Clean every character's appearance/face prompt once per world.

    Reads no template — the token list is pinned above — so boot order does
    not matter; it only needs the world DB.
    """
    result = {"characters": 0, "texts": 0}
    try:
        from app.models.world import get_world_setting, set_world_setting
        from app.models.character import (list_available_characters,
                                          get_character_profile,
                                          save_character_profile)
        if get_world_setting(_GUARD_KEY):
            return result
        for name in list_available_characters():
            profile = get_character_profile(name) or {}
            touched = False
            for field in _TEXT_FIELDS:
                text = str(profile.get(field) or "")
                new, dropped = strip_dead_tokens(text)
                if not dropped:
                    continue
                profile[field] = new
                touched = True
                result["texts"] += 1
                logger.info("Dead tokens removed from %s.%s: %s | now: %r",
                            name, field, "; ".join(dropped), new)
            if touched:
                save_character_profile(name, profile)
                result["characters"] += 1
        set_world_setting(_GUARD_KEY, "1")
    except Exception as e:
        logger.warning("Dead-appearance-token migration failed: %s", e)
    return result
