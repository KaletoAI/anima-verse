"""Two CPU passes over a baked face (``face_retexture.bake_face_texture``) before it is rigged — no hub, no Blender.

1. DARK-TEXEL FILL. A face projection writes only the texels its patch covers. A texel it never wrote keeps the
   mesher's own albedo — on a mesh whose lash flaps the face cleanup did not press back, that is black lash paint
   on flaps that sit inside the face but outside the projection's UV mask; the "black eye" the gate
   (``face_retexture.dark_face_gate``) measures. The fill region is 3D: every head texel within ``FILL_REACH_MM``
   of a projected face texel (texels rasterised through the triangles' UVs to their surface points). A candidate
   in that region
   - is dark: Rec. 709 luma below ``FILL_DARK_SHARE`` of the face's median luma, and
   - was NOT written by the projection: every channel within ``FILL_UNCHANGED`` of the hub's input atlas.
   Whatever the photo put on the face (pupils, lashes, brows — texels the projection wrote) is never a candidate,
   so the photo's own dark features stay. Each candidate takes the inverse-distance-weighted colour of the
   ``FILL_NEIGHBOURS`` nearest non-dark region texels in 3D within ``FILL_RADIUS_MM`` — in 3D, not across the
   atlas: a UniForge atlas is hundreds of small islands, and the texel next door in UV is often another part of the
   body. Changed texels carry into the atlas padding next to them (``_spread_to_padding``), else bilinear sampling
   draws the old colour along every island border. Runs only when the dark gate failed, so a face that passed
   keeps its bytes.

2. SEAM CHECK. Measured on the surface, texel by texel: front-of-head texels just outside the projection's mask and
   just inside it, each outer texel paired with its nearest inner one, in two bands — ``edge`` (``SEAM_EDGE_MM``,
   the step the eye sees) and ``wide`` (``SEAM_WIDE_MM``, the band of the 2026-11-10 measurement). The record keeps
   the median CIE76 difference and the median lightness step (inside minus outside) of each; the model overview
   shows them. There is NO automatic lightness correction: on Lirien (the only model above the others in the wide
   band — wide dE 8.8 vs Kira 7.8 / Kai 7.0) the step AT the edge is +0.7 L* (edge dE 4.5; Kira 8.8, Kai 5.1);
   the wide-band difference comes from gradients and interior geometry (eye sockets, lash flaps) a few mm away,
   and a shift fitted to it drew a visible jagged line on the forehead and greyed the face (renders 2026-11-11).

Calibration of the fill (read-only copies of the three base bodies, 2026-11-11): on Lirien's baked face the fill
region's near-black share went 4.18 % -> 0.24 % (2880 texels filled, the eye band alone 12.5 % -> 3.9 %); Kira and
Kai pass the gate, the fill does not run on them. Wired in by ``model3d._face_polish_stage`` after the black-eye
check of every face retexture (generation with "Improve face before rigging", the dialog, "Re-apply face cleanup").
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

VERSION = 1

FILL_DARK_SHARE = 0.5          # a candidate is darker than this share of the median face-skin luma ...
FILL_UNCHANGED = 12            # ... and within this many 8-bit levels of the hub's input atlas (never written)
FILL_NEIGHBOURS = 12
FILL_RADIUS_MM = 25.0
FILL_REACH_MM = 8.0            # the fill region: head texels within this distance of a projected face texel

SEAM_EDGE_MM = (1.0, 4.0)      # the seam bands either side of the projection's edge
SEAM_WIDE_MM = (2.0, 10.0)
REFERENCE_HEIGHT_MM = 1700.0

_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 8-bit (…, 3) -> CIE L*a*b* (D65)."""
    c = np.asarray(rgb, np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def texel_positions(P: np.ndarray, F: np.ndarray, U: np.ndarray, width: int, height: int,
                    faces: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """``(texels (n, 2) int row/col, positions (n, 3))``: the texel centres covered by ``faces`` in UV with the
    3D surface point each one shows (barycentric). A texel covered twice keeps the last triangle."""
    rows, cols, points = [], [], []
    uv = U * np.array([width, height])
    for tri in faces:
        a, b, c = uv[tri]
        x0, x1 = int(np.floor(min(a[0], b[0], c[0]))), int(np.ceil(max(a[0], b[0], c[0])))
        y0, y1 = int(np.floor(min(a[1], b[1], c[1]))), int(np.ceil(max(a[1], b[1], c[1])))
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, width - 1), min(y1, height - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        if not inside.any():
            continue
        w = np.stack([l1[inside], l2[inside], l3[inside]], 1)
        points.append(w @ P[tri])
        rows.append((ys[inside] - 0.5).astype(int))
        cols.append((xs[inside] - 0.5).astype(int))
    if not points:
        return np.zeros((0, 2), int), np.zeros((0, 3))
    return np.stack([np.concatenate(rows), np.concatenate(cols)], 1), np.concatenate(points)


def _head_frame(P: np.ndarray) -> Tuple[float, np.ndarray]:
    low, high = P.min(0), P.max(0)
    mm = (high[1] - low[1]) / REFERENCE_HEIGHT_MM
    head = P[:, 1] > high[1] - 0.15 * (high[1] - low[1])
    return mm, head


def _seam_pairs(texels: np.ndarray, points: np.ndarray, texture: np.ndarray, mask: np.ndarray, mm: float,
                centre: np.ndarray, band: Tuple[float, float]):
    """Texel pairs across the face edge on the front of the head: ``(outer Lab, inner Lab)`` — each outer texel
    ``band`` mm outside the edge with its nearest inner texel the same band inside — or None.
    ``texels``/``points``: the head's rasterised texels and their surface points."""
    from scipy.spatial import cKDTree
    t_in = mask[texels[:, 0], texels[:, 1]]
    if not t_in.any() or t_in.all():
        return None
    front = 1.0 if (points[t_in, 2] - centre[2]).mean() > 0 else -1.0
    near = front * (points[:, 2] - centre[2]) > 0
    inner, outer = np.nonzero(t_in & near)[0], np.nonzero(~t_in & near)[0]
    if len(inner) == 0 or len(outer) == 0:
        return None
    d_out = cKDTree(points[inner]).query(points[outer])[0] / mm
    d_in = cKDTree(points[outer]).query(points[inner])[0] / mm
    band_out = outer[(d_out > band[0]) & (d_out < band[1])]
    band_in = inner[(d_in > band[0]) & (d_in < band[1])]
    if len(band_out) < 10 or len(band_in) < 10:
        return None
    pair = band_in[cKDTree(points[band_in]).query(points[band_out])[1]]
    lab_out = _lab(texture[texels[band_out, 0], texels[band_out, 1], :3])
    lab_in = _lab(texture[texels[pair, 0], texels[pair, 1], :3])
    return lab_out, lab_in


def seam(texels: np.ndarray, points: np.ndarray, texture: np.ndarray, mask: np.ndarray, mm: float,
         centre: np.ndarray) -> Optional[Dict[str, Any]]:
    """The seam measurement (module doc, 2.): ``{edge: {...}, wide: {...}}``, a band None without texels on both
    sides; None when neither band has any."""
    result: Dict[str, Any] = {}
    for name, band in (("edge", SEAM_EDGE_MM), ("wide", SEAM_WIDE_MM)):
        pairs = _seam_pairs(texels, points, texture, mask, mm, centre, band)
        if pairs is None:
            result[name] = None
            continue
        lab_out, lab_in = pairs
        delta = np.linalg.norm(lab_out - lab_in, axis=1)
        result[name] = {"band_mm": list(band), "de76_median": round(float(np.median(delta)), 2),
                        "de76_p90": round(float(np.percentile(delta, 90)), 2),
                        "dl_median": round(float(np.median(lab_in[:, 0] - lab_out[:, 0])), 2),
                        "pairs": int(len(delta))}
    return result if any(result.values()) else None


PADDING_PX = 8                 # atlas padding within this many texels of a changed texel follows it


def _covered(F: np.ndarray, U: np.ndarray, width: int, height: int) -> np.ndarray:
    from app.core.face_cleanup import _triangle_mask
    return _triangle_mask(U, F, width, height)


def _spread_to_padding(texture: np.ndarray, out: np.ndarray, covered: np.ndarray) -> None:
    """Carry every changed texel into the atlas padding next to it (in place).

    Only texels a triangle covers have a surface point; the padding around each UV island is still sampled by
    bilinear filtering and mip levels at the island's edge. Left alone it draws the old colour as lines along
    every island border (seen on the first renders). Each padding texel (covered by no triangle of the body)
    within ``PADDING_PX`` of a covered texel takes that nearest covered texel's colour when it changed."""
    from scipy import ndimage
    if not covered.any():
        return
    dist, (iy, ix) = ndimage.distance_transform_edt(~covered, return_indices=True)
    ys, xs = np.nonzero(~covered & (dist <= PADDING_PX))
    sy, sx = iy[ys, xs], ix[ys, xs]
    moved = np.any(out[sy, sx, :3] != texture[sy, sx, :3], axis=1)
    out[ys[moved], xs[moved], :3] = out[sy[moved], sx[moved], :3]


def pack_mask(mask: np.ndarray) -> str:
    """A bool atlas mask in the bake's ``face_mask`` encoding (``face_retexture.face_mask_array`` reads it)."""
    import base64
    import zlib
    return base64.b64encode(zlib.compress(np.packbits(mask).tobytes())).decode("ascii")


def polish(glb: bytes, original_glb: bytes, bake_meta: Dict[str, Any], *,
           fill: bool) -> Tuple[bytes, Dict[str, Any], Optional[np.ndarray]]:
    """Both passes on one baked source. ``fill``: run the dark-texel fill (the gate failed). Returns
    ``(bytes, record, changed)`` — the input bytes themselves and ``changed`` None when nothing changed, else the
    (height, width) mask of the texels written (padding included). ``record``:
    ``{version, dark_fill: {...}|absent, seam: {edge, wide}|None}`` (``seam`` measured after the fill). Raises ValueError for a mesh it cannot read."""
    from scipy.spatial import cKDTree
    from app.core import face_cleanup as fc
    from app.core.face_retexture import face_mask_array, _near_black
    from app.core.glb_mesh import _parse, pack_glb
    parsed = _parse(glb, "Source")
    primitives, P, F, U, _N, _offsets = fc._body(parsed)
    image_index, texture, mime = fc._texture(parsed, primitives[0])
    height, width = texture.shape[:2]
    mask = face_mask_array(bake_meta, width, height)
    record: Dict[str, Any] = {"version": VERSION}
    if mask is None or not mask.any():
        record["skipped"] = "no face mask"
        return glb, record, None
    mm, head = _head_frame(P)
    rgb = texture[..., :3]
    out = texture.copy()
    luma = rgb.astype(np.float64) @ _LUMA
    skin_luma = float(np.median(luma[mask]))
    texels, points = texel_positions(P, F, U, width, height, F[head[F].any(1)])
    covered = _covered(F, U, width, height)

    if fill:
        source_parsed = _parse(original_glb, "Source")
        original = fc._texture(source_parsed, fc._body(source_parsed)[0][0])[1][..., :3]
        if original.shape != rgb.shape:
            from PIL import Image
            original = np.asarray(Image.fromarray(original).resize((width, height), Image.Resampling.LANCZOS))
        t_mask = mask[texels[:, 0], texels[:, 1]]
        # The face region in 3D: the projected texels and everything within FILL_REACH_MM of them on the head
        # (lash flaps the projection's own face patch left out sit inside the face, outside its UV mask).
        reach = cKDTree(points[t_mask]).query(points, distance_upper_bound=FILL_REACH_MM * mm)[0]
        t_region = np.isfinite(reach)
        rows, cols = texels[:, 0], texels[:, 1]
        t_dark = luma[rows, cols] < FILL_DARK_SHARE * skin_luma
        t_unchanged = np.abs(rgb[rows, cols].astype(int) - original[rows, cols].astype(int)).max(1) <= FILL_UNCHANGED
        t_cand = t_region & t_dark & t_unchanged
        t_source = t_region & ~t_dark
        band = np.zeros(mask.shape, bool)
        band[rows[t_region], cols[t_region]] = True
        dark_before = float(_near_black(rgb)[band].mean())
        filled = 0
        if t_cand.any() and t_source.sum() >= FILL_NEIGHBOURS:
            src = texels[t_source]
            dist, idx = cKDTree(points[t_source]).query(points[t_cand], k=FILL_NEIGHBOURS,
                                                         distance_upper_bound=FILL_RADIUS_MM * mm)
            valid = np.isfinite(dist)
            weight = np.where(valid, 1.0 / np.maximum(np.where(valid, dist, 1.0), 0.05 * mm), 0.0)
            ok = weight.sum(1) > 0
            colours = rgb[src[np.where(valid, idx, 0), 0], src[np.where(valid, idx, 0), 1]].astype(np.float64)
            fill_rgb = (colours * weight[..., None]).sum(1) / np.maximum(weight.sum(1), 1e-12)[:, None]
            target = texels[t_cand][ok]
            out[target[:, 0], target[:, 1], :3] = np.clip(np.round(fill_rgb[ok]), 0, 255).astype(np.uint8)
            filled = int(len(np.unique(target[:, 0] * width + target[:, 1])))
        record["dark_fill"] = {
            "region_texels": int(band.sum()), "candidates": int(len(np.unique(
                texels[t_cand][:, 0] * width + texels[t_cand][:, 1]))), "filled": filled,
            "dark_share_before": round(dark_before, 6),
            "dark_share_after": round(float(_near_black(out[..., :3])[band].mean()), 6),
            "skin_luma": round(skin_luma, 1)}

    record["seam"] = seam(texels, points, out, mask, mm, P[head].mean(0))
    _spread_to_padding(texture, out, covered)
    changed = np.any(out != texture, axis=2)
    if not changed.any():
        return glb, record, None
    binary = fc._replace_image(parsed, bytearray(parsed["bin"]), image_index, fc._encode(out, mime))
    return pack_glb(parsed["gltf"], bytes(binary)), record, changed
