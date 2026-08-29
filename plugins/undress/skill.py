"""Undress package — Undress / GetDressed verbs, ONE class, two directions.

For characters whose template has NO outfit system (``outfit_system_enabled:
false``, e.g. npc-temporary): their clothing is one free text
(``outfit_description``) plus one binary state (``outfit_worn``), and this
package is the only way the character itself can flip that state. Wardrobe
characters are untouched — they change clothes with ChangeOutfit, which works
on equipped pieces this template does not have.

The whole condition lives in ``visible_for`` (the hook the skill manager asks
generically, ``app/skills/skill_manager.py:169``), so the core never names
either verb (R1) and removing this folder removes the feature.

``visible_for`` is also how the character learns its own state: ``outfit_worn``
is ``in_prompt: false``, so nothing tells it whether it is dressed — but only
ONE of the two verbs is ever offered, and which one it is says everything.

The reading of ``outfit_worn`` is imported, never rebuilt: the field arrives
both as a bool and as the UI select's string "true"/"false", and
``outfit_renderer.is_outfit_worn`` is the single interpretation that the
renderer itself uses.

See development_instructions/plan-temp-npc-undress.md.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class UndressSkill(PluginSkill):
    """One class, two opposite verbs: Undress (dressed=False) / GetDressed."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, dressed: bool):
        super().__init__(config, ctx)
        self._dressed = dressed
        self.SKILL_ID = "get_dressed" if dressed else "undress"
        # name/description come from templates/llm/skills/<skill_id>.md
        self._defaults = {"enabled": True}

    def visible_for(self, character_name: str) -> bool:
        """Offer this verb only where it means something.

        Three ways it stays hidden:
          1. the character HAS a wardrobe — it dresses with ChangeOutfit, and
             its free text is not its dressed state;
          2. no ``outfit_description`` — there is nothing to take off, and
             flipping the state would change no prompt;
          3. the state is already reached — Undress goes as soon as the
             character is undressed, and GetDressed takes its place.

        Fails CLOSED: without a readable profile the verb is not offered.
        """
        if not character_name:
            return False
        try:
            from app.core.outfit_renderer import is_outfit_worn
            from app.models.character import get_character_profile
            from app.models.character_template import is_feature_enabled

            if is_feature_enabled(character_name, "outfit_system_enabled"):
                return False
            profile = get_character_profile(character_name) or {}
            if not str(profile.get("outfit_description") or "").strip():
                return False
            return is_outfit_worn(profile) != self._dressed
        except Exception as e:
            self.ctx.logger.debug("visible_for(%s) failed: %s", character_name, e)
            return False

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        char = (data.get("agent_name") or "").strip()
        if not char:
            return "Error: character_name missing."
        try:
            from app.models.character import (get_character_profile,
                                              save_character_profile)
            profile = get_character_profile(char)
            if not profile:
                return f"Error: no profile for {char}."
            described = str(profile.get("outfit_description") or "").strip()
            if not described:
                return f"{char} has no described clothing to change."
            # A real bool — the same shape npc_ops/npc_pool write. The UI
            # select stores strings; both are read by is_outfit_worn.
            profile["outfit_worn"] = self._dressed
            save_character_profile(char, profile)
            if self._dressed:
                return f"{char} puts the clothes back on: {described}."
            return f"{char} takes off the clothes and is undressed now."
        except Exception as e:
            self.ctx.logger.exception("%s failed for %s: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"
