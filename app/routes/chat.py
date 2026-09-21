"""Chat routes — image upload/library plus the shared chat-prompt helpers.

The streaming 1:1 chat surface of the removed vanilla UI is gone (2026-09-21).
What stays here are the live upload routes and the prompt/marker helpers that
``core/chat_engine.py``, ``core/thoughts.py``, ``core/template_preview.py`` and
``routes/play.py`` import.
"""
import base64
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, NamedTuple, Optional
from fastapi import APIRouter, Request
from app.core.log import get_logger
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("chat")
from app.core.dependencies import get_skill_manager
from app.models.account import get_user_appearance
from app.core.outfit_renderer import render_outfit, render_unworn_slots
from app.models.character import (
    get_character_config,
    get_character_profile,
    get_character_appearance,
    get_character_language_instruction,
    get_character_current_location,
    get_effective_activity,
    get_character_current_room,
    save_character_current_feeling,
    get_character_images_dir)
from app.models.world import (get_location, get_room_by_id, get_location_name,
                              list_locations_for_character, resolve_location)
from app.models.character_template import (
    resolve_profile_tokens, get_template, build_prompt_section)
from app.models.memory import build_memory_prompt_section, record_mood as record_mood_history
from app.models.events import build_events_prompt_section
from app.utils.history_manager import build_daily_summary_prompt_section

router = APIRouter(prefix="/chat", tags=["chat"])


def _strip_tool_hallucinations(text: str) -> str:
    """Entfernt halluzinierte Tool-Tags aus LLM-Antworten.

    Chat-LLMs schreiben manchmal <tool name="..."> Tags als Text statt
    echte Tool-Calls. Diese muessen bereinigt werden bevor die Antwort
    gespeichert oder dem LLM als History praesentiert wird.
    """
    if not text:
        return text

    # Send-Message-Template-Halluzination: "[Name, ]deine Antwort: '...'"
    # vom alten Hint-Wording. Prefix abschneiden, den eigentlichen Inhalt behalten.
    _meta = re.match(
        r'^(?:[A-Z][\wÄÖÜäöüß \-]{0,30},\s*)?(?:deine|meine|seine|ihre)\s+Antwort:\s*[\'\"]?(.*)$',
        text, flags=re.IGNORECASE | re.DOTALL)
    if _meta:
        text = _meta.group(1).rstrip("'\"").strip()

    if "<tool" in text:
        # <tool name="...">...</tool> (geschlossen)
        text = re.sub(r'<tool\s+name="[^"]*">[\s\S]*?</tool>', '', text)
        # <tool name="...">... (ungeschlossen — bis naechstes <tool oder Textende)
        text = re.sub(r'<tool\s+name="[^"]*">[^<]*', '', text)
    # *An:* / *Betreff:* / *Text:* Bloecke (Notification-Halluzinationen)
    text = re.sub(r'\n\s*\*(?:An|Betreff|Text|Target|Message):\*\s*[^\n]*', '', text, flags=re.IGNORECASE)
    # Intent-Marker ([INTENT: …] / [INTENT_DONE: …] / [INTENT_PROGRESS: …]) —
    # interne Vorhaben-Metadaten, duerfen nicht im sichtbaren Text landen
    # (plan-intents-unified.md). Werden vorher bereits ausgewertet.
    try:
        from app.models.intents import strip_intent_markers
        text = strip_intent_markers(text)
    except Exception:
        pass
    # LLM-Tokenizer-Artefakte (jedes <|...|>, auch lowercase, + <SPECIAL_N>)
    text = re.sub(r'<\|[^|>]{0,60}\|>', '', text)
    text = re.sub(r'<SPECIAL_\d+>', '', text)
    # Mehrfache Leerzeilen
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# --- Chat Image Upload Endpoint ---

from app.core.paths import get_storage_dir as _get_storage_dir

def _get_chat_upload_dir() -> Path:
    d = _get_storage_dir() / "chat_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/{user_id}/upload-image")
async def upload_chat_image(request: Request) -> Dict[str, Any]:
    """Upload an image for use in chat. Returns a temporary image ID."""
    from app.core.chat_ops import save_chat_upload
    return await save_chat_upload(request)


@router.get("/{user_id}/upload-image/{image_id}")
def get_chat_upload(image_id: str):
    """Serve an uploaded chat image."""
    from fastapi.responses import Response
    from app.core.chat_ops import resolve_chat_upload_path
    path = resolve_chat_upload_path(image_id)
    ext = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext.lstrip("."), "image/png")
    return Response(content=path.read_bytes(), media_type=mime)


@router.get("/{user_id}/image-library")
def chat_image_library(character: str = None) -> Dict[str, Any]:
    """List images from character libraries for linking in chat.

    If character is specified, returns only that character's images.
    Otherwise returns images from all characters.
    """
    from app.core.chat_ops import build_chat_image_library
    return build_chat_image_library(character)



def _generate_image_prompt(
    text: str, appearances: List[Dict[str, str]],
    setting_context: str = "",
    agent_config: Dict[str, Any] = None, image_model: str = "",
    prompt_instruction: str = "",
    photographer_mode: bool = False,
    outdoor_conditions: str = "") -> str:
    """Generate an image prompt via the router (task: image_prompt).

    ``outdoor_conditions`` is the world calendar's weather + time of day for
    an OPEN-AIR scene (``prompt_compose.outdoor_conditions``); it stays empty
    indoors and for story renders, which play in their own setting.
    """
    # Character-Kontext fuer Pronomen-Aufloesung
    _agent_name = (agent_config or {}).get("name", "")
    _user_name = ""
    try:
        from app.models.account import get_player_identity as _gpi
        _user_name = _gpi("")
    except Exception:
        pass

    # Pronomen-Mapping aufbauen: "Ich/mir/mich" = Agent, "Du/dir/dich" = User
    identity_lines = []
    if _agent_name:
        identity_lines.append(
            f'In the text, first-person pronouns ("Ich", "mir", "mich", "mein") refer to {_agent_name}.'
        )
    if _user_name:
        identity_lines.append(
            f'Second-person pronouns ("Du", "dir", "dich", "dein") refer to {_user_name}.'
        )
    identity_context = " ".join(identity_lines)

    # Workflow-spezifische Anweisungen
    model_context = f"The target image model is: {image_model}. " if image_model else ""
    instruction_context = f"{prompt_instruction} " if prompt_instruction else ""

    # Photographer-Kontext: Agent ist Fotograf, nicht im Bild
    _agent_name = (agent_config or {}).get("name", "")
    photographer_context = ""
    if photographer_mode and _agent_name:
        photographer_context = (
            f"IMPORTANT: {_agent_name} is the PHOTOGRAPHER and is NOT visible in the image. "
            f"Do NOT describe {_agent_name} or any of their actions (camera, photographing, etc.). "
            "Only describe the subjects who are being photographed. "
        )

    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        _agent_name = (agent_config or {}).get("name", "")
        characters_present_block = ""
        if appearances:
            # Nur Namen senden – das LLM braucht sie fuer Pronomen-Aufloesung.
            # Volle Appearance-Texte werden spaeter vom ImageGenerationSkill
            # in den Prompt eingefuegt; hier wuerden sie vom LLM oft dupliziert.
            app_names = ", ".join(p["name"] for p in appearances)
            characters_present_block = f"Characters present: {app_names}"

        system_prompt, human_msg = render_task(
            "image_prompt_scene",
            model_context=model_context,
            instruction_context=instruction_context,
            photographer_context=photographer_context,
            identity_context=identity_context,
            scene_text=text,
            setting_block=setting_context,
            outdoor_conditions=outdoor_conditions,
            characters_present_block=characters_present_block)

        response = llm_call(
            task="image_prompt",
            system_prompt=system_prompt,
            user_prompt=human_msg,
            agent_name=_agent_name)
        return (response.content or "").strip()
    except Exception as e:
        logger.error("LLM error: %s", e)
        return ""




# --- Vision Analysis for Chat Images ---

def _analyze_chat_image(image_path: str, agent_name: str, user_text: str = "") -> Optional[str]:
    """Analyze an image with the vision LLM and return a description.

    Used when user attaches an image to a chat message. The description is
    injected into the user message so the chat LLM can react to it.
    """
    from app.core.llm_router import resolve_llm

    if not os.path.exists(image_path):
        logger.warning("Chat image not found: %s", image_path)
        return None

    try:
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    except Exception as e:
        logger.error("Error loading chat image: %s", e)
        return None

    # Vision-LLM via Router (Task: image_recognition)
    instance = resolve_llm("image_recognition", agent_name=agent_name)
    if not instance:
        logger.warning("No image_recognition LLM available for chat image analysis")
        return None

    llm = instance.create_llm(temperature=0.3, max_tokens=500)

    # Get character language for the analysis
    lang_instruction = get_character_language_instruction(agent_name)
    analysis_lang = "German" if "deutsch" in lang_instruction.lower() or "german" in lang_instruction.lower() else "English"

    prompt_text = (
        "Describe this image in detail. Include:\n"
        "- People: appearance, clothing, pose, expression\n"
        "- Setting: location, environment, lighting\n"
        "- Objects and activities visible\n"
        "- Overall mood and atmosphere\n\n"
        "Be factual and objective. Respond ONLY with the description, "
        "no formatting, no markdown, no quotes. 2-4 sentences."
    )

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "gif": "gif"}.get(ext, "png")
    image_url = f"data:image/{mime};base64,{base64_image}"

    messages = [
        {"role": "system", "content": f"You MUST answer in {analysis_lang}. This is mandatory."},
        {"role": "user", "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]},
    ]

    try:
        from app.core.llm_queue import get_llm_queue, Priority
        response = get_llm_queue().submit(
            task_type="image_recognition",
            priority=Priority.HIGH,
            llm=llm,
            messages_or_prompt=messages,
            agent_name=agent_name)
        text = response.content.strip()
        logger.info("Chat image analysis complete: %d chars", len(text))
        return text if text else None
    except Exception as e:
        logger.error("Vision LLM error for chat image: %s", e)
        return None


def resolve_chat_image(image_id: str = "", image_url: str = "") -> tuple[str, str]:
    """Resolve an attached chat image to (filesystem_path, display_url).

    Shared by the legacy /chat endpoint and the room-based /play/say flow.
    ``image_id`` points at an upload (chat_uploads), ``image_url`` at a
    character-library image (/characters/{name}/images/{file}). Returns
    ("", "") when nothing resolves (missing/invalid path).
    """
    if image_id:
        if ".." in image_id or "/" in image_id:
            return "", ""
        path = _get_chat_upload_dir() / image_id
        if path.exists():
            # The serve route is /chat/{user_id}/upload-image/{id}; user_id is
            # ignored, so a fixed segment is fine for the display URL.
            return str(path), f"/chat/me/upload-image/{image_id}"
        return "", ""
    if image_url:
        import urllib.parse
        parsed = urllib.parse.urlparse(image_url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "characters" and parts[2] == "images":
            char_name = parts[1]
            img_file = "/".join(parts[3:])
            if ".." in img_file or ".." in char_name:
                return "", ""
            resolved = get_character_images_dir(char_name) / img_file
            if resolved.exists():
                return str(resolved), image_url
    return "", ""


def analyze_chat_image_blocking(image_path: str, agent_name: str = "",
                                user_text: str = "") -> Optional[str]:
    """Synchronous wrapper around _analyze_chat_image for non-streaming callers.

    /play/say resolves and analyses the image inline (only when one is
    attached) so the description is part of the utterance BEFORE the
    perceiving agents are bumped.
    """
    return _analyze_chat_image(image_path, agent_name, user_text)


# ---------------------------------------------------------------------------
# Post-stream helpers — moved out of generate() for readability
# ---------------------------------------------------------------------------

def _current_activity_hint(character_name: str, location_id: str) -> str:
    """The room's PLACE OFFER — markers first (free seats with their poses,
    busy ones by name), the room's free-text hint as the tail
    (``places.room_offer``). Replaces the earlier activity-name list: the
    room offers, the LLM decides freely.
    """
    if not location_id:
        return ""
    try:
        from app.core import places
        return places.room_offer(character_name, location_id,
                                 get_character_current_room(character_name) or "")
    except Exception:
        return ""


def _extract_mood(agent_name: str, response: str) -> Optional[str]:
    """Extrahiert Mood aus LLM-Antwort. Returns mood string or None."""
    config = get_character_config(agent_name)
    if not config.get("mood_tracking", False):
        return None
    # Primaer: **I feel <emotion>** ODER lokalisiert **Ich f\u00FChle <emotion>**
    match = re.search(r'\*\*\s*(?:I\s+feel|Ich\s+f[\u00FCu]hle)\s+(.+?)\*\*', response, re.IGNORECASE)
    # Fallback: letztes **<emotion>** am Ende der Antwort
    if not match:
        match = re.search(
            r'\*\*([A-Za-z\u00C0-\u00FF][a-z\u00E0-\u00FF]+(?:\s+[a-z\u00E0-\u00FF]+)*)[.?!]*\*\*\s*$',
            response
        )
    if not match:
        return None
    mood = match.group(1).strip().rstrip('.!,')
    # Falls der Fallback die ganze Phrase fing (\u201EIch f\u00FChle aggressiv"), den
    # Gef\u00FChls-Vorsatz wegnormalisieren \u2192 nur die Emotion als State.
    mood = re.sub(r'^(?:I\s+feel|Ich\s+f[\u00FCu]hle)\s+', '', mood, flags=re.IGNORECASE).strip()
    save_character_current_feeling(agent_name, mood)
    # Mood-History aufzeichnen
    try:
        record_mood_history(agent_name, mood)
    except Exception as mh_err:
        logger.error("Mood history error: %s", mh_err)
    logger.info("Mood %s: %s", agent_name, mood)
    return mood


def _marker_travel_refusal(agent_name: str) -> str:
    """Why the ``**I am at …**`` marker may NOT start a journey — "" = it may.

    The marker travels only for a character that cannot travel any other way:

    * ``has_movement_verb`` — whoever has SetLocation uses it; a second path
      for the same thing is what kept a party standing;
    * ``party_follower`` — a follower is dragged along by its leader and must
      not set out on its own. The verb is hidden from it for exactly that
      reason, so "has no verb" alone would say the opposite here;
    * ``player_avatar`` — the avatar travels over the /play route, not
      through a chat reply.
    """
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(agent_name):
            return "player_avatar"
        from app.core.party_engine import is_party_follower
        if is_party_follower(agent_name):
            return "party_follower"
        from app.core.dependencies import get_skill_manager
        skills = get_skill_manager()._get_agent_skills(agent_name, check_limits=False)
        if any(getattr(s, "SKILL_ID", "") == "setlocation" for s in skills):
            return "has_movement_verb"
        return ""
    except Exception as e:
        logger.debug("marker-travel check failed for %s: %s", agent_name, e)
        return "check_failed"


def _may_travel_by_marker(agent_name: str) -> bool:
    """True when the marker may start a journey (see the reason function)."""
    return not _marker_travel_refusal(agent_name)


def _extract_location(agent_name: str, response: str) -> Optional[Dict[str, str]]:
    """Extrahiert Location aus LLM-Antwort. Returns {'name': ..., 'id': ...} or None.

    Wenn der Chat-Character den Ort wechselt, geht der Spieler-Avatar
    automatisch mit (gemeinsam einen Ort besuchen).
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import save_character_current_room
    from app.models.account import get_active_character
    from app.models.world import get_location_by_id, get_room_by_name
    match = re.search(r'\*\*I\s+am\s+at\s+(.+?)\*\*', response, re.IGNORECASE)
    if not match:
        return None
    new_name = match.group(1).strip().rstrip('.!,')
    old_loc = get_character_current_location(agent_name)

    def _move_avatar_room(room_id: str):
        """Avatar geht mit dem Chat-Character mit (Raum-Wechsel innerhalb
        derselben Location). Location-Follow ist bewusst abgeschaltet."""
        player = get_active_character()
        if player and player != agent_name:
            player_loc = get_character_current_location(player)
            agent_loc = get_character_current_location(agent_name)
            # Nur mitgehen wenn sie an der gleichen Location sind — sonst
            # wuerde der Avatar in einen Raum gesetzt, der nicht zu seiner
            # Location gehoert.
            if player_loc and player_loc == agent_loc:
                # THE AVATAR-STATE LOCK of this avatar (``core.keyed_lock``),
                # the very one ``POST /play/enter-room`` and the position
                # report take: all three write where the avatar is standing,
                # and ``save_character_current_room`` is a read-modify-write of
                # the whole profile. This path runs on the event loop while
                # those two run in the threadpool since 2026-08-24, so nothing
                # serializes them any more. Around the WRITE only — the LLM
                # work before it must not hold a lock.
                with keyed_lock("avatar_state", player):
                    save_character_current_room(player, room_id)
                logger.info("Avatar %s folgt %s -> Room %s", player, agent_name, room_id)

    # 1. Raum-Match: Ist es ein Raum an der aktuellen Location?
    if old_loc:
        current_loc_data = get_location_by_id(old_loc)
        if current_loc_data:
            room = get_room_by_name(current_loc_data, new_name)
            if room:
                room_id = room.get("id", "")
                old_room = get_character_current_room(agent_name)
                if room_id != old_room:
                    # Leave-Gate (Raum-Scope): Halluzinierter Raumwechsel
                    # in der Narrative darf Pinning-Rules nicht umgehen.
                    try:
                        from app.models.rules import check_leave as _chk_leave
                        _ok, _why = _chk_leave(agent_name, room_only=True,
                                                target_location_id=old_loc,
                                                target_room_id=room_id)
                        if not _ok:
                            try:
                                from app.models.character import record_access_denied
                                from app.models.world import get_location_name as _gln_chat
                                _cur_name = _gln_chat(old_loc) or old_loc
                                record_access_denied(agent_name, old_loc, _cur_name,
                                                      _why, action="leave")
                            except Exception:
                                logger.debug("record_access_denied(chat-room-leave) failed", exc_info=True)
                            logger.info("Chat-Raumwechsel %s blockiert (leave room): %s",
                                        agent_name, _why)
                            return None
                    except Exception as _rerr:
                        logger.debug("Chat room-leave-Check fehlgeschlagen: %s", _rerr)
                    # Same lock, keyed on the CHARACTER whose room is written
                    # (see ``_move_avatar_room`` above). Not nested with the
                    # avatar's: that write follows this one, it does not sit
                    # inside it — two narrow spans, never two locks at once.
                    with keyed_lock("avatar_state", agent_name):
                        save_character_current_room(agent_name, room_id)
                    _move_avatar_room(room_id)
                    logger.info("Room %s: %s -> %s (%s)", agent_name, old_room, room_id, new_name)
                    return {"name": new_name, "room": room_id, "location_id": old_loc}
                return None  # Schon im Raum

    # 2. Location match. The marker NEVER sets a place directly ("Lösung C",
    # 2026-06): that bypassed the pathfinder and teleported the character to
    # places and along ways it does not know. A room change at the CURRENT
    # place (section 1 above) stays instant; a real jump is the teleport spell.
    #
    # What the marker may do is START A JOURNEY — the same call SetLocation
    # makes, with the same knowledge gate on the target. It does that for a
    # character that has NO movement verb, because otherwise such a character
    # could never travel at all. Whoever has the verb keeps the tool as its one
    # way: two paths for one thing is what left a party standing.
    loc_obj = resolve_location(new_name)
    if loc_obj and loc_obj.get("id") and loc_obj["id"] != old_loc:
        refusal = _marker_travel_refusal(agent_name)
        if not refusal:
            from app.core.travel_engine import start_journey
            journey, reason = start_journey(agent_name, loc_obj["id"])
            if journey:
                logger.info(
                    "Marker journey for %s -> '%s' (%s): started, no tool of "
                    "its own", agent_name, new_name, loc_obj.get("id"))
            else:
                # unknown_target also means "the character does not know the
                # place" — the gate sits in start_journey, not here.
                logger.info("Marker journey for %s -> '%s' refused: %s",
                            agent_name, new_name, reason)
        else:
            logger.info(
                "Narrative place change for %s ignored: '%s' (%s) — %s",
                agent_name, new_name, loc_obj.get("name", new_name), refusal)
    else:
        # Neither a room at the current place nor a (different) world location.
        logger.info(
            "Location extract for %s ignored: '%s' is neither a room here nor "
            "a world location.", agent_name, new_name)
    return None


def _extract_activity(agent_name: str, response: str) -> Optional[str]:
    """Reads the ``**I do <key>: <detail>**`` marker of a reply.

    The key must be a catalog alias (``split_key_detail``); it is written
    exactly with the detail as display text. A marker without a usable key
    goes through the net (``unknown="resolve"``): resolver + candidate row,
    because a silently dropped pose is worse than a row in the Poses tab.
    Returns the marker text, or None when there is no marker, nothing
    changed, or the text names a two-person pose.
    """
    match = re.search(r'\*\*I\s+do\s+(.+?)\*\*', response, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).strip().rstrip('.!,')
    if not raw:
        return None
    from app.core.pose_catalog import PairPoseWithoutPartner, split_key_detail
    from app.models.character import (get_character_pose_flavor,
                                      get_character_pose_key,
                                      set_pose_key_detail)
    key, detail = split_key_detail(raw)
    if not key and raw.lower() == (get_character_pose_flavor(agent_name) or "").lower():
        # The same free text again: no second resolver pass, no candidate bump.
        return None
    if key and key == (get_character_pose_key(agent_name) or "") \
            and detail.lower() == (get_character_pose_flavor(agent_name) or "").lower():
        return None
    try:
        written = set_pose_key_detail(agent_name, key, detail, unknown="resolve")
    except PairPoseWithoutPartner as e:
        # RP prose claiming a two-person action is exactly what the pair verb
        # is for — narrating it does not make it happen. The pose is dropped;
        # the text itself stays in the answer.
        logger.info("Pose %s discarded: '%s' resolves to the two-person pose "
                    "'%s' — a pair is started via InteractWith",
                    agent_name, raw, e)
        return None
    if not written:
        return None
    logger.info("Pose %s: %r -> %s (%r)", agent_name, raw, written, detail[:60])
    return raw


def _apply_removed_pieces(character_name: str,
                          removed_names: List[str]) -> List[str]:
    """Equipped Pieces ablegen, deren Name in ``removed_names`` vorkommt.

    Match: case-insensitiver Vergleich gegen den Item-Namen. Pieces die nicht
    angelegt sind, werden ignoriert. Erfundene Namen (nicht equipped) werden
    ignoriert. Returns Liste der tatsaechlich abgelegten Eintraege "Name (slot)".

    Safety-Cap: wenn die Extraktion ALLE equipped Pieces gleichzeitig
    entfernen wuerde, ist das praktisch immer ein Outfit-Wechsel-Wunsch der
    via Tool laufen sollte — wir lassen das Outfit dann unveraendert (besser
    als komplett nackt). Echte "kompletter Strip"-Szenen (Sex/Bath/Sleep)
    machen die Pieces meist Stueck fuer Stueck ueber mehrere Antworten ab.
    """
    if not removed_names or not character_name:
        return []
    try:
        from app.models.inventory import (
            get_equipped_pieces, get_item, unequip_piece)
        eq = get_equipped_pieces(character_name) or {}
        if not eq:
            return []

        wanted = {n.strip().lower() for n in removed_names if n and n.strip()}
        if not wanted:
            return []

        # Anzahl distinct equipped Items (Multi-Slot zaehlt als 1)
        distinct_equipped = len({iid for iid in eq.values() if iid})
        if distinct_equipped >= 2 and len(wanted) >= distinct_equipped:
            logger.warning(
                "Chat-Extraktion [%s]: %d/%d Pieces sollen entfernt werden — "
                "vermutlich Outfit-Wechsel ohne Tool-Aufruf, ignoriere "
                "removed-Liste (Pieces: %s)",
                character_name, len(wanted), distinct_equipped,
                ", ".join(sorted(wanted))[:200])
            return []

        unequipped: List[str] = []
        for slot, iid in list(eq.items()):
            if not iid:
                continue
            it = get_item(iid)
            if not it:
                continue
            name = (it.get("name") or "").strip().lower()
            if not name or name not in wanted:
                continue
            r = unequip_piece(character_name, slot=slot, source="chat_extract")
            if r.get("status") == "ok":
                unequipped.append(f"{it.get('name', iid)} ({slot})")

        # KEIN Auto-Equip durch den Extractor — das wuerde manuell abgelegte
        # Pieces sofort wieder anziehen (Race-Condition mit Wardrobe-Aenderungen).
        # Anziehen laeuft ausschliesslich ueber ChangeOutfit-Skill oder Wardrobe-UI.

        if unequipped:
            logger.info("Chat-Extraktion [%s]: %d Piece(s) abgelegt: %s",
                         character_name, len(unequipped), ", ".join(unequipped))
            # Intent.forbidden_slots: die abgelegten Slots bleiben "absichtlich
            # leer" bis zum naechsten Location-Wechsel. Verhindert dass die
            # Compliance/Auto-Fill sie sofort wieder anzieht.
            try:
                from app.models.character import add_forbidden_slot
                for _u in unequipped:
                    # _u ist "Name (slot)" — Slot extrahieren
                    _m = _u.rsplit("(", 1)
                    if len(_m) == 2:
                        _slot = _m[1].rstrip(")").strip()
                        if _slot:
                            add_forbidden_slot(character_name, _slot)
            except Exception as _fse:
                logger.debug("forbidden_slots konnte nicht gesetzt werden: %s", _fse)

        # Regenerate the expression variant when something changed
        if unequipped:
            try:
                from app.core.expression_regen import trigger_expression_generation
                from app.models.inventory import get_equipped_pieces, get_equipped_items
                from app.models.character import (
                    get_character_current_feeling, get_effective_pose_key)
                _mood = get_character_current_feeling(character_name) or ""
                _pose_key = get_effective_pose_key(character_name) or ""
                _eqp = get_equipped_pieces(character_name)
                _eqi = get_equipped_items(character_name)
                trigger_expression_generation(character_name, _mood, _pose_key,
                    equipped_pieces=_eqp, equipped_items=_eqi,
                    ignore_cooldown=True)
            except Exception as _te:
                logger.debug("Expression trigger after extraction failed: %s", _te)
        return unequipped
    except Exception as e:
        logger.warning("Chat-Extraktion [%s] Piece-Abgleich fehlgeschlagen: %s",
                        character_name, e)
        return []


def _extract_context_from_last_chat(agent_name: str,
    chat_history: List[Dict[str, str]],
    agent_config: Optional[Dict[str, Any]] = None) -> None:
    """Extrahiert Activity und Outfit-Aenderungen aus den letzten Chat-Nachrichten.

    Ueberschreibt die gespeicherte Activity und legt Pieces ab, deren Name im
    Narrativ nicht mehr erwaehnt wird (unequip-only, kein Auto-Equip).
    """
    if not chat_history:
        return

    # Letzte Assistant-Nachrichten sammeln (max. 3 fuer Kontext)
    last_assistant_msgs = []
    for msg in reversed(chat_history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "").strip()
            if content:
                last_assistant_msgs.append(content)
                if len(last_assistant_msgs) >= 3:
                    break
    if not last_assistant_msgs:
        return

    # Auch letzte User-Nachricht fuer Kontext
    last_user_msg = ""
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "").strip()
            break

    # Tool-Marker aus dem Quelltext rausziehen, BEVOR das Extraktions-LLM
    # ihn sieht. Sonst interpretiert es Outfit-Tool-Aufrufe als Aktions-
    # Beschreibung ("Kahiro emittiert *OutfitChange: Graue Jeans...*" =>
    # LLM denkt die alten Pieces sind ausgezogen) und der Agent landet nackt
    # weil das Tool selbst die alten Pieces ueber den Tool-Skill verdraengen
    # wuerde — nicht ueber die Extraktion.
    #
    # Erkennt drei Formate:
    #   <tool name="X">...</tool>     — kanonischer Tool-Tag
    #   *ToolName: ...*               — degenerierter Marker (Sterne)
    #   [Tool-Aufruf: X(...)]         — narrative Bracket-Notation
    _TOOL_MARKER_PATTERNS = [
        re.compile(r'<tool\s+name="[^"]+">[\s\S]*?</tool>', re.IGNORECASE),
        re.compile(r'\*\s*(?:OutfitChange|ChangeOutfit|SetActivity|TalkTo|SendMessage|SetLocation)\s*[:\(][^\*\n]*\*', re.IGNORECASE),
        re.compile(r'\[(?:Tool-Aufruf|Tool Call):\s*[^\]]*\]', re.IGNORECASE),
    ]

    def _strip_tool_markers(text: str) -> str:
        for pat in _TOOL_MARKER_PATTERNS:
            text = pat.sub("", text)
        # Zusammengeschrumpfte Leerzeilen aufraeumen
        return re.sub(r'\n\s*\n\s*\n+', '\n\n', text).strip()

    # Quellen strikt getrennt:
    # - Avatar-Aenderungen kommen aus der User-Eingabe ("Ich ziehe die Jacke aus")
    # - Character-Aenderungen kommen aus der Character-Antwort
    # Jeder Call sieht nur seine eigene Quelle → keine Fehlzuordnung moeglich.
    character_source = "\n".join(
        f"Character: {_strip_tool_markers(m)}" for m in reversed(last_assistant_msgs)
    )
    avatar_source = f"User: {_strip_tool_markers(last_user_msg)}" if last_user_msg else ""

    # Avatar-Name fuer User-Zuordnung (Full-Extraction: Outfit-Aenderungen
    # des Spielers landen auf seinem Avatar-Character, nicht auf dem Login-Konto).
    from app.models.account import get_active_character
    avatar_name = get_active_character() or ""

    def _extract_for_character(
        target_name: str, target_config: Optional[Dict[str, Any]],
        source_text: str, is_avatar: bool):
        """One LLM call for ONE character from ONE source.

        - is_avatar=False: source = character reply. Extracts the agent's
          outfit, pose (key from the menu + display detail) and stat deltas
          (status_effects).
        - is_avatar=True:  source = user input. Extracts only the avatar outfit.

        Runs under target_name's tool-LLM config — logs and LLM choice are
        attributed to the respective character.
        """
        if not source_text.strip():
            return
        from app.models.character import is_outfit_locked
        from app.core.llm_queue import get_llm_queue, Priority

        # Outfit-Lock: spart LLM-Call wenn der User Auto-Aenderungen fuer
        # diesen Character gesperrt hat. Beim Avatar gibt es nur Outfit-
        # Extraktion → kompletter Skip. Beim Agent laeuft Activity-Extraktion
        # weiter (anderer Zweck), nur das Outfit-Feld wird aus dem Prompt
        # entfernt und spaeter ignoriert.
        outfit_locked = is_outfit_locked(target_name)
        if outfit_locked and is_avatar:
            logger.debug("Chat-Kontext [%s]: Outfit-Lock aktiv, Avatar-Extraktion uebersprungen",
                         target_name)
            return

        # Piece-Liste fuer den Prompt — die einzigen Namen, die der LLM
        # zurueckgeben darf. Nicht-equipped Items kann er nicht "ausziehen".
        piece_list = ""
        if not outfit_locked:
            from app.models.inventory import get_equipped_pieces, get_item
            _eq = get_equipped_pieces(target_name) or {}
            _names: List[str] = []
            _seen = set()
            for _slot, _iid in _eq.items():
                if not _iid or _iid in _seen:
                    continue
                _seen.add(_iid)
                _it = get_item(_iid) or {}
                _n = (_it.get("name") or "").strip()
                if _n:
                    _names.append(_n)
            if not _names:
                # Keine equipped Pieces → Outfit-Extraktion entfaellt; nur
                # Activity ist relevant (und auch nur fuer Agent-Calls).
                if is_avatar:
                    return
            piece_list = "\n".join(f"- {n}" for n in _names)

        source_label = "User input" if is_avatar else "Character reply"
        # Kontext-Text: die jeweils ANDERE Quelle als Disambiguierungs-Hilfe.
        # Bei Character-Extraktion bekommt der LLM den User-Input zu sehen
        # (damit "Natuerlich, Lirien" als Reaktion auf "zieh dich aus"
        # interpretierbar ist), bei Avatar-Extraktion umgekehrt. Extraktion
        # bleibt aber strikt auf source_text begrenzt — der Template-Prompt
        # macht das explizit klar.
        context_text = avatar_source if not is_avatar else character_source

        # Stat-Bewertung (C): nur fuer Character-Calls, nur wenn das Feature
        # aktiv ist. Die verfuegbaren Stats werden dynamisch aus dem Character-
        # Template gelesen (store=status_effects) — nichts hardcoden.
        stats_enabled = False
        stat_list = ""
        if not is_avatar:
            try:
                # Single source for the value list (also used by package
                # end-of-activity hooks and the activity tick).
                from app.core.stat_effects import build_stat_list
                stats_enabled, stat_list = build_stat_list(target_name)
            except Exception as _se:
                logger.debug("Stat-Liste fuer Extraktor [%s] fehlgeschlagen: %s", target_name, _se)

        from app.core.npc_actions import _solo_pose_keys
        pose_keys = _solo_pose_keys() if not is_avatar else []

        from app.core.prompt_templates import render_task
        sys_prompt, user_prompt = render_task(
            "extraction_chat_state",
            target_name=target_name,
            pose_keys=pose_keys,
            piece_list=piece_list,
            source_label=source_label,
            source_text=source_text,
            context_text=context_text,
            outfit_locked=outfit_locked,
            is_avatar=is_avatar,
            stats_enabled=stats_enabled,
            stat_list=stat_list)

        try:
            from app.core.llm_router import llm_call as _llm_call
            response = _llm_call(
                task="extraction_chat_state",
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                agent_name=target_name)
        except RuntimeError:
            logger.debug("Chat-Kontext-Extraktion [%s]: kein LLM verfuegbar", target_name)
            return
        except Exception as e:
            logger.warning("Chat-Kontext-Extraktion [%s] Fehler: %s", target_name, e)
            return

        raw = (response.content or "").strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.debug("Chat-Kontext [%s]: kein JSON in Antwort", target_name)
            return
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.debug("Chat-Kontext [%s]: JSON-Parse-Fehler: %s", target_name, raw[:100])
            return

        # The removed list is ignored while the lock is on — no write, no
        # expression trigger.
        removed_raw = [] if outfit_locked else data.get("removed") or []
        if not isinstance(removed_raw, list):
            removed_raw = []
        removed_names = [str(n).strip() for n in removed_raw if n and str(n).strip()]

        # Activity only from the character call — and never written onto a
        # player avatar (not even while it is open as the chat target).
        # is_avatar is set call-site-driven (call 1 = agent, call 2 = user
        # input) — but when the user opened an NPC chat picker on their own
        # avatar through the legacy admin, call 1 ran with is_avatar=False on
        # the avatar and filled its activity/detail from the LLM answer (e.g.
        # "Talking" + "sleeps"). The is_player_controlled check stops that.
        from app.models.account import is_player_controlled as _is_pc
        if not is_avatar and not _is_pc(target_name):
            # Key + detail (plan-pose-key-detail.md): a key from the shown
            # menu is written exactly; an empty or unknown key keeps the
            # current pose and only refreshes the display detail — a gesture
            # must never overturn the body shape.
            extracted_pose = str(data.get("pose") or "").strip()
            extracted_detail = str(data.get("detail") or "").strip()
            if extracted_pose or extracted_detail:
                from app.core.pose_catalog import PairPoseWithoutPartner
                from app.models.character import set_pose_key_detail
                try:
                    written = set_pose_key_detail(
                        target_name, extracted_pose, extracted_detail,
                        unknown="keep")
                    logger.info("Chat context [%s]: pose %r detail %r -> %r",
                                target_name, extracted_pose[:40],
                                extracted_detail[:80], written)
                except PairPoseWithoutPartner as e:
                    logger.info("Chat context [%s]: pose %r discarded — '%s' "
                                "is a two-person pose", target_name,
                                extracted_pose[:80], e)

            # Stats: apply this scene's malus/bonus to status_effects.
            stats_raw = data.get("stats")
            if isinstance(stats_raw, dict) and stats_raw:
                try:
                    from app.models.character import adjust_status_effects
                    applied = adjust_status_effects(target_name, stats_raw, source="chat")
                    if applied:
                        logger.info("Chat-Kontext [%s]: Stats %s", target_name,
                                     ", ".join(f"{k} {v['old']}->{v['new']}"
                                               for k, v in applied.items()))
                except Exception as _ste:
                    logger.debug("Stat-Apply [%s] fehlgeschlagen: %s", target_name, _ste)

        # Pieces ablegen, deren Name in der removed-Liste steht.
        # Neue Pieces koennen nicht aus dem Freitext erzeugt werden —
        # dafuer muss das LLM den OutfitCreation-Skill rufen.
        if removed_names:
            _apply_removed_pieces(target_name, removed_names)

    def _do_extraction():
        # Call 1: Character-Antwort → Agent-Outfit + Activity (unter Agent-Config)
        _extract_for_character(
            agent_name, agent_config,
            source_text=character_source, is_avatar=False)
        # Call 2: User-Eingabe → Avatar-Outfit (unter Avatar-Config)
        if avatar_name and avatar_source:
            from app.models.character import get_character_config
            avatar_config = get_character_config(avatar_name)
            _extract_for_character(
                avatar_name, avatar_config,
                source_text=avatar_source, is_avatar=True)

    import asyncio
    from app.core.turn_trace import bind_trace
    try:
        # bind_trace carries the turn's trace id into the pool thread:
        # run_in_executor does not propagate the context, so the
        # extraction_chat_state calls above would otherwise be orphaned in
        # the LLM log. The synchronous fallback keeps the context anyway.
        asyncio.get_event_loop().run_in_executor(None, bind_trace(_do_extraction))
    except RuntimeError:
        # No event loop (daemon/worker thread, e.g. run_chat_turn's follow-up
        # thread) — run synchronously instead of losing the extraction.
        _do_extraction()


class ChatPrompt(NamedTuple):
    """The chat prompt in its two cache parts.

    ``system`` is the system prompt — only what stays put between turns.
    ``moment`` is the scene state of THIS turn; the caller hangs it on the last
    user turn, after the history, so a changing clock, mood or room never
    invalidates the backend's cached system prompt and history.
    """
    system: str
    moment: str


def _build_chat_prompt(character_name: str,
    lang_instruction: str,
    history_summary: str,
    tools_enabled: bool = False,
    agent_config: Optional[Dict[str, Any]] = None,
    selected_skills: Optional[list] = None,
    has_tool_llm: bool = False,
    partner_override: str = "",
    skip_partner: bool = False,
    medium: str = "in_person",
    room_item_ids: Optional[list] = None,
    respond_opportunity: bool = False,
    winding_down: bool = False,
    present_characters: Optional[list] = None,
    incoming_text: str = "",
    addressed_to: Optional[List[str]] = None,
    moment_notes: Optional[List[str]] = None) -> ChatPrompt:
    """Build the chat-stream / talk-to prompt as system prompt + scene state.

    Loads all data sections (character/soul template, partner template,
    memory, relationships, ...), then renders ``chat/chat_stream.md`` (the
    stable system prompt) and ``chat/chat_moment.md`` (the per-turn scene
    state). Which block goes where is decided by how often it changes — see
    the header of both templates. Pre-formatted blocks live in Python
    (``build_*_prompt_section``); static instruction text lives in the
    templates.

    Args:
        skip_partner: True for group chat — partner section is skipped
            (participants get listed in the GROUP CONVERSATION block instead).
        incoming_text: The message the LLM is about to answer, exactly as
            it will see it. Only its size and shape reach the prompt;
            callers that have no incoming message leave it empty.
        addressed_to: Names the incoming line was addressed to (room mode).
            ``None`` = not known — a plain 1:1 chat, where the line is by
            definition meant for this character, so ``addressed_to_me`` is
            True. An empty list means the line went to the room.
        moment_notes: One-off context of this turn (a state modifier, a spell
            taking effect, being woken up, a caller's hint). Rendered in the
            scene state, never in the system prompt.
    """
    from app.core.prompt_templates import render

    char_profile = get_character_profile(character_name)
    char_template = get_template(char_profile.get("template", "human-default"))
    char_features = (char_template or {}).get("features", {})

    # ---- Conversation partner ----------------------------------------
    from app.models.account import get_active_character
    _partner_name = "" if skip_partner else (partner_override or get_active_character())
    _partner_lines: list = []
    # The partner's per-turn facts (mood, doing, volatile fields) — they go
    # to the scene state; _partner_lines keeps only the stable sheet.
    _partner_state_lines: list = []
    partner_mode = "none"

    if _partner_name and _partner_name != character_name:
        if not char_features.get("relationships_enabled", True):
            partner_mode = "chatbot"
        else:
            partner_mode = "character"
            partner_profile = get_character_profile(_partner_name)
            partner_template = get_template(partner_profile.get("template", "human-default"))
            if partner_template:
                p_app = partner_profile.get("character_appearance", "")
                if p_app and "{" in p_app:
                    p_app = resolve_profile_tokens(
                        p_app, partner_profile, template=partner_template,
                        target_key="character_appearance")
                # Append the slot fragments of uncovered, unworn slots (same
                # logic as the variant image), so the LLM knows what would be
                # visible under the outfit.
                try:
                    _slot_extras = render_unworn_slots(profile=partner_profile)
                    if _slot_extras:
                        p_app = (p_app + ", " + _slot_extras).strip(", ").strip()
                except Exception:
                    pass
                partner_profile["character_appearance"] = p_app
                p_loc_id = partner_profile.get("current_location", "")
                if p_loc_id:
                    p_loc_name = get_location_name(p_loc_id)
                    partner_profile["current_location"] = p_loc_name or p_loc_id
                _partner_lines = build_prompt_section(
                    partner_template, partner_profile,
                    active_features=char_features,
                    is_partner=True, character_name=_partner_name,
                    volatile=False)
                _partner_state_lines = build_prompt_section(
                    partner_template, partner_profile,
                    active_features=char_features,
                    is_partner=True, character_name=_partner_name,
                    volatile=True)
            if not _partner_lines:
                _partner_lines = [f"Name: {_partner_name}"]

            try:
                _p_feeling = (partner_profile.get("current_feeling") or "").strip()
                if _p_feeling:
                    _partner_state_lines.append(f"Current mood: {_p_feeling}")
                _p_activity = (partner_profile.get("pose_flavor")
                               or partner_profile.get("pose_key") or "").strip()
                if _p_activity:
                    _partner_state_lines.append(f"Currently doing: {_p_activity}")
            except Exception:
                pass

            # How THIS character addresses THIS partner (free text per pair
            # and per direction, e.g. formal vs. informal plus a nickname).
            # Stable for a given partner, so it belongs in the partner block
            # of the system prompt — the template's "unless a different form
            # of address is specified above" refers to exactly this line.
            from app.models.relationship import address_line as _address_line
            _addr = _address_line(character_name, _partner_name)
            if _addr:
                _partner_lines.append(_addr)
    elif not skip_partner:
        # Fallback: no active character — no login name, otherwise "admin"
        # slips into prompts and memory as a pseudo partner.
        pass

    # ---- Self / partner wearing blocks --------------------------------
    def _strip_wearing_prefix(text: str) -> str:
        t = (text or "").strip()
        if t.lower().startswith("wearing:"):
            t = t[len("wearing:"):].lstrip()
        return t

    def _build_wearing_block(_cname: str, _label: str,
                             include_inventory: bool) -> str:
        try:
            from app.models.inventory import (
                get_character_inventory, get_equipped_item_ids)
            wearing = _strip_wearing_prefix(
                render_outfit(character_name=_cname).get("full", ""))
            lines: list = []
            _is_self = (_label == "You")
            _v_wear = "are" if _is_self else "is"
            _v_carry = "have" if _is_self else "has"
            if wearing:
                lines.append(f"{_label} {_v_wear} currently wearing this clothing and equipment: {wearing}")
            if include_inventory:
                inv = get_character_inventory(_cname).get("inventory", [])
                equipped_set = set(get_equipped_item_ids(_cname))
                carried = [
                    (e.get("item_name") or e.get("item_id") or "?")
                    for e in inv
                    if e.get("item_id") not in equipped_set
                ]
                if carried:
                    lines.append(f"{_label} {_v_carry} on hand (not yet equipped / in inventory): {', '.join(carried)}")
            return "\n".join(lines)
        except Exception:
            return ""

    self_wearing = _build_wearing_block(character_name, "You", include_inventory=True)
    partner_wearing = ""
    if _partner_name and _partner_name != character_name and not skip_partner:
        partner_wearing = _build_wearing_block(_partner_name, _partner_name,
                                                include_inventory=False)

    # ---- Focused room items (in_person + room_item_ids) ---------------
    focused_items = ""
    if medium == "in_person" and room_item_ids:
        try:
            from app.models.inventory import get_item
            _item_lines = []
            for _iid in room_item_ids:
                _it = get_item(_iid)
                if not _it:
                    continue
                _n = _it.get("name", _iid)
                _d = (_it.get("description") or "").strip()
                _item_lines.append(f"- {_n}: {_d}" if _d else f"- {_n}")
            if _item_lines:
                focused_items = "\n".join(_item_lines)
        except Exception:
            pass

    # ---- Character template lines (the core "this is who you are") ----
    if char_template:
        appearance = char_profile.get("character_appearance", "")
        if appearance and "{" in appearance:
            appearance = resolve_profile_tokens(
                appearance, char_profile, template=char_template,
                target_key="character_appearance")
        # Append the slot fragments of uncovered, unworn slots — same logic
        # as in the partner block + variant image.
        try:
            _slot_extras = render_unworn_slots(profile=char_profile)
            if _slot_extras:
                appearance = (appearance + ", " + _slot_extras).strip(", ").strip()
        except Exception:
            pass
        char_profile["character_appearance"] = appearance
        current_outfit = (render_outfit(character_name=character_name).get("full", "") or "").removeprefix("wearing: ")
        if current_outfit:
            char_profile["default_outfit"] = current_outfit
        loc_id = char_profile.get("current_location", "")
        if loc_id:
            loc_name = get_location_name(loc_id)
            char_profile["current_location"] = loc_name if loc_name else loc_id
        char_lines = build_prompt_section(
            char_template, char_profile,
            active_features=char_features, character_name=character_name,
            volatile=False)
        self_state_lines = build_prompt_section(
            char_template, char_profile,
            active_features=char_features, character_name=character_name,
            volatile=True)
    else:
        char_lines = [f"Name: {character_name}"]
        self_state_lines = []
        if char_profile.get("character_personality"):
            char_lines.append(f"Personality: {char_profile['character_personality']}")

    # ---- Feature-Check Helper -----------------------------------------
    from app.models.character_template import is_feature_enabled as _feat
    def _has(feat: str) -> bool:
        return _feat(character_name, feat)

    # ---- Active intents (plans & tasks) -------------------------------
    assignment_section = ""
    if _has("assignments_enabled"):
        from app.models.intents import build_intents_prompt_section
        assignment_section = build_intents_prompt_section(character_name) or ""

    # ---- Current situation block --------------------------------------
    current_location_id = get_character_current_location(character_name)
    current_location = get_location_name(current_location_id) if current_location_id else ""
    current_room_id = get_character_current_room(character_name)
    current_activity = get_effective_activity(character_name)

    from app.core.timeutils import game_time
    from app.models.character import get_character_language as _get_lang
    # Game clock + world calendar (storage stays real UTC). The date label
    # carries season, day and year — and the weekday name when the world has
    # weeks at all. No real-world date reaches the character anymore.
    _now_game = game_time()
    _date_lang = _get_lang(character_name) or "de"
    time_line = (f"Current time: {_now_game.time_hhmm()} — "
                 f"{_now_game.date_label(_date_lang)}\n"
                 f"Weather: {_now_game.atmosphere(_date_lang)['label']}")
    # The day itself, not the standing date: the character block already
    # carries "Birthday: Summer, day 14" generically from the template.
    from app.core.birthday import is_birthday_today as _is_birthday_today
    if _is_birthday_today(char_profile, _now_game):
        time_line += "\nToday is your birthday."
    situation_parts = [time_line]

    if _has("locations_enabled") and current_location:
        loc_data = get_location(current_location_id)
        loc_desc = loc_data.get("description", "") if loc_data else ""
        situation_parts.append(
            f"Location: {current_location} - {loc_desc}" if loc_desc
            else f"Location: {current_location}")
        if current_room_id and loc_data:
            room_data = get_room_by_id(loc_data, current_room_id)
            if not room_data:
                for r in loc_data.get("rooms", []):
                    if r.get("name", "").lower() == current_room_id.lower():
                        room_data = r
                        break
            if room_data:
                room_name = room_data.get("name", "")
                room_desc = room_data.get("description", "")
                if room_desc:
                    situation_parts.append(f"Room: {room_name} - {room_desc}")
                elif room_name:
                    situation_parts.append(f"Room: {room_name}")

    if _has("activities_enabled") and current_activity:
        # current_activity == the display pose (flavor or catalog key) resp.
        # "Sleeping" via the flag. No library description any more.
        situation_parts.append(f"Activity: {current_activity}")

    if len(situation_parts) == 1:
        situation_block = time_line
    else:
        situation_block = "Your current situation:\n" + "\n".join(situation_parts)

    # ---- Location events ----------------------------------------------
    events_section = ""
    if current_location_id and _has("locations_enabled"):
        events_section = build_events_prompt_section(
            location_id=current_location_id, character_name=character_name) or ""

    # ---- Memory --------------------------------------------------------
    memory_section = ""
    if _has("memory_enabled"):
        memory_section = build_memory_prompt_section(
            character_name, partner_name=_partner_name, current_message="") or ""

    # ---- Relationships -------------------------------------------------
    relationships_section = ""
    if _has("relationships_enabled"):
        from app.models.relationship import build_relationship_prompt_section
        relationships_section = build_relationship_prompt_section(character_name) or ""

    # ---- Secrets -------------------------------------------------------
    secrets_section = ""
    if _has("secrets_enabled"):
        from app.models.secrets import build_secrets_prompt_section
        secrets_section = build_secrets_prompt_section(character_name) or ""

    # ---- Inventory: carrying + room visible ---------------------------
    inventory_carrying_section = ""
    inventory_room_section = ""
    if _has("inventory_enabled"):
        try:
            from app.models.inventory import (
                get_character_inventory, get_room_items, get_item,
                get_equipped_item_ids)

            def _localized(item: Dict[str, Any], field: str) -> str:
                if field == "name":
                    return (item.get("name") or "").strip()
                return (item.get(field) or item.get(f"{field}_de") or "").strip()

            inv_data = get_character_inventory(character_name)
            inv_items = inv_data.get("inventory", [])
            equipped_set = set(get_equipped_item_ids(character_name))
            if inv_items:
                inv_lines = []
                for entry in inv_items:
                    item_id = entry.get("item_id", "")
                    if item_id in equipped_set or entry.get("equipped"):
                        continue
                    full_item = get_item(item_id) or {}
                    name = _localized(full_item, "name") or entry.get("item_name", "?")
                    desc = _localized(full_item, "description")
                    qty = entry.get("quantity", 1)
                    line = f"- {name}" + (f" x{qty}" if qty > 1 else "")
                    if desc:
                        line += f" — {desc}"
                    inv_lines.append(line)
                if inv_lines:
                    inventory_carrying_section = "Items you are carrying:\n" + "\n".join(inv_lines)

            if current_location_id and current_room_id:
                room_entries = get_room_items(current_location_id, current_room_id) or []
                visible_lines = []
                for ri in room_entries:
                    if ri.get("hidden"):
                        continue
                    full_item = get_item(ri.get("item_id", "")) or {}
                    if not full_item:
                        continue
                    name = _localized(full_item, "name") or ri.get("item_id", "?")
                    desc = _localized(full_item, "description")
                    qty = ri.get("quantity", 1)
                    note = (ri.get("note") or "").strip()
                    line = f"- {name}" + (f" x{qty}" if qty > 1 else "")
                    if note:
                        line += f" ({note})"
                    elif desc:
                        line += f" — {desc}"
                    visible_lines.append(line)
                if visible_lines:
                    inventory_room_section = "Items visible in this room:\n" + "\n".join(visible_lines)
        except Exception:
            pass

    # ---- Mood tracking flag -------------------------------------------
    char_config = get_character_config(character_name)
    mood_tracking_enabled = bool(
        _has("mood_tracking_enabled") and char_config.get("mood_tracking", False))

    # ---- Location / activity change instructions ----------------------
    # The place marker is taught ONLY where it still does something: a
    # character with the movement verb travels with the verb, and a follower
    # or an avatar may not travel this way at all (_marker_travel_refusal).
    # Teaching it to everyone is what produced markers the server then threw
    # away — the prompt promised a way that was closed.
    marker_travel_enabled = bool(_has("locations_enabled")
                                 and _may_travel_by_marker(character_name))
    known_locations = ""
    if current_location_id and marker_travel_enabled:
        # The places this character may know (knowledge items), not every place
        # in the world: the movement package's "Places you can go" is gated the
        # same way (plugins/movement/blocks.py), and a chat prompt that names
        # more would teach a destination the travel gate then refuses.
        location_names = [loc.get("name", "")
                          for loc in list_locations_for_character(character_name)]
        if location_names:
            known_locations = ", ".join(n for n in location_names if n)

    # The marker RULE is stable (system prompt); the place offer it points at
    # follows the room's occupancy and goes to the scene state.
    activity_marker_enabled = bool(current_location_id and _has("activities_enabled"))
    known_activities = ""
    if activity_marker_enabled:
        known_activities = _current_activity_hint(character_name, current_location_id)

    # ---- Intent tracking flag (unified plans & tasks) -----------------
    # One block teaches the [INTENT:] marker syntax (plan-intents-unified.md).
    # Only when the chat LLM may set markers itself (no separate tool LLM)
    # AND the character keeps plans at all (intents_enabled).
    intent_tracking_enabled = bool(
        tools_enabled and not has_tool_llm and _has("intents_enabled"))

    # ---- Tool instructions block (built externally — complex) ---------
    tool_instructions = ""
    if tools_enabled and agent_config and not has_tool_llm:
        from app.core.tool_formats import build_tool_instruction, get_format_for_model
        sm = get_skill_manager()
        agent_tools = sm.get_agent_tools(character_name, check_limits=False)
        if selected_skills is not None:
            agent_tools = [t for t in agent_tools if t.name in selected_skills]
        if agent_tools:
            from app.core.llm_router import resolve_llm as _resolve_llm_sp
            _sp_chat_inst = _resolve_llm_sp("chat_stream", agent_name=character_name)
            _model_for_fmt = _sp_chat_inst.model if _sp_chat_inst else ""
            fmt = get_format_for_model(_model_for_fmt)
            appearance = get_character_appearance(character_name)
            usage = sm.get_agent_usage_instructions(character_name, fmt, check_limits=False)
            from app.core.prompt_builder import is_photographer_mode as _is_pm
            _sp_photographer = _is_pm(character_name)
            _sp_user_app = get_user_appearance() or "" if _sp_photographer else ""
            from app.models.character_template import is_roleplay_character as _is_rp_char
            tool_instructions = build_tool_instruction(
                fmt, agent_tools, appearance, usage, model_name=_model_for_fmt,
                photographer_mode=_sp_photographer, user_appearance=_sp_user_app,
                is_roleplay=_is_rp_char(character_name))

    # ---- Long-term / daily / session summaries -----------------------
    longterm_section = ""
    daily_summary_section = ""
    history_summary_block = ""
    if _has("memory_enabled"):
        from app.utils.history_manager import build_longterm_summary_prompt_section
        longterm_section = build_longterm_summary_prompt_section(
            character_name, _date_lang) or ""
        from app.models.memory import memory_amount as _mem_amt2
        daily_summary_section = build_daily_summary_prompt_section(
            character_name,
            max_days=_mem_amt2(character_name, "memory_partner_days_in_prompt",
                               "memory.partner_days_in_prompt", 5)) or ""

        if history_summary:
            history_summary_block = f"Summary of previous conversations:\n{history_summary}"

    # ---- Multi-party room scene framing -------------------------------
    # Several people present → group scene instead of 1:1 partner framing
    # (fixes identity mixing: the model narrated/took over other figures
    # because the prompt framed a 4-person scene as "you talk to X").
    _present_str = ""
    _present_details = ""
    if present_characters:
        _others = list(dict.fromkeys(
            c for c in present_characters if c and c != character_name))
        if _others:
            _present_str = ", ".join(_others)
            partner_mode = "room"
            # Visible outfit/states per present person — same builder as
            # the thought context (a character SEES the people around it).
            try:
                from app.core.thought_context import present_people_details
                # NO local import of get_character_current_location here —
                # it would shadow the module-level import and turn line
                # ~2305 into an UnboundLocalError, killing EVERY room
                # respond-turn (broken 07-09..07-18 exactly this way).
                _loc = get_character_current_location(character_name) or ""
                _present_details = present_people_details(
                    [(n, n) for n in _others], _loc)
            except Exception:
                _present_details = ""

    # ---- Scenes as the canonical "earlier conversations" --------------
    # scene_store consolidation (conversation -> scene). Closes the loop and
    # replaces the old pairwise history summary in room mode (no redundancy).
    # Past days = ONE day entry each (stage 2b); today's not yet folded scenes
    # one by one (stage 2, filtered by the day cursor).
    scenes_block = ""
    if _has("memory_enabled"):
        try:
            from app.models import scene_store
            from app.models.world import get_location_by_id
            from app.core import day_consolidation as _dc
            _parts = []
            # Stage 2b: past days
            from app.models.memory import memory_amount as _mem_amt
            _days = _dc.recent_daily_entries(
                character_name,
                limit=_mem_amt(character_name, "memory_daily_entries_in_prompt",
                               "memory.daily_entries_in_prompt", 7))
            if _days:
                # recent_daily_entries returns newest-first; the prompt reads
                # chronologically -> oldest first. The key is a game day
                # ("Y0002-D109") — the character reads the world date, never
                # the raw key.
                def _day_label(dk: str) -> str:
                    try:
                        return _dc.parse_day_key(dk).date_label(_date_lang)
                    except (AttributeError, ValueError, TypeError):
                        return dk
                _parts.append("Earlier days:\n" + "\n".join(
                    f"- {_day_label(dk)}: {txt.strip()}"
                    for dk, txt in reversed(_days) if (txt or "").strip()))
            # Stage 2: today's scenes (after the cursor — folded ones drop out)
            _cursor = _dc.get_cursor(character_name)
            _lines = []
            for sc in scene_store.get_recent_scenes_for(
                    character_name,
                    limit=_mem_amt(character_name, "memory_scenes_in_prompt",
                                   "memory.scenes_in_prompt", 8)):
                if (sc.get("last_activity_ts") or "") <= _cursor:
                    continue
                summ = (sc.get("summary") or "").strip()
                if not summ:
                    continue
                _osc = [p for p in (sc.get("participants") or [])
                        if p and p != character_name and p != STORYTELLER_SPEAKER]
                _loc = get_location_by_id(sc.get("location_id", "")) or {}
                tag = " · ".join([x for x in (_loc.get("name", ""), ", ".join(_osc)) if x])
                _lines.append(f"- {summ}" + (f"  ({tag})" if tag else ""))
            if _lines:
                # get_recent_scenes_for is newest-first -> flip to chronological.
                _lines.reverse()
                _parts.append("Earlier scenes today:\n" + "\n".join(_lines))
            scenes_block = "\n\n".join(_parts)
        except Exception as _se:
            logger.debug("scenes_block build failed: %s", _se)
    # Room mode = new pipeline (stage 1 live transcript + stage 2 scenes +
    # stage 3 memories). The chat_messages-based old blocks (pairwise history
    # summary, daily summaries, longterm summary) do NOT belong in the room
    # prompt anymore — they duplicate the scenes and were the source of the
    # garbage flooding (plan-history-consolidation-cleanup.md, phase 1).
    if partner_mode == "room":
        history_summary_block = ""
        daily_summary_section = ""
        longterm_section = ""

    # ---- Recent activity ----------------------------------------------
    recent_activity_section = ""
    try:
        from app.core.system_prompt_builder import build_recent_activity_section
        recent_activity_section = build_recent_activity_section(character_name) or ""
    except Exception as _re:
        logger.debug("Recent-Activity-Section: %s", _re)

    # ---- Condition reminder -------------------------------------------
    condition_reminder = ""
    if _has("status_effects_enabled"):
        from app.core.danger_system import build_condition_reminder
        condition_reminder = build_condition_reminder(character_name) or ""

    from app.models.world_setup import get_world_setup_text
    world_setup = get_world_setup_text()

    # ---- Reply shape --------------------------------------------------
    # Facts about this moment only (role, mood, relationship, size of the
    # incoming line). How to read them for reply length is the template's
    # job, not Python's. Never raises — a missing fact just drops a line.
    from app.core.reply_shape import build_reply_shape_section
    reply_shape_section = build_reply_shape_section(
        character_name, _partner_name, incoming_text)

    # ---- Form of address toward the partner -----------------------------
    # 1:1 character mode keeps the note in the partner block of the SYSTEM
    # prompt (see above) — it is stable for that partner. In room mode the
    # partner is whoever just spoke and changes from turn to turn, so the
    # scene state carries it instead of invalidating the prompt prefix.
    partner_address = ""
    if partner_mode == "room" and _partner_name and _partner_name != character_name:
        from app.models.relationship import get_address as _get_address
        partner_address = _get_address(character_name, _partner_name)

    # ---- Who was addressed ---------------------------------------------
    # Only meaningful in room mode; a 1:1 chat has no addressee list and the
    # line is always meant for this character.
    if addressed_to is None:
        addressed_to_me = True
        addressed_names = ""
    else:
        addressed_to_me = bool(character_name in addressed_to)
        addressed_names = ", ".join(n for n in addressed_to if n != character_name)

    system = render(
        "chat/chat_stream.md",
        character_name=character_name,
        world_setup=world_setup,
        lang_instruction=lang_instruction,
        char_lines=char_lines,
        partner_mode=partner_mode,
        partner_name=_partner_name,
        partner_lines=_partner_lines,
        medium=medium,
        secrets_section=secrets_section,
        tools_enabled=tools_enabled,
        mood_tracking_enabled=mood_tracking_enabled,
        known_locations=known_locations,
        activity_marker_enabled=activity_marker_enabled,
        intent_tracking_enabled=intent_tracking_enabled,
        tool_instructions=tool_instructions,
        longterm_section=longterm_section,
        daily_summary_section=daily_summary_section,
        scenes_block=scenes_block,
        history_summary_block=history_summary_block)
    moment = render(
        "chat/chat_moment.md",
        character_name=character_name,
        partner_mode=partner_mode,
        partner_name=_partner_name,
        partner_state_lines=_partner_state_lines,
        partner_address=partner_address,
        present_characters=_present_str,
        present_details=_present_details,
        situation_block=situation_block,
        self_state_lines=self_state_lines,
        condition_reminder=condition_reminder,
        moment_notes=[n for n in (moment_notes or []) if n],
        self_wearing=self_wearing,
        partner_wearing=partner_wearing,
        inventory_carrying_section=inventory_carrying_section,
        inventory_room_section=inventory_room_section,
        focused_items=focused_items,
        known_activities=known_activities,
        events_section=events_section,
        assignment_section=assignment_section,
        recent_activity_section=recent_activity_section,
        memory_section=memory_section,
        relationships_section=relationships_section,
        reply_shape_section=reply_shape_section,
        addressed_to_me=addressed_to_me,
        addressed_names=addressed_names,
        respond_opportunity=respond_opportunity,
        winding_down=winding_down)
    return ChatPrompt(system=system, moment=moment)
