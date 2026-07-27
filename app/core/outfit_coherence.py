"""Which outfit pieces GO TOGETHER — over the pieces' own ``outfit_types``.

The tags were always there; what was missing is a vocabulary and a rule. Both
live here:

* the vocabulary is CLOSED (``CANONICAL_OUTFIT_TYPES``) and enforced at every
  save path — an unknown tag is dropped with a warning instead of quietly
  kept, otherwise the wild growth simply starts again. Several tags per piece
  are explicitly fine (sneakers = casual + sport);
* a combination is COHERENT when its visible pieces share at least one tag.

Two details make the rule usable rather than pedantic. Visibility is the same
normalisation the render cache keys on (``visible_equipped_pieces``): boxers
under trousers cannot clash with anything, because nobody sees them. And an
UNTAGGED piece is a wildcard — it never makes a combination incoherent. That
keeps the whole existing inventory working and lets a deliberately neutral
piece (a plain white shirt) belong everywhere.
"""

from typing import Any, Dict, Iterable, List, Set

from app.core.log import get_logger

logger = get_logger(__name__)

#: The closed vocabulary. Anything else is dropped on save.
CANONICAL_OUTFIT_TYPES = [
    "casual", "business", "formal", "clubwear",
    "sport", "beach", "intimate", "home",
]

#: Old spellings that map onto a canonical tag instead of being dropped.
ALIASES = {
    "beach/pool": "beach",
    "pool": "beach",
    "elegant": "formal",
}

#: What a piece gets when the creating LLM produced nothing usable — a
#: documented fallback, so an untagged piece cannot come into being any more.
DEFAULT_OUTFIT_TYPE = "casual"


def normalize_outfit_types(raw: Any) -> List[str]:
    """Clean a tag list: lowercase/trim, resolve aliases, drop what is not in
    the vocabulary (with a warning), de-duplicate, keep the input order.

    Order is kept because the first tag reads as the primary one in the UI;
    de-duplication keeps the first occurrence.
    """
    out: List[str] = []
    dropped: List[str] = []
    for entry in (raw or []):
        tag = str(entry or "").strip().lower()
        if not tag:
            continue
        tag = ALIASES.get(tag, tag)
        if tag not in CANONICAL_OUTFIT_TYPES:
            dropped.append(str(entry))
            continue
        if tag not in out:
            out.append(tag)
    if dropped:
        logger.warning("outfit_types: dropped unknown tag(s) %s (vocabulary: %s)",
                       dropped, ", ".join(CANONICAL_OUTFIT_TYPES))
    return out


def _types_of(item_id: str) -> List[str]:
    """The (already normalised) tags of one piece; [] when it has none or the
    item is gone — both mean "wildcard" to the rule below."""
    from app.models.inventory import get_item
    try:
        item = get_item(item_id) or {}
    except Exception:
        return []
    return list(((item.get("outfit_piece") or {}).get("outfit_types")) or [])


def visible_types(pieces: Dict[str, str]) -> List[List[str]]:
    """Tag lists of the VISIBLE pieces of a combination, one entry per piece.

    Covered slots drop out via the render normalisation — a piece nobody sees
    cannot clash with anything.
    """
    try:
        from app.core.outfit_renderer import visible_equipped_pieces
        visible = visible_equipped_pieces(pieces or {})
    except Exception:
        visible = {k: v for k, v in (pieces or {}).items() if v}
    return [_types_of(iid) for iid in visible.values() if iid]


def common_types(pieces: Dict[str, str]) -> Set[str]:
    """The tags ALL tagged visible pieces share — the reason a combination is
    coherent, for a log line or a tooltip. Empty set when they share none;
    with no tagged piece at all it is the whole vocabulary (everything goes).
    """
    tagged = [set(t) for t in visible_types(pieces) if t]
    if not tagged:
        return set(CANONICAL_OUTFIT_TYPES)
    common = tagged[0]
    for other in tagged[1:]:
        common &= other
    return common


def is_coherent(pieces: Dict[str, str]) -> bool:
    """Do the visible pieces of this combination go together?

    True when every TAGGED visible piece shares at least one tag with all the
    others. Untagged pieces are wildcards; a combination of nothing but
    untagged pieces is coherent, and so is a single visible piece.
    """
    return bool(common_types(pieces))


def coherent_pieces(combos: Iterable[Dict[str, str]]) -> Iterable[Dict[str, str]]:
    """Filter an enumeration lazily — the batch feeds a generator of a
    million combinations through here."""
    for pieces in combos:
        if is_coherent(pieces):
            yield pieces
