"""Notify-user package — SendNotification verb.

Lets a character proactively send a system notification to the active
avatar. Mainly used by the thought system, but callable in normal chat too.

The notification is also stored as a chat message in the character's history
with the active user avatar — so the character knows later, in context, what
it announced.

Cooldown: at most one notification per character every NOTIFY_COOLDOWN_MIN
minutes (default 30) — prevents notification spam from repeated thought loops.

USER_NOTIFICATION / PROGRESS_TYPE come from the manifest (F7 flags) and let
the core forward the result as a user notification generically.
"""
import os
import time
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext

from app.models.notifications import create_notification

# Cooldown per character (in minutes)
NOTIFY_COOLDOWN_MIN = int(os.environ.get("SKILL_NOTIFY_USER_COOLDOWN_MIN", "30"))
_last_notification_ts: Dict[str, float] = {}  # character_name -> monotonic ts


class NotifyUserSkill(PluginSkill):
    """Sends a notification to the user, even when the user is not actively
    in the chat."""

    SKILL_ID = "notify_user"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/notify_user.md
        self._defaults = {}

    def execute(self, raw_input: str) -> str:
        """Create a notification for the user.

        Input (from the LLM): simply the message, e.g. "Don't forget: meeting
        at 2pm!" — or JSON {"input": "...", "agent_name": "...", "user_id": "..."}.
        """
        if not self.enabled:
            return "SendNotification skill is not available."

        data = self._parse_base_input(raw_input)
        input_text = data.get("input", raw_input).strip()
        character_name = data.get("agent_name", "").strip()
        user_id = data.get("user_id", "").strip()

        if not character_name:
            return "Error: agent name missing."
        if not input_text:
            return "Error: no message given."

        # Cooldown check: prevents notification spam
        now_mono = time.monotonic()
        last = _last_notification_ts.get(character_name, 0.0)
        wait_s = NOTIFY_COOLDOWN_MIN * 60 - (now_mono - last)
        if wait_s > 0:
            self.ctx.logger.info("Notification from %s blocked: cooldown %.0fs left",
                                 character_name, wait_s)
            return (f"Notification not sent: cooldown active "
                    f"(last notification {(now_mono-last)/60:.1f} min ago, "
                    f"limit every {NOTIFY_COOLDOWN_MIN} min). "
                    f"If urgent: use SendMessage instead.")

        try:
            nid = create_notification(
                character=character_name,
                content=input_text,
                notification_type="message",
                metadata={"trigger": "thought"})
            _last_notification_ts[character_name] = now_mono

            # IMPORTANT: also store as a chat message in the history so the
            # character knows later what it announced. Previously the
            # notification only existed in the notif panel; if the user clicked
            # "→ chat" and wrote, the character had no history entry and reacted
            # confused.
            try:
                from app.models.chat import save_message
                from app.models.account import get_player_identity
                from app.core.timeutils import utc_now_iso
                avatar = get_player_identity("")
                if avatar and avatar != character_name:
                    ts = utc_now_iso()
                    save_message({
                        "role": "assistant",
                        "content": input_text,
                        "timestamp": ts,
                        "speaker": character_name,
                        "medium": "messaging",
                    }, character_name=character_name, partner_name=avatar)
                    # Mirror into the avatar inbox so a reload shows the entry
                    save_message({
                        "role": "user",
                        "content": input_text,
                        "timestamp": ts,
                        "speaker": character_name,
                        "medium": "messaging",
                    }, character_name=avatar, partner_name=character_name)
            except Exception as _se:
                self.ctx.logger.debug("Notification → chat history failed: %s", _se)

            self.ctx.logger.info("Notification created: %s (%s -> %s)",
                                 nid, character_name, user_id)
            return f"Notification sent successfully: {input_text}"
        except Exception as e:
            self.ctx.logger.error("Error: %s", e)
            return f"Error sending the notification: {e}"
