#!/usr/bin/env python3
"""Smoke run for the server-side LoRA gate (finding IMG-6).

Runs against a THROWAWAY storage directory with a STUBBED LoRA library — no
image backend is contacted, nothing is rendered.

The rule (CLAUDE.md, plan-lora-library.md): every LoRA dropdown is scoped to
the SELECTED backend, and the server rejects a pick the library does not
associate with the backend the render resolved to. Entries whose LoRA the
sync flagged "(missing)" stay offered and MAY still generate. Until this fix
the gate existed only on the location-image path (``world_ops``); the
profile-image, character-image and video paths passed the dialog's selection
through unchecked.

The gate has TWO halves, because a LoRA list reaches a render from two very
different places:

* an EXPLICIT pick of the current request (payload flag ``loras_explicit``,
  set by the dialogs) is rejected hard — HTTP 400;
* STORED configuration (per-character image settings, slot LoRAs of a
  body-slot package) is FILTERED: the render runs without the unassociated
  entries and the admin is warned ONCE per (character, backend, LoRA).
  Rejecting there would turn one stale config value into a permanently
  broken expression/outfit pipeline for that character.

Expected values, derived by hand from ``config.get_lora_options`` and the
gate block of ``world_ops.generate_image_core``:

* an empty selection and the "None" placeholder of an unused slot pass —
  ``get_lora_options`` is never even consulted;
* a discovered entry associated with the backend passes;
* a discovered entry of ANOTHER backend is rejected (exactly the
  ``qwen_style.safetensors`` on a Flux backend scenario of the finding);
* a manual entry flagged missing on this backend passes — it is offered in
  the dialog, marked "(missing)", and the flag can be stale;
* a manual entry with ``backends: []`` ("all backends") passes, unless the
  backend's ``lora_filter`` glob excludes its name;
* the three unguarded paths are covered: ``generate_from_input`` (image,
  hard for an explicit pick / filtering for a stored one), ``generate_video``
  (animate dialog — always an explicit pick), and the profile-image route
  turns the error into HTTP 400 rather than a 500 "Bildgenerierung
  fehlgeschlagen";
* a filtered render keeps the associated entries in their original order and
  drops only the foreign ones, and a SECOND identical render logs nothing
  (``warn_dropped_loras`` remembers (subject, backend, name)).

Usage:  ./.venv/bin/python scripts/smoke_lora_gate.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="lora-gate-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

import asyncio  # noqa: E402
import json  # noqa: E402

import app.core.config as cfg  # noqa: E402
import app.core.lora_library as lib  # noqa: E402
from app.core.lora_library import (LoraNotAllowedError,  # noqa: E402
                                   assert_loras_allowed, filter_allowed_loras,
                                   unassociated_loras, warn_dropped_loras)

FAILURES = []
CHECKED = 0

LIBRARY = [
    # discovered → carries its backends
    {"lora": "flux_style.safetensors", "source": "discovered",
     "backends": ["flux-backend"], "missing_on": []},
    {"lora": "qwen_style.safetensors", "source": "discovered",
     "backends": ["qwen-backend"], "missing_on": []},
    # manual, associated but currently not reported by the backend
    {"lora": "flux_manual.safetensors", "source": "manual",
     "backends": ["flux-backend"], "missing_on": ["flux-backend"]},
    # manual "all backends"
    {"lora": "everywhere.safetensors", "source": "manual",
     "backends": [], "missing_on": []},
    # video alias
    {"lora": "motion_smooth.safetensors", "source": "discovered",
     "backends": ["video-backend"], "missing_on": []},
]


class FakeBackend:
    def __init__(self, name, lora_filter="", api_type="openai_diffusion"):
        self.name = name
        self.lora_filter = lora_filter
        self.api_type = api_type


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def rejects(fn) -> list:
    """Runs fn and returns the rejected names, or [] when it did not raise."""
    try:
        fn()
    except LoraNotAllowedError as e:
        return e.names
    return []


def main() -> int:
    _real_get = cfg.get
    cfg.get = lambda key, default=None: (
        LIBRARY if key == "image_generation.lora_triggers" else _real_get(key, default))

    flux = FakeBackend("flux-backend")
    filtered = FakeBackend("flux-filtered", lora_filter="flux*")
    video = FakeBackend("video-backend", api_type="openai_video")

    print("\n[1] the rule")
    cases = [
        ("empty selection passes", flux, None, []),
        ("an empty list passes", flux, [], []),
        ("the 'None' placeholder passes", flux, [{"name": "None"}], []),
        ("an associated pick passes", flux,
         [{"name": "flux_style.safetensors", "strength": 0.8}], []),
        ("a pick of ANOTHER backend is rejected", flux,
         [{"name": "qwen_style.safetensors"}], ["qwen_style.safetensors"]),
        ("a manual entry marked missing still passes", flux,
         [{"name": "flux_manual.safetensors"}], []),
        ("a manual 'all backends' entry passes", flux,
         [{"name": "everywhere.safetensors"}], []),
        ("… unless the backend's lora_filter excludes it", filtered,
         [{"name": "everywhere.safetensors"}], ["everywhere.safetensors"]),
        ("one good + one foreign pick → only the foreign one is named", flux,
         [{"name": "flux_style.safetensors"}, {"name": "qwen_style.safetensors"}],
         ["qwen_style.safetensors"]),
    ]
    for label, backend, loras, expected in cases:
        got = unassociated_loras(backend, loras)
        check(label, got == expected, f"{got} != {expected}" if got != expected else "")
    named = rejects(lambda: assert_loras_allowed(flux, [{"name": "qwen_style.safetensors"}]))
    check("assert_loras_allowed raises with the rejected names",
          named == ["qwen_style.safetensors"], str(named))
    check("the message names backend and LoRA",
          "flux-backend" in str(LoraNotAllowedError("flux-backend", ["x.safetensors"]))
          and "x.safetensors" in str(LoraNotAllowedError("flux-backend", ["x.safetensors"])))

    print("\n[1b] the soft half — stored LoRAs are filtered, not rejected")
    stored = [{"name": "flux_style.safetensors", "strength": 0.7},
              {"name": "qwen_style.safetensors"},
              {"name": "flux_manual.safetensors"}]
    kept, dropped = filter_allowed_loras(flux, stored)
    check("the foreign entry is dropped, the others kept in order",
          [k.get("name") for k in kept] == ["flux_style.safetensors",
                                            "flux_manual.safetensors"]
          and dropped == ["qwen_style.safetensors"],
          f"{[k.get('name') for k in kept]} / {dropped}")
    check("the kept entries are the ORIGINAL dicts (strength survives)",
          kept[0] is stored[0] and kept[0]["strength"] == 0.7)
    check("nothing to drop → the list is handed back unchanged",
          filter_allowed_loras(flux, [{"name": "flux_style.safetensors"}])
          == ([{"name": "flux_style.safetensors"}], []))
    check("an empty selection stays empty", filter_allowed_loras(flux, None)
          == ([], []))
    lib._dropped_logged.clear()
    first = warn_dropped_loras("flux-backend", ["qwen_style.safetensors"], "demo")
    second = warn_dropped_loras("flux-backend", ["qwen_style.safetensors"], "demo")
    check("warned once per (character, backend, LoRA)",
          first == ["qwen_style.safetensors"] and second == [],
          f"{first} / {second}")
    check("another character warns again",
          warn_dropped_loras("flux-backend", ["qwen_style.safetensors"],
                             "other") == ["qwen_style.safetensors"])
    check("the memo is bounded", lib._DROP_LOG_CAP <= 4096
          and len(lib._dropped_logged) == 2, str(len(lib._dropped_logged)))

    print("\n[2] the image path (generate_from_input)")
    from app.imagegen import service as svc_mod
    svc = svc_mod.ImageService.__new__(svc_mod.ImageService)
    svc.enabled = True
    svc._wait_for_explicit_backend = lambda *a, **k: flux
    svc._wait_for_backend = lambda *a, **k: flux
    svc_mod.render_has_reference_image = lambda *a, **k: False
    svc_mod.get_character_profile = lambda *a, **k: {}
    reached = []
    svc._get_instance_config = lambda *a, **k: reached.append("generated") or {}
    # Keep a handle on the parsed payload — the gate filters it IN PLACE, so
    # this is what the generation below would actually send.
    seen = []
    svc._parse_input = lambda raw: (seen.append(json.loads(raw)), seen[-1])[1]

    def _run(loras, explicit=False):
        reached.clear()
        payload = {"prompt": "a portrait", "agent_name": "demo",
                   "backend": "flux-backend", "loras": loras}
        if explicit:
            payload["loras_explicit"] = True
        return svc.generate_from_input(json.dumps(payload))

    named = rejects(lambda: _run([{"name": "qwen_style.safetensors"}],
                                 explicit=True))
    check("an EXPLICIT foreign pick is rejected before anything is generated",
          named == ["qwen_style.safetensors"] and not reached, str(named))
    named = rejects(lambda: _run([{"name": "flux_manual.safetensors"}],
                                 explicit=True))
    check("an explicit '(missing)' pick reaches the generation",
          named == [] and reached == ["generated"], str(named))
    named = rejects(lambda: _run(None))
    check("no selection reaches the generation",
          named == [] and reached == ["generated"], str(named))

    print("\n[2b] an automatic render with a STORED foreign LoRA")
    lib._dropped_logged.clear()
    warned = []
    _real_warn = lib.warn_dropped_loras
    lib.warn_dropped_loras = lambda b, d, s="": warned.append((b, tuple(d), s)) \
        or _real_warn(b, d, s)
    stored_sel = [{"name": "flux_style.safetensors", "strength": 0.6},
                  {"name": "qwen_style.safetensors"}]
    named = rejects(lambda: _run(stored_sel))
    check("the render happens instead of failing",
          named == [] and reached == ["generated"], str(named))
    check("it runs WITHOUT the unassociated LoRA",
          [l.get("name") for l in seen[-1].get("loras", [])]
          == ["flux_style.safetensors"],
          str(seen[-1].get("loras")))
    logged = _real_warn("flux-backend", ["qwen_style.safetensors"], "demo")
    check("exactly one warning was emitted for it — a repeat says nothing",
          len(warned) == 1 and warned[0][1] == ("qwen_style.safetensors",)
          and logged == [], f"{warned} / {logged}")
    named = rejects(lambda: _run([{"name": "flux_style.safetensors"}]))
    check("a stored ASSOCIATED LoRA is kept and the render runs",
          named == []
          and [l.get("name") for l in seen[-1].get("loras", [])]
          == ["flux_style.safetensors"] and reached == ["generated"],
          str(seen[-1].get("loras")))
    lib.warn_dropped_loras = _real_warn

    print("\n[3] the video path (generate_video)")
    vsvc = svc_mod.ImageService.__new__(svc_mod.ImageService)
    vsvc._wait_for_explicit_backend = lambda *a, **k: video
    rendered = []
    vsvc.run_on_backend = lambda *a, **k: (rendered.append("render"), (None, None))[1]
    named = rejects(lambda: vsvc.generate_video(
        source_image_path="x.png", action_prompt="wave", output_path="o.mp4",
        backend_glob="video-backend", loras=[{"name": "flux_style.safetensors"}]))
    check("a LoRA of an image backend is rejected on the video backend",
          named == ["flux_style.safetensors"] and not rendered, str(named))
    named = rejects(lambda: vsvc.generate_video(
        source_image_path="x.png", action_prompt="wave", output_path="o.mp4",
        backend_glob="video-backend",
        loras=[{"name": "motion_smooth.safetensors"}]))
    check("the video alias' own LoRA passes the gate and reaches the render",
          named == [] and rendered == ["render"], f"{named} {rendered}")

    print("\n[4] the profile-image route reports 400, not 500")
    from fastapi import HTTPException
    import app.core.character_ops as ops

    class _Req:
        async def json(self):
            return {"loras": [{"name": "qwen_style.safetensors"}]}

    sent = []

    class _Svc:
        enabled = True

        def generate_from_input(self, payload):
            sent.append(json.loads(payload))
            raise LoraNotAllowedError("flux-backend", ["qwen_style.safetensors"])

    ops._resolve_face_prompt = lambda *a, **k: "a face"
    ops.resolve_profile_imagegen = lambda *a, **k: {"workflow": "", "backend": ""}
    import app.models.character as char_mod
    char_mod.get_character_profile = lambda *a, **k: {"name": "demo"}
    svc_mod.get_image_service = lambda: _Svc()
    try:
        asyncio.run(ops.generate_profile_image_core("demo", _Req()))
        status, detail = 0, "no error raised"
    except HTTPException as e:
        status, detail = e.status_code, str(e.detail)
    check("HTTP 400 with the rejected LoRA in the message",
          status == 400 and "qwen_style.safetensors" in detail,
          f"{status}: {detail}")
    check("the dialog's selection is marked as an explicit pick",
          bool(sent) and sent[-1].get("loras_explicit") is True,
          str(sent[-1]) if sent else "nothing sent")

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + "; ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
