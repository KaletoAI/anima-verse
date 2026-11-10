"""The subtract hair method's cut — the hair taken off a mesh of the HAIRED character
(plan ``docs/superpowers/plans/2026-11-10-hair-subtract-method.md``, spec
``docs/superpowers/specs/2026-11-10-hair-subtract-method-design.md``; productised from hair spike A,
``~/claude-out/hair-spike-a/src/hair_cut.py``).

Inputs: ``H`` — the mesh of the haired character (``hair_source_mesh``, generated from the cut-outs of the
haired front + back views), the unrigged + rigged base body ``B`` and per view the haired image, the haired
figure's silhouette (the cut-out's alpha) and the bald base view. Output: a static GLB in B's UNRIGGED frame —
the hair as ONE closed part — that ``garment_fit.fit_hair(placed=True)`` fits like every hair mesh.

The steps (every threshold in METRES; ``k`` = metres per unrigged unit from the head similarity unrigged ->
rigged, ``k_h`` the same for H's own units):

1. 2D hair masks (``hair_mask_2d``): haired vs bald view in one frame — changed pixels whose colour is nearer
   to the hair colour (median of the hair that grew the outline) than to the skin; front priors (no hair in the
   face box, none inside the body below the chin); components that reach the crown band.
2. Labels on H in H's own frame (H was generated from exactly these views): the mesh bbox maps onto the haired
   silhouette's bbox (``garment_fit._frame``); a vertex votes "hair" when it is visible from the view (depth
   buffer, ``CELL_M`` cells, 3 x 3 neighbourhood, ``VIS_TOL_M``) and projects into the view's hair mask.
3. Registration H -> B, pass 1: the shared image framing (``garment_fit.place_by_framing``), then a similarity
   ICP on the vertices of H's top ``REGISTER_TOP_M`` the masks do not vote (correspondences farther than
   ``NONHAIR_MAX_M`` dropped, ``ICP_ITERATIONS``).
4. Hair label by GEOMETRY first (``label_hair``; the 2D masks miss blonde hair over light skin — Kira e2e
   2026-11-10, haired vs bald 15 RGB at the back of the head), on H's outer wall (frontmost within
   ``OUTER_TOL_M`` from five directions), distances to B's outer wall exact (``garment_fit.ExactNearSdf``):
   on the head (nearest B vertex Head-weighted) more than ``GEO_MIN_M`` outside B is hair — except in the face
   zone (below the 2D hairline, facing forward or near the eyes / ears), where only the masks decide; the
   masks' votes and the old growth (``LOOSE_EPS_M``, ``GROW_RINGS``, never into the face zone) add the rest;
   the crown, which can lie INSIDE B, is filled when hair encloses it (``fill_enclosed``); holes up to
   ``HOLE_FILL_MAX_M2``; the largest component only (it must reach the head). Long hair on the shoulders and
   back lies ON the body: there only the masks' votes and the growth from them count. Then registration pass 2
   on the non-hair HEAD only (the hair sits on it; one similarity does not fit head and shoulders of two
   mesher outputs at once), starting from pass 1, and the label again (off the head with pass 1's distances).
5. ``cut`` (longer hair): H's hair faces with H's texture as the outer sheet, an inner sheet SNAPPED onto B
   (``INNER_OFFSET_M`` outside, never across the outer sheet; a free strand farther than ``SNAP_MAX_M`` keeps a
   sheet ``FREE_INNER_M`` inward), the two sheets joined at the cut edge -> one closed part. ``shell`` (short
   hair): the hair patch snapped onto the scalp, outer sheet at the shell thickness, inner at ``SHELL_INNER_M``,
   colour baked from the haired views into a ``TEXTURE_SIDE``² texture (seamless azimuthal UVs from the head
   top), the shell's rim re-seated on the scalp after the smoothing (a smoothed rim cuts chords into the curved
   head). Body distances are taken to B's OUTER wall only (``garment_fit.outer_faces``). Colour mend
   (``recolour_texture``): texels nearer to the skin colour than to the hair colour, and white ones, are painted
   over with the nearest hair texel (CIELAB; the hair colour = the label ``CORE_RINGS`` inside its border, the
   skin = H's non-hair head for ``cut``, the bald front view's face for ``shell``). Both: the cut edge is smoothed
   along its loops (``EDGE_SMOOTH_PASSES``) and feathered — ring 0 is
   where both sheets meet (no rim strip), ring 1 halfway — so the hairline thins out instead of ending in a
   wall. The edge is found on H's WELDED topology: H carries UV-seam duplicates, and an edge on a UV seam is no
   cut edge (the spike's rims along UV seams were its white streaks). A hole in the hair sheet shorter than
   ``CAP_LOOP_MAX_M`` is capped with a fan (a groove between strands, not an island of vertices).
6. Gates (``CUT_GATES``, numbers § B5a style): registration p95 of the non-hair outer wall of the head below
   1 cm (the top 35 cm are reported as ``top_p95_cm``), the hairline (front centre strip, 3D label vs 2D mask) within 1.5 cm, no small hole left in the hair
   sheet (boundary loops shorter than ``HOLE_LOOP_MAX_M``), hair area at least 1 cm².

``CUT_VERSION`` is part of the subtract fsig: bump it whenever the cut's output changes.
"""
from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from app.core import garment_fit as gf
from app.core.log import get_logger

logger = get_logger("garment_cut")

#: Bump whenever the cut's output changes (part of the subtract fsig, ``garment_store``).
CUT_VERSION = 4   # 2: colour mend, shell rim seated on the outer scalp; 3: pale texels mended; 4: geometry label

SHAPES: Tuple[str, ...] = ("cut", "shell")
#: Default / allowed shell thickness (profile ``hair_shell_mm``).
DEFAULT_SHELL_M = 0.005
SHELL_MIN_M = 0.002
SHELL_MAX_M = 0.015

# --- thresholds (metres unless named otherwise; hair spike A) -------------------------------------------------------
GROW_RINGS = 10             # label growth from the seeds over the far-outside outer wall (~5 cm)
LOOSE_EPS_M = 0.015         # growth / loose-mask votes only this far outside the bald base
DEEP_M = 0.012              # deeper than this inside the bald base = H's inner wall, never hair
OUTER_TOL_M = 0.010         # H's outer wall: frontmost in its depth cell within this, from one of five directions
CLEAR_CUT_M = 0.006         # push-out clearance of the cut hair (its inner sheet sits there)
VIS_TOL_M = 0.050           # mask vote: within this depth of the frontmost vertex of the cell
CELL_M = 0.004              # depth-buffer cell size
NONHAIR_MAX_M = 0.02        # ICP correspondences farther than this from B are outliers
REGISTER_TOP_M = 0.35       # ICP + registration gate region: the top of H
ICP_ITERATIONS = 12
SNAP_MAX_M = 0.03           # inner sheet of the cut: snapped onto B within this distance
INNER_OFFSET_M = 0.006      # inner sheet of the cut: this far outside the scalp (= the push-out clearance)
FREE_INNER_M = 0.01         # a free strand's inner sheet: this far inward
INNER_GAP_M = 0.001         # the inner sheet stays at least this far below the outer one
SHELL_INNER_M = 0.001       # the shell's inner sheet above the scalp (= its push-out clearance)
SHELL_RELAX_PASSES = 3      # tangential relaxation of the snapped shell patch
CENTRE_BAND_M = 0.015       # hairline strip: |x - face centre| below this
EYE_ROW = 0.07              # hairline strip: rows above y0 + EYE_ROW * Hb only (the beard is below)
MASK_DRGB = 20.0            # garment_gates.HAIR_REF_DRGB
MASK_MIN_AREA = 400         # px @1536
MASK_ALPHA_MIN = 17         # the cut-out alpha that counts as figure
LABEL_SMOOTH_PASSES = 2     # neighbour-majority passes on the label boundary
HOLE_FILL_MAX_M2 = 0.0025   # enclosed non-hair islands up to 25 cm² become hair
HOLE_LOOP_MAX_M = 0.12      # a boundary loop of the hair sheet shorter than this is a hole
EDGE_SMOOTH_PASSES = 3      # Laplacian passes along the cut edge
FEATHER = (0.0, 0.5)        # outer-sheet thickness kept on ring 0 / ring 1 of the cut edge
TEXTURE_SIDE = 512          # the shell's baked colour texture
CORE_RINGS = 3              # recolour: the hair colour is the median of the label this many rings inside
OFF_MIN_DE = 12.0           # recolour: never off-colour within this CIELAB distance of the hair colour
WHITE_DL = 8.0              # recolour: "white" = lighter than the hair by this much L* ...
WHITE_CHROMA = 15.0         # ... and greyer than this chroma (C*ab) and than half the hair's chroma + 3
PALE_CHROMA_SHARE = 0.6     # recolour: "pale" = not darker than the hair, chroma below this share of the hair's ...
PALE_MIN_HAIR_CHROMA = 12.0  # ... on coloured hair only (grey / white hair has no chroma to lose)
# Geometry label (``label_hair``). GEO_MIN_M from the signed distance of H to B's outer wall after the final
# registration, 2026-11-10 (~/claude-out/hair-subtract-geometry/runs/thresholds_after.txt): skin outside the face
# zone on the head — Kai, whose every non-face head vertex off the label is skin — max 0.42 cm (p99.9 0.40); the
# face zone itself reaches 1.51 cm (Kai), 0.96 (Kira spike), 1.37 (Kira e2e: brows, eye sockets — hence no
# geometry there; p95 0.58-0.86 = the registration noise); the hair the blonde back mask missed lies 2-5 cm out
# (Kira e2e back of the head, p50 3.5-4.5 cm). 1.2 cm = the skin's max + more than that noise, under the hair.
GEO_MIN_M = 0.012
GEO_EXACT_M = 0.03          # the signed distance is exact (outer wall triangles) within this band
PROTECT_BEHIND_M = 0.03     # the face zone reaches this far behind the head's centre plane (the ears) ...
PROTECT_BROW_M = 0.03       # ... up to this far above the 2D eye row (the brows, the ear tops); higher only
PROTECT_FACING = 0.7        # ... where B faces forward (normal z above this: the forehead, not the temples)
ENCLOSE_LEAK_SHARE = 0.05   # a scalp patch is enclosed by hair when its face-zone contact is at most this share
                            # of its hair contact (Kira e2e crown: 4 of 155, through the temple's thin hair)
REREG_DILATE = 2            # registration pass 2 leaves out the pass-1 label dilated by this many rings
CAP_LOOP_MAX_M = 0.25       # a boundary loop of the hair sheet shorter than this is capped (the face opening and
                            # the hair's outer edge are 90-190 cm; Kira e2e's gaps between strands 1.6-21 cm)
CAP_ROUNDS = 3              # rounds of capping the hair sheet's small holes (loops touching at a vertex: 2)

#: The cut's gates: (kind, limit, label) like ``garment_fit.GATES``.
CUT_GATES: Dict[str, Tuple[str, float, str]] = {
    "registration_p95_cm": ("max", 1.0, "registration p95 of the non-hair head"),
    "hairline_cm": ("max", 1.5, "hairline 3D vs 2D"),
    "label_holes": ("max", 0, "holes left in the hair sheet"),
    "hair_area_cm2": ("min", 1.0, "hair area"),
}

_VIEW_SIGN = {"front": 1, "back": -1}
_DIRECTIONS = ((2, 1), (2, -1), (0, 1), (0, -1), (1, 1))


class CutRefused(RuntimeError):
    """The cut's gates refused (``result`` carries the numbers)."""

    def __init__(self, result: "CutResult"):
        self.result = result
        super().__init__("cut refused — " + "; ".join(result.reasons))


# --- images -----------------------------------------------------------------------------------------------------------

@dataclass
class View:
    """One view in the HAIRED view's frame: the haired image, the haired figure's silhouette (the mesh source's
    cut-out alpha) and the bald base view padded into the same frame."""
    haired_rgb: np.ndarray      # (h, w, 3) float32 0..255
    haired_mask: np.ndarray     # (h, w) bool
    base_rgb: np.ndarray        # (h, w, 3) float32
    base_mask: np.ndarray       # (h, w) bool


def pad_into(rgb: np.ndarray, mask: np.ndarray, shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    """An image + mask moved into another view's frame of ``shape`` (h, w): both are crops of the same square
    edit canvas (side = max(w, h)), each centred horizontally, so the shift is the difference of the two centring
    offsets; a different height is scaled to ``shape`` first (pure scale)."""
    hh, wh = int(shape[0]), int(shape[1])
    rgb = np.asarray(rgb, np.float32)
    mask = np.asarray(mask, bool)
    if rgb.shape[0] != hh:
        from PIL import Image
        f = hh / rgb.shape[0]
        size = (max(1, int(round(rgb.shape[1] * f))), hh)
        rgb = np.asarray(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize(
            size, Image.Resampling.LANCZOS), np.float32)
        mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(
            size, Image.Resampling.BILINEAR)) >= 128
    wb = rgb.shape[1]
    side = max(hh, wh)
    shift = (side - wb) // 2 - (side - wh) // 2
    out_rgb = np.full((hh, wh, 3), 128.0, np.float32)
    out_mask = np.zeros((hh, wh), bool)
    x0, x1 = max(shift, 0), min(wh, shift + wb)
    if x1 > x0:
        out_rgb[:, x0:x1] = rgb[:, x0 - shift:x1 - shift, :3]
        out_mask[:, x0:x1] = mask[:, x0 - shift:x1 - shift]
    return out_rgb, out_mask


def _figure_mask(data: bytes) -> Tuple[np.ndarray, np.ndarray]:
    """``(rgb, mask)`` of an encoded base view: its alpha when it has a transparent pixel, else the BiRefNet mask
    (``garment_images._mask_image``)."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgba = np.asarray(im.convert("RGBA"))
    alpha = rgba[..., 3]
    if int(alpha.min()) < 255:
        return rgba[..., :3].astype(np.float32), alpha >= MASK_ALPHA_MIN
    from app.core import garment_images as gi
    mask = np.asarray(gi._mask_image(data, (rgba.shape[1], rgba.shape[0]))) >= gi.MASK_THRESHOLD
    return rgba[..., :3].astype(np.float32), mask


def load_view(haired: Path, cutout: Path, base: Path) -> View:
    """A ``View`` from the haired image, its cut-out (RGBA, same frame — the alpha is the silhouette) and the
    bald base view (RGBA, or RGB through BiRefNet)."""
    from PIL import Image
    with Image.open(haired) as im:
        haired_rgb = np.asarray(im.convert("RGB"), np.float32)
    with Image.open(cutout) as im:
        alpha = np.asarray(im.convert("RGBA"))[..., 3]
    if alpha.shape != haired_rgb.shape[:2]:
        raise ValueError(f"The cut-out {cutout.name} is not in the haired view's frame")
    base_rgb, base_mask = _figure_mask(Path(base).read_bytes())
    base_rgb, base_mask = pad_into(base_rgb, base_mask, haired_rgb.shape[:2])
    return View(haired_rgb, alpha >= MASK_ALPHA_MIN, base_rgb, base_mask)


def hair_mask_2d(bald_rgb, bald_mask, haired_rgb, haired_mask, view: str = "front",
                 chest_prior: bool = True) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Hair of the haired view against the bald base view (one frame) -> ``(mask, info)``.

    1. ``changed`` = haired figure AND (|dRGB| > ``MASK_DRGB`` OR outside the bald figure).
    2. ``sure`` hair = haired pixels outside the 3 px dilated bald silhouette in the upper half of the figure (the
       crown band when that is too small); its median colour is the hair colour, the base's skin colour the skin.
    3. A changed pixel is hair when nearer to the hair colour than to the skin colour, or outside the bald figure.
    4. Front: nothing in the face box (rows 0.05..0.13 Hb, +-0.85 of the head half-width) and — ``chest_prior`` —
       nothing inside the body below the chin row.
    5. Opened 2 / closed 4 (@1536), holes filled, components >= ``MASK_MIN_AREA`` (@1536) that reach the crown
       band (the top 0.08 Hb of the haired figure)."""
    from scipy import ndimage
    from app.core.garment_gates import skin_colour
    bald_rgb = np.asarray(bald_rgb, np.float32)
    haired_rgb = np.asarray(haired_rgb, np.float32)
    bald_mask = np.asarray(bald_mask, bool)
    haired_mask = np.asarray(haired_mask, bool)
    h = bald_mask.shape[0]

    def it(n: float) -> int:
        return max(1, int(round(n * h / 1536)))

    if not bald_mask.any() or not haired_mask.any():
        return np.zeros_like(haired_mask), {"empty": True}
    diff = np.abs(bald_rgb - haired_rgb).mean(2)
    changed = haired_mask & ((diff > MASK_DRGB) | ~bald_mask)
    ys = np.nonzero(bald_mask.any(1))[0]
    y0, hb = int(ys.min()), int(ys.max() - ys.min())
    grown = haired_mask & ~ndimage.binary_dilation(bald_mask, iterations=it(3))
    grown[int(y0 + 0.5 * hb):] = False
    grown = ndimage.binary_opening(grown, iterations=it(2))
    top = int(np.nonzero(haired_mask.any(1))[0].min())
    crown = changed.copy()
    crown[int(top + 0.06 * hb):] = False
    use_grown = grown.sum() >= 500 * (h / 1536) ** 2
    sure = grown if use_grown else crown
    if not sure.any():
        return np.zeros_like(haired_mask), {"empty": True, "sure_px": 0}
    hair_rgb = np.median(haired_rgb[sure], 0)
    skin = skin_colour(bald_rgb, bald_mask)
    d_hair = np.abs(haired_rgb - hair_rgb[None, None, :]).mean(2)
    d_skin = (np.abs(haired_rgb - np.asarray(skin, np.float32)[None, None, :]).mean(2) if skin is not None
              else np.full_like(d_hair, np.inf))
    hair = changed & ((d_hair < d_skin) | ~bald_mask)
    if view == "front":
        chin = int(y0 + 0.13 * hb)
        r0 = int(y0 + 0.05 * hb)
        span = np.nonzero(bald_mask[int(y0 + 0.08 * hb)])[0]
        if len(span):
            cx, hw = (span.min() + span.max()) / 2, (span.max() - span.min()) / 2
            hair[r0:chin, max(0, int(cx - 0.85 * hw)):int(cx + 0.85 * hw) + 1] = False
        if chest_prior:
            inner = ndimage.binary_erosion(bald_mask, iterations=it(3))
            inner[:chin] = False
            hair &= ~inner
    hair = ndimage.binary_closing(ndimage.binary_opening(hair, iterations=it(2)), iterations=it(4))
    hair = ndimage.binary_fill_holes(hair)
    labels, count = ndimage.label(hair)
    if count:
        sizes = np.bincount(labels.ravel())
        keep = np.nonzero(sizes >= MASK_MIN_AREA * (h / 1536) ** 2)[0]
        keep = keep[keep > 0]
        band = labels[: int(top + 0.08 * hb)]
        reach = np.unique(band[band > 0])
        hair = np.isin(labels, np.intersect1d(keep, reach))
    info = {"hair_rgb": [round(float(c), 1) for c in hair_rgb],
            "skin_rgb": None if skin is None else [round(float(c), 1) for c in skin],
            "sure_source": "grown" if use_grown else "crown", "sure_px": int(sure.sum()), "px": int(hair.sum())}
    return hair, info


# --- projection -------------------------------------------------------------------------------------------------------

class Frame:
    """Orthographic image <-> mesh mapping through the shared framing (``garment_fit._frame``: the mask bbox
    and the mesh bbox). ``sign`` = +1 for the front view (image x right = +x), -1 for the back view."""

    def __init__(self, P: np.ndarray, mask: np.ndarray, sign: int):
        self.s, self.c, self.m = gf._frame(np.asarray(P, np.float64), mask)
        self.sign = int(sign)
        self.shape = np.asarray(mask).shape

    def to_px(self, P: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        P = np.asarray(P, np.float64)
        px = self.c[0] + self.sign * (P[:, 0] - self.m[0]) / self.s
        py = self.c[1] - (P[:, 1] - self.m[1]) / self.s
        return px, py

    def x_of_col(self, col: float) -> float:
        return float(self.m[0] + self.sign * (col - self.c[0]) * self.s)

    def y_of_row(self, row: float) -> float:
        return float(self.m[1] - (row - self.c[1]) * self.s)


def depth_visible(depth: np.ndarray, u: np.ndarray, v: np.ndarray, cell: float, tol: float) -> np.ndarray:
    """Depth-buffer visibility: ``depth`` grows toward the camera; a point is visible when it lies within
    ``tol`` of the nearest point over the 3 x 3 neighbourhood of its ``cell``-sized cell in (u, v) (at ~5 mm
    vertex spacing a 4 mm cell often holds one vertex only)."""
    from scipy import ndimage
    if len(depth) == 0:
        return np.zeros(0, bool)
    iu = np.floor(np.asarray(u) / cell).astype(np.int64)
    iv = np.floor(np.asarray(v) / cell).astype(np.int64)
    iu -= iu.min()
    iv -= iv.min()
    grid = np.full((iv.max() + 1, iu.max() + 1), -np.inf)
    np.maximum.at(grid, (iv, iu), depth)
    grid = ndimage.maximum_filter(grid, size=3, mode="nearest")
    return depth >= grid[iv, iu] - tol


def visible_axis(P: np.ndarray, axis: int, sign: int, cell: float, tol: float) -> np.ndarray:
    """Visibility along a mesh axis from the ``sign`` side."""
    others = [i for i in range(3) if i != axis]
    return depth_visible(P[:, axis] * sign, P[:, others[0]], P[:, others[1]], cell, tol)


def mask_vote(P: np.ndarray, frame: Frame, mask: np.ndarray, cell: float, tol: float) -> np.ndarray:
    """Vertices visible from the view that project into ``mask``."""
    px, py = frame.to_px(P)
    vis = depth_visible(P[:, 2] * frame.sign, px * frame.s, py * frame.s, cell, tol)
    h, w = mask.shape
    ix = np.clip(np.round(px).astype(np.int64), 0, w - 1)
    iy = np.clip(np.round(py).astype(np.int64), 0, h - 1)
    inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    return vis & inside & np.asarray(mask, bool)[iy, ix]


def outer_wall(P: np.ndarray, cell: float, tol: float) -> np.ndarray:
    """The outer wall of a double-walled mesh: frontmost within ``tol`` from +-z, +-x or +y."""
    out = np.zeros(len(P), bool)
    for axis, sign in _DIRECTIONS:
        out |= visible_axis(P, axis, sign, cell, tol)
    return out


# --- vertex sets on a mesh --------------------------------------------------------------------------------------------

def dilate(mask: np.ndarray, adj, passes: int) -> np.ndarray:
    A = adj[0]
    m = np.asarray(mask, bool).copy()
    for _ in range(passes):
        m = m | (A @ m.astype(np.float64) > 0)
    return m


def erode(mask: np.ndarray, adj, passes: int) -> np.ndarray:
    return ~dilate(~np.asarray(mask, bool), adj, passes)


def majority(mask: np.ndarray, adj, passes: int) -> np.ndarray:
    """Neighbour-majority smoothing of a vertex set: a vertex is in when at least half of its neighbours are
    (a straight boundary stays, a one-vertex tooth or notch goes)."""
    A, deg = adj
    m = np.asarray(mask, bool).copy()
    deg = np.maximum(np.asarray(deg, np.float64).ravel(), 1.0)
    for _ in range(passes):
        share = (A @ m.astype(np.float64)) / deg
        m = np.where(share > 0.5, True, np.where(share < 0.5, False, m))
    return m


def _face_components(F: np.ndarray, n: int) -> np.ndarray:
    """Per-vertex component label of the edge graph of ``F``."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    rows = np.concatenate([F[:, 0], F[:, 1], F[:, 2]])
    cols = np.concatenate([F[:, 1], F[:, 2], F[:, 0]])
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    return connected_components(g, directed=False)[1]


def faces_all(F: np.ndarray, vmask: np.ndarray) -> np.ndarray:
    return F[vmask[F].all(1)]


def largest_components(F: np.ndarray, n: int, keep_share: float) -> np.ndarray:
    """Vertex mask of the components of ``F`` holding at least ``keep_share`` of its faces."""
    if len(F) == 0:
        return np.zeros(n, bool)
    lab = _face_components(F, n)
    counts = np.bincount(lab[F[:, 0]], minlength=lab.max() + 1)
    used = np.zeros(n, bool)
    used[F.ravel()] = True
    return (counts >= keep_share * len(F))[lab] & used


def fill_label_holes(F: np.ndarray, P_m: np.ndarray, label: np.ndarray, adj, max_area_m2: float
                     ) -> Tuple[np.ndarray, int]:
    """Islands of non-label vertices that touch the label and whose faces cover at most ``max_area_m2`` become
    label -> ``(label, islands filled)``. A non-label component that touches no label (a floater) stays; the
    big rest of the mesh is larger than any hole."""
    from scipy.sparse.csgraph import connected_components
    label = np.asarray(label, bool).copy()
    A = adj[0].tocsr()
    rest = np.nonzero(~label)[0]
    if len(rest) == 0 or not label.any():
        return label, 0
    sub = A[rest][:, rest]
    count, comp_rest = connected_components(sub, directed=False)
    comp = np.full(len(label), -1, np.int64)
    comp[rest] = comp_rest
    touches = np.zeros(count, bool)
    touch_v = (A @ label.astype(np.float64)) > 0
    np.logical_or.at(touches, comp_rest, touch_v[rest])
    areas = gf.triangle_areas(P_m, F)
    first = np.where(comp[F[:, 0]] >= 0, comp[F[:, 0]], np.where(comp[F[:, 1]] >= 0, comp[F[:, 1]], comp[F[:, 2]]))
    has = first >= 0
    area = np.bincount(first[has], weights=areas[has], minlength=count)
    fill = touches & (area <= max_area_m2)
    if fill.any():
        label[rest[fill[comp_rest]]] = True
    return label, int(fill.sum())


def boundary_edges(F: np.ndarray) -> np.ndarray:
    """The edges used by exactly one face (sorted vertex pairs)."""
    if len(F) == 0:
        return np.zeros((0, 2), np.int64)
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    uniq, cnt = np.unique(E, axis=0, return_counts=True)
    return uniq[cnt == 1]


def boundary_loops(F: np.ndarray, P: np.ndarray) -> List[Tuple[np.ndarray, float]]:
    """``[(vertices, perimeter)]`` per connected component of the boundary-edge graph of ``F`` (one loop each,
    unless loops touch at a vertex)."""
    B = boundary_edges(F)
    if len(B) == 0:
        return []
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    verts, local = np.unique(B, return_inverse=True)
    local = local.reshape(-1, 2)
    g = coo_matrix((np.ones(len(local)), (local[:, 0], local[:, 1])), shape=(len(verts), len(verts)))
    count, lab = connected_components(g, directed=False)
    lengths = np.linalg.norm(P[B[:, 0]] - P[B[:, 1]], axis=1)
    per = np.bincount(lab[local[:, 0]], weights=lengths, minlength=count)
    return [(verts[lab == i], float(per[i])) for i in range(count)]


def _boundary_neighbours(B: np.ndarray) -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = {}
    for a, b in B.tolist():
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return out


def smooth_edge(P: np.ndarray, B: np.ndarray, passes: int) -> np.ndarray:
    """Laplacian smoothing (lambda 0.5) of the vertices on the boundary edges ``B`` along their loops; a vertex
    with other than two boundary neighbours (a pinch) stays."""
    P = np.asarray(P, np.float64).copy()
    nb = _boundary_neighbours(B)
    idx = np.array([v for v, n in nb.items() if len(n) == 2], np.int64)
    if len(idx) == 0:
        return P
    pair = np.array([nb[v] for v in idx.tolist()], np.int64)
    for _ in range(passes):
        P[idx] = 0.5 * P[idx] + 0.25 * (P[pair[:, 0]] + P[pair[:, 1]])
    return P


# --- registration -----------------------------------------------------------------------------------------------------

def register(Q0: np.ndarray, Pb: np.ndarray, Fb: np.ndarray, exclude: np.ndarray, k: float, *,
             iterations: int = ICP_ITERATIONS, scale: bool = True):
    """Similarity ICP of ``Q0`` (H placed in B's frame) onto B over the vertices not ``exclude``d within the top
    ``REGISTER_TOP_M`` of H, point-to-plane: each vertex pairs with its nearest dense surface sample of B within
    ``NONHAIR_MAX_M`` and that sample's triangle normal; one step solves the linearised small similarity
    (rotation ``w``, scale ``ds``, shift ``t`` about the centroid) for ``sum(((x - p) . n + (x x n) . w +
    (x . n) ds + n . t)^2)`` and applies it exactly (Rodrigues). Point-to-point pairs have spurious fixed points:
    once every vertex keeps its sample the step is the identity although the pose is off (measured on a synthetic
    head, 3.4 mm at the crown after 60 steps; ``scripts/smoke_garment_cut.py`` [c]). Returns ``(Q, tree of B's
    samples, distance per vertex in B units, report)``."""
    from scipy.spatial import cKDTree
    from scipy.spatial.transform import Rotation
    pts, tri_of = gf._surface_samples(Pb, Fb)
    fn = np.cross(Pb[Fb[:, 1]] - Pb[Fb[:, 0]], Pb[Fb[:, 2]] - Pb[Fb[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    normals = np.concatenate([fn[tri_of], gf.vertex_normals(Pb, Fb)])
    tree = cKDTree(np.concatenate([pts, Pb]))
    Q = np.asarray(Q0, np.float64).copy()
    report: Dict[str, Any] = {}
    for it in range(iterations):
        d, j = tree.query(Q)
        use = (~exclude) & (d * k < NONHAIR_MAX_M) & (Q[:, 1] > Q[:, 1].max() - REGISTER_TOP_M / k)
        if use.sum() < 100:
            raise ValueError("Too few non-hair correspondences between the haired mesh and the base body")
        c = Q[use].mean(0)
        x, p, n = Q[use] - c, tree.data[j[use]] - c, normals[j[use]]
        A = np.concatenate([np.cross(x, n), (x * n).sum(1, keepdims=True), n], 1)
        if not scale:
            A = np.delete(A, 3, axis=1)
        r = -((x - p) * n).sum(1)
        sol, *_ = np.linalg.lstsq(A, r, rcond=None)
        if not scale:
            sol = np.insert(sol, 3, 0.0)
        w, ds, t = sol[:3], float(sol[3]), sol[3 + 1:]
        R = Rotation.from_rotvec(w).as_matrix()
        Q = (1.0 + ds) * (Q - c) @ R.T + c + t
        report = {"iterations": it + 1, "last_scale_step": 1.0 + ds,
                  "last_step_mm": float(np.linalg.norm(w) * np.abs(x).max() * k * 1000 + np.linalg.norm(t) * k * 1000),
                  "used": int(use.sum())}
    d, _ = tree.query(Q)
    return Q, tree, d, report


def _apply(T, P: np.ndarray) -> np.ndarray:
    s, R, a, b = T
    return (s * (np.asarray(P, np.float64) - a) @ R.T) + b


def fill_enclosed(label: np.ndarray, allowed: np.ndarray, barrier: np.ndarray, adj,
                  leak_share: float = 0.0) -> Tuple[np.ndarray, int, List[Dict[str, Any]]]:
    """Components of ``allowed`` non-label vertices enclosed by the label become label, whatever their size ->
    ``(label, components filled, [{n, hair, barrier}] of the largest components)``. A component is enclosed when
    the non-label ``barrier`` vertices it touches (the face zone, the body) number at most ``leak_share`` of the
    label vertices it touches — a gap of a few vertices where the hairline's mask ran thin does not open a scalp
    to the face. Vertices neither allowed nor barrier (H's grooves between strands that the outer-wall test
    leaves out) are walls: never crossed, never a leak. The crown of a haired mesh can lie INSIDE the bald head
    (the mesher's skull is smaller under flat hair: Kira's crown p50 1.0 cm inside B) — no distance test calls
    it hair, but the hair outside B surrounds it on the scalp."""
    from scipy.sparse.csgraph import connected_components
    label = np.asarray(label, bool).copy()
    cand = np.asarray(allowed, bool) & ~label
    idx = np.nonzero(cand)[0]
    if len(idx) == 0:
        return label, 0, []
    A = adj[0].tocsr()
    count, comp = connected_components(A[idx][:, idx], directed=False)
    hair_n = np.zeros(count)
    leak_n = np.zeros(count)
    # every (candidate, neighbour) edge: count distinct neighbours per component
    rows, cols = A[idx].nonzero()
    ci, nb = comp[rows], cols
    pairs = np.unique(np.stack([ci, nb], 1), axis=0)
    is_hair = label[pairs[:, 1]]
    is_leak = np.asarray(barrier, bool)[pairs[:, 1]] & ~label[pairs[:, 1]]
    np.add.at(hair_n, pairs[:, 0], is_hair)
    np.add.at(leak_n, pairs[:, 0], is_leak)
    fill = (hair_n > 0) & (leak_n <= leak_share * hair_n)
    if fill.any():
        label[idx[fill[comp]]] = True
    sizes = np.bincount(comp, minlength=count)
    top = [{"n": int(sizes[c]), "hair": int(hair_n[c]), "barrier": int(leak_n[c]), "filled": bool(fill[c])}
           for c in np.argsort(-sizes)[:6]]
    return label, int(fill.sum()), top


def small_loops(F: np.ndarray, P_m: np.ndarray, max_m: float) -> List[Tuple[np.ndarray, np.ndarray, float]]:
    """``[(directed boundary edges, loop vertices, perimeter)]`` of the boundary loops of ``F`` shorter than
    ``max_m`` (``P_m`` in metres); each edge in the direction its one face runs it."""
    if len(F) == 0:
        return []
    D = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    _u, inv, cnt = np.unique(np.sort(D, 1), axis=0, return_inverse=True, return_counts=True)
    Db = D[cnt[inv.ravel()] == 1]
    out = []
    for verts, per in boundary_loops(F, P_m):
        if per < max_m:
            on = np.isin(Db, verts).all(1)
            out.append((Db[on], verts, per))
    return out


def label_hair(Q: np.ndarray, sd: np.ndarray, adj, *, outer: np.ndarray, head: np.ndarray, voted: np.ndarray,
               loose: np.ndarray, hairline_y: Optional[float], eye_y: float,
               facing: np.ndarray, centre_z: float, k: float, F: np.ndarray) -> Dict[str, Any]:
    """The hair label of H (registered into B's frame as ``Q``; ``sd`` its signed distance to B's outer wall in
    METRES, + outside) -> ``{"hair": vertex mask, "report": {...}}``. GEOMETRY first, colour at the face:

    - ``protect`` (the face zone, colour decides): H's outer wall on the head, below the 2D hairline (front
      centre strip, ``hairline_y``) and in front of ``PROTECT_BEHIND_M`` behind the head's centre plane — the
      face, the brows, the ears; above ``PROTECT_BROW_M`` over the eye row only where B faces forward
      (``facing`` > ``PROTECT_FACING``: the forehead, not the temples). No geometry seed or growth there — a brow
      or an ear stands out of B by up to 2 cm (Kira e2e, Kai), as far as thin hair; the masks' votes still
      count there (the hairline band is colour's).
    - Geometry seeds: the outer wall on the head (nearest B vertex Head-weighted) outside ``protect`` more than
      ``GEO_MIN_M`` outside B. The skin outside the face zone stays within it (derivation at ``GEO_MIN_M``);
      the hair the blonde back mask missed lies 2-5 cm out (Kira e2e back of the head, p50 3.5-4.5 cm).
    - With the mask votes (the loose ones only that far outside B, ``LOOSE_EPS_M``): seeds (eroded + dilated
      once), growth over the outer wall more than ``LOOSE_EPS_M`` outside B (never into ``protect``), closing,
      opening, majority (the old label steps).
    - The crown: candidates enclosed by hair on the head outside ``protect`` are filled (``fill_enclosed``), then
      holes up to ``HOLE_FILL_MAX_M2`` anywhere (``fill_label_holes``).
    - Long hair on the shoulders and the back lies ON the body (no distance test separates it): there only the
      mask votes and the growth from them count; the largest label component is kept (connectivity from the
      scalp — a strand piece or an inner sheet under the crown on its own is dropped; the fit gates one
      component anyway)."""
    deep = sd < -DEEP_M
    y_line = float(hairline_y) if hairline_y is not None else float(Q[:, 1].max())
    below = Q[:, 1] < y_line
    low = below & (Q[:, 1] < eye_y + PROTECT_BROW_M / k) & (Q[:, 2] > centre_z - PROTECT_BEHIND_M / k)
    protect = outer & head & (low | (below & (facing > PROTECT_FACING)))
    geo = outer & head & ~protect & (sd > GEO_MIN_M)
    guess = voted | (loose & (sd > LOOSE_EPS_M)) | geo
    seed = dilate(erode(guess & outer & ~deep, adj, 1), adj, 1)
    grown = seed | (dilate(seed, adj, GROW_RINGS) & outer & (sd > LOOSE_EPS_M) & ~protect)
    hair = erode(dilate(grown, adj, 3), adj, 3) & outer & ~deep
    hair = dilate(erode(hair, adj, 1), adj, 1)
    hair = majority(hair, adj, LABEL_SMOOTH_PASSES) & outer & ~deep
    hair, enclosed, enclosure = fill_enclosed(hair, outer & head & ~protect, outer & (protect | ~head), adj,
                                              ENCLOSE_LEAK_SHARE)
    hair, filled = fill_label_holes(F, Q * k, hair, adj, HOLE_FILL_MAX_M2)
    hair &= largest_components(faces_all(F, hair), len(Q), 0.5)
    return {"hair": hair, "report": {
        "geo_seeds": int(geo.sum()), "geo_only": int((geo & ~voted & ~loose).sum()), "protect": int(protect.sum()),
        "seeds": int(seed.sum()), "grown": int(grown.sum()), "enclosed_filled": enclosed, "enclosure": enclosure, "holes_filled": filled,
        "hairline_y_m": None if hairline_y is None else round(float(hairline_y) * k, 4)}}


# --- result -----------------------------------------------------------------------------------------------------------

@dataclass
class CutResult:
    glb: bytes
    ok: bool
    reasons: List[str]
    metrics: Dict[str, Any]
    shape: str
    clearance_m: float
    spread_m: float
    report: Dict[str, Any] = field(default_factory=dict)


def fit_params(shape: str) -> Tuple[float, float]:
    """``(clearance_m, spread_m)`` of the placed fit of a cut / shell (``garment_fit.fit_hair``): the cut's inner
    sheet sits at ``CLEAR_CUT_M`` and keeps the spike's push spread; the shell's inner sheet at ``SHELL_INNER_M``
    without spread (a shell pushed to its thickness would fold both sheets onto one)."""
    if shape == "shell":
        return SHELL_INNER_M, 0.0
    return CLEAR_CUT_M, gf.SPREAD_M


def _scale(body_u, body_r) -> Tuple[float, np.ndarray]:
    """``(k metres per unrigged unit, head mask of the unrigged vertices)`` — the head similarity
    (``garment_fit.fit_hair``)."""
    corr, _ = gf.uv_correspondence(body_u, body_r)
    Wb = gf.dense_weights(body_r)[corr]
    head = Wb[:, gf.joint_index(body_r, "head")] > 0.5
    k, _, _, _ = gf.region_similarity(body_u, body_r, corr, head)
    if not (k > 0 and math.isfinite(k)):
        raise ValueError("Could not measure the unrigged -> rigged scale")
    return float(k), head


def _hairline(views: Dict[str, View], masks: Dict[str, np.ndarray], frame_h: Frame, k_h: float,
              to_q: Callable[[np.ndarray], np.ndarray], zc_h: float) -> Dict[str, Any]:
    """The 2D hairline of the front view (front centre strip, the lower edge of the first contiguous run of hair
    rows from the hair top, above ``EYE_ROW``) as points in B's frame: ``{row, eye_row, x, y, y_eye}`` (``y`` None
    without hair in the strip)."""
    base = views["front"].base_mask
    ys = np.nonzero(base.any(1))[0]
    y0, hb = int(ys.min()), int(ys.max() - ys.min())
    xr = np.nonzero(base[int(y0 + 0.08 * hb)])[0]
    cx = float((xr.min() + xr.max()) / 2) if len(xr) else float(base.shape[1] / 2)
    band_px = CENTRE_BAND_M / k_h / frame_h.s
    cols = slice(max(0, int(cx - band_px)), int(cx + band_px) + 1)
    eye_row = int(y0 + EYE_ROW * hb)
    strip = masks["front"][:eye_row, cols]
    rows = np.nonzero(strip.any(1))[0]
    out: Dict[str, Any] = {"eye_row": eye_row, "face_centre_px": cx, "row": None, "y": None}
    x_h = frame_h.x_of_col(cx)
    eye = to_q(np.array([[x_h, frame_h.y_of_row(eye_row), zc_h]]))[0]
    out.update(x=float(eye[0]), y_eye=float(eye[1]))
    if len(rows):
        breaks = np.nonzero(np.diff(rows) > 1)[0]
        row = float(rows[breaks[0]] if len(breaks) else rows[-1])
        point = to_q(np.array([[x_h, frame_h.y_of_row(row), zc_h]]))[0]
        out.update(row=row, x=float(point[0]), y=float(point[1]))
    return out


def _snap_offsets(points: np.ndarray, surface: "gf.BodySurface", k: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(closest B surface point, outward unit normal there, distance in metres)`` per point."""
    snap, normal = surface.closest(points)
    return snap, normal, np.linalg.norm(points - snap, axis=1) * k


def _relax_on_surface(P: np.ndarray, F: np.ndarray, surface: "gf.BodySurface", passes: int) -> Tuple[np.ndarray, np.ndarray]:
    """Tangential relaxation of a patch lying on B: Laplacian passes, each projected back onto B
    (``garment_fit.BodySurface.closest``) — snapped vertices that bunched up spread out again. -> ``(points, normals)``."""
    adj = gf._adjacency(F, len(P))
    A, deg = adj
    deg = np.maximum(np.asarray(deg, np.float64).ravel(), 1.0)[:, None]
    P, N = surface.closest(P)
    for _ in range(passes):
        avg = (A @ P) / deg
        P, N = surface.closest(0.5 * P + 0.5 * avg)
    return P, N


def _bake_shell_texture(P: np.ndarray, centre: np.ndarray, to_h, R_inv: np.ndarray,
                        frames: Dict[str, Frame], views: Dict[str, View], masks: Dict[str, np.ndarray],
                        side: int = TEXTURE_SIDE) -> Tuple[np.ndarray, bytes, Dict[str, Any]]:
    """Seamless UVs of the shell's vertices ``P`` (B frame; azimuthal equidistant from the head top around
    ``centre``) and their colour texture: every texel's surface point (inverse distance over the 4 UV-nearest
    vertices) is mapped into H's frame (``to_h``) and sampled from the haired views — weighted by how squarely
    the view sees it, only where the view's hair mask holds; elsewhere the median hair colour."""
    from PIL import Image
    from scipy.spatial import cKDTree
    d = gf._unit(np.asarray(P, np.float64) - centre)
    theta = np.arccos(np.clip(d[:, 1], -1.0, 1.0))
    phi = np.arctan2(d[:, 0], d[:, 2])
    theta_max = float(min(math.pi * 0.98, max(float(theta.max()) * 1.05, 1e-3)))
    r = 0.48 * theta / theta_max
    uv = np.stack([0.5 + r * np.sin(phi), 0.5 + r * np.cos(phi)], 1)

    grid = (np.arange(side) + 0.5) / side
    U, V = np.meshgrid(grid, grid)          # row i <-> v, col j <-> u (glTF: v = 0 is the top row)
    du, dv = U.ravel() - 0.5, V.ravel() - 0.5
    tr = np.hypot(du, dv)
    inside = tr <= 0.5
    th = np.minimum(tr / 0.48, 1.0) * theta_max
    ph = np.arctan2(du, dv)
    dirs = np.stack([np.sin(th) * np.sin(ph), np.cos(th), np.sin(th) * np.cos(ph)], 1)
    tree = cKDTree(uv)
    dist, idx = tree.query(np.stack([U.ravel(), V.ravel()], 1), k=min(4, len(uv)))
    if dist.ndim == 1:
        dist, idx = dist[:, None], idx[:, None]
    w = 1.0 / np.maximum(dist, 1e-6)
    pts = (P[idx] * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    pts_h = to_h(pts)
    n_h = dirs @ R_inv.T
    colour = np.zeros((len(pts), 3))
    weight = np.zeros(len(pts))
    hair_px = []
    for view, frame in frames.items():
        rgb = views[view].haired_rgb
        mask = masks[view]
        hair_px.append(rgb[mask])
        px, py = frame.to_px(pts_h)
        h, wd = mask.shape
        ix = np.clip(np.round(px).astype(np.int64), 0, wd - 1)
        iy = np.clip(np.round(py).astype(np.int64), 0, h - 1)
        ok = (px >= 0) & (px < wd) & (py >= 0) & (py < h) & mask[iy, ix]
        facing = np.maximum(n_h[:, 2] * frame.sign, 0.0)
        top = np.abs(n_h[:, 2]) < 0.05     # seen edge-on by both views: both count
        wv = np.where(ok, np.where(top, 1.0, facing), 0.0)
        colour += rgb[iy, ix] * wv[:, None]
        weight += wv
    pool = np.concatenate([p for p in hair_px if len(p)]) if any(len(p) for p in hair_px) else np.zeros((0, 3))
    median = np.median(pool, 0) if len(pool) else np.array([60.0, 45.0, 35.0])
    out = np.where(weight[:, None] > 1e-6, colour / np.maximum(weight, 1e-6)[:, None], median[None, :])
    covered = inside & (dist[:, 0] < 0.02)
    img = np.clip(out, 0, 255).reshape(side, side, 3).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    info = {"side": side, "theta_max_deg": round(math.degrees(theta_max), 1),
            "sampled_share": round(float((weight[covered] > 1e-6).mean()) if covered.any() else 0.0, 3),
            "mean_colour_srgb": [round(float(c), 1) for c in (out[covered].mean(0) if covered.any() else median)],
            "median_hair_srgb": [round(float(c), 1) for c in median]}
    return uv, buf.getvalue(), info


def _finite(value: float, digits: int) -> Optional[float]:
    """``value`` rounded, None when it could not be measured (NaN): a metric is JSON, and the gates refuse a
    None as "missing"."""
    return round(float(value), digits) if math.isfinite(value) else None


# --- colour mend --------------------------------------------------------------------------------------------------

def lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 (..., 3) -> CIELAB (D65)."""
    c = np.asarray(rgb, np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _rgb_of(image: bytes) -> Optional[np.ndarray]:
    """A texture as (h, w, 3) float 0..255, None when there is none / it does not decode."""
    if not image:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(image)) as im:
            return np.asarray(im.convert("RGB"), np.float64)
    except Exception:  # noqa: BLE001 — an undecodable texture only switches the colour trim off
        return None


def sample_texture(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Nearest texel of glTF UVs (v = 0 is the top row), wrapped."""
    h, w = tex.shape[:2]
    uv = np.asarray(uv, np.float64)
    x = np.floor(np.mod(uv[:, 0], 1.0) * w).astype(np.int64).clip(0, w - 1)
    y = np.floor(np.mod(uv[:, 1], 1.0) * h).astype(np.int64).clip(0, h - 1)
    return tex[y, x]


def off_colour(L: np.ndarray, hair_lab: np.ndarray,
               skin_lab: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(skin-like, white, pale)`` masks of CIELAB colours ``L`` that are not hair: nearer to the skin colour
    than to the hair colour; white = lighter than the hair by ``WHITE_DL`` and greyer than ``WHITE_CHROMA`` and
    than half the hair's own chroma + 3 (Kira's white streaks: L* 71, C* 5 on blonde hair of L* 59, C* 27);
    pale = a washed-out grey of coloured hair that is not lighter by ``WHITE_DL`` — at least as light as the hair,
    chroma below ``PALE_CHROMA_SHARE`` of the hair's (Kira's lower side strands after the white mend: texels
    L* 66, C* 11 on hair of L* 59, C* 27, their halo C* 14-16 — the mesher's guess for strands neither haired
    view shows; they rendered as pale streaks). None of them within ``OFF_MIN_DE`` of the hair colour."""
    L = np.asarray(L, np.float64).reshape(-1, 3)
    d_hair = np.linalg.norm(L - hair_lab, axis=1)
    far = d_hair > OFF_MIN_DE
    skin = (np.linalg.norm(L - skin_lab, axis=1) < d_hair) & far if skin_lab is not None else np.zeros(len(L), bool)
    grey = min(WHITE_CHROMA, 0.5 * float(np.hypot(hair_lab[1], hair_lab[2])) + 3.0)
    chroma = np.hypot(L[:, 1], L[:, 2])
    white = (L[:, 0] > hair_lab[0] + WHITE_DL) & (chroma < grey) & far
    hair_chroma = float(np.hypot(hair_lab[1], hair_lab[2]))
    pale = ((L[:, 0] >= hair_lab[0]) & (chroma < PALE_CHROMA_SHARE * hair_chroma) & far
            if hair_chroma >= PALE_MIN_HAIR_CHROMA else np.zeros(len(L), bool))
    return skin, white, pale


def _raster(uv_faces: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """Texels covered by the UV triangles ``uv_faces`` (n, 3, 2), one texel of margin."""
    from PIL import Image, ImageDraw
    from scipy import ndimage
    h, w = shape
    im = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(im)
    for tri in np.asarray(uv_faces, np.float64):
        draw.polygon([(float(u) * w - 0.5, float(v) * h - 0.5) for u, v in tri], fill=255)
    return ndimage.binary_dilation(np.asarray(im) > 0, iterations=1)


def recolour_texture(tex: np.ndarray, cover: np.ndarray, hair_lab: np.ndarray,
                     skin_lab: Optional[np.ndarray]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Paint the off-colour texels (``off_colour``: skin-like, white or pale) within ``cover`` (the texels the hair
    uses) over with the nearest hair texel. The mesher paints the forehead skin a centimetre or two past the
    hairline and the background's white along strand edges onto H's hair surface (Kira 2026-11-10); the hair
    GEOMETRY there is right — its hairline agrees with the 2D mask's to 0.4 cm, and peeling the skin-coloured
    border off the label moved it to 1.9 cm — so the colour is mended, not the label. The paint is the nearest
    texel within ``OFF_MIN_DE`` of the hair colour. -> ``(texture, report)``."""
    from scipy import ndimage
    tex = np.array(tex, np.float64)
    L = lab(tex[cover])
    skin, white, pale = off_colour(L, hair_lab, skin_lab)
    off = np.zeros(cover.shape, bool)
    off[cover] = skin | white | pale
    # the paint comes from hair-coloured texels only (within OFF_MIN_DE): the nearest merely "not off" texel is
    # the washed-out halo of an off region, and copying it inwards left Kira's pale streaks in place (C* 14)
    source = np.zeros(cover.shape, bool)
    source[cover] = np.linalg.norm(L - hair_lab, axis=1) <= OFF_MIN_DE
    source &= ~off
    if not off.any() or not source.any():
        return tex, {"recoloured_texels": 0, "recoloured_share": 0.0}
    _d, (iy, ix) = ndimage.distance_transform_edt(~source, return_indices=True)
    tex[off] = tex[iy[off], ix[off]]
    n = int(off.sum())
    return tex, {"recoloured_texels": n, "recoloured_share": round(n / max(int(cover.sum()), 1), 4),
                 "skin_texels": int(skin.sum()), "white_texels": int((white & ~skin).sum()),
                 "pale_texels": int((pale & ~white & ~skin).sum())}


def _view_skin_lab(view: "View", hair_mask: np.ndarray) -> Optional[np.ndarray]:
    """CIELAB median of the bald front view's skin: its figure without hair in the top eighth of the figure (the
    face), None when there is none."""
    rows = np.nonzero(view.base_mask.any(1))[0]
    if not len(rows):
        return None
    face = view.base_mask & ~hair_mask
    face[: rows[0]] = False
    face[rows[0] + max(1, (rows[-1] - rows[0]) // 8):] = False
    return lab(np.median(view.base_rgb[face], 0)) if face.sum() >= 50 else None


def _png(tex: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.clip(np.round(tex), 0, 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


# --- the cut --------------------------------------------------------------------------------------------------------

def cut_hair(haired_glb: bytes, unrigged_glb: bytes, rigged_glb: bytes, views: Dict[str, View], *,
             shape: str = "cut", thickness_m: float = DEFAULT_SHELL_M,
             place_mask: Optional[np.ndarray] = None) -> CutResult:
    """Cut the hair off the haired mesh ``haired_glb`` against the base body (module docstring).

    ``views``: ``front`` and ``back`` (``View``). ``shape`` ``cut`` | ``shell``; ``thickness_m`` the shell's
    thickness. ``place_mask``: the silhouette (in the haired view's frame) of the front view the unrigged body was
    meshed from — default the bald front view's; an outfit body passes its own front view's. ValueError for
    unusable inputs; the gates' verdict is in the result (``ok`` / ``reasons``)."""
    from app.core.glb_mesh import body_arrays, static_arrays, static_glb
    started = time.monotonic()
    if shape not in SHAPES:
        raise ValueError(f"unknown cut shape {shape!r}")
    if not (SHELL_MIN_M - 1e-9 <= thickness_m <= SHELL_MAX_M + 1e-9):
        raise ValueError(f"shell thickness must be within {SHELL_MIN_M * 1000:g}..{SHELL_MAX_M * 1000:g} mm")
    if set(views) != set(_VIEW_SIGN):
        raise ValueError("cut_hair needs the front and the back view")

    Ph0, Fh0, Uh, img_h, mime_h, mat_h = static_arrays(haired_glb)
    Fh0 = np.asarray(Fh0, np.int64).reshape(-1, 3)
    Uh = np.asarray(Uh, np.float64)
    Ph, Fh, inv_h = gf.weld(Ph0, Fh0, Uh)
    body_u, body_r = body_arrays(unrigged_glb), body_arrays(rigged_glb)
    if not body_r.joint_names:
        raise ValueError("The rigged base has no skin")
    Pb = np.asarray(body_u.positions, np.float64)
    Fb = np.asarray(body_u.faces, np.int64).reshape(-1, 3)
    k, head_b = _scale(body_u, body_r)
    report: Dict[str, Any] = {"shape": shape, "k_m_per_unit": round(k, 5),
                              "vertices": {"H_original": int(len(Ph0)), "H_welded": int(len(Ph)),
                                           "H_faces": int(len(Fh)), "B": int(len(Pb))}}

    # 1. 2D hair masks
    masks, loose, mask_info = {}, {}, {}
    for view in _VIEW_SIGN:
        v = views[view]
        masks[view], mask_info[view] = hair_mask_2d(v.base_rgb, v.base_mask, v.haired_rgb, v.haired_mask, view)
        loose[view], _ = hair_mask_2d(v.base_rgb, v.base_mask, v.haired_rgb, v.haired_mask, view,
                                      chest_prior=False)
    report["masks"] = mask_info

    # 2. frames + votes in H's own frame; H units -> metres through the framing scale
    frames_h = {view: Frame(Ph, views[view].haired_mask, sign) for view, sign in _VIEW_SIGN.items()}
    front_place = views["front"].base_mask if place_mask is None else np.asarray(place_mask, bool)
    frame_b = Frame(Pb, front_place, 1)
    k_h = k * frame_b.s / frames_h["front"].s
    cell_h, vis_h = CELL_M / k_h, VIS_TOL_M / k_h
    votes = {view: mask_vote(Ph, frames_h[view], masks[view], cell_h, vis_h) for view in _VIEW_SIGN}
    votes_loose = {view: mask_vote(Ph, frames_h[view], loose[view], cell_h, vis_h) for view in _VIEW_SIGN}
    guess = votes["front"] | votes["back"]

    # 3. registration, pass 1: the similarity ICP on what the masks do not call hair
    Q0 = gf.place_by_framing(Ph, Pb, front_place, views["front"].haired_mask)
    Q, treeB, dist_u, icp = register(Q0, Pb, Fb, guess, k)
    voted = guess.copy()            # the mask votes the ICP left out: never a registration sample
    loose_v = (votes_loose["front"] | votes_loose["back"])

    # 4. label (geometry first, ``label_hair``), then pass 2 of the registration without the labelled hair (the
    # hair the masks missed pulled pass 1 outward), then the label again on the re-registered mesh
    adj = gf._adjacency(Fh, len(Ph))
    outer_h = outer_wall(Ph, cell_h, OUTER_TOL_M / k_h)
    margin = gf.SDF_MARGIN_M / k
    ytop0 = float(Q[:, 1].max())
    region = guess | (Q[:, 1] > ytop0 - REGISTER_TOP_M / k)
    lo = np.minimum(Q[region].min(0), Pb.min(0)) - margin
    hi = np.maximum(Q[region].max(0), Pb.max(0)) + margin
    lo[1] = max(lo[1], min(float(Q[region, 1].min()), ytop0 - 0.45 / k) - margin)
    sdf = gf.body_sdf(Pb, Fb, vox=gf.VOX_M / k, bounds=(lo, hi))
    exact = gf.ExactNearSdf(sdf, Pb, Fb, GEO_EXACT_M / k)
    zc_q = float(np.median(Pb[head_b, 2])) if head_b.any() else float(np.median(Q[:, 2]))
    from scipy.spatial import cKDTree
    tree_vb = cKDTree(Pb)
    vn_b = gf.vertex_normals(Pb, Fb)

    def label_pass(Qp, sd_body=None):
        T = gf.similarity(Ph, Qp)
        y_top = float(Qp[:, 1].max())
        zc_hp = float(_apply(gf.similarity(Qp, Ph), np.array([[0.0, y_top, zc_q]]))[0, 2])
        line_p = _hairline(views, masks, frames_h["front"], k_h, lambda P: _apply(T, P), zc_hp)
        head_h = head_b[tree_vb.query(Qp)[1]] if head_b.any() else (Qp[:, 1] > y_top - 0.25 / k)
        sd_p = exact.sample(Qp) * k
        if sd_body is not None:         # off the head: the distance under the body's own registration (pass 1)
            sd_p = np.where(head_h, sd_p, sd_body)
        facing = vn_b[tree_vb.query(Qp)[1], 2]
        labelled = label_hair(Qp, sd_p, adj, outer=outer_h, head=head_h, voted=voted, loose=loose_v,
                              hairline_y=line_p["y"], eye_y=line_p["y_eye"],
                              facing=facing, centre_z=zc_q, k=k, F=Fh)
        return labelled, sd_p, head_h

    lab1, sd1, head1 = label_pass(Q)
    # pass 2: the HEAD only (nearest B vertex Head-weighted), from pass 1 — the hair sits on the head, and one
    # similarity cannot fit head and shoulders of two mesher outputs at once (Kira e2e: head p95 1.44 cm when the
    # top 35 cm are fitted, 0.91 cm when the head is; the head's own scale is stable: Kira 0.936 / 0.937 on two
    # meshes, Kai 0.999 from either start, where the top 35 cm gave 0.945 / 0.963 / 1.037)
    exclude = voted | dilate(lab1["hair"], adj, REREG_DILATE) | ~head1
    Q, treeB, dist_u, icp2 = register(Q, Pb, Fb, exclude, k)
    # the label off the head (long hair on the shoulders: votes + growth over "outside B") keeps pass 1's
    # distances: under the head similarity Kira e2e's neck and chest stood up to 2.6 cm out of B (p95 of the
    # top 35 cm) and the growth took them (a 67 cm² bib in front of the neck)
    labelled, sd_h, head_h = label_pass(Q, sd_body=sd1)
    hair_v = labelled["hair"]
    T_hq = gf.similarity(Ph, Q)
    T_qh = gf.similarity(Q, Ph)

    def to_q(P):
        return _apply(T_hq, P)

    def to_h(P):
        return _apply(T_qh, P)

    ytop = float(Q[:, 1].max())
    # colour reference: H's texture per welded vertex; the skin colour from H's own non-hair head, the hair
    # colour from the label CORE_RINGS inside its border
    tex_h = _rgb_of(img_h)
    hair_lab = skin_lab = None
    cap_uv = None               # the UV of the hair texel nearest the hair colour (the caps of the sheet's holes)
    if tex_h is not None and len(Uh) == len(Ph0) and hair_v.any():
        rgb_v = np.zeros((len(Ph), 3))
        np.add.at(rgb_v, inv_h, sample_texture(tex_h, Uh))
        rgb_v /= np.maximum(np.bincount(inv_h, minlength=len(Ph)), 1)[:, None]
        lab_v = lab(rgb_v)
        face = (~hair_v) & (~voted) & outer_h & (Q[:, 1] > ytop - REGISTER_TOP_M / k) & (sd_h > -DEEP_M)
        skin_lab = np.median(lab_v[face], 0) if face.sum() >= 20 else None
        core = erode(hair_v, adj, CORE_RINGS)
        hair_lab = np.median(lab_v[core if core.any() else hair_v], 0)
        pool = np.nonzero(core if core.any() else hair_v)[0]
        best = pool[np.argmin(np.linalg.norm(lab_v[pool] - hair_lab, axis=1))]
        cap_uv = Uh[np.nonzero(inv_h == best)[0][0]]
    Fhair_w = faces_all(Fh, hair_v)
    report["label"] = {**labelled["report"], "votes": int(voted.sum()), "outer": int(outer_h.sum()),
                       "vertices": int(hair_v.sum()), "faces": int(len(Fhair_w)),
                       "pass1_vertices": int(lab1["hair"].sum()),
                       "thickness_p50_cm": round(float(np.median(sd_h[hair_v])) * 100, 2) if hair_v.any() else None}
    icp = {**icp2, "pass1_used": icp["used"]}

    # registration numbers (the outer wall's non-hair top; H's inner wall has no counterpart on B): neither labelled
    # nor voted hair — a voted vertex the label left out (a loose strand end, the hair edge) is still hair, not a
    # misregistered head (Kira: p95 1.31 cm with them, 0.7 cm without, as the spike's K1)
    dist_m = dist_u * k
    top = (~hair_v) & (~voted) & outer_h & (Q[:, 1] > ytop - REGISTER_TOP_M / k)
    upper = top & head_h          # the gate: the head the hair sits on (the shoulders are reported, not gated)
    reg_p95 = float(np.percentile(dist_m[upper], 95)) * 100 if upper.any() else float("nan")
    report["registration"] = {**icp, "region": "head",
                              "outer_nonhair_p50_cm": round(float(np.percentile(dist_m[upper], 50)) * 100, 3)
                              if upper.any() else None,
                              "outer_nonhair_p95_cm": _finite(reg_p95, 3), "n": int(upper.sum()),
                              "top_p95_cm": round(float(np.percentile(dist_m[top], 95)) * 100, 3)
                              if top.any() else None,
                              "scale_h_to_b": round(float(T_hq[0]), 5)}

    # hairline: 2D (front centre strip, mapped into B's frame) vs the 3D label
    zc_q = float(np.median(Pb[head_b, 2])) if head_b.any() else float(np.median(Q[:, 2]))
    zc_h = float(to_h(np.array([[0.0, ytop, zc_q]]))[0, 2])
    line = _hairline(views, masks, frames_h["front"], k_h, to_q, zc_h)
    hair_q = Q[hair_v]
    strip = ((np.abs(hair_q[:, 0] - line["x"]) * k < CENTRE_BAND_M) & (hair_q[:, 2] > zc_q)
             & (hair_q[:, 1] > line["y_eye"]))
    y3d = float(hair_q[strip, 1].min()) if strip.any() else float("nan")
    hairline_cm = abs(y3d - line["y"]) * k * 100 if line["y"] is not None and strip.any() else float("nan")
    report["hairline"] = {"row_2d": line["row"], "eye_row": line["eye_row"],
                          "y_2d_m": None if line["y"] is None else round(line["y"] * k, 4),
                          "y_3d_m": None if not strip.any() else round(y3d * k, 4), "n_strip": int(strip.sum()),
                          "delta_cm": None if not math.isfinite(hairline_cm) else round(hairline_cm, 2)}

    # 5. build: the hair faces of the ORIGINAL H (UV seams kept), the topology from the welded one
    def hair_faces():
        Fo_ = Fh0[hair_v[inv_h[Fh0]].all(1)]
        Fw_ = inv_h[Fo_]
        return Fo_[(Fw_[:, 0] != Fw_[:, 1]) & (Fw_[:, 1] != Fw_[:, 2]) & (Fw_[:, 0] != Fw_[:, 2])]

    Fo = hair_faces()
    # a hole in the hair SHEET shorter than CAP_LOOP_MAX_M is capped: a fan from the loop's centroid. Its inside is
    # a groove between strands that the outer-wall test leaves out and that runs on under the hair to the rest of
    # H, so no vertex island explains it (Kira e2e: loops of 1.6-21 cm over the back, the larger ones showed the
    # back through the hair; adding the groove's vertices instead grew a 4 cm one to 12 cm). The cap has its own
    # copies of the loop vertices, all on ONE hair texel (``cap_uv``): the loop's own UVs jump across texture
    # islands and painted skin streaks over the cap
    caps_done = []
    for _round in range(CAP_ROUNDS):          # loops that touch at a vertex come out as one; a second round
        caps = small_loops(inv_h[Fo], Q * k, CAP_LOOP_MAX_M) if len(Fo) else []
        if not caps:
            break
        rep = np.full(len(Q), -1, np.int64)
        rep[inv_h] = np.arange(len(inv_h))
        new_faces = []
        for edges, verts, _per in caps:
            uv = cap_uv if cap_uv is not None else Uh[rep[verts[0]]]
            own = np.full(len(Q) + 1, -1, np.int64)
            own[verts] = len(Ph0) + np.arange(len(verts))       # the cap's copies of the loop vertices
            n0, nw = len(Ph0) + len(verts), len(Q)
            Ph0 = np.vstack([Ph0, Ph0[rep[verts]], Ph0[rep[verts[:1]]]])
            Uh = np.vstack([Uh, np.repeat(np.asarray(uv)[None, :], len(verts) + 1, 0)])
            inv_h = np.concatenate([inv_h, verts, [nw]])
            Q = np.vstack([Q, Q[verts].mean(0)])
            hair_v = np.append(hair_v, True)
            new_faces.append(np.stack([own[edges[:, 1]], own[edges[:, 0]], np.full(len(edges), n0)], 1))
        Fh0 = np.vstack([Fh0] + new_faces)
        Fo = hair_faces()
        caps_done += caps
    caps = caps_done
    report["edge_caps"] = {"capped": len(caps), "perimeters_cm": sorted(round(p * 100, 1) for _e, _v, p in caps)}
    if len(Fo) == 0:
        metrics = {"registration_p95_cm": _finite(reg_p95, 3), "hairline_cm": None, "label_holes": 0,
                   "hair_area_cm2": 0.0}
        ok, reasons = gf.gate(metrics, CUT_GATES)
        clear, spread = fit_params(shape)
        report["seconds"] = round(time.monotonic() - started, 2)
        return CutResult(b"", False, reasons or ["no hair found on the haired mesh"], metrics, shape, clear,
                         spread, report)
    used = np.unique(Fo)
    remap = np.full(len(Ph0), -1, np.int64)
    remap[used] = np.arange(len(used))
    F_out = remap[Fo]
    w_of = inv_h[used]                                   # welded vertex of every patch vertex
    wu, w_local = np.unique(w_of, return_inverse=True)   # the patch's welded vertices
    Fw = w_local[F_out]                                  # patch faces on welded indices
    Pw_q = Q[wu]
    B_edges = boundary_edges(Fw)
    ring0 = np.zeros(len(wu), bool)
    ring0[B_edges.ravel()] = True
    adj_w = gf._adjacency(Fw, len(wu))
    ring1 = dilate(ring0, adj_w, 1) & ~ring0
    hair_area_cm2 = float(gf.triangle_areas(Pw_q * k, Fw).sum()) * 1e4
    loops = boundary_loops(Fw, Pw_q * k)
    holes = [per for _v, per in loops if per < HOLE_LOOP_MAX_M]
    report["edge"] = {"loops": len(loops), "perimeters_cm": sorted(round(p * 100, 1) for _v, p in loops)[:12],
                      "holes": len(holes), "ring0": int(ring0.sum()), "ring1": int(ring1.sum())}

    surface = gf.BodySurface(Pb, Fb[gf.outer_faces(Pb, Fb, sdf)])   # never onto an inner wall
    snap, normal, d_m = _snap_offsets(Pw_q, surface, k)
    if shape == "cut":
        sd_outer = sdf.sample(Pw_q) * k
        offset = np.clip(sd_outer - INNER_GAP_M, 0.0005, INNER_OFFSET_M)
        near = d_m < SNAP_MAX_M
        toward = gf._unit(snap - Pw_q)
        inner = np.where(near[:, None], snap + normal * (offset / k)[:, None], Pw_q + toward * (FREE_INNER_M / k))
        inner = smooth_edge(inner, B_edges, EDGE_SMOOTH_PASSES)
        outer = Pw_q.copy()
        # ring 0: the sheets meet (on the inner sheet near the scalp, on the outer one at a free strand's end)
        meet = np.where(near[:, None], inner, smooth_edge(outer, B_edges, EDGE_SMOOTH_PASSES))
        inner[ring0] = meet[ring0]
        outer[ring0] = meet[ring0]
        f1 = FEATHER[1]
        r1 = ring1 & near
        outer[r1] = inner[r1] + f1 * (outer[r1] - inner[r1])
        uv_out = Uh[used]
        image, mime, material = img_h, mime_h, mat_h
        report["cut"] = {"snapped_share": round(float(near.mean()), 3),
                         "inner_offset_p50_mm": round(float(np.median(offset[near])) * 1000, 2) if near.any() else None}
        if tex_h is not None and hair_lab is not None:
            cover = _raster(uv_out[F_out], tex_h.shape[:2])
            mended, report["colour"] = recolour_texture(tex_h, cover, hair_lab, skin_lab)
            if report["colour"]["recoloured_texels"]:
                image, mime = _png(mended), "image/png"
    else:
        base_pts, n_out = _relax_on_surface(snap, Fw, surface, SHELL_RELAX_PASSES)
        outer = base_pts + n_out * (thickness_m / k)
        inner = base_pts + n_out * (SHELL_INNER_M / k)
        inner = smooth_edge(inner, B_edges, EDGE_SMOOTH_PASSES)
        # the smoothed rim cuts chords through the curved scalp (Kai: down to 2.95 mm inside): back onto it
        seat, seat_n = surface.closest(inner[ring0])
        inner[ring0] = seat + seat_n * (SHELL_INNER_M / k)
        outer[ring0] = inner[ring0]
        f1 = FEATHER[1]
        outer[ring1] = inner[ring1] + f1 * (outer[ring1] - inner[ring1])
        on = surface.closest(np.concatenate([outer, inner]))[0]
        gap_mm = np.linalg.norm(np.concatenate([outer, inner]) - on, axis=1) * k * 1000
        rim_mm = gap_mm[np.concatenate([ring0, ring0])]
        report["shell_rim"] = {"rim_p50_mm": round(float(np.median(rim_mm)), 2) if len(rim_mm) else None,
                               "rim_max_mm": round(float(rim_mm.max()), 2) if len(rim_mm) else None,
                               "max_mm": round(float(gap_mm.max()), 2)}
        head_pts = Pb[head_b] if head_b.any() else Pb[Pb[:, 1] > ytop - 0.15 / k]
        centre = np.array([float(np.median(head_pts[:, 0])), float(head_pts[:, 1].mean()),
                           float(np.median(head_pts[:, 2]))])
        R_inv = T_qh[1]
        uv_w, image, tex_info = _bake_shell_texture(outer, centre, to_h, R_inv, frames_h, views, masks)
        uv_out = uv_w[w_local]
        # the baked colour comes from the haired views: a parting or a temple shows the skin there, which on a
        # shell reads as a bald speck — every skin-like or white texel is painted over (the shell IS the hair)
        baked = _rgb_of(image)
        skin_view = _view_skin_lab(views["front"], masks["front"])
        if baked is not None:
            cover = _raster(uv_out[F_out], baked.shape[:2])
            if cover.any():
                hair_baked = np.median(lab(baked[cover]), 0)
                mended, report["colour"] = recolour_texture(baked, cover, hair_baked, skin_view)
                if report["colour"]["recoloured_texels"]:
                    image = _png(mended)
        mime, material = "image/png", {"name": "hair_shell", "doubleSided": True,
                                       "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.8}}
        report["shell"] = {"thickness_mm": round(thickness_m * 1000, 2),
                           "snap_p50_cm": round(float(np.median(d_m)) * 100, 2),
                           "snap_p90_cm": round(float(np.percentile(d_m, 90)) * 100, 2), "texture": tex_info}
    # per patch vertex (original indexing) -> both sheets; the inner sheet's winding flipped
    P_out = np.concatenate([outer[w_local], inner[w_local]])
    U_out = np.concatenate([uv_out, uv_out])
    F_all = np.concatenate([F_out, F_out[:, ::-1] + len(used)])
    # closure: on the welded result every edge is used by exactly two faces
    Pc, Fc, _ = gf.weld(P_out, F_all, U_out)
    labels, shares = gf.components(Pc, Fc)
    open_edges = int(len(boundary_edges(Fc)))
    report["closed"] = {"open_edges": open_edges, "components": int(len(shares)),
                        "largest_share": round(float(shares.max()) if len(shares) else 0.0, 4),
                        "vertices": int(len(Pc)), "faces": int(len(Fc))}

    metrics = {"registration_p95_cm": _finite(reg_p95, 3), "hairline_cm": _finite(hairline_cm, 2),
               "label_holes": len(holes), "hair_area_cm2": round(hair_area_cm2, 1)}
    ok, reasons = gf.gate(metrics, CUT_GATES)
    glb = static_glb(P_out, F_all, U_out, image=image, mime=mime, material=material, name="hair_subtract")
    clear, spread = fit_params(shape)
    report["seconds"] = round(time.monotonic() - started, 2)
    logger.info("Hair cut (%s): %s — registration p95 %.2f cm, hairline %s cm, holes %d, area %.0f cm², %.1f s",
                shape, "ok" if ok else "refused " + "; ".join(reasons), reg_p95, metrics["hairline_cm"],
                len(holes), hair_area_cm2, report["seconds"])
    return CutResult(glb, ok, reasons, metrics, shape, clear, spread, report)
