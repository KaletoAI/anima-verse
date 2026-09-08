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

  [5a] ``set_pose_intent`` refuses a two-person key (catalog ``solo: false``)
      on a character that no interaction of that key binds: a pair pose on a
      lone profile has no partner and no anchor. "embracing" on the unbound
      Eve raises ``PairPoseWithoutPartner("embracing")`` and writes nothing,
      "standing" still goes through, and the pose the ENGINE wrote on the
      bound pair stands. The refusal happens BEFORE the setter's
      end-interaction branch, so asking a bound Ann for the other pair pose
      "cuddling" is refused with her running "embracing" untouched — a
      rejected pose must not cost her the pair she is in.

  [6] A new pose on one partner ends the interaction for both; a manual
      ``set_character_pos`` (teleport) ends it too, and so does a plain ROOM
      change — which writes no position, so the teleport guard never sees it.

  [7] The worldmap payload carries the ``interaction`` block on both
      characters while it runs (anchor, role, elapsed), and null after.

  [8] A pair clip whose sidecar says ``loop`` (a pack's 0.5 s cycle) runs
      for LOOP_INTERACTION_S game seconds — the payload says so
      (``loop``, ``clip_duration_s`` 0.5) and a client replays the cycle;
      after 5 s it is still running.

  [10] Invitations. A pair is ASKED, never imposed: ``create_invite`` writes
      the question and nothing else happens — no interaction on either side.
      Only the invitee is asked (the inviter sees what it waits on through
      ``outgoing_invite_of``), and asking twice replaces the open question
      rather than queueing a second. ``find_pending_invite`` is what turns a
      counter-invitation into consent. Accepting starts the pair and clears
      the question; declining starts nothing and cannot be re-answered. An
      inviter in another room is filtered out of the invitee's list at read
      time and reappears when they come back. Past ``INVITE_MAX_AGE_MIN``
      (SYSTEM minutes — a conversational window that a world freeze must not
      stretch forever) the row is neither offered nor read as consent.
      Answering one question clears the OTHER questions both partners were
      part of; a refusal that standing still will not fix (a sleeping
      partner) closes its question instead of leaving it hanging; and
      ``_claim_invite`` makes a second answer to the same row a no-op.

      THE WALK OVER. Geometry is checked on acceptance, and distance alone
      is the one refusal that walking fixes — so it is not a refusal. With
      Bob 8 m away his yes turns the row into ``approaching`` and sends BOB
      (the one who agreed, never the one who asked) to a metre short of Ann;
      ``settle_approaches`` leaves him alone while the journey runs, binds
      the pair on the beat after it ends, and marks the row ``accepted``.
      Calling the invitation off mid-walk cancels the journey with it — the
      trip existed only for that pair. Arriving with the other one gone ends
      the approach (``stale``) instead of walking after them forever.

      Finally ``describe`` renders the running pair as "embracing with Bob"
      from both sides and "" without one.

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

  [9b] A marker OUTSIDE the boundary seats without moving (review fix,
      "a seat never evicts"): "edge" at room-local (15.5, 5), capacity 2,
      rotation 90 → world (10 − 5 + 15.5, 22) = (20.5, 22), slots (20.5,
      22.3) + (20.5, 21.7) — half a metre past the plaza's boundary edge
      x = 20, so places.inside(plaza, 20.5, 22) is False. Ann (19, 21) +
      Bob (19, 23) — 1.8 m from the anchor, within MAX_START_DISTANCE_M —
      with Cid on spot/0 (spot cannot take two) start "embracing": the
      anchor is the edge centre (20.5, 22) with place_id "edge", both hold
      {edge, pair}, but the partner points (20.2, 22)/(20.8, 22) lie
      outside, so set_character_pos is skipped: Ann stays (19, 21), Bob
      (19, 23), both still in the square. The marker is removed afterwards.

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
from app.core.travel_engine import cancel_journey, get_journey  # noqa: E402
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
    # ``needs_place`` (plan-platztypen.md) is the property the "a pair without
    # a marker meets halfway" rule hangs on — it used to be the literal group
    # name "stand". A fixture that leaves it out inherits the default True and
    # would make every standing pair raise PlaceUnavailable.
    "stand": {"label": "Standing spot", "root_drop": 0, "default": "standing",
              "needs_place": False},
    # 0.320 is the shipped catalog's seat drop (re-derived 2026-09-08); no
    # check here reads it, but a fixture number that disagrees with the real
    # one just puts a second truth in front of the next reader.
    "seat": {"label": "Seat", "root_drop": 0.320, "default": "cuddling",
             "needs_place": True},
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

# ── [5a] the setter refuses a pair pose without a pair ──────────────────
print("\n[5a] a pair pose needs a bound pair")
from app.core.pose_catalog import PairPoseWithoutPartner  # noqa: E402


def pose_refused(name, pose):
    """The setter's verdict: the exception's key, or "" when it wrote."""
    try:
        set_pose_intent(name, pose)
        return ""
    except PairPoseWithoutPartner as e:
        return str(e)


check("a lone character cannot put on a pair pose",
      pose_refused("Eve", "embracing") == "embracing")
check("… and nothing was written", get_character_pose_key("Eve") == "")
check("a solo pose still goes through", pose_refused("Eve", "standing") == ""
      and get_character_pose_key("Eve") == "standing")
set_pose_intent("Eve", "")
check("the bound pair keeps its pose (the engine's own write)",
      get_character_pose_key("Ann") == "embracing"
      and get_character_pose_key("Bob") == "embracing")
# A pair pose OTHER than the running one is refused — and the refusal must
# not have torn down the interaction on its way out.
check("a bound character cannot switch to another pair pose",
      pose_refused("Ann", "cuddling") == "cuddling")
check("… and the running interaction survived the refusal",
      ie.get_interaction("Ann") is not None and ie.get_interaction("Bob") is not None
      and get_character_pose_key("Ann") == "embracing")

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
# A ROOM change writes no position at all, so the position guard above never
# sees it — and a pair anchored in the lounge must not keep playing while one
# half stands in the cellar.
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
ie.start_interaction("Ann", "Bob", "embracing")
save_character_current_room("Bob", "cellar")
check("a room change frees both", ie.get_interaction("Ann") is None
      and ie.get_interaction("Bob") is None)
save_character_current_room("Bob", "square")
clear_pose_intent("Ann")
clear_pose_intent("Bob")

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

# [9b] a marker outside the boundary seats the pair without moving anybody
ie.end_interaction("Ann")
clear_pose_intent("Cid")
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == PLAZA:
        _loc["rooms"][0]["layout"]["markers"].append(
            {"id": "edge", "group": "stand", "at": [15.5, 5], "capacity": 2, "rotation": 90})
_save_world_data(_data)
places.invalidate()
PL = {p["id"]: p for p in places.room_places(PLAZA, "square")}
check("edge: world (20.5, 22) — 0.5 m past the boundary's x = 20",
      PL.get("edge", {}).get("slots") == [[20.5, 22.3], [20.5, 21.7]], str(PL.get("edge")))
check("inside() says so", not places.inside(PLAZA, 20.5, 22.0) and places.inside(PLAZA, 19.0, 21.0))
set_character_pos("Ann", 19.0, 21.0)
set_character_pos("Bob", 19.0, 23.0)
check("Cid holds spot/0 again (spot cannot take two)",
      places.assign("Cid", "standing", prefer="spot") == {"id": "spot", "slot": 0, "room_id": "square"})
inter = ie.start_interaction("Ann", "Bob", "embracing")
anchor = inter["anchor"]
check("anchor is the edge marker's centre (20.5, 22), place_id edge",
      near(anchor["x"], 20.5) and near(anchor["z"], 22) and anchor.get("place_id") == "edge", str(anchor))
check("both hold {edge, pair}",
      get_character_profile("Ann").get("place") == {"id": "edge", "slot": "pair", "room_id": "square"}
      and get_character_profile("Bob").get("place") == {"id": "edge", "slot": "pair", "room_id": "square"})
check("nobody was moved out of the plaza: Ann (19, 21), Bob (19, 23), both still in the square",
      get_character_pos("Ann") == {"x": 19.0, "z": 21.0} and get_character_pos("Bob") == {"x": 19.0, "z": 23.0}
      and places.where("Ann") == (PLAZA, "square") and places.where("Bob") == (PLAZA, "square"),
      f'{get_character_pos("Ann")} {get_character_pos("Bob")} {places.where("Ann")}')
ie.end_interaction("Ann")
clear_pose_intent("Cid")
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == PLAZA:
        _loc["rooms"][0]["layout"]["markers"] = [
            m for m in _loc["rooms"][0]["layout"]["markers"] if m["id"] != "edge"]
_save_world_data(_data)
places.invalidate()
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

# ── [10] invitations: a pair is asked, never imposed ────────────────────
print("\n[10] invitations")
for _n in ("Ann", "Bob", "Cid"):
    ie.end_interaction(_n)
    clear_pose_intent(_n)
    ie.clear_invites_for(_n)
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)

iid = ie.create_invite("Ann", "Bob", "embracing")
check("an invitation is recorded", bool(iid))
check("nothing started from the question alone",
      ie.get_interaction("Ann") is None and ie.get_interaction("Bob") is None)
check("Bob is asked", [i["invite_id"] for i in ie.pending_invites_for("Bob")] == [iid])
check("Ann is not asked (she is the one asking)", ie.pending_invites_for("Ann") == [])
check("Ann sees what she is waiting on",
      (ie.outgoing_invite_of("Ann") or {}).get("invite_id") == iid)
# Asking again replaces the open question instead of queueing a second one.
iid2 = ie.create_invite("Ann", "Bob", "embracing")
check("asking twice leaves ONE open question",
      [i["invite_id"] for i in ie.pending_invites_for("Bob")] == [iid2] and iid2 != iid)

# The counter-invitation IS the consent: Bob asking Ann for the same thing
# finds her open question and starts the pair instead of asking back.
found = ie.find_pending_invite("Ann", "Bob", "embracing")
check("Bob finds Ann's open question", (found or {}).get("invite_id") == iid2)
res = ie.resolve_invite(iid2, True)
check("accepting starts the pair", res["status"] == "started")
check("both are bound", ie.get_interaction("Ann") is not None
      and ie.get_interaction("Bob") is not None)
check("the answered question is gone", ie.pending_invites_for("Bob") == [])

# A refusal is an answer, and it starts nothing.
ie.end_interaction("Ann")
iid3 = ie.create_invite("Ann", "Bob", "embracing")
check("declining starts nothing", ie.resolve_invite(iid3, False)["status"] == "declined"
      and ie.get_interaction("Bob") is None)
check("a declined question is not asked again", ie.pending_invites_for("Bob") == [])
check("answering it twice is not_found",
      ie.resolve_invite(iid3, True)["status"] == "not_found")

# Geometry is validated on ACCEPTANCE, not when the question is asked — the
# invitation survives the walk over. Close enough, and the yes starts the
# clip at once; the too-far case has its own block below.
iid4 = ie.create_invite("Ann", "Bob", "embracing")
check("within reach, a yes starts the pair straight away",
      ie.resolve_invite(iid4, True)["status"] == "started")
ie.end_interaction("Ann")

# Someone who leaves the room takes the question with them.
ie.end_interaction("Ann")
iid5 = ie.create_invite("Ann", "Bob", "embracing")
save_character_current_room("Ann", "cellar")
check("a question from another room is not asked", ie.pending_invites_for("Bob") == [])
save_character_current_room("Ann", "square")
check("… and comes back when she does",
      [i["invite_id"] for i in ie.pending_invites_for("Bob")] == [iid5])
check("taking it back closes it", ie.cancel_invite(iid5)
      and ie.pending_invites_for("Bob") == [])
check("and it cannot be taken back twice", ie.cancel_invite(iid5) is False)

# An invitation nobody answered must not start a clip in a scene hours later.
iid6 = ie.create_invite("Ann", "Bob", "embracing")
from app.core.db import transaction as _tx  # noqa: E402
from app.core.timeutils import utc_now as _now  # noqa: E402
from datetime import timedelta as _td  # noqa: E402
with _tx() as _c:
    _c.execute("UPDATE interaction_invites SET created_at=? WHERE invite_id=?",
               ((_now() - _td(minutes=ie.INVITE_MAX_AGE_MIN + 1)).isoformat(), iid6))
check("a question older than the window is not asked any more",
      ie.pending_invites_for("Bob") == [])
check("… and is not found as consent either",
      ie.find_pending_invite("Ann", "Bob", "embracing") is None)
ie.clear_invites_for("Ann")

# Starting a pair sweeps the OTHER questions both partners were part of:
# Cid's open ask to Bob cannot be answered while Bob is in a clip, and it
# would come back the moment the clip ends.
ie.end_interaction("Ann")
for _n in ("Ann", "Bob", "Cid"):
    ie.clear_invites_for(_n)
cid_ask = ie.create_invite("Cid", "Bob", "embracing")
ann_ask = ie.create_invite("Ann", "Bob", "embracing")
check("Bob has two open questions", len(ie.pending_invites_for("Bob")) == 2)
ie.resolve_invite(ann_ask, True)
check("answering one clears the other too", ie.pending_invites_for("Bob") == [],
      str(ie.get_invite(cid_ask)))
ie.end_interaction("Ann")

# Refusals that are NOT about the metres close the question: standing still
# will not make a sleeping partner available, so the banner must not linger.
from app.models.character import set_is_sleeping  # noqa: E402
iid7 = ie.create_invite("Ann", "Bob", "embracing")
set_is_sleeping("Bob", True)
res = ie.resolve_invite(iid7, True)
check("accepting with a sleeping partner is refused",
      res["status"] == "cannot" and "asleep" in res["reason"], str(res))
check("… and that question is closed, not left hanging",
      ie.get_invite(iid7)["status"] == "stale")
set_is_sleeping("Bob", False)

# The claim makes a double answer harmless: the second one finds nothing.
iid8 = ie.create_invite("Ann", "Bob", "embracing")
check("claiming the row once works", ie._claim_invite(iid8))
check("… and a second claim on the same row fails",
      ie._claim_invite(iid8) is False)
check("an already-claimed question answers not_found",
      ie.resolve_invite(iid8, True)["status"] == "not_found")
ie.clear_invites_for("Ann")

# ── the walk over: yes was said, only the metres are missing ────────────
# Ann asks from 8 m away. Bob says yes: the pair cannot start (8 m > 4.5),
# but the answer is consent, so BOB — the one who agreed — walks to a metre
# short of Ann and the ticker binds the pair when he arrives.
ie.end_interaction("Ann")
for _n in ("Ann", "Bob"):
    ie.clear_invites_for(_n)
    clear_pose_intent(_n)
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 28.0)
iid9 = ie.create_invite("Ann", "Bob", "embracing")
res = ie.resolve_invite(iid9, True)
check("too far on yes: the walk starts instead of a refusal",
      res["status"] == "approaching" and "too far" in res["reason"], str(res))
check("the one who AGREED is the one walking",
      get_journey("Bob") is not None and get_journey("Ann") is None)
check("the question is now an approach, not an open one",
      ie.get_invite(iid9)["status"] == "approaching"
      and ie.pending_invites_for("Bob") == [])
check("both ends see the approach",
      (ie.approach_of("Ann") or {}).get("invite_id") == iid9
      and (ie.approach_of("Bob") or {}).get("invite_id") == iid9)
check("nothing has started yet", ie.get_interaction("Ann") is None)
check("the ticker leaves a walker alone", ie.settle_approaches() == 0)
check("… and it is still an approach",
      ie.get_invite(iid9)["status"] == "approaching")
# Arrival: the journey ends, the next beat binds the pair.
cancel_journey("Bob")
set_character_pos("Bob", 10.0, 21.0)
check("on arrival the beat binds the pair", ie.settle_approaches() == 1)
check("both are in the clip now", ie.get_interaction("Ann") is not None
      and ie.get_interaction("Bob") is not None)
check("the invitation is spent", ie.get_invite(iid9)["status"] == "accepted")

# Called off mid-walk: the trip goes with the invitation — it only existed
# to make that pair possible.
ie.end_interaction("Ann")
for _n in ("Ann", "Bob"):
    ie.clear_invites_for(_n)
    clear_pose_intent(_n)
set_character_pos("Bob", 10.0, 28.0)
iid10 = ie.create_invite("Ann", "Bob", "embracing")
check("… the walk starts again",
      ie.resolve_invite(iid10, True)["status"] == "approaching")
check("calling it off works", ie.cancel_invite(iid10))
check("… and stops the walk", get_journey("Bob") is None)
check("… and cannot be done twice", ie.cancel_invite(iid10) is False)

# Walked all the way and the other one is gone: the approach dies, it does
# not follow them across the world.
for _n in ("Ann", "Bob"):
    ie.clear_invites_for(_n)
set_character_pos("Bob", 10.0, 28.0)
iid11 = ie.create_invite("Ann", "Bob", "embracing")
ie.resolve_invite(iid11, True)
cancel_journey("Bob")                      # the walk ended…
check("arrived but still too far: the approach is over",
      ie.settle_approaches() == 0
      and ie.get_invite(iid11)["status"] == "stale")
check("… and nothing started", ie.get_interaction("Bob") is None)
ie.clear_invites_for("Ann")
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)

# describe(): a pair pose without its partner reads as a solo pose.
set_character_pos("Ann", 10.0, 20.0)
set_character_pos("Bob", 10.0, 24.0)
ie.start_interaction("Ann", "Bob", "embracing")
check("describe names the partner", ie.describe("Ann") == "embracing with Bob",
      ie.describe("Ann"))
check("… from both sides", ie.describe("Bob") == "embracing with Ann")
ie.end_interaction("Ann")
check("and is empty without a pair", ie.describe("Ann") == "")


print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
