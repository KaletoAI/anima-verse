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
"""
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
}

import app.core.npc_ops as npc_ops  # noqa: E402
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
    lambda location_id="", reason="slot", triggered_by="":
    SUBMITS.append((location_id, reason)) or f"task_{len(SUBMITS)}")

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

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
