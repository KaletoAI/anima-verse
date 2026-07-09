"""Image Generation Backends - various API types for image generation"""
import base64
import json
import os
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger

logger = get_logger("image_backends")


class ImageBackend(ABC):
    """
    Base class for image generation backends.

    Each backend implements a specific API protocol
    (e.g. A1111/Forge, Mammouth/OpenAI-compatible).
    """

    # Throttle for "unreachable" warnings — avoid log spam for permanently
    # offline backends. First time WARNING, then reduced to DEBUG for
    # _UNREACHABLE_THROTTLE_SEC seconds. Recovery (avail True after False)
    # is logged as INFO.
    _UNREACHABLE_THROTTLE_SEC = 300

    # How many reference-image slots (params['reference_images']) this backend
    # type can consume. 0 = backend takes no reference images. Overridable per
    # instance via {env_prefix}REF_SLOT_COUNT (config field ref_slot_count).
    DEFAULT_REF_SLOT_COUNT = 0

    # Media kind produced by this backend: "image" (default) or "video".
    # The BackendPool keeps the two apart — an image render never matches a
    # video backend and vice-versa (like the inpaint-category exclusion). Video
    # backends return one MP4 as a single-element List[bytes]; the central
    # generate() skips the image-only downscale post-processing for them.
    MEDIA_TYPE = "image"

    def __init__(self, name: str, api_url: str, cost: float, api_type: str, env_prefix: str):
        self.name = name
        self.api_url = api_url.rstrip("/")
        self.cost = cost
        self.api_type = api_type
        self.env_prefix = env_prefix
        self._available = False
        # Cooldown after an error: keeps `available` hard False temporarily, even
        # when check_availability sees the (reachable) endpoint respond 200 again.
        # This way a gateway that is online but currently cannot serve the model
        # (e.g. 503 "No healthy backend") is not retried on every generation — the
        # match selection skips it until the cooldown expires (mirrors
        # provider.mark_unhealthy on the LLM side).
        self._cooldown_until: float = 0.0
        self._cooldown_reason: str = ""
        self._active_jobs = 0
        self._jobs_lock = __import__("threading").Lock()
        # Last time we logged "unreachable" as a WARNING
        self._last_unreachable_warn_ts: float = 0.0
        # Previous availability status — transition False->True triggers "back again"
        self._was_available: Optional[bool] = None

        # Instance-enabled from .env (global default)
        self.instance_enabled = os.environ.get(f"{env_prefix}ENABLED", "true").strip().lower() in ("true", "1", "yes")

        # Image family (natural/keywords) — how the model wants its prompts.
        # Style/negative belong to the use cases, not to the backend.
        self.image_family = os.environ.get(f"{env_prefix}IMAGE_FAMILY", "").strip()

        # Reference-image slot budget (see DEFAULT_REF_SLOT_COUNT).
        _slots_str = os.environ.get(f"{env_prefix}REF_SLOT_COUNT", "").strip()
        try:
            self.ref_slot_count = int(_slots_str) if _slots_str else self.DEFAULT_REF_SLOT_COUNT
        except ValueError:
            self.ref_slot_count = self.DEFAULT_REF_SLOT_COUNT

        # Static fallback configuration (fallback_mode/fallback_specific) removed:
        # on failure run_with_fallback dynamically picks the next available
        # compatible backend — the availability logic IS the fallback (match
        # concept).

        # NVFP4 architecture: backend requires NVFP4-quantized models (legacy)
        self.nvfp4 = os.environ.get(
            f"{env_prefix}NVFP4", "false"
        ).strip().lower() in ("true", "1", "yes")

        # Per-backend queue/channel settings (supersedes the old gpu_provider
        # mechanism: each backend gets its own channel via the ProviderManager).
        mc_str = os.environ.get(f"{env_prefix}MAX_CONCURRENT", "1").strip()
        try:
            self.max_concurrent = max(1, int(mc_str))
        except ValueError:
            self.max_concurrent = 1
        # Serialize group (metadata only — the channel setup in
        # provider_manager reads the same env directly): channels with the
        # same group share one Semaphore(1), e.g. an LLM provider and this
        # backend on one physical GPU.
        self.serialize_group = os.environ.get(f"{env_prefix}SERIALIZE_GROUP", "").strip()

    @property
    def effective_cost(self) -> float:
        """Semantic cost of the backend. Used by the selector for
        preference (local=0, cloud > 0). No load penalty anymore —
        distribution of equal-cost backends runs via round-robin in the skill.
        """
        return self.cost

    def _log_unreachable(self, reason: str = "") -> None:
        """Throttled logging for 'unreachable' states.

        WARNING the first time and again every 5 minutes, DEBUG in between.
        Prevents a log flood when polling/check_availability runs often.
        """
        msg = f"{self.name} nicht erreichbar: {self.api_url}"
        if reason:
            msg += f" ({reason})"
        now = time.time()
        if now - self._last_unreachable_warn_ts >= self._UNREACHABLE_THROTTLE_SEC:
            logger.warning(msg)
            self._last_unreachable_warn_ts = now
        else:
            logger.debug(msg)

    def _mark_available(self, info: str = "") -> None:
        """Marks the backend as available; logs INFO on recovery."""
        _was_recovery = (self._was_available is False)
        if _was_recovery:
            logger.info("%s wieder erreichbar%s", self.name, f": {info}" if info else "")
        elif self._was_available is None:
            # First successful check — short INFO, no "again"
            logger.info("%s erreichbar%s", self.name, f": {info}" if info else "")
        self._was_available = True
        # Reset the throttle counter so the next down event warns immediately
        self._last_unreachable_warn_ts = 0.0
        self.available = True
        # Recovery: re-poll channel_health immediately so GPU task routing
        # (find_channel/is_healthy) sees the fresh status and does not wait
        # until the next 30s poll. Otherwise GPU tasks would still fail right
        # after recovery even though the backend is online again.
        if _was_recovery:
            try:
                from app.core.channel_health import get_monitor as _ch_monitor
                _ch_monitor().force_poll()
            except Exception as _ch_err:
                logger.debug("channel_health force_poll fehlgeschlagen: %s", _ch_err)

    def _mark_unavailable(self, reason: str = "") -> None:
        """Marks the backend as unavailable; throttled logging."""
        self._log_unreachable(reason)
        self._was_available = False
        self.available = False

    @property
    def available(self) -> bool:
        """Available for backend selection. During a cooldown hard False —
        regardless of what the last availability check set (see
        mark_unhealthy)."""
        if self._cooldown_active():
            return False
        return self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = bool(value)

    def _cooldown_active(self) -> bool:
        if not self._cooldown_until:
            return False
        if time.monotonic() < self._cooldown_until:
            return True
        # Expired — reset, the next check_availability may probe again.
        self._cooldown_until = 0.0
        self._cooldown_reason = ""
        return False

    def mark_unhealthy(self, reason: str = "", cooldown_seconds: float = 300.0) -> None:
        """Puts the backend into cooldown after an error.

        Unlike ``available = False`` this survives the next
        ``check_availability`` probe: while the cooldown runs the
        ``available`` property returns False so the match selection skips this
        backend and picks another. After it expires it is probed normally
        again (retry).
        """
        self._available = False
        self._was_available = False
        self._cooldown_until = time.monotonic() + max(0.0, cooldown_seconds)
        self._cooldown_reason = reason or "unhealthy"
        logger.warning("Backend %s in Cooldown fuer %ds: %s",
                       self.name, int(cooldown_seconds), reason)

    @abstractmethod
    def check_availability(self) -> bool:
        """Checks whether the API is reachable. Sets self.available."""
        pass

    def _inject_lora_triggers(self, prompt: str, params: Dict[str, Any]) -> str:
        """Prepends the activation words of the active LoRAs to the prompt
        (from the per-world repository image_generation.lora_triggers). Cloud
        backends without LoRAs (lora_inputs popped) get nothing."""
        try:
            names = [str(l.get("name")).strip()
                     for l in (params.get("lora_inputs") or params.get("loras") or [])
                     if isinstance(l, dict) and (l.get("name") or "").strip()
                     and l.get("name") != "None"]
            if not names:
                return prompt
            from app.core.config import get_lora_trigger_words
            words = get_lora_trigger_words(names)
            if not words:
                return prompt
            logger.info("%s: LoRA-Trigger-Woerter ergaenzt: %s", self.name, ", ".join(words))
            return ", ".join(words) + ", " + prompt
        except Exception as e:
            logger.debug("LoRA-Trigger-Injektion fehlgeschlagen: %s", e)
            return prompt

    def generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any],
                 log_meta: Optional[Dict[str, Any]] = None) -> List[bytes]:
        """Generates images with automatic job tracking for load balancing.

        CENTRAL final step of image creation: (1) include the LoRA activation
        words in the prompt -> final prompt, (2) hand it to the engine,
        (3) on success write the image-prompt logfile — with EXACTLY the final
        prompt that went to the engine. This keeps log == generation without
        every caller having to maintain it. ``log_meta`` provides the caller's
        context (agent_name, original_prompt, PromptBuilder vars …); the
        engine-/prompt-side fields (final_prompt, backend, model, LoRAs,
        reference images, duration, seed, negative) are set by this function
        itself. ``log_meta=None`` -> no logging (e.g. error logging is done by
        the caller).

        Applies central downscale post-processing when ``params`` contains an
        ``image_use_case`` (item / location). Callers that need full
        resolution (outfit, avatar) do not set the key.
        """
        import time as _time
        # Include the LoRA activation words (per-world repository) centrally in
        # the prompt — applies to ALL backends/paths as soon as a LoRA is active.
        final_prompt = self._inject_lora_triggers(prompt, params)

        _t0 = _time.time()
        with self._jobs_lock:
            self._active_jobs += 1
        try:
            result = self._generate(final_prompt, negative_prompt, params)
        finally:
            with self._jobs_lock:
                self._active_jobs = max(0, self._active_jobs - 1)

        # Only downscale a real result list; empty/error results pass through.
        # Video backends return MP4 bytes — never run the image downscale on them.
        use_case = (params or {}).get("image_use_case") or ""
        if self.MEDIA_TYPE == "image" and use_case and isinstance(result, list) and result:
            try:
                from app.core.image_postprocess import downscale_bytes
                result = [
                    downscale_bytes(img, use_case) if isinstance(img, (bytes, bytearray)) else img
                    for img in result
                ]
            except Exception as _exc:
                logger.warning("Downscale-Postprocess fehlgeschlagen: %s", _exc)

        # Central logging only on real success (images produced).
        if log_meta is not None and isinstance(result, list) and result:
            self._log_generation(final_prompt, negative_prompt, params,
                                 _time.time() - _t0, log_meta)
        return result

    def _log_generation(self, final_prompt: str, negative_prompt: str,
                        params: Dict[str, Any], duration_s: float,
                        log_meta: Dict[str, Any]) -> None:
        """Writes the image-prompt log line with the FINAL prompt + engine-/
        prompt-side fields; ``log_meta`` contributes the caller context."""
        try:
            from app.utils.image_prompt_logger import log_image_prompt
            _model = (params.get("model") or params.get("unet")
                      or getattr(self, 'last_used_checkpoint', '')
                      or getattr(self, 'model', '') or getattr(self, 'checkpoint', '') or '')
            fields = dict(log_meta or {})
            fields.update(
                final_prompt=final_prompt,
                negative_prompt=negative_prompt,
                backend_name=self.name,
                backend_type=self.api_type,
                model=_model,
                loras=params.get("lora_inputs") or params.get("loras") or [],
                reference_images=params.get("reference_images") or {},
                duration_s=round(float(duration_s), 2),
            )
            if "seed" not in fields and params.get("seed") is not None:
                fields["seed"] = int(params.get("seed") or 0)
            log_image_prompt(**fields)
        except Exception as _le:
            logger.debug("Zentrales Image-Logging fehlgeschlagen: %s", _le)

    @abstractmethod
    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """
        Generates images and returns them as a list of PNG bytes.

        Args:
            prompt: The finished prompt (incl. prefix/suffix)
            negative_prompt: Negative prompt
            params: Additional parameters (guidance_scale, steps, etc.)

        Returns:
            List of PNG images as bytes
        """
        pass

    def __repr__(self):
        status = "verfuegbar" if self.available else "nicht verfuegbar"
        return f"{self.name} ({self.api_type}, cost={self.cost}, {status})"
