"""Chat history — thin wrapper around the unified chat storage.

DEPRECATED: these functions exist for backward compatibility.
Use app.models.unified_chat.UnifiedChatManager instead.
"""
from typing import Dict, List, Optional

from app.models.unified_chat import UnifiedChatManager
from app.models.channel import Message


def get_chat_history(character_name: str = "", partner_name: str = "",
                     limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Loads the chat history. partner_name: explicit partner character (C2C).

    ``limit`` is handed straight to ``UnifiedChatManager.get_chat_history``,
    which applies it IN SQL (DATA-12): the history of a pair is never pruned,
    so a caller that only wants the last few messages otherwise reads, parses
    and object-ifies the whole conversation. Only pass it when the window is
    exactly a message count — a time window (``get_time_based_history``) is
    not the same thing and must not be approximated by one.
    Without it nothing changes: the full history is returned as before.
    """
    if not character_name:
        return []
    messages = UnifiedChatManager.get_chat_history(
        character_name, partner_name=partner_name, limit=limit)
    return [msg.to_dict() for msg in messages]


def save_message(message: Dict[str, str], character_name: str = "",
                 partner_name: str = "") -> bool:
    """Stores a message. partner_name: explicit partner character (C2C).

    Returns True when the row was committed, False when it was NOT (DATA-13).
    This used to return ``None`` in every case, so a ``database is locked``
    during a chat turn dropped the message while the caller reported success.
    A caller that tells anyone the message was stored has to check this.
    """
    if not character_name:
        return False
    msg_obj = Message.from_dict(message.copy())
    return UnifiedChatManager.save_message(msg_obj, character_name,
                                           partner_name=partner_name)
