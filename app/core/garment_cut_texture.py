"""Texture from cut: a garment template's pattern islands, filled from the item image by a routed img2img backend.

Plan: ``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md`` (Tasks 5–10).

This part is the RENDER of a piece's islands, pure numpy + PIL on the CUT's ``islands.json`` payload (written by
``app/blender/scripts/uv_pattern.islands_payload`` in the cut-only run of ``garment_template_cut`` — seconds on the CPU,
no drape needed; a drape of the same cut writes the same bytes; this module never imports the Blender scripts):

- ``rasterise_islands`` / ``island_mask`` — the island label raster and mask the gate measures against;
- ``render_template`` — the CLEAN model template (islands pre-filled with the item's base fabric colour — neutral grey
  without one —, a thin outline drawn inside the mask, a white background, square, no text) that goes to the model as
  the first image;
- ``render_pattern_sheet`` — the user's DEBUG view of the same islands (pastel fills, part names, sizes in cm, grain
  arrows, seam letters, the sleeve cap height, a px/cm footer). It is never sent to a model.

The PROMPT (Task 6) is the shipped Jinja2 file ``shared/templates/image/garment_cut_texture.md`` — its own tiny
``SandboxedEnvironment`` + ``StrictUndefined`` loader here, deliberately not world-overridable (``/admin/templates``
stays LLM-only); ``layout_words`` names each island by its place in the template. ``PROMPT_SHA`` (md5 of the file
text) enters the cut atlas key and the record (``prompt_sha``), so a reworded prompt makes an old atlas stale. The render runs on the occasion
``CUT_OCCASION`` with the use case ``CUT_USE_CASE`` (empty style/negative/instruction: the prompt is the whole subject).

The JOB (Task 8): ``start`` checks synchronously (media switch, a configured chain, a ready CUT with islands
(``garment_template_cut.state``), an item picture) and runs ``generate`` in a thread — ONE attempt per click, no
retry; it never waits for a drape and may run while the Build drapes the piece. The character's Build runs the same
flow as its step "cut_texture" for a top whose ``texture`` is "cut" (``build_state`` / ``build_start`` /
``build_join``, user test 2026-11-21) — no click on the dialog's button is needed. A cut
atlas is keyed by ``csig`` (the cut's islands sha, the item picture sha, ``PROMPT_SHA``,
``cut_texture_post.POST_VERSION``), never by ``tsig``; its record lives under ``cut_dir`` (``templates/cut/``) with
the state "ready" / "rejected" / "failed". The assembly maps it onto a drape whose islands have the same sha — every
drape of the same cut (``garment_template.cut_info``). Every render goes ``routing.run_routed`` -> ``run_on_backend`` ->
``run_on_backend_channel``; the reference wording is the central handoff's job.

Pixel frame: the payload stores image-frame pixels (x right, y down, row = (1 - v) * atlas_px), so nothing here
re-derives the Blender UV flip.
"""
from __future__ import annotations

import colorsys
import glob
import hashlib
import io
import json
import re
import threading
from pathlib import Path

import numpy as np
from jinja2 import StrictUndefined, Template
from jinja2.sandbox import SandboxedEnvironment
from PIL import Image, ImageDraw, ImageFont

from app.core import cut_texture_post
from app.core.log import get_logger

logger = get_logger("garment_cut_texture")

#: The image occasion and the style use case of a cut-texture render (``app/imagegen/occasions.py``,
#: ``config._DEFAULT_IMAGE_USE_CASES``).
CUT_OCCASION = "garment_cut_texture"
CUT_USE_CASE = "garment_cut_texture"

PROMPT_FILE = Path(__file__).resolve().parents[2] / "shared" / "templates" / "image" / "garment_cut_texture.md"
#: The back job's prompt (the back panel alone, filled from the piece's back view).
PROMPT_FILE_BACK = PROMPT_FILE.with_name("garment_cut_texture_back.md")
PROMPT_TEXTS = {"front": PROMPT_FILE.read_text(encoding="utf-8"),
                "back": PROMPT_FILE_BACK.read_text(encoding="utf-8")}
PROMPT_TEXT = PROMPT_TEXTS["front"]
#: md5 of both shipped prompt file texts — part of the cut atlas key, so a reworded prompt makes an atlas stale.
PROMPT_SHA = hashlib.md5((PROMPT_TEXTS["front"] + "\0" + PROMPT_TEXTS["back"]).encode("utf-8")).hexdigest()

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
    # step 3a: the close-fitting kinds' pieces (``uv_pattern.PARTS`` 10..36)
    "front_l": "Front left", "front_r": "Front right", "back_l": "Back left", "back_r": "Back right",
    "waistband": "Waistband", "gusset": "Gusset", "leg_l": "Leg left", "leg_r": "Leg right",
    "cup_l": "Cup left", "cup_r": "Cup right", "cup_top_l": "Upper cup left", "cup_top_r": "Upper cup right",
    "gore": "Gore", "band_l": "Band left", "band_r": "Band right", "strap_l": "Strap left", "strap_r": "Strap right",
    "glove_back_l": "Back of hand left", "glove_back_r": "Back of hand right", "palm_l": "Palm left",
    "palm_r": "Palm right", "thumb_l": "Thumb left", "thumb_r": "Thumb right", "hip_band_l": "Hip band left",
    "hip_band_r": "Hip band right", "top_band_l": "Top band left", "top_band_r": "Top band right",
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


#: ``outline_for``: the outline drawn inside a pre-filled island is the fill times ``OUTLINE_DARK`` (in sRGB, always in
#: gamut); a fill darker than L* ``OUTLINE_LIGHT_BELOW`` gets ``OUTLINE_LIGHT`` of the way to white instead.
OUTLINE_DARK = 0.6
OUTLINE_LIGHT = 0.4
OUTLINE_LIGHT_BELOW = 30.0


def outline_for(fill) -> tuple[int, int, int]:
    """The outline colour drawn inside islands pre-filled with ``fill``: a darker shade of it (``OUTLINE_DARK``), a
    lighter one for a dark fabric — the outline shows on any fabric without being a colour of its own."""
    rgb = np.asarray(fill, np.float64)
    if float(cut_texture_post.srgb_to_lab(rgb)[0]) < OUTLINE_LIGHT_BELOW:
        out = rgb + (255.0 - rgb) * OUTLINE_LIGHT
    else:
        out = rgb * OUTLINE_DARK
    return tuple(int(v) for v in np.clip(np.rint(out), 0, 255))


def render_template(islands: dict, size: int | None = None, fill=None) -> Image.Image:
    """The clean model template: square RGB of ``size`` (default the payload's ``atlas_px``), white background, the
    islands in ``fill`` (the item's base fabric colour, ``cut_texture_post.fabric_colour``; default the neutral
    ``TEMPLATE_FILL``) and a ``LINE_PX`` outline (``TEMPLATE_LINE``, with a fill ``outline_for``) drawn INSIDE each
    island — so the non-white footprint IS the island mask the gate measures against. No text, no arrows."""
    size = int(size or islands.get("atlas_px") or 2048)
    labels = rasterise_islands(islands, size)
    inner = _interior(labels, LINE_PX)
    img = np.empty((size, size, 3), np.uint8)
    img[:] = BACKGROUND
    img[labels > 0] = TEMPLATE_LINE if fill is None else outline_for(fill)
    img[inner] = TEMPLATE_FILL if fill is None else tuple(int(v) for v in fill)
    return Image.fromarray(img, "RGB")


# ---------------------------------------------------------------------------------------------------- prompt

#: English panel name per part, in pattern order (the order the prompt lists the pieces in).
PROMPT_PIECE_NAMES = {
    "front": "front panel", "back": "back panel", "sleeve_l": "left sleeve", "sleeve_r": "right sleeve",
    "band": "neckband", "collar": "collar", "placket": "placket",
    # step 3a: the close-fitting kinds' pieces (left / right are the wearer's)
    "front_r": "right front leg panel", "front_l": "left front leg panel", "back_l": "left back leg panel",
    "back_r": "right back leg panel", "leg_r": "right leg", "leg_l": "left leg", "cup_r": "right cup",
    "cup_l": "left cup", "cup_top_r": "right upper cup", "cup_top_l": "left upper cup", "gore": "centre gore",
    "glove_back_r": "back of the right hand", "glove_back_l": "back of the left hand", "palm_l": "left palm",
    "palm_r": "right palm", "thumb_r": "right thumb", "thumb_l": "left thumb", "gusset": "crotch gusset",
    "waistband": "waistband", "band_r": "right band", "band_l": "left band", "strap_r": "right strap",
    "strap_l": "left strap", "hip_band_r": "right hip band", "hip_band_l": "left hip band",
    "top_band_r": "right top band", "top_band_l": "left top band", "cuff_r": "right cuff", "cuff_l": "left cuff",
}

_PROMPT_ENV = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined, trim_blocks=True,
                                   lstrip_blocks=True, keep_trailing_newline=False)


def prompt_template(side: str = "front") -> Template:
    """The shipped prompt file of the ``side`` job ("front" / "back") as a StrictUndefined template (a missing
    variable raises)."""
    return _PROMPT_ENV.from_string(PROMPT_TEXTS[side])


def render_prompt(*, piece: str, pieces: list[str], side: str = "front", layout: list[str] | None = None) -> str:
    """The cut-texture prompt of the ``side`` job for ``piece`` (e.g. "T-shirt") with the pattern ``pieces`` of that
    job (English panel names) and the ``layout`` sentences (``layout_words``: which island is which, in words of the
    template). The sleeves the prompt speaks of are the pieces with "sleeve" in their name. Ordinal wording ("the
    first image") — the central handoff rewrites it per backend."""
    pieces = list(pieces)
    return prompt_template(side).render(piece=piece, pieces=pieces, layout=list(layout or []),
                                        sleeves=[p for p in pieces if "sleeve" in p]).strip()


#: ``layout_words``: an island centre left of this share of the template is "left", right of 1 - it "right"; the
#: same for top / bottom; below ``LAYOUT_VERY`` it is "at the very bottom" (the neckband strip under the sleeves).
LAYOUT_SIDE = 0.36
LAYOUT_VERY = 0.9
#: An island whose bounding box is this many times wider than high (or higher than wide) is "the long thin strip".
LAYOUT_STRIP = 6.0


def _place_words(cx: float, cy: float) -> str:
    v = "top" if cy < LAYOUT_SIDE else "bottom" if cy > 1 - LAYOUT_SIDE else "middle"
    h = "left" if cx < LAYOUT_SIDE else "right" if cx > 1 - LAYOUT_SIDE else ""
    if v == "bottom" and cy > LAYOUT_VERY and not h:
        return "at the very bottom"
    if v == "middle":
        return f"in the middle {h}".strip() if h else "in the middle"
    return f"at the {v} {h}".strip()


def layout_words(islands: dict) -> list[str]:
    """One sentence per island of the job's payload, in pattern order, saying which island of the template is which
    piece — e.g. "the large piece at the top left is the front panel", "the piece at the bottom left is the left
    sleeve", "the long thin strip at the very bottom is the neckband" (user test 2026-11-21: the model did not take
    the wide fan-shaped sleeve islands for sleeves). Positions are the island's bbox centre in the square template
    (``LAYOUT_SIDE`` / ``LAYOUT_VERY``); "large" marks the island with the largest bbox area when the job has more
    than one; a bbox ``LAYOUT_STRIP`` times longer than wide is "the long thin strip"."""
    size = float(islands.get("atlas_px") or 2048)
    names = {n: w for n, w in zip(_pattern_order(islands), prompt_pieces(islands))}
    boxes = {}
    for isl in islands.get("islands", []):
        x0, y0, x1, y1 = (float(v) for v in (isl.get("bbox_px") or _bbox(isl)))
        boxes[str(isl["name"])] = (x0, y0, x1, y1)
    if not boxes:
        return []
    largest = max(boxes, key=lambda n: (boxes[n][2] - boxes[n][0]) * (boxes[n][3] - boxes[n][1]))
    out = []
    for name in _pattern_order(islands):
        x0, y0, x1, y1 = boxes[name]
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        if max(w / h, h / w) >= LAYOUT_STRIP:
            shape = "the long thin strip"
        elif name == largest and len(boxes) > 1:
            shape = "the large piece"
        else:
            shape = "the piece"
        out.append(f"{shape} {_place_words(0.5 * (x0 + x1) / size, 0.5 * (y0 + y1) / size)} is the {names[name]}")
    return out


def _split_name(name: str) -> tuple[str, int]:
    base, _, n = str(name).rpartition("_")
    if base and n.isdigit() and base in PROMPT_PIECE_NAMES:
        return base, int(n)
    return str(name), 1


def _pattern_key(name: str) -> tuple:
    base, n = _split_name(name)
    order = list(PROMPT_PIECE_NAMES)
    return (order.index(base) if base in PROMPT_PIECE_NAMES else len(order), base, n)


def _pattern_order(islands: dict) -> list[str]:
    """The payload's island names in pattern order (``PROMPT_PIECE_NAMES``, a split part after its first)."""
    return sorted((str(i["name"]) for i in islands.get("islands", [])), key=_pattern_key)


def prompt_pieces(islands: dict) -> list[str]:
    """The English panel names of the payload's islands in pattern order; a split part keeps its number
    (``front_2`` -> "front panel 2"); an unknown part name is spoken plainly after the known ones."""
    out = []
    for name in _pattern_order(islands):
        base, n = _split_name(name)
        word = PROMPT_PIECE_NAMES.get(base, base.replace("_", " "))
        out.append(word if n == 1 else f"{word} {n}")
    return out


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


# ---------------------------------------------------------------------------------------------------- the flow (Task 8)
#
# One click = one FLOW (``start`` -> thread -> ``generate``), never retried, never started by Build:
#
# 1. the piece's BACK view (``garment_template_views``, occasion ``garment_view``: the item picture turned around, the
#    piece alone) when the pattern has a back panel and the view does not exist yet — up to
#    ``garment_template_views.JOBS_PER_VIEW`` image jobs, the same view the projection fallback reads;
# 2. one routed upscale of an item picture under ``MIN_ITEM_SIDE``;
# 3. the FRONT job: a template with only the front-facing islands (``split_islands``), Picture 2 = the item picture;
# 4. the BACK job: a template with only the back panel, Picture 2 = the piece's back view (user finding 2026-11-20:
#    with ONE template and the item FRONT only, P-H3 painted the chest embroidery onto the back panel too);
# 5. post-processing PER JOB on its own islands (register, gate, cut + bleed, colour match), then both composed into
#    the one atlas; the seam continuity runs over the composed atlas, the front/back seams reported on their own;
# 6. on "ready": ``figure.invalidate`` + ``garment_assembly.schedule`` — the figure is re-assembled on the CPU with
#    the atlas (``start`` already set the piece's ``texture`` to "cut": the flow's only purpose).
#
# A job that fails or is rejected stops the flow: the next job that needs a render is not spent (a re-used passed
# answer still keeps its "ready" entry). Files under ``cut_dir`` per (item,
# csig): ``{item}_{csig}.json`` (the record), ``.template_front.png`` / ``.template_back.png`` (each template carries
# ONLY its job's islands, at their atlas positions), ``.item.png`` (Picture 2 of the front job), ``.back_ref.png``
# (Picture 2 of the back job), ``.raw_front.png`` / ``.raw_back.png`` (the answers) and ``.atlas.png``. The record is
# NOT a gallery image: the Improvements type ``fallback_rerender`` lists only character/location gallery metas, so
# ``route_meta`` here is information only.

#: The item image's long side below which it goes through the routed ``upscale`` occasion first (tiny 177-413 px item
#: pictures gave the wrong logo in the user's test jobs).
MIN_ITEM_SIDE = 1024
#: The reason of a job the media master switch stopped.
MEDIA_OFF = "Media generation is off — switch it on in /admin/settings → Media Generation"

#: The image jobs of the flow, in run order.
JOBS = ("front", "back")
#: Ruling 2026-11-20 — the parts the BACK job fills: the back panel alone (``back``, a split ``back_2`` too); step 3a
#: adds a trouser's back leg panels and a glove's palms (the back view shows them; tights and a bra have no back job).
#: Every other island goes with the FRONT job: the sleeves (the item picture shows them, with any print or cuff detail on
#: their visible side; a sleeve is one tube whose front and back halves are the same island, so it cannot follow the
#: back view for one half only), the neckband, collar, placket and cuffs.
BACK_PARTS = ("back", "back_l", "back_r", "palm_l", "palm_r")
#: Picture 2 of each job.
JOB_REFERENCE = {"front": "item", "back": "back_view"}

_running: dict[tuple[str, str], str] = {}
#: The step the flow of (character, item) is at: "back_view" / "upscale" / "front" / "back" / "post" / "apply".
_progress: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


class NotReady(ValueError):
    """The piece has no cut pattern (islands) yet, or no picture (a 400 for the route)."""


class Busy(RuntimeError):
    """Another hub-job flow of this piece runs (``piece_jobs``): the route answers 409 with this text."""


def part_of(name: str) -> str:
    """The pattern part of an island name: ``back_2`` -> "back", ``sleeve_l`` -> "sleeve_l"."""
    return _split_name(name)[0]


def job_of(name: str) -> str:
    """The job ("front" / "back") that fills an island (``BACK_PARTS``)."""
    return "back" if part_of(name) in BACK_PARTS else "front"


def split_islands(islands: dict) -> dict[str, dict]:
    """The payload split per job: ``{"front": payload, "back": payload}`` — each the full payload (same
    ``atlas_px`` / ``px_per_cm``, so the templates share the atlas frame and compose back into it) with only that
    job's islands and the seam pairs whose BOTH sides are in it. A job without islands is left out (a pattern without
    a back panel has the front job only)."""
    out = {}
    for job in JOBS:
        names = {str(i["name"]) for i in islands.get("islands", []) if job_of(str(i["name"])) == job}
        if not names:
            continue
        sub = {k: v for k, v in islands.items() if k not in ("islands", "seams")}
        sub["islands"] = [i for i in islands.get("islands", []) if str(i["name"]) in names]
        sub["seams"] = [p for p in islands.get("seams") or [] if str(p.get("a")) in names and str(p.get("b")) in names]
        out[job] = sub
    return out


def job_labels(islands: dict, size: int, job: str) -> np.ndarray:
    """The label raster of the WHOLE payload (global ids, ``island_ids``) with every island of another job set to 0
    — the job's mask and its per-island coverage keys stay those of the composed atlas."""
    labels = rasterise_islands(islands, size)
    keep = np.zeros(256, bool)
    ids = island_ids(islands)
    for name, iid in ids.items():
        keep[iid] = job_of(name) == job
    return np.where(keep[labels], labels, 0).astype(np.uint8)


def csig(islands_sha: str, item_sha: str, back_sha: str = "") -> str:
    """The cut atlas key: the cut's islands, the item image, the back view the back job read ("" for a pattern
    without a back panel, or before the view exists), the prompt files and the post-processing version — NOT
    ``tsig`` (it carries the piece-only views' sha for the projection, which the atlas does not depend on)."""
    raw = "|".join([str(islands_sha), str(item_sha), str(back_sha or ""), PROMPT_SHA,
                    str(cut_texture_post.POST_VERSION)])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def cut_dir(character_name: str) -> Path:
    """``characters/<name>/garments/templates/cut`` (not created here)."""
    from app.core.garment_store import garments_dir
    return garments_dir(character_name) / "templates" / "cut"


def _stem(character_name: str, item_id: str, sig: str) -> Path:
    return cut_dir(character_name) / f"{item_id}_{sig}"


def _file(stem: Path, suffix: str) -> Path:
    return stem.with_name(stem.name + suffix)


def current_drape(character_name: str, item_id: str) -> dict:
    """The piece's drape on the character's current base model — the same rule as the parameter dialog
    (``garment_template.piece_progress``): ``{state, reason, tsig, islands_path, islands_sha, record, worn}``;
    ``islands_path`` None when the ready drape carries no pattern islands (a kind still on the grid UV)."""
    from app.core import base_body, figure
    from app.core import garment_template as gt
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    profile = get_character_profile(character_name) or {}
    item = get_item(item_id)
    sets = figure.worn_sets(character_name, profile=profile)
    worn = item_id in set(sets.pieces.values())
    base = base_body.current_base(character_name, profile=profile)
    drape = gt.drape_state(character_name, item_id, base_sha=base[1] if base else "",
                           lower=gt.lower_layers(sets.own, item_id) if worn else [], item=item)
    record = drape.get("record") or {}
    islands = record.get("islands") or {}
    path = gt.templates_dir(character_name) / islands["file"] if islands.get("file") else None
    return {"state": drape["state"], "reason": drape.get("reason") or "", "tsig": drape.get("tsig"),
            "islands_path": path if path is not None and path.is_file() else None,
            "islands_sha": str(islands.get("sha256") or ""), "record": record if drape["state"] == "ready" else {},
            "worn": worn}


def current_pattern(character_name: str, item_id: str) -> dict:
    """The piece's CUT now (``garment_template_cut.state``): ``{state ("ready" / "cutting" / "missing" / "failed" /
    "blocked"), reason, cut_sig, islands_path, islands_sha, cut_at, wall_s, record}`` — the pattern every job, plan
    and sheet of this module reads. Never the drape's."""
    from app.core import garment_template_cut as gtc
    return gtc.state(character_name, item_id)


def _ready_pattern(character_name: str, item_id: str) -> dict:
    pattern = current_pattern(character_name, item_id)
    if pattern["state"] != "ready" or pattern.get("islands_path") is None or not pattern.get("islands_sha"):
        from app.core import garment_template_cut as gtc
        raise NotReady(pattern.get("reason") or gtc.NOT_CUT)
    return pattern


def _item_path(item_id: str) -> Path:
    from app.models.inventory import get_item_image_path
    path = get_item_image_path(item_id)
    if not path or not Path(path).is_file():
        raise NotReady(f"The item {item_id!r} has no picture")
    return Path(path)


#: sha256 of a picture per (path, mtime_ns, size): ``item_sha`` / ``back_sha`` are read by every assembly state check
#: of a piece whose texture is "cut", so an unchanged picture is hashed once.
_sha_cache: dict[tuple[str, int, int], str] = {}


def _sha_of(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    sha = _sha_cache.get(key)
    if sha is None:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(_sha_cache) > 512:
            _sha_cache.clear()
        _sha_cache[key] = sha
    return sha


def _item_sha(item_id: str) -> str:
    return _sha_of(_item_path(item_id))


def item_sha(item_id: str) -> str | None:
    """sha256 of the item picture, None when the item has none."""
    try:
        return _item_sha(item_id)
    except (NotReady, OSError):
        return None


def back_view(character_name: str, item_id: str) -> Path | None:
    """The piece's accepted BACK piece-only view (``garment_template_views``) — Picture 2 of the back job."""
    from app.core import garment_template_views as tv
    return tv.accepted(character_name, item_id, "back")


def back_sha(character_name: str, item_id: str) -> str:
    """sha256 of the accepted back view, "" without one."""
    path = back_view(character_name, item_id)
    try:
        return _sha_of(path) if path is not None else ""
    except OSError:
        return ""


def has_back(islands: dict) -> bool:
    """Whether the pattern has a back panel (the back job is due)."""
    return any(job_of(str(i["name"])) == "back" for i in islands.get("islands", []))


#: ``has_back`` per islands sha256 (``has_back_file``: the assembly's state check reads it on every figure read).
_back_cache: dict[str, bool] = {}


def has_back_file(path: Path, islands_sha: str) -> bool:
    """``has_back`` of a drape's ``islands.json`` (cached by its sha256); False when the file cannot be read."""
    hit = _back_cache.get(islands_sha)
    if hit is None:
        try:
            hit = has_back(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return False
        if len(_back_cache) > 512:
            _back_cache.clear()
        _back_cache[islands_sha] = hit
    return hit


def _islands_of(pattern: dict) -> dict:
    try:
        return json.loads(Path(pattern["islands_path"]).read_text(encoding="utf-8")) \
            if pattern.get("islands_path") else {}
    except (OSError, ValueError):
        return {}


def csig_for(character_name: str, item_id: str, islands_sha: str, islands: dict | None = None,
             *, has_back_panel: bool | None = None) -> str | None:
    """The csig of the piece for these islands with the CURRENT item picture and back view; None without a
    picture. ``has_back_panel`` None = read it from ``islands``."""
    isha = item_sha(item_id)
    if isha is None:
        return None
    if has_back_panel is None:
        has_back_panel = has_back(islands or {})
    return csig(islands_sha, isha, back_sha(character_name, item_id) if has_back_panel else "")


def atlas_path(character_name: str, item_id: str, sig: str) -> Path:
    """The accepted atlas of (item, csig) — written only for a "ready" record."""
    return _file(_stem(character_name, item_id, sig), ".atlas.png")


_CSIG_RE = re.compile(r"[0-9a-f]{12}")


def older_ready(character_name: str, item_id: str, sig: str) -> bool:
    """Whether the item has a READY cut record for a csig other than ``sig`` (the cut texture went stale)."""
    folder = cut_dir(character_name)
    if not folder.is_dir():
        return False
    prefix = f"{item_id}_"
    for path in folder.glob(f"{glob.escape(item_id)}_*.json"):
        other = path.name[len(prefix):-len(".json")]
        if other == sig or not _CSIG_RE.fullmatch(other):
            continue
        if read_record(character_name, item_id, other).get("state") == "ready":
            return True
    return False


def newer_cut_ready(character_name: str, item_id: str, islands_sha: str, since: str) -> bool:
    """Whether the item has a READY cut record for islands OTHER than ``islands_sha`` (another cut) made after
    ``since`` (a drape's ``created_at``): the texture was made from a new cut before the drape of it
    (``garment_template.cut_info`` "drape_behind"). False without ``since`` (a drape of unknown age is no proof)."""
    folder = cut_dir(character_name)
    if not since or not folder.is_dir():
        return False
    prefix = f"{item_id}_"
    for path in folder.glob(f"{glob.escape(item_id)}_*.json"):
        other = path.name[len(prefix):-len(".json")]
        if not _CSIG_RE.fullmatch(other):
            continue
        rec = read_record(character_name, item_id, other)
        if rec.get("state") == "ready" and str(rec.get("islands_sha") or "") not in ("", islands_sha) \
                and str(rec.get("created_at") or "") > since:
            return True
    return False


def current_csig(character_name: str, item_id: str) -> str | None:
    """The csig the piece would have now (a ready cut + item picture), else None."""
    try:
        pattern = _ready_pattern(character_name, item_id)
    except NotReady:
        return None
    return csig_for(character_name, item_id, pattern["islands_sha"], _islands_of(pattern))


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _flatten(im: Image.Image) -> Image.Image:
    """RGB on white (item pictures are RGBA on a transparent background)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        out = Image.new("RGB", rgba.size, BACKGROUND)
        out.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
        return out
    return im.convert("RGB")


def _lanczos_to(im: Image.Image, side: int) -> Image.Image:
    scale = side / max(im.size)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS)


def item_source(item_id: str) -> tuple[bytes, dict]:
    """The FULL-RES item picture flattened on white as PNG bytes, and ``{"item_px", "upscale"}``. Below
    ``MIN_ITEM_SIDE`` it goes through the routed upscale first (as ``footwear_source._step_source``): load
    (``BackendBusyError``) and the media switch are re-raised, any other failure falls back to Lanczos; a result still
    below the minimum is topped up with Lanczos."""
    from app.imagegen.base import BackendBusyError, MediaGenerationDisabled
    path = _item_path(item_id)
    with Image.open(path) as im:
        im.load()
        image = _flatten(im)
    size = [image.width, image.height]
    if max(image.size) >= MIN_ITEM_SIDE:
        upscale: dict = {"status": "not_needed"}
    else:
        from app.imagegen.service import get_image_service
        try:
            result = get_image_service().upscale_image(_png(image), character_name="")
        except (BackendBusyError, MediaGenerationDisabled):
            raise
        except Exception as e:  # noqa: BLE001 — Lanczos alone is the documented fallback
            logger.warning("Cut texture %s: upscale failed, Lanczos only: %s", item_id, e)
            upscale = {"status": "lanczos", "reason": str(e) or type(e).__name__}
        else:
            with Image.open(io.BytesIO(result["bytes"])) as up:
                image = up.convert("RGB")
            upscale = {k: v for k, v in result.items() if k not in ("bytes",)}
        if max(image.size) < MIN_ITEM_SIDE:
            image = _lanczos_to(image, MIN_ITEM_SIDE)
            upscale["topped_up_to"] = [image.width, image.height]
    return _png(image), {"item_px": size, "upscale": upscale}


def back_source(path: Path) -> bytes:
    """The back view flattened on white as PNG bytes (the view is a cut-out RGBA, square around the piece)."""
    with Image.open(path) as im:
        im.load()
        return _png(_flatten(im))


def piece_name(item_id: str) -> str:
    """The English name of the piece the prompt speaks of (``piece_name_of`` of the item's template params)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    return piece_name_of(gt.params_of(get_item(item_id)) or {})


def piece_name_of(params: dict) -> str:
    """The English name of a piece from its template params: a top by its sleeve length; step 3a the close-fitting
    kinds by their cut (briefs: boxer / string / thong / high-leg; a bra by its cup; gloves by fingers and length;
    tights by style and foot; trousers by length and leg)."""
    p = params or {}
    kind = str(p.get("kind") or "garment")
    if kind == "top":
        return {"none": "sleeveless top", "cap": "T-shirt", "short": "T-shirt", "elbow": "elbow-sleeve shirt",
                "long": "long-sleeve shirt"}.get(str(p.get("sleeves") or "short"), "top")
    if kind == "briefs":
        if float(p.get("leg_length_m") or 0.0) > 0:
            return "boxer briefs"
        if p.get("sides") == "string":
            return "string briefs"
        if float(p.get("back_coverage", 1.0)) < 0.15:
            return "thong"
        return "high-leg briefs" if float(p.get("leg_cut", 0.5)) > 1.0 else "briefs"
    if kind == "bra":
        return {"balconette": "balconette bra", "triangle": "triangle bra", "bandeau": "bandeau"}.get(
            str(p.get("cup_style") or ""), "bra")
    if kind == "gloves":
        if p.get("fingers") == "none":
            return "arm warmers"
        base = "fingerless gloves" if p.get("fingers") == "fingerless" else "gloves"
        return {"forearm": "forearm-length ", "elbow": "elbow-length ", "opera": "opera "}.get(
            str(p.get("length") or "wrist"), "") + base
    if kind == "tights":
        style = str(p.get("tights_style") or "tights")
        if style == "knee_high":
            return "knee-high socks"
        if style in ("hold_up", "thigh_high"):
            return "hold-up stockings" if style == "hold_up" else "thigh-high stockings"
        return {"footless": "footless tights", "stirrup": "stirrup tights"}.get(str(p.get("feet") or ""), "tights")
    if kind == "trousers":
        if p.get("leg_shape") == "skinny" and p.get("hem") == "stirrup":
            return "stirrup leggings"
        if p.get("leg_shape") == "skinny" and float(p.get("fit", 0.3)) == 0.0:
            return "leggings"
        return {"shorts": "shorts", "knee": "knee-length trousers", "capri": "capri trousers",
                "ankle": "ankle trousers"}.get(str(p.get("trouser_length") or "full"), "trousers")
    return kind.replace("_", " ")


def _item_matte():
    """The matte function the colour match cuts the item fabric with (BiRefNet; a smoke returns None = key only)."""
    from app.core import garment_matte
    return garment_matte.birefnet_matte


def _upsampler_on(b) -> bool:
    """A P-H3 backend whose entry does not switch the prompt upsampler off (a warning, not a block)."""
    from app.core.prompt_adapters import uses_picture_references
    if not uses_picture_references(str(getattr(b, "model", "") or "")):
        return False
    return (getattr(b, "extra_params", None) or {}).get("use_prompt_upsampler") is not False


def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    tmp.replace(path)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_record(character_name: str, item_id: str, sig: str) -> dict:
    try:
        data = json.loads(_file(_stem(character_name, item_id, sig), ".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _failure_reason(e: BaseException) -> str:
    from app.imagegen.base import BackendBusyError, MediaGenerationDisabled
    from app.imagegen.routing import NoRouteError
    if isinstance(e, MediaGenerationDisabled):
        return MEDIA_OFF
    if isinstance(e, NoRouteError):
        return str(e)
    if isinstance(e, BackendBusyError):
        return f"The backend is busy — try again later ({e})"
    return str(e) or type(e).__name__


def _routed_render(item_id: str, side: str, prompt: str, template_png: Path, ref_png: Path, seed: int):
    """ONE routed img2img render of a job's template + its Picture 2 -> ``(answer bytes, backend, route)``."""
    from app.core.prompt_compose import compose
    from app.imagegen import routing as _routing
    from app.imagegen.service import get_image_service
    svc = get_image_service()

    def _render(b):
        composed = compose(use_case=CUT_USE_CASE, subject=prompt, backend=b)
        for warning in composed.warnings:
            logger.info("Prompt composer (%s): %s", CUT_USE_CASE, warning)
        params = {"seed": seed,
                  "reference_images": {"input_reference_image_1": str(template_png),
                                       "input_reference_image_2": str(ref_png)}}
        log_meta = {"agent_name": f"Cut texture {item_id} ({side})", "original_prompt": prompt,
                    "auto_enhance": False, "compose": composed.meta}

        def _op(bb):
            # through the backend's GPU channel: never two generations on one backend at once
            return svc.run_on_backend_channel(
                bb, lambda: bb.generate(composed.prompt, composed.negative, params, log_meta=log_meta),
                task_type="garment_cut_texture", agent_name="system", label=f"Cut texture ({side}): {item_id}")
        return svc.run_on_backend(b, op=_op)

    (images, used), route = _routing.run_routed(CUT_OCCASION, _render, has_ref=True, pool=svc.pool)
    if not isinstance(images, (list, tuple)) or not images or not isinstance(images[0], (bytes, bytearray)):
        raise RuntimeError("the cut-texture render delivered no image")
    return bytes(images[0]), used, route


def _set_progress(key: tuple[str, str], step: str) -> None:
    with _lock:
        _progress[key] = step


def progress_step(character_name: str, item_id: str) -> str:
    """The step the running flow of the piece is at ("" when none runs)."""
    with _lock:
        if _running.get((character_name, item_id)) != "running":
            return ""
        return _progress.get((character_name, item_id), "")


def _ensure_back_view(character_name: str, item_id: str) -> dict:
    """Step 1: the piece's back view — made here when missing (``garment_template_views.generate``, up to
    ``JOBS_PER_VIEW`` image jobs; inside the cut's own piece claim). ``{"made": bool, "jobs": n}``; raises
    ``RuntimeError`` with a plain reason when every attempt was refused."""
    from app.core import garment_template_views as tv
    if back_view(character_name, item_id) is not None:
        return {"made": False, "jobs": 0}
    try:
        tv.generate(character_name, item_id, "back")
    except tv.ViewRefused as e:
        raise RuntimeError(f"The back view was refused ({e}) — choose an attempt or upload one in Views, then "
                           "make the texture again") from e
    return {"made": True, "jobs": None}


def reused_jobs(character_name: str, item_id: str, sig: str, parts, *, only: str | None = None) -> dict:
    """The jobs whose stored answer of csig ``sig`` a flow re-uses instead of rendering it again: every job of
    ``parts`` other than ``only`` whose record entry is "ready" and whose raw answer file exists (re-posted from that
    file, 0 image jobs). Run all (``only`` None) therefore spends only on what did not pass — a rejected back job
    re-renders the back alone (review finding 2026-11-20); Redo ``only`` always renders that job. The ONE rule both
    ``generate`` and ``job_plan`` (the buttons' counts) use. ``{job: record entry}``."""
    previous = read_record(character_name, item_id, sig)
    stem = _stem(character_name, item_id, sig)
    out = {}
    for job in parts:
        entry = (previous.get("jobs") or {}).get(job) or {}
        if job != only and entry.get("state") == "ready" and _file(stem, f".raw_{job}.png").is_file():
            out[job] = entry
    return out


def _plan_one(character_name: str, item_id: str, islands: dict, islands_sha: str, side: int,
              only: str | None) -> dict:
    from app.core import garment_template_views as tv
    parts = [j for j in JOBS if j == "front" or has_back(islands)]
    view = 1 if "back" in parts and back_view(character_name, item_id) is None else 0
    reuse = {}
    sig = None
    if not view and islands_sha:
        sig = csig_for(character_name, item_id, islands_sha, islands, has_back_panel="back" in parts)
        if sig:
            reuse = reused_jobs(character_name, item_id, sig, parts, only=only)
    todo = [j for j in parts if j not in reuse]
    item_png = _file(_stem(character_name, item_id, sig), ".item.png") if sig else None
    upscale = 1 if 0 < side < MIN_ITEM_SIDE and ("front" in todo or item_png is None or not item_png.is_file()) \
        else 0
    front = 1 if "front" in todo else 0
    back = 1 if "back" in todo else 0
    total = view + upscale + front + back
    return {"back_view": view, "upscale": upscale, "front": front, "back": back, "total": total,
            "max": total + view * (tv.JOBS_PER_VIEW - 1), "reused": sorted(reuse)}


def job_plan(character_name: str, item_id: str, islands: dict | None = None, islands_sha: str = "") -> dict:
    """What one click spends now — the buttons' counts, by the same reuse rule ``generate`` runs (``reused_jobs``):
    Run all ``{"back_view" (0 / 1, at most ``JOBS_PER_VIEW``), "upscale" (0 / 1), "front" (0 / 1), "back" (0 / 1),
    "total", "max", "reused" (the jobs whose answer is kept)}`` (``max``: a refused back-view attempt is made once
    more) and ``redo`` = the same per Redo button (``{"front": {...}, "back": {...}}``, "back" only with a back
    panel)."""
    if islands is None or not islands_sha:
        try:
            pattern = _ready_pattern(character_name, item_id)
            islands, islands_sha = _islands_of(pattern), pattern["islands_sha"]
        except NotReady:
            islands, islands_sha = islands or {}, ""
    side = _item_side(item_id)
    out = _plan_one(character_name, item_id, islands, islands_sha, side, None)
    out["redo"] = {job: _plan_one(character_name, item_id, islands, islands_sha, side, job)
                   for job in JOBS if job == "front" or has_back(islands)}
    return out


#: User test 2026-11-21 — the parts of each job whose pixels come from the model's answer; every other island of the
#: job (the sleeves, the neckband, the cuffs) is filled with the seamless fabric patch of the job's main panel
#: (``fill_fabric``). With the piece's ``sleeve_print`` "picture" the sleeves and cuffs come from the answer too.
MODEL_PARTS = {"front": ("front", "collar", "placket"), "back": ("back",)}
SLEEVE_PARTS = ("sleeve_l", "sleeve_r", "cuff_l", "cuff_r")
#: The panel each job's gates measure and its fabric patch is cut from.
MAIN_PART = {"front": "front", "back": "back"}
#: A pre-fill nearer to white than this (the largest channel distance) is darkened to it: the gate and the
#: registration find the islands as "not near-white" (``cut_texture_post.WHITE_TOL`` 24), so a white fabric goes as a
#: very light grey (the colour match moves the atlas back onto the item's own white).
PREFILL_MIN_DIST = 40


def model_parts(job: str, sleeve_print: str = "plain") -> tuple[str, ...]:
    """The parts of ``job`` taken from the model's answer (``MODEL_PARTS``, the sleeves with "picture")."""
    parts = MODEL_PARTS.get(job, ())
    return parts + SLEEVE_PARTS if job == "front" and sleeve_print == "picture" else parts


def prefill_colour(colour: dict | None) -> tuple[int, int, int] | None:
    """The colour the template's islands are pre-filled with: the item's base fabric colour
    (``cut_texture_post.fabric_colour``), darkened to ``PREFILL_MIN_DIST`` from white when nearer; None without one."""
    if not colour:
        return None
    rgb = np.asarray(colour["rgb"], np.float64)
    dist = float((255.0 - rgb).max())
    if dist < PREFILL_MIN_DIST:
        rgb = 255.0 - (255.0 - rgb) * (PREFILL_MIN_DIST / dist) if dist > 0 else np.full(3, 255.0 - PREFILL_MIN_DIST)
    return tuple(int(v) for v in np.clip(np.rint(rgb), 0, 255))


def _part_mask(islands: dict, labels: np.ndarray, parts) -> np.ndarray:
    keep = np.zeros(256, bool)
    for name, iid in island_ids(islands).items():
        keep[iid] = part_of(name) in parts
    return keep[labels]


def fill_fabric(img: np.ndarray, labels: np.ndarray, grown: np.ndarray, islands: dict, job: str, px_per_cm: float,
                sleeve_print: str = "plain") -> tuple[np.ndarray, dict]:
    """The islands of ``job`` that are not ``model_parts`` (and the bleed around them: the grown pixels whose nearest
    island is one of them) filled with a seamless patch of the job's main panel (``cut_texture_post.fabric_patch`` on
    the panel eroded by ``LINE_PX + 1``, ``mirror_tile``, the Lab mean moved onto the panel's base fabric colour).
    ``labels`` are the job's labels (``job_labels``). Returns the image and ``{"islands", "patch", "base",
    "shift"}`` ({"islands": []} when there is nothing to fill, {"skipped": reason} when no patch fits)."""
    from scipy import ndimage
    post = cut_texture_post
    keep = model_parts(job, sleeve_print)
    ids = island_ids(islands)
    fabric_names = sorted(n for n, iid in ids.items() if job_of(n) == job and part_of(n) not in keep
                          and (labels == iid).any())
    if not fabric_names:
        return img, {"islands": []}
    panel = _part_mask(islands, labels, (MAIN_PART[job],))
    if not panel.any():
        return img, {"islands": fabric_names, "skipped": "no main panel"}
    base = post.fabric_colour(img, panel)
    found = post.fabric_patch(img, ndimage.binary_erosion(panel, iterations=LINE_PX + 1), px_per_cm,
                              base["lab"] if base else None)
    if found is None or base is None:
        return img, {"islands": fabric_names, "skipped": "no fabric patch fits the main panel"}
    patch, info = found
    _, (iy, ix) = ndimage.distance_transform_edt(labels == 0, return_indices=True)
    nearest = labels[iy, ix]
    fab_ids = np.zeros(256, bool)
    for n in fabric_names:
        fab_ids[ids[n]] = True
    region = np.asarray(grown, bool) & fab_ids[nearest]
    out, tinfo = post.tile_fill(img, region, patch, base["lab"])
    return out, {"islands": fabric_names, "patch": info, "base": base["rgb"], "shift": tinfo["shift"]}


def _post_job(answer: bytes, islands: dict, size: int, px_per_cm: float, job: str, refs: dict, *,
              force: bool = False, sleeve_print: str = "plain") -> dict:
    """Task 7 on ONE job's answer, against that job's islands only (``job_labels``): register, gate, cut + bleed,
    colour match to the ITEM fabric (both jobs — ruling 2026-11-20: the item picture is the colour truth, the back view
    a model's copy of it; matching both to it keeps the side seams continuous), then the fabric fill of the islands
    the model does not paint (``fill_fabric``). The gates: the island gate (``cut_texture_post.gate``) and the answer
    gates of the job's main panel (``cut_texture_post.answer_gates``: its colour against the item's, its detail
    against the job's Picture 2 — ``refs`` = ``{"colour": item colour, "detail": {job: density}, "fabric": the
    colour match's fabric pixels}``). ``force`` (the user's "Use this answer") posts a failing answer anyway and marks
    it ``accepted``. ``{"state", "reason", "metrics", "accepted", "_image", "_grown", "_mask"}`` (the arrays only on
    ``ready``); ``metrics.failures`` lists every failing gate."""
    post = cut_texture_post
    labels = job_labels(islands, size, job)
    mask = labels > 0
    with Image.open(io.BytesIO(answer)) as im:
        im.load()
        reg, reg_info = post.resample_register(im, mask)
    ok, met, reason = post.gate(reg, mask, labels, px_per_cm)
    panel = _part_mask(islands, labels, (MAIN_PART[job],))
    gates, answer = post.answer_gates(reg, panel, refs.get("colour"), (refs.get("detail") or {}).get(job))
    failures = list(met["failures"]) + [g["text"] for g in gates if not g["ok"]]
    metrics = {"iou": met["iou"], "coverage": met["coverage"], "island_coverage": met["island_coverage"],
               "spill": met["spill"], "registration": reg_info, "islands": met["islands"],
               "gates": gates, "fabric": answer["fabric"], "detail": answer["detail"], "failures": failures}
    if failures and not force:
        metrics.update({"de_before": None, "de_after": None, "clamped": None})
        return {"state": "rejected", "reason": failures[0], "metrics": metrics, "accepted": False}
    cut = post.cut_and_bleed(reg, mask, max(1, int(round(post.BLEED_CM * px_per_cm))))
    grown = ~np.all(cut == 255, axis=-1) | mask
    matched, cm = post.colour_match(cut, grown, fabric=refs.get("fabric"))
    filled, fill = fill_fabric(matched, labels, grown, islands, job, px_per_cm, sleeve_print)
    metrics.update({"de_before": cm.get("de_before"), "de_after": cm.get("de_after"),
                    "clamped": cm.get("clamped"), "colour": cm, "fabric_fill": fill})
    return {"state": "ready", "reason": "", "metrics": metrics, "accepted": bool(failures),
            "_image": filled, "_grown": grown, "_mask": mask}


def references(character_name: str, item_id: str, has_back_panel: bool) -> dict:
    """``_post_job``'s ``refs`` and the pre-fill: ONE ``garment_matte.cut`` of the item picture (BiRefNet,
    ``_item_matte``) for its base fabric colour, its detail and the colour match's fabric; the back view's detail for
    the back job (its alpha is the cut-out). ``{"colour", "prefill", "detail": {"front", "back"}, "fabric"}``."""
    post = cut_texture_post
    with Image.open(_item_path(item_id)) as it:
        item_rgba = np.asarray(it.convert("RGBA"))
    item = post.picture_reference(item_rgba, matte=_item_matte())
    detail = {"front": item["detail"]}
    if has_back_panel:
        path = back_view(character_name, item_id)
        if path is not None:
            with Image.open(path) as bv:
                detail["back"] = post.picture_reference(np.asarray(bv.convert("RGBA")), matte=None)["detail"]
    return {"colour": item["colour"], "prefill": prefill_colour(item["colour"]), "detail": detail,
            "fabric": item["fabric"]}


def compose(results: dict, size: int) -> np.ndarray:
    """The one atlas from the jobs' post-processed images: white, then the FRONT job inside its grown area (islands +
    bleed), then the BACK job inside its grown area wherever the front's islands are not, then the back's own islands
    — an island's own pixels always beat the other job's bleed (the islands are disjoint)."""
    out = np.full((size, size, 3), 255, np.uint8)
    order = [j for j in JOBS if j in results]
    for job in order:
        r = results[job]
        sel = r["_grown"].copy()
        for other in order:
            if other != job:
                sel &= ~results[other]["_mask"]
        out[sel] = r["_image"][sel]
    for job in order:
        m = results[job]["_mask"]
        out[m] = results[job]["_image"][m]
    return out


def cross_seams(islands: dict) -> list[dict]:
    """The seam pairs whose two sides are filled by different jobs (the side and shoulder seams front <-> back)."""
    return [p for p in islands.get("seams") or [] if job_of(str(p.get("a"))) != job_of(str(p.get("b")))]


def _summary_metrics(jobs: dict, seam: dict | None, cross: dict | None) -> dict:
    """The record's top-level metrics over the jobs that ran: the worst IoU / coverage / island coverage, the largest
    spill and dE, any clamp; the seam medians of the composed atlas (``seam_de`` all pairs, ``seam_cross_de`` the
    front/back pairs)."""
    ran = [j["metrics"] for j in jobs.values() if j.get("metrics")]

    def worst(key, fn):
        vals = [m.get(key) for m in ran if m.get(key) is not None]
        return fn(vals) if vals else None
    return {"iou": worst("iou", min), "coverage": worst("coverage", min),
            "island_coverage": worst("island_coverage", min), "spill": worst("spill", max),
            "de_before": worst("de_before", max), "de_after": worst("de_after", max),
            "clamped": any(bool(m.get("clamped")) for m in ran) if ran else None,
            "seam_de": (seam or {}).get("median"), "seam_cross_de": (cross or {}).get("median"),
            "seams": seam, "seams_cross": cross}


#: The reason of a job that has no answer yet while the job before it passed (or was accepted by the user).
NOT_MADE = "Not made yet — Make texture from cut renders it"
SKIPPED = "Not run — the job before it did not pass"


def sleeve_print_of(item_id: str) -> str:
    """The piece's ``sleeve_print`` param ("plain" without one)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    value = str((gt.params_of(get_item(item_id)) or {}).get("sleeve_print") or "plain")
    return value if value in gt.SLEEVE_PRINTS else "plain"


def _finish(character_name: str, item_id: str, record: dict, parts: dict, results: dict, islands: dict,
            size: int, stem: Path, *, apply_after: bool = True) -> dict:
    """The end of a flow and of a re-compose: the missing job entries ("skipped" behind a job that did not pass,
    ``NOT_MADE`` behind passed ones), the record's state (the first job that is not ready gives "rejected" and the
    reason), on "ready" the composed atlas and the seam metrics; the record written, the figure re-assembled on
    "ready" (``apply_after`` False — the Build's own step: only ``figure.invalidate``, its assembly step comes next)."""
    from app.core.timeutils import utc_now_iso
    blocked = False
    for job in parts:
        entry = record["jobs"].get(job)
        if entry is None or entry.get("state") == "skipped":
            record["jobs"][job] = {**(entry or {}), "state": "skipped", "reason": SKIPPED if blocked else NOT_MADE,
                                   "reference": JOB_REFERENCE[job]}
        if record["jobs"][job].get("state") != "ready":
            blocked = True
    record["upsampler_on"] = any(j.get("upsampler_on") for j in record["jobs"].values())
    bad = [(j, record["jobs"][j]) for j in parts if record["jobs"][j]["state"] != "ready" or j not in results]
    atlas = None
    if bad:
        job, entry = bad[0]
        record.update({"state": "rejected", "reason": f"{job.capitalize()}: {entry.get('reason') or NOT_MADE}"})
        record["metrics"] = _summary_metrics(record["jobs"], None, None)
    else:
        atlas = compose(results, size)
        seam = cut_texture_post.seam_continuity(atlas, islands.get("seams") or [])
        cross = cut_texture_post.seam_continuity(atlas, cross_seams(islands))
        record.update({"state": "ready", "reason": "", "metrics": _summary_metrics(record["jobs"], seam, cross)})
    record["created_at"] = utc_now_iso()
    _file(stem, ".atlas.png").unlink(missing_ok=True)
    if atlas is not None:
        _write_bytes(_file(stem, ".atlas.png"), _png(Image.fromarray(atlas, "RGB")))
    _write_record(_file(stem, ".json"), record)
    if record["state"] == "ready" and apply_after:
        _set_progress((character_name, item_id), "apply")
        apply(character_name)
    else:
        from app.core import figure
        figure.invalidate()     # the Figure tab, the plan and the open-steps badges read the new record
    return record


def _entry_from_post(entry: dict, res: dict) -> dict:
    entry = {k: v for k, v in entry.items() if k not in ("accepted", "accepted_over")}
    entry.update({"state": res["state"], "reason": res["reason"], "metrics": res["metrics"]})
    if res.get("accepted"):
        entry.update({"accepted": True, "accepted_over": res["metrics"]["failures"][0]})
    return entry


def generate(character_name: str, item_id: str, *, only: str | None = None, apply_after: bool = True) -> dict:
    """ONE flow (module comment above): -> the record (``state`` "ready", "rejected" or "failed"). A job whose answer
    of the same csig passed (or was accepted, ``use_answer``) is re-used (re-posted from its raw file,
    ``reused_jobs``) — Run all renders only what did not pass; ``only`` "front" / "back" always renders that job and
    keeps the other's passed answer (without one both run). A rejected job stops only the jobs that still need a
    render: a re-used answer costs no image job and is posted (and stays "ready") behind it, so "Use this answer" on
    the rejected one composes the atlas without spending the re-used job again. Raises ``NotReady`` before anything is written when the
    piece has no ready cut or no picture; every later failure is recorded as "failed" and returned."""
    from app.imagegen.routing import route_meta
    key = (character_name, item_id)
    pattern = _ready_pattern(character_name, item_id)
    _item_path(item_id)
    islands = json.loads(Path(pattern["islands_path"]).read_text(encoding="utf-8"))
    parts = split_islands(islands)
    px_per_cm = float(islands.get("px_per_cm") or 0.0)
    size = int(islands.get("atlas_px") or 2048)
    from app.core.timeutils import utc_now_iso
    record: dict = {"islands_sha": pattern["islands_sha"], "cut_sig": pattern.get("cut_sig"), "state": "failed",
                    "reason": "", "metrics": {}, "jobs": {}, "px_per_cm": px_per_cm, "item_px": None,
                    "upscale": None, "prompt_sha": PROMPT_SHA, "post_version": cut_texture_post.POST_VERSION,
                    "item_sha": _item_sha(item_id), "back_sha": "", "back_view": {"made": False, "jobs": 0},
                    "only": only or "", "sleeve_print": sleeve_print_of(item_id)}
    sig = csig(pattern["islands_sha"], record["item_sha"])
    try:
        if "back" in parts:
            _set_progress(key, "back_view")
            record["back_view"] = _ensure_back_view(character_name, item_id)
            record["back_sha"] = back_sha(character_name, item_id)
        sig = csig(pattern["islands_sha"], record["item_sha"], record["back_sha"])
    except Exception as e:  # noqa: BLE001 — the flow's failure is the record
        logger.warning("Cut texture %s %s: back view: %s", character_name, item_id, e)
        record.update({"csig": sig, "state": "failed", "reason": _failure_reason(e), "created_at": utc_now_iso()})
        _write_record(_file(_stem(character_name, item_id, sig), ".json"), record)
        return record
    record["csig"] = sig
    stem = _stem(character_name, item_id, sig)
    previous = read_record(character_name, item_id, sig)
    reuse = reused_jobs(character_name, item_id, sig, parts, only=only)
    todo = [j for j in parts if j not in reuse]
    stale = [_file(stem, ".atlas.png")] + [_file(stem, f".raw_{j}.png") for j in todo]
    for path in stale:
        path.unlink(missing_ok=True)       # this attempt's record never sits next to another attempt's files
    results: dict = {}
    try:
        item_png, back_png = _file(stem, ".item.png"), _file(stem, ".back_ref.png")
        if "front" in todo or not item_png.is_file():
            _set_progress(key, "upscale")
            data, info = item_source(item_id)
            record.update(info)
            _write_bytes(item_png, data)
        else:
            record.update({"item_px": previous.get("item_px"), "upscale": previous.get("upscale")})
        if "back" in parts:
            _write_bytes(back_png, back_source(back_view(character_name, item_id)))
        refs = references(character_name, item_id, "back" in parts)
        record["fabric"] = {"item": refs["colour"], "prefill": list(refs["prefill"]) if refs["prefill"] else None,
                            "detail": refs["detail"]}
        name = piece_name(item_id)
        stopped = False             # a job did not pass: no further image job is spent, re-used answers still post
        for job in parts:
            if stopped and job not in reuse:
                continue
            template_png = _file(stem, f".template_{job}.png")
            _write_bytes(template_png, _png(render_template(parts[job], size, fill=refs["prefill"])))
            raw_png = _file(stem, f".raw_{job}.png")
            if job in reuse:
                answer = raw_png.read_bytes()
                entry = {k: v for k, v in reuse[job].items() if k not in ("metrics", "state", "reason")}
                force = bool(reuse[job].get("accepted"))
            else:
                _set_progress(key, job)
                prompt = render_prompt(piece=name, pieces=prompt_pieces(parts[job]), side=job,
                                       layout=layout_words(parts[job]))
                seed = (int(sig[:8], 16) + (0 if job == "front" else 1)) % 2 ** 31
                ref = item_png if job == "front" else back_png
                try:
                    answer, used, route = _routed_render(item_id, job, prompt, template_png, ref, seed)
                except Exception as e:  # noqa: BLE001 — the job's failure stops the flow
                    record["jobs"][job] = {"state": "failed", "reason": _failure_reason(e),
                                           "reference": JOB_REFERENCE[job]}
                    raise
                _write_bytes(raw_png, answer)
                entry = {"backend": getattr(used, "name", ""), "routing": route_meta(route),
                         "upsampler_on": _upsampler_on(used), "reference": JOB_REFERENCE[job],
                         "islands": [str(i["name"]) for i in parts[job]["islands"]]}
                force = False
            _set_progress(key, "post")
            res = _post_job(answer, islands, size, px_per_cm, job, refs, force=force,
                            sleeve_print=record["sleeve_print"])
            record["jobs"][job] = _entry_from_post(entry, res)
            if res["state"] != "ready":
                stopped = True      # a rejected job stops the flow: the next job that needs a render is not spent
                continue
            results[job] = res
    except Exception as e:  # noqa: BLE001 — a job's failure is the record, shown in the dialog
        logger.warning("Cut texture %s %s failed: %s", character_name, item_id, e)
        failed = next((j for j in JOBS if (record["jobs"].get(j) or {}).get("state") == "failed"), "")
        reason = _failure_reason(e)
        record.update({"state": "failed", "reason": f"{failed.capitalize()}: {reason}" if failed else reason})
        for job in parts:       # a re-used answer that was not posted yet keeps its passed entry (its raw file stays)
            record["jobs"].setdefault(job, dict(reuse[job]) if job in reuse else
                                      {"state": "skipped", "reason": SKIPPED, "reference": JOB_REFERENCE[job]})
        record["upsampler_on"] = any(j.get("upsampler_on") for j in record["jobs"].values())
        record["created_at"] = utc_now_iso()
        _write_record(_file(stem, ".json"), record)
        return record
    for job in parts:
        record["jobs"].setdefault(job, {"state": "skipped", "reason": SKIPPED, "reference": JOB_REFERENCE[job]})
    return _finish(character_name, item_id, record, parts, results, islands, size, stem, apply_after=apply_after)


def usable_answers(character_name: str, item_id: str, sig: str | None = None) -> dict:
    """Per job of the current csig (``sig``): whether its answer can be put on the figure by hand (``use_answer``) —
    ``{job: {"raw": the answer file exists, "state", "accepted", "can_use"}}``; ``can_use`` = an answer exists and it
    was rejected (accept it) or it passed (compose with it again)."""
    sig = sig or current_csig(character_name, item_id)
    if not sig:
        return {}
    record = read_record(character_name, item_id, sig)
    stem = _stem(character_name, item_id, sig)
    out = {}
    for job, entry in (record.get("jobs") or {}).items():
        raw = _file(stem, f".raw_{job}.png").is_file()
        state = str(entry.get("state") or "")
        out[job] = {"raw": raw, "state": state, "accepted": bool(entry.get("accepted")),
                    "can_use": raw and state in ("ready", "rejected")}
    return out


def recompose(character_name: str, item_id: str, *, accept: str | None = None, apply_after: bool = True) -> dict:
    """The CPU path of "Use this answer" (``accept`` = the job whose shown answer the user puts on the figure, also a
    rejected one: it is marked ``accepted`` with the reason it overrode) and of a changed ``sleeve_print``
    (``accept`` None): every job of the current csig whose answer passed or was accepted is post-processed again from
    its raw file — no image job — and, when every job has one, the atlas is composed and applied. A job without an
    answer stays "skipped" (``NOT_MADE`` once the jobs before it are in): Run all renders exactly that one next.
    Raises ``NotReady`` when the piece has no ready cut, no record or (``accept``) no answer of that job."""
    pattern = _ready_pattern(character_name, item_id)
    islands = json.loads(Path(pattern["islands_path"]).read_text(encoding="utf-8"))
    parts = split_islands(islands)
    sig = csig_for(character_name, item_id, pattern["islands_sha"], islands, has_back_panel="back" in parts)
    record = read_record(character_name, item_id, sig) if sig else {}
    if not record:
        raise NotReady("Nothing to use yet — make the texture from cut first")
    stem = _stem(character_name, item_id, sig)
    if accept is not None:
        if accept not in parts:
            raise ValueError(f"job must be one of {', '.join(parts)}")
        entry = record.get("jobs", {}).get(accept) or {}
        if not _file(stem, f".raw_{accept}.png").is_file() or entry.get("state") not in ("ready", "rejected"):
            raise NotReady(f"The {accept} job has no answer to use — redo it first")
    size = int(islands.get("atlas_px") or 2048)
    px_per_cm = float(islands.get("px_per_cm") or 0.0)
    record["sleeve_print"] = sleeve_print_of(item_id)
    _set_progress((character_name, item_id), "post")
    refs = references(character_name, item_id, "back" in parts)
    record["fabric"] = {"item": refs["colour"], "prefill": list(refs["prefill"]) if refs["prefill"] else None,
                        "detail": refs["detail"]}
    results = {}
    for job in parts:
        entry = dict(record["jobs"].get(job) or {})
        raw = _file(stem, f".raw_{job}.png")
        wanted = job == accept or entry.get("state") == "ready"
        if not wanted or not raw.is_file():
            continue
        force = job == accept or bool(entry.get("accepted"))
        res = _post_job(raw.read_bytes(), islands, size, px_per_cm, job, refs, force=force,
                        sleeve_print=record["sleeve_print"])
        record["jobs"][job] = _entry_from_post(entry, res)
        if res["state"] == "ready":
            results[job] = res
    return _finish(character_name, item_id, record, parts, results, islands, size, stem, apply_after=apply_after)


def set_sleeve_print(character_name: str, item_id: str, value: str, *, run=None) -> dict:
    """Store the piece's ``sleeve_print`` ("plain" / "picture", ``TEXTURE_ONLY``: no drape) and, when the current
    record has a ready atlas or accepted / passed answers, compose it again on the CPU in the background
    (``recompose`` through ``start_recompose``). ``{"changed": bool, "recompose": bool}``."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    if value not in gt.SLEEVE_PRINTS:
        raise ValueError(f"sleeve_print must be one of {', '.join(gt.SLEEVE_PRINTS)}")
    item = get_item(item_id)
    params = gt.params_of(item)
    if not params:
        raise NotReady("The piece has no template parameters yet")
    changed = str(params.get("sleeve_print") or "plain") != value
    if changed:
        source = ((item or {}).get("outfit_piece") or {}).get("template", {}).get("source") or "user"
        gt.set_params(item_id, {**params, "sleeve_print": value}, source=source)
    usable = usable_answers(character_name, item_id)
    again = any(u["state"] == "ready" and u["raw"] for u in usable.values())
    started = bool(again and start_recompose(character_name, item_id, run=run))
    return {"changed": changed, "recompose": started}


def apply(character_name: str) -> bool:
    """Step 6: the figure picks the new atlas up — ``figure.invalidate`` (the assembly state carries ``cut:<csig>``)
    and a background re-assembly of the served model (``garment_assembly.schedule``, CPU, no hub job). True when an
    assembly was started."""
    from app.core import figure
    figure.invalidate()
    try:
        from app.core import garment_assembly
        return bool(garment_assembly.schedule(character_name))
    except Exception as e:  # noqa: BLE001 — the next serve asks for the build anyway
        logger.warning("Cut texture %s: re-assembly not scheduled: %s", character_name, e)
        return False


def select_cut(item_id: str) -> bool:
    """Set the piece's ``texture`` param to "cut" (the flow's only purpose; a CPU re-assemble, no drape). True when it
    changed."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    item = get_item(item_id)
    params = gt.params_of(item)
    if not params or params.get("texture") == "cut":
        return False
    source = ((item or {}).get("outfit_piece") or {}).get("template", {}).get("source") or "user"
    gt.set_params(item_id, {**params, "texture": "cut"}, source=source)
    return True


def start(character_name: str, item_id: str, *, run=None, only: str | None = None) -> bool:
    """Check SYNCHRONOUSLY (so the HTTP answer carries the reason), select the texture "cut" and start ``generate``
    in a thread; False when this piece's cut already runs. Raises ``MediaGenerationDisabled`` (media off),
    ``NoRouteError`` (empty chain), ``NotReady`` (no ready cut, no picture) or ``Busy`` (another
    hub-job flow of the piece runs — ``piece_jobs``) before any thread or file exists."""
    from app.imagegen import routing as _routing
    from app.imagegen.base import MediaGenerationDisabled, media_generation_enabled
    if only not in (None, *JOBS):
        raise ValueError(f"only must be one of {', '.join(JOBS)}")
    if not media_generation_enabled():
        raise MediaGenerationDisabled(MEDIA_OFF)
    if not _routing.chain_for(CUT_OCCASION):
        raise _routing.NoRouteError(CUT_OCCASION, [])
    _ready_pattern(character_name, item_id)
    _item_path(item_id)
    fn = run or generate
    return _launch(character_name, item_id, lambda: fn(character_name, item_id, **({"only": only} if only else {})),
                   select=True)


def start_recompose(character_name: str, item_id: str, *, accept: str | None = None, run=None) -> bool:
    """"Use this answer" (``accept`` = "front" / "back") or a changed sleeve option (``accept`` None): ``recompose``
    in a thread — CPU only, so neither the media switch nor the routing is asked. Checked synchronously: a ready
    cut, a record with that job's answer (``NotReady``), no other hub-job flow of the piece (``Busy``).
    False when this piece's cut already runs."""
    if accept is not None and accept not in JOBS:
        raise ValueError(f"job must be one of {', '.join(JOBS)}")
    _ready_pattern(character_name, item_id)
    if accept is not None and not (usable_answers(character_name, item_id).get(accept) or {}).get("can_use"):
        raise NotReady(f"The {accept} job has no answer to use — redo it first")
    fn = run or recompose
    return _launch(character_name, item_id, lambda: fn(character_name, item_id, accept=accept), select=accept is not None)


def _launch(character_name: str, item_id: str, call, *, select: bool) -> bool:
    """Claim the piece (``piece_jobs`` "cut", ``Busy`` when another flow holds it), select texture "cut" when
    ``select``, and run ``call`` in a thread; False when this piece's cut already runs."""
    from app.core import piece_jobs
    key = (character_name, item_id)
    with _lock:
        if _running.get(key) == "running":
            return False
        held = piece_jobs.claim(character_name, item_id, "cut")
        if held:
            raise Busy(held)
        _running[key] = "running"
        _progress[key] = ""
    if select:
        try:
            select_cut(item_id)
        except Exception as e:  # noqa: BLE001 — the flow still runs; the user can switch the field by hand
            logger.warning("Cut texture %s %s: texture not switched to cut: %s", character_name, item_id, e)

    def work() -> None:
        outcome = "done"
        try:
            call()
        except Exception as e:  # noqa: BLE001 — shown in the dialog
            logger.warning("Cut texture %s %s: %s", character_name, item_id, e)
            outcome = str(e) or type(e).__name__
        with _lock:
            _running[key] = outcome
            _progress.pop(key, None)
        piece_jobs.release(character_name, item_id, "cut")

    threading.Thread(target=work, name=f"cut-texture-{item_id}", daemon=True).start()
    return True


# --- the Build's step (user test 2026-11-21) ------------------------------------------------------------------------
#
# Tilda's and Dario's shirts were draped by the Build and stayed on the projection: the texture from cut was made only
# by the dialog's button. A template top whose ``texture`` is "cut" is now finished by the character's Build
# (``figure_build``: the step "cut_texture"): the cut-only run, the back view when missing, the front and back image
# jobs, the gates, the atlas — and the Build's own assembly puts it on. The step starts in the background just before
# the piece's drape (``build_start``: the hub jobs run while the CPU drapes) and is joined in its place in the plan
# (``build_join``). It takes the piece's hub-job claim (``piece_jobs``) like the dialog: a dialog flow of the piece that
# runs is waited for and its record read, never a second submit.

#: The Build step's states (``build_state``).
BUILD_OFF, BUILD_DONE, BUILD_DUE, BUILD_COMPOSE, BUILD_FAILED = "off", "done", "due", "compose", "failed"
#: The Build step's labels (English; ``figure_build`` shows them as they are).
BUILD_LABEL = "Texture from cut · {name} (+{n} image jobs)"
BUILD_LABEL_ESTIMATE = "Texture from cut · {name} (+{n} image jobs, estimate — the pattern is cut first)"
BUILD_COMPOSE_LABEL = "Texture from cut · {name}: compose again (CPU, 0 hub jobs)"
#: The cost note's part of the cut texture (``figure_build.cost``).
BUILD_COST_NOTE = "+{n} image jobs for the cut texture"
#: How long the step waits for a cut / a flow of the piece another click started, at most.
BUILD_WAIT_S = 3 * 3600.0
BUILD_POLL_S = 2.0
#: The step's error when the piece stayed claimed by another flow for ``BUILD_WAIT_S``.
BUILD_BUSY = "The piece stayed busy with another job ({reason}) — Build again once it is done"

_build_runs: dict[tuple[str, str], dict] = {}


def _estimate_jobs(character_name: str, item_id: str) -> int:
    """The image jobs of a flow whose pattern is not cut yet: the back view when missing, the item upscale when the
    picture is small, the front and the back job (a top with a bodice always has a back panel)."""
    side = _item_side(item_id)
    view = 1 if back_view(character_name, item_id) is None else 0
    return view + (1 if 0 < side < MIN_ITEM_SIDE else 0) + len(JOBS)


def build_state(character_name: str, item_id: str, *, item: dict | None = None) -> dict:
    """What the Build has to do for the piece's texture from cut: ``{state, reason, jobs, estimate}`` —

    - ``off``: the piece does not want it (``texture`` not "cut", not a pattern kind, a strapless top, no parameters
      or no plain body — the drape step says those);
    - ``done``: a ready record of the current csig with its atlas, composed with the piece's sleeve option;
    - ``compose``: a ready record composed with the other sleeve option (``recompose``, CPU, 0 jobs);
    - ``failed``: the current cut failed, the item has no picture, or the current csig's record is "rejected" /
      "failed" — a cached failure: an automatic Build skips it, a manual one retries it (Run all: only the jobs that
      did not pass are rendered again, ``reused_jobs``); ``jobs`` what that retry spends;
    - ``due``: nothing made for the current csig yet (or the cut not made yet: ``estimate`` True, ``jobs`` from
      ``_estimate_jobs``).

    Read-only: no Blender, no hub job; never raises (a read error is ``off`` with the reason logged)."""
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    from app.models.inventory import get_item
    out = {"state": BUILD_OFF, "reason": "", "jobs": 0, "estimate": False}
    try:
        item = item if item is not None else get_item(item_id)
        params = gt.params_of(item) or {}
        if params.get("texture") != "cut":
            return out
        key = gtc.cut_key(character_name, item_id, item=item)
        if key["sig"] is None:
            if key["reason"] == gtc.WAITING_LOWER:
                return {**out, "state": BUILD_DUE, "reason": key["reason"],
                        "jobs": _estimate_jobs(character_name, item_id), "estimate": True}
            return {**out, "reason": key["reason"]}
        cut = gtc.state(character_name, item_id, key=key)
        if cut["state"] == "failed":
            return {**out, "state": BUILD_FAILED, "reason": cut["reason"]}
        if item_sha(item_id) is None:
            return {**out, "state": BUILD_FAILED, "reason": BLOCKED_PICTURE}
        if cut["state"] != "ready":
            return {**out, "state": BUILD_DUE, "reason": cut["reason"],
                    "jobs": _estimate_jobs(character_name, item_id), "estimate": True}
        islands = _islands_of(cut)
        sig = csig_for(character_name, item_id, cut["islands_sha"], islands)
        record = read_record(character_name, item_id, sig) if sig else {}
        plan = job_plan(character_name, item_id, islands, cut["islands_sha"])
        if record.get("state") == "ready" and atlas_path(character_name, item_id, sig).is_file():
            if str(record.get("sleeve_print") or "plain") == str(params.get("sleeve_print") or "plain"):
                return {**out, "state": BUILD_DONE}
            return {**out, "state": BUILD_COMPOSE}
        if record.get("state") in ("rejected", "failed"):
            return {**out, "state": BUILD_FAILED, "reason": str(record.get("reason") or record["state"]),
                    "jobs": int(plan["total"])}
        return {**out, "state": BUILD_DUE, "jobs": int(plan["total"])}
    except Exception as e:  # noqa: BLE001 — a plan never fails on it
        logger.warning("Cut texture %s %s: Build state not read: %s", character_name, item_id, e)
        return {**out, "reason": str(e) or type(e).__name__}


def _claim_for_build(character_name: str, item_id: str, deadline: float, poll_s: float) -> str:
    """Claim the piece for the Build's flow (``piece_jobs`` "cut" plus the ``_running`` mark the dialog reads): ""
    when claimed; else waits while another flow of the piece runs (a dialog's cut texture, a view) and gives the
    ``BUILD_BUSY`` reason when ``deadline`` passes. The caller re-reads the record after a wait."""
    import time
    from app.core import piece_jobs
    key = (character_name, item_id)
    while True:
        with _lock:
            if _running.get(key) != "running":
                held = piece_jobs.claim(character_name, item_id, "cut")
                if not held:
                    _running[key] = "running"
                    _progress[key] = ""
                    return ""
            else:
                held = piece_jobs.reason(character_name, item_id) or piece_jobs.REASONS["cut"]
        if time.monotonic() >= deadline:
            return BUILD_BUSY.format(reason=held)
        time.sleep(poll_s)


def run_for_build(character_name: str, item_id: str, *, explicit: bool, wait_s: float = BUILD_WAIT_S,
                  poll_s: float = BUILD_POLL_S) -> dict:
    """The Build step, synchronously: ``{"ok": bool, "reason", "state", "record"}``. A cached failure
    (``build_state`` "failed") is only retried by a manual Build (``explicit``). The media switch and the routing are
    asked first (their reasons are the step's error); the cut is made or waited for (``garment_template_cut.ensure``);
    the piece is claimed (``_claim_for_build`` — a flow another click started is waited for, then its record decides);
    then ``generate`` / ``recompose`` with ``apply_after`` False (the Build assembles). Never raises."""
    import time
    from app.core import garment_template_cut as gtc
    from app.core import piece_jobs
    from app.imagegen import routing as _routing
    from app.imagegen.base import media_generation_enabled
    deadline = time.monotonic() + wait_s
    st = build_state(character_name, item_id)
    if st["state"] in (BUILD_OFF, BUILD_DONE):
        return {"ok": True, "reason": st["reason"], "state": st["state"], "record": {}}
    if st["state"] == BUILD_FAILED and not explicit:
        return {"ok": False, "reason": st["reason"], "state": st["state"], "record": {}}
    if st["state"] != BUILD_COMPOSE:
        if not media_generation_enabled():
            return {"ok": False, "reason": MEDIA_OFF, "state": BUILD_FAILED, "record": {}}
        if not _routing.chain_for(CUT_OCCASION):
            return {"ok": False, "reason": BLOCKED_ROUTING, "state": BUILD_FAILED, "record": {}}
    _set_build_step(character_name, item_id, "cut")
    cut = gtc.ensure(character_name, item_id, timeout_s=max(1.0, deadline - time.monotonic()))
    if cut["state"] != "ready":
        return {"ok": False, "reason": str(cut.get("reason") or gtc.NOT_CUT), "state": BUILD_FAILED, "record": {}}
    busy = _claim_for_build(character_name, item_id, deadline, poll_s)
    if busy:
        return {"ok": False, "reason": busy, "state": BUILD_FAILED, "record": {}}
    key = (character_name, item_id)
    outcome = "done"
    try:
        st = build_state(character_name, item_id)      # a flow that ran meanwhile may have made it
        if st["state"] in (BUILD_OFF, BUILD_DONE):
            return {"ok": True, "reason": "", "state": st["state"], "record": {}}
        if st["state"] == BUILD_FAILED and not explicit:
            return {"ok": False, "reason": st["reason"], "state": st["state"], "record": {}}
        if st["state"] == BUILD_COMPOSE:
            record = recompose(character_name, item_id, apply_after=False)
        else:
            record = generate(character_name, item_id, apply_after=False)
        ok = record.get("state") == "ready"
        if not ok:
            outcome = str(record.get("reason") or record.get("state") or "failed")
        return {"ok": ok, "reason": "" if ok else outcome, "state": BUILD_DONE if ok else BUILD_FAILED,
                "record": record}
    except Exception as e:  # noqa: BLE001 — the step's error
        outcome = _failure_reason(e)
        logger.warning("Cut texture %s %s (Build): %s", character_name, item_id, outcome)
        return {"ok": False, "reason": outcome, "state": BUILD_FAILED, "record": {}}
    finally:
        with _lock:
            _running[key] = outcome
            _progress.pop(key, None)
        piece_jobs.release(character_name, item_id, "cut")


def _set_build_step(character_name: str, item_id: str, step: str) -> None:
    with _lock:
        entry = _build_runs.get((character_name, item_id))
        if entry is not None:
            entry["step"] = step


def build_start(character_name: str, item_id: str, *, explicit: bool) -> bool:
    """Start the Build step in the background (before the piece's drape — the hub jobs run while the CPU drapes):
    True when a thread started, False when one of the piece already runs (it is reused, never a second flow)."""
    key = (character_name, item_id)
    with _lock:
        entry = _build_runs.get(key)
        if entry is not None and entry["thread"].is_alive():
            return False
        entry = {"result": None, "step": "", "explicit": explicit}

        def work() -> None:
            res = run_for_build(character_name, item_id, explicit=explicit)
            with _lock:
                entry["result"] = res
        entry["thread"] = threading.Thread(target=work, name=f"cut-texture-build-{item_id}", daemon=True)
        _build_runs[key] = entry
    entry["thread"].start()
    return True


def build_join(character_name: str, item_id: str, *, explicit: bool, timeout_s: float = BUILD_WAIT_S) -> dict:
    """The Build step in its place in the plan: joins the background run ``build_start`` began (or runs it now when
    none was started) and returns its result (``run_for_build``)."""
    key = (character_name, item_id)
    with _lock:
        entry = _build_runs.get(key)
    if entry is None:
        build_start(character_name, item_id, explicit=explicit)
        with _lock:
            entry = _build_runs.get(key)
    entry["thread"].join(timeout_s)
    with _lock:
        if entry["thread"].is_alive():
            return {"ok": False, "reason": "The texture from cut is still running — Build again once it is done",
                    "state": BUILD_FAILED, "record": {}}
        if _build_runs.get(key) is entry:
            _build_runs.pop(key, None)
        res = entry["result"]
    return res or {"ok": False, "reason": "The texture from cut ended without a result", "state": BUILD_FAILED,
                   "record": {}}


def build_running(character_name: str, item_id: str) -> bool:
    """Whether the Build's flow of the piece runs now."""
    with _lock:
        entry = _build_runs.get((character_name, item_id))
        return bool(entry is not None and entry["thread"].is_alive())


def status(character_name: str, item_id: str) -> dict:
    """``{running, step, error, csig, record}``: ``csig`` the piece's current key (None without a ready cut),
    ``record`` that key's record ({} when none was made yet), ``step`` where a running flow is."""
    with _lock:
        state = _running.get((character_name, item_id), "")
        step = _progress.get((character_name, item_id), "") if state == "running" else ""
    sig = current_csig(character_name, item_id)
    return {"running": state == "running", "step": step,
            "error": state if state not in ("", "running", "done") else "",
            "csig": sig, "record": read_record(character_name, item_id, sig) if sig else {}}


# --- the dialog (plan Task 10, reworked 2026-11-20) ---------------------------------------------------------------
#
# The template dialog's Texture tab reads ``dialog_state``: the flow's status, whether its button may start and, when
# not, the ONE reason that is true now and what fixes it (English; the React client puts it through ``t()``). User
# finding 2026-11-20 (Dario): "Build the template first" came while the Build was draping the piece and after a new
# view had only made the dialog's state stale — every reason below is now said only in the state it describes.
# Cut-first (2026-11-21): the Pattern step is the CUT (``garment_template_cut``, seconds on the CPU), never the drape —
# its reasons are ``garment_template_cut``'s (``CUTTING``, ``NOT_CUT``, ``CUT_FAILED``, ``CUT_LEFT``, ``NO_PATTERN``
# and the key's own: no parameters, no plain body); a Build draping the piece keeps nothing from starting.

#: The button's other disabled reasons (``dialog_state``).
BLOCKED_MEDIA = "Media generation is off"
BLOCKED_ROUTING = ("Routing chain for 'Garment — texture from cut' is empty — set it in /admin/settings → Media "
                   "Generation → Routing")
BLOCKED_PICTURE = "The item has no picture"
#: The record files the dialog shows (``cut_file``): per job its template, its Picture 2 and its answer, and the atlas.
CUT_FILES = ("template_front", "item", "raw_front", "template_back", "back_ref", "raw_back", "atlas")


def _item_side(item_id: str) -> int:
    """The item picture's long side in px (header only), 0 without a picture."""
    try:
        with Image.open(_item_path(item_id)) as im:
            return max(im.size)
    except (NotReady, OSError):
        return 0


def dialog_state(character_name: str, item_id: str) -> dict:
    """``status`` plus:

    - ``can_generate`` / ``blocked_reason`` — "" when the button may start; else the ONE true reason, in the order
      the user has to fix them: the cut (``current_pattern``'s reason), ``BLOCKED_PICTURE``, ``BLOCKED_MEDIA``,
      ``BLOCKED_ROUTING``, another hub-job flow of the piece (``piece_jobs.reason``). A running cut-texture flow is
      no "blocked" reason: the button says it runs. The drape is never asked: the flow may run while it drapes;
    - ``pattern_reason`` / ``cutting`` / ``cut_at`` / ``cut_wall_s`` — the Pattern step's own line (only the cut's
      reason, never the media switch's or the routing's; ``cutting`` while ``garment_template_cut`` cuts it);
    - ``current`` — a ready record exists for the current csig (Run all says "Everything is current");
    - ``plan`` — ``job_plan`` (the button's job count, the back view and the upscale included);
    - ``texture`` — the piece's ``texture`` param; ``applied`` — the figure shows the cut atlas now
      (``garment_template.cut_info``), with ``applied_reason`` when not;
    - ``upscale``, ``islands_sha``, ``files`` (which of ``CUT_FILES`` exist for the current csig);
    - ``answers`` — ``usable_answers`` (the "Use this answer" buttons: 0 image jobs, CPU); ``can_use`` False for
      every job while the button would be refused (a flow runs, another hub-job flow of the piece, no cut);
    - ``sleeve_print`` — the piece's sleeve option, ``has_sleeves`` whether the pattern has sleeves to choose for,
      ``option_stale`` whether the ready atlas was composed with the other option (``cut_info`` "option")."""
    from app.core import garment_template as gt
    from app.core import piece_jobs
    from app.imagegen import routing as _routing
    from app.imagegen.base import media_generation_enabled
    from app.models.inventory import get_item
    out = status(character_name, item_id)
    pattern = current_pattern(character_name, item_id)
    drape = current_drape(character_name, item_id)
    cut_ready = pattern["state"] == "ready"
    islands = _islands_of(pattern) if cut_ready else {}
    side = _item_side(item_id)
    pattern_reason = "" if cut_ready else str(pattern.get("reason") or "")
    blocked = pattern_reason
    if not blocked and not side:
        blocked = BLOCKED_PICTURE
    if not blocked and not media_generation_enabled():
        blocked = BLOCKED_MEDIA
    if not blocked and not _routing.chain_for(CUT_OCCASION):
        blocked = BLOCKED_ROUTING
    held = piece_jobs.holder(character_name, item_id)
    if not blocked and held and held != "cut":
        blocked = piece_jobs.reason(character_name, item_id)
    sig = out.get("csig")
    stem = _stem(character_name, item_id, sig) if sig else None
    item = get_item(item_id)
    params = gt.params_of(item) or {}
    info = gt.cut_info(character_name, item_id, drape.get("record"), item=item) if drape["state"] == "ready" else {}
    record = out.get("record") or {}
    out.update({"can_generate": not blocked and not out["running"], "blocked_reason": blocked,
                # the Pattern step's own line: "" = cut with islands; ``cutting`` = the cut-only run cuts it now
                "pattern_reason": pattern_reason, "cutting": pattern["state"] == "cutting",
                "cut_at": str(pattern.get("cut_at") or ""), "cut_wall_s": pattern.get("wall_s"),
                "current": record.get("state") == "ready"
                and str(record.get("sleeve_print") or "plain") == str(params.get("sleeve_print") or "plain"),
                "plan": job_plan(character_name, item_id, islands, str(pattern.get("islands_sha") or ""))
                if cut_ready else None,
                "texture": params.get("texture") or "projection",
                "applied": info.get("texture") == "cut",
                "applied_state": info.get("cut_state") or "",
                "upscale": 0 < side < MIN_ITEM_SIDE,
                "has_back": has_back(islands),
                "islands_sha": str(pattern.get("islands_sha") or "") if cut_ready else "",
                "files": {k: bool(stem and _file(stem, f".{k}.png").is_file()) for k in CUT_FILES}})
    use_off = out["running"] or bool(pattern_reason) or bool(held and held != "cut")
    answers = usable_answers(character_name, item_id, sig) if sig else {}
    for entry in answers.values():
        entry["can_use"] = bool(entry["can_use"] and not use_off)
    sleeve_print = str(params.get("sleeve_print") or "plain")
    out.update({"answers": answers, "sleeve_print": sleeve_print,
                "has_sleeves": any(part_of(str(i["name"])) in SLEEVE_PARTS for i in islands.get("islands", [])),
                "option_stale": record.get("state") == "ready"
                and str(record.get("sleeve_print") or "plain") != sleeve_print})
    return out


def cut_file(character_name: str, item_id: str, kind: str, sig: str | None = None) -> Path | None:
    """One of ``CUT_FILES`` of (item, ``sig``) — ``sig`` the csig a URL names (a 12-hex key), else the piece's current
    one; None when it does not exist (or ``kind`` / ``sig`` is not one)."""
    if kind not in CUT_FILES:
        return None
    if sig is None or not _CSIG_RE.fullmatch(str(sig)):
        sig = current_csig(character_name, item_id)
    if not sig:
        return None
    path = _file(_stem(character_name, item_id, sig), f".{kind}.png")
    return path if path.is_file() else None


def pattern_sheet_file(character_name: str, item_id: str) -> Path | None:
    """The DEBUG pattern sheet (``render_pattern_sheet``) of the piece's CURRENT cut — written by the cut-only run
    beside its islands (``templates/cut/{item}_{cutsig}.pattern.png``), rendered here when missing. None while the
    piece is not cut (the dialog's URL carries the islands sha, so a new cut is a new URL)."""
    from app.core import garment_template_cut as gtc
    pattern = current_pattern(character_name, item_id)
    path, sig = pattern.get("islands_path"), pattern.get("cut_sig")
    if pattern["state"] != "ready" or path is None or not sig:
        return None
    sheet = gtc.sheet_file(character_name, item_id, sig)
    if not sheet.is_file():
        islands = json.loads(Path(path).read_text(encoding="utf-8"))
        _write_bytes(sheet, _png(render_pattern_sheet(islands)))
    return sheet
