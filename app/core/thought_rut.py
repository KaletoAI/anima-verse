"""Transient repetition heuristic for autonomous thoughts, forgotten on restart."""
from collections import deque
from threading import RLock
from typing import Iterable, Tuple

from app.core.log import get_logger

logger = get_logger("thought_rut")
RUT_TURNS = 3
_turns = {}
_lock = RLock()


def _repeating(turns) -> bool:
    return (len(turns) == RUT_TURNS
            and len({place for tools, place in turns}) == 1
            and len({tools for tools, place in turns}) == 1)


def record_turn(character: str, tool_names: Iterable[str],
                location_key: Tuple[str, str]) -> None:
    """Record a completed, non-SKIP turn at its final location and room."""
    with _lock:
        turns = _turns.setdefault(character, deque(maxlen=RUT_TURNS))
        was_rut = _repeating(turns)
        turns.append((frozenset(tool_names), location_key))
        if not was_rut and _repeating(turns):
            logger.info("Thought rut started: %s (%s)", character,
                        ", ".join(sorted(turns[-1][0])) or "narration only")


def rut_hint(character: str) -> str:
    """Return one user-turn hint, with tool names coming only from records."""
    with _lock:
        turns = _turns.get(character, ())
        if not _repeating(turns):
            return ""
        actions = ", ".join(sorted(turns[-1][0])) or "narration without tools"
    return (f"Your last {RUT_TURNS} turns were all: {actions} (here). "
            "Do something different now — go somewhere, contact someone, "
            "take a step of your task or a plan — or SKIP.")


def rut_here(character: str, location_key: Tuple[str, str]) -> bool:
    """A changed place releases the rest even before another turn runs."""
    with _lock:
        turns = _turns.get(character, ())
        return _repeating(turns) and turns[-1][1] == location_key
