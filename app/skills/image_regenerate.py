"""Image regeneration — replaces an existing image via the core image-service pipeline.

Uses the stored prompt + an optional improvement wish, renders on the
explicitly picked backend or on the chain of the image-routing occasion, and
overwrites the file (or writes a new one next to it).
"""
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso
logger = get_logger("image_regen")


class ExplicitBackendUnavailable(RuntimeError):
    """The explicitly picked backend is not available right now (disabled,
    offline or cooling down) — no automatic fallback. A RuntimeError, so
    every existing caller keeps treating it as a failure; a caller that can
    wait (the improvements queue) tells it apart from a defect."""



def enhance_prompt(
    original_prompt: str,
    improvement_request: str,
    agent_config: Optional[dict] = None,
    allow_general: bool = False) -> str:
    """Improve an image prompt from user feedback via the LLM.

    ``allow_general`` lets an EMPTY request through: the LLM then tidies the
    prompt for the image model without changing what it shows (the dialogs'
    "Improve prompt" button without a change wish). Without it an empty
    request returns the prompt unchanged — the regenerate path relies on that.

    Returns:
        The improved prompt, or original_prompt on an error / empty request.
    """
    improvement_request = (improvement_request or "").strip()
    if not improvement_request and not allow_general:
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
    """Store the image analysis in the matching metadata (Instagram or character image)."""
    from pathlib import Path as _Path
    filename = _Path(output_path).name

    # Instagram image?
    if "/instagram/" in output_path:
        try:
            from app.models.instagram import (
                load_image_meta, save_image_meta, load_feed, save_feed)
            # Update the separate metadata record.
            meta = load_image_meta(filename) or {}
            meta["image_analysis"] = analysis
            save_image_meta(filename, meta)
            # Update the feed entry (image_meta.image_analysis).
            feed = load_feed()
            for post in feed:
                if post.get("image_filename") == filename:
                    if "image_meta" in post and isinstance(post["image_meta"], dict):
                        post["image_meta"]["image_analysis"] = analysis
                    break
            save_feed(feed)
            logger.info("Bildanalyse in Instagram-Meta gespeichert")
        except Exception as e:
            logger.warning("Saving the Instagram meta failed: %s", e)
        return

    # Character image
    if character_name:
        try:
            from app.models.character import add_character_image_metadata
            add_character_image_metadata(character_name, filename, {"image_analysis": analysis})
            logger.info("Bildanalyse in Character-Image-Meta gespeichert")
        except Exception as e:
            logger.warning("Saving the character image meta failed: %s", e)


def _merge_regen_meta(orig_meta: Dict[str, Any], values: Dict[str, Any],
                      route_fields: Dict[str, Any], *, create_new: bool,
                      orig_filename: str, now_iso: str,
                      source_file: str = "") -> Dict[str, Any]:
    """The meta a regenerate writes for its output file — ONE dict, written
    in ONE call.

    ``values`` are the render's own fields; ``route_fields`` is
    ``routing.route_meta(route)`` (``{}`` for an explicit render). ``routing``
    and ``fallback_from`` are always set from it, so an explicit render writes
    them as None: an overwritten file loses an old marker, and a
    ``create_new`` copy does not inherit the marker of the image it was
    rendered from.

    ``create_new``: the original's meta is the base, overwritten by the new
    values; its ``source_file`` is dropped (a re-render marker belongs to the
    image it was written for). ``source_file`` names the image THIS render
    replaces (fallback_rerender) — it goes into the same write, so a crash can
    never leave a replacement without it (the candidate would then be
    rendered a second time)."""
    meta = dict(values)
    meta["routing"] = route_fields.get("routing")
    meta["fallback_from"] = route_fields.get("fallback_from")
    if create_new:
        base = dict(orig_meta or {})
        # Fields that must not be carried over
        base.pop("image_filename", None)
        base.pop("image_analysis", None)
        base.pop("source_file", None)
        base.update(meta)
        meta = base
        # created_at from the original, so they sort together
        meta["created_at"] = (orig_meta or {}).get("created_at") or now_iso
        meta["variant_of"] = orig_filename
    if source_file:
        meta["source_file"] = source_file
    return meta


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
    source_room_id: str = "",
    negative_prompt_override: str = "",
    track_id: str = "",
    create_new: bool = False,
    use_room: bool = True,
    use_source_as_reference: bool = False,
    source_image_path: str = "",
    occasion: str = "regenerate",
    source_file: str = "",
    pose_check: Optional[bool] = None,
    keep_source_references: bool = False,
    negative_prompt_extra: str = "") -> Tuple[bool, str, str]:
    """Renders an image again. ``create_new=True`` writes a new file next to
    the source instead of overwriting it.

    Args:
        character_name: character name (empty for world images)
        output_path: the image file to overwrite (or to derive the new name from)
        original_prompt: the stored image prompt
        improvement_request: optional improvement wish (rewritten via LLM)
        room_id: a room picked in the dialog — overrides the prompt's
            setting AND the room reference (strict, no location fallback)
        location_id: the location the source image was rendered at
        source_room_id: the room the source image was rendered in (its
            meta). Without a ``room_id`` override the room reference follows
            ``location_id`` + this room, never the default image of the
            character's CURRENT location.
        backend_name: explicit — exactly this backend, no fallback; empty =
            the ``occasion`` chain of the image routing
        agent_config: per-character config (LLM override)
        occasion: the image-routing occasion rendered without an explicit
            backend — "regenerate" (gallery regenerate), "photo" (scene
            photo), "profile" (portrait re-render)
        source_file: the image this render replaces (fallback_rerender) —
            written into the new file's meta in the same write
        pose_check: the dialog's pose-check override; None = the routing
            switch of ``occasion`` decides (app/imagegen/pose_check.py)
        keep_source_references: a regenerate of the image at ``output_path``
            — its people keep the reference images it was rendered with
            (outfit/nudity of THAT moment) and its room keeps its room
            reference unless the dialog picked another room
            (app/imagegen/source_refs.py). Persons the dialog adds resolve
            live. False for a NEW render (scene photo, portrait).
        negative_prompt_extra: exclusions merged once with the selected negative
            or use-case default, only for backends with a negative input.

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
            raise ExplicitBackendUnavailable(
                f"Backend '{backend_name}' is not available — no automatic fallback")
    explicit = backend is not None

    # 3b. Optional LLM pose check of the subject prompt — before routing, so
    # the LLM wait never holds a backend slot and a re-run reuses the result.
    from app.imagegen import pose_check as _pose_check
    _pre_check = final_prompt
    final_prompt, _pose_checked = _pose_check.apply(
        occasion, final_prompt, override=pose_check, character=character_name)

    # The source image's meta: location/created_at for the new meta and, on
    # a regenerate, the reference images it was rendered with.
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
    if occasion == "photo":
        # A fresh photo uses output_path as a name template, not as its source.
        _orig_meta.pop("screenshot_source", None)

    # The same composition mode handles initial uploads and gallery regenerates.
    # Resolve even when unchecked: a new variant still owns a copy of its input.
    _screenshot_source = None
    if character_name and "/instagram/" not in output_path:
        from app.core.screenshot_sources import resolve_screenshot_source
        _screenshot_source = resolve_screenshot_source(character_name, _orig_filename, _orig_meta)
    screenshot_photo = bool(use_source_as_reference and (
        _screenshot_source or (occasion == "photo" and source_image_path)))
    if screenshot_photo:
        from app.core.scene_photo import _SCREENSHOT_SENTENCE, _SCREENSHOT_NEGATIVE
        if _screenshot_source:
            source_image_path = str(_screenshot_source)
        final_prompt = final_prompt.replace(_SCREENSHOT_SENTENCE, "").strip()
        final_prompt = f"{final_prompt}\n{_SCREENSHOT_SENTENCE}".strip()
        negative_prompt_extra = f"{negative_prompt_extra}, {_SCREENSHOT_NEGATIVE}".strip(", ")
    screenshot_subjects = screenshot_photo and character_names is not None

    # Person detection is backend-independent; post-processing needs appearances.
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
            if not _persons and not screenshot_subjects:
                _persons = _regen_builder_for_appearances.detect_persons("", character_names=[character_name])
            appearances = [{"name": p.name, "appearance": p.appearance} for p in _persons]
        except Exception as _ape:
            logger.warning("Appearance detection failed: %s", _ape)

    _source_refs: Dict[str, Any] = {"persons": {}, "room": ""}
    if keep_source_references and _orig_meta and Path(output_path).exists():
        from app.imagegen.source_refs import source_references
        _source_refs = source_references(
            _orig_meta, names=[character_name, *(character_names or [])],
            location_id=location_id)
        logger.info("Source references [%s]: persons=%s room=%s", _orig_filename,
                    {n: Path(p).name for n, p in _source_refs["persons"].items()},
                    Path(_source_refs["room"]).name if _source_refs["room"] else "-")
    # A room picked in the dialog that IS the source image's room is no
    # change: the source's room reference stays.
    _source_room = str(_orig_meta.get("room_id") or source_room_id or "")
    _room_changed = bool(room_id) and room_id != _source_room

    _attempt = {"n": 0}
    # Context for the CENTRAL logging in backend.generate() (final prompt,
    # backend, model, LoRAs, refs and duration are set by generate() itself).
    _log_meta = {"agent_name": character_name, "original_prompt": original_prompt,
                 "auto_enhance": bool(improvement_request),
                 "pose_checked_from": _pre_check if _pose_checked else ""}

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
        _ref_slots = getattr(b, "ref_slot_count", 0)
        if screenshot_photo:
            # Reserve composition before resolving people. Even a failed person
            # lookup must never evict the screenshot or replace it with a room.
            if _ref_slots > 0:
                face_refs = {"reference_images": {"input_reference_image_1": source_image_path},
                             "has_reference_slots": True}
            else:
                logger.info("Screenshot photo: backend %s has no reference slots — text-only", b.name)
            params["reference_images"] = face_refs["reference_images"]
        if character_name:
            try:
                from app.core.prompt_builder import PromptBuilder, PromptVariables
                _regen_builder = PromptBuilder(character_name)
                # Resolve persons again for the reference slots (with ref_images etc.)
                if character_names is not None:
                    persons = _regen_builder.detect_persons(final_prompt, character_names=character_names)
                else:
                    persons = _regen_builder.detect_persons(final_prompt)
                if not persons and not screenshot_subjects:
                    persons = _regen_builder.detect_persons("", character_names=[character_name])
                _regen_pv = PromptVariables(persons=persons)
                _regen_pv.ref_images = {}
                for idx, p in enumerate(persons, 1):
                    # A person of the source image keeps the reference it was
                    # rendered with; anyone else resolves live.
                    # Avatars are characters too. The is_user shortcut uses a
                    # profile image; photos need the same exact-outfit resolver
                    # as NPCs, without altering the normal slot priorities.
                    ref_person = replace(p, is_user=False) if (occasion == "photo" or screenshot_photo) and p.is_user else p
                    ref = (_source_refs["persons"].get(p.name)
                           or _regen_builder._resolve_person_ref_image(ref_person))
                    if ref:
                        _regen_pv.ref_images[idx] = ref
                if not screenshot_photo:
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
                if screenshot_photo:
                    # Composition and room geometry already come from slot 1.
                    _regen_pv.ref_image_room = ""
                elif _source_refs["room"] and not _room_changed:
                    _regen_pv.ref_image_room = _source_refs["room"]
                    logger.info("Room reference of the source image: %s",
                                Path(_source_refs["room"]).name)
                elif room_id:
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
                elif location_id:
                    # No room override: the reference shows where the source
                    # image was rendered (location + room from its meta).
                    # _collect_location above resolved the character's CURRENT
                    # place, which is a different picture once it has moved.
                    from app.models.world import get_background_path
                    _bg = get_background_path(location_id, room=source_room_id)
                    _regen_pv.ref_image_room = str(_bg) if _bg and _bg.exists() else ""
                    logger.info("Room reference from the source image [%s/%s]: %s",
                                location_id, source_room_id or "-",
                                _bg.name if _bg else "none")

                # Room reference only when selected in the dialog — otherwise free
                # the slot (e.g. for the self-reference or another person).
                if not use_room:
                    _regen_pv.ref_image_room = ""

                if screenshot_photo:
                    candidates = [(p.name, _regen_pv.ref_images[idx])
                                  for idx, p in enumerate(persons, 1)
                                  if idx in _regen_pv.ref_images]
                    budget = max(0, _ref_slots - 1)
                    for slot, (_, ref) in enumerate(candidates[:budget], 2):
                        face_refs["reference_images"][f"input_reference_image_{slot}"] = ref
                    if _ref_slots > 0 and len(candidates) > budget:
                        logger.info("Screenshot photo: dropped person references (max %d slots): %s",
                                    _ref_slots, ", ".join(name for name, _ in candidates[budget:]))
                else:
                    face_refs = _regen_builder.resolve_reference_slots(_regen_pv, max_slots=_ref_slots)

                # Self-reference (current image) into the first free slot — the
                # dialog already caps the selection to the slot budget, here it
                # is only inserted when there is actually room.
                if use_source_as_reference and source_image_path and not screenshot_photo:
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
        if negative_prompt_extra and b.supports_negative_prompt:
            # Preserve the selected negative (or the photo-style default),
            # adding screenshot exclusions once, including on routed retries.
            terms = [term.strip() for term in f"{gen_neg}, {negative_prompt_extra}".split(",") if term.strip()]
            unique = {}
            for term in terms:
                unique.setdefault(term.casefold(), term)
            gen_neg = ", ".join(unique.values())
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
                "negative": gen_neg if negative_prompt_extra else negative, "face_refs": face_refs}

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

        _companion_meta = {}
        if create_new and _screenshot_source:
            from app.core.screenshot_sources import store_screenshot_source, resolve_screenshot_source
            _companion_meta["screenshot_source"] = store_screenshot_source(
                character_name, Path(actual_output_path).name, _screenshot_source)
            if screenshot_photo and "input_reference_image_1" in params.get("reference_images", {}):
                # Persist the new image's own composition path, not its parent's.
                own_source = resolve_screenshot_source(
                    character_name, Path(actual_output_path).name, _companion_meta)
                params["reference_images"]["input_reference_image_1"] = str(own_source)

        # Post-processing runs externally (pull model). The regeneration only
        # writes the image; an external service takes over the post-processing.

        # Update metadata (backend, duration)
        import os as _os
        from app.models.character import get_character_current_location
        from app.imagegen.source_refs import meta_paths as _ref_paths_meta
        _ref_source = params.get("reference_images") or face_refs.get("reference_images") or {}
        _ref_meta = {}
        for _rk, _rv in _ref_source.items():
            _ref_meta[_rk] = _os.path.basename(_rv) if _rv else ""
        _now_iso = utc_now_iso()

        # Location from the original meta or the passed parameter
        _location_val = location_id or _orig_meta.get("location", "")
        if not _location_val and character_name:
            _location_val = get_character_current_location(character_name) or ""

        _regen_values = {
            **_companion_meta,
            "prompt": final_prompt,
            "negative_prompt": negative_prompt,
            "backend": backend.name,
            "backend_type": backend.api_type,
            "guidance_scale": params.get("guidance_scale"),
            "num_inference_steps": params.get("num_inference_steps") or params.get("steps"),
            "duration_s": round(_gen_duration, 1),
            "regenerated_at": _now_iso,
            "reference_images": _ref_meta,
            "reference_paths": _ref_paths_meta(_ref_source),
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
        }
        # Image routing record (None on an explicit render) + the create_new
        # base + source_file — one dict, one write.
        _regen_meta = _merge_regen_meta(
            _orig_meta, _regen_values, _routing, create_new=create_new,
            orig_filename=_orig_filename, now_iso=_now_iso,
            source_file=source_file)
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
