#!/usr/bin/env python3
"""Smoke run for the PLACE TYPES (plan-platztypen.md E1).

Throwaway storage, private pose catalog, no server, no clips needed.

A place type used to name a piece of FURNITURE; since this rebuild it names a
BODY SHAPE::

    old:  seat(0.314)  bed(0.631)  floor(0.051)  counter(0)  stand(0)
    new:  seat(0.314, needs_place)  lie(0.051, needs_place)  ground(0)  stand(0)

Two bugs are the reason, and both are pinned below as numbers.

**Bug 1 — the couch.** "Kira lies on the couch" put Kira on the FLOOR. The
pose `lying` belonged to the group `floor`, `places.assign` looks for a free
place OF THE POSE'S GROUP, and the couch's marker said `bed`. No match, no
place, a lying figure at ground level next to the sofa. `bed` and `floor` were
never two body shapes — one lies on a mattress, on a couch and on the ground,
and the marker is what says which. They are ONE group now, and § 3 below runs
exactly that scene: a stored `bed` marker, migrated, taking a `lying` pose.

**Bug 2 — the mattress.** `bed.root_drop = 0.631` was calibrated on 2026-08-27
for the Mixamo clip `sleep`, which was deleted three days later (c2eb166d).
Everything lying plays `laying.fbx` today. The chain that puts a figure on a
marked surface (scripts/smoke_prop_marker_place.mjs § E5,
packages/scene-render/src/figure.ts) is::

    posed hips = S − rootOffset − clipHipsDrop + hipsBindY

with, at the figure height H = 1.70 m, `hipsBindY` = 0.98013 (the reference
figure's hips in its anchored bind pose) and `clipHipsDrop(laying)` = 0.84033
(0.98013 × (1 − 15.81 / 110.86), the documented median of the served clip).
Hand-derived for both drops:

    lie    0.051 × 1.70 = 0.0867  ->  S − 0.0867 − 0.84033 + 0.98013 = S + 0.0531
    bed    0.631 × 1.70 = 1.0727  ->  S − 1.0727 − 0.84033 + 0.98013 = S − 0.9330

    difference = 1.0727 − 0.0867 = 0.9860 m

**Every sleeper in the field stood 0.93 m below the mattress**, and the merge
is what lifts them out. § 4 checks the new number and keeps the old one beside
it as the red probe.

    Caveat, deliberately not hidden: `clipHipsDrop(laying)` = 0.84033 is the
    value recorded in the .mjs check for the clip library as it was imported
    then. The CMU library was re-imported since (a605c5a7 / 7f8b113f) and the
    same measurement now yields 0.7989, i.e. S + 0.0945 — the .mjs E5 stage
    reports that as a failure of its own. What § 4 pins is the term this
    rebuild owns, the ROOT DROP, and the 0.986 m between the two drops is
    independent of any clip: whatever the clip measures, the old group put the
    figure 0.986 m lower than the new one.

**`counter` is gone** without an heir. Its only entry, `working` ("sitting at
desk, hands on keyboard", clip `sit`), is a sitting pose and moved to `seat`;
what the group pretended to be — "standing at a device, facing it" — is what a
marker's position and yaw already say.

**`needs_place`** is the new group property that keeps `ground` from being a
regression. False means "poses of this group need no marker": they are offered
under "Anywhere here", `assign` gives nothing, the place is never named, and a
pair of them meets halfway instead of raising. Four rules used to hang on the
literal group name `"stand"` and hang on this flag now
(`places._named_place`, `places.assign_pair`, `routes/play.py._state_block`,
`interaction_engine`'s distance rule).

Hand-derived expectations
=========================

  [1] The pure rename. RENAMES maps exactly bed -> lie, floor -> lie,
      counter -> stand; `seat` and `stand` are ABSENT, so a lookup miss means
      "nothing to do". `rename_place_groups` rewrites in place and returns the
      number of markers it touched: over a list of five markers
      (bed, FLOOR, Counter, seat, stand) it returns 3 — the lookup lowercases,
      so a stored "FLOOR" is caught, and the value written is always the
      lower-case new name. Fields other than `group` are untouched, a non-dict
      entry is skipped without raising, and None/[] return 0.

  [2] The boot migration, all four marker homes:
        room layout   "lounge"   bed, floor, counter, seat, stand  -> 3 renamed
        ground layout "__ground__"  floor                          -> 1 renamed
        prop sidecar  variant 0  bed, seat                         -> 1 renamed
                      variant 1  counter                           -> 1 renamed
                      record-level (legacy) floor                  -> 1 renamed
      => {"room_markers": 4, "prop_markers": 3}. `at`, `id` and `capacity`
      survive verbatim. The second run returns None (world_kv flag
      `migration.place_groups_v1`), and nothing in the world changes.

  [3] Bug 1, the couch. A room holds ONE marker, group `bed` (a couch), and
      Kira's pose is `lying`. Before the migration `assign` finds nothing:
      `lying` is a `lie` pose in today's catalog and no `lie` place exists.
      After the migration the marker IS a `lie` place and Kira gets it —
      `{"id": "couch", "slot": 0, "room_id": "lounge"}` — and stands on the
      marker's world point. `sleeping`, the other pose of the merged group,
      takes the same marker. A `seat` marker does NOT: a sitting pose and a
      lying pose are still two different body shapes.

  [4] Bug 2, the height (chain above). With the catalog's own `lie.root_drop`
      the hips of a `sleeping` figure land at S + 0.0531 for the bench surface
      S = 0.587 of smoke_prop_marker_surface.py: 0.6401. With the retired
      `bed` drop they landed at S − 0.9330 = −0.3460, i.e. 0.35 m below the
      floor the bed stands on. The difference is 0.9860 m and does not depend
      on the clip.

  [5] `needs_place`. `kneeling` is a `ground` pose: `assign` returns None and
      writes no place even though the room has markers, `_named_place` is None
      and `place_phrase` is "" — a place nobody needs is not worth naming. The
      pose is nevertheless OFFERED: `room_offer` walks the placeless groups in
      catalog order and each group's default first, so with this fixture the
      line reads "Anywhere here: standing, chatting (with partner), kneeling"
      — `stand` first (its default `standing`, then its other entry
      `chatting`, marked because it is a pair pose), then `ground` with
      `kneeling`. Placed groups keep their own rows above it. A `stand`
      marker that IS held is still not named: the rule reads the flag, not the group name. And a
      placeless PAIR gets None from `assign_pair` instead of
      `PlaceUnavailable` — a standing pair meets halfway.

  [6] Falling asleep. `get_effective_pose_key` answers `sleeping` the moment
      `is_sleeping` is set, and `sleeping` is a `lie` pose — a sitter who nods
      off used to keep his `seat` place and get the lying figure's root drop on
      it, i.e. sink into the upholstery. `set_is_sleeping(name, True)` hands
      the place out again: Ann on the seat, asleep -> the `lie` marker. With
      the `lie` marker taken by someone else, the same transition RELEASES her
      seat (place None) rather than keeping it. Waking up assigns nothing.

  [7] The import path. A content pack authored before this rebuild carries
      retired groups, and the boot migration ran long ago.
      `content_io._sanitize_imported_location` renames a room's `bed` marker to
      `lie` and says so in one warning; `prop_field_migration
      .normalize_prop_sidecar` does the same for a prop directory the importer
      just installed (`counter` -> `stand` on the variant).

  [8] The trace an unknown place type leaves (E2). Nothing checked a marker's
      group against the catalog on the way in, and `scene_recipe` skipped an
      unknown one with a bare `continue` — so a typo or a pack from before the
      rename made markers vanish from the scene AND from the place inventory,
      and the symptom was an empty room rather than a message. Counted by
      hand, with the four-group fixture catalog above (so `bed` and `counter`
      are unknown):
        - `world_ops._sanitize_markers` over [bed, seat] returns BOTH, the
          `bed` verbatim (no fallback, no correction), and logs exactly 1
          warning naming `m1` and `'bed'`;
        - `props.sanitize_markers` over [counter, lie]: same, 1 warning;
        - `compose_scene` over a house with 3 unusable markers of 2 groups in
          2 rooms publishes 1 place (the `seat`) and logs exactly **1** line —
          collecting rather than logging per marker, because a composition is
          the hot path (a twenty-seat tavern with one bad group would write
          twenty identical lines per poll); the line names both groups;
        - `furnish_needs.valid_needs` over [armchair with a `bed` marker, rug
          with no marker, stool with a `seat` marker] keeps all 3 needs, gives
          the armchair `marker: None`, and reports it ONCE — 1 log line and 1
          `dropped` entry, which is what the confirmation dialog shows. The
          rug, which asked for nothing, produces neither.

Usage:  ./.venv/bin/python scripts/smoke_platztypen.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="platztypen-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import places, pose_catalog  # noqa: E402
from app.core import props as prop_store  # noqa: E402
from app.core.place_group_migration import (  # noqa: E402
    _FLAG, RENAMES, migrate_place_groups_once, rename_place_groups)
from app.models.character import (  # noqa: E402
    clear_pose_intent, get_character_pos, get_character_profile,
    save_character_current_location, save_character_current_room,
    save_character_profile, set_character_pos, set_is_sleeping,
    set_pose_intent)
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    update_location_position)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────
# A private pose catalog with the FOUR place types of the rebuild. The real
# one must not be edited, and a fixture that leaves `needs_place` out inherits
# the default True — which is exactly the bug this file guards against.
CAT = Path(tempfile.mkdtemp(prefix="platztypen-cat-"))
_orig_catalog_path = pose_catalog.catalog_path
pose_catalog.catalog_path = (
    lambda axis: CAT / "pose_catalog.json" if axis == "pose" else _orig_catalog_path(axis))
(CAT / "pose_catalog.json").write_text(json.dumps({
    "groups": {
        "stand": {"label": "Standing spot", "root_drop": 0, "default": "standing",
                  "needs_place": False},
        "ground": {"label": "Ground", "root_drop": 0, "default": "kneeling",
                   "needs_place": False},
        "seat": {"label": "Seat", "root_drop": 0.314, "default": "sitting",
                 "needs_place": True},
        "lie": {"label": "Lying place", "root_drop": 0.051, "default": "lying",
                "needs_place": True},
    },
    "entries": {
        "standing": {"prompt": "p", "animation": "idle", "group": "stand",
                     "_default": True},
        "kneeling": {"prompt": "p", "animation": "kneeling", "group": "ground"},
        "sitting": {"prompt": "p", "animation": "sit", "group": "seat"},
        "lying": {"prompt": "p", "animation": "laying", "group": "lie"},
        "sleeping": {"prompt": "p", "animation": "laying", "group": "lie"},
        "chatting": {"prompt": "p", "animation": "idle", "group": "stand",
                     "solo": False, "places": 2, "yaw_offset": 0},
    }}), encoding="utf-8")
pose_catalog.reload_catalogs()

HOUSE = add_location(name="Platz House", description="place-type smoke",
                     rooms=[{"id": "lounge", "name": "Lounge"}])["id"]
update_location_position(HOUSE, 0.0, 0.0)


def write_rooms(rooms) -> None:
    """Replace the location's room list — ``rooms`` is ``[(id, name, layout)]``.
    Written straight into the ``locations.meta`` blob so a fixture may carry a
    RETIRED group; the ordinary save path sanitizes and would swallow it, and
    the point here is what the migration finds in an old world."""
    data = _load_world_data()
    for loc in data["locations"]:
        if loc["id"] != HOUSE:
            continue
        map3d = loc.setdefault("map3d", {})
        map3d["plan_width_m"] = 10.0
        map3d["boundary"] = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
        loc["rooms"] = [{"id": rid, "name": name, "layout": layout}
                        for rid, name, layout in rooms]
    _save_world_data(data)
    places.invalidate()


def room_layout(markers) -> dict:
    """The lounge rectangle of the places smoke: min corner (−4, −4), 8 × 6 m."""
    return {"x": -4, "y": -4, "w": 8, "d": 6, "markers": list(markers)}


def person(name: str, x: float, z: float) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    save_character_current_location(name, HOUSE)
    set_character_pos(name, x, z)
    save_character_current_room(name, "lounge")


# ── [1] the pure rename ─────────────────────────────────────────────────
print("\n[1] rename_place_groups — the one-way table")
check("the table is exactly bed/floor -> lie and counter -> stand",
      RENAMES == {"bed": "lie", "floor": "lie", "counter": "stand"}, str(RENAMES))
check("a group that keeps its name is NOT in the table",
      "seat" not in RENAMES and "stand" not in RENAMES and "lie" not in RENAMES)

_ms = [{"id": "m1", "group": "bed", "at": [1, 1], "capacity": 2},
       {"id": "m2", "group": "FLOOR", "at": [2, 2]},
       {"id": "m3", "group": "Counter", "at": [3, 3]},
       {"id": "m4", "group": "seat", "at": [4, 4]},
       {"id": "m5", "group": "stand", "at": [5, 5]},
       "not a marker at all"]
_n = rename_place_groups(_ms)
check("three of five markers are renamed", _n == 3, str(_n))
check("the new names are lower case, whatever was stored",
      [m["group"] for m in _ms[:5]] == ["lie", "lie", "stand", "seat", "stand"],
      str([m["group"] for m in _ms[:5]]))
check("nothing but `group` is touched",
      _ms[0] == {"id": "m1", "group": "lie", "at": [1, 1], "capacity": 2},
      str(_ms[0]))
check("a second pass over the same list changes nothing",
      rename_place_groups(_ms) == 0)
check("None and [] are 0, not a crash",
      rename_place_groups(None) == 0 and rename_place_groups([]) == 0)


# ── [2] the boot migration, all four homes ──────────────────────────────
print("\n[2] migrate_place_groups_once — four marker homes")
LOUNGE_IN = [{"id": "p1", "group": "bed", "at": [2.0, 4.0], "capacity": 2},
             {"id": "p2", "group": "floor", "at": [1.0, 1.0]},
             {"id": "p3", "group": "counter", "at": [3.0, 1.0]},
             {"id": "p4", "group": "seat", "at": [5.0, 1.0]},
             {"id": "p5", "group": "stand", "at": [6.0, 1.0]}]
GROUND_IN = {"props": [], "markers": [{"id": "g1", "group": "floor",
                                       "at": [-3.0, 4.0]}]}
write_rooms([("lounge", "Lounge", room_layout(LOUNGE_IN)),
             (GROUND_ROOM_ID, "Ground", GROUND_IN)])

PROP = "couch-smoke"
(paths.get_storage_dir() / "props" / PROP).mkdir(parents=True, exist_ok=True)
prop_store._write_sidecar(PROP, {
    "name": "Couch", "width_m": 2.0, "depth_m": 0.9, "height_m": 0.8,
    # The legacy record-level list has had no reader since the field
    # migration; it is renamed anyway so an old sidecar landing here later
    # cannot carry a dead group onto a variant.
    prop_store.MARKERS_KEY: [{"id": "old1", "group": "floor", "at": [0.5, 0.0, 0.5]}],
    prop_store.VARIANTS_KEY: [
        {prop_store.MARKERS_KEY: [{"id": "v0a", "group": "bed", "at": [0.5, -0.6, 0.5]},
                                  {"id": "v0b", "group": "seat", "at": [0.2, -0.6, 0.2]}]},
        {prop_store.MARKERS_KEY: [{"id": "v1a", "group": "counter", "at": [0.1, 0.0, 0.1]}]},
    ]})

stats = migrate_place_groups_once()
check("room markers: 3 in the lounge + 1 on the ground",
      stats == {"room_markers": 4, "prop_markers": 3}, str(stats))

_rooms = {r["id"]: r for r in _load_world_data()["locations"][0]["rooms"]}
_lounge = _rooms["lounge"]["layout"]["markers"]
check("the lounge speaks the new vocabulary",
      [m["group"] for m in _lounge] == ["lie", "lie", "stand", "seat", "stand"],
      str([m["group"] for m in _lounge]))
check("id, at and capacity are untouched",
      _lounge[0] == {"id": "p1", "group": "lie", "at": [2.0, 4.0], "capacity": 2},
      str(_lounge[0]))
check("the GROUND layout is walked too (it is a room with id __ground__)",
      _rooms[GROUND_ROOM_ID]["layout"]["markers"][0]["group"] == "lie",
      str(_rooms[GROUND_ROOM_ID]["layout"]["markers"]))

_side = prop_store.read_sidecar(PROP)
check("variant 0: bed -> lie, seat stays",
      [m["group"] for m in _side[prop_store.VARIANTS_KEY][0][prop_store.MARKERS_KEY]]
      == ["lie", "seat"])
check("variant 1: counter -> stand",
      [m["group"] for m in _side[prop_store.VARIANTS_KEY][1][prop_store.MARKERS_KEY]]
      == ["stand"])
check("the legacy record-level list is renamed as well",
      [m["group"] for m in _side[prop_store.MARKERS_KEY]] == ["lie"])

_before = json.dumps(_load_world_data(), sort_keys=True)
check("the second run is a no-op (world_kv flag)",
      migrate_place_groups_once() is None)
check("...and nothing in the world moved",
      json.dumps(_load_world_data(), sort_keys=True) == _before)


# ── [3] bug 1: the couch ────────────────────────────────────────────────
print("\n[3] the couch — a lying pose finds the marker it was written for")
# One marker, stored the way a world written before the rebuild stores a
# couch: group `bed`. The room is otherwise empty, so nothing else can answer.
write_rooms([("lounge", "Lounge",
              room_layout([{"id": "couch", "group": "bed", "at": [2.0, 4.0]}]))])
person("Kira", -3.5, -3.5)
check("before the migration a lying pose finds nothing — the symptom",
      places.assign("Kira", "lying") is None
      and get_character_profile("Kira").get("place") is None)

# Migrate this second world state: the flag is already set from § 2, so the
# pure function is what runs here — the same call content_io makes.
data = _load_world_data()
for _loc in data["locations"]:
    for _room in _loc.get("rooms") or []:
        rename_place_groups((_room.get("layout") or {}).get("markers"))
_save_world_data(data)
places.invalidate()

_pl = places.room_places(HOUSE, "lounge")
check("the couch marker is a lying place now",
      [(p["id"], p["group"]) for p in _pl] == [("couch", "lie")], str(_pl))
check("Kira lies ON THE COUCH",
      places.assign("Kira", "lying") == {"id": "couch", "slot": 0, "room_id": "lounge"},
      str(get_character_profile("Kira").get("place")))
# The couch marker sits at (2, 4) in room metres; the room's min corner is
# (−4, −4) in a 10 m plan whose centre is the location at (0, 0), so the world
# point is (−4 + 2, −4 + 4) = (−2, 0).
check("...and stands on the marker's world point (−2, 0)",
      get_character_pos("Kira") == {"x": -2.0, "z": 0.0},
      str(get_character_pos("Kira")))
places.release("Kira")
check("sleeping is the SAME group and takes the SAME marker",
      places.assign("Kira", "sleeping") == {"id": "couch", "slot": 0, "room_id": "lounge"})
places.release("Kira")
check("a sitting pose does NOT take a lying place",
      places.assign("Kira", "sitting") is None
      and get_character_profile("Kira").get("place") is None)


# ── [4] bug 2: the height ───────────────────────────────────────────────
print("\n[4] the height — a sleeper on the mattress, not in it")
from app.core.scene_recipe import FIGURE_HEIGHT_M  # noqa: E402

# The chain of scripts/smoke_prop_marker_place.mjs § E5 /
# packages/scene-render/src/figure.ts, as arithmetic:
#     posed hips = S − rootOffset − clipHipsDrop + hipsBindY
HIPS_BIND_Y = 0.98013          # the reference figure at H = 1.70 m
CLIP_HIPS_DROP_LAYING = 0.84033  # 0.98013 × (1 − 15.81 / 110.86)
SURFACE = 0.587                # the bench of smoke_prop_marker_surface.py § 5
RETIRED_BED_DROP = 0.631       # calibrated on the deleted Mixamo `sleep` clip


def posed_hips(surface: float, root_drop: float) -> float:
    return (surface - root_drop * FIGURE_HEIGHT_M
            - CLIP_HIPS_DROP_LAYING + HIPS_BIND_Y)


_lie_drop = pose_catalog.get_groups()["lie"]["root_drop"]
check("the catalog's lying drop is the served clip's 0.051",
      _lie_drop == 0.051, str(_lie_drop))
check("root offset in metres: 0.051 × 1.70 = 0.0867",
      abs(_lie_drop * FIGURE_HEIGHT_M - 0.0867) < 5e-5,
      str(round(_lie_drop * FIGURE_HEIGHT_M, 5)))
_now = posed_hips(SURFACE, _lie_drop)
check("the sleeper's hips land at S + 0.0531 = 0.6401",
      abs(_now - 0.6401) < 1e-3, str(round(_now, 5)))
# RED PROBE: the number the retired group produced. 0.587 − 1.0727 − 0.84033
# + 0.98013 = −0.3460 — a sleeping figure 0.35 m under the floor the bed
# stands on, and 0.93 m under the mattress it was marked on.
_then = posed_hips(SURFACE, RETIRED_BED_DROP)
check("the retired bed drop put it at −0.3460", abs(_then + 0.3460) < 1e-3,
      str(round(_then, 5)))
# 1.0727 − 0.0867 = 0.9860. The clip cancels out of the difference, so this
# number holds whatever the clip library currently measures.
check("the merge lifts every sleeper by 0.9860 m",
      abs((_now - _then) - 0.9860) < 1e-3, str(round(_now - _then, 5)))
check("no place type carries the retired drop any more",
      all(g["root_drop"] != RETIRED_BED_DROP
          for g in pose_catalog.get_groups().values()))


# ── [5] needs_place ─────────────────────────────────────────────────────
print("\n[5] needs_place — a body shape that wants no marker")
write_rooms([("lounge", "Lounge", room_layout([
    {"id": "couch", "group": "lie", "at": [2.0, 4.0]},
    {"id": "s1", "group": "seat", "at": [1.0, 1.0]},
    {"id": "st1", "group": "stand", "at": [6.0, 1.0]}]))])
for _n in ("Kira", "Ann", "Bob"):
    person(_n, -3.5, -3.5)
    clear_pose_intent(_n)

check("a ground pose gets no place, though the room has three markers",
      places.assign("Kira", "kneeling") is None
      and get_character_profile("Kira").get("place") is None)
set_pose_intent("Kira", "kneeling")
check("...the setter leaves her without one too",
      get_character_profile("Kira").get("place") is None
      and places._named_place("Kira") is None
      and places.place_phrase("Kira") == "",
      str(get_character_profile("Kira").get("place")))
_offer = places.room_offer("Kira", HOUSE, "lounge")
# What the Anywhere line still carries. The room HAS a stand marker, so
# `standing` is already on its row and is left out here — naming it twice
# costs prompt and says nothing new. `chatting` needs two slots on ONE place
# and st1 holds one, so the marker does not offer it and it stays. `kneeling`
# has no ground marker in this room at all, so it stays too.
check("a pose the marker already offers is left out of the Anywhere line",
      "Anywhere here: chatting (with partner), kneeling" in _offer, repr(_offer))
check("...and the two placed types are rows of their own",
      "Lying place (free): lying, sleeping" in _offer
      and "Seat (free): sitting" in _offer, repr(_offer))
check("...while the stand marker names standing on its own row",
      "- Standing spot (free): standing" in _offer, repr(_offer))

# Everything covered -> the line goes away entirely, it is not left empty.
# A capacity-2 stand marker also covers the pair pose, and a ground marker
# covers kneeling; nothing placeless is left to offer.
write_rooms([("full", "Full", room_layout([
    {"id": "st2", "group": "stand", "at": [1.0, 1.0], "capacity": 2,
     "spacing_m": 0.6},
    {"id": "gr1", "group": "ground", "at": [4.0, 1.0]}]))])
save_character_current_room("Kira", "full")
_full = places.room_offer("Kira", HOUSE, "full")
check("every placeless pose covered: no Anywhere line at all",
      "Anywhere here" not in _full, repr(_full))
check("...the markers carry them instead",
      "- Standing spot (free): standing, chatting (with partner)" in _full
      and "- Ground (free): kneeling" in _full, repr(_full))

# A marker with no free slot offers nothing, so its poses come back: a full
# room must not stop anyone standing.
save_character_current_room("Ann", "full")
save_character_current_room("Bob", "full")
places.assign("Ann", "standing", prefer="st2")
places.assign("Bob", "standing", prefer="st2")
_taken = places.room_offer("Kira", HOUSE, "full")
check("an occupied stand marker gives its poses back to Anywhere",
      "Anywhere here: standing" in _taken, repr(_taken))
places.release("Ann")
places.release("Bob")
save_character_current_room("Ann", "lounge")
save_character_current_room("Bob", "lounge")
write_rooms([("lounge", "Lounge", room_layout([
    {"id": "couch", "group": "lie", "at": [2.0, 4.0]},
    {"id": "s1", "group": "seat", "at": [1.0, 1.0]},
    {"id": "st1", "group": "stand", "at": [6.0, 1.0]}]))])
save_character_current_room("Kira", "lounge")

# A HELD place of a placeless group is still not named: the rule reads the
# flag, not the group name — "standing, on the standing spot" tells a prompt
# nothing, and the same has to hold for a ground spot an admin authors.
check("a stand marker IS assigned when one exists",
      places.assign("Ann", "standing") == {"id": "st1", "slot": 0, "room_id": "lounge"})
check("...but it is never named",
      places._named_place("Ann") is None and places.place_label("Ann") == ""
      and places.place_phrase("Ann") == "")

# The pair rule of the same flag: no marker, no exception.
places.release("Ann")
check("a placeless pair meets halfway (None), it does not raise",
      places.assign_pair("Ann", "Bob", "chatting") is None
      and get_character_profile("Ann").get("place") is None)


# ── [6] falling asleep ──────────────────────────────────────────────────
print("\n[6] whoever falls asleep lies down")
for _n in ("Kira", "Ann", "Bob"):
    clear_pose_intent(_n)
    places.release(_n)
check("Ann sits on s1", places.assign("Ann", "sitting")
      == {"id": "s1", "slot": 0, "room_id": "lounge"})
set_is_sleeping("Ann", True)
check("falling asleep moves her to the lying place",
      get_character_profile("Ann").get("place")
      == {"id": "couch", "slot": 0, "room_id": "lounge"},
      str(get_character_profile("Ann").get("place")))
# The bed goes with the sleep. Waking clears the pose, and a place without a
# pose still puts the body on the mattress — every renderer draws a figure
# where its PLACE says, not where its pose says.
set_is_sleeping("Ann", False)
check("waking up gives the lying place back",
      get_character_profile("Ann").get("place") is None,
      str(get_character_profile("Ann").get("place")))
check("...so the couch is free again",
      places.assign("Ann", "lying") == {"id": "couch", "slot": 0, "room_id": "lounge"})
places.release("Ann")

# A sleeper who ALREADY lies keeps the place it holds — assign's keep branch,
# not a release-and-take that would hand the couch to someone else in between.
check("Ann lies down", places.assign("Ann", "lying")
      == {"id": "couch", "slot": 0, "room_id": "lounge"})
set_is_sleeping("Ann", True)
check("falling asleep on the couch keeps that very place",
      get_character_profile("Ann").get("place")
      == {"id": "couch", "slot": 0, "room_id": "lounge"},
      str(get_character_profile("Ann").get("place")))
set_is_sleeping("Ann", False)
places.release("Ann")

# Same transition, no free lying place: the seat is GIVEN UP rather than kept
# — a sitter with the lying figure's root drop sinks into the upholstery.
check("Bob takes the only lying place", places.assign("Bob", "lying")
      == {"id": "couch", "slot": 0, "room_id": "lounge"})
check("Ann sits down again", places.assign("Ann", "sitting")
      == {"id": "s1", "slot": 0, "room_id": "lounge"})
set_is_sleeping("Ann", True)
check("falling asleep with no lying place free releases the seat",
      get_character_profile("Ann").get("place") is None,
      str(get_character_profile("Ann").get("place")))
check("...and Bob keeps his",
      get_character_profile("Bob").get("place")
      == {"id": "couch", "slot": 0, "room_id": "lounge"})
set_is_sleeping("Ann", False)
check("waking up assigns nothing",
      get_character_profile("Ann").get("place") is None)


# ── [6b] a partial run is not a finished one ────────────────────────────
# The failure mode this guards: a prop that keeps a retired group is dropped
# from the scene by scene_recipe WITHOUT a word. Stamping the flag over such a
# run would mean no boot ever looks at it again.
print("\n[6b] a sidecar that cannot be written keeps the run open")
from app.models.world import get_world_setting, set_world_setting  # noqa: E402

set_world_setting(_FLAG, "")
_pid = "broken-prop"
(paths.get_storage_dir() / "props" / _pid).mkdir(parents=True, exist_ok=True)
prop_store._write_sidecar(_pid, {"name": "Broken", "model_variants": [
    {"markers": [{"id": "x", "group": "bed", "at": [0.5, 0.5, 0.5]}]}]})
_orig_write = prop_store._write_sidecar


def _refuse(pid, meta):
    if pid == _pid:
        raise OSError("disk full")
    return _orig_write(pid, meta)


prop_store._write_sidecar = _refuse
try:
    _stats = migrate_place_groups_once()
finally:
    prop_store._write_sidecar = _orig_write
check("the failure is counted, not swallowed",
      _stats.get("props_failed") == 1, str(_stats))
check("the flag stays unset so the next boot retries",
      not get_world_setting(_FLAG), repr(get_world_setting(_FLAG)))
_grp = prop_store.read_sidecar(_pid)["model_variants"][0]["markers"][0]["group"]
check("the unwritable prop still carries the retired group", _grp == "bed", _grp)
_stats2 = migrate_place_groups_once()
_grp = prop_store.read_sidecar(_pid)["model_variants"][0]["markers"][0]["group"]
check("the retry writes it", _grp == "lie", _grp)
check("...and only NOW is the flag set", bool(get_world_setting(_FLAG)))

# ── [7] the import path ─────────────────────────────────────────────────
print("\n[7] a pack from before the rebuild is renamed on import")
from app.core.content_io import _sanitize_imported_location  # noqa: E402
from app.core.prop_field_migration import normalize_prop_sidecar  # noqa: E402

_loc = {"id": "packed", "name": "Packed Inn",
        "rooms": [{"id": "r1", "name": "Cellar",
                   "layout": {"x": 0, "y": 0, "w": 6, "d": 4,
                              "markers": [{"id": "b", "group": "bed", "at": [1, 1]},
                                          {"id": "c", "group": "counter", "at": [2, 2]}]}}]}
_warn = _sanitize_imported_location(_loc)
check("the imported markers speak the new vocabulary",
      [m["group"] for m in _loc["rooms"][0]["layout"]["markers"]] == ["lie", "stand"],
      str(_loc["rooms"][0]["layout"]["markers"]))
check("...and the import says so instead of swallowing it",
      any("retired place type" in w and "2 marker" in w for w in _warn), str(_warn))

PACK_PROP = "packed-stool"
(paths.get_storage_dir() / "props" / PACK_PROP).mkdir(parents=True, exist_ok=True)
prop_store._write_sidecar(PACK_PROP, {
    "name": "Stool", "width_m": 0.4, "depth_m": 0.4, "height_m": 0.5,
    prop_store.VARIANTS_KEY: [
        {prop_store.MARKERS_KEY: [{"id": "k", "group": "counter", "at": [0.5, 0.0, 0.5]}]}]})
check("normalize_prop_sidecar reports the change", normalize_prop_sidecar(PACK_PROP) is True)
check("...and the installed prop's marker is a standing spot",
      [m["group"] for m in prop_store.read_sidecar(PACK_PROP)
       [prop_store.VARIANTS_KEY][0][prop_store.MARKERS_KEY]] == ["stand"])
check("a second normalisation finds nothing left to do",
      normalize_prop_sidecar(PACK_PROP) is False)


# ── [8] an unknown place type leaves a trace ────────────────────────────
# The failure this guards (plan-platztypen.md E2): NOTHING checked a marker's
# group against the catalog on the way in, and `scene_recipe` skipped an
# unknown one with a bare `continue`. A typo or a content pack from before the
# rename therefore made markers vanish from the scene AND from the place
# inventory, and the symptom was an empty room — never a message. Nothing is
# corrected here and nothing falls back to a neighbouring group; the point is
# only that there is a trace.
print("\n[8] an unknown place type is reported, not swallowed")
import logging  # noqa: E402
from contextlib import contextmanager  # noqa: E402


@contextmanager
def captured(name: str):
    """Every WARNING the logger ``name`` emits inside the block, formatted."""
    out: list = []

    class _Sink(logging.Handler):
        def emit(self, record):
            out.append(record.getMessage())

    lg = logging.getLogger(name)
    sink = _Sink(level=logging.WARNING)
    lg.addHandler(sink)
    try:
        yield out
    finally:
        lg.removeHandler(sink)


from app.core import furnish_needs, scene_recipe, world_ops  # noqa: E402

# ── the two sanitizers ──────────────────────────────────────────────────
with captured("world") as _log:
    _kept = world_ops._sanitize_markers([
        {"id": "m1", "group": "bed", "at": [1.0, 1.0]},
        {"id": "m2", "group": "seat", "at": [2.0, 2.0]}])
check("the layout sanitizer keeps BOTH markers", len(_kept) == 2, str(_kept))
check("...and leaves the unknown group exactly as authored",
      [m["group"] for m in _kept] == ["bed", "seat"], str(_kept))
check("...but says so once, naming marker and group",
      len(_log) == 1 and "m1" in _log[0] and "'bed'" in _log[0], str(_log))

with captured("app.core.props") as _log:
    _kept = prop_store.sanitize_markers([
        {"id": "p1", "group": "counter", "at": [0.5, 0.5, 0.5]},
        {"id": "p2", "group": "lie", "at": [0.5, 1.0, 0.5]}])
check("the prop sanitizer keeps both too",
      [m["group"] for m in _kept] == ["counter", "lie"], str(_kept))
check("...and reports the unknown one once",
      len(_log) == 1 and "p1" in _log[0] and "'counter'" in _log[0], str(_log))

# ── the scene: ONE line for the whole composition ───────────────────────
# Three unusable markers of TWO groups across TWO rooms. Composing a scene is
# the hot path (every poll of every client), so the composer collects and the
# caller reports once — one line naming both groups, not three lines, and not
# one per poll and marker.
_WARN_LOC = {
    "id": "warn-house", "name": "Warn House",
    "map3d": {"outline": [[0, 0], [10, 0], [10, 8], [0, 8]],
              "plan_width_m": 10.0, "storey_height_m": 3.0},
    "rooms": [
        {"id": "r0", "name": "Ground",
         "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 0,
                    "markers": [{"id": "ok", "group": "seat", "at": [1, 1]},
                                {"id": "b1", "group": "bed", "at": [2, 1]},
                                {"id": "b2", "group": "bed", "at": [3, 1]}]}},
        {"id": "r1", "name": "Upper",
         "layout": {"x": 2, "y": 2, "w": 4, "d": 3, "level": 1,
                    "markers": [{"id": "c1", "group": "counter",
                                 "at": [1, 1]}]}},
    ]}
with captured("app.core.scene_recipe") as _log:
    _scene = scene_recipe.compose_scene(_WARN_LOC, plan_width_m=10.0)
check("only the known marker becomes a place",
      [m["id"] for m in _scene["markers"]] == ["ok"],
      str([m["id"] for m in _scene["markers"]]))
check("ONE line for three bad markers in two rooms", len(_log) == 1, str(_log))
check("...and it names both groups and the count",
      len(_log) == 1 and "'bed'" in _log[0] and "'counter'" in _log[0]
      and "2 marker place type(s)" in _log[0], str(_log))

# ── the furnishing dialog ───────────────────────────────────────────────
# `valid_marker` used to answer None for "no marker given" and for "the
# catalog does not know this group" alike, and only the first is silent by
# right. The NEED survives either way — a chair without a marker is still a
# chair — but the loss now reaches the confirmation dialog through `dropped`.
_GROUPS = list(pose_catalog.get_groups())
with captured("app.core.furnish_needs") as _log:
    _needs, _dropped = furnish_needs.valid_needs([
        {"kind": "armchair", "width_m": 0.8, "depth_m": 0.8, "height_m": 1.0,
         "description": "a worn leather armchair",
         "marker": {"group": "bed", "at": [0.5, 0.6, 0.5]}},
        {"kind": "rug", "width_m": 2.0, "depth_m": 1.5, "height_m": 0.06,
         "description": "a woven rug"},
        {"kind": "stool", "width_m": 0.4, "depth_m": 0.4, "height_m": 0.5,
         "description": "a three-legged stool",
         "marker": {"group": "seat", "at": [0.5, 0.9, 0.5]}},
    ], _GROUPS)
check("all three needs survive", [n["kind"] for n in _needs]
      == ["armchair", "rug", "stool"], str([n["kind"] for n in _needs]))
check("the armchair is built WITHOUT a place", _needs[0]["marker"] is None,
      str(_needs[0]["marker"]))
check("the stool keeps its seat", (_needs[2]["marker"] or {}).get("group")
      == "seat", str(_needs[2]["marker"]))
check("exactly one entry reaches the dialog", len(_dropped) == 1, str(_dropped))
check("...naming the piece and the group",
      len(_dropped) == 1 and _dropped[0]["kind"] == "armchair"
      and "'bed'" in _dropped[0]["reason"], str(_dropped))
check("...and the rug, which never asked for a marker, is NOT in it",
      all(d["kind"] != "rug" for d in _dropped), str(_dropped))
check("the log carries it as well", len(_log) == 1 and "armchair" in _log[0],
      str(_log))


# ── result ──────────────────────────────────────────────────────────────
pose_catalog.catalog_path = _orig_catalog_path
if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nall checks passed")
