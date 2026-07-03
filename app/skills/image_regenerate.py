"""Bild-Regenerierung — ersetzt ein bestehendes Bild ueber die ImageGenerationSkill-Pipeline.

Nutzt den gespeicherten Prompt + optionalen User-Verbesserungswunsch,
waehlt Workflow + Backend, generiert neu und ueberschreibt die Datei.
"""
import os
from pathlib import Path
from typing import Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso
logger = get_logger("image_regen")



def enhance_prompt(
    original_prompt: str,
    improvement_request: str,
    agent_config: Optional[dict] = None) -> str:
    """Verbessert einen Image-Prompt basierend auf User-Feedback via LLM.

    Returns:
        Verbesserter Prompt, oder original_prompt bei Fehler/leerem Request.
    """
    if not improvement_request or not improvement_request.strip():
        return original_prompt

    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    character_name = (agent_config or {}).get("name", "")

    system_prompt, human_msg = render_task(
        "image_prompt_improver",
        original_prompt=original_prompt,
        improvement_request=improvement_request)

    try:
        response = llm_call(
            task="image_prompt",
            system_prompt=system_prompt,
            user_prompt=human_msg,
            agent_name=character_name)
        improved = response.content.strip()
        if improved:
            logger.info(f"Verbesserter Prompt: {improved[:120]}...")
            return improved
        logger.warning("LLM gab leere Antwort, verwende Original-Prompt")
        return original_prompt
    except Exception as e:
        logger.error(f"LLM Fehler: {e}")
        return original_prompt


def _save_analysis(output_path: str, analysis: str, character_name: str) -> None:
    """Speichert die Bildanalyse in den passenden Metadaten (Instagram oder Character-Image)."""
    from pathlib import Path as _Path
    filename = _Path(output_path).name

    # Instagram-Bild?
    if "/instagram/" in output_path:
        try:
            from app.models.instagram import (
                load_image_meta, save_image_meta, load_feed, save_feed)
            # Separate Meta-Datei aktualisieren
            meta = load_image_meta(filename) or {}
            meta["image_analysis"] = analysis
            save_image_meta(filename, meta)
            # Feed-Eintrag aktualisieren (image_meta.image_analysis)
            feed = load_feed()
            for post in feed:
                if post.get("image_filename") == filename:
                    if "image_meta" in post and isinstance(post["image_meta"], dict):
                        post["image_meta"]["image_analysis"] = analysis
                    break
            save_feed(feed)
            logger.info("Bildanalyse in Instagram-Meta gespeichert")
        except Exception as e:
            logger.warning("Instagram-Meta Speichern fehlgeschlagen: %s", e)
        return

    # Character-Bild
    if character_name:
        try:
            from app.models.character import add_character_image_metadata
            add_character_image_metadata(character_name, filename, {"image_analysis": analysis})
            logger.info("Bildanalyse in Character-Image-Meta gespeichert")
        except Exception as e:
            logger.warning("Character-Image-Meta Speichern fehlgeschlagen: %s", e)


def regenerate_image(character_name: str,
    output_path: str,
    original_prompt: str,
    improvement_request: str = "",
    workflow_name: str = "",
    backend_name: str = "",
    agent_config: Optional[dict] = None,
    loras: Optional[list] = None,
    model_override: str = "",
    character_names: Optional[list] = None,
    room_id: str = "",
    location_id: str = "",
    negative_prompt_override: str = "",
    track_id: str = "",
    create_new: bool = False,
    use_room: bool = True,
    use_source_as_reference: bool = False,
    source_image_path: str = "") -> Tuple[bool, str, str]:
    """Generiert ein Bild neu. Bei create_new=True wird eine neue Datei angelegt statt zu ueberschreiben.

    Returns:
        (success, final_prompt, actual_output_path)

    Args:
        user_id: User-ID
        character_name: Character-Name (leer fuer Welt-Bilder)
        output_path: Pfad der zu ueberschreibenden Bilddatei
        original_prompt: Gespeicherter Image-Prompt
        improvement_request: Optionaler Verbesserungswunsch
        workflow_name: Legacy parameter (ComfyUI removed) — ignored
        backend_name: Optional backend name/glob (direct backend selection)
        agent_config: Per-Agent Config (fuer LLM-Override)

    Returns:
        (success, final_prompt) — final_prompt ist der tatsaechlich verwendete Prompt
    """
    final_prompt = original_prompt

    # 1b. Prompt verbessern wenn User-Feedback vorhanden
    if improvement_request:
        final_prompt = enhance_prompt(final_prompt, improvement_request, agent_config)

    # 1c. Room-Override: "setting: ..." aus Prompt entfernen und ggf. durch neuen Raum ersetzen
    if room_id and character_name:
        import re as _re
        # "setting: Meetingraum (A bright meeting room ...)" oder ", setting: ..." entfernen
        final_prompt = _re.sub(r',?\s*setting:\s*[^,]*(?:\([^)]*\))?', '', final_prompt).strip()
        final_prompt = _re.sub(r',\s*$', '', final_prompt).strip()
        # Neuen Raum-Text einfuegen (originale Location verwenden)
        from app.models.world import get_location, get_room_by_id
        from app.models.character import get_character_current_location
        _loc_id = location_id or get_character_current_location(character_name)
        if _loc_id:
            _loc_data = get_location(_loc_id)
            if _loc_data:
                _room_data = get_room_by_id(_loc_data, room_id)
                if _room_data:
                    _room_name = _room_data.get("name", "")
                    _room_desc = _room_data.get("image_prompt_day", "") or _room_data.get("description", "")
                    _setting = f", setting: {_room_name}" + (f" ({_room_desc})" if _room_desc else "")
                    final_prompt += _setting
                    logger.info("Room-Override: %s", _room_name)

    # 2. ImageGenerationSkill holen
    from app.core.dependencies import get_skill_manager
    skill_mgr = get_skill_manager()
    skill = skill_mgr.get_skill("image_generation") if skill_mgr else None
    if not skill:
        raise RuntimeError("ImageGenerationSkill nicht verfuegbar")

    # 3. Determine backend (backend-only; the ComfyUI workflow axis is gone)
    backend = None

    if workflow_name:
        logger.warning(
            "Legacy workflow selection '%s' ignoriert (ComfyUI entfernt) — "
            "Backend-Auswahl wird verwendet", workflow_name)

    if backend_name:
        # Provider selection via match glob (e.g. "Together.ai" / "Together*"),
        # resolved by availability — same as the admin default match.
        backend = skill.match_backend(backend_name)
        if not backend:
            raise RuntimeError(f"Backend '{backend_name}' nicht verfuegbar")
    else:
        backend = skill._wait_for_backend(character_name)

    if not backend:
        raise RuntimeError("Kein Backend verfuegbar")

    # 5. Config + Params
    cfg = skill._get_instance_config(character_name, backend) if character_name else skill._get_backend_defaults(backend)
    negative_prompt = negative_prompt_override or cfg.get("negative_prompt", getattr(backend, "negative_prompt", ""))

    params = {
        "width": cfg.get("width", getattr(backend, "width", 1024)),
        "height": cfg.get("height", getattr(backend, "height", 1024)),
    }
    # Model override (user selection in the dialog, highest priority) —
    # otherwise the backend's configured default model stays active.
    if model_override:
        params["model"] = model_override
        logger.info("Model-Override: %s", model_override)
    # LoRA inputs: user override from the dialog
    if loras is not None:
        params["lora_inputs"] = loras

    # 6. Resolve reference images (for the generation; no post-processing here)
    face_refs = {"reference_images": {}, "has_reference_slots": False}
    appearances: list = []

    # Person detection ALWAYS runs when character_name is present — the
    # external post-processing needs appearances to resolve the persons.
    if character_name:
        try:
            from app.core.prompt_builder import PromptBuilder
            _regen_builder_for_appearances = PromptBuilder(character_name)
            if character_names is not None:
                _persons = _regen_builder_for_appearances.detect_persons(final_prompt, character_names=character_names)
                logger.info("Explizite Character-Auswahl: %s", character_names)
            else:
                _persons = _regen_builder_for_appearances.detect_persons(final_prompt)
            if not _persons:
                _persons = _regen_builder_for_appearances.detect_persons("", character_names=[character_name])
            appearances = [{"name": p.name, "appearance": p.appearance} for p in _persons]
        except Exception as _ape:
            logger.warning("Appearance-Detection fehlgeschlagen: %s", _ape)

    if character_name:
        try:
            from app.core.prompt_builder import PromptBuilder, PromptVariables
            _regen_builder = PromptBuilder(character_name)
            # Resolve persons again for the reference slots (with ref_images etc.)
            if character_names is not None:
                persons = _regen_builder.detect_persons(final_prompt, character_names=character_names)
            else:
                persons = _regen_builder.detect_persons(final_prompt)
            if not persons:
                persons = _regen_builder.detect_persons("", character_names=[character_name])
            _regen_pv = PromptVariables(persons=persons)
            _regen_pv.ref_images = {}
            for idx, p in enumerate(persons, 1):
                ref = _regen_builder._resolve_person_ref_image(p)
                if ref:
                    _regen_pv.ref_images[idx] = ref
            _regen_builder._collect_location(_regen_pv)

            # Room override: inject the background image for the chosen room.
            # Set BEFORE resolve_reference_slots so the room lands in its
            # slot according to the priority plan.
            #
            # strict_room=True: when the chosen room has no dedicated
            # gallery images we do NOT fall back to the location default.
            # Instead ref_image_room is cleared and the background is
            # generated purely from the text prompt. Otherwise the user
            # would not notice the room change in the dialog because the
            # previously chosen default image comes back again.
            if room_id:
                from app.models.world import get_background_path
                from app.models.character import get_character_current_location
                _loc_id = location_id or get_character_current_location(character_name)
                if _loc_id:
                    _bg = get_background_path(_loc_id, room=room_id, strict_room=True)
                    if _bg and _bg.exists():
                        _regen_pv.ref_image_room = str(_bg)
                        logger.info("Room-Override Bild: %s", _bg.name)
                    else:
                        # Raum hat keine dedizierten Bilder — Default raus,
                        # Hintergrund wird aus dem Text-Prompt generiert.
                        _regen_pv.ref_image_room = ""
                        logger.info("Room-Override [%s]: keine Gallery-Bilder fuer "
                                    "Raum %s — kein ref_image_room (Hintergrund "
                                    "kommt aus dem Text-Prompt)",
                                    character_name, room_id)

            # Room reference only when selected in the dialog — otherwise free
            # the slot (e.g. for the self-reference or another person).
            if not use_room:
                _regen_pv.ref_image_room = ""

            _ref_slots = getattr(backend, "ref_slot_count", 0)
            face_refs = _regen_builder.resolve_reference_slots(_regen_pv, max_slots=_ref_slots)

            # Self-reference (current image) into the first free slot — the
            # dialog already caps the selection to the slot budget, here it
            # is only inserted when there is actually room.
            if use_source_as_reference and source_image_path:
                import re as _re
                if Path(source_image_path).exists():
                    _refs = face_refs.get("reference_images") or {}
                    _used = {int(_m.group(1)) for _k in _refs
                             if (_m := _re.match(r"input_reference_image_(\d+)$", _k))}
                    for _n in range(1, _ref_slots + 1):
                        if _n not in _used:
                            _refs[f"input_reference_image_{_n}"] = source_image_path
                            face_refs["reference_images"] = _refs
                            face_refs["has_reference_slots"] = True
                            logger.info("Selbst-Referenz in Slot %d: %s", _n, Path(source_image_path).name)
                            break
                    else:
                        logger.info("Selbst-Referenz: kein freier Ref-Slot (max %d)", _ref_slots)

            # Inject the references directly into the generation request.
            # Backends without reference slots simply get an empty dict.
            params["reference_images"] = face_refs["reference_images"]
        except Exception as e:
            logger.warning(f"Referenz-Aufloesung Fehler: {e}")

    # 6b. Apply use-case style (the prompt is stored without affixes).
    from app.core import config as _cfg
    _ucp = _cfg.resolve_use_case_style(
        "character",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    generation_prompt = final_prompt
    if _ucp.get("prompt_style"):
        generation_prompt = f"{_ucp['prompt_style']} {generation_prompt}"

    logger.info(f"Backend={backend.name}")
    logger.info(f"Prompt (clean): {final_prompt[:120]}...")
    if generation_prompt != final_prompt:
        logger.info(f"Prompt (with affixes): {generation_prompt[:120]}...")
    logger.info(f"Output: {output_path}")

    # 7. Generieren (via GPU-Queue wenn Provider zugeordnet)
    import time as _time
    _gen_start = _time.time()

    # Track-Aktivierung: Timer erst starten wenn GPU-Arbeit tatsaechlich beginnt
    def _activate_track(provider_name: str = ""):
        if track_id:
            try:
                from app.core.task_queue import get_task_queue
                from app.core.task_router import match_queue_name
                resolved_queue = match_queue_name(provider_name) if provider_name else ""
                get_task_queue().track_activate(track_id, queue_name=resolved_queue or "")
            except Exception:
                pass

    # Backend fallback engine: on a failure of the primary backend the op
    # automatically switches to the next available backend. The op callback
    # adapts generation_prompt/params per backend — important when the
    # fallback has a different api_type.
    def _build_op(_orig_prompt: str, _orig_neg: str, _orig_params: dict):
        def _op(b):
            _activate_track(getattr(b, "name", ""))
            # Use-case style per backend (family from the backend model).
            from app.core import config as _cfg
            _bucp = _cfg.resolve_use_case_style(
                "character",
                backend_model=getattr(b, "model", "") or "",
                backend_family=getattr(b, "image_family", ""))
            _gen_prompt = _orig_prompt
            if _bucp.get("prompt_style"):
                _gen_prompt = f"{_bucp['prompt_style']} {_gen_prompt}"
            # Negative: call override wins, otherwise use-case
            _gen_neg = _orig_neg or _bucp.get("prompt_negative", "")
            _bp = dict(_orig_params)
            # GPU queue for local backends, direct otherwise
            if getattr(b, "api_type", "") == "a1111":
                from app.core.llm_queue import get_llm_queue, Priority
                logger.info("GPU-Task (Backend=%s)", b.name)
                return get_llm_queue().submit_gpu_task(
                    provider_name=b.name,
                    task_type="image_regen",
                    priority=Priority.NORMAL,
                    callable_fn=lambda: b.generate(_gen_prompt, _gen_neg, _bp, log_meta=_log_meta),
                    agent_name=character_name,
                    gpu_type=b.api_type)
            return b.generate(_gen_prompt, _gen_neg, _bp, log_meta=_log_meta)
        return _op

    # Kontext fuers ZENTRALE Logging in backend.generate() (final_prompt, Backend,
    # Model, LoRAs, Refs, Dauer setzt generate() selbst).
    _log_meta = {"agent_name": character_name, "original_prompt": original_prompt,
                 "auto_enhance": bool(improvement_request)}
    try:
        _op = _build_op(final_prompt, negative_prompt, params)
        try:
            images, backend = skill.run_with_fallback(
                primary_backend=backend,
                op=_op,
                character_name=character_name)
        except RuntimeError as _fb_err:
            msg = str(_fb_err)
            logger.error("Regen Fallback-Engine: %s", msg)
            raise
        if images == "NO_NEW_IMAGE":
            msg = "Keine neuen Bilder — Seed oder Model unveraendert (Duplikat/Cache)"
            logger.warning(msg)
            raise RuntimeError(msg)
        if not images:
            msg = "Backend gab keine Bilder zurueck"
            logger.error(msg)
            raise RuntimeError(msg)

        _gen_duration = _time.time() - _gen_start

        # Bei create_new: neue Datei anlegen statt ueberschreiben
        actual_output_path = output_path
        if create_new:
            _orig = Path(output_path)
            _suffix = _orig.suffix
            _stem = _orig.stem
            import uuid as _uuid
            _new_name = f"{_stem}_v{_uuid.uuid4().hex[:6]}{_suffix}"
            actual_output_path = str(_orig.parent / _new_name)
            logger.info(f"create_new: Neues Bild als {_new_name}")

        Path(actual_output_path).write_bytes(images[0])
        logger.info(f"Bild erfolgreich geschrieben ({len(images[0])} bytes, {_gen_duration:.1f}s)")

        # Post-Processing laeuft extern (Pull-Modell). Die Regenerierung
        # schreibt nur das Bild; ein externer Dienst uebernimmt die Nachbearbeitung.

        # Update metadata (backend, duration)
        import os as _os
        from app.models.character import get_character_current_location
        _ref_source = params.get("reference_images") or face_refs.get("reference_images") or {}
        _ref_meta = {}
        for _rk, _rv in _ref_source.items():
            _ref_meta[_rk] = _os.path.basename(_rv) if _rv else ""
        _now_iso = utc_now_iso()

        # Original-Metadaten laden (fuer location, created_at und andere Felder)
        _orig_filename = Path(output_path).name
        _orig_meta = None
        if "/instagram/" in output_path:
            try:
                from app.models.instagram import load_image_meta as _load_ig_meta
                _orig_meta = _load_ig_meta(_orig_filename)
            except Exception:
                pass
        elif character_name:
            try:
                from app.models.character import _load_single_image_meta
                _orig_meta = _load_single_image_meta(character_name, _orig_filename)
            except Exception:
                pass
        _orig_meta = _orig_meta or {}

        # Location aus Original-Meta oder aus uebergebenem Parameter
        _location_val = location_id or _orig_meta.get("location", "")
        if not _location_val and character_name:
            _location_val = get_character_current_location(character_name) or ""

        _regen_meta = {
            "prompt": final_prompt,
            "negative_prompt": negative_prompt,
            "backend": backend.name,
            "backend_type": backend.api_type,
            "guidance_scale": params.get("guidance_scale"),
            "num_inference_steps": params.get("num_inference_steps") or params.get("steps"),
            "duration_s": round(_gen_duration, 1),
            "regenerated_at": _now_iso,
            "reference_images": _ref_meta,
            "character_names": character_names if character_names is not None else [p["name"] for p in appearances],
            "room_id": room_id or _orig_meta.get("room_id", ""),
            "location": _location_val,
            "seed": params.get("seed", 0),
            # Model: dialog override > backend.model > backend.last_used_checkpoint
            # — visible in the image info for cloud backends too.
            "model": (
                params.get("model")
                or getattr(backend, "model", "")
                or getattr(backend, "last_used_checkpoint", "")
                or getattr(backend, "checkpoint", "")
                or ""),
            "loras": params.get("lora_inputs", []),
            # from_character: bei Regen aus Original-Meta erben — sonst geht
            # die Herkunft (z.B. "von Diego an Avatar gesendet") verloren.
            "from_character": _orig_meta.get("from_character", ""),
        }
        # Bei create_new: alle Original-Metadaten als Basis nehmen, dann mit neuen Werten ueberschreiben
        if create_new:
            _base_meta = dict(_orig_meta)
            # Felder entfernen die nicht uebernommen werden sollen
            _base_meta.pop("image_filename", None)
            _base_meta.pop("image_analysis", None)
            _base_meta.update(_regen_meta)
            _regen_meta = _base_meta
            # created_at vom Original uebernehmen (damit sie zusammen sortiert werden)
            if _orig_meta.get("created_at"):
                _regen_meta["created_at"] = _orig_meta["created_at"]
            else:
                _regen_meta["created_at"] = _now_iso
            _regen_meta["variant_of"] = _orig_filename
        _regen_filename = Path(actual_output_path).name
        if "/instagram/" in actual_output_path:
            try:
                from app.models.instagram import load_image_meta, save_image_meta
                existing_meta = load_image_meta(_regen_filename) or {}
                existing_meta.update(_regen_meta)
                save_image_meta(_regen_filename, existing_meta)
                logger.info("Instagram-Meta aktualisiert: backend=%s", backend.name)
            except Exception as meta_err:
                logger.warning("Instagram-Meta Update fehlgeschlagen: %s", meta_err)
        elif character_name:
            try:
                from app.models.character import add_character_image_metadata
                add_character_image_metadata(character_name, _regen_filename, _regen_meta)
                logger.info("Character-Image-Meta aktualisiert: backend=%s", backend.name)
            except Exception as meta_err:
                logger.warning("Character-Image-Meta Update fehlgeschlagen: %s", meta_err)

        # Image-Prompt-Logging passiert jetzt ZENTRAL in backend.generate()
        # (final, trigger-injiziert) — via log_meta beim generate-Aufruf.

        # Bildanalyse via Vision-LLM (aktualisiert Metadaten)
        try:
            analysis = skill._generate_image_analysis(actual_output_path, character_name)
            if analysis:
                logger.info("Bildanalyse: %s", analysis[:120])
                _save_analysis(actual_output_path, analysis, character_name)
            else:
                logger.warning("Bildanalyse leer oder fehlgeschlagen")
        except Exception as ana_err:
            logger.warning("Bildanalyse-Fehler: %s", ana_err)

        return True, final_prompt, actual_output_path
    except Exception as e:
        logger.error(f"Generierung fehlgeschlagen: {e}")
        logger.debug("Traceback:", exc_info=True)
        # Fehlgeschlagene Generierung ebenfalls ins Image-Log schreiben, damit der
        # fehlerhafte Request im Viewer (Errors-only) sichtbar ist. locals().get(),
        # weil je nach Abbruchstelle noch nicht alle Variablen gesetzt sind.
        try:
            from app.utils.image_prompt_logger import log_image_prompt
            _lv = locals()
            _bk = _lv.get("backend")
            log_image_prompt(
                agent_name=_lv.get("character_name") or "",
                original_prompt=_lv.get("original_prompt") or "",
                final_prompt=_lv.get("final_prompt") or "",
                negative_prompt=_lv.get("negative_prompt") or "",
                backend_name=getattr(_bk, "name", "") or "",
                backend_type=getattr(_bk, "api_type", "") or "",
                duration_s=_lv.get("_gen_duration") or 0.0,
                error=str(e))
        except Exception as _le:
            logger.debug("Fehler-Logging (Image) fehlgeschlagen: %s", _le)
        raise
