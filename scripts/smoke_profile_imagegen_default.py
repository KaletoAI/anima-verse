#!/usr/bin/env python3
"""Smoke run for the profile-image render occasion (image routing, R2a).

Throwaway storage, throwaway world DB — no server, no real world is touched.
NOTHING is generated: the image service is replaced by a stub that records the
payload `generate_from_input` is handed — the consumer of this rule.

THE RULE, by hand (development_instructions/plan-image-routing.md § 1 + review):
a portrait is the "profile" occasion. The backend is resolved INSIDE the
service by the image routing (the character's own match
`profile.outfit_imagegen.workflow` is position 0, then the profile chain), so
the caller writes only `occasion` — never a `workflow` glob, never a config
default. Only an explicit dialog pick reaches `backend` (hard, no fallback).

  [1] no request pick -> payload occasion "profile", backend "", no
      "workflow" key — on BOTH entry points (route core and the NPC asset job).
  [2] a character override "Krea*" does not change the payload (it is
      position 0 of the routing, applied in the service).
  [3] request backend "Qwen-Exact" -> backend "Qwen-Exact", occasion "profile".
  [4] a request "workflow" glob is ignored (no such field any more).
  [5] character_ops.resolve_profile_imagegen is gone, and npc_assets does not
      import it.

THE LoRA RULE of the variant / model-ref render (`expression_regen.
generate_expression_image`, coordinator ruling F2 on Task 11): the
character's `outfit_imagegen.tpose_loras` REPLACE its normal `loras` exactly
when the render is the "tpose" OCCASION — the same key the routing uses to
pick the character's `tpose_workflow` backend, so backend and LoRAs agree.
The occasion is the explicit `occasion=` argument, else "tpose" for a T-pose
use case, else "expression". The character below has NORMAL = [normal] and
TPOSE = [turnaround], no worn pieces (so no slot LoRAs are merged in):

  [6] use case "outfit" + occasion "tpose" (the default-pose ref as
      model_refs sends it) -> payload occasion "tpose", loras == TPOSE.
      (At 7f386576 the choice keyed on the use case, so this got NORMAL.)
      use case "outfit", no occasion -> "expression", loras == NORMAL — the
      same use case, only the occasion differs.
      use case "expression", no occasion -> "expression", loras == NORMAL.
      use case "tpose", no occasion -> "tpose", loras == TPOSE.

Usage:  ./.venv/bin/python scripts/smoke_profile_imagegen_default.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="profileimg-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="profileimg-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
CONFIG_PATH = STORAGE / "config.json"
config.load(CONFIG_PATH)
db.init_schema()

from app.core import character_ops, npc_assets as na  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
from app.core import expression_regen  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the image-service stub ──────────────────────────────────────────────────

class FakeImageService:
    """Records the payload instead of rendering. `enabled` is all the callers ask."""

    enabled = True

    def __init__(self):
        self.inputs = []

    def generate_from_input(self, input_data: str) -> str:
        payload = json.loads(input_data)
        self.inputs.append(payload)
        return f"/characters/{payload['agent_name']}/images/face.png"


SERVICE = FakeImageService()
imagegen_service.get_image_service = lambda: SERVICE


class FakeRequest:
    """The one thing `generate_profile_image_core` uses of a Request."""

    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


# ── helpers ─────────────────────────────────────────────────────────────────

def set_char_override(name: str, glob: str) -> None:
    """Set (or CLEAR) the per-character render override.

    Clearing means writing an empty glob, not dropping the key:
    `outfit_imagegen` is a per-character CONFIG key
    (`character._CONFIG_KEYS_IN_PROFILE`) and its config_json is MERGED on
    save, so a popped key survives. Emptying the field is also exactly what
    the character editor writes.
    """
    profile = get_character_profile(name) or {}
    profile["outfit_imagegen"] = {"workflow": glob}
    save_character_profile(name, profile)


def _target(payload: dict) -> dict:
    return {"occasion": payload.get("occasion", ""), "backend": payload.get("backend", ""),
            "has_workflow": "workflow" in payload}


def route_target(name: str, **request_data) -> dict:
    SERVICE.inputs.clear()
    asyncio.run(character_ops.generate_profile_image_core(
        name, FakeRequest(dict(request_data))))
    return _target(SERVICE.inputs[-1])


def job_target(name: str) -> dict:
    SERVICE.inputs.clear()
    na._render_profile_image(name)
    return _target(SERVICE.inputs[-1])


# The NPC is created through the REAL apply path, gate off — this smoke is
# about the render target, not about the placement gate.
cfg = config.get_all()
cfg.setdefault("npc", {})["require_assets"] = False
config.save(cfg, CONFIG_PATH)
config.load(CONFIG_PATH)

NPC = "Torvald"
apply_npc({"character_name": NPC,
           "character_appearance": "a weathered farmhand",
           "face_appearance": "a broad face, grey stubble",
           "outfit_description": "a grey linen apron",
           "standing_task": "sweeping the yard"},
          "", template="npc-temporary",
          created_by="smoke_profile_imagegen_default")

ROUTED = {"occasion": "profile", "backend": "", "has_workflow": False}

print("[1] no pick — routed as 'profile'")
set_char_override(NPC, "")
check("route core", route_target(NPC), ROUTED)
check("asset job", job_target(NPC), ROUTED)

print("[2] the character override stays out of the payload")
set_char_override(NPC, "Krea*")
check("route core", route_target(NPC), ROUTED)
check("asset job", job_target(NPC), ROUTED)

print("[3] an explicit pick is hard")
check("route core", route_target(NPC, backend="Qwen-Exact"),
      {"occasion": "profile", "backend": "Qwen-Exact", "has_workflow": False})

print("[4] a request workflow glob is ignored")
check("route core", route_target(NPC, workflow="SD15*"), ROUTED)

print("[5] the old resolver is gone")
check("character_ops.resolve_profile_imagegen",
      hasattr(character_ops, "resolve_profile_imagegen"), False)
check("npc_assets does not import it",
      "resolve_profile_imagegen" in Path(na.__file__).read_text(encoding="utf-8"), False)

print("[6] the variant render picks its LoRAs by occasion")
LORA_CHAR = "Solveig"
NORMAL = [{"name": "normal.safetensors", "strength": 0.8}]
TPOSE = [{"name": "turnaround.safetensors", "strength": 1.0}]
save_character_profile(LORA_CHAR, {
    "name": LORA_CHAR,
    "character_appearance": "woman, 30s, braided hair",
    "outfit_imagegen": {"workflow": "", "loras": NORMAL, "tpose_loras": TPOSE},
}, create_new=True)
REF_DIR = Path(tempfile.mkdtemp(prefix="profileimg-refs-"))


def variant_payload(use_case: str, occasion: str = "") -> dict:
    SERVICE.inputs.clear()
    expression_regen.generate_expression_image(
        LORA_CHAR, mood="", pose_key="", equipped_pieces={}, equipped_items=[],
        image_use_case=use_case, occasion=occasion,
        output_stem=REF_DIR / f"{use_case}_{occasion or 'none'}")
    p = SERVICE.inputs[-1]
    return {"occasion": p.get("occasion", ""), "loras": p.get("loras")}


check("outfit + occasion tpose", variant_payload("outfit", "tpose"),
      {"occasion": "tpose", "loras": TPOSE})
check("outfit, no occasion", variant_payload("outfit"),
      {"occasion": "expression", "loras": NORMAL})
check("expression, no occasion", variant_payload("expression"),
      {"occasion": "expression", "loras": NORMAL})
check("tpose, no occasion", variant_payload("tpose"),
      {"occasion": "tpose", "loras": TPOSE})

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
