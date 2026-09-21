"""Task-disable state for the LLM router.

Replaces the old global llm_queue.pause() — instead of blocking every LLM
call, single tasks (or preset groups) can be disabled. The router treats a
disabled task as "no LLM available" (resolve_llm returns None, llm_call raises
RuntimeError). Callers already have fallbacks for that case.

Two levels:
- Persistent:    `llm_task_state.disabled_tasks` in config.json
- Runtime-only:  in-memory set, overrides the persistent one for the session
                 (e.g. the world-dev builder activates the "world_dev" preset
                 for the duration of the session without changing the config)
"""
from threading import RLock
from typing import List, Set

from app.core import config
from app.core.llm_tasks import TASK_TYPES
from app.core.log import get_logger

logger = get_logger("llm_task_state")


# Preset → list of disabled tasks. Every entry must be an id from
# llm_tasks.TASK_TYPES (set_runtime_disabled drops unknown ones silently).
PRESETS = {
    "background": [
        "random_event", "thought", "secret_generation",
        "consolidation", "relationship_summary",
        "outfit_generation",
    ],
    "world_dev": [
        # All background LLM activity that gets in the way in world-dev mode
        "random_event", "thought", "secret_generation",
        "consolidation", "relationship_summary",
        "instagram_caption", "image_prompt", "image_recognition",
        "outfit_generation",
    ],
    "chat_only": [
        # everything except chat_stream, extraction and npc_talk
    ],
}


def _chat_only_disabled() -> List[str]:
    # npc_talk: a temporary NPC's reply IS chat (npc_scene, the director, is not).
    keep = {"chat_stream", "extraction", "npc_talk"}
    return [t for t in TASK_TYPES.keys() if t not in keep]


PRESETS["chat_only"] = _chat_only_disabled()


_lock = RLock()
_runtime_disabled: Set[str] = set()  # not persistent — world-dev etc.


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled(task: str) -> bool:
    """True when the task is currently neither persistently nor runtime disabled."""
    with _lock:
        if task in _runtime_disabled:
            return False
    persisted = _persisted_disabled()
    return task not in persisted


def disabled_tasks() -> List[str]:
    """List of every currently disabled task (persistent + runtime, deduplicated)."""
    persisted = _persisted_disabled()
    with _lock:
        combined = set(persisted) | set(_runtime_disabled)
    return sorted(combined)


def set_runtime_disabled(tasks: List[str]) -> None:
    """Sets the runtime-disable list (overwrites the existing set).

    An empty list = every runtime disable lifted (the persistent ones stay).
    """
    with _lock:
        _runtime_disabled.clear()
        _runtime_disabled.update(t for t in tasks if t in TASK_TYPES)
    logger.info("Runtime-disabled: %s", sorted(_runtime_disabled))


def activate_preset_runtime(preset: str) -> List[str]:
    """Activates a preset as a runtime disable. Returns the task list."""
    tasks = PRESETS.get(preset, [])
    set_runtime_disabled(tasks)
    return tasks


def clear_runtime() -> None:
    """Lifts every runtime disable."""
    with _lock:
        _runtime_disabled.clear()
    logger.info("Runtime-Disables aufgehoben")


def runtime_disabled_tasks() -> List[str]:
    with _lock:
        return sorted(_runtime_disabled)


def get_presets() -> dict:
    return {k: list(v) for k, v in PRESETS.items()}


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _persisted_disabled() -> Set[str]:
    """Reads the persistently disabled tasks from the config."""
    val = config.get("llm_task_state.disabled_tasks", [])
    if isinstance(val, list):
        return {str(t) for t in val if t}
    return set()
