"""Relationship decay — periodic background job that weakens idle
relationships and re-classifies their type.

Runs in the BackgroundQueue, submitted by the periodic sub-job
``relationship_decay`` (every 24 h, see ``app/core/periodic_jobs.py``).

Rules:
  - a pair that has not interacted for more than ``GRACE_DAYS`` days loses
    strength (``DECAY_STRENGTH_PER_WEEK`` per week of idleness)
  - ``romantic_tension`` decays more slowly (``DECAY_ROMANTIC_PER_WEEK``)
  - after the strength update the relationship type is re-classified

How much is applied per run is measured from ``last_decay`` — the stamp of the
last run that touched this pair — not from ``last_interaction``. Without it
every run would apply the WHOLE idle span again (with a 24 h cadence a pair
would have lost the per-week amount every single day). A pair that has no
``last_decay`` yet is only stamped, never decayed: the job did not run at all
between the multi-user rework and 2026-09 (it submitted an empty ``user_id``
that the handler rejected), and charging months of backlog in one tick would
wipe every long-idle relationship at once. Decay therefore starts counting at
the first run after the grace period.

Clock note: ``last_interaction``/``last_decay`` are SYSTEM stamps
(``app/models/relationship.py`` writes ``utc_now_iso()``), so the elapsed span
is measured with the system clock — the same clock the stamps carry.
"""
from typing import Any, Dict

from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now, utc_now_iso

logger = get_logger("relationship_decay")

# Decay amounts per week of idleness. Plain constants on purpose: this project
# takes no configuration from environment variables.
DECAY_STRENGTH_PER_WEEK = 1.0
DECAY_ROMANTIC_PER_WEEK = 0.02
# No decay before a pair has been idle this long.
GRACE_DAYS = 7.0
# Upper bound per run — a long server downtime (or a system-clock jump) must
# not empty a relationship in a single pass.
MAX_WEEKS_PER_RUN = 2.0


def handle_relationship_decay(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Background-queue handler: applies decay to all relationships."""
    from app.models.relationship import (
        load_relationships,
        save_relationships,
        classify_type)

    rels = load_relationships()
    if not rels:
        return {"skipped": True, "reason": "no relationships"}

    now = utc_now()
    now_iso = utc_now_iso()
    strength_affected = 0
    romantic_affected = 0
    stamped = 0

    for rel in rels:
        last_iso = rel.get("last_interaction", "")
        try:
            last_interaction = parse_iso(last_iso)
        except (ValueError, TypeError):
            logger.debug("unparseable last_interaction %r on %s/%s — treating "
                         "the pair as idle", last_iso,
                         rel.get("character_a", ""), rel.get("character_b", ""))
            last_interaction = None

        if last_interaction is not None:
            days_idle = (now - last_interaction).total_seconds() / 86400
            if days_idle < GRACE_DAYS:
                continue

        prev_iso = rel.get("last_decay", "")
        if not prev_iso:
            # First run for this pair: remember where decay starts, do not
            # charge the backlog.
            rel["last_decay"] = now_iso
            stamped += 1
            continue
        try:
            reference = parse_iso(prev_iso)
        except (ValueError, TypeError):
            rel["last_decay"] = now_iso
            stamped += 1
            continue
        # An interaction after the last decay run resets the reference.
        if last_interaction is not None and last_interaction > reference:
            reference = last_interaction

        weeks = (now - reference).total_seconds() / (7 * 86400)
        if weeks <= 0:
            continue
        weeks = min(weeks, MAX_WEEKS_PER_RUN)

        touched = False

        old_strength = rel.get("strength", 0)
        new_strength = max(0, old_strength - DECAY_STRENGTH_PER_WEEK * weeks)
        # Two decimals, not one: with a 24 h cadence a run takes off
        # 1/7 = 0.142857, and rounding that to one decimal would swallow a
        # third of the decay on every single run.
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

        rel["last_decay"] = now_iso
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
    """Registers the handler in the BackgroundQueue."""
    from app.core.background_queue import get_background_queue
    bq = get_background_queue()
    bq.register_handler("relationship_decay", handle_relationship_decay)
    logger.info("Relationship decay handler registered")
