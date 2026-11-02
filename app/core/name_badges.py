"""Small icons behind a character's name (plan-intim-privatsphaere.md, part E).

Clients show them after the name in the chat's address chips and in the name
tag over the 3D figure. The core names no badge: packages contribute through
the provider ``character.name_badges`` (``hooks.register_provider(...,
multiple=True)``), called as ``fn(name, profile)`` and answering a list of
``{"icon": str, "title": str}`` — ``title_<lang>`` variants are allowed and
resolved here with ``i18n.localized``. A contributor that raises, or answers
something else, is skipped; one broken package never empties another's badge.
"""
from typing import Any, Dict, Iterable, List, Optional

from app.core.log import get_logger

logger = get_logger("name_badges")

CAPABILITY = "character.name_badges"


def badges_for(name: str, *, profile: Optional[Dict[str, Any]] = None,
               lang: str = "en") -> List[Dict[str, str]]:
    """``[{icon, title}]`` for one character, in contributor order."""
    from app.core.hooks import get_providers
    from app.core.i18n import localized
    providers = get_providers(CAPABILITY)
    if not providers or not name:
        return []
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(name) or {}
    out: List[Dict[str, str]] = []
    for fn in providers:
        try:
            got = fn(name, profile) or []
        except Exception as e:
            logger.warning("name badge provider %s failed for %s: %s",
                           getattr(fn, "__qualname__", fn), name, e)
            continue
        if not isinstance(got, list):
            continue
        for b in got:
            if not isinstance(b, dict):
                continue
            icon = b.get("icon")
            if not isinstance(icon, str) or not icon.strip():
                continue
            title = localized(b, "title", lang)
            out.append({"icon": icon.strip(), "title": title if isinstance(title, str) else ""})
    return out


def badges_map(names: Iterable[str], *, lang: str = "en",
               profiles: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, str]]]:
    """``{name: badges}`` for the names that have any — an absent name has none."""
    from app.core.hooks import get_providers
    if not get_providers(CAPABILITY):
        return {}
    out: Dict[str, List[Dict[str, str]]] = {}
    for name in names:
        b = badges_for(name, profile=(profiles or {}).get(name), lang=lang)
        if b:
            out[name] = b
    return out
