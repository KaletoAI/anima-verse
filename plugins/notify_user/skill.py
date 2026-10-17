"""Notify-user package — SendNotification verb.

Lets a character proactively send a system notification to the active
avatar. Mainly used by the thought system, but callable in normal chat too.

Notifications stay in the system feed. A phone message requires SendMessage;
publishing a notification must not implicitly create a DM or spoken line.

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
            if not nid:
                # "" means the INSERT did not happen (DATA-13). Nothing was
                # shown to anyone, so this must not report success — and the
                # cooldown is NOT armed for a notification that never was.
                self.ctx.logger.error(
                    "Notification for %s was NOT stored", character_name)
                return ("Error sending the notification: it could not be "
                        "stored and was not delivered.")
            _last_notification_ts[character_name] = now_mono

            self.ctx.logger.info("Notification created: %s (%s -> %s)",
                                 nid, character_name, user_id)
            return f"Notification sent successfully: {input_text}"
        except Exception as e:
            self.ctx.logger.error("Error: %s", e)
            return f"Error sending the notification: {e}"
