"""Transformation verbs — Transform / Revert / RevealIdentity.

One class, three verbs (``params: {verb: transform|revert|reveal_identity}``):

* ``transform`` — visible to whoever carries a persona's power item; offered
  while not transformed and not on cooldown. Input ``{}``, or
  ``{"persona": "<alias>"}`` when the character carries several power items.
* ``revert`` — the clearing verb of the ``is_transformed`` flag; visible only
  while the character wears a persona.
* ``reveal_identity`` — ``{"target": "<name>"}``: makes one present person a
  knower (the bearer's knower secret, ``knowers.add``) and tells the two of
  them in a private line.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from app.core.game_time import GameTime
from app.core.perception import addressable_for, record_private_line
from app.core.prompt_templates import render
from app.core.timeutils import game_time
from app.models.character import get_character_current_location, get_character_current_room
from app.models.inventory import get_carried_item_ids
from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolRefusal, TurnFacts

from plugins.transformation import definitions, engine, knowers, store
from plugins.transformation.definitions import Definition

VERBS = ("transform", "revert", "reveal_identity")

_TRANSFORM_REFUSALS = {
    "unknown_persona": "that persona does not exist",
    "not_holding_item": "you do not carry the power item of {alias}",
    "already_transformed": "you are already transformed",
    "cooldown": "the power of {alias} has not recovered yet",
}


def held_personas(character: str) -> List[Definition]:
    """The personas whose power item ``character`` carries, in definition order."""
    defs = definitions.load()
    if not defs or not character:
        return []
    carried = get_carried_item_ids(character)
    return [d for d in defs.values() if d.item_id in carried]


def on_cooldown(character: str, d: Definition) -> bool:
    stamp = store.cooldown_until(character, d.id)
    if not stamp:
        return False
    try:
        return game_time() < GameTime.parse(stamp)
    except ValueError:
        return False


def _pick(options: List[Definition], token: str) -> Union[Definition, str]:
    """The persona ``token`` names among ``options`` (casefold alias or id);
    the only option without a token; else a refusal reason."""
    token = (token or "").strip()
    if token:
        folded = token.casefold()
        for d in options:
            if d.alias.casefold() == folded or d.id.casefold() == folded:
                return d
        return f"you have no persona called {token}"
    if len(options) == 1:
        return options[0]
    return "name the persona: " + ", ".join(d.alias for d in options)


class TransformationSkill(PluginSkill):
    """One implementation, three verbs — the LLM sees each as its own tool."""

    def __init__(self, config: Dict[str, Any], ctx: PluginContext, verb: str):
        super().__init__(config, ctx)
        if verb not in VERBS:
            raise ValueError(f"unknown transformation verb {verb!r}")
        self._verb = verb
        self.SKILL_ID = verb
        # name/description/brief come from templates/llm/skills/<skill_id>.md
        self._defaults = {"enabled": True}

    # ── visibility ──────────────────────────────────────────────────────────

    def default_enabled_for(self, character_name: str) -> bool:
        """On without a character setting: the power travels with the item,
        so whoever picks it up can use it (``visible_for`` gates the rest);
        an explicit per-character setting still wins."""
        return True

    def visible_for(self, character_name: str) -> bool:
        if self._verb == "revert":
            return store.get_active(character_name) is not None
        return bool(held_personas(character_name))

    def available_now(self, facts: TurnFacts) -> Optional[str]:
        c = facts.character
        if self._verb == "transform":
            if store.get_active(c) is not None:
                return "already transformed"
            held = held_personas(c)
            if held and all(on_cooldown(c, d) for d in held):
                return "on cooldown"
            return None
        if self._verb == "reveal_identity":
            d = self._reveal_persona(c, "")
            if isinstance(d, str):
                return None
            if not any(not knowers.knows(n, c, d.id) for n in facts.present if n != c):
                return "nobody present who is not in on the secret"
        return None

    def decision_menu(self, character_name: str) -> List[str]:
        if self._verb == "transform":
            held = held_personas(character_name)
            return [d.alias for d in held] if len(held) > 1 else []
        if self._verb == "reveal_identity":
            d = self._reveal_persona(character_name, "")
            if isinstance(d, str):
                return []
            return sorted((n for n in addressable_for(character_name)
                           if not knowers.knows(n, character_name, d.id)),
                          key=str.casefold)
        return []

    def tool_decision_context(self, character_name: str) -> str:
        if self._verb != "reveal_identity":
            return ""
        d = self._reveal_persona(character_name, "")
        if isinstance(d, str):
            return ""
        present = addressable_for(character_name)
        inside = [n for n in present if knowers.knows(n, character_name, d.id)]
        outside = [n for n in present if not knowers.knows(n, character_name, d.id)]
        return render("transformation/decision_context.md", alias=d.alias,
                      knowers_present=sorted(inside, key=str.casefold),
                      non_knowers_present=sorted(outside, key=str.casefold))

    # ── execution ───────────────────────────────────────────────────────────

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        c = str(data.get("agent_name") or "").strip()
        if not c:
            return "Error: character_name missing."
        try:
            if self._verb == "transform":
                return self._transform(c, str(data.get("persona") or ""))
            if self._verb == "revert":
                return self._revert(c)
            return self._reveal(c, str(data.get("target") or ""), str(data.get("persona") or ""))
        except Exception as e:  # noqa: BLE001 — a failure is the tool's answer
            self.ctx.logger.exception("%s failed for %s: %s", self.name, c, e)
            return f"Error in {self.name}: {e}"

    def _transform(self, c: str, persona: str) -> str:
        held = held_personas(c)
        if not held:
            return ToolRefusal("you carry no power item to transform with")
        d = _pick(held, persona)
        if isinstance(d, str):
            return ToolRefusal(d)
        result = engine.transform(c, d.id, source="verb")
        if result.get("ok"):
            return f"{c} transforms into {d.alias}."
        reason = _TRANSFORM_REFUSALS.get(str(result.get("reason")), "the transformation failed")
        return ToolRefusal(reason.format(alias=d.alias))

    def _revert(self, c: str) -> str:
        row = store.get_active(c)
        if row is None:
            return ToolRefusal(f"{c} is not transformed")
        d = definitions.load().get(row.persona_id)
        alias = str((row.snapshot or {}).get("alias") or (d.alias if d else ""))
        if not engine.revert(c, reason="verb"):
            return ToolRefusal(f"{c} is not transformed")
        return f"{c} turns back from {alias or 'the persona'}."

    def _reveal_persona(self, c: str, token: str) -> Union[Definition, str]:
        """The persona a reveal is about: the worn one while transformed
        (unless another is named), else one of the carried ones."""
        row = store.get_active(c)
        defs = definitions.load()
        worn = defs.get(row.persona_id) if row is not None else None
        options = held_personas(c)
        if worn is not None:
            if not (token or "").strip():
                return worn
            options = [worn] + [d for d in options if d.id != worn.id]
        if not options:
            return "you have no secret identity to reveal"
        return _pick(options, token)

    @staticmethod
    def _present_target(token: str, present: List[str]) -> Optional[str]:
        """The present character ``token`` names (casefolded, stripped), or None."""
        folded = (token or "").strip().casefold()
        return next((n for n in present if n.casefold() == folded), None) if folded else None

    def _reveal(self, c: str, token: str, persona: str) -> str:
        if not token.strip():
            return ToolRefusal('name the person to tell: {"target": "<exact name>"}')
        d = self._reveal_persona(c, persona)
        if isinstance(d, str):
            return ToolRefusal(d)
        target = self._present_target(token, addressable_for(c))
        if target is None or target == c:
            return ToolRefusal(f"{token.strip()} is not here — only someone present can be told")
        if knowers.knows(target, c, d.id):
            return ToolRefusal(f"{target} already knows that you are {d.alias}")
        if not knowers.add(target, c, d.id):
            return ToolRefusal(f"the secret of {d.alias} could not be shared")
        content = render("transformation/reveal.md", bearer=c, target=target, alias=d.alias)
        record_private_line(recipients=[c, target], content=content,
                            location_id=get_character_current_location(c) or "",
                            room_id=get_character_current_room(c) or "",
                            source="transformation:reveal",
                            perception_meta={"transformation": "reveal", "persona_id": d.id})
        self.ctx.logger.info("%s reveals persona %s to %s", c, d.id, target)
        return f"{c} reveals to {target} that {c} is {d.alias}."
