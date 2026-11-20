"""Texture from cut: a garment template's pattern islands, filled from the item image by a routed img2img backend.

Plan: ``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md`` (Tasks 5–10).

This part is the RENDER of a piece's islands, pure numpy + PIL on the drape's ``islands.json`` payload (written by
``app/blender/scripts/uv_pattern.islands_payload``; this module never imports the Blender scripts):

- ``rasterise_islands`` / ``island_mask`` — the island label raster and mask the gate measures against;
- ``render_template`` — the CLEAN model template (neutral grey islands, a thin outline drawn inside the mask, a white
  background, square, no text) that goes to the model as the first image;
- ``render_pattern_sheet`` — the user's DEBUG view of the same islands (pastel fills, part names, sizes in cm, grain
  arrows, seam letters, the sleeve cap height, a px/cm footer). It is never sent to a model.

Pixel frame: the payload stores image-frame pixels (x right, y down, row = (1 - v) * atlas_px), so nothing here
re-derives the Blender UV flip.
"""
from __future__ import annotations

import colorsys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TEMPLATE_FILL = (190, 190, 190)
TEMPLATE_LINE = (80, 80, 80)
LINE_PX = 2
BACKGROUND = (255, 255, 255)

SHEET_LINE = (60, 60, 60)
SHEET_TEXT = (30, 30, 30)
SHEET_SEAM = (170, 30, 30)
SHEET_PASTELS = (
    (174, 214, 241), (249, 231, 159), (171, 235, 198), (245, 183, 177), (215, 189, 226),
    (250, 215, 160), (162, 217, 206), (237, 187, 153), (210, 180, 222), (200, 230, 160),
)
PART_LABELS = {
    "front": "Front", "back": "Back", "sleeve_l": "Sleeve left", "sleeve_r": "Sleeve right", "band": "Neckband",
    "collar": "Collar", "placket": "Placket", "cuff_l": "Cuff left", "cuff_r": "Cuff right",
}


# ---------------------------------------------------------------------------------------------------- raster


def island_ids(islands: dict) -> dict[str, int]:
    """Label id per island name: 1 + the index of the name in sorted order (0 = background)."""
    names = sorted(str(i["name"]) for i in islands.get("islands", []))
    if len(names) > 255:
        raise ValueError("garment_cut_texture: more than 255 islands do not fit a uint8 label raster")
    return {n: k + 1 for k, n in enumerate(names)}


def _fill_triangle(out: np.ndarray, tri: np.ndarray, value: int) -> None:
    """Set ``out`` to ``value`` at every pixel whose CENTRE (j + 0.5, i + 0.5) lies inside ``tri`` (3 x 2, x/y image
    pixels). Edges are half-open (top-left rule), so two triangles sharing an edge never both claim a centre on it
    and a shape whose corners sit on pixel centres keeps its left/top centres and drops its right/bottom ones."""
    h, w = out.shape
    a, b, c = (np.asarray(p, float) for p in tri)
    area2 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if area2 == 0:
        return
    if area2 < 0:
        b, c = c, b
    lo = np.floor(np.minimum(np.minimum(a, b), c) - 0.5).astype(int)
    hi = np.ceil(np.maximum(np.maximum(a, b), c) - 0.5).astype(int)
    j0, i0 = max(lo[0], 0), max(lo[1], 0)
    j1, i1 = min(hi[0], w - 1), min(hi[1], h - 1)
    if j1 < j0 or i1 < i0:
        return
    px = np.arange(j0, j1 + 1, dtype=float)[None, :] + 0.5
    py = np.arange(i0, i1 + 1, dtype=float)[:, None] + 0.5
    inside = np.ones((i1 - i0 + 1, j1 - j0 + 1), bool)
    for p, q in ((a, b), (b, c), (c, a)):
        dx, dy = q[0] - p[0], q[1] - p[1]
        e = dx * (py - p[1]) - dy * (px - p[0])
        top_left = (dy == 0 and dx > 0) or dy < 0
        inside &= (e >= 0) if top_left else (e > 0)
    out[i0:i1 + 1, j0:j1 + 1][inside] = value


def rasterise_islands(islands: dict, size: int) -> np.ndarray:
    """uint8 label raster (``size`` x ``size``) of the payload's islands from ``verts_px`` / ``tris``; 0 = background,
    id = ``island_ids``. The payload's pixels are scaled when ``size`` differs from its ``atlas_px``."""
    size = int(size)
    out = np.zeros((size, size), np.uint8)
    ids = island_ids(islands)
    scale = size / float(islands.get("atlas_px") or size)
    for isl in islands.get("islands", []):
        verts = np.asarray(isl.get("verts_px") or [], float).reshape(-1, 2) * scale
        for t in isl.get("tris") or []:
            _fill_triangle(out, verts[list(t)], ids[str(isl["name"])])
    return out


def island_mask(islands: dict, size: int) -> np.ndarray:
    """Boolean mask of every island (labels > 0)."""
    return rasterise_islands(islands, size) > 0


def _interior(labels: np.ndarray, r: int) -> np.ndarray:
    """Pixels whose whole (2r + 1)^2 neighbourhood carries their own non-zero label (outside the canvas = 0): the
    per-island erosion. ``labels > 0`` minus this is an outline ``r`` px wide drawn INSIDE each island."""
    h, w = labels.shape
    pad = np.zeros((h + 2 * r, w + 2 * r), labels.dtype)
    pad[r:r + h, r:r + w] = labels
    keep = labels > 0
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            keep &= pad[r + di:r + di + h, r + dj:r + dj + w] == labels
    return keep


def render_template(islands: dict, size: int | None = None) -> Image.Image:
    """The clean model template: square RGB of ``size`` (default the payload's ``atlas_px``), white background,
    ``TEMPLATE_FILL`` on the islands and a ``LINE_PX`` outline in ``TEMPLATE_LINE`` drawn INSIDE each island — so
    the non-white footprint IS the island mask the gate measures against. No text, no arrows."""
    size = int(size or islands.get("atlas_px") or 2048)
    labels = rasterise_islands(islands, size)
    inner = _interior(labels, LINE_PX)
    img = np.empty((size, size, 3), np.uint8)
    img[:] = BACKGROUND
    img[labels > 0] = TEMPLATE_LINE
    img[inner] = TEMPLATE_FILL
    return Image.fromarray(img, "RGB")


# ---------------------------------------------------------------------------------------------------- debug sheet


def part_label(name: str) -> str:
    """English display name of an island: ``front_2`` -> "Front 2", unknown names title-cased."""
    base, _, n = str(name).rpartition("_")
    if base and n.isdigit():
        return f"{part_label(base)} {n}"
    return PART_LABELS.get(str(name), str(name).replace("_", " ").capitalize())


def sheet_fill(index: int) -> tuple[int, int, int]:
    """Pastel fill of the ``index``-th island (sorted names): the fixed palette, then golden-angle hues."""
    if index < len(SHEET_PASTELS):
        return SHEET_PASTELS[index]
    h = (index * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.28, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)


def pattern_sheet_labels(islands: dict) -> dict[str, list[str]]:
    """Label lines per island: the part name, the bbox size in cm (bbox px / px_per_cm), and the sleeve cap height
    when the payload has one."""
    s = float(islands.get("px_per_cm") or 0) or 1.0
    out = {}
    for isl in islands.get("islands", []):
        x0, y0, x1, y1 = (float(v) for v in isl.get("bbox_px") or _bbox(isl))
        lines = [part_label(isl["name"]), f"{(x1 - x0) / s:.1f} × {(y1 - y0) / s:.1f} cm"]
        if isl.get("cap_height_cm") is not None:
            lines.append(f"cap {float(isl['cap_height_cm']):.1f} cm")
        out[str(isl["name"])] = lines
    return out


def pattern_sheet_footer(islands: dict) -> str:
    return f"{float(islands.get('px_per_cm') or 0):.2f} px/cm · atlas {int(islands.get('atlas_px') or 0)}²"


def _bbox(isl: dict) -> list[float]:
    v = np.asarray(isl.get("verts_px") or [[0, 0]], float).reshape(-1, 2)
    return [*v.min(axis=0), *v.max(axis=0)]


def _letter(k: int) -> str:
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def seam_marks(islands: dict) -> list[dict]:
    """One letter per seam (A, B, ... in seam index order), placed at the seam's middle sample on BOTH sides:
    [{"letter", "seam", "island", "xy"}] in image-frame pixels of the payload."""
    by_seam = {}
    for p in islands.get("seams") or []:
        by_seam.setdefault(int(p["seam"]), []).append(p)
    marks = []
    for k, sid in enumerate(sorted(by_seam)):
        pairs = by_seam[sid]
        mid = pairs[len(pairs) // 2]
        for side in ("a", "b"):
            marks.append({"letter": _letter(k), "seam": sid, "island": str(mid[side]),
                          "xy": [float(v) for v in mid[f"uv_{side}_px"]]})
    return marks


def _font(px: int):
    px = max(8, int(px))
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def render_pattern_sheet(islands: dict, size: int | None = None) -> Image.Image:
    """The DEBUG pattern sheet of a piece: each island in its own pastel fill (``sheet_fill`` by sorted name) with a
    2 px dark outline, its English name, its size in cm and the sleeve cap height (``pattern_sheet_labels``), a grain
    arrow pointing up (the islands are oriented so ``up`` is image up), the seam letters (``seam_marks``) and a footer
    strip below the square atlas (``pattern_sheet_footer``). RGB, ``size`` wide (default ``atlas_px``)."""
    size = int(size or islands.get("atlas_px") or 2048)
    scale = size / float(islands.get("atlas_px") or size)
    labels = rasterise_islands(islands, size)
    inner = _interior(labels, LINE_PX)
    ids = island_ids(islands)
    footer_h = max(24, size // 32)
    img = np.empty((size + footer_h, size, 3), np.uint8)
    img[:] = BACKGROUND
    for name, iid in ids.items():
        img[:size][labels == iid] = sheet_fill(iid - 1)
    edge = (labels > 0) & ~inner
    img[:size][edge] = SHEET_LINE
    img[size:size + 1] = SHEET_LINE
    out = Image.fromarray(img, "RGB")
    draw = ImageDraw.Draw(out)

    base_font = max(12, size // 64)
    texts = pattern_sheet_labels(islands)
    for isl in islands.get("islands", []):
        x0, y0, x1, y1 = (float(v) * scale for v in (isl.get("bbox_px") or _bbox(isl)))
        w, h = x1 - x0, y1 - y0
        lines = texts[str(isl["name"])]
        fpx = int(min(base_font, max(8, h / (len(lines) + 1.5))))
        font = _font(fpx)
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        line_h = fpx * 1.2
        top = cy - 0.5 * line_h * len(lines)
        for k, line in enumerate(lines):
            draw.text((cx, top + k * line_h + 0.5 * line_h), line, fill=SHEET_TEXT, font=font, anchor="mm")
        # grain arrow: vertical, pointing to image up, left of the text block
        alen = min(0.6 * h, 0.12 * size)
        ax = x0 + max(0.12 * w, 3 * LINE_PX + 4)
        if alen >= 12 and w >= 24:
            ay0, ay1 = cy + 0.5 * alen, cy - 0.5 * alen
            lw = max(2, size // 680)
            head = max(6.0, alen * 0.18)
            draw.line([(ax, ay0), (ax, ay1 + head * 0.5)], fill=SHEET_TEXT, width=lw)
            draw.polygon([(ax, ay1), (ax - head * 0.5, ay1 + head), (ax + head * 0.5, ay1 + head)], fill=SHEET_TEXT)

    sfont = _font(max(10, size // 85))
    for m in seam_marks(islands):
        x, y = (v * scale for v in m["xy"])
        draw.text((x, y), m["letter"], fill=SHEET_SEAM, font=sfont, anchor="mm", stroke_width=2,
                  stroke_fill=BACKGROUND)

    draw.text((size / 2, size + footer_h / 2), pattern_sheet_footer(islands), fill=SHEET_TEXT,
              font=_font(int(footer_h * 0.6)), anchor="mm")
    return out
