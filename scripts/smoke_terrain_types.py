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
  [8b] TWO MORE clip-side meta keys since the same evening, and they are two
      on purpose (finding 13): `move_sink_m` and `idle_sink_m`, how deep a
      figure stands IN this ground while it MOVES over it and while it WAITS
      on it. One number could not serve both poses — a swimmer lies flat and
      its lowest point is a knee just under the body, a treader hangs upright
      and its lowest point is a foot a body length down — so the ground says
      both and the renderer picks. Same numeric shape rule
      (`_clamped_meta_number`) for each, clamp 0…1.5:
        0.35 / 1.3 -> unchanged   the seed values of water (move / idle)
        0.05       -> 0.05     there is no lower limit but 0 — a hand's depth
                               is a legal depth
        0.4449     -> 0.44     two decimals, the editor's precision
        9          -> 1.5      a body length and a half; deeper is under the
                               ground rather than in it
        0 / −1 / "deep" / NaN / "" -> the KEY IS GONE (0 = no sinking, and
                               that is written by leaving the key out)
      THE ROUNDING EDGE (review 2026-08-13, closed with this round): a depth
      that only rounds to nothing says nothing either. The lower clamp of
      these two keys is 0, so a value under half a centimetre survived the
      "> 0" test and was then stored AS 0.0 — the "authored as 0" the shape
      rule exists to make impossible.
        0.004      -> the KEY IS GONE (0.004 -> round 2 -> 0.0)
        0.0049     -> the KEY IS GONE (the last value under the line)
        0.005      -> 0.01     the first one that rounds to something
      The relief keys cannot reach it: their lower clamps (0.05 / 4) are
      themselves positive, so no clamped value can round down to 0.
      Water carries `move_sink_m: 0.35` and `idle_sink_m: 1.3` in the shared
      seed, next to its two clips; `deep_water` carries neither — nobody
      stands in a barrier, and nobody waits in one.
      `sink_m` is GONE, without an alias: the key was one day old, and a
      stored one is a dead free-form key nothing reads (checked below).

  [9] TWO MORE whitelisted meta keys since the micro-relief decision
      (2026-08-13): `relief_amplitude_m` and `relief_wave_m`, the random
      small hills the world heightfield bakes in wherever this kind is
      painted (§ A16.2). Same shape rule as `move_anim` — a value that says
      nothing leaves NO key behind — plus CLAMPS, because a slip should move
      the ground to the limit rather than lose the entry:
        amplitude 0.4      -> 0.4          (the authored case)
        amplitude 99       -> 2.0          the walkability limit: two
                                           neighbouring support points differ
                                           by at most 2·amp over one grid step,
                                           atan(2·2/2) = 63 deg on the 2 m tile
                                           grid the rules read (45 deg while
                                           that step was 4 m)
        amplitude 0.001    -> 0.05         below this nothing is visible
        amplitude 0.4449   -> 0.44         two decimals, the editor's precision
        amplitude 0 / −1 / "much" / NaN / "" -> the KEY IS GONE
        wave 2             -> 4.0          NYQUIST: 2 × the 2 m TILE step, a
                                           wave the grid cannot carry at all
                                           (the floor halved with the step on
                                           2026-08-14)
        wave 999           -> 200.0
        wave 0 / junk      -> the KEY IS GONE (and the reader then uses 32 m)
      The keys are independent: a wave without an amplitude survives as a
      number and simply means nothing, and neither key disturbs `move_anim`
      or any free-form neighbour.

  [10] ONE MORE since the terrain animations (2026-08-14): `sway_m`, how far
      what GROWS on this ground bends in the wind — the maximum sideways
      deflection of a blade's tip, in metres (§ A9). Same numeric shape rule,
      clamp 0.01…0.5:
        0.06 / 0.04   -> unchanged   the seed values of grass and forest
        0.9           -> 0.5         a hand's breadth and a half; further is
                                     shearing, not bending
        0.0649        -> 0.06        two decimals, the editor's precision
        0 / −1 / "windy" / NaN / "" -> the KEY IS GONE (a ground that says
                                     nothing lets nothing wave)
      THE ROUNDING EDGE reads the other way round here, and that is the point
      of checking it: the lower clamp is 0.01, which is itself positive, so a
      value under it is LIFTED to the smallest visible sway instead of being
      dropped the way a 0.004 sink depth is. Nothing can round to a stored 0.
        0.004         -> 0.01        clamped up, then rounded — a key, not a 0
      Saat: `grass` 0.06 and `forest` 0.04 carry it in the shared seed, water
      and the rest carry none. The key is independent of every other one.

  [11] ONE MORE since the undergrowth decision (2026-08-15): `undergrowth`,
      how much grows on this ground WITHOUT anybody authoring a scatter row —
      a SHARE of the client's full tuft density (§ A9), not a count and not a
      list of props. Same numeric shape rule, clamp 0…1:
        0.6 / 0.3     -> unchanged   the seed values of forest and grass
        5             -> 1.0         a share cannot be more than all of it
        0.4449        -> 0.44        two decimals, the editor's precision
        0 / −1 / "dense" / NaN / "" -> the KEY IS GONE (bare ground is
                                     written by leaving the key out)
      THE ROUNDING EDGE reads like the SINK depths and not like `sway_m`: the
      lower clamp is 0, which is itself nothing, so a value that only rounds to
      zero has to leave no key behind rather than be lifted to a floor.
        0.004         -> the KEY IS GONE (rounds to 0.0)
        0.005         -> 0.01        the first share that rounds to something
      Saat: exactly `forest` 0.6 and `grass` 0.3 carry it — a wood is
      undergrown because it is a wood, a path is not. The key is independent of
      every other one and survives the save/read round trip.

  [12] WHICH SURFACE A KIND WEARS IS SAID, NOT GUESSED (2026-08-16).
      `surface` names the kind of the surface-texture library that skins this
      ground. It is a key of the ENTRY (not of `meta`) and follows the shape
      rule of the clip keys letter for letter:
        "  grass  "   -> "grass"    (trimmed)
        "g" * 45      -> "g" * 40   (40 characters like a `kind`)
        "" / "   "    -> the KEY IS GONE, never an empty string
        no key at all -> no key in the result either
      NOTHING is validated against the library on save: the library grows a
      texture tomorrow that an author wants to name today, so an unknown id
      is stored verbatim (the admin tab flags it — the LoRA "(missing)"
      pattern).
      Saat: exactly the five kinds the library holds under their own name
      carry the assignment — grass, forest, sand, water, deep_water map to
      themselves; `path` and `rock` carry NONE (the library has no entry of
      either name, so the old rule never dressed them either).
      Payload: `GET /play/terrain` types[] carries the field through
      verbatim — the clients read it and nothing else.
      Round trip: a world row stores and returns it; an empty one stores
      nothing and the entry comes back without the key.

 [12b] THE MIGRATION, on a throwaway world (`terrain_surface_migration`).
      Bestandswelten must not be undressed by dropping the name match, so
      the assignment the old rule DERIVED is written out once:
        row "moor" (no surface) + library holding "moor"  -> surface "moor"
        row "bog"  (no surface) + library NOT holding it  -> still no key
        row "fen"  with surface "dark_stone" already set  -> untouched
                   (the field is the author's, a repair never overwrites it)
      Idempotence is the world_kv marker, not the content: a SECOND call
      returns {} and leaves a row added afterwards alone.
      THE RED COUNTER-CHECK — the name fallback is really dead: that row
      added afterwards is called "heath", the library holds "heath", and the
      catalog answers NO surface for it. Under the old rule it would have
      worn the heath texture; now nothing anywhere re-derives the name, so
      it renders the default ground until an author says otherwise.

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
# Since "Ein Boden" E1 (§ G4) both water kinds also carry the WATER FLAG —
# ``meta.water``, the one thing that makes the bake carve a bed under an area
# painted with them. It is a flag on the TYPE and never a match on the NAME:
# kinds are an open vocabulary, so a world whose lakes are called "lagoon"
# carves exactly like this one.
check("water carries both clips in the shared seed — plus its two sink depths"
      " and the water flag",
      (terrain_types.get_type("water") or {}).get("meta"),
      {"water": True, "move_anim": "swim", "idle_anim": "treading-water",
       "move_sink_m": 0.35, "idle_sink_m": 1.3})
check("...so is_water_kind says yes for it",
      terrain_types.is_water_kind("water"), True)
check("...and no for the meadow next to it",
      terrain_types.is_water_kind("grass"), False)
check("...and no for a kind the catalog does not know",
      terrain_types.is_water_kind("lagoon"), False)
check("the flag is coerced to a plain bool on write",
      meta_of({"water": "yes"}), {"water": True})
check("...and a false one is kept as the explicit 'not water'",
      meta_of({"water": 0}), {"water": False})
check("...at the pace of a ground one wades through",
      (terrain_types.get_type("water") or {}).get("speed_factor"), 0.4)
check("...and it is walked into, not refused",
      (terrain_types.get_type("water") or {}).get("passable"), True)
check("the barrier kind carries the same MOVE clip and pace — and no idle "
      "one, nobody stands in it",
      ((terrain_types.get_type("deep_water") or {}).get("meta"),
       (terrain_types.get_type("deep_water") or {}).get("speed_factor")),
      ({"water": True, "move_anim": "swim"}, 0.4))

print("[8b] the two sink depths — how deep one stands IN the ground")
check("the moving depth of water survives", meta_of({"move_sink_m": 0.35}),
      {"move_sink_m": 0.35})
check("...and the waiting one, which is a different number",
      meta_of({"idle_sink_m": 1.3}), {"idle_sink_m": 1.3})
for _key in ("move_sink_m", "idle_sink_m"):
    check(f"[{_key}] a hand's depth is a legal depth (no lower limit but 0)",
          meta_of({_key: 0.05}), {_key: 0.05})
    check(f"[{_key}] ...rounded to two decimals", meta_of({_key: 0.4449}),
          {_key: 0.44})
    check(f"[{_key}] deeper than a body and a half is clamped",
          meta_of({_key: 9}), {_key: 1.5})
    check(f"[{_key}] a zero depth leaves no key behind", meta_of({_key: 0}), {})
    check(f"[{_key}] ...and neither does a negative one",
          meta_of({_key: -1}), {})
    check(f"[{_key}] ...nor junk", meta_of({_key: "deep"}), {})
    check(f"[{_key}] ...nor NaN", meta_of({_key: float("nan")}), {})
    check(f"[{_key}] ...nor an empty string", meta_of({_key: ""}), {})
    # THE ROUNDING EDGE: the "> 0" test alone let these through and the
    # rounding then stored the 0 the rule forbids.
    check(f"[{_key}] a depth that only rounds to nothing leaves no key",
          meta_of({_key: 0.004}), {})
    check(f"[{_key}] ...up to the last value under the line",
          meta_of({_key: 0.0049}), {})
    check(f"[{_key}] ...while the first one that rounds to something stays",
          meta_of({_key: 0.005}), {_key: 0.01})
check("the two are independent, and travel with the clips and a neighbour",
      meta_of({"move_anim": " swim ", "idle_anim": " treading-water ",
               "move_sink_m": 0.35, "idle_sink_m": 1.3, "note": "x"}),
      {"move_anim": "swim", "idle_anim": "treading-water",
       "move_sink_m": 0.35, "idle_sink_m": 1.3, "note": "x"})
check("a ground may sink a walker without naming a clip",
      meta_of({"move_sink_m": 0.2}), {"move_sink_m": 0.2})
# `sink_m` is GONE and has NO alias (the key was one day old). A stored one is
# a free-form key like any other: it survives the sanitizer untouched — and
# means nothing to anybody, which is what the report tells the user.
check("the replaced sink_m is no longer read, only carried",
      meta_of({"sink_m": 0.4}), {"sink_m": 0.4})
check("...and it does NOT become one of the two new depths",
      meta_of({"sink_m": 0.4}).get("move_sink_m"), None)
terrain_types.save_world_type(
    {"kind": "bog", "name": "Bog", "color": "#5b4a2f",
     "meta": {"move_sink_m": 0.3, "idle_sink_m": 0.6}})
check("both survive the save/read round trip",
      (terrain_types.get_type("bog") or {}).get("meta"),
      {"move_sink_m": 0.3, "idle_sink_m": 0.6})
terrain_types.delete_world_type("bog")
check("the barrier kind has neither — nobody stands or waits in it",
      [k for k in ("move_sink_m", "idle_sink_m")
       if k in ((terrain_types.get_type("deep_water") or {}).get("meta") or {})],
      [])

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
      meta_of({"relief_wave_m": 2}), {"relief_wave_m": 4.0})
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

print("[10] the sway of what grows on a ground")
check("the authored deflection of grass survives", meta_of({"sway_m": 0.06}),
      {"sway_m": 0.06})
check("...and the gentler one of a wood", meta_of({"sway_m": 0.04}),
      {"sway_m": 0.04})
check("a wind that would shear the meadow is clamped",
      meta_of({"sway_m": 0.9}), {"sway_m": 0.5})
check("...and rounded to two decimals", meta_of({"sway_m": 0.0649}),
      {"sway_m": 0.06})
# THE ROUNDING EDGE, the other way round: the lower clamp is positive, so a
# value under it is lifted rather than dropped — no `sway_m` can be stored 0.
check("a deflection under the smallest visible one is lifted to it",
      meta_of({"sway_m": 0.004}), {"sway_m": 0.01})
check("a zero sway leaves no key behind", meta_of({"sway_m": 0}), {})
check("...and neither does a negative one", meta_of({"sway_m": -1}), {})
check("...nor junk", meta_of({"sway_m": "windy"}), {})
check("...nor NaN", meta_of({"sway_m": float("nan")}), {})
check("...nor an empty string", meta_of({"sway_m": ""}), {})
check("it travels with the relief, a clip and a free-form neighbour",
      meta_of({"sway_m": 0.06, "relief_amplitude_m": 0.4,
               "move_anim": " swim ", "note": "x"}),
      {"sway_m": 0.06, "relief_amplitude_m": 0.4,
       "move_anim": "swim", "note": "x"})
_seeded = {k: (e.get("meta") or {}).get("sway_m")
           for k, e in terrain_types.effective_catalog().items()
           if (e.get("meta") or {}).get("sway_m")}
check("exactly grass and forest wave in the shared seed", _seeded,
      {"grass": 0.06, "forest": 0.04})
terrain_types.save_world_type(
    {"kind": "reed", "name": "Reed", "color": "#8ab17d",
     "meta": {"sway_m": 0.2}})
check("it survives the save/read round trip",
      (terrain_types.get_type("reed") or {}).get("meta"), {"sway_m": 0.2})
terrain_types.delete_world_type("reed")

print("[11] what a ground grows all by itself")
check("the authored share of a wood survives", meta_of({"undergrowth": 0.6}),
      {"undergrowth": 0.6})
check("...and the thinner one of a meadow", meta_of({"undergrowth": 0.3}),
      {"undergrowth": 0.3})
check("a share of more than everything is clamped to all of it",
      meta_of({"undergrowth": 5}), {"undergrowth": 1.0})
check("...and rounded to two decimals", meta_of({"undergrowth": 0.4449}),
      {"undergrowth": 0.44})
check("a zero share leaves no key behind (bare ground)",
      meta_of({"undergrowth": 0}), {})
check("...and neither does a negative one", meta_of({"undergrowth": -1}), {})
check("...nor junk", meta_of({"undergrowth": "dense"}), {})
check("...nor NaN", meta_of({"undergrowth": float("nan")}), {})
check("...nor an empty string", meta_of({"undergrowth": ""}), {})
# THE ROUNDING EDGE, the sink-depth way round: the lower clamp is 0 itself, so
# a share under half a hundredth must leave NO key rather than be lifted.
check("a share that only rounds to nothing leaves no key",
      meta_of({"undergrowth": 0.004}), {})
check("...while the first one that rounds to something stays",
      meta_of({"undergrowth": 0.005}), {"undergrowth": 0.01})
check("it travels with the wind, the relief and a free-form neighbour",
      meta_of({"undergrowth": 0.6, "sway_m": 0.04,
               "relief_amplitude_m": 0.4, "note": "x"}),
      {"undergrowth": 0.6, "sway_m": 0.04,
       "relief_amplitude_m": 0.4, "note": "x"})
_grown = {k: (e.get("meta") or {}).get("undergrowth")
          for k, e in terrain_types.effective_catalog().items()
          if (e.get("meta") or {}).get("undergrowth")}
check("exactly forest and grass are undergrown in the shared seed", _grown,
      {"forest": 0.6, "grass": 0.3})
terrain_types.save_world_type(
    {"kind": "thicket", "name": "Thicket", "color": "#2f5d3a",
     "meta": {"undergrowth": 0.9}})
check("it survives the save/read round trip",
      (terrain_types.get_type("thicket") or {}).get("meta"),
      {"undergrowth": 0.9})
terrain_types.delete_world_type("thicket")

print("[12] the surface a kind wears, said out loud")


def surface_of(raw):
    """`surface` as the sanitizer leaves it — the key or its absence."""
    entry = terrain_types.sanitize_type({"kind": "meadow", **raw})
    return entry.get("surface", "<no key>")


check("an assignment is trimmed", surface_of({"surface": "  grass  "}), "grass")
check("...and capped at 40 characters like a kind",
      surface_of({"surface": "g" * 45}), "g" * 40)
check("an empty assignment leaves no key behind",
      surface_of({"surface": ""}), "<no key>")
check("...and neither do blanks", surface_of({"surface": "   "}), "<no key>")
check("...nor no key at all", surface_of({}), "<no key>")
# The library is a living thing: a texture generated tomorrow must be
# nameable today, so a save NEVER checks the id against it.
check("an id the library does not hold is stored verbatim",
      surface_of({"surface": "not_generated_yet"}), "not_generated_yet")
check("it lives on the ENTRY, not in meta",
      terrain_types.sanitize_type(
          {"kind": "meadow", "surface": "grass"})["meta"], {})

_seed = {k: terrain_types.effective_catalog()[k].get("surface", "<no key>")
         for k in sorted(SHARED_KINDS)}
check("the seed names its materials explicitly", _seed,
      {"deep_water": "deep_water", "forest": "forest", "grass": "grass",
       "path": "<no key>", "rock": "<no key>", "sand": "sand",
       "water": "water"})

terrain_types.save_world_type(
    {"kind": "clay", "name": "Clay", "color": "#a9744f",
     "surface": "dark_stone"})
check("it survives the save/read round trip",
      (terrain_types.get_type("clay") or {}).get("surface"), "dark_stone")
terrain_types.save_world_type(
    {"kind": "clay", "name": "Clay", "color": "#a9744f", "surface": ""})
check("...and clearing it leaves no key",
      (terrain_types.get_type("clay") or {}).get("surface", "<no key>"),
      "<no key>")
terrain_types.delete_world_type("clay")

from app.routes.play import get_terrain_route  # noqa: E402
_payload_types = {t["kind"]: t.get("surface", "<no key>")
                  for t in get_terrain_route(user=None)["types"]}
check("/play/terrain carries the assignment of grass",
      _payload_types.get("grass"), "grass")
check("...and the missing one of a path", _payload_types.get("path"),
      "<no key>")

print("[12b] the boot migration writes what the name match derived")
from app.core import terrain_surface_migration as tsm  # noqa: E402
from app.models.world import get_world_setting  # noqa: E402

for _kind in ("moor", "bog"):
    terrain_types.save_world_type({"kind": _kind, "name": _kind.title(),
                                   "color": "#556b2f"})
terrain_types.save_world_type({"kind": "fen", "name": "Fen",
                               "color": "#556b2f", "surface": "dark_stone"})
check("the marker is unset before the run",
      bool(get_world_setting("migrated_terrain_surface_v1")), False)
# A library of exactly two ids: "moor" is held under its own name, "bog" is
# not — the two sides of the rule the migration reproduces. "fen" is held as
# well and must STILL be left alone, because it already has an answer.
_stats = tsm.migrate_terrain_surfaces_once({"moor", "fen", "heath"})
check("exactly the one row the old rule dressed is assigned",
      _stats.get("assigned"), 1)
check("a kind the library holds under its own name gets it",
      (terrain_types.get_type("moor") or {}).get("surface"), "moor")
check("a kind it does not hold gets nothing",
      (terrain_types.get_type("bog") or {}).get("surface", "<no key>"),
      "<no key>")
check("an authored assignment is never overwritten",
      (terrain_types.get_type("fen") or {}).get("surface"), "dark_stone")
check("the marker is set after the run",
      get_world_setting("migrated_terrain_surface_v1"), "1")

# THE RED COUNTER-CHECK: a row created AFTER the migration, whose kind the
# library holds under exactly that name. Under the old rule it would have worn
# that texture; nothing derives it any more.
terrain_types.save_world_type({"kind": "heath", "name": "Heath",
                               "color": "#8a9a5b"})
check("a second run is a no-op (the marker, not the content)",
      tsm.migrate_terrain_surfaces_once({"moor", "fen", "heath"}), {})
check("...and the name match is dead: a same-named library id dresses nobody",
      (terrain_types.get_type("heath") or {}).get("surface", "<no key>"),
      "<no key>")
for _kind in ("moor", "bog", "fen", "heath"):
    terrain_types.delete_world_type(_kind)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
