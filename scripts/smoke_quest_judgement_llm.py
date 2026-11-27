#!/usr/bin/env python3
"""Smoke: real LLM judge for `llm_judgement` quest condition (quest stage 3, Task 2).

Throwaway storage (`paths.init(<tmpdir>)` BEFORE importing any world-DB module),
no server, no real LLM. `app.core.llm_router.llm_call` is monkeypatched with a
stub returning an object with `.content`.

Usage:
    ./.venv/bin/python scripts/smoke_quest_judgement_llm.py

FIXTURE
    Location "inn" with room "hall" (entry).
    Characters:
      - Ava: player-controlled avatar (user "demo", active_character "Ava") in inn/hall.
      - NPC_A: NPC in inn/hall.

WHAT FOLLOWS BY HAND
  (a) Fenced ```json:verdict {"passed": true, "reason": "asked politely"}```:
      - `llm_judge` returns `(True, "asked politely")`.
      - Through `handle(payload)` on a real open run with transcript lines ->
        returns `{"status": "yes"}` and row state in `quest_judgements` is `"yes"`,
        reason `"asked politely"`.
  (b) Bare JSON object without fence `{"passed": false, "reason": "x"}`:
      - `parse_verdict` and `llm_judge` return `(False, "x")`.
  (c) Prose answer `"I think yes."`:
      - `parse_verdict` raises `ValueError`.
      - Through `handle(payload)` -> returns `{"status": "error"}`, row state is
        `"error"`, and `judged_through` remains unchanged (previous value).
  (d) Stub raises `RefusalError`:
      - Through `handle(payload)` -> returns `{"status": "error"}`, row state is
        `"error"`.
  (e) `"passed": "yes"` (string instead of boolean):
      - `parse_verdict` raises `ValueError`.
  (f) Stub call arguments:
      - `task == "quest_judgement"`.
      - Rendered user prompt contains the criterion and the formatted transcript
        line `"Ava -> NPC_A: Could you please help me?"`.
  (g) Config settings:
      - With `quests.judgement_min_interval_s = 90`, `min_interval_s() == 90`.
      - Missing / None -> `min_interval_s() == 30`.
  (h) Routing & catalog metadata:
      - `fallback_parent("quest_judgement") == "intent"`.
      - `TASK_TYPES["quest_judgement"]["cache_class"] == "bg"`.
"""
from __future__ import annotations

from datetime import timedelta
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_raises(label, exc_type, fn):
    try:
        res = fn()
    except exc_type:
        print(f"  ok   {label}: raised {exc_type.__name__}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {label}: raised {type(e).__name__} ({e}) -- expected {exc_type.__name__}")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: returned {res!r} -- expected {exc_type.__name__}")
    FAILURES.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-judgement-llm-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import config, db, llm_router, quest_engine, quest_judgement, quest_types
    from app.core.llm_refusal import RefusalError
    from app.core.llm_tasks import TASK_TYPES
    from app.core.perception import VOLUME_NORMAL, record_utterance
    from app.core.timeutils import parse_iso
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
    for name in ("Ava", "NPC_A"):
        assert chars.save_character_profile(
            name, {"current_location": "inn", "current_room": "hall"},
            create_new=True,
        ), name
    uid = create_user("demo", "smoke-password", allowed_characters=["Ava"])
    update_user(uid, settings={"active_character": "Ava"})

    sample_lines = [
        {"id": 1, "speaker": "Ava", "addressees": ["NPC_A"],
         "content": "Could you please help me?", "game_ts": "Y0001-D001T10:00:00"},
    ]

    # (a) & (f) Fenced json:verdict + call argument capture + handle() on real open run
    print("(a)/(f) fenced verdict, call args & handle() end-to-end")
    recorded = []

    def stub_yes(task, system_prompt, user_prompt, **kwargs):
        recorded.append({"task": task, "system": system_prompt, "user": user_prompt, "kwargs": kwargs})
        return SimpleNamespace(
            content='```json:verdict\n{"passed": true, "reason": "asked politely"}\n```'
        )

    with patch.object(llm_router, "llm_call", side_effect=stub_yes):
        res_a = quest_judgement.llm_judge("Ask NPC_A politely for help", sample_lines, "Ava")
    check("llm_judge fenced verdict", res_a, (True, "asked politely"))
    check("recorded task == quest_judgement", recorded[0]["task"], "quest_judgement")
    check("user prompt contains criterion",
          "Ask NPC_A politely for help" in recorded[0]["user"], True)
    check("user prompt contains formatted transcript line",
          "Ava -> NPC_A: Could you please help me?" in recorded[0]["user"], True)

    t1 = quests.create_template(
        title="Polite request",
        steps=[{"id": "s1", "text": "Ask nicely.", "condition": {
            "type": "llm_judgement", "params": {"criterion": "Ask NPC_A politely for help"}}}],
        state="ready",
    )
    r1 = quests.create_run(template=t1, bindings={}, state="open")
    after_ts = (parse_iso(r1["step_started_at"]) + timedelta(seconds=1)).isoformat(timespec="seconds")
    record_utterance(
        speaker="Ava", content="Could you please help me?",
        volume=VOLUME_NORMAL, addressees=["NPC_A"],
        location_id="inn", room_id="hall", source="play", ts=after_ts,
    )
    newest_id = perception_store.newest_perception_id("Ava")
    ckey = quest_judgement.criterion_key("Ask NPC_A politely for help")
    payload = {
        "run_id": r1["id"],
        "step": 0,
        "criterion_key": ckey,
        "criterion": "Ask NPC_A politely for help",
        "mind": "Ava",
        "avatar": "Ava",
        "since": r1["step_started_at"],
        "through_id": newest_id,
    }
    with patch.object(llm_router, "llm_call", side_effect=stub_yes):
        h_yes = quest_judgement.handle(payload)
    check("handle fenced verdict returns yes", h_yes, {"status": "yes"})
    row_yes = quests.get_judgement(r1["id"], 0, ckey, "Ava")
    check("row state is yes with reason",
          (row_yes["state"], row_yes["reason"]) if row_yes else None,
          ("yes", "asked politely"))

    # (b) Bare JSON object without fence
    print("(b) bare JSON object without fence")
    check("parse_verdict bare JSON",
          quest_judgement.parse_verdict('{"passed": false, "reason": "x"}'),
          (False, "x"))
    with patch.object(
        llm_router, "llm_call",
        return_value=SimpleNamespace(content='{"passed": false, "reason": "x"}'),
    ):
        check("llm_judge bare JSON",
              quest_judgement.llm_judge("crit", sample_lines, "Ava"),
              (False, "x"))

    # (c) Prose answer -> ValueError, through handle -> state error & judged_through unchanged
    print("(c) prose answer -> ValueError / handle error preserves judged_through")
    check_raises("parse_verdict prose raises ValueError", ValueError,
                 lambda: quest_judgement.parse_verdict("I think yes."))
    r2 = quests.create_run(template=t1, bindings={}, state="open")
    after_ts2 = (parse_iso(r2["step_started_at"]) + timedelta(seconds=1)).isoformat(timespec="seconds")
    record_utterance(
        speaker="Ava", content="Hello there.",
        volume=VOLUME_NORMAL, addressees=["NPC_A"],
        location_id="inn", room_id="hall", source="play", ts=after_ts2,
    )
    newest_id2 = perception_store.newest_perception_id("Ava")
    prev_through = max(0, newest_id2 - 1)
    quests.set_judgement(r2["id"], 0, ckey, "Ava", state="no", reason="earlier", judged_through=prev_through)
    payload2 = {
        "run_id": r2["id"],
        "step": 0,
        "criterion_key": ckey,
        "criterion": "Ask NPC_A politely for help",
        "mind": "Ava",
        "avatar": "Ava",
        "since": r2["step_started_at"],
        "through_id": newest_id2,
    }
    with patch.object(
        llm_router, "llm_call",
        return_value=SimpleNamespace(content="I think yes."),
    ):
        h_prose = quest_judgement.handle(payload2)
    check("handle prose returns error", h_prose, {"status": "error"})
    row_prose = quests.get_judgement(r2["id"], 0, ckey, "Ava")
    check("prose error preserves judged_through",
          (row_prose["state"], row_prose["judged_through"]) if row_prose else None,
          ("error", prev_through))

    # (d) RefusalError -> handle returns state error
    print("(d) RefusalError -> handle state error")
    def stub_refusal(*args, **kwargs):
        raise RefusalError("prov", "mod", "quest_judgement", "I cannot comply")

    with patch.object(llm_router, "llm_call", side_effect=stub_refusal):
        h_ref = quest_judgement.handle(payload2)
    check("handle RefusalError returns error", h_ref, {"status": "error"})
    row_ref = quests.get_judgement(r2["id"], 0, ckey, "Ava")
    check("RefusalError row state is error",
          row_ref["state"] if row_ref else None, "error")

    # (e) String "passed": "yes" -> ValueError
    print("(e) string passed -> ValueError")
    check_raises("parse_verdict string passed raises ValueError", ValueError,
                 lambda: quest_judgement.parse_verdict('{"passed": "yes", "reason": "nope"}'))

    # (g) Config: quests.judgement_min_interval_s
    print("(g) config quests.judgement_min_interval_s")
    with patch.object(config, "get", side_effect=lambda k, d=None: 90 if k == "quests.judgement_min_interval_s" else d):
        check("min_interval_s() == 90 from config", quest_judgement.min_interval_s(), 90.0)
    with patch.object(config, "get", side_effect=lambda k, d=None: d):
        check("min_interval_s() == 30 when missing", quest_judgement.min_interval_s(), 30)

    # (h) fallback_parent and cache_class
    print("(h) fallback_parent & cache_class")
    check("fallback_parent('quest_judgement') == 'intent'",
          llm_router.fallback_parent("quest_judgement"), "intent")
    check("TASK_TYPES['quest_judgement']['cache_class'] == 'bg'",
          TASK_TYPES["quest_judgement"].get("cache_class"), "bg")

    if FAILURES:
        print(f"FAIL smoke_quest_judgement_llm: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_judgement_llm: (a)-(h)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
