"""Chat-domain operations behind app/routes/chat.py.

Logic moved 1:1 out of the route handlers (code-review section 5c); the routes
remain thin HTTP adapters (auth, request parsing, response types, FileResponse/
StreamingResponse). HTTPExceptions embedded mid-logic moved along unchanged.
Shared helpers that stay in app/routes/chat.py (external importers rely on them)
are pulled in via function-scope lazy imports to avoid a module-level cycle.
"""
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from app.core.log import get_logger

logger = get_logger("chat")

from app.core.paths import get_storage_dir as _get_storage_dir

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _get_chat_upload_dir() -> Path:
    # Duplicated 1:1 from app/routes/chat.py: the original stays there because
    # resolve_chat_image() (non-moving) still uses it.
    d = _get_storage_dir() / "chat_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d



async def save_chat_upload(request) -> Dict[str, Any]:
    """Store an uploaded chat image and return a temporary image ID.

    Size and type are enforced by `app.core.upload_limits` (SEC-7): the
    Content-Length is refused before the body is parsed at all, the read stops
    at the cap, and the MAGIC BYTES decide whether this is an image — the file
    name alone used to be the only check, so any file at all could be parked
    in the world's upload dir under a `.png` name.
    """
    from app.core.upload_limits import (ensure_image, guard_content_length,
                                        read_upload_capped)

    guard_content_length(request, what="chat image")
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        raise HTTPException(status_code=400, detail="No file uploaded")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    content = await read_upload_capped(file, what="chat image")
    ensure_image(content, filename=file.filename, what="chat image")

    image_id = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = _get_chat_upload_dir() / image_id
    dest.write_bytes(content)

    return {"image_id": image_id, "filename": file.filename}


def build_chat_image_library(character: str = None) -> Dict[str, Any]:
    """List character-library images for linking in chat."""
    from app.models.character import get_character_images, list_available_characters

    result = {}
    if character:
        characters = [character]
    else:
        characters = list_available_characters()

    for char_name in characters:
        images = get_character_images(char_name)
        if images:
            result[char_name] = [
                {
                    "filename": img,
                    "url": f"/characters/{char_name}/images/{img}",
                }
                for img in images[:50]  # Limit per character
            ]

    return {"characters": result}






def resolve_chat_upload_path(image_id: str) -> Path:
    """Validate an upload image ID and return its filesystem Path."""
    if ".." in image_id or "/" in image_id:
        raise HTTPException(status_code=400, detail="Invalid image ID")
    path = _get_chat_upload_dir() / image_id
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return path
