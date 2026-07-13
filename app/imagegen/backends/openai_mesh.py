"""LLM-gateway image-to-mesh backend (gateway generations/jobs API).

3D counterpart of ``OpenAIVideoBackend``: the gateway hosts an image-to-3D
workflow under a generation alias (e.g. ``Trellis2-Low``). Same async API,
but ONE input image, NO prompt and alias-specific params. Per the alias
schema (``GET /v1/generations/Trellis2-Low/schema``):

    POST {api_url}/v1/generations            JSON:
        {"model": alias,
         "images": {"input_image": <base64|http-URL>},
         "params": {"name": …, "remove background": true,
                    "face num": 20000, "no fingers": true},
         "mode": "async"}
        → 202 {"job_id": …}   (429/503 carry Retry-After)
    GET  {api_url}/v1/jobs/{job_id}           queued|running|done|failed
    POST {api_url}/v1/jobs/{job_id}/cancel

The ``name`` param names the produced asset — the gateway returns e.g.
``<name>_mia.fbx``. Meshing takes minutes → always ``mode:"async"`` + polling.
``MEDIA_TYPE == "mesh"`` keeps it out of image/video matching; the central
``generate()`` skips image post-processing for it. Returns the model file as
a single-element ``List[bytes]``; the file NAME (and thus the format) of the
last result is exposed via ``last_result_name`` (thread-local).
"""
import base64
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")


class OpenAIMeshBackend(ImageBackend):
    """Gateway image-to-mesh via /v1/generations + /v1/jobs (async)."""

    MEDIA_TYPE = "mesh"
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="openai_mesh",
                         env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120") or 120)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.mesh_endpoint = (os.environ.get(f"{env_prefix}MESH_ENDPOINT", "")
                              or "/v1/generations").strip().rstrip("/")
        # Alias params (schema: "remove background" / "face num" / "no fingers")
        self.remove_background = str(
            os.environ.get(f"{env_prefix}REMOVE_BACKGROUND", "true")).strip().lower() \
            not in ("0", "false", "no", "off")
        self.no_fingers = str(
            os.environ.get(f"{env_prefix}NO_FINGERS", "true")).strip().lower() \
            not in ("0", "false", "no", "off")
        self.face_num = int(os.environ.get(f"{env_prefix}FACE_NUM", "20000") or 20000)
        # Alias self-discovery (image slot name); safe fallback without schema.
        self._image_slot: str = ""
        self._tls = threading.local()

    # -- result naming ------------------------------------------------------
    @property
    def last_result_name(self) -> str:
        """File name of the last downloaded result (thread-local, e.g.
        ``Bianca_mia.fbx``) — carries the FORMAT the gateway produced."""
        return getattr(self._tls, "result_name", "") or ""

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def check_availability(self) -> bool:
        if not self.model:
            logger.warning("%s: kein Model/Alias konfiguriert", self.name)
            self._mark_unavailable()
            return False
        try:
            r = requests.get(f"{self.api_url}/v1/models",
                             headers=self._headers(), timeout=10)
            if r.status_code in (401, 403):
                logger.warning("%s: Auth abgelehnt (HTTP %d)", self.name, r.status_code)
                self._mark_unavailable()
                return False
            if r.status_code != 200:
                self._mark_unavailable()
                return False
        except Exception as e:
            logger.debug("%s: nicht erreichbar: %s", self.name, e)
            self._mark_unavailable()
            return False
        self._mark_available()
        self._fetch_alias_schema()
        return True

    def _fetch_alias_schema(self) -> None:
        """Reads the image slot name from the alias schema (e.g. input_image)."""
        try:
            r = requests.get(f"{self.api_url}/v1/generations/{self.model}/schema",
                             headers=self._headers(), timeout=10)
            if r.status_code != 200:
                return
            sd = r.json() if r.content else {}
            images = sd.get("images") or []
            if isinstance(images, list) and images:
                first = images[0]
                slot = (first.get("name") if isinstance(first, dict) else str(first)) or ""
                if slot:
                    self._image_slot = slot
            elif isinstance(images, dict) and images:
                self._image_slot = next(iter(images))
            logger.info("%s: Alias-Schema gelesen (image_slot=%s)",
                        self.name, self._image_slot or "input_image")
        except Exception as e:
            logger.debug("%s: Alias-Schema nicht lesbar: %s", self.name, e)

    @staticmethod
    def _input_image(params: Dict[str, Any]) -> str:
        """Local path / URL of the single input image (reference slot first)."""
        refs = params.get("reference_images") or {}
        if isinstance(refs, dict):
            for path in refs.values():
                if path:
                    return str(path)
        return str(params.get("source_image_path") or "")

    def _result_name_from(self, url: str, resp: requests.Response) -> str:
        cd = resp.headers.get("Content-Disposition", "") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
        if m:
            return unquote(m.group(1)).strip()
        return unquote(Path(urlparse(url).path).name or "")

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        self._tls.result_name = ""
        src = self._input_image(params)
        image_val = ""
        if src.startswith(("http://", "https://")):
            image_val = src
        elif src:
            p = Path(src)
            if not p.exists():
                logger.error("%s: Eingangsbild fehlt: %s", self.name, src)
                return []
            image_val = base64.b64encode(p.read_bytes()).decode("utf-8")
        if not image_val:
            logger.error("%s: kein Eingangsbild fuer die Mesh-Generierung", self.name)
            return []

        # Param keys are the alias-schema names (with spaces) — sent verbatim.
        alias_params: Dict[str, Any] = {
            "name": str(params.get("mesh_name") or "").strip(),
            "remove background": bool(params.get("remove_background",
                                                 self.remove_background)),
            "face num": int(params.get("face_num") or self.face_num),
            "no fingers": bool(params.get("no_fingers", self.no_fingers)),
        }
        payload: Dict[str, Any] = {
            "model": params.get("model") or self.model,
            "images": {self._image_slot or "input_image": image_val},
            "params": alias_params,
            "mode": "async",
        }

        url = f"{self.api_url}{self.mesh_endpoint}"
        logger.info("%s: starte Mesh-Job (Alias=%s, faces=%d, name='%s')",
                    self.name, payload["model"], alias_params["face num"],
                    alias_params["name"])
        resp = None
        for _attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=self._headers(),
                                     timeout=self.timeout)
            except Exception as e:
                logger.error("%s: Verbindungsfehler: %s", self.name, e)
                return []
            if resp.status_code in (429, 503) and _attempt < 2:
                try:
                    wait_s = min(120.0, float(resp.headers.get("Retry-After", "10")))
                except (TypeError, ValueError):
                    wait_s = 10.0
                logger.info("%s: Gateway busy (HTTP %d) — retry in %.0fs",
                            self.name, resp.status_code, wait_s)
                time.sleep(wait_s)
                continue
            break
        if resp is None or resp.status_code not in (200, 201, 202):
            logger.error("%s: Mesh-Request HTTP %s - %s", self.name,
                         getattr(resp, "status_code", "?"),
                         (resp.text[:300] if resp is not None else ""))
            return []
        body = resp.json() if resp.content else {}
        job_id = str(body.get("job_id") or body.get("id") or "") if isinstance(body, dict) else ""
        if not job_id:
            logger.error("%s: keine job_id in Response: %s", self.name, str(body)[:200])
            return []

        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            try:
                poll = requests.get(f"{self.api_url}/v1/jobs/{job_id}",
                                    headers=self._headers(), timeout=30)
                if poll.status_code != 200:
                    logger.debug("%s: Job-Poll HTTP %d", self.name, poll.status_code)
                    continue
                sd = poll.json() if poll.content else {}
                status = (sd.get("status") or "").lower() if isinstance(sd, dict) else ""
                if status in ("failed", "error"):
                    logger.error("%s: Mesh-Job failed: %s", self.name,
                                 str(sd.get("error") or sd)[:300])
                    return []
                if status == "running" and sd.get("progress") is not None:
                    logger.info("%s: Job %s laeuft — %.0f%% (ETA %ss)", self.name,
                                job_id, float(sd.get("progress") or 0) * 100,
                                sd.get("eta_s", "?"))
                if status in ("done", "completed"):
                    _results = sd.get("results") or []
                    _first = _results[0] if _results and isinstance(_results[0], dict) else {}
                    _r_url = (_first.get("url") or "")
                    if _r_url and not _r_url.startswith(("http://", "https://")):
                        _r_url = f"{self.api_url}{_r_url}"
                    if not _r_url:
                        _r_url = f"{self.api_url}/v1/jobs/{job_id}/result/0"
                    dl = requests.get(_r_url, headers=self._headers(), timeout=300)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        self._tls.result_name = (
                            str(_first.get("filename") or _first.get("name") or "")
                            or self._result_name_from(_r_url, dl))
                        logger.info("%s: Mesh fertig (%.1fs, %d bytes, %s)",
                                    self.name, time.time() - start, len(dl.content),
                                    self.last_result_name or "?")
                        return [dl.content]
                    logger.error("%s: Result-Download HTTP %d (%d bytes)",
                                 self.name, dl.status_code, len(dl.content))
                    return []
            except Exception as e:
                logger.warning("%s: Poll-Fehler: %s", self.name, e)
                continue
        logger.error("%s: Timeout nach %ds — Job %s wird abgebrochen",
                     self.name, self.max_wait, job_id)
        try:
            requests.post(f"{self.api_url}/v1/jobs/{job_id}/cancel",
                          headers=self._headers(), timeout=10)
        except Exception:
            pass
        return []
