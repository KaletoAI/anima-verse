#!/usr/bin/env python3
"""Smoke: the string façade of the image service (generate_from_input) after
the service split (plan-image-routing.md, review notes "Service-Teilung").

Usage:  ./.venv/bin/python scripts/smoke_image_service_facade.py

`generate_on_backend` (one backend, typed errors) is replaced on the instance
by a fake that goes through the REAL `run_on_backend` — so a failing backend
cools down and raises BackendFailedError exactly like in production — and
returns a GenerationResult. Chain rules / character spec / switches come in
through the routing test seams. Throwaway storage, no server.

Fakes: A (cost 1) fails with HTTP 500, B (cost 2) renders, Busy (cost 1)
raises BackendBusyError, Cool (cost 0) is in cooldown.

EXPECTED (by hand):
 F1 {"prompt","agent_name":"C"} (no occasion, no backend) -> routed as
    "photo"; rules photo ["A","B"] -> A fails, B renders; the answer is B's
    text; the returned meta dict (== last_image_meta) now holds
    routing {"occasion":"photo","position":2,"spec":"B"} and fallback_from
    {"occasion":"photo","intended_spec":"A","position":1}; the gallery meta
    writer got exactly those two keys for C / "f.png".
 F2 "backend":"B" -> generate_on_backend(B, explicit=True) once, no routing
    keys written, no other backend asked.
 F3 "backend":"Cool" (cooling down) -> "Error: backend 'Cool' is not
    available (disabled, offline, or cooling down)." and NO render call.
 F4 "occasion":"mesh_low" -> "Error: unknown image occasion 'mesh_low'"
 F5 rules photo ["Cool"] -> "Error: no backend available for photo: Cool
    (cooling down)", no render call (no slide onto A/B).
 F6 rules photo ["Busy","B"] -> starts with "Error: the image backend is busy",
    calls [Busy] only.
 F7 "occasion":"profile" with rules only for profile ["B"] -> rendered on B.
 F8 _parse_input keeps occasion + loras_explicit, drops workflow.
 F9 empty prompt -> "Error: No image description given.";
    no agent -> "Error: Character name missing for storing the image."
 F10 media switch off -> "Error: Media generation is disabled for this world"
 F11 matches_configured is gone from BackendPool and ImageService; the
    façade source no longer reads a "workflow" payload key.
 F12 a stored model_override survives only on the character's own match:
    character spec "B" -> the render on B sees model_override "m1"; character
    spec "X*" (B is a rule entry) -> model_override "".
"""
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = tempfile.mkdtemp(prefix="facade-")
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="facade-clips-")
from app.core import paths  # noqa: E402
paths.init(_TMP)
from app.core import config, db  # noqa: E402
config.load(Path(_TMP) / "config.json")
db.init_schema()

from app.imagegen import routing  # noqa: E402
from app.imagegen import service as service_mod  # noqa: E402
from app.imagegen.base import BackendBusyError, ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
import app.models.character as character_mod  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, cost):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_FACADE_")
        self.category = "img2img"
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = True

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"img"]


RULES = {}
CHAR = {"spec": ""}
routing._rules = lambda occasion: list(RULES.get(occasion, []))
routing._character_switches = lambda character: {}
routing._character_spec = lambda occ_def, character: (
    CHAR["spec"] if character and occ_def.get("character_scoped") else "")
service_mod.render_has_reference_image = lambda *a, **k: False
META_WRITES = []
character_mod.add_character_image_metadata = (
    lambda ch, fn, meta: META_WRITES.append((ch, fn, dict(meta))))

svc = service_mod.ImageService()
svc.enabled = True
service_mod._service = svc          # get_image_service() answers with this one
CALLS = []


def fresh_pool():
    fakes = [Fake("A", 1), Fake("B", 2), Fake("Busy", 1), Fake("Cool", 0)]
    fakes[3].mark_unhealthy("smoke", 300)
    svc._pool = BackendPool(fakes, agent_instances_provider=lambda n: {})
    CALLS.clear()
    META_WRITES.clear()


def fake_gob(backend, input_data, *, explicit):
    CALLS.append((backend.name, explicit, input_data.get("model_override", "")))

    def op(b):
        if b.name == "A":
            raise RuntimeError("HTTP 500: gone")
        if b.name == "Busy":
            raise BackendBusyError("busy")
        return [b"img"]

    svc.pool.run_on_backend(backend, op)
    meta = {"backend": backend.name}
    svc._meta_tls.last_image_meta = meta
    return service_mod.GenerationResult(text=f"done on {backend.name}", meta=meta,
                                        gallery_character="C", files=["f.png"])


svc.generate_on_backend = fake_gob


def gen(**payload):
    payload.setdefault("prompt", "a photo")
    payload.setdefault("agent_name", "C")
    return svc.generate_from_input(json.dumps(payload))


fresh_pool()
RULES = {"photo": ["A", "B"]}
check("F1 answer", gen(), "done on B")
meta = svc._meta_tls.last_image_meta
check("F1 routing", meta.get("routing"), {"occasion": "photo", "position": 2, "spec": "B"})
check("F1 fallback_from", meta.get("fallback_from"),
      {"occasion": "photo", "intended_spec": "A", "position": 1})
check("F1 gallery meta write", META_WRITES,
      [("C", "f.png", {"routing": meta["routing"], "fallback_from": meta["fallback_from"]})])

fresh_pool()
check("F2 explicit", gen(backend="B"), "done on B")
check("F2 one explicit call", CALLS, [("B", True, "")])
check("F2 no routing written", META_WRITES, [])

fresh_pool()
check("F3 explicit unavailable", gen(backend="Cool"),
      "Error: backend 'Cool' is not available (disabled, offline, or cooling down).")
check("F3 no render", CALLS, [])

fresh_pool()
check("F4 unknown occasion", gen(occasion="mesh_low"), "Error: unknown image occasion 'mesh_low'")

fresh_pool()
RULES = {"photo": ["Cool"]}
check("F5 chain dead", gen(), "Error: no backend available for photo: Cool (cooling down)")
check("F5 no render", CALLS, [])

fresh_pool()
RULES = {"photo": ["Busy", "B"]}
res = gen()
check("F6 busy text", res.startswith("Error: the image backend is busy"), True)
check("F6 no re-run", [c[0] for c in CALLS], ["Busy"])

fresh_pool()
RULES = {"profile": ["B"]}
check("F7 occasion passes", gen(occasion="profile"), "done on B")

parsed = svc._parse_input(json.dumps({"prompt": "x", "occasion": "frame",
                                      "workflow": "Z*", "loras_explicit": True}))
check("F8 whitelist", (parsed.get("occasion"), "workflow" in parsed,
                       parsed.get("loras_explicit")), ("frame", False, True))

check("F9 empty prompt", gen(prompt=""), "Error: No image description given.")
check("F9 no agent", gen(agent_name=""), "Error: Character name missing for storing the image.")

_real_switch = service_mod.media_generation_enabled
service_mod.media_generation_enabled = lambda: False
check("F10 master switch", gen(), "Error: Media generation is disabled for this world")
service_mod.media_generation_enabled = _real_switch

check("F11 pool helper gone", hasattr(BackendPool, "matches_configured"), False)
check("F11 service helper gone", hasattr(service_mod.ImageService, "matches_configured"), False)
check("F11 no workflow read", 'get("workflow"' in inspect.getsource(
    service_mod.ImageService.generate_from_input), False)

fresh_pool()
RULES = {"photo": []}
CHAR["spec"] = "B"
gen(model_override="m1")
check("F12 own match keeps the model", CALLS[-1], ("B", False, "m1"))
fresh_pool()
RULES = {"photo": ["B"]}
CHAR["spec"] = "X*"
gen(model_override="m1")
check("F12 rule entry drops it", CALLS[-1], ("B", False, ""))
CHAR["spec"] = ""

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("all checks passed")
