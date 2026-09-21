"""Group-chat location helper.

The group-chat HTTP surface of the removed vanilla UI is gone (2026-09-21);
the ``group_chats`` table stays (character reinit still clears it). What is
left here is the one helper the thought context still asks for: who is
standing at a location.
"""
from typing import Dict, List

from app.core.log import get_logger
from app.models.character import (
    get_character_current_location,
    get_character_profile_image,
    list_available_characters)

logger = get_logger("group_chat")


def get_characters_at_location(location_id: str
) -> List[Dict[str, str]]:
    """Return all characters currently at the given location.

    Reuses the same logic as the /characters/at-location endpoint.
    """
    from app.models.world import resolve_location

    loc = resolve_location(location_id)
    loc_id = loc.get("id", "") if loc else ""

    all_chars = list_available_characters()
    result = []
    for name in all_chars:
        char_loc = get_character_current_location(name)
        if char_loc and (char_loc == loc_id or char_loc == location_id):
            profile_img = get_character_profile_image(name)
            result.append({
                "name": name,
                "profile_image": profile_img or "",
                "avatar_url": (
                    f"/characters/{name}/images/{profile_img}"
                    if profile_img else ""
                ),
            })
    return result
