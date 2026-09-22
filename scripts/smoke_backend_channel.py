#!/usr/bin/env python3
"""Smoke run for the per-backend serialization of image generation (IMG-1):
``ImageService.run_on_backend_channel`` must put EVERY generation onto the
backend's own GPU queue channel, so two renders never run at the same time on
one backend — and must not serialize two DIFFERENT backends against each other.

No server, no network, no world DB: two real ``ProviderQueue`` channels are
built by hand around fake backends whose ``generate`` only records when it
entered and when it left.

Usage:  ./.venv/bin/python scripts/smoke_backend_channel.py

THE RULE (CLAUDE.md, feedback_queue_serialization)
---------------------------------------------------------------------------
"Never run two image generations in parallel on the same backend — serialize
on the GPU/backend channel. Each GPU is its own queue channel."

Until 2026-09-20 seven render paths only did that ``if api_type == "a1111"``
and called ``backend.generate()`` directly otherwise — and no configured world
has an a1111 backend, so the serialization never applied there.

Hand-derived expectations
---------------------------------------------------------------------------
Each fake render takes ``HOLD = 0.30 s`` and stamps ``time.monotonic()`` on
entry and exit.  A channel with ``max_concurrent = 1`` hands out one permit, so
for two submissions A and B on the SAME backend exactly one order is possible:

    A.enter < A.exit <= B.enter < B.exit      (or the same with A/B swapped)

  [1] two concurrent calls on ONE backend: the intervals do NOT overlap, and
      the wall time of the pair is >= 2 * HOLD = 0.60 s.
  [2] two concurrent calls on TWO backends: the intervals DO overlap (both
      threads start within the same barrier, each channel has its own permit),
      and the wall time of the pair is < 2 * HOLD.
  [3] the control: the same two threads calling ``backend.generate()``
      DIRECTLY — what every non-a1111 render path did until this fix — DO
      overlap and finish in ~HOLD. That is the old behaviour, measured, so
      [1] is not passing for want of parallelism in the harness.
  [4] the helper hands the worker's exception back TYPED — a
      ``BackendBusyError`` raised inside the callable arrives as
      ``BackendBusyError`` at the caller, not as a plain ``Exception``; that is
      what keeps "busy is not broken" alive across the queue boundary.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The storage root MUST be redirected BEFORE the first app import that can
# open a world DB: app.core.provider_queue reaches its world.db through paths,
# and without a storage root every world access raises StorageNotInitialised —
# there is no default world any more, so nothing here can land in the tracked
# worlds/demo (scripts/smoke_scripts_storage_lint.py enforces this).
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="backend-channel-storage-"))

from app.core import provider_manager as pm_mod  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.imagegen.base import BackendBusyError, ImageBackend  # noqa: E402
from app.imagegen.service import ImageService  # noqa: E402

HOLD = 0.30
FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


class _Fake(ImageBackend):
    """Records the interval of every generation it runs."""

    def __init__(self, name):
        super().__init__(name, "http://localhost", 0.0, "fake", "FAKE_")
        self._available = True
        self.instance_enabled = True
        self.spans = []
        self._span_lock = threading.Lock()

    def check_availability(self) -> bool:
        return True

    def _generate(self, prompt, negative_prompt, params):
        t0 = time.monotonic()
        time.sleep(HOLD)
        t1 = time.monotonic()
        with self._span_lock:
            self.spans.append((t0, t1))
        return [b"img"]


def _build_manager(names):
    """A real ProviderManager with one single-slot channel per backend name."""
    pm = pm_mod.ProviderManager()
    for n in names:
        provider = Provider(name=n, type="image", api_base="", api_key="",
                            max_concurrent=1, timeout=60)
        provider.available = True
        pq = ProviderQueue(provider, queue_name=f"backend:{n}",
                           max_concurrent=1, chat_pause_enabled=False)
        pm.channels[f"backend:{n}"] = pq
        pm._backend_providers[n] = provider
        pm._known_backend_names.add(n)
    return pm


def _run_pair(call_a, call_b):
    """Runs both callables in parallel threads, released by one barrier."""
    barrier = threading.Barrier(2)
    errors = []

    def _wrap(fn):
        def _run():
            barrier.wait()
            try:
                fn()
            except BaseException as e:      # noqa: BLE001
                errors.append(e)
        return _run

    threads = [threading.Thread(target=_wrap(call_a)),
               threading.Thread(target=_wrap(call_b))]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return time.monotonic() - t0, errors


def _overlap(span_a, span_b):
    """True when the two [enter, exit] intervals intersect."""
    return min(span_a[1], span_b[1]) > max(span_a[0], span_b[0])


_orig_get_pm = pm_mod.get_provider_manager

print("[1] two generations on ONE backend never overlap")
b1 = _Fake("B1")
_pm1 = _build_manager(["B1"])
pm_mod.get_provider_manager = lambda: _pm1
try:
    def _via_channel(b):
        return ImageService.run_on_backend_channel(
            b, lambda: b.generate("p", "", {}), task_type="smoke",
            agent_name="smoke")

    elapsed, errors = _run_pair(lambda: _via_channel(b1), lambda: _via_channel(b1))
finally:
    pm_mod.get_provider_manager = _orig_get_pm
check("1: no thread error", [type(e).__name__ for e in errors], [])
check("1: two renders ran", len(b1.spans), 2)
if len(b1.spans) == 2:
    check("1: intervals overlap", _overlap(*b1.spans), False)
check("1: pair took >= 2 * HOLD", elapsed >= 2 * HOLD, True)
print(f"     (wall time {elapsed:.2f}s, serialized minimum {2 * HOLD:.2f}s)")

print("[2] two generations on TWO backends do overlap")
b2, b3 = _Fake("B2"), _Fake("B3")
pm = _build_manager(["B2", "B3"])
pm_mod.get_provider_manager = lambda: pm
try:
    elapsed2, errors2 = _run_pair(lambda: _via_channel(b2), lambda: _via_channel(b3))
finally:
    pm_mod.get_provider_manager = _orig_get_pm
check("2: no thread error", [type(e).__name__ for e in errors2], [])
check("2: one render each", (len(b2.spans), len(b3.spans)), (1, 1))
if b2.spans and b3.spans:
    check("2: intervals overlap", _overlap(b2.spans[0], b3.spans[0]), True)
check("2: pair took < 2 * HOLD", elapsed2 < 2 * HOLD, True)
print(f"     (wall time {elapsed2:.2f}s)")

print("[3] DIRECT calls (the removed non-a1111 branch) DO collide")
b4 = _Fake("B4")
elapsed3, errors3 = _run_pair(lambda: b4.generate("p", "", {}),
                              lambda: b4.generate("p", "", {}))
check("3: no thread error", [type(e).__name__ for e in errors3], [])
if len(b4.spans) == 2:
    check("3: intervals overlap", _overlap(*b4.spans), True)
check("3: pair took < 2 * HOLD", elapsed3 < 2 * HOLD, True)

print("[4] the worker's exception type survives the channel")
b5 = _Fake("B5")
_pm5 = _build_manager(["B5"])
pm_mod.get_provider_manager = lambda: _pm5
try:
    def _busy():
        raise BackendBusyError("gpu is working")

    raised = None
    try:
        ImageService.run_on_backend_channel(b5, _busy, task_type="smoke")
    except BaseException as e:               # noqa: BLE001
        raised = e
finally:
    pm_mod.get_provider_manager = _orig_get_pm
check("4: exception type", type(raised).__name__, "BackendBusyError")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
sys.exit(0)
