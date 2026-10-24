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
from typing import List

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

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


def decision_state_lines(character_name: str, tool_names) -> List[str]:
    """State lines for the TOOL DECISION prompt — set AND unset flags.

    ``situation_lines`` speaks to the character and only names set flags.
    The tool LLM that turns the character's prose into calls saw neither
    (0 of 3005 logged decisions, 2026-10-24), so it could not tell whether a
    state is running: it ended states that were never started (and an end
    verb may carry side effects of its own) and started them where the prose
    did not call for it. Here every flag whose clearing verb is among the
    offered tools gets one line either way. A flag whose verb is not on offer
    stays out — the decision prompt names no tool the character lacks.
    """
    specs = [s for s in _specs() if s.cleared_by]
    offered = set(tool_names or ())
    if not specs or not character_name or not offered:
        return []
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return []
    lines: List[str] = []
    for spec in specs:
        clear_tool = _clear_tool_name(spec)
        if clear_tool not in offered:
            continue
        if bool(profile.get(spec.flag)):
            cue = ""
            if spec.prompt_when_set:
                try:
                    cue = spec.prompt_when_set.format(
                        name=character_name, clear_tool=clear_tool)
                except (KeyError, IndexError):
                    cue = spec.prompt_when_set
                cue = f' (the character\'s own cue: "{cue}")'
            lines.append(
                f"- {clear_tool}: the state it ends IS active for "
                f"{character_name} right now{cue}. Call {clear_tool} only when "
                f"the text shows that state ending. The tool that starts this "
                f"state would change nothing — it is already running.")
        else:
            lines.append(
                f"- {clear_tool}: the state it ends is NOT active for "
                f"{character_name} — there is nothing to end, never call "
                f"{clear_tool} this turn.")
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
            # Lifecycle cleanup must always run, even when the character is
            # blocked or exhausted. Deliberately bypass gates and skill costs.
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
    now = game_time()  # flag durations are in-world -> game clock
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
                        # ``state_flag_since`` holds canonical GAME-time stamps.
                        set_at = GameTime.parse(ts)
                    except (ValueError, TypeError):
                        set_at = None
                if set_at is None:
                    stamp_state_flag_since(name, spec.flag)
                    continue
                ttl = _ttl_minutes(spec)
                if now - set_at >= GameDuration.of(minutes=ttl):
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
