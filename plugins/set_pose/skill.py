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
            from app.core.pose_catalog import PairPoseWithoutPartner
            from app.models.character import (get_character_pose_key,
                                              set_pose_intent)
            # Catalog key + flavor + image variant, all in the setter
            try:
                set_pose_intent(character_name, pose)
            except PairPoseWithoutPartner as e:
                # The text landed on a two-person pose. Say so instead of
                # writing half a pair. The turn is usually over by the time
                # this is read (the tool phase does not loop back for a
                # second choice), so this answer is for the LOG and for the
                # models that do get another pass — the prompt is what stops
                # the wrong choice being made in the first place.
                from app.core.hooks import get_provider
                _verb = get_provider("pair_verb_name")
                _name = _verb() if _verb else ""
                how = (f"Start it together with {_name}: "
                       f"{{\"partner\": \"<name>\", \"action\": \"{e}\"}}. "
                       if _name else "There is no way to start it here. ")
                return (f"'{e}' is a two-person action, not something "
                        f"{character_name} does alone. {how}For a solo pose, "
                        f"describe what {character_name} does on their own.")
            return f"{character_name}: {get_character_pose_key(character_name) or pose}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, character_name, e)
            return f"Error in {self.name}: {e}"
