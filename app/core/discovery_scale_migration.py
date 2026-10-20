"""Convert legacy hidden placements to the stat scale once per world."""


def migrate_discovery_scale_once() -> int:
    """Preserve legacy invisibility with difficulty 101; return changed count.

    The marker is written only after every location upsert succeeds. Retrying
    an interrupted migration is safe and never deletes unrelated locations.
    """
    from app.models.world import (list_locations, upsert_location,
                                  world_write_lock, get_world_setting, set_world_setting)
    with world_write_lock:
        if get_world_setting("discovery_scale") == "stat":
            return 0
        count = 0
        for location in list_locations():
            changed = False
            for room in location.get("rooms") or []:
                for placement in room.get("items") or []:
                    if placement.get("hidden"):
                        placement["discovery_difficulty"] = 101
                        count += 1
                        changed = True
            if changed and not upsert_location(location, sync_world=False):
                raise RuntimeError("Could not migrate item discovery scale")
        set_world_setting("discovery_scale", "stat")
        return count
