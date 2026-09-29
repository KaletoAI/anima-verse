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
* ``interaction_invites.pose_key`` and ``pose_candidates.nearest_key``;
* the rendered expression variants: the key is hashed into the file stem
  (``expression_regen.variant_stem``) and stored in the sidecar.

The OLD key is not kept as a synonym — no backward-compat alias on a rename.
Only the CURRENT world is rewritten; another world that stored the old key
falls back to the default pose there until its next pose change.
"""
import json
from typing import Any, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

#: Keys the server code names literally — renaming one would silently break
#: that code path: ``standing`` is the fallback default
#: (``pose_catalog._FALLBACK_DEFAULT``), ``sleeping`` is what
#: ``character.get_effective_pose_key`` returns for a sleeper, ``walking`` is
#: what a roaming NPC walks in (``npc_actions``).
CODE_NAMED_POSE_KEYS = frozenset({"standing", "sleeping", "walking"})

_IMAGE_EXTS = (".png", ".jpg", ".webp")


def rewrite_references(old: str, new: str) -> Dict[str, Any]:
    """Point every stored reference to pose key ``old`` at ``new``.

    Returns counts: ``profiles`` (characters whose profile changed),
    ``invites``, ``candidates`` (nearest_key rewritten), ``candidates_closed``
    (open rows whose text now IS a key), ``variants_moved`` / ``variants_kept``
    and ``failed`` — names whose profile save failed (they stay on the default
    pose until their next pose change), plus ``step:<name>`` for a step that
    raised; the steps after it still run, so the counts of the others survive.
    """
    out: Dict[str, Any] = {"profiles": 0, "invites": 0, "candidates": 0,
                           "candidates_closed": 0, "variants_moved": 0,
                           "variants_kept": 0, "failed": []}
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
    try:
        out["variants_moved"], out["variants_kept"] = _rewrite_variants(old, new)
    except Exception as e:
        logger.error("pose key rename: variant step failed: %s", e, exc_info=True)
        out["failed"].append("step:variants")
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


def _rewrite_variants(old: str, new: str) -> Tuple[int, int]:
    """Move the rendered expression variants of ``old`` under their new stem.

    A variant moves only when its OLD stem, recomputed from the sidecar's
    inputs, equals its actual file stem — proof the inputs still reproduce
    it. That proof is conservative on purpose: the outfit part of the stem
    reads the items table live (``visible_equipped_pieces``) and, for a
    character without an outfit system, the CURRENT free-text outfit. A
    variant rendered before such an edit cannot be re-derived and is KEPT
    under its old name; it would never have been hit again anyway and the LRU
    pruner removes it. Every matching sidecar gets the new key either way (the
    scene fallback compares its ``activity`` with the pose key).
    """
    from app.core.expression_regen import variant_stem
    from app.core.model_refs import outfit_signature_raw
    from app.models.character import get_character_dir, list_available_characters
    moved = kept = 0
    for name in list_available_characters(include_pooled=True):
        # Not get_character_outfits_dir: that one creates the folder, and a
        # rename must not leave empty ones behind.
        folder = get_character_dir(name) / "outfits"
        if not folder.is_dir():
            continue
        for sidecar in sorted(folder.glob("*.json")):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict) or meta.get("pose_key") != old:
                continue
            meta["pose_key"] = new
            if meta.get("activity") == old:
                meta["activity"] = new
            expr = str(meta.get("expression_key") or "")
            pieces = meta.get("equipped_pieces") or {}
            items = meta.get("equipped_items") or []
            state_fp = meta.get("state_fingerprint") or ""
            images = [folder / f"{sidecar.stem}{ext}" for ext in _IMAGE_EXTS
                      if (folder / f"{sidecar.stem}{ext}").exists()]
            stem = ""
            if expr and images:
                outfit = outfit_signature_raw(pieces, items, name)
                if variant_stem(name, expr, old, outfit, state_fp) == sidecar.stem:
                    stem = variant_stem(name, expr, new, outfit, state_fp)
                    if any((folder / f"{stem}{ext}").exists()
                           for ext in _IMAGE_EXTS + (".json",)):
                        stem = ""  # something already lives there — keep ours
            # Sidecar FIRST, at its old path: a failure after that leaves a
            # consistent old-stem variant carrying the new key, never images
            # under the new stem without their sidecar.
            try:
                sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
                if stem:
                    for img in images:
                        img.rename(folder / f"{stem}{img.suffix}")
                    sidecar.rename(folder / f"{stem}.json")
            except OSError as e:
                logger.warning("pose key rename: variant %s not moved: %s",
                               sidecar.name, e)
                stem = ""
            if stem:
                moved += 1
            else:
                kept += 1
    return moved, kept
