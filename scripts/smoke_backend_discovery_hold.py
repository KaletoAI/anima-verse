#!/usr/bin/env python3
"""Smoke: the availability check re-reads LoRA list / alias schema at most
every ``ImageBackend.DISCOVERY_HOLD_S`` (300 s).

Usage:
    ./.venv/bin/python scripts/smoke_backend_discovery_hold.py

No server, no world: the backends are built directly, ``requests.get`` is a
fake that counts calls per URL kind, and the monotonic clock of
``app.imagegen.base`` is a stepped fake.

Expected values, derived by hand from the rule "a SUCCESSFUL read is reused
for 300 s; a failed read retries on the next check; an unreachable endpoint
drops the hold":

LocalAI (``loras``):
  [1] t=0     check -> 1 LoRA read                      (nothing held yet)
  [2] t=0,10  two more checks -> still 1                (held)
  [3] t=299.9 check -> still 1                          (299.9 < 300)
  [4] t=300   check -> 2                                (300 >= 300, due)
  [5] t=310   /v1/models raises ConnectionError -> 2, then t=311 check -> 3
              (unreachable dropped the hold)
  [6] read 3 (t=311) is held until 611. With the LoRA endpoint answering
      500, the check at t=700 makes read 4, which fails; t=701 -> read 5
      (a failed read is not held); t=702 -> still 5 (read 5 succeeded).
  [7] an explicit fetch_loras() at t=703 reads at once -> 6.

Gateway mesh (``schema``):
  [8] t=0 check -> 1 schema read; t=100 -> 1; t=300 -> 2.
  [9] the held check keeps the slots read at t=300 (image_slots == ["input_image"]).

Gateway video (``loras`` + ``schema``):
  [10] t=0 check -> 1 LoRA + 1 schema read; t=200 -> 1 + 1; t=300 -> 2 + 2.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="discovery_hold_"))
os.environ.setdefault("INSTANCE_DIR", tempfile.mkdtemp(prefix="discovery_hold_inst_"))

import requests  # noqa: E402

from app.imagegen import base as base_mod  # noqa: E402
from app.imagegen.backends.localai import LocalAIBackend  # noqa: E402
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend  # noqa: E402
from app.imagegen.backends.openai_video import OpenAIVideoBackend  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{label}: got {got!r}, want {want!r}")
    if not ok:
        FAILS.append(label)


class Clock:
    t = 0.0

    def monotonic(self):
        return self.t

    def time(self):
        return 1_000_000.0 + self.t

    def __getattr__(self, name):          # sleep etc. from the real module
        import time as _t
        return getattr(_t, name)


clock = Clock()
base_mod.time = clock

# A recovery calls channel_health.force_poll — keep the monitor out of it.
import app.core.channel_health as ch  # noqa: E402


class _NoMonitor:
    def force_poll(self):
        pass


ch.get_monitor = lambda: _NoMonitor()


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.content = b"x"

    def json(self):
        return self._body


calls = {"loras": 0, "schema": 0}
mode = {"models": "ok", "loras": 200}


def fake_get(url, headers=None, timeout=None, **kw):
    if url.endswith("/v1/models"):
        if mode["models"] == "down":
            raise requests.ConnectionError("down")
        return Resp(200, {"data": [{"id": "m"}]})
    if url.endswith("/loras"):
        calls["loras"] += 1
        return Resp(mode["loras"], {"loras": ["a", "b"]})
    if url.endswith("/schema"):
        calls["schema"] += 1
        return Resp(200, {"images": [{"name": "input_image"}], "params": []})
    raise AssertionError(url)


requests.get = fake_get


def at(t):
    clock.t = t


# ── LocalAI: LoRAs ──────────────────────────────────────────────────────
b = LocalAIBackend("L", "http://gw", 0.0, "SMOKE_L_", model="m")
b.lora_url = "http://gw"
at(0); b.check_availability()
check("[1] first check reads the LoRAs", calls["loras"], 1)
b.check_availability(); at(10); b.check_availability()
check("[2] held within the window", calls["loras"], 1)
at(299.9); b.check_availability()
check("[3] still held at 299.9 s", calls["loras"], 1)
at(300); b.check_availability()
check("[4] due at 300 s", calls["loras"], 2)
at(310); mode["models"] = "down"; b.check_availability()
check("[5a] unreachable reads nothing", calls["loras"], 2)
at(311); mode["models"] = "ok"; b.check_availability()
check("[5b] back again -> read at once", calls["loras"], 3)
at(700); mode["loras"] = 500; b.check_availability()
check("[6a] due at 700 s, read fails", calls["loras"], 4)
at(701); mode["loras"] = 200; b.check_availability()
check("[6b] failed read is not held", calls["loras"], 5)
at(702); b.check_availability()
check("[6c] successful read held again", calls["loras"], 5)
at(703); b.fetch_loras()
check("[7] explicit fetch_loras reads at once", calls["loras"], 6)

# ── Gateway mesh: alias schema ──────────────────────────────────────────
calls.update(loras=0, schema=0)
m = OpenAIMeshBackend("M", "http://gw", 0.0, "SMOKE_M_", model="mesh")
at(0); m.check_availability()
check("[8a] first check reads the schema", calls["schema"], 1)
at(100); m.check_availability()
check("[8b] held", calls["schema"], 1)
at(300); m.check_availability()
check("[8c] due at 300 s", calls["schema"], 2)
at(301); m.check_availability()
check("[9] held check keeps the slots", list(getattr(m, "_image_slots", [])), ["input_image"])

# ── Gateway video: LoRAs + schema ───────────────────────────────────────
calls.update(loras=0, schema=0)
v = OpenAIVideoBackend("V", "http://gw", 0.0, "SMOKE_V_", model="vid")
v.lora_url = "http://gw"
at(0); v.check_availability()
check("[10a] first check reads both", (calls["loras"], calls["schema"]), (1, 1))
at(200); v.check_availability()
check("[10b] both held", (calls["loras"], calls["schema"]), (1, 1))
at(300); v.check_availability()
check("[10c] both due at 300 s", (calls["loras"], calls["schema"]), (2, 2))

print(f"{'OK' if not FAILS else 'FAILED'} smoke_backend_discovery_hold"
      + (f" ({len(FAILS)} failed: {', '.join(FAILS)})" if FAILS else ""))
sys.exit(1 if FAILS else 0)
