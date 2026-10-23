"""Read a provider-backed room item privately during an autonomous thought."""
import json

from app.plugins.base import PluginSkill
from app.core.item_reading import has_pages, readable_here, npc_read, npc_read_today
from app.core.room_entry import characters_in_room
from app.models import character, inventory


class ReadItemSkill(PluginSkill):
    SKILL_ID = "read_item"
    ALWAYS_LOAD = True
    TURN_KINDS = ("thought",)
    CONTENT_TOOL = True

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}

    def default_enabled_for(self, character_name: str) -> bool:
        # A temporary NPC keeps no memories, so what it read would be lost.
        return (self.enabled and bool(self.ctx.get_config("skills.read_item.enabled", True))
                and not character.is_temporary_npc(character_name))

    def _candidates(self, name):
        """Cheap availability checks: never evaluate a page provider here."""
        if not name or not self.default_enabled_for(name):
            return []
        loc = character.get_character_current_location(name) or ""
        room = character.get_character_current_room(name) or ""
        if not loc or not room or characters_in_room(loc, room, exclude=name):
            return []
        items = []
        for placement in inventory.get_room_items(loc, room):
            item = inventory.get_item(placement.get("item_id", ""))
            if (item and item.get("owner") != name and has_pages(item)
                    and not npc_read_today(name, item["id"])
                    and inventory.placement_visible_to(name, loc, room, placement)):
                items.append(item)
        return items

    def visible_for(self, character_name: str) -> bool:
        return bool(self._candidates(character_name))

    def execute(self, raw_input: str) -> str:
        error = "There is nothing like that to read here."
        data = self._parse_base_input(raw_input)
        name = data.get("agent_name")
        payload = data
        if "item" not in payload:
            try:
                payload = json.loads(data.get("input", ""))
            except (ValueError, TypeError):
                return error
        token = payload.get("item") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token.strip() or not isinstance(name, str):
            return error
        token = token.strip().casefold()
        candidates = self._candidates(name)
        # Names take precedence over IDs, within this room's candidates only.
        def names(item):
            # The prompt may show a localized name (name_<lang>).
            return {str(v).casefold() for k, v in item.items()
                    if (k == "name" or k.startswith("name_")) and v}
        ordered = ([i for i in candidates if token in names(i)]
                   + [i for i in candidates if i["id"].casefold() == token])
        for item in ordered:
            if not readable_here(name, item["id"]):
                continue
            result = npc_read(name, item["id"])
            if "error" in result:
                return error
            lines = [f"You read in {result['item_name']}:"]
            lines.extend(f"[{p.get('heading', '')}]\n{p.get('text', '')[:600]}"
                         for p in result.get("pages", []))
            return "\n".join(lines)
        return error
