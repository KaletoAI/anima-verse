"""Image Generation Skill - Multi-Instance Dispatcher mit Kosten-basierter Auswahl"""
import base64
import json
import os
import re
import time
import uuid
from datetime import datetime

from app.core.timeutils import utc_now_iso
from typing import Any, Dict, List, Optional


import requests

from app.imagegen import ImageBackend, BACKEND_REGISTRY
from app.imagegen.selection import BackendPool, _BACKEND_COOLDOWN_SECONDS

from app.core.log import get_logger
from app.core.task_queue import get_task_queue
from app.models.character import (
    get_character_images_dir,
    add_character_image,
    add_character_image_comment,
    add_character_image_prompt,
    set_character_profile_image,
    get_character_profile_image,
    get_character_profile,
    get_character_config,
    get_character_skill_config,
    save_character_skill_config,
    get_character_current_location,
    get_effective_activity,
    get_character_current_feeling,
    get_character_current_room)
from app.core.outfit_renderer import render_outfit, collect_covered_slots
from app.models.account import (
    get_user_profile,
    get_user_gender,
    get_user_profile_image,
    get_user_images_dir)
from app.models.world import get_background_path
from app.utils.image_prompt_logger import log_image_prompt

logger = get_logger("image_gen")


def _log_image_failure(lv: dict, error_msg: str) -> None:
    """Schreibt eine fehlgeschlagene Bildgenerierung ins Image-Log (Errors-only
    im Viewer sichtbar). ``lv`` = locals() der Aufrufstelle — Variablen werden
    defensiv via .get() gelesen, da je nach Abbruchstelle nicht alle gesetzt sind."""
    try:
        _bk = lv.get("backend")
        log_image_prompt(
            agent_name=lv.get("character_name") or "",
            original_prompt=lv.get("prompt_text") or "",
            final_prompt=lv.get("enhanced_prompt") or "",
            negative_prompt=lv.get("negative_prompt") or "",
            backend_name=getattr(_bk, "name", "") or "",
            backend_type=getattr(_bk, "api_type", "") or "",
            error=error_msg)
    except Exception as _le:
        logger.debug("Fehler-Logging (Image) fehlgeschlagen: %s", _le)


class ImageService:
    """Multi-instance image generation SERVICE (core engine, R5).

    Owns the backend pool (A1111/Forge, OpenAI-compatible, ...), instance
    selection and the full generation pipeline. Split out of the former
    ImageGenerationSkill (wave 6): every consumer (scene photo, outfits,
    profile images, instagram, video, events, regenerate) talks to this
    service via ``get_image_service()`` — the TakePhoto VERB in
    plugins/take_photo is just the LLM tool surface on top.

    Configuration:
        Numbered instance blocks SKILL_IMAGEGEN_{N}_* (env bridge)
        Per character: skills/image_generation.json (SKILL_ID kept as the
        per-character config key)
    """

    SKILL_ID = "image_generation"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))

        # Last used enhanced_prompt (for callers like Instagram)
        self.last_enhanced_prompt: str = ""

        # Thread-lokaler Slot fuer last_image_meta — notwendig damit parallele
        # Aufrufer (z.B. Expression-Regen fuer mehrere Characters gleichzeitig)
        # nicht die Meta-Daten des anderen ueberschreiben. Die instance-Variante
        # self.last_image_meta bleibt als Backward-Compat bestehen.
        import threading as _th
        self._meta_tls = _th.local()

        # Load all configured instances and build the backend pool.
        # Round-robin state + all selection logic live in BackendPool now.
        backends = self._load_instances()
        self._pool = BackendPool(
            backends, agent_instances_provider=self._agent_instances)

        if not self.backends:
            logger.warning("Keine Image-Generation Instanzen konfiguriert")
            self.enabled = False
            return

        # Pruefe Verfuegbarkeit aller enabled Instanzen
        available_count = 0
        enabled_backends = [b for b in self.backends if b.instance_enabled]
        logger.info("Pruefe %d von %d Instanz(en)...", len(enabled_backends), len(self.backends))
        for backend in enabled_backends:
            if backend.check_availability():
                available_count += 1

        if available_count == 0:
            logger.warning("Keine Instanz verfuegbar")
            self.enabled = False
        else:
            logger.info("%d/%d Instanz(en) verfuegbar", available_count, len(self.backends))

        # ImageGen nutzt ein eigenes per-Instanz Config-System (_get_instance_config)
        # statt der generischen BaseSkill._defaults. Daher keine _defaults fuer
        # get_config_fields() — die Konfiguration geschieht ueber die instanzbasierte
        # Config in storage/users/{user}/characters/{char}/skills/imagegen.json
        self._defaults = {}

    @property
    def backends(self) -> List[ImageBackend]:
        """Backends live in the pool now; exposed as a property for the many
        external readers (``img.backends``) and internal skill helpers."""
        return self._pool.backends

    def _agent_instances(self, name: str) -> Dict[str, Any]:
        """Provider injected into ``BackendPool``: returns the per-agent
        instances dict, auto-creating the per-agent config on first access."""
        return self._ensure_agent_config(name).get("instances", {})

    def get_config_fields(self) -> Dict[str, Dict[str, Any]]:
        """Top-level Config-Felder fuer den Character-Editor.

        Post-Processing laeuft extern (Pull-Modell), daher hier keine Felder.
        """
        return {}

    def _load_instances(self) -> List[ImageBackend]:
        """Scannt .env nach SKILL_IMAGEGEN_{N}_* Bloecken und erstellt Backends."""
        instances = []

        for n in range(1, 20):
            prefix = f"SKILL_IMAGEGEN_{n}_"
            api_type = os.environ.get(f"{prefix}API_TYPE", "").strip().lower()
            if not api_type:
                continue

            name = os.environ.get(f"{prefix}NAME", f"Instance_{n}")
            api_url = os.environ.get(f"{prefix}API_URL", "").strip()
            cost = float(os.environ.get(f"{prefix}COST", "0"))

            if not api_url:
                logger.warning("Instanz %d (%s): Keine API_URL konfiguriert, ueberspringe", n, name)
                continue

            backend_class = BACKEND_REGISTRY.get(api_type)
            if not backend_class:
                logger.warning("Instanz %d (%s): Unbekannter API-Typ '%s'", n, name, api_type)
                logger.info("Verfuegbare Typen: %s", ", ".join(BACKEND_REGISTRY.keys()))
                continue

            try:
                if api_type in ("openai_chat", "civitai"):
                    api_key = os.environ.get(f"{prefix}API_KEY", "")
                    model = os.environ.get(f"{prefix}MODEL", "")
                    backend = backend_class(
                        name=name, api_url=api_url, cost=cost,
                        env_prefix=prefix, api_key=api_key, model=model
                    )
                else:
                    backend = backend_class(
                        name=name, api_url=api_url, cost=cost, env_prefix=prefix
                    )

                instances.append(backend)
                enabled_str = "enabled" if backend.instance_enabled else "DISABLED"
                logger.info("Instanz geladen: %s (Typ=%s, Cost=%s, %s)", name, api_type, cost, enabled_str)

            except Exception as e:
                logger.error("Fehler beim Laden von Instanz %d (%s): %s", n, name, e)

        return instances

    # ------------------------------------------------------------------
    # BackendPool facade — thin delegators to self._pool (public API)
    # ------------------------------------------------------------------

    def pick_lowest_cost(self, candidates: List[ImageBackend],
                         rotation_key: str = "default") -> Optional[ImageBackend]:
        return self._pool.pick_lowest_cost(candidates, rotation_key)

    def _select_backend(self) -> Optional[ImageBackend]:
        return self._pool._select_backend()

    def _ensure_agent_config(self, character_name: str) -> Dict[str, Any]:
        """Erstellt automatisch eine per-Agent Skill-Config mit .env-Defaults, falls noch keine existiert."""
        agent_config = get_character_skill_config(character_name, self.SKILL_ID)

        if agent_config and "instances" in agent_config:
            # Config existiert - pruefen ob neue Backends fehlen
            changed = False
            existing_names = set(agent_config["instances"].keys())
            backend_names = {b.name for b in self.backends}
            missing = backend_names - existing_names
            if missing:
                for b in self.backends:
                    if b.name in missing:
                        agent_config["instances"][b.name] = self._get_backend_defaults(b)
                        logger.info("Auto-Config: Backend '%s' fuer %s hinzugefuegt", b.name, character_name)
                changed = True
            if changed:
                save_character_skill_config(character_name, self.SKILL_ID, agent_config)
            return agent_config

        # Keine Config vorhanden - erstelle mit Defaults aller Backends
        agent_config = {
            "instances": {}
        }
        for b in self.backends:
            agent_config["instances"][b.name] = self._get_backend_defaults(b)

        save_character_skill_config(character_name, self.SKILL_ID, agent_config)
        logger.info("Auto-Config fuer %s erstellt: %s", character_name, list(agent_config["instances"].keys()))
        return agent_config

    def _select_backend_for_agent(self, character_name: str) -> Optional[ImageBackend]:
        return self._pool._select_backend_for_agent(character_name)

    def resolve_imagegen_target(self, spec: str,
                                preferred_backend: str = "",
                                media: str = "image"
                                ) -> Optional[ImageBackend]:
        return self._pool.resolve_imagegen_target(spec, preferred_backend, media)

    def match_backend(self, pattern: str, media: str = "image") -> Optional[ImageBackend]:
        return self._pool.match_backend(pattern, media=media)

    def list_available_backends(self, character_name: str = "",
                                media: str = "image") -> List[ImageBackend]:
        return self._pool.list_available_backends(character_name, media=media)

    def run_with_fallback(self, primary_backend, op, character_name="",
                          max_attempts=3):
        return self._pool.run_with_fallback(
            primary_backend, op, character_name, max_attempts)

    def _wait_for_backend(self, character_name):
        return self._pool._wait_for_backend(character_name)

    def _wait_for_explicit_backend(self, backend_name, media: str = "image"):
        return self._pool._wait_for_explicit_backend(backend_name, media=media)

    def generate_video(self, source_image_path: str, action_prompt: str,
                       output_path: str, backend_glob: str = "",
                       character_name: str = "") -> bool:
        """Renders a video from a still via a MEDIA_TYPE=="video" backend.

        Picks a video backend by glob (empty = cheapest available video
        backend), runs it through the pool's fallback engine, and writes the
        returned MP4 to ``output_path``. Returns True on success.
        """
        params: Dict[str, Any] = {"source_image_path": source_image_path,
                                  "reference_images": {"frame": source_image_path}}
        if backend_glob.strip():
            primary = self._wait_for_explicit_backend(backend_glob, media="video")
        else:
            vids = self.list_available_backends(character_name, media="video")
            primary = vids[0] if vids else None
        if not primary:
            logger.warning("generate_video: kein Video-Backend verfuegbar (glob=%r)",
                           backend_glob)
            return False

        def _op(backend: ImageBackend):
            return backend.generate(action_prompt, "", params,
                                    log_meta={"agent_name": character_name,
                                              "original_prompt": action_prompt,
                                              "media": "video"})
        try:
            result, _used = self.run_with_fallback(
                primary, _op, character_name=character_name)
        except Exception as e:
            logger.error("generate_video fehlgeschlagen: %s", e)
            return False
        if not result:
            return False
        try:
            from pathlib import Path as _P
            _P(output_path).parent.mkdir(parents=True, exist_ok=True)
            _P(output_path).write_bytes(result[0])
            return True
        except Exception as e:
            logger.error("generate_video: Schreiben fehlgeschlagen: %s", e)
            return False

    def _get_backend_defaults(self, backend: ImageBackend) -> Dict[str, Any]:
        """Holt die Instanz-spezifischen Defaults (nur agent-level Overrides).

        Technische Backend-Parameter (guidance_scale, num_inference_steps, checkpoint,
        sampling_method, schedule_type, sampler, scheduler) kommen direkt vom Backend/.env
        und werden NICHT in die per-Agent Config geschrieben.
        """
        defaults = {
            "enabled": backend.instance_enabled,
        }
        if hasattr(backend, 'width'):
            defaults["width"] = backend.width
        if hasattr(backend, 'height'):
            defaults["height"] = backend.height
        # workflow_file ist ein technischer Backend-Parameter und wird
        # NICHT in die per-Agent Config geschrieben (kommt direkt vom Backend/.env)
        return defaults

    def _get_instance_config(self, character_name: str, backend: ImageBackend) -> Dict[str, Any]:
        """
        Laedt per-Agent per-Instanz Config.

        JSON-Format:
        {
            "instances": {
                "LocalSD": {"prompt_prefix": "...", "negative_prompt": "...", ...},
                "NanoBanana": {"prompt_prefix": "", ...}
            }
        }

        Merge-Logik: Agent-Instance-Override > Backend .env Default > leer
        """
        backend_defaults = self._get_backend_defaults(backend)

        if not character_name or not self.SKILL_ID:
            return backend_defaults

        agent_config = get_character_skill_config(character_name, self.SKILL_ID)

        # Migration: Falls altes flaches Format, konvertiere zu per-Instanz
        if agent_config and "instances" not in agent_config:
            logger.info("Migriere %s Config zu per-Instanz Format...", character_name)
            agent_config = self._migrate_flat_config(agent_config)
            save_character_skill_config(character_name, self.SKILL_ID, agent_config)
            logger.info("Migration abgeschlossen")

        if agent_config and "instances" in agent_config:
            migrated = False
            # Backend-Defaults fuer Vergleich laden (Name → Defaults)
            backend_defaults_map = {b.name: self._get_backend_defaults(b) for b in self.backends}
            for inst_name, inst_cfg in agent_config["instances"].items():
                # workflow_file ist technischer Backend-Param, gehoert nicht in per-Agent Config
                if "workflow_file" in inst_cfg:
                    del inst_cfg["workflow_file"]
                    migrated = True
                # Werte entfernen die dem Backend-Default (.env) entsprechen
                defaults = backend_defaults_map.get(inst_name, {})
                for key in list(inst_cfg.keys()):
                    if key in defaults and inst_cfg[key] == defaults[key]:
                        del inst_cfg[key]
                        migrated = True
            if migrated:
                save_character_skill_config(character_name, self.SKILL_ID, agent_config)
                logger.info("Config bereinigt fuer %s (nur Overrides gespeichert)", character_name)

            instance_overrides = agent_config["instances"].get(backend.name, {})
            if instance_overrides:
                # Merge: Override > Backend-Default
                result = dict(backend_defaults)
                for key, default_val in result.items():
                    if key in instance_overrides:
                        val = instance_overrides[key]
                        # bool VOR int pruefen (bool ist Subklasse von int)
                        if isinstance(default_val, bool):
                            result[key] = bool(val)
                        elif isinstance(default_val, float):
                            result[key] = float(val)
                        elif isinstance(default_val, int):
                            result[key] = int(val)
                        else:
                            result[key] = str(val).strip()
                return result
        else:
            # Erstelle per-Agent Config mit allen Instanzen beim ersten Aufruf
            new_config = self._build_initial_config()
            save_character_skill_config(character_name, self.SKILL_ID, new_config)
            logger.info("Per-Agent Config erstellt fuer %s: %s.json", character_name, self.SKILL_ID)

        return backend_defaults

    def _build_initial_config(self) -> Dict[str, Any]:
        """Erstellt initiale per-Agent Config mit allen Backend-Instanzen.

        Speichert nur leere Dicts pro Instanz — Defaults kommen aus .env/Backend.
        Nur echte Overrides (die vom Default abweichen) sollen hier gespeichert werden.
        """
        instances = {}
        for backend in self.backends:
            instances[backend.name] = {}
        config: Dict[str, Any] = {"instances": instances}
        return config

    def _migrate_flat_config(self, old_config: Dict[str, Any]) -> Dict[str, Any]:
        """Migriert altes flaches Format zu per-Instanz Format."""
        instances = {}
        for backend in self.backends:
            backend_defaults = self._get_backend_defaults(backend)
            instance_cfg = {}
            for key, default_val in backend_defaults.items():
                if key in old_config:
                    instance_cfg[key] = old_config[key]
                else:
                    instance_cfg[key] = default_val
            instances[backend.name] = instance_cfg
        return {"instances": instances}

    @staticmethod
    def _detect_media_extension(data: bytes) -> str:
        """Erkennt den Medien-Typ anhand der Magic Bytes."""
        if len(data) >= 12:
            if data[:4] == b'\x89PNG':
                return '.png'
            if data[:3] == b'\xff\xd8\xff':
                return '.jpg'
            if data[:4] == b'GIF8':
                return '.gif'
            if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                return '.webp'
            if data[4:8] == b'ftyp':
                return '.mp4'
        return '.png'

    def _get_vision_llm_config(self, character_name: str) -> Dict[str, Any]:
        """Loads Vision LLM config via Router (Task: image_recognition)."""
        from app.core.llm_router import resolve_llm
        instance = resolve_llm("image_recognition", agent_name=character_name)
        if instance:
            return {
                "model": instance.model,
                "api_base": instance.api_base,
                "api_key": instance.api_key,
                "temperature": instance.temperature,
                "max_tokens": instance.max_tokens,
            }
        logger.warning("No LLM available for task=image_recognition (check LLM Routing)")
        return None

    def _generate_image_analysis(self, image_path: str, character_name: str) -> Optional[str]:
        """Objektive Bildanalyse via Vision-LLM - sachliche Beschreibung des Bildinhalts."""
        from app.core.llm_client import LLMClient

        if not os.path.exists(image_path):
            return None

        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            logger.error("Fehler beim Laden des Bildes fuer Analyse: %s", e)
            return None

        prompt_text = os.environ.get("IMAGE_ANALYSIS_PROMPT", "").strip() or (
            "Describe this image in detail. Include:\n"
            "- People: appearance, clothing, pose, expression\n"
            "- Setting: location, environment, lighting\n"
            "- Objects and activities visible\n"
            "- Overall mood and atmosphere\n\n"
            "Be factual and objective. Respond ONLY with the description, "
            "no formatting, no markdown, no quotes. 2-4 sentences."
        )

        # Language from env (default: German)
        analysis_lang = os.environ.get("IMAGE_ANALYSIS_LANGUAGE", "de").strip()
        lang_name = "German" if analysis_lang == "de" else "English"

        try:
            vcfg = self._get_vision_llm_config(character_name)
            if not vcfg:
                return None

            llm = LLMClient(
                model=vcfg["model"],
                api_key=vcfg["api_key"],
                api_base=vcfg["api_base"],
                temperature=0.3,
                max_tokens=500,
                request_timeout=int(os.environ.get("LLM_REQUEST_TIMEOUT", "120")))

            image_url = f"data:image/png;base64,{base64_image}"
            messages = [
                {"role": "system", "content": f"You MUST answer in {lang_name}. This is mandatory."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]},
            ]

            from app.core.llm_queue import get_llm_queue, Priority
            response = get_llm_queue().submit(
                task_type="image_analysis",
                priority=Priority.NORMAL,
                llm=llm,
                messages_or_prompt=messages,
                agent_name=character_name)
            analysis = response.content.strip()
            if analysis.startswith('"') and analysis.endswith('"'):
                analysis = analysis[1:-1]
            if analysis.startswith("'") and analysis.endswith("'"):
                analysis = analysis[1:-1]
            return analysis
        except Exception as e:
            logger.error("Objektive Bildanalyse fehlgeschlagen: %s", e)
            return None

    def describe_map_tile(self, image_path: str) -> Optional[str]:
        """Kurze Terrain-Phrase eines 2D-Karten-Tiles via Vision-LLM (Task
        image_recognition). Fuer Fit/Edge-Prompts, damit north/south/east/west das
        TATSAECHLICHE Tile beschreiben (nicht die evtl. veraltete Textbeschreibung).
        Englisch, 3-8 Woerter, nur die Phrase. ``None`` bei Fehler/Vision aus."""
        from app.core.llm_client import LLMClient
        if not os.path.exists(image_path):
            return None
        try:
            with open(image_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            vcfg = self._get_vision_llm_config("")
            if not vcfg:
                return None
            llm = LLMClient(
                model=vcfg["model"], api_key=vcfg["api_key"], api_base=vcfg["api_base"],
                temperature=0.2, max_tokens=40,
                request_timeout=int(os.environ.get("LLM_REQUEST_TIMEOUT", "120")))
            prompt_text = (
                "This is a top-down 2D map tile. Describe its terrain in a short "
                "English phrase of 3-8 words (e.g. 'dense dark green pine forest', "
                "'rocky coastline with open water', 'grassy plain with a dirt road'). "
                "Only the terrain phrase — no sentence, no punctuation, no quotes.")
            messages = [
                {"role": "user", "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]},
            ]
            from app.core.llm_queue import get_llm_queue, Priority
            response = get_llm_queue().submit(
                task_type="image_recognition", priority=Priority.NORMAL,
                llm=llm, messages_or_prompt=messages, agent_name="")
            term = " ".join((response.content or "").split()).strip().strip('"\'.,;')
            return term or None
        except Exception as e:
            logger.warning("Map-Tile-Analyse fehlgeschlagen: %s", e)
            return None

    def _generate_comment(self, character_name: str, rp_context: str = "",
                          photographer_subjects: Optional[List[str]] = None) -> Optional[str]:
        """Erzeugt eine kurze Situations-Beschreibung als Galerie-Caption.

        Beschreibt, welche Situation zum Foto gefuehrt hat (aus dem RP-Kontext),
        statt einer emotionalen Reaktion auf das Bild.

        Args:
            rp_context: Die Chat-Antwort, die das Bild ausgeloest hat.
            photographer_subjects: Liste der abgebildeten Personen (nur in Photographer mode).
        """
        if not rp_context or len(rp_context.strip()) < 15:
            logger.debug("Kein RP-Kontext fuer Situations-Kommentar vorhanden")
            return None

        # Aktions-Teile extrahieren (Text zwischen *...*), Dialog verwerfen
        action_chunks = re.findall(r'\*([^*]+)\*', rp_context)
        if action_chunks:
            clean = " ".join(action_chunks)
        else:
            clean = rp_context
        # Meta-Text und Markdown entfernen
        clean = re.sub(r'"[^"]*"', '', clean)
        clean = re.sub(r'\([^)]*\)', '', clean)
        clean = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()

        if not clean or len(clean) < 15:
            return None

        try:
            from app.core.llm_client import LLMClient
            from app.core.llm_queue import get_llm_queue, Priority

            vcfg = self._get_vision_llm_config(character_name)
            if not vcfg:
                # Fallback: gekuerzten Rohtext verwenden
                return clean[:200]

            llm = LLMClient(
                model=vcfg["model"],
                api_key=vcfg["api_key"],
                api_base=vcfg["api_base"],
                temperature=0.5,
                max_tokens=100,
                request_timeout=30)

            if photographer_subjects:
                subject_names = ", ".join(photographer_subjects)
                who = f"{character_name} hat ein Foto von {subject_names} gemacht."
            else:
                who = f"Ein Foto von {character_name} ist entstanden."

            system = (
                "Fasse die Situation, die zu einem Foto gefuehrt hat, in 1 kurzen Satz zusammen "
                "(maximal 150 Zeichen, deutsch). "
                "Beschreibe WAS passiert ist und WARUM das Foto entstanden ist. "
                "Schreibe in der dritten Person. "
                "Antworte NUR mit dem Satz. Keine Anfuehrungszeichen, kein Markdown."
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": f"{who}\n\nKontext:\n{clean[:500]}"},
            ]

            response = get_llm_queue().submit(
                task_type="image_comment",
                priority=Priority.NORMAL,
                llm=llm,
                messages_or_prompt=messages,
                agent_name=character_name)
            comment = response.content.strip()

            if comment.startswith('"') and comment.endswith('"'):
                comment = comment[1:-1]
            if comment.startswith("'") and comment.endswith("'"):
                comment = comment[1:-1]

            # Zeichenbegrenzung: max 200 Zeichen, am letzten Satzende abschneiden
            if len(comment) > 200:
                truncated = comment[:200]
                for sep in ['. ', '! ', '? ']:
                    idx = truncated.rfind(sep)
                    if idx > 50:
                        truncated = truncated[:idx + 1]
                        break
                comment = truncated

            logger.info("Situations-Kommentar generiert: %s", comment[:200])
            return comment
        except Exception as e:
            logger.error("Situations-Kommentar fehlgeschlagen: %s", e)
            logger.debug("Traceback:", exc_info=True)
            # Fallback: gekuerzten Rohtext verwenden
            return clean[:200] if clean else None

    # _detect_mentioned_appearances() wurde durch PromptBuilder.detect_persons() ersetzt.

    def _extract_rp_scene_context(
        self, rp_text: str, character_name: str) -> str:
        """Extrahiert die Pose aus der Character-Antwort via Vision-LLM.

        Gibt den Pose-String zurueck (fuer den Enhanced Prompt).
        """
        from app.models.character import is_outfit_locked

        # Outfit-Lock spart den kompletten Pose-Call (Pose ist an Agent-Call gekoppelt).
        agent_locked = is_outfit_locked(character_name)

        rp_text = (rp_text or "").strip()
        if not rp_text or agent_locked:
            return ""

        # Character-Quelle: nur Aktionen zwischen *...*, Dialog + Noise raus
        clean_rp = ""
        if rp_text:
            action_chunks = re.findall(r'\*([^*]+)\*', rp_text)
            clean_rp = " ".join(action_chunks) if action_chunks else rp_text
            clean_rp = re.sub(r'"[^"]*"', '', clean_rp)
            clean_rp = re.sub(r'\([^)]*\)', '', clean_rp)
            clean_rp = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', clean_rp)
            clean_rp = re.sub(r'\s+', ' ', clean_rp).strip()

        _instruction_fragments = [
            "description of body pose",
            "short english description",
        ]

        def _strip_instruction_echo(value: str, label: str) -> str:
            for frag in _instruction_fragments:
                if frag in value.lower():
                    logger.warning("RP-Scene: %s ist Echo der Instruktion, verworfen: '%s'",
                                   label, value)
                    return ""
            return value

        def _run_llm(vcfg: Dict[str, Any], system: str, source: str):
            try:
                from app.core.llm_client import LLMClient
                from app.core.llm_queue import get_llm_queue, Priority
                llm = LLMClient(
                    model=vcfg["model"],
                    api_key=vcfg["api_key"],
                    api_base=vcfg["api_base"],
                    temperature=0.1,
                    max_tokens=200,
                    request_timeout=30)
                response = get_llm_queue().submit(
                    task_type="tool",
                    priority=Priority.HIGH,
                    llm=llm,
                    messages_or_prompt=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": f"/no_think\n{source[:500]}"},
                    ],
                    agent_name=vcfg.get("_target_name", character_name))
                raw = response.content.strip()
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                if not match:
                    logger.debug("RP-Scene: Kein JSON: %s", raw[:100])
                    return {}
                import json as _json
                return _json.loads(match.group())
            except Exception as e:
                logger.warning("RP-Scene LLM-Call Fehler: %s", e)
                return {}

        pose = ""

        # Character-Antwort → Pose (fuer Bild-Prompt).
        if clean_rp and len(clean_rp) >= 15:
            vcfg_agent = self._get_vision_llm_config(character_name)
            if vcfg_agent:
                vcfg_agent["_target_name"] = character_name
                sys_agent = (
                    f"The following is {character_name}'s roleplay action. "
                    "Extract a short English description of the character's "
                    "body pose and action.\n\n"
                    "Respond ONLY with JSON:\n"
                    '{"pose": "<pose or empty>"}'
                )
                data = _run_llm(vcfg_agent, sys_agent, clean_rp)
                pose = _strip_instruction_echo((data.get("pose") or "").strip(), "Pose")
                if pose:
                    logger.info("RP-Scene LLM: Pose -> '%s'", pose)
            else:
                logger.debug("RP-Scene: Kein Vision-LLM fuer Agent %s", character_name)

        return pose

    @staticmethod
    def _parse_base_input(raw_input: str) -> Dict[str, Any]:
        """Standard context extraction from a JSON tool/service input
        (self-contained copy of the BaseSkill helper — the service has no
        skill base class)."""
        data: Dict[str, Any] = {"input": raw_input, "agent_name": "", "user_id": ""}
        if isinstance(raw_input, str) and raw_input.strip().startswith("{"):
            try:
                parsed = json.loads(raw_input)
                if isinstance(parsed, dict):
                    data.update(parsed)
            except Exception:
                try:
                    parsed, _ = json.JSONDecoder().raw_decode(raw_input.strip())
                    if isinstance(parsed, dict):
                        data.update(parsed)
                except Exception:
                    pass
        return data

    def _parse_input(self, prompt_input: str) -> Dict[str, Any]:
        """Parses the optional JSON input format of tool/service calls."""
        ctx = self._parse_base_input(prompt_input)

        data: Dict[str, Any] = {
            "prompt": ctx.get("prompt", ctx.get("input", prompt_input)),
            "agent_name": ctx.get("agent_name", ""),
            "set_profile": ctx.get("set_profile", False),
            "skip_gallery": ctx.get("skip_gallery", False),
            "appearances": ctx.get("appearances", None),
            "auto_enhance": ctx.get("auto_enhance", True),
            "workflow": ctx.get("workflow", ""),
            "backend": ctx.get("backend", ""),
            "override_width": ctx.get("override_width"),
            "override_height": ctx.get("override_height"),
            "model_override": ctx.get("model_override", ""),
            "loras": ctx.get("loras", None),
            "character_prompt": ctx.get("character_prompt", ""),
            "pose_prompt": ctx.get("pose_prompt", ""),
            "expression_prompt": ctx.get("expression_prompt", ""),
            "rp_context": ctx.get("rp_context", ""),
            "user_input": ctx.get("user_input", ""),
            "profile_only": ctx.get("profile_only", False),
            "to_avatar_gallery": ctx.get("to_avatar_gallery", False),
            "image_use_case": ctx.get("image_use_case", ""),
        }

        if isinstance(data.get("prompt"), str):
            data["prompt"] = data["prompt"].strip()
        else:
            data["prompt"] = ""

        return data

    def generate_from_input(self, prompt: str) -> str:
        """Generates an image via the cheapest available instance.

        Args:
            prompt: text description of the desired image (or JSON with context)

        Returns:
            string with image links or an error message
        """
        if not self.enabled:
            return "Image generation is not available. No instance configured or reachable."

        # Input parsen (vor Backend-Auswahl, da per-Agent enabled beruecksichtigt wird)
        input_data = self._parse_input(prompt)
        prompt_text = input_data.get("prompt", "")
        character_name = input_data.get("agent_name", "").strip()
        set_profile = bool(input_data.get("set_profile"))
        skip_gallery = bool(input_data.get("skip_gallery"))

        if not prompt_text or len(prompt_text.strip()) == 0:
            return "Fehler: Bitte gib eine Bildbeschreibung ein."

        if not character_name:
            return "Fehler: Agent-Name fehlt fuer Bildspeicherung."

        # Pick backend (explicit selection wins)
        explicit_backend = input_data.get("backend", "").strip() if isinstance(input_data, dict) else ""
        backend = None

        # Normalize the render-target spec: the "workflow" field (legacy name)
        # is a backend glob, e.g. from the per-character render match. A leading
        # "backend:" is a tolerated legacy prefix; "workflow:<glob>" specs come
        # from old configs (ComfyUI removed) and are ignored.
        _target_spec = input_data.get("workflow", "").strip() if isinstance(input_data, dict) else ""
        _soft_backend = ""
        if _target_spec.lower().startswith("backend:"):
            if not explicit_backend:
                explicit_backend = _target_spec.split(":", 1)[1].strip()
        elif _target_spec.lower().startswith("workflow:"):
            logger.warning(
                "Legacy workflow spec '%s' ignoriert (ComfyUI entfernt) — "
                "bitte einen Backend-Glob verwenden", _target_spec)
        elif _target_spec:
            # Bare glob: try as a backend glob, fall back to default selection.
            _soft_backend = _target_spec

        if explicit_backend:
            # Explicit backend — no fallback
            backend = self._wait_for_explicit_backend(explicit_backend)
            if not backend:
                return f"Fehler: Backend '{explicit_backend}' nicht verfuegbar (Timeout)."
            logger.info("Explizites Backend: %s", explicit_backend)
        elif _soft_backend:
            backend = self._wait_for_explicit_backend(_soft_backend)
            if backend:
                logger.info("Backend (Render-Match '%s'): %s", _soft_backend, backend.name)
            else:
                logger.warning(
                    "Render-Match '%s' trifft kein verfuegbares Backend — "
                    "Fallback auf Standard-Auswahl", _soft_backend)

        if not backend:
            backend = self._wait_for_backend(character_name)
        if not backend:
            return "Fehler: Keine Image-Generation Instanz ist aktuell verfuegbar (Timeout)."

        # Lade per-Agent per-Instanz Config
        cfg = self._get_instance_config(character_name, backend)

        # Style/Negative/Instruction kommen AUSSCHLIESSLICH aus dem Use-Case
        # (Admin-Override oder eingebauter Default). Kein Workflow-/Backend-
        # Fallback mehr — der Style gehoert zum FALL der Generierung, nicht zum
        # Modell. Familie (natural/keywords) wird aus dem "Target Prompt Stil"
        # (image_model) des aufgeloesten Workflows abgeleitet.
        # Default-Use-Case "character" — un-verdrahtete Gen-Pfade bekommen so den
        # photoreal Character-Style statt eines leeren Styles.
        from app.core import config as _cfg_mod
        _uc_name = (input_data.get("image_use_case") or "character").strip()
        _uc_img_model = getattr(backend, "image_family", "") if backend else ""
        _ucp = _cfg_mod.get_use_case_prompts(_uc_name, _uc_img_model)
        prompt_style = _ucp.get("prompt_style", "")
        negative_prompt = _ucp.get("prompt_negative", "")

        # Task im Queue-System registrieren fuer einheitliche Sichtbarkeit.
        # start_running=False: Prompt-Build (LLM-Calls) + GPU-Kanal-Wartezeit
        # zaehlen nicht als running — track_activate() erfolgt im GPU-Callable,
        # wenn der Channel-Worker die Generierung tatsaechlich startet.
        _tq = get_task_queue()
        _track_id = _tq.track_start(
            "image_generation", "Bild generieren", agent_name=character_name,
            provider=backend.name, start_running=False)

        try:
            logger.info("=" * 80)
            logger.info("BILDGENERIERUNG GESTARTET")
            logger.info("=" * 80)
            logger.info("Instanz: %s (Typ=%s, Cost=%s)", backend.name, backend.api_type, backend.cost)
            logger.debug("User-ID: %s, Agent: %s, Set as Profile: %s", character_name, set_profile)
            logger.info("Original Prompt: %s", prompt_text)

            # Profilbild-Erkennung
            if not set_profile:
                lowered = prompt_text.lower()
                set_profile = "profilbild" in lowered or "profile image" in lowered or "avatar" in lowered

            # --- RP-Kontext verarbeiten (Deferred Execution) ---
            rp_context = input_data.get("rp_context", "").strip()
            user_text = input_data.get("user_input", "").strip()
            rp_scene_context = ""
            if rp_context and character_name:
                rp_scene_context = self._extract_rp_scene_context(
                    rp_context, character_name)

            # --- Kontext-Daten via PromptBuilder sammeln ---
            from app.core.prompt_builder import (
                PromptBuilder, EntryPointConfig,
                is_photographer_mode, detect_selfie)

            auto_enhance = input_data.get("auto_enhance", True)
            photographer_mode = is_photographer_mode(character_name)
            is_selfie = detect_selfie(prompt_text)
            if photographer_mode:
                logger.info("PHOTOGRAPHER MODE aktiv fuer %s", character_name)

            builder = PromptBuilder(character_name)

            if auto_enhance:
                config = EntryPointConfig.chat()

                # Personen-Detection: NUR aus dem expliziten image_prompt, nicht
                # aus dem RP-Scene-Context. Sonst wird jeder Character, der zufaellig
                # im RP-Kontext eines Tasks erwaehnt ist (z.B. "Logs zu Kai's
                # Aktivitaet"), als Person samt Reference-Bild ins Bild gepushed —
                # auch wenn der Character gar nicht im Bild sein soll.
                # Der User-Avatar wird bei rp_context separat ergaenzt (Block unten),
                # also nichts geht verloren.
                input_appearances = input_data.get("appearances")
                persons = builder.detect_persons(
                    prompt_text,
                    explicit_appearances=input_appearances)

                # Photographer-Filter idempotent anwenden (chat.py:visualize hat
                # ihn bereits aufgerufen, andere Entry Points wie Tool-Call/
                # Instagram noch nicht).
                persons = builder.apply_photographer_filter(
                    persons,
                    photographer_mode=photographer_mode,
                    is_selfie=is_selfie,
                    set_profile=set_profile)

                # Avatar-Augmentation entfernt: Wenn der User-Avatar im Bild
                # sein soll, muss ihn der Tool-LLM namentlich oder via
                # Du-Pronomen erwaehnen. detect_persons() faengt das bereits
                # ab. Automatisches Anhaengen war eine falsche Annahme aus
                # 1:1-Chat-Zeiten und brachte Avatare in Szenen wo sie gar
                # nicht waren (z.B. Bianca macht Selfie waehrend Avatar
                # schlaefft).

                # Item-IDs aus Input (vom Room-Items Panel) — werden in freie
                # Ref-Slots als Props gelegt und im Scene-Prompt beschrieben.
                _item_ids = input_data.get("item_ids") or []
                if isinstance(_item_ids, str):
                    _item_ids = [x.strip() for x in _item_ids.split(",") if x.strip()]

                # Kontext sammeln
                pv = builder.collect_context(
                    persons, config,
                    prompt_text=prompt_text,
                    photographer_mode=photographer_mode,
                    set_profile=set_profile,
                    item_ids=_item_ids)

                # Exclusion rules: only the location leaves the text, and only
                # when a room ref actually gets a slot (priority plan,
                # max_slots). Outfit + activity always stay in the text.
                builder.apply_exclusion_rules(pv, max_slots=backend.ref_slot_count)

                # RP-Szene-Kontext als Scene-Prompt anhaengen
                pv.scene_prompt = prompt_text
                if rp_scene_context:
                    pv.scene_prompt += f", {rp_scene_context}"
                    logger.info("RP-Scene-Context angehaengt: %s", rp_scene_context[:120])

                # Items (Props) als Scene-Zusatz. Slot-Position wird im
                # resolve_reference_slots-Schritt zugeordnet; hier nur
                # Text-Beschreibung anhaengen.
                if pv.items:
                    _item_bits = []
                    for _it in pv.items:
                        _n = _it.get("name", "")
                        _d = _it.get("description", "")
                        if _n and _d:
                            _item_bits.append(f"{_n} ({_d})")
                        elif _n:
                            _item_bits.append(_n)
                    if _item_bits:
                        pv.scene_prompt += f", scene includes props: {', '.join(_item_bits)}"
                        logger.info("Item-Props angehaengt: %s", ", ".join(_item_bits))

                # scene_prompt bereinigen (Defense-in-Depth, Plan 4.2.1b)
                pv.scene_prompt = builder.sanitize_scene_prompt(pv.scene_prompt, pv)

                # Style und Negative-Prompt setzen
                pv.prompt_style = prompt_style
                pv.negative_prompt = negative_prompt

                if set_profile:
                    logger.info("PROFILBILD-MODUS AKTIVIERT")

                # Prompt zusammenbauen via Target-Model-Adapter
                from app.core.prompt_adapters import (
                    get_target_model, render as adapter_render,
                    canonical_to_dict, maybe_enhance_via_llm)
                _backend_model = getattr(backend, "model", "") if backend else ""
                _target_model = get_target_model(
                    getattr(backend, "image_family", "") if backend else "",
                    _backend_model)
                assembled = adapter_render(pv, _target_model)
                template_prompt = assembled["input_prompt_positiv"]
                prompt_without_style = assembled["prompt_without_style"]

                # Optional LLM-Enhancement: Use-Case-Instruction hat Vorrang vor
                # (zentral, nicht per-Character) — kommt aus dem Use-Case.
                _wf_instruction = _ucp.get("prompt_instruction", "")
                enhanced_prompt, _prompt_method = maybe_enhance_via_llm(
                    template_prompt, pv,
                    target_model=_target_model,
                    prompt_instruction=_wf_instruction)
                _canonical_dict = canonical_to_dict(pv)

                # Abwaertskompatible Variablen fuer restlichen Code
                appearances = [{"name": p.name, "appearance": p.appearance} for p in pv.persons]
                agent_mentioned = any(p.is_agent for p in pv.persons)
                no_person_detected = pv.no_person_detected
            else:
                # auto_enhance=False: Prompt bereits vom Caller angereichert
                input_appearances = input_data.get("appearances")
                if input_appearances is not None:
                    persons = builder.detect_persons(
                        prompt_text, explicit_appearances=input_appearances)
                else:
                    persons = builder.detect_persons(
                        "", character_names=[character_name] if character_name else [])

                from app.core.prompt_builder import PromptVariables
                pv = PromptVariables()
                pv.persons = persons
                pv.negative_prompt = negative_prompt

                # Reference-Bilder aufloesen (fuer Style-Conditioning der Generierung).
                # profile_only: Profilbild statt Outfit-Bild (z.B. Outfit-Erstellung).
                # Bei set_profile=True (Profilbild-Erstellung) keine Refs —
                # sonst Self-Reference-Loop.
                _profile_only = bool(input_data.get("profile_only", False))
                if not set_profile:
                    for idx, p in enumerate(persons, 1):
                        ref = builder._resolve_person_ref_image(p, profile_only=_profile_only)
                        if ref:
                            pv.ref_images[idx] = ref
                # profile_only = Variant/Outfit-Portrait: keine Location (weder
                # Location-Prompt noch ref_image_room). Sonst wuerde bei FLUX_BG
                # das Location-Bild den Profilbild-Referenzslot verdraengen.
                if not _profile_only:
                    builder._collect_location(pv)

                appearances = [{"name": p.name, "appearance": p.appearance} for p in persons]
                agent_mentioned = any(p.is_agent for p in persons)
                no_person_detected = False

                enhanced_prompt = prompt_text
                prompt_without_style = prompt_text
                if prompt_style:
                    enhanced_prompt = f"{prompt_style} {enhanced_prompt}"
                logger.info("Auto-Enhance deaktiviert (Prompt vom Caller angereichert)")

                # Canonical-Metadaten fuer Re-Creation auch im auto_enhance=False Pfad
                # (z.B. Instagram). Der Original-Prompt geht 1:1 an ComfyUI, aber
                # canonical wird gespeichert damit "Prompt neu aufbauen" spaeter
                # mit Adapter rendern kann.
                from app.core.prompt_adapters import (
                    get_target_model, canonical_to_dict)
                _backend_model = getattr(backend, "model", "") if backend else ""
                _target_model = get_target_model(
                    getattr(backend, "image_family", "") if backend else "",
                    _backend_model)
                appearances = [{"name": p.name, "appearance": p.appearance} for p in pv.persons]
                pv.prompt_style = prompt_style or "photorealistic"
                pv.scene_prompt = prompt_text
                # Mood/Activity/Outfit aus aktuellem Character-State fuer Rebuild-Kontext
                try:
                    from app.models.character import (
                        get_character_current_feeling,
                        get_effective_activity)
                    if character_name:
                        _mood = get_character_current_feeling(character_name) or ""
                        if _mood:
                            pv.prompt_mood = _mood
                        _act = get_effective_activity(character_name) or ""
                        if _act:
                            pv.prompt_activity = _act
                        _outfit = render_outfit(character_name=character_name).get("full", "") or ""
                        if _outfit and persons:
                            pv.prompt_outfits[1] = f"{persons[0].actor_label or persons[0].name} is wearing {_outfit}"
                except Exception:
                    pass
                template_prompt = enhanced_prompt
                _prompt_method = "caller_provided"
                _canonical_dict = canonical_to_dict(pv)

            # Enhanced Prompt fuer Caller verfuegbar machen — thread-local
            # zuerst, damit parallele Generationen sich nicht gegenseitig
            # ueberschreiben (Race-Condition zwischen Instagram-Post und
            # Expression-Regen). self.last_enhanced_prompt bleibt als
            # Backward-Compat fuer non-threaded Caller.
            self._meta_tls.last_enhanced_prompt = enhanced_prompt
            self.last_enhanced_prompt = enhanced_prompt

            # Start-Zeit fuer Logging merken
            _gen_start = time.time()

            # Generation via backend — the model comes from the backend attribute.
            workflow_model = getattr(backend, 'model', "")

            _ow = input_data.get("override_width")
            _oh = input_data.get("override_height")
            # Priority: override > per-agent config > backend > 1024
            params = {
                "width": _ow or cfg.get("width", getattr(backend, 'width', 1024)),
                "height": _oh or cfg.get("height", getattr(backend, 'height', 1024)),
            }
            logger.info("Size: %sx%s (override_w=%s, override_h=%s)", params["width"], params["height"], _ow, _oh)
            _model_key = "model"
            if workflow_model:
                params[_model_key] = workflow_model
            # Model override from the dialog selection (highest priority)
            model_override = input_data.get("model_override", "").strip()
            if model_override:
                params[_model_key] = model_override

            # Sampling params (read by A1111-style backends)
            if hasattr(backend, 'guidance_scale'):
                params["guidance_scale"] = backend.guidance_scale
            if hasattr(backend, 'num_inference_steps'):
                params["num_inference_steps"] = backend.num_inference_steps
            if hasattr(backend, 'checkpoint'):
                params["checkpoint"] = backend.checkpoint
            if hasattr(backend, 'sampler'):
                params["sampler"] = backend.sampler
            if hasattr(backend, 'scheduler'):
                params["scheduler"] = backend.scheduler
            if hasattr(backend, 'sampling_method'):
                params["sampling_method"] = backend.sampling_method
            if hasattr(backend, 'schedule_type'):
                params["schedule_type"] = backend.schedule_type

            # LoRAs: dialog selection (from the endpoint-filtered per-world LoRA
            # library) goes straight into lora_inputs — localai builds <lora:>
            # prompt tags from it, openai_diffusion lora_NN/strength_NN params.
            if backend.api_type in ("localai", "openai_diffusion"):
                _dialog_loras = input_data.get("loras")
                if _dialog_loras:
                    params["lora_inputs"] = [
                        l for l in _dialog_loras
                        if isinstance(l, dict) and (l.get("name") or "None") != "None"
                    ]

            # Referenz-Slots fuer die Generierung (Conditioning) aufloesen.
            # Workflows mit Referenz-Slots (z.B. QWEN_STYLE) bekommen die
            # aufgeloesten Referenzbilder direkt in die Generierung injiziert.
            if not no_person_detected and pv:
                face_refs = builder.resolve_reference_slots(
                    pv, max_slots=backend.ref_slot_count)
                params["reference_images"] = face_refs["reference_images"]
            else:
                logger.info("Keine Person erkannt -> keine Referenzbilder")
                face_refs = {"reference_images": {}, "has_reference_slots": False}

            # Post-processing happens externally (pull model, see
            # postprocess_trigger.py + /api/images). The generation itself
            # (incl. reference_images for conditioning above) is unaffected.

            _display_model = params.get("model") or getattr(backend, 'model', 'N/A')
            logger.info("Starte Bildgenerierung mit %s (%s)", backend.name, backend.api_url)
            logger.info("Model: %s", _display_model)
            logger.debug("Params: %s", params)

            _primary_backend = backend

            def _prepare_for_backend(b):
                """Adjusts model/LoRA params when falling back to another backend."""
                if b is not _primary_backend:
                    # Model names from the primary backend are not portable —
                    # the fallback backend uses its own configured default.
                    _local = [k for k in ("model", "unet", "checkpoint", "gguf")
                              if params.get(k)]
                    if _local:
                        logger.info(
                            "Fallback: Modell-Keys %s nicht portabel zu %s, "
                            "nutze Backend-Default '%s'",
                            _local, b.name, getattr(b, "model", "?"))
                        for _k in ("model", "unet", "checkpoint", "gguf",
                                   "lora_inputs", "loras"):
                            params.pop(_k, None)
                # Negative comes from the use case (resolved above).
                return enhanced_prompt, negative_prompt

            # Kontext fuers ZENTRALE Logging in backend.generate() (final_prompt,
            # Backend, Model, LoRAs, Refs, Dauer, Seed setzt generate() selbst).
            _log_meta = {
                "agent_name": character_name,
                "original_prompt": prompt_text,
                "appearances": appearances,
                "agent_mentioned": agent_mentioned,
                "auto_enhance": auto_enhance,
                "context": {k: v for k, v in {
                    "mood": pv.prompt_mood if pv else "",
                    "activity": pv.prompt_activity if pv else "",
                    "location": pv.prompt_location if pv else "",
                }.items() if v},
                "pose_prompt": params.get("pose_prompt", ""),
                "expression_prompt": params.get("expression_prompt", ""),
            }
            def _op(b):
                _p, _n = _prepare_for_backend(b)

                def _gen():
                    # Tracker erst hier aktivieren: laeuft im Channel-Worker,
                    # d.h. exakt wenn die GPU-Arbeit beginnt — Warteschlangen-
                    # Zeit erscheint im Panel als pending, nicht als running.
                    try:
                        from app.core.task_router import match_queue_name
                        _tq.track_activate(
                            _track_id,
                            queue_name=match_queue_name(b.name) or "",
                            provider=b.name)
                    except Exception:
                        pass
                    return b.generate(_p, _n, params, log_meta=_log_meta)

                # ALLE Backends laufen ueber die channel-limitierte GPU-Queue:
                # submit_gpu_task matcht per provider_name den backend:<name>-Channel
                # mit dessen max_concurrent. Frueher liefen Cloud-/OpenAI-Backends
                # direkt (return _gen()) → unbegrenzt parallel; jetzt wartet ein
                # Job, wenn das Backend-Limit erreicht ist (wie bei ComfyUI/A1111).
                from app.core.llm_queue import get_llm_queue, Priority as _P
                return get_llm_queue().submit_gpu_task(
                    provider_name=b.name,
                    task_type="image_generation",
                    priority=_P.IMAGE_GEN,
                    callable_fn=_gen,
                    agent_name=character_name, label=b.name,
                    gpu_type=b.api_type)

            # Re-Check anderer Backends, falls sie beim Start unavailable waren
            for b in self.backends:
                if b.instance_enabled and not b.available and b != backend:
                    b.check_availability()

            try:
                images, backend = self.run_with_fallback(
                    primary_backend=backend, op=_op,
                    character_name=character_name)
            except RuntimeError as _err:
                logger.error("Bildgenerierung fehlgeschlagen (alle Backends): %s", _err)
                images = []

            if not images:
                _tq.track_finish(_track_id, error="Keine Bilder generiert")
                return "API antwortete, aber keine Bilder enthalten."

            _gen_duration = time.time() - _gen_start
            logger.info("ERFOLG - %d Bild(er) generiert via %s (%.1fs)", len(images), backend.name, _gen_duration)

            # Image-Prompt-Logging passiert jetzt ZENTRAL in backend.generate()
            # (mit dem finalen, trigger-injizierten Prompt) — via log_meta oben.

            # 1. Zuerst Bilder/Videos auf die Platte speichern.
            # Gallery-Target-Routing (Prio von hoch nach niedrig):
            #  (a) `to_avatar_gallery=True` explizit -> Avatar (z.B. SendImage-Intent)
            #  (b) Empfaenger-Erkennung aus Prompt ("Fuer Diego", "An Enzo") ->
            #      Empfaenger's Galerie. Funktioniert auch fuer Background-Thoughts.
            #  (c) Avatar chattet AKTIV mit dem Erzeuger-NPC -> Avatar's Galerie.
            #  (d) Sonst -> Erzeuger behaelt das Bild (Background-Thoughts ohne
            #      klaren Empfaenger).
            # set_profile bleibt beim Agent — sonst landet das Profilbild
            # in der falschen Galerie.
            _explicit_avatar = bool(input_data.get("to_avatar_gallery"))
            gallery_character = character_name
            if not skip_gallery and not set_profile:
                try:
                    from app.models.account import get_active_character
                    from app.models.character import list_available_characters
                    _avatar = (get_active_character() or "").strip()
                    _all_chars = [c for c in list_available_characters() if not c.startswith("_")]

                    # (a) explicit-avatar override wins
                    if _explicit_avatar and _avatar and _avatar != character_name:
                        gallery_character = _avatar
                        logger.info(
                            "Bild wird in Avatar-Galerie gespeichert "
                            "(agent=%s -> avatar=%s, source=explicit)",
                            character_name, _avatar)
                    elif rp_context:
                        # (b) Empfaenger aus Prompt-Text extrahieren
                        recipient = self._detect_recipient_from_prompt(
                            prompt_text, character_name, _all_chars)
                        if recipient:
                            gallery_character = recipient
                            logger.info(
                                "Bild routed zu Empfaenger '%s' (agent=%s, prompt enthaelt 'fuer/an %s')",
                                recipient, character_name, recipient)
                        else:
                            # (c) avatar chattet aktiv mit creator?
                            _is_active_chat = False
                            try:
                                from app.routes.chat import _get_chat_partner
                                _is_active_chat = (_get_chat_partner() or "").strip() == character_name
                            except Exception:
                                pass
                            if _is_active_chat and _avatar and _avatar != character_name:
                                gallery_character = _avatar
                                logger.info(
                                    "Bild wird in Avatar-Galerie gespeichert "
                                    "(agent=%s -> avatar=%s, source=active_chat)",
                                    character_name, _avatar)
                            else:
                                logger.info(
                                    "Bild bleibt bei Erzeuger '%s' "
                                    "(rp_context=True, kein Empfaenger erkannt, kein aktiver Chat mit Avatar)",
                                    character_name)
                except Exception as _gt_err:
                    logger.debug("Gallery-Target-Resolve fehlgeschlagen: %s", _gt_err)

            images_dir = get_character_images_dir(gallery_character)
            saved_files = []
            timestamp = int(time.time())

            for i, image_bytes in enumerate(images, 1):
                ext = self._detect_media_extension(image_bytes)
                # Filename behaelt Agent-Namen (Herkunfts-Hinweis), liegt aber
                # unter gallery_character/images/.
                file_name = f"{character_name}_{timestamp}_{uuid.uuid4().hex[:8]}_{i}{ext}"
                image_path = images_dir / file_name
                image_path.write_bytes(image_bytes)
                if not skip_gallery:
                    add_character_image(gallery_character, file_name)
                    add_character_image_prompt(gallery_character, file_name, prompt_without_style)
                saved_files.append(file_name)

            if not saved_files:
                _tq.track_finish(_track_id, error="Bilder nicht gespeichert")
                return "Fehler: Bilder konnten nicht gespeichert werden."

            logger.info("Gespeicherte Bilder: %s", ", ".join(saved_files))

            if not set_profile:
                lowered = prompt_text.lower()
                set_profile = "profilbild" in lowered or "profile image" in lowered or "avatar" in lowered

            if set_profile:
                set_character_profile_image(character_name, saved_files[0])
                logger.info("Als Profilbild gesetzt: %s", saved_files[0])

            # Post-Processing geschieht extern (Pull-Modell): nach dem Speichern
            # wird ein Trigger an den externen Dienst gesendet (s.u.
            # postprocess_trigger), der das fertige Bild zieht, bearbeitet und
            # ueber /api/images zurueckschreibt.

            # Save image metadata (skill, backend, duration)
            _location = get_character_current_location(character_name) or ""
            _room_id = get_character_current_room(character_name) or ""
            _lora_meta = [
                {"name": l.get("name", "None"), "strength": l.get("strength", 1.0)}
                for l in params.get("lora_inputs", [])
                if l.get("name") and l["name"] != "None"
            ]
            # Referenzbilder-Namen fuer Metadaten
            # Referenzen liegen je nach Workflow in face_refs statt params
            _ref_source = params.get("reference_images") or face_refs.get("reference_images") or {}
            _ref_meta = {}
            for _rk, _rv in _ref_source.items():
                _ref_meta[_rk] = os.path.basename(_rv) if _rv else ""
            # Herkunft: wenn das Bild in einer FREMDEN Galerie landet (anderer
            # Character als der Erzeuger), wird der Erzeuger in `from_character`
            # vermerkt. Das Frontend zeigt dann einen Marker am Bild und die
            # Bild-Info nennt explizit von wem das Bild stammt.
            _from_character = character_name if gallery_character != character_name else ""
            _meta = {
                "backend": backend.name,
                "backend_type": backend.api_type,
                "negative_prompt": negative_prompt,
                "from_character": _from_character,
                "guidance_scale": params.get("guidance_scale"),
                "num_inference_steps": params.get("num_inference_steps") or params.get("steps"),
                "duration_s": round(_gen_duration, 1),
                "created_at": utc_now_iso(),
                "location": _location,
                "room_id": _room_id,
                "seed": params.get("seed", 0),
                "loras": _lora_meta,
                # Model: Prio params (Dialog-Override / Workflow-Default) > backend.model
                # > backend.last_used_checkpoint > backend.checkpoint. Damit auch
                # bei Cloud-Backends ohne Workflow (Together/CivitAI) ein Modellname
                # in der Bild-Info erscheint.
                "model": (
                    params.get("model")
                    or params.get("unet")
                    or getattr(backend, "model", "")
                    or getattr(backend, "last_used_checkpoint", "")
                    or getattr(backend, "checkpoint", "")
                    or ""),
                "reference_images": _ref_meta,
                "target_model": locals().get("_target_model", ""),
                "canonical": locals().get("_canonical_dict", {}),
                "template_prompt": locals().get("template_prompt", ""),
                "prompt_method": locals().get("_prompt_method", "template"),
                "items_used": list(locals().get("_item_ids") or []),
                # Owner + files of this generation — lets same-turn consumers
                # (e.g. SendMessage attach_image) reference the image without
                # rescanning the gallery.
                "gallery_character": gallery_character,
                "filenames": list(saved_files),
            }
            # Store thread-local (for parallel callers)
            # + mirror on the instance (backward compat for non-threaded callers)
            self._meta_tls.last_image_meta = _meta
            self.last_image_meta = _meta

            if not skip_gallery:
                from app.models.character import add_character_image_metadata
                for fn in saved_files:
                    add_character_image_metadata(gallery_character, fn, _meta)

            # Post-processing hand-off (pull model): notify an external service
            # about scene/chat images. Avatar/profile images are excluded
            # (set_profile) — they are the reference sources, not PP targets.
            # Fire-and-forget; no image bytes are sent.
            if not skip_gallery and not set_profile:
                try:
                    from app.core import postprocess_trigger
                    for fn in saved_files:
                        postprocess_trigger.trigger(images_dir / fn, "scene")
                except Exception as _pp_err:  # noqa: BLE001
                    logger.debug("postprocess trigger skipped: %s", _pp_err)

            # Situations-Kommentar + Bildanalyse generieren
            comment = None
            if not skip_gallery:
                _tq.track_update_label(_track_id, "Bildanalyse")
                logger.info("Starte Bildanalyse + Situations-Kommentar...")
                first_image_path = images_dir / saved_files[0]
                logger.debug("Bild-Datei: %s, Existiert: %s", first_image_path, first_image_path.exists())
                _subjects = [p["name"] for p in appearances] if photographer_mode and appearances else None
                # Comment wird aus Sicht des AGENTS generiert (er hat das Bild
                # gemacht), aber an das Bild des gallery_character geheftet.
                comment = self._generate_comment(
                    character_name, rp_context=rp_context,
                    photographer_subjects=_subjects)
                if comment:
                    logger.info("Situations-Kommentar gespeichert")
                    add_character_image_comment(gallery_character, saved_files[0], comment)
                else:
                    logger.debug("Kein Situations-Kommentar generiert (kein RP-Kontext)")
                # Objektive Bildanalyse: Vision-LLM-Aufruf nutzt Agent-Profil
                # (Sprache/Persoenlichkeit), Ergebnis landet am Bild im Gallery-Char.
                analysis = self._generate_image_analysis(str(first_image_path), character_name)
                if analysis:
                    from app.models.character import add_character_image_metadata
                    add_character_image_metadata(gallery_character, saved_files[0], {"image_analysis": analysis})
                    logger.info("Objektive Bildanalyse gespeichert")
            else:
                logger.debug("Bildanalyse uebersprungen (skip_gallery=True)")

            # Rueckgabe: Bild(er) + Kommentar
            output_lines = []
            output_lines.append(f"AKTION: Bild wurde GENERIERT und in der Galerie von {gallery_character} gespeichert. "
                                f"Das Bild wurde NICHT gesendet oder verschickt — es liegt in der Galerie.")
            for i, file_name in enumerate(saved_files, 1):
                image_url = f"/characters/{gallery_character}/images/{file_name}"
                output_lines.append(f"![Generated Image {i}]({image_url})")

            if comment:
                output_lines.append(f"CAPTION (nur zur Anzeige, NICHT als Fakt behandeln): {comment}")

            logger.info("=" * 80)
            logger.info("BILDGENERIERUNG ABGESCHLOSSEN (via %s)", backend.name)
            logger.info("=" * 80)

            _tq.track_finish(_track_id)
            return "\n\n".join(output_lines)

        except requests.exceptions.Timeout:
            error_msg = f"Bildgenerierung hat zu lange gedauert ({backend.name})"
            logger.error("Timeout: %s", error_msg)
            backend.mark_unhealthy("generate timeout", _BACKEND_COOLDOWN_SECONDS)
            _tq.track_finish(_track_id, error=error_msg)
            _log_image_failure(locals(), error_msg)
            return f"Fehler: {error_msg}"
        except requests.exceptions.ConnectionError:
            error_msg = f"Verbindung zu {backend.name} ({backend.api_url}) fehlgeschlagen"
            logger.error("ConnectionError: %s", error_msg)
            backend.mark_unhealthy("connection error", _BACKEND_COOLDOWN_SECONDS)
            _tq.track_finish(_track_id, error=error_msg)
            _log_image_failure(locals(), error_msg)
            return f"Fehler: {error_msg}"
        except Exception as e:
            error_msg = f"Bildgenerierung ({backend.name}): {e}"
            logger.error("Fehler bei %s", error_msg)
            _tq.track_finish(_track_id, error=error_msg)
            _log_image_failure(locals(), error_msg)
            return f"Fehler bei {error_msg}"

# ---------------------------------------------------------------------------
# Singleton access — consumers use this instead of fetching a skill
# ---------------------------------------------------------------------------

_service: Optional[ImageService] = None


def get_image_service() -> ImageService:
    """Lazy singleton. Rebuilt after reset_image_service() (config reload)."""
    global _service
    if _service is None:
        _service = ImageService()
    return _service


def reset_image_service() -> None:
    """Drop the cached service so the next access reloads the backend pool
    (called from skill reload / admin settings save)."""
    global _service
    _service = None
