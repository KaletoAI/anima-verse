#!/usr/bin/env python3
"""Smoke run for the location background pick: ground room + day/night.

Two things are checked here.

**The ground room** ``__ground__`` is the outdoors of a location. It used to
fall through to the location's UNTAGGED images — which are the inside, so
standing outside showed the living room in /play (F8: strict, no image). F8b
gives it the images that DO show the outside: the location's EXTERIOR renders,
i.e. gallery images of type ``building-front`` (the same marker
``location_model3d.py`` reads for the 3D building model), and any image tagged
to the ground room itself.

**Day/night** is decided by ``get_background_path`` ITSELF, from the GAME
calendar (``game_time().is_day()`` → the current season's sunrise/sunset).
There is no ``hour`` argument and no query parameter any more — no caller, and
above all no browser, can tell the world what time of day it is. The former
binary split ("day" = hour 6..17) is gone with it, so a season whose sun rises
at 08:00 really gets night images at 07:00.

Expectations derived by hand from the rule set in ``get_background_path``
(``stable=True`` picks ``sorted(...)[0]``; a candidate typed for the CURRENT
half wins, else an untyped one, else any):

  gallery of the location:
    interior.png  — untagged, no type (the location default)
    living.png    — tagged to the "Living room" room
    outside.png   — untagged, type "building-front" (the exterior render; note it is
                    NOT flagged as a background image, exactly as the
                    generator leaves building renders)
    ground_day.png / ground_night.png — tagged to __ground__, types day/night

  Calendar.default(): every season sunrise 06:00, sunset 18:00.

  1) room = Living room   -> living.png    (the room owns an image)
  2) room = Cellar        -> interior.png  (untagged fallback for a NORMAL room)
  3) room = ""            -> interior.png  (no room at all -> location default)
  4) room = __ground__, only interior.png+living.png present
                          -> None          (no exterior -> no background)
  5) room = __ground__, outside.png present
                          -> outside.png   (the exterior, NEVER the interior),
                             at 10:00 and at 22:00 alike — a building render
                             carries no time of day, so the day/night tail ends
                             on the neutral pick
  6) room = __ground__ with ground_day.png + ground_night.png
                          -> 10:00 -> ground_day.png, 22:00 -> ground_night.png
                             (the ground-tagged images win over outside.png and
                             run through the SAME day/night rule as any room)
  7) room = Cellar, strict_room=True -> None (strict mode untouched by F8b)
  8) a calendar whose season runs sunrise 08:00 / sunset 20:00
                          -> 07:00 -> ground_night.png (the old fixed rule said
                             day), 09:00 -> ground_day.png,
                             19:00 -> ground_day.png (the old fixed rule said
                             night). This is the whole point of asking the
                             calendar: sunrise moves, the picture follows.

Runs against a THROWAWAY storage directory — it never touches a real world.
The game clock is re-anchored with factor 0.0, so it stands still while the
checks run.

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

from app.core import game_time as game_time_mod  # noqa: E402
from app.core.game_time import (  # noqa: E402
    EPOCH, Calendar, GameDuration, Season,
)
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, add_location, get_background_path, list_locations,
    set_gallery_image_room, set_gallery_image_type, toggle_background_image,
)

FAILURES = []
CHECKED = 0

# Same shape as the default calendar (4 seasons x 30 days) so only the sun
# times differ — the canonical GameTime strings stay comparable.
LATE_SUN = Calendar(
    seasons=tuple(Season(key=s.key, name=s.name, days=s.days,
                         sunrise_min=8 * 60, sunset_min=20 * 60)
                  for s in Calendar.default().seasons))


def use_calendar(calendar: Calendar) -> None:
    """Point the module-level calendar lookup at ``calendar`` (no config)."""
    game_time_mod.get_calendar = lambda: calendar


def at(hour: int, minute: int = 0) -> None:
    """Stop the game clock at day 1, ``hour:minute`` of the world calendar."""
    set_game_factor(0.0)
    set_game_time(EPOCH + GameDuration(hour * 3600 + minute * 60))


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    use_calendar(Calendar.default())
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
    at(10)

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
    at(22)
    check("ground background at 22:00",
          get_background_path(loc_id, room=GROUND_ROOM_ID), None)

    print("\n[5] the exterior render is the ground's background")
    # A building render as the generator leaves it: typed, NOT background-flagged.
    # The type is a building VIEW since the multiview round of 2026-09-02: the
    # bare ``building`` was migrated to ``building-front`` and no reader knows
    # it any more, so a fixture writing the old word tags an image nothing
    # recognises as an exterior.
    put("outside.png", background=False, itype="building-front")
    at(10)
    check("ground at 10:00", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                                 stable=True),
          gallery / "outside.png")
    at(22)
    check("ground at 22:00", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                                 stable=True),
          gallery / "outside.png")
    check("the interior is untouched by it",
          get_background_path(loc_id, room=cellar, stable=True),
          gallery / "interior.png")

    print("\n[6] ground-tagged day/night images follow the game clock")
    put("ground_day.png", background=True, room=GROUND_ROOM_ID, itype="day")
    put("ground_night.png", background=True, room=GROUND_ROOM_ID, itype="night")
    at(10)
    check("ground at 10:00", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                                 stable=True),
          gallery / "ground_day.png")
    at(22)
    check("ground at 22:00", get_background_path(loc_id, room=GROUND_ROOM_ID,
                                                 stable=True),
          gallery / "ground_night.png")

    print("\n[7] strict_room is unchanged")
    check("cellar strict", get_background_path(loc_id, room=cellar,
                                               strict_room=True), None)

    print("\n[8] the SEASON's sunrise/sunset decides, not a fixed hour")
    use_calendar(LATE_SUN)
    at(7)
    check("07:00 with sunrise 08:00 is night",
          get_background_path(loc_id, room=GROUND_ROOM_ID, stable=True),
          gallery / "ground_night.png")
    at(9)
    check("09:00 with sunrise 08:00 is day",
          get_background_path(loc_id, room=GROUND_ROOM_ID, stable=True),
          gallery / "ground_day.png")
    at(19)
    check("19:00 with sunset 20:00 is still day",
          get_background_path(loc_id, room=GROUND_ROOM_ID, stable=True),
          gallery / "ground_day.png")
    at(20)
    check("20:00 is sunset, so night",
          get_background_path(loc_id, room=GROUND_ROOM_ID, stable=True),
          gallery / "ground_night.png")

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
