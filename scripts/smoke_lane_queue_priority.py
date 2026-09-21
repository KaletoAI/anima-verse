#!/usr/bin/env python3
"""Smoke run: a QUEUED call takes its lane with the priority of its PROMPT
class, and a lane count that did not change wakes nobody.

Usage:
    ./.venv/bin/python scripts/smoke_lane_queue_priority.py

Runs WITHOUT the server, without a world DB and without a network: the
storage root is a temp dir, the lane manager is a private instance with a
stepped clock and hand-set rules, and ``ProviderQueue._acquire_lane`` is
driven directly — it reads nothing from its queue but ``self.provider.name``.

The findings under test (review 2026-09-20, logic_llm.md)
---------------------------------------------------------------------------
LLM-6  The queue path passed ``task.priority`` — the QUEUE priority — to
       ``acquire_lane``, while the streaming path derives the lane priority
       from the prompt class (``lane_priority_for``). The rp_first tool
       decision is submitted as ``task_type="intent"`` with
       ``Priority.CHAT`` (chat_engine._run_tool_phase), so in the lanes it
       ranked as a live conversation: past R3's affinity wait, past R4's
       conversation hold and past an R7 reservation made for a waiting
       reply. Exactly the displacement the rules exist to prevent.
LLM-7  ``sync_from_config`` -> ``reconfigure`` called ``notify_all()`` on the
       ONE process-wide condition on EVERY lane attempt. The queue path calls
       it before every single attempt and re-queues every 0.15 s, so a full
       pool produced hundreds of thundering herds per second over ALL pools.

Expected values, derived by hand from the catalog and plan-cache-lanes.md §4
---------------------------------------------------------------------------
* ``task_class_for("intent")`` is ``tool`` (app/core/llm_tasks.py), and
  ``lane_priority_for`` maps everything that is neither ``chat`` nor
  ``thought`` to NORMAL. So a queued ``intent`` task must end up with
  ``_lane_priority == Priority.NORMAL`` (20) even though its queue priority
  is ``Priority.CHAT`` (0) — and ``task.priority`` itself must be untouched,
  because that is what pauses the queue and what the panel shows.
* ``task_type="chat_stream"`` is class ``chat`` -> CHAT (0): a reply keeps
  its precedence (commit e6e0ea5d). ``task_type="thought"`` -> LOW (30).
* R7: with a reservation held for a CHAT reply on the pool, a freed lane may
  not go to a waiter of a LOWER class. A queued ``intent`` task must
  therefore NOT get the only lane of the pool while the claim stands — with
  the old CHAT value it walked straight through. The reply itself (same
  class as the claim) does get it.
* R3: the affinity wait applies below the chat class. On a pool whose one
  lane is free but FOREIGN (another key on it) and with the affinity wait set
  far into the future, a queued ``intent`` task must come away empty-handed
  and a queued ``chat_stream`` task must get the lane at once.
* LLM-7: ``sync_from_config`` on a pool whose configured lane count has not
  changed must call ``notify_all`` ZERO times. The first call creates the
  pool (also zero — there is nobody to wake). Changing the count to 2 and
  syncing again must notify exactly once, and syncing twice more after that
  zero times.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_lane_prio_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)

from app.core import llm_lanes  # noqa: E402
from app.core.llm_lanes import (LaneManager, LaneRules,  # noqa: E402
                                cache_key_for, lane_priority_for)
from app.core.llm_queue import LLMTask, Priority  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


class _Clock:
    """A stepped clock — nothing here waits for real time."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _FakeQueue:
    """Everything ``_acquire_lane`` reads from its queue object."""

    class _Prov:
        name = "P"

    provider = _Prov()

    _acquire_lane = ProviderQueue._acquire_lane


def _task(task_type: str, agent: str, priority: int) -> LLMTask:
    return LLMTask(task_id=f"t_{task_type}_{agent}", task_type=task_type,
                   priority=int(priority), agent_name=agent,
                   created_at=utc_now_iso(), provider_name="P", model="m")


def _install(manager: LaneManager) -> None:
    llm_lanes._manager = manager


def part_derivation() -> None:
    print("\nLLM-6 a) the lane priority is derived, the queue priority is kept")
    clock = _Clock()
    mgr = LaneManager(now=clock, lane_count=lambda _k: 4,
                      rules=lambda: LaneRules(affinity_wait=0.0,
                                              conversation_hold=0.0,
                                              wait_upgrade=0.0))
    _install(mgr)
    q = _FakeQueue()

    expect = {"intent": int(Priority.NORMAL),
              "chat_stream": int(Priority.CHAT),
              "thought": int(Priority.LOW)}
    for task_type, want in expect.items():
        t = _task(task_type, "Kira", Priority.CHAT)
        got_handle = q._acquire_lane(t)
        check(f"{task_type}: lane priority {t._lane_priority} == {want}",
              got_handle and t._lane_priority == want,
              f"got {t._lane_priority}")
        check(f"{task_type}: queue priority untouched (CHAT)",
              t.priority == int(Priority.CHAT), str(t.priority))
        check(f"{task_type}: matches lane_priority_for()",
              t._lane_priority == lane_priority_for(task_type),
              f"{t._lane_priority} vs {lane_priority_for(task_type)}")
        if t._lane_handle:
            t._lane_handle.release()


def part_reservation() -> None:
    print("\nLLM-6 b) R7 — a reservation for a reply holds the tool call off")
    clock = _Clock()
    mgr = LaneManager(now=clock, lane_count=lambda _k: 1,
                      rules=lambda: LaneRules(affinity_wait=0.0,
                                              conversation_hold=0.0,
                                              wait_upgrade=0.0))
    _install(mgr)
    q = _FakeQueue()
    pool = "P/m"
    # A claim is never made on a pool the manager does not know yet (that is
    # documented behaviour of `reserve`), so the pool is brought into being
    # first — with its one lane still fresh and unused.
    mgr.reconfigure(pool, 1)

    # A reply is queued for this pool: the dispatcher claims it.
    mgr.reserve(pool, cache_key_for("chat_stream", "Vallerie"),
                priority=int(Priority.CHAT), ttl=600.0, holder="respond")

    tool = _task("intent", "Kira", Priority.CHAT)
    check("the queued tool decision does NOT take the reserved lane",
          q._acquire_lane(tool) is False and tool._lane_handle is None,
          f"handle={tool._lane_handle}")

    reply = _task("chat_stream", "Vallerie", Priority.CHAT)
    check("the reply the claim was made for does take it",
          q._acquire_lane(reply) is True and reply._lane_handle is not None)
    if reply._lane_handle:
        reply._lane_handle.release()

    # Claim consumed -> the tool decision is served on the next attempt.
    check("with the claim gone the tool decision is served",
          q._acquire_lane(tool) is True)
    if tool._lane_handle:
        tool._lane_handle.release()


def part_affinity() -> None:
    print("\nLLM-6 c) R3 — the affinity wait applies to the queued tool call")
    clock = _Clock()
    rules = {"wait": 1000.0}
    mgr = LaneManager(now=clock, lane_count=lambda _k: 1,
                      rules=lambda: LaneRules(affinity_wait=rules["wait"],
                                              conversation_hold=0.0,
                                              wait_upgrade=0.0))
    _install(mgr)
    q = _FakeQueue()

    # Make the single lane USED and FOREIGN: another key was on it and left.
    foreign = _task("image_prompt", "Bo", Priority.NORMAL)
    q._acquire_lane(foreign)
    foreign._lane_handle.release()

    tool = _task("intent", "Kira", Priority.CHAT)
    check("below the chat class the foreign lane is not taken at once",
          q._acquire_lane(tool) is False, f"handle={tool._lane_handle}")

    reply = _task("chat_stream", "Kira", Priority.CHAT)
    check("the chat class is exempt from R3 and takes it",
          q._acquire_lane(reply) is True)
    if reply._lane_handle:
        reply._lane_handle.release()

    rules["wait"] = 0.0
    check("with the wait over, the tool call is served too",
          q._acquire_lane(tool) is True)
    if tool._lane_handle:
        tool._lane_handle.release()


def part_notify() -> None:
    print("\nLLM-7 — an unchanged lane count wakes nobody")
    clock = _Clock()
    count = {"n": 1}
    mgr = LaneManager(now=clock, lane_count=lambda _k: count["n"],
                      rules=lambda: LaneRules(affinity_wait=0.0,
                                              conversation_hold=0.0,
                                              wait_upgrade=0.0))
    calls = {"n": 0}
    real_notify = mgr._cond.notify_all

    def counting_notify(*a, **kw):
        calls["n"] += 1
        return real_notify(*a, **kw)

    mgr._cond.notify_all = counting_notify  # type: ignore[method-assign]

    mgr.sync_from_config("P/m")
    first = calls["n"]
    check("creating the pool wakes nobody", first == 0, str(first))

    for _ in range(50):
        mgr.sync_from_config("P/m")
    check("50 further syncs with an unchanged count: 0 notify_all",
          calls["n"] == first, str(calls["n"] - first))

    count["n"] = 2
    mgr.sync_from_config("P/m")
    check("raising the count to 2 notifies exactly once",
          calls["n"] == first + 1, str(calls["n"] - first))

    before = calls["n"]
    mgr.sync_from_config("P/m")
    mgr.sync_from_config("P/m")
    check("and the two syncs after that notify nobody again",
          calls["n"] == before, str(calls["n"] - before))


def main() -> int:
    print("smoke_lane_queue_priority")
    try:
        part_derivation()
        part_reservation()
        part_affinity()
        part_notify()
    finally:
        llm_lanes._manager = None
        shutil.rmtree(_TMP, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
