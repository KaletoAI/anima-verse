#!/usr/bin/env python3
"""Smoke run for what happens to CHARACTER POINTERS when a place is deleted.

Runs against a THROWAWAY storage directory — never touches a real world.

THE HOLE THIS CLOSES. ``delete_location`` removed the record and nothing
else, while three character-side fields go on naming the id:

  * ``known_locations``  — the travel-target list. The prompt section
    ``blocks.known_locations_section`` and ``travel_engine.start_journey``
    read the SAME list, so a dead id was offered as a destination and then
    refused by the engine: the character walked into a wall it was shown.
  * ``daily_schedules`` slots — the rhythm hint. ``_build_daily_schedule_block``
    resolved the place with ``loc_id_to_name.get(loc, loc)``, so a deleted id
    reached the prompt as the raw hex string the character was told to be at
    ("09:00 — location: c68dc34a"), a destination no verb accepts. Measured in
    a live world: 31 of 91 rendered blocks carried raw ids.
  * ``home_location`` — where auto-sleep walks to. Pointing at nothing, the
    exhausted character takes the no-path branch every single time.

``current_location`` is deliberately NOT rewritten: where a character standing
in a deleted place belongs is an authoring decision. It is reported by name and
left alone.

Hand-derived expectations. The world (all placed, so all reachable):

    HOME    (0, 0)     the character's own place, survives everything
    OFFICE  (100, 0)   deleted through the real path in case [2]
    GYM     (200, 0)   already dangling in case [4] (deleted behind the
                       purge's back, the way every pre-existing orphan
                       came to be)
    DOOMED  (300, 0)   case [1]'s throwaway: the block has to be shown a
                       place that vanished WITHOUT a sweep, and spending
                       OFFICE on it would leave case [2] nothing real to
                       delete

  [1] ``_build_daily_schedule_block`` renders places, not ids. Pinned at
      game hour 09:00, so the block shows the 09 and 10 slots and nothing
      else:
        * a slot on a LIVE place renders its NAME;
        * a slot on a DELETED place drops the place and KEEPS the role —
          the role is still true, the place is not;
        * a slot with a deleted place and NO role produces no line at all
          (rather than a line naming a hex string);
        * a slot naming the place the character is standing in renders
          WITHOUT the "you are not there" clause, and one naming anywhere
          else renders WITH it. That clause is the entire coupling between
          rhythm and travel — enforcement was removed on purpose
          (``scheduler_manager._resync_daily_schedules``), so this sentence
          is all that is left to turn a plan into a journey.
      An empty world list is the fail-open case: nothing is judged orphaned
      when the world itself could not be read.

  [2] ``delete_location`` sweeps all three pointers in one go: OFFICE leaves
      ``known_locations`` (HOME stays), its 09:00 slot loses the place but
      keeps the role, and ``home_location`` + ``home_room`` are cleared. The
      character standing in OFFICE keeps its ``current_location`` — reported,
      never moved.

  [3] The sweep and the ENGINE agree afterwards: the deleted place is gone
      from the prompt section, and ``start_journey`` answers
      ``unknown_target`` for it. Before the sweep the list offered it — that
      contradiction is the bug, so both halves are pinned.

  [4] ``cleanup_orphan_location_references`` (the boot sweep) catches what
      was ALREADY dangling: GYM is removed from the world list directly, so
      no delete path ever ran, and the boot sweep alone has to find it in all
      three fields. Idempotent — a second run touches nothing.

  [5] The ``__offmap__`` home sentinel is NOT a place and must survive every
      sweep; a character asleep off the map would otherwise lose its way back.

Usage:  ./.venv/bin/python scripts/smoke_location_purge.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="loc-purge-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="loc-purge-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.thought_context import _build_daily_schedule_block  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_config, get_character_current_location,
    get_character_daily_schedule, get_known_locations, save_character_config,
    save_character_daily_schedule, save_character_current_location,
    save_character_profile, set_character_pos, set_known_locations)
from plugins.movement.blocks import known_locations_section  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    cleanup_orphan_location_references, delete_location,
    replace_all_locations, update_location_position)

FAILURES = []
CHECKED = 0

# 09:00 in the world calendar — the block renders the current and the next
# hour, so every slot below is written for 09 or 10 and nothing drifts.
START = "Y0001-D001T09:00:00"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def set_map3d(loc_id: str, width: float) -> None:
    """Give a location a footprint — without one it is 'unplaced' and the
    journey engine refuses it for that reason instead of the knowledge one."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == loc_id:
            loc["map3d"] = dict(loc.get("map3d") or {}, plan_width_m=width)
    _save_world_data(data)


def place(name: str, x: float, z: float) -> str:
    loc_id = add_location(name=name, description="purge smoke")["id"]
    update_location_position(loc_id, x, z)
    set_map3d(loc_id, 10.0)
    return loc_id


def new_char(name: str, at: str, known=(), home: str = "") -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    if at:
        save_character_current_location(name, at)
    set_known_locations(name, list(known))
    if home:
        save_character_config(name, dict(get_character_config(name) or {},
                                         home_location=home,
                                         home_room="some_room"))


def set_plan(name: str, slots) -> None:
    save_character_daily_schedule(name, {"enabled": True, "slots": list(slots)})


def plan_places(name: str):
    """The ``location`` value of every stored slot, in hour order."""
    slots = (get_character_daily_schedule(name) or {}).get("slots") or []
    return [(s.get("hour"), (s.get("location") or ""), (s.get("role") or ""))
            for s in sorted(slots, key=lambda s: s.get("hour", 0))]


set_game_factor(0.0)
set_game_time(GameTime.parse(START))

HOME = place("Purge Home", 0.0, 0.0)
OFFICE = place("Purge Office", 100.0, 0.0)
GYM = place("Purge Gym", 200.0, 0.0)
# Case [1] needs a place it may destroy without spending one the later cases
# still have to delete through the real path.
DOOMED = place("Purge Doomed", 300.0, 0.0)

# ── [1] the rhythm block renders places, never ids ──────────────────────
print("[1] _build_daily_schedule_block: names, not hex strings")

new_char("plan_npc", HOME, known=[HOME, DOOMED])
set_plan("plan_npc", [
    {"hour": 9, "location": DOOMED, "role": "assistant", "sleep": False},
    {"hour": 10, "location": HOME, "role": "", "sleep": False},
])
block = _build_daily_schedule_block("plan_npc")
check_true("a live place renders by NAME", "location: Purge Doomed" in block,
           block)
check_true("… never as its id", DOOMED not in block, block)
check_true("the place it is NOT at says so",
           "Purge Doomed — you are not there right now" in block, block)
check_true("… and the one it IS at does not",
           "location: Purge Home\n" in block or block.endswith("Purge Home"),
           block)

# A place the world no longer has: the role survives, the place does not.
data = _load_world_data()
data["locations"] = [l for l in data["locations"] if l.get("id") != DOOMED]
replace_all_locations(data)
block = _build_daily_schedule_block("plan_npc")
check_true("a deleted place is dropped from the line", DOOMED not in block,
           block)
check_true("… while its role survives", "role: assistant" in block, block)
check_true("… and no place is named for that hour",
           "09:00 — role: assistant" in block, block)

# Same slot without a role: nothing left worth a line.
set_plan("plan_npc", [{"hour": 9, "location": DOOMED, "role": "",
                       "sleep": False}])
check("a placeless, roleless hour produces no line",
      _build_daily_schedule_block("plan_npc"), "")

# Fail-open: with no readable world list nothing may be judged orphaned.
_saved = _load_world_data()
replace_all_locations({"locations": []})
set_plan("plan_npc", [{"hour": 9, "location": DOOMED, "role": "assistant",
                       "sleep": False}])
check_true("an unreadable world judges nothing orphaned",
           DOOMED in _build_daily_schedule_block("plan_npc"),
           _build_daily_schedule_block("plan_npc"))
replace_all_locations(_saved)
# Case [1] left plan_npc pointing at the destroyed DOOMED. Sweep it now, so
# the counts in case [4] can be exact statements about GYM alone.
cleanup_orphan_location_references()

# ── [2] delete_location sweeps all three pointers ───────────────────────
print("[2] delete_location takes the character pointers with it")

new_char("office_npc", OFFICE, known=[HOME, OFFICE], home=OFFICE)
set_plan("office_npc", [
    {"hour": 9, "location": OFFICE, "role": "assistant", "sleep": False},
    {"hour": 10, "location": HOME, "role": "", "sleep": False},
])
check("before: the office is known",
      sorted(get_known_locations("office_npc")), sorted([HOME, OFFICE]))
check_true("before: the prompt section offers it as a destination",
           "Purge Office" in known_locations_section("office_npc"),
           known_locations_section("office_npc"))

check("the place is deleted", delete_location(OFFICE), True)
check("known_locations lost it — and only it",
      get_known_locations("office_npc"), [HOME])
check("the plan lost the place but kept the role",
      plan_places("office_npc"), [(9, "", "assistant"), (10, HOME, "")])
check("home_location was cleared",
      (get_character_config("office_npc") or {}).get("home_location"), "")
check("… and home_room with it",
      (get_character_config("office_npc") or {}).get("home_room"), "")
check("standing in it is reported, never rewritten",
      get_character_current_location("office_npc"), OFFICE)

# ── [3] section and engine agree after the sweep ────────────────────────
print("[3] what the prompt offers, the engine accepts")
section = known_locations_section("office_npc")
check_true("the deleted place is gone from the section",
           "Purge Office" not in section, section)
check("… and the engine refuses it too",
      travel_engine.start_journey("office_npc", OFFICE)[1], "unknown_target")

# ── [4] the boot sweep catches what was already dangling ────────────────
print("[4] cleanup_orphan_location_references finds pre-existing orphans")

cleanup_orphan_location_references()   # start from nothing dangling
new_char("gym_npc", HOME, known=[HOME, GYM], home=GYM)
set_plan("gym_npc", [{"hour": 9, "location": GYM, "role": "trainer",
                      "sleep": False}])
# Delete GYM behind the purge's back — exactly how every pre-existing orphan
# was made, before delete_location swept up after itself.
data = _load_world_data()
data["locations"] = [l for l in data["locations"] if l.get("id") != GYM]
replace_all_locations(data)
check("nothing swept it yet: the gym is still known",
      sorted(get_known_locations("gym_npc")), sorted([HOME, GYM]))

stats = cleanup_orphan_location_references()
check("the boot sweep reports one cleaned list", stats["known"], 1)
check("… one cleaned plan", stats["schedule"], 1)
check("… and one cleared home", stats["home"], 1)
check("the gym left known_locations", get_known_locations("gym_npc"), [HOME])
check("the plan kept the role, lost the place",
      plan_places("gym_npc"), [(9, "", "trainer")])
check("home was cleared",
      (get_character_config("gym_npc") or {}).get("home_location"), "")

again = cleanup_orphan_location_references()
check("a second run finds nothing left", sum(again.values()), 0)

# ── [5] the off-map sentinel is not a place ─────────────────────────────
print("[5] the __offmap__ home sentinel survives every sweep")

new_char("sleeper_npc", HOME, known=[HOME], home="__offmap__")
cleanup_orphan_location_references()
check("the sentinel is untouched",
      (get_character_config("sleeper_npc") or {}).get("home_location"),
      "__offmap__")

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
