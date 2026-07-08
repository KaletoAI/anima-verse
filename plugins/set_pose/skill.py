"""SetActivity package — sets the character's current free-text pose/activity.

Writes ``pose_intent`` (+ the matched image variant id) to the profile via
the core pose engine. The tool name is SetActivity (template frontmatter);
the skill_id stays ``set_pose``. SINGLETON is declared in plugin.yaml — on
multiple calls within one stream only the last one sticks.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class SetPoseSkill(PluginSkill):
    """Sets pose_intent from free text (no state flag, pose pipeline only)."""

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
            from app.models.character import get_character_profile, save_character_profile
            from app.core.pose_engine import resolve_pose_variant
            # Resolve variant (normalize + match), store pose_intent + id
            variant = resolve_pose_variant(character_name, pose)
            prof = get_character_profile(character_name) or {}
            prof["pose_intent"] = pose
            if variant:
                prof["pose_variant_id"] = variant["id"]
            save_character_profile(character_name, prof)
            canonical = (variant or {}).get("canonical_pose") or pose
            return f"{character_name}: {canonical}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, character_name, e)
            return f"Error in {self.name}: {e}"
