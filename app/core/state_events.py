"""Typed character-state event bus (AV3D-3).

ONE generic pub/sub for the state changes external map clients care about
— ``location_changed`` / ``room_changed`` / ``activity_changed`` — instead
of a third single-purpose module next to outfit_events.py. Published from
the central setters in app/models/character.py (plus the offmap/appear
bypasses that intentionally skip them); consumed by the SSE route
``GET /events/state-stream``. Party followers ride through the central
setters, so their moves publish for free.

Losing events while nobody subscribes is fine: polling /play/worldmap
stays every client's baseline — the stream only makes changes arrive
instantly instead of on the next poll.

Thread-safe: publishers may run on worker threads (skills, scheduler,
agent loop); subscribers are asyncio-based SSE handlers with their own
loop.
"""

import asyncio
import threading
from typing import Any, AsyncIterator, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("state_events")

# Global subscriber list (single-world model)
_subscribers: List[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
_lock = threading.Lock()


def publish(event_type: str, character: str, **fields: Any) -> None:
    """Broadcast one typed state event to all subscribers.

    Safe to call from threads or async code; never raises into the caller
    (a failed push must not break a movement save).
    """
    if not event_type or not character:
        return
    event = {"type": event_type, "character": character, **fields}
    with _lock:
        subs = list(_subscribers)
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, event)
        except RuntimeError:
            # Loop closed — the subscriber is dropped on its next iteration.
            pass
        except Exception as e:
            logger.debug("publish %s[%s]: %s", event_type, character, e)


async def subscribe() -> AsyncIterator[Dict[str, Any]]:
    """Async iterator over state events.

    Must be consumed on the SSE handler's event loop; registers itself and
    cleans up on exit.
    """
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    entry = (q, loop)
    with _lock:
        _subscribers.append(entry)
    try:
        while True:
            yield await q.get()
    finally:
        with _lock:
            if entry in _subscribers:
                _subscribers.remove(entry)
