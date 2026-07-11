"""Intent Engine — extracts character action commitments from chat responses and executes them.

Character emits: [INTENT: type | delay=0 | key=value]
Supported types (F6, declaration-based): the core types remind/execute_tool
plus every INTENT_TYPES declaration of the loaded skills — a skill/package
brings its intents along (class attributes or plugin.yaml ``intents``) and
executes them via handle_intent(); nothing is registered here by name.
Delay formats: 0/now/sofort, 30m, 2h, 1d, HH:MM
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.timeutils import utc_now
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("intent_engine")


# ---------------------------------------------------------------------------
# Intent dataclass
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    type: str
    delay_seconds: int = 0
    params: Dict[str, str] = field(default_factory=dict)
    raw: str = ""


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r'\[INTENT:\s*([^\]]+)\]', re.IGNORECASE)


def parse_intent_tags(text: str) -> List[Intent]:
    """Parse [INTENT: type | delay=... | key=value] tags from text."""
    intents = []
    for match in _TAG_RE.finditer(text):
        parts = [p.strip() for p in match.group(1).split('|')]
        if not parts or not parts[0].strip():
            continue
        intent_type = parts[0].strip()
        params: Dict[str, str] = {}
        for part in parts[1:]:
            if '=' in part:
                k, v = part.split('=', 1)
                params[k.strip()] = v.strip()
        delay_seconds = _parse_delay(params.pop('delay', '0'))
        intents.append(Intent(type=intent_type, delay_seconds=delay_seconds,
                               params=params, raw=match.group(0)))
    return intents


def strip_intent_tags(text: str) -> str:
    """Remove [INTENT: ...] tags from text before storing in history."""
    return _TAG_RE.sub('', text).strip()


def _parse_delay(delay_str: str) -> int:
    """Convert delay string to seconds.
    Supported: 0/now/sofort, 30m, 2h, 1d, HH:MM (today or tomorrow).
    """
    s = delay_str.strip().lower()
    if not s or s in ('0', 'now', 'sofort', 'immediately', 'jetzt'):
        return 0
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|d|day)', s)
    if m:
        v, unit = float(m.group(1)), m.group(2)
        factor = {'s': 1, 'sec': 1, 'm': 60, 'min': 60,
                  'h': 3600, 'hr': 3600, 'd': 86400, 'day': 86400}[unit]
        return int(v * factor)
    tm = re.fullmatch(r'(\d{1,2}):(\d{2})', s)
    if tm:
        now = utc_now()
        target = now.replace(hour=int(tm.group(1)), minute=int(tm.group(2)),
                              second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())
    logger.warning("Unbekanntes delay-Format: %s", delay_str)
    return 0


# ---------------------------------------------------------------------------
# Execution routing
# ---------------------------------------------------------------------------

# Core-owned intent types — no skill involved (memory / generic stub).
# Everything else comes from the loaded skills' INTENT_TYPES declarations
# (F6, plan-skill-plugin-architecture.md): no skill intent is named here.
_CORE_TYPES = {"remind", "execute_tool"}

# Lowercase identifier, 3-40 chars. Rejects template placeholders the LLM
# echoes verbatim from the system prompt (e.g. "<type>", "...", "key=value")
# which otherwise leak into the commitment-memory as ghost plans.
_PLAUSIBLE_INTENT_TYPE_RE = re.compile(r'^[a-z][a-z0-9_]{2,39}$')


def _is_plausible_intent_type(t: str) -> bool:
    return bool(t) and bool(_PLAUSIBLE_INTENT_TYPE_RE.match(t))


def _skill_for_intent(intent_type: str):
    """The loaded skill declaring this intent type (or None)."""
    try:
        from app.core.dependencies import get_skill_manager
        for skill in get_skill_manager().skills:
            if intent_type in getattr(skill, "INTENT_TYPES", ()):
                return skill
    except Exception as e:
        logger.debug("intent skill lookup failed for %s: %s", intent_type, e)
    return None


def _known_types() -> set:
    """Core types plus every INTENT_TYPES declaration of the loaded skills."""
    types = set(_CORE_TYPES)
    try:
        from app.core.dependencies import get_skill_manager
        for skill in get_skill_manager().skills:
            types.update(getattr(skill, "INTENT_TYPES", ()))
    except Exception:
        pass
    return types


def _normalize_text(s: str) -> str:
    """Collapse whitespace + lowercase for fuzzy comparison."""
    if not s:
        return ""
    return " ".join(s.split()).lower()


def _intent_payload(intent: "Intent") -> str:
    """Comparable content blob from an INTENT marker — the declaring
    skill's INTENT_PAYLOAD_KEYS decide which params carry it."""
    skill = _skill_for_intent(intent.type)
    if skill is None:
        return ""
    p = intent.params or {}
    for key in getattr(skill, "INTENT_PAYLOAD_KEYS", ()):
        if p.get(key):
            return _normalize_text(p[key])
    return ""


def _is_intent_redundant(intent: "Intent",
                          executed_tools: Optional[List]) -> bool:
    """True when an INTENT marker matches a tool already executed in the
    same turn (same skill, same/overlapping content blob). RP-finetunes
    often emit BOTH a real <tool> call AND a [INTENT: ...] marker for the
    same action — running both duplicates the action.

    ``executed_tools``: list of ``(tool_name, raw_input)`` tuples captured
    by the tool executor during the streaming phase. The content extraction
    on both sides is declared by the skill (INTENT_PAYLOAD_KEYS /
    tool_intent_payload) — no tool name lives here.

    Comparison: normalized text equality, OR one contains the other (≥30
    chars). Different content → both run; identical or near-identical →
    INTENT skipped.
    """
    if not executed_tools:
        return False
    skill = _skill_for_intent(intent.type)
    if skill is None:
        return False
    intent_text = _intent_payload(intent)
    if not intent_text:
        return False
    for (tname, raw) in executed_tools:
        if (tname or "").lower() != (skill.name or "").lower():
            continue
        try:
            tool_text = _normalize_text(skill.tool_intent_payload(raw))
        except Exception:
            continue
        if not tool_text:
            continue
        if tool_text == intent_text:
            return True
        # Allow small variation — one is contained in the other
        shorter, longer = (tool_text, intent_text) if len(tool_text) <= len(intent_text) else (intent_text, tool_text)
        if len(shorter) >= 30 and shorter in longer:
            return True
    return False


def execute_intent(intent: Intent, character_name: str,
                   scheduler_manager: Any = None) -> None:
    """Route intent to TaskQueue (immediate) or Scheduler DateTrigger (deferred)."""
    if intent.delay_seconds == 0:
        _submit_to_task_queue(intent, character_name)
    elif scheduler_manager:
        _schedule_intent(intent, character_name, scheduler_manager)
    else:
        logger.warning("Kein SchedulerManager für deferred intent %s — sofortige Ausführung",
                       intent.type)
        _submit_to_task_queue(intent, character_name)


def _submit_to_task_queue(intent: Intent, character_name: str) -> None:
    try:
        from app.core.task_queue import get_task_queue
        payload = {"user_id": "", "agent_name": character_name,
                   "intent_type": intent.type, **intent.params}
        # One generic dispatch task type (F6): the handler routes to the
        # declaring skill at execution time — new packages need no queue
        # re-registration.
        task_id = get_task_queue().submit(
            task_type="intent_dispatch",
            payload=payload,
            queue_name="default",
            agent_name=character_name)
        logger.info("Intent → TaskQueue: %s (task=%s)", intent.type, task_id)
    except Exception as e:
        logger.error("Intent TaskQueue submit: %s", e)


def _schedule_intent(intent: Intent, character_name: str,
                     scheduler_manager: Any) -> None:
    try:
        # delay_seconds is an in-world delay — run_date must be a GAME-time
        # stamp (character scheduler jobs dispatch on the game clock).
        from app.core.timeutils import game_now
        run_at = (game_now() + timedelta(seconds=intent.delay_seconds)).isoformat()
        job_id = f"intent_{character_name}_{int(utc_now().timestamp())}_{intent.type}"

        if intent.type == "send_message":
            action = {
                "type": "send_message",
                "message": intent.params.get("message", ""),
                "character": character_name,
            }
        else:
            action = {
                "type": "execute_tool",
                "tool": intent.type,
                "params": {"user_id": "", "agent_name": character_name, **intent.params},
            }

        result = scheduler_manager.add_job(
            agent=character_name,
            trigger={"type": "date", "run_date": run_at, "one_time": True},
            action=action, job_id=job_id)
        delay_h = intent.delay_seconds / 3600
        logger.info("Intent → Scheduler: %s in %.1fh (job=%s)", intent.type, delay_h,
                    result.get("job_id"))
    except Exception as e:
        logger.error("Intent Scheduler submit: %s", e)


def _save_commitment(intent: Intent, character_name: str) -> None:
    """Fallback: store intent as memory so character remembers it."""
    try:
        from app.models.memory import add_memory
        content = f"Planned action: {intent.type}"
        if intent.params:
            content += f" — {json.dumps(intent.params, ensure_ascii=False)}"
        if intent.delay_seconds:
            h = intent.delay_seconds / 3600
            content += f" (in {h:.1f}h)"
        # importance=3 (kein Cleanup-Schutz): das ist ein automatisch erzeugter
        # Plan, kein vom User markierter wichtiger Commitment. source=intent
        # markiert die Provenance fuer spaeteren Event-Cleanup.
        add_memory(
            character_name=character_name,
            content=content, memory_type="commitment", importance=3,
            tags=["intent"],
            extra_meta={"source": "intent"})
        logger.info("Commitment → Memory: %s", intent.type)
    except Exception as e:
        logger.warning("Commitment Memory save: %s", e)


# ---------------------------------------------------------------------------
# TaskQueue handler registration + handlers
# ---------------------------------------------------------------------------

def register_intent_handlers() -> None:
    """Register TaskQueue handlers. Call at server startup.

    One generic dispatcher (F6): skill intents route to the declaring
    skill's handle_intent at execution time; only the core-owned types
    (remind, execute_tool) have their own handlers here.
    """
    from app.core.task_queue import get_task_queue
    tq = get_task_queue()
    tq.register_handler("intent_dispatch", _dispatch_intent)
    tq.register_handler("intent_remind", _handle_remind)
    tq.register_handler("intent_execute_tool", _handle_execute_tool)
    logger.info("Intent-Handler registriert (generischer Dispatcher)")


def _dispatch_intent(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generic TaskQueue handler: route to the core handler or the skill
    that declares the intent type. Knows no intent/skill name."""
    intent_type = (payload.get("intent_type") or "").strip()
    if not intent_type:
        return {"success": False, "error": "missing intent_type"}
    if intent_type == "remind":
        return _handle_remind(payload)
    if intent_type == "execute_tool":
        return _handle_execute_tool(payload)
    skill = _skill_for_intent(intent_type)
    if skill is None:
        return {"success": False,
                "error": f"no loaded skill declares intent '{intent_type}'"}
    try:
        return skill.handle_intent(intent_type, payload)
    except Exception as e:
        logger.error("Intent %s failed in %s: %s", intent_type, skill.name, e,
                     exc_info=True)
        return {"success": False, "error": str(e)}


def _handle_remind(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Store reminder in character memory."""
    user_id = payload.get("user_id", "")
    character_name = payload.get("agent_name", "")
    note = (payload.get("note") or payload.get("message") or "").strip()
    if not note:
        logger.warning("Intent remind ohne note/message — kein Memory erzeugt (agent=%s)",
                       character_name)
        return {"success": False, "error": "missing_note"}
    try:
        from app.models.memory import add_memory
        add_memory(
            character_name=character_name,
            content=f"Reminder: {note}", memory_type="commitment", importance=4,
            tags=["reminder"],
            extra_meta={"source": "intent"})
        return {"success": True, "note": note}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _handle_execute_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a named skill. Extend mapping as needed."""
    tool = payload.get("tool", "")
    logger.info("Intent execute_tool: %s (payload=%s)", tool, list(payload.keys()))
    return {"success": True, "tool": tool, "note": "Tool mapping pending"}


# ---------------------------------------------------------------------------
# Main entry point — called from chat.py post-stream
# ---------------------------------------------------------------------------

def process_response_intents(
    response: str, character_name: str,
    agent_config: Dict[str, Any],
    scheduler_manager: Any = None,
    executed_tools: Optional[List] = None) -> List[Intent]:
    """Sync entry: extract tag-based intents and execute/schedule them.

    ``executed_tools``: optional list of ``(tool_name, raw_input)`` tuples
    captured during the same streaming turn. INTENT markers whose action
    matches a tool already run with the same payload are skipped to avoid
    double-execution (e.g. duplicate Instagram posts when the LLM emits
    both ``<tool name="Instagram">`` and ``[INTENT: instagram_post]``).
    """
    intents = parse_intent_tags(response)
    for intent in intents:
        if _is_intent_redundant(intent, executed_tools):
            logger.info("INTENT skipped (redundant with executed tool): %s",
                        intent.type)
            continue
        if intent.type in _known_types():
            execute_intent(intent, character_name, scheduler_manager)
        elif _is_plausible_intent_type(intent.type):
            _save_commitment(intent, character_name)
        else:
            logger.info("INTENT discarded (implausible type): %r", intent.type)
    return intents


async def process_response_intents_async(
    response: str, character_name: str,
    agent_config: Dict[str, Any],
    scheduler_manager: Any = None,
    executed_tools: Optional[List] = None) -> List[Intent]:
    """Async entry: tag-based intent extraction.

    The LLM fallback has been removed — the tag-based [INTENT: ...] path
    stays for the user-facing streaming chat where the chat-LLM emits
    intent markers. See ``process_response_intents`` for the
    ``executed_tools`` skip semantics.
    """
    intents = parse_intent_tags(response)
    for intent in intents:
        if _is_intent_redundant(intent, executed_tools):
            logger.info("INTENT skipped (redundant with executed tool): %s",
                        intent.type)
            continue
        if intent.type in _known_types():
            execute_intent(intent, character_name, scheduler_manager)
        elif _is_plausible_intent_type(intent.type):
            _save_commitment(intent, character_name)
        else:
            logger.info("INTENT discarded (implausible type): %r", intent.type)
    return intents
