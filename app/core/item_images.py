"""Synchronous item image generation and storage.

Renders item product images through the image-service facade and stores them
with rembg post-processing under the item's storage directory. The render call
is blocking and belongs on a background thread or queue task, never on the
event loop; ``MediaGenerationDisabled`` (and other generation errors) are
swallowed and return ``False`` unless ``raise_errors=True``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.models.inventory import get_item, replace_item_image, set_item_image_meta

logger = get_logger("item_images")


def _alpha_coverage_too_low(image_path: Path, threshold_pct: float = 5.0) -> bool:
    """True when fewer than threshold_pct pixels are visible (alpha > 32).

    Guard against rembg/u2net failing to recognize the subject and returning
    a fully transparent image.
    """
    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.mode != "RGBA":
            return False  # No alpha channel to check.
        alpha = img.getchannel("A")
        total = alpha.size[0] * alpha.size[1]
        if total == 0:
            return True
        # Histogram: pixel count per alpha value (0..255).
        hist = alpha.histogram()
        visible = sum(hist[33:])  # alpha > 32 is visible.
        return (visible / total) * 100 < threshold_pct
    except Exception:
        return False


def store_item_image(item_id: str, blob: bytes) -> str:
    """Store a finished item render and make it the item's image; returns
    the stored file name, '' when the item is gone or not writable.

    Runs after a render of minutes: the item is looked up FRESH before its
    directory is created, so a deleted item does not come back as an empty
    ``items/<id>/``. If it disappears between that check and the switch, the
    new file and the then empty directory go again."""
    item = get_item(item_id)
    if not item:
        logger.warning("Item image [%s]: item deleted during the render — "
                       "result discarded", item_id)
        return ""
    if item.get("_shared"):
        from app.core.paths import get_shared_dir
        item_dir = get_shared_dir() / "items" / item_id
    else:
        item_dir = get_storage_dir() / "items" / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{int(time.time())}.png"
    image_path = item_dir / image_name
    image_path.write_bytes(blob)
    # rembg post-process: the green prompt background + u2net cut the subject
    # out reliably on a high-contrast backdrop. Sanity check on the alpha
    # coverage — when rembg removed the subject along with the background
    # (typical for non-person subjects), the original is kept.
    try:
        from app.models.character import postprocess_outfit_image
        processed = postprocess_outfit_image(image_path)
        if processed.exists() and _alpha_coverage_too_low(processed):
            logger.warning("Item image [%s]: rembg coverage too low — keeping "
                           "the original with the green background", item_id)
            image_path = item_dir / image_name
            image_path.write_bytes(blob)
        elif processed.name != image_name:
            image_name = processed.name
    except Exception:
        pass
    # Switch to the new image and drop the one the item points at NOW (read
    # fresh under a lock — a second queued render may have replaced it).
    if not replace_item_image(item_id, image_name):
        logger.warning("Item image [%s]: item gone or not writable — "
                       "discarding %s", item_id, image_name)
        (item_dir / image_name).unlink(missing_ok=True)
        try:
            item_dir.rmdir()          # only when it is empty now
        except OSError:
            pass
        return ""
    return image_name


def generate_item_image_sync(
    item_id: str,
    overrides: Dict[str, Any] | None = None, *,
    raise_errors: bool = False) -> bool:
    """Synchronous item-image generation (for background threads).

    Without a ``backend`` override the render is the ``item`` occasion of the
    image routing (chain + re-run on the next entry after a failure); the
    item meta then carries ``routing`` (+ ``fallback_from``). A ``backend``
    override is an explicit pick: exactly that backend or nothing — False
    when it is not available (it used to fall back to the automatic pick).
    ``overrides`` comes from the Game-Admin generate-image dialog and may
    contain:
        - backend:         name/glob of an image backend (explicit pick)
        - model_override:  model name (overrides the backend default)
        - loras:           list of {name, strength} dicts
        - prompt:          full prompt (overrides the auto variant)
        - negative_prompt: negative prompt (overrides the backend default)

    The dialog's prompt and model belong to the backend the dialog showed:
    the explicit pick, or the chain's FIRST attempt. A re-run on another
    backend composes the item's own subject for that backend and drops the
    model name; dialog LoRAs not associated with that backend are dropped
    with a warning (on an explicit pick they refuse the render instead).

    ``raise_errors`` preserves generation exceptions for synchronous queue
    consumers: load must remain typed, and failures must not look successful.
    """
    overrides = overrides or {}
    item = get_item(item_id)
    if not item:
        return False
    # The item's own subject: image_prompt > prompt_fragment > name. A green
    # background + product-photo style gives rembg a high-contrast backdrop
    # to cut the subject out cleanly.
    base = (item.get("image_prompt") or "").strip()
    if not base:
        base = (item.get("prompt_fragment") or "").strip()
    if not base:
        base = (item.get("name") or item_id).strip()
    own_subject = (f"{base}, isolated object on green background, "
                   f"product photography, sharp focus, realistic")
    # A custom prompt from the dialog is LITERAL (settings_applied
    # equivalent): the style is already in it, so the composer stays out.
    custom_prompt = (overrides.get("prompt") or "").strip()
    negative_override = (overrides.get("negative_prompt") or "").strip()

    # Backend selection goes through the image-service façade — the LAST
    # holdout that fished the skill out of the skill manager broke when the
    # take_photo plugin took over SKILL_ID "image_generation" without the
    # old class API (world_ops has used get_image_service() all along).
    from app.imagegen.service import get_image_service
    from app.imagegen.routing import route_meta, run_routed
    from app.core.lora_library import LoraNotAllowedError
    img_service = get_image_service()

    # An explicit dialog pick renders there or nowhere; no pick = the "item"
    # occasion of the image routing.
    backend = None
    backend_name = (overrides.get("backend") or "").strip()
    if backend_name:
        backend = img_service._wait_for_explicit_backend(backend_name)
        if not backend:
            logger.warning("Item image [%s]: backend '%s' is not available — "
                           "no automatic fallback", item_id, backend_name)
            return False
    explicit = backend is not None
    _attempt = {"n": 0}

    def _render(b):
        """Everything backend-dependent, built FOR ``b`` — the routing calls
        it again with the next backend after a failure."""
        first = _attempt["n"] == 0
        _attempt["n"] += 1
        from app.core import config as _cfg
        _ucp = _cfg.resolve_use_case_style(
            "item", getattr(b, "image_family", "") or "",
            backend_model=getattr(b, "model", "") or "")
        compose_meta: Dict[str, Any] = {}
        if custom_prompt and (explicit or first):
            p = custom_prompt
            n = negative_override or _ucp.get("prompt_negative", "")
        else:
            from app.core.prompt_compose import compose as _compose
            composed = _compose(use_case="item", subject=own_subject, backend=b)
            p = composed.prompt
            # A dialog negative next to a dialog prompt belongs to that
            # prompt; alone it is the user's wish for any backend.
            n = (negative_override if not custom_prompt else "") or composed.negative
            compose_meta = composed.meta
            for _w in composed.warnings:
                logger.info("Prompt composer (item): %s", _w)
        # Items are generated at the backend's default resolution. The later
        # downscale pipeline shrinks the result to ui.downscale_item_max_dim.
        params: Dict[str, Any] = {"image_use_case": "item"}
        # A dialog's model name belongs to the backend it was picked for
        # (backends read params["model"]).
        _model_val = (overrides.get("model_override") or "").strip()
        if _model_val and (explicit or first):
            params["model"] = _model_val
        # LoRA overrides: list of {name|file, strength} dicts from the dialog.
        _loras = overrides.get("loras")
        if isinstance(_loras, list) and _loras:
            clean = []
            for l in _loras:
                if isinstance(l, dict):
                    _f = (l.get("name") or l.get("file") or "").strip()
                    if _f:
                        clean.append({"name": _f, "strength": float(l.get("strength") or 1.0)})
            if clean and explicit:
                # The hard gate of an explicit pick: a LoRA the library does
                # not associate with this backend refuses the render.
                from app.core.lora_library import assert_loras_allowed
                assert_loras_allowed(b, clean)
            elif clean:
                # A routed render may land on a backend the dialog did not
                # scope for: foreign entries are dropped, with one warning.
                from app.core.lora_library import (filter_allowed_loras,
                                                   warn_dropped_loras)
                clean, dropped = filter_allowed_loras(b, clean)
                if dropped:
                    warn_dropped_loras(b.name, dropped, "")
            if clean:
                params["lora_inputs"] = clean
        _log_meta = {"agent_name": item.get("name", item_id),
                     "original_prompt": p, "auto_enhance": False,
                     "compose": compose_meta or {"use_case": "item", "settings_applied": True}}

        def _op(bb):
            # EVERY backend goes through the backend's GPU channel — two
            # generations must never run in parallel on one backend.
            return img_service.run_on_backend_channel(
                bb, lambda: bb.generate(p, n, params, log_meta=_log_meta),
                task_type="item_image", agent_name=item.get("name", item_id),
                label=f"Item: {item.get('name', item_id)}")
        return img_service.run_on_backend(b, op=_op)

    try:
        if explicit:
            (images, backend), route = _render(backend), None
        else:
            (images, backend), route = run_routed("item", _render,
                                                  pool=img_service.pool)
    except LoraNotAllowedError as e:
        logger.warning("Item image [%s]: %s", item_id, e)
        return False
    except Exception as e:
        logger.error("Item image [%s] failed: %s", item_id, e)
        if raise_errors:
            raise
        return False

    image_name = store_item_image(item_id, images[0])
    if not image_name:
        return False
    # Caption data (backend + model) — like the location galleries, shown in
    # the Game-Admin as the caption under the item image — plus the routing
    # marks of a routed render.
    _model_used = (getattr(backend, 'last_used_checkpoint', '')
                   or getattr(backend, 'model', '')
                   or getattr(backend, 'checkpoint', '') or '')
    set_item_image_meta(item_id, {
        "backend": backend.name,
        "backend_type": backend.api_type,
        "model": _model_used,
        **route_meta(route),
    })
    logger.info("Item image [%s] generated: %s", item_id, image_name)
    return True
