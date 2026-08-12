#!/usr/bin/env python3
"""Smoke run for the World-Dev field coverage (Block W).

Covers the plumbing the audit found leaking: the location-level semantic
fields (decency / indoor / swim_allowed / style_hint / activity_hint) and the
2D map prompt have to survive ``add_location`` -> DB -> load, in BOTH branches
(new location and update of an existing one), and the room-level overrides
have to come back untouched.

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_worlddev_fields.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worlddev-fields-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.models.world import add_location, list_locations  # noqa: E402

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


def load(name: str) -> dict:
    """The location as the editor sees it — through the normal load path."""
    for loc in list_locations():
        if loc.get("name") == name:
            return loc
    raise AssertionError(f"location {name!r} not found after save")


# The apply path hands these through verbatim; a room carries its own
# overrides and is stored wholesale.
CREATE = dict(
    name="Smoke Bay",
    description="A test bay.",
    decency="nude_ok",
    indoor="outdoor",
    swim_allowed=True,
    style_hint="sunny mediterranean",
    activity_hint="swim and sunbathe",
    image_prompt_day="sunny bay, day",
    image_prompt_night="sunny bay, night",
    image_prompt_map_2d="flat 2d icon of a bay",
    rooms=[{
        "name": "Changing room",
        "description": "Small wooden cabin.",
        "decency": "private",
        "indoor": "indoor",
        "swim_allowed": False,
        "style_hint": "rustic wood",
        "activity_hint": "change clothes",
        "image_prompt_day": "wooden changing cabin, day",
        "image_prompt_night": "wooden changing cabin, night",
    }],
)

# Second call, same name: the UPDATE branch. Every value differs from the
# create, so a branch that silently drops a field cannot pass by accident.
UPDATE = dict(
    name="Smoke Bay",
    description="An edited test bay.",
    decency="private",
    indoor="indoor",
    swim_allowed=False,
    style_hint="covered spa",
    activity_hint="relax in the water",
    image_prompt_day="covered spa, day",
    image_prompt_night="covered spa, night",
    image_prompt_map_2d="flat 2d icon of a spa",
    rooms=[{
        "name": "Pool hall",
        "description": "Warm indoor pool.",
        "decency": "nude_ok",
        "indoor": "outdoor",
        "swim_allowed": True,
        "style_hint": "steamy tiles",
        "activity_hint": "swim laps",
        "image_prompt_day": "indoor pool, day",
        "image_prompt_night": "indoor pool, night",
    }],
)

LOC_FIELDS = ("description", "decency", "indoor", "swim_allowed", "style_hint",
              "activity_hint", "image_prompt_day", "image_prompt_night",
              "image_prompt_map_2d")
ROOM_FIELDS = ("name", "description", "decency", "indoor", "swim_allowed",
               "style_hint", "activity_hint", "image_prompt_day",
               "image_prompt_night")


def run(label: str, payload: dict) -> None:
    print(f"\n[{label}")
    add_location(**payload)
    loc = load(payload["name"])
    for field in LOC_FIELDS:
        check(f"location.{field}", loc.get(field), payload[field])
    rooms = loc.get("rooms") or []
    check("room count", len(rooms), 1)
    if rooms:
        want = payload["rooms"][0]
        for field in ROOM_FIELDS:
            check(f"room.{field}", rooms[0].get(field), want[field])
        check("room has an id", bool(rooms[0].get("id")), True)


def main() -> int:
    run("1] create branch", CREATE)
    run("2] update branch — same name, every value changed", UPDATE)

    print("\n[3] the legacy map prompt is not invented")
    loc = load(UPDATE["name"])
    check("image_prompt_map stays empty", loc.get("image_prompt_map", ""), "")
    check("exactly one location exists", len(list_locations()), 1)

    print(f"\n{CHECKED} fields checked, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
