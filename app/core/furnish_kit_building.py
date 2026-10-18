"""Furnish empty building rooms deterministically without opening jobs."""
from typing import Dict

from app.core import furniture_kits, room_furnish
from app.core.keyed_lock import keyed_lock
from app.models import world


def furnish_location(location_id: str, kit: str, *, dry_run: bool) -> Dict:
    """Serialize building plans and re-check emptiness when writing them.

    A preview follows the same solver path as a real call, so confirmation
    can describe the saved geometry without changing the world.
    """
    with keyed_lock("furnish_kit", location_id):
        if not isinstance(kit, str) or kit not in furniture_kits.load_kits():
            raise room_furnish.FurnishError("Unknown furniture kit.", 400)
        loc = world.get_location_by_id(location_id)
        if not loc:
            raise room_furnish.FurnishError("Unknown location.", 404)
        rooms, skipped = [], []
        library = room_furnish._library()
        height = room_furnish._storey_height_m(loc)
        for room in loc.get("rooms", []):
            room_id = str(room.get("id") or "")
            if room_id == world.GROUND_ROOM_ID or world.is_floor_room(room_id):
                continue
            identity = {"room_id": room_id, "name": room.get("name") or ""}
            layout = room.get("layout")
            room_type = furniture_kits.room_type_of(room)
            if room_furnish._get_row(room_id):
                reason = "job_open"
            elif isinstance(layout, dict) and layout.get("props"):
                reason = "has_furniture"
            elif not room_type:
                reason = "no_room_type"
            else:
                reason = ""
                try:
                    geom = room_furnish._geometry(loc, room)
                except (room_furnish.FurnishError, ValueError, TypeError):
                    # A corrupt x/y/w/d must cost this room, not the building.
                    reason = "no_layout"
            if reason:
                skipped.append({**identity, "reason": reason})
                continue
            result = furniture_kits.solve_kit(
                kit=kit, room_type=room_type, geom=geom, library=library,
                room_id=room_id, existing=[], storey_height_m=height)
            placements = result.get("placed") or []
            if not placements:
                # Nothing to write: reporting it as furnished would also make
                # every later run "furnish" it again with an empty list.
                skipped.append({**identity, "reason": "nothing_placed"})
                continue
            ox, oy = geom.get("origin") or [0, 0]
            for entry in placements:
                if entry.get("on"):
                    continue
                at = entry.get("at") or [0, 0]
                entry["at"] = [round(float(at[0]) + ox, 2),
                               round(float(at[1]) + oy, 2)]
            rooms.append({**identity, "room_type": room_type,
                          "placed": len(placements),
                          "unplaced": len(result.get("unplaced") or []),
                          "missing_roles": result.get("missing_roles") or [],
                          "placements": placements})
        if not dry_run:
            written = world.append_rooms_props(location_id, {
                room["room_id"]: room["placements"] for room in rooms})
            accepted = []
            for room in rooms:
                if written.get(room["room_id"], False):
                    accepted.append(room)
                else:
                    skipped.append({"room_id": room["room_id"], "name": room["name"],
                                    "reason": "has_furniture"})
            rooms = accepted
        return {"rooms": rooms, "skipped": skipped}
