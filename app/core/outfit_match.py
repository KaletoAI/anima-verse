"""Outfit similarity for nearest-match serving fallbacks.

The mesh store (app/core/model3d.py) and the expression-variant cache key
entries by EXACT outfit signature. A character in a never-rendered
combination therefore served nothing — the 3D client degraded to a pool
placeholder figure, the scene to an unrelated variant image. The serving
fallbacks instead pick the stored entry whose recorded piece combination is
CLOSEST to the worn one; this module is the one scoring rule both use.

Slot-aware on purpose, not plain Jaccard: per slot in the union a same item
scores 1.0, different items in the same slot 0.5, a slot occupied on one
side only 0.0 — same coverage with a different garment is nearer than a
missing garment (plain Jaccard would prefer a topless model over one with
the wrong shirt). Non-piece items match by id. Hidden pieces are collapsed
via the same visibility normalisation the signatures use, so scoring and
signing agree on what counts as "the outfit".
"""

from typing import Dict, List, Optional

from app.core.log import get_logger

logger = get_logger(__name__)


def _visible(pieces: Optional[Dict[str, str]]) -> Dict[str, str]:
    pieces = {k: v for k, v in (pieces or {}).items() if v}
    try:
        from app.core.outfit_renderer import visible_equipped_pieces
        return visible_equipped_pieces(pieces)
    except Exception:  # unreadable items must not break matching — score raw
        return pieces


def outfit_similarity(pieces_a: Optional[Dict[str, str]],
                      items_a: Optional[List[str]],
                      pieces_b: Optional[Dict[str, str]],
                      items_b: Optional[List[str]]) -> float:
    """Similarity of two worn combinations in [0.0, 1.0]; empty vs empty is 1.0."""
    pa, pb = _visible(pieces_a), _visible(pieces_b)
    ia, ib = set(i for i in (items_a or []) if i), set(i for i in (items_b or []) if i)
    slots = set(pa) | set(pb)
    total = len(slots) + len(ia | ib)
    if not total:
        return 1.0
    score = len(ia & ib)
    for slot in slots:
        a, b = pa.get(slot), pb.get(slot)
        if a and b:
            score += 1.0 if a == b else 0.5
    return score / total
