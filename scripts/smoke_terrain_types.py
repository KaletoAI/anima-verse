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
  [8c] ONE MORE, and it is what turns SWIMMING from a property of the KIND
      into one of the water DEPTH under the figure (W4c, 2026-08-23):
      `swim_from_m`. Until it existed, `move_anim: swim` played on every
      pixel of a water area, ankle-deep on the shore ramp included. From
      this depth on the two clips and the two depths of [8]/[8b] apply;
      shallower water is WADED — the figure keeps its own walk/run and
      standing clips, is not sunk at all and stands on the bed (the rule
      itself is the CLIENT's, `client3d/src/game/walk.wadeGate`, checked in
      `client3d/scripts/smoke_walk_math.mjs`; the server only carries the
      number). It does NOT share the shape rule of the two sinks: 0 IS A
      VALUE here — "swim from the very rim", i.e. the behaviour of every
      water kind before this round — so it clamps like `shore_ramp_m`
      instead of dropping the key, and only junk leaves nothing behind:
        1.0        -> 1.0     the seed value of `river` (and the default a
                              kind without the key gets, read by the client)
        0          -> 0.0     KEPT, unlike a sink of 0 — the pre-W4c water
        0.75       -> 0.75    ankle-to-knee water is authorable
        1.2349     -> 1.23    two decimals, the editor's precision
        99         -> 10.0    deeper than any authored water gets: past it
                              the threshold could never be reached and the
                              figure would wade across a sea
        −3         -> 0.0     clamped up, not dropped: "from the rim"
        "deep" / NaN / "" / None -> the KEY IS GONE (and the client then
                              reads its default metre)
      The seed's `river` carries it at 1.0 next to a 1.2 m depth and a 1.0 m
      shore ramp: a 6 m wide river reaches full depth over 4 m of its width,
      so the middle is swum and the two ramps are waded. `water` and
      `deep_water` name none — the open sea is deep everywhere it matters,
      and an absent key is the same metre.

  [9] THE MICRO-RELIEF IS GONE FROM THE KIND (decision 2026-08-23). Its two
      keys, `relief_amplitude_m` and `relief_wave_m`, were whitelisted here
      from 2026-08-13 until then, which made every meadow of a world exactly
      as bumpy as every other one. They belong to the painted AREA now
      (scripts/smoke_terrain_areas.py, § A16.2) and left this module WITHOUT
      a fallback: no clamp, no default, no reader.

      The DELETION PROOF is the same shape [7] uses for the scatter list that
      moved to the area: what a whitelist used to catch now travels through
      `meta` verbatim, because `meta` is free-form and a key nobody claims is
      just data.
        amplitude 99    -> 99      NOT the old clamp of 2.0
        amplitude 0     -> 0       NOT "the key is gone"
        wave 2          -> 2       NOT the old Nyquist floor of 4.0
        amplitude "much"-> "much"  NOT dropped as junk
      Asserted BY NAME as well: `RELIEF_AMPLITUDE_MIN`/`_MAX`,
      `RELIEF_WAVE_MIN`/`_MAX` and `DEFAULT_RELIEF_WAVE_M` do not exist in
      `terrain_types` any more — they live next to the area sanitizer that
      writes them (`models.terrain.RELIEF_*`).

      And the READER agrees, which is what makes the deletion real rather
      than cosmetic: an area painted with a kind whose row still carries the
      two numbers contributes NOTHING to `heightfield.relief_inputs` — the
      world stays flat until the AREA says otherwise.

      No shared seed kind carries either key.

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

  [13] THE RELIEF MIGRATION, on the same throwaway world
      (`terrain_relief_migration`). The kind lost the two micro-relief keys
      without a fallback reader ([9]), so an existing world would FLATTEN on
      the boot that dropped them. The value the old rule would have used is
      written into every painted area of that kind, once:
        kind "downs" (0.8 / 24), painted TWICE   -> BOTH areas carry 0.8 / 24
                   — which is the picture the one bumpy kind used to make, and
                   the two areas can now be told apart for the first time
        kind "moss" (1.5), area already at 0.1   -> the AREA keeps its 0.1
                   (its keys are the author's; a repair never overwrites one)
        kind "slab" (no relief)                  -> its area stays flat
      Then the kind rows lose the two keys AND NOTHING ELSE (a free-form
      `note` next to them survives).
      Idempotence is the world_kv marker, not the content: a second call
      returns None.
      THE PICTURE IS PRESERVED, asserted at the consumer: after the run
      `heightfield.relief_params` answers `(seed("downs"), 0.8, 24.0)` for
      both areas — the same seed, because the seed is still hashed from the
      KIND name, and the same two numbers the kind used to hand the bake.

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
from app.core import heightfield as hf  # noqa: E402
from app.models import terrain as terrain_store  # noqa: E402


def _square(x, z, size):
    """One axis-aligned square polygon — the fixture's only geometry."""
    return [[x, z], [x + size, z], [x + size, z + size], [x, z + size]]


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
SHARED_KINDS = {"grass", "forest", "sand", "path", "water", "river",
                "deep_water", "rock"}
check("eight shared kinds present", SHARED_KINDS <= set(cat), True)
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

print("[8c] swim_from_m — from which DEPTH the four above apply at all")
check("the river seed's threshold survives", meta_of({"swim_from_m": 1.0}),
      {"swim_from_m": 1.0})
check("A ZERO IS KEPT here, unlike a sink of 0 — swim from the very rim",
      meta_of({"swim_from_m": 0}), {"swim_from_m": 0.0})
check("...and a negative one is clamped up to it, never dropped",
      meta_of({"swim_from_m": -3}), {"swim_from_m": 0.0})
check("ankle-to-knee water is authorable", meta_of({"swim_from_m": 0.75}),
      {"swim_from_m": 0.75})
check("...rounded to two decimals", meta_of({"swim_from_m": 1.2349}),
      {"swim_from_m": 1.23})
check("deeper than any authored water is clamped to ten metres",
      meta_of({"swim_from_m": 99}), {"swim_from_m": 10.0})
for _junk in ("deep", float("nan"), "", None):
    check(f"junk ({_junk!r}) leaves no key — the client reads its default",
          meta_of({"swim_from_m": _junk}), {})
check("it travels with the clips and the two sinks",
      meta_of({"move_anim": "swim", "idle_anim": "treading-water",
               "move_sink_m": 0.35, "idle_sink_m": 1.3, "swim_from_m": 1.0}),
      {"move_anim": "swim", "idle_anim": "treading-water",
       "move_sink_m": 0.35, "idle_sink_m": 1.3, "swim_from_m": 1.0})
# THE SEED KIND OF W4b: a river is narrow, so it is shaped by its own two
# numbers (1.2 m deep over a 1 m ramp) rather than by the module defaults a
# lake keeps — and it is the first kind that says where swimming starts.
check("the seed ships a river with its own depth, ramp and threshold",
      (terrain_types.get_type("river") or {}).get("meta"),
      {"water": True, "water_depth_m": 1.2, "shore_ramp_m": 1.0,
       "move_anim": "swim", "idle_anim": "treading-water",
       "move_sink_m": 0.35, "idle_sink_m": 1.3, "swim_from_m": 1.0})
check("...it is water by the one predicate",
      terrain_types.is_water_kind("river"), True)
check("...and the KIND answers its two shape numbers, not the module ones",
      terrain_types.water_kind_defaults("river"), (1.2, 1.0))
check("...while the lake kind still answers the module defaults",
      terrain_types.water_kind_defaults("water"), (2.0, 3.0))
check("...one is walked into at a wading pace",
      ((terrain_types.get_type("river") or {}).get("passable"),
       (terrain_types.get_type("river") or {}).get("speed_factor")),
      (True, 0.4))
check("...and it wears the water material of the surface library",
      (terrain_types.get_type("river") or {}).get("surface"), "water")
check("the older water kinds name no threshold — an absent key is the "
      "client's metre",
      [k for k in ("water", "deep_water")
       if "swim_from_m" in ((terrain_types.get_type(k) or {}).get("meta") or {})],
      [])

print("[9] the micro-relief is GONE from the kind")
# THE DELETION PROOF, shaped like [7]: a key nobody whitelists is free-form
# data, so what the old rule CHANGED now travels through untouched.
check("an amplitude past the old clamp is no longer clamped",
      meta_of({"relief_amplitude_m": 99}), {"relief_amplitude_m": 99})
check("...a zero is no longer dropped",
      meta_of({"relief_amplitude_m": 0}), {"relief_amplitude_m": 0})
check("...junk is no longer refused",
      meta_of({"relief_amplitude_m": "much"}), {"relief_amplitude_m": "much"})
check("...and a wave under the old Nyquist floor stays where it was typed",
      meta_of({"relief_wave_m": 2}), {"relief_wave_m": 2})
check("a whole relief pair rides along verbatim, next to a real key",
      meta_of({"relief_amplitude_m": 0.4449, "relief_wave_m": 999,
               "move_anim": " swim ", "note": "x"}),
      {"relief_amplitude_m": 0.4449, "relief_wave_m": 999,
       "move_anim": "swim", "note": "x"})
# …AND BY NAME: the clamps left with the fields, they did not go quiet.
check("the module holds no relief clamp any more",
      [n for n in ("RELIEF_AMPLITUDE_MIN", "RELIEF_AMPLITUDE_MAX",
                   "RELIEF_WAVE_MIN", "RELIEF_WAVE_MAX",
                   "DEFAULT_RELIEF_WAVE_M")
       if hasattr(terrain_types, n)], [])
check("...they live next to the sanitizer that writes them, on the AREA",
      [n for n in ("RELIEF_AMPLITUDE_MIN_M", "RELIEF_AMPLITUDE_MAX_M",
                   "RELIEF_WAVE_MIN_M", "RELIEF_WAVE_MAX_M",
                   "DEFAULT_RELIEF_WAVE_M")
       if not hasattr(terrain_store, n)], [])
# THE READER AGREES — that is what makes the deletion real. An area of a kind
# whose row still carries both numbers contributes NOTHING to the bake: the
# world stays flat until the AREA says otherwise.
terrain_types.save_world_type(
    {"kind": "meadow", "name": "Meadow", "color": "#7ac74f",
     "meta": {"relief_amplitude_m": 0.4, "relief_wave_m": 32}})
_leftover = (terrain_types.get_type("meadow") or {}).get("meta") or {}
check("a hand-edited row may still HOLD the two numbers", _leftover,
      {"relief_amplitude_m": 0.4, "relief_wave_m": 32})
_plain_area = {"id": "ta_m", "kind": "meadow", "z_order": 0, "meta": {},
               "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]]}
check("...and an area of it is STILL no input to the relief pass",
      hf.relief_inputs([_plain_area]), [])
check("...while the same area saying it itself IS one",
      [(a["id"], p[1], p[2]) for a, p, _b in hf.relief_inputs(
          [{**_plain_area, "meta": {"relief_amplitude_m": 0.4,
                                    "relief_wave_m": 32.0}}])],
      [("ta_m", 0.4, 32.0)])
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
       "path": "<no key>", "rock": "<no key>", "river": "water",
       "sand": "sand", "water": "water"})

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

print("[13] the boot migration hands the relief from the kind to the areas")
from app.core import terrain_relief_migration as trm  # noqa: E402

# THE FIXTURE, one kind of each case the migration can meet:
#   "downs"  a kind with relief, painted TWICE — both areas must take it over,
#            and that is exactly the picture that used to be one bumpy kind
#   "moss"   a kind with relief and an area that ALREADY authors its own,
#            which is the author's answer and must survive untouched
#   "slab"   a kind without relief — its area stays flat
terrain_types.save_world_type(
    {"kind": "downs", "name": "Downs", "color": "#7ac74f",
     "meta": {"relief_amplitude_m": 0.8, "relief_wave_m": 24,
              "note": "keep me"}})
terrain_types.save_world_type(
    {"kind": "moss", "name": "Moss", "color": "#4f7a55",
     "meta": {"relief_amplitude_m": 1.5}})
terrain_types.save_world_type(
    {"kind": "slab", "name": "Slab", "color": "#999999"})
_a1 = terrain_store.save_area({"kind": "downs", "polygon": _square(0, 0, 40)})
_a2 = terrain_store.save_area({"kind": "downs", "polygon": _square(80, 0, 40)})
_a3 = terrain_store.save_area({"kind": "moss", "polygon": _square(0, 80, 40),
                               "meta": {"relief_amplitude_m": 0.1}})
_a4 = terrain_store.save_area({"kind": "slab", "polygon": _square(80, 80, 40)})
check("the marker is unset before the run",
      bool(get_world_setting("migrated_area_relief_v1")), False)
_rstats = trm.migrate_area_relief_once()
check("two areas took the relief over, one kept its own",
      (_rstats.get("areas"), _rstats.get("kept")), (2, 1))


def _meta(area_id):
    for a in terrain_store.list_areas():
        if a["id"] == area_id:
            return a.get("meta") or {}
    return {}


check("the first area of the bumpy kind now says it itself",
      _meta(_a1["id"]), {"relief_amplitude_m": 0.8, "relief_wave_m": 24.0})
check("...and so does the second — one kind, two areas, same picture",
      _meta(_a2["id"]), {"relief_amplitude_m": 0.8, "relief_wave_m": 24.0})
check("an area that already authored its own is untouched",
      _meta(_a3["id"]), {"relief_amplitude_m": 0.1})
check("an area of a flat kind stays flat", _meta(_a4["id"]), {})
check("the kind rows lost the two keys — and nothing else",
      (terrain_types.get_type("downs") or {}).get("meta"), {"note": "keep me"})
check("...the second one too",
      (terrain_types.get_type("moss") or {}).get("meta"), {})
check("the marker is set after the run",
      get_world_setting("migrated_area_relief_v1"), "1")
check("a second run is a no-op (the marker, not the content)",
      trm.migrate_area_relief_once(), None)
# THE PICTURE IS PRESERVED, which is the whole point: the bake now reads the
# two areas and gets the parameters the kind used to hand it, seed included.
check("both areas feed the bake with what the kind used to give it",
      [hf.relief_params(a["kind"], a) for a in terrain_store.list_areas()
       if a["id"] in (_a1["id"], _a2["id"])],
      [(hf.relief_seed("downs"), 0.8, 24.0)] * 2)
for _a in (_a1, _a2, _a3, _a4):
    terrain_store.delete_area(_a["id"])
for _kind in ("downs", "moss", "slab"):
    terrain_types.delete_world_type(_kind)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
