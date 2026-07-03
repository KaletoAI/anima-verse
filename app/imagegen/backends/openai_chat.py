"""OpenAI-chat-compatible image-output backend."""
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


class OpenAIChatImageBackend(ImageBackend):
    """
    Generic image backend for OpenAI-chat-compatible image-output models
    (e.g. Mammouth AI, Gemini-Image, GPT-Image-via-Chat). The image comes from
    the chat response, not from a diffusion endpoint — for diffusion models
    (SD/Flux/Z-Image) use LocalAIBackend (api_type "localai") or the strictly
    OpenAI-conformant OpenAIDiffusionBackend (api_type "openai_diffusion").
    API: POST {url}/chat/completions
    Response: choices[0].message.images[].image_url.url (data:image/png;base64,...)
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = "gemini-2.5-flash-image"):
        super().__init__(name, api_url, cost, api_type="openai_chat", env_prefix=env_prefix)

        self.api_key = api_key or os.environ.get(f"{env_prefix}API_KEY", "")
        self.model = model or os.environ.get(f"{env_prefix}MODEL", "gemini-2.5-flash-image")
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120"))

    def _headers(self) -> Dict[str, str]:
        """Creates auth headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_availability(self) -> bool:
        """Tests the connection via GET /models and checks whether the model exists."""
        try:
            resp = requests.get(
                f"{self.api_url}/models",
                headers=self._headers(),
                timeout=10
            )
            if resp.status_code != 200:
                logger.warning(f"{self.name} antwortet mit Status {resp.status_code}")
                self.available = False
                return False

            # Check whether the configured model is available
            try:
                models_data = resp.json()
                model_ids = [m.get("id", "") for m in models_data.get("data", [])]
                if self.model in model_ids:
                    logger.info(f"{self.name} erreichbar, Modell '{self.model}' verfuegbar")
                    self.available = True
                else:
                    # Look for similar model names
                    image_models = [m for m in model_ids if "image" in m.lower()]
                    logger.warning(f"{self.name}: Modell '{self.model}' nicht gefunden!")
                    if image_models:
                        logger.info(f"Verfuegbare Image-Modelle: {', '.join(image_models)}")
                    self.available = False
            except Exception:
                # JSON parsing failed, API reachable but model unknown
                logger.info(f"{self.name} erreichbar: {self.api_url}")
                self.available = True

        except requests.exceptions.ConnectionError:
            logger.warning(f"{self.name} nicht erreichbar: {self.api_url}")
            self.available = False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
        return self.available

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generates images via the Mammouth chat/completions API."""
        # Build the prompt for the image model
        full_prompt = f"Generate an image: {prompt}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": full_prompt}
            ]
        }

        logger.info(f"{self.name} API-Request: {self.api_url}/chat/completions")
        logger.info(f"Model: {self.model}, Prompt ({len(full_prompt)} chars): {full_prompt}")
        logger.debug(f"Bearer Token {'gesetzt' if self.api_key else 'FEHLT'}, Timeout: 120s")

        try:
            resp = requests.post(
                f"{self.api_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout
            )
        except requests.exceptions.Timeout as e:
            logger.error(f"{self.name} Timeout nach 120s")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"{self.name} Verbindungsfehler: {self.api_url}: {str(e)[:200]}")
            raise
        except Exception as e:
            logger.error(f"{self.name} Unerwarteter Fehler: {type(e).__name__}: {str(e)[:200]}")
            raise

        # Check the response status
        logger.info(f"{self.name} Response: HTTP {resp.status_code}, {len(resp.content)} bytes")
        logger.debug(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")

        # On error: log the response body for debugging
        if resp.status_code != 200:
            error_body = ""
            try:
                error_body = resp.text[:500]
            except Exception:
                pass
            logger.error(f"{self.name} HTTP {resp.status_code}: {error_body}")
            resp.raise_for_status()

        # Parse the JSON response
        try:
            result = resp.json()
            logger.debug("JSON erfolgreich geparsed")
        except Exception as e:
            logger.error(f"JSON-Parsing fehlgeschlagen: {str(e)}")
            logger.debug(f"Response (500 chars): {resp.text[:500]}")
            raise

        images = []

        # Parse response: choices[0].message.images[].image_url.url
        logger.debug("Analysiere Response-Struktur...")
        choices = result.get("choices", [])
        if not choices:
            logger.warning(f"{self.name}: Keine choices in Response, Keys: {list(result.keys())}")
            return images

        message = choices[0].get("message", {})
        image_list = message.get("images", [])

        # If no images list: check content for embedded base64 images
        if not image_list:
            content = message.get("content", "")
            if content:
                logger.info(f"{self.name}: Keine 'images' in message, pruefe Content ({len(content)} chars)")
                b64_matches = re.findall(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
                for b64_data in b64_matches:
                    try:
                        images.append(base64.b64decode(b64_data))
                    except Exception:
                        continue
                if images:
                    logger.info(f"{self.name}: {len(images)} Bild(er) aus Content extrahiert")
                    return images

        for img_entry in image_list:
            image_url = img_entry.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)

            if not url:
                continue

            # Extract base64 from data:image/png;base64,...
            b64_match = re.match(r"data:image/[^;]+;base64,(.+)", url)
            if b64_match:
                try:
                    img_bytes = base64.b64decode(b64_match.group(1))
                    images.append(img_bytes)
                    logger.debug(f"Bild {len(images)} dekodiert: {len(img_bytes)} bytes")
                except Exception as e:
                    logger.error(f"Base64-Dekodierung fehlgeschlagen: {str(e)[:100]}")
                    continue

        if images:
            logger.info(f"{self.name}: {len(images)} Bild(er) erfolgreich generiert")
            for idx, img in enumerate(images, 1):
                logger.debug(f"Bild {idx}: {len(img)} bytes")

        if not images:
            logger.warning(f"{self.name}: Keine Bilder in Response gefunden")
            logger.debug(f"Response-Struktur: Top-Level Keys: {list(result.keys())}, Choices: {bool(choices)}")
            if choices:
                logger.debug(f"Choices[0] Keys: {list(choices[0].keys())}, Message Keys: {list(message.keys())}")
                logger.debug(f"Images-Liste: vorhanden={bool(image_list)}, Laenge={len(image_list)}")
                if message.get("content"):
                    content_preview = str(message['content'])[:300]
                    logger.debug(f"Content-Preview (300 chars): {content_preview}")
                    if any(err in content_preview.lower() for err in ['error', 'fail', 'exception', 'invalid']):
                        logger.warning("Content enthaelt moeglicherweise Fehlermeldung!")
            logger.debug(f"Komplette Response (erste 500 chars): {str(result)[:500]}")

        return images
