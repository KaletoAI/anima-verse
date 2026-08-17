"""Central time helpers — system clock AND game clock.

**Two clocks, and the border between them is the TYPE** (plan-game-calendar.md
§1). Never call ``datetime.now()``/``time.time()`` in game logic directly:

- ``datetime`` = SYSTEM time. ``utc_now()`` / ``utc_now_iso()`` /
  ``parse_iso()`` for everything technical: persisted timestamps
  (chat/memories/state history), ordering, cooldowns, queue timing, logs.
  ``local_now()`` / ``to_local()`` / ``to_world_tz()`` render such a stamp in
  the configured display timezone — that is *display of system time only*.
- :class:`~app.core.game_time.GameTime` = GAME time. ``game_time()`` for
  everything the game world "sees": time of day in prompts, day/night
  backgrounds, narration clock, night/day rules, in-world durations
  (conditions, state-flag lifecycle, hourly stat ticks).

The game clock has **no timezone** — the world calendar knows seasons and
days, not zones, so there is no game-time counterpart to ``to_world_tz``.

The game clock is anchored to the system clock and persisted in ``world_kv``
(``anchor_real`` = ISO system stamp, ``anchor_game`` = CANONICAL GameTime
string, ``factor``):

    game_time() = anchor_game + (utc_now() − anchor_real) × factor

``factor`` ≥ 0 lets game time run x-times as fast as system time. The world
freeze stops the game clock (``on_freeze_change``); the sleep mode does not.

Server stores/sends timezone-aware UTC ISO strings (``…+00:00``) for system
stamps; the frontend converts to local time. Works regardless of the server's
timezone.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.game_time import (EPOCH, GameDuration, GameTime,
                                calendar_to_dict)
from app.core.log import get_logger

logger = get_logger("timeutils")


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso(timespec: str = "seconds") -> str:
    """Current UTC time as an ISO string with a +00:00 offset."""
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


def _world_tz():
    """Configured world timezone (``server.timezone``, IANA name). Drives the
    *display*/world clock + day boundaries — NOT storage (which stays UTC).
    Falls back to UTC when unset / invalid."""
    try:
        from app.core import config
        name = (config.get("server.timezone") or "").strip()
        if name:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
    except Exception:
        pass
    return timezone.utc


def local_now() -> datetime:
    """Current SYSTEM time in the configured display timezone (aware). For
    real-world day boundaries and log display. Storage keeps using
    ``utc_now()``. The in-game clock is ``game_time()`` — a ``GameTime``,
    which has no timezone at all."""
    return datetime.now(timezone.utc).astimezone(_world_tz())


def to_local(dt: datetime) -> datetime:
    """UTC (or any aware) stamp → configured world timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_world_tz())


def parse_iso(s: str) -> datetime:
    """ISO string -> timezone-aware datetime.

    Naive legacy data is interpreted as UTC (migration path: old timestamps were
    effectively UTC because the server ran on UTC). This is the key guard against
    "can't compare offset-naive and offset-aware" TypeErrors: every parsed stamp
    becomes aware before it is compared.
    """
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def to_world_tz(iso_or_dt) -> datetime:
    """ISO string or aware datetime → the configured display timezone (aware).

    SYSTEM stamps only — game time is a ``GameTime`` and has no timezone."""
    dt = parse_iso(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt
    return dt.astimezone(_world_tz())


# ═══════════════════════════════════════════════════════════════════════════
# Game clock — anchored to the system clock, persisted in world_kv
# ═══════════════════════════════════════════════════════════════════════════

_KEY_ANCHOR_REAL = "game_time.anchor_real"
_KEY_ANCHOR_GAME = "game_time.anchor_game"
_KEY_FACTOR = "game_time.factor"

# In-process cache of the anchors (single-process server). Invalidated by the
# setters below and by on_freeze_change; loaded lazily from world_kv.
_game_cache: Dict[str, Any] = {}


def _load_game_anchors() -> Dict[str, Any]:
    """Anchors + factor + frozen from world_kv (cached).

    ``anchor_game`` is persisted as a CANONICAL GameTime string. A stored
    value in any other shape (a legacy ISO datetime, or garbage) is NOT
    guessed at: the boot migration (``game_calendar_migration``) converts it
    once, so seeing a non-canonical value here means the migration has not
    run (or failed). We log that loudly and fall back to the epoch with
    factor 1.0 WITHOUT caching, so the next call retries.
    """
    global _game_cache
    if _game_cache.get("loaded"):
        return _game_cache
    anchor_real = utc_now()
    anchor_game = EPOCH
    factor = 1.0
    frozen = False
    try:
        from app.models.world import get_world_setting, is_world_frozen
        raw_real = get_world_setting(_KEY_ANCHOR_REAL, "")
        raw_game = get_world_setting(_KEY_ANCHOR_GAME, "")
        raw_factor = get_world_setting(_KEY_FACTOR, "")
        if raw_factor:
            factor = max(0.0, float(raw_factor))
        frozen = is_world_frozen()
        if raw_game:
            if not GameTime.is_canonical(raw_game):
                logger.error(
                    "game clock anchor %r is not a canonical GameTime string "
                    "— the boot migration has not converted it; falling back "
                    "to the epoch", raw_game)
                return {"anchor_real": utc_now(), "anchor_game": EPOCH,
                        "factor": 1.0, "frozen": frozen, "loaded": False}
            anchor_game = GameTime.parse(raw_game)
            # A missing real anchor means "the world time starts counting
            # now" — never silently discard the game anchor over it.
            if raw_real:
                anchor_real = parse_iso(raw_real)
    except Exception:
        # DB not ready (early boot) — start at the epoch, do not cache so the
        # next call retries.
        return {"anchor_real": anchor_real, "anchor_game": anchor_game,
                "factor": factor, "frozen": frozen, "loaded": False}
    _game_cache = {"anchor_real": anchor_real, "anchor_game": anchor_game,
                   "factor": factor, "frozen": frozen, "loaded": True}
    return _game_cache


def _persist_game_anchors(anchor_real: datetime, anchor_game: GameTime,
                          factor: float) -> None:
    from app.models.world import set_world_setting
    set_world_setting(_KEY_ANCHOR_REAL, anchor_real.isoformat())
    set_world_setting(_KEY_ANCHOR_GAME, anchor_game.canonical())
    set_world_setting(_KEY_FACTOR, repr(float(factor)))
    _game_cache.clear()


def game_time() -> GameTime:
    """Current GAME time as a :class:`GameTime` (world calendar, no timezone).

    Frozen world → the clock stands still at the freeze anchor."""
    a = _load_game_anchors()
    anchor_game: GameTime = a["anchor_game"]
    if a["frozen"]:
        return anchor_game
    elapsed = (utc_now() - a["anchor_real"]).total_seconds() * a["factor"]
    seconds = int(round(elapsed))
    if seconds >= 0:
        return anchor_game + GameDuration(seconds)
    # A real clock jump backwards must never produce a pre-epoch instant.
    return anchor_game.minus_clamped(GameDuration(-seconds))


def game_speed_factor() -> float:
    """Current game-clock factor; 0.0 while the world is frozen.

    How many GAME seconds pass per REAL second. Consumers turn game-time
    durations into real-time ones (a frozen world → 0.0 → no conversion)."""
    a = _load_game_anchors()
    return 0.0 if a["frozen"] else float(a["factor"])


def set_game_time(when: GameTime) -> None:
    """Re-anchor the game clock to ``when`` (time jumps, factor unchanged).

    Strictly typed: a ``datetime`` or a string is rejected instead of being
    parsed. Callers hold world time, and world time is a ``GameTime``."""
    if not isinstance(when, GameTime):
        raise TypeError(
            f"set_game_time expects a GameTime, got {type(when).__name__} "
            f"({when!r}) — game time is not a datetime/ISO string")
    a = _load_game_anchors()
    _persist_game_anchors(utc_now(), when, a["factor"])


def set_game_factor(factor: float) -> None:
    """Change the tick factor. Re-anchors at the current game time first so
    the clock is continuous (no jump)."""
    factor = max(0.0, float(factor))
    current = game_time()
    _persist_game_anchors(utc_now(), current, factor)


def on_freeze_change(frozen: bool) -> None:
    """World-freeze hook: freeze stops the game clock, unfreeze resumes it.

    Called by ``set_world_frozen`` AFTER the flag is persisted. Freeze
    re-anchors at the current game time (so ``game_time()`` returns the frozen
    anchor); unfreeze re-anchors the real side so no frozen span is counted."""
    a = _load_game_anchors()
    if frozen:
        # Compute the game time BEFORE the flag flip took effect in our cache:
        # anchors are still the running ones here.
        elapsed = (utc_now() - a["anchor_real"]).total_seconds() * a["factor"]
        seconds = int(round(elapsed))
        anchor_game: GameTime = a["anchor_game"]
        frozen_at = (anchor_game + GameDuration(seconds) if seconds >= 0
                     else anchor_game.minus_clamped(GameDuration(-seconds)))
        _persist_game_anchors(utc_now(), frozen_at, a["factor"])
    else:
        _persist_game_anchors(utc_now(), a["anchor_game"], a["factor"])


def get_game_clock_info(lang: str = "en") -> Dict[str, Any]:
    """Clock info for the API/UI: system now, the world instant (fully
    rendered — clients never compute), anchors, factor, freeze, calendar."""
    a = _load_game_anchors()
    anchor_game: GameTime = a["anchor_game"]
    return {
        "system_now": utc_now_iso(),
        "game": game_time().to_dict(lang),
        "anchor_real": a["anchor_real"].isoformat(timespec="seconds"),
        "anchor_game": anchor_game.canonical(),
        "factor": a["factor"],
        "frozen": bool(a["frozen"]),
        "calendar": calendar_to_dict(lang=lang),
    }


def invalidate_game_clock_cache() -> None:
    """Drops the in-process anchor cache (next read reloads from world_kv)."""
    _game_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Back-projection — SYSTEM stamp ↔ GAME day
# ═══════════════════════════════════════════════════════════════════════════
#
# Clock mathematics, so it lives next to the clock. Both directions run the
# CURRENT rate backwards/forwards; they are for GROUPING and MIGRATING rows
# that were stamped in system time, never for durations and never for stamps
# that get persisted as game time.


def _start_of_day_key(day_key: str) -> Optional[GameTime]:
    """Start of the game day named by a ``day_key`` (``Y0002-D109``), or None."""
    if not isinstance(day_key, str) or not day_key.strip():
        return None
    try:
        return GameTime.parse(f"{day_key.strip()}T00:00:00")
    except ValueError:
        return None


def game_time_at(when: Any) -> Optional[GameTime]:
    """The GAME time a SYSTEM stamp belongs to, or ``None`` if unusable.

    The world keeps no clock history — only the current anchor (game time,
    real time, factor) exists. A past system stamp is therefore placed by
    running the CURRENT rate backwards::

        game_at(t) = game_time() − (utc_now() − t) × factor

    That is exact as long as anchor and factor have not moved since ``t`` and
    the world was not frozen in between — the very assumption ``game_time()``
    already makes for the present. Its ONLY jobs are to sort SYSTEM-stamped
    rows (scenes, chat messages, memories) into game days and to backfill a
    game stamp during a migration: never for durations, never for a stamp that
    is then persisted as the authoritative game time of a NEW row (those call
    ``game_time()``). Stamps that project before the world epoch clamp to it.
    """
    if isinstance(when, datetime):
        dt = when
    elif isinstance(when, str) and when.strip():
        try:
            dt = parse_iso(when.strip())
        except (ValueError, TypeError):
            return None
    else:
        return None
    factor = game_speed_factor()
    if factor <= 0:
        factor = 1.0
    behind = (utc_now() - dt).total_seconds() * factor
    if behind <= 0:
        return game_time() + GameDuration.of(seconds=-behind)
    return game_time().minus_clamped(GameDuration.of(seconds=behind))


def system_window_of_game_day(day_key: str) -> Optional[Tuple[str, str]]:
    """SYSTEM window ``(start_iso, end_iso)`` covering one game day.

    The inverse of :func:`game_time_at`, with the same caveat, for the one job
    that needs it: selecting SYSTEM-stamped rows (``chat_messages.ts``,
    ``mood_history.ts``, ``state_history.ts``) that belong to a given game
    day. ``start`` inclusive, ``end`` exclusive.
    """
    start = _start_of_day_key(day_key)
    if start is None:
        return None
    factor = game_speed_factor()
    if factor <= 0:
        factor = 1.0
    now, now_game = utc_now(), game_time()

    def _real(point: GameTime) -> str:
        ahead = (now_game - point).total_seconds / factor
        return (now - timedelta(seconds=ahead)).isoformat()

    return _real(start), _real(start.next_day_start())
