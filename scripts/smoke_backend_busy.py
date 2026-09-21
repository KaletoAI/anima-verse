#!/usr/bin/env python3
"""Smoke run for "BUSY IS NOT BROKEN" (app/imagegen/base.py) on the five
backends that used to answer a LOAD situation with an untyped exception or an
empty list: a1111, openai_chat, together, together_video, localai_video.

No server, no network, no world DB: each backend's HTTP layer is replaced by a
stub that answers exactly the case under test, and ``_generate`` is called
directly (the same way scripts/smoke_backend_runner.py drives civitai).

Usage:  ./.venv/bin/python scripts/smoke_backend_busy.py

THE RULE
---------------------------------------------------------------------------
``selection.run_on_backend`` reads the failure TYPE:

  - ``BackendBusyError``            -> no cooldown, retried elsewhere at once
  - any other exception / ``[]``    -> ``mark_unhealthy(..., 300s)``

So a merely LOADED backend must raise ``BackendBusyError``:
  * a request timeout while the endpoint is reachable,
  * HTTP 429 (rate limit) / HTTP 503 (busy, no capacity),
  * ``max_wait`` exhausted while the job is still queued or rendering.
A REAL failure must NOT: connection refused, 4xx auth/validation, a malformed
response, a job the provider reports as ``failed``.

Hand-derived expectations (one line per case, the type IS the assertion)
---------------------------------------------------------------------------
a1111        [1a] requests.Timeout on POST            -> BackendBusyError
             [1b] HTTP 429                            -> BackendBusyError
             [1c] HTTP 503                            -> BackendBusyError
             [1d] HTTP 401 (auth)                     -> HTTPError   (defect)
             [1e] ConnectionError                     -> ConnectionError
openai_chat  [2a] requests.Timeout on POST            -> BackendBusyError
             [2b] HTTP 429                            -> BackendBusyError
             [2c] HTTP 400 (bad request)              -> HTTPError   (defect)
together     [3a] requests.Timeout on POST            -> BackendBusyError
             [3b] HTTP 429 on every attempt (5 posts: 1 + _max_429=4)
                                                      -> BackendBusyError
             [3c] HTTP 503                            -> BackendBusyError
             [3d] HTTP 400 naming no known parameter  -> []  (RuntimeError is
                  caught in _generate and turned into an empty result — a
                  payload defect, which stays a defect)
together_vid [4a] max_wait = 0 -> the poll loop cannot run one round, the job
                  is neither completed nor failed                       -> BackendBusyError
             [4b] HTTP 503 on job creation            -> BackendBusyError
             [4c] job status "failed"                 -> []   (defect)
localai_vid  [5a] max_wait = 0, async job id in the body -> BackendBusyError
             [5b] HTTP 429 on job creation            -> BackendBusyError
             [5c] job status "failed"                 -> []   (defect)

Before the fix every BackendBusyError line above was a bare ``raise`` (a1111 /
openai_chat: requests.Timeout, no 429/503 branch at all) or ``return []``
(together, together_video, localai_video) — i.e. a 300 s cooldown on a healthy
backend.  Confirmed by running this script against the pre-fix sources
(``git show HEAD:app/imagegen/backends/<f>.py``): all 12 busy cases fail there,
the 6 defect cases pass unchanged.
"""
import base64
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from app.imagegen.backends import a1111 as a1111_mod  # noqa: E402
from app.imagegen.backends import localai_video as lv_mod  # noqa: E402
from app.imagegen.backends import openai_chat as chat_mod  # noqa: E402
from app.imagegen.backends import together as tg_mod  # noqa: E402
from app.imagegen.backends import together_video as tgv_mod  # noqa: E402

FAILED = []

# Polling/backoff must not make the check slow — nothing here waits for real.
time.sleep = lambda *_a, **_k: None          # noqa: E731


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


def outcome(fn):
    """Runs ``fn`` and returns the exception class name, or ``"[]"`` / repr."""
    try:
        res = fn()
    except BaseException as e:               # noqa: BLE001 — the type IS the check
        return type(e).__name__
    return "[]" if res == [] else repr(res)


class _Resp:
    """Just enough of a requests.Response."""

    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = b"x"
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def _post(*responses):
    """A POST stub that answers the given responses in order (last repeats)."""
    seq = list(responses)

    def _fn(*_a, **_k):
        r = seq[0] if len(seq) == 1 else seq.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r
    return _fn


# --------------------------------------------------------------------------
print("[1] a1111")
a1111 = a1111_mod.A1111Backend("a", "http://x", 1.0, "A_")

a1111_mod.requests.post = _post(requests.exceptions.Timeout("slow"))
check("1a timeout", outcome(lambda: a1111._generate("p", "", {})),
      "BackendBusyError")
for code, label, expected in ((429, "1b 429", "BackendBusyError"),
                              (503, "1c 503", "BackendBusyError"),
                              (401, "1d 401", "HTTPError")):
    a1111_mod.requests.post = _post(_Resp(code, text="nope"))
    check(label, outcome(lambda: a1111._generate("p", "", {})), expected)
a1111_mod.requests.post = _post(requests.exceptions.ConnectionError("refused"))
check("1e refused", outcome(lambda: a1111._generate("p", "", {})),
      "ConnectionError")

# --------------------------------------------------------------------------
print("[2] openai_chat")
chat = chat_mod.OpenAIChatImageBackend("c", "http://x", 1.0, "C_",
                                       api_key="k", model="m")

chat_mod.requests.post = _post(requests.exceptions.Timeout("slow"))
check("2a timeout", outcome(lambda: chat._generate("p", "", {})),
      "BackendBusyError")
for code, label, expected in ((429, "2b 429", "BackendBusyError"),
                              (400, "2c 400", "HTTPError")):
    chat_mod.requests.post = _post(_Resp(code, text="nope"))
    check(label, outcome(lambda: chat._generate("p", "", {})), expected)

# --------------------------------------------------------------------------
print("[3] together")
tg = tg_mod.TogetherBackend("t", "http://x", 1.0, "T_", api_key="k", model="m")

tg_mod.requests.post = _post(requests.exceptions.Timeout("slow"))
check("3a timeout", outcome(lambda: tg._generate("p", "", {})),
      "BackendBusyError")
# 1 initial attempt + _max_429 = 4 retries, all answered 429 -> give 6 so the
# loop cannot run out of responses before the backend gives up.
tg_mod.requests.post = _post(*[_Resp(429, text="slow down") for _ in range(6)])
check("3b 429 exhausted", outcome(lambda: tg._generate("p", "", {})),
      "BackendBusyError")
tg_mod.requests.post = _post(_Resp(503, text="no capacity"))
check("3c 503", outcome(lambda: tg._generate("p", "", {})), "BackendBusyError")
tg_mod.requests.post = _post(_Resp(400, text="unsupported thing"))
check("3d 400", outcome(lambda: tg._generate("p", "", {})), "[]")

# --------------------------------------------------------------------------
print("[4] together_video")
with tempfile.TemporaryDirectory() as _tmp:
    frame = Path(_tmp) / "frame.png"
    frame.write_bytes(base64.b64decode("iVBORw0KGgo="))
    tgv = tgv_mod.TogetherVideoBackend("v", "http://x", 1.0, "V_",
                                       api_key="k", model="m")
    params = {"source_image_path": str(frame)}

    tgv.max_wait = 0
    tgv_mod.requests.post = _post(_Resp(200, {"id": "j1"}))
    check("4a max_wait", outcome(lambda: tgv._generate("p", "", params)),
          "BackendBusyError")

    tgv_mod.requests.post = _post(_Resp(503, text="busy"))
    check("4b 503", outcome(lambda: tgv._generate("p", "", params)),
          "BackendBusyError")

    tgv.max_wait = 60
    tgv_mod.requests.post = _post(_Resp(200, {"id": "j1"}))
    tgv_mod.requests.get = _post(_Resp(200, {"status": "failed",
                                             "error": "bad model"}))
    check("4c job failed", outcome(lambda: tgv._generate("p", "", params)),
          "[]")

# --------------------------------------------------------------------------
print("[5] localai_video")
lv = lv_mod.LocalAIVideoBackend("l", "http://x", 1.0, "L_", model="m")
# A data: URI keeps the first frame free of file IO on this path.
lv_params = {"source_image_path": "data:image/png;base64,iVBORw0KGgo="}

lv.max_wait = 0
lv_mod.requests.post = _post(_Resp(200, {"id": "j1", "status": "queued"}))
check("5a max_wait", outcome(lambda: lv._generate("p", "", lv_params)),
      "BackendBusyError")

lv_mod.requests.post = _post(_Resp(429, text="slow down"))
check("5b 429", outcome(lambda: lv._generate("p", "", lv_params)),
      "BackendBusyError")

lv.max_wait = 60
lv_mod.requests.post = _post(_Resp(200, {"id": "j1", "status": "queued"}))
lv_mod.requests.get = _post(_Resp(200, {"status": "failed", "error": "bad"}))
check("5c job failed", outcome(lambda: lv._generate("p", "", lv_params)), "[]")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
sys.exit(0)
