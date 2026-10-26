"""Renaming a pose catalog key — every place the key is STORED follows it.

The catalog entry itself (and the group defaults naming it) is rewritten by
the route (``routes/poses._rename_entry_sync``) inside the catalog lock; this
module rewrites the world's references AFTERWARDS, in that order: the other
way round would point live rows at a key that does not exist yet. Between the
two steps the old key simply resolves to the default pose.

What stores a pose key (plan-pose-key-rename.md):

* the profile — ``pose_key`` (a ``character_state`` column that every
  ``save_character_profile`` writes back, so it is rewritten through the
  profile under its lock, never with a raw UPDATE) and a running pair
  interaction's ``interaction.pose_key``;
* ``interaction_invites.pose_key`` and ``pose_candidates.nearest_key``.

Expression images no longer depend on activity poses and are not rewritten.

The OLD key is not kept as a synonym — no backward-compat alias on a rename.
Only the CURRENT world is rewritten; another world that stored the old key
falls back to the default pose there until its next pose change.
"""
from typing import Any, Dict, List, Tuple

from app.core.movement import MOVEMENT_POSES
from app.core.log import get_logger

logger = get_logger(__name__)

#: Keys the server code names literally — renaming one would silently break
#: that code path: ``sleeping`` is what ``character.get_effective_pose_key``
#: returns for a sleeper, and the movement poses (``movement.MOVEMENT_POSES``)
#: are what the movement types play — ``standing`` is also the fallback
#: default (``pose_catalog._FALLBACK_DEFAULT``), ``walking`` what a roaming
#: NPC walks in (``npc_actions``).
CODE_NAMED_POSE_KEYS = frozenset({"sleeping", *MOVEMENT_POSES})



def rewrite_references(old: str, new: str) -> Dict[str, Any]:
    """Point every stored reference to pose key ``old`` at ``new``.

    Returns counts: ``profiles`` (characters whose profile changed),
    ``invites``, ``candidates`` (nearest_key rewritten), ``candidates_closed``
    and ``failed``. Expression files are independent of activity pose keys.
    """
    out: Dict[str, Any] = {"profiles": 0, "invites": 0, "candidates": 0,
                           "candidates_closed": 0, "failed": []}
    try:
        out["profiles"], out["failed"] = _rewrite_profiles(old, new)
    except Exception as e:
        logger.error("pose key rename: profile step failed: %s", e, exc_info=True)
        out["failed"].append("step:profiles")
    try:
        out["invites"], out["candidates"], out["candidates_closed"] = _rewrite_rows(old, new)
    except Exception as e:
        logger.error("pose key rename: table step failed: %s", e, exc_info=True)
        out["failed"].append("step:tables")
    logger.info("pose key rename %r -> %r: %s", old, new, out)
    return out


def _rewrite_profiles(old: str, new: str) -> Tuple[int, List[str]]:
    """``pose_key`` and ``interaction.pose_key``, one save per character."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import (
        get_character_profile, list_available_characters, save_character_profile,
    )
    changed = 0
    failed: List[str] = []
    for name in list_available_characters(include_pooled=True):
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            touched = False
            if profile.get("pose_key") == old:
                profile["pose_key"] = new
                touched = True
            inter = profile.get("interaction")
            if isinstance(inter, dict) and inter.get("pose_key") == old:
                inter["pose_key"] = new
                touched = True
            if not touched:
                continue
            if save_character_profile(name, profile):
                changed += 1
            else:
                logger.warning("pose key rename: profile of %s not saved", name)
                failed.append(name)
    return changed, failed


def _rewrite_rows(old: str, new: str) -> Tuple[int, int, int]:
    """The two tables without an in-memory mirror, in one transaction."""
    from app.core.db import transaction
    with transaction() as conn:
        invites = conn.execute(
            "UPDATE interaction_invites SET pose_key=? WHERE pose_key=?",
            (new, old)).rowcount
        candidates = conn.execute(
            "UPDATE pose_candidates SET nearest_key=? "
            "WHERE axis='pose' AND nearest_key=?", (new, old)).rowcount
        # A candidate whose text is now a catalog key resolves directly — left
        # open it would stay in the review list forever. Any status: a
        # dismissed row for a text that is now a key is dead weight too.
        closed = conn.execute(
            "DELETE FROM pose_candidates WHERE axis='pose' AND raw_text=?",
            (new,)).rowcount
    return invites, candidates, closed



