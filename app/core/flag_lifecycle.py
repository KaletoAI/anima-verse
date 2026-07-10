"""Flag-lifecycle executor — runs package-declared state-flag lifecycles.

Skill packages declare their flags in plugin.yaml (``state_flags``): which
verb clears them, how they appear in the character's situation context,
and when they decay (TTL and/or location change). This module executes
those declarations generically — it knows NO flag name (rules R1/R4,
development_instructions/plan-skill-plugin-architecture.md):

- ``situation_lines()``     — prompt lines for set flags (thought context)
- ``decay_tick()``          — TTL decay, runs in the world-admin tick
- ``on_location_change()``  — location-reset flags, called centrally from
                              save_character_current_location

Auto-clear invokes the declaring package's clear VERB (``cleared_by``) via
the skill manager, so decay runs exactly the same side effects as an LLM
tool call (compliance re-evaluation, partner handling, stat hooks). If the
verb is unavailable the flag is hard-cleared as a fallback.
"""
import json
from datetime import timedelta
from typing import List

from app.core.log import get_logger
from app.core.timeutils import parse_iso, game_now

logger = get_logger("flag_lifecycle")


def _specs():
    try:
        from app.plugins.registry import flag_specs
        return flag_specs()
    except Exception:
        return []


def _ttl_minutes(spec) -> int:
    """Manifest TTL, overridable at runtime via ``skills.<package>.ttl_minutes``
    (the package declares that field in its config_schema)."""
    try:
        from app.core import config
        val = config.get(f"skills.{spec.package_id}.ttl_minutes", None)
        if val not in (None, ""):
            return max(0, int(val))
    except Exception:
        pass
    return max(0, int(spec.ttl_minutes or 0))


def _clear_tool_name(spec) -> str:
    """Tool name of the clearing verb for prompt lines ({clear_tool})."""
    try:
        from app.core.dependencies import get_skill_manager
        skill = get_skill_manager().get_skill(spec.cleared_by)
        if skill:
            return skill.name
    except Exception:
        pass
    return spec.cleared_by


def situation_lines(character_name: str) -> List[str]:
    """Prompt lines for all set flags with a declared ``prompt_when_set``.

    Gives the LLM the cue to actually end its states (the historic
    stuck-flag problem: flags were set but never surfaced in the prompt).
    """
    specs = [s for s in _specs() if s.prompt_when_set]
    if not specs or not character_name:
        return []
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return []
    lines: List[str] = []
    for spec in specs:
        if not bool(profile.get(spec.flag)):
            continue
        try:
            lines.append(spec.prompt_when_set.format(
                name=character_name, clear_tool=_clear_tool_name(spec)))
        except (KeyError, IndexError):
            lines.append(spec.prompt_when_set)
    return lines


def _clear_via_verb(spec, character_name: str, reason: str) -> None:
    """End a flag by invoking the declaring package's clear verb — same
    code path and side effects as an LLM tool call."""
    try:
        from app.core.dependencies import get_skill_manager
        skill = get_skill_manager().get_skill(spec.cleared_by)
    except Exception:
        skill = None
    if skill is not None:
        try:
            skill.execute(json.dumps({"agent_name": character_name}))
            logger.info("flag %s auto-cleared for %s via %s (%s)",
                        spec.flag, character_name, skill.name, reason)
            return
        except Exception as e:
            logger.warning("flag %s: clear verb '%s' failed for %s: %s",
                           spec.flag, spec.cleared_by, character_name, e)
    # Fallback: hard clear so the flag cannot stick forever.
    try:
        from app.models.character import set_state_flag
        set_state_flag(character_name, spec.flag, False)
        logger.info("flag %s hard-cleared for %s (%s)",
                    spec.flag, character_name, reason)
    except Exception as e:
        logger.warning("flag %s: hard clear failed for %s: %s",
                       spec.flag, character_name, e)


def decay_tick() -> None:
    """TTL decay for all declared flags (world-admin tick).

    A set flag WITHOUT a timestamp gets a baseline stamp instead of an
    immediate clear — covers flags set before the executor existed and
    manual data edits; the TTL then counts from now.
    """
    specs = [s for s in _specs() if _ttl_minutes(s) > 0]
    if not specs:
        return
    try:
        from app.models.character import (
            get_character_profile, list_available_characters,
            stamp_state_flag_since)
    except Exception:
        return
    now = game_now()  # flag durations are in-world -> game clock
    for name in list_available_characters():
        try:
            profile = get_character_profile(name) or {}
            since_map = profile.get("state_flag_since") or {}
            for spec in specs:
                if not bool(profile.get(spec.flag)):
                    continue
                ts = since_map.get(spec.flag)
                set_at = None
                if ts:
                    try:
                        set_at = parse_iso(ts)
                    except (ValueError, TypeError):
                        set_at = None
                if set_at is None:
                    stamp_state_flag_since(name, spec.flag)
                    continue
                ttl = _ttl_minutes(spec)
                if now - set_at >= timedelta(minutes=ttl):
                    _clear_via_verb(spec, name, f"ttl {ttl}min")
        except Exception as e:
            logger.debug("decay tick failed for %s: %s", name, e)


def on_location_change(character_name: str) -> None:
    """End flags declared with ``reset_on_location_change`` — called
    centrally from save_character_current_location on a real move."""
    specs = [s for s in _specs() if s.reset_on_location_change]
    if not specs or not character_name:
        return
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return
    for spec in specs:
        if bool(profile.get(spec.flag)):
            _clear_via_verb(spec, character_name, "location change")
