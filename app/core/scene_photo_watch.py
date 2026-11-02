"""Notice secret photographs and apply once-per-observer consequences."""
from app.core.i18n import t
from app.core.keyed_lock import keyed_lock

DISCOVERY_BASE = 0.35
DEPICTED_MULTIPLIER = 1.7
DISTRACTED_MULTIPLIER = 0.25
DISCOVERY_MAX = 0.95


def discovery_chance(watcher: str, *, depicted: bool) -> float:
    """Sleeping observers never notice; other attention modifies the roll."""
    from app.models.character import get_character_profile, is_character_sleeping
    from app.core.attention import is_distracted
    profile = get_character_profile(watcher) or {}
    if is_character_sleeping(watcher, profile=profile):
        return 0.0
    chance = DISCOVERY_BASE * (DEPICTED_MULTIPLIER if depicted else 1)
    if is_distracted(watcher, profile=profile):
        chance *= DISTRACTED_MULTIPLIER
    return max(0.0, min(DISCOVERY_MAX, chance))


def discover_photo(photographer: str, filename: str, subjects: list[str],
                   watcher: str, location: str, room: str, *, shown: bool = False) -> bool:
    """Claim knowledge once, then publish consequences without holding a lock."""
    from app.models import secrets
    from app.models.character import get_character_language
    ref = f"secret_photo:{filename}"
    lang = get_character_language(photographer)
    with keyed_lock("secret_photo", (photographer, filename)):
        secret = next((s for s in secrets.list_secrets(photographer, strict=True)
                       if s.get("source_ref") == ref), None)
        if secret and watcher in secret.get("known_by", []):
            return False
        if secret is None:
            secret = secrets.add_secret(photographer,
                t("{photographer} secretly took a photo.", lang).format(photographer=photographer),
                category="relationship", severity=3, related_characters=subjects,
                source="discovered", source_ref=ref)
        secrets.add_known_by(photographer, secret["id"], watcher, discovered=True)

    from app.core.perception import record_utterance, STORYTELLER_SPEAKER
    from app.models.memory import add_memory
    from app.models.relationship import record_interaction
    from app.models.account import is_player_controlled
    from app.models.notifications import create_notification
    depicted = watcher in subjects
    source = ("{watcher} realizes the photo was taken secretly." if shown else
              "{watcher} notices {photographer} secretly taking a photo of them." if depicted else
              "{watcher} notices {photographer} secretly taking a photo.")
    line = t(source, lang).format(watcher=watcher, photographer=photographer)
    record_utterance(speaker=STORYTELLER_SPEAKER, content=line,
                     location_id=location, room_id=room, anchor=photographer,
                     source="secret_photo")
    for name, source in [(watcher, "I discovered that {photographer} secretly took a photo."),
                         (photographer, "{watcher} discovered that I secretly took a photo.")]:
        add_memory(name, t(source, get_character_language(name)).format(
            photographer=photographer, watcher=watcher),
            memory_type="episodic", importance=4, tags=["photo", "caught"])
    record_interaction(watcher, photographer, "caught_photographing",
                       sentiment_delta_a=-0.4 if depicted else -0.3,
                       sentiment_delta_b=0.0, strength_delta=0.0)
    if is_player_controlled(watcher):
        create_notification(watcher, t("You discover that {photographer} secretly took a photo.",
                                      get_character_language(watcher)).format(photographer=photographer))
    else:
        from app.core.agent_loop import get_agent_loop
        hint = (f"You just discovered that {photographer} secretly photographed"
                f"{' you' if depicted else ' the scene'}. You are upset. React strongly.")
        get_agent_loop().bump_respond(watcher, speaker=photographer, content=hint,
                                     on_demand=True, obligatory=True, hint=hint)
    return True


def reveal_photo(photographer: str, filename: str) -> list[str]:
    """Showing reveals a secret photo only to depicted people here now."""
    from app.models.character import (get_single_image_meta, get_character_current_location,
                                      get_character_current_room, is_character_sleeping)
    from app.core.room_entry import characters_in_room
    meta = get_single_image_meta(photographer, filename)
    if not meta.get("secret"):
        return []
    subjects = meta.get("photo_subjects") or []
    loc = get_character_current_location(photographer) or ""
    room = get_character_current_room(photographer) or ""
    if not loc or not room:
        return []  # An empty room query would mean the entire location.
    return [name for name in characters_in_room(loc, room)
            if name != photographer and name in subjects and not is_character_sleeping(name)
            and discover_photo(photographer, meta.get("photo_id") or filename, subjects,
                               name, loc, room, shown=True)]
