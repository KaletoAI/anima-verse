"""Executable semantic action skill; actor is bound by the skill manager."""
import json
from app.plugins.base import PluginSkill
from app.skills.base import ToolSpec
from app.core.prop_actions import execute


class PropActionSkill(PluginSkill):
    SKILL_ID = "prop_action"
    PLAYER_ACTION = "prop_action"

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}

    def execute(self, raw_input):
        if not self.enabled:
            return json.dumps({"status": "refused", "reason": "skill_disabled", "execution_id": ""})
        data = self._parse_base_input(raw_input)
        actor = data.pop("agent_name", "")
        for key in ("input", "user_id", "rp_context", "user_input", "initiator", "skip_daily_limit"):
            data.pop(key, None)
        return json.dumps(execute(actor, data), ensure_ascii=False)

    def as_tool(self, character_name=""):
        if not character_name:
            return super().as_tool()
        def bound(raw):
            data = self._parse_base_input(raw)
            data["agent_name"] = character_name
            return self.execute(json.dumps(data))
        return ToolSpec(name=self.name, description=self.description, func=bound)
