#!/usr/bin/env python3
"""Smoke: the admin side of the image routing — save validator and routes.

Usage:  ./.venv/bin/python scripts/smoke_image_routing_admin.py

Spec: development_instructions/plan-image-routing.md § 6 + review notes
("_validate_image_routing: unknown occasion / a pattern that only names
backends of the wrong kind -> 400; a pattern without a match -> warning,
saveable"). Runs on a throwaway storage; no server.

Backends of the fixture config (image_generation.backends):
  Flux2 A        openai_diffusion img2img ref_slot_count 1
  Qwen Inpaint   openai_diffusion inpaint
  Flat           openai_diffusion txt2img ref_slot_count 0
  Mesh-H1        openai_mesh img2mesh mixamo
  Vid            openai_video

Expected, by hand:
 V1 {"photo": ["Flux2*"], "mesh_humanoid": ["Mesh-H*"]} -> ("", [])
 V2 {"mesh_low": ["x"]} -> error "Image routing: unknown occasion 'mesh_low'."
 V3 {"mesh_object": ["Mesh-H*"]} -> error mentions "wrong kind" and "Mesh-H1"
    (rig mixamo, the occasion needs rig none)
 V4 {"location": ["Qwen Inpaint"]} -> wrong kind (inpaint)
 V5 {"timevariant": ["Flat"]} -> wrong kind (no reference slot)
 V6 {"photo": ["Nope*"]} -> ("", ["Image routing: 'Nope*' for 'photo' matches no backend."])
 V7 {"photo": ["Flux2*", "flux2*"]} -> error "listed twice"
 V8 routing = ["x"] -> error "must be an object"
 V9 no routing key at all -> ("", [])
 V10 {"video": ["Vid"]} -> ("", []); {"photo": ["Vid"]} -> wrong kind
 V11 describe_config_backend(openai_mesh without mesh_rig) -> media "mesh",
     rig "mixamo"; (openai_video) -> media "video", ref_slot_count 1
     (OpenAIVideoBackend.DEFAULT_REF_SLOT_COUNT)
 R1 settings_image_routing_occasions() -> 19 rows
 R2 settings_image_routing_effective(character="x") hands the character to
    explain_image_routing (patched) and returns its result plus
    "media_generation_enabled" = base.media_generation_enabled() (patched to
    True -> True; to False -> False: with the world's master switch off the
    Overview shows a banner that nothing renders)
 R3 settings_save calls _validate_image_routing (source check)

settings_save end to end (config.get_all / save / env flatten / reloads
patched; the stored config is
  {"image_generation": {"backends": <fixture>, "routing": {"photo": ["Flux2*"]}}}):
 S1 payload image_generation WITHOUT a "routing" key (the admin page sends
    JSON.stringify(CONFIG); a tab loaded before the chains existed has none)
    -> the saved routing is still {"photo": ["Flux2*"]}. _merge_sensitive
    alone treats a missing key as deleted; a dropped routing would make the
    next load re-seed from the old default fields and lose every edited chain
    ("never delete by absence").
 S1b payload "routing": null -> same as missing: {"photo": ["Flux2*"]}
 S2 payload "routing": {} -> saved {} (an explicit empty object is a real
    clear, not an absence)
 S3 payload {"mesh_low": ["x"]} -> HTTP 400, detail
    "Image routing: unknown occasion 'mesh_low'.", nothing saved
 S4 payload {"photo": ["Nope*"]} -> saved; "warnings" ==
    ["Image routing: 'Nope*' for 'photo' matches no backend."]; the message
    is "Configuration saved (env updated)." (no reloads, patched) +
    " Warnings: " + that warning

A stored chain that turned invalid must not lock the admin out (fix round
1): only an EDITED chain (new occasion key, or normalised specs that differ
from the stored chain) can fail the save; an unchanged invalid stored chain
is a warning "Image routing: stored chain '<occasion>' is invalid and was
kept unchanged — <error without the 'Image routing: ' prefix>".
Fixture: backends = the five above + Mesh-O1 (openai_mesh img2mesh rig none);
stored routing {"mesh_low": ["x"], "mesh_object": ["Mesh-H*"],
"photo": ["Flux2*"]} — mesh_low is not in the catalog, Mesh-H* matches only
Mesh-H1 (rig mixamo, mesh_object needs none). In dict order:
  W_low = "Image routing: stored chain 'mesh_low' is invalid and was kept
           unchanged — unknown occasion 'mesh_low'."
  W_obj = "Image routing: stored chain 'mesh_object' is invalid and was kept
           unchanged — 'Mesh-H*' for 'mesh_object' matches only backends of
           the wrong kind (Mesh-H1)."
 F1 the same routing + an unrelated section change {"tts": {"enabled": true}}
    -> 200, warnings [W_low, W_obj], message "Configuration saved (env
    updated). Warnings: " + W_low + " " + W_obj, tts saved
 F1b the same without a routing key (stale tab) -> 200, [W_low, W_obj],
    saved routing == stored routing
 F2 mesh_object -> ["Qwen Inpaint"] (edited, still invalid) -> 400
    "Image routing: 'Qwen Inpaint' for 'mesh_object' matches only backends
    of the wrong kind (Qwen Inpaint).", nothing saved
 F3 mesh_object -> ["Mesh-O*"] (edited, valid) -> 200, warnings [W_low],
    saved mesh_object ["Mesh-O*"]
 F4 a NEW unknown key "mesh_tiny": ["x"] next to the stored ones -> 400
    "Image routing: unknown occasion 'mesh_tiny'."
 F5 mesh_object -> [" mesh-h* "] (only case/whitespace differ; normalised it
    is the stored chain) -> 200 with 2 warnings, no 400
"""
import asyncio
import copy
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = tempfile.mkdtemp(prefix="routing-admin-")
os.environ["STORAGE_DIR"] = _TMP
os.environ.setdefault("ANIMATION_CLIPS_DIR", tempfile.mkdtemp(prefix="routing-admin-clips-"))
from app.core import paths  # noqa: E402
paths.init(_TMP)
from fastapi import HTTPException  # noqa: E402
from app.routes import admin_settings as adm  # noqa: E402
from app.imagegen import routing  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


BACKENDS = [
    {"name": "Flux2 A", "api_type": "openai_diffusion", "category": "img2img", "ref_slot_count": 1},
    {"name": "Qwen Inpaint", "api_type": "openai_diffusion", "category": "inpaint"},
    {"name": "Flat", "api_type": "openai_diffusion", "category": "txt2img", "ref_slot_count": 0},
    {"name": "Mesh-H1", "api_type": "openai_mesh", "category": "img2mesh", "mesh_rig": "mixamo"},
    {"name": "Vid", "api_type": "openai_video", "category": "txt2img"},
]


def v(routing_value, with_key=True):
    ig = {"backends": BACKENDS}
    if with_key:
        ig["routing"] = routing_value
    return adm._validate_image_routing(ig)


check("V1 valid", v({"photo": ["Flux2*"], "mesh_humanoid": ["Mesh-H*"]}), ("", []))
check("V2 unknown occasion", v({"mesh_low": ["x"]})[0],
      "Image routing: unknown occasion 'mesh_low'.")
e3 = v({"mesh_object": ["Mesh-H*"]})[0]
check("V3 wrong rig", ("wrong kind" in e3, "Mesh-H1" in e3), (True, True))
check("V4 inpaint", "wrong kind" in v({"location": ["Qwen Inpaint"]})[0], True)
check("V5 no ref slot", "wrong kind" in v({"timevariant": ["Flat"]})[0], True)
check("V6 no match is a warning", v({"photo": ["Nope*"]}),
      ("", ["Image routing: 'Nope*' for 'photo' matches no backend."]))
check("V7 duplicate", "listed twice" in v({"photo": ["Flux2*", "flux2*"]})[0], True)
check("V8 not an object", "must be an object" in v(["x"])[0], True)
check("V9 no routing key", v(None, with_key=False), ("", []))
check("V10 video ok", v({"video": ["Vid"]}), ("", []))
check("V10 video on photo", "wrong kind" in v({"photo": ["Vid"]})[0], True)
k = routing.describe_config_backend({"name": "M", "api_type": "openai_mesh"})
check("V11 mesh kind", (k["media"], k["rig"]), ("mesh", "mixamo"))
k = routing.describe_config_backend({"name": "V", "api_type": "openai_video"})
check("V11 video kind", (k["media"], k["ref_slot_count"]), ("video", 1))

check("R1 occasions", len(adm.settings_image_routing_occasions(user=None)["occasions"]), 19)
SEEN = {}


def fake_explain(character="", pool=None):
    SEEN["character"] = character
    return {"character": character, "occasions": []}


from app.imagegen import base as _img_base  # noqa: E402
_real_explain = routing.explain_image_routing
_real_media_on = _img_base.media_generation_enabled
routing.explain_image_routing = fake_explain
_img_base.media_generation_enabled = lambda: True
check("R2 effective", adm.settings_image_routing_effective(character=" x ", user=None),
      {"character": "x", "occasions": [], "media_generation_enabled": True})
check("R2 character passed", SEEN.get("character"), "x")
_img_base.media_generation_enabled = lambda: False
check("R2 media switch off",
      adm.settings_image_routing_effective(character="", user=None).get("media_generation_enabled"),
      False)
routing.explain_image_routing = _real_explain
_img_base.media_generation_enabled = _real_media_on
check("R3 save wiring", "_validate_image_routing(" in inspect.getsource(adm.settings_save), True)


# ── settings_save end to end ────────────────────────────────────────────
STORED = {"image_generation": {"backends": copy.deepcopy(BACKENDS),
                               "routing": {"photo": ["Flux2*"]}}}
SAVED = []
adm.config.get_all = lambda: copy.deepcopy(STORED)
adm.config.save = lambda data, config_path=None: SAVED.append(copy.deepcopy(data))
adm.config._flatten_to_env = lambda data: None
adm._apply_section_reloads = lambda keys: []


class _Req:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return copy.deepcopy(self._payload)


def save(ig_extra, with_routing_key=True, backends=None, extra=None):
    """Run settings_save with a payload image_generation of the fixture
    backends plus ``routing`` (or without the key) and optional further
    top-level sections. Returns (response or the HTTPException, saved routing
    or the string "<not saved>")."""
    SAVED.clear()
    ig = {"backends": copy.deepcopy(backends or BACKENDS)}
    if with_routing_key:
        ig["routing"] = ig_extra
    payload = {"image_generation": ig}
    payload.update(copy.deepcopy(extra or {}))
    try:
        resp = asyncio.run(adm.settings_save(_Req(payload), user=None))
    except HTTPException as e:
        resp = e
    saved = SAVED[-1]["image_generation"].get("routing", "<key missing>") if SAVED else "<not saved>"
    return resp, saved


_, saved = save(None, with_routing_key=False)
check("S1 missing routing keeps the stored chains", saved, {"photo": ["Flux2*"]})
_, saved = save(None)
check("S1b null routing keeps the stored chains", saved, {"photo": ["Flux2*"]})
_, saved = save({})
check("S2 empty object clears", saved, {})
resp, saved = save({"mesh_low": ["x"]})
check("S3 invalid -> 400", (getattr(resp, "status_code", None), getattr(resp, "detail", None), saved),
      (400, "Image routing: unknown occasion 'mesh_low'.", "<not saved>"))
resp, saved = save({"photo": ["Nope*"]})
_w = "Image routing: 'Nope*' for 'photo' matches no backend."
check("S4 warning saved", saved, {"photo": ["Nope*"]})
check("S4 warnings field", resp.get("warnings") if isinstance(resp, dict) else resp, [_w])
check("S4 message", resp.get("message") if isinstance(resp, dict) else resp,
      "Configuration saved (env updated). Warnings: " + _w)

# ── fix round 1: an invalid STORED chain never locks the save ──────────
F_BACKENDS = copy.deepcopy(BACKENDS) + [
    {"name": "Mesh-O1", "api_type": "openai_mesh", "category": "img2mesh", "mesh_rig": "none"}]
F_ROUTING = {"mesh_low": ["x"], "mesh_object": ["Mesh-H*"], "photo": ["Flux2*"]}
STORED = {"image_generation": {"backends": copy.deepcopy(F_BACKENDS),
                               "routing": copy.deepcopy(F_ROUTING)}}
W_LOW = ("Image routing: stored chain 'mesh_low' is invalid and was kept "
         "unchanged — unknown occasion 'mesh_low'.")
W_OBJ = ("Image routing: stored chain 'mesh_object' is invalid and was kept "
         "unchanged — 'Mesh-H*' for 'mesh_object' matches only backends of "
         "the wrong kind (Mesh-H1).")


def fsave(routing_value, with_routing_key=True, extra=None):
    return save(routing_value, with_routing_key, backends=F_BACKENDS, extra=extra)


def _resp(r):
    """(status, warnings, message) of a dict response, (status, detail) of a 400."""
    if isinstance(r, HTTPException):
        return (r.status_code, r.detail)
    return (200, r.get("warnings"), r.get("message"))


resp, saved = fsave(copy.deepcopy(F_ROUTING), extra={"tts": {"enabled": True}})
check("F1 unrelated save passes with warnings", _resp(resp),
      (200, [W_LOW, W_OBJ], "Configuration saved (env updated). Warnings: " + W_LOW + " " + W_OBJ))
check("F1 unrelated section saved", SAVED[-1].get("tts") if SAVED else None, {"enabled": True})
resp, saved = fsave(None, with_routing_key=False, extra={"tts": {"enabled": True}})
check("F1b stale tab passes, routing kept", (_resp(resp)[:2], saved),
      ((200, [W_LOW, W_OBJ]), F_ROUTING))
r = copy.deepcopy(F_ROUTING)
r["mesh_object"] = ["Qwen Inpaint"]
resp, saved = fsave(r)
check("F2 edited to another invalid chain -> 400", (_resp(resp), saved),
      ((400, "Image routing: 'Qwen Inpaint' for 'mesh_object' matches only "
             "backends of the wrong kind (Qwen Inpaint)."), "<not saved>"))
r["mesh_object"] = ["Mesh-O*"]
resp, saved = fsave(r)
check("F3 edited to a valid chain -> 200", (_resp(resp)[:2], saved.get("mesh_object")
                                            if isinstance(saved, dict) else saved),
      ((200, [W_LOW]), ["Mesh-O*"]))
r = copy.deepcopy(F_ROUTING)
r["mesh_tiny"] = ["x"]
resp, saved = fsave(r)
check("F4 new unknown key -> 400", (_resp(resp), saved),
      ((400, "Image routing: unknown occasion 'mesh_tiny'."), "<not saved>"))
r = copy.deepcopy(F_ROUTING)
r["mesh_object"] = [" mesh-h* "]
resp, saved = fsave(r)
_f5 = _resp(resp)
check("F5 case/whitespace-only edit stays a warning", (_f5[0], len(_f5[1] or [])), (200, 2))

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("all checks passed")
