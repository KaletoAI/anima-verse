"""Player photo preflight, shutter snapshot and tracked background workers.

Like model-reference renders, workers are in-process daemon threads. The
regenerate pipeline retains ownership of backend-channel scheduling. Results
use stored notifications: sync sends only the recipient's notices topic.
"""
import contextvars
import random
import threading
import uuid
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.log import get_logger

logger = get_logger("scene_photo_jobs")
_workers: dict[str, threading.Thread] = {}
_lock = threading.Lock()


class PhotoLora(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = Field(min_length=1, max_length=200)
    strength: float = Field(default=1.0, allow_inf_nan=False)


class PhotoRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    prompt: str = ""
    backend: str = ""
    negative_prompt: str = ""
    loras: Optional[list[PhotoLora]] = None
    character_names: Optional[list[str]] = Field(default=None, max_length=128)
    use_room: bool = True
    pose_check: Optional[bool] = None
    reference_image_id: str = ""
    secret: bool = False


def validate_request(body) -> PhotoRequest:
    try:
        return PhotoRequest.model_validate(body)
    except ValidationError as exc:
        # No render, discovery or charge may precede body validation.
        raise HTTPException(422, "Invalid photo request") from exc


def _snapshot(avatar: str, options: PhotoRequest, user_id: str) -> dict:
    from app.core.chat_ops import resolve_owned_chat_upload_path
    from app.models.character import get_character_current_location, get_character_current_room
    from app.core.room_entry import characters_in_room
    from app.core.interaction_engine import get_interaction
    from app.core.scene_photo import _room_transcript

    source = (str(resolve_owned_chat_upload_path(options.reference_image_id, user_id))
              if options.reference_image_id else "")
    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    if not loc:
        raise HTTPException(409, "Avatar has no location.")
    present = list(dict.fromkeys(characters_in_room(loc, room) or []))
    others = [n for n in present if n != avatar]
    defaults = others + [avatar] if others and get_interaction(avatar) else others or [avatar]
    selected = (options.character_names if options.character_names or
                (source and options.character_names == []) else defaults)
    subjects = list(dict.fromkeys(n for n in selected if n in present))
    return {"photo_id": uuid.uuid4().hex, "location": loc, "room": room,
            "subjects": subjects, "present": present, "source_path": source,
            "transcript": _room_transcript(avatar, loc, room), "discovered_by": []}


def accept_photo(avatar: str, options: PhotoRequest, user_id: str,
                 skill_id: Optional[str]) -> dict:
    """Blocking preflight only; the async route calls this off the event loop."""
    from app.core.lora_library import LoraNotAllowedError, assert_loras_allowed
    from app.core.explicit_backend import require_explicit_backend
    from app.imagegen.base import media_generation_enabled
    from app.imagegen.service import get_image_service, render_has_reference_image
    from app.imagegen.routing import resolve_image_route, NoRouteError

    # Ownership and cheap world validation precede any backend probing.
    snapshot = _snapshot(avatar, options, user_id)
    if not media_generation_enabled():
        raise HTTPException(409, "Media generation is disabled for this world")
    if not get_image_service().enabled:
        raise HTTPException(503, "Image service not available")
    has_ref = bool(snapshot["source_path"]) or render_has_reference_image(avatar)
    if options.backend.strip():
        backend = require_explicit_backend(options.backend.strip(), has_input_image=has_ref)
        try:
            assert_loras_allowed(backend, [l.model_dump() for l in options.loras or []])
        except LoraNotAllowedError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        try:
            resolve_image_route("photo", character=avatar, has_ref=has_ref,
                                advance_rotation=False)
        except NoRouteError as exc:
            raise HTTPException(503, str(exc)) from exc

    # The shutter event is independent of whether the later image succeeds.
    if options.secret and snapshot["room"]:
        from app.core.scene_photo_watch import discovery_chance, discover_photo
        for watcher in snapshot["present"]:
            if watcher == avatar:
                continue
            chance = discovery_chance(watcher, depicted=watcher in snapshot["subjects"])
            if chance > 0 and random.random() < chance and discover_photo(
                    avatar, snapshot["photo_id"], snapshot["subjects"], watcher,
                    snapshot["location"], snapshot["room"]):
                snapshot["discovered_by"].append(watcher)

    photo_id = snapshot["photo_id"]
    # Copy auth/job context just as to_thread does; a worker must never inherit
    # another request's identity when it eventually enters a backend channel.
    context = contextvars.copy_context()
    worker = threading.Thread(target=context.run, args=(
        _render, avatar, options, user_id, skill_id, snapshot),
        name=f"scene-photo-{photo_id}", daemon=True)
    with _lock:
        _workers[photo_id] = worker
    try:
        worker.start()
    except Exception:
        with _lock:
            _workers.pop(photo_id, None)
        raise
    return {"status": "accepted", "photo_id": photo_id,
            "discovered_by": snapshot["discovered_by"]}


def _render(avatar: str, options: PhotoRequest, user_id: str,
            skill_id: Optional[str], snapshot: dict) -> None:
    from app.core.scene_photo import take_scene_photo
    from app.core.skill_gate import charge
    from app.core.i18n import t
    from app.models.character import get_character_language
    from app.models.notifications import create_notification

    photo_id = snapshot["photo_id"]
    try:
        lang = get_character_language(avatar)
        try:
            result = take_scene_photo(avatar, prompt=options.prompt,
                backend_name=options.backend, loras=[l.model_dump() for l in options.loras or []],
                negative_prompt=options.negative_prompt, character_names=options.character_names,
                use_room=options.use_room, pose_check=options.pose_check,
                reference_image_id=options.reference_image_id, user_id=user_id,
                secret=options.secret, snapshot=snapshot)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Photo failed.")
            if skill_id is not None:
                charge(avatar, skill_id)
        except Exception as exc:
            logger.warning("Scene photo %s failed: %s", photo_id, exc)
            content = t(str(getattr(exc, "detail", exc)) or "Photo failed.", lang)
            metadata = {"photo_id": photo_id, "status": "failed"}
        else:
            content = t("Photo ready", lang)
            metadata = {"photo_id": photo_id, "status": "ready",
                        "filename": result["filename"], "url": result["url"]}
        if not create_notification(avatar, content, "scene_photo", metadata):
            logger.error("Could not store scene photo completion %s", photo_id)
    finally:
        with _lock:
            _workers.pop(photo_id, None)
