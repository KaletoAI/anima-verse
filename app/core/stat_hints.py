"""Resolve template threshold hints against effective character stats."""
from typing import Any, Dict, Iterable, List

from app.core.log import get_logger

logger = get_logger("stat_hints")


def _iter_template_fields(template: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for section in template.get("sections", []) or []:
        for field in section.get("fields", []) or []:
            yield field


def active_band(rule: dict, value: int) -> dict | None:
    """Select the smallest matching maximum, else the largest minimum."""
    thresholds = rule.get("thresholds") or []
    maxima = [band for band in thresholds if "max" in band and value <= band["max"]]
    if maxima:
        return min(maxima, key=lambda band: band["max"])
    minima = [band for band in thresholds if "min" in band and value >= band["min"]]
    return max(minima, key=lambda band: band["min"]) if minima else None


def stat_bands(name: str, *, profile: dict | None = None) -> list[dict]:
    """Describe active bands for declared, present stats using resolved rules."""
    from app.models.character import get_character_profile
    from app.models.character_template import get_template
    from app.core.stat_boosts import effective_stats
    from app.core.stat_rules import rules_for_character

    if profile is None:
        profile = get_character_profile(name) or {}
    template = get_template(profile.get("template") or "") or {}
    rules = rules_for_character(name, profile=profile)
    values = effective_stats(profile)
    result = []
    for field in _iter_template_fields(template):
        key = field.get("key")
        if field.get("store") != "status_effects" or key not in values:
            continue
        value = values[key]["value"]
        band = active_band(rules.get(key, {}), value)
        if band is not None:
            result.append({"key": key, "name": field.get("label") or key,
                           "value": value, "label": band.get("label") or "",
                           "text": band.get("text") or "", "need": band.get("need")})
    return result


def get_stat_hints(character_name: str) -> List[str]:
    """Return active band labels (or their text) for event character hints."""
    return [band["label"] or band["text"] for band in stat_bands(character_name)
            if band["label"] or band["text"]]


def template_stat_keys(template: Dict[str, Any]) -> set:
    """Set of stat keys (store=status_effects) declared by ONE template —
    the authoritative list of stats a character of that template may have."""
    keys = set()
    for field in _iter_template_fields(template or {}):
        if field.get("store") == "status_effects" and field.get("key"):
            keys.add(field["key"])
    return keys


def get_all_stat_keys() -> List[str]:
    """Return stat field keys across all world character templates."""
    keys: List[str] = []
    seen = set()
    try:
        from app.models.character_template import list_templates, get_template
        for entry in list_templates() or []:
            tmpl = get_template(entry.get("name", "")) or {}
            for field in _iter_template_fields(tmpl):
                if field.get("store") != "status_effects":
                    continue
                k = field.get("key")
                if k and k not in seen:
                    seen.add(k)
                    keys.append(k)
    except Exception as e:
        logger.debug("get_all_stat_keys failed: %s", e)
    return keys


def format_character_with_hints(character_name: str) -> str:
    """Format the character name with matching hints, if any."""
    hints = get_stat_hints(character_name)
    return f"{character_name} ({', '.join(hints)})" if hints else character_name
