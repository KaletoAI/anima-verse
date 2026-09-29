#!/usr/bin/env python3
"""Smoke run for the gateway 503/502 mapping and the soft-glob transition
(plan-befundrunde-2026-09-29 B2, incl. the binding review notes).

Usage:  ./.venv/bin/python scripts/smoke_gateway_503_mapping.py

No server, no network, no world DB: ``paths.init`` points at a throwaway
directory BEFORE any app import, ``requests.post`` / ``time.sleep`` of each
backend module are replaced by recorders, and the soft-glob part runs a bare
``ImageService`` over stub backends whose ``_generate`` only counts calls.

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
[D] localai_video ``_generate``:
    D1 503 (no header), always   → 4 POSTs, waits [2, 8, 20], RuntimeError
    D2 503 Retry-After: 3        → 1 POST, BackendBusyError
    D3 502 "park timeout"        → BackendBusyError
[E] openai_chat ``_generate``:
    E1 503 (no header), always   → 4 POSTs, waits [2, 8, 20], RuntimeError
    E2 503 Retry-After: 3        → 1 POST, BackendBusyError
    E3 502 "park timeout"        → BackendBusyError
[F] ``BackendPool.matches_configured`` over GW-A, GW-B (both cooling down),
    OFF-1 (instance disabled), Cloud (available); character "Alice" has GW-B
    switched off:
    F1 "GW-*"                    → True  (configured, merely unavailable)
    F2 "GW-B" for Alice          → False (character-disabled does not count)
    F3 "GW-B" for nobody         → True
    F4 "OFF-*"                   → False (instance-disabled does not count)
    F5 "Nope*"                   → False
    F6 "gw-a" (case)             → True  (the glob matches lowercased, like
                                          match_backend)
[G] ``ImageService.generate_from_input`` soft globs:
    G1 render match "GW-*" (both cooling)  → returns
       "Error: GW-* matches only unavailable backends (offline or cooling
       down)."; the default selection is NOT asked; no backend's _generate ran
    G2 the same through the CHARACTER match (profile outfit_imagegen.workflow)
    G3 "OFF-*" (only disabled)             → default selection asked (today's
       fallback)
    G4 "GW-B" for Alice (character-disabled) → default selection asked
    G5 "Nope*" (no backend)                 → default selection asked
   (The recorder for the default selection returns None, so G3–G5 end in
    "Error: No image generation backend is available right now." — the
    fallback being ASKED is the assertion.)
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
from app.imagegen import service as svc_mod  # noqa: E402
from app.imagegen.base import BackendBusyError, ImageBackend  # noqa: E402
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


# ── [F] matches_configured ──────────────────────────────────────────────
class StubBackend(ImageBackend):
    def __init__(self, name, *, enabled=True, available=True, cost=0.0):
        super().__init__(name, "http://stub.invalid", cost, "stub",
                         f"P1SMOKE_{name.replace('-', '_')}_")
        self.instance_enabled = enabled
        self.available = available
        self.generate_calls = 0

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        self.generate_calls += 1
        return [b"img"]


def build_pool():
    gw_a, gw_b = StubBackend("GW-A"), StubBackend("GW-B")
    gw_a.mark_unhealthy("smoke", 300.0)
    gw_b.mark_unhealthy("smoke", 300.0)
    off = StubBackend("OFF-1", enabled=False)
    cloud = StubBackend("Cloud", cost=5.0)
    agent_flags = {"Alice": {"GW-B": {"enabled": False}}}
    pool = BackendPool([gw_a, gw_b, off, cloud],
                       agent_instances_provider=lambda n: agent_flags.get(n, {}))
    return pool, [gw_a, gw_b, off, cloud]


print("\n[F] BackendPool.matches_configured")
pool, _all = build_pool()
check("F1 'GW-*' → True", pool.matches_configured("GW-*") is True)
check("F2 'GW-B' for Alice → False",
      pool.matches_configured("GW-B", character_name="Alice") is False)
check("F3 'GW-B' → True", pool.matches_configured("GW-B") is True)
check("F4 'OFF-*' → False", pool.matches_configured("OFF-*") is False)
check("F5 'Nope*' → False", pool.matches_configured("Nope*") is False)
check("F6 'gw-a' → True", pool.matches_configured("gw-a") is True)


# ── [G] generate_from_input soft globs ──────────────────────────────────
def build_service():
    import threading
    svc = svc_mod.ImageService.__new__(svc_mod.ImageService)
    svc.config = {}
    svc.enabled = True
    svc.last_enhanced_prompt = ""
    svc._meta_tls = threading.local()
    pool, backends = build_pool()
    svc._pool = pool
    fallback_calls = []

    def _fallback(character_name, has_input_image=False):
        fallback_calls.append(character_name)
        return None
    svc._wait_for_backend = _fallback
    return svc, backends, fallback_calls


PROFILES = {}
_real_profile = svc_mod.get_character_profile
_real_has_ref = svc_mod.render_has_reference_image
svc_mod.get_character_profile = lambda name: PROFILES.get(name, {})
svc_mod.render_has_reference_image = lambda *_a, **_k: False
try:
    print("\n[G] generate_from_input soft globs")
    svc, backends, fb = build_service()
    out = svc.generate_from_input(json.dumps(
        {"prompt": "a harbour", "agent_name": "Bob", "workflow": "GW-*"}))
    check("G1 render match on cooling backends → the error string",
          out == "Error: GW-* matches only unavailable backends "
                 "(offline or cooling down).", out)
    check("G1 default selection not asked", fb == [], str(fb))
    check("G1 no backend generated", sum(x.generate_calls for x in backends) == 0)

    svc, backends, fb = build_service()
    PROFILES["Bob"] = {"outfit_imagegen": {"workflow": "GW-*"}}
    out = svc.generate_from_input(json.dumps({"prompt": "a harbour", "agent_name": "Bob"}))
    check("G2 character match on cooling backends → the error string",
          out.startswith("Error: GW-* matches only unavailable backends"), out)
    check("G2 default selection not asked", fb == [], str(fb))
    PROFILES.clear()

    svc, backends, fb = build_service()
    out = svc.generate_from_input(json.dumps(
        {"prompt": "a harbour", "agent_name": "Bob", "workflow": "OFF-*"}))
    check("G3 only-disabled glob falls back", fb == ["Bob"], f"{fb} {out}")
    check("G3 ends in the no-backend error (fallback stub returned None)",
          out == "Error: No image generation backend is available right now.", out)

    svc, backends, fb = build_service()
    out = svc.generate_from_input(json.dumps(
        {"prompt": "a harbour", "agent_name": "Alice", "workflow": "GW-B"}))
    check("G4 character-disabled glob falls back", fb == ["Alice"], f"{fb} {out}")

    svc, backends, fb = build_service()
    out = svc.generate_from_input(json.dumps(
        {"prompt": "a harbour", "agent_name": "Bob", "workflow": "Nope*"}))
    check("G5 glob without any backend falls back", fb == ["Bob"], f"{fb} {out}")
finally:
    svc_mod.get_character_profile = _real_profile
    svc_mod.render_has_reference_image = _real_has_ref

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
