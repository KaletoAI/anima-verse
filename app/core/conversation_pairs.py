"""Who is talking with whom — DERIVED from the utterance log, never stored.

A conversation is not an object. That decision stands
(``development_instructions/done/plan-room-conversation-redesign.md``): there
is no conversation row, no session id, nothing to open or to close. What a
character needs to know is much smaller — "am I in the middle of something
with someone?" — and the utterance log already answers it.

So a PAIR is read out of the last lines of a room: the newest line in which a
character appears as speaker or as addressee names its partner. Newest wins;
a character that has since been addressed by someone else has moved on.

The window is GAME time (``chat.pair_window_game_minutes``, default 5), not
system time. A frozen world freezes the pairs with it — otherwise the world
would stand still while every pair quietly expired behind it.

The pure core is :func:`derive_partners`; :func:`partners_in_room` and
:func:`conversation_partner` are the DB wrappers around it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger

logger = get_logger("conversation_pairs")

#: Default length of the pair window in GAME minutes — how long a line keeps
#: two characters paired. Overridable per world via
#: ``chat.pair_window_game_minutes``.
WINDOW_DEFAULT_MINUTES = 5


def pair_window() -> GameDuration:
    """The configured pair window as a :class:`GameDuration` (game minutes)."""
    try:
        from app.core import config
        raw = config.get("chat.pair_window_game_minutes",
                         WINDOW_DEFAULT_MINUTES)
        minutes = float(raw)
    except Exception:
        minutes = float(WINDOW_DEFAULT_MINUTES)
    if minutes <= 0:
        minutes = float(WINDOW_DEFAULT_MINUTES)
    return GameDuration.of(minutes=minutes)


def _sorted_rows(rows: Sequence[Dict[str, Any]]
                 ) -> List[Tuple[GameTime, Dict[str, Any]]]:
    """Parse ``game_ts`` and order newest first.

    A row without a usable world stamp is dropped, not guessed at: it is an
    old row written before the column existed (no backfill, by design), and a
    guessed time would invent a pair that never happened.
    """
    parsed: List[Tuple[GameTime, Dict[str, Any]]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("game_ts")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            stamp = GameTime.parse(raw.strip())
        except ValueError:
            continue
        parsed.append((stamp, row))
    parsed.sort(key=lambda item: item[0].total_seconds, reverse=True)
    return parsed


def derive_partners(rows: Sequence[Dict[str, Any]], now: GameTime,
                    window: GameDuration,
                    storyteller: Optional[str] = None) -> Dict[str, str]:
    """Name → conversation partner, read off the room's utterances.

    ``rows`` are dicts with ``speaker``, ``addressees`` (a list) and
    ``game_ts`` (canonical string), in any order. Processing runs newest
    first, and the FIRST assignment a name gets wins — that is what "the
    newest line decides" means.

    Three kinds of line contribute nothing: a storyteller line (narration is
    not a conversation partner), a line without addressees (spoken to the
    room, so it pairs nobody), and a line older than the window. The exclusion
    test is ``now - stamp > window``: a line of exactly the window's age is
    still inside.

    Pure — no DB, no clock, no config.
    """
    if storyteller is None:
        from app.core.perception import STORYTELLER_SPEAKER
        storyteller = STORYTELLER_SPEAKER

    partners: Dict[str, str] = {}
    for stamp, row in _sorted_rows(rows):
        if now - stamp > window:
            continue
        speaker = str(row.get("speaker") or "").strip()
        if not speaker or speaker == storyteller:
            continue
        raw_addr = row.get("addressees")
        if not isinstance(raw_addr, (list, tuple)):
            continue
        addressees = [str(a).strip() for a in raw_addr if str(a or "").strip()]
        if not addressees:
            continue
        if speaker not in partners:
            partners[speaker] = addressees[0]
        for name in addressees:
            if name not in partners:
                partners[name] = speaker
    return partners


def partners_in_room(location_id: str, room_id: str) -> Dict[str, str]:
    """The pairs currently standing in one room — ``{}`` when nothing pairs.

    Never raises: this feeds the chime selection, and a broken read must cost
    a chime, not a turn.
    """
    try:
        from app.core.timeutils import game_time
        from app.models import perception_store
        rows = perception_store.recent_room_utterances(
            location_id, room_id, limit=40)
        return derive_partners(rows, game_time(), pair_window())
    except Exception as e:  # noqa: BLE001
        logger.debug("partners_in_room(%s/%s) failed: %s",
                     location_id, room_id, e)
        return {}


def conversation_partner(name: str, location_id: str,
                         room_id: str) -> Optional[str]:
    """Whom ``name`` is talking with in that room right now, or ``None``."""
    if not name:
        return None
    return partners_in_room(location_id, room_id).get(name)
