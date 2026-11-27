#!/usr/bin/env python3
"""Smoke: automatic quests — tick, giver pick, worker, expiry, re-checks (quest stage 3, Task 6).

Throwaway storage (``paths.init(<tmpdir>)`` BEFORE importing any world-DB
module), no server, no real LLM, no real task queue.

Usage:
    ./.venv/bin/python scripts/smoke_quest_auto.py

FIXTURE
    Locations:
      - "inn" ("Inn"), room "hall" ("Hall"), pos (0, 0).
      - "market" ("Market"), room "square" ("Square"), pos (30, 40).
    Characters:
      - Ava: player avatar of user "demo" at inn/hall (activated after case (b)).
      - Bram: NPC at inn/hall (same room as Ava).
      - Cora: NPC at market/square (different location).
    Stubs:
      - ``app.core.task_queue.get_task_queue`` -> fake queue recording ``submit``
        calls and returning ``"t1"``, ``"t2"``, ...
      - ``config.get`` -> ``quests.auto_enabled=True``, ``quests.max_open_auto_quests=1``
        (unless overridden for a case), other keys -> the passed default.
      - ``llm_router.llm_call`` -> scripted answers per case.

WHAT FOLLOWS BY HAND
  (a) Disabled switch (``quests.auto_enabled=False``): ``tick()`` ->
      ``{"skipped": "disabled"}``, 0 jobs submitted.
  (b) No avatar (user "demo" exists with empty ``active_character``): ``tick()`` ->
      ``{"skipped": "no_giver"}``, 0 jobs submitted.
  (c) Activate Ava on "demo": ``pick_giver()`` == ``("Bram", "Ava")`` (Bram shares
      inn/hall with Ava; Cora is at market/square). ``tick()`` submits 1 job with
      payload ``{"giver": "Bram", "avatar": "Ava"}``, ``queue_name="background"``,
      ``agent_name="auto_quest"``, ``deduplicate=True``, ``priority=30``,
      ``max_retries=0``, returning ``{"queued": "t1", "giver": "Bram", "avatar": "Ava"}``.
  (d) Sleeping NPC skipped: Bram ``is_sleeping=True`` -> ``pick_giver()`` is ``None``
      (Cora is at market, not inn) and ``tick()`` -> ``{"skipped": "no_giver"}``;
      restoring ``is_sleeping=False`` restores ``pick_giver() == ("Bram", "Ava")``.
  (e) Handler happy path: ``_handle({"giver": "Bram", "avatar": "Ava"})`` with
      draft prose + valid ``json:quest`` (step 0 ``at_place`` bound to ``"market"``,
      ``giver`` bound to ``"Bram"``) -> 1 stored template with ``origin == "auto"``,
      ``state == "ready"``, ``kept is False``, ``time_limit_s == 48 * 3600 == 172800``;
      1 run with ``state == "open"``, ``started_by == "auto"``, non-empty
      ``expires_at``, ``bindings["giver"] == {"name": "Bram"}``;
      ``open_auto_count() == 1``.
  (f) Cap full (1 open auto run == ``max_open_auto_quests == 1``): ``tick()`` ->
      ``{"skipped": "cap"}``, no new submit; ``live_givers() == {"Bram"}``.
  (g) Expiry frees the slot: ``quests.expire_runs`` at ``game_time() + 1000 h``
      marks the run ``"failed"``; ``open_auto_count() == 0``, ``live_givers() == set()``,
      and ``tick()`` queues ``"t2"`` instead of ``"cap"``.
  (h) Refused start leaves nothing behind: ``quest_engine.start_run`` patched to
      raise ``QuestRefused([{"path": "x", "code": "refused", "message": "m"}])`` ->
      ``_handle`` returns ``{"dropped": ["refused"]}``, template count and run
      count equal their pre-call values (the created template was deleted).
  (i) Generation failure (LLM returns prose twice without ``json:quest`` fence) ->
      ``_handle`` returns ``"dropped"`` containing ``"no_block"``, template count
      and run count unchanged.
  (j) Run-time re-checks in ``_handle`` (with ``llm_call`` scripted empty so any
      invocation fails):
        - Bram ``is_sleeping=True`` -> ``{"skipped": "giver asleep"}``
        - Bram moved to ``market/square`` -> ``{"skipped": "apart"}``
        - ``world.set_world_frozen(True)`` -> ``{"skipped": "world frozen"}``
        - ``quests.auto_enabled=False`` -> ``{"skipped": "disabled"}``
      0 ``llm_call`` invocations across all four.
  (k) Schema & scheduler wiring: ``SECTIONS["quests"]`` has ``scope == "world"``,
      ``world_group == "story"``, declares ``auto_enabled`` (default ``False``),
      ``max_open_auto_quests`` (default ``2``), ``auto_expiry_game_hours`` (default
      ``48``), each resolving ``scope_of("quests.<key>") == "world"``;
      ``periodic_jobs._SUB_TASKS`` contains ``(_sub_auto_quests, 300, "auto_quests")``
      and ``"auto_quests"`` is not detached.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def _fence(obj: dict) -> str:
    return "```json:quest\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```"


def _valid_obj(place_loc: str = "market") -> dict:
    return {
        "template": {
            "title": "Errand at {place}",
            "summary": "{giver} asks for a quick errand at {place}.",
            "gm_notes": "Auto quest smoke fixture.",
            "giver_role": "giver",
            "roles": [
                {"key": "giver", "kind": "character", "description": "Quest giver"},
                {"key": "place", "kind": "location", "description": "Destination"},
            ],
            "steps": [
                {
                    "id": "s1",
                    "text": "Walk to {place}.",
                    "condition": {"type": "at_place", "params": {"place": "place"}},
                }
            ],
            "start_condition": {},
            "prerequisites": {},
            "setup_effects": [],
            "rewards": [],
            "time_limit_s": 0,
        },
        "bindings": {
            "giver": {"name": "Bram"},
            "place": {"location_id": place_loc},
        },
    }


def _scripted_llm(answers: list):
    queue = list(answers)
    calls: list[tuple[str, str]] = []

    def fake(task, system_prompt, user_prompt, **kwargs):
        calls.append((task, str(kwargs.get("label") or "")))
        if not queue:
            raise AssertionError(f"unexpected extra llm_call #{len(calls)} for task={task}")
        nxt = queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return SimpleNamespace(content=nxt)

    return fake, calls


class _FakeTaskQueue:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.handlers: dict[str, object] = {}

    def submit(self, task_type: str, payload: dict, **kwargs) -> str:
        tid = f"t{len(self.submitted) + 1}"
        self.submitted.append({
            "task_id": tid,
            "task_type": task_type,
            "payload": payload,
            **kwargs,
        })
        return tid

    def register_handler(self, task_type: str, handler: object) -> None:
        self.handlers[task_type] = handler


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-auto-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)

    from app.core import (
        config,
        config_scope,
        db,
        llm_router,
        periodic_jobs,
        quest_auto,
        quest_engine,
        quest_types,
        task_queue,
    )
    from app.core.config_schema import SECTIONS
    from app.core.game_time import GameDuration
    from app.core.timeutils import game_time
    from app.core.users import create_user, update_user
    from app.models import character as chars, quests, world

    db.init_schema()
    quest_types.register()

    world.upsert_location(
        {
            "id": "inn",
            "name": "Inn",
            "entry_room": "hall",
            "pos_x": 0.0,
            "pos_z": 0.0,
            "rooms": [{"id": "hall", "name": "Hall"}],
        },
        sync_world=False,
    )
    world.upsert_location(
        {
            "id": "market",
            "name": "Market",
            "entry_room": "square",
            "pos_x": 30.0,
            "pos_z": 40.0,
            "rooms": [{"id": "square", "name": "Square"}],
        },
        sync_world=False,
    )
    for name, loc_id, room_id in (
        ("Ava", "inn", "hall"),
        ("Bram", "inn", "hall"),
        ("Cora", "market", "square"),
    ):
        assert chars.save_character_profile(
            name,
            {"current_location": loc_id, "current_room": room_id},
            create_new=True,
        ), name

    uid = create_user("demo", "smoke-password", allowed_characters=["Ava"])

    fake_tq = _FakeTaskQueue()
    cfg_overrides: dict[str, object] = {
        "quests.auto_enabled": False,
        "quests.max_open_auto_quests": 1,
    }

    def fake_cfg_get(key: str, default=None):
        return cfg_overrides[key] if key in cfg_overrides else default

    with (
        patch.object(task_queue, "get_task_queue", return_value=fake_tq),
        patch.object(config, "get", side_effect=fake_cfg_get),
    ):
        quest_auto.register()
        check("register wires TASK_TYPE handler", fake_tq.handlers.get("quest_auto") is quest_auto._handle)

        # (a) Disabled switch
        print("(a) disabled switch")
        res_a = quest_auto.tick()
        check("a. tick skipped disabled", res_a == {"skipped": "disabled"}, str(res_a))
        check("a. no submit", fake_tq.submitted == [], str(fake_tq.submitted))

        # (b) No avatar (user "demo" has empty active_character)
        print("(b) no avatar")
        cfg_overrides["quests.auto_enabled"] = True
        res_b = quest_auto.tick()
        check("b. tick skipped no_giver", res_b == {"skipped": "no_giver"}, str(res_b))
        check("b. no submit", fake_tq.submitted == [], str(fake_tq.submitted))

        # (c) pick_giver + tick submit once Ava is active
        print("(c) pick_giver and tick submit")
        update_user(uid, settings={"active_character": "Ava"})
        picked_c = quest_auto.pick_giver()
        check("c. pick_giver == ('Bram', 'Ava')", picked_c == ("Bram", "Ava"), str(picked_c))
        res_c = quest_auto.tick()
        check(
            "c. tick returns queued t1",
            res_c == {"queued": "t1", "giver": "Bram", "avatar": "Ava"},
            str(res_c),
        )
        check("c. 1 job submitted", len(fake_tq.submitted) == 1, str(fake_tq.submitted))
        job_c = fake_tq.submitted[0] if fake_tq.submitted else {}
        check("c. job task_type quest_auto", job_c.get("task_type") == "quest_auto", str(job_c))
        check("c. job payload", job_c.get("payload") == {"giver": "Bram", "avatar": "Ava"}, str(job_c))
        check("c. job queue background", job_c.get("queue_name") == "background", str(job_c))
        check("c. job agent_name auto_quest", job_c.get("agent_name") == "auto_quest", str(job_c))
        check("c. job deduplicate True", job_c.get("deduplicate") is True, str(job_c))
        check("c. job max_retries 0", job_c.get("max_retries") == 0, str(job_c))

        # (d) Sleeping NPC skipped
        print("(d) sleeping NPC skipped")
        bram_prof = chars.get_character_profile("Bram")
        bram_prof["is_sleeping"] = True
        assert chars.save_character_profile("Bram", bram_prof)
        try:
            check("d. Bram is sleeping", chars.is_character_sleeping("Bram") is True)
            check("d. pick_giver None when Bram asleep", quest_auto.pick_giver() is None)
            res_d = quest_auto.tick()
            check("d. tick skipped no_giver", res_d == {"skipped": "no_giver"}, str(res_d))
        finally:
            bram_prof = chars.get_character_profile("Bram")
            bram_prof["is_sleeping"] = False
            assert chars.save_character_profile("Bram", bram_prof)
        check("d. Bram restored awake", quest_auto.pick_giver() == ("Bram", "Ava"))

        # (e) Handler happy path
        print("(e) handler happy path")
        fake_llm, llm_calls = _scripted_llm([
            "Bram asks Ava to check the market stalls.",
            _fence(_valid_obj("market")),
        ])
        with patch.object(llm_router, "llm_call", fake_llm):
            res_e = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
        check("e. handler returns template_id & run_id", bool(res_e.get("template_id")) and bool(res_e.get("run_id")), str(res_e))
        check("e. handler giver & avatar", (res_e.get("giver"), res_e.get("avatar")) == ("Bram", "Ava"), str(res_e))
        tpls_e = quests.list_templates()
        check("e. 1 template stored", len(tpls_e) == 1, str(tpls_e))
        tpl_e = tpls_e[0]
        check("e. template origin auto", tpl_e["origin"] == "auto", str(tpl_e["origin"]))
        check("e. template state ready", tpl_e["state"] == "ready", str(tpl_e["state"]))
        check("e. template kept False", tpl_e["kept"] is False, str(tpl_e["kept"]))
        check("e. template time_limit_s == 48*3600", tpl_e["time_limit_s"] == 48 * 3600, str(tpl_e["time_limit_s"]))
        runs_e = quests.list_runs()
        check("e. 1 run stored", len(runs_e) == 1, str(runs_e))
        run_e = runs_e[0]
        check("e. run state open", run_e["state"] == "open", str(run_e["state"]))
        check("e. run started_by auto", run_e["started_by"] == "auto", str(run_e["started_by"]))
        check("e. run expires_at non-empty", bool(run_e["expires_at"]), str(run_e["expires_at"]))
        check("e. run giver bound to Bram", run_e["bindings"].get("giver") == {"name": "Bram"}, str(run_e["bindings"]))
        check("e. open_auto_count == 1", quest_auto.open_auto_count() == 1, str(quest_auto.open_auto_count()))
        check("e. 2 llm calls", len(llm_calls) == 2, str(llm_calls))

        # (f) Cap full + live_givers
        print("(f) cap full and live_givers")
        sub_before_f = len(fake_tq.submitted)
        res_f = quest_auto.tick()
        check("f. tick skipped cap", res_f == {"skipped": "cap"}, str(res_f))
        check("f. no new submit when capped", len(fake_tq.submitted) == sub_before_f)
        check("f. live_givers == {'Bram'}", quest_auto.live_givers() == {"Bram"}, str(quest_auto.live_givers()))

        # (g) Expiry frees the slot
        print("(g) expiry frees the slot")
        future_stamp = (game_time() + GameDuration.of(hours=1000)).canonical()
        expired_ids = quests.expire_runs(future_stamp)
        check("g. run expired", expired_ids == [run_e["id"]], str(expired_ids))
        check("g. run state failed", (quests.get_run(run_e["id"]) or {}).get("state") == "failed")
        check("g. open_auto_count == 0", quest_auto.open_auto_count() == 0, str(quest_auto.open_auto_count()))
        res_g = quest_auto.tick()
        check("g. tick no longer says cap", res_g.get("skipped") != "cap" and res_g.get("queued") == "t2", str(res_g))

        # (h) Refused template leaves nothing behind
        print("(h) refused template leaves nothing behind")
        tpl_count_h = len(quests.list_templates())
        run_count_h = len(quests.list_runs())
        fake_llm, _calls_h = _scripted_llm([
            "Draft prose.",
            _fence(_valid_obj("market")),
        ])
        refused_exc = quest_engine.QuestRefused([{"path": "x", "code": "refused", "message": "m"}])
        with (
            patch.object(llm_router, "llm_call", fake_llm),
            patch.object(quest_engine, "start_run", side_effect=refused_exc),
        ):
            res_h = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
        check("h. returns dropped with refused", res_h.get("dropped") == ["refused"], str(res_h))
        check("h. template count unchanged", len(quests.list_templates()) == tpl_count_h, str(quests.list_templates()))
        check("h. run count unchanged", len(quests.list_runs()) == run_count_h, str(quests.list_runs()))

        # (i) Generation failure (prose twice without fence)
        print("(i) generation failure")
        tpl_count_i = len(quests.list_templates())
        run_count_i = len(quests.list_runs())
        fake_llm, _calls_i = _scripted_llm([
            "Draft prose.",
            "Plain prose without fence.",
            "Still plain prose without fence.",
        ])
        with patch.object(llm_router, "llm_call", fake_llm):
            res_i = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
        check(
            "i. returns dropped with no_block",
            isinstance(res_i.get("dropped"), list) and "no_block" in res_i["dropped"],
            str(res_i),
        )
        check("i. no template stored", len(quests.list_templates()) == tpl_count_i)
        check("i. no run stored", len(quests.list_runs()) == run_count_i)

        # (j) Run-time re-checks (never invoke llm_call)
        print("(j) run-time re-checks")
        fake_llm_empty, recheck_calls = _scripted_llm([])
        with patch.object(llm_router, "llm_call", fake_llm_empty):
            # 1. giver asleep
            bram_prof = chars.get_character_profile("Bram")
            bram_prof["is_sleeping"] = True
            assert chars.save_character_profile("Bram", bram_prof)
            try:
                res_j_sleep = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
            finally:
                bram_prof = chars.get_character_profile("Bram")
                bram_prof["is_sleeping"] = False
                assert chars.save_character_profile("Bram", bram_prof)
            check("j1. giver asleep -> skipped", res_j_sleep == {"skipped": "giver asleep"}, str(res_j_sleep))

            # 2. giver moved to market -> apart
            bram_prof = chars.get_character_profile("Bram")
            bram_prof["current_location"] = "market"
            bram_prof["current_room"] = "square"
            assert chars.save_character_profile("Bram", bram_prof)
            try:
                res_j_apart = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
            finally:
                bram_prof = chars.get_character_profile("Bram")
                bram_prof["current_location"] = "inn"
                bram_prof["current_room"] = "hall"
                assert chars.save_character_profile("Bram", bram_prof)
            check("j2. giver moved -> skipped apart", res_j_apart == {"skipped": "apart"}, str(res_j_apart))

            # 3. world frozen
            world.set_world_frozen(True)
            try:
                res_j_frozen = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
            finally:
                world.set_world_frozen(False)
            check("j3. world frozen -> skipped", res_j_frozen == {"skipped": "world frozen"}, str(res_j_frozen))

            # 4. switch off
            cfg_overrides["quests.auto_enabled"] = False
            try:
                res_j_off = quest_auto._handle({"giver": "Bram", "avatar": "Ava"})
            finally:
                cfg_overrides["quests.auto_enabled"] = True
            check("j4. switch off -> skipped disabled", res_j_off == {"skipped": "disabled"}, str(res_j_off))

        check("j5. llm_call never invoked on skipped re-checks", recheck_calls == [], str(recheck_calls))

    # (k) Config schema & periodic_jobs table
    print("(k) config schema and periodic_jobs table")
    q_sec = SECTIONS.get("quests") or {}
    q_fields = q_sec.get("fields") or {}
    check("k. quests section scope world", q_sec.get("scope") == "world", str(q_sec.get("scope")))
    check("k. quests section world_group story", q_sec.get("world_group") == "story", str(q_sec.get("world_group")))
    check(
        "k. auto_enabled bool default False",
        (q_fields.get("auto_enabled") or {}).get("type") == "bool"
        and (q_fields.get("auto_enabled") or {}).get("default") is False,
        str(q_fields.get("auto_enabled")),
    )
    check(
        "k. max_open_auto_quests int default 2",
        (q_fields.get("max_open_auto_quests") or {}).get("type") == "int"
        and (q_fields.get("max_open_auto_quests") or {}).get("default") == 2,
        str(q_fields.get("max_open_auto_quests")),
    )
    check(
        "k. auto_expiry_game_hours int default 48",
        (q_fields.get("auto_expiry_game_hours") or {}).get("type") == "int"
        and (q_fields.get("auto_expiry_game_hours") or {}).get("default") == 48,
        str(q_fields.get("auto_expiry_game_hours")),
    )
    for fname in ("auto_enabled", "max_open_auto_quests", "auto_expiry_game_hours"):
        check(
            f"k. scope_of('quests.{fname}') == 'world'",
            config_scope.scope_of(f"quests.{fname}") == "world",
            str(config_scope.scope_of(f"quests.{fname}")),
        )
    auto_entries = [row for row in periodic_jobs._SUB_TASKS if len(row) >= 3 and row[2] == "auto_quests"]
    check(
        "k. periodic_jobs._SUB_TASKS has auto_quests @ 300s",
        len(auto_entries) == 1
        and auto_entries[0][0] is periodic_jobs._sub_auto_quests
        and auto_entries[0][1] == 300,
        str(auto_entries),
    )
    check("k. auto_quests is not detached", "auto_quests" not in periodic_jobs._DETACHED)

    print()
    if FAILURES:
        print(f"FAIL smoke_quest_auto: {len(FAILURES)}/{CHECKS} failed: {FAILURES}")
        return 1
    print(f"PASS smoke_quest_auto: {CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
