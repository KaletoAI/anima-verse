#!/usr/bin/env python3
"""Checks that one gateway outage leaves ONE cooldown line and no stray traceback.

Usage:
    ./.venv/bin/python scripts/smoke_model_cooldown_log.py

Runs without the server, without a world DB and without any real provider: the
queue is faked, the failure is a hand-built exception carrying the gateway's
own 503 text.

WHY these expectations (derived by hand from the defect, not recorded from
current output):

The log of 2026-09-11 showed 22 lines "Model LLM-Gateway/<model> in cooldown
for 300s" for 11 incidents, plus 11 full tracebacks on ERROR — while the router
fell back to the next model and every one of those calls succeeded. Two causes:

  * The cooldown is set TWICE per incident. The queue worker sets it when the
    task fails (it also covers submitters that never go through llm_call), and
    llm_router.llm_call sets it again on the re-raised exception (it also
    covers the streaming path's chain). Both setters stay — only the second
    one must stop shouting. `mark_model_unhealthy` / `Provider.mark_unhealthy`
    therefore log WARNING only when no cooldown is running, and DEBUG while one
    is (the deadline is still pushed out).
  * The worker logged EVERY failed LLM task with `exc_info=True`. Whether the
    failure is final is known to the CALLER, not to the worker — so llm_call
    submits inside `caller_handles_failure()`, the worker keeps a recoverable
    upstream failure at WARNING without a traceback, and llm_call itself logs
    the ERROR with the traceback once its fallback chain is exhausted.

Expected counts, derived from that rule:

 [1] `mark_model_unhealthy("P","helper")` twice in a row = ONE incident =
     1 WARNING + 1 DEBUG. After the deadline passed it is a NEW incident, so
     the next call is a WARNING again (2 WARNINGs for two outages, not 4).
 [2] `Provider.mark_unhealthy` behaves the same and still extends the deadline
     on the repeat (second deadline > first).
 [3] A task whose caller retries it (flag set) failing with the gateway's
     503 "No healthy backend" → 1 WARNING, no traceback attached.
 [4] The same flag with an HTTP 400 → nobody retries a payload error
     (llm_call re-raises it at once), so it stays ERROR + traceback.
 [5] No flag (a direct queue submitter, e.g. a background job) → ERROR +
     traceback, exactly as before.
 [6] One full incident with a working fallback: attempt 1 fails with the 503,
     attempt 2 answers. Expected over the three loggers: exactly 1 cooldown
     line at WARNING, exactly 0 records at ERROR, and llm_call returns the
     answer. Before the fix: 2 cooldown lines + 1 ERROR traceback.
 [7] The same incident without a working fallback (three providers, all dead):
     3 cooldown lines (three distinct (provider, model) outages, one line each)
     and exactly 1 ERROR — llm_call's own, WITH the traceback, because this
     failure really is final.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inspect  # noqa: E402

from app.core import llm_router as lr  # noqa: E402
from app.core import provider_queue as pq  # noqa: E402
from app.core.llm_queue import LLMTask  # noqa: E402
from app.core.provider import Provider  # noqa: E402

failures = []

# The gateway's own wording for "this model has no servable backend" — the
# exact class of error that produced the 22 duplicated lines.
NO_BACKEND = "LLM Queue task failed: Error code: 503 - No healthy backend for model 'helper'"
PAYLOAD_ERROR = "Error code: 400 - Bad Request: messages[1] has no content"


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


class CountingHandler(logging.Handler):
    """Keeps every record so a check can count by level and ask for exc_info."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()

    def by_level(self, level):
        return [r for r in self.records if r.levelno == level]

    def messages(self, level):
        return [r.getMessage() for r in self.by_level(level)]


handler = CountingHandler()
for _name in ("llm_router", "provider_queue", "provider"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.DEBUG)      # so the DEBUG repeat is visible, not just gone
    _lg.propagate = False            # keep the smoke's own output readable
    _lg.addHandler(handler)


def cooldown_lines(level):
    """Only the setters' own line ("… in cooldown for 300s …"). llm_call's
    one-line announcement that it falls back is a different message and stays."""
    return [m for m in handler.messages(level) if "in cooldown for" in m]


print("1) the model cooldown warns once per outage")
lr._MODEL_COOLDOWN.clear()
handler.clear()
lr.mark_model_unhealthy("P", "helper")
lr.mark_model_unhealthy("P", "helper")
check("first call warns, second stays DEBUG", len(cooldown_lines(logging.WARNING)), 1)
check("the repeat is logged at DEBUG", len(cooldown_lines(logging.DEBUG)), 1)
check("the pair is cooling", lr._model_cooled_down("P", "helper"), True)

lr._MODEL_COOLDOWN[("P", "helper")] = time.monotonic() - 1  # outage window over
handler.clear()
lr.mark_model_unhealthy("P", "helper")
check("a new outage warns again", len(cooldown_lines(logging.WARNING)), 1)

print("2) the provider cooldown warns once per outage and still extends it")
prov = Provider(name="P", type="openai", api_base="http://127.0.0.1:1/v1", api_key="")
handler.clear()
prov.mark_unhealthy("upstream-fail: boom", 300.0)
first_deadline = prov._cooldown_until
prov.mark_unhealthy("upstream-fail: boom again", 300.0)
check("one warning for the outage", len(cooldown_lines(logging.WARNING)), 1)
check("the repeat is logged at DEBUG", len(cooldown_lines(logging.DEBUG)), 1)
check("the deadline was pushed out", prov._cooldown_until > first_deadline, True)
check("the provider is unavailable", prov.available, False)

print("3) the worker log level follows who reports the failure")


def failing_task(handled: bool) -> LLMTask:
    task = LLMTask(task_id="llm_test", task_type="tools", priority=20,
                   agent_name="Demo", created_at="")
    task._caller_handles_failure = handled
    return task


handler.clear()
pq.log_task_failure("P", failing_task(True), Exception(NO_BACKEND))
check("recoverable failure: 1 WARNING", len(handler.by_level(logging.WARNING)), 1)
check("recoverable failure: no ERROR", len(handler.by_level(logging.ERROR)), 0)
check("recoverable failure: no traceback",
      handler.by_level(logging.WARNING)[0].exc_info, None)

handler.clear()
pq.log_task_failure("P", failing_task(True), RuntimeError(PAYLOAD_ERROR))
check("payload error: 1 ERROR", len(handler.by_level(logging.ERROR)), 1)
check("payload error: keeps the traceback",
      handler.by_level(logging.ERROR)[0].exc_info is not None, True)

handler.clear()
pq.log_task_failure("P", failing_task(False), Exception(NO_BACKEND))
check("nobody retries it: 1 ERROR", len(handler.by_level(logging.ERROR)), 1)
check("nobody retries it: keeps the traceback",
      handler.by_level(logging.ERROR)[0].exc_info is not None, True)

check("submit() stamps the owner onto the task",
      "_caller_handles_failure" in inspect.getsource(pq.ProviderQueue.submit), True)


print("4) a whole incident through llm_call")


class _FakeLLM:
    model = "helper"


class _FakeInstance:
    def __init__(self, provider_name, model):
        self.provider_name = provider_name
        self.model = model

    def create_llm(self, max_tokens=None):
        return _FakeLLM()


class _FakeAnswer:
    content = "ok"


class _FakeQueue:
    """Stands in for the provider queue: runs the worker's failure handling
    (the real functions) and re-raises the way ProviderQueue.submit does."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
        self.owner_seen = []

    def submit(self, task_type, priority, llm, messages_or_prompt,
               agent_name="", label=""):
        self.calls += 1
        # Same stamping as ProviderQueue.submit — read in the CALLER's context.
        task = LLMTask(task_id=f"llm_fake{self.calls}", task_type=task_type,
                       priority=priority, agent_name=agent_name, created_at="")
        task._caller_handles_failure = pq._caller_handles_failure.get()
        self.owner_seen.append(task._caller_handles_failure)
        if self.calls > self.fail_times:
            return _FakeAnswer()
        err = Exception(NO_BACKEND)
        pq.log_task_failure("P", task, err)
        pq.cooldown_after_failure(providers[self.calls - 1], "helper", task_type, err)
        raise Exception(f"LLM Queue task failed: {err}")


providers = [Provider(name=f"P{i}", type="openai",
                      api_base="http://127.0.0.1:1/v1", api_key="")
             for i in range(3)]
instances = [_FakeInstance(p.name, "helper") for p in providers]

orig_resolve, orig_queue = lr.resolve_llm, lr.get_llm_queue
try:
    fake_q = _FakeQueue(fail_times=1)
    seq = iter(instances)
    lr.resolve_llm = lambda task, agent_name="": next(seq, None)
    lr.get_llm_queue = lambda: fake_q
    lr._MODEL_COOLDOWN.clear()
    handler.clear()
    answer = lr.llm_call("tools", "sys", "user", priority=20)
    check("the fallback answered", getattr(answer, "content", None), "ok")
    check("llm_call declared itself the owner", fake_q.owner_seen, [True, True])
    check("exactly one cooldown line", len(cooldown_lines(logging.WARNING)), 1)
    check("the caught failure leaves no ERROR", len(handler.by_level(logging.ERROR)), 0)

    fake_q = _FakeQueue(fail_times=3)
    seq = iter(instances)
    lr.resolve_llm = lambda task, agent_name="": next(seq, None)
    lr.get_llm_queue = lambda: fake_q
    lr._MODEL_COOLDOWN.clear()
    handler.clear()
    raised = ""
    try:
        lr.llm_call("tools", "sys", "user", priority=20)
    except RuntimeError as e:
        raised = str(e)
    check("llm_call gives up", raised.startswith("llm_call: every provider"), True)
    check("one cooldown line per dead model", len(cooldown_lines(logging.WARNING)), 3)
    check("the final failure is one ERROR", len(handler.by_level(logging.ERROR)), 1)
    check("the final ERROR carries the traceback",
          handler.by_level(logging.ERROR)[0].exc_info is not None, True)
finally:
    lr.resolve_llm, lr.get_llm_queue = orig_resolve, orig_queue
    lr._MODEL_COOLDOWN.clear()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("All checks passed.")
sys.exit(0)
