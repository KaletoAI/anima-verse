"""Party-Skills — invite_to_party + leave_party.

invite_to_party (NPC-Tool): der Character laedt einen Anwesenden in seine Party.
  - Ziel = Avatar -> Pending-Einladung (Frage im Chat-Fenster, UI entscheidet).
  - Ziel = NPC   -> sofortige LLM-Consent-Entscheidung (ask_to_join_party).
leave_party: verlaesst die eigene Party. Follower steigt aus, Leader loest die
  Party auf. Wird Followern im Agent-Loop angeboten (siehe skill_manager).

Siehe development_instructions/plan-party-system.md (Phase 2).
"""
from typing import Any, Dict

from app.core.log import get_logger
from .base import BaseSkill, ToolSpec

logger = get_logger("party_skills")


class _PartyBaseSkill(BaseSkill):
    """Gemeinsames Geruest: Name/Description aus dem Skill-Meta-Template, Input
    parsen, an _apply dispatchen."""
    SKILL_META = ""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta(self.SKILL_META) or {}
        self.name = meta.get("name") or self.__class__.__name__
        self.description = meta.get("description") or ""
        self._defaults = {"enabled": True}

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        raise NotImplementedError

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} ist deaktiviert."
        ctx = self._parse_base_input(raw_input)
        char = (ctx.get("agent_name") or "").strip()
        if not char:
            return "Fehler: character_name fehlt."
        try:
            return self._apply(char, ctx)
        except Exception as e:
            logger.exception("%s [%s] fehlgeschlagen: %s", self.name, char, e)
            return f"Fehler in {self.name}: {e}"

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, func=self.execute)


def _resolve_target(ctx: Dict[str, Any]) -> str:
    target = (ctx.get("target") or ctx.get("partner")
              or ctx.get("partner_name") or "").strip()
    if target:
        return target
    text = (ctx.get("input") or "").strip()
    return text.split()[0] if text else ""


class InviteToPartySkill(_PartyBaseSkill):
    SKILL_ID = "invite_to_party"
    SKILL_META = "invite_to_party"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        target = _resolve_target(ctx)
        if not target or target == character_name:
            return "Wen genau einladen? (kein gueltiges Ziel)"
        if P.is_party_follower(character_name):
            return f"{character_name} ist selbst Teil einer Party und kann niemanden einladen."
        if P.get_party_of(target) is not None:
            return f"{target} ist bereits in einer Party."
        # Avatar als Ziel -> Pending-Einladung (UI-Frage im Chat-Fenster).
        try:
            from app.models.account import is_player_controlled
            _is_avatar = is_player_controlled(target)
        except Exception:
            _is_avatar = False
        if _is_avatar:
            P.create_pending_invite(character_name, target)
            return (f"{character_name} hat {target} in die Party eingeladen "
                    f"— wartet auf dessen Antwort.")
        # NPC -> sofortige LLM-Consent-Entscheidung.
        accepted, preview = P.ask_to_join_party(character_name, target)
        if accepted:
            return f"{target} schliesst sich {character_name}s Party an."
        return f"{target} lehnt die Einladung ab."


class LeavePartySkill(_PartyBaseSkill):
    SKILL_ID = "leave_party"
    SKILL_META = "leave_party"

    def _apply(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        res = P.leave_party(character_name)
        if res.get("status") != "ok":
            return f"{character_name} ist in keiner Party."
        try:
            P.clear_invites_for(character_name)
        except Exception:
            pass
        if res.get("disbanded"):
            return f"{character_name} verlaesst die Party — sie loest sich auf."
        return f"{character_name} verlaesst die Party."
