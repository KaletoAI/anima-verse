"""SearX search plugin - privacy-respecting meta search engine."""
from typing import Any, Dict, List
from urllib.parse import urlencode

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


class SearXPlugin(PluginSkill):
    """
    SearX search skill for web searches through a self-hosted SearX instance.
    Uses the SearX JSON API directly for structured results with titles,
    URLs, snippets and timestamps.

    Configuration:
        World config (admin: Settings -> Skills -> SearX Web Search), declared
        by this package's own ``config_schema``:
            skills.searx.url, .engines, .categories, .num_results
        Per character:
            engines, categories, num_results
    """

    SKILL_ID = "searx"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)

        self.name = "WebSearch"
        self.description = "Searches the web for current information via SearX meta search engine"

        self.searx_host = str(
            ctx.get_config('skills.searx.url', 'http://localhost:8888')
            or 'http://localhost:8888').rstrip('/')

        self._defaults = {
            "engines": str(ctx.get_config('skills.searx.engines') or '').strip(),
            "categories": str(ctx.get_config('skills.searx.categories') or '').strip(),
            "num_results": int(ctx.get_config('skills.searx.num_results', 5) or 5),
        }

        # Connection test
        try:
            resp = ctx.http.get(
                f"{self.searx_host}/search",
                params={"q": "test", "format": "json"},
                timeout=5)
            if resp.ok:
                ctx.logger.info("SearX reachable: %s", self.searx_host)
            else:
                ctx.logger.warning("SearX not reachable: HTTP %d", resp.status_code)
        except Exception as e:
            ctx.logger.error("SearX connection error: %s", e)

    def _search(self, query: str, engines: str, categories: str, num_results: int) -> List[Dict]:
        """Run one search through the SearX JSON API."""
        params = {
            "q": query,
            "format": "json",
        }
        if engines:
            params["engines"] = engines
        if categories:
            params["categories"] = categories

        url = f"{self.searx_host}/search"
        self.ctx.logger.debug("API-Request: %s?%s", url, urlencode(params))

        resp = self.ctx.http.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])[:num_results]
        return results

    def _format_results(self, results: List[Dict], query: str) -> str:
        """Format the search results as readable text for the LLM.

        The wording stays German on purpose: the strings below are what the
        LLM reads, and `save_as_memory` recognises a failed run by their
        first word ("Fehler" / "Keine Ergebnisse").
        """
        if not results:
            return f"Keine Ergebnisse fuer '{query}' gefunden."

        lines = [f"**Suchergebnisse fuer: \"{query}\"**\n"]

        for i, result in enumerate(results, 1):
            title = result.get("title", "Ohne Titel")
            url = result.get("url", "")
            snippet = result.get("content", "").strip()
            published = result.get("publishedDate", "")
            engine_list = result.get("engines", [])
            engine = ", ".join(engine_list) if isinstance(engine_list, list) else str(engine_list)
            img_src = result.get("img_src", "") or result.get("thumbnail", "")

            if url:
                lines.append(f"**{i}. [{title}]({url})**")
            else:
                lines.append(f"**{i}. {title}**")

            meta_parts = []
            if published:
                meta_parts.append(f"Datum: {published}")
            if engine:
                meta_parts.append(f"Quelle: {engine}")
            if meta_parts:
                lines.append(f"   {' | '.join(meta_parts)}")

            if img_src:
                lines.append(
                    f'   <img src="{img_src}" alt="{title}" '
                    f'style="max-width:300px;max-height:300px;border-radius:6px;margin:4px 0;" />'
                )

            if snippet:
                lines.append(f"   {snippet}")

            lines.append("")

        lines.append(f"*{len(results)} Ergebnisse gefunden*")
        return "\n".join(lines)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "SearX Skill ist nicht verfuegbar."

        ctx = self._parse_base_input(raw_input)
        query = ctx.get("input", raw_input).strip()
        character_name = ctx.get("agent_name", "").strip()
        user_id = ctx.get("user_id", "").strip()

        if not query:
            return "Fehler: Leere Suchanfrage."

        cfg = self._get_effective_config(character_name)
        engines = cfg.get("engines", "")
        categories = cfg.get("categories", "")
        num_results = int(cfg.get("num_results", 10))

        try:
            self.ctx.logger.info("Skill aufgerufen: query=%s", query)
            self.ctx.logger.debug("SearX-URL: %s", self.searx_host)
            if engines:
                self.ctx.logger.debug("Engines: %s", engines)
            if categories:
                self.ctx.logger.debug("Categories: %s", categories)
            self.ctx.logger.debug("Max results: %d", num_results)

            results = self._search(query, engines, categories, num_results)
            formatted = self._format_results(results, query)

            self.ctx.logger.info("%d result(s) found", len(results))
            return formatted

        except Exception as e:
            self.ctx.logger.error("Search failed: %s", e)
            return f"Fehler bei der Suche: {e}"

    def memorize_result(self, result: str, character_name: str) -> bool:
        """Store web search results as a memory (for scheduler calls)."""
        if not result or result.startswith("Fehler") or result.startswith("Keine Ergebnisse"):
            return False
        try:
            from app.models.memory import add_memory
            # Shorten the result — only the first 1500 characters matter
            content = result[:1500]
            add_memory(
                character_name=character_name,
                content=content,
                memory_type="semantic",
                importance=3,
                tags=["scheduler_tool", "web_search"],
                context="scheduler:WebSearch")
            return True
        except Exception as e:
            self.ctx.logger.warning("memorize_result fehlgeschlagen: %s", e)
            return False

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        if 'usage_instructions' in self.config:
            return self.config['usage_instructions']
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "current weather in Berlin")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=f"{self.description}. Input should be a search query.",
            func=self.execute)
