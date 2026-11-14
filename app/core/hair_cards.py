"""Hair cards as alpha-tested strips (strand-hair spec 2026-11-13 § 6.1, stage H1).

One procedural strip atlas serves every hair card: ``ATLAS_VARIANTS`` strips side by side, each a few strand lines
whose alpha tapers toward the tip. A card keeps its own UVs and is mapped into the column of its variant
(``variant_uvs``); the scalp cap reads a fixed opaque patch (``SOLID_UV``). The material is glTF ``MASK`` with the
world's cutoff (``alpha_overrides``) — never BLEND, so no sorting is needed.

Texel convention (glTF): ``u`` runs left to right, ``v = 0`` is the TOP image row. HairDeck's cards run ``v = 1`` at
the root to ``v = 0`` at the tip, so the strips are root-dark at the bottom of the image and taper toward the top.

RGB is near-white (luminance 0.75-1.0, darkened to 0.6 at the root): the hair colour stays in ``COLOR_0`` and the
renderer multiplies it with the map. The atlas is deterministic (fixed seed), so a refit reproduces it bit for bit.
"""
from __future__ import annotations

import dataclasses
import functools
import io
import math
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: (width, height) of the strip atlas in pixels.
ATLAS_SIZE: Tuple[int, int] = (1024, 1024)
#: Strip variants side by side; a card's variant is its index mod this.
ATLAS_VARIANTS = 8
#: The opaque patch (alpha 255) in the bottom-right corner — the root end of the last strip, where the strands
#: are densest — in pixels.
SOLID_PATCH_PX = 64
#: The centre of the opaque patch in UV (glTF: v = 0 at the top): the scalp cap's UV.
SOLID_UV: Tuple[float, float] = ((ATLAS_SIZE[0] - SOLID_PATCH_PX / 2) / ATLAS_SIZE[0],
                                 (ATLAS_SIZE[1] - SOLID_PATCH_PX / 2) / ATLAS_SIZE[1])
#: Linear luminance of the opaque patch: the middle of the strands' 0.75-1.0, so the cap reads like the hair
#: around it (a darker cap at the parting was rejected, garment_hairdeck.CAP_COLOUR_PERCENTILE).
SOLID_LUMINANCE = 0.875
#: The atlas's RNG seed — fixed, so every process and every refit writes the same bytes.
ATLAS_SEED = 7
#: The world setting (``config_schema`` ``base_body``) and its clamp.
CUTOFF_KEY = ("base_body", "hair_alpha_cutoff")
CUTOFF_LIMITS: Tuple[float, float] = (0.05, 0.5)


# --- The setting ------------------------------------------------------------------------------------------------

def alpha_cutoff() -> float:
    """The world setting ``base_body.hair_alpha_cutoff``, read live; the schema default when it is unset or not a
    number; clamped to ``CUTOFF_LIMITS``."""
    from app.core import config
    from app.core.config_schema import field_default
    default = float(field_default(*CUTOFF_KEY))
    raw = config.get(".".join(CUTOFF_KEY), default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return round(min(max(value, CUTOFF_LIMITS[0]), CUTOFF_LIMITS[1]), 4)


def alpha_overrides(cutoff: Optional[float] = None) -> Dict[str, Any]:
    """The glTF material keys of a hair card (``glb_mesh.graft`` ``material_overrides``): MASK at ``cutoff`` (the
    world setting when None), double-sided."""
    c = alpha_cutoff() if cutoff is None else float(cutoff)
    return {"alphaMode": "MASK", "alphaCutoff": c, "doubleSided": True}


# --- The atlas --------------------------------------------------------------------------------------------------

def _lin2srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _atlas_rgba() -> np.ndarray:
    """(H, W, 4) float RGBA in [0, 1] (RGB sRGB-encoded). Port of the HAAR spike's ``cards.make_atlas``: per strip
    26-39 strand lines with a slight drift and wave; each ends at 80-100 % of the length, thins over its last
    quarter and fades over its last 18 %. ``s`` below is the distance from the root (0) to the tip (1); the image
    row of ``s`` is ``(1 - s) * H`` (root at the bottom, glTF v = 1)."""
    from scipy import ndimage
    rng = np.random.default_rng(ATLAS_SEED)
    W, H = ATLAS_SIZE
    sw = W // ATLAS_VARIANTS
    lum = np.zeros((H, W))
    alpha = np.zeros((H, W))
    s = 1.0 - (np.arange(H) + 0.5) / H
    px = np.arange(sw) + 0.5
    for var in range(ATLAS_VARIANTS):
        acc_a = np.zeros((H, sw))
        acc_l = np.zeros((H, sw))
        for _ in range(int(rng.integers(26, 40))):
            x0 = rng.uniform(6, sw - 6)
            drift = rng.uniform(-4, 4)
            wav = rng.uniform(0.5, 2.0)
            ph = rng.uniform(0, 2 * math.pi)
            xc = x0 + drift * s + wav * np.sin(2 * np.pi * s * rng.uniform(1.5, 4) + ph)
            s_end = rng.uniform(0.80, 1.0)
            wid = rng.uniform(1.4, 3.2) * np.clip((s_end - s) / 0.25, 0.25, 1.0)
            a_line = np.clip((s_end - s) / 0.18, 0, 1) * rng.uniform(0.75, 1.0)
            cov = np.clip(wid[:, None] / 2 + 0.5 - np.abs(px[None] - xc[:, None]), 0, 1) * a_line[:, None]
            # near-white, darkened toward the root (0.6 at s = 0, full from s = 0.15)
            line_l = rng.uniform(0.75, 1.0) * (0.6 + 0.4 * np.clip(s / 0.15, 0, 1))
            acc_l = acc_l * (1 - cov) + line_l[:, None] * cov
            acc_a = acc_a + cov * (1 - acc_a)
        alpha[:, var * sw:(var + 1) * sw] = acc_a
        lum[:, var * sw:(var + 1) * sw] = np.where(acc_a > 0, acc_l / np.maximum(acc_a, 1e-6), 0.0)
    alpha[H - SOLID_PATCH_PX:, W - SOLID_PATCH_PX:] = 1.0
    lum[H - SOLID_PATCH_PX:, W - SOLID_PATCH_PX:] = SOLID_LUMINANCE
    # bleed the luminance into transparent texels (no dark fringes under filtering and mipmaps)
    filled = alpha > 0.01
    _, idx = ndimage.distance_transform_edt(~filled, return_indices=True)
    lum = lum[idx[0], idx[1]]
    rgb = _lin2srgb(np.clip(lum, 0, 1))
    return np.dstack([rgb, rgb, rgb, alpha])


@functools.lru_cache(maxsize=1)
def strip_atlas() -> bytes:
    """The strip atlas as an RGBA PNG (``ATLAS_SIZE``), deterministic, built once per process."""
    from PIL import Image
    rgba = (np.clip(_atlas_rgba(), 0, 1) * 255 + 0.5).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(out, "PNG", optimize=False)
    return out.getvalue()


# --- Cards and UVs ----------------------------------------------------------------------------------------------

def hairdeck_cards(F: np.ndarray, n_hair: int, n_total: int) -> np.ndarray:
    """The card of each of ``n_total`` vertices: the connected components of the hair faces (``F`` restricted to
    the first ``n_hair`` vertices, ``hair_chains.components``) numbered in order of their first vertex; -1 for
    every vertex at ``index >= n_hair`` (the scalp cap appended by ``fit_hairdeck``)."""
    from app.core.hair_chains import components
    F = np.asarray(F, np.int64).reshape(-1, 3)
    n_hair = int(n_hair)
    n_total = int(n_total)
    if n_hair < 0 or n_total < n_hair:
        raise ValueError(f"hairdeck_cards: {n_hair} hair vertices of {n_total}")
    card = np.full(n_total, -1, np.int64)
    card[:n_hair] = components(F[(F < n_hair).all(1)], n_hair)
    return card


def variant_uvs(uvs: np.ndarray, card: np.ndarray) -> np.ndarray:
    """The card UVs mapped into their variant's column: ``u' = (card % ATLAS_VARIANTS + u) / ATLAS_VARIANTS``, ``v``
    kept (root at v = 1); a vertex of card -1 (the cap) gets ``SOLID_UV``."""
    uv = np.asarray(uvs, np.float64).reshape(-1, 2)
    card = np.asarray(card, np.int64).reshape(-1)
    if len(uv) != len(card):
        raise ValueError(f"variant_uvs: {len(uv)} UVs, {len(card)} card ids")
    out = uv.copy()
    hair = card >= 0
    out[hair, 0] = (card[hair] % ATLAS_VARIANTS + uv[hair, 0]) / ATLAS_VARIANTS
    out[~hair] = SOLID_UV
    return out


def card_faces(indices: np.ndarray, uvs: np.ndarray, card: np.ndarray) -> np.ndarray:
    """``indices`` without the cross sections of the cards: a face whose three vertices lie on one card (id >= 0)
    at one ``v`` (a row) of a card whose ``v`` runs along its length. HairDeck's square tubes close every row with
    such a quad; opaque it is hidden inside the tube, but through alpha-tested sides it would show as a ladder rung
    (it samples one atlas row across the whole strip). Faces of the cap (card -1), every face spanning two rows and
    every face of a card without a ``v`` run (no strand UVs: nothing tells a row) are kept, in order."""
    F = np.asarray(indices, np.int64).reshape(-1, 3)
    card = np.asarray(card, np.int64).reshape(-1)
    if not len(F) or not (card >= 0).any():
        return F
    vv = np.asarray(uvs, np.float64).reshape(-1, 2)[:, 1]
    hair = card >= 0
    lo = np.full(int(card.max()) + 1, np.inf)
    hi = np.full(int(card.max()) + 1, -np.inf)
    np.minimum.at(lo, card[hair], vv[hair])
    np.maximum.at(hi, card[hair], vv[hair])
    v, c = vv[F], card[F]
    one_card = (c[:, 0] >= 0) & (c == c[:, :1]).all(1)
    runs = np.zeros(len(F), bool)
    runs[one_card] = (hi - lo)[c[one_card, 0]] > 1e-9
    cross = one_card & runs & (np.ptp(v, axis=1) < 1e-9)
    return F[~cross]


def texture_garment(garment: Any, card: np.ndarray) -> Any:
    """A copy of the hair ``GarmentMesh`` with the strip atlas as its base colour (``image``, ``mime`` PNG), its
    UVs mapped by ``variant_uvs`` (no roughness map: it would not match those UVs) and its faces without the cards' cross sections (``card_faces``). The material
    keys of the card (MASK, cutoff) are the graft's ``alpha_overrides``, not part of the garment."""
    return dataclasses.replace(garment, image=strip_atlas(), mime="image/png", mr_image=b"", mr_mime="",
                               uvs=variant_uvs(garment.uvs, card),
                               indices=card_faces(garment.indices, garment.uvs, card))


# --- HAAR cards -------------------------------------------------------------------------------------------------

#: A HAAR card's width (m): twice the spread of its strands across it + ``HAAR_WIDTH_PAD_M``, clamped to
#: ``HAAR_WIDTH_LIMITS``, tapered to ``HAAR_TIP_TAPER`` of that at the tip (the spike's ``cards.build``).
HAAR_WIDTH_PAD_M = 0.004
HAAR_WIDTH_LIMITS: Tuple[float, float] = (0.006, 0.030)
HAAR_TIP_TAPER = 0.7
#: The k-means feature weight of the root (it keeps a card's strands growing from one place) and its iterations.
HAAR_ROOT_WEIGHT = 3.0
HAAR_KMEANS_ITER = 20
#: A card row farther than this from the body takes its normal from the head centre (a flyaway), not the SDF.
HAAR_FAR_M = 0.05
#: A strip's inset from the column edges in u (the strand lines start 6 px into a 128 px strip).
HAAR_U_INSET = 0.04
#: Passes of the clearance push of the card vertices.
HAAR_PUSH_ITERATIONS = 6
#: The strip variants a HAAR card uses: all but the last column, whose root end holds the cap's opaque patch
#: (``SOLID_PATCH_PX``). A HAAR card's root lies on the crown in plain view from above; in that column its first
#: segment sampled the patch and showed as a solid chip (Kira, the sample job: ~1/8 of the crown cards).
HAAR_VARIANTS = ATLAS_VARIANTS - 1


def _resample(P: np.ndarray, n: int) -> np.ndarray:
    P = np.asarray(P, np.float64)
    seg = np.linalg.norm(np.diff(P, axis=1), axis=2)
    cum = np.concatenate([np.zeros((len(P), 1)), np.cumsum(seg, 1)], 1)
    out = np.empty((len(P), n, 3))
    for i in range(len(P)):
        q = np.linspace(0, cum[i, -1], n)
        for a in range(3):
            out[i, :, a] = np.interp(q, cum[i], P[i, :, a])
    return out


def haar_cards(X: np.ndarray, sdf, *, n_cards: int = 700, n_seg: int = 16, clear: float = 0.004, seed: int = 0,
               centre: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Alpha cards from draped strands ``X`` (S, P, 3) — the HAAR spike's ``cards.build`` (strand-hair spec § 6.3.1
    step 4) -> ``(V, F, UV, card)``.

    The strands are resampled to ``n_seg + 1`` rows and clustered by k-means (``scipy.cluster.vq.kmeans2``,
    k-means++ seeded by ``seed``, so a refit is bitwise the same) on ``[root * HAAR_ROOT_WEIGHT, row n_seg/3, row
    2 n_seg/3, tip]`` into K = min(``n_cards``, S // 3) clusters. A card is its cluster's mean curve: the normal at
    each row is the body ``sdf``'s gradient (outward; a row farther than ``HAAR_FAR_M`` from the body: radial from
    ``centre`` when given), made perpendicular to the tangent; the width runs across ``tangent x normal``. Each card
    has ``n_seg + 1`` rows of 2 vertices (left, right), root first: card k is vertices ``[2 (n_seg + 1) k, 2 (n_seg +
    1) (k + 1))`` and every card vertex is then pushed ``clear`` out of ``sdf``. ``UV``: the strip atlas, u
    ``HAAR_U_INSET`` .. ``1 - HAAR_U_INSET`` in the column of variant ``k % HAAR_VARIANTS`` (``u' = (variant + u) /
    ATLAS_VARIANTS``), v 1 at the root .. 0 at the tip. ``card`` (n,) the card of each vertex. An empty cluster gives
    no card (cards are renumbered densely)."""
    from scipy.cluster.vq import kmeans2
    from app.core.garment_fit import _unit
    X = np.asarray(X, np.float64)
    if X.ndim != 3 or X.shape[2] != 3 or X.shape[1] < 2:
        raise ValueError(f"haar_cards: strands of shape {X.shape}")
    rows = int(n_seg) + 1
    U = _resample(X, rows)
    feat = np.concatenate([U[:, 0] * HAAR_ROOT_WEIGHT, U[:, n_seg // 3], U[:, 2 * n_seg // 3], U[:, -1]], 1)
    K = min(int(n_cards), len(U) // 3)
    if K < 1:
        raise ValueError(f"haar_cards: {len(U)} strands make no card")
    _, lab = kmeans2(feat, K, seed=int(seed), minit="++", iter=HAAR_KMEANS_ITER)
    taper = np.linspace(1.0, HAAR_TIP_TAPER, rows)
    V, UV, card = [], [], []
    k_out = 0
    for k in range(K):
        m = lab == k
        if not m.any():
            continue
        P = U[m]
        c = P.mean(0)
        tan = _unit(np.gradient(c, axis=0))
        nrm = np.asarray(sdf.grad(c), np.float64)
        if centre is not None:
            far = np.asarray(sdf.sample(c)) > HAAR_FAR_M
            nrm[far] = (c - np.asarray(centre, np.float64))[far]
        nrm = nrm - (nrm * tan).sum(1, keepdims=True) * tan
        nrm = _unit(nrm)
        bi = np.cross(tan, nrm)
        spread = np.abs(((P - c) * bi[None]).sum(2)).max(0) if len(P) > 1 else np.zeros(rows)
        w = np.clip(2 * spread + HAAR_WIDTH_PAD_M, *HAAR_WIDTH_LIMITS) * taper
        half = (bi * (w / 2)[:, None])
        V.append(np.stack([c - half, c + half], 1).reshape(-1, 3))
        v = 1.0 - np.arange(rows) / n_seg
        UV.append(np.stack([np.stack([np.full(rows, HAAR_U_INSET), v], 1),
                            np.stack([np.full(rows, 1 - HAAR_U_INSET), v], 1)], 1).reshape(-1, 2))
        card.append(np.full(2 * rows, k_out, np.int64))
        k_out += 1
    V = np.concatenate(V)
    card = np.concatenate(card)
    UVa = np.concatenate(UV)
    UVa[:, 0] = (card % HAAR_VARIANTS + UVa[:, 0]) / ATLAS_VARIANTS
    a = (np.arange(k_out)[:, None] * 2 * rows + 2 * np.arange(n_seg)[None, :]).ravel()
    F = np.concatenate([np.stack([a, a + 1, a + 3], 1), np.stack([a, a + 3, a + 2], 1)], 1).reshape(-1, 3)
    for _ in range(HAAR_PUSH_ITERATIONS):
        d = np.asarray(sdf.sample(V))
        m = d < clear
        if not m.any():
            break
        V[m] += (clear - d[m])[:, None] * _unit(np.asarray(sdf.grad(V[m])))
    return V, F.astype(np.int64), UVa, card
