#!/usr/bin/env python3
"""Respond-lane mechanics check (plan-parallel-bump-lane.md, Task 2).

Usage:
    ./.venv/bin/python scripts/test_respond_lane.py

Runs WITHOUT the server and without a world DB: the LLM turn
(_run_respond_turn) and the room resolution (_char_room_key) are stubbed on
the AgentLoop instance; the module-level gates (_is_paused,
_is_respond_eligible, _chat_llm_available, _get_max_parallel_responds) are
monkeypatched. What remains under test is the REAL dispatcher, queue and
lock logic of app/core/agent_loop.py.

Expected numbers, derived by hand from the design (not from output):

1. Capacity — 3 obligatory bumps in 3 distinct rooms, cap 2, each stub
   turn takes 0.4 s: all 3 must run, and the maximum number of turns
   observed running at the same instant must be exactly 2 (the third can
   only start after a slot frees up; with only a serial loop it would
   never exceed 1 — that is the regression this guards).

2. Same-room serialization — 2 bumps in the SAME room: their stub
   intervals must not overlap. 2 bumps in DIFFERENT rooms: they MUST
   overlap (both start within one dispatcher tick, both sleep 0.4 s).

3. Obligatory-first — an opportunity queued first, then an obligatory
   bump for another character: the obligatory one must START first
   (insert(0) beats append).

4. Merge rule — an obligatory payload followed by an opportunity bump for
   the SAME character keeps obligatory=True (never downgraded).

5. Re-queue while active — a second bump for a character whose turn is
   running is deferred, not dropped: the stub must run exactly twice.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import agent_loop as al  # noqa: E402

# Captured BEFORE make_loop() monkeypatches the module gates — scenario 6
# inspects the real implementation.
_REAL_CHAT_GATE = al._chat_llm_available

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_loop(room_map, cap=2, turn_seconds=0.4):
    """AgentLoop with stubbed turn + room resolution; returns (loop, runs).

    runs collects (name, start, end) per stub turn, monotonic seconds.
    """
    loop = al.AgentLoop()
    runs = []

    async def fake_turn(name, respond):
        start = time.monotonic()
        await asyncio.sleep(turn_seconds)
        runs.append((name, start, time.monotonic()))
        return {"preview": f"stub {name}", "tools": [], "intents": [],
                "rp_response": ""}

    loop._run_respond_turn = fake_turn
    loop._char_room_key = lambda name: room_map.get(name, "")
    al._is_paused = lambda: False
    al._is_respond_eligible = lambda name: True
    al._chat_llm_available = lambda: True
    al._get_max_parallel_responds = lambda: cap
    al._BOOT_GRACE_SECONDS = 0
    return loop, runs


async def drive(loop, until_runs, runs, timeout=10.0):
    """Run the dispatcher until `until_runs` stub turns finished."""
    task = asyncio.create_task(loop._respond_dispatcher())
    deadline = time.monotonic() + timeout
    try:
        while len(runs) < until_runs and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        for t in list(loop._respond_active.values()):
            t.cancel()
        await asyncio.gather(task, *loop._respond_active.values(),
                             return_exceptions=True)
    return len(runs) >= until_runs


def overlap(a, b):
    return a[1] < b[2] and b[1] < a[2]


async def scenario_capacity():
    print("Scenario 1: capacity cap 2, three rooms")
    loop, runs = make_loop({"A": "loc/r1", "B": "loc/r2", "C": "loc/r3"})
    for n in ("A", "B", "C"):
        loop.bump_respond(n, speaker="S", content="hi", obligatory=True)
    done = await drive(loop, 3, runs)
    check("all three turns ran", done and len(runs) == 3, f"ran={len(runs)}")
    # Max simultaneous turns from the recorded intervals.
    max_conc = max(sum(1 for r in runs if overlap(r, s)) for s in runs)
    check("max concurrency == 2", max_conc == 2, f"observed={max_conc}")


async def scenario_room_serial():
    print("Scenario 2: same room serial, different rooms parallel")
    loop, runs = make_loop({"A": "loc/r1", "B": "loc/r1"})
    loop.bump_respond("A", speaker="S", content="hi", obligatory=True)
    loop.bump_respond("B", speaker="S", content="hi", obligatory=True)
    await drive(loop, 2, runs)
    check("same room: no overlap", len(runs) == 2 and not overlap(runs[0], runs[1]))

    loop2, runs2 = make_loop({"A": "loc/r1", "B": "loc/r2"})
    loop2.bump_respond("A", speaker="S", content="hi", obligatory=True)
    loop2.bump_respond("B", speaker="S", content="hi", obligatory=True)
    await drive(loop2, 2, runs2)
    check("different rooms: overlap", len(runs2) == 2 and overlap(runs2[0], runs2[1]))


async def scenario_obligatory_first():
    print("Scenario 3: obligatory starts before earlier opportunity")
    loop, runs = make_loop({"A": "loc/r1", "B": "loc/r2"}, cap=1)
    loop.bump_respond("A", speaker="S", content="hi", obligatory=False)
    loop.bump_respond("B", speaker="S", content="hi", obligatory=True)
    check("queue order B,A", loop._respond_queue == ["B", "A"],
          str(loop._respond_queue))
    await drive(loop, 2, runs)
    starts = [r[0] for r in sorted(runs, key=lambda r: r[1])]
    check("B ran first", starts and starts[0] == "B", str(starts))


async def scenario_merge():
    print("Scenario 4: obligation never downgraded")
    loop, _ = make_loop({"A": "loc/r1"})
    loop.bump_respond("A", speaker="S", content="hi", obligatory=True)
    loop.bump_respond("A", speaker="T", content="later", obligatory=False)
    p = loop._respond_to.get("A") or {}
    check("payload stays obligatory", bool(p.get("obligatory")))
    check("payload speaker unchanged", p.get("speaker") == "S", str(p.get("speaker")))


async def scenario_requeue_active():
    print("Scenario 5: re-bump while running defers, then runs")
    loop, runs = make_loop({"A": "loc/r1"})
    loop.bump_respond("A", speaker="S", content="one", obligatory=True)
    task = asyncio.create_task(loop._respond_dispatcher())
    # Wait until the first turn is running, then re-bump.
    deadline = time.monotonic() + 5
    while "A" not in loop._respond_active and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    loop.bump_respond("A", speaker="S", content="two", obligatory=True)
    check("second bump queued while active", loop._respond_queue == ["A"])
    deadline = time.monotonic() + 10
    while len(runs) < 2 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, *loop._respond_active.values(),
                         return_exceptions=True)
    check("stub ran exactly twice", len(runs) == 2, f"ran={len(runs)}")
    check("runs did not overlap", len(runs) == 2 and not overlap(runs[0], runs[1]))


def scenario_llm_gate_task_id():
    """The dispatcher's LLM gate must probe a task id that EXISTS in
    llm_tasks.TASK_TYPES — an unknown id has no routing chain, resolves to
    None forever and silently parks the whole lane (2026-07-30 regression:
    the probe said "chat", the real route is "chat_stream"). The stubbed
    scenarios above cannot catch this, so check the source directly."""
    print("Scenario 6: LLM gate probes a registered task id")
    import inspect
    import re
    from app.core.llm_tasks import TASK_TYPES
    src = inspect.getsource(_REAL_CHAT_GATE)
    probed = re.findall(r'resolve_llm\("([^"]+)"\)', src)
    check("gate calls resolve_llm with a literal task id", bool(probed), src)
    for task in probed:
        check(f"task id {task!r} is registered", task in TASK_TYPES)


async def main():
    await scenario_capacity()
    await scenario_room_serial()
    await scenario_obligatory_first()
    await scenario_merge()
    await scenario_requeue_active()
    scenario_llm_gate_task_id()
    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} check(s): {FAILED}")
        return 1
    print("All respond-lane checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
