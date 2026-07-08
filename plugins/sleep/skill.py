"""Sleep package — Sleep / WakeUp verbs.

One class, two verbs (``asleep=True`` → Sleep, ``asleep=False`` → WakeUp):
sets the ``is_sleeping`` state flag and moves the character off-map while
asleep, back to the pre-sleep location on wake.

The ``is_sleeping`` vocabulary and the off-map transition live in the core
(``app.models.character``) — auto-sleep in the agent loop and the B1 wake
rule write the same flag; this package is just one of several triggers.
Compliance reads the flag via ``get_state_flags()``.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class SleepWakeSkill(PluginSkill):
    """Sets is_sleeping (+ off-map). One implementation, two verbs:
    Sleep (asleep=True) / WakeUp (asleep=False) — the LLM sees both tools."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, asleep: bool):
        super().__init__(config, ctx)
        self._asleep = asleep
        self.SKILL_ID = "sleep" if asleep else "wakeup"
        # name/description/action_hint come from templates/llm/skills/<id>.md
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        char = (data.get("agent_name") or "").strip()
        if not char:
            return "Error: character_name missing."
        try:
            from app.models.character import (
                set_is_sleeping, enter_offmap_sleep, wake_from_offmap)
            set_is_sleeping(char, self._asleep)
            try:
                if self._asleep:
                    enter_offmap_sleep(char)
                else:
                    wake_from_offmap(char)
            except Exception as e:
                self.ctx.logger.debug("offmap toggle (asleep=%s) failed: %s",
                                      self._asleep, e)
            return (f"{char} is now asleep." if self._asleep
                    else f"{char} is awake again.")
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"
