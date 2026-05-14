"""State-Flag-Skills + SetPose (Schritt 6, May 2026).

Plan: development_instructions/plan-outfit-system-rethink.md §1.4

Sieben kleine Skills die jeweils einen State-Flag oder pose_intent setzen.
Sie ersetzen den generischen SetActivity-Skill fuer die wenigen
"Activity-Effekte" die wirklich Code-Wirkung haben:

    Sleep         → is_sleeping=True  + go_offmap (off-map per Helper)
    WakeUp        → is_sleeping=False + return-from-offmap
    EnterWater    → is_wet=True       (Decency swim-exemption greift)
    DryOff        → is_wet=False
    StartIntimate → is_intimate=True (selbst + Partner falls angegeben)
    EndIntimate   → is_intimate=False (selbst + Partner falls angegeben)
    SetPose       → pose_intent setzen (kein Flag, nur Pose-Pipeline)

Compliance liest die Flags via get_state_flags() und reagiert entsprechend.
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
    """Shared scaffolding fuer alle State-Flag-Skills.

    Subklasse setzt SKILL_ID + SKILL_META + überschreibt _apply().
    """
    SKILL_META = ""  # name of the shared/templates/llm/skills/*.md file
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta(self.SKILL_META) or {}
        self.name = meta.get("name") or self.__class__.__name__
        self.description = meta.get("description") or ""
        self._defaults = {"enabled": True}

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        """Subklasse: macht den eigentlichen State-Change. Returns Text fuer LLM."""
        raise NotImplementedError

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} Skill ist deaktiviert."
        ctx, char = _agent_from_input(self, raw_input)
        if not char:
            return "Fehler: character_name fehlt."
        try:
            return self._apply(char, ctx)
        except Exception as e:
            logger.exception("%s [%s] fehlgeschlagen: %s", self.name, char, e)
            return f"Fehler in {self.name}: {e}"

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        func=self.execute)


# --- Sleep / WakeUp -------------------------------------------------------

class SleepSkill(_BaseFlagSkill):
    SKILL_ID = "sleep"
    SKILL_META = "sleep"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_sleeping, enter_offmap_sleep
        set_is_sleeping(character_name, True)
        try:
            enter_offmap_sleep(character_name)
        except Exception as e:
            logger.debug("enter_offmap_sleep fehlgeschlagen: %s", e)
        return f"{character_name} schlaeft jetzt."


class WakeUpSkill(_BaseFlagSkill):
    SKILL_ID = "wakeup"
    SKILL_META = "wakeup"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_sleeping, wake_from_offmap
        set_is_sleeping(character_name, False)
        try:
            wake_from_offmap(character_name)
        except Exception as e:
            logger.debug("wake_from_offmap fehlgeschlagen: %s", e)
        return f"{character_name} ist wieder wach."


# --- Wet / Dry ------------------------------------------------------------

class EnterWaterSkill(_BaseFlagSkill):
    SKILL_ID = "enter_water"
    SKILL_META = "enter_water"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_wet
        set_is_wet(character_name, True)
        # Compliance re-evaluieren damit swim-exemption greift
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
        except Exception as e:
            logger.debug("compliance nach EnterWater: %s", e)
        return f"{character_name} ist jetzt im Wasser."


class DryOffSkill(_BaseFlagSkill):
    SKILL_ID = "dry_off"
    SKILL_META = "dry_off"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_wet
        set_is_wet(character_name, False)
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
        except Exception as e:
            logger.debug("compliance nach DryOff: %s", e)
        return f"{character_name} ist trocken."


# --- Intimate -------------------------------------------------------------

def _resolve_partner(ctx: Dict[str, Any]) -> str:
    """partner_name aus JSON-Input oder erstem Token."""
    partner = (ctx.get("partner") or ctx.get("partner_name") or "").strip()
    if partner:
        return partner
    # Freitext-Fallback
    text = (ctx.get("input") or "").strip()
    if text:
        return text.split()[0]
    return ""


class StartIntimateSkill(_BaseFlagSkill):
    SKILL_ID = "start_intimate"
    SKILL_META = "start_intimate"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_intimate
        set_is_intimate(character_name, True)
        partner = _resolve_partner(ctx)
        if partner and partner != character_name:
            try:
                set_is_intimate(partner, True)
            except Exception as e:
                logger.debug("Partner is_intimate fehlgeschlagen: %s", e)
        # Compliance reagiert sofort (decency_override → nude_ok)
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
            if partner and partner != character_name:
                apply_outfit_compliance(partner)
        except Exception as e:
            logger.debug("compliance nach StartIntimate: %s", e)
        if partner:
            return f"Intimer Moment zwischen {character_name} und {partner}."
        return f"{character_name} ist im intimen Modus."


class EndIntimateSkill(_BaseFlagSkill):
    SKILL_ID = "end_intimate"
    SKILL_META = "end_intimate"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_intimate
        set_is_intimate(character_name, False)
        partner = _resolve_partner(ctx)
        if partner and partner != character_name:
            try:
                set_is_intimate(partner, False)
            except Exception as e:
                logger.debug("Partner is_intimate clear fehlgeschlagen: %s", e)
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
            if partner and partner != character_name:
                apply_outfit_compliance(partner)
        except Exception as e:
            logger.debug("compliance nach EndIntimate: %s", e)
        return f"{character_name} verlaesst den intimen Modus."


# --- SetPose --------------------------------------------------------------

class SetPoseSkill(_BaseFlagSkill):
    SKILL_ID = "set_pose"
    SKILL_META = "set_pose"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        pose = (ctx.get("pose") or ctx.get("input") or "").strip()
        if not pose:
            return "Fehler: keine Pose angegeben."
        from app.models.character import get_character_profile, save_character_profile
        from app.core.pose_engine import resolve_pose_variant
        # Variant resolven (normalize + match), pose_intent + id speichern
        variant = resolve_pose_variant(character_name, pose)
        prof = get_character_profile(character_name) or {}
        prof["pose_intent"] = pose
        if variant:
            prof["pose_variant_id"] = variant["id"]
        save_character_profile(character_name, prof)
        canonical = (variant or {}).get("canonical_pose") or pose
        return f"{character_name}: {canonical}"
