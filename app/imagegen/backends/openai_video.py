"""LLM-gateway image-to-video backend — strict OpenAI video API.

Video counterpart of ``OpenAIDiffusionBackend``: the gateway hosts a video
workflow (e.g. a ComfyUI img2video graph) under a generation alias and exposes
it via the OpenAI video endpoints:

    POST {api_url}/v1/videos                (multipart: model, prompt, seconds,
                                             size, input_reference = first frame)
    GET  {api_url}/v1/videos/{id}           (status: queued|in_progress|completed|failed)
    GET  {api_url}/v1/videos/{id}/content   (MP4 bytes)

``MEDIA_TYPE == "video"`` keeps it out of image matching. A Bearer header is
sent whenever an api_key is configured (gateways on a trusted network may run
keyless). Tolerant response handling: a synchronous body carrying the video
inline (``b64_json``/``url``/``video_url``) is accepted too, and the endpoint
path is overridable via ``video_endpoint`` for gateway deviations.
"""
import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")


class OpenAIVideoBackend(ImageBackend):
    """Gateway image-to-video via the OpenAI-style /v1/videos API."""

    MEDIA_TYPE = "video"
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="openai_video",
                         env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "768") or 768)
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "768") or 768)
        self.seconds = int(os.environ.get(f"{env_prefix}SECONDS", "5") or 5)
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "300") or 300)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.video_endpoint = (os.environ.get(f"{env_prefix}VIDEO_ENDPOINT", "")
                               or "/v1/videos").strip().rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def check_availability(self) -> bool:
        if not self.model:
            self._mark_unavailable("kein MODEL (Gateway-Video-Alias)")
            return False
        try:
            resp = requests.get(f"{self.api_url}/v1/models",
                                headers=self._headers(), timeout=10)
            if resp.status_code in (401, 403):
                self._mark_unavailable(f"API-Key ungueltig ({resp.status_code})")
                return False
            if resp.status_code == 200:
                self._mark_available(f"OpenAI video, Alias: {self.model}")
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
    def _first_frame_path(params: Dict[str, Any]) -> str:
        """Path of the first-frame still: first reference-image slot, else
        ``source_image_path``."""
        refs = params.get("reference_images") or {}
        if isinstance(refs, dict):
            for _title, path in refs.items():
                if path:
                    return str(path)
        return str(params.get("source_image_path") or "")

    def _extract_inline_video(self, body: Any) -> Optional[bytes]:
        """MP4 from a synchronous response body (b64 or URL) — gateway shortcut."""
        items = []
        if isinstance(body, dict):
            data = body.get("data")
            items = data if isinstance(data, list) else [body]
        for item in items:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json") or item.get("video") or ""
            if b64 and isinstance(b64, str):
                try:
                    return base64.b64decode(b64)
                except Exception:
                    pass
            url = item.get("url") or item.get("video_url") or ""
            if url:
                try:
                    dl = requests.get(url, headers=self._headers(), timeout=120)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        return dl.content
                except Exception as e:
                    logger.error("%s: Video-Download-Fehler: %s", self.name, e)
        return None

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        src = self._first_frame_path(params)
        p = Path(src) if src else None
        if not p or not p.exists():
            logger.error("%s: kein Quellbild fuer die Animation (%r)", self.name, src)
            return []

        width = params.get("width") or self.width
        height = params.get("height") or self.height
        data = {
            "model": params.get("model") or self.model,
            "prompt": prompt,
            "seconds": str(params.get("seconds") or self.seconds),
            "size": f"{width}x{height}",
        }
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp"}.get(p.suffix.lower().lstrip("."), "image/png")
        url = f"{self.api_url}{self.video_endpoint}"
        logger.info("%s: starte Video (Alias=%s, %sx%s, %ss)", self.name,
                    data["model"], width, height, data["seconds"])
        try:
            with open(p, "rb") as fh:
                resp = requests.post(
                    url, data=data,
                    files={"input_reference": (p.name, fh, mime)},
                    headers=self._headers(), timeout=self.timeout)
        except Exception as e:
            logger.error("%s: Verbindungsfehler: %s", self.name, e)
            return []
        if resp.status_code not in (200, 201, 202):
            logger.error("%s: Video-Request HTTP %d - %s", self.name,
                         resp.status_code, resp.text[:300])
            return []

        body = resp.json() if resp.content else {}

        # Gateway shortcut: video already inline.
        video = self._extract_inline_video(body)
        if video:
            return [video]

        job_id = str(body.get("id") or "") if isinstance(body, dict) else ""
        if not job_id:
            logger.error("%s: keine Video-Daten und keine Job-ID in Response",
                         self.name)
            return []

        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            try:
                poll = requests.get(f"{url}/{job_id}",
                                    headers=self._headers(), timeout=30)
                if poll.status_code != 200:
                    continue
                sd = poll.json()
                status = (sd.get("status") or "").lower() if isinstance(sd, dict) else ""
                if status in ("failed", "error"):
                    logger.error("%s: Video failed: %s", self.name,
                                 str(sd.get("error", ""))[:300])
                    return []
                if status == "completed":
                    # Spec path: dedicated content endpoint. Fallback: inline.
                    try:
                        dl = requests.get(f"{url}/{job_id}/content",
                                          headers=self._headers(), timeout=120)
                        if dl.status_code == 200 and len(dl.content) > 1000:
                            logger.info("%s: Video fertig (%.1fs, %d bytes)",
                                        self.name, time.time() - start,
                                        len(dl.content))
                            return [dl.content]
                    except Exception as e:
                        logger.warning("%s: /content-Download fehlgeschlagen: %s",
                                       self.name, e)
                    video = self._extract_inline_video(sd)
                    if video:
                        return [video]
                    logger.error("%s: completed, aber kein Video abrufbar", self.name)
                    return []
            except Exception as e:
                logger.warning("%s: Poll-Fehler: %s", self.name, e)
                continue
        logger.error("%s: Timeout nach %ds", self.name, self.max_wait)
        return []
