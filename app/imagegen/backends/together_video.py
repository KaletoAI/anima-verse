"""Together.ai image-to-video backend (Kling, Wan, … via the Together API).

Migrated from the standalone ``app/skills/animate.py`` service into the
ImageBackend architecture so video runs through the same BackendPool /
matching / fallback / per-backend queue as image generation. ``MEDIA_TYPE ==
"video"`` keeps it out of image matching. ``_generate`` takes the first-frame
image from ``params`` (reference-image slot or ``source_image_path``) plus the
action prompt and returns one MP4 as a single-element ``List[bytes]``.

API: POST {api_url}/v2/videos → job id → poll {api_url}/v2/videos/{id} →
download ``outputs.video_url``.
"""
import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")


def _find_together_api_key() -> str:
    """Fallback: pull a Together API key from the PROVIDER_* configuration."""
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


class TogetherVideoBackend(ImageBackend):
    """Together.ai video generation (image-to-video)."""

    MEDIA_TYPE = "video"
    # One first-frame reference image (the rendered still).
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url or "https://api.together.xyz", cost,
                         api_type="together_video", env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "768") or 768)
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "768") or 768)
        self.seconds = int(os.environ.get(f"{env_prefix}SECONDS", "5") or 5)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "600") or 600)
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "60") or 60)
        # Fall back to a Together provider's key when none is set on the backend.
        if not self.api_key:
            self.api_key = _find_together_api_key()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def check_availability(self) -> bool:
        if not self.api_key or not self.model:
            self._mark_unavailable("kein API_KEY/MODEL")
            return False
        try:
            resp = requests.get(f"{self.api_url}/v1/models",
                                headers=self._headers(), timeout=10)
            if resp.status_code in (401, 403):
                self._mark_unavailable(f"API-Key ungueltig ({resp.status_code})")
                return False
            if resp.status_code == 200:
                self._mark_available(f"Together video, Modell: {self.model}")
                return True
            self._mark_unavailable(f"HTTP {resp.status_code}")
            return False
        except requests.ConnectionError:
            self._mark_unavailable("ConnectionError")
            return False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self._mark_unavailable(str(e))
            return False

    @staticmethod
    def _first_frame_data_uri(params: Dict[str, Any]) -> str:
        """First-frame image as a data: URI. Source: the first reference-image
        slot, else ``source_image_path``."""
        src = ""
        refs = params.get("reference_images") or {}
        if isinstance(refs, dict):
            for _title, path in refs.items():
                if path:
                    src = str(path)
                    break
        src = src or str(params.get("source_image_path") or "")
        if not src:
            return ""
        p = Path(src)
        if not p.exists():
            logger.error("together_video: Quellbild fehlt: %s", src)
            return ""
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp"}.get(p.suffix.lower().lstrip("."), "image/png")
        b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        data_uri = self._first_frame_data_uri(params)
        if not data_uri:
            logger.error("%s: kein Quellbild fuer die Animation", self.name)
            return []

        payload: Dict[str, Any] = {
            "model": params.get("model") or self.model,
            "prompt": prompt,
            "width": params.get("width") or self.width,
            "height": params.get("height") or self.height,
            "seconds": params.get("seconds") or self.seconds,
            "output_format": "MP4",
            "frame_images": [{"input_image": data_uri, "frame": "first"}],
        }
        logger.info("%s: starte Video (Modell=%s, %dx%d, %ds)", self.name,
                    payload["model"], payload["width"], payload["height"],
                    payload["seconds"])
        try:
            resp = requests.post(f"{self.api_url}/v2/videos", json=payload,
                                 headers=self._headers(), timeout=self.timeout)
        except Exception as e:
            logger.error("%s: Verbindungsfehler: %s", self.name, e)
            return []
        if resp.status_code not in (200, 201, 202):
            logger.error("%s: Video-Job fehlgeschlagen HTTP %d - %s",
                         self.name, resp.status_code, resp.text[:300])
            return []
        job_id = (resp.json() or {}).get("id", "")
        if not job_id:
            logger.error("%s: keine Job-ID erhalten", self.name)
            return []

        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            try:
                poll = requests.get(f"{self.api_url}/v2/videos/{job_id}",
                                    headers=self._headers(), timeout=30)
                if poll.status_code != 200:
                    continue
                sd = poll.json()
                status = sd.get("status", "")
                if status == "failed":
                    logger.error("%s: Video failed: %s", self.name,
                                 str(sd.get("error", ""))[:300])
                    return []
                if status == "completed":
                    url = (sd.get("outputs") or {}).get("video_url", "")
                    if not url:
                        logger.error("%s: keine video_url in Response", self.name)
                        return []
                    dl = requests.get(url, timeout=120)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        logger.info("%s: Video fertig (%.1fs, %d bytes)", self.name,
                                    time.time() - start, len(dl.content))
                        return [dl.content]
                    logger.error("%s: Download fehlgeschlagen HTTP %d", self.name,
                                 dl.status_code)
                    return []
            except Exception as e:
                logger.warning("%s: Poll-Fehler: %s", self.name, e)
                continue
        logger.error("%s: Timeout nach %ds", self.name, self.max_wait)
        return []
