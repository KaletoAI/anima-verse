#!/usr/bin/env python3
"""Smoke: the four-part acceptance play-through of quest stages 1 to 3 — "Errand" (stage 1),
"The big rock" (stage 2), "A mug for the guard" (conversation quest under a frozen clock), and
stage 3 (admin LLM generation, automatic NPC quest, and llm_judgement) played end to end over the
REAL routes and the real task queue.

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

PART 3 — Conversation quest ("A mug for the guard") under a FROZEN game clock (world_frozen=True,
game_time stays Y0001-D010T12:00:00 throughout), exercising spoke_with since_step (system-time
ordering), give_item, take_item, and step role_notes end to end over the REAL routes.

FIXTURE (PART 3)
    Avatar A (moved back to L1/r1), NPC N (host, in L1/r1), NPC W (guard, in L1/r1), stackable item
    "Ale" (nobody holds it). Before the quest starts, N and W each speak to A (record_utterance
    source="loop" -> both spoke_with facts already exist in quest_facts).
    Template: roles host (character), guard (character), ale (item); giver_role "host".
    - Step 0 "Ask {host} for the ale.": spoke_with(host, since_step=True); on_done [give_item(ale)];
      role_notes [{role: "host", text: "Hand the adventurer a jug of ale for {guard}."}].
    - Step 1 "Bring the ale to {guard}.": all[spoke_with(guard, since_step=True), holds_item(ale, 1)];
      on_done [take_item(ale, to="guard")]; role_notes [{role: "guard", text: "You are waiting for your ale."}].

WHAT FOLLOWS BY HAND (PART 3)
 1. Start -> state "open", current_step 0 (pre-start talks do NOT fulfil since_step=True).
    lines_for("N") contains 'Quest "A mug for the guard": Hand the adventurer a jug of ale for W.';
    lines_for("W") == [].
 2. W speaks to A -> current_step stays 0.
 3. N speaks to A -> step 0 done, current_step 1, state "open"; pass_once() -> A holds 1 Ale.
    Step 1 is NOT fulfilled yet (W's talk happened before step 1 started).
    lines_for("N") no longer contains the host role note;
    lines_for("W") == ['Quest "A mug for the guard": You are waiting for your ale.'].
 4. W speaks to A -> run state "done"; pass_once() -> A holds 0 Ale, W holds 1 Ale.
 5. GET /play/quests as player -> 200; neither "role_notes" nor "step_started_at" appears in resp.text.
 6. Game clock stayed frozen at Y0001-D010T12:00:00 throughout PART 3.

PART 4 — Quest system stage 3, Task 7: admin LLM generation (4a), automatic NPC quest (4b), and
llm_judgement under a frozen clock (4c) played end to end over the REAL routes and the real
TaskQueue, with `llm_router.llm_call` stubbed and every unexpected LLM task failing the check.
Without FastAPI lifespan, the smoke calls `quest_authoring.register()`, `quest_auto.register()`,
and `quest_judgement.register()` itself.

FIXTURE (PART 4)
    Location L4 ("Courtyard", entry_room "r1") with rooms "r1" ("Gate") and "r2" ("Well").
    Avatar A is moved to L4/r1; awake non-avatar NPC G4 is created in L4/r1 (language "en").
    Active avatars in `account.get_all_avatars()` are {"A", "A2"} (from "demo" and "demo2").
    `quest_auto.pick_giver()` iterates `sorted(avatars)` -> "A" first ("A" < "A2"); A is at
    L4/r1, and among non-avatar characters not in `live_givers()`, only G4 stands at L4 (in the
    same room r1, awake), so `pick_giver()` deterministically answers `("G4", "A")`.

WHAT FOLLOWS BY HAND (PART 4)
 4a. Admin generates a quest (Decision 4 — stored as an ordinary draft, starts nothing):
     - POST /quests/generate {"brief": "Check the courtyard well", "giver": "G4"} -> 202 with
       non-empty task_id.
     - Poll GET /quests/generate/jobs until finished -> status "completed", state "done", ok True,
       issues [], bindings == {"giver": {"name": "G4"}, "place": {"location_id": "L4", "room_id": "r2"}}.
       LLM tasks invoked: ["quest_draft", "quest_structure"].
     - GET /quests/templates/<tpl4a_id> -> 200, state "draft", origin "admin", kept True, rev 1,
       issues []. Before starting, 0 runs exist for <tpl4a_id>.
     - PUT {"state": "ready", "base_revision": 1} -> 200, state "ready", rev 2, issues [].
     - POST /quests/templates/<tpl4a_id>/start {"bindings": job["bindings"]} -> 200, state "open",
       current_step 0 (step 0 is at_place L4/r2 while A stands in L4/r1).
     - POST /quests/runs/<run4a_id>/cancel -> 200 {"ok": True}, freeing G4 from `live_givers()`
       before 4b.
 4b. Automatic quest offered by an NPC beside the avatar (Decision 5):
     - Default expiry from config_schema: `field_default("quests", "auto_expiry_game_hours")` == 48
       -> `time_limit_s` == 48 * 3600 == 172800 game seconds.
     - World briefly unfrozen (`world.set_world_frozen(False)`), `quest_auto.auto_enabled` patched
       to True; `quest_auto.pick_giver()` == `("G4", "A")`.
     - `quest_auto.tick()` -> `{"queued": <task_id>, "giver": "G4", "avatar": "A"}` on the real
       task queue; LLM stub returns prose on `quest_draft` and a valid auto `json:quest` block on
       `quest_structure` (title "Water from {place}", summary "Water from {place} for {giver}.",
       giver_role "giver" -> G4, step 0 at_place -> L4/r2 so dry_check sees step 0 false for A in
       L4/r1, start_condition {}, no create_prop). LLM tasks invoked: ["quest_draft", "quest_structure"].
     - Exactly 1 template with origin "auto": state "ready", kept False, time_limit_s == 172800;
       hidden from default `GET /quests/templates` (generated=0) and listed in `?generated=1`.
     - Exactly 1 run of that template: state "open", started_by "auto", giver bound to {"name": "G4"},
       non-empty `expires_at`; `quest_auto.open_auto_count()` == 1.
     - `quest_prompt.lines_for("G4")` ==
       `["You want an adventurer to: Water from Well for G4. \u2014 next: Check Well for G4."]`
       (`quest_prompt` renders `summary`, falling back to `title` when `summary` is empty; here the
       rendered line also contains the rendered quest title "Water from Well").
     - GET /play/quests as player -> 200, lists the open run with title "Water from Well", and
       resp.text contains none of "origin", "kept", "gm_notes".
     - Cancel the auto run via POST /quests/runs/<run4b_id>/cancel -> 200 {"ok": True}, and
       re-freeze the world (`world.set_world_frozen(True)`).
 4c. `llm_judgement` step passes on a stubbed "yes" verdict under a frozen game clock (Decisions 1–3):
     - World is frozen (`world.is_world_frozen()` is True); record `t4c_start_game = game_time().canonical()`
       (within <= 5 s of PART 3's frozen stamp after 4b's brief thaw).
     - Admin POST /quests/templates with role `giver` (character) and step 0
       `{"type": "llm_judgement", "params": {"criterion": "{giver} was asked about the lost lamp"}}`
       -> 200 draft; PUT ready -> 200 ready; POST .../start with giver -> G4 -> 200 state "open",
       current_step 0. (`start_run` emits no signal and does not evaluate, so 0 judgements exist yet;
       `quest_judgement.min_interval_s` is patched to 0.0 so no 30 s cooldown can gate a claim.)
     - `perception_store.get_character_stream_since` truncates `step_started_at` to whole UTC seconds
       and filters strictly (`u.ts > since_sec`), so A's line is recorded at
       `ts = (parse_iso(step_started_at) + 1 s)` in L4/r1:
       `record_utterance(speaker="A", content="G4, have you seen my lost lamp?", addressees=["G4"], ...)`.
     - `utterance.heard` -> `quest_engine._heard` sees `speaker_is_avatar=True` and evaluates A on
       `utterance.spoken` -> `_llm_judgement` claims the slot and submits `quest_judgement` to the
       real task queue -> `quest_judgement.handle` calls `llm_call("quest_judgement", ...)` -> stub
       returns fenced `{"passed": true, "reason": "A asked G4 about the lamp."}` -> `set_judgement`
       stores state "yes" and notifies `quest.judged` -> engine worker evaluates A, `record_step_done`
       completes the 1-step run (`state == "done"`, `current_step == 1`, `step_log` [(0, "A", "A")])
       and in the SAME transaction deletes `quest_judgements` rows with `step <= 0`.
     - Therefore, once the run is "done":
       * LLM tasks invoked in 4c: `["quest_judgement"]`; `user_prompt` contains both
         `"G4 was asked about the lost lamp"` and `"A -> G4: G4, have you seen my lost lamp?"`.
       * `quests.list_judgements(run4c_id)` == `[]`, and `GET /quests/runs` shows the run with
         `state == "done"`, `step_log` step 0 by "A", and `judgements == []` (`record_step_done`
         purged `step <= 0`, and `_run_row` only populates `judgements` while `state == "open"`).
       * GET /play/quests as player -> 200, run state "done", and resp.text contains neither the
         verdict reason `"A asked G4 about the lamp."` nor `"judgements"` nor `"criterion"`.
       * `game_time().canonical()` == `t4c_start_game` and `world.is_world_frozen()` is True.
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

        # ══════════════════════════════════════════════════════════════════════════════════════════
        # PART 3 — Conversation quest (since_step, take_item, role_notes) under frozen game time
        # ══════════════════════════════════════════════════════════════════════════════════════════
        import time
        from app.core.timeutils import game_time

        print("[P3.1] fixture and pre-start talks under frozen game clock")
        t3_start_game = game_time().canonical()
        check("p3 world is frozen", world.is_world_frozen(), True)
        chars.save_character_current_room("A", "r1")
        assert chars.save_character_profile(
            "W", {"current_location": "L1", "current_room": "r1", "language": "en"}, create_new=True
        ), "W"
        ale_id = inventory.add_item("Ale", stackable=True, max_stack=20)["id"]
        record_utterance(speaker="N", content="Good day, traveler.", location_id="L1", room_id="r1",
                         addressees=["A"], source="loop")
        record_utterance(speaker="W", content="Move along.", location_id="L1", room_id="r1",
                         addressees=["A"], source="loop")
        check("p3 drain pre-start talks", quest_engine.drain(), True)
        check("p3 pre-start facts exist",
              (quests_mod.has_fact("A", "spoke_with", "N"), quests_mod.has_fact("A", "spoke_with", "W")),
              (True, True))

        tpl3_body = {
            "title": "A mug for the guard",
            "summary": "Fetch ale from {host} for {guard}.",
            "giver_role": "host",
            "roles": [
                {"key": "host", "kind": "character", "description": "The innkeeper"},
                {"key": "guard", "kind": "character", "description": "The thirsty guard"},
                {"key": "ale", "kind": "item", "description": "A jug of ale"},
            ],
            "steps": [
                {
                    "id": "s1",
                    "text": "Ask {host} for the ale.",
                    "hint": "",
                    "condition": {"type": "spoke_with", "params": {"character": "host", "since_step": True}},
                    "on_done": [{"key": "pour", "type": "give_item", "params": {"item": "ale"}}],
                    "role_notes": [{"role": "host", "text": "Hand the adventurer a jug of ale for {guard}."}],
                },
                {
                    "id": "s2",
                    "text": "Bring the ale to {guard}.",
                    "hint": "",
                    "condition": {"all": [
                        {"type": "spoke_with", "params": {"character": "guard", "since_step": True}},
                        {"type": "holds_item", "params": {"item": "ale", "count": 1}},
                    ]},
                    "on_done": [{"key": "hand", "type": "take_item", "params": {"item": "ale", "to": "guard"}}],
                    "role_notes": [{"role": "guard", "text": "You are waiting for your ale."}],
                },
            ],
            "start_condition": {},
            "prerequisites": {},
            "time_limit_s": 0,
        }
        resp = call("POST", "/quests/templates", tpl3_body)
        check("p3 POST 200", resp.status_code, 200)
        tpl3 = resp.json() if resp.status_code == 200 else {}
        resp = call("PUT", f"/quests/templates/{tpl3.get('id')}", {"state": "ready", "base_revision": 1})
        check("p3 PUT ready 200", resp.status_code, 200)
        time.sleep(0.002)
        bindings3 = {"host": {"name": "N"}, "guard": {"name": "W"}, "ale": {"item_id": ale_id}}
        resp = call("POST", f"/quests/templates/{tpl3.get('id')}/start", {"bindings": bindings3})
        check("p3 start 200", resp.status_code, 200)
        run3 = resp.json() if resp.status_code == 200 else {}
        rid3_talk = run3.get("id")
        check("p3 open at step 0 (old talks do not count)",
              (run3.get("state"), run3.get("current_step")), ("open", 0))
        host_note = 'Quest "A mug for the guard": Hand the adventurer a jug of ale for W.'
        guard_note = 'Quest "A mug for the guard": You are waiting for your ale.'
        check("p3 N lines contain host note", host_note in qp.lines_for("N"), True)
        check("p3 W lines empty on step 0", qp.lines_for("W"), [])

        print("[P3.2] W talks to A -> step 0 stays current")
        time.sleep(0.002)
        record_utterance(speaker="W", content="Still waiting.", location_id="L1", room_id="r1",
                         addressees=["A"], source="loop")
        check("p3 drain W talk", quest_engine.drain(), True)
        check("p3 current_step still 0", quests_mod.get_run(rid3_talk)["current_step"], 0)

        print("[P3.3] N talks to A -> step 0 done, A gets Ale, step 1 still open")
        time.sleep(0.002)
        record_utterance(speaker="N", content="Here is the ale for the guard.", location_id="L1", room_id="r1",
                         addressees=["A"], source="loop")
        check("p3 drain N talk", quest_engine.drain(), True)
        r3_mid = quests_mod.get_run(rid3_talk)
        check("p3 step 0 done, current_step 1, open", (r3_mid["state"], r3_mid["current_step"]), ("open", 1))
        qfx.pass_once()
        check("p3 A holds 1 Ale", inventory.get_item_quantity("A", ale_id), 1)
        check("p3 drain after give_item", quest_engine.drain(), True)
        check("p3 step 1 still open (W talked before step 1)",
              (quests_mod.get_run(rid3_talk)["state"], quests_mod.get_run(rid3_talk)["current_step"]),
              ("open", 1))
        check("p3 N no longer sees host note", host_note in qp.lines_for("N"), False)
        check("p3 W sees guard note", qp.lines_for("W"), [guard_note])

        print("[P3.4] W talks to A -> done, take_item transfers Ale to W")
        time.sleep(0.002)
        record_utterance(speaker="W", content="Thanks for the ale!", location_id="L1", room_id="r1",
                         addressees=["A"], source="loop")
        check("p3 drain W final talk", quest_engine.drain(), True)
        check("p3 run done", quests_mod.get_run(rid3_talk)["state"], "done")
        qfx.pass_once()
        check("p3 A has 0 Ale, W has 1 Ale",
              (inventory.get_item_quantity("A", ale_id), inventory.get_item_quantity("W", ale_id)),
              (0, 1))

        print("[P3.5] player quest book leaks neither role_notes nor step_started_at")
        resp_book3 = call("GET", "/play/quests", role="player")
        check("p3 GET /play/quests 200", resp_book3.status_code, 200)
        check("p3 no role_notes in response text", "role_notes" in resp_book3.text, False)
        check("p3 no step_started_at in response text", "step_started_at" in resp_book3.text, False)
        check("p3 game clock stayed frozen throughout PART 3", game_time().canonical(), t3_start_game)

        # ══════════════════════════════════════════════════════════════════════════════════════════
        # PART 4 — Stage 3: admin LLM authoring (4a), automatic quest (4b), llm_judgement (4c)
        # ══════════════════════════════════════════════════════════════════════════════════════════
        from datetime import timedelta, timezone
        from types import SimpleNamespace
        from app.core import llm_router, quest_authoring, quest_auto, quest_judgement, task_queue
        from app.core.timeutils import parse_iso

        quest_authoring.register()
        quest_auto.register()
        quest_judgement.register()

        world.upsert_location(
            {
                "id": "L4",
                "name": "Courtyard",
                "entry_room": "r1",
                "rooms": [
                    {"id": "r1", "name": "Gate"},
                    {"id": "r2", "name": "Well"},
                ],
            },
            sync_world=False,
        )
        with keyed_lock("character_profile", "A"):
            prof_a = chars.get_character_profile("A") or {}
            prof_a["current_location"] = "L4"
            prof_a["current_room"] = "r1"
            assert chars.save_character_profile("A", prof_a)
        assert chars.save_character_profile(
            "G4", {"current_location": "L4", "current_room": "r1", "language": "en"}, create_new=True
        ), "G4"
        check("p4 drain after moving A to L4/r1", quest_engine.drain(), True)

        admin_quest_obj = {
            "template": {
                "title": "Inspect the well",
                "summary": "Help {giver} check {place}.",
                "gm_notes": "Admin generated GM note",
                "giver_role": "giver",
                "roles": [
                    {"key": "giver", "kind": "character", "description": "Who asks"},
                    {"key": "place", "kind": "room", "description": "Where to look"},
                ],
                "steps": [{
                    "id": "s1",
                    "text": "Walk to {place}.",
                    "hint": "",
                    "condition": {"type": "at_place", "params": {"place": "place"}},
                }],
                "start_condition": {},
                "prerequisites": {},
                "setup_effects": [],
                "rewards": [],
                "time_limit_s": 0,
            },
            "bindings": {
                "giver": {"name": "G4"},
                "place": {"location_id": "L4", "room_id": "r2"},
            },
        }
        auto_quest_obj = {
            "template": {
                "title": "Water from {place}",
                "summary": "Water from {place} for {giver}.",
                "gm_notes": "Auto generated GM note",
                "giver_role": "giver",
                "roles": [
                    {"key": "giver", "kind": "character", "description": "Quest giver"},
                    {"key": "place", "kind": "room", "description": "Target room"},
                ],
                "steps": [{
                    "id": "s1",
                    "text": "Check {place} for {giver}.",
                    "hint": "",
                    "condition": {"type": "at_place", "params": {"place": "place"}},
                }],
                "start_condition": {},
                "prerequisites": {},
                "setup_effects": [],
                "rewards": [],
                "time_limit_s": 0,
            },
            "bindings": {
                "giver": {"name": "G4"},
                "place": {"location_id": "L4", "room_id": "r2"},
            },
        }
        verdict_reason_4c = "A asked G4 about the lamp."

        llm_calls_p4: list[dict] = []
        unexpected_tasks_p4: list[str] = []
        struct_mode_holder = ["admin"]

        def stub_llm_p4(task, system_prompt, user_prompt, **kwargs):
            llm_calls_p4.append({
                "task": task,
                "system": system_prompt,
                "user": user_prompt,
                "kwargs": dict(kwargs),
            })
            if task == "quest_draft":
                return SimpleNamespace(content="G4 asks A to inspect the courtyard well.")
            if task == "quest_structure":
                obj = admin_quest_obj if struct_mode_holder[0] == "admin" else auto_quest_obj
                return SimpleNamespace(content="```json:quest\n" + json.dumps(obj) + "\n```")
            if task == "quest_judgement":
                verdict = {"passed": True, "reason": verdict_reason_4c}
                return SimpleNamespace(content="```json:verdict\n" + json.dumps(verdict) + "\n```")
            unexpected_tasks_p4.append(str(task))
            FAILURES.append(f"p4 unexpected llm_call task: {task!r}")
            raise AssertionError(f"unexpected llm_call task: {task!r}")

        def wait_generate_job(task_id: str) -> dict:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                jobs_resp = call("GET", "/quests/generate/jobs")
                if jobs_resp.status_code == 200:
                    for j in jobs_resp.json().get("jobs", []):
                        if j.get("task_id") == task_id and j.get("status") not in ("pending", "running"):
                            return j
                time.sleep(0.05)
            return {}

        # ── 4a: Admin generates a quest (Decision 4) ───────────────────────────────────────────
        print("[P4.a] admin generates a quest via POST /quests/generate")
        struct_mode_holder[0] = "admin"
        llm_calls_p4.clear()
        with patch.object(llm_router, "llm_call", side_effect=stub_llm_p4):
            resp_gen = call("POST", "/quests/generate", {"brief": "Check the courtyard well", "giver": "G4"})
            gen_tid = resp_gen.json().get("task_id", "") if resp_gen.status_code == 202 else ""
            check("p4a POST /quests/generate -> 202 with task_id",
                  (resp_gen.status_code, bool(gen_tid)), (202, True))
            job4a = wait_generate_job(gen_tid)

        check("p4a job completed, state done, ok True, no issues",
              (job4a.get("status"), job4a.get("state"), job4a.get("ok"), job4a.get("issues")),
              ("completed", "done", True, []))
        check("p4a llm tasks invoked", [c["task"] for c in llm_calls_p4], ["quest_draft", "quest_structure"])
        want_bindings_4a = {"giver": {"name": "G4"}, "place": {"location_id": "L4", "room_id": "r2"}}
        check("p4a job carries proposed bindings", job4a.get("bindings"), want_bindings_4a)

        tpl4a_id = job4a.get("template_id") or ""
        resp_tpl4a = call("GET", f"/quests/templates/{tpl4a_id}")
        tpl4a = resp_tpl4a.json() if resp_tpl4a.status_code == 200 else {}
        check("p4a template saved as admin draft rev 1 with no issues",
              (resp_tpl4a.status_code, tpl4a.get("state"), tpl4a.get("origin"),
               tpl4a.get("kept"), tpl4a.get("revision"), tpl4a.get("issues")),
              (200, "draft", "admin", True, 1, []))
        runs_before_4a = [
            r for r in (call("GET", "/quests/runs").json().get("runs") or [])
            if r.get("template_id") == tpl4a_id
        ]
        check("p4a generation started no run automatically",
              (runs_before_4a, quests_mod.list_runs(template_id=tpl4a_id)), ([], []))

        resp_ready4a = call("PUT", f"/quests/templates/{tpl4a_id}", {"state": "ready", "base_revision": 1})
        tpl4a_ready = resp_ready4a.json() if resp_ready4a.status_code == 200 else {}
        check("p4a PUT ready 200 with empty issues",
              (resp_ready4a.status_code, tpl4a_ready.get("state"),
               tpl4a_ready.get("revision"), tpl4a_ready.get("issues")),
              (200, "ready", 2, []))
        resp_start4a = call("POST", f"/quests/templates/{tpl4a_id}/start", {"bindings": job4a.get("bindings") or {}})
        run4a = resp_start4a.json() if resp_start4a.status_code == 200 else {}
        run4a_id = run4a.get("id") or ""
        check("p4a start with proposed bindings -> open at step 0",
              (resp_start4a.status_code, run4a.get("state"), run4a.get("current_step")),
              (200, "open", 0))
        resp_cancel4a = call("POST", f"/quests/runs/{run4a_id}/cancel")
        check("p4a cancel run before 4b -> 200 ok",
              (resp_cancel4a.status_code, resp_cancel4a.json()), (200, {"ok": True}))
        check("p4a drain after cancel", quest_engine.drain(), True)

        # ── 4b: Automatic quest offered by nearby NPC (Decision 5) ─────────────────────────────
        print("[P4.b] automatic quest offered by G4 beside A")
        auto_hours_default = field_default("quests", "auto_expiry_game_hours")
        check("p4b schema default auto_expiry_game_hours == 48", auto_hours_default, 48)
        want_auto_limit_s = auto_hours_default * 3600
        check("p4b hand-derived auto time_limit_s == 172800", want_auto_limit_s, 172800)

        struct_mode_holder[0] = "auto"
        llm_calls_p4.clear()
        tq = task_queue.get_task_queue()
        world.set_world_frozen(False)
        try:
            with (
                patch.object(quest_auto, "auto_enabled", return_value=True),
                patch.object(llm_router, "llm_call", side_effect=stub_llm_p4),
            ):
                check("p4b pick_giver == ('G4', 'A')", quest_auto.pick_giver(), ("G4", "A"))
                tick_res = quest_auto.tick()
                auto_tid = str(tick_res.get("queued") or "")
                check("p4b tick queues quest_auto for G4 and A",
                      (bool(auto_tid), tick_res.get("giver"), tick_res.get("avatar")),
                      (True, "G4", "A"))

                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    if auto_tid and tq.task_status(auto_tid) not in ("pending", "running"):
                        break
                    time.sleep(0.05)
                check("p4b quest_auto task completed", tq.task_status(auto_tid), "completed")

                check("p4b llm tasks invoked",
                      [c["task"] for c in llm_calls_p4], ["quest_draft", "quest_structure"])
                auto_tpls = quests_mod.list_templates(origin="auto")
                check("p4b exactly one auto template stored", len(auto_tpls), 1)
                tpl4b = auto_tpls[0] if auto_tpls else {}
                tpl4b_id = tpl4b.get("id") or ""
                check("p4b auto template origin/state/kept/time_limit_s",
                      (tpl4b.get("origin"), tpl4b.get("state"), tpl4b.get("kept"), tpl4b.get("time_limit_s")),
                      ("auto", "ready", False, want_auto_limit_s))
                lib_ids = {t["id"] for t in (call("GET", "/quests/templates").json().get("templates") or [])}
                gen_ids = [t["id"] for t in (call("GET", "/quests/templates?generated=1").json().get("templates") or [])]
                check("p4b unkept auto hidden from default library and shown in generated=1",
                      (tpl4b_id in lib_ids, gen_ids), (False, [tpl4b_id]))

                auto_runs = quests_mod.list_runs(template_id=tpl4b_id) if tpl4b_id else []
                check("p4b exactly one run of the auto template", len(auto_runs), 1)
                run4b = auto_runs[0] if auto_runs else {}
                run4b_id = run4b.get("id") or ""
                check("p4b auto run open, giver bound to G4, expires_at set",
                      (run4b.get("state"), run4b.get("started_by"),
                       (run4b.get("bindings") or {}).get("giver"), bool(run4b.get("expires_at"))),
                      ("open", "auto", {"name": "G4"}, True))
                check("p4b open_auto_count == 1", quest_auto.open_auto_count(), 1)

                want_g4_line = "You want an adventurer to: Water from Well for G4. \u2014 next: Check Well for G4."
                g4_lines = qp.lines_for("G4")
                check("p4b G4 prompt line offers the quest with rendered title",
                      (g4_lines, any("Water from Well" in ln for ln in g4_lines)),
                      ([want_g4_line], True))

                resp_book4b = call("GET", "/play/quests", role="player")
                check("p4b GET /play/quests 200", resp_book4b.status_code, 200)
                book4b_quests = (resp_book4b.json() if resp_book4b.status_code == 200 else {}).get("quests") or []
                entry4b = next((q for q in book4b_quests if q.get("id") == run4b_id), {})
                check("p4b player quest book lists open auto quest title",
                      (entry4b.get("state"), entry4b.get("title")), ("open", "Water from Well"))
                check("p4b player quest book leaks none of origin, kept, gm_notes",
                      ("origin" in resp_book4b.text, "kept" in resp_book4b.text, "gm_notes" in resp_book4b.text),
                      (False, False, False))

                resp_cancel4b = call("POST", f"/quests/runs/{run4b_id}/cancel")
                check("p4b cancel auto run before 4c -> 200 ok",
                      (resp_cancel4b.status_code, resp_cancel4b.json()), (200, {"ok": True}))
        finally:
            world.set_world_frozen(True)
        check("p4b world re-frozen after auto quest", world.is_world_frozen(), True)
        check("p4b drain after auto quest cancel", quest_engine.drain(), True)

        # ── 4c: llm_judgement passes after stubbed "yes" verdict under frozen clock ────────────
        print("[P4.c] llm_judgement step passes under frozen game clock")
        t4c_start_game = game_time().canonical()
        drift_s = abs((GameTime.parse(t4c_start_game) - GameTime.parse(t3_start_game)).total_seconds)
        check("p4c world frozen and game clock barely moved during 4b thaw (<= 5 s)",
              (world.is_world_frozen(), drift_s <= 5), (True, True))

        tpl4c_body = {
            "title": "The lost lamp",
            "summary": "Ask {giver} about the lost lamp.",
            "gm_notes": "GM ONLY 4c",
            "giver_role": "giver",
            "roles": [{"key": "giver", "kind": "character", "description": "Who to ask"}],
            "steps": [{
                "id": "s1",
                "text": "Ask {giver} about the lost lamp.",
                "hint": "",
                "condition": {
                    "type": "llm_judgement",
                    "params": {"criterion": "{giver} was asked about the lost lamp"},
                },
            }],
            "start_condition": {},
            "prerequisites": {},
            "time_limit_s": 0,
        }
        resp_tpl4c = call("POST", "/quests/templates", tpl4c_body)
        tpl4c = resp_tpl4c.json() if resp_tpl4c.status_code == 200 else {}
        tpl4c_id = tpl4c.get("id") or ""
        check("p4c POST llm_judgement template -> 200 draft with no issues",
              (resp_tpl4c.status_code, tpl4c.get("state"), tpl4c.get("issues")),
              (200, "draft", []))
        resp_ready4c = call("PUT", f"/quests/templates/{tpl4c_id}", {"state": "ready", "base_revision": 1})
        check("p4c PUT ready 200", resp_ready4c.status_code, 200)
        resp_start4c = call("POST", f"/quests/templates/{tpl4c_id}/start",
                            {"bindings": {"giver": {"name": "G4"}}})
        run4c = resp_start4c.json() if resp_start4c.status_code == 200 else {}
        run4c_id = run4c.get("id") or ""
        check("p4c start -> open at step 0",
              (resp_start4c.status_code, run4c.get("state"), run4c.get("current_step")),
              (200, "open", 0))
        check("p4c drain after start", quest_engine.drain(), True)
        check("p4c start_run does not pre-submit a judgement", quests_mod.list_judgements(run4c_id), [])

        with quest_judgement._rate_lock:
            quest_judgement._recent_submits.clear()
        llm_calls_p4.clear()

        # get_character_stream_since truncates step_started_at to whole UTC seconds and compares
        # strictly (u.ts > since_sec), so record A's utterance 1 second after step_started_at.
        after_step_ts = (
            parse_iso(run4c["step_started_at"]) + timedelta(seconds=1)
        ).astimezone(timezone.utc).isoformat(timespec="seconds")

        with (
            patch.object(quest_judgement, "min_interval_s", return_value=0.0),
            patch.object(llm_router, "llm_call", side_effect=stub_llm_p4),
        ):
            uid_4c = record_utterance(
                speaker="A",
                content="G4, have you seen my lost lamp?",
                addressees=["G4"],
                location_id="L4",
                room_id="r1",
                source="play",
                ts=after_step_ts,
            )
            check("p4c avatar utterance recorded", uid_4c is not None, True)

            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                quest_engine.drain()
                cur_4c = quests_mod.get_run(run4c_id) or {}
                if cur_4c.get("state") == "done":
                    break
                time.sleep(0.05)
            quest_engine.drain()

        run4c_done = quests_mod.get_run(run4c_id) or {}
        check("p4c run reached state done at step 1",
              (run4c_done.get("state"), run4c_done.get("current_step")), ("done", 1))
        check("p4c llm_call invoked once with task quest_judgement",
              [c["task"] for c in llm_calls_p4], ["quest_judgement"])
        judge_user_prompt = llm_calls_p4[0]["user"] if llm_calls_p4 else ""
        check("p4c judge prompt contains rendered criterion and avatar utterance",
              ("G4 was asked about the lost lamp" in judge_user_prompt,
               "A -> G4: G4, have you seen my lost lamp?" in judge_user_prompt),
              (True, True))

        # record_step_done deletes quest_judgements with step <= idx in the same transaction, and
        # _run_row only populates judgements while state == "open".
        check("p4c step completion purged step 0 judgement rows",
              quests_mod.list_judgements(run4c_id), [])
        admin_runs_4c = call("GET", "/quests/runs").json().get("runs") or []
        admin_row_4c = next((r for r in admin_runs_4c if r.get("id") == run4c_id), {})
        check("p4c admin run row shows done, step_log by A, and empty judgements",
              (admin_row_4c.get("state"),
               [(e.get("step"), e.get("avatar"), e.get("mind")) for e in (admin_row_4c.get("step_log") or [])],
               admin_row_4c.get("judgements")),
              ("done", [(0, "A", "A")], []))

        resp_book4c = call("GET", "/play/quests", role="player")
        check("p4c GET /play/quests 200", resp_book4c.status_code, 200)
        entry4c = next(
            (q for q in (resp_book4c.json().get("quests") or []) if q.get("id") == run4c_id),
            {},
        )
        check("p4c player quest book shows run done", entry4c.get("state"), "done")
        check("p4c player quest book leaks neither verdict reason nor judgements/criterion",
              (verdict_reason_4c in resp_book4c.text,
               "judgements" in resp_book4c.text,
               "criterion" in resp_book4c.text),
              (False, False, False))
        check("p4c game clock unchanged and world still frozen",
              (game_time().canonical(), world.is_world_frozen()),
              (t4c_start_game, True))
        check("p4 no unexpected LLM tasks called", unexpected_tasks_p4, [])

    quest_engine.drain()
    if FAILURES:
        print(f"FAIL smoke_quest_playthrough: {len(FAILURES)} failed")
        return 1
    print("PASS smoke_quest_playthrough")
    return 0


if __name__ == "__main__":
    sys.exit(main())
