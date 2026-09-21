"""Thumbnail serving for tile views (UI-8).

ONE route per image kind a tile view shows, mirroring the full-size route's
URL under the ``/thumbs`` prefix:

    /characters/{name}/images/{file}        -> /thumbs/characters/{name}/images/{file}?w=192
    /world/locations/{id}/gallery/{file}    -> /thumbs/world/locations/{id}/gallery/{file}?w=192
    /inventory/items/{id}/image             -> /thumbs/inventory/items/{id}/image?w=96

The client builds these by prepending ``/thumbs`` and appending ``?w=`` —
``thumbUrl()`` in ``packages/player-ui/src/thumbs.ts`` is the one place that
does it. The lightbox/full view keeps the original URL.

RESOLUTION AND SAFETY. Each route resolves its source through the SAME helper
and the SAME file-name check as the full-size route it mirrors
(``routes/characters.get_character_image``, ``routes/world.get_gallery_image``,
``routes/inventory.get_item_image_route``), so a traversal-shaped name is a
400 here exactly as it is there, and no path can be reached through a
thumbnail that could not be reached full size.

AUTH. ``/thumbs/...`` is NOT on the public allowlist, so a session is
required — same as the full-size routes. The per-character policy in
``auth_dependency`` classifies ``/characters/{n}/images/{f}`` as PUBLIC
(``images`` is in ``_PUBLIC_CHARACTER_SEGMENTS``: any logged-in player may see
any character's pictures), and ``/thumbs/...`` is not a character-scoped path
at all, so it is likewise non-sensitive — the two classify the same way and
the prefix needs no entry in ``auth_dependency``.

CPU. The routes are sync ``def``, so FastAPI runs them in the threadpool: a
first request decodes a multi-megapixel PNG, which must never sit on the event
loop. Everything after the first request is an ETag revalidation on a file of
a few dozen kB.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.core.http_files import etag_file_response
from app.core.paths import get_storage_dir
from app.core.thumbnails import THUMB_MEDIA_TYPE, get_thumbnail, parse_width

router = APIRouter(prefix="/thumbs", tags=["thumbs"])


def _check_filename(name: str) -> str:
    """The file-name check of the full-size routes, verbatim: a name that
    carries a separator or a parent reference is a 400."""
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name


def _inside(directory: Path, path: Path) -> Path:
    """Belt and braces on top of :func:`_check_filename`: the resolved file
    must really lie under ``directory``. A symlink or an exotic name that got
    past the textual check cannot leave the gallery this way."""
    try:
        resolved = path.resolve()
        base = directory.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return resolved


def _serve(src: Path, raw_width, request: Request):
    """Width check first (it is free), then the thumbnail, then ETag/304."""
    width = parse_width(raw_width)
    thumb = get_thumbnail(src, width)
    return etag_file_response(thumb, request, THUMB_MEDIA_TYPE)


@router.get("/characters/{character_name}/images/profile")
def thumb_character_profile_image(character_name: str, request: Request,
                                  w: str = ""):
    """Thumbnail of the character's profile picture.

    Declared BEFORE the generic image route so ``/images/profile`` keeps
    meaning "the profile picture" and is not looked up as a file of that name
    — exactly the order ``routes/characters.py`` uses for the full-size pair.
    Every small portrait in the UI (roster rows, phone avatars, post headers)
    points at this URL.
    """
    from app.models.character import (get_character_images_dir,
                                      get_character_profile_image)
    try:
        profile = get_character_profile_image(character_name) or ""
        images_dir = get_character_images_dir(character_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid character name")
    if not profile:
        raise HTTPException(status_code=404, detail="No profile image")
    _check_filename(profile)
    src = _inside(images_dir, images_dir / profile)
    return _serve(src, w, request)


@router.get("/characters/{character_name}/images/{image_filename}")
def thumb_character_image(character_name: str, image_filename: str,
                          request: Request, w: str = ""):
    """Thumbnail of a character gallery image (the player gallery tiles)."""
    from app.models.character import get_character_images_dir
    _check_filename(image_filename)
    try:
        images_dir = get_character_images_dir(character_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid character name")
    src = _inside(images_dir, images_dir / image_filename)
    return _serve(src, w, request)


@router.get("/world/locations/{location_name}/gallery/{image_name}")
def thumb_location_gallery_image(location_name: str, image_name: str,
                                 request: Request, w: str = ""):
    """Thumbnail of a location gallery image (the admin gallery cards)."""
    from app.models.world import get_gallery_dir
    _check_filename(image_name)
    gallery_dir = get_gallery_dir(location_name)
    src = _inside(gallery_dir, gallery_dir / image_name)
    return _serve(src, w, request)


@router.get("/inventory/items/{item_id}/image")
def thumb_item_image(item_id: str, request: Request, w: str = ""):
    """Thumbnail of an item picture (inventory/gift/wardrobe icons).

    The file name comes from the item row, not from the URL — the same
    indirection the full-size route uses, so there is nothing to sanitise
    beyond the item id itself.
    """
    from app.models.inventory import get_item
    _check_filename(item_id)
    item = get_item(item_id)
    if not item or not item.get("image"):
        raise HTTPException(status_code=404, detail="No image")
    if item.get("_shared"):
        from app.core.paths import get_shared_dir
        item_dir = get_shared_dir() / "items" / item_id
    else:
        item_dir = get_storage_dir() / "items" / item_id
    src = _inside(item_dir, item_dir / item["image"])
    return _serve(src, w, request)
