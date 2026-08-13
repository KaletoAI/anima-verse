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
  [8] ONE key inside `meta` is whitelisted again since finding 3 of the E8
      acceptance: `move_anim`, the clip a MOVING figure plays on this
      ground instead of walk/run. It is a clip kind out of an OPEN
      vocabulary, so nothing is checked against a list — only the shape:
        "  swim  "        -> "swim"          (trimmed)
        "s" * 45          -> "s" * 40        (a kind is 40 chars, no more)
        ""  /  "   "      -> the KEY IS GONE, never an empty string
        41 chars of blanks around a 3-letter word -> the word
        no `move_anim` at all -> untouched, and the other keys with it
      Water carries it in the shared seed: `{"move_anim": "swim"}` with
      `speed_factor 0.4` — the ground one wades through.

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
check("water carries it in the shared seed",
      (terrain_types.get_type("water") or {}).get("meta"),
      {"move_anim": "swim"})
check("...at the pace of a ground one wades through",
      (terrain_types.get_type("water") or {}).get("speed_factor"), 0.4)
check("...and it is walked into, not refused",
      (terrain_types.get_type("water") or {}).get("passable"), True)
check("the barrier kind carries the same clip and pace",
      ((terrain_types.get_type("deep_water") or {}).get("meta"),
       (terrain_types.get_type("deep_water") or {}).get("speed_factor")),
      ({"move_anim": "swim"}, 0.4))

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
