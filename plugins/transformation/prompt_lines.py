"""Scene-state identity lines — who is who, as one character knows it.

``blocks_for(character)`` gives the lines for one character's prompt:

* the character is transformed: which persona it wears, who knows, and who
  present does not;
* the character knows a present, transformed bearer: the alias here is that
  bearer, and who present does not know;
* the character knows a bearer otherwise (absent, or not transformed): the
  plain mapping ``<alias> = <name>``, so alias-named summaries and memories
  read right.

A non-knower gets nothing. The lines are volatile (they change with every
transform, reveal and room change), so they go to the scene state only:
``character.prompt_context`` (chat moment, NPC action, NPC scene) and
``character.thought_context`` (one section of the thought turn) — never the
system prompt. The text lives in ``templates/llm/transformation/``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.identity_view import shown_name
from app.core.log import get_logger
from app.core.perception import addressable_for
from app.core.prompt_templates import render
from app.models.character import list_available_characters
from app.models.inventory import get_carried_item_ids

from plugins.transformation import definitions, knowers, store
from plugins.transformation.definitions import Definition

logger = get_logger("transformation")


def _sorted(names: List[str]) -> List[str]:
    return sorted(dict.fromkeys(names), key=lambda n: n.casefold())


def bearers() -> List[Tuple[str, Definition, bool]]:
    """``(bearer, persona, transformed)`` for every current bearer, sorted.

    A bearer is whoever wears a persona right now (its worn persona) or
    carries a persona's power item (that persona). Empty without personas.
    """
    defs = definitions.load()
    if not defs:
        return []
    out: Dict[Tuple[str, str], Tuple[str, Definition, bool]] = {}
    for row in store.all_active():
        d = defs.get(row.persona_id)
        if d is not None:
            out[(row.bearer, d.id)] = (row.bearer, d, True)
    by_item: Dict[str, Definition] = {}
    for d in defs.values():
        by_item.setdefault(d.item_id, d)
    for name in list_available_characters():
        for iid in get_carried_item_ids(name) & by_item.keys():
            d = by_item[iid]
            out.setdefault((name, d.id), (name, d, False))
    return [out[k] for k in sorted(out, key=lambda k: (k[0].casefold(), k[1]))]


def _line(kind: str, *, alias: str, name: str, knower_list: List[str] = (),
          non_knowers: List[str] = ()) -> str:
    return render("transformation/scene_line.md", kind=kind, alias=alias, name=name,
                  knowers=list(knower_list), non_knowers=list(non_knowers))


def blocks_for(character: str) -> List[str]:
    """The identity lines for ``character``'s prompt; ``[]`` when there are none."""
    if not character:
        return []
    found = bearers()
    if not found:
        return []
    present: List[str] = []
    present_loaded = False
    lines: List[str] = []
    for bearer, d, transformed in found:
        is_self = bearer.casefold() == character.casefold()
        if not is_self and not knowers.knows(character, bearer, d.id):
            continue
        if transformed and not present_loaded:
            present, present_loaded = addressable_for(character), True
        if is_self and transformed:
            non = [shown_name(character, n) for n in present
                   if not knowers.knows(n, bearer, d.id)]
            lines.append(_line("bearer", alias=d.alias, name=bearer,
                               knower_list=_sorted([shown_name(character, k) for k in
                                                    knowers.knower_names(bearer, d.id)]),
                               non_knowers=_sorted(non)))
        elif transformed and bearer in present:
            non = [shown_name(character, n) for n in present
                   if n != bearer and not knowers.knows(n, bearer, d.id)]
            lines.append(_line("knower_present", alias=d.alias, name=bearer,
                               non_knowers=_sorted(non)))
        else:
            lines.append(_line("mapping", alias=d.alias, name=bearer))
    return [line for line in lines if line]


def on_prompt_context(*, character_name: str = "", blocks: Any = None, **_: Any) -> None:
    """``character.prompt_context``: one block per identity line."""
    if blocks is None or not character_name:
        return
    blocks.extend(blocks_for(character_name))


def on_thought_context(*, character_name: str = "", blocks: Any = None, **_: Any) -> None:
    """``character.thought_context``: the identity lines as one section."""
    if blocks is None or not character_name:
        return
    lines = blocks_for(character_name)
    if lines:
        blocks.append(render("transformation/thought_block.md", lines=lines))
