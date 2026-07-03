"""Image-to-Video Animation.

Currently supported service:
  - Together.ai (Cloud) - Kling, Wan and other video models via the Together API

Configuration via .env:

  # --- Together.ai Service ---
  TOGETHER_ANIMATE_ENABLED      - service enabled (default: false)
  TOGETHER_ANIMATE_LABEL        - display name (default: "Together.ai Cloud")
  TOGETHER_ANIMATE_API_KEY      - API key (or PROVIDER with a Together key)
  TOGETHER_ANIMATE_API_URL      - API URL (default: https://api.together.xyz)
  TOGETHER_ANIMATE_MODEL        - model id (e.g. "kwaivgI/kling-2.1-standard")
  TOGETHER_ANIMATE_WIDTH        - video width (default: 768)
  TOGETHER_ANIMATE_HEIGHT       - video height (default: 768)
  TOGETHER_ANIMATE_SECONDS      - video length in seconds (default: 5)
  TOGETHER_ANIMATE_POLL_INTERVAL - poll interval (default: 5.0)
  TOGETHER_ANIMATE_MAX_WAIT     - max wait time (default: 600)
"""

import base64
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger

logger = get_logger("animate")


# ═══════════════════════════════════════════════════════════════════════════
# Abstract base
# ═══════════════════════════════════════════════════════════════════════════

class AnimateService(ABC):
    """Abstract base for animation services."""

    service_id: str = ""
    label: str = ""
    enabled: bool = False

    @abstractmethod
    def animate(self, source_image_path: str, prompt: str, output_path: str) -> bool:
        """Generates a video from a source image.

        Returns:
            True on success, False on error.
        """

    def info(self) -> Dict[str, Any]:
        """Returns service info for the frontend."""
        return {"id": self.service_id, "label": self.label, "enabled": self.enabled}


# ═══════════════════════════════════════════════════════════════════════════
# Together.ai Service
# ═══════════════════════════════════════════════════════════════════════════

class TogetherAnimateService(AnimateService):
    """Animation via the Together.ai Video Generation API (Kling, Wan, etc.)."""

    service_id = "together"

    def __init__(self):
        self.label = os.environ.get("TOGETHER_ANIMATE_LABEL", "Together.ai Cloud").strip()
        self.enabled = os.environ.get("TOGETHER_ANIMATE_ENABLED", "false").strip().lower() in ("true", "1", "yes")
        self.api_key = os.environ.get("TOGETHER_ANIMATE_API_KEY", "").strip()
        self.api_url = os.environ.get("TOGETHER_ANIMATE_API_URL", "https://api.together.xyz").strip().rstrip("/")
        self.model = os.environ.get("TOGETHER_ANIMATE_MODEL", "").strip()
        self.width = int(os.environ.get("TOGETHER_ANIMATE_WIDTH", "768"))
        self.height = int(os.environ.get("TOGETHER_ANIMATE_HEIGHT", "768"))
        self.seconds = int(os.environ.get("TOGETHER_ANIMATE_SECONDS", "5"))
        self.poll_interval = float(os.environ.get("TOGETHER_ANIMATE_POLL_INTERVAL", "5.0"))
        self.max_wait = int(os.environ.get("TOGETHER_ANIMATE_MAX_WAIT", "600"))

        # Fallback: pull the API key from a Together provider
        if not self.api_key:
            self.api_key = self._find_together_api_key()

    @staticmethod
    def _find_together_api_key() -> str:
        """Looks up the Together API key from the PROVIDER_* configuration."""
        for n in range(1, 20):
            name = os.environ.get(f"PROVIDER_{n}_NAME", "").strip()
            if not name:
                break
            api_base = os.environ.get(f"PROVIDER_{n}_API_BASE", "").strip()
            if "together" in name.lower() or "together" in api_base.lower():
                key = os.environ.get(f"PROVIDER_{n}_API_KEY", "").strip()
                if key:
                    return key
        return ""

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def animate(self, source_image_path: str, prompt: str, output_path: str) -> bool:
        if not self.enabled:
            logger.warning("Together animation is disabled")
            return False
        if not self.api_key:
            logger.error("Together animation: no API key configured")
            return False
        if not self.model:
            logger.error("Together animation: no model configured")
            return False

        # 1. Read image as base64
        path = Path(source_image_path)
        if not path.exists():
            logger.error("Source file not found: %s", source_image_path)
            return False

        with open(source_image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        # Determine MIME type
        suffix = path.suffix.lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
            suffix.lstrip("."), "image/png"
        )
        data_uri = f"data:{mime};base64,{image_b64}"

        # 2. Create the video job
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "width": self.width,
            "height": self.height,
            "seconds": self.seconds,
            "output_format": "MP4",
            "frame_images": [
                {"input_image": data_uri, "frame": "first"}
            ],
        }

        logger.info("Starting Together animation: model=%s, %dx%d, %ds", self.model, self.width, self.height, self.seconds)

        try:
            resp = requests.post(
                f"{self.api_url}/v2/videos",
                json=payload,
                headers=self._headers(),
                timeout=60)
        except Exception as e:
            logger.error("Together API connection error: %s", e)
            return False

        if resp.status_code not in (200, 201, 202):
            logger.error("Together video job failed: HTTP %d - %s", resp.status_code, resp.text[:500])
            return False

        job = resp.json()
        job_id = job.get("id", "")
        if not job_id:
            logger.error("No job id received: %s", str(job)[:300])
            return False

        logger.info("Together video job created: %s", job_id)

        # 3. Poll for the result
        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            try:
                poll_resp = requests.get(
                    f"{self.api_url}/v2/videos/{job_id}",
                    headers=self._headers(),
                    timeout=30)
                if poll_resp.status_code != 200:
                    logger.warning("Together poll HTTP %d", poll_resp.status_code)
                    continue

                status_data = poll_resp.json()
                status = status_data.get("status", "")

                if status == "failed":
                    error_info = status_data.get("error", {})
                    logger.error("Together video failed: %s", str(error_info)[:300])
                    return False

                if status == "completed":
                    outputs = status_data.get("outputs", {})
                    video_url = outputs.get("video_url", "")
                    if not video_url:
                        logger.error("No video_url in Together response")
                        return False

                    logger.info("Together video ready after %.1fs, downloading...", time.time() - start)

                    # Download the video
                    try:
                        dl_resp = requests.get(video_url, timeout=120)
                        if dl_resp.status_code == 200 and len(dl_resp.content) > 1000:
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                            Path(output_path).write_bytes(dl_resp.content)
                            logger.info("Video saved: %s (%d bytes)", output_path, len(dl_resp.content))
                            return True
                        logger.error("Video download failed: HTTP %d, %d bytes",
                                     dl_resp.status_code, len(dl_resp.content))
                    except Exception as e:
                        logger.error("Video download error: %s", e)
                    return False

                # queued / in_progress → keep waiting
                logger.debug("Together status: %s (%.0fs)", status, time.time() - start)

            except Exception as e:
                logger.warning("Together poll error: %s", e)
                continue

        logger.error("Together animation timeout after %ds", self.max_wait)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Service registry & public API
# ═══════════════════════════════════════════════════════════════════════════

_services: Optional[Dict[str, AnimateService]] = None


def _load_services() -> Dict[str, AnimateService]:
    """Initializes all configured animation services."""
    global _services
    if _services is not None:
        return _services

    _services = {}

    together = TogetherAnimateService()
    if together.enabled:
        _services[together.service_id] = together
        logger.info("Animation service loaded: %s (%s)", together.service_id, together.label)

    if not _services:
        logger.warning("No animation services enabled")

    return _services


def reload_animate_services() -> None:
    """Resets the service cache so services are reloaded on the next call."""
    global _services
    _services = None
    logger.info("Animation services cache reset")


def get_animate_services() -> List[Dict[str, Any]]:
    """Returns the list of available animation services for the frontend."""
    services = _load_services()
    return [svc.info() for svc in services.values()]


def animate_image(
    source_image_path: str,
    prompt: str,
    output_path: str,
    service: str = "") -> bool:
    """Animates an image as a video.

    Args:
        source_image_path: Path to the source image.
        prompt: Text prompt for the animation.
        output_path: Output path for the video.
        service: Service id ("together"). Empty = first available.

    Returns:
        True on success, False on error.
    """
    services = _load_services()
    if not services:
        logger.error("No animation services available")
        return False

    if service and service in services:
        svc = services[service]
    elif service:
        logger.warning("Unknown animation service '%s', using default", service)
        svc = next(iter(services.values()))
    else:
        svc = next(iter(services.values()))

    logger.info("Animation with service '%s' (%s)", svc.service_id, svc.label)
    return svc.animate(source_image_path, prompt, output_path)
