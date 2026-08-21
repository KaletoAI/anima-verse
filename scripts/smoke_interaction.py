#!/usr/bin/env python3
"""Smoke run for PAIR INTERACTIONS (app/core/interaction_engine.py).

Throwaway storage + throwaway clip directory — never touches a real world or
the real clip library. No server.

The clip convention the expectations are derived from (app/blender/scripts/
cmu_clip.py, docs/schnittstellen-3d.md § A8a): a pair clip's frame has its
origin at the ANCHOR and +X pointing from A to B; a client places a figure at
``anchor + R_y(yaw) · clip_root`` with three.js's Y rotation
(x' = x·cos + z·sin, z' = −x·sin + z·cos).

World: one location "Smoke Plaza" at (0, 0), width 10 m, both characters
inside it and in the same room. Game clock pinned (factor 0).

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
from app.core import pose_catalog  # noqa: E402
from app.core.animation_clips import pair_kinds  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import game_time, set_game_factor, set_game_time  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_pos, get_character_pose_key, get_character_profile,
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
(CAT / "pose_catalog.json").write_text(json.dumps({"entries": {
    "standing": {"prompt": "standing", "synonyms": [], "animation": "idle", "_default": True},
    "embracing": {"prompt": "two people hugging", "synonyms": ["hug"],
                  "animation": "hug", "solo": False},
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
        _loc.setdefault("map3d", {})["plan_width_m"] = 10.0
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
check("partner_poses lists embracing and swaying",
      sorted(ie.partner_poses()) == [("embracing", "hug"), ("swaying", "sway")], str(ie.partner_poses()))

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

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
