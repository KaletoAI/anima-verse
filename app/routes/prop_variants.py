"""Prop MODEL VARIANTS — several meshes of the same object (E2.3, 2026-08-19).

A prop used to have exactly one mesh gallery, so a scattered wood was the same
tree twenty times over. It now carries an ORDERED LIST of variants, each a
gallery of its own (own resolution tiers, own history) — see
``app/core/props.py`` for the storage and the primary-variant contract.

These routes are the variant-scoped twins of the prop gallery endpoints in
``routes/world.py``: everything under ``/world/props/{id}/variants/{i}/…``
does to ONE variant what the unqualified route does to the primary one, plus
the verbs the strip itself needs (list, add, toggle, delete) and one per field
the VARIANT owns (2026-08-25): ``/dims``, ``/description``,
``/ground-offset``, ``/markers``, ``/seasons``. One route per kind of value,
so the body shape can be read off the path. The gallery bodies and the HTTP
mapping are shared with the unqualified routes — the helpers are imported, not
copied, so a change to one answers for both.
"""
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.log import get_logger

logger = get_logger("prop_variants")

router = APIRouter(prefix="/world", tags=["world"])

#: Same ceiling as the unqualified upload route.
_PROP_MODEL_MAX_BYTES = 100 * 1024 * 1024


def _variant(prop_id: str, index: int) -> int:
    """Validate prop + variant index, or raise the 404. Returns the index."""
    from app.core.props import get_prop, list_variants
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    if not 0 <= index < len(list_variants(prop_id)):
        raise HTTPException(status_code=404, detail="Variant not found")
    return index


async def _body(request: Request) -> Dict[str, Any]:
    if (request.headers.get("content-length") or "0") == "0":
        return {}
    data = await request.json()
    return data if isinstance(data, dict) else {}


# ── The variant list itself ─────────────────────────────────────────────

@router.get("/props/{prop_id}/variants")
def prop_variants(prop_id: str) -> Dict[str, Any]:
    """The prop's model variants: ``{variants: [{index, stem, active, seasons,
    in_season, primary, tiers, has_model, model_file, model_url, signature,
    dims, dims_estimated, description, ground_offset_m, markers}], max,
    generating_variants, world_seasons, current_season}``.

    Since 2026-08-25 the variant OWNS what the object looks like, so each
    record carries one value per field and no inherited twin: ``dims`` are the
    three metres it renders at, ``description`` the subject its product shot is
    rendered from (``""`` = none, the render falls back to the prop's name),
    ``ground_offset_m`` how deep it stands (0 = on the ground) and ``markers``
    its object-local animation spots.

    ``max`` is the configured ceiling on ACTIVE variants
    (``image_generation.prop_variant_max``) — the strip greys its "add" action
    out with it instead of letting the server refuse.

    ``generating_variants`` are the STORE indices with a run in flight, so the
    strip knows which chip is busy the moment it loads; while a run lasts the
    admin gets the same list from the polled ``GET /world/props``.

    ``world_seasons`` are the season NAMES this world runs on and
    ``current_season`` the one it is in right now (E2c) — the season chips are
    a pick from that list, never free text, and the server sends it so the
    strip does not have to fetch the calendar itself. Empty list = a world
    without seasons, and then the chips stay away: the tags would be inert."""
    from app.core.game_time import get_calendar
    from app.core.props import (get_prop, list_variants, pending_variants,
                                variant_max)
    from app.core.timeutils import game_time
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    cal = get_calendar()
    try:
        current = (cal.seasons[game_time().parts(cal).season_index].name
                   if cal.seasons else "")
    except Exception:
        current = ""
    return {"variants": list_variants(prop_id), "max": variant_max(),
            "generating_variants": pending_variants(prop_id).get(prop_id, []),
            "world_seasons": [s.name for s in cal.seasons],
            "current_season": current}


@router.post("/props/{prop_id}/variants")
async def prop_variant_add(prop_id: str, request: Request) -> Dict[str, Any]:
    """Append a variant slot (body: ``{from?: <store index>}``). 409 when the
    active cap is reached — the next generation would fill this slot, so
    refusing it is the honest answer rather than silently generating into the
    last variant.

    The slot carries no mesh and no image yet, but it is not blank: size,
    subject, ground offset and markers are COPIED from the variant ``from``
    names — the one the admin has open — and from the PRIMARY variant when the
    body names none. A version of an object is authored by EDITING the one
    beside it, not by re-typing everything."""
    from app.core.props import add_variant, get_prop, variant_max
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    index = add_variant(prop_id, (await _body(request)).get("from"))
    if index < 0:
        raise HTTPException(
            status_code=409,
            detail=f"At most {variant_max()} active variants per prop")
    return {"status": "ok", "index": index}


@router.post("/props/{prop_id}/variants/{index}/active")
async def prop_variant_active(prop_id: str, index: int,
                              request: Request) -> Dict[str, Any]:
    """Switch one variant on or off (body: ``{active: bool}``). Switching the
    LAST active one off is refused with a 409: a prop that renders nothing is
    the ``__none__`` selection sentinel's job, not a toggle's. A variant with a
    generation in flight is refused too, with its own reason."""
    from app.core.props import set_variant_active, variant_generating
    _variant(prop_id, index)
    active = bool((await _body(request)).get("active", True))
    if variant_generating(prop_id, index):
        raise HTTPException(
            status_code=409,
            detail="This variant is generating right now")
    if not set_variant_active(prop_id, index, active):
        raise HTTPException(status_code=409,
                            detail="A prop needs at least one active variant")
    return {"status": "ok", "index": index, "active": active}


@router.post("/props/{prop_id}/variants/{index}/seasons")
async def prop_variant_seasons(prop_id: str, index: int,
                               request: Request) -> Dict[str, Any]:
    """Tag one variant with the seasons it depicts (body: ``{seasons: [name,
    …]}``; ``[]`` clears the tag).

    An in-season variant renders, an out-of-season one does not — that is the
    whole rule (E2c). Never refused for a running generation: a tag moves no
    file and renumbers nothing. The answer carries the SANITIZED list, so the
    strip shows what was really stored."""
    from app.core.props import list_variants, set_variant_seasons
    _variant(prop_id, index)
    body = await _body(request)
    if not set_variant_seasons(prop_id, index, body.get("seasons")):
        raise HTTPException(status_code=404, detail="Variant not found")
    return {"status": "ok", "index": index,
            "seasons": list_variants(prop_id)[index]["seasons"]}


@router.post("/props/{prop_id}/variants/{index}/dims")
async def prop_variant_dims(prop_id: str, index: int,
                            request: Request) -> Dict[str, Any]:
    """Set this variant's real size (body: ``{width_m?, depth_m?, height_m?}``).

    A variant is a whole version of the object, and versions differ in size —
    a sapling beside the grown pine. Only the keys the body names are touched,
    so the three inputs of the strip can be committed one at a time; a null /
    empty / unusable value LEAVES THE CURRENT ONE STANDING, because there is
    nothing to inherit and a variant with no size is not a state a payload may
    carry. Storing a size clears this variant's ``dims_estimated``. Never
    refused for a running generation: a size moves no file and renames no stem.

    The answer carries what was really stored, so the strip re-renders from
    the server's own numbers."""
    from app.core.props import list_variants, set_variant_dims
    _variant(prop_id, index)
    body = await _body(request)
    if not set_variant_dims(prop_id, index, body):
        raise HTTPException(status_code=404, detail="Variant not found")
    entry = list_variants(prop_id)[index]
    return {"status": "ok", "index": index, "dims": entry["dims"],
            "dims_estimated": entry["dims_estimated"]}


@router.post("/props/{prop_id}/variants/{index}/description")
async def prop_variant_description(prop_id: str, index: int,
                                   request: Request) -> Dict[str, Any]:
    """Give one variant its OWN generation subject (body:
    ``{description: str}``; blank clears it and a render of this variant
    composes from the prop's NAME).

    A sibling verb rather than a field of the ``/dims`` patch, for the same
    reason ``/seasons`` is one: that route's whole contract is "numbers,
    clamped to (0, 100], every key optional", and a free-text field with its
    own sanitation and its own clearing rule inside it would make the body
    shape a union nobody can read off the path. One verb, one kind of value.

    Never refused for a running generation: the text is read when a render
    starts, so changing it now touches nothing in flight."""
    from app.core.props import list_variants, set_variant_description
    _variant(prop_id, index)
    body = await _body(request)
    if not set_variant_description(prop_id, index, body.get("description")):
        raise HTTPException(status_code=404, detail="Variant not found")
    entry = list_variants(prop_id)[index]
    return {"status": "ok", "index": index,
            "description": entry["description"]}


@router.post("/props/{prop_id}/variants/{index}/ground-offset")
async def prop_variant_ground_offset(prop_id: str, index: int,
                                     request: Request) -> Dict[str, Any]:
    """How deep THIS variant stands in the ground (body:
    ``{ground_offset_m: float}``, ± 5 m in centimetre steps).

    Negative sinks the mesh, positive lifts it, and it applies WHEREVER this
    version stands: manual placements, room and yard scatter, painted terrain
    scatter, world props. The default 0.0 — and every junk value — clears the
    key: "stands on the ground" is stored as absence and in no other shape, so
    no payload carries a zero for it. The per-placement ``offset_y`` in the
    room editor stays the trim of ONE instance on top of this.

    Its own verb next to ``/dims`` for the same reason ``/description`` is one:
    one route, one kind of value, one clearing rule. Never refused for a
    running generation — a sink moves no file and renames no stem."""
    from app.core.props import list_variants, set_variant_ground_offset
    _variant(prop_id, index)
    body = await _body(request)
    if not set_variant_ground_offset(prop_id, index,
                                     body.get("ground_offset_m")):
        raise HTTPException(status_code=404, detail="Variant not found")
    entry = list_variants(prop_id)[index]
    return {"status": "ok", "index": index,
            "ground_offset_m": entry["ground_offset_m"]}


@router.post("/props/{prop_id}/variants/{index}/markers")
async def prop_variant_markers(prop_id: str, index: int,
                               request: Request) -> Dict[str, Any]:
    """Replace THIS variant's object-local marker list (body: ``{markers:
    [{animation, at: [u,v,w], facing?}]}``) — same vocabulary as room markers,
    object-local frame.

    ``at`` are fractions of THIS variant's mesh bounding box, which is why the
    list belongs to the variant and to no other: a seat authored on the grown
    chair sits somewhere else on the broken one. An empty list clears the key.

    The answer carries the SANITIZED list, so the editor re-renders from what
    was really stored (invalid entries are dropped individually, the list is
    capped at 50)."""
    from app.core.props import list_variants, set_variant_markers
    _variant(prop_id, index)
    body = await _body(request)
    if not set_variant_markers(prop_id, index, body.get("markers")):
        raise HTTPException(status_code=404, detail="Variant not found")
    entry = list_variants(prop_id)[index]
    return {"status": "ok", "index": index, "markers": entry["markers"]}


@router.delete("/props/{prop_id}/variants/{index}")
def prop_variant_delete(prop_id: str, index: int) -> Dict[str, Any]:
    """Remove one variant WITH its stored meshes. Refused for the last
    remaining variant, and while THIS variant is generating."""
    from app.core.props import delete_variant, variant_generating
    _variant(prop_id, index)
    if variant_generating(prop_id, index):
        raise HTTPException(
            status_code=409,
            detail="This variant is generating right now")
    if not delete_variant(prop_id, index):
        raise HTTPException(status_code=409,
                            detail="A prop needs at least one variant")
    return {"status": "deleted", "index": index}


# ── One variant's gallery (twins of the unqualified prop routes) ─────────

@router.get("/props/{prop_id}/variants/{index}/models")
def prop_variant_models(prop_id: str, index: int) -> Dict[str, Any]:
    """One variant's mesh gallery — same shape as
    ``GET /world/props/{id}/models``, scoped to this variant."""
    from app.core.props import get_model_info
    return get_model_info(prop_id, _variant(prop_id, index))


@router.post("/props/{prop_id}/variants/{index}/models/select")
async def prop_variant_model_select(prop_id: str, index: int,
                                    request: Request) -> Dict[str, Any]:
    """Make a stored mesh the ACTIVE one of a resolution tier IN THIS VARIANT
    (body: ``{file, tier?}``)."""
    from app.core.props import select_model
    from app.routes.world import _tier
    _variant(prop_id, index)
    data = await _body(request)
    filename = str(data.get("file") or "").strip()
    tier = _tier(data.get("tier"))
    if not select_model(prop_id, filename, tier=tier, variant=index):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"status": "success", "active": filename, "tier": tier}


@router.delete("/props/{prop_id}/variants/{index}/models")
def prop_variant_model_delete(prop_id: str, index: int,
                              file: str = "") -> Dict[str, Any]:
    """Remove ONE stored mesh of this variant (``?file=``) or all of them."""
    from app.core.props import delete_model
    _variant(prop_id, index)
    return {"status": "success",
            "removed": delete_model(prop_id, file.strip(), variant=index)}


@router.get("/props/{prop_id}/variants/{index}/models/files/{filename}")
def prop_variant_model_file(prop_id: str, index: int, filename: str,
                            request: Request):
    """Serve ONE stored mesh of this variant by filename (admin preview)."""
    from app.core.http_files import etag_file_response
    from app.core.props import model_file_path
    _variant(prop_id, index)
    p = model_file_path(prop_id, filename, variant=index)
    if not p:
        raise HTTPException(status_code=404, detail="Model not found")
    return etag_file_response(p, request, "model/gltf-binary")


@router.post("/props/{prop_id}/variants/{index}/models/shrink")
async def prop_variant_model_shrink(prop_id: str, index: int,
                                    request: Request) -> Dict[str, Any]:
    """Reduce a stored mesh of THIS variant to its low tier (mesh→mesh)."""
    from app.core.props import model_file_path, trigger_shrink
    from app.routes.world import _shrink_body, _shrink_start
    _variant(prop_id, index)
    body = _shrink_body(await request.json())
    if not model_file_path(prop_id, body["source_file"], variant=index):
        raise HTTPException(status_code=404, detail="Model not found")
    return _shrink_start(trigger_shrink, prop_id, variant=index, **body)


@router.post("/props/{prop_id}/variants/{index}/models/lod")
def prop_variant_model_lod(prop_id: str, index: int,
                           ratio: float = 0) -> Dict[str, Any]:
    """Build THIS variant's distance mesh from its full mesh (Blender, CPU)."""
    from app.core.props import build_low_tier
    from app.routes.world import _lod_result
    _variant(prop_id, index)
    # `_lod_result` forwards only `ratio`/`force` to the builder (it serves
    # locations and characters too), so the variant is bound here instead of
    # widening a helper three other routes share.
    return _lod_result(
        lambda pid, **kw: build_low_tier(pid, variant=index, **kw),
        prop_id, ratio=ratio, kind="prop")


@router.post("/props/{prop_id}/variants/{index}/upload")
async def prop_variant_upload(prop_id: str, index: int,
                              file: UploadFile = File(...),
                              tier: str = Form(""),
                              force: str = Form("")) -> Dict[str, Any]:
    """Upload a GLB as a new mesh of THIS variant (same validation and the
    same ``force`` escape hatch as the unqualified upload route)."""
    from app.core.model_validate import validate_static_glb
    from app.core.props import save_uploaded_glb
    from app.routes.world import _tier
    _variant(prop_id, index)
    contents = await file.read()
    if len(contents) > _PROP_MODEL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Model too large")
    result = validate_static_glb(contents)
    forced = str(force or "").strip().lower() in ("1", "true", "yes")
    if not result["ok"] and not forced:
        raise HTTPException(status_code=422, detail={
            "reason": "invalid_model",
            "errors": result["errors"],
            "warnings": result["warnings"],
        })
    if not save_uploaded_glb(prop_id, contents, _tier(tier), variant=index):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "ok", "warnings": result["warnings"]}


@router.post("/props/{prop_id}/variants/{index}/source")
async def prop_variant_source_upload(prop_id: str, index: int,
                                     file: UploadFile = File(...)
                                     ) -> Dict[str, Any]:
    """Upload THIS variant's product-shot image — the picture its re-mesh
    works from. The image belongs to the variant like its meshes do, so an
    upload here can never overwrite another version's picture."""
    from app.routes.world import _prop_source_upload
    return await _prop_source_upload(prop_id, file, _variant(prop_id, index))


@router.post("/props/{prop_id}/variants/{index}/generate")
async def prop_variant_generate(prop_id: str, index: int,
                                request: Request) -> Dict[str, Any]:
    """Run the source→mesh chain INTO THIS VARIANT — the "re-mesh" path.

    Same body as ``POST /world/props/{id}/generate``; the difference is the
    target: the unqualified route APPENDS a variant (that is the plain
    "generate another one" button), this one refines the variant the admin has
    open, so a better bake replaces the mesh it is meant to replace.

    The variant owns its SOURCE IMAGE as well, so all three modes stay inside
    it: ``image_only`` re-renders this variant's picture and no other,
    ``mesh_only`` meshes this variant's picture, and the full chain does both.
    """
    from app.core.props import trigger_generation
    from app.routes.world import _mesh_int, _tier
    _variant(prop_id, index)
    data = await _body(request)
    if bool(data.get("mesh_only")) and bool(data.get("image_only")):
        raise HTTPException(status_code=400,
                            detail="mesh_only and image_only are exclusive")
    started = trigger_generation(
        prop_id,
        prompt=str(data.get("prompt") or ""),
        negative=str(data.get("negative") or ""),
        image_backend_glob=str(data.get("image_backend") or "").strip(),
        mesh_backend_glob=str(data.get("mesh_backend") or "").strip(),
        face_num=_mesh_int(data.get("face_num")) or None,
        texture_size=_mesh_int(data.get("texture_size")) or None,
        mesh_only=bool(data.get("mesh_only")),
        image_only=bool(data.get("image_only")),
        tier=_tier(data.get("tier")),
        lod_faces=_mesh_int(data.get("lod_faces")) or None,
        variant=index)
    return {"status": "generating" if started else "already_running"}
