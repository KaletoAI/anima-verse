#!/usr/bin/env python3
"""Smoke run for the error classification of ``BackendPool.run_on_backend`` —
that a payload error keeps a healthy backend in the pool and only a real
outage cools it down.

No server, no network, no world DB: fake backends raise / return the cases,
and the two real backends under test get their HTTP layer patched out.

Usage:  ./.venv/bin/python scripts/smoke_backend_runner.py

THE RULE, and where it was dead code
---------------------------------------------------------------------------
``run_on_backend`` (app/imagegen/selection.py) documents eight outcomes:

  - ``BackendBusyError``  = load, not a defect -> NO cooldown, re-raised
    typed so the queue boundary retries it.
  - 4xx payload error / ``GatewayRejectedError`` = the service is reachable
    and the REQUEST is broken -> backend stays available, re-raised.
    ``_re_4xx`` matches 400/401/403/404/405/413/422, "Bad Request",
    "Unprocessable" — deliberately NOT 402: no credit means the backend
    cannot deliver, so a quota error IS a cooldown (decision E3).
  - ``NoBackendChannelError`` = the config disabled this backend (or left it
    without a URL) -> no cooldown, re-raised typed so it is skipped.
  - ``TooManyJobsError`` = the submitter's own per-user job quota -> no
    cooldown, re-raised typed (429).
  - ``GpuTaskCancelled`` = a user cancelled the GPU task in the queue panel
    -> no cooldown, re-raised typed (neither load nor defect).
  - ``GpuTaskTimeout`` = the queue watchdog outran the job budget; it IS a
    ``BackendBusyError`` (load) and takes the busy branch.
  - every other exception -> ``mark_unhealthy(..., 300s)`` +
    ``BackendFailedError(backend, cause)``.
  - empty result -> ``mark_unhealthy(..., 300s)`` + ``BackendFailedError``.

``BackendFailedError`` is a RuntimeError subclass since the image routing;
the backend travels with it, and it is the ONE signal the image routing
re-runs an occasion on (``routing.run_routed``).

Until 2026-09-11 the 4xx branch could never fire for the gateway backend:
``openai_diffusion._generate`` caught ``RuntimeError`` — exactly the type
``_post_gateway`` raises WITH the status code in its text — and returned
``[]``. The runner then saw "empty result", not "4xx", and put a perfectly
reachable backend into a 300s cooldown because of a permission error. The
log showed the pair directly: ``HTTP 403 — API key/alias not allowed``
followed by ``generate returned empty result``.

Hand-derived expectations
---------------------------------------------------------------------------
  [1] op raises ``RuntimeError("... (HTTP 400): bad")``  -> RuntimeError out,
      mark_unhealthy called 0x, ``available`` still True.
  [2] op raises ``RuntimeError("... HTTP 500: boom")``   -> BackendFailedError out
      (a RuntimeError subclass carrying the backend — the ONE signal the
      image routing re-runs an occasion on),
      mark_unhealthy called 1x  (500 is no 4xx match).
  [3] op raises ``BackendBusyError("busy")``             -> BackendBusyError
      out (same type, not wrapped), mark_unhealthy 0x.
  [4] op returns ``[]``                                  -> BackendFailedError out
      (a RuntimeError subclass carrying the backend — the ONE signal the
      image routing re-runs an occasion on),
      mark_unhealthy 1x.
  [4b] op raises ``RuntimeError("... (HTTP 402): no credit")`` -> cooldown,
      mark_unhealthy 1x, BackendFailedError out (a RuntimeError subclass
      carrying the backend — the ONE signal the image routing re-runs an
      occasion on) — the deliberate exception to [1].
  [4d] op raises ``TooManyJobsError`` (the SUBMITTER is already at
      ``server.max_inflight_jobs_per_user``, so ``submit_gpu_task`` refused
      before the job was queued): mark_unhealthy 0x, ``available`` still
      True, re-raised TYPED — it carries status 429 and IS the answer the
      caller sends. Without its own branch it fell into the generic one
      (``_re_4xx`` does not match 429) and ONE user hitting his quota took
      a healthy backend away from everyone else for 300 s.
  [4c] op raises ``NoBackendChannelError`` (app/core/provider_manager — the
      named backend has no queue channel, i.e. the config disabled it or it
      has no URL) -> the SAME treatment as busy: mark_unhealthy 0x,
      ``available`` still True, re-raised TYPED so the caller skips this
      backend. Before 2026-09-21 it fell into the generic branch and a merely
      DISABLED backend was put on a 300 s cooldown — which then outlived
      re-enabling it in the admin UI.
  [4e] op raises GpuTaskCancelled (the user cancelled the GPU task in the queue
       panel) -> GpuTaskCancelled out, mark_unhealthy 0x, still available.
       Before: a plain Exception into the generic branch -> 300 s cooldown.
  [4f] op raises GpuTaskTimeout (the queue watchdog) -> GpuTaskTimeout out
       (a BackendBusyError: load), mark_unhealthy 0x.
  [4g] the [2] case once more on a backend named "fake": the
       ``BackendFailedError`` carries ``backend_name == "fake"``, keeps the
       original exception as ``cause`` (text "HTTP 500: boom"), and its
       ``str()`` is "<name>: <cause>" = "fake: HTTP 500: boom".
  [4h] the name appears ONCE: backends already prefix their own messages
       with "<name>: ", so a cause "fake: HTTP 500: boom" keeps its text
       as it is — str() == "fake: HTTP 500: boom", not "fake: fake: …".
  [5] ``OpenAIDiffusionBackend._generate`` with a ``_post_gateway`` that
      raises the 400 RuntimeError must RAISE it. Before the fix: ``[]``.
      Checked for the generations path AND the edits/inpaint path, because
      both carried the same swallowing handler.
  [6] ``CivitAIBackend._generate`` (Orchestration v2) with
      ``max_queue_wait = 0``: the workflow is submitted and still
      ``scheduled``, so the queue budget is spent at once. That is a job
      still queued — LOAD — and must raise ``BackendBusyError``, the same
      class ``openai_diffusion`` raises on its request timeout. Before the
      2026-09 fix: ``[]``, which the runner read as a failure and answered
      with a 300s cooldown on a backend that was merely slow. Since the v2
      move the abandoned workflow is DELETEd first (a queued workflow is
      refunded) — a retry must not leave a paid job running in parallel —
      so the DELETE must come BEFORE the exception.
  [7] ``_wait_for_explicit_backend("nope")`` on a pool that cannot match it
      logs exactly ONE warning; with ``log_missing=False`` it logs NONE.
      The soft-match path in ``service.generate`` passes False: it falls back
      to the default selection and says so itself, so the pool announcing
      "fail-fast" for the same event produced a contradictory log pair.
"""
import atexit
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix: str) -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Throwaway storage and clip library BEFORE the first app import: the queue
# modules imported below reach their world.db through paths, and without a
# storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = _scratch("backend-runner-clips-")

from app.core import paths  # noqa: E402

paths.init(_scratch("backend-runner-storage-"))

from app.core.provider_manager import NoBackendChannelError  # noqa: E402
from app.core.provider_queue import TooManyJobsError  # noqa: E402
from app.imagegen.base import (BackendBusyError, BackendFailedError,  # noqa: E402
                               GpuTaskCancelled, GpuTaskTimeout, ImageBackend)
from app.imagegen import selection as selection_mod  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen.backends.openai_diffusion import OpenAIDiffusionBackend  # noqa: E402
from app.imagegen.backends import civitai as civitai_mod  # noqa: E402

FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


class _Fake(ImageBackend):
    """Minimal backend: always available, counts its own cooldowns."""

    def __init__(self):
        super().__init__("fake", "http://localhost", 0.0, "fake", "FAKE_")
        self._available = True
        self.instance_enabled = True
        self.cooldowns = 0

    def check_availability(self) -> bool:
        return True

    def _generate(self, prompt, negative_prompt, params):
        return []

    def mark_unhealthy(self, reason: str = "", cooldown_seconds: float = 300.0) -> None:
        self.cooldowns += 1
        super().mark_unhealthy(reason, cooldown_seconds)


def run_case(label, op, expect_type, expect_cooldowns, expect_available=True):
    fake = _Fake()
    pool = BackendPool([fake], lambda n: {})
    raised = None
    try:
        pool.run_on_backend(fake, op=op)
    except BaseException as e:   # noqa: BLE001 — the type IS the assertion
        raised = e
    check(f"{label}: exception type", type(raised).__name__, expect_type)
    check(f"{label}: cooldowns", fake.cooldowns, expect_cooldowns)
    check(f"{label}: still available", fake.available, expect_available)


def _raiser(exc):
    def _op(backend):
        raise exc
    return _op


print("[1] 4xx payload error — backend stays in the pool")
run_case("400", _raiser(RuntimeError("fake: Request error (HTTP 400): bad")),
         "RuntimeError", 0, True)

print("[2] 5xx — a real outage cools the backend down")
run_case("500", _raiser(RuntimeError("fake: HTTP 500: boom")),
         "BackendFailedError", 1, False)

print("[3] busy is not broken")
run_case("busy", _raiser(BackendBusyError("busy")), "BackendBusyError", 0, True)

print("[4] empty result counts as a failure")
run_case("empty", lambda b: [], "BackendFailedError", 1, False)

print("[4b] 402 quota stays a cooldown (decision E3)")
run_case("402", _raiser(RuntimeError("fake: Quota/credit limit reached (HTTP 402): x")),
         "BackendFailedError", 1, False)

print("[4c] a backend without a queue channel is disabled, not broken")
run_case("no-channel",
         _raiser(NoBackendChannelError(
             "Backend 'fake' has no queue channel (disabled or without API URL)")),
         "NoBackendChannelError", 0, True)

print("[4d] a user's own job quota is not a backend defect")
run_case("too-many-jobs", _raiser(TooManyJobsError(4, 4, "generation job")),
         "TooManyJobsError", 0, True)
check("too-many-jobs: the 429 reaches the caller",
      TooManyJobsError(4, 4, "generation job").status_code, 429)

print("[4e] a user cancel is neither load nor defect")
run_case("cancelled", _raiser(GpuTaskCancelled("GPU task cancelled: t1")),
         "GpuTaskCancelled", 0, True)

print("[4f] a watchdog timeout is load")
run_case("watchdog", _raiser(GpuTaskTimeout("S: no result within 1s")),
         "GpuTaskTimeout", 0, True)

print("[4g] the failure carries its backend")
_fk = _Fake()
_failed = None
try:
    BackendPool([_fk], lambda n: {}).run_on_backend(
        _fk, op=_raiser(RuntimeError("HTTP 500: boom")))
except BackendFailedError as e:
    _failed = e
check("raised BackendFailedError", _failed is not None, True)
if _failed is not None:
    check("backend_name", _failed.backend_name, "fake")
    check("backend object", _failed.backend is _fk, True)
    check("cause kept", str(_failed.cause), "HTTP 500: boom")
    check("text", str(_failed), "fake: HTTP 500: boom")

print("[4h] a cause that already names its backend is not prefixed twice")
_fk2 = _Fake()
_failed2 = None
try:
    BackendPool([_fk2], lambda n: {}).run_on_backend(
        _fk2, op=_raiser(RuntimeError("fake: HTTP 500: boom")))
except BackendFailedError as e:
    _failed2 = e
check("raised BackendFailedError", _failed2 is not None, True)
check("text names the backend once", str(_failed2), "fake: HTTP 500: boom")

print("[5] openai_diffusion hands the HTTP error on instead of swallowing it")
for label, method, kwargs in (
        ("generations", "_generate", {}),
        ("edits", "_generate_edits", {}),
):
    gw = OpenAIDiffusionBackend("t", "http://x", 1.0, "T_")

    def _boom(*a, **k):
        raise RuntimeError("t: Request error (HTTP 400): x")

    gw._post_gateway = _boom
    # the edits path refuses without a reference image; a data: URI keeps the
    # check free of file IO, and the request never leaves the process.
    _px = "data:image/png;base64,iVBORw0KGgo="
    params = ({"reference_images": {"canvas": _px, "input_mask": _px}}
              if method == "_generate_edits" else {})
    raised = None
    try:
        getattr(gw, method)("a prompt", "", params)
    except BaseException as e:   # noqa: BLE001
        raised = e
    check(f"{label}: raises", type(raised).__name__, "RuntimeError")
    check(f"{label}: keeps the HTTP code in the text",
          "HTTP 400" in str(raised or ""), True)

print("[6] a civitai polling timeout is load, not a defect")


class _Resp:
    """Just enough of a requests.Response for the workflow submit."""

    status_code = 202
    content = b"{}"
    text = ""

    @staticmethod
    def json():
        return {"id": "wf1", "status": "scheduled"}


_calls = []
_requests = civitai_mod.requests
_orig = {m: getattr(_requests, m) for m in ("post", "get", "put", "delete")}


def _record(method, result=None):
    def _fn(*a, **k):
        _calls.append(method)
        return result
    return _fn


civ = civitai_mod.CivitAIBackend("c", "http://x", 1.0, "C_",
                                 api_key="k", model="urn:air:sdxl:checkpoint:civitai:1@2")
civ.max_queue_wait = 0      # the queue budget is spent before the first poll
civ.poll_interval = 0
_requests.post = _record("post", _Resp())
_requests.get = _record("get")        # a poll would be a bug here
_requests.put = _record("put")
_requests.delete = _record("delete")
raised = None
try:
    civ._generate("a prompt", "", {})
except BaseException as e:   # noqa: BLE001
    raised = e
finally:
    for _m, _fn in _orig.items():
        setattr(_requests, _m, _fn)
check("civitai timeout: exception type", type(raised).__name__, "BackendBusyError")
check("civitai timeout: the queued workflow is DELETEd before the raise",
      _calls, ["post", "delete"])

print("[7] the miss is announced by whoever owns the policy")


class _CountingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warnings.append(record.getMessage())


_counter = _CountingHandler()
selection_mod.logger.addHandler(_counter)
try:
    empty_pool = BackendPool([], lambda n: {})
    empty_pool._wait_for_explicit_backend("nope")
    check("explicit miss: warnings", len(_counter.warnings), 1)
    _counter.warnings.clear()
    empty_pool._wait_for_explicit_backend("nope", log_missing=False)
    check("soft miss: warnings", len(_counter.warnings), 0)
finally:
    selection_mod.logger.removeHandler(_counter)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
sys.exit(0)
