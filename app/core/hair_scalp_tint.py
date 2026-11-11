"""Scalp tint under a hair garment, written into the ASSEMBLED model's body texture (never the base model file).

The bald base's scalp texture is lighter than any hair: between the hair's front edge and the forehead, and through
the gaps of the hair, it showed as a light strip / light specks (Kai's subtract cut, 2026-11-11). Per hair fit, the
assembly (``garment_assembly._build``) paints the hair's median colour into the body texture where the hair covers
the skin in the FRONT view, and fades it out over ``TINT_FADE_M`` beyond the hair's edge there:

- Front raster (``TINT_CELL_M`` cells in x / y, bind space, +z = the face): per cell the front-most skin point of the
  head (Head weight > 0.5) and the front-most hair point. A cell is covered when its hair point lies in front of
  that skin, at most ``TINT_INSIDE_M`` behind it.
- A texel of a head triangle (rasterized in UV space, its 3D point interpolated) is tinted when it is skin the front
  view shows (no more than ``TINT_VISIBLE_M`` behind the cell's front-most skin) and above the brow line plus
  ``TINT_ABOVE_BROW_M`` (``garment_hairdeck.placement_landmarks``; proportions on a face-less head): weight 1 in a
  covered cell, ``1 - d / TINT_FADE_M`` at the distance ``d`` (front raster) to the nearest covered cell.
- The colour: the median of the hair's vertex colours (linear -> sRGB) or of its texture at its UVs. The texel
  becomes ``(1 - w) * texel + w * colour``; alpha is kept. Texels no triangle covers within ``TINT_PAD_PX`` of a
  tinted one take its weight (the filtering margin of the UV islands).

A GLB whose buffers are compressed (meshopt / Draco) or whose body texture is neither PNG nor JPEG is left as it is
(report ``skipped``)."""
from __future__ import annotations

import io
import json
import math
import struct
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

TINT_CELL_M = 0.001
TINT_INSIDE_M = 0.003
TINT_VISIBLE_M = 0.005
TINT_FADE_M = 0.005
TINT_ABOVE_BROW_M = 0.01
TINT_PAD_PX = 2
_UNSAFE_EXTENSIONS = ("EXT_meshopt_compression", "KHR_draco_mesh_compression", "KHR_texture_basisu")


def _srgb(linear: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(linear, np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def hair_colour_srgb(hair) -> Optional[np.ndarray]:
    """The hair's median colour, sRGB 0..255 (``GarmentMesh``: vertex colours, else its texture at its UVs)."""
    from PIL import Image
    colors = getattr(hair, "colors", None)
    if colors is not None and len(colors):
        return _srgb(np.median(np.asarray(colors, np.float64)[:, :3], 0)) * 255.0
    if not hair.image:
        return None
    rgb = np.asarray(Image.open(io.BytesIO(hair.image)).convert("RGB"), np.float64)
    h, w = rgb.shape[:2]
    uv = np.asarray(hair.uvs, np.float64)
    px = np.clip((uv[:, 0] % 1.0) * w, 0, w - 1).astype(int)
    py = np.clip((uv[:, 1] % 1.0) * h, 0, h - 1).astype(int)
    return np.median(rgb[py, px], 0)


def _front_raster(X: np.ndarray, x0: float, y0: float, shape: Tuple[int, int]) -> np.ndarray:
    ix = np.floor((X[:, 0] - x0) / TINT_CELL_M).astype(int)
    iy = np.floor((X[:, 1] - y0) / TINT_CELL_M).astype(int)
    ok = (ix >= 0) & (ix < shape[1]) & (iy >= 0) & (iy < shape[0])
    grid = np.full(shape, -np.inf)
    np.maximum.at(grid, (iy[ok], ix[ok]), X[ok, 2])
    return grid


def _texels(P: np.ndarray, F: np.ndarray, UV: np.ndarray, size: Tuple[int, int]
            ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(rows, cols, points)``: every texel centre inside a triangle of ``F`` in UV space and its 3D point."""
    h, w = size
    rows, cols, pts = [], [], []
    T = UV[F] * np.array([w, h]) - 0.5          # pixel coordinates of the corners (texel centres at integers)
    for t, f in zip(T, F):
        x0, y0 = np.floor(t.min(0)).astype(int)
        x1, y1 = np.ceil(t.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w - 1), min(y1, h - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        gx, gy = gx.ravel().astype(float), gy.ravel().astype(float)
        (ax, ay), (bx, by), (cx, cy) = t
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        l1 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        l2 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        if not inside.any():
            continue
        rows.append(gy[inside].astype(int))
        cols.append(gx[inside].astype(int))
        pts.append(l1[inside, None] * P[f[0]] + l2[inside, None] * P[f[1]] + l3[inside, None] * P[f[2]])
    if not rows:
        return np.zeros(0, int), np.zeros(0, int), np.zeros((0, 3))
    return np.concatenate(rows), np.concatenate(cols), np.concatenate(pts)


def _repack(parsed: Dict[str, Any], images: Dict[int, bytes]) -> bytes:
    """The GLB of ``parsed`` with the embedded bytes of ``images`` (image index -> PNG bytes) replaced."""
    gltf = json.loads(json.dumps(parsed["gltf"]))
    source = parsed["bin"]
    view_bytes: Dict[int, bytes] = {}
    for index, png in images.items():
        image = gltf["images"][index]
        view_bytes[int(image["bufferView"])] = png
        image["mimeType"] = "image/png"
    binary = bytearray()
    for i, view in enumerate(gltf.get("bufferViews") or []):
        offset, length = int(view.get("byteOffset", 0)), int(view["byteLength"])
        raw = view_bytes.get(i, bytes(source[offset:offset + length]))
        binary.extend(b"\0" * (-len(binary) % 4))
        view["byteOffset"] = len(binary)
        view["byteLength"] = len(raw)
        binary.extend(raw)
    binary.extend(b"\0" * (-len(binary) % 4))
    gltf["buffers"][0]["byteLength"] = len(binary)
    document = json.dumps(gltf, separators=(",", ":")).encode()
    document += b" " * (-len(document) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(document) + len(binary))
            + struct.pack("<I4s", len(document), b"JSON") + document
            + struct.pack("<I4s", len(binary), b"BIN\0") + bytes(binary))


def tint_scalp(glb: bytes, hair) -> Tuple[bytes, Dict[str, Any]]:
    """``(glb with the scalp tinted under ``hair``, report)`` — module docstring. ``hair``: the fitted hair
    ``GarmentMesh`` in the body's bind space (what ``garment_assembly`` grafts)."""
    from PIL import Image
    from scipy.ndimage import distance_transform_edt, maximum_filter
    from app.core import glb_mesh
    from app.core.garment_cut import _surface_samples
    from app.core.garment_fit import chin_height, dense_weights, joint_index
    from app.core.garment_hairdeck import FALLBACK_BROW_RATIO, placement_landmarks
    from app.core.model_validate import texture_image_index

    parsed = glb_mesh._parse(glb, "Body")
    gltf = parsed["gltf"]
    used = set(gltf.get("extensionsUsed") or []) | set(gltf.get("extensionsRequired") or [])
    if used & set(_UNSAFE_EXTENSIONS) or len(gltf.get("buffers") or []) != 1 or "uri" in gltf["buffers"][0]:
        return glb, {"skipped": "packed_buffers"}
    colour = hair_colour_srgb(hair)
    if colour is None:
        return glb, {"skipped": "no_hair_colour"}
    body = glb_mesh.body_arrays(glb)
    P = np.asarray(body.positions, np.float64)
    head_w = dense_weights(body)[:, joint_index(body, "head")]
    head_v = head_w > 0.5
    if not head_v.any():
        return glb, {"skipped": "no_head"}
    chin = chin_height(body)
    top = float(P[head_v, 1].max())
    landmarks, source, _rejected = placement_landmarks(P, head_v, chin, top)
    brow = float(landmarks["brow_y"]) if landmarks else chin + FALLBACK_BROW_RATIO * (top - chin)
    floor_y = brow + TINT_ABOVE_BROW_M

    Fall = np.asarray(body.faces, np.int64).reshape(-1, 3)
    on_head = Fall[head_v[Fall].all(1)]
    S = _surface_samples(P, on_head, TINT_CELL_M / 2)
    Hp = np.asarray(hair.positions, np.float64)
    H = _surface_samples(Hp, np.asarray(hair.indices, np.int64).reshape(-1, 3), TINT_CELL_M / 2)
    x0, y0 = float(S[:, 0].min()) - 0.01, floor_y - TINT_FADE_M - 0.01
    shape = (int(math.ceil((top + 0.01 - y0) / TINT_CELL_M)), int(math.ceil((S[:, 0].max() + 0.01 - x0) / TINT_CELL_M)))
    skin = _front_raster(S, x0, y0, shape)
    front_hair = _front_raster(H, x0, y0, shape)
    covered = np.isfinite(skin) & (front_hair >= skin - TINT_INSIDE_M)
    dist = (distance_transform_edt(~covered) * TINT_CELL_M) if covered.any() else np.full(shape, np.inf)

    prims = glb_mesh._body_prims(parsed)
    arrays = glb_mesh.body_primitive_arrays(glb)
    per_image: Dict[int, List[Tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    base = 0
    for prim, arr in zip(prims, arrays):
        n = len(arr.positions)
        uv = arr.attributes.get("TEXCOORD_0")
        material = (gltf.get("materials") or [{}])[prim["material"]] if "material" in prim else {}
        info = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if uv is not None and isinstance(info, dict):
            index = texture_image_index(gltf, gltf["textures"][info["index"]])
            f = np.asarray(arr.faces, np.int64)
            keep = head_v[base:base + n][f].all(1) & (P[base:base + n][f][:, :, 1].max(1) >= y0)
            if keep.any():
                per_image.setdefault(index, []).append((P[base:base + n], f[keep], uv))
        base += n
    report: Dict[str, Any] = {"colour_srgb": [round(float(c), 1) for c in colour], "brow_y": round(brow, 5),
                              "landmarks": source, "covered_cells": int(covered.sum()), "images": {}}
    replaced: Dict[int, bytes] = {}
    for index, parts in per_image.items():
        image = gltf["images"][index]
        if image.get("mimeType") not in ("image/png", "image/jpeg") or "bufferView" not in image:
            report["images"][index] = "skipped: " + str(image.get("mimeType"))
            continue
        view = gltf["bufferViews"][image["bufferView"]]
        start = int(view.get("byteOffset", 0))
        raw = bytes(parsed["bin"][start:start + int(view["byteLength"])])
        pil = Image.open(io.BytesIO(raw))
        mode = "RGBA" if pil.mode in ("RGBA", "LA", "P") else "RGB"
        tex = np.asarray(pil.convert(mode), np.float64)
        h, w = tex.shape[:2]
        weight = np.zeros((h, w))
        hit = np.zeros((h, w), bool)
        for Pp, f, uv in parts:
            r, c, X = _texels(Pp, f, np.asarray(uv, np.float64), (h, w))
            if not len(r):
                continue
            hit[r, c] = True
            ix = np.floor((X[:, 0] - x0) / TINT_CELL_M).astype(int)
            iy = np.floor((X[:, 1] - y0) / TINT_CELL_M).astype(int)
            ok = (ix >= 0) & (ix < shape[1]) & (iy >= 0) & (iy < shape[0]) & (X[:, 1] >= floor_y)
            wv = np.zeros(len(r))
            sk = skin[iy[ok], ix[ok]]
            visible = np.isfinite(sk) & (X[ok, 2] >= sk - TINT_VISIBLE_M)
            wv[ok] = np.where(visible, np.clip(1.0 - dist[iy[ok], ix[ok]] / TINT_FADE_M, 0.0, 1.0), 0.0)
            weight[r, c] = np.maximum(weight[r, c], wv)
        pad = maximum_filter(weight, size=2 * TINT_PAD_PX + 1)
        weight = np.where(hit, weight, pad)
        tinted = weight > 0
        if not tinted.any():
            report["images"][index] = {"tinted_texels": 0}
            continue
        tex[..., :3] = tex[..., :3] * (1.0 - weight[..., None]) + colour[None, None, :] * weight[..., None]
        out = io.BytesIO()
        Image.fromarray(np.clip(np.rint(tex), 0, 255).astype(np.uint8), mode).save(out, format="PNG")
        replaced[index] = out.getvalue()
        report["images"][index] = {"tinted_texels": int(tinted.sum()), "full_texels": int((weight >= 1.0).sum()),
                                   "size": [w, h]}
    if not replaced:
        return glb, report
    return _repack(parsed, replaced), report
