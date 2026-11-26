#!/usr/bin/env python3
"""Smoke: the quest effects worker (`app/core/quest_effects.py`) and object registry (`app/core/quest_objects.py`).

Quest system stage 2, Task 4 (D8-D12, rulings a-e). Throwaway storage (`paths.init(<tmpdir>)` BEFORE any world-DB
module), no server, no LLM, no media. `quest_engine.register()` is NOT called (the smoke drives `evaluate`, `tick`
and `pass_once` directly, except in (k) which starts the `quest-effects` thread).

Usage:
    ./.venv/bin/python scripts/smoke_quest_effects.py

FIXTURE
    Locations: L1 (rooms r1 = entry "Front", r2 = "Back"), L2 (room s1 = entry "Gate").
    Characters: A (avatar of user "demo", active_character A), N, Gil (NPCs) — all start in L2/s1.
    Items: Lamp, Spare (`inventory.add_item`).
    Game clock: Y0001-D010T12:00:00.
    Stub effect types under owner "test":
      - `t.make` (object_kind "event", text param "text"): records (run_id, effect_key, position, avatar, text) in
        CALLS, inserts a global ambient event, returns [CreatedObject("event", {"event_id": ev["id"]}, text)].
      - `t.slow` (object_kind "t_slow", registered with exists -> SLOW["done"], remove -> "done", label -> "slow"):
        increments SLOW["calls"], returns [CreatedObject("t_slow", {"n": 1}, "slow", status="live" if done else "pending")].
      - `t.fail` (object_kind ""): increments FAIL["calls"], raises EffectFailed("stub failure") while FAIL["on"] is
        True, else returns [].

WHAT FOLLOWS BY HAND (plan D8-D12, Task 4 brief)
 (a) Setup `[m: t.make "a"]`:
     - start_run -> state "preparing", news_event_id "", started_game_ts "", absent from
       quest_book.build_player_quests("A")["quests"] (ruling a: preparing runs are not announced or shown).
     - pass_once() -> opened == [run_id], state "open", news_event_id non-empty and event_exists True,
       started_game_ts non-empty, object m status "live", payout setup state "applied".
 (a2) Same setup plus start_condition `at_place place` (L1/r1, while A stands in L2/s1):
     - pass_once() -> opened == [run_id], state "hidden", news_event_id "", started_game_ts "" (D9).
 (b) Pending object reconciliation, setup `[s: t.slow]` with SLOW["done"] = False:
     - pass 1 -> state "preparing", SLOW["calls"] == 1, 1 object row for s with status "pending".
     - pass 2 -> exists returns False -> re-applied: SLOW["calls"] == 2, still 1 row for s (reused), still "preparing".
     - SLOW["done"] = True; pass 3 -> exists returns True -> promoted to "live" without calling apply
       (SLOW["calls"] stays 2) -> state "open".
 (c) Setup failure and retry, setup `[m: t.make "c", f: t.fail]` with FAIL["on"] = True:
     - pass 1 -> m is "live", run stays "preparing", run issues ==
       [{"path": "setup_effects.1", "code": "effect_failed", "message": "stub failure"}], result["failed"] >= 1.
     - pass 2 -> preparing run with non-empty issues is skipped: no new call of t.make or t.fail for this run.
     - FAIL["on"] = False; retry(run_id) -> True, run issues == [].
     - pass 3 -> m already live so t.make is NOT called again (1 total call for this run), t.fail called once more,
       state "open".
     - retry(open run with no failed payouts) -> False; retry("qr_unknown") -> False.
 (c2) Step payout failure and retry: no setup, steps [s1 at_place L1/r2 with on_done [f: t.fail], s2 at_place place2
     bound to L1/r1], FAIL["on"] = True:
     - move A to L1/r2, evaluate("A") -> step 0 done (current_step 1, state "open").
     - pass_once() -> payout "step:0" state "failed" with issues ==
       [{"path": "steps.0.on_done.0", "code": "effect_failed", "message": "stub failure"}].
     - FAIL["on"] = False; retry(run_id) -> True, payout "step:0" back to "pending".
     - pass_once() -> payout "step:0" state "applied".
 (d) Cancel during preparing, setup `[m: t.make "d", s: t.slow]` with SLOW["done"] = False:
     - pass 1 -> m "live", s "pending", run "preparing".
     - cancel_run -> True.
     - pass 2 -> m "reverted" and its event gone (event_exists False), s "reverted", payout "setup" "failed" with
       issue code "run_ended" (ruling e).
 (e) All five end paths (D10), each run with setup `[m: t.make "temp <x>", k: t.make "kept <x>" permanent True]`:
     1. done (place L1/r2; A moves to L1/r2; evaluate("A") -> done).
     2. cancel (place L1/r1; cancel_run -> cancelled).
     3. failed (place L1/r1, time_limit_s 3600; after opening pass, expires_at ==
        (GameTime.parse(started_game_ts) + GameDuration.of(seconds=3600)).canonical() (ruling b);
        advance clock +2 game hours and tick() -> failed).
     4. broken by tick (place L1/r1, thing Spare; delete_item(Spare); tick() -> broken).
     5. on_character_deleted (place L1/r1, giver Gil; delete_character("Gil") -> broken).
     - One pass_once() after all five ended -> result["reverted"] == 5; each run's m row "reverted" and its event
       gone; each run's k row stays "live" and its event still exists.
 (f) Restart reconciliation with pre-existing pending row, setup `[m: t.make "f"]`:
     - Before any pass, insert real event `ev` and add pending object row for key m pointing to `ev["id"]`.
     - _reset_for_tests() on engine and effects; pass_once() -> run "open", 1 row for m, status "live", ref still
       {"event_id": ev["id"]}, t.make NOT called for this run.
 (f2) Same with ref {"event_id": "evt_missing"} -> exists False -> t.make called once, still 1 row for m, status
     "live", ref updated to the newly created event's id.
 (g) World freeze does NOT gate the effects worker (D8):
     - set_world_frozen(True); start setup run -> pass_once() opens it; cancel_run -> pass_once() reverts its object.
 (h) Object gone at two consecutive ticks (D11):
     - setup `[m: t.make "h"]`, pass_once() opens it; delete_event(m's event).
     - tick 1 -> still "open", issues == [] (one missing read is no evidence).
     - tick 2 -> "broken" with issue {"path": "objects.m", "code": "object_gone", ...}.
     - pass_once() -> m row status "gone".
 (i) Concurrent pass_once serialization:
     - no setup, steps [s1 at_place L1/r2 with on_done [o: t.make "once"], s2 at_place place2 L1/r1]; A in L1/r2;
       evaluate("A") -> step 0 done, run open.
     - Two threads synchronized by threading.Barrier(2) call pass_once() simultaneously -> t.make called exactly
       once for this run with text "once", 1 object row for key o, payout "step:0" "applied".
 (j) Reward payout survives crash after run ended "done" (ruling d, e):
     - no setup, 1 step at_place L1/r2, rewards [prize: t.make "prize"]; A in L1/r2; evaluate("A") -> "done",
       payout "reward" pending with avatar "A".
     - _reset_for_tests() on engine and effects; pass_once() -> CALLS entry for this run is
       (run_id, "prize", "reward", "A", "prize"); prize row has permanent True and status "live" (event exists);
       payout "reward" "applied"; second pass_once() adds no new call.
 (k) Worker thread lifecycle:
     - quest_effects.start() -> daemon thread named "quest-effects" is alive.
     - Start a setup run -> within 5 s (without calling pass_once) it becomes "open".
     - quest_effects.stop() -> thread is no longer alive.
 (static) app/server.py source contains "quest_effects.start()" and "quest_effects.stop()".
"""
import os
import sys
import tempfile
import threading
import time
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


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-effects-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import db, hooks, quest_book, quest_catalog as qc, quest_effects as qfx
    from app.core import quest_engine as qe, quest_objects as qo, quest_types as qt
    from app.core.game_time import GameDuration, GameTime
    from app.core.timeutils import set_game_time
    from app.core.users import create_user, update_user
    from app.models import character as chars, events, inventory, quests, world

    db.init_schema()
    qt.register()
    # Intentionally DO NOT call qe.register() — this smoke drives evaluate/tick/pass_once directly.

    # Fixture
    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Front"}, {"id": "r2", "name": "Back"}]},
                          sync_world=False)
    world.upsert_location({"id": "L2", "name": "Yard", "entry_room": "s1",
                           "rooms": [{"id": "s1", "name": "Gate"}]}, sync_world=False)
    for name in ("A", "N", "Gil"):
        assert chars.save_character_profile(
            name, {"current_location": "L2", "current_room": "s1"}, create_new=True), name
    uid = create_user("demo", "smoke-password", allowed_characters=["A"])
    update_user(uid, settings={"active_character": "A"})
    lamp_id = inventory.add_item("Lamp")["id"]
    spare_id = inventory.add_item("Spare")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    # Stubs
    CALLS = []
    SLOW = {"done": False, "calls": 0}
    FAIL = {"on": True, "calls": 0}

    qo.register_kind(
        "t_slow",
        exists=lambda ref: SLOW["done"],
        remove=lambda ref: "done",
        label=lambda ref: "slow",
    )

    def _apply_make(params, ctx):
        CALLS.append((ctx.run["id"], ctx.effect_key, ctx.position, ctx.avatar, params["text"]))
        ev = events.add_event(params["text"], location_id=None, category="ambient")
        return [qfx.CreatedObject("event", {"event_id": ev["id"]}, params["text"])]

    def _apply_slow(params, ctx):
        SLOW["calls"] += 1
        return [qfx.CreatedObject("t_slow", {"n": 1}, "slow", status="live" if SLOW["done"] else "pending")]

    def _apply_fail(params, ctx):
        FAIL["calls"] += 1
        if FAIL["on"]:
            raise qfx.EffectFailed("stub failure")
        return []

    STUBS = [
        qc.QuestType(
            id="t.make", kind="effect", label="Make event", description="stub make",
            params=({"key": "text", "type": "text", "required": True},),
            apply=_apply_make, object_kind="event",
        ),
        qc.QuestType(
            id="t.slow", kind="effect", label="Slow object", description="stub slow",
            params=(), apply=_apply_slow, object_kind="t_slow",
        ),
        qc.QuestType(
            id="t.fail", kind="effect", label="Fail effect", description="stub fail",
            params=(), apply=_apply_fail, object_kind="",
        ),
    ]
    qc.register("test", lambda: STUBS)

    ROLES = [
        {"key": "place", "kind": "room", "description": "where"},
        {"key": "thing", "kind": "item", "description": "what"},
        {"key": "giver", "kind": "character", "description": "who"},
    ]
    AT_PLACE = {"type": "at_place", "params": {"place": "place"}}

    def mk_tpl(title, *, roles=None, steps=None, setup_effects=None, rewards=None,
               start_condition=None, time_limit_s=0):
        return quests.create_template(
            state="ready",
            title=title,
            roles=ROLES if roles is None else roles,
            steps=steps if steps is not None else [{"id": "s1", "text": "Go there.", "condition": AT_PLACE}],
            setup_effects=setup_effects or [],
            rewards=rewards or [],
            start_condition=start_condition or {},
            time_limit_s=time_limit_s,
        )

    def mk_bindings(*, place=("L1", "r1"), thing=None, giver="N", extra=None):
        b = {
            "place": {"location_id": place[0], "room_id": place[1]},
            "thing": {"item_id": thing or lamp_id},
            "giver": {"name": giver},
        }
        if extra:
            b.update(extra)
        return b

    def move_a(loc, room):
        if chars.get_character_current_location("A") != loc:
            chars.save_character_current_location("A", loc)
        if chars.get_character_current_room("A") != room:
            chars.save_character_current_room("A", room)

    def end_and_clean(*run_ids):
        for rid in run_ids:
            qe.cancel_run(rid)
        qfx.pass_once()

    try:
        # (a) ----------------------------------------------------------------------------------
        section("(a)", "setup opens and announces only after pass_once; a2 opens hidden")
        tpl_a = mk_tpl("Setup A", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "a"}}])
        ra = qe.start_run(tpl_a["id"], mk_bindings())
        check("preparing on start", ra["state"], "preparing")
        check("not announced on start", ra["news_event_id"], "")
        check("started_game_ts empty on start", ra["started_game_ts"], "")
        book_ids = [q["id"] for q in quest_book.build_player_quests("A")["quests"]]
        check("absent from player quest book while preparing", ra["id"] in book_ids, False)

        res_a = qfx.pass_once()
        check("opened contains ra", res_a["opened"], [ra["id"]])
        ra_after = quests.get_run(ra["id"])
        check("state open", ra_after["state"], "open")
        check("news_event_id set and exists",
              bool(ra_after["news_event_id"]) and events.event_exists(ra_after["news_event_id"]), True)
        check("started_game_ts set", bool(ra_after["started_game_ts"]), True)
        objs_a = quests.list_objects(ra["id"])
        check("object m live", [(o["effect_key"], o["status"]) for o in objs_a], [("m", "live")])
        pays_a = quests.list_payouts(states=(), run_id=ra["id"])
        check("setup payout applied", [(p["position"], p["state"]) for p in pays_a], [("setup", "applied")])

        tpl_a2 = mk_tpl("Setup A2", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "a2"}}],
                        start_condition=AT_PLACE)
        ra2 = qe.start_run(tpl_a2["id"], mk_bindings(place=("L1", "r1")))
        res_a2 = qfx.pass_once()
        ra2_after = quests.get_run(ra2["id"])
        check("a2 opened", res_a2["opened"], [ra2["id"]])
        check("a2 hidden, unannounced, no start stamp",
              (ra2_after["state"], ra2_after["news_event_id"], ra2_after["started_game_ts"]),
              ("hidden", "", ""))
        end_and_clean(ra["id"], ra2["id"])

        # (b) ----------------------------------------------------------------------------------
        section("(b)", "pending object reconciliation (t.slow)")
        SLOW["done"] = False
        SLOW["calls"] = 0
        tpl_b = mk_tpl("Slow B", setup_effects=[{"key": "s", "type": "t.slow", "params": {}}])
        rb = qe.start_run(tpl_b["id"], mk_bindings())
        qfx.pass_once()
        check("pass 1: preparing, 1 call, 1 pending row",
              (quests.get_run(rb["id"])["state"], SLOW["calls"],
               [(o["effect_key"], o["status"]) for o in quests.list_objects(rb["id"])]),
              ("preparing", 1, [("s", "pending")]))
        qfx.pass_once()
        check("pass 2: exists False -> re-applied, still 1 row, preparing",
              (quests.get_run(rb["id"])["state"], SLOW["calls"],
               [(o["effect_key"], o["status"]) for o in quests.list_objects(rb["id"])]),
              ("preparing", 2, [("s", "pending")]))
        SLOW["done"] = True
        qfx.pass_once()
        check("pass 3: exists True -> live without call, open",
              (quests.get_run(rb["id"])["state"], SLOW["calls"],
               [(o["effect_key"], o["status"]) for o in quests.list_objects(rb["id"])]),
              ("open", 2, [("s", "live")]))
        end_and_clean(rb["id"])

        # (c) ----------------------------------------------------------------------------------
        section("(c)", "setup failure, hold on issues, retry")
        FAIL["on"] = True
        FAIL["calls"] = 0
        tpl_c = mk_tpl("Fail C", setup_effects=[
            {"key": "m", "type": "t.make", "params": {"text": "c"}},
            {"key": "f", "type": "t.fail", "params": {}},
        ])
        rc = qe.start_run(tpl_c["id"], mk_bindings())
        res_c1 = qfx.pass_once()
        rc1 = quests.get_run(rc["id"])
        check("pass 1: m live, preparing, issue recorded, failed >= 1",
              ([(o["effect_key"], o["status"]) for o in quests.list_objects(rc["id"])],
               rc1["state"], rc1["issues"], res_c1["failed"] >= 1),
              ([("m", "live")], "preparing",
               [{"path": "setup_effects.1", "code": "effect_failed", "message": "stub failure"}], True))
        make_calls_c = sum(1 for c in CALLS if c[0] == rc["id"])
        fail_calls_c = FAIL["calls"]
        qfx.pass_once()
        check("pass 2: no calls while issues present",
              (sum(1 for c in CALLS if c[0] == rc["id"]), FAIL["calls"]),
              (make_calls_c, fail_calls_c))
        FAIL["on"] = False
        check("retry returns True", qfx.retry(rc["id"]), True)
        check("issues cleared by retry", quests.get_run(rc["id"])["issues"], [])
        qfx.pass_once()
        check("pass 3: m not re-applied, f called once more, open",
              (sum(1 for c in CALLS if c[0] == rc["id"]), FAIL["calls"], quests.get_run(rc["id"])["state"]),
              (1, fail_calls_c + 1, "open"))
        check("retry on open run with no failed payouts -> False", qfx.retry(rc["id"]), False)
        check("retry on unknown run -> False", qfx.retry("qr_unknown"), False)
        end_and_clean(rc["id"])

        # (c2) ---------------------------------------------------------------------------------
        section("(c2)", "step payout failure and retry")
        FAIL["on"] = True
        tpl_c2 = mk_tpl(
            "Step Fail C2",
            roles=ROLES + [{"key": "place2", "kind": "room", "description": "other"}],
            steps=[
                {"id": "s1", "text": "Go back.", "condition": AT_PLACE,
                 "on_done": [{"key": "f", "type": "t.fail", "params": {}}]},
                {"id": "s2", "text": "Go front.",
                 "condition": {"type": "at_place", "params": {"place": "place2"}}},
            ],
        )
        rc2 = qe.start_run(tpl_c2["id"], mk_bindings(
            place=("L1", "r2"), extra={"place2": {"location_id": "L1", "room_id": "r1"}}))
        move_a("L1", "r2")
        qe.evaluate("A")
        check("step 0 done, run open", (quests.get_run(rc2["id"])["current_step"], quests.get_run(rc2["id"])["state"]),
              (1, "open"))
        qfx.pass_once()
        p_c2 = quests.list_payouts(states=(), run_id=rc2["id"])
        check("step:0 payout failed with issue",
              [(p["position"], p["state"], p["issues"]) for p in p_c2],
              [("step:0", "failed", [{"path": "steps.0.on_done.0", "code": "effect_failed", "message": "stub failure"}])])
        FAIL["on"] = False
        check("retry step payout -> True", qfx.retry(rc2["id"]), True)
        check("payout re-armed pending",
              [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=rc2["id"])],
              [("step:0", "pending")])
        qfx.pass_once()
        check("payout applied after retry",
              [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=rc2["id"])],
              [("step:0", "applied")])
        move_a("L2", "s1")
        end_and_clean(rc2["id"])

        # (d) ----------------------------------------------------------------------------------
        section("(d)", "cancel during preparing reverts live and pending objects")
        SLOW["done"] = False
        tpl_d = mk_tpl("Cancel D", setup_effects=[
            {"key": "m", "type": "t.make", "params": {"text": "d"}},
            {"key": "s", "type": "t.slow", "params": {}},
        ])
        rd = qe.start_run(tpl_d["id"], mk_bindings())
        qfx.pass_once()
        objs_d1 = {o["effect_key"]: o for o in quests.list_objects(rd["id"])}
        check("pass 1: m live, s pending, preparing",
              (objs_d1["m"]["status"], objs_d1["s"]["status"], quests.get_run(rd["id"])["state"]),
              ("live", "pending", "preparing"))
        d_evt_id = objs_d1["m"]["ref"]["event_id"]
        check("cancel_run", qe.cancel_run(rd["id"]), True)
        qfx.pass_once()
        objs_d2 = {o["effect_key"]: o for o in quests.list_objects(rd["id"])}
        pays_d2 = quests.list_payouts(states=(), run_id=rd["id"])
        check("m reverted and event gone", (objs_d2["m"]["status"], events.event_exists(d_evt_id)), ("reverted", False))
        check("s reverted", objs_d2["s"]["status"], "reverted")
        check("setup payout failed with run_ended",
              [(p["position"], p["state"], [i["code"] for i in p["issues"]]) for p in pays_d2],
              [("setup", "failed", ["run_ended"])])

        # (e) ----------------------------------------------------------------------------------
        section("(e)", "all five end paths clean temp objects and keep permanent ones")
        def mk_e_tpl(tag, time_limit_s=0):
            return mk_tpl(f"End {tag}", setup_effects=[
                {"key": "m", "type": "t.make", "params": {"text": f"temp {tag}"}},
                {"key": "k", "type": "t.make", "params": {"text": f"kept {tag}"}, "permanent": True},
            ], time_limit_s=time_limit_s)

        r_done = qe.start_run(mk_e_tpl("done")["id"], mk_bindings(place=("L1", "r2")))
        r_cancel = qe.start_run(mk_e_tpl("cancel")["id"], mk_bindings(place=("L1", "r1")))
        r_fail = qe.start_run(mk_e_tpl("fail", time_limit_s=3600)["id"], mk_bindings(place=("L1", "r1")))
        r_broken = qe.start_run(mk_e_tpl("broken")["id"], mk_bindings(place=("L1", "r1"), thing=spare_id))
        r_del = qe.start_run(mk_e_tpl("del")["id"], mk_bindings(place=("L1", "r1"), giver="Gil"))
        e_runs = [r_done["id"], r_cancel["id"], r_fail["id"], r_broken["id"], r_del["id"]]

        qfx.pass_once()
        rf_open = quests.get_run(r_fail["id"])
        want_exp = (GameTime.parse(rf_open["started_game_ts"]) + GameDuration.of(seconds=3600)).canonical()
        check("ruling (b): expires_at recomputed at finish_preparing", rf_open["expires_at"], want_exp)

        # 1. done
        move_a("L1", "r2")
        qe.evaluate("A")
        move_a("L2", "s1")
        # 2. cancel
        qe.cancel_run(r_cancel["id"])
        # 3. failed by expiry + 4. broken by tick (deleted item)
        inventory.delete_item(spare_id)
        set_game_time(GameTime.parse(rf_open["started_game_ts"]) + GameDuration.of(hours=2))
        qe.tick()
        # 5. broken by on_character_deleted
        chars.delete_character("Gil")

        check("all five ended in expected states",
              [quests.get_run(rid)["state"] for rid in e_runs],
              ["done", "cancelled", "failed", "broken", "broken"])
        res_e = qfx.pass_once()
        check("reverted == 5", res_e["reverted"], 5)
        for rid in e_runs:
            by_key = {o["effect_key"]: o for o in quests.list_objects(rid)}
            check(f"{rid} temp reverted & event gone",
                  (by_key["m"]["status"], events.event_exists(by_key["m"]["ref"]["event_id"])),
                  ("reverted", False))
            check(f"{rid} kept live & event exists",
                  (by_key["k"]["status"], events.event_exists(by_key["k"]["ref"]["event_id"])),
                  ("live", True))

        # (f) ----------------------------------------------------------------------------------
        section("(f)", "restart reconciliation of pre-existing pending rows")
        tpl_f = mk_tpl("Restart F", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "f"}}])
        rf1 = qe.start_run(tpl_f["id"], mk_bindings())
        pre_ev = events.add_event("pre", location_id=None, category="ambient")
        quests.add_object(rf1["id"], effect_key="m", position="setup", kind="event",
                          ref={"event_id": pre_ev["id"]}, label="pre", status="pending")
        qe._reset_for_tests()
        qfx._reset_for_tests()
        qfx.pass_once()
        rf1_objs = quests.list_objects(rf1["id"])
        check("f1: open, 1 live row, ref unchanged, t.make not called",
              (quests.get_run(rf1["id"])["state"], len(rf1_objs), rf1_objs[0]["status"],
               rf1_objs[0]["ref"], sum(1 for c in CALLS if c[0] == rf1["id"])),
              ("open", 1, "live", {"event_id": pre_ev["id"]}, 0))

        rf2 = qe.start_run(tpl_f["id"], mk_bindings())
        quests.add_object(rf2["id"], effect_key="m", position="setup", kind="event",
                          ref={"event_id": "evt_missing"}, label="missing", status="pending")
        qe._reset_for_tests()
        qfx._reset_for_tests()
        qfx.pass_once()
        rf2_objs = quests.list_objects(rf2["id"])
        new_eid = rf2_objs[0]["ref"].get("event_id")
        check("f2: open, 1 live row, t.make called once, ref updated to real event",
              (quests.get_run(rf2["id"])["state"], len(rf2_objs), rf2_objs[0]["status"],
               sum(1 for c in CALLS if c[0] == rf2["id"]),
               new_eid != "evt_missing" and events.event_exists(new_eid)),
              ("open", 1, "live", 1, True))
        end_and_clean(rf1["id"], rf2["id"])

        # (g) ----------------------------------------------------------------------------------
        section("(g)", "world freeze does not gate the effects worker")
        world.set_world_frozen(True)
        try:
            tpl_g = mk_tpl("Frozen G", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "g"}}])
            rg = qe.start_run(tpl_g["id"], mk_bindings())
            qfx.pass_once()
            check("opens while frozen", quests.get_run(rg["id"])["state"], "open")
            qe.cancel_run(rg["id"])
            qfx.pass_once()
            check("reverts while frozen",
                  [o["status"] for o in quests.list_objects(rg["id"])], ["reverted"])
        finally:
            world.set_world_frozen(False)

        # (h) ----------------------------------------------------------------------------------
        section("(h)", "live object gone at two consecutive ticks marks run broken")
        tpl_h = mk_tpl("Gone H", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "h"}}])
        rh = qe.start_run(tpl_h["id"], mk_bindings())
        qfx.pass_once()
        h_evt_id = quests.list_objects(rh["id"])[0]["ref"]["event_id"]
        events.delete_event(h_evt_id)
        qe.tick()
        rh1 = quests.get_run(rh["id"])
        check("after tick 1: still open, no issues", (rh1["state"], rh1["issues"]), ("open", []))
        qe.tick()
        rh2 = quests.get_run(rh["id"])
        check("after tick 2: broken with objects.m / object_gone",
              (rh2["state"], [(i["path"], i["code"]) for i in rh2["issues"]]),
              ("broken", [("objects.m", "object_gone")]))
        qfx.pass_once()
        check("cleanup marks missing object gone",
              [o["status"] for o in quests.list_objects(rh["id"])], ["gone"])

        # (i) ----------------------------------------------------------------------------------
        section("(i)", "concurrent pass_once serialization")
        tpl_i = mk_tpl(
            "Concurrent I",
            roles=ROLES + [{"key": "place2", "kind": "room", "description": "other"}],
            steps=[
                {"id": "s1", "text": "Go back.", "condition": AT_PLACE,
                 "on_done": [{"key": "o", "type": "t.make", "params": {"text": "once"}}]},
                {"id": "s2", "text": "Go front.",
                 "condition": {"type": "at_place", "params": {"place": "place2"}}},
            ],
        )
        ri = qe.start_run(tpl_i["id"], mk_bindings(
            place=("L1", "r2"), extra={"place2": {"location_id": "L1", "room_id": "r1"}}))
        move_a("L1", "r2")
        qe.evaluate("A")
        check("step 0 done, run open", (quests.get_run(ri["id"])["current_step"], quests.get_run(ri["id"])["state"]),
              (1, "open"))
        barrier = threading.Barrier(2)

        def _worker():
            barrier.wait()
            qfx.pass_once()

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(5.0)
        t2.join(5.0)
        calls_i = [c for c in CALLS if c[0] == ri["id"]]
        check("t.make called once with 'once'", calls_i, [(ri["id"], "o", "step:0", "A", "once")])
        check("one object row for o",
              [(o["effect_key"], o["status"]) for o in quests.list_objects(ri["id"])], [("o", "live")])
        check("step:0 payout applied",
              [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=ri["id"])],
              [("step:0", "applied")])
        end_and_clean(ri["id"])

        # (j) ----------------------------------------------------------------------------------
        section("(j)", "reward payout survives crash after run ended done")
        tpl_j = mk_tpl(
            "Reward J",
            steps=[{"id": "s1", "text": "Go back.", "condition": AT_PLACE}],
            rewards=[{"key": "prize", "type": "t.make", "params": {"text": "prize"}, "permanent": True}],
        )
        rj = qe.start_run(tpl_j["id"], mk_bindings(place=("L1", "r2")))
        qe.evaluate("A")
        check("run done", quests.get_run(rj["id"])["state"], "done")
        check("reward payout pending with avatar A",
              [(p["position"], p["state"], p["avatar"]) for p in quests.list_payouts(states=(), run_id=rj["id"])],
              [("reward", "pending", "A")])
        qe._reset_for_tests()
        qfx._reset_for_tests()
        qfx.pass_once()
        calls_j = [c for c in CALLS if c[0] == rj["id"]]
        check("reward call entry", calls_j, [(rj["id"], "prize", "reward", "A", "prize")])
        objs_j = quests.list_objects(rj["id"])
        check("prize permanent and live, event exists",
              [(o["effect_key"], o["permanent"], o["status"], events.event_exists(o["ref"]["event_id"]))
               for o in objs_j],
              [("prize", True, "live", True)])
        check("reward payout applied",
              [(p["position"], p["state"]) for p in quests.list_payouts(states=(), run_id=rj["id"])],
              [("reward", "applied")])
        qfx.pass_once()
        check("second pass_once makes no new call", [c for c in CALLS if c[0] == rj["id"]], calls_j)
        move_a("L2", "s1")

        # (k) ----------------------------------------------------------------------------------
        section("(k)", "quest-effects thread start, automatic open, stop, and server wiring")
        qfx.start()
        try:
            alive_names = [t.name for t in threading.enumerate() if t.is_alive()]
            check("quest-effects thread alive", "quest-effects" in alive_names, True)
            tpl_k = mk_tpl("Thread K", setup_effects=[{"key": "m", "type": "t.make", "params": {"text": "k"}}])
            rk = qe.start_run(tpl_k["id"], mk_bindings())
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if quests.get_run(rk["id"])["state"] == "open":
                    break
                time.sleep(0.05)
            check("run opened by thread without pass_once", quests.get_run(rk["id"])["state"], "open")
        finally:
            qfx.stop()
        alive_after = [t.name for t in threading.enumerate() if t.is_alive()]
        check("quest-effects thread stopped", "quest-effects" in alive_after, False)
        server_src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        check("server calls quest_effects.start()", "quest_effects.start()" in server_src, True)
        check("server calls quest_effects.stop()", "quest_effects.stop()" in server_src, True)
    finally:
        qfx._reset_for_tests()
        hooks.unregister_owned_providers("test")

    if FAILURES:
        print(f"FAIL smoke_quest_effects: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_effects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
