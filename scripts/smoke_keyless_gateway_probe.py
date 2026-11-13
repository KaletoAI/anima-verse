"""Usage: ./.venv/bin/python scripts/smoke_keyless_gateway_probe.py

A gateway backend without an API key is never probed: the AI hub answers
every keyless request with 401, and an empty test instance (every smoke that
builds the image service) used to send one probe per seeded alias — 9x
GET /v1/models + 1x GET /v1/generations/<alias>/schema per service start —
into the hub's call log (quartermaster report 2026-11-13).

[1] openai_mesh, api_key "" -> check_availability() False, requests.get
    never called, backend unavailable.
[2] openai_upscale, api_key "" -> the same.
[3] openai_mesh WITH a key -> requests.get IS called once with
    "Authorization: Bearer k" (the probe still runs when it can succeed).
Fails on ecf8222f: [1] and [2] call requests.get.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp(prefix="keyless-probe-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)

import requests  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        fails.append(label)


class _Resp:
    status_code = 200

    def json(self):
        return {"data": []}

    def raise_for_status(self):
        return None


calls = []


def fake_get(url, headers=None, timeout=None, **kw):
    calls.append((url, dict(headers or {})))
    return _Resp()


requests.get = fake_get

from app.imagegen.backends.openai_mesh import OpenAIMeshBackend  # noqa: E402
from app.imagegen.backends.openai_upscale import OpenAIUpscaleBackend  # noqa: E402


def mesh(key):
    os.environ["KP_MESH_MODEL"] = "Trellis2-Low"
    os.environ["KP_MESH_API_KEY"] = key
    b = OpenAIMeshBackend("Mesh", "http://gateway.invalid:4000", 1, "KP_MESH_")
    b.model, b.api_key = "Trellis2-Low", key
    return b


def upscale(key):
    os.environ["KP_UP_MODEL"] = "Iris-3B-Upscale"
    os.environ["KP_UP_API_KEY"] = key
    b = OpenAIUpscaleBackend("Up", "http://gateway.invalid:4000", 1, "KP_UP_")
    b.model, b.api_key = "Iris-3B-Upscale", key
    return b


print("[1] keyless mesh")
calls.clear()
b = mesh("")
check("available", b.check_availability(), False)
check("no request", len(calls), 0)
print("[2] keyless upscale")
calls.clear()
b = upscale("")
check("available", b.check_availability(), False)
check("no request", len(calls), 0)
print("[3] mesh with a key")
calls.clear()
b = mesh("k")
b.check_availability()
check("first request is /v1/models with the bearer",
      calls[0] if calls else None, ("http://gateway.invalid:4000/v1/models", {"Authorization": "Bearer k"}))

print("FAILED: " + ", ".join(fails) if fails else "OK — keyless gateway backends are not probed")
sys.exit(1 if fails else 0)
