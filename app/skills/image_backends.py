"""Image Generation Backends - Verschiedene API-Typen fuer Bildgenerierung"""
import base64
import json
import os
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
logger = get_logger("image_backends")


_comfyui_url_cache: dict = {"url": None, "expires": 0.0}
_COMFYUI_CACHE_TTL = 60.0


def get_active_comfyui_url() -> str:
    """Gibt die URL des ersten erreichbaren ComfyUI Image-Gen-Dienstes zurueck.

    Durchsucht SKILL_IMAGEGEN_1_*, SKILL_IMAGEGEN_2_*, ... und testet jeden
    aktivierten ComfyUI-Dienst auf Erreichbarkeit. Gibt die URL des ersten
    antwortenden Dienstes zurueck. Ergebnis wird 60s gecacht.

    Returns:
        API-URL ohne trailing slash, oder "" wenn kein ComfyUI-Dienst erreichbar.
    """
    global _comfyui_url_cache
    import time as _t
    now = _t.time()
    if _comfyui_url_cache["url"] is not None and now < _comfyui_url_cache["expires"]:
        return _comfyui_url_cache["url"]

    i = 1
    while True:
        name = os.environ.get(f"SKILL_IMAGEGEN_{i}_NAME")
        if name is None:
            break
        enabled = os.environ.get(f"SKILL_IMAGEGEN_{i}_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        api_type = os.environ.get(f"SKILL_IMAGEGEN_{i}_API_TYPE", "").strip().lower()
        if enabled and api_type == "comfyui":
            url = os.environ.get(f"SKILL_IMAGEGEN_{i}_API_URL", "").strip().rstrip("/")
            if url:
                try:
                    resp = requests.get(f"{url}/system_stats", timeout=3)
                    if resp.status_code == 200:
                        logger.info(f"Aktiver Dienst: {name} ({url})")
                        _comfyui_url_cache["url"] = url
                        _comfyui_url_cache["expires"] = now + _COMFYUI_CACHE_TTL
                        return url
                    # /system_stats kann 500 werfen (kaputter Custom-Node);
                    # Fallback /queue probieren bevor wir den Dienst aufgeben.
                    q_resp = requests.get(f"{url}/queue", timeout=3)
                    if q_resp.status_code == 200:
                        logger.info(f"Aktiver Dienst: {name} ({url}) — via /queue, /system_stats wirft {resp.status_code}")
                        _comfyui_url_cache["url"] = url
                        _comfyui_url_cache["expires"] = now + _COMFYUI_CACHE_TTL
                        return url
                    logger.warning(f"{name} ({url}): HTTP {resp.status_code}, uebersprungen")
                except Exception:
                    logger.warning(f"{name} ({url}): nicht erreichbar, uebersprungen")
        i += 1

    logger.warning("Kein erreichbarer ComfyUI-Dienst gefunden")
    _comfyui_url_cache["url"] = ""
    _comfyui_url_cache["expires"] = now + _COMFYUI_CACHE_TTL
    return ""


class ImageBackend(ABC):
    """
    Basisklasse fuer Image Generation Backends.

    Jedes Backend implementiert ein spezifisches API-Protokoll
    (z.B. A1111/Forge, Mammouth/OpenAI-kompatibel).
    """

    # Throttle fuer "nicht erreichbar"-Warnungen — log spam vermeiden bei
    # dauerhaft offline Backends. Erstes Mal WARNING, dann fuer
    # _UNREACHABLE_THROTTLE_SEC Sekunden auf DEBUG reduziert. Wiederkehr
    # (avail True nach False) wird als INFO geloggt.
    _UNREACHABLE_THROTTLE_SEC = 300

    def __init__(self, name: str, api_url: str, cost: float, api_type: str, env_prefix: str):
        self.name = name
        self.api_url = api_url.rstrip("/")
        self.cost = cost
        self.api_type = api_type
        self.env_prefix = env_prefix
        self.available = False
        self._active_jobs = 0
        self._jobs_lock = __import__("threading").Lock()
        # Letzter Zeitpunkt an dem wir "nicht erreichbar" als WARNING geloggt haben
        self._last_unreachable_warn_ts: float = 0.0
        # Vorheriger Verfuegbarkeitsstatus — Uebergang False->True triggert "wieder da"
        self._was_available: Optional[bool] = None

        # Instanz-Enabled aus .env (globaler Default)
        self.instance_enabled = os.environ.get(f"{env_prefix}ENABLED", "true").strip().lower() in ("true", "1", "yes")

        # Image Family (natural/keywords) — fuer Cloud-Backends ohne Workflow.
        # Style/Negative gehoeren in die Use-Cases, nicht ans Backend.
        self.image_family = os.environ.get(f"{env_prefix}IMAGE_FAMILY", "").strip()

        # Statische Fallback-Konfiguration (fallback_mode/fallback_specific)
        # entfernt: bei Ausfall waehlt run_with_fallback dynamisch das naechste
        # verfuegbare kompatible Backend — die Verfuegbarkeits-Logik IST der
        # Fallback (Match-Konzept).

        # NVFP4-Architektur: Backend benoetigt NVFP4-quantisierte Modelle (legacy)
        self.nvfp4 = os.environ.get(
            f"{env_prefix}NVFP4", "false"
        ).strip().lower() in ("true", "1", "yes")

        # Per-Backend Queue/Channel Settings (verdraengt den alten
        # gpu_provider-Mechanismus: jedes Backend bekommt seinen eigenen
        # Channel ueber den ProviderManager).
        mc_str = os.environ.get(f"{env_prefix}MAX_CONCURRENT", "1").strip()
        try:
            self.max_concurrent = max(1, int(mc_str))
        except ValueError:
            self.max_concurrent = 1
        self.beszel_system_id = os.environ.get(f"{env_prefix}BESZEL_SYSTEM_ID", "").strip()

        # Optionale GPU-Metadaten (VRAM/Label/Beszel-Mapping).
        # Diese sind reine Anzeige/Monitoring-Daten — die Channel-Zahl bleibt
        # immer 1 pro Backend (Queue-Serialisierung). Pflicht ist nichts.
        self.gpu_configs: List[dict] = []
        gi = 0
        while True:
            gvram = os.environ.get(f"{env_prefix}GPU{gi}_VRAM", "").strip()
            if not gvram:
                break
            try:
                vram_mb = int(float(gvram) * 1024)
            except ValueError:
                break
            self.gpu_configs.append({
                "index": gi,
                "vram_mb": vram_mb,
                "device": os.environ.get(f"{env_prefix}GPU{gi}_DEVICE", "").strip(),
                "label": os.environ.get(f"{env_prefix}GPU{gi}_LABEL", "").strip(),
                "match_name": os.environ.get(f"{env_prefix}GPU{gi}_MATCH_NAME", "").strip(),
            })
            gi += 1

    @property
    def effective_cost(self) -> float:
        """Semantische Kosten des Backends. Wird vom Selektor zur
        Bevorzugung genutzt (lokal=0, Cloud > 0). Keine Last-Penalty mehr —
        Verteilung gleich-cost Backends laeuft ueber Round-Robin im Skill.
        """
        return self.cost

    def _log_unreachable(self, reason: str = "") -> None:
        """Throttled-Logging fuer 'nicht erreichbar'-Zustaende.

        WARNING beim ersten Mal und alle 5 Minuten erneut, dazwischen DEBUG.
        Verhindert Log-Flut wenn Polling/check_availability oft laeuft.
        """
        msg = f"{self.name} nicht erreichbar: {self.api_url}"
        if reason:
            msg += f" ({reason})"
        now = time.time()
        if now - self._last_unreachable_warn_ts >= self._UNREACHABLE_THROTTLE_SEC:
            logger.warning(msg)
            self._last_unreachable_warn_ts = now
        else:
            logger.debug(msg)

    def _mark_available(self, info: str = "") -> None:
        """Markiert Backend als verfuegbar; loggt INFO bei Recovery."""
        _was_recovery = (self._was_available is False)
        if _was_recovery:
            logger.info("%s wieder erreichbar%s", self.name, f": {info}" if info else "")
        elif self._was_available is None:
            # Erster erfolgreicher Check — kurze INFO, kein "wieder"
            logger.info("%s erreichbar%s", self.name, f": {info}" if info else "")
        self._was_available = True
        # Throttle-Counter zuruecksetzen, damit naechstes Down-Event sofort warnt
        self._last_unreachable_warn_ts = 0.0
        self.available = True
        # Recovery: channel_health sofort neu pollen, damit GPU-Task-Routing
        # (find_channel/is_healthy) den frischen Status sieht und nicht erst
        # bis zum naechsten 30s-Poll wartet. Sonst schlagen GPU-Tasks direkt
        # nach Recovery noch fehl, obwohl das Backend wieder online ist.
        if _was_recovery:
            try:
                from app.core.channel_health import get_monitor as _ch_monitor
                _ch_monitor().force_poll()
            except Exception as _ch_err:
                logger.debug("channel_health force_poll fehlgeschlagen: %s", _ch_err)

    def _mark_unavailable(self, reason: str = "") -> None:
        """Markiert Backend als unavailable; throttled-Logging."""
        self._log_unreachable(reason)
        self._was_available = False
        self.available = False

    @abstractmethod
    def check_availability(self) -> bool:
        """Prueft ob die API erreichbar ist. Setzt self.available."""
        pass

    def _inject_lora_triggers(self, prompt: str, params: Dict[str, Any]) -> str:
        """Stellt dem Prompt die Aktivierungs-Woerter der aktiven LoRAs voran
        (aus dem per-Welt-Repository image_generation.lora_triggers). Cloud-
        Backends ohne LoRAs (lora_inputs gepoppt) bekommen nichts."""
        try:
            names = [str(l.get("name")).strip()
                     for l in (params.get("lora_inputs") or params.get("loras") or [])
                     if isinstance(l, dict) and (l.get("name") or "").strip()
                     and l.get("name") != "None"]
            if not names:
                return prompt
            from app.core.config import get_lora_trigger_words
            words = get_lora_trigger_words(names)
            if not words:
                return prompt
            logger.info("%s: LoRA-Trigger-Woerter ergaenzt: %s", self.name, ", ".join(words))
            return ", ".join(words) + ", " + prompt
        except Exception as e:
            logger.debug("LoRA-Trigger-Injektion fehlgeschlagen: %s", e)
            return prompt

    def generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any],
                 log_meta: Optional[Dict[str, Any]] = None) -> List[bytes]:
        """Generiert Bilder mit automatischem Job-Tracking fuer Load-Balancing.

        ZENTRALER letzter Schritt der Bild-Erzeugung: (1) LoRA-Aktivierungswoerter
        in den Prompt aufnehmen -> finaler Prompt, (2) an die Engine uebergeben,
        (3) bei Erfolg das Image-Prompt-Logfile schreiben — mit GENAU dem finalen
        Prompt, der an die Engine ging. So bleibt Log == Generierung, ohne dass
        jeder Aufrufer das nachpflegen muss. ``log_meta`` liefert den Kontext des
        Aufrufers (agent_name, original_prompt, PromptBuilder-Vars …); die
        engine-/prompt-seitigen Felder (final_prompt, Backend, Model, LoRAs,
        Referenzbilder, Dauer, Seed, Negative) setzt diese Funktion selbst.
        ``log_meta=None`` -> kein Logging (z.B. Fehler-Logging macht der Aufrufer).

        Wendet zentrales Downscale-Postprocessing an, wenn ``params`` einen
        ``image_use_case`` enthaelt (item / location). Caller, die volle
        Aufloesung brauchen (Outfit, Avatar), setzen den Key nicht.
        """
        import time as _time
        # LoRA-Aktivierungs-Woerter (per-Welt-Repository) zentral in den Prompt
        # aufnehmen — gilt fuer ALLE Backends/Pfade, sobald ein LoRA aktiv ist.
        final_prompt = self._inject_lora_triggers(prompt, params)

        _t0 = _time.time()
        with self._jobs_lock:
            self._active_jobs += 1
        try:
            result = self._generate(final_prompt, negative_prompt, params)
        finally:
            with self._jobs_lock:
                self._active_jobs = max(0, self._active_jobs - 1)

        # Sentinel-String "NO_NEW_IMAGE" oder Fehler-Listen unveraendert weitergeben.
        use_case = (params or {}).get("image_use_case") or ""
        if use_case and isinstance(result, list) and result:
            try:
                from app.core.image_postprocess import downscale_bytes
                result = [
                    downscale_bytes(img, use_case) if isinstance(img, (bytes, bytearray)) else img
                    for img in result
                ]
            except Exception as _exc:
                logger.warning("Downscale-Postprocess fehlgeschlagen: %s", _exc)

        # Zentrales Logging nur bei echtem Erfolg (Bilder erzeugt, kein Cache-Hit).
        if log_meta is not None and isinstance(result, list) and result:
            self._log_generation(final_prompt, negative_prompt, params,
                                 _time.time() - _t0, log_meta)
        return result

    def _log_generation(self, final_prompt: str, negative_prompt: str,
                        params: Dict[str, Any], duration_s: float,
                        log_meta: Dict[str, Any]) -> None:
        """Schreibt die Image-Prompt-Logzeile mit dem FINALEN Prompt + engine-/
        prompt-seitigen Feldern; ``log_meta`` steuert den Aufrufer-Kontext bei."""
        try:
            from app.utils.image_prompt_logger import log_image_prompt
            _model = (params.get("model") or params.get("unet")
                      or getattr(self, 'last_used_checkpoint', '')
                      or getattr(self, 'model', '') or getattr(self, 'checkpoint', '') or '')
            fields = dict(log_meta or {})
            fields.update(
                final_prompt=final_prompt,
                negative_prompt=negative_prompt,
                backend_name=self.name,
                backend_type=self.api_type,
                model=_model,
                loras=params.get("lora_inputs") or params.get("loras") or [],
                reference_images=params.get("reference_images") or {},
                duration_s=round(float(duration_s), 2),
            )
            if "seed" not in fields and params.get("seed") is not None:
                fields["seed"] = int(params.get("seed") or 0)
            log_image_prompt(**fields)
        except Exception as _le:
            logger.debug("Zentrales Image-Logging fehlgeschlagen: %s", _le)

    @abstractmethod
    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """
        Generiert Bilder und gibt sie als Liste von PNG-Bytes zurueck.

        Args:
            prompt: Der fertige Prompt (inkl. Prefix/Suffix)
            negative_prompt: Negative Prompt
            params: Zusaetzliche Parameter (guidance_scale, steps, etc.)

        Returns:
            Liste von PNG-Bildern als bytes
        """
        pass

    def __repr__(self):
        status = "verfuegbar" if self.available else "nicht verfuegbar"
        return f"{self.name} ({self.api_type}, cost={self.cost}, {status})"


class A1111Backend(ImageBackend):
    """
    Backend fuer Stable Diffusion WebUI (A1111/Forge).
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
        """Testet Verbindung via GET /info."""
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
        """Generiert Bilder ueber A1111 txt2img API."""
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


class OpenAIChatImageBackend(ImageBackend):
    """
    Generisches Bild-Backend fuer OpenAI-Chat-kompatible Bild-Output-Modelle
    (z.B. Mammouth AI, Gemini-Image, GPT-Image-via-Chat). Das Bild kommt aus der
    Chat-Antwort, nicht aus einem Diffusion-Endpoint — fuer Diffusion-Modelle
    (SD/Flux/Z-Image) sind LocalAIBackend (api_type "localai") bzw. das strikt
    OpenAI-konforme OpenAIDiffusionBackend (api_type "openai_diffusion") da.
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
        """Erstellt Auth-Headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_availability(self) -> bool:
        """Testet Verbindung via GET /models und prueft ob das Modell existiert."""
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

            # Pruefe ob das konfigurierte Modell verfuegbar ist
            try:
                models_data = resp.json()
                model_ids = [m.get("id", "") for m in models_data.get("data", [])]
                if self.model in model_ids:
                    logger.info(f"{self.name} erreichbar, Modell '{self.model}' verfuegbar")
                    self.available = True
                else:
                    # Suche nach aehnlichen Modellnamen
                    image_models = [m for m in model_ids if "image" in m.lower()]
                    logger.warning(f"{self.name}: Modell '{self.model}' nicht gefunden!")
                    if image_models:
                        logger.info(f"Verfuegbare Image-Modelle: {', '.join(image_models)}")
                    self.available = False
            except Exception:
                # JSON-Parsing fehlgeschlagen, API erreichbar aber Modell unbekannt
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
        """Generiert Bilder ueber Mammouth chat/completions API."""
        # Prompt fuer Image-Modell aufbauen
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

        # Response-Status pruefen
        logger.info(f"{self.name} Response: HTTP {resp.status_code}, {len(resp.content)} bytes")
        logger.debug(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")

        # Bei Fehler: Response-Body loggen fuer Debugging
        if resp.status_code != 200:
            error_body = ""
            try:
                error_body = resp.text[:500]
            except Exception:
                pass
            logger.error(f"{self.name} HTTP {resp.status_code}: {error_body}")
            resp.raise_for_status()

        # JSON Response parsen
        try:
            result = resp.json()
            logger.debug("JSON erfolgreich geparsed")
        except Exception as e:
            logger.error(f"JSON-Parsing fehlgeschlagen: {str(e)}")
            logger.debug(f"Response (500 chars): {resp.text[:500]}")
            raise

        images = []

        # Parse Response: choices[0].message.images[].image_url.url
        logger.debug("Analysiere Response-Struktur...")
        choices = result.get("choices", [])
        if not choices:
            logger.warning(f"{self.name}: Keine choices in Response, Keys: {list(result.keys())}")
            return images

        message = choices[0].get("message", {})
        image_list = message.get("images", [])

        # Falls keine images-Liste: Content auf eingebettete base64-Bilder pruefen
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

            # Extrahiere base64 aus data:image/png;base64,...
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


class ComfyUIBackend(ImageBackend):
    """
    Backend fuer ComfyUI.
    API: POST /prompt → GET /history/{id} → GET /view?filename=...
    Nutzt einen gespeicherten Workflow (API-Format) der zur Laufzeit parametrisiert wird.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str):
        super().__init__(name, api_url, cost, api_type="comfyui", env_prefix=env_prefix)
        # Lock: schuetzt die Slot-Upload → Queue-Submit Sequenz,
        # damit parallele Generierungen die festen Referenz-Slots nicht ueberschreiben.
        self._slot_lock = __import__("threading").Lock()
        # Letzte (workflow_file, model_name) Kombination, die auf diesem Backend
        # geladen wurde. Wenn der naechste Run dieselbe Kombination nutzt,
        # ueberspringen wir /free — das Modell ist schon im VRAM und kann
        # wiederverwendet werden (spart 1-3s Disk-Load pro identischem Run).
        self._last_loaded_signature: str = ""

        self.checkpoint = os.environ.get(f"{env_prefix}CHECKPOINT", "").strip()
        self.sampler = os.environ.get(f"{env_prefix}SAMPLER", "euler").strip()
        self.scheduler = os.environ.get(f"{env_prefix}SCHEDULER", "normal").strip()
        self.guidance_scale = float(os.environ.get(f"{env_prefix}GUIDANCE_SCALE", "7.0"))
        self.num_inference_steps = int(os.environ.get(f"{env_prefix}NUM_INFERENCE_STEPS", "20"))
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "1024"))
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "1024"))
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "1.0"))
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "600"))

    def _load_workflow(self, workflow_override: str = "") -> Dict:
        """Laedt einen Custom-Workflow aus einer JSON-Datei.

        Returns:
            workflow_dict

        Raises:
            FileNotFoundError: Wenn keine Workflow-Datei angegeben oder gefunden wurde
        """
        wf_path = workflow_override
        if not wf_path:
            raise FileNotFoundError(
                f"{self.name}: Kein Workflow konfiguriert. "
                f"Bitte einen ComfyUI-Workflow (COMFY_IMAGEGEN_*) in der .env definieren."
            )
        if not os.path.exists(wf_path):
            raise FileNotFoundError(
                f"{self.name}: Workflow-Datei nicht gefunden: {wf_path}"
            )
        with open(wf_path) as f:
            wf = json.load(f)
        logger.info(f"{self.name}: Custom-Workflow geladen: {wf_path}")
        return wf

    def _find_node_by_class(self, workflow: Dict, class_type: str) -> Optional[str]:
        """Findet die erste Node-ID mit dem gegebenen class_type."""
        for node_id, node in workflow.items():
            if node.get("class_type") == class_type:
                return node_id
        return None

    def _find_node_by_title(self, workflow: Dict, title: str) -> Optional[str]:
        """Findet eine Node-ID anhand ihres _meta.title (case-insensitive)."""
        title_lower = title.lower()
        for node_id, node in workflow.items():
            node_title = node.get("_meta", {}).get("title", "").lower()
            if node_title == title_lower:
                return node_id
        return None

    def _find_positive_clip(self, workflow: Dict) -> Optional[str]:
        """Findet die Positive-CLIP-Node (anhand _meta.title oder erste CLIPTextEncode)."""
        clip_nodes = []
        for node_id, node in workflow.items():
            if node.get("class_type") == "CLIPTextEncode":
                meta_title = node.get("_meta", {}).get("title", "").lower()
                if "positive" in meta_title or "prompt" in meta_title:
                    return node_id
                clip_nodes.append(node_id)
        return clip_nodes[0] if clip_nodes else None

    def _find_negative_clip(self, workflow: Dict) -> Optional[str]:
        """Findet die Negative-CLIP-Node."""
        clip_nodes = []
        for node_id, node in workflow.items():
            if node.get("class_type") == "CLIPTextEncode":
                meta_title = node.get("_meta", {}).get("title", "").lower()
                if "negative" in meta_title:
                    return node_id
                clip_nodes.append(node_id)
        # Zweite CLIPTextEncode = Negative (wenn mindestens 2 vorhanden)
        return clip_nodes[1] if len(clip_nodes) > 1 else None

    # Feste Dateinamen fuer Referenzbild-Slots auf dem ComfyUI-Server.
    # Da immer nur eine Generierung gleichzeitig laeuft (Queue/GPU-Lock),
    # werden diese Slots vor jedem Run mit Placeholder-Bildern ueberschrieben,
    # damit keine Reste aus vorherigen Generierungen im Workflow landen.
    _REF_SLOT_NAMES = [
        "_slot_ref_1.png",
        "_slot_ref_2.png",
        "_slot_ref_3.png",
        "_slot_ref_4.png",
        "_slot_target.png",
    ]

    # ComfyUI-Standard-Platzhalter, den LoadImage/LoadAndResizeImage-Nodes ohne
    # ausgewaehltes Bild tragen. Existiert auf dem Server nicht -> wie ein leerer
    # Slot behandeln, damit ungefuellte Referenz-Slots entfernt/deaktiviert
    # werden (sonst validiert ComfyUI "example.png" und faellt mit HTTP 400).
    _PLACEHOLDER_IMAGE_NAMES = ("example.png",)

    def _upload_image(self, file_path: str, slot_name: Optional[str] = None) -> Optional[str]:
        """Laedt ein Bild zu ComfyUI hoch (fuer LoadImage-Nodes).

        Args:
            file_path: Lokaler Pfad zur Bilddatei.
            slot_name: Fertiger, DETERMINISTISCHER Zieldateiname auf dem ComfyUI-
                       Server (z.B. ``<workflow>_slot_ref_1.png``). Wird per Run
                       mit ``overwrite=true`` ueberschrieben. KEIN Timestamp:
                       da ComfyUI nur EINE Generierung gleichzeitig macht
                       (GPU-Lock), kann sich nichts in die Quere kommen, der
                       input-Ordner bleibt klein (nur N Dateien pro Workflow),
                       und es kann kein altes/fremdes Bild zufaellig als Referenz
                       durchsickern. Wenn None, wird der Original-Dateiname
                       verwendet (kollisionsfrei, da Source-Filenames eindeutig).

        Returns:
            Dateiname auf dem ComfyUI-Server, oder None bei Fehler.
        """
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            logger.error(f"Upload: Datei nicht gefunden: {file_path}")
            return None
        upload_name = slot_name if slot_name else path.name
        try:
            with open(file_path, "rb") as f:
                files = {"image": (upload_name, f, "image/png")}
                data = {"subfolder": "", "type": "input", "overwrite": "true"}
                resp = requests.post(
                    f"{self.api_url}/upload/image",
                    files=files,
                    data=data,
                    timeout=30)
            if resp.status_code == 200:
                filename = resp.json().get("name", upload_name)
                logger.info(f"Upload OK: {filename}")
                return filename
            else:
                logger.error(f"Upload fehlgeschlagen: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Upload Fehler: {e}")
            return None

    def _upload_bytes(self, data_bytes: bytes, upload_name: str) -> Optional[str]:
        """Laedt rohe Bytes als Bild zu ComfyUI hoch.

        Returns:
            Dateiname auf dem ComfyUI-Server, oder None bei Fehler.
        """
        import io
        try:
            files = {"image": (upload_name, io.BytesIO(data_bytes), "image/png")}
            data = {"subfolder": "", "type": "input", "overwrite": "true"}
            resp = requests.post(
                f"{self.api_url}/upload/image",
                files=files,
                data=data,
                timeout=30)
            if resp.status_code == 200:
                filename = resp.json().get("name", upload_name)
                return filename
            else:
                logger.error(f"Upload-Bytes fehlgeschlagen: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Upload-Bytes Fehler: {e}")
            return None

    def _wf_slot_prefix(self, params: Dict[str, Any]) -> str:
        """Dateinamen-sicherer Praefix pro Workflow fuer die Referenz-Slot-Namen.

        Aus dem Workflow-File-Basename abgeleitet (z.B. ``text2img_workflow_qwen``).
        Deterministisch — zusammen mit dem festen Slot-Suffix ergibt das pro
        (Workflow, Slot) IMMER denselben Dateinamen, der bei jedem Run sauber
        ueberschrieben wird (keine Timestamp-Flut im input-Ordner, kein
        Durchsickern alter Referenzbilder)."""
        import os as _os
        import re as _re
        base = _os.path.splitext(_os.path.basename(params.get("workflow_file", "") or ""))[0]
        token = _re.sub(r'[^A-Za-z0-9_-]', '_', base).strip('_')
        # A/B-Wechsel pro Generierung: zwei aufeinanderfolgende Laeufe nutzen
        # UNTERSCHIEDLICHE Slot-Dateinamen — so ueberschreibt der zweite nicht den
        # Input des ersten, und ComfyUI liefert nicht den gecachten alten
        # Dateinamen. Bleibt bounded (nur Satz A + B, keine Timestamp-Flut).
        # Aufruf erfolgt unter gehaltenem _slot_lock -> kein Race auf den Zaehler.
        self._slot_ab = getattr(self, "_slot_ab", 0) + 1
        ab = "A" if self._slot_ab % 2 else "B"
        token = f"{token}_{ab}" if token else ab
        return f"{token}_"

    def _reset_reference_slots(self, prefix: str = "") -> None:
        """Ueberschreibt alle Referenzbild-Slots auf dem ComfyUI-Server mit
        einem 8x8 schwarzen Placeholder-PNG.

        Muss vor jedem Workflow-Run aufgerufen werden, damit keine Bilder aus
        vorherigen Generierungen in den LoadImage-Nodes landen. ``prefix`` ist
        der Workflow-Praefix (s. :meth:`_wf_slot_prefix`), damit Reset und Upload
        denselben deterministischen Dateinamen treffen.
        """
        placeholder = self._create_placeholder_png(size=8)
        for slot in self._REF_SLOT_NAMES:
            self._upload_bytes(placeholder, f"{prefix}{slot}")
        logger.debug(f"Referenz-Slots zurueckgesetzt ({len(self._REF_SLOT_NAMES)} Slots, prefix='{prefix}')")

    def _free_comfyui_memory(self, signature: str = "") -> None:
        """Triggert ComfyUI's /free Endpoint: VRAM freigeben + Modelle unloaden.

        Wenn `signature` uebergeben wird und identisch zur letzten ist, wird
        /free uebersprungen — das Modell ist schon im VRAM und wird
        wiederverwendet (spart Disk-Load). Bei Wechsel oder ohne Signature
        wird /free ausgefuehrt und die neue Signature gemerkt.

        Damit teilen sich aufeinanderfolgende Generierungen auf demselben
        ComfyUI-Server nicht den VRAM-Cache (mehrere grosse Modell-Stacks
        passen sonst nicht in 24GB).

        Per Env abschaltbar (`COMFY_FREE_MEMORY_BEFORE_RUN=false`), falls
        die wiederholten Modell-Loads zu viel I/O kosten.
        """
        if os.environ.get("COMFY_FREE_MEMORY_BEFORE_RUN", "true").strip().lower() in ("false", "0", "no"):
            logger.info(f"{self.name}: /free uebersprungen (COMFY_FREE_MEMORY_BEFORE_RUN=false)")
            return
        # Wenn wir eine Signature haben und sie matched -> /free skippen
        if signature and signature == self._last_loaded_signature:
            logger.info(f"{self.name}: /free uebersprungen — gleiche Signature: {signature}")
            return
        try:
            resp = requests.post(
                f"{self.api_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=10)
            if resp.status_code == 200:
                logger.info(f"{self.name}: /free OK (alte Signature='{self._last_loaded_signature}', neue='{signature or '(keine)'}')")
                self._last_loaded_signature = signature
            else:
                logger.warning(f"{self.name}: /free HTTP {resp.status_code} — Body: {resp.text[:200]}")
                # Trotz HTTP-Fehler die Signature merken, damit bei demselben
                # naechsten Call nicht erneut versucht wird.
                self._last_loaded_signature = signature
        except Exception as e:
            # /free ist Best-Effort — wenn ComfyUI es nicht unterstuetzt oder
            # nicht erreichbar ist, einfach weitermachen.
            logger.warning(f"{self.name}: /free fehlgeschlagen ({type(e).__name__}: {e})")
            # Hier bewusst keine Signature-Aktualisierung: beim naechsten Call
            # wird's nochmal versucht.

    def _create_placeholder_png(self, size: int = 8) -> bytes:
        """Erzeugt ein minimales transparentes PNG (default 8x8)."""
        import struct
        import zlib

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            raw = chunk_type + data
            return struct.pack(">I", len(data)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)

        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # NxN RGBA
        # Jede Zeile: filter-byte (0) + N * 4 Bytes (RGBA transparent)
        row = b'\x00' + b'\x00\x00\x00\x00' * size
        raw_rows = row * size
        idat = zlib.compress(raw_rows)
        return sig + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b'')

    def _remove_empty_load_images(self, workflow: Dict) -> None:
        """Entfernt leere LoadImage-Nodes und deren Verbindungen aus dem Workflow.

        Wenn ein LoadImage-Node kein echtes Referenzbild erhalten hat (image leer),
        wird er komplett entfernt. Alle Verbindungen anderer Nodes zu diesem Node
        werden ebenfalls entfernt. So verhaelt sich der Workflow wie beim
        ComfyUI-Bypass: der TextEncoder arbeitet ohne Referenzbild-Conditioning.
        """
        # Leere LoadImage-Nodes sammeln
        empty_node_ids = set()
        for node_id, node in workflow.items():
            if node.get("class_type") not in ("LoadImage", "LoadAndResizeImage"):
                continue
            img_val = node.get("inputs", {}).get("image", "")
            if not img_val or img_val in self._PLACEHOLDER_IMAGE_NAMES:
                title = node.get("_meta", {}).get("title", node_id)
                empty_node_ids.add(node_id)
                logger.debug(f"Leerer/Platzhalter-LoadImage-Node '{title}' (Node {node_id}, image={img_val!r}) wird entfernt")

        if not empty_node_ids:
            return

        # Verbindungen zu leeren Nodes aus allen anderen Nodes entfernen.
        # Crystools-Switches haben on_true UND on_false beide als required —
        # wenn nur einer gekappt wuerde, validiert ComfyUI den Switch nicht mehr.
        # Daher: vor dem Entfernen eines on_true-Wires den noch gueltigen
        # on_false-Wire kopieren (und umgekehrt), damit der Switch wohlgeformt
        # bleibt. Der boolean-Flag (vom Upload-Pfad gesetzt) entscheidet weiter
        # welche Quelle tatsaechlich genutzt wird.
        for node_id, node in workflow.items():
            if node_id in empty_node_ids:
                continue
            inputs = node.get("inputs", {})
            is_switch = node.get("class_type") == "Switch any [Crystools]"
            keys_to_remove = []
            for key, value in inputs.items():
                if not (isinstance(value, list) and len(value) == 2):
                    continue
                if str(value[0]) not in empty_node_ids:
                    continue
                title = node.get("_meta", {}).get("title", node_id)
                if is_switch and key in ("on_true", "on_false"):
                    other = "on_false" if key == "on_true" else "on_true"
                    other_val = inputs.get(other)
                    if (isinstance(other_val, list) and len(other_val) == 2
                            and str(other_val[0]) not in empty_node_ids):
                        # Rewire auf die noch gueltige Quelle (deepcopy nicht
                        # noetig — die Liste wird nicht mutiert).
                        inputs[key] = list(other_val)
                        logger.debug(
                            "Switch '%s' (Node %s): %s -> Node %s entfernt, rewired auf %s (Node %s)",
                            title, node_id, key, value[0], other, other_val[0])
                        # boolean so setzen, dass die jetzt KORREKTE Quelle
                        # genutzt wird (key=on_true gekappt → boolean=False).
                        if "boolean" in inputs:
                            inputs["boolean"] = (key == "on_false")
                        continue
                logger.debug(f"Verbindung '{key}' in '{title}' (Node {node_id}) -> Node {value[0]} entfernt")
                keys_to_remove.append(key)
            for key in keys_to_remove:
                del inputs[key]

        # Leere Nodes aus Workflow entfernen
        for node_id in empty_node_ids:
            del workflow[node_id]

        # IPAdapter-Nodes ohne image-Input bypassen:
        # Wenn ein IPAdapter-Node sein Referenzbild verloren hat, wird er
        # entfernt und sein model-Input direkt an die Konsumenten weitergereicht.
        bypass_node_ids = set()
        for node_id, node in workflow.items():
            class_type = node.get("class_type", "")
            if "IPAdapter" not in class_type or "Loader" in class_type:
                continue
            inputs = node.get("inputs", {})
            if "image" not in inputs:
                bypass_node_ids.add(node_id)
                title = node.get("_meta", {}).get("title", node_id)
                logger.debug(f"IPAdapter-Node '{title}' (Node {node_id}) hat kein image-Input, wird bypassed")

        for bypass_id in bypass_node_ids:
            bypass_node = workflow[bypass_id]
            # model-Input des IPAdapter-Nodes (der Upstream-Model-Anschluss)
            model_source = bypass_node.get("inputs", {}).get("model")
            # Alle Nodes umverdrahten, die auf den bypassed Node zeigen
            for node_id, node in workflow.items():
                if node_id == bypass_id:
                    continue
                inputs = node.get("inputs", {})
                for key, value in list(inputs.items()):
                    if isinstance(value, list) and len(value) == 2 and str(value[0]) == bypass_id:
                        if model_source and key == "model":
                            inputs[key] = model_source
                            logger.debug(f"Node {node_id} '{key}' umverdrahtet: {bypass_id} -> {model_source}")
                        else:
                            del inputs[key]
                            logger.debug(f"Node {node_id} '{key}' -> {bypass_id} entfernt (kein Bypass moeglich)")
            # Zugehoerige Nodes entfernen (IPAdapterLoader, CLIPVision) wenn nicht anderweitig genutzt
            for dep_key in ("ipadapter", "clip_vision"):
                dep_ref = bypass_node.get("inputs", {}).get(dep_key)
                if isinstance(dep_ref, list) and len(dep_ref) == 2:
                    dep_id = str(dep_ref[0])
                    # Pruefen ob noch andere Nodes diesen dep_id nutzen
                    still_used = False
                    for nid, n in workflow.items():
                        if nid == bypass_id or nid == dep_id:
                            continue
                        for v in n.get("inputs", {}).values():
                            if isinstance(v, list) and len(v) == 2 and str(v[0]) == dep_id:
                                still_used = True
                                break
                        if still_used:
                            break
                    if not still_used and dep_id in workflow:
                        title = workflow[dep_id].get("_meta", {}).get("title", dep_id)
                        logger.debug(f"Ungenutzer Node '{title}' (Node {dep_id}) wird entfernt")
                        del workflow[dep_id]
            del workflow[bypass_id]

    def check_availability(self) -> bool:
        """Testet Verbindung via GET /system_stats — Fallback /queue."""
        try:
            resp = requests.get(f"{self.api_url}/system_stats", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                version = data.get("system", {}).get("comfyui_version", "?")
                devices = data.get("devices", [])
                gpu_name = devices[0].get("name", "?") if devices else "keine GPU"
                self._mark_available(f"ComfyUI v{version} ({gpu_name})")
                return self.available
            # /system_stats nicht-200 (z.B. 500 durch kaputten Custom-Node):
            # Fallback /queue als Liveness-Check — leichter Endpoint, immer da.
            logger.debug(f"{self.name}: /system_stats HTTP {resp.status_code}, probiere /queue")
            try:
                q_resp = requests.get(f"{self.api_url}/queue", timeout=5)
                if q_resp.status_code == 200:
                    self._mark_available(f"via /queue, /system_stats wirft {resp.status_code}")
                    return self.available
            except Exception:
                pass
            self._mark_unavailable(f"HTTP {resp.status_code}")
        except requests.exceptions.ConnectionError:
            self._mark_unavailable()
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
            self._was_available = False
        return self.available

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generiert Bilder ueber ComfyUI Prompt-Queue API."""
        workflow = self._load_workflow(params.get("workflow_file", ""))

        # --- Workflow parametrisieren ---
        # Seed randomisieren, aber nur wenn kein input_seed Node vorhanden
        # (input_seed Workflows steuern den Seed ueber PrimitiveInt -> KSampler/RandomNoise Referenz)
        has_input_seed = self._find_node_by_title(workflow, "input_seed") is not None
        sampler_node = self._find_node_by_class(workflow, "KSampler")
        if sampler_node and not has_input_seed:
            workflow[sampler_node]["inputs"]["seed"] = random.randint(0, 2**63)
        # SamplerCustomAdvanced nutzt RandomNoise-Node fuer den Seed
        noise_node = self._find_node_by_class(workflow, "RandomNoise")
        if noise_node and not has_input_seed:
            workflow[noise_node]["inputs"]["noise_seed"] = random.randint(0, 2**63)

        # Input-Nodes per Title befuellen

        # Separated Prompt Workflow (character + pose + expression)
        _char_node = self._find_node_by_title(workflow, "input_prompt_character")
        _pose_prompt_node = self._find_node_by_title(workflow, "input_prompt_pose")
        _expr_node = self._find_node_by_title(workflow, "input_prompt_expression")

        if _char_node and _pose_prompt_node and _expr_node:
            workflow[_char_node]["inputs"]["text"] = params.get("character_prompt", prompt)
            # Fallback: wenn pose/expression leer, vollen Prompt in character_node
            # und neutrale Defaults fuer pose/expression (z.B. Location-Bilder)
            _pose = params.get("pose_prompt", "")
            _expr = params.get("expression_prompt", "")
            if not _pose and not _expr:
                from app.core.expression_pose_maps import DEFAULT_EXPRESSION, DEFAULT_POSE
                _pose = DEFAULT_POSE
                _expr = DEFAULT_EXPRESSION
            workflow[_pose_prompt_node]["inputs"]["text"] = _pose
            workflow[_expr_node]["inputs"]["text"] = _expr
            logger.info("Separated prompts: character=%d, pose=%d, expression=%d chars",
                        len(params.get("character_prompt", prompt)),
                        len(params.get("pose_prompt", "")),
                        len(params.get("expression_prompt", "")))
        else:
            # Positive Prompt (Format 1: PrimitiveString, Format 2: CLIPTextEncode)
            pos_input = self._find_node_by_title(workflow, "input - prompt - positive")
            if pos_input:
                workflow[pos_input]["inputs"]["value"] = prompt
            else:
                pos_clip = self._find_node_by_title(workflow, "input_prompt_positiv")
                if pos_clip:
                    # "value" fuer PrimitiveStringMultiline, "prompt" fuer TextEncodeQwenImageEditPlus, "text" fuer CLIPTextEncode
                    inputs = workflow[pos_clip]["inputs"]
                    prompt_field = "value" if "value" in inputs else ("prompt" if "prompt" in inputs else "text")
                    workflow[pos_clip]["inputs"][prompt_field] = prompt
                else:
                    pos_node = self._find_positive_clip(workflow)
                    if pos_node:
                        workflow[pos_node]["inputs"]["text"] = prompt

        # Negative Prompt (Format 1: PrimitiveString, Format 2: CLIPTextEncode/TextEncode)
        neg_input = self._find_node_by_title(workflow, "input - prompt - negative")
        if neg_input:
            workflow[neg_input]["inputs"]["value"] = negative_prompt or ""
        else:
            neg_clip = self._find_node_by_title(workflow, "input_prompt_negativ")
            if neg_clip:
                inputs = workflow[neg_clip]["inputs"]
                prompt_field = "value" if "value" in inputs else ("prompt" if "prompt" in inputs else "text")
                workflow[neg_clip]["inputs"][prompt_field] = negative_prompt or ""
            else:
                neg_node = self._find_negative_clip(workflow)
                if neg_node:
                    workflow[neg_node]["inputs"]["text"] = negative_prompt or ""

        # Width / Height — Prioritaetskette:
        #   1. caller-explizit via params['width']/['height'] (gewinnt)
        #   2. Workflow-eigene input_*-Nodes bleiben unangetastet (deren JSON-Wert wirkt)
        #   3. 1024 als finaler Fallback nur wenn Flux2Scheduler einen Literal-Wert braucht
        #
        # Items, Default-Items und Outfit-Pieces uebergeben kein width/height,
        # daher rendert ComfyUI in der Aufloesung die im Workflow-JSON steht.
        # World-Backgrounds, Map-Icons, Day/Night-Variants und Expression-
        # Variants uebergeben hingegen explizite Werte und ueberschreiben damit.
        explicit_w = params.get("width")
        explicit_h = params.get("height")
        has_explicit = explicit_w is not None and explicit_h is not None

        def _read_workflow_dim(dim_attr: str) -> Optional[int]:
            """Liest den effektiven Workflow-Wert aus den input_*-Nodes
            (input_width / input_height fuer dim_attr='value', input_size
            fuer dim_attr in ('width','height')). Gibt None zurueck wenn
            der Workflow keinen passenden Node hat."""
            attr_title = "input_width" if dim_attr == "width" else "input_height"
            n = self._find_node_by_title(workflow, attr_title)
            if n is not None:
                v = workflow[n].get("inputs", {}).get("value")
                if isinstance(v, int):
                    return v
            n = self._find_node_by_title(workflow, "input_size")
            if n is not None:
                v = workflow[n].get("inputs", {}).get(dim_attr)
                if isinstance(v, int):
                    return v
            n = self._find_node_by_title(workflow, f"input - {dim_attr}")
            if n is not None:
                v = workflow[n].get("inputs", {}).get("value")
                if isinstance(v, int):
                    return v
            return None

        if has_explicit:
            w = int(explicit_w)
            h = int(explicit_h)
            # Caller-Override: alle bekannten input_*-Patterns patchen, damit
            # der Effekt erreicht wird egal wie der Workflow strukturiert ist.
            for title in ("input - width", "input_width"):
                n = self._find_node_by_title(workflow, title)
                if n is not None:
                    workflow[n]["inputs"]["value"] = w
            for title in ("input - height", "input_height"):
                n = self._find_node_by_title(workflow, title)
                if n is not None:
                    workflow[n]["inputs"]["value"] = h
            n = self._find_node_by_title(workflow, "input_size")
            if n is not None:
                workflow[n]["inputs"]["width"] = w
                workflow[n]["inputs"]["height"] = h
            logger.info(f"caller-override size: {w}x{h}")
        else:
            # Kein Caller-Override → Workflow-Wert wirken lassen. Nur
            # auslesen fuer das Flux2Scheduler-Literal-Hardening unten.
            w = _read_workflow_dim("width") or 1024
            h = _read_workflow_dim("height") or 1024
            logger.info(f"workflow size: {w}x{h} (no caller override)")

        # Flux2Scheduler haerten: im Workflow-Design sind width/height oft an
        # ein LoadAndResizeImage (input_reference_image_background) verkabelt.
        # Wenn dieses Bild leer ist, wird der Node spaeter durch
        # _remove_empty_load_images entfernt — und Flux2Scheduler verliert
        # damit seine width/height-Verbindungen. Praeventiv: Literal-Werte
        # direkt setzen, dann ist die Verkabelung nicht mehr noetig.
        scheduler_node = self._find_node_by_class(workflow, "Flux2Scheduler")
        if scheduler_node:
            workflow[scheduler_node]["inputs"]["width"] = w
            workflow[scheduler_node]["inputs"]["height"] = h
            logger.debug("Flux2Scheduler width/height auf Literal-Werte gesetzt: %dx%d", w, h)

        # Model-Name in input_model Node setzen (PrimitiveString, CheckpointLoaderSimple oder UNETLoader)
        model_name = params.get("model", "")
        if model_name:
            model_node = self._find_node_by_title(workflow, "input_model")
            if model_node:
                class_type = workflow[model_node].get("class_type", "")
                if class_type == "UNETLoader":
                    workflow[model_node]["inputs"]["unet_name"] = model_name
                    _wdt0 = (params.get("weight_dtype") or "").strip()
                    if _wdt0 and "weight_dtype" in workflow[model_node]["inputs"]:
                        workflow[model_node]["inputs"]["weight_dtype"] = _wdt0
                elif class_type == "CheckpointLoaderSimple":
                    workflow[model_node]["inputs"]["ckpt_name"] = model_name
                else:
                    workflow[model_node]["inputs"]["value"] = model_name

        # UNet-Modell in den passenden Loader-Node schreiben.
        # Workflows wie Qwen haben BEIDE Loader (input_safetensors + input_gguf)
        # plus einen safetensors_gguf Switch — der Code muss anhand der Datei-
        # Endung den richtigen Loader befuellen UND den Switch entsprechend
        # auf boolean=True (safetensors) bzw. False (gguf) setzen.
        # Workflows mit nur einem Loader (z.B. Flux only-safetensors) werden
        # weiterhin korrekt bedient — der jeweils nicht vorhandene Node
        # wird ignoriert.
        _model_for_loader = params.get("unet", "") or params.get("model", "")
        if _model_for_loader:
            _is_gguf = _model_for_loader.lower().endswith(".gguf")
            _safe_node = self._find_node_by_title(workflow, "input_safetensors")
            _gguf_node = self._find_node_by_title(workflow, "input_gguf")
            _unet_node = self._find_node_by_title(workflow, "input_unet")

            # Ziel-Loader anhand Endung waehlen, Fallback auf den vorhandenen.
            if _is_gguf and _gguf_node:
                _target_node = _gguf_node
                _target_kind = "gguf"
            elif (not _is_gguf) and _safe_node:
                _target_node = _safe_node
                _target_kind = "safetensors"
            elif _gguf_node and _is_gguf:
                _target_node = _gguf_node
                _target_kind = "gguf"
            else:
                _target_node = _safe_node or _unet_node or _gguf_node
                _target_kind = "safetensors" if _target_node == _safe_node else "gguf" if _target_node == _gguf_node else "unet"

            if _target_node:
                _cls = workflow[_target_node].get("class_type", "")
                _inputs = workflow[_target_node].get("inputs", {})
                # UnetLoaderGGUF + UNETLoader nutzen beide `unet_name`. Nur die
                # aelteren `LoaderGGUF`-Varianten (city96) haben `gguf_name`.
                _key = "gguf_name" if "gguf_name" in _inputs else "unet_name"
                _inputs[_key] = _model_for_loader
                logger.debug(f"Model -> {_target_kind} ({_cls}.{_key}): {_model_for_loader}")
                # weight_dtype patchen (nur UNETLoader/Safetensors — GGUF hat keinen).
                # Leerer/fehlender Param laesst den Workflow-Wert unveraendert.
                _wdt = (params.get("weight_dtype") or "").strip()
                if _wdt and "weight_dtype" in _inputs:
                    _inputs["weight_dtype"] = _wdt
                    logger.info(f"weight_dtype -> {_wdt} (node {_target_node})")

            # input_unet (Legacy) auch befuellen, falls separat vorhanden
            if _unet_node and _unet_node != _target_node:
                workflow[_unet_node]["inputs"]["unet_name"] = _model_for_loader
                logger.debug(f"input_unet (Legacy) auch gesetzt: {_model_for_loader}")

            # safetensors_gguf Switch automatisch auf passenden Branch.
            # Verkabelung der aktuellen Workflows (qwen, flux2):
            #   on_true  -> input_gguf
            #   on_false -> input_safetensors
            # → boolean=True bei .gguf-Modellen, False bei .safetensors.
            #
            # Crystools "Switch any" fuehrt BEIDE Branches eager aus (nicht
            # lazy). Der ungenutzte Loader wuerde mit leerem oder falsch-Format
            # Modell scheitern und den KSampler crashen. Loesung: den ungenutzten
            # Branch auf den genutzten Branch umbiegen — dadurch hat der
            # ungenutzte Loader-Node keinen Consumer mehr und ComfyUI ignoriert
            # ihn beim Build des Execution-Graph.
            _gguf_switch = (self._find_node_by_title(workflow, "input_safetensors_gguf")
                            or self._find_node_by_title(workflow, "safetensors_gguf"))
            if _gguf_switch:
                _switch_inputs = workflow[_gguf_switch].get("inputs", {})
                if "boolean" in _switch_inputs:
                    _switch_inputs["boolean"] = _is_gguf
                    used_branch = "on_true" if _is_gguf else "on_false"
                    unused_branch = "on_false" if _is_gguf else "on_true"
                    used_ref = _switch_inputs.get(used_branch)
                    if isinstance(used_ref, list) and len(used_ref) == 2:
                        _switch_inputs[unused_branch] = list(used_ref)
                        logger.info(
                            f"safetensors_gguf Switch: boolean={_is_gguf} "
                            f"({'gguf' if _is_gguf else 'safetensors'}) — "
                            f"{unused_branch} rewired to {used_branch}={used_ref} "
                            f"(model={_model_for_loader})")
                    else:
                        logger.info(
                            f"safetensors_gguf Switch: boolean={_is_gguf} "
                            f"({'gguf' if _is_gguf else 'safetensors'}) — model={_model_for_loader}")

        # CLIP setzen — single (CLIPLoader, input_clip) oder dual (DualCLIPLoader,
        # input_dual_cliploader). Bei Dual: clip_name1=clip_name, clip_name2=clip_name2.
        clip_name = params.get("clip_name", "")
        clip_name2 = params.get("clip_name2", "")
        if clip_name:
            clip_node = (self._find_node_by_title(workflow, "input_clip")
                         or self._find_node_by_title(workflow, "input_dual_cliploader"))
            if clip_node:
                _cin = workflow[clip_node]["inputs"]
                if "clip_name1" in _cin:  # DualCLIPLoader
                    _cin["clip_name1"] = clip_name
                    if clip_name2:
                        _cin["clip_name2"] = clip_name2
                    logger.debug(f"CLIP (dual): {clip_name} + {clip_name2}")
                else:
                    _cin["clip_name"] = clip_name
                    logger.debug(f"CLIP: {clip_name}")
                # CLIP-Loader-type passend zum Modell setzen (z.B. ClipLoaderGGUF /
                # DualCLIPLoader haben einen 'type'-Input: flux2 / qwen_image / ...).
                _clip_type = params.get("clip_type", "")
                if _clip_type and "type" in _cin:
                    _cin["type"] = _clip_type
                    logger.debug(f"CLIP type: {_clip_type}")

        # VAE setzen (VAELoader, input_vae). Nur den vae_name-Input anfassen.
        vae_name = params.get("vae_name", "")
        if vae_name:
            vae_node = self._find_node_by_title(workflow, "input_vae")
            if vae_node:
                _vin = workflow[vae_node]["inputs"]
                if "vae_name" in _vin:
                    _vin["vae_name"] = vae_name
                    logger.debug(f"VAE: {vae_name}")

        # Seed in input_seed Node setzen (PrimitiveInt)
        seed_value = params.get("seed")
        if seed_value is not None:
            seed_node = self._find_node_by_title(workflow, "input_seed")
            if seed_node:
                workflow[seed_node]["inputs"]["value"] = int(seed_value)
                logger.debug(f"Seed: {seed_value}")

        # Alle Referenz-Slots mit Placeholder ueberschreiben, damit keine
        # Bilder aus vorherigen Generierungen im Workflow landen.
        # Lock schuetzt die gesamte Sequenz: Slot-Reset → Upload → Queue-Submit.
        ref_images = params.get("reference_images", {})
        # Workflows koennen entweder pro Slot einen Node haben
        # ("input_reference_image_1/_2/...") oder einen einzelnen Node ohne
        # Suffix ("input_reference_image") oder einen benannten Slot
        # ("input_reference_image_background" bei Flux2). Alle erkennen,
        # damit der Slot-Reset auch bei Flux2 ohne Background sauber laeuft.
        _has_ref_nodes = bool(
            self._find_node_by_title(workflow, "input_reference_image_1")
            or self._find_node_by_title(workflow, "input_reference_image")
            or self._find_node_by_title(workflow, "input_reference_image_background"))
        self._slot_lock.acquire()
        # VRAM des ComfyUI-Servers freigeben — aber nur wenn das Modell-Setup
        # sich gegenueber dem letzten Run auf diesem Backend geaendert hat.
        # Signature: workflow_file + Hauptmodell (model/unet/gguf/checkpoint).
        _gen_sig = "|".join([
            params.get("workflow_file", "") or "",
            str(params.get("model", "") or params.get("unet", "")
                or params.get("gguf", "") or params.get("checkpoint", "") or ""),
        ])
        self._free_comfyui_memory(signature=_gen_sig)
        # Deterministischer Slot-Praefix pro Workflow (kein Timestamp) — Reset,
        # Upload und Legacy-Placeholder treffen denselben Dateinamen.
        _slot_prefix = self._wf_slot_prefix(params)
        if ref_images or _has_ref_nodes:
            self._reset_reference_slots(_slot_prefix)

        # Referenzbilder hochladen und in LoadImage-Nodes einsetzen.
        # Jeder Slot bekommt einen festen Dateinamen (_slot_ref_N.png),
        # der beim naechsten Run wieder ueberschrieben wird.
        _activated_switches = set()  # Switch-Nodes die aktiviert wurden
        _slot_map = {}  # node_title -> slot_name Zuordnung
        _injected_nodes = set()  # node_ids die diesen Run ein Bild bekamen
        import re as _re
        for i, (node_title, file_path) in enumerate(ref_images.items()):
            ref_node = self._find_node_by_title(workflow, node_title)
            # Fallback: wenn der Workflow nur einen einzelnen Slot ohne
            # Suffix hat (Flux.2 GGUF), input_reference_image_1 darauf mappen.
            if not ref_node and node_title == "input_reference_image_1":
                ref_node = self._find_node_by_title(workflow, "input_reference_image")
            if ref_node and file_path:
                # Slot-Name aus Node-Title ableiten damit Datei und Node
                # semantisch zusammenpassen: input_reference_image_N → _slot_ref_N.png
                _m = _re.search(r'_(\d+)$', node_title)
                if _m:
                    _n = int(_m.group(1))
                    if 1 <= _n <= len(self._REF_SLOT_NAMES):
                        slot_idx = _n - 1
                    else:
                        slot_idx = min(i, len(self._REF_SLOT_NAMES) - 1)
                else:
                    slot_idx = min(i, len(self._REF_SLOT_NAMES) - 1)
                slot_name = f"{_slot_prefix}{self._REF_SLOT_NAMES[slot_idx]}"
                _slot_map[node_title] = slot_name
                uploaded = self._upload_image(file_path, slot_name=slot_name)
                if uploaded:
                    workflow[ref_node]["inputs"]["image"] = uploaded
                    _injected_nodes.add(ref_node)
                    # Width/Height auf LoadAndResizeImage-Nodes setzen (z.B. Qwen-Workflow)
                    if "width" in workflow[ref_node]["inputs"]:
                        workflow[ref_node]["inputs"]["width"] = w
                        workflow[ref_node]["inputs"]["height"] = h
                    # Switch-Node aktivieren. Naming-Konventionen:
                    #   "<title>_on"        — Multi-Slot Workflows (Z-Image)
                    #   "<title>_use"       — Multi-Slot mit explizitem use-Switch
                    #   "input_reference_image_use" — Single-Slot (Flux.2 GGUF)
                    on_node = (
                        self._find_node_by_title(workflow, f"{node_title}_on")
                        or self._find_node_by_title(workflow, f"{node_title}_use")
                        or self._find_node_by_title(workflow, "input_reference_image_use"))
                    if on_node:
                        workflow[on_node]["inputs"]["boolean"] = True
                        _activated_switches.add(on_node)
                        logger.debug(f"Switch '{on_node}' (fuer {node_title}): true")
                    # Nachvollziehbarkeit: welche QUELLDATEI (= mapblend_debug-Kopie
                    # bei Map-Fit/Edge) geht unveraendert in welchen Node/Slot auf
                    # ComfyUI. md5/Groesse erlauben den 1:1-Abgleich mit den Debug-
                    # Dateien (Upload ist roh, keine Transformation).
                    try:
                        import hashlib as _hl
                        with open(file_path, "rb") as _rf:
                            _raw = _rf.read()
                        _dig = _hl.md5(_raw).hexdigest()[:12]
                        logger.info("Ref-Inject: node '%s' <- %s (%d B, md5=%s) -> ComfyUI '%s'",
                                    node_title, os.path.basename(file_path), len(_raw), _dig, uploaded)
                    except Exception:
                        logger.info("Ref-Inject: node '%s' <- %s -> ComfyUI '%s'",
                                    node_title, file_path, uploaded)

        # Nicht befuellte Referenz-Slots auf den Placeholder zeigen lassen.
        # Sonst behaelt eine input_reference_image*-Node ihren im Workflow-File
        # fest verdrahteten image-Wert (z.B. ein altes "Vallerie_...png" aus dem
        # Workflow-Design) — existiert die Datei auf dem ComfyUI-Server nicht,
        # faellt die ganze Generierung mit HTTP 400 ("Invalid image file"). Die
        # Placeholder-Dateien (<prefix>_slot_ref_N.png) wurden oben bereits per
        # _reset_reference_slots hochgeladen. Nur input_*-Nodes (Konvention).
        if _has_ref_nodes:
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                if node_id in _injected_nodes:
                    continue
                title = node.get("_meta", {}).get("title", "")
                if not title.startswith("input_reference_image"):
                    continue
                # Switch-/Typ-Hilfsnodes nicht anfassen (kein Bild-Input).
                inputs = node.get("inputs", {})
                if "image" not in inputs:
                    continue
                _m = _re.search(r'_(\d+)$', title)
                _idx = (int(_m.group(1)) - 1) if _m else 0
                if not (0 <= _idx < len(self._REF_SLOT_NAMES)):
                    _idx = 0
                inputs["image"] = f"{_slot_prefix}{self._REF_SLOT_NAMES[_idx]}"
                logger.debug("Leerer Ref-Slot '%s' -> Placeholder %s", title, inputs["image"])

        # Inaktive Switch-Nodes: boolean=false setzen — aber NUR REFERENZ-Switches
        # (Titel enthaelt "reference_image"). Diese sind so designt, dass on_false
        # auf EmptyImage zeigt, ungenutzte Ref-Slots routen sauber dorthin. Andere
        # Crystools-Switches sind User-Workflow-Design (z.B. der Modell-Wahlschalter
        # "input_safetensors_gguf", den der Dual-Loader-Code oben anhand der Datei-
        # Endung selbst setzt) und duerfen hier NICHT angefasst werden — sonst kippt
        # die Generierung still auf den falschen Modell-/Verkabelungs-Zweig.
        for node_id, node in workflow.items():
            if node.get("class_type") != "Switch any [Crystools]":
                continue
            if node_id in _activated_switches:
                continue
            if "reference_image" not in node.get("_meta", {}).get("title", "").lower():
                continue
            inputs = node.get("inputs", {})
            if "boolean" in inputs:
                inputs["boolean"] = False
            logger.debug(f"Switch '{node.get('_meta', {}).get('title', node_id)}': inaktiv")

        # Boolean-Inputs in PrimitiveBoolean-Nodes setzen
        for node_title, value in params.get("boolean_inputs", {}).items():
            bool_node = self._find_node_by_title(workflow, node_title)
            if bool_node:
                workflow[bool_node]["inputs"]["value"] = bool(value)
                logger.debug(f"Boolean '{node_title}': {value}")

        # String-Inputs in PrimitiveString-Nodes setzen (z.B. _type Nodes)
        for node_title, value in params.get("string_inputs", {}).items():
            str_node = self._find_node_by_title(workflow, node_title)
            if str_node:
                workflow[str_node]["inputs"]["value"] = str(value)
                logger.debug(f"String '{node_title}': {value}")

        # Float-Inputs in PrimitiveFloat-Nodes setzen (z.B. input_denoise_strength)
        for node_title, value in params.get("float_inputs", {}).items():
            float_node = self._find_node_by_title(workflow, node_title)
            if float_node:
                try:
                    workflow[float_node]["inputs"]["value"] = float(value)
                    logger.debug(f"Float '{node_title}': {value}")
                except (TypeError, ValueError):
                    logger.debug(f"Float '{node_title}': invalid value {value!r}")

        # LoRA-Inputs in input_loras Node setzen (z.B. "Lora Loader Stack (rgthree)")
        lora_inputs = params.get("lora_inputs", [])
        if lora_inputs:
            lora_node = self._find_node_by_title(workflow, "input_loras")
            if lora_node:
                for i, lora in enumerate(lora_inputs[:4], start=1):
                    lora_name = (lora.get("name") or "None").strip() or "None"
                    try:
                        lora_strength = float(lora.get("strength", 1.0))
                    except (TypeError, ValueError):
                        lora_strength = 1.0
                    workflow[lora_node]["inputs"][f"lora_0{i}"] = lora_name
                    workflow[lora_node]["inputs"][f"strength_0{i}"] = lora_strength
                    logger.debug(f"LoRA {i}: {lora_name} (strength={lora_strength})")

        # LoRA-Inputs in input_lora Node setzen (z.B. "Power Lora Loader (rgthree)")
        # Format: lora_1: {on: bool, lora: str, strength: float}
        if lora_inputs:
            power_lora_node = self._find_node_by_title(workflow, "input_lora")
            if power_lora_node:
                for i, lora in enumerate(lora_inputs[:4], start=1):
                    lora_name = (lora.get("name") or "").strip()
                    try:
                        lora_strength = float(lora.get("strength", 1.0))
                    except (TypeError, ValueError):
                        lora_strength = 1.0
                    lora_active = bool(lora_name and lora_name != "None")
                    workflow[power_lora_node]["inputs"][f"lora_{i}"] = {
                        "on": lora_active,
                        "lora": lora_name if lora_active else "",
                        "strength": lora_strength,
                    }
                    logger.debug(f"Power LoRA {i}: {lora_name} (on={lora_active}, strength={lora_strength})")

        # Flux.2 Placeholder-Workaround NUR fuer alte Workflows ohne
        # input_reference_image_use-Switch. Neue Workflows leiten ueber
        # den Switch direkt auf EmptyImage, der Workaround wuerde dort
        # ungewollt das alte Ref-Bild aus _slot_ref_1.png reaktivieren.
        _use_switch = self._find_node_by_title(workflow, "input_reference_image_use")
        if not _use_switch:
            _ref1_node = (
                self._find_node_by_title(workflow, "input_reference_image_1")
                or self._find_node_by_title(workflow, "input_reference_image"))
            if _ref1_node:
                _ref1_image = workflow[_ref1_node]["inputs"].get("image", "")
                if not _ref1_image:
                    workflow[_ref1_node]["inputs"]["image"] = f"{_slot_prefix}{self._REF_SLOT_NAMES[0]}"
                    # Width/Height auf Ziel-Dimensionen setzen (statt 8x8 vom Placeholder)
                    # damit Flux2Scheduler korrekte Dimensionen bekommt
                    if "width" in workflow[_ref1_node]["inputs"]:
                        workflow[_ref1_node]["inputs"]["width"] = w
                        workflow[_ref1_node]["inputs"]["height"] = h
                    logger.debug("Flux.2 Legacy-Placeholder gesetzt (%s, %dx%d)",
                                 self._REF_SLOT_NAMES[0], w, h)

        # Leere LoadImage-Nodes entfernen (inkl. Verbindungen)
        # Verhindert, dass Placeholder-Bilder als Referenz-Conditioning wirken
        # und z.B. ungewollte Personen in Location-Bildern erzeugen.
        self._remove_empty_load_images(workflow)

        wf_name = params.get("workflow_file", "")
        # Checkpoint/Model aus Workflow extrahieren (fuer Logging + Image Prompt Log)
        wf_checkpoint = "N/A"
        _model_node = self._find_node_by_title(workflow, "input_model")
        if _model_node:
            wf_checkpoint = workflow[_model_node]["inputs"].get("value", "?")
        if wf_checkpoint in ("N/A", "?", ""):
            ckpt_node = self._find_node_by_class(workflow, "CheckpointLoaderSimple")
            wf_checkpoint = workflow[ckpt_node]["inputs"].get("ckpt_name", "?") if ckpt_node else "N/A"
        if wf_checkpoint in ("N/A", "?", ""):
            unet_node = self._find_node_by_class(workflow, "UNETLoader")
            wf_checkpoint = workflow[unet_node]["inputs"].get("unet_name", "?") if unet_node else "N/A"
        if wf_checkpoint in ("N/A", "?", ""):
            unet_gguf_node = self._find_node_by_class(workflow, "UnetLoaderGGUF")
            wf_checkpoint = workflow[unet_gguf_node]["inputs"].get("unet_name", "?") if unet_gguf_node else "N/A"
        # Seed aus KSampler oder RandomNoise extrahieren
        if sampler_node:
            wf_seed = workflow[sampler_node]["inputs"].get("seed", "?")
        elif noise_node:
            wf_seed = workflow[noise_node]["inputs"].get("noise_seed", "?")
        else:
            wf_seed = "?"
        # KSampler-Parameter aus Workflow lesen (Fallback: SamplerCustomAdvanced-Kette)
        if sampler_node:
            wf_steps = workflow[sampler_node]["inputs"].get("steps", "?")
            wf_cfg = workflow[sampler_node]["inputs"].get("cfg", "?")
            wf_sampler_name = workflow[sampler_node]["inputs"].get("sampler_name", "?")
            wf_scheduler = workflow[sampler_node]["inputs"].get("scheduler", "?")
        else:
            # SamplerCustomAdvanced: Steps in Scheduler-Node, CFG in CFGGuider
            scheduler_node = self._find_node_by_class(workflow, "Flux2Scheduler")
            wf_steps = workflow[scheduler_node]["inputs"].get("steps", "?") if scheduler_node else "?"
            cfg_node = self._find_node_by_class(workflow, "CFGGuider")
            wf_cfg = workflow[cfg_node]["inputs"].get("cfg", "?") if cfg_node else "?"
            sampler_select = self._find_node_by_class(workflow, "KSamplerSelect")
            wf_sampler_name = workflow[sampler_select]["inputs"].get("sampler_name", "?") if sampler_select else "?"
            wf_scheduler = "flux2" if scheduler_node else "?"
        logger.info(f"{self.name} ComfyUI Workflow: {self.api_url}/prompt")
        logger.info(f"Workflow: {wf_name}, Checkpoint: {wf_checkpoint}, Size: {w}x{h}")
        logger.info(f"Seed: {wf_seed}, Steps: {wf_steps}, CFG: {wf_cfg}, Sampler: {wf_sampler_name}/{wf_scheduler}")
        logger.info(f"Prompt: {prompt}")
        if negative_prompt:
            logger.info(f"Negative: {negative_prompt}")
        for rt, rp in params.get("reference_images", {}).items():
            logger.debug(f"RefImage: {rt} -> {rp}")
        for bt, bv in params.get("boolean_inputs", {}).items():
            logger.debug(f"Boolean: {bt} = {bv}")
        for st, sv in params.get("string_inputs", {}).items():
            logger.debug(f"String: {st} = {sv}")
        self.last_used_checkpoint = wf_checkpoint

        # 1) Prompt in Queue senden + 2) Pollen + 3) Download — alles unter
        # gehaltenem _slot_lock. Sonst kann ein paralleler Task die Slot-
        # Dateien (_slot_ref_N.png) ueberschreiben, bevor ComfyUI sie bei
        # der Execution liest — ComfyUI liest sie NICHT beim /prompt-Submit.
        payload = {"prompt": workflow}
        try:
            try:
                resp = requests.post(f"{self.api_url}/prompt", json=payload, timeout=30)
            except requests.exceptions.ConnectionError as e:
                logger.error(f"{self.name} Verbindungsfehler: {str(e)[:200]}")
                raise
            except Exception as e:
                logger.error(f"{self.name} Request-Fehler: {str(e)[:200]}")
                raise

            if resp.status_code != 200:
                error_body = resp.text[:500] if hasattr(resp, 'text') else 'N/A'
                logger.error(f"{self.name} HTTP {resp.status_code}: {error_body}")
                resp.raise_for_status()

            result = resp.json()
            prompt_id = result.get("prompt_id", "")
            if not prompt_id:
                logger.error(f"{self.name}: Keine prompt_id in Response: {result}")
                return []

            logger.info(f"Prompt queued: {prompt_id}")

            # 2) Pollen bis fertig
            outputs = {}
            start_time = time.time()
            while time.time() - start_time < self.max_wait:
                time.sleep(self.poll_interval)
                try:
                    hist_resp = requests.get(f"{self.api_url}/history/{prompt_id}", timeout=10)
                    if hist_resp.status_code != 200:
                        continue
                    history = hist_resp.json()
                    if prompt_id not in history:
                        elapsed = int(time.time() - start_time)
                        if elapsed % 10 == 0:
                            logger.info(f"Warte auf Ergebnis... ({elapsed}s)")
                        continue

                    # Fertig!
                    outputs = history[prompt_id].get("outputs", {})
                    status = history[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        err_detail = str(msgs)[:1000] if msgs else "Unbekannter Fehler"
                        logger.error(f"{self.name} Ausfuehrungsfehler: {err_detail}")
                        raise RuntimeError(f"ComfyUI Fehler: {err_detail}")

                    elapsed = round(time.time() - start_time, 1)
                    logger.info(f"Fertig nach {elapsed}s")
                    break
                except RuntimeError:
                    raise  # ComfyUI Ausfuehrungsfehler sofort weitergeben
                except Exception as e:
                    logger.warning(f"Poll-Fehler: {e}")
                    continue
            else:
                logger.error(f"{self.name}: Timeout nach {self.max_wait}s")
                return []

            # 3) Bilder und Videos aus Output-Nodes extrahieren
            # ComfyUI liefert Videos (AnimateDiff, VHS_VideoCombine) unter "gifs" statt "images"
            # Wenn ein "output_final" Node existiert, nur von diesem downloaden
            output_final_id = self._find_node_by_title(workflow, "output_final")
            if output_final_id and output_final_id in outputs:
                target_outputs = {output_final_id: outputs[output_final_id]}
            else:
                target_outputs = outputs

            images = []
            for node_id, node_output in target_outputs.items():
                output_items = node_output.get("images", []) + node_output.get("gifs", [])
                for img_info in output_items:
                    filename = img_info.get("filename", "")
                    subfolder = img_info.get("subfolder", "")
                    img_type = img_info.get("type", "output")
                    if not filename:
                        continue

                    view_params = {"filename": filename, "type": img_type}
                    if subfolder:
                        view_params["subfolder"] = subfolder

                    try:
                        img_resp = requests.get(
                            f"{self.api_url}/view",
                            params=view_params,
                            timeout=30
                        )
                        if img_resp.status_code == 200:
                            images.append(img_resp.content)
                            logger.debug(f"Bild {len(images)}: {filename} ({len(img_resp.content)} bytes)")
                        else:
                            logger.error(f"Bild-Download fehlgeschlagen: HTTP {img_resp.status_code}")
                    except Exception as e:
                        logger.error(f"Bild-Download Fehler: {str(e)[:200]}")

            if images:
                logger.info(f"{self.name}: {len(images)} Bild(er) erfolgreich generiert")
            else:
                logger.warning(f"{self.name}: Keine Bilder in Output gefunden (Duplikat/Cache?)")
                logger.debug(f"Outputs: {json.dumps(outputs, indent=2)[:500]}")
                # Leere Liste aber kein Fehler — Sentinel-String signalisiert "kein neues Bild"
                return "NO_NEW_IMAGE"

            return images
        finally:
            self._slot_lock.release()


class CivitAIBackend(ImageBackend):
    """
    Backend fuer CivitAI Cloud API (asynchron mit Polling).
    API: POST /v1/consumer/jobs → Polling → Download blobUrl
    Modelle im AIR URN Format: urn:air:{ecosystem}:checkpoint:civitai:{modelId}@{versionId}
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
        """Erstellt Auth-Headers fuer CivitAI API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def check_availability(self) -> bool:
        """Prueft ob der API-Key gueltig ist und die API erreichbar."""
        if not self.api_key:
            logger.warning(f"{self.name}: Kein API_KEY konfiguriert")
            self.available = False
            return False
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert (AIR URN erforderlich)")
            self.available = False
            return False

        try:
            # Sauberer authentifizierter GET (KEIN bogus ?token=… — der wurde von
            # CivitAI als ungueltiges Job-Token interpretiert und gab faelschlich
            # 401, obwohl der Bearer-Key gueltig war).
            resp = requests.get(
                f"{self.api_url}/v1/consumer/jobs",
                headers=self._headers(),
                timeout=10)
            if resp.status_code in (401, 403):
                logger.warning(f"{self.name}: API-Key abgelehnt (Status {resp.status_code})")
                self.available = False
                return False

            # Jeder andere Status (auch 400/404) bedeutet: API erreichbar, Key akzeptiert
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
        """Generiert ein Bild ueber die CivitAI API (async mit Polling)."""
        # CivitAI erfordert AIR URN Format - lokale Dateinamen aus params ignorieren
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
        # CivitAI erfordert Dimensionen als Vielfache von 64
        width = round(width / 64) * 64 or 1024
        height = round(height / 64) * 64 or 1024

        # BaseModel aus AIR URN ableiten: urn:air:{ecosystem}:checkpoint:...
        # Ecosystem-Segment direkt extrahieren statt Heuristik — CivitAI nutzt
        # exakt diesen Token als baseModel-Tag.
        model_lower = model.lower()
        ecosystem = ""
        try:
            _parts = model_lower.split(":")
            # urn:air:{ecosystem}:... -> Index 2 ist ecosystem
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

        # Flux-Modelle unterstuetzen nur "Euler" als Scheduler bei CivitAI
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
            # FLUX: kein cfgScale, kein clipSkip, kein negativePrompt
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

        # 1. Job erstellen
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

        # 2. Polling — Result kann dict oder list sein
        #    Format: result=[{blobKey, available, seed, blobUrl?}] oder result={blobUrl, ...}
        #    available=true + blobUrl vorhanden = fertig
        start_time = time.time()
        blob_url = None
        _logged_shape = False  # einmaliges Roh-Logging der Job-Struktur
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
                # Einmal die echte Struktur loggen (Diagnose: blobUrl-Feldname etc.)
                if not _logged_shape:
                    _logged_shape = True
                    logger.info("%s: Job-Struktur (Diagnose) job-keys=%s result=%s",
                                self.name, list(job0.keys()), json.dumps(job0.get("result"))[:300])

                # Explizite Fehler-/Endzustaende erkennen (statt blind bis Timeout).
                _status = str(job0.get("status") or job0.get("$type") or "").lower()
                if any(s in _status for s in ("failed", "error", "canceled", "rejected", "deleted")):
                    logger.error("%s: Job-Status '%s' — Abbruch. Raw: %s",
                                 self.name, _status, _last_raw)
                    return []

                job_result = job0.get("result")
                if job_result is None:
                    continue

                # Result kann list oder dict sein
                result_item = job_result[0] if isinstance(job_result, list) and job_result else job_result
                if isinstance(result_item, dict):
                    available = result_item.get("available", False)
                    # Feldname-Varianten tolerant lesen.
                    url = (result_item.get("blobUrl") or result_item.get("blobUrlExpirationDate") and result_item.get("blobUrl")
                           or result_item.get("url") or "")
                    # Explizit fehlgeschlagenes Result-Item.
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
                    # sonst noch in Bearbeitung -> weiter pollen

            except Exception as e:
                logger.warning(f"{self.name}: Polling-Fehler: {e} ({elapsed}s)")

        if not blob_url:
            logger.error(f"{self.name}: Timeout nach {self.max_wait}s (kein blobUrl). Letzte Response: {_last_raw}")
            return []

        # 3. Bild herunterladen
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


class TogetherBackend(ImageBackend):
    """
    Backend fuer Together.ai Image Generation API.
    API: POST https://api.together.xyz/v1/images/generations
    Unterstuetzt FLUX.1, FLUX.2 und weitere Modelle.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="together", env_prefix=env_prefix)

        self.api_key = api_key or os.environ.get(f"{env_prefix}API_KEY", "")
        self.model = model or os.environ.get(f"{env_prefix}MODEL", "")
        # Komma-getrennte Modellliste fuer Auswahl im UI
        models_str = os.environ.get(f"{env_prefix}MODELS", "").strip()
        self.available_models: List[str] = [m.strip() for m in models_str.split(",") if m.strip()] if models_str else []
        self.num_inference_steps = int(os.environ.get(f"{env_prefix}NUM_INFERENCE_STEPS", "20"))
        self.width = int(os.environ.get(f"{env_prefix}WIDTH", "1024"))
        self.height = int(os.environ.get(f"{env_prefix}HEIGHT", "1024"))
        self.disable_safety = os.environ.get(
            f"{env_prefix}DISABLE_SAFETY", "false"
        ).strip().lower() in ("true", "1", "yes")
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120"))

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def check_availability(self) -> bool:
        if not self.api_key:
            logger.warning(f"{self.name}: Kein API_KEY konfiguriert")
            self.available = False
            return False
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert")
            self.available = False
            return False

        try:
            resp = requests.get(
                f"{self.api_url}/v1/models",
                headers=self._headers(),
                timeout=10)
            if resp.status_code in (401, 403):
                logger.warning(f"{self.name}: API-Key ungueltig (Status {resp.status_code})")
                self.available = False
                return False

            # Bild-Modelle live aus API extrahieren
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    # Together.ai liefert {"data": [...]}, ggf. auch direkt eine Liste
                    all_models = body.get("data", body) if isinstance(body, dict) else body
                    live_models = sorted(
                        [m["id"] for m in all_models if m.get("type") == "image"])
                    if live_models:
                        self.available_models = live_models
                        logger.info(f"{self.name}: {len(live_models)} Bild-Modelle verfuegbar")
                except (ValueError, KeyError):
                    pass  # JSON-Parsing fehlgeschlagen — available_models bleibt wie konfiguriert

            logger.info(f"{self.name} erreichbar (Together.ai, Modell: {self.model})")
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

    # Parameter-Keys die bei 400 einzeln entfernt werden koennen
    _OPTIONAL_KEYS = ("steps", "negative_prompt", "width", "height", "n")

    def _rate_limit_wait(self, resp: requests.Response, attempt: int) -> float:
        """Wartezeit bei 429: bevorzugt Retry-After / X-RateLimit-Reset Header,
        sonst exponentielles Backoff (2,4,8,16s), gedeckelt auf 30s."""
        for h in ("retry-after", "x-ratelimit-reset"):
            v = resp.headers.get(h)
            if not v:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            # Header kann absolute Epoch-Zeit ODER Sekunden sein.
            if f > time.time():
                f = f - time.time()
            if f > 0:
                return max(1.0, min(f, 30.0))
        return min(2.0 * (2 ** (attempt - 1)), 30.0)

    def _post_with_retry(self, payload: Dict[str, Any],
                         optional: Dict[str, Any]) -> requests.Response:
        """Sendet den Request und entfernt bei 400 den beanstandeten Parameter.

        Erkennt aus der Fehlermeldung welcher Parameter nicht unterstuetzt wird
        und wiederholt den Request ohne diesen. Maximal len(optional) Retries.
        """
        remaining = dict(optional)
        _429_retries = 0
        _max_429 = 4

        for _ in range(len(remaining) + 1 + _max_429):
            resp = requests.post(
                f"{self.api_url}/v1/images/generations",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout)
            # Rate-Limit: mit Backoff erneut versuchen statt hart abzubrechen.
            if resp.status_code == 429:
                if _429_retries >= _max_429:
                    error_msg = resp.text[:300] or '(leer)'
                    logger.error(f"{self.name}: Rate-Limit (429) nach {_max_429} Versuchen — Abbruch")
                    raise RuntimeError(f"{self.name}: HTTP 429 (Rate-Limit): {error_msg[:160]}")
                _429_retries += 1
                _wait = self._rate_limit_wait(resp, _429_retries)
                logger.warning(f"{self.name}: Rate-Limit (429), warte {_wait:.1f}s (Versuch {_429_retries}/{_max_429})")
                time.sleep(_wait)
                continue
            if resp.status_code != 400:
                if resp.status_code != 200:
                    error_msg = resp.text[:500] or '(leer)'
                    logger.error(f"{self.name}: Generierung fehlgeschlagen (Status {resp.status_code})")
                    logger.error(f"Response: {error_msg}")
                    raise RuntimeError(f"{self.name}: HTTP {resp.status_code}: {error_msg[:200]}")
                return resp

            # 400: herausfinden welcher Parameter stoert
            error_text = resp.text.lower()
            removed = False
            for key in list(remaining.keys()):
                if key in error_text or (key in ("width", "height") and "dimension" in error_text):
                    logger.warning(f"{self.name}: Parameter '{key}' nicht unterstuetzt, wiederhole ohne")
                    payload.pop(key, None)
                    # width/height immer zusammen entfernen
                    if key in ("width", "height"):
                        payload.pop("width", None)
                        payload.pop("height", None)
                        remaining.pop("width", None)
                        remaining.pop("height", None)
                    else:
                        remaining.pop(key, None)
                    removed = True
                    break

            if not removed:
                # Unbekannter 400-Fehler — nicht wiederholbar
                error_msg = resp.text[:500] or '(leer)'
                logger.error(f"{self.name}: Generierung fehlgeschlagen (Status 400)")
                logger.error(f"Response: {error_msg}")
                raise RuntimeError(f"{self.name}: HTTP 400: {error_msg[:200]}")

        # Sollte nicht erreicht werden
        raise RuntimeError(f"{self.name}: Retry-Limit erreicht")

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Generiert ein Bild ueber die Together.ai API.

        Baut den Payload mit optionalen Parametern (steps, width/height, negative_prompt)
        auf. Falls die API einen Parameter ablehnt (400), wird der betreffende Parameter
        entfernt und der Request automatisch wiederholt.
        """
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps

        # Together.ai erfordert Dimensionen als Vielfache von 8
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "b64_json",
        }

        if self.disable_safety:
            payload["disable_safety_checker"] = True

        # Optionale Parameter — werden bei 400 einzeln entfernt und wiederholt.
        # KEIN "n": Together generiert per Default 1 Bild; viele Modelle lehnen
        # "n" mit 400 ab, und der dann sofortige Retry loeste ein 429
        # ("too many requests in a short window") aus.
        # seed/steps/dimensions sind ebenfalls optional — manche Modell-
        # Architekturen (z.B. GPT-Image) lehnen 'seed' mit 400 ab.
        optional_params: Dict[str, Any] = {}
        if steps:
            optional_params["steps"] = steps
        if width and height:
            optional_params["width"] = width
            optional_params["height"] = height
        if negative_prompt:
            optional_params["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            optional_params["seed"] = seed

        payload.update(optional_params)

        logger.info(f"{self.name}: Starte Generierung...")
        logger.info(f"Modell: {model}, Groesse: {width}x{height}, Steps: {steps}")
        logger.info(f"Prompt: {prompt[:120]}...")

        try:
            resp = self._post_with_retry(payload, optional_params)

            data = resp.json()
            images = []
            for item in data.get("data", []):
                b64 = item.get("b64_json", "")
                if b64:
                    images.append(base64.b64decode(b64))
                    logger.info(f"Bild erhalten: {len(images[-1])} bytes")
                else:
                    # Fallback: URL-basierte Response
                    url = item.get("url", "")
                    if url:
                        img_resp = requests.get(url, timeout=60)
                        if img_resp.status_code == 200:
                            images.append(img_resp.content)
                            logger.info(f"Bild heruntergeladen: {len(images[-1])} bytes")

            if not images:
                logger.error(f"{self.name}: Keine Bilder in Response")
            return images

        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []


class LocalAIBackend(TogetherBackend):
    """LocalAI-style OpenAI-kompatibler Diffusion-Endpoint (POST {url}/v1/images/generations).

    Funktioniert mit LocalAI / vLLM / sd.cpp / jedem Server mit deren Eigenheiten.
    Unterschiede zum Together.ai-spezifischen TogetherBackend:
      - **api_key optional** (LocalAI braucht keinen Bearer-Token).
      - **ref_images-Support** (Flux Kontext / Referenzbild-Conditioning): lokale
        Referenzdateien werden als **rohes base64** mitgeschickt (LocalAI/Flux
        erwartet KEIN data:-URI-Praefix), http(s)-URLs unveraendert durchgereicht.
        Quelle ist params['reference_images'] (vom Skill aufgeloeste Slots —
        dieselbe Quelle wie bei ComfyUI).
      - LoRAs als ``<lora:name:gewicht>``-Prompt-Syntax (sd.cpp/LocalAI), nutzt den
        LocalAI-Parameternamen ``step`` und ``size`` ("WxH") statt width/height.

    Fuer einen Endpoint, der sich an den **strikten OpenAI-Images-Standard** haelt
    (z.B. das LLM-Gateway), siehe die abgeleitete ``OpenAIDiffusionBackend``.

    Erbt _post_with_retry / _rate_limit_wait von TogetherBackend (gleicher Endpoint).
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, env_prefix, api_key=api_key, model=model)
        self.api_type = "localai"

    def _headers(self) -> Dict[str, str]:
        # api_key optional — Authorization nur senden wenn gesetzt.
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_availability(self) -> bool:
        # Kein api_key noetig — nur Erreichbarkeit + konfiguriertes Modell pruefen.
        if not self.model:
            logger.warning(f"{self.name}: Kein MODEL konfiguriert")
            self.available = False
            return False
        try:
            resp = requests.get(f"{self.api_url}/v1/models",
                                headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    items = body.get("data", body) if isinstance(body, dict) else body
                    ids = [m.get("id") for m in items
                           if isinstance(m, dict) and m.get("id")]
                    if ids:
                        self.available_models = sorted(ids)
                except (ValueError, KeyError, AttributeError):
                    pass
                self._mark_available(f"OpenAI-Diffusion, Modell: {self.model}")
                self.available = True
                return True
            self._log_unreachable(f"HTTP {resp.status_code}")
            self.available = False
            self._was_available = False
            return False
        except requests.ConnectionError:
            self._log_unreachable("ConnectionError")
            self.available = False
            self._was_available = False
            return False
        except Exception as e:
            logger.error(f"{self.name} Fehler: {e}")
            self.available = False
            return False

    def _collect_ref_images(self, params: Dict[str, Any]) -> List[str]:
        """ref_images-Liste fuers Conditioning aus params['reference_images'].

        Dict-Werte (slot_title -> lokaler Pfad): http(s)-URLs werden
        durchgereicht, lokale Dateien als **rohes base64** eingebettet.
        WICHTIG: LocalAI/Flux erwartet im ref_images-Feld rohes base64 OHNE
        "data:<mime>;base64,"-Praefix — ein data-URI wird serverseitig nicht
        als Bild erkannt und still ignoriert.
        """
        refs = params.get("reference_images") or {}
        out: List[str] = []
        for _title, path in refs.items():
            if not path:
                continue
            sp = str(path)
            if sp.startswith(("http://", "https://")):
                out.append(sp)
                continue
            if sp.startswith("data:"):
                # data:<mime>;base64,<payload> -> nur <payload> (rohes base64)
                out.append(sp.split(",", 1)[1] if "," in sp else sp)
                continue
            try:
                with open(sp, "rb") as f:
                    raw = f.read()
                out.append(base64.b64encode(raw).decode())
            except Exception as e:
                logger.warning(f"{self.name}: Referenzbild '{sp}' nicht lesbar: {e}")
        return out

    def _with_lora_syntax(self, prompt: str, params: Dict[str, Any]) -> str:
        """Haengt ausgewaehlte LoRAs als ``<lora:name:gewicht>`` an den Prompt an
        (LocalAI/sd.cpp-Syntax). Quelle ist params['lora_inputs'] (vom Skill aus
        der per-Welt-LoRA-Library + per-Character-Overrides aufgeloest). Cloud-
        Backends haben kein lora-Node — die Referenz MUSS im Prompt stehen. Keine
        LoRAs -> Prompt unveraendert; bereits vorhandene <lora:..> nicht doppeln."""
        tags = []
        for l in (params.get("lora_inputs") or params.get("loras") or []):
            if not isinstance(l, dict):
                continue
            name = (l.get("name") or "").strip()
            if not name or name == "None":
                continue
            base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            for ext in (".safetensors", ".ckpt", ".pt"):
                if base.lower().endswith(ext):
                    base = base[:-len(ext)]
                    break
            if f"<lora:{base}" in prompt:
                continue
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            tags.append(f"<lora:{base}:{strength:g}>")
        if tags:
            return (prompt.rstrip() + " " + " ".join(tags)).strip()
        return prompt

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        # Ausgewaehlte LoRAs als <lora:name:gewicht> in den Prompt (die Basis-
        # generate() ergaenzt nur die Trigger-Woerter, nicht die LoRA-Referenz).
        prompt = self._with_lora_syntax(prompt, params)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
        # ref_images bewusst NICHT optional — Conditioning soll nicht bei einem
        # 400 stillschweigend entfernt werden.
        ref_images = self._collect_ref_images(params)
        if ref_images:
            payload["ref_images"] = ref_images

        # Optionale Parameter (bei 400 einzeln entfernbar). LocalAI nutzt "step".
        optional: Dict[str, Any] = {}
        if steps:
            optional["step"] = steps
        if negative_prompt:
            optional["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            optional["seed"] = seed
        payload.update(optional)

        logger.info(f"{self.name}: Starte Generierung (Modell {model}, {width}x{height}, "
                    f"{len(ref_images)} Ref-Bild(er))")
        try:
            resp = self._post_with_retry(payload, optional)
            data = resp.json()
            images: List[bytes] = []
            for item in data.get("data", []):
                b64 = item.get("b64_json", "")
                if b64:
                    images.append(base64.b64decode(b64))
                    continue
                url = item.get("url", "")
                if url:
                    img_resp = requests.get(url, timeout=60)
                    if img_resp.status_code == 200:
                        images.append(img_resp.content)
            if not images:
                logger.error(f"{self.name}: Keine Bilder in Response")
            return images
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []


class OpenAIDiffusionBackend(LocalAIBackend):
    """Strikt OpenAI-Images-Standard (POST {url}/v1/images/generations).

    Fuer Endpoints, die sich an den OpenAI-Standard halten — insbesondere das
    **LLM-Gateway** (OpenAI-kompatibler Reverse-Proxy vor ComfyUI). Unterschiede
    zum LocalAI-flavour (``LocalAIBackend``):
      - Parametername ``steps`` (nicht ``step``).
      - Generischer **Extra-Params-Block** (JSON): beliebige Zusatz-Keys
        (seed/steps/cfg/lora_01/...) werden 1:1 in den Request gemergt. Welche Namen
        gueltig sind, definiert der Alias-Workflow gateway-seitig — daher NICHT
        hartkodiert, sondern frei konfigurierbar.
      - ``response_format`` konfigurierbar (Default ``b64_json``).
      - **Bearer-Header auch beim Result-URL-Abruf** (Gateway-Result-URLs sind nicht
        oeffentlich, verlangen denselben Job-Owner-Token).
      - Fehler-Mapping nach OpenAI-/Gateway-Semantik: 400=Request-Fehler (kein Retry),
        401/403=Config, 402=Quota, 502=1x Retry, 503=Backoff-Retry, 429=Backoff.

    ``model`` ist hier ein **Generierungs-Alias** des Gateways, kein ComfyUI-Checkpoint.
    ``ref_images`` (rohes base64) bleibt geerbt — das Gateway akzeptiert es als Bonus.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, env_prefix, api_key=api_key, model=model)
        self.api_type = "openai_diffusion"
        rf = os.environ.get(f"{env_prefix}RESPONSE_FORMAT", "").strip().lower()
        self.response_format = rf if rf in ("b64_json", "url") else "b64_json"
        # Zweck-Kategorie (z.B. "inpaint") — steuert, ueber welchen Endpoint generiert
        # wird: "inpaint" -> POST /v1/images/edits (Canvas + Maske als zwei Bilder),
        # sonst /v1/images/generations. Markiert das Backend zudem als Inpaint-Ziel
        # fuer den Map-Fit/Edge-Dialog.
        self.category = os.environ.get(f"{env_prefix}CATEGORY", "").strip().lower()
        # Default-Prompt (z.B. Inpaint-Fill-Anweisung) — Fallback, wenn der Aufrufer
        # keinen Prompt liefert.
        self.default_prompt = os.environ.get(f"{env_prefix}PROMPT", "").strip()
        # Inpaint-Maskenparameter (nur bei category=inpaint). KEINE Modell-Sonderlogik —
        # alles frei konfigurierbar; der Map-Blend-Pfad (world.py) baut Canvas + Maske
        # rein aus diesen Werten. Die Maske wird IMMER mitgegeben.
        #   full_mask    True = ganze Flaeche maskieren, False = nur die Mitte/Zelle
        #   terrain_hint True = dynamische Terrain-Beschreibung an den Prompt anhaengen
        #   mask_grow    Maskenrand-Faktor (1.05 = +5%)
        #   inner_crop   Kern-Ausschnitt der Mitte (0.7 = innere 70%)
        def _flag(key: str, default: bool) -> bool:
            return os.environ.get(f"{env_prefix}{key}", str(default)).strip().lower() in ("true", "1", "yes")
        def _num(key: str, default: float) -> float:
            try:
                return float(os.environ.get(f"{env_prefix}{key}", "").strip() or default)
            except (TypeError, ValueError):
                return default
        self.full_mask = _flag("FULL_MASK", True)
        self.terrain_hint = _flag("TERRAIN_HINT", False)
        self.mask_grow = _num("MASK_GROW", 1.05)
        self.inner_crop = _num("INNER_CROP", 0.7)
        # Extra-Params: frei konfigurierbarer JSON-Block (loras/seed/steps/cfg/...).
        # Wird als zusaetzliche Top-Level-Keys in den Request gemergt.
        raw = os.environ.get(f"{env_prefix}EXTRA_PARAMS", "").strip()
        self.extra_params: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.extra_params = parsed
                else:
                    logger.warning(f"{name}: EXTRA_PARAMS ist kein JSON-Objekt, ignoriert")
            except (ValueError, TypeError) as e:
                logger.warning(f"{name}: EXTRA_PARAMS kein gueltiges JSON ({e}), ignoriert")

    def _post_gateway(self, endpoint: str, *, json: Optional[Dict[str, Any]] = None,
                      files: Optional[list] = None,
                      data: Optional[Dict[str, Any]] = None) -> requests.Response:
        """POST mit OpenAI-/Gateway-Fehler-Mapping (Spec §6). Blockiert synchron bis
        das Bild fertig ist (Gateway parkt unter Last selbst — kein eigenes Throttling).

        ``endpoint`` = "generations" (JSON) oder "edits" (multipart: ``files`` + ``data``).
        Bei multipart KEIN Content-Type setzen — requests fuegt die Boundary selbst an,
        daher nur der Bearer-Header (Spec: Auth auf jedem Request).
        """
        url = f"{self.api_url}/v1/images/{endpoint}"
        if json is not None:
            headers = self._headers()
        else:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        _429 = _502 = _503 = 0
        max_429, max_502, max_503 = 4, 1, 4
        while True:
            resp = requests.post(url, json=json, files=files, data=data,
                                 headers=headers, timeout=self.timeout)
            code = resp.status_code
            if code == 200:
                return resp
            body = (resp.text or "")[:300]
            if code == 429:
                if _429 >= max_429:
                    raise RuntimeError(f"{self.name}: HTTP 429 (Rate-Limit) nach {max_429} Versuchen")
                _429 += 1
                wait = self._rate_limit_wait(resp, _429)
                logger.warning(f"{self.name}: 429, warte {wait:.1f}s ({_429}/{max_429})")
                time.sleep(wait)
                continue
            if code == 503:  # kein gesundes Backend fuer den Alias — mit Backoff erneut
                if _503 >= max_503:
                    raise RuntimeError(f"{self.name}: HTTP 503 (kein Backend) nach {max_503} Versuchen: {body}")
                _503 += 1
                wait = min(2.0 * (2 ** (_503 - 1)), 30.0)
                logger.warning(f"{self.name}: 503 (kein gesundes Backend), warte {wait:.1f}s ({_503}/{max_503})")
                time.sleep(wait)
                continue
            if code == 502:  # Generierung fehlgeschlagen / Park-Timeout — 1x erneut
                if _502 >= max_502:
                    raise RuntimeError(f"{self.name}: HTTP 502 (Generierung fehlgeschlagen): {body}")
                _502 += 1
                logger.warning(f"{self.name}: 502, einmaliger Retry ({_502}/{max_502})")
                continue
            if code == 402:
                logger.error(f"{self.name}: HTTP 402 — Credit-/Quota-Limit erreicht: {body}")
                raise RuntimeError(f"{self.name}: Quota/Credit-Limit erreicht (HTTP 402): {body[:160]}")
            if code in (401, 403):
                logger.error(f"{self.name}: HTTP {code} — API-Key/Alias nicht erlaubt: {body}")
                raise RuntimeError(f"{self.name}: Auth/Alias-Fehler (HTTP {code}): {body[:160]}")
            if code == 400:
                logger.error(f"{self.name}: HTTP 400 — Request-Fehler (prompt/image fehlt?): {body}")
                raise RuntimeError(f"{self.name}: Request-Fehler (HTTP 400): {body[:160]}")
            logger.error(f"{self.name}: HTTP {code}: {body}")
            raise RuntimeError(f"{self.name}: HTTP {code}: {body[:160]}")

    def _apply_lora_params(self, payload: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Uebertraegt ausgewaehlte LoRAs dynamisch als ``lora_01``/``strength_01``,
        ``lora_02``/``strength_02`` … (ComfyUI-/Gateway-Konvention, vgl. Spec §2/§4).

        Quelle ist params['lora_inputs'] — vom Skill aufgeloest (Dialog-Auswahl aus
        der per-Welt LoRA-Library, endpoint-gefiltert). Anders als LocalAI KEINE
        ``<lora:>``-Prompt-Syntax: das Gateway/ComfyUI mappt die keyed Params auf den
        Lora-Loader-Node des Alias-Workflows. 'None'/leere Slots werden uebersprungen.
        """
        idx = 0
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
            idx += 1
            payload[f"lora_{idx:02d}"] = name
            payload[f"strength_{idx:02d}"] = strength
        if idx:
            logger.info(f"{self.name}: {idx} LoRA(s) dynamisch als lora_NN-Params uebertragen")

    def _is_inpaint(self, params: Dict[str, Any]) -> bool:
        """Inpaint, wenn das Backend so kategorisiert ist ODER eine Maske vorliegt."""
        refs = params.get("reference_images") or {}
        return self.category == "inpaint" or "input_mask" in refs

    def _collect_ref_bytes(self, params: Dict[str, Any]) -> List[tuple]:
        """Referenzbilder als geordnete (title, bytes)-Liste fuer den edits-Upload.

        Reihenfolge = Insertion-Order von params['reference_images']. Der Aufrufer
        unterscheidet anhand des Titels: 'input_mask' -> mask-Feld, alles andere ->
        image-Feld (Canvas/Referenzen).
        """
        out: List[tuple] = []
        for title, path in (params.get("reference_images") or {}).items():
            if not path:
                continue
            sp = str(path)
            try:
                if sp.startswith(("http://", "https://")):
                    r = requests.get(sp, timeout=30)
                    if r.status_code == 200:
                        out.append((title, r.content))
                elif sp.startswith("data:"):
                    out.append((title, base64.b64decode(sp.split(",", 1)[1] if "," in sp else sp)))
                else:
                    with open(sp, "rb") as f:
                        out.append((title, f.read()))
            except Exception as e:
                logger.warning(f"{self.name}: Referenzbild '{sp}' nicht lesbar: {e}")
        return out

    def _parse_image_response(self, resp: requests.Response) -> List[bytes]:
        """Gemeinsames Response-Parsing (b64_json | url) fuer generations + edits."""
        images: List[bytes] = []
        for item in resp.json().get("data", []):
            b64 = item.get("b64_json", "")
            if b64:
                images.append(base64.b64decode(b64))
                continue
            url = item.get("url", "")
            if url:
                # Result-URLs sind nicht oeffentlich — Bearer-Header mitschicken.
                img_resp = requests.get(url, headers=self._headers(), timeout=60)
                if img_resp.status_code == 200:
                    images.append(img_resp.content)
                else:
                    logger.error(f"{self.name}: Result-URL HTTP {img_resp.status_code}")
        if not images:
            logger.error(f"{self.name}: Keine Bilder in Response")
        return images

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        prompt = prompt or self.default_prompt
        if self._is_inpaint(params):
            return self._generate_edits(prompt, negative_prompt, params)

        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": self.response_format,
        }
        ref_images = self._collect_ref_images(params)
        if ref_images:
            payload["ref_images"] = ref_images
        # LoRAs dynamisch (lora_01/strength_01..) — KEINE <lora:>-Prompt-Syntax.
        self._apply_lora_params(payload, params)
        if steps:
            payload["steps"] = steps  # OpenAI-Standard: steps (nicht LocalAI "step")
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            payload["seed"] = seed
        # Frei konfigurierte Extra-Params (Alias-Workflow-spezifisch) zuletzt mergen —
        # sie duerfen die Defaults oben bewusst ueberschreiben.
        if self.extra_params:
            payload.update(self.extra_params)

        logger.info(f"{self.name}: Starte Generierung (Alias {model}, {width}x{height}, "
                    f"{len(ref_images)} Ref-Bild(er), rf={self.response_format})")
        try:
            resp = self._post_gateway("generations", json=payload)
            return self._parse_image_response(resp)
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []

    def _to_openai_mask(self, raw: bytes) -> bytes:
        """Graustufen-Inpaint-Maske (weiss = zu fuellen, ComfyUI-Konvention) ->
        OpenAI-Edits-Standard: RGBA-PNG, wo editiert wird ist alpha=0 (transparent).
        Bei Fehler die Rohbytes unveraendert (degradiert, statt zu crashen)."""
        try:
            from PIL import Image, ImageOps
            import io as _io
            m = Image.open(_io.BytesIO(raw)).convert("L")
            rgba = Image.new("RGBA", m.size, (255, 255, 255, 255))
            rgba.putalpha(ImageOps.invert(m))  # weiss(255) -> alpha 0 (transparent = edit)
            buf = _io.BytesIO()
            rgba.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"{self.name}: Masken-Konvertierung fehlgeschlagen ({e}), sende roh")
            return raw

    def _generate_edits(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Inpaint/img2img ueber POST /v1/images/edits (multipart).

        Das Gateway mappt ``image`` -> ``inputs.init_image`` und ``mask`` -> ``inputs.mask``
        (Gateway-Plan: "image+mask -> inputs.init_image/mask"). Daher geht der Canvas
        ins ``image``-Feld und die Inpaint-Maske ins **dedizierte** ``mask``-Feld —
        NICHT als zweites ``image``, sonst greift keine Latent-Noise-Mask und das
        ganze Bild wird neu gerechnet (nur der maskierte Bereich soll sich aendern).
        Der Gateway gibt den vollen (inpainteten) Canvas zurueck — den Mitte-Crop macht
        der Aufrufer (world.py) selbst.
        """
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        ref_bytes = self._collect_ref_bytes(params)
        if not ref_bytes:
            logger.error(f"{self.name}: Inpaint ohne Eingangsbild/Maske — abgebrochen")
            return []
        # Canvas/Referenzen -> image, input_mask -> mask. Maske ans Ende (Feldname
        # entscheidet die Zuordnung, nicht die Position). Die Inpaint-Maske wird auf
        # den OpenAI-Edits-Standard konvertiert: RGBA, transparent = zu editieren.
        files: list = []
        mask_part = None
        for title, raw in ref_bytes:
            if "mask" in title.lower():
                mask_part = ("mask", (f"{title}.png", self._to_openai_mask(raw), "image/png"))
            else:
                files.append(("image", (f"{title}.png", raw, "image/png")))
        if mask_part:
            files.append(mask_part)

        # Form-Felder: alle Werte als String (multipart). Extra-Params + LoRAs zuletzt.
        data: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": self.response_format,
        }
        steps = params.get("num_inference_steps") or self.num_inference_steps
        if steps:
            data["steps"] = steps
        if negative_prompt:
            data["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            data["seed"] = seed
        self._apply_lora_params(data, params)
        if self.extra_params:
            data.update(self.extra_params)
        data = {k: str(v) for k, v in data.items()}

        _img_n = sum(1 for f, _ in files if f == "image")
        logger.info(f"{self.name}: Starte Inpaint/edits (Alias {model}, {width}x{height}, "
                    f"{_img_n} image + {'1 mask' if mask_part else 'KEINE mask'})")
        try:
            resp = self._post_gateway("edits", files=files, data=data)
            return self._parse_image_response(resp)
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []


# Registry der verfuegbaren Backend-Typen
BACKEND_REGISTRY = {
    "a1111": A1111Backend,
    "openai_chat": OpenAIChatImageBackend,
    "comfyui": ComfyUIBackend,
    "civitai": CivitAIBackend,
    "together": TogetherBackend,
    "localai": LocalAIBackend,
    "openai_diffusion": OpenAIDiffusionBackend,
}
