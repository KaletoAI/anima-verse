#!/usr/bin/env python3
"""Smoke: decision point thought_skip in AgentLoop._run_turn
(development_instructions/plan-decision-models.md § 4.1, § 9).

Usage:  ./.venv/bin/python scripts/smoke_decision_thought_skip.py

The turn runs for real down to the thought runner; everything around it is
stubbed at module level (context build, template render, runner, decide), so
no LLM, no network. Storage is a throwaway dir initialised first.

EXPECTATIONS, DERIVED BY HAND
S  thought_state: header lines always kept; with recent_thoughts (20 lines)
   and recent_chat_block (200 numbered lines, ~6 kB) the budget 2500 is hit ->
   recent_thoughts is cut first (whole block gone), then the chat block from
   the FRONT -> "chat 199" (newest) present, "chat 000" gone, len <= 2500,
   "Character: Kira" present.
1  decide -> Decision(turn = idle, conf .93): runner NOT called, outcome
   "decision_skip", mark_taken called once, char counts as a real turn
   (_last_real_turn_at set).
2  decide -> None, runner returns skipped=True: outcome "ok_skip",
   record_outcome(turn="idle").
3  decide -> None, runner returns a normal turn: outcome "ok",
   record_outcome(turn="act").
4  inbox_block non-empty: decide NOT called, runner called, no outcome recorded.
5  a bump hint pending: decide NOT called.
6  decide -> Decision(turn = act): runner called, outcome "ok",
   record_outcome(turn="act").
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_thought_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))
from app.core.db import init_schema  # noqa: E402
init_schema()

import app.core.agent_loop as al  # noqa: E402
import app.core.thought_context as tc  # noqa: E402
import app.core.prompt_templates as pt  # noqa: E402
import app.core.thoughts as th  # noqa: E402
import app.core.agent_inbox as ib  # noqa: E402
import app.core.stat_effects as se  # noqa: E402
import app.models.rules as rules  # noqa: E402
from app.core import decision, decision_points  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


print("=== S thought_state ===")
ctx = {"character_name": "Kira", "location_name": "Inn", "activity": "sitting", "feeling": "calm",
       "time_of_day": "14:00", "game_date": "Summer, day 3",
       "recent_thoughts": "\n".join(f"thought {i:02d} " + "x" * 40 for i in range(20)),
       "recent_chat_block": "\n".join(f"chat {i:03d} " + "y" * 20 for i in range(200)),
       "present_people_block": "Tom is here.", "elsewhere_block": "", "daily_schedule_block": ""}
s = decision_points.thought_state(ctx)["situation"]
check("S len <= 2500", len(s) <= decision_points.THOUGHT_STATE_MAX_CHARS, True)
check("S newest chat kept", "chat 199" in s, True)
check("S oldest chat cut", "chat 000" in s, False)
check("S thoughts cut first", "thought 19" in s, False)
check("S header kept", "Character: Kira" in s, True)

# ── stubs ────────────────────────────────────────────────────────────────
CTX = {}
RUNNER_CALLS, DECIDE_CALLS, OUTCOMES, TAKEN = [], [], [], []
RUNNER_RESULT = {}
DECIDE_RESULT = [None]

tc.build_thought_context = lambda name: dict(CTX)
pt.render = lambda name, **kw: "system"
ib.mark_thought_processed = lambda name: None
se.maybe_activity_tick = lambda name: None
rules.check_discover_rules = lambda name: None
al._minutes_since_last_chat_with_avatar = lambda name: None


class Runner:
    async def run_thought_turn(self, name, **kw):
        RUNNER_CALLS.append(name)
        return dict(RUNNER_RESULT)


th.get_thought_runner = lambda: Runner()


def fake_decide(point, state, questions, *, key=None, then=None):
    DECIDE_CALLS.append((point, key))
    return DECIDE_RESULT[0]


decision.decide = fake_decide
decision.record_outcome = lambda point, key, actual: OUTCOMES.append(actual)
decision.mark_taken = lambda point, key: TAKEN.append(key)


def answer(value, conf):
    return decision.Decision(answers={"turn": decision.Answer(value, None, conf, {})})


def run(inbox="", hint="", decided=None, result=None):
    CTX.clear()
    CTX.update(ctx, inbox_block=inbox)
    DECIDE_RESULT[0] = decided
    RUNNER_RESULT.clear()
    RUNNER_RESULT.update(result or {"preview": "x", "tools": ["t"], "intents": []})
    for lst in (RUNNER_CALLS, DECIDE_CALLS, OUTCOMES, TAKEN):
        lst.clear()
    loop = al.AgentLoop()
    loop._maybe_active_conversation_chime = lambda name: None
    loop._maybe_auto_sleep = lambda name: None
    if hint:
        loop._bump_hints["Kira"] = hint
    asyncio.run(loop._run_turn("Kira"))
    return loop, loop._recent[-1]["outcome"]


print("=== 1 decision idle ===")
loop, out = run(decided=answer("idle", 0.93))
check("1 runner not called", RUNNER_CALLS, [])
check("1 outcome", out, "decision_skip")
check("1 mark_taken once", len(TAKEN), 1)
check("1 real turn", "Kira" in loop._last_real_turn_at, True)

print("=== 2 LLM SKIP ===")
_, out = run(result={"preview": "SKIP", "tools": [], "intents": [], "skipped": True})
check("2 outcome", out, "ok_skip")
check("2 recorded idle", OUTCOMES, [{"turn": "idle"}])

print("=== 3 normal turn ===")
_, out = run()
check("3 outcome", out, "ok")
check("3 recorded act", OUTCOMES, [{"turn": "act"}])

print("=== 4 inbox ===")
_, out = run(inbox="Tom: are you there?")
check("4 decide not called", DECIDE_CALLS, [])
check("4 runner called", RUNNER_CALLS, ["Kira"])
check("4 nothing recorded", OUTCOMES, [])

print("=== 5 hint ===")
run(hint="scheduled message")
check("5 decide not called", DECIDE_CALLS, [])

print("=== 6 decision act ===")
_, out = run(decided=answer("act", 0.95))
check("6 runner called", RUNNER_CALLS, ["Kira"])
check("6 outcome", out, "ok")
check("6 recorded act", OUTCOMES, [{"turn": "act"}])

print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
