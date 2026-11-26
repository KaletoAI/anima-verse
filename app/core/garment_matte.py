"""A230: the cut-out of a garment TEMPLATE source picture (the piece-only views and the item picture a template piece
bakes its texture from) — clean enough that no backdrop colour reaches the baked texture.

The old cut (``prepare_view`` before A230: border-connected flood fill within 24 of the median border colour, hard
alpha) left the anti-aliased rim in the piece: a 1-2 px band mixed with the white / grey / green backdrop, which the
orthographic projection bake stretched into light or green streaks along every seam and hem ("Shy Red Dress").

The pipeline (``cut``), CPU only:

1. Backdrop colour ``bg``: the median of the picture's border band (``BORDER_PX``) — any colour, white, grey or the
   green screen the template view prompt now asks for (``garment_template_views.GREEN_LINE``). A picture that already
   has alpha (a stored cut-out, an upload) is composited over the median of its transparent ring next to the piece
   (``RING_PX``) first; the crop padding (exact black, alpha 0) is left out of that estimate.
2. Matte = consensus of
   (a) the backdrop-distance key: ``k = clip((|c - bg| - lo) / KEY_RAMP)`` with ``lo = max(KEY_LO, KEY_SPREAD x
       the border's spread)`` — a soft ramp, not a hard tolerance, and
   (b) the BiRefNet-DIS matte (``models.character.run_rembg``, the mesh-input model already used by the garment /
       footwear cut-outs; a CPU session whose thread count the session code sets explicitly).
   Per pixel ``min(k, m)`` (both must call it the piece), except a colour far from the backdrop (``|c - bg| >=
   lo + KEY_RAMP + KEY_SURE``) which the key alone decides. When the piece is the backdrop's colour (a white
   blouse on white: at least ``LOW_CONTRAST`` of the matte's piece is key-background) the matte alone decides.
   Without a matte (rembg missing / failing) the key alone. Then small holes (< ``HOLE_MAX`` of the piece) are
   filled and components smaller than ``COMPONENT_MIN`` x the largest dropped (a pair of gloves keeps both).
3. Edge decontamination: every pixel with ``0 < alpha < 1`` and the inner rim band (``RIM_PX``) is un-mixed from the
   backdrop: its coverage ``t`` is measured on the line from ``bg`` to the nearest inner colour, the colour becomes
   ``(c - (1 - t) bg) / t``; against a chromatic backdrop the dominant backdrop channel is clamped to
   the other two on the rim (despill) unless the piece itself is of that colour. Then the outer ``DROP_PX`` of the
   piece take the colour of the nearest pixel further in, and every transparent pixel the colour of the nearest
   piece pixel (a sampler that strays over the rim reads the piece, never the backdrop).
4. The alpha written is hard (0 / 255) on the consensus footprint — the projection bake registers by the alpha box,
   so the footprint is not shrunk; only its colours change.

``bake_fill`` (the projection bake's empty texels, ``garment_template_drape.project_bake``) is the numpy push-pull
of step 4 on the texture side; it lives in the Blender script (no scipy there) — this module is the image side."""
from __future__ import annotations

import io
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_matte")

#: Bumped when the same picture cuts differently (part of the reason of ``garment_template.TEMPLATE_VERSIONS`` 8, A230).
#: 2 (A235): enclosed backdrop-coloured holes (the gap of a ring, between chain links) open instead of being filled;
#: thin / near-edge parts are despilled, not only the rim.
MATTE_VERSION = 2
#: Width of the border band the backdrop colour is read from (px).
BORDER_PX = 3
#: Width of the transparent ring next to an already cut piece the backdrop colour is read from (px).
RING_PX = 6
#: The key's lower edge: a colour within this distance (RGB, Euclidean) of the backdrop is backdrop ...
KEY_LO = 22.0
#: ... or within this many times the border band's spread (a noisy / gradient backdrop) ...
KEY_SPREAD = 3.0
#: ... and the key reaches 1 this far above its lower edge (the soft ramp of an anti-aliased rim).
KEY_RAMP = 48.0
#: A colour this far above the ramp's top is the piece whatever the matte says (a flat backdrop has no such colour).
KEY_SURE = 40.0
#: The matte alone decides when at least this share of its piece is key-background (piece = backdrop colour).
#: A235: 0.25 -> 0.03 — measured on stored ghost views: a grey cardigan on grey (0.20) and a wicker bandeau on grey
#: (0.10) lost a third / a sixth of their fabric to the key under 0.25; the bra on green / white, a harness and a
#: lace thong stay below 0.016 (``~/claude-out/a235/matte_measure.json``).
LOW_CONTRAST = 0.03
#: Holes inside the piece smaller than this share of it are filled (specks, a print of the backdrop's colour).
HOLE_MAX = 0.002
#: Components smaller than this share of the largest go (strays); a pair (gloves, shoes) keeps both.
COMPONENT_MIN = 0.05
#: A235: a hole inside the piece whose pixels are at least this share key-background (the backdrop's colour) is the
#: backdrop seen through an opening — it opens whatever its size; the key-background pixels of a larger hole open too.
HOLE_BACKDROP_SHARE = 0.5
#: A235: the despill reaches this far (px) into the piece — thin parts (chains, straps, a dark rim) are all near an edge.
DESPILL_PX = 6
#: Inner rim band (px) whose colours are un-mixed from the backdrop.
RIM_PX = 3
#: The outermost px of the piece whose colours are replaced by the nearest colour further in.
DROP_PX = 2
#: The un-mix of a rim pixel divides by its coverage; below this coverage the pixel takes the inner colour only.
UNMIX_MIN_ALPHA = 0.2
#: The un-mix needs the piece's inner colour at least this far (RGB) from the backdrop (else nothing to tell apart).
UNMIX_MIN_CONTRAST = 30.0
#: A backdrop is chromatic (despill applies) when its channels lie at least this far apart.
CHROMA_MIN = 40.0
#: A pixel counts as backdrop-coloured (the metric ``backdrop_share``) within this distance of the backdrop.
BACKDROP_NEAR = 40.0

#: A235: the hue key of a chromatic backdrop: a pixel whose backdrop channel leads the other two by at least
#: ``HUE_KEY_HI`` x the backdrop's own lead is backdrop, below ``HUE_KEY_LO`` x it the piece (a ramp between).
HUE_KEY_HI = 0.6
HUE_KEY_LO = 0.3

MatteFn = Callable[[np.ndarray], Optional[np.ndarray]]


def birefnet_matte(rgb: np.ndarray) -> Optional[np.ndarray]:
    """The BiRefNet-DIS matte of an (h, w, 3) uint8 picture as float [0, 1] at its size; None when rembg fails."""
    try:
        from PIL import Image
        from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
        buf = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(rgb, np.uint8)).save(buf, format="PNG")
        with Image.open(io.BytesIO(run_rembg(buf.getvalue(), MESH_INPUT_REMBG_MODEL, only_mask=True))) as m:
            mask = m.convert("L")
            if mask.size != (rgb.shape[1], rgb.shape[0]):
                mask = mask.resize((rgb.shape[1], rgb.shape[0]), Image.Resampling.BILINEAR)
            return np.asarray(mask, np.float64) / 255.0
    except Exception as e:  # noqa: BLE001 — the key alone then (documented fallback)
        logger.warning("Garment matte: BiRefNet failed, the backdrop key alone: %s", e)
        return None


def _hue_key(rgb: np.ndarray, bg) -> Optional[np.ndarray]:
    """A235: [0, 1] backdrop-ness by hue for a chromatic ``bg`` (``CHROMA_MIN``), None for a neutral one: the lead of
    the backdrop's dominant channel over the other two, as a share of the backdrop's own lead, ramped from
    ``HUE_KEY_LO`` to ``HUE_KEY_HI``."""
    bg = np.asarray(bg, np.float64)
    if float(bg.max() - bg.min()) < CHROMA_MIN:
        return None
    j = int(np.argmax(bg))
    others = [i for i in range(3) if i != j]
    lead_bg = float(bg[j] - bg[others].max())
    lead = rgb[..., j] - rgb[..., others].max(-1)
    return np.clip((lead / lead_bg - HUE_KEY_LO) / (HUE_KEY_HI - HUE_KEY_LO), 0.0, 1.0)


def _border(rgb: np.ndarray, px: int = BORDER_PX) -> np.ndarray:
    return np.concatenate([rgb[:px].reshape(-1, 3), rgb[-px:].reshape(-1, 3),
                           rgb[:, :px].reshape(-1, 3), rgb[:, -px:].reshape(-1, 3)])


def backdrop_of(samples: np.ndarray) -> Tuple[np.ndarray, float]:
    """``(bg, spread)``: the median colour of ``samples`` (n x 3) and the largest channel's median absolute deviation."""
    s = np.asarray(samples, np.float64).reshape(-1, 3)
    bg = np.median(s, 0)
    spread = float(np.median(np.abs(s - bg), 0).max())
    return bg, spread


def _ring_backdrop(rgb: np.ndarray, alpha: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
    """The backdrop of an already cut picture: the transparent ring next to the piece, crop padding (exact black at
    alpha 0) left out unless nothing else is there. None without a ring."""
    from scipy import ndimage
    piece = alpha >= 128
    if not piece.any():
        return None
    ring = ndimage.binary_dilation(piece, iterations=RING_PX) & (alpha == 0)
    samples = rgb[ring]
    real = samples[samples.max(1) > 0]
    if len(real) >= 20:
        samples = real
    if len(samples) < 20:
        return None
    return backdrop_of(samples)


def backdrop_share(rgba: np.ndarray, bg, *, band: Optional[int] = None) -> Dict[str, Any]:
    """Metric: the share of the piece's pixels (alpha >= 128) within ``BACKDROP_NEAR`` of ``bg`` — of the whole piece
    and of its outer ``band`` px (default ``RIM_PX``)."""
    from scipy import ndimage
    px = np.asarray(rgba)
    piece = px[..., 3] >= 128
    near = np.linalg.norm(px[..., :3].astype(np.float64) - np.asarray(bg, np.float64), axis=-1) <= BACKDROP_NEAR
    rim = piece & ~ndimage.binary_erosion(piece, iterations=band or RIM_PX)
    return {"whole": round(float((near & piece).sum() / max(1, piece.sum())), 4),
            "rim": round(float((near & rim).sum() / max(1, rim.sum())), 4)}


def cut(rgba: np.ndarray, *, matte: Optional[MatteFn] = birefnet_matte,
        keep_alpha: Optional[bool] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The A230 cut of an (h, w, 4) uint8 picture (see the module docstring). ``keep_alpha``: the picture's own alpha
    bounds the piece (a stored cut-out, an upload) — None decides by the picture (more than 2 % transparent).
    Returns the new (h, w, 4) uint8 array and ``info``: ``alpha`` ("kept" / "border"), ``mode`` ("consensus" /
    "matte" / "key"), ``bg``, ``spread``, ``share``, ``holes``, ``components``."""
    from scipy import ndimage
    px = np.asarray(rgba, np.uint8)
    rgb = px[..., :3].astype(np.float64)
    a0 = px[..., 3]
    kept = bool((a0 < 128).mean() > 0.02) if keep_alpha is None else bool(keep_alpha)
    ring = _ring_backdrop(px[..., :3], a0) if kept else None
    if ring is not None:
        bg, spread = ring
    else:
        bg, spread = backdrop_of(_border(rgb))
    if kept:
        # the transparent part composited over the backdrop: the key and the matte see a flat picture
        t = (a0.astype(np.float64) / 255.0)[..., None]
        rgb = rgb * t + bg * (1.0 - t)
    dist = np.linalg.norm(rgb - bg, axis=-1)
    lo = max(KEY_LO, KEY_SPREAD * spread)
    k = np.clip((dist - lo) / KEY_RAMP, 0.0, 1.0)
    k_dist = k
    hue_bg = _hue_key(rgb, bg)
    if hue_bg is not None:
        # A235: a chromatic backdrop (the green screen) is keyed by its HUE too — its shadow in a ring's gap or
        # between chain links is far from the lit backdrop by distance, yet as green as it
        k = np.minimum(k, 1.0 - hue_bg)
        dist = np.where(hue_bg >= 0.5, 0.0, dist)
    m = matte(np.clip(rgb, 0, 255).astype(np.uint8)) if matte is not None else None
    info: Dict[str, Any] = {"alpha": "kept" if kept else "border", "bg": [round(float(v), 1) for v in bg],
                            "spread": round(spread, 1), "matte_version": MATTE_VERSION}
    if m is None:
        alpha, mode = k, "key"
    else:
        m = np.clip(np.asarray(m, np.float64), 0.0, 1.0)
        mat_fg = m >= 0.5
        # the low-contrast share by DISTANCE: a hue-keyed gap (green between chain links) is no sign of a piece
        # in the backdrop's colour
        low = float((mat_fg & (k_dist < 0.5)).sum() / max(1, mat_fg.sum()))
        info["low_contrast"] = round(low, 3)
        if low >= LOW_CONTRAST:
            alpha, mode = m, "matte"
        else:
            alpha = np.minimum(k, m)
            alpha = np.where(dist >= lo + KEY_RAMP + KEY_SURE, 1.0, alpha)
            mode = "consensus"
    if kept:
        alpha = np.minimum(alpha, (a0 >= 128).astype(np.float64))
    info["mode"] = mode
    piece = alpha >= 0.5
    # holes: small ones filled (specks), large ones (an opening, the backdrop between straps) stay
    # A235: enclosed backdrop (a ring's gap, between chain links): every key-background pixel enclosed by the piece
    # that the matte or the soft key had called piece opens — the consensus's min / the sure-key override can enclose it
    # (not when the matte alone decides: a white piece on white is all key-background)
    enclosed_bg = ndimage.binary_fill_holes(piece) & (k < 0.5) if mode != "matte" else np.zeros_like(piece)
    opened = int((enclosed_bg & piece).sum())
    piece &= ~enclosed_bg
    alpha = np.where(enclosed_bg, 0.0, alpha)
    holes = ndimage.binary_fill_holes(piece) & ~piece
    lab, n = ndimage.label(holes)
    filled = 0
    if n and mode != "matte":
        bgish = ndimage.mean((k < 0.5).astype(np.float64), lab, range(1, n + 1))
        holes &= ~np.isin(lab, 1 + np.flatnonzero(np.asarray(bgish) >= HOLE_BACKDROP_SHARE))
        lab, n = ndimage.label(holes)
    if n:
        sizes = ndimage.sum(holes, lab, range(1, n + 1))
        small = np.isin(lab, 1 + np.flatnonzero(sizes < HOLE_MAX * max(1, piece.sum())))
        filled = int(small.sum())
        piece |= small
        alpha = np.where(small, 1.0, alpha)
    lab, n = ndimage.label(piece)
    if n > 1:
        sizes = ndimage.sum(piece, lab, range(1, n + 1))
        keep = 1 + np.flatnonzero(sizes >= COMPONENT_MIN * sizes.max())
        piece = np.isin(lab, keep)
        n = len(keep)
    info.update(holes_filled=filled, holes_opened=opened, components=int(n))
    if kept and piece.sum() < 0.7 * (a0 >= 128).sum():
        # the consensus lost too much of an already cut piece: its own alpha stands, only the colours are cleaned
        piece = a0 >= 128
        alpha = piece.astype(np.float64)
        info["mode"] = mode = "kept_alpha"
    out = np.zeros_like(px)
    out[..., :3] = decontaminate(rgb, alpha, piece, bg)
    out[..., 3] = np.where(piece, 255, 0).astype(np.uint8)
    info["share"] = round(float(piece.mean()), 4)
    return out, info


def decontaminate(rgb: np.ndarray, alpha: np.ndarray, piece: np.ndarray, bg) -> np.ndarray:
    """Step 3 of ``cut``: the rim un-mixed from ``bg`` and despilled, the outer ``DROP_PX`` and everything outside the
    piece filled with the nearest colour further in. uint8 (h, w, 3)."""
    from scipy import ndimage
    bg = np.asarray(bg, np.float64)
    c = np.asarray(rgb, np.float64).copy()
    if not piece.any():
        return np.clip(c, 0, 255).astype(np.uint8)
    inner = ndimage.binary_erosion(piece, iterations=RIM_PX)
    rim = piece & ~inner
    a = np.clip(alpha, 0.0, 1.0)
    soft = rim | (piece & (a < 0.999))
    edge = soft
    if inner.any() and soft.any():
        # the rim's own coverage, measured against the nearest inner colour F: c = bg + t (F - bg); the colour
        # un-mixed is (c - (1 - t) bg) / t — the piece's colour without the backdrop share
        dist_in, idx = ndimage.distance_transform_edt(~inner, return_indices=True)
        # A235: only a rim next to its own inner part un-mixes — a thin part (a chain) far from any inner pixel
        # would be un-mixed against another part's colour; it is despilled below instead
        soft = soft & (dist_in <= 2 * RIM_PX)
        F = c[idx[0][soft], idx[1][soft]]
        d = F - bg
        dd = (d * d).sum(1)
        t = np.clip(((c[soft] - bg) * d).sum(1) / np.maximum(dd, 1e-9), 0.0, 1.0)
        ok = (dd >= UNMIX_MIN_CONTRAST ** 2) & (t >= UNMIX_MIN_ALPHA)
        un = np.clip((c[soft] - (1.0 - t[:, None]) * bg) / np.maximum(t, 1e-9)[:, None], 0, 255)
        weak = (dd >= UNMIX_MIN_CONTRAST ** 2) & (t < UNMIX_MIN_ALPHA)
        cs = c[soft]
        cs[ok] = un[ok]
        cs[weak] = F[weak]
        c[soft] = cs
    if float(bg.max() - bg.min()) >= CHROMA_MIN:
        j = int(np.argmax(bg))
        others = [i for i in range(3) if i != j]
        core = inner if inner.any() else piece
        med = np.median(c[core], 0)
        if med[j] <= med[others].max():           # the piece is not of the backdrop's own colour: despill
            lim = c[..., others].max(-1)
            near_edge = piece & (ndimage.distance_transform_edt(piece) <= DESPILL_PX)
            spill = (edge | near_edge) & (c[..., j] > lim)
            c[spill, j] = lim[spill]
    # the outer DROP_PX and the outside take the nearest colour further in
    core = ndimage.binary_erosion(piece, iterations=DROP_PX)
    # A235: a thin part (a chain, a strap) has no core of its own — it keeps its own (un-mixed, despilled) colours
    # instead of taking a far, thick part's
    core |= piece & ~ndimage.binary_dilation(core, iterations=2 * DROP_PX)
    if not core.any():
        core = piece
    _d, idx = ndimage.distance_transform_edt(~core, return_indices=True)
    fill = ~core
    c[fill] = c[idx[0][fill], idx[1][fill]]
    return np.clip(np.rint(c), 0, 255).astype(np.uint8)


def clean_colours(rgb, mask) -> Tuple[np.ndarray, Dict[str, Any]]:
    """A235: the colours of a piece-only view whose FOOTPRINT is set elsewhere (the shell's ghost mask — the geometry
    stays as it is): ``cut`` with ``mask`` (bool / [0, 1], the view's stored BiRefNet mask) as the matte, so no
    second BiRefNet run. Every pixel outside the cut's piece — the backdrop, a green fringe the mask took in, an
    enclosed gap — takes the nearest piece colour; rim and thin parts are un-mixed and despilled. Returns the (h, w,
    3) uint8 colours and the cut's ``info``."""
    px = np.asarray(rgb)[..., :3]
    m = np.clip(np.asarray(mask, np.float64), 0.0, 1.0)
    rgba = np.dstack([np.clip(px, 0, 255).astype(np.uint8), np.full(px.shape[:2], 255, np.uint8)])
    out, info = cut(rgba, matte=lambda _rgb: m, keep_alpha=False)
    return out[..., :3], info
