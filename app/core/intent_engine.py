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

from app.core.game_time import GameDuration
from app.core.timeutils import game_time, utc_now
from typing import Any, Dict

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


def strip_intent_tags(text: str) -> str:
    """Remove [INTENT: ...] tags from text before storing in history."""
    return _TAG_RE.sub('', text).strip()


# ---------------------------------------------------------------------------
# Execution routing
# ---------------------------------------------------------------------------

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
        # delay_seconds is an in-world delay — run_date must be a canonical
        # GAME-time stamp (character scheduler jobs dispatch on the game clock).
        run_at = (game_time()
                  + GameDuration.of(seconds=intent.delay_seconds)).canonical()
        # The job id only has to be unique — SYSTEM time is the right clock here.
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
