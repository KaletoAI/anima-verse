#!/usr/bin/env python3
"""Smoke: generated quest template lifetime, filters, run deletion, and effects drop step.

Quest system stage 3, Task 5 (Decision 7). Throwaway storage (`paths.init(<tmpdir>)`
BEFORE any world-DB module), no server, no LLM, no media. Every expected value below
is derived by hand from Decision 7 and the Task 5 interface.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) KEPT FLAG ON CREATE.
      - `create_template(title="Auto U", origin="auto", kept=False)` stores `kept=0` ->
        both the returned dict and `get_template(id)` decode `kept` as `False`.
      - `create_template(title="Default")` omits `kept` -> defaults to `True`.
      Both rows are deleted before (b) so the table is empty.

  (b) TEMPLATE FILTER (`list_templates(generated=...)`).
      Four templates in an otherwise empty table:
        - `ADM`: `origin="admin"` (`kept=True` by default) — library
        - `AU`:  `origin="auto", kept=False`               — unkept generated
        - `AK`:  `origin="auto", kept=True`                — kept generated (library)
        - `ST`:  `origin="story", kept=False`              — unkept generated
      By definition (`GENERATED_ORIGINS == ("auto", "story")`, unkept generated <=>
      `origin IN GENERATED_ORIGINS AND kept == 0`):
        - `generated=True`  -> `{AU, ST}` (2 rows)
        - `generated=False` -> `{ADM, AK}` (2 rows, the library)
        - `generated=None` and `list_templates()` -> `{ADM, AU, AK, ST}` (all 4)
        - combined with `origin="auto"`: `generated=True` -> `{AU}`, `generated=False` -> `{AK}`.

  (c) RUN COUNTS BY ORIGIN AND LIST BY TEMPLATE.
      - One open run of `AU` (`r_au`) and one open run of `ADM` (`r_adm`):
        `count_runs(RUN_OPEN_STATES, origin="auto") == 1`,
        `count_runs(RUN_OPEN_STATES, origin="admin") == 1`,
        `count_runs(RUN_OPEN_STATES, origin="story") == 0`,
        `count_runs(RUN_OPEN_STATES) == 2`;
        `list_runs(template_id=AU)` returns `[r_au]`.
      - A temporary `auto` template `TMP` with 1 ended (`cancelled`) run `r_tmp`:
        before `delete_template(TMP)`, `count_runs(RUN_ENDED_STATES, origin="auto") == 1`;
        after `delete_template(TMP)`, the JOIN on `quest_templates` finds no live template
        row for `r_tmp`, so `count_runs(RUN_ENDED_STATES, origin="auto") == 0` while
        `count_runs(RUN_ENDED_STATES)` (no `origin` filter) is still `1`.

  (d) DELETE RUN (`delete_run`).
      - An open run is never deleted: `delete_run(r_au)` -> `False` and `get_run(r_au)`
        still returns the open run; `delete_run("qr_unknown")` -> `False`.
      - Run `r_full` of a 2-step template (`s0` has `on_done` so `record_step_done` at
        step 0 writes a `"step:0"` payout while `r_full` stays `"open"` at step 1), plus
        1 object row (`add_object`) and 1 judgement row (`claim_judgement` at step 1):
        while `"open"`, `delete_run(r_full)` -> `False` and all four rows remain;
        after `set_run_state(r_full, "cancelled")`, `delete_run(r_full)` -> `True`, and
        `get_run(r_full) is None`, `list_objects(r_full) == []`,
        `list_payouts(states=(), run_id=r_full) == []`, `list_judgements(r_full) == []`;
        calling `delete_run(r_full)` a second time -> `False`.
      All remaining fixtures from (b)–(d) are deleted so (e) starts with 0 templates,
      0 runs, and `list_chronicle(10) == []`.

  (e) DELETION WINDOW IN `quest_effects.pass_once()` STEP (5) (`CHRONICLE_SIZE == 10`).
      Stub object kind `t_hold` returns `REMOVE_LATER` from `remove`, so step (3) leaves
      a `revert_pending` row of kind `t_hold` uncleaned until the test marks it `reverted`.
      Templates and runs created in order:
        1. `N` (`origin="auto", kept=False`): 0 runs -> never touched by step (5).
        2. `P` (`origin="auto", kept=False`): 1 ended (`done`) run `rP` (ended 1st) with
           non-permanent `t_hold` object `objP` in `status="revert_pending"`.
        3. `G` (`origin="auto", kept=False`): 1 ended (`done`) run `rG` (ended 2nd) with
           1 `reverted` object, 1 `applied` payout, and 1 judgement row (cleanup done).
        4. `K` (`origin="auto", kept=True`): 1 ended (`done`) run `rK` (ended 3rd).
        5. `O` (`origin="auto", kept=False`): 1 `open` run `rO`.
        6. `ADM_E` (`origin="admin"`): 8 ended (`done`) runs `A1..A8` (ended 4th..11th).
      - At 11 ended runs (`rP, rG, rK, A1..A8`), `list_chronicle(10)` holds the 10 latest
        (`[A8..A1, rK, rG]`): `rG` is 10th (in chronicle) and `rP` is 11th (outside
        chronicle, held by `objP` in `revert_pending`).
        Pass 1 -> `dropped == 0`; `N`, `P`+`rP`, `G`+`rG`, `K`+`rK`, `O`+`rO` all survive.
      - End 2 more admin runs `A9, A10` (13 ended runs total; `list_chronicle(10)` is
        `[A10..A1]`, so `rK`, `rG`, and `rP` are ALL outside the chronicle window).
        Pass 2 -> `dropped == 1`: `G` and `rG` (plus `rG`'s object, payout, and judgement
        rows) are deleted; `K`+`rK` survive (`kept=True` even outside the chronicle);
        `O`+`rO` survive (open); `N` survives (0 runs); `P`+`rP` survive (`objP` still
        `revert_pending`).
      - `set_object_status(objP, "reverted")` finishes `rP`'s cleanup.
        Pass 3 -> `dropped == 1`: `P`, `rP`, and `objP` are deleted; `K`+`rK`, `O`+`rO`,
        and `N` still survive.
      - Permanent prop untag gate: `M` (`origin="story", kept=False`) has ended run `rM`
        with `permanent=True, kind="prop", status="live", ref={"prop_id": "prop_perm_1"}`
        (sidecar file in temp storage) followed by 10 ended admin runs so `rM` is outside
        `list_chronicle(10)`. While `props.set_quest_run` returns `False`, `"prop_perm_1"`
        is not in `_untagged_props` -> pass 4 has `dropped == 0` and `M`+`rM` survive.
        When `props.set_quest_run` returns `True`, step (4) untags `"prop_perm_1"` and
        step (5) in the same pass drops `M` and `rM` (`dropped == 1`).
      - Retryable failed payout gate:
        * `F` (`origin="auto", kept=False`) has 1 run `rF` with payout `"step:0"` set to
          `"failed"` and run state `"done"` (accepted by `quest_effects.retry()`).
        * Counter-case `FC` (`origin="auto", kept=False`) has 1 run `rFC` with payout
          `"step:0"` set to `"failed"` and run state `"failed"` (`in RUN_ENDED_STATES`,
          `!= "done"`, refused by `quest_effects.retry()`).
        * 10 more ended admin runs push both `rF` and `rFC` outside `list_chronicle(10)`.
        * Pass 6 -> `dropped == 1`: `FC` and `rFC` (and `rFC`'s payout) are deleted
          because a non-`done` ended run with a failed payout cannot be retried, whereas
          `F` and `rF` survive (`get_template(F)` and `get_run(rF)` are not `None`).
        * `set_payout(rF, "step:0", "applied")` clears the failed payout; pass 7 ->
          `dropped == 1`, and `F`, `rF`, and `rF`'s payout row are deleted.

Usage:
    ./.venv/bin/python scripts/smoke_quest_generated.py
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="smoke-quest-generated-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

    from app.core import paths
    paths.init(tmp)

    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import db, props, quest_effects, quest_objects
    from app.core.quest_book import CHRONICLE_SIZE
    from app.models import quests

    db.init_schema()
    check("CHRONICLE_SIZE == 10", CHRONICLE_SIZE, 10)
    check("GENERATED_ORIGINS", quests.GENERATED_ORIGINS, ("auto", "story"))

    # (a) ----------------------------------------------------------------------------------
    print("(a) create_template kept flag")
    u = quests.create_template(title="Auto U", origin="auto", kept=False)
    check("returned kept is False", u["kept"], False)
    check("get_template kept is False", quests.get_template(u["id"])["kept"], False)
    d = quests.create_template(title="Default")
    check("default kept is True", (d["kept"], quests.get_template(d["id"])["kept"]), (True, True))
    quests.delete_template(u["id"])
    quests.delete_template(d["id"])

    # (b) ----------------------------------------------------------------------------------
    print("(b) list_templates(generated=...)")
    adm = quests.create_template(title="Admin T", origin="admin")
    au = quests.create_template(title="Auto Unkept", origin="auto", kept=False)
    ak = quests.create_template(title="Auto Kept", origin="auto", kept=True)
    st = quests.create_template(title="Story Unkept", origin="story", kept=False)

    check("generated=True -> {AU, ST}",
          {t["id"] for t in quests.list_templates(generated=True)},
          {au["id"], st["id"]})
    check("generated=False -> {ADM, AK}",
          {t["id"] for t in quests.list_templates(generated=False)},
          {adm["id"], ak["id"]})
    check("generated=None -> all 4",
          {t["id"] for t in quests.list_templates(generated=None)},
          {adm["id"], au["id"], ak["id"], st["id"]})
    check("default list_templates() -> all 4",
          {t["id"] for t in quests.list_templates()},
          {adm["id"], au["id"], ak["id"], st["id"]})
    check("origin='auto' + generated=True -> {AU}",
          {t["id"] for t in quests.list_templates(origin="auto", generated=True)},
          {au["id"]})
    check("origin='auto' + generated=False -> {AK}",
          {t["id"] for t in quests.list_templates(origin="auto", generated=False)},
          {ak["id"]})

    # (c) ----------------------------------------------------------------------------------
    print("(c) count_runs(origin=...) and list_runs(template_id=...)")
    r_au = quests.create_run(template=au, bindings={}, state="open")
    r_adm = quests.create_run(template=adm, bindings={}, state="open")
    check("count_runs open origin='auto' == 1",
          quests.count_runs(quests.RUN_OPEN_STATES, origin="auto"), 1)
    check("count_runs open origin='admin' == 1",
          quests.count_runs(quests.RUN_OPEN_STATES, origin="admin"), 1)
    check("count_runs open origin='story' == 0",
          quests.count_runs(quests.RUN_OPEN_STATES, origin="story"), 0)
    check("count_runs open total == 2",
          quests.count_runs(quests.RUN_OPEN_STATES), 2)
    check("list_runs(template_id=AU)",
          [r["id"] for r in quests.list_runs(template_id=au["id"])], [r_au["id"]])

    tmp_tpl = quests.create_template(title="Tmp Auto", origin="auto", kept=False)
    r_tmp = quests.create_run(template=tmp_tpl, bindings={}, state="open")
    quests.set_run_state(r_tmp["id"], "cancelled")
    check("ended auto count before template delete == 1",
          quests.count_runs(quests.RUN_ENDED_STATES, origin="auto"), 1)
    quests.delete_template(tmp_tpl["id"])
    check("ended auto count after template delete == 0 (no live template row)",
          quests.count_runs(quests.RUN_ENDED_STATES, origin="auto"), 0)
    check("ended total count without origin still == 1",
          quests.count_runs(quests.RUN_ENDED_STATES), 1)
    check("cleanup r_tmp", quests.delete_run(r_tmp["id"]), True)

    # (d) ----------------------------------------------------------------------------------
    print("(d) delete_run")
    check("delete_run on open run -> False", quests.delete_run(r_au["id"]), False)
    check("open run still exists", quests.get_run(r_au["id"]) is not None, True)
    check("delete_run on unknown id -> False", quests.delete_run("qr_unknown"), False)

    full_tpl = quests.create_template(
        title="Full Run",
        steps=[
            {"id": "s0", "on_done": [{"key": "e0", "type": "narrate", "params": {}}]},
            {"id": "s1"},
        ],
    )
    r_full = quests.create_run(template=full_tpl, bindings={}, state="open")
    quests.record_step_done(r_full["id"], 0, avatar="Ava", mind="Ava")
    quests.add_object(r_full["id"], effect_key="e0", position="step:0", kind="item",
                      ref={"item_id": "i1"}, status="reverted")
    quests.claim_judgement(r_full["id"], 1, "c1", "Ava", "Ava",
                           now="2026-01-01T00:00:00+00:00", min_interval_s=0, newest_id=1)
    check("r_full has object, payout, judgement before end",
          (len(quests.list_objects(r_full["id"])),
           len(quests.list_payouts(states=(), run_id=r_full["id"])),
           len(quests.list_judgements(r_full["id"]))),
          (1, 1, 1))
    check("delete_run while still open -> False", quests.delete_run(r_full["id"]), False)
    check("rows untouched after refused delete_run",
          (quests.get_run(r_full["id"]) is not None,
           len(quests.list_objects(r_full["id"])),
           len(quests.list_payouts(states=(), run_id=r_full["id"])),
           len(quests.list_judgements(r_full["id"]))),
          (True, 1, 1, 1))

    quests.set_run_state(r_full["id"], "cancelled")
    check("delete_run on ended run -> True", quests.delete_run(r_full["id"]), True)
    check("ended run and child rows all gone",
          (quests.get_run(r_full["id"]),
           quests.list_objects(r_full["id"]),
           quests.list_payouts(states=(), run_id=r_full["id"]),
           quests.list_judgements(r_full["id"])),
          (None, [], [], []))
    check("second delete_run -> False", quests.delete_run(r_full["id"]), False)

    # Clear all fixtures from (b)–(d) before (e).
    for rid in (r_au["id"], r_adm["id"]):
        quests.set_run_state(rid, "cancelled")
        quests.delete_run(rid)
    for tid in (adm["id"], au["id"], ak["id"], st["id"], full_tpl["id"]):
        quests.delete_template(tid)
    check("clean slate before (e)",
          (quests.list_templates(), quests.list_runs(), quests.list_chronicle(CHRONICLE_SIZE)),
          ([], [], []))

    # (e) ----------------------------------------------------------------------------------
    print("(e) deletion window in quest_effects.pass_once() step (5)")
    quest_objects.register_kind(
        "t_hold",
        exists=lambda ref: True,
        remove=lambda ref: quest_objects.REMOVE_LATER,
        label=lambda ref: "hold",
    )

    def end_one(tpl: dict) -> dict:
        r = quests.create_run(template=tpl, bindings={}, state="open")
        assert quests.set_run_state(r["id"], "done")
        return quests.get_run(r["id"])

    try:
        quest_effects._reset_for_tests()

        tpl_n = quests.create_template(title="No Runs", origin="auto", kept=False)

        tpl_p = quests.create_template(title="Pending Cleanup", origin="auto", kept=False)
        r_p = end_one(tpl_p)
        obj_p = quests.add_object(
            r_p["id"], effect_key="h", position="setup", kind="t_hold",
            ref={}, permanent=False, status="revert_pending",
        )

        tpl_g = quests.create_template(
            title="Gone Outside Chronicle", origin="auto", kept=False,
            steps=[
                {"id": "s0", "on_done": [{"key": "e0", "type": "narrate", "params": {}}]},
                {"id": "s1"},
            ],
        )
        r_g = quests.create_run(template=tpl_g, bindings={}, state="open")
        quests.record_step_done(r_g["id"], 0, avatar="Ava", mind="Ava")
        quests.set_payout(r_g["id"], "step:0", "applied")
        quests.claim_judgement(r_g["id"], 1, "c1", "Ava", "Ava",
                               now="2026-01-01T00:00:00+00:00", min_interval_s=0, newest_id=1)
        quests.add_object(r_g["id"], effect_key="e0", position="step:0", kind="item",
                          ref={"item_id": "i1"}, permanent=False, status="reverted")
        assert quests.set_run_state(r_g["id"], "done")

        tpl_k = quests.create_template(title="Kept Auto", origin="auto", kept=True)
        r_k = end_one(tpl_k)

        tpl_o = quests.create_template(title="Open Auto", origin="auto", kept=False)
        r_o = quests.create_run(template=tpl_o, bindings={}, state="open")

        tpl_adm = quests.create_template(title="Admin Filler", origin="admin")
        admin_runs = [end_one(tpl_adm) for _ in range(8)]

        chron1 = [r["id"] for r in quests.list_chronicle(CHRONICLE_SIZE)]
        check("11 ended runs: G in chronicle (10th), P outside",
              (len(chron1), r_g["id"] in chron1, r_p["id"] in chron1),
              (10, True, False))

        res1 = quest_effects.pass_once()
        check("pass 1: dropped == 0 while G is in chronicle and P has revert_pending",
              res1["dropped"], 0)
        check("pass 1: N, P, G, K, O and runs all survive",
              (quests.get_template(tpl_n["id"]) is not None,
               quests.get_template(tpl_p["id"]) is not None,
               quests.get_run(r_p["id"]) is not None,
               quests.get_template(tpl_g["id"]) is not None,
               quests.get_run(r_g["id"]) is not None,
               quests.get_template(tpl_k["id"]) is not None,
               quests.get_run(r_k["id"]) is not None,
               quests.get_template(tpl_o["id"]) is not None,
               quests.get_run(r_o["id"]) is not None),
              (True, True, True, True, True, True, True, True, True))

        # End 2 more admin runs -> 13 ended runs total; r_k, r_g, r_p all outside chronicle(10).
        admin_runs.append(end_one(tpl_adm))
        admin_runs.append(end_one(tpl_adm))
        chron2 = {r["id"] for r in quests.list_chronicle(CHRONICLE_SIZE)}
        check("after 2 more admin runs: K, G, P all outside chronicle",
              (r_k["id"] in chron2, r_g["id"] in chron2, r_p["id"] in chron2),
              (False, False, False))

        res2 = quest_effects.pass_once()
        check("pass 2: dropped == 1 (G dropped)", res2["dropped"], 1)
        check("pass 2: G template, run, object, payout, judgement all deleted",
              (quests.get_template(tpl_g["id"]),
               quests.get_run(r_g["id"]),
               quests.list_objects(r_g["id"]),
               quests.list_payouts(states=(), run_id=r_g["id"]),
               quests.list_judgements(r_g["id"])),
              (None, None, [], [], []))
        check("pass 2: kept K, open O, runless N, uncleaned P all survive",
              (quests.get_template(tpl_k["id"]) is not None,
               quests.get_run(r_k["id"]) is not None,
               quests.get_template(tpl_o["id"]) is not None,
               quests.get_run(r_o["id"]) is not None,
               quests.get_template(tpl_n["id"]) is not None,
               quests.get_template(tpl_p["id"]) is not None,
               quests.get_run(r_p["id"]) is not None),
              (True, True, True, True, True, True, True))

        quests.set_object_status(obj_p, "reverted")
        res3 = quest_effects.pass_once()
        check("pass 3: dropped == 1 after P cleanup completes", res3["dropped"], 1)
        check("pass 3: P template, run, and object deleted",
              (quests.get_template(tpl_p["id"]),
               quests.get_run(r_p["id"]),
               quests.list_objects(r_p["id"])),
              (None, None, []))
        check("pass 3: K, O, N still survive",
              (quests.get_template(tpl_k["id"]) is not None,
               quests.get_run(r_k["id"]) is not None,
               quests.get_template(tpl_o["id"]) is not None,
               quests.get_run(r_o["id"]) is not None,
               quests.get_template(tpl_n["id"]) is not None),
              (True, True, True, True, True))

        # Permanent prop untag gate: story unkept template M waits until _untag_permanent_props succeeds.
        tpl_m = quests.create_template(title="Story Perm Prop", origin="story", kept=False)
        r_m = end_one(tpl_m)
        pid = "prop_perm_1"
        sidecar = props._sidecar_path(pid)
        assert sidecar is not None and sidecar.resolve().is_relative_to(Path(tmp).resolve()), sidecar
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text('{"name": "Rock"}', encoding="utf-8")
        quests.add_object(r_m["id"], effect_key="rock", position="setup", kind="prop",
                          ref={"prop_id": pid}, permanent=True, status="live")
        for _ in range(CHRONICLE_SIZE):
            end_one(tpl_adm)
        check("r_m outside chronicle", r_m["id"] in {r["id"] for r in quests.list_chronicle(CHRONICLE_SIZE)}, False)

        with patch.object(props, "set_quest_run", return_value=False):
            res4 = quest_effects.pass_once()
        check("pass 4: dropped == 0 while permanent prop not yet untagged",
              (res4["dropped"], quests.get_template(tpl_m["id"]) is not None, quests.get_run(r_m["id"]) is not None),
              (0, True, True))

        with patch.object(props, "set_quest_run", return_value=True):
            res5 = quest_effects.pass_once()
        check("pass 5: step (4) untags prop and step (5) drops M in same pass",
              (res5["dropped"], quests.get_template(tpl_m["id"]), quests.get_run(r_m["id"]),
               quests.list_objects(r_m["id"])),
              (1, None, None, []))

        # Retryable failed payout gate: done + failed payout holds template; non-done ended + failed payout does not.
        step_fx_steps = [
            {"id": "s0", "on_done": [{"key": "e0", "type": "narrate", "params": {}}]},
            {"id": "s1"},
        ]
        tpl_f = quests.create_template(title="Done Failed Payout", origin="auto", kept=False, steps=step_fx_steps)
        r_f = quests.create_run(template=tpl_f, bindings={}, state="open")
        quests.record_step_done(r_f["id"], 0, avatar="Ava", mind="Ava")
        assert quests.set_payout(r_f["id"], "step:0", "failed")
        assert quests.set_run_state(r_f["id"], "done")

        tpl_fc = quests.create_template(title="Failed Run Failed Payout", origin="auto", kept=False, steps=step_fx_steps)
        r_fc = quests.create_run(template=tpl_fc, bindings={}, state="open")
        quests.record_step_done(r_fc["id"], 0, avatar="Ava", mind="Ava")
        assert quests.set_payout(r_fc["id"], "step:0", "failed")
        assert quests.set_run_state(r_fc["id"], "failed")

        for _ in range(CHRONICLE_SIZE):
            end_one(tpl_adm)
        chron6 = {r["id"] for r in quests.list_chronicle(CHRONICLE_SIZE)}
        check("r_f and r_fc both outside chronicle",
              (r_f["id"] in chron6, r_fc["id"] in chron6),
              (False, False))

        res6 = quest_effects.pass_once()
        check("pass 6: dropped == 1 (only non-done FC dropped; done F held by failed payout)",
              res6["dropped"], 1)
        check("pass 6: FC template, run, and payout deleted",
              (quests.get_template(tpl_fc["id"]),
               quests.get_run(r_fc["id"]),
               quests.list_payouts(states=(), run_id=r_fc["id"])),
              (None, None, []))
        check("pass 6: F template, run, and failed payout survive",
              (quests.get_template(tpl_f["id"]) is not None,
               quests.get_run(r_f["id"]) is not None,
               len(quests.list_payouts(states=("failed",), run_id=r_f["id"]))),
              (True, True, 1))

        assert quests.set_payout(r_f["id"], "step:0", "applied")
        res7 = quest_effects.pass_once()
        check("pass 7: dropped == 1 after F payout is applied", res7["dropped"], 1)
        check("pass 7: F template, run, and payout deleted",
              (quests.get_template(tpl_f["id"]),
               quests.get_run(r_f["id"]),
               quests.list_payouts(states=(), run_id=r_f["id"])),
              (None, None, []))
    finally:
        quest_effects._reset_for_tests()
        quest_objects._KINDS.pop("t_hold", None)

    if FAILURES:
        print(f"FAIL — {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("PASS — quest generated templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
