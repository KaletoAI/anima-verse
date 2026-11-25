#!/usr/bin/env python3
"""Smoke: the acceptance play-through of quest stage 1 — the reference quest "Errand" played to its end over the
REAL routes.

Quest system stage 1, Task 13. The REAL `app.server` app through a `TestClient` without `with` (no lifespan: the
smoke calls `init_schema()`, `quest_types.register()` and `quest_engine.register()` itself, as
`smoke_quest_routes.py` / `smoke_play_quests.py` do). `STORAGE_DIR` / `INSTANCE_DIR` point at a throwaway
directory before `app.server` is imported. The session lookup is stubbed: the header `x-test-user` names the user —
"admin" (a dict, role admin) or "player" (the REAL `users` row of user "demo", allowed_characters [A],
settings.active_character A, so A is player-controlled).

Usage:
    ./.venv/bin/python scripts/smoke_quest_playthrough.py

FIXTURE
    Location L1 with rooms r1 (entry) and r2. Avatar A and NPC N both stand in L1/r1, language "en". Item "Lamp",
    nobody holds it. Game clock Y0001-D010T12:00:00, world FROZEN: every stamp of the play-through is that moment
    (a frozen world still evaluates a player's own action, plan D10), so L = GameTime.parse(that).display_label("en")
    is every done_label and the ended_label.
    "Errand" = the plan's reference quest: roles giver (character), place (room), thing (item); steps
    ① "Talk to the giver." spoke_with giver  ② "Go to the place." at_place place  ③ "Hold the thing." holds_item thing
    count 1. Bindings: giver {name N}, place {L1, r2}, thing {item_id Lamp}. The place is r2, NOT the room A stands
    in, so step ② is false until A walks; A holds no Lamp, so ③ is false until it is added. Steps are sequential and
    a cascade only goes on while the next step is already true — so each action below advances exactly one step.

WHAT FOLLOWS BY HAND
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
 4. Action 2 — A walks to r2 through save_character_current_room (what POST /play/enter-room calls) ->
    character.entered_room -> step ② passes, ③ does not (no Lamp). drain(). GET /play/quests (call 3) -> "open",
    steps [① done/A/L, ② done/A/L, {text "Hold the thing.", state "current"}].
 5. Action 3 — add_to_inventory(A, Lamp, 1) -> inventory.changed delta +1 -> step ③ passes, the run ends "done".
    drain(). GET /play/quests (call 4) -> the quest is ended: state "done", ended_label L, steps all three done
    (① ② ③ each done_by "A", done_label L), no "current" step, no time_left_label, no locked.
 6. GET /quests/runs as the admin -> exactly one run R: state "done", current_step 3, step_count 3, and a step_log
    of THREE entries, steps 0, 1, 2 in that order, each avatar "A", mind "A" (A is no linked body).
"""
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
    lamp = inventory.add_item("Lamp")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
    world.set_world_frozen(True)
    now = GameTime.parse("Y0001-D010T12:00:00").display_label("en")
    check("L is a real label", bool(now), True)
    bindings = {"giver": {"name": "N"}, "place": {"location_id": "L1", "room_id": "r2"},
                "thing": {"item_id": lamp}}

    def session_user(request):
        who = request.headers.get("x-test-user", "")
        if who == "admin":
            return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
        if who == "player":
            return get_user_by_id(player_id)
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
        check("call 2: state", entry.get("state"), "open")
        steps = entry.get("steps") or []
        check("call 2: step count", len(steps), 2)
        check("call 2: step 1", steps[0] if steps else None, done("Talk to the giver."))
        check("call 2: step 2", steps[1] if len(steps) > 1 else None, {"text": "Go to the place.", "state": "current"})

        print("[4] A walks to the place")
        chars.save_character_current_room("A", "r2")
        check("A is in r2", chars.get_character_current_room("A"), "r2")
        check("drain after the walk", quest_engine.drain(), True)
        entry = book("call 3")
        check("call 3: state", entry.get("state"), "open")
        steps = entry.get("steps") or []
        check("call 3: step count", len(steps), 3)
        check("call 3: step 1", steps[0] if steps else None, done("Talk to the giver."))
        check("call 3: step 2", steps[1] if len(steps) > 1 else None, done("Go to the place."))
        check("call 3: step 3", steps[2] if len(steps) > 2 else None, {"text": "Hold the thing.", "state": "current"})

        print("[5] A takes the thing")
        check("Lamp added", inventory.add_to_inventory("A", lamp, 1), True)
        check("drain after the item", quest_engine.drain(), True)
        entry = book("call 4")
        check("call 4: ended done", (entry.get("state"), entry.get("ended_label")), ("done", now))
        check("call 4: no open-run keys", ("time_left_label" in entry, "locked" in entry), (False, False))
        check("call 4: steps", entry.get("steps"),
              [done("Talk to the giver."), done("Go to the place."), done("Hold the thing.")])

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

    quest_engine.drain()
    if FAILURES:
        print(f"FAIL smoke_quest_playthrough: {len(FAILURES)} failed")
        return 1
    print("PASS smoke_quest_playthrough")
    return 0


if __name__ == "__main__":
    sys.exit(main())
