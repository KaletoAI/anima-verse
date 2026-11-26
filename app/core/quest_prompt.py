"""Per-turn quest prompt block for quest givers and hint holders (D15).

Builds at most ``MAX_LINES`` short English lines for a character:
- one per live quest run (``hidden`` or ``open``) in which the character is
  bound to the template's ``giver_role``;
- one per ``live`` quest hint secret owned by the character's mind in an
  ``open`` run (never a ``hidden`` run, so hidden runs never leak secret ids).

Cache rule: quest state and current steps change between turns, so this block
belongs ONLY in per-turn prompts — the chat scene state (``chat/chat_moment.md``),
the per-turn tool decision (``chat/tool_step_turn.md``),
thought prompts (``chat/agent_thought.md``, ``chat/agent_thought_in_chat.md``),
and NPC action prompts (``tasks/npc_action.md`` via ``npc_actions._with_action_context``).
It must NEVER enter the stable chat system prompt (``chat/chat_stream.md`` / ``reply_base.md``).
"""
from app.core.log import get_logger

logger = get_logger(__name__)

MAX_LINES = 3


def lines_for(character_name: str) -> list[str]:
    """Return up to ``MAX_LINES`` quest giver and hint lines for ``character_name``.

    Takes no locks and never raises. Uses ``quest_engine.has_live_runs()`` as
    a cheap early-out before reading any runs or secrets.
    """
    if not character_name or not isinstance(character_name, str):
        return []
    try:
        from app.core import quest_engine
        if not quest_engine.has_live_runs():
            return []

        from app.core.linked_characters import mind_of
        from app.models import quests, secrets

        runs = quests.list_runs(states=quest_engine.LIVE_STATES)
        lines: list[str] = []

        # Giver lines first (hidden and open runs)
        for run in runs:
            snap = run.get("template_snapshot") or {}
            giver = snap.get("giver_role") or ""
            if not giver:
                continue
            b = (run.get("bindings") or {}).get(giver)
            if not (isinstance(b, dict) and b.get("name") == character_name):
                continue
            summary = (
                quest_engine.render_text(snap.get("summary") or "", run).strip()
                or quest_engine.render_text(snap.get("title") or "", run).strip()
            )
            if not summary:
                continue
            state = run.get("state")
            if state == "open":
                steps = snap.get("steps")
                i = run.get("current_step")
                step_text = ""
                if (isinstance(steps, list) and isinstance(i, int)
                        and not isinstance(i, bool) and 0 <= i < len(steps)
                        and isinstance(steps[i], dict)):
                    step_text = quest_engine.render_text(
                        steps[i].get("text") or "", run).strip()
                if step_text:
                    lines.append(f"You want an adventurer to: {summary} \u2014 next: {step_text}")
                else:
                    lines.append(f"You want an adventurer to: {summary}")
            else:
                # Hidden run: summary wish only, never step text or hint ids.
                lines.append(f"You want an adventurer to: {summary}")
            if len(lines) >= MAX_LINES:
                return lines[:MAX_LINES]

        # Hint lines after all giver lines (open runs only)
        mind = mind_of(character_name)
        for run in runs:
            if run.get("state") != "open":
                continue
            for obj in quests.list_objects(run["id"], statuses=("live",)):
                if obj.get("kind") != "secret":
                    continue
                ref = obj.get("ref") or {}
                if not (isinstance(ref, dict) and ref.get("owner") == mind and ref.get("secret_id")):
                    continue
                sec = secrets.get_secret(mind, ref["secret_id"])
                if sec is None:
                    continue
                content = quest_engine.render_text(sec.get("content") or "", run).strip()
                if not content:
                    continue
                lines.append(
                    f"You know something you may tell an adventurer who asks "
                    f"[secret {ref['secret_id']}]: {content}"
                )
                if len(lines) >= MAX_LINES:
                    return lines[:MAX_LINES]

        return lines[:MAX_LINES]
    except Exception as e:  # noqa: BLE001
        logger.debug("quest prompt lines failed for %s: %s", character_name, e)
        return []


def block_for(character_name: str) -> str:
    """Bullet-formatted quest block for ``character_name``, or ``""`` when none."""
    lines = lines_for(character_name)
    if not lines:
        return ""
    return "\n".join("- " + line for line in lines)
