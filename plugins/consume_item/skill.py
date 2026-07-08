"""Consume-item package — a character consumes one item from its own inventory.

Uses the existing ``inventory.consume_item`` pipeline:
  - removes 1 unit from the inventory
  - applies ``effects`` (stat changes, mood_influence)
  - sets ``apply_condition`` if defined (with ``condition_duration_hours``)

Usage: an avatar or NPC hands the character an item (gift); the recipient's
tool LLM decides in chat whether to drink/eat/apply it and calls this skill
with ``item_id`` or ``name``.

Input (JSON or plaintext):
    {"item_id": "item_xxxxxxx"}
    {"name": "Moon potion"}
    "Moon potion"
"""
import json
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class ConsumeItemSkill(PluginSkill):
    """Character consumes one item from its own inventory."""

    SKILL_ID = "consume_item"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/consume_item.md
        self._defaults = {"enabled": False}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is not available."
        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            self.ctx.logger.error("ConsumeItem error: %s", e)
            return f"Error while consuming: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        data = self._parse_base_input(raw_input)
        input_text = (data.get("input", raw_input) or "").strip()
        character_name = (data.get("agent_name") or "").strip()
        if not character_name:
            return "Error: character name missing."
        if not input_text:
            return "Error: item name or id missing."

        # JSON or plaintext
        token = ""
        if input_text.startswith("{"):
            try:
                parsed = json.loads(input_text)
                if isinstance(parsed, dict):
                    token = (parsed.get("item_id")
                             or parsed.get("name")
                             or parsed.get("item")
                             or "").strip()
            except Exception:
                pass
        if not token:
            token = input_text

        # Resolve token to an item id (id, name, item_<name>)
        from app.models.inventory import resolve_item_id, get_item, has_item, consume_item
        item_id = resolve_item_id(token)
        if not item_id:
            return f"Item '{token}' not found in the library."

        item = get_item(item_id) or {}
        item_name = item.get("name") or item_id

        # Must be in the character's own inventory
        if not has_item(character_name, item_id):
            return f"'{item_name}' is not in your inventory."

        # Consume
        result = consume_item(character_name, item_id)
        if not result.get("success"):
            return f"Could not consume '{item_name}'."

        # Confirmation with effect summary
        msg = f"'{item_name}' consumed."
        changes = result.get("changes") or {}
        if isinstance(changes, dict) and changes:
            chunks = []
            for stat, info in changes.items():
                if isinstance(info, dict):
                    delta = info.get("new", 0) - info.get("old", 0)
                    if delta:
                        sign = "+" if delta > 0 else ""
                        chunks.append(f"{stat} {sign}{delta}")
            if chunks:
                msg += " Effect: " + ", ".join(chunks) + "."
        cond = result.get("condition_applied")
        if cond:
            msg += f" Condition active: {cond}."
        return msg
