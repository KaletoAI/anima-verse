"""Smoke: "texture from cut" — the clean island template and the debug pattern sheet (``app/core/garment_cut_texture.py``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_cut_texture.py

No server, no world DB, no hub job: the render part is numpy + PIL on an ``islands.json`` payload. The synthetic
T-shirt payload of [2]/[3] is built through ``app/blender/scripts/uv_pattern.py`` (imported through ``sys.path`` the
way ``scripts/smoke_uv_pattern.py`` does; the core module itself never imports it). Every expectation is derived by
hand below.

[1] Raster: one axis-aligned 100 x 200 px rectangle island, corners on integer pixels (x 20..120, y 20..220) in a
    256 canvas, two fan triangles. A pixel (row i, column j) belongs to a triangle when its CENTRE (j + 0.5, i + 0.5)
    is inside; columns 20..119 (20 <= j + 0.5 < 120) and rows 20..219 -> the mask count is exactly 100 * 200 =
    20 000. The render: the centre pixel (row 120, column 70) is FILL, the canvas corner (0, 0) is white, the pixel
    just inside the left edge (row 120, column 20) is LINE; the outline is drawn INSIDE the mask (mask minus its
    2 px erosion), so the non-white count is exactly 20 000 and the LINE count is 20 000 - 96 * 196 = 1 184. The
    image is square (256 x 256), RGB.
    Half-open edges: a 10 x 10 square whose corners sit ON pixel centres ((0.5, 0.5) .. (10.5, 10.5)) covers
    exactly 10 * 10 = 100 pixels (top-left rule: the centres on its left and top edges are in, those on its right
    and bottom edges are out; its diagonal centres (i = j) are counted once): pixel (0, 0) in, (10, 10) out.
    Labels: islands "front" and "back" -> id = 1 + sorted name index: back = 1, front = 2; 0 = background.
[2] The render of the synthetic T-shirt payload (the five boxes of smoke_uv_pattern [7]: front 50 x 47, back
    50 x 45, sleeves 34 x 25, band 44 x 4 cm, margin 1.5 -> 19.59 px/cm; 4-connected regions) has exactly 5 connected
    non-white regions (the islands are >= 1.5 cm = 29 px apart) and 5 connected FILL regions (each island's FILL is
    its 2 px eroded interior, one rectangle; the band is 4 * 19.59 = 78 px high, so its interior survives).
[3] Debug pattern sheet (user request 2026-11-20): the same payload. 5 distinct pastel fill colours, each covering
    a large share of its island (>= 50 % of the island's mask pixels: text, arrow and outline take less). The front
    box's label text names "Front" and its bbox size: 50 * 19.59 = 979.5 px / 19.59 = 50.0 cm wide, 47 * 19.59 =
    920.73 px / 19.59 = 47.0 cm high (+-0.1). A sleeve label carries its cap height when the payload has one
    (sleeve_l -2.0 -> "cap -2.0 cm"). Seam letters: a payload with two seams gives letters A and B, each on both of
    its sides. The footer reads "19.59 px/cm · atlas 2048²". The sheet is never the model template: it differs
    from ``render_template`` of the same payload.
[4] Occasion + prompt file (plan Task 6): ``CUT_OCCASION`` / ``CUT_USE_CASE`` are "garment_cut_texture" and the
    occasion is in the catalog. The front prompt (the short plain one since the prompt test 2026-11-21) renders for
    piece "T-shirt": it names "T-shirt", carries "the first image" and "the second image" and no Jinja leftovers
    ("{{", "{#"). After ``edit_prompt.normalise`` (two slots) with model "p-h3-image" it contains "<Picture 1>" and
    "<Picture 2>" and no "first image"/"second image"; with "qwen-edit" (ordinal) it is byte-identical. The back prompt reads
    "the fabric on the back of the T-shirt" and names no panel.
    ``PROMPT_SHA`` is the md5 of the three shipped files joined by NUL in ``PROMPT_FILES`` order (32 hex).
[5] A missing variable raises (StrictUndefined): the plain front file through ``edit_prompt.from_template`` with
    ``piece`` only (no ``pieces`` for its subject section) raises ``jinja2.exceptions.UndefinedError``.
[6] ``prompt_compose.compose(use_case="garment_cut_texture", subject=<rendered>, backend=<model "P-H3-Image",
    image_family "natural">)``: the use case has empty style / negative / instruction for both families, so the
    prompt is the rendered text byte-identical, the negative is "" and there are no warnings (the prompt opens no
    sentence or clause with "no"/"without" — the negation guard moves nothing — and has no mid-sentence "no").
    Same for image_family "keywords".

Task 8 — the job (``generate`` / ``start`` / ``status`` / ``item_source``), stubbed: ``current_pattern`` returns a ready
CUT whose islands are the [2] payload (cut sig "cut0"; ``current_drape`` a ready drape of the same islands for the
figure's ``cut_info``); the routes' ``garment_template_cut.schedule`` is a counter; ``routing.run_routed`` calls ``render`` once with a fake two-slot P-H3 backend
(or raises); ``get_image_service`` is a counter stub (upscale x4, ``run_on_backend`` / ``run_on_backend_channel`` call
straight through); ``inventory.get_item_image_path`` serves fixture files; the item matte is key-only (no BiRefNet).
[8.1] The fake backend answers the template it was given with every island pixel set to (150, 40, 40) (the item's
    fabric colour, a 1200 x 1100 RGBA picture with a (150, 40, 40) block on transparent): ``state`` "ready", IoU >= 0.98
    (the answer IS the mask, so the registration finds the identity map: IoU 1.0), ``.atlas.png`` exists at 2048 x
    2048; colour match moves nothing (atlas mean = fabric mean -> dE 0, the centre of the front island stays
    (150, 40, 40) +-2). ``csig`` = md5("|".join([islands sha, item sha, PROMPT_SHA, str(cut_texture_post.POST_VERSION)]))[:12]; the
    two references are file PATHS (str) in the order template, item; the front prompt (the short plain one: the
    fixture item has no detail) says "T-shirt" once ("the fabric of the T-shirt in <Picture 2>", the picture_edit
    section — the fake backend's model is P-H3-Image) (formerly: 4 times (made
    from the front of the T-shirt / the sewing pattern of the T-shirt / the plain fabric colour of the T-shirt / A
    plain T-shirt stays plain); ``run_routed`` got the occasion, has_ref=True
    and the service's pool; the model is P-H3 without ``use_prompt_upsampler: false`` -> ``upsampler_on`` True;
    ``figure.invalidate`` ran once; the record keeps ``routing`` = route_meta (occasion garment_cut_texture,
    position 1).
[8.2] A white answer (the [8.1] record removed first, so no passed answer is re-used — [12.12]): ``rejected``, reason
    "coverage 0.00 < 0.97"; the raw answer is kept, no atlas — the atlas of [8.1] (same csig) is gone, so a record
    never sits next to an atlas it did not make. ``figure.invalidate`` runs once more (the Build's plan reads the
    rejection), no assembly is scheduled.
[8.3] ``run_routed`` raises NoRouteError("garment_cut_texture", []) (its text points to /admin/settings -> Media
    Generation -> Routing): ``failed``, the reason contains "Routing"; no ``.raw.png`` / ``.atlas.png``, the record
    and the two input PNGs (template, item) exist. ``start`` with an empty ``chain_for`` raises NoRouteError before
    any thread or file (cut dir has no file of that item, no running entry); with media off it raises
    MediaGenerationDisabled; without a ready drape (or one without islands) it raises ``NotReady``.
[8.4] ``run_routed`` raises MediaGenerationDisabled: ``failed``, the reason contains "Media generation is off".
[8.5] ``socket.create_connection`` is replaced for the whole smoke and counts every attempt: 0 at the end.
[8.6] ``item_source``: a 300 x 256 item -> the (stubbed) upscaler runs once (status "applied", 1200 x 1024 out);
    1200 x 1100 -> not called ("not_needed", size kept); an upscaler that fails -> Lanczos to a 1024 long side
    ("lanczos"); BackendBusyError / MediaGenerationDisabled are re-raised.
[8.7] ``start`` runs ``generate`` in a thread: with a white answer the status ends not running, the record is
    "rejected", and a second ``start`` while running answers False.

Task 9 — the atlas assignment (``garment_template.texture`` / ``cut_info`` / ``atlas_for`` / ``texture_warning``,
``garment_assembly._state`` / ``_apply_cut_atlas``, ``figure_build._template_row``), same stubs; the drape record is a
dict whose ``islands.sha256`` is the [2] payload's sha.
[9.1] ``PARAM_SPEC["texture"]`` = ("choice", ("projection", "cut"), "projection"), a ``top`` field (since group B
    phase C a jacket's too: it keeps "cut"), an unknown value is an error; ``TEXTURE_ONLY`` = ("fly", "texture",
    "sleeve_print", "placket", "buttons") (the placket is painted, B10), so a top's ``tsig``
    is the same for texture "projection" and "cut".
[9.2] ``generate`` with the filled answer -> ready; with the item's texture "cut", ``atlas_for`` returns the
    ``.atlas.png`` bytes and ``{texture "cut", csig, cut_state "ready", metrics (IoU >= 0.98), px_per_cm 19.59}``;
    texture "projection" -> (None, "off"); a drape record without ``islands`` (a grid kind) -> (None, "off"). While the
    cut atlas is in use the projection bake's warning is not shown (``texture_warning({coverage 0.43}, info)`` None:
    the projection is not what the figure shows).
[9.3] The drape's islands sha changed -> no record for the new csig, a ready one for the old -> "stale", texture
    "projection", the warning's ``cut.text`` "Texture from cut is out of date — make it again (1 image job)" (the bake
    flags stay false on a good bake). Only the drape's ``tsig`` changed (a re-rendered piece-only view, same islands)
    -> still "cut", same csig. An item with no cut record at all -> "missing", which is not a warning.
[9.4] Item "shirt" (its current csig's record is the [8.2] rejection) -> "rejected" with reason "coverage 0.00 <
    0.97"; the warning's ``cut`` names it. ``_template_row`` (drape_state / current_base stubbed): ``metrics.cut.state``
    "rejected" with the reason, ``metrics.texture`` stays the projection's source ("views"); for "shirt9"
    ``metrics.texture`` "cut", ``metrics.cut`` {state "ready", reason, iou >= 0.98, de_after, px_per_cm 19.59}, no
    warning, ``cost.hub_jobs`` 0.
[9.5] ``garment_assembly._state`` of the template piece: ``texture`` "projection", then "cut:<csig>" once the item
    says "cut"; the two entries differ only in ``texture`` (the GLB sha256 is the same file's). ``_apply_cut_atlas``
    puts the atlas bytes (mime image/png) on the mesh with "cut" and leaves the GLB's image with "projection".
Task 10 — the routes (``app/routes/figure.py``, called as functions with the same stubs) and the dialog's backend
rules.
[10.1] ``GET …/cut`` of "shirt9" (texture "cut", the ready record of [9.2]): ``csig`` = c9, ``record.state`` "ready",
    ``can_generate`` True, ``blocked_reason`` "", ``upscale`` False (the item is 1200 x 1100 >= 1024), and the three
    picture URLs ``…/cut/<kind>.png?v=<c9>`` for every kind of ``CUT_FILES`` (both jobs' templates, references and
    answers, and the atlas); ``pattern_url`` = ``…/pattern.png?v=<islands sha[:12]>``.
    "tiny" (300 x 256) -> ``upscale`` True (the button says "+1 upscale").
[10.2] Blocked reasons, in this order of precedence: a piece without a cut -> ``garment_template_cut.NOT_CUT`` (the
    GET schedules the cut: one ``garment_template_cut.schedule`` call);
    media off -> "Media generation is off"; an empty chain -> "Routing chain for 'Garment — texture from cut' is empty
    — set it in /admin/settings → Media Generation → Routing" (``can_generate`` False each time).
[10.3] ``POST …/cut/generate``: an empty chain -> HTTP 503 whose detail contains "Routing"; media off ->
    ``MediaGenerationDisabled`` propagates (409 through the global handler); no cut -> HTTP 400; with all in
    place it starts (the answer carries ``running`` True), a second POST while it runs -> HTTP 409.
[10.4] ``GET …/cut/atlas.png`` of "shirt9" -> 200, the atlas file's bytes; every other kind of ``CUT_FILES`` too; an unknown
    kind -> 404; "shirt4" (nothing made) -> 404.
[10.5] ``GET …/pattern.png`` of "shirt9" -> 200, a PNG 2048 px wide (the atlas; its footer strip below) cached beside the cut
    as ``templates/cut/shirt9_<cut sig>.pattern.png`` (the fixture's cut sig "cut0"); a second GET does not render
    again (render count 1); a piece without a cut -> 404.
[10.6] User finding 2026-11-20: the template dialog's source picture is the ITEM picture only (``source`` "item",
    ``/inventory/items/<id>/image``) — even when a worn front view exists on disk; an item without a picture -> "".
[10.7] User finding 2026-11-20: with texture "cut" the piece-only views are not due — ``garment_template_views.status``
    of a SHEER top: texture "projection" -> required True, ``hub_jobs`` 2; texture "cut" -> ``optional`` True,
    required False, ``hub_jobs`` 0, ``max_jobs`` 0. ``texture_sources`` of that sheer top without views: {} with
    "projection" (blocked: SHEER_NEEDS_VIEWS from ``key_for``), the item picture ("item_image") with "cut";
    ``piece_progress``'s picture step then carries no ``hub_jobs``.

[12] The rework after the user's Dario test (2026-11-20). Hand-derived on the [2] T-shirt (sorted names give the label
    ids back=1, band=2, front=3, sleeve_l=4, sleeve_r=5):
[12.1] ``split_islands``: back job = [back], front job = [band, front, sleeve_l, sleeve_r] (sleeves go with the front).
    The back template's non-white pixels are exactly ``labels == 1``, the front template's exactly ``labels >= 2``;
    disjoint, and their counts add up to ``labels > 0``. A pattern without "back" has the front job only; "back_2"
    (a split back panel) goes with the back job.
[12.2] Seams on {front, back, back_2, sleeve_l} with seams 0 front|back, 1 sleeve_l|front, 2 back|back_2: the front
    job keeps [1], the back job [2]; ``cross_seams`` = [0].
[12.3] ``generate`` -> two image calls; the front prompt is the plain one in the P-H3 dialect ("Edit <Picture 1>.
    Texture the sewing pattern"), the back
    prompt "the fabric on the back of"; both name no panel (prompt test 2026-11-21). The back job runs ZOOMED: its
    ``metrics.zoom`` is ``job_frame`` (k > 1), the front's None, and the back template's non-white pixels are the
    atlas back island's pixel count times k^2 (+-3 %: area scales with the square, edges round); per-job coverage keys back {1}, front
    {2..5}; Picture 2 of the back job is the back view (40, 40, 150) on white; the atlas centre of the back island is
    (150, 40, 40) +-2 (colour-matched to the item); the summary IoU is the worse job's.
[12.4] ``compose`` on 20 x 20: front island cols 2..7 grown 0..9 (red), back island cols 10..15 grown 8..17 (blue);
    front first, back outside the front island, then each island -> row: 8 x r, 10 x b, 2 x w.
[12.5] A white back answer: "rejected", reason "Back: coverage 0.00 < 0.97", both raw answers kept, no atlas.
[12.6] ``only="back"`` -> 1 image call with the back references, ready; ``only="front"`` without a back answer of
    this csig -> 2 calls.
[12.7] No back view: ``job_plan`` = {back_view 1, upscale 0, front 1, back 1, total 3, max 6 (3 + the view's second
    attempt 1 + attempt 2 of each texture job 2)}; ``generate`` renders the
    view once (VIEW_JOBS + ("mk1", "back")) and keys the cut with it (csig != the csig without a back view); after it
    the plan totals 0 (every answer passed; each Redo 1); the tiny item adds +1 upscale; a refused view -> "failed" with "back view was refused", 0 image
    calls.
[12.8] ``piece_jobs``: a second claim returns the holder's reason; a view (core and route: 409), Use this and Remove
    (route: 409) while the cut runs; the cut (core and route: 409) while a view runs, and the dialog names the view's
    reason; four racing ``start`` calls -> exactly one True; the claim is released when the flow ends.
[12.9] Cut-first (2026-11-21): ``dialog_state.blocked_reason`` per CUT state (``current_pattern``): ready "", missing
    NOT_CUT, cutting CUTTING (and ``cutting`` True, no plan), failed its CUT_FAILED text, blocked its own reason
    (NO_PATTERN); a ready cut while the Build drapes the piece, with no drape and not worn -> "" (the drape is never
    asked); ready -> plan total 2, ``has_back`` True, ``cut_at`` the cut's stamp.
[12.10] ``start`` sets texture "cut" (``set_params``) and, on ready, invalidates the figure once and schedules one
    assembly; the dialog then reads ``applied`` and ``current`` True; the views payload: ``hub_jobs`` 0, ``cut_uses``
    ["back"].
[12.11] ``cut_stand_in``: texture "cut" and a drape whose tsig differs only by ``texture_sha`` (tex0 vs tex1) ->
    "ready", ``stand_in`` True, the old tsig; "projection" -> missing; another lower layer -> missing; a record
    without ``texture_sha`` -> missing.
[12.12] Review finding 2026-11-20: the reuse rule (``reused_jobs``) is ONE rule for ``generate`` and ``job_plan``. Back
    rejected: Run all = 1 (front 0, back 1, reused ["front"]), Redo back 1, Redo front 2 (the back answer did not
    pass, nothing to keep); Run all then makes exactly 1 image call (the back template) -> ready; all passed -> Run
    all 0 ("current"), each Redo 1. Front rejected (the back "skipped"): Run all 2, Redo back 2, Redo front 2.
[12.13] Review finding 2026-11-20: an old drape record without ``texture_sha`` that is ready by its exact key; the
    flow renders the missing back view (a fake ``generate`` that publishes through the real ``_publish``): the
    record gets ``texture_sha`` = md5(sha(item), sha(item)) (the item picture on both sides, the sources before the
    view), and afterwards ``drape_state`` is "ready" with ``stand_in`` and the old tsig. Control: the same with the
    stamp switched off -> "missing" (the piece would drop off). ``remove`` stamps too; a stamped record is not
    written again.
[13] User test 2026-11-21 (Kai: an invented colour; no way to accept a shown answer):
[13.1] The item is the (150, 40, 40) block: its base fabric colour is exactly that (uniform -> the median), so the
    front template's front-island centre is (150, 40, 40) +-1 (Lab round trip) and the outline is that colour x 0.6
    (its L* 34.3 >= 30): (90, 24, 24). An answer that fills the islands with (40, 150, 40): ΔE00 to the item > 20 -> the
    front job "rejected" with "colour ΔE00 …", the detail gate passes (both uniform: 0 <= 0.04), the back not spent;
    2 image calls — the rejected front is rendered a second time (``CUT_ATTEMPTS`` 2; the fake chain has one entry,
    so attempt 2 runs on the same backend with seed + 1000, and is rejected the same way).
[13.2] ``dialog_state.answers``: front can_use (its answer exists), back not (none); Use this answer on the back is
    refused (NotReady). ``recompose(accept="front")``: 0 image calls, the front "ready" + accepted with the colour
    reason it overrode, the back "skipped" with ``NOT_MADE``, the record "rejected" "Back: <NOT_MADE>", nothing
    applied; ``job_plan`` = 1 (back), reused ["front"].
[13.3] Run all: exactly 1 image call (the back), "ready", the front still accepted (re-posted with force), the atlas
    written, one assembly scheduled; ``cut_info`` texture "cut".
[13.4] ``start_recompose`` runs the (stubbed) recompose once in its thread with accept "front".
[13.5] ``set_sleeve_print("picture")``: stored (fake set_params), a re-compose started (accept None); before it runs
    ``cut_info`` says "option" and the dialog ``option_stale`` True / ``current`` False; ``recompose()`` then: 0 image
    calls, the record's sleeve_print "picture", ``cut_info`` "cut", and the front job's fabric fill covers only the
    band (the sleeves are the model's now). "glitter" -> ValueError.
[13.6] Review finding 2026-11-21: a fresh item, both jobs pass (2 image calls, "ready"). Redo front with the green
    answer: 2 image calls (attempt 1 and 2, both rejected), the front "rejected", the back re-used from its raw file (0 calls) and still "ready" — not
    "skipped" — and its raw file on disk; the dialog offers Use this answer for both. ``recompose(accept="front")``:
    0 image calls, "ready", the atlas written, one assembly scheduled; ``job_plan`` then 0 with both reused.
"""
import os
import re
import sys
import tempfile
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "app" / "blender" / "scripts"))
_tmp = tempfile.mkdtemp(prefix="smoke_cut_tex_")
os.environ.setdefault("STORAGE_DIR", os.path.join(_tmp, "world"))
os.environ.setdefault("INSTANCE_DIR", os.path.join(_tmp, "instance"))

# [8.5] the outbound guard: any network connection attempt during the whole smoke fails (and is counted)
import socket  # noqa: E402

OUTBOUND = []


def _no_outbound(*a, **k):
    OUTBOUND.append(a[:1])
    raise OSError("smoke_garment_cut_texture: outbound connection refused")


socket.create_connection = _no_outbound

import uv_pattern as up  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def regions(mask):
    """4-connected component count of a boolean mask."""
    seen = np.zeros_like(mask, bool)
    h, w = mask.shape
    n = 0
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        n += 1
        seen[i0, j0] = True
        q = deque([(i0, j0)])
        while q:
            i, j = q.popleft()
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    q.append((a, b))
    return n


def rgb_eq(arr, colour):
    return np.all(arr == np.array(colour, np.uint8), axis=-1)


# [1] raster
rect = {"name": "front", "part": 1, "verts_px": [[20, 20], [120, 20], [120, 220], [20, 220]],
        "tris": [[0, 1, 2], [0, 2, 3]], "loops_px": [[[20, 20], [120, 20], [120, 220], [20, 220]]],
        "bbox_px": [20, 20, 120, 220]}
pl1 = {"version": 1, "atlas_px": 256, "px_per_cm": 10.0, "margin_cm": 1.5, "islands": [rect], "seams": []}
m1 = gct.island_mask(pl1, 256)
check("[1] mask count 20 000", int(m1.sum()) == 20000, int(m1.sum()))
img1 = gct.render_template(pl1)
a1 = np.asarray(img1)
check("[1] square RGB 256", img1.size == (256, 256) and img1.mode == "RGB", (img1.size, img1.mode))
check("[1] centre is FILL", tuple(a1[120, 70]) == gct.TEMPLATE_FILL, tuple(a1[120, 70]))
check("[1] corner is white", tuple(a1[0, 0]) == gct.BACKGROUND, tuple(a1[0, 0]))
check("[1] just inside the left edge is LINE", tuple(a1[120, 20]) == gct.TEMPLATE_LINE, tuple(a1[120, 20]))
nonwhite = int((~rgb_eq(a1, gct.BACKGROUND)).sum())
check("[1] non-white count 20 000 (outline inside the mask)", nonwhite == 20000, nonwhite)
nline = int(rgb_eq(a1, gct.TEMPLATE_LINE).sum())
check("[1] LINE count 1 184", nline == 20000 - 96 * 196, nline)
check("[1] only FILL, LINE, white", nonwhite == nline + int(rgb_eq(a1, gct.TEMPLATE_FILL).sum()))

sq = {"name": "front", "part": 1, "verts_px": [[0.5, 0.5], [10.5, 0.5], [10.5, 10.5], [0.5, 10.5]],
      "tris": [[0, 1, 2], [0, 2, 3]]}
msq = gct.island_mask({"atlas_px": 16, "islands": [sq]}, 16)
check("[1] half-open: 10 x 10 square on pixel centres covers 100", int(msq.sum()) == 100, int(msq.sum()))
check("[1] half-open: top-left in, bottom-right out", bool(msq[0, 0]) and not bool(msq[10, 10])
      and not bool(msq[0, 10]) and not bool(msq[10, 0]))
two = {"atlas_px": 64, "islands": [
    {"name": "front", "part": 1, "verts_px": [[2, 2], [20, 2], [20, 20], [2, 20]], "tris": [[0, 1, 2], [0, 2, 3]]},
    {"name": "back", "part": 2, "verts_px": [[30, 2], [50, 2], [50, 20], [30, 20]], "tris": [[0, 1, 2], [0, 2, 3]]}]}
lab = gct.rasterise_islands(two, 64)
check("[1] labels: uint8, back = 1, front = 2, background 0",
      lab.dtype == np.uint8 and lab[10, 40] == 1 and lab[10, 10] == 2 and lab[40, 40] == 0
      and set(np.unique(lab).tolist()) == {0, 1, 2}, np.unique(lab).tolist())
check("[1] label ids", gct.island_ids(two) == {"back": 1, "front": 2}, gct.island_ids(two))


# [2] synthetic T-shirt payload through uv_pattern
def tshirt_payload(caps=None):
    boxes = {"front": (50, 47, 1), "back": (50, 45, 2), "sleeve_l": (34, 25, 3), "sleeve_r": (34, 25, 4),
             "band": (44, 4, 5)}
    xyz, faces, part, uvm = [], [], [], {}
    for k, (name, (w, h, p)) in enumerate(boxes.items()):
        o = len(xyz)
        w_m, h_m = w / 100.0, h / 100.0
        xyz += [(0, k, 0), (w_m, k, 0), (w_m, k, h_m), (0, k, h_m)]
        faces.append((o, o + 1, o + 2, o + 3))
        part.append(p)
        uvm[name] = np.array([(0, 0), (w_m, 0), (w_m, h_m), (0, h_m)], float)
    xyz = np.array(xyz, float)
    isl = up.split_islands(len(xyz), faces, np.array(part), set(), xyz=xyz)
    return up.islands_payload(isl, uvm, xyz, 2048, 1.5, cap_heights=caps)


pl2 = tshirt_payload({"sleeve_l": -2.0})
check("[2] payload: 5 islands at 19.59 px/cm", len(pl2["islands"]) == 5 and abs(pl2["px_per_cm"] - 19.59) < 1e-9,
      ([i["name"] for i in pl2["islands"]], pl2["px_per_cm"]))
img2 = gct.render_template(pl2)
a2 = np.asarray(img2)
check("[2] square 2048", img2.size == (2048, 2048), img2.size)
nw2 = ~rgb_eq(a2, gct.BACKGROUND)
check("[2] non-white = the island mask", np.array_equal(nw2, gct.island_mask(pl2, 2048)))
r_nw = regions(nw2)
check("[2] 5 connected non-white regions", r_nw == 5, r_nw)
r_fill = regions(rgb_eq(a2, gct.TEMPLATE_FILL))
check("[2] 5 connected FILL regions", r_fill == 5, r_fill)

# [3] debug pattern sheet
labels = gct.pattern_sheet_labels(pl2)
front_txt = " ".join(labels.get("front", []))
nums = [float(x) for x in re.findall(r"\d+\.\d", front_txt)]
check("[3] front label names the piece", "Front" in front_txt, front_txt)
check("[3] front label 50.0 x 47.0 cm (+-0.1)", len(nums) >= 2 and abs(nums[0] - 50.0) <= 0.1
      and abs(nums[1] - 47.0) <= 0.1, front_txt)
check("[3] part names", labels.get("sleeve_l", [""])[0] == "Sleeve left" and labels.get("back", [""])[0] == "Back"
      and labels.get("band", [""])[0] == "Neckband", {k: v[0] for k, v in labels.items()})
sl = " ".join(labels.get("sleeve_l", []))
check("[3] sleeve cap height in the label", "cap -2.0 cm" in sl, sl)
check("[3] no cap line without a cap value", not any("cap" in t for t in labels.get("sleeve_r", [])))
check("[3] footer", gct.pattern_sheet_footer(pl2) == "19.59 px/cm · atlas 2048²", gct.pattern_sheet_footer(pl2))

sheet = gct.render_pattern_sheet(pl2)
sa = np.asarray(sheet.convert("RGB"))
mask2 = gct.island_mask(pl2, 2048)
labs2 = gct.rasterise_islands(pl2, 2048)
ids2 = gct.island_ids(pl2)
fills = {}
for name, iid in ids2.items():
    region = labs2 == iid
    px = sa[:2048][region]
    cols, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    top = tuple(int(c) for c in cols[np.argmax(counts)])
    fills[name] = (top, float(counts.max()) / float(region.sum()))
check("[3] 5 distinct fill colours", len({c for c, _ in fills.values()}) == 5, fills)
check("[3] each fill covers >= 50 % of its island", all(share >= 0.5 for _, share in fills.values()),
      {k: round(v[1], 3) for k, v in fills.items()})
check("[3] fills are pastel (every channel >= 150)", all(min(c) >= 150 for c, _ in fills.values()), fills)
check("[3] the sheet is not the model template", sa.shape[1] == 2048 and not np.array_equal(sa[:2048], a2))
check("[3] background outside the islands is white", tuple(sa[5, 5]) == gct.BACKGROUND, tuple(sa[5, 5]))

# seam letters: a cylinder cut in two halves has two seams
import math  # noqa: E402

R, H, S, NR = 0.15, 0.50, 40, 10
cx = np.array([(R * math.cos(2 * math.pi * k / S), R * math.sin(2 * math.pi * k / S), H * j / NR)
               for j in range(NR + 1) for k in range(S)])
cv = lambda k, j: j * S + (k % S)  # noqa: E731
cf = [(cv(k, j), cv(k + 1, j), cv(k + 1, j + 1), cv(k, j + 1)) for j in range(NR) for k in range(S)]
cs = {tuple(sorted((cv(k, j), cv(k, j + 1)))) for k in (0, S // 2) for j in range(NR)}
cisl = up.split_islands(len(cx), cf, np.ones(len(cf), int), cs, xyz=cx)
cuv = {}
for i in cisl:
    lx = cx[i.vmap]
    tris = np.array([t for poly in i.corner_vid for t in up.fan(poly)], dtype=np.int64)
    uv = up.arap(lx, tris, up.lscm(lx, tris), iters=20)
    cuv[i.name] = up.orient(uv, lx, tris, np.array([0, 0, 1.0]), np.zeros(3), None)
cpl = up.islands_payload(cisl, cuv, cx)
marks = gct.seam_marks(cpl)
letters = sorted({m["letter"] for m in marks})
check("[3] two seams -> letters A, B", letters == ["A", "B"], letters)
check("[3] each letter on both sides", all({m["island"] for m in marks if m["letter"] == L} == {"front", "front_2"}
                                           for L in letters), marks)
csheet = gct.render_pattern_sheet(cpl)
check("[3] cylinder sheet renders", csheet.size[0] == 2048, csheet.size)

# [4] occasion + prompt file
import hashlib  # noqa: E402

from types import SimpleNamespace  # noqa: E402

from app.imagegen import occasions as occ  # noqa: E402
from app.imagegen.edit_prompt import normalise  # noqa: E402

check("[4] occasion constant", gct.CUT_OCCASION == "garment_cut_texture" and gct.CUT_USE_CASE == "garment_cut_texture",
      (getattr(gct, "CUT_OCCASION", None), getattr(gct, "CUT_USE_CASE", None)))
check("[4] occasion in the catalog", gct.CUT_OCCASION in occ.occasion_ids())
prompt = gct.render_prompt(piece="T-shirt")
check("[4] prompt names the piece", "T-shirt" in prompt, prompt)
check("[4] prompt has the ordinal wording", "the first image" in prompt and "the second image" in prompt, prompt)
check("[4] no Jinja leftovers", "{{" not in prompt and "{#" not in prompt and prompt == prompt.strip())
_two = {"reference_images": {"input_reference_image_1": "t.png", "input_reference_image_2": "i.png"}}
ph3 = normalise(prompt, _two, SimpleNamespace(model="p-h3-image"))[0]
check("[4] P-H3 wording", "<Picture 1>" in ph3 and "<Picture 2>" in ph3 and "first image" not in ph3
      and "second image" not in ph3, ph3)
check("[4] other backends keep the text", normalise(prompt, _two, SimpleNamespace(model="qwen-edit"))[0] == prompt)
_img = ROOT / "shared" / "templates" / "image"
shipped = "\0".join((_img / f).read_text(encoding="utf-8") for f in (
    "garment_cut_texture_front_plain.md", "garment_cut_texture_front_decorated.md", "garment_cut_texture_back.md"))
check("[4] PROMPT_SHA = md5 of the three shipped files", gct.PROMPT_SHA
      == hashlib.md5(shipped.encode("utf-8")).hexdigest()
      and re.fullmatch(r"[0-9a-f]{32}", gct.PROMPT_SHA) is not None, gct.PROMPT_SHA)
back_prompt = gct.render_prompt(piece="T-shirt", side="back")
check("[4] back prompt: the fabric on the back, no panel named", "the fabric on the back of the T-shirt" in back_prompt
      and "panel" not in back_prompt and "the second image" in back_prompt and "{{" not in back_prompt, back_prompt)

# [5] StrictUndefined
import jinja2  # noqa: E402

from app.imagegen.edit_prompt import Ref, from_template  # noqa: E402

try:
    from_template(gct.PROMPT_FILES["front_plain"], [Ref(1, "canvas"), Ref(2, "material")], piece="T-shirt")
    check("[5] a missing variable raises", False, "rendered without 'pieces'")
except jinja2.exceptions.UndefinedError as e:
    check("[5] a missing variable raises", True, e)

# [6] compose keeps the prompt byte-identical
from types import SimpleNamespace  # noqa: E402

from app.core import config as _cfg  # noqa: E402
from app.core.prompt_compose import compose  # noqa: E402

for fam in ("keywords", "natural"):
    ucp = _cfg.get_use_case_prompts("garment_cut_texture", "qwen" if fam == "natural" else "z_image")
    check(f"[6] use case empty ({fam})", ucp == {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""},
          ucp)
    check(f"[6] use case shipped ({fam})", _cfg._DEFAULT_IMAGE_USE_CASES.get("garment_cut_texture", {}).get(fam)
          == {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""})
    c = compose(use_case="garment_cut_texture", subject=prompt,
                backend=SimpleNamespace(model="P-H3-Image", image_family=fam))
    check(f"[6] compose byte-identical ({fam})", c.prompt == prompt, c.prompt)
    cb = compose(use_case="garment_cut_texture", subject=back_prompt,
                 backend=SimpleNamespace(model="P-H3-Image", image_family=fam))
    check(f"[6] compose keeps the back prompt byte-identical ({fam})", cb.prompt == back_prompt
          and cb.negative == "" and cb.warnings == [], (cb.prompt, cb.negative, cb.warnings))
    check(f"[6] compose negative empty, no warnings ({fam})", c.negative == "" and c.warnings == [],
          (c.negative, c.warnings))

# ---------------------------------------------------------------------------------------------------- Task 8: the job
import io  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from unittest.mock import patch  # noqa: E402

from PIL import Image  # noqa: E402

from app.core import paths  # noqa: E402

_world = Path(_tmp) / "world"
_inst = Path(_tmp) / "instance"
paths.init(_world)
paths.init_instance(_inst)
(_world / "config.json").write_text("{}", encoding="utf-8")
(_inst / "config.json").write_text("{}", encoding="utf-8")
_cfg.load(_world / "config.json", _inst / "config.json")

from app.imagegen.base import BackendBusyError, MediaGenerationDisabled  # noqa: E402
from app.imagegen.routing import NoRouteError, Route  # noqa: E402
from app.models.character import get_character_dir  # noqa: E402

CHAR = "demo"
get_character_dir(CHAR, create=True)
_items = Path(_tmp) / "items"
_items.mkdir()


def _png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _item_picture(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste((150, 40, 40, 255), (w // 6, h // 6, w - w // 6, h - h // 6))
    return im


ITEM_FILES = {}
for _iid, (_w, _h) in {"shirt": (1200, 1100), "shirt3": (1200, 1100), "shirt4": (1200, 1100),
                       "shirt5": (1200, 1100), "tiny": (300, 256), "shirt9": (1200, 1100)}.items():
    ITEM_FILES[_iid] = _items / f"{_iid}.png"
    _item_picture(_w, _h).save(ITEM_FILES[_iid])

from app.core.garment_template import templates_dir  # noqa: E402

# the islands file lives where a drape's record names it (``cut_info`` reads ``has_back`` from it)
_islands_file = templates_dir(CHAR) / "shirt9_tsig0.islands.json"
_islands_file.parent.mkdir(parents=True, exist_ok=True)
_islands_file.write_text(json.dumps(pl2), encoding="utf-8")
ISLANDS_SHA = hashlib.sha256(_islands_file.read_bytes()).hexdigest()
DRAPE_REC = {"islands": {"file": _islands_file.name, "sha256": ISLANDS_SHA, "px_per_cm": 19.59}, "tsig": "tsig0"}
DRAPES = {iid: {"state": "ready", "reason": "", "tsig": "tsig0", "islands_path": _islands_file,
                "islands_sha": ISLANDS_SHA, "record": DRAPE_REC, "worn": True} for iid in ITEM_FILES}

# the piece's BACK view (``garment_template_views``): a (40, 40, 150) block on transparent with a back PRINT — light
# (220, 220, 220) stripes 24 px high every 48 px over its middle 400 x 400 — Picture 2 of the back job. The print makes
# it DECORATED (``is_plain_back``: its detail density is far above ``PLAIN_BACK_DETAIL`` 0.20 — at the 128 px measure
# scale every stripe edge of the middle 2/3 of the block: 0.47 measured, it only has to be above 0.20), so the back job
# runs as these sections expect; a PLAIN back (no job) is ``smoke_cut_texture_plain_back.py``. Every fixture item has
# one, except the ones a test makes the flow render it for.
_backs = Path(_tmp) / "backs"
_backs.mkdir()


def _back_picture(path, blue=150):
    im = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    im.paste((40, 40, blue, 255), (100, 100, 700, 700))
    for y in range(200, 600, 48):
        im.paste((220, 220, 220, 255), (200, y, 600, y + 24))
    im.save(path)
    return path


BACKS = {iid: _back_picture(_backs / f"{iid}_back.png") for iid in ITEM_FILES}
VIEW_JOBS = []          # (item, view) of every piece-only view the flow had rendered
VIEW_REFUSE = {"on": False}
SCHEDULED = []          # ``garment_assembly.schedule`` calls
SET_PARAMS = []         # ``garment_template.set_params`` calls (item, texture)
BUILDING = {}           # ``figure_build.fits_piece``: a Build drapes the piece now
SCHEDULED_CUTS = []     # ``garment_template_cut.schedule`` calls (the routes start the cut on the CPU)


def fake_view_generate(character_name, item_id, view):
    from app.core import garment_template_views as _tv
    VIEW_JOBS.append((item_id, view))
    if VIEW_REFUSE["on"]:
        raise _tv.ViewRefused(view, [{"reasons": ["no piece found"]}])
    BACKS[item_id] = _back_picture(_backs / f"{item_id}_back.png", blue=151)    # a new picture: a new sha
    return BACKS[item_id]


def fake_set_params(item_id, params, *, source="user"):
    SET_PARAMS.append((item_id, params.get("texture")))
    TEXTURES[item_id] = params.get("texture")
    if params.get("sleeve_print"):
        SLEEVE_P[item_id] = params["sleeve_print"]
    return {"params": params, "source": source}


def fake_current_drape(character_name, item_id):
    return DRAPES.get(item_id) or {"state": "missing", "reason": "Not draped yet", "tsig": None,
                                   "islands_path": None, "islands_sha": "", "record": {}, "worn": True}


#: Cut-first (2026-11-21): the pattern the flow reads is the CUT (``gct.current_pattern``), never the drape. A ready
#: drape fixture stands for a ready cut of the same islands (a drape of the same cut writes the same bytes); a
#: ``PATTERNS`` entry overrides it (a cut that runs, failed, or is missing while a drape exists).
PATTERNS = {}


def fake_current_pattern(character_name, item_id):
    from app.core import garment_template_cut as _gtc
    if item_id in PATTERNS:
        return {"state": "missing", "reason": _gtc.NOT_CUT, "cut_sig": "cut0", "islands_path": None,
                "islands_sha": "", "cut_at": "", "wall_s": None, "record": {}, **PATTERNS[item_id]}
    d = DRAPES.get(item_id) or {}
    if d.get("state") == "ready" and d.get("islands_path") is not None and d.get("islands_sha"):
        return {"state": "ready", "reason": "", "cut_sig": "cut0", "islands_path": d["islands_path"],
                "islands_sha": d["islands_sha"], "cut_at": "2026-11-21T10:00:00+00:00", "wall_s": 11.8, "record": {}}
    return {"state": "missing", "reason": _gtc.NOT_CUT, "cut_sig": "cut0", "islands_path": None, "islands_sha": "",
            "cut_at": "", "wall_s": None, "record": {}}


class CutBackend:
    name = "FakeCut"
    api_type = "fake"
    image_family = "natural"
    model = "P-H3-Image"
    ref_slot_count = 2
    max_side = 2048
    extra_params = {}

    def __init__(self):
        self.calls = []
        self.answer = None

    def generate(self, prompt, negative, params, log_meta=None):
        self.calls.append({"prompt": prompt, "negative": negative, "params": params})
        return [self.answer(params)]


class Service:
    def __init__(self):
        self.pool = object()
        self.upscales = 0
        self.upscale_fail = None

    def upscale_image(self, image_bytes, *, character_name="", **_kw):
        self.upscales += 1
        if self.upscale_fail is not None:
            raise self.upscale_fail
        with Image.open(io.BytesIO(image_bytes)) as im:
            big = im.convert("RGB").resize((im.width * 4, im.height * 4), Image.NEAREST)
        return {"bytes": _png(big), "backend": "FakeUp", "scale": 4, "status": "applied",
                "in": [big.width // 4, big.height // 4], "out": [big.width, big.height],
                "routing": {"occasion": "upscale", "position": 1, "spec": "FakeUp*"}}

    def run_on_backend(self, backend, op, character_name=""):
        return op(backend), backend

    def run_on_backend_channel(self, backend, gen_fn, **_kw):
        return gen_fn()


def answer_filled(params):
    with Image.open(params["reference_images"]["input_reference_image_1"]) as t:
        arr = np.asarray(t.convert("RGB")).copy()
    m = ~rgb_eq(arr, gct.BACKGROUND)
    arr[:] = 255
    arr[m] = (150, 40, 40)
    return _png(Image.fromarray(arr, "RGB"))


def answer_white(params):
    return _png(Image.new("RGB", (2048, 2048), (255, 255, 255)))


backend = CutBackend()
svc = Service()
ROUTED = []
RAISE = {"exc": None}
INVALIDATED = []
CHAIN = {"rows": [("FakeCut*", "rule", 1)]}
MEDIA = {"on": True}


def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
    ROUTED.append({"occasion": occasion, "has_ref": has_ref, "pool_is_svc": pool is svc.pool})
    if RAISE["exc"] is not None:
        raise RAISE["exc"]
    result = render(backend)
    return result, Route(occasion=occasion, backend=backend, position=1, spec="FakeCut*",
                         intended_spec="FakeCut*", first_position=1)


def files_of(item_id):
    d = gct.cut_dir(CHAR)
    return sorted(p.name for p in d.glob(f"{item_id}_*")) if d.is_dir() else []


SLEEVES = {"shirt": "short", "long": "long"}
TEXTURES = {}       # Task 9: the item's stored ``texture`` param (absent = the default "projection")
FABRICS = {}        # Task 10: the item's fabric (absent = the default)
SLEEVE_P = {}       # [13]: the item's ``sleeve_print`` (absent = the default "plain")


def fake_get_item(iid):
    params = {"kind": "top", "sleeves": SLEEVES.get(iid, "short")}
    if iid in TEXTURES:
        params["texture"] = TEXTURES[iid]
    if iid in FABRICS:
        params["fabric"] = FABRICS[iid]
    if iid in SLEEVE_P:
        params["sleeve_print"] = SLEEVE_P[iid]
    out = {"id": iid, "category": "outfit_piece",
           "outfit_piece": {"template": {"params": params, "source": "user"}}}
    if ITEM_FILES.get(iid):
        out["image"] = ITEM_FILES[iid].name
    return out


with patch("app.models.inventory.get_item_image_path", lambda iid: str(ITEM_FILES.get(iid, ""))), \
        patch("app.models.inventory.get_item", fake_get_item), \
        patch("app.imagegen.service.get_image_service", lambda: svc), \
        patch("app.imagegen.routing.run_routed", fake_run_routed), \
        patch("app.imagegen.routing.chain_for", lambda occasion, *a, **k: list(CHAIN["rows"])), \
        patch("app.imagegen.base.media_generation_enabled", lambda: MEDIA["on"]), \
        patch("app.core.figure.invalidate", lambda: INVALIDATED.append(1)), \
        patch("app.core.garment_assembly.schedule", lambda c, *a, **k: SCHEDULED.append(c) or True), \
        patch("app.core.garment_template_views.generate", fake_view_generate), \
        patch("app.core.garment_template.set_params", fake_set_params), \
        patch("app.core.figure_build.fits_piece", lambda c, i: BUILDING.get(i, False)), \
        patch.object(gct, "back_view", lambda c, i: BACKS.get(i)), \
        patch.object(gct, "current_drape", fake_current_drape), \
        patch.object(gct, "current_pattern", fake_current_pattern), \
        patch("app.core.garment_template_cut.schedule", lambda c, i, **k: SCHEDULED_CUTS.append((c, i)) or {}), \
        patch.object(gct, "_item_matte", lambda: None):

    item_sha = hashlib.sha256(ITEM_FILES["shirt"].read_bytes()).hexdigest()
    back_sha_s = hashlib.sha256(BACKS["shirt"].read_bytes()).hexdigest()
    want_csig = hashlib.md5("|".join([ISLANDS_SHA, item_sha, back_sha_s, gct.PROMPT_SHA,
                                      str(gct.cut_texture_post.POST_VERSION)]).encode()).hexdigest()[:12]
    check("[8.1] csig formula (islands, item, back view, prompts, post)",
          gct.csig(ISLANDS_SHA, item_sha, back_sha_s) == want_csig, gct.csig(ISLANDS_SHA, item_sha, back_sha_s))
    check("[8.1] current_csig", gct.current_csig(CHAR, "shirt") == want_csig, gct.current_csig(CHAR, "shirt"))

    # [8.1] a filled template -> ready
    backend.answer = answer_filled
    t0 = time.time()
    rec = gct.generate(CHAR, "shirt")
    print(f"     (generate took {time.time() - t0:.1f} s)")
    check("[8.1] ready", rec.get("state") == "ready", (rec.get("state"), rec.get("reason")))
    check("[8.1] IoU >= 0.98", (rec.get("metrics") or {}).get("iou", 0) >= 0.98, rec.get("metrics"))
    stem = gct.cut_dir(CHAR) / f"shirt_{want_csig}"
    atlas = Path(f"{stem}.atlas.png")
    check("[8.1] atlas exists", atlas.is_file(), files_of("shirt"))
    if atlas.is_file():
        with Image.open(atlas) as a_im:
            a_arr = np.asarray(a_im.convert("RGB"))
            check("[8.1] atlas 2048 x 2048", a_im.size == (2048, 2048), a_im.size)
        front = next(i for i in pl2["islands"] if i["name"] == "front")
        x0, y0, x1, y1 = front["bbox_px"]
        cpx = a_arr[int((y0 + y1) / 2), int((x0 + x1) / 2)].astype(int)
        check("[8.1] colour kept (150, 40, 40) +-2", np.abs(cpx - [150, 40, 40]).max() <= 2, cpx.tolist())
    check("[8.1] record on disk", json.loads(Path(f"{stem}.json").read_text()).get("state") == "ready")
    check("[8.1] record fields", rec.get("csig") == want_csig and rec.get("islands_sha") == ISLANDS_SHA
          and rec.get("cut_sig") == "cut0" and rec.get("prompt_sha") == gct.PROMPT_SHA
          and rec.get("item_px") == [1200, 1100] and (rec.get("upscale") or {}).get("status") == "not_needed"
          and abs(rec.get("px_per_cm", 0) - 19.59) < 1e-6, rec)
    check("[8.1] metrics keys", set(rec.get("metrics") or {}) >= {"iou", "coverage", "island_coverage", "spill",
                                                                 "de_before", "de_after", "clamped", "seam_de"},
          sorted(rec.get("metrics") or {}))
    check("[8.1] each job keeps its routing = route_meta", all(
        ((rec.get("jobs") or {}).get(j, {}).get("routing") or {}).get("routing")
        == {"occasion": "garment_cut_texture", "position": 1, "spec": "FakeCut*"} for j in ("front", "back")),
        rec.get("jobs"))
    check("[8.1] run_routed occasion / has_ref / pool", ROUTED[-1] == {"occasion": "garment_cut_texture",
                                                                       "has_ref": True, "pool_is_svc": True}, ROUTED)
    check("[8.1] two image jobs: front, then back", len(backend.calls) == 2, len(backend.calls))
    refs = backend.calls[-2]["params"].get("reference_images") or {}
    check("[8.1] front job references: its template then the item, as str paths",
          list(refs) == ["input_reference_image_1", "input_reference_image_2"]
          and all(isinstance(v, str) for v in refs.values())
          and refs.get("input_reference_image_1") == f"{stem}.template_front.png"
          and refs.get("input_reference_image_2") == f"{stem}.item.png", refs)
    refs_b = backend.calls[-1]["params"].get("reference_images") or {}
    check("[8.1] back job references: its template then the back view",
          refs_b == {"input_reference_image_1": f"{stem}.template_back.png",
                     "input_reference_image_2": f"{stem}.back_ref.png"}, refs_b)
    check("[8.1] no image_use_case in params", all("image_use_case" not in c["params"] for c in backend.calls))
    check("[8.1] the prompt is the rendered file in the backend's dialect (P-H3: picture_edit)",
          backend.calls[-2]["prompt"].startswith("Edit <Picture 1>. Texture the sewing pattern in <Picture 1>")
          and backend.calls[-2]["negative"] == "", backend.calls[-2]["prompt"][:80])
    check("[8.1] piece name from kind + sleeves", backend.calls[-2]["prompt"].count("T-shirt") == 1
          and gct.piece_name("long") == "long-sleeve shirt", gct.piece_name("long"))
    check("[8.1] upsampler_on noted", rec.get("upsampler_on") is True, rec.get("upsampler_on"))
    check("[8.1] applied: figure invalidated once, the assembly scheduled once", len(INVALIDATED) == 1
          and SCHEDULED == [CHAR], (len(INVALIDATED), SCHEDULED))
    st = gct.status(CHAR, "shirt")
    check("[8.1] status: the current record", st.get("csig") == want_csig and st.get("running") is False
          and (st.get("record") or {}).get("state") == "ready", st)

    # [8.2] white -> rejected, the old atlas of this csig gone. The [8.1] record goes first: Run all re-uses a passed
    # answer ([12.12]), so this run starts with no passed answer to keep (the atlas file stays until the flow runs)
    Path(f"{stem}.json").unlink()
    backend.answer = answer_white
    rec2 = gct.generate(CHAR, "shirt")
    check("[8.2] rejected", rec2.get("state") == "rejected", rec2.get("state"))
    check("[8.2] reason names the job", rec2.get("reason") == "Front: coverage 0.00 < 0.97", rec2.get("reason"))
    check("[8.2] the front answer kept; the back job not spent; no atlas", Path(f"{stem}.raw_front.png").is_file()
          and not Path(f"{stem}.raw_back.png").is_file() and not atlas.is_file()
          and (rec2.get("jobs") or {}).get("back", {}).get("state") == "skipped", files_of("shirt"))
    # since 2026-11-21 a rejection invalidates the figure too (the Build's plan and the open-steps badges read the
    # new record: "failed — Retry"), but puts nothing on: no assembly is scheduled for it
    check("[8.2] a rejection invalidates once more (plan), schedules no assembly",
          len(INVALIDATED) == 2 and len(SCHEDULED) == 1, (len(INVALIDATED), len(SCHEDULED)))

    # [8.3] NoRouteError -> failed
    RAISE["exc"] = NoRouteError("garment_cut_texture", [])
    rec3 = gct.generate(CHAR, "shirt3")
    c3 = gct.csig(ISLANDS_SHA, hashlib.sha256(ITEM_FILES["shirt3"].read_bytes()).hexdigest(),
                  hashlib.sha256(BACKS["shirt3"].read_bytes()).hexdigest())
    check("[8.3] failed, reason names Routing", rec3.get("state") == "failed" and "Routing" in rec3.get("reason", ""),
          (rec3.get("state"), rec3.get("reason")))
    check("[8.3] record + inputs of the front job + the back reference, no raw / atlas", files_of("shirt3") == sorted(
        [f"shirt3_{c3}.json", f"shirt3_{c3}.item.png", f"shirt3_{c3}.back_ref.png",
         f"shirt3_{c3}.template_front.png"]), files_of("shirt3"))

    # [8.4] media off inside the job -> failed
    RAISE["exc"] = MediaGenerationDisabled("Media generation is disabled for this world")
    rec4 = gct.generate(CHAR, "shirt3")
    check("[8.4] failed, media off", rec4.get("state") == "failed"
          and "Media generation is off" in rec4.get("reason", ""), (rec4.get("state"), rec4.get("reason")))
    RAISE["exc"] = None

    # [8.3] start(): synchronous refusals, nothing started, nothing written
    CHAIN["rows"] = []
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start with an empty chain raises", False, "no exception")
    except NoRouteError as e:
        check("[8.3] start with an empty chain raises NoRouteError (Routing)", "Routing" in str(e), e)
    check("[8.3] nothing written, nothing running", files_of("shirt4") == []
          and (CHAR, "shirt4") not in gct._running, (files_of("shirt4"), dict(gct._running)))
    CHAIN["rows"] = [("FakeCut*", "rule", 1)]
    MEDIA["on"] = False
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start with media off raises", False, "no exception")
    except MediaGenerationDisabled as e:
        check("[8.3] start with media off raises MediaGenerationDisabled", "Media generation is off" in str(e), e)
    MEDIA["on"] = True
    DRAPES["shirt4"] = {"state": "missing", "reason": "Not draped yet", "tsig": "t", "islands_path": None,
                        "islands_sha": "", "record": {}, "worn": True}
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start without a cut raises", False, "no exception")
    except gct.NotReady as e:
        check("[8.3] start without a cut raises NotReady (the cut's reason)", str(e) == gtc.NOT_CUT, e)
    DRAPES["shirt4"] = {"state": "ready", "reason": "", "tsig": "t", "islands_path": None, "islands_sha": "",
                        "record": {}, "worn": True}
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] a ready drape without a cut does not start", False, "no exception")
    except gct.NotReady as e:
        check("[8.3] a ready drape without a cut raises NotReady", True, e)
    check("[8.3] still nothing written", files_of("shirt4") == [], files_of("shirt4"))

    # [8.7] the thread
    backend.answer = answer_white
    gate_evt = threading.Event()
    real_answer = backend.answer

    def slow_white(params):
        gate_evt.wait(10)
        return real_answer(params)

    backend.answer = slow_white
    started = gct.start(CHAR, "shirt5")
    again = gct.start(CHAR, "shirt5")
    check("[8.7] start -> True, a second start while running -> False", started is True and again is False,
          (started, again))
    check("[8.7] status running", gct.status(CHAR, "shirt5").get("running") is True)
    gate_evt.set()
    for _ in range(600):
        if not gct.status(CHAR, "shirt5").get("running"):
            break
        time.sleep(0.05)
    st5 = gct.status(CHAR, "shirt5")
    check("[8.7] thread done, record rejected", st5.get("running") is False
          and (st5.get("record") or {}).get("state") == "rejected", st5)

    # [8.6] item_source
    n0 = svc.upscales
    data, info = gct.item_source("tiny")
    with Image.open(io.BytesIO(data)) as im:
        size_t = im.size
    check("[8.6] 300 x 256 -> upscaled once", svc.upscales == n0 + 1 and (info.get("upscale") or {}).get("status")
          == "applied" and size_t == (1200, 1024), (svc.upscales - n0, info, size_t))
    data, info = gct.item_source("shirt")
    with Image.open(io.BytesIO(data)) as im:
        size_s = im.size
    check("[8.6] 1200 x 1100 -> not upscaled", svc.upscales == n0 + 1 and (info.get("upscale") or {}).get("status")
          == "not_needed" and size_s == (1200, 1100), (svc.upscales - n0, info, size_s))
    svc.upscale_fail = RuntimeError("upscaler broken")
    data, info = gct.item_source("tiny")
    with Image.open(io.BytesIO(data)) as im:
        size_l = im.size
    check("[8.6] failed upscale -> Lanczos to 1024", (info.get("upscale") or {}).get("status") == "lanczos"
          and max(size_l) == 1024, (info, size_l))
    for exc in (BackendBusyError("busy"), MediaGenerationDisabled("off")):
        svc.upscale_fail = exc
        try:
            gct.item_source("tiny")
            check(f"[8.6] {type(exc).__name__} re-raised", False, "swallowed")
        except type(exc):
            check(f"[8.6] {type(exc).__name__} re-raised", True)
    svc.upscale_fail = None

    # ------------------------------------------------------------------------------- Task 9: the atlas assignment
    from types import SimpleNamespace as NS  # noqa: E402

    from app.core import figure_build  # noqa: E402
    from app.core import garment_assembly as ga  # noqa: E402
    from app.core import garment_template as gt  # noqa: E402

    # [9.1] the param, out of tsig
    p_proj, e_proj = gt.validate_params({"kind": "top", "texture": "projection"})
    p_cut, e_cut = gt.validate_params({"kind": "top", "texture": "cut"})
    check("[9.1] texture: a top field, choices projection / cut, default projection",
          gt.PARAM_SPEC.get("texture") == ("choice", ("projection", "cut"), "projection")
          and "texture" in gt.KIND_FIELDS["top"] and p_cut.get("texture") == "cut" and not e_proj and not e_cut
          and gt.validate_params({"kind": "top"})[0].get("texture") == "projection", gt.PARAM_SPEC.get("texture"))
    check("[9.1] a jacket takes cut too (group B phase C: every kind is cut into pattern pieces)",
          gt.validate_params({"kind": "jacket", "texture": "cut"})[0].get("texture") == "cut")
    check("[9.1] an unknown value is an error", gt.validate_params({"kind": "top", "texture": "paint"})[1] != [])
    check("[9.1] texture is TEXTURE_ONLY", gt.TEXTURE_ONLY == ("fly", "texture", "sleeve_print", "placket", "buttons"), gt.TEXTURE_ONLY)
    k_proj = gt.tsig(p_proj, base_sha="b", texture_sha="t", lower=[])
    k_cut = gt.tsig(p_cut, base_sha="b", texture_sha="t", lower=[])
    check("[9.1] switching texture leaves tsig unchanged", k_proj == k_cut, (k_proj, k_cut))

    # [9.2] a ready cut atlas is used only with texture == "cut"
    backend.answer = answer_filled
    rec9 = gct.generate(CHAR, "shirt9")
    c9 = rec9.get("csig")
    atlas9_file = gct.cut_dir(CHAR) / f"shirt9_{c9}.atlas.png"
    TEXTURES["shirt9"] = "cut"
    a9, i9 = gt.atlas_for(CHAR, "shirt9", DRAPE_REC)
    check("[9.2] ready -> the atlas bytes", rec9.get("state") == "ready" and a9 is not None
          and a9 == atlas9_file.read_bytes(), (rec9.get("state"), None if a9 is None else len(a9)))
    check("[9.2] info: cut, csig, metrics", i9.get("texture") == "cut" and i9.get("csig") == c9
          and i9.get("cut_state") == "ready" and (i9.get("metrics") or {}).get("iou", 0) >= 0.98
          and abs((i9.get("px_per_cm") or 0) - 19.59) < 1e-6, i9)
    TEXTURES["shirt9"] = "projection"
    a9p, i9p = gt.atlas_for(CHAR, "shirt9", DRAPE_REC)
    check("[9.2] texture projection -> None, off", a9p is None and i9p.get("texture") == "projection"
          and i9p.get("cut_state") == "off", i9p)
    TEXTURES["shirt9"] = "cut"
    a9g, i9g = gt.atlas_for(CHAR, "shirt9", {"tsig": "tsig0"})
    check("[9.2] a drape without islands (grid kind) -> None, off", a9g is None and i9g.get("cut_state") == "off",
          i9g)
    check("[9.2] the cut atlas in use: no projection warning", gt.texture_warning({"coverage": 0.43}, i9) is None)

    # [9.3] stale: new islands -> the projection and the warning; a new tsig alone keeps the cut
    a9s, i9s = gt.atlas_for(CHAR, "shirt9", {**DRAPE_REC, "islands": {**DRAPE_REC["islands"], "sha256": "f" * 64}})
    check("[9.3] new islands -> stale, projection", a9s is None and i9s.get("cut_state") == "stale"
          and i9s.get("texture") == "projection", i9s)
    w9s = gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i9s) or {}
    check("[9.3] the stale warning text", (w9s.get("cut") or {}).get("text")
          == "Texture from cut is out of date — make it again in the piece dialog (Texture tab)", w9s)
    check("[9.3] stale: the bake flags stay false", w9s.get("low_coverage") is False and w9s.get("low_iou") is False,
          w9s)
    a9t, i9t = gt.atlas_for(CHAR, "shirt9", {**DRAPE_REC, "tsig": "tsig1"})
    check("[9.3] a new tsig alone (a re-rendered view) -> still cut", a9t is not None and i9t.get("csig") == c9, i9t)
    TEXTURES["shirt4"] = "cut"
    a4, i4 = gt.atlas_for(CHAR, "shirt4", DRAPE_REC)
    check("[9.3] nothing made yet -> missing, no warning", a4 is None and i4.get("cut_state") == "missing"
          and gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i4) is None, i4)

    # [9.4] rejected: the reason in the warning and in the figure row
    TEXTURES["shirt"] = "cut"
    a1r, i1r = gt.atlas_for(CHAR, "shirt", DRAPE_REC)
    check("[9.4] rejected -> projection with the reason", a1r is None and i1r.get("cut_state") == "rejected"
          and i1r.get("reason") == "Front: coverage 0.00 < 0.97", i1r)
    w1r = gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i1r) or {}
    check("[9.4] the warning carries the reason", (w1r.get("cut") or {}).get("state") == "rejected"
          and "coverage 0.00 < 0.97" in (w1r.get("cut") or {}).get("text", ""), w1r)

    def fake_drape_state(character_name, item_id, **_kw):
        return {"state": "ready", "reason": "", "tsig": "tsig0", "path": None,
                "record": {**DRAPE_REC, "created_at": "now", "texture": {"source": "views"},
                           "metrics": {"bake": {"coverage": 0.9, "iou": 0.9}, "drape": {}}}}

    with patch.object(gt, "drape_state", fake_drape_state), \
            patch("app.core.base_body.current_base", lambda *a, **k: ("bsig", "bsha")):
        row1 = figure_build._template_row(CHAR, "shirt", fake_get_item("shirt"), NS(own=[]), {})
        row9 = figure_build._template_row(CHAR, "shirt9", fake_get_item("shirt9"), NS(own=[]), {})
    m1r, m9 = row1.get("metrics") or {}, row9.get("metrics") or {}
    check("[9.4] figure row: cut rejected, projection source kept", (m1r.get("cut") or {}).get("state") == "rejected"
          and (m1r.get("cut") or {}).get("reason") == "Front: coverage 0.00 < 0.97" and m1r.get("texture") == "views"
          and ((m1r.get("texture_warning") or {}).get("cut") or {}).get("state") == "rejected", m1r)
    check("[9.4] figure row: cut in use", m9.get("texture") == "cut" and (m9.get("cut") or {}).get("state") == "ready"
          and (m9.get("cut") or {}).get("iou", 0) >= 0.98 and abs(((m9.get("cut") or {}).get("px_per_cm") or 0)
                                                                   - 19.59) < 1e-6
          and set(m9.get("cut") or {}) >= {"state", "reason", "iou", "de_after", "px_per_cm"}
          and m9.get("texture_warning") is None and row9.get("cost", {}).get("hub_jobs") == 0, m9)

    # [9.5] the assembly state and the graft swap
    fit9 = Path(_tmp) / "shirt9.glb"
    fit9.write_bytes(b"glb")
    g9 = {"item_id": "shirt9", "kind": "clothing", "fsig": "tsig0", "fit": fit9, "low": None, "record": DRAPE_REC,
          "template": True}
    with patch.object(ga, "_material", lambda gm: ("m", None)):
        TEXTURES["shirt9"] = "projection"
        st_p = ga._state([{**g9, "item": fake_get_item("shirt9")}], "full", character_name=CHAR)["shirt9"]
        TEXTURES["shirt9"] = "cut"
        st_c = ga._state([{**g9, "item": fake_get_item("shirt9")}], "full", character_name=CHAR)["shirt9"]
    check("[9.5] state: projection, then cut:<csig>", st_p.get("texture") == "projection"
          and st_c.get("texture") == f"cut:{c9}", (st_p.get("texture"), st_c.get("texture")))
    check("[9.5] the two states differ, the GLB sha does not", st_p != st_c and st_p.get("sha256") == st_c.get("sha256")
          and {k: v for k, v in st_p.items() if k != "texture"} == {k: v for k, v in st_c.items() if k != "texture"},
          (st_p, st_c))
    mesh_c = NS(image=b"projection", mime="image/jpeg")
    ga._apply_cut_atlas(CHAR, {**g9, "item": fake_get_item("shirt9")}, mesh_c)
    check("[9.5] graft: the cut atlas replaces the image", mesh_c.image == atlas9_file.read_bytes()
          and mesh_c.mime == "image/png", (len(mesh_c.image), mesh_c.mime))
    TEXTURES["shirt9"] = "projection"
    mesh_p = NS(image=b"projection", mime="image/jpeg")
    ga._apply_cut_atlas(CHAR, {**g9, "item": fake_get_item("shirt9")}, mesh_p)
    check("[9.5] graft: projection keeps the GLB's image", mesh_p.image == b"projection" and mesh_p.mime == "image/jpeg")

    # ------------------------------------------------------------------------------- Task 10: routes + dialog rules
    from fastapi import HTTPException  # noqa: E402
    from starlette.requests import Request  # noqa: E402

    from app.core import garment_template_views as tv  # noqa: E402
    from app.routes import figure as fr  # noqa: E402

    def req():
        return Request({"type": "http", "method": "GET", "headers": [], "query_string": b"", "path": "/"})

    base9 = f"/characters/{CHAR}/figure/template/shirt9"
    TEXTURES["shirt9"] = "cut"
    g9p = fr.get_template_cut(CHAR, "shirt9", _={})
    check("[10.1] GET cut: the ready record", g9p.get("csig") == c9 and (g9p.get("record") or {}).get("state") == "ready"
          and g9p.get("can_generate") is True and g9p.get("blocked_reason") == "" and g9p.get("upscale") is False, g9p)
    check("[10.1] picture URLs carry the csig", g9p.get("urls") == {
        k: f"{base9}/cut/{k}.png?v={c9}" for k in gct.CUT_FILES}, g9p.get("urls"))
    check("[10.1] pattern URL carries the islands sha", g9p.get("pattern_url") == f"{base9}/pattern.png?v={ISLANDS_SHA[:12]}",
          g9p.get("pattern_url"))
    check("[10.1] a small item picture -> +1 upscale", fr.get_template_cut(CHAR, "tiny", _={}).get("upscale") is True)

    DRAPES["shirt4"] = {"state": "missing", "reason": "Not draped yet", "tsig": None, "islands_path": None,
                        "islands_sha": "", "record": {}, "worn": True}
    MEDIA["on"] = False
    CHAIN["rows"] = []
    n_sched = len(SCHEDULED_CUTS)
    b4 = fr.get_template_cut(CHAR, "shirt4", _={})
    check("[10.2] not cut -> the cut's own reason (and nothing else is said)", b4.get("can_generate") is False
          and b4.get("blocked_reason") == gtc.NOT_CUT and b4.get("pattern_reason") == gtc.NOT_CUT,
          b4.get("blocked_reason"))
    check("[10.2] reading the Texture tab schedules the cut (CPU)", SCHEDULED_CUTS[n_sched:] == [(CHAR, "shirt4")],
          SCHEDULED_CUTS[n_sched:])
    b9m = fr.get_template_cut(CHAR, "shirt9", _={})
    check("[10.2] media off", b9m.get("can_generate") is False and b9m.get("blocked_reason") == "Media generation is off",
          b9m.get("blocked_reason"))
    MEDIA["on"] = True
    b9r = fr.get_template_cut(CHAR, "shirt9", _={})
    check("[10.2] empty chain", b9r.get("can_generate") is False and b9r.get("blocked_reason")
          == "Routing chain for 'Garment — texture from cut' is empty — set it in /admin/settings → Media Generation"
             " → Routing", b9r.get("blocked_reason"))

    def post_status(item_id):
        try:
            fr.generate_template_cut(CHAR, item_id, _={})
            return 200, ""
        except HTTPException as e:
            return e.status_code, str(e.detail)

    code, detail = post_status("shirt9")
    check("[10.3] POST, empty chain -> 503 Routing", code == 503 and "Routing" in detail, (code, detail))
    CHAIN["rows"] = [("FakeCut*", "rule", 1)]
    MEDIA["on"] = False
    try:
        fr.generate_template_cut(CHAR, "shirt9", _={})
        check("[10.3] POST, media off -> MediaGenerationDisabled", False, "no exception")
    except MediaGenerationDisabled:
        check("[10.3] POST, media off -> MediaGenerationDisabled", True)
    MEDIA["on"] = True
    code, detail = post_status("shirt4")
    check("[10.3] POST, no drape -> 400", code == 400, (code, detail))
    gate10 = threading.Event()

    def slow_filled(params):
        gate10.wait(10)
        return answer_filled(params)

    backend.answer = slow_filled
    started10 = fr.generate_template_cut(CHAR, "shirt5", _={})
    code2, _d2 = post_status("shirt5")
    check("[10.3] POST starts; a second POST while it runs -> 409", started10.get("running") is True and code2 == 409,
          (started10.get("running"), code2))
    gate10.set()
    for _ in range(600):
        if not gct.status(CHAR, "shirt5").get("running"):
            break
        time.sleep(0.05)
    backend.answer = answer_filled

    atlas_resp = fr.template_cut_image(CHAR, "shirt9", "atlas", req(), _={})
    check("[10.4] atlas.png -> 200, the atlas file", getattr(atlas_resp, "status_code", 0) == 200
          and Path(getattr(atlas_resp, "path", "")) == atlas9_file, getattr(atlas_resp, "path", None))
    codes = {k: getattr(fr.template_cut_image(CHAR, "shirt9", k, req(), _={}), "status_code", 0)
             for k in gct.CUT_FILES}
    check("[10.4] every record picture -> 200 (both jobs' templates, references, answers)",
          set(codes.values()) == {200}, codes)
    for item_id, kind in (("shirt9", "item.json"), ("shirt4", "atlas")):
        try:
            fr.template_cut_image(CHAR, item_id, kind, req(), _={})
            check(f"[10.4] {item_id} {kind} -> 404", False, "served")
        except HTTPException as e:
            check(f"[10.4] {item_id} {kind} -> 404", e.status_code == 404, e.status_code)

    SHEETS = []
    real_sheet = gct.render_pattern_sheet

    def counting_sheet(*a, **k):
        SHEETS.append(1)
        return real_sheet(*a, **k)

    with patch.object(gct, "render_pattern_sheet", counting_sheet):
        p1 = fr.template_pattern_image(CHAR, "shirt9", req(), _={})
        p2 = fr.template_pattern_image(CHAR, "shirt9", req(), _={})
    sheet_file = gtc.sheet_file(CHAR, "shirt9", "cut0")
    check("[10.5] pattern.png -> 200, cached beside the cut (templates/cut/<item>_<cut sig>.pattern.png)", getattr(p1, "status_code", 0) == 200
          and Path(getattr(p1, "path", "")) == sheet_file and sheet_file.is_file(), getattr(p1, "path", None))
    if sheet_file.is_file():
        with Image.open(sheet_file) as sh:
            check("[10.5] the sheet is atlas-wide (the footer strip below)", sh.size[0] == 2048 and sh.size[1] > 2048,
                  sh.size)
    check("[10.5] the second GET renders nothing", len(SHEETS) == 1 and getattr(p2, "status_code", 0) == 200,
          len(SHEETS))
    DRAPES["shirt4"] = {"state": "ready", "reason": "", "tsig": "t", "islands_path": None, "islands_sha": "",
                        "record": {}, "worn": True}
    try:
        fr.template_pattern_image(CHAR, "shirt4", req(), _={})
        check("[10.5] not cut -> 404", False, "served")
    except HTTPException as e:
        check("[10.5] not cut -> 404", e.status_code == 404, e.status_code)

    worn_file = Path(_tmp) / "worn_front.png"
    worn_file.write_bytes(b"png")
    with patch("app.core.garments.image_path", lambda *a, **k: worn_file):
        fp = fr._front_picture(CHAR, "shirt9", fake_get_item("shirt9"))
    check("[10.6] the dialog shows the item picture, never the worn view",
          fp == {"source": "item", "url": "/inventory/items/shirt9/image"}, fp)
    fpn = fr._front_picture(CHAR, "nopic", fake_get_item("nopic"))
    check("[10.6] no item picture -> none", fpn.get("source") == "" and fpn.get("url") == "", fpn)

    FABRICS["sheer9"] = "sheer"
    ITEM_FILES["sheer9"] = ITEM_FILES["shirt9"]
    TEXTURES["sheer9"] = "projection"
    sv_p = tv.status(CHAR, "sheer9")
    TEXTURES["sheer9"] = "cut"
    sv_c = tv.status(CHAR, "sheer9")
    check("[10.7] projection: the sheer views are required", sv_p.get("required") is True and sv_p.get("hub_jobs") == 2
          and not sv_p.get("optional"), sv_p)
    check("[10.7] cut: the views are optional, 0 jobs", sv_c.get("optional") is True and sv_c.get("required") is False
          and sv_c.get("hub_jobs") == 0 and sv_c.get("max_jobs") == 0, sv_c)
    TEXTURES["sheer9"] = "projection"
    src_p = gt.texture_sources(CHAR, "sheer9")
    TEXTURES["sheer9"] = "cut"
    src_c = gt.texture_sources(CHAR, "sheer9")
    check("[10.7] sheer sources: none with projection, the item picture with cut", src_p == {}
          and src_c.get("source") == "item_image", (src_p, src_c))
    with patch.object(gt, "drape_state", lambda *a, **k: {"state": "missing", "reason": "", "record": None}), \
            patch("app.core.base_body.current_base", lambda *a, **k: ("bsig", "bsha")), \
            patch("app.core.figure.worn_sets", lambda *a, **k: NS(pieces={}, own=[])), \
            patch("app.core.figure_build.fits_piece", lambda *a, **k: False):
        prog = gt.piece_progress(CHAR, "sheer9", item=fake_get_item("sheer9"), profile={})
    pic = next((s for s in prog.get("steps") or [] if s.get("id") == "picture"), {})
    check("[10.7] piece_progress: the picture step is done, no view jobs", pic.get("status") == "done"
          and not (pic.get("numbers") or {}).get("hub_jobs"), pic)


    # ------------------------------------------------------------------- [12] the rework of 2026-11-20 (user findings)
    from app.core import piece_jobs  # noqa: E402

    def item_fixture(iid, *, back=True, texture=None, drape=None):
        ITEM_FILES[iid] = ITEM_FILES["shirt9"]
        if back:
            BACKS[iid] = _back_picture(_backs / f"{iid}_back.png")
        else:
            BACKS.pop(iid, None)
        if texture is not None:
            TEXTURES[iid] = texture
        DRAPES[iid] = drape or {"state": "ready", "reason": "", "tsig": "tsig0", "islands_path": _islands_file,
                                "islands_sha": ISLANDS_SHA, "record": DRAPE_REC, "worn": True}

    def wait_done(iid):
        for _ in range(1200):
            if not gct.status(CHAR, iid).get("running"):
                return gct.status(CHAR, iid)
            time.sleep(0.05)
        return gct.status(CHAR, iid)

    # [12.1] the split: back panel alone vs everything else; templates with disjoint islands in the atlas frame
    parts = gct.split_islands(pl2)
    names = {k: sorted(i["name"] for i in v["islands"]) for k, v in parts.items()}
    check("[12.1] split: back = [back]; front = band, front, sleeve_l, sleeve_r",
          names == {"front": ["band", "front", "sleeve_l", "sleeve_r"], "back": ["back"]}, names)
    lab = gct.rasterise_islands(pl2, 2048)
    t_front = ~rgb_eq(np.asarray(gct.render_template(parts["front"], 2048)), gct.BACKGROUND)
    t_back = ~rgb_eq(np.asarray(gct.render_template(parts["back"], 2048)), gct.BACKGROUND)
    check("[12.1] the back template is exactly the back island (id 1 of the sorted names)",
          np.array_equal(t_back, lab == 1), int(t_back.sum()))
    check("[12.1] the front template is exactly the other four islands (ids 2..5)",
          np.array_equal(t_front, lab >= 2), int(t_front.sum()))
    check("[12.1] the two templates are disjoint and add up to the full template",
          not (t_front & t_back).any() and int(t_front.sum()) + int(t_back.sum()) == int((lab > 0).sum()),
          (int(t_front.sum()), int(t_back.sum()), int((lab > 0).sum())))
    check("[12.1] both keep the atlas frame", parts["back"]["atlas_px"] == pl2["atlas_px"]
          and parts["front"]["px_per_cm"] == pl2["px_per_cm"])
    check("[12.1] a pattern without a back panel has the front job only",
          list(gct.split_islands({"islands": [{"name": "front"}, {"name": "band"}]})) == ["front"])
    check("[12.1] a split back part goes with the back job", gct.job_of("back_2") == "back"
          and gct.job_of("sleeve_l") == "front" and gct.job_of("band") == "front")
    sl = {"islands": [{"name": n} for n in ("front", "back", "back_2", "sleeve_l")],
          "seams": [{"seam": 0, "a": "front", "b": "back"}, {"seam": 1, "a": "sleeve_l", "b": "front"},
                    {"seam": 2, "a": "back", "b": "back_2"}]}
    sp = gct.split_islands(sl)
    check("[12.2] seams: each job keeps its inner seams, the front/back seams are the cross seams",
          [p_["seam"] for p_ in sp["front"]["seams"]] == [1] and [p_["seam"] for p_ in sp["back"]["seams"]] == [2]
          and [p_["seam"] for p_ in gct.cross_seams(sl)] == [0], (sp["front"]["seams"], sp["back"]["seams"]))

    # [12.3] the two jobs end to end: per-job islands, prompts and Picture 2
    item_fixture("two", texture="cut")
    backend.answer = answer_filled
    n0 = len(backend.calls)
    rec_two = gct.generate(CHAR, "two")
    front_call, back_call = backend.calls[n0], backend.calls[n0 + 1]
    check("[12.3] two image jobs, both ready", len(backend.calls) == n0 + 2 and rec_two.get("state") == "ready"
          and all(rec_two["jobs"][j]["state"] == "ready" for j in ("front", "back")), rec_two.get("jobs"))
    check("[12.3] front prompt plain, back prompt the back's fabric, no panel named",
          front_call["prompt"].startswith("Edit <Picture 1>. Texture the sewing pattern")
          and "the fabric on the back of" in back_call["prompt"] and "panel" not in front_call["prompt"]
          and "panel" not in back_call["prompt"], (front_call["prompt"][:60], back_call["prompt"][:60]))
    zb, zf = rec_two["jobs"]["back"]["metrics"].get("zoom"), rec_two["jobs"]["front"]["metrics"].get("zoom")
    stem_z = gct.cut_dir(CHAR) / f"two_{rec_two['csig']}"
    with Image.open(f"{stem_z}.template_back.png") as tb:
        tb_nw = int((np.asarray(tb.convert("RGB")) != 255).any(-1).sum())
    _two_isl = json.loads(Path(gct.current_pattern(CHAR, "two")["islands_path"]).read_text(encoding="utf-8"))
    back_px = int((gct.job_labels(_two_isl, 2048, "back") > 0).sum())
    check("[12.3] the back job is zoomed: k > 1, template area = island area x k^2 (+-3 %), the front not",
          zf is None and isinstance(zb, dict) and zb["k"] > 1
          and abs(tb_nw - back_px * zb["k"] ** 2) <= 0.03 * back_px * zb["k"] ** 2, (zb, zf, tb_nw, back_px))
    check("[12.3] per-job coverage keys: back = {1}, front = {2, 3, 4, 5}",
          set(rec_two["jobs"]["back"]["metrics"]["islands"]) == {"1"}
          and set(rec_two["jobs"]["front"]["metrics"]["islands"]) == {"2", "3", "4", "5"},
          {j: sorted(rec_two["jobs"][j]["metrics"]["islands"]) for j in ("front", "back")})
    check("[12.3] the job references are named", rec_two["jobs"]["front"]["reference"] == "item"
          and rec_two["jobs"]["back"]["reference"] == "back_view")
    stem2 = gct.cut_dir(CHAR) / f"two_{rec_two['csig']}"
    with Image.open(f"{stem2}.back_ref.png") as br:
        bref = np.asarray(br.convert("RGB"))
    check("[12.3] Picture 2 of the back job is the back view flattened on white",
          tuple(bref[400, 150]) == (40, 40, 150) and tuple(bref[10, 10]) == (255, 255, 255),
          (tuple(bref[400, 150]), tuple(bref[10, 10])))
    with Image.open(f"{stem2}.atlas.png") as at2:
        atl = np.asarray(at2.convert("RGB")).astype(int)
    bk = next(i for i in pl2["islands"] if i["name"] == "back")
    bx0, by0, bx1, by1 = bk["bbox_px"]
    check("[12.3] the composed atlas carries the back island (150, 40, 40) +-2",
          np.abs(atl[int((by0 + by1) / 2), int((bx0 + bx1) / 2)] - [150, 40, 40]).max() <= 2)
    check("[12.3] summary metrics: worst IoU over both jobs, seam keys present",
          rec_two["metrics"]["iou"] == min(rec_two["jobs"][j]["metrics"]["iou"] for j in ("front", "back"))
          and "seam_cross_de" in rec_two["metrics"], rec_two["metrics"].get("iou"))

    # [12.4] the composition rule on a 20 x 20 canvas: front island cols 2..7, back island cols 10..15 (all rows),
    # each grown by 2 columns of bleed: front grown 0..9, back grown 8..17. Front is written first, then back outside
    # the front island, then each island again: cols 0..7 red, 8..17 blue (cols 8, 9 are bleed of both: the back,
    # written last, keeps them; neither island is touched), 18..19 white.
    fm = np.zeros((20, 20), bool)
    fm[:, 2:8] = True
    bm = np.zeros((20, 20), bool)
    bm[:, 10:16] = True
    fg_ = np.zeros((20, 20), bool)
    fg_[:, 0:10] = True
    bg_ = np.zeros((20, 20), bool)
    bg_[:, 8:18] = True
    red = np.zeros((20, 20, 3), np.uint8)
    red[:] = (200, 0, 0)
    blue = np.zeros((20, 20, 3), np.uint8)
    blue[:] = (0, 0, 200)
    comp = gct.compose({"front": {"_image": red, "_grown": fg_, "_mask": fm},
                        "back": {"_image": blue, "_grown": bg_, "_mask": bm}}, 20)
    cols = ["r" if tuple(comp[5, j]) == (200, 0, 0) else "b" if tuple(comp[5, j]) == (0, 0, 200)
            else "w" if tuple(comp[5, j]) == (255, 255, 255) else "?" for j in range(20)]
    check("[12.4] compose: rrrrrrrr bbbbbbbbbb ww", "".join(cols) == "r" * 8 + "b" * 10 + "w" * 2, "".join(cols))

    # [12.5] the back job rejected: the front answer kept, the atlas not written
    def answer_back_white(params):
        if params["reference_images"]["input_reference_image_1"].endswith(".template_back.png"):
            return answer_white(params)
        return answer_filled(params)

    item_fixture("backbad", texture="cut")
    backend.answer = answer_back_white
    rec_bb = gct.generate(CHAR, "backbad")
    stem_bb = gct.cut_dir(CHAR) / f"backbad_{rec_bb['csig']}"
    check("[12.5] back rejected -> rejected, reason names the back job, both answers kept, no atlas",
          rec_bb.get("state") == "rejected" and rec_bb.get("reason") == "Back: coverage 0.00 < 0.97"
          and Path(f"{stem_bb}.raw_front.png").is_file() and Path(f"{stem_bb}.raw_back.png").is_file()
          and not Path(f"{stem_bb}.atlas.png").is_file(), (rec_bb.get("state"), rec_bb.get("reason")))

    # [12.6] redo one job: "back" re-uses the front answer (1 image job); "front" without a back answer runs both
    backend.answer = answer_filled
    n0 = len(backend.calls)
    rec_ob = gct.generate(CHAR, "backbad", only="back")
    check("[12.6] only back: 1 image job, the back job's references, ready",
          len(backend.calls) == n0 + 1 and backend.calls[-1]["params"]["reference_images"]["input_reference_image_2"]
          .endswith(".back_ref.png") and rec_ob.get("state") == "ready" and rec_ob.get("only") == "back",
          (len(backend.calls) - n0, rec_ob.get("state"), rec_ob.get("reason")))
    item_fixture("only2", texture="cut")
    n0 = len(backend.calls)
    rec_o2 = gct.generate(CHAR, "only2", only="front")
    check("[12.6] only front without a back answer of this csig: both jobs run", len(backend.calls) == n0 + 2
          and rec_o2.get("state") == "ready", len(backend.calls) - n0)

    # [12.7] the back view missing: the flow makes it first and counts it on the button
    item_fixture("mk1", back=False, texture="cut")
    plan = gct.job_plan(CHAR, "mk1")
    check("[12.7] plan with the back view missing: 1 view + 0 upscale + front + back = 3 jobs, at most 4",
          {k: plan.get(k) for k in ("back_view", "upscale", "front", "back", "total", "max", "reused")}
          == {"back_view": 1, "upscale": 0, "front": 1, "back": 1, "total": 3, "max": 6, "reused": []}, plan)
    v0 = len(VIEW_JOBS)
    rec_mk = gct.generate(CHAR, "mk1")
    want_mk = gct.csig(ISLANDS_SHA, hashlib.sha256(ITEM_FILES["mk1"].read_bytes()).hexdigest(),
                       hashlib.sha256(BACKS["mk1"].read_bytes()).hexdigest())
    check("[12.7] the back view rendered once, then the cut keyed with it", VIEW_JOBS[v0:] == [("mk1", "back")]
          and rec_mk.get("back_view", {}).get("made") is True and rec_mk.get("csig") == want_mk
          and rec_mk.get("state") == "ready"
          and rec_mk.get("csig") != gct.csig(ISLANDS_SHA, hashlib.sha256(ITEM_FILES["mk1"].read_bytes()).hexdigest(), ""),
          (VIEW_JOBS[v0:], rec_mk.get("csig"), want_mk))
    pl_mk = gct.job_plan(CHAR, "mk1")
    check("[12.7] plan afterwards: 0 (current); each Redo 1", pl_mk["total"] == 0
          and pl_mk["redo"]["front"]["total"] == 1 and pl_mk["redo"]["back"]["total"] == 1, pl_mk)
    check("[12.7] tiny item picture: +1 upscale in the plan", gct.job_plan(CHAR, "tiny")["upscale"] == 1)
    item_fixture("mk2", back=False, texture="cut")
    VIEW_REFUSE["on"] = True
    n0 = len(backend.calls)
    rec_mk2 = gct.generate(CHAR, "mk2")
    VIEW_REFUSE["on"] = False
    check("[12.7] a refused back view: failed with the plain reason, no image job spent",
          rec_mk2.get("state") == "failed" and "back view was refused" in rec_mk2.get("reason", "")
          and len(backend.calls) == n0, rec_mk2.get("reason"))

    # [12.8] one hub-job flow per piece: the server refuses the second (409 with the holder's reason)
    item_fixture("lock1", texture="cut")
    check("[12.8] claim -> '' ; a second claim -> the cut's reason",
          piece_jobs.claim(CHAR, "lock1", "cut") == "" and piece_jobs.claim(CHAR, "lock1", "view:back")
          == piece_jobs.REASONS["cut"])
    try:
        tv.start(CHAR, "lock1", "front", run=lambda *a: None)
        check("[12.8] a view while the cut runs -> Busy", False, "started")
    except tv.Busy as e:
        check("[12.8] a view while the cut runs -> Busy", str(e) == piece_jobs.REASONS["cut"], e)
    try:
        fr.generate_template_view(CHAR, "lock1", "back", _={})
        check("[12.8] route: a view while the cut runs -> 409", False, "started")
    except HTTPException as e:
        check("[12.8] route: a view while the cut runs -> 409 with the reason",
              e.status_code == 409 and e.detail == piece_jobs.REASONS["cut"], (e.status_code, e.detail))
    check("[12.8] the views payload names why its buttons are off",
          tv.status(CHAR, "lock1").get("busy") == piece_jobs.REASONS["cut"], tv.status(CHAR, "lock1").get("busy"))
    for label, call in (("Use this", lambda: fr.use_template_view(CHAR, "lock1", "back", 1, _={})),
                        ("Remove", lambda: fr.delete_template_view(CHAR, "lock1", "back", _={}))):
        try:
            call()
            check(f"[12.8] route: {label} on a view while the cut runs -> 409", False, "ran")
        except HTTPException as e:
            check(f"[12.8] route: {label} on a view while the cut runs -> 409 with the reason",
                  e.status_code == 409 and e.detail == piece_jobs.REASONS["cut"], (e.status_code, e.detail))
    piece_jobs.release(CHAR, "lock1", "cut")
    check("[12.8] released", piece_jobs.holder(CHAR, "lock1") == "")
    piece_jobs.claim(CHAR, "lock1", "view:front")
    try:
        gct.start(CHAR, "lock1", run=lambda *a, **k: None)
        check("[12.8] the cut while a view runs -> Busy", False, "started")
    except gct.Busy as e:
        check("[12.8] the cut while a view runs -> Busy", str(e) == piece_jobs.REASONS["view:front"], e)
    try:
        fr.generate_template_cut(CHAR, "lock1", _={})
        check("[12.8] route: the cut while a view runs -> 409", False, "started")
    except HTTPException as e:
        check("[12.8] route: the cut while a view runs -> 409 with the reason",
              e.status_code == 409 and e.detail == piece_jobs.REASONS["view:front"], (e.status_code, e.detail))
    dl = gct.dialog_state(CHAR, "lock1")
    check("[12.8] the dialog says the view runs, not the drape", dl.get("can_generate") is False
          and dl.get("blocked_reason") == piece_jobs.REASONS["view:front"], dl.get("blocked_reason"))
    piece_jobs.release(CHAR, "lock1", "view:front")
    gate12 = threading.Event()
    starts = []

    def slow_run(c, i, **k):
        gate12.wait(10)

    racers = [threading.Thread(target=lambda: starts.append(gct.start(CHAR, "lock1", run=slow_run)))
              for _ in range(4)]
    for th in racers:
        th.start()
    for th in racers:
        th.join()
    check("[12.8] four racing starts -> exactly one starts", sorted(starts) == [False, False, False, True], starts)
    dr = gct.dialog_state(CHAR, "lock1")
    check("[12.8] while the cut runs: running, no blocked reason, the button off", dr.get("running") is True
          and dr.get("blocked_reason") == "" and dr.get("can_generate") is False, dr.get("blocked_reason"))
    gate12.set()
    wait_done("lock1")
    check("[12.8] the claim is released when the flow ends", piece_jobs.holder(CHAR, "lock1") == "")

    # [12.9] cut-first: the dialog's reason per CUT state — each only where it is true; the drape is never asked
    states = {
        "dr_ready": ({}, False, ""),
        "dr_missing": ({"state": "missing", "reason": gtc.NOT_CUT}, False, gtc.NOT_CUT),
        "dr_cutting": ({"state": "cutting", "reason": gtc.CUTTING}, False, gtc.CUTTING),
        "dr_failed": ({"state": "failed", "reason": gtc.CUT_FAILED.format(error="boom")}, False,
                      gtc.CUT_FAILED.format(error="boom")),
        "dr_blocked": ({"state": "blocked", "reason": gtc.NO_PATTERN}, False, gtc.NO_PATTERN),
        # a Build draping the piece, no drape yet, the piece not worn: the ready cut alone decides — nothing blocks
        "dr_draping": (None, True, ""),
    }
    got = {}
    for iid, (over, building, _want) in states.items():
        drape_d = {"state": "missing", "reason": "Not draped yet", "tsig": None, "islands_path": None,
                   "islands_sha": "", "record": {}, "worn": False}
        item_fixture(iid, texture="cut", drape=drape_d)
        if over:
            PATTERNS[iid] = over
        else:
            PATTERNS[iid] = {"state": "ready", "reason": "", "islands_path": _islands_file,
                             "islands_sha": ISLANDS_SHA, "cut_at": "2026-11-21T10:00:00+00:00", "wall_s": 11.8}
        BUILDING[iid] = building
        got[iid] = gct.dialog_state(CHAR, iid).get("blocked_reason")
    check("[12.9] one true reason per cut state (ready none, missing, cutting, failed, blocked; a drape running or "
          "missing blocks nothing)", got == {k: v[2] for k, v in states.items()}, got)
    dcut = gct.dialog_state(CHAR, "dr_cutting")
    check("[12.9] cutting -> the Pattern line's reason and the cutting flag", dcut.get("cutting") is True
          and dcut.get("pattern_reason") == gtc.CUTTING and dcut.get("plan") is None, dcut.get("pattern_reason"))
    dready = gct.dialog_state(CHAR, "dr_ready")
    check("[12.9] ready without any drape: the plan says 2 jobs and the back panel", dready.get("plan", {}).get("total")
          == 2 and dready.get("has_back") is True and dready.get("can_generate") is True
          and dready.get("cut_at") == "2026-11-21T10:00:00+00:00" and dready.get("pattern_reason") == "",
          dready.get("plan"))

    # [12.10] one click applies itself: the texture selected at the start, the figure re-assembled at the end
    item_fixture("auto1", texture="projection")
    p0, s0, i0 = len(SET_PARAMS), len(SCHEDULED), len(INVALIDATED)
    check("[12.10] start", gct.start(CHAR, "auto1") is True)
    check("[12.10] starting selects texture 'cut' (the flow's only purpose)", SET_PARAMS[p0:] == [("auto1", "cut")],
          SET_PARAMS[p0:])
    st_a = wait_done("auto1")
    check("[12.10] ready, the figure invalidated and re-assembled once (no second click)",
          (st_a.get("record") or {}).get("state") == "ready" and len(SCHEDULED) == s0 + 1
          and len(INVALIDATED) == i0 + 1, (st_a.get("record", {}).get("state"), len(SCHEDULED) - s0))
    da = gct.dialog_state(CHAR, "auto1")
    check("[12.10] the dialog reads it applied and current", da.get("applied") is True and da.get("current") is True
          and da.get("texture") == "cut", (da.get("applied"), da.get("current"), da.get("texture")))
    sv = tv.status(CHAR, "auto1")
    check("[12.10] the views with texture cut: none due, the back one used by the cut", sv.get("hub_jobs") == 0
          and sv.get("cut_uses") == ["back"], sv)

    # [12.11] a cut-textured piece keeps its drape when only a projection view changed (no re-drape, no drop-off)
    p_cut = gt.validate_params({"kind": "top", "texture": "cut"})[0]
    t_old = gt.tsig(p_cut, base_sha="bsha", texture_sha="tex0", lower=["x:-"])
    t_new = gt.tsig(p_cut, base_sha="bsha", texture_sha="tex1", lower=["x:-"])
    folder = gt.templates_dir(CHAR)
    (folder / f"stand_{t_old}.glb").write_bytes(b"glb")
    old_rec = {"item_id": "stand", "tsig": t_old, "accepted": True, "texture_sha": "tex0", "created_at": "2026"}
    (folder / f"stand_{t_old}.json").write_text(json.dumps(old_rec), encoding="utf-8")

    def drape_with(params, lower_all=("x:-",)):
        with patch.object(gt, "_key", lambda *a, **k: (t_new, None, {"front": "", "back": ""}, params,
                                                       list(lower_all))):
            return gt.drape_state(CHAR, "stand", base_sha="bsha", lower=[], item=None)
    d_cut = drape_with(p_cut)
    check("[12.11] texture cut, only the texture part differs -> the old drape stands in (ready)",
          d_cut.get("state") == "ready" and d_cut.get("stand_in") is True and d_cut.get("tsig") == t_old, d_cut)
    p_proj = gt.validate_params({"kind": "top", "texture": "projection"})[0]
    check("[12.11] texture projection -> missing (the projection must be re-baked)",
          drape_with(p_proj).get("state") == "missing")
    check("[12.11] another lower layer -> missing (not only the texture differs)",
          drape_with(p_cut, ("y:-",)).get("state") == "missing")
    (folder / f"stand_{t_old}.json").write_text(json.dumps({**old_rec, "texture_sha": None}), encoding="utf-8")
    check("[12.11] a record without texture_sha never stands in", drape_with(p_cut).get("state") == "missing")

    # [12.12] Run all spends only on what did not pass; every Redo names its real count (review finding 2026-11-20)
    def answer_front_white(params):
        if params["reference_images"]["input_reference_image_1"].endswith(".template_front.png"):
            return answer_white(params)
        return answer_filled(params)

    item_fixture("ra1", texture="cut")
    backend.answer = answer_back_white
    rec_ra = gct.generate(CHAR, "ra1")
    pl_ra = gct.job_plan(CHAR, "ra1")
    check("[12.12] back rejected: Run all = 1 image job (the back), the front answer kept",
          rec_ra.get("state") == "rejected" and pl_ra.get("total") == 1 and pl_ra.get("front") == 0
          and pl_ra.get("back") == 1 and pl_ra.get("reused") == ["front"], pl_ra)
    check("[12.12] back rejected: Redo back = 1, Redo front = 2 (the back answer did not pass, nothing is kept)",
          pl_ra["redo"]["back"]["total"] == 1 and pl_ra["redo"]["front"]["total"] == 2
          and pl_ra["redo"]["front"]["reused"] == [], pl_ra["redo"])
    check("[12.12] the dialog carries the same plan", gct.dialog_state(CHAR, "ra1").get("plan") == pl_ra)
    backend.answer = answer_filled
    n0 = len(backend.calls)
    rec_ra2 = gct.generate(CHAR, "ra1")
    check("[12.12] Run all after it: exactly 1 image call (the back job), ready",
          len(backend.calls) == n0 + 1 and backend.calls[-1]["params"]["reference_images"]["input_reference_image_1"]
          .endswith(".template_back.png") and rec_ra2.get("state") == "ready", (len(backend.calls) - n0,
                                                                                rec_ra2.get("reason")))
    pl_done = gct.job_plan(CHAR, "ra1")
    check("[12.12] all passed: Run all = 0 (Everything is current), each Redo = 1",
          pl_done["total"] == 0 and gct.dialog_state(CHAR, "ra1").get("current") is True
          and pl_done["redo"]["front"]["total"] == 1 and pl_done["redo"]["back"]["total"] == 1, pl_done)
    item_fixture("rf1", texture="cut")
    backend.answer = answer_front_white
    rec_rf = gct.generate(CHAR, "rf1")
    pl_rf = gct.job_plan(CHAR, "rf1")
    check("[12.12] front rejected (back skipped): Run all = 2, Redo back = 2, Redo front = 2",
          rec_rf.get("state") == "rejected" and rec_rf["jobs"]["back"]["state"] == "skipped"
          and pl_rf["total"] == 2 and pl_rf["redo"]["back"]["total"] == 2 and pl_rf["redo"]["front"]["total"] == 2,
          (rec_rf["jobs"]["back"].get("state"), pl_rf))
    backend.answer = answer_filled
    check("[12.12] the tiny item: the upscale is counted only where the front job runs",
          gct.job_plan(CHAR, "tiny")["upscale"] == 1)

    # [13] the answer gates, the pre-filled template and the override path (user test 2026-11-21)
    def answer_green(params):
        with Image.open(params["reference_images"]["input_reference_image_1"]) as t:
            arr = np.asarray(t.convert("RGB")).copy()
        m = ~rgb_eq(arr, gct.BACKGROUND)
        arr[:] = 255
        arr[m] = (40, 150, 40)
        return _png(Image.fromarray(arr, "RGB"))

    def answer_front_green(params):
        if params["reference_images"]["input_reference_image_1"].endswith(".template_front.png"):
            return answer_green(params)
        return answer_filled(params)

    item_fixture("ov1", texture="cut")
    backend.answer = answer_front_green
    n0 = len(backend.calls)
    rec_ov = gct.generate(CHAR, "ov1")
    stem_ov = gct.cut_dir(CHAR) / f"ov1_{rec_ov['csig']}"
    with Image.open(f"{stem_ov}.template_front.png") as tf:
        tarr = np.asarray(tf.convert("RGB"))
    fr = next(i for i in pl2["islands"] if i["name"] == "front")
    fx0, fy0, fx1, fy1 = fr["bbox_px"]
    tc = tarr[int((fy0 + fy1) / 2), int((fx0 + fx1) / 2)].astype(int)
    check("[13.1] the template's islands are pre-filled with the item's fabric (150, 40, 40) +-1",
          np.abs(tc - [150, 40, 40]).max() <= 1 and (rec_ov.get("fabric") or {}).get("prefill") is not None, tc.tolist())
    check("[13.1] the outline is the fill x 0.6 (L* 34 >= 30): (90, 24, 24)", gct.outline_for((150, 40, 40))
          == (90, 24, 24), gct.outline_for((150, 40, 40)))
    gates_ov = {g["gate"]: g for g in rec_ov["jobs"]["front"]["metrics"]["gates"]}
    check("[13.1] a green answer for a red item: front rejected by the colour gate, the back not spent",
          rec_ov.get("state") == "rejected" and rec_ov["jobs"]["front"]["reason"].startswith("colour ΔE00")
          and gates_ov["colour"]["ok"] is False and gates_ov["colour"]["value"] > 20
          and gates_ov["detail"]["ok"] is True and rec_ov["jobs"]["back"]["state"] == "skipped"
          and len(backend.calls) == n0 + 2, (rec_ov.get("reason"), gates_ov))
    use0 = gct.dialog_state(CHAR, "ov1").get("answers") or {}
    check("[13.2] the dialog offers Use this answer for the shown (rejected) front answer, not for the missing back",
          (use0.get("front") or {}).get("can_use") is True and (use0.get("back") or {}).get("can_use") is False, use0)
    try:
        gct.start_recompose(CHAR, "ov1", accept="back")
        check("[13.2] Use this answer without an answer is refused", False)
    except gct.NotReady as e:
        check("[13.2] Use this answer without an answer is refused", "no answer" in str(e), e)
    n0 = len(backend.calls)
    sch0 = len(SCHEDULED)
    rec_use = gct.recompose(CHAR, "ov1", accept="front")
    fj = rec_use["jobs"]["front"]
    check("[13.2] Use this answer: 0 image jobs, the front accepted over its reason, the back next (not made)",
          len(backend.calls) == n0 and fj.get("state") == "ready" and fj.get("accepted") is True
          and str(fj.get("accepted_over", "")).startswith("colour ΔE00")
          and rec_use["jobs"]["back"]["state"] == "skipped" and rec_use["jobs"]["back"]["reason"] == gct.NOT_MADE
          and rec_use.get("state") == "rejected" and rec_use.get("reason") == f"Back: {gct.NOT_MADE}"
          and len(SCHEDULED) == sch0, (fj, rec_use.get("reason")))
    pl_ov = gct.job_plan(CHAR, "ov1")
    check("[13.2] Run all then spends 1 (the back job), the accepted front is kept",
          pl_ov["total"] == 1 and pl_ov["back"] == 1 and pl_ov["reused"] == ["front"], pl_ov)
    rec_ov2 = gct.generate(CHAR, "ov1")
    check("[13.3] Run all: exactly 1 image call (the back), ready, the front still accepted, atlas written, applied",
          len(backend.calls) == n0 + 1 and rec_ov2.get("state") == "ready"
          and rec_ov2["jobs"]["front"].get("accepted") is True
          and Path(f"{stem_ov}.atlas.png").is_file() and len(SCHEDULED) == sch0 + 1,
          (len(backend.calls) - n0, rec_ov2.get("state"), rec_ov2.get("reason")))
    check("[13.3] the figure uses the accepted atlas", gt.cut_info(CHAR, "ov1", DRAPE_REC).get("texture") == "cut",
          gt.cut_info(CHAR, "ov1", DRAPE_REC))
    # [13.4] Use this answer through the thread (start_recompose), with the run stubbed
    RECOMP = []
    ok_start = gct.start_recompose(CHAR, "ov1", accept="front", run=lambda c, i, accept=None: RECOMP.append(accept))
    wait_done("ov1")
    check("[13.4] start_recompose runs recompose(accept) once in the background", ok_start is True
          and RECOMP == ["front"], (ok_start, RECOMP))
    # [13.5] the sleeve option: stored as a param, the made atlas composed again (CPU)
    RECOMP.clear()
    res_sp = gct.set_sleeve_print(CHAR, "ov1", "picture", run=lambda c, i, accept=None: RECOMP.append(accept))
    wait_done("ov1")
    st_sp = gct.dialog_state(CHAR, "ov1")
    check("[13.5] the sleeve option changed: stored, a CPU re-compose started (accept None)",
          res_sp == {"changed": True, "recompose": True} and RECOMP == [None] and SLEEVE_P.get("ov1") == "picture",
          (res_sp, RECOMP))
    check("[13.5] until it is composed again: cut_info 'option' (projection), the dialog not current",
          gt.cut_info(CHAR, "ov1", DRAPE_REC).get("cut_state") == "option" and st_sp.get("option_stale") is True
          and st_sp.get("current") is False and st_sp.get("sleeve_print") == "picture" and st_sp.get("has_sleeves"),
          (gt.cut_info(CHAR, "ov1", DRAPE_REC), st_sp.get("option_stale")))
    n0 = len(backend.calls)
    rec_sp = gct.recompose(CHAR, "ov1")
    check("[13.5] composed again: 0 image jobs, sleeve_print 'picture' in the record, the figure uses it",
          len(backend.calls) == n0 and rec_sp.get("state") == "ready" and rec_sp.get("sleeve_print") == "picture"
          and gt.cut_info(CHAR, "ov1", DRAPE_REC).get("texture") == "cut"
          and (rec_sp["jobs"]["front"]["metrics"].get("fabric_fill") or {}).get("islands") == ["band"],
          (rec_sp.get("state"), rec_sp["jobs"]["front"]["metrics"].get("fabric_fill")))
    try:
        gct.set_sleeve_print(CHAR, "ov1", "glitter")
        check("[13.5] an unknown sleeve option is an error", False)
    except ValueError:
        check("[13.5] an unknown sleeve option is an error", True)
    # [13.6] Redo front over two passed answers, rejected, then Use this answer (review finding 2026-11-21)
    item_fixture("ov2", texture="cut")
    backend.answer = answer_filled
    n0 = len(backend.calls)
    rec_b = gct.generate(CHAR, "ov2")
    stem_o2 = gct.cut_dir(CHAR) / f"ov2_{rec_b['csig']}"
    check("[13.6] both jobs pass first: 2 image calls, ready", len(backend.calls) == n0 + 2
          and rec_b.get("state") == "ready", (len(backend.calls) - n0, rec_b.get("reason")))
    backend.answer = answer_front_green
    n0 = len(backend.calls)
    rec_rf = gct.generate(CHAR, "ov2", only="front")
    check("[13.6] Redo front, rejected: 2 image calls (attempt 2), the re-used back stays 'ready' and its answer on disk",
          len(backend.calls) == n0 + 2 and rec_rf.get("state") == "rejected"
          and rec_rf["jobs"]["front"]["state"] == "rejected" and rec_rf["jobs"]["back"]["state"] == "ready"
          and Path(f"{stem_o2}.raw_back.png").is_file(),
          (len(backend.calls) - n0, rec_rf.get("reason"), rec_rf["jobs"]["back"].get("state")))
    use2 = gct.dialog_state(CHAR, "ov2").get("answers") or {}
    check("[13.6] the dialog offers Use this answer for both shown answers",
          (use2.get("front") or {}).get("can_use") is True and (use2.get("back") or {}).get("can_use") is True, use2)
    sch0 = len(SCHEDULED)
    rec_u2 = gct.recompose(CHAR, "ov2", accept="front")
    check("[13.6] Use this answer: 0 image calls, ready, the atlas composed, the figure re-assembled",
          len(backend.calls) == n0 + 2 and rec_u2.get("state") == "ready"
          and rec_u2["jobs"]["front"].get("accepted") is True and rec_u2["jobs"]["back"]["state"] == "ready"
          and Path(f"{stem_o2}.atlas.png").is_file() and len(SCHEDULED) == sch0 + 1,
          (rec_u2.get("state"), rec_u2.get("reason")))
    pl_o2 = gct.job_plan(CHAR, "ov2")
    check("[13.6] Run all then spends nothing: both answers are kept",
          pl_o2["total"] == 0 and pl_o2["reused"] == ["back", "front"], pl_o2)
    backend.answer = answer_filled

    # [12.13] an old drape (no texture_sha) keeps standing in after the FLOW makes the back view (review finding):
    # ``garment_template_views._publish`` stamps the record's texture part BEFORE the view changes. Hand-derived: the
    # sources before the view are the item picture on both sides -> tex0 = md5(sha(item), sha(item)), the record's
    # tsig is tsig(p, bsha, tex0, ["x:-"]); after the view both sides read the view -> tex1 != tex0 -> a new current
    # key; the record now carries texture_sha tex0, which rebuilds its own tsig -> ``cut_stand_in`` -> "ready".
    from app.core import garment_template_views as tv  # noqa: E402

    def key_stub(character_name, item_id, *, base_sha, lower, item=None):
        src = gt.texture_sources(character_name, item_id)
        return (gt.tsig(p_cut, base_sha=base_sha, texture_sha=gt.texture_sha_of(src), lower=["x:-"]), None, src,
                p_cut, ["x:-"])

    view_src = _back_picture(_backs / "flow_view_src.png", blue=152)

    def real_publish_generate(character_name, item_id, view):
        VIEW_JOBS.append((item_id, view))
        return tv._publish(character_name, item_id, view, view_src, {"source": "render", "attempt": 1})

    def old_drape(iid):
        item_fixture(iid, back=False, texture="cut")
        tsig_old = key_stub(CHAR, iid, base_sha="bsha", lower=[])[0]
        (folder / f"{iid}_{tsig_old}.glb").write_bytes(b"glb")
        (folder / f"{iid}_{tsig_old}.json").write_text(json.dumps(
            {"item_id": iid, "tsig": tsig_old, "accepted": True, "created_at": "2026"}), encoding="utf-8")
        return tsig_old

    from contextlib import ExitStack  # noqa: E402
    with ExitStack() as stack13:        # one block: the outer ``with`` already nests close to Python's limit
        for ctx in (patch.object(gt, "_key", key_stub),
                    patch("app.core.base_body.current_base", lambda c, **k: ("bsig", "bsha")),
                    patch("app.core.figure.worn_sets", lambda c, **k: NS(pieces={}, own=[])),
                    patch("app.models.character.get_character_profile", lambda c, **k: {}),
                    patch("app.core.garment_template_views.generate", real_publish_generate),
                    patch.object(gct, "back_view", lambda c, i: tv.accepted(c, i, "back"))):
            stack13.enter_context(ctx)
        t_o1 = old_drape("old1")
        check("[12.13] before: the old drape is ready by its exact key, without texture_sha",
              gt.drape_state(CHAR, "old1", base_sha="bsha", lower=[]).get("state") == "ready"
              and "texture_sha" not in json.loads((folder / f"old1_{t_o1}.json").read_text(encoding="utf-8")))
        rec_o1 = gct.generate(CHAR, "old1")
        d_o1 = gt.drape_state(CHAR, "old1", base_sha="bsha", lower=[])
        stamped = json.loads((folder / f"old1_{t_o1}.json").read_text(encoding="utf-8")).get("texture_sha")
        src_item = str(ITEM_FILES["old1"])
        check("[12.13] the flow made the back view and the cut is ready",
              rec_o1.get("state") == "ready" and rec_o1.get("back_view", {}).get("made") is True, rec_o1.get("reason"))
        check("[12.13] the record learned its texture part (item picture both sides) before the view changed",
              stamped == gt.texture_sha_of({"front": src_item, "back": src_item}), stamped)
        check("[12.13] after the flow the old drape still stands in (ready, stand_in, its own tsig)",
              d_o1.get("state") == "ready" and d_o1.get("stand_in") is True and d_o1.get("tsig") == t_o1, d_o1)
        # control: the same old drape when nothing stamps it (the code before this fix) -> "missing"
        t_o2 = old_drape("old2")
        no_stamp = patch.object(gt, "stamp_texture_sha", lambda c, i: False)
        no_stamp.start()
        try:
            gct.generate(CHAR, "old2")
        finally:
            no_stamp.stop()
        check("[12.13] control without the stamp: the piece would drop off (missing)",
              gt.drape_state(CHAR, "old2", base_sha="bsha", lower=[]).get("state") == "missing")
        # a manual view change (Remove) stamps too, and a record that has texture_sha is left as it is
        t_o3 = old_drape("old3")
        tv.remove(CHAR, "old3", "front")
        rec3 = json.loads((folder / f"old3_{t_o3}.json").read_text(encoding="utf-8"))
        check("[12.13] Remove stamps the current drape as well", bool(rec3.get("texture_sha")), rec3)
        check("[12.13] a stamped record is not written again", gt.stamp_texture_sha(CHAR, "old3") is False)

check("[8.5] no outbound connection attempt", OUTBOUND == [], OUTBOUND)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
