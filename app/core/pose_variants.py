"""Per-character pose variant consolidation (plan §6.3).

Instead of using every free pose description as its own image cache key, new
poses are matched against existing variants of the same character. The match
threshold (cosine similarity of the embeddings, default 0.75) decides whether
an existing image is reused or a new variant is created.

Fallback when no embedding is available (no provider configured): string
equality of the normalized pose. Converges more slowly but never crashes.

API:
    get_or_create_variant(char, normalized_pose, embedding=None) -> dict
    get_variant(variant_id) -> dict | None
    update_variant_canonical(variant_id, canonical_pose, embedding) -> None
    list_variants_for_char(char, limit=20) -> list[dict]
    prune_lru(char, keep=20) -> int   # removes the oldest above the limit
    clear_all_variants() -> int       # world-wide reset of the variant cache
"""
import json
import struct
from datetime import datetime

from app.core.timeutils import utc_now_iso
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("pose_variants")


# ----- Settings -----

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_MAX_VARIANTS    = 20


def get_match_threshold() -> float:
    """Cosine threshold from which an existing variant is reused."""
    from app.models.world import get_world_setting
    try:
        raw = get_world_setting("pose.variant_match_threshold", "")
        if raw:
            return max(0.0, min(1.0, float(raw)))
    except Exception:
        pass
    return DEFAULT_MATCH_THRESHOLD


def get_max_variants_per_char() -> int:
    from app.models.world import get_world_setting
    try:
        raw = get_world_setting("pose.max_variants_per_char", "")
        if raw:
            return max(1, int(raw))
    except Exception:
        pass
    return DEFAULT_MAX_VARIANTS


# ----- Embedding helpers -----

def _pack_embedding(vec: Optional[List[float]]) -> Optional[bytes]:
    """Packs an embedding vector into a compact BLOB."""
    if not vec:
        return None
    try:
        return struct.pack(f"{len(vec)}f", *(float(x) for x in vec))
    except Exception as e:
        logger.debug("embedding pack failed: %s", e)
        return None


def _unpack_embedding(blob: Optional[bytes]) -> Optional[List[float]]:
    if not blob:
        return None
    try:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))
    except Exception as e:
        logger.debug("embedding unpack failed: %s", e)
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity of two vectors. Returns 0.0 on any inconsistency."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ----- DB-Helpers -----

def _row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id":             row[0],
        "character_name": row[1],
        "canonical_pose": row[2],
        "embedding":      _unpack_embedding(row[3]),
        "example_image":  row[4] or "",
        "use_count":      int(row[5] or 0),
        "created_at":     row[6] or "",
        "last_used_at":   row[7] or "",
    }


def get_variant(variant_id: int) -> Optional[Dict[str, Any]]:
    if not variant_id:
        return None
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT id, character_name, canonical_pose, embedding, "
            "example_image, use_count, created_at, last_used_at "
            "FROM character_pose_variants WHERE id=?",
            (variant_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.debug("get_variant(%s): %s", variant_id, e)
        return None


def list_variants_for_char(character_name: str,
                            limit: int = 100) -> List[Dict[str, Any]]:
    if not character_name:
        return []
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, character_name, canonical_pose, embedding, "
            "example_image, use_count, created_at, last_used_at "
            "FROM character_pose_variants WHERE character_name=? "
            "ORDER BY last_used_at DESC LIMIT ?",
            (character_name, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.debug("list_variants_for_char(%s): %s", character_name, e)
        return []


def _create_variant(character_name: str,
                     canonical_pose: str,
                     embedding: Optional[List[float]],
                     example_image: str = "") -> Optional[int]:
    """Writes a new variant. Returns the new id or None."""
    now = utc_now_iso()
    blob = _pack_embedding(embedding)
    try:
        with transaction() as conn:
            cur = conn.execute(
                "INSERT INTO character_pose_variants "
                "(character_name, canonical_pose, embedding, example_image, "
                " use_count, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (character_name, canonical_pose, blob, example_image or "",
                 now, now),
            )
            return cur.lastrowid
    except Exception as e:
        logger.warning("create_variant [%s] failed: %s",
                       character_name, e)
        return None


def _touch_variant(variant_id: int) -> None:
    """Updates last_used_at + use_count of the variant."""
    now = utc_now_iso()
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE character_pose_variants "
                "SET use_count = use_count + 1, last_used_at = ? "
                "WHERE id = ?",
                (now, variant_id),
            )
    except Exception as e:
        logger.debug("_touch_variant(%s): %s", variant_id, e)


def update_variant_canonical(variant_id: int,
                              canonical_pose: str,
                              embedding: Optional[List[float]] = None
                              ) -> bool:
    """Overwrites canonical_pose + (optionally) the embedding.

    Called by the vision-LLM background job once the real image has been
    analyzed.
    """
    if not variant_id or not canonical_pose:
        return False
    blob = _pack_embedding(embedding) if embedding is not None else None
    try:
        with transaction() as conn:
            if blob is not None:
                conn.execute(
                    "UPDATE character_pose_variants "
                    "SET canonical_pose=?, embedding=? WHERE id=?",
                    (canonical_pose, blob, variant_id),
                )
            else:
                conn.execute(
                    "UPDATE character_pose_variants "
                    "SET canonical_pose=? WHERE id=?",
                    (canonical_pose, variant_id),
                )
        return True
    except Exception as e:
        logger.warning("update_variant_canonical(%s): %s", variant_id, e)
        return False


def set_example_image(variant_id: int, image_path: str) -> bool:
    if not variant_id:
        return False
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE character_pose_variants SET example_image=? "
                "WHERE id=?",
                (image_path or "", variant_id),
            )
        return True
    except Exception as e:
        logger.debug("set_example_image(%s): %s", variant_id, e)
        return False


# ----- Main logic: match or new variant -----

def get_or_create_variant(
    character_name: str,
    normalized_pose: str,
    embedding: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    """Finds a matching variant or creates a new one.

    Match strategy:
        - With an embedding: cosine against every variant that has one.
          Best match >= threshold → reuse.
        - Otherwise: exact string match on canonical_pose (case-insensitive).

    On a match: use_count++ and last_used_at refreshed. Otherwise a new
    variant. Returns the variant dict (with its id).
    """
    if not (character_name and normalized_pose):
        return None
    normalized = normalized_pose.strip()
    if not normalized:
        return None

    variants = list_variants_for_char(character_name, limit=200)

    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0

    if embedding:
        threshold = get_match_threshold()
        for v in variants:
            ve = v.get("embedding")
            if not ve:
                continue
            score = cosine_similarity(embedding, ve)
            if score >= threshold and score > best_score:
                best_score = score
                best_match = v
    else:
        # String-equality fallback — case-insensitive
        norm_lower = normalized.lower()
        for v in variants:
            if (v.get("canonical_pose") or "").strip().lower() == norm_lower:
                best_match = v
                best_score = 1.0
                break

    if best_match:
        _touch_variant(best_match["id"])
        best_match["use_count"] = (best_match.get("use_count") or 0) + 1
        logger.debug(
            "pose match [%s] %s -> variant %s (score=%.3f)",
            character_name, normalized[:40], best_match["id"], best_score,
        )
        return best_match

    # No match — new variant
    new_id = _create_variant(character_name, normalized, embedding)
    if not new_id:
        return None
    # Prune if the limit is exceeded
    try:
        prune_lru(character_name, keep=get_max_variants_per_char())
    except Exception as e:
        logger.debug("prune_lru after create: %s", e)
    logger.info(
        "new pose variant [%s] id=%s pose=%r",
        character_name, new_id, normalized[:60],
    )
    return get_variant(new_id)


def prune_lru(character_name: str, keep: int = 20) -> int:
    """Deletes the oldest variants above the `keep` limit. Returns the
    number of deleted rows.
    """
    if keep < 1 or not character_name:
        return 0
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id FROM character_pose_variants "
            "WHERE character_name=? ORDER BY last_used_at DESC",
            (character_name,),
        ).fetchall()
        if len(rows) <= keep:
            return 0
        to_delete = [r[0] for r in rows[keep:]]
        with transaction() as conn2:
            conn2.executemany(
                "DELETE FROM character_pose_variants WHERE id=?",
                [(i,) for i in to_delete],
            )
        logger.info("pose LRU [%s]: %d variants removed",
                    character_name, len(to_delete))
        return len(to_delete)
    except Exception as e:
        logger.warning("prune_lru(%s): %s", character_name, e)
        return 0


def clear_all_variants() -> int:
    """Deletes ALL pose variants of the world (one-time cache reset when the
    key scheme changes). Returns the number of deleted rows.

    The stored ``character_state.pose_variant_id`` values are nulled in the
    same transaction — they would otherwise point at rows that no longer
    exist (same reasoning as the pose-catalog migration in ``db.py``).
    """
    try:
        with transaction() as conn:
            # Counted explicitly: a DELETE without WHERE hits SQLite's
            # truncate optimization, whose reported rowcount is not a
            # dependable row count.
            total = conn.execute(
                "SELECT COUNT(*) FROM character_pose_variants").fetchone()[0]
            conn.execute("DELETE FROM character_pose_variants")
            conn.execute(
                "UPDATE character_state SET pose_variant_id=NULL "
                "WHERE pose_variant_id IS NOT NULL")
        logger.info("pose variant cache cleared: %d rows", total)
        return int(total or 0)
    except Exception as e:
        logger.warning("clear_all_variants failed: %s", e)
        return 0
