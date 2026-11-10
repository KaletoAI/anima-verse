#!/usr/bin/env python3
"""Smoke: a failed gateway job is classified by its STRUCTURE, not its text
(``GatewayJobFailed`` in ``app/imagegen/base.py``, raised by
``_gateway_job.poll_job``; ``BackendPool.run_on_backend`` in
``app/imagegen/selection.py``). Footwear P1 fix round, controller follow-up.

Usage:
    ./.venv/bin/python scripts/smoke_gateway_job_failure_class.py

No server, no gateway, no world DB (throwaway storage before the app
imports): ``requests.get`` of ``_gateway_job`` answers canned polls, the real
``poll_job`` runs inside the real ``run_on_backend`` of a ``BackendPool`` with
one fake backend that counts its cooldowns.

The runner keeps a backend WITHOUT cooldown when an error's text matches
``_re_4xx`` (a rejected request). A failed job's text is the gateway's own
error and may quote any status of whatever failed inside the worker — so a
job that crashed while a download answered 404 used to look like a rejected
request. Expected, by hand:

[F1] poll HTTP 200, {"status": "failed", "error": "ComfyUI: node 4
     LoadWeights: HTTP 404 Not Found (weights.safetensors)"} — a job the
     worker failed (a 500-class defect) whose text contains "404".
     Precondition: ``_re_4xx`` matches that text (else the case proves
     nothing). -> poll_job raises GatewayJobFailed (job_status "failed",
     detail = the text) -> run_on_backend: cooldown 1x, backend unavailable,
     BackendFailedError out whose cause is that GatewayJobFailed and whose
     text is "fake: job j1 failed: ComfyUI: node 4 …" (display only).
[F2] a REAL 404: the poll itself answers HTTP 404 three times in a row (the
     gateway no longer knows the job) -> GatewayRejectedError "fake: job j1
     is no longer retrievable (HTTP 404)" -> re-raised unchanged, cooldown
     0x, backend still available.
[F3] scope: an exception that is NOT a gateway job failure keeps the text
     rule — RuntimeError("fake: Request error (HTTP 404): unknown alias") ->
     re-raised, cooldown 0x (smoke_backend_runner [1] for 400).
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _scratch(prefix: str) -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("job-failure-clips-")
from app.core import paths  # noqa: E402

paths.init(_scratch("job-failure-storage-"))

from app.imagegen import selection as selection_mod  # noqa: E402
from app.imagegen.backends import _gateway_job as gj  # noqa: E402
from app.imagegen.base import (BackendFailedError, GatewayJobFailed,  # noqa: E402
                               GatewayRejectedError, ImageBackend)
from app.imagegen.selection import BackendPool  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:260] + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self):
        super().__init__("fake", "http://gateway.invalid", 0.0, "fake", "FAKE_")
        self._available = True
        self.instance_enabled = True
        self.cooldowns = 0

    def check_availability(self) -> bool:
        return True

    def _headers(self):
        return {}

    def _generate(self, prompt, negative_prompt, params):
        return []

    def mark_unhealthy(self, reason: str = "", cooldown_seconds: float = 300.0) -> None:
        self.cooldowns += 1
        super().mark_unhealthy(reason, cooldown_seconds)


class Reply:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}
        self.content = b"x"

    def json(self):
        return self._body


def run(reply):
    """poll_job against canned polls inside run_on_backend -> (backend, raised)."""
    fake = Fake()
    pool = BackendPool([fake])

    def op(b):
        return gj.poll_job(b, "j1", max_wait=60, max_queue_wait=60, poll_interval=0,
                           on_done=lambda sd, t: [b"blob"])
    raised = None
    with mock.patch.object(gj.requests, "get", lambda *a, **k: reply), \
            mock.patch.object(gj.requests, "post", lambda *a, **k: Reply(200)), \
            mock.patch.object(gj.time, "sleep", lambda _s: None):
        try:
            pool.run_on_backend(fake, op=op)
        except BaseException as e:  # noqa: BLE001 — the type IS the assertion
            raised = e
    return fake, raised


print("[F1] a failed job whose text quotes a 404 is a defect (cooldown)")
text = "ComfyUI: node 4 LoadWeights: HTTP 404 Not Found (weights.safetensors)"
check("F1 precondition: the text matches the 4xx text rule", bool(selection_mod._re_4xx.search(text)), True)
fake, raised = run(Reply(200, {"status": "failed", "error": text}))
check("F1 BackendFailedError out", type(raised).__name__, "BackendFailedError")
cause = getattr(raised, "cause", None)
check("F1 cause is the structured job failure",
      (type(cause).__name__, getattr(cause, "job_status", None), getattr(cause, "detail", None)),
      ("GatewayJobFailed", "failed", text))
check("F1 cooldown 1x, unavailable", (fake.cooldowns, fake.available), (1, False))
check("F1 text for display", str(raised), "fake: job j1 failed: " + text)

print("[F2] a real 404 (the poll's own HTTP status) keeps the backend")
fake, raised = run(Reply(404))
check("F2 GatewayRejectedError out", (type(raised).__name__, str(raised)),
      ("GatewayRejectedError", "fake: job j1 is no longer retrievable (HTTP 404)"))
check("F2 no cooldown, available", (fake.cooldowns, fake.available), (0, True))

print("[F3] other exceptions keep the text rule")
fake = Fake()
raised = None
try:
    BackendPool([fake]).run_on_backend(
        fake, op=lambda b: (_ for _ in ()).throw(RuntimeError("fake: Request error (HTTP 404): unknown alias")))
except BaseException as e:  # noqa: BLE001
    raised = e
check("F3 re-raised as is, no cooldown", (type(raised).__name__, fake.cooldowns, fake.available),
      ("RuntimeError", 0, True))
check("F3 types", (issubclass(GatewayJobFailed, RuntimeError), issubclass(BackendFailedError, RuntimeError),
                   issubclass(GatewayRejectedError, RuntimeError)), (True, True, True))

print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
