"""TTS routes - Text-to-Speech endpoints."""
import asyncio
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from app.core.log import get_logger

logger = get_logger("tts_route")

from app.core.tts_service import get_tts_service, clean_text_for_tts
from app.core.paths import get_storage_dir
from app.models.character import get_character_config

router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("/status")
def tts_status() -> Dict[str, Any]:
    """Returns TTS service availability and config info."""
    service = get_tts_service()
    return service.status_info()


@router.post("/speak")
async def speak(request: Request) -> Dict[str, Any]:
    """Generates audio on demand (button click).

    Request body:
        text: Text to speak
        user_id: User ID
        character_name: Character name
    """
    data = await request.json()
    text = data.get("text", "")
    user_id = data.get("user_id", "")
    character_name = data.get("character_name", "")

    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    service = get_tts_service()
    if not service.enabled:
        return {"error": "TTS is disabled"}

    # Per-character config
    agent_config = {}
    if user_id and character_name:
        agent_config = get_character_config(character_name)
    elif character_name:
        agent_config = get_character_config(character_name)
    tts_config = service.get_character_config(agent_config)

    # Optional preview overrides from the Character editor (unsaved draft values)
    override_model = data.get("model")
    override_voice = data.get("voice")
    override_param = data.get("param")
    model = str(override_model).strip() if override_model is not None else tts_config.get("model", "")
    param = str(override_param).strip() if override_param is not None else tts_config.get("param", "")
    if override_voice is not None:
        from app.core.tts_service import split_generic_voice
        voice, speaker_wav = split_generic_voice(str(override_voice), "")
    else:
        voice = tts_config.get("voice", "")
        speaker_wav = tts_config.get("speaker_wav", "")

    clean_text = clean_text_for_tts(text)
    if not clean_text.strip():
        return {"error": "No speakable text after cleanup"}

    audio_path = await asyncio.to_thread(
        service.generate,
        text=clean_text,
        voice=voice,
        speaker_wav=speaker_wav,
        language=tts_config.get("language", "de"),
        model=model,
        param=param)

    if audio_path and audio_path.exists():
        return {"audio_url": f"/tts/tmp/{audio_path.name}"}

    return {"error": "TTS generation failed"}


@router.get("/tmp/{filename}")
def serve_tts_audio(filename: str):
    """Serves a temporary TTS audio file."""
    # Security: filename only, no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = get_storage_dir() / "tmp" / "tts_audio" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

    low = filename.lower()
    media_type = "audio/wav"
    if low.endswith(".mp3"):
        media_type = "audio/mpeg"
    elif low.endswith(".flac"):
        media_type = "audio/flac"
    elif low.endswith(".ogg"):
        media_type = "audio/ogg"
    elif low.endswith(".opus"):
        media_type = "audio/opus"
    elif low.endswith(".aac"):
        media_type = "audio/aac"

    return FileResponse(path, media_type=media_type)


@router.get("/capabilities")
def tts_capabilities() -> Dict[str, Any]:
    """Returns discovered TTS models/aliases, preset voices, cloned voices, and controls."""
    service = get_tts_service()
    return service.capabilities()


@router.get("/speakers")
def list_speakers() -> Dict[str, Any]:
    """Listet verfuegbare Speaker-WAV-Dateien aus dem voices/ Verzeichnis."""
    from app.core.tts_service import list_local_cloned_voices
    speakers = [
        {"value": entry["path"], "label": entry["label"]}
        for entry in list_local_cloned_voices()
    ]
    return {"speakers": speakers}


@router.get("/voices")
def list_voices() -> Dict[str, Any]:
    """Listet verfuegbare TTS Voices (fuer das aktive Backend bzw. Default-Alias)."""
    service = get_tts_service()
    caps = service.capabilities()
    default_id = caps.get("default_model", "")
    voices: List[Dict[str, str]] = []
    for m in caps.get("models", []):
        if m.get("id") == default_id:
            voices = list(m.get("voices") or [])
            break
    if not voices and service.backend == "magpie" and service.magpie_voice:
        voices.append({"value": service.magpie_voice, "label": service.magpie_voice})
    return {"voices": voices}
