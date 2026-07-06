"""LocalAI-style OpenAI-compatible diffusion backend."""
import base64
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.backends.together import TogetherBackend

logger = get_logger("image_backends")


class LocalAIBackend(TogetherBackend):
    """LocalAI-style OpenAI-compatible diffusion endpoint (POST {url}/v1/images/generations).

    Works with LocalAI / vLLM / sd.cpp / any server with their quirks.
    Differences from the Together.ai-specific TogetherBackend:
      - **api_key optional** (LocalAI needs no Bearer token).
      - **ref_images support** (Flux context / reference-image conditioning): local
        reference files are sent as **raw base64** (LocalAI/Flux expects NO
        data: URI prefix), http(s) URLs are passed through unchanged.
        The source is params['reference_images'] (slots resolved by the skill —
        the same source as for ComfyUI).
      - LoRAs as ``<lora:name:weight>`` prompt syntax (sd.cpp/LocalAI), uses the
        LocalAI parameter name ``step`` and ``size`` ("WxH") instead of width/height.

    For an endpoint that adheres to the **strict OpenAI images standard**
    (e.g. the LLM gateway), see the derived ``OpenAIDiffusionBackend``.

    Inherits _post_with_retry / _rate_limit_wait from TogetherBackend (same endpoint).
    """

    # Reference-image conditioning: agent + room + others/items (see
    # _collect_ref_images). OpenAIDiffusionBackend inherits this budget.
    DEFAULT_REF_SLOT_COUNT = 4

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, env_prefix, api_key=api_key, model=model)
        self.api_type = "localai"
        # Optional endpoint to query the LoRAs available for this model
        # (analogous to ComfyUI). Empty = no query. ``{alias}`` is replaced by the
        # model name; without a placeholder ``/v1/generations/{model}/loras`` is appended.
        self.lora_url = os.environ.get(f"{env_prefix}LORA_URL", "").strip()
        # Glob narrowing the endpoint's LoRA list to this backend's model
        # (e.g. "Qwen*") — gateways list the LoRAs of ALL models on one
        # endpoint. Applied in fetch_loras, so discovery and every dropdown
        # only see matching LoRAs. Empty = no filtering.
        self.lora_filter = os.environ.get(f"{env_prefix}LORA_FILTER", "").strip()
        self.available_loras: List[str] = []

    def _lora_query_url(self) -> str:
        """Builds the LoRA query URL from lora_url + model name (alias)."""
        model = (self.model or "").strip()
        if "{alias}" in self.lora_url:
            return self.lora_url.replace("{alias}", model)
        return f"{self.lora_url.rstrip('/')}/v1/generations/{model}/loras"

    def fetch_loras(self) -> List[str]:
        """Fetches the available LoRAs from the lora_url endpoint (GET -> {"loras": [...]}).

        The result is narrowed by ``lora_filter`` (case-insensitive glob) —
        gateway endpoints list the LoRAs of ALL models, the filter keeps only
        the ones matching this backend's model. Sets + returns
        self.available_loras. Empty/erroneous response -> []."""
        if not self.lora_url or not self.model:
            return self.available_loras
        try:
            resp = requests.get(self._lora_query_url(), headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                body = resp.json()
                loras = body.get("loras") if isinstance(body, dict) else body
                if isinstance(loras, list):
                    names = [str(l).strip() for l in loras if l and str(l).strip()]
                    if self.lora_filter:
                        import fnmatch
                        pat = self.lora_filter.lower()
                        names = [n for n in names if fnmatch.fnmatch(n.lower(), pat)]
                    self.available_loras = names
                    logger.info(
                        f"{self.name}: {len(self.available_loras)} LoRA(s) vom Endpoint geladen"
                        + (f" (Filter '{self.lora_filter}')" if self.lora_filter else ""))
            else:
                logger.warning(f"{self.name}: LoRA-Abfrage HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"{self.name}: LoRA-Abfrage fehlgeschlagen: {e}")
        return self.available_loras

    def _headers(self) -> Dict[str, str]:
        # api_key optional — only send Authorization when set.
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_availability(self) -> bool:
        # No api_key needed — only check reachability + configured model.
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert")
            self.available = False
            return False
        try:
            resp = requests.get(f"{self.api_url}/v1/models",
                                headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    items = body.get("data", body) if isinstance(body, dict) else body
                    ids = [m.get("id") for m in items
                           if isinstance(m, dict) and m.get("id")]
                    if ids:
                        self.available_models = sorted(ids)
                except (ValueError, KeyError, AttributeError):
                    pass
                self._mark_available(f"OpenAI-Diffusion, Modell: {self.model}")
                self.available = True
                # Pull the LoRAs along too (if an endpoint is configured).
                if self.lora_url:
                    self.fetch_loras()
                return True
            self._log_unreachable(f"HTTP {resp.status_code}")
            self.available = False
            self._was_available = False
            return False
        except requests.ConnectionError:
            self._log_unreachable("ConnectionError")
            self.available = False
            self._was_available = False
            return False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
            return False

    def _collect_ref_images(self, params: Dict[str, Any]) -> List[str]:
        """ref_images list for conditioning from params['reference_images'].

        Dict values (slot_title -> local path): http(s) URLs are passed
        through, local files are embedded as **raw base64**.
        IMPORTANT: LocalAI/Flux expects raw base64 in the ref_images field
        WITHOUT a "data:<mime>;base64," prefix — a data URI is not recognized
        as an image server-side and silently ignored.
        """
        refs = params.get("reference_images") or {}
        out: List[str] = []
        for _title, path in refs.items():
            if not path:
                continue
            sp = str(path)
            if sp.startswith(("http://", "https://")):
                out.append(sp)
                continue
            if sp.startswith("data:"):
                # data:<mime>;base64,<payload> -> only <payload> (raw base64)
                out.append(sp.split(",", 1)[1] if "," in sp else sp)
                continue
            try:
                with open(sp, "rb") as f:
                    raw = f.read()
                out.append(base64.b64encode(raw).decode())
            except Exception as e:
                logger.warning(f"{self.name}: Referenzbild '{sp}' nicht lesbar: {e}")
        return out

    def _with_lora_syntax(self, prompt: str, params: Dict[str, Any]) -> str:
        """Appends selected LoRAs as ``<lora:name:weight>`` to the prompt
        (LocalAI/sd.cpp syntax). The source is params['lora_inputs'] (resolved by
        the skill from the per-world LoRA library + per-character overrides). Cloud
        backends have no lora node — the reference MUST be in the prompt. No
        LoRAs -> prompt unchanged; do not duplicate an already-present <lora:..>."""
        tags = []
        for l in (params.get("lora_inputs") or params.get("loras") or []):
            if not isinstance(l, dict):
                continue
            name = (l.get("name") or "").strip()
            if not name or name == "None":
                continue
            base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            for ext in (".safetensors", ".ckpt", ".pt"):
                if base.lower().endswith(ext):
                    base = base[:-len(ext)]
                    break
            if f"<lora:{base}" in prompt:
                continue
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            tags.append(f"<lora:{base}:{strength:g}>")
        if tags:
            return (prompt.rstrip() + " " + " ".join(tags)).strip()
        return prompt

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        # Selected LoRAs as <lora:name:weight> into the prompt (the base
        # generate() only adds the trigger words, not the LoRA reference).
        prompt = self._with_lora_syntax(prompt, params)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
        # ref_images deliberately NOT optional — conditioning must not be
        # silently removed on a 400.
        ref_images = self._collect_ref_images(params)
        if ref_images:
            payload["ref_images"] = ref_images

        # Optional parameters (removable individually on a 400). LocalAI uses "step".
        optional: Dict[str, Any] = {}
        if steps:
            optional["step"] = steps
        if negative_prompt:
            optional["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            optional["seed"] = seed
        payload.update(optional)

        logger.info(f"{self.name}: Starte Generierung (Modell {model}, {width}x{height}, "
                    f"{len(ref_images)} Ref-Bild(er))")
        try:
            resp = self._post_with_retry(payload, optional)
            data = resp.json()
            images: List[bytes] = []
            for item in data.get("data", []):
                b64 = item.get("b64_json", "")
                if b64:
                    images.append(base64.b64decode(b64))
                    continue
                url = item.get("url", "")
                if url:
                    img_resp = requests.get(url, timeout=60)
                    if img_resp.status_code == 200:
                        images.append(img_resp.content)
            if not images:
                logger.error(f"{self.name}: Keine Bilder in Response")
            return images
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []
