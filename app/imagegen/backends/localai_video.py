"""LocalAI / OpenAI-compatible gateway image-to-video backend (e.g. WAN-LowRAM).

Video counterpart of ``LocalAIBackend``: talks to the same LLM gateway
(LocalAI) that serves the video model under an alias (``model=WAN-LowRAM``).
``MEDIA_TYPE == "video"`` keeps it out of image matching; ``_generate`` sends
the rendered still (first frame) plus the action prompt and returns one MP4 as
a single-element ``List[bytes]``.

There is no official OpenAI *video* standard, so the request/response shape is
kept deliberately flexible and configurable:
  - ``VIDEO_ENDPOINT`` (config ``video_endpoint``): request path, default
    ``/v1/videos/generations``. Point it at ``/v1/images/generations`` if the
    gateway serves the video model through the images endpoint.
  - Response handling auto-detects both shapes: a **synchronous** body with the
    video inline (``b64_json`` / ``url`` / ``video_url`` in ``data[]`` or at the
    top level) OR an **asynchronous** job (``id``/``task_id`` + ``status``),
    which is then polled until ``completed``.
Adjust the payload once the gateway's exact WAN API is known — that is a
one-file change, the rest of the pipeline is agnostic.
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


class LocalAIVideoBackend(ImageBackend):
    """WAN-style image-to-video via a LocalAI/OpenAI-compatible gateway."""

    MEDIA_TYPE = "video"
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="localai_video",
                         env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "768") or 768)
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "768") or 768)
        self.seconds = int(os.environ.get(f"{env_prefix}SECONDS", "5") or 5)
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "300") or 300)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "600") or 600)
        self.video_endpoint = (os.environ.get(f"{env_prefix}VIDEO_ENDPOINT", "")
                               or "/v1/videos/generations").strip()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_availability(self) -> bool:
        # No api_key needed for LocalAI — check reachability + configured model.
        if not self.model:
            self._mark_unavailable("kein MODEL")
            return False
        try:
            resp = requests.get(f"{self.api_url}/v1/models",
                                headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                self._mark_available(f"LocalAI video, Modell: {self.model}")
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
    def _first_frame_b64(params: Dict[str, Any]) -> str:
        """First-frame image as raw base64 (no data: prefix — LocalAI style).
        Source: first reference-image slot, else ``source_image_path``."""
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
        if src.startswith("data:"):
            return src.split(",", 1)[1] if "," in src else src
        p = Path(src)
        if not p.exists():
            logger.error("localai_video: Quellbild fehlt: %s", src)
            return ""
        return base64.b64encode(p.read_bytes()).decode("utf-8")

    def _extract_video(self, body: Any) -> Optional[bytes]:
        """Pull the MP4 out of a synchronous response body (b64 or URL)."""
        items = []
        if isinstance(body, dict):
            data = body.get("data")
            items = data if isinstance(data, list) else [body]
        for item in items:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json") or item.get("video") or ""
            if b64:
                try:
                    return base64.b64decode(b64)
                except Exception:
                    pass
            url = item.get("url") or item.get("video_url") or ""
            if url:
                try:
                    dl = requests.get(url, timeout=120)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        return dl.content
                except Exception as e:
                    logger.error("%s: Video-Download-Fehler: %s", self.name, e)
        return None

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        image_b64 = self._first_frame_b64(params)
        if not image_b64:
            logger.error("%s: kein Quellbild fuer die Animation", self.name)
            return []

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "seconds": params.get("seconds") or self.seconds,
            # First frame — sent as raw base64 (LocalAI/Flux convention). If the
            # gateway wants a different field name, adjust here.
            "image": image_b64,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        url = f"{self.api_url}{self.video_endpoint}"
        logger.info("%s: starte Video (Modell=%s, %dx%d, %s)", self.name, model,
                    width, height, self.video_endpoint)
        try:
            resp = requests.post(url, json=payload, headers=self._headers(),
                                 timeout=self.timeout)
        except Exception as e:
            logger.error("%s: Verbindungsfehler: %s", self.name, e)
            return []
        if resp.status_code not in (200, 201, 202):
            logger.error("%s: Video-Request HTTP %d - %s", self.name,
                         resp.status_code, resp.text[:300])
            return []

        body = resp.json() if resp.content else {}

        # Synchronous: video already in the body.
        video = self._extract_video(body)
        if video:
            return [video]

        # Asynchronous: a job id + status -> poll until completed.
        job_id = ""
        if isinstance(body, dict):
            job_id = str(body.get("id") or body.get("task_id") or "")
        if not job_id:
            logger.error("%s: keine Video-Daten und keine Job-ID in Response",
                         self.name)
            return []

        poll_base = url.rsplit("/", 1)[0] if "/" in self.video_endpoint else url
        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            try:
                poll = requests.get(f"{poll_base}/{job_id}",
                                    headers=self._headers(), timeout=30)
                if poll.status_code != 200:
                    continue
                sd = poll.json()
                status = (sd.get("status") or "").lower() if isinstance(sd, dict) else ""
                if status in ("failed", "error"):
                    logger.error("%s: Video failed: %s", self.name,
                                 str(sd.get("error", ""))[:300])
                    return []
                video = self._extract_video(sd)
                if video:
                    logger.info("%s: Video fertig (%.1fs)", self.name,
                                time.time() - start)
                    return [video]
            except Exception as e:
                logger.warning("%s: Poll-Fehler: %s", self.name, e)
                continue
        logger.error("%s: Timeout nach %ds", self.name, self.max_wait)
        return []
