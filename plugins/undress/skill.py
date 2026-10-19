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

The package supplies volatile clothing context and an explicit solo action
to background NPC turns. Chat turns use the same context and ordinary tools.

The reading of ``outfit_worn`` is imported, never rebuilt: the field arrives
both as a bool and as the UI select's string "true"/"false", and
``outfit_renderer.is_outfit_worn`` is the single interpretation that the
renderer itself uses.

See development_instructions/done/plan-temp-npc-undress.md.
"""
from typing import Any, Dict
import json

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
        from app.core.hooks import register
        tag = f"undress:{self.SKILL_ID}"
        register("character.prompt_context", self._prompt_context, tag=tag)
        register("npc.action_execute", self._npc_action, tag=tag)

    def _is_current(self) -> bool:
        """A removed or replaced skill must not keep contributing callbacks."""
        from app.core.dependencies import get_skill_manager
        return get_skill_manager().get_skill(self.SKILL_ID) is self

    def _available(self, character_name: str) -> bool:
        from app.models.character import get_character_skill_config
        cfg = get_character_skill_config(character_name, self.SKILL_ID)
        return self.enabled and bool(cfg.get("enabled", False)) and self.visible_for(character_name)

    def _prompt_context(self, *, character_name: str, mode: str, blocks: list) -> None:
        if not self._is_current() or not self._available(character_name):
            return
        from app.core.outfit_renderer import undressed_line
        from app.core.prompt_templates import render
        from app.models.character import get_character_profile, get_state_flags
        profile = get_character_profile(character_name) or {}
        flags = get_state_flags(character_name)
        # Undressed, the prompt states what is there (the core's undressed
        # text plus exposed anatomy), never the clothes lying around.
        undressed = "" if not self._dressed else undressed_line(character_name, profile)
        blocks.append(render(
            "undress/context.md", mode=mode, dressed=not self._dressed,
            description=profile.get("outfit_description", ""),
            undressed=undressed,
            verb=self.name, target_dressed=self._dressed,
            suggest_dressing=self._dressed and not any(flags.get(k) for k in
                ("is_sleeping", "is_wet", "is_intimate", "decency_exempt")),
            flags=[k for k, value in flags.items() if value]))

    def _npc_action(self, *, character_name: str, action: dict, result: dict) -> None:
        if not self._is_current() or result.get("handled") or action.get("type") != "clothing":
            return
        direction = action.get("dressed")
        if type(direction) is bool and direction != self._dressed:
            return  # The counter-verb handles its own direction.
        result["handled"] = True
        if type(direction) is not bool or not self._available(character_name):
            result.update(success=False, text="Clothing action is not available.")
            return
        text = self.execute(json.dumps({"agent_name": character_name}))
        result.update(success=not text.startswith("Error"), text=text)

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
            from app.core.keyed_lock import keyed_lock
            from app.models.character import (get_character_profile,
                                              save_character_profile)
            with keyed_lock("character_profile", char):
                if not self._available(char):
                    return f"Error: {self.name} is not available for {char}."
                profile = get_character_profile(char)
                if not profile:
                    return f"Error: no profile for {char}."
                described = str(profile.get("outfit_description") or "").strip()
                profile["outfit_worn"] = self._dressed
                if not save_character_profile(char, profile):
                    return f"Error: clothing change for {char} was not stored."
            if self._dressed:
                return f"{char} puts the clothes back on: {described}."
            return f"{char} takes off the clothes and is undressed now."
        except Exception as e:
            self.ctx.logger.exception("%s failed for %s: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"
