"""LLM Provider - represents a single API endpoint (e.g. Ollama server, OpenAI API).

Multiple LLM instances can share one provider. Each provider has its own queue
and concurrency settings.
"""
import time
import requests
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("provider")


@dataclass
class Provider:
    """Represents a single LLM API endpoint."""
    name: str                           # e.g. "OllamaLocal"
    type: str                           # "ollama", "openai", etc.
    api_base: str                       # e.g. "http://localhost:11434/v1"
    api_key: str
    max_concurrent: int = 1             # Max parallel requests
    timeout: Optional[int] = None       # Request timeout in seconds (None = use global default)
    available: bool = False
    # Cooldown gate set by upstream-failure detector (5xx, connection drop,
    # process-crash). check_availability() respects this without re-probing,
    # so a flaky provider doesn't oscillate available/unavailable across
    # health checks. Auto-clears when the timestamp passes.
    _cooldown_until: float = field(default=0.0, repr=False)
    _cooldown_reason: str = field(default="", repr=False)

    # Model list cache
    _models_cache: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    _models_cache_time: float = field(default=0.0, repr=False)

    def get_native_api_base(self) -> str:
        """Returns API base without /v1 suffix (for native Ollama API calls)."""
        base = self.api_base.rstrip("/")
        if base.endswith("/v1"):
            return base[:-3]
        return base

    def mark_unhealthy(self, reason: str, cooldown_seconds: float = 300.0) -> None:
        """Force the provider into a cooldown after an upstream failure.

        Used when a request mid-flight crashed the backend (e.g. 5xx,
        process exit, connection reset) but the /models probe might still
        report 200. The cooldown blocks scheduling here so the routing
        chain falls through to the next provider until the window expires.
        """
        import time as _time
        self.available = False
        self._cooldown_until = _time.monotonic() + max(0.0, cooldown_seconds)
        self._cooldown_reason = reason or "unhealthy"
        logger.warning("Provider %s in cooldown for %ds: %s",
                       self.name, int(cooldown_seconds), reason)

    def _cooldown_active(self) -> bool:
        if not self._cooldown_until:
            return False
        import time as _time
        return _time.monotonic() < self._cooldown_until

    def check_availability(self) -> bool:
        """Checks if this provider endpoint is reachable."""
        if self._cooldown_active():
            self.available = False
            return False
        # Cooldown expired — clear marker before probing.
        if self._cooldown_until:
            self._cooldown_until = 0.0
            self._cooldown_reason = ""
        try:
            headers = {}
            if self.api_key and self.api_key not in ("ollama-local", ""):
                headers["Authorization"] = f"Bearer {self.api_key}"

            if self.type == "ollama":
                # Try OpenAI-compatible /models endpoint
                url = f"{self.api_base.rstrip('/')}/models"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    self.available = True
                    logger.info("OK   %s (%s, %s)", self.name, self.type, self.api_base)
                    return True

                # Fallback: native Ollama /api/tags
                native = self.get_native_api_base()
                resp = requests.get(f"{native}/api/tags", timeout=10)
                if resp.status_code == 200:
                    self.available = True
                    logger.info("OK   %s (%s, %s)", self.name, self.type, self.api_base)
                    return True

                logger.warning("FAIL %s (%s): not reachable at %s", self.name, self.type, self.api_base)
                self.available = False
                return False

            elif self.type == "anthropic":
                # Anthropic Claude API: GET /models mit x-api-key Header
                url = f"{self.api_base.rstrip('/')}/models"
                anth_headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                }
                resp = requests.get(url, headers=anth_headers, timeout=10)
                self.available = resp.status_code == 200
                if self.available:
                    logger.info("OK   %s (anthropic, %s)", self.name, self.api_base)
                else:
                    logger.warning("FAIL %s (anthropic): HTTP %d", self.name, resp.status_code)
                return self.available

            else:
                # OpenAI and other types: GET /models with auth
                url = f"{self.api_base.rstrip('/')}/models"
                resp = requests.get(url, headers=headers, timeout=10)
                self.available = resp.status_code == 200
                if self.available:
                    logger.info("OK   %s (%s, %s)", self.name, self.type, self.api_base)
                else:
                    logger.warning("FAIL %s (%s): HTTP %d", self.name, self.type, resp.status_code)
                return self.available

        except requests.exceptions.ConnectionError:
            logger.warning("FAIL %s (%s): connection refused at %s", self.name, self.type, self.api_base)
            self.available = False
        except Exception as e:
            logger.error("FAIL %s (%s): %s", self.name, self.type, e)
            self.available = False

        return self.available

    def _do_unload(self, timeout: int = 30) -> bool:
        """Unloads all models via the /unload endpoint (used by the GPU-OOM retry)."""
        native = self.get_native_api_base()
        url = f"{native}/unload"
        try:
            logger.info("[%s] Unloading models: GET %s", self.name, url)
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                logger.info("[%s] Models unloaded (VRAM freed)", self.name)
                return True
            else:
                logger.warning("[%s] Unload returned HTTP %d", self.name, resp.status_code)
                return False
        except requests.exceptions.ConnectionError:
            logger.warning("[%s] Unload failed: connection refused at %s", self.name, url)
            return False
        except Exception as e:
            logger.error("[%s] Unload failed: %s", self.name, e)
            return False

    def list_models(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Lists available models from this provider.

        Ollama: GET /api/tags -> models[].name, .size, .details
        OpenAI: GET /models -> data[].id
        Results are cached for 60 seconds.
        """
        if not force_refresh and self._models_cache and (time.time() - self._models_cache_time) < 60:
            return self._models_cache

        models: List[Dict[str, Any]] = []
        try:
            headers = {}
            if self.api_key and self.api_key not in ("ollama-local", ""):
                headers["Authorization"] = f"Bearer {self.api_key}"

            if self.type == "ollama":
                native = self.get_native_api_base()
                resp = requests.get(f"{native}/api/tags", headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("models", []):
                        raw_size = m.get("size", 0)
                        models.append({
                            "name": m.get("name", ""),
                            "size": raw_size,
                            "size_gb": round(raw_size / (1024**3), 1) if raw_size else 0,
                            "parameter_size": m.get("details", {}).get("parameter_size", ""),
                            "family": m.get("details", {}).get("family", ""),
                            "quantization": m.get("details", {}).get("quantization_level", ""),
                        })
            elif self.type == "anthropic":
                url = f"{self.api_base.rstrip('/')}/models"
                anth_headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                }
                resp = requests.get(url, headers=anth_headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        models.append({
                            "name": m.get("id", ""),
                            "size": 0,
                            "size_gb": 0,
                            "parameter_size": "",
                            "family": "claude",
                            "quantization": "",
                        })
            else:
                url = f"{self.api_base.rstrip('/')}/models"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data.get("data", []) if isinstance(data, dict) else data
                    for m in raw:
                        # Skip non-chat models (image, video, audio, etc.)
                        mtype = m.get("type", "")
                        if mtype and mtype != "chat":
                            continue

                        # Serverless filter: skip models without per-token pricing
                        # (Together.ai provides pricing.input / pricing.output)
                        pricing = m.get("pricing")
                        if isinstance(pricing, dict):
                            has_serverless = (pricing.get("input", 0) or 0) > 0 or (pricing.get("output", 0) or 0) > 0
                            if not has_serverless:
                                continue

                        # Vision/VL/OCR-Modelle werden NICHT mehr ausgefiltert
                        # (die App hat Bild-Tasks, die ein Vision-Modell brauchen)
                        # — nur per Flag gekennzeichnet, damit die UI sie als
                        # "(vision)" markieren kann.
                        mid = m.get("id", "").lower()
                        display = m.get("display_name", "").lower()
                        is_vision = any(tag in mid or tag in display for tag in
                                        ("-vl-", "-vl ", "vl-", "/vl-", "-ocr", "vision"))

                        # Extract pricing for display
                        price_in = pricing.get("input", 0) if isinstance(pricing, dict) else 0
                        price_out = pricing.get("output", 0) if isinstance(pricing, dict) else 0
                        ctx_len = m.get("context_length", 0)
                        display_name = m.get("display_name", "") or m.get("id", "")

                        models.append({
                            "name": m.get("id", ""),
                            "display_name": display_name,
                            "size": 0,
                            "size_gb": 0,
                            "parameter_size": "",
                            "family": m.get("organization", ""),
                            "quantization": "",
                            "context_length": ctx_len,
                            "vision": is_vision,
                            "pricing": {"input": price_in, "output": price_out},
                        })

        except Exception as e:
            logger.error("list_models failed for %s: %s", self.name, e)

        self._models_cache = models
        self._models_cache_time = time.time()
        return models

    def has_model(self, model_name: str) -> bool:
        """Checks if this provider has the given model available.

        Handles Ollama tag normalization: 'model' matches 'model:latest'.
        """
        for m in self.list_models():
            if m["name"] == model_name:
                return True
            # 'Qwen3-8B' matches 'Qwen3-8B:latest' and vice versa
            if ":" not in model_name and m["name"] == f"{model_name}:latest":
                return True
            if model_name.endswith(":latest") and m["name"] == model_name[:-7]:
                return True
        return False
