#!/usr/bin/env python3
"""Reserved-chat-slot check for ProviderQueue (plan-parallel-bump-lane.md, Task 4).

Usage:
    ./.venv/bin/python scripts/test_reserved_chat_slot.py

Runs WITHOUT the server: the provider is a SimpleNamespace and every task is
a submit_gpu_task stub callable (goes through the same _worker_loop and the
same reservation gate as LLM submits — the gate keys on task.priority only).
Under test is the REAL worker/semaphore/reservation logic of
app/core/provider_queue.py.

Expected outcomes, derived by hand from the design:

1. N=2, reservation ON, two background tasks (Priority.NORMAL, 0.5 s each):
   background may hold at most N-1 = 1 slot, so the two tasks must NOT
   overlap. A chat task (Priority.CHAT) submitted while background #1 is
   running must START before background #1 ends (it takes the reserved
   slot instead of waiting) — without the reservation it would queue
   behind the running pair.

2. N=2, reservation OFF: the same two background tasks MUST overlap
   (both slots usable — proves the cap comes from the reservation, not
   from the worker count).

3. N=1, reservation ON: ineffective by design — a single background task
   still runs (the only slot is not withheld from background).

4. N=2, reservation ON, two chat tasks: both run in parallel — chat is
   never capped by the background counter, only by the semaphore.
"""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm_queue import Priority  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_queue(n: int, reserve: bool) -> ProviderQueue:
    provider = SimpleNamespace(name="test", type="openai", available=True,
                               max_concurrent=n, timeout=30)
    return ProviderQueue(provider, queue_name="test", max_concurrent=n,
                         chat_pause_enabled=False, serialize_group="",
                         reserve_chat_slot=reserve)


def run_task(pq: ProviderQueue, name: str, priority: int, runs: list,
             seconds: float = 0.5) -> threading.Thread:
    """submit_gpu_task in its own thread (submit blocks until done)."""
    def _callable():
        start = time.monotonic()
        time.sleep(seconds)
        runs.append((name, start, time.monotonic()))
        return name

    t = threading.Thread(
        target=lambda: pq.submit_gpu_task(name, priority, _callable),
        daemon=True)
    t.start()
    return t


def overlap(a, b):
    return a[1] < b[2] and b[1] < a[2]


def by_name(runs, name):
    return next(r for r in runs if r[0] == name)


def scenario_reserved():
    print("Scenario 1: N=2 reserved — bg serialized, chat starts immediately")
    pq = make_queue(2, reserve=True)
    runs = []
    threads = [run_task(pq, "bg1", Priority.NORMAL, runs),
               run_task(pq, "bg2", Priority.NORMAL, runs)]
    time.sleep(0.15)  # bg1 should be running now, bg2 capped
    threads.append(run_task(pq, "chat", Priority.CHAT, runs, seconds=0.2))
    for t in threads:
        t.join(timeout=10)
    check("all three tasks ran", len(runs) == 3, f"ran={len(runs)}")
    if len(runs) == 3:
        bg1, bg2 = by_name(runs, "bg1"), by_name(runs, "bg2")
        chat = by_name(runs, "chat")
        first_bg, second_bg = sorted([bg1, bg2], key=lambda r: r[1])
        check("background never parallel", not overlap(bg1, bg2))
        check("chat started before running bg ended",
              chat[1] < first_bg[2],
              f"chat_start={chat[1]:.2f} bg_end={first_bg[2]:.2f}")
        check("chat overlapped a bg task", overlap(chat, first_bg) or overlap(chat, second_bg))


def scenario_unreserved():
    print("Scenario 2: N=2 unreserved — bg uses both slots")
    pq = make_queue(2, reserve=False)
    runs = []
    threads = [run_task(pq, "bg1", Priority.NORMAL, runs),
               run_task(pq, "bg2", Priority.NORMAL, runs)]
    for t in threads:
        t.join(timeout=10)
    check("both ran", len(runs) == 2, f"ran={len(runs)}")
    check("background overlapped", len(runs) == 2 and overlap(runs[0], runs[1]))


def scenario_single_slot():
    print("Scenario 3: N=1 reserved — reservation ineffective, bg still runs")
    pq = make_queue(1, reserve=True)
    runs = []
    t = run_task(pq, "bg1", Priority.NORMAL, runs, seconds=0.2)
    t.join(timeout=10)
    check("bg ran with a single slot", len(runs) == 1, f"ran={len(runs)}")


def scenario_chat_uncapped():
    print("Scenario 4: N=2 reserved — two chats run in parallel")
    pq = make_queue(2, reserve=True)
    runs = []
    threads = [run_task(pq, "chat1", Priority.CHAT, runs),
               run_task(pq, "chat2", Priority.CHAT, runs)]
    for t in threads:
        t.join(timeout=10)
    check("both chats ran", len(runs) == 2, f"ran={len(runs)}")
    check("chats overlapped", len(runs) == 2 and overlap(runs[0], runs[1]))


def main() -> int:
    scenario_reserved()
    scenario_unreserved()
    scenario_single_slot()
    scenario_chat_uncapped()
    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} check(s): {FAILED}")
        return 1
    print("All reserved-chat-slot checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
