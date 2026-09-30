#!/usr/bin/env python3
"""Smoke run for the gateway 503/502 mapping (plan-befundrunde-2026-09-29 B2,
incl. the binding review notes). The soft-glob transition of that round is
gone (see [F]/[G] below).

Usage:  ./.venv/bin/python scripts/smoke_gateway_503_mapping.py

No server, no network, no world DB: ``paths.init`` points at a throwaway
directory BEFORE any app import, ``requests.post`` / ``time.sleep`` of each
backend module are replaced by recorders.

THE GATEWAY SEMANTICS (ai-hub/main.py, as the design quotes it)
---------------------------------------------------------------------------
* 503 WITHOUT ``Retry-After`` = the alias has no healthy backend at all → a
  DEFECT once it outlasts the gateway's documented ~30 s health flap: retried
  after waits of 2, 8 and 20 s (``GATEWAY_503_FLAP_WAITS_S``, 30 s in all),
  then ``RuntimeError`` → ``run_on_backend`` puts the backend on cooldown
  (``available`` False). A shorter window let a saturated GPU walk its
  sibling aliases into cooldown one after the other.
* 503 WITH ``Retry-After`` = queue full → LOAD: ``BackendBusyError``, the
  wait taken from the header, no cooldown.
* 502 whose body says "park timeout" / "backend busy" → LOAD
  (``BackendBusyError``, no retry — a second POST would only park again);
  every other 502 behaves as before (openai_diffusion: one retry, then
  ``RuntimeError``).

Hand-derived expectations
---------------------------------------------------------------------------
[A] openai_diffusion ``_post_gateway`` (max_503 = 4, cap 30 s):
    A1 503 (no header), always   → 1 + 3 = 4 POSTs, waits [2, 8, 20],
                                   RuntimeError naming "no healthy backend"
    A2 503 (no header), 200      → 2 POSTs, waits [2.0], the 200 response
    A2b 503, 503, 503, 200       → 4 POSTs, waits [2, 8, 20], the 200 — the
                                   flap window is used in full
    A3 503 Retry-After: 1, always→ 1 + 4 = 5 POSTs, waits [1,1,1,1],
                                   BackendBusyError
    A4 503 Retry-After: 90, 200  → waits [30.0] (capped), the 200 response
    A5 502 "park timeout"        → 1 POST, no wait, BackendBusyError
    A6 502 "Backend busy"        → 1 POST, no wait, BackendBusyError (the
                                   match ignores case)
    A7 502 "generation failed" ×2→ 2 POSTs, waits [2.0], RuntimeError
[B] through ``BackendPool.run_on_backend`` (the cooldown decision):
    B1 503 without header        → RuntimeError, backend.available False
    B2 503 with Retry-After: 1   → BackendBusyError, backend.available True
[C] ``_gateway_job.submit_job`` (video/mesh; 3 attempts, cap 120 s,
    default wait 10 s):
    C1 503 (no header), always   → 4 POSTs, waits [2, 8, 20], RuntimeError
    C2 503 no header, 202 job j1 → "j1", waits [2.0]
    C3 503 Retry-After: 5, always→ 3 POSTs, waits [5.0, 5.0], BackendBusyError
    C4 429 (no header), always   → 3 POSTs, waits [10.0, 10.0], BackendBusyError
    C5 502 "park timeout"        → 1 POST, BackendBusyError
    C6 poll_job: job "failed" with error "park timeout" → BackendBusyError;
       with error "CUDA out of memory" → [] (a defect, as before)
    C7 poll_job, a LOST job (Task 16b, review carry-over of 16a: with image
       routing a failed mesh/video is re-run on the next chain entry, so the
       abandoned job must not keep running on the gateway). Lost = 3
       consecutive 404s, or more than 10 (= 11) other failed polls:
       C7a GET → 404 always          → 3 GETs, [] and exactly ONE POST to
                                       http://gw.invalid/v1/jobs/j1/cancel
       C7b GET → 500 always          → 11 GETs, [], one cancel POST
       C7c GET raises ConnectionError→ 11 GETs, [], one cancel POST
       C7d GET → 404, the cancel POST raises → still [] (best effort: the
                                       cancel never raises out of poll_job)
       C7e C6's "failed" job (the gateway ENDED it) → no cancel POST (0)
       Fails on commit 4893221f: C7a-C7d see 0 cancel POSTs.
[D] localai_video ``_generate``:
    D1 503 (no header), always   → 4 POSTs, waits [2, 8, 20], RuntimeError
    D2 503 Retry-After: 3        → 1 POST, BackendBusyError
    D3 502 "park timeout"        → BackendBusyError
[E] openai_chat ``_generate``:
    E1 503 (no header), always   → 4 POSTs, waits [2, 8, 20], RuntimeError
    E2 503 Retry-After: 3        → 1 POST, BackendBusyError
    E3 502 "park timeout"        → BackendBusyError
[F]/[G] (the soft-glob transition of the bug round, B2.3 —
    ``BackendPool.matches_configured`` and the "matches only unavailable
    backends" answer of ``generate_from_input``) are gone: replaced by the
    image routing chains, plan-image-routing.md R2a
    (``scripts/smoke_image_service_facade.py`` F5 covers the dead chain).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_gw503_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)

import requests  # noqa: E402

import app.imagegen.backends._gateway_job as gj  # noqa: E402
import app.imagegen.backends.localai_video as lv_mod  # noqa: E402
import app.imagegen.backends.openai_chat as chat_mod  # noqa: E402
import app.imagegen.backends.openai_diffusion as od  # noqa: E402
from app.imagegen.base import BackendBusyError  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeResponse:
    def __init__(self, code, text="", headers=None, payload=None):
        self.status_code = code
        self.text = text or f"fake body {code}"
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload).encode() if payload else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def drive(module, responses, fn):
    """Runs ``fn`` with ``module.requests.post`` answering ``responses`` in
    order (the last one repeats) and ``module.time.sleep`` recording.
    Returns (posts, waits, result-or-exception)."""
    posts, waits = [], []

    def _post(url, **_kw):
        posts.append(url)
        i = min(len(posts), len(responses)) - 1
        return responses[i]

    real_post, real_sleep = module.requests.post, module.time.sleep
    module.requests.post = _post
    module.time.sleep = lambda s: waits.append(round(float(s), 3))
    try:
        result = fn()
    except Exception as e:  # noqa: BLE001 — the raised error IS the result
        result = e
    finally:
        module.requests.post, module.time.sleep = real_post, real_sleep
    return posts, waits, result


def is_defect(res) -> bool:
    return isinstance(res, RuntimeError) and not isinstance(res, BackendBusyError)


R503 = lambda: FakeResponse(503, "No healthy backend for alias")  # noqa: E731
def R503RA(s): return FakeResponse(503, "queue full", {"Retry-After": str(s)})  # noqa: E704
R200 = lambda: FakeResponse(200, "ok")  # noqa: E731
# Derived by hand from the gateway's ~30 s health flap (2 + 8 + 20 s).
FLAP = [2.0, 8.0, 20.0]


# ── [A] openai_diffusion ────────────────────────────────────────────────
def diffusion_backend():
    b = od.OpenAIDiffusionBackend("gw-diff", "http://gw.invalid", 0.0,
                                  "P1SMOKE_GWDIFF_", api_key="k", model="alias")
    b.timeout = 1
    b.available = True
    return b


def diff_post(b):
    return lambda: b._post_gateway("generations", json={"prompt": "x"})


print("\n[A] openai_diffusion _post_gateway")
b = diffusion_backend()
posts, waits, res = drive(od, [R503()], diff_post(b))
check("A1 503 without header: 4 POSTs", len(posts) == 4, str(len(posts)))
check("A1 flap waits [2, 8, 20]", waits == FLAP, str(waits))
check("A1 RuntimeError naming 'no healthy backend'",
      is_defect(res) and "no healthy backend" in str(res), repr(res))

posts, waits, res = drive(od, [R503(), R200()], diff_post(b))
check("A2 flap then 200: response returned after one wait",
      len(posts) == 2 and waits == [2.0] and getattr(res, "status_code", 0) == 200,
      f"{len(posts)} {waits} {res!r}")

posts, waits, res = drive(od, [R503(), R503(), R503(), R200()], diff_post(b))
check("A2b 200 after the full flap window",
      len(posts) == 4 and waits == FLAP and getattr(res, "status_code", 0) == 200,
      f"{len(posts)} {waits} {res!r}")

posts, waits, res = drive(od, [R503RA(1)], diff_post(b))
check("A3 503 Retry-After: 5 POSTs", len(posts) == 5, str(len(posts)))
check("A3 waits [1,1,1,1] from the header", waits == [1.0, 1.0, 1.0, 1.0], str(waits))
check("A3 BackendBusyError", isinstance(res, BackendBusyError), repr(res))

posts, waits, res = drive(od, [R503RA(90), R200()], diff_post(b))
check("A4 Retry-After 90 capped at 30 s", waits == [30.0], str(waits))

posts, waits, res = drive(od, [FakeResponse(502, "gateway park timeout after 600s")],
                          diff_post(b))
check("A5 502 park timeout: 1 POST, no wait, BackendBusyError",
      len(posts) == 1 and waits == [] and isinstance(res, BackendBusyError),
      f"{len(posts)} {waits} {res!r}")

posts, waits, res = drive(od, [FakeResponse(502, "Backend busy")], diff_post(b))
check("A6 502 'Backend busy' (case) → BackendBusyError",
      len(posts) == 1 and isinstance(res, BackendBusyError), repr(res))

posts, waits, res = drive(od, [FakeResponse(502, "generation failed")], diff_post(b))
check("A7 other 502: 2 POSTs, wait 2.0, RuntimeError",
      len(posts) == 2 and waits == [2.0] and is_defect(res),
      f"{len(posts)} {waits} {res!r}")

# ── [B] the cooldown decision in run_on_backend ─────────────────────────
print("\n[B] BackendPool.run_on_backend")
b = diffusion_backend()
pool = BackendPool([b], agent_instances_provider=lambda _n: {})
posts, waits, res = drive(od, [R503()],
                          lambda: pool.run_on_backend(
                              b, lambda be: be._post_gateway("generations", json={})))
check("B1 503 without header → RuntimeError", is_defect(res), repr(res))
check("B1 backend on cooldown (available False)", b.available is False,
      str(b.runtime_status()))

b = diffusion_backend()
pool = BackendPool([b], agent_instances_provider=lambda _n: {})
posts, waits, res = drive(od, [R503RA(1)],
                          lambda: pool.run_on_backend(
                              b, lambda be: be._post_gateway("generations", json={})))
check("B2 503 with Retry-After → BackendBusyError", isinstance(res, BackendBusyError),
      repr(res))
check("B2 no cooldown (available True)", b.available is True, str(b.runtime_status()))


# ── [C] _gateway_job.submit_job ─────────────────────────────────────────
class _JobBackend:
    name = "gw-job"
    timeout = 1

    def _headers(self):
        return {}


def submit():
    return gj.submit_job(_JobBackend(), "http://gw.invalid/v1/generations",
                         {"model": "m"}, "Video")


print("\n[C] _gateway_job.submit_job")
posts, waits, res = drive(gj, [R503()], submit)
check("C1 503 without header: 4 POSTs, waits [2, 8, 20], RuntimeError",
      len(posts) == 4 and waits == FLAP and is_defect(res),
      f"{len(posts)} {waits} {res!r}")
posts, waits, res = drive(gj, [R503(), FakeResponse(202, payload={"job_id": "j1"})],
                          submit)
check("C2 flap then 202: job id j1", res == "j1" and waits == [2.0],
      f"{res!r} {waits}")
posts, waits, res = drive(gj, [R503RA(5)], submit)
check("C3 503 Retry-After: 3 POSTs, waits [5,5], BackendBusyError",
      len(posts) == 3 and waits == [5.0, 5.0] and isinstance(res, BackendBusyError),
      f"{len(posts)} {waits} {res!r}")
posts, waits, res = drive(gj, [FakeResponse(429, "slow down")], submit)
check("C4 429 unchanged: 3 POSTs, waits [10,10], BackendBusyError",
      len(posts) == 3 and waits == [10.0, 10.0] and isinstance(res, BackendBusyError),
      f"{len(posts)} {waits} {res!r}")
posts, waits, res = drive(gj, [FakeResponse(502, "park timeout")], submit)
check("C5 502 park timeout: BackendBusyError",
      len(posts) == 1 and isinstance(res, BackendBusyError), repr(res))


def poll_failed(error_text):
    gets = []

    def _get(url, **_kw):
        gets.append(url)
        return FakeResponse(200, payload={"status": "failed", "error": error_text})

    real_get, real_sleep = gj.requests.get, gj.time.sleep
    gj.requests.get = _get
    gj.time.sleep = lambda _s: None
    try:
        return gj.poll_job(_JobBackend(), "j1", max_wait=60, max_queue_wait=60,
                           poll_interval=0, on_done=lambda sd, t: [b"x"])
    except Exception as e:  # noqa: BLE001 — the raised error IS the result
        return e
    finally:
        gj.requests.get, gj.time.sleep = real_get, real_sleep


_JobBackend.api_url = "http://gw.invalid"
res = poll_failed("park timeout after 600s")
check("C6 failed job on park timeout → BackendBusyError",
      isinstance(res, BackendBusyError), repr(res))
res = poll_failed("CUDA out of memory")
check("C6 failed job on a real error → [] (defect)", res == [], repr(res))


def poll_lost(get_answer, cancel_raises=False):
    """poll_job against a gateway whose GET answers ``get_answer()`` (a
    response, or an exception to raise); returns (gets, cancel posts, result)."""
    gets, posts = [], []

    def _get(url, **_kw):
        gets.append(url)
        ans = get_answer()
        if isinstance(ans, Exception):
            raise ans
        return ans

    def _post(url, **_kw):
        posts.append(url)
        if cancel_raises:
            raise requests.exceptions.ConnectionError("gateway gone")
        return FakeResponse(200)

    real = gj.requests.get, gj.requests.post, gj.time.sleep
    gj.requests.get, gj.requests.post = _get, _post
    gj.time.sleep = lambda _s: None
    try:
        res = gj.poll_job(_JobBackend(), "j1", max_wait=60, max_queue_wait=60,
                          poll_interval=0, on_done=lambda sd, t: [b"x"])
    except Exception as e:  # noqa: BLE001 — the raised error IS the result
        res = e
    finally:
        gj.requests.get, gj.requests.post, gj.time.sleep = real
    return gets, posts, res


CANCEL = ["http://gw.invalid/v1/jobs/j1/cancel"]
gets, posts, res = poll_lost(lambda: FakeResponse(404))
check("C7a 3x404: 3 GETs, [], one cancel POST",
      len(gets) == 3 and res == [] and posts == CANCEL,
      f"{len(gets)} {res!r} {posts}")
gets, posts, res = poll_lost(lambda: FakeResponse(500))
check("C7b 11x500: 11 GETs, [], one cancel POST",
      len(gets) == 11 and res == [] and posts == CANCEL,
      f"{len(gets)} {res!r} {posts}")
gets, posts, res = poll_lost(
    lambda: requests.exceptions.ConnectionError("reset"))
check("C7c 11 poll exceptions: 11 GETs, [], one cancel POST",
      len(gets) == 11 and res == [] and posts == CANCEL,
      f"{len(gets)} {res!r} {posts}")
gets, posts, res = poll_lost(lambda: FakeResponse(404), cancel_raises=True)
check("C7d a failing cancel never raises: []",
      res == [] and posts == CANCEL, f"{res!r} {posts}")
gets, posts, res = poll_lost(
    lambda: FakeResponse(200, payload={"status": "failed", "error": "CUDA out of memory"}))
check("C7e a failed job is not cancelled", res == [] and posts == [],
      f"{res!r} {posts}")

# ── [D] localai_video ───────────────────────────────────────────────────
print("\n[D] localai_video _generate")
lv = lv_mod.LocalAIVideoBackend("lv", "http://gw.invalid", 1.0, "P1SMOKE_LV_", model="m")
lv_params = {"source_image_path": "data:image/png;base64,iVBORw0KGgo="}
gen_lv = lambda: lv._generate("p", "", lv_params)  # noqa: E731
posts, waits, res = drive(lv_mod, [R503()], gen_lv)
check("D1 503 without header: 4 POSTs, waits [2, 8, 20], RuntimeError",
      len(posts) == 4 and waits == FLAP and is_defect(res),
      f"{len(posts)} {waits} {res!r}")
posts, waits, res = drive(lv_mod, [R503RA(3)], gen_lv)
check("D2 503 Retry-After: 1 POST, BackendBusyError",
      len(posts) == 1 and isinstance(res, BackendBusyError), f"{len(posts)} {res!r}")
posts, waits, res = drive(lv_mod, [FakeResponse(502, "park timeout")], gen_lv)
check("D3 502 park timeout: BackendBusyError", isinstance(res, BackendBusyError), repr(res))

# ── [E] openai_chat ─────────────────────────────────────────────────────
print("\n[E] openai_chat _generate")
chat = chat_mod.OpenAIChatImageBackend("chat", "http://gw.invalid", 1.0, "P1SMOKE_CH_",
                                       api_key="k", model="m")
gen_chat = lambda: chat._generate("p", "", {})  # noqa: E731
posts, waits, res = drive(chat_mod, [R503()], gen_chat)
check("E1 503 without header: 4 POSTs, waits [2, 8, 20], RuntimeError",
      len(posts) == 4 and waits == FLAP and is_defect(res),
      f"{len(posts)} {waits} {res!r}")
posts, waits, res = drive(chat_mod, [R503RA(3)], gen_chat)
check("E2 503 Retry-After: 1 POST, BackendBusyError",
      len(posts) == 1 and isinstance(res, BackendBusyError), f"{len(posts)} {res!r}")
posts, waits, res = drive(chat_mod, [FakeResponse(502, "park timeout")], gen_chat)
check("E3 502 park timeout: BackendBusyError", isinstance(res, BackendBusyError), repr(res))


print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
