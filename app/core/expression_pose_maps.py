"""Expression & pose prompt lookups — a thin adapter over the catalogs.

The catalog entry key (``app/core/pose_catalog.py``) is the ONE render key:
image prompts, the 3D animation kind and the variant cache all key off it.
Everything here is an exact dict access — no substring matching, no LLM
preset generation, no ``*_generated.json`` files. Free text is mapped onto a
key exactly once, by ``pose_catalog.resolve_to_catalog`` (pose: at the write
path in ``character.set_pose_intent``; expression: by
``resolve_expression_key`` below, because a mood is never stored as a key).
"""

from typing import Dict

from app.core.log import get_logger
from app.core.pose_catalog import (
    get_catalog,
    get_default_key,
    reload_catalogs,
    resolve_to_catalog,
)

logger = get_logger(__name__)


def _default_entry(axis: str) -> dict:
    """The catalog's ``_default`` entry — ``{}`` when the catalog is empty."""
    return get_catalog(axis).get(get_default_key(axis)) or {}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def default_pose_prompt() -> str:
    """Default pose prompt: admin override or the catalog's default entry.

    The admin setting (``image_generation.default_pose_prompt``, editable at
    /admin/settings) wins when set; empty means the ``_default`` entry of
    ``pose_catalog.json``. Read fresh on every call so config changes apply
    without a restart."""
    try:
        from app.core import config
        override = (config.get("image_generation.default_pose_prompt", "") or "").strip()
        if override:
            return override
    except Exception:
        pass
    return _default_entry("pose").get("prompt", "")


def default_expression_prompt() -> str:
    """Default expression prompt: the ``_default`` entry of the expression
    catalog. Read fresh on every call so a catalog edit (``reload_presets``)
    applies without a restart."""
    return _default_entry("expression").get("prompt", "")


def get_pose_prompt(pose_key: str) -> str:
    """Pose prompt for an exact catalog key. Unknown/empty key → the default
    pose prompt (admin override or the catalog's ``_default`` entry)."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    prompt = (entry or {}).get("prompt", "")
    return prompt or default_pose_prompt()


def get_expression_prompt(expression_key: str) -> str:
    """Expression prompt for an exact catalog key. Unknown/empty key → the
    prompt of the catalog's ``_default`` entry."""
    entry = get_catalog("expression").get((expression_key or "").strip().lower())
    prompt = (entry or {}).get("prompt", "")
    return prompt or default_expression_prompt()


# ---------------------------------------------------------------------------
# Key-derived facts
# ---------------------------------------------------------------------------


def resolve_pose_animation(pose_key: str) -> str:
    """Animation kind for a pose catalog key ("" = unknown → the 3D client
    keeps guessing from the activity text). The kind vocabulary is open and
    comes from the clips that actually exist, never from a list in code."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    return (entry or {}).get("animation", "")


def is_partner_activity(pose_key: str) -> bool:
    """True if the pose is tagged ``"solo": false`` — an interaction between
    two people (kissing, embracing).

    The image pipeline injects exactly ONE character, so the model duplicates
    the subject to satisfy the "two people" implication of the pose prompt
    ("the character hugs themselves"). Tagged keys are skipped at the
    variant-generation trigger; the avatar keeps its last good frame.
    """
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    if not entry:
        return False
    return not entry.get("solo", True)


# ---------------------------------------------------------------------------
# Free text → expression key
# ---------------------------------------------------------------------------

# A mood is free text everywhere (``current_feeling``) and is never stored as
# a key, so — unlike the pose — it has to be resolved on the READ path, which
# includes the /play poll (peek_cached_expression on every request). Without
# this memo an unknown mood would cost one embedding call plus one candidate
# upsert per poll. Cleared by reload_presets(); a full memo is dropped whole
# (moods are few, the cap only guards against a pathological producer).
_EXPRESSION_KEY_MEMO: Dict[str, str] = {}
_MEMO_MAX_ENTRIES = 512


def resolve_expression_key(mood_free_text: str) -> str:
    """Map a free-text mood onto an expression catalog key.

    Always returns a key that exists (the catalog default for empty/unknown
    text); unabsorbed text is recorded as a candidate by the resolver.
    """
    text = (mood_free_text or "").strip().lower()
    cached = _EXPRESSION_KEY_MEMO.get(text)
    if cached is not None:
        return cached
    key, _how = resolve_to_catalog(text, "expression")
    if len(_EXPRESSION_KEY_MEMO) >= _MEMO_MAX_ENTRIES:
        _EXPRESSION_KEY_MEMO.clear()
    _EXPRESSION_KEY_MEMO[text] = key
    return key


def reload_presets() -> None:
    """Re-read the catalogs after an edit in the Poses admin tab — no restart
    needed."""
    reload_catalogs()
    _EXPRESSION_KEY_MEMO.clear()
    logger.info("Catalogs reloaded: %d poses, %d expressions",
                len(get_catalog("pose")), len(get_catalog("expression")))


def available_animation_kinds() -> list[str]:
    """The animation kinds that actually exist right now — derived from the
    shared clips (``app.core.animation_clips``), never a list in the code."""
    try:
        from app.core.animation_clips import clip_kinds
        return clip_kinds()
    except Exception as e:
        logger.debug("animation kinds not determinable: %s", e)
        return []
