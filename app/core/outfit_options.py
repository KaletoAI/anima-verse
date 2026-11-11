"""Per-outfit options beside the worn pieces — today one: the boot hem (boots spec
``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md`` § 8, § 20; plan Task 10).

**Live state**: the profile key ``equipped_options`` = ``{"boot_hem": "tucked" | "over" | null}`` beside
``equipped_pieces``. ``null`` means ``over`` for every shaft class (§ 20.2: no per-class default) — the trousers
fall over the boot shaft; ``tucked`` is the explicit per-outfit choice: the trouser leg is cut inside the collar
(``garment_layers``). Written through ``set_boot_hem`` under the profile lock; the routes
``GET`` / ``POST /characters/{name}/outfit-options`` (admin and the character's player, like an equip).

**When the choice exists** (``hem_eligible`` / ``hem_applicable``): a worn boot — a footwear fit whose record is
SPLIT (``split.is_boot``) with a shaft class other than ``none`` — and a worn own-mesh ``bottom`` piece with an
accepted fit that is no skirt (the fit's ``report.skirt``, ``garment_fit.is_skirt``). Painted trousers are never
"over" (§ 20.1): with them the boot is simply outside the painted shin and nothing is offered. A skirt or a dress
is layered over the shaft by the ordinary layer order and has no mode.

**Saved outfits** (``outfits_sets``): the ``options`` key ``{boot_hem}`` rides in the row's ``meta``;
``add_character_outfit`` stores what it is given, a new set without ``options`` the live value;
``apply_outfit_set`` restores it (an old row without ``options`` applies ``null``).

The mode is an ASSEMBLY input, not an outfit-signature input (§ 8.2): it changes neither the bare outfit model nor
the painted body — only the trousers' layered fit — so ``garment_assembly._wanted`` reads it from the profile and
``_state`` carries it, and a toggle rebuilds the assembly in seconds.
"""
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("outfit_options")

#: The profile key holding the per-outfit options, and the boot hem key inside it.
OPTIONS_KEY = "equipped_options"
BOOT_HEM_KEY = "boot_hem"
#: The two hem modes; ``None`` in the profile reads as ``HEM_DEFAULT``.
HEM_MODES: Tuple[str, ...] = ("tucked", "over")
HEM_DEFAULT = "over"
#: The outfit-piece slot of the trousers the hem applies to.
TROUSERS_SLOT = "bottom"
#: The Wardrobe warning when a tucked pair did not fit into the shaft (``garment_layers`` fallback ``too_wide``).
TOO_WIDE_WARNING = "{trousers}: too wide to tuck into {boot} — worn over it"


def boot_hem(profile: Optional[Dict[str, Any]]) -> str:
    """The boot hem mode of a profile: ``tucked`` or ``over`` (a missing / null / unknown value is ``over``)."""
    options = (profile or {}).get(OPTIONS_KEY)
    mode = options.get(BOOT_HEM_KEY) if isinstance(options, dict) else None
    return mode if mode in HEM_MODES else HEM_DEFAULT


def normalise_hem(mode: Any) -> Optional[str]:
    """``tucked`` / ``over`` / ``None`` for a value that is one of those (or null / ""); ValueError otherwise."""
    if mode is None or mode == "":
        return None
    if isinstance(mode, str) and mode in HEM_MODES:
        return mode
    raise ValueError(f"boot_hem must be one of {', '.join(HEM_MODES)} or null")


def set_boot_hem(character_name: str, mode: Optional[str]) -> bool:
    """Store the boot hem mode (``tucked`` / ``over`` / ``None`` = the default) in the profile under the profile
    lock; True when saved. ValueError for another value."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    value = normalise_hem(mode)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)
        if not profile:
            return False
        options = dict(profile.get(OPTIONS_KEY) or {}) if isinstance(profile.get(OPTIONS_KEY), dict) else {}
        options[BOOT_HEM_KEY] = value
        profile[OPTIONS_KEY] = options
        return bool(save_character_profile(character_name, profile))


def apply_saved_options(character_name: str, outfit: Dict[str, Any]) -> bool:
    """Apply a saved set's ``options`` to the profile — the boot hem; a set without them (or with an unknown
    value) stores null = the default. Called by the apply-outfit-set routes inside their profile lock (the lock
    is re-entrant). True when saved."""
    options = outfit.get("options") if isinstance(outfit.get("options"), dict) else {}
    try:
        mode = normalise_hem(options.get(BOOT_HEM_KEY))
    except ValueError:
        mode = None
    return set_boot_hem(character_name, mode)


def is_boot_record(record: Optional[Dict[str, Any]]) -> bool:
    """Whether a footwear fit record is a split boot with a shaft class other than ``none`` — a fit that
    serves a shaft node the trousers can be tucked into or layered over."""
    if not isinstance(record, dict):
        return False
    split = record.get("split") if isinstance(record.get("split"), dict) else {}
    shaft = record.get("shaft") if isinstance(record.get("shaft"), dict) else {}
    cls = shaft.get("class")
    return bool(split.get("is_boot")) and isinstance(cls, str) and cls != "none"


def is_skirt_record(record: Optional[Dict[str, Any]]) -> bool:
    """Whether a clothing fit record says the piece hangs as a skirt (``report.skirt``, ``garment_fit.is_skirt``)."""
    if not isinstance(record, dict):
        return False
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    return bool(report.get("skirt"))


def hem_eligible(boot_record: Optional[Dict[str, Any]],
                 trousers_record: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """``(applicable, reason)`` of a boot fit record and a trousers fit record (either may be None): the one
    rule behind ``hem_applicable`` and the assembly (``garment_assembly._wanted``)."""
    if not is_boot_record(boot_record):
        return False, "no boot worn (a footwear fit split at the ankle with a shaft)"
    if not isinstance(trousers_record, dict):
        return False, "no own-mesh trousers worn with an accepted fit (painted trousers stay inside the boot)"
    if is_skirt_record(trousers_record):
        return False, "the bottom piece is a skirt or a dress — layered by the ordinary layer order"
    return True, ""


def hem_applicable(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the Wardrobe shows: ``{applicable, boot_item, trousers_item, reason, mode}`` for the pieces the
    character wears NOW — the feet piece with a boot fit on the current base model and the own-mesh ``bottom``
    piece with an accepted, non-skirt fit there. ``mode`` is the stored choice (``boot_hem``) either way."""
    from app.core import base_body, garment_store
    from app.core.garment_set import FOOTWEAR_SLOT
    from app.models.inventory import get_item
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    out: Dict[str, Any] = {"applicable": False, "boot_item": None, "trousers_item": None, "reason": "",
                           "mode": boot_hem(profile)}
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    feet = str(pieces.get(FOOTWEAR_SLOT) or "")
    bottom = str(pieces.get(TROUSERS_SLOT) or "")
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        out["reason"] = "no base model"
        return out

    def own_mesh_fit(item_id: str) -> Optional[Dict[str, Any]]:
        if not item_id:
            return None
        item = get_item(item_id) or {}
        piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
        if not piece.get("own_mesh"):
            return None
        try:
            fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
        except ValueError:
            return None
        return fit[1] if fit else None
    boot_rec = own_mesh_fit(feet)
    trousers_rec = own_mesh_fit(bottom)
    ok, reason = hem_eligible(boot_rec, trousers_rec)
    out.update(applicable=ok, reason=reason, boot_item=feet if is_boot_record(boot_rec) else None,
               trousers_item=bottom if (ok and bottom) else None)
    return out
