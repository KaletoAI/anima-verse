"""State-Flag-Skills + SetPose (Schritt 6, May 2026).

Plan: development_instructions/plan-outfit-system-rethink.md §1.4

State-Flag-Skills die jeweils einen State-Flag oder pose_intent setzen. Sie
ersetzen den generischen SetActivity-Skill fuer die wenigen "Activity-Effekte"
die wirklich Code-Wirkung haben. Die drei Gegensatz-Paare teilen sich je EINE
parameterisierte Klasse, werden aber als zwei klare LLM-Verben registriert
(siehe skill_manager._Verb):

    SleepWakeSkill  → is_sleeping + Off-Map   · Sleep (asleep=True) / WakeUp
    WetSkill        → is_wet (swim-exemption)  · EnterWater (wet=True) / DryOff
    IntimateSkill   → is_intimate (+ Partner)  · StartIntimate (active=True) / EndIntimate
    SetPoseSkill    → pose_intent setzen (kein Flag, nur Pose-Pipeline)

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

class SleepWakeSkill(_BaseFlagSkill):
    """Setzt is_sleeping (+ Off-Map). Eine Implementierung, zwei Verben:
    Sleep (asleep=True) / WakeUp (asleep=False) — der LLM sieht beide Tools."""

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
            logger.debug("offmap toggle (asleep=%s) fehlgeschlagen: %s", self._asleep, e)
        return (f"{character_name} schlaeft jetzt." if self._asleep
                else f"{character_name} ist wieder wach.")


# --- Wet / Dry ------------------------------------------------------------

class WetSkill(_BaseFlagSkill):
    """Setzt is_wet + Compliance-Reeval (Swim-Exemption). Zwei Verben:
    EnterWater (wet=True) / DryOff (wet=False)."""

    def __init__(self, config: Dict[str, Any], wet: bool):
        self._wet = wet
        self.SKILL_ID = "enter_water" if wet else "dry_off"
        self.SKILL_META = "enter_water" if wet else "dry_off"
        super().__init__(config)

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_wet
        set_is_wet(character_name, self._wet)
        # Compliance re-evaluieren damit swim-exemption greift / faellt
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
        except Exception as e:
            logger.debug("compliance nach Wet-Toggle (wet=%s): %s", self._wet, e)
        return (f"{character_name} ist jetzt im Wasser." if self._wet
                else f"{character_name} ist trocken.")


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


class IntimateSkill(_BaseFlagSkill):
    """Setzt is_intimate (selbst + Partner) + Compliance-Override (nude_ok).
    Zwei Verben: StartIntimate (active=True) / EndIntimate (active=False)."""

    def __init__(self, config: Dict[str, Any], active: bool):
        self._active = active
        self.SKILL_ID = "start_intimate" if active else "end_intimate"
        self.SKILL_META = "start_intimate" if active else "end_intimate"
        super().__init__(config)

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_is_intimate
        set_is_intimate(character_name, self._active)
        partner = _resolve_partner(ctx)
        if partner and partner != character_name:
            try:
                set_is_intimate(partner, self._active)
            except Exception as e:
                logger.debug("Partner is_intimate=%s fehlgeschlagen: %s", self._active, e)
        # Compliance reagiert sofort (decency_override → nude_ok bzw. zurueck)
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
            if partner and partner != character_name:
                apply_outfit_compliance(partner)
        except Exception as e:
            logger.debug("compliance nach Intimate-Toggle (active=%s): %s", self._active, e)
        if self._active:
            if partner:
                return f"Intimer Moment zwischen {character_name} und {partner}."
            return f"{character_name} ist im intimen Modus."
        return f"{character_name} verlaesst den intimen Modus."


# --- DecencyExempt --------------------------------------------------------

class DecencyExemptSkill(_BaseFlagSkill):
    """Setzt decency_exempt — Decency-Override auf nude_ok, unabhaengig von
    Anwesenheit/Fremden. Zwei Verben: AllowExposed (active=True) /
    RequireDecency (active=False). Manuelle/Skill-Entsprechung zu is_intimate,
    aber als bewusster Dauerzustand (z.B. Exhibitionismus, FKK)."""

    def __init__(self, config: Dict[str, Any], active: bool):
        self._active = active
        self.SKILL_ID = "allow_exposed" if active else "require_decency"
        self.SKILL_META = "allow_exposed" if active else "require_decency"
        super().__init__(config)

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.models.character import set_decency_exempt
        set_decency_exempt(character_name, self._active)
        # Compliance reagiert sofort (nude_ok → kein Zwangs-Anziehen bzw. zurueck)
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
        except Exception as e:
            logger.debug("compliance nach DecencyExempt-Toggle (active=%s): %s",
                         self._active, e)
        if self._active:
            return f"{character_name} darf sich frei zeigen (Decency aufgehoben)."
        return f"{character_name} haelt sich wieder an die Kleiderordnung."


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
