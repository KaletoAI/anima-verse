"""A1111/Forge (Stable Diffusion WebUI) image backend."""
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


class A1111Backend(ImageBackend):
    """
    Backend for Stable Diffusion WebUI (A1111/Forge).
    API: POST {url}/sdapi/v1/txt2img
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str):
        super().__init__(name, api_url, cost, api_type="a1111", env_prefix=env_prefix)

        self.guidance_scale = float(os.environ.get(f"{env_prefix}GUIDANCE_SCALE", "7.5"))
        self.num_inference_steps = int(os.environ.get(f"{env_prefix}NUM_INFERENCE_STEPS", "50"))
        self.checkpoint = os.environ.get(f"{env_prefix}CHECKPOINT", "").strip()
        self.sampling_method = os.environ.get(f"{env_prefix}SAMPLING_METHOD", "").strip()
        self.schedule_type = os.environ.get(f"{env_prefix}SCHEDULE_TYPE", "").strip()
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "1024"))
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "1024"))

    def check_availability(self) -> bool:
        """Tests the connection via GET /info."""
        try:
            resp = requests.get(f"{self.api_url}/info", timeout=5)
            self.available = resp.status_code == 200
            if self.available:
                logger.info(f"{self.name} erreichbar: {self.api_url}")
            else:
                logger.warning(f"{self.name} antwortet mit Status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"{self.name} nicht erreichbar: {self.api_url}")
            self.available = False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
        return self.available

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generates images via the A1111 txt2img API."""
        guidance = params.get("guidance_scale", self.guidance_scale)
        steps = params.get("num_inference_steps", self.num_inference_steps)
        checkpoint = params.get("checkpoint", self.checkpoint)
        sampler = params.get("sampling_method", self.sampling_method)
        scheduler = params.get("schedule_type", self.schedule_type)
        width = int(params.get("width", self.width))
        height = int(params.get("height", self.height))

        payload = {
            "prompt": prompt,
            "guidance_scale": guidance,
            "steps": steps,
            "width": width,
            "height": height,
        }

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if checkpoint:
            payload["sd_model_checkpoint"] = checkpoint
        if sampler:
            payload["sampler_name"] = sampler
        if scheduler:
            payload["scheduler"] = scheduler

        logger.info(f"{self.name} API-Request: {self.api_url}/sdapi/v1/txt2img")
        logger.info(f"Prompt ({len(prompt)} chars): {prompt}")
        if negative_prompt:
            logger.info(f"Negative-Prompt: {negative_prompt}")
        logger.info(f"Params: guidance={guidance}, steps={steps}, size={width}x{height}")
        if checkpoint:
            logger.info(f"Checkpoint: {checkpoint}")
        if sampler:
            logger.info(f"Sampler: {sampler}")
        if scheduler:
            logger.info(f"Scheduler: {scheduler}")
        logger.debug("Timeout: 600s")

        try:
            resp = requests.post(
                f"{self.api_url}/sdapi/v1/txt2img",
                json=payload,
                timeout=600
            )
        except requests.exceptions.Timeout:
            logger.error(f"{self.name} Timeout nach 600s")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"{self.name} Verbindungsfehler: Kann API nicht erreichen ({self.api_url}): {str(e)[:200]}")
            raise
        except Exception as e:
            logger.error(f"{self.name} Request-Fehler: {str(e)[:200]}")
            raise

        logger.info(f"{self.name} Response: HTTP {resp.status_code}, {len(resp.content)} bytes")
        logger.debug(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")

        if resp.status_code != 200:
            error_body = resp.text[:500] if hasattr(resp, 'text') else 'N/A'
            logger.error(f"HTTP {resp.status_code}: {error_body}")
            resp.raise_for_status()

        try:
            result = resp.json()
            logger.debug("JSON geparsed")
        except Exception as e:
            logger.error(f"JSON-Parsing fehlgeschlagen: {str(e)}")
            logger.debug(f"Response: {resp.text[:500]}")
            raise

        images_b64 = result.get("images", [])
        logger.info(f"Gefunden: {len(images_b64)} base64-Bild(er) in Response")

        images = []
        for idx, img_b64 in enumerate(images_b64, 1):
            try:
                img_bytes = base64.b64decode(img_b64)
                images.append(img_bytes)
                logger.debug(f"Bild {idx} dekodiert: {len(img_bytes)} bytes")
            except Exception as e:
                logger.error(f"Bild {idx} Dekodierung fehlgeschlagen: {str(e)[:100]}")
                continue

        if images:
            logger.info(f"{self.name}: {len(images)} Bild(er) erfolgreich generiert")
        else:
            logger.warning(f"{self.name}: Keine Bilder dekodiert")
            logger.debug(f"Response-Struktur: Top-Level Keys: {list(result.keys())}")
            logger.debug(f"'images' Key vorhanden: {'images' in result}, Laenge: {len(images_b64)}")
            if result.get("info"):
                logger.debug(f"Info: {str(result['info'])[:200]}")
            logger.debug(f"Tipp: Prüfe ob Stable Diffusion Model geladen ist")
            logger.debug(f"Komplette Response (erste 500 chars): {str(result)[:500]}")

        return images
