#!/usr/bin/env python3
"""Smoke run for the error classification of ``BackendPool.run_on_backend`` —
that a payload error keeps a healthy backend in the pool and only a real
outage cools it down.

No server, no network, no world DB: fake backends raise / return the cases,
and the two real backends under test get their HTTP layer patched out.

Usage:  ./.venv/bin/python scripts/smoke_backend_runner.py

THE RULE, and where it was dead code
---------------------------------------------------------------------------
``run_on_backend`` (app/imagegen/selection.py) documents four outcomes:

  - ``BackendBusyError``  = load, not a defect -> NO cooldown, re-raised
    typed so the queue boundary retries it.
  - 4xx payload error / ``GatewayRejectedError`` = the service is reachable
    and the REQUEST is broken -> backend stays available, re-raised.
    ``_re_4xx`` matches 400/401/403/404/405/413/422, "Bad Request",
    "Unprocessable" — deliberately NOT 402: no credit means the backend
    cannot deliver, so a quota error IS a cooldown (decision E3).
  - every other exception -> ``mark_unhealthy(..., 300s)``, re-raised.
  - empty result -> ``mark_unhealthy(..., 300s)`` + ``RuntimeError``.

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
  [2] op raises ``RuntimeError("... HTTP 500: boom")``   -> RuntimeError out,
      mark_unhealthy called 1x  (500 is no 4xx match).
  [3] op raises ``BackendBusyError("busy")``             -> BackendBusyError
      out (same type, not wrapped), mark_unhealthy 0x.
  [4] op returns ``[]``                                  -> RuntimeError out,
      mark_unhealthy 1x.
  [4b] op raises ``RuntimeError("... (HTTP 402): no credit")`` -> cooldown,
      mark_unhealthy 1x — the deliberate exception to [1].
  [5] ``OpenAIDiffusionBackend._generate`` with a ``_post_gateway`` that
      raises the 400 RuntimeError must RAISE it. Before the fix: ``[]``.
      Checked for the generations path AND the edits/inpaint path, because
      both carried the same swallowing handler.
  [6] ``CivitAIBackend._generate`` with ``max_wait = 0``: the job is created,
      the polling loop never runs (``time.time() - start < 0`` is false at
      once), so no blobUrl arrives. That is a job still queued or rendering —
      LOAD — and must raise ``BackendBusyError``, the same class
      ``openai_diffusion`` raises on its request timeout. Before the fix:
      ``[]``, which the runner read as a failure and answered with a 300s
      cooldown on a backend that was merely slow.
  [7] ``_wait_for_explicit_backend("nope")`` on a pool that cannot match it
      logs exactly ONE warning; with ``log_missing=False`` it logs NONE.
      The soft-match path in ``service.generate`` passes False: it falls back
      to the default selection and says so itself, so the pool announcing
      "fail-fast" for the same event produced a contradictory log pair.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.imagegen.base import BackendBusyError, ImageBackend  # noqa: E402
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
         "RuntimeError", 1, False)

print("[3] busy is not broken")
run_case("busy", _raiser(BackendBusyError("busy")), "BackendBusyError", 0, True)

print("[4] empty result counts as a failure")
run_case("empty", lambda b: [], "RuntimeError", 1, False)

print("[4b] 402 quota stays a cooldown (decision E3)")
run_case("402", _raiser(RuntimeError("fake: Quota/credit limit reached (HTTP 402): x")),
         "RuntimeError", 1, False)

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
    """Just enough of a requests.Response for the job-creation call."""

    status_code = 200

    @staticmethod
    def json():
        return {"token": "tok", "jobs": [{"jobId": "j"}]}

    text = ""


civ = civitai_mod.CivitAIBackend("c", "http://x", 1.0, "C_",
                                 api_key="k", model="urn:air:sdxl:checkpoint:civitai:1@2")
civ.max_wait = 0            # the poll loop cannot run a single round
civitai_mod.requests.post = lambda *a, **k: _Resp()
raised = None
try:
    civ._generate("a prompt", "", {})
except BaseException as e:   # noqa: BLE001
    raised = e
check("civitai timeout: exception type", type(raised).__name__, "BackendBusyError")

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
