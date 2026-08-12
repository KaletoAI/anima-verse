#!/usr/bin/env python3
"""Smoke: a config reload must not hand a busy backend a second free slot.

Usage:  ./.venv/bin/python scripts/smoke_channel_reload.py

Background (incident 2026-08-03): an admin save rebuilt the backend channels
while a mesh job was running on ``backend:Trellis2-Object-High``. The rebuilt
ProviderQueue was a NEW object whose Semaphore(1) had its permit free, so the
next task started immediately — two jobs at once on a ``concurrent=1``
backend, both ending in 600-s ComfyUI timeouts. The rule the code must keep:

  ONE channel key == ONE queue object == ONE set of concurrency permits,
  for as long as that channel exists.

Expectations are derived by hand from that rule, not from recorded output:

  [1] reload keeps the SAME queue object per surviving channel key
      -> the running task keeps holding its permit
  [2] a permit held before the reload is STILL held after it
      (Semaphore(1): acquire() succeeded once -> a second acquire fails)
  [3] raising max_concurrent 1 -> 3 releases exactly 2 extra permits
      (3 acquires succeed, the 4th does not)
  [4] lowering 3 -> 1 with one slot held by a running task takes the 2 free
      slots at once, and the running task's slot is NOT handed on when it
      finishes (the shrink lands deterministically, no reaper race)
  [5] a channel key that disappears while BUSY is remembered and re-adopted
      (same object) when it comes back; an IDLE one is forgotten
  [6] settings themselves are applied (serialize_group, chat pause, gate)
"""
import os
import sys
import threading


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.provider_manager import ProviderManager  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.core.provider import Provider  # noqa: E402

FAILED = 0


def check(label: str, got, want) -> None:
    global FAILED
    if got == want:
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}\n      got:  {got!r}\n      want: {want!r}")


def _provider(name: str, concurrent: int = 1) -> Provider:
    p = Provider(name=name, type="openai_mesh", api_base="http://x",
                 api_key="", max_concurrent=concurrent, timeout=None)
    p.available = True
    return p


def _env_backend(idx: int, name: str, concurrent: int = 1) -> None:
    os.environ[f"SKILL_IMAGEGEN_{idx}_NAME"] = name
    os.environ[f"SKILL_IMAGEGEN_{idx}_ENABLED"] = "true"
    os.environ[f"SKILL_IMAGEGEN_{idx}_API_TYPE"] = "openai_mesh"
    os.environ[f"SKILL_IMAGEGEN_{idx}_API_URL"] = "http://192.0.2.1:4000"
    os.environ[f"SKILL_IMAGEGEN_{idx}_MAX_CONCURRENT"] = str(concurrent)


def _clear_env() -> None:
    for key in [k for k in os.environ
                if k.startswith(("SKILL_IMAGEGEN_", "PROVIDER_"))]:
        os.environ.pop(key, None)


print("[1+2] a running task keeps its slot across a reload")
_clear_env()
_env_backend(1, "MeshA", concurrent=1)
mgr = ProviderManager()
mgr.load_providers()
q_before = mgr.channels["backend:MeshA"]
# The running task's permit — exactly what a mesh job holds while it works.
check("the fresh channel has its single permit free",
      q_before._semaphore.acquire(blocking=False), True)

mgr.load_providers()  # <- the admin save
q_after = mgr.channels["backend:MeshA"]
check("reload keeps the same queue object", q_after is q_before, True)
check("the held permit is still held after the reload "
      "(no second job may start)",
      q_after._semaphore.acquire(blocking=False), False)
q_after._semaphore.release()
check("after the task finishes the slot is free again",
      q_after._semaphore.acquire(blocking=False), True)
q_after._semaphore.release()

print("[3] raising the limit adds exactly the delta")
_clear_env()
_env_backend(1, "MeshA", concurrent=1)
mgr = ProviderManager()
mgr.load_providers()
q = mgr.channels["backend:MeshA"]
_env_backend(1, "MeshA", concurrent=3)
mgr.load_providers()
check("same object after the limit change",
      mgr.channels["backend:MeshA"] is q, True)
check("max_concurrent applied", q._max_concurrent, 3)
acquired = sum(1 for _ in range(4) if q._semaphore.acquire(blocking=False))
check("3 of 4 acquires succeed", acquired, 3)
for _ in range(acquired):
    q._semaphore.release()

print("[4] lowering the limit with a task running")
_clear_env()
_env_backend(1, "MeshA", concurrent=3)
mgr = ProviderManager()
mgr.load_providers()
q = mgr.channels["backend:MeshA"]
check("one permit taken by the running task",
      q._semaphore.acquire(blocking=False), True)
_env_backend(1, "MeshA", concurrent=1)
mgr.load_providers()
check("the two free slots are gone at once",
      q._semaphore.acquire(blocking=False), False)
q._semaphore.release()          # the running task finishes
check("the freed slot is the ONE the new limit allows",
      q._semaphore.acquire(blocking=False), True)
check("and no second one on top of it",
      q._semaphore.acquire(blocking=False), False)
q._semaphore.release()

print("[5] a channel that disappears")
_clear_env()
_env_backend(1, "MeshBusy", concurrent=1)
_env_backend(2, "MeshIdle", concurrent=1)
mgr = ProviderManager()
mgr.load_providers()
busy = mgr.channels["backend:MeshBusy"]
idle = mgr.channels["backend:MeshIdle"]
# MeshBusy has a task running (what is_busy reports to the manager)
busy._current_tasks.append(object())
_clear_env()
mgr.load_providers()
check("both channels are gone from the routing table",
      [k for k in mgr.channels if k.startswith("backend:")], [])
check("the busy queue is remembered", "backend:MeshBusy" in mgr._queues, True)
check("the idle queue is forgotten", "backend:MeshIdle" in mgr._queues, False)
_env_backend(1, "MeshBusy", concurrent=1)
_env_backend(2, "MeshIdle", concurrent=1)
mgr.load_providers()
check("the busy one is re-adopted (same object)",
      mgr.channels["backend:MeshBusy"] is busy, True)
check("the idle one is rebuilt (new object)",
      mgr.channels["backend:MeshIdle"] is idle, False)
busy._current_tasks.clear()

print("[6] settings are applied on adoption")
q = ProviderQueue(_provider("P", 1), queue_name="P", max_concurrent=1,
                  chat_pause_enabled=False, serialize_group="")
gate = threading.Semaphore(1)
q.reconfigure(_provider("P", 2), max_concurrent=2, chat_pause_enabled=True,
              serialize_group="gpu0", reserve_chat_slot=True,
              serialize_gate=gate)
check("serialize_group applied", q.serialize_group, "gpu0")
check("chat pause applied", q._chat_pause_enabled, True)
check("reserve_chat_slot applied", q.reserve_chat_slot, True)
check("serialize gate applied", q._serialize_gate is gate, True)
check("limit applied", q._max_concurrent, 2)

_clear_env()
print()
if FAILED:
    print(f"{FAILED} check(s) FAILED")
    sys.exit(1)
print("all channel-reload checks passed")
