"""The geometric body cut under a fitted shoe: conform, cut, bisect, gates (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 14, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.7 ``cut``, § 7.1, § 8).

Pure numpy (scipy.ndimage for the gates' voxel flood fill); no Blender, no storage.

**The cut frame.** Everything in a cut description lives in the shoe's own frame at the fitted size: x along
the insole from the heel end (metres), y up from the shoe's ground, z lateral to the shoe's right, with the
fit's width factor applied to z — the WIDENED shoe sits at ``raw x (k, k, k·width_factor)`` and the foot in true
metres. The right foot is seen through the mirror of its placement, so one geometry serves both sides and the
description is still per side. The frame is attached to the bones, not to the body: ``frame`` is the 4x4 from
the Foot's bone-local bind frame to the cut frame (``diag(k, k, k·wf, 1) · FrameM · placement_bind⁻¹``), and
with the side's ``extension`` / ``toe_counter`` (the fit's own numbers) ``apply_cut`` rebuilds the stand-pose
skin matrices of Foot and ToeBase from any body's bind matrices: a body vertex is taken into the cut frame by
its OWN linear blend skinning of those two bones (other bones identity) followed by the shoe frame's inverse —
exactly how the fit measured the foot — and moved vertices come back through the inverse of their blended
affine map. No vertex indices anywhere (spec § 7.1): the same description hits both tiers and a rebuilt body.

**The description** (``cut_description``), per side: ``topline`` (the shoe's topline ring, from the insole
overlay), ``cap`` stations ``[x, y]`` = the shoe's wall top per station — the lower of the two sides' top edges,
every shoe point farther than ``WALL_SIDE_M`` from the midline counted (the record's ``insole.wall_top_raw``,
the spike's rule: behind the throat the side wall's edge, a leaning heel counter's true top included; over the
vamp its outer surface), gaps interpolated along x; ``footprint`` = the outline polygon of
``insole["footprint_outline"]`` — the OUTSOLE footprint since ``INSOLE_VERSION`` 2, the columns whose lowest hit
is a sole underside, so a flared boot shaft never widens it (its per-station middle and half-width are the upper's midline and inner
half-width the slimming works against — the tracked insole is only partial in a steep shank);
``throat`` ``{x, y}`` = the throat front (the first station with a roof in the front half)
and the vamp edge (the cap there); ``vamp_inner`` stations ``[x, y]`` = the vamp's INNER surface over the roofed
stations (the insole profile plus the measured cavity, ``insole.profile + insole.cavity``; the cap over the vamp is
its outer surface, the difference the shell); ``toe_box`` ``{x_from, headroom_m, slack_m}``: in front of the throat the vamp
covers the foot, so a foot vertex up to ``VAMP_HEADROOM_M`` above the vamp's surface or ``VAMP_SLACK_M`` beside
the footprint is a mesh mismatch and goes too (spike v4's HIDE_TOEBOX; a pointed toe box narrows faster than
the slimming's ``max_share`` can follow, and a toe knuckle may stand above the vamp — hidden, never shown);
``stations`` ``{heel_x, ball_x, heel_seat_x, x_min, x_max}``; ``conform`` = the constants.

**apply_cut**, per side, in this order (spec § 7.1):

1. **Forefoot slimming.** Within the footprint's x range, from the sole up to ``cap + LATERAL_BAND_M``, measured
   per station (``SLIM_WINDOW_M`` along x) on the vertices that are mostly foot (Foot + ToeBase weight >
   ``FOOT_WEIGHT_MIN``): the station's foot half-width = max |z − mid| → factor ``s = target / half_width`` with
   target = the footprint half-width − ``CLEARANCE_M``, clipped to [1 − max_share, 1]; 1 behind the heel seat;
   smoothed over ±``SLIM_SMOOTH_M`` so the heel seat is no step. Every vertex with foot weight has its lateral
   offset from the footprint midline scaled by ``1 − (1 − s(x))·fade(y)·w``, ``fade`` = 1 up to ``cap +
   LATERAL_BAND_M``, linear to 0 over ``FADE_M`` above that, ``w`` = its Foot + ToeBase weight (the ankle, where
   the leg takes over, follows smoothly instead of stepping).
2. **Throat conform.** Vertices that are mostly foot within ``THROAT_BAND_M`` behind the throat front and above
   the vamp edge move down by their height above it times ``1 − smoothstep(d / THROAT_BAND_M)``, ``d`` = the
   distance behind the front (so a vertex at the front lands on the edge, one at the band's end stays). In
   front of the throat a toe that stands above the vamp's surface is laid onto it: it goes with the toe box in
   step 3, but the cut wall at the throat front takes the height of every crossing edge's removed endpoint,
   and without this it rose above the vamp edge as a row of slivers. (Mostly foot = Foot + ToeBase weight >
   ``FOOT_WEIGHT_MIN``: an auto-weighted knee carries a trace of Foot weight and stands over the toe box.)
2b. **Toe conform** (``CUT_VERSION`` 2, T21 round 4). In the toe box (throat front … ``x_max``) every vertex with
   foot weight is conformed INTO the toe box — the shoe keeps the item's look, the toe follows: vertically to
   ``TOE_CLEARANCE_M`` below the vamp's inner surface (``vamp_inner``, the cap where the insole has no cavity
   there; the step 2 landing on the cap stays the floor of the move), laterally to the footprint's inner
   half-width minus the clearance about its midline (the slimming's clamp without its ``max_share`` — a pointed
   toe box narrows faster than 18 % and the toes stood 16–20 mm beside it, below the vamp, on the real pump). The
   move ramps in over ``TOE_FADE_M`` in front of the throat front (0 at the front, where the throat conform's own
   landing holds, 1 from ``TOE_FADE_M`` on) and scales with the vertex's foot weight, like the slimming. The
   largest vertical push is the record's ``toe_conform_m`` (gate ``CUT_GATES["toe_conform_m"]``, 25 mm: more
   than that is not a toe under a vamp but a shoe of the wrong height for the foot); the largest lateral pull
   is the diagnostic ``toe_pull_m``. Beyond ``x_max`` nothing is conformed: a toe in front of the shoe's tip is a
   shoe too short and stays a visible poke.
3. **Removal.** ``g = max(y − cap(x), x_min − x, x − x_max, zlo(x) − z, z − zhi(x))`` (in the toe box the cap
   raised by the headroom, the prism widened by the slack): a vertex with ``g < −1e-9`` (inside the footprint
   prism and below the cap) goes; a face with three such vertices goes.
4. **Bisection.** A face with one or two removed vertices is cut where ``g = 0`` on its crossing edges (secant
   step, then bisection to 1e-12 along the edge: the cut vertex lies ON the cap, not one ring off as in spike
   v4): every float attribute and morph-target delta lerps, joints/weights = the union of the two endpoints'
   influences (lerped, top 4, renormalised); one kept vertex keeps a triangle, two keep a quad (two triangles).
5. The normals of touched vertices (moved, or on a bisected face) are recomputed area-weighted on the result.

**cut_gates** = ``toe_conform_m`` from the conform plus the spike's ``metrics.py`` voxel method at ``VOXEL_M`` (2 mm), in the cut frame: the shoe
surface voxelised and dilated once, the opening capped at the lower side-wall top of each slab (the roof range
= throat front … footprint end stays uncapped), the exterior flood-filled; a foot vertex SHOULD be enclosed when
it lies below the slab's wall top − ``SHOULD_MARGIN_M`` and in front of the heel; a poke is a should-vertex in the
exterior, deep when farther than ``DEEP_M`` from the surface. ``deep_outside`` (spec: after the slimming, before
the cut) is read on ``body_before`` run through the conform; ``visible_poke`` = the remaining foot vertices of
``body_after`` that should still be enclosed, of all remaining foot vertices; ``throat_ledge_p95_mm`` = the p95
height of the remaining vertices within ``THROAT_LEDGE_BAND_M`` behind the throat front above the measured vamp
wall top (the spike read a 2 cm band on the unconformed instep; after the smoothstep conform the step is at the
front, the band's far end is the instep's own rise — that number is ``throat_step_20mm_p95_mm`` in the
diagnostics). Diagnostics: rim gap (topline → nearest foot vertex), arch gap (lowest foot vertex per 4 mm cell →
nearest shoe surface, EDT), overhang above the rim, poke by region (heel / mid / toe by the fit's heel and ball x).

**Calibration (P3 acceptance, Task 21, 2026-11-11) — REAL material.** Kira's base body (``base20d5701a``) in the
Business Heels (UniForge mesh of the Qwen side-view empty shoe, 98 507 → 57 527 tris at ``TARGET_TRIS`` 60 000, width
cap 1.10, ``FOOTWEAR_FIT_VERSION`` 4 / ``CUT_VERSION`` 2), the clone chain live: ``slim_needed`` 0.151 (limit 0.18);
``deep_outside`` 0.12 % / 0.15 % (L / R; limit 2 %); ``visible_poke`` **0 / 0** (limit 0.5 %); ``throat_ledge_p95_mm``
0.00 / 1.04 (limit 4); ``toe_conform_m`` 4.3 / **20.9 mm** (limit 25) with ``toe_pull_m`` 10.6 / 23.9 mm; the fit
gates ball 0.000 mm, lift asymmetry 0.78 mm, ``stand_floor`` 0.0 mm, boot −52.7 mm. Before the toe conform (round 3,
``CUT_VERSION`` 1) the same material read ``visible_poke`` 0 / 3.12 %: 34 of 1090 remaining right-foot vertices, all
in the toe region 3–7 mm BELOW the cap and 16–20 mm BESIDE the footprint — the right foot is the longer one
(0.256 vs 0.242 m) and the pointed toe box narrows faster than the slimming's 18 % could follow, so the toes stood out
of its side; ``deep_outside`` was 0.47 / 1.72 %. The toe conform's lateral clamp is what removed the poke (the
vertical push, 20.9 mm, is the toe knuckle above the vamp's inner surface, which the step 2 landing already hid).
Motion (``check_footwear.mjs`` on the SERVED outfit GLB against the bare base): bind floor 0 mm over the bare
soles, still sole L/R 1 / 0 mm, idle −3.1 … −2.4 mm, walk stance −2.0 … +15.5 mm (strike ≥ −1.2, heel off ≤ −1.4,
the lift-off frames 10.2 / 15.5 at the leg's reach), Foot pitch max 45 / 47°, sit −52 … −50.5 mm (P3b). The spike
shoe (Black Stilettos) read slim 0.066 / 0.115, deep_outside 0.45 / 1.20 %, visible_poke 0 / 0, ledge 0.00 /
0.42 mm, ball 0.0, lift asym 0.06 mm (Tasks 14/15/17). **The cut limits stay at their start values** (every gate met
with margin on the real material once the toes follow the toe box); ``toe_conform_m`` 25 mm is a start value with
one data point (20.9). Calibrated upstream by the same acceptance: ``footwear_source.TARGET_TRIS`` 30 000 → 60 000
(30 000 with the seam merge collapsed the cavity: insole_cover 0.18 / 0.30 instead of 0.86 raw; 60 000 keeps 0.89)
and ``footwear_gates.MESH_GATES`` ``mesh_iou`` 0.80 → 0.75 (0.77–0.78 on both real deliveries, 0.86 on the spike; a
3/4-view cut-out, 0.66–0.76, is excluded upstream since ``FOOTWEAR_SOURCE_VERSION`` 2 — the empty edit always runs).
The source's own gates on the same item: upscale ×2 (Iris), empty ``single_share`` 1.0 / ``aspect`` 1.331 /
``iou_below_topline`` 0.943, insole cover 0.890 / vamp 0.647 / opening 0.996 (pitch 36.0°, heel seat 9.8 cm, heel
rise 9.1 cm).
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core import glb_mesh
from app.core.footwear_fit import FOOT_WEIGHT_MIN, WALL_SIDE_M, _about, _apply, _frame_matrix, _r, _smoothstep, _unit
from app.core.footwear_gates import check_gates
from app.core.footwear_insole import HEEL_SEAT_M
from app.core.glb_mesh import Prim  # noqa: F401  (re-exported: the cut's primitive type)

#: Bumped when the cut changes what it produces (the record's ``cut.version``). 2: the toe conform (step 2b).
CUT_VERSION = 2
#: The throat conform acts this far behind the throat front (metres).
THROAT_BAND_M = 0.02
#: The slimming band reaches this far above the cap (metres) ...
LATERAL_BAND_M = 0.015
#: ... and the foot ends this far inside the upper's inner half-width (metres).
CLEARANCE_M = 0.002
#: The slimming fades out over this height above the band (metres).
FADE_M = 0.015
#: The largest share of the local half-width the slimming takes off (``footwear_fit.SLIM_MAX_SHARE``).
MAX_SHARE = 0.18
#: Toe conform: the toe ends this far below the vamp's inner surface and inside the inner half-width (metres) ...
TOE_CLEARANCE_M = 0.002
#: ... and the conform ramps in over this distance in front of the throat front (metres).
TOE_FADE_M = 0.015

#: name -> (kind, limit) — ``footwear_gates.check_gates`` kinds.
CUT_GATES: Dict[str, Tuple[str, Any]] = {
    "deep_outside": ("max", 0.02),
    "visible_poke": ("max", 0.005),
    "throat_ledge_p95_mm": ("max", 4.0),
    "toe_conform_m": ("max", 0.025),
}
GATE_LABELS = {
    "deep_outside": "share of the slimmed foot's should-be-enclosed vertices > 3 mm outside the shoe, worse side",
    "visible_poke": "share of the remaining foot vertices still below the upper's rim, worse side",
    "throat_ledge_p95_mm": "p95 height of the remaining vertices just behind the throat front above the vamp edge",
    "toe_conform_m": "largest vertical push of a toe under the vamp's inner surface, worse side",
}

#: The voxel size of the enclosure test (the spike's 2 mm).
VOXEL_M = 0.002
#: A foot vertex should be enclosed below the slab's wall top minus this (metres) ...
SHOULD_MARGIN_M = 0.002
#: ... and in front of the shoe's heel end minus this (metres).
HEEL_SLACK_M = 0.005
#: A poke farther than this (metres) from the shoe surface is deep.
DEEP_M = 0.003
#: Overhang: visible vertices up to this far above the rim that stick out laterally by more than OVERHANG_M.
OVERHANG_BAND_M = 0.015
OVERHANG_M = 0.003
#: The throat ledge is read on the remaining vertices this far behind the throat front (metres).
THROAT_LEDGE_BAND_M = 0.005
#: The spike's 2 cm band of the throat step (diagnostic only).
THROAT_STEP_BAND_M = 0.02
#: Shoe vertices with |lateral| above this (metres) count as a side wall (the spike's 4 mm; the fit's rule).
SIDE_WALL_M = WALL_SIDE_M
#: In front of the throat the vamp covers the foot: a foot vertex up to this far above the vamp's surface ...
VAMP_HEADROOM_M = 0.03
#: ... or this far beside the toe box's footprint is a mesh mismatch and is hidden (spike v4's HIDE_TOEBOX).
VAMP_SLACK_M = 0.015
#: The heel region of the poke-by-region split reaches this far in front of the heel x (metres).
HEEL_REGION_M = 0.03
#: Arch gap: the lowest foot vertex per cell of this size (metres) against the shoe surface.
ARCH_CELL_M = 0.004
#: Slimming: the station's foot half-width is read over ±this along x (metres) ...
SLIM_WINDOW_M = 0.003
#: ... and the station factor is smoothed over ±this (metres).
SLIM_SMOOTH_M = 0.005
#: A vertex is removed below this signed distance (metres): a vertex ON the cap stays.
REMOVE_EPS_M = 1e-9
#: Bisection: the cut parameter is refined until |g| is under this (metres) or this many halvings.
ROOT_TOL_M = 1e-12
ROOT_STEPS = 60

SIDES = ("left", "right")


# --- the description --------------------------------------------------------------------------------------------------

def _floats(values: Any) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], np.float64)


def _fill(values: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """NaN gaps of ``values`` over ``xs`` interpolated linearly, the ends held."""
    ok = ~np.isnan(values)
    if not ok.any():
        return values
    return np.where(ok, values, np.interp(xs, xs[ok], values[ok]))


def cut_description(fit: Any, insole: Dict[str, Any]) -> Dict[str, Any]:
    """The record's ``cut`` (module docstring) from a ``footwear_fit.FootwearFit`` that ran and its item's
    ``insole.json``: ``{"version", "sides": {side: {...}}}``, JSON-safe. ValueError for a fit that produced no
    sides or a record without ``insole.width_raw``. For a split fit (a boot, fit version 6) the side's ``cap`` is
    ``min(wall top, y_split − band)`` and the description carries ``split {y_m, band_m}``."""
    record = fit.record
    sides_rec = record.get("sides") or {}
    if not sides_rec:
        raise ValueError("The fit has no sides to cut for")
    wall_raw = (record.get("insole") or {}).get("wall_top_raw")
    if wall_raw is None:
        raise ValueError("The fit record carries no insole.wall_top_raw (fit it again)")
    k = float(record["scale"]["k_m_per_unit"])
    wf = float(record["scale"]["width_factor"])
    scale3 = np.array([k, k, k * wf])
    Dm = np.diag([k, k, k * wf, 1.0])
    FrameM = _frame_matrix(insole)

    gx = _floats(insole["stations"])
    cav = _floats(insole.get("cavity") or [None] * len(gx))
    roofed = ~np.isnan(cav) & (gx > 0.5 * float(gx.max()))
    cap = _fill(_floats(wall_raw), gx)
    ok_cap = ~np.isnan(cap)
    if not ok_cap.any():
        raise ValueError("The shoe has no side walls to cap")
    cap_stations = np.stack([gx[ok_cap] * k, cap[ok_cap] * k], axis=1)
    throat: Optional[Dict[str, float]] = None
    toe_box: Optional[Dict[str, float]] = None
    vamp_inner = np.zeros((0, 2))
    if roofed.any():
        x_t = float(gx[roofed].min()) * k
        throat = {"x": x_t, "y": float(np.interp(x_t, cap_stations[:, 0], cap_stations[:, 1]))}
        toe_box = {"x_from": x_t, "headroom_m": VAMP_HEADROOM_M, "slack_m": VAMP_SLACK_M}
        prof_all = _floats(insole["profile"])
        inner_ok = roofed & ~np.isnan(prof_all)
        if inner_ok.any():
            vamp_inner = np.stack([gx[inner_ok] * k, (prof_all[inner_ok] + cav[inner_ok]) * k], axis=1)

    outline = np.asarray(insole["footprint_outline"], np.float64).reshape(-1, 2) * np.array([k, k * wf])
    if len(outline) < 3:
        raise ValueError("The insole has no footprint outline")
    prof = _floats(insole["profile"])
    if not (~np.isnan(prof)).any():
        raise ValueError("The insole has no profile")
    heel_seat_x = float(gx[~np.isnan(prof)].min()) * k + HEEL_SEAT_M
    ring = np.asarray((insole.get("overlay") or {}).get("topline") or np.zeros((0, 3)), np.float64).reshape(-1, 3)
    topline = _apply(FrameM, ring) * scale3 if len(ring) else np.zeros((0, 3))
    x_min, x_max = (float(outline[:, 0].min()), float(outline[:, 0].max())) if len(outline) else (0.0, 0.0)
    diag = record.get("diagnostics") or {}

    sides: Dict[str, Any] = {}
    for side, rec in sides_rec.items():
        placement = np.asarray(rec["placement_bind"], np.float64)
        frame = Dm @ FrameM @ np.linalg.inv(placement)
        shoe = ((fit.parts or {}).get(side) or {}).get("foot")
        if shoe is None or len(shoe.joint_names) < 2:
            raise ValueError(f"The fit has no bound shoe for the {side} side")
        foot_joint, toe_joint = str(shoe.joint_names[0]), str(shoe.joint_names[1])
        d = diag.get(side) or {}
        # a split fit (boots spec § 7): the removal stops at the bottom of the band instead of climbing the
        # shaft's wall top — the shin stays inside the shaft, the bisected edge lies hidden in it
        split = rec.get("split") or {}
        side_cap = cap_stations
        if split.get("is_boot"):
            bound = float(split["y_m"]) - float(split.get("band_m", 0.0))
            side_cap = np.stack([cap_stations[:, 0], np.minimum(cap_stations[:, 1], bound)], axis=1)
        sides[side] = {
            "foot_joint": foot_joint, "toe_joint": toe_joint, "frame": frame,
            "extension": {"axis_local": rec["extension"]["axis_local"], "deg": rec["extension"]["deg"]},
            "toe_counter": {"axis_local": rec["toe_counter"]["axis_local"], "deg": rec["toe_counter"]["deg"]},
            "topline": topline, "cap": side_cap, "footprint": outline,
            **({"split": {"y_m": float(split["y_m"]), "band_m": float(split.get("band_m", 0.0))}}
               if split.get("is_boot") else {}),
            "throat": throat, "toe_box": toe_box, "vamp_inner": vamp_inner,
            "stations": {"heel_x": d.get("heel_x_m"), "ball_x": d.get("ball_x_m"),
                         "heel_seat_x": heel_seat_x, "x_min": x_min, "x_max": x_max},
            "conform": {"throat_band_m": THROAT_BAND_M, "lateral_band_m": LATERAL_BAND_M,
                        "slim": {"clearance_m": CLEARANCE_M, "fade_m": FADE_M, "max_share": MAX_SHARE},
                        "toe": {"clearance_m": TOE_CLEARANCE_M, "fade_m": TOE_FADE_M}},
        }
    return _r({"version": CUT_VERSION, "sides": sides})


# --- the side geometry --------------------------------------------------------------------------------------------------

class _Side:
    """One side's description as callables over the cut frame."""

    def __init__(self, desc: Dict[str, Any]):
        self.desc = desc
        cap = np.asarray(desc["cap"], np.float64).reshape(-1, 2)
        order = np.argsort(cap[:, 0])
        self.cap_x, self.cap_y = cap[order, 0], cap[order, 1]
        fp = np.asarray(desc["footprint"], np.float64).reshape(-1, 2)
        st = desc.get("stations") or {}
        if len(fp) >= 3:
            self.fp_x, self.fp_lo, self.fp_hi = _prism_bounds(fp)
            self.x_min = float(self.fp_x.min() if st.get("x_min") is None else st["x_min"])
            self.x_max = float(self.fp_x.max() if st.get("x_max") is None else st["x_max"])
        else:
            self.fp_x = np.array([0.0, 1.0])
            self.fp_lo = np.array([np.inf, np.inf])
            self.fp_hi = np.array([-np.inf, -np.inf])
            self.x_min, self.x_max = 1.0, 0.0
        self.throat = desc.get("throat")
        tb = desc.get("toe_box") or {}
        self.toe_from = float(tb["x_from"]) if tb.get("x_from") is not None else np.inf
        self.toe_headroom = float(tb.get("headroom_m", VAMP_HEADROOM_M))
        self.toe_slack = float(tb.get("slack_m", VAMP_SLACK_M))
        conform = desc.get("conform") or {}
        slim = conform.get("slim") or {}
        self.throat_band = float(conform.get("throat_band_m", THROAT_BAND_M))
        self.lateral_band = float(conform.get("lateral_band_m", LATERAL_BAND_M))
        self.clearance = float(slim.get("clearance_m", CLEARANCE_M))
        self.fade = float(slim.get("fade_m", FADE_M))
        self.max_share = float(slim.get("max_share", MAX_SHARE))
        toe = conform.get("toe") or {}
        self.toe_clearance = float(toe.get("clearance_m", TOE_CLEARANCE_M))
        self.toe_fade = float(toe.get("fade_m", TOE_FADE_M))
        vi = np.asarray(desc.get("vamp_inner") if desc.get("vamp_inner") is not None else np.zeros((0, 2)),
                        np.float64).reshape(-1, 2)
        vi = vi[np.argsort(vi[:, 0])] if len(vi) else vi
        self.inner_x, self.inner_y = (vi[:, 0], vi[:, 1]) if len(vi) else (np.zeros(0), np.zeros(0))
        seat = st.get("heel_seat_x")
        self.heel_seat_x = float(seat) if seat is not None else self.x_min + HEEL_SEAT_M

    def cap(self, x: np.ndarray) -> np.ndarray:
        return np.interp(x, self.cap_x, self.cap_y)

    def zlo(self, x: np.ndarray) -> np.ndarray:
        return np.interp(x, self.fp_x, self.fp_lo)

    def zhi(self, x: np.ndarray) -> np.ndarray:
        return np.interp(x, self.fp_x, self.fp_hi)

    def mid(self, x: np.ndarray) -> np.ndarray:
        """The footprint's lateral middle per station."""
        return 0.5 * (self.zlo(x) + self.zhi(x))

    def hw(self, x: np.ndarray) -> np.ndarray:
        """The footprint's half-width per station — the upper's inner half-width before the clearance."""
        return 0.5 * (self.zhi(x) - self.zlo(x))

    def inner(self, x: np.ndarray) -> np.ndarray:
        """The vamp's inner surface per station: the measured one where the insole has a cavity, never above
        the cap (the outer surface), the cap itself elsewhere."""
        c = self.cap(x)
        if not len(self.inner_x):
            return c
        return np.minimum(c, np.interp(x, self.inner_x, self.inner_y))

    def g(self, X: np.ndarray) -> np.ndarray:
        """Signed removal distance (metres): negative inside the footprint prism below the cap; in front of the
        throat (the toe box) the cap is raised by the headroom and the prism widened by the slack."""
        x, y, z = X[:, 0], X[:, 1], X[:, 2]
        front = x >= self.toe_from
        head = np.where(front, self.toe_headroom, 0.0)
        slack = np.where(front, self.toe_slack, 0.0)
        return np.max(np.stack([y - self.cap(x) - head, self.x_min - x, x - self.x_max,
                                self.zlo(x) - slack - z, z - self.zhi(x) - slack]), axis=0)


def _prism_bounds(fp: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(xs, zlo, zhi)`` of a closed outline polygon: at every distinct x of its points the lowest and highest z
    of the polygon's edges crossing that x (a vertical edge contributes both its ends), so a rectangle and the
    insole's station outline are both exact; between the xs the bounds interpolate linearly."""
    xs = np.unique(fp[:, 0])
    lo = np.full(len(xs), np.inf)
    hi = np.full(len(xs), -np.inf)
    eps = 1e-12 * max(float(np.ptp(fp[:, 0])), 1e-9)
    n = len(fp)
    for i in range(n):
        p, q = fp[i], fp[(i + 1) % n]
        xa, xb = (p[0], q[0]) if p[0] <= q[0] else (q[0], p[0])
        m = (xs >= xa - eps) & (xs <= xb + eps)
        if not m.any():
            continue
        if xb - xa <= eps:
            z = np.full(m.sum(), min(p[1], q[1]))
            lo[m] = np.minimum(lo[m], z)
            hi[m] = np.maximum(hi[m], np.full(m.sum(), max(p[1], q[1])))
            continue
        z = p[1] + (xs[m] - p[0]) / (q[0] - p[0]) * (q[1] - p[1])
        lo[m] = np.minimum(lo[m], z)
        hi[m] = np.maximum(hi[m], z)
    return xs, lo, hi


# --- transforms -----------------------------------------------------------------------------------------------------

def _weight_of(prim: Prim, key: str) -> np.ndarray:
    """The summed weight of every skin index of ``prim`` whose normalised name is ``key``."""
    from app.core.rig_contract import norm_bone_name
    idx = [i for i, name in enumerate(prim.joint_names) if norm_bone_name(str(name)) == key]
    if not idx or not len(prim.joints):
        return np.zeros(len(prim.positions))
    J = np.asarray(prim.joints, np.int64)
    W = np.asarray(prim.weights, np.float64)
    return np.where(np.isin(J, idx), W, 0.0).sum(axis=1)


class _Map:
    """Bind space <-> cut frame for one side on one primitive (module docstring)."""

    def __init__(self, desc: Dict[str, Any], joints: Dict[str, np.ndarray], prim: Prim):
        from app.core.rig_contract import norm_bone_name
        fkey, tkey = norm_bone_name(str(desc["foot_joint"])), norm_bone_name(str(desc["toe_joint"]))
        if fkey not in joints or tkey not in joints:
            raise ValueError(f"The body has no {desc['foot_joint']} / {desc['toe_joint']} joint")
        Jf = np.asarray(joints[fkey], np.float64)
        Jt = np.asarray(joints[tkey], np.float64)
        axis = _unit(Jf[:3, :3] @ np.asarray(desc["extension"]["axis_local"], np.float64))
        theta = np.radians(float(desc["extension"]["deg"]))
        toe_turn = np.radians(float(desc["toe_counter"]["deg"]))
        Bf = _about(Jf[:3, 3], axis, theta)
        Bt = _about(_apply(Bf, Jt[:3, 3]), axis, toe_turn) @ Bf
        frame = np.asarray(desc["frame"], np.float64)
        self.Tf = frame @ np.linalg.inv(Jf)
        self.T0 = self.Tf @ np.linalg.inv(Bf)
        self.Tt = self.T0 @ Bt
        self.wF = _weight_of(prim, fkey)
        self.wT = _weight_of(prim, tkey)
        self.foot = self.wF + self.wT

    def blend(self, wF: np.ndarray, wT: np.ndarray) -> np.ndarray:
        """The per-vertex affine map bind -> cut, (n, 4, 4)."""
        w0 = 1.0 - wF - wT
        return (w0[:, None, None] * self.T0[None] + wF[:, None, None] * self.Tf[None]
                + wT[:, None, None] * self.Tt[None])

    def to_cut(self, P: np.ndarray, wF: Optional[np.ndarray] = None, wT: Optional[np.ndarray] = None) -> np.ndarray:
        wF = self.wF if wF is None else wF
        wT = self.wT if wT is None else wT
        base = _apply(self.T0, P)
        return base + wF[:, None] * (_apply(self.Tf, P) - base) + wT[:, None] * (_apply(self.Tt, P) - base)

    def to_bind(self, C: np.ndarray, ids: np.ndarray) -> np.ndarray:
        A = self.blend(self.wF[ids], self.wT[ids])
        inv = np.linalg.inv(A)
        return np.einsum("nij,nj->ni", inv[:, :3, :3], C) + inv[:, :3, 3]


# --- conform ----------------------------------------------------------------------------------------------------

def _slim_factors(side: _Side, C: np.ndarray, cand: np.ndarray, meas: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Per-station slimming factor ``s`` (stations every ``SLIM_WINDOW_M`` over the candidates' x range, the
    footprint's midline / half-width interpolated there; the station's foot half-width read on ``meas``, the
    vertices that are mostly foot) and the per-vertex factor for ``cand``."""
    if not cand.any():
        return np.zeros(0), {"slim_share": 0.0, "slim_station_max": 0.0}
    X = C[cand]
    xs = np.arange(float(X[:, 0].min()), float(X[:, 0].max()) + SLIM_WINDOW_M, SLIM_WINDOW_M)
    s = np.ones(len(xs))
    need = np.ones(len(xs))          # the uncapped factor: what the station would need
    has = np.zeros(len(xs), bool)
    Xm = C[meas]
    band = Xm[:, 1] <= side.cap(Xm[:, 0]) + side.lateral_band + 1e-12
    Xb = Xm[band]
    if len(Xb):
        order = np.argsort(Xb[:, 0])
        bx = Xb[order, 0]
        boff = np.abs(Xb[order, 2] - side.mid(Xb[order, 0]))
        lo = np.searchsorted(bx, xs - SLIM_WINDOW_M, side="left")
        hi = np.searchsorted(bx, xs + SLIM_WINDOW_M, side="right")
        targets = side.hw(xs) - side.clearance
        for i in range(len(xs)):
            if hi[i] > lo[i] and xs[i] >= side.heel_seat_x:
                has[i] = True
                hw_foot = float(boff[lo[i]:hi[i]].max())
                if hw_foot > targets[i] > 0:
                    need[i] = targets[i] / hw_foot
                    s[i] = max(1.0 - side.max_share, need[i])
    # smooth over ±SLIM_SMOOTH_M across the stations that carry a value (behind the heel seat s = 1 counts); a
    # station without one in its window takes the interpolated neighbours (the ends held, so the toe tip
    # keeps the last measured factor)
    valid = has | (xs < side.heel_seat_x)
    s_sm = s.copy()
    if valid.any():
        vx, vs = xs[valid], s[valid]
        lo = np.searchsorted(vx, xs - SLIM_SMOOTH_M, side="left")
        hi = np.searchsorted(vx, xs + SLIM_SMOOTH_M, side="right")
        cs = np.concatenate([[0.0], np.cumsum(vs)])
        n = hi - lo
        mean = np.where(n > 0, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)
        s_sm = _fill(mean, xs)
    per_vertex = np.interp(C[cand, 0], xs, s_sm) if cand.any() else np.zeros(0)
    info = {"slim_share": float(1.0 - s_sm[valid].min()) if valid.any() else 0.0,
            "slim_station_max": float(1.0 - need.min())}
    return per_vertex, info


def conform_body(prim: Prim, cut: Dict[str, Any], joints: Dict[str, np.ndarray]) -> Tuple[Prim, Dict[str, Any]]:
    """Steps 1–2 of ``apply_cut`` on every side of ``cut``: the forefoot slimming and the throat conform, positions
    moved in bind space, everything else untouched. ``(prim, info)`` with per-side ``slim_share`` /
    ``throat_moved`` and the touched vertex ids (``touched``)."""
    P = np.asarray(prim.positions, np.float64).copy()
    touched = np.zeros(len(P), bool)
    info: Dict[str, Any] = {"slim_share": {}, "throat_moved": {}, "slim_station_max": {}, "toe_conform": {},
                            "toe_pull": {}}
    for name, desc in (cut.get("sides") or {}).items():
        side = _Side(desc)
        m = _Map(desc, joints, prim)
        C = m.to_cut(P)
        x, y, z = C[:, 0], C[:, 1].copy(), C[:, 2]      # y: the height before any move (the toe push is read against it)
        capx = side.cap(x)
        foot = m.foot > 0
        in_x = (x >= side.x_min) & (x <= side.x_max)
        moved = np.zeros(len(P), bool)
        # 1. slimming: measured on the vertices that are mostly foot, applied to every vertex with foot weight
        # in proportion to it (so the ankle, where the leg's weight takes over, follows smoothly)
        cand = foot & in_x & (y <= capx + side.lateral_band + side.fade)
        meas = cand & (m.foot > FOOT_WEIGHT_MIN)
        s_v, sinfo = _slim_factors(side, C, cand, meas)
        if cand.any():
            ids = np.nonzero(cand)[0]
            fade = np.clip((capx[ids] + side.lateral_band + side.fade - y[ids]) / side.fade, 0.0, 1.0)
            factor = 1.0 - (1.0 - s_v) * fade * np.minimum(1.0, m.foot[ids])
            mid = side.mid(x[ids])
            newz = mid + (z[ids] - mid) * factor
            change = np.abs(newz - z[ids]) > 0
            C[ids[change], 2] = newz[change]
            moved[ids[change]] = True
        info["slim_share"][name] = sinfo["slim_share"]
        info["slim_station_max"][name] = sinfo["slim_station_max"]
        # 2. throat conform — on the vertices that are mostly foot: a knee carries a trace of Foot weight in an
        # auto-weighted rig and stands over the toe box in the cut frame
        n_throat = 0
        toe_conform = toe_pull = 0.0
        mostly = m.foot > FOOT_WEIGHT_MIN
        if side.throat:
            xt, yt = float(side.throat["x"]), float(side.throat["y"])
            d = xt - x
            band = mostly & (d >= 0.0) & (d <= side.throat_band) & (z >= side.zlo(x)) & (z <= side.zhi(x)) & (y > yt)
            if band.any():
                ids = np.nonzero(band)[0]
                drop = (y[ids] - yt) * (1.0 - _smoothstep(d[ids] / side.throat_band))
                C[ids, 1] = y[ids] - drop
                moved[ids] = True
                n_throat = int(len(ids))
            # in front of the throat a toe knuckle that stands above the vamp is laid onto the vamp's surface
            # first: it goes with the toe box anyway, but the cut wall at the throat front inherits the height
            # of the removed endpoint of every crossing edge — without this the wall rises above the vamp edge
            # as a row of slivers
            zone = (d < 0.0) & (x <= side.x_max)
            fore = mostly & zone & (z >= side.zlo(x) - side.toe_slack) & (z <= side.zhi(x) + side.toe_slack) \
                & (y > capx)
            if fore.any():
                ids = np.nonzero(fore)[0]
                C[ids, 1] = capx[ids]
                moved[ids] = True
            # 2b. toe conform: the toe box narrows and lowers the toes into it (module docstring), ramped in over
            # TOE_FADE_M in front of the throat front and by foot weight; the landing above stays its floor
            zone &= foot
            if zone.any():
                ids = np.nonzero(zone)[0]
                ramp = np.clip(-d[ids] / side.toe_fade, 0.0, 1.0) * np.minimum(1.0, m.foot[ids])
                target = side.inner(x[ids]) - side.toe_clearance
                y_now = C[ids, 1]
                drop = ramp * np.maximum(0.0, y_now - target)
                mid = side.mid(x[ids])
                off = C[ids, 2] - mid
                hw_t = np.maximum(side.hw(x[ids]) - side.toe_clearance, 0.0)
                mag = np.abs(off)
                squeeze = np.where(mag > hw_t, np.where(mag > 0, hw_t / np.where(mag > 0, mag, 1.0), 1.0), 1.0)
                new_off = off * (1.0 - ramp * (1.0 - squeeze))
                change = (drop > 0) | (np.abs(new_off - off) > 0)
                C[ids, 1] = y_now - drop
                C[ids, 2] = mid + new_off
                moved[ids[change]] = True
                toe_conform = max(toe_conform, float((y[ids] - C[ids, 1]).max()))
                toe_pull = max(toe_pull, float(np.abs(new_off - off).max()))
        info["throat_moved"][name] = n_throat
        info["toe_conform"][name] = toe_conform
        info["toe_pull"][name] = toe_pull
        if moved.any():
            ids = np.nonzero(moved)[0]
            P[ids] = m.to_bind(C[ids], ids)
            touched |= moved
    out = Prim(positions=P, faces=np.asarray(prim.faces, np.int64).copy(),
               attributes={k: np.asarray(v, np.float64).copy() for k, v in prim.attributes.items()},
               joints=np.asarray(prim.joints, np.int64).copy(), weights=np.asarray(prim.weights, np.float64).copy(),
               targets=[{k: np.asarray(v, np.float64).copy() for k, v in t.items()} for t in prim.targets],
               joint_names=list(prim.joint_names))
    info["touched"] = touched
    return out, info


# --- removal + bisection --------------------------------------------------------------------------------------------

def _edge_roots(side: _Side, m: _Map, P: np.ndarray, a: np.ndarray, b: np.ndarray, ga: np.ndarray,
                gb: np.ndarray) -> np.ndarray:
    """``t`` per edge (removed ``a`` -> kept ``b``) where ``g`` crosses zero: a secant step, then bisection."""
    Ca, Cb = m.to_cut(P[a], m.wF[a], m.wT[a]), m.to_cut(P[b], m.wF[b], m.wT[b])
    wa = np.stack([m.wF[a], m.wT[a]], 1)
    wb = np.stack([m.wF[b], m.wT[b]], 1)

    def g_at(t: np.ndarray) -> np.ndarray:
        # the new vertex is the bind-space lerp with lerped weights, seen in the cut frame
        Pt = P[a] + t[:, None] * (P[b] - P[a])
        wt = wa + t[:, None] * (wb - wa)
        return side.g(m.to_cut(Pt, wt[:, 0], wt[:, 1]))

    lo, hi = np.zeros(len(a)), np.ones(len(a))
    glo, ghi = ga.copy(), gb.copy()
    t = np.clip(ga / (ga - gb), 0.0, 1.0)
    for _ in range(ROOT_STEPS):
        gt = g_at(t)
        done = np.abs(gt) <= ROOT_TOL_M
        if done.all():
            break
        neg = gt < 0
        lo = np.where(neg & ~done, t, lo)
        glo = np.where(neg & ~done, gt, glo)
        hi = np.where(~neg & ~done, t, hi)
        ghi = np.where(~neg & ~done, gt, ghi)
        t_new = 0.5 * (lo + hi)
        t = np.where(done, t, t_new)
    return t


def _union_skin(J: np.ndarray, W: np.ndarray, a: np.ndarray, b: np.ndarray, t: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Joints/weights of the edge points: the union of both endpoints' influences, lerped, top 4, renormalised."""
    n = len(a)
    if not len(J):
        return np.zeros((n, 4), np.int64), np.zeros((n, 4))
    cj = np.concatenate([J[a], J[b]], axis=1)
    cw = np.concatenate([(1.0 - t)[:, None] * W[a], t[:, None] * W[b]], axis=1)
    outj = np.zeros((n, 4), np.int64)
    outw = np.zeros((n, 4))
    for i in range(n):
        acc: Dict[int, float] = {}
        for j, w in zip(cj[i], cw[i]):
            if w > 0:
                acc[int(j)] = acc.get(int(j), 0.0) + float(w)
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        total = sum(w for _, w in top)
        for k, (j, w) in enumerate(top):
            outj[i, k] = j
            outw[i, k] = w / total if total > 0 else 0.0
    return outj, outw


def _recompute_normals(P: np.ndarray, F: np.ndarray, N: np.ndarray, ids: np.ndarray) -> None:
    """Area-weighted vertex normals of ``ids`` from the faces of ``F`` (in place)."""
    if not len(ids):
        return
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    acc = np.zeros_like(P)
    for k in range(3):
        np.add.at(acc, F[:, k], fn)
    n = np.linalg.norm(acc[ids], axis=1, keepdims=True)
    N[ids] = np.where(n > 0, acc[ids] / np.where(n > 0, n, 1.0), N[ids])


def _cut_side(prim: Prim, desc: Dict[str, Any], joints: Dict[str, np.ndarray],
              touched: np.ndarray) -> Tuple[Prim, Dict[str, int], np.ndarray]:
    """Steps 3–4 for one side on ``prim`` (positions already conformed)."""
    side = _Side(desc)
    m = _Map(desc, joints, prim)
    P = np.asarray(prim.positions, np.float64)
    F = np.asarray(prim.faces, np.int64)
    J = np.asarray(prim.joints, np.int64)
    W = np.asarray(prim.weights, np.float64)
    g = side.g(m.to_cut(P))
    removed = g < -REMOVE_EPS_M
    rf = removed[F]
    n_rem = rf.sum(axis=1)
    stats = {"removed_faces": int((n_rem == 3).sum()), "bisected_faces": int(((n_rem > 0) & (n_rem < 3)).sum()),
             "new_vertices": 0}
    if not removed.any():
        return prim, stats, touched
    keep_faces = F[n_rem == 0]
    cross = np.nonzero((n_rem > 0) & (n_rem < 3))[0]
    # rotate every crossing face so its pattern is [R, K, K] or [R, R, K]
    rot = np.zeros(len(cross), np.int64)
    for i, fi in enumerate(cross):
        flags = rf[fi]
        if int(flags.sum()) == 1:
            rot[i] = int(np.nonzero(flags)[0][0])
        else:
            rot[i] = (int(np.nonzero(~flags)[0][0]) + 1) % 3
    tri = np.stack([F[cross, (rot + k) % 3] for k in range(3)], axis=1)
    one = rf[cross].sum(axis=1) == 1
    # the crossing edges: removed endpoint first; a kept endpoint that already sits ON the cap (g within the
    # root tolerance, e.g. pulled onto the vamp edge by the throat conform) is the cut point itself: no new
    # vertex, the degenerate triangles are dropped below
    edges: List[Tuple[int, int]] = []
    e_index: Dict[Tuple[int, int], int] = {}

    def edge(r: int, k: int) -> int:
        if g[k] <= ROOT_TOL_M:
            return -(k + 1)
        key = (r, k)
        if key not in e_index:
            e_index[key] = len(edges)
            edges.append(key)
        return e_index[key]

    tri_edges = np.zeros((len(cross), 2), np.int64)
    for i in range(len(cross)):
        a, b, c = (int(v) for v in tri[i])
        if one[i]:
            tri_edges[i] = (edge(a, b), edge(a, c))      # n_ab, n_ca
        else:
            tri_edges[i] = (edge(b, c), edge(a, c))      # n_bc, n_ca
    ea = np.array([e[0] for e in edges], np.int64)
    eb = np.array([e[1] for e in edges], np.int64)
    t = _edge_roots(side, m, P, ea, eb, g[ea], g[eb]) if len(edges) else np.zeros(0)
    n_old = len(P)
    kept = ~removed
    new_index = np.full(n_old, -1, np.int64)
    new_index[kept] = np.arange(int(kept.sum()))
    base = int(kept.sum())
    e_new = base + np.arange(len(edges))

    def lerp(A: np.ndarray) -> np.ndarray:
        return np.concatenate([A[kept], A[ea] + t[:, None] * (A[eb] - A[ea])])

    def point(code: int) -> int:
        return int(new_index[-code - 1]) if code < 0 else int(e_new[code])

    positions = lerp(P)
    attributes = {k: lerp(np.asarray(v, np.float64)) for k, v in prim.attributes.items()}
    targets = [{k: lerp(np.asarray(v, np.float64)) for k, v in tgt.items()} for tgt in prim.targets]
    nj, nw = _union_skin(J, W, ea, eb, t)
    joints_out = np.concatenate([J[kept], nj]) if len(J) else J
    weights_out = np.concatenate([W[kept], nw]) if len(W) else W
    faces = [new_index[keep_faces]]
    for i in range(len(cross)):
        a, b, c = (int(v) for v in tri[i])
        n1, n2 = point(int(tri_edges[i, 0])), point(int(tri_edges[i, 1]))
        if one[i]:
            faces.append(np.array([[new_index[b], new_index[c], n2], [new_index[b], n2, n1]], np.int64))
        else:
            faces.append(np.array([[n1, new_index[c], n2]], np.int64))
    faces_out = np.concatenate(faces) if faces else np.zeros((0, 3), np.int64)
    degenerate = ((faces_out[:, 0] == faces_out[:, 1]) | (faces_out[:, 1] == faces_out[:, 2])
                  | (faces_out[:, 0] == faces_out[:, 2]))
    faces_out = faces_out[~degenerate]
    stats["new_vertices"] = int(len(edges))
    touched_out = np.concatenate([touched[kept], np.ones(len(edges), bool)])
    for i in range(len(cross)):
        for v in tri[i]:
            if kept[v]:
                touched_out[new_index[v]] = True
    out = Prim(positions=positions, faces=faces_out, attributes=attributes, joints=joints_out, weights=weights_out,
               targets=targets, joint_names=list(prim.joint_names))
    return out, stats, touched_out


def apply_cut(prim: Prim, cut: Dict[str, Any], joints: Dict[str, np.ndarray]) -> Tuple[Prim, Dict[str, Any]]:
    """``prim`` with the cut applied for every side of ``cut`` (module docstring: conform, then removal and
    bisection, then the normals of touched vertices), and the stats ``{removed_faces, bisected_faces,
    new_vertices, slim_share: {side}, throat_moved: {side}}``. ``joints`` = ``glb_mesh.joint_bind_matrices`` of the
    body the primitive belongs to. ValueError when the body lacks a side's joints."""
    out, info = conform_body(prim, cut, joints)
    touched = info["touched"]
    stats: Dict[str, Any] = {"removed_faces": 0, "bisected_faces": 0, "new_vertices": 0,
                             "slim_share": info["slim_share"], "slim_needed": info["slim_station_max"],
                             "throat_moved": info["throat_moved"], "toe_conform": info["toe_conform"],
                             "toe_pull": info["toe_pull"], "sides": {}}
    for name, desc in (cut.get("sides") or {}).items():
        out, st, touched = _cut_side(out, desc, joints, touched)
        stats["sides"][name] = dict(st)
        for key in ("removed_faces", "bisected_faces", "new_vertices"):
            stats[key] += st[key]
    if "NORMAL" in out.attributes and touched.any():
        N = out.attributes["NORMAL"]
        _recompute_normals(out.positions, out.faces, N, np.nonzero(touched)[0])
    return out, stats


# --- gates ----------------------------------------------------------------------------------------------------------

def _voxel_surface(Sc: np.ndarray, SF: np.ndarray, lo: np.ndarray, shape: np.ndarray) -> np.ndarray:
    """The shoe surface as voxels, dilated once (watertight at ``VOXEL_M``). Every triangle is sampled on a
    barycentric grid fine enough for its longest edge (half a voxel), so a long thin triangle of a coarse mesh
    leaves no hole — the spike's fixed 15 samples assume the mesher's tiny triangles."""
    from scipy import ndimage
    surf = np.zeros(shape, bool)
    tri = Sc[SF]
    edge = np.max(np.stack([np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1), np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
                            np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)]), axis=0)
    n = np.clip(np.ceil(edge / (0.5 * VOXEL_M)).astype(int), 1, 1024)
    for steps in np.unique(n):
        sel = tri[n == steps]
        i_idx, j_idx = np.meshgrid(np.arange(steps + 1), np.arange(steps + 1), indexing="ij")
        keep = (i_idx + j_idx) <= steps
        u = (i_idx[keep] / steps)[None, :, None]
        v = (j_idx[keep] / steps)[None, :, None]
        p = (sel[:, 0:1] * (1 - u - v) + sel[:, 1:2] * u + sel[:, 2:3] * v).reshape(-1, 3)
        i = np.clip(np.round((p - lo) / VOXEL_M).astype(int), 0, shape - 1)
        surf[i[:, 0], i[:, 1], i[:, 2]] = True
    return ndimage.binary_dilation(surf)


def _side_gates(desc: Dict[str, Any], joints: Dict[str, np.ndarray], before: Prim, after: Prim,
                shoe: glb_mesh.GarmentMesh, raw: Prim) -> Dict[str, Any]:
    """The spike's voxel metrics for one side (module docstring), spike axes (x, lateral, up); ``before`` = the
    conformed bare body, ``raw`` = the bare body as it came (the toes against the vamp are read there)."""
    from scipy import ndimage
    from scipy.spatial import cKDTree
    side = _Side(desc)
    mb, ma = _Map(desc, joints, before), _Map(desc, joints, after)
    fb = mb.foot > FOOT_WEIGHT_MIN
    fa = ma.foot > FOOT_WEIGHT_MIN
    Fb = mb.to_cut(np.asarray(before.positions, np.float64))[fb][:, [0, 2, 1]]
    Fa = ma.to_cut(np.asarray(after.positions, np.float64))[fa][:, [0, 2, 1]]
    Fr = mb.to_cut(np.asarray(raw.positions, np.float64))[fb][:, [0, 2, 1]]
    # the shoe: bind -> posed by its own Foot / ToeBase weights -> cut frame
    w = np.asarray(shoe.weights, np.float64)[:, 1:2]
    Sb = np.asarray(shoe.positions, np.float64)
    Sc = ((1.0 - w) * _apply(mb.Tf, Sb) + w * _apply(mb.Tt, Sb))[:, [0, 2, 1]]
    SF = np.asarray(shoe.indices, np.int64).reshape(-1, 3)
    pts = [Sc, Fb] + ([Fa] if len(Fa) else [])
    lo = np.min([p.min(0) for p in pts], axis=0) - 0.01
    hi = np.max([p.max(0) for p in pts], axis=0) + 0.01
    shape = np.ceil((hi - lo) / VOXEL_M).astype(int) + 1
    surf = _voxel_surface(Sc, SF, lo, shape)
    sx = np.round((Sc[:, 0] - lo[0]) / VOXEL_M).astype(int)
    wt = np.full(shape[0], -1.0)
    ylo = np.zeros(shape[0])
    yhi = np.zeros(shape[0])
    for ixs in np.unique(sx):
        q = Sc[sx == ixs]
        l, rr = q[q[:, 1] > SIDE_WALL_M, 2], q[q[:, 1] < -SIDE_WALL_M, 2]
        if len(l) and len(rr):
            wt[ixs] = min(l.max(), rr.max())
            ylo[ixs], yhi[ixs] = q[:, 1].min(), q[:, 1].max()
    good = wt > 0
    idxg = np.nonzero(good)[0]
    if not len(idxg):
        raise ValueError("The shoe has no side walls to cap")
    ar = np.arange(shape[0])
    wt = np.interp(ar, idxg, wt[good])
    ylo = np.interp(ar, idxg, ylo[good])
    yhi = np.interp(ar, idxg, yhi[good])
    roof = (float(side.throat["x"]), side.x_max) if side.throat else None
    cap = np.zeros(shape, bool)
    wz = np.round((wt - lo[2]) / VOXEL_M).astype(int)
    for ixs in range(int(idxg.min()), int(idxg.max()) + 1):
        xm = lo[0] + ixs * VOXEL_M
        if roof and roof[0] <= xm <= roof[1]:
            continue
        nb = [wz[j] for j in (ixs - 1, ixs, ixs + 1) if 0 <= j < shape[0]]
        z0, z1 = min(nb) - 1, max(nb) + 1
        j0, j1 = int((ylo[ixs] - lo[1]) / VOXEL_M), int((yhi[ixs] - lo[1]) / VOXEL_M) + 1
        cap[ixs, max(0, j0):j1, max(0, z0):z1 + 1] = True
    free = ~(surf | cap)
    lab, _ = ndimage.label(free)
    exterior = lab == lab[0, 0, 0]
    edt = ndimage.distance_transform_edt(~surf) * VOXEL_M

    def vox(Fc: np.ndarray) -> np.ndarray:
        return np.clip(np.round((Fc - lo) / VOXEL_M).astype(int), 0, shape - 1)

    def should_of(Fc: np.ndarray, fi: np.ndarray) -> np.ndarray:
        return (Fc[:, 2] < wt[fi[:, 0]] - SHOULD_MARGIN_M) & (Fc[:, 0] > Sc[:, 0].min() - HEEL_SLACK_M)

    heel_x = desc.get("stations", {}).get("heel_x")
    ball_x = desc.get("stations", {}).get("ball_x")
    heel_x = float(heel_x) if heel_x is not None else float(Sc[:, 0].min())
    ball_x = float(ball_x) if ball_x is not None else 0.5 * (heel_x + float(Sc[:, 0].max()))

    def regions(Fc: np.ndarray) -> np.ndarray:
        return np.where(Fc[:, 0] > ball_x, "toe", np.where(Fc[:, 0] < heel_x + HEEL_REGION_M, "heel", "mid"))

    # before the cut, after the conform: deep pokes of the should-enclosed set
    fi = vox(Fb)
    outside = exterior[fi[:, 0], fi[:, 1], fi[:, 2]] & ~surf[fi[:, 0], fi[:, 1], fi[:, 2]]
    should = should_of(Fb, fi)
    poke = should & outside
    depth = edt[fi[:, 0], fi[:, 1], fi[:, 2]]
    deep = poke & (depth > DEEP_M)
    n_should = int(should.sum())
    reg = regions(Fb)
    # after the cut: what remains below the rim (the cut's own cap, station-exact: a cut-edge vertex sits ON
    # it; the voxel wall top is a slab maximum and reads a steep topline 2–3 mm high) and farther than the
    # same margin from the footprint's wall (a vertex on the seam where the foot exits through the wall is
    # the cut surface, not a leftover; the spike's own ``outside`` ignored the dilated surface likewise) — i.e.
    # left inside the shoe or poking through its wall; then the overhang and the throat ledge
    fa_i = vox(Fa) if len(Fa) else np.zeros((0, 3), int)
    if len(Fa):
        lat_a = np.maximum(side.zlo(Fa[:, 0]) - Fa[:, 1], Fa[:, 1] - side.zhi(Fa[:, 0]))
        below_a = (Fa[:, 2] < side.cap(Fa[:, 0]) - SHOULD_MARGIN_M) & (Fa[:, 0] > Sc[:, 0].min() - HEEL_SLACK_M)
        should_a = below_a & (np.abs(lat_a) > SHOULD_MARGIN_M)
    else:
        below_a = should_a = np.zeros(0, bool)
    should_vox_a = should_of(Fa, fa_i) if len(Fa) else np.zeros(0, bool)
    out_a = (exterior[fa_i[:, 0], fa_i[:, 1], fa_i[:, 2]] & ~surf[fa_i[:, 0], fa_i[:, 1], fa_i[:, 2]]) if len(Fa) \
        else np.zeros(0, bool)
    vis = ~should_a
    band = vis & (Fa[:, 2] < wt[fa_i[:, 0]] + OVERHANG_BAND_M) if len(Fa) else np.zeros(0, bool)
    lat_out = np.maximum(Fa[:, 1] - yhi[fa_i[:, 0]], ylo[fa_i[:, 0]] - Fa[:, 1]) if len(Fa) else np.zeros(0)
    over = band & (lat_out > OVERHANG_M)
    ledge = step20 = toe_above = 0.0
    vamp_left = 0
    if side.throat:
        xt = float(side.throat["x"])
        # the toes against the vamp: how far the forefoot stands above the vamp's surface before the cut
        # (neither gate sees a toe ABOVE the upper), and what the cut left in front of the throat
        fore = Fr[:, 0] >= xt
        fr_i = vox(Fr)
        toe_above = float(max(0.0, (Fr[fore, 2] - wt[fr_i[fore, 0]]).max() * 1000.0)) if fore.any() else 0.0
        vamp_left = int((Fa[:, 0] >= xt).sum()) if len(Fa) else 0
    if side.throat and len(Fa):
        vz = wt[int(np.clip(round((xt - lo[0]) / VOXEL_M), 0, shape[0] - 1))]
        in_lat = (Fa[:, 1] > ylo[fa_i[:, 0]]) & (Fa[:, 1] < yhi[fa_i[:, 0]])
        near = vis & in_lat & (Fa[:, 0] >= xt - THROAT_LEDGE_BAND_M) & (Fa[:, 0] < xt)
        wide = vis & in_lat & (Fa[:, 0] >= xt - THROAT_STEP_BAND_M) & (Fa[:, 0] < xt)
        ledge = float(max(0.0, np.percentile(Fa[near, 2] - vz, 95) * 1000.0)) if near.any() else 0.0
        step20 = float(max(0.0, np.percentile(Fa[wide, 2] - vz, 95) * 1000.0)) if wide.any() else 0.0
    # diagnostics: rim gap (topline -> nearest foot vertex, before), arch gap (lowest foot vertex per cell -> surface)
    topline = np.asarray(desc.get("topline") or np.zeros((0, 3)), np.float64).reshape(-1, 3)
    rim = topline[:, [0, 2, 1]] if len(topline) else np.zeros((0, 3))
    rim_d = cKDTree(Fb).query(rim)[0] if len(rim) and len(Fb) else np.zeros(0)
    cell = np.floor(Fb[:, :2] / ARCH_CELL_M).astype(np.int64)
    order = np.lexsort((Fb[:, 2], cell[:, 1], cell[:, 0]))
    keys = cell[order]
    first = np.concatenate([[True], np.any(np.diff(keys, axis=0) != 0, axis=1)]) if len(keys) else np.zeros(0, bool)
    low_ids = order[first]
    arch = depth[low_ids] * 1000.0 if len(low_ids) else np.zeros(0)
    pct = lambda a, p: float(np.percentile(a, p)) if len(a) else None  # noqa: E731
    return {
        "deep_outside": float(deep.sum() / n_should) if n_should else 0.0,
        "should_enclosed": n_should, "poke_n": int(poke.sum()), "deep_n": int(deep.sum()),
        "poke_depth_p95_mm": float(np.percentile(depth[poke], 95) * 1000.0) if poke.any() else 0.0,
        "poke_by_region": {g: int((deep & (reg == g)).sum()) for g in ("heel", "mid", "toe")},
        "should_by_region": {g: int((should & (reg == g)).sum()) for g in ("heel", "mid", "toe")},
        "foot_vertices_before": int(len(Fb)),
        "visible_poke": float(should_a.sum() / len(Fa)) if len(Fa) else 0.0,
        "visible_n": int(len(Fa)), "visible_poke_n": int(should_a.sum()),
        "visible_below_rim_n": int(below_a.sum()), "visible_below_rim_outside_n": int((below_a & out_a).sum()),
        "visible_below_voxel_rim_n": int(should_vox_a.sum()),
        "throat_ledge_p95_mm": ledge, "throat_step_20mm_p95_mm": step20,
        "toe_above_vamp_max_mm": toe_above, "vamp_left_n": vamp_left,
        "overhang_share_of_band": float(over.sum() / band.sum()) if band.any() else 0.0,
        "overhang_p95_mm": float(np.percentile(lat_out[over], 95) * 1000.0) if over.any() else 0.0,
        "rim_gap_p50_mm": None if not len(rim_d) else pct(rim_d, 50) * 1000.0,
        "rim_gap_p95_mm": None if not len(rim_d) else pct(rim_d, 95) * 1000.0,
        "arch_gap_edt_p50_mm": pct(arch, 50), "arch_gap_edt_p95_mm": pct(arch, 95),
        "hidden_share_of_foot": float(should.mean()) if len(Fb) else 0.0,
    }


def cut_gates(body_after: Prim, shoes: Dict[str, glb_mesh.GarmentMesh], cut: Dict[str, Any], *,
              joints: Dict[str, np.ndarray], body_before: Prim) -> Dict[str, Any]:
    """The cut's gates (module docstring): ``{"ok", "reasons", "gates": {name: {value, limit, ok}}, "sides": {side:
    diagnostics}}``. ``body_before`` is the primitive ``apply_cut`` started from (bare); ``deep_outside`` is read on
    it after the conform, the rest on ``body_after``; ``shoes`` = the fit's bind-space shoes; ``joints`` =
    ``glb_mesh.joint_bind_matrices`` of the body."""
    before, cinfo = conform_body(body_before, cut, joints)
    sides: Dict[str, Any] = {}
    for name, desc in (cut.get("sides") or {}).items():
        shoe = shoes.get(name)
        if shoe is None:
            raise ValueError(f"No shoe for the {name} side")
        sides[name] = _side_gates(desc, joints, before, body_after, shoe, body_before)
        sides[name]["toe_conform_m"] = float(cinfo["toe_conform"].get(name, 0.0))
        sides[name]["toe_pull_m"] = float(cinfo["toe_pull"].get(name, 0.0))
    metrics = {key: max(s[key] for s in sides.values()) if sides else None for key in CUT_GATES}
    table = {name: (kind, limit, GATE_LABELS[name]) for name, (kind, limit) in CUT_GATES.items()}
    ok, reasons = check_gates(metrics, table)
    gates = {name: {"value": metrics[name], "limit": limit,
                    "ok": check_gates({name: metrics[name]}, {name: (kind, limit, GATE_LABELS[name])})[0]}
             for name, (kind, limit) in CUT_GATES.items()}
    return {"ok": ok, "reasons": reasons, "gates": gates, "sides": sides}
