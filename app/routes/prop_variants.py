"""Prop MODEL VARIANTS — several meshes of the same object (E2.3, 2026-08-19).

A prop used to have exactly one mesh gallery, so a scattered wood was the same
tree twenty times over. It now carries an ORDERED LIST of variants, each a
gallery of its own (own resolution tiers, own history) — see
``app/core/props.py`` for the storage and the primary-variant contract.

Everything under ``/world/props/{id}/variants/{i}/…`` addresses ONE variant:
its mesh gallery (list, select, upload, shrink, LOD, delete, serve), its
source images per view, its own generate run, plus the verbs the strip itself
needs (list, add, toggle, delete). THE MESH GALLERY IS ADDRESSED HERE AND
NOWHERE ELSE (2026-09-21): the unqualified shorthands for the primary variant
that used to sit in ``routes/world.py`` are gone, because a panel that used
them would silently edit variant 1 while the admin looks at variant 3. The
gallery bodies and the HTTP mapping still share their helpers with
``routes/world.py`` — they are imported, not copied.

PICTURE VARIANTS (spec-picture-props.md § 5, 2026-08-27) are three more verbs
of the same list: ``POST /variants/picture`` appends a variant that carries a
COPY of the frame's mesh and the pictures on it, ``POST
/variants/{i}/slot-values`` re-hangs them, ``POST /variants/{i}/recopy`` takes
the frame again after it was re-split. All three are admin-only and answer 400
with the store's own reason — the Areas tab shows it verbatim.

THE PER-FIELD VARIANT ROUTES ARE GONE (2026-09-21): ``/dims``,
``/description``, ``/ground-offset``, ``/markers``, ``/seasons`` and
``/face-targets`` wrote the very fields the batch save owns, but without its
"everything is checked before anything is written" rule — two ways in, one of
them laxer. The one way in is ``POST /world/props/{id}/bulk``
(``props.bulk_update``), one request and one sidecar write for the whole prop;
its appliers ARE the bodies those routes used to have. ``/area-defaults``,
``/slot-values`` and ``/picture`` stay: they are the picture-prop verbs the
Areas tab calls and the batch does not carry them.
"""
from typing import Any, Dict

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)

from app.core.auth_dependency import require_admin
from app.core.log import get_logger

from app.core.scene_recipe import invalidate_prop_lib_token

logger = get_logger("prop_variants")

router = APIRouter(prefix="/world", tags=["world"])


def _variant(prop_id: str, index: int) -> int:
    """Validate prop + variant index, or raise the 404. Returns the index."""
    from app.core.props import read_sidecar, _variant_list
    meta = read_sidecar(prop_id, read_only=True)
    if not meta:
        raise HTTPException(status_code=404, detail="Prop not found")
    if not 0 <= index < len(_variant_list(meta)):
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
    dims, dims_estimated, description, ground_offset_m, markers, slot_values,
    label, stale}], max, generating_variants, world_seasons,
    current_season}``.

    ``slot_values`` / ``label`` / ``stale`` are the picture half
    (spec-picture-props.md § 1): what this variant shows in the prop's picture
    areas, the name it is listed under, and whether its COPIED frame predates
    the mesh the prop shows now — the tab's "Re-copy mesh" runs on that flag.

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
    prop = get_prop(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    cal = get_calendar()
    try:
        current = (cal.seasons[game_time().parts(cal).season_index].name
                   if cal.seasons else "")
    except Exception:
        current = ""
    return {"variants": list_variants(prop_id), "max": variant_max(),
            "revision": prop["revision"],
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
    result_payload = {"status": "ok", "index": index}
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/picture")
async def prop_variant_add_picture(
        prop_id: str, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """HANG A PICTURE (spec-picture-props.md § 1, D2) — body
    ``{slot_values: {"<area id>": {"image"|"preset": …}}, label?}``.

    A picture assignment is a VARIANT of the frame prop, not a property of the
    placement and not a prop of its own: the new variant carries a COPY of the
    primary variant's mesh (its ``.areas.json`` companion and its source image
    with it) and shows the pictures on top. The answer is the finished variant
    record, so the strip can render the new chip without a second request.

    ``label`` is optional: omitted (or ``null``) it is DERIVED from the
    picture file names, any text is stored verbatim (R10).

    400 for everything the store refuses with a reason the tab can show: an
    unknown area, an EMPTY assignment (that is a plain model variant, not a
    picture one), a URL that is not one of this world's two galleries, a
    preset on a picture panel (or a picture on a pane) and the reached variant
    cap (R5). Nothing is created for any of them."""
    from app.core.props import add_picture_variant, get_prop, list_variants
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    body = await _body(request)
    try:
        index = add_picture_variant(prop_id, body.get("slot_values"),
                                    body.get("label")
                                    if "label" in body else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    result_payload = {"status": "ok", "index": index,
            "variant": list_variants(prop_id)[index]}
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/{index}/slot-values")
async def prop_variant_slot_values(
        prop_id: str, index: int, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """WHAT this variant shows in the prop's picture areas — body
    ``{slot_values: {…}, label?}``; an EMPTY object clears both and the
    variant stops being a picture variant.

    The values are checked against the prop's real areas: the area has to
    exist, a ``picture`` panel takes an image URL of this world and a
    ``glass`` one a preset from ``SLOT_PRESETS``. Anything else is a 400 and
    nothing is written — this is the ONE gate, the scene recipe reads what is
    stored verbatim.

    ``label`` is three-valued (R10): OMITTED from the body (or ``null``) keeps
    the stored name — re-hanging a picture must not rename the variant behind
    the admin's back — ``""`` re-derives it from the new picture file names,
    and any text is stored verbatim.
    """
    from app.core.props import list_variants, set_variant_slot_values
    _variant(prop_id, index)
    body = await _body(request)
    try:
        # `None` when the body does not mention the label at all — the store
        # then keeps the stored name (R10); an explicit "" re-derives it.
        stored = set_variant_slot_values(prop_id, index,
                                         body.get("slot_values"),
                                         body.get("label")
                                         if "label" in body else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not stored:
        raise HTTPException(status_code=404, detail="Variant not found")
    entry = list_variants(prop_id)[index]
    result_payload = {"status": "ok", "index": index,
            "slot_values": entry["slot_values"], "label": entry["label"]}
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/{index}/area-defaults")
async def prop_variant_area_defaults(
        prop_id: str, index: int, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """What this variant shows in its PANES when nobody hung anything — body
    ``{area_defaults: {"<area id>": {"preset": "glass"}}}``; an EMPTY object
    clears them (spec-bild-props-v2.md E1: the defaults describe ONE
    variant's mesh, so they live on the variant like its ``slot_values``).

    Checked against THAT variant's file areas: the area has to exist on its
    active full mesh and be a ``glass`` one, the preset one of
    ``SLOT_PRESETS``. Anything else is a 400 and nothing is written."""
    from app.core.props import set_variant_area_defaults
    _variant(prop_id, index)
    body = await _body(request)
    try:
        entry = set_variant_area_defaults(prop_id, index,
                                          body.get("area_defaults"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if entry is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    result_payload = {"status": "ok", "index": index,
            "area_defaults": entry["area_defaults"], "variant": entry}
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/{index}/recopy")
def prop_variant_recopy(
        prop_id: str, index: int,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Take the frame again (ruling R4): copy the PRIMARY variant's current
    mesh into this picture variant, keeping its ``slot_values``.

    The answer to the strip's "variants outdated" — a re-split frame leaves
    every copy behind, and this is how they catch up. 400 for the primary
    variant itself (it IS the source), 409 while this variant is generating:
    the run is about to write the very file the copy lands in (the store
    refuses it a second time, so a race cannot slip past this check)."""
    from app.core.props import (list_variants, recopy_variant_mesh,
                                variant_generating)
    _variant(prop_id, index)
    if variant_generating(prop_id, index):
        raise HTTPException(status_code=409,
                            detail="This variant is generating right now")
    try:
        done = recopy_variant_mesh(prop_id, index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not done:
        raise HTTPException(status_code=404, detail="Variant not found")
    result_payload = {"status": "ok", "index": index,
            "variant": list_variants(prop_id)[index]}
    invalidate_prop_lib_token()
    return result_payload


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
    result_payload = {"status": "ok", "index": index, "active": active}
    invalidate_prop_lib_token()
    return result_payload


@router.delete("/props/{prop_id}/variants/{index}")
def prop_variant_delete(prop_id: str, index: int) -> Dict[str, Any]:
    """Remove one variant WITH its stored meshes. Refused for the last
    remaining variant, and while this variant or one behind it is generating
    (the delete renumbers those)."""
    from app.core.props import delete_variant, variant_delete_blocked
    _variant(prop_id, index)
    if variant_delete_blocked(prop_id, index):
        raise HTTPException(
            status_code=409,
            detail="This variant or one after it is generating right now")
    if not delete_variant(prop_id, index):
        raise HTTPException(status_code=409,
                            detail="A prop needs at least one variant")
    result_payload = {"status": "deleted", "index": index}
    invalidate_prop_lib_token()
    return result_payload


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
    result_payload = {"status": "success", "active": filename, "tier": tier}
    invalidate_prop_lib_token()
    return result_payload


@router.delete("/props/{prop_id}/variants/{index}/models")
def prop_variant_model_delete(prop_id: str, index: int,
                              file: str = "") -> Dict[str, Any]:
    """Remove ONE stored mesh of this variant (``?file=``) or all of them."""
    from app.core.props import delete_model
    _variant(prop_id, index)
    result_payload = {"status": "success",
            "removed": delete_model(prop_id, file.strip(), variant=index)}
    invalidate_prop_lib_token()
    return result_payload


@router.get("/props/{prop_id}/variants/{index}/models/files/{filename}")
def prop_variant_model_file(prop_id: str, index: int, filename: str,
                            request: Request):
    """Serve ONE stored mesh of this variant by filename (admin preview)."""
    from app.core.http_files import etag_file_response, glb_file_response
    from app.core.props import model_file_path
    _variant(prop_id, index)
    p = model_file_path(prop_id, filename, variant=index)
    if not p:
        raise HTTPException(status_code=404, detail="Model not found")
    if p.suffix.lower() == ".glb":
        return glb_file_response(p, request)
    return etag_file_response(p, request, "application/octet-stream")


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
    result_payload = _shrink_start(trigger_shrink, prop_id, variant=index, **body)
    invalidate_prop_lib_token()
    return result_payload


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
    result_payload = _lod_result(
        lambda pid, **kw: build_low_tier(pid, variant=index, **kw),
        prop_id, ratio=ratio, kind="prop")
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/{index}/upload")
async def prop_variant_upload(prop_id: str, index: int,
                              file: UploadFile = File(...),
                              tier: str = Form(""),
                              force: str = Form("")) -> Dict[str, Any]:
    """Upload a GLB as a new mesh of THIS variant (same validation and the
    same ``force`` escape hatch as the unqualified upload route)."""
    from app.core.model_validate import validate_static_glb
    from app.core.props import save_uploaded_glb
    from app.core.upload_limits import (MODEL_UPLOAD_MAX_BYTES,
                                        read_upload_capped)
    from app.routes.world import _tier
    _variant(prop_id, index)
    contents = await read_upload_capped(file, max_bytes=MODEL_UPLOAD_MAX_BYTES,
                                        what="Prop model")
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
    result_payload = {"status": "ok", "warnings": result["warnings"]}
    invalidate_prop_lib_token()
    return result_payload


@router.post("/props/{prop_id}/variants/{index}/source")
async def prop_variant_source_upload(prop_id: str, index: int,
                                     file: UploadFile = File(...),
                                     view: str = "front") -> Dict[str, Any]:
    """Upload THIS variant's product-shot image (``?view=`` picks one of the
    four views; default front) — the picture its re-mesh works from. The
    image belongs to the variant like its meshes do, so an upload here can
    never overwrite another version's picture."""
    from app.routes.world import _prop_source_upload
    result_payload = await _prop_source_upload(prop_id, file, _variant(prop_id, index),
                                     view=view)
    invalidate_prop_lib_token()
    return result_payload


@router.delete("/props/{prop_id}/variants/{index}/source")
def prop_variant_source_delete(prop_id: str, index: int,
                               view: str = "") -> Dict[str, Any]:
    """Remove ONE extra view image (``?view=back|left|right``) of this
    variant. The front is not deletable — it is the variant's picture."""
    from app.core.props import delete_source_image
    from app.core.view_prompts import EXTRA_VIEWS
    _variant(prop_id, index)
    if view not in EXTRA_VIEWS:
        raise HTTPException(status_code=400,
                            detail="view must be back, left or right")
    if not delete_source_image(prop_id, index, view):
        raise HTTPException(status_code=404, detail="No such view image")
    result_payload = {"status": "ok"}
    invalidate_prop_lib_token()
    return result_payload


@router.get("/props/{prop_id}/generation-repairs")
def prop_generation_repairs(prop_id: str,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Retained legacy paid work. Repair with the chosen variant's generate
    route and ``{resume_op_id, variant_uid, base_revision}``; no source render
    or new mesh submission is made by this repair."""
    from app.core.props import generation_repairs
    return {"repairs": generation_repairs(prop_id)}


@router.post("/props/{prop_id}/generation-repairs/{op_id}/dismiss")
def prop_dismiss_generation_repair(prop_id: str, op_id: str,
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Hide a retained legacy result after an explicit admin decision."""
    from app.core.props import dismiss_generation_repair, PropRevisionConflict
    try:
        dismiss_generation_repair(prop_id, op_id)
    except PropRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "dismissed"}


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

    ``view`` names which of the four views an ``image_only`` run renders
    (default the front), ``front_reference`` slots a front image as that
    render's appearance reference — ``reference_variant`` says whose, this
    variant's own by default and ANOTHER variant's when a new version of the
    object is authored from the one before it — and ``views`` lists the extra
    views a MESH run sends along to the mesh alias.

    ``resume_op_id`` explicitly binds a retained legacy paid mesh to this
    variant. It requires its current ``variant_uid`` and ``base_revision``;
    the operation's frozen images, backend, budgets and result are reused.
    """
    from app.routes.world import (_mesh_int, _mesh_lod, _require_prop_picks,
                                  _tier, _view_args, _start_prop_generation)
    _variant(prop_id, index)
    data = await _body(request)
    if bool(data.get("mesh_only")) and bool(data.get("image_only")):
        raise HTTPException(status_code=400,
                            detail="mesh_only and image_only are exclusive")
    view, front_reference, reference_variant, views = _view_args(data)
    await _require_prop_picks(data)
    started = _start_prop_generation(
        prop_id, data,
        prompt=str(data.get("prompt") or ""),
        negative=str(data.get("negative") or ""),
        image_backend_glob=str(data.get("image_backend") or "").strip(),
        mesh_backend_glob=str(data.get("mesh_backend") or "").strip(),
        face_num=_mesh_int(data.get("face_num")) or None,
        texture_size=_mesh_int(data.get("texture_size")) or None,
        mesh_only=bool(data.get("mesh_only")),
        image_only=bool(data.get("image_only")),
        tier=_tier(data.get("tier")),
        # Three-valued (ruling V9): absent = the variant's own low budget may
        # apply, `[]` = the dialog switched the stage OFF, a number = that one.
        lod_faces=_mesh_lod(data),
        variant=index,
        view=view,
        front_reference=front_reference,
        reference_variant=reference_variant,
        views=views)
    result_payload = {"status": "generating" if started else "already_running"}
    invalidate_prop_lib_token()
    return result_payload


# Water belongs to the selected model file, outside the variant draft.
def _variant_water_model(prop_id: str, index: int):
    from app.core import props
    _variant(prop_id, index)
    mp = props.model_path(prop_id, variant=index)
    if not mp:
        raise HTTPException(status_code=404, detail="No model")
    return (mp, props.file_areas(mp)["rotation"],
            max(props.variant_dims(props.read_sidecar(prop_id), index).values()), "xyz")


@router.get("/props/{prop_id}/variants/{index}/water")
def prop_variant_water(prop_id: str, index: int,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core.model_water import read_water, water_status
    mp, rot, _target, _measure = _variant_water_model(prop_id, index)
    return {**water_status(mp, rot), "water": read_water(mp, rot)}


@router.post("/props/{prop_id}/variants/{index}/water/detect")
def prop_variant_water_detect(prop_id: str, index: int, wait: bool = False,
                              _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core.model_water import request_detection
    return request_detection(lambda: _variant_water_model(prop_id, index), wait=wait)


@router.patch("/props/{prop_id}/variants/{index}/water")
async def prop_variant_water_patch(prop_id: str, index: int, request: Request,
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    import asyncio
    from app.core.model_water import patch_water
    mp, rot, _target, _measure = _variant_water_model(prop_id, index)
    try:
        water = await asyncio.to_thread(patch_water, mp, rot, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"status": "valid", "water": water}


# House builds use the same variant galleries as uploaded/generated models.
def _house_footprint(prop_id: str, entry: dict):
    """Read authored size without repairing missing dimensions on disk."""
    import json
    import math
    from app.core import props
    house = entry.get('house') or {}
    if house.get('footprint_m'):
        return house['footprint_m']
    path = props._sidecar_path(prop_id)
    raw = json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
    stored = next((item for item in raw.get(props.VARIANTS_KEY, [])
                   if isinstance(item, dict) and item.get('stem') == entry['stem']), {})
    try:
        footprint = [float(stored[key]) for key in ('width_m', 'depth_m')]
        return footprint if all(math.isfinite(v) and v > 0 for v in footprint) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


@router.get('/props/{prop_id}/variants/{index}/house')
def prop_variant_house(prop_id: str, index: int) -> Dict[str, Any]:
    from copy import deepcopy
    from app.core import props, house_props, hull_styles, door_styles
    from app.routes.assets import list_surface_textures
    _variant(prop_id, index)
    entry = props._variant_list(props.read_sidecar(prop_id, read_only=True))[index]
    house = entry.get('house') or {}
    footprint = _house_footprint(prop_id, entry)
    gallery = props.ModelGallery(props._prop_dir(prop_id), entry['stem'], ('.glb',))
    with house_props._running_lock:
        running = props.safe_prop_id(prop_id) in house_props._running
        error = house_props._errors.get((props.safe_prop_id(prop_id), entry['uid']), '')
    return {'spec': deepcopy(house.get('spec', house_props.HOUSE_DEFAULTS)),
            'footprint_m': footprint,
            'built': any(props.read_model_sidecar(file).get('source') == 'house_build'
                         for file in gallery.files()),
            'running': running, 'error': error,
            'styles': [{'id': key, 'name': value.get('name') or key}
                       for key, value in hull_styles.load_styles().items()],
            'door_styles': [{'id': key, 'name': value.get('name') or key}
                            for key, value in door_styles.load_door_styles().items()],
            'wall_kinds': list_surface_textures()}


@router.put('/props/{prop_id}/variants/{index}/house')
async def put_prop_variant_house(prop_id: str, index: int, request: Request,
                                 _admin: dict = Depends(require_admin)) -> Dict[str, Any]:
    from app.core.house_props import set_house_spec
    _variant(prop_id, index)
    try:
        house = set_house_spec(prop_id, index, await _body(request))
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    invalidate_prop_lib_token()
    return house['spec']


@router.post('/props/{prop_id}/variants/{index}/house/build')
def build_prop_variant_house(prop_id: str, index: int,
                             _admin: dict = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import house_props, props
    _variant(prop_id, index)
    if not props._variant_list(props.read_sidecar(prop_id, read_only=True))[index].get('house'):
        raise HTTPException(400, detail='save the house spec first')
    try:
        started = house_props.trigger_house_build(prop_id, index)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    return {'status': 'building' if started else 'already_running'}


@router.post('/props/{prop_id}/house/copy-layout')
async def copy_prop_house_layout(prop_id: str, request: Request,
                                _admin: dict = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import props
    try:
        body = await _body(request)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    source = body.get('from')
    if type(source) is not int:
        raise HTTPException(400, detail='from must be a variant index')
    _variant(prop_id, source)
    try:
        props.copy_house_layout(prop_id, source)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    invalidate_prop_lib_token()
    return {'status': 'copied'}


@router.post('/props/{prop_id}/variants/{index}/house/reset-footprint')
def reset_prop_house_footprint(prop_id: str, index: int,
                              _admin: dict = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import props
    _variant(prop_id, index)
    try:
        house = props.reset_house_footprint(prop_id, index)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    invalidate_prop_lib_token()
    return house
