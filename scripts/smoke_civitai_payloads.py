#!/usr/bin/env python3
"""Smoke check for the CivitAI Orchestration v2 backends (``civitai`` images
incl. img2img, ``civitai_video``) — the workflow step payloads and the error
classes of the shared client ``app/imagegen/backends/_civitai_workflow.py``.

No server, no network, no world: ``requests`` is scripted, the storage root is
a throwaway directory.

Usage:  ./.venv/bin/python scripts/smoke_civitai_payloads.py

EXPECTED VALUES, derived by hand from the spec
(``https://orchestration.civitai.com/openapi/v2-consumers.json``) and the plan
(``development_instructions/plan-civitai-img2img-video.md`` § 4, § 6)
---------------------------------------------------------------------------
[1] textToImage, SDXL AIR, entry 1000x700, steps 25, cfg 7, clipSkip 2,
    params seed 42. Width/height are rounded to multiples of 64:
    1000/64 = 15.6 -> 16 -> 1024, 700/64 = 10.9 -> 11 -> 704. The spec
    requires seed (0..4294967295) and cfgScale (1..30); v1's ``baseModel``
    does not exist in TextToImageInput. Scheduler default = the spec enum
    value ``dpM2MKarras``. So the input is exactly
      {model, prompt "p", scheduler "dpM2MKarras", steps 25, width 1024,
       height 704, seed 42, quantity 1, cfgScale 7.0, negativePrompt "n",
       clipSkip 2}
    No seed / seed -1 -> a seed inside 0..4294967295. An entry cfg of 0 ->
    cfgScale 1 (the spec minimum). Entry steps 200 (the shared admin field
    allows 200) -> 150 (spec TextToImageInput.steps 1..150).
[2] textToImage, Flux AIR (ecosystem "flux1"): scheduler "euler", cfgScale 1
    (guidance-distilled; the field is required), no negativePrompt, no clipSkip.
[3] img2img: category "img2img" -> ref_slot_count 1, the first reference image
    travels as ``sourceImage`` (local file -> "data:image/png;base64,…") with
    ``sourceImageDenoiseStrenght`` (sic, the API's spelling) = the entry's
    denoise_strength, default 0.6. Category "txt2img" -> 0 slots and no
    sourceImage even when a reference is handed in; a configured
    ref_slot_count does not override the category. routing.
    describe_config_backend applies the same rule (" IMG2IMG " is trimmed and
    lower-cased first). Other types keep the old rule: localai without a value
    -> its class default 4, with "2" -> 2; civitai_video -> 1. A missing
    source file -> GatewayRejectedError (the INPUT is broken, no cooldown).
[4] videoGen wan (v2.2, provider comfy), entry 1280x720:
    source 1000x500 -> long edge max(1280, 720) = 1280 (<= 2048), short
    1280 * 500/1000 = 640 -> 1280x640;
    source 1000x530 -> short 1280 * 0.53 = 678.4, /16 = 42.4 -> 42 -> 672
    -> 1280x672. seconds 40 -> duration 30 (range 1..30). cfgScale default 4.
    Halves round UP: a 1280x680 source in the same box keeps 680 = 16 * 42.5
    -> 43 * 16 = 688 (Python's round() would give 672).
    LoRA "urn:air:wanvideo22:lora:civitai:1@2" (0.8) -> [{air, strength 0.8}];
    "my_lora" (no AIR) and "urn:air:wanvideo22:lora:civitai:1:2" (malformed —
    CivitAI answers 500 to it) are dropped. A model AIR -> "model".
    extra_params {"steps": 30} lands in the input.
[5] videoGen minimax-h3-comfy, operation imageToVideo, ``firstFrame``:
    source 500x1000, entry 1280x720 -> long edge min(1280, 1344) = 1280 ->
    640x1280; entry 2000x1000, source 1000x500 -> long min(2000, 1344) = 1344,
    short 672 -> 1344x672. seconds 2 -> 4 (range 4..15). LoRAs as a map
    {air: strength}; a model AIR -> "diffusionModel".
[6] videoGen minimax-h3 (managed): ``firstFrameImage``, resolution "2K",
    aspectRatio "adaptive", no width/height, no loras, no model; seconds 3 -> 5.
[7] The client's error classes, checked THROUGH ``BackendPool.run_on_backend``
    — what the routing sees, not the raw exception:
      submit 400                         -> GatewayRejectedError, no cooldown
      submit 429 / 503                   -> BackendBusyError, no cooldown
      submit 401                         -> BackendFailedError + cooldown
                                            (the text carries no "401", which
                                            ``_re_4xx`` would read as payload)
      polls 202 processing x3, 200 succeeded -> the image bytes (202 is a
                                            usable poll, not a failed one)
      failed + blob.blockedReason        -> GatewayRejectedError, no cooldown
      succeeded, blob available=false + blockedReason
                                         -> GatewayRejectedError, no cooldown
      failed / expired, no reason        -> BackendFailedError + cooldown
      succeeded, blob available=false, no reason
                                         -> [] -> BackendFailedError + cooldown
      submit answers 200 succeeded       -> no poll, no cancel, the bytes
      processing + a blocked blob        -> PUT status=canceled (stop paying),
                                            THEN GatewayRejectedError
      processing past max_wait           -> PUT status=canceled, THEN busy
      3 polls answering 404              -> DELETE (still queued), [] ->
                                            BackendFailedError + cooldown
[8] The workflow-level mature-content fields (spec WorkflowTemplate):
    allow_mature_content off -> upgradeMode "automatic" (spec enum
    WorkflowUpgradeMode: manual | automatic) and NO allowMatureContent;
    on -> allowMatureContent true and NO upgradeMode.
"""
import atexit
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix: str) -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


# Throwaway storage BEFORE the first app import — nothing here may reach the
# tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = _scratch("civitai-smoke-clips-")

from app.core import paths  # noqa: E402

paths.init(_scratch("civitai-smoke-storage-"))

from PIL import Image  # noqa: E402

from app.imagegen import routing  # noqa: E402
from app.imagegen.backends import _civitai_workflow as wfapi  # noqa: E402
from app.imagegen.backends.civitai import CivitAIBackend  # noqa: E402
from app.imagegen.backends import civitai_video  # noqa: E402
from app.imagegen.backends.civitai_video import CivitAIVideoBackend  # noqa: E402
from app.imagegen.base import (BackendBusyError, BackendFailedError,  # noqa: E402
                               GatewayRejectedError)
from app.imagegen.selection import BackendPool  # noqa: E402

FAILED = []
SCRATCH = Path(_scratch("civitai-smoke-img-"))
SDXL = "urn:air:sdxl:checkpoint:civitai:101055@128078"
FLUX = "urn:air:flux1:checkpoint:civitai:618692@691639"
LORA = "urn:air:wanvideo22:lora:civitai:1@2"
SEED_MAX = 2 ** 32 - 1


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


_n = [0]


def make(cls, **env):
    """A backend built the way the service builds it: from its env prefix."""
    _n[0] += 1
    prefix = f"SMOKE_CIV_{_n[0]}_"
    for k, v in env.items():
        os.environ[f"{prefix}{k}"] = str(v)
    try:
        return cls("civ", "http://x", 1.0, prefix, api_key="k")
    finally:
        for k in env:
            os.environ.pop(f"{prefix}{k}", None)


def png(w, h):
    p = SCRATCH / f"src_{w}x{h}.png"
    Image.new("RGB", (w, h), (90, 120, 160)).save(p)
    return str(p)


def raised_by(fn):
    try:
        fn()
    except BaseException as e:   # noqa: BLE001
        return e
    return None


# ── [1] textToImage SDXL ───────────────────────────────────────────────────
print("[1] textToImage, SDXL")
b = make(CivitAIBackend, MODEL=SDXL, WIDTH=1000, HEIGHT=700, NUM_INFERENCE_STEPS=25,
         GUIDANCE_SCALE=7, CLIP_SKIP=2)
step = b.build_step("p", "n", {"seed": 42})
check("step type", step["$type"], "textToImage")
check("input", step["input"], {
    "model": SDXL, "prompt": "p", "scheduler": "dpM2MKarras", "steps": 25,
    "width": 1024, "height": 704, "seed": 42, "quantity": 1, "cfgScale": 7.0,
    "negativePrompt": "n", "clipSkip": 2})
for label, params in (("no seed", {}), ("seed -1", {"seed": -1})):
    s = b.build_step("p", "n", params)["input"]["seed"]
    check(f"{label} -> a seed inside the spec range", 0 <= s <= SEED_MAX, True)
b0 = make(CivitAIBackend, MODEL=SDXL, GUIDANCE_SCALE=0, NUM_INFERENCE_STEPS=200)
check("cfg 0 -> cfgScale 1", b0.build_step("p", "n", {})["input"]["cfgScale"], 1.0)
check("steps 200 -> 150", b0.build_step("p", "n", {})["input"]["steps"], 150)

# ── [2] textToImage Flux ───────────────────────────────────────────────────
print("[2] textToImage, Flux")
inp = make(CivitAIBackend, MODEL=FLUX).build_step("p", "n", {})["input"]
check("scheduler", inp["scheduler"], "euler")
check("cfgScale", inp["cfgScale"], 1)
check("no negativePrompt / clipSkip",
      ("negativePrompt" in inp, "clipSkip" in inp), (False, False))

# ── [3] img2img + the slot rule ────────────────────────────────────────────
print("[3] img2img and the reference-slot rule")
src = png(64, 64)
i2i = make(CivitAIBackend, MODEL=SDXL, CATEGORY="img2img")
check("img2img: ref_slot_count", i2i.ref_slot_count, 1)
inp = i2i.build_step("p", "n", {"reference_images": {"input_reference_image_1": src}})["input"]
check("sourceImage is a PNG data URI",
      inp.get("sourceImage", "").startswith("data:image/png;base64,"), True)
check("sourceImage carries the file",
      base64.b64decode(inp["sourceImage"].split(",", 1)[1]) == Path(src).read_bytes(), True)
check("sourceImageDenoiseStrenght default", inp.get("sourceImageDenoiseStrenght"), 0.6)
t2i = make(CivitAIBackend, MODEL=SDXL, CATEGORY="txt2img", REF_SLOT_COUNT=4)
check("txt2img: ref_slot_count (a configured 4 does not override)", t2i.ref_slot_count, 0)
inp = t2i.build_step("p", "n", {"reference_images": {"input_reference_image_1": src}})["input"]
check("txt2img: no sourceImage", "sourceImage" in inp, False)
for label, entry, want in (
        ("config view civitai ' IMG2IMG '", {"api_type": "civitai", "category": " IMG2IMG "}, 1),
        ("config view civitai txt2img + 4", {"api_type": "civitai", "category": "txt2img",
                                            "ref_slot_count": 4}, 0),
        ("config view localai, no value -> class default", {"api_type": "localai"}, 4),
        ("config view localai '2'", {"api_type": "localai", "ref_slot_count": "2"}, 2),
        ("config view civitai_video", {"api_type": "civitai_video"}, 1)):
    check(label, routing.describe_config_backend(entry)["ref_slot_count"], want)
e = raised_by(lambda: i2i.build_step("p", "n", {"reference_images": {"x": str(SCRATCH / "gone.png")}}))
check("missing source file", type(e).__name__, "GatewayRejectedError")

# ── [4] videoGen wan ───────────────────────────────────────────────────────
print("[4] videoGen wan")
wan = make(CivitAIVideoBackend, WIDTH=1280, HEIGHT=720,
           MODEL="urn:air:wanvideo22:checkpoint:civitai:3@4")
s1000 = png(1000, 500)
step = wan.build_step("p", {"source_image_path": s1000, "reference_images": {"frame": s1000},
                            "seconds": 40,
                            "lora_inputs": [{"name": LORA, "strength": 0.8},
                                            {"name": "my_lora", "strength": 1.0},
                                            {"name": "urn:air:wanvideo22:lora:civitai:1:2"}]})
inp = dict(step["input"])
check("step type", step["$type"], "videoGen")
check("sourceImage is a data URI", inp.pop("sourceImage").startswith("data:image/png;base64,"), True)
check("input", inp, {
    "engine": "wan", "version": "v2.2", "provider": "comfy", "prompt": "p",
    "cfgScale": 4.0, "duration": 30, "width": 1280, "height": 640,
    "model": "urn:air:wanvideo22:checkpoint:civitai:3@4",
    "loras": [{"air": LORA, "strength": 0.8}]})
s530 = png(1000, 530)
inp = wan.build_step("p", {"source_image_path": s530})["input"]
check("1000x530 -> 1280x672", (inp["width"], inp["height"]), (1280, 672))
check("default duration 5", inp["duration"], 5)
check("half rounds up: 1280x680 -> 1280x688",
      civitai_video.fit_size(1280, 680, 1280, 720, (64, 2048)), (1280, 688))
wx = make(CivitAIVideoBackend, EXTRA_PARAMS=json.dumps({"steps": 30}))
check("extra_params merged", wx.build_step("p", {"source_image_path": s530})["input"]["steps"], 30)

# ── [5] videoGen minimax-h3-comfy ──────────────────────────────────────────
print("[5] videoGen minimax-h3-comfy")
h3c = make(CivitAIVideoBackend, VIDEO_ENGINE="minimax-h3-comfy", WIDTH=1280, HEIGHT=720,
           MODEL="urn:air:other:checkpoint:civitai:5@6")
s500 = png(500, 1000)
inp = h3c.build_step("p", {"source_image_path": s500, "seconds": 2,
                           "lora_inputs": [{"name": LORA, "strength": 0.7}]})["input"]
check("engine / operation", (inp["engine"], inp["operation"]), ("minimax-h3-comfy", "imageToVideo"))
check("firstFrame is a data URI", inp.get("firstFrame", "").startswith("data:image/png;base64,"), True)
check("500x1000 -> 640x1280", (inp["width"], inp["height"]), (640, 1280))
check("seconds 2 -> 4", inp["duration"], 4)
check("loras as a map", inp["loras"], {LORA: 0.7})
check("model -> diffusionModel", inp.get("diffusionModel"), "urn:air:other:checkpoint:civitai:5@6")
big = make(CivitAIVideoBackend, VIDEO_ENGINE="minimax-h3-comfy", WIDTH=2000, HEIGHT=1000)
inp = big.build_step("p", {"source_image_path": s1000})["input"]
check("long edge capped at 1344", (inp["width"], inp["height"]), (1344, 672))

# ── [6] videoGen minimax-h3 (managed) ──────────────────────────────────────
print("[6] videoGen minimax-h3")
h3 = make(CivitAIVideoBackend, VIDEO_ENGINE="minimax-h3", MODEL="urn:air:other:checkpoint:civitai:5@6")
inp = dict(h3.build_step("p", {"source_image_path": s1000, "seconds": 3,
                               "lora_inputs": [{"name": LORA}]})["input"])
check("firstFrameImage is a data URI", inp.pop("firstFrameImage").startswith("data:image/png;base64,"), True)
check("input", inp, {"engine": "minimax-h3", "prompt": "p", "duration": 5,
                     "resolution": "2K", "aspectRatio": "adaptive"})

# ── [7] the client's error classes, through run_on_backend ─────────────────
print("[7] error classes as the routing sees them")


class Resp:
    def __init__(self, status, body=None, content=None):
        self.status_code = status
        self._body = body
        self.content = content if content is not None else (json.dumps(body).encode() if body is not None else b"")
        self.text = self.content.decode("utf-8", "replace") if isinstance(self.content, bytes) else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeHTTP:
    """Scripted requests: ``post``/``polls`` are answered in order, blob
    downloads return PNG bytes, every call is recorded."""

    def __init__(self, post, polls=()):
        self.post_resp = post
        self.polls = list(polls)
        self.calls = []
        self.body = None

    def install(self):
        self.saved = {m: getattr(wfapi.requests, m) for m in ("post", "get", "put", "delete")}
        wfapi.requests.post = self._post
        wfapi.requests.get = self._get
        wfapi.requests.put = lambda url, **k: self.calls.append(("put", k.get("json")))
        wfapi.requests.delete = lambda url, **k: self.calls.append(("delete", None))

    def restore(self):
        for m, fn in self.saved.items():
            setattr(wfapi.requests, m, fn)

    def _post(self, url, **k):
        self.calls.append(("post", None))
        self.body = k.get("json")
        return self.post_resp

    def _get(self, url, **k):
        if url.startswith("https://blob/"):
            self.calls.append(("download", None))
            return Resp(200, content=b"PNGBYTES")
        self.calls.append(("poll", None))
        return self.polls.pop(0) if self.polls else Resp(404)


def wf(status, blobs=None):
    body = {"id": "wf1", "status": status}
    if blobs is not None:
        body["steps"] = [{"$type": "textToImage", "output": {"images": blobs}}]
    return body


OK_BLOB = {"id": "blob_1", "url": "https://blob/1", "available": True}


RESULT = [None]


def run(http, **attrs):
    """One _generate through run_on_backend on a fresh backend. Returns
    (exception or None, cooldown active, call kinds); the result lands in
    RESULT[0]."""
    be = make(CivitAIBackend, MODEL=SDXL)
    be.poll_interval = 0
    for k, v in attrs.items():
        setattr(be, k, v)
    RESULT[0] = None

    def _go():
        RESULT[0] = BackendPool([be], lambda n: {}).run_on_backend(
            be, op=lambda bb: bb._generate("p", "n", {}))

    http.install()
    try:
        out = raised_by(_go)
    finally:
        http.restore()
    return out, be._cooldown_active(), [c[0] for c in http.calls]


cases = [
    ("submit 400", FakeHTTP(Resp(400, {"errors": {"x": ["bad"]}})), {},
     "GatewayRejectedError", False),
    ("submit 429", FakeHTTP(Resp(429, {})), {}, "BackendBusyError", False),
    ("submit 503", FakeHTTP(Resp(503, {})), {}, "BackendBusyError", False),
    ("submit 401", FakeHTTP(Resp(401, {})), {}, "BackendFailedError", True),
    ("failed + blockedReason", FakeHTTP(Resp(202, wf("scheduled")), [
        Resp(200, wf("failed", [{"id": "b", "blockedReason": "nsfw", "available": False}]))]),
     {}, "GatewayRejectedError", False),
    ("succeeded, blob blocked", FakeHTTP(Resp(202, wf("scheduled")), [
        Resp(200, wf("succeeded", [{"id": "b", "blockedReason": "csam", "available": False}]))]),
     {}, "GatewayRejectedError", False),
    ("failed, no reason", FakeHTTP(Resp(202, wf("scheduled")), [Resp(200, wf("failed", []))]),
     {}, "BackendFailedError", True),
    ("expired", FakeHTTP(Resp(202, wf("scheduled")), [Resp(200, wf("expired"))]),
     {}, "BackendFailedError", True),
    ("succeeded, blob unavailable, no reason", FakeHTTP(Resp(202, wf("scheduled")), [
        Resp(200, wf("succeeded", [{"id": "b", "url": "https://blob/1", "available": False}]))]),
     {}, "BackendFailedError", True),
]
for label, http, attrs, want, cooled in cases:
    e, cd, _calls = run(http, **attrs)
    check(f"{label}: outcome", type(e).__name__, want)
    check(f"{label}: cooldown", cd, cooled)
e, _, _ = run(FakeHTTP(Resp(401, {})))
check("submit 401: text free of the status number", "401" in str(e), False)

http = FakeHTTP(Resp(202, wf("scheduled")), [
    Resp(202, wf("processing")), Resp(202, wf("processing")), Resp(202, wf("processing")),
    Resp(200, wf("succeeded", [OK_BLOB]))])
e, cd, calls = run(http)
check("202 polls then success: no exception", e, None)
check("202 polls then success: result", RESULT[0][0] if RESULT[0] else None, [b"PNGBYTES"])
check("202 polls then success: call order", calls,
      ["post", "poll", "poll", "poll", "poll", "download"])

http = FakeHTTP(Resp(200, wf("succeeded", [OK_BLOB])))
e, cd, calls = run(http)
check("submit already succeeded: result", RESULT[0][0] if RESULT[0] else None, [b"PNGBYTES"])
check("submit already succeeded: no poll, no cancel", calls, ["post", "download"])

http = FakeHTTP(Resp(202, wf("processing", [{"id": "b", "blockedReason": "nsfw"}])))
e, cd, calls = run(http)
check("processing + blocked blob: outcome", type(e).__name__, "GatewayRejectedError")
check("processing + blocked blob: PUT canceled before the raise", http.calls,
      [("post", None), ("put", {"status": "canceled"})])

http = FakeHTTP(Resp(202, wf("processing")))
e, cd, calls = run(http, max_wait=0)
check("processing past max_wait: outcome", type(e).__name__, "BackendBusyError")
check("processing past max_wait: PUT canceled before the raise", http.calls,
      [("post", None), ("put", {"status": "canceled"})])
check("processing past max_wait: no cooldown", cd, False)

http = FakeHTTP(Resp(202, wf("scheduled")), [Resp(404), Resp(404), Resp(404)])
e, cd, calls = run(http)
check("3x 404: outcome", type(e).__name__, "BackendFailedError")
check("3x 404: DELETE (still queued) after three polls", calls,
      ["post", "poll", "poll", "poll", "delete"])
check("3x 404: cooldown", cd, True)

# ── [8] mature content on the workflow ─────────────────────────────────────
print("[8] mature content: upgradeMode vs allowMatureContent")
for label, attrs, want in (
        ("allow_mature_content off", {"allow_mature_content": False},
         {"upgradeMode": "automatic"}),
        ("allow_mature_content on", {"allow_mature_content": True},
         {"allowMatureContent": True})):
    http = FakeHTTP(Resp(200, wf("succeeded", [OK_BLOB])))
    run(http, **attrs)
    body = http.body or {}
    check(label, {k: v for k, v in body.items() if k != "steps"}, want)

print()
if FAILED:
    print(f"{len(FAILED)} check(s) FAILED: {FAILED}")
    sys.exit(1)
print("all checks passed")
