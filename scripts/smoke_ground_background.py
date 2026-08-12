#!/usr/bin/env python3
"""Smoke run for the ground room's background (findings F8 + F8b).

The ground room ``__ground__`` is the outdoors of a location. It used to fall
through to the location's UNTAGGED images — which are the inside, so standing
outside showed the living room in /play (F8: strict, no image). F8b gives it
the images that DO show the outside: the location's EXTERIOR renders, i.e.
gallery images of type ``building`` (the same marker ``location_model3d.py``
reads for the 3D building model), and any image tagged to the ground room
itself. The pick reuses the shared day/night tail of ``get_background_path``.

Expectations derived by hand from the rule set in ``get_background_path``
(day = hour 6..17, night = 18..5; ``stable=True`` picks ``sorted(...)[0]``):

  gallery of the location:
    interior.png  — untagged, no type (the location default)
    living.png    — tagged to the "Living room" room
    outside.png   — untagged, type "building" (the exterior render; note it is
                    NOT flagged as a background image, exactly as the
                    generator leaves building renders)
    ground_day.png / ground_night.png — tagged to __ground__, types day/night

  1) room = Living room   -> living.png    (the room owns an image)
  2) room = Cellar        -> interior.png  (untagged fallback for a NORMAL room)
  3) room = ""            -> interior.png  (no room at all -> location default)
  4) room = __ground__, only interior.png+living.png present
                          -> None          (no exterior -> no background)
  5) room = __ground__, outside.png present
                          -> outside.png   (the exterior, NEVER the interior),
                             at hour 10 and at hour 22 alike — a building render
                             carries no time of day, so the day/night tail ends
                             on the neutral pick
  6) room = __ground__ with ground_day.png + ground_night.png
                          -> hour 10 -> ground_day.png, hour 22 -> ground_night.png
                             (the ground-tagged images win over outside.png and
                             run through the SAME day/night rule as any room)
  7) room = Cellar, strict_room=True -> None (strict mode untouched by F8b)

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_ground_background.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="ground-bg-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, add_location, get_background_path, list_locations,
    set_gallery_image_room, set_gallery_image_type, toggle_background_image,
)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    add_location(
        name="Smoke House",
        description="A test house.",
        rooms=[{"name": "Living room", "description": "Sofa and a lamp."},
               {"name": "Cellar", "description": "Dark and empty."}],
    )
    loc = next(x for x in list_locations() if x.get("name") == "Smoke House")
    loc_id = loc["id"]
    rooms = {r.get("name", ""): r.get("id", "") for r in (loc.get("rooms") or [])}
    living = rooms.get("Living room", "")
    cellar = rooms.get("Cellar", "")
    check("the ground room exists", GROUND_ROOM_ID in rooms.values(), True)

    gallery = STORAGE / "world_gallery" / loc_id
    gallery.mkdir(parents=True, exist_ok=True)

    def put(name: str, *, background: bool, room: str = "", itype: str = "") -> None:
        (gallery / name).write_bytes(b"fake png")
        if background:
            toggle_background_image(loc_id, name)
        if room:
            set_gallery_image_room(loc_id, name, room)
        if itype:
            set_gallery_image_type(loc_id, name, itype)

    # Only the living room image carries a room tag; interior.png stays the
    # untagged location default.
    put("interior.png", background=True)
    put("living.png", background=True, room=living)

    print("\n[1] a room with its own image gets it")
    check("living room background", get_background_path(loc_id, room=living),
          gallery / "living.png")

    print("\n[2] the untagged fallback still works for a normal room")
    check("cellar background", get_background_path(loc_id, room=cellar),
          gallery / "interior.png")

    print("\n[3] no room at all -> location default")
    check("location background", get_background_path(loc_id, room=""),
          gallery / "interior.png")

    print("\n[4] without an exterior the ground stays empty")
    check("ground background", get_background_path(loc_id, room=GROUND_ROOM_ID),
          None)
    check("ground background at 22h",
          get_background_path(loc_id, room=GROUND_ROOM_ID, hour=22), None)

    print("\n[5] the exterior render is the ground's background")
    # A building render as the generator leaves it: typed, NOT background-flagged.
    put("outside.png", background=False, itype="building")
    check("ground at 10h", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                               hour=10, stable=True),
          gallery / "outside.png")
    check("ground at 22h", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                               hour=22, stable=True),
          gallery / "outside.png")
    check("the interior is untouched by it",
          get_background_path(loc_id, room=cellar, stable=True),
          gallery / "interior.png")

    print("\n[6] ground-tagged day/night images win and follow the hour")
    put("ground_day.png", background=True, room=GROUND_ROOM_ID, itype="day")
    put("ground_night.png", background=True, room=GROUND_ROOM_ID, itype="night")
    check("ground at 10h", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                               hour=10, stable=True),
          gallery / "ground_day.png")
    check("ground at 22h", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                               hour=22, stable=True),
          gallery / "ground_night.png")

    print("\n[7] strict_room is unchanged")
    check("cellar strict", get_background_path(loc_id, room=cellar,
                                               strict_room=True), None)

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
