#!/usr/bin/env python3
"""Smoke run for the profile-image render target (plan-npc-leben, task 5).

Throwaway storage, throwaway world DB — no server, no real world is touched.
NOTHING is generated: the image service is replaced by a stub that only records
the payload `generate_from_input` is handed. That payload IS the consumer of
this feature (feedback_pruefe_am_verbraucher) — the backend choice happens
inside the service, from the `workflow`/`backend` fields the caller writes.

THE RULE, by hand — the resolution chain of `character_ops.
resolve_profile_imagegen`, the same order `expression_regen` uses for the
T-pose/expression render (`app/core/expression_regen.py`: char override ->
config default -> cheapest available):

    explicit request pick  ->  per-character override
    (`profile.outfit_imagegen.workflow`)  ->  `PROFILE_IMAGEGEN_DEFAULT`
    (config `image_generation.profile_imagegen_default`)  ->  EMPTY.

    Empty is the behaviour that existed before this field: the service's own
    `_wait_for_backend` picks the cheapest AVAILABLE backend, which in a pool
    of several cost-0 backends is an arbitrary round-robin pick — that is what
    rendered one NPC photoreal and the next one comic.

    WHICH FIELD carries the spec is part of the rule. `service.
    generate_from_input` reads `workflow` as a SOFT glob (match by name, fall
    back to the ordinary selection when nothing matches) and `backend` as a
    HARD pick that fails the render when it does not resolve. A configured
    default must never be able to fail a render, so the chain writes the glob
    into `workflow`; only an explicit request pick reaches `backend`.

Hand-derived expectations, per case of the brief:

  [1] Config default `"Flux2*"`, no character override → the payload carries
      workflow="Flux2*", backend="". BOTH entry points must show it: the
      route core (`character_ops.generate_profile_image_core`, the character
      editor's button) and the temporary-NPC asset job
      (`npc_assets._render_profile_image`) — the chain lives in ONE helper
      both call, so neither can drift.

  [2] Character override `profile.outfit_imagegen.workflow = "Krea*"` beats
      the config default → workflow="Krea*" on both paths.

  [3] Neither set → workflow="" and backend="" (the field is empty, the pool
      decides exactly as before) — for an override that was CLEARED as well as
      for a character that never carried one.

  [4] An explicit request pick wins over everything: `backend="Qwen-Exact"` in
      the request leaves workflow="" (no default injected behind the user's
      back), and an explicit request `workflow="SD15*"` likewise survives the
      character override AND the config default unchanged.

  [5] The config→env mirror: `image_generation.profile_imagegen_default` in
      config.json reaches `os.environ["PROFILE_IMAGEGEN_DEFAULT"]` on load,
      exactly like its `*_imagegen_default` siblings, and the field is in the
      admin schema (section `image_generation`, on a page, type
      `imagegen_select`) so /admin/settings renders it generically.
      NOTE: `config._set` skips empty values, so the env mirror never CLEARS a
      key — a world that empties the field again gets the empty value on the
      next process start. This smoke pops the key itself where it needs "unset".

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

from app.core import character_ops, config_schema, npc_assets as na  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
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

def set_config_default(value: str) -> None:
    """Write the field, save, reload — the load is what fills os.environ."""
    cfg = config.get_all()
    cfg.setdefault("image_generation", {})["profile_imagegen_default"] = value
    config.save(cfg, CONFIG_PATH)
    if not value:
        # `_set` skips empty values, so a reload cannot clear a stale key.
        os.environ.pop("PROFILE_IMAGEGEN_DEFAULT", None)
    config.load(CONFIG_PATH)


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


def route_target(name: str, **request_data) -> dict:
    """Run the route core once and return the render target it wrote."""
    SERVICE.inputs.clear()
    asyncio.run(character_ops.generate_profile_image_core(
        name, FakeRequest(dict(request_data))))
    payload = SERVICE.inputs[-1]
    return {"workflow": payload.get("workflow", ""),
            "backend": payload.get("backend", "")}


def job_target(name: str) -> dict:
    """Run the NPC asset job's producer once and return its render target."""
    SERVICE.inputs.clear()
    na._render_profile_image(name)
    payload = SERVICE.inputs[-1]
    return {"workflow": payload.get("workflow", ""),
            "backend": payload.get("backend", "")}


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

# ── [1] the config default reaches BOTH entry points ────────────────────────
print("[1] config default, no character override")
set_config_default("Flux2*")
set_char_override(NPC, "")
check("the route core carries the glob as a soft match",
      route_target(NPC), {"workflow": "Flux2*", "backend": ""})
check("and so does the temporary-NPC asset job",
      job_target(NPC), {"workflow": "Flux2*", "backend": ""})

# ── [2] the character override wins over the config default ─────────────────
print("[2] character override beats the config default")
set_char_override(NPC, "Krea*")
check("route core", route_target(NPC), {"workflow": "Krea*", "backend": ""})
check("asset job", job_target(NPC), {"workflow": "Krea*", "backend": ""})

# ── [3] nothing configured = the old behaviour ──────────────────────────────
print("[3] neither set — the pool decides, as before")
set_config_default("")
set_char_override(NPC, "")
check("route core, override cleared", route_target(NPC),
      {"workflow": "", "backend": ""})
check("asset job, override cleared", job_target(NPC),
      {"workflow": "", "backend": ""})
apply_npc({"character_name": "Ingeborg",
           "character_appearance": "a stooped weaver",
           "face_appearance": "a narrow face, deep-set eyes",
           "outfit_description": "a brown woollen dress",
           "standing_task": "working the loom"},
          "", template="npc-temporary",
          created_by="smoke_profile_imagegen_default")
check("and a character that never carried an override at all",
      job_target("Ingeborg"), {"workflow": "", "backend": ""})

# ── [4] an explicit request pick wins over everything ───────────────────────
print("[4] the request wins")
set_config_default("Flux2*")
set_char_override(NPC, "Krea*")
check("an explicit backend leaves the defaults out of the payload",
      route_target(NPC, backend="Qwen-Exact"),
      {"workflow": "", "backend": "Qwen-Exact"})
check("an explicit workflow glob survives override and default",
      route_target(NPC, workflow="SD15*"),
      {"workflow": "SD15*", "backend": ""})

# ── [5] config mirror + admin schema ────────────────────────────────────────
print("[5] the config field, its env mirror and the admin schema")
check("the config value reaches the env the chain reads",
      os.environ.get("PROFILE_IMAGEGEN_DEFAULT"), "Flux2*")
_ig = config_schema.get_schema()["image_generation"]
check("the admin schema knows the field as a generic imagegen_select",
      _ig["fields"].get("profile_imagegen_default", {}).get("type"),
      "imagegen_select")
check("with an English label",
      _ig["fields"].get("profile_imagegen_default", {}).get("label"),
      "Profile Image Default (Match)")
check("and it sits on a page, so the settings page renders it",
      any("profile_imagegen_default" in (p.get("fields") or [])
          for p in _ig.get("pages", [])), True)
check("the legacy-spec rewrite covers it like its siblings",
      "image_generation.profile_imagegen_default" in config.LEGACY_SPEC_FIELDS,
      True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
