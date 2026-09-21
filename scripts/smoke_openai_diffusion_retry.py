#!/usr/bin/env python3
"""Smoke run for the retry loop of the openai_diffusion backend (IMG-11).

Pure check — no storage, no HTTP: ``requests.post`` and ``time.sleep`` of the
backend module are replaced by recorders, so the run measures which status
code waits how long before it tries again.

Expected values, derived by hand from the loop in ``_post_gateway``
(``max_429, max_502, max_503 = 4, 1, 4``):

* 502 ("generation failed / park timeout") retries EXACTLY once and waits
  2.0 s first — the first step of the 503 backoff. Without the wait the
  second POST hits the gateway in the state that just failed. Two POSTs,
  then ``RuntimeError`` (a real defect, so the backend goes on cooldown).
* 503 ("no healthy backend") waits 2, 4, 8, 16 s and raises
  ``BackendBusyError`` on the fifth answer — load, not a defect, so no
  cooldown (round-one typing).
* 429 (rate limit) waits 2, 4, 8, 16 s as well (no Retry-After header) and
  also raises ``BackendBusyError``.
* 200 returns immediately, without a single wait.

Usage:  ./.venv/bin/python scripts/smoke_openai_diffusion_retry.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.imagegen.backends.openai_diffusion as od  # noqa: E402
from app.imagegen.base import BackendBusyError  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeResponse:
    def __init__(self, code):
        self.status_code = code
        self.text = f"fake body {code}"
        self.headers = {}


def run(codes):
    """Drives the loop against a fixed list of status codes.

    Returns (posts, waits, raised) — ``raised`` is the exception instance or
    the returned response.
    """
    backend = od.OpenAIDiffusionBackend.__new__(od.OpenAIDiffusionBackend)
    backend.name = "gateway-test"
    backend.api_url = "http://localhost:9"
    backend.api_key = "k"
    backend.timeout = 1
    backend._headers = lambda: {"Authorization": "Bearer k"}

    posts = []
    waits = []
    seq = list(codes)

    def _post(url, **kwargs):
        posts.append(url)
        return FakeResponse(seq[len(posts) - 1] if len(posts) <= len(seq)
                            else seq[-1])

    _real_post, _real_sleep = od.requests.post, od.time.sleep
    od.requests.post = _post
    od.time.sleep = lambda s: waits.append(round(float(s), 3))
    try:
        result = backend._post_gateway("generations", json={"prompt": "x"})
    except Exception as e:  # noqa: BLE001 — the raised error IS the result here
        result = e
    finally:
        od.requests.post, od.time.sleep = _real_post, _real_sleep
    return posts, waits, result


def main() -> int:
    print("\n[1] 502 — retry once, WITH a wait")
    posts, waits, res = run([502, 502])
    check("two POSTs", len(posts) == 2, str(len(posts)))
    check("waits 2.0 s between them", waits == [2.0], str(waits))
    check("then a RuntimeError (defect → cooldown)",
          isinstance(res, RuntimeError) and not isinstance(res, BackendBusyError),
          type(res).__name__)

    print("\n[2] 502 then success")
    posts, waits, res = run([502, 200])
    check("two POSTs, one wait", len(posts) == 2 and waits == [2.0],
          f"{len(posts)} {waits}")
    check("the 200 response is returned",
          isinstance(res, FakeResponse) and res.status_code == 200)

    print("\n[3] 503 — the backoff the 502 branch is modelled on")
    posts, waits, res = run([503])
    check("five POSTs", len(posts) == 5, str(len(posts)))
    check("waits 2, 4, 8, 16", waits == [2.0, 4.0, 8.0, 16.0], str(waits))
    check("BackendBusyError (load, not a defect → no cooldown)",
          isinstance(res, BackendBusyError), type(res).__name__)

    print("\n[4] 429 — rate limit")
    posts, waits, res = run([429])
    check("five POSTs, waits 2, 4, 8, 16",
          len(posts) == 5 and waits == [2.0, 4.0, 8.0, 16.0],
          f"{len(posts)} {waits}")
    check("BackendBusyError", isinstance(res, BackendBusyError),
          type(res).__name__)

    print("\n[5] 200 — no wait at all")
    posts, waits, res = run([200])
    check("one POST, no wait", len(posts) == 1 and waits == [],
          f"{len(posts)} {waits}")

    print("\n[6] 400 — no retry, no wait")
    posts, waits, res = run([400])
    check("one POST, no wait, RuntimeError",
          len(posts) == 1 and waits == [] and isinstance(res, RuntimeError),
          f"{len(posts)} {waits} {type(res).__name__}")

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + "; ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
