"""Shared 3D assets — animation clips + surface textures.

Reading is public, editing is not: everything a client plays is served
unauthenticated, while the import sources and the two library edit routes
(``DELETE`` / ``PATCH /assets/animation-clips/{library}/{rel}``) are
admin-only.

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). They
belong to the RIG, not to a character or a world, so every client — the
Game-Admin 3D preview and the external 3D map client — reads them from here.
Surface textures (AV3D-13) are the second asset family: tileable ground
materials in ``shared/surface_textures``, managed via /world/surface-textures,
served here because the 3D client consumes them exactly like the clip library.
They are shared across worlds for the same reason the clips are — a ground
material belongs to no single world (E5 Task 4).

``kind`` (idle / walk / run / sit / dance / wave / …) is derived from the file
name, ``set`` from the subdirectory the clip lies in; both vocabularies are
OPEN — no list exists in the code, a new kind is just a new file and a new set
just a new directory. Clips practically never change → served with an ETag and
a long max-age.

On top of the two libraries sits the CMU TRIAL archive (``clip_catalog``):
``/assets/clip-catalog`` hands out the measured catalog of the whole database
plus the reviewer's own state, ``/assets/animation-clips/trial/{rel}`` serves a
converted take for preview, and ``/assets/clip-catalog/{take}/import`` turns
one into a real clip of the free library. Those three are ADMIN-only and none
of them touches the listing above — a trial clip is review material, not game
content.

The second import source is the INBOX (``fbx_import``): foreign FBX files an
admin drops into ``shared/models/clips-inbox`` or uploads through
``/assets/clips-inbox/upload``. ``GET /assets/clips-inbox`` lists them with the
skeleton probe, ``POST /assets/clips-inbox/import`` retargets one (or a pair)
onto the library rig. Same rule as the trial archive: the inbox is no library,
and it is admin-only.
"""
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core import clip_catalog, fbx_import
from app.core.animation_clips import (CLIP_EXTS, ClipExists, ClipLibraryError,
                                      ClipNotFound, clip_entries, clip_meta,
                                      clip_view, delete_clip, pair_kinds,
                                      rename_clip)
from app.core.auth_dependency import require_admin
from app.core.cmu_import import ClipImportError
from app.core.http_files import etag_file_response
from app.core.log import get_logger
from app.core.paths import (get_animation_clips_dir, get_licensed_clips_dir,
                            get_rig_file)

logger = get_logger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/animation-clips")
def list_animation_clips() -> Dict[str, Any]:
    """Lists the shared animation clips.

    Per clip: ``kind`` (the activity category), ``role`` (``a``/``b`` for the
    half of a pair clip, empty for a solo clip), ``set`` (the figure it was
    made for — empty = the neutral figure), plus name/url/size. ``kinds`` and
    ``sets`` list the vocabularies actually present; both are OPEN — a new one
    is just a new file or directory, nothing is hardcoded. ``pairs`` maps every
    complete pair kind to its sidecar (duration, fps, anchor geometry) — the
    data a client needs to play both halves at one anchor (§ A8a).

    For the library view every clip also carries what its sidecar knows —
    ``duration_s`` / ``fps`` / ``frames`` (``null`` without a sidecar),
    ``loop``, ``origin`` (``cmu`` / the skeleton family / ``unknown``) and
    ``has_sidecar`` — plus ``library`` (= ``source``) and ``rel``, the
    library-relative ``[<set>/]<file>`` the edit routes address it by.

    A set clip's ``url`` carries its directory segment. Clients take the URL
    from this listing opaquely — they never build it from name + set.
    """
    clips = [clip_view(entry) for entry in clip_entries()]
    from app.core.animation_sets import available_sets
    pairs = {}
    for kind in pair_kinds():
        meta = clip_meta(kind) or {}
        pairs[kind] = {
            "duration_s": meta.get("duration_s"),
            "fps": meta.get("fps"),
            "frames": meta.get("frames"),
            "geometry": meta.get("geometry") or {},
        }
    return {"clips": clips,
            "kinds": sorted({c["kind"] for c in clips}),
            "pair_kinds": sorted(pairs),
            "pairs": pairs,
            # Sets that HAVE clips …
            "clip_sets": sorted({c["set"] for c in clips if c["set"]}),
            # … and everything selectable on a character: the base sets
            # (female/male/animal, which follow from gender + the humanoid
            # feature) plus any further set found in the files.
            "sets": available_sets()}


# ── Editing the libraries (the Poses tab's "Library" view) ───────────────
#
# Both routes address a clip as ``{library}/{rel}`` — the library it lives in
# plus its library-relative ``[<set>/]<file>``, exactly the ``library`` /
# ``rel`` pair of the listing. They are ADMIN-only (same gate as the inbox)
# and they are thin: every rule lives in ``animation_clips``, so the smoke
# check can exercise it without HTTP.

def _clip_edit_error(e: ClipLibraryError) -> HTTPException:
    """The one mapping of the core's errors onto status codes."""
    if isinstance(e, ClipNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ClipExists):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


@router.delete("/animation-clips/{library}/{rel:path}")
def delete_animation_clip(library: str, rel: str,
                          _: Dict[str, Any] = Depends(require_admin)
                          ) -> Dict[str, Any]:
    """Deletes one clip — both halves when it is a pair, and the ``<kind>.json``
    sidecar once no file of that kind is left beside it."""
    try:
        return delete_clip(library, rel)
    except ClipLibraryError as e:
        raise _clip_edit_error(e)


@router.patch("/animation-clips/{library}/{rel:path}")
async def patch_animation_clip(library: str, rel: str, request: Request,
                               _: Dict[str, Any] = Depends(require_admin)
                               ) -> Dict[str, Any]:
    """Renames a clip and/or moves it to another set or library.

    Body ``{kind?, set?, library?}``, at least one of them. ``set: ""`` moves
    the clip to the neutral root — the ONE empty value with a meaning;
    ``library: ""`` is a bad request, not a silent no-op. The answer carries
    the moved clips in the shape of the listing.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="object expected")
    if not any(k in body for k in ("kind", "set", "library")):
        raise HTTPException(status_code=400,
                            detail="one of kind, set, library is required")
    if "library" in body and not str(body["library"] or "").strip():
        raise HTTPException(status_code=400,
                            detail="library must be 'free' or 'licensed'")
    try:
        clips = rename_clip(library, rel,
                            kind=body["kind"] if "kind" in body else None,
                            cset=body["set"] if "set" in body else None,
                            to_library=body["library"] if "library" in body
                            else None)
    except ClipLibraryError as e:
        raise _clip_edit_error(e)
    return {"clips": clips}


# ── The CMU trial archive (plan-clip-import.md step 1) ───────────────────
#
# The trial pool is NOT a clip library: nothing here is scanned by
# animation_clips, nothing shows up in the listing above, and no character ever
# plays one. It exists so an admin can WATCH a take before deciding to import
# it. Hence its own route — and it has to be registered BEFORE the
# ``{rel:path}`` catch-all below, which would otherwise swallow every
# ``trial/…`` request and answer 404 from inside the free library.

@router.get("/animation-clips/trial/{rel:path}")
def get_trial_clip(rel: str, request: Request,
                   _: Dict[str, Any] = Depends(require_admin)):
    """Serves ONE converted trial clip, ``<main>/<sub>/<file>.fbx``.

    Admin-only, like the whole catalog browser: this is review material, not
    game content. Path validation is ``clip_catalog.resolve_trial_path``.
    """
    path = clip_catalog.resolve_trial_path(rel)
    if path is None:
        raise HTTPException(status_code=400, detail="Invalid trial clip path")
    if not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _mt = mimetypes.guess_type(str(path))
    return etag_file_response(path, request,
                              media_type or "application/octet-stream",
                              cache_control="public, max-age=3600")


@router.get("/clip-catalog")
def get_clip_catalog(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The whole CMU catalog with the review state merged in.

    One request, everything the browser needs: ``takes`` (each with its
    metrics, sparkline, tags, group, its ``status`` and the ``clip_urls`` its
    preview plays) plus the ``tags``/``facets``/``groups`` vocabularies.

    PARTIAL is the normal state. The enrich run and the bulk conversion both
    fill this file in the background: a take may have no ``clip`` yet (not
    converted), and takes may be missing entirely (not measured yet). Neither
    is an error — only a completely absent catalog is a 404.
    """
    data = clip_catalog.catalog_with_status()
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"no trial catalog at {clip_catalog.catalog_path()} — build it "
                   "with scripts/cmu_fetch_all.py + scripts/cmu_enrich_index.py")
    for take in data["takes"]:
        take["clip_urls"] = clip_catalog.trial_clip_urls(take)
    return data


@router.put("/clip-catalog/{take_id}/status")
async def put_clip_catalog_status(take_id: str, request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)
                                  ) -> Dict[str, Any]:
    """Sets ``favorite`` / ``rejected`` on one take. Only the fields present in
    the body are touched, so a favorite click never clears a rejection."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_put_clip_catalog_status_sync, take_id, _,
                                   body)


def _put_clip_catalog_status_sync(take_id: str, _: Dict[str, Any],
                                  body: Any) -> Dict[str, Any]:
    """The blocking body of ``put_clip_catalog_status`` — runs in the
    threadpool."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="object expected")
    fav = body.get("favorite")
    rej = body.get("rejected")
    status = clip_catalog.set_status(
        take_id.strip(),
        favorite=None if fav is None else bool(fav),
        rejected=None if rej is None else bool(rej))
    return {"take_id": take_id, "status": status}


@router.get("/clip-catalog/{take_id}/loop-window")
def get_clip_catalog_loop_window(take_id: str, start_s: float = 0.0,
                                 end_s: Optional[float] = None, min_s: float = 1.0,
                                 _: Dict[str, Any] = Depends(require_admin)
                                 ) -> Dict[str, Any]:
    """The loop window an import with these settings would cut — start/end in
    take seconds — so the preview plays the very clip the converter writes
    (same resampling, same seam metric; a second of CPU, no Blender)."""
    from app.core.cmu_import import loop_window
    take = clip_catalog.find_take(take_id.strip())
    if not take:
        raise HTTPException(status_code=404, detail=f"unknown take {take_id}")
    try:
        return loop_window(take_id.strip(), start_s=max(0.0, start_s), end_s=end_s,
                           min_s=max(0.1, min_s))
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/clip-catalog/{take_id}/import")
async def post_clip_catalog_import(take_id: str, request: Request,
                                   _: Dict[str, Any] = Depends(require_admin)
                                   ) -> Dict[str, Any]:
    """Imports one take into the FREE clip library — synchronously.

    Body: ``{kind, set?, start_s?, end_s?, loop_s?, in_place?, overwrite?,
    target?}``. The conversion is a Blender run of a few seconds, so it answers
    directly instead of going through the queue; the caller sees either the new
    clip or the converter's own message.

    ``target`` accepts only ``free``: CMU data is redistributable and that is
    the whole reason its clips may live in the tracked library. Anything else
    belongs to the (later) generic importer, not here.
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_post_clip_catalog_import_sync, take_id, _,
                                   body)


def _post_clip_catalog_import_sync(take_id: str, _: Dict[str, Any],
                                   body: Any) -> Dict[str, Any]:
    """The blocking body of ``post_clip_catalog_import`` — runs in the
    threadpool."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="object expected")
    target = str(body.get("target") or "free").strip().lower()
    if target != "free":
        raise HTTPException(status_code=400,
                            detail="CMU clips are redistributable — target must be 'free'")

    def _num(key: str) -> Optional[float]:
        raw = body.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be a number")

    try:
        return clip_catalog.import_take(
            take_id.strip(), body.get("kind"),
            clip_set=str(body.get("set") or ""),
            start_s=_num("start_s") or 0.0, end_s=_num("end_s"),
            loop_s=_num("loop_s"),
            in_place=bool(body.get("in_place", True)),
            overwrite=bool(body.get("overwrite")),
            speed=_num("speed") or 1.0)
    except clip_catalog.ClipKindExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ClipImportError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── The import inbox for foreign FBX files (plan-clip-import.md steps 1+3) ──
#
# Same separation as the trial archive: the inbox is NOT a library. Nothing in
# it is listed by /assets/animation-clips and no character can play it; a file
# becomes a clip only through the import below, which retargets it onto the
# library rig. Admin-only, and every route talks in BARE FILE NAMES — the path
# gate is fbx_import.safe_inbox_name.

#: One uploaded file may be this large. A mocap FBX is a few MB; 200 MB is
#: generous enough for a long, finger-carrying take and small enough that a
#: mis-drop (a whole model pack) is refused instead of filling the disk.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

#: Everything an upload's file name may consist of — the name is rebuilt from
#: this class, so nothing a browser sends can leave the inbox.
_UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/clips-inbox")
def get_clips_inbox(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """What is waiting to be imported.

    Per file: name/size/mtime, the ``probe`` (skeleton family, bone count,
    fingers, reference-pose candidate — read from the bytes, no Blender) and
    the ``pair`` partner suggested by the file names. ``rest_suggestion`` is
    the reference-pose file the whole inbox agrees on. An empty inbox (or none
    at all) is the normal state, not an error.
    """
    entries = fbx_import.inbox_entries()
    for entry in entries:
        entry["pair"] = fbx_import.pair_suggestion(entry["name"])
    return {"dir": str(fbx_import.get_clips_inbox_dir()),
            "entries": entries,
            "rest_suggestion": fbx_import.rest_suggestion(),
            "families": sorted(fbx_import.SIGNATURES)}


@router.post("/clips-inbox/upload")
async def post_clips_inbox_upload(files: List[UploadFile] = File(...),
                                  _: Dict[str, Any] = Depends(require_admin)
                                  ) -> Dict[str, Any]:
    """Uploads one or more FBX files into the inbox.

    The stored name is REBUILT from the upload's base name (directory parts
    dropped, everything outside ``[A-Za-z0-9._-]`` replaced), so the browser
    never decides where a byte lands. A file above ``MAX_UPLOAD_BYTES`` is
    refused with 413 and its partial write removed.
    """
    root = fbx_import.get_clips_inbox_dir()
    root.mkdir(parents=True, exist_ok=True)
    stored: List[Dict[str, Any]] = []
    for upload in files:
        base = Path(str(upload.filename or "")).name
        name = _UPLOAD_NAME_RE.sub("_", base).lstrip(".")
        if Path(name).suffix.lower() not in fbx_import.INBOX_EXTS:
            raise HTTPException(status_code=400,
                                detail=f"{base or 'file'}: only "
                                       f"{', '.join(fbx_import.INBOX_EXTS)} files")
        dest = root / fbx_import.safe_inbox_name(name)
        size = 0
        try:
            with dest.open("wb") as fh:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{name} is larger than "
                                   f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                    fh.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        stored.append({"name": dest.name, "size": size})
    logger.info("clip inbox upload: %s", ", ".join(s["name"] for s in stored))
    return {"stored": stored, **get_clips_inbox(None)}


@router.delete("/clips-inbox/{name}")
def delete_clips_inbox(name: str,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Removes one inbox file. Deleting a file that is already gone is fine."""
    try:
        removed = fbx_import.delete_inbox(name)
    except ClipImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "removed": removed}


@router.post("/clips-inbox/preview")
async def post_clips_inbox_preview(request: Request,
                                   _: Dict[str, Any] = Depends(require_admin)
                                   ) -> Dict[str, Any]:
    """Probe conversion with the import form's values — same body as
    ``/clips-inbox/import`` — into the inbox's hidden preview folder; answers
    the URLs the preview plays. Nothing enters a library."""
    return await _clips_inbox_convert(request, preview=True)


@router.get("/clips-inbox/preview-clip/{name}")
def get_clips_inbox_preview_clip(name: str, request: Request,
                                 _: Dict[str, Any] = Depends(require_admin)):
    from app.core import fbx_import
    path = fbx_import.preview_clip_path(name)
    if path is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "application/octet-stream",
                              cache_control="no-cache")


@router.post("/clips-inbox/import")
async def post_clips_inbox_import(request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)
                                  ) -> Dict[str, Any]:
    """Imports one inbox file — or a pair — into a clip library, synchronously."""
    return await _clips_inbox_convert(request, preview=False)


async def _clips_inbox_convert(request: Request, preview: bool) -> Dict[str, Any]:
    """Imports one inbox file — or a pair — into a clip library, synchronously.

    Body: ``{kind, files: [name] | [a, b], rest_file?, set?, start_s?, end_s?,
    loop_s?, in_place?, overwrite?, target?, redistributable?}``. The Blender
    run takes a second or two, so the answer carries the finished clip.

    ``target`` defaults to ``licensed``: a foreign file is licensed material
    until its owner says otherwise. ``free`` (the tracked, redistributable
    library) needs ``redistributable: true`` — 400 without it.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="object expected")

    def _num(key: str) -> Optional[float]:
        raw = body.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be a number")

    files = body.get("files")
    if not isinstance(files, list):
        raise HTTPException(status_code=400, detail="files must be a list of names")
    target = str(body.get("target") or "licensed").strip().lower()
    redistributable = bool(body.get("redistributable"))
    if preview:
        target, redistributable = "licensed", False      # a probe enters no library
    if target == "free" and not redistributable:
        raise HTTPException(
            status_code=400,
            detail="the free library is redistributable — confirm the licence "
                   "allows it, or import into the licensed library")
    try:
        return fbx_import.import_fbx(
            body.get("kind"), files,
            rest_file=str(body.get("rest_file") or "") or None,
            clip_set=str(body.get("set") or ""),
            start_s=_num("start_s") or 0.0, end_s=_num("end_s"),
            loop_s=_num("loop_s"),
            in_place=bool(body.get("in_place")),
            overwrite=bool(body.get("overwrite")),
            offset_b_m=[float(v) for v in (body.get("offset_b_m") or [0, 0, 0])][:3]
            if isinstance(body.get("offset_b_m"), list) else None,
            loops=None if body.get("loops") is None else bool(body.get("loops")),
            speed=_num("speed") or 1.0,
            target=target, redistributable=redistributable, preview=preview)
    except fbx_import.ClipKindExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ClipImportError as e:
        raise HTTPException(status_code=422, detail=str(e))


def resolve_clip_path(rel: str) -> Optional[Path]:
    """``[licensed/][<set>/]<file>`` → the clip file, or None when the request
    is not a legal clip reference.

    The leading ``licensed/`` segment selects the licensed library; without
    it the free one is meant. At most one set segment. Every segment must be
    a plain name — no empty segment, no ``.``/``..``, no backslash — and the
    resolved path must stay inside its library (a symlink pointing out is
    refused too, hence ``resolve()`` on both sides). Only clip extensions.
    """
    segments = rel.split("/")
    base = get_animation_clips_dir()
    if segments and segments[0] == "licensed":
        base = get_licensed_clips_dir()
        segments = segments[1:]
    if not 1 <= len(segments) <= 2:
        return None
    for seg in segments:
        if not seg or seg in (".", "..") or "\\" in seg:
            return None
    base = base.resolve()
    path = base.joinpath(*segments).resolve()
    if not path.is_relative_to(base):
        return None
    if path.suffix.lower() not in CLIP_EXTS:
        return None
    return path


@router.get("/animation-rig")
def get_animation_rig(request: Request):
    """The RETARGET REFERENCE skeleton (``shared/models/rig/reference.fbx``).

    Every library clip is converted onto this rig, so its rest pose is the
    frame the clips' rotation tracks are written in. A renderer needs it to
    read a clip as a rotation AWAY FROM REST and transplant that onto a
    character rig with a bind pose of its own
    (``@anima/scene-render``'s ``restCorrections``). Without it a renderer can
    only copy tracks 1:1, which overwrites the character's own stance.

    404 while the rig is absent is a normal state — the consumer then falls
    back to the 1:1 copy.
    """
    path = get_rig_file()
    if not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "application/octet-stream",
                              cache_control="public, max-age=86400")


@router.get("/animation-clips/{rel:path}")
def get_animation_clip(rel: str, request: Request):
    """Serves a clip file — ``<file>`` for a neutral clip, ``<set>/<file>`` for
    a set clip, ``licensed/…`` for one out of the licensed library. ETag + If-None-Match; clips are immutable in practice, so they
    may be cached hard."""
    path = resolve_clip_path(rel)
    if path is None:
        raise HTTPException(status_code=400, detail="Invalid clip path")
    if not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request,
                              media_type or "application/octet-stream",
                              cache_control="public, max-age=86400")


@router.get("/surface-textures")
def list_surface_textures():
    """Global surface-texture library (AV3D-13) — contract shape: a BARE
    array ``[{kind, name, url, size_m, material?}, …]`` (compositions carry
    ``blend`` instead of url/size_m). ``kind`` is the ID and the open
    vocabulary matching the location ``terrain`` field, ``name`` what a picker
    shows, ``material`` HOW the kind is lit (§ A9); an empty list is the
    normal state (the client falls back to its procedural materials).

    The whitelist is explicit ON PURPOSE — this is a contract surface, and a
    field reaches a client only by being named here. It is also the trap it
    sounds like: ``name`` and ``material`` were added to ``list_textures``
    and silently dropped right here, so the lake rendered its texture and not
    a drop of water (2026-07-29). A new field needs BOTH ends.
    """
    from app.core.surface_textures import list_textures
    out = []
    for t in list_textures():
        entry = {"kind": t["kind"], "name": t.get("name", "")}
        if "blend" in t:
            # Composition entry (AV3D-13 v2) — no url/size_m.
            entry["blend"] = t["blend"]
        else:
            entry["url"] = t["url"]
            entry["size_m"] = t["size_m"]
        if t.get("material"):
            entry["material"] = t["material"]
        out.append(entry)
    return out


@router.get("/surface-textures/{filename}")
def get_surface_texture(filename: str, request: Request):
    """Serves a texture image. ETag + If-None-Match; textures can be
    regenerated, so revalidation stays cheap but caching moderate."""
    from app.core.surface_textures import file_by_name
    path = file_by_name(filename)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "image/jpeg",
                              cache_control="public, max-age=3600")


# ── Props (plan-room-props.md) ──
# Global per-world prop library — single furnishing objects (chair, table, …)
# as their own GLB meshes + object-local markers. Managed via /world/props;
# served here because the 3D client consumes them like the other asset
# families. A prop's placement in a room is NOT here (that is the room recipe,
# Fable's part) — this is the raw library.

#: Sentinel for a ``variant`` parameter that is not a number at all — telling
#: it apart from "absent" (= the primary variant) is the difference between a
#: 404 and quietly serving another variant's file.
_BAD_VARIANT = object()


def _variant_index(variant: str):
    """The ``?variant=`` query parameter as a store index: ``None`` when it is
    absent (the PRIMARY variant), the index when it is a number, the
    ``_BAD_VARIANT`` sentinel otherwise."""
    raw = str(variant or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return _BAD_VARIANT


@router.get("/props")
def list_props():
    """Prop library — the lean client shape: a bare array
    ``[{id, name, category, width_m, depth_m, height_m, tags, marker_count,
    has_model, model_tiers, variant_tiers}, …]``. The three dims are the
    object's REAL extent in metres after its orientation fix (x/y/z =
    width/height/depth) — of the PRIMARY variant, which is what every read
    without a variant in hand answers. ``variant_tiers`` lists the prop's
    ACTIVE model variants (E2.3) as ``{variant, tiers, dims,
    ground_offset_m?}`` — element 0 is the primary one, whose ``tiers`` IS
    ``model_tiers``; size and sink belong to the VARIANT (2026-08-25), so a
    consumer that draws one reads them off its entry. ``marker_count`` is the
    primary variant's; the marker LISTS ride only on the admin record. An
    empty list is the normal starting state."""
    from app.core.props import list_props as _list
    return _list()


@router.get("/props/{prop_id}/model")
def get_prop_model(prop_id: str, request: Request, tier: str = "",
                   variant: str = ""):
    """Serves a prop's GLB mesh in the requested resolution tier (``full`` =
    default, ``low`` = overview mesh). A tier the prop does not have falls
    back to the best available one — a missing low variant must never make an
    object disappear. ETag + If-None-Match; a 404 is the normal "no model yet"
    state (the record may exist before the mesh does).

    ``variant`` picks one of the prop's MODEL variants (E2.3) — several
    meshes of the same object, so a scattered wood is not one tree twenty
    times. Absent = the PRIMARY variant, which is what every payload's
    ``variants`` map points at and therefore what every consumer that knows
    nothing about variants keeps getting. An index the prop has no variant for
    is a 404, never a silent other mesh.

    A MISSING low variant is not noticed here: every payload lists only the
    tiers a prop has and every renderer picks from that list, so this route
    never sees a request for one that does not exist. The build is asked for
    where the tier list is produced (``props._demand_low``)."""
    from app.core.props import model_path
    idx = _variant_index(variant)
    if idx is _BAD_VARIANT:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    path = model_path(prop_id, tier, variant=idx)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "model/gltf-binary",
                              cache_control="public, max-age=3600")


@router.get("/props/{prop_id}/source")
def get_prop_source(prop_id: str, request: Request, variant: str = "",
                    view: str = "front"):
    """Serves the product-shot render a prop's mesh was made from (the
    library thumbnail). 404 when the prop was uploaded without a source.

    ``variant`` picks one of the prop's MODEL variants — the image belongs to
    the variant, not to the prop, because a variant is a whole version of the
    object and its mesh was made from THIS picture. Absent = the PRIMARY
    variant, which is the historic ``source.png`` and therefore exactly the
    file this URL has always served. An index the prop has no variant for is
    a 404, never another variant's image.

    ``view`` serves one of the extra views (``back``/``left``/``right``);
    default front."""
    from app.core.props import source_path
    from app.core.view_prompts import is_view
    idx = _variant_index(variant)
    if idx is _BAD_VARIANT or not is_view(view):
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    path = source_path(prop_id, variant=idx, view=view)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "image/png",
                              cache_control="public, max-age=3600")
