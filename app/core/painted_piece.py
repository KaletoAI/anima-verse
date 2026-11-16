"""The painted piece dialog (Ruling A148) — the steps of a WORN piece of mesh mode ``painted``, read-only.

A painted piece has no chain of its own: it is painted per OUTFIT. Its steps are the outfit's:

1. Dressed views (``base_body.dressed_views()``): edits of the body's views that show the outfit (1 image job each).
2. Paint region (Ruling A127): the body regions its slot may change (``paint_region.regions_of_slot``).
3. Painted texture: the worker paints every painted piece of the outfit at once into the body texture
   (``model3d/texture/<tex>.glb``, CPU), then the piece colours (``paint_colour``) go on the outfit model.
4. Assembly: the outfit model plus the grafted own-mesh pieces and the hair (CPU).

``info`` is the dialog's payload; ``region_png`` its region tile; ``preview_glb`` the recoloured outfit model the
dialog's viewer shows while a colour is being picked (nothing stored, CPU).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("painted_piece")

#: The piece is not worn (painting is per worn outfit).
NOT_WORN = "Not worn — a painted piece is painted with the outfit it is worn in"
#: The piece is worn in another mode.
NOT_PAINTED = "This piece is not painted — its mode is {mode}"
#: Texture states, their words.
TEXTURE_CURRENT = "Painted with the outfit's current views and colours"
TEXTURE_COLOUR_DUE = "The colour changed — Paint now repaints it from the stored texture (CPU, 0 hub jobs)"
TEXTURE_DUE = "Not painted for these views yet — the Build paints it (CPU, 0 hub jobs once the views are there)"
TEXTURE_LEFT_OFF = "Left off the figure now: {reason}"
VIEW_MISSING = "Missing — the Build renders it (1 image job)"
VIEW_CURRENT = "Current"
ASSEMBLY_CURRENT = "Assembled"
ASSEMBLY_DUE = "Due after the paint (CPU, 0 hub jobs)"


def _name(item_id: str) -> str:
    from app.models.inventory import get_item
    return str((get_item(item_id) or {}).get("name") or item_id)


def _stamp(path) -> Optional[str]:
    from app.core import model_overview
    try:
        return model_overview.built_at(path) if path is not None else None
    except Exception:  # noqa: BLE001 — a caption only
        return None


def _outfit_model(character_name: str, signature: str) -> Tuple[Optional[Any], Dict[str, Any], str]:
    """``(path, sidecar, stale reason)`` of the stored outfit model of ``signature`` (stale ones too)."""
    from app.core import base_body, model3d
    path = model3d.find_model3d(character_name, signature, include_stale=True)
    if path is None:
        return None, {}, "missing"
    meta = model3d._read_sidecar(path)
    try:
        reason = base_body.figure_stale(character_name, meta) or ""
    except Exception:  # noqa: BLE001 — judged missing rather than raise in a poll
        reason = "figure"
    return path, meta, reason


def info(character_name: str, item_id: str) -> Dict[str, Any]:
    """The dialog's payload (module docstring). ValueError when the piece is not the character's."""
    from urllib.parse import quote
    from app.core import base_body, figure, figure_build, paint_colour, paint_region
    from app.core.garment_set import holds
    from app.models.character import get_character_profile
    if not holds(character_name, item_id):
        raise ValueError(f"{item_id} is not a piece of {character_name}")
    profile = get_character_profile(character_name) or {}
    wanted, delivered = figure._delivered(character_name, profile=profile)
    slots = sorted(slot for slot, i in wanted.pieces.items() if i == item_id)
    regions = sorted({r for slot in slots for r in paint_region.regions_of_slot(slot)})
    enc, item_enc = quote(character_name, safe=""), quote(item_id, safe="")
    out: Dict[str, Any] = {
        "item_id": item_id, "name": _name(item_id), "slots": slots, "regions": regions,
        "margin_mm": paint_region.PAINT_REGION_MARGIN_MM, "worn": bool(slots),
        "mode": delivered.state_of(item_id) if slots else "", "painted": item_id in wanted.painted,
        "signature": wanted.signature, "texture_key": delivered.texture,
        "shared_with": [{"item_id": i, "name": _name(i)} for i in wanted.painted if i != item_id],
        "colour": {**(paint_colour.colour_of(profile, item_id) or {"hex": "", "strength": paint_colour.DEFAULT_STRENGTH}),
                   "presets": paint_colour.preset_list(), "applied": None},
        "build_running": figure_build.running(character_name),
        "region_url": f"/characters/{enc}/figure/painted/{item_enc}/region.png",
        "preview_url": f"/characters/{enc}/figure/painted/{item_enc}/preview.glb",
        "note": "",
    }
    if not slots:
        out["note"] = NOT_WORN
        return out
    if item_id not in wanted.painted:
        out["note"] = NOT_PAINTED.format(mode=wanted.state_of(item_id) or "unknown")
        return out
    # 1. Views (of the figure delivered now).
    views: List[Dict[str, Any]] = []
    for v in base_body.dressed_views():
        path = base_body.dressed_image(character_name, v, wanted.signature, delivered.bsig, fig=delivered)
        views.append({"view": v, "state": "current" if path is not None else "missing",
                      "reason": VIEW_CURRENT if path is not None else VIEW_MISSING,
                      "built_at": _stamp(path), "jobs": 0 if path is not None else 1})
    out["views"] = views
    # 3./4. Texture and assembly.
    path, meta, stale = _outfit_model(character_name, wanted.signature)
    left = delivered.left_out.get(item_id, "")
    applied = (paint_colour.recorded(meta).get("pieces") or {}).get(item_id)
    out["colour"]["applied"] = {"hex": applied["hex"], "strength": applied["strength"]} if applied else None
    if left:
        texture = {"state": "left_out", "reason": TEXTURE_LEFT_OFF.format(reason=left)}
    elif stale == "paint_colour":
        texture = {"state": "colour_due", "reason": TEXTURE_COLOUR_DUE}
    elif path is None or stale:
        texture = {"state": "due", "reason": TEXTURE_DUE}
    else:
        texture = {"state": "current", "reason": TEXTURE_CURRENT}
    texture.update(key=delivered.texture, built_at=_stamp(path) if path is not None else None,
                   reused=bool(meta.get("texture_reused")), proof=(meta.get(paint_colour.PROOF_KEY) or {})
                   .get("pieces", {}).get(item_id))
    out["texture"] = texture
    try:
        cpu, hub = figure_build.paint_steps(character_name, profile=profile, resolved=(wanted, delivered))
    except Exception:  # noqa: BLE001 — the dialog never fails on the estimate
        logger.exception("Paint plan of %s unreadable", character_name)
        cpu, hub = [], []
    out["paint"] = {"cpu_steps": [s.label for s in cpu], "hub_steps": [s.label for s in hub],
                    "hub_jobs": sum(int(s.jobs or 0) for s in hub)}
    assembled = texture["state"] == "current" and not any(s.name == "assemble" for s in cpu)
    out["assembly"] = {"state": "current" if assembled else "due",
                       "reason": ASSEMBLY_CURRENT if assembled else ASSEMBLY_DUE,
                       "built_at": figure_build._served_built_at(character_name)}
    return out


def _sources(character_name: str) -> Tuple[bytes, bytes, Dict[str, Any], Any]:
    """``(outfit glb with the RAW paint, plain glb, profile, delivered figure)`` of the worn outfit: the stored
    painted body of the delivered texture (the worker's output, no colours), and the rigged body the worker
    painted from. ValueError when nothing is painted yet."""
    from app.core import base_body, figure
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    _wanted, delivered = figure._delivered(character_name, profile=profile)
    if not delivered.texture:
        raise ValueError("Nothing is painted on this figure")
    path = base_body.texture_body_path(character_name, delivered.texture)
    if not path.is_file():
        raise ValueError("The painted texture is not built yet — Build paints it")
    if figure.is_plain(delivered.shape):
        plain = base_body._snapshot_base_model(character_name, delivered.bsig)["rigged"]
    else:
        plain = base_body._snapshot_shape(character_name, delivered.shape, delivered.bsig)["rigged"]
    return path.read_bytes(), plain, profile, delivered


def preview_glb(character_name: str, item_id: str, hex_colour: str, strength: Any) -> bytes:
    """The painted body with ``item_id`` in ``hex_colour`` / ``strength`` (the other pieces in their stored
    colours) — nothing stored. ValueError for a bad colour or nothing painted."""
    from app.core import paint_colour
    value = paint_colour.validate(hex_colour, strength)
    outfit, plain, profile, fig = _sources(character_name)
    if item_id not in fig.painted:
        raise ValueError("This piece is not painted on the figure")
    stored = dict(profile.get(paint_colour.SETTINGS_KEY) or {})
    if value is None:
        stored.pop(item_id, None)
    else:
        stored[item_id] = value
    colours = paint_colour.wanted({paint_colour.SETTINGS_KEY: stored}, fig.pieces, fig.painted)
    glb, _proof = paint_colour.apply(outfit, plain, colours)
    return glb


def region_png(character_name: str, item_id: str) -> bytes:
    """The region tile: the painted body's texture with this piece's body regions tinted and the texels the paint
    changed outside them marked."""
    import io
    import numpy as np
    from PIL import Image
    from app.core import paint_colour, paint_region
    from app.core.base_body import base_color_image
    outfit, plain, _profile, fig = _sources(character_name)
    slots = [slot for slot, i in fig.pieces.items() if i == item_id]
    regions = sorted({r for slot in slots for r in paint_region.regions_of_slot(slot)})

    def dec(glb: bytes):
        with Image.open(io.BytesIO(base_color_image(glb)[0])) as im:
            return np.asarray(im.convert("RGBA"))
    atlas, base = dec(outfit), dec(plain)
    mask = paint_colour.changed_mask(atlas, base) if atlas.shape == base.shape else None
    return paint_colour.region_overlay(outfit, regions, mask=mask)
