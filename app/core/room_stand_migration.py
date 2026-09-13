"""One-time re-placement of everybody standing in a room without a place
(plan-animationen-echtzeit-stehplatz.md T4 Nr. 4).

Since T4 the SERVER picks the point a character stands on in a room, and it
does so on the two write paths that put one there: entering a room and standing
up from a place. Neither has run yet for a character that has been standing in
its room since before the change — it would keep the point it has (the location
centre, a client-invented raster spot, or nothing at all) until its next room
change, and a client now draws it exactly there.

So every roomed character without a place is put on its free standing point
once, with ``near`` = where it stands today: a character that already stands
free does not move at all, and the one in the wall steps out of it.

Idempotent via the ``migration.room_stand_v1`` world_kv flag. A character the
geometry chokes on is logged and skipped — a broken layout must not stop a
boot.
"""
from typing import Dict

from app.core.log import get_logger

logger = get_logger("room_stand_migration")

_FLAG = "migration.room_stand_v1"


def migrate_room_stands_once() -> Dict[str, int]:
    """Put every roomed, place-less character on a free standing point.
    Returns counts for the boot log; ``{}`` when it has run before."""
    from app.core.room_stand import stand_up
    from app.models.character import (get_character_profile,
                                      list_available_characters)
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(_FLAG):
        return {}
    stats = {"checked": 0, "moved": 0, "failed": 0}
    for name in list_available_characters():
        try:
            prof = get_character_profile(name) or {}
            if not (prof.get("current_location") or "") \
                    or not (prof.get("current_room") or "") \
                    or prof.get("place"):
                continue
            stats["checked"] += 1
            if stand_up(name):
                stats["moved"] += 1
        except Exception as e:
            stats["failed"] += 1
            logger.warning("room stand migration: %s skipped (%s)", name, e)
    set_world_setting(_FLAG, "1")
    logger.info("room stand migration: %s", stats)
    return stats
