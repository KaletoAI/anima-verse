"""Animation sets — which figure's clips a character uses.

A clip lives at ``[<set>/]<kind>.fbx``: the KIND comes from what the character
is doing (the pose preset's ``animation``), the SET from WHO it is. Setting a
character's set once to ``female`` gives it female/walk, female/sit,
female/sleep … automatically — no per-character clip assignment anywhere.

The three BASE sets are always offered because they follow from data the
characters already carry: gender (female/male) and the template's ``humanoid``
feature (animal). Any further set is simply a new subdirectory in
shared/models/clips — discovered, never hardcoded.

A character with no explicit set is NOT setless: its set is DERIVED, so the
figures animate correctly out of the box. An empty derivation (e.g. a
non-binary humanoid) falls back to the plain ``<kind>.fbx`` clips.
"""
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

# Sets that follow from existing character data — always selectable, even
# before a single matching clip exists.
BASE_SETS = ("female", "male", "animal")


def discovered_sets() -> List[str]:
    """Sets that actually have clips in shared/models/clips."""
    try:
        from app.core.animation_clips import clip_sets
        return clip_sets()
    except Exception as e:
        logger.debug("Animations-Sets nicht ermittelbar: %s", e)
        return []


def available_sets() -> List[str]:
    """The base sets plus every set found in the clips."""
    return sorted(set(BASE_SETS) | set(discovered_sets()))


def _profile(character_name: str,
             profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The given profile, or a fresh load. Callers iterating many characters
    (the worldmap builds this per character per request) load once and pass
    it through instead of paying several DB/file reads per character."""
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def derive_set(character_name: str,
               profile: Optional[Dict[str, Any]] = None) -> str:
    """The set that follows from the character itself: animals -> "animal",
    humanoids -> their gender when it is one we have clips for. "" when nothing
    fits (the plain clips apply)."""
    try:
        from app.core.model_refs import is_humanoid
        if not is_humanoid(character_name):
            return "animal"
        gender = str(_profile(character_name, profile).get(
            "gender") or "").strip().lower()
        return gender if gender in ("female", "male") else ""
    except Exception:
        return ""


def explicit_set(character_name: str,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """The set explicitly assigned to the character ("" = none)."""
    try:
        return str(_profile(character_name, profile).get(
            "animation_set") or "").strip().lower()
    except Exception:
        return ""


def resolve_sets(character_name: str,
                 profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """The character's set chain, most specific first.

    An explicit set need NOT be complete: a character on ``lady`` that has no
    ``lady/sit`` clip should sit like the figure it derives from (``female``),
    not like the neutral default. So the chain is

        explicit set  ->  derived set (animal / female / male)

    and only when neither has a clip of the wanted kind does the plain
    ``<kind>.fbx`` apply. Duplicates are collapsed (an explicit set equal to
    the derived one yields a single entry).
    """
    if profile is None:
        profile = _profile(character_name, None)
    chain: List[str] = []
    for s in (explicit_set(character_name, profile),
              derive_set(character_name, profile)):
        if s and s not in chain:
            chain.append(s)
    return chain


def resolve_set(character_name: str,
                profile: Optional[Dict[str, Any]] = None) -> str:
    """The character's primary set (first of the chain) — "" if it has none."""
    chain = resolve_sets(character_name, profile)
    return chain[0] if chain else ""
