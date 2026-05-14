"""Pose-Variant-Konsolidierung pro Character (Plan §6.3).

Statt jede freie pose-Beschreibung als eigenen Bild-Cache-Key zu nutzen,
matchen wir neue Posen gegen bestehende Varianten desselben Characters.
Match-Schwelle (Cosine-Similarity der Embeddings, Default 0.75) bestimmt
ob ein bestehendes Bild wiederverwendet wird oder ein neuer Variant
angelegt wird.

Fallback wenn kein Embedding verfuegbar (kein Provider konfiguriert):
String-Equality der normalisierten Pose. Konvergiert langsamer aber
stuerzt nicht ab.

API:
    get_or_create_variant(char, normalized_pose, embedding=None) -> dict
    get_variant(variant_id) -> dict | None
    update_variant_canonical(variant_id, canonical_pose, embedding) -> None
    list_variants_for_char(char, limit=20) -> list[dict]
    prune_lru(char, keep=20) -> int   # entfernt aelteste ueber dem Limit
"""
import json
import struct
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("pose_variants")


# ----- Settings -----

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_MAX_VARIANTS    = 20


def get_match_threshold() -> float:
    """Cosine-Threshold ab dem ein bestehender Variant wiederverwendet wird."""
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


# ----- Embedding-Hilfen -----

def _pack_embedding(vec: Optional[List[float]]) -> Optional[bytes]:
    """Packt einen Embedding-Vektor in einen kompakten BLOB."""
    if not vec:
        return None
    try:
        return struct.pack(f"{len(vec)}f", *(float(x) for x in vec))
    except Exception as e:
        logger.debug("Embedding-Pack fehlgeschlagen: %s", e)
        return None


def _unpack_embedding(blob: Optional[bytes]) -> Optional[List[float]]:
    if not blob:
        return None
    try:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))
    except Exception as e:
        logger.debug("Embedding-Unpack fehlgeschlagen: %s", e)
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine-Similarity zweier Vektoren. Returns 0.0 bei Inkonsistenzen."""
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
    """Schreibt einen neuen Variant. Returns neue ID oder None."""
    now = datetime.now().isoformat()
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
        logger.warning("create_variant [%s] fehlgeschlagen: %s",
                       character_name, e)
        return None


def _touch_variant(variant_id: int) -> None:
    """Aktualisiert last_used_at + use_count fuer den Variant."""
    now = datetime.now().isoformat()
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
    """Ueberschreibt canonical_pose + (optional) embedding.

    Wird vom Visual-LLM-Background-Job aufgerufen, nachdem das echte
    Bild analysiert wurde.
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


# ----- Hauptlogik: Match oder neuer Variant -----

def get_or_create_variant(
    character_name: str,
    normalized_pose: str,
    embedding: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    """Sucht einen passenden Variant oder legt einen neuen an.

    Match-Strategie:
        - Wenn embedding gegeben: Cosine gegen alle Variants mit embedding.
          Bestes Match >= threshold → wiederverwenden.
        - Sonst: exakte String-Match auf canonical_pose (case-insensitive).

    Bei Match: use_count++ und last_used_at aktualisieren. Sonst: neuer
    Variant. Returns das Variant-Dict (mit id).
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
        # String-Equality-Fallback — case-insensitive
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
            "Pose-Match [%s] %s -> variant %s (score=%.3f)",
            character_name, normalized[:40], best_match["id"], best_score,
        )
        return best_match

    # Kein Match — neuer Variant
    new_id = _create_variant(character_name, normalized, embedding)
    if not new_id:
        return None
    # Pruning falls Limit ueberschritten
    try:
        prune_lru(character_name, keep=get_max_variants_per_char())
    except Exception as e:
        logger.debug("prune_lru nach create: %s", e)
    logger.info(
        "Pose-Variant neu [%s] id=%s pose=%r",
        character_name, new_id, normalized[:60],
    )
    return get_variant(new_id)


def prune_lru(character_name: str, keep: int = 20) -> int:
    """Loescht aelteste Variants ueber dem `keep`-Limit. Returns Anzahl
    geloeschter Rows.
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
        logger.info("Pose-LRU [%s]: %d Variants entfernt",
                    character_name, len(to_delete))
        return len(to_delete)
    except Exception as e:
        logger.warning("prune_lru(%s): %s", character_name, e)
        return 0
