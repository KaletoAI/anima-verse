"""State-flag skills + SetPose (step 6, May 2026).

Plan: development_instructions/plan-outfit-system-rethink.md §1.4

State-flag skills each set one state flag or pose_intent. They replaced the
generic SetActivity skill for the few "activity effects" that really have
code impact. An opposite pair shares ONE parameterized class registered as
two distinct LLM verbs (see skill_manager._Verb):

    SleepWakeSkill  → is_sleeping + off-map   · Sleep (asleep=True) / WakeUp
    SetPoseSkill    → set pose_intent (no flag, pose pipeline only)

Compliance reads the flags via get_state_flags() and reacts accordingly.

The wet/intimacy/decency flag skills were migrated to self-contained
packages (plugins/wet, plugins/intimacy, plugins/decency_exempt — wave 2
pilot of plan-skill-plugin-architecture.md); sleep and set_pose follow in
a later wave (their semantics are still interwoven with the agent loop /
pose engine).
"""
from typing import Any, Dict

from app.core.log import get_logger
from .base import BaseSkill, ToolSpec

logger = get_logger("state_flag_skills")


def _agent_from_input(skill: BaseSkill, raw_input: str) -> tuple[Dict[str, Any], str]:
    """Helper: parse input + extract character_name. Returns (ctx, char)."""
    ctx = skill._parse_base_input(raw_input)
    char = (ctx.get("agent_name") or "").strip()
    return ctx, char


class _BaseFlagSkill(BaseSkill):
    """Shared scaffolding for all state-flag skills.

    Subclass sets SKILL_ID + SKILL_META and overrides _apply().
    """
    SKILL_META = ""  # name of the shared/templates/llm/skills/*.md file
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta(self.SKILL_META) or {}
        self.name = meta.get("name") or self.__class__.__name__
        self.description = meta.get("description") or ""
        self.action_hint = meta.get("action_hint", "")
        self._defaults = {"enabled": True}

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        """Subclass: performs the actual state change. Returns text for the LLM."""
        raise NotImplementedError

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        ctx, char = _agent_from_input(self, raw_input)
        if not char:
            return "Error: character_name missing."
        try:
            return self._apply(char, ctx)
        except Exception as e:
            logger.exception("%s [%s] failed: %s", self.name, char, e)
            return f"Error in {self.name}: {e}"

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        func=self.execute)


# --- Sleep / WakeUp -------------------------------------------------------

class SleepWakeSkill(_BaseFlagSkill):
    """Sets is_sleeping (+ off-map). One implementation, two verbs:
    Sleep (asleep=True) / WakeUp (asleep=False) — the LLM sees both tools."""

    def __init__(self, config: Dict[str, Any], asleep: bool):
        self._asleep = asleep
        self.SKILL_ID = "sleep" if asleep else "wakeup"
        self.SKILL_META = "sleep" if asleep else "wakeup"
        super().__init__(config)

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import (
            set_is_sleeping, enter_offmap_sleep, wake_from_offmap)
        set_is_sleeping(character_name, self._asleep)
        try:
            if self._asleep:
                enter_offmap_sleep(character_name)
            else:
                wake_from_offmap(character_name)
        except Exception as e:
            logger.debug("offmap toggle (asleep=%s) failed: %s", self._asleep, e)
        return (f"{character_name} schlaeft jetzt." if self._asleep
                else f"{character_name} ist wieder wach.")


# --- SetPose --------------------------------------------------------------

class SetPoseSkill(_BaseFlagSkill):
    SINGLETON = True
    SKILL_ID = "set_pose"
    SKILL_META = "set_pose"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        pose = (ctx.get("pose") or ctx.get("input") or "").strip()
        if not pose:
            return "Fehler: keine Pose angegeben."
        from app.models.character import get_character_profile, save_character_profile
        from app.core.pose_engine import resolve_pose_variant
        # Resolve variant (normalize + match), store pose_intent + id
        variant = resolve_pose_variant(character_name, pose)
        prof = get_character_profile(character_name) or {}
        prof["pose_intent"] = pose
        if variant:
            prof["pose_variant_id"] = variant["id"]
        save_character_profile(character_name, prof)
        canonical = (variant or {}).get("canonical_pose") or pose
        return f"{character_name}: {canonical}"
