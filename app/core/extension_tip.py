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

Saving a setting rebuilds nothing (``save_tip_override``, Task UI2 rule R3):
the panel then reports the model as due (``tip_panels`` ``due``) and
"Rebuild" (``start_tip_rebuild``: the existing CPU extension rebuild in the
background, no hub job) or the Base body tab's "Run all" applies it. This
module also builds the plain body's tip panel data (``tip_panels``). It
never names a group or a package.
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
    rows top-down). Per texel
    ``out = in * (1 - a) + colour * a``. A JPEG keeps
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
    model unpainted and says why — it never fails the build. A switched-off
    tip part that leaves a neutral surface paints nothing: only its mesh is
    levelled (Ruling A53)."""
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
    from app.core.model3d import _extension_groups_for, _read_sidecar, find_model3d, stored_mesh_variant
    from app.models.character import get_character_profile
    if meta is None:
        path = find_model3d(character_name, signature)
        if path is None:
            raise ValueError("Stored model not found for signature")
        meta = _read_sidecar(path)
    if profile is None:
        profile = get_character_profile(character_name) or {}
    # The model's own mesh variant: a base body's resolves as unclothed (Ruling A49).
    mesh_variant = stored_mesh_variant(character_name, meta)
    declarations = _extension_groups_for(meta, rig_groups_for(character_name, profile=profile,
                                                              mesh_variant=mesh_variant))
    groups = resolved_extension_groups(
        character_name, profile=profile, signature=signature, mesh_variant=mesh_variant,
        overrides=effective_extension_overrides(profile, signature, meta, declarations))
    return [group for group in _extension_groups_for(meta, groups) if group["op"] == "pair_tip"]


#: ``save_tip_override`` / ``start_tip_rebuild``: a rebuild of the character runs now.
REBUILD_RUNNING = "A tip rebuild is already running for this character"


def save_tip_override(character_name: str, signature: str, group_id: str,
                      tip: Any = KEEP, *, enabled: Any = KEEP) -> Optional[Dict[str, Any]]:
    """Store the tip override / the per-model switch (``set_tip_override``) WITHOUT rebuilding anything (Task UI2,
    rule R3: a setting is saved on its own). The stored model's extension rig is then out of date with its settings
    (``model3d.extension_settings_changed``): the panel says so and the Base body tab's "Run all" — or the panel's
    "Rebuild" (``start_tip_rebuild``) — applies it. RuntimeError(``REBUILD_RUNNING``) while a rebuild of the
    character runs (it read the settings at its start); the store's ValueError / RuntimeError propagate. Returns
    the stored tip value (None = none)."""
    with _lock:
        if character_name in _running:
            raise RuntimeError(REBUILD_RUNNING)
    return set_tip_override(character_name, signature, group_id, tip, enabled=enabled)


def rebuild_running(character_name: str) -> str:
    """The model signature whose extension rig is rebuilt for the character now, "" when none (Ruling A26: a
    Build does not start beside it)."""
    with _lock:
        return str(_running.get(character_name) or "")


def start_tip_rebuild(character_name: str, signature: str) -> bool:
    """Rebuild the extension rig of the stored model ``signature`` in a worker thread with the saved settings (the
    CPU rebuild of ``model3d.rebuild_extension_rig``, forced so a failed attempt is retried; no hub job). False
    when a rebuild of the character already runs. ValueError when the model is missing."""
    from app.core.model3d import find_model3d
    if find_model3d(character_name, signature) is None:
        raise ValueError("Stored model not found for signature")
    with _lock:
        if character_name in _running:
            return False
        _running[character_name] = signature
        _results.pop(character_name, None)
    try:
        from app.core import cpu_progress
        threading.Thread(target=cpu_progress.scoped(f"figure:{character_name}", _apply),  # A194: live line
                         args=(character_name, signature), daemon=True,
                         name=f"extension-tip-{character_name}").start()
    except BaseException:
        with _lock:
            _running.pop(character_name, None)
        raise
    return True


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
    """The plain-body details' panel per ``pair_tip`` group of the stored model
    ``signature`` (all positions in the model's glTF frame, metres):

    ``{id, label, enabled, active, status, reason, tip_source, sides: [{side: left|right,
    suggested, tip, tangent_up, tangent_out, offset_mm} | None, ...],
    override, disc, limits, running, due, error}`` (``due``: the saved
    settings differ from the ones the model's extension rig was built with —
    ``model3d.extension_settings_changed``; the same for every group, the
    rebuild is per model). ``tip`` is the built tip
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
    try:
        from app.core.model3d import extension_settings_changed
        due = extension_settings_changed(character_name, path, meta)
    except Exception:  # noqa: BLE001 — the poll never fails on the panel
        logger.exception("Extension settings state of %s (%s) not readable", character_name, signature)
        due = False
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
                       # Saved settings not built yet (the model's extension rig is older than them).
                       "due": due,
                       "error": last.get("error") or "" if last.get("signature") == signature else ""})
    return panels


def group_tip_settings(panels: List[Dict[str, Any]], extension: Optional[Dict[str, Any]]) -> None:
    """One place per tip group (Ruling A53): each tip panel gets what the "Extension bones" box used to show for
    its group — ``light`` (the group's ``extension_group_lights`` entry, None without one), ``controls`` (the
    motion values the group declares, e.g. length and girth factors; [] without a declaration) and ``built_at`` (when
    the model's extension rig was last built with something applied, else None) — and the box's
    ``box_groups`` lists only the groups WITHOUT a tip panel (the box no longer shows tip groups). ``groups`` and
    ``lights`` stay whole: the viewer's motion preview reads every group. Mutates in place; a missing
    ``extension`` (no stored model) leaves the panels with ``light`` None and ``controls`` []."""
    ids = {panel["id"] for panel in panels}
    groups = {g.get("id"): g for g in ((extension or {}).get("groups") or []) if isinstance(g, dict)}
    lights = (extension or {}).get("lights") or {}
    result = (extension or {}).get("result") or {}
    built_at = result.get("attempted_at") if result.get("status") == "applied" else None
    for panel in panels:
        group = groups.get(panel["id"]) or {}
        panel["light"] = lights.get(panel["id"])
        panel["controls"] = list(group.get("controls") or [])
        panel["built_at"] = built_at
    if extension is not None:
        extension["box_groups"] = [gid for gid in groups if gid not in ids]


# --- Tip smoothing (Ruling A43) ------------------------------------------------------------------------------------
#
# Before a ``pair_tip`` group builds its stub, ``extension_bones.tip_mesh`` levels the source bump — the part the
# mesher modelled where the source group located it, before any offset — onto the surface around it (Ruling A53, the
# levelling of Ruling A44); a tip an offset moved away is not levelled where it sits (no source bump there, and a
# quadric fitted on the curve's flank flattens it); the moved vertices get the surface's own normals (Ruling A34). It runs inside the extension rebuild; this record makes it
# visible on its own: ``meta["tip_smoothing"]`` of a base model = ``{version, at, status: built|failed, error,
# groups: {group: {applied, reason, max_shift_mm, moved, radius_mm, passes, inverted: [before, after], off_60:
# [before, after], region_mm, bump_mm: [[before, after] per side], tip_from_source_mm: [per side]}}}``, written by
# every extension build of a base body that carries a ``pair_tip`` group (``model3d._extension_rig_once``). A base
# whose tip groups lack it, or carry an older ``version``, is due: Run all, the Build or "Smooth again" rerun the
# extension step (CPU, no hub job).
#
# A ``pair_tip`` group switched off on the base model whose declaration says ``when_off: neutralise`` (Ruling A44)
# shares the row: the extension build levels the source bump the same way (``extension_bones.neutralise_mesh``) and
# leaves the texture as it is (Ruling A53); its record entry carries ``mode: "neutralised"`` with the tip height
# before → after. Each group's entry must be of the mode its switch asks for, so switching the part on or off makes
# the step due.

#: The tip smoothing's version: a record of an older one makes the step due. 1 = Laplacian smoothing over the
#: footprint + surface normals (Ruling A34), recorded with the normal counts (Ruling A43); 2 = the source bump levelled
#: onto the fitted surface under a part that is on, and a part that is off levels the mesh only (Ruling A53).
TIP_SMOOTHING_VERSION = 2


def _source_smooth(values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for row in values.get("placement") or []:
        if isinstance(row, dict) and isinstance(row.get("source_smooth"), dict):
            return row["source_smooth"]
    return None


def _levelled_sides(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per side the source bump's height above the fitted surface [before, after] (mm) and the placed tip's distance
    from the source apex (mm) — ``extension_bones.level_sides``."""
    sides = [row.get("source_level") if isinstance(row.get("source_level"), dict) else row for row in rows]
    return {"bump_mm": [side.get("bump_mm") for side in sides if side.get("bump_mm") is not None],
            "tip_from_source_mm": [side.get("tip_from_source_mm") for side in sides
                                   if side.get("tip_from_source_mm") is not None]}


def tip_smoothing_group(values: Dict[str, Any]) -> Dict[str, Any]:
    """One group's entry of the record from the extension script's metrics of that group (pure)."""
    values = values if isinstance(values, dict) else {}
    smooth = _source_smooth(values)
    normals = values.get("tip_normals") if isinstance(values.get("tip_normals"), dict) else {}
    rows = [row for row in values.get("placement") or [] if isinstance(row, dict)]
    entry: Dict[str, Any] = {"applied": False, "reason": "", "max_shift_mm": None, "moved": 0,
                             "radius_mm": None, "passes": None,
                             "inverted": normals.get("inverted"), "off_60": normals.get("off_60"),
                             "region_mm": normals.get("region_mm"), **_levelled_sides(rows)}
    status = str(values.get("status") or ("applied" if rows else "not_found"))
    if status not in ("applied", ""):
        entry["reason"] = f"Tip part not built: {values.get('reason') or status}"
    elif smooth is None:
        entry["reason"] = "Not smoothed"
    else:
        entry.update(max_shift_mm=smooth.get("max_shift_mm"), moved=int(smooth.get("moved") or 0),
                     radius_mm=round(float(smooth.get("radius_m") or 0) * 1000, 2),
                     passes=smooth.get("iterations"))
        entry["applied"] = entry["moved"] > 0
        if smooth.get("error"):
            entry["reason"] = f"Source bump not levelled: {smooth['error']}"
        elif not entry["applied"]:
            entry["reason"] = "Already smooth — nothing moved"
    return entry


#: The reason of a neutralised group (Ruling A44; only the mesh since Ruling A53).
NEUTRALISED_REASON = "Smoothed — part is off"


def tip_neutral_group(values: Dict[str, Any]) -> Dict[str, Any]:
    """One switched-off group's entry of the record (Ruling A44) from the extension script's metrics of that group
    (pure): ``mode`` neutralised, the levelling's numbers, per side ``height_mm`` (the mesh's own tip above its
    surroundings, [before, after]) and ``bump_mm`` (the source bump above the fitted surface, [before, after]);
    ``applied`` when anything moved. The texture is never touched (Ruling A53)."""
    values = values if isinstance(values, dict) else {}
    smooth = values.get("source_smooth") if isinstance(values.get("source_smooth"), dict) else None
    normals = values.get("tip_normals") if isinstance(values.get("tip_normals"), dict) else {}
    rows = [row for row in values.get("placement") or [] if isinstance(row, dict)]
    entry: Dict[str, Any] = {"mode": "neutralised", "applied": False, "reason": "", "max_shift_mm": None, "moved": 0,
                             "radius_mm": None, "passes": None,
                             "inverted": normals.get("inverted"), "off_60": normals.get("off_60"),
                             "region_mm": normals.get("region_mm"),
                             "height_mm": [[row.get("height_before_mm"), row.get("height_after_mm")] for row in rows],
                             "bump_mm": _levelled_sides(rows)["bump_mm"]}
    if values.get("status") != "neutralised":
        entry["reason"] = str(values.get("reason") or "Nothing located where the part would sit — nothing changed")
        return entry
    if smooth:
        entry.update(max_shift_mm=smooth.get("max_shift_mm"), moved=int(smooth.get("moved") or 0),
                     radius_mm=round(float(smooth.get("radius_m") or 0) * 1000, 2), passes=smooth.get("iterations"))
    entry["applied"] = entry["moved"] > 0
    entry["reason"] = NEUTRALISED_REASON
    return entry


def tip_smoothing_record(metrics: Dict[str, Any], tip_ids: List[str], at: str,
                         neutral_ids: List[str] = ()) -> Dict[str, Any]:
    """The record of a published extension build whose switched-on ``pair_tip`` groups are ``tip_ids`` and whose
    switched-off, neutralised ones are ``neutral_ids`` (pure)."""
    groups = {gid: tip_smoothing_group((metrics or {}).get(gid) or {}) for gid in tip_ids}
    groups.update({gid: tip_neutral_group((metrics or {}).get(gid) or {}) for gid in neutral_ids})
    return {"version": TIP_SMOOTHING_VERSION, "at": at, "status": "built", "error": "", "groups": groups}


def tip_smoothing_failed(previous: Any, error: str, at: str) -> Dict[str, Any]:
    """The record after an extension build of the tip groups that published nothing: the model keeps what it had
    (the previous groups stay listed); ``status`` failed with the reason, not due again until a rebuild is asked
    for (no retry loop in automatic Builds)."""
    groups = (previous or {}).get("groups") if isinstance(previous, dict) else None
    return {"version": TIP_SMOOTHING_VERSION, "at": at, "status": "failed", "error": error or "Extension rebuild failed",
            "groups": dict(groups or {})}


def tip_smoothing_due(record: Any, tip_ids: List[str], neutral_ids: List[str] = ()) -> bool:
    """Whether a base model with the switched-on ``pair_tip`` groups ``tip_ids`` and the switched-off, neutralised
    ones ``neutral_ids`` needs its tip smoothing: no record, a record of an older version, or one that does not cover
    every group in the mode its switch asks for (pure). False without such groups."""
    if not tip_ids and not neutral_ids:
        return False
    if not isinstance(record, dict):
        return True
    try:
        version = int(record.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < TIP_SMOOTHING_VERSION:
        return True
    if record.get("status") == "failed":
        return False
    groups = record.get("groups") if isinstance(record.get("groups"), dict) else {}
    mode = lambda gid: (groups.get(gid) or {}).get("mode", "smoothed") if isinstance(groups.get(gid), dict) else None
    return (any(mode(gid) != "smoothed" for gid in tip_ids)
            or any(mode(gid) != "neutralised" for gid in neutral_ids))


def _mm(value: Any) -> str:
    return f"{float(value):.1f}"


def tip_smoothing_summary(record: Optional[Dict[str, Any]], due: bool) -> Tuple[str, str]:
    """``(light, text)`` of the record (English, the model step's detail; the tab builds its own translated line):
    ``ok`` applied · ``warn`` due · ``error`` the last build failed · ``off`` nothing to smooth."""
    if not isinstance(record, dict) or due and int(record.get("version") or 0) < TIP_SMOOTHING_VERSION:
        return "warn", "Not applied to this model yet — rebuilds the extension bones (local, no hub job)"
    if record.get("status") == "failed":
        return "error", f"Last rebuild failed: {record.get('error') or 'unknown error'}"
    groups = [g for g in (record.get("groups") or {}).values() if isinstance(g, dict)]
    if due:
        return "warn", "A tip part is not covered yet — rebuilds the extension bones (local, no hub job)"
    neutral = [g for g in groups if g.get("mode") == "neutralised"]
    groups = [g for g in groups if g.get("mode") != "neutralised"]
    applied = [g for g in groups if g.get("applied")]
    if neutral:
        # A switched-off part (Ruling A44): its own reason, then the switched-on parts' line, if any.
        texts = sorted({str(g.get("reason") or NEUTRALISED_REASON) for g in neutral})
        if groups:
            light, text = tip_smoothing_summary({**record, "groups": {str(i): g for i, g in enumerate(groups)}}, False)
            texts.append(text)
        light = "ok" if all(g.get("applied") for g in neutral) and (not groups or light == "ok") else "off"
        return light, "; ".join(texts)
    if not applied:
        reasons = sorted({str(g.get("reason") or "Not smoothed") for g in groups})
        return "off", "; ".join(reasons) or "Not smoothed"
    shift = max(float(g.get("max_shift_mm") or 0) for g in applied)
    text = f"Applied — max shift {_mm(shift)} mm"
    inverted = [g.get("inverted") for g in applied if isinstance(g.get("inverted"), list) and len(g["inverted"]) == 2]
    if inverted:
        text += f", inverted normals {sum(i[0] for i in inverted)} → {sum(i[1] for i in inverted)}"
    return "ok", text


def smoothing_ids(groups: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """``(tip_ids, neutral_ids)`` of resolved ``pair_tip`` groups: the switched-on ones, and the switched-off ones
    whose declaration leaves a neutral surface (``when_off: neutralise``, Ruling A44)."""
    tips = [g for g in groups if g.get("op") == "pair_tip"]
    return ([g["id"] for g in tips if g.get("enabled")],
            [g["id"] for g in tips if not g.get("enabled") and g.get("when_off") == "neutralise"])


def tip_smoothing_state(character_name: str, signature: str) -> Optional[Dict[str, Any]]:
    """The Base body tab's tip smoothing row of the stored base model ``signature``: ``{groups: [{id, label}],
    record, due, light, summary, running, last}``; None without a stored humanoid base model or when it carries no
    switched-on ``pair_tip`` group and no switched-off one that leaves a neutral surface (the row is hidden). ``running`` / ``last``: the extension rebuild of the
    character ("Smooth again" = ``start_tip_rebuild``). Never raises (None)."""
    from app.core.model3d import _mesh_repair_target, _read_sidecar, find_model3d, required_rig
    try:
        path = find_model3d(character_name, signature) if signature else None
        if path is None:
            return None
        meta = _read_sidecar(path)
        meta.setdefault("rig", required_rig(character_name))
        if not _mesh_repair_target(meta, path):
            return None
        groups = _tip_groups(character_name, signature, meta=meta)
    except Exception:  # noqa: BLE001 — the poll never fails on the row
        logger.exception("Tip smoothing state of %s (%s) failed", character_name, signature)
        return None
    tip_ids, neutral_ids = smoothing_ids(groups)
    groups = [g for g in groups if g["id"] in tip_ids or g["id"] in neutral_ids]
    if not groups:
        return None
    record = meta.get("tip_smoothing") if isinstance(meta.get("tip_smoothing"), dict) else None
    due = tip_smoothing_due(record, tip_ids, neutral_ids)
    light, text = tip_smoothing_summary(record, due)
    with _lock:
        running = _running.get(character_name) == signature
        last = dict(_results.get(character_name) or {})
    return {"groups": [{"id": g["id"], "label": g.get("label") or g["id"],
                        "mode": "neutralised" if g["id"] in neutral_ids else "smoothed"} for g in groups],
            "record": record, "due": due, "light": light, "summary": text, "running": running,
            "last": last if last.get("signature") == signature else None,
            "version": TIP_SMOOTHING_VERSION}


def model_tip_smoothing_due(character_name: str, path, meta: Dict[str, Any]) -> bool:
    """Whether the stored base model ``path`` (sidecar ``meta``) needs its tip smoothing (``tip_smoothing_due`` over
    its switched-on ``pair_tip`` groups and its neutralised switched-off ones). False for any other model, after a
    failed extension build (its own row says so) and when the groups cannot be read."""
    from app.core.model3d import _mesh_repair_target
    if not _mesh_repair_target(meta, path) or (meta.get("extension_rig") or {}).get("status") == "failed":
        return False
    try:
        tip_ids, neutral_ids = smoothing_ids(_tip_groups(character_name, path.stem, meta=meta))
    except Exception:  # noqa: BLE001 — a due check never fails the caller
        logger.debug("Tip groups of %s (%s) not readable", character_name, path, exc_info=True)
        return False
    return tip_smoothing_due(meta.get("tip_smoothing"), tip_ids, neutral_ids)
