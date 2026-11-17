"""Declared channels — the ``channel`` regions a package declares on a body slot, resolved per model into the bind
space of its collision record (collision version 7; spec
``docs/superpowers/specs/2026-11-13-cross-person-collision-design.md`` Part 4, plan Task 12).

A channel is an inside capsule another figure's chain may enter: the declaration (``extension_rig.
region_declarations_for``) names its owning joint, its opening and inward axis in the BODY FRAME (``body_frame``),
its depth / radius / funnel, and the ops whose chains it accepts. This module turns that into the record the
renderers read (``collision.py`` "CHANNELS (version 7)"), with

- the PLACEMENT: ``declared`` = owning joint + ``offset`` along the frame, axis = ``axis`` in the frame; ``rig`` =
  the ``opening`` the region's ``from_rig`` op reports in its build metrics (``extension_rig.metrics[rig].opening``,
  bind space) gives the opening CENTRE, and the axis is the declared ``axis`` read in the PELVIS frame
  (``pelvis_frame``: the pelvis' own up Hips → Spine; Ruling A193 — the reported surface normal is not anatomical and
  measured 10° forward to 67° sideways on six bodies). A ``from_rig`` region whose rig reports no opening (not built on this model, an older build, or no
  pocket left after levelling) gets NO channel — the reason is listed in ``channels_skipped`` (the panel shows it);
  it never falls back to the declared offset;
- the per-character OVERRIDE (``model3d_opts.collision_channels[<channel id>]``, ``validate_overrides``): an offset in
  mm along the frame axes added to the opening, a radius scale, a depth scale, the funnel half-angle and the axis
  tilt ``tilt_deg`` (turned about the frame's side axis, + = toward the back, ±45°; Ruling A193);
- EXPOSURE: an ``exposed_only`` channel exists only on a model whose worn pieces leave its slot uncovered
  (``extension_rig.hides_exposed_detail`` over the model's ``pieces`` — the item's ``exposed_detail`` switch shows it
  through); a base model is exposed. Exposure is identity: it is applied whenever a record is written (fit, relabel,
  apply) and is NOT part of ``channels_sig``;
- SUPPRESS: the receiving body's capsules a link tip inside the channel skips — every capsule whose bind-pose segment
  comes within its radius + the channel radius of the channel segment ``a_pos → b_pos``, plus every capsule whose
  start joint is the owning joint, in payload order.

``wanted_channels`` gives the inputs and their hash ``channels_sig`` (declarations with resolved attribute values,
the overrides and the opening); ``resolve_channels`` is pure over a GLB and a capsule list.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("collision")

#: The per-character override (``validate_overrides``): offset per frame axis in mm, the two scales, the cone.
OVERRIDE_KEYS = ("offset_mm", "radius_scale", "depth_scale", "cone_deg")
#: The optional override key (Ruling A193): the axis turned about the frame's side axis, degrees, + = toward the back.
TILT_KEY = "tilt_deg"
TILT_DEG_MAX = 45.0
OFFSET_MM_MAX = 50.0
OVERRIDE_SCALE_MIN, OVERRIDE_SCALE_MAX = 0.5, 2.0
CONE_DEG_MAX = 60.0
#: The joints of the body frame (``body_frame``), base names.
FRAME_JOINTS = ("Hips", "Head", "LeftArm", "RightArm", "LeftFoot", "LeftToeBase")
#: The joints of the pelvis frame (``pelvis_frame``): Hips, then the first spine joint the rig has.
PELVIS_JOINTS = ("Hips", "Spine", "Spine1")
#: ``channels_skipped`` reason of an ``exposed_only`` channel a worn piece covers.
COVERED = "Covered by the worn outfit"
#: ``declarations_info``'s reason of every channel while the character has no base model to place it on.
NO_MODEL = "No base model yet"


def _unit(vector: np.ndarray, what: str) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if not math.isfinite(length) or length < 1e-9:
        raise ValueError(f"degenerate {what}")
    return vector / length


def body_frame(joints: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """The body frame the declarations use, from bind joint positions (keys compared after ``norm_bone_name``):
    ``up`` = unit(Head − Hips); ``side`` = unit(LeftArm − RightArm without its component along ``up``); ``front`` =
    side × up, flipped when its dot with (LeftToeBase − LeftFoot) is negative (the feet point forward). ValueError
    when a joint is missing or the frame degenerates."""
    from app.core.rig_contract import norm_bone_name
    by_key = {norm_bone_name(str(name)): np.asarray(value, np.float64) for name, value in joints.items()}
    missing = [name for name in FRAME_JOINTS if norm_bone_name(name) not in by_key]
    if missing:
        raise ValueError("joint " + " and ".join(missing) + " missing")
    j = {name: by_key[norm_bone_name(name)] for name in FRAME_JOINTS}
    up = _unit(j["Head"] - j["Hips"], "body axis (Hips → Head)")
    across = j["LeftArm"] - j["RightArm"]
    side = _unit(across - (across @ up) * up, "side axis (RightArm → LeftArm)")
    front = np.cross(side, up)
    if float(front @ (j["LeftToeBase"] - j["LeftFoot"])) < 0:
        front = -front
    return {"side": side, "up": up, "front": front}


def pelvis_frame(joints: Dict[str, np.ndarray], frame: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """The PELVIS frame a ``from_rig`` channel's axis is read in (Ruling A193): ``side`` of the body frame,
    ``up`` = unit(Spine − Hips without its component along ``side``; Spine1 on a rig without Spine) — the
    pelvis' own tilt, not the trunk's — and ``front`` = side × up, on the body frame's front side. ValueError
    without Hips or a spine joint."""
    from app.core.rig_contract import norm_bone_name
    by_key = {norm_bone_name(str(name)): np.asarray(value, np.float64) for name, value in joints.items()}
    spine = next((by_key[k] for k in (norm_bone_name(n) for n in PELVIS_JOINTS[1:]) if k in by_key), None)
    if norm_bone_name("Hips") not in by_key or spine is None:
        raise ValueError("joint Hips or Spine missing")
    side = frame["side"]
    rise = spine - by_key[norm_bone_name("Hips")]
    up = _unit(rise - (rise @ side) * side, "pelvis axis (Hips → Spine)")
    front = np.cross(side, up)
    if float(front @ frame["front"]) < 0:
        front = -front
    return {"side": side, "up": up, "front": front}


def tilted(axis: np.ndarray, side: np.ndarray, tilt_deg: float) -> np.ndarray:
    """``axis`` turned about ``side`` by ``tilt_deg`` toward the back (−front, with front = side × up): Rodrigues'
    rotation by −tilt about ``side``."""
    t = -math.radians(tilt_deg)
    k = side / np.linalg.norm(side)
    return axis * math.cos(t) + np.cross(k, axis) * math.sin(t) + k * float(k @ axis) * (1.0 - math.cos(t))


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number")
    return float(value)


def validate_overrides(raw: Any) -> Dict[str, Dict[str, Any]]:
    """The per-character channel overrides, ``{<channel id>: {offset_mm: [side, up, front], radius_scale,
    depth_scale, cone_deg, tilt_deg}}`` — every key but ``tilt_deg`` required (absent = 0, always written back);
    offsets within ±50 mm, the scales within [0.5, 2], ``cone_deg`` within (0, 60], ``tilt_deg`` within ±45.
    ValueError otherwise. An id no declaration names any more is kept (the declaration may come
    back). None = no overrides."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("channel overrides must be a channel id -> override map")
    out: Dict[str, Dict[str, Any]] = {}
    for channel_id, value in raw.items():
        if not isinstance(channel_id, str) or not channel_id:
            raise ValueError("a channel id must be a non-empty string")
        if not isinstance(value, dict) or set(value) - {TILT_KEY} != set(OVERRIDE_KEYS):
            raise ValueError(f"the override of '{channel_id}' needs exactly {', '.join(OVERRIDE_KEYS)} "
                             f"(and optionally {TILT_KEY})")
        offset = value["offset_mm"]
        if not isinstance(offset, (list, tuple)) or len(offset) != 3:
            raise ValueError(f"offset_mm of '{channel_id}' must be [side, up, front]")
        offset = [_number(v, f"offset_mm of '{channel_id}'") for v in offset]
        if any(abs(v) > OFFSET_MM_MAX for v in offset):
            raise ValueError(f"offset_mm of '{channel_id}' must be within ±{OFFSET_MM_MAX:g} mm")
        scales = {}
        for key in ("radius_scale", "depth_scale"):
            scale = _number(value[key], f"{key} of '{channel_id}'")
            if not OVERRIDE_SCALE_MIN <= scale <= OVERRIDE_SCALE_MAX:
                raise ValueError(f"{key} of '{channel_id}' must be between {OVERRIDE_SCALE_MIN} and "
                                 f"{OVERRIDE_SCALE_MAX}")
            scales[key] = round(scale, 3)
        cone = _number(value["cone_deg"], f"cone_deg of '{channel_id}'")
        if not 0 < cone <= CONE_DEG_MAX:
            raise ValueError(f"cone_deg of '{channel_id}' must be within (0, {CONE_DEG_MAX:g}]")
        tilt = _number(value.get(TILT_KEY, 0.0), f"{TILT_KEY} of '{channel_id}'")
        if abs(tilt) > TILT_DEG_MAX:
            raise ValueError(f"{TILT_KEY} of '{channel_id}' must be within ±{TILT_DEG_MAX:g}°")
        out[channel_id] = {"offset_mm": [round(v, 2) for v in offset], **scales, "cone_deg": round(cone, 2),
                           TILT_KEY: round(tilt, 2)}
    return out


def _profile(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    try:
        from app.models.character import get_character_profile
        return get_character_profile(character_name) or {}
    except Exception:  # noqa: BLE001 — no declarations rather than no record
        return {}


def character_overrides(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The character's stored overrides (``model3d_opts.collision_channels``); an invalid stored map counts as none."""
    profile = _profile(character_name, profile)
    try:
        return validate_overrides((profile.get("model3d_opts") or {}).get("collision_channels"))
    except ValueError as exc:
        logger.warning("Channel overrides of %s ignored: %s", character_name, exc)
        return {}


def _any_region_declared() -> bool:
    from app.plugins.registry import packages
    return any(slot.regions for package in packages() for slot in package.body_slots)


def _opening(state: Any, rig: str) -> Tuple[Optional[Dict[str, List[float]]], str]:
    """The ``opening`` metric of the built rig ``rig`` on a model (``extension_rig`` sidecar record), or the reason
    there is none."""
    if not isinstance(state, dict) or state.get("status") != "applied" or rig not in (state.get("groups") or []):
        return None, f"Rig {rig} is not built on this model"
    opening = ((state.get("metrics") or {}).get(rig) or {}).get("opening")
    try:
        centre = [_number(v, "centre") for v in opening["centre"]]
        axis = [_number(v, "axis") for v in opening["axis"]]
        if len(centre) != 3 or len(axis) != 3 or math.hypot(*axis) < 1e-9:
            raise ValueError("opening")
    except (TypeError, KeyError, ValueError):
        return None, f"Rig {rig} reports no opening (an older build, or no pocket left after levelling)"
    return {"centre": centre, "axis": axis}, ""


def wanted_channels(character_name: str, path: Optional[Path], meta: Dict[str, Any], *,
                    profile: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], str]:
    """The channels the model ``path`` (sidecar ``meta``) should carry, before exposure: every applicable region
    declaration with its resolved attribute values (``region_declarations_for``), the character's override
    (``override``, None without one) and, for a ``from_rig`` region, the rig's reported ``opening`` (None plus
    ``opening_reason`` without one) — and ``channels_sig``, the sha256 of that list. Exposure is NOT in the sig."""
    wanted: List[Dict[str, Any]] = []
    if _any_region_declared():
        from app.core.extension_rig import region_declarations_for
        profile = _profile(character_name, profile)
        overrides = character_overrides(character_name, profile=profile)
        state = meta.get("extension_rig")
        for declaration in region_declarations_for(character_name, profile):
            entry = {key: declaration[key] for key in (
                "id", "bone", "offset", "axis", "depth", "radius", "cone_deg", "funnel", "accepts", "min_length",
                "compress_min", "interaction_kinds", "exposed_only", "covered_by", "from_rig")}
            entry["override"] = overrides.get(declaration["id"])
            if declaration["from_rig"]:
                entry["opening"], entry["opening_reason"] = _opening(state, declaration["from_rig"])
            wanted.append(entry)
    blob = json.dumps(wanted, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return wanted, hashlib.sha256(blob.encode("utf-8")).hexdigest()


def exposure(meta: Dict[str, Any], *, items: Optional[Dict[str, Any]] = None) -> Callable[[Dict[str, Any]], bool]:
    """Whether a wanted channel exists on the model of ``meta``: a channel that is not ``exposed_only`` always; a
    base model (``meta.base``) or a model without worn ``pieces`` is exposed; otherwise the channel exists unless a
    worn piece covers its slot without showing the detail through (``extension_rig.hides_exposed_detail``)."""
    pieces = dict(meta.get("pieces") or {}) if not meta.get("base") else {}
    if not pieces:
        return lambda entry: True
    from app.core.extension_rig import hides_exposed_detail
    cache: Dict[str, Any] = {"items": items}

    def exposed(entry: Dict[str, Any]) -> bool:
        if not entry.get("exposed_only"):
            return True
        if cache["items"] is None:
            from app.core.motion_item_cache import item_snapshot
            cache["items"] = item_snapshot()
        return not hides_exposed_detail([{"exposed_only": True, "covered_by": list(entry.get("covered_by") or [])}],
                                        pieces, cache["items"])
    return exposed


def _segment_distance(p0: np.ndarray, p1: np.ndarray, q0: np.ndarray, q1: np.ndarray) -> float:
    """The closest distance between the segments p0→p1 and q0→q1 (either may be a point)."""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = float(d1 @ d1), float(d2 @ d2), float(d2 @ r)
    if a < 1e-18 and e < 1e-18:
        return float(np.linalg.norm(r))
    if a < 1e-18:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = float(d1 @ r)
        if e < 1e-18:
            s, t = min(max(-c / a, 0.0), 1.0), 0.0
        else:
            b = float(d1 @ d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-18 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                s, t = min(max(-c / a, 0.0), 1.0), 0.0
            elif t > 1.0:
                s, t = min(max((b - c) / a, 0.0), 1.0), 1.0
    return float(np.linalg.norm((p0 + d1 * s) - (q0 + d2 * t)))


def _point(values: List[float]) -> List[float]:
    return [round(float(v), 4) for v in values]


def resolve_channels(rigged_glb: bytes, capsules: List[Dict[str, Any]], wanted: List[Dict[str, Any]], *,
                     exposed: Callable[[Dict[str, Any]], bool]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(channels, skipped)`` of the wanted channels on a rigged GLB with the capsule set ``capsules`` (pure; module
    docstring). One record per exposed channel, ``{id, kind "channel", a, b, a_pos, b_pos, r, cone_deg, funnel,
    accepts, min_length, compress_min, interaction_kinds?, suppress, frame {side, up, front}, placement "rig" |
    "declared", applied}`` — ``a`` = ``b`` = the owning joint as in the model, ``a_pos`` the opening, ``b_pos`` the
    bottom (opening + axis · depth), both bind space fixed to the joint (the ENDPOINT RULE); ``applied`` the override
    used (None without one). ``skipped``: ``[{id, reason}]`` — covered, a missing joint, a rig without an opening.
    ValueError for a file without a skin."""
    from app.core.collision import bind_joints, capsule_segment
    from app.core.rig_contract import norm_bone_name
    names, index_of, positions = bind_joints(rigged_glb)
    frame_error = ""
    frame: Optional[Dict[str, np.ndarray]] = None
    pelvis: Optional[Dict[str, np.ndarray]] = None
    pelvis_error = ""
    try:
        frame = body_frame({name: positions[index_of[norm_bone_name(name)]] for name in FRAME_JOINTS
                            if norm_bone_name(name) in index_of})
    except ValueError as exc:
        frame_error = f"No body frame: {exc}"
    if frame is not None:
        try:
            pelvis = pelvis_frame({name: positions[index_of[norm_bone_name(name)]] for name in PELVIS_JOINTS
                                   if norm_bone_name(name) in index_of}, frame)
        except ValueError as exc:
            pelvis_error = f"No pelvis frame: {exc}"
    segments = [(capsule, capsule_segment(capsule, index_of, positions)) for capsule in capsules or []]
    channels: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for entry in wanted:
        channel_id = str(entry["id"])
        if not exposed(entry):
            skipped.append({"id": channel_id, "reason": COVERED})
            continue
        owner = norm_bone_name(str(entry["bone"]))
        index = index_of.get(owner)
        if index is None:
            skipped.append({"id": channel_id, "reason": f"joint {entry['bone']} missing"})
            continue
        if frame is None:
            skipped.append({"id": channel_id, "reason": frame_error})
            continue
        basis = np.stack([frame["side"], frame["up"], frame["front"]])
        if entry.get("from_rig"):
            opening = entry.get("opening")
            if not opening:
                skipped.append({"id": channel_id, "reason": str(entry.get("opening_reason") or "No opening")})
                continue
            if pelvis is None:
                skipped.append({"id": channel_id, "reason": pelvis_error})
                continue
            # The opening's CENTRE comes from the build; its surface normal does not set the axis (Ruling A193:
            # measured 10° forward to 67° sideways on six bodies). The axis is the declared one in the pelvis frame.
            a_pos = np.asarray(opening["centre"], np.float64)
            axis = _unit(np.asarray(entry["axis"], np.float64) @ np.stack([pelvis["side"], pelvis["up"],
                                                                            pelvis["front"]]), "channel axis")
            placement = "rig"
        else:
            a_pos = positions[index] + np.asarray(entry["offset"], np.float64) @ basis
            axis = _unit(np.asarray(entry["axis"], np.float64) @ basis, "channel axis")
            placement = "declared"
        depth, radius, cone = float(entry["depth"]), float(entry["radius"]), float(entry["cone_deg"])
        override = entry.get("override") or None
        if override:
            a_pos = a_pos + (np.asarray(override["offset_mm"], np.float64) / 1000.0) @ basis
            depth *= float(override["depth_scale"])
            radius *= float(override["radius_scale"])
            cone = float(override["cone_deg"])
            axis = tilted(axis, frame["side"], float(override.get(TILT_KEY, 0.0)))
        b_pos = a_pos + axis * depth
        suppress = []
        for capsule, segment in segments:
            if norm_bone_name(str(capsule.get("a") or "")) == owner:
                suppress.append(str(capsule.get("id") or ""))
            elif segment is not None and (_segment_distance(segment[0], segment[1], a_pos, b_pos)
                                          <= float(capsule.get("r") or 0) + radius + 1e-9):
                suppress.append(str(capsule.get("id") or ""))
        record: Dict[str, Any] = {
            "id": channel_id, "kind": "channel", "a": names[index], "b": names[index],
            "a_pos": _point(a_pos), "b_pos": _point(b_pos), "r": round(radius, 4), "cone_deg": round(cone, 2),
            "funnel": float(entry["funnel"]), "accepts": list(entry["accepts"]),
            "min_length": float(entry["min_length"]), "compress_min": float(entry["compress_min"])}
        if entry.get("interaction_kinds") is not None:
            record["interaction_kinds"] = list(entry["interaction_kinds"])
        record.update({"suppress": suppress,
                       "frame": {key: [round(float(v), 6) for v in frame[key]] for key in ("side", "up", "front")},
                       "placement": placement, "applied": dict(override) if override else None})
        channels.append(record)
    return channels, skipped


def filter_exposed(record: Dict[str, Any], wanted: List[Dict[str, Any]],
                   exposed: Callable[[Dict[str, Any]], bool]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """An inherited record's channels re-filtered by THIS model's exposure (the relabel path): ``(channels,
    skipped)`` — a channel no wanted declaration names is dropped, a covered one moves to ``skipped`` (``COVERED``),
    and every ``suppress`` list keeps only the ids of the record's capsules."""
    by_id = {str(entry["id"]): entry for entry in wanted}
    present = {str(capsule.get("id") or "") for capsule in record.get("capsules") or []}
    channels: List[Dict[str, Any]] = []
    skipped = [dict(s) for s in record.get("channels_skipped") or [] if isinstance(s, dict)
               and s.get("reason") != COVERED and str(s.get("id")) in by_id]
    for channel in record.get("channels") or []:
        entry = by_id.get(str(channel.get("id")))
        if entry is None:
            continue
        if not exposed(entry):
            skipped.append({"id": str(channel["id"]), "reason": COVERED})
            continue
        channels.append({**channel, "suppress": [c for c in channel.get("suppress") or [] if c in present]})
    for entry in wanted:
        if not exposed(entry) and entry["id"] not in {s["id"] for s in skipped}:
            skipped.append({"id": str(entry["id"]), "reason": COVERED})
    order = {str(entry["id"]): i for i, entry in enumerate(wanted)}
    skipped.sort(key=lambda s: order.get(str(s["id"]), len(order)))
    return channels, skipped


def declarations_info(character_name: str, path: Optional[Path], meta: Dict[str, Any], *,
                      profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """What the Channels panel lists for the model ``path``: every wanted channel (``wanted_channels``) with
    ``placement`` ("rig" / "declared" from the stored record) or, without a channel on the model, the ``reason`` of
    ``channels_skipped`` ("Not computed" before the record has channels). ``path`` None (no base model yet): the
    declarations alone, each with ``reason`` ``NO_MODEL`` and no placement. Never raises (empty list)."""
    try:
        wanted, _sig = wanted_channels(character_name, path, meta, profile=profile)
    except Exception:  # noqa: BLE001 — the poll never fails on the panel
        logger.exception("Channel declarations of %s failed", character_name)
        return []
    record = meta.get("collision") if isinstance(meta.get("collision"), dict) else {}
    placed = {str(c.get("id")): c for c in record.get("channels") or [] if isinstance(c, dict)}
    reasons = {str(s.get("id")): str(s.get("reason") or "") for s in record.get("channels_skipped") or []
               if isinstance(s, dict)}
    out = []
    for entry in wanted:
        channel = placed.get(entry["id"])
        info = {key: entry[key] for key in ("id", "bone", "offset", "axis", "depth", "radius", "cone_deg", "funnel",
                                            "accepts", "min_length", "compress_min", "exposed_only", "from_rig")}
        info["placement"] = channel.get("placement") if channel else None
        info["reason"] = (NO_MODEL if path is None else "" if channel
                          else reasons.get(entry["id"], "Not computed"))
        out.append(info)
    return out
