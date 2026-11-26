"""Share-secret package — record that another character in the same room now knows a secret.

An NPC calls ``ShareSecret`` when its reply actually tells another character in
the same room a secret it owns or already knows. The verb only records the
knowledge through ``app.models.secrets.add_known_by(owner, secret_id, to)``,
which emits the ``secret.learned`` hook when the recipient is new.

Input (JSON object or JSON string inside ``input``):
    {"secret_id": "<id>", "to": "<name of someone in your room>"}

Deletion test: removing ``plugins/share_secret/`` removes the verb cleanly with
no core changes or broken dependencies.
"""
import json
from typing import Any, Dict, Optional

from app.core import room_entry
from app.models import character, secrets
from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class ShareSecretSkill(PluginSkill):
    """Record that another character in the same room learned a secret."""

    SKILL_ID = "share_secret"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/share_secret.md
        self._defaults = {"enabled": True}

    def available_now(self, facts) -> Optional[str]:
        if not facts.present:
            return "nobody is present"
        return None

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is not available."
        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            self.ctx.logger.error("ShareSecret error: %s", e)
            return f"Error: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        data = self._parse_base_input(raw_input)
        speaker = data.get("agent_name")
        speaker = speaker.strip() if isinstance(speaker, str) else ""
        if not speaker:
            return "Error: speaker is missing."

        secret_id = data.get("secret_id")
        to_raw = data.get("to")
        if secret_id is None or to_raw is None:
            raw_inner = data.get("input", "")
            if isinstance(raw_inner, str) and raw_inner.strip():
                try:
                    parsed = json.loads(raw_inner)
                    if isinstance(parsed, dict):
                        if secret_id is None:
                            secret_id = parsed.get("secret_id")
                        if to_raw is None:
                            to_raw = parsed.get("to")
                except (ValueError, TypeError):
                    pass

        secret_id = secret_id.strip() if isinstance(secret_id, str) else ""
        to_raw = to_raw.strip() if isinstance(to_raw, str) else ""
        if not secret_id or not to_raw:
            return "Error: both secret_id and to are required."

        if to_raw.casefold() == speaker.casefold():
            return "Error: you cannot share a secret with yourself."

        loc = (character.get_character_current_location(speaker) or "").strip()
        room = (character.get_character_current_room(speaker) or "").strip()
        if not loc or not room:
            return "Error: you are not currently in a room."

        present = room_entry.characters_in_room(loc, room, exclude=speaker)
        to = _resolve_exact_name(to_raw, present)
        if not to:
            return f"Error: {to_raw} is not in the same room."
        if to == speaker:
            return "Error: you cannot share a secret with yourself."

        owner, secret = _find_secret(speaker, secret_id)
        if secret is None or owner is None:
            return "Error: unknown secret."
        if owner != speaker and not secrets.knows(secret, speaker):
            return "Error: you do not know that secret."

        if secrets.knows(secret, to) or secrets.get_secret(to, secret_id) is not None:
            return f"{to} already knows that."

        if secrets.add_known_by(owner, secret_id, to):
            return f"{to} now knows it."
        return "Error: could not record that."


def _resolve_exact_name(raw: str, candidates: list) -> str:
    """Resolve a recipient name against present characters: exact, then case-insensitive exact."""
    if raw in candidates:
        return raw
    folded = raw.casefold()
    for name in candidates:
        if isinstance(name, str) and name.casefold() == folded:
            return name
    return ""


def _find_secret(speaker: str, secret_id: str):
    """Locate (owner, secret) by checking speaker's mind first, then all characters."""
    own = secrets.get_secret(speaker, secret_id)
    if own is not None:
        return speaker, own
    for name in character.list_available_characters(include_dormant=True):
        found = secrets.get_secret(name, secret_id)
        if found is not None:
            return name, found
    return None, None
