"""Per-model tip placement and colour disc of ``pair_tip`` extension groups.

A ``pair_tip`` group (``app/blender/scripts/extension_bones.py``) builds a
stub and a child bone on each side of its ``pair_protrusion`` source: at the
source's colour marker, or without one at its geometry crest — the
SUGGESTION (``tip_source`` in the metrics: ``colour`` / ``geometry``).

What the user sets per model (``model3d_opts.extension_rig_models[sig][group]
["tip"]``, ``extension_rig.validate_tip_override``; part of the extension
fingerprint, so a change rebuilds the extension rig from the clean source):

* an offset per side in mm, ``up`` and ``out`` (away from the midline), which
  moves the tip along the body surface — the stub's axis stays the local
  surface normal there; ``mirror`` gives both sides one value pair;
* a colour disc: painted into the base-colour texture around each tip, by UV
  lookup in Blender (``disc_mask``) and painted here (``paint_disc_masks``).
  Every build starts from the clean source's texture (``prerig/``), so a
  re-run never paints over an older disc and "off" restores it exactly.

An outfit model on the base body inherits the base model's tip override
(``extension_rig.effective_extension_overrides``) and its texture comes from
the base's, disc included.

This module also runs "Apply" in the background (``apply_tip_override``: the
existing CPU extension rebuild, no hub job) and builds the Base body tab's
panel data (``tip_panels``). It never names a group or a package.
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# character -> signature of the Apply running now; character -> last result.
_running: Dict[str, str] = {}
_results: Dict[str, Dict[str, Any]] = {}


def _rgb(colour: str) -> Tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def paint_texels(image: bytes, mime: str, discs: List[Dict[str, Any]]) -> Tuple[bytes, int]:
    """``image`` with every disc blended in: ``discs`` = ``[{size: [w, h],
    texels: [x, y, alpha 1..255, ...], color: "#rrggbb"}]`` (``disc_mask``,
    rows top-down). Per texel ``out = in * (1 - a) + colour * a``. A JPEG keeps
    its own quantisation tables (no second, coarser generation), PNG/WebP stay
    lossless. Returns ``(bytes, texels painted)``; with no texel the input
    bytes come back unchanged."""
    import numpy as np
    from PIL import Image
    if not any(disc.get("texels") for disc in discs):
        return image, 0
    with Image.open(io.BytesIO(image)) as source:
        source.load()
        mode = source.mode
        rgb = np.asarray(source.convert("RGB"), dtype=np.float32).copy()
        height, width = rgb.shape[:2]
        painted_at = set()
        for disc in discs:
            texels = np.asarray(disc.get("texels") or [], dtype=np.int64).reshape(-1, 3)
            if not len(texels):
                continue
            w, h = disc["size"]
            xs, ys = texels[:, 0], texels[:, 1]
            if (w, h) != (width, height):
                xs, ys = xs * width // w, ys * height // h
            alpha = (texels[:, 2] / 255.0)[:, None]
            colour = np.asarray(_rgb(disc["color"]), dtype=np.float32)
            rgb[ys, xs] = rgb[ys, xs] * (1 - alpha) + colour * alpha
            painted_at.update(zip(xs.tolist(), ys.tolist()))
        painted = Image.fromarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8), "RGB")
        out = io.BytesIO()
        if mime == "image/jpeg":
            if mode == "RGB":
                try:
                    source.paste(painted)
                    source.save(out, format="JPEG", quality="keep", subsampling="keep")
                except (OSError, ValueError):
                    out = io.BytesIO()
            if not out.getvalue():
                painted.save(out, format="JPEG", quality=95)
        else:
            if mode in ("RGBA", "LA"):
                painted.putalpha(source.getchannel("A"))
            if mime == "image/webp":
                painted.save(out, format="WEBP", lossless=True, exact=True, quality=100)
            else:
                painted.save(out, format="PNG")
    return out.getvalue(), len(painted_at)


def paint_disc_masks(path, groups: List[Dict[str, Any]], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """The extension script's ``metrics`` without the texel lists
    (``disc_mask``): each such group gets a ``disc`` summary instead
    (``status`` applied / failed / skipped, ``reason``, ``pixels``, colour,
    diameter, soft edge). With ``path`` (the staged GLB the script wrote)
    the discs are painted into its base colour (``paint_texels``); ``path``
    None (no model was produced) paints nothing. A paint failure keeps the
    model unpainted and says why — it never fails the build."""
    from app.core.extension_rig import DISC_DEFAULTS
    settings = {group["id"]: {**DISC_DEFAULTS, **((group.get("tip_override") or {}).get("disc") or {})}
                for group in groups}
    out: Dict[str, Any] = {}
    discs: List[Tuple[str, Dict[str, Any]]] = []
    for group_id, values in metrics.items():
        if not isinstance(values, dict) or "disc_mask" not in values:
            out[group_id] = values
            continue
        values = dict(values)
        mask = values.pop("disc_mask") or {}
        disc = settings.get(group_id, dict(DISC_DEFAULTS))
        summary = {"color": disc["color"], "diameter_mm": disc["diameter_mm"], "soft_mm": disc["soft_mm"],
                   "pixels": int(mask.get("pixels") or 0), "status": "applied", "reason": ""}
        if mask.get("error"):
            summary.update(status="failed", reason=str(mask["error"]), pixels=0)
        elif path is None:
            summary.update(status="skipped", reason="No model was produced")
        else:
            discs.append((group_id, {"size": mask.get("size") or [0, 0], "texels": mask.get("texels") or [],
                                     "color": disc["color"]}))
        values["disc"] = summary
        out[group_id] = values
    if discs and path is not None:
        from app.core.base_body import base_color_image, replace_base_color
        try:
            glb = path.read_bytes()
            image, mime = base_color_image(glb)
            painted, count = paint_texels(image, mime, [disc for _, disc in discs])
            if painted != image:
                path.write_bytes(replace_base_color(glb, painted, mime))
            for group_id, _ in discs:
                out[group_id]["disc"]["texture_pixels"] = count
        except (ValueError, OSError) as exc:
            logger.warning("Colour disc not painted into %s: %s", path, exc)
            for group_id, _ in discs:
                out[group_id]["disc"].update(status="failed", reason=f"Painting failed: {exc}")
    return out


#: ``set_tip_override``'s "leave this field as it is".
KEEP: Any = object()


def set_tip_override(character_name: str, signature: str, group_id: str,
                     tip: Any = KEEP, *, enabled: Any = KEEP) -> Optional[Dict[str, Any]]:
    """Store (or with None / the defaults remove) the ``tip`` override of
    ``group_id`` on the stored model ``signature`` and/or its per-model
    ``enabled`` switch — the same ``extension_rig_models[sig][group]`` dict
    the 3D tab's switches write (``model3d.set_model3d_options``); what is
    not given stays, the group's other switches too. ``enabled`` True is the
    default and is stored as the key's absence, so off → on gives the
    fingerprint of before. ValueError when the model is missing, the group
    is not one of its ``pair_tip`` groups or a value is malformed;
    RuntimeError when the profile cannot be saved. Returns the stored tip
    value (None = none)."""
    from app.core.extension_rig import validate_tip_override
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    if group_id not in {group["id"] for group in _tip_groups(character_name, signature)}:
        raise ValueError("Not a tip group of this model")
    if enabled is not KEEP and type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    cleaned = validate_tip_override(tip) if tip is not KEEP else None
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        opts = dict(profile.get("model3d_opts") or {})
        models = dict(opts.get("extension_rig_models") or {})
        model = dict(models.get(signature) or {})
        values = dict(model.get(group_id) or {})
        if tip is KEEP:
            cleaned = values.get("tip")
        elif cleaned is None:
            values.pop("tip", None)
        else:
            values["tip"] = cleaned
        if enabled is False:
            values["enabled"] = False
        elif enabled is True:
            values.pop("enabled", None)
        if values:
            model[group_id] = values
        else:
            model.pop(group_id, None)
        if model:
            models[signature] = model
        else:
            models.pop(signature, None)
        opts["extension_rig_models"] = models
        profile["model3d_opts"] = opts
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The character profile could not be saved")
    return cleaned


def _tip_groups(character_name: str, signature: str, *, profile=None, meta=None) -> List[Dict[str, Any]]:
    """The ``pair_tip`` groups the stored model ``signature`` carries, each
    with its effective ``tip_override``."""
    from app.core.extension_rig import effective_extension_overrides, resolved_extension_groups, rig_groups_for
    from app.core.model3d import _extension_groups_for, _read_sidecar, find_model3d
    from app.models.character import get_character_profile
    if meta is None:
        path = find_model3d(character_name, signature)
        if path is None:
            raise ValueError("Stored model not found for signature")
        meta = _read_sidecar(path)
    if profile is None:
        profile = get_character_profile(character_name) or {}
    mesh_variant = meta.get("mesh_variant") or ""
    declarations = _extension_groups_for(meta, rig_groups_for(character_name, profile=profile,
                                                              mesh_variant=mesh_variant))
    groups = resolved_extension_groups(
        character_name, profile=profile, signature=signature, mesh_variant=mesh_variant,
        overrides=effective_extension_overrides(profile, signature, meta, declarations))
    return [group for group in _extension_groups_for(meta, groups) if group["op"] == "pair_tip"]


def apply_tip_override(character_name: str, signature: str, group_id: str,
                       tip: Any = KEEP, *, enabled: Any = KEEP) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Store the tip override (``set_tip_override``) and rebuild the
    extension rig of ``signature`` in a worker thread (the CPU rebuild of
    ``model3d.rebuild_extension_rig``, forced so a failed attempt is
    retried). The character's slot is taken BEFORE the store, so a second
    request while a rebuild runs changes nothing: ``(False, None)``.
    Otherwise ``(True, stored value)``; the store's ValueError /
    RuntimeError propagate with the slot released."""
    with _lock:
        if character_name in _running:
            return False, None
        _running[character_name] = signature
    try:
        stored = set_tip_override(character_name, signature, group_id, tip, enabled=enabled)
    except BaseException:
        with _lock:
            _running.pop(character_name, None)
        raise
    with _lock:
        _results.pop(character_name, None)
    threading.Thread(target=_apply, args=(character_name, signature), daemon=True,
                     name=f"extension-tip-{character_name}").start()
    return True, stored


def _apply(character_name: str, signature: str) -> None:
    from app.core.model3d import rebuild_extension_rig
    from app.core.task_queue import get_task_queue
    from app.core.timeutils import utc_now_iso
    error, task_id = "", ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"Extension tips: {character_name}",
            agent_name=character_name, start_running=True)
    except Exception:  # noqa: BLE001 — tracking is display only
        task_id = ""
    try:
        result = rebuild_extension_rig(character_name, signature, force=True)
        if not result.get("ok"):
            error = (result.get("error") or (result.get("extension_rig") or {}).get("reason")
                     or "Extension rebuild failed")
    except Exception as exc:  # noqa: BLE001 — reported to the panel
        logger.exception("Extension tip apply of %s (%s) failed", character_name, signature)
        error = str(exc) or type(exc).__name__
    finally:
        with _lock:
            _running.pop(character_name, None)
            _results[character_name] = {"signature": signature, "error": error, "at": utc_now_iso()}
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:  # noqa: BLE001
                pass


def _gltf(vector) -> Optional[List[float]]:
    """Blender world (front -Y, up +Z) -> glTF/model frame (front +Z, up +Y)."""
    if not vector or len(vector) != 3:
        return None
    x, y, z = (float(v) for v in vector)
    return [x, z, -y]


def _frame(normal, side: int) -> Tuple[List[float], List[float]]:
    """``surface_frame`` of the Blender script, for a stored normal: up (+Z)
    and out (side * X) projected into the tangent plane, normalised."""
    import math
    n = [float(v) for v in normal]
    length = math.sqrt(sum(v * v for v in n)) or 1.0
    n = [v / length for v in n]

    def project(axis):
        dot = sum(a * b for a, b in zip(axis, n))
        v = [a - dot * b for a, b in zip(axis, n)]
        norm = math.sqrt(sum(c * c for c in v)) or 1.0
        return [c / norm for c in v]
    return project([0.0, 0.0, 1.0]), project([float(side), 0.0, 0.0])


def tip_panels(character_name: str, signature: str) -> List[Dict[str, Any]]:
    """The Base body tab's panel per ``pair_tip`` group of the stored model
    ``signature`` (all positions in the model's glTF frame, metres):

    ``{id, label, enabled, active, status, reason, tip_source, sides: [{side: left|right,
    suggested, tip, tangent_up, tangent_out, offset_mm} | None, ...],
    override, disc, limits, running, error}``. ``tip`` is the built tip
    (None while the group was not built); ``suggested`` falls back to the
    source group's apex, the tangents to its wall normal. ``side`` follows
    the operation's convention: the first chain lies on +X, the figure's left.
    Never raises (an unreadable model gives [])."""
    from app.core.extension_rig import (DISC_DEFAULTS, DISC_DIAMETER_MM, DISC_SOFT_MAX_MM,
                                       TIP_OFFSET_MAX_MM)
    from app.core.model3d import _read_sidecar, find_model3d
    from app.models.character import get_character_profile
    try:
        path = find_model3d(character_name, signature)
        if path is None:
            return []
        meta = _read_sidecar(path)
        profile = get_character_profile(character_name) or {}
        groups = _tip_groups(character_name, signature, meta=meta, profile=profile)
    except Exception:  # noqa: BLE001 — the poll never fails on the panel
        logger.exception("Tip panels of %s (%s) failed", character_name, signature)
        return []
    state = meta.get("extension_rig") or {}
    metrics = state.get("metrics") or {}
    with _lock:
        running = _running.get(character_name) == signature
        last = dict(_results.get(character_name) or {})
    panels = []
    for group in groups:
        built = metrics.get(group["id"]) or {}
        rows = built.get("placement") or []
        source_rows = (metrics.get(group.get("depends_on") or "") or {}).get("placement") or []
        sides = []
        for index, sign in enumerate((1, -1)):
            row = rows[index] if index < len(rows) and isinstance(rows[index], dict) else {}
            source = source_rows[index] if index < len(source_rows) and isinstance(source_rows[index], dict) else {}
            suggested = row.get("suggested") or source.get("tip")
            normal = row.get("suggested_normal") or source.get("wall_normal")
            if not suggested or not normal:
                sides.append(None)
                continue
            tangent_up, tangent_out = ((row["tangent_up"], row["tangent_out"])
                                       if row.get("tangent_up") and row.get("tangent_out") else _frame(normal, sign))
            sides.append({"side": "left" if sign > 0 else "right",
                          "suggested": _gltf(suggested), "tip": _gltf(row.get("tip")) if rows else None,
                          "tangent_up": _gltf(tangent_up), "tangent_out": _gltf(tangent_out),
                          "offset_mm": row.get("offset_mm") or [0.0, 0.0]})
        status = built.get("status") or ("applied" if rows else "not_found")
        tip_source = built.get("tip_source") or (
            ("colour" if all(r.get("apex_source") == "colour" for r in source_rows) else "geometry")
            if source_rows else None)
        # ``enabled``: this model's own switch (the one the 3D tab shows);
        # ``active``: what the build uses — off also when the source group is.
        own = ((((profile.get("model3d_opts") or {}).get("extension_rig_models") or {})
                .get(signature) or {}).get(group["id"]) or {})
        enabled = own.get("enabled", True) is not False
        if not group["enabled"]:
            status = "disabled"
        panels.append({"id": group["id"], "label": group.get("label") or group["id"],
                       "enabled": enabled, "active": bool(group["enabled"]),
                       "status": status, "reason": built.get("reason") or "",
                       "tip_source": tip_source, "sides": sides,
                       "override": group.get("tip_override"), "disc": built.get("disc"),
                       "limits": {"offset_max_mm": TIP_OFFSET_MAX_MM, "diameter_mm": list(DISC_DIAMETER_MM),
                                  "soft_max_mm": DISC_SOFT_MAX_MM, "disc_defaults": dict(DISC_DEFAULTS)},
                       "running": running,
                       "error": last.get("error") or "" if last.get("signature") == signature else ""})
    return panels
