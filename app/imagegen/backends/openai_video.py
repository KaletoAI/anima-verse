"""LLM-gateway image-to-video backend (gateway generations/jobs API).

Video counterpart of ``OpenAIDiffusionBackend`` for the LLM gateway: the
gateway hosts a video workflow (e.g. a ComfyUI Wan img2video graph) under a
generation alias. API (gateway spec, e.g. alias ``Wan-LowRAM``):

    POST {api_url}/v1/generations            JSON:
        {"model": alias, "prompt": …, "images": {"image": <base64|http-URL>},
         "params": {"frames": N}, "mode": "async",
         "negative_prompt"?: …, "lora1_high"/"lora1_high_strength" +
         "lora1_low"/"lora1_low_strength" … "lora3_*"}
        → 202 {"job_id": …, "status": "queued"}
    GET  {api_url}/v1/jobs/{job_id}           status: queued|running|done|failed
    GET  {api_url}/v1/jobs/{job_id}/result/0  the MP4 (owner-gated: the key
                                              that created the job)
    POST {api_url}/v1/jobs/{job_id}/cancel

Generation takes MINUTES → always ``mode:"async"`` + polling. ``MEDIA_TYPE ==
"video"`` keeps it out of image matching. A Bearer header is sent whenever an
api_key is configured (same key as chat; note the owner-gated result
download). Wan LoRAs come in HIGH/LOW pairs — the dialog's flat {name,
strength} selections are auto-paired into ``lora{n}_high``/``lora{n}_low`` by
the high/low token in the filename. Valid names: the alias' LoRA endpoint
(``fetch_loras``).
"""
import base64
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")

# Frames per second of the Wan graphs — the gateway takes a FRAME count
# (default 81 ≈ 5 s); the backend maps its `seconds` field onto frames.
_WAN_FPS = 16


class OpenAIVideoBackend(ImageBackend):
    """Gateway image-to-video via /v1/generations + /v1/jobs (async)."""

    MEDIA_TYPE = "video"
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="openai_video",
                         env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "0") or 0)
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "0") or 0)
        self.seconds = int(os.environ.get(f"{env_prefix}SECONDS", "5") or 5)
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120") or 120)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.video_endpoint = (os.environ.get(f"{env_prefix}VIDEO_ENDPOINT", "")
                               or "/v1/generations").strip().rstrip("/")
        # LoRA discovery: GET {lora_url}/v1/generations/{alias}/loras (same
        # convention as the gateway image backends), narrowed by lora_filter.
        self.lora_url = os.environ.get(f"{env_prefix}LORA_URL", "").strip()
        self.lora_filter = os.environ.get(f"{env_prefix}LORA_FILTER", "").strip()
        self.available_loras: List[str] = []

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
                self._mark_available(f"Gateway video, Alias: {self.model}")
                if self.lora_url:
                    self.fetch_loras()
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

    def fetch_loras(self) -> List[str]:
        """LoRAs of the video alias (GET -> {"loras": [...]}), narrowed by
        ``lora_filter``."""
        if not self.lora_url or not self.model:
            return self.available_loras
        url = (self.lora_url.replace("{alias}", self.model)
               if "{alias}" in self.lora_url
               else f"{self.lora_url.rstrip('/')}/v1/generations/{self.model}/loras")
        try:
            resp = requests.get(url, headers=self._headers(), timeout=10)
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
                    logger.info("%s: %d LoRA(s) vom Endpoint geladen%s", self.name,
                                len(names),
                                f" (Filter '{self.lora_filter}')" if self.lora_filter else "")
            else:
                logger.warning("%s: LoRA-Abfrage HTTP %d", self.name, resp.status_code)
        except Exception as e:
            logger.warning("%s: LoRA-Abfrage fehlgeschlagen: %s", self.name, e)
        return self.available_loras

    @staticmethod
    def _apply_lora_params(payload: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Maps flat dialog selections ({name, strength}) onto the gateway's
        Wan HIGH/LOW pair labels: ``lora{n}_high``/``lora{n}_high_strength`` +
        ``lora{n}_low``/``lora{n}_low_strength`` (n = 1..3).

        Files carrying a high/low token in the name are paired by their base
        name (token stripped) — selecting the HIGH and LOW variant of the same
        LoRA in two dialog slots lands them in ONE pair slot. A file without a
        recognizable token occupies both halves of its slot (the gateway may
        ignore the irrelevant half)."""
        _tok = re.compile(r'(high|low)', re.IGNORECASE)
        slots: List[Dict[str, Any]] = []
        by_base: Dict[str, int] = {}
        for l in (params.get("lora_inputs") or params.get("loras") or []):
            if not isinstance(l, dict):
                continue
            name = (l.get("name") or "").strip()
            if not name or name == "None":
                continue
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            m = _tok.search(name)
            kind = m.group(1).lower() if m else ""
            base = _tok.sub("*", name).lower() if m else name.lower()
            if base in by_base:
                slot = slots[by_base[base]]
            else:
                if len(slots) >= 3:
                    logger.warning("openai_video: mehr als 3 LoRA-Paare — '%s' ignoriert", name)
                    continue
                slot = {"high": "", "high_s": 1.0, "low": "", "low_s": 1.0}
                by_base[base] = len(slots)
                slots.append(slot)
            if kind == "low":
                slot["low"], slot["low_s"] = name, strength
            elif kind == "high":
                slot["high"], slot["high_s"] = name, strength
            else:
                # No token — use for both halves.
                slot["high"], slot["high_s"] = name, strength
                slot["low"], slot["low_s"] = name, strength
        for n, slot in enumerate(slots, start=1):
            if slot["high"]:
                payload[f"lora{n}_high"] = slot["high"]
                payload[f"lora{n}_high_strength"] = slot["high_s"]
            if slot["low"]:
                payload[f"lora{n}_low"] = slot["low"]
                payload[f"lora{n}_low_strength"] = slot["low_s"]
        if slots:
            logger.info("openai_video: %d LoRA-Paar(e) als lora{n}_high/low uebertragen",
                        len(slots))

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

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        src = self._first_frame_path(params)
        image_val = ""
        if src.startswith(("http://", "https://")):
            image_val = src
        elif src:
            p = Path(src)
            if not p.exists():
                logger.error("%s: Quellbild fehlt: %s", self.name, src)
                return []
            image_val = base64.b64encode(p.read_bytes()).decode("utf-8")
        if not image_val:
            # Without a reference image the gateway animates an 8x8 placeholder
            # — the result is garbage. Fail loudly instead.
            logger.error("%s: kein Quellbild fuer die Animation", self.name)
            return []

        seconds = int(params.get("seconds") or self.seconds or 5)
        frames = max(1, seconds * _WAN_FPS + 1)  # 5 s → 81 (gateway default)
        payload: Dict[str, Any] = {
            "model": params.get("model") or self.model,
            "prompt": prompt,
            "images": {"image": image_val},
            "params": {"frames": frames},
            "mode": "async",
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        self._apply_lora_params(payload, params)

        url = f"{self.api_url}{self.video_endpoint}"
        logger.info("%s: starte Video-Job (Alias=%s, %d Frames ≈ %ds)",
                    self.name, payload["model"], frames, seconds)
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
                    logger.error("%s: Video-Job failed: %s", self.name,
                                 str(sd.get("error") or sd)[:300])
                    return []
                if status in ("done", "completed"):
                    dl = requests.get(f"{self.api_url}/v1/jobs/{job_id}/result/0",
                                      headers=self._headers(), timeout=180)
                    if dl.status_code == 200 and len(dl.content) > 1000:
                        logger.info("%s: Video fertig (%.1fs, %d bytes)", self.name,
                                    time.time() - start, len(dl.content))
                        return [dl.content]
                    logger.error("%s: Result-Download HTTP %d (%d bytes)",
                                 self.name, dl.status_code, len(dl.content))
                    return []
                # queued / running → weiter warten
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
