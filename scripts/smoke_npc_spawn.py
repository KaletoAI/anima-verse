#!/usr/bin/env python3
"""Smoke run for the automatic NPCs: slots, approach trigger, pool, wanderers.

Usage:
    ./.venv/bin/python scripts/smoke_npc_spawn.py

Runs against a THROWAWAY storage directory — never touches a real world, never
needs a server. ``ANIMATION_CLIPS_DIR`` is redirected before the app modules
are imported. Every expected number below is derived BY HAND from the rule it
tests (plan-npc-auto-spawn.md), not recorded from current output.

Sections:

  [1] Slot fulfilment is a PURE function. ``missing_slots(location, held)``
      sees a location's authored slots and one role tag per living NPC that
      holds one — no names, no DB. Hand cases, each derived from § 1 ("a slot
      counts as filled when enough living NPCs carry its tag"):
        · empty slot, nobody there            → needed 1
        · count_min 2, one holder             → needed 1
        · count_min 2, two holders            → not listed at all
        · count_min 3 but count_max 2, two    → not listed (the ceiling wins)
        · a holder of ANOTHER role            → does not fill this one
        · role match is case/space insensitive (the tag is authored text)
        · a slot without a role is not a slot (it could never be counted)
        · count_max is raised to count_min when an author inverts them
      Plus the sanitizer the editor saves through: one slot per role, counts
      clamped, and a location that is saved with an empty list loses the key.

  [2] The approach trigger is cheap and cooled down. ``consider_point`` gets a
      hand-built location list and never touches the DB: only placed locations
      that DECLARE slots and lie within ``npc.spawn_radius_m`` produce a job.
      The § 2 proof: four reports in one second (the walker's real rate is up
      to four per second) submit exactly ONE job, and only after the game
      clock has passed the per-location cooldown does the fifth report submit
      the second one. A location out of range and a location without slots
      never submit at all.

  [3] The TTL sweep POOLS instead of deleting (§ 3). After the sweep the
      expired NPC is: gone from the roster, gone from the living-NPC list,
      NOT deleted (its profile is still readable), marked ``status='pooled'``,
      standing nowhere — and what another character remembered about it is
      deleted, exactly as before pooling existed. The NPC whose TTL still runs
      stays untouched.

  [4] A spawn takes the POOL before the pipeline (§ 3). With a pooled NPC of
      the same role, ``spawn_for_slot`` returns that NPC and the generation
      pipeline is NOT called once. With no pool hit for the role, the pipeline
      is called exactly once. The revived NPC carries the new slot tag, the
      new TTL and is back in the roster. A slot that names its own TEMPLATE
      only takes a sheet of that template — a role match alone would hand an
      animal slot a human.

  [5] The hard cap holds (§ 4). With ``npc.max_alive`` already reached,
      ``fill_location_slots`` spawns nothing and reports ``capped`` — the
      pipeline is never called. The cap is checked before EVERY spawn, so a
      job that fills two slots stops at the boundary, not after it.

  [6] Wanderers (§ 5): the quota is a ceiling — at quota the tick queues
      nothing, below quota it queues exactly one (never a burst). An arriving
      wanderer is pooled; a turning wanderer (the other half of the 50/50)
      stays alive with its target and origin swapped. Both branches are
      forced, not rolled, so the check is deterministic.

  [7] A PAINTED AREA HAS SLOTS OF ITS OWN (spec § E3.2). The same approach
      trigger, over the polygon instead of the pin — `polygon_distance` is 0
      anywhere inside, so "inside" and "within `npc.spawn_radius_m` of the
      rim" are one comparison. The fixture is the Heath, x 1000…1100 ×
      z 0…100, painted far away from both locations of section [2] so only
      the area can answer. With `spawn_radius_m` = 100:

        · (1050, 50) — inside            → distance 0    → one job
        · a second report right after it → the per-area cooldown holds
        · (950, 50)  — 50 m west of the rim              → one job
        · (880, 50)  — 120 m west of the rim             → nothing
        · standing INSIDE an area without slots (1050, 230) → nothing

      The job carries `area_id`, never `location_id`, and the worker routes
      it to `fill_area_slots`: with a pooled `guard` in stock the slot is
      filled from the pool, the revived NPC stands at a point INSIDE the
      polygon, carries `npc_slot_area` (not `npc_slot_location`) and shows up
      in `held_roles_at_area`.

  [8] A FAILED PLACEMENT ON THE POOL-RETURN PATH LEAVES NO GHOST.
      `revive_from_pool` sets the row status to '' BEFORE it places, because
      the location setter's arrival side effects read the roster. When the
      placement then fails, "" means: living, positionless, slot-stamped —
      counting against `npc.max_alive`, holding the slot through
      `held_roles_at_area`, standing nowhere at all. And its caller reads
      False as "the pool did not deliver" and runs the LLM pipeline for the
      very same slot, so one failure buys a ghost AND a generation.
      The failing placement is a home naming a painted area that does not
      exist: `npc_home.random_point` has no polygon, so every draw answers
      None and `place_npc` yields "" for real — nothing is stubbed.
      Expected: `revive_from_pool` False, status back to POOLED_STATUS, the
      NPC not in `list_temporary_npcs`, `held_roles_at_area` empty, and
      `take_from_pool` hands the same sheet out again. Through
      `spawn_for_slot` the whole pass then produces "" with the pipeline
      called EXACTLY ONCE and still nobody holding the role.

  [9] THE APPROACH CHECK DOES NOT RE-READ THE PAINTED WORLD. A position
      report arrives up to four times a second per walker, and the area half
      of `consider_point` used to read and JSON-parse every painted area on
      each of them. Two ways out, both checked by COUNTING the calls to
      `terrain.list_areas` (a monkeypatched counter, measured as a delta per
      report because `save_area` reads the areas itself):

        · a caller that already holds the areas hands them over
          (`areas=`, which `routes/play.py` does on the wilderness branch)
                                                            → 0 reads
        · without them, the stamp-keyed cache of the slot-bearing areas
          answers: first report 1 read, the next four 0
        · editing an area moves `terrain.area_stamps()` → the next report
          rebuilds (1 read), the one after it does not (0)
        · `reset_cooldowns()` drops the cache too         → 1 read

 [10] AN AUTHORED Infinity NEVER ESCAPES THE LOCATION SAVE. `json.loads`
      accepts the literal `Infinity`, and `int(float("inf"))` raises
      OverflowError — not ValueError — which `normalize_slots` would let
      through into the location save, `missing_slots` and `location_gap`.
      A slot with `count_min`, `count_max` and `radius_m` all Infinity comes
      out as the plain fallbacks (1, 1, 0) with a warning, and nothing raises.

 [11] A SLOT BOUND TO AN EXISTING NPC NEVER GENERATES ANYBODY. The `character`
      key names one temporary NPC, and that sheet is what the slot gets —
      revived out of the pool or, if it is already alive somewhere else,
      re-stamped and moved. Hand cases, each derived from the rule:

        · the sanitizer keeps the name (trimmed); an unbound slot has ""
        · a bound slot's counts collapse to at most 1 — there is one of her,
          and an authored 3 would report a gap that can never close; an
          authored 0 ("wants nobody") survives as 0
        · the terrain sanitizer passes it through to an AREA slot
        · bound + POOLED, with an OLDER sheet of the same role in front of it
          in the FIFO → exactly the bound one comes back, the decoy stays
          pooled, the generator is asked 0 times, and the slot is stamped and
          placed in the location's ARRIVAL room (the slot names no room)
        · bound + LIVING somewhere else → stamps and position move, the sheet
          never touches the pool (status stays ''), and what another character
          remembers about it survives: `cleanup_npc_traces` is counted and
          must be called 0 times, the memory row is still there
        · bound + ALREADY standing in this slot → the profile is byte-identical
          afterwards and the generator is not asked
        · bound to a FULL character, and to a name that exists nowhere → the
          slot stays empty with a warning, the generator is asked 0 times, and
          the full character is not moved an inch
        · bound + still WAITING FOR ITS ASSETS → this pass yields "" and the
          sheet stays pooled; the finish job is what places it
        · bound + PERMANENT pooled sheet → revived (`take_from_pool` skips a
          permanent sheet, so the binding is its only way out of the pool) and
          its empty lifetime stamp is NOT refreshed
        · bound on a painted AREA → `npc_slot_area` instead of
          `npc_slot_location`, `npc_home` of kind area, point inside the
          polygon
        · WINDOWS APPLY UNCHANGED: at 12:00 a 20:00-06:00 slot wants nobody,
          `sweep_closed_windows` pools the bound NPC, and at 22:00 the very
          same sheet comes back — again without a single pipeline call.
        · AT THE CAP a bound LIVING sheet is still moved, and the job walks on
          past the slot it could not fill. `alive_npc_count` counts that sheet
          before and after (`_fill_bound_slot` re-stamps and places, it never
          pools), so the move adds nobody and the cap has no business blocking
          it. The Toll Gate is authored with the capped slot FIRST:
            `npc.max_alive` 1, and exactly one temp NPC alive (demo_bound) →
            `cap_reached()` True
            slot 1 "toller"  unbound → needs capacity → skipped, `capped` True,
                             the pipeline is not called
            slot 2 "sentry"  bound to the LIVING demo_bound → needs none →
                             filled
          so the job answers `filled` 1, `spawned` ["demo_bound"], `capped`
          True, demo_bound stands at the gate with `npc_slot_role` "sentry",
          and `alive_npc_count()` is still 1. With the old `return` the second
          slot was never even looked at.
          `_slot_needs_capacity` itself answers the three cases directly:
          bound+living False, unbound True, bound+pooled True.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npc-spawn-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npc-spawn-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import config  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import game_time, set_game_time  # noqa: E402

# A fresh world starts at the game epoch and GameTime refuses to go below it —
# the "already expired" stamps below would underflow. Anchor a few days in.
set_game_time(GameTime.from_parts(1, 10, 12, 0, 0))

# The limits under test, set in-process: a smoke must not depend on whatever
# a world's config.json happens to say, and these are exactly the numbers the
# hand-derived expectations below use.
config._CONFIG["npc"] = {
    "auto_spawn_enabled": True,
    "max_alive": 3,
    "wanderer_quota": 2,
    "spawn_radius_m": 100,
    "spawn_cooldown_game_minutes": 10,
    "slot_ttl_game_hours": 12,
    "wanderer_ttl_game_hours": 24,
    # The FINISH GATE is off here. This run is about slots, the pool and the
    # roads; with the gate armed every NPC of this smoke — none of them has a
    # portrait or a mesh — would be held back out of the world, which is what
    # scripts/smoke_npc_assets.py checks instead.
    "require_assets": False,
}

import app.core.npc_ops as npc_ops  # noqa: E402
import app.core.npc_pool as npc_pool  # noqa: E402
import app.core.npc_spawn as npc_spawn  # noqa: E402
from app.core.npc_pool import list_pool, pool_npc, take_from_pool  # noqa: E402
from app.models.character import (  # noqa: E402
    POOLED_STATUS, get_character_current_location, get_character_profile,
    get_character_status, list_available_characters, list_pooled_characters,
    list_temporary_npcs, save_character_profile)
from app.models.memory import add_memory  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def make_npc(name, role="", location="", ttl_stamp=None, wanderer=False,
             **extra):
    """A living temporary NPC, created the way the apply path leaves one."""
    profile = {
        "character_name": name, "template": "npc-temporary",
        "character_personality": "Dry, economical with words.",
        "standing_task": "tends the bar",
        "outfit_description": "grey linen apron",
        "npc_slot_role": role, "npc_slot_location": location if role else "",
        "npc_wanderer": wanderer,
        "expires_at": "" if ttl_stamp is None else ttl_stamp,
    }
    profile.update(extra)
    save_character_profile(name, profile, create_new=True)
    if location:
        from app.models.character import save_character_current_location
        save_character_current_location(name, location)
    return name


# ---------------------------------------------------------------------------
print("[1] Slot fulfilment is a pure function")
BAR = {"id": "tavern", "name": "The Tavern", "npc_slots": [
    {"role": "barkeeper", "count_min": 1, "count_max": 1,
     "briefing": "runs the taproom"},
    {"role": "guest", "count_min": 2, "count_max": 3, "briefing": "a regular"},
]}

gap = npc_spawn.missing_slots(BAR, [])
check("nobody there: two slots missing", [(g["role"], g["needed"]) for g in gap],
      [("barkeeper", 1), ("guest", 2)])
gap = npc_spawn.missing_slots(BAR, ["barkeeper", "guest"])
check("one guest of two", [(g["role"], g["needed"]) for g in gap], [("guest", 1)])
check("both guests there",
      npc_spawn.missing_slots(BAR, ["barkeeper", "guest", "guest"]), [])
check("a third guest does not create a gap",
      npc_spawn.missing_slots(BAR, ["barkeeper", "guest", "guest", "guest"]), [])
check("a stranger's role fills nothing",
      [(g["role"], g["needed"])
       for g in npc_spawn.missing_slots(BAR, ["stablehand", "stablehand"])],
      [("barkeeper", 1), ("guest", 2)])
check("the tag match ignores case and padding",
      npc_spawn.missing_slots({"id": "x", "npc_slots": [
          {"role": "Barkeeper", "count_min": 1, "count_max": 1}]},
          ["  barkeeper "]), [])
# A slot standing at its maximum is never spawned into, whoever put the NPCs
# there (a manual NPC, a wanderer that took the slot).
check("a slot at its maximum is closed",
      npc_spawn.missing_slots({"id": "x", "npc_slots": [
          {"role": "guard", "count_min": 2, "count_max": 2}]},
          ["guard", "guard"]), [])
# An inverted pair is an authoring slip; the MINIMUM is the binding half, so
# min 3 / max 2 with two guards still wants one more.
check("an inverted pair follows the minimum",
      [(g["role"], g["needed"]) for g in npc_spawn.missing_slots(
          {"id": "x", "npc_slots": [
              {"role": "guard", "count_min": 3, "count_max": 2}]},
          ["guard", "guard"])], [("guard", 1)])
check("a slot without a role is not a slot",
      npc_spawn.normalize_slots([{"count_min": 2}, {"role": " "}]), [])
check("one slot per role survives",
      [s["role"] for s in npc_spawn.normalize_slots(
          [{"role": "guest"}, {"role": "Guest"}, {"role": "cook"}])],
      ["guest", "cook"])
check("counts are clamped and ordered",
      {k: v for k, v in npc_spawn.normalize_slots(
          [{"role": "guest", "count_min": -4, "count_max": 999}])[0].items()
       if k.startswith("count")},
      {"count_min": 0, "count_max": 20})
check("an inverted pair lifts the maximum to the minimum",
      {k: v for k, v in npc_spawn.normalize_slots(
          [{"role": "guest", "count_min": 4, "count_max": 1}])[0].items()
       if k.startswith("count")},
      {"count_min": 4, "count_max": 4})

# The editor's round trip goes through the very same sanitizer.
from app.core.world_ops import create_location_with_extras  # noqa: E402
from app.models.world import get_location_by_id  # noqa: E402

create_location_with_extras({
    "name": "The Tavern", "description": "A low room that smells of beer.",
    "rooms": [{"id": "taproom", "name": "Taproom"}],
    "npc_slots": [{"role": "barkeeper", "count_min": 1, "count_max": 1,
                   "briefing": "runs the taproom", "room": "taproom"},
                  {"role": "", "count_min": 5}]})
TAVERN = [l for l in __import__("app.models.world", fromlist=["x"]).list_locations()
          if l.get("name") == "The Tavern"][0]
TAVERN_ID = TAVERN["id"]
check("saved slots are sanitized",
      [(s["role"], s["count_min"], s["room"])
       for s in get_location_by_id(TAVERN_ID).get("npc_slots") or []],
      [("barkeeper", 1, "taproom")])
create_location_with_extras({"name": "The Tavern", "rooms": [], "npc_slots": []})
check("an empty list drops the key entirely",
      "npc_slots" in (get_location_by_id(TAVERN_ID) or {}), False)
create_location_with_extras({
    "name": "The Tavern", "rooms": [],
    "npc_slots": [{"role": "barkeeper", "count_min": 1, "count_max": 1,
                   "briefing": "runs the taproom", "room": "taproom"}]})

# ---------------------------------------------------------------------------
print("\n[2] The approach trigger: geometry + one job per cooldown window")
SUBMITS = []
npc_spawn.submit_spawn_job = (
    lambda location_id="", reason="slot", triggered_by="", area_id="":
    SUBMITS.append((location_id or area_id, reason)) or f"task_{len(SUBMITS)}")

LOCS = [
    {"id": "tavern", "pos_x": 0.0, "pos_z": 0.0,
     "npc_slots": [{"role": "barkeeper", "count_min": 1, "count_max": 1}]},
    {"id": "far_inn", "pos_x": 500.0, "pos_z": 0.0,
     "npc_slots": [{"role": "cook", "count_min": 1, "count_max": 1}]},
    {"id": "empty_hut", "pos_x": 5.0, "pos_z": 0.0, "npc_slots": []},
    {"id": "unplaced", "pos_x": None, "pos_z": None,
     "npc_slots": [{"role": "hermit", "count_min": 1, "count_max": 1}]},
]

npc_spawn.reset_cooldowns()
# Four reports in one second — the walking client's real rate.
for _ in range(4):
    npc_spawn.consider_point("demo", 10.0, 0.0, locations=LOCS)
check("four reports, one job", SUBMITS, [("tavern", "slot")])
check("out of radius: no job", [s for s in SUBMITS if s[0] == "far_inn"], [])
check("no slots: no job", [s for s in SUBMITS if s[0] == "empty_hut"], [])
check("unplaced: no job", [s for s in SUBMITS if s[0] == "unplaced"], [])

# 9 game minutes later the cooldown (10) still holds, at 11 it is over.
set_game_time(game_time() + GameDuration.of(minutes=9))
npc_spawn.consider_point("demo", 10.0, 0.0, locations=LOCS)
check("still cooling down", len(SUBMITS), 1)
set_game_time(game_time() + GameDuration.of(minutes=2))
npc_spawn.consider_point("demo", 10.0, 0.0, locations=LOCS)
check("after the cooldown: the second job", len(SUBMITS), 2)

# Walking into range of the far one submits for it, and only for it.
SUBMITS.clear()
npc_spawn.consider_point("demo", 450.0, 0.0, locations=LOCS)
check("in range of the far place", SUBMITS, [("far_inn", "slot")])

# The master switch stops it dead.
SUBMITS.clear()
config._CONFIG["npc"]["auto_spawn_enabled"] = False
npc_spawn.reset_cooldowns()
npc_spawn.consider_point("demo", 10.0, 0.0, locations=LOCS)
check("switched off: nothing at all", SUBMITS, [])
config._CONFIG["npc"]["auto_spawn_enabled"] = True

# ---------------------------------------------------------------------------
print("\n[3] The TTL sweep pools instead of deleting")
EXPIRED = game_time().minus_clamped(GameDuration.of(hours=1)).canonical()
FUTURE = (game_time() + GameDuration.of(hours=5)).canonical()
make_npc("demo_gone", role="guest", location=TAVERN_ID, ttl_stamp=EXPIRED)
make_npc("demo_stays", role="guest", location=TAVERN_ID, ttl_stamp=FUTURE)
save_character_profile("demo_witness", {"character_name": "demo_witness",
                                        "template": "human-roleplay"},
                       create_new=True)
add_memory("demo_witness", "demo_gone poured me a beer.", memory_type="episodic")
add_memory("demo_witness", "The road to the north was muddy.",
           memory_type="episodic")

check("the witness remembers two things",
      db.get_connection().execute(
          "SELECT COUNT(*) FROM memories WHERE character_name='demo_witness'"
      ).fetchone()[0], 2)
check("sweep pools exactly one", npc_ops.sweep_expired_npcs(), 1)
check("the pooled NPC is out of the roster",
      "demo_gone" in list_available_characters(), False)
check("…and out of the living NPCs", "demo_gone" in list_temporary_npcs(), False)
check("…but NOT deleted",
      "demo_gone" in list_available_characters(include_pooled=True), True)
check("its profile survives",
      (get_character_profile("demo_gone") or {}).get("standing_task"),
      "tends the bar")
check("its status says pooled", get_character_status("demo_gone"), POOLED_STATUS)
check("it stands nowhere", get_character_current_location("demo_gone"), "")
check("it is in the pool listing",
      [r["name"] for r in list_pool()], ["demo_gone"])
check("the memory ABOUT it is gone, the unrelated one stays",
      [r[0] for r in db.get_connection().execute(
          "SELECT content FROM memories WHERE character_name='demo_witness'")],
      ["The road to the north was muddy."])
check("the NPC whose TTL runs is untouched",
      "demo_stays" in list_temporary_npcs(), True)

# ---------------------------------------------------------------------------
print("\n[4] A spawn takes the pool before the pipeline")
PIPELINE = []


def _fake_pipeline(**kwargs):
    PIPELINE.append(kwargs.get("slot_role") or kwargs.get("created_by"))
    return {"ok": False, "error": "smoke: pipeline not run"}


npc_ops.generate_npc_blocking = _fake_pipeline

GUEST_SLOT = {"role": "guest", "template": "", "count_min": 1, "count_max": 1,
              "briefing": "a regular", "room": "taproom"}
check("the pool has a guest", take_from_pool("guest"), "demo_gone")
check("…and nobody for another role", take_from_pool("stablehand"), None)
# A slot that insists on its OWN NPC kind must not be handed a sheet built
# from another template; a slot without one takes any temporary NPC back.
check("…and nobody of a foreign template",
      take_from_pool("guest", template="npc-animal"), None)
check("…while the default template matches",
      take_from_pool("guest", template="npc-temporary"), "demo_gone")

name = npc_spawn.spawn_for_slot({"id": TAVERN_ID, "name": "The Tavern"},
                                GUEST_SLOT)
check("the slot was filled from the pool", name, "demo_gone")
check("the pipeline was not called", PIPELINE, [])
check("the revived NPC is in the roster again",
      "demo_gone" in list_temporary_npcs(), True)
revived = get_character_profile("demo_gone") or {}
check("it carries the slot tag",
      (revived.get("npc_slot_role"), revived.get("npc_slot_location")),
      ("guest", TAVERN_ID))
check("it stands at the location",
      get_character_current_location("demo_gone"), TAVERN_ID)
check("it got a fresh TTL — 12 game hours",
      round((GameTime.parse(revived["expires_at"]) - game_time()).hours, 3), 12.0)
check("the pool is empty again", list_pooled_characters(), [])

# No pool hit for this role → the pipeline runs, exactly once.
name = npc_spawn.spawn_for_slot({"id": TAVERN_ID, "name": "The Tavern"},
                                {**GUEST_SLOT, "role": "stablehand"})
check("no pool hit: the pipeline ran once", PIPELINE, ["stablehand"])
check("a failed pipeline yields no NPC", name, "")

# ---------------------------------------------------------------------------
print("\n[5] The hard cap stops the spawn")
PIPELINE.clear()
check("living NPCs now", sorted(list_temporary_npcs()),
      ["demo_gone", "demo_stays"])
make_npc("demo_third", role="guest", location=TAVERN_ID)
check("the cap of 3 is reached", npc_spawn.cap_reached(), True)

# The tavern wants a barkeeper it does not have — and still gets none.
result = npc_spawn.fill_location_slots(TAVERN_ID)
check("nothing was filled", result.get("filled"), 0)
check("the job reports the cap", result.get("capped"), True)
check("the pipeline was never called", PIPELINE, [])

# One below the cap the same job fills the barkeeper slot (through the
# pipeline, which the stub refuses — the proof is that it was ASKED).
pool_npc("demo_third", reason="smoke")
check("one seat free again", npc_spawn.cap_reached(), False)
result = npc_spawn.fill_location_slots(TAVERN_ID)
check("the barkeeper slot was attempted once", PIPELINE, ["barkeeper"])
check("…and produced nothing, the stub refuses", result.get("filled"), 0)

# ---------------------------------------------------------------------------
print("\n[6] Wanderers: quota, arrival, turnaround")
SUBMITS.clear()
for name in list_temporary_npcs():
    pool_npc(name, reason="smoke reset")
check("no living NPCs left", list_temporary_npcs(), [])

make_npc("demo_walk_a", wanderer=True, location=TAVERN_ID,
         wander_origin=TAVERN_ID, wander_target="far_inn")
make_npc("demo_walk_b", wanderer=True, location=TAVERN_ID,
         wander_origin=TAVERN_ID, wander_target=TAVERN_ID)
check("two wanderers alive", sorted(npc_spawn.list_wanderers()),
      ["demo_walk_a", "demo_walk_b"])

# A wanderer that is still on the road is not touched: journey present.
save_character_profile("demo_walk_a", {**get_character_profile("demo_walk_a"),
                                       "journey": {"target": "far_inn"}})
# demo_walk_b has arrived (target == where it stands) and rolls "pool".
npc_spawn.random.random = lambda: 0.9
result = npc_spawn.wanderer_tick()
check("the walking one was not settled", result["arrived"], ["demo_walk_b"])
check("the arrived one is pooled",
      get_character_status("demo_walk_b"), POOLED_STATUS)
check("it is no longer a wanderer", npc_spawn.list_wanderers(), ["demo_walk_a"])
# Below quota (2) and below the cap (3) → exactly ONE job, never a burst.
check("one top-up job queued", SUBMITS, [("", "wanderer")])

# The other half of the 50/50: turn around instead of vanishing.
SUBMITS.clear()
SENT = []
npc_spawn._send_wanderer = lambda name, target: SENT.append((name, target)) or True
save_character_profile("demo_walk_a", {**get_character_profile("demo_walk_a"),
                                       "journey": None,
                                       "wander_origin": "far_inn",
                                       "wander_target": TAVERN_ID})
npc_spawn.random.random = lambda: 0.1
result = npc_spawn.wanderer_tick()
check("the arrival was settled", result["arrived"], ["demo_walk_a"])
check("it is still alive", npc_spawn.list_wanderers(), ["demo_walk_a"])
check("it walks back to where it came from", SENT, [("demo_walk_a", "far_inn")])
turned = get_character_profile("demo_walk_a") or {}
check("target and origin swapped",
      (turned.get("wander_target"), turned.get("wander_origin")),
      ("far_inn", TAVERN_ID))

# At quota the tick queues nothing.
SUBMITS.clear()
SENT.clear()
make_npc("demo_walk_c", wanderer=True, location=TAVERN_ID,
         wander_origin=TAVERN_ID, wander_target=TAVERN_ID)
save_character_profile("demo_walk_a", {**get_character_profile("demo_walk_a"),
                                       "journey": {"target": "far_inn"}})
save_character_profile("demo_walk_c", {**get_character_profile("demo_walk_c"),
                                       "journey": {"target": "far_inn"}})
result = npc_spawn.wanderer_tick()
check("two wanderers = the quota", result["wanderers"], 2)
check("nothing queued at quota", SUBMITS, [])

# ---------------------------------------------------------------------------
print("\n[7] A painted area carries slots of its own")
from app.models import terrain  # noqa: E402

HEATH_POLY = [[1000, 0], [1100, 0], [1100, 100], [1000, 100]]
HEATH = terrain.save_area({
    "kind": "grass", "polygon": HEATH_POLY, "z_order": 0,
    "meta": {"label": "The Heath",
             "npc_slots": [{"role": "guard", "count_min": 1, "count_max": 1,
                            "briefing": "watches the heath"}]}})["id"]
BARE = terrain.save_area({
    "kind": "grass", "polygon": [[1000, 180], [1100, 180], [1100, 280],
                                 [1000, 280]],
    "z_order": 0, "meta": {"label": "The Fen"}})["id"]

SUBMITS.clear()
npc_spawn.reset_cooldowns()
npc_spawn.consider_point("demo", 1050.0, 50.0, locations=LOCS)
check("standing on the area submits for it", SUBMITS, [(HEATH, "slot")])
npc_spawn.consider_point("demo", 1050.0, 50.0, locations=LOCS)
check("and the per-area cooldown holds the second report", len(SUBMITS), 1)

set_game_time(game_time() + GameDuration.of(minutes=11))
SUBMITS.clear()
npc_spawn.consider_point("demo", 950.0, 50.0, locations=LOCS)
check("50 m from the rim is within the spawn radius", SUBMITS,
      [(HEATH, "slot")])

set_game_time(game_time() + GameDuration.of(minutes=11))
SUBMITS.clear()
npc_spawn.consider_point("demo", 880.0, 50.0, locations=LOCS)
check("120 m from the rim is not", SUBMITS, [])
# Standing INSIDE the Fen, which declares nothing: its own distance is 0 and
# it is still skipped, while the Heath is 130 m away — out of range.
npc_spawn.consider_point("demo", 1050.0, 230.0, locations=LOCS)
check("and an area without slots never submits", SUBMITS, [])

# The worker side: the job routes to the area, and the pool fills the slot.
for name in list_temporary_npcs():
    pool_npc(name, reason="smoke reset")
make_npc("demo_heath_guard", role="guard", location=TAVERN_ID)
pool_npc("demo_heath_guard", reason="smoke")
check("the pool holds a guard", take_from_pool("guard"), "demo_heath_guard")

PIPELINE.clear()
result = npc_spawn._handle_npc_spawn({"reason": "slot", "area_id": HEATH,
                                      "location_id": ""})
check("the job filled the area's slot from the pool",
      (result.get("filled"), result.get("area_id")), (1, HEATH))
check("the pipeline was never asked", PIPELINE, [])
guard = get_character_profile("demo_heath_guard") or {}
check("the slot stamp is the area one",
      (guard.get("npc_slot_area"), guard.get("npc_slot_location"),
       guard.get("npc_slot_role")), (HEATH, "", "guard"))
check("its home is the area",
      guard.get("npc_home"), {"kind": "area", "area_id": HEATH})
from app.core.world_geometry import point_in_polygon  # noqa: E402
from app.models.character import get_character_pos  # noqa: E402
gpos = get_character_pos("demo_heath_guard") or {}
check("and it stands inside the polygon",
      point_in_polygon(gpos.get("x"), gpos.get("z"), HEATH_POLY), True)
check("held_roles_at_area sees it", npc_spawn.held_roles_at_area(HEATH),
      ["guard"])
check("so the area has no gap left",
      npc_spawn.fill_area_slots(HEATH).get("filled"), 0)
check("an unknown area is skipped, not crashed",
      npc_spawn.fill_area_slots("ta_nothing").get("skipped"), "unknown area")

# ---------------------------------------------------------------------------
print("\n[8] A failed placement on the pool-return path leaves no ghost")
# The home is a painted area that does not exist, so `npc_home.random_point`
# has no polygon and answers None for every draw — the shortest way to a
# placement that fails for real, without stubbing the placement itself.
GHOST_AREA = "ta_nowhere"
RANGER_SLOT = {"role": "ranger", "count_min": 1, "count_max": 1,
               "briefing": "walks the lost wood"}
make_npc("demo_ranger", role="ranger", location=TAVERN_ID)
pool_npc("demo_ranger", reason="smoke")
check("the pool holds a ranger", get_character_status("demo_ranger"),
      POOLED_STATUS)

check("reviving it into the vanished area fails",
      npc_pool.revive_from_pool("demo_ranger", "", "", ttl_hours=12,
                                slot_role="ranger",
                                home={"kind": "area",
                                      "area_id": GHOST_AREA}), False)
check("…and the sheet is still POOLED, not a living positionless ghost",
      (get_character_status("demo_ranger"),
       "demo_ranger" in list_temporary_npcs()), (POOLED_STATUS, False))
check("…so it holds no slot of that area",
      npc_spawn.held_roles_at_area(GHOST_AREA), [])
check("…and it is ordinary pool stock again",
      take_from_pool("ranger"), "demo_ranger")

# THE WHOLE PASS: the same failure through `spawn_for_slot`. The pool hit
# fails, the pipeline runs ONCE, and no second NPC ends up holding the role.
PIPELINE.clear()
check("the slot is not filled",
      npc_spawn.spawn_for_slot({"id": GHOST_AREA,
                                "meta": {"label": "The Lost Wood"}},
                               RANGER_SLOT, kind="area"), "")
check("…the pipeline was asked exactly once", PIPELINE, ["ranger"])
check("…and still nobody holds the ranger role",
      npc_spawn.held_roles_at_area(GHOST_AREA), [])

# ---------------------------------------------------------------------------
print("\n[9] The approach check does not re-read the painted world")
AREA_READS = []
_real_list_areas = terrain.list_areas


def _counting_list_areas():
    AREA_READS.append(1)
    return _real_list_areas()


terrain.list_areas = _counting_list_areas


def report(**kwargs) -> int:
    """One position report, 11 game minutes after the last one (so the
    per-area cooldown never masks a read). Returns the number of area reads
    THIS report cost — measured as a delta, because `save_area` reads the
    areas itself and its bookkeeping is not what is under test here.
    """
    before = len(AREA_READS)
    set_game_time(game_time() + GameDuration.of(minutes=11))
    npc_spawn.consider_point("demo", 1050.0, 50.0, locations=LOCS, **kwargs)
    return len(AREA_READS) - before


try:
    HEATH_AREA = [a for a in _real_list_areas() if a["id"] == HEATH]
    npc_spawn.reset_cooldowns()
    SUBMITS.clear()
    check("a caller that hands its areas over pays for no read",
          (report(areas=HEATH_AREA), SUBMITS), (0, [(HEATH, "slot")]))

    # Without them: ONE read, then the stamp-keyed cache answers.
    check("the first report without them costs one read", report(), 1)
    check("…and four further reports cost none",
          [report() for _ in range(4)], [0, 0, 0, 0])

    # An EDIT moves `area_stamps()`, so the very next report rebuilds.
    terrain.save_area({"id": HEATH, "kind": "grass", "polygon": HEATH_POLY,
                       "z_order": 0,
                       "meta": {"label": "The Heath",
                                "npc_slots": [
                                    {"role": "guard", "count_min": 1,
                                     "count_max": 1,
                                     "briefing": "watches the heath"}]}})
    check("an edited area invalidates the cache", report(), 1)
    check("…once, not per report", report(), 0)

    # …and so does the admin's manual sweep.
    npc_spawn.reset_cooldowns()
    check("reset_cooldowns clears it too", report(), 1)
finally:
    terrain.list_areas = _real_list_areas

# ---------------------------------------------------------------------------
print("\n[10] An authored Infinity never escapes the location save")
INF_SLOT = json.loads('{"role": "ferryman", "count_min": Infinity, '
                      '"count_max": Infinity, "radius_m": Infinity}')
check("count_min is Infinity as JSON reads it",
      INF_SLOT["count_min"] == float("inf"), True)
NORMALIZED = npc_spawn.normalize_slots([INF_SLOT])
check("normalize_slots survives it and falls back",
      [(s["role"], s["count_min"], s["count_max"], s["radius_m"])
       for s in NORMALIZED], [("ferryman", 1, 1, 0)])

# ---------------------------------------------------------------------------
print("\n[11] A slot bound to an existing NPC revives exactly that one")
import app.core.memory_service as memory_service  # noqa: E402
import app.core.npc_assets as npc_assets  # noqa: E402
from app.models.character import get_character_current_room  # noqa: E402

# A clean slate: everything still standing from the sections above goes into
# the pool, so `held_roles_at` below answers about THIS section only.
for name in list_temporary_npcs():
    pool_npc(name, reason="smoke reset")
PIPELINE.clear()

check("the sanitizer keeps the binding, trimmed",
      npc_spawn.normalize_slots(
          [{"role": "watch", "character": "  demo_bound "}])[0]["character"],
      "demo_bound")
check("an unbound slot carries an empty binding",
      npc_spawn.normalize_slots([{"role": "watch"}])[0]["character"], "")
# There is only ONE of her: a bound slot's counts collapse to at most 1, or
# `missing_slots` would report a gap that can never close and the fill job
# would count the same NPC twice.
check("a bound slot wants exactly one",
      {k: v for k, v in npc_spawn.normalize_slots(
          [{"role": "watch", "character": "demo_bound", "count_min": 3,
            "count_max": 5}])[0].items() if k.startswith("count")},
      {"count_min": 1, "count_max": 1})
check("…and a bound slot that wants nobody still wants nobody",
      {k: v for k, v in npc_spawn.normalize_slots(
          [{"role": "watch", "character": "demo_bound", "count_min": 0,
            "count_max": 0}])[0].items() if k.startswith("count")},
      {"count_min": 0, "count_max": 0})
BOUND_AREA = terrain.save_area({
    "kind": "grass", "polygon": [[2000, 0], [2100, 0], [2100, 100], [2000, 100]],
    "z_order": 0,
    "meta": {"label": "The Ridge",
             "npc_slots": [{"role": "ranger", "count_min": 1, "count_max": 1,
                            "character": "demo_bound"}]}})["id"]
check("…and the area sanitizer passes it through",
      [(s["role"], s["character"])
       for s in (terrain.get_area(BOUND_AREA) or {})["meta"]["npc_slots"]],
      [("ranger", "demo_bound")])

# --- bound + pooled: exactly that sheet, never the older one of the same role
TAVERN_LOC = get_location_by_id(TAVERN_ID)
ARRIVAL_ROOM = __import__("app.models.world", fromlist=["x"]).get_arrival_room_id(
    TAVERN_LOC)
make_npc("demo_decoy", role="watch", location=TAVERN_ID)
pool_npc("demo_decoy", reason="smoke")          # oldest of the role: the trap
make_npc("demo_bound", role="guest", location=TAVERN_ID)
pool_npc("demo_bound", reason="smoke")
check("the FIFO would hand out the decoy", take_from_pool("watch"), "demo_decoy")

WATCH_SLOT = {"role": "watch", "template": "", "count_min": 1, "count_max": 1,
              "briefing": "keeps the night watch", "room": "", "when": "",
              "radius_m": 0, "character": "demo_bound"}
check("the bound sheet came back, not the decoy",
      npc_spawn.spawn_for_slot(TAVERN_LOC, WATCH_SLOT), "demo_bound")
check("the pipeline was never asked", PIPELINE, [])
check("the decoy is still pooled", get_character_status("demo_decoy"),
      POOLED_STATUS)
check("the bound NPC stands at the location",
      get_character_current_location("demo_bound"), TAVERN_ID)
check("…in the arrival room, as an unroomed slot places anybody",
      get_character_current_room("demo_bound"), ARRIVAL_ROOM)
bound = get_character_profile("demo_bound") or {}
check("…and carries this slot's stamps, the other one empty",
      (bound.get("npc_slot_role"), bound.get("npc_slot_location"),
       bound.get("npc_slot_area")), ("watch", TAVERN_ID, ""))
check("so it holds the role", npc_spawn.held_roles_at(TAVERN_ID), ["watch"])
check("…and the slot has no gap left",
      npc_spawn.missing_slots({"id": TAVERN_ID, "npc_slots": [WATCH_SLOT]},
                              npc_spawn.held_roles_at(TAVERN_ID)), [])

# --- bound + living elsewhere: moved, not recycled. No pool, no trace sweep.
TRACE_CALLS = []
_real_cleanup = memory_service.cleanup_npc_traces


def _counting_cleanup(npc_name):
    TRACE_CALLS.append(npc_name)
    return _real_cleanup(npc_name)


memory_service.cleanup_npc_traces = _counting_cleanup
add_memory("demo_witness", "demo_bound nodded at me by the door.",
           memory_type="episodic")
create_location_with_extras({
    "name": "The Watchpost", "description": "A shed on the ridge road.",
    "rooms": []})
POST_ID = [l for l in __import__("app.models.world", fromlist=["x"]).list_locations()
           if l.get("name") == "The Watchpost"][0]["id"]
POST_LOC = get_location_by_id(POST_ID)
POST_SLOT = {**WATCH_SLOT, "role": "lookout"}

check("the living NPC is moved, not regenerated",
      npc_spawn.spawn_for_slot(POST_LOC, POST_SLOT), "demo_bound")
check("…without a pipeline call", PIPELINE, [])
check("…without a single trace cleanup", TRACE_CALLS, [])
check("…so the memory ABOUT it survives",
      db.get_connection().execute(
          "SELECT COUNT(*) FROM memories WHERE character_name='demo_witness'"
          " AND content LIKE '%demo_bound%'").fetchone()[0], 1)
check("it never went through the pool", get_character_status("demo_bound"), "")
check("it stands at the new place",
      get_character_current_location("demo_bound"), POST_ID)
moved = get_character_profile("demo_bound") or {}
check("…with the new stamps",
      (moved.get("npc_slot_role"), moved.get("npc_slot_location"),
       moved.get("npc_slot_area")), ("lookout", POST_ID, ""))
check("…and the old place holds nobody any more",
      npc_spawn.held_roles_at(TAVERN_ID), [])

# --- bound + already standing there: nothing happens at all.
BEFORE = get_character_profile("demo_bound")
check("a second pass returns the same NPC",
      npc_spawn.spawn_for_slot(POST_LOC, POST_SLOT), "demo_bound")
check("…and wrote nothing", get_character_profile("demo_bound") == BEFORE, True)
check("…and asked no pipeline", PIPELINE, [])

# --- bound to something that is not a temporary NPC: skipped with a warning.
WARNINGS = []
_real_warning = npc_spawn.logger.warning


def _counting_warning(msg, *args):
    WARNINGS.append(msg % args if args else msg)
    _real_warning(msg, *args)


npc_spawn.logger.warning = _counting_warning
save_character_profile("demo_person", {"character_name": "demo_person",
                                       "template": "human-roleplay"},
                       create_new=True)
check("a full character is never bound",
      npc_spawn.spawn_for_slot(TAVERN_LOC,
                               {**WATCH_SLOT, "character": "demo_person"}), "")
check("…and it was not moved an inch",
      get_character_current_location("demo_person"), "")
check("a name that exists nowhere is skipped too",
      npc_spawn.spawn_for_slot(TAVERN_LOC,
                               {**WATCH_SLOT, "character": "demo_ghost"}), "")
check("both were reported", len([w for w in WARNINGS
                                 if "not a temporary NPC" in w]), 2)
check("…and neither generated anybody", PIPELINE, [])
npc_spawn.logger.warning = _real_warning

# --- bound + still waiting for its assets: this pass yields nothing.
make_npc("demo_pending", role="watch", location=TAVERN_ID)
pool_npc("demo_pending", reason="smoke")
_real_awaiting = npc_assets.is_awaiting_assets
npc_assets.is_awaiting_assets = lambda n: n == "demo_pending"
try:
    check("an unfinished sheet is left to its finish job",
          npc_spawn.spawn_for_slot(TAVERN_LOC,
                                   {**WATCH_SLOT,
                                    "character": "demo_pending"}), "")
    check("…and stays pooled", get_character_status("demo_pending"),
          POOLED_STATUS)
    check("…with no pipeline call", PIPELINE, [])
finally:
    npc_assets.is_awaiting_assets = _real_awaiting

# --- bound + PERMANENT pooled sheet: the binding is its only way out.
make_npc("demo_keeper", role="keeper", location=TAVERN_ID, npc_permanent=True)
pool_npc("demo_keeper", reason="smoke")
check("the ordinary pool draw skips a permanent sheet",
      take_from_pool("keeper"), None)
check("the binding revives it anyway",
      npc_spawn.spawn_for_slot(TAVERN_LOC, {**WATCH_SLOT, "role": "keeper",
                                            "character": "demo_keeper"}),
      "demo_keeper")
check("…and its lifetime is still none",
      (get_character_profile("demo_keeper") or {}).get("expires_at"), "")
check("…and nothing was generated", PIPELINE, [])

# --- bound on a painted AREA: the area stamp, the area home, a point inside.
make_npc("demo_ridge", role="", location=TAVERN_ID)
check("the bound area slot took the living sheet",
      npc_spawn.spawn_for_slot(terrain.get_area(BOUND_AREA),
                               {**WATCH_SLOT, "role": "ranger",
                                "character": "demo_ridge"}, kind="area"),
      "demo_ridge")
ridge = get_character_profile("demo_ridge") or {}
check("…with the AREA stamp and no location stamp",
      (ridge.get("npc_slot_role"), ridge.get("npc_slot_area"),
       ridge.get("npc_slot_location")), ("ranger", BOUND_AREA, ""))
check("…its home is the polygon", ridge.get("npc_home"),
      {"kind": "area", "area_id": BOUND_AREA})
rpos = get_character_pos("demo_ridge") or {}
check("…and it stands inside it",
      point_in_polygon(rpos.get("x"), rpos.get("z"),
                       [[2000, 0], [2100, 0], [2100, 100], [2000, 100]]), True)
check("…and the pipeline was still never asked", PIPELINE, [])

# --- the time window governs the bound NPC exactly as it governs a fresh one.
NIGHT_SLOT = {**WATCH_SLOT, "role": "robber", "when": "20:00-06:00",
              "character": "demo_bound"}
create_location_with_extras({
    "name": "The Night Post", "description": "A crossing under bare trees.",
    "rooms": [], "npc_slots": [NIGHT_SLOT]})
NIGHT_ID = [l for l in __import__("app.models.world", fromlist=["x"]).list_locations()
            if l.get("name") == "The Night Post"][0]["id"]
NIGHT_LOC = get_location_by_id(NIGHT_ID)
check("the binding survived the location save",
      [(s["role"], s["character"], s["when"])
       for s in NIGHT_LOC.get("npc_slots") or []],
      [("robber", "demo_bound", "20:00-06:00")])

set_game_time(GameTime.from_parts(1, 40, 22, 0, 0))          # 22:00 — open
check("at 22:00 the slot wants somebody",
      [g["role"] for g in npc_spawn.location_gap(NIGHT_LOC)], ["robber"])
check("and it is the bound sheet that arrives",
      npc_spawn.spawn_for_slot(NIGHT_LOC, NIGHT_SLOT), "demo_bound")
check("…without a pipeline call", PIPELINE, [])

set_game_time(GameTime.from_parts(1, 41, 12, 0, 0))          # 12:00 — shut
check("at 12:00 the slot wants nobody", npc_spawn.location_gap(NIGHT_LOC), [])
check("the window sweep pools the bound NPC",
      npc_ops.sweep_closed_windows(), 1)
check("…so it sits in the pool", get_character_status("demo_bound"),
      POOLED_STATUS)

set_game_time(GameTime.from_parts(1, 41, 22, 0, 0))          # 22:00 — open
check("at nightfall the very same sheet comes back",
      npc_spawn.spawn_for_slot(NIGHT_LOC, NIGHT_SLOT), "demo_bound")
check("…alive at the night post",
      (get_character_status("demo_bound"),
       get_character_current_location("demo_bound")), ("", NIGHT_ID))
check("…and the generator was never asked, once, in this whole section",
      PIPELINE, [])

# --- AT THE CAP a pure MOVE still happens, and the job walks on.
for name in list_temporary_npcs():
    if name != "demo_bound":
        pool_npc(name, reason="smoke reset")
check("only the bound NPC is alive", list_temporary_npcs(), ["demo_bound"])
config._CONFIG["npc"]["max_alive"] = 1
check("the cap of 1 is reached", npc_spawn.cap_reached(), True)

check("a slot bound to a LIVING sheet needs no capacity",
      npc_spawn._slot_needs_capacity({"character": "demo_bound"}), False)
check("an UNBOUND slot always needs it",
      npc_spawn._slot_needs_capacity({"character": ""}), True)
check("and a slot bound to a POOLED sheet needs it too",
      npc_spawn._slot_needs_capacity({"character": "demo_decoy"}), True)

create_location_with_extras({
    "name": "The Toll Gate", "description": "A bar across the road.",
    "rooms": [],
    "npc_slots": [
        # FIRST, and capped: with the old `return` the job ended right here.
        {"role": "toller", "count_min": 1, "count_max": 1},
        # SECOND, and a pure move: it must still be reached and filled.
        {"role": "sentry", "count_min": 1, "count_max": 1,
         "character": "demo_bound"},
    ]})
TOLL_ID = [l for l in __import__("app.models.world", fromlist=["x"]).list_locations()
           if l.get("name") == "The Toll Gate"][0]["id"]
check("both slots are gaps",
      [g["role"] for g in npc_spawn.location_gap(get_location_by_id(TOLL_ID))],
      ["toller", "sentry"])

PIPELINE.clear()
result = npc_spawn.fill_location_slots(TOLL_ID)
check("the capped unbound slot is reported", result.get("capped"), True)
check("…and never reached the pipeline", PIPELINE, [])
check("but the bound slot BEHIND it was still filled",
      (result.get("filled"), result.get("spawned")), (1, ["demo_bound"]))
check("the named NPC really moved to the gate",
      get_character_current_location("demo_bound"), TOLL_ID)
check("…and carries that slot's stamp",
      (get_character_profile("demo_bound") or {}).get("npc_slot_role"),
      "sentry")
check("…and the world is paying for exactly as many NPCs as before",
      (npc_spawn.alive_npc_count(), npc_spawn.cap_reached()), (1, True))
config._CONFIG["npc"]["max_alive"] = 3

memory_service.cleanup_npc_traces = _real_cleanup

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
