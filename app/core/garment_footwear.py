"""Footwear as its own mesh — an outfit piece flagged ``outfit_piece.own_mesh``
worn in slot ``feet`` (plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``;
spec ``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.1, § 5.6).

The kind module of garment kind ``footwear`` (``garment_set.FOOTWEAR``),
method ``shoe`` (``garment_store.SHOE``). The steps ``source → empty →
cutout → mesh → insole`` are per ITEM (``footwear_source``, world-scoped);
only ``fit`` is per wearer and body (``footwear_fit``). The fingerprint has
no base in it: a base change makes a fit stale, never the source.
"""
from typing import Any, Dict

KIND = "footwear"
#: Profile key of the per-fit width cap overrides: ``{item_id: float}``.
WIDTH_CAP_KEY = "footwear_width_cap"


def width_cap(profile: Dict[str, Any], item_id: str) -> float:
    """The width cap of the character's fit of ``item_id``: the profile
    override (``WIDTH_CAP_KEY``) clamped to ``footwear_fit.WIDTH_CAP_MIN`` ..
    ``footwear_fit.WIDTH_CAP``, the cap itself without a valid one."""
    from app.core import footwear_fit
    caps = profile.get(WIDTH_CAP_KEY) if isinstance(profile, dict) else None
    value = caps.get(item_id) if isinstance(caps, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return footwear_fit.WIDTH_CAP
    return round(min(footwear_fit.WIDTH_CAP, max(footwear_fit.WIDTH_CAP_MIN, float(value))), 4)


def fsig_inputs(character_name: str, item: Dict[str, Any], *, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The footwear fingerprint inputs: the item's current source ``ssig``,
    the insole analysis version, the width cap and the fit version — no base
    signature, no base images, no base model."""
    from app.core import footwear_insole, footwear_source, garment_fit
    item_id = str(item.get("id") or "")
    return {"ssig": footwear_source.current_ssig(item_id), "insole_version": footwear_insole.INSOLE_VERSION,
            "width_cap": width_cap(profile, item_id), "fit_version": garment_fit.FIT_VERSION[KIND]}
