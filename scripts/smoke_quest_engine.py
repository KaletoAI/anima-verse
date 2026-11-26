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
 10. Unloaded type (Review Focus 5, review R12): owner "smoke_x" registers condition "x_flag" (always passes,
    listens to character.entered_room). Run RX = [① x_flag]. Unregister smoke_x: evaluate("A") raises nothing and
    RX stays at current_step 0 (an unregistered type is unavailable, never passed). Then run RY = [① at_place place]
    while A already stands in L1/r1 (nothing evaluated yet). tick() -> RX still "open" without issues (a type missing
    from ONE catalog read is no evidence), RY "done" in the same tick. A second tick() -> RX "broken" (issue code
    type_not_registered): the same run missed the type at two consecutive ticks.
    RZ = [① z_flag] (owner smoke_z, never passes). Unregister, tick (missing once), register again, tick -> RZ open
    (the set of runs that missed a type is replaced each tick). Unregister, tick (missing once); a contributor
    "smoke_boom" that raises -> tick, tick: the strict catalog read raises, RZ is skipped both times, still "open"
    (a skipped run keeps its "missed last time" mark); boom removed, tick -> missing again after a missing mark ->
    RZ "broken" with type_not_registered.
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
 15. Role placeholders (final fix wave A). validate_template of Errand with
      title "Errand for {giver}" -> no issue (giver is a role); summary "Bring {{the}} {thing}." -> no issue
      ({{ }} are literal braces); step 0 text "Talk to {boss}." -> unknown_role at steps.0.text; step 1 hint
      "{place" -> bad_text at steps.1.hint; step 2 text "Hold it}" -> bad_text at steps.2.text; locked_text
      "Not you, {nobody}" -> unknown_role at prerequisites.locked_text; gm_notes "{whatever" -> no issue (never
      substituted). Exactly those four (path, code) pairs.
    Start: the labelled Errand (title "Errand for {giver}", step 0 text "Talk to {giver} now.", step 1 text
      "Go to {place} in {{brackets}}.") with
      E(N) -> binding_labels == {"giver": "N", "place": "Front", "thing": "Lamp"} (character name, room name,
      item name). render_text("Talk to {giver} at {place}, {{ok}}", run) == "Talk to N at Front, {ok}"; a key the
      run has no label for renders as the key: "{ghost}" -> "ghost".
    Frozen: room r1 of L1 is renamed "Lobby" after the start -> the run's binding_labels still say "Front".
    Quest book (quest_book.build_player_quests("A")): the entry of that run has title "Errand for N"; after A
    talks to N... A already spoke with N in [4], so evaluate("A") records ① at once; A stands in L2 -> the shown
    steps are ① "Talk to N now." (done) and the current ② "Go to Front in {brackets}." (old name). The step
    notice for A ends in ": Talk to N now." (the prefix is in A's language; a text no earlier notice had: notices are deduplicated by
    text while unread) and A's run announcement event text starts with
    "Errand for N".
 16. Time limit on signals (review R8): RL = create_run of [① at_place place] (L1/r1), open, expires_at one game
    hour in the past. A walks into L1/r1 -> the signal records nothing: RL "open", current_step 0, empty log.
    tick() -> RL "failed".
 17. Prerequisites gate the opening (review R9): hidden template, start_condition at_place place (L1/r2),
    prerequisites relationship_at_least giver(N) >= 50 (B has 60 since [7], A has none). A walks into L1/r2 ->
    still "hidden". B walks into L1/r2 -> "open".
 18. time_elapsed cannot start a quest (review R1): validate_template with start_condition time_elapsed hours=2 ->
    one issue (start_condition.type, not_allowed_here); inside {"any": [at_place, time_elapsed]} -> at
    start_condition.any.1.type; time_elapsed as a STEP condition -> no issue. A ready template stored with it
    directly (bypassing the route) -> start_run raises QuestRefused naming start_condition.type.
    Under prerequisites.condition it depends on the start condition: with start_condition AT_PLACE (a hidden run,
    which opens only once its prerequisites pass, and time_elapsed is unavailable until the run has opened) ->
    one issue (prerequisites.condition.type, not_allowed_here); with an empty start condition (the run is open
    from the start, so time_elapsed can be read) -> no issue.
 19. One failed fact write (review R3): run Errand with giver Ola (A has spoken with Ola since [4b], B never).
    add_fact raises for mind A only; Ola says a line addressed to [A, B], both in the room -> B's fact is written
    (has_fact(B, spoke_with, Ola)), and A is still evaluated: ① done by A (the older fact counts).
 20. A failed delete breaks nothing (review R4): run Errand with giver Zed. character.transaction raises once ->
    delete_character("Zed") False, Zed still listed, the run still "open". The real delete -> True, "broken".
 21. Deleted references, tick only (review R10a): L3 (rooms t1, t2), L4 (room u1), NPC Pim. Runs bound to L3/t2,
    to L4/u1 and to giver Pim. upsert L3 with t1 only, delete_location_row(L4), DELETE the characters row of Pim
    by raw SQL (no hook) -> tick() -> the three runs "broken" with unknown_room, unknown_location,
    unknown_character (at bindings.place, bindings.place, bindings.giver).
 22. Linked avatar swaps mid-run (review R10b): Kai (avatar of user "demo3") stands in L2/s1, create_linked(Kai,
    Lio). Run [① at_place place] bound to L5/v1. swap_presence(Kai -> Lio): Lio is the player-controlled body now
    and stands where Kai stood. Lio walks into L5/v1 -> "done", step_log[-1] avatar Lio, mind Kai.
 23. Empty step conditions (D1) and giver_role (D3) (stage 2, Task 1):
    - ERRAND with steps[1].condition set to {}, removed, or [] -> validate_template returns exactly
      [("steps.1.condition", "required")].
    - ERRAND with start_condition {} and prerequisites {"condition": {}} -> [] ({} stays legal there).
    - giver_role "giver" (character) or "" -> []; giver_role "place" (room) or "nobody" ->
      [("giver_role", "unknown_role")].
    - A template stored ready directly with steps[0].condition {} -> start_run raises QuestRefused whose issues
      contain ("steps.0.condition", "required").
    - Proof on the old code (pinned commit cd58910b6): its validate_template accepted ERRAND with
      steps[1].condition {} (-> []).
 24. "The big rock" — effect lists, target scope, placeholders, bindings, _unregistered (stage 2, Task 2):
    Test stubs registered under owner "test" ahead of core (create_prop, create_item, place_item, give_hint, narrate,
    give_item, eff_v; near_object, knows_secret, holds_item). Reference quest ROCK (roles giver/wood/glade; setup
    rock/box/box_spot/hint; steps s1 near_object rock, s2 knows_secret hint + on_done told, s3 holds_item box; rewards
    charm, charm_given):
    - a. validate_template(ROCK) == [] (all targets reachable with accepted kinds; stat_bonuses has placeholders=False;
      {glade}, {giver}, {wood} are roles).
    - b. setup order rock, box_spot, box, hint -> [("setup_effects.1.params.item", "not_yet_created")] (box is created
      at index 2, after box_spot at index 1; steps still see all setup keys).
    - c. s1 condition object "hint" -> [("steps.0.condition.params.object", "wrong_kind")] (hint is a secret,
      near_object accepts world_prop/room_prop/room_item).
    - d. on_done key "told" renamed "rock" -> [("steps.1.on_done.0.key", "duplicate")] (cross-list duplicate).
    - e. give_hint text "In {cave}." -> [("setup_effects.3.params.text", "unknown_role")].
    - f. steps[1].on_done = "x" -> [("steps.1.on_done", "shape")]; setup_effects = {} -> [("setup_effects", "shape"),
      ("steps.0.condition.params.object", "unknown_target"), ("steps.1.condition.params.secret", "unknown_target"),
      ("steps.2.condition.params.item", "unknown_target")] (no setup key exists; rewards still see charm).
    - g. 3 extra create_prop setup entries r2, r3, r4 -> rock+r2+r3 allowed (3), r4 is 4th ->
      [("setup_effects.6.type", "too_many")].
    - h. scope_at(ROCK, "step:1"): objects={rock:world_prop, box:item, box_spot:room_item, hint:secret},
      later={told, charm, charm_given}; "step:2" adds told:"" (5 keys); "setup:2" has {rock, box}; "reward:1" has
      4 setup + told + charm (6 keys) and later={charm_given}; "start".roles == {giver:character, wood:location,
      glade:room}; "nonsense" raises ValueError.
    - i. effect_positions(ROCK) -> [("setup_effects", "setup"), ("steps.1.on_done", "step:1"), ("rewards", "reward")].
    - j. check_bindings with 5th setup entry eff_v -> validate_template == [], check_bindings ==
      [("setup_effects.4.type", "eff_bound")].
    - k. _unregistered: with stubs registered, owed=("setup","step:1","reward") -> []; after unregistering "test"
      (core stays, so holds_item is registered), owed=() -> ["steps.0.condition.type", "steps.1.condition.type"];
      owed=("setup",) -> those 2 + setup_effects.0..3.type (6 paths); owed=("step:1",) -> those 2 +
      steps.1.on_done.0.type (3 paths).
    - l. After restoring core: validate_template(ERRAND) == [].
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
    check("first tick without the type: RX still open (one catalog read is no evidence)",
          (run(rx["id"])["state"], run(rx["id"])["issues"]), ("open", []))
    check("RY done in the same tick", run(ry["id"])["state"], "done")
    qe.tick()
    got = run(rx["id"])
    check("second tick still without it: RX broken", (got["state"], [i["code"] for i in got["issues"]]),
          ("broken", ["type_not_registered"]))
    qc.register("smoke_z", lambda: [qc.QuestType(
        id="z_flag", kind="condition", label="Z flag", description="never", signals=("character.entered_room",),
        evaluate=lambda params, ctx: ConditionResult(True, False, "no"))])
    z_t = template(title="Z", steps=[{"id": "a", "text": "Flag.", "condition": {"type": "z_flag", "params": {}}}])
    rz = qe.start_run(z_t["id"], errand_bindings())
    hooks.unregister_owned_providers("smoke_z")
    qe.tick()
    qc.register("smoke_z", lambda: [qc.QuestType(
        id="z_flag", kind="condition", label="Z flag", description="never", signals=("character.entered_room",),
        evaluate=lambda params, ctx: ConditionResult(True, False, "no"))])
    qe.tick()
    check("a type back by the next tick: RZ stays open", run(rz["id"])["state"], "open")
    hooks.unregister_owned_providers("smoke_z")
    qe.tick()

    def boom():
        raise RuntimeError("contributor hiccup")

    qc.register("smoke_boom", boom)
    qe.tick()
    qe.tick()
    check("a raising contributor skips the tick, never breaks", run(rz["id"])["state"], "open")
    hooks.unregister_owned_providers("smoke_boom")
    qe.tick()
    check("RZ broken once the type stays gone over two clean ticks",
          [i["code"] for i in run(rz["id"])["issues"]], ["type_not_registered"])

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

    # 15 ---------------------------------------------------------------------------------------
    section("[15]", "role placeholders")
    move("A", "L2")
    bad = {**ERRAND, "title": "Errand for {giver}", "summary": "Bring {{the}} {thing}.", "gm_notes": "{whatever",
           "steps": [{**ERRAND["steps"][0], "text": "Talk to {boss}."},
                     {**ERRAND["steps"][1], "hint": "{place"},
                     {**ERRAND["steps"][2], "text": "Hold it}"}],
           "prerequisites": {"condition": {}, "locked_text": "Not you, {nobody}"}}
    check("issues", sorted((i["path"], i["code"]) for i in qe.validate_template(bad)),
          [("prerequisites.locked_text", "unknown_role"), ("steps.0.text", "unknown_role"),
           ("steps.1.hint", "bad_text"), ("steps.2.text", "bad_text")])
    labelled = template(title="Errand for {giver}", steps=[
        {**ERRAND["steps"][0], "text": "Talk to {giver} now."},
        {**ERRAND["steps"][1], "text": "Go to {place} in {{brackets}}."}, ERRAND["steps"][2]])
    r15 = qe.start_run(labelled["id"], errand_bindings())
    check("labels", r15["binding_labels"], {"giver": "N", "place": "Front", "thing": "Lamp"})
    check("render", qe.render_text("Talk to {giver} at {place}, {{ok}}", r15), "Talk to N at Front, {ok}")
    check("unlabelled key", qe.render_text("{ghost}", r15), "ghost")
    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Lobby"}, {"id": "r2", "name": "Back"}]},
                          sync_world=False)
    check("frozen after the rename", run(r15["id"])["binding_labels"]["place"], "Front")
    qe.evaluate("A")
    from app.core.quest_book import build_player_quests
    entry = next(q for q in build_player_quests("A")["quests"] if q["id"] == r15["id"])
    check("book title", entry["title"], "Errand for N")
    check("book steps", [(s["text"], s["state"]) for s in entry["steps"]],
          [("Talk to N now.", "done"), ("Go to Front in {brackets}.", "current")])
    notes = [str(n.get("content") or n.get("body") or "") for n in quest_notes("A", r15["id"])]
    check("step notice renders the label (any language)", [n.endswith(": Talk to N now.") for n in notes], [True])
    check("announcement", (events.get_event(r15["news_event_id"]) or {}).get("text", "").startswith("Errand for N"),
          True)
    cleanup(r15["id"])

    # 16 ---------------------------------------------------------------------------------------
    section("[16]", "a step after the deadline is not recorded")
    move("A", "L2")
    late_t = template(title="Late", steps=[{"id": "a", "text": "Be there.", "condition": AT_PLACE}])
    rl = quests.create_run(template=quests.get_template(late_t["id"]), bindings=errand_bindings(), state="open",
                           expires_at=(game_time() - GameDuration.of(hours=1)).canonical())
    qe._refresh_live()  # created by the store, not start_run: the engine's live count must see it
    move("A", "L1", "r1")
    got = run(rl["id"])
    check("nothing recorded", (got["state"], got["current_step"], got["step_log"]), ("open", 0, []))
    qe.tick()
    check("tick fails it", run(rl["id"])["state"], "failed")
    move("A", "L2")

    # 17 ---------------------------------------------------------------------------------------
    section("[17]", "a locked avatar does not open a hidden run")
    gate_t = template(title="Gate", start_condition=AT_PLACE, prerequisites={
        "condition": {"type": "relationship_at_least", "params": {"character": "giver", "strength": 50}},
        "locked_text": ""})
    r17 = qe.start_run(gate_t["id"], errand_bindings(place=("L1", "r2")))
    move("A", "L1", "r2")
    check("A (locked) leaves it hidden", run(r17["id"])["state"], "hidden")
    move("B", "L1", "r2")
    check("B opens it", run(r17["id"])["state"], "open")
    cleanup(r17["id"])
    move("A", "L2")
    move("B", "L2")

    # 18 ---------------------------------------------------------------------------------------
    section("[18]", "time_elapsed is no start condition")
    elapsed = {"type": "time_elapsed", "params": {"hours": 2}}
    check("as the start condition", [(i["path"], i["code"]) for i in qe.validate_template(
        {**ERRAND, "start_condition": elapsed})], [("start_condition.type", "not_allowed_here")])
    check("inside any", [(i["path"], i["code"]) for i in qe.validate_template(
        {**ERRAND, "start_condition": {"any": [AT_PLACE, elapsed]}})],
          [("start_condition.any.1.type", "not_allowed_here")])
    check("as a step condition", qe.validate_template(
        {**ERRAND, "steps": [{"id": "a", "text": "Wait.", "condition": elapsed}]}), [])
    check("as a prerequisite of a hidden run", [(i["path"], i["code"]) for i in qe.validate_template(
        {**ERRAND, "start_condition": AT_PLACE, "prerequisites": {"condition": elapsed}})],
          [("prerequisites.condition.type", "not_allowed_here")])
    check("as a prerequisite with an empty start condition", qe.validate_template(
        {**ERRAND, "start_condition": {}, "prerequisites": {"condition": elapsed}}), [])
    stored = template(title="Waiting start", start_condition=elapsed)
    try:
        qe.start_run(stored["id"], errand_bindings())
        check("start refused", "started", "QuestRefused")
    except qe.QuestRefused as e:
        check("start refused", "start_condition.type" in {i["path"] for i in e.issues}, True)

    # 19 ---------------------------------------------------------------------------------------
    section("[19]", "one failed fact write")
    r19 = qe.start_run(errand["id"], errand_bindings(giver="Ola"))
    real_add_fact = quests.add_fact

    def flaky_add_fact(mind, kind, subject):
        if mind == "A":
            raise RuntimeError("database is locked")
        return real_add_fact(mind, kind, subject)

    move("B", "L2", "s1")
    move("A", "L2", "s1")
    move("Ola", "L2", "s1")
    quests.add_fact = flaky_add_fact
    try:
        record_utterance(speaker="Ola", content="Hello, both.", addressees=["A", "B"], source="loop")
        check("drain", qe.drain(), True)
    finally:
        quests.add_fact = real_add_fact
    check("B's fact written", quests.has_fact("B", qt.FACT_SPOKE_WITH, "Ola"), True)
    check("A still evaluated", [s["avatar"] for s in run(r19["id"])["step_log"]], ["A"])
    cleanup(r19["id"])

    # 20 ---------------------------------------------------------------------------------------
    section("[20]", "a failed delete breaks nothing")
    assert chars.save_character_profile("Zed", {"current_location": "L2", "current_room": "s1"}, create_new=True)
    r20 = qe.start_run(errand["id"], errand_bindings(giver="Zed"))
    real_tx = chars.transaction
    calls = [0]

    def failing_tx():
        calls[0] += 1
        raise RuntimeError("database is locked")

    chars.transaction = failing_tx
    try:
        check("delete refused", chars.delete_character("Zed"), False)
    finally:
        chars.transaction = real_tx
    check("Zed still there", "Zed" in chars.list_available_characters(), True)
    check("run still open", run(r20["id"])["state"], "open")
    check("real delete", chars.delete_character("Zed"), True)
    check("broken now", run(r20["id"])["state"], "broken")

    # 21 ---------------------------------------------------------------------------------------
    section("[21]", "deleted references, tick only")
    world.upsert_location({"id": "L3", "name": "Mill", "entry_room": "t1",
                           "rooms": [{"id": "t1", "name": "Floor"}, {"id": "t2", "name": "Loft"}]}, sync_world=False)
    world.upsert_location({"id": "L4", "name": "Barn", "entry_room": "u1",
                           "rooms": [{"id": "u1", "name": "Stall"}]}, sync_world=False)
    assert chars.save_character_profile("Pim", {"current_location": "L2", "current_room": "s1"}, create_new=True)
    room_run = qe.start_run(y_t["id"], errand_bindings(place=("L3", "t2")))
    loc_run = qe.start_run(y_t["id"], errand_bindings(place=("L4", "u1")))
    char_run = qe.start_run(errand["id"], errand_bindings(giver="Pim"))
    world.upsert_location({"id": "L3", "name": "Mill", "entry_room": "t1",
                           "rooms": [{"id": "t1", "name": "Floor"}]}, sync_world=False)
    check("L4 deleted", world.delete_location_row("L4"), True)
    with db.transaction() as conn:
        conn.execute("DELETE FROM characters WHERE name=?", ("Pim",))
    qe.tick()
    for label, rid, want in (("room", room_run["id"], ("bindings.place", "unknown_room")),
                             ("location", loc_run["id"], ("bindings.place", "unknown_location")),
                             ("character", char_run["id"], ("bindings.giver", "unknown_character"))):
        got = run(rid)
        check(f"{label} gone -> broken", (got["state"], [(i["path"], i["code"]) for i in got["issues"]]),
              ("broken", [want]))

    # 22 ---------------------------------------------------------------------------------------
    section("[22]", "a linked avatar swaps mid-run")
    from app.core.linked_characters import create_linked, swap_presence
    from app.models.account import is_player_controlled
    assert chars.save_character_profile("Kai", {"current_location": "L2", "current_room": "s1"}, create_new=True)
    uid3 = create_user("demo3", "smoke-password", allowed_characters=["Kai"])
    update_user(uid3, settings={"active_character": "Kai"})
    check("linked", create_linked("Kai", "Lio").get("ok"), True)
    world.upsert_location({"id": "L5", "name": "Pier", "entry_room": "v1",
                           "rooms": [{"id": "v1", "name": "Dock"}]}, sync_world=False)
    r22 = qe.start_run(y_t["id"], errand_bindings(place=("L5", "v1")))
    check("swap", swap_presence("Kai", "Lio").get("ok"), True)
    check("Lio is player-controlled", is_player_controlled("Lio"), True)
    check("Lio stands where Kai stood", chars.get_character_current_location("Lio"), "L2")
    move("Lio", "L5", "v1")
    got = run(r22["id"])
    check("done by the new body", (got["state"], {k: got["step_log"][-1][k] for k in ("avatar", "mind")}),
          ("done", {"avatar": "Lio", "mind": "Kai"}))

    # 23 ---------------------------------------------------------------------------------------
    section("[23]", "empty step conditions and the giver role")
    import subprocess
    import types

    def _errand_step1(cond_value, *, omit=False):
        step1 = {k: v for k, v in ERRAND["steps"][1].items() if not (omit and k == "condition")}
        if not omit:
            step1["condition"] = cond_value
        return {**ERRAND, "steps": [ERRAND["steps"][0], step1, ERRAND["steps"][2]]}

    empty_step1 = _errand_step1({})
    for label, bad_tpl in (("empty dict", empty_step1),
                           ("missing key", _errand_step1(None, omit=True)),
                           ("empty list", _errand_step1([]))):
        check(f"step 1 condition {label}",
              [(i["path"], i["code"]) for i in qe.validate_template(bad_tpl)],
              [("steps.1.condition", "required")])
    check("empty start_condition and prerequisites.condition stay legal",
          qe.validate_template({**ERRAND, "start_condition": {}, "prerequisites": {"condition": {}}}), [])
    check("giver_role character", qe.validate_template({**ERRAND, "giver_role": "giver"}), [])
    check("giver_role empty", qe.validate_template({**ERRAND, "giver_role": ""}), [])
    check("giver_role room",
          [(i["path"], i["code"]) for i in qe.validate_template({**ERRAND, "giver_role": "place"})],
          [("giver_role", "unknown_role")])
    check("giver_role unknown",
          [(i["path"], i["code"]) for i in qe.validate_template({**ERRAND, "giver_role": "nobody"})],
          [("giver_role", "unknown_role")])
    bad_ready = quests.create_template(
        title="Empty step ready", roles=ERRAND["roles"],
        steps=[{**ERRAND["steps"][0], "condition": {}}, ERRAND["steps"][1], ERRAND["steps"][2]],
        state="ready")
    try:
        qe.start_run(bad_ready["id"], errand_bindings())
        check("start_run refuses empty step condition", "started", "QuestRefused")
    except qe.QuestRefused as e:
        check("start_run refuses empty step condition",
              ("steps.0.condition", "required") in {(i["path"], i["code"]) for i in e.issues}, True)
    res = subprocess.run(["git", "show", "cd58910b6:app/core/quest_engine.py"],
                         cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print("  skip proof: git show cd58910b6 unavailable")
    else:
        mod_name = "quest_engine_cd58910b6"
        old_mod = types.ModuleType(mod_name)
        sys.modules[mod_name] = old_mod
        try:
            exec(compile(res.stdout, mod_name, "exec"), old_mod.__dict__)
            old_mod.quest_catalog = types.SimpleNamespace(**{
                **qc.__dict__,
                "check_expression": lambda expr, roles, *, allowed_kinds: qc.check_expression(
                    expr,
                    qc.Scope({str(r["key"]): str(r["kind"]) for r in (roles or [])
                              if isinstance(r, dict) and r.get("key")}, {}),
                    allowed_kinds=allowed_kinds,
                ),
            })
            old_issues = old_mod.validate_template(empty_step1)
        finally:
            sys.modules.pop(mod_name, None)
        check("old code (cd58910b6) accepted empty step condition", old_issues, [])

    # 24 ---------------------------------------------------------------------------------------
    section("[24]", "The big rock — effect lists, target scope, bindings, _unregistered")
    import copy
    from app.core.activity_engine import ConditionIssue

    def _s(tid, kind, params=(), **kw):
        return qc.QuestType(id=tid, kind=kind, label=tid, description=f"stub {tid}", params=params, **kw)

    ROCK_STUBS = [
        _s("create_prop", "effect", object_kind="world_prop", params=(
            {"key": "name", "type": "str", "required": True},
            {"key": "prompt", "type": "text", "required": True},
            {"key": "width_m", "type": "float", "min": 0.1, "max": 20},
            {"key": "depth_m", "type": "float", "min": 0.1, "max": 20},
            {"key": "height_m", "type": "float", "min": 0.1, "max": 20},
            {"key": "room", "type": "role", "role_kinds": ["room"]},
            {"key": "near", "type": "role", "role_kinds": ["location"]},
            {"key": "offset_x", "type": "float", "min": -200, "max": 200},
            {"key": "offset_z", "type": "float", "min": -200, "max": 200},
            {"key": "yaw", "type": "int", "min": 0, "max": 359},
        )),
        _s("create_item", "effect", object_kind="item", params=(
            {"key": "name", "type": "str", "required": True},
            {"key": "description", "type": "text"},
            {"key": "category", "type": "str"},
            {"key": "consumable", "type": "bool"},
            {"key": "effects", "type": "text", "placeholders": False},
            {"key": "stat_bonuses", "type": "text", "placeholders": False},
            {"key": "bonus_when", "type": "select", "choices": ["equipped", "carried"]},
            {"key": "image_prompt", "type": "text"},
        )),
        _s("place_item", "effect", object_kind="room_item", params=(
            {"key": "item", "type": "target", "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
            {"key": "room", "type": "role", "role_kinds": ["room"], "required": True},
            {"key": "quantity", "type": "int", "min": 1, "max": 20, "default": 1},
            {"key": "hidden", "type": "bool"},
            {"key": "difficulty", "type": "int", "min": 0, "max": 10, "default": 0},
            {"key": "note", "type": "str"},
        )),
        _s("give_hint", "effect", object_kind="secret", params=(
            {"key": "holder", "type": "role", "role_kinds": ["character"], "required": True},
            {"key": "text", "type": "text", "required": True},
        )),
        _s("narrate", "effect", object_kind="", params=(
            {"key": "text", "type": "text", "required": True},
            {"key": "to", "type": "role", "role_kinds": ["character"]},
        )),
        _s("give_item", "effect", object_kind="grant", params=(
            {"key": "item", "type": "target", "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
            {"key": "to", "type": "role", "role_kinds": ["character"]},
            {"key": "quantity", "type": "int", "min": 1, "max": 20, "default": 1},
        )),
        _s("eff_v", "effect", object_kind="",
           validate=lambda params, bindings: [ConditionIssue("eff_bound", "bound check")] if bindings is not None else []),
        _s("near_object", "condition", params=(
            {"key": "object", "type": "target", "role_kinds": [],
             "object_kinds": ["world_prop", "room_prop", "room_item"], "required": True},
            {"key": "radius_m", "type": "float", "min": 1, "max": 200, "default": 10},
        )),
        _s("knows_secret", "condition", params=(
            {"key": "secret", "type": "target", "role_kinds": [], "object_kinds": ["secret"], "required": True},
        )),
        _s("holds_item", "condition", params=(
            {"key": "item", "type": "target", "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
            {"key": "count", "type": "int", "min": 1, "default": 1},
        )),
    ]

    ROCK = {
        "title": "The big rock", "summary": "{giver} lost something near {wood}.", "gm_notes": "GM ONLY",
        "giver_role": "giver",
        "roles": [{"key": "giver", "kind": "character", "description": "who asks"},
                  {"key": "wood", "kind": "location", "description": "the wood"},
                  {"key": "glade", "kind": "room", "description": "where the box lies"}],
        "setup_effects": [
            {"key": "rock", "type": "create_prop", "params": {"name": "Big rock", "prompt": "a large mossy boulder",
              "height_m": 2.0, "near": "wood", "offset_x": 12, "offset_z": -4}},
            {"key": "box", "type": "create_item", "params": {"name": "Old tin box", "category": "tool"}},
            {"key": "box_spot", "type": "place_item", "params": {"item": "box", "room": "glade", "hidden": True, "difficulty": 3}},
            {"key": "hint", "type": "give_hint", "params": {"holder": "giver", "text": "The box lies hidden in {glade}."}}],
        "steps": [
            {"id": "s1", "text": "Find the big rock near {wood}.", "hint": "",
             "condition": {"type": "near_object", "params": {"object": "rock", "radius_m": 15}}},
            {"id": "s2", "text": "Find out where the box is.", "hint": "",
             "condition": {"type": "knows_secret", "params": {"secret": "hint"}},
             "on_done": [{"key": "told", "type": "narrate", "params": {"text": "You remember the hollow under the roots."}}]},
            {"id": "s3", "text": "Bring the tin box.", "hint": "",
             "condition": {"type": "holds_item", "params": {"item": "box", "count": 1}}}],
        "rewards": [
            {"key": "charm", "type": "create_item", "permanent": True,
             "params": {"name": "Lucky charm", "category": "tool", "stat_bonuses": "{\"focus\": 5}", "bonus_when": "carried"}},
            {"key": "charm_given", "type": "give_item", "permanent": True, "params": {"item": "charm"}}],
        "start_condition": {}, "prerequisites": {}, "time_limit_s": 0,
    }

    def _pc(issues_list):
        return sorted((i["path"], i["code"]) for i in issues_list)

    hooks.unregister_owned_providers(qt.OWNER)
    qc.register("test", lambda: ROCK_STUBS)
    qt.register()
    try:
        check("a. valid ROCK", qe.validate_template(ROCK), [])

        rock_b = copy.deepcopy(ROCK)
        rock_b["setup_effects"][1], rock_b["setup_effects"][2] = rock_b["setup_effects"][2], rock_b["setup_effects"][1]
        check("b. setup forward ref", _pc(qe.validate_template(rock_b)),
              [("setup_effects.1.params.item", "not_yet_created")])

        rock_c = copy.deepcopy(ROCK)
        rock_c["steps"][0]["condition"]["params"]["object"] = "hint"
        check("c. wrong_kind in condition", _pc(qe.validate_template(rock_c)),
              [("steps.0.condition.params.object", "wrong_kind")])

        rock_d = copy.deepcopy(ROCK)
        rock_d["steps"][1]["on_done"][0]["key"] = "rock"
        check("d. cross-list duplicate key", _pc(qe.validate_template(rock_d)),
              [("steps.1.on_done.0.key", "duplicate")])

        rock_e = copy.deepcopy(ROCK)
        rock_e["setup_effects"][3]["params"]["text"] = "In {cave}."
        check("e. effect text placeholder unknown_role", _pc(qe.validate_template(rock_e)),
              [("setup_effects.3.params.text", "unknown_role")])

        rock_f1 = copy.deepcopy(ROCK)
        rock_f1["steps"][1]["on_done"] = "x"
        check("f1. on_done not a list", _pc(qe.validate_template(rock_f1)), [("steps.1.on_done", "shape")])

        rock_f2 = copy.deepcopy(ROCK)
        rock_f2["setup_effects"] = {}
        check("f2. setup_effects not a list", _pc(qe.validate_template(rock_f2)), [
            ("setup_effects", "shape"),
            ("steps.0.condition.params.object", "unknown_target"),
            ("steps.1.condition.params.secret", "unknown_target"),
            ("steps.2.condition.params.item", "unknown_target"),
        ])

        rock_g = copy.deepcopy(ROCK)
        for k in ("r2", "r3", "r4"):
            rock_g["setup_effects"].append(
                {"key": k, "type": "create_prop", "params": {"name": "R", "prompt": "a rock", "room": "glade"}})
        check("g. 4th create_prop too_many", _pc(qe.validate_template(rock_g)),
              [("setup_effects.6.type", "too_many")])

        sc_s1 = qe.scope_at(ROCK, "step:1")
        check("h. step:1 objects", sc_s1.objects,
              {"rock": "world_prop", "box": "item", "box_spot": "room_item", "hint": "secret"})
        check("h. step:1 later", sc_s1.later, frozenset({"told", "charm", "charm_given"}))
        sc_s2 = qe.scope_at(ROCK, "step:2")
        check("h. step:2 objects", sc_s2.objects,
              {"rock": "world_prop", "box": "item", "box_spot": "room_item", "hint": "secret", "told": ""})
        check("h. setup:2 objects", qe.scope_at(ROCK, "setup:2").objects, {"rock": "world_prop", "box": "item"})
        sc_r1 = qe.scope_at(ROCK, "reward:1")
        check("h. reward:1 objects", sc_r1.objects,
              {"rock": "world_prop", "box": "item", "box_spot": "room_item", "hint": "secret",
               "told": "", "charm": "item"})
        check("h. reward:1 later", sc_r1.later, frozenset({"charm_given"}))
        check("h. start roles", qe.scope_at(ROCK, "start").roles,
              {"giver": "character", "wood": "location", "glade": "room"})
        try:
            qe.scope_at(ROCK, "nonsense")
            check("h. nonsense raises ValueError", "no error", "ValueError")
        except ValueError:
            check("h. nonsense raises ValueError", True, True)

        check("i. effect_positions", [(p, pos) for p, _l, pos in qe.effect_positions(ROCK)],
              [("setup_effects", "setup"), ("steps.1.on_done", "step:1"), ("rewards", "reward")])

        rock_j = copy.deepcopy(ROCK)
        rock_j["setup_effects"].append({"key": "v", "type": "eff_v", "params": {}})
        check("j. validate_template with eff_v", qe.validate_template(rock_j), [])
        check("j. check_bindings runs effect validator",
              _pc(qe.check_bindings(rock_j, {"giver": {"name": "N"}, "wood": {"location_id": "L1"},
                                             "glade": {"location_id": "L1", "room_id": "r1"}})),
              [("setup_effects.4.type", "eff_bound")])

        check("k. _unregistered with stubs",
              qe._unregistered(ROCK, owed=("setup", "step:1", "reward")), [])
        hooks.unregister_owned_providers("test")
        check("k. _unregistered owed=()", sorted(i["path"] for i in qe._unregistered(ROCK)),
              ["steps.0.condition.type", "steps.1.condition.type"])
        check("k. _unregistered owed=(setup,)", sorted(i["path"] for i in qe._unregistered(ROCK, owed=("setup",))),
              ["setup_effects.0.type", "setup_effects.1.type", "setup_effects.2.type", "setup_effects.3.type",
               "steps.0.condition.type", "steps.1.condition.type"])
        check("k. _unregistered owed=(step:1,)", sorted(i["path"] for i in qe._unregistered(ROCK, owed=("step:1",))),
              ["steps.0.condition.type", "steps.1.condition.type", "steps.1.on_done.0.type"])
    finally:
        hooks.unregister_owned_providers("test")
        hooks.unregister_owned_providers(qt.OWNER)
        qt.register()

    check("l. ERRAND still valid after restore", qe.validate_template(ERRAND), [])

    if FAILURES:
        print(f"FAIL smoke_quest_engine: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_engine: [1]-[24]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
