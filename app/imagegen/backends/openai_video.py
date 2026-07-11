"""LLM-gateway image-to-video backend (gateway generations/jobs API).

Video counterpart of ``OpenAIDiffusionBackend`` for the LLM gateway: the
gateway hosts a video workflow (e.g. a ComfyUI Wan img2video graph) under a
generation alias. API (gateway spec v2, e.g. alias ``Wan-LowRAM``):

    POST {api_url}/v1/generations            JSON:
        {"model": alias, "prompt": …, "images": {"image": <base64|http-URL>},
         "params": {"seconds": N}, "loras": [{"name": …, "strength": …}],
         "mode": "async", "negative_prompt"?: …}
        → 202 {"job_id": …}   (429/503 carry Retry-After)
    GET  {api_url}/v1/jobs/{job_id}           status queued|running|done|failed;
                                              running adds elapsed_s/progress/eta_s;
                                              done adds results[].url
    POST {api_url}/v1/jobs/{job_id}/cancel

Generation takes MINUTES → always ``mode:"async"`` + polling. The gateway owns
backend choice/queueing/failover (never send a backend field), converts
``seconds`` to the frame raster itself, and resolves Wan HIGH/LOW LoRA pairs
from ONE half — the flat {name, strength} list from the dialog goes through
verbatim. ``MEDIA_TYPE == "video"`` keeps it out of image matching; results
are owner-gated (downloaded with the creating key). Valid LoRA names: the
alias' LoRA endpoint (``fetch_loras``).
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
        # Alias self-discovery (GET /v1/generations/{alias}/schema): image
        # slot name, fps, seconds support. Filled on availability; every
        # value has a safe fallback so a gateway without the endpoint works.
        self._image_slot: str = ""
        self._fps: float = 0.0
        self._seconds_supported: bool = True

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
                self._fetch_alias_schema()
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

    def _fetch_alias_schema(self) -> None:
        """Self-discovery via GET /v1/generations/{alias}/schema (gateway spec
        v2): required image slot, fps, seconds support. Tolerant parsing —
        unknown shapes fall back to the defaults (slot "image", seconds
        passthrough)."""
        try:
            resp = requests.get(
                f"{self.api_url}/v1/generations/{self.model}/schema",
                headers=self._headers(), timeout=10)
            if resp.status_code != 200:
                logger.debug("%s: kein Alias-Schema (HTTP %d)", self.name,
                             resp.status_code)
                return
            sc = resp.json() if resp.content else {}
            if not isinstance(sc, dict):
                return
            # Image slots: dict {slot: {required: bool, ...}} under one of the
            # known keys; pick the first REQUIRED slot, else the first slot.
            slots = None
            for key in ("images", "image_slots", "slots"):
                if isinstance(sc.get(key), dict):
                    slots = sc[key]
                    break
            if slots:
                required = [k for k, v in slots.items()
                            if isinstance(v, dict) and v.get("required")]
                self._image_slot = (required[0] if required
                                    else next(iter(slots.keys()), ""))
            try:
                self._fps = float(sc.get("fps") or 0)
            except (TypeError, ValueError):
                self._fps = 0.0
            if sc.get("seconds_supported") is not None:
                self._seconds_supported = bool(sc.get("seconds_supported"))
            logger.info("%s: Alias-Schema geladen (slot=%s, fps=%s, seconds=%s)",
                        self.name, self._image_slot or "image",
                        self._fps or "?", self._seconds_supported)
        except Exception as e:
            logger.debug("%s: Alias-Schema-Abfrage fehlgeschlagen: %s", self.name, e)

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
    def _lora_list(params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flat ``loras`` list for the gateway (spec v2): the gateway resolves
        Wan HIGH/LOW pairs from ONE half itself — selections go through
        verbatim; a missing file fails the job immediately with the exact
        filename in the error text."""
        out: List[Dict[str, Any]] = []
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
            out.append({"name": name, "strength": strength})
        return out

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
        # Discovered per-alias values (safe fallbacks without the schema
        # endpoint): image slot name and seconds-vs-frames support.
        _slot = self._image_slot or "image"
        if self._seconds_supported:
            _p: Dict[str, Any] = {"seconds": seconds}
        else:
            _fps = self._fps or 16.0
            _p = {"frames": max(1, int(seconds * _fps) + 1)}
        payload: Dict[str, Any] = {
            "model": params.get("model") or self.model,
            "prompt": prompt,
            "images": {_slot: image_val},
            # The gateway converts seconds to the frame raster itself.
            "params": _p,
            "mode": "async",
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        loras = self._lora_list(params)
        if loras:
            payload["loras"] = loras
            logger.info("%s: %d LoRA(s) (Gateway ergaenzt High/Low-Paare)",
                        self.name, len(loras))

        url = f"{self.api_url}{self.video_endpoint}"
        logger.info("%s: starte Video-Job (Alias=%s, %ds)",
                    self.name, payload["model"], seconds)
        resp = None
        for _attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=self._headers(),
                                     timeout=self.timeout)
            except Exception as e:
                logger.error("%s: Verbindungsfehler: %s", self.name, e)
                return []
            # 429/503 carry Retry-After (gateway busy) — wait and retry.
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
            logger.error("%s: Video-Request HTTP %s - %s", self.name,
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
                    logger.error("%s: Video-Job failed: %s", self.name,
                                 str(sd.get("error") or sd)[:300])
                    return []
                if status == "running" and sd.get("progress") is not None:
                    logger.info("%s: Job %s laeuft — %.0f%% (ETA %ss)", self.name,
                                job_id, float(sd.get("progress") or 0) * 100,
                                sd.get("eta_s", "?"))
                if status in ("done", "completed"):
                    # Spec v2: results[].url (owner-gated, same key);
                    # fallback: the older /result/0 path.
                    _results = sd.get("results") or []
                    _r_url = (_results[0].get("url") if _results
                              and isinstance(_results[0], dict) else "") or ""
                    if _r_url and not _r_url.startswith(("http://", "https://")):
                        _r_url = f"{self.api_url}{_r_url}"
                    if not _r_url:
                        _r_url = f"{self.api_url}/v1/jobs/{job_id}/result/0"
                    dl = requests.get(_r_url, headers=self._headers(), timeout=180)
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
