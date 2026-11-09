#!/usr/bin/env python3
"""Smoke: a model-test request shares the provider's whole-key parallel cap
with play traffic (model_suitability.provider_slot).

Usage: ./.venv/bin/python scripts/smoke_model_test_provider_slot.py

No server, no network, no world DB (storage and instance point at temp dirs).
Provider "Key1" has max_parallel_llm = 1, provider "Free" has none; every
pool has one lane. Expectations, derived from the rule "busy lanes of every
pool of a provider count against its cap" (llm_lanes._provider_room):

[1] Play holds a lane on Key1/chat-model. A test request for Key1/other-model
    (a DIFFERENT pool, same key) must not start: after 1.5 s it is still
    waiting. Once play releases, it starts (within 3 s).
[2] While the test holds its slot, play's pool on the same key has
    free_lanes == 0 (room = cap 1 - busy 1), so play waits for the test too.
[3] The slot is released after the request: free_lanes back to 1.
[4] A request that is cancelled while waiting raises _QuotaWaitCancelled and
    never starts.
[5] Provider "Free" (no cap) is not touched: the request starts at once and
    no Free pool appears in the manager.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths
paths.init(tempfile.mkdtemp(prefix="smoke_slot_world_"))
paths.init_instance(tempfile.mkdtemp(prefix="smoke_slot_instance_"))

from app.core import llm_lanes
from app.core.llm_queue import Priority
from app.core import model_suitability as ms

CAPS = {"Key1": 1}
llm_lanes.configured_provider_cap = lambda name: CAPS.get(name, 0)
manager = llm_lanes.LaneManager(lane_count=lambda key: 1, provider_cap=lambda name: CAPS.get(name, 0))
llm_lanes._manager = manager


class Inst:
    def __init__(self, provider, model):
        self.provider_name, self.model = provider, model


def run_request(inst, cancel=None):
    """Start a test request in a thread; returns (started event, done event, errors)."""
    started, done, errors = threading.Event(), threading.Event(), []

    def body():
        try:
            with ms.provider_slot(inst, cancel):
                started.set()
                done.wait(10)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return started, done, errors, thread


play = manager.acquire_lane("Key1/chat-model", "chat:Ada", Priority.CHAT)
started, done, errors, thread = run_request(Inst("Key1", "other-model"))
time.sleep(1.5)
assert not started.is_set(), "[1] test request started while play held the key's only slot"
play.release()
assert started.wait(3), "[1] test request did not start after play released"
print("[1] the test waits for play on the same key — PASS")

assert manager.free_lanes("Key1/chat-model", "chat:Ada", Priority.CHAT) == 0, "[2]"
print("[2] play's pool has no room while the test holds the slot — PASS")
done.set()
thread.join(3)
assert manager.free_lanes("Key1/chat-model", "chat:Ada", Priority.CHAT) == 1, "[3]"
print("[3] the slot is released after the request — PASS")

play = manager.acquire_lane("Key1/chat-model", "chat:Ada", Priority.CHAT)
cancel = threading.Event()
started, done, errors, thread = run_request(Inst("Key1", "other-model"), cancel)
time.sleep(0.3)
cancel.set()
thread.join(4)
assert not started.is_set() and len(errors) == 1 and isinstance(errors[0], ms._QuotaWaitCancelled), errors
play.release()
print("[4] a cancelled wait raises _QuotaWaitCancelled — PASS")

started, done, errors, thread = run_request(Inst("Free", "any-model"))
assert started.wait(0.5), "[5] uncapped provider waited"
assert not any(key.startswith("Free/") for key in manager.snapshot()["pools"]), "[5] pool created"
done.set()
thread.join(3)
print("[5] a provider without a cap is not touched — PASS")
print("ALL OK")
