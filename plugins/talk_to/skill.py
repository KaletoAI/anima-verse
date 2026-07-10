"""TalkTo package — face-to-face message to another character.

Only available when the target character is at the same location as the
sender. For remote communication see the SendMessage skill.

Input format: "CharacterName, message"
Example: "Pixel, can you help me for a moment?"
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.models.character import list_available_characters
from app.core.timeutils import utc_now_iso


class TalkToSkill(PluginSkill):
    """One character speaks to another at the same location.

    Inbox-only: the spoken line is written into both characters' chat
    history (sender as 'assistant', recipient as 'user'); the recipient
    is bumped and processes it on their next AgentLoop turn. The skill
    returns immediately — it no longer blocks for a synchronous reply.

    Tool name/description/action_hint and the CASCADE_BRAKE flag come from
    the package (plugin.yaml + templates/llm/skills/talk_to.md).
    """

    SKILL_ID = "talk_to"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}
        self.ctx.logger.info("TalkTo skill initialized")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "TalkTo Skill is disabled."

        data = self._parse_base_input(raw_input)
        input_text = data.get("input", raw_input).strip()
        sender_name = data.get("agent_name", "").strip()
        user_id = data.get("user_id", "").strip()

        if not sender_name:
            return "Error: sender context missing."

        # JSON form ({"name"/"to", "message", "volume"} merged into data by
        # _parse_base_input / the executor envelope) takes precedence;
        # legacy form: "Target, message". Volume mirrors the avatar's say
        # feature: whisper = only the addressee hears the content, shout =
        # location-wide earshot (perception compute_earshot).
        target_raw = str(data.get("name") or data.get("to") or "").strip()
        message = str(data.get("message") or "").strip()
        volume = str(data.get("volume") or "").strip().lower()
        if volume not in ("whisper", "shout"):
            volume = ""
        if not (target_raw and message):
            if not input_text:
                return "Error: empty input. Format: 'CharacterName, message'"
            # Parse "Target, message"
            parts = input_text.split(",", 1)
            if len(parts) < 2 or not parts[1].strip():
                parts = input_text.split(" ", 1)
            target_raw = target_raw or parts[0].strip()
            message = message or (parts[1].strip() if len(parts) > 1 else "")
        if not message:
            return f"Error: no message for {target_raw}."

        # Resolve target name
        available = list_available_characters()
        target_name = _resolve_name(target_raw, available)
        if not target_name:
            return f"Character '{target_raw}' not found. Available: {', '.join(available)}"
        if target_name == sender_name:
            return "You cannot talk to yourself."

        # Chat-partner check: TalkTo is for THIRD parties — the current chat
        # partner receives statements directly through the RP, so a TalkTo
        # call would be redundant.
        try:
            from app.models.account import get_chat_partner
            current_partner = (get_chat_partner() or "").strip()
            if current_partner and target_name == current_partner:
                return (
                    f"{target_name} is already in the current conversation — "
                    f"address them directly through your RP speech, not via TalkTo. "
                    f"TalkTo is only for third characters at your location."
                )
        except Exception:
            pass

        # Location check: must be at the same place
        from app.models.character import get_character_current_location
        self_loc = get_character_current_location(sender_name) or ""
        target_loc = get_character_current_location(target_name) or ""
        if not self_loc or self_loc != target_loc:
            return (
                f"{target_name} is not at your location. "
                f"Use SendMessage for remote contact."
            )

        # Sleep / busy check
        from app.models.character import is_character_sleeping
        if is_character_sleeping(target_name):
            return f"{target_name} is sleeping and cannot be reached."
        from app.core.activity_engine import is_character_interruptible
        can_interrupt, busy = is_character_interruptible(target_name)
        if not can_interrupt:
            return f"{target_name} is focused on '{busy}' and cannot be interrupted right now."

        self.ctx.logger.info("TalkTo %s -> %s: %s", sender_name, target_name, message[:100])

        # Pending-Report: when the skill was triggered from a chat with a
        # third party (chain of command), record that the sender owes a
        # follow-up to whoever asked them to talk.
        initiator = data.get("initiator", "").strip()
        if initiator and initiator != sender_name:
            try:
                from app.core.pending_reports import add_report
                add_report(
                    reporter=sender_name,
                    initiator=initiator,
                    initiator_type="user" if initiator == "user" else "character",
                    target=target_name,
                    trigger_type="talk_to_response")
            except Exception as e:
                self.ctx.logger.debug("pending_report add failed: %s", e)

        # Inbox-only: write the spoken line into both characters' chat
        # history. Sender sees their own line as 'assistant', recipient
        # sees it as 'user'. Recipient processes the message in their
        # next AgentLoop turn — TalkTo no longer blocks waiting for a
        # synchronous reply.
        from app.models.chat import save_message
        ts = utc_now_iso()
        # Volume travels in the message metadata; the perception shadow reads
        # it so a whispered line stays private (content only for the addressee)
        # and a shouted one carries location-wide.
        _meta = {"volume": volume} if volume else {}
        try:
            save_message({
                "role": "user", "content": message, "timestamp": ts,
                "speaker": sender_name, "medium": "in_person",
                "metadata": _meta,
            }, character_name=target_name, partner_name=sender_name)
            save_message({
                "role": "assistant", "content": message, "timestamp": ts,
                "speaker": sender_name, "medium": "in_person",
                "metadata": _meta,
            }, character_name=sender_name, partner_name=target_name)
        except Exception as e:
            self.ctx.logger.error("TalkTo: chat-history save failed: %s", e)
            return f"Error saving message to {target_name}."

        # Bump the recipient so they react soon, not on their normal slot.
        try:
            from app.core.agent_loop import get_agent_loop
            get_agent_loop().bump(target_name)
        except Exception as e:
            self.ctx.logger.debug("TalkTo: AgentLoop bump failed: %s", e)

        # Resolve: if this TalkTo answers an open pending_report.
        try:
            from app.core.pending_reports import list_open, mark_resolved
            from app.models.account import get_active_character
            active_avatar = get_active_character() or ""
            for r in list_open(sender_name):
                to_who = r.get("to", "")
                if to_who == target_name or (to_who == "user" and target_name == active_avatar):
                    mark_resolved(sender_name, r["id"])
                    break
        except Exception as e:
            self.ctx.logger.debug("pending_report resolve failed: %s", e)

        return f"Spoke to {target_name}. They will reply when they get to it."

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "Pixel, can you help me with this?")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Input: target character name, comma, message. "
                f"Example: 'Pixel, are you free tonight?'. "
                f"Only works when target is at your location; otherwise use SendMessage."
            ),
            func=self.execute)


def _resolve_name(raw: str, available: list) -> str:
    """Case-insensitive + fuzzy name resolution."""
    raw_lower = raw.lower()
    for name in available:
        if name.lower() == raw_lower:
            return name
    for name in available:
        if raw_lower in name.lower() or name.lower() in raw_lower:
            return name
    return ""
