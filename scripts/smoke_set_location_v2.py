#!/usr/bin/env python3
"""Smoke run for the movement SKILLS on Journey v2
(Seamless World, E3 Task 4).

Runs against a THROWAWAY storage directory — never touches a real world.

Rules every expectation below is derived from BY HAND:

  * ``start_journey`` answers ``(journey, reason)`` with reason ∈
    {'', 'unknown_target', 'no_route', 'unplaced_target'} (Task 2). The
    SKILL owns the character-facing wording and the diary record; the
    engine owns the mechanics.
  * A character cannot KNOW whether a place is on the map — so an
    ``unplaced_target`` reads to the character exactly like an
    ``unknown_target``; only the ``travel_failed`` record keeps them apart.
  * ``journey_state`` is a pure function of the GAME clock, which is pinned
    here (``set_game_factor(0.0)`` + ``set_game_time``) so the ETA text is
    an exact statement, not a race against wall time.
  * The avatar is excluded from journeys (Task 5 owns avatar travel): a
    cross-location SetLocation by a player-controlled character stays the
    INSTANT move it was.
  * ``move_skill`` is gone without replacement — the grid it stepped over
    does not exist any more.

The world used below (all grass unless painted):

    HOME    (0, 0)    w 10, opening S at 0.5 → (0, 5)
    MARKET  (100, 0)  w 10, opening W at 0.5 → (95, 0)
    SECRET  (0, 60)   w 10, placed, NOT in known_locations
    ISLE    (0, 200)  w 10, known + placed, ringed by water
    GHOST   —         known, never placed

Hand-derived expectations:

  [1] Deletion test for move: no ``skill_move.py`` on disk, no ``move``
      verb in the movement manifest, ``discover_packages`` offers no skill
      with id ``move`` (so the intent engine cannot surface it either), and
      no source file under app/ or plugins/ mentions ``MoveSkill``,
      ``skill_move`` or ``surroundings_section``.

  [2] HOME → MARKET starts a journey: a v2 journey dict on the profile
      (waypoints, no ``path``), ``movement_target`` = MARKET, the character
      still stands in HOME (the ticker performs the arrival, not the skill)
      and the answer names the target plus the ETA as HH:MM of
      ``to_world_tz(journey_state(...)["eta_game"])``. No travel_failed
      record is written for a successful start.

  [3] SECRET is placed but unknown → no journey, no movement target, a
      ``travel_failed`` record with reason ``unknown_target``, and the text
      says the character does not know the way.

  [4] ISLE is known and placed but drowned in water → reason ``no_route``
      in the record and a text that speaks of a missing PASSABLE route
      (a different fact than not knowing the way).

  [5] GHOST is known but unplaced → record reason ``unplaced_target``,
      while the TEXT is character-identical to [3].

  [6] An avatar (account.active_character) crossing locations moves
      instantly: current_location is MARKET right after the call and no
      journey exists.

  [7] CancelTravel drops a running journey (journey + movement_target gone,
      the answer names the abandoned target) and answers "no journey" when
      there is none.

  [8] Joining a party cancels the joiner's own journey — followers are
      dragged by the leader and must not walk a second route of their own
      (Task 3 handover: the ticker only cleans up under a TRAVELLING
      leader). Pinned on BOTH join paths, because the cancel sits at their
      one choke point ``party_engine.add_to_party``: the JoinParty verb and
      the accepted pending invite (``resolve_pending_invite`` — the route a
      taken-over avatar answers through).

  [9] ``blocks.travel_section`` renders the v2 journey in METRES: the text
      carries "m to go", the ETA and the CancelTravel nudge, and the word
      "cell" appears nowhere.

 [10] The AgentLoop auto-sleep, BEHAVIOURALLY (the method swallows every
      exception, so a source grep would prove nothing): an exhausted
      character (stamina < 10) away from its home_location journeys home
      → outcome ``auto_sleep_walking`` with a real journey on the profile;
      a home that cannot be walked to (ISLE behind the water) → outcome
      ``auto_sleep_no_path``, ``is_sleeping`` set, no journey.

 [12] ``accessible_when`` is a WALL for the SKILL too (E7 cleanup). VAULT is
      known, placed and reachable, but carries
      ``accessible_when: ["has_item:silver_key"]``. Without the key the skill
      refuses with the sentence the travel route and the arrival ticker use
      ("This place is not accessible to you.") — no journey, no movement
      target — and with the key in the inventory the very same call starts
      one. The field is read through ``world_ops.conditions_pass``, the ONE
      reader all three enforcement points share; before this the skill was the
      hole through which an NPC set off for a place the ticker would then turn
      away at the door.

 [11] No raw engine reason reaches the character: the recent-activity
      section (system_prompt_builder) and the diary render all three
      travel_failed reasons in-fiction, and ``unplaced_target`` reads
      exactly like ``unknown_target``.

Usage:  ./.venv/bin/python scripts/smoke_set_location_v2.py
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]

STORAGE = Path(tempfile.mkdtemp(prefix="set-location-v2-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="set-location-v2-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import travel_engine  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.timeutils import (game_now, set_game_factor,  # noqa: E402
                                set_game_time, to_world_tz)
from app.models import terrain  # noqa: E402
from app.models.account import save_user_profile  # noqa: E402
from app.models.inventory import add_item, add_to_inventory  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_profile, get_movement_target,
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)
from app.plugins.context import PluginContext  # noqa: E402
from app.plugins.loader import discover_packages  # noqa: E402

FAILURES = []
CHECKED = 0

START_DT = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


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


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (scale anchor, openings)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def patch_location(location_id: str, **fields) -> None:
    """Set top-level fields on a location (``accessible_when`` here)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc.update(fields)
    _save_world_data(data)


def new_npc(name: str, location_id: str, x: float, z: float, known) -> None:
    save_character_profile(name, {"current_location": ""}, create_new=True)
    if location_id:
        save_character_current_location(name, location_id)
    set_character_pos(name, x, z)
    set_known_locations(name, list(known))


def last_state(name: str, change_type: str):
    """The most recent state_history entry of the given type, or None."""
    rows = get_connection().execute(
        "SELECT state_json FROM state_history WHERE character_name=? "
        "ORDER BY id DESC LIMIT 30", (name,)).fetchall()
    for row in rows:
        try:
            entry = json.loads(row[0] or "{}")
        except Exception:
            continue
        if entry.get("type") == change_type:
            return entry
    return None


def call(skill, character: str, text: str) -> str:
    return skill.execute(json.dumps({"input": text, "agent_name": character}))


# ── [1] the deletion test for move ──────────────────────────────────────
print("[1] move_skill is gone without replacement")
check("skill_move.py on disk",
      (REPO / "plugins" / "movement" / "skill_move.py").exists(), False)
manifest = (REPO / "plugins" / "movement" / "plugin.yaml").read_text(encoding="utf-8")
check("the manifest declares no move verb",
      "skill_move" in manifest or "MoveSkill" in manifest, False)
movement_pkg = next((p for p in discover_packages(force=True)
                     if p.id == "movement"), None)
check_true("the movement package was discovered", movement_pkg is not None)
verb_ids = sorted(e.skill_id for e in (movement_pkg.skills if movement_pkg else []))
check("the movement verbs", verb_ids, ["cancel_travel", "setlocation"])
grep = subprocess.run(
    ["grep", "-rn", "-e", "MoveSkill", "-e", "skill_move",
     "-e", "surroundings_section", "app", "plugins"],
    cwd=REPO, capture_output=True, text=True)
check("no source reference to the move skill is left", grep.stdout.strip(), "")
# The deletion has to reach the PROMPT layer too — a tool the LLM is told to
# call but that no longer exists is a hallucination invitation. Prompt text
# is built in two places: Jinja templates AND Python strings, so both are
# swept (comments are not prompt text and are excluded by the pattern).
grep = subprocess.run(
    ["grep", "-rnE", r"\bMove\b", "--include=*.md",
     "shared/templates", "plugins"],
    cwd=REPO, capture_output=True, text=True)
check("no template advertises the Move verb", grep.stdout.strip(), "")
grep = subprocess.run(
    ["grep", "-rnE", "-e", "Move/SetLocation", "-e", "SetLocation/Move",
     "--include=*.py", "app", "plugins"],
    cwd=REPO, capture_output=True, text=True)
check("no Python line pairs Move with SetLocation any more",
      grep.stdout.strip(), "")

# ── the world ───────────────────────────────────────────────────────────
set_game_factor(0.0)
set_game_time(START_DT)

HOME = add_location(name="Smoke Home", description="set-location v2 smoke")["id"]
update_location_position(HOME, 0.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": "S", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
MARKET = add_location(name="Smoke Market", description="set-location v2 smoke")["id"]
update_location_position(MARKET, 100.0, 0.0)
set_map3d(MARKET, plan_width_m=10.0,
          boundary_openings=[{"edge": "W", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
SECRET = add_location(name="Smoke Secret", description="unknown to the npc")["id"]
update_location_position(SECRET, 0.0, 60.0)
set_map3d(SECRET, plan_width_m=10.0,
          boundary_openings=[{"edge": "N", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
ISLE = add_location(name="Smoke Isle", description="drowned in water")["id"]
update_location_position(ISLE, 0.0, 200.0)
set_map3d(ISLE, plan_width_m=10.0,
          boundary_openings=[{"edge": "N", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
VAULT = add_location(name="Smoke Vault", description="needs the key")["id"]
update_location_position(VAULT, 0.0, -60.0)
set_map3d(VAULT, plan_width_m=10.0,
          boundary_openings=[{"edge": "S", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
patch_location(VAULT, accessible_when=["has_item:silver_key"])
add_item(name="Silver Key", description="opens the vault", item_id="silver_key")
GHOST = add_location(name="Smoke Ghost", description="never placed")["id"]
# A water ring wide enough that the nav grid's rescue radius (2 cells of
# 2 m) cannot escape it — ISLE is genuinely unreachable, not merely awkward.
terrain.save_area({"kind": "deep_water",
                   "polygon": [[-40, 160], [40, 160], [40, 240], [-40, 240]],
                   "z_order": 0})

from plugins.movement.skill_set_location import (  # noqa: E402
    CancelTravelSkill, SetLocationSkill)
from plugins.party.skill import PartySkill  # noqa: E402

CTX = PluginContext("movement")
set_location = SetLocationSkill({"enabled": True}, CTX)
cancel_travel = CancelTravelSkill({"enabled": True}, CTX)
join_party = PartySkill({"enabled": True}, PluginContext("party"), verb="join")

# ── [2] a real journey ──────────────────────────────────────────────────
print("[2] SetLocation across locations starts a v2 journey")
new_npc("demo_npc", HOME, 0.0, 0.0, [HOME, MARKET, ISLE, GHOST])
answer = call(set_location, "demo_npc", "Smoke Market")
journey = travel_engine.get_journey("demo_npc")
check_true("a journey exists", journey is not None, answer)
check("movement_target", get_movement_target("demo_npc"), MARKET)
check("the character has NOT arrived yet (the ticker does that)",
      get_character_current_location("demo_npc"), HOME)
if journey is not None:
    check("the journey is v2 (waypoints, no path)",
          "waypoints" in journey and "path" not in journey, True)
    state = travel_engine.journey_state(journey["waypoints"],
                                        journey["started_at_game"], game_now())
    eta_text = f"{to_world_tz(state['eta_game']):%H:%M}"
    check_true(f"the answer carries the ETA {eta_text}", eta_text in answer,
               answer)
    check_true("the answer names the target", "Smoke Market" in answer, answer)
check("no travel_failed record for a successful start",
      last_state("demo_npc", "travel_failed"), None)

# ── [3] an unknown target ───────────────────────────────────────────────
print("[3] a placed but UNKNOWN target fails with unknown_target")
new_npc("npc_unknown", HOME, 0.0, 0.0, [HOME, MARKET, ISLE, GHOST])
unknown_answer = call(set_location, "npc_unknown", "Smoke Secret")
check("no journey", travel_engine.get_journey("npc_unknown"), None)
check("no movement target", get_movement_target("npc_unknown"), "")
record = last_state("npc_unknown", "travel_failed")
check_true("a travel_failed record exists", record is not None)
check("the recorded reason", (record or {}).get("metadata", {}).get("reason"),
      "unknown_target")
check_true("the text is about not knowing the way",
           "know the way" in unknown_answer.lower(), unknown_answer)

# ── [4] no passable route ───────────────────────────────────────────────
print("[4] a known + placed target behind water fails with no_route")
new_npc("npc_water", HOME, 0.0, 0.0, [HOME, MARKET, ISLE, GHOST])
water_answer = call(set_location, "npc_water", "Smoke Isle")
check("no journey", travel_engine.get_journey("npc_water"), None)
record = last_state("npc_water", "travel_failed")
check("the recorded reason", (record or {}).get("metadata", {}).get("reason"),
      "no_route")
check_true("the text speaks of a missing passable route",
           "passable route" in water_answer.lower(), water_answer)
check_true("… and NOT of missing knowledge",
           "know the way" not in water_answer.lower(), water_answer)

# ── [5] an unplaced target ──────────────────────────────────────────────
print("[5] a known but UNPLACED target: own reason, unknown-style text")
new_npc("npc_ghost", HOME, 0.0, 0.0, [HOME, MARKET, ISLE, GHOST])
ghost_answer = call(set_location, "npc_ghost", "Smoke Ghost")
check("no journey", travel_engine.get_journey("npc_ghost"), None)
record = last_state("npc_ghost", "travel_failed")
check("the recorded reason", (record or {}).get("metadata", {}).get("reason"),
      "unplaced_target")
check("the text is the unknown-target one (a character cannot know about "
      "placement)",
      ghost_answer.replace("Smoke Ghost", "X"),
      unknown_answer.replace("Smoke Secret", "X"))

# ── [6] the avatar is excluded ──────────────────────────────────────────
print("[6] a player-controlled character still moves instantly")
new_npc("avatar_npc", HOME, 0.0, 0.0, [HOME, MARKET, ISLE, GHOST])
save_user_profile({"active_character": "avatar_npc"})
from app.models.account import is_player_controlled  # noqa: E402
check("the avatar is recognised", is_player_controlled("avatar_npc"), True)
avatar_answer = call(set_location, "avatar_npc", "Smoke Market")
check("no journey for the avatar", travel_engine.get_journey("avatar_npc"),
      None)
check("the avatar arrived instantly",
      get_character_current_location("avatar_npc"), MARKET)
check_true("the answer is the ordinary location confirmation",
           "Smoke Market" in avatar_answer, avatar_answer)
save_user_profile({"active_character": ""})

# ── [7] CancelTravel ────────────────────────────────────────────────────
print("[7] CancelTravel aborts a running journey")
check_true("demo_npc is still travelling",
           travel_engine.get_journey("demo_npc") is not None)
cancel_answer = call(cancel_travel, "demo_npc", "")
check("journey gone", travel_engine.get_journey("demo_npc"), None)
check("movement target gone", get_movement_target("demo_npc"), "")
check_true("the answer names the abandoned target",
           "Smoke Market" in cancel_answer, cancel_answer)
idle_answer = call(cancel_travel, "demo_npc", "")
check_true("a second call reports that there is no journey",
           "no journey" in idle_answer.lower(), idle_answer)

# ── [8] joining a party cancels the joiner's journey ────────────────────
print("[8] JoinParty cancels the joiner's own journey")
new_npc("leader_npc", HOME, 0.0, 0.0, [HOME, MARKET])
new_npc("joiner_npc", HOME, 0.0, 0.0, [HOME, MARKET])
call(set_location, "joiner_npc", "Smoke Market")
check_true("the joiner is travelling before the join",
           travel_engine.get_journey("joiner_npc") is not None)
join_answer = join_party.execute(json.dumps({"input": "leader_npc",
                                             "agent_name": "joiner_npc",
                                             "leader": "leader_npc"}))
check_true("the join succeeded", "joins" in join_answer, join_answer)
check("the joiner's journey is gone",
      travel_engine.get_journey("joiner_npc"), None)
check("… and its movement target with it",
      get_movement_target("joiner_npc"), "")

# The SECOND join path: an accepted pending invite never touches the skill,
# it calls the engine directly — the cancel has to sit at the choke point.
from app.core.party_engine import (create_pending_invite,  # noqa: E402
                                   resolve_pending_invite)
new_npc("host_npc", HOME, 0.0, 0.0, [HOME, MARKET])
new_npc("guest_npc", HOME, 0.0, 0.0, [HOME, MARKET])
call(set_location, "guest_npc", "Smoke Market")
check_true("the guest is travelling before the invite",
           travel_engine.get_journey("guest_npc") is not None)
invite_id = create_pending_invite("host_npc", "guest_npc")
resolved = resolve_pending_invite(invite_id, True)
check("the invite was accepted", resolved.get("status"), "accepted")
check("the accepted invite cancels the guest's journey too",
      travel_engine.get_journey("guest_npc"), None)
check("… and its movement target with it",
      get_movement_target("guest_npc"), "")

# ── [9] the travel prompt section ───────────────────────────────────────
print("[9] blocks.travel_section renders metres, not cells")
from plugins.movement.blocks import travel_section  # noqa: E402
new_npc("prompt_npc", HOME, 0.0, 0.0, [HOME, MARKET])
call(set_location, "prompt_npc", "Smoke Market")
section = travel_section("prompt_npc")
check_true("the section is rendered", section.startswith("=== On the road ==="),
           section)
check_true("it states the remaining metres", "m to go" in section, section)
check_true("it nudges towards CancelTravel", "CancelTravel" in section, section)
check_true("no cell wording is left", "cell" not in section.lower(), section)
travel_engine.cancel_journey("prompt_npc")
check("no section without a journey", travel_section("prompt_npc"), "")

# ── [10] the AgentLoop auto-sleep ───────────────────────────────────────
print("[10] the AgentLoop auto-sleep journeys home — or sleeps in place")
from app.core.agent_loop import get_agent_loop  # noqa: E402
from app.models.character import (get_character_config,  # noqa: E402
                                  save_character_config)

loop = get_agent_loop()


def exhaust(name: str, home_id: str) -> None:
    """An exhausted character (stamina 5) whose home is ``home_id``."""
    profile = get_character_profile(name)
    profile["status_effects"] = dict(profile.get("status_effects") or {},
                                     stamina=5)
    profile["is_sleeping"] = False
    save_character_profile(name, profile)
    save_character_config(name, dict(get_character_config(name),
                                     home_location=home_id))


new_npc("tired_npc", HOME, 0.0, 0.0, [HOME, MARKET, ISLE])
exhaust("tired_npc", MARKET)
result = loop._maybe_auto_sleep("tired_npc") or {}
check("a walkable home starts the journey home", result.get("outcome"),
      "auto_sleep_walking")
check_true("… and a real journey is on the profile",
           travel_engine.get_journey("tired_npc") is not None)
check("… and the character is NOT asleep yet",
      bool(get_character_profile("tired_npc").get("is_sleeping")), False)

new_npc("stuck_npc", HOME, 0.0, 0.0, [HOME, MARKET, ISLE])
exhaust("stuck_npc", ISLE)                    # known + placed, behind water
result = loop._maybe_auto_sleep("stuck_npc") or {}
check("an unreachable home sleeps in place", result.get("outcome"),
      "auto_sleep_no_path")
check("… the character sleeps",
      bool(get_character_profile("stuck_npc").get("is_sleeping")), True)
check("… and no journey was left behind",
      travel_engine.get_journey("stuck_npc"), None)

# ── [12] accessible_when is a wall for the skill too ────────────────────
print("[12] accessible_when refuses the skill — and the key lifts it")
new_npc("npc_locked", HOME, 0.0, 0.0, [HOME, MARKET, VAULT])
# English by profile, so the refusal can be pinned as an exact sentence
# instead of whatever the language file makes of it.
_locked = get_character_profile("npc_locked")
_locked["language"] = "en"
save_character_profile("npc_locked", _locked)
locked_answer = call(set_location, "npc_locked", "Smoke Vault")
check("the refusal is the sentence route and ticker use", locked_answer,
      "This place is not accessible to you.")
check("no journey was started", travel_engine.get_journey("npc_locked"), None)
check("no movement target either", get_movement_target("npc_locked"), "")
check("and the character did not move",
      get_character_current_location("npc_locked"), HOME)
add_to_inventory("npc_locked", "silver_key")
key_answer = call(set_location, "npc_locked", "Smoke Vault")
check("with the key a journey starts",
      get_movement_target("npc_locked"), VAULT)
check_true("… and the answer names the target",
           "Smoke Vault" in key_answer, key_answer)

# ── [11] no raw engine reason reaches the character ─────────────────────
print("[11] travel_failed reasons are rendered in-fiction, never raw")
from app.core.system_prompt_builder import build_recent_activity_section  # noqa: E402
from app.models.diary import _process_state_entry  # noqa: E402

for who, reason in (("npc_unknown", "unknown_target"),
                    ("npc_water", "no_route"),
                    ("npc_ghost", "unplaced_target")):
    section = build_recent_activity_section(who)
    check_true(f"prompt: {reason} is not leaked raw",
               "travel to" in section and reason not in section, section)
    entry = _process_state_entry(last_state(who, "travel_failed")) or {}
    check_true(f"diary: {reason} is not leaked raw",
               reason not in (entry.get("content") or ""), entry.get("content"))

unknown_line = build_recent_activity_section("npc_unknown").splitlines()[-1]
ghost_line = build_recent_activity_section("npc_ghost").splitlines()[-1]
check("prompt: unplaced reads exactly like unknown",
      ghost_line.replace("Smoke Ghost", "X"),
      unknown_line.replace("Smoke Secret", "X"))
check_true("prompt: no_route has its own wording",
           "passable route" in build_recent_activity_section("npc_water"),
           build_recent_activity_section("npc_water"))

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
