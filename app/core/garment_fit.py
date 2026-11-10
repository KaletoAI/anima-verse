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
and a skirt whose leg weights are smoothed across the gap between the legs and blended partly toward Hips down to the
hem. Its placement constants are FRACTIONS OF THE BODY HEIGHT (the spike worked in units of a 1.0-high body =
1.70 m, so at that height they are the spike's numbers); ``k`` is the height ratio rigged / unrigged (the whole body
is the carrier; A- and T-pose share the height).

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
# Hair weights (``hair_weights``): the ear line lies this fraction of the head height (chin -> crown) above the chin
# — the earlobe / jaw angle (measured on Kira's base: 1.513 m; its Head joint 1.515 m, nose tip 1.503 m).
HAIR_EAR_LINE_FRACTION = 0.25
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

#: Fit algorithm version per garment kind, written into every fit record (``fit_version``, ``garments._publish_fit``).
#: A record with an older or missing version is stale (``garments._fit_state``): the chain re-runs the FIT only — CPU,
#: no hub job; images and mesh stay cached under the unchanged fsig. Bump a kind whenever its fit output changes.
#: 2 (2026-11-10): clothing — skinned transfer (sleeves, 3b4b0abf) and the smoothed skirt leg weights; hair — the
#: Head -> Neck -> Spine2 ramp between the ear line and the shoulder top.
#: 3 (2026-11-10): clothing — long sleeves below the waist ride the arm (``sleeve_vertices``); the deep push share
#: replaces the moved share in the gate.
#: 4 (2026-11-10): clothing — the garment over extension-bone tissue takes the extension share of its weights
#: (``EXTENSION_FULL_M``), so it moves with the chest instead of letting the chest jiggle through it.
#: 5 (2026-11-10): clothing — a fit on an outfit body (and a refit from another base) aligns its sleeves / trouser
#: legs onto the body's own limbs (``align_limbs``); a native base fit is unchanged.
#: 6 (2026-11-10): clothing — a fit on an outfit body places its trunk from the base fit too (``map_torso``) and
#: smooths the alignment's displacement over the mesh; v5 outfit-body fits could be torn open at the front.
FIT_VERSION: Dict[str, int] = {"hair": 2, "clothing": 6}

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
# Extension bones (a pack's secondary-motion chains, e.g. the chest pair) carry the garment over their tissue: a
# garment vertex takes the EXTENSION SHARE of the inverse-distance blend of its 8 nearest body vertices' full weights
# — all of it up to ``EXTENSION_FULL_M`` from the nearest body vertex, falling linearly to none at
# ``EXTENSION_ZERO_M`` (fabric bridging away from the tissue stays on the torso) — and the contract blend fills the
# rest. Towards the torso the body's own weight gradient is the falloff. Measured 2026-11-10 on Kira's Black Blazer
# (fit 2966, base20d5701a; 8123 garment vertices with an extension share > 0.05): distance to the nearest body vertex
# 10-15 mm 7258 (mean share 0.76), 15-20 mm 702 (0.46), 20-30 mm 144 (0.46), 30-40 mm 19 (0.20), none beyond 40 mm
# — twice the clearance (``CLEAR_M``) keeps every fitted layer whole. Contract-only weights left the chest jiggling
# under a static blazer: run clip with the secondary motion, 21 % of the covered chest skin in front of the fabric on
# average, 44 % at the worst sample (``scripts/check_garment_collision.mjs --motion``); the capsule push changed none.
EXTENSION_FULL_M = 0.025
EXTENSION_ZERO_M = 0.05
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
# Skirt: below crotch + ``SKIRT_ZONE_M`` the leg weights of a garment vertex are the Gaussian average (sigma =
# ``SKIRT_SMOOTH_M`` / 2, neighbours within ``SKIRT_SMOOTH_M``) of the leg weights of the zone's vertices, so the
# switch from the left to the right leg spreads over the gap between the legs instead of the few centimetres the
# inverse-distance donors give; then the vertex keeps ``SKIRT_KEEP_TOP`` of them at the crotch, falling linearly to
# ``SKIRT_KEEP_HEM`` at the hem, and the rest goes to Hips. Crotch = the lowest rigged vertex within
# ``CROTCH_HALF_X_M`` of the centre line with Hips weight > ``CROTCH_HIPS_MIN``.
# Measured 2026-11-10 on the phase-5 e2e dress on Kira's base (dense checker with the capsule push, 8 samples; skirt
# triangles stretched > 2x by the pose / thigh skin left visible beside the skirt, mean of five views): the old blend
# (0.5 -> 0, no smoothing) walk 0.85 % / 3.0 %, run 1.07 % / 25.9 %, sit 0.63 % / 73.9 % (the thighs came out in
# front of a skirt hanging from the hips); more leg weight without smoothing tore the skirt between the legs (1 -> 0.5:
# walk 2.1 %, run 2.6 %, sit 3.1 %, centre line up to 15 %); 1 -> 0.75 smoothed over 0.16 m: 0.00 % / 2.0 %,
# 0.00 % / 3.6 %, 0.00 % / 10.2 %. Smoothing radius 0.12 m left 0.9 % of the triangles > 1.5x, 0.16 m 0.16-0.31 %.
SKIRT_ZONE_M = 0.05
SKIRT_KEEP_TOP = 1.0
SKIRT_KEEP_HEM = 0.75
SKIRT_SMOOTH_M = 0.16
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
#
# ``moved_share`` is REPORTED, no longer gated (2026-11-10, Kira's Black Blazer refused at 0.991): it counts every
# vertex the push moved by more than 0.17 mm, and the displacement smoothing carries any push to the whole piece, so a
# close-fitting piece scores ~1 when it is placed right and LESS when it is misplaced (one side then floats free).
# Measured through the unrigged push-out (blazer on Kira's base20d5701a; e2e dress on the base of that run; spike
# dress on the spike bases) — moved_share / share of vertices pushed more than 3 cm / max push:
#   blazer 2966 (correct)        0.991 / 0.031 / 42 mm      blazer 2966 scaled 0.95   0.990 / 0.146 / 46 mm
#   blazer 8ee7 (correct)        0.972 / 0.073 / 50 mm      blazer 2966 scaled 0.90   0.985 / 0.323 / 56 mm
#   e2e dress (correct)          0.743 / 0.041 / 54 mm      blazer 2966 scaled 0.85   0.977 / 0.431 / 68 mm
#   spike dress (correct)        0.926 / 0.079 / 50 mm      blazer 2966 depth +3 cm   0.816 / 0.203 / 80 mm
#                                                           blazer 2966 depth -3 cm   0.833 / 0.329 / 72 mm
# The DEEP push share (``DEEP_PUSH_M`` = 3 cm, 2.5 x ``CLEAR_M``) separates them: correct <= 0.079, misplaced >= 0.146
# — the limit 0.12 lies between; the max push gate passes every one of the misplaced pieces.
DEEP_PUSH_M = 0.03
CLOTHING_GATES = {
    "max_push_m": ("max", 0.10, "largest push-out"),
    "deep_push_share": ("max", 0.12, "share of vertices pushed out more than 3 cm"),
    "largest_component_share": ("min", 0.98, "area share of the largest component"),
    "rigged_inside_share": ("max", 0.01, "share of vertices inside the rigged body after the transfer"),
}

# Scale retry (2026-11-10): a clothing fit refused ONLY because the piece is too small for the body — every failing
# gate one of ``SCALE_RETRY_KEYS`` — is fitted again with the placed piece widened by the steps of
# ``SCALE_RETRY_STEPS``; the smallest step whose fit passes every gate is taken, the first that fails for any other
# reason does not end the walk (a larger one may still pass). A refusal for another gate is never retried; a fit that
# passes unwidened is the unchanged fit (the factor 1.0, the same arrays as before).
#
# Axes and centre, measured 2026-11-10 on Kira's Black Blazer (fit-reuse spike: prepared mesh, ghost front warped to
# the outfit body 2b6731cd04b4, refused there for deep_push_share 0.133 > 0.12) through the unrigged push-out —
# deep push share / max push / hem height / top height (unrigged frame x k, m):
#   unwidened                     0.133 / 60 mm / 0.0456 / 0.627
#   x, z  1.02 / 1.04 / 1.08      0.118 / 0.104 / 0.085   hem 0.0456 at every step, top 0.628 .. 0.632
#   isotropic about the centroid  0.104 / 0.084 / 0.054   hem 0.040 / 0.033 / 0.021, top 0.638 / 0.632 / 0.644
# The isotropic scale makes the piece LONGER (the hem 2.4 cm lower at 1.08) — a blazer must not grow a hem. Widening
# x and z only keeps the hem and the collar where they were (the top moves by the push-out alone, < 6 mm). Every deep
# vertex of that case lay within the torso (|x| < 0.25 m); beyond the torso's half width (``CLOTHING_BODY_HALF_X`` of
# the body height, the band ``align_band_depth`` centres on) x is SHIFTED by the shoulder's widening instead of
# scaled, so a sleeve keeps its length and moves out with the shoulder seam (same deep shares, 0.118 / 0.104 / 0.085:
# no deep vertex lies there). The centre is the body's vertical axis through the torso band: x = the body's median x,
# z = the middle of the body band's depth (where ``align_band_depth`` put the garment band's middle).
#: Widening factors tried after a too-small refusal, smallest first.
SCALE_RETRY_STEPS: Tuple[float, ...] = (1.02, 1.04, 1.06, 1.08)
#: The clothing gates whose refusal means "too small for the body".
SCALE_RETRY_KEYS: Tuple[str, ...] = ("deep_push_share", "max_push_m")
#: Stamped on a refused fit's failure record (``garment_store.record_failure``): the refusal was made WITH the scale
#: retry. A too-small refusal recorded without it is retried once by the refit sweep (``garment_refit``).
SCALE_RETRY_VERSION = 1

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
    return np.linalg.norm(X - point_triangle_closest(X, A, B, C), axis=-1)


def point_triangle_closest(X: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """The closest point of triangles ``(A, B, C)`` to points ``X`` (see ``point_triangle_distance``)."""
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
    return closest


class BodySurface:
    """B's surface for exact snapping: ``closest(X)`` -> ``(closest point, outward unit normal there)``, the
    closest point over the triangles of the ``k`` nearest dense samples (Ericson), the normal B's vertex normals
    interpolated at it. The voxel SDF moves a point onto its zero level only to within a fraction of a voxel and
    its gradient turns at a polar fan — the 5 mm hair shell of ``scripts/smoke_garment_cut.py`` came out 6.4 mm
    at the crown through it (``garment_cut`` snaps with this)."""

    def __init__(self, P: np.ndarray, F: np.ndarray, k: int = 8):
        from scipy.spatial import cKDTree
        self.P, self.F, self.k = np.asarray(P, np.float64), np.asarray(F, np.int64), k
        pts, self.tri_of = _surface_samples(self.P, self.F)
        self.tree = cKDTree(pts)
        self.vn = vertex_normals(self.P, self.F)

    def closest(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        X = np.asarray(X, np.float64)
        _d, j = self.tree.query(X, k=min(self.k, self.tree.n))
        tris = self.F[self.tri_of[j.reshape(len(X), -1)]]                    # (n, k, 3)
        A, B, C = (self.P[tris[..., i]] for i in range(3))
        cand = point_triangle_closest(X[:, None, :], A, B, C)
        best = np.linalg.norm(cand - X[:, None, :], axis=-1).argmin(1)
        rows = np.arange(len(X))
        Y, tri = cand[rows, best], tris[rows, best]
        a, b, c = A[rows, best], B[rows, best], C[rows, best]
        # barycentric coordinates of Y in its triangle -> interpolated vertex normal
        v0, v1, v2 = b - a, c - a, Y - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = np.maximum(d00 * d11 - d01 * d01, 1e-30)
        wv, ww = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
        N = (1 - wv - ww)[:, None] * self.vn[tri[:, 0]] + wv[:, None] * self.vn[tri[:, 1]] \
            + ww[:, None] * self.vn[tri[:, 2]]
        return Y, _unit(N)


def outer_faces(P: np.ndarray, F: np.ndarray, sdf: Sdf) -> np.ndarray:
    """The faces of the body's OUTER wall: those whose normal agrees with the gradient of the voxel field
    ``sdf`` at their centre (faces outside its crop count as outer). A double-walled body's inner wall faces
    inward, a few millimetres below the skin: a hair vertex that lies inside the skin is nearer to it than to the
    skin (Kai's temple 2026-11-10: a shell snapped onto it sat 8.4 mm under the skin and was pushed out 11 mm)."""
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    centre = P[F].mean(1)
    hi = sdf.lo + (np.array(sdf.field.shape) - 1) * sdf.vox
    crop = ((centre >= sdf.lo) & (centre <= hi)).all(1)
    outer = np.ones(len(F), bool)
    if crop.any():
        outer[crop] = (fn[crop] * sdf.grad(centre[crop])).sum(1) > 0
    return outer


class ExactNearSdf:
    """A voxel ``Sdf`` whose values below ``band`` (the units of the field) are replaced by the exact signed
    distance to the body's outer wall (``outer_faces``; ``BodySurface.closest``: the distance, signed by the
    interpolated normal) and whose gradient there is that normal. The voxel field is off by up to 1.5 mm near
    the skin (p95 over Kira's cut, 0.6 mm over Kai's shell) — as much as the placed hair fit's whole clearance
    (a shell's inner sheet lies 1 mm over the scalp). Used by the placed hair fit (``fit_hair(placed=True)``)
    only."""

    def __init__(self, sdf: Sdf, P: np.ndarray, F: np.ndarray, band: float):
        F = np.asarray(F, np.int64).reshape(-1, 3)
        self.sdf, self.band = sdf, float(band)
        self.surface = BodySurface(P, F[outer_faces(P, F, sdf)])

    def _exact(self, X: np.ndarray):
        X = np.asarray(X, np.float64)
        v = np.array(self.sdf.sample(X), np.float64)
        near = np.nonzero(v < self.band)[0]
        N = None
        if len(near):
            Y, N = self.surface.closest(X[near])
            off = X[near] - Y
            v[near] = np.linalg.norm(off, axis=1) * np.where((off * N).sum(1) < 0, -1.0, 1.0)
        return v, near, N

    def sample(self, X) -> np.ndarray:
        return self._exact(X)[0]

    def grad(self, X) -> np.ndarray:
        g = np.array(self.sdf.grad(X), np.float64)
        _v, near, N = self._exact(X)
        if len(near):
            g[near] = N
        return g


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
             margin_m: float = SDF_MARGIN_M, split_y: Optional[float] = None,
             exact_near_m: Optional[float] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
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
    4. A clearance pass on the rigged body (SDF in metres, 10 iterations, smoothed in the first 7); with
       ``exact_near_m`` the field is exact below that distance (``ExactNearSdf``).
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
    if exact_near_m is not None:
        sdf = ExactNearSdf(sdf, Pr, body_rigged.faces, exact_near_m)
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


def sleeve_vertices(Q, body_P, parts, faces, upper) -> np.ndarray:
    """The SLEEVES of a garment (unrigged units): the vertices whose nearest body vertex lies on an arm chain
    (``parts`` 1 / 2, ``_donor_parts``) and that are connected through such vertices of the SAME arm — within the
    garment mesh — to one at or above the waist (``upper``). A long sleeve hangs below the waist in the A-pose (the
    cuff beside the hip); it is still the sleeve and rides the whole arm, while a skirt panel beside a hanging hand
    reaches no sleeve through arm-nearest vertices and stays a skirt.

    Measured 2026-11-10, Kira's Black Blazer (long sleeves, waist at the garment top minus 0.20 of the body height):
    without this, the forearm half of each sleeve took torso weights and stayed at the hips in the T-pose while the
    upper half rode the arm."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    Q = np.asarray(Q, np.float64)
    near = np.asarray(parts)[cKDTree(np.asarray(body_P, np.float64)).query(Q)[1]]
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = E[(near[E[:, 0]] > 0) & (near[E[:, 0]] == near[E[:, 1]])]
    n = len(Q)
    _, labels = connected_components(coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)),
                                      directed=False)
    seeds = np.unique(labels[(near > 0) & np.asarray(upper, bool)])
    return (near > 0) & np.isin(labels, seeds)


def transfer_skinned(Q, body_unrigged: BodyMesh, body_rigged: BodyMesh, *, faces, k: float, split_y: float,
                     idw_k: int = TRANSFER_IDW_K, clear_m: float = CLEAR_M, vox_m: float = VOX_M,
                     margin_m: float = SDF_MARGIN_M,
                     rigged_iterations: int = RIGGED_ITERATIONS,
                     limbs: Optional[Dict[str, Any]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Carry welded clothing positions ``Q`` (unrigged units) into the rigged bind space (metres) by the body's own
    skinning -> ``(X, report)``. ``limbs`` (a refit, ``fit_clothing``): the source fit per welded vertex (``x0``,
    ``w0``, ``names0``, ``frames``, ``kinds``) — its limb part is aligned onto this body's limbs (``align_limbs``)
    before step 4.

    1. ``bone_transforms``: one rigid transform per bone, ``k * unrigged -> rigged``.
    2. Each garment vertex takes the inverse-distance blend (``idw_k`` nearest, ``w = 1 / max(d, 1e-4 / k)``) of the
       body weights of the ELIGIBLE unrigged body vertices around it — the same rule as ``transfer``: at or above
       ``split_y`` only forearm/hand donors are excluded (a sleeve rides the upper arm through the A -> T motion),
       below it every arm/shoulder bone (a skirt next to a hanging hand stays on the hips) — except on the SLEEVES
       (``sleeve_vertices``), which take the whole arm chain at any height. The blend is taken within
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
    sleeve = sleeve_vertices(Q, Pb, parts, faces, upper)
    Wg = np.zeros((len(Q), Wb.shape[1]))
    lower, top = ~upper & ~sleeve, upper & ~sleeve
    if lower.any():
        Wg[lower] = blend(eligible(_ARM_TOKENS), np.nonzero(lower)[0])
    if top.any():
        Wg[top] = blend(eligible(_LOWER_ARM_TOKENS), np.nonzero(top)[0])
    if sleeve.any():
        Wg[sleeve] = blend(np.arange(len(Pb)), np.nonzero(sleeve)[0])
    X = bones.apply(Q * float(k), Wg)
    relaxed = relax_stretched(X, Q * float(k), faces, adjacency)
    limb_report = None
    if limbs is not None:
        target = limb_frames(body_rigged)
        if "torso" in limbs["frames"]:
            torso = torso_frame(body_rigged)
            if torso is not None:
                target["torso"] = torso
        X, limb_report = align_limbs(X, limbs["x0"], limbs["w0"], limbs["names0"], limbs["frames"], target,
                                     kinds=limbs.get("kinds", ("arm", "leg")), adjacency=adjacency)

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
        "sleeve_vertices": int(sleeve.sum()),
        "sleeve_below_waist": int((sleeve & ~upper).sum()),
        "relaxed_vertices": int(relaxed),
        "rigged_push_max_m": float(np.linalg.norm(Xd, axis=1).max()) if len(Xd) else 0.0,
        "rigged_clearance_p1_m": float(np.percentile(d, 1)),
        "rigged_inside_share": float((d < 0).mean()),
    }
    if limb_report is not None:
        report["limbs"] = limb_report
    return X, report


# --- weights ---------------------------------------------------------------------------------------------------------------

# --- limb alignment (refit before re-render, garment_source) -----------------------------------------------------------
# A piece made on one base and fitted onto another keeps its torso by the silhouette registration; its sleeves and
# trouser legs follow the TARGET limbs: every garment vertex the SOURCE fit skinned to a limb bone is re-expressed
# from the source base's limb frames into the target base's (``align_limbs``) before the rigged clearance pass.
# Chain = proximal joint -> middle joint -> distal joint (-> tip): the joint points are the mean of the body vertices
# carrying both neighbouring bones above ``LIMB_JOINT_SHARED`` (the bind arrays carry no joint positions); a
# segment's radius is the median distance of its bone's dominant vertices to it. Per bone: the vertex's distance
# ALONG the chain from the proximal joint is kept in metres (the piece keeps its own length — user ruling
# 2026-11-10: the length is irrelevant, it must sit on the body) and clamped to the chain's end (hand tip, ankle);
# its radial offset, normalised by the source segment's radius, and its angle around the segment (a frame whose
# second axis is the projection of ``reference`` — world up for an arm, forward for a leg — so both bases' frames
# twist alike) are re-expressed on the target segment at that distance. The bones' results are blended with the
# source garment's own skin weights (the transition into the shoulder / hip runs over the same blend as the skin,
# no crease); the rest of the vertex stays where the torso placement put it.
LIMB_JOINT_SHARED = 0.25
#: Passes of the displacement smoothing after the alignment (``align_limbs``).
LIMB_SMOOTH_PASSES = 150
LIMB_CHAINS: Dict[str, Dict[str, Any]] = {
    f"{side}_{limb}": spec
    for side in ("left", "right")
    for limb, spec in (
        ("arm", {"joints": [("shoulder", "arm"), ("arm", "forearm"), ("forearm", "hand")],
                 "tip": "hand", "bones": {"arm": 0, "forearm": 1, "hand": 2}, "reference": (0.0, 1.0, 0.0),
                 "kind": "arm"}),
        ("leg", {"joints": [("hips", "upleg"), ("upleg", "leg"), ("leg", "foot")],
                 "tip": None, "bones": {"upleg": 0, "leg": 1, "foot": 1}, "reference": (0.0, 0.0, 1.0),
                 "kind": "leg"}),
    )}


def _limb_key(side: str, bone: str) -> str:
    return bone if bone == "hips" else f"{side}{bone}"


def segment_distance(X: np.ndarray, a, b) -> np.ndarray:
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    X = np.asarray(X, np.float64)
    d = b - a
    t = np.clip(((X - a) @ d) / max(float(d @ d), 1e-12), 0.0, 1.0)
    return np.linalg.norm(X - (a + t[:, None] * d), axis=1)


def limb_frames(body: BodyMesh) -> Dict[str, Dict[str, Any]]:
    """The limb chains of a rigged body (block above): ``{chain: {points [[x, y, z], ...], radii [...], bones {bone
    key: segment}, reference, kind}}`` (JSON-ready). A chain whose joints cannot be found is missing."""
    W = dense_weights(body)
    P = np.asarray(body.positions, np.float64)
    dominant = W.argmax(1)
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in LIMB_CHAINS.items():
        side = name.split("_")[0]
        try:
            idx = {bone: joint_index(body, _limb_key(side, bone))
                   for pair in spec["joints"] for bone in pair}
        except KeyError:
            continue
        points = []
        for a, b in spec["joints"]:
            shared = (W[:, idx[a]] > LIMB_JOINT_SHARED) & (W[:, idx[b]] > LIMB_JOINT_SHARED)
            if shared.sum() < 3:
                break
            points.append(P[shared].mean(0))
        if len(points) < len(spec["joints"]):
            continue
        if spec["tip"]:
            tip = P[dominant == idx[spec["tip"]]]
            if len(tip):
                u = points[-1] - points[-2]
                u = u / max(float(np.linalg.norm(u)), 1e-12)
                reach = float(np.percentile((tip - points[-1]) @ u, 99))
                if reach > 0:
                    points.append(points[-1] + reach * u)
        nseg = len(points) - 1
        radii = []
        for seg in range(nseg):
            bone = next((b for b, s in spec["bones"].items() if s == seg), None)
            own = P[dominant == idx[bone]] if bone in idx else np.zeros((0, 3))
            radii.append(float(np.median(segment_distance(own, points[seg], points[seg + 1]))) if len(own)
                         else (radii[-1] if radii else 0.0))
        out[name] = {"points": [[float(c) for c in p] for p in points], "radii": radii,
                     "bones": {_limb_key(side, b): min(seg, nseg - 1) for b, seg in spec["bones"].items()},
                     "reference": list(spec["reference"]), "kind": spec["kind"]}
    return out


def _segment_frame(a, b, reference) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """``(u, v, w, length)``: u along a -> b, v the projection of ``reference`` perpendicular to u, w = u x v."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    length = float(np.linalg.norm(b - a))
    u = (b - a) / max(length, 1e-12)
    r = np.asarray(reference, np.float64)
    v = r - (r @ u) * u
    if np.linalg.norm(v) < 1e-6:
        v = np.cross(u, [1.0, 0.0, 0.0])
    v = v / np.linalg.norm(v)
    return u, v, np.cross(u, v), length


def align_limbs(X, X0, W0, names0, source: Dict[str, Dict[str, Any]], target: Dict[str, Dict[str, Any]], *,
                kinds=("arm", "leg"), adjacency=None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Re-express the limb part of ``X`` (the torso-placed garment in the target's rigged space) from the source
    fit ``X0`` (same vertices, the source's rigged space; ``W0`` its skin weights over ``names0``) — block above.
    Chains missing on either side, or of a kind not in ``kinds``, are left alone; a ``torso`` chain (``torso_frame``)
    goes through ``map_torso``. With ``adjacency`` (the garment's, ``_adjacency``) the displacement from ``X0`` is
    smoothed over the mesh (``LIMB_SMOOTH_PASSES``): where the skin blends two maps that disagree by centimetres
    (upper arm / shoulder / trunk) their positions would stretch the triangles across the body; the smoothed
    displacement keeps the garment's own local shape. ``(X, report)``."""
    from app.core.rig_contract import norm_bone_name
    X = np.asarray(X, np.float64)
    X0 = np.asarray(X0, np.float64)
    W0 = np.asarray(W0, np.float64)
    col = {norm_bone_name(n): i for i, n in enumerate(names0)}
    Y = np.zeros_like(X)
    S = np.zeros(len(X))
    report: Dict[str, Any] = {"chains": {}}
    for name, src in source.items():
        tgt = target.get(name)
        if not tgt or src.get("kind") not in kinds:
            continue
        if src["kind"] == "torso":
            w = np.zeros(len(X))
            for bone, c in col.items():
                if torso_bone(bone):
                    w += W0[:, c]
            rows = np.nonzero(w > 1e-4)[0]
            if len(rows):
                Y[rows] += w[rows, None] * map_torso(X0[rows], src, tgt)
                S[rows] += w[rows]
            report["chains"][name] = {"vertices": int(len(rows)),
                                      "source_span_m": round(src["neck_y"] - src["hip_y"], 4),
                                      "target_span_m": round(tgt["neck_y"] - tgt["hip_y"], 4)}
            continue
        ps, pt = np.asarray(src["points"], np.float64), np.asarray(tgt["points"], np.float64)
        nseg = min(len(ps), len(pt)) - 1
        if nseg < 1:
            continue
        fs = [_segment_frame(ps[i], ps[i + 1], src["reference"]) for i in range(nseg)]
        ft = [_segment_frame(pt[i], pt[i + 1], tgt["reference"]) for i in range(nseg)]
        cum_s = np.concatenate([[0.0], np.cumsum([f[3] for f in fs])])
        cum_t = np.concatenate([[0.0], np.cumsum([f[3] for f in ft])])
        moved = 0
        for bone, seg in src["bones"].items():
            c = col.get(bone)
            if c is None:
                continue
            seg = min(int(seg), nseg - 1)
            w = W0[:, c]
            rows = np.nonzero(w > 1e-4)[0]
            if not len(rows):
                continue
            u, v, ww, _length = fs[seg]
            rel = X0[rows] - ps[seg]
            along = rel @ u
            radial = rel - along[:, None] * u
            rho = np.linalg.norm(radial, axis=1) / max(float(src["radii"][seg]), 1e-6)
            theta = np.arctan2(radial @ ww, radial @ v)
            dist = np.minimum(cum_s[seg] + along, cum_t[-1])
            j = np.clip(np.searchsorted(cum_t, dist, side="right") - 1, 0, nseg - 1)
            # The offset scales with the target radius of the vertex's OWN bone segment: a forearm vertex that
            # lands on the target's (longer) upper arm keeps the forearm's thickness — no step at the elbow.
            radius = float(tgt["radii"][min(seg, len(tgt["radii"]) - 1)])
            out = np.empty((len(rows), 3))
            for k in range(nseg):
                m = j == k
                if not m.any():
                    continue
                tu, tv, tw, _ = ft[k]
                out[m] = (pt[k] + (dist[m] - cum_t[k])[:, None] * tu
                          + (rho[m] * radius)[:, None] * (np.cos(theta[m])[:, None] * tv
                                                          + np.sin(theta[m])[:, None] * tw))
            Y[rows] += w[rows, None] * out
            S[rows] += w[rows]
            moved += len(rows)
        report["chains"][name] = {"vertices": int(moved), "source_length_m": round(float(cum_s[-1]), 4),
                                  "target_length_m": round(float(cum_t[-1]), 4)}
    total = np.maximum(S, 1e-12)
    Y = np.where(S[:, None] > 0, Y / total[:, None], X)
    S = np.clip(S, 0.0, 1.0)
    Xa = (1.0 - S)[:, None] * X + S[:, None] * Y
    if adjacency is not None and LIMB_SMOOTH_PASSES > 0 and (S > 0).any():
        Xa = X0 + _smooth(Xa - X0, adjacency, LIMB_SMOOTH_PASSES)
    shift = np.linalg.norm(Xa - X, axis=1)
    moved = S > 0
    report.update({"vertices": int(moved.sum()),
                   "shift_p50_m": round(float(np.median(shift[moved])), 4) if moved.any() else 0.0,
                   "shift_max_m": round(float(shift.max()), 4) if len(shift) else 0.0})
    return Xa, report


# --- torso alignment (fits on outfit bodies, garment_source) -------------------------------------------------------
# An outfit body is meshed from its own dressed views (another framing, heels, another chest), so the image framing
# that places a piece on its base does not place it on the outfit body (Kira's blazer: collar 0.4 - 6.5 cm and hem up
# to 6 cm off). ``map_torso`` re-expresses every vertex the SOURCE fit skinned to a trunk bone (``torso_bone``: any
# bone that is no limb bone — extension bones such as the chest included, whatever the rig names them; without
# them the radius table misses the chest and the front panel lands inside it) from the source body's trunk into
# the target's: height proportional between the hip joint (the mean of both
# Hips / UpLeg joints) and the neck joint (Spine2 / Neck), in metres below and above them; around the trunk axis
# (the chain of joint points, interpolated by height) its clearance over the body SURFACE in its direction is kept
# in metres — the surface radius ``R(v, theta)`` per normalised height v (``TORSO_V`` bins) and angle (``TORSO_THETA``
# bins) is the outermost trunk vertex there, gaps filled along the height and smoothed 3 x 3 — so a deeper chest
# carries the front panel out with it. Blended with the limbs by the source skin weights (``align_limbs``).
_LIMB_BONE_PARTS = ("arm", "hand", "leg", "foot", "toe")
_HEAD_BONE_PARTS = ("head", "eye", "jaw")


def torso_bone(name: str) -> bool:
    """A normalised bone name (``rig_contract.norm_bone_name``) the trunk carries: no arm / hand / leg / foot / toe
    bone. The head counts (a collar's weights), but not for the trunk's surface (``trunk_bone``)."""
    return not any(part in name for part in _LIMB_BONE_PARTS)


def trunk_bone(name: str) -> bool:
    """A bone whose dominant vertices are the trunk's SURFACE (radius table, coverage): ``torso_bone`` without the
    head (whose hair would read as a trunk)."""
    return torso_bone(name) and not any(part in name for part in _HEAD_BONE_PARTS)
TORSO_V = (-0.6, 1.4, 0.02)
TORSO_THETA = 36


def torso_frame(body: BodyMesh) -> Optional[Dict[str, Any]]:
    """The trunk of a rigged body (block above): ``{points [[x, y, z], ...] (hip, joints up to the neck),
    hip_y, neck_y, radius [[...] per v bin] (TORSO_THETA per bin), kind "torso"}``; None without the joints."""
    from app.core.rig_contract import norm_bone_name
    W = dense_weights(body)
    P = np.asarray(body.positions, np.float64)
    names = [norm_bone_name(n) for n in body.joint_names]

    def joint(a: str, b: str) -> Optional[np.ndarray]:
        if a not in names or b not in names:
            return None
        shared = (W[:, names.index(a)] > LIMB_JOINT_SHARED) & (W[:, names.index(b)] > LIMB_JOINT_SHARED)
        return P[shared].mean(0) if shared.sum() >= 3 else None

    legs = [joint("hips", "leftupleg"), joint("hips", "rightupleg")]
    chain = [joint("hips", "spine"), joint("spine", "spine1"), joint("spine1", "spine2"), joint("spine2", "neck")]
    if any(p is None for p in legs) or chain[-1] is None:
        return None
    hip = (legs[0] + legs[1]) / 2
    points = [hip] + [p for p in chain if p is not None]
    neck = chain[-1]
    trunk = np.isin(W.argmax(1), [i for i, n in enumerate(names) if trunk_bone(n)])
    T = P[trunk]
    frame = {"points": [[float(c) for c in p] for p in points], "hip_y": float(hip[1]), "neck_y": float(neck[1]),
             "kind": "torso"}
    v, theta, rho = _torso_coords(T, frame)
    lo, hi, step = TORSO_V
    nv = int(round((hi - lo) / step))
    iv = np.clip(((v - lo) / step).astype(int), 0, nv - 1)
    it = _theta_bin(theta)
    R = np.full((nv, TORSO_THETA), np.nan)
    np.fmax.at(R, (iv, it), rho)
    rows = np.arange(nv)
    for k in range(TORSO_THETA):  # gaps along the height: nearest defined bins
        ok = ~np.isnan(R[:, k])
        if ok.any():
            R[:, k] = np.interp(rows, rows[ok], R[ok, k])
    for k in np.nonzero(np.isnan(R).all(0))[0]:  # an angle without any vertex: its neighbours
        R[:, k] = np.nanmean(R[:, [(k - 1) % TORSO_THETA, (k + 1) % TORSO_THETA]], axis=1)
    R = np.nan_to_num(R, nan=float(np.nanmedian(R)))
    padded = np.concatenate([R[:, -1:], R, R[:, :1]], axis=1)
    padded = np.concatenate([padded[:1], padded, padded[-1:]], axis=0)
    R = sum(padded[1 + dv:1 + dv + nv, 1 + dt:1 + dt + TORSO_THETA] for dv in (-1, 0, 1) for dt in (-1, 0, 1)) / 9.0
    frame["radius"] = R.round(5).tolist()
    return frame


def _theta_bin(theta: np.ndarray) -> np.ndarray:
    return ((np.asarray(theta) + np.pi) / (2 * np.pi) * TORSO_THETA).astype(int) % TORSO_THETA


def _torso_v(y: np.ndarray, frame: Dict[str, Any]) -> np.ndarray:
    return (np.asarray(y, np.float64) - frame["hip_y"]) / max(frame["neck_y"] - frame["hip_y"], 1e-6)


def _torso_axis(y: np.ndarray, frame: Dict[str, Any]) -> np.ndarray:
    pts = np.asarray(frame["points"], np.float64)
    order = np.argsort(pts[:, 1])
    return np.stack([np.interp(y, pts[order, 1], pts[order, 0]), np.interp(y, pts[order, 1], pts[order, 2])], 1)


def _torso_coords(X: np.ndarray, frame: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(v, theta, rho)``: normalised height, angle around the trunk axis (0 = +z, front), radial distance."""
    X = np.asarray(X, np.float64)
    rel = X[:, [0, 2]] - _torso_axis(X[:, 1], frame)
    return _torso_v(X[:, 1], frame), np.arctan2(rel[:, 0], rel[:, 1]), np.linalg.norm(rel, axis=1)


def _torso_radius(frame: Dict[str, Any], v: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """``R(v, theta)`` bilinear over the bins (clamped in v, circular in theta)."""
    R = np.asarray(frame["radius"], np.float64)
    lo, _hi, step = TORSO_V
    fv = np.clip((np.asarray(v) - lo) / step - 0.5, 0, len(R) - 1)
    ft = (np.asarray(theta) + np.pi) / (2 * np.pi) * TORSO_THETA - 0.5
    v0 = np.minimum(np.floor(fv).astype(int), len(R) - 2)
    t0 = np.floor(ft).astype(int)
    av, at = fv - v0, ft - t0
    t0, t1 = t0 % TORSO_THETA, (t0 + 1) % TORSO_THETA
    return ((1 - av) * ((1 - at) * R[v0, t0] + at * R[v0, t1])
            + av * ((1 - at) * R[v0 + 1, t0] + at * R[v0 + 1, t1]))


def map_torso(X0, source: Dict[str, Any], target: Dict[str, Any]) -> np.ndarray:
    """``X0`` (source rigged space) re-expressed on the target trunk (block above)."""
    X0 = np.asarray(X0, np.float64)
    v, theta, rho = _torso_coords(X0, source)
    clearance = rho - _torso_radius(source, v, theta)
    y = X0[:, 1]
    span_s = source["neck_y"] - source["hip_y"]
    span_t = target["neck_y"] - target["hip_y"]
    y_t = np.where(y < source["hip_y"], target["hip_y"] + (y - source["hip_y"]),
                   np.where(y > source["neck_y"], target["neck_y"] + (y - source["neck_y"]),
                            target["hip_y"] + v * span_t))
    if span_s <= 0:
        return X0.copy()
    radius = np.maximum(_torso_radius(target, _torso_v(y_t, target), theta) + clearance, 0.0)
    axis = _torso_axis(y_t, target)
    return np.stack([axis[:, 0] + np.sin(theta) * radius, y_t, axis[:, 1] + np.cos(theta) * radius], 1)


def chin_height(body_rigged: BodyMesh) -> float:
    """Height of the lowest rigged vertex with Head weight > 0.5."""
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    if not head.any():
        raise ValueError("The rigged body has no Head-weighted vertex")
    return float(body_rigged.positions[head, 1].min())


def ear_line_height(body_rigged: BodyMesh) -> float:
    """The ear line (earlobe / jaw angle): ``HAIR_EAR_LINE_FRACTION`` of the head height (chin -> crown, both
    measured on the Head-weighted vertices) above the chin."""
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    chin = chin_height(body_rigged)
    return float(chin + HAIR_EAR_LINE_FRACTION * (body_rigged.positions[head, 1].max() - chin))


def shoulder_top_height(body_rigged: BodyMesh) -> float:
    """The top of the shoulders: per side the highest rigged vertex whose dominant bone is that side's Shoulder
    (clavicle) bone, averaged over the sides found (Kira's base: 1.437 / 1.440 m — the trapezius top at |x| 9-10 cm).
    A skin without Shoulder-dominated vertices (a reduced test rig): the highest Spine2-dominated vertex. ValueError
    when neither exists."""
    W = dense_weights(body_rigged)
    dominant = W.argmax(1)
    tops = []
    for key in ("leftshoulder", "rightshoulder"):
        try:
            side = dominant == joint_index(body_rigged, key)
        except KeyError:
            continue
        if side.any():
            tops.append(float(body_rigged.positions[side, 1].max()))
    if tops:
        return float(np.mean(tops))
    trunk = dominant == joint_index(body_rigged, "spine2")
    if not trunk.any():
        raise ValueError("The rigged body has no vertex dominated by a Shoulder or the Spine2 bone")
    return float(body_rigged.positions[trunk, 1].max())


def hair_weights(X, body_rigged: BodyMesh):
    """Head -> Neck -> Spine2 by height -> ``(joint_names, joints (n,4), weights (n,4))``; column 0 is always Head.

    A smooth vertical ramp between two measured landmarks: at the ear line (``ear_line_height``) and above all Head,
    at the shoulder top (``shoulder_top_height``) and below all Spine2. In between ``t`` = the fraction of the way
    down, ``s = smoothstep(t)``, and the three weights are the quadratic B-spline basis of ``s``: Head (1-s)^2,
    Neck 2s(1-s), Spine2 s^2 — they sum to 1, each is C1 in the height, and the middle of the ramp rides the neck.
    Hair below the ear line hangs beside the neck and on the shoulders; weighted to the Head it swept 1.5-2 cm into
    the shoulder tops on every head tilt (collision ruling C7, Kira: excess sit 9.4 %, celebrating 7.6 %). Joints are
    resolved by ``norm_bone_name`` (``head``, ``neck``, ``spine2`` — rig-contract bones), never by index; a skin
    without a Neck joint (a reduced test rig) gives the Neck share to Spine2.
    """
    X = np.asarray(X, np.float64)
    head, spine2 = joint_index(body_rigged, "head"), joint_index(body_rigged, "spine2")
    try:
        neck: Optional[int] = joint_index(body_rigged, "neck")
    except KeyError:
        neck = None
    ear, shoulder = ear_line_height(body_rigged), shoulder_top_height(body_rigged)
    if not shoulder < ear:
        raise ValueError(f"The shoulder top ({shoulder:.3f} m) is not below the ear line ({ear:.3f} m)")
    t = np.clip((ear - X[:, 1]) / (ear - shoulder), 0, 1)
    s = t * t * (3 - 2 * t)
    W = np.zeros((len(X), 4))
    if neck is None:
        names = [body_rigged.joint_names[i] for i in (head, spine2)]
        J = np.tile(np.array([0, 1, 0, 0], np.int64), (len(X), 1))
        W[:, 0] = (1 - s) ** 2
        W[:, 1] = 1 - W[:, 0]
    else:
        names = [body_rigged.joint_names[i] for i in (head, neck, spine2)]
        J = np.tile(np.array([0, 1, 2, 0], np.int64), (len(X), 1))
        W[:, 0], W[:, 1], W[:, 2] = (1 - s) ** 2, 2 * s * (1 - s), s ** 2
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
    2. ``skirt`` (``skirt_leg_weights``): below crotch + ``SKIRT_ZONE_M`` the leg weights are smoothed over the zone
       (``SKIRT_SMOOTH_M``) and a vertex keeps ``SKIRT_KEEP_TOP`` of them from the crotch up, falling linearly to
       ``SKIRT_KEEP_HEM`` at the hem (the lowest point); the rest goes to Hips. The skirt follows the thighs when
       sitting and spans the gap between the legs smoothly when they scissor.
    3. Extension bones: the same inverse distance over the 8 nearest body vertices, of their FULL weights (rows
       normalised), restricted to the extension bones = ``E`` (row sum ``e``); times the distance factor
       ``clip((EXTENSION_ZERO_M - d) / (EXTENSION_ZERO_M - EXTENSION_FULL_M), 0, 1)``, ``d`` = distance to the
       nearest body vertex. The weights are ``(1 - e) * contract + E``: over the tissue the garment rides the
       extension bone as the skin does, beside it the contract blend of steps 1-2 is unchanged.
    4. The four largest weights, renormalised.
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    X = np.asarray(points, np.float64)
    Wr = dense_weights(body)
    contract = _contract_columns(body)
    contract = np.concatenate([contract, np.zeros(Wr.shape[1] - len(contract), bool)])
    Wc = Wr * contract[None, :]

    def neighbours(positions, rows):
        k = min(CLOTHING_IDW_K, len(positions))
        dist, nn = cKDTree(positions).query(X[rows], k=k)
        dist, nn = dist.reshape(len(dist), -1), nn.reshape(len(nn), -1)
        w = 1.0 / np.maximum(dist, CLOTHING_IDW_EPS_M)
        return dist, nn, w / w.sum(1, keepdims=True)

    def idw(index, positions, rows):
        _dist, nn, w = neighbours(positions, rows)
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
        legs = [i for i, n in enumerate(body.joint_names)
                if contract[i] and any(t in norm_bone_name(n) for t in _LEG_TOKENS)]
        W = skirt_leg_weights(X, W, legs=legs, hips=joint_index(body, "hips"), crotch=crotch_height(body))

    if len(X) and not contract.all():
        dist, nn, w = neighbours(body.positions, np.ones(len(X), bool))
        full = Wr / np.maximum(Wr.sum(1, keepdims=True), 1e-12)
        E = np.einsum("nk,nkj->nj", w, full[nn]) * ~contract[None, :]
        E *= np.clip((EXTENSION_ZERO_M - dist[:, 0]) / (EXTENSION_ZERO_M - EXTENSION_FULL_M), 0, 1)[:, None]
        W = W * (1 - E.sum(1, keepdims=True)) + E

    J = np.argsort(-W, 1, kind="stable")[:, :4]
    top = np.take_along_axis(W, J, 1)
    top /= np.maximum(top.sum(1, keepdims=True), 1e-12)
    J = np.where(top > 0, J, 0)
    return J.astype(np.int64), top


def skirt_leg_weights(X, W, *, legs, hips: int, crotch: float, smooth_m: float = SKIRT_SMOOTH_M,
                      keep_top: float = SKIRT_KEEP_TOP, keep_hem: float = SKIRT_KEEP_HEM,
                      zone_m: float = SKIRT_ZONE_M) -> np.ndarray:
    """The skirt step of ``clothing_weights`` on dense weights ``W`` (n, joints; rows sum to 1) -> new dense weights.

    Zone = the vertices below ``crotch + zone_m``. Per zone vertex: (1) its leg columns become the Gaussian average
    (sigma ``smooth_m / 2``) of the leg columns of the zone vertices within ``smooth_m`` (itself included); its other
    columns are rescaled to the remaining weight (all on ``hips`` when it had none); (2) with ``t`` = the fraction of
    the way from the crotch down to the hem (the lowest point, 0 above the crotch), it keeps ``keep_top + (keep_hem -
    keep_top) * t`` of its leg weight and the rest goes to ``hips``. Rows still sum to 1.
    """
    from scipy.spatial import cKDTree
    X = np.asarray(X, np.float64)
    W = np.array(W, np.float64)
    zone = np.nonzero(X[:, 1] < crotch + zone_m)[0]
    if not len(zone) or not legs:
        return W
    legs = list(legs)
    L = W[np.ix_(zone, legs)]
    Ls = np.empty_like(L)
    Z = X[zone]
    tree = cKDTree(Z)
    sigma = max(smooth_m / 2, 1e-9)
    for a in range(0, len(zone), 1024):
        rows = tree.query_ball_point(Z[a:a + 1024], max(smooth_m, 0.0))
        for r, nb in enumerate(rows):
            nb = np.asarray(nb if len(nb) else [a + r], np.int64)
            g = np.exp(-0.5 * (np.linalg.norm(Z[nb] - Z[a + r], axis=1) / sigma) ** 2)
            Ls[a + r] = g @ L[nb] / g.sum()
    other = np.setdiff1d(np.arange(W.shape[1]), legs)
    O = W[np.ix_(zone, other)]
    rest = np.clip(1 - Ls.sum(1), 0, 1)
    osum = O.sum(1)
    O = np.where(osum[:, None] > 1e-12, O / np.maximum(osum[:, None], 1e-12) * rest[:, None], 0.0)
    O[osum <= 1e-12, list(other).index(hips)] = rest[osum <= 1e-12]
    hem = float(X[:, 1].min())
    t = np.clip((crotch - Z[:, 1]) / max(crotch - hem, 1e-6), 0, 1)
    keep = keep_top + (keep_hem - keep_top) * t
    W[np.ix_(zone, other)] = O
    W[np.ix_(zone, legs)] = Ls * keep[:, None]
    W[zone, hips] += Ls.sum(1) * (1 - keep)
    return W


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
        "deep_push_share": round(float((push > DEEP_PUSH_M).mean()) if len(push) else 0.0, 4),
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


def _out_index(Pd, Fd, inv, new_of_welded) -> np.ndarray:
    """Per output vertex of ``_garment_out`` its kept welded vertex (the same rule) — the vertex order of every fit
    of this prepared mesh, whatever body it was fitted on."""
    vmap = new_of_welded[inv]
    kept_v = np.nonzero(vmap >= 0)[0]
    orig_new = np.full(len(Pd), -1, np.int64)
    orig_new[kept_v] = np.arange(len(kept_v))
    Fo = np.asarray(Fd, np.int64).reshape(-1, 3)
    Fwo = inv[Fo]
    face_ok = ((Fwo[:, 0] != Fwo[:, 1]) & (Fwo[:, 1] != Fwo[:, 2]) & (Fwo[:, 0] != Fwo[:, 2])
               & (vmap[Fo] >= 0).all(1))
    used = np.unique(orig_new[Fo[face_ok]])
    return vmap[kept_v[used]]


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


#: The placed hair fit (subtract method) measures the clearance exactly below this distance (``ExactNearSdf``).
PLACED_EXACT_M = 0.03


def hair_gates(length_class: Optional[str] = None, *, shell: bool = False) -> Dict[str, Tuple[str, float, str]]:
    """The fit gates of hair of ``length_class`` (``garment_hair.LENGTH_CLASSES``): ``GATES`` without
    ``moved_share`` for short hair (``garment_hair.SHORT_LENGTH_CLASSES``) and for a scalp ``shell`` — a
    scalp-hugging layer is pushed almost everywhere by design (hair spike A); ``GATES`` otherwise."""
    from app.core.garment_hair import SHORT_LENGTH_CLASSES
    if shell or (length_class or "") in SHORT_LENGTH_CLASSES:
        return {key: value for key, value in GATES.items() if key != "moved_share"}
    return dict(GATES)


def fit_hair(prepared_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes,
             bald_front_mask=None, ghost_front_mask=None, *, placed: bool = False,
             clearance_m: float = CLEAR_M, spread_m: float = SPREAD_M,
             gates: Optional[Dict[str, Tuple[str, float, str]]] = None) -> FitResult:
    """Fit a prepared (decimated) hair mesh onto the rigged base body.

    ``bald_front_mask`` is the full-frame body mask of the bald front view the unrigged base was generated from,
    ``ghost_front_mask`` the full-frame hair mask of the hair-only front view (same framing, R6). The R9 constants
    are converted to unrigged units by ``k`` from a first global similarity pass over the head (Head weight > 0.5).

    ``placed`` (the subtract method, ``garment_cut``): the prepared mesh already lies in the unrigged base's
    frame — no ``place_by_framing`` / ``align_depth``, the masks are not needed. ``clearance_m`` / ``spread_m``
    are the push-out's clearance and spread (metres; defaults ``CLEAR_M`` / ``SPREAD_M``), ``gates`` the limits
    the metrics are gated on (default ``GATES``; ``hair_gates`` per length class).
    """
    if not placed:
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

    if placed:
        Q = np.asarray(Pk, np.float64)
    else:
        Q = place_by_framing(Pk, body_u.positions, bald, ghost)
        head_P = body_u.positions[head]
        Q = align_depth(Q, head_P, probe_u=PROBE_M / k, band_u=PROBE_BAND_M / k)
    margin = SDF_MARGIN_M / k
    sdf = body_sdf(body_u.positions, body_u.faces, vox=VOX_M / k, bounds=(Q.min(0) - margin, Q.max(0) + margin))
    if placed:
        sdf = ExactNearSdf(sdf, body_u.positions, body_u.faces, PLACED_EXACT_M / k)
    Qp, disp = push_out(Q, Fk, sdf, clear=clearance_m / k, spread=spread_m / k, spread_depth=SPREAD_DEPTH_M / k)
    # placed: the rigged clearance pass keeps the cut's own clearance — the default CLEAR_M (11.9 mm) lifted a 1 mm
    # shell to 12 mm off the scalp (Kai, p50 11.9 mm) and curled its rim where both sheets meet
    X, transfer_report = (transfer(Qp, body_u, body_r, faces=Fk, clear_m=clearance_m, exact_near_m=PLACED_EXACT_M)
                          if placed else transfer(Qp, body_u, body_r, faces=Fk))
    names, J, W = hair_weights(X, body_r)
    m = metrics(X, Fk, Q * k, Qp * k, body_r)
    ok, reasons = gate(m, gates)

    garment = _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material)
    report = {
        "k": float(k),
        "placed": bool(placed), "clearance_m": float(clearance_m), "spread_m": float(spread_m),
        "vertices": {"prepared": int(len(Pd)), "welded": int(len(Pw)), "kept": int(len(Pk)),
                     "out": int(len(garment.positions))},
        "dropped_components_faces": int(len(Fw0) - len(Fk)),
        "push": {"moved": int((np.linalg.norm(disp, axis=1) > MOVED_EPS_M / k).sum()),
                 "max_m": float(np.linalg.norm(disp, axis=1).max() * k) if len(disp) else 0.0},
        "transfer": transfer_report,
        "chin_y_m": chin_height(body_r),
        "ear_line_y_m": ear_line_height(body_r),
        "shoulder_top_y_m": shoulder_top_height(body_r),
        "share_below_ear": float((W[:, 0] < 1).mean()) if len(W) else 0.0,
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)


def _depth_bands(Q, body_P, *, height_u: float, band, half_x: float
                 ) -> Tuple[np.ndarray, np.ndarray, float]:
    """``(garment band, body band, body centre x)`` of ``align_band_depth``."""
    top = Q[:, 1].max()
    bq = Q[(Q[:, 1] < top - band[0] * height_u) & (Q[:, 1] > top - band[1] * height_u)]
    if len(bq) == 0:
        raise ValueError("No garment vertices in the depth band below its top")
    yl, yh = bq[:, 1].min(), bq[:, 1].max()
    xc = float(np.median(body_P[:, 0]))
    bb = body_P[(body_P[:, 1] > yl) & (body_P[:, 1] < yh) & (np.abs(body_P[:, 0] - xc) < half_x * height_u)]
    if len(bb) == 0:
        raise ValueError("No body vertices at the garment's depth band")
    return bq, bb, xc


def align_band_depth(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
                     half_x: float = CLOTHING_BODY_HALF_X) -> Tuple[np.ndarray, float]:
    """Shift the garment in z so its band ``band`` (fractions of ``height_u`` below its top) is centred on the body
    band at the same heights within ``half_x * height_u`` of the body's centre line (the median x) -> ``(Q, dz)``
    (spike ``fit_dress.py``: the torso band of a dress)."""
    Q = np.array(Q, np.float64)
    bq, bb, _xc = _depth_bands(Q, np.asarray(body_P, np.float64), height_u=height_u, band=band, half_x=half_x)
    dz = float((bb[:, 2].min() + bb[:, 2].max()) / 2 - (bq[:, 2].min() + bq[:, 2].max()) / 2)
    Q[:, 2] += dz
    return Q, dz


def torso_axis(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
               half_x: float = CLOTHING_BODY_HALF_X) -> Tuple[float, float]:
    """``(x, z)`` of the body's vertical axis through the torso band of ``align_band_depth``: the body's median x
    and the middle of the body band's depth — the centre the scale retry widens about (``widen``)."""
    _bq, bb, xc = _depth_bands(np.asarray(Q, np.float64), np.asarray(body_P, np.float64), height_u=height_u,
                               band=band, half_x=half_x)
    return xc, float((bb[:, 2].min() + bb[:, 2].max()) / 2)


def widen(Q, scale: float, *, centre_x: float, centre_z: float, half_width: float) -> np.ndarray:
    """The placed garment ``Q`` widened by ``scale`` about the vertical axis ``(centre_x, centre_z)``: z scaled
    about ``centre_z``; x scaled about ``centre_x`` within ``half_width`` of it and beyond that shifted by the
    widening at ``half_width`` (``x' = x + (scale - 1) * clip(x - centre_x, -half_width, half_width)``), so a
    sleeve keeps its length. y (the length) is never changed. ``scale`` 1.0 returns ``Q`` as a copy."""
    Q = np.array(Q, np.float64)
    if scale == 1.0:
        return Q
    dx = Q[:, 0] - centre_x
    Q[:, 0] = Q[:, 0] + (scale - 1.0) * np.clip(dx, -half_width, half_width)
    Q[:, 2] = centre_z + (Q[:, 2] - centre_z) * scale
    return Q


def push_numbers(Q0_pre, Q_post) -> Dict[str, float]:
    """``max_push_m`` and ``deep_push_share`` of a push-out (positions in metres, as ``clothing_metrics``)."""
    push = np.linalg.norm(np.asarray(Q_post, np.float64) - np.asarray(Q0_pre, np.float64), axis=1)
    return {"max_push_m": round(float(push.max()) if len(push) else 0.0, 4),
            "deep_push_share": round(float((push > DEEP_PUSH_M).mean()) if len(push) else 0.0, 4)}


def gate_keys(reasons: List[str]) -> List[str]:
    """The metric keys of ``gate`` reasons (each reason starts with its key)."""
    return [str(r).split(" ", 1)[0].rstrip(":") for r in reasons]


def too_small(reasons: List[str]) -> bool:
    """A refusal whose every reason is a ``SCALE_RETRY_KEYS`` gate: the piece is too small for the body."""
    keys = gate_keys(reasons)
    return bool(keys) and all(key in SCALE_RETRY_KEYS for key in keys)


def scale_retry(Q, push, finish, *, centre_x: float, centre_z: float, half_width: float,
                steps: Tuple[float, ...] = SCALE_RETRY_STEPS) -> Tuple["FitResult", Dict[str, Any]]:
    """Fit the placed garment ``Q``; when refused as ``too_small``, again widened (``widen``) by each of ``steps``
    until one passes -> ``(result, info)``.

    ``push(Qs)`` -> ``(Qp, disp, numbers)`` (the push-out of the placed positions and its ``push_numbers``),
    ``finish(Qs, Qp, disp)`` -> the ``FitResult`` of that push-out. A step whose push numbers already fail the
    ``SCALE_RETRY_KEYS`` gates is not finished (no transfer). ``info``: ``factor`` = the scale of the returned
    result (1.0 unwidened — a pass at 1.0, another refusal, or no step passed: then the unwidened refusal is
    returned), ``max_tried`` = the largest scale tried (1.0 without a retry), ``attempts`` = per tried scale
    (1.0 first) ``{scale, ok, reasons, deep_push_share, max_push_m}`` — empty without a retry."""
    Qp, disp, _numbers = push(Q)
    first = finish(Q, Qp, disp)
    info: Dict[str, Any] = {"factor": 1.0, "max_tried": 1.0, "attempts": [], "centre": [centre_x, centre_z],
                            "half_width_u": half_width}
    if first.ok or not too_small(first.reasons):
        return first, info

    def attempt(scale, ok, reasons, m):
        info["attempts"].append({"scale": scale, "ok": bool(ok), "reasons": list(reasons),
                                 **{key: m.get(key) for key in SCALE_RETRY_KEYS}})

    attempt(1.0, False, first.reasons, first.metrics)
    push_gates = {key: CLOTHING_GATES[key] for key in SCALE_RETRY_KEYS}
    for scale in steps:
        info["max_tried"] = scale
        Qs = widen(Q, scale, centre_x=centre_x, centre_z=centre_z, half_width=half_width)
        Qp, disp, numbers = push(Qs)
        ok, reasons = gate(numbers, push_gates)
        if not ok:
            attempt(scale, False, reasons, numbers)
            continue
        result = finish(Qs, Qp, disp)
        attempt(scale, result.ok, result.reasons, result.metrics)
        if result.ok:
            info["factor"] = scale
            return result, info
    return first, info


def fit_clothing(unrigged_garment_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes, *,
                 masks, slots, limb_source: Optional[Dict[str, Any]] = None) -> FitResult:
    """Fit a prepared (decimated) clothing mesh onto the rigged base body (dress spike ``fit_dress.py``).

    ``masks``: ``{"body": ..., "garment": ...}`` — the full-frame body mask of the bald front view the unrigged base
    was generated from and the full-frame garment mask of the accepted ghost front view (same framing, never the
    cut-out). ``slots``: the piece's outfit slots (a skirt blend needs a ``SKIRT_SLOTS`` slot).

    ``k`` = rigged height / unrigged height. Placement by the shared framing, depth by the torso band
    (``align_band_depth``), push-out to ``CLEAR_M`` without the crown spread (6 smoothing passes in the first 6 of 8
    iterations), the skinned transfer (``transfer_skinned``) with the waist at the garment top minus
    ``CLOTHING_WAIST_DROP`` of the body height (sleeves ride the arms above it), ``clothing_weights`` (skirt when
    ``is_skirt``), the gate ``CLOTHING_GATES``. The output joints are the bones the weights use (contract bones and,
    over their tissue, extension bones), in skin order.

    A fit refused only because the piece is too small (``too_small``) is fitted again widened about the torso axis
    (``scale_retry``, ``widen``, steps ``SCALE_RETRY_STEPS``); the push numbers of a widened fit are measured from
    the widened placement. ``metrics["scale_retry"]`` = the applied factor (1.0 unwidened), ``scale_retry_max`` =
    the largest tried (1.0 without a retry), ``report["scale_retry"]`` the attempts with their gate numbers.

    ``limb_source`` (a refit — ``garment_source``): the source fit of the same prepared mesh on another base,
    ``{x0 (output vertices, 3), w0 (output vertices, len(names0)), names0, frames (its body's limb_frames),
    kinds}``; its limbs are aligned onto this body's (``align_limbs`` inside ``transfer_skinned``). Skipped
    (``report["transfer"]["limbs"]["skipped"]``) when its vertex count is not this fit's.
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
    limbs, limbs_skipped = None, ""
    if limb_source is not None:
        src = _out_index(Pd, Fd, inv, new_of_welded)
        x0 = np.asarray(limb_source["x0"], np.float64)
        if len(x0) != len(src):
            limbs_skipped = f"the source has {len(x0)} vertices, this fit {len(src)}"
        else:
            w0 = np.asarray(limb_source["w0"], np.float64)
            x0k, w0k = np.zeros((len(Pk), 3)), np.zeros((len(Pk), w0.shape[1]))
            x0k[src], w0k[src] = x0, w0
            limbs = {"x0": x0k, "w0": w0k, "names0": list(limb_source["names0"]),
                     "frames": limb_source["frames"], "kinds": tuple(limb_source.get("kinds") or ("arm", "leg"))}
    margin = SDF_MARGIN_M / k

    def push(Qs):
        sdf = body_sdf(body_u.positions, body_u.faces, vox=VOX_M / k,
                       bounds=(Qs.min(0) - margin, Qs.max(0) + margin))
        Qp, disp = push_out(Qs, Fk, sdf, clear=CLEAR_M / k)
        return Qp, disp, push_numbers(Qs * k, Qp * k)

    def finish(Qs, Qp, disp) -> FitResult:
        split_y = float(Qp[:, 1].max() - CLOTHING_WAIST_DROP * height_u)
        X, transfer_report = transfer_skinned(Qp, body_u, body_r, faces=Fk, k=k, split_y=split_y, limbs=limbs)
        if limbs_skipped:
            transfer_report["limbs"] = {"skipped": limbs_skipped}
        skirt = is_skirt(X, body_r, slots)
        J, W = clothing_weights(X, body_r, skirt=skirt)
        used = np.unique(J[W > 0])
        remap = np.zeros(max(len(body_r.joint_names), int(J.max()) + 1 if J.size else 0), np.int64)
        remap[used] = np.arange(len(used))
        J = np.where(W > 0, remap[J], 0)
        names = [body_r.joint_names[i] for i in used]
        m = clothing_metrics(X, Fk, Qs * k, Qp * k, transfer_report)
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

    centre_x, centre_z = torso_axis(Q, body_u.positions, height_u=height_u)
    result, info = scale_retry(Q, push, finish, centre_x=centre_x, centre_z=centre_z,
                               half_width=CLOTHING_BODY_HALF_X * height_u)
    result.metrics["scale_retry"] = info["factor"]
    result.metrics["scale_retry_max"] = info["max_tried"]
    result.report["scale_retry"] = info
    return result
