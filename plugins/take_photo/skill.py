"""TakePhoto verb — the LLM tool surface of the core image service.

The character takes a photo / creates an image; all heavy lifting
(backend pool, instance selection, prompt pipeline, gallery) lives in
the core ImageService (app/imagegen/service.py, R5 — many consumers).
This package only contributes the tool the LLM can call.

SKILL_ID stays "image_generation": per-character config files and the
F8 capability key (📷 scene photo) keep working unchanged; only the
tool NAME was renamed to TakePhoto (approved rename table §8.2).

A TEMPORARY NPC shoots for somebody else (plan-npc-leben, task 3). It is a
disposable extra whose whole gallery disappears with it, so its photo belongs
to the avatar it is talking to — and without an avatar present there is
nobody to hand a picture to, so it does not shoot at all. Both halves live
here, in the package, because the core must not know what a photo is.
"""
import json
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


def _avatar_in_room(character_name: str) -> str:
    """The avatar standing in the same room as *character_name*, or "".

    "Avatar" is the codebase's third noun: a character a human has taken over
    (``get_all_avatars`` reads every user's active character, so this also
    answers outside a request — the agent loop shoots without a browser).
    With several avatars in the room the one whose user is driving THIS turn
    wins (``get_active_character``), otherwise the first one present.

    A character the map places nowhere has no room and therefore no partner —
    the honest answer for a wanderer between two locations.
    """
    from app.core.room_entry import _list_characters_in_room
    from app.models.account import get_active_character, get_all_avatars
    from app.models.character import (get_character_current_location,
                                      get_character_current_room)

    location_id = (get_character_current_location(character_name) or "").strip()
    if not location_id:
        return ""
    room_id = (get_character_current_room(character_name) or "").strip()
    avatars = get_all_avatars()
    present = [c for c in _list_characters_in_room(location_id, room_id,
                                                   exclude=character_name)
               if c in avatars]
    if not present:
        return ""
    active = (get_active_character() or "").strip()
    return active if active in present else present[0]


class TakePhotoSkill(PluginSkill):
    """Character takes a photo — thin wrapper over the image service."""

    SKILL_ID = "image_generation"
    DEFERRED = True  # image is generated after the chat reply
    PROGRESS_TYPE = "image"  # count-based intent/assignment progress

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/image_generation.md
        # Per-character settings use the service's instance-based config —
        # no generic _defaults fields here.
        self._defaults = {}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "TakePhoto is disabled."
        from app.imagegen.service import get_image_service
        svc = get_image_service()
        if not svc.enabled:
            return ("Image generation is not available. No instance "
                    "configured or reachable.")

        data = self._parse_base_input(raw_input)
        character_name = str(data.get("agent_name") or "").strip()
        if character_name and self._is_temporary_npc(character_name):
            owner = _avatar_in_room(character_name)
            if not owner:
                # In-character, and a real answer for the LLM: nothing was
                # rendered, so the reply must not claim a picture exists.
                return (f"{character_name} lowers the camera again — there is "
                        f"nobody here to show a picture to. No photo is taken.")
            # The gallery is the avatar's, the PROMPT stays the NPC's: only
            # the owner field moves, so appearance, outfit, location and the
            # reference slots are still resolved for the photographer.
            data["gallery_character"] = owner
            raw_input = json.dumps(data, ensure_ascii=False)
        return svc.generate_from_input(raw_input)

    def _is_temporary_npc(self, character_name: str) -> bool:
        """Template feature, never a name (fails closed)."""
        try:
            from app.models.character import is_temporary_npc
            return is_temporary_npc(character_name)
        except Exception as e:  # noqa: BLE001
            self.ctx.logger.debug("temporary-NPC check for %s failed: %s",
                                  character_name, e)
            return False

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        if "usage_instructions" in self.config:
            return self.config["usage_instructions"]
        from app.core.tool_formats import format_example
        return format_example(format_name or "tag", self.name,
                              "young woman with blonde hair at the beach, sunset")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=f"{self.description}. Input should be a detailed "
                        f"description of the desired image.",
            func=self.execute)
