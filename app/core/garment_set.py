"""Which items a character wears or holds as their own garment mesh
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``).

Two kinds of item become a fitted garment mesh on a base-body character:

- ``hair`` — the hair garment (category ``garment``, ``garment.kind ==
  "hair"``), worn through the profile state key ``equipped_mesh_pieces`` and
  owned through ``item.owner`` (``garment_hair``);
- ``clothing`` — an ordinary ``outfit_piece`` whose ``outfit_piece.own_mesh``
  flag is set. It stays an outfit piece worn through ``equipped_pieces`` (2D
  renders, the outfit signature and the chat prompts never see the flag);
  the flag lives on the ITEM, so it applies to every wearer, and a wearer is
  whoever holds it (inventory) or wears it. Its fits are per wearer, under
  ``characters/<n>/garments/`` like the hair fits.

Only characters on the base-body pipeline (``base_body.is_base_pipeline``)
wear garments; everyone else ignores the flag (``worn_garments`` is empty).
"""
from typing import Any, Dict, Iterable, List, Optional

HAIR = "hair"
CLOTHING = "clothing"


def garment_kind_of(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """``"hair"`` for a hair garment, ``"clothing"`` for an outfit piece with
    the own-mesh flag, else None."""
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    if category == "garment":
        kind = str((item.get("garment") or {}).get("kind") or "")
        return HAIR if kind == HAIR else None
    if category == "outfit_piece" and (item.get("outfit_piece") or {}).get("own_mesh") is True:
        return CLOTHING
    return None


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _ids(mapping: Any) -> List[str]:
    if not isinstance(mapping, dict):
        return []
    return [str(v).strip() for v in mapping.values() if v and str(v).strip()]


def _flagged(item_ids: Iterable[str]) -> List[str]:
    from app.models.inventory import get_item
    return sorted({iid for iid in item_ids if garment_kind_of(get_item(iid)) == CLOTHING})


def holds(character_name: str, item_id: str, *,
          profile: Optional[Dict[str, Any]] = None) -> bool:
    """The character has the item in the inventory or wears it (as an outfit
    piece or a mesh piece)."""
    if not isinstance(item_id, str) or not item_id:
        return False
    from app.models.inventory import has_item
    if has_item(character_name, item_id):
        return True
    profile = _profile_of(character_name, profile)
    return item_id in _ids(profile.get("equipped_pieces")) or item_id in _ids(
        profile.get("equipped_mesh_pieces"))


def worn_garments(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                  pieces: Optional[Dict[str, str]] = None) -> List[str]:
    """Item ids of the garments the character wears, sorted and deduped: the
    mesh pieces of ``equipped_mesh_pieces`` (hair) plus the own-mesh outfit
    pieces of ``pieces`` (default: the profile's ``equipped_pieces``; a
    multi-slot piece once). Empty off the base-body pipeline."""
    from app.core import base_body
    profile = _profile_of(character_name, profile)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return []
    worn = set(_ids(profile.get("equipped_mesh_pieces")))
    worn.update(_flagged(_ids(profile.get("equipped_pieces") if pieces is None else pieces)))
    return sorted(worn)


def held_clothing(character_name: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Own-mesh outfit pieces the character holds or wears, sorted — the
    keep set of the garment cache GC (a dress in the wardrobe keeps its fit).
    Not gated on the pipeline: switching it off and on again must not cost
    the fits."""
    from app.models.inventory import _load_inventory
    entries = _load_inventory(character_name).get("inventory") or []
    ids = {str(e.get("item_id") or "").strip() for e in entries}
    ids.update(_ids(_profile_of(character_name, profile).get("equipped_pieces")))
    ids.discard("")
    return _flagged(ids)
