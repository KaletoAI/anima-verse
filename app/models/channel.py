"""Message model — the unified shape of a stored chat message.

One message row of ``chat_messages`` as an object. There used to be a
multi-channel layer around it (an abstract channel interface plus an external
chat bridge); the web UI is the only way in or out now, so the interface and
its registry are gone and ``channel`` is simply the string the column
carries.
"""
from typing import Optional, Dict, Any

from app.core.timeutils import utc_now_iso


class Message:
    """Uniform message structure.

    speaker: who wrote the message.
        "user"         -> user input (default for role=user)
        "<CharName>"   -> another character speaks (also role=user from the
                          point of view of the answering character)
        For role=assistant: name of the answering character.

    medium: communication channel from the characters' point of view.
        "in_person"    -> in person, same place
        "messaging"    -> message window (remote communication)
        "instagram"    -> Instagram comment / DM
    """

    def __init__(
        self,
        content: str,
        role: str,  # "user" or "assistant"
        channel: str = "web",
        timestamp: Optional[str] = None,
        channel_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        speaker: str = "user",
        medium: str = "in_person",
        id: Optional[int] = None):  # noqa: A002 - DB row id
        self.content = content
        self.role = role
        self.channel = channel or "web"
        self.timestamp = timestamp or utc_now_iso()
        self.channel_message_id = channel_message_id
        self.metadata = metadata or {}
        self.speaker = speaker
        self.medium = medium
        # DB rowid (chat_messages.id). Set when read from the DB; None on a
        # freshly built message until save_message has committed it.
        self.id = id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for JSON storage."""
        return {
            "id": self.id,
            "content": self.content,
            "role": self.role,
            "channel": self.channel,
            "timestamp": self.timestamp,
            "channel_message_id": self.channel_message_id,
            "metadata": self.metadata,
            "speaker": self.speaker,
            "medium": self.medium,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Message":
        """Build a Message from a dictionary.

        Old messages without speaker/medium get the defaults
        ('user' / 'in_person') — no backfill migration.
        """
        return Message(
            content=data["content"],
            role=data["role"],
            channel=data.get("channel", "web"),
            timestamp=data.get("timestamp"),
            channel_message_id=data.get("channel_message_id"),
            metadata=data.get("metadata", {}),
            speaker=data.get("speaker", "user"),
            medium=data.get("medium", "in_person"),
            id=data.get("id"))
