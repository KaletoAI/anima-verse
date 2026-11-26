#!/usr/bin/env python3
"""Smoke: the acceptance play-through of quest stages 1 and 2 — "Errand" (stage 1) and
"The big rock" (stage 2) played end to end over the REAL routes.

PART 1 — Quest system stage 1, Task 13. The REAL `app.server` app through a `TestClient` without `with` (no lifespan: the
smoke calls `init_schema()`, `quest_types.register()` and `quest_engine.register()` itself, as
`smoke_quest_routes.py` / `smoke_play_quests.py` do). `STORAGE_DIR` / `INSTANCE_DIR` point at a throwaway
directory before `app.server` is imported. The session lookup is stubbed: the header `x-test-user` names the user —
"admin" (a dict, role admin) or "player" (the REAL `users` row of user "demo", allowed_characters [A],
settings.active_character A, so A is player-controlled) or "player2" (user "demo2", allowed_characters [A2],
settings.active_character A2, for PART 2).

Usage:
    ./.venv/bin/python scripts/smoke_quest_playthrough.py

FIXTURE (PART 1)
    Location L1 with rooms r1 (entry) and r2. Avatar A and NPC N both stand in L1/r1, language "en". Item "Lamp",
    nobody holds it. Game clock Y0001-D010T12:00:00, world FROZEN: every stamp of the play-through is that moment
    (a frozen world still evaluates a player's own action, plan D10), so L = GameTime.parse(that).display_label("en")
    is every done_label and the ended_label. By hand: day 10 of the first season (Spring) of year 1 at 12:00 ->
    L = "Spring, day 10 · 12:00 · Year 1" (GameTime.display_label, lang "en"); the smoke compares L against that
    literal once, then every label against L.
    "Errand" = the plan's reference quest: roles giver (character), place (room), thing (item); steps
    ① "Talk to the giver." spoke_with giver  ② "Go to the place." at_place place  ③ "Hold the thing." holds_item thing
    count 1. Bindings: giver {name N}, place {L1, r2}, thing {item_id Lamp}. The place is r2, NOT the room A stands
    in, so step ② is false until A walks; A holds no Lamp, so ③ is false until it is added. Steps are sequential and
    a cascade only goes on while the next step is already true — so each action below advances exactly one step.

WHAT FOLLOWS BY HAND (PART 1)
 1. Admin builds it (D13):
    POST /quests/templates with the reference quest -> 200, state "draft", revision 1, issues [].
    PUT {"state": "ready", "base_revision": 1} -> 200, state "ready", revision 2, issues [].
    POST /quests/templates/<id>/start {"bindings": ...} -> 200, state "open" (empty start condition), current_step 0
    (nobody has spoken with N yet).
 2. GET /play/quests as the player (call 1) -> 200, avatar "A", exactly one quest:
    {id R, title "Errand", summary "Run an errand for someone.", state "open",
     steps [{text "Talk to the giver.", state "current"}]}  — steps ② ③ are the future and withheld (D14); no
    time limit -> no time_left_label; no prerequisites -> no locked.
 3. Action 1 — N's reply to A: record_utterance(speaker N, addressees [A], source "loop") with both in L1/r1 ->
    utterance.heard with avatars [A] -> the engine stores the fact "A's mind has spoken with N's mind" and evaluates
    A: step ① passes, ② does not (A is in r1). drain(). GET /play/quests (call 2) -> state "open", steps
    [{text "Talk to the giver.", state "done", done_by "A", done_label L}, {text "Go to the place.", state "current"}].
 4. Action 2 — the player walks A to r2 through the REAL route POST /play/enter-room {"room_id": "r2"} with the
    player session -> 200 {"ok": true, "room_id": "r2"} (r2 is a room of A's location, no block rule, A is no party
    follower) -> save_character_current_room -> character.entered_room -> step ② passes, ③ does not (no Lamp). drain(). GET /play/quests (call 3) -> "open",
    steps [① done/A/L, ② done/A/L, {text "Hold the thing.", state "current"}].
 5. Action 3 — add_to_inventory(A, Lamp, 1) -> inventory.changed delta +1 -> step ③ passes, the run ends "done".
    drain(). GET /play/quests (call 4) -> the quest is ended: state "done", ended_label L, steps all three done
    (① ② ③ each done_by "A", done_label L), no "current" step, no time_left_label, no locked — the whole entry is
    exactly {id, title, summary, state "done", ended_label L, steps}.
    Calls 2 and 3 assert the entry's key set exactly {id, title, summary, state, steps} (an open run without a time
    limit or prerequisites), so a leaked quest-level field fails.
 6. GET /quests/runs as the admin -> exactly one run R: state "done", current_step 3, step_count 3, and a step_log
    of THREE entries, steps 0, 1, 2 in that order, each avatar "A", mind "A" (A is no linked body).

PART 2 — Quest system stage 2, Task 14: "The big rock" played end to end over the REAL routes with all media
stubbed (no LLM, no GPU, no image/mesh job). `quest_effects.pass_once()` is driven directly (no worker thread);
stubs are restored in `finally`.

FIXTURE (PART 2)
    Location L2 ("Wood", pos_x=100.0, pos_z=-50.0, map3d square boundary, entry_room "entry") with rooms
    "entry" ("Trailhead", layout w=4, d=4) and "glade" ("Glade", layout w=6, d=4).
    NPC N2 and Avatar A2 (player-controlled via user "demo2", header x-test-user: player2) both stand in L2/entry,
    language "en". Discovery stat key S read at run time from config "inventory.discovery_stat" with
    config_schema.field_default("inventory", "discovery_stat") fallback (never hardcoded).
    Bindings: giver -> {name: "N2"}, wood -> {location_id: "L2"}, glade -> {location_id: "L2", room_id: "glade"}.
    Frozen binding_labels: giver="N2", wood="Wood", glade="Glade".
    "The big rock": setup_effects [rock (create_prop near wood, offset_x=12, offset_z=-4, height_m=2.0),
    marker (create_prop permanent=True in room glade, height_m=1.0), box (create_item "Old tin box"),
    box_spot (place_item box in glade, hidden=True, difficulty=3), hint (give_hint to giver: "The box lies hidden
    in {glade}.")]; steps [s1 near_object rock radius_m=15, s2 knows_secret hint with on_done narrate,
    s3 found_item box_spot, s4 holds_item box count=1]; rewards [charm (create_item permanent=True, "Lucky charm",
    stat_bonuses={S: 5}, bonus_when="carried"), charm_given (give_item permanent=True, item=charm)].

WHAT FOLLOWS BY HAND (PART 2)
 1. Admin POST /quests/templates -> 200 draft rev 1 issues []; PUT ready rev 1 -> 200 ready rev 2 issues [];
    POST /quests/templates/<id>/start -> 200 state "preparing" (setup_effects non-empty), issues [].
 2. _step_setup applies setup_effects sequentially and stops at the first pending entry:
    - pass_once() #1 triggers rock (1 trigger call), stays "preparing".
    - Mark rock modeled & not pending -> pass_once() #2 writes rock placement at (100+12, -50-4) = (112.0, -54.0),
      triggers marker (2nd trigger call), still "preparing".
    - Mark marker modeled & not pending -> pass_once() #3 writes marker in L2/glade at [6/2, 4/2] = [3.0, 2.0],
      creates box, places box_spot (discovery_difficulty = 3 * 10 = 30), creates hint secret, opens run (state "open",
      current_step 0).
    - Object rows in creation order: rock (world_prop, prop), marker (room_prop, prop), box (item), box_spot
      (room_item), hint (secret) — all 7 "live". Both prop sidecars carry quest_run == run id.
 3. Prompt lines (quest_prompt.lines_for):
    - N2 -> ["You want an adventurer to: N2 lost something near Wood. \u2014 next: Find the big rock near Wood.",
             "You know something you may tell an adventurer who asks [secret <hint_sid>]: The box lies hidden in Glade."]
    - A2 -> [].
 4. s1 near_object (rock at (112.0, -54.0), radius 15 m):
    - A2 at (200.0, 0.0): hypot(88, 54) = 103.2 m > 15 m -> world_tick + drain() -> still current_step 0.
    - A2 at (115.0, -50.0): hypot(3, 4) = 5.0 m <= 15 m -> world_tick + drain() -> current_step 1.
 5. s2 knows_secret via share_secret verb:
    - N2 and A2 both in L2/entry; ShareSecretSkill.execute({"agent_name": "N2", "secret_id": hint_sid, "to": "A2"})
      -> "A2 now knows it." (plugins/share_secret/skill.py); secrets.knows(secret, "A2") is True;
      drain() -> current_step 2; pass_once() -> payout "step:1" is "applied" (narrate on_done).
 6. s3 found_item (difficulty 3 -> discovery_difficulty = 3 * 10 = 30):
    - A2 without discovery stat S (effective 0 < 30) -> placement_visible_to False, drain() -> still current_step 2.
    - A2 discovery stat S = 35 (>= 30) -> placement_visible_to True (emits item.discovered -> found fact),
      drain() -> current_step 3.
 7. s4 holds_item + reward:
    - inventory.pick_up_item("A2", "L2", "glade", box_id, 1) -> inventory.changed -> drain() -> state "done",
      current_step 4.
    - pass_once() -> payout "reward" is "applied"; A2 holds 1 charm; effective_stat(A2, S) == 35 + 5 = 40
      (bonus_when "carried"); GET /play/quests as player2 shows run state "done" with rewards_label == "Lucky charm"
      (quest_book.reward_items_label: single item quantity 1 -> item name).
 8. Cleanup after done (at most 2 pass_once() calls, idempotent):
    - rock world placement and prop sidecar gone ("reverted", "reverted");
    - box gone from A2's inventory, catalog, and glade (box "reverted", box_spot "gone" since already picked up);
    - hint secret gone ("reverted");
    - narrate utterance and found fact stay;
    - charm item and A2's charm stay ("live", "live");
    - marker prop and glade placement stay ("live", "live") and marker sidecar has NO "quest_run" key (D17 untag).
 9. Second run cancelled at step 1:
    - Start same template with same bindings -> pass_once until open (current_step 0, A2 far at (200.0, 0.0)),
      move A2 to (115.0, -50.0) + world_tick + drain() -> current_step 1.
    - POST /quests/runs/<id>/cancel -> 200 {"ok": True}; pass_once() ->
      run 2's rock placement + prop, box item + glade placement, and hint secret all gone ("reverted");
      run 2's permanent marker prop + glade placement stay ("live") and sidecar has no "quest_run";
      no reward paid for run 2 (A2 still holds 1 charm total).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


ERRAND = {
    "title": "Errand", "summary": "Run an errand for someone.", "gm_notes": "GM ONLY",
    "roles": [{"key": "giver", "kind": "character", "description": "who asks"},
              {"key": "place", "kind": "room", "description": "where to go"},
              {"key": "thing", "kind": "item", "description": "what to bring"}],
    "steps": [{"id": "s1", "text": "Talk to the giver.", "hint": "HINT ONE",
               "condition": {"type": "spoke_with", "params": {"character": "giver"}}},
              {"id": "s2", "text": "Go to the place.", "hint": "HINT TWO",
               "condition": {"type": "at_place", "params": {"place": "place"}}},
              {"id": "s3", "text": "Hold the thing.", "hint": "HINT THREE",
               "condition": {"type": "holds_item", "params": {"item": "thing", "count": 1}}}],
    "start_condition": {}, "prerequisites": {}, "time_limit_s": 0,
}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-playthrough-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__
    from app.server import app as server_app
    from app.core import auth_dependency, quest_engine, quest_types
    from app.core.db import init_schema
    from app.core.game_time import GameTime
    from app.core.perception import record_utterance
    from app.core.timeutils import set_game_time
    from app.core.users import create_user, get_user_by_id, update_user
    from app.models import character as chars, inventory, world
    from fastapi.testclient import TestClient
    import logging
    logging.disable(logging.INFO)  # request/event chatter; warnings still show
    init_schema()
    quest_types.register()
    quest_engine.register()

    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Front"}, {"id": "r2", "name": "Back"}]},
                          sync_world=False)
    for name in ("A", "N"):
        assert chars.save_character_profile(name, {"current_location": "L1", "current_room": "r1",
                                                   "language": "en"}, create_new=True), name
    player_id = create_user("demo", "smoke-password", allowed_characters=["A"])
    update_user(player_id, settings={"active_character": "A"})
    player2_id = create_user("demo2", "smoke-password", allowed_characters=["A2"])
    update_user(player2_id, settings={"active_character": "A2"})
    lamp = inventory.add_item("Lamp")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
    world.set_world_frozen(True)
    now = GameTime.parse("Y0001-D010T12:00:00").display_label("en")
    check("L is the hand-derived label", now, "Spring, day 10 · 12:00 · Year 1")
    bindings = {"giver": {"name": "N"}, "place": {"location_id": "L1", "room_id": "r2"},
                "thing": {"item_id": lamp}}

    def session_user(request):
        who = request.headers.get("x-test-user", "")
        if who == "admin":
            return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
        if who == "player":
            return get_user_by_id(player_id)
        if who == "player2":
            return get_user_by_id(player2_id)
        return None

    def done(text):
        return {"text": text, "state": "done", "done_by": "A", "done_label": now}

    with patch.object(auth_dependency, "_get_session_user", side_effect=session_user):
        client = TestClient(server_app)

        def call(method, path, body=None, role="admin"):
            return client.request(method, path, json=body, headers={"x-test-user": role})

        def book(label):
            resp = call("GET", "/play/quests", role="player")
            check(f"{label}: GET /play/quests 200", resp.status_code, 200)
            body = resp.json() if resp.status_code == 200 else {}
            check(f"{label}: avatar", body.get("avatar"), "A")
            quests = body.get("quests") or []
            check(f"{label}: one quest", len(quests), 1)
            return quests[0] if quests else {}

        print("[1] the admin builds and starts Errand")
        resp = call("POST", "/quests/templates", ERRAND)
        check("POST 200", resp.status_code, 200)
        tpl = resp.json() if resp.status_code == 200 else {}
        check("created draft", (tpl.get("state"), tpl.get("revision"), tpl.get("issues")), ("draft", 1, []))
        resp = call("PUT", f"/quests/templates/{tpl.get('id')}", {"state": "ready", "base_revision": 1})
        check("PUT ready 200", resp.status_code, 200)
        tpl = resp.json() if resp.status_code == 200 else {}
        check("ready", (tpl.get("state"), tpl.get("revision"), tpl.get("issues")), ("ready", 2, []))
        resp = call("POST", f"/quests/templates/{tpl.get('id')}/start", {"bindings": bindings})
        check("start 200", resp.status_code, 200)
        run = resp.json() if resp.status_code == 200 else {}
        check("run open at step 0", (run.get("state"), run.get("current_step")), ("open", 0))
        rid = run.get("id")

        print("[2] the quest book before anything happened")
        entry = book("call 1")
        check("call 1: entry", entry, {"id": rid, "title": "Errand", "summary": "Run an errand for someone.",
                                       "state": "open", "steps": [{"text": "Talk to the giver.",
                                                                   "state": "current"}]})

        print("[3] N answers A")
        record_utterance(speaker="N", content="Would you run an errand for me, A?", addressees=["A"],
                         source="loop")
        check("drain after the reply", quest_engine.drain(), True)
        entry = book("call 2")
        check("call 2: entry keys", sorted(entry), sorted(["id", "title", "summary", "state", "steps"]))
        check("call 2: head", (entry.get("id"), entry.get("title"), entry.get("summary"), entry.get("state")),
              (rid, "Errand", "Run an errand for someone.", "open"))
        steps = entry.get("steps") or []
        check("call 2: step count", len(steps), 2)
        check("call 2: step 1", steps[0] if steps else None, done("Talk to the giver."))
        check("call 2: step 2", steps[1] if len(steps) > 1 else None, {"text": "Go to the place.", "state": "current"})

        print("[4] A walks to the place")
        resp = call("POST", "/play/enter-room", {"room_id": "r2"}, role="player")
        check("POST /play/enter-room", (resp.status_code, resp.json()), (200, {"ok": True, "room_id": "r2"}))
        check("A is in r2", chars.get_character_current_room("A"), "r2")
        check("drain after the walk", quest_engine.drain(), True)
        entry = book("call 3")
        check("call 3: entry keys", sorted(entry), sorted(["id", "title", "summary", "state", "steps"]))
        check("call 3: head", (entry.get("id"), entry.get("title"), entry.get("summary"), entry.get("state")),
              (rid, "Errand", "Run an errand for someone.", "open"))
        steps = entry.get("steps") or []
        check("call 3: step count", len(steps), 3)
        check("call 3: step 1", steps[0] if steps else None, done("Talk to the giver."))
        check("call 3: step 2", steps[1] if len(steps) > 1 else None, done("Go to the place."))
        check("call 3: step 3", steps[2] if len(steps) > 2 else None, {"text": "Hold the thing.", "state": "current"})

        print("[5] A takes the thing")
        check("Lamp added", inventory.add_to_inventory("A", lamp, 1), True)
        check("drain after the item", quest_engine.drain(), True)
        entry = book("call 4")
        check("call 4: entry", entry, {
            "id": rid, "title": "Errand", "summary": "Run an errand for someone.", "state": "done",
            "ended_label": now,
            "steps": [done("Talk to the giver."), done("Go to the place."), done("Hold the thing.")]})

        print("[6] the admin's run list")
        resp = call("GET", "/quests/runs")
        check("GET /quests/runs 200", resp.status_code, 200)
        runs = (resp.json() if resp.status_code == 200 else {}).get("runs") or []
        check("one run", [r.get("id") for r in runs], [rid])
        row = runs[0] if runs else {}
        check("run done", (row.get("state"), row.get("current_step"), row.get("step_count")), ("done", 3, 3))
        log = row.get("step_log") or []
        check("three log entries", len(log), 3)
        check("log steps/avatar/mind", [(e.get("step"), e.get("avatar"), e.get("mind")) for e in log],
              [(0, "A", "A"), (1, "A", "A"), (2, "A", "A")])

        # ── PART 2: stage 2 reference quest "The big rock" ─────────────────────────────────────
        from app.core import config, db, hooks, item_images, props
        from app.core import quest_effects as qfx, quest_prompt as qp, stat_boosts
        from app.core.config_schema import field_default
        from app.core.keyed_lock import keyed_lock
        from app.models import quests as quests_mod, secrets, world_props
        from app.plugins.loader import discover_packages, load_plugin

        stat = config.get("inventory.discovery_stat", field_default("inventory", "discovery_stat"))
        world.upsert_location(
            {
                "id": "L2",
                "name": "Wood",
                "pos_x": 100.0,
                "pos_z": -50.0,
                "entry_room": "entry",
                "map3d": {"boundary": [[-20.0, -20.0], [20.0, -20.0], [20.0, 20.0], [-20.0, 20.0]]},
                "rooms": [
                    {"id": "entry", "name": "Trailhead", "layout": {"x": 0, "y": 0, "w": 4, "d": 4}},
                    {"id": "glade", "name": "Glade", "layout": {"x": 4, "y": 0, "w": 6, "d": 4}},
                ],
            },
            sync_world=False,
        )
        for name in ("N2", "A2"):
            assert chars.save_character_profile(
                name,
                {"current_location": "L2", "current_room": "entry", "language": "en"},
                create_new=True,
            ), name

        def set_stat_a2(val):
            with keyed_lock("character_profile", "A2"):
                prof = chars.get_character_profile("A2") or {}
                se = dict(prof.get("status_effects") or {})
                se[stat] = val
                prof["status_effects"] = se
                assert chars.save_character_profile("A2", prof)

        big_rock = {
            "title": "The big rock",
            "summary": "{giver} lost something near {wood}.",
            "gm_notes": "GM ONLY",
            "giver_role": "giver",
            "roles": [
                {"key": "giver", "kind": "character", "description": "who asks"},
                {"key": "wood", "kind": "location", "description": "the wood"},
                {"key": "glade", "kind": "room", "description": "where the box lies"},
            ],
            "setup_effects": [
                {"key": "rock", "type": "create_prop",
                 "params": {"name": "Big rock", "prompt": "a large mossy boulder",
                            "height_m": 2.0, "near": "wood", "offset_x": 12, "offset_z": -4}},
                {"key": "marker", "type": "create_prop", "permanent": True,
                 "params": {"name": "Stone marker", "prompt": "a small carved stone marker",
                            "height_m": 1.0, "room": "glade"}},
                {"key": "box", "type": "create_item",
                 "params": {"name": "Old tin box", "category": "tool"}},
                {"key": "box_spot", "type": "place_item",
                 "params": {"item": "box", "room": "glade", "hidden": True, "difficulty": 3}},
                {"key": "hint", "type": "give_hint",
                 "params": {"holder": "giver", "text": "The box lies hidden in {glade}."}},
            ],
            "steps": [
                {"id": "s1", "text": "Find the big rock near {wood}.", "hint": "",
                 "condition": {"type": "near_object", "params": {"object": "rock", "radius_m": 15}}},
                {"id": "s2", "text": "Find out where the box is.", "hint": "",
                 "condition": {"type": "knows_secret", "params": {"secret": "hint"}},
                 "on_done": [{"key": "told", "type": "narrate",
                              "params": {"text": "You remember the hollow under the roots."}}]},
                {"id": "s3", "text": "Find the tin box in {glade}.", "hint": "",
                 "condition": {"type": "found_item", "params": {"placement": "box_spot"}}},
                {"id": "s4", "text": "Bring the tin box.", "hint": "",
                 "condition": {"type": "holds_item", "params": {"item": "box", "count": 1}}},
            ],
            "rewards": [
                {"key": "charm", "type": "create_item", "permanent": True,
                 "params": {"name": "Lucky charm", "category": "tool",
                            "stat_bonuses": json.dumps({stat: 5}), "bonus_when": "carried"}},
                {"key": "charm_given", "type": "give_item", "permanent": True,
                 "params": {"item": "charm"}},
            ],
            "start_condition": {},
            "prerequisites": {},
            "time_limit_s": 0,
        }
        bindings2 = {
            "giver": {"name": "N2"},
            "wood": {"location_id": "L2"},
            "glade": {"location_id": "L2", "room_id": "glade"},
        }

        triggers = []
        pending_pids = set()
        modeled_pids = set()

        def fake_trigger(prop_id, **kwargs):
            triggers.append((prop_id, dict(kwargs)))
            pending_pids.add(prop_id)
            return True

        def fake_is_pending(prop_id=""):
            if prop_id:
                return [prop_id] if prop_id in pending_pids else []
            return sorted(pending_pids)

        orig_trigger = props.trigger_generation
        orig_is_pending = props.is_pending
        orig_has_model = qfx._prop_has_model
        orig_media_problem = qfx._prop_media_problem
        orig_item_gen = item_images.generate_item_image_sync
        props.trigger_generation = fake_trigger
        props.is_pending = fake_is_pending
        qfx._prop_has_model = lambda pid: pid in modeled_pids
        qfx._prop_media_problem = lambda: ""
        item_images.generate_item_image_sync = lambda item_id, overrides=None, *, raise_errors=False: True
        try:
            print("[P2.1] admin builds and starts The big rock")
            resp = call("POST", "/quests/templates", big_rock)
            check("p2 POST 200", resp.status_code, 200)
            tpl2 = resp.json() if resp.status_code == 200 else {}
            check("p2 created draft", (tpl2.get("state"), tpl2.get("revision"), tpl2.get("issues")),
                  ("draft", 1, []))
            resp = call("PUT", f"/quests/templates/{tpl2.get('id')}", {"state": "ready", "base_revision": 1})
            check("p2 PUT ready 200", resp.status_code, 200)
            tpl2 = resp.json() if resp.status_code == 200 else {}
            check("p2 ready", (tpl2.get("state"), tpl2.get("revision"), tpl2.get("issues")),
                  ("ready", 2, []))
            resp = call("POST", f"/quests/templates/{tpl2.get('id')}/start", {"bindings": bindings2})
            check("p2 start 200", resp.status_code, 200)
            run2 = resp.json() if resp.status_code == 200 else {}
            rid2 = run2.get("id")
            check("p2 starts preparing with no issues", (run2.get("state"), run2.get("issues")),
                  ("preparing", []))

            print("[P2.2] preparing -> open as both prop meshes land")
            qfx.pass_once()
            check("p2 still preparing while rock pending", quests_mod.get_run(rid2)["state"], "preparing")
            check("p2 1st trigger (rock)", len(triggers), 1)
            rock_pid = triggers[0][0]
            pending_pids.discard(rock_pid)
            modeled_pids.add(rock_pid)

            qfx.pass_once()
            check("p2 still preparing while marker pending", quests_mod.get_run(rid2)["state"], "preparing")
            check("p2 2nd trigger (marker)", len(triggers), 2)
            marker_pid = triggers[1][0]
            pending_pids.discard(marker_pid)
            modeled_pids.add(marker_pid)

            qfx.pass_once()
            run2_open = quests_mod.get_run(rid2)
            check("p2 open at step 0", (run2_open["state"], run2_open["current_step"]), ("open", 0))
            objs2 = quests_mod.list_objects(rid2)
            check(
                "p2 setup object rows live in order",
                [(o["effect_key"], o["kind"], o["status"], o["permanent"]) for o in objs2],
                [
                    ("rock", "world_prop", "live", False),
                    ("rock", "prop", "live", False),
                    ("marker", "room_prop", "live", True),
                    ("marker", "prop", "live", True),
                    ("box", "item", "live", False),
                    ("box_spot", "room_item", "live", False),
                    ("hint", "secret", "live", False),
                ],
            )
            check("p2 rock sidecar tagged", props.read_sidecar(rock_pid, read_only=True).get("quest_run"), rid2)
            check("p2 marker sidecar tagged", props.read_sidecar(marker_pid, read_only=True).get("quest_run"), rid2)
            rock_wp_id = objs2[0]["ref"]["placement_id"]
            marker_place_id = objs2[2]["ref"]["place_id"]
            box_id = objs2[4]["ref"]["item_id"]
            hint_sid = objs2[6]["ref"]["secret_id"]

            print("[P2.3] prompt lines for giver N2 and avatar A2")
            want_giver_line = "You want an adventurer to: N2 lost something near Wood. \u2014 next: Find the big rock near Wood."
            want_hint_line = (
                f"You know something you may tell an adventurer who asks [secret {hint_sid}]: "
                "The box lies hidden in Glade."
            )
            check("p2 lines_for N2", qp.lines_for("N2"), [want_giver_line, want_hint_line])
            check("p2 lines_for A2", qp.lines_for("A2"), [])

            print("[P2.4] s1 near_object")
            chars._write_character_pos("A2", 200.0, 0.0)
            hooks.emit("world_tick")
            check("p2 drain far", quest_engine.drain(), True)
            check("p2 still step 0 when far (103.2 m > 15 m)", quests_mod.get_run(rid2)["current_step"], 0)
            chars._write_character_pos("A2", 115.0, -50.0)
            hooks.emit("world_tick")
            check("p2 drain near", quest_engine.drain(), True)
            check("p2 step 1 after moving near (5.0 m <= 15 m)", quests_mod.get_run(rid2)["current_step"], 1)

            print("[P2.5] s2 knows_secret via share_secret verb")
            real_cfg_get = config.get
            with patch(
                "app.core.config.get",
                side_effect=lambda key, default=None: "share_secret" if key == "packages.enabled"
                else real_cfg_get(key, default),
            ):
                pkg = next((p for p in discover_packages(force=True) if p.id == "share_secret"), None)
            assert pkg is not None, "share_secret package missing"
            share_skill = dict(load_plugin(pkg))["share_secret"]
            reply = share_skill.execute(json.dumps({"agent_name": "N2", "secret_id": hint_sid, "to": "A2"}))
            check("p2 share_secret reply", reply, "A2 now knows it.")
            check("p2 A2 knows hint", secrets.knows(secrets.get_secret("N2", hint_sid), "A2"), True)
            check("p2 drain after share_secret", quest_engine.drain(), True)
            check("p2 step 2 after share_secret", quests_mod.get_run(rid2)["current_step"], 2)
            qfx.pass_once()
            payouts_s2 = {p["position"]: p["state"] for p in quests_mod.list_payouts(states=(), run_id=rid2)}
            check("p2 step:1 payout applied", payouts_s2.get("step:1"), "applied")

            print("[P2.6] s3 found_item")
            pl_box = next((p for p in inventory.get_room_items("L2", "glade") if p.get("item_id") == box_id), None)
            check("p2 box placement difficulty 30", pl_box is not None and pl_box.get("discovery_difficulty"), 30)
            check("p2 hidden without discovery stat (0 < 30)",
                  inventory.placement_visible_to("A2", "L2", "glade", pl_box), False)
            check("p2 drain before discovery", quest_engine.drain(), True)
            check("p2 still step 2 before discovery", quests_mod.get_run(rid2)["current_step"], 2)
            set_stat_a2(35)
            check("p2 visible with stat 35 >= 30", inventory.placement_visible_to("A2", "L2", "glade", pl_box), True)
            check("p2 drain after discovery", quest_engine.drain(), True)
            check("p2 step 3 after discovery", quests_mod.get_run(rid2)["current_step"], 3)

            print("[P2.7] s4 holds_item + reward + quest book")
            pickup = inventory.pick_up_item("A2", "L2", "glade", box_id, 1)
            check("p2 pick up box", pickup.get("success"), True)
            check("p2 drain after pickup", quest_engine.drain(), True)
            run2_done = quests_mod.get_run(rid2)
            check("p2 run done at step 4", (run2_done["state"], run2_done["current_step"]), ("done", 4))
            qfx.pass_once()
            payouts_done = {p["position"]: p["state"] for p in quests_mod.list_payouts(states=(), run_id=rid2)}
            check("p2 reward payout applied", payouts_done.get("reward"), "applied")
            charm_row = next((o for o in quests_mod.list_objects(rid2) if o["effect_key"] == "charm"), None)
            charm_id = charm_row["ref"]["item_id"] if charm_row else ""
            check("p2 A2 holds 1 charm", inventory.get_item_quantity("A2", charm_id), 1)
            check("p2 effective_stat 35 + 5 = 40",
                  stat_boosts.effective_stat(chars.get_character_profile("A2"), stat), 40)
            resp = call("GET", "/play/quests", role="player2")
            check("p2 GET /play/quests 200", resp.status_code, 200)
            book2 = resp.json() if resp.status_code == 200 else {}
            check("p2 quest book avatar A2", book2.get("avatar"), "A2")
            entry2 = next((q for q in (book2.get("quests") or []) if q.get("id") == rid2), {})
            check("p2 quest book done with rewards_label",
                  (entry2.get("state"), entry2.get("rewards_label")), ("done", "Lucky charm"))

            print("[P2.8] cleanup after done")
            qfx.pass_once()
            check("p2 rock world placement gone",
                  any(r["id"] == rock_wp_id for r in world_props.list_world_props()), False)
            check("p2 rock prop sidecar gone", bool(props.read_sidecar(rock_pid, read_only=True)), False)
            check("p2 box gone from A2, catalog, glade",
                  (inventory.get_item_quantity("A2", box_id),
                   inventory.get_item(box_id),
                   any(p.get("item_id") == box_id for p in inventory.get_room_items("L2", "glade"))),
                  (0, None, False))
            check("p2 hint secret gone", secrets.get_secret("N2", hint_sid), None)
            narrate_count = db.get_connection().execute(
                "SELECT COUNT(*) FROM utterances WHERE content=?",
                ("You remember the hollow under the roots.",),
            ).fetchone()[0]
            check("p2 narrate line stays", narrate_count >= 1, True)
            check("p2 found fact stays", quests_mod.has_fact("A2", "found", f"L2/glade/{box_id}"), True)
            check("p2 charm item and grant stay",
                  (inventory.get_item(charm_id) is not None, inventory.get_item_quantity("A2", charm_id)),
                  (True, 1))
            sc_marker = props.read_sidecar(marker_pid, read_only=True)
            check("p2 marker sidecar stays without quest_run",
                  (bool(sc_marker), "quest_run" in sc_marker), (True, False))
            glade_props = (world.get_room_by_id(world.get_location_by_id("L2"), "glade").get("layout") or {}).get("props") or []
            check("p2 marker glade placement stays",
                  any(p.get("id") == marker_place_id for p in glade_props), True)
            objs2_after = [o for o in quests_mod.list_objects(rid2) if o["kind"] != "marker"]
            check(
                "p2 object statuses after done cleanup",
                [(o["effect_key"], o["kind"], o["status"]) for o in objs2_after],
                [
                    ("rock", "world_prop", "reverted"),
                    ("rock", "prop", "reverted"),
                    ("marker", "room_prop", "live"),
                    ("marker", "prop", "live"),
                    ("box", "item", "reverted"),
                    ("box_spot", "room_item", "gone"),
                    ("hint", "secret", "reverted"),
                    ("charm", "item", "live"),
                    ("charm_given", "grant", "live"),
                ],
            )

            print("[P2.9] second run cancelled at step 1")
            triggers.clear()
            chars._write_character_pos("A2", 200.0, 0.0)
            resp = call("POST", f"/quests/templates/{tpl2.get('id')}/start", {"bindings": bindings2})
            check("p2 run2 start 200", resp.status_code, 200)
            rid3 = (resp.json() if resp.status_code == 200 else {}).get("id")
            qfx.pass_once()
            rock2_pid = triggers[0][0]
            pending_pids.discard(rock2_pid)
            modeled_pids.add(rock2_pid)
            qfx.pass_once()
            marker2_pid = triggers[1][0]
            pending_pids.discard(marker2_pid)
            modeled_pids.add(marker2_pid)
            qfx.pass_once()
            check("p2 run2 open at step 0",
                  (quests_mod.get_run(rid3)["state"], quests_mod.get_run(rid3)["current_step"]),
                  ("open", 0))
            objs3 = quests_mod.list_objects(rid3)
            rock2_wp_id = objs3[0]["ref"]["placement_id"]
            marker2_place_id = objs3[2]["ref"]["place_id"]
            box2_id = objs3[4]["ref"]["item_id"]
            hint2_sid = objs3[6]["ref"]["secret_id"]

            chars._write_character_pos("A2", 115.0, -50.0)
            hooks.emit("world_tick")
            check("p2 run2 drain step 1", quest_engine.drain(), True)
            check("p2 run2 current_step 1", quests_mod.get_run(rid3)["current_step"], 1)

            resp = call("POST", f"/quests/runs/{rid3}/cancel")
            check("p2 run2 cancel 200 ok", (resp.status_code, resp.json()), (200, {"ok": True}))
            qfx.pass_once()
            check("p2 run2 rock placement + prop gone",
                  (any(r["id"] == rock2_wp_id for r in world_props.list_world_props()),
                   bool(props.read_sidecar(rock2_pid, read_only=True))),
                  (False, False))
            check("p2 run2 box item + glade placement gone",
                  (inventory.get_item(box2_id),
                   any(p.get("item_id") == box2_id for p in inventory.get_room_items("L2", "glade"))),
                  (None, False))
            check("p2 run2 hint secret gone", secrets.get_secret("N2", hint2_sid), None)
            sc_marker2 = props.read_sidecar(marker2_pid, read_only=True)
            glade_props2 = (world.get_room_by_id(world.get_location_by_id("L2"), "glade").get("layout") or {}).get("props") or []
            check("p2 run2 permanent marker stays untagged",
                  (bool(sc_marker2), "quest_run" in sc_marker2,
                   any(p.get("id") == marker2_place_id for p in glade_props2)),
                  (True, False, True))
            check("p2 run2 no reward paid (A2 still holds 1 charm)",
                  (inventory.get_item_quantity("A2", charm_id),
                   sum(e.get("quantity", 1) for e in (inventory.get_character_inventory("A2") or {}).get("inventory", [])
                       if (inventory.get_item(e.get("item_id")) or {}).get("name") == "Lucky charm")),
                  (1, 1))
        finally:
            props.trigger_generation = orig_trigger
            props.is_pending = orig_is_pending
            qfx._prop_has_model = orig_has_model
            qfx._prop_media_problem = orig_media_problem
            item_images.generate_item_image_sync = orig_item_gen

    quest_engine.drain()
    if FAILURES:
        print(f"FAIL smoke_quest_playthrough: {len(FAILURES)} failed")
        return 1
    print("PASS smoke_quest_playthrough")
    return 0


if __name__ == "__main__":
    sys.exit(main())
