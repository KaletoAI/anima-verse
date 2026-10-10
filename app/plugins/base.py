"""PluginSkill extends BaseSkill with a public package service context."""
from typing import Any, Dict

from app.skills.base import BaseSkill
from app.plugins.context import PluginContext


class PluginSkill(BaseSkill):
    """Package skill configured by its manifest and character overrides.

    Packages use PluginContext services or the documented public core API.
    """

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config)
        self.ctx = ctx

    def default_enabled_for(self, character_name: str) -> bool:
        """Activation without a character override; explicit settings take precedence."""
        return not self.ALWAYS_LOAD
