"""InstagramComment skill — a character comments on someone else's post.

Typically invoked from a forced thought triggered by a new post during
feed processing.

Input format: "post_id: comment" or JSON {"post_id": "...", "text": "..."}
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.models.instagram import add_comment, add_character_like, get_post


class InstagramCommentSkill(PluginSkill):
    """Writes a comment on an Instagram post."""

    SKILL_ID = "instagram_comment"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/instagram_comment.md
        self._defaults = {"enabled": True, "auto_like": True}
        self.ctx.logger.info("InstagramComment skill initialized")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "InstagramComment Skill is disabled."

        data = self._parse_base_input(raw_input)
        commenter = data.get("agent_name", "").strip()
        if not commenter:
            return "Error: agent context missing."

        post_id, text = _parse_input(data)
        if not post_id:
            return "Error: post_id missing."
        if not text:
            return f"Error: empty comment for {post_id}."

        post = get_post(post_id)
        if not post:
            return f"Error: post {post_id} not found."

        try:
            add_comment(post_id=post_id, commenter_name=commenter, text=text)
            self.ctx.logger.info("Instagram comment: %s -> post %s: %s", commenter, post_id, text[:80])
        except Exception as e:
            self.ctx.logger.error("Comment add failed: %s", e)
            return f"Error: {e}"

        # Optional auto-like (on by default)
        cfg = self._get_effective_config(commenter)
        if cfg.get("auto_like", True):
            try:
                add_character_like(post_id, commenter)
            except Exception:
                pass

        # Recomment bump: poster and prior commenters get a chance to react
        # on their next AgentLoop slot. The post surfaces in the
        # instagram_pending_block (within pending_window_hours), so they have
        # full context. agent_loop.bump filters reserved names, sleepers and
        # the avatar — so we can call it broadly.
        try:
            _bump_recomment_audience(post, commenter)
        except Exception as e:
            self.ctx.logger.debug("Recomment bump skipped: %s", e)

        return f"Comment posted on {post_id}: {text[:120]}"

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "post_abc123: Nice picture!")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Use only when you actually want to react to a specific post."
            ),
            func=self.execute)


_RECOMMENT_BUMP_LIMIT = 5  # max prior-commenter bumps per new comment


def _bump_recomment_audience(post: Dict[str, Any], commenter: str) -> None:
    """Bump the poster + recent unique commenters so they can recomment.

    Self-bump is skipped. Order: poster first, then most recent unique
    prior commenters (capped). agent_loop.bump dedups and filters
    ineligible names internally.
    """
    from app.core.agent_loop import get_agent_loop

    loop = get_agent_loop()
    if not loop:
        return

    poster = (post.get("agent_name") or "").strip()
    bumped: set = {commenter}
    if poster and poster not in bumped:
        loop.bump(poster)
        bumped.add(poster)

    # Most recent prior commenters first, dedup, cap.
    prior_count = 0
    for c in reversed(post.get("comments") or []):
        if prior_count >= _RECOMMENT_BUMP_LIMIT:
            break
        author = (c.get("author") or "").strip()
        if not author or author in bumped:
            continue
        loop.bump(author)
        bumped.add(author)
        prior_count += 1


def _parse_input(data: Dict[str, Any]) -> tuple:
    """Extract (post_id, text) from the input.

    Accepts: JSON fields in data, or the string 'post_id: text'.
    """
    post_id = (data.get("post_id") or "").strip()
    text = (data.get("text") or data.get("comment") or "").strip()
    if post_id and text:
        return post_id, text

    raw = (data.get("input") or "").strip()
    if not raw:
        return "", ""
    if ":" in raw:
        pid, rest = raw.split(":", 1)
        return pid.strip(), rest.strip()
    # Fallback: only post_id without text
    return raw.strip(), text
