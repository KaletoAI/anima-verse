"""The item-wide description of a thin accessory (Ruling A118, spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 5): ``outfit_piece.jewellery``.

An outfit piece in mode ``accessory`` (``garment_set.ACCESSORY``) carries::

    jewellery: {kind, band, buckle, chain, metal, color?, pendant, side, finger?, sway}

Every shape value is item-wide; only what is measured from a body (the neck curve) is per character
(``accessory_build``). ``normalize`` fills the defaults and clamps; ``suggest_kind`` proposes a kind from the slots and
the item's words — a suggestion the Wardrobe shows, never stored silently. Pure: no I/O.
"""
import copy
import re
from typing import Any, Dict, Optional, Tuple

#: The kinds of spec § 5 (generic accessory words).
KINDS: Tuple[str, ...] = ("necklace", "choker", "earrings", "bracelet", "ring", "anklet", "belt", "strap")
#: The kinds built so far (phase P1: the necklace chain). Any other kind is stored but not built yet.
BUILT_KINDS: Tuple[str, ...] = ("necklace",)
CHAIN_STYLES: Tuple[str, ...] = ("cable", "box", "rope", "none")
METALS: Tuple[str, ...] = ("gold", "silver", "rose_gold", "black", "custom")
SIDES: Tuple[str, ...] = ("left", "right", "both")
FINGERS: Tuple[str, ...] = ("index", "middle", "ring", "little")
SWAY: Tuple[str, ...] = ("off", "light")
BAND_LAYERS: Tuple[str, ...] = ("auto", "body")
BAND_MATERIALS: Tuple[str, ...] = ("leather", "metal", "fabric", "from_image")

#: Spec § 5 defaults (plan Task 3).
DEFAULTS: Dict[str, Any] = {
    "band": {"height_cm": 0.0, "width_cm": 4.0, "layer": "auto", "material": "from_image"},
    "buckle": {"from_image": True, "size_mm": 50.0},
    "chain": {"drop_cm": 4.0, "thickness_mm": 1.5, "style": "cable"},
    "metal": "gold",
    "pendant": None,
    "side": "both",
    "sway": "off",
}
#: The pendant's defaults when one is switched on (spec § 5; built in phase P2).
PENDANT_DEFAULTS: Dict[str, Any] = {"from_image": True, "size_mm": 18.0}

#: Clamp ranges ``(low, high)`` of the numeric fields.
RANGES: Dict[str, Tuple[float, float]] = {
    "drop_cm": (0.0, 30.0), "thickness_mm": (0.5, 6.0), "width_cm": (0.5, 12.0), "size_mm": (3.0, 120.0),
    "height_cm": (-30.0, 30.0),
}
#: Named drop lengths below the jugular notch (spec § 4).
DROP_PRESETS: Dict[str, float] = {"collar": 4.0, "princess": 10.0, "matinee": 20.0}

#: ``metal`` -> (base colour, roughness); metalness is always 1.0 (plan Global Constraints).
METAL_PRESETS: Dict[str, Tuple[str, float]] = {
    "gold": ("#d4af37", 0.25), "silver": ("#c0c0c0", 0.2), "rose_gold": ("#b76e79", 0.25),
    "black": ("#1c1c1c", 0.35),
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
    band_raw = raw.get("band") if isinstance(raw.get("band"), dict) else {}
    chain_raw = raw.get("chain") if isinstance(raw.get("chain"), dict) else {}
    out: Dict[str, Any] = {
        "kind": kind,
        "band": {"height_cm": _num(band_raw.get("height_cm", d["band"]["height_cm"]), "height_cm", 0.0),
                 "width_cm": _num(band_raw.get("width_cm", d["band"]["width_cm"]), "width_cm", 4.0),
                 "layer": _choice(band_raw.get("layer"), BAND_LAYERS, d["band"]["layer"]),
                 "material": _choice(band_raw.get("material"), BAND_MATERIALS, d["band"]["material"])},
        "chain": {"drop_cm": _num(chain_raw.get("drop_cm", d["chain"]["drop_cm"]), "drop_cm", 4.0),
                  "thickness_mm": _num(chain_raw.get("thickness_mm", d["chain"]["thickness_mm"]), "thickness_mm", 1.5),
                  "style": _choice(chain_raw.get("style"), CHAIN_STYLES, d["chain"]["style"])},
        "metal": _choice(raw.get("metal"), METALS, d["metal"]),
        "side": _choice(raw.get("side"), SIDES, d["side"]),
        "sway": _choice(raw.get("sway"), SWAY, d["sway"]),
    }
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


def metal_material(spec: Dict[str, Any]) -> Tuple[str, float]:
    """``(base colour hex, roughness)`` of the metal of ``spec`` (``METAL_PRESETS``; ``custom`` = ``color``)."""
    metal = spec.get("metal") if isinstance(spec, dict) else None
    if metal == "custom":
        color = spec.get("color") if isinstance(spec.get("color"), str) and _HEX.match(spec["color"]) else "#d4af37"
        return color.lower(), CUSTOM_ROUGHNESS
    return METAL_PRESETS.get(str(metal), METAL_PRESETS["gold"])


def srgb_to_linear(hex_color: str) -> Tuple[float, float, float]:
    """The glTF ``baseColorFactor`` (linear) of an sRGB hex colour."""
    rgb = [int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)  # type: ignore[return-value]
