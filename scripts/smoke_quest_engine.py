#!/usr/bin/env python3
"""Smoke: the quest engine (`app/core/quest_engine.py`) — start, evaluate, tick, broken runs.

Quest system stage 1, Task 5. Throwaway storage (`paths.init(<tmpdir>)` BEFORE any world-DB module), no server, no
LLM. Every expectation below is derived by hand from the plan (Task 5 brief, D2, D6-D11, D15, Review Focus 2/3/5),
not recorded from a run.

Usage:
    ./.venv/bin/python scripts/smoke_quest_engine.py

FIXTURE
    Locations: L1 (rooms r1 = entry, r2), L2 (room s1 = entry).
    Characters: A (avatar: user "demo", active_character A), B (avatar: user "demo2"), NPCs N, Ola, Nox — all start
    in L2/s1 except N, which starts in L1/r2. Items: I ("Lamp"), P ("Pebble").
    The engine's hooks are registered (`quest_engine.register()`); every signal goes through the worker, so each
    action is followed by `drain()` before reading.
    Moving: `save_character_current_location` to another location lands in its entry room and emits
    `character.entered_room`; `save_character_current_room` inside a location emits it for the new room.
    "Errand" = the plan's reference quest (giver: character, place: room, thing: item; steps
    ① spoke_with giver ② at_place place ③ holds_item thing count=1), stored `ready` unless said otherwise.
    Bindings E(giver) = giver {name}, place L1/r1, thing I.
    The game clock is set to Y0001-D010T12:00:00 first (a fresh world starts at the epoch, where "one game hour ago"
    does not exist).

WHAT FOLLOWS BY HAND
 1. validate_template({}): title is blank -> "title"; steps missing -> "steps" (both in the issue paths).
    The reference quest: title set, three unique roles of known kinds, three steps with id/text, each leaf a
    registered condition with its role of the right kind, empty start/prerequisites, limit 0 -> [].
 2. start_run on a "draft" Errand -> QuestRefused (only ready starts). Ready, without "thing" -> QuestRefused with
    an issue at "bindings.thing". Ready with E(N) -> no start condition -> state "open", current_step 0, and announced
    (news_event_id set, D15).
 3. Run R1 = Errand E(N). N (an NPC) walks L1/r2 -> L1/r1, the bound room: is_player_controlled(N) is False, so
    nothing changes (current_step 0, empty log), and evaluate("N") == []. A walks into L1/r1: the current step is ①
    (spoke_with), it listens only to utterance.heard and is false anyway -> still 0 (steps are sequential). A goes
    back to L2.
 4. N comes to L2/s1 and says a line addressed to A with source "loop": A is an avatar who heard it -> fact
    (A, spoke_with, N) -> ① passes -> current_step 1, exactly one log entry, avatar A. A walks to L1/r1 -> ② ->
    current_step 2. add_to_inventory(A, I) -> inventory.changed -> ③ -> state "done", three log entries. One
    "quest" notification per step for A on R1 (3), none for B.
 4b. Talk before the quest: Ola says a line to A (source "loop") BEFORE the run exists; the fact is written anyway.
    start_run Errand with giver Ola, then evaluate("A"): ① passes at once -> step 1; ② needs L1/r1 but A stands in
    L2/s1 -> current_step stays 1.
 4c. World-owned progress: fresh run Errand E(N). evaluate("A"): A has spoken with N (4) -> ① by A. B (avatar)
    walks into L1/r1 -> ② passes for B -> step_log[0].avatar == A, step_log[1].avatar == B; ③ needs B to hold I ->
    stops at current_step 2.
 5. Cascade: template [① at_place place, ② holds_item thing]; A stands in L1/r1 and holds I before the start.
    evaluate("A", "character.entered_room"): ① listens and passes, ② is read in the same call whatever the signal
    -> "done" after ONE call, which returns [run id].
 6. Hidden: Errand with start_condition at_place place and giver B (A has never been spoken to by B; with giver N
    the steps would cascade to "done" at once, since A spoke with N in 4, stands in L1/r1 and holds I) -> state
    "hidden", no news event (news_event_id ""). A (in L2) walks into L1/r1 -> start condition passes -> "open",
    current_step 0, started_game_ts set; opening from hidden is not announced -> news_event_id still "".
 7. Prerequisite relationship_at_least giver(N) >= 50, locked_text "Earn their trust first.": A has spoken with N but
    has no relationship (strength 0 < 50) -> evaluate("A") == [] and current_step 0; avatar_view(run, A) ==
    {"locked": True, "locked_text": "Earn their trust first."}. B gets strength 60 and N says a line to B -> ① done
    by B; avatar_view(run, B) -> {"locked": False, "locked_text": ""}.
 8. Snapshot (Review Focus 2): template [① at_place place]; run started; update_template replaces ① by
    holds_item thing count=5 (A holds 1 I) -> the run still reads its snapshot: A walks into L1/r1 -> "done".
 9. Broken (Review Focus 3): run of [① holds_item thing] with thing = P; delete_item(P) -> tick() -> "broken" with
    exactly one issue (bindings.thing, unknown_item), its announcement deleted. Run Errand with giver Nox;
    delete_character("Nox") -> "broken" at once, no tick.
 10. Unloaded type (Review Focus 5): owner "smoke_x" registers condition "x_flag" (always passes, listens to
    character.entered_room). Run RX = [① x_flag]. Unregister smoke_x: evaluate("A") raises nothing and RX stays at
    current_step 0 (an unregistered type is unavailable, never passed). Then run RY = [① at_place place] while A
    already stands in L1/r1 (nothing evaluated yet). tick() -> RX "broken" (issue code type_not_registered), RY
    "done" in the same tick.
 11. Freeze: RE = create_run of Errand E(N), open, expires_at = now - 1 game hour. set_world_frozen(True) ->
    periodic_jobs._is_paused() is True (the gate that keeps world_tick from firing) and RE is still "open". RF =
    [① at_place place2] with place2 = L1/r2: A walks to L1/r2 -> the signal is evaluated while frozen -> RF "done".
    A direct tick() -> RE "failed".
 12. cancel_run on an announced open run -> True, "cancelled", its news event gone (get_event None, not in
    list_events()); a second cancel_run -> False.
 13. Restart: one open run [① at_place place] (A in L2). _reset_for_tests() forgets the live-run count as a fresh
    process; the count is loaded on first use, so A walking into L1/r1 still finishes the run. app/server.py contains
    "quest_types.register()" and "quest_engine.register()".
 14. A raising validator is no broken reference (fix round 1): owner "smoke_v" registers condition "v_flag" (always
    passes, no signals; its validate raises once when armed and called WITH bindings). Run RV = [① v_flag] starts
    unarmed. Armed, tick(): check_bindings(strict=True) re-raises -> RV is skipped for this tick: still "open",
    current_step 0 (not evaluated either), the arm used up. The one WARNING "reference check failed, skipped this
    tick: validator hiccup" in the output is expected. Next tick(): the validator passes, RV is evaluated ->
    "done".
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []
SECTION = [""]


def check(label, actual, expected):
    label = f"{SECTION[0]} {label}".strip()
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def section(name, title):
    SECTION[0] = name
    print(f"{name} {title}")


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
AT_PLACE = {"type": "at_place", "params": {"place": "place"}}
HOLDS = {"type": "holds_item", "params": {"item": "thing", "count": 1}}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-engine-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__
    from app.core import db, hooks, periodic_jobs
    db.init_schema()
    from app.core import quest_catalog as qc
    from app.core import quest_types as qt
    from app.core.activity_engine import ConditionResult
    from app.core.game_time import GameDuration, GameTime
    from app.core.perception import record_utterance
    from app.core.timeutils import game_time, set_game_time
    from app.core.users import create_user, update_user
    from app.models import character as chars, events, inventory, quests, relationship, world
    from app.models.notifications import get_notifications
    try:
        from app.core import quest_engine as qe
    except ImportError as e:
        print(f"  FAIL app.core.quest_engine is missing: {e}")
        print("FAIL smoke_quest_engine: 1 failed")
        return 1

    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Front"}, {"id": "r2", "name": "Back"}]},
                          sync_world=False)
    world.upsert_location({"id": "L2", "name": "Yard", "entry_room": "s1",
                           "rooms": [{"id": "s1", "name": "Gate"}]}, sync_world=False)
    for name in ("A", "B", "N", "Ola", "Nox"):
        loc, room = ("L1", "r2") if name == "N" else ("L2", "s1")
        assert chars.save_character_profile(
            name, {"current_location": loc, "current_room": room}, create_new=True), name
    for user, avatar in (("demo", "A"), ("demo2", "B")):
        uid = create_user(user, "smoke-password", allowed_characters=[avatar])
        update_user(uid, settings={"active_character": avatar})
    item_i = inventory.add_item("Lamp")["id"]
    item_p = inventory.add_item("Pebble")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    qt.register()
    qe.register()

    def move(name, loc, room=None):
        if chars.get_character_current_location(name) != loc:
            chars.save_character_current_location(name, loc)
        if room and chars.get_character_current_room(name) != room:
            chars.save_character_current_room(name, room)
        check(f"drain after moving {name}", qe.drain(), True)

    def say(speaker, to):
        move(speaker, chars.get_character_current_location(to), chars.get_character_current_room(to))
        record_utterance(speaker=speaker, content=f"Hello, {to}.", addressees=[to], source="loop")
        check(f"drain after {speaker} -> {to}", qe.drain(), True)

    def template(state="ready", **over):
        body = {**ERRAND, **over}
        body.pop("gm_notes", None)
        return quests.create_template(state=state, gm_notes=ERRAND["gm_notes"], **body)

    def errand_bindings(giver="N", thing=None, place=("L1", "r1")):
        return {"giver": {"name": giver}, "place": {"location_id": place[0], "room_id": place[1]},
                "thing": {"item_id": thing or item_i}}

    def run(rid):
        return quests.get_run(rid)

    def quest_notes(avatar, rid):
        return [n for n in get_notifications(limit=200, character_whitelist=[avatar])
                if n["type"] == "quest" and (n.get("metadata") or {}).get("run_id") == rid]

    def cleanup(*rids):
        for rid in rids:
            qe.cancel_run(rid)

    # 1 ----------------------------------------------------------------------------------------
    section("[1]", "validate_template")
    paths_of_empty = {i["path"] for i in qe.validate_template({})}
    check("empty: title", "title" in paths_of_empty, True)
    check("empty: steps", "steps" in paths_of_empty, True)
    check("reference quest", qe.validate_template(ERRAND), [])

    # 2 ----------------------------------------------------------------------------------------
    section("[2]", "start_run refusals and start")
    draft = template(state="draft")
    try:
        qe.start_run(draft["id"], errand_bindings())
        check("draft refused", "started", "QuestRefused")
    except qe.QuestRefused as e:
        check("draft refused", bool(e.issues), True)
    errand = template()
    partial = errand_bindings()
    partial.pop("thing")
    try:
        qe.start_run(errand["id"], partial)
        check("thing unbound refused", "started", "QuestRefused")
    except qe.QuestRefused as e:
        check("thing unbound names the role", "bindings.thing" in {i["path"] for i in e.issues}, True)
    r1 = qe.start_run(errand["id"], errand_bindings(), started_by="smoke")
    check("open", (r1["state"], r1["current_step"]), ("open", 0))
    check("announced", bool(r1.get("news_event_id")), True)

    # 3 ----------------------------------------------------------------------------------------
    section("[3]", "NPCs fulfil nothing, steps are sequential")
    move("N", "L1", "r1")
    check("N in the room: unchanged", (run(r1["id"])["current_step"], run(r1["id"])["step_log"]), (0, []))
    check("evaluate(N)", qe.evaluate("N"), [])
    move("A", "L1", "r1")
    check("A in the room before ①: unchanged", run(r1["id"])["current_step"], 0)
    move("A", "L2")

    # 4 ----------------------------------------------------------------------------------------
    section("[4]", "the reference quest end to end")
    say("N", "A")
    got = run(r1["id"])
    check("① by A", (got["current_step"], [s["avatar"] for s in got["step_log"]]), (1, ["A"]))
    move("A", "L1", "r1")
    check("②", run(r1["id"])["current_step"], 2)
    inventory.add_to_inventory("A", item_i, 1)
    check("drain after the item", qe.drain(), True)
    got = run(r1["id"])
    check("③ -> done", (got["state"], len(got["step_log"])), ("done", 3))
    check("three notices for A", len(quest_notes("A", r1["id"])), 3)
    check("none for B", quest_notes("B", r1["id"]), [])

    # 4b ---------------------------------------------------------------------------------------
    section("[4b]", "talk before the quest")
    move("A", "L2")
    say("Ola", "A")
    check("fact before any run", quests.has_fact("A", qt.FACT_SPOKE_WITH, "Ola"), True)
    r4b = qe.start_run(errand["id"], errand_bindings(giver="Ola"))
    check("first evaluation", qe.evaluate("A"), [r4b["id"]])
    check("① done at once", run(r4b["id"])["current_step"], 1)
    cleanup(r4b["id"])

    # 4c ---------------------------------------------------------------------------------------
    section("[4c]", "world-owned progress")
    r4c = qe.start_run(errand["id"], errand_bindings())
    qe.evaluate("A")
    move("B", "L1", "r1")
    got = run(r4c["id"])
    check("① by A, ② by B", [s["avatar"] for s in got["step_log"]], ["A", "B"])
    check("waits at ③", got["current_step"], 2)
    cleanup(r4c["id"])
    move("B", "L2")

    # 5 ----------------------------------------------------------------------------------------
    section("[5]", "cascade")
    cascade = template(title="Cascade", steps=[
        {"id": "a", "text": "Be there.", "condition": AT_PLACE},
        {"id": "b", "text": "Hold it.", "condition": HOLDS}])
    move("A", "L1", "r1")
    r5 = qe.start_run(cascade["id"], errand_bindings())
    check("one call", qe.evaluate("A", "character.entered_room"), [r5["id"]])
    check("done", run(r5["id"])["state"], "done")

    # 6 ----------------------------------------------------------------------------------------
    section("[6]", "hidden start")
    move("A", "L2")
    hidden_t = template(title="Hidden errand", start_condition=AT_PLACE)
    r6 = qe.start_run(hidden_t["id"], errand_bindings(giver="B"))
    check("hidden, not announced", (r6["state"], r6["news_event_id"]), ("hidden", ""))
    move("A", "L1", "r1")
    got = run(r6["id"])
    check("opened", (got["state"], got["current_step"]), ("open", 0))
    check("started_game_ts set", bool(got["started_game_ts"]), True)
    check("still not announced", got["news_event_id"], "")
    check("no news event with its title",
          [e for e in events.get_all_events() if "Hidden errand" in e.get("text", "")], [])
    cleanup(r6["id"])
    move("A", "L2")

    # 7 ----------------------------------------------------------------------------------------
    section("[7]", "prerequisites")
    locked_t = template(title="Trust", prerequisites={
        "condition": {"type": "relationship_at_least", "params": {"character": "giver", "strength": 50}},
        "locked_text": "Earn their trust first."})
    r7 = qe.start_run(locked_t["id"], errand_bindings())
    check("A does not advance", qe.evaluate("A"), [])
    check("step 0", run(r7["id"])["current_step"], 0)
    check("A locked", qe.avatar_view(run(r7["id"]), "A"),
          {"locked": True, "locked_text": "Earn their trust first."})
    relationship.update_relationship_manual("B", "N", strength=60)
    say("N", "B")
    got = run(r7["id"])
    check("① by B", [s["avatar"] for s in got["step_log"]], ["B"])
    check("B not locked", qe.avatar_view(got, "B"), {"locked": False, "locked_text": ""})
    cleanup(r7["id"])

    # 8 ----------------------------------------------------------------------------------------
    section("[8]", "the snapshot wins")
    snap_t = template(title="Snapshot", steps=[{"id": "a", "text": "Be there.", "condition": AT_PLACE}])
    r8 = qe.start_run(snap_t["id"], errand_bindings())
    quests.update_template(snap_t["id"], {"steps": [
        {"id": "a", "text": "Hold five.", "condition": {"type": "holds_item", "params": {"item": "thing", "count": 5}}}]},
        base_revision=snap_t["revision"])
    move("A", "L1", "r1")
    check("done on the old step", run(r8["id"])["state"], "done")
    move("A", "L2")

    # 9 ----------------------------------------------------------------------------------------
    section("[9]", "broken references")
    pebble_t = template(title="Pebble", steps=[{"id": "a", "text": "Hold it.", "condition": HOLDS}])
    r9 = qe.start_run(pebble_t["id"], errand_bindings(thing=item_p))
    check("announced", bool(r9["news_event_id"]), True)
    inventory.delete_item(item_p)
    qe.tick()
    got = run(r9["id"])
    check("broken", got["state"], "broken")
    check("one issue", [(i["path"], i["code"]) for i in got["issues"]], [("bindings.thing", "unknown_item")])
    check("announcement deleted", events.get_event(r9["news_event_id"]), None)
    r9b = qe.start_run(errand["id"], errand_bindings(giver="Nox"))
    check("Nox deleted", chars.delete_character("Nox"), True)
    check("broken without a tick", run(r9b["id"])["state"], "broken")

    # 10 ---------------------------------------------------------------------------------------
    section("[10]", "unloaded type")
    qc.register("smoke_x", lambda: [qc.QuestType(
        id="x_flag", kind="condition", label="X flag", description="always", signals=("character.entered_room",),
        evaluate=lambda params, ctx: ConditionResult(True, True, ""))])
    x_t = template(title="X", steps=[{"id": "a", "text": "Flag.", "condition": {"type": "x_flag", "params": {}}}])
    rx = qe.start_run(x_t["id"], errand_bindings())
    hooks.unregister_owned_providers("smoke_x")
    try:
        changed = qe.evaluate("A")
        check("evaluate raises nothing, RX unchanged", (rx["id"] in changed, run(rx["id"])["current_step"]),
              (False, 0))
    except Exception as e:  # noqa: BLE001
        check("evaluate raises nothing", repr(e), "no exception")
    move("A", "L1", "r1")
    y_t = template(title="Y", steps=[{"id": "a", "text": "Be there.", "condition": AT_PLACE}])
    ry = qe.start_run(y_t["id"], errand_bindings())
    qe.tick()
    got = run(rx["id"])
    check("RX broken", (got["state"], [i["code"] for i in got["issues"]]), ("broken", ["type_not_registered"]))
    check("RY done in the same tick", run(ry["id"])["state"], "done")

    # 11 ---------------------------------------------------------------------------------------
    section("[11]", "freeze")
    errand_now = quests.get_template(errand["id"])
    re_run = quests.create_run(template=errand_now, bindings=errand_bindings(), state="open",
                               expires_at=(game_time() - GameDuration.of(hours=1)).canonical())
    world.set_world_frozen(True)
    try:
        check("periodic gate paused", periodic_jobs._is_paused(), True)
        check("RE still open", run(re_run["id"])["state"], "open")
        f_t = template(title="F", steps=[{"id": "a", "text": "Back room.", "condition": AT_PLACE}])
        rf = qe.start_run(f_t["id"], errand_bindings(place=("L1", "r2")))
        move("A", "L1", "r2")
        check("own action evaluated while frozen", run(rf["id"])["state"], "done")
        qe.tick()
        check("direct tick expires RE", run(re_run["id"])["state"], "failed")
    finally:
        world.set_world_frozen(False)
    move("A", "L2")

    # 12 ---------------------------------------------------------------------------------------
    section("[12]", "cancel")
    r12 = qe.start_run(errand["id"], errand_bindings())
    event_id = r12["news_event_id"]
    check("announced", bool(event_id) and events.get_event(event_id) is not None, True)
    check("cancel", qe.cancel_run(r12["id"]), True)
    check("cancelled", run(r12["id"])["state"], "cancelled")
    check("event gone", (events.get_event(event_id), [e for e in events.list_events() if e["id"] == event_id]),
          (None, []))
    check("second cancel", qe.cancel_run(r12["id"]), False)

    # 13 ---------------------------------------------------------------------------------------
    section("[13]", "restart")
    r13 = qe.start_run(y_t["id"], errand_bindings())
    check("drain", qe.drain(), True)
    qe._reset_for_tests()
    move("A", "L1", "r1")
    check("first signal after the reset", run(r13["id"])["state"], "done")
    server_src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    check("server registers the types", "quest_types.register()" in server_src, True)
    check("server registers the engine", "quest_engine.register()" in server_src, True)

    # 14 ---------------------------------------------------------------------------------------
    section("[14]", "a raising validator skips the tick, never breaks the run")
    armed = [False]

    def v_validate(params, bindings):
        if armed[0] and bindings is not None:
            armed[0] = False
            raise RuntimeError("validator hiccup")
        return []

    qc.register("smoke_v", lambda: [qc.QuestType(
        id="v_flag", kind="condition", label="V flag", description="always", validate=v_validate,
        evaluate=lambda params, ctx: ConditionResult(True, True, ""))])
    v_t = template(title="V", steps=[{"id": "a", "text": "Flag.", "condition": {"type": "v_flag", "params": {}}}])
    rv = qe.start_run(v_t["id"], errand_bindings())
    armed[0] = True
    qe.tick()
    got = run(rv["id"])
    check("after the raising tick", (got["state"], got["current_step"], armed[0]), ("open", 0, False))
    qe.tick()
    check("next tick evaluates it", run(rv["id"])["state"], "done")

    if FAILURES:
        print(f"FAIL smoke_quest_engine: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_engine: [1]-[14]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
