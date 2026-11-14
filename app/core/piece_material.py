"""The material of a worn piece's own mesh (Ruling A36): ``outfit_piece.material``.

A piece made with its own mesh is grafted onto the figure with the generator's material: its base colour and — since
A36 — its predicted roughness map (``glb_mesh.GarmentMesh.mr_image``). A leather jacket still read as matte cloth,
so a piece carries a material choice ``MATERIALS``:

- ``auto`` (the default, no key stored) guesses a preset from the item's name, prompt fragment and description
  (``guess``: a small keyword table, typo-tolerant by ``difflib`` — "lether" is leather — no LLM); no match keeps
  the generator's roughness map unchanged;
- a preset (``leather`` · ``denim`` · ``cotton`` · ``knit`` · ``rubber`` · ``metal``) sets fixed PBR values
  (``PRESETS``) and drops the generator's map: the roughness and metallic factors, plus a light clear coat for
  leather and a sheen for cloth (``KHR_materials_clearcoat`` / ``KHR_materials_sheen`` — three.js GLTFLoader makes a
  ``MeshPhysicalMaterial`` of both, in the 3D client and the Game-Admin viewer alike).

Applied ONLY at the assembly (``garment_assembly``: ``overrides`` as ``glb_mesh.graft`` ``material_overrides`` on
both tiers), on the CPU — never a hub job, never a refit. The effective preset enters the assembly's identity
(``state_key`` in the sidecar ``garments`` entry), so a change re-assembles the figure on the next delivery; a
choice that resolves to the same preset ("auto (→ leather)" vs. "leather") changes nothing.

A preset with a metallic factor marks its material ``extras.explicit_metallic`` (three.js: ``userData``): the
viewers force metalness 0 on every other figure material (the generator's MR maps claim metal on skin and cloth) but
keep it there.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

AUTO = "auto"
#: The presets, in the order a tie between two guesses is decided by.
PRESET_NAMES: Tuple[str, ...] = ("leather", "denim", "knit", "cotton", "rubber", "metal")
MATERIALS: Tuple[str, ...] = (AUTO,) + PRESET_NAMES
#: Bumped whenever a preset's values change: every assembly carrying a preset is rebuilt once.
PRESETS_VERSION = 1

#: The fixed PBR values of each preset: ``roughness`` / ``metallic`` factors, optional ``clearcoat`` (factor,
#: roughness) and ``sheen`` (colour factor, roughness).
PRESETS: Dict[str, Dict[str, Any]] = {
    "leather": {"roughness": 0.45, "metallic": 0.0, "clearcoat": (0.3, 0.4)},
    "denim": {"roughness": 0.9, "metallic": 0.0, "sheen": (0.2, 0.8)},
    "knit": {"roughness": 0.95, "metallic": 0.0, "sheen": (0.3, 0.9)},
    "cotton": {"roughness": 0.95, "metallic": 0.0, "sheen": (0.15, 0.9)},
    "rubber": {"roughness": 0.6, "metallic": 0.0},
    "metal": {"roughness": 0.3, "metallic": 1.0},
}

#: Keywords per preset, lower case (English and German). A keyword of 5 letters or more also matches inside a
#: compound ("Lederjacke") and, of 6 or more, a word within ``FUZZY_RATIO`` of it ("lether").
KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "leather": ("leather", "leder", "suede", "wildleder", "nappa", "lambskin", "biker"),
    "denim": ("denim", "jeans", "jean", "chambray"),
    "knit": ("knit", "knitted", "strick", "wool", "wolle", "woollen", "cashmere", "kaschmir", "mohair",
             "sweater", "pullover", "cardigan", "jumper", "beanie"),
    "cotton": ("cotton", "baumwolle", "linen", "leinen", "flannel", "flanell", "jersey", "canvas", "hoodie",
               "t-shirt", "tshirt", "tee"),
    "rubber": ("rubber", "gummi", "neoprene", "neopren", "vinyl", "wellies", "wellington", "gummistiefel"),
    "metal": ("metal", "metall", "steel", "stahl", "iron", "eisen", "chainmail", "kettenhemd", "plate armor",
              "plate armour", "chrome"),
}
#: Words that contain a keyword but name no such material ("metallic" is a sheen of colour, not metal).
NOT_MATERIAL = frozenset({"metallic", "metallisch", "metallisches", "metallischer", "metallische"})
#: ``difflib.SequenceMatcher`` ratio a word needs to count as a typo of a keyword of 6 letters or more.
FUZZY_RATIO = 0.83
#: Weight of a keyword hit per text: the name says most.
_FIELD_WEIGHTS = (("name", 3), ("prompt_fragment", 2), ("description", 1))
_WORD_RE = re.compile(r"[a-zäöüß]+(?:-[a-zäöüß]+)*")


def clean(raw: Any) -> Optional[str]:
    """A stored ``outfit_piece.material``: a preset name, else None (the caller stores no key — the piece is
    ``auto``, never ``auto`` written down)."""
    return raw if isinstance(raw, str) and raw in PRESET_NAMES else None


def choice_of(item: Optional[Dict[str, Any]]) -> str:
    """The piece's choice: its stored preset, else ``auto``."""
    return clean(((item or {}).get("outfit_piece") or {}).get("material")) or AUTO


def _hits(text: str) -> Dict[str, int]:
    """``{preset: number of keyword hits}`` in ``text``."""
    low = (text or "").lower()
    words = _WORD_RE.findall(low)
    out: Dict[str, int] = {}
    for preset, keywords in KEYWORDS.items():
        n = 0
        for keyword in keywords:
            if " " in keyword:
                n += low.count(keyword)
                continue
            for word in words:
                if word in NOT_MATERIAL:
                    continue
                if word == keyword or (len(keyword) >= 5 and keyword in word):
                    n += 1
                elif len(keyword) >= 6 and abs(len(word) - len(keyword)) <= 2 \
                        and difflib.SequenceMatcher(None, word, keyword).ratio() >= FUZZY_RATIO:
                    n += 1
        if n:
            out[preset] = n
    return out


def guess(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """The preset ``auto`` resolves to: the one with the most weighted keyword hits in the item's name (×3),
    prompt fragment (×2) and description (×1); a tie goes to the earlier preset of ``PRESET_NAMES``; None without
    a hit."""
    score: Dict[str, int] = {}
    for field, weight in _FIELD_WEIGHTS:
        for preset, n in _hits(str((item or {}).get(field) or "")).items():
            score[preset] = score.get(preset, 0) + n * weight
    if not score:
        return None
    return max(PRESET_NAMES, key=lambda p: (score.get(p, 0), -PRESET_NAMES.index(p)))


def resolve(item: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """``(choice, preset)``: the stored choice and the preset it takes effect as — the choice itself, or the
    ``guess`` of ``auto`` (None: the generator's roughness map stays)."""
    choice = choice_of(item)
    return choice, (guess(item) if choice == AUTO else choice)


def state_key(item: Optional[Dict[str, Any]]) -> str:
    """The assembly identity of the piece's material: ``<preset>.v<PRESETS_VERSION>`` or ``map`` (no preset)."""
    preset = resolve(item)[1]
    return f"{preset}.v{PRESETS_VERSION}" if preset else "map"


def overrides(preset: Optional[str]) -> Optional[Dict[str, Any]]:
    """The ``glb_mesh.graft`` ``material_overrides`` of ``preset``: fixed factors, the generator's map dropped,
    the extensions of a clear coat / sheen and ``extras {anima_material, explicit_metallic}``; None for no
    preset (the graft keeps the map)."""
    spec = PRESETS.get(preset or "")
    if spec is None:
        return None
    extensions: Dict[str, Any] = {}
    if spec.get("clearcoat"):
        factor, rough = spec["clearcoat"]
        extensions["KHR_materials_clearcoat"] = {"clearcoatFactor": factor, "clearcoatRoughnessFactor": rough}
    if spec.get("sheen"):
        colour, rough = spec["sheen"]
        extensions["KHR_materials_sheen"] = {"sheenColorFactor": [colour, colour, colour],
                                             "sheenRoughnessFactor": rough}
    out: Dict[str, Any] = {
        "pbrMetallicRoughness": {"metallicRoughnessTexture": None, "roughnessFactor": spec["roughness"],
                                 "metallicFactor": spec["metallic"]},
        "extras": {"anima_material": preset, "explicit_metallic": spec["metallic"] > 0},
    }
    if extensions:
        out["extensions"] = extensions
    return out


def describe(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The Wardrobe's material select of one piece: ``{choice, guess}`` — ``guess`` the preset ``auto`` takes
    effect as ("" = the generator's roughness map)."""
    return {"choice": choice_of(item), "guess": guess(item) or ""}


def options() -> List[str]:
    """The select's values in order."""
    return list(MATERIALS)
