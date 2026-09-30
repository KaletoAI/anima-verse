"""CivitAI Orchestration v2 image-to-video backend (``api_type: civitai_video``).

One ``videoGen`` workflow step per clip, the engine picked per entry
(``video_engine``, the API's own engine values):

  * ``wan``              — WAN 2.2 on CivitAI's comfy workers (``version
    "v2.2"``, ``provider "comfy"``): ``sourceImage``, width/height, LoRAs as
    ``[{air, strength}]``, an optional custom model AIR (``model``).
  * ``minimax-h3-comfy`` — MiniMax H3 on comfy, ``operation "imageToVideo"``:
    ``firstFrame``, width/height, LoRAs as ``{air: strength}``, an optional
    ``diffusionModel`` AIR.
  * ``minimax-h3``       — the managed MiniMax H3: ``firstFrameImage``,
    ``resolution "2K"``, ``aspectRatio "adaptive"``, no LoRAs, no size.

``MEDIA_TYPE == "video"`` keeps it out of image matching; ``service.
generate_video`` hands the first frame as ``reference_images`` /
``source_image_path`` and the clip length as ``seconds``. Returns one MP4 as a
single-element ``List[bytes]``. Protocol + failure semantics:
``_civitai_workflow``. Spec: ``https://orchestration.civitai.com/openapi/v2-consumers.json``.
"""
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.log import get_logger
from app.imagegen.backends import _civitai_workflow as wfapi
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")

ENGINES = ("wan", "minimax-h3-comfy", "minimax-h3")

# Spec ranges per engine: duration (s) and the edge range of width/height
# (None = the engine takes no size — minimax-h3 derives it from the image).
_DURATION = {"wan": (1, 30), "minimax-h3-comfy": (4, 15), "minimax-h3": (5, 15)}
_EDGE = {"wan": (64, 2048), "minimax-h3-comfy": (32, 1344), "minimax-h3": None}

# A full AIR: urn:air:{ecosystem}:{type}:{source}:{id}[@{version}]. Stricter
# than the spec pattern on purpose: a malformed AIR makes CivitAI answer 500
# (a defect -> cooldown) instead of 400, so it is dropped before sending.
_AIR_RE = re.compile(r"^urn:air:[\w\-/]+:[\w\-/]+:[\w\-/]+:[\w\-/.]+(?:@[\w\-/.=,%+]+)?$")


def is_air(name: str) -> bool:
    return bool(_AIR_RE.match(str(name or "").strip()))


def _round16(v: float) -> int:
    """Nearest multiple of 16, halves rounded UP (not Python's banker's round)."""
    return int(v / 16.0 + 0.5) * 16


def fit_size(src_w: int, src_h: int, box_w: int, box_h: int,
             edge_range: Tuple[int, int]) -> Tuple[int, int]:
    """Output size with the source's aspect ratio: the long edge is the entry's
    larger dimension (clamped to the engine range), the short edge follows the
    aspect; both rounded to multiples of 16 (the recipes' convention — the
    spec has no multipleOf) and kept inside the engine range."""
    lo, hi = edge_range
    long_edge = min(max(box_w, box_h), hi)
    if src_w >= src_h:
        w, h = long_edge, long_edge * src_h / src_w
    else:
        w, h = long_edge * src_w / src_h, long_edge
    clamp = lambda x: min(hi, max(lo, _round16(x)))   # noqa: E731
    return clamp(w), clamp(h)


def _image_size(src: str) -> Optional[Tuple[int, int]]:
    """Pixel size of a LOCAL source image (Pillow reads the header only)."""
    if not src or src.startswith(("http://", "https://", "data:")):
        return None
    try:
        from PIL import Image
        with Image.open(src) as im:
            return im.size
    except Exception:   # noqa: BLE001 — unreadable -> the entry's size
        return None


class CivitAIVideoBackend(ImageBackend):
    """CivitAI image-to-video (WAN 2.2 comfy / MiniMax H3 comfy / MiniMax H3)."""

    MEDIA_TYPE = "video"
    # One first-frame image (the rendered still).
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="civitai_video", env_prefix=env_prefix)
        env = lambda k, d="": os.environ.get(f"{env_prefix}{k}", d).strip()   # noqa: E731
        self.api_key = (api_key or env("API_KEY")).strip()
        self.model = (model or env("MODEL")).strip()
        engine = env("VIDEO_ENGINE").lower() or "wan"
        if engine not in ENGINES:
            logger.warning("%s: unknown video_engine '%s' — using 'wan'", name, engine)
            engine = "wan"
        self.video_engine = engine
        self.guidance_scale = self._num(env("GUIDANCE_SCALE"), 4.0)
        self.width = int(self._num(env("WIDTH"), 1280))
        self.height = int(self._num(env("HEIGHT"), 720))
        self.seconds = int(self._num(env("SECONDS"), 5))
        self.allow_mature_content = env("ALLOW_MATURE_CONTENT").lower() in ("true", "1", "yes")
        self.poll_interval = self._num(env("POLL_INTERVAL"), 5.0)
        self.max_wait = int(self._num(env("MAX_WAIT"), 900))
        # Video jobs often sit in CivitAI's queue for minutes.
        self.max_queue_wait = int(self._num(env("MAX_QUEUE_WAIT"), 1800))
        self.extra_params: Dict[str, Any] = {}
        raw = env("EXTRA_PARAMS")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.extra_params = parsed
                else:
                    logger.warning("%s: extra_params is not a JSON object — ignored", name)
            except (ValueError, TypeError) as e:
                logger.warning("%s: extra_params is not valid JSON (%s) — ignored", name, e)

    @staticmethod
    def _num(raw: str, default: float) -> float:
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    def _headers(self) -> Dict[str, str]:
        return wfapi.headers(self.api_key)

    def check_availability(self) -> bool:
        """Only the key counts — ``model`` is optional for every engine."""
        if not self.api_key:
            self._mark_unavailable("no API key configured")
            return False
        try:
            resp = requests.get(f"{self.api_url}{wfapi.WORKFLOWS_PATH}",
                                params={"take": 1}, headers=self._headers(), timeout=10)
        except requests.ConnectionError:
            self._mark_unavailable("ConnectionError")
            return False
        except Exception as e:   # noqa: BLE001
            logger.error("%s: availability check failed: %s", self.name, e)
            self._mark_unavailable(str(e))
            return False
        if resp.status_code in (401, 403):
            self._mark_unavailable(f"API key rejected (HTTP {resp.status_code})")
            return False
        if resp.status_code == 200:
            self._mark_available(f"CivitAI video, engine: {self.video_engine}")
            return True
        self._mark_unavailable(f"HTTP {resp.status_code}")
        return False

    def _duration(self, params: Dict[str, Any]) -> int:
        want = int(params.get("seconds") or self.seconds or 5)
        lo, hi = _DURATION[self.video_engine]
        got = min(hi, max(lo, want))
        if got != want:
            logger.warning("%s: %ds is outside %s's range %d-%ds — using %ds",
                           self.name, want, self.video_engine, lo, hi, got)
        return got

    def _loras(self, params: Dict[str, Any]) -> List[Tuple[str, float]]:
        """(AIR, strength) pairs from ``lora_inputs``. Names that are no AIR —
        and every LoRA for the managed minimax-h3, which takes none — are
        dropped with one warning each."""
        out: List[Tuple[str, float]] = []
        for l in params.get("lora_inputs") or []:
            if not isinstance(l, dict):
                continue
            name = str(l.get("name") or "").strip()
            if not name or name == "None":
                continue
            if self.video_engine == "minimax-h3":
                logger.warning("%s: minimax-h3 takes no LoRAs — dropped %s", self.name, name)
                continue
            if not is_air(name):
                logger.warning("%s: LoRA '%s' is no CivitAI AIR (urn:air:…) — dropped",
                               self.name, name)
                continue
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            out.append((name, strength))
        return out

    def _model_air(self) -> str:
        if not self.model:
            return ""
        if not is_air(self.model):
            logger.warning("%s: model '%s' is no CivitAI AIR — not sent", self.name, self.model)
            return ""
        return self.model

    def build_step(self, prompt: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """The ``videoGen`` workflow step for one clip (no HTTP)."""
        src = wfapi.first_reference_image(params)
        image = wfapi.image_input(self, src)
        engine = self.video_engine
        duration = self._duration(params)
        loras = self._loras(params)
        model = self._model_air() if engine != "minimax-h3" else ""

        size: Optional[Tuple[int, int]] = None
        if _EDGE[engine] is not None:
            src_size = _image_size(src) or (self.width, self.height)
            size = fit_size(src_size[0], src_size[1], self.width, self.height, _EDGE[engine])

        if engine == "wan":
            inp: Dict[str, Any] = {
                "engine": "wan", "version": "v2.2", "provider": "comfy",
                "prompt": prompt, "sourceImage": image,
                "cfgScale": self.guidance_scale, "duration": duration,
            }
            if model:
                inp["model"] = model
            if loras:
                inp["loras"] = [{"air": a, "strength": s} for a, s in loras]
        elif engine == "minimax-h3-comfy":
            inp = {
                "engine": "minimax-h3-comfy", "operation": "imageToVideo",
                "prompt": prompt, "firstFrame": image, "duration": duration,
            }
            if model:
                inp["diffusionModel"] = model
            if loras:
                inp["loras"] = {a: s for a, s in loras}
        else:   # minimax-h3 (managed)
            inp = {
                "engine": "minimax-h3", "prompt": prompt, "firstFrameImage": image,
                "duration": duration, "resolution": "2K", "aspectRatio": "adaptive",
            }
        if size:
            inp["width"], inp["height"] = size
        # Free per-entry extras (steps, shift, fast, turbo, negativePrompt,
        # seed, …) — they win over the defaults above.
        inp.update(self.extra_params)
        return {"$type": "videoGen", "input": inp}

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        step = self.build_step(prompt, params)
        inp = step["input"]
        logger.info("%s: starting video (engine %s, %ss%s)", self.name, self.video_engine,
                    inp.get("duration"),
                    f", {inp['width']}x{inp['height']}" if "width" in inp else "")
        wf = wfapi.run_workflow(self, [step], allow_mature=self.allow_mature_content,
                                max_wait=self.max_wait, max_queue_wait=self.max_queue_wait,
                                poll_interval=self.poll_interval)
        if wf is None:
            return []
        return wfapi.download_blobs(self, wf)
