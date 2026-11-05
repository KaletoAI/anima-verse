"""Transformation verbs — Transform / Revert / RevealIdentity.

One class, three verbs (``params: {verb: transform|revert|reveal_identity}``):

* ``transform`` — visible to a LEADER who carries the power item of one of
  its definitions; offered while not on cooldown. Input ``{}``, or
  ``{"into": "<body>"}`` when the leader can become several bodies.
* ``revert`` — the clearing verb of the ``is_transformed`` flag; visible only
  to a body that stands in the world for its leader right now.
* ``reveal_identity`` — ``{"target": "<name>"}``: makes one present person a
  knower of "<body> is secretly <leader>" (``knowers.add``) and tells the two
  of them in a private line. Usable by the present body, and by the leader
  for the bodies it can become (``{"as": "<body>"}`` picks one).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from app.core.game_time import GameTime
from app.core.linked_characters import leader_of
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
    "unknown_definition": "that transformation does not exist",
    "not_holding_item": "you do not carry the power item",
    "already_transformed": "you are already transformed",
    "cooldown": "the power to become {body} has not recovered yet",
    "body_not_linked": "{body} is not one of your linked characters",
}
_REVERT_REFUSALS = {
    "not_transformed": "you are not transformed",
    "not_holding_item": "you do not carry the power item — without it you cannot turn back",
}


def held_definitions(character: str) -> List[Definition]:
    """The definitions ``character`` leads whose power item it carries."""
    own = definitions.for_leader(character)
    if not own:
        return []
    carried = get_carried_item_ids(character)
    return [d for d in own if d.item_id in carried]


def on_cooldown(character: str, d: Definition) -> bool:
    stamp = store.cooldown_until(character, d.id)
    if not stamp:
        return False
    try:
        return game_time() < GameTime.parse(stamp)
    except ValueError:
        return False


def present_body_row(character: str):
    """The active row that put ``character`` into the world, or ``None``."""
    row = store.active_of_body(character)
    return row if row is not None and leader_of(character) == row.leader else None


def _pick(options: List[Definition], token: str) -> Union[Definition, str]:
    """The definition ``token`` names among ``options`` (casefold body name or
    id); the only option without a token; else a refusal reason."""
    token = (token or "").strip()
    if token:
        folded = token.casefold()
        for d in options:
            if d.body.casefold() == folded or d.id.casefold() == folded:
                return d
        return f"you cannot become {token}"
    bodies = list(dict.fromkeys(d.body for d in options))
    if len(bodies) == 1:
        return options[0]
    return "name who to become: " + ", ".join(bodies)


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
        """On without a character setting: whoever leads a definition and
        carries its item can use it (``visible_for`` gates the rest); an
        explicit per-character setting still wins."""
        return True

    def visible_for(self, character_name: str) -> bool:
        if self._verb == "revert":
            return present_body_row(character_name) is not None
        if self._verb == "reveal_identity":
            return bool(self._reveal_options(character_name))
        return bool(held_definitions(character_name))

    def available_now(self, facts: TurnFacts) -> Optional[str]:
        c = facts.character
        if self._verb == "transform":
            if store.get_active(c) is not None:
                return "already transformed"
            held = held_definitions(c)
            if held and all(on_cooldown(c, d) for d in held):
                return "on cooldown"
            return None
        if self._verb == "reveal_identity":
            d = self._reveal_def(c, "")
            if isinstance(d, str):
                return None
            if not any(not knowers.knows(n, d.body) for n in facts.present if n != c):
                return "nobody present who is not in on the secret"
        return None

    def decision_menu(self, character_name: str) -> List[str]:
        if self._verb == "transform":
            bodies = list(dict.fromkeys(d.body for d in held_definitions(character_name)))
            return bodies if len(bodies) > 1 else []
        if self._verb == "reveal_identity":
            d = self._reveal_def(character_name, "")
            if isinstance(d, str):
                return []
            return sorted((n for n in addressable_for(character_name)
                           if not knowers.knows(n, d.body)), key=str.casefold)
        return []

    def tool_decision_context(self, character_name: str) -> str:
        if self._verb != "reveal_identity":
            return ""
        d = self._reveal_def(character_name, "")
        if isinstance(d, str):
            return ""
        present = addressable_for(character_name)
        inside = [n for n in present if knowers.knows(n, d.body)]
        outside = [n for n in present if not knowers.knows(n, d.body)]
        return render("transformation/decision_context.md", body=d.body, leader=d.leader,
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
                return self._transform(c, str(data.get("into") or ""))
            if self._verb == "revert":
                return self._revert(c)
            return self._reveal(c, str(data.get("target") or ""), str(data.get("as") or ""))
        except Exception as e:  # noqa: BLE001 — a failure is the tool's answer
            self.ctx.logger.exception("%s failed for %s: %s", self.name, c, e)
            return f"Error in {self.name}: {e}"

    def _transform(self, c: str, into: str) -> str:
        held = held_definitions(c)
        if not held:
            return ToolRefusal("you carry no power item to transform with")
        d = _pick(held, into)
        if isinstance(d, str):
            return ToolRefusal(d)
        result = engine.transform(c, d.id, source="verb")
        if result.get("ok"):
            return f"{c} transforms into {d.body}."
        reason = str(result.get("reason") or "")
        if reason in ("refused", "failed"):
            return ToolRefusal(f"you cannot transform right now: {result.get('error') or reason}")
        text = _TRANSFORM_REFUSALS.get(reason, "the transformation failed")
        return ToolRefusal(text.format(body=d.body))

    def _revert(self, c: str) -> str:
        row = present_body_row(c)
        if row is None:
            return ToolRefusal(f"{c} is not transformed")
        result = engine.revert(row.leader, reason="verb")
        if result.get("ok"):
            return f"{c} turns back into {row.leader}."
        reason = str(result.get("reason") or "")
        if reason in ("refused", "failed"):
            return ToolRefusal(f"you cannot turn back right now: {result.get('error') or reason}")
        return ToolRefusal(_REVERT_REFUSALS.get(reason, "turning back failed"))

    @staticmethod
    def _reveal_options(c: str) -> List[Definition]:
        """What ``c`` could reveal: as the present body its own definitions
        (the running one first); as a leader those whose item it carries."""
        row = present_body_row(c)
        if row is not None:
            own = definitions.for_body(c)
            return sorted(own, key=lambda d: d.id != row.def_id)
        return held_definitions(c)

    def _reveal_def(self, c: str, token: str) -> Union[Definition, str]:
        options = self._reveal_options(c)
        if not options:
            return "you have no secret identity to reveal"
        return _pick(options, token)

    @staticmethod
    def _present_target(token: str, present: List[str]) -> Optional[str]:
        """The present character ``token`` names (casefolded, stripped), or None."""
        folded = (token or "").strip().casefold()
        return next((n for n in present if n.casefold() == folded), None) if folded else None

    def _reveal(self, c: str, token: str, as_body: str) -> str:
        if not token.strip():
            return ToolRefusal('name the person to tell: {"target": "<exact name>"}')
        d = self._reveal_def(c, as_body)
        if isinstance(d, str):
            return ToolRefusal(d)
        target = self._present_target(token, addressable_for(c))
        if target is None or target == c:
            return ToolRefusal(f"{token.strip()} is not here — only someone present can be told")
        if knowers.knows(target, d.body):
            return ToolRefusal(f"{target} already knows that {d.body} is {d.leader}")
        if not knowers.add(target, d.body):
            return ToolRefusal(f"the secret of {d.body} could not be shared")
        content = render("transformation/reveal.md", revealer=c, target=target,
                         body=d.body, leader=d.leader)
        record_private_line(recipients=[c, target], content=content,
                            location_id=get_character_current_location(c) or "",
                            room_id=get_character_current_room(c) or "",
                            source="transformation:reveal",
                            perception_meta={"transformation": "reveal", "def_id": d.id})
        self.ctx.logger.info("%s reveals to %s that %s is %s", c, target, d.body, d.leader)
        return f"{c} reveals to {target} that {d.body} is {d.leader}."
