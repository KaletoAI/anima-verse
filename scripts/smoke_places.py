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
  [4] The setter. Ann holds s1 without a pose: clear_pose_intent releases
      it anyway (a place alone is reason enough to clear). Then
      set_pose_intent("Eve", "sitting") seats Eve on s1 — s2 is full
      (Dan/0, Cid/1) — so profile["place"] is {s1, 0, lounge}, Eve stands
      on (−3, −3), and the SSE activity_changed carries that place. A
      repeated identical setter publishes nothing and keeps s1.
      set_pose_intent("Eve", "standing") releases (group stand has no
      marker here): place None, the SSE carries place None. Seated again
      and cleared with clear_pose_intent: place None. The worldmap row
      (show_all — a fogged row is thinned to null) of the seated Eve
      carries place {id s1, slot 0, x −3, z −3, facing 0.0 (rotation 0
      in an unrotated room), room_id lounge}; Ann's row (nothing held)
      carries null, and so does Eve's row in a fogged payload.
  [4b] Hardening. A profile place {id s1, room_id "kitchen"} neither
      counts in the lounge's occupancy nor resolves — marker ids are per
      room, s1 in the kitchen is another chair. {id s2, slot 5} on the
      capacity-2 s2 neither counts nor resolves: a slot today's capacity
      does not have is a vanished marker. Both leave s1/s2 free for
      others: assign(prefer="s1") succeeds for Bob while Ann "holds"
      the kitchen's s1.
  [5] The avatar route (_play_set_activity_sync with Eve as the active
      avatar, nobody seated on s1): place_id s1 + pose "sleeping" → 400
      (a bed pose on a seat); place_id "nope" → 404; pose "flying" → 400
      (unknown key); place_id s2 + "sitting" → 409 (Dan/0 and Cid/1 hold
      both slots) and Eve stays unseated with no pose — the taken chair
      is refused BEFORE the pose is set; place_id s1 + "sitting" → ok,
      place {s1, 0, lounge}, Eve at (−3, −3); {"activity": "reading"}
      keeps s1 (same group). Dan and Cid released → s2 has two free
      slots: Eve (on s1, pose "reading") clicks s2 with the SAME pose →
      profile s2 slot 0, Eve at (0.7, −3), and an SSE is published although
      the pose text did not change (the seat did). Eve now 0.6 m from
      s2/1 and 3.7 m from s1 clicks s1 with "sitting" → the setter alone
      would keep s2 (own place, same group); the click insists, so BOTH
      the profile and the SSE carry s1 — one event, never a wrong seat
      first. {"activity": ""} clears: pose_key "" and place None.
  [5b] Guard: with places.assign raising RuntimeError,
      set_pose_intent("Eve", "sitting") still stores the pose and still
      publishes activity_changed with place None — a seat failure degrades
      exactly like the no-marker case, never into a lost pose.
  [6] room_offer for Fay (standing, unseated) while Ann sits on s1, Bob and
      Cid on s2, nobody on b1 — hand-built line by line (plan § 5):
        Places here:
        - Seat (occupied by Ann)
        - Seat (occupied by Bob, Cid)
        - Bed (free): sleeping
        Anywhere here: standing
        Also typical here: reading nooks
      (s1 and s2 are both room markers labelled "Seat" but different places →
      two lines; the pair pose "cuddling" needs 2 free seat slots → absent;
      "reading" is a seat pose → absent because no seat is free; the lounge's
      activity_hint "reading nooks" closes the block.)
      room_offer_short == "seat 0 free, bed 1 free".
      location_occupancy(house) — one roster pass — is exactly
      {"lounge": {s1: [Ann/0], s2: [Bob/0, Cid/1]}} (Dan, Eve, Fay hold
      nothing; b1 is nobody's), and room_offer_short fed that room's map
      (occ=) gives the same string as the self-reading call.
      place_label("Ann") == "Seat"; place_label("Fay") == "".
  [6b] The pair gate of _group_lines counts free slots PER PLACE, never the
      row's sum: two prop-sourced "Chair" seats of capacity 1 collapse to
      ONE row "2× Chair" (same label + group) with 2 free slots in total but
      at most 1 on any one chair → "- 2× Chair (free): sitting, reading" —
      the pair pose "cuddling" (places 2) is absent. One prop "Sofa" of
      capacity 2 → "- Sofa (free): sitting, cuddling (with partner), reading"
      (poses_in_group: the group default first, the rest alphabetical).
      room_places is stubbed for a room "den" nobody is in, so the
      occupancy is empty and the lines are pure inventory.
      The setup restores the full layout (stage 3 dropped b1) and sets the
      room hint straight in the world data — there is no setter,
      activity_hint is a column of the rooms table.
  [7] A PAIR on one place (Task 9). The layout gains
      s3  group seat, at (5, 4), capacity 3, spacing 0.6, facing 0
          → centre (1, 0), slots (0.4, 0), (1, 0), (1.6, 0).
      Everybody cleared and standing at (−3.5, −3.5).
      assign_pair("Ann", "Bob", "cuddling") (places 2): s1 (capacity 1)
      cannot take two; s2 (2 free, centre = mean of its slots = (1, −3))
      is √(4.5² + 0.5²) = 4.53 m from the pair's midpoint, s3 (3 free,
      centre (1, 0)) √(4.5² + 3.5²) = 5.70 m → s2. yaw = facing − 90° +
      yaw_offset = −90° = −π/2 (clip +X along the facing: compass f gives
      the world direction (sin f, cos f), mapped by atan2(−cos f, sin f)).
      Both profiles hold {s2, "pair", lounge}; assign_pair moves nobody
      (the interaction engine places the figures from the anchor), so
      both still stand at (−3.5, −3.5). The setter then writes the pose:
      set_pose_intent(…, "cuddling") runs assign, which KEEPS a pair seat
      (same id, slot "pair", the pose is that pair pose) — place and
      position unchanged. occupancy s2 == [Ann/pair, Bob/pair];
      free_slots(s2) == [] and _taken_count(s2) == 2 — the pair is counted
      ONCE, not per partner. room_offer_short == "seat 4 free, bed 1 free"
      (s1 1 + s3 3). place_of(Ann) = s2 slot "pair" at the place's CENTRE
      (1, −3) — the pair's anchor. release_pair clears both; s2 is no
      occupancy.
      Catalog variant (written for this stage, restored after): "lapsitting"
      (seat, solo false, places 1, yaw_offset 90) and "dancing" (stand,
      solo false, places 2). Cid takes s1 (prefer). assign_pair(Ann, Bob,
      "lapsitting") needs ONE slot: s2 4.53 m beats s3 5.70 m → s2,
      yaw = 0 − 90 + 90 = 0.0; after both setters free_slots(s2) == [1]
      and _taken_count == 1. Dan takes s3/0 (prefer). Eve at (1.3, −2.5)
      — 0.5 m from s2/1 (1.3, −3), √(0.3² + 2.5²) = 2.52 m from s3/1
      (1, 0) — says "sitting": the free-place sort counts SLOTS, not
      entries: s2 has 1 slot taken (2 entries), s3 1 slot taken (1 entry)
      → tie → nearest → s2/1, Eve at (1.3, −3). (Counting entries would
      have sent her to s3.) assign_pair(Eve, Fay, "dancing"): no stand
      marker → None, nothing written (a standing pair meets halfway).
      Base catalog back: everybody released, Cid on s1, Dan on s2/0.
      assign_pair(Ann, Bob, "cuddling"): s2 has 1 free < 2, s3 3 free →
      (s3, −π/2); after the setters free_slots(s3) == [2] (2 slots taken
      of 3, not 3 — one pair) and _taken_count == 2. assign_pair(Eve, Fay,
      "cuddling") — s1 taken, s2 and s3 with one free each — raises
      PlaceUnavailable("no free seat for two"), Eve and Fay hold nothing.
      ONE PAIR PER PLACE (review fix): the room is reduced to a single
      s4  group seat, at (5, 1), capacity 4, spacing 0.6, facing 0
          → centre (1, −3), slots (i − 1.5)·0.6 across: (0.1, −3),
          (0.7, −3), (1.3, −3), (1.9, −3).
      Everybody cleared. Ann+Bob "cuddling" → s4; after the setters the
      pair holds slots 0+1: free_slots == [2, 3], _taken_count 2. The
      offer for Fay reads "- Seat (2 of 4 free, Ann, Bob here): sitting,
      reading" — two slots free but NO "cuddling (with partner)": a place
      holding a pair takes no second one, whatever is left; room_offer_short
      "seat 2 free". assign_pair("Cid", "Dan", "cuddling") raises
      PlaceUnavailable although 2 slots are free; Cid and Dan hold nothing.
      Eve "sitting" takes the first free slot, s4/2 at (1.3, −3): free
      [3], _taken_count 3. Ann/Bob's pair ends (release_pair + poses
      cleared), Eve released: Cid+Dan get s4 → (s4, −π/2).
      Solo first: all cleared, Eve on s4/0 (prefer, (0.1, −3)); Ann+Bob
      "cuddling" fit (3 free ≥ 2) and hold the first two slots Eve does
      NOT: held {0, 1, 2} → free_slots == [3], _taken_count 3; place_of(Ann)
      still says the centre (1, −3).
  [8] The click-UI route (Task 13): _play_places_sync, the avatar's (Eve's)
      room read the way the 3D client reads it. Full layout back (s1, s2,
      b1), everybody cleared and standing at (−3.5, −3.5); Ann takes s2/0
      (prefer), Eve takes s1 (prefer). room_id "lounge", three places in
      marker order s1, s2, b1:
        s1  label "Seat", group seat, capacity 1, free 1, free_slots [0]
            — Eve holds it, but the avatar is EXCLUDED from the occupancy
            (its own seat is clickable with another pose of the group),
            poses [sitting, reading]: the group default first, then
            alphabetical — and NO "cuddling": a pair pose is nothing one
            sits down into alone, the menu lists solo poses only.
        s2  "Seat", seat, capacity 2, free 1, free_slots [1] (Ann on 0).
        b1  "Bed", bed, capacity 1, free 1, free_slots [0], poses [sleeping].
      Every pose is {key, label} with label == key (the catalog has no
      display label of its own). Eve with an empty current_room →
      {"room_id": "", "places": []} (restored afterwards).

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
    clear_pose_intent, get_character_pos, get_character_profile,
    save_character_current_location, save_character_current_room,
    save_character_profile, set_character_pos, set_pose_intent)
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

# ── [4] the setter, the SSE and the worldmap row ────────────────────────
print("\n[4] the setter, the SSE and the worldmap row")
from app.core import state_events  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402

EVENTS = []
_orig_publish = state_events.publish
state_events.publish = lambda event_type, character, **fields: EVENTS.append(
    {"type": event_type, "character": character, **fields})


def last_event(character: str):
    return next((e for e in reversed(EVENTS)
                 if e["type"] == "activity_changed" and e["character"] == character), None)


clear_pose_intent("Ann")
check("clear_pose_intent releases a place held without a pose",
      (get_character_profile("Ann") or {}).get("place") is None
      and "s1" not in places.occupancy(HOUSE, "lounge"))
set_pose_intent("Eve", "sitting")
check("setter assigns", (get_character_profile("Eve").get("place") or {}).get("id") == "s1",
      str(get_character_profile("Eve").get("place")))
check("setter stores the pose key", get_character_profile("Eve").get("pose_key") == "sitting")
check("Eve sits on (−3, −3)", get_character_pos("Eve") == {"x": -3.0, "z": -3.0},
      str(get_character_pos("Eve")))
ev = last_event("Eve")
check("SSE activity_changed carries the place",
      ev is not None and ev.get("activity") == "sitting" and ev.get("place") == field("s1", 0),
      str(ev))
n_events = len(EVENTS)
set_pose_intent("Eve", "sitting")
check("an identical repeat publishes nothing and keeps s1",
      len(EVENTS) == n_events and get_character_profile("Eve").get("place") == field("s1", 0))
wm = build_worldmap_payload(show_all=True)
row = next(c for c in wm["characters"] if c["name"] == "Eve")
check("payload place", row.get("place") == {"id": "s1", "slot": 0, "x": -3.0, "z": -3.0,
                                            "facing": 0.0, "room_id": "lounge"},
      str(row.get("place")))
check("an unseated row carries place null",
      next(c for c in wm["characters"] if c["name"] == "Ann").get("place") is None)
fog = build_worldmap_payload("Ann", show_all=False)
check("a fogged (thinned) row carries place null",
      next((c.get("place") for c in fog["characters"] if c["name"] == "Eve"), None) is None)
set_pose_intent("Eve", "standing")
check("group without marker releases", get_character_profile("Eve").get("place") is None)
check("… and the SSE says place None", (last_event("Eve") or {}).get("place", "missing") is None
      and (last_event("Eve") or {}).get("activity") == "standing", str(last_event("Eve")))
set_pose_intent("Eve", "sitting")
clear_pose_intent("Eve")
check("clear releases", get_character_profile("Eve").get("place") is None
      and get_character_profile("Eve").get("pose_key") == "")
check("… with an SSE of activity '' and place None",
      (last_event("Eve") or {}).get("activity") == "" and (last_event("Eve") or {}).get("place", "missing") is None)
check("s1 is free again", "s1" not in places.occupancy(HOUSE, "lounge"))

# ── [4b] hardening: room id and capacity are part of the match ──────────
print("\n[4b] hardening: room id and capacity are part of the match")
_prof = get_character_profile("Ann")
_prof["place"] = {"id": "s1", "slot": 0, "room_id": "kitchen"}
save_character_profile("Ann", _prof)
check("s1 of another room is no occupancy of the lounge's s1",
      "s1" not in places.occupancy(HOUSE, "lounge"), str(places.occupancy(HOUSE, "lounge")))
check("… and does not resolve", places.place_of("Ann") is None)
check("… so Bob may take s1 by preference", places.assign("Bob", "sitting", prefer="s1") == field("s1", 0))
places.release("Bob")
_prof = get_character_profile("Ann")
_prof["place"] = {"id": "s2", "slot": 5, "room_id": "lounge"}
save_character_profile("Ann", _prof)
check("a slot beyond today's capacity is no occupancy",
      sorted(places.occupancy(HOUSE, "lounge").get("s2") or []) == [("Cid", 1), ("Dan", 0)],
      str(places.occupancy(HOUSE, "lounge")))
check("… and does not resolve", places.place_of("Ann") is None)
places.release("Ann")

# ── [5] the avatar route ────────────────────────────────────────────────
print("\n[5] the avatar route")
from fastapi import HTTPException  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.routes import play as play_route  # noqa: E402

set_active_character("Eve")


def route(body: dict):
    try:
        return play_route._play_set_activity_sync(body)
    except HTTPException as e:
        return e.status_code


check("bed pose on a seat → 400", route({"place_id": "s1", "pose": "sleeping"}) == 400)
check("unknown place → 404", route({"place_id": "nope", "pose": "sitting"}) == 404)
check("unknown pose → 400", route({"place_id": "s1", "pose": "flying"}) == 400)
check("taken place → 409", route({"place_id": "s2", "pose": "sitting"}) == 409)
check("… and Eve stays unseated without a pose",
      get_character_profile("Eve").get("place") is None
      and get_character_profile("Eve").get("pose_key") == "")
r = route({"place_id": "s1", "pose": "sitting"})
check("clicked s1 → ok with the place", isinstance(r, dict) and r.get("ok") is True
      and r.get("activity") == "sitting" and r.get("place") == field("s1", 0), str(r))
check("Eve sits on (−3, −3)", get_character_pos("Eve") == {"x": -3.0, "z": -3.0})
r = route({"activity": "reading"})
check("free text of the same group keeps s1", isinstance(r, dict) and r.get("place") == field("s1", 0)
      and get_character_profile("Eve").get("pose_key") == "reading", str(r))
places.release("Dan")
places.release("Cid")
n_events = len(EVENTS)
r = route({"place_id": "s2", "pose": "reading"})
check("same pose, other seat: profile carries the clicked s2",
      isinstance(r, dict) and r.get("place") == field("s2", 0)
      and get_character_profile("Eve").get("place") == field("s2", 0), str(r))
check("… Eve moved to (0.7, −3)", get_character_pos("Eve") == {"x": 0.7, "z": -3.0},
      str(get_character_pos("Eve")))
check("… and ONE SSE announces the seat change",
      len(EVENTS) == n_events + 1 and (last_event("Eve") or {}).get("place") == field("s2", 0)
      and (last_event("Eve") or {}).get("activity") == "reading", str(last_event("Eve")))
n_events = len(EVENTS)
r = route({"place_id": "s1", "pose": "sitting"})
check("farther clicked s1 beats the own s2: profile s1",
      isinstance(r, dict) and r.get("place") == field("s1", 0)
      and get_character_pos("Eve") == {"x": -3.0, "z": -3.0}, str(r))
check("… and the ONE SSE carries s1, never s2 first",
      len(EVENTS) == n_events + 1 and (last_event("Eve") or {}).get("place") == field("s1", 0)
      and (last_event("Eve") or {}).get("activity") == "sitting", str(last_event("Eve")))
r = route({"activity": ""})
check("empty activity clears pose and place", isinstance(r, dict) and r.get("place") is None
      and r.get("activity") == "" and get_character_profile("Eve").get("pose_key") == ""
      and get_character_profile("Eve").get("place") is None, str(r))

# ── [5b] a failing seat never loses the pose ────────────────────────────
print("\n[5b] a failing seat never loses the pose")
_orig_assign = places.assign


def _boom(*a, **k):
    raise RuntimeError("layout broke")


places.assign = _boom
n_events = len(EVENTS)
set_pose_intent("Eve", "sitting")
places.assign = _orig_assign
check("the pose is stored although assign raised",
      get_character_profile("Eve").get("pose_key") == "sitting")
check("… without a place", get_character_profile("Eve").get("place") is None)
check("… and the SSE was published with place None",
      len(EVENTS) == n_events + 1 and (last_event("Eve") or {}).get("activity") == "sitting"
      and (last_event("Eve") or {}).get("place", "missing") is None, str(last_event("Eve")))
clear_pose_intent("Eve")
state_events.publish = _orig_publish

# ── [6] the offer the LLM reads ─────────────────────────────────────────
print("\n[6] the offer the LLM reads")
write_layout(MARKERS)                      # b1 is back
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == HOUSE:
        _loc["rooms"][0]["activity_hint"] = "reading nooks"
_save_world_data(_data)
places.invalidate()
for _n in ("Ann", "Bob", "Cid", "Dan", "Eve"):
    clear_pose_intent(_n)                  # nobody seated, no pose
check("Ann → s1", places.assign("Ann", "sitting", prefer="s1") == field("s1", 0))
check("Bob → s2/0", places.assign("Bob", "sitting", prefer="s2") == field("s2", 0))
check("Cid → s2/1", places.assign("Cid", "sitting", prefer="s2") == field("s2", 1))
person("Fay", -3.5, -3.5)
offer = places.room_offer("Fay", HOUSE, "lounge")
EXPECTED_OFFER = "\n".join([
    "Places here:",
    "- Seat (occupied by Ann)",
    "- Seat (occupied by Bob, Cid)",
    "- Bed (free): sleeping",
    "Anywhere here: standing",
    "Also typical here: reading nooks",
])
for _i, (_want, _got) in enumerate(zip(EXPECTED_OFFER.split("\n"),
                                       offer.split("\n") + [""] * 6)):
    check(f"offer line {_i + 1}: {_want}", _got == _want, repr(_got))
check("offer has exactly six lines", offer == EXPECTED_OFFER, repr(offer))
short = places.room_offer_short(HOUSE, "lounge")
check("room_offer_short", short == "seat 0 free, bed 1 free", repr(short))
loc_occ = places.location_occupancy(HOUSE)
check("location_occupancy: one map for the whole house",
      loc_occ == {"lounge": {"s1": [("Ann", 0)], "s2": [("Bob", 0), ("Cid", 1)]}}, str(loc_occ))
check("room_offer_short with a precomputed map gives the same string",
      places.room_offer_short(HOUSE, "lounge", occ=loc_occ["lounge"]) == short)
check("place_label(Ann) == 'Seat'", places.place_label("Ann") == "Seat",
      repr(places.place_label("Ann")))
check("place_label(Fay) == ''", places.place_label("Fay") == "",
      repr(places.place_label("Fay")))

# ── [6b] the pair gate counts free slots per place ──────────────────────
print("\n[6b] the pair gate counts free slots per place")


def prop_place(pid: str, label: str, cap: int) -> dict:
    return {"id": pid, "group": "seat", "label": label, "capacity": cap,
            "slots": [[float(i), 0.0] for i in range(cap)], "facing": 0.0, "y_world": 0.0,
            "root_offset": 0.534, "source": "prop", "room_id": "den"}


_orig_room_places = places.room_places
places.room_places = lambda loc, room: (
    [prop_place("c1/s", "Chair", 1), prop_place("c2/s", "Chair", 1), prop_place("sofa/s", "Sofa", 2)]
    if room == "den" else _orig_room_places(loc, room))
try:
    den = places._group_lines(HOUSE, "den", "Fay")
finally:
    places.room_places = _orig_room_places
check("two rows (the two chairs collapsed, the sofa apart)", len(den) == 2, str(den))
check("2× Chair: 2 free in total, 1 per chair → no pair pose",
      den[0] == "- 2× Chair (free): sitting, reading", repr(den[0]))
check("Sofa: 2 free on one place → cuddling (with partner)",
      den[1] == "- Sofa (free): sitting, cuddling (with partner), reading", repr(den[1]))

# ── [7] a pair on one place ─────────────────────────────────────────────
print("\n[7] a pair on one place")
import math  # noqa: E402

S3 = {"id": "s3", "group": "seat", "at": [5, 4], "capacity": 3, "spacing_m": 0.6, "rotation": 0}
write_layout(MARKERS + [S3])
places.invalidate()
for _n in ("Ann", "Bob", "Cid", "Dan", "Eve", "Fay"):
    clear_pose_intent(_n)
    set_character_pos(_n, -3.5, -3.5)
pl = {p["id"]: p for p in places.room_places(HOUSE, "lounge")}
check("s3 slots (0.4, 0), (1, 0), (1.6, 0)",
      pl.get("s3", {}).get("slots") == [[0.4, 0.0], [1.0, 0.0], [1.6, 0.0]], str(pl.get("s3")))
PAIR_S2 = {"id": "s2", "slot": "pair", "room_id": "lounge"}


def near(a, b, eps=1e-4) -> bool:
    return abs(float(a) - float(b)) <= eps


r = places.assign_pair("Ann", "Bob", "cuddling")
check("assign_pair → (s2, −π/2): nearest place with 2 free slots",
      r is not None and r[0]["id"] == "s2" and near(r[1], -math.pi / 2), str(r))
check("both profiles hold s2/pair",
      get_character_profile("Ann").get("place") == PAIR_S2
      and get_character_profile("Bob").get("place") == PAIR_S2)
check("assign_pair moves nobody", get_character_pos("Ann") == {"x": -3.5, "z": -3.5}
      and get_character_pos("Bob") == {"x": -3.5, "z": -3.5})
set_pose_intent("Ann", "cuddling")
set_pose_intent("Bob", "cuddling")
check("the setter keeps the pair seat (assign's keep branch)",
      get_character_profile("Ann").get("place") == PAIR_S2
      and get_character_profile("Bob").get("place") == PAIR_S2
      and get_character_pos("Ann") == {"x": -3.5, "z": -3.5},
      str(get_character_profile("Ann").get("place")))
occ = places.occupancy(HOUSE, "lounge")
check("occupancy s2 [Ann/pair, Bob/pair]",
      sorted(occ.get("s2") or []) == [("Ann", "pair"), ("Bob", "pair")], str(occ))
check("a pair of two takes both slots — counted once, not per partner",
      places.free_slots(pl["s2"], occ["s2"]) == [] and places._taken_count(pl["s2"], occ["s2"]) == 2)
short = places.room_offer_short(HOUSE, "lounge")
check("room_offer_short: seat 4 free, bed 1 free", short == "seat 4 free, bed 1 free", repr(short))
po = places.place_of("Ann")
check("place_of(Ann) = s2 slot pair at the centre (1, −3)",
      po is not None and po["id"] == "s2" and po["slot"] == "pair" and po["x"] == 1.0 and po["z"] == -3.0,
      str(po))
places.release_pair("Ann", "Bob")
check("release_pair clears both",
      get_character_profile("Ann").get("place") is None and get_character_profile("Bob").get("place") is None
      and "s2" not in places.occupancy(HOUSE, "lounge"))

BASE_CATALOG = json.loads((CAT / "pose_catalog.json").read_text())
_variant = json.loads(json.dumps(BASE_CATALOG))
_variant["entries"]["lapsitting"] = {"prompt": "p", "animation": "cuddle", "group": "seat",
                                     "solo": False, "places": 1, "yaw_offset": 90}
_variant["entries"]["dancing"] = {"prompt": "p", "animation": "dance", "group": "stand",
                                  "solo": False, "places": 2, "yaw_offset": 0}
(CAT / "pose_catalog.json").write_text(json.dumps(_variant), encoding="utf-8")
pose_catalog.reload_catalogs()
places.invalidate()
check("Cid → s1", places.assign("Cid", "sitting", prefer="s1") == field("s1", 0))
r = places.assign_pair("Ann", "Bob", "lapsitting")
check("a places-1 pair → (s2, 0.0): facing 0 − 90 + yaw_offset 90",
      r is not None and r[0]["id"] == "s2" and near(r[1], 0.0), str(r))
set_pose_intent("Ann", "lapsitting")
set_pose_intent("Bob", "lapsitting")
occ = places.occupancy(HOUSE, "lounge")
check("it takes ONE slot: free_slots(s2) == [1], _taken_count 1",
      places.free_slots(pl["s2"], occ["s2"]) == [1] and places._taken_count(pl["s2"], occ["s2"]) == 1,
      str(occ.get("s2")))
check("Dan → s3/0", places.assign("Dan", "sitting", prefer="s3") == field("s3", 0))
set_character_pos("Eve", 1.3, -2.5)
check("the free-place sort counts slots, not entries: Eve → s2/1",
      places.assign("Eve", "sitting") == field("s2", 1)
      and get_character_pos("Eve") == {"x": 1.3, "z": -3.0}, str(get_character_profile("Eve").get("place")))
check("a standing pair without a stand marker → None, nothing written",
      places.assign_pair("Eve", "Fay", "dancing") is None
      and get_character_profile("Eve").get("place") == field("s2", 1)
      and get_character_profile("Fay").get("place") is None)

(CAT / "pose_catalog.json").write_text(json.dumps(BASE_CATALOG), encoding="utf-8")
pose_catalog.reload_catalogs()
places.invalidate()
for _n in ("Ann", "Bob", "Dan", "Eve"):
    clear_pose_intent(_n)
check("Dan → s2/0", places.assign("Dan", "sitting", prefer="s2") == field("s2", 0))
r = places.assign_pair("Ann", "Bob", "cuddling")
check("s2 has one free slot: the pair goes to s3 (−π/2)",
      r is not None and r[0]["id"] == "s3" and near(r[1], -math.pi / 2), str(r))
set_pose_intent("Ann", "cuddling")
set_pose_intent("Bob", "cuddling")
occ = places.occupancy(HOUSE, "lounge")
check("on a capacity-3 place the pair takes 2: free_slots(s3) == [2]",
      places.free_slots(pl["s3"], occ["s3"]) == [2] and places._taken_count(pl["s3"], occ["s3"]) == 2,
      str(occ.get("s3")))
try:
    places.assign_pair("Eve", "Fay", "cuddling")
    check("no place with two free seats raises PlaceUnavailable", False, "no exception")
except places.PlaceUnavailable as e:
    check("no place with two free seats raises PlaceUnavailable", str(e) == "no free seat for two", str(e))
check("Eve and Fay hold nothing", get_character_profile("Eve").get("place") is None
      and get_character_profile("Fay").get("place") is None)

# one pair per place: a second pair is refused however many slots are left
S4 = {"id": "s4", "group": "seat", "at": [5, 1], "capacity": 4, "spacing_m": 0.6, "rotation": 0}
write_layout([S4])
places.invalidate()
for _n in ("Ann", "Bob", "Cid", "Dan", "Eve", "Fay"):
    clear_pose_intent(_n)
    set_character_pos(_n, -3.5, -3.5)
s4 = next(p for p in places.room_places(HOUSE, "lounge") if p["id"] == "s4")
check("s4 slots (0.1, −3) … (1.9, −3)",
      s4["slots"] == [[0.1, -3.0], [0.7, -3.0], [1.3, -3.0], [1.9, -3.0]], str(s4["slots"]))
r = places.assign_pair("Ann", "Bob", "cuddling")
check("Ann+Bob → s4", r is not None and r[0]["id"] == "s4", str(r))
set_pose_intent("Ann", "cuddling")
set_pose_intent("Bob", "cuddling")
occ = places.occupancy(HOUSE, "lounge")
check("one pair on a capacity-4 place: free_slots [2, 3], _taken_count 2",
      places.free_slots(s4, occ["s4"]) == [2, 3] and places._taken_count(s4, occ["s4"]) == 2,
      str(occ.get("s4")))
offer = places.room_offer("Fay", HOUSE, "lounge")
check("the offer shows 2 of 4 free but no pair pose on the pair's place",
      "- Seat (2 of 4 free, Ann, Bob here): sitting, reading" in offer.split("\n"), repr(offer))
check("room_offer_short: seat 2 free", places.room_offer_short(HOUSE, "lounge") == "seat 2 free")
try:
    places.assign_pair("Cid", "Dan", "cuddling")
    check("a second pair on the same place is refused", False, "no exception")
except places.PlaceUnavailable as e:
    check("a second pair on the same place is refused", str(e) == "no free seat for two", str(e))
check("Cid and Dan hold nothing", get_character_profile("Cid").get("place") is None
      and get_character_profile("Dan").get("place") is None)
check("Eve → s4/2, the first free slot, at (1.3, −3)",
      places.assign("Eve", "sitting") == field("s4", 2) and get_character_pos("Eve") == {"x": 1.3, "z": -3.0})
occ = places.occupancy(HOUSE, "lounge")
check("free [3], _taken_count 3", places.free_slots(s4, occ["s4"]) == [3]
      and places._taken_count(s4, occ["s4"]) == 3)
places.release_pair("Ann", "Bob")
clear_pose_intent("Ann")
clear_pose_intent("Bob")
places.release("Eve")
r = places.assign_pair("Cid", "Dan", "cuddling")
check("after the first pair ends, Cid+Dan get s4 (−π/2)",
      r is not None and r[0]["id"] == "s4" and near(r[1], -math.pi / 2), str(r))
# solo first: the pair holds the first slots the solo sitter does NOT
places.release_pair("Cid", "Dan")
check("Eve → s4/0 (prefer)", places.assign("Eve", "sitting", prefer="s4") == field("s4", 0)
      and get_character_pos("Eve") == {"x": 0.1, "z": -3.0})
r = places.assign_pair("Ann", "Bob", "cuddling")
set_pose_intent("Ann", "cuddling")
set_pose_intent("Bob", "cuddling")
occ = places.occupancy(HOUSE, "lounge")
check("pair beside a solo on slot 0: held {0, 1, 2} → free [3], _taken_count 3",
      r is not None and r[0]["id"] == "s4" and places.free_slots(s4, occ["s4"]) == [3]
      and places._taken_count(s4, occ["s4"]) == 3, str(occ.get("s4")))
po = places.place_of("Ann")
check("place_of(Ann) says the centre (1, −3)", po is not None and po["x"] == 1.0 and po["z"] == -3.0, str(po))

# ── [8] the click-UI route: the avatar's room as the 3D client reads it ──
print("\n[8] the click-UI route")
write_layout(MARKERS)
places.invalidate()
for _n in ("Ann", "Bob", "Cid", "Dan", "Eve", "Fay"):
    clear_pose_intent(_n)
    set_character_pos(_n, -3.5, -3.5)
check("Ann → s2/0", places.assign("Ann", "sitting", prefer="s2") == field("s2", 0))
check("Eve → s1", places.assign("Eve", "sitting", prefer="s1") == field("s1", 0))
r = play_route._play_places_sync()
check("room_id lounge", r.get("room_id") == "lounge", str(r.get("room_id")))
check("three places in marker order s1, s2, b1",
      [p["id"] for p in r.get("places", [])] == ["s1", "s2", "b1"], str([p["id"] for p in r.get("places", [])]))
by_id = {p["id"]: p for p in r.get("places", [])}
check("s1: Seat, seat, capacity 1, free 1 (the avatar's own seat counts free), free_slots [0]",
      by_id.get("s1") == {"id": "s1", "label": "Seat", "group": "seat", "capacity": 1, "free": 1,
                          "free_slots": [0],
                          "poses": [{"key": "sitting", "label": "sitting"},
                                    {"key": "reading", "label": "reading"}]}, str(by_id.get("s1")))
check("s2: free 1, free_slots [1] — Ann on 0",
      by_id.get("s2", {}).get("free") == 1 and by_id.get("s2", {}).get("free_slots") == [1]
      and by_id.get("s2", {}).get("capacity") == 2, str(by_id.get("s2")))
check("b1: Bed, bed, free 1, poses [sleeping]",
      by_id.get("b1") == {"id": "b1", "label": "Bed", "group": "bed", "capacity": 1, "free": 1,
                          "free_slots": [0], "poses": [{"key": "sleeping", "label": "sleeping"}]},
      str(by_id.get("b1")))
save_character_current_room("Eve", "")
r = play_route._play_places_sync()
check("no room → empty answer", r == {"room_id": "", "places": []}, str(r))
save_character_current_room("Eve", "lounge")

# ── summary ─────────────────────────────────────────────────────────────
print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
