"""CivitAI Orchestration v2 image backend (txt2img + img2img, async with polling)."""
import json
import os
import random
from typing import Any, Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.backends import _civitai_workflow as wfapi
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")

# Spec TextToImageInput: width/height at most 4084 — the largest multiple of 64 below it.
_MAX_EDGE = 4032
_SEED_MAX = 2 ** 32 - 1


def air_ecosystem(model: str) -> str:
    """The ecosystem segment of an AIR URN ``urn:air:{ecosystem}:...`` (lower
    case), ``""`` for anything else."""
    parts = (model or "").lower().split(":")
    if len(parts) >= 3 and parts[0] == "urn" and parts[1] == "air":
        return parts[2]
    return ""


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "") or default)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.environ.get(key, "") or default))
    except ValueError:
        return default


class CivitAIBackend(ImageBackend):
    """
    Backend for the CivitAI Orchestration API v2: one ``textToImage`` workflow
    step per render (POST /v2/consumer/workflows -> poll -> download the
    output blob). Models are AIR URNs:
    urn:air:{ecosystem}:checkpoint:civitai:{modelId}@{versionId}

    img2img: with category "img2img" the entry gets exactly ONE reference slot
    (``config_ref_slot_count``); the slotted image travels as ``sourceImage``
    with ``sourceImageDenoiseStrenght`` (sic — the API's spelling). That is
    init-image img2img: the composition of the source survives, so it suits
    variant occasions (day/night, location variants), not character scenes.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="civitai", env_prefix=env_prefix)

        self.api_key = api_key or os.environ.get(f"{env_prefix}API_KEY", "")
        self.model = model or os.environ.get(f"{env_prefix}MODEL", "")
        # Spec enum Scheduler (camelCase); the API matches it case-insensitively.
        self.scheduler = os.environ.get(f"{env_prefix}SCHEDULER", "").strip() or "dpM2MKarras"
        self.guidance_scale = _env_float(f"{env_prefix}GUIDANCE_SCALE", 7.0)
        self.num_inference_steps = _env_int(f"{env_prefix}NUM_INFERENCE_STEPS", 40)
        self.width = _env_int(f"{env_prefix}WIDTH", 1024)
        self.height = _env_int(f"{env_prefix}HEIGHT", 1024)
        self.clip_skip = _env_int(f"{env_prefix}CLIP_SKIP", 2)
        self.denoise_strength = min(1.0, max(0.0, _env_float(f"{env_prefix}DENOISE_STRENGTH", 0.6)))
        self.allow_mature_content = os.environ.get(
            f"{env_prefix}ALLOW_MATURE_CONTENT", "").strip().lower() in ("true", "1", "yes")
        self.poll_interval = _env_float(f"{env_prefix}POLL_INTERVAL", 5.0)
        # max_wait budgets the RENDER time only; the queued phase has its own budget.
        self.max_wait = _env_int(f"{env_prefix}MAX_WAIT", 300)
        self.max_queue_wait = _env_int(f"{env_prefix}MAX_QUEUE_WAIT", 600)
        # Free per-entry extras merged into the step input (win over defaults).
        self.extra_params: Dict[str, Any] = {}
        raw = os.environ.get(f"{env_prefix}EXTRA_PARAMS", "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.extra_params = parsed
                else:
                    logger.warning("%s: extra_params is not a JSON object — ignored", name)
            except (ValueError, TypeError) as e:
                logger.warning("%s: extra_params is not valid JSON (%s) — ignored", name, e)

    @classmethod
    def config_ref_slot_count(cls, category: str, configured: Any) -> int:
        """The slot budget follows the category alone: img2img consumes the one
        source image, every other category none — so a txt2img entry is never
        handed an image it would silently turn into img2img."""
        return 1 if (category or "").strip().lower() == "img2img" else 0

    def _headers(self) -> Dict[str, str]:
        return wfapi.headers(self.api_key)

    def check_availability(self) -> bool:
        """Checks whether the API key is valid and the API reachable."""
        if not self.api_key:
            self._mark_unavailable("no API key configured")
            return False
        if not self.model:
            self._mark_unavailable("no model configured (AIR URN required)")
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
            self._mark_available(f"CivitAI, model: {self.model}")
            return True
        self._mark_unavailable(f"HTTP {resp.status_code}")
        return False

    def _model_for(self, params: Dict[str, Any]) -> str:
        """CivitAI needs an AIR URN — a local file name in params is ignored."""
        param_model = str(params.get("model") or "")
        if param_model.startswith("urn:air:"):
            return param_model
        if param_model:
            logger.debug("%s: ignoring non-AIR model from params: %s (using %s)",
                         self.name, param_model, self.model)
        return self.model

    def build_step(self, prompt: str, negative_prompt: str,
                   params: Dict[str, Any]) -> Dict[str, Any]:
        """The ``textToImage`` workflow step for one render (no HTTP)."""
        model = self._model_for(params)
        is_flux = air_ecosystem(model).startswith("flux")

        def _edge(v: Any, fallback: int) -> int:
            v = int(v or fallback)
            # Multiples of 64, within the spec's 64..4084.
            return min(_MAX_EDGE, max(64, round(v / 64) * 64))

        seed = params.get("seed")
        if not (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed <= _SEED_MAX):
            # The spec requires a seed in 0..2^32-1 (-1 is not "random" here).
            seed = random.randint(0, _SEED_MAX)

        inp: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "scheduler": "euler" if is_flux else self.scheduler,
            # Spec TextToImageInput.steps: 1..150 (the shared admin field allows 200).
            "steps": min(150, max(1, int(params.get("num_inference_steps") or self.num_inference_steps))),
            "width": _edge(params.get("width"), self.width),
            "height": _edge(params.get("height"), self.height),
            "seed": seed,
            "quantity": 1,
        }
        if is_flux:
            # cfgScale is required (1..30); Flux is guidance-distilled -> 1,
            # and it takes neither a negative prompt nor clipSkip.
            inp["cfgScale"] = 1
        else:
            cfg = float(params.get("guidance_scale") or self.guidance_scale)
            inp["cfgScale"] = min(30.0, max(1.0, cfg))
            inp["negativePrompt"] = negative_prompt or ""
            inp["clipSkip"] = self.clip_skip

        if self.ref_slot_count >= 1:
            src = wfapi.first_reference_image(params)
            if src:
                inp["sourceImage"] = wfapi.image_input(self, src)
                inp["sourceImageDenoiseStrenght"] = self.denoise_strength
        inp.update(self.extra_params)
        return {"$type": "textToImage", "input": inp}

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generates an image via one CivitAI v2 workflow (async with polling)."""
        if not self._model_for(params):
            logger.error("%s: no model configured", self.name)
            return []
        step = self.build_step(prompt, negative_prompt, params)
        inp = step["input"]
        logger.info("%s: model %s, %dx%d, steps %d%s", self.name, inp["model"],
                    inp["width"], inp["height"], inp["steps"],
                    f", img2img strength {inp['sourceImageDenoiseStrenght']}"
                    if "sourceImage" in inp else "")
        logger.info("Prompt: %s...", prompt[:120])
        wf = wfapi.run_workflow(self, [step], allow_mature=self.allow_mature_content,
                                max_wait=self.max_wait, max_queue_wait=self.max_queue_wait,
                                poll_interval=self.poll_interval)
        if wf is None:
            return []
        return wfapi.download_blobs(self, wf)
