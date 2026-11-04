"""Render the shared rp_first tool decision without caller-specific prompts."""
from dataclasses import dataclass
from typing import Literal

from app.core import prompt_templates
from app.core.tool_formats import get_format, get_format_for_model
from app.skills.base import TurnFacts


@dataclass
class ToolStepPrompt:
    system: str
    user: str
    offered: list[str]
    hidden: dict[str, str]


def build_tool_step_prompt(
    character: str, *, mode: Literal['thought', 'respond', 'act'],
    rp_response: str, user_input: str, tools: list, facts: TurnFacts,
    constrained: bool = False, tool_format: str, model_name: str = '',
) -> ToolStepPrompt:
    """Filter tools once; put all situation-dependent declarations in the turn."""
    from app.core.dependencies import get_skill_manager
    from app.core.identity_view import shown_name
    from app.core.streaming import (
        turn_tools, decision_menu_note, open_questions_note,
        tool_decision_guardrails, speech_turn_note, tool_step_presence_labels,
    )
    from app.models.intents import build_open_intents_brief
    from app.routes.chat import _marker_travel_refusal

    offered, hidden = turn_tools(tools, facts, rp_first=True)
    manager = get_skill_manager()
    names = [getattr(tool, 'name', tool) for tool in offered]
    declarations = []
    for tool, name in zip(offered, names):
        skill = tool if hasattr(tool, 'brief') else manager.get_skill_by_name(name)
        declarations.append({'name': name, 'brief': getattr(skill, 'brief', '')})
    tool_map = dict.fromkeys(names)
    # The place marker is the way to move for a character without a movement
    # verb; it needs the exact names, which no offered menu carries then.
    marker_allowed = _marker_travel_refusal(character) == ''
    known_places: list[str] = []
    if marker_allowed:
        from app.models.world import list_locations_for_character
        known_places = [loc['name'] for loc in list_locations_for_character(character) or []
                        if loc.get('name')]
    fmt = get_format_for_model(model_name) if tool_format == 'auto' else tool_format
    from app.models.character import get_character_language_instruction
    system = prompt_templates.render(
        'chat/tool_step_system.md', character=character, constrained=constrained,
        syntax_example=get_format(fmt)["example"],
        language_instruction=get_character_language_instruction(character),
    )
    user = prompt_templates.render(
        'chat/tool_step_turn.md', character=character, mode=mode,
        rp_response=rp_response, user_input=user_input,
        # Names as the character perceives them; facts keep the real names
        # for availability (turn_tools) and the label is mapped back when
        # the tool LLM answers with it.
        present=tool_step_presence_labels(character, facts.present),
        partner=shown_name(character, facts.partner) if facts.partner else facts.partner,
        tools=declarations,
        speech_note=speech_turn_note(tool_map, is_thought=mode != 'respond'),
        menu_note=decision_menu_note(character, tool_map, indent=''),
        questions_note=open_questions_note(character, tool_map, indent=''),
        guardrails=tool_decision_guardrails(tool_map, with_markers=False),
        marker_travel_allowed=marker_allowed,
        known_places=known_places,
        plans='' if constrained else build_open_intents_brief(character),
    )
    return ToolStepPrompt(system, user, names, hidden)
