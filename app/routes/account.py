"""Account routes — character selection, switching and the account language.

Separates account management (which character to control) from auth (login/register).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Any, Dict

from app.core.log import get_logger
from app.core.auth_dependency import get_current_user
from app.models.account import (
    TRANSLATION_MODES,
    get_active_character,
    get_default_character,
    get_language_settings,
    save_language_settings,
    set_active_character)
from app.models.character import list_available_characters

logger = get_logger("account")

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/characters")
def list_characters(request: Request) -> Dict[str, Any]:
    """List characters the player can control (Avatar-faehige Characters).

    Chatbots (Template ohne playable_avatar Flag) werden ausgefiltert —
    sie existieren als NPCs aber koennen nicht der Spieler-Avatar sein.
    Fuer Nicht-Admins zusaetzlich nach allowed_characters filtern.
    """
    from app.core.auth_dependency import filter_characters
    from app.models.character_template import is_feature_enabled

    all_chars = list_available_characters()
    characters = [c for c in all_chars if is_feature_enabled(c, "playable_avatar")]
    characters = filter_characters(request, characters)

    active = get_active_character()
    default = get_default_character()

    return {
        "characters": characters,
        "active_character": active,
        "default_character": default,
    }


@router.post("/switch-character")
async def switch_character(request: Request) -> Dict[str, Any]:
    """Switch which character the player controls.

    The previous character becomes autonomous again; the new one loses autonomy.
    """
    from app.core.auth_dependency import user_can_access_character

    data = await request.json()
    character_name = data.get("character_name", "").strip()

    if not character_name:
        raise HTTPException(status_code=400, detail="character_name required")

    # Zugriffsrecht pruefen (Admin darf alle, User nur allowed_characters)
    if not user_can_access_character(request, character_name):
        raise HTTPException(
            status_code=403,
            detail=f"Kein Zugriff auf Character '{character_name}'")

    # Verify character exists AND is playable as avatar
    available = list_available_characters()
    if character_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_name}' not found")
    from app.models.character_template import is_feature_enabled
    if not is_feature_enabled(character_name, "playable_avatar"):
        raise HTTPException(
            status_code=400,
            detail=f"Character '{character_name}' ist kein Avatar (Template-Flag playable_avatar=false)")

    previous = get_active_character()
    set_active_character(character_name)

    from app.core.auth_dependency import get_current_user_optional
    user = get_current_user_optional(request)
    username = (user or {}).get("username", "(unknown)")
    logger.info(
        "Player %s switched from '%s' to '%s'",
        username, previous or "(none)", character_name)

    return {
        "status": "success",
        "previous_character": previous,
        "active_character": character_name,
    }


# --- Account language -------------------------------------------------------
#
# The account profile lives in the world DB (table ``account``, id=1), so these
# two settings are PER WORLD, not per user — every logged-in user of a world
# reads and writes the same pair. They moved here when the old /store surface
# of the vanilla UI was deleted (2026-09-21); the Player UI edits them under
# "Avatar settings → Preferences → Language".

@router.get("/language")
def get_account_language(user=Depends(get_current_user)) -> Dict[str, Any]:
    """Current account language + translation mode, plus the allowed options.

    The language list is the ONE source ``shared/config/languages.json``, the
    same one ``/i18n/languages`` serves and every prompt names its language
    from.
    """
    from app.core.i18n import list_languages

    settings = get_language_settings()
    return {
        **settings,
        "languages": [
            {"value": o.get("value", ""), "label": o.get("label", "")}
            for o in list_languages() if o.get("value")
        ],
        "translation_modes": list(TRANSLATION_MODES),
    }


@router.post("/language")
async def set_account_language(request: Request,
                               user=Depends(get_current_user)) -> Dict[str, Any]:
    """Change the account language and/or the translation mode.

    Both fields are optional; an omitted one keeps its current value. An
    unknown language code or mode is a 400 — the value would otherwise end up
    in a prompt ("Always respond in xx.").
    """
    import asyncio
    from app.core.i18n import list_languages

    data = await request.json()
    current = get_language_settings()

    lang = str(data.get("system_language", current["system_language"]) or "").strip()
    mode = str(data.get("translation_mode", current["translation_mode"]) or "").strip()

    known = {o.get("value") for o in list_languages() if o.get("value")}
    if lang not in known:
        raise HTTPException(status_code=400, detail=f"Unknown language '{lang}'")
    if mode not in TRANSLATION_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown translation mode '{mode}'")

    await asyncio.to_thread(save_language_settings, lang, mode)
    logger.info("Account language set to %s / %s", lang, mode)
    return {"status": "success", "system_language": lang, "translation_mode": mode}
