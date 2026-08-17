#!/usr/bin/env python3
"""Smoke run for AVATAR travel over the /play routes
(Seamless World, E3 Task 5).

Runs against a THROWAWAY storage directory — never touches a real world.
Route level: the handler functions of ``app/routes/play.py`` are called
directly (a minimal request stand-in supplies the JSON body), so the whole
gate chain runs exactly as it does behind uvicorn — without a server.

Rules every expectation below is derived from BY HAND:

  * ``POST /play/travel`` is the avatar's counterpart of the SetLocation
    journey branch. It applies the SAME gates in the SAME order as
    ``plugins/movement/skill_set_location.py`` does before it journeys:
    leave rules (``rules.check_leave``) → location access
    (``danger_system.check_location_access``) → the mechanics
    (``travel_engine.start_journey``). A party FOLLOWER is refused before
    all of them — it is dragged along by its leader and owns no movement.
  * The engine's own reasons pass through unchanged: ``unknown_target``,
    ``unplaced_target``, ``no_route`` (Task 2). They are answers, not
    errors — 200 with ``journey: null``. A RULE refusal is a 403 with the
    rule's own sentence, like every other blocked move in the player UI.
  * The gates sit at the START. ``start_journey`` itself checks no rule at
    all (it is pure mechanics), so a blocked target that is nevertheless
    reachable would produce a perfectly walkable journey — pinned below so
    the route can never quietly stop applying the gate. The ticker's
    arrival gate stays the SECOND net (Task 3), not the first.
  * ``journey_state`` is a pure function of the GAME clock, which is pinned
    here (``set_game_factor(0.0)`` + ``set_game_time(GameTime)``) so the ETA
    is an exact statement, not a race against wall time. Game time is the
    world calendar: the clock is pinned to ``Y0001-D001T12:00:00`` and every
    arrival stamp is canonical, never an ISO datetime and never in a
    timezone.
  * The grid compass is GONE: ``compute_avatar_neighbors``,
    ``move_avatar_step``, ``neighbor_access`` and the two ``/world/avatar/*``
    routes existed for a world of square cells that E1 deleted. Deletion
    test: no source reference left under ``app/`` or ``frontend/src``, no
    such route on the app, and ``/play/scene`` carries no ``neighbors``
    block any more. (``client3d/`` is E4 and deliberately not swept.)

The world used below (all grass unless painted):

    HOME    (0, 0)     w 10, opening S at 0.5 → (0, 5)   — where the avatar is
    MARKET  (100, 0)   w 10, opening W at 0.5 → (95, 0)  — the normal target
    GATE    (0, 100)   w 10, opening N at 0.5 → (0, 95)  — blocked by a rule
    LOCKED  (-100, 0)  w 10, opening E at 0.5,
                       accessible_when ["has_item:silver_key"]
    SECRET  (200, 0)   w 10, placed, NOT in known_locations
    ISLE    (0, 300)   w 10, known + placed, ringed by water
    GHOST   —          known, never placed

Hand-derived expectations:

  [1] HOME → MARKET starts a journey: the answer carries
      ``journey.target_id`` = MARKET, the ETA as the CANONICAL game stamp of
      ``journey_state(...)['eta_game']`` plus the two display strings the
      server renders from it (``eta_hhmm``, ``eta_label`` — one vocabulary
      with the worldmap block, § A11) and the walked distance; the profile holds a v2 journey (waypoints, no ``path``)
      with ``movement_target`` = MARKET, and the avatar still STANDS in
      HOME — the ticker performs arrivals, the route does not.

  [2] ``POST /play/travel/cancel`` drops journey + movement target and
      reports the abandoned target; a second call answers "nothing to
      cancel" (``cancelled: false``) instead of failing.

  [3] The three engine reasons pass through as ``{journey: null, reason}``:
      SECRET → ``unknown_target``, GHOST → ``unplaced_target``,
      ISLE → ``no_route``. None of them writes a journey.

  [4] A party FOLLOWER is refused with 403 / ``party_follower`` — before
      any rule is consulted, and without a journey.

  [5] A block rule with ``action="leave"`` on HOME refuses the start with
      403 / ``block_leave`` and the rule's own message. No journey.

  [6] A block rule with ``action="enter"`` on GATE refuses the start with
      403 / ``block_enter`` and the rule's own message. No journey — while
      ``start_journey`` called directly still produces one (proof that the
      gate is the ROUTE's and not the engine's).

  [6b] ``accessible_when`` on the TARGET is a WALL, not a hint
      (backend-status-3d.md, commit bdd8598 "a wall now, not a hint"). No
      rule row backs that field — ``check_access`` does not read it — so
      this route is its ONLY enforcement point since the grid step went.
      LOCKED wants ``has_item:silver_key``: without the key 403 /
      ``not_accessible`` and no journey, with the key in the inventory the
      very same trip starts. (The net this replaces lived in
      ``smoke_enterable`` part 6, which the compass carried away.)

  [7] ``GET /play/scene`` carries the running journey in a ``travel`` block
      (target id + name + canonical ETA + its HH:MM + metres) and ``null`` when there is
      none — the player UI's poll channel.

  [8] The destination list's data source: ``GET /play/worldmap`` (fogged)
      carries every location entry's ``passable`` flag, so the panel can
      drop transit tiles the way the LLM's target list does.

  [9] The compass deletion test (see above).

  [10] ``GET /play/scene`` in the WILDERNESS (E6): without a location there
      is no room to list, so the neighbours are everyone within the hearing
      radius — the same roster the prompts and TalkTo use. Hand-derived with
      the default radius of 20 m (``perception.DEFAULT_HEARING_RADIUS_M``,
      nothing configured here), the avatar standing at (50, 0):
        npc_close (55, 0)  -> hypot(5, 0)   =  5.0 m <= 20  -> present
        npc_far   (55, 60) -> hypot(5, 60)  = 60.2 m  > 20  -> not present
      ``present_detail`` carries exactly the same names.

Usage:  ./.venv/bin/python scripts/smoke_avatar_travel.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]

STORAGE = Path(tempfile.mkdtemp(prefix="avatar-travel-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="avatar-travel-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import (game_time, set_game_factor,  # noqa: E402
                                set_game_time)
from app.core.party_engine import add_to_party  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_movement_target,
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.inventory import add_item, add_to_inventory  # noqa: E402
from app.models.rules import add_rule, delete_rule  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)
from app.routes.play import (  # noqa: E402
    play_scene, play_travel, play_travel_cancel, play_worldmap)

FAILURES = []
CHECKED = 0

START_GT = GameTime.parse("Y0001-D001T12:00:00")
USER = {"username": "demo", "role": "user"}


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


class _FakeRequest:
    """Minimal stand-in: the route only ever awaits ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (scale anchor, openings)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def place(name: str, x: float, z: float, edge: str) -> str:
    loc_id = add_location(name=name, description="avatar travel smoke")["id"]
    update_location_position(loc_id, x, z)
    set_map3d(loc_id, plan_width_m=10.0,
              boundary_openings=[{"edge": edge, "at": 0.5, "width_m": 4.0,
                                  "type": "passage"}])
    return loc_id


def travel(target_id: str):
    """POST /play/travel → ("ok", payload) or ("refused", detail)."""
    try:
        return "ok", asyncio.run(play_travel(
            _FakeRequest({"target_id": target_id}), user=USER))
    except HTTPException as exc:
        return "refused", exc.detail


def new_character(name: str, location_id: str, x: float, z: float,
                  known) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    if location_id:
        save_character_current_location(name, location_id)
    set_character_pos(name, x, z)
    set_known_locations(name, list(known))


# ── the world ───────────────────────────────────────────────────────────
set_game_factor(0.0)
set_game_time(START_GT)

HOME = place("Smoke Home", 0.0, 0.0, "S")
MARKET = place("Smoke Market", 100.0, 0.0, "W")
GATE = place("Smoke Gate", 0.0, 100.0, "N")
LOCKED = place("Smoke Vault", -100.0, 0.0, "E")
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == LOCKED:
        _loc["accessible_when"] = ["has_item:silver_key"]
_save_world_data(_data)
add_item(name="Silver Key", description="opens the vault",
         item_id="silver_key")
SECRET = place("Smoke Secret", 200.0, 0.0, "W")
ISLE = place("Smoke Isle", 0.0, 300.0, "N")
GHOST = add_location(name="Smoke Ghost", description="never placed")["id"]
# A water ring wide enough that the nav grid's rescue radius cannot escape it
# — ISLE is genuinely unreachable, not merely awkward.
terrain.save_area({"kind": "deep_water",
                   "polygon": [[-40, 260], [40, 260], [40, 340], [-40, 340]],
                   "z_order": 0})

KNOWN = [HOME, MARKET, GATE, LOCKED, ISLE, GHOST]
new_character("demo_avatar", HOME, 0.0, 0.0, KNOWN)
set_active_character("demo_avatar")


def main() -> int:
    print("\n[1] POST /play/travel starts the avatar's journey")
    status, payload = travel(MARKET)
    check("the call succeeded", status, "ok")
    journey = travel_engine.get_journey("demo_avatar")
    check_true("a journey exists on the profile", journey is not None, payload)
    check("movement_target", get_movement_target("demo_avatar"), MARKET)
    check("the avatar has NOT arrived (the ticker does that)",
          get_character_current_location("demo_avatar"), HOME)
    block = (payload or {}).get("journey") if status == "ok" else None
    check_true("the answer carries a journey block", block is not None, payload)
    if block and journey is not None:
        check("the answered target", block.get("target_id"), MARKET)
        check("the answered target name", block.get("target_name"),
              "Smoke Market")
        state = travel_engine.journey_state(
            journey["waypoints"], journey["started_at_game"], game_time())
        # ONE vocabulary with the worldmap block (§ A11, E3 Task 6):
        # eta_game is the CANONICAL game stamp in both payloads, and both
        # render the display strings beside it server-side — no client ever
        # slices a stamp.
        eta = GameTime.parse(state["eta_game"])
        check("the answered eta_game (canonical)", block.get("eta_game"),
              state["eta_game"])
        check("the answered ETA as game wall-clock time",
              block.get("eta_hhmm"), eta.time_hhmm())
        check("the answered ETA label", block.get("eta_label"),
              eta.label("en"))
        check("the answered distance", block.get("total_m"), state["total_m"])
        check("the journey is v2 (waypoints, no path)",
              "waypoints" in journey and "path" not in journey, True)
    check("no reason on a successful start",
          (payload or {}).get("reason") if status == "ok" else "?", "")

    print("\n[2] POST /play/travel/cancel drops the journey")
    res = asyncio.run(play_travel_cancel(user=USER))
    check("cancelled", res.get("cancelled"), True)
    check("the abandoned target is reported", res.get("target_id"), MARKET)
    check("no journey left", travel_engine.get_journey("demo_avatar"), None)
    check("no movement target left", get_movement_target("demo_avatar"), "")
    check("the avatar stayed where it was",
          get_character_current_location("demo_avatar"), HOME)
    res = asyncio.run(play_travel_cancel(user=USER))
    check("a second cancel is a no-op, not a failure",
          res.get("cancelled"), False)

    print("\n[3] the engine reasons pass through unchanged")
    for label, target, reason in (("unknown (not in known_locations)", SECRET,
                                   "unknown_target"),
                                  ("known but unplaced", GHOST,
                                   "unplaced_target"),
                                  ("known, placed, behind water", ISLE,
                                   "no_route")):
        status, payload = travel(target)
        check(f"{label} → status", status, "ok")
        check(f"{label} → reason", (payload or {}).get("reason"), reason)
        check(f"{label} → no journey block", (payload or {}).get("journey"),
              None)
        check(f"{label} → nothing stored",
              travel_engine.get_journey("demo_avatar"), None)

    print("\n[4] a party follower owns no movement")
    new_character("demo_leader", HOME, 0.0, 0.0, KNOWN)
    check_true("the party was formed",
               add_to_party("demo_leader", "demo_avatar") is not None)
    status, detail = travel(MARKET)
    check("the call was refused", status, "refused")
    check("the refusal reason",
          (detail or {}).get("reason") if isinstance(detail, dict) else detail,
          "party_follower")
    check("no journey was started",
          travel_engine.get_journey("demo_avatar"), None)
    from app.core.party_engine import leave_party  # noqa: E402
    leave_party("demo_avatar")
    check("the avatar left the party again",
          travel_engine.get_journey("demo_avatar"), None)

    print("\n[5] a leave rule refuses the start")
    rule = add_rule({"type": "block", "action": "leave", "name": "Pinned",
                     "condition": "always",
                     "message": "You promised to wait here.",
                     "target": {"scope": "location", "location_id": HOME}})
    status, detail = travel(MARKET)
    check("the call was refused", status, "refused")
    check("the refusal reason", (detail or {}).get("reason"), "block_leave")
    check("the rule's own sentence is passed on",
          (detail or {}).get("message"), "You promised to wait here.")
    check("no journey was started",
          travel_engine.get_journey("demo_avatar"), None)
    delete_rule(rule["id"] if isinstance(rule, dict) else rule)
    status, _ = travel(MARKET)
    check("without the rule the same trip starts", status, "ok")
    asyncio.run(play_travel_cancel(user=USER))

    print("\n[6] an access rule on the TARGET refuses the start")
    rule = add_rule({"type": "block", "action": "enter", "name": "Barred gate",
                     "condition": "always",
                     "message": "The gate is barred.",
                     "target": {"scope": "location", "location_id": GATE}})
    status, detail = travel(GATE)
    check("the call was refused", status, "refused")
    check("the refusal reason", (detail or {}).get("reason"), "block_enter")
    check("the rule's own sentence is passed on",
          (detail or {}).get("message"), "The gate is barred.")
    check("no journey was started",
          travel_engine.get_journey("demo_avatar"), None)
    # The engine knows no rules: called directly it walks straight through the
    # barred gate. That is precisely why the gate has to sit in the route.
    engine_journey, engine_reason = travel_engine.start_journey(
        "demo_avatar", GATE)
    check("start_journey alone ignores the rule", engine_reason, "")
    check_true("… and produces a real journey", engine_journey is not None)
    travel_engine.cancel_journey("demo_avatar")
    delete_rule(rule["id"] if isinstance(rule, dict) else rule)

    print("\n[6b] accessible_when on the target is a wall, not a hint")
    status, detail = travel(LOCKED)
    check("without the key the call was refused", status, "refused")
    check("the refusal reason", (detail or {}).get("reason"), "not_accessible")
    check("the sentence is the one the map greys a place out with",
          (detail or {}).get("message"),
          "This place is not accessible to you.")
    check("no journey was started",
          travel_engine.get_journey("demo_avatar"), None)
    # The condition is not backed by any rule row: the access gate the ticker
    # applies on arrival would let the avatar walk right in, which is why the
    # check has to happen HERE.
    from app.models.rules import check_access  # noqa: E402
    check("no rule row backs the condition",
          check_access("demo_avatar", LOCKED), (True, ""))
    add_to_inventory("demo_avatar", "silver_key")
    status, payload = travel(LOCKED)
    check("with the key the same trip starts", status, "ok")
    check("… and it really is a journey",
          bool((payload or {}).get("journey")), True)
    asyncio.run(play_travel_cancel(user=USER))

    print("\n[7] GET /play/scene carries the running journey")
    scene = asyncio.run(play_scene(user=USER))
    check("no travel while standing still", scene.get("travel"), None)
    travel(MARKET)
    scene = asyncio.run(play_scene(user=USER))
    trav = scene.get("travel") or {}
    check("the travelling target", trav.get("target_id"), MARKET)
    check("the travelling target name", trav.get("target_name"), "Smoke Market")
    journey = travel_engine.get_journey("demo_avatar")
    state = travel_engine.journey_state(
        journey["waypoints"], journey["started_at_game"], game_time())
    check("the canonical ETA", trav.get("eta_game"), state["eta_game"])
    check("the ETA in game wall-clock time", trav.get("eta_hhmm"),
          GameTime.parse(state["eta_game"]).time_hhmm())
    check("the total distance", trav.get("total_m"), state["total_m"])
    asyncio.run(play_travel_cancel(user=USER))

    print("\n[8] the destination list's data source")
    wm = asyncio.run(play_worldmap(user=USER, show_all=0))
    check("the payload is fogged", wm.get("fogged"), True)
    entries = {e["id"]: e for e in wm.get("locations", [])}
    check_true("the known target is on the map", MARKET in entries)
    check_true("the UNKNOWN location is not", SECRET not in entries,
               sorted(entries))
    check("every entry carries a passable flag",
          sorted({("passable" in e) for e in wm.get("locations", [])}), [True])
    check("a normal location is no transit tile",
          entries.get(MARKET, {}).get("passable"), False)

    print("\n[9] the grid compass is gone without replacement")
    grep = subprocess.run(
        ["grep", "-rn", "-e", "compute_avatar_neighbors", "-e",
         "move_avatar_step", "-e", "neighbor_access", "-e", "avatar/step",
         "-e", "avatar/neighbors", "app", "frontend/src"],
        cwd=REPO, capture_output=True, text=True)
    check("no source reference under app/ or frontend/src left",
          grep.stdout.strip(), "")
    # The routers themselves, not the composed app: importing app.server
    # would boot the configured world (config + world.db), and a smoke must
    # never reach into a real one.
    from app.routes.play import router as play_router  # noqa: E402
    from app.routes.world import router as world_router  # noqa: E402
    world_paths = {getattr(r, "path", "") for r in world_router.routes}
    play_paths = {getattr(r, "path", "") for r in play_router.routes}
    check("no /world/avatar/step route",
          "/world/avatar/step" in world_paths, False)
    check("no /world/avatar/neighbors route",
          "/world/avatar/neighbors" in world_paths, False)
    check_true("the travel routes exist instead",
               {"/play/travel", "/play/travel/cancel"} <= play_paths,
               sorted(p for p in play_paths if "travel" in p))
    scene = asyncio.run(play_scene(user=USER))
    check("no neighbors block in /play/scene", "neighbors" in scene, False)
    check("no entry_room_name in /play/scene either",
          "entry_room_name" in scene, False)
    check_true("the room chips are untouched", bool(scene.get("rooms")) or
               scene.get("rooms") == [], scene.get("rooms"))

    print("\n[10] out in the open the scene lists who is within earshot")
    new_character("npc_close", "", 55.0, 0.0, [])
    new_character("npc_far", "", 55.0, 60.0, [])
    set_character_pos("demo_avatar", 50.0, 0.0)
    scene = asyncio.run(play_scene(user=USER))
    check("the avatar stands in the wilderness", scene.get("location_id"), "")
    check("present = everyone inside the hearing radius",
          sorted(scene.get("present") or []), ["npc_close"])
    check("… and the portraits follow the same list",
          sorted(d["name"] for d in (scene.get("present_detail") or [])),
          ["npc_close"])

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
