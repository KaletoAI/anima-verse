"""TalkTo package — face-to-face message to another character.

Only available when the target is within EARSHOT of the sender, matching
the shared addressability rule: the same room plus everyone in the open
within the hearing radius around the sender. For
remote communication see the SendMessage skill.

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
    """One character speaks to another within earshot.

    The spoken line is written into both characters' chat history (sender
    as 'assistant', recipient as 'user') and the recipient is queued for a
    mandatory answer in the AgentLoop's respond lane (``bump_respond``) —
    temporary NPCs included, who answer through ``npc_talk``. The skill
    returns immediately — it does not block for a synchronous reply.

    Tool name/description/action_hint and the CASCADE_BRAKE flag come from
    the package (plugin.yaml + templates/llm/skills/talk_to.md).
    """

    SKILL_ID = "talk_to"

    def available_now(self, facts):
        if not facts.present:
            return "nobody is present"
        if facts.mode == "respond" and facts.present == (facts.partner,):
            return "the chat partner already hears the reply"
        return None

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

        # Resolve target name — from the sender's view: an alias or a
        # knower's label reaches the real character, the real name of a
        # transformed person only for a knower (identity_view.resolve_present).
        from app.core.identity_view import shown_name, shown_names
        available = list_available_characters()
        target_name = _resolve_name(sender_name, target_raw, available)
        if not target_name:
            return (f"Character '{target_raw}' not found. "
                    f"Available: {', '.join(shown_names(sender_name, available))}")
        if target_name == sender_name:
            return "You cannot talk to yourself."
        # Every answer below names the target as the sender perceives them.
        target_shown = shown_name(sender_name, target_name)

        # TalkTo is for THIRD parties. In a reactive chat turn the character
        # is ALREADY answering somebody — the prose of that turn is delivered
        # to them — so a TalkTo aimed back at them would only repeat it. Who
        # that is comes from the TURN, not from a stored chat partner: the
        # executor puts the speaker of the triggering utterance into
        # ``initiator`` (chat_engine.build_chat_context), which is the avatar's
        # name when the player spoke. An autonomous thought turn carries no
        # initiator at all — there the verb IS the only way spoken words reach
        # anyone, avatar included, so nothing is refused here.
        initiator = str(data.get("initiator") or "").strip()
        if initiator and target_name == initiator:
            return (
                f"{target_shown} is the one you are answering right now — "
                f"address them directly through your RP speech, not via TalkTo. "
                f"TalkTo is only for third characters within earshot."
            )

        # The same room + open-air circle as the HUD and perception fan-out.
        # Never add a separate location/room gate after this shared rule.
        from app.core.perception import addressable_for
        if target_name not in addressable_for(sender_name):
            from app.models.character import get_character_current_location
            self_loc = get_character_current_location(sender_name) or ""
            target_loc = get_character_current_location(target_name) or ""
            if not self_loc:
                if target_loc:
                    return (
                        f"{target_shown} is not out here with you — they are "
                        f"inside a location. Use SendMessage for remote contact."
                    )
                return (
                    f"{target_shown} is too far away out here to hear you. "
                    f"Go to them first or use SendMessage for remote contact."
                )
            if self_loc != target_loc:
                return (
                    f"{target_shown} is not at your location. "
                    f"Use SendMessage for remote contact."
                )
            from app.models.character import (get_character_current_room,
                                              get_character_language)
            from app.models.world import get_room_name
            room_label = get_room_name(
                self_loc, get_character_current_room(target_name) or "",
                get_character_language(sender_name) or "de")
            return (
                f"{target_shown} is at this location but in another room "
                f"({room_label}) — they cannot hear you from here. Go to "
                f"them first with SetLocation (a room of your current "
                f"location is a valid target) or use SendMessage."
            )

        # Sleep check
        from app.models.character import is_character_sleeping
        if is_character_sleeping(target_name):
            return f"{target_shown} is sleeping and cannot be reached."

        self.ctx.logger.info("TalkTo %s -> %s: %s", sender_name, target_name, message[:100])

        # Pending-Report: when the skill was triggered from a chat with a
        # third party (chain of command), record that the sender owes a
        # follow-up to whoever asked them to talk.
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

        # Write the spoken line into both characters' chat history. Sender
        # sees their own line as 'assistant', recipient sees it as 'user'.
        # The answer is queued below — TalkTo does not block waiting for a
        # synchronous reply.
        from app.models.chat import save_message
        ts = utc_now_iso()
        # Store both history perspectives without shadowing the same speech
        # act. Its explicit publication below supplies canonical delivery.
        _meta = {"volume": volume} if volume else {}
        try:
            from app.core import perception_shadow
            with perception_shadow.suppressed():
                stored = [
                    save_message({
                        "role": "user", "content": message, "timestamp": ts,
                        "speaker": sender_name, "medium": "in_person",
                        "metadata": _meta,
                    }, character_name=target_name, partner_name=sender_name),
                    save_message({
                        "role": "assistant", "content": message, "timestamp": ts,
                        "speaker": sender_name, "medium": "in_person",
                        "metadata": _meta,
                    }, character_name=sender_name, partner_name=target_name),
                ]
        except Exception as e:
            self.ctx.logger.error("TalkTo: chat-history save failed: %s", e)
            return f"Error saving message to {target_shown}."
        # A write that merely returned False is the same lost message as one
        # that raised (DATA-13) — and the recipient's inbox IS the delivery
        # here, so the tool must not report a line that was never said.
        if not all(stored):
            self.ctx.logger.error(
                "TalkTo: chat-history save for %s -> %s failed (%d of 2 writes) "
                "— the message was not delivered",
                sender_name, target_name, stored.count(False))
            return f"Error saving message to {target_shown}."
        from app.core.perception import record_utterance
        utterance_id = record_utterance(
            speaker=sender_name, content=message, volume=volume or "normal",
            addressees=[target_name], source="talk_to", ts=ts)
        if utterance_id is None:
            return f"Error publishing message to {target_shown}."

        # The addressee OWES an answer: queue it into the respond lane, the
        # same path a room utterance with an addressee takes. A thought bump
        # was the old route and it dead-ended for every character without
        # thoughts — a temporary NPC never answered a TalkTo (2026-10-20).
        try:
            from app.core.agent_loop import get_agent_loop
            if not get_agent_loop().bump_respond(
                    target_name, speaker=sender_name, content=message,
                    volume=volume or "normal", obligatory=True, cascade=False,
                    utterance_id=utterance_id):
                self.ctx.logger.info(
                    "TalkTo: %s cannot answer on its own (player-controlled)",
                    target_name)
        except Exception as e:
            self.ctx.logger.warning("TalkTo: respond bump for %s failed: %s",
                                    target_name, e)

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

        return f"Spoke to {target_shown}. They will reply when they get to it."

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
                f"Only works when the target is within earshot — in your room, "
                f"or nearby when you are out in the open; otherwise use SendMessage."
            ),
            func=self.execute)


def _resolve_name(sender: str, raw: str, available: list) -> str:
    """The real character ``sender`` means with ``raw``.

    Exact first (``identity_view.resolve_present``: roster name, an active
    alias, a knower's label), then a fuzzy substring match against the names
    the sender PERCEIVES (``shown_name``) — never against the real name of a
    person the sender only knows by an alias. A real name the sender may not
    use right now (a transformed person, a non-knower) resolves to nothing:
    no fuzzy fallback for it either.
    """
    from app.core.identity_view import resolve_name, resolve_present, shown_name
    exact = resolve_present(sender, raw)
    if exact:
        return exact
    if resolve_name(sender, raw):
        return ""
    raw_lower = raw.lower()
    for name in available:
        label = shown_name(sender, name).lower()
        if raw_lower in label or label in raw_lower:
            return name
    return ""
