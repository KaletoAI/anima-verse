#!/usr/bin/env python3
"""Smoke: cached-verdict `llm_judgement` quest condition (quest stage 3, Task 1).

Throwaway storage (`paths.init(<tmpdir>)` BEFORE importing any world-DB module),
no server, no real LLM. `quest_judgement.get_task_queue` is monkeypatched with a
fake queue recording submits; `judge_fn` stubs are injected into `handle(...)`.

Usage:
    ./.venv/bin/python scripts/smoke_quest_judgement.py

FIXTURE
    Location "inn" with room "hall" (entry).
    Characters:
      - Ava: player-controlled avatar (user "demo", active_character "Ava") in inn/hall.
      - NPC_A, NPC_B: NPCs in inn/hall.

WHAT FOLLOWS BY HAND
  [1] CLAIM GATES & RATE CAP (on open run R1, step 0, criterion "Greet someone"):
      - First `request(ctx, crit)` claims the row (state 'pending', attempts 1, task_id set)
        and submits exactly 1 job to the fake queue.
      - Second `request(ctx, crit)` immediately -> row is 'pending' and fresh -> 0 new submits.
      - `set_judgement(..., state='no', reason='Not yet', judged_through=newest_id)`:
        * With no new perception lines (`newest_id == judged_through`), even after
          `MIN_INTERVAL_S + 5` seconds -> `claim_judgement` returns False, 0 new submits.
        * After a new perception line (`newest_id > judged_through`), within `MIN_INTERVAL_S`
          (at +5 s) -> `claim_judgement` returns False, 0 new submits.
        * With new perception line AND interval passed (`MIN_INTERVAL_S + 5` s, clock patched)
          -> `request` claims (attempts 2) and submits 1 new job.
      - Stale pending row: after `PENDING_STALE_S + 5` s (clock patched), `request` re-claims
        the pending row (attempts 3) and submits 1 new job.
      - Per-minute cap: clearing the rate-limit deque, then calling `request` on
        `MAX_PER_MINUTE + 1` (= 7) distinct open runs submits exactly `MAX_PER_MINUTE` (= 6)
        jobs; the 7th run is NOT claimed (no row in `quest_judgements`).

  [2] STALE STEP & CLEANUP ON STEP ADVANCE (2-step open run R2):
      - Claim + `set_judgement` on step 0 -> True, row exists.
      - `record_step_done(R2, 0, avatar="Ava", mind="Ava")` advances to step 1 and deletes
        `quest_judgements` rows with `step <= 0` -> `get_judgement(R2, 0, ...)` is None.
      - `set_judgement(R2, 0, ...)` for the old step 0 -> returns False, nothing written.
      - Evaluating `_llm_judgement` on step 1 sees no 'yes' verdict (returns `(True, False)`).

  [3] SUBJECTIVE STREAM (`get_character_stream_since`):
      - NPC_A whispers to NPC_B in inn/hall ("secret whisper"): Ava receives a contentless
        `whisper_meta` row -> MUST NOT appear in `get_character_stream_since("Ava", ...)`.
      - NPC_A says a normal line in inn/hall ("hello room"): appears in Ava's stream with
        speaker "NPC_A" and content "hello room".
      - Ava says a normal line in inn/hall ("hi back"): appears in Ava's stream with
        speaker "Ava" and content "hi back".
      - A `display_only` line in inn/hall ("+5 friendship"): MUST NOT appear in Ava's stream.

  [4] END-TO-END & ERROR & DELETE:
      - Ready 1-step template with `llm_judgement` ("Ava greeted the room"), started as open
        run R3.
      - Ava speaks in inn/hall -> `utterance.heard` -> `_heard` evaluates Ava with
        `utterance.spoken` -> `_llm_judgement` sees no cached 'yes', calls `request`, submits
        1 job with payload for R3.
      - `quest_judgement.handle(payload, judge_fn=raising)` -> returns `{"status": "error"}`,
        row state is `'error'`, run R3 stays `'open'`.
      - `quest_judgement.handle(payload, judge_fn=lambda c, t, a: (True, "ok"))` -> returns
        `{"status": "yes"}`, notifies `quest.judged`, `quest_engine.drain()` -> R3 advances
        to `state == "done"` and `step_log[0]["avatar"] == "Ava"`.
      - `on_character_deleted("Ava")` deletes remaining judgement rows for mind `"Ava"`.
"""
from __future__ import annotations

from datetime import timedelta
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []
SECTION = [""]


def check(label, actual, expected):
    label = f"{SECTION[0]} {label}".strip()
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class _FakeQueue:
    def __init__(self):
        self.submits = []
        self._seq = 0

    def submit(self, task_type, payload, queue_name="", priority=20,
               agent_name="", max_retries=-1, deduplicate=False,
               character_hold=False):
        self._seq += 1
        tid = f"fake_task_{self._seq}"
        self.submits.append({
            "task_id": tid,
            "task_type": task_type,
            "payload": dict(payload),
            "queue_name": queue_name,
            "priority": priority,
            "agent_name": agent_name,
            "max_retries": max_retries,
            "deduplicate": deduplicate,
        })
        return tid


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-judgement-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import db, quest_catalog, quest_engine, quest_judgement, quest_types
    from app.core.perception import VOLUME_NORMAL, VOLUME_WHISPER, record_utterance
    from app.core.timeutils import parse_iso, utc_now_iso
    from app.core.users import create_user, update_user
    from app.models import character as chars, perception_store, quests, world

    db.init_schema()
    quest_types.register()
    quest_engine.register()
    quest_engine._reset_for_tests()

    world.upsert_location(
        {"id": "inn", "name": "Inn", "entry_room": "hall",
         "rooms": [{"id": "hall", "name": "Hall"}]},
        sync_world=False,
    )
    for name in ("Ava", "NPC_A", "NPC_B"):
        assert chars.save_character_profile(
            name, {"current_location": "inn", "current_room": "hall"},
            create_new=True,
        ), name
    uid = create_user("demo", "smoke-password", allowed_characters=["Ava"])
    update_user(uid, settings={"active_character": "Ava"})

    fake_q = _FakeQueue()

    def _reset_rate():
        with quest_judgement._rate_lock:
            quest_judgement._recent_submits.clear()

    with patch.object(quest_judgement, "get_task_queue", return_value=fake_q):
        # ── [1] Claim gates & rate cap ──────────────────────────────────────
        SECTION[0] = "[1]"
        print("[1] claim gates & rate cap")
        _reset_rate()
        t1 = quests.create_template(
            title="Gate test",
            steps=[{"id": "s1", "text": "Greet.", "condition": {
                "type": "llm_judgement", "params": {"criterion": "Greet someone"}}}],
            state="ready",
        )
        r1 = quests.create_run(template=t1, bindings={}, state="open")
        ctx1 = quest_types.build_context("Ava", r1)
        crit = "Greet someone"
        ckey = quest_judgement.criterion_key(crit)

        t0 = parse_iso(utc_now_iso(timespec="microseconds"))
        t0_iso = t0.isoformat(timespec="microseconds")

        with patch.object(quest_judgement, "utc_now_iso", return_value=t0_iso):
            quest_judgement.request(ctx1, crit)
        check("first request submits once", len(fake_q.submits), 1)
        row = quests.get_judgement(r1["id"], 0, ckey, "Ava")
        check("row is pending, attempts 1, task_id set",
              row is not None and row["state"] == "pending" and row["attempts"] == 1
              and row["task_id"] == "fake_task_1", True)

        with patch.object(quest_judgement, "utc_now_iso", return_value=t0_iso):
            quest_judgement.request(ctx1, crit)
        check("second immediate request does nothing", len(fake_q.submits), 1)

        newest0 = perception_store.newest_perception_id("Ava")
        check("set_judgement('no') succeeds",
              quests.set_judgement(r1["id"], 0, ckey, "Ava", state="no",
                                   reason="Not yet", judged_through=newest0), True)

        t_later_iso = (t0 + timedelta(seconds=quest_judgement.MIN_INTERVAL_S + 5)).isoformat(timespec="microseconds")
        with patch.object(quest_judgement, "utc_now_iso", return_value=t_later_iso):
            quest_judgement.request(ctx1, crit)
        check("no new perception lines -> no submit even after interval", len(fake_q.submits), 1)

        # Record a new utterance so newest_perception_id increases
        record_utterance(speaker="NPC_A", content="Good evening.", volume=VOLUME_NORMAL,
                         location_id="inn", room_id="hall", source="loop")
        newest1 = perception_store.newest_perception_id("Ava")
        check("newest_perception_id grew", newest1 > newest0, True)

        t_soon_iso = (t0 + timedelta(seconds=5)).isoformat(timespec="microseconds")
        with patch.object(quest_judgement, "utc_now_iso", return_value=t_soon_iso):
            quest_judgement.request(ctx1, crit)
        check("new lines within MIN_INTERVAL_S -> no submit", len(fake_q.submits), 1)

        with patch.object(quest_judgement, "utc_now_iso", return_value=t_later_iso):
            quest_judgement.request(ctx1, crit)
        check("new lines + interval passed -> submits", len(fake_q.submits), 2)
        row2 = quests.get_judgement(r1["id"], 0, ckey, "Ava")
        check("attempts incremented to 2", row2 is not None and row2["attempts"] == 2, True)

        # Stale pending row older than PENDING_STALE_S -> re-claimed
        t_stale_iso = (t0 + timedelta(
            seconds=quest_judgement.MIN_INTERVAL_S + 5 + quest_judgement.PENDING_STALE_S + 5
        )).isoformat(timespec="microseconds")
        with patch.object(quest_judgement, "utc_now_iso", return_value=t_stale_iso):
            quest_judgement.request(ctx1, crit)
        check("stale pending row re-claimed", len(fake_q.submits), 3)
        row3 = quests.get_judgement(r1["id"], 0, ckey, "Ava")
        check("attempts incremented to 3", row3 is not None and row3["attempts"] == 3, True)

        # Per-minute cap: MAX_PER_MINUTE + 1 distinct runs -> exactly MAX_PER_MINUTE submits
        _reset_rate()
        fake_q.submits.clear()
        cap_runs = [quests.create_run(template=t1, bindings={}, state="open")
                    for _ in range(quest_judgement.MAX_PER_MINUTE + 1)]
        for cr in cap_runs:
            quest_judgement.request(quest_types.build_context("Ava", cr), crit)
        check("per-minute cap allows exactly MAX_PER_MINUTE submits",
              len(fake_q.submits), quest_judgement.MAX_PER_MINUTE)
        check("overflow run was not claimed",
              quests.get_judgement(cap_runs[-1]["id"], 0, ckey, "Ava"), None)

        # ── [2] Stale step & cleanup on record_step_done ────────────────────
        SECTION[0] = "[2]"
        print("[2] stale step & cleanup on record_step_done")
        _reset_rate()
        fake_q.submits.clear()
        t2 = quests.create_template(
            title="Two-step",
            steps=[
                {"id": "s1", "text": "Step 1.", "condition": {
                    "type": "llm_judgement", "params": {"criterion": "Step one"}}},
                {"id": "s2", "text": "Step 2.", "condition": {
                    "type": "llm_judgement", "params": {"criterion": "Step two"}}},
            ],
            state="ready",
        )
        r2 = quests.create_run(template=t2, bindings={}, state="open")
        k1 = quest_judgement.criterion_key("Step one")
        check("set_judgement on step 0 -> True",
              quests.set_judgement(r2["id"], 0, k1, "Ava", state="yes",
                                   reason="done", judged_through=newest1), True)
        check("row exists before step advance",
              quests.get_judgement(r2["id"], 0, k1, "Ava") is not None, True)
        r2_adv = quests.record_step_done(r2["id"], 0, avatar="Ava", mind="Ava")
        check("record_step_done advanced to step 1",
              r2_adv is not None and r2_adv["current_step"] == 1, True)
        check("record_step_done deleted step 0 judgement",
              quests.get_judgement(r2["id"], 0, k1, "Ava"), None)
        check("set_judgement for old step 0 returns False",
              quests.set_judgement(r2["id"], 0, k1, "Ava", state="yes",
                                   reason="late", judged_through=newest1), False)
        check("old step 0 still absent",
              quests.get_judgement(r2["id"], 0, k1, "Ava"), None)
        ctx2_s1 = quest_types.build_context("Ava", r2_adv)
        res_s1 = quest_catalog.evaluate_expression(
            {"type": "llm_judgement", "params": {"criterion": "Step two"}}, ctx2_s1)
        check("evaluator on step 1 does not pass", (res_s1.available, res_s1.passed), (True, False))

        # ── [3] Subjective stream ───────────────────────────────────────────
        SECTION[0] = "[3]"
        print("[3] subjective stream")
        since_marker = utc_now_iso(timespec="microseconds")
        after_before = perception_store.newest_perception_id("Ava")
        record_utterance(speaker="NPC_A", content="secret whisper", volume=VOLUME_WHISPER,
                         addressees=["NPC_B"], location_id="inn", room_id="hall", source="loop")
        record_utterance(speaker="NPC_A", content="hello room", volume=VOLUME_NORMAL,
                         location_id="inn", room_id="hall", source="loop")
        record_utterance(speaker="Ava", content="hi back", volume=VOLUME_NORMAL,
                         location_id="inn", room_id="hall", source="play")
        record_utterance(speaker="NPC_A", content="+5 friendship", volume=VOLUME_NORMAL,
                         location_id="inn", room_id="hall", source="system",
                         perception_meta={"display_only": True})
        stream = perception_store.get_character_stream_since(
            "Ava", since_ts=since_marker, after_id=after_before, limit=40)
        contents = [line["content"] for line in stream]
        speakers = [line["speaker"] for line in stream]
        check("whisper content absent", "secret whisper" not in contents, True)
        check("display_only line absent", "+5 friendship" not in contents, True)
        check("normal + avatar lines present in order", contents, ["hello room", "hi back"])
        check("speakers match", speakers, ["NPC_A", "Ava"])

        # ── [4] End-to-end, judge error & on_character_deleted ──────────────
        SECTION[0] = "[4]"
        print("[4] end-to-end, error & delete")
        # Cancel earlier open runs so they do not interfere with the e2e submits
        for r in [r1, r2, *cap_runs]:
            quests.set_run_state(r["id"], "cancelled")
        quest_engine._refresh_live()
        _reset_rate()
        fake_q.submits.clear()

        t3 = quests.create_template(
            title="Speak up",
            steps=[{"id": "s1", "text": "Greet the room.", "condition": {
                "type": "llm_judgement", "params": {"criterion": "Ava greeted the room"}}}],
            state="ready",
        )
        r3 = quest_engine.start_run(t3["id"], {})
        quest_engine.drain()
        check("r3 starts open", r3["state"], "open")

        record_utterance(speaker="Ava", content="Hello everyone in the hall!",
                         volume=VOLUME_NORMAL, location_id="inn", room_id="hall", source="play")
        check("engine drained after avatar spoke", quest_engine.drain(), True)
        check("utterance.spoken triggered one judgement submit", len(fake_q.submits), 1)
        payload = fake_q.submits[0]["payload"]
        check("payload targets r3", (payload["run_id"], payload["step"], payload["avatar"]),
              (r3["id"], 0, "Ava"))

        def _raising_judge(c, tr, av):
            raise RuntimeError("judge boom")

        err_res = quest_judgement.handle(payload, judge_fn=_raising_judge)
        check("raising judge -> status error", err_res, {"status": "error"})
        err_row = quests.get_judgement(r3["id"], 0, payload["criterion_key"], "Ava")
        check("row stored as error", err_row is not None and err_row["state"] == "error", True)
        quest_engine.drain()
        check("run stays open after error verdict", quests.get_run(r3["id"])["state"], "open")

        ok_res = quest_judgement.handle(payload, judge_fn=lambda c, tr, av: (True, "ok"))
        check("passing judge -> status yes", ok_res, {"status": "yes"})
        check("engine drained after quest.judged", quest_engine.drain(), True)
        r3_done = quests.get_run(r3["id"])
        check("run is now done", r3_done["state"], "done")
        check("step_log recorded Ava",
              len(r3_done["step_log"]) == 1 and r3_done["step_log"][0]["avatar"] == "Ava", True)

        # on_character_deleted deletes judgements for that mind
        r4 = quests.create_run(template=t3, bindings={}, state="open")
        k4 = quest_judgement.criterion_key("Ava greeted the room")
        quests.set_judgement(r4["id"], 0, k4, "Ava", state="no", reason="x", judged_through=1)
        check("judgement exists before delete",
              quests.get_judgement(r4["id"], 0, k4, "Ava") is not None, True)
        quest_engine.on_character_deleted("Ava")
        check("on_character_deleted removed Ava's judgements",
              quests.get_judgement(r4["id"], 0, k4, "Ava"), None)

    if FAILURES:
        print(f"FAIL smoke_quest_judgement: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_judgement: [1]-[4]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
