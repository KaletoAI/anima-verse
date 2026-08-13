#!/usr/bin/env python3
"""Smoke run for the terrain-type catalog (Seamless World, E1 Task 3).

Throwaway storage. Hand-derived expectations:

  [1] Fresh world: effective_catalog() contains at least the seven shared
      kinds; grass is passable with speed_factor 1.0; `water` is SWIMMABLE
      (round 2 of the E8 acceptance — swimming is what move_anim is for)
      while the barrier kind `deep_water` carries the same 0.4 and the same
      swim clip at `passable: false`. sources say "shared" for grass.
  [2] save_world_type({kind: "grass", name: "Dry Grass", color: "#aaaa00",
      passable: True, speed_factor: 0.9}) -> effective grass has name
      "Dry Grass" AND speed_factor 0.9. Override REPLACES the shared entry
      (no deep merge): the world entry's values win entirely.
  [3] save_world_type({kind: "lava", ...passable False}) -> a brand-new
      world-only kind appears; source "world".
  [4] delete_world_type("grass") -> shared grass is back (speed 1.0).
      delete_world_type("grass") again -> False (nothing to delete).
      Shared entries themselves are never deletable.
  [5] Sanitizer: kind "Bad Kind!" -> ValueError; speed_factor 99 clamps
      to 2.0; speed_factor -1 clamps to 0.0; color "xyz" -> ValueError;
      a non-dict meta is dropped to {}.
  [6] Non-finite speed: "nan", inf and -inf all fall back to 1.0. A clamp
      alone does NOT catch NaN (every NaN comparison is False, so min/max
      pass it through) — hence the explicit isfinite guard. The catalog
      must therefore stay encodable with allow_nan=False, which is what
      Starlette uses: a single NaN would 500 the whole endpoint.
  [7] `meta` stays FREE-FORM. The scatter whitelist that used to live
      here moved to the AREA with finding B17 (see
      scripts/smoke_terrain_areas.py [11]) — the type-level field was
      removed without a shim, so a `meta` handed to sanitize_type now
      survives verbatim, scatter-shaped keys included.
  [8] TWO keys inside `meta` are whitelisted as CLIPS: `move_anim` (finding
      3 of the E8 acceptance), what a MOVING figure plays on this ground
      instead of walk/run, and `idle_anim` (the water round of 2026-08-13),
      what it plays STANDING there instead of its idle. Both are clip kinds
      out of an OPEN vocabulary, so nothing is checked against a list — only
      the shape, and it is the SAME shape rule for both:
        "  swim  "        -> "swim"          (trimmed)
        "s" * 45          -> "s" * 40        (a kind is 40 chars, no more)
        ""  /  "   "      -> the KEY IS GONE, never an empty string
        41 chars of blanks around a 3-letter word -> the word
        no `move_anim` at all -> untouched, and the other keys with it
      Water carries both in the shared seed:
      `{"move_anim": "swim", "idle_anim": "treading-water"}` with
      `speed_factor 0.4` — the ground one wades through and treads water in.
      `deep_water` is the barrier kind: same swim clip, no idle one, because
      nobody stands in it (`passable: false`).
  [9] TWO MORE whitelisted meta keys since the micro-relief decision
      (2026-08-13): `relief_amplitude_m` and `relief_wave_m`, the random
      small hills the world heightfield bakes in wherever this kind is
      painted (§ A16.2). Same shape rule as `move_anim` — a value that says
      nothing leaves NO key behind — plus CLAMPS, because a slip should move
      the ground to the limit rather than lose the entry:
        amplitude 0.4      -> 0.4          (the authored case)
        amplitude 99       -> 2.0          the walkability limit: two
                                           neighbouring support points differ
                                           by at most 2·amp over one 4 m step,
                                           atan(2·2/4) = 45 deg
        amplitude 0.001    -> 0.05         below this nothing is visible
        amplitude 0.4449   -> 0.44         two decimals, the editor's precision
        amplitude 0 / −1 / "much" / NaN / "" -> the KEY IS GONE
        wave 2             -> 8.0          NYQUIST: 2 × the 4 m raster step, a
                                           wave the grid cannot carry at all
        wave 999           -> 200.0
        wave 0 / junk      -> the KEY IS GONE (and the reader then uses 32 m)
      The keys are independent: a wave without an amplitude survives as a
      number and simply means nothing, and neither key disturbs `move_anim`
      or any free-form neighbour.

Usage:  ./.venv/bin/python scripts/smoke_terrain_types.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="terrain-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="terrain-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import terrain_types  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


print("[1] fresh world serves the shared seed")
cat = terrain_types.effective_catalog()
SHARED_KINDS = {"grass", "forest", "sand", "path", "water", "deep_water",
                "rock"}
check("seven shared kinds present", SHARED_KINDS <= set(cat), True)
check("grass passable", cat["grass"]["passable"], True)
check("grass speed", cat["grass"]["speed_factor"], 1.0)
check("water is swum, not blocked", cat["water"]["passable"], True)
check("...a wall of water is its own kind", cat["deep_water"]["passable"], False)
check("grass source", terrain_types.sources().get("grass"), "shared")

print("[2] world override REPLACES the shared entry")
terrain_types.save_world_type({"kind": "grass", "name": "Dry Grass",
                               "color": "#aaaa00", "passable": True,
                               "speed_factor": 0.9})
cat = terrain_types.effective_catalog()
check("grass name", cat["grass"]["name"], "Dry Grass")
check("grass speed", cat["grass"]["speed_factor"], 0.9)
check("grass color", cat["grass"]["color"], "#aaaa00")
check("grass source", terrain_types.sources().get("grass"), "world")

print("[3] a brand-new world-only kind")
terrain_types.save_world_type({"kind": "lava", "name": "Lava",
                               "color": "#d62828", "passable": False,
                               "speed_factor": 0.0})
cat = terrain_types.effective_catalog()
check("lava present", "lava" in cat, True)
check("lava impassable", cat["lava"]["passable"], False)
check("lava source", terrain_types.sources().get("lava"), "world")
check("get_type lava", (terrain_types.get_type("lava") or {}).get("name"), "Lava")

print("[4] deleting the override brings the shared entry back")
check("delete grass", terrain_types.delete_world_type("grass"), True)
cat = terrain_types.effective_catalog()
check("grass back to shared speed", cat["grass"]["speed_factor"], 1.0)
check("grass name back", cat["grass"]["name"], "Grass")
check("grass source", terrain_types.sources().get("grass"), "shared")
check("delete grass again", terrain_types.delete_world_type("grass"), False)
check("shared grass still there", "grass" in terrain_types.effective_catalog(), True)

print("[5] sanitizer")
raised = False
try:
    terrain_types.sanitize_type({"kind": "Bad Kind!", "name": "x"})
except ValueError:
    raised = True
check("bad kind raises", raised, True)

check("speed 99 clamps",
      terrain_types.sanitize_type({"kind": "hot", "speed_factor": 99})["speed_factor"],
      2.0)
check("speed -1 clamps",
      terrain_types.sanitize_type({"kind": "tar", "speed_factor": -1})["speed_factor"],
      0.0)

raised = False
try:
    terrain_types.sanitize_type({"kind": "mud", "color": "xyz"})
except ValueError:
    raised = True
check("bad color raises", raised, True)

check("non-dict meta dropped",
      terrain_types.sanitize_type({"kind": "mud", "meta": "nope"})["meta"], {})

print("[6] non-finite speed never survives the clamp")
check("nan -> default",
      terrain_types.sanitize_type({"kind": "mud", "speed_factor": "nan"})["speed_factor"],
      1.0)
check("inf -> default",
      terrain_types.sanitize_type({"kind": "mud", "speed_factor": float("inf")})["speed_factor"],
      1.0)
check("-inf -> default",
      terrain_types.sanitize_type({"kind": "mud", "speed_factor": float("-inf")})["speed_factor"],
      1.0)
# The catalog must stay renderable by a strict JSON encoder: Starlette uses
# allow_nan=False, so ONE NaN in the catalog 500s the whole endpoint.
terrain_types.save_world_type({"kind": "mud", "name": "Mud", "speed_factor": "nan"})
check("catalog renders under allow_nan=False",
      bool(json.dumps(terrain_types.effective_catalog(), allow_nan=False)), True)
terrain_types.delete_world_type("mud")

print("[7] meta stays free-form (the scatter whitelist moved to the area)")


def meta_of(meta):
    return terrain_types.sanitize_type({"kind": "meadow", "meta": meta})["meta"]


check("a scatter-shaped key is no longer whitelisted, only carried",
      meta_of({"scatter": {"density_per_100m2": "lots", "colour": "red"}}),
      {"scatter": {"density_per_100m2": "lots", "colour": "red"}})
check("a non-dict meta is still dropped to {}", meta_of("nope"), {})
check("foreign keys survive", meta_of({"foo": 1, "bar": [2]}),
      {"foo": 1, "bar": [2]})

terrain_types.save_world_type(
    {"kind": "meadow", "name": "Meadow", "color": "#7ac74f",
     "meta": {"note": "free form", "n": 3}})
check("meta survives the save/read round trip",
      (terrain_types.get_type("meadow") or {}).get("meta"),
      {"note": "free form", "n": 3})
terrain_types.delete_world_type("meadow")

print("[8] move_anim is the one whitelisted meta key")
check("a move_anim is trimmed", meta_of({"move_anim": "  swim  "}),
      {"move_anim": "swim"})
check("...and capped at 40 characters",
      meta_of({"move_anim": "s" * 45}), {"move_anim": "s" * 40})
check("an empty one leaves no key behind", meta_of({"move_anim": ""}), {})
check("...and neither does a blank one", meta_of({"move_anim": "   "}), {})
check("blanks around a real value keep the value",
      meta_of({"move_anim": " " * 20 + "fly" + " " * 21}), {"move_anim": "fly"})
check("a meta without it is untouched", meta_of({"note": "free form"}),
      {"note": "free form"})
check("...and the neighbours of a move_anim survive",
      meta_of({"move_anim": " crawl ", "note": "x"}),
      {"move_anim": "crawl", "note": "x"})
check("an idle_anim follows the same shape rule",
      meta_of({"idle_anim": "  treading-water  "}),
      {"idle_anim": "treading-water"})
check("...capped at 40 characters too",
      meta_of({"idle_anim": "t" * 45}), {"idle_anim": "t" * 40})
check("...and an empty one leaves no key behind either",
      meta_of({"idle_anim": "   "}), {})
check("the two are independent, and neighbours survive both",
      meta_of({"move_anim": " swim ", "idle_anim": " treading-water ",
               "note": "x"}),
      {"move_anim": "swim", "idle_anim": "treading-water", "note": "x"})
check("water carries both in the shared seed",
      (terrain_types.get_type("water") or {}).get("meta"),
      {"move_anim": "swim", "idle_anim": "treading-water"})
check("...at the pace of a ground one wades through",
      (terrain_types.get_type("water") or {}).get("speed_factor"), 0.4)
check("...and it is walked into, not refused",
      (terrain_types.get_type("water") or {}).get("passable"), True)
check("the barrier kind carries the same MOVE clip and pace — and no idle "
      "one, nobody stands in it",
      ((terrain_types.get_type("deep_water") or {}).get("meta"),
       (terrain_types.get_type("deep_water") or {}).get("speed_factor")),
      ({"move_anim": "swim"}, 0.4))

print("[9] the micro-relief keys")
check("an authored amplitude survives", meta_of({"relief_amplitude_m": 0.4}),
      {"relief_amplitude_m": 0.4})
check("...clamped at the walkability limit",
      meta_of({"relief_amplitude_m": 99}), {"relief_amplitude_m": 2.0})
check("...and up to the smallest visible swing",
      meta_of({"relief_amplitude_m": 0.001}), {"relief_amplitude_m": 0.05})
check("...rounded to two decimals",
      meta_of({"relief_amplitude_m": 0.4449}), {"relief_amplitude_m": 0.44})
check("a zero amplitude leaves no key behind",
      meta_of({"relief_amplitude_m": 0}), {})
check("...and neither does a negative one",
      meta_of({"relief_amplitude_m": -1}), {})
check("...nor junk", meta_of({"relief_amplitude_m": "much"}), {})
check("...nor NaN", meta_of({"relief_amplitude_m": float("nan")}), {})
check("...nor an empty string", meta_of({"relief_amplitude_m": ""}), {})
check("a wave shorter than two support points is clamped (Nyquist)",
      meta_of({"relief_wave_m": 2}), {"relief_wave_m": 8.0})
check("...and a huge one to the upper limit",
      meta_of({"relief_wave_m": 999}), {"relief_wave_m": 200.0})
check("a zero wave leaves no key behind (the reader uses 32 m)",
      meta_of({"relief_wave_m": 0}), {})
check("...and neither does junk", meta_of({"relief_wave_m": "wide"}), {})
check("both together, with a neighbour and a move_anim",
      meta_of({"relief_amplitude_m": 0.4, "relief_wave_m": 32,
               "move_anim": " swim ", "note": "x"}),
      {"relief_amplitude_m": 0.4, "relief_wave_m": 32.0,
       "move_anim": "swim", "note": "x"})
check("a meta without them is untouched", meta_of({"note": "free form"}),
      {"note": "free form"})
terrain_types.save_world_type(
    {"kind": "meadow", "name": "Meadow", "color": "#7ac74f",
     "meta": {"relief_amplitude_m": 0.4, "relief_wave_m": 32}})
check("they survive the save/read round trip",
      (terrain_types.get_type("meadow") or {}).get("meta"),
      {"relief_amplitude_m": 0.4, "relief_wave_m": 32.0})
terrain_types.delete_world_type("meadow")
check("no shared kind carries a relief by default",
      [k for k, e in terrain_types.effective_catalog().items()
       if (e.get("meta") or {}).get("relief_amplitude_m")], [])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
