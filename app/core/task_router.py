"""Task Router — resolves informational queue labels for background tasks.

With the unified channel system, actual task routing happens via
ProviderManager.find_channel(). This module only provides informational
queue_name labels for UI display and task tracking.
"""
from typing import Optional

from app.core.log import get_logger

logger = get_logger("task_router")


def resolve_queue(
    task_type: str,
    payload: dict = None,
    agent_name: str = "") -> str:
    """Returns an informational queue label for a background task.

    This does NOT affect routing — channels handle that dynamically.
    The label is stored in TaskQueue DB for UI display.
    """
    return "background"


def match_queue_name(name: str) -> Optional[str]:
    """Resolve a provider/backend name to a channel key.

    Channel keys are the provider name (LLM providers) or
    ``backend:<name>`` (image backends).
    """
    if not name:
        return None
    try:
        from app.core.provider_manager import get_provider_manager
        pm = get_provider_manager()
        # Exact channel match (provider name or full "backend:<name>" key)
        if name in pm.channels:
            return name
        # Image-backend name → "backend:<name>"
        backend_key = f"backend:{name}"
        if backend_key in pm.channels:
            return backend_key
    except Exception:
        pass
    return None


def invalidate_cache() -> None:
    """No-op — kept for backward compatibility."""
    pass
