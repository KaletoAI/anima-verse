"""Where a painted piece may change the body texture (Ruling A127).

The body retexture worker paints a dressed view onto the base texture. A dressed picture that is
not an exact edit of the base view reads every pose or shading difference as "garment" — on the
face, the scalp, a knee. So the change is restricted to the body regions of the worn PAINTED
pieces' slots: the worker turns the region list into the surface those regions' bones hold on
the rigged twin (skin weights, matched by UV), adds a soft margin, and keeps every texel outside
byte-identical. Head, hands, feet and toes stay locked unless a painted piece's slot names them.

The region list is part of the texture key (``base_body.texture_inputs`` / ``figure.texture_key``),
so a texture painted without it, or for other slots, is a different texture.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

#: Bumped when the region of a slot or the margin changes how a texture is painted.
PAINT_REGION_VERSION = 1
#: Full-strength reach beyond the regions' bones, surface distance in mm; the worker fades it to 0
#: at twice this distance.
PAINT_REGION_MARGIN_MM = 40

#: The worker's body regions (``body_core.BODY_REGIONS``).
BODY_REGIONS = ("head", "neck", "spine", "hips", "shoulder", "upper_arm", "forearm", "hand",
                "upper_leg", "lower_leg", "foot", "toe")
#: Locked unless a slot names them (``body_core.LOCKED_REGIONS``).
LOCKED_REGIONS = ("head", "hand", "foot", "toe")

#: Core clothing slots (``inventory.VALID_PIECE_SLOTS``) -> body regions a piece there may cover.
SLOT_REGIONS: Dict[str, Tuple[str, ...]] = {
    "head": ("head",),
    "neck": ("neck",),
    "underwear_top": ("spine",),
    "underwear_bottom": ("hips",),
    "top": ("spine", "shoulder", "upper_arm", "forearm"),
    "bottom": ("hips", "upper_leg", "lower_leg"),
    "outer": ("spine", "shoulder", "upper_arm", "forearm", "hips", "upper_leg"),
    "legs": ("hips", "upper_leg", "lower_leg", "foot", "toe"),
    "feet": ("lower_leg", "foot", "toe"),
}
#: A slot this table does not know (a species package's own slot): every region but the locked ones.
UNKNOWN_SLOT_REGIONS: Tuple[str, ...] = tuple(r for r in BODY_REGIONS if r not in LOCKED_REGIONS)


def regions_of_slot(slot: str) -> Tuple[str, ...]:
    return SLOT_REGIONS.get(str(slot), UNKNOWN_SLOT_REGIONS)


def paint_region(pieces: Optional[Mapping[str, Any]], painted: Iterable[str]) -> Optional[Dict[str, Any]]:
    """``{"version", "regions", "margin_mm"}`` for the slots of ``pieces`` (``{slot: item id}``) whose
    item is in ``painted``; None when no worn piece is painted."""
    painted_ids = {str(i) for i in painted or ()}
    regions = set()
    for slot, item_id in (pieces or {}).items():
        if item_id and str(item_id).strip() in painted_ids:
            regions.update(regions_of_slot(slot))
    if not regions:
        return None
    return {"version": PAINT_REGION_VERSION, "regions": sorted(regions), "margin_mm": PAINT_REGION_MARGIN_MM}


def worker_arguments(region: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The ``body_retexture.retexture`` keywords of ``region`` (empty without one)."""
    if not region:
        return {}
    return {"paint_region": tuple(region["regions"]), "paint_region_margin_mm": float(region["margin_mm"])}
