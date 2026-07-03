"""CivitAI Cloud API image backend (async with polling)."""
import base64
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")


class CivitAIBackend(ImageBackend):
    """
    Backend for the CivitAI Cloud API (asynchronous with polling).
    API: POST /v1/consumer/jobs → polling → download blobUrl
    Models in the AIR URN format: urn:air:{ecosystem}:checkpoint:civitai:{modelId}@{versionId}
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="civitai", env_prefix=env_prefix)

        self.api_key = api_key or os.environ.get(f"{env_prefix}API_KEY", "")
        self.model = model or os.environ.get(f"{env_prefix}MODEL", "")
        self.scheduler = os.environ.get(f"{env_prefix}SCHEDULER", "DPM2MKarras").strip()
        self.guidance_scale = float(os.environ.get(f"{env_prefix}GUIDANCE_SCALE", "7.0"))
        self.num_inference_steps = int(os.environ.get(f"{env_prefix}NUM_INFERENCE_STEPS", "40"))
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "1024"))
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "1024"))
        self.clip_skip = int(os.environ.get(f"{env_prefix}CLIP_SKIP", "2"))
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0"))
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "300"))

    def _headers(self) -> Dict[str, str]:
        """Creates auth headers for the CivitAI API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def check_availability(self) -> bool:
        """Checks whether the API key is valid and the API reachable."""
        if not self.api_key:
            logger.warning(f"{self.name}: Kein API_KEY konfiguriert")
            self.available = False
            return False
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert (AIR URN erforderlich)")
            self.available = False
            return False

        try:
            # Clean authenticated GET (NO bogus ?token=… — CivitAI interpreted
            # that as an invalid job token and wrongly returned 401 even though
            # the Bearer key was valid).
            resp = requests.get(
                f"{self.api_url}/v1/consumer/jobs",
                headers=self._headers(),
                timeout=10)
            if resp.status_code in (401, 403):
                logger.warning(f"{self.name}: API-Key abgelehnt (Status {resp.status_code})")
                self.available = False
                return False

            # Any other status (even 400/404) means: API reachable, key accepted
            logger.info(f"{self.name} erreichbar (CivitAI, Modell: {self.model})")
            self.available = True
            return True
        except requests.ConnectionError:
            logger.warning(f"{self.name} nicht erreichbar")
            self.available = False
            return False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
            return False

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generates an image via the CivitAI API (async with polling)."""
        # CivitAI requires the AIR URN format - ignore local filenames from params
        param_model = params.get("model", "")
        if param_model and param_model.startswith("urn:air:"):
            model = param_model
        else:
            model = self.model
            if param_model:
                logger.debug(f"{self.name}: Ignoriere nicht-AIR Modell aus params: {param_model}, nutze Backend-Modell: {model}")
        if not model:
            logger.error(f"{self.name}: Kein Modell konfiguriert")
            return []

        width = params.get("width") or self.width
        height = params.get("height") or self.height
        # CivitAI requires dimensions as multiples of 64
        width = round(width / 64) * 64 or 1024
        height = round(height / 64) * 64 or 1024

        # Derive baseModel from the AIR URN: urn:air:{ecosystem}:checkpoint:...
        # Extract the ecosystem segment directly instead of a heuristic — CivitAI
        # uses exactly this token as the baseModel tag.
        model_lower = model.lower()
        ecosystem = ""
        try:
            _parts = model_lower.split(":")
            # urn:air:{ecosystem}:... -> index 2 is ecosystem
            if len(_parts) >= 3 and _parts[0] == "urn" and _parts[1] == "air":
                ecosystem = _parts[2]
        except Exception:
            pass

        is_flux = ecosystem.startswith("flux") or ":flux" in model_lower
        is_turbo = "turbo" in ecosystem
        if ecosystem.startswith("zimage") or ecosystem.startswith("z_image"):
            base_model = "Z_Image_Turbo" if is_turbo else "Z_Image"
        elif ecosystem.startswith("flux2"):
            base_model = "Flux2"
        elif ecosystem.startswith("flux"):
            base_model = "Flux1"
        elif ecosystem == "sdxl":
            base_model = "SDXL"
        elif ecosystem.startswith("sd3"):
            base_model = "SD3"
        elif ecosystem == "pony":
            base_model = "Pony"
        elif ecosystem == "illustrious":
            base_model = "Illustrious"
        elif ecosystem == "noobai":
            base_model = "NoobAI"
        elif ecosystem == "hidream":
            base_model = "HiDream"
        else:
            base_model = "SD_1_5"

        # Flux models only support "Euler" as scheduler on CivitAI
        scheduler = "Euler" if is_flux else self.scheduler

        gen_params = {
            "prompt": prompt,
            "scheduler": scheduler,
            "steps": params.get("num_inference_steps") or self.num_inference_steps,
            "width": width,
            "height": height,
            "seed": -1,
        }
        if is_flux:
            # FLUX: no cfgScale, no clipSkip, no negativePrompt
            pass
        else:
            gen_params["negativePrompt"] = negative_prompt or ""
            gen_params["cfgScale"] = params.get("guidance_scale") or self.guidance_scale
            gen_params["clipSkip"] = self.clip_skip

        payload = {
            "$type": "textToImage",
            "baseModel": base_model,
            "model": model,
            "params": gen_params,
            "quantity": 1,
        }

        logger.info(f"{self.name}: Starte Generierung...")
        logger.info(f"Modell: {model} (baseModel={base_model}), Groesse: {width}x{height}, Steps: {gen_params['steps']}")
        logger.info(f"Prompt: {prompt[:120]}...")

        # 1. Create the job
        try:
            resp = requests.post(
                f"{self.api_url}/v1/consumer/jobs",
                json=payload,
                headers=self._headers(),
                timeout=30)
            if resp.status_code not in (200, 202):
                import json as _json
                error_msg = resp.text[:500] or '(leer)'
                logger.error(f"{self.name}: Job-Erstellung fehlgeschlagen (Status {resp.status_code})")
                logger.error(f"CivitAI Response: {error_msg}")
                logger.error(f"Gesendeter Payload: {_json.dumps(payload, indent=2)[:800]}")
                raise RuntimeError(f"{self.name}: Job fehlgeschlagen (HTTP {resp.status_code}): {error_msg[:200]}")

            data = resp.json()
            token = data.get("token", "")
            jobs = data.get("jobs", [])
            if not token or not jobs:
                logger.error(f"{self.name}: Unerwartete Response: {resp.text[:300]}")
                return []

            job_id = jobs[0].get("jobId", "unknown")
            logger.info(f"Job erstellt: {job_id}")
        except Exception as e:
            logger.error(f"{self.name}: Fehler beim Erstellen des Jobs: {e}")
            return []

        # 2. Polling — result can be dict or list
        #    Format: result=[{blobKey, available, seed, blobUrl?}] or result={blobUrl, ...}
        #    available=true + blobUrl present = done
        start_time = time.time()
        blob_url = None
        _logged_shape = False  # one-time raw logging of the job structure
        _last_raw = ""

        while time.time() - start_time < self.max_wait:
            time.sleep(self.poll_interval)
            elapsed = int(time.time() - start_time)

            try:
                status_resp = requests.get(
                    f"{self.api_url}/v1/consumer/jobs",
                    params={"token": token},
                    headers=self._headers(),
                    timeout=15)
                if status_resp.status_code not in (200, 202):
                    logger.warning(f"{self.name}: Polling HTTP {status_resp.status_code} ({elapsed}s) — Body: {status_resp.text[:200]}")
                    continue

                status_data = status_resp.json()
                _last_raw = json.dumps(status_data)[:600]
                status_jobs = status_data.get("jobs", [])
                if not status_jobs:
                    continue

                job0 = status_jobs[0]
                # Log the real structure once (diagnostics: blobUrl field name etc.)
                if not _logged_shape:
                    _logged_shape = True
                    logger.info("%s: Job-Struktur (Diagnose) job-keys=%s result=%s",
                                self.name, list(job0.keys()), json.dumps(job0.get("result"))[:300])

                # Detect explicit error/terminal states (instead of blindly waiting until timeout).
                _status = str(job0.get("status") or job0.get("$type") or "").lower()
                if any(s in _status for s in ("failed", "error", "canceled", "rejected", "deleted")):
                    logger.error("%s: Job-Status '%s' — Abbruch. Raw: %s",
                                 self.name, _status, _last_raw)
                    return []

                job_result = job0.get("result")
                if job_result is None:
                    continue

                # Result can be list or dict
                result_item = job_result[0] if isinstance(job_result, list) and job_result else job_result
                if isinstance(result_item, dict):
                    available = result_item.get("available", False)
                    # Read field-name variants tolerantly.
                    url = (result_item.get("blobUrl") or result_item.get("blobUrlExpirationDate") and result_item.get("blobUrl")
                           or result_item.get("url") or "")
                    # Explicitly failed result item.
                    if str(result_item.get("blobKey") or "").lower() in ("failed", "error"):
                        logger.error("%s: Result-Item fehlgeschlagen. Raw: %s", self.name, _last_raw)
                        return []
                    if available and url:
                        blob_url = url
                        logger.info(f"Generierung abgeschlossen ({elapsed}s)")
                        break
                    elif url:
                        blob_url = url
                        logger.info(f"Generierung abgeschlossen ({elapsed}s)")
                        break
                    # otherwise still processing -> keep polling

            except Exception as e:
                logger.warning(f"{self.name}: Polling-Fehler: {e} ({elapsed}s)")

        if not blob_url:
            logger.error(f"{self.name}: Timeout nach {self.max_wait}s (kein blobUrl). Letzte Response: {_last_raw}")
            return []

        # 3. Download the image
        try:
            img_resp = requests.get(blob_url, timeout=60)
            if img_resp.status_code != 200:
                logger.error(f"{self.name}: Bild-Download fehlgeschlagen (Status {img_resp.status_code})")
                return []

            image_bytes = img_resp.content
            logger.info(f"Bild heruntergeladen: {len(image_bytes)} bytes")
            return [image_bytes]
        except Exception as e:
            logger.error(f"{self.name}: Fehler beim Herunterladen: {e}")
            return []
