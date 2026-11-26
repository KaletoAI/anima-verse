"""Inventory routes: manage items, room items and character inventories."""
import io
import time
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File, Depends
from fastapi.responses import FileResponse, StreamingResponse
from typing import Dict, Any, List
from app.core.auth_dependency import get_current_user, require_admin
from app.core import users
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.models.inventory import (
    list_items, get_item, add_item, update_item, delete_item,
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
    from app.core.accessory_parts import is_part
    items = list_items()
    if include_shared:
        from app.models.inventory import list_shared_items
        for s in list_shared_items():
            items.append({**s, "_shared": True})
    # design G: a part item (buckle / pendant / charm) is marked, so pickers that put items in an inventory or on a
    # slot can leave it out
    return {"items": [{**i, "part": True} if is_part(i) else i for i in items]}


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
    from app.core import accessory_parts
    from app.models.inventory import get_item, is_shared_item, move_item_to_shared
    user_id = (body.get("user_id") or "").strip()
    # A chain or belt takes its world-local part items along, before itself (design G): a library item never links
    # a part only one world has. Each move runs under that item's own locks.
    for pid in accessory_parts.part_ids_of(get_item(item_id)):
        if get_item(pid) and not is_shared_item(pid):
            moved = move_item_to_shared(pid)
            if moved.get("status") != "ok":
                raise HTTPException(status_code=400,
                                    detail=f"part {pid}: {moved.get('reason', 'move failed')}")
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
    from fastapi.responses import JSONResponse
    from app.core import accessory_parts
    from app.core.keyed_lock import keyed_lock
    from app.models.inventory import move_item_to_world
    user_id = (body.get("user_id") or "").strip()
    with keyed_lock("accessory_part", item_id):
        # A part a library chain or belt still links stays in the library (design G) — 409 naming them.
        shared_users = [u for u in accessory_parts.used_by(item_id) if u["shared"]] \
            if accessory_parts.is_part_id(item_id) else []
        if shared_users:
            names = ", ".join(u["name"] for u in shared_users)
            return JSONResponse(status_code=409, content={
                "detail": f"The part is used by library items: {names}", "used_by": shared_users})
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
        "tracks_character", "prompt_fragment_back",
    ) if k in body}
    if _extras:
        item = update_item(item["id"], _extras) or item
    return {"ok": True, "item": item}


@router.post("/items/suggest-back-text")
def suggest_back_text_route(body: Dict[str, Any], _admin=Depends(require_admin)) -> Dict[str, Any]:
    """The Items editor's "Suggest" for an outfit piece's "Description
    (back)" (Task 11e, ``piece_back_text.suggest``): ``{prompt_fragment,
    name}`` of the form as it stands (saved or not) → ``{text, changed}``.
    Saves NOTHING — the editor puts the text into the field and the user
    saves it. ``changed`` False: the front text has no front-only or scene
    words, the field may stay empty. 400 without a front text, 502 when the
    LLM fails, is not routed or answers unusably. Admin-only (also by the
    ``/inventory/items`` write prefix)."""
    from app.core.piece_back_text import normalise, suggest
    front = normalise((body or {}).get("prompt_fragment"))
    if not front:
        raise HTTPException(status_code=400, detail="Fill in the description (front) first")
    try:
        return suggest(front, name=str((body or {}).get("name") or ""))
    except Exception as e:  # noqa: BLE001 — any LLM failure is one answer for the editor
        logger.warning("Back text suggestion failed: %s", e)
        raise HTTPException(status_code=502, detail=f"No suggestion: {e}")


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
    updates = {k: v for k, v in body.items() if k != "user_id"}
    prev = get_item(item_id) or {}
    prev_fragment = (prev.get("prompt_fragment") or "").strip()
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
    """Delete an item — and, through the artefact GC, every derived file of
    it in every character that held it (fits on every body, its outfit
    bodies and textures, its outfit renders), and its jewellery mesh store
    (``<world>/jewellery/<item>/``). A part item still linked by a chain or a
    belt is a 409 naming them (design G) — unlink it there first."""
    from fastapi.responses import JSONResponse
    from app.core import accessory_parts
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("accessory_part", item_id):
        users_of = accessory_parts.used_by(item_id) if accessory_parts.is_part_id(item_id) else []
        if users_of:
            names = ", ".join(u["name"] for u in users_of)
            return JSONResponse(status_code=409, content={"detail": f"The part is used by {names}",
                                                          "used_by": users_of})
        result = _delete_item(item_id)
    _drop_jewellery_store(item_id)
    return result


def _drop_jewellery_store(item_id: str) -> None:
    """Remove ``<world>/jewellery/<item>/`` (the item's part / drop meshes) — contained in the store, never followed
    outside it."""
    import shutil
    from app.core import accessory_pendant, media_cleanup
    try:
        d = accessory_pendant.item_dir(item_id)
    except ValueError:
        return
    if d.is_dir() and media_cleanup.contained(accessory_pendant.root(), d):
        shutil.rmtree(d, ignore_errors=True)


def _delete_item(item_id: str) -> Dict[str, Any]:
    from app.core import artefact_graph
    # Invalidate variants while the item can still be found in inventories.
    try:
        from app.core.expression_regen import invalidate_variants_for_item
        invalidate_variants_for_item(item_id)
    except Exception as e:
        logger.debug("Variant invalidation failed: %s", e)
    try:
        holders = artefact_graph.item_holders(item_id)  # before its inventory rows go
    except Exception:
        logger.exception("Item %s: holders for the artefact GC unreadable", item_id)
        holders = []
    deleted = delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    for name in holders:
        artefact_graph.collect_quietly(name, f"item {item_id} deleted")
    try:
        # A deleted feet item takes its world shoe source with it (footwear/<item>/, footwear_source.collect).
        from app.core import footwear_source
        footwear_source.collect()
    except Exception:
        logger.exception("Item %s: footwear source GC failed", item_id)
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
    # Every stored character, dormant and pooled ones included: an owner
    # that stands nowhere right now still owns the item (a dormant linked
    # body's things listed as "Owned by nobody" got deleted, 2026-11-11).
    for char in list_available_characters(include_pooled=True):
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


@router.get("/items/{item_id}/wearers")
def get_item_wearers_route(item_id: str, _admin=Depends(require_admin)) -> Dict[str, Any]:
    """The characters on the figure pipeline wearing the item (dormant and
    pooled ones included, ``figure_build.wearers``) — admin-only, it names
    other characters. ``{item_id, mode, wearers: [{name, changes,
    auto_build, hub_jobs, steps}], cost: {hub_jobs, note}}``: ``mode`` the
    item's mesh mode, ``changes`` the count of ``figure.pending_changes``,
    ``hub_jobs`` / ``steps`` the wearer's own Build cost and the labels of
    the steps it would run (``figure_build.cost``: a manual Build — a plain
    body made with older prompts and a "failed — Retry" piece included),
    ``cost`` the sum of every wearer's Build cost (``hub_jobs`` None as soon
    as one is unknown)."""
    from app.core import figure, figure_build, garment_set
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    rows, total, unknown = [], 0, []
    for name in figure_build.wearers(item_id):
        own = figure_build.cost(name)
        jobs = own.get("hub_jobs")
        rows.append({"name": name, "changes": len(figure.pending_changes(name)),
                     "auto_build": figure_build.auto_build_on(name), "hub_jobs": jobs,
                     "steps": [str(s.get("label") or "") for s in own.get("steps") or []]})
        if jobs is None:
            unknown.append(name)
        else:
            total += int(jobs)
    if unknown:
        cost = {"hub_jobs": None, "note": "cost unknown — " + ", ".join(unknown)}
    else:
        cost = {"hub_jobs": total,
                "note": figure_build.COST_NOTE.format(total=total) if rows else "nobody wears it"}
    return {"item_id": item_id, "mode": garment_set.mesh_mode_of(item) or "", "wearers": rows, "cost": cost}


@router.get("/items/{item_id}/own-mesh-files")
def get_item_own_mesh_files_route(item_id: str, _admin=Depends(require_admin)) -> Dict[str, Any]:
    """What switching the piece off its own mesh hands to the cleanup (Ruling A63,
    ``artefact_graph.own_mesh_files``): ``{item_id, mode, kind, files, bytes, hub_jobs, note, characters: [{name,
    files, bytes, hub_jobs, note}], world: {files, bytes}}``. Read-only; the Wardrobe's mode select asks before
    switching when ``files`` > 0. Admin-only — it names other characters."""
    from app.core import artefact_graph
    try:
        return artefact_graph.own_mesh_files(item_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Item not found")


@router.post("/items/{item_id}/build-wearers")
def build_item_wearers_route(item_id: str, _admin=Depends(require_admin)) -> Dict[str, Any]:
    """"Build for them": one Build per wearer (``figure_build.start``, a
    click). ``{started: {name: status}}`` — ``started`` / ``queued`` (its
    one follow-up while a Build runs) / ``current``. Admin-only (also by the
    ``/inventory/items`` write prefix)."""
    from app.core import figure_build
    if not get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"started": {name: str(figure_build.start(name, reason="build_wearers").get("status") or "")
                        for name in figure_build.wearers(item_id)}}


@router.get("/ownership")
def get_ownership_map_route() -> Dict[str, Any]:
    """Map item ids to owning characters for the item filter.

    One request instead of N calls to /items/{id}/owners. Items missing from
    the map have no owners.
    """
    from app.models.character import list_available_characters
    from app.models.inventory import _load_inventory
    ownership: Dict[str, List[str]] = {}
    # Every stored character — see get_item_owners_route.
    for char in list_available_characters(include_pooled=True):
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


def generate_item_image_sync(item_id: str, overrides: Dict[str, Any] | None = None, *, raise_errors: bool = False) -> bool:
    """Thin route-side entry point; the render lives in app.core.item_images."""
    from app.core import item_images
    return item_images.generate_item_image_sync(item_id, overrides, raise_errors=raise_errors)


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
# PART ITEMS (design G: buckle / pendant / charm of a belt or chain)
# ============================================================

@router.post("/items/{host_id}/make-part")
async def make_part_route(host_id: str, request: Request) -> Any:
    """A new part item for the chain / belt ``host_id`` — ``{role: buckle|pendant|charm, at?}`` — linked on the host
    (``accessory_parts.make_part``), never put in an inventory; then its image in the background (ONE image job,
    ``generate_item_image_sync`` with the part's own ``image_prompt``, which never carries the host text). 202
    ``{part_id, image: "queued"}``; 400 for a role the host has no place for or a full charm list."""
    import asyncio
    import threading
    from fastapi.responses import JSONResponse
    from app.core import accessory_parts
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    role = str(body.get("role") or "")
    at = str(body.get("at") or "front")
    if not get_item(host_id):
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        part_id = await asyncio.to_thread(accessory_parts.make_part, host_id, role, at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    threading.Thread(target=generate_item_image_sync, args=(part_id, {}), daemon=True,
                     name=f"item-img-{part_id[:8]}").start()
    return JSONResponse(status_code=202, content={"part_id": part_id, "image": "queued"})


@router.post("/items/{item_id}/part-mesh")
def part_mesh_route(item_id: str) -> Dict[str, Any]:
    """The part's mesh — ONE routed ``jewellery_mesh`` hub job in the background (``accessory_pendant.start``) — for a
    part item, or for earrings with a drop (their drop is meshed from their own image). ``{status: ready}`` (nothing
    spent) when the mesh of the current image exists, ``running`` while a job runs, else ``started``. 400 for any other
    item or without an image."""
    from app.core import accessory_parts, accessory_pendant, accessory_spec
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not (accessory_parts.is_part(item) or accessory_spec.pendant_on(accessory_spec.of_item(item))):
        raise HTTPException(status_code=400, detail="Only a part item (or earrings with a drop) has a part mesh")
    state = accessory_pendant.pendant_state(item_id)
    if state["state"] == "no_image":
        raise HTTPException(status_code=400, detail=accessory_pendant.REASON_NO_IMAGE)
    if state["state"] == "ready":
        return {"status": "ready"}
    if state["state"] == "running" or not accessory_pendant.start(item_id):
        return {"status": "running"}
    return {"status": "started"}


@router.get("/items/{item_id}/part-mesh")
def part_mesh_state_route(item_id: str) -> Dict[str, Any]:
    """The part's mesh state (read-only, ``accessory_pendant.pendant_state``): ``{state, reason}``."""
    from app.core import accessory_pendant
    if not get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        st = accessory_pendant.pendant_state(item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"state": st["state"], "reason": st["reason"]}


@router.get("/items/{item_id}/used-by")
def part_used_by_route(item_id: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The chains / belts that link the part ``item_id``: ``{used_by: [{item_id, name, role, shared}]}``."""
    from app.core import accessory_parts
    if not get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"used_by": accessory_parts.used_by(item_id)}


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


def _refuse_part(item_id: str) -> None:
    """400 for a part item (plan-anhaenger Task 2): it is worn through its chain or belt — never carried, placed in a
    room or put on a slot."""
    from app.core import accessory_parts
    if accessory_parts.is_part_id(item_id):
        raise HTTPException(status_code=400, detail=accessory_parts.REFUSED_WEAR)


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
    _refuse_part(item_id)

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
    _refuse_part(item_id)

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
    _refuse_part(item_id)
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


@router.get("/body-under-piece")
def body_under_piece_route() -> Dict[str, Any]:
    """Which clothing slots the item editor's "Body shape under this piece"
    controls apply to, read from the loaded packages (never a hardcoded list):

    - ``exposed_detail_slots``: slots that hide a body detail of a rig
      declaring ``exposed_only`` → ``outfit_piece.exposed_detail``.
    - ``lift_defaults``: ``{slot: default}`` from rigs declaring
      ``clothing_lift_default`` → ``outfit_piece.lift`` (placeholder = default).
    - ``motion_damping_slots``: slots covering a moving rig →
      ``outfit_piece.motion_damping``.
    - ``contact_free_slots``: slots a package's part or channel needs free
      for a contact clip (``contact_free``) → ``outfit_piece.open_below``."""
    from app.core.contact_clothing import declared_slots
    from app.core.extension_rig import clothing_lift_slots, exposed_only_slots, motion_damping_slots
    return {"exposed_detail_slots": exposed_only_slots(),
            "lift_defaults": clothing_lift_slots(),
            "motion_damping_slots": motion_damping_slots(),
            "contact_free_slots": declared_slots()}


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


@router.get("/characters/{character_name}/outfit-sets/{outfit_id}")
def preview_outfit_set_route(character_name: str, outfit_id: str,
                             _admin=Depends(require_admin)) -> Dict[str, Any]:
    """Preview a saved outfit without equipping or granting any pieces."""
    from app.core.outfit_options import clean_piece_state_map
    from app.models.character import get_character_outfits
    target = next((o for o in get_character_outfits(character_name)
                   if o.get("id") == outfit_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="outfit not found")
    pieces = []
    for item_id in target.get("pieces") or []:
        item = get_item(item_id)
        pieces.append({
            "item_id": item_id,
            "name": (item or {}).get("name", ""),
            "image": bool((item or {}).get("image")),
            "missing": item is None,
        })
    return {
        "id": target["id"],
        "name": target.get("name", ""),
        "outfit": target.get("outfit", ""),
        "pieces": pieces,
        "remove_slots": list(target.get("remove_slots") or []),
        # The saved boot hem (``outfit_options``, boots spec § 8.2): "tucked" / "over" / null (= over).
        "boot_hem": (target.get("options") or {}).get("boot_hem") if isinstance(target.get("options"), dict) else None,
        # The saved open pieces (``outfit_options.piece_state``, Addendum A): {item_id: "open"}; {} = all closed.
        "piece_state": (clean_piece_state_map((target.get("options") or {}).get("piece_state"))
                        if isinstance(target.get("options"), dict) else {}),
        # The hairstyle the set wears (hairstyles plan Task 13 / D5): its item id, "" = the hair stays as it is.
        "hairstyle": str(target.get("hairstyle") or ""),
    }


@router.delete("/characters/{character_name}/outfit-sets/{outfit_id}")
def delete_outfit_set_route(character_name: str, outfit_id: str,
                            _admin=Depends(require_admin)) -> Dict[str, Any]:
    """Remove the preset only; leave inventory and equipped pieces intact."""
    from app.core import artefact_graph
    from app.models.character import delete_character_outfit
    if not delete_character_outfit(character_name, outfit_id):
        raise HTTPException(status_code=404, detail="outfit not found")
    artefact_graph.collect_quietly(character_name, "outfit set deleted")
    return {"status": "ok", "outfit_id": outfit_id}


@router.post("/characters/{character_name}/outfit-sets/{outfit_id}/hairstyle")
async def set_outfit_set_hairstyle_route(character_name: str, outfit_id: str, request: Request,
                                         _admin=Depends(require_admin)) -> Dict[str, Any]:
    """Name the hairstyle a saved outfit set wears (plan 2026-11-12-unified-worn-pieces D5, the Wardrobe's
    set editor, Task 14). Body ``{"hairstyle": "<item id>"}``; ``""`` = the set leaves the hair as it is.
    Stores the set only — nothing is worn, nothing is built (applying the set wears it). 400 for an item
    that is no hairstyle of the character, 404 for an unknown set. ``{outfit_id, hairstyle}``."""
    import asyncio
    body = await request.json()
    hairstyle = str((body or {}).get("hairstyle") or "").strip() if isinstance(body, dict) else ""
    return await asyncio.to_thread(_set_outfit_set_hairstyle_sync, character_name, outfit_id, hairstyle)


def _set_outfit_set_hairstyle_sync(character_name: str, outfit_id: str, hairstyle: str) -> Dict[str, Any]:
    """The blocking body of ``set_outfit_set_hairstyle_route``.

    The existence check and the write sit under the ``character_profile`` lock
    that ``delete_character_outfit`` and the hairstyle delete also take: an
    unknown id makes ``add_character_outfit`` create a NEW empty set, so a set
    deleted between an unlocked check and the write came back as a phantom."""
    from app.core.garment_hair import is_hairstyle
    from app.core.keyed_lock import keyed_lock
    from app.models.character import add_character_outfit, get_character_outfits
    with keyed_lock("character_profile", character_name):
        if not any(o.get("id") == outfit_id for o in get_character_outfits(character_name)):
            raise HTTPException(status_code=404, detail="outfit not found")
        if hairstyle and not is_hairstyle(get_item(hairstyle), character_name):
            raise HTTPException(status_code=400, detail=f"{hairstyle[:80]} is no hairstyle of {character_name}")
        add_character_outfit(character_name, {"id": outfit_id, "hairstyle": hairstyle})
    return {"outfit_id": outfit_id, "hairstyle": hairstyle}


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
    from app.models.inventory import apply_equipped_pieces, outfit_set_pieces_by_slot
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

    # One declared slot per piece; apply_equipped_pieces handles all
    # mirrored slots from the item's definition.
    pieces_by_slot = outfit_set_pieces_by_slot(target)

    with keyed_lock("character_profile", character_name):
        result = apply_equipped_pieces(character_name,
            pieces=pieces_by_slot,
            remove_slots=list(target.get("remove_slots") or []),
            source="outfit_preset")
        # The set's per-outfit options come with it (boots plan Task 10): a row without them applies null.
        from app.core.outfit_options import apply_saved_options
        apply_saved_options(character_name, target)
        # The set's hairstyle (hairstyles plan Task 13 / D5) — an outfit change: ONE Build request below.
        from app.core.garment_hair import wear_outfit_hairstyle
        hair_changed = wear_outfit_hairstyle(character_name, target)
    if hair_changed:
        from app.core.garment_hair import request_outfit_build
        request_outfit_build(character_name)
    return {
        "status": "ok",
        "outfit_id": target.get("id"),
        "outfit_name": target.get("name"),
        "changed": result["changed"],
        "applied": result["applied"],
        "skipped": result["skipped"],
        "cleared": result["cleared"],
    }
