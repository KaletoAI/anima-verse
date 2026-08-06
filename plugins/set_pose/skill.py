"""SetActivity package — sets the character's current free-text pose/activity.

Hands the text to the canonical setter ``set_pose_intent``, which maps it onto
a pose catalog key + sanitized flavor (and the matched image variant). The tool
name is SetActivity (template frontmatter); the skill_id stays ``set_pose``.
SINGLETON is declared in plugin.yaml — on multiple calls within one stream only
the last one sticks.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class SetPoseSkill(PluginSkill):
    """Sets the pose from free text (no state flag, pose pipeline only)."""

    SKILL_ID = "set_pose"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/set_pose.md
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        character_name = (data.get("agent_name") or "").strip()
        if not character_name:
            return "Error: character_name missing."
        try:
            pose = (data.get("pose") or data.get("input") or "").strip()
            if not pose:
                return "Error: no pose given."
            from app.models.character import (get_character_pose_key,
                                              set_pose_intent)
            # Catalog key + flavor + image variant, all in the setter
            set_pose_intent(character_name, pose)
            return f"{character_name}: {get_character_pose_key(character_name) or pose}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, character_name, e)
            return f"Error in {self.name}: {e}"
