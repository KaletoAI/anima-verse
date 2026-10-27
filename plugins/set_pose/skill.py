"""SetActivity package — sets the character's current pose key + detail.

Takes a catalog pose key plus a short display detail and hands both to
``set_pose_key_detail``: a known key is written exactly with the detail as its
flavor, an unknown or empty one falls back to the resolver net. The tool name
is SetActivity (template frontmatter); the skill_id stays ``set_pose``.
SINGLETON is declared in plugin.yaml — on multiple calls within one stream only
the last one sticks.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolRefusal, ToolSpec


class SetPoseSkill(PluginSkill):
    """Sets the pose from key + detail (no state flag, pose pipeline only)."""

    SKILL_ID = "set_pose"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/set_pose.md
        self._defaults = {"enabled": True}

    def as_tool(self, character_name: str = "") -> ToolSpec:
        from app.core.hooks import get_provider
        provider = get_provider("pair_verb_name")
        pair_name = provider() if provider else ""
        return ToolSpec(name=self.name, description=self.description,
                        func=self.execute,
                        run_before=(pair_name,) if pair_name else ())

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        character_name = (data.get("agent_name") or "").strip()
        if not character_name:
            return "Error: character_name missing."
        try:
            key = str(data.get("pose") or "").strip()
            detail = str(data.get("detail") or "").strip()
            if not key and not detail:
                # Bare text ("standing: waiting" or simply "waiting"): the
                # split decides what is key and what is detail.
                from app.core.pose_catalog import split_key_detail
                key, detail = split_key_detail(str(data.get("input") or ""))
            if not key and not detail:
                return "Error: no pose given."
            from app.core.pose_catalog import PairPoseWithoutPartner
            from app.models.character import set_pose_key_detail
            # A known key is written exactly with the detail as display text;
            # an unknown one goes through the resolver net.
            try:
                written = set_pose_key_detail(character_name, key, detail,
                                              unknown="resolve")
            except PairPoseWithoutPartner as e:
                from app.core.hooks import get_provider
                _verb = get_provider("pair_verb_name")
                _name = _verb() if _verb else ""
                how = (f"Start it together with {_name}: "
                       f"{{\"partner\": \"<name>\", \"action\": \"{e}\"}}. "
                       if _name else "There is no way to start it here. ")
                return ToolRefusal(
                    f"'{e}' is a two-person action, not something "
                    f"{character_name} does alone. {how}For a solo pose, "
                    f"pass a pose key from the list plus a short detail.",
                    correction_tools=(_name,) if _name else ())
            return f"{character_name}: {written or key or detail}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, character_name, e)
            return f"Error in {self.name}: {e}"
