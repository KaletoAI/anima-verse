#!/usr/bin/env python3
"""A gateway job cancelled by the user is a cancel, not a backend defect.

Usage:
    ./.venv/bin/python scripts/smoke_gateway_job_cancelled.py

No server, no gateway: ``requests.get`` of ``app/imagegen/backends/_gateway_job.py``
answers one canned job status. On 2026-10-31 the gateway reported a job the
user had cancelled in its UI as ``{"status": "failed", "error": "cancelled by
user"}``; ``poll_job`` returned ``[]`` for it, the pool put the backend in a
300 s cooldown and the routing re-ran the occasion on the next backend.
Hand-derived from the failure contract in the module docstring:

  [1] status "cancelled"                          -> GenerationCancelled
  [2] status "failed", error "cancelled by user"  -> GenerationCancelled
  [3] status "failed", error "Cancelled"          -> GenerationCancelled
  [4] status "failed", error "CUDA out of memory" -> GatewayJobFailed
      "fixture: job job1 failed: CUDA out of memory" (a defect: cooldown; the
      gateway's text is the message — footwear P1 fix round)
  [5] status "failed", error "not cancelled: OOM" -> GatewayJobFailed (only a
      LEADING "cancelled" is a cancel)
"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.imagegen.backends import _gateway_job as gj  # noqa: E402
from app.imagegen.base import GenerationCancelled  # noqa: E402

FAILS = []


class Backend:
    name = "fixture"
    api_url = "http://gateway.invalid"

    def _headers(self):
        return {}


class Reply:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.content = b"x"

    def json(self):
        return self._body


def outcome(body):
    with mock.patch.object(gj.requests, "get", lambda *a, **k: Reply(body)), \
            mock.patch.object(gj, "_cancel_lost_job", lambda *a: None):
        try:
            return gj.poll_job(Backend(), "job1", max_wait=5, max_queue_wait=5,
                               poll_interval=0, on_done=lambda sd, s: [b"blob"])
        except GenerationCancelled:
            return "cancelled"
        except gj.GatewayJobFailed as e:
            return f"failed: {e}"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


check("[1] status cancelled", outcome({"status": "cancelled"}), "cancelled")
check("[2] failed: cancelled by user", outcome({"status": "failed", "error": "cancelled by user"}), "cancelled")
check("[3] failed: Cancelled", outcome({"status": "failed", "error": "Cancelled"}), "cancelled")
check("[4] failed: CUDA out of memory", outcome({"status": "failed", "error": "CUDA out of memory"}),
      "failed: fixture: job job1 failed: CUDA out of memory")
check("[5] failed: not cancelled: OOM", outcome({"status": "failed", "error": "not cancelled: OOM"}),
      "failed: fixture: job job1 failed: not cancelled: OOM")
print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
