"""Together.ai Image Generation API backend."""
import base64
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")


class TogetherBackend(ImageBackend):
    """
    Backend for the Together.ai Image Generation API.
    API: POST https://api.together.xyz/v1/images/generations
    Supports FLUX.1, FLUX.2 and other models.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="together", env_prefix=env_prefix)

        self.api_key = api_key or os.environ.get(f"{env_prefix}API_KEY", "")
        self.model = model or os.environ.get(f"{env_prefix}MODEL", "")
        # Comma-separated model list for selection in the UI
        models_str = os.environ.get(f"{env_prefix}MODELS", "").strip()
        self.available_models: List[str] = [m.strip() for m in models_str.split(",") if m.strip()] if models_str else []
        self.num_inference_steps = int(os.environ.get(f"{env_prefix}NUM_INFERENCE_STEPS", "20"))
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "1024"))
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "1024"))
        self.disable_safety = os.environ.get(
            f"{env_prefix}DISABLE_SAFETY", "false"
        ).strip().lower() in ("true", "1", "yes")
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120"))

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def check_availability(self) -> bool:
        if not self.api_key:
            logger.warning(f"{self.name}: Kein API_KEY konfiguriert")
            self.available = False
            return False
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert")
            self.available = False
            return False

        try:
            resp = requests.get(
                f"{self.api_url}/v1/models",
                headers=self._headers(),
                timeout=10)
            if resp.status_code in (401, 403):
                logger.warning(f"{self.name}: API-Key ungueltig (Status {resp.status_code})")
                self.available = False
                return False

            # Extract image models live from the API
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    # Together.ai returns {"data": [...]}, possibly a list directly
                    all_models = body.get("data", body) if isinstance(body, dict) else body
                    live_models = sorted(
                        [m["id"] for m in all_models if m.get("type") == "image"])
                    if live_models:
                        self.available_models = live_models
                        logger.info(f"{self.name}: {len(live_models)} Bild-Modelle verfuegbar")
                except (ValueError, KeyError):
                    pass  # JSON parsing failed — available_models stays as configured

            logger.info(f"{self.name} erreichbar (Together.ai, Modell: {self.model})")
            self.available = True
            return True
        except requests.ConnectionError:
            logger.warning(f"{self.name} nicht erreichbar")
            self.available = False
            return False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
            return False

    # Parameter keys that can be removed individually on a 400
    _OPTIONAL_KEYS = ("steps", "negative_prompt", "width", "height", "n")

    def _rate_limit_wait(self, resp: requests.Response, attempt: int) -> float:
        """Wait time on 429: prefers the Retry-After / X-RateLimit-Reset header,
        otherwise exponential backoff (2,4,8,16s), capped at 30s."""
        for h in ("retry-after", "x-ratelimit-reset"):
            v = resp.headers.get(h)
            if not v:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            # Header can be an absolute epoch time OR seconds.
            if f > time.time():
                f = f - time.time()
            if f > 0:
                return max(1.0, min(f, 30.0))
        return min(2.0 * (2 ** (attempt - 1)), 30.0)

    def _post_with_retry(self, payload: Dict[str, Any],
                         optional: Dict[str, Any]) -> requests.Response:
        """Sends the request and removes the offending parameter on a 400.

        Detects from the error message which parameter is not supported and
        retries the request without it. At most len(optional) retries.
        """
        remaining = dict(optional)
        _429_retries = 0
        _max_429 = 4

        for _ in range(len(remaining) + 1 + _max_429):
            resp = requests.post(
                f"{self.api_url}/v1/images/generations",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout)
            # Rate limit: retry with backoff instead of hard-aborting.
            if resp.status_code == 429:
                if _429_retries >= _max_429:
                    error_msg = resp.text[:300] or '(leer)'
                    logger.error(f"{self.name}: Rate-Limit (429) nach {_max_429} Versuchen — Abbruch")
                    raise RuntimeError(f"{self.name}: HTTP 429 (Rate-Limit): {error_msg[:160]}")
                _429_retries += 1
                _wait = self._rate_limit_wait(resp, _429_retries)
                logger.warning(f"{self.name}: Rate-Limit (429), warte {_wait:.1f}s (Versuch {_429_retries}/{_max_429})")
                time.sleep(_wait)
                continue
            if resp.status_code != 400:
                if resp.status_code != 200:
                    error_msg = resp.text[:500] or '(leer)'
                    logger.error(f"{self.name}: Generierung fehlgeschlagen (Status {resp.status_code})")
                    logger.error(f"Response: {error_msg}")
                    raise RuntimeError(f"{self.name}: HTTP {resp.status_code}: {error_msg[:200]}")
                return resp

            # 400: find out which parameter is the problem
            error_text = resp.text.lower()
            removed = False
            for key in list(remaining.keys()):
                if key in error_text or (key in ("width", "height") and "dimension" in error_text):
                    logger.warning(f"{self.name}: Parameter '{key}' nicht unterstuetzt, wiederhole ohne")
                    payload.pop(key, None)
                    # always remove width/height together
                    if key in ("width", "height"):
                        payload.pop("width", None)
                        payload.pop("height", None)
                        remaining.pop("width", None)
                        remaining.pop("height", None)
                    else:
                        remaining.pop(key, None)
                    removed = True
                    break

            if not removed:
                # Unknown 400 error — not retryable
                error_msg = resp.text[:500] or '(leer)'
                logger.error(f"{self.name}: Generierung fehlgeschlagen (Status 400)")
                logger.error(f"Response: {error_msg}")
                raise RuntimeError(f"{self.name}: HTTP 400: {error_msg[:200]}")

        # Should not be reached
        raise RuntimeError(f"{self.name}: Retry-Limit erreicht")

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generates an image via the Together.ai API.

        Builds the payload with optional parameters (steps, width/height, negative_prompt).
        If the API rejects a parameter (400), that parameter is removed and the request
        is retried automatically.
        """
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps

        # Together.ai requires dimensions as multiples of 8
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "b64_json",
        }

        if self.disable_safety:
            payload["disable_safety_checker"] = True

        # Optional parameters — removed individually on a 400 and retried.
        # NO "n": Together generates 1 image by default; many models reject
        # "n" with a 400, and the immediate retry then triggered a 429
        # ("too many requests in a short window").
        # seed/steps/dimensions are optional too — some model architectures
        # (e.g. GPT-Image) reject 'seed' with a 400.
        optional_params: Dict[str, Any] = {}
        if steps:
            optional_params["steps"] = steps
        if width and height:
            optional_params["width"] = width
            optional_params["height"] = height
        if negative_prompt:
            optional_params["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            optional_params["seed"] = seed

        payload.update(optional_params)

        logger.info(f"{self.name}: Starte Generierung...")
        logger.info(f"Modell: {model}, Groesse: {width}x{height}, Steps: {steps}")
        logger.info(f"Prompt: {prompt[:120]}...")

        try:
            resp = self._post_with_retry(payload, optional_params)

            data = resp.json()
            images = []
            for item in data.get("data", []):
                b64 = item.get("b64_json", "")
                if b64:
                    images.append(base64.b64decode(b64))
                    logger.info(f"Bild erhalten: {len(images[-1])} bytes")
                else:
                    # Fallback: URL-based response
                    url = item.get("url", "")
                    if url:
                        img_resp = requests.get(url, timeout=60)
                        if img_resp.status_code == 200:
                            images.append(img_resp.content)
                            logger.info(f"Bild heruntergeladen: {len(images[-1])} bytes")

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
