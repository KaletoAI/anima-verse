#!/usr/bin/env python3
"""Smoke run for PLACES (app/core/places.py, plan-posen-plaetze.md § 3.6/§ 4).

Throwaway storage, private pose catalog, no server, no clips needed.

World: one location "Smoke House" at (0, 0), plan 10 m with a DRAWN 10 m
boundary (since 2026-08-19 a width alone is no area, and ``set_character_pos``
derives the location from the point — without the boundary every position
write would put the characters into the open), room "lounge" (min corner
−4/−4, 8 × 6 m) with three markers:
  s1  group seat, at (1, 1), capacity 1, facing 0      → slot (−3, −3)
  s2  group seat, at (5, 1), capacity 2, spacing 0.6,
      facing 0 (south): lateral (cos 0, −sin 0) = (1, 0)
      → slots (1 − 0.3, −3) = (0.7, −3) and (1.3, −3)
  b1  group bed,  at (2, 4), capacity 1               → slot (−2, 0)
Catalog: standing (stand, default), sitting (seat, default of seat),
reading (seat), sleeping (bed, default of bed), cuddling (seat, solo false,
places 2, animation "cuddle").

Hand-derived expectations:
  [1] room_places("lounge") has 3 places, s2.slots == [[0.7,-3],[1.3,-3]],
      s1.root_offset == 0.534 (0.314 × 1.70 = 0.5338, millimetres).
      where("Ann") == (house, "lounge").
  [2] assign: Ann "sitting" → s1. All seats have 0 occupants, so the nearest
      slot to Ann's point (−3.5, −3.5) wins: s1 slot (−3, −3) is
      √(0.5² + 0.5²) = 0.71 m away, s2 slot 0 (0.7, −3) is
      √(4.2² + 0.5²) = 4.23 m. Ann's map position becomes (−3, −3).
      Bob "sitting" → s2 slot 0 (s1 full). Cid "sitting" → s2 slot 1.
      Dan "sitting" → None (no free seat), his position (−3.5, −3.5) is
      untouched and his profile carries no place. Bob "reading" keeps
      s2 slot 0 (same group). Bob "sleeping" → b1 (group change frees
      s2 slot 0), Bob stands at (−2, 0); Dan "sitting" now gets s2 slot 0.
      occupancy: s1 [Ann/0], s2 [Dan/0, Cid/1], b1 [Bob/0].
  [3] release: Ann cleared → s1 free again (occupancy has no s1);
      place_of(Ann) is None; her position stays (−3, −3). A stale id
      ("gone") on a profile reads as None and does not count as occupancy.
      Ann moved to (1, −3.2) — 0.36 m from s2 slot 0 (0.7, −3) and 4.0 m
      from s1 (−3, −3) — with assign(prefer="s1") takes s1 anyway, position
      (−3, −3). Eve (never placed) with assign(prefer="s1") raises
      PlaceUnavailable, her profile stays without a place and her position
      (−3.5, −3.5) is untouched. The inventory is cached: after b1 is
      removed from the layout, room_places still lists it until
      invalidate(); afterwards Bob's held b1 reads as no place.

Usage:  ./.venv/bin/python scripts/smoke_places.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="places-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import places, pose_catalog  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_pos, get_character_profile, save_character_current_location,
    save_character_current_room, save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────
# A private pose catalog: the real one must not be edited.
CAT = Path(tempfile.mkdtemp(prefix="places-cat-"))
_orig_catalog_path = pose_catalog.catalog_path
pose_catalog.catalog_path = (
    lambda axis: CAT / "pose_catalog.json" if axis == "pose" else _orig_catalog_path(axis))
(CAT / "pose_catalog.json").write_text(json.dumps({
    "groups": {"seat": {"label": "Seat", "root_drop": 0.314, "default": "sitting"},
               "bed": {"label": "Bed", "root_drop": 0.631, "default": "sleeping"},
               "stand": {"label": "Standing spot", "root_drop": 0, "default": "standing"}},
    "entries": {"standing": {"prompt": "p", "animation": "idle", "group": "stand", "_default": True},
                "sitting": {"prompt": "p", "animation": "sit", "group": "seat"},
                "reading": {"prompt": "p", "animation": "sit", "group": "seat"},
                "sleeping": {"prompt": "p", "animation": "sleep", "group": "bed"},
                "cuddling": {"prompt": "p", "animation": "cuddle", "group": "seat",
                             "solo": False, "places": 2, "yaw_offset": 0}}}), encoding="utf-8")
pose_catalog.reload_catalogs()

HOUSE = add_location(name="Smoke House", description="places smoke",
                     rooms=[{"id": "lounge", "name": "Lounge"}])["id"]
update_location_position(HOUSE, 0.0, 0.0)

MARKERS = [
    {"id": "s1", "group": "seat", "at": [1, 1], "rotation": 0},
    {"id": "s2", "group": "seat", "at": [5, 1], "capacity": 2, "spacing_m": 0.6, "rotation": 0},
    {"id": "b1", "group": "bed", "at": [2, 4]},
]


def write_layout(markers) -> None:
    data = _load_world_data()
    for loc in data["locations"]:
        if loc["id"] == HOUSE:
            map3d = loc.setdefault("map3d", {})
            map3d["plan_width_m"] = 10.0
            map3d["boundary"] = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
            loc["rooms"][0]["layout"] = {"x": -4, "y": -4, "w": 8, "d": 6,
                                         "markers": list(markers)}
    _save_world_data(data)


write_layout(MARKERS)
places.invalidate()


def person(name: str, x: float, z: float) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    save_character_current_location(name, HOUSE)
    # The point is the truth: set_character_pos derives the location from it.
    set_character_pos(name, x, z)
    save_character_current_room(name, "lounge")


for _n in ("Ann", "Bob", "Cid", "Dan", "Eve"):
    person(_n, -3.5, -3.5)


def field(place_id: str, slot) -> dict:
    return {"id": place_id, "slot": slot, "room_id": "lounge"}


# ── [1] inventory ───────────────────────────────────────────────────────
print("[1] inventory")
pl = {p["id"]: p for p in places.room_places(HOUSE, "lounge")}
check("three places", sorted(pl) == ["b1", "s1", "s2"], str(sorted(pl)))
check("s1 slot is (−3, −3)", pl.get("s1", {}).get("slots") == [[-3.0, -3.0]],
      str(pl.get("s1", {}).get("slots")))
check("s2 slots", pl.get("s2", {}).get("slots") == [[0.7, -3.0], [1.3, -3.0]],
      str(pl.get("s2", {}).get("slots")))
check("b1 slot is (−2, 0)", pl.get("b1", {}).get("slots") == [[-2.0, 0.0]],
      str(pl.get("b1", {}).get("slots")))
check("s1 root_offset 0.534", pl.get("s1", {}).get("root_offset") == 0.534,
      str(pl.get("s1", {}).get("root_offset")))
check("s2 capacity 2, group seat, room lounge",
      pl.get("s2", {}).get("capacity") == 2 and pl.get("s2", {}).get("group") == "seat"
      and pl.get("s2", {}).get("room_id") == "lounge")
check("unknown room has no places", places.room_places(HOUSE, "attic") == [])
check("where(Ann)", places.where("Ann") == (HOUSE, "lounge"), str(places.where("Ann")))
check("nobody holds a place yet", places.occupancy(HOUSE, "lounge") == {},
      str(places.occupancy(HOUSE, "lounge")))

# ── [2] assignment ──────────────────────────────────────────────────────
print("\n[2] assignment")
a = places.assign("Ann", "sitting")
check("Ann → s1 (nearest: 0.71 m vs 4.23 m)", a == field("s1", 0), str(a))
check("Ann moved to the slot", get_character_pos("Ann") == {"x": -3.0, "z": -3.0},
      str(get_character_pos("Ann")))
check("Ann's profile carries the place",
      (get_character_profile("Ann") or {}).get("place") == field("s1", 0))
check("Bob → s2/0 (s1 full)", places.assign("Bob", "sitting") == field("s2", 0))
check("Bob stands on slot 0", get_character_pos("Bob") == {"x": 0.7, "z": -3.0},
      str(get_character_pos("Bob")))
check("Cid → s2/1", places.assign("Cid", "sitting") == field("s2", 1))
check("Cid stands on slot 1", get_character_pos("Cid") == {"x": 1.3, "z": -3.0},
      str(get_character_pos("Cid")))
check("Dan → None (no free seat)", places.assign("Dan", "sitting") is None)
check("Dan's position untouched", get_character_pos("Dan") == {"x": -3.5, "z": -3.5},
      str(get_character_pos("Dan")))
check("Dan holds no place", not (get_character_profile("Dan") or {}).get("place"))
check("Bob keeps s2/0 on reading (same group)",
      places.assign("Bob", "reading") == field("s2", 0))
check("Bob → b1 on sleeping (group change)", places.assign("Bob", "sleeping") == field("b1", 0))
check("Bob lies on b1", get_character_pos("Bob") == {"x": -2.0, "z": 0.0},
      str(get_character_pos("Bob")))
check("Dan → s2/0 now (freed by Bob)", places.assign("Dan", "sitting") == field("s2", 0))
occ = places.occupancy(HOUSE, "lounge")
check("occupancy s1 [Ann/0], s2 [Dan/0, Cid/1], b1 [Bob/0]",
      occ.get("s1") == [("Ann", 0)] and sorted(occ.get("s2") or []) == [("Cid", 1), ("Dan", 0)]
      and occ.get("b1") == [("Bob", 0)], str(occ))
check("free_slots of a full s2 is empty", places.free_slots(pl["s2"], occ["s2"]) == [])
check("free_slots of s2 without Cid is [1]",
      places.free_slots(pl["s2"], [("Dan", 0)]) == [1])
po = places.place_of("Dan")
check("place_of(Dan) = s2 slot 0 at (0.7, −3)",
      po is not None and po["id"] == "s2" and po["slot"] == 0
      and po["x"] == 0.7 and po["z"] == -3.0, str(po))

# ── [3] release, stale ids, prefer, invalidation ────────────────────────
print("\n[3] release, stale ids, prefer, invalidation")
places.release("Ann")
check("release clears the profile", (get_character_profile("Ann") or {}).get("place") is None)
check("place_of(Ann) is None", places.place_of("Ann") is None)
check("s1 is free again", "s1" not in places.occupancy(HOUSE, "lounge"),
      str(places.occupancy(HOUSE, "lounge")))
check("release leaves the position", get_character_pos("Ann") == {"x": -3.0, "z": -3.0})
places.release("Ann")
check("release twice is harmless", (get_character_profile("Ann") or {}).get("place") is None)

_prof = get_character_profile("Ann")
_prof["place"] = field("gone", 0)
save_character_profile("Ann", _prof)
check("a stale id reads as no place", places.place_of("Ann") is None)
check("a stale id is no occupancy", "gone" not in places.occupancy(HOUSE, "lounge"),
      str(places.occupancy(HOUSE, "lounge")))

set_character_pos("Ann", 1.0, -3.2)
check("Ann now 0.36 m from s2/0 (nearest) …", get_character_pos("Ann") == {"x": 1.0, "z": -3.2})
check("… but prefer='s1' takes s1", places.assign("Ann", "sitting", prefer="s1") == field("s1", 0))
check("Ann sits on s1", get_character_pos("Ann") == {"x": -3.0, "z": -3.0},
      str(get_character_pos("Ann")))
try:
    places.assign("Eve", "sitting", prefer="s1")
    check("prefer on a taken s1 raises PlaceUnavailable", False, "no exception")
except places.PlaceUnavailable as e:
    check("prefer on a taken s1 raises PlaceUnavailable", True, str(e))
check("Eve holds no place", not (get_character_profile("Eve") or {}).get("place"))
check("Eve's position untouched", get_character_pos("Eve") == {"x": -3.5, "z": -3.5})
check("PlaceUnavailable is a ValueError", issubclass(places.PlaceUnavailable, ValueError))

write_layout([m for m in MARKERS if m["id"] != "b1"])
check("the inventory is cached until invalidate()",
      sorted(p["id"] for p in places.room_places(HOUSE, "lounge")) == ["b1", "s1", "s2"])
places.invalidate()
check("invalidate() drops b1", sorted(p["id"] for p in places.room_places(HOUSE, "lounge")) == ["s1", "s2"])
check("Bob's vanished bed reads as no place", places.place_of("Bob") is None)
check("… and is no occupancy", "b1" not in places.occupancy(HOUSE, "lounge"))

# ── summary ─────────────────────────────────────────────────────────────
print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
