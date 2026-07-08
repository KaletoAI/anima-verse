"""Wet state package — EnterWater / DryOff verbs.

Sets/clears the ``is_wet`` state flag (swim exemption in outfit
compliance). Prompt visibility and TTL decay are declared in plugin.yaml
and executed by the core flag-lifecycle executor — auto-dry invokes the
DryOff verb, i.e. exactly this code path.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class WetSkill(PluginSkill):
    """One class, two verbs: EnterWater (wet=True) / DryOff (wet=False)."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, wet: bool):
        super().__init__(config, ctx)
        self._wet = wet
        self.SKILL_ID = "enter_water" if wet else "dry_off"
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        char = (data.get("agent_name") or "").strip()
        if not char:
            return "Error: character_name missing."
        try:
            from app.models.character import set_is_wet
            set_is_wet(char, self._wet)
            # Re-evaluate compliance so the swim exemption applies / falls.
            try:
                from app.core.outfit_compliance import apply_outfit_compliance
                apply_outfit_compliance(char)
            except Exception as e:
                self.ctx.logger.debug("compliance after wet toggle (wet=%s): %s",
                                      self._wet, e)
            return (f"{char} is in the water now." if self._wet
                    else f"{char} is dry again.")
        except Exception as e:
            self.ctx.logger.exception("%s failed for %s: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"
