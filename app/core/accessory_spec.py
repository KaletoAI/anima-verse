"""The item-wide description of a thin accessory (Ruling A118, spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 5): ``outfit_piece.jewellery``.

An outfit piece in mode ``accessory`` (``garment_set.ACCESSORY``) carries::

    jewellery: {kind, band, buckle, chain, metal, color?, pendant, side, finger?, sway, earring}

A234 adds ``band.at`` (where a strap goes round: thigh / upper_arm / chest) and ``earring: {style, size_mm}`` (stud /
hoop built on the CPU, ``drop`` = the item-image mesh hung under the lobe — the necklace pendant's job).

Every shape value is item-wide; only what is measured from a body (the neck curve) is per character
(``accessory_build``). ``normalize`` fills the defaults and clamps; ``suggest_kind`` proposes a kind from the slots and
the item's words — a suggestion the Wardrobe shows, never stored silently. Pure: no I/O.
"""
import copy
import re
from typing import Any, Dict, Optional, Tuple

#: The kinds of spec § 5 (generic accessory words).
KINDS: Tuple[str, ...] = ("necklace", "choker", "earrings", "bracelet", "ring", "anklet", "belt", "strap")
#: The kinds built (A216 the necklace, A234 every other kind).
BUILT_KINDS: Tuple[str, ...] = ("necklace", "belt")
CHAIN_STYLES: Tuple[str, ...] = ("cable", "box", "rope", "none")
#: The chain's material (A225): the metals, then the cords (a pendant on a leather cord, a string or a fabric band).
#: The stored key stays ``metal`` (spec § 5).
CORDS: Tuple[str, ...] = ("leather", "string", "fabric")
METALS: Tuple[str, ...] = ("gold", "silver", "rose_gold", "black", "custom") + CORDS
SIDES: Tuple[str, ...] = ("left", "right", "both")
FINGERS: Tuple[str, ...] = ("index", "middle", "ring", "little")
SWAY: Tuple[str, ...] = ("off", "light")
BAND_LAYERS: Tuple[str, ...] = ("auto", "body")
BAND_MATERIALS: Tuple[str, ...] = ("leather", "metal", "fabric", "from_image")
#: Where a strap goes round (A234).
STRAP_AT: Tuple[str, ...] = ("thigh", "upper_arm", "chest")
#: Earring styles (A234): procedural stud / hoop, or ``drop`` from the item image (1 hub job per item).
EARRING_STYLES: Tuple[str, ...] = ("stud", "hoop", "drop")
#: The kinds whose ``band`` is a flat strip (the rest of ``band`` — ``height_cm`` — moves any ring-shaped kind).
BAND_KINDS: Tuple[str, ...] = ("belt", "choker", "strap")
#: The kinds that are a round tube around a limb.
TUBE_KINDS: Tuple[str, ...] = ("anklet", "bracelet", "ring")

#: Spec § 5 defaults (plan Task 3).
DEFAULTS: Dict[str, Any] = {
    "band": {"height_cm": 0.0, "width_cm": 4.0, "layer": "auto", "material": "from_image", "at": "thigh"},
    "earring": {"style": "stud", "size_mm": 6.0},
    "buckle": {"from_image": True, "size_mm": 50.0},
    "chain": {"drop_cm": 4.0, "thickness_mm": 1.5, "style": "cable"},
    "metal": "gold",
    "pendant": None,
    "side": "both",
    "sway": "off",
}
#: The pendant's defaults when one is switched on (spec § 5; built in phase P2).
PENDANT_DEFAULTS: Dict[str, Any] = {"from_image": True, "size_mm": 18.0}
#: A cord is thicker than a chain (A225): its thickness when none is stored.
CORD_THICKNESS_MM = 2.5

#: Clamp ranges ``(low, high)`` of the numeric fields.
RANGES: Dict[str, Tuple[float, float]] = {
    "drop_cm": (0.0, 30.0), "thickness_mm": (0.5, 6.0), "width_cm": (0.5, 12.0), "size_mm": (3.0, 120.0),
    "height_cm": (-30.0, 30.0), "earring_mm": (2.0, 60.0),
}
#: A234: a choker / strap / belt's width when none is stored (a 4 cm belt is a 1.5 cm choker).
KIND_WIDTH_CM: Dict[str, float] = {"belt": 4.0, "choker": 1.5, "strap": 2.5}
#: A234: a bracelet / anklet / ring's thickness when none is stored.
KIND_THICKNESS_MM: Dict[str, float] = {"bracelet": 2.5, "anklet": 1.5, "ring": 2.0}
#: Named drop lengths below the jugular notch (spec § 4).
DROP_PRESETS: Dict[str, float] = {"collar": 4.0, "princess": 10.0, "matinee": 20.0}

#: ``metal`` -> (base colour, roughness, metalness): the metals at metalness 1.0 (plan Global Constraints), the
#: cords (A225) at 0.0.
METAL_PRESETS: Dict[str, Tuple[str, float, float]] = {
    "gold": ("#d4af37", 0.25, 1.0), "silver": ("#c0c0c0", 0.2, 1.0), "rose_gold": ("#b76e79", 0.25, 1.0),
    "black": ("#1c1c1c", 0.35, 1.0),
    "leather": ("#5b3a24", 0.75, 0.0), "string": ("#d9cfb4", 0.9, 0.0), "fabric": ("#2e2a26", 0.85, 0.0),
}
#: The roughness of ``metal: custom``.
CUSTOM_ROUGHNESS = 0.25

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(value: Any, key: str, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    if v != v:   # NaN
        v = float(default)
    lo, hi = RANGES[key]
    return round(min(max(v, lo), hi), 3)


def _choice(value: Any, allowed: Tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def normalize(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The full description of ``raw`` (a stored ``jewellery`` dict): defaults filled in, numbers clamped to
    ``RANGES``, unknown choices replaced by the default. ``ValueError`` for a missing or unknown ``kind``."""
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown accessory kind {kind!r}")
    d = DEFAULTS
    metal = _choice(raw.get("metal"), METALS, d["metal"])
    thick_default = CORD_THICKNESS_MM if metal in CORDS else KIND_THICKNESS_MM.get(kind, d["chain"]["thickness_mm"])
    width_default = KIND_WIDTH_CM.get(kind, d["band"]["width_cm"])
    band_raw = raw.get("band") if isinstance(raw.get("band"), dict) else {}
    chain_raw = raw.get("chain") if isinstance(raw.get("chain"), dict) else {}
    out: Dict[str, Any] = {
        "kind": kind,
        "band": {"height_cm": _num(band_raw.get("height_cm", d["band"]["height_cm"]), "height_cm", 0.0),
                 "width_cm": _num(band_raw.get("width_cm", width_default), "width_cm", width_default),
                 "layer": _choice(band_raw.get("layer"), BAND_LAYERS, d["band"]["layer"]),
                 "material": _choice(band_raw.get("material"), BAND_MATERIALS, d["band"]["material"]),
                 "at": _choice(band_raw.get("at"), STRAP_AT, d["band"]["at"])},
        "chain": {"drop_cm": _num(chain_raw.get("drop_cm", d["chain"]["drop_cm"]), "drop_cm", 4.0),
                  "thickness_mm": _num(chain_raw.get("thickness_mm", thick_default), "thickness_mm", thick_default),
                  "style": _choice(chain_raw.get("style"), CHAIN_STYLES, d["chain"]["style"])},
        "metal": metal,
        "side": _choice(raw.get("side"), SIDES, d["side"]),
        "sway": _choice(raw.get("sway"), SWAY, d["sway"]),
    }
    ear_raw = raw.get("earring") if isinstance(raw.get("earring"), dict) else {}
    out["earring"] = {"style": _choice(ear_raw.get("style"), EARRING_STYLES, d["earring"]["style"]),
                      "size_mm": _num(ear_raw.get("size_mm", d["earring"]["size_mm"]), "earring_mm",
                                      d["earring"]["size_mm"])}
    buckle = raw.get("buckle", d["buckle"])
    if buckle is None:
        out["buckle"] = None
    elif isinstance(buckle, dict):
        out["buckle"] = {"from_image": bool(buckle.get("from_image", True)),
                         "size_mm": _num(buckle.get("size_mm", 50.0), "size_mm", 50.0)}
    else:
        out["buckle"] = copy.deepcopy(d["buckle"])
    pendant = raw.get("pendant")
    if isinstance(pendant, dict):
        out["pendant"] = {"from_image": bool(pendant.get("from_image", True)),
                          "size_mm": _num(pendant.get("size_mm", PENDANT_DEFAULTS["size_mm"]), "size_mm", 18.0)}
        if isinstance(pendant.get("gem_color"), str) and _HEX.match(pendant["gem_color"]):
            out["pendant"]["gem_color"] = pendant["gem_color"].lower()
    else:
        out["pendant"] = None
    if isinstance(raw.get("color"), str) and _HEX.match(raw["color"]):
        out["color"] = raw["color"].lower()
    if raw.get("finger") in FINGERS:
        out["finger"] = raw["finger"]
    return out


def of_item(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The normalized description stored on an outfit piece, None when it has none (or an unknown kind)."""
    piece = (item or {}).get("outfit_piece") if isinstance(item, dict) else None
    raw = piece.get("jewellery") if isinstance(piece, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        return normalize(raw)
    except ValueError:
        return None


def buildable(item: Optional[Dict[str, Any]]) -> bool:
    """Whether ``item`` describes an accessory this version builds: a stored kind in ``BUILT_KINDS``."""
    spec = of_item(item)
    return bool(spec) and spec["kind"] in BUILT_KINDS


#: Word rules of ``suggest_kind``: (kind, regex over the item's name + prompt words), first match wins.
_WORDS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("choker", re.compile(r"\bchoker\b", re.I)),
    ("necklace", re.compile(r"necklace|pendant|\bchain\b|halskette|kette|anh[äa]nger|collier|amulet", re.I)),
    ("earrings", re.compile(r"earring|ear ring|ohrring|ohrstecker|\bstud", re.I)),
    ("bracelet", re.compile(r"bracelet|bangle|armband|armreif", re.I)),
    ("anklet", re.compile(r"anklet|fu[ßs]kette|fusskettchen", re.I)),
    ("ring", re.compile(r"\bring\b|\bsignet|fingerring", re.I)),
    ("belt", re.compile(r"\bbelt\b|g[üu]rtel|sash", re.I)),
    ("strap", re.compile(r"\bstrap|riemen|harness", re.I)),
)


def suggest_kind(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """The kind the Wardrobe proposes for ``item`` (spec § 5 default derivation), None when nothing fits: the item's
    name and prompt words against ``_WORDS``; a ``neck``-only piece is only ever proposed a neck kind (necklace /
    choker). Never stored by this function."""
    if not isinstance(item, dict):
        return None
    words = " ".join(str(item.get(k) or "") for k in ("name", "prompt_fragment"))
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    slots = {str(s) for s in piece.get("slots") or []}
    for kind, pattern in _WORDS:
        if pattern.search(words):
            if slots == {"neck"} and kind not in ("necklace", "choker"):
                continue
            return kind
    return None


def metal_material(spec: Dict[str, Any]) -> Tuple[str, float, float]:
    """``(base colour hex, roughness, metalness)`` of the chain material of ``spec`` (``METAL_PRESETS``; ``custom``
    = ``color`` as a metal)."""
    metal = spec.get("metal") if isinstance(spec, dict) else None
    if metal == "custom":
        color = spec.get("color") if isinstance(spec.get("color"), str) and _HEX.match(spec["color"]) else "#d4af37"
        return color.lower(), CUSTOM_ROUGHNESS, 1.0
    return METAL_PRESETS.get(str(metal), METAL_PRESETS["gold"])


def pendant_on(spec: Optional[Dict[str, Any]]) -> bool:
    """Whether ``spec`` (normalized) asks for a part made from the item image (one ``jewellery_mesh`` job per item):
    the necklace's pendant (A225), the belt's buckle and the earrings' drop (A234)."""
    return image_part_mm(spec) is not None


def image_part_mm(spec: Optional[Dict[str, Any]]) -> Optional[float]:
    """The size (longest side, mm) of the item-image part ``spec`` asks for, None without one (``pendant_on``)."""
    if not spec:
        return None
    kind = spec.get("kind")
    if kind == "belt":
        buckle = spec.get("buckle")
        return float(buckle["size_mm"]) if isinstance(buckle, dict) and buckle.get("from_image", True) else None
    if kind == "earrings":
        if (spec.get("earring") or {}).get("style") != "drop":
            return None
        pendant = spec.get("pendant") if isinstance(spec.get("pendant"), dict) else PENDANT_DEFAULTS
        return float(pendant["size_mm"])
    if kind in ("necklace", "earrings") and isinstance(spec.get("pendant"), dict) \
            and bool(spec["pendant"].get("from_image", True)):
        return float(spec["pendant"]["size_mm"])
    return None


#: A234: what the item-image part of a kind is called (the dialog's and the Build plan's words).
PART_NAMES: Dict[str, str] = {"necklace": "Pendant", "belt": "Buckle", "earrings": "Earring drop"}


def part_name(spec: Optional[Dict[str, Any]]) -> str:
    """The word for ``spec``'s item-image part (``PART_NAMES``; "Pendant" by default)."""
    return PART_NAMES.get(str((spec or {}).get("kind") or ""), "Pendant")


def srgb_to_linear(hex_color: str) -> Tuple[float, float, float]:
    """The glTF ``baseColorFactor`` (linear) of an sRGB hex colour."""
    rgb = [int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)  # type: ignore[return-value]
