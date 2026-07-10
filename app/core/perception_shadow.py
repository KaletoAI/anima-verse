"""Shadow-Write: spiegelt reale Chat-Nachrichten zusaetzlich in den
Wahrnehmungs-Stream (plan-room-conversation Phase 1).

Additiv + vollstaendig gekapselt — bricht NIE den Chat-Pfad. Reines
Beobachtungs-Feature, solange der Loop den Stream noch nicht primaer befuellt
(ab Phase 3 wird der Schreibpfad direkt, der Shadow faellt dann weg).

Zwei Quellen, weil 1:1 und Gruppe getrennte Persistenz haben:
- ``from_chat_message``  — Hook in ``UnifiedChatManager.save_message`` (1:1,
                            TalkTo, Telegram).
- ``from_group_message`` — Hook in ``group_chat.save_group_message`` (Gruppe,
                            inkl. Fluestern).
"""
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.log import get_logger

logger = get_logger("perception_shadow")

# Wenn gesetzt, schreibt der Shadow NICHT — fuer Pfade, die den Stream bereits
# selbst primaer befuellen (z.B. /play/say ruft run_chat_turn auf, will dessen
# save_message-Shadow aber NICHT, weil es die Antwort direkt aufzeichnet).
_suppressed: ContextVar[bool] = ContextVar("perception_shadow_suppressed",
                                           default=False)


@contextmanager
def suppressed():
    """Im Block ausgeloeste save_message/save_group_message schreiben keinen
    Shadow. ContextVar-basiert → propagiert auch in asyncio.to_thread."""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def _avatar() -> str:
    from app.models.account import get_active_character
    return (get_active_character() or "").strip()


def from_chat_message(message, character_name: str, partner: str) -> None:
    """Ein ``chat_messages``-Eintrag -> ein Sprechakt.

    role=user      -> Avatar spricht, adressiert den Character.
    role=assistant -> der Character spricht, adressiert den Partner.
    """
    try:
        if _suppressed.get():
            return
        role = getattr(message, "role", "") or ""
        content = getattr(message, "content", "") or ""
        ts = getattr(message, "timestamp", "") or None
        if role not in ("user", "assistant") or not content.strip():
            return

        # Remote-DM (Phone/Telegram/Instagram) NICHT in den Raum-Wahrnehmungs-
        # Stream schatten — das ist die Messaging-Saeule (Fernkommunikation),
        # der Partner ist gar nicht im Raum. Sonst taucht eine Telefon-Nachricht
        # an einen abwesenden NPC im Raum-Chat auf. Nur co-located (in_person /
        # leeres Medium) wird gespiegelt.
        if (getattr(message, "medium", "") or "") in ("messaging", "telegram", "instagram"):
            return

        from app.core.perception import (VOLUME_NORMAL, VOLUME_SHOUT,
                                          VOLUME_WHISPER, record_utterance)

        if role == "assistant":
            speaker = character_name or ""
            addressees = [partner] if partner else []
        else:  # user -> Avatar
            speaker = _avatar()
            addressees = [character_name] if character_name else []
        if not speaker:
            return

        # Volume from the message metadata (e.g. TalkTo whisper/shout) — a
        # whispered line stays private to the addressee, a shout carries
        # location-wide; same semantics as the avatar's say feature.
        _md = getattr(message, "metadata", None) or {}
        _vol = str(_md.get("volume") or "").strip().lower()
        volume = _vol if _vol in (VOLUME_WHISPER, VOLUME_SHOUT) else VOLUME_NORMAL

        record_utterance(speaker=speaker, content=content, volume=volume,
                         addressees=addressees, ts=ts, source="shadow",
                         dedupe=True)
    except Exception as e:
        logger.debug("shadow from_chat_message skipped: %s", e)


def from_group_message(role: str, content: str, character: str = "",
                       whisper_to: str = "") -> None:
    """Ein ``save_group_message`` -> ein Sprechakt (Fluestern unterstuetzt).

    role=user      -> Avatar spricht (whisper_to -> Fluestern).
    role=assistant -> der ``character`` spricht.
    """
    try:
        if _suppressed.get():
            return
        content = content or ""
        if role not in ("user", "assistant") or not content.strip():
            return

        from app.core.perception import (VOLUME_NORMAL, VOLUME_WHISPER,
                                          record_utterance)

        speaker = (character or "") if role == "assistant" else _avatar()
        if not speaker:
            return

        if whisper_to:
            volume = VOLUME_WHISPER
            addressees = [whisper_to]
        else:
            volume = VOLUME_NORMAL
            addressees = []

        record_utterance(speaker=speaker, content=content, volume=volume,
                         addressees=addressees, source="shadow")
    except Exception as e:
        logger.debug("shadow from_group_message skipped: %s", e)
