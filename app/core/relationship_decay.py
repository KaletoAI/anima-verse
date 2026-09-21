"""Relationship decay — periodic background job that weakens idle
relationships and re-classifies their type.

Runs in the task queue, submitted by the periodic sub-job
``relationship_decay`` (hourly, see ``app/core/periodic_jobs.py``); the
handler itself decides whether a pair is due.

Rules:
  - a pair that has not interacted for more than ``GRACE`` loses strength
    (``DECAY_STRENGTH_PER_WEEK`` per week of idleness)
  - ``romantic_tension`` decays more slowly (``DECAY_ROMANTIC_PER_WEEK``)
  - after the strength update the relationship type is re-classified

Clock note: this is GAME logic, so every span here is measured on the GAME
clock (``game_time()``) and every stamp it reads or writes is a canonical
``GameTime`` string — ``last_interaction_game`` on the pair,
``last_decay_game`` for the run itself. A world that runs at a high tick
factor ages its relationships faster, a frozen world ages none at all, and a
real-time downtime costs nothing. "One week" is a flat
``GameDuration.of(days=7)``: the world calendar has no real weeks (its
``week_days`` list only NAMES days and may be absent entirely), so the decay
period is a duration, never a calendar lookup.

How much is applied per run is measured from ``last_decay_game`` — the stamp
of the last run that touched this pair — not from ``last_interaction_game``.
Without it every run would apply the WHOLE idle span again. A pair that has no
``last_decay_game`` yet is only stamped, never decayed; charging months of
backlog in one tick would wipe every long-idle relationship at once. Decay
therefore starts counting at the first run after the grace period.

Legacy pairs: a pair written before the game stamps existed carries only the
SYSTEM stamps. The two clocks are NOT convertible (the world keeps no clock
history), so such a pair is stamped with the CURRENT game time and skipped for
this run. Its grace period therefore restarts once, at that migration run —
the accepted, gentle behaviour, in the same spirit as the "first run only
stamps" rule above. Nobody loses closeness because of a conversion.

Cadence: the periodic job fires every real hour, but a pair is only acted on
once its ``last_decay_game`` is at least ``MIN_STEP`` (one game day) old. That
keeps a fast game clock from nibbling the strength away in tiny float steps
while still picking up a deliberate clock jump within the hour. A world whose
clock stands still produces a zero span, which is a clean no-op: nothing is
written and ``save_relationships`` is not called at all.
"""
from typing import Any, Dict, Optional

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger("relationship_decay")

# Decay amounts per week of idleness. Plain constants on purpose: this project
# takes no configuration from environment variables.
DECAY_STRENGTH_PER_WEEK = 1.0
DECAY_ROMANTIC_PER_WEEK = 0.02
# "A week" of the decay rates — seven GAME days, flat (see the module note).
DECAY_PERIOD = GameDuration.of(days=7)
# No decay before a pair has been idle this long.
GRACE = GameDuration.of(days=7)
# The smallest span a run charges: a pair is skipped until one GAME day has
# passed since its last decay stamp.
MIN_STEP = GameDuration.of(days=1)
# Upper bound per run — a long idle span (or a deliberate clock jump forward)
# must not empty a relationship in a single pass.
MAX_WEEKS_PER_RUN = 2.0


def _game_stamp(value: Any) -> Optional[GameTime]:
    """A persisted canonical game stamp, or ``None`` when it is missing or
    unreadable. Both cases are treated alike by the caller."""
    try:
        return GameTime.parse(value)
    except (ValueError, TypeError):
        return None


def _drop_system_stamp(rel: Dict[str, Any]) -> None:
    """Remove the obsolete SYSTEM decay stamp from a row we are writing anyway.

    ``last_decay`` was the system-clock predecessor of ``last_decay_game``.
    Nothing reads it any more, so it is dropped rather than carried along in
    the row's meta blob forever."""
    rel.pop("last_decay", None)


def handle_relationship_decay(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background-queue handler: applies decay to all relationships."""
    from app.models.relationship import (
        load_relationships,
        save_relationships,
        classify_type)

    rels = load_relationships()
    if not rels:
        return {"skipped": True, "reason": "no relationships"}

    now = game_time()
    now_game = now.canonical()
    strength_affected = 0
    romantic_affected = 0
    stamped = 0

    for rel in rels:
        last_interaction = _game_stamp(rel.get("last_interaction_game"))
        last_decay = _game_stamp(rel.get("last_decay_game"))

        if last_decay is not None:
            since_run = now - last_decay
            if since_run < GameDuration.ZERO:
                # The world clock was set BACK behind this pair's stamp. A
                # negative span must never be charged, and leaving the stamp
                # in the future would freeze the pair until the clock caught
                # up again — so re-anchor it and decay nothing this run.
                rel["last_decay_game"] = now_game
                _drop_system_stamp(rel)
                stamped += 1
                continue
            if since_run < MIN_STEP:
                # Same game day: nothing to charge, and nothing to write.
                continue

        if last_interaction is None:
            # A pair written before the game stamps existed. System time does
            # not convert into world time, so the only honest answer is "the
            # world meets this pair now" — stamp and skip.
            rel["last_interaction_game"] = now_game
            rel["last_decay_game"] = now_game
            _drop_system_stamp(rel)
            stamped += 1
            continue

        if (now - last_interaction) < GRACE:
            continue

        if last_decay is None:
            # First run for this pair: remember where decay starts, do not
            # charge the backlog.
            rel["last_decay_game"] = now_game
            _drop_system_stamp(rel)
            stamped += 1
            continue

        # An interaction after the last decay run resets the reference.
        reference = max(last_decay, last_interaction)
        span = now - reference
        if span <= GameDuration.ZERO:
            continue
        weeks = min(span.total_seconds / DECAY_PERIOD.total_seconds,
                    MAX_WEEKS_PER_RUN)

        touched = False

        old_strength = rel.get("strength", 0)
        new_strength = max(0, old_strength - DECAY_STRENGTH_PER_WEEK * weeks)
        # Two decimals, not one: a run may charge a fraction of a week, and
        # rounding that to one decimal would swallow part of the decay on
        # every single run.
        if round(new_strength, 2) != round(old_strength, 2):
            rel["strength"] = round(new_strength, 2)
            strength_affected += 1
            touched = True

        old_romantic = rel.get("romantic_tension", 0)
        if old_romantic > 0:
            new_romantic = max(
                0, old_romantic - DECAY_ROMANTIC_PER_WEEK * weeks)
            if round(new_romantic, 3) != round(old_romantic, 3):
                rel["romantic_tension"] = round(new_romantic, 3)
                romantic_affected += 1
                touched = True

        rel["last_decay_game"] = now_game
        _drop_system_stamp(rel)
        stamped += 1

        if not touched:
            continue

        # Re-classify the type after the decay
        from app.models.relationship import are_romantically_compatible
        compatible = are_romantically_compatible(
            rel.get("character_a", ""), rel.get("character_b", ""))
        rel["type"] = classify_type(
            rel.get("strength", 0),
            rel.get("sentiment_a_to_b", 0),
            rel.get("sentiment_b_to_a", 0),
            rel.get("romantic_tension", 0),
            romantic_compatible=compatible)

    if strength_affected or romantic_affected or stamped:
        save_relationships(rels)
        logger.info("Relationship decay: %d strength, %d romantic, %d stamped",
                    strength_affected, romantic_affected, stamped)

    return {
        "success": True,
        "strength_affected": strength_affected,
        "romantic_affected": romantic_affected,
    }


def register_relationship_decay_handler():
    """Registers the handler in the task queue."""
    from app.core.task_queue import get_task_queue
    tq = get_task_queue()
    tq.register_handler("relationship_decay", handle_relationship_decay)
    logger.info("Relationship decay handler registered")
