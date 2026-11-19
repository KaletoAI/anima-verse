"""The MOUTH CHANNEL every humanoid carries (Ruling A203): a core extension group and a core channel declaration.

The mouth is not package content: the core declares it for every HUMANOID character (``for_character``), and it
is built on every rigged humanoid GLB that goes through the extension step (``model3d._extension_rig_once``). An
animal or any other non-humanoid has no mouth group and no mouth channel at all; a humanoid character's model of
another rig does not list them either (``model3d._extension_groups_for``, ``applies``).

- THE GROUP ``mouth_channel`` (op ``mouth_part``, Blender script ``mouth_part.py``): the skin is cut along the
  measured lip line and a closed pouch is built behind it, along the axis toward the top of the throat; the bone
  ``Jaw`` (``JAW``) opens it, the shape key ``mouth_open`` adds the upper lip's lift. Its
  ``params.override`` is the character's channel override for ``mouth`` (``model3d_opts.collision_channels``,
  without the cone, which has no geometry) — so a saved override changes the extension fingerprint and the
  extension step reads "due" until it is rebuilt (CPU only). Its ``params.teeth`` are the character's TEETH OPTIONS
  (``model3d_opts.mouth_teeth``, ``teeth_options``; Ruling A206): teeth on/off, tongue on/off, the tooth colour
  (three shades) and the size — only what differs from ``TEETH_DEFAULTS``, so a saved change makes the step due
  the same way and the Build applies it (local, 0 jobs).
- THE CHANNEL ``mouth`` (``collision_channels.wanted_channels`` appends it for a humanoid model): placed where the
  build reports its ``opening`` — centre, axis, depth and radius are the BUILT ones (``built`` = True;
  ``collision_channels.resolve_channels`` applies no override on top, the build already did, and reports the
  override the build used as ``applied``). Its id is the renderers' mouth channel id (``contactTarget.ts``
  ``MOUTH_CHANNEL_ID``), so a figure that carries it gets no formula mouth beside it, and the contact target
  ``mouth`` finds it. A model without the built opening (not rebuilt yet, or the build found no lip line) lists the
  reason in ``channels_skipped`` and keeps the renderers' measured mouth (collision ``mouth``, Ruling A193).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

#: The group's id and op; the op is also the Blender script's name.
GROUP_ID = "mouth_channel"
OP = "mouth_part"
#: The channel's id — the renderers' ``MOUTH_CHANNEL_ID``.
CHANNEL_ID = "mouth"
#: The ops whose chains may enter (the renderers' ``POINT_TARGET_OPS``).
ACCEPTS = ("attached_part", "appendage_chain")
#: The declared sizes (metres); the build's ``depth`` / ``radius`` defaults are the same numbers.
DEPTH_M = 0.08
RADIUS_M = 0.02
#: Gates as the renderers' formula mouth had them (``contactTarget.ts`` ``MOUTH``): cone, funnel, least state
#: length, least depth scale.
CONE_DEG = 35.0
FUNNEL_M = 0.03
MIN_LENGTH = 0.0
COMPRESS_MIN = 0.6
#: The jaw bone the build creates (part 3): an extension bone under Head that owns the chin, the lower lip and the
#: channel's lower wall by computed weights. No motion group drives it (``extension_rig.motion_payload`` reads the
#: packages' groups only); the renderers turn it (``mouthOpen.ts``), a clip may.
JAW = {"bone": "mixamorig:Jaw", "parent": "Head"}
#: The mouth's tilt without an override (degrees, + = toward the back; owner decision 2026-11-19): the axis is turned
#: 20 degrees about the side axis away from the throat, toward the top of the head. The Blender build's
#: ``DEFAULTS.override.tilt_deg`` and the renderers' ``contactTarget.ts`` ``MOUTH.tiltDeg`` (the measured and the
#: formula mouth of a model without the built one) are the same number (``scripts/smoke_mouth_channel.py`` [1]). A
#: STORED override keeps its absolute tilt (``validate_overrides`` writes it, 0 when absent): the build applies it
#: instead of this default. The panel shows this value as the neutral one (``declarations_info`` ``tilt_deg``).
TILT_DEFAULT_DEG = -20.0
#: The override keys the build reads (``collision_channels`` override without ``cone_deg``).
BUILD_OVERRIDE_KEYS = ("offset_mm", "radius_scale", "depth_scale", "tilt_deg")
#: The teeth options (Ruling A206) and their defaults — the Blender build's ``mouth_teeth.DEFAULTS`` agree
#: (``scripts/smoke_mouth_teeth.py``). ``shade``: 0 bright, 1 natural, 2 ivory; ``size`` within ``TEETH_SIZE``.
TEETH_DEFAULTS = {"enabled": True, "tongue": True, "shade": 1, "size": 1.0}
TEETH_SIZE = (0.8, 1.2)


def validate_teeth(raw: Any) -> Dict[str, Any]:
    """The teeth options, complete (missing keys take ``TEETH_DEFAULTS``). ValueError naming a wrong key or value;
    None = the defaults."""
    if raw is None:
        return dict(TEETH_DEFAULTS)
    if not isinstance(raw, dict) or set(raw) - set(TEETH_DEFAULTS):
        raise ValueError("teeth options are enabled, tongue, shade and size")
    out = dict(TEETH_DEFAULTS)
    for key, value in raw.items():
        if key in ("enabled", "tongue"):
            if type(value) is not bool:
                raise ValueError(f"teeth option {key} must be true or false")
        elif key == "shade":
            if type(value) is not int or value not in (0, 1, 2):
                raise ValueError("teeth shade must be 0, 1 or 2")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not TEETH_SIZE[0] <= float(value) <= TEETH_SIZE[1]:
                raise ValueError(f"teeth size must be within {TEETH_SIZE[0]}..{TEETH_SIZE[1]}")
            value = round(float(value), 2)
        out[key] = value
    return out


def teeth_options(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The character's stored teeth options, complete; an invalid stored map counts as the defaults."""
    try:
        return validate_teeth((profile.get("model3d_opts") or {}).get("mouth_teeth"))
    except ValueError:
        return dict(TEETH_DEFAULTS)


def set_teeth_options(character_name: str, raw: Any) -> Dict[str, Any]:
    """Store the teeth options (only what differs from the defaults; the defaults = nothing stored) under the
    profile lock; returns them complete. ValueError for invalid options, KeyError for an unknown character. Stores
    only — the extension step reads "due" and the Build applies it."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    options = validate_teeth(raw)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)
        if not profile:
            raise KeyError(character_name)
        opts = dict(profile.get("model3d_opts") or {})
        changed = {k: v for k, v in options.items() if v != TEETH_DEFAULTS[k]}
        if changed:
            opts["mouth_teeth"] = changed
        else:
            opts.pop("mouth_teeth", None)
        profile["model3d_opts"] = opts
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The teeth options could not be saved")
    return options


def build_override(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The part of the character's ``mouth`` channel override the build reads, {} without one (or an invalid map)."""
    from app.core.collision_channels import validate_overrides
    try:
        stored = validate_overrides((profile.get("model3d_opts") or {}).get("collision_channels")).get(CHANNEL_ID)
    except ValueError:
        return {}
    if not stored:
        return {}
    return {key: stored[key] for key in BUILD_OVERRIDE_KEYS if key in stored}


def group(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The core extension group, shaped like a package's (``dataclasses.asdict`` of a ``RigSpec``) so every reader
    of ``rig_groups_for`` finds the keys it expects; one chain (the jaw bone), no clothing slot covers it."""
    from dataclasses import asdict
    from app.plugins.registry import RigSpec
    override = build_override(profile)
    teeth = {k: v for k, v in teeth_options(profile).items() if v != TEETH_DEFAULTS[k]}
    params = {**({"override": override} if override else {}), **({"teeth": teeth} if teeth else {})}
    declared = asdict(RigSpec(id=GROUP_ID, op=OP, chains=[[dict(JAW)]], params=params))
    declared["covered_by"] = []
    return declared


def region() -> Dict[str, Any]:
    """The core channel declaration, with the keys of ``extension_rig.region_declarations_for`` plus ``built``."""
    return {"id": CHANNEL_ID, "slot": None, "bone": "Head", "offset": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, -1.0],
            "depth": DEPTH_M, "radius": RADIUS_M, "cone_deg": CONE_DEG, "funnel": FUNNEL_M,
            "accepts": list(ACCEPTS), "min_length": MIN_LENGTH, "compress_min": COMPRESS_MIN,
            "exposed_only": False, "interaction_kinds": None, "from_rig": GROUP_ID, "covered_by": [],
            "built": True}


def for_character(character_name: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character has a mouth group at all: humanoids only (the template feature ``humanoid``,
    ``model_refs.is_humanoid``; user decision 2026-11-18 — an animal gets no mouth, not a hidden one)."""
    from app.core.model_refs import is_humanoid
    return bool(is_humanoid(character_name, profile=profile))


def applies(meta: Optional[Dict[str, Any]]) -> bool:
    """Whether a model of ``meta`` is one the mouth is built on: a humanoid rig (``rig "mixamo"``). Without a model
    there is nothing to list yet."""
    return (meta or {}).get("rig") == "mixamo"
