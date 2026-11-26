#!/usr/bin/env python3
"""Smoke: the player's quest book — `app/core/quest_book.build_player_quests` and `GET /play/quests`.

Quest system stage 1, Task 7 (plan D14). The REAL `app.server` app through a `TestClient` without `with` (no
lifespan: the smoke calls `init_schema()`, `quest_types.register()` and `quest_engine.register()` itself).
`STORAGE_DIR` / `INSTANCE_DIR` point at a throwaway directory before `app.server` is imported. The session lookup
is stubbed: the header `x-test-user: player` is the REAL `users` row of user "demo" (allowed_characters [A],
settings.active_character A).

Usage:
    ./.venv/bin/python scripts/smoke_play_quests.py

FIXTURE
    Location L1 with room r1. Characters A (the player's avatar, language "en") and N (an NPC), both in L1/r1.
    Item "Lamp". Game clock set to Y0001-D010T12:00:00 and the world FROZEN, so "now" stays put between a start
    and the read (a running clock would turn 26 h left into 25 h 59 min a second later).
    "Errand" = the plan's reference quest (gm_notes "GM ONLY", hints "HINT ONE/TWO/THREE", steps ① "Talk to the
    giver." ② "Go to the place." ③ "Hold the thing."), made ready. Bindings E = giver N, place L1/r1, thing Lamp.

WHAT FOLLOWS BY HAND
 1. No avatar: build_player_quests("") == {"avatar": "", "quests": []} (D14).
 2. Run R (Errand, E), started with an empty start condition -> open. Step ① recorded for avatar A (mind A) ->
    current_step 1. Its entry: keys exactly {id, title, summary, state, steps} (no time limit -> no
    time_left_label; no prerequisites -> no locked; open -> no ended_label); title "Errand", summary "Run an errand
    for someone.", state "open". steps = 2 entries (① done + ② current; ③ is the future, withheld):
    ① {text "Talk to the giver.", state "done", done_by "A", done_label = GameTime.parse(Y0001-D010T12:00:00)
    .display_label("en") (the frozen clock stamped it)}; ② exactly {text "Go to the place.", state "current"}.
 3. Spoilers: json.dumps(payload) contains none of "Hold the thing." (step ③), "HINT" (any hint), "GM ONLY",
    "gm_notes", "bindings", "template_snapshot", the Lamp's item id (only a binding names it), "hint".
 4. Hidden: a template "Secret" with a start condition that cannot pass now (holds_item thing count 5) starts
    hidden -> its id is in no entry, "Secret" nowhere in the dump. Cancelled while still hidden (never opened) ->
    still absent (it never had a started_game_ts).
 5. Chronicle: 12 more Errand runs C1..C12 started and cancelled in that order. Ended runs list latest end first;
    ended_at has whole-second precision, so ties keep list_runs' newest-created-first order — either way C12
    leads. The book: the open runs first (newest first), then exactly 10 ended: C12, C11, ..., C3 (C2, C1 dropped,
    CHRONICLE_SIZE 10). Each carries state "cancelled", ended_label == the label of the frozen clock, no
    time_left_label, no locked, steps [] (nothing done, an ended run shows only done steps).
 6. Locked: template "Friends" (Errand steps) with prerequisites {condition relationship_at_least character=giver
    strength 50, locked_text "Only friends of the giver."}. A and N have no relationship row -> strength 0 < 50
    -> locked == "Only friends of the giver.". Template "Gate" with the same condition and locked_text "" ->
    locked == quest_engine.DEFAULT_LOCKED_TEXT "You do not meet the requirements." (lang en). R has no key "locked".
 7. Time left (whole units, rounded down; day = 86400 s):
    _time_left_label: 26 h = 93600 s -> 1 d, 2 h -> "1 d 2 h"; 90 min = 5400 s -> 1 h 30 min -> "1 h 30 min";
    20 min -> "20 min"; 26 h in "de" -> de.json's "{d} d {h} h" with 1 and 2 put in.
    End to end: Errand copies with time_limit_s 93600 / 5400 / 1200 started on the frozen clock -> expires_at -
    now is exactly that limit -> time_left_label "1 d 2 h" / "1 h 30 min" / "20 min"; R has none.
 8. Route: "/play/quests" is a registered GET path; the player GET -> 200 and the body equals
    build_player_quests("A", "en") (A's language is en).
 9. Preparing: a ready template "Staging" (Errand roles/steps) with a setup create_item starts in state
    "preparing". Without running pass_once, its id is in no book entry and "Staging" appears nowhere in
    json.dumps(book). Cancelled while preparing -> still absent (it never opened); one pass_once cleans up.
10. Reward label + notice: template "Prize" (Errand roles, one step at_place, rewards all permanent: charm
    create_item "Lucky charm" tool, charm_given give_item charm, coin create_item "Coin", coin_given give_item
    coin qty 3, npc_gift give_item charm to giver). Started -> open; step 0 recorded for A -> done + pending
    reward payout with avatar A; pass_once -> payout applied. By hand: A received charm x1 and coin x3 in
    first-seen order -> "Lucky charm, 3 × Coin"; N received charm x1 -> "Lucky charm". A's book entry has
    exact keys {id, title, summary, state, steps, ended_label, rewards_label} and rewards_label ==
    "Lucky charm, 3 × Coin". A's quest notifications for this run are ["Reward: Lucky charm, 3 × Coin"]
    (no per-item "You received ..." notices); a second pass_once adds none; t("Reward: {items}", "de") ==
    "Belohnung: {items}". Spoilers: json.dumps(book) contains none of charm/coin item ids, "charm_given",
    "npc_gift", "grant", "quest_run", "payout".
11. Whitelist: quest_book.OPTIONAL_FIELDS == ("time_left_label", "locked", "ended_label", "rewards_label");
    every entry in the final book has keys within QUEST_FIELDS + ("steps",) + OPTIONAL_FIELDS; no open or
    cancelled entry has "rewards_label".
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
    tmp = tempfile.mkdtemp(prefix="play-quests-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__
    from app.server import app as server_app
    from app.core import auth_dependency, item_images, quest_book, quest_effects, quest_engine, quest_types
    from app.core.db import init_schema
    from app.core.game_time import GameDuration, GameTime
    from app.core.i18n import t
    from app.core.timeutils import set_game_time
    from app.core.users import create_user, get_user_by_id, update_user
    from app.models import character as chars, inventory, notifications, quests, world
    from fastapi.testclient import TestClient
    import logging
    logging.disable(logging.INFO)
    init_schema()
    quest_types.register()
    quest_engine.register()

    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Front"}]}, sync_world=False)
    for name in ("A", "N"):
        assert chars.save_character_profile(name, {"current_location": "L1", "current_room": "r1",
                                                   "language": "en"}, create_new=True), name
    player_id = create_user("demo", "smoke-password", allowed_characters=["A"])
    update_user(player_id, settings={"active_character": "A"})
    lamp = inventory.add_item("Lamp")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
    world.set_world_frozen(True)
    now_label = GameTime.parse("Y0001-D010T12:00:00").display_label("en")
    bindings = {"giver": {"name": "N"}, "place": {"location_id": "L1", "room_id": "r1"},
                "thing": {"item_id": lamp}}

    def template(**over):
        body = {**ERRAND, **over}
        return quests.create_template(state="ready", **body)["id"]

    def start(tid):
        return quest_engine.start_run(tid, bindings)

    def entries(payload):
        return {q["id"]: q for q in payload["quests"]}

    print("[1] no avatar")
    check("empty book", quest_book.build_player_quests(""), {"avatar": "", "quests": []})

    print("[2] open run, step one done")
    errand = template()
    run = start(errand)
    check("R open", run.get("state"), "open")
    done = quests.record_step_done(run["id"], 0, avatar="A", mind="A")
    check("step 1 recorded", (done or {}).get("current_step"), 1)
    payload = quest_book.build_player_quests("A", "en")
    check("avatar", payload.get("avatar"), "A")
    entry = entries(payload).get(run["id"], {})
    check("entry keys", sorted(entry), sorted(["id", "title", "summary", "state", "steps"]))
    check("entry head", (entry.get("title"), entry.get("summary"), entry.get("state")),
          ("Errand", "Run an errand for someone.", "open"))
    steps = entry.get("steps") or []
    check("two steps", len(steps), 2)
    check("step 1 done", steps[0] if steps else None,
          {"text": "Talk to the giver.", "state": "done", "done_by": "A", "done_label": now_label})
    check("done_label not empty", bool(now_label), True)
    check("step 2 current", steps[1] if len(steps) > 1 else None, {"text": "Go to the place.", "state": "current"})

    print("[3] spoilers")
    dump = json.dumps(payload)
    for needle in ("Hold the thing.", "HINT", "GM ONLY", "gm_notes", "bindings", "template_snapshot", lamp,
                   '"hint"'):
        check(f"no {needle!r}", needle in dump, False)

    print("[4] hidden")
    secret = template(title="Secret", start_condition={"type": "holds_item",
                                                       "params": {"item": "thing", "count": 5}})
    hidden = start(secret)
    check("Secret is hidden", hidden.get("state"), "hidden")
    payload = quest_book.build_player_quests("A", "en")
    check("hidden run absent", hidden["id"] in entries(payload), False)
    check("Secret nowhere", "Secret" in json.dumps(payload), False)
    check("cancel hidden", quest_engine.cancel_run(hidden["id"]), True)
    payload = quest_book.build_player_quests("A", "en")
    check("never-opened ended run absent", hidden["id"] in entries(payload), False)

    print("[5] chronicle")
    chronicle = []
    for _ in range(12):
        c = start(errand)
        assert quest_engine.cancel_run(c["id"]), c["id"]
        chronicle.append(c["id"])
    payload = quest_book.build_player_quests("A", "en")
    states = [q["state"] for q in payload["quests"]]
    n_open = states.count("open")
    check("open first", states[:n_open], ["open"] * n_open)
    tail = payload["quests"][n_open:]
    check("10 ended after them", [q["id"] for q in tail], list(reversed(chronicle))[:10])
    check("ended rows", {(q["state"], q.get("ended_label"), "time_left_label" in q, "locked" in q,
                          json.dumps(q["steps"])) for q in tail},
          {("cancelled", now_label, False, False, "[]")})

    print("[6] locked")
    prereq = {"type": "relationship_at_least", "params": {"character": "giver", "strength": 50}}
    friends = start(template(title="Friends", prerequisites={"condition": prereq,
                                                            "locked_text": "Only friends of the giver."}))
    gate = start(template(title="Gate", prerequisites={"condition": prereq, "locked_text": ""}))
    book = entries(quest_book.build_player_quests("A", "en"))
    check("author lock text", book.get(friends["id"], {}).get("locked"), "Only friends of the giver.")
    check("fallback lock text", book.get(gate["id"], {}).get("locked"), "You do not meet the requirements.")
    check("fallback is the engine's", quest_engine.DEFAULT_LOCKED_TEXT, "You do not meet the requirements.")
    check("R not locked", "locked" in book.get(run["id"], {}), False)

    print("[7] time left")
    label = quest_book._time_left_label
    check("26 h", label(GameDuration.of(hours=26), "en"), "1 d 2 h")
    check("90 min", label(GameDuration.of(minutes=90), "en"), "1 h 30 min")
    check("20 min", label(GameDuration.of(minutes=20), "en"), "20 min")
    de = t("{d} d {h} h", "de")
    check("de has its own text", de != "{d} d {h} h", True)
    check("26 h in de", label(GameDuration.of(hours=26), "de"), de.replace("{d}", "1").replace("{h}", "2"))
    timed = {limit: start(template(title=f"Timed {limit}", time_limit_s=limit))["id"]
             for limit in (93600, 5400, 1200)}
    book = entries(quest_book.build_player_quests("A", "en"))
    check("end to end", [book.get(timed[k], {}).get("time_left_label") for k in (93600, 5400, 1200)],
          ["1 d 2 h", "1 h 30 min", "20 min"])
    check("R has no time_left_label", "time_left_label" in book.get(run["id"], {}), False)

    print("[8] route")
    from app.routes.play import router as play_router
    paths_get = {r.path for r in play_router.routes if "GET" in (getattr(r, "methods", None) or set())}
    check("/play/quests registered", "/play/quests" in paths_get, True)

    def session_user(request):
        return get_user_by_id(player_id) if request.headers.get("x-test-user") == "player" else None

    with patch.object(auth_dependency, "_get_session_user", side_effect=session_user):
        client = TestClient(server_app)
        resp = client.get("/play/quests", headers={"x-test-user": "player"})
        check("player GET 200", resp.status_code, 200)
        check("body is the book", resp.json() if resp.status_code == 200 else None,
              quest_book.build_player_quests("A", "en"))

    orig_gen = item_images.generate_item_image_sync
    item_images.generate_item_image_sync = lambda item_id, overrides=None, *, raise_errors=False: True
    try:
        print("[9] preparing")
        staging_tid = template(
            title="Staging",
            setup_effects=[{"key": "box", "type": "create_item", "params": {"name": "Staging box"}}],
        )
        staging = start(staging_tid)
        check("Staging is preparing", staging.get("state"), "preparing")
        payload = quest_book.build_player_quests("A", "en")
        check("preparing run absent", staging["id"] in entries(payload), False)
        check("Staging nowhere", "Staging" in json.dumps(payload), False)
        check("cancel preparing", quest_engine.cancel_run(staging["id"]), True)
        payload = quest_book.build_player_quests("A", "en")
        check("cancelled preparing run absent", staging["id"] in entries(payload), False)
        quest_effects.pass_once()

        print("[10] reward label + notice")
        prize_tid = template(
            title="Prize",
            steps=[{"id": "s1", "text": "Go to the place.", "hint": "",
                    "condition": {"type": "at_place", "params": {"place": "place"}}}],
            rewards=[
                {"key": "charm", "type": "create_item", "permanent": True,
                 "params": {"name": "Lucky charm", "category": "tool"}},
                {"key": "charm_given", "type": "give_item", "permanent": True,
                 "params": {"item": "charm"}},
                {"key": "coin", "type": "create_item", "permanent": True,
                 "params": {"name": "Coin"}},
                {"key": "coin_given", "type": "give_item", "permanent": True,
                 "params": {"item": "coin", "quantity": 3}},
                {"key": "npc_gift", "type": "give_item", "permanent": True,
                 "params": {"item": "charm", "to": "giver"}},
            ],
        )
        prize = start(prize_tid)
        check("Prize is open", prize.get("state"), "open")
        prize_done = quests.record_step_done(prize["id"], 0, avatar="A", mind="A")
        check("Prize is done", (prize_done or {}).get("state"), "done")
        payouts_before = [p for p in quests.list_payouts(states=("pending",), run_id=prize["id"])
                          if p.get("position") == "reward"]
        check("pending reward payout for A",
              [(p.get("position"), p.get("avatar"), p.get("state")) for p in payouts_before],
              [("reward", "A", "pending")])
        quest_effects.pass_once()
        payouts_after = [p for p in quests.list_payouts(states=(), run_id=prize["id"])
                         if p.get("position") == "reward"]
        check("reward payout applied", [p.get("state") for p in payouts_after], ["applied"])

        payload = quest_book.build_player_quests("A", "en")
        prize_entry = entries(payload).get(prize["id"], {})
        check("Prize entry keys", sorted(prize_entry),
              sorted(["id", "title", "summary", "state", "steps", "ended_label", "rewards_label"]))
        check("Prize rewards_label", prize_entry.get("rewards_label"), "Lucky charm, 3 \u00d7 Coin")
        reward_fn = getattr(quest_book, "reward_items_label", None)
        check("N reward_items_label",
              reward_fn(prize["id"], "N", "en") if callable(reward_fn) else None,
              "Lucky charm")

        def run_quest_notices(run_id):
            return [
                n["content"]
                for n in notifications.get_notifications(character_whitelist=["A"])
                if n.get("type") == "quest" and (n.get("metadata") or {}).get("run_id") == run_id
            ]

        check("A reward notice only", run_quest_notices(prize["id"]), ["Reward: Lucky charm, 3 \u00d7 Coin"])
        quest_effects.pass_once()
        check("second pass_once adds no notice", run_quest_notices(prize["id"]),
              ["Reward: Lucky charm, 3 \u00d7 Coin"])
        check("de translation for Reward: {items}", t("Reward: {items}", "de"), "Belohnung: {items}")

        obj_by_key = {o["effect_key"]: o["ref"] for o in quests.list_objects(prize["id"])}
        charm_id = obj_by_key.get("charm", {}).get("item_id", "")
        coin_id = obj_by_key.get("coin", {}).get("item_id", "")
        check("charm and coin ids present", bool(charm_id) and bool(coin_id), True)
        book_dump = json.dumps(payload)
        for needle in (charm_id, coin_id, "charm_given", "npc_gift", "grant", "quest_run", "payout"):
            check(f"no spoiler {needle!r}", needle in book_dump, False)

        print("[11] whitelist")
        opt_fields = getattr(quest_book, "OPTIONAL_FIELDS", None)
        check("OPTIONAL_FIELDS", opt_fields, ("time_left_label", "locked", "ended_label", "rewards_label"))
        allowed_keys = set(quest_book.QUEST_FIELDS) | {"steps"} | set(opt_fields or ())
        check("all entry keys within whitelist",
              all(set(q.keys()) <= allowed_keys for q in payload["quests"]), True)
        check("no open or cancelled entry has rewards_label",
              any("rewards_label" in q for q in payload["quests"] if q.get("state") in ("open", "cancelled")),
              False)
    finally:
        item_images.generate_item_image_sync = orig_gen

    quest_engine.drain()
    if FAILURES:
        print(f"FAIL smoke_play_quests: {len(FAILURES)} failed")
        return 1
    print("PASS smoke_play_quests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
