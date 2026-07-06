"""Chat-domain operations behind app/routes/chat.py.

Logic moved 1:1 out of the route handlers (code-review section 5c); the routes
remain thin HTTP adapters (auth, request parsing, response types, FileResponse/
StreamingResponse). HTTPExceptions embedded mid-logic moved along unchanged.
Shared helpers that stay in app/routes/chat.py (external importers rely on them)
are pulled in via function-scope lazy imports to avoid a module-level cycle.
"""
import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from app.core.log import get_logger

logger = get_logger("chat")

from app.core.timeutils import utc_now
from app.core.dependencies import get_skill_manager
from app.core.paths import get_storage_dir as _get_storage_dir
from app.models.chat import get_chat_history
from app.models.character import (
    get_character_config,
    get_character_current_location,
    get_character_current_room,
    get_character_images_dir,
    get_effective_activity,
    list_available_characters,
)
from app.models.world import get_location
from app.models.account import get_user_profile

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _get_chat_upload_dir() -> Path:
    # Duplicated 1:1 from app/routes/chat.py: the original stays there because
    # resolve_chat_image()/the SSE generator (both non-moving) still use it.
    d = _get_storage_dir() / "chat_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d



def delete_chat_history_core(days: int, character: str = "") -> Dict[str, Any]:
    """Delete chat messages from the last ``days`` days (see route docstring)."""
    if days is None or int(days) < 1:
        raise HTTPException(status_code=400, detail="days >= 1 required")
    from datetime import datetime, timedelta
    from app.core.db import get_connection, transaction
    cutoff = (utc_now() - timedelta(days=int(days))).isoformat()

    char = (character or "").strip()
    if char:
        sql = ("DELETE FROM chat_messages WHERE ts >= ? "
               "AND (character_name = ? OR partner = ?)")
        params = (cutoff, char, char)
    else:
        sql = "DELETE FROM chat_messages WHERE ts >= ?"
        params = (cutoff,)

    with transaction() as conn:
        cur = conn.execute(sql, params)
        deleted = cur.rowcount or 0

    logger.info("chat history deleted: days=%d cutoff=%s character=%r → %d rows",
                int(days), cutoff, char, deleted)
    return {
        "deleted": int(deleted),
        "character": char,
        "days": int(days),
        "cutoff": cutoff,
    }


def build_chat_history(limit: int = 2, offset: int = 0, since_id: int = 0) -> Dict[str, Any]:
    """Return the last N chat messages for the current chat partner."""
    from app.routes.chat import _get_chat_partner
    current_agent = _get_chat_partner()
    if not current_agent:
        return {"messages": [], "agent_name": "", "total": 0}

    history = get_chat_history(current_agent)
    if not history:
        return {"messages": [], "agent_name": current_agent, "total": 0}

    total = len(history)
    if since_id:
        last_messages = [m for m in history if (m.get("id") or 0) > since_id]
    elif offset:
        last_messages = history[-(limit + offset):-offset] if (limit + offset) <= total else history[:max(0, total - offset)]
    else:
        last_messages = history[-limit:] if limit else history

    # Clean the hallucinated send-message template prefix from the displayed
    # history ([Name, ]deine Antwort: "..."). The prefix came from the old
    # send_message hint and is present in many existing messages.
    _meta_re = re.compile(
        r'^(?:[A-Z][\wÄÖÜäöüß \-]{0,30},\s*)?(?:deine|meine|seine|ihre)\s+Antwort:\s*[\'\"]?',
        re.IGNORECASE)
    cleaned_messages = []
    for m in last_messages:
        if m.get("role") == "assistant":
            c = m.get("content", "")
            cleaned = _meta_re.sub('', c).rstrip("'\"").strip()
            if cleaned and cleaned != c:
                m = dict(m)
                m["content"] = cleaned
        cleaned_messages.append(m)
    return {"messages": cleaned_messages, "agent_name": current_agent, "total": total}


async def build_unread_summary() -> Dict[str, Any]:
    """Per-character latest assistant-message timestamps for unread badges."""
    from app.models.account import get_player_identity
    avatar = get_player_identity("")
    if not avatar:
        return {"avatar": "", "chats": {}}

    from app.core.db import get_connection
    try:
        conn = get_connection()
        # Per character: fetch all assistant timestamps from the last 7 days.
        # Limit 30 per character to keep the response compact.
        rows = conn.execute(
            "SELECT character_name, ts FROM chat_messages "
            "WHERE partner=? AND role='assistant' AND character_name<>? "
            "  AND ts > datetime('now', '-7 days') "
            "ORDER BY ts DESC LIMIT 500",
            (avatar, avatar)).fetchall()
        per_char: Dict[str, Dict[str, Any]] = {}
        for char, ts in rows:
            if not char:
                continue
            slot = per_char.setdefault(char, {"latest": "", "recent": []})
            if not slot["latest"]:
                slot["latest"] = ts or ""
            if len(slot["recent"]) < 30:
                slot["recent"].append(ts or "")
        chats = per_char
    except Exception as e:
        return {"avatar": avatar, "chats": {}, "error": str(e)}
    return {"avatar": avatar, "chats": chats}


async def save_chat_upload(request) -> Dict[str, Any]:
    """Store an uploaded chat image and return a temporary image ID."""
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        raise HTTPException(status_code=400, detail="No file uploaded")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    image_id = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = _get_chat_upload_dir() / image_id
    content = await file.read()
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


async def detect_chat_characters_core(request) -> Dict[str, Any]:
    """Detect characters mentioned in text plus all available ones."""
    data = await request.json()
    user_id = data.get("user_id", "")
    agent_name = data.get("agent_name", "")
    text = data.get("text", "")

    if not agent_name:
        raise HTTPException(status_code=400, detail="user_id and agent_name required")

    # Detected persons from text
    from app.core.prompt_builder import PromptBuilder as _PB
    _det_persons = _PB(agent_name).detect_persons(text) if text else []
    detected = [{"name": p.name, "appearance": p.appearance} for p in _det_persons]
    detected_names = [p.name for p in _det_persons]

    # All available characters
    all_chars = list_available_characters()

    # Avatar = the character the user is currently controlling (if set).
    # When an avatar exists, IT represents the user in the image — the bare
    # login name (e.g. "admin") is NOT listed as an extra entry, that would
    # be a duplication. Only when no avatar is chosen (plain admin without a
    # role-play character) is the login name shown.
    from app.models.account import get_active_character
    avatar_name = (get_active_character() or "").strip()
    user_profile = get_user_profile()
    user_name = user_profile.get("user_name", "")

    available = []
    # Agent first
    if agent_name in all_chars:
        available.append({"name": agent_name, "type": "agent"})
    # Avatar as "you" (instead of login name)
    if avatar_name and avatar_name != agent_name:
        available.append({"name": avatar_name, "type": "user"})
    elif not avatar_name and user_name:
        # No avatar — login name as fallback "you"
        available.append({"name": user_name, "type": "user"})
    # Other characters
    for c in all_chars:
        if c == agent_name or c == avatar_name:
            continue
        available.append({"name": c, "type": "character"})

    # Rooms of the current location
    rooms = []
    current_room_id = ""
    location_id = get_character_current_location(agent_name) or ""
    if location_id:
        loc_data = get_location(location_id)
        if loc_data:
            for room in loc_data.get("rooms", []):
                rooms.append({"id": room.get("id", ""), "name": room.get("name", "")})
        current_room_id = get_character_current_room(agent_name) or ""

    return {
        "detected": detected_names,
        "available": available,
        "rooms": rooms,
        "current_room_id": current_room_id,
        "location_id": location_id,
    }


async def visualize_core(request) -> Dict[str, Any]:
    """Generate an image from a bot message."""
    from app.routes.chat import _generate_image_prompt, _generate_visualization_image
    data = await request.json()
    user_id = data.get("user_id", "")
    agent_name = data.get("agent_name", "")
    text = data.get("text", "")
    workflow = data.get("workflow", "")
    backend = data.get("backend", "")
    loras = data.get("loras")  # Optional: [{name, strength}, ...]
    model_override = data.get("model_override", "").strip()
    character_names = data.get("character_names")  # Optional: explicit character selection
    item_ids = data.get("item_ids") or []  # Optional: flagged room items as props

    if not agent_name or not text:
        raise HTTPException(status_code=400, detail="user_id, agent_name and text required")

    logger.info("Start: agent=%s text=%s...", agent_name, text[:80])

    # Strip mood and location line (sometimes comes along in the frontend text)
    text = re.sub(r'\n?\*{0,2}I feel\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\n?\*{0,2}I am at\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\n?\*{0,2}I do\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()

    # 1. Collect appearances via PromptBuilder
    from app.core.prompt_builder import (
        PromptBuilder, is_photographer_mode, detect_selfie)
    _builder = PromptBuilder(agent_name)
    if character_names is not None:
        persons = _builder.detect_persons(text, character_names=character_names)
        logger.info("Explizite Character-Auswahl: %s", character_names)
    else:
        persons = _builder.detect_persons(text)

    agent_config_early = get_character_config(agent_name)
    is_photographer = is_photographer_mode(agent_name)
    is_selfie = detect_selfie(text)

    # Photographer filter centrally via the builder. Provides the subjects for
    # the LLM prompt generation; appearances stays the full list for the
    # response (character_names) and execute() applies the filter idempotently
    # again.
    llm_persons = _builder.apply_photographer_filter(
        persons,
        photographer_mode=is_photographer,
        is_selfie=is_selfie,
        set_profile=False)

    appearances = [{"name": p.name, "appearance": p.appearance} for p in persons]
    llm_appearances = [{"name": p.name, "appearance": p.appearance} for p in llm_persons]
    logger.debug("Appearances: %s", [p.name for p in persons])

    # 2. Build scene context from character state (location + activity only)
    scene_parts = []
    try:
        raw_location = get_character_current_location(agent_name)
        if raw_location:
            loc_data = get_location(raw_location)
            loc_name = loc_data.get("name", raw_location) if loc_data else raw_location
            loc_desc = loc_data.get("description", "") if loc_data else ""
            scene_parts.append(f"Location: {loc_name}" + (f" ({loc_desc})" if loc_desc else ""))

        raw_activity = get_effective_activity(agent_name)
        if raw_activity:
            scene_parts.append(f"Activity: {raw_activity}")
    except Exception as e:
        logger.error("Szenen-Kontext Fehler: %s", e)

    setting_context = "Setting: " + ", ".join(scene_parts) if scene_parts else ""

    # 3. Determine backend-specific prompt instructions (image family from
    #    the backend the spec resolves to).
    workflow_instruction = ""
    workflow_image_model = ""
    if workflow:
        sm = get_skill_manager()
        for skill in sm.skills:
            if skill.__class__.__name__ == "ImageGenerationSkill":
                _be = skill.resolve_imagegen_target(workflow)
                if _be:
                    from app.core import config as _cfg
                    workflow_image_model = getattr(_be, "image_family", "") or ""
                    workflow_instruction = _cfg.resolve_use_case_style(
                        "character", workflow_image_model,
                        backend_model=getattr(_be, "model", "") or "",
                    ).get("prompt_instruction", "")
                break

    # Generate image prompt via LLM (with scene context)
    agent_config = agent_config_early

    logger.debug("Generiere Image-Prompt via LLM...")
    image_prompt = await asyncio.to_thread(
        _generate_image_prompt, text, llm_appearances,
        setting_context, agent_config, workflow_image_model, workflow_instruction,
        is_photographer)
    if not image_prompt:
        logger.error("Image-Prompt leer")
        return {"error": "Failed to generate image prompt"}

    logger.debug("Image-Prompt: %s...", image_prompt[:120])

    # 4. Generate image via ImageGenerationSkill
    #    When explicit character_names are set: pass appearances through so
    #    execute() uses them instead of auto-detection
    vis_appearances = appearances if character_names is not None else None
    logger.debug("Generiere Bild via ImageGenerationSkill...")
    result = await asyncio.to_thread(
        _generate_visualization_image, agent_name, image_prompt,
        vis_appearances, workflow, backend, loras, model_override, item_ids)

    # Insert character names into the response (for regeneration)
    result["character_names"] = [p["name"] for p in appearances]

    logger.debug("Ergebnis: %s", list(result.keys()))
    return result


async def instagram_post_core(request) -> Dict[str, Any]:
    """Generate an image from a bot message and create an Instagram post."""
    from app.routes.chat import (_generate_image_prompt, _extract_image_description_from_text, _extract_caption_from_text)
    data = await request.json()
    user_id = data.get("user_id", "")
    agent_name = data.get("agent_name", "")
    text = data.get("text", "")

    if not agent_name or not text:
        raise HTTPException(status_code=400, detail="user_id, agent_name and text required")

    # Strip thought-message prefix (internal metadata)
    text = re.sub(r'^\[Gedanken-Nachricht[^\]]*\]\s*', '', text).strip()
    # Strip mood, location line and token metadata (sometimes come along in the frontend text)
    text = re.sub(r'\n?\*{0,2}I feel\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\n?\*{0,2}I am at\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\n?\*{0,2}I do\s+[^*\n]+\*{0,2}\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\n?\d{2}:\d{2}.*?Tokens:.*$', '', text, flags=re.MULTILINE).strip()
    # Strip assignment tags (internal metadata, not for posts)
    from app.models.assignments import strip_assignment_tags
    text = strip_assignment_tags(text)

    logger.info("Instagram-Post starte fuer %s", agent_name)

    # 1. Image prompt: first extract from the bot answer, fall back to LLM
    image_prompt = _extract_image_description_from_text(text)
    use_auto_enhance = True
    explicit_appearances = None

    if not image_prompt:
        # LLM generates the prompt — check appearances first (smart detection)
        from app.core.prompt_builder import PromptBuilder as _PB_IG
        _ig_persons = _PB_IG(agent_name).detect_persons(text)
        appearances = [{"name": p.name, "appearance": p.appearance} for p in _ig_persons]
        agent_config = get_character_config(agent_name)

        image_prompt = await asyncio.to_thread(
            _generate_image_prompt, text, appearances,
            "", agent_config)
        if not image_prompt:
            return {"error": "Failed to generate image prompt"}
        use_auto_enhance = False
    else:
        agent_config = get_character_config(agent_name)
        from app.core.prompt_builder import PromptBuilder as _PB_IG2
        _ig_persons2 = _PB_IG2(agent_name).detect_persons(image_prompt)
        explicit_appearances = [{"name": p.name, "appearance": p.appearance} for p in _ig_persons2]

    logger.debug("Instagram-Post Image-Prompt: %s", image_prompt[:150])

    # 2. Generate image via ImageGenerationSkill (skip_gallery=True — not in chat gallery)
    sm = get_skill_manager()
    img_skill = None
    for skill in sm.skills:
        if skill.__class__.__name__ == "ImageGenerationSkill":
            img_skill = skill
            break

    if not img_skill:
        return {"error": "ImageGenerationSkill not available"}

    img_payload = {
        "prompt": image_prompt,
        "agent_name": agent_name,
        "user_id": "",
        "set_profile": False,
        "skip_gallery": True,
        "auto_enhance": use_auto_enhance,
    }
    if explicit_appearances is not None:
        img_payload["appearances"] = explicit_appearances
    input_json = json.dumps(img_payload)

    result_text = await asyncio.to_thread(img_skill.execute, input_json)
    logger.debug("Instagram-Post ImageGen Result: %s", result_text[:200])

    # Extract image URL and filename
    image_urls = re.findall(r'!\[.*?\]\((\/characters\/[^)]+)\)', result_text)
    if not image_urls:
        return {"error": "Image generation failed"}

    image_url = image_urls[0]
    filename_match = re.search(r'/images/([^?]+)', image_url)
    if not filename_match:
        return {"error": "Could not extract filename from generated image"}
    image_filename = filename_match.group(1)

    # Determine image path
    images_dir = get_character_images_dir(agent_name)
    image_path = images_dir / image_filename

    # 3. Generate caption — depending on caption_mode
    caption_mode = data.get("caption_mode", "vision")
    caption = None

    if caption_mode == "text":
        # Chat text as caption basis
        logger.debug("Caption aus Chat-Text extrahieren...")
        caption = _extract_caption_from_text(text)

    if not caption:
        # Vision LLM: analyze image and generate caption
        logger.debug("Caption via Vision-LLM (Bildanalyse)...")
        insta_skill = None
        for skill in sm.skills:
            if skill.__class__.__name__ == "InstagramSkill":
                insta_skill = skill
                break

        if insta_skill:
            current_location = get_character_current_location(agent_name)
            current_activity = get_effective_activity(agent_name)

            caption = await asyncio.to_thread(
                insta_skill._generate_caption,
                str(image_path), agent_name, "",
                current_location, current_activity, text
            )

    if not caption:
        caption = f"#{agent_name} #ai"

    hashtags = re.findall(r'#(\w+)', caption)

    # 4. Copy image to Instagram + create post
    from app.models.instagram import create_post, get_instagram_dir

    import shutil
    instagram_dir = get_instagram_dir()
    dst_path = instagram_dir / image_filename

    if not dst_path.exists():
        shutil.copy2(str(image_path), str(dst_path))

    post = create_post(
        character_name=agent_name,
        image_filename=image_filename,
        caption=caption,
        hashtags=hashtags,
        image_prompt=image_prompt)

    image_post_url = f"/instagram/images/{image_filename}?user_id={user_id}"

    logger.info("Instagram-Post erstellt: %s", post['id'])
    logger.debug("Instagram-Post Caption: %s", caption[:100])

    return {
        "post_id": post["id"],
        "caption": caption,
        "image_url": image_post_url,
    }


def resolve_chat_upload_path(image_id: str) -> Path:
    """Validate an upload image ID and return its filesystem Path."""
    if ".." in image_id or "/" in image_id:
        raise HTTPException(status_code=400, detail="Invalid image ID")
    path = _get_chat_upload_dir() / image_id
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return path
