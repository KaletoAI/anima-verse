"""Decency-exempt package — AllowExposed / RequireDecency verbs.

Sets/clears the ``decency_exempt`` state flag — decency override to
nude_ok regardless of presence/strangers. The skill counterpart to
is_intimate, but as a DELIBERATE persistent state (e.g. exhibitionism,
nudist spots) — therefore no TTL and no location reset; only the prompt
line (declared in plugin.yaml) reminds the character that the override
is active. The flag is also settable via the manual UI toggle and force
rules (core flag vocabulary).
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class DecencyExemptSkill(PluginSkill):
    """One class, two verbs: AllowExposed (active=True) / RequireDecency."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, active: bool):
        super().__init__(config, ctx)
        self._active = active
        self.SKILL_ID = "allow_exposed" if active else "require_decency"
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        char = (data.get("agent_name") or "").strip()
        if not char:
            return "Error: character_name missing."
        try:
            from app.models.character import set_decency_exempt
            set_decency_exempt(char, self._active)
            # Compliance reacts immediately (nude_ok -> no forced dressing / back).
            try:
                from app.core.outfit_compliance import apply_outfit_compliance
                apply_outfit_compliance(char)
            except Exception as e:
                self.ctx.logger.debug(
                    "compliance after decency-exempt toggle (active=%s): %s",
                    self._active, e)
            if self._active:
                return f"{char} may stay exposed (decency lifted)."
            return f"{char} follows the dress code again."
        except Exception as e:
            self.ctx.logger.exception("%s failed for %s: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"
