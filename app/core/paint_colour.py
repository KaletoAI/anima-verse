"""The colour of a painted piece (Ruling A148) — the hair colour's counterpart for mode ``painted``.

A painted piece is painted into the body texture by the retexture worker from the dressed views; its colour is
whatever the image model drew. This module lets a person recolour it afterwards, on the CPU and without a hub job:

- Stored per character and piece on the profile (``SETTINGS_KEY``: ``{item_id: {"hex": "#rrggbb", "strength":
  0..1}}``); a piece without an entry keeps the painted colours. ``set_colour`` is the one writer (profile lock).
- Applied when the outfit model is made (``base_body`` after the paint, ``apply``): to the piece's painted texels
  only. Mask = the texels the paint changed against the plain body's texture (the worker's input atlas) — and, when
  more than one painted piece shares the outfit's texture, intersected with this piece's body regions
  (``paint_region.regions_of_slot``) rasterised in UV space from the model's skin weights (``region_mask``). Every
  texel outside the mask keeps its bytes.
- The recolour keeps the shading: in CIELAB every masked texel moves by ``strength * (target - median)`` — the
  median of the piece's texels lands on the chosen colour at strength 1 and every texel keeps its offset from it
  (folds, seams, shadow), the hair's ``garment_hairdeck._transfer_colours`` rule with a strength.
- NOT part of the texture key: the stored painted body (``model3d/texture/<tex>.glb``) stays the worker's output and
  is reused; the OUTFIT model records the colours it was made with (``RECORD_KEY``) and is stale when they differ
  from the wanted ones (``base_body.figure_stale``) — a change makes only the paint/assembly due (CPU, 0 hub jobs).
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np

#: Profile key: ``{item_id: {"hex": "#rrggbb", "strength": float}}``.
SETTINGS_KEY = "garment_paint_colours"
#: Outfit model sidecar key: the colours it was painted with (``wanted`` format; absent = none).
RECORD_KEY = "paint_colours"
#: Its proof (per piece: texels, median before/after, ΔE).
PROOF_KEY = "paint_colour_proof"
DEFAULT_STRENGTH = 1.0
#: Bumped when the recolour rule changes how a texel is coloured (part of the record: a model made by another
#: rule is stale).
VERSION = 1
#: A vertex belongs to a piece's regions when those regions' bones hold at least this share of its skin weight
#: (``body_core.PAINT_REGION_MAJORITY``).
REGION_MAJORITY = 0.5
#: Texels the region mask grows by in the atlas (the worker's margin and gutters lie just outside the core).
REGION_DILATE_PX = 6
#: Swatches the colour row offers (sRGB hex), with their English names.
PRESETS: Tuple[Tuple[str, str], ...] = (
    ("#f2ead8", "Cream"), ("#ffffff", "White"), ("#1c1c1c", "Black"), ("#7a7a7a", "Grey"),
    ("#2f4a7a", "Navy"), ("#8a1f24", "Burgundy"), ("#3f6b3a", "Forest green"), ("#6b4428", "Brown"),
    ("#c9a227", "Mustard"), ("#d98ba0", "Rose"),
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --- storage -------------------------------------------------------------------------------------------------------

def normalise(raw: Any) -> Optional[Dict[str, Any]]:
    """``{"hex", "strength"}`` of a stored or posted value, None when it sets no colour."""
    if not isinstance(raw, Mapping):
        return None
    hex_colour = str(raw.get("hex") or "").strip().lower()
    if not _HEX_RE.match(hex_colour):
        return None
    try:
        strength = float(raw.get("strength", DEFAULT_STRENGTH))
    except (TypeError, ValueError):
        strength = DEFAULT_STRENGTH
    if not np.isfinite(strength):
        strength = DEFAULT_STRENGTH
    return {"hex": hex_colour, "strength": round(min(1.0, max(0.0, strength)), 2)}


def colour_of(profile: Optional[Dict[str, Any]], item_id: str) -> Optional[Dict[str, Any]]:
    """The stored colour of ``item_id`` on ``profile``, None = the painted colours."""
    stored = profile.get(SETTINGS_KEY) if isinstance(profile, dict) else None
    return normalise(stored.get(item_id)) if isinstance(stored, dict) else None


def validate(hex_colour: Any, strength: Any) -> Optional[Dict[str, Any]]:
    """A posted colour: ``""`` / None clears (None returned); else ``normalise`` — ValueError when it is no
    ``#rrggbb`` or the strength is not a number in 0..1."""
    text = str(hex_colour or "").strip()
    if not text:
        return None
    if not _HEX_RE.match(text):
        raise ValueError("The colour must be #rrggbb")
    try:
        value = float(DEFAULT_STRENGTH if strength is None else strength)
    except (TypeError, ValueError):
        raise ValueError("The strength must be a number from 0 to 1") from None
    if not np.isfinite(value) or value < 0 or value > 1:
        raise ValueError("The strength must be a number from 0 to 1")
    return normalise({"hex": text, "strength": value})


def set_colour(character_name: str, item_id: str, hex_colour: Any, strength: Any = None) -> bool:
    """Store (or with ``hex_colour`` "" clear) the colour of a clothing piece of the character — one
    read-modify-write under the profile lock. Runs nothing: the outfit model becomes due (module docstring).
    ValueError for an invalid value or an item that is no clothing piece of the character."""
    from app.core import garment_set, garments
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    value = validate(hex_colour, strength)
    _item, kind = garments._item(character_name, item_id)
    if kind != garment_set.CLOTHING:
        raise ValueError("A paint colour is for clothing pieces")
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        stored = dict(profile.get(SETTINGS_KEY)) if isinstance(profile.get(SETTINGS_KEY), dict) else {}
        if colour_of(profile, item_id) == value:
            return True
        if value is None:
            stored.pop(item_id, None)
        else:
            stored[item_id] = value
        if stored:
            profile[SETTINGS_KEY] = stored
        else:
            profile.pop(SETTINGS_KEY, None)
        saved = bool(save_character_profile(character_name, profile))
    if saved:
        from app.core import figure
        figure.invalidate()
    return saved


def wanted(profile: Optional[Dict[str, Any]], pieces: Optional[Mapping[str, Any]],
           painted: Iterable[str]) -> Dict[str, Any]:
    """The colours an outfit model of ``pieces`` with the painted set ``painted`` is to carry: ``{}`` without one,
    else ``{"version", "pieces": {item_id: {hex, strength, regions}}, "painted": [every painted piece]}`` — the
    record compared with the model's ``RECORD_KEY``."""
    from app.core import paint_region
    painted_ids = sorted({str(i) for i in painted or () if i})
    out: Dict[str, Any] = {}
    for slot, item_id in sorted((pieces or {}).items()):
        item_id = str(item_id or "").strip()
        if item_id not in painted_ids:
            continue
        colour = colour_of(profile, item_id)
        if colour is None:
            continue
        entry = out.setdefault(item_id, {**colour, "regions": []})
        entry["regions"] = sorted({*entry["regions"], *paint_region.regions_of_slot(slot)})
    if not out:
        return {}
    return {"version": VERSION, "pieces": out, "painted": painted_ids}


def recorded(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The colours an outfit model was made with (its sidecar), ``{}`` without."""
    value = (meta or {}).get(RECORD_KEY)
    return value if isinstance(value, dict) else {}


# --- colour math (sRGB 8 bit <-> CIELAB) ---------------------------------------------------------------------------

def _linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(np.asarray(lin, np.float64), 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def hex_to_lab(hex_colour: str) -> np.ndarray:
    from app.core.garment_hairdeck import linear_to_lab, srgb_to_linear
    rgb = np.array([int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)], np.float64) / 255.0
    return linear_to_lab(srgb_to_linear(rgb))


def rgb8_to_lab(rgb: np.ndarray) -> np.ndarray:
    from app.core.garment_hairdeck import linear_to_lab, srgb_to_linear
    return linear_to_lab(srgb_to_linear(np.asarray(rgb, np.float64) / 255.0))


def lab_to_rgb8(lab: np.ndarray) -> np.ndarray:
    from app.core.garment_hairdeck import lab_to_linear
    return np.clip(np.rint(_linear_to_srgb(lab_to_linear(lab)) * 255.0), 0, 255).astype(np.uint8)


def recolour_texels(rgb: np.ndarray, hex_colour: str, strength: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``rgb`` (N, 3) uint8 recoloured: every texel's CIELAB moves by ``strength * (target - median)`` (the shading
    offsets from the median stay). Returns ``(uint8 (N, 3), record)``."""
    from app.core.garment_hairdeck import delta_e
    target = hex_to_lab(hex_colour)
    lab = rgb8_to_lab(rgb)
    median = np.median(lab, 0)
    shifted = lab + float(strength) * (target - median)
    out = lab_to_rgb8(shifted)
    after = np.median(rgb8_to_lab(out), 0)
    return out, {"texels": int(len(rgb)), "target_lab": [round(float(v), 2) for v in target],
                 "median_lab_before": [round(float(v), 2) for v in median],
                 "median_lab_after": [round(float(v), 2) for v in after],
                 "delta_e_before": round(delta_e(median, target), 2),
                 "delta_e_after": round(delta_e(after, target), 2), "strength": float(strength)}


# --- masks ---------------------------------------------------------------------------------------------------------

def changed_mask(atlas: np.ndarray, plain: np.ndarray) -> np.ndarray:
    """Texels whose RGB the paint changed: ``atlas`` vs the plain body's ``plain`` (both (H, W, ≥3) uint8, same
    size)."""
    if atlas.shape[:2] != plain.shape[:2]:
        raise ValueError("The painted and the plain texture differ in size")
    return np.any(atlas[..., :3] != plain[..., :3], axis=2)


#: Body regions by bone name — the worker's ``body_core.bone_region`` rule (any common rig naming).
_SIDE_TOKENS = {"left", "right", "l", "r", "mixamorig", "def", "org", "bip", "end"}


def bone_region(name: str) -> Optional[str]:
    """The body region (``paint_region.BODY_REGIONS``) of a bone by its name, None for tail/wing/helper bones —
    the worker's ``body_core.bone_region``, so a piece's regions here are the ones the worker painted."""
    name = str(name).rsplit(":", 1)[-1]
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).lower()
    tokens = {t for t in re.split(r"[^a-z]+", spaced) if t} - _SIDE_TOKENS
    if tokens & {"hand", "palm", "finger", "thumb", "index", "middle", "ring", "pinky", "little", "wrist"}:
        return "hand"
    if tokens & {"toe", "toes"}:
        return "toe"
    if tokens & {"foot", "ankle"}:
        return "foot"
    if tokens & {"head", "eye", "jaw", "skull"}:
        return "head"
    if tokens & {"neck"}:
        return "neck"
    if tokens & {"thigh", "upleg"} or {"up", "leg"} <= tokens or {"upper", "leg"} <= tokens:
        return "upper_leg"
    if tokens & {"leg", "calf", "shin", "knee", "lowerleg"}:
        return "lower_leg"
    if tokens & {"forearm", "lowerarm", "elbow"} or {"fore", "arm"} <= tokens or {"lower", "arm"} <= tokens:
        return "forearm"
    if tokens & {"arm", "upperarm"}:
        return "upper_arm"
    if tokens & {"shoulder", "clavicle", "collar", "collarbone"}:
        return "shoulder"
    if tokens & {"hips", "hip", "pelvis", "root"}:
        return "hips"
    if tokens & {"spine", "chest", "breast", "torso", "abdomen", "belly", "waist"}:
        return "spine"
    return None


def region_mask(glb: bytes, regions: Iterable[str], size: Tuple[int, int], *,
                dilate_px: int = REGION_DILATE_PX) -> np.ndarray:
    """(H, W) bool: the atlas texels of the triangles whose vertices the bones of ``regions`` hold (skin share ≥
    ``REGION_MAJORITY`` at any corner), grown by ``dilate_px`` — rasterised from ``glb``'s body UVs (glTF UV: v down
    from the image top, the convention ``base_color_image`` reads)."""
    from PIL import Image, ImageDraw, ImageFilter
    from app.core import glb_mesh
    body = glb_mesh.body_arrays(glb)
    wanted_regions = set(regions)
    bone_in = np.array([bone_region(n) in wanted_regions for n in body.joint_names] + [False], bool)
    joints = np.where((body.joints >= 0) & (body.joints < len(body.joint_names)), body.joints, len(body.joint_names))
    share = (body.weights * bone_in[joints]).sum(1) / np.maximum(body.weights.sum(1), 1e-9)
    held = share >= REGION_MAJORITY
    h, w = size
    image = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(image)
    uv = np.asarray(body.uvs, np.float64)
    px = np.stack([uv[:, 0] % 1.0 * w, uv[:, 1] % 1.0 * h], 1)
    for tri in body.faces[held[body.faces].any(1)]:
        draw.polygon([tuple(px[i]) for i in tri], fill=255)
    if dilate_px > 0:
        image = image.filter(ImageFilter.MaxFilter(2 * int(dilate_px) + 1))
    return np.asarray(image) > 0


def piece_masks(atlas: np.ndarray, plain: np.ndarray, glb: bytes, colours: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """``{item_id: (H, W) bool}`` — each coloured piece's painted texels (module docstring): the changed texels,
    intersected with the piece's regions only when another painted piece shares the texture."""
    changed = changed_mask(atlas, plain)
    pieces = (colours or {}).get("pieces") or {}
    shared = len((colours or {}).get("painted") or []) > 1
    out: Dict[str, np.ndarray] = {}
    for item_id, entry in sorted(pieces.items()):
        out[item_id] = changed & region_mask(glb, entry.get("regions") or (), atlas.shape[:2]) if shared else changed
    return out


# --- apply ---------------------------------------------------------------------------------------------------------

def _decode(image: bytes) -> np.ndarray:
    from PIL import Image
    with Image.open(io.BytesIO(image)) as decoded:
        return np.asarray(decoded.convert("RGBA")).copy()


def recolour_atlas(atlas: np.ndarray, plain: np.ndarray, glb: bytes, colours: Dict[str, Any]
                   ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``atlas`` (H, W, 4 uint8) with every coloured piece's texels recoloured (``piece_masks``,
    ``recolour_texels``); alpha and every texel outside the masks untouched. Returns ``(atlas, proof)``."""
    out = atlas.copy()
    proof: Dict[str, Any] = {"version": VERSION, "pieces": {}}
    masks = piece_masks(atlas, plain, glb, colours)
    for item_id, mask in masks.items():
        entry = colours["pieces"][item_id]
        if not mask.any():
            proof["pieces"][item_id] = {"texels": 0, "skipped": "no painted texel"}
            continue
        rgb, record = recolour_texels(atlas[mask][:, :3], entry["hex"], entry["strength"])
        out[..., :3][mask] = rgb
        proof["pieces"][item_id] = {**record, "hex": entry["hex"]}
    return out, proof


def apply(outfit: bytes, plain_glb: bytes, colours: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    """The outfit model ``outfit`` (GLB, the paint in its base colour) recoloured with ``colours`` (``wanted``):
    the plain texture is ``plain_glb``'s base colour (the worker's input), the region UVs and weights are
    ``outfit``'s own. ``(outfit, {})`` unchanged without colours. Returns ``(glb, proof)``."""
    if not (colours or {}).get("pieces"):
        return outfit, {}
    from PIL import Image
    from app.core.base_body import base_color_image, replace_base_color
    image, _mime = base_color_image(outfit)
    plain_image, _plain_mime = base_color_image(plain_glb)
    atlas, plain = _decode(image), _decode(plain_image)
    recoloured, proof = recolour_atlas(atlas, plain, outfit, colours)
    buf = io.BytesIO()
    Image.fromarray(recoloured).save(buf, "PNG")
    return replace_base_color(outfit, buf.getvalue(), "image/png"), proof


def region_overlay(glb: bytes, regions: Iterable[str], *, mask: Optional[np.ndarray] = None,
                   max_side: int = 1024) -> bytes:
    """A PNG of ``glb``'s base colour with the body region of ``regions`` tinted (and, when given, the painted
    ``mask`` outlined in a second colour) — the dialog's "Paint region" tile."""
    from PIL import Image
    from app.core.base_body import base_color_image
    image, _mime = base_color_image(glb)
    atlas = _decode(image)
    region = region_mask(glb, regions, atlas.shape[:2])
    rgb = atlas[..., :3].astype(np.float64)
    rgb[region] = rgb[region] * 0.45 + np.array([40, 170, 255]) * 0.55
    if mask is not None and mask.shape == region.shape:
        rgb[mask & ~region] = rgb[mask & ~region] * 0.4 + np.array([255, 140, 0]) * 0.6
    out = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    out.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def preset_list() -> List[Dict[str, str]]:
    return [{"hex": h, "name": n} for h, n in PRESETS]
