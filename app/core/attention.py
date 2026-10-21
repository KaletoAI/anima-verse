"""Generic distraction checks for observers of activity in a room."""
from __future__ import annotations


def is_distracted(name: str, *, profile: dict | None = None) -> bool:
    """Whether sleep, a pair, conversation or a declared flag occupies attention.

    Reuse a supplied profile, including an empty one, for all profile reads.
    Conversation membership is derived from recent room utterances in game time.
    """
    from app.models.character import get_character_profile, is_character_sleeping
    from app.core.interaction_engine import get_interaction
    from app.core.conversation_pairs import conversation_partner
    from app.plugins.registry import flag_specs

    if profile is None:
        profile = get_character_profile(name) or {}
    if is_character_sleeping(name, profile=profile):
        return True
    if get_interaction(name, profile=profile) is not None:
        return True
    if conversation_partner(name, profile.get("current_location", ""),
                            profile.get("current_room", "")) is not None:
        return True
    return any(spec.distracting and bool(profile.get(spec.flag))
               for spec in flag_specs())
