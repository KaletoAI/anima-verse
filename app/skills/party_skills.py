"""Party-Skills — gemeinsam reisen, EINE Klasse, drei Verben (wie WetSkill
enter/leave): PartySkill mit verb='invite'|'join'|'leave' (via skill_manager._Verb).

  invite_to_party (verb='invite'): der Character laedt einen Anwesenden ein.
    - Ziel = Avatar -> Pending-Einladung (Frage im Chat-Fenster, UI entscheidet).
    - Ziel = NPC   -> sofortige LLM-Consent-Entscheidung (ask_to_join_party).
  join_party (verb='join'): der Character TRITT der Party eines Anwesenden BEI —
    der robuste Weg fuer "X laedt mich ein, ich sage zu": die Tool-LLM ruft das
    Skill im normalen Antwort-Turn auf (keine Keyword-Erkennung, keine separate
    Consent-Runde).
  leave_party (verb='leave'): verlaesst die eigene Party (Follower steigt aus,
    Leader = Aufloesung). Followern im Agent-Loop angeboten (siehe skill_manager).

Siehe development_instructions/plan-party-system.md.
"""
from typing import Any, Dict

from app.core.log import get_logger
from .base import BaseSkill, ToolSpec

logger = get_logger("party_skills")

_VERB_TO_ID = {"invite": "invite_to_party", "join": "join_party", "leave": "leave_party"}


def _resolve_target(ctx: Dict[str, Any]) -> str:
    target = (ctx.get("leader") or ctx.get("target") or ctx.get("partner")
              or ctx.get("partner_name") or "").strip()
    if target:
        return target
    text = (ctx.get("input") or "").strip()
    return text.split()[0] if text else ""


class PartySkill(BaseSkill):
    """Party-Verben in einer Klasse. Subklasse-frei: ein verb-Parameter waehlt die
    Operation; SKILL_ID/SKILL_META leiten sich daraus ab (vor super().__init__,
    damit das Meta-Template geladen werden kann)."""

    def __init__(self, config: Dict[str, Any], verb: str):
        self._verb = verb
        self.SKILL_ID = _VERB_TO_ID[verb]
        self.SKILL_META = self.SKILL_ID
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta(self.SKILL_META) or {}
        self.name = meta.get("name") or self.__class__.__name__
        self.description = meta.get("description") or ""
        self._defaults = {"enabled": True}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} ist deaktiviert."
        ctx = self._parse_base_input(raw_input)
        char = (ctx.get("agent_name") or "").strip()
        if not char:
            return "Fehler: character_name fehlt."
        try:
            if self._verb == "invite":
                return self._invite(char, ctx)
            if self._verb == "join":
                return self._join(char, ctx)
            return self._leave(char, ctx)
        except Exception as e:
            logger.exception("%s [%s] fehlgeschlagen: %s", self.name, char, e)
            return f"Fehler in {self.name}: {e}"

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, func=self.execute)

    # --- Verben ----------------------------------------------------------

    def _invite(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        target = _resolve_target(ctx)
        if not target or target == character_name:
            return "Wen genau einladen? (kein gueltiges Ziel)"
        if P.is_party_follower(character_name):
            return f"{character_name} ist selbst Teil einer Party und kann niemanden einladen."
        if P.get_party_of(target) is not None:
            return f"{target} ist bereits in einer Party."
        try:
            from app.models.account import is_player_controlled
            _is_avatar = is_player_controlled(target)
        except Exception:
            _is_avatar = False
        if _is_avatar:
            P.create_pending_invite(character_name, target)
            return (f"{character_name} hat {target} in die Party eingeladen "
                    f"— wartet auf dessen Antwort.")
        accepted, _reply = P.ask_to_join_party(character_name, target)
        if accepted:
            return f"{target} schliesst sich {character_name}s Party an."
        return f"{target} lehnt die Einladung ab."

    def _join(self, character_name: str, ctx: Dict[str, Any]) -> str:
        from app.core import party_engine as P
        leader = _resolve_target(ctx)
        if not leader or leader == character_name:
            return "Wessen Party beitreten? (kein gueltiges Ziel)"
        if P.is_in_party(character_name):
            return f"{character_name} ist bereits in einer Party."
        pid = P.add_to_party(leader, character_name)
        if not pid:
            return (f"{character_name} kann {leader}s Party nicht beitreten "
                    f"(bereits in einer Party / ungueltig).")
        try:
            P.clear_invites_for(character_name)
        except Exception:
            pass
        # Beitritt im Raum sichtbar machen (Erzaehler-Zeile); die eigene RP-Antwort
        # des Characters laeuft separat ueber den Antwort-Turn.
        try:
            from app.models.character import (get_character_current_location,
                                              get_character_current_room)
            from app.core.perception import record_utterance, VOLUME_NORMAL
            _loc = get_character_current_location(character_name) or ""
            _room = get_character_current_room(character_name) or ""
            record_utterance(speaker="Erzähler",
                             content=f"{character_name} schließt sich {leader}s Party an.",
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="party")
        except Exception as _re:
            logger.debug("join_party record fehlgeschlagen: %s", _re)
        return f"{character_name} schliesst sich {leader}s Party an."

    def _leave(self, character_name: str, ctx: Dict[str, Any]) -> str:
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
