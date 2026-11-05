"""Scene-state secrecy lines — who may learn that a body is its leader.

``blocks_for(character)`` gives the lines for one character's prompt:

* the character is a body standing in the world for its leader (an active
  transformation): "You are <body>, and secretly <leader>. Nobody may learn
  that you are <leader>, except <knowers>." plus who present does not know;
* the character knows a present, transformed body: "<body> here is secretly
  <leader>." plus who present does not know;
* the character is a leader standing in the world, one line per body of its
  usable definitions: "You are <leader>, and secretly also <body>. Nobody may
  learn that you are <body>, except <knowers>." plus who present does not know
  — the mind remembers being the body ("(as <body>)" memories), so it needs
  the same discretion when it is itself;
* the character knows a body whose present leader is not transformed:
  "<leader> here is secretly <body>." plus who present does not know.

A non-knower gets nothing; the mapping itself reaches knowers through their
known-about-others secrets. The lines are volatile (they change with every
transform, reveal and room change), so they go to the scene state only:
``character.prompt_context`` (chat moment, NPC action, NPC scene) and
``character.thought_context`` (one section of the thought turn) — never the
system prompt. The text lives in ``templates/llm/transformation/``.
"""
from __future__ import annotations

from typing import Any, List

from app.core.log import get_logger
from app.core.perception import addressable_for
from app.core.prompt_templates import render

from plugins.transformation import definitions, knowers, store

logger = get_logger("transformation")


def _sorted(names: List[str]) -> List[str]:
    return sorted(dict.fromkeys(names), key=lambda n: n.casefold())


def _line(kind: str, *, body: str, leader: str, knower_list: List[str] = (),
          non_knowers: List[str] = ()) -> str:
    return render("transformation/scene_line.md", kind=kind, body=body, leader=leader,
                  knowers=list(knower_list), non_knowers=list(non_knowers))


def blocks_for(character: str) -> List[str]:
    """The secrecy lines for ``character``'s prompt; ``[]`` when there are none."""
    if not character:
        return []
    rows = store.all_active()
    defs = definitions.load().values()
    if not rows and not defs:
        return []
    present = addressable_for(character)
    transformed = {row.leader for row in rows}
    lines: List[str] = []
    for row in sorted(rows, key=lambda r: r.body.casefold()):
        if row.body == character:
            non = [n for n in present if not knowers.knows(n, row.body)]
            lines.append(_line("body", body=row.body, leader=row.leader,
                               knower_list=_sorted(knowers.knower_names(row.body)),
                               non_knowers=_sorted(non)))
        elif row.body in present and knowers.knows(character, row.body):
            non = [n for n in present if n != row.body and not knowers.knows(n, row.body)]
            lines.append(_line("knower_present", body=row.body, leader=row.leader,
                               non_knowers=_sorted(non)))
    # A leader standing as itself (not transformed): one line per secret body.
    pairs = sorted({(d.leader, d.body) for d in defs if d.leader not in transformed},
                   key=lambda p: (p[1].casefold(), p[0].casefold()))
    for leader, body in pairs:
        if leader == character:
            non = [n for n in present if not knowers.knows(n, body)]
            lines.append(_line("leader", body=body, leader=leader,
                               knower_list=_sorted(knowers.knower_names(body)),
                               non_knowers=_sorted(non)))
        elif leader in present and knowers.knows(character, body):
            non = [n for n in present if n != leader and not knowers.knows(n, body)]
            lines.append(_line("knower_leader_present", body=body, leader=leader,
                               non_knowers=_sorted(non)))
    return [line for line in lines if line]


def on_prompt_context(*, character_name: str = "", blocks: Any = None, **_: Any) -> None:
    """``character.prompt_context``: one block per secrecy line."""
    if blocks is None or not character_name:
        return
    blocks.extend(blocks_for(character_name))


def on_thought_context(*, character_name: str = "", blocks: Any = None, **_: Any) -> None:
    """``character.thought_context``: the secrecy lines as one section."""
    if blocks is None or not character_name:
        return
    lines = blocks_for(character_name)
    if lines:
        blocks.append(render("transformation/thought_block.md", lines=lines))
