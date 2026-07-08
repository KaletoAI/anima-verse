"""InstagramReply skill — a creator replies to a comment on their own post.

Typically invoked from a forced thought triggered by a new comment.

Input format: "post_id @commenter: text" or JSON {post_id, commenter, text}
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.models.instagram import add_comment, get_post


class InstagramReplySkill(PluginSkill):
    """Replies as the creator to a comment on their own post."""

    SKILL_ID = "instagram_reply"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/instagram_reply.md
        self._defaults = {"enabled": True}
        from plugins.instagram.social_reactions import ensure_registered
        ensure_registered()
        self.ctx.logger.info("InstagramReply skill initialized")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "InstagramReply Skill is disabled."

        data = self._parse_base_input(raw_input)
        creator = data.get("agent_name", "").strip()
        if not creator:
            return "Error: agent context missing."

        post_id, commenter, text = _parse_input(data)
        if not post_id:
            return "Error: post_id missing."
        if not text:
            return "Error: empty reply."

        post = get_post(post_id)
        if not post:
            return f"Error: post {post_id} not found."
        if post.get("agent_name", "") and post.get("agent_name", "") != creator:
            return f"Error: post {post_id} belongs to {post.get('agent_name', '')}, not you."

        body = f"@{commenter} {text}" if commenter else text
        try:
            add_comment(post_id=post_id, commenter_name=creator, text=body)
            self.ctx.logger.info("Instagram reply: %s -> %s on %s: %s",
                                 creator, commenter, post_id, text[:80])
        except Exception as e:
            self.ctx.logger.error("Reply add failed: %s", e)
            return f"Error: {e}"

        return f"Reply posted on {post_id}: {body[:120]}"

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "post_abc @Pixel: Thanks for the kind comment!")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            func=self.execute)


def _parse_input(data: Dict[str, Any]) -> tuple:
    """Extract (post_id, commenter, text) from the input."""
    post_id = (data.get("post_id") or "").strip()
    commenter = (data.get("commenter") or "").strip()
    text = (data.get("text") or data.get("reply") or "").strip()
    if post_id and text:
        return post_id, commenter, text

    raw = (data.get("input") or "").strip()
    if not raw:
        return "", "", ""

    # Format: "post_id @commenter: text"
    parts = raw.split(":", 1)
    if len(parts) == 2:
        head = parts[0].strip()
        text = parts[1].strip()
        if "@" in head:
            pid, mention = head.split("@", 1)
            return pid.strip(), mention.strip(), text
        return head.strip(), commenter, text

    return raw.strip(), commenter, text
