"""Rigged GLB animation through the gateway generations/jobs API."""
import base64
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.backends._gateway_job import poll_job, submit_job
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")
UPLOAD_MAX_BYTES = 64 * 1024 * 1024
GLB_MIME = "model/gltf-binary"


class OpenAIMeshAnimationBackend(ImageBackend):
    """Text-to-motion on an existing rigged GLB (gateway alias mesh-unimate)."""

    MEDIA_TYPE = "animation"

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str):
        super().__init__(name, api_url, cost, api_type="openai_mesh_animation",
                         env_prefix=env_prefix)
        self.api_key = os.environ.get(f"{env_prefix}API_KEY", "").strip()
        self.model = os.environ.get(f"{env_prefix}MODEL", "").strip()
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120") or 120)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.max_queue_wait = int(
            os.environ.get(f"{env_prefix}MAX_QUEUE_WAIT", "0") or 0) or self.max_wait * 4
        self.mesh_endpoint = (os.environ.get(f"{env_prefix}MESH_ENDPOINT", "")
                              or "/v1/generations").strip().rstrip("/")
        extra = json.loads(os.environ.get(f"{env_prefix}EXTRA_PARAMS", "") or "{}")
        self.extra_params = {k: v for k, v in extra.items()
                             if k in ("input_cfg_scale", "input_chain_overlap")}
        if not self.category:
            self.category = "mesh2anim"
        self._tls = threading.local()

    @property
    def last_job_id(self) -> str:
        """The latest submitted job ID on the current worker thread."""
        return getattr(self._tls, "job_id", "")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def check_availability(self) -> bool:
        if not self.model:
            logger.warning("%s: no model/alias configured", self.name)
            self._mark_unavailable()
            return False
        try:
            r = requests.get(f"{self.api_url}/v1/models",
                             headers=self._headers(), timeout=10)
            if r.status_code in (401, 403):
                logger.warning("%s: authentication rejected (HTTP %d)",
                               self.name, r.status_code)
                self._mark_unavailable()
                return False
            if r.status_code != 200:
                self._mark_unavailable()
                return False
        except Exception as e:
            logger.debug("%s: not reachable: %s", self.name, e)
            self._mark_unavailable()
            return False
        self._mark_available()
        return True

    def _read_source(self, path: str) -> bytes:
        p = Path(path or "")
        if not path or not p.is_file():
            raise ValueError("source model missing")
        size = p.stat().st_size
        if size > UPLOAD_MAX_BYTES:
            raise ValueError(f"source model exceeds 64 MiB ({size} bytes)")
        raw = p.read_bytes()
        if raw[:4] != b"glTF":
            raise ValueError("source model is not a binary glTF")
        return raw

    def _generate(self, prompt, negative_prompt, params):
        self._tls.job_id = ""
        raw = self._read_source(params.get("source_model_path"))
        captions = [str(c) for c in (params.get("captions") or [])]
        if not 1 <= len(captions) <= 3:
            raise ValueError("1..3 captions required")
        alias_params = {"seed": int(params["seed"]), "input_num_repetitions": 1}
        alias_params.update(self.extra_params)
        payload = {"model": params.get("model") or self.model, "mode": "async",
                   "prompt": "\n".join(captions), "params": alias_params,
                   "files": {"input_mesh_path": "data:" + GLB_MIME + ";base64,"
                             + base64.b64encode(raw).decode()}}
        job_id = submit_job(self, f"{self.api_url}{self.mesh_endpoint}", payload, "Animation")
        if not job_id:
            return []
        self._tls.job_id = job_id
        cb = params.get("on_job_id")
        if callable(cb):
            cb(job_id)
        return poll_job(self, job_id, max_wait=self.max_wait,
                        max_queue_wait=self.max_queue_wait,
                        poll_interval=self.poll_interval,
                        should_cancel=params.get("should_cancel"),
                        on_done=lambda sd, _s: self._download(sd, job_id))

    def _download(self, sd, job_id: str) -> List[bytes]:
        results = [r for r in (sd.get("results") or [])
                   if isinstance(r, dict) and r.get("mime") == GLB_MIME]
        if len(results) != 1:
            logger.error("%s: job %s expected exactly one result, got %d",
                         self.name, job_id, len(results))
            return []
        res = results[0]
        dl = requests.get(f"{self.api_url}/v1/jobs/{job_id}/result/{res.get('n', 0)}",
                          headers=self._headers(), timeout=300, allow_redirects=False)
        if dl.status_code != 200:
            logger.error("%s: result download HTTP %d", self.name, dl.status_code)
            return []
        blob = dl.content
        want = res.get("sha256")
        if not isinstance(want, str) or re.fullmatch(r"[0-9a-fA-F]{64}", want) is None:
            logger.error("%s: result sha256 missing or malformed — job discarded", self.name)
            return []
        if hashlib.sha256(blob).hexdigest() != want.lower():
            logger.error("%s: result sha256 mismatch — job discarded", self.name)
            return []
        if blob[:4] != b"glTF":
            logger.error("%s: result is not a binary glTF", self.name)
            return []
        return [blob]
