"""Insole and heel analysis of a shoe mesh, pure numpy (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 5, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.4).

A port of the spike's ``bl_shoe_rays.py`` + ``insole.py`` (``~/claude-out/shoe-spike/src``) without
Blender:

- **Frame** (``shoe_frame``): up = the mesher's +Y, x = the principal axis of the footprint, the
  provisional heel = the end whose rear ``HEEL_END_SHARE`` stands taller. After tracking, the frame is
  flipped when the insole at 0.10 L is lower than at 0.90 L — toe and heel come from the insole height.
- **Vertical rays** (``vertical_hits``) on ``STATIONS`` stations x the lateral columns: every triangle's
  xz bounding box is binned into the station grid and each (triangle, ray) pair is tested with the 2D
  barycentric point-in-triangle test (vertical rays need no Möller–Trumbore); the height is the
  barycentric interpolation, ``normal_up`` the face normal's up component. Hits closer than 1e-5 L in
  one column are one hit (the spike's BVH restarted its ray 1e-5 L above the last hit).
- **Tracking** (the spike's ``insole.py`` verbatim): a candidate is an up-facing hit (``normal_up >
  0.3``) with at least ``AIR_SHARE`` L of air above it or nothing above; seeded at 0.55 of the stations
  (the lowest candidate), followed both ways with the slope-extrapolated prediction within ``TOL_SHARE``
  L; a second pass gives each lost cell the candidate nearest its station's median within 2 TOL.
  Profile = the median over the middle 50 % of a station's insole columns.
- **Topline** per station (tessellation-independent): every triangle edge is cut by the station plane;
  per lateral side the highest cut point with |z| >= ``TOPLINE_SIDE_SHARE`` x that side's max |z| at
  the station; the topline is the lower of the two sides. ("The station's max |z|" is read per side,
  so an asymmetric cross-section does not drop the narrower side.)
- **Nominal numbers**: per-item numbers need a size, so they are given at ``NOMINAL_LENGTH_M``
  (k = NOMINAL_LENGTH_M / length_raw); the fit recomputes them at the real scale. Heel seat = the
  profile ``HEEL_SEAT_M`` (nominal) from the heel end; ball = the profile at ``BALL_SHARE`` L; pitch =
  atan2(profile(``PITCH_HEEL_SHARE`` L) - profile(``BALL_SHARE`` L), (BALL - PITCH_HEEL) L); shank
  slope = the median station slope between the heel seat and the ball (negative: falling to the toe).
- **Outsole footprint** (``footprint_ground``, INSOLE_VERSION 2 — boots spec
  ``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md`` § 6.1): the footprint columns whose
  LOWEST hit is a sole underside — its face normal's up component <= ``DOWN_MAX`` (``UP_MIN`` mirrored).
  It is the denominator of ``insole_cover`` (the insole cells counted are the ones within it, so the share
  stays <= 1) and the polygon of ``footprint_outline`` (what the cut hides under the shoe);
  ``footprint_ground`` in insole.json is its share of every column with a hit. A flared shaft adds columns
  whose lowest hit is the leaning wall — neither insole nor underside (spec § 5 F5: a synthetic knee boot
  read 0.891 under the round-1 rule, a perfectly closed shoe pushed towards the 0.80 refusal, and the cut
  polygon widened to the flare). The spec's first wording — "within ``GROUND_SHARE`` L of the ground" — was
  measured on the Business Heels (``item_68c4d249/df44e2fa4177``, 2026-11-11) and rejected: a pump's waist
  hangs above the ground and its toe springs 2.7 % L up, so only 31.7 % of its columns stand on the ground
  and the outline lost the toe box (x 0.92 … 1.00 L) — the cut would have stopped hiding the toes. Facing
  keeps 93.1 % of the heels' columns, x 0.013 … 0.996 L (the round-1 footprint ran 0.004 … 1.0 L), the ball
  station's width unchanged and the median station 2.1 mm (one rim column of rounded sole edge) narrower;
  ``insole_cover`` 0.890 -> 0.929. Every synthetic shoe (pump, clog, sandal, shaft) reads 1.0.
- **Shaft block** (``shaft``, INSOLE_VERSION 3 — boots spec § 6.1), measured in the shoe frame:
  ``collar_h_raw`` = the highest topline over the stations behind the THROAT (the first roofed station in the
  front half, ``footwear_cut``'s rule; every station without one) minus the insole at the HEEL SEAT. The
  spec's first wording, a per-station "wall top − insole profile", was dropped on the pump-shaped boot of the
  smoke fixtures: under a flat-topped shaft the insole falls from the heel seat to the ball, so the per-station
  difference at the shaft's front reads the shaft PLUS the heel rise (0.109 instead of 0.07 on a 16-cm shaft,
  one class up); the spec's own example — the pump's 13.1 − 9.1 cm, its counter above its heel seat — is the
  heel-seat reading. ``collar_h_nominal`` = ``collar_h_raw`` × k; ``class`` from the 7-decimal nominal value
  insole.json stores (``SHAFT_CLASS_M``: ``none`` ≤ 0.07, ``ankle`` ≤ 0.22, ``knee`` ≤ 0.48, else
  ``overknee`` — refused, ``OVERKNEE_REFUSED``, gate ``overknee``). The class is a label (Wardrobe, model
  overview); the fit treats every shaft alike.
  **Tube slabs**: horizontal planes every ``SHAFT_SLAB_SHARE`` L from the mesh's top down to max(the vamp
  roof's highest point in front of the throat, heel seat + ``SHAFT_CLASS_M["none"]`` / k) — the height a shaft
  begins to be one; a shoe whose walls stay under it has no slabs and its ``closed_share`` is ``None`` (not
  gated). The ceiling is the mesh's highest point, not the topline: the topline is the LOWER side and a shaft
  with one wall missing would otherwise not be looked at. Per slab the ring of edge-cut points: ``x_min`` /
  ``x_max`` / ``z_min`` / ``z_max``, ``gap_deg`` = the largest angular gap between neighbouring cut points about
  the ring's bbox centre (``None`` for a plane that cuts nothing), and ``closed`` (INSOLE_VERSION 4, P2 Ruling 8c)
  = cut points in all four quadrants about that centre (strict) AND ``gap_deg`` < ``RING_GAP_MAX_DEG`` (90°: a
  tube's neighbours sit a few degrees apart, a U or an arc leaves the opening as one gap) AND both bbox ranges
  ≥ ``RING_EXTENT_MIN_SHARE`` L (a pull tab's own loop is a closed ring 1.5 cm across — not the shaft). The
  version-3 test was the quadrants alone; on the P2 material it read the Work Shoes' tongue (gap 114–154°) and
  the Leather Boots' pull tab (1.2 × 1.5 cm) as the shaft top, 2.1 / 1.6 cm above the collar. ``top_raw`` = the
  highest closed slab (``None`` without one), ``closed_share`` = closed slabs / slabs at or below it (0.0 without
  one) — gate ``shaft_closed_share`` ≥ 0.9, refusal ``SHAFT_OPEN_REFUSED`` (an open-sided shaft is a mesher hole).
  **Cap**: a single-view mesher closes an opening it cannot see; the faces whose centroid lies within the top
  ``CAP_TOP_SHARE`` of the shaft height — from ``top_raw − CAP_TOP_SHARE × (top_raw − vamp_top_raw)`` up,
  nothing of a shaft lies above its top but a cap — whose normal's up component is ≥ ``CAP_UP_MIN`` (cos 30°)
  AND whose centroid lies INSIDE the opening (INSOLE_VERSION 5, P2 carry to Task 9) are the cap: ``cap_removed``
  counts them, ``strip_cap`` takes them out of the arrays and the insole step rewrites ``prepared.glb`` without
  them (``footwear_source._step_insole``); the shaft's material is marked double-sided at the fit. The opening
  is the ring the plane at the cap band's floor cuts out of the mesh (``_ring_cut``), reduced to its INNER loop —
  per ``CAP_RING_BINS`` angular bin about the ring's bbox centre the cut point of smallest radius — and read as a
  polygon (even-odd test on the centroid's (x, z)). The height-band rule alone (version 3 / 4) ate the collar
  RIM of a real mesh: a mesh has a wall thickness, its rounded rim's top faces are up-facing and inside the band
  (161 of 161 faces on the P2 Work Shoes, 10 cm²; 142 on the Leather Boots) and were stripped with the disc; the
  rim's faces lie BETWEEN the inner and the outer wall surface, i.e. outside the inner loop, and stay now. A
  tongue or pull tab standing above the collar inside the opening still counts as a cap where it faces up.
  Without a ring at the floor (fewer than 3 cut points) nothing is a cap.
- **Type gates** (``INSOLE_GATES``): ``insole_cover`` = insole cells within the outsole footprint / its
  cells (refusal ``INSOLE_REFUSED``); ``vamp_cover`` = the share of footprint cells at x >= ``BALL_SHARE`` L whose
  column has a hit above the insole (refusal ``OPEN_REFUSED``); ``opening_share`` = the share of
  profile stations whose topline stands at least ``AIR_SHARE`` L above the insole — a solid mesh (its
  top surface read as the insole, no side walls above it) has none (refusal ``SOLID_REFUSED``, judged
  before ``vamp_cover`` so a solid shoe never gets the sandal message). ``boot`` (``BOOT_MARGIN_M`` above the
  ankle, ``BOOT_REFUSED``) needs a body and is judged at the fit.
- ``cavity_end_x``: the first roofed station in front of the ball whose insole-to-roof gap is below
  ``CAVITY_MIN_M`` (nominal), else the last insole station — where the insole arc for the scale ends.
- ``contacts`` (frame coordinates, on the sole): ``heel_tip`` = the centroid of the ground cells within
  ``CONTACT_BAND_SHARE`` L of the rearmost ground cell (the top-lift of a heel), ``ball`` = the ground
  cells within that band around ``BALL_SHARE`` L, ``toe_tip`` = the front-most footprint station.

Every length in ``insole.json`` is raw (mesh units) except ``nominal``; ``overlay`` is in the prepared
mesh's own coordinates.

Calibration: the spike's Black Stilettos (Blender rays) — insole cover 0.92, heel seat 9.3 cm (at the
fitted foot's heel point), heel rise 8.0 cm, insole ball 1.3 cm, foot-chord pitch 35.3 / 32.5 deg. This
port on the spike's raw mesh (93k tris, 0.4 s): profile within 0.6 mm of the Blender profile, insole
cover 0.918, nominal heel seat 9.62 cm, ball 1.37 cm, heel rise 8.25 cm, pitch 33.84 deg (the spike's
own profile gives 33.81 / 9.63 by these definitions), shank -35.7 deg, vamp cover 0.613, cavity end
0.222 m (spike 0.217 with the foot's 1.63 cm toes), shaft (max lower topline) 14.0 cm, opening share 0.915.

Boots round P2 (2026-11-11, the clone, UniForge3D-Multiview meshes of Qwen side-view edits of two 3/4-view item
images; nominal values at 26 cm): **Leather Boots** (``item_946db709``, a Chelsea ankle boot) — insole cover 0.932,
vamp 0.970, opening 0.996, pitch 14.6 deg, heel seat 3.58 cm, rise 3.37 cm; shaft ``ankle``, collar 13.97 cm,
``top_raw`` 19.11 cm, closed share 1.0 (26 of 27 slabs), cap 46 faces. **Work Shoes** (``item_fede24fa``, a laced
work boot) — insole cover 0.941, vamp 0.836, opening 0.954, pitch 5.4 deg, heel seat 3.54 cm, rise 1.23 cm; shaft
``ankle``, collar 10.28 cm, ``top_raw`` 15.87 cm, closed share 1.0 (21 of 22), cap 6 faces. Both pass, but the
four-quadrant ``closed`` test reads non-tube rings as closed on both (the cut points' largest angular gap about the
bbox centre, measured per slab): on the Work Shoes the 8 top "closed" slabs (14.05–15.87 cm) are the TONGUE above
the padded collar — a U open at the back, largest gap 114–154 deg, extent 0.7–6.8 cm × 2.0–6.2 cm against the
tube's 11 × 7 cm below, where the gap is 4.6–10.7 deg; on the Leather Boots the 4 top ones (18.33–19.11 cm) are
the PULL TAB's own small loop (1.2–1.4 × 1.5 cm, gap 54–72 deg) and two at the collar edge read 132 / 135 deg.
So ``top_raw`` sat on the tongue / the tab, 2.1 / 1.6 cm above the real collar ring (13.79 / 17.55 cm), and the
cap band was measured from there. INSOLE_VERSION 4 (the gap and extent rules above) puts ``top_raw`` on the collar
of both (fix-1 report: the numbers on the stored meshes are in the Task 8 fix-1 report of the SDD folder).
"""
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.footwear_gates import check_gates

#: Bumped when the analysis changes what it measures (part of the footwear fsig).
#: 2: insole_cover and footprint_outline over the outsole footprint (footprint_ground);
#: 3: the shaft block (collar height, class, tube slabs, closed share, cap removal);
#: 4: a closed slab ring needs a largest angular gap < 90° and an extent ≥ 0.1 L (tongue / pull tab are no shaft);
#: 5: a cap face lies inside the opening's inner loop (the collar rim of a real mesh is no cap).
INSOLE_VERSION = 5

#: Shoe length the per-item (nominal) numbers are given at.
NOMINAL_LENGTH_M = 0.26
#: Stations along the length (the lateral column count follows the aspect).
STATIONS = 240
#: Air above an up-facing hit that makes it an insole candidate, as a share of the length.
AIR_SHARE = 0.025
#: Tracking tolerance against the slope-extrapolated height, as a share of the length.
TOL_SHARE = 0.035
#: Up component of a hit's face normal above which it faces up.
UP_MIN = 0.3
#: Station (share of the count) where the tracking is seeded: the open forepart.
SEED_SHARE = 0.55
#: Recorded hits per ray.
MAX_HITS = 12
#: Share of the length at each end whose height decides the provisional heel.
HEEL_END_SHARE = 0.15
#: Topline: cut points per side with |z| >= this share of the side's max |z| at the station.
TOPLINE_SIDE_SHARE = 0.75
#: Heel seat: the insole this far (nominal metres) from the heel end.
HEEL_SEAT_M = 0.04
#: The ball station, as a share of the length.
BALL_SHARE = 0.62
#: The heel point of the pitch chord, as a share of the length.
PITCH_HEEL_SHARE = 0.10
#: Insole-to-roof gap (nominal metres) below which the toe box is too low for the toes.
CAVITY_MIN_M = 0.015
#: A lowest hit within this share of the length above the ground stands on the ground (the contacts).
GROUND_SHARE = 0.01
#: A column's lowest hit with a face normal up component at or below this is a sole underside: the column
#: belongs to the outsole footprint (``footprint_ground``). ``UP_MIN`` mirrored.
DOWN_MAX = -0.3
#: Contact bands (heel tip, ball) as a share of the length.
CONTACT_BAND_SHARE = 0.05

INSOLE_GATES: Dict[str, Tuple[str, Any, str]] = {
    "insole_cover": ("min", 0.80, "share of the footprint with a tracked insole"),
    "vamp_cover": ("min", 0.6, "share of the forefoot footprint under a vamp"),
    "opening_share": ("min", 0.5, "share of the insole stations whose side walls rise above the insole"),
}
#: Shaft class by the nominal collar height (metres above the heel seat at NOMINAL_LENGTH_M): a class's upper
#: bound, inclusive; above the last one the shaft is over-knee (boots spec § 6.1).
SHAFT_CLASS_M: Dict[str, float] = {"none": 0.07, "ankle": 0.22, "knee": 0.48}
#: Tube slabs every this share of the length (module docstring).
SHAFT_SLAB_SHARE = 0.01
#: A closed slab ring: largest angular gap between neighbouring cut points about the bbox centre below this, and
#: both bbox ranges at least this share of the length (module docstring, INSOLE_VERSION 4).
RING_GAP_MAX_DEG = 90.0
RING_EXTENT_MIN_SHARE = 0.10
#: The cap band: the top share of the shaft height (top_raw − vamp top) and the up component of a cap face.
CAP_TOP_SHARE = 0.02
CAP_UP_MIN = math.cos(math.radians(30.0))
#: The opening's inner loop: angular bins about the ring's bbox centre, the nearest cut point per bin (3°).
CAP_RING_BINS = 120
#: The shaft gates, judged with INSOLE_GATES at the insole step; both are optional for a shoe without a shaft.
SHAFT_GATES: Dict[str, Tuple[str, Any, str]] = {
    "shaft_closed_share": ("min", 0.9, "share of the shaft's tube slabs with a closed ring"),
    "overknee": ("max", SHAFT_CLASS_M["knee"], "nominal collar height above the heel seat (m)"),
}
#: The boot gate (judged at the fit): a topline above the ankle joint + this margin.
BOOT_MARGIN_M = 0.03
BOOT_REFUSED = "Boots are not supported yet"
OPEN_REFUSED = "Open shoes and sandals are not supported yet"
INSOLE_REFUSED = "No insole found in the shoe mesh"
SOLID_REFUSED = "Solid mesh: no shoe opening found"
OVERKNEE_REFUSED = "Over-knee boots are not supported yet"
SHAFT_OPEN_REFUSED = "The boot shaft is not closed"


@dataclass
class ShoeFrame:
    """The shoe's own frame in the mesh's coordinates.

    ``origin`` sits at the heel end on the ground (the lowest point), centred
    across the footprint; ``x_axis`` runs heel -> toe, ``up`` is the mesher's
    +Y, ``z_axis`` = ``x_axis`` x ``up``; ``length`` is the extent along
    ``x_axis`` in mesh units.
    """
    origin: np.ndarray
    x_axis: np.ndarray
    up: np.ndarray
    z_axis: np.ndarray
    length: float

    def to_frame(self, positions: np.ndarray) -> np.ndarray:
        """``(N, 3)`` frame coordinates ``(x, height, z)`` of ``positions``."""
        basis = np.stack([self.x_axis, self.up, self.z_axis])
        return (np.asarray(positions, np.float64).reshape(-1, 3) - self.origin) @ basis.T

    def to_mesh(self, points: np.ndarray) -> np.ndarray:
        """``(N, 3)`` mesh coordinates of frame points ``(x, height, z)``."""
        basis = np.stack([self.x_axis, self.up, self.z_axis])
        return np.asarray(points, np.float64).reshape(-1, 3) @ basis + self.origin

    def flipped(self) -> "ShoeFrame":
        """The same frame seen from the other end: the heel becomes the toe
        (x and z negated, the origin moved ``length`` along x)."""
        return ShoeFrame(origin=self.origin + self.length * self.x_axis, x_axis=-self.x_axis, up=self.up,
                         z_axis=-self.z_axis, length=self.length)


def shoe_frame(positions: np.ndarray, faces: np.ndarray) -> ShoeFrame:
    """The frame of a shoe mesh: up = +Y, x = the principal axis of the
    footprint (the surface's area second moments on the XZ plane), the
    provisional heel = the end whose rear ``HEEL_END_SHARE`` of the length
    stands taller (a tie keeps the PCA direction, sign-normalised so its
    largest component is positive). Only vertices used by a face count.
    """
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if len(F) == 0:
        raise ValueError("a shoe frame needs at least one triangle")
    used = P[np.unique(F)]
    up = np.array([0.0, 1.0, 0.0])

    # Exact second moments of the surface spread uniformly over the triangles,
    # projected on XZ (per triangle E[x x^T] = (sum v v^T + s s^T) / 12 with
    # s = the vertex sum): unlike centroids, independent of the tessellation.
    tri = P[F][:, :, [0, 2]]
    area = 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
    if area.sum() <= 0:
        raise ValueError("a shoe frame needs a mesh with area")
    s = tri.sum(axis=1)
    second = (np.einsum("tvi,tvj->tij", tri, tri) + np.einsum("ti,tj->tij", s, s)) / 12.0
    mean = (area[:, None] * s / 3.0).sum(0) / area.sum()
    cov = (area[:, None, None] * second).sum(0) / area.sum() - np.outer(mean, mean)
    _, vecs = np.linalg.eigh(cov)
    axis2 = vecs[:, -1]
    if axis2[np.argmax(np.abs(axis2))] < 0:
        axis2 = -axis2
    x_axis = np.array([axis2[0], 0.0, axis2[1]])

    t = used @ x_axis
    t0, t1 = float(t.min()), float(t.max())
    length = t1 - t0
    band = HEEL_END_SHARE * length
    h = used[:, 1]
    low_end = float(h[t <= t0 + band].max())
    high_end = float(h[t >= t1 - band].max())
    if high_end > low_end:
        x_axis = -x_axis
        t = -t
        t0 = float(t.min())
    z_axis = np.cross(x_axis, up)
    zs = used @ z_axis
    z_mid = 0.5 * (float(zs.min()) + float(zs.max()))
    origin = t0 * x_axis + float(h.min()) * up + z_mid * z_axis
    return ShoeFrame(origin=origin, x_axis=x_axis, up=up, z_axis=z_axis, length=float(length))


# --- rays -------------------------------------------------------------------------------------------------------------

#: (triangle, ray) pairs tested per vectorised batch (bounds the memory of large triangles).
_PAIR_BATCH = 2_000_000
#: A ray within this share of the grid span OUTSIDE a triangle's edge still hits it (``vertical_hits``).
EDGE_EPS_SHARE = 1e-6


def vertical_hits(p_frame: np.ndarray, faces: np.ndarray, gx: np.ndarray, gz: np.ndarray,
                  max_hits: int = MAX_HITS) -> np.ndarray:
    """Every hit of the vertical rays at ``(gx[i], gz[j])`` (frame coordinates ``(x, height, z)``) ->
    ``(nx, nz, max_hits, 2)`` = ``(height, normal_up)`` sorted by height, NaN where there is none.

    Each triangle's xz bounding box is binned into the station grid; every (triangle, ray) pair in it
    gets the 2D point-in-triangle test, inclusive by ``EDGE_EPS_SHARE`` x the grid span measured as a
    DISTANCE to each edge (barycentric weight x 2 area / edge length), the height by barycentric
    interpolation, ``normal_up`` = the unit face normal's up component. The outermost lateral columns
    lie exactly on the footprint's extreme vertices, so a ray on an edge must hit whatever rounding the
    coordinates went through (float32 GLB accessors, the 7-digit grid in ``insole.json``). Triangles
    without xz area (vertical faces) have no hit. Hits within 1e-5 x the grid span of the previous one
    in the same column (a ray through a shared edge) count once."""
    P = np.asarray(p_frame, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    gx = np.asarray(gx, np.float64)
    gz = np.asarray(gz, np.float64)
    nx, nz = len(gx), len(gz)
    out = np.full((nx, nz, max_hits, 2), np.nan)
    if not len(F) or not nx or not nz:
        return out
    span = max(float(gx[-1] - gx[0]), float(gz[-1] - gz[0]), float(np.ptp(P[:, [0, 2]])), 1e-12)
    a, b, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    det = (b[:, 0] - a[:, 0]) * (c[:, 2] - a[:, 2]) - (c[:, 0] - a[:, 0]) * (b[:, 2] - a[:, 2])
    keep = np.abs(det) > 1e-14 * span * span
    a, b, c, det = a[keep], b[keep], c[keep], det[keep]
    n = np.cross(b - a, c - a)
    norm = np.linalg.norm(n, axis=1)
    nu = n[:, 1] / np.where(norm > 0, norm, 1.0)
    tri = np.stack([a, b, c], axis=1)
    tol = EDGE_EPS_SHARE * span
    # xz edge lengths opposite a, b, c: weight w_k x |det| / len_k = the distance to that edge
    lens = np.stack([np.hypot(c[:, 0] - b[:, 0], c[:, 2] - b[:, 2]), np.hypot(a[:, 0] - c[:, 0], a[:, 2] - c[:, 2]),
                     np.hypot(b[:, 0] - a[:, 0], b[:, 2] - a[:, 2])], axis=1)
    reach = tol * lens / np.abs(det)[:, None]
    i0 = np.searchsorted(gx, tri[:, :, 0].min(1) - tol, "left")
    i1 = np.searchsorted(gx, tri[:, :, 0].max(1) + tol, "right")
    j0 = np.searchsorted(gz, tri[:, :, 2].min(1) - tol, "left")
    j1 = np.searchsorted(gz, tri[:, :, 2].max(1) + tol, "right")
    ni, nj = np.maximum(i1 - i0, 0), np.maximum(j1 - j0, 0)
    count = ni * nj
    cells: List[np.ndarray] = []
    heights: List[np.ndarray] = []
    normals: List[np.ndarray] = []
    ends = np.cumsum(count)
    start = 0
    while start < len(count):
        base = ends[start - 1] if start else 0
        stop = int(np.searchsorted(ends, base + _PAIR_BATCH, "right"))
        stop = max(stop, start + 1)
        sel = np.arange(start, stop)
        cnt = count[sel]
        total = int(cnt.sum())
        start = stop
        if not total:
            continue
        t = np.repeat(sel, cnt)
        local = np.arange(total) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        ii = i0[t] + local // nj[t]
        jj = j0[t] + local % nj[t]
        px, pz = gx[ii], gz[jj]
        ax, az = a[t, 0], a[t, 2]
        w1 = ((px - ax) * (c[t, 2] - az) - (c[t, 0] - ax) * (pz - az)) / det[t]
        w2 = ((b[t, 0] - ax) * (pz - az) - (px - ax) * (b[t, 2] - az)) / det[t]
        w0 = 1.0 - w1 - w2
        r = reach[t]
        inside = (w0 >= -r[:, 0]) & (w1 >= -r[:, 1]) & (w2 >= -r[:, 2])
        if not inside.any():
            continue
        t, ii, jj = t[inside], ii[inside], jj[inside]
        w0, w1, w2 = w0[inside], w1[inside], w2[inside]
        heights.append(w0 * a[t, 1] + w1 * b[t, 1] + w2 * c[t, 1])
        normals.append(nu[t])
        cells.append(ii * nz + jj)
    if not cells:
        return out
    cell = np.concatenate(cells)
    height = np.concatenate(heights)
    normal = np.concatenate(normals)
    order = np.lexsort((height, cell))
    cell, height, normal = cell[order], height[order], normal[order]
    dup = np.zeros(len(cell), bool)
    dup[1:] = (cell[1:] == cell[:-1]) & (height[1:] - height[:-1] <= 1e-5 * span)
    cell, height, normal = cell[~dup], height[~dup], normal[~dup]
    _, first, inverse = np.unique(cell, return_index=True, return_inverse=True)
    rank = np.arange(len(cell)) - first[inverse]
    ok = rank < max_hits
    out[cell[ok] // nz, cell[ok] % nz, rank[ok], 0] = height[ok]
    out[cell[ok] // nz, cell[ok] % nz, rank[ok], 1] = normal[ok]
    return out


# --- topline ----------------------------------------------------------------------------------------------------------

def _edges(F: np.ndarray) -> np.ndarray:
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    return np.unique(np.sort(e, axis=1), axis=0)


def topline_stations(p_frame: np.ndarray, faces: np.ndarray, gx: np.ndarray, *,
                     side_share: float = TOPLINE_SIDE_SHARE, min_abs: float = 0.0) -> Tuple[np.ndarray, np.ndarray,
                                                                                            np.ndarray]:
    """``(topline, z_pos, z_neg)`` per station: every triangle edge cut by the plane x = gx[i]
    (an edge lying in the plane gives both its ends); per side (z > 0 / z < 0) the highest cut point
    with |z| >= ``side_share`` x that side's max |z| (default ``TOPLINE_SIDE_SHARE``) and |z| > ``min_abs``;
    ``topline`` = the lower of the two sides' heights, ``z_pos`` / ``z_neg`` = the lateral position of each
    side's point. NaN where a side has no cut point. (``side_share=0`` with a ``min_abs`` of a few mm is the
    spike's wall top — the true top edge of each side, a leaning heel counter included — which the cut uses.)"""
    P = np.asarray(p_frame, np.float64).reshape(-1, 3)
    E = _edges(np.asarray(faces, np.int64).reshape(-1, 3))
    nx = len(gx)
    top = np.full(nx, np.nan)
    zp = np.full(nx, np.nan)
    zn = np.full(nx, np.nan)
    if not len(E):
        return top, zp, zn
    pa, pb = P[E[:, 0]], P[E[:, 1]]
    xlo, xhi = np.minimum(pa[:, 0], pb[:, 0]), np.maximum(pa[:, 0], pb[:, 0])
    dxe = pb[:, 0] - pa[:, 0]
    eps = 1e-9 * max(float(np.ptp(P[:, 0])), 1e-12)
    flat = np.abs(dxe) <= eps
    for i, s in enumerate(np.asarray(gx, np.float64)):
        m = (xlo <= s + eps) & (xhi >= s - eps)
        if not m.any():
            continue
        cut = m & ~flat
        tt = (s - pa[cut, 0]) / dxe[cut]
        pts = [pa[cut] + tt[:, None] * (pb[cut] - pa[cut])]
        inplane = m & flat
        if inplane.any():
            pts += [pa[inplane], pb[inplane]]
        q = np.concatenate(pts)
        heights = []
        for sign, zarr in ((1.0, zp), (-1.0, zn)):
            side = q[sign * q[:, 2] > 0]
            if not len(side):
                heights.append(np.nan)
                continue
            lat = sign * side[:, 2]
            side = side[(lat >= side_share * lat.max()) & (lat > min_abs)]
            if not len(side):
                heights.append(np.nan)
                continue
            k = int(np.argmax(side[:, 1]))
            heights.append(float(side[k, 1]))
            zarr[i] = float(side[k, 2])
        top[i] = min(heights) if not any(math.isnan(v) for v in heights) else np.nan
    return top, zp, zn


# --- tracking ---------------------------------------------------------------------------------------------------------

def _track(H: np.ndarray, length: float) -> Tuple[np.ndarray, np.ndarray]:
    """The spike's ``insole.py``: ``(ins, roof)`` (nx, nz) — the tracked insole height per cell and the
    next hit above it (NaN where none)."""
    nx, nz, K = H.shape[:3]
    air, tol = AIR_SHARE * length, TOL_SHARE * length
    hz, hn = H[..., 0], H[..., 1]
    above = np.full_like(hz, np.nan)
    above[..., :-1] = hz[..., 1:]
    cand_mask = (hn > UP_MIN) & (np.isnan(above) | (above - hz > air))
    cand = np.where(cand_mask, hz, np.nan)
    ins = np.full((nx, nz), np.nan)
    pick = np.full((nx, nz), -1, np.int64)

    def candidates(i: int, j: int) -> Tuple[np.ndarray, np.ndarray]:
        k = np.nonzero(~np.isnan(cand[i, j]))[0]
        return cand[i, j, k], k

    seed = int(SEED_SHARE * nx)
    for j in range(nz):
        c, ks = candidates(seed, j)
        if not len(c):
            continue
        k0 = int(np.argmin(c))
        z0 = float(c[k0])
        ins[seed, j], pick[seed, j] = z0, ks[k0]
        for step in (-1, 1):
            prev = [z0]
            i = seed + step
            while 0 <= i < nx:
                c, ks = candidates(i, j)
                pred = prev[-1] + (prev[-1] - prev[-3]) / 2 if len(prev) >= 3 else prev[-1]
                if not len(c):
                    break
                k = int(np.argmin(np.abs(c - pred)))
                if abs(c[k] - pred) > tol:
                    break
                ins[i, j], pick[i, j] = c[k], ks[k]
                prev.append(float(c[k]))
                i += step
    # Second pass: cells the per-column track lost (the insole curls up toward the walls) take the
    # candidate nearest the station's tracked median, within 2 TOL.
    for i in range(nx):
        tracked = ins[i][~np.isnan(ins[i])]
        if len(tracked) < 3:
            continue
        zc = float(np.median(tracked))
        for j in range(nz):
            if not np.isnan(ins[i, j]):
                continue
            c, ks = candidates(i, j)
            if not len(c):
                continue
            k = int(np.argmin(np.abs(c - zc)))
            if abs(c[k] - zc) < 2 * tol:
                ins[i, j], pick[i, j] = c[k], ks[k]
    roof = np.full((nx, nz), np.nan)
    ii, jj = np.nonzero(pick >= 0)
    nxt = pick[ii, jj] + 1
    has = nxt < K
    roof[ii[has], jj[has]] = hz[ii[has], jj[has], nxt[has]]
    return ins, roof


def _middle(js: np.ndarray) -> np.ndarray:
    """The middle 50 % of a station's insole column indices."""
    lo, hi = js.min(), js.max()
    return js[(js >= lo + 0.25 * (hi - lo)) & (js <= hi - 0.25 * (hi - lo))]


def _interp(x: float, xs: np.ndarray, ys: np.ndarray) -> Optional[float]:
    ok = ~np.isnan(ys)
    if not ok.any():
        return None
    return float(np.interp(x, xs[ok], ys[ok]))


def _r(v: Any, nd: int = 7) -> Any:
    """JSON-safe: floats rounded, NaN/inf -> None, arrays -> lists."""
    if isinstance(v, np.ndarray):
        return [_r(x, nd) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return round(f, nd) if math.isfinite(f) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


# --- the shaft ----------------------------------------------------------------------------------------------------------

def _slab_rings(p_frame: np.ndarray, faces: np.ndarray, levels: np.ndarray, eps: float,
                min_extent: float = 0.0) -> List[Dict[str, Any]]:
    """The tube slabs (module docstring): per height in ``levels`` the ring of edge-cut points of the plane
    y = level (an edge lying in the plane gives both ends) -> ``{y, x_min, x_max, z_min, z_max, gap_deg, closed}``;
    the ranges and ``gap_deg`` are ``None`` and ``closed`` False for a plane that cuts nothing. ``closed`` = four
    quadrants about the bbox centre AND ``gap_deg`` < ``RING_GAP_MAX_DEG`` AND both bbox ranges ≥ ``min_extent``."""
    P = np.asarray(p_frame, np.float64).reshape(-1, 3)
    E = _edges(np.asarray(faces, np.int64).reshape(-1, 3))
    out: List[Dict[str, Any]] = []
    empty = {"x_min": None, "x_max": None, "z_min": None, "z_max": None, "gap_deg": None, "closed": False}
    if not len(E):
        return [{"y": float(y), **empty} for y in levels]
    pa, pb = P[E[:, 0]], P[E[:, 1]]
    ylo, yhi = np.minimum(pa[:, 1], pb[:, 1]), np.maximum(pa[:, 1], pb[:, 1])
    dye = pb[:, 1] - pa[:, 1]
    flat = np.abs(dye) <= eps
    for y in levels:
        m = (ylo <= y + eps) & (yhi >= y - eps)
        slab: Dict[str, Any] = {"y": float(y), **empty}
        if m.any():
            cut = m & ~flat
            tt = (y - pa[cut, 1]) / dye[cut]
            pts = [pa[cut] + tt[:, None] * (pb[cut] - pa[cut])]
            inplane = m & flat
            if inplane.any():
                pts += [pa[inplane], pb[inplane]]
            q = np.concatenate(pts)[:, [0, 2]]
            lo, hi = q.min(0), q.max(0)
            c = 0.5 * (lo + hi)
            dx, dz = q[:, 0] - c[0], q[:, 1] - c[1]
            quadrants = bool(((dx > 0) & (dz > 0)).any() and ((dx > 0) & (dz < 0)).any()
                             and ((dx < 0) & (dz > 0)).any() and ((dx < 0) & (dz < 0)).any())
            ang = np.sort(np.degrees(np.arctan2(dz, dx)))
            gap = float(np.max(np.diff(np.concatenate([ang, ang[:1] + 360.0])))) if len(ang) > 1 else 360.0
            extent_ok = bool(min(hi[0] - lo[0], hi[1] - lo[1]) >= min_extent)
            slab.update({"x_min": float(lo[0]), "x_max": float(hi[0]), "z_min": float(lo[1]), "z_max": float(hi[1]),
                         "gap_deg": gap, "closed": quadrants and gap < RING_GAP_MAX_DEG and extent_ok})
        out.append(slab)
    return out


def _ring_cut(P: np.ndarray, F: np.ndarray, y: float, eps: float) -> np.ndarray:
    """The (x, z) points where the plane ``y`` cuts the edges of ``F`` (an edge lying in the plane gives both
    ends) — the ring of ``_slab_rings`` for one level, as points; (0, 2) when the plane cuts nothing."""
    E = _edges(F)
    if not len(E):
        return np.zeros((0, 2))
    pa, pb = P[E[:, 0]], P[E[:, 1]]
    ylo, yhi = np.minimum(pa[:, 1], pb[:, 1]), np.maximum(pa[:, 1], pb[:, 1])
    m = (ylo <= y + eps) & (yhi >= y - eps)
    if not m.any():
        return np.zeros((0, 2))
    dye = pb[:, 1] - pa[:, 1]
    flat = np.abs(dye) <= eps
    cut = m & ~flat
    tt = (y - pa[cut, 1]) / dye[cut]
    pts = [pa[cut] + tt[:, None] * (pb[cut] - pa[cut])]
    inplane = m & flat
    if inplane.any():
        pts += [pa[inplane], pb[inplane]]
    return np.concatenate(pts)[:, [0, 2]]


def _opening_polygon(ring: np.ndarray) -> np.ndarray:
    """The inner loop of a ring of cut points (module docstring): per ``CAP_RING_BINS`` angular bin about the
    ring's bbox centre the point of smallest radius, sorted by angle — the opening as a polygon (n, 2); (0, 2)
    for fewer than 3 points."""
    q = np.asarray(ring, np.float64).reshape(-1, 2)
    if len(q) < 3:
        return np.zeros((0, 2))
    c = 0.5 * (q.min(0) + q.max(0))
    d = q - c
    ang = np.arctan2(d[:, 1], d[:, 0])
    r = np.hypot(d[:, 0], d[:, 1])
    b = np.clip(((ang + math.pi) / (2.0 * math.pi) * CAP_RING_BINS).astype(int), 0, CAP_RING_BINS - 1)
    order = np.lexsort((r, b))
    first = np.concatenate([[True], b[order][1:] != b[order][:-1]])
    pick = order[first]
    pick = pick[np.argsort(ang[pick])]
    return q[pick] if len(pick) >= 3 else np.zeros((0, 2))


def _inside_polygon(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon test of ``pts`` (n, 2) against ``poly`` (m, 2)."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    inside = np.zeros(len(pts), bool)
    if len(poly) < 3 or not len(pts):
        return inside
    x, z = pts[:, 0], pts[:, 1]
    px, pz = poly[:, 0], poly[:, 1]
    qx, qz = np.roll(px, -1), np.roll(pz, -1)
    for i in range(len(poly)):
        crosses = (pz[i] > z) != (qz[i] > z)
        if not crosses.any():
            continue
        xi = px[i] + (z[crosses] - pz[i]) / (qz[i] - pz[i]) * (qx[i] - px[i])
        hit = np.zeros(len(pts), bool)
        hit[crosses] = x[crosses] < xi
        inside ^= hit
    return inside


def opening_polygon(positions: np.ndarray, faces: np.ndarray, y: float) -> np.ndarray:
    """The cross-section of a mesh at height ``y`` (its own coordinates, y up) as the inner-loop polygon (n, 2)
    of (x, z) — ``_ring_cut`` + ``_opening_polygon``; (0, 2) when the plane cuts fewer than 3 points. Used by the
    cap rule here and by ``garment_layers`` (a trouser leg tucked into a boot shaft)."""
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if not len(P) or not len(F):
        return np.zeros((0, 2))
    extent = float(np.ptp(P[:, 1]))
    return _opening_polygon(_ring_cut(P, F, float(y), 1e-9 * max(extent, 1e-12)))


def inside_polygon(points_xz: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Even-odd test of (x, z) points against a polygon from ``opening_polygon`` (all False for an empty one)."""
    return _inside_polygon(points_xz, polygon)


def _cap_mask(p_frame: np.ndarray, faces: np.ndarray, top_raw: Optional[float],
              vamp_top_raw: Optional[float]) -> np.ndarray:
    """The cap faces (module docstring): centroid height >= ``top_raw − CAP_TOP_SHARE × (top_raw − vamp top)``
    (the cap band's floor), the face normal's up component >= ``CAP_UP_MIN``, and the centroid's (x, z) inside
    the opening — the inner loop of the ring the plane at the floor cuts out of the mesh. All False without a
    closed shaft top or without a ring at the floor."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if top_raw is None or not len(F):
        return np.zeros(len(F), bool)
    P = np.asarray(p_frame, np.float64).reshape(-1, 3)
    base = float(top_raw) if vamp_top_raw is None else float(vamp_top_raw)
    floor = float(top_raw) - CAP_TOP_SHARE * max(0.0, float(top_raw) - base)
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    norm = np.linalg.norm(n, axis=1)
    nu = n[:, 1] / np.where(norm > 0, norm, 1.0)
    centroid = P[F].mean(1)
    band = (centroid[:, 1] >= floor) & (nu >= CAP_UP_MIN)
    if not band.any():
        return band
    poly = opening_polygon(P, F, floor)
    if not len(poly):
        return np.zeros(len(F), bool)
    return band & _inside_polygon(centroid[:, [0, 2]], poly)


def cap_faces(positions: np.ndarray, faces: np.ndarray, insole: Dict[str, Any]) -> np.ndarray:
    """Boolean mask over ``faces``: the shaft cap of a mesh measured as ``insole`` (``_cap_mask`` in the frame of
    ``insole`` with its ``shaft.top_raw`` / ``shaft.vamp_top_raw``)."""
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    shaft = insole.get("shaft") or {}
    return _cap_mask(frame_of(insole).to_frame(P), F, shaft.get("top_raw"), shaft.get("vamp_top_raw"))


def strip_cap(positions: np.ndarray, faces: np.ndarray, insole: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, int]:
    """``(positions, faces, removed)``: the mesh without its shaft cap (``cap_faces``); the vertices the remaining
    faces use are kept and re-indexed. The arrays come back unchanged (copies) when there is nothing to remove.
    (``footwear_source._step_insole`` filters the same mask itself to carry the UVs along.)"""
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    cap = cap_faces(P, F, insole)
    removed = int(cap.sum())
    if not removed:
        return P.copy(), F.copy(), 0
    used, inverse = np.unique(F[~cap].reshape(-1), return_inverse=True)
    return P[used].copy(), inverse.reshape(-1, 3).astype(np.int64), removed


def _shaft_block(pf: np.ndarray, F: np.ndarray, used: np.ndarray, gx: np.ndarray, top: np.ndarray,
                 prof: np.ndarray, cav: np.ndarray, roof: np.ndarray, seat: Optional[float], k: float,
                 L: float) -> Dict[str, Any]:
    """The ``shaft`` block of insole.json (module docstring); every length raw but ``collar_h_nominal``."""
    roofed = ~np.isnan(cav) & (gx > 0.5 * float(gx.max()))
    behind = gx < float(gx[roofed].min()) if roofed.any() else np.ones(len(gx), bool)
    vamp_top: Optional[float] = None
    if roofed.any():
        front = roof[gx >= float(gx[roofed].min())]
        if (~np.isnan(front)).any():
            vamp_top = float(np.nanmax(front))
    top_behind = top[behind & ~np.isnan(top)]
    collar = None if seat is None or not len(top_behind) else float(top_behind.max()) - float(seat)
    nominal = None if collar is None or k != k else collar * k
    cls = "none"
    if nominal is not None:
        rounded = _r(nominal)
        cls = next((name for name, limit in SHAFT_CLASS_M.items() if rounded <= limit), "overknee")
    slabs: List[Dict[str, Any]] = []
    y0 = None if seat is None else max(float(seat) + SHAFT_CLASS_M["none"] / k, vamp_top or -np.inf)
    eps = 1e-9 * max(L, 1e-12)
    if y0 is not None and len(used):
        ymax = float(used[:, 1].max())
        step = SHAFT_SLAB_SHARE * L
        n = int(math.floor((ymax - y0 + eps) / step)) + 1 if ymax >= y0 - eps else 0
        if n > 0:
            slabs = _slab_rings(pf, F, ymax - step * np.arange(n), eps, min_extent=RING_EXTENT_MIN_SHARE * L)
    closed = [s["closed"] for s in slabs]
    top_raw = next((s["y"] for s in slabs if s["closed"]), None)
    closed_share: Optional[float] = None
    if slabs:
        below = [c for s, c in zip(slabs, closed) if top_raw is not None and s["y"] <= top_raw + eps]
        closed_share = float(sum(below) / len(below)) if below else 0.0
    cap_removed = int(_cap_mask(pf, F, top_raw, vamp_top).sum())
    return {"collar_h_raw": collar, "collar_h_nominal": nominal, "class": cls, "top_raw": top_raw,
            "vamp_top_raw": vamp_top, "slabs": slabs, "closed_share": closed_share, "cap_removed": cap_removed}


# --- analysis ---------------------------------------------------------------------------------------------------------

def _measure(P: np.ndarray, F: np.ndarray, frame: ShoeFrame) -> Dict[str, Any]:
    """Every measurement in ``frame`` (raw units); ``flip`` = the insole says the heel is the other end."""
    L = frame.length
    pf = frame.to_frame(P)
    used = pf[np.unique(F)]
    gx = np.linspace(0.0, L, STATIONS)
    zlo, zhi = float(used[:, 2].min()), float(used[:, 2].max())
    nzc = max(8, int(STATIONS * (zhi - zlo) / L)) if L > 0 else 8
    gz = np.linspace(zlo, zhi, nzc)
    H = vertical_hits(pf, F, gx, gz)
    ins, roof = _track(H, L)
    air = AIR_SHARE * L

    footprint = ~np.isnan(H[:, :, 0, 0])
    n_fp = int(footprint.sum())
    found = ~np.isnan(ins)
    # the outsole footprint: the columns whose lowest hit faces down (module docstring); cover and outline over it
    low = H[:, :, 0, 0]
    with np.errstate(invalid="ignore"):
        sole = footprint & (H[:, :, 0, 1] <= DOWN_MAX)
    n_sole = int(sole.sum())
    insole_cover = float((found & sole).sum() / n_sole) if n_sole else 0.0
    footprint_ground = float(n_sole / n_fp) if n_fp else 0.0

    prof = np.full(STATIONS, np.nan)
    cav = np.full(STATIONS, np.nan)
    mid_z = np.full(STATIONS, np.nan)
    for i in range(STATIONS):
        js = np.nonzero(found[i])[0]
        if len(js) < 4:
            continue
        c = _middle(js)
        prof[i] = float(np.median(ins[i, c]))
        mid_z[i] = float(np.median(gz[c]))
        r = roof[i, c] - ins[i, c]
        if np.mean(~np.isnan(r)) > 0.5:
            cav[i] = float(np.nanmedian(r))

    k = NOMINAL_LENGTH_M / L if L > 0 else float("nan")
    p_heel = _interp(PITCH_HEEL_SHARE * L, gx, prof)
    p_toe = _interp((1.0 - PITCH_HEEL_SHARE) * L, gx, prof)
    flip = p_heel is not None and p_toe is not None and p_heel < p_toe

    # vamp cover: forefoot footprint cells with a hit above the insole (a cell without its own
    # insole is judged against the station profile, interpolated where the station has none)
    ref = np.where(found, ins, np.nan)
    fill = np.isnan(ref)
    if fill.any() and (~np.isnan(prof)).any():
        ok = ~np.isnan(prof)
        ref = np.where(fill, np.interp(gx, gx[ok], prof[ok])[:, None], ref)
    fore = footprint & (gx >= BALL_SHARE * L)[:, None]
    with np.errstate(invalid="ignore"):
        covered = np.any(H[..., 0] > (ref + 0.25 * air)[..., None], axis=2)
    n_fore = int(fore.sum())
    vamp_cover = float((covered & fore).sum() / n_fore) if n_fore else 0.0

    top, zp, zn = topline_stations(pf, F, gx)

    # footprint outline: per station the lateral extent of the outsole cells
    left, right = [], []
    for i in range(STATIONS):
        js = np.nonzero(sole[i])[0]
        if len(js):
            left.append([gx[i], gz[js.min()]])
            right.append([gx[i], gz[js.max()]])
    outline = left + right[::-1]

    # cavity end: the first roofed station in front of the ball lower than the toes
    valid = np.nonzero(~np.isnan(prof))[0]
    cavity_end = float(gx[valid[-1]]) if len(valid) else None
    if len(valid) and k == k:
        for i in range(STATIONS):
            if gx[i] >= BALL_SHARE * L and not np.isnan(cav[i]) and cav[i] * k < CAVITY_MIN_M:
                cavity_end = float(gx[i])
                break

    # sole contacts
    contacts: Dict[str, Optional[List[float]]] = {"heel_tip": None, "ball": None, "toe_tip": None}
    if n_fp:
        ground = footprint & (low <= np.nanmin(low) + GROUND_SHARE * L)
        band = CONTACT_BAND_SHARE * L
        X = np.broadcast_to(gx[:, None], low.shape)
        Z = np.broadcast_to(gz[None, :], low.shape)
        rear = ground & (X < 0.5 * L)
        if rear.any():
            sel = rear & (X <= X[rear].min() + band)
            contacts["heel_tip"] = [float(X[sel].mean()), float(low[sel].mean()), float(Z[sel].mean())]
        ball = ground & (np.abs(X - BALL_SHARE * L) <= band)
        if ball.any():
            contacts["ball"] = [float(X[ball].mean()), float(low[ball].mean()), float(Z[ball].mean())]
        else:
            i = int(np.argmin(np.abs(gx - BALL_SHARE * L)))
            js = np.nonzero(footprint[i])[0]
            if len(js):
                j = int(js[np.argmin(np.abs(gz[js] - gz[js].mean()))])
                contacts["ball"] = [float(gx[i]), float(low[i, j]), float(gz[j])]
        i_toe = int(np.nonzero(footprint.any(axis=1))[0].max())
        js = np.nonzero(footprint[i_toe])[0]
        contacts["toe_tip"] = [float(gx[i_toe]), float(low[i_toe, js].min()), float(gz[js].mean())]

    # nominal numbers
    seat = _interp(HEEL_SEAT_M / k, gx, prof) if k == k else None
    ball_h = _interp(BALL_SHARE * L, gx, prof)
    pitch = shank = None
    if p_heel is not None and ball_h is not None:
        pitch = math.degrees(math.atan2(p_heel - ball_h, (BALL_SHARE - PITCH_HEEL_SHARE) * L))
    if seat is not None:
        span = (gx >= HEEL_SEAT_M / k) & (gx <= BALL_SHARE * L)
        idx = np.nonzero(span & ~np.isnan(prof))[0]
        if len(idx) >= 2:
            slopes = np.degrees(np.arctan2(np.diff(prof[idx]), np.diff(gx[idx])))
            shank = float(np.median(slopes))
    nominal = {
        "k": k,
        "heel_seat_h_m": None if seat is None else seat * k,
        "insole_ball_h_m": None if ball_h is None else ball_h * k,
        "heel_rise_m": None if seat is None or ball_h is None else (seat - ball_h) * k,
        "pitch_deg": pitch,
        "shank_slope_deg": shank,
    }

    # opening: stations whose side walls (the lower one) rise AIR above the insole
    with_prof = ~np.isnan(prof)
    with np.errstate(invalid="ignore"):
        walls = with_prof & (top - prof >= air)
    opening_share = float(walls.sum() / with_prof.sum()) if with_prof.any() else 0.0
    shaft = _shaft_block(pf, F, used, gx, top, prof, cav, roof, seat, k, L)
    metrics = {"insole_cover": insole_cover, "vamp_cover": vamp_cover, "opening_share": opening_share,
               "shaft_closed_share": shaft["closed_share"], "overknee": shaft["collar_h_nominal"]}
    ok, reasons = check_gates(metrics, {**INSOLE_GATES, **SHAFT_GATES}, optional=tuple(SHAFT_GATES))
    refusal = None
    if not ok:
        failed = {r.split(" ")[0].rstrip(":") for r in reasons}
        refusal = next((text for key, text in (("insole_cover", INSOLE_REFUSED), ("opening_share", SOLID_REFUSED),
                                               ("vamp_cover", OPEN_REFUSED), ("overknee", OVERKNEE_REFUSED),
                                               ("shaft_closed_share", SHAFT_OPEN_REFUSED)) if key in failed),
                       OPEN_REFUSED)

    finite_top = top[~np.isnan(top)]
    # overlay polylines in the mesh's own coordinates
    pi = np.nonzero(~np.isnan(prof))[0]
    insole_line = frame.to_mesh(np.stack([gx[pi], prof[pi], mid_z[pi]], axis=1)) if len(pi) else np.zeros((0, 3))
    ti = np.nonzero(~np.isnan(top))[0]
    ring = np.concatenate([np.stack([gx[ti], top[ti], zp[ti]], axis=1),
                           np.stack([gx[ti], top[ti], zn[ti]], axis=1)[::-1]]) if len(ti) else np.zeros((0, 3))
    topline_line = frame.to_mesh(ring) if len(ring) else ring

    return {
        "flip": flip,
        "length_raw": L,
        "stations": gx,
        "lateral": gz,
        "profile": prof,
        "topline": top,
        "cavity": cav,
        "footprint_outline": outline,
        "footprint_ground": footprint_ground,
        "insole_cover": insole_cover,
        "vamp_cover": vamp_cover,
        "opening_share": opening_share,
        "cavity_end_x": cavity_end,
        "shaft_h_raw": float(finite_top.max()) if len(finite_top) else None,
        "shaft": shaft,
        "contacts": contacts,
        "nominal": nominal,
        "gates": {"ok": ok, "reasons": reasons, **metrics, "refusal": refusal},
        "overlay": {"insole": insole_line, "topline": topline_line},
    }


def analyse_arrays(positions: np.ndarray, faces: np.ndarray) -> Dict[str, Any]:
    """The ``insole.json`` content of a shoe mesh (module docstring): measured in the provisional
    frame, measured again in the flipped frame when the insole says the heel is the other end."""
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    frame = shoe_frame(P, F)
    res = _measure(P, F, frame)
    flipped = bool(res.pop("flip"))
    if flipped:
        frame = frame.flipped()
        res = _measure(P, F, frame)
        res.pop("flip")
    out: Dict[str, Any] = {
        "version": INSOLE_VERSION,
        "frame": {"origin": frame.origin, "x_axis": frame.x_axis, "up": frame.up, "z_axis": frame.z_axis,
                  "length": frame.length, "flipped": flipped},
        **res,
    }
    return _r_tree(out)


def _r_tree(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _r_tree(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)) and v and all(isinstance(x, (dict, list, tuple, np.ndarray)) for x in v):
        return [_r_tree(x) for x in v]
    return _r(v)


def analyse(prepared_glb: bytes) -> Dict[str, Any]:
    """``analyse_arrays`` of a prepared shoe GLB (all primitives, node transforms ignored)."""
    from app.core import glb_mesh
    positions, faces = glb_mesh.static_arrays(prepared_glb)[:2]
    return analyse_arrays(positions, faces)


def frame_of(insole: Dict[str, Any]) -> ShoeFrame:
    """The ``ShoeFrame`` an ``insole.json`` was measured in."""
    f = insole["frame"]
    return ShoeFrame(origin=np.asarray(f["origin"], np.float64), x_axis=np.asarray(f["x_axis"], np.float64),
                     up=np.asarray(f["up"], np.float64), z_axis=np.asarray(f["z_axis"], np.float64),
                     length=float(f["length"]))


def insole_map(positions: np.ndarray, faces: np.ndarray, insole: Dict[str, Any]) -> np.ndarray:
    """The tracked insole height per cell, ``(stations, lateral)`` in the frame of ``insole`` (raw units, NaN
    where none) — the map ``analyse_arrays`` measured from, rebuilt from the same mesh, frame and grid (the
    fit reads the insole's lateral extent per station from it; ``insole.json`` keeps only the profile)."""
    frame = frame_of(insole)
    gx = np.asarray(insole["stations"], np.float64)
    gz = np.asarray(insole["lateral"], np.float64)
    pf = frame.to_frame(np.asarray(positions, np.float64).reshape(-1, 3))
    hits = vertical_hits(pf, np.asarray(faces, np.int64).reshape(-1, 3), gx, gz)
    return _track(hits, frame.length)[0]
