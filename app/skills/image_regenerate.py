"""Image regeneration — replaces an existing image via the core image-service pipeline.

Uses the stored prompt + an optional improvement wish, renders on the
explicitly picked backend or on the chain of the image-routing occasion, and
overwrites the file (or writes a new one next to it).
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
    source_image_path: str = "",
    occasion: str = "regenerate") -> Tuple[bool, str, str]:
    """Renders an image again. ``create_new=True`` writes a new file next to
    the source instead of overwriting it.

    Args:
        character_name: character name (empty for world images)
        output_path: the image file to overwrite (or to derive the new name from)
        original_prompt: the stored image prompt
        improvement_request: optional improvement wish (rewritten via LLM)
        backend_name: explicit — exactly this backend, no fallback; empty =
            the ``occasion`` chain of the image routing
        agent_config: per-character config (LLM override)
        occasion: the image-routing occasion rendered without an explicit
            backend — "regenerate" (gallery regenerate), "photo" (scene
            photo), "profile" (portrait re-render)

    Returns:
        (success, final_prompt, actual_output_path) — final_prompt is the
        prompt actually used.
    """
    final_prompt = original_prompt

    # 1b. Improve the prompt when the user gave feedback
    if improvement_request:
        final_prompt = enhance_prompt(final_prompt, improvement_request, agent_config)

    # 1c. Room override: drop "setting: ..." from the prompt and replace it
    # with the chosen room
    if room_id and character_name:
        import re as _re
        # Drop "setting: Meeting room (A bright meeting room ...)" or ", setting: ..."
        final_prompt = _re.sub(r',?\s*setting:\s*[^,]*(?:\([^)]*\))?', '', final_prompt).strip()
        final_prompt = _re.sub(r',\s*$', '', final_prompt).strip()
        # Insert the new room text (from the original location)
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

    # 2. Image service (core engine — wave-6 split)
    from app.imagegen.service import get_image_service
    skill = get_image_service()
    if not skill.enabled:
        raise RuntimeError("Image service not available")

    # 3. Backend: an explicit pick renders there or nowhere; no pick = the
    # occasion's chain of the image routing (built per backend in _render).
    backend = None
    if backend_name:
        backend = skill._wait_for_explicit_backend(backend_name)
        if not backend:
            raise RuntimeError(f"Backend '{backend_name}' is not available — "
                               f"no automatic fallback")
    explicit = backend is not None

    # 4. Person detection (backend-independent) ALWAYS runs when
    # character_name is present — the external post-processing needs
    # appearances to resolve the persons.
    appearances: list = []
    if character_name:
        try:
            from app.core.prompt_builder import PromptBuilder
            _regen_builder_for_appearances = PromptBuilder(character_name)
            if character_names is not None:
                _persons = _regen_builder_for_appearances.detect_persons(final_prompt, character_names=character_names)
                logger.info("Explicit character selection: %s", character_names)
            else:
                _persons = _regen_builder_for_appearances.detect_persons(final_prompt)
            if not _persons:
                _persons = _regen_builder_for_appearances.detect_persons("", character_names=[character_name])
            appearances = [{"name": p.name, "appearance": p.appearance} for p in _persons]
        except Exception as _ape:
            logger.warning("Appearance detection failed: %s", _ape)

    _attempt = {"n": 0}
    # Context for the CENTRAL logging in backend.generate() (final prompt,
    # backend, model, LoRAs, refs and duration are set by generate() itself).
    _log_meta = {"agent_name": character_name, "original_prompt": original_prompt,
                 "auto_enhance": bool(improvement_request)}

    # Track activation: the timer starts only when GPU work actually begins.
    def _activate_track(provider_name: str = ""):
        if track_id:
            try:
                from app.core.task_queue import get_task_queue
                from app.core.task_router import match_queue_name
                resolved_queue = match_queue_name(provider_name) if provider_name else ""
                get_task_queue().track_activate(track_id, queue_name=resolved_queue or "")
            except Exception:
                pass

    def _render(b) -> Dict[str, Any]:
        """Config, size, model, LoRAs, reference slots and style — for ``b``.
        The routing calls it again with the next backend after a failure, so
        nothing built for another backend is reused."""
        first = _attempt["n"] == 0
        _attempt["n"] += 1
        cfg = (skill._get_instance_config(character_name, b) if character_name
               else skill._get_backend_defaults(b))
        negative = negative_prompt_override or cfg.get("negative_prompt",
                                                       getattr(b, "negative_prompt", ""))
        params: Dict[str, Any] = {"width": cfg.get("width", getattr(b, "width", 1024)),
                                  "height": cfg.get("height", getattr(b, "height", 1024))}
        # A dialog's model name belongs to the backend it was picked for.
        if model_override and (explicit or first):
            params["model"] = model_override
            logger.info("Model override: %s", model_override)
        if loras is not None:
            if explicit:
                # An explicit dialog pick keeps the hard LoRA gate: a LoRA the
                # library does not associate with THIS backend is refused
                # before anything is queued (no cooldown, no re-run).
                from app.core.lora_library import assert_loras_allowed
                assert_loras_allowed(b, loras)
                params["lora_inputs"] = loras
            else:
                from app.core.lora_library import filter_allowed_loras, warn_dropped_loras
                kept, dropped = filter_allowed_loras(b, loras)
                if dropped:
                    warn_dropped_loras(b.name, dropped, character_name)
                params["lora_inputs"] = kept
        face_refs: Dict[str, Any] = {"reference_images": {}, "has_reference_slots": False}
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
                            logger.info("Room override image: %s", _bg.name)
                        else:
                            # The room has no dedicated images — drop the
                            # default, the background comes from the text prompt.
                            _regen_pv.ref_image_room = ""
                            logger.info("Room override [%s]: no gallery images for "
                                        "room %s — no ref_image_room (the "
                                        "background comes from the text prompt)",
                                        character_name, room_id)

                # Room reference only when selected in the dialog — otherwise free
                # the slot (e.g. for the self-reference or another person).
                if not use_room:
                    _regen_pv.ref_image_room = ""

                _ref_slots = getattr(b, "ref_slot_count", 0)
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
                                logger.info("Self-reference in slot %d: %s", _n, Path(source_image_path).name)
                                break
                        else:
                            logger.info("Self-reference: no free reference slot (max %d)", _ref_slots)

                # Inject the references directly into the generation request.
                # Backends without reference slots simply get an empty dict.
                params["reference_images"] = face_refs["reference_images"]
            except Exception as e:
                logger.warning(f"Reference resolution error: {e}")
        # Use-case style for THIS backend (the prompt is stored without affixes).
        from app.core import config as _cfg
        _ucp = _cfg.resolve_use_case_style(
            "character", backend_model=getattr(b, "model", "") or "",
            backend_family=getattr(b, "image_family", ""))
        gen_prompt = final_prompt
        if _ucp.get("prompt_style"):
            gen_prompt = f"{_ucp['prompt_style']} {gen_prompt}"
        # Negative: the call's override wins, otherwise the use case's.
        gen_neg = negative or _ucp.get("prompt_negative", "")
        logger.info("Backend=%s, prompt (clean): %s...", b.name, final_prompt[:120])
        if gen_prompt != final_prompt:
            logger.info("Prompt (with affixes): %s...", gen_prompt[:120])

        def _op(bb):
            _activate_track(getattr(bb, "name", ""))
            # EVERY render goes through the backend's GPU channel — two
            # generations must never run in parallel on one backend.
            from app.core.llm_queue import Priority
            return skill.run_on_backend_channel(
                bb, lambda: bb.generate(gen_prompt, gen_neg, params, log_meta=_log_meta),
                task_type="image_regen", agent_name=character_name,
                priority=Priority.NORMAL)
        images, used = skill.run_on_backend(b, op=_op, character_name=character_name)
        return {"images": images, "backend": used, "params": params,
                "negative": negative, "face_refs": face_refs}

    logger.info("Output: %s", output_path)

    # 5. Generate — explicit on its backend, otherwise on the occasion's chain
    import time as _time
    _gen_start = _time.time()
    from app.imagegen.routing import route_meta, run_routed
    from app.imagegen.service import render_has_reference_image
    try:
        if explicit:
            out, route = _render(backend), None
        else:
            has_ref = bool(use_source_as_reference and source_image_path) or (
                bool(character_name) and render_has_reference_image(character_name))
            out, route = run_routed(occasion, _render, character=character_name,
                                    has_ref=has_ref, pool=skill.pool)
        images, backend = out["images"], out["backend"]
        params, negative_prompt, face_refs = out["params"], out["negative"], out["face_refs"]
        _routing = route_meta(route)

        _gen_duration = _time.time() - _gen_start

        # create_new: write a new file instead of overwriting
        actual_output_path = output_path
        if create_new:
            _orig = Path(output_path)
            _suffix = _orig.suffix
            _stem = _orig.stem
            import uuid as _uuid
            _new_name = f"{_stem}_v{_uuid.uuid4().hex[:6]}{_suffix}"
            actual_output_path = str(_orig.parent / _new_name)
            logger.info(f"create_new: new image as {_new_name}")

        Path(actual_output_path).write_bytes(images[0])
        logger.info(f"Image written ({len(images[0])} bytes, {_gen_duration:.1f}s)")

        # Post-processing runs externally (pull model). The regeneration only
        # writes the image; an external service takes over the post-processing.

        # Update metadata (backend, duration)
        import os as _os
        from app.models.character import get_character_current_location
        _ref_source = params.get("reference_images") or face_refs.get("reference_images") or {}
        _ref_meta = {}
        for _rk, _rv in _ref_source.items():
            _ref_meta[_rk] = _os.path.basename(_rv) if _rv else ""
        _now_iso = utc_now_iso()

        # Load the original metadata (for location, created_at and other fields)
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

        # Location from the original meta or the passed parameter
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
            # from_character: inherited from the original meta on a regenerate
            # — otherwise the origin (e.g. "sent by an NPC to the avatar") is lost.
            "from_character": _orig_meta.get("from_character", ""),
            # Image routing record — None on an explicit render, so an
            # overwritten file loses an old marker too.
            "routing": _routing.get("routing"),
            "fallback_from": _routing.get("fallback_from"),
        }
        # create_new: the original metadata is the base, overwritten by the new values
        if create_new:
            _base_meta = dict(_orig_meta)
            # Fields that must not be carried over
            _base_meta.pop("image_filename", None)
            _base_meta.pop("image_analysis", None)
            # A re-render marker belongs to the image it was written for
            # (fallback_rerender stamps source_file on its replacement).
            _base_meta.pop("source_file", None)
            _base_meta.update(_regen_meta)
            _regen_meta = _base_meta
            # Take created_at from the original (so they sort together)
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
                logger.info("Instagram meta updated: backend=%s", backend.name)
            except Exception as meta_err:
                logger.warning("Instagram meta update failed: %s", meta_err)
        elif character_name:
            try:
                from app.models.character import add_character_image_metadata
                add_character_image_metadata(character_name, _regen_filename, _regen_meta)
                logger.info("Character image meta updated: backend=%s", backend.name)
            except Exception as meta_err:
                logger.warning("Character image meta update failed: %s", meta_err)

        # Image-prompt logging happens CENTRALLY in backend.generate()
        # (final, trigger-injected) — via log_meta on the generate call.

        # Image analysis via vision LLM (updates the metadata)
        try:
            analysis = skill._generate_image_analysis(actual_output_path, character_name)
            if analysis:
                logger.info("Image analysis: %s", analysis[:120])
                _save_analysis(actual_output_path, analysis, character_name)
            else:
                logger.warning("Image analysis empty or failed")
        except Exception as ana_err:
            logger.warning("Image analysis error: %s", ana_err)

        return True, final_prompt, actual_output_path
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        logger.debug("Traceback:", exc_info=True)
        # A failed generation goes into the image log too, so the broken
        # request is visible in the viewer (errors only). locals().get(),
        # because depending on where it broke not every variable is set yet.
        try:
            from app.utils.image_prompt_logger import log_image_prompt
            _lv = locals()
            # A routed failure names its backend on the error, not in a local.
            _bk = _lv.get("backend") or getattr(e, "backend", None)
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
            logger.debug("Failure logging (image) failed: %s", _le)
        raise
