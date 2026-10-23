"""World-configured rewards and asynchronous event aftermath evaluation."""
import threading

from app.core.log import get_logger

logger = get_logger('stat_rewards')
_registered = False
_registration_lock = threading.Lock()


def apply_reward(name: str, occasion: str) -> dict:
    """Apply the world's fixed reward for an occasion, recording its source."""
    from app.core.stat_rules import get_setting
    from app.models.character import adjust_status_effects
    deltas = (get_setting('rewards') or {}).get(occasion) or {}
    return adjust_status_effects(name, deltas, source=occasion) if deltas else {}


def on_event_resolved(event: dict, resolved_by: str) -> None:
    """Evaluate the aftermath off the caller's thread for a known character."""
    from app.models.character import list_available_characters
    if not resolved_by or resolved_by not in list_available_characters():
        return
    situation = (f"{resolved_by} just resolved this situation: {event.get('text', '')}. "
                 "Judge the immediate aftermath.")

    def evaluate():
        try:
            from app.core.stat_effects import evaluate_stat_effects
            evaluate_stat_effects(resolved_by, situation, source='event_resolved')
        except Exception:
            logger.exception('Event aftermath evaluation failed for %s', resolved_by)

    threading.Thread(target=evaluate, daemon=True).start()


def _intent_changed(*, intent: dict, previous: dict) -> None:
    if intent.get('status') == 'done' and (previous or {}).get('status') != 'done':
        apply_reward(intent.get('owner', ''), 'intent_done')


def register_hooks() -> None:
    """Subscribe once during server startup, including repeated lifespans."""
    global _registered
    with _registration_lock:
        if _registered:
            return
        from app.core.hooks import register
        from app.core.random_events import on_character_entered_room
        register('intent_changed', _intent_changed)
        register('character.entered_room', on_character_entered_room)
        _registered = True
