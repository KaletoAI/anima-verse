"""Instagram pending block — recent activity the agent may react to.

Package-owned thought-context contribution (wave 5): rendered into the
agent's thought prompt via the generic ``thought_context_block`` skill
hook — the core knows no instagram content anymore.

Two sections (window: ``skills.instagram.pending_window_hours``, default
4, each capped at the 5 newest):
- Foreign posts the agent hasn't commented on yet (→ InstagramComment).
- NEW comments by others under the agent's OWN posts that the agent
  hasn't answered yet (→ InstagramReply). "Answered" = the agent
  commented on that post after the comment; filtered by COMMENT time, so
  an older own post with fresh comments still surfaces.
"""
from datetime import timedelta

from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now

logger = get_logger("instagram_pending")

_HEADER = "=== Instagram (recent) ==="
_INSTRUCTIONS = ("You may use InstagramComment to react to other people's "
                 "posts. Answer new comments under your OWN posts with "
                 "InstagramReply (input: post_id @commenter: your answer).")


def build_pending_block(character_name: str) -> str:
    """Full prompt section (header + pending items + verb instructions);
    empty string when there is nothing pending."""
    try:
        from app.core import config as _cfg
        window_h = int((_cfg.get("skills.instagram.pending_window_hours") or 4))
    except Exception:
        window_h = 4
    try:
        from app.models.instagram import load_feed
        feed = load_feed() or []
    except Exception as e:
        logger.debug("pending feed load failed: %s", e)
        return ""
    if not feed:
        return ""

    def _comment_dt(c):
        try:
            return parse_iso(c.get("timestamp") or "")
        except Exception:
            return None

    def _comment_author(c):
        # Saved comments use "author" (instagram.add_comment); legacy data
        # may have "by" or "character".
        return c.get("author") or c.get("by") or c.get("character") or ""

    cutoff = utc_now() - timedelta(hours=window_h)
    relevant = []
    own_replies = []  # (comment_dt, post, comment)
    for post in feed:
        comments = post.get("comments") or []
        if post.get("agent_name") == character_name:
            # Own post: surface others' comments the agent hasn't answered.
            own_times = [dt for c in comments
                         if _comment_author(c) == character_name
                         and (dt := _comment_dt(c))]
            last_own = max(own_times) if own_times else None
            for c in comments:
                if _comment_author(c) == character_name:
                    continue
                cdt = _comment_dt(c)
                if cdt is None or cdt < cutoff:
                    continue
                if last_own and cdt <= last_own:
                    continue  # already answered after this comment
                own_replies.append((cdt, post, c))
            continue
        ts = post.get("timestamp", "") or ""
        try:
            post_dt = parse_iso(ts)
        except Exception:
            continue
        if post_dt < cutoff:
            continue
        # Skip if this character already commented on the post.
        already = any(_comment_author(c) == character_name for c in comments)
        if already:
            continue
        relevant.append((post_dt, post))

    parts = []
    if relevant:
        relevant.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for _, post in relevant[:5]:
            poster = post.get("agent_name", "?")
            post_id = post.get("post_id") or post.get("id") or ""
            caption = (post.get("caption") or "").strip()
            if len(caption) > 140:
                caption = caption[:140].rstrip() + "…"
            # Surface image_analysis when available — gives the agent
            # something concrete to react to without shipping the image
            # (the vision LLM already did that earlier).
            analysis = ""
            meta = post.get("image_meta") or {}
            if isinstance(meta, dict):
                analysis = (meta.get("image_analysis") or "").strip()
            line = f"- [{post_id}] {poster}: \"{caption}\""
            if analysis:
                if len(analysis) > 140:
                    analysis = analysis[:140].rstrip() + "…"
                line += f"\n    Image: {analysis}"
            lines.append(line)
        parts.append("Recent Instagram posts you haven't reacted to yet:\n"
                     + "\n".join(lines))
    if own_replies:
        own_replies.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for _, post, c in own_replies[:5]:
            post_id = post.get("post_id") or post.get("id") or ""
            txt = (c.get("text") or "").strip()
            if len(txt) > 140:
                txt = txt[:140].rstrip() + "…"
            lines.append(f"- [{post_id}] {_comment_author(c) or '?'}: \"{txt}\"")
        parts.append("New comments under YOUR OWN posts you haven't answered yet:\n"
                     + "\n".join(lines))
    if not parts:
        return ""
    return _HEADER + "\n" + "\n\n".join(parts) + "\n" + _INSTRUCTIONS
