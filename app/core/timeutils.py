"""Central time helpers — system clock AND game clock.

Two clocks, one convention (never call ``datetime.now()``/``time.time()`` in
game logic directly):

- ``utc_now()`` / ``utc_now_iso()`` — SYSTEM time (UTC). For everything
  technical: persisted timestamps (chat/memories/state history), ordering,
  cooldowns, queue timing, logs, day consolidation.
- ``game_now()`` / ``game_local_now()`` / ``game_now_iso()`` — GAME time.
  For everything the game world "sees": time of day in prompts, day/night
  backgrounds, narration clock, night/day rules, in-world durations
  (conditions, state-flag lifecycle, hourly stat ticks).

The game clock is anchored to the system clock and persisted in ``world_kv``:

    game_now() = anchor_game + (utc_now() − anchor_real) × factor

``factor`` ≥ 0 lets game time run x-times as fast as system time. The world
freeze stops the game clock (``on_freeze_change``); the sleep mode does not.

Server stores/sends timezone-aware UTC ISO strings (``…+00:00``); the frontend
converts to local time. Works regardless of the server's timezone.
"""

from datetime import datetime, timezone
from typing import Any, Dict


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
    """Current SYSTEM time in the configured world timezone (aware). For real
    day boundaries (e.g. day consolidation). Storage keeps using ``utc_now()``.
    The in-game clock is ``game_local_now()``."""
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
    """Anchors + factor + frozen from world_kv (cached). Unset world → the
    game clock equals the system clock (factor 1)."""
    global _game_cache
    if _game_cache.get("loaded"):
        return _game_cache
    anchor_real = utc_now()
    anchor_game = anchor_real
    factor = 1.0
    frozen = False
    try:
        from app.models.world import get_world_setting, is_world_frozen
        raw_real = get_world_setting(_KEY_ANCHOR_REAL, "")
        raw_game = get_world_setting(_KEY_ANCHOR_GAME, "")
        raw_factor = get_world_setting(_KEY_FACTOR, "")
        if raw_real and raw_game:
            anchor_real = parse_iso(raw_real)
            anchor_game = parse_iso(raw_game)
        if raw_factor:
            factor = max(0.0, float(raw_factor))
        frozen = is_world_frozen()
    except Exception:
        # DB not ready (early boot) — behave like the system clock, do not
        # cache so the next call retries.
        return {"anchor_real": anchor_real, "anchor_game": anchor_game,
                "factor": factor, "frozen": frozen, "loaded": False}
    _game_cache = {"anchor_real": anchor_real, "anchor_game": anchor_game,
                   "factor": factor, "frozen": frozen, "loaded": True}
    return _game_cache


def _persist_game_anchors(anchor_real: datetime, anchor_game: datetime,
                          factor: float) -> None:
    from app.models.world import set_world_setting
    set_world_setting(_KEY_ANCHOR_REAL, anchor_real.isoformat())
    set_world_setting(_KEY_ANCHOR_GAME, anchor_game.isoformat())
    set_world_setting(_KEY_FACTOR, repr(float(factor)))
    _game_cache.clear()


def game_now() -> datetime:
    """Current GAME time as a timezone-aware UTC datetime.

    Frozen world → the clock stands still at the freeze anchor."""
    a = _load_game_anchors()
    if a["frozen"]:
        return a["anchor_game"]
    elapsed = utc_now() - a["anchor_real"]
    return a["anchor_game"] + elapsed * a["factor"]


def game_now_iso(timespec: str = "seconds") -> str:
    """Current game time as an ISO string with a +00:00 offset."""
    return game_now().isoformat(timespec=timespec)


def game_local_now() -> datetime:
    """Current game time in the configured world timezone (aware). THE in-game
    clock: time of day for prompts, day/night backgrounds, night/day rules."""
    return game_now().astimezone(_world_tz())


def set_game_time(dt: datetime) -> None:
    """Re-anchor the game clock to ``dt`` (game time jumps, factor unchanged)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    a = _load_game_anchors()
    _persist_game_anchors(utc_now(), dt.astimezone(timezone.utc), a["factor"])


def set_game_factor(factor: float) -> None:
    """Change the tick factor. Re-anchors at the current game time first so
    the clock is continuous (no jump)."""
    factor = max(0.0, float(factor))
    current = game_now()
    _persist_game_anchors(utc_now(), current, factor)


def on_freeze_change(frozen: bool) -> None:
    """World-freeze hook: freeze stops the game clock, unfreeze resumes it.

    Called by ``set_world_frozen`` AFTER the flag is persisted. Freeze
    re-anchors at the current game time (so ``game_now()`` returns the frozen
    anchor); unfreeze re-anchors the real side so no frozen span is counted."""
    a = _load_game_anchors()
    if frozen:
        # Compute the game time BEFORE the flag flip took effect in our cache:
        # anchors are still the running ones here.
        elapsed = utc_now() - a["anchor_real"]
        frozen_at = a["anchor_game"] + elapsed * a["factor"]
        _persist_game_anchors(utc_now(), frozen_at, a["factor"])
    else:
        _persist_game_anchors(utc_now(), a["anchor_game"], a["factor"])


def get_game_clock_info() -> Dict[str, Any]:
    """Clock info for the API/UI: both nows, anchors, factor, frozen."""
    a = _load_game_anchors()
    return {
        "system_now": utc_now_iso(),
        "game_now": game_now().isoformat(timespec="seconds"),
        "anchor_real": a["anchor_real"].isoformat(timespec="seconds"),
        "anchor_game": a["anchor_game"].isoformat(timespec="seconds"),
        "factor": a["factor"],
        "frozen": bool(a["frozen"]),
    }


def invalidate_game_clock_cache() -> None:
    """Drops the in-process anchor cache (next read reloads from world_kv)."""
    _game_cache.clear()
