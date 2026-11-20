"""Texture from cut: a garment template's pattern islands, filled from the item image by a routed img2img backend.

Plan: ``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md`` (Tasks 5–10).

This part is the RENDER of a piece's islands, pure numpy + PIL on the drape's ``islands.json`` payload (written by
``app/blender/scripts/uv_pattern.islands_payload``; this module never imports the Blender scripts):

- ``rasterise_islands`` / ``island_mask`` — the island label raster and mask the gate measures against;
- ``render_template`` — the CLEAN model template (neutral grey islands, a thin outline drawn inside the mask, a white
  background, square, no text) that goes to the model as the first image;
- ``render_pattern_sheet`` — the user's DEBUG view of the same islands (pastel fills, part names, sizes in cm, grain
  arrows, seam letters, the sleeve cap height, a px/cm footer). It is never sent to a model.

The PROMPT (Task 6) is the shipped Jinja2 file ``shared/templates/image/garment_cut_texture.md`` — its own tiny
``SandboxedEnvironment`` + ``StrictUndefined`` loader here, deliberately not world-overridable (``/admin/templates``
stays LLM-only). ``PROMPT_SHA`` (md5 of the file text) enters the cut atlas key. The render runs on the occasion
``CUT_OCCASION`` with the use case ``CUT_USE_CASE`` (empty style/negative/instruction: the prompt is the whole subject).

The JOB (Task 8): ``start`` checks synchronously (media switch, a configured chain, a ready drape with islands, an
item picture) and runs ``generate`` in a thread — ONE attempt per click, no retry, no auto-trigger from Build. A
cut atlas is keyed by ``csig`` (the drape's islands sha, the item picture sha, ``PROMPT_SHA``,
``cut_texture_post.POST_VERSION``), never by ``tsig``; its record lives under ``cut_dir`` (``templates/cut/``) with
the state "ready" / "rejected" / "failed". Every render goes ``routing.run_routed`` -> ``run_on_backend`` ->
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
PROMPT_TEXT = PROMPT_FILE.read_text(encoding="utf-8")
#: md5 of the shipped prompt file text — part of the cut atlas key, so a reworded prompt makes an atlas stale.
PROMPT_SHA = hashlib.md5(PROMPT_TEXT.encode("utf-8")).hexdigest()

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


# ---------------------------------------------------------------------------------------------------- prompt

#: English panel name per part, in pattern order (the order the prompt lists the pieces in).
PROMPT_PIECE_NAMES = {
    "front": "front panel", "back": "back panel", "sleeve_l": "left sleeve", "sleeve_r": "right sleeve",
    "band": "neckband", "collar": "collar", "placket": "placket", "cuff_l": "left cuff", "cuff_r": "right cuff",
}

_PROMPT_ENV = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined, trim_blocks=True,
                                   lstrip_blocks=True, keep_trailing_newline=False)


def prompt_template() -> Template:
    """The shipped prompt file as a StrictUndefined template (a missing variable raises)."""
    return _PROMPT_ENV.from_string(PROMPT_TEXT)


def render_prompt(*, piece: str, pieces: list[str]) -> str:
    """The cut-texture prompt for ``piece`` (e.g. "T-shirt") with its pattern ``pieces`` (English panel names).
    Ordinal wording ("the first image") — the central handoff rewrites it per backend."""
    return prompt_template().render(piece=piece, pieces=list(pieces)).strip()


def _split_name(name: str) -> tuple[str, int]:
    base, _, n = str(name).rpartition("_")
    if base and n.isdigit() and base in PROMPT_PIECE_NAMES:
        return base, int(n)
    return str(name), 1


def prompt_pieces(islands: dict) -> list[str]:
    """The English panel names of the payload's islands in pattern order; a split part keeps its number
    (``front_2`` -> "front panel 2"); an unknown part name is spoken plainly after the known ones."""
    order = list(PROMPT_PIECE_NAMES)
    keyed = []
    for isl in islands.get("islands", []):
        base, n = _split_name(isl["name"])
        rank = order.index(base) if base in PROMPT_PIECE_NAMES else len(order)
        word = PROMPT_PIECE_NAMES.get(base, base.replace("_", " "))
        keyed.append(((rank, base, n), word if n == 1 else f"{word} {n}"))
    return [w for _, w in sorted(keyed)]


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


# ---------------------------------------------------------------------------------------------------- the job (Task 8)
#
# One attempt per click (``start`` -> thread -> ``generate``), never retried, never started by Build. Files under
# ``cut_dir`` per (item, csig): ``{item}_{csig}.json`` (the record), ``.template.png`` + ``.item.png`` (the two
# references, written BEFORE the routed render: ``reference_images`` values are file paths), ``.raw.png`` (the model's
# answer) and ``.atlas.png`` (the accepted atlas). The record is NOT a gallery image: the Improvements type
# ``fallback_rerender`` lists only character/location gallery metas, so ``route_meta`` here is information only.

#: The item image's long side below which it goes through the routed ``upscale`` occasion first (tiny 177-413 px item
#: pictures gave the wrong logo in the user's test jobs).
MIN_ITEM_SIDE = 1024
#: The reason of a job the media master switch stopped.
MEDIA_OFF = "Media generation is off — switch it on in /admin/settings → Media Generation"

_running: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


class NotReady(ValueError):
    """The piece has no ready drape with pattern islands yet (a 400 for the route)."""


def csig(islands_sha: str, item_sha: str) -> str:
    """The cut atlas key: the drape's islands, the item image, the prompt file and the post-processing version —
    NOT ``tsig`` (it carries the piece-only views' sha, which the cut atlas does not depend on)."""
    raw = "|".join([str(islands_sha), str(item_sha), PROMPT_SHA, str(cut_texture_post.POST_VERSION)])
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
    (``garment_template.piece_progress``): ``{state, reason, tsig, islands_path, islands_sha}``; ``islands_path``
    None when the ready drape carries no pattern islands (a kind still on the grid UV)."""
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
    islands = (drape.get("record") or {}).get("islands") or {}
    path = gt.templates_dir(character_name) / islands["file"] if islands.get("file") else None
    return {"state": drape["state"], "reason": drape.get("reason") or "", "tsig": drape.get("tsig"),
            "islands_path": path if path is not None and path.is_file() else None,
            "islands_sha": str(islands.get("sha256") or "")}


def _ready_drape(character_name: str, item_id: str) -> dict:
    drape = current_drape(character_name, item_id)
    if drape["state"] != "ready":
        raise NotReady(drape.get("reason") or "The piece has no ready drape yet — build it first")
    if drape.get("islands_path") is None or not drape.get("islands_sha"):
        raise NotReady("The piece's drape has no pattern islands — re-drape it (tops only for now)")
    return drape


def _item_path(item_id: str) -> Path:
    from app.models.inventory import get_item_image_path
    path = get_item_image_path(item_id)
    if not path or not Path(path).is_file():
        raise NotReady(f"The item {item_id!r} has no picture")
    return Path(path)


#: sha256 of an item picture per (path, mtime_ns, size): ``item_sha`` is read by every assembly state check of a piece
#: whose texture is "cut", so an unchanged picture is hashed once.
_sha_cache: dict[tuple[str, int, int], str] = {}


def _item_sha(item_id: str) -> str:
    path = _item_path(item_id)
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    sha = _sha_cache.get(key)
    if sha is None:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(_sha_cache) > 512:
            _sha_cache.clear()
        _sha_cache[key] = sha
    return sha


def item_sha(item_id: str) -> str | None:
    """sha256 of the item picture, None when the item has none."""
    try:
        return _item_sha(item_id)
    except (NotReady, OSError):
        return None


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


def current_csig(character_name: str, item_id: str) -> str | None:
    """The csig the piece would have now (ready drape with islands + item picture), else None."""
    try:
        drape = _ready_drape(character_name, item_id)
        return csig(drape["islands_sha"], _item_sha(item_id))
    except NotReady:
        return None


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


def piece_name(item_id: str) -> str:
    """The English name of the piece the prompt speaks of, from the template kind and its sleeve length."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    params = gt.params_of(get_item(item_id)) or {}
    kind = str(params.get("kind") or "garment")
    if kind == "top":
        return {"none": "sleeveless top", "cap": "T-shirt", "short": "T-shirt", "elbow": "elbow-sleeve shirt",
                "long": "long-sleeve shirt"}.get(str(params.get("sleeves") or "short"), "top")
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


def _routed_render(item_id: str, prompt: str, template_png: Path, item_png: Path, seed: int):
    """ONE routed img2img render of the template + item -> ``(answer bytes, backend, route)``."""
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
                                       "input_reference_image_2": str(item_png)}}
        log_meta = {"agent_name": f"Cut texture {item_id}", "original_prompt": prompt, "auto_enhance": False,
                    "compose": composed.meta}

        def _op(bb):
            # through the backend's GPU channel: never two generations on one backend at once
            return svc.run_on_backend_channel(
                bb, lambda: bb.generate(composed.prompt, composed.negative, params, log_meta=log_meta),
                task_type="garment_cut_texture", agent_name="system", label=f"Cut texture: {item_id}")
        return svc.run_on_backend(b, op=_op)

    (images, used), route = _routing.run_routed(CUT_OCCASION, _render, has_ref=True, pool=svc.pool)
    if not isinstance(images, (list, tuple)) or not images or not isinstance(images[0], (bytes, bytearray)):
        raise RuntimeError("the cut-texture render delivered no image")
    return bytes(images[0]), used, route


def generate(character_name: str, item_id: str) -> dict:
    """ONE attempt: template + item picture -> routed render -> post-processing -> the record (``state`` "ready",
    "rejected" or "failed"). Raises ``NotReady`` before anything is written when the piece has no ready drape with
    islands or no picture; every later failure is recorded as "failed" and returned."""
    from app.imagegen.routing import route_meta
    drape = _ready_drape(character_name, item_id)
    item_sha = _item_sha(item_id)
    sig = csig(drape["islands_sha"], item_sha)
    islands = json.loads(Path(drape["islands_path"]).read_text(encoding="utf-8"))
    px_per_cm = float(islands.get("px_per_cm") or 0.0)
    stem = _stem(character_name, item_id, sig)
    raw_png, atlas_png = _file(stem, ".raw.png"), _file(stem, ".atlas.png")
    for stale in (raw_png, atlas_png):
        stale.unlink(missing_ok=True)       # this attempt's record never sits next to another attempt's files
    record: dict = {"csig": sig, "islands_sha": drape["islands_sha"], "tsig": drape.get("tsig"), "state": "failed",
                    "reason": "", "metrics": {}, "routing": {}, "px_per_cm": px_per_cm, "item_px": None,
                    "upscale": None, "prompt_sha": PROMPT_SHA, "item_sha": item_sha}
    try:
        size = int(islands.get("atlas_px") or 2048)
        template_png, item_png = _file(stem, ".template.png"), _file(stem, ".item.png")
        _write_bytes(template_png, _png(render_template(islands, size)))
        data, info = item_source(item_id)
        record.update(info)
        _write_bytes(item_png, data)
        prompt = render_prompt(piece=piece_name(item_id), pieces=prompt_pieces(islands))
        answer, used, route = _routed_render(item_id, prompt, template_png, item_png, int(sig[:8], 16) % 2 ** 31)
        record.update({"backend": getattr(used, "name", ""), "routing": route_meta(route),
                       "upsampler_on": _upsampler_on(used)})
        _write_bytes(raw_png, answer)
        record.update(_post(answer, islands, size, px_per_cm, item_id))
    except Exception as e:  # noqa: BLE001 — a job's failure is the record, shown in the dialog
        logger.warning("Cut texture %s %s failed: %s", character_name, item_id, e)
        record.update({"state": "failed", "reason": _failure_reason(e)})
        atlas = None
    else:
        atlas = record.pop("_atlas", None)
    from app.core.timeutils import utc_now_iso
    record["created_at"] = utc_now_iso()
    if record["state"] == "ready" and atlas is not None:
        _write_bytes(atlas_png, _png(Image.fromarray(atlas, "RGB")))
    _write_record(_file(stem, ".json"), record)
    if record["state"] == "ready":
        from app.core import figure
        figure.invalidate()
    return record


def _post(answer: bytes, islands: dict, size: int, px_per_cm: float, item_id: str) -> dict:
    """Task 7 on the answer: register, gate, cut + bleed, colour match, seam continuity. ``{"state", "reason",
    "metrics", "_atlas"}`` (``_atlas`` the uint8 image on ``ready``)."""
    post = cut_texture_post
    labels = rasterise_islands(islands, size)
    mask = labels > 0
    with Image.open(io.BytesIO(answer)) as im:
        im.load()
        reg, reg_info = post.resample_register(im, mask)
    ok, met, reason = post.gate(reg, mask, labels, px_per_cm)
    metrics = {"iou": met["iou"], "coverage": met["coverage"], "island_coverage": met["island_coverage"],
               "spill": met["spill"], "registration": reg_info, "islands": met["islands"]}
    if not ok:
        metrics.update({"de_before": None, "de_after": None, "clamped": None, "seam_de": None})
        return {"state": "rejected", "reason": reason, "metrics": metrics}
    cut = post.cut_and_bleed(reg, mask, max(1, int(round(post.BLEED_CM * px_per_cm))))
    with Image.open(_item_path(item_id)) as it:
        item_rgba = np.asarray(it.convert("RGBA"))
    grown = ~np.all(cut == 255, axis=-1) | mask
    matched, cm = post.colour_match(cut, grown, item_rgba, matte=_item_matte())
    seam = post.seam_continuity(matched, islands.get("seams") or [])
    metrics.update({"de_before": cm.get("de_before"), "de_after": cm.get("de_after"),
                    "clamped": cm.get("clamped"), "seam_de": seam.get("median"), "colour": cm, "seams": seam})
    return {"state": "ready", "reason": "", "metrics": metrics, "_atlas": matched}


def start(character_name: str, item_id: str, *, run=None) -> bool:
    """Check SYNCHRONOUSLY (so the HTTP answer carries the reason) and start ``generate`` in a thread; False when
    this piece's job already runs. Raises ``MediaGenerationDisabled`` (media off), ``NoRouteError`` (empty chain)
    or ``NotReady`` (no ready drape with islands, no picture) before any thread or file exists."""
    from app.imagegen import routing as _routing
    from app.imagegen.base import MediaGenerationDisabled, media_generation_enabled
    if not media_generation_enabled():
        raise MediaGenerationDisabled(MEDIA_OFF)
    if not _routing.chain_for(CUT_OCCASION):
        raise _routing.NoRouteError(CUT_OCCASION, [])
    _ready_drape(character_name, item_id)
    _item_path(item_id)
    key = (character_name, item_id)
    with _lock:
        if _running.get(key) == "running":
            return False
        _running[key] = "running"
    fn = run or generate

    def work() -> None:
        outcome = "done"
        try:
            fn(character_name, item_id)
        except Exception as e:  # noqa: BLE001 — shown in the dialog
            logger.warning("Cut texture %s %s: %s", character_name, item_id, e)
            outcome = str(e) or type(e).__name__
        with _lock:
            _running[key] = outcome

    threading.Thread(target=work, name=f"cut-texture-{item_id}", daemon=True).start()
    return True


def status(character_name: str, item_id: str) -> dict:
    """``{running, error, csig, record}``: ``csig`` the piece's current key (None without a ready drape with
    islands), ``record`` that key's record ({} when none was made yet)."""
    with _lock:
        state = _running.get((character_name, item_id), "")
    sig = current_csig(character_name, item_id)
    return {"running": state == "running", "error": state if state not in ("", "running", "done") else "",
            "csig": sig, "record": read_record(character_name, item_id, sig) if sig else {}}
