"""The MOUTH CHANNEL every humanoid carries (Ruling A203): a core extension group and a core channel declaration.

The mouth is not package content: the core declares it for every character, and it is built on every rigged
humanoid GLB that goes through the extension step (``model3d._extension_rig_once``; a model of another rig records
"none applicable" as for any group).

- THE GROUP ``mouth_channel`` (op ``mouth_part``, Blender script ``mouth_part.py``): the skin is cut along the
  measured lip line and a closed pouch is built behind it, along the axis toward the top of the throat; the bone
  ``Jaw`` (``JAW``) opens it, the shape key ``mouth_open`` adds the upper lip's lift. Its
  ``params.override`` is the character's channel override for ``mouth`` (``model3d_opts.collision_channels``,
  without the cone, which has no geometry) — so a saved override changes the extension fingerprint and the
  extension step reads "due" until it is rebuilt (CPU only).
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
#: The override keys the build reads (``collision_channels`` override without ``cone_deg``).
BUILD_OVERRIDE_KEYS = ("offset_mm", "radius_scale", "depth_scale", "tilt_deg")


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
    declared = asdict(RigSpec(id=GROUP_ID, op=OP, chains=[[dict(JAW)]],
                              params={"override": override} if override else {}))
    declared["covered_by"] = []
    return declared


def region() -> Dict[str, Any]:
    """The core channel declaration, with the keys of ``extension_rig.region_declarations_for`` plus ``built``."""
    return {"id": CHANNEL_ID, "slot": None, "bone": "Head", "offset": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, -1.0],
            "depth": DEPTH_M, "radius": RADIUS_M, "cone_deg": CONE_DEG, "funnel": FUNNEL_M,
            "accepts": list(ACCEPTS), "min_length": MIN_LENGTH, "compress_min": COMPRESS_MIN,
            "exposed_only": False, "interaction_kinds": None, "from_rig": GROUP_ID, "covered_by": [],
            "built": True}


def applies(meta: Optional[Dict[str, Any]]) -> bool:
    """Whether a model of ``meta`` is one the mouth is built on: a humanoid rig (``rig "mixamo"``). Without a model
    there is nothing to list yet."""
    return (meta or {}).get("rig") == "mixamo"
