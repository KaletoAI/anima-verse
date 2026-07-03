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


class ImageBackend(ABC):
    """
    Basisklasse fuer Image Generation Backends.

    Jedes Backend implementiert ein spezifisches API-Protokoll
    (z.B. A1111/Forge, Mammouth/OpenAI-kompatibel).
    """

    # Throttle for "unreachable" warnings — avoid log spam for permanently
    # offline backends. First time WARNING, then reduced to DEBUG for
    # _UNREACHABLE_THROTTLE_SEC seconds. Recovery (avail True after False)
    # is logged as INFO.
    _UNREACHABLE_THROTTLE_SEC = 300

    # How many reference-image slots (params['reference_images']) this backend
    # type can consume. 0 = backend takes no reference images. Overridable per
    # instance via {env_prefix}REF_SLOT_COUNT (config field ref_slot_count).
    DEFAULT_REF_SLOT_COUNT = 0

    def __init__(self, name: str, api_url: str, cost: float, api_type: str, env_prefix: str):
        self.name = name
        self.api_url = api_url.rstrip("/")
        self.cost = cost
        self.api_type = api_type
        self.env_prefix = env_prefix
        self._available = False
        # Cooldown nach Fehler: haelt available temporaer hart auf False, auch
        # wenn check_availability den (erreichbaren) Endpoint wieder mit 200
        # sieht. So wird ein Gateway, das zwar online ist aber das Modell gerade
        # nicht liefern kann (z.B. 503 "No healthy backend"), nicht bei jeder
        # Generierung neu probiert — die Match-Auswahl ueberspringt es bis der
        # Cooldown ablaeuft (spiegelt provider.mark_unhealthy der LLM-Seite).
        self._cooldown_until: float = 0.0
        self._cooldown_reason: str = ""
        self._active_jobs = 0
        self._jobs_lock = __import__("threading").Lock()
        # Letzter Zeitpunkt an dem wir "nicht erreichbar" als WARNING geloggt haben
        self._last_unreachable_warn_ts: float = 0.0
        # Vorheriger Verfuegbarkeitsstatus — Uebergang False->True triggert "wieder da"
        self._was_available: Optional[bool] = None

        # Instanz-Enabled aus .env (globaler Default)
        self.instance_enabled = os.environ.get(f"{env_prefix}ENABLED", "true").strip().lower() in ("true", "1", "yes")

        # Image family (natural/keywords) — how the model wants its prompts.
        # Style/negative belong to the use cases, not to the backend.
        self.image_family = os.environ.get(f"{env_prefix}IMAGE_FAMILY", "").strip()

        # Reference-image slot budget (see DEFAULT_REF_SLOT_COUNT).
        _slots_str = os.environ.get(f"{env_prefix}REF_SLOT_COUNT", "").strip()
        try:
            self.ref_slot_count = int(_slots_str) if _slots_str else self.DEFAULT_REF_SLOT_COUNT
        except ValueError:
            self.ref_slot_count = self.DEFAULT_REF_SLOT_COUNT

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
        # Serialize group (metadata only — the channel setup in
        # provider_manager reads the same env directly): channels with the
        # same group share one Semaphore(1), e.g. an LLM provider and this
        # backend on one physical GPU.
        self.serialize_group = os.environ.get(f"{env_prefix}SERIALIZE_GROUP", "").strip()

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

    @property
    def available(self) -> bool:
        """Verfuegbar fuer die Backend-Auswahl. Waehrend eines Cooldowns hart
        False — unabhaengig davon, was die letzte Erreichbarkeits-Pruefung
        gesetzt hat (siehe mark_unhealthy)."""
        if self._cooldown_active():
            return False
        return self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = bool(value)

    def _cooldown_active(self) -> bool:
        if not self._cooldown_until:
            return False
        if time.monotonic() < self._cooldown_until:
            return True
        # Abgelaufen — zuruecksetzen, naechste check_availability darf neu proben.
        self._cooldown_until = 0.0
        self._cooldown_reason = ""
        return False

    def mark_unhealthy(self, reason: str = "", cooldown_seconds: float = 300.0) -> None:
        """Setzt das Backend nach einem Fehler in Cooldown.

        Anders als ``available = False`` ueberlebt das die naechste
        ``check_availability``-Probe: solange der Cooldown laeuft liefert die
        ``available``-Property False, sodass die Match-Auswahl dieses Backend
        ueberspringt und ein anderes nimmt. Nach Ablauf wird wieder normal
        geprobt (Retry).
        """
        self._available = False
        self._was_available = False
        self._cooldown_until = time.monotonic() + max(0.0, cooldown_seconds)
        self._cooldown_reason = reason or "unhealthy"
        logger.warning("Backend %s in Cooldown fuer %ds: %s",
                       self.name, int(cooldown_seconds), reason)

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

    # Reference-image conditioning: agent + room + others/items (see
    # _collect_ref_images). OpenAIDiffusionBackend inherits this budget.
    DEFAULT_REF_SLOT_COUNT = 4

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, env_prefix, api_key=api_key, model=model)
        self.api_type = "localai"
        # Optionaler Endpoint, um die fuer dieses Modell verfuegbaren LoRAs abzufragen
        # (analog ComfyUI). Leer = keine Abfrage. ``{alias}`` wird durch den Modellnamen
        # ersetzt; ohne Platzhalter wird ``/v1/generations/{model}/loras`` angehaengt.
        self.lora_url = os.environ.get(f"{env_prefix}LORA_URL", "").strip()
        self.available_loras: List[str] = []

    def _lora_query_url(self) -> str:
        """Baut die LoRA-Abfrage-URL aus lora_url + Modellname (Alias)."""
        model = (self.model or "").strip()
        if "{alias}" in self.lora_url:
            return self.lora_url.replace("{alias}", model)
        return f"{self.lora_url.rstrip('/')}/v1/generations/{model}/loras"

    def fetch_loras(self) -> List[str]:
        """Holt die verfuegbaren LoRAs vom lora_url-Endpoint (GET -> {"loras": [...]}).
        Setzt + liefert self.available_loras. Leere/fehlerhafte Antwort -> []."""
        if not self.lora_url or not self.model:
            return self.available_loras
        try:
            resp = requests.get(self._lora_query_url(), headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                body = resp.json()
                loras = body.get("loras") if isinstance(body, dict) else body
                if isinstance(loras, list):
                    self.available_loras = [str(l).strip() for l in loras if l and str(l).strip()]
                    logger.info(f"{self.name}: {len(self.available_loras)} LoRA(s) vom Endpoint geladen")
            else:
                logger.warning(f"{self.name}: LoRA-Abfrage HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"{self.name}: LoRA-Abfrage fehlgeschlagen: {e}")
        return self.available_loras

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
                # LoRAs (falls Endpoint konfiguriert) gleich mitziehen.
                if self.lora_url:
                    self.fetch_loras()
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
        # Masken-Format fuer den edits-Upload (nur category=inpaint):
        #   grayscale = L-PNG 1:1 wie erzeugt (Weiss=Edit) — fuer Gateways, die die
        #               Maske direkt an ComfyUIs ``inputs.mask`` reichen (Weiss=Edit).
        #               Der Draht ist dann byte-identisch zu mapblend_debug/last_mask.png.
        #   openai    = OpenAI-Edits-Standard (RGBA, transparent=Edit) fuer echte
        #               OpenAI-/DALL-E-Edits-Endpoints.
        _mf = os.environ.get(f"{env_prefix}MASK_FORMAT", "grayscale").strip().lower()
        self.mask_format = _mf if _mf in ("grayscale", "openai") else "grayscale"
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
        # entscheidet die Zuordnung, nicht die Position). Polaritaet je nach
        # ``mask_format``: 'grayscale' sendet die L-Maske (Weiss=Edit) 1:1 wie erzeugt
        # (== mapblend_debug), 'openai' invertiert auf den OpenAI-Edits-Standard
        # (RGBA, transparent = zu editieren).
        files: list = []
        mask_part = None
        for title, raw in ref_bytes:
            if "mask" in title.lower():
                _mbytes = self._to_openai_mask(raw) if self.mask_format == "openai" else raw
                mask_part = ("mask", (f"{title}.png", _mbytes, "image/png"))
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
        _mask_info = f"1 mask [{self.mask_format}]" if mask_part else "KEINE mask"
        logger.info(f"{self.name}: Starte Inpaint/edits (Alias {model}, {width}x{height}, "
                    f"{_img_n} image + {_mask_info})")
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


# Registry of available backend types
BACKEND_REGISTRY = {
    "a1111": A1111Backend,
    "openai_chat": OpenAIChatImageBackend,
    "civitai": CivitAIBackend,
    "together": TogetherBackend,
    "localai": LocalAIBackend,
    "openai_diffusion": OpenAIDiffusionBackend,
}
