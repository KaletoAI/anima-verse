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

    def default_enabled_for(self, character_name):
        # ALWAYS_LOAD controls installation, not existing-character activation.
        # The manager still gives explicit character overrides precedence.
        return self.enabled and bool(self.ctx.get_config("skills.prop_action.enabled", True))

    def available_now(self, facts):
        from app.core.prop_actions import offers
        from app.core.prop_action_store import live_runs
        if any(run["actor"] == facts.character or (
                facts.character in run["members"] and run["status"] != "awaiting_consent")
                for run in live_runs()):
            return None
        for offer in offers(facts.character):
            if offer["required_partner"]:
                if any(target["enabled"] for target in offer["available_targets"]):
                    return None
            elif offer["enabled"]:
                return None
        return "no requestable furniture action or own running action"

    def decision_menu(self, character_name: str) -> list[str]:
        """Exact requestable names, plus the participant's own stop action."""
        from app.core.prop_actions import offers, piece_label
        from app.core.prop_action_engine import state_for

        lines = []
        state = state_for(character_name)
        for run in state["current"] + state["outgoing"]:
            piece = piece_label(run["target"]) or "Furniture"
            lines.append(f"running now: {piece} | {run['label']} - to get up or leave it, "
                         'the whole input is {"stop": true}')
        for row in offers(character_name):
            pair = row["required_partner"]
            usable = (any(target["enabled"] for target in row["available_targets"])
                      if pair else row["enabled"])
            if usable:
                line = f"{row['prop_label'] or 'Furniture'} | {row['label']}"
                if pair:
                    line += " | with partner"
                if line not in lines:
                    lines.append(line)
        return lines[:20]

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
