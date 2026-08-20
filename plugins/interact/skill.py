"""Interact package — the pair-interaction verb.

``InteractWith`` binds the acting character and a present partner to a PAIR
animation clip (``app/core/interaction_engine.py``): the action text is
resolved against the pose catalog like any pose, and only a catalog pose that
is marked ``solo: false`` AND whose ``animation`` is a complete pair clip
(``<kind>__a`` + ``<kind>__b``) qualifies. The partner name is matched exactly
(case-insensitive) — never by first name or substring.

The interaction itself ends on the game clock (travel ticker), or when either
participant walks away, is moved, or takes another pose.
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


class InteractSkill(PluginSkill):
    SKILL_ID = "interact"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        self._defaults = {"enabled": True}

    def visible_for(self, character_name: str) -> bool:
        """No pair clip in the library → the verb is not offered at all."""
        try:
            from app.core.interaction_engine import partner_poses
            return bool(partner_poses())
        except Exception:
            return False

    def as_tool(self, **kwargs) -> ToolSpec:
        try:
            from app.core.interaction_engine import partner_poses
            keys = ", ".join(sorted(k for k, _ in partner_poses()))
        except Exception:
            keys = ""
        extra = f" Known two-person actions: {keys}." if keys else ""
        return ToolSpec(name=self.name, description=f"{self.description}{extra}",
                        func=self.execute)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return f"{self.name} skill is disabled."
        data = self._parse_base_input(raw_input)
        actor = (data.get("agent_name") or "").strip()
        if not actor:
            return "Error: character_name missing."
        partner_raw = str(data.get("partner") or data.get("name")
                          or data.get("target") or "").strip()
        action = str(data.get("action") or data.get("pose") or "").strip()
        if not partner_raw or not action:
            return "Error: pass {\"partner\": \"<name>\", \"action\": \"<what you do together>\"}."
        try:
            from app.core.interaction_engine import (partner_poses,
                                                     start_interaction)
            from app.core.pose_catalog import resolve_to_catalog
            from app.models.character import list_available_characters
            available = list_available_characters()
            partner = next((n for n in available
                            if n.lower() == partner_raw.lower()), "")
            if not partner:
                return f"Character '{partner_raw}' not found. Available: {', '.join(available)}"
            known = dict(partner_poses())
            key, _how = resolve_to_catalog(action, "pose")
            if key not in known:
                return (f"'{action}' is not a two-person action. "
                        f"Known: {', '.join(sorted(known)) or 'none'}.")
            inter = start_interaction(actor, partner, key)
            return (f"{actor} and {partner}: {key} "
                    f"(for about {inter['duration_s']:.0f} seconds).")
        except ValueError as e:
            return f"Cannot: {e}"
        except Exception as e:
            self.ctx.logger.exception("%s [%s] failed: %s", self.name, actor, e)
            return f"Error in {self.name}: {e}"
