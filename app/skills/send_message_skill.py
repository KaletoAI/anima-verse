"""SendMessage skill — remote message to another character.

For remote communication (character not at the same place). Default medium
is "messaging" (internal message window / phone panel).

Input formats:
  - Legacy text: "CharacterName, message" — e.g. "Luna, are you free tonight?"
  - JSON: {"to": "Luna", "message": "look!", "attach_image": true} — with
    attach_image the image generated in the SAME turn is attached to the DM
    (the streaming layer defers such calls until after the image tools ran).
"""
from typing import Any, Dict

from .base import BaseSkill, ToolSpec

from app.core.log import get_logger
logger = get_logger("send_message")

from app.models.character import list_available_characters

from app.core.timeutils import utc_now_iso


class SendMessageSkill(BaseSkill):
    """Sends a remote message to another character.

    Independent of location. The target LLM replies via the central chat
    engine with medium="messaging". The result is returned as skill output.
    """
    CASCADE_BRAKE = True

    SKILL_ID = "send_message"
    # [INTENT: send_message | message=...] (F6) — the deferred follow-up
    # message goes through the chat endpoint, not through execute().
    REMOTE_COMM = True  # reaches characters not present (setup checklist)
    INTENT_TYPES = ("send_message",)
    INTENT_PAYLOAD_KEYS = ("content", "message")

    def handle_intent(self, intent_type, payload):
        """[INTENT: send_message]: post the follow-up via the chat endpoint
        (silent) so it lands in the regular history/stream."""
        import os as _os
        import requests as _requests
        message = payload.get("message", "") or payload.get("content", "")
        if not message:
            return {"success": False, "error": "missing message"}
        try:
            port = _os.environ.get("PORT", "8000")
            resp = _requests.post(
                f"http://localhost:{port}/chat/{payload.get('user_id', '')}",
                json={"agent": payload.get("agent_name", ""),
                      "message": message, "silent": True},
                timeout=60)
            return {"success": resp.ok, "status": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def defer_for_attachment(self, raw_input: str) -> bool:
        """attach_image requests must run AFTER this turn's deferred image
        tools — the attachment (the generated image) only exists then."""
        if not raw_input or "attach_image" not in raw_input:
            return False
        stripped = raw_input.strip()
        if stripped.startswith("{"):
            import json as _json
            try:
                data, _ = _json.JSONDecoder().raw_decode(stripped)
                return bool(isinstance(data, dict) and data.get("attach_image"))
            except ValueError:
                return True  # mentions attach_image but unparseable — defer to be safe
        return True

    def tool_intent_payload(self, raw_input: str) -> str:
        """SendMessage freetext convention: "Recipient, message" — the part
        after the first comma is the comparable content."""
        s = (raw_input or "").strip()
        if not s:
            return ""
        if s.startswith("{"):
            return super().tool_intent_payload(raw_input)
        parts = s.split(",", 1)
        return parts[1] if len(parts) > 1 else s

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("send_message")
        self.name = meta["name"]
        self.description = meta["description"]
        self.action_hint = meta.get("action_hint", "")
        self._defaults = {"enabled": True}
        logger.info("SendMessage Skill initialized")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "SendMessage Skill is disabled."

        ctx = self._parse_base_input(raw_input)
        input_text = ctx.get("input", raw_input).strip()
        sender_name = ctx.get("agent_name", "").strip()
        user_id = ctx.get("user_id", "").strip()

        if not sender_name:
            return "Error: sender context missing."

        # JSON form ({"to", "message", "attach_image"} merged into ctx by
        # _parse_base_input) takes precedence; legacy form: "Name, message".
        target_raw = str(ctx.get("to") or "").strip()
        message = str(ctx.get("message") or "").strip()
        attach_image = bool(ctx.get("attach_image"))
        if not (target_raw and message):
            if not input_text:
                return "Error: empty input. Format: 'CharacterName, message'"
            parts = input_text.split(",", 1)
            if len(parts) < 2 or not parts[1].strip():
                parts = input_text.split(" ", 1)
            target_raw = target_raw or parts[0].strip()
            message = message or (parts[1].strip() if len(parts) > 1 else "")
        if not message:
            return f"Error: no message for {target_raw}."

        available = list_available_characters()
        target_name = _resolve_name(target_raw, available)
        if not target_name:
            return f"Character '{target_raw}' not found. Available: {', '.join(available)}"
        if target_name == sender_name:
            return "You cannot message yourself."

        # Sleep check (no busy check — messages can always be sent, the
        # recipient reads them when they have time)
        from app.models.character import is_character_sleeping
        if is_character_sleeping(target_name):
            return f"{target_name} is sleeping — message queued, but no response for now."

        # Detect avatar target: when the recipient is the player-controlled
        # character, SendMessage counts as a "proactive chat message to the
        # player". No notification (pollutes the system event feed), no
        # forced_thought (the avatar does not think autonomously).
        from app.models.account import is_player_controlled as _is_pc
        target_is_avatar = _is_pc(target_name)

        logger.info("SendMessage %s -> %s: %s", sender_name, target_name, message[:100])

        initiator = ctx.get("initiator", "").strip()
        if initiator and initiator != sender_name:
            try:
                from app.core.pending_reports import add_report
                add_report(
                    reporter=sender_name,
                    initiator=initiator,
                    initiator_type="user" if initiator == "user" else "character",
                    target=target_name,
                    trigger_type="message_response")
            except Exception as e:
                logger.debug("pending_report add failed: %s", e)

        # Optional image attachment: the image generated in this turn. The
        # streaming layer defers attach-sends until after the image tools, so
        # the file exists by now. Without a resolvable image the DM goes out
        # as text-only (never a placeholder).
        attached_image = ""
        if attach_image:
            attached_image = _resolve_turn_image(sender_name)
            if attached_image:
                logger.info("SendMessage %s: attaching image %s",
                            sender_name, attached_image)
            else:
                logger.info("SendMessage %s: attach_image requested but no "
                            "recent image found — sending text only", sender_name)
        _msg_meta = {"image": attached_image} if attached_image else {}

        # Asynchronous: store the message + notification + schedule a
        # forced_thought for the recipient. The sender does NOT wait for the
        # reply — that is DM semantics (messaging, not a call). Waiting
        # synchronously would blow the outer thought timeout on nested
        # LLM-queue calls.
        from datetime import datetime
        ts = utc_now_iso()

        try:
            from app.models.chat import save_message
            # Recipient history: sender as originator (role=user)
            save_message({
                "role": "user", "content": message, "timestamp": ts,
                "speaker": sender_name, "medium": "messaging",
                "metadata": _msg_meta,
            }, character_name=target_name, partner_name=sender_name)
            # Sender history: sender as author (role=assistant)
            save_message({
                "role": "assistant", "content": message, "timestamp": ts,
                "speaker": sender_name, "medium": "messaging",
                "metadata": _msg_meta,
            }, character_name=sender_name, partner_name=target_name)
        except Exception as e:
            logger.error("SendMessage: saving chat history failed: %s", e)

        # Push bridge (Telegram option B): if the target is a Telegram-bound
        # avatar of this sender (NPC), deliver the message to the Telegram
        # chat. Sync enqueue; the NPC's poller delivers it asynchronously.
        # (Image attachments are not bridged yet — text only, phase 2.)
        try:
            from app.models.telegram_channel import (
                get_telegram_channel, enqueue_telegram_outbound)
            tg = get_telegram_channel()
            for cid in tg.chat_ids_for(npc=sender_name, avatar=target_name):
                enqueue_telegram_outbound(cid, sender_name, message)
        except Exception as _be:
            logger.debug("telegram outbound enqueue failed: %s", _be)

        # Notification only for character→character (keeps the system event
        # feed clean of "X wrote Y" spam). For an avatar target the chat
        # history entry suffices — the unread indicator pings automatically.
        if not target_is_avatar:
            try:
                from app.models.notifications import create_notification
                create_notification(
                    character=sender_name,
                    content=f"Nachricht an {target_name}: {message[:500]}",
                    notification_type="message",
                    metadata={"trigger": "send_message", "to": target_name})
            except Exception as e:
                logger.debug("SendMessage: Notification fehlgeschlagen: %s", e)

        # AgentLoop bump: recipient gets prioritised on the next slot so
        # they see the inbox message soon (not waiting for their normal
        # importance quota). Avatars don't think autonomously, so skip.
        if not target_is_avatar:
            try:
                from app.core.agent_loop import get_agent_loop
                get_agent_loop().bump(target_name)
            except Exception as e:
                logger.debug("SendMessage: AgentLoop bump failed: %s", e)

        # Resolve: if this send resolves an open pending_report, mark it.
        # Heuristic: target == initiator of an open report.
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
            logger.debug("pending_report resolve failed: %s", e)

        if attached_image:
            return (f"Message with photo sent to {target_name}. "
                    f"They will reply when they get to it.")
        return f"Message sent to {target_name}. They will reply when they get to it."

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "Luna, are you free tonight?")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Input: target character name, comma, message. "
                f"Example: 'Luna, dinner at 8?'. "
                f'To send along a photo taken THIS turn use JSON: '
                f'{{"to": "Luna", "message": "look!", "attach_image": true}}. '
                f"No other attachments exist — NEVER write placeholder text "
                f"like '[image attached]'. For face-to-face use TalkTo instead."
            ),
            func=self.execute)


def _resolve_turn_image(sender_name: str) -> str:
    """URL path of the image the sender generated in this turn, or "".

    Primary source: the ImageGenerationSkill's last-generation meta —
    thread-local slot first, instance mirror as fallback (the deferred
    SendMessage may run on a different worker thread than the image tool).
    The meta must belong to the sender. Fallback: the sender's newest
    gallery file, if it is fresh (≤ 15 min).
    """
    from urllib.parse import quote
    try:
        from app.core.dependencies import get_skill_manager
        from app.skills.image_generation_skill import ImageGenerationSkill
        for sk in get_skill_manager().skills:
            if not isinstance(sk, ImageGenerationSkill):
                continue
            metas = []
            tls = getattr(sk, "_meta_tls", None)
            if tls is not None:
                metas.append(getattr(tls, "last_image_meta", None))
            metas.append(getattr(sk, "last_image_meta", None))
            for meta in metas:
                if not isinstance(meta, dict):
                    continue
                files = meta.get("filenames") or []
                owner = str(meta.get("gallery_character") or "")
                if files and owner == sender_name:
                    return (f"/characters/{quote(owner)}"
                            f"/images/{quote(str(files[-1]))}")
            break
    except Exception as e:
        logger.debug("attach_image: skill meta lookup failed: %s", e)
    try:
        import time
        from app.models.character import get_character_images_dir
        newest = None
        for p in get_character_images_dir(sender_name).iterdir():
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
                newest = p
        if newest and time.time() - newest.stat().st_mtime <= 900:
            return (f"/characters/{quote(sender_name)}"
                    f"/images/{quote(newest.name)}")
    except Exception as e:
        logger.debug("attach_image: gallery fallback failed: %s", e)
    return ""


def _resolve_name(raw: str, available: list) -> str:
    raw_lower = raw.lower()
    for name in available:
        if name.lower() == raw_lower:
            return name
    for name in available:
        if raw_lower in name.lower() or name.lower() in raw_lower:
            return name
    return ""
