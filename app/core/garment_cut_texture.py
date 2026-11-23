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

The PROMPT is one of three shipped SECTIONED templates (``PROMPT_FILES``: front plain, front decorated, back; one
section per edit-prompt dialect, ``app/imagegen/edit_prompt.py``, ``docs/edit-prompts.md`` §6) — deliberately not
world-overridable (``/admin/templates`` stays LLM-only). Code picks the variant (``is_decorated``, the side); the
backend the render lands on picks the dialect, inside the routed render, so attempt 2 on another backend gets its own
wording. ``PROMPT_SHA`` (md5 of the three file texts) enters the cut atlas key and the record (``prompt_sha``), so a
reworded section makes an old atlas stale. The render runs on the occasion ``CUT_OCCASION`` with the use case
``CUT_USE_CASE`` (empty style/negative/instruction: the prompt is the whole subject).

The JOB (Task 8): ``start`` checks synchronously (media switch, a configured chain, a ready CUT with islands
(``garment_template_cut.state``), an item picture) and runs ``generate`` in a thread — per job up to ``CUT_ATTEMPTS``
renders: a gate rejection of attempt 1 renders attempt 2 on the routing chain's SECOND entry
(``routing.gate_attempts``); a failure (busy, media off, no route, a dead backend) never does. It never waits for a drape and may run while the Build drapes the piece. The character's Build runs the same
flow as its step "cut_texture" for a top whose ``texture`` is "cut" (``build_state`` / ``build_start`` /
``build_join``, user test 2026-11-21) — no click on the dialog's button is needed. A cut
atlas is keyed by ``csig`` (the cut's islands sha, the item picture sha, ``PROMPT_SHA``,
``cut_texture_post.POST_VERSION``), never by ``tsig``; its record lives under ``cut_dir`` (``templates/cut/``) with
the state "ready" / "rejected" / "failed". The assembly maps it onto a drape whose islands have the same sha — every
drape of the same cut (``garment_template.cut_info``). Every render goes ``routing.run_routed`` -> ``run_on_backend`` ->
``run_on_backend_channel``; the central handoff's ``edit_prompt.normalise`` finds the section already in its dialect.

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
from PIL import Image, ImageDraw, ImageFont

from app.core import cut_texture_post
from app.core.log import get_logger

logger = get_logger("garment_cut_texture")

#: The image occasion and the style use case of a cut-texture render (``app/imagegen/occasions.py``,
#: ``config._DEFAULT_IMAGE_USE_CASES``).
CUT_OCCASION = "garment_cut_texture"
CUT_USE_CASE = "garment_cut_texture"

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "shared" / "templates" / "image"
#: The three prompt variants, each a sectioned edit-prompt template (``edit_prompt.from_template``): the front job of a
#: plain item, the front job of a decorated one (``is_decorated``), the back job (the back panel alone).
PROMPT_FILES = {"front_plain": _PROMPT_DIR / "garment_cut_texture_front_plain.md",
                "front_decorated": _PROMPT_DIR / "garment_cut_texture_front_decorated.md",
                "back": _PROMPT_DIR / "garment_cut_texture_back.md"}
#: Group A (2026-11-21): the close-fitting kinds' own three variants (``FITTED_KINDS``: briefs, bra, gloves, tights,
#: trousers) — their main pieces come in pairs (two leg panels, two cups, two backs of the hand) and their small pieces
#: are bands, so they are named per piece; a top's tested files and its ``PROMPT_SHA`` stay byte-identical.
FITTED_PROMPT_FILES = {"front_plain": _PROMPT_DIR / "garment_cut_texture_fitted_front_plain.md",
                       "front_decorated": _PROMPT_DIR / "garment_cut_texture_fitted_front_decorated.md",
                       "back": _PROMPT_DIR / "garment_cut_texture_fitted_back.md"}
#: The prompt family of each pattern kind (``prompt_family``) -> its variant files.
PROMPT_SETS = {"top": PROMPT_FILES, "fitted": FITTED_PROMPT_FILES}
PROMPT_TEXTS = {family: {variant: path.read_text(encoding="utf-8") for variant, path in files.items()}
                for family, files in PROMPT_SETS.items()}
#: md5 of a family's three shipped files (every section) — part of the cut atlas key, so a reworded section makes an
#: atlas of that family stale (and only of that family).
PROMPT_SHAS = {family: hashlib.md5("\0".join(texts[v] for v in PROMPT_SETS[family]).encode("utf-8")).hexdigest()
               for family, texts in PROMPT_TEXTS.items()}
#: A top's prompt sha (unchanged by group A: a top's atlases keep their csig).
PROMPT_SHA = PROMPT_SHAS["top"]
#: Renders per job: a gate rejection of attempt 1 renders attempt 2 on the chain's second entry (docs/edit-prompts.md
#: §7); a single-entry chain renders it on the same backend with ``ATTEMPT_SEED_STEP`` added to the seed.
CUT_ATTEMPTS = 2
ATTEMPT_SEED_STEP = 1000

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
    # step 3b (plan group B): a skirt's panels, an open jacket's fronts
    "skirt_front": "Skirt front", "skirt_back": "Skirt back", "left_front": "Left front", "right_front": "Right front",
}


# ---------------------------------------------------------------------------------------------------- raster


def island_ids(islands: dict) -> dict[str, int]:
    """Label id per island name: 1 + the index of the name in sorted order (0 = background)."""
    names = sorted(str(i["name"]) for i in islands.get("islands", []))
    if len(names) > 255:
        raise ValueError("garment_cut_texture: more than 255 islands do not fit a uint8 label raster")
    return {n: k + 1 for k, n in enumerate(names)}


def prompt_family(kind) -> str:
    """The prompt family of a piece's prompt kind (``item_kind``): "fitted" for the close-fitting kinds
    (``garment_template.FITTED_KINDS``, group A) and the panel kinds with held trims (``HELD_TRIM_KINDS``, group B: a
    skirt, ``item_kind`` "strapless" — their main pieces are named by where they lie, their small pieces kept plain);
    "top" for every other, a piece without template parameters ("") included — its csig, seed and stem stay as
    before group B."""
    from app.core import garment_template as gt
    k = str(kind or "")
    return "fitted" if k in gt.FITTED_KINDS or k in HELD_TRIM_KINDS else "top"


def prompt_sha_of(kind) -> str:
    """The prompt sha a piece of ``kind`` is keyed by (``PROMPT_SHAS`` of its ``prompt_family``)."""
    return PROMPT_SHAS[prompt_family(kind)]


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

#: English panel name per part (``_split_name`` knows a split part ``front_2`` by these bases).
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
    # step 3b (plan group B)
    "skirt_front": "front skirt panel", "skirt_back": "back skirt panel", "left_front": "left front panel",
    "right_front": "right front panel",
}


#: Prompt test 2026-11-21 — the item picture's detail density (``cut_texture_post.picture_reference``) above which the
#: FRONT job gets the decorated prompt (the print / embroidery is painted onto the front panel): Dario's embroidered
#: shirt 0.142, Kai's plain T-shirt 0.013, Tilda's plain shirt 0.076. Code decides, never the model.
DECORATED_DETAIL = 0.10


def decor_detail(detail: dict, params: dict | None):
    """The detail ``is_decorated`` reads: the item picture's (``detail["front"]``); for a sheer piece (``params``, the
    item's template params) the picture's WITHOUT the body seen through the cloth (``detail["front_cloth"]``,
    ``cut_texture_post.BODY_SEEN``; the whole picture's when nothing is left — a skin-toned sheer piece) — the legs'
    outlines through a sheer skirt are no decoration. Only for sheer: on an opaque light linen the cloth itself is
    skin-coloured (Dario's Worn Linen Shirt 0.277 would read 0.0)."""
    detail = detail or {}
    if str((params or {}).get("fabric") or "") == "sheer" and detail.get("front_cloth") is not None:
        return detail["front_cloth"]
    return detail.get("front")


def is_decorated(detail_front) -> bool:
    """Whether the item picture carries a print / embroidery worth the decorated front prompt (``DECORATED_DETAIL``)."""
    try:
        return float(detail_front) > DECORATED_DETAIL
    except (TypeError, ValueError):
        return False


#: Live E2E 2026-11-21 — the BACK view's detail density (the same ``cut_texture_post.picture_reference`` measure as
#: ``DECORATED_DETAIL``, on the accepted back piece-only view, its alpha the cut-out) at or below which the back is
#: PLAIN: no back hub job — the back panel gets the front panel's fabric patch, like the sleeves and the neckband
#: (``fill_plain_back``, 0 image jobs). P-H3 invented a collar and a button placket on Dario's plain back and strong
#: fold shading plus a colour fringe on Tilda's; neither is in the back view.
#: Derived like the front threshold, from the measured pictures (``DETAIL_SIDE`` 128). The back views are model renders
#: with strong fold shading, so a plain back reads higher than a plain item photo: the plain backs of the cut tops
#: Kai 0.0175, Tilda 0.0536, Dario 0.158 (his dark green shirt's vertical drape folds are every edge pixel — the box
#: pleat and the yoke are not), the plain knit cardigan 0.246; on the same backs a painted-in back print measured
#: Kai 0.071 / Tilda 0.198 / Dario 0.229 (a logo on 20 % of the garment), 0.257 / 0.295 / 0.364 (a text print on 35 %).
#: 0.20 = the front's margin (0.10 = 1.3 x its highest plain item, Tilda 0.076) over the highest plain shirt back
#: (1.3 x Dario 0.158 = 0.205): every plain shirt back is plain (the knit's rib reads as detail and keeps its job); a
#: large back print, or a print on a light back, is decorated. What it gives up: a
#: small back print on a dark folded shirt (Dario + a 20 % logo 0.229 is caught, + a 10 % logo 0.179 is not) is
#: filled plain — losing a small print is safer than the invented content of the back job.
PLAIN_BACK_DETAIL = 0.20


def is_plain_back(detail_back) -> bool:
    """Whether the piece's back view is plain (``PLAIN_BACK_DETAIL``): True only for a measured detail at or below
    the threshold — an unknown detail (no back view, an empty cut-out) is never plain."""
    try:
        return float(detail_back) <= PLAIN_BACK_DETAIL
    except (TypeError, ValueError):
        return False


def prompt_variant(side: str = "front", decorated: bool = False) -> str:
    """The ``PROMPT_FILES`` key of a job: "back", "front_decorated" or "front_plain"."""
    if side == "back":
        return "back"
    return "front_decorated" if decorated else "front_plain"


#: The last word of a piece name that is a pair noun ("gloves", "briefs", "trousers"): "a pair of …", never "a …".
PAIR_NOUNS = ("gloves", "briefs", "tights", "trousers", "leggings", "stockings", "socks", "shorts", "warmers")


def a_piece(piece: str) -> str:
    """The piece name with its article: "a balconette bra", "an …", "a pair of elbow-length gloves" (``PAIR_NOUNS``)."""
    piece = str(piece or "garment")
    if piece.rsplit(" ", 1)[-1] in PAIR_NOUNS:
        return f"a pair of {piece}"
    return f"an {piece}" if piece[:1].lower() in "aeiou" else f"a {piece}"


def _prompt_refs(side: str, piece: str, family: str = "top"):
    """The slots of every cut-texture render: the job's template is the canvas, its Picture 2 the material source."""
    from app.imagegen.edit_prompt import Ref
    if family == "fitted":
        back_canvas = f"the flat sewing pattern of the back pieces of {a_piece(piece)}"
        canvas = back_canvas if side == "back" else f"the flat sewing pattern of {a_piece(piece)}"
    else:
        canvas = (f"the flat sewing pattern of the back panel of a {piece}" if side == "back"
                  else f"the flat sewing pattern of a {piece}")
    source = f"the back of the {piece}" if side == "back" else f"the {piece}"
    return [Ref(1, "canvas", canvas), Ref(2, "material", source)]


def edit_prompt(*, piece: str, side: str = "front", decorated: bool = False, front_place: str = "",
                pieces=(), layout=(), sleeves=(), family: str = "top", main: dict | None = None,
                weave: str = cut_texture_post.WEAVE_WORDS[""]):
    """The cut-texture prompt of the ``side`` job as an ``EditPrompt`` (every dialect rendered): the variant's
    sectioned file (``prompt_variant`` of the ``family``'s ``PROMPT_SETS``) with ``piece`` (e.g. "T-shirt"), the job's
    ``pieces`` (``prompt_pieces``), ``layout`` (``layout_words``), the ``sleeves`` whose fabric stays plain (a fitted
    piece: its small pieces, ``prompt_plain_pieces``) and, for a ``decorated`` front, the front island's
    ``front_place`` ("top left"). A fitted family's prompt also names its MAIN pieces (``main`` = ``main_words``:
    ``{"phrase", "count", "names"}`` — "the two largest shapes", 2, "the right front leg panel and the left front leg
    panel"). ``weave`` names the fabric's weave in the back prompt (``cut_texture_post.stripe_words`` of the front
    answer: "fine vertical stripes" for a striped front, else "fine weave"). A missing variable raises
    (StrictUndefined)."""
    from app.imagegen.edit_prompt import from_template
    main = main or {"phrase": "", "count": 0, "names": ""}
    if side == "front" and decorated and not (front_place if family == "top" else main.get("phrase")):
        raise ValueError("a decorated front prompt needs the front island's place")
    variant = prompt_variant(side, decorated)
    return from_template(PROMPT_SETS[family][variant], _prompt_refs(side, piece, family), piece=piece,
                         a_piece=a_piece(piece),
                         front_place=front_place or "", pieces=list(pieces), layout=list(layout or []),
                         sleeves=list(sleeves or []), main=str(main.get("phrase") or ""),
                         main_count=int(main.get("count") or 0), main_names=str(main.get("names") or ""),
                         weave=weave)


def render_prompt(*, piece: str, side: str = "front", decorated: bool = False, front_place: str = "",
                  pieces=(), layout=(), sleeves=(), dialect: str = "ordinal", family: str = "top",
                  main: dict | None = None) -> str:
    """``edit_prompt(...)`` rendered in ``dialect`` (``edit_prompt.dialect_of`` of the backend it runs on)."""
    return edit_prompt(piece=piece, side=side, decorated=decorated, front_place=front_place, pieces=pieces,
                       layout=layout, sleeves=sleeves, family=family, main=main).render(dialect)


#: ``_place_words``: an island centre left of this share of the template is "left", right of 1 - it "right"; the
#: same for top / bottom; below ``LAYOUT_VERY`` it is "at the very bottom".
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


def front_place(islands: dict) -> str:
    """Where the front panel sits in the job's template, as the decorated prompt says it: the bbox centre of the first
    island whose part is "front" in ``_place_words`` without its preposition ("top left", "middle right", "very
    bottom"); "" without a front island."""
    size = float(islands.get("atlas_px") or 2048)
    fronts = sorted((i for i in islands.get("islands", []) if part_of(str(i["name"])) == "front"),
                    key=lambda i: _split_name(str(i["name"]))[1])
    if not fronts:
        return ""
    x0, y0, x1, y1 = (float(v) for v in (fronts[0].get("bbox_px") or _bbox(fronts[0])))
    words = _place_words(0.5 * (x0 + x1) / size, 0.5 * (y0 + y1) / size)
    for lead in ("at the ", "in the "):
        if words.startswith(lead):
            return words[len(lead):]
    return words


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
    (``front_2`` -> "front panel 2"); an unknown part name is spoken plainly after the known ones. Only the subject-form
    and the image-tag sections name the pieces (the short P-H3 prompts do not)."""
    out = []
    for name in _pattern_order(islands):
        base, n = _split_name(name)
        word = PROMPT_PIECE_NAMES.get(base, base.replace("_", " "))
        out.append(word if n == 1 else f"{word} {n}")
    return out


def _box_of(isl: dict) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in (isl.get("bbox_px") or _bbox(isl)))
    return x0, y0, x1, y1


def _shape_word(box, largest: bool, many: bool) -> str:
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    if max(w / h, h / w) >= LAYOUT_STRIP:
        return "the long thin strip"
    return "the large piece" if largest and many else "the piece"


#: The fitted family's cells (``fitted_places``): thirds of the square template on both axes.
FITTED_CELL = 1.0 / 3.0
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def _fitted_cell(cx: float, cy: float) -> str:
    v = "top" if cy < FITTED_CELL else "bottom" if cy > 1 - FITTED_CELL else "middle"
    h = "left" if cx < FITTED_CELL else "right" if cx > 1 - FITTED_CELL else "centre"
    if v == "middle":
        return "in the centre" if h == "centre" else f"in the middle {h}"
    return f"at the {v} {h}"


#: Row words of a cell whose pieces lie in 2 or 3 rows (``_rows_of``).
_ROW_WORDS = {2: ("upper", "lower"), 3: ("upper", "middle", "lower")}


def _rows_of(names: list, boxes: dict) -> list[list[str]]:
    """``names`` grouped into rows, top to bottom: pieces whose bbox height ranges overlap share a row (chained)."""
    rows: list[list[str]] = []
    bottom = -1.0
    for n in sorted(names, key=lambda n: boxes[n][1]):
        if rows and boxes[n][1] < bottom:
            rows[-1].append(n)
            bottom = max(bottom, boxes[n][3])
        else:
            rows.append([n])
            bottom = boxes[n][3]
    return rows


def _ranked_refs(names: list, centre: dict, order: list, axis: int, group: str, single: str = "") -> dict:
    """The refs of ``names`` (one cell, or one row of it) ordered along ``axis`` (0 = x, 1 = y): one piece ->
    ``single``; two -> "the left one of the two {group}" / "the right one ..." ("upper" / "lower" along y); more ->
    "the second from the left of the three {group}" (or "from the top")."""
    ranked = sorted(names, key=lambda n: (centre[n][axis], centre[n][1 - axis], order.index(n)))
    if len(ranked) == 1:
        return {ranked[0]: single}
    out = {}
    for k, n in enumerate(ranked):
        if len(ranked) == 2:
            side = ("left", "right")[k] if axis == 0 else ("upper", "lower")[k]
            out[n] = f"the {side} one of the two {group}"
        else:
            word = _ORDINALS[k] if k < len(_ORDINALS) else f"number {k + 1}"
            count = _COUNT_WORDS.get(len(ranked), str(len(ranked)))
            out[n] = f"the {word} from the {('left', 'top')[axis]} of the {count} {group}"
    return out


def fitted_places(islands: dict) -> dict[str, dict]:
    """Where every island of a fitted job's payload lies, as a phrase NO other island of the job shares (review
    2026-11-22: "the piece at the top left" named both front leg panels of Lirien's trousers, the cup and the gore of
    a bra, both backs of the hand). ``{name: {"cell", "alone", "ref"}}`` (a piece that shares its cell also
    carries ``group`` — "the two upper pieces at the top centre" — and the sorted ``members`` of it): ``cell`` = the third of the square template
    its bbox centre lies in on both axes (``FITTED_CELL``: "at the top left", "at the top centre", "in the middle
    right", "in the centre"); ``alone`` = no other island in that cell; ``ref`` = the noun phrase that picks it out —
    alone: "the piece at the top left" (``_shape_word``: "the long thin strip" / "the large piece" for the job's
    largest bbox). Several in a cell whose bboxes lie in 2 or 3 rows (``_rows_of``, height ranges that do not
    overlap): per row "the upper piece at the top right" (one), "the left one of the two upper pieces at the top
    centre" (two), "the second from the left of the three lower pieces ..." (more). Otherwise ordered along the axis
    their centres spread more on (x on a tie): "the left one of the two pieces at the top left" / "the right one ..."
    ("upper" / "lower" along y); three or more: "the second from the left of the three pieces at the bottom centre"
    (or "from the top")."""
    size = float(islands.get("atlas_px") or 2048)
    order = _pattern_order(islands)
    boxes = {str(i["name"]): _box_of(i) for i in islands.get("islands", [])}
    if not boxes:
        return {}
    largest = max(boxes, key=lambda n: (boxes[n][2] - boxes[n][0]) * (boxes[n][3] - boxes[n][1]))
    centre = {n: (0.5 * (b[0] + b[2]) / size, 0.5 * (b[1] + b[3]) / size) for n, b in boxes.items()}
    cells: dict[str, list[str]] = {}
    for name in order:
        cells.setdefault(_fitted_cell(*centre[name]), []).append(name)
    out = {}
    for cell, names in cells.items():
        if len(names) == 1:
            n = names[0]
            out[n] = {"cell": cell, "alone": True,
                      "ref": f"{_shape_word(boxes[n], n == largest, len(boxes) > 1)} {cell}"}
            continue
        rows = _rows_of(names, boxes)
        if 2 <= len(rows) <= len(_ROW_WORDS[len(rows)]):
            for row, word in zip(rows, _ROW_WORDS[len(rows)]):
                group = f"the {_COUNT_WORDS.get(len(row), str(len(row)))} {word} pieces {cell}"
                for n, ref in _ranked_refs(row, centre, order, 0, f"{word} pieces {cell}",
                                           single=f"the {word} piece {cell}").items():
                    out[n] = {"cell": cell, "alone": False, "ref": ref, "group": group, "members": sorted(row)}
            continue
        xs = [centre[n][0] for n in names]
        ys = [centre[n][1] for n in names]
        axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
        group = f"the {_COUNT_WORDS.get(len(names), str(len(names)))} pieces {cell}"
        for n, ref in _ranked_refs(names, centre, order, axis, f"pieces {cell}").items():
            out[n] = {"cell": cell, "alone": False, "ref": ref, "group": group, "members": sorted(names)}
    return out


def layout_words(islands: dict, family: str = "top") -> list[str]:
    """One sentence per island of the job's payload, in pattern order, saying which island of the template is which
    piece — e.g. "the large piece at the top left is the front panel", "the piece at the bottom left is the left
    sleeve", "the long thin strip at the very bottom is the neckband". Positions are the island's bbox centre in the
    square template (``LAYOUT_SIDE`` / ``LAYOUT_VERY``); "large" marks the island with the largest bbox area when the
    job has more than one; a bbox ``LAYOUT_STRIP`` times longer than wide is "the long thin strip".
    The ``fitted`` family names every island by ``fitted_places`` instead — a phrase no other island of the job
    shares ("the left one of the two pieces at the top left is the right front leg panel")."""
    names = dict(zip(_pattern_order(islands), prompt_pieces(islands)))
    if family == "fitted":
        places = fitted_places(islands)
        return [f"{places[n]['ref']} is the {names[n]}" for n in _pattern_order(islands)]
    size = float(islands.get("atlas_px") or 2048)
    boxes = {str(i["name"]): _box_of(i) for i in islands.get("islands", [])}
    if not boxes:
        return []
    largest = max(boxes, key=lambda n: (boxes[n][2] - boxes[n][0]) * (boxes[n][3] - boxes[n][1]))
    out = []
    for name in _pattern_order(islands):
        x0, y0, x1, y1 = boxes[name]
        shape = _shape_word(boxes[name], name == largest, len(boxes) > 1)
        out.append(f"{shape} {_place_words(0.5 * (x0 + x1) / size, 0.5 * (y0 + y1) / size)} is the {names[name]}")
    return out


def prompt_sleeves(islands: dict, sleeve_print: str = "plain") -> list[str]:
    """The sleeve pieces the subject-form prompt keeps plain: every piece name with "sleeve" in it, none when the
    piece's ``sleeve_print`` is "picture" (the sleeves then come from the answer, ``model_parts``)."""
    if sleeve_print == "picture":
        return []
    return [p for p in prompt_pieces(islands) if "sleeve" in p]


def prompt_plain_pieces(islands: dict, sleeve_print: str = "plain") -> list[str]:
    """A fitted piece's small pieces the prompt keeps plain (``TRIM_PARTS``: waistband, cuffs, bands, straps, gusset,
    thumbs, gore), in pattern order with their prompt names; none with ``sleeve_print`` "picture" (they then come
    from the answer)."""
    if sleeve_print == "picture":
        return []
    names = dict(zip(_pattern_order(islands), prompt_pieces(islands)))
    return [names[n] for n in _pattern_order(islands) if part_of(n) in TRIM_PARTS]


_COUNT_WORDS = {2: "two", 3: "three", 4: "four"}


def main_islands(islands: dict, job: str) -> list[str]:
    """The island names of ``job``'s MAIN pieces (``MAIN_PARTS``) in pattern order."""
    return [n for n in _pattern_order(islands) if part_of(n) in MAIN_PARTS.get(job, ())]


def main_words(islands: dict, job: str) -> dict:
    """How a fitted prompt names ``job``'s main pieces in its template (``islands`` = the job's payload, as the model
    sees it): ``{"phrase", "count", "names"}``. One main island alone in its cell (``fitted_places``): "the {cell}
    shape" ("the top left shape"); one that shares its cell: its ``ref`` ("the left one of the two pieces at the top
    left"). Several that are the largest by area (``area_cm2``): "the two largest shapes"; several that are not, each
    alone in its cell: "the shapes at the top left and at the top right"; exactly the pieces of one row or cell: its
    group ("the two upper pieces at the top centre"); otherwise their refs joined with "and".
    ``names``: their prompt names joined with "and", each with "the" ("the right front leg panel and the left front
    leg panel"). ``{"phrase": "", "count": 0, "names": ""}`` without one."""
    mains = main_islands(islands, job)
    if not mains:
        return {"phrase": "", "count": 0, "names": ""}
    by_name = {str(i["name"]): i for i in islands.get("islands", [])}
    words = dict(zip(_pattern_order(islands), prompt_pieces(islands)))
    places = fitted_places(islands)
    names = " and ".join(f"the {words[n]}" for n in mains)
    if len(mains) == 1:
        p = places[mains[0]]
        if p["alone"]:
            where = p["cell"].split(" ", 2)[-1]       # "at the top left" -> "top left", "in the centre" -> "centre"
            return {"phrase": f"the {where} shape", "count": 1, "names": names}
        return {"phrase": p["ref"], "count": 1, "names": names}
    area = {n: float(by_name[n].get("area_cm2") or 0.0) for n in by_name}
    largest = sorted(area, key=lambda n: -area[n])[:len(mains)]
    if set(largest) == set(mains) and len(mains) in _COUNT_WORDS:
        phrase = f"the {_COUNT_WORDS[len(mains)]} largest shapes"
    elif all(places[n]["alone"] for n in mains):
        phrase = "the shapes " + " and ".join(places[n]["cell"] for n in mains)
    elif places[mains[0]].get("members") == sorted(mains):
        phrase = places[mains[0]]["group"]             # the mains are exactly one row / cell: "the two upper pieces …"
    else:
        phrase = " and ".join(places[n]["ref"] for n in mains)
    return {"phrase": phrase, "count": len(mains), "names": names}

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
BACK_PARTS = ("back", "back_l", "back_r", "palm_l", "palm_r", "skirt_back")
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


#: Prompt test 2026-11-21 — the BACK job's template is ZOOMED: the back panel took only 14-16 % of the canvas (a
#: corner of the atlas), and P-H3 filled the empty white with the back-view photo (every short prompt, coverage
#: 0.84-0.91) or an extra garment (the long prompt). Cropped to the island box + this margin per side, padded white
#: to a square and scaled to the canvas, the panel fills ~40 % and the short back prompt passed Kai, Dario and Tilda.
BACK_ZOOM_MARGIN = 0.12


def job_frame(islands: dict, job: str, size: int, *, zoom_front: bool = False) -> dict | None:
    """The zoom frame of ``job``'s template (``BACK_ZOOM_MARGIN``; the back job, the front job too with
    ``zoom_front`` — a piece with held trims, ``held_trims``): ``{"ox", "oy", "side", "k"}`` — the atlas square
    ``[ox, ox + side) x [oy, oy + side)`` (integers, may reach past the atlas edge) is scaled by ``k = size / side``
    onto the template. None for an unzoomed front job, for a job without islands, or when the crop would not enlarge
    (``side >= size``)."""
    if job != "back" and not zoom_front:
        return None
    scale = size / float(islands.get("atlas_px") or size)
    pts = [np.asarray(i.get("verts_px") or [], float).reshape(-1, 2) * scale
           for i in islands.get("islands", []) if job_of(str(i["name"])) == job]
    pts = [p for p in pts if len(p)]
    if not pts:
        return None
    allp = np.concatenate(pts)
    (x0, y0), (x1, y1) = allp.min(0), allp.max(0)
    side = int(np.ceil(max(x1 - x0, y1 - y0) * (1 + 2 * BACK_ZOOM_MARGIN)))
    if side <= 0 or side >= size:
        return None
    ox = int(np.floor(0.5 * (x0 + x1) - side / 2))
    oy = int(np.floor(0.5 * (y0 + y1) - side / 2))
    return {"ox": ox, "oy": oy, "side": side, "k": size / side}


def zoom_payload(islands: dict, job: str, frame: dict, size: int) -> dict:
    """``islands`` with every island of ``job`` moved into the zoom ``frame`` (``(v - (ox, oy)) * k`` in ``size``
    pixels; the payload's ``atlas_px`` becomes ``size``; ``bbox_px`` dropped) — island names and so the label ids stay
    those of the atlas. The other jobs' islands keep their names but lose their triangles: in the frame they would
    land on the zoomed island and overwrite its labels."""
    import copy
    out = copy.deepcopy(islands)
    scale = size / float(islands.get("atlas_px") or size)
    k, o = float(frame["k"]), np.array([frame["ox"], frame["oy"]], float)
    for isl in out.get("islands", []):
        v = np.asarray(isl.get("verts_px") or [], float).reshape(-1, 2) * scale
        if job_of(str(isl["name"])) == job:
            isl["verts_px"] = ((v - o) * k).tolist()
        else:
            isl["verts_px"], isl["tris"] = [], []
        isl.pop("bbox_px", None)
    out["atlas_px"] = size
    return out


def unzoom(image: np.ndarray, grown: np.ndarray, frame: dict, size: int) -> tuple[np.ndarray, np.ndarray]:
    """A zoomed job's post-processed ``image`` / ``grown`` (``size`` square, the ``frame``'s view) back in the atlas
    frame: scaled to ``side`` (Lanczos; the grown mask nearest) and put at ``(ox, oy)``, clipped to the atlas; white /
    False elsewhere."""
    side, ox, oy = int(frame["side"]), int(frame["ox"]), int(frame["oy"])
    image = np.asarray(image, np.uint8)
    grown = np.asarray(grown, bool)
    if grown.any() and not grown.all():
        # review 2026-11-23 (Rosi's corset: white-pink rays round the front island, on the figure as pale streaks on
        # the flank): the Lanczos kernel mixed the white outside ``grown`` into its outer pixels, and the atlas's
        # pocket fill (``cut_texture_post.fill_pockets``) drew those pale pixels out as rays — so the outside takes the
        # nearest grown colour before the scale
        from scipy import ndimage
        _d, (iy, ix) = ndimage.distance_transform_edt(~grown, return_indices=True)
        image = image[iy, ix]
    small = np.asarray(Image.fromarray(image, "RGB").resize((side, side), Image.LANCZOS))
    gsmall = np.asarray(Image.fromarray(np.asarray(grown, np.uint8) * 255, "L").resize((side, side), Image.NEAREST)) > 127
    out = np.full((size, size, 3), 255, np.uint8)
    g = np.zeros((size, size), bool)
    x0, y0 = max(ox, 0), max(oy, 0)
    x1, y1 = min(ox + side, size), min(oy + side, size)
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = small[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        g[y0:y1, x0:x1] = gsmall[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return out, g


def csig(islands_sha: str, item_sha: str, back_sha: str = "", prompt_sha: str = PROMPT_SHA) -> str:
    """The cut atlas key: the cut's islands, the item image, the back view the back job read ("" for a pattern
    without a back panel, or before the view exists), the prompt files of the piece's family (``prompt_sha_of``; a
    top's by default) and the post-processing version — NOT ``tsig`` (it carries the piece-only views' sha for the
    projection, which the atlas does not depend on)."""
    raw = "|".join([str(islands_sha), str(item_sha), str(back_sha or ""), str(prompt_sha),
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


#: ``back_detail`` per (path, mtime_ns, size) — the plan reads it on every figure read.
_back_detail_cache: dict[tuple, float | None] = {}


def detail_of_view(path: Path) -> float | None:
    """The detail density of a piece-only view file (``cut_texture_post.picture_reference``, its alpha the cut-out —
    the measure ``references`` gives the back job's detail gate), cached by the file's stat; None when unreadable."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _back_detail_cache:
        return _back_detail_cache[key]
    try:
        with Image.open(path) as bv:
            rgba = np.asarray(bv.convert("RGBA"))
        value = cut_texture_post.picture_reference(rgba, matte=None)["detail"]
    except (OSError, ValueError) as e:
        logger.warning("Cut texture: the detail of %s not measured: %s", path, e)
        return None
    if len(_back_detail_cache) > 256:
        _back_detail_cache.clear()
    _back_detail_cache[key] = value
    return value


def back_detail(character_name: str, item_id: str) -> float | None:
    """The detail density of the piece's accepted back view (``detail_of_view``), None without one."""
    path = back_view(character_name, item_id)
    return detail_of_view(path) if path is not None else None


def back_plain(character_name: str, item_id: str) -> bool | None:
    """Whether the piece's back is filled plain (``is_plain_back`` of ``back_detail``): None while there is no back
    view to measure (the flow makes it first, the counts then assume the back job)."""
    if back_view(character_name, item_id) is None:
        return None
    return is_plain_back(back_detail(character_name, item_id))


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


def prompt_kind(params: dict | None) -> str:
    """The prompt kind of template ``params``: the template kind, "strapless" for a strapless top (cut by ``wrap`` into
    a front and a back panel, group B) — "" without parameters. Every csig of a piece is keyed by it
    (``prompt_sha_of``): the record's and the one ``garment_template.cut_info`` looks the atlas up with."""
    params = params or {}
    if params.get("kind") == "top" and params.get("shoulders") == "strapless":
        return "strapless"
    return str(params.get("kind") or "")


def item_kind(item_id: str) -> str:
    """The piece's prompt kind (``prompt_kind`` of its params)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    return prompt_kind(gt.params_of(get_item(item_id)))


def csig_for(character_name: str, item_id: str, islands_sha: str, islands: dict | None = None,
             *, has_back_panel: bool | None = None, kind: str | None = None) -> str | None:
    """The csig of the piece for these islands with the CURRENT item picture and back view; None without a
    picture. ``has_back_panel`` None = read it from ``islands``; ``kind`` None = the item's (``item_kind``)."""
    isha = item_sha(item_id)
    if isha is None:
        return None
    if has_back_panel is None:
        has_back_panel = has_back(islands or {})
    kind = item_kind(item_id) if kind is None else kind
    return csig(islands_sha, isha, back_sha(character_name, item_id) if has_back_panel else "", prompt_sha_of(kind))


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
    """The English name of a piece from its template params: a top by its sleeve length (a strapless one: "corset top" /
    "strapless top"), a skirt by its flare and length (group B), a jacket by its collar, fabric and front, a dress by
    its length and sleeves (group B, phases C / D); step 3a the close-fitting kinds by their cut (briefs: boxer / string / thong / high-leg; a bra by its cup; gloves by fingers and length;
    tights by style and foot; trousers by length and leg)."""
    p = params or {}
    kind = str(p.get("kind") or "garment")
    if kind == "top" and p.get("shoulders") == "strapless":
        # group B (A4): a straight / sweetheart edge cut tight is a corset top
        tight = float(p.get("fit", 0.4)) <= 0.2 and p.get("neckline") in ("straight", "sweetheart")
        return "corset top" if tight else "strapless top"
    if kind == "top":
        return {"none": "sleeveless top", "cap": "T-shirt", "short": "T-shirt", "elbow": "elbow-sleeve shirt",
                "long": "long-sleeve shirt"}.get(str(p.get("sleeves") or "short"), "top")
    if kind == "skirt":
        # group B (A4): by flare and length; a slit does not change the name
        flare, length = float(p.get("flare", 0.3)), float(p.get("length_m", 0.5))
        if flare >= 0.6:
            base = "circle skirt"
        elif flare <= 0.1:
            base = "pencil skirt" if length <= 0.45 else "straight skirt"
        else:
            base = "A-line skirt"
        return f"long {base}" if length >= 0.75 and base != "pencil skirt" else base
    if kind == "jacket":
        # phase C (C4): a lapel collar is a blazer's, leather a leather jacket's, an open front without a collar a
        # cardigan's
        if p.get("collar") == "lapel":
            return "blazer"
        if str(p.get("fabric") or "").startswith("leather"):
            return "leather jacket"
        return "cardigan" if p.get("front") == "open" and p.get("collar") in (None, "none") else "jacket"
    if kind == "dress":
        # phase D (D2): by its length from the waist (mini < 0.40 m, knee-length < 0.65, midi < 0.85, else long) and
        # its sleeves (long -> "long-sleeve", any other -> "short-sleeve", none -> no word)
        length = float(p.get("length_m", 0.6))
        base = ("mini dress" if length < 0.40 else "knee-length dress" if length < 0.65
                else "midi dress" if length < 0.85 else "long dress")
        sleeves = str(p.get("sleeves") or "none")
        if p.get("shoulders") not in ("covered", "off_shoulder") or sleeves == "none":
            return base
        return ("long-sleeve " if sleeves == "long" else "short-sleeve ") + base
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
    """A ``picture_edit`` backend whose entry does not switch the prompt upsampler off (``edit_prompt.lint_backend``;
    a warning, not a block)."""
    from app.imagegen.edit_prompt import lint_backend
    return any(note["code"] == "upsampler_on" for note in lint_backend(b))


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


def _routed_render(item_id: str, side: str, prompt_for, template_png: Path, ref_png: Path, seed: int):
    """ONE routed img2img render of a job's template + its Picture 2 -> ``(answer bytes, backend, route, dialect,
    prompt)``. ``prompt_for(dialect)`` gives the job's prompt in the dialect of the backend the route lands on
    (``edit_prompt.dialect_of``) — chosen inside the render, so a re-run on the next entry gets its own wording."""
    from app.core.prompt_compose import compose
    from app.imagegen import routing as _routing
    from app.imagegen.edit_prompt import dialect_of
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    chosen: dict = {}

    def _render(b):
        dialect = dialect_of(b)
        prompt = prompt_for(dialect)
        chosen.update(dialect=dialect, prompt=prompt)
        composed = compose(use_case=CUT_USE_CASE, subject=prompt, backend=b, keep_negations=True)
        for warning in composed.warnings:
            logger.info("Prompt composer (%s): %s", CUT_USE_CASE, warning)
        params = {"seed": seed,
                  "reference_images": {"input_reference_image_1": str(template_png),
                                       "input_reference_image_2": str(ref_png)},
                  "reference_roles": {"input_reference_image_1": {"role": "canvas", "label": f"{side} template"},
                                      "input_reference_image_2": {"role": "material",
                                                                  "label": JOB_REFERENCE[side]}}}
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
    return bytes(images[0]), used, route, chosen.get("dialect", ""), chosen.get("prompt", "")


def attempt_seed(seed: int, attempt: int) -> int:
    """The seed of render ``attempt`` (1-based): ``seed`` + ``ATTEMPT_SEED_STEP`` per later attempt — a single-entry
    chain clamps attempt 2 onto the same backend, and the same seed would give the same answer."""
    return (int(seed) + ATTEMPT_SEED_STEP * (int(attempt) - 1)) % 2 ** 31


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
    plain = bool("back" in parts and not view and back_plain(character_name, item_id))
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
    back = 1 if "back" in todo and not plain else 0     # a plain back is the front's fabric: 0 image jobs
    total = view + upscale + front + back
    return {"back_view": view, "upscale": upscale, "front": front, "back": back, "total": total,
            "max": total + view * (tv.JOBS_PER_VIEW - 1) + (front + back) * (CUT_ATTEMPTS - 1),
            "reused": sorted(reuse), "back_plain": plain}


def job_plan(character_name: str, item_id: str, islands: dict | None = None, islands_sha: str = "") -> dict:
    """What one click spends now — the buttons' counts, by the same reuse rule ``generate`` runs (``reused_jobs``):
    Run all ``{"back_view" (0 / 1, at most ``JOBS_PER_VIEW``), "upscale" (0 / 1), "front" (0 / 1), "back" (0 / 1),
    "total", "max", "reused" (the jobs whose answer is kept), "back_plain"}`` (``max``: a refused back-view attempt is
    made once more, and each texture job may render ``CUT_ATTEMPTS`` times — attempt 2 after a gate rejection; ``back_plain``: the back view is plain (``back_plain``) — the back is the front's fabric, "back" 0;
    while the back view is missing the back job is counted) and ``redo`` = the same per Redo button (``{"front":
    {...}, "back": {...}}``, "back" only with a back panel that is not plain)."""
    if islands is None or not islands_sha:
        try:
            pattern = _ready_pattern(character_name, item_id)
            islands, islands_sha = _islands_of(pattern), pattern["islands_sha"]
        except NotReady:
            islands, islands_sha = islands or {}, ""
    side = _item_side(item_id)
    out = _plan_one(character_name, item_id, islands, islands_sha, side, None)
    out["redo"] = {job: _plan_one(character_name, item_id, islands, islands_sha, side, job)
                   for job in JOBS if job == "front" or (has_back(islands) and not out["back_plain"])}
    return out


#: The MAIN pieces of each job — what its gates measure (colour, detail), what its fabric patch is cut from, what a
#: decorated prompt names: a top's front / back panel; group A (2026-11-21) the close-fitting kinds' large pieces —
#: the trousers' (and boxers') front_l + front_r / back_l + back_r, a brief's front / back, the tights' legs, the
#: bra's cups (a bandeau's front / back), the gloves' backs of the hand / palms; group B a skirt's skirt_front /
#: skirt_back (a dress's skirt part beside its bodice) and an open jacket's left_front + right_front. Part names are
#: unique across kinds, so a pattern finds its own without its kind.
MAIN_PARTS = {"front": ("front", "front_r", "front_l", "leg_r", "leg_l", "cup_r", "cup_l", "glove_back_r",
                        "glove_back_l", "skirt_front", "left_front", "right_front"),
              "back": ("back", "back_l", "back_r", "palm_l", "palm_r", "skirt_back")}
#: User test 2026-11-21 — the parts of each job whose pixels come from the model's answer: the main pieces, a top's
#: placket (reserved), a balconette's upper cups (the lace / trim sits on them); every other island of the job (the
#: sleeves, the neckband, the cuffs; group A's small pieces ``TRIM_PARTS``) is filled with the seamless fabric patch
#: of the job's main pieces (``fill_fabric``). With the piece's ``sleeve_print`` "picture" the sleeves, cuffs and
#: small pieces come from the answer too.
MODEL_PARTS = {"front": MAIN_PARTS["front"] + ("placket", "cup_top_r", "cup_top_l"),
               "back": MAIN_PARTS["back"]}
SLEEVE_PARTS = ("sleeve_l", "sleeve_r", "cuff_l", "cuff_r")
#: The parts ``sleeve_print`` decides about: a top's sleeves and cuffs, group A's small pieces — waistband, cuffs,
#: bra bands, straps and gore, gusset, glove thumbs, a string brief's hip bands, a stocking's top bands; phases C / D a
#: jacket's / dress's collar (a 3.7 cm strip: held like the waistband; a covered top's too since phase E). A neckband is never one
#: (always the fabric patch).
TRIM_PARTS = SLEEVE_PARTS + ("waistband", "gusset", "gore", "band_r", "band_l", "strap_r", "strap_l", "thumb_r",
                             "thumb_l", "hip_band_r", "hip_band_l", "top_band_r", "top_band_l", "collar")
#: Stage "layers" (2026-11-22, Glut's bra: the picture's straps and band are black with gold edges, the fabric fill gave
#: them the cups' scales) — the small pieces the item TEXT names with a colour of their own (``trim_style``): the noun
#: (singular / plural) and the parts it names. Only these nouns: "trim" / "edge" name the edging, never a piece.
TRIM_NOUNS = {"strap": ("strap_l", "strap_r"), "band": ("band_l", "band_r"), "underband": ("band_l", "band_r"),
              "waistband": ("waistband",), "cuff": ("cuff_l", "cuff_r"), "collar": ("collar",), "gore": ("gore",)}
#: The nouns that make a colour the trims' EDGE colour ("with gold edges", "gold piping").
EDGE_NOUNS = ("edge", "edging", "trim", "piping", "rim", "border", "binding")
#: The participles that make the colour after them the edge colour ("edged in gold", "trimmed with silver").
EDGE_VERBS = ("edged", "trimmed", "piped", "rimmed", "bordered")
#: sRGB of the colour words a trim may name (English: the item's prompt fragment is the picture's prompt). A word
#: outside this list names no trim colour (the trims keep the fabric fill).
TRIM_COLOURS = {"black": (24, 22, 22), "white": (236, 234, 230), "grey": (128, 128, 128), "gray": (128, 128, 128),
                "silver": (184, 184, 190), "gold": (196, 152, 64), "golden": (196, 152, 64),
                "brass": (176, 140, 72), "bronze": (150, 100, 52), "copper": (176, 102, 64), "red": (164, 32, 32),
                "brown": (104, 66, 38), "tan": (176, 134, 92), "beige": (212, 192, 160), "cream": (232, 222, 196),
                "blue": (44, 66, 148), "navy": (28, 36, 72), "green": (44, 112, 54), "pink": (222, 142, 164),
                "purple": (104, 52, 124), "orange": (214, 112, 36), "yellow": (222, 192, 52)}
#: The edge band of a trim island (cm, inside its outline).
TRIM_EDGE_CM = 0.25
#: The share of the filled fabric's lightness detail a trim keeps over its own colour (the grain of the material,
#: not the fabric's print).
TRIM_GRAIN = 0.25
#: Garment nouns: a colour before one of them is the garment's, a trim noun right before one is a compound
#: ("spaghetti-strap dress") — round D, final step (review of stage "layers": ``trim_style`` false positives).
GARMENT_NOUNS = ("dress", "gown", "top", "bra", "bralette", "bodice", "corset", "bustier", "skirt", "shirt", "blouse",
                 "tee", "jacket", "coat", "blazer", "cardigan", "sweater", "jumper", "pullover", "vest", "waistcoat",
                 "tunic", "robe", "suit", "jeans", "trousers", "pants", "shorts", "leggings", "tights", "stockings",
                 "gloves", "glove", "bikini", "swimsuit", "leotard", "camisole", "slip", "brief", "apron", "uniform")
#: The version of the trims' painting, kept in ``trim_style`` (so in every record's ``trim_style``): a change of the
#: painting recomposes every atlas with trims once (CPU, 0 image jobs; ``composed_as_now``). 2 (round D, final step):
#: the edge band keeps a core of the trim colour in a narrow part (``paint_trims``).
TRIM_VERSION = 2
_TRIM_WORD = re.compile(r"[a-z]+")


def _noun(word: str, nouns) -> str | None:
    for n in nouns:
        if word == n or word == n + "s" or word == n + "es":
            return n
    return None


def trim_style(text: str) -> dict | None:
    """The trims' own colour as the item ``text`` (its prompt fragment) names it: ``{"parts": [...], "colour": rgb,
    "edge": rgb | None, "words": [...], "version": TRIM_VERSION}``, or None when it names none.

    The text is read in segments (split at ",", ";" and the word "with"). In a segment, a trim noun (``TRIM_NOUNS``)
    takes the colour word (``TRIM_COLOURS``) nearest BEFORE it, else the first one after it — but never across a
    garment noun (``GARMENT_NOUNS``: "red dress straps" names the dress's colour) and never the edge colour. A trim
    noun right before a garment or another trim noun is a compound ("spaghetti-strap dress", "band collar") and names
    no trim. The first colour found stands: a noun with another colour ends the reading ("white collar and red
    cuffs" -> the collar). A segment of trim nouns without a colour, right after such a segment, joins it ("black
    straps, band and gore"); the colour word right before an edge noun ("with gold edges") or after an edge participle
    ("edged in gold") in the segment or in the next one without a trim noun is the edge colour. "molded cups of red
    scales with black straps" gives black straps."""
    low = (text or "").lower()
    segs = [seg for part in re.split(r"[,;]", low) for seg in re.split(r"\bwith\b", part)]
    parts: list[str] = []
    colour = edge = None
    group = False
    done = False
    for seg in segs:
        words = _TRIM_WORD.findall(seg)
        edge_at = next((i for i, w in enumerate(words) if w in TRIM_COLOURS
                        and (_noun(words[i + 1] if i + 1 < len(words) else "", EDGE_NOUNS)
                             or any(v in EDGE_VERBS for v in words[max(0, i - 2):i]))), None)
        edge_here = words[edge_at] if edge_at is not None else None
        found = []                             # (noun, colour word | None) in reading order
        for i, w in enumerate(words):
            n = _noun(w, TRIM_NOUNS)
            if not n:
                continue
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if _noun(nxt, TRIM_NOUNS) or _noun(nxt, GARMENT_NOUNS):
                continue                       # a compound: the next noun is the piece
            own = None
            for j in range(i - 1, -1, -1):     # the nearest colour before it, not across a garment noun
                if _noun(words[j], GARMENT_NOUNS):
                    break
                if words[j] in TRIM_COLOURS and j != edge_at:
                    own = words[j]
                    break
            if own is None:
                for j in range(i + 1, len(words)):
                    if _noun(words[j], GARMENT_NOUNS) or _noun(words[j], TRIM_NOUNS):
                        break
                    if words[j] in TRIM_COLOURS and j != edge_at:
                        own = words[j]
                        break
            found.append((n, own))
        nouns = [n for n, _ in found]
        if nouns and (any(c for _, c in found) or group):
            for n, own in found:
                if own and colour and own != colour:
                    done = True                # a second trim colour: the first group stands
                    break
                if own is None and colour is None:
                    continue                   # a trim before the first colour of the segment names none
                colour = colour or own
                parts.extend(p for p in TRIM_NOUNS[n] if p not in parts)
            edge = edge or edge_here
            group = True
            if done:
                break
            continue
        if group and not nouns and edge_here and edge is None:
            edge = edge_here
        group = False
    if not parts or colour is None:
        return None
    return {"parts": parts, "colour": list(TRIM_COLOURS[colour]), "edge": list(TRIM_COLOURS[edge]) if edge else None,
            "words": [colour] + ([edge] if edge else []), "version": TRIM_VERSION}


def trim_style_of(item_id: str) -> dict | None:
    """``trim_style`` of the piece's prompt fragment (None without one or when it names no trim colour)."""
    from app.models.inventory import get_item
    return trim_style(str((get_item(item_id) or {}).get("prompt_fragment") or ""))


def paint_trims(atlas: np.ndarray, islands: dict, size: int, px_per_cm: float,
                style: dict | None) -> tuple[np.ndarray, dict]:
    """The trim islands ``style`` names (``trim_style``; only those the pattern has) and the bleed nearest to them
    painted in the trims' colour, keeping ``TRIM_GRAIN`` of the filled fabric's lightness detail, with an
    ``TRIM_EDGE_CM`` band inside each island's outline in the edge colour — in a narrow part at most half of the
    local half-width, so the trim colour keeps a core there. Returns the atlas and
    ``{"islands": [...], "edge_px": n}`` ({"islands": []} without a style or a named island)."""
    from scipy import ndimage
    post = cut_texture_post
    if not style:
        return atlas, {"islands": []}
    labels = rasterise_islands(islands, size)
    ids = island_ids(islands)
    names = sorted(n for n, iid in ids.items() if part_of(n) in style["parts"] and (labels == iid).any())
    if not names:
        return atlas, {"islands": []}
    sel = np.zeros(256, bool)
    for n in names:
        sel[ids[n]] = True
    own = sel[labels]
    dist, (iy, ix) = ndimage.distance_transform_edt(labels == 0, return_indices=True)
    bleed = max(1, int(round(post.BLEED_CM * px_per_cm)))
    region = own | ((labels == 0) & sel[labels[iy, ix]] & (dist <= bleed))
    out = np.asarray(atlas)[..., :3].astype(np.uint8).copy()
    lab = post.srgb_to_lab(out[region].astype(np.float64))
    grain = (lab[:, 0] - lab[:, 0].mean()) * TRIM_GRAIN
    edge_px = 0
    colours = np.repeat(post.srgb_to_lab(np.asarray([style["colour"]], np.float64)), len(lab), axis=0)
    if style.get("edge"):
        band = max(1, int(round(TRIM_EDGE_CM * px_per_cm)))
        yy, xx = np.mgrid[-band:band + 1, -band:band + 1]
        disk = (xx * xx + yy * yy) <= band * band
        inner = np.zeros_like(own)
        for n in names:
            m = labels == ids[n]
            d = ndimage.distance_transform_edt(m)
            # round D, final step (review of stage "layers": a narrow gore turned fully gold): the edge takes at most
            # half of the island's local half-width (the largest inner distance within one band, +1 px for the
            # raster), so a narrow part keeps a core of the trim colour; a part at least 4 bands wide is unchanged
            local = ndimage.maximum_filter(d, footprint=disk)
            inner |= m & (d <= band) & (2 * d <= local + 1)
        edge_mask = (inner | ((labels == 0) & region))[region]
        colours[edge_mask] = post.srgb_to_lab(np.asarray([style["edge"]], np.float64))[0]
        edge_px = int(inner.sum())
    colours[:, 0] = colours[:, 0] + grain
    out[region] = np.clip(np.rint(post.lab_to_srgb(colours)), 0, 255).astype(np.uint8)
    return out, {"islands": names, "edge_px": edge_px}


#: A pre-fill nearer to white than this (the largest channel distance) is darkened to it: the gate and the
#: registration find the islands as "not near-white" (``cut_texture_post.WHITE_TOL`` 24), so a white fabric goes as a
#: very light grey (the colour match moves the atlas back onto the item's own white).
PREFILL_MIN_DIST = 40


def model_parts(job: str, sleeve_print: str = "plain") -> tuple[str, ...]:
    """The parts of ``job`` taken from the model's answer (``MODEL_PARTS``; with "picture" also ``TRIM_PARTS``)."""
    parts = MODEL_PARTS.get(job, ())
    return parts + TRIM_PARTS if job == "front" and sleeve_print == "picture" else parts


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


def panel_fabric(img: np.ndarray, islands: dict, labels: np.ndarray, job: str, px_per_cm: float) -> dict:
    """The fabric of ``job``'s main panel in ``img`` (``labels`` = the job's labels): its base colour
    (``cut_texture_post.fabric_colour``) and its plainest seamless patch (``fabric_patch`` on the panel eroded by
    ``LINE_PX + 1``) — ``{"patch", "info", "base"}``, or ``{"skipped": reason}``. The ONE source of the sleeves', the
    neckband's and a plain back's fabric (``fill_fabric``, ``fill_plain_back``)."""
    from scipy import ndimage
    post = cut_texture_post
    panel = _part_mask(islands, labels, MAIN_PARTS[job])
    if not panel.any():
        return {"skipped": "no main panel"}
    base = post.fabric_colour(img, panel)
    found = post.fabric_patch(img, ndimage.binary_erosion(panel, iterations=LINE_PX + 1), px_per_cm,
                              base["lab"] if base else None)
    if found is None or base is None:
        return {"skipped": "no fabric patch fits the main panel"}
    return {"patch": found[0], "info": found[1], "base": base}


def fill_fabric(img: np.ndarray, labels: np.ndarray, grown: np.ndarray, islands: dict, job: str, px_per_cm: float,
                sleeve_print: str = "plain", fabric: dict | None = None) -> tuple[np.ndarray, dict]:
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
    fabric = fabric if fabric is not None else panel_fabric(img, islands, labels, job, px_per_cm)
    if "skipped" in fabric:
        return img, {"islands": fabric_names, "skipped": fabric["skipped"]}
    patch, info, base = fabric["patch"], fabric["info"], fabric["base"]
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
    ok, met, reason = post.gate(reg, mask, labels, px_per_cm, reg_info.get("white_tol", post.WHITE_TOL))
    panel = _part_mask(islands, labels, MAIN_PARTS[job])
    gates, answer = post.answer_gates(reg, panel, refs.get("colour"), (refs.get("detail") or {}).get(job))
    split = post.split_gate(reg, np.where(panel, labels, 0), px_per_cm,
                            reg_info.get("white_tol", post.WHITE_TOL), refs.get("fabric"))
    if split is not None:
        gates.append(split)
    # review of stage 3: the back's weave against the front answer's (``cut_texture_post.WEAVE_GATE``)
    weave = post.weave_levels(reg, panel, px_per_cm) if panel.any() else None
    if weave is not None:
        # stage "details": the front's stripe direction names the back prompt's weave (``stripe_words``), a back
        # striped along the same axis is held to the stripe level limit (``weave_gates``)
        weave = {**weave, "axis": post.weave_axis(reg, panel, px_per_cm)}
    if job == "back":
        gates.extend(post.weave_gates(weave, refs.get("front_weave")))
    failures = list(met["failures"]) + [g["text"] for g in gates if not g["ok"]]
    metrics = {"iou": met["iou"], "coverage": met["coverage"], "island_coverage": met["island_coverage"],
               "spill": met["spill"], "registration": reg_info, "islands": met["islands"],
               "gates": gates, "fabric": answer["fabric"], "detail": answer["detail"], "weave": weave,
               "failures": failures}
    if failures and not force:
        metrics.update({"de_before": None, "de_after": None, "clamped": None})
        return {"state": "rejected", "reason": failures[0], "metrics": metrics, "accepted": False}
    rim = post.outline_rim(reg, mask)
    cut = post.cut_and_bleed(reg, mask, max(1, int(round(post.BLEED_CM * px_per_cm))), erode_px=rim["px"])
    grown = ~np.all(cut == 255, axis=-1) | mask
    matched, cm = post.colour_match(cut, grown, fabric=refs.get("fabric"),
                                    base=(refs.get("colour"), (answer.get("fabric") or {}).get("answer")))
    fabric = panel_fabric(matched, islands, labels, job, px_per_cm)
    filled, fill = fill_fabric(matched, labels, grown, islands, job, px_per_cm, sleeve_print, fabric=fabric)
    halo = None
    if job == "front" and refs.get("halo") and "skipped" not in fabric:
        # stage "details": an invented texture field round a decorated front's motif becomes the plain fabric —
        # measured on the registered ANSWER (the colour match after it flattens the contrast),
        # filled on the matched image (the same frame)
        own = post.fabric_colour(reg, panel)
        busy, halo = (post.busy_halo(reg, panel, own["lab"], px_per_cm) if own
                      else (np.zeros(panel.shape, bool), {"px": 0}))
        if busy.any():
            filled, _t = post.tile_fill(filled, busy, fabric["patch"], fabric["base"]["lab"])
    metrics.update({"de_before": cm.get("de_before"), "de_after": cm.get("de_after"),
                    "clamped": cm.get("clamped"), "colour": cm, "fabric_fill": fill, "rim": rim, "halo": halo})
    return {"state": "ready", "reason": "", "metrics": metrics, "accepted": bool(failures),
            "_image": filled, "_grown": grown, "_mask": mask, "_fabric": fabric}


#: Live test 2026-11-22 (Tilda's wool skirt, a 1-row waistband 21 px high beside the front panel): MiniMax painted
#: the thin strip twice as high (spill 0.07, iou 0.87) and P-H3 left it out and blew the panel up to the frame
#: (waistband coverage 0.00) — yet a plain trim's pixels never come from the answer (``fill_fabric``). So for these
#: prompt kinds the plain trims are HELD: the template and the gates hold the model's parts only (zoomed like the
#: back job), the trims are filled with the panel's fabric in the atlas frame afterwards. The tops and group A keep
#: their tested templates.
#: Phases C / D (2026-11-22): a jacket and a dress hold their sleeves, neckband and collar the same way — the model
#: paints the front / back panels (a dress's bodice and skirt part, an open jacket's two fronts) only.
HELD_TRIM_KINDS = ("skirt", "strapless", "jacket", "dress")


def held_trims(kind, sleeve_print: str = "plain") -> bool:
    """Whether a piece of prompt kind ``kind`` (``item_kind``) holds its plain trims back from the model
    (``HELD_TRIM_KINDS``; never with ``sleeve_print`` "picture": the trims then come from the answer)."""
    return str(kind or "") in HELD_TRIM_KINDS and sleeve_print != "picture"


def sent_islands(islands: dict, job: str, sleeve_print: str = "plain", *, drop: bool = False) -> dict:
    """``islands`` as the model sees ``job`` with held trims: the job's islands outside ``model_parts`` lose their
    geometry (names kept — the label ids are the sorted names, ``island_ids``) or, with ``drop`` (the prompt's
    words), leave the list."""
    import copy
    keep = model_parts(job, sleeve_print)
    out = copy.deepcopy(islands)
    kept = []
    for isl in out.get("islands", []):
        name = str(isl["name"])
        if job_of(name) == job and part_of(name) not in keep:
            if drop:
                continue
            isl["verts_px"], isl["tris"] = [], []
            isl.pop("bbox_px", None)
        kept.append(isl)
    out["islands"] = kept
    return out


def job_template(islands: dict, parts: dict, job: str, size: int, fill=None, *, held: bool = False,
                 sleeve_print: str = "plain") -> Image.Image:
    """The template the ``job`` sends as the first image: ``render_template`` of its islands, in its zoom frame
    (``job_frame``) when it has one; with ``held`` (``held_trims``) the model's parts only, the front zoomed too."""
    src = sent_islands(islands, job, sleeve_print) if held else islands
    frame = job_frame(src, job, size, zoom_front=held)
    if frame:
        sub = split_islands(zoom_payload(src, job, frame, size))[job]
    else:
        sub = split_islands(src)[job] if held else parts[job]
    return render_template(sub, size, fill=fill)


def post_job(answer: bytes, islands: dict, size: int, px_per_cm: float, job: str, refs: dict, *,
             force: bool = False, sleeve_print: str = "plain", held: bool = False) -> dict:
    """``_post_job`` in the job's zoom frame (``job_frame``: the islands moved into it, ``px_per_cm`` times ``k``)
    and, on "ready", its image / grown area back in the atlas frame (``unzoom``) with the atlas mask — so ``compose``
    never sees the frame. ``metrics.zoom`` is the frame (None for an unzoomed front job). With ``held``
    (``held_trims``) see ``_post_held``."""
    if held:
        return _post_held(answer, islands, size, px_per_cm, job, refs, force=force, sleeve_print=sleeve_print)
    frame = job_frame(islands, job, size)
    if frame is None:
        res = _post_job(answer, islands, size, px_per_cm, job, refs, force=force, sleeve_print=sleeve_print)
    else:
        res = _post_job(answer, zoom_payload(islands, job, frame, size), size, px_per_cm * frame["k"], job, refs,
                        force=force, sleeve_print=sleeve_print)
        if res["state"] == "ready":
            mask = job_labels(islands, size, job) > 0
            image, grown = unzoom(res["_image"], res["_grown"], frame, size)
            res.update({"_image": image, "_grown": grown | mask, "_mask": mask})
    res["metrics"]["zoom"] = ({k: (round(v, 4) if isinstance(v, float) else v) for k, v in frame.items()}
                              if frame else None)
    return res


def _post_held(answer: bytes, islands: dict, size: int, px_per_cm: float, job: str, refs: dict, *,
               force: bool = False, sleeve_print: str = "plain") -> dict:
    """``post_job`` of a piece with held trims (``HELD_TRIM_KINDS``): ``_post_job`` on the model's parts only
    (``sent_islands``; the gates measure them alone), in the zoom frame of those parts; on "ready" back in the atlas
    frame, where the held trims and their bleed (``cut_texture_post.BLEED_CM``) are filled with the job's panel fabric
    (``panel_fabric`` / ``fill_fabric`` at the atlas scale, so a plain back's tile matches too)."""
    from scipy import ndimage
    post = cut_texture_post
    src = sent_islands(islands, job, sleeve_print)
    frame = job_frame(src, job, size, zoom_front=True)
    if frame is None:
        res = _post_job(answer, src, size, px_per_cm, job, refs, force=force, sleeve_print=sleeve_print)
    else:
        res = _post_job(answer, zoom_payload(src, job, frame, size), size, px_per_cm * frame["k"], job, refs,
                        force=force, sleeve_print=sleeve_print)
    res["metrics"]["zoom"] = ({k: (round(v, 4) if isinstance(v, float) else v) for k, v in frame.items()}
                              if frame else None)
    if res["state"] != "ready":
        return res
    image, grown = (unzoom(res["_image"], res["_grown"], frame, size) if frame
                    else (res["_image"], res["_grown"]))
    labels = job_labels(islands, size, job)
    mask = labels > 0
    trims = mask & ~(job_labels(src, size, job) > 0)
    if trims.any():
        bleed = max(1, int(round(post.BLEED_CM * px_per_cm)))
        grown = grown | (ndimage.distance_transform_edt(~trims) <= bleed)
    grown = grown | mask
    fabric = panel_fabric(image, islands, labels, job, px_per_cm)
    image, fill = fill_fabric(image, labels, grown, islands, job, px_per_cm, sleeve_print, fabric=fabric)
    res["metrics"]["fabric_fill"] = fill
    res.update({"_image": image, "_grown": grown, "_mask": mask, "_fabric": fabric})
    return res


#: The record entry of a plain back (``fill_plain_back``): no model, no answer file, no hub job.
PLAIN_BACK_SOURCE = "fabric"
PLAIN_BACK_REASON = "No fabric patch for the plain back: {reason}"


def fill_plain_back(front: dict, islands: dict, size: int, px_per_cm: float, detail: float | None) -> dict:
    """The BACK of a piece whose back view is plain (``is_plain_back``), with no hub job: the back islands and their
    bleed (``BLEED_CM``) tiled with the FRONT job's panel fabric — the same patch and base colour the sleeves and the
    neckband get (``front["_fabric"]``, ``panel_fabric``; ``tile_fill`` moves the tile's mean onto the front panel's
    base colour, so the side seams meet the same colour). ``front`` is the front job's ``post_job`` result ("ready",
    atlas frame). Returns a ``post_job``-shaped result: "ready" with ``_image`` / ``_grown`` / ``_mask`` for
    ``compose``, or "rejected" when no patch fits the front panel."""
    post = cut_texture_post
    labels = job_labels(islands, size, "back")
    mask = labels > 0
    fabric = front.get("_fabric") or panel_fabric(front["_image"], islands, job_labels(islands, size, "front"),
                                                  "front", px_per_cm)
    plain = {"detail": detail, "limit": PLAIN_BACK_DETAIL}
    names = sorted(str(i["name"]) for i in islands.get("islands", []) if job_of(str(i["name"])) == "back")
    if "skipped" in fabric:
        reason = PLAIN_BACK_REASON.format(reason=fabric["skipped"])
        return {"state": "rejected", "reason": reason, "accepted": False,
                "metrics": {"plain": plain, "failures": [reason], "zoom": None}}
    grown = post.dilate(mask, max(1, int(round(post.BLEED_CM * px_per_cm)))) | mask
    image, tinfo = post.tile_fill(front["_image"], grown, fabric["patch"], fabric["base"]["lab"])
    metrics = {"plain": plain, "failures": [], "zoom": None,
               "fabric_fill": {"islands": names, "patch": fabric["info"], "base": fabric["base"]["rgb"],
                               "shift": tinfo["shift"], "from": "front"}}
    return {"state": "ready", "reason": "", "metrics": metrics, "accepted": False,
            "_image": image, "_grown": grown, "_mask": mask}


def plain_back_entry(res: dict) -> dict:
    """The record entry of ``fill_plain_back``'s result."""
    return {"state": res["state"], "reason": res["reason"], "metrics": res["metrics"],
            "source": PLAIN_BACK_SOURCE, "reference": JOB_REFERENCE["back"], "prompt": "",
            "islands": list((res["metrics"].get("fabric_fill") or {}).get("islands") or [])}


def references(character_name: str, item_id: str, has_back_panel: bool) -> dict:
    """``_post_job``'s ``refs`` and the pre-fill: ONE ``garment_matte.cut`` of the item picture (BiRefNet,
    ``_item_matte``) for its base fabric colour, its detail and the colour match's fabric; the BACK VIEW's own detail
    (``back_detail``, its alpha the cut-out) for the back job — the back job's detail gate and the plain-back decision
    (``is_plain_back``) read it, never the item picture's. ``{"colour", "prefill", "detail": {"front", "back"},
    "fabric"}``."""
    post = cut_texture_post
    with Image.open(_item_path(item_id)) as it:
        item_rgba = np.asarray(it.convert("RGBA"))
    item = post.picture_reference(item_rgba, matte=_item_matte())
    detail = {"front": item["detail"], "front_cloth": item.get("detail_cloth")}
    if has_back_panel and back_view(character_name, item_id) is not None:
        detail["back"] = back_detail(character_name, item_id)
    return {"colour": item["colour"], "prefill": prefill_colour(item["colour"]), "detail": detail,
            "fabric": item["fabric"]}


def compose(results: dict, size: int, px_per_cm: float = 0.0) -> np.ndarray:
    """The one atlas from the jobs' post-processed images: white, then the FRONT job inside its grown area (islands +
    bleed), then the BACK job inside its grown area wherever the front's islands are not, then the back's own islands
    — an island's own pixels always beat the other job's bleed (the islands are disjoint). Last the background
    pockets near and between the grown areas are filled (``cut_texture_post.fill_pockets``, ``POCKET_CM``; none
    without ``px_per_cm``)."""
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
    if px_per_cm > 0 and order:
        grown = np.zeros((size, size), bool)
        for job in order:
            grown |= results[job]["_grown"] | results[job]["_mask"]
        out, _ = cut_texture_post.fill_pockets(out, grown, max(1, int(round(cut_texture_post.POCKET_CM * px_per_cm))))
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


def _item_params(item_id: str) -> dict:
    """The item's template params ({} without a template)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    return gt.params_of(get_item(item_id)) or {}


def composed_as_now(record: dict, item_id: str, params: dict | None = None) -> bool:
    """Whether a ready ``record`` was composed with the piece's options as they are now: its ``sleeve_print`` and
    the trims' colour of the item text (``trim_style``, stage "layers"). Otherwise ``recompose`` makes it again on
    the CPU from the stored answers (0 image jobs)."""
    if params is None:
        from app.core import garment_template as gt
        from app.models.inventory import get_item
        params = gt.params_of(get_item(item_id)) or {}
    return (str(record.get("sleeve_print") or "plain") == str(params.get("sleeve_print") or "plain")
            and record.get("trim_style") == trim_style_of(item_id))


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
        ppc = float(islands.get("px_per_cm") or record.get("px_per_cm") or 0.0)
        atlas = compose(results, size, ppc)
        if record.get("sleeve_print") != "picture":
            # stage "layers": the trims the item text gives a colour of their own (``trim_style``)
            atlas, record["trim_paint"] = paint_trims(atlas, islands, size, ppc, record.get("trim_style"))
        seam = cut_texture_post.seam_continuity(atlas, islands.get("seams") or [])
        cross = cut_texture_post.seam_continuity(atlas, cross_seams(islands))
        record.update({"state": "ready", "reason": "", "metrics": _summary_metrics(record["jobs"], seam, cross)})
        isl_mask = np.zeros((size, size), bool)
        for r in results.values():
            isl_mask |= np.asarray(r["_mask"], bool)
        record["metrics"]["bleed_streaks"] = cut_texture_post.bleed_streaks(
            atlas, isl_mask, max(1, int(round(cut_texture_post.POCKET_CM * ppc))) if ppc > 0 else 0)
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
    kind = item_kind(item_id)
    family, psha = prompt_family(kind), prompt_sha_of(kind)
    record: dict = {"islands_sha": pattern["islands_sha"], "cut_sig": pattern.get("cut_sig"), "state": "failed",
                    "reason": "", "metrics": {}, "jobs": {}, "px_per_cm": px_per_cm, "item_px": None,
                    "upscale": None, "prompt_sha": psha, "prompt_family": family,
                    "post_version": cut_texture_post.POST_VERSION,
                    "item_sha": _item_sha(item_id), "back_sha": "", "back_view": {"made": False, "jobs": 0},
                    "only": only or "", "sleeve_print": sleeve_print_of(item_id),
                    "trim_style": trim_style_of(item_id)}
    record["held"] = held_trims(kind, record["sleeve_print"])
    sig = csig(pattern["islands_sha"], record["item_sha"], "", psha)
    try:
        if "back" in parts:
            _set_progress(key, "back_view")
            record["back_view"] = _ensure_back_view(character_name, item_id)
            record["back_sha"] = back_sha(character_name, item_id)
        sig = csig(pattern["islands_sha"], record["item_sha"], record["back_sha"], psha)
    except Exception as e:  # noqa: BLE001 — the flow's failure is the record
        logger.warning("Cut texture %s %s: back view: %s", character_name, item_id, e)
        record.update({"csig": sig, "state": "failed", "reason": _failure_reason(e), "created_at": utc_now_iso()})
        _write_record(_file(_stem(character_name, item_id, sig), ".json"), record)
        return record
    record["csig"] = sig
    stem = _stem(character_name, item_id, sig)
    previous = read_record(character_name, item_id, sig)
    # a plain back view: the back is the front's fabric (``fill_plain_back``) — no back job, whatever ``only`` says
    plain = "back" in parts and is_plain_back(back_detail(character_name, item_id))
    record["back_plain"] = {"plain": bool(plain), "detail": back_detail(character_name, item_id) if "back" in parts
                            else None, "limit": PLAIN_BACK_DETAIL}
    reuse = reused_jobs(character_name, item_id, sig, parts, only=only)
    todo = [j for j in parts if j not in reuse and not (plain and j == "back")]
    stale = [_file(stem, ".atlas.png")] + [_file(stem, f".raw_{j}.png") for j in todo] \
        + [_file(stem, f".raw_{j}.a{a}.png") for j in todo for a in range(1, CUT_ATTEMPTS + 1)]
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
        from app.imagegen import routing as _routing
        stopped = False             # a job did not pass: no further image job is spent, re-used answers still post
        for job in parts:
            if plain and job == "back":
                continue            # filled from the front's fabric below
            if stopped and job not in reuse:
                continue
            template_png = _file(stem, f".template_{job}.png")
            _write_bytes(template_png, _png(job_template(islands, parts, job, size, fill=refs["prefill"],
                                                         held=record["held"], sleeve_print=record["sleeve_print"])))
            raw_png = _file(stem, f".raw_{job}.png")
            if job in reuse:
                answer = raw_png.read_bytes()
                entry = {k: v for k, v in reuse[job].items() if k not in ("metrics", "state", "reason")}
                force = bool(reuse[job].get("accepted"))
                if job == "front":
                    refs["halo"] = entry.get("prompt") == "decorated" and family == "top"
            else:
                _set_progress(key, job)
                # held trims (``held_trims``): the words name what the template shows — the model's parts only
                said = (split_islands(sent_islands(islands, job, record["sleeve_print"], drop=True))[job]
                        if record["held"] else parts[job])
                place = front_place(said) if job == "front" else ""
                main = main_words(said, job)
                found = place if family == "top" else (main["phrase"] if job == "front" else "")
                decorated = bool(found) and is_decorated(decor_detail(refs["detail"], _item_params(item_id)))
                plain_pieces = (prompt_sleeves(said, record["sleeve_print"]) if family == "top"
                                else prompt_plain_pieces(said, record["sleeve_print"]))
                if job == "front":
                    refs["halo"] = decorated and family == "top"     # ``busy_halo`` (stage "details")
                weave_words = (cut_texture_post.stripe_words(refs.get("front_weave"),
                                                             (refs.get("front_weave") or {}).get("axis"))
                               if job == "back" else cut_texture_post.WEAVE_WORDS[""])
                ep = edit_prompt(piece=name, side=job, decorated=decorated, front_place=place,
                                 pieces=prompt_pieces(said), layout=layout_words(said, family),
                                 sleeves=plain_pieces, family=family, main=main, weave=weave_words)
                seed = (int(sig[:8], 16) + (0 if job == "front" else 1)) % 2 ** 31
                ref = item_png if job == "front" else back_png
                attempts: list = []
                for attempt in _routing.gate_attempts(CUT_ATTEMPTS):
                    try:
                        answer, used, route, dialect, _prompt = _routed_render(
                            item_id, job, ep.render, template_png, ref, attempt_seed(seed, attempt))
                    except Exception as e:  # noqa: BLE001 — a failure is never retried: it stops the flow
                        attempts.append({"attempt": attempt, "state": "failed", "reason": _failure_reason(e)})
                        if attempt > 1:
                            # attempt 1's rejected answer stays the job's answer ("Use this answer" can take it)
                            logger.warning("Cut texture %s %s: %s attempt %d failed: %s", character_name, item_id,
                                           job, attempt, e)
                            break
                        record["jobs"][job] = {"state": "failed", "reason": _failure_reason(e),
                                               "reference": JOB_REFERENCE[job], "attempts": attempts}
                        raise
                    _write_bytes(_file(stem, f".raw_{job}.a{attempt}.png"), answer)
                    _write_bytes(raw_png, answer)
                    entry = {"backend": getattr(used, "name", ""), "routing": route_meta(route),
                             "dialect": dialect, "prompt": "decorated" if decorated else "plain",
                             "weave_words": weave_words,
                             "upsampler_on": _upsampler_on(used), "reference": JOB_REFERENCE[job],
                             "islands": [str(i["name"]) for i in said["islands"]], "attempt": attempt}
                    _set_progress(key, "post")
                    res = post_job(answer, islands, size, px_per_cm, job, refs, force=False,
                                   sleeve_print=record["sleeve_print"], held=record["held"])
                    attempts.append({"attempt": attempt, "backend": entry["backend"], "dialect": dialect,
                                     "routing": entry["routing"], "state": res["state"], "reason": res["reason"],
                                     "metrics": res["metrics"]})
                    if res["state"] == "ready":
                        break
                    if attempt < CUT_ATTEMPTS:
                        logger.info("Cut texture %s %s: %s attempt %d rejected on %s (%s) — attempt %d",
                                    character_name, item_id, job, attempt, entry["backend"], res["reason"],
                                    attempt + 1)
                entry["attempts"] = attempts
                record["jobs"][job] = _entry_from_post(entry, res)
                if res["state"] != "ready":
                    stopped = True
                    continue
                results[job] = res
                if job == "front":
                    refs["front_weave"] = res["metrics"].get("weave")
                continue
            _set_progress(key, "post")
            res = post_job(answer, islands, size, px_per_cm, job, refs, force=force,
                           sleeve_print=record["sleeve_print"], held=record["held"])
            record["jobs"][job] = _entry_from_post(entry, res)
            if res["state"] != "ready":
                stopped = True      # a rejected job stops the flow: the next job that needs a render is not spent
                continue
            results[job] = res
            if job == "front":
                refs["front_weave"] = res["metrics"].get("weave")
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
    if plain:
        _plain_back_into(record, results, islands, size, px_per_cm)
    for job in parts:
        record["jobs"].setdefault(job, {"state": "skipped", "reason": SKIPPED, "reference": JOB_REFERENCE[job]})
    return _finish(character_name, item_id, record, parts, results, islands, size, stem, apply_after=apply_after)


def _plain_back_into(record: dict, results: dict, islands: dict, size: int, px_per_cm: float) -> None:
    """A plain back (``fill_plain_back``) into the record and the results — once the front job is in; without it
    the back stays to ``_finish`` ("skipped" behind the front)."""
    if "front" not in results:
        record["jobs"].pop("back", None)        # ``_finish`` marks it "skipped" behind the front
        return
    res = fill_plain_back(results["front"], islands, size, px_per_cm, (record.get("back_plain") or {}).get("detail"))
    record["jobs"]["back"] = plain_back_entry(res)
    if res["state"] == "ready":
        results["back"] = res


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


def recompose(character_name: str, item_id: str, *, accept: str | None = None, attempt: int | None = None,
              apply_after: bool = True) -> dict:
    """The CPU path of "Use this answer" (``accept`` = the job whose shown answer the user puts on the figure, also a
    rejected one: it is marked ``accepted`` with the reason it overrode) and of a changed ``sleeve_print``
    (``accept`` None): every job of the current csig whose answer passed or was accepted is post-processed again from
    its raw file — no image job — and, when every job has one, the atlas is composed and applied. A job without an
    answer stays "skipped" (``NOT_MADE`` once the jobs before it are in): Run all renders exactly that one next.
    ``attempt`` (with ``accept``): the answer of that render attempt (``.raw_{job}.a{n}.png``, its backend / dialect /
    routing from the job's ``attempts``) becomes the job's answer first — "Use this answer" on attempt 1 after a
    rejected attempt 2, or the other way round.
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
        if attempt is not None:
            _take_attempt(record, stem, accept, int(attempt))
            entry = record["jobs"][accept]
        if not _file(stem, f".raw_{accept}.png").is_file() or entry.get("state") not in ("ready", "rejected"):
            raise NotReady(f"The {accept} job has no answer to use — redo it first")
    size = int(islands.get("atlas_px") or 2048)
    px_per_cm = float(islands.get("px_per_cm") or 0.0)
    record["sleeve_print"] = sleeve_print_of(item_id)
    record["trim_style"] = trim_style_of(item_id)
    record["held"] = held_trims(item_kind(item_id), record["sleeve_print"])
    _set_progress((character_name, item_id), "post")
    refs = references(character_name, item_id, "back" in parts)
    record["fabric"] = {"item": refs["colour"], "prefill": list(refs["prefill"]) if refs["prefill"] else None,
                        "detail": refs["detail"]}
    plain = "back" in parts and is_plain_back(refs["detail"].get("back"))
    record["back_plain"] = {"plain": bool(plain), "detail": refs["detail"].get("back"), "limit": PLAIN_BACK_DETAIL}
    results = {}
    for job in parts:
        if plain and job == "back":
            continue
        entry = dict(record["jobs"].get(job) or {})
        raw = _file(stem, f".raw_{job}.png")
        wanted = job == accept or entry.get("state") == "ready"
        if not wanted or not raw.is_file():
            continue
        force = job == accept or bool(entry.get("accepted"))
        if job == "front":
            refs["halo"] = entry.get("prompt") == "decorated" and record.get("prompt_family", "top") == "top"
        res = post_job(raw.read_bytes(), islands, size, px_per_cm, job, refs, force=force,
                       sleeve_print=record["sleeve_print"], held=record["held"])
        record["jobs"][job] = _entry_from_post(entry, res)
        if res["state"] == "ready":
            results[job] = res
    if plain:
        _plain_back_into(record, results, islands, size, px_per_cm)
    return _finish(character_name, item_id, record, parts, results, islands, size, stem, apply_after=apply_after)


def _take_attempt(record: dict, stem: Path, job: str, attempt: int) -> None:
    """Make render ``attempt``'s answer the ``job``'s answer (its raw file and its backend / dialect / routing / state
    from the job's ``attempts``); ``NotReady`` when that attempt has no answer."""
    entry = dict(record.get("jobs", {}).get(job) or {})
    tried = next((a for a in entry.get("attempts") or [] if a.get("attempt") == attempt), None)
    raw = _file(stem, f".raw_{job}.a{attempt}.png")
    if tried is None or not raw.is_file() or tried.get("state") not in ("ready", "rejected"):
        raise NotReady(f"Attempt {attempt} of the {job} job has no answer to use")
    _write_bytes(_file(stem, f".raw_{job}.png"), raw.read_bytes())
    entry.update({k: tried[k] for k in ("backend", "dialect", "routing", "state", "reason", "metrics") if k in tried})
    entry["attempt"] = attempt
    record["jobs"][job] = entry


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


def start_recompose(character_name: str, item_id: str, *, accept: str | None = None, attempt: int | None = None,
                    run=None) -> bool:
    """"Use this answer" (``accept`` = "front" / "back") or a changed sleeve option (``accept`` None): ``recompose``
    in a thread — CPU only, so neither the media switch nor the routing is asked. Checked synchronously: a ready
    cut, a record with that job's answer (``NotReady``), no other hub-job flow of the piece (``Busy``).
    False when this piece's cut already runs."""
    if accept is not None and accept not in JOBS:
        raise ValueError(f"job must be one of {', '.join(JOBS)}")
    _ready_pattern(character_name, item_id)
    if accept is not None and not (usable_answers(character_name, item_id).get(accept) or {}).get("can_use"):
        raise NotReady(f"The {accept} job has no answer to use — redo it first")
    if attempt is not None:
        if accept is None:
            raise ValueError("an attempt needs its job")
        sig = current_csig(character_name, item_id)
        entry = (read_record(character_name, item_id, sig).get("jobs") or {}).get(accept) or {} if sig else {}
        if not any(a.get("attempt") == attempt and a.get("state") in ("ready", "rejected")
                   for a in entry.get("attempts") or []) \
                or not _file(_stem(character_name, item_id, sig), f".raw_{accept}.a{attempt}.png").is_file():
            raise NotReady(f"Attempt {attempt} of the {accept} job has no answer to use")
    fn = run or recompose
    kwargs = {"accept": accept} if attempt is None else {"accept": accept, "attempt": int(attempt)}
    return _launch(character_name, item_id, lambda: fn(character_name, item_id, **kwargs), select=accept is not None)


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


def kind_has_back(params: dict | None) -> bool:
    """Whether a piece of these template params has back-job pieces (``BACK_PARTS``) before it is cut: a top (a bodice
    always has a back panel), trousers and boxers (back leg panels), briefs (the back panel), gloves (the palms), a
    bandeau (front / back); NOT tights (one island per leg, decision D2) nor a cupped bra (cups, gore, bands, straps —
    D4)."""
    p = params or {}
    kind = str(p.get("kind") or "")
    if kind == "tights":
        return False
    if kind == "bra":
        return str(p.get("cup_style") or "") == "bandeau"
    return True


def _estimate_jobs(character_name: str, item_id: str) -> int:
    """The image jobs of a flow whose pattern is not cut yet: the back view when missing, the item upscale when the
    picture is small, the front job and the back job — both of the latter only when the kind has back pieces
    (``kind_has_back``), and the back job only when the back view is not plain (``back_plain``; a missing back view
    counts it)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    side = _item_side(item_id)
    upscale = 1 if 0 < side < MIN_ITEM_SIDE else 0
    if not kind_has_back(gt.params_of(get_item(item_id))):
        return upscale + 1
    view = 1 if back_view(character_name, item_id) is None else 0
    back = 0 if not view and back_plain(character_name, item_id) else 1
    return view + upscale + 1 + back


def build_state(character_name: str, item_id: str, *, item: dict | None = None) -> dict:
    """What the Build has to do for the piece's texture from cut: ``{state, reason, jobs, estimate}`` —

    - ``off``: the piece does not want it (``texture`` not "cut", not a pattern kind, a strapless top, no parameters
      or no plain body — the drape step says those);
    - ``done``: a ready record of the current csig with its atlas, composed with the piece's sleeve option;
    - ``compose``: a ready record composed with the other sleeve option (``recompose``, CPU, 0 jobs);
    - ``failed``: the current cut failed, the item has no picture, or the current csig's record is "rejected" /
      "failed" — a cached failure: an automatic Build skips it; a MANUAL Build re-runs only what failed (``retry``):
      "cut" — the cut-only run once more (``garment_template_cut.ensure`` ``retry_failed``), then the image jobs
      (``jobs``, an estimate); "jobs" — only the jobs that did not pass are rendered again (``reused_jobs``; ``jobs``
      what that spends); "" — nothing a Build can re-run (no item picture);
    - ``due``: nothing made for the current csig yet (or the cut not made yet: ``estimate`` True, ``jobs`` from
      ``_estimate_jobs``).

    Read-only: no Blender, no hub job; never raises (a read error is ``off`` with the reason logged)."""
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    from app.models.inventory import get_item
    out = {"state": BUILD_OFF, "reason": "", "jobs": 0, "estimate": False, "retry": ""}
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
            return {**out, "state": BUILD_FAILED, "reason": cut["reason"], "retry": "cut",
                    "jobs": _estimate_jobs(character_name, item_id), "estimate": True}
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
            if composed_as_now(record, item_id, params):
                return {**out, "state": BUILD_DONE}
            return {**out, "state": BUILD_COMPOSE}
        if record.get("state") in ("rejected", "failed"):
            return {**out, "state": BUILD_FAILED, "reason": str(record.get("reason") or record["state"]),
                    "jobs": int(plan["total"]), "retry": "jobs"}
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
    (``build_state`` "failed") is only retried by a manual Build (``explicit``), and only what failed (``retry``): a
    failed cut is cut once more (``garment_template_cut.ensure`` ``retry_failed``), a rejected / failed record renders
    only the jobs that did not pass; a failure with nothing to re-run (no item picture) stays. The media switch and
    the routing are asked first (their reasons are the step's error); the cut is made or waited for; the piece is
    claimed (``_claim_for_build`` — a flow another click started is waited for, then its record decides); then
    ``generate`` / ``recompose`` with ``apply_after`` False (the Build assembles). The dialog's ``status`` reads the
    run like one of its own flows: "done" when a record came back (a rejected one says its reason in the record, not
    as a flow error), the error text only when the run raised. Never raises."""
    import time
    from app.core import garment_template_cut as gtc
    from app.core import piece_jobs
    from app.imagegen import routing as _routing
    from app.imagegen.base import media_generation_enabled
    deadline = time.monotonic() + wait_s
    st = build_state(character_name, item_id)
    if st["state"] in (BUILD_OFF, BUILD_DONE):
        return {"ok": True, "reason": st["reason"], "state": st["state"], "record": {}}
    if st["state"] == BUILD_FAILED and (not explicit or not st.get("retry")):
        return {"ok": False, "reason": st["reason"], "state": st["state"], "record": {}}
    if st["state"] != BUILD_COMPOSE:
        if not media_generation_enabled():
            return {"ok": False, "reason": MEDIA_OFF, "state": BUILD_FAILED, "record": {}}
        if not _routing.chain_for(CUT_OCCASION):
            return {"ok": False, "reason": BLOCKED_ROUTING, "state": BUILD_FAILED, "record": {}}
    _set_build_step(character_name, item_id, "cut")
    cut = gtc.ensure(character_name, item_id, timeout_s=max(1.0, deadline - time.monotonic()),
                     retry_failed=bool(explicit and st.get("retry") == "cut"))
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
        if st["state"] == BUILD_FAILED and (not explicit or not st.get("retry")):
            return {"ok": False, "reason": st["reason"], "state": st["state"], "record": {}}
        if st["state"] == BUILD_COMPOSE:
            record = recompose(character_name, item_id, apply_after=False)
        else:
            record = generate(character_name, item_id, apply_after=False)
        ok = record.get("state") == "ready"
        reason = "" if ok else str(record.get("reason") or record.get("state") or "failed")
        return {"ok": ok, "reason": reason, "state": BUILD_DONE if ok else BUILD_FAILED, "record": record}
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
            entry["released"] = False           # a Build owns it again (``build_release``)
            return False
        entry = {"result": None, "step": "", "explicit": explicit, "released": False}

        def work() -> None:
            res = run_for_build(character_name, item_id, explicit=explicit)
            with _lock:
                entry["result"] = res
                if entry["released"] and _build_runs.get(key) is entry:
                    _build_runs.pop(key, None)      # the Build that started it ended without joining it
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
        if entry is not None:
            entry["released"] = False
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


def build_release(character_name: str, item_id: str) -> bool:
    """The Build that pre-started the piece's run (``build_start``) ended WITHOUT joining it (it broke out between the
    drape and the cut_texture step: a stop, a pause, a superseded figure, an error). Its entry never outlives it: a
    finished run is dropped now, a running one drops itself when it ends (its record is written as usual — the next
    plan reads it). Without this the next Build's ``build_join`` would return the OLD result without running.
    True when an entry was released."""
    key = (character_name, item_id)
    with _lock:
        entry = _build_runs.get(key)
        if entry is None:
            return False
        if entry["thread"].is_alive():
            entry["released"] = True
        else:
            _build_runs.pop(key, None)
    return True


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
      ``option_stale`` whether the ready atlas was composed with the other option (``cut_info`` "option");
    - ``back_detail`` / ``back_plain`` / ``plain_back_limit`` — the back view's detail, whether it is plain (the back
      is then the front's fabric, no back job; None without a back view or a back panel) and the threshold."""
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
                "current": record.get("state") == "ready" and composed_as_now(record, item_id, params),
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
    if has_back(islands):
        out.update({"back_detail": back_detail(character_name, item_id),
                    "back_plain": back_plain(character_name, item_id), "plain_back_limit": PLAIN_BACK_DETAIL})
    else:
        out.update({"back_detail": None, "back_plain": None, "plain_back_limit": PLAIN_BACK_DETAIL})
    out.update({"answers": answers, "sleeve_print": sleeve_print,
                # the option's pieces: a top's sleeves, a fitted piece's small pieces (``TRIM_PARTS``); ``trim``
                # says which the dialog names
                "has_sleeves": any(part_of(str(i["name"])) in TRIM_PARTS for i in islands.get("islands", [])),
                "trim": "sleeves" if any(part_of(str(i["name"])) in SLEEVE_PARTS and "sleeve" in str(i["name"])
                                         for i in islands.get("islands", [])) or not islands.get("islands")
                else "pieces",
                "option_stale": record.get("state") == "ready" and not composed_as_now(record, item_id, params),
                # stage "layers": the trims' own colour read from the item text (None: the fabric fill)
                "trim_style": trim_style_of(item_id)})
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


# ----------------------------------------------------------------------------------------------- placket (phase C3)

def placket_of(item_id: str) -> tuple[str, int, str, str]:
    """The piece's (``placket``, ``buttons``, ``kind``, ``collar``) params ("none", 0, ... without them)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    p = gt.params_of(get_item(item_id)) or {}
    style = str(p.get("placket") or "none")
    return (style if style in gt.PLACKETS else "none", int(p.get("buttons") or 0), str(p.get("kind") or ""),
            str(p.get("collar") or "none"))


#: Stage "details": the button colour words of an item text — the trims' colours (``TRIM_COLOURS``) and the materials
#: a button is made of (sRGB).
BUTTON_MATERIALS = {"wooden": (128, 84, 48), "wood": (128, 84, 48), "horn": (92, 70, 52), "pearl": (236, 230, 216),
                    "metal": (170, 170, 176)}
_button_pic_cache: dict[tuple[str, int, int], dict | None] = {}


def button_text_colour(text: str) -> tuple[int, int, int] | None:
    """The buttons' colour as the item ``text`` names it, None without one. The text is cut into clauses (at ",",
    ";" and the words "with" and "and", as ``trim_style`` reads it) so the garment's own colour of "green shirt with
    white buttons" never reaches the buttons; in the clause naming "button(s)" the colour word (``TRIM_COLOURS``)
    nearest before the noun wins, else the material word (``BUTTON_MATERIALS``) nearest before it, else the first
    of either after it ("buttons in brass"). "black tailored blazer, fitted, two silver buttons" -> silver,
    "brown wooden buttons" -> brown, "wool coat with horn buttons" -> horn."""
    low = (text or "").lower()
    for clause in (c for part in re.split(r"[,;]", low) for c in re.split(r"\b(?:with|and)\b", part)):
        words = _TRIM_WORD.findall(clause)
        at = next((i for i, w in enumerate(words) if _noun(w, ("button",))), None)
        if at is None:
            continue
        before = words[:at]
        colour = next((w for w in reversed(before) if w in TRIM_COLOURS), None)
        if colour:
            return tuple(TRIM_COLOURS[colour])
        material = next((w for w in reversed(before) if w in BUTTON_MATERIALS), None)
        if material:
            return BUTTON_MATERIALS[material]
        for w in words[at + 1:]:
            if w in TRIM_COLOURS:
                return tuple(TRIM_COLOURS[w])
            if w in BUTTON_MATERIALS:
                return BUTTON_MATERIALS[w]
    return None


def button_rgb(item_id: str, character_name: str = "", csig: str = "") -> tuple[list[int] | None, str]:
    """The painted buttons' colour (stage "details"): the item TEXT's (``button_text_colour``), else the item
    PICTURE's (``cut_texture_post.picture_buttons``, cached by the file's stat) — the cut's own upscaled picture
    (``<stem>.item.png`` of ``csig``, the one the front job saw) when there is one: on Dario's 392 x 512 shirt picture
    the buttons are ~5 px and found at no analysis size reliably, on its 1024 px upscale at 512, 768 and 1024 —,
    else None (a shade of the fabric, ``button_colours``). ``(rgb, source)`` with source "text" / "picture" / ""."""
    from app.models.inventory import get_item
    said = button_text_colour(str((get_item(item_id) or {}).get("prompt_fragment") or ""))
    if said is not None:
        return list(said), "text"
    path = _file(_stem(character_name, item_id, csig), ".item.png") if character_name and csig else None
    if path is None or not path.is_file():
        try:
            path = _item_path(item_id)
        except NotReady:
            return None, ""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _button_pic_cache:
        with Image.open(path) as im:
            rgba = np.asarray(im.convert("RGBA")).astype(np.float64)
        rgb = rgba[..., :3] * (rgba[..., 3:] / 255.0) + 255.0 * (1.0 - rgba[..., 3:] / 255.0)  # flattened on white
        _button_pic_cache[key] = cut_texture_post.picture_buttons(rgb)
    found = _button_pic_cache[key]
    return (list(found["rgb"]), "picture") if found else (None, "")


def placket_key(item_id: str, character_name: str = "", csig: str = "") -> str:
    """The assembly key part of a piece's painted placket ("" without one): a changed style, button count, button
    colour (``button_rgb``) or ``cut_texture_post.PLACKET_VERSION`` re-assembles on the CPU, the record's atlas and
    csig stay."""
    style, buttons, _, _ = placket_of(item_id)
    seams = f":seams{cut_texture_post.SEAM_VERSION}" if _has_seams(item_id) else ""
    if style == "none":
        return seams
    colour = button_rgb(item_id, character_name, csig)[0] if style == "buttons" else None
    tint = "-" + "".join(f"{int(v):02x}" for v in colour) if colour else ""
    return f":placket{cut_texture_post.PLACKET_VERSION}-{style}-{buttons}{tint}{seams}"


def _has_seams(item_id: str) -> bool:
    """Corset v3: whether the piece's cut carries painted seam lines (a strapless top: ``corset_darts.seam_lines``)."""
    from app.core import garment_template as gt
    from app.models.inventory import get_item
    params = gt.params_of(get_item(item_id))
    return bool(params) and gt.strapless_top(params)


def placket_atlas(character_name: str, item_id: str, atlas: bytes) -> tuple[bytes, dict | None]:
    """Plan group B, C3 (B10-B13): the composed cut atlas with the piece's placket painted along the cut's
    ``marks.json`` lines (``cut_texture_post.draw_placket``) — drawn at assembly, so switching the placket or the
    button count is a CPU re-assembly without an image job. Unchanged (info None) without a placket, without a ready
    cut or without a marks file (a cut that wrote no line; an old top cut is cut once more for it, B11)."""
    style, buttons, kind, collar = placket_of(item_id)
    seams = _has_seams(item_id)
    if style == "none" and not seams:
        return atlas, None
    try:
        pattern = _ready_pattern(character_name, item_id)
    except NotReady:
        return atlas, None
    ipath = Path(pattern["islands_path"])
    mpath = ipath.with_name(ipath.name[:-len(".islands.json")] + ".marks.json")
    if not mpath.is_file():
        return atlas, {"style": style, "skipped": "no marks"}
    islands = json.loads(ipath.read_text(encoding="utf-8"))
    marks = json.loads(mpath.read_text(encoding="utf-8")).get("lines") or {}
    with Image.open(io.BytesIO(atlas)) as im:
        rgb = np.asarray(im.convert("RGB"))
    size = rgb.shape[0]
    labels = rasterise_islands(islands, size)
    ids = island_ids(islands)
    masks = {n: labels == ids[n] for n in {str(v.get("island")) for v in marks.values()} if n in ids}
    colour, source = (button_rgb(item_id, character_name, current_csig(character_name, item_id) or "")
                      if style == "buttons" else (None, ""))
    px_per_cm = float(islands.get("px_per_cm") or 0.0)
    info = {"style": style}
    if seams:
        # corset v3: the sewn seams first, the placket over them
        rgb, sinfo = cut_texture_post.draw_seams(rgb, masks, marks, px_per_cm=px_per_cm)
        info.update(sinfo)
    out, pinfo = cut_texture_post.draw_placket(rgb, masks, {k: v for k, v in marks.items()
                                                            if not k.startswith("seam_")},
                                               kind=kind, style=style, buttons=buttons, px_per_cm=px_per_cm,
                                               lapel=collar == "lapel", button_rgb=colour)
    info.update(pinfo)
    if colour:
        info["button_rgb"], info["button_source"] = colour, source
    return _png(Image.fromarray(out, "RGB")), info
