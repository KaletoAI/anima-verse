"""Act verb — concrete in-scene action witnessed by everyone in scope.

Thin LLM tool surface over the core act engine (app/core/act_engine.py):
the storyteller LLM narrates the consequence, may resolve active events,
and records the narration into the room stream. The same engine also
powers the avatar direct-action / storyteller-fallback flow in
routes/play.py — which is why it is core (R5), not package code.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


class ActSkill(PluginSkill):
    """Concrete in-scene action witnessed by everyone in scope.

    The storyteller LLM narrates the consequence; active events may be
    resolved if the narration includes an [EVENT_RESOLVED:…] marker
    (gated by category — danger needs independent validator agreement).
    """

    SKILL_ID = "act"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/act.md
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "Act Skill is disabled."

        from app.core.act_engine import (
            perform_act, _extract_text_and_scope, _sender_on_cooldown,
            SENDER_COOLDOWN_MIN)

        ctx = self._parse_base_input(raw_input)
        actor = (ctx.get("agent_name") or "").strip()
        if not actor:
            return "Error: actor context missing."

        text, scope = _extract_text_and_scope(ctx)
        if not text:
            return "Error: empty action text."
        if scope not in ("here", "location"):
            scope = "here"

        if _sender_on_cooldown(actor, scope):
            return (f"You acted very recently — wait at least "
                    f"{SENDER_COOLDOWN_MIN} minutes before the next action.")

        # Sync entry point for tool-LLM callers — drive the async pipeline
        # via asyncio. Top-level routes use ``await perform_act(...)`` directly.
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an event loop — schedule and wait via thread.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_asyncio.run, perform_act(actor, text, scope))
                    result = fut.result()
            else:
                result = _asyncio.run(perform_act(actor, text, scope))
        except RuntimeError:
            result = _asyncio.run(perform_act(actor, text, scope))
        return result.get("summary", "Action performed.")

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(
            fmt, self.name,
            '{"text": "draws her bow and scares off the wolves", "scope": "here"}')

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Input JSON: {{\"text\": \"<what you do>\", \"scope\": \"here\"|\"location\"}}."
            ),
            func=self.execute)
