"""Inventory routes: manage items, room items and character inventories."""
import io
import time
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File, Depends
from fastapi.responses import FileResponse, StreamingResponse
from typing import Dict, Any, List
from app.core.auth_dependency import get_current_user
from app.core import users
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.models.inventory import (
    list_items, get_item, add_item, update_item, delete_item,
    set_item_image_meta, replace_item_image,
    get_room_items, add_item_to_room, remove_item_from_room,
    get_character_inventory, add_to_inventory, remove_from_inventory,
    update_inventory_entry)

logger = get_logger("inventory")

router = APIRouter(prefix="/inventory", tags=["inventory"])


# ============================================================
# ITEM DEFINITIONS (world scope)
# ============================================================

@router.get("/items")
def list_items_route(include_shared: int = Query(0, description="Include shared items (1)")) -> Dict[str, Any]:
    """List all item definitions."""
    items = list_items()
    if include_shared:
        from app.models.inventory import list_shared_items
        for s in list_shared_items():
            items.append({**s, "_shared": True})
    return {"items": items}


@router.get("/items-shared")
def list_shared_items_route() -> Dict[str, Any]:
    """List all cross-world shared-library items."""
    from app.models.inventory import list_shared_items
    return {"items": list_shared_items()}


# ── Item Import / Export ──

@router.get("/items/{item_id}/export")
def export_item_route(item_id: str) -> StreamingResponse:
    """Streams a single-item ZIP (DB row + image files)."""
    from app.core.content_io import export_item_to_zip
    try:
        zip_bytes = export_item_to_zip(item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{item_id}.zip"'},
    )


@router.post("/items/export-bundle")
async def export_items_bundle_route(request: Request) -> StreamingResponse:
    """Bundle multiple items into one ZIP. Body: {"item_ids": [...]}"""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_export_items_bundle_route_sync, body)


def _export_items_bundle_route_sync(body: Any) -> StreamingResponse:
    """The blocking body of ``export_items_bundle_route`` — runs in the
    threadpool."""
    from app.core.content_io import export_items_to_bundle_zip
    ids = body.get("item_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="item_ids must be a non-empty list")
    try:
        zip_bytes = export_items_to_bundle_zip(ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    filename = f"items_bundle_{int(time.time())}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/items/import")
async def import_item_route(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Replace items with the same id"),
    target: str = Query("auto", description="Target store: auto / world / shared"),
) -> Dict[str, Any]:
    """Import a single-item or bundle ZIP. Accepts both formats."""
    from app.core.content_io import import_item_from_zip, import_bundle_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    from app.core.upload_limits import max_pack_bytes, read_upload_capped
    content = await read_upload_capped(file, max_bytes=max_pack_bytes(),
                                       what="Item ZIP")
    # Sniff manifest to decide single vs bundle.
    import zipfile, json as _json
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            manifest = _json.loads(zf.read("manifest.json"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid pack: {e}")
    pack_type = manifest.get("type")
    try:
        if pack_type == "item_bundle":
            return import_bundle_from_zip(content, target=target, overwrite=overwrite)
        if pack_type == "item":
            return import_item_from_zip(content, target=target, overwrite=overwrite)
        raise HTTPException(status_code=400, detail=f"unexpected pack type: {pack_type!r}")
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/items/{item_id}/move-to-shared")
async def move_item_to_shared_route(item_id: str, request: Request) -> Dict[str, Any]:
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_move_item_to_shared_route_sync, item_id,
                                   body)


def _move_item_to_shared_route_sync(item_id: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``move_item_to_shared_route`` — runs in the
    threadpool."""
    from app.models.inventory import move_item_to_shared
    user_id = (body.get("user_id") or "").strip()
    result = move_item_to_shared(item_id)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("reason", "move failed"))
    return result


@router.post("/items/{item_id}/move-to-world")
async def move_item_to_world_route(item_id: str, request: Request) -> Dict[str, Any]:
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_move_item_to_world_route_sync, item_id,
                                   body)


def _move_item_to_world_route_sync(item_id: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``move_item_to_world_route`` — runs in the
    threadpool."""
    from app.models.inventory import move_item_to_world
    user_id = (body.get("user_id") or "").strip()
    result = move_item_to_world(item_id)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("reason", "move failed"))
    return result


@router.get("/items/{item_id}")
def get_item_route(
    item_id: str) -> Dict[str, Any]:
    """Return a single item."""
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item": item}


@router.post("/items")
async def create_item_route(request: Request) -> Dict[str, Any]:
    """Create a new item."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_create_item_route_sync, body)


def _create_item_route_sync(body: Any) -> Dict[str, Any]:
    """The blocking body of ``create_item_route`` — runs in the threadpool."""
    user_id = body.get("user_id", "")
    name = body.get("name", "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="user_id and name required")

    try:
        item = add_item(
            name=name,
            description=body.get("description", ""),
            category=body.get("category", "tool"),
            image_prompt=body.get("image_prompt", ""),
            rarity=body.get("rarity", "common"),
            stackable=body.get("stackable", False),
            max_stack=int(body.get("max_stack", 1)),
            transferable=body.get("transferable", True),
            consumable=body.get("consumable", False),
            reveals_secret=body.get("reveals_secret"),
            properties=body.get("properties"),
            prompt_fragment=body.get("prompt_fragment", ""),
            outfit_piece=body.get("outfit_piece"),
            effects=body.get("effects"),
            item_id=(body.get("id") or "").strip(),
            owner=body.get("owner", ""),
            pages_source=body.get("pages_source", ""),
            portable=body.get("portable", True),
            extra_fields=body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Apply magic fields immediately: add_item does not accept them directly,
    # but update_item whitelists them. Creation must not lose these fields.
    _extras = {k: body[k] for k in (
        "incantation", "spell_mode", "clone_item_id",
        "success_chance", "copy_on_give",
        "success_text", "fail_text", "cast_activity",
        "anchor_item_id", "teleport_subject", "cost",
        "tracks_character",
    ) if k in body}
    if _extras:
        item = update_item(item["id"], _extras) or item
    return {"ok": True, "item": item}


@router.put("/items/{item_id}")
async def update_item_route(item_id: str, request: Request) -> Dict[str, Any]:
    """Update an item."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_update_item_route_sync, item_id, body)


def _update_item_route_sync(item_id: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``update_item_route`` — runs in the threadpool."""
    user_id = body.get("user_id", "")

    # Keep the old prompt_fragment: invalidate variants only when this value
    # changes. Their cache depends on the prompt, not the name or image.
    prev = get_item(item_id) or {}
    prev_fragment = (prev.get("prompt_fragment") or "").strip()

    updates = {k: v for k, v in body.items() if k != "user_id"}
    try:
        updated = update_item(item_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Item not found")

    new_fragment = (updated.get("prompt_fragment") or "").strip()
    if new_fragment != prev_fragment:
        try:
            from app.core.expression_regen import invalidate_variants_for_item
            invalidate_variants_for_item(item_id)
        except Exception as e:
            logger.debug("Variant invalidation failed: %s", e)
    return {"ok": True, "item": updated}


@router.delete("/items/{item_id}")
def delete_item_route(
    item_id: str) -> Dict[str, Any]:
    """Delete an item."""
    # Invalidate variants while the item can still be found in inventories.
    try:
        from app.core.expression_regen import invalidate_variants_for_item
        invalidate_variants_for_item(item_id)
    except Exception as e:
        logger.debug("Variant invalidation failed: %s", e)
    deleted = delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


@router.get("/items/{item_id}/image")
def get_item_image_route(
    item_id: str):
    """Serve an item's image."""
    item = get_item(item_id)
    if not item or not item.get("image"):
        raise HTTPException(status_code=404, detail="No image available")
    # Shared images live in shared/items/<id>; others in the world item directory.
    if item.get("_shared"):
        from app.core.paths import get_shared_dir
        item_dir = get_shared_dir() / "items" / item_id
    else:
        item_dir = get_storage_dir() / "items" / item_id
    path = item_dir / item["image"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    suffix = path.suffix.lower()
    media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
    return FileResponse(
        str(path),
        media_type=media_types.get(suffix, 'image/png'),
        headers={"Cache-Control": "no-cache"})


@router.get("/items/{item_id}/owners")
def get_item_owners_route(
    item_id: str) -> Dict[str, Any]:
    """List characters owning this item.
    Returns: {owners: [{character: str, quantity: int, equipped: bool}]}
    """
    from app.models.character import list_available_characters
    from app.models.inventory import _load_inventory
    owners = []
    for char in list_available_characters():
        try:
            inv = _load_inventory(char).get("inventory", []) or []
        except Exception:
            continue
        for entry in inv:
            if entry.get("item_id") != item_id:
                continue
            owners.append({
                "character": char,
                "quantity": int(entry.get("quantity", 1) or 1),
                "equipped": bool(entry.get("equipped", False)),
                # Giver: trace the origin for the charm/effect mechanism.
                "obtained_from": (entry.get("obtained_from") or "").strip(),
            })
            break
    owners.sort(key=lambda x: x["character"].lower())
    return {"owners": owners, "item_id": item_id}


@router.get("/ownership")
def get_ownership_map_route() -> Dict[str, Any]:
    """Map item ids to owning characters for the item filter.

    One request instead of N calls to /items/{id}/owners. Items missing from
    the map have no owners.
    """
    from app.models.character import list_available_characters
    from app.models.inventory import _load_inventory
    ownership: Dict[str, List[str]] = {}
    for char in list_available_characters():
        try:
            inv = _load_inventory(char).get("inventory", []) or []
        except Exception:
            continue
        for entry in inv:
            iid = entry.get("item_id")
            if not iid:
                continue
            chars = ownership.setdefault(iid, [])
            if char not in chars:
                chars.append(char)
    for chars in ownership.values():
        chars.sort(key=str.lower)
    return {"ownership": ownership}


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


def _store_item_image(item_id: str, blob: bytes) -> str:
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

    image_name = _store_item_image(item_id, images[0])
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


@router.post("/items/{item_id}/generate-image")
async def generate_item_image_route(item_id: str, request: Request) -> Dict[str, Any]:
    """Generates an item image — fire-and-forget.

    Returns 202 right away; the render runs in a background thread over the
    GPU queue, so the user can click several items in a row.

    Optional overrides from the Game-Admin regenerate dialog:
        backend, model_override, loras, prompt, negative_prompt

    An explicit ``backend`` that is not available is a 503 BEFORE anything
    is queued — the background thread could only log it, and the user would
    get no image and no message. (The thread checks again: the backend may
    drop out in between.)
    """
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Read body — dialog overrides; an empty body is OK (auto selection)
    overrides: Dict[str, Any] = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            for k in ("backend", "model_override",
                      "loras", "prompt", "negative_prompt"):
                if k in body:
                    overrides[k] = body[k]
    except Exception:
        pass

    backend_name = str(overrides.get("backend") or "").strip()
    if backend_name:
        from app.core.explicit_backend import require_explicit_backend_async
        await require_explicit_backend_async(backend_name)

    import threading
    threading.Thread(
        target=generate_item_image_sync,
        args=(item_id, overrides),
        daemon=True,
        name=f"item-img-{item_id[:8]}").start()
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={"status": "queued", "item_id": item_id,
                 "item_name": item.get("name", item_id),
                 "overrides_applied": list(overrides.keys())})


# ============================================================
# ROOM ITEMS
# ============================================================

@router.get("/rooms/{location_id}/{room_id}")
def list_room_items_route(
    location_id: str,
    room_id: str, user=Depends(get_current_user)) -> Dict[str, Any]:
    """List placements visible to the caller, with discovery details for admins."""
    from app.models.account import get_active_character
    from app.models.inventory import placement_visible_to, discovered_by
    admin = user.get("role") == users.ROLE_ADMIN
    avatar = "" if admin else (get_active_character() or "")
    room_items = get_room_items(location_id, room_id)
    # Enrich with item details.
    enriched = []
    for ri in room_items:
        if not admin and not placement_visible_to(avatar, location_id, room_id, ri):
            continue
        item = get_item(ri.get("item_id", ""))
        entry = {**ri}
        if admin:
            entry["discovery_difficulty"] = ri.get("discovery_difficulty", 0)
            entry["found_by"] = discovered_by(location_id, room_id, ri.get("item_id", ""))
        else:
            entry.pop("discovery_difficulty", None)
            entry.pop("found_by", None)
        if item:
            entry["item_name"] = item.get("name", "?")
            entry["item_description"] = item.get("description", "")
            entry["item_category"] = item.get("category", "")
            entry["item_image"] = item.get("image")
        enriched.append(entry)
    return {"items": enriched}


@router.post("/rooms/{location_id}/{room_id}")
async def add_room_item_route(
    location_id: str,
    room_id: str,
    request: Request) -> Dict[str, Any]:
    """Place an item in a room."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_add_room_item_route_sync, location_id,
                                   room_id, body)


def _add_room_item_route_sync(location_id: str, room_id: str,
                              body: Any) -> Dict[str, Any]:
    """The blocking body of ``add_room_item_route`` — runs in the
    threadpool."""
    user_id = body.get("user_id", "")
    item_id = body.get("item_id", "")
    if not item_id:
        raise HTTPException(status_code=400, detail="user_id and item_id required")

    success = add_item_to_room(
        location_id=location_id,
        room_id=room_id,
        item_id=item_id,
        quantity=int(body.get("quantity", 1)),
        hidden=body.get("hidden", False),
        # A hidden placement without an explicit difficulty must not be
        # visible to everyone (0); 50 is the middle of the stat scale.
        discovery_difficulty=int(body.get("discovery_difficulty",
                                          50 if body.get("hidden") else 0)),
        note=body.get("note", ""))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to place item")
    return {"ok": True}


@router.patch("/rooms/{location_id}/{room_id}/{item_id}")
async def patch_room_item_route(location_id: str, room_id: str, item_id: str,
                                request: Request) -> Dict[str, Any]:
    """Edit an existing placement without adding quantity or clearing discoveries."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_patch_room_item_route_sync,
                                   location_id, room_id, item_id, body)


def _patch_room_item_route_sync(location_id: str, room_id: str, item_id: str,
                                 body: Any) -> Dict[str, Any]:
    """Validate and serialize a placement edit with other world writers."""
    from app.models.world import (get_location_by_id, get_room_by_id,
                                  upsert_location, world_write_lock)
    from app.core import sync_topics
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected an object")
    updates = {}
    for key in ("hidden", "discovery_difficulty", "note", "quantity"):
        if key not in body:
            continue
        value = body[key]
        expected = {"hidden": bool, "discovery_difficulty": int, "note": str, "quantity": int}[key]
        if type(value) is not expected or (key == "quantity" and value < 1):
            raise HTTPException(400, f"Invalid {key}")
        updates[key] = max(0, min(999, value)) if key == "discovery_difficulty" else value
    with world_write_lock:
        location = get_location_by_id(location_id)
        room = get_room_by_id(location, room_id) if location else None
        placement = next((p for p in (room or {}).get("items", [])
                          if p.get("item_id") == item_id), None)
        if placement is None:
            raise HTTPException(404, "Item not found in room")
        visible_before = not placement.get("hidden", False)
        placement.update(updates)
        if not upsert_location(location, sync_world=False):
            raise HTTPException(400, "Failed to update placement")
        sync_topics.room_items_changed(location_id, room_id, visible_before,
                                       not placement.get("hidden", False))
    return {"ok": True}


@router.delete("/rooms/{location_id}/{room_id}/{item_id}")
def remove_room_item_route(
    location_id: str,
    room_id: str,
    item_id: str) -> Dict[str, Any]:
    """Remove an item from a room."""
    success = remove_item_from_room(location_id, room_id, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found in room")
    return {"ok": True}


# ============================================================
# CHARACTER INVENTORY
# ============================================================

@router.get("/characters/{character_name}")
def get_inventory_route(
    character_name: str,
    include_equipped: bool = Query(True, description="Include equipped items")) -> Dict[str, Any]:
    """Return a character's inventory.

    include_equipped=False excludes currently equipped pieces/items, for
    lists of items the character can still put on.
    """
    return get_character_inventory(character_name, include_equipped=include_equipped)


@router.post("/characters/{character_name}")
async def add_inventory_item_route(
    character_name: str,
    request: Request) -> Dict[str, Any]:
    """Add an item to a character's inventory."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_add_inventory_item_route_sync,
                                   character_name, body)


def _add_inventory_item_route_sync(character_name: str,
                                   body: Any) -> Dict[str, Any]:
    """The blocking body of ``add_inventory_item_route`` — runs in the
    threadpool."""
    user_id = body.get("user_id", "")
    item_id = body.get("item_id", "")
    if not item_id:
        raise HTTPException(status_code=400, detail="user_id and item_id required")

    success = add_to_inventory(
        character_name=character_name,
        item_id=item_id,
        quantity=int(body.get("quantity", 1)),
        obtained_from=body.get("obtained_from", ""),
        obtained_method=body.get("obtained_method", "manual"))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add item (inventory full or item not found)")
    return {"ok": True}


@router.put("/characters/{character_name}/{item_id}")
async def update_inventory_item_route(
    character_name: str,
    item_id: str,
    request: Request) -> Dict[str, Any]:
    """Update an inventory entry (equipped, notes)."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_update_inventory_item_route_sync,
                                   character_name, item_id, body)


def _update_inventory_item_route_sync(character_name: str, item_id: str,
                                      body: Any) -> Dict[str, Any]:
    """The blocking body of ``update_inventory_item_route`` — runs in the
    threadpool."""
    user_id = body.get("user_id", "")

    updates = {k: v for k, v in body.items() if k != "user_id"}
    success = update_inventory_entry(character_name, item_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Item not in inventory")
    return {"ok": True}


@router.delete("/characters/{character_name}/{item_id}")
def remove_inventory_item_route(
    character_name: str,
    item_id: str) -> Dict[str, Any]:
    """Remove an item from a character's inventory."""
    success = remove_from_inventory(character_name, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not in inventory")
    return {"ok": True}


@router.post("/characters/{character_name}/{item_id}/give")
async def give_inventory_item_route(
    character_name: str,
    item_id: str,
    request: Request) -> Dict[str, Any]:
    """Give an item to another character.

    Body: { user_id, to_character }
    Returns: { ok, boost, item_name, rarity }
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_give_inventory_item_route_sync,
                                   character_name, item_id, body)


def _give_inventory_item_route_sync(character_name: str, item_id: str,
                                    body: Any) -> Dict[str, Any]:
    """The blocking body of ``give_inventory_item_route`` — runs in the
    threadpool."""
    from app.models.inventory import gift_item
    user_id = body.get("user_id", "")
    to_character = (body.get("to_character") or "").strip()
    if not to_character:
        raise HTTPException(status_code=400, detail="to_character required")
    if to_character == character_name:
        raise HTTPException(status_code=400, detail="A character cannot give items to itself")
    result = gift_item(character_name, to_character, item_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to give item"))
    return {"ok": True, **result}


# ============================================================
# EQUIPMENT (outfit pieces and other equipment)
# ============================================================

@router.get("/characters/{character_name}/equipped")
def get_equipped_route(
    character_name: str) -> Dict[str, Any]:
    """Return a character's equipped pieces (slot -> item)
    and other equipped items (list).
    """
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    return {
        "equipped_pieces": get_equipped_pieces(character_name),
        "equipped_items": get_equipped_items(character_name),
    }


# POST /pieces/{slot}/color and set_equipped_piece_color were removed in step 8
# (May 2026, plan-outfit-system-rethink.md §5): item identity is unique and
# color lives in prompt_fragment.


@router.post("/characters/{character_name}/equip")
async def equip_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Equip an outfit piece or another item.

    Body: {"user_id": "...", "item_id": "..."}.
    Pieces (category=outfit_piece) fill their slots; all other items go into
    equipped_items.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_equip_route_sync, character_name, body)


def _equip_route_sync(character_name: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``equip_route`` — runs in the threadpool.

    SERIALIZED PER CHARACTER (``character_profile``): equipping reads the
    profile, changes the equipped slots and writes the whole profile back.
    Since this body runs in the threadpool the event loop no longer keeps two
    of them apart, and two equips of the same character would each read the
    pre-state — the later write silently drops the earlier piece.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.inventory import (
        get_item, equip_piece, equip_item)
    user_id = (body.get("user_id") or "").strip()
    item_id = (body.get("item_id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="user_id and item_id required")
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    with keyed_lock("character_profile", character_name):
        if item.get("category") == "outfit_piece":
            result = equip_piece(character_name, item_id, source="wardrobe_ui")
        else:
            result = equip_item(character_name, item_id, source="wardrobe_ui")
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("reason", "equip failed"))
    # Direct (UI) action is world-visible: narrator line -> others can react.
    try:
        from app.core.perception import announce_action
        announce_action(character_name,
                        f"{character_name} zieht {item.get('name') or 'etwas'} an.",
                        source="wardrobe")
    except Exception:
        pass
    return result


@router.post("/characters/{character_name}/unequip")
async def unequip_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Unequip a piece (by slot or item_id) or another equipped item.

    Body variants:
      - {"user_id": "...", "slot": "outer"} — clear the slot
      - {"user_id": "...", "item_id": "..."} — remove that item
        (searches equipped_pieces first, then equipped_items)
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_unequip_route_sync, character_name, body)


def _unequip_route_sync(character_name: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``unequip_route`` — runs in the threadpool.

    SERIALIZED PER CHARACTER (``character_profile``), same profile
    read-modify-write as ``_equip_route_sync``.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.inventory import unequip_piece, unequip_item
    user_id = (body.get("user_id") or "").strip()
    slot = (body.get("slot") or "").strip()
    item_id = (body.get("item_id") or "").strip()
    if not slot and not item_id:
        raise HTTPException(status_code=400, detail="slot or item_id required")
    with keyed_lock("character_profile", character_name):
        # First as a piece (slot or item_id), then as an equipped item.
        result = unequip_piece(character_name, slot=slot, item_id=item_id,
                               source="wardrobe_ui")
        if result.get("status") != "ok" and item_id:
            result = unequip_item(character_name, item_id, source="wardrobe_ui")
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("reason", "unequip failed"))
    # Direct (UI) action is world-visible: narrator line -> others can react.
    try:
        from app.models.inventory import get_item as _gi
        from app.core.perception import announce_action
        _nm = ((_gi(item_id) or {}).get("name") if item_id else "") or slot
        announce_action(character_name, f"{character_name} legt {_nm} ab.",
                        source="wardrobe")
    except Exception:
        pass
    return result


@router.get("/outfit-types")
def list_outfit_types_route() -> Dict[str, Any]:
    """The canonical outfit-type vocabulary — THE source for every filter UI.

    The tags were deprecated once (decency + style_hint replaced the old
    dresscode model) and came back with the coherence feature: they now say
    which pieces GO TOGETHER (app/core/outfit_coherence.py), which is a
    different job from the one they lost. The vocabulary is closed and
    enforced on every save, so a UI must read it from here instead of
    hardcoding a list that would drift.
    """
    from app.core.outfit_coherence import CANONICAL_OUTFIT_TYPES
    return {"outfit_types": list(CANONICAL_OUTFIT_TYPES)}


@router.post("/characters/{character_name}/apply-equipped")
async def apply_equipped_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Apply a piece combination directly to the profile.

    Body:
        user_id: str
        pieces: {slot: item_id} — desired state per slot
        remove_slots: [slot, ...] — slots explicitly cleared

    Occupied slots absent from pieces are also cleared: pieces describes the
    complete desired state.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_apply_equipped_route_sync, character_name,
                                   body)


def _apply_equipped_route_sync(character_name: str,
                               body: Any) -> Dict[str, Any]:
    """The blocking body of ``apply_equipped_route`` — runs in the threadpool.

    SERIALIZED PER CHARACTER (``character_profile``): the whole equipped state
    is one read-modify-write, and it races both the single-piece equips above
    and a second apply of the same character.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.inventory import apply_equipped_pieces
    user_id = (body.get("user_id") or "").strip()
    pieces = body.get("pieces") or {}
    remove_slots = body.get("remove_slots") or []
    if not isinstance(pieces, dict):
        raise HTTPException(status_code=400, detail="pieces must be {slot: item_id}")
    with keyed_lock("character_profile", character_name):
        result = apply_equipped_pieces(character_name,
            pieces=pieces, remove_slots=remove_slots,
            source="ui_wardrobe")
    return {
        "status": "ok",
        "changed": result["changed"],
        "applied": result["applied"],
        "skipped": result["skipped"],
        "cleared": result["cleared"],
    }


@router.post("/characters/{character_name}/apply-outfit-set")
async def apply_outfit_set_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Apply a saved outfit set with a piece list.

    Body: {"user_id": "...", "outfit_id": "..."} OR {"name": "..."}.

    Equip every piece in outfit.pieces[].
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_apply_outfit_set_route_sync,
                                   character_name, body)


def _apply_outfit_set_route_sync(character_name: str,
                                 body: Any) -> Dict[str, Any]:
    """The blocking body of ``apply_outfit_set_route`` — runs in the
    threadpool.

    SERIALIZED PER CHARACTER (``character_profile``) around the apply, like
    every other equip path here.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_outfits
    from app.models.inventory import apply_equipped_pieces, get_item
    outfit_id = (body.get("outfit_id") or "").strip()
    name = (body.get("name") or "").strip()
    # user_id is unused, so not required, matching equip/unequip. The admin
    # wardrobe calls without user_id.
    if not outfit_id and not name:
        raise HTTPException(status_code=400, detail="outfit_id or name required")

    outfits = get_character_outfits(character_name)
    target = None
    for o in outfits:
        if outfit_id and o.get("id") == outfit_id:
            target = o
            break
        if name and (o.get("name") or "").lower() == name.lower():
            target = o
            break
    if not target:
        raise HTTPException(status_code=404, detail="outfit not found")

    # Map preset pieces (item ids) to slot -> id. Pass one declared slot per
    # piece; apply_equipped_pieces handles all mirrored slots from its definition.
    pieces_by_slot: Dict[str, str] = {}
    for pid in (target.get("pieces") or []):
        it = get_item(pid) or {}
        slots = ((it.get("outfit_piece") or {}).get("slots") or [])
        if slots:
            pieces_by_slot[slots[0]] = pid

    with keyed_lock("character_profile", character_name):
        result = apply_equipped_pieces(character_name,
            pieces=pieces_by_slot,
            remove_slots=list(target.get("remove_slots") or []),
            source="outfit_preset")
    return {
        "status": "ok",
        "outfit_id": target.get("id"),
        "outfit_name": target.get("name"),
        "changed": result["changed"],
        "applied": result["applied"],
        "skipped": result["skipped"],
        "cleared": result["cleared"],
    }
