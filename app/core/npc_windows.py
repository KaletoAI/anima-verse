"""Time windows in GAME time — when a slot is open and when it is shut.

spec-npc-heimat-zeitfenster § E2. A place may want a role only at certain
hours ("robbers in the forest at night"): the slot carries a ``when``, and
outside it nothing spawns and the NPCs already standing there go back into the
pool. Everything here is PURE — a :class:`GameTime` in, a bool out; no DB, no
config, no ``datetime``. The game clock is the caller's business.

Four forms, and nothing else::

    ""              always — the slot has no time condition at all
    "night"         outside the season's sunrise..sunset
    "day"           inside it
    "HH:MM-HH:MM"   a literal span, half-open, wrapping over midnight

THE NIGHT/DAY DECISION LIVES ONCE. :func:`is_night` is the single answer the
whole app asks — it forwards to :meth:`GameTime.is_night`, the calendar's own
definition (the season's sunrise/sunset, so a world with long winter nights
gets long winter nights for free). ``activity_engine``'s ``night``/``day``
rule condition used to carry its own copy of that comparison; it now asks
here, and only the ± minute OFFSET arithmetic of ``night-30`` stayed behind.
A second copy of the rule would be a world in which a rule and a slot disagree
about what "night" is.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from app.core.game_time import GameTime

#: Minutes in a day — the modulus every window value lives in.
DAY_MINUTES = 24 * 60

#: The two symbolic windows. Everything else is a literal span or "".
NIGHT = "night"
DAY = "day"

_SPAN_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def is_night(now: GameTime) -> bool:
    """True while the world is between sunset and sunrise.

    The season's sun, not a fixed hour: ``not (sunrise <= m < sunset)`` with
    ``m = now.minutes_of_day``. One decision, one place — see the module
    docstring.
    """
    return now.is_night()


def parse_window(when: Any) -> Optional[Tuple[int, int]]:
    """``"HH:MM-HH:MM"`` → ``(from_min, to_min)``; anything else → ``None``.

    ``None`` is the answer for every value that is not a literal span — an
    impossible hour ("25:00-01:00"), free text, and the symbolic ``night`` /
    ``day`` too (those are not spans; :func:`slot_window_open` answers them).
    """
    if not isinstance(when, str):
        return None
    m = _SPAN_RE.match(when.strip())
    if not m:
        return None
    from_h, from_m, to_h, to_m = (int(g) for g in m.groups())
    if not (0 <= from_h < 24 and 0 <= from_m < 60
            and 0 <= to_h < 24 and 0 <= to_m < 60):
        return None
    return from_h * 60 + from_m, to_h * 60 + to_m


def normalize_when(raw: Any) -> str:
    """The stored form of a slot window; "" for empty AND for unusable input.

    An authoring slip must not silently kill a slot forever, so anything this
    function cannot read becomes "always" — the caller (``normalize_slot``)
    says so in the log. A span is stored canonically (``"8:00-12:00"`` →
    ``"08:00-12:00"``) so the editor round trip has one shape.
    """
    text = str(raw or "").strip().lower()
    if text in ("", NIGHT, DAY):
        return text
    span = parse_window(text)
    if span is None:
        return ""
    start, end = span
    return (f"{start // 60:02d}:{start % 60:02d}"
            f"-{end // 60:02d}:{end % 60:02d}")


def slot_window_open(when: Any, now: GameTime) -> bool:
    """Is a slot with this ``when`` open at ``now``?

    The span is HALF-OPEN: ``from`` counts, ``to`` does not, so two windows
    that meet at 12:00 hand over without an overlap. ``from > to`` spans
    midnight ("22:00-05:00" is open at 23:00 and at 04:59). ``from == to`` is
    therefore an EMPTY window and never open — the editor never writes one,
    an authored one is a slot that says "never".

    An unreadable value counts as "always open", the same fail-open
    :func:`normalize_when` applies.
    """
    text = str(when or "").strip().lower()
    if not text:
        return True
    if text == NIGHT:
        return is_night(now)
    if text == DAY:
        return not is_night(now)
    span = parse_window(text)
    if span is None:
        return True
    start, end = span
    minute = now.minutes_of_day
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end
