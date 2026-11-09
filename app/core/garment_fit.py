"""Garment fit math: place a generated garment mesh on the unrigged base body, push it out of the body, carry it
into the rigged bind space and weight it — pure numpy/scipy on arrays (plan 2026-11-09 phase 4, R1).

A port of the hair spike (``fit_hair.py`` run as ``GARMENT_KIND=hairframe HAIR_SPREAD=0.005
HAIR_SPREAD_DEPTH=0.07``, ``hair_metrics.py``, ``poke.py``). Facts the code relies on:

- The generator body (UniForge) is DOUBLE-WALLED: winding and normals are about 50:50 and never trusted. The body
  is voxelised, its walls closed into one solid by a hole fill, and the push follows the gradient of the signed
  distance of that solid.
- A generated garment has UV-seam duplicates: all geometry work runs on welded positions (``weld``); results are
  scattered back through ``inv``.
- The unrigged base (the generator's mesh) and the rigged base share the UV atlas: a body vertex is found in the
  rigged mesh by its UV, and a garment vertex follows a local similarity (Kabsch with scale) of the body around it.

Units: the unrigged base has its own units (height ~1.0); the rigged base is in metres. Every constant is declared
in METRES (R9) and converted by ``k = rigged / unrigged``, measured by a similarity over the garment's
carrier region (for hair: the Head-weighted vertices, the rigid part between an A-pose source and a T-pose rig).

Clothing (an own-mesh outfit piece, plan ``2026-11-09-base-body-phase5-mesh-items.md`` Task 3) is a port of the dress
spike ``fit_dress.py`` (``fit_clothing``): the same framing; depth by a torso band; the push-out without the crown
spread; a transfer that lets sleeves ride the arms (only forearm/hand excluded above the waist, every arm/shoulder
bone below it); weights by inverse distance from the 8 nearest rigged body vertices, restricted to the rig contract,
and a skirt that blends its leg weights toward Hips down to the hem. Its placement constants are FRACTIONS OF THE
BODY HEIGHT (the spike worked in units of a 1.0-high body = 1.70 m, so at that height they are the spike's numbers);
``k`` is the height ratio rigged / unrigged (the whole body is the carrier; A- and T-pose share the height).

The clothing transfer is SKINNED (``transfer_skinned``, 2026-11-09 sleeve fix): the rigged body IS the unrigged body
posed by linear blend skinning (measured on the e2e base: per-bone rigid fits residual p50 0.6 mm, the whole body as
LBS p99 9 mm, dual quaternions worse), so the garment is carried by the same motion — one rigid transform per bone
recovered from the body correspondence, blended with the skin weights of the body under each garment vertex. The
nearest-donor local-Kabsch transfer (``transfer``, still the hair path) tore a sleeve around the 70-degree A -> T
rotation of the upper arm (adjacent vertices with different donors landed centimetres apart: sleeve area x1.9) and
its 25 smoothing passes folded the tear into the puffed shoulder cap (15 % of the sleeve triangles flipped).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.glb_mesh import BodyMesh, GarmentMesh

# R9 — fit constants in METRES (the spike's unit constants x 1.70)
# Clearance from the REAL body surface. The spike asked for 0.004 units (0.0068 m), but its raw voxel field put the
# zero level ~1.8 voxels outside the surface, and with the field's two-voxel jump in the boundary cell its pushes
# landed 1.5 voxels further out than asked (measured on spheres of 30..75 voxels radius: 3.48..3.52 voxels for a
# 2-voxel request). Its visually verified look therefore had 0.0068 + 1.5 * 0.0034 = 0.0119 m of real clearance.
# ``body_sdf`` measures from the real surface, so the default asks for that distance directly (controller ruling
# 2026-11-09: the default reproduces the spike's look).
CLEAR_M = 0.0119
VOX_M = 0.0034
SPREAD_M = 0.0085
SPREAD_DEPTH_M = 0.119
PROBE_M = 0.068
KABSCH_RES_M = 0.006
HAIR_BLEND_M = 0.15
POKE_TOL_M = 0.0034
# Half height of the depth probe band (spike 0.004 units x 1.70) and the SDF crop margin around the garment.
PROBE_BAND_M = 0.0068
SDF_MARGIN_M = 0.05
# Raw zero level of the voxel SDF outside the true surface, in voxels (see ``body_sdf``).
SDF_ZERO_OFFSET_VOX = 1.3
# Outside the body, voxels up to this many voxels away carry the exact distance to the surface triangles.
SDF_EXACT_BAND_VOX = 6.0
# A vertex counts as moved by the push-out above this displacement (spike 1e-4 units x 1.70).
MOVED_EPS_M = 0.00017
# Loose components below this share of the garment area are dropped in the weld step (R8).
MIN_COMPONENT_SHARE = 0.002
# Spike push-out loop: 8 iterations, the displacement smoothed (6 passes) and spread over the crown in the first 6.
PUSH_ITERATIONS = 8
PUSH_SMOOTH_UNTIL = 6
PUSH_SPREAD_UNTIL = 6
PUSH_SPREAD_K = 48
SMOOTH_PASSES = 6
# Transfer: local Kabsch neighbourhood size, smoothing of the local-minus-global delta, rigged clearance loop.
KABSCH_K = 24
DELTA_SMOOTH_PASSES = 25
RIGGED_ITERATIONS = 10
RIGGED_SMOOTH_UNTIL = 7

# R7 — mesh gates after the fit, in metres / cm^2 / shares.
GATES = {
    "bib_cm2": ("max", 50.0, "bib area in front of the neck"),
    "poke_share": ("max", 0.02, "poke-through share of the crown"),
    "scalp_uncovered_share": ("max", 0.10, "scalp share without hair within 2 cm"),
    "max_push_m": ("max", 0.15, "largest push-out"),
    "moved_share": ("max", 0.90, "share of vertices moved by the push-out"),
    "largest_component_share": ("min", 0.98, "area share of the largest component"),
}

# Clothing (phase 5) — the dress spike ``fit_dress.py``. Placement: fractions of the unrigged body height.
#: Depth band of the garment below its top (spike 0.03 .. 0.15 units on a 1.0-high body).
CLOTHING_DEPTH_BAND = (0.03, 0.15)
#: Half width of the body band the garment band is centred on (spike |x| < 0.12 units).
CLOTHING_BODY_HALF_X = 0.12
#: The waist of the transfer rule: garment top minus this (spike 0.20 units).
CLOTHING_WAIST_DROP = 0.20
# Weights, rigged metres: inverse distance over the 8 nearest rigged body vertices, w = 1 / max(d, 1e-4).
CLOTHING_IDW_K = 8
CLOTHING_IDW_EPS_M = 1e-4
#: A body vertex donates weights to a garment vertex whose neighbours carry only extension bones when at least this
#: share of its weight sits on rig-contract bones.
CONTRACT_DONOR_MIN = 0.5
# Skinned transfer (clothing): a bone gets its own rigid transform from its RIGID CORE — the body vertices carrying
# at least ``BONE_CORE_WEIGHT`` of their weight on it — when that core has ``BONE_CORE_MIN`` vertices (measured on
# the e2e base: every core fits to < 1 mm median, the upper arm's deltoid to 13.6 mm at p99); a blend-only bone (Spine,
# Spine1, the Shoulders, Neck, Thumb1 on the mixamo rig) folds into the bone its vertices co-weight most. Core
# vertices farther than ``BONE_CORE_OUTLIER_M`` from their first fit are UV-twin mismatches and are dropped for a
# second fit. The garment's transfer weights are inverse-distance blends of the body weights of the
# ``TRANSFER_IDW_K`` nearest eligible body vertices.
BONE_CORE_WEIGHT = 0.8
BONE_CORE_MIN = 20
BONE_CORE_OUTLIER_M = 0.05
TRANSFER_IDW_K = 8
# Donor PARTS of the skinned transfer: each arm chain (folded weight on Arm/ForeArm/Hand of one side > this) against
# the rest of the body. A garment vertex takes the weights of the part whose skin is NEAREST to it, blended by inverse
# distance within that part only. In the A-pose the sleeve's underside hangs 1-3 cm from BOTH the inner arm and the
# torso side; an inverse-distance blend over the 8 nearest body vertices of all parts there is a noisy mix of the two
# (adjacent sleeve vertices with arm weight 0 and 1, 3 mm apart on a double-walled garment) and the 70-degree A -> T
# motion tears such neighbours apart. Measured on the e2e dress (sleeve edges whose two faces fold against each
# other, left/right): mixed blend 86/153 flipped triangles; nearest part 16/13 fold edges; a distance RAMP between
# the parts instead (2.5 / 5 / 10 / 20 / 40 mm wide) 27/19, 31/17, 49/21, 65/36, 97/108 — intermediate weights
# across a 70-degree joint collapse toward the pivot and the sleeve underside fans out (dual quaternions did not
# help: 42/25 at 5 mm, 275/282 at 40 mm). So: the nearest part, no ramp.
TRANSFER_PART_ARM_MIN = 0.5
# Web relaxation: triangles stretched beyond this area ratio by the transfer (the fabric that bridged the closed armpit
# of the A-pose and spans the open one in T-pose) have their vertices Laplacian-relaxed for this many passes, the
# rest of the garment fixed, so the stretch spreads over the band instead of alternating slits and folds (renders
# 2026-11-09: 0 passes leaves a sharp pleat under each sleeve, 10 and 25 look alike).
STRETCH_RELAX_RATIO = 3.0
STRETCH_RELAX_PASSES = 10
# Skirt (spike ``SKIRT_KEEP_TOP`` / ``SKIRT_KEEP_HEM``): below crotch + ``SKIRT_ZONE_M`` a garment vertex keeps a share
# of its leg weights — ``SKIRT_KEEP_TOP`` from the crotch up, falling linearly to ``SKIRT_KEEP_HEM`` at the hem — and
# the rest goes to Hips. Crotch = the lowest rigged vertex within ``CROTCH_HALF_X_M`` of the centre line with Hips
# weight > ``CROTCH_HIPS_MIN``.
SKIRT_ZONE_M = 0.05
SKIRT_KEEP_TOP = 0.5
SKIRT_KEEP_HEM = 0.0
CROTCH_HALF_X_M = 0.03
CROTCH_HIPS_MIN = 0.3
#: Slots whose piece may hang over the legs as a skirt (a dress is top + bottom).
SKIRT_SLOTS = frozenset({"bottom", "legs"})
#: ``is_skirt``: the cut through the garment between these heights below the crotch, garment vertices within
#: ``SKIRT_CENTRE_M`` of the centre line.
SKIRT_PROBE_M = (0.01, 0.10)
SKIRT_CENTRE_M = 0.02

# Mesh gates of a fitted clothing piece. Measured 2026-11-09 on the spike dress (UniForge ghost-s52 mesh, decimated
# to 59721 triangles, on the spike bases kira_bald_dis_apose / s1ap_ext) through ``fit_clothing``: max push 0.0501 m
# (spike script: 0.0293 units x 1.70 = 0.0498 m), moved share 0.929 (spike 38720 / 44950 = 0.861 — the product asks
# its clearance from the real surface, see ``CLEAR_M``), largest component 0.9888 after ``drop_small``, rigged inside
# share 0.0 (spike 0.0). Limits: twice the measured push; the moved share refuses only a piece pushed nearly
# everywhere (a loose dress moves 0.93, a tight piece legitimately more); one component as for hair; at most 1 % of
# the vertices left inside the rigged body.
CLOTHING_GATES = {
    "max_push_m": ("max", 0.10, "largest push-out"),
    "moved_share": ("max", 0.99, "share of vertices moved by the push-out"),
    "largest_component_share": ("min", 0.98, "area share of the largest component"),
    "rigged_inside_share": ("max", 0.01, "share of vertices inside the rigged body after the transfer"),
}

_ARM_TOKENS = ("arm", "hand", "shoulder")
_LOWER_ARM_TOKENS = ("forearm", "hand")
_LEG_TOKENS = ("leg", "foot", "toe")


# --- welding / components ------------------------------------------------------------------------------------------

def weld(P, F, U=None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weld duplicates (positions rounded to 1e-6) -> ``(Pw, Fw, inv)`` with ``Pw[inv]`` ~ ``P``.

    Faces collapsing onto fewer than three welded vertices are dropped. ``U`` (the UVs) is only checked for its
    length: UV seams are exactly what is welded away, the caller keeps its per-vertex UVs through ``inv``.
    """
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if U is not None and len(U) != len(P):
        raise ValueError("UV count differs from the vertex count")
    _, first, inv = np.unique(np.round(P, 6), axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    Fw = inv[F]
    keep = (Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])
    return P[first], Fw[keep], inv


def triangle_areas(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    if len(F) == 0:
        return np.zeros(0)
    return 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)


def components(Pw, Fw) -> Tuple[np.ndarray, np.ndarray]:
    """``(labels per vertex, area share per label)`` of the edge-connected components."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    Pw = np.asarray(Pw, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    n = len(Pw)
    E = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    count, labels = connected_components(graph, directed=False)
    area = np.bincount(labels[Fw[:, 0]], weights=triangle_areas(Pw, Fw), minlength=count) if len(Fw) \
        else np.zeros(count)
    total = area.sum()
    return labels, (area / total if total > 0 else np.zeros(count))


def drop_small(Pw, Fw, min_share: float = MIN_COMPONENT_SHARE) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop components below ``min_share`` of the area -> ``(Pk, Fk, keep)``; ``keep`` indexes ``Pw`` (vertices
    used by no remaining face go too)."""
    Pw = np.asarray(Pw, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    labels, share = components(Pw, Fw)
    Fk = Fw[share[labels[Fw[:, 0]]] >= min_share] if len(Fw) else Fw
    keep = np.unique(Fk)
    new = np.full(len(Pw), -1, np.int64)
    new[keep] = np.arange(len(keep))
    return Pw[keep], new[Fk], keep


# --- placement --------------------------------------------------------------------------------------------------------

def _frame(P: np.ndarray, mask) -> Tuple[float, np.ndarray, np.ndarray]:
    """``(mesh units per pixel, mask bbox centre (x, y) px, mesh bbox centre)``; the height is the reliable axis."""
    ys, xs = np.nonzero(np.asarray(mask, bool))
    if len(xs) == 0:
        raise ValueError("Empty mask: nothing to frame")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    lo, hi = P.min(0), P.max(0)
    return float((hi - lo)[1] / (y1 - y0)), np.array([(x0 + x1) / 2, (y0 + y1) / 2]), (lo + hi) / 2


def place_by_framing(Pd, body_P, body_mask, garment_mask) -> np.ndarray:
    """Map garment mesh coordinates into unrigged body coordinates through the shared image framing.

    Both meshes were generated from views with the same framing: the garment vertex goes to image pixels through
    its own mesh/mask frame and from there into the body's. x right = +x, image y down = -y; the depth is scaled
    like x/y and centred on the body (``align_depth`` sets it afterwards).
    """
    Pd = np.asarray(Pd, np.float64)
    body_P = np.asarray(body_P, np.float64)
    sb, cb, mb = _frame(body_P, body_mask)
    sd, cd, md = _frame(Pd, garment_mask)
    px = cd[0] + (Pd[:, 0] - md[0]) / sd
    py = cd[1] - (Pd[:, 1] - md[1]) / sd
    Q = np.empty_like(Pd)
    Q[:, 0] = mb[0] + (px - cb[0]) * sb
    Q[:, 1] = mb[1] - (py - cb[1]) * sb
    Q[:, 2] = mb[2] + (Pd[:, 2] - md[2]) * (sb / sd)
    return Q


def align_depth(Q, head_P, *, probe_u: float, band_u: Optional[float] = None) -> np.ndarray:
    """Shift the garment in z so its crown band is centred on the head band at ``ytop - probe_u``.

    ``ytop`` is the head's top; both bands are ``+- band_u`` high (default a tenth of the probe depth, the spike's
    0.004 at probe 0.04).
    """
    Q = np.array(Q, np.float64)
    head_P = np.asarray(head_P, np.float64)
    band_u = probe_u * 0.1 if band_u is None else band_u
    y = head_P[:, 1].max() - probe_u
    band = head_P[np.abs(head_P[:, 1] - y) < band_u]
    bq = Q[np.abs(Q[:, 1] - y) < band_u]
    if len(band) == 0 or len(bq) == 0:
        raise ValueError("No head or garment vertices at the depth probe height")
    Q[:, 2] += (band[:, 2].max() + band[:, 2].min()) / 2 - (bq[:, 2].max() + bq[:, 2].min()) / 2
    return Q


# --- body SDF / push-out ---------------------------------------------------------------------------------------------

@dataclass
class Sdf:
    """Signed distance of a voxelised solid (negative inside), trilinear sampling."""
    field: np.ndarray
    lo: np.ndarray
    vox: float
    _grad: Tuple[np.ndarray, ...] = ()

    def __post_init__(self):
        self._grad = tuple(np.gradient(self.field))

    def _coords(self, X) -> np.ndarray:
        return ((np.asarray(X, np.float64) - self.lo) / self.vox).T

    def sample(self, X) -> np.ndarray:
        from scipy import ndimage
        return ndimage.map_coordinates(self.field, self._coords(X), order=1, mode="nearest")

    def grad(self, X) -> np.ndarray:
        """The (unnormalised) spatial gradient at ``X``."""
        from scipy import ndimage
        c = self._coords(X)
        return np.stack([ndimage.map_coordinates(g, c, order=1, mode="nearest") for g in self._grad], 1) / self.vox


def _surface_samples(P: np.ndarray, F: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The spike's 5 x 5 barycentric samples (15 per triangle) -> ``(points, triangle index per point)``."""
    tri = P[F]
    steps = np.linspace(0, 1, 5)
    out = [tri[:, 0] * (1 - u - v) + tri[:, 1] * u + tri[:, 2] * v
           for u in steps for v in steps if u + v <= 1 + 1e-9]
    return np.concatenate(out), np.tile(np.arange(len(F)), len(out))


def point_triangle_distance(X: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """Euclidean distance of points ``X`` to triangles ``(A, B, C)`` (broadcasting, last axis xyz; Ericson's
    closest-point regions, degenerate triangles fall back to their edges)."""
    ab, ac, ap = B - A, C - A, X - A
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = X - B
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = X - C
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    eps = 1e-30
    # interior
    denom = va + vb + vc
    v = vb / np.where(np.abs(denom) > eps, denom, eps)
    w = vc / np.where(np.abs(denom) > eps, denom, eps)
    closest = A + ab * v[..., None] + ac * w[..., None]

    def seg(P0, P1):
        d = P1 - P0
        t = np.clip(((X - P0) * d).sum(-1) / np.maximum((d * d).sum(-1), eps), 0, 1)
        return P0 + d * t[..., None]
    regions = [
        (d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (d6 >= 0) & (d5 <= d6),
        (vc <= 0) & (d1 >= 0) & (d3 <= 0), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
        (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0),
    ]
    points = [A, B, C, seg(A, B), seg(A, C), seg(B, C)]
    done = np.zeros(d1.shape, bool)
    for region, point in zip(regions, points):
        region = region & ~done
        closest = np.where(region[..., None], np.broadcast_to(point, closest.shape), closest)
        done |= region
    # degenerate triangles: nearest of the three edges
    degenerate = np.linalg.norm(np.cross(ab, ac), axis=-1) <= 1e-18
    if degenerate.any():
        edge = [seg(A, B), seg(A, C), seg(B, C)]
        dist = np.stack([np.linalg.norm(X - e, axis=-1) for e in edge], -1)
        pick = np.take_along_axis(np.stack(edge, -2), dist.argmin(-1)[..., None, None], -2)[..., 0, :]
        closest = np.where(degenerate[..., None], pick, closest)
    return np.linalg.norm(X - closest, axis=-1)


def body_sdf(P, F, *, vox: float, bounds, zero_offset_vox: Optional[float] = None,
             exact_band_vox: float = SDF_EXACT_BAND_VOX) -> Sdf:
    """Signed distance field of the body solid on a grid cropped to ``bounds = (lo, hi)``.

    Surface voxelisation at the 5 x 5 barycentric samples, one dilation, hole fill, EDT difference (spike), with:
    - The solid (dilated surface + hole fill) is decided on a grid over the WHOLE body plus the bounds, aligned
      with the crop; only the distance fields are cropped. A fill on the crop alone leaks wherever the crop cuts
      the body (the cut cross-section is open), and the neck would read as outside.
    - Each EDT is taken half a voxel back (it measures to the nearest voxel CENTRE of the other set), so the field
      is continuous across the boundary instead of jumping by two voxels within one cell.
    - The zero level is put ON the surface: the dilation and the voxel rounding put it ``SDF_ZERO_OFFSET_VOX``
      (1.3) voxels outside (measured on spheres of 10 to 75 voxels radius: 1.25..1.39, spread +- 0.15), so that
      much is added and a clearance means distance from the real surface. A median over the surface samples
      would be pulled inward by the inner wall of a double-walled body. ``zero_offset_vox=0`` keeps the raw
      level.
    - Outside the body, within ``exact_band_vox`` voxels, the field is the EXACT distance to the surface (nearest
      of the triangles of the 8 nearest surface samples). The voxel EDT is up to 0.6 voxel short along diagonal
      directions, and the clearance is decided exactly in this band. Inside, the corrected EDT stays (it only
      sets how far the first push goes; the iterations converge outside). The nearest outside triangles are the
      outer wall, so a double wall does not disturb the band.
    Inside distances near the crop faces may be overestimated (the nearest outside voxel can lie beyond the
    crop); the crop margin keeps that away from the garment.
    """
    from scipy import ndimage
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    lo, hi = (np.asarray(b, np.float64) for b in bounds)
    shape = np.ceil((hi - lo) / vox).astype(np.int64) + 1
    if (shape < 3).any():
        raise ValueError("SDF bounds are too small")
    if len(F) == 0:
        raise ValueError("The body has no triangles")
    # full grid, aligned with the crop: whole voxels before lo and after the crop's end
    before = np.maximum(np.ceil((lo - (P.min(0) - 2 * vox)) / vox), 0).astype(np.int64)
    after = np.maximum(np.ceil(((P.max(0) + 2 * vox) - (lo + (shape - 1) * vox)) / vox), 0).astype(np.int64)
    full_lo = lo - before * vox
    full_shape = shape + before + after
    pts, tri_of = _surface_samples(P, F)
    idx = np.clip(np.round((pts - full_lo) / vox).astype(np.int64), 0, full_shape - 1)
    surf = np.zeros(tuple(full_shape), bool)
    surf[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    surf = ndimage.binary_dilation(surf, iterations=1)
    inside_full = ndimage.binary_fill_holes(surf)
    del surf
    crop = tuple(slice(int(b), int(b + n)) for b, n in zip(before, shape))
    inside = np.ascontiguousarray(inside_full[crop])
    del inside_full
    offset = SDF_ZERO_OFFSET_VOX if zero_offset_vox is None else zero_offset_vox
    # each EDT measures to the nearest voxel CENTRE of the other set; half a voxel off each side makes the field
    # continuous with slope ~1 across the boundary (the plain difference jumps by 2 voxels within one cell)
    field = np.where(inside, 0.5 - ndimage.distance_transform_edt(inside),
                     ndimage.distance_transform_edt(~inside) - 0.5)
    field = (field + offset) * vox
    if exact_band_vox > 0:
        _exact_outside_band(field, lo, vox, P, F, pts, tri_of, exact_band_vox)
    return Sdf(field=field, lo=lo, vox=float(vox))


def _exact_outside_band(field: np.ndarray, lo: np.ndarray, vox: float, P: np.ndarray, F: np.ndarray,
                        pts: np.ndarray, tri_of: np.ndarray, band_vox: float, k: int = 8) -> None:
    """Replace the outside band ``0 < field <= band_vox`` voxels by the exact distance to the nearest of the
    triangles of their ``k`` nearest surface samples (in place)."""
    from scipy.spatial import cKDTree
    band = (field > 0) & (field <= band_vox * vox)
    cells = np.argwhere(band)
    if len(cells) == 0:
        return
    X = lo + cells * vox
    reach = (band_vox + 2) * vox
    near = ((pts >= X.min(0) - reach) & (pts <= X.max(0) + reach)).all(1)
    if not near.any():
        return
    _, nn = cKDTree(pts[near]).query(X, k=min(k, int(near.sum())))
    nn = nn.reshape(len(X), -1)
    tris = F[tri_of[near][nn]]                                  # (n, k, 3)
    exact = np.full(len(X), np.inf)
    for start in range(0, len(X), 65536):
        sl = slice(start, start + 65536)
        t = tris[sl]
        d = point_triangle_distance(X[sl, None, :], P[t[..., 0]], P[t[..., 1]], P[t[..., 2]])
        exact[sl] = d.min(1)
    field[tuple(cells.T)] = exact


def _adjacency(F: np.ndarray, n: int):
    """Row-normalised edge adjacency (edges counted per face, like the spike's ``np.add.at``)."""
    from scipy.sparse import coo_matrix
    F = np.asarray(F, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = np.concatenate([E, E[:, ::-1]])
    A = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)).tocsr()
    deg = np.asarray(A.sum(1)).ravel()
    return A, np.maximum(deg, 1)[:, None]


def _smooth(D: np.ndarray, adjacency, passes: int) -> np.ndarray:
    A, deg = adjacency
    for _ in range(passes):
        D = 0.5 * D + 0.5 * (A @ D) / deg
    return D


def _unit(g: np.ndarray) -> np.ndarray:
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)


def push_out(Q0, Fd, sdf: Sdf, *, clear: float, spread: float = 0.0, spread_depth: float = 0.0,
             iterations: int = PUSH_ITERATIONS, smooth_until: int = PUSH_SMOOTH_UNTIL,
             spread_until: int = PUSH_SPREAD_UNTIL) -> Tuple[np.ndarray, np.ndarray]:
    """Push garment vertices to at least ``clear`` outside the body -> ``(Q, disp)``.

    Each iteration adds ``max(clear - d, 0)`` along the SDF gradient. While ``it < spread_until`` the crown
    (``y > top - spread_depth``) takes, per vertex, the largest displacement found within ``spread`` (cKDTree, up to
    48 neighbours): an inner hair layer pushed out carries the outer layer with it instead of poking through. While
    ``it < smooth_until`` the displacement is smoothed over the mesh (6 passes); the last iterations enforce the
    clearance exactly.
    """
    from scipy.spatial import cKDTree
    Q0 = np.asarray(Q0, np.float64)
    n = len(Q0)
    adjacency = _adjacency(Fd, n)
    crown = Q0[:, 1] > Q0[:, 1].max() - spread_depth
    disp = np.zeros_like(Q0)
    rows = np.arange(n)
    for it in range(iterations):
        X = Q0 + disp
        need = np.clip(clear - sdf.sample(X), 0, None)
        disp = disp + need[:, None] * _unit(sdf.grad(X))
        if spread > 0 and it < spread_until and crown.any():
            X = Q0 + disp
            dist, nn = cKDTree(X).query(X, k=min(PUSH_SPREAD_K, n), distance_upper_bound=spread)
            dist, nn = dist.reshape(n, -1), nn.reshape(n, -1)
            nn = np.where(np.isinf(dist), rows[:, None], nn)
            mag = np.linalg.norm(disp, axis=1)[nn]
            spread_disp = disp[nn[rows, mag.argmax(1)]]
            disp = np.where(crown[:, None], spread_disp, disp)
        if it < smooth_until:
            disp = _smooth(disp, adjacency, SMOOTH_PASSES)
    return Q0 + disp, disp


# --- transfer into the rigged bind space ----------------------------------------------------------------------------

def similarity(A: np.ndarray, B: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Least-squares similarity ``B ~ s R (A - a) + b`` (Umeyama) -> ``(s, R, a, b)``."""
    a, b = A.mean(0), B.mean(0)
    A0, B0 = A - a, B - b
    U, S, Vt = np.linalg.svd(A0.T @ B0)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    s = float((S * np.array([1.0, 1.0, d])).sum() / max((A0 ** 2).sum(), 1e-30))
    return s, R, a, b


def dense_weights(body: BodyMesh) -> np.ndarray:
    """``(n, n_joints)`` weights of a skinned body."""
    nj = max(len(body.joint_names), int(body.joints.max()) + 1 if body.joints.size else 0)
    W = np.zeros((len(body.positions), nj))
    np.add.at(W, (np.repeat(np.arange(len(body.positions)), 4), body.joints.ravel()), body.weights.ravel())
    return W


def joint_index(body: BodyMesh, key: str) -> int:
    """Skin index of the joint whose ``norm_bone_name`` is ``key``; KeyError naming it otherwise."""
    from app.core.rig_contract import norm_bone_name
    for i, name in enumerate(body.joint_names):
        if norm_bone_name(name) == key:
            return i
    raise KeyError(f"The rigged body has no joint '{key}'")


def uv_correspondence(body_unrigged: BodyMesh, body_rigged: BodyMesh) -> Tuple[np.ndarray, np.ndarray]:
    """``(rigged index per unrigged body vertex, UV distance)`` through the shared UV atlas."""
    from scipy.spatial import cKDTree
    dist, corr = cKDTree(body_rigged.uvs).query(body_unrigged.uvs)
    if np.median(dist) > 1e-4:
        raise ValueError("The rigged base does not share the UV atlas of the unrigged base "
                         f"(median UV distance {np.median(dist):.2e})")
    return corr, dist


def region_similarity(body_unrigged: BodyMesh, body_rigged: BodyMesh, corr: np.ndarray, mask: np.ndarray):
    """Similarity unrigged -> rigged over the body vertices in ``mask`` (through the UV correspondence)."""
    if mask.sum() < 4:
        raise ValueError("Too few body vertices for a similarity fit")
    return similarity(body_unrigged.positions[mask], body_rigged.positions[corr[mask]])


def transfer(Q, body_unrigged: BodyMesh, body_rigged: BodyMesh, *, faces, k: int = KABSCH_K,
             res_max_m: float = KABSCH_RES_M, clear_m: float = CLEAR_M, vox_m: float = VOX_M,
             margin_m: float = SDF_MARGIN_M, split_y: Optional[float] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Carry welded garment positions ``Q`` (unrigged units) into the rigged bind space (metres) -> ``(X, report)``.

    1. Each garment vertex takes the nearest unrigged body vertex that is not arm/hand/shoulder (weight < 0.2).
       With ``split_y`` (clothing, unrigged units) a garment vertex at or above it excludes only forearm/hand, so a
       sleeve rides the upper arm through the A -> T motion; below it every arm/shoulder bone is excluded (a skirt
       next to a hanging hand stays on the hips).
    2. Per used body vertex a local similarity (Kabsch with scale) over its ``k`` nearest body vertices maps them
       onto their rigged twins; a neighbourhood whose residual exceeds ``res_max_m`` (it spans two body parts)
       is bad, and its garment vertices borrow the transform of the nearest garment vertex with a good one.
    3. The local result minus one global similarity is smoothed 25 passes over the garment mesh and added back:
       large motions stay, per-vertex jumps go. The global similarity is fit over the body vertices of the good
       neighbourhoods — the region the garment rides on. (The spike fit a fixed torso band; on a T-pose rig the
       spine-weighted region deforms with the shoulders and gives scales of 1.15..1.6 instead of 1.70.)
    4. A clearance pass on the rigged body (SDF in metres, 10 iterations, smoothed in the first 7).
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    Q = np.asarray(Q, np.float64)
    Pb, Pr = body_unrigged.positions, body_rigged.positions
    adjacency = _adjacency(faces, len(Q))
    corr, uv_dist = uv_correspondence(body_unrigged, body_rigged)
    Wb = dense_weights(body_rigged)[corr]

    def eligible(tokens) -> np.ndarray:
        cols = [i for i, n in enumerate(body_rigged.joint_names) if any(t in norm_bone_name(n) for t in tokens)]
        ok = Wb[:, cols].sum(1) < 0.2 if cols else np.ones(len(Pb), bool)
        candidates = np.nonzero(ok)[0]
        if len(candidates) == 0:
            raise ValueError("No body vertex is eligible for the garment transfer")
        return candidates

    def nearest_of(candidates, points) -> np.ndarray:
        return candidates[cKDTree(Pb[candidates]).query(points)[1]]
    nearest = nearest_of(eligible(_ARM_TOKENS), Q)
    if split_y is not None:
        upper = Q[:, 1] >= split_y
        if upper.any():
            nearest[upper] = nearest_of(eligible(_LOWER_ARM_TOKENS), Q[upper])

    used, li = np.unique(nearest, return_inverse=True)
    # neighbourhoods over UNIQUE body positions: UV-seam and pole duplicates would make one degenerate
    _, distinct = np.unique(np.round(Pb, 6), axis=0, return_index=True)
    kk = min(k, len(distinct))
    _, nb = cKDTree(Pb[distinct]).query(Pb[used], k=kk)
    nb = distinct[nb.reshape(len(used), kk)]
    A, B = Pb[nb], Pr[corr[nb]]
    Am, Bm = A.mean(1, keepdims=True), B.mean(1, keepdims=True)
    A0, B0 = A - Am, B - Bm
    U_, S_, Vt = np.linalg.svd(np.einsum("nki,nkj->nij", A0, B0))
    D = np.sign(np.linalg.det(np.einsum("nij,njk->nik", Vt.transpose(0, 2, 1), U_.transpose(0, 2, 1))))
    D[D == 0] = 1.0
    Dm = np.zeros((len(used), 3, 3))
    Dm[:, 0, 0] = 1
    Dm[:, 1, 1] = 1
    Dm[:, 2, 2] = D
    Rm = np.einsum("nij,njk,nkl->nil", Vt.transpose(0, 2, 1), Dm, U_.transpose(0, 2, 1))
    sc = (S_ * np.stack([np.ones_like(D), np.ones_like(D), D], 1)).sum(1) / np.maximum((A0 ** 2).sum((1, 2)), 1e-30)
    res = np.sqrt(((sc[:, None, None] * np.einsum("nij,nkj->nki", Rm, A0) - B0) ** 2).sum(2).mean(1))
    # a flat-line (rank < 2) neighbourhood has no defined rotation
    good = (res < res_max_m) & (S_[:, 1] > 1e-9 * np.maximum(S_[:, 0], 1e-30)) & (S_[:, 0] > 0)
    if not good.any():
        raise ValueError("No body neighbourhood maps onto the rigged body (all Kabsch residuals too large)")
    X = Bm[li, 0] + sc[li, None] * np.einsum("nij,nj->ni", Rm[li], Q - Am[li, 0])
    g = good[li]
    if (~g).any():
        gi = np.nonzero(g)[0]
        _, kn = cKDTree(Q[gi]).query(Q[~g])
        src = li[gi[kn]]
        X[~g] = Bm[src, 0] + sc[src, None] * np.einsum("nij,nj->ni", Rm[src], Q[~g] - Am[src, 0])

    # the smooth reference: one similarity over the body region the garment rides on (the good neighbourhoods)
    region = np.zeros(len(Pb), bool)
    region[nb[good].ravel()] = True
    s, R, a, b = region_similarity(body_unrigged, body_rigged, corr, region)
    Xg = b + s * (Q - a) @ R.T
    X = Xg + _smooth(X - Xg, adjacency, DELTA_SMOOTH_PASSES)

    lo, hi = X.min(0) - margin_m, X.max(0) + margin_m
    sdf = body_sdf(Pr, body_rigged.faces, vox=vox_m, bounds=(lo, hi))
    Xd = np.zeros_like(X)
    for it in range(RIGGED_ITERATIONS):
        Y = X + Xd
        Xd = Xd + np.clip(clear_m - sdf.sample(Y), 0, None)[:, None] * _unit(sdf.grad(Y))
        if it < RIGGED_SMOOTH_UNTIL:
            Xd = _smooth(Xd, adjacency, SMOOTH_PASSES)
    X = X + Xd
    d = sdf.sample(X)
    report = {
        "scale_k": float(np.median(sc)),
        "global_scale": s,
        "uv_dist_p99": float(np.percentile(uv_dist, 99)),
        "kabsch_res_median_m": float(np.median(res)),
        "neighbourhoods": int(len(used)),
        "bad_neighbourhoods": int((~good).sum()),
        "borrowing": int((~g).sum()),
        "rigged_push_max_m": float(np.linalg.norm(Xd, axis=1).max()) if len(Xd) else 0.0,
        "rigged_clearance_p1_m": float(np.percentile(d, 1)),
        "rigged_inside_share": float((d < 0).mean()),
    }
    return X, report


# --- skinned transfer (clothing) ------------------------------------------------------------------------------------------

@dataclass
class BoneTransforms:
    """One rigid transform per skin joint, ``k * unrigged -> rigged`` (metres): ``X = R[b] @ x + t[b]``.

    ``has[b]`` says the joint carries enough body weight for its own transform; ``fold[b]`` is the joint whose
    transform a joint without one uses (itself when ``has``). ``report`` holds the body's own LBS residual.
    """
    R: np.ndarray                      # (nj, 3, 3)
    t: np.ndarray                      # (nj, 3)
    has: np.ndarray                    # (nj,) bool
    fold: np.ndarray                   # (nj,) int
    report: Dict[str, Any] = field(default_factory=dict)

    def fold_weights(self, W: np.ndarray) -> np.ndarray:
        """Dense weights ``(n, nj)`` with every weight moved onto a joint that has a transform."""
        out = np.zeros_like(W)
        for j in range(W.shape[1]):
            out[:, self.fold[j]] += W[:, j]
        return out

    def apply(self, Xk: np.ndarray, W: np.ndarray) -> np.ndarray:
        """Linear blend skinning of points ``Xk`` (already scaled by ``k``) with folded dense weights ``W``."""
        out = np.zeros_like(Xk)
        for j in np.nonzero(self.has)[0]:
            w = W[:, j]
            rows = np.nonzero(w)[0]
            if len(rows):
                out[rows] += w[rows, None] * (Xk[rows] @ self.R[j].T + self.t[j])
        return out

def _kabsch(P: np.ndarray, Q: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Rigid ``Q ~ R P + t`` (least squares, det +1) -> ``(R, t)``."""
    a, b = P.mean(0), Q.mean(0)
    U, _, Vt = np.linalg.svd((P - a).T @ (Q - b))
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, b - R @ a


def bone_transforms(body_unrigged: BodyMesh, body_rigged: BodyMesh, corr: np.ndarray, k: float, *,
                    core_weight: float = BONE_CORE_WEIGHT, core_min: int = BONE_CORE_MIN) -> BoneTransforms:
    """Recover the pose change unrigged -> rigged as one rigid transform per bone.

    The rigged body is the unrigged body posed by linear blend skinning with its own weights. Each bone with a
    rigid core (``core_min`` body vertices with >= ``core_weight`` of their weight on it) gets the Kabsch fit of
    that core, ``k * unrigged -> rigged``, refit once without vertices farther than ``BONE_CORE_OUTLIER_M`` from
    the first fit (UV-twin mismatches). A bone without a core — a blend-only bone — folds into the bone its
    vertices co-weight most (a joint least-squares over all bones puts arbitrary affine motion on such bones:
    measured p99 44 mm against 9 mm for the folds). The report carries the residual of the whole body skinned by
    the result (p50 / p99, metres) and the folds.
    """
    Pb, Pr = body_unrigged.positions, body_rigged.positions
    W = dense_weights(body_rigged)[corr]
    W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
    nj = W.shape[1]
    A = Pb * float(k)
    B = Pr[corr]
    R = np.tile(np.eye(3), (nj, 1, 1))
    t = np.zeros((nj, 3))
    has = np.zeros(nj, bool)
    for j in range(nj):
        core = np.nonzero(W[:, j] >= core_weight)[0]
        if len(core) < core_min:
            continue
        R[j], t[j] = _kabsch(A[core], B[core])
        keep = np.linalg.norm(A[core] @ R[j].T + t[j] - B[core], axis=1) <= BONE_CORE_OUTLIER_M
        if keep.sum() >= max(core_min, 4) and not keep.all():
            R[j], t[j] = _kabsch(A[core[keep]], B[core[keep]])
        has[j] = True
    if not has.any():
        raise ValueError("No bone of the rigged body has a rigid core")
    total = W.sum(0)
    fold = np.arange(nj)
    for j in np.nonzero(~has)[0]:
        rows = W[:, j] > 0
        co = W[rows].sum(0) if rows.any() else np.zeros(nj)
        co[~has] = -1.0
        fold[j] = int(co.argmax()) if co.max() > 0 else int(np.where(has, total, -1.0).argmax())
    out = BoneTransforms(R=R, t=t, has=has, fold=fold)
    res = np.linalg.norm(out.apply(A, out.fold_weights(W)) - B, axis=1)
    out.report = {
        "bones": int(has.sum()),
        "folded": {body_rigged.joint_names[j]: body_rigged.joint_names[fold[j]] for j in np.nonzero(~has)[0]
                   if total[j] > 0},
        "body_lbs_res_p50_m": float(np.median(res)),
        "body_lbs_res_p99_m": float(np.percentile(res, 99)),
    }
    return out


def relax_stretched(X: np.ndarray, X0: np.ndarray, faces, adjacency, *, ratio: float = STRETCH_RELAX_RATIO,
                    passes: int = STRETCH_RELAX_PASSES) -> int:
    """Laplacian-relax (in place) the vertices of triangles whose area grew beyond ``ratio`` times their area in
    ``X0``, every other vertex fixed -> the number of relaxed vertices."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if passes <= 0 or len(F) == 0:
        return 0
    a0, a1 = triangle_areas(X0, F), triangle_areas(X, F)
    stretched = a1 > ratio * np.maximum(a0, 1e-12)
    free = np.zeros(len(X), bool)
    free[F[stretched].ravel()] = True
    if not free.any():
        return 0
    A, deg = adjacency
    for _ in range(passes):
        mean = (A @ X) / deg
        X[free] = 0.5 * X[free] + 0.5 * mean[free]
    return int(free.sum())


def _donor_parts(Wb: np.ndarray, joint_names) -> np.ndarray:
    """Part per body vertex from its (folded) weights: 0 = the rest of the body, 1 = the left arm chain, 2 = the
    right (Arm / ForeArm / Hand bones of that side carry more than ``TRANSFER_PART_ARM_MIN``)."""
    from app.core.rig_contract import norm_bone_name
    parts = np.zeros(len(Wb), np.int64)
    for part, side in ((1, "left"), (2, "right")):
        cols = [i for i, n in enumerate(joint_names)
                if norm_bone_name(n).startswith(side) and any(t in norm_bone_name(n) for t in ("arm", "hand"))]
        if cols:
            parts[Wb[:, cols].sum(1) > TRANSFER_PART_ARM_MIN] = part
    return parts


def transfer_skinned(Q, body_unrigged: BodyMesh, body_rigged: BodyMesh, *, faces, k: float, split_y: float,
                     idw_k: int = TRANSFER_IDW_K, clear_m: float = CLEAR_M, vox_m: float = VOX_M,
                     margin_m: float = SDF_MARGIN_M,
                     rigged_iterations: int = RIGGED_ITERATIONS) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Carry welded clothing positions ``Q`` (unrigged units) into the rigged bind space (metres) by the body's own
    skinning -> ``(X, report)``.

    1. ``bone_transforms``: one rigid transform per bone, ``k * unrigged -> rigged``.
    2. Each garment vertex takes the inverse-distance blend (``idw_k`` nearest, ``w = 1 / max(d, 1e-4 / k)``) of the
       body weights of the ELIGIBLE unrigged body vertices around it — the same rule as ``transfer``: at or above
       ``split_y`` only forearm/hand donors are excluded (a sleeve rides the upper arm through the A -> T motion),
       below it every arm/shoulder bone (a skirt next to a hanging hand stays on the hips). The blend is taken within
       ONE PART (``_donor_parts``: each arm chain, the rest) — the part whose skin is nearest to the garment vertex —
       so a sleeve hanging next to the torso is a sleeve and not a noisy mix of arm and torso.
    3. Linear blend skinning of ``k * Q`` with those weights (the body itself is skinned that way). A vertex far
       from the skin keeps its distance to the bone it rides (a rigid motion), the blend zone of a joint deforms like
       the skin under it — no tear between neighbours with different donors, nothing to smooth over. The fabric
       that bridged the closed armpit of the A-pose spans the open one in T-pose; ``relax_stretched`` spreads that
       stretch over its band.
    4. The clearance pass on the rigged body (SDF in metres, ``rigged_iterations`` iterations, smoothed in the
       first ``RIGGED_SMOOTH_UNTIL``), as in ``transfer``.
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    Q = np.asarray(Q, np.float64)
    Pb, Pr = body_unrigged.positions, body_rigged.positions
    adjacency = _adjacency(faces, len(Q))
    corr, uv_dist = uv_correspondence(body_unrigged, body_rigged)
    bones = bone_transforms(body_unrigged, body_rigged, corr, k)
    Wb = bones.fold_weights(dense_weights(body_rigged)[corr])
    Wb /= np.maximum(Wb.sum(1, keepdims=True), 1e-12)

    def eligible(tokens) -> np.ndarray:
        cols = [i for i, n in enumerate(body_rigged.joint_names) if any(t in norm_bone_name(n) for t in tokens)]
        ok = Wb[:, cols].sum(1) < 0.2 if cols else np.ones(len(Pb), bool)
        candidates = np.nonzero(ok)[0]
        if len(candidates) == 0:
            raise ValueError("No body vertex is eligible for the garment transfer")
        return candidates

    parts = _donor_parts(Wb, body_rigged.joint_names)

    def blend(candidates, rows) -> np.ndarray:
        """Inverse-distance weights of the garment rows over the ``candidates`` of their nearest part."""
        best_d = np.full(len(rows), np.inf)
        out = np.zeros((len(rows), Wb.shape[1]))
        found = False
        for part in range(3):
            cand = candidates[parts[candidates] == part]
            if len(cand) == 0:
                continue
            found = True
            kk = min(idw_k, len(cand))
            dist, nn = cKDTree(Pb[cand]).query(Q[rows], k=kk)
            dist, nn = dist.reshape(len(rows), -1), nn.reshape(len(rows), -1)
            w = 1.0 / np.maximum(dist, CLOTHING_IDW_EPS_M / k)
            w /= w.sum(1, keepdims=True)
            nearer = dist[:, 0] < best_d
            out[nearer] = np.einsum("nk,nkj->nj", w[nearer], Wb[cand[nn[nearer]]])
            best_d[nearer] = dist[nearer, 0]
        if not found:
            raise ValueError("No body vertex is eligible for the garment transfer")
        return out
    upper = Q[:, 1] >= split_y
    Wg = np.zeros((len(Q), Wb.shape[1]))
    if (~upper).any():
        Wg[~upper] = blend(eligible(_ARM_TOKENS), np.nonzero(~upper)[0])
    if upper.any():
        Wg[upper] = blend(eligible(_LOWER_ARM_TOKENS), np.nonzero(upper)[0])
    X = bones.apply(Q * float(k), Wg)
    relaxed = relax_stretched(X, Q * float(k), faces, adjacency)

    lo, hi = X.min(0) - margin_m, X.max(0) + margin_m
    sdf = body_sdf(Pr, body_rigged.faces, vox=vox_m, bounds=(lo, hi))
    Xd = np.zeros_like(X)
    for it in range(rigged_iterations):
        Y = X + Xd
        Xd = Xd + np.clip(clear_m - sdf.sample(Y), 0, None)[:, None] * _unit(sdf.grad(Y))
        if it < RIGGED_SMOOTH_UNTIL:
            Xd = _smooth(Xd, adjacency, SMOOTH_PASSES)
    X = X + Xd
    d = sdf.sample(X)
    arm_cols = [i for i, n in enumerate(body_rigged.joint_names) if "arm" in norm_bone_name(n)]
    report = {
        "method": "skinned",
        "scale_k": float(k),
        "uv_dist_p99": float(np.percentile(uv_dist, 99)),
        **bones.report,
        "sleeve_share": float((Wg[:, arm_cols].sum(1) > 0.5).mean()) if arm_cols and len(Wg) else 0.0,
        "relaxed_vertices": int(relaxed),
        "rigged_push_max_m": float(np.linalg.norm(Xd, axis=1).max()) if len(Xd) else 0.0,
        "rigged_clearance_p1_m": float(np.percentile(d, 1)),
        "rigged_inside_share": float((d < 0).mean()),
    }
    return X, report


# --- weights ---------------------------------------------------------------------------------------------------------------

def chin_height(body_rigged: BodyMesh) -> float:
    """Height of the lowest rigged vertex with Head weight > 0.5."""
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    if not head.any():
        raise ValueError("The rigged body has no Head-weighted vertex")
    return float(body_rigged.positions[head, 1].min())


def hair_weights(X, body_rigged: BodyMesh, *, blend_m: float = HAIR_BLEND_M):
    """Head -> Spine2 by height below the chin -> ``(joint_names, joints (n,4), weights (n,4))``.

    chin = lowest rigged vertex with Head weight > 0.5; at the chin and above all Head, ``blend_m`` below it all
    Spine2, linear in between. Joints are resolved by ``norm_bone_name`` (``head``, ``spine2``), never by index.
    """
    X = np.asarray(X, np.float64)
    head, spine2 = joint_index(body_rigged, "head"), joint_index(body_rigged, "spine2")
    chin = chin_height(body_rigged)
    t = np.clip((chin - X[:, 1]) / blend_m, 0, 1)
    names = [body_rigged.joint_names[head], body_rigged.joint_names[spine2]]
    J = np.zeros((len(X), 4), np.int64)
    J[:, 1] = 1
    W = np.zeros((len(X), 4))
    W[:, 0], W[:, 1] = 1 - t, t
    return names, J, W


def _contract_columns(body: BodyMesh) -> np.ndarray:
    """Bool per skin joint: a rig-contract bone (``rig_contract.BASE_JOINT_KEYS``), never an extension bone."""
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    return np.array([norm_bone_name(n) in BASE_JOINT_KEYS for n in body.joint_names], bool)


def crotch_height(body_rigged: BodyMesh) -> float:
    """Height of the lowest rigged vertex within ``CROTCH_HALF_X_M`` of the centre line (the median x of the
    Hips-weighted vertices) with Hips weight > ``CROTCH_HIPS_MIN``."""
    hips = dense_weights(body_rigged)[:, joint_index(body_rigged, "hips")] > CROTCH_HIPS_MIN
    if not hips.any():
        raise ValueError("The rigged body has no Hips-weighted vertex")
    P = body_rigged.positions
    xc = float(np.median(P[hips, 0]))
    centre = hips & (np.abs(P[:, 0] - xc) < CROTCH_HALF_X_M)
    if not centre.any():
        raise ValueError("The rigged body has no Hips-weighted vertex on its centre line")
    return float(P[centre, 1].min())


def is_skirt(X, body_rigged: BodyMesh, slots) -> bool:
    """Whether a fitted piece hangs over both legs as ONE surface below the crotch (a skirt or a dress).

    Only a piece on a skirt slot (``SKIRT_SLOTS``) can be one. Its rigged vertices between ``SKIRT_PROBE_M`` below
    the crotch (the hem, when it ends higher up) that lie within ``SKIRT_CENTRE_M`` of the centre line must reach in
    front of the body's front AND behind its back at those heights: a skirt crosses the centre line on both sides of
    the legs, trousers (one tube per leg) never cover the gap between them.
    """
    if not SKIRT_SLOTS & {str(s) for s in (slots or [])}:
        return False
    X = np.asarray(X, np.float64)
    if len(X) == 0:
        return False
    crotch = crotch_height(body_rigged)
    hi = crotch - SKIRT_PROBE_M[0]
    lo = max(float(X[:, 1].min()), crotch - SKIRT_PROBE_M[1])
    if lo >= hi:
        return False
    P = body_rigged.positions
    hips = dense_weights(body_rigged)[:, joint_index(body_rigged, "hips")] > CROTCH_HIPS_MIN
    xc = float(np.median(P[hips, 0]))
    body = P[(P[:, 1] >= lo) & (P[:, 1] <= hi)]
    garment = X[(X[:, 1] >= lo) & (X[:, 1] <= hi) & (np.abs(X[:, 0] - xc) < SKIRT_CENTRE_M)]
    if len(body) == 0 or len(garment) == 0:
        return False
    return bool(garment[:, 2].max() > body[:, 2].max() and garment[:, 2].min() < body[:, 2].min())


def clothing_weights(points, body: BodyMesh, *, skirt: bool) -> Tuple[np.ndarray, np.ndarray]:
    """Skin weights of rigged clothing positions -> ``(joints (n, 4), weights (n, 4))``, joints indexing
    ``body.joint_names``; zero-weight slots point at joint 0.

    1. Inverse distance over the ``CLOTHING_IDW_K`` (8) nearest rigged body vertices, ``w = 1 / max(d, 1e-4)``
       (spike ``fit_dress.py``), of the body weights RESTRICTED to the rig-contract bones and renormalised. A point
       whose neighbours carry only extension bones takes the same inverse distance over the nearest body vertices
       with at least ``CONTRACT_DONOR_MIN`` of their weight on contract bones.
    2. ``skirt``: below crotch + ``SKIRT_ZONE_M`` a vertex with leg weight keeps ``SKIRT_KEEP_TOP`` of it from the
       crotch up, falling linearly to ``SKIRT_KEEP_HEM`` at the hem (the lowest point); the rest goes to Hips, so the
       skirt does not split with the legs.
    3. The four largest weights, renormalised.
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    X = np.asarray(points, np.float64)
    Wr = dense_weights(body)
    contract = _contract_columns(body)
    contract = np.concatenate([contract, np.zeros(Wr.shape[1] - len(contract), bool)])
    Wc = Wr * contract[None, :]

    def idw(index, positions, rows):
        k = min(CLOTHING_IDW_K, len(index))
        dist, nn = cKDTree(positions).query(X[rows], k=k)
        dist, nn = dist.reshape(len(dist), -1), nn.reshape(len(nn), -1)
        w = 1.0 / np.maximum(dist, CLOTHING_IDW_EPS_M)
        w /= w.sum(1, keepdims=True)
        return np.einsum("nk,nkj->nj", w, Wc[index[nn]])
    every = np.arange(len(body.positions))
    W = idw(every, body.positions, np.ones(len(X), bool)) if len(X) else np.zeros((0, Wr.shape[1]))
    empty = W.sum(1) <= 1e-9
    if empty.any():
        total = Wr.sum(1)
        donors = np.nonzero(Wc.sum(1) >= CONTRACT_DONOR_MIN * np.maximum(total, 1e-12))[0]
        donors = donors[total[donors] > 0]
        if len(donors) == 0:
            raise ValueError("The rigged body has no vertex weighted on rig-contract bones")
        W[empty] = idw(donors, body.positions[donors], empty)
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)

    if skirt and len(X):
        hips = joint_index(body, "hips")
        legs = [i for i, n in enumerate(body.joint_names)
                if contract[i] and any(t in norm_bone_name(n) for t in _LEG_TOKENS)]
        crotch = crotch_height(body)
        hem = float(X[:, 1].min())
        t = np.clip((crotch - X[:, 1]) / max(crotch - hem, 1e-6), 0, 1)
        keep = SKIRT_KEEP_TOP + (SKIRT_KEEP_HEM - SKIRT_KEEP_TOP) * t
        legw = W[:, legs].sum(1)
        zone = (X[:, 1] < crotch + SKIRT_ZONE_M) & (legw > 0)
        W[np.ix_(zone, legs)] *= keep[zone, None]
        W[zone, hips] += legw[zone] * (1 - keep[zone])

    J = np.argsort(-W, 1, kind="stable")[:, :4]
    top = np.take_along_axis(W, J, 1)
    top /= np.maximum(top.sum(1, keepdims=True), 1e-12)
    J = np.where(top > 0, J, 0)
    return J.astype(np.int64), top


# --- metrics + gate -----------------------------------------------------------------------------------------------------

def _head_centre_x(body_rigged: BodyMesh) -> float:
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    return float(np.median(body_rigged.positions[head, 0]))


def bib_area_cm2(X, Fw, body_rigged: BodyMesh) -> float:
    """Garment area in front of the neck below the chin (spike ``hair_metrics``): triangles whose centroid is within
    16 cm below the chin, within 6 cm of the head's centre line and in front of (or less than 1 cm behind) the neck's
    front surface of its 1 cm height bin. Bodies face +z."""
    X = np.asarray(X, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    if len(Fw) == 0:
        return 0.0
    chin, xc = chin_height(body_rigged), _head_centre_x(body_rigged)
    Pr = body_rigged.positions
    nb = Pr[(np.abs(Pr[:, 0] - xc) < 0.04) & (Pr[:, 1] > chin - 0.17) & (Pr[:, 1] < chin + 0.01)]
    bins = np.round(nb[:, 1] / 0.01).astype(int)
    front = {k: nb[bins == k, 2].max() for k in np.unique(bins)}
    C = X[Fw].mean(1)
    fz = np.array([front.get(k, np.inf) for k in np.round(C[:, 1] / 0.01).astype(int)])
    bib = (C[:, 1] < chin) & (C[:, 1] > chin - 0.16) & (np.abs(C[:, 0] - xc) < 0.06) & (C[:, 2] > fz - 0.01)
    return float(triangle_areas(X, Fw)[bib].sum() * 1e4)


def poke_share(Q0_pre, Q_post, *, tol_m: float = POKE_TOL_M) -> float:
    """Inner-layer poke-through on the crown (spike ``poke.py``), positions in metres.

    Directions from the skull centre (crown top - 0.102 m, x/z medians of the top 0.034 m before the push), 3-degree
    bins over the directions above the ear line (unit y > 0.2). Per bin with at least 3 vertices: if the vertex
    outermost AFTER the push was more than ``tol_m`` inside the outermost one BEFORE it, an inner layer came
    through.
    """
    Q0, Q = np.asarray(Q0_pre, np.float64), np.asarray(Q_post, np.float64)
    top = Q0[:, 1].max()
    crown = Q0[:, 1] > top - 0.034
    c = np.array([np.median(Q0[crown, 0]), top - 0.102, np.median(Q0[crown, 2])])
    v0, v1 = Q0 - c, Q - c
    r0, r1 = np.linalg.norm(v0, axis=1), np.linalg.norm(v1, axis=1)
    u = v1 / np.maximum(r1, 1e-12)[:, None]
    up = u[:, 1] > 0.2
    theta = np.degrees(np.arctan2(u[:, 0], u[:, 2]))
    elev = np.degrees(np.arcsin(np.clip(u[:, 1], -1, 1)))
    key = (np.round(theta / 3).astype(np.int64) + 1000) * 10000 + np.round(elev / 3).astype(np.int64) + 100
    idx = np.nonzero(up)[0]
    if len(idx) == 0:
        return 0.0
    order = idx[np.argsort(key[idx], kind="stable")]
    keys = key[order]
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(order)]
    bad = total = 0
    for s, e in zip(starts, ends):
        if e - s < 3:
            continue
        m = order[s:e]
        total += 1
        if r0[m[r1[m].argmax()]] < r0[m].max() - tol_m:
            bad += 1
    return bad / max(total, 1)


def scalp_uncovered_share(X, Fw, body_rigged: BodyMesh, *, gap_m: float = 0.02, top_m: float = 0.05) -> float:
    """Share of scalp vertices (Head-weighted, within ``top_m`` of the head top) with no garment surface within
    ``gap_m`` (garment vertices + 6 seeded random samples per triangle)."""
    from scipy.spatial import cKDTree
    X = np.asarray(X, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    H = body_rigged.positions[head]
    scalp = H[H[:, 1] > H[:, 1].max() - top_m]
    pts = X
    if len(Fw):
        w = np.random.default_rng(0).dirichlet((1, 1, 1), size=(len(Fw), 6))
        pts = np.concatenate([np.einsum("fkj,fjd->fkd", w, X[Fw]).reshape(-1, 3), X])
    dist, _ = cKDTree(pts).query(scalp)
    return float((dist > gap_m).mean())


def metrics(X, Fw, Q0_pre, Q_post, body_rigged: BodyMesh) -> Dict[str, Any]:
    """Mesh gate numbers of a fitted garment (R7). ``X``: welded rigged positions (m); ``Q0_pre``/``Q_post``: the
    welded unrigged positions before/after the push-out, scaled to metres by ``k``."""
    X = np.asarray(X, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    Q0, Q = np.asarray(Q0_pre, np.float64), np.asarray(Q_post, np.float64)
    push = np.linalg.norm(Q - Q0, axis=1)
    _, share = components(X, Fw)
    return {
        "bib_cm2": round(bib_area_cm2(X, Fw, body_rigged), 2),
        "poke_share": round(poke_share(Q0, Q), 4),
        "scalp_uncovered_share": round(scalp_uncovered_share(X, Fw, body_rigged), 4),
        "max_push_m": round(float(push.max()) if len(push) else 0.0, 4),
        "moved_share": round(float((push > MOVED_EPS_M).mean()) if len(push) else 0.0, 4),
        "largest_component_share": round(float(share.max()) if len(share) else 0.0, 4),
        "drop_below_chin_m": round(chin_height(body_rigged) - float(X[:, 1].min()), 4),
        "tris": int(len(Fw)),
    }


def clothing_metrics(X, Fw, Q0_pre, Q_post, transfer_report: Dict[str, Any]) -> Dict[str, Any]:
    """Mesh gate numbers of a fitted clothing piece (``CLOTHING_GATES``), positions as in ``metrics``."""
    X = np.asarray(X, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    push = np.linalg.norm(np.asarray(Q_post, np.float64) - np.asarray(Q0_pre, np.float64), axis=1)
    _, share = components(X, Fw)
    return {
        "max_push_m": round(float(push.max()) if len(push) else 0.0, 4),
        "moved_share": round(float((push > MOVED_EPS_M).mean()) if len(push) else 0.0, 4),
        "largest_component_share": round(float(share.max()) if len(share) else 0.0, 4),
        "rigged_inside_share": round(float(transfer_report.get("rigged_inside_share", float("nan"))), 4),
        "rigged_clearance_p1_m": round(float(transfer_report.get("rigged_clearance_p1_m", float("nan"))), 4),
        "tris": int(len(Fw)),
    }


def gate(m: Dict[str, Any], gates: Optional[Dict[str, Tuple[str, float, str]]] = None) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` against ``gates`` (default: the R7 limits ``GATES``); a missing or non-finite number
    refuses."""
    reasons = []
    for key, (kind, limit, label) in (GATES if gates is None else gates).items():
        value = m.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            reasons.append(f"{key}: missing ({label})")
        elif kind == "max" and value > limit:
            reasons.append(f"{key} {value:g} > {limit:g} ({label})")
        elif kind == "min" and value < limit:
            reasons.append(f"{key} {value:g} < {limit:g} ({label})")
    return not reasons, reasons


# --- composition ------------------------------------------------------------------------------------------------------------

@dataclass
class FitResult:
    garment: GarmentMesh            # per prepared-GLB vertex (minus dropped components), rigged space, weighted
    metrics: Dict[str, Any]
    ok: bool
    reasons: List[str]
    report: Dict[str, Any] = field(default_factory=dict)


def _mask(mask) -> np.ndarray:
    """A bool mask as is; a uint8 BiRefNet mask thresholded at 17 like the spike."""
    arr = np.asarray(mask)
    return arr if arr.dtype == bool else arr >= 17


def vertex_normals(X: np.ndarray, F: np.ndarray) -> np.ndarray:
    N = np.zeros_like(X)
    fn = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
    for i in range(3):
        np.add.at(N, F[:, i], fn)
    norm = np.linalg.norm(N, axis=1, keepdims=True)
    return np.where(norm > 1e-12, N / np.maximum(norm, 1e-12), np.array([0.0, 1.0, 0.0]))


def _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material) -> GarmentMesh:
    """The fitted garment on the prepared GLB's vertices (UV seams intact), minus the dropped components: ``X``,
    ``J``, ``W`` are per kept welded vertex (``Fk`` their faces), ``new_of_welded`` maps welded -> kept (-1 dropped)
    and ``inv`` prepared -> welded."""
    vmap = new_of_welded[inv]
    kept_v = np.nonzero(vmap >= 0)[0]
    orig_new = np.full(len(Pd), -1, np.int64)
    orig_new[kept_v] = np.arange(len(kept_v))
    Fo = np.asarray(Fd, np.int64).reshape(-1, 3)
    Fwo = inv[Fo]
    face_ok = ((Fwo[:, 0] != Fwo[:, 1]) & (Fwo[:, 1] != Fwo[:, 2]) & (Fwo[:, 0] != Fwo[:, 2])
               & (vmap[Fo] >= 0).all(1))
    faces = orig_new[Fo[face_ok]]
    used = np.unique(faces)
    final = np.full(len(kept_v), -1, np.int64)
    final[used] = np.arange(len(used))
    src = vmap[kept_v[used]]
    normals = vertex_normals(X, Fk)
    return GarmentMesh(positions=X[src], normals=normals[src], uvs=np.asarray(Ud, np.float64)[kept_v[used]],
                       indices=final[faces], joints=J[src], weights=W[src], joint_names=names,
                       image=image, mime=mime, material=material)


def _prepare(prepared_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes):
    """Read and weld a prepared garment and both bases -> ``(static arrays, bases, welded, kept)``."""
    from app.core.glb_mesh import body_arrays, static_arrays
    Pd, Fd, Ud, image, mime, material = static_arrays(prepared_glb)
    body_u, body_r = body_arrays(unrigged_base_glb), body_arrays(rigged_base_glb)
    if not body_r.joint_names:
        raise ValueError("The rigged base has no skin")
    Pw, Fw0, inv = weld(Pd, Fd, Ud)
    Pk, Fk, keep = drop_small(Pw, Fw0)
    new_of_welded = np.full(len(Pw), -1, np.int64)
    new_of_welded[keep] = np.arange(len(keep))
    return (Pd, Fd, Ud, image, mime, material), (body_u, body_r), (Pw, Fw0, inv), (Pk, Fk, new_of_welded)


def fit_hair(prepared_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes,
             bald_front_mask, ghost_front_mask) -> FitResult:
    """Fit a prepared (decimated) hair mesh onto the rigged base body.

    ``bald_front_mask`` is the full-frame body mask of the bald front view the unrigged base was generated from,
    ``ghost_front_mask`` the full-frame hair mask of the hair-only front view (same framing, R6). The R9 constants
    are converted to unrigged units by ``k`` from a first global similarity pass over the head (Head weight > 0.5).
    """
    bald, ghost = _mask(bald_front_mask), _mask(ghost_front_mask)
    if bald.shape != ghost.shape:
        raise ValueError(f"The masks must share one image size (same framing): {bald.shape} vs {ghost.shape}")
    (Pd, Fd, Ud, image, mime, material), (body_u, body_r), (Pw, Fw0, inv), (Pk, Fk, new_of_welded) = \
        _prepare(prepared_glb, unrigged_base_glb, rigged_base_glb)

    corr, _ = uv_correspondence(body_u, body_r)
    Wb = dense_weights(body_r)[corr]
    head = Wb[:, joint_index(body_r, "head")] > 0.5
    # k over the head, the hair's carrier: the rigid part of the body between an A-pose source and a T-pose rig
    k, _, _, _ = region_similarity(body_u, body_r, corr, head)
    if not (k > 0 and math.isfinite(k)):
        raise ValueError("Could not measure the unrigged -> rigged scale")

    Q = place_by_framing(Pk, body_u.positions, bald, ghost)
    head_P = body_u.positions[head]
    Q = align_depth(Q, head_P, probe_u=PROBE_M / k, band_u=PROBE_BAND_M / k)
    margin = SDF_MARGIN_M / k
    sdf = body_sdf(body_u.positions, body_u.faces, vox=VOX_M / k, bounds=(Q.min(0) - margin, Q.max(0) + margin))
    Qp, disp = push_out(Q, Fk, sdf, clear=CLEAR_M / k, spread=SPREAD_M / k, spread_depth=SPREAD_DEPTH_M / k)
    X, transfer_report = transfer(Qp, body_u, body_r, faces=Fk)
    names, J, W = hair_weights(X, body_r, blend_m=HAIR_BLEND_M)
    m = metrics(X, Fk, Q * k, Qp * k, body_r)
    ok, reasons = gate(m)

    garment = _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material)
    report = {
        "k": float(k),
        "vertices": {"prepared": int(len(Pd)), "welded": int(len(Pw)), "kept": int(len(Pk)),
                     "out": int(len(garment.positions))},
        "dropped_components_faces": int(len(Fw0) - len(Fk)),
        "push": {"moved": int((np.linalg.norm(disp, axis=1) > MOVED_EPS_M / k).sum()),
                 "max_m": float(np.linalg.norm(disp, axis=1).max() * k) if len(disp) else 0.0},
        "transfer": transfer_report,
        "chin_y_m": chin_height(body_r),
        "share_below_chin": float((W[:, 1] > 0).mean()) if len(W) else 0.0,
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)


def align_band_depth(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
                     half_x: float = CLOTHING_BODY_HALF_X) -> Tuple[np.ndarray, float]:
    """Shift the garment in z so its band ``band`` (fractions of ``height_u`` below its top) is centred on the body
    band at the same heights within ``half_x * height_u`` of the body's centre line (the median x) -> ``(Q, dz)``
    (spike ``fit_dress.py``: the torso band of a dress)."""
    Q = np.array(Q, np.float64)
    body_P = np.asarray(body_P, np.float64)
    top = Q[:, 1].max()
    bq = Q[(Q[:, 1] < top - band[0] * height_u) & (Q[:, 1] > top - band[1] * height_u)]
    if len(bq) == 0:
        raise ValueError("No garment vertices in the depth band below its top")
    yl, yh = bq[:, 1].min(), bq[:, 1].max()
    xc = float(np.median(body_P[:, 0]))
    bb = body_P[(body_P[:, 1] > yl) & (body_P[:, 1] < yh) & (np.abs(body_P[:, 0] - xc) < half_x * height_u)]
    if len(bb) == 0:
        raise ValueError("No body vertices at the garment's depth band")
    dz = float((bb[:, 2].min() + bb[:, 2].max()) / 2 - (bq[:, 2].min() + bq[:, 2].max()) / 2)
    Q[:, 2] += dz
    return Q, dz


def fit_clothing(unrigged_garment_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes, *,
                 masks, slots) -> FitResult:
    """Fit a prepared (decimated) clothing mesh onto the rigged base body (dress spike ``fit_dress.py``).

    ``masks``: ``{"body": ..., "garment": ...}`` — the full-frame body mask of the bald front view the unrigged base
    was generated from and the full-frame garment mask of the accepted ghost front view (same framing, never the
    cut-out). ``slots``: the piece's outfit slots (a skirt blend needs a ``SKIRT_SLOTS`` slot).

    ``k`` = rigged height / unrigged height. Placement by the shared framing, depth by the torso band
    (``align_band_depth``), push-out to ``CLEAR_M`` without the crown spread (6 smoothing passes in the first 6 of 8
    iterations), the skinned transfer (``transfer_skinned``) with the waist at the garment top minus
    ``CLOTHING_WAIST_DROP`` of the body height (sleeves ride the arms above it), ``clothing_weights`` (skirt when
    ``is_skirt``), the gate ``CLOTHING_GATES``. The output joints are the contract bones the weights use, in skin
    order.
    """
    body_mask, garment_mask = _mask(masks["body"]), _mask(masks["garment"])
    if body_mask.shape != garment_mask.shape:
        raise ValueError("The masks must share one image size (same framing): "
                         f"{body_mask.shape} vs {garment_mask.shape}")
    (Pd, Fd, Ud, image, mime, material), (body_u, body_r), (Pw, Fw0, inv), (Pk, Fk, new_of_welded) = \
        _prepare(unrigged_garment_glb, unrigged_base_glb, rigged_base_glb)
    if len(Pk) == 0:
        raise ValueError("The garment mesh has no faces")
    uv_correspondence(body_u, body_r)
    height_u = float(np.ptp(body_u.positions[:, 1]))
    height_r = float(np.ptp(body_r.positions[:, 1]))
    k = height_r / height_u if height_u > 0 else float("nan")
    if not (k > 0 and math.isfinite(k)):
        raise ValueError("Could not measure the unrigged -> rigged scale")

    Q = place_by_framing(Pk, body_u.positions, body_mask, garment_mask)
    Q, dz = align_band_depth(Q, body_u.positions, height_u=height_u)
    margin = SDF_MARGIN_M / k
    sdf = body_sdf(body_u.positions, body_u.faces, vox=VOX_M / k, bounds=(Q.min(0) - margin, Q.max(0) + margin))
    Qp, disp = push_out(Q, Fk, sdf, clear=CLEAR_M / k)
    split_y = float(Qp[:, 1].max() - CLOTHING_WAIST_DROP * height_u)
    X, transfer_report = transfer_skinned(Qp, body_u, body_r, faces=Fk, k=k, split_y=split_y)
    skirt = is_skirt(X, body_r, slots)
    J, W = clothing_weights(X, body_r, skirt=skirt)
    used = np.unique(J[W > 0])
    remap = np.zeros(max(len(body_r.joint_names), int(J.max()) + 1 if J.size else 0), np.int64)
    remap[used] = np.arange(len(used))
    J = np.where(W > 0, remap[J], 0)
    names = [body_r.joint_names[i] for i in used]
    m = clothing_metrics(X, Fk, Q * k, Qp * k, transfer_report)
    ok, reasons = gate(m, CLOTHING_GATES)

    garment = _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material)
    crotch = crotch_height(body_r)
    hips = names.index(body_r.joint_names[joint_index(body_r, "hips")]) if skirt else -1
    report = {
        "k": float(k),
        "vertices": {"prepared": int(len(Pd)), "welded": int(len(Pw)), "kept": int(len(Pk)),
                     "out": int(len(garment.positions))},
        "dropped_components_faces": int(len(Fw0) - len(Fk)),
        "depth_shift_u": dz,
        "push": {"moved": int((np.linalg.norm(disp, axis=1) > MOVED_EPS_M / k).sum()),
                 "max_m": float(np.linalg.norm(disp, axis=1).max() * k) if len(disp) else 0.0},
        "waist_y_u": split_y,
        "transfer": transfer_report,
        "crotch_y_m": crotch,
        "hem_y_m": float(X[:, 1].min()),
        "skirt": bool(skirt),
        "skirt_zone_share": float((X[:, 1] < crotch + SKIRT_ZONE_M).mean()) if skirt else 0.0,
        "hem_hips_weight": (float(((J == hips) * W).sum(1)[X[:, 1] <= X[:, 1].min() + 0.01].mean())
                            if skirt else None),
        "joints": names,
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)
