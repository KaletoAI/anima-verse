"""Load installed skills and expose each character's active tools."""
import os
from typing import List, Dict, Any

from app.core.log import get_logger
from .base import ToolSpec

logger = get_logger("skill_mgr")
from .describe_room_skill import DescribeRoomSkill
from .outfit_change_skill import OutfitChangeSkill
from .outfit_creation_skill import OutfitCreationSkill
from .video_generation_skill import VideoGenerationSkill


class SkillManager:
    """Expose installed skills with runtime character configuration."""

    # Remaining built-ins; packages load through the manifest loader.
    SKILL_REGISTRY = {
        'describe_room': DescribeRoomSkill,
        'outfit_change': OutfitChangeSkill,
        'outfit_creation': OutfitCreationSkill,
        'videogen': VideoGenerationSkill,
    }

    def __init__(self):
        self.skills = []
        self.tools = []

    def _load_skill(self, skill_id: str, skill_class) -> bool:
        """Load a remaining built-in; return whether it was enabled."""
        # ALWAYS_LOAD controls loading, not per-character activation.
        if not getattr(skill_class, 'ALWAYS_LOAD', False):
            env_prefix = f"SKILL_{skill_id.upper()}_"
            enabled_key = f"{env_prefix}ENABLED"
            if os.getenv(enabled_key, 'false').lower() != 'true':
                return False

        try:
            skill = skill_class({'enabled': True})
            if skill.enabled:
                self.skills.append(skill)
                self.tools.append(skill.as_tool())
                logger.info(f"Skill geladen: {skill.name}")
                return True
            else:
                logger.info(f"Skill deaktiviert: {skill.name}")
        except Exception as e:
            logger.error(f"Fehler beim Laden von Skill '{skill_id}': {e}")

        return False

    def _load_plugins(self) -> int:
        """Load installed packages from the plugin registry."""
        from app.plugins.loader import load_all_plugins
        loaded = 0
        for skill_id, skill in load_all_plugins().items():
            if skill.enabled:
                self.skills.append(skill)
                self.tools.append(skill.as_tool())
                logger.info("Plugin geladen: %s (skill_id=%s)", skill.name, skill_id)
                loaded += 1
        return loaded

    def load_skills(self) -> None:
        """Load enabled remaining built-ins and installed packages."""
        # 1. Built-in Skills
        for skill_id, skill_class in self.SKILL_REGISTRY.items():
            self._load_skill(skill_id, skill_class)
        # Installed packages.
        self._load_plugins()

    def reload_skills(self) -> Dict[str, Any]:
        # Config may have changed — rebuild the image service backend pool
        # on next access (core engine, lives outside the skill registry).
        try:
            from app.imagegen.service import reset_image_service
            reset_image_service()
        except Exception:
            pass
        """Reload skills without restarting the server."""
        logger.info("=" * 80)
        logger.info("SKILLS NEU LADEN")
        logger.info("=" * 80)

        old_count = len(self.skills)
        self.skills = []
        self.tools = []

        loaded_count = 0
        errors = []

        for skill_id, skill_class in self.SKILL_REGISTRY.items():
            try:
                if self._load_skill(skill_id, skill_class):
                    loaded_count += 1
            except Exception as e:
                error_msg = f"Fehler beim Laden von {skill_id}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)

        # Installed packages.
        try:
            loaded_count += self._load_plugins()
        except Exception as e:
            error_msg = f"Fehler beim Laden der Plugins: {e}"
            errors.append(error_msg)
            logger.error(error_msg)

        logger.info("=" * 80)
        logger.info(f"Skills neu geladen: {old_count} -> {loaded_count}")
        logger.info("=" * 80)

        return {
            "status": "success",
            "old_count": old_count,
            "new_count": loaded_count,
            "skills": [skill.name for skill in self.skills],
            "errors": errors
        }

    def _get_agent_skills(self, character_name: str,
                          check_limits: bool = True) -> List:
        """Filter visible skills by character overrides and package defaults.

        Proactive calls also apply runtime limits; chat calls skip those limits.
        """
        if not character_name:
            return self.skills

        from app.models.character import get_character_skill_config

        result = []
        for skill in self.skills:
            if not skill.SKILL_ID:
                result.append(skill)
                continue
            _sid = skill.SKILL_ID
            # Per-character visibility hook (wave 4): skills hide themselves
            # based on world state (party role etc.) — replaces the former
            # hardcoded skill-id whitelist here (R1).
            try:
                if not skill.visible_for(character_name):
                    continue
            except Exception as _ve:
                logger.debug("visible_for failed for %s: %s", _sid, _ve)
            agent_config = get_character_skill_config(character_name, _sid)
            if agent_config and "enabled" in agent_config:
                if not bool(agent_config["enabled"]):
                    continue
            else:
                default_enabled = getattr(skill, "default_enabled_for", None)
                if not (default_enabled(character_name) if default_enabled
                        else not getattr(skill, "ALWAYS_LOAD", False)):
                    continue

            # Runtime limits apply only to proactive calls, not user chat.
            if check_limits and hasattr(skill, 'is_limit_reached') and skill.is_limit_reached(character_name):
                logger.info("Skill '%s' fuer %s ausgeblendet: Limit erreicht", skill.name, character_name)
                continue

            result.append(skill)
        return result

    def get_agent_tools(self, character_name: str,
                        check_limits: bool = True) -> List[ToolSpec]:
        """Return the character's currently active tool specifications."""
        agent_skills = self._get_agent_skills(character_name, check_limits=check_limits)
        return [s.as_tool(character_name=character_name) for s in agent_skills]

    def get_skill(self, skill_id: str):
        """Find a loaded skill by its stable id."""
        for skill in self.skills:
            if getattr(skill, 'SKILL_ID', '') == skill_id:
                return skill
        return None

    def get_skill_by_name(self, name: str):
        """Find a loaded skill by its case-insensitive tool name."""
        name_lower = name.lower()
        for skill in self.skills:
            if getattr(skill, 'name', '').lower() == name_lower:
                return skill
        return None

    def progress_type_for_tool(self, tool_name: str) -> str:
        """Generic progress type ('image', 'search', …) declared by the
        skill behind a tool name (PROGRESS_TYPE) — replaces the former
        hardcoded TOOL_NAME_MAP (wave 4). Empty string = not trackable."""
        for skill in self.skills:
            if getattr(skill, "name", "") == tool_name:
                return getattr(skill, "PROGRESS_TYPE", "") or ""
        return ""

    def tool_names_with_flag(self, flag: str) -> frozenset:
        """Tool names of loaded skills with a truthy metadata flag (F7) —
        e.g. SINGLETON, SUPPRESS_IN_PERSON, CASCADE_BRAKE, SEARCH_INTENT.
        The generic replacement for hardcoded tool-name lists in the core."""
        return frozenset(s.name for s in self.skills if getattr(s, flag, False))

    def get_action_hint(self, tool_name: str) -> str:
        """Declared action hint of a tool (skill meta frontmatter `action_hint:`)."""
        skill = self.get_skill_by_name(tool_name)
        return getattr(skill, "action_hint", "") if skill else ""

    def get_agent_usage_instructions(self, character_name: str,
                                     format_name: str = "",
                                     check_limits: bool = True,
                                     exclude: frozenset = frozenset()) -> str:
        """Usage instructions for the skills active for this character.

        ``exclude``: tool names whose usage lines stay out — a verb the
        caller does not offer this turn (in-person movement) must not come
        back through its usage example either.
        """
        agent_skills = self._get_agent_skills(character_name, check_limits=check_limits)
        if not agent_skills:
            return ""
        return "\n".join(skill.get_usage_instructions(format_name, character_name=character_name)
                         for skill in agent_skills
                         if getattr(skill, "name", "") not in exclude)
