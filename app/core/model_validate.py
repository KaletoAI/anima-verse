"""Validation of uploaded 3D character models (dependency-free).

The contract a 3D client relies on:

* humanoid  -> ONE .glb: 52-bone Mixamo rig, mesh AND textures embedded.
* generic   -> a rigged .fbx PLUS its basecolor .png (an FBX embeds no
  texture, and the PNG belongs to exactly that mesh — same run).

Both failure modes below have been seen in the wild and are silent:
a GLB whose only texture is a 2x2 placeholder (a known generation glitch —
the model renders flat grey), and an FBX shipped without its PNG.

Pure stdlib: a GLB is a 12-byte header + a JSON chunk + a BIN chunk, so the
structure can be read without a glTF library.
"""
import json
import struct
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

MIXAMO_JOINT_COUNT = 52
# A texture this small is never real content — it is the known "empty texture"
# artefact of a failed bake.
MIN_TEXTURE_DIM = 8


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) of a PNG from its IHDR, or None if it isn't a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) of a JPEG from its first SOF marker, or None."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h)
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return None


def _image_size(data: bytes) -> Optional[Tuple[int, int]]:
    return _png_size(data) or _jpeg_size(data)


def parse_glb(data: bytes) -> Dict[str, Any]:
    """Reads the glTF JSON + embedded image sizes out of a GLB container."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file (magic missing)")
    _magic, version, _length = struct.unpack("<III", data[:12])
    if version != 2:
        raise ValueError(f"unsupported glTF version: {version}")

    gltf: Dict[str, Any] = {}
    bin_chunk = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack("<II", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + chunk_len]
        if chunk_type == 0x4E4F534A:      # 'JSON'
            gltf = json.loads(body.decode("utf-8"))
        elif chunk_type == 0x004E4942:    # 'BIN'
            bin_chunk = body
        offset += 8 + chunk_len + ((4 - chunk_len % 4) % 4)

    views = gltf.get("bufferViews") or []
    images: List[Dict[str, Any]] = []
    for img in (gltf.get("images") or []):
        entry: Dict[str, Any] = {"name": img.get("name", "")}
        idx = img.get("bufferView")
        if idx is not None and 0 <= idx < len(views):
            bv = views[idx]
            start = int(bv.get("byteOffset", 0))
            end = start + int(bv.get("byteLength", 0))
            size = _image_size(bin_chunk[start:end])
            entry["embedded"] = True
            entry["size"] = size
        else:
            # An external URI is not embedded — the client would have to fetch
            # a file we do not ship.
            entry["embedded"] = False
            entry["uri"] = img.get("uri", "")
        images.append(entry)

    joints: List[str] = []
    nodes = gltf.get("nodes") or []
    skins = gltf.get("skins") or []
    if skins:
        for j in (skins[0].get("joints") or []):
            if 0 <= j < len(nodes):
                joints.append(str(nodes[j].get("name", "")))
    return {"gltf": gltf, "images": images, "joints": joints,
            "joint_count": len(joints)}


def validate_glb(data: bytes) -> Dict[str, Any]:
    """Validates a humanoid GLB: 52-joint Mixamo rig + a real embedded texture.

    Returns {"ok", "errors": [...], "warnings": [...], "joint_count", "rig"}.
    """
    errors: List[str] = []
    warnings: List[str] = []
    try:
        info = parse_glb(data)
    except (ValueError, KeyError, struct.error, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"GLB unreadable: {e}"],
                "warnings": [], "joint_count": 0, "rig": "generic"}

    joints = info["joints"]
    count = info["joint_count"]
    mixamo = sum(1 for j in joints if "mixamorig" in j.lower())
    if count == 0:
        errors.append("no skin/skeleton in the GLB — the model cannot be animated")
    elif count != MIXAMO_JOINT_COUNT:
        errors.append(
            f"{count} joints instead of {MIXAMO_JOINT_COUNT} — not the Mixamo rig")
    if count and not mixamo:
        warnings.append("no 'mixamorig' joint names — a foreign rig with the "
                        "same joint count will not match the animation clips")

    embedded = [i for i in info["images"] if i.get("embedded")]
    if not info["images"]:
        errors.append("no texture in the GLB — a humanoid model must embed it")
    elif not embedded:
        errors.append("textures are referenced externally, not embedded")
    else:
        real = []
        for img in embedded:
            size = img.get("size")
            if size and max(size) < MIN_TEXTURE_DIM:
                errors.append(
                    f"texture is {size[0]}x{size[1]} px — that is the known "
                    "empty-texture artefact of a failed generation, not a result")
            elif size:
                real.append(size)
        if embedded and not real and not errors:
            warnings.append("embedded texture size could not be read")

    rig = "mixamo" if (count == MIXAMO_JOINT_COUNT and mixamo) else "generic"
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "joint_count": count, "rig": rig}


def validate_fbx(data: bytes, texture: Optional[bytes]) -> Dict[str, Any]:
    """Validates a generic FBX: it must come WITH its basecolor texture."""
    errors: List[str] = []
    warnings: List[str] = []
    if not data.startswith(b"Kaydara FBX Binary"):
        warnings.append("no binary-FBX signature — ASCII FBX may not load "
                        "in every client")
    if texture is None:
        errors.append("FBX without a texture PNG — an FBX embeds no texture, "
                      "so the basecolor image of the SAME run must be uploaded "
                      "with it")
    else:
        size = _image_size(texture)
        if not size:
            errors.append("the texture is not a readable PNG/JPEG")
        elif max(size) < MIN_TEXTURE_DIM:
            errors.append(
                f"texture is {size[0]}x{size[1]} px — that is the known "
                "empty-texture artefact of a failed generation, not a result")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "joint_count": 0, "rig": "generic"}
