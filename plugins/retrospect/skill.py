"""Retrospect package — character self-reflection (tool: Reflect).

Loads recent daily/weekly summaries plus episodic memories, asks the LLM to
extract new beliefs, lessons and goals from recent experience, and rewrites
the right ``##`` subsection of the character's editable soul files
(``soul/beliefs.md``, ``soul/lessons.md``, ``soul/goals.md``).

The same files are also user-editable via the Soul-Editor UI — Retrospect
consolidates into the existing structure rather than maintaining a parallel
set of output files.

Tool exposure: takes no arguments — the agent just decides "I want to
reflect now". The thought-context layer hints at this option when enough
new material has accumulated since the last retrospect. The soul engine
(``app.core.soul_writer``) owns the last-retrospect timestamp (two consumers,
core — R5); this package only reads/writes it through that engine.
"""
import json
import re
from typing import Any, Dict, List

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec
from app.core.soul_writer import (
    list_categories, load_all_body_lines, mark_retrospect_done)


class RetrospectSkill(PluginSkill):
    """Lets a character reflect on recent experience and update their
    beliefs / lessons / goals."""

    SKILL_ID = "retrospect"
    ALWAYS_LOAD = True
    # ALWAYS_LOAD=True means the skill is loaded into the manager but hidden
    # for characters that don't have a <char>/skills/retrospect.json with
    # {"enabled": true}.

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/retrospect.md
        self._defaults = {"enabled": True}
        self.ctx.logger.info("Retrospect skill initialized")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "Retrospect is disabled."

        data = self._parse_base_input(raw_input)
        character_name = (data.get("agent_name") or "").strip()
        if not character_name:
            return "Error: agent_name missing."

        # Per-character master switch: the UI toggle "Retrospect: No"
        # overrides the skill default.
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "retrospect_enabled"):
            return "Retrospect disabled for this character."

        from app.models.character import (
            get_character_profile, get_character_language, LANGUAGE_MAP)
        profile = get_character_profile(character_name)
        personality = (profile.get("character_personality", "") or "").strip()
        lang_code = (get_character_language(character_name) or "en").strip()
        language_name = LANGUAGE_MAP.get(lang_code, "English")

        recent_summaries = self._gather_recent_summaries(character_name)
        recent_memories = self._gather_recent_memories(character_name)

        if not recent_summaries and not recent_memories:
            return "Nothing to reflect on yet — no recent material."

        # Show ALL existing entries (not just 15) — the LLM consolidates them
        # and otherwise cannot dedupe older entries at all.
        existing_beliefs = "\n".join(load_all_body_lines(character_name, "beliefs", limit=60))
        existing_lessons = "\n".join(load_all_body_lines(character_name, "lessons", limit=60))
        existing_goals = "\n".join(load_all_body_lines(character_name, "goals", limit=60))

        try:
            from app.core.llm_router import llm_call
            from app.core.prompt_templates import render_task

            sys_prompt, user_prompt = render_task(
                "retrospect",
                character_name=character_name,
                personality=personality or "(not specified)",
                language_name=language_name,
                recent_summaries=recent_summaries or "(none)",
                recent_memories=recent_memories or "(none)",
                existing_beliefs=existing_beliefs,
                existing_lessons=existing_lessons,
                existing_goals=existing_goals)

            response = llm_call(
                task="consolidation",
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                agent_name=character_name)
            raw = (response.content or "").strip()
        except Exception as e:
            self.ctx.logger.error("Retrospect LLM call failed for %s: %s", character_name, e)
            return f"Reflection failed: {e}"

        parsed = self._parse_json(raw)
        if parsed is None:
            self.ctx.logger.warning("Retrospect JSON parse failed for %s: %s",
                                    character_name, raw[:200])
            return "Reflection produced no usable output."

        # Consolidate instead of append: the LLM returns the full, already
        # deduplicated set per bucket → replace the file completely. Do NOT
        # write empty buckets (otherwise "nothing changed" would clear the file).
        counts = {
            "beliefs": self._replace_entries(character_name, "beliefs",
                                             parsed.get("beliefs") or [], lang_code),
            "lessons": self._replace_entries(character_name, "lessons",
                                             parsed.get("lessons") or [], lang_code),
            "goals":   self._replace_entries(character_name, "goals",
                                             parsed.get("goals") or [], lang_code),
        }

        # Goals → standing intents (plan-intents-unified.md): each goal becomes
        # an intent set by the character. Dedupe against existing active intents
        # of the same title so repeated retrospects don't stack them.
        try:
            from app.models.intents import create_intent, list_intents
            existing = {(i.get("title") or "").strip().lower()
                        for i in list_intents(owner=character_name, status="active")}
            for g in (parsed.get("goals") or []):
                if not isinstance(g, dict):
                    continue
                title = (g.get("text") or "").strip()
                if title and title.lower() not in existing:
                    create_intent(owner=character_name, title=title, source="character",
                                  trigger={"kind": "standing"}, priority=3,
                                  meta={"origin": "retrospect_goal"})
                    existing.add(title.lower())
        except Exception as _ge:
            self.ctx.logger.debug("retrospect goals -> intents failed: %s", _ge)

        mark_retrospect_done(character_name)

        updated = [(k, v) for k, v in counts.items() if v is not None]
        if not updated:
            return "Reflected — nothing worth recording this time."
        bits = [f"{n} {k}" for k, n in updated]
        return "Reflected (consolidated): " + ", ".join(bits) + "."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gather_recent_summaries(self, character_name: str) -> str:
        try:
            from app.utils.history_manager import load_daily_summaries_combined
            daily = load_daily_summaries_combined(character_name) or {}
        except Exception:
            return ""
        if not daily:
            return ""
        items = sorted(daily.items())[-5:]
        return "\n".join(f"- {day}: {text}" for day, text in items if text)

    def _gather_recent_memories(self, character_name: str) -> str:
        try:
            from app.models.memory import load_memories
            mems = load_memories(character_name) or []
        except Exception:
            return ""
        sig = [m for m in mems
               if (m.get("importance") or 0) >= 3
               or m.get("memory_type") == "commitment"]
        sig.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        out: List[str] = []
        for m in sig[:12]:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append(f"- {content}")
        return "\n".join(out)

    def _parse_json(self, raw: str):
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = [ln for ln in cleaned.split("\n") if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        m = re.search(r"\{[\s\S]+\}", cleaned)
        try:
            return json.loads(m.group(0) if m else cleaned)
        except Exception:
            return None

    def _replace_entries(self, character_name: str, file_id: str,
                         entries: List[Any], lang_code: str):
        """Replace a soul file with the LLM's consolidated set. Returns the
        number of written entries — or ``None`` when the bucket was empty, in
        which case the existing file is left untouched ("nothing changed")."""
        CAP_PER_CATEGORY = 5  # hard safety net against LLM overproduction
        valid_categories = set(list_categories(file_id))
        cleaned: List[Dict[str, str]] = []
        seen: set = set()
        per_cat: Dict[str, int] = {}
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            text = (e.get("text") or "").strip()
            category = (e.get("category") or "").strip()
            if not text or category not in valid_categories:
                continue
            k = (category, text.lower())
            if k in seen or per_cat.get(category, 0) >= CAP_PER_CATEGORY:
                continue
            seen.add(k)
            per_cat[category] = per_cat.get(category, 0) + 1
            cleaned.append({"text": text, "category": category})
        if not cleaned:
            return None  # nothing usable → keep the existing file
        try:
            from app.core.soul_writer import rewrite_file
            return rewrite_file(character_name, file_id, cleaned, language=lang_code)
        except Exception as ex:
            self.ctx.logger.warning("rewrite_file failed [%s]: %s", file_id, ex)
            return None

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            func=self.execute)
