"""Instagram posting verb — creates Instagram posts with an AI-generated image and caption.

Part of the instagram package (wave 5): the platform (models/instagram,
feed routes, panel) stays core, the verbs + social reactions + prompt
contributions live here."""
import base64
import json
import os
import re
from typing import Any, Dict, Optional

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.core.log import get_logger
from app.core.llm_queue import get_llm_queue, Priority
from app.core.task_queue import get_task_queue
from app.core.tool_formats import format_example
from app.models.instagram import create_post, get_instagram_dir
from app.models.character import (
    get_character_images_dir,
    get_character_personality,
    get_character_appearance,
    get_character_profile,
    get_character_current_location,
    get_effective_activity,
    save_character_current_feeling,
    list_available_characters)
from app.models.character_template import resolve_profile_tokens, get_template
from app.models.world import get_location

from app.core.timeutils import parse_iso, utc_now, utc_now_iso

logger = get_logger("instagram_skill")

# Language code to English name for caption/image-analysis prompts.
# Previously binary ("de" -> German, everything else -> English); now
# every supported language is mapped consistently.
_LANG_NAMES = {"de": "German", "en": "English", "fr": "French",
               "es": "Spanish", "it": "Italian", "ja": "Japanese",
               "pt": "Portuguese", "nl": "Dutch", "ru": "Russian"}

class InstagramSkill(PluginSkill):
    """Create Instagram posts for agents.

    Generate an image without a gallery entry, analyse it with a vision LLM,
    then write a natural caption from the analysis.
    """

    SKILL_ID = "instagram"
    DEFERRED = True  # The post is created after the chat response.
    # [INTENT: instagram_post | caption=...] (F6) — dispatched here.
    INTENT_TYPES = ("instagram_post",)
    INTENT_PAYLOAD_KEYS = ("caption",)

    def handle_intent(self, intent_type, payload):
        """[INTENT: instagram_post]: the caption hint becomes the input."""
        import json as _json
        raw_input = _json.dumps({
            "input": payload.get("caption", "") or "Create an Instagram post",
            "agent_name": payload.get("agent_name", ""),
            "user_id": "",
        })
        result = self.execute(raw_input)
        success = bool(result) and "Fehler" not in str(result)
        return {"success": success, "result": str(result)[:500]}

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)

        # Package config (skills.instagram.*) seeds the per-character defaults.
        self._defaults = {
            "enabled": True,
            "caption_style": str(ctx.get_config("skills.instagram.caption_style", "casual")),
            "hashtag_count": int(ctx.get_config("skills.instagram.hashtag_count", 5)),
            "caption_language": str(ctx.get_config("skills.instagram.caption_language", "en")),
            "popularity": int(ctx.get_config("skills.instagram.default_popularity", 50)),
            "post_cooldown_hours": int(ctx.get_config("skills.instagram.post_cooldown_hours", 12)),
        }

        from plugins.instagram.social_reactions import ensure_registered
        ensure_registered()
        logger.info("Instagram skill initialized")

    def _get_vision_llm(self, character_name: str):
        """Resolve the image_recognition LLM for this character."""
        from app.core.llm_router import resolve_llm
        instance = resolve_llm("image_recognition", agent_name=character_name)
        if not instance:
            logger.warning("No image_recognition LLM instance available for %s", character_name)
        return instance

    def _get_image_skill(self):
        """Returns the core image service (wave-6 split) or None."""
        from app.imagegen.service import get_image_service
        svc = get_image_service()
        return svc if svc.enabled else None

    def _parse_input(self, raw_input: str) -> Dict[str, Any]:
        """Parse JSON fields, a plain image prompt, or IMAGE/CAPTION legacy input."""
        ctx = self._parse_base_input(raw_input)

        # Prefer explicit JSON fields.
        image_prompt_field = (ctx.get("image_prompt") or "").strip()
        caption_field = (ctx.get("caption") or "").strip()

        full_input = ctx.get("prompt", ctx.get("input", raw_input))
        image_prompt = image_prompt_field or full_input
        caption = caption_field

        # Legacy: IMAGE: ... | CAPTION: ...
        if "|" in full_input and "CAPTION" in full_input.upper():
            parts = full_input.split("|", 1)
            image_prompt = parts[0].strip()
            cap_part = parts[1].strip()
            if cap_part.upper().startswith("CAPTION:"):
                caption = caption or cap_part[8:].strip()

        # Remove the IMAGE: prefix.
        if image_prompt.upper().startswith("IMAGE:"):
            image_prompt = image_prompt[6:].strip()

        return {
            "image_prompt": image_prompt,
            "caption": caption,
            "agent_name": ctx.get("agent_name", ""),
            "user_id": ctx.get("user_id", ""),
        }

    def _extract_filename(self, image_result: str) -> str:
        """Extract the image filename from the image-generation result."""
        match = re.search(r'/images/([^?)\n]+)', image_result)
        return match.group(1) if match else ""

    def _extract_hashtags(self, caption: str) -> list:
        """Extract hashtags from a caption."""
        return re.findall(r'#(\w+)', caption)

    def _generate_caption(self, image_path: str, character_name: str, image_prompt: str, current_location: Optional[str] = None, current_activity: Optional[str] = None, chat_text: str = "", draft_caption: str = "") -> Optional[str]:
        """Analyse the generated image and write a natural caption.

        Args:
            image_path: Path to the generated image.
            character_name: Name of the agent.
            image_prompt: Original image description.
            current_location: Current location, if available.
            current_activity: Current activity, if available.
            chat_text: Current situation, if available.
            draft_caption: The calling LLM's idea to inspire a complete post.
        """

        logger.info("Instagram Caption-Generierung gestartet...")
        logger.info(f"Bildpfad: {image_path}")
        logger.info(f"Agent: {character_name}")
        
        # Check that the image exists.
        if not os.path.exists(image_path):
            logger.error(f"Bilddatei existiert nicht: {image_path}")
            return None
        
        # Encode the image as base64.
        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            logger.info(f"Bild geladen: {len(image_bytes)} bytes -> {len(base64_image)} chars Base64")
        except Exception as e:
            logger.error(f"Fehler beim Laden des Bildes: {e}")
            return None

        # Load the agent's personality.
        personality = get_character_personality(character_name) or ""

        # Per-Agent Config
        cfg = self._get_effective_config(character_name)
        caption_style = cfg.get("caption_style", "casual")
        hashtag_count = cfg.get("hashtag_count", 5)
        caption_language = cfg.get("caption_language", "de")

        lang_name = _LANG_NAMES.get(caption_language, caption_language)

        # Build context-aware prompt with location, activity, situation and persons
        context_info = ""
        context_parts = []
        if current_location:
            loc_data = get_location(current_location)
            loc_name = loc_data.get("name", current_location) if loc_data else current_location
            loc_desc = loc_data.get("description", "") if loc_data else ""
            context_parts.append(f"- Ort: {loc_name}" + (f" ({loc_desc})" if loc_desc else ""))
        if current_activity:
            context_parts.append(f"- Aktivitaet: {current_activity}")
        if chat_text:
            context_parts.append(f"- Aktuelle Situation: {chat_text[:500]}")
        if context_parts:
            context_info = "\n\nKONTEXT MEINES MOMENTS:\n" + "\n".join(context_parts)
            context_info += "\nNutze diesen Kontext fuer einen passenden, authentischen Post.\n"

        # Use the thought LLM's draft caption as inspiration.
        if draft_caption:
            context_info += (
                "\n\nMEINE KURZE NOTIZ-IDEE (dient als Einstieg/Inspiration, "
                "du darfst sie umformulieren und ausbauen — nicht woertlich "
                "uebernehmen, nicht nur verkuerzen):\n"
                f"\"{draft_caption}\"\n"
            )

        # Include the personality in the prompt.
        style_description = (
            f"Your style: {personality}" if personality
            else "Your style: friendly, confident and approachable.")

        from app.core.prompt_templates import render_task
        _, prompt_text = render_task(
            "instagram_caption",
            character_name=character_name,
            style_description=style_description,
            caption_style=caption_style,
            hashtag_count=hashtag_count,
            language_name=lang_name,
            context_info=context_info)

        try:
            # Use the routed provider and its request-body settings for captions.
            instance = self._get_vision_llm(character_name)
            if not instance:
                return None
            llm = instance.create_llm(
                temperature=instance.temperature,
                max_tokens=instance.max_tokens or 300)
            logger.info("LLM initialized: %s @ %s", instance.model,
                        instance.api_base or "default")

            # Send the image and text together.
            image_url = f"data:image/png;base64,{base64_image}"
            message = {"role": "user", "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]}

            logger.debug("Message erstellt:")
            logger.debug(f"Text: {len(prompt_text)} chars")
            logger.debug(f"Image URL: data:image/png;base64,... ({len(image_url)} chars total)")
            logger.debug(f"Content items: {len(message['content'])}")
            logger.info("Sending to LLM %s...", instance.model)
            
            from app.core.llm_queue import get_llm_queue, Priority
            response = get_llm_queue().submit(
                task_type="instagram_caption",
                priority=Priority.NORMAL,
                llm=llm,
                messages_or_prompt=[message],
                agent_name=character_name)
            caption = response.content.strip()

            # Remove artifacts and metadata from the generated caption.
            caption = re.sub(r'^(?:Bildtext|Caption|Post\s*Text|Text\s*\d*)\s*:\s*', '', caption, flags=re.MULTILINE)
            caption = re.sub(r'\*\*I\s+feel\s+[^*]+\*\*\.?\s*', '', caption, flags=re.IGNORECASE)
            caption = re.sub(r'\bI\s+feel\s+\w+(?:\s+\w+)?\.?\s*$', '', caption, flags=re.IGNORECASE)
            caption = ' '.join(caption.split()).strip()
            # Remove surrounding quotes when the LLM adds them.
            if caption.startswith('"') and caption.endswith('"'):
                caption = caption[1:-1]
            if caption.startswith("'") and caption.endswith("'"):
                caption = caption[1:-1]

            logger.info(f"Caption generiert: {caption}")
            return caption

        except Exception as e:
            logger.error(f"Caption-Generation fehlgeschlagen: {e}")
            logger.debug("Traceback:", exc_info=True)
            return None

    def _analyze_image(self, image_path: str, character_name: str) -> Optional[str]:
        """Describe the generated image objectively for its post metadata."""

        logger.info("Instagram Bildanalyse gestartet...")

        if not os.path.exists(image_path):
            logger.error("Bilddatei existiert nicht: %s", image_path)
            return None

        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            logger.error("Fehler beim Laden des Bildes fuer Analyse: %s", e)
            return None

        # Detect language from caption config for this agent
        cfg = self._get_effective_config(character_name)
        caption_language = cfg.get("caption_language", "de")
        lang_name = _LANG_NAMES.get(caption_language, caption_language)

        from app.core.prompt_templates import render_task
        analysis_system, prompt_text = render_task(
            "image_analysis", language_name=lang_name)

        try:
            instance = self._get_vision_llm(character_name)
            if not instance:
                logger.warning("No vision LLM available for image analysis")
                return None
            llm = instance.create_llm(temperature=0.3, max_tokens=500)

            image_url = f"data:image/png;base64,{base64_image}"
            messages = [
                {"role": "system", "content": analysis_system},
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

            logger.info("Bildanalyse abgeschlossen: %s", analysis[:120])
            return analysis
        except Exception as e:
            logger.error("Bildanalyse fehlgeschlagen: %s", e)
            logger.debug("Traceback:", exc_info=True)
            return None

    def execute(self, raw_input: str) -> str:
        """
        Create an Instagram post in 3 steps:
        1. Render the image (no gallery entry)
        2. Let the LLM analyse the image
        3. Write a natural caption from it

        Args:
            raw_input: JSON string with input (image description), character_name, user_id

        Returns:
            A string with the post confirmation and the image link
        """
        input_data = self._parse_input(raw_input)
        image_prompt = input_data["image_prompt"]
        provided_caption = input_data.get("caption", "").strip()
        character_name = input_data["agent_name"]
        user_id = input_data["user_id"]

        if not character_name:
            return "Fehler: Agent-Name fehlt."
        if not image_prompt.strip():
            return "Fehler: Bildbeschreibung fehlt."

        # Per-agent enabled check
        cfg = self._get_effective_config(character_name)
        if not cfg.get("enabled", True):
            return f"Error: Instagram is disabled for {character_name}."

        # Check the cooldown
        cooldown_hours = int(cfg.get("post_cooldown_hours", 12))
        if cooldown_hours > 0:
            from datetime import datetime, timedelta
            from app.models.character import get_character_skill_config
            agent_config = get_character_skill_config(character_name, self.SKILL_ID)
            last_ts = (agent_config or {}).get("last_post_timestamp")
            if last_ts:
                try:
                    last_post_time = parse_iso(last_ts)
                    cooldown_end = last_post_time + timedelta(hours=cooldown_hours)
                    now = utc_now()
                    if now < cooldown_end:
                        remaining = cooldown_end - now
                        hours_left = remaining.total_seconds() / 3600
                        logger.info("Cooldown aktiv: %s hat noch %.1fh Cooldown", character_name, hours_left)
                        return (f"Error: {character_name} is still on post cooldown "
                                f"({hours_left:.1f} h of {cooldown_hours} h left).")
                except (ValueError, TypeError):
                    pass

        # Step 1: get the image service and render the image
        image_skill = self._get_image_skill()
        if not image_skill:
            return "Fehler: ImageGenerator Skill nicht verfuegbar. Bild kann nicht generiert werden."

        # Remember location and activity for the caption
        current_location = get_character_current_location(character_name)
        current_activity = get_effective_activity(character_name)

        # Task tracking
        _tq = get_task_queue()
        _track_id = _tq.track_start("instagram_post", "Instagram: Bild generieren", agent_name=character_name)

        logger.info("=" * 60)
        logger.info(f"INSTAGRAM-POST ERSTELLEN fuer {character_name}")
        logger.info("=" * 60)
        if current_location:
            _il = get_location(current_location)
            logger.info(f"Location: {_il.get('name', current_location) if _il else current_location}")
        if current_activity:
            logger.info(f"Activity: {current_activity}")
        logger.info("Schritt 1: Bild generieren via Standard-Pipeline (auto_enhance=True)...")
        logger.info(f"Bild-Prompt: {image_prompt}")

        # Instagram-specific: fish the people out of the image prompt (the
        # agent always + every character mentioned). The standard pipeline
        # then does person/outfit/mood/activity/location/adapter rendering
        # and the optional LLM enhancement.
        _appearances = []
        _agent_app = get_character_appearance(character_name)
        if _agent_app and "{" in _agent_app:
            _prof = get_character_profile(character_name)
            _tmpl = get_template(_prof.get("template", "")) if _prof.get("template") else None
            _agent_app = resolve_profile_tokens(
                _agent_app, _prof, template=_tmpl, target_key="character_appearance"
            )
        if _agent_app:
            _appearances.append({"name": character_name, "appearance": _agent_app})

        # Detect other characters in the prompt (everything is a character — the
        # player's avatar too is an ordinary character in list_available_characters)
        _prompt_lower = f" {image_prompt.lower()} "
        for _char_name in list_available_characters():
            if _char_name == character_name:
                continue
            if f" {_char_name.lower()} " in _prompt_lower:
                _char_app = get_character_appearance(_char_name)
                if _char_app and "{" in _char_app:
                    _other_profile = get_character_profile(_char_name)
                    _other_tmpl = get_template(_other_profile.get("template", "human-default"))
                    _char_app = resolve_profile_tokens(
                        _char_app, _other_profile, template=_other_tmpl, target_key="character_appearance"
                    )
                if _char_app:
                    _appearances.append({"name": _char_name, "appearance": _char_app})

        image_payload = {
            "prompt": image_prompt,
            "input": image_prompt,
            "agent_name": character_name,
            "user_id": "",
            "set_profile": False,
            "skip_gallery": True,
            "auto_enhance": True,           # standard pipeline: adapter + optional LLM enhancement
            "appearances": _appearances,    # Instagram-specific: people pre-detected in the prompt
            # The render target is the "instagram" occasion of the image
            # routing (the character's own match first, then its chain).
            "occasion": "instagram",
        }

        try:
            image_result = image_skill.generate_from_input(json.dumps(image_payload))
        except Exception as e:
            logger.error(f"Fehler bei Bildgenerierung: {e}")
            _tq.track_finish(_track_id, error=str(e))
            return f"Fehler bei Bildgenerierung: {e}"

        # Extract the file name from the result
        image_filename = self._extract_filename(image_result)
        if not image_filename:
            logger.error(f"Konnte Dateiname nicht extrahieren: {image_result}")
            _tq.track_finish(_track_id, error="Dateiname nicht extrahiert")
            return f"Fehler: Bild wurde generiert, aber Dateiname konnte nicht extrahiert werden."

        logger.info(f"Bild generiert: {image_filename}")

        # Take the enhanced prompt (as sent to the backend) for the post metadata.
        # Thread-local first (race-safe) — see the gen_meta block below.
        final_image_prompt = ""
        try:
            _tls_p = getattr(image_skill, '_meta_tls', None)
            if _tls_p is not None:
                final_image_prompt = getattr(_tls_p, 'last_enhanced_prompt', '') or ""
        except Exception:
            pass
        if not final_image_prompt:
            final_image_prompt = getattr(image_skill, 'last_enhanced_prompt', '') or image_prompt

        # Take the generation metadata from the image service.
        # IMPORTANT: read the thread-local slot first — with parallel renders
        # (e.g. an Instagram post and an expression regen at the same time) the
        # instance variant would be overwritten with foreign meta (race
        # condition: one character's expression-regen meta lands in another's post).
        gen_meta = {}
        try:
            _tls = getattr(image_skill, '_meta_tls', None)
            if _tls is not None:
                gen_meta = getattr(_tls, 'last_image_meta', None) or {}
        except Exception:
            pass
        if not gen_meta:
            gen_meta = getattr(image_skill, 'last_image_meta', None) or {}

        # Move the image from images/ to instagram/
        images_dir = get_character_images_dir(character_name)
        instagram_dir = get_instagram_dir()
        src_path = images_dir / image_filename
        dst_path = instagram_dir / image_filename

        logger.info(f"Verschiebe Bild: {src_path} -> {dst_path}")

        import shutil
        try:
            shutil.copy2(str(src_path), str(dst_path))
            if dst_path.exists():
                src_path.unlink()
                logger.info("Bild verschoben: images/ -> instagram/")
            else:
                logger.warning("Kopie fehlgeschlagen, verwende Originalpfad")
                dst_path = src_path
        except Exception as e:
            logger.warning(f"Fehler beim Verschieben: {e}, verwende Originalpfad")
            dst_path = src_path

        # Current location and activity
        current_activity = get_effective_activity(character_name)
        
        # Steps 2+3: the LLM analyses the image and writes the caption
        _tq.track_update_label(_track_id, "Instagram: Caption generieren")
        logger.info("=" * 60)
        logger.info("Schritt 2+3: Bild analysieren und Caption generieren...")
        logger.info(f"Bildpfad fuer Analyse: {dst_path}")
        logger.debug(f"Datei existiert: {dst_path.exists()}")
        if current_location:
            _il = get_location(current_location)
            logger.info(f"Location: {_il.get('name', current_location) if _il else current_location}")
        if current_activity:
            logger.info(f"Activity: {current_activity}")
        logger.info("=" * 60)

        # Primary: the caption from the thought tool argument (provided_caption).
        # The calling thought LLM already wrote it in the character's voice —
        # no second vision-LLM call needed.
        # Fallback: without a caption the vision LLM writes one from the
        # image. Last fallback: image_prompt + generic hashtags.
        if provided_caption and provided_caption.strip():
            caption = provided_caption.strip()
            logger.info("Caption aus Tool-Argument genutzt (Vision-LLM uebersprungen)")
        else:
            caption = self._generate_caption(
                str(dst_path), character_name, image_prompt,
                current_location, current_activity,
                draft_caption="")
            if not caption:
                logger.warning("Fallback: Verwende einfachen Caption")
                caption = f"{image_prompt} #instagram #ai"

        # Extract the hashtags
        hashtags = self._extract_hashtags(caption)

        # Step 4: image analysis via the vision LLM
        _tq.track_update_label(_track_id, "Instagram: Bildanalyse")
        logger.info("Schritt 4: Bildanalyse via Vision-LLM...")
        image_analysis = self._analyze_image(str(dst_path), character_name)
        if image_analysis:
            logger.info("Bildanalyse: %s", image_analysis[:120])
        else:
            logger.warning("Bildanalyse fehlgeschlagen oder leer")

        # Create and store the post
        _tq.track_update_label(_track_id, "Instagram: Post erstellen")
        image_meta = {
            "backend": gen_meta.get("backend", ""),
            "backend_type": gen_meta.get("backend_type", ""),
            "duration_s": gen_meta.get("duration_s", 0.0),
            "image_analysis": image_analysis or "",
        }
        # Copy the reference images into the metadata (for regeneration + character detection)
        if gen_meta.get("reference_images"):
            image_meta["reference_images"] = gen_meta["reference_images"]
        # Extended fields for the re-creation dialog + image info panel —
        # without them a rebuild runs blind on the current character state
        # (the "no original values stored" hint in the UI). `routing` /
        # `fallback_from` carry the image routing's record of this render.
        for _k in ("canonical", "canonical_source", "target_model",
                   "template_prompt", "prompt_method",
                   "character_names", "from_character",
                   "model", "loras", "seed", "negative_prompt",
                   "guidance_scale", "num_inference_steps",
                   "items_used", "location", "room_id",
                   "routing", "fallback_from"):
            _v = gen_meta.get(_k)
            if _v not in (None, "", [], {}):
                image_meta[_k] = _v
        post = create_post(
            character_name=character_name,
            image_filename=image_filename,
            caption=caption,
            hashtags=hashtags,
            image_prompt=final_image_prompt,
            image_meta=image_meta)

        logger.info(f"Post erstellt: {post['id']}")
        logger.info(f"Caption: {caption}")

        # Post-processing hand-off (pull model), fire-and-forget. No bytes sent.
        try:
            from app.core import postprocess_trigger
            postprocess_trigger.trigger(dst_path, "instagram")
        except Exception as _pp_err:
            logger.debug("Instagram postprocess trigger skipped: %s", _pp_err)

        # Persist the cooldown timestamp
        try:
            from datetime import datetime
            from app.models.character import get_character_skill_config, save_character_skill_config
            agent_config = get_character_skill_config(character_name, self.SKILL_ID) or {}
            agent_config["last_post_timestamp"] = utc_now_iso()
            save_character_skill_config(character_name, self.SKILL_ID, agent_config)
            logger.info("Cooldown-Timestamp gespeichert fuer %s", character_name)
        except Exception as e:
            logger.warning("Cooldown-Timestamp konnte nicht gespeichert werden: %s", e)

        logger.info("=" * 60)
        logger.info("INSTAGRAM-POST FERTIG")
        logger.info("=" * 60)

        # Set the mood from the caption sentiment
        try:
            caption_lower = caption.lower()
            mood = "inspiriert"  # default

            if any(word in caption_lower for word in ["happy", "glücklich", "joy", "freud", "laugh", "lach", "smile", "lächel"]):
                mood = "glücklich"
            elif any(word in caption_lower for word in ["beautiful", "schön", "amazing", "toll", "love", "liebe", "wonderful", "wunderbar"]):
                mood = "begeistert"
            elif any(word in caption_lower for word in ["peace", "calm", "ruhig", "zen", "relax"]):
                mood = "entspannt"
            elif any(word in caption_lower for word in ["adventure", "abenteuer", "explore", "entdecken", "journey", "reise"]):
                mood = "abenteuerlustig"
            elif any(word in caption_lower for word in ["creative", "kreativ", "art", "kunst", "imagine", "vorstell"]):
                mood = "kreativ"

            save_character_current_feeling(character_name, mood)
            logger.info(f"Stimmung gesetzt: {mood}")
        except Exception as e:
            logger.warning(f"Stimmung konnte nicht gesetzt werden: {e}")

        _tq.track_finish(_track_id)

        # Return the result
        image_url = f"/instagram/images/{image_filename}?user_id={user_id}"
        return (
            f"Instagram-Post erstellt!\n\n"
            f"![Post]({image_url})\n\n"
            f"**Caption:** {caption}\n\n"
            f"Post-ID: {post['id']}"
        )

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "relaxing at a cafe with coffee")

    def memorize_result(self, result: str, character_name: str) -> bool:
        """Store Instagram posts as memories for scheduled calls."""
        if not result or "Fehler" in result[:20] or "Error" in result[:20]:
            return False
        try:
            from app.models.memory import add_memory
            # Keep only the essential information, not the full URL.
            content = f"Ich habe einen Instagram-Post erstellt: {result[:500]}"
            add_memory(
                character_name=character_name,
                content=content,
                memory_type="episodic",
                importance=2,
                tags=["scheduler_tool", "instagram_post"],
                context="scheduler:Instagram")
            return True
        except Exception:
            return False

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description.rstrip('.')}. "
                f"Input options: "
                f"(a) JSON {{\"image_prompt\": \"...\", \"caption\": \"your caption text\"}} — "
                f"recommended, write the caption in your own voice. "
                f"(b) just the image description — caption auto-generated."
            ),
            func=self.execute)
