#!/usr/bin/env python3
"""Smoke run for PAIR INTERACTIONS (app/core/interaction_engine.py).

Throwaway storage + throwaway clip directory — never touches a real world or
the real clip library. No server.

The clip convention the expectations are derived from (app/blender/scripts/
cmu_clip.py, docs/schnittstellen-3d.md § A8a): a pair clip's frame has its
origin at the ANCHOR and +X pointing from A to B; a client places a figure at
``anchor + R_y(yaw) · clip_root`` with three.js's Y rotation
(x' = x·cos + z·sin, z' = −x·sin + z·cos).

World: one location "Smoke Plaza" pinned at (10, 22) with a DRAWN 20 m
boundary (authored in LOCAL metres around the pin, ±10 → world 0..20 ×
12..32; ``set_character_pos`` derives the location from the point, so
without the boundary nobody would stand IN the plaza and the room's places
could never be found), both characters inside it and in the same room
"square". Game clock pinned (factor 0). Catalog (private copy): "standing"
(group stand), "embracing" (solo false, group stand, places 2, yaw_offset 0,
animation "hug"), "cuddling" (solo false, group SEAT, animation "hug"),
"kissing" (no clip pair), "swaying" (loop clip). Blocks [1]–[8] run with a
room WITHOUT markers, so a pair meets at the midpoint; [9] adds the markers.

Hand-derived expectations:

  [1] Clip discovery: ``hug__a.fbx`` + ``hug__b.fbx`` + ``hug.json`` make the
      pair kind "hug"; the catalog pose "embracing" (solo: false, animation
      "hug") is a partner pose, "standing" is not.

  [2] Geometry: Ann stands at (10, 20), Bob at (10, 24) — Bob is 4 m away
      in +Z. The anchor is the midpoint (10, 22). The yaw must map clip +X
      onto world +Z: with x' = x·cos + z·sin, z' = −x·sin + z·cos the clip
      point (1, 0) goes to (cos yaw, −sin yaw) = (0, 1) → yaw = −π/2.
      The sidecar puts A at clip (−0.3, 0) and B at (+0.3, 0) at the anchor
      moment, so the game-state positions become Ann (10, 21.7) and
      Bob (10, 22.3) — the pair faces each other 0.6 m apart along +Z.

  [3] Both profiles carry the same interaction id, roles a/b, the partner,
      ``duration_s`` = 2.0 from the sidecar and the pinned start stamp;
      both poses are "embracing".

  [4] Clock: at +1.0 game second the state is elapsed 1.0 / not done; at
      +2.0 it is done. ``settle_finished`` then clears BOTH profiles and the
      poses go back to empty.

  [5] Guards: 5 m apart is too far (MAX_START_DISTANCE_M = 4.5), a partner
      490 m away elsewhere is refused, a solo pose ("standing") is refused,
      an already-bound character is refused.

  [6] A new pose on one partner ends the interaction for both; a manual
      ``set_character_pos`` (teleport) ends it too.

  [7] The worldmap payload carries the ``interaction`` block on both
      characters while it runs (anchor, role, elapsed), and null after.

  [8] A pair clip whose sidecar says ``loop`` (a pack's 0.5 s cycle) runs
      for LOOP_INTERACTION_S game seconds — the payload says so
      (``loop``, ``clip_duration_s`` 0.5) and a client replays the cycle;
      after 5 s it is still running.

  [9] A pair anchors on a free PLACE of its group (plan-posen-plaetze.md
      § 4, Task 9). The room "square" gets the layout {x −5, y −5, w 10,
      d 10} — room metres from the location origin (10, 22) — and two
      stand markers: "spot" at (5, 5), capacity 2, rotation 90 → world
      (10 − 5 + 5, 22 − 5 + 5) = (10, 22), facing 90; its slots lie ACROSS
      the facing (lateral = (cos 90°, −sin 90°) = (0, −1)), 0.6 m apart:
      slot 0 = (10, 22.3), slot 1 = (10, 21.7); "spot2" at (2, 2),
      capacity 1 → (7, 19).
      Ann (10, 20) + Bob (10, 24) start "embracing": the anchor is the
      marker CENTRE = mean of the slots = (10, 22) (not the midpoint of the
      figures, which here happens to coincide — the yaw tells them apart).
      yaw: compass facing f gives the world direction (sin f, cos f); the
      clip's +X is mapped onto it by _yaw_from_to's atan2(−uz, ux) →
      atan2(−cos f, sin f) = f − 90°; f = 90 → 0.0 rad, plus yaw_offset 0.
      (Midpoint path of [2]: Bob is in +Z → −π/2; here the marker faces
      east, so the pair stands along +X instead.) The sidecar offsets
      (∓0.3, 0) turned by 0 → Ann at (9.7, 22), Bob at (10.3, 22).
      Both profiles hold place {spot, slot "pair", square}; the anchor
      carries place_id "spot"; the worldmap row's ``place`` says slot
      "pair" on the place's centre (10, 22) — the anchor — and the anchor's
      place_id. The
      pair consumes ``places`` = 2 slots: free_slots(spot) == [] and
      _taken_count == 2. ``assign("Ann", "embracing")`` — what the setter
      calls right after — KEEPS the pair seat unchanged, so Ann is not
      moved onto a solo slot. end_interaction clears interaction, pose and
      place on both.
      Advisory pre-check: the pair started again, Cid seated on spot2
      (capacity 1, prefer). ``set_pose_intent("Ann", "standing",
      prefer="spot2")`` raises PlaceUnavailable BEFORE the interaction is
      ended — both still hold it, Ann's pose and pair seat are untouched.
      The pair's own place insisted (``prefer="spot"``) passes: the pair's
      two slots do not count against its partners, the interaction ends
      for both, Ann sits on spot/0 (10, 22.3) with pose "standing", Bob
      holds nothing.
      Marker taken by a third (Cid on spot/0 → ONE free slot < 2 needed):
      the standing pair meets halfway as in [2] — anchor (10, 22), yaw
      −π/2, place_id None, no place on either — the solo setter after the
      start must NOT seat a partner of a placeless pair on the spot's free
      slot (it would drag the figure off the anchor), so Cid's slot 0 stays
      the spot's only occupancy. "cuddling" is a SEAT pair and the square
      has no seat: refused with "no free seat for two", nothing written.
      The "together" rule runs against the ANCHOR: Ann (10, 13) + Bob
      (10, 14) are 1 m apart but 9 m / 8 m from spot (10, 22) → a STANDING
      pair meets halfway (anchor (10, 13.5), yaw −π/2, place_id None, no
      place held); a seat marker "bench" at room (0, 0) → world (5, 17)
      with Ann (10, 20) √(5² + 3²) = 5.83 m and Bob (10, 24)
      √(5² + 7²) = 8.60 m away → a SEATED pair is refused ("Bob is too far
      from the Seat (8.6 m)"), the pair seat is released, nothing written.
      Places are WORLD metres: the recipe composes in the location's LOCAL
      frame (origin = pin), places.py maps every slot through
      local_to_world and turns the facing with the location. Pinned at
      (10, 22) and turned by 90°: local slot 0 (0, 0.3) → x = 10 + 0·cos
      90° + 0.3·sin 90° = 10.3, z = 22 − 0·sin 90° + 0.3·cos 90° = 22 →
      (10.3, 22); slot 1 (9.7, 22); facing 90 + 90 = 180.

Usage:  ./.venv/bin/python scripts/smoke_interaction.py
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="interaction-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="interaction-smoke-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import interaction_engine as ie  # noqa: E402
from app.core import places, pose_catalog  # noqa: E402
from app.core.animation_clips import pair_kinds  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import game_time, set_game_factor, set_game_time  # noqa: E402
from app.models.character import (  # noqa: E402
    clear_pose_intent, get_character_pos, get_character_pose_key, get_character_profile,
    save_character_current_location, save_character_current_room,
    save_character_profile, set_character_pos, set_pose_intent)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-3) -> bool:
    return abs(float(a) - float(b)) <= eps


# ── fixtures ────────────────────────────────────────────────────────────
(CLIPS / "hug__a.fbx").write_bytes(b"a")
(CLIPS / "hug__b.fbx").write_bytes(b"b")
(CLIPS / "hug.json").write_text(json.dumps({
    "kind": "hug", "pair": True, "fps": 30, "frames": 60, "duration_s": 2.0,
    "geometry": {"anchor_frame": 30, "root_distance_m": 0.6,
                 "roles": {"a": {"anchor_xz_m": [-0.3, 0.0]},
                           "b": {"anchor_xz_m": [0.3, 0.0]}}}}), encoding="utf-8")

# A LOOPING pair (a pack's 0.5 s cycle): the interaction must run for
# LOOP_INTERACTION_S game seconds, not for one cycle.
(CLIPS / "sway__a.fbx").write_bytes(b"a")
(CLIPS / "sway__b.fbx").write_bytes(b"b")
(CLIPS / "sway.json").write_text(json.dumps({
    "kind": "sway", "pair": True, "fps": 30, "frames": 15, "duration_s": 0.5, "loop": True,
    "geometry": {"anchor_frame": 0, "root_distance_m": 0.2,
                 "roles": {"a": {"anchor_xz_m": [-0.1, 0.0]}, "b": {"anchor_xz_m": [0.1, 0.0]}}}}),
    encoding="utf-8")

# A private pose catalog for the smoke: the real one must not be edited.
CAT = Path(tempfile.mkdtemp(prefix="interaction-smoke-cat-"))
_orig_catalog_path = pose_catalog.catalog_path


def _smoke_catalog_path(axis: str) -> Path:
    return CAT / f"{axis}_catalog.json" if axis == "pose" else _orig_catalog_path(axis)


pose_catalog.catalog_path = _smoke_catalog_path
(CAT / "pose_catalog.json").write_text(json.dumps({"groups": {
    "stand": {"label": "Standing spot", "root_drop": 0, "default": "standing"},
    "seat": {"label": "Seat", "root_drop": 0.314, "default": "cuddling"},
}, "entries": {
    "standing": {"prompt": "standing", "synonyms": [], "animation": "idle", "_default": True,
                 "group": "stand"},
    "embracing": {"prompt": "two people hugging", "synonyms": ["hug"],
                  "animation": "hug", "solo": False, "group": "stand", "places": 2,
                  "yaw_offset": 0},
    "cuddling": {"prompt": "cuddling on a seat", "synonyms": [], "animation": "hug",
                 "solo": False, "group": "seat", "places": 2, "yaw_offset": 0},
    "kissing": {"prompt": "kissing", "synonyms": [], "animation": "kiss", "solo": False},
    "swaying": {"prompt": "swaying together", "synonyms": [], "animation": "sway", "solo": False},
}}), encoding="utf-8")
pose_catalog.reload_catalogs()

START = GameTime.parse("Y0001-D001T12:00:00")
set_game_factor(0.0)
set_game_time(START)

PLAZA = add_location(name="Smoke Plaza", description="interaction smoke",
                     rooms=[{"id": "square", "name": "Square"}])["id"]
update_location_position(PLAZA, 10.0, 22.0)
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == PLAZA:
        _loc.setdefault("map3d", {})["plan_width_m"] = 20.0
        _loc["map3d"]["boundary"] = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
_save_world_data(_data)
FAR = add_location(name="Smoke Far", description="elsewhere")["id"]
update_location_position(FAR, 500.0, 0.0)


def new_character(name: str, x: float, z: float, loc: str = PLAZA) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    save_character_current_location(name, loc)
    # The point is the truth: set_character_pos derives the location from it
    # (a later save_character_current_location would snap the figure back to
    # the location centre).
    set_character_pos(name, x, z)
    save_character_current_room(name, "square")


new_character("Ann", 10.0, 20.0)
new_character("Bob", 10.0, 24.0)
new_character("Cid", 10.0, 25.0)
new_character("Dee", 500.0, 0.0, FAR)

# ── [1] discovery ───────────────────────────────────────────────────────
print("[1] clip discovery + partner poses")
check("pair_kinds finds hug and sway", pair_kinds() == ["hug", "sway"], str(pair_kinds()))
check("'embracing' is a partner pose with kind hug",
      ie.pair_kind_for_pose("embracing") == "hug")
check("'standing' is not", ie.pair_kind_for_pose("standing") == "")
check("'kissing' (no clip pair) is not", ie.pair_kind_for_pose("kissing") == "")
check("partner_poses lists cuddling, embracing and swaying",
      sorted(ie.partner_poses()) == [("cuddling", "hug"), ("embracing", "hug"), ("swaying", "sway")],
      str(ie.partner_poses()))

# ── [2]+[3] start ───────────────────────────────────────────────────────
print("\n[2] anchor geometry")
inter = ie.start_interaction("Ann", "Bob", "embracing")
anchor = inter["anchor"]
check("anchor is the midpoint (10, 22)", near(anchor["x"], 10) and near(anchor["z"], 22),
      str(anchor))
check("yaw maps clip +X onto world +Z (−π/2)", near(anchor["yaw"], -math.pi / 2, 1e-3),
      str(anchor["yaw"]))
pa, pb = get_character_pos("Ann"), get_character_pos("Bob")
check("Ann stands at (10, 21.7)", near(pa["x"], 10, 0.011) and near(pa["z"], 21.7, 0.011), str(pa))
check("Bob stands at (10, 22.3)", near(pb["x"], 10, 0.011) and near(pb["z"], 22.3, 0.011), str(pb))

print("\n[3] both profiles")
ia = ie.get_interaction("Ann")
ib = ie.get_interaction("Bob")
check("same id on both", ia and ib and ia["id"] == ib["id"])
check("roles a/b", ia["role"] == "a" and ib["role"] == "b")
check("partners cross-linked", ia["partner"] == "Bob" and ib["partner"] == "Ann")
check("duration from the sidecar", ia["duration_s"] == 2.0 and ib["duration_s"] == 2.0)
check("start stamp is the pinned clock", ia["started_at_game"] == START.canonical(),
      ia["started_at_game"])
check("both poses are embracing",
      get_character_pose_key("Ann") == "embracing" and get_character_pose_key("Bob") == "embracing")

# ── [7a] payload while running ──────────────────────────────────────────
print("\n[7] worldmap payload")
from app.core.world_ops import build_worldmap_payload  # noqa: E402
wm = build_worldmap_payload(show_all=True)
rows = {c["name"]: c for c in wm["characters"]}
check("Ann's row carries the interaction",
      rows["Ann"].get("interaction", {}) and rows["Ann"]["interaction"]["role"] == "a"
      and near(rows["Ann"]["interaction"]["anchor"]["yaw"], -math.pi / 2, 1e-3)
      and rows["Ann"]["interaction"]["elapsed_s"] == 0.0, str(rows["Ann"].get("interaction")))
check("Bob's row too, role b, same id",
      rows["Bob"].get("interaction", {}) and rows["Bob"]["interaction"]["role"] == "b"
      and rows["Bob"]["interaction"]["id"] == rows["Ann"]["interaction"]["id"])
check("Cid has none", rows["Cid"].get("interaction") is None)

# ── [5] guards ──────────────────────────────────────────────────────────
print("\n[5] guards")


def refused(actor, partner, pose):
    try:
        ie.start_interaction(actor, partner, pose)
        return ""
    except ValueError as e:
        return str(e)


check("a bound character is refused", "busy" in refused("Cid", "Ann", "embracing"),
      refused("Cid", "Ann", "embracing"))
check("a solo pose is refused", "no pair animation" in refused("Cid", "Dee", "standing"))
# Dee is 490 m away in another location; whichever guard fires first (the
# location compare, or the distance when the smoke world derives no location
# for an unbounded place), she is refused.
_r = refused("Cid", "Dee", "embracing")
check("someone elsewhere is refused", "not here" in _r or "too far" in _r, _r)
new_character("Eve", 10.0, 30.0)            # 5 m from Cid (10, 25)
check("5 m is too far", "too far" in refused("Cid", "Eve", "embracing"),
      refused("Cid", "Eve", "embracing"))

# ── [4] clock ───────────────────────────────────────────────────────────
print("\n[4] the game clock ends it")
set_game_time(START + GameDuration.of(seconds=1))
st = ie.interaction_state(ie.get_interaction("Ann"), game_time())
check("at +1 s: elapsed 1.0, not done", st["elapsed_s"] == 1.0 and not st["done"], str(st))
check("settle_finished closes nothing yet", ie.settle_finished() == 0)
set_game_time(START + GameDuration.of(seconds=2))
st = ie.interaction_state(ie.get_interaction("Ann"), game_time())
check("at +2 s: done", st["done"], str(st))
wm = build_worldmap_payload(show_all=True)
rows = {c["name"]: c for c in wm["characters"]}
check("payload already shows null when the clip is over",
      rows["Ann"].get("interaction") is None)
check("settle_finished closes ONE interaction (both profiles)", ie.settle_finished() == 1)
check("both profiles are clear",
      ie.get_interaction("Ann") is None and ie.get_interaction("Bob") is None)
check("poses are cleared", get_character_pose_key("Ann") == "" and get_character_pose_key("Bob") == "")

# ── [6] cancellations ───────────────────────────────────────────────────
print("\n[6] a new pose / a teleport ends it")
set_game_time(START)
ie.start_interaction("Ann", "Bob", "embracing")
set_pose_intent("Bob", "standing")
check("Bob's new pose frees Ann too", ie.get_interaction("Ann") is None
      and ie.get_interaction("Bob") is None)
check("Ann's pose was cleared, Bob's is standing",
      get_character_pose_key("Ann") == "" and get_character_pose_key("Bob") == "standing")
set_pose_intent("Bob", "")
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
ie.start_interaction("Ann", "Bob", "embracing")
set_character_pos("Ann", 12.0, 20.0)         # a manual move = teleport
check("a manual position write frees both", ie.get_interaction("Ann") is None
      and ie.get_interaction("Bob") is None)
check("the interaction's own position writes did NOT cancel it (proved by [3])", True)

# ── [8] a looping pair runs for LOOP_INTERACTION_S, the clip repeats ───────
print("\n[8] looping pair")
set_game_time(START)
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
inter = ie.start_interaction("Ann", "Bob", "swaying")
check("a 0.5 s cycle runs for LOOP_INTERACTION_S game seconds",
      inter["duration_s"] == ie.LOOP_INTERACTION_S and inter["clip_duration_s"] == 0.5 and inter["loop"],
      str({k: inter[k] for k in ("duration_s", "clip_duration_s", "loop")}))
wm = build_worldmap_payload(show_all=True)
row = {c["name"]: c for c in wm["characters"]}["Ann"]["interaction"]
check("payload carries loop + clip_duration_s", row["loop"] is True and row["clip_duration_s"] == 0.5, str(row))
set_game_time(START + GameDuration.of(seconds=5))
check("still running after 5 s (one cycle would be long over)",
      not ie.interaction_state(ie.get_interaction("Ann"), game_time())["done"])
ie.end_interaction("Ann")

# ── [9] a pair anchors on a free place of its group ─────────────────────
print("\n[9] a pair on a marker")
set_game_time(START)
for _n in ("Ann", "Bob", "Cid", "Eve"):
    clear_pose_intent(_n)
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == PLAZA:
        _loc["rooms"][0]["layout"] = {"x": -5, "y": -5, "w": 10, "d": 10, "markers": [
            {"id": "spot", "group": "stand", "at": [5, 5], "capacity": 2, "rotation": 90},
            {"id": "spot2", "group": "stand", "at": [2, 2], "rotation": 0}]}
_save_world_data(_data)
places.invalidate()
PL = {p["id"]: p for p in places.room_places(PLAZA, "square")}
check("spot: world (10, 22), facing 90, slots (10, 22.3) + (10, 21.7)",
      PL.get("spot", {}).get("facing") == 90.0
      and PL.get("spot", {}).get("slots") == [[10.0, 22.3], [10.0, 21.7]], str(PL.get("spot")))
check("spot2: world (7, 19)", PL.get("spot2", {}).get("slots") == [[7.0, 19.0]], str(PL.get("spot2")))
PAIR_FIELD = {"id": "spot", "slot": "pair", "room_id": "square"}

inter = ie.start_interaction("Ann", "Bob", "embracing")
anchor = inter["anchor"]
check("anchor is the marker centre (10, 22)", near(anchor["x"], 10) and near(anchor["z"], 22), str(anchor))
check("yaw = facing 90° − 90° = 0.0 (clip +X on world +x)", near(anchor["yaw"], 0.0), str(anchor["yaw"]))
check("anchor names the place", anchor.get("place_id") == "spot", str(anchor))
pa, pb = get_character_pos("Ann"), get_character_pos("Bob")
check("Ann at (9.7, 22), Bob at (10.3, 22)",
      near(pa["x"], 9.7, 0.011) and near(pa["z"], 22, 0.011)
      and near(pb["x"], 10.3, 0.011) and near(pb["z"], 22, 0.011), f"{pa} {pb}")
check("both hold the pair slot of spot",
      get_character_profile("Ann").get("place") == PAIR_FIELD
      and get_character_profile("Bob").get("place") == PAIR_FIELD,
      f'{get_character_profile("Ann").get("place")} {get_character_profile("Bob").get("place")}')
check("both poses are embracing",
      get_character_pose_key("Ann") == "embracing" and get_character_pose_key("Bob") == "embracing")
occ = places.occupancy(PLAZA, "square")
check("occupancy: spot [Ann/pair, Bob/pair]",
      sorted(occ.get("spot") or []) == [("Ann", "pair"), ("Bob", "pair")], str(occ))
check("the pair consumes both slots", places.free_slots(PL["spot"], occ["spot"]) == []
      and places._taken_count(PL["spot"], occ["spot"]) == 2)
check("assign keeps the pair seat (no re-seating onto a solo slot)",
      places.assign("Ann", "embracing") == PAIR_FIELD
      and get_character_profile("Ann").get("place") == PAIR_FIELD
      and near(get_character_pos("Ann")["x"], 9.7, 0.011), str(get_character_profile("Ann").get("place")))
wm = build_worldmap_payload(show_all=True)
rows = {c["name"]: c for c in wm["characters"]}
check("worldmap: anchor.place_id spot, place slot 'pair' on the centre (10, 22)",
      rows["Ann"]["interaction"]["anchor"].get("place_id") == "spot"
      and rows["Ann"].get("place", {}).get("slot") == "pair"
      and rows["Ann"]["place"]["x"] == 10.0 and rows["Ann"]["place"]["z"] == 22.0,
      f'{rows["Ann"]["interaction"]["anchor"]} {rows["Ann"].get("place")}')
ie.end_interaction("Ann")
check("end clears interaction, pose and place on both",
      ie.get_interaction("Ann") is None and ie.get_interaction("Bob") is None
      and get_character_pose_key("Ann") == "" and get_character_pose_key("Bob") == ""
      and get_character_profile("Ann").get("place") is None
      and get_character_profile("Bob").get("place") is None)
check("spot is free again", "spot" not in places.occupancy(PLAZA, "square"))

# advisory pre-check: an insisted taken place is refused BEFORE the interaction ends
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
ie.start_interaction("Ann", "Bob", "embracing")
check("Cid takes spot2", places.assign("Cid", "standing", prefer="spot2")
      == {"id": "spot2", "slot": 0, "room_id": "square"})
try:
    set_pose_intent("Ann", "standing", prefer="spot2")
    _r = "no exception"
except places.PlaceUnavailable as e:
    _r = str(e)
check("a taken insisted place raises PlaceUnavailable", _r != "no exception", _r)
check("… BEFORE the interaction ended: both still bound",
      ie.get_interaction("Ann") is not None and ie.get_interaction("Bob") is not None)
check("… Ann's pose and pair seat untouched",
      get_character_pose_key("Ann") == "embracing"
      and get_character_profile("Ann").get("place") == PAIR_FIELD)
set_pose_intent("Ann", "standing", prefer="spot")
check("the pair's own place insisted: interaction over for both",
      ie.get_interaction("Ann") is None and ie.get_interaction("Bob") is None)
check("… Ann on spot/0 (10, 22.3) standing, Bob holds nothing",
      get_character_profile("Ann").get("place") == {"id": "spot", "slot": 0, "room_id": "square"}
      and get_character_pos("Ann") == {"x": 10.0, "z": 22.3}
      and get_character_pose_key("Ann") == "standing"
      and get_character_profile("Bob").get("place") is None and get_character_pose_key("Bob") == "",
      f'{get_character_profile("Ann").get("place")} {get_character_pos("Ann")}')
clear_pose_intent("Ann")
clear_pose_intent("Cid")

# marker taken by a third: one free slot is not enough for two
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
check("Cid holds spot/0", places.assign("Cid", "standing", prefer="spot")
      == {"id": "spot", "slot": 0, "room_id": "square"})
inter = ie.start_interaction("Ann", "Bob", "embracing")
anchor = inter["anchor"]
check("one free slot < 2: midpoint (10, 22), yaw −π/2, place_id None",
      near(anchor["x"], 10) and near(anchor["z"], 22) and near(anchor["yaw"], -math.pi / 2, 1e-3)
      and anchor.get("place_id", "missing") is None, str(anchor))
check("neither partner holds a place (a pair pose never takes a solo slot)",
      get_character_profile("Ann").get("place") is None
      and get_character_profile("Bob").get("place") is None,
      f'{get_character_profile("Ann").get("place")} {get_character_profile("Bob").get("place")}')
check("… and the spot's free slot stays free for a third",
      places.occupancy(PLAZA, "square").get("spot") == [("Cid", 0)])
ie.end_interaction("Ann")
clear_pose_intent("Cid")

# a SEAT pair without a seat is refused, nothing written
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
_r = refused("Ann", "Bob", "cuddling")
check("cuddling without a seat: 'no free seat for two'", _r == "no free seat for two", _r)
check("nothing written", ie.get_interaction("Ann") is None
      and get_character_profile("Ann").get("place") is None
      and get_character_profile("Bob").get("place") is None
      and get_character_pose_key("Ann") == "")

# the place is out of reach: a standing pair meets halfway, a seated pair is refused
set_character_pos("Ann", 10.0, 13.0)
set_character_pos("Bob", 10.0, 14.0)
inter = ie.start_interaction("Ann", "Bob", "embracing")
anchor = inter["anchor"]
check("spot 9 m away: the standing pair meets halfway (10, 13.5), yaw −π/2, place_id None",
      near(anchor["x"], 10) and near(anchor["z"], 13.5) and near(anchor["yaw"], -math.pi / 2, 1e-3)
      and anchor.get("place_id", "missing") is None, str(anchor))
check("… and holds no place", get_character_profile("Ann").get("place") is None
      and get_character_profile("Bob").get("place") is None)
ie.end_interaction("Ann")
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == PLAZA:
        _loc["rooms"][0]["layout"]["markers"].append(
            {"id": "bench", "group": "seat", "at": [0, 0], "capacity": 2, "rotation": 0})
_save_world_data(_data)
places.invalidate()
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
_r = refused("Ann", "Bob", "cuddling")
check("bench (5, 17) 8.6 m from Bob: the seated pair is refused",
      _r == "Bob is too far from the Seat (8.6 m)", _r)
check("… the pair seat was released, nothing written",
      ie.get_interaction("Ann") is None and ie.get_interaction("Bob") is None
      and get_character_profile("Ann").get("place") is None
      and get_character_profile("Bob").get("place") is None
      and "bench" not in places.occupancy(PLAZA, "square"))

# a turned location turns its places: pin (10, 22), yaw 90 → the marker
# stays on the pin, its facing becomes 180, the slots turn with it
update_location_position(PLAZA, 10.0, 22.0, yaw_deg=90.0)
places.invalidate()
_spot = next(p for p in places.room_places(PLAZA, "square") if p["id"] == "spot")
check("turned by 90°: spot faces 180, slots (10.3, 22) + (9.7, 22)",
      _spot["facing"] == 180.0 and _spot["slots"] == [[10.3, 22.0], [9.7, 22.0]], str(_spot))
update_location_position(PLAZA, 10.0, 22.0, yaw_deg=0.0)
places.invalidate()


print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
