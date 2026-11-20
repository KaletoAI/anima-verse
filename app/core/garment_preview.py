"""A188 — the template dialog's picture overlay: a template piece drawn ON the character's plain base-body front.

The server computes, the client draws (CLAUDE.md): ``overlay(character, params)`` returns the piece as polygons in
the PIXELS of the base front picture, so every slider of the dialog moves something on the person.

Two halves:

* **Registration** (``picture_frame`` + ``register``): the base front is an RGBA cut-out (the figure on a transparent
  ground). Its silhouette gives the head top and the feet bottom rows, the body centre column and, per row, how far
  the body reaches either side of the centre; the plain base MODEL (``garment_template.measure_body``, the same
  measurements the drape is cut from) gives the heights in metres. A metre height maps to a pixel row linearly
  (``floor_y`` -> the feet row, ``floor_y + height`` -> the head-top row), the same scale serves x (square pixels).
  The arms are NOT taken from the model: the picture stands in an A-pose while the model is T-posed, so an arm's
  axis is the shoulder joint's pixel (model x / height) to the hand tip found in the silhouette.
* **Drawing** (``shapes``): the piece's heights and girths come from ``garment_template.outline`` / ``bodice_spec``
  (what the drape uses, a jacket's layer allowance over a draped sleeved layer included: ``over_sleeves``); a
  girth becomes a front width through the body's own silhouette at that height (garment girth / body girth x the
  body's half width in the picture) — so a fit of 0 hugs the body in the picture and the flare widens the hem from
  the hip width. Every option is drawn the way its builder makes it (bug round 2026-11-20, "bei Körbchen sieht vieles
  ähnlich aus"): the neckline along the builder's meridians (``neckline_geometry``), the collar rings
  (``collar_geometry``), the bra's cups / gore / push-up / straps (``bra_geometry``), gloves with their cuffs
  (``glove_geometry``), the bands and open feet of hosiery, a stirrup, a brief's back line. The builder-only numbers
  are mirrored below and checked against the builder source (``scripts/smoke_garment_preview_options.py``).

Nothing is generated or stored; the picture analysis and the body measurement are cached per file (path + mtime).
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Alpha above this is the figure.
ALPHA_MIN = 128
#: Rows either side averaged when the body's half width is read at a height (the cut-out edge is ragged).
ROW_SMOOTH = 3
#: The neckline's round exponent — ``garment_template_build.NECK_ROUND_POW`` (crew / scoop / boat).
NECK_ROUND_POW = 1.4
#: Points per curve (hem, neckline).
CURVE_N = 24
#: A sleeve starts this far back from the shoulder joint along the arm (it covers the shoulder cap).
SLEEVE_BACK_M = 0.04

# --- the builder's own numbers -------------------------------------------------------------------------------------
# The Blender builders cannot be imported here (bpy), so the values the drawing needs are MIRRORED below, each named
# after its source; ``scripts/smoke_garment_preview_options.py`` reads them back out of the builder files (AST /
# source) and fails when one drifts. Spec decides, the drawing follows.
#: ``garment_template_build.NECK_RING_UP_M``: the neck opening is the body's section this far above the neck joint.
NECK_RING_UP_M = 0.02
#: ``garment_template_build.CAP_MIN_M``: the yoke reaches at least this far outward from the neck opening.
CAP_MIN_M = 0.03
#: ``garment_template_build.COLLAR_RINGS`` x ``COLLAR_STEP_M``: a collar (stand AND lapel) is this many rings this far
#: apart above the neck rim, each ``COLLAR_SHRINK`` of the one below round the neck axis.
COLLAR_RINGS = 3
COLLAR_STEP_M = 0.012
COLLAR_SHRINK = 0.97
#: ``garment_template_build.COLLAR_CUT_MAX_M``: the collar runs only where the neckline is cut less than this.
COLLAR_CUT_MAX_M = 0.03
#: ``garment_template_fitted.bra_region``: a cup reaches ``r_out`` outward from its apex; a triangle's rim ends this
#: far over the underbust line; no cup top lies lower than ``CUP_TOP_MIN_M`` over it; the gore is ``GORE_EXTRA_M``
#: wider than its half width either side; a strap starts ``STRAP_START_IN_M`` outward of the apex and
#: ``STRAP_START_DROP_M`` under the cup top; a halter runs to ``HALTER_NECK_SHARE`` of the neck radius.
CUP_R_OUT_M = 0.075
TRIANGLE_RIM_M = 0.015
CUP_TOP_MIN_M = 0.01
GORE_EXTRA_M = 0.004
STRAP_START_IN_M = 0.005
#: ``garment_template_fitted.CLOSURE_HALF_M``: a back hook takes the band this far either side of the spine.
CLOSURE_HALF_M = 0.025
STRAP_START_DROP_M = 0.01
HALTER_NECK_SHARE = 0.9
#: ``garment_template_fitted._apex``: the apex is the foremost body point 3 .. 17 cm out from the centre, between the
#: underbust line and 8 cm over the bust line (fallback 9 cm out, on the bust line).
APEX_X_M = (0.03, 0.17)
APEX_UP_M = 0.08
APEX_FALLBACK_X_M = 0.09
#: ``garment_template_fitted.FOLD_SCAN_M`` / ``FOLD_STEP_M`` (``_fold``: the breast's fold under the apex).
FOLD_SCAN_M = 0.14
FOLD_STEP_M = 0.004
#: ``garment_template_fitted.tights_region`` / ``trousers_region``: an open foot is cut this far under the ankle
#: joint; a stirrup keeps a band this far either side of the middle of the foot.
FOOT_CUT_M = 0.01
STIRRUP_HALF_M = 0.025
#: ``garment_template.panel_spec``: the front panel's hem curve sags ``dip`` x 200 cm at the centre (dip 0.01).
SKIRT_HEM_DIP_M = 0.02
#: A top's hem (its torso rows end on one height) — a slight curve, only so it reads as a hem.
TOP_HEM_DIP_M = 0.008

# --- drawing-only estimates (no builder number exists for these) ---------------------------------------------------
#: Fingerless gloves leave the finger-weighted faces: the knuckles lie this share of the way from the wrist to the
#: hand tip (the palm); without a hand tip in the picture the hand is HAND_LEN_M long.
PALM_SHARE = 0.5
HAND_LEN_M = 0.18
#: A stirrup's band reaches this share of the way from the floor up to the ankle joint (the instep, seen from the front).
INSTEP_SHARE = 0.65
#: The torso's half depth at the shoulder line is solved from its girth and half width (an ellipse), clamped here.
TORSO_DEPTH_M = (0.06, 0.16)

_lock = threading.Lock()
_frames: Dict[Tuple[str, int], Dict[str, Any]] = {}
_measures: Dict[Tuple[str, int], Dict[str, Any]] = {}


# --- registration ------------------------------------------------------------------------------------------------

def silhouette(image) -> Any:
    """The figure mask (bool rows x cols) of a PIL image: alpha when the picture carries a cut-out, else every pixel
    that differs from the corner colour by more than 40 (a plain grey ground)."""
    import numpy as np
    rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[:, :, 3]
    if alpha.min() < ALPHA_MIN:
        return alpha >= ALPHA_MIN
    rgb = rgba[:, :, :3].astype(int)
    corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    ground = np.median(corners, axis=0)
    return np.abs(rgb - ground).sum(axis=2) > 40


def frame_of_mask(mask) -> Dict[str, Any]:
    """``{w, h, top_px, feet_px, mask}`` of a figure mask: the first and the last row holding figure pixels."""
    import numpy as np
    rows = np.where(mask.any(axis=1))[0]
    if not len(rows):
        raise ValueError("the picture shows no figure")
    return {"w": int(mask.shape[1]), "h": int(mask.shape[0]), "top_px": int(rows[0]), "feet_px": int(rows[-1]) + 1,
            "mask": mask}


def picture_frame(path: Path) -> Dict[str, Any]:
    """``frame_of_mask`` of the picture at ``path``, cached by path + mtime."""
    from PIL import Image
    key = (str(path), Path(path).stat().st_mtime_ns)
    with _lock:
        hit = _frames.get(key)
    if hit is not None:
        return hit
    with Image.open(path) as im:
        frame = frame_of_mask(silhouette(im))
    with _lock:
        _frames.clear()
        _frames[key] = frame
    return frame


def body_measure(glb: Path) -> Dict[str, Any]:
    """``garment_template.measure_body`` of the plain base model at ``glb`` plus the hip / leg joints, cached."""
    from app.core import garment_template as gt
    from app.core import glb_mesh
    key = (str(glb), Path(glb).stat().st_mtime_ns)
    with _lock:
        hit = _measures.get(key)
    if hit is not None:
        return hit
    data = Path(glb).read_bytes()
    meas = gt.measure_body(data)
    joints = glb_mesh.body_arrays(data).joint_positions
    extra = {k: [round(float(x), 4) for x in joints[k]] for k in ("hips", "leftupleg", "rightupleg", "leftleg",
                                                                  "rightleg", "leftfoot", "rightfoot", "head") if k in joints}
    meas = dict(meas, joints={**(meas.get("joints") or {}), **extra})
    if "shoulder_y" in meas and "spine1" in joints:
        meas.update(bra_landmarks(glb_mesh.body_arrays(data).positions, joints["spine1"], meas))
    with _lock:
        _measures.clear()
        _measures[key] = meas
    return meas


def bra_landmarks(P, spine1, meas: Dict[str, Any]) -> Dict[str, Any]:
    """The bra builder's body landmarks read off the plain model's vertices ``P`` (glTF Y-up, front = +z), by the rules
    of ``garment_template_fitted``: ``bra_apex`` {"1": [x, y, z], "-1": …} per side (``_apex``: the foremost point
    ``APEX_X_M`` out from the centre — the Spine1 joint — between the underbust line and ``APEX_UP_M`` over the bust
    line) and ``bra_fold`` [y, …] (``_fold``: going down from each apex in ``FOLD_STEP_M`` steps, the front surface's
    depth at the apex's x; the first height after the steepest recession where it recedes less than a fifth as fast;
    the builder casts rays, the vertices within half a step of the ray stand in for them here)."""
    import numpy as np
    from app.core import garment_template as gt
    under, bust = gt._bust_lines(meas)
    cx, cz = float(spine1[0]), float(spine1[2])
    apex: Dict[str, List[float]] = {}
    folds: List[float] = []
    for s in (1, -1):
        dx = s * (P[:, 0] - cx)
        m = (dx > APEX_X_M[0]) & (dx < APEX_X_M[1]) & (P[:, 2] > cz) & (P[:, 1] > under) & (P[:, 1] < bust + APEX_UP_M)
        if m.any():
            a = P[np.where(m)[0][int(np.argmax(P[m, 2]))]]
            apex[str(s)] = [round(float(v), 4) for v in a]
        else:
            apex[str(s)] = [round(cx + s * APEX_FALLBACK_X_M, 4), round(bust, 4), round(cz + 0.1, 4)]
            continue
        near = P[(np.abs(P[:, 0] - a[0]) < FOLD_STEP_M) & (P[:, 2] > cz)]
        zs, depth = [], []
        for k in range(int(round(FOLD_SCAN_M / FOLD_STEP_M))):
            y = float(a[1]) - FOLD_STEP_M * (k + 1)
            sl = near[np.abs(near[:, 1] - y) < FOLD_STEP_M / 2]
            if len(sl):
                zs.append(y)
                depth.append(-float(sl[:, 2].max()))
        if len(depth) < 5:
            continue
        d = np.diff(depth)
        k = int(np.argmax(d))
        if d[k] < 0.004:
            continue
        for i in range(k + 1, len(d)):
            if d[i] < 0.2 * d[k]:
                folds.append(round(zs[i], 4))
                break
    return {"bra_apex": apex, "bra_fold": folds}


def _runs(row) -> List[Tuple[int, int]]:
    """The figure runs of one mask row: ``[(start, end_exclusive)]``."""
    import numpy as np
    d = np.diff(np.r_[0, row.astype(np.int8), 0])
    return list(zip(np.where(d == 1)[0].tolist(), np.where(d == -1)[0].tolist()))


class Registration:
    """Metres (model x, Y-up) <-> picture pixels, and the body's extent in the picture.

    ``px(x, y)``: pixel of a model point — row = feet_px - (y - floor_y) * scale, column = cx_px + (x - x0) * scale,
    scale = (feet_px - top_px) / height px per metre; ``x0`` = the model's centre (hips / neck joints), ``cx_px`` =
    the picture's body centre (median centre of the run under the image middle between the hip and the chest band)."""

    def __init__(self, frame: Dict[str, Any], meas: Dict[str, Any]):
        import numpy as np
        self.frame, self.meas = frame, meas
        self.mask = frame["mask"]
        self.top, self.feet = frame["top_px"], frame["feet_px"]
        self.floor, self.height = float(meas["floor_y"]), float(meas["height"])
        j = meas.get("joints") or {}
        xs = [j[k][0] for k in ("hips", "neck") if k in j]
        self.x0 = float(sum(xs) / len(xs)) if xs else 0.0
        cam = frame.get("camera")
        #: A195: a picture rendered with a known camera (``front_camera``) maps metres EXACTLY; the silhouette only
        #: gives the body's extent then.
        self.exact = cam is not None
        if cam is not None:
            from app.core import front_camera
            self.scale = float(cam["ppm"])
            self._xref, self._col0 = float(cam["cx"]), cam["w"] / 2.0
            self._feet_f = front_camera.to_px(cam, 0.0, self.floor)[1]
            self.cx = self._col0 + (self.x0 - self._xref) * self.scale
            return
        self.scale = (self.feet - self.top) / self.height
        self._feet_f = float(self.feet)
        centres = []
        guess = frame["w"] / 2.0
        for y in np.arange(meas["hip_y"], meas["band_y"], 0.02):
            r = self.row(float(y))
            run = self._run_at(r, guess)
            if run:
                centres.append((run[0] + run[1]) / 2.0)
        self.cx = float(np.median(centres)) if centres else guess
        self._xref, self._col0 = self.x0, self.cx

    # metres <-> pixels
    def row(self, y: float) -> int:
        return int(round(min(self.feet - 1, max(self.top, self._feet_f - (y - self.floor) * self.scale))))

    def px(self, x: float, y: float) -> List[float]:
        return [round(self._col0 + (x - self._xref) * self.scale, 1),
                round(self._feet_f - (y - self.floor) * self.scale, 1)]

    def metres(self, col: float, row: float) -> Tuple[float, float]:
        return (col - self._col0) / self.scale + self._xref, (self._feet_f - row) / self.scale + self.floor

    def joint_arm_axis(self, side: int) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """A195: on an exactly mapped render (the model's own T-pose) the arm IS the model's: shoulder joint ->
        hand joint (``(root, unit direction)``); None on the A-posed base picture or without the joints."""
        j = self.meas.get("joints") or {}
        a, h = ("leftarm", "lefthand") if side > 0 else ("rightarm", "righthand")
        if not self.exact or a not in j or h not in j:
            return None
        dx, dy = j[h][0] - j[a][0], j[h][1] - j[a][1]
        n = math.hypot(dx, dy)
        if n < 1e-6:
            return None
        return (j[a][0], self.meas["shoulder_y"]), (dx / n, dy / n)

    def _run_at(self, r: int, col: float) -> Optional[Tuple[int, int]]:
        for a, b in _runs(self.mask[r]):
            if a <= col < b:
                return a, b
        return None

    def body_half(self, y: float, cap_m: float) -> Tuple[float, float]:
        """The body's reach (metres) to the left (-x, image left) and the right (+x) of the centre at height ``y``,
        the median over ``ROW_SMOOTH`` rows either side. The run under the centre; between the legs (no run there)
        the outer edges of the two runs nearest the centre. Capped at ``cap_m`` (an A-posed arm can touch the body)."""
        import numpy as np
        lefts, rights = [], []
        r0 = self.row(y)
        for r in range(max(self.top, r0 - ROW_SMOOTH), min(self.feet, r0 + ROW_SMOOTH + 1)):
            runs = _runs(self.mask[r])
            run = self._run_at(r, self.cx)
            if run:
                a, b = run
            else:
                left = [q for q in runs if q[1] <= self.cx]
                right = [q for q in runs if q[0] >= self.cx]
                if not left or not right:
                    continue
                a, b = left[-1][0], right[0][1]
            lefts.append((self.cx - a) / self.scale)
            rights.append((b - self.cx) / self.scale)
        if not lefts:
            return cap_m * 0.5, cap_m * 0.5
        return min(cap_m, float(np.median(lefts))), min(cap_m, float(np.median(rights)))

    def leg_run(self, y: float, x_guess: float) -> Optional[Tuple[float, float]]:
        """One leg's extent (metres x, from - to) at height ``y``: the run under ``x_guess``, else the nearest."""
        r = self.row(y)
        col = self.cx + (x_guess - self.x0) * self.scale
        runs = _runs(self.mask[r])
        if not runs:
            return None
        a, b = min(runs, key=lambda q: 0 if q[0] <= col < q[1] else min(abs(q[0] - col), abs(q[1] - col)))
        return self.metres(a, r)[0], self.metres(b, r)[0]

    def hand_tip(self, side: int) -> Optional[Tuple[float, float]]:
        """The hand tip (metres) on ``side`` (+1 = +x / image right, -1): the outermost figure pixel between the
        shoulder row and the knee row; of several equally far out, the lowest."""
        import numpy as np
        r0 = self.row(self.meas["shoulder_y"])
        r1 = self.row(self.floor + 0.28 * self.height)
        sub = self.mask[r0:r1]
        cols = np.where(sub.any(axis=0))[0]
        if not len(cols):
            return None
        col = int(cols.max()) if side > 0 else int(cols.min())
        rows = np.where(sub[:, col])[0]
        return self.metres(col + (0.5 if side > 0 else -0.5), r0 + int(rows.max()))

    def arm_axis(self, side: int, shoulder: Tuple[float, float]) -> Optional[Tuple[Tuple[float, float],
                                                                               Tuple[float, float]]]:
        """The arm's centre line in the picture on ``side``: the centres of the outermost figure run (the arm, apart
        from the body) at 35 % and 65 % of the way down from the shoulder to the hand tip -> ``(root, u)``: the
        line's point at the shoulder joint's height and the unit direction towards the hand. None when the arm
        never stands apart from the body."""
        tip = self.hand_tip(side)
        if tip is None:
            return None
        pts = []
        for share in (0.35, 0.65):
            y = shoulder[1] + (tip[1] - shoulder[1]) * share
            r = self.row(y)
            runs = _runs(self.mask[r])
            if len(runs) < 2:
                continue
            a, b = runs[-1] if side > 0 else runs[0]
            if (side > 0 and a <= self.cx) or (side < 0 and b >= self.cx):
                continue
            pts.append(self.metres((a + b) / 2.0, r))
        if len(pts) < 2:
            d = (tip[0] - shoulder[0], tip[1] - shoulder[1])
            n = math.hypot(*d) or 1.0
            return shoulder, (d[0] / n, d[1] / n)
        (xa, ya), (xb, yb) = pts
        n = math.hypot(xb - xa, yb - ya) or 1.0
        u = ((xb - xa) / n, (yb - ya) / n)
        if abs(u[1]) < 1e-6:
            return (xa, ya), u
        t = (shoulder[1] - ya) / u[1]
        return (xa + u[0] * t, shoulder[1]), u

    def landmarks(self) -> Dict[str, List[float]]:
        """Pixel positions of the model's key heights on the centre line (and the shoulder joints)."""
        m = self.meas
        out = {"head_top": self.px(self.x0, self.floor + self.height), "feet": self.px(self.x0, self.floor),
               "neck": self.px(self.x0, m["neck_y"]), "shoulders": self.px(self.x0, m["shoulder_y"]),
               "chest_band": self.px(self.x0, m["band_y"]), "waist": self.px(self.x0, m["waist_y"]),
               "hips": self.px(self.x0, m["hip_y"])}
        j = m.get("joints") or {}
        for k in ("leftarm", "rightarm", "leftupleg", "rightupleg", "leftfoot", "rightfoot"):
            if k in j:
                out[k] = self.px(j[k][0], j[k][1])
        return out


def register(frame: Dict[str, Any], meas: Dict[str, Any]) -> Registration:
    return Registration(frame, meas)


# --- drawing -----------------------------------------------------------------------------------------------------

def _girth_at(meas: Dict[str, Any], y: float) -> float:
    """The body's girth at ``y``: the torso profile above the hip line, the hip girth below it (a skirt hangs from
    the hips)."""
    from app.core import garment_template as gt
    return gt._torso_girth(meas, max(y, meas["hip_y"])) if meas.get("torso") else float(meas["hip_c"])


def _side_points(reg: Registration, meas: Dict[str, Any], knots: List[Tuple[float, float]], hem_y: float,
                 cap_m: float) -> Tuple[List[List[float]], List[List[float]]]:
    """The two side contours (metres) of a piece whose girth runs ``knots`` [(metres above the hem, girth)]: at each
    knot the body's half width in the picture at that height (the hip's below the hip line) x garment / body girth."""
    left, right = [], []
    for h, c in knots:
        y = hem_y + h
        yb = max(y, meas["hip_y"])
        # above the hips an A-posed arm can touch the body: no wider than the girth's front share
        cap = cap_m if yb <= meas["hip_y"] else min(cap_m, _girth_at(meas, yb) / math.pi * 0.52 + 0.005)
        bl, br = reg.body_half(yb, cap)
        k = c / max(1e-6, _girth_at(meas, y))
        left.append([reg.x0 - bl * k, y])
        right.append([reg.x0 + br * k, y])
    return left, right


def _hem_curve(left: List[float], right: List[float], dip: float) -> List[List[float]]:
    """The hem from the right corner to the left one, sagging ``dip`` metres at the centre (a flared hem seen from
    the front)."""
    out = []
    for i in range(CURVE_N + 1):
        t = i / CURVE_N
        x = right[0] + (left[0] - right[0]) * t
        y = right[1] + (left[1] - right[1]) * t - dip * math.sin(math.pi * t)
        out.append([x, y])
    return out


def neckline_curve(neckline: str, x0: float, half_w: float, top_y: float, bottom_y: float) -> List[List[float]]:
    """The neckline seen from the front (metres), from the right rim (x0 + half_w, top_y) down to the centre at
    ``bottom_y`` and up to the left rim. The builder's cut rule: a meridian at angle a from the front is cut over
    cos(a)^1.4 (crew / scoop / boat) or 1 - |sin a| (V) of the centre's cut; seen from the front x = half_w sin a."""
    out = []
    for i in range(CURVE_N + 1):
        s = 1.0 - 2.0 * i / CURVE_N            # sin a: +1 (right rim) .. -1 (left rim)
        share = (1.0 - abs(s)) if neckline == "v" else max(0.0, 1.0 - s * s) ** (NECK_ROUND_POW / 2.0)
        out.append([x0 + half_w * s, top_y - (top_y - bottom_y) * share])
    return out


def _ellipse_r(a: float, w: float, d: float) -> float:
    """The radius at angle ``a`` from the front of an ellipse ``w`` wide and ``d`` deep (half axes)."""
    return 1.0 / math.sqrt((math.sin(a) / w) ** 2 + (math.cos(a) / d) ** 2)


def torso_depth(m: Dict[str, Any]) -> float:
    """The torso's half depth at the shoulder line: the ellipse of half width ``shoulder_w`` / 2 whose perimeter
    (Ramanujan) is the torso girth there, clamped to ``TORSO_DEPTH_M`` (the yoke's outer end in the drawing)."""
    from app.core import garment_template as gt
    w = float(m.get("shoulder_w", 0.38)) / 2.0
    c = gt._torso_girth(m, float(m["shoulder_y"]))
    lo, hi = TORSO_DEPTH_M
    a, b = lo, min(hi, w)
    for _ in range(40):
        d = (a + b) / 2
        per = math.pi * (3 * (w + d) - math.sqrt((3 * w + d) * (w + 3 * d)))
        a, b = (d, b) if per < c else (a, d)
    return round(max(lo, min(hi, w, (a + b) / 2)), 4)


def neckline_geometry(spec: Dict[str, Any], m: Dict[str, Any], x0: float) -> Dict[str, Any]:
    """The bodice's neckline seen from the front (metres), as ``garment_template_build`` cuts it (A179 / Ruling A144):

    * every column is a MERIDIAN from the neck rim out over the yoke to the shoulder line and down the torso rows; the
      rim lies on the ring ``neck_r`` round the neck at ``neck_y + NECK_RING_UP_M`` beside and behind the neck and
      comes down to the jugular notch (``front_y`` = the shoulder joints' height) at the front centre (the builder
      lays the rim on the surface; drawn here as front_y + (ring - front_y) x sin^2 of the angle from the front);
    * the yoke runs out to the torso's shoulder-line section (an ellipse ``shoulder_w`` / 2 x ``torso_depth``, at
      least ``CAP_MIN_M`` past the ring) at the notch height at the front and the shoulder line's top (``top_y``) at
      the sides, then the meridian runs straight down;
    * the front-centre meridian is cut over the arc length ``s_front`` to ``front_y - depth``; a meridian at angle a
      over ``s_front`` x cos(a)^NECK_ROUND_POW (crew / scoop / boat) or x (1 - |sin a|) (V); under 2 mm no cut.

    -> ``{edge (right rim .. left rim, CURVE_N + 1 points), rim, cut_s (per point), s_front, bottom_y, r_ring, z_ring,
    angles}``. A cut of 0 everywhere (a boat neck: its depth 0 ends at the notch) leaves the edge on the rim."""
    neckline = spec["neckline"]
    depth = float(spec["depth_m"])
    r_ring = float(spec["neck_r"])
    z_ring = float(m["neck_y"]) + NECK_RING_UP_M
    front_y = float(spec.get("front_y") or m["shoulder_y"])
    top_y = float(spec["top_y"])
    w = float(m.get("shoulder_w", 0.38)) / 2.0
    d = torso_depth(m) if m.get("torso") else 0.1
    angles, edge, rim, cut_s = [], [], [], []
    # the front-centre rim lies at the notch: a depth of 0 is reached there already (no cut, the rim is the edge)
    s_front = max(d, r_ring + CAP_MIN_M) - r_ring + depth if depth > 0 else 0.0
    for i in range(CURVE_N + 1):
        sn = 1.0 - 2.0 * i / CURVE_N            # sin a: +1 (right rim) .. -1 (left rim)
        a = math.asin(sn)
        share = (1.0 - abs(sn)) if neckline == "v" else max(0.0, 1.0 - sn * sn) ** (NECK_ROUND_POW / 2.0)
        sc = s_front * share
        sc = sc if sc >= 0.002 else 0.0
        z_rim = front_y + (z_ring - front_y) * sn * sn
        z_out = front_y + (top_y - front_y) * sn * sn
        r_out = max(_ellipse_r(a, w, d), r_ring + CAP_MIN_M)
        yoke = math.hypot(r_out - r_ring, z_rim - z_out)
        if sc <= yoke:
            t = sc / max(1e-9, yoke)
            pt = [x0 + (r_ring + t * (r_out - r_ring)) * sn, z_rim + t * (z_out - z_rim)]
        else:
            pt = [x0 + r_out * sn, z_out - (sc - yoke)]
        angles.append(a)
        edge.append(pt)
        rim.append([x0 + r_ring * sn, z_rim])
        cut_s.append(sc)
    return {"edge": edge, "rim": rim, "cut_s": cut_s, "s_front": s_front, "bottom_y": front_y - depth,
            "r_ring": r_ring, "z_ring": z_ring, "front_y": front_y, "angles": angles,
            "cut": any(c > 0 for c in cut_s)}


def collar_geometry(neck: Dict[str, Any], x0: float) -> Dict[str, Any]:
    """A collar (``stand`` and ``lapel`` alike, ``garment_template_build``): ``COLLAR_RINGS`` rings ``COLLAR_STEP_M``
    apart above the neck rim, each ``COLLAR_SHRINK`` of the one below round the neck axis — only over the columns
    whose neckline cut is at most ``COLLAR_CUT_MAX_M`` (it ends where the neckline runs down the front). -> ``{front:
    [polygons over the front half's qualifying runs], back: the ring's top behind the neck (a guide), height_m}``."""
    h = COLLAR_RINGS * COLLAR_STEP_M
    k = COLLAR_SHRINK ** COLLAR_RINGS
    runs, cur = [], []
    for pt, sc in zip(neck["edge"], neck["cut_s"]):
        if sc <= COLLAR_CUT_MAX_M:
            cur.append(pt)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    polys = []
    for run in runs:
        if len(run) < 2:
            continue
        top = [[x0 + (x - x0) * k, y + h] for x, y in run]
        polys.append(run + top[::-1])
    r = neck["r_ring"]
    back = [[x0 + r * k, neck["z_ring"] + h], [x0 - r * k, neck["z_ring"] + h]]
    return {"front": polys, "back": back, "height_m": round(h, 4)}


def top_edge_curve(x0: float, right: List[float], left: List[float], depth: float,
                   half_rad: Optional[float] = None) -> List[List[float]]:
    """A231: a corset top's sweetheart top edge seen from the front (metres), from the right rim ``right`` to the
    left rim ``left`` (both at the band height). A point at angle a round from the front centre lies at
    x = x0 +- half_w * sin(a) and ``garment_template.sweetheart_drop(depth, a)`` under the band."""
    from app.core import garment_template as gt
    half = gt.SWEETHEART_HALF_RAD if half_rad is None else half_rad
    out = []
    for i in range(CURVE_N + 1):
        s = 1.0 - 2.0 * i / CURVE_N            # sin a: +1 (right rim) .. -1 (left rim)
        rim = right if s >= 0 else left
        out.append([x0 + (rim[0] - x0) * abs(s), rim[1] - gt.sweetheart_drop(depth, math.asin(min(1.0, abs(s))), half)])
    return out


def _quad_along(a: Tuple[float, float], u: Tuple[float, float], start: float, end: float, w0: float,
                w1: float) -> List[List[float]]:
    """A band along the axis from ``a`` in direction ``u`` (unit), from ``start`` to ``end`` metres, ``w0`` / ``w1``
    wide at either end."""
    n = (-u[1], u[0])
    p0 = (a[0] + u[0] * start, a[1] + u[1] * start)
    p1 = (a[0] + u[0] * end, a[1] + u[1] * end)
    return [[p0[0] + n[0] * w0 / 2, p0[1] + n[1] * w0 / 2], [p1[0] + n[0] * w1 / 2, p1[1] + n[1] * w1 / 2],
            [p1[0] - n[0] * w1 / 2, p1[1] - n[1] * w1 / 2], [p0[0] - n[0] * w0 / 2, p0[1] - n[1] * w0 / 2]]


def shapes(params: Dict[str, Any], meas: Dict[str, Any], reg: Registration, *,
           over_sleeves: bool = False) -> Dict[str, Any]:
    """The piece on the picture: ``{shapes: [{role, kind (fill | cut | line | dash), points (px)}], marks: [{x, y,
    text, anchor}], landmarks}``. ``fill`` = cloth, ``cut`` = an opening in the cloth (neckline, open front, slit),
    ``line`` / ``dash`` = a guide (the waist line chosen, a dimension). Marks carry the numbers: hem height, length,
    sleeve length, neckline depth, slit depth. ``over_sleeves``: the drape cuts the piece over a draped sleeved layer
    (``garment_template.layer_ease``, bug round 2026-11-20) — drawn the same way."""
    from app.core import garment_template as gt
    p = params
    m = meas
    kind = p["kind"]
    out: List[Dict[str, Any]] = []
    marks: List[Dict[str, Any]] = []
    x0 = reg.x0
    half_sh = m.get("shoulder_w", 0.38) / 2.0
    cap_m = max(half_sh + 0.03, m["hip_c"] / math.pi * 0.62)

    def add(role: str, kind_: str, pts: List[List[float]]) -> None:
        out.append({"role": role, "kind": kind_, "points": [reg.px(x, y) for x, y in pts]})

    def mark(x: float, y: float, text: str, anchor: str = "start") -> None:
        q = reg.px(x, y)
        marks.append({"x": q[0], "y": q[1], "text": text, "anchor": anchor})

    waist_y = gt._waist_line(p, m)
    # the waist line chosen (skirt / trousers / dress): a dashed guide across the body
    if kind in ("skirt", "dress"):
        bl, br = reg.body_half(waist_y, cap_m)
        add("waist", "dash", [[x0 - bl - 0.03, waist_y], [x0 + br + 0.03, waist_y]])
        mark(x0 + br + 0.04, waist_y, f"waist {p['waist_height']}")

    if kind == "trousers":
        _trousers(p, m, reg, cap_m, add, mark)
        return {"shapes": out, "marks": marks}
    if kind in gt.FITTED_KINDS:
        _fitted(p, m, reg, cap_m, add, mark)
        return {"shapes": out, "marks": marks}

    shape = gt.outline(p, m, over_sleeves=over_sleeves)
    knots = shape["knots"]
    top_y = shape["top_y"]
    hem_y = top_y - knots[-1][0]
    left, right = _side_points(reg, m, knots, hem_y, cap_m)
    bodice = gt.has_bodice(p)
    spec = gt.bodice_spec(p, m, over_sleeves=over_sleeves) if bodice and "shoulder_y" in m else None
    dip = SKIRT_HEM_DIP_M if kind in ("skirt", "dress") else TOP_HEM_DIP_M
    hem = _hem_curve(left[0], right[0], dip)
    # the outline: up the right side, across the top, down the left side, along the hem
    if spec is None:
        if gt.strapless_top(p) and p["neckline"] == "sweetheart":
            # A231: the strapless top edge dips at the front centre (the drape's ``top_drop``)
            depth = gt.sweetheart_depth(p)
            edge = top_edge_curve(x0, right[-1], left[-1], depth)
            add("body", "fill", right[:-1] + edge + left[:-1][::-1] + hem[::-1][1:-1])
            add("top_edge", "line", edge)
            mark(x0 + 0.02, right[-1][1] - depth, f"sweetheart −{round(depth * 100)} cm")
        else:
            add("body", "fill", right + left[::-1] + hem[::-1][1:-1])
    else:
        sy = m["shoulder_y"]
        neck = neckline_geometry(spec, m, x0)

        def neck_cut(below: float) -> None:
            """The neckline as an opening of a piece cut below its top (straps: the band, off-shoulder: the line) —
            only where the cut reaches under that top (above it there is no cloth to open)."""
            if neck["cut"] and neck["bottom_y"] < below:
                add("neck", "cut", neck["edge"] + neck["rim"][::-1])
                add("neck_edge", "line", neck["edge"])
                neck_mark()

        def neck_mark() -> None:
            depth = spec["depth_m"]
            mark(x0 + neck["r_ring"] + 0.02, neck["bottom_y"] if neck["cut"] else neck["front_y"],
                 f"{_neck_name(spec['neckline'])} −{round(depth * 100)} cm" if neck["cut"]
                 else f"{_neck_name(spec['neckline'])} · no cut")
        if p["shoulders"] == "straps" and kind in ("dress", "top"):
            # the bodice ends at the chest band; above it only the straps (the neckline's cut still applies)
            band = spec["band_y"]
            r_cut = [q for q in right if q[1] <= band] + [_at(right, band)]
            l_cut = [q for q in left if q[1] <= band] + [_at(left, band)]
            te = spec.get("top_edge") or {}
            if te.get("dip_m"):
                # A231: the band's sweetheart dip round the front centre (the builder's ``top_edge`` cut)
                edge = top_edge_curve(x0, r_cut[-1], l_cut[-1], te["dip_m"], te["half_rad"])
                add("body", "fill", r_cut[:-1] + edge + l_cut[:-1][::-1] + hem[::-1][1:-1])
                add("top_edge", "line", edge)
                mark(x0 + 0.02, band - te["dip_m"], f"sweetheart −{round(te['dip_m'] * 100)} cm")
            else:
                add("body", "fill", r_cut + l_cut[::-1] + hem[::-1][1:-1])
            for sgn in (1, -1):
                sx = x0 + sgn * spec["strap_x"]
                w = spec["strap_w"] / 2
                add("strap", "fill", [[sx - w, band], [sx + w, band], [sx + w, top_y], [sx - w, top_y]])
            mark(x0 + spec["strap_x"] + 0.03, top_y - 0.03, "straps")
            if not te:
                neck_cut(band)
        elif spec.get("off_shoulder"):
            _off_shoulder(p, m, reg, spec, right, left, hem, add, mark)
            neck_cut(spec["off_shoulder"]["line_y"])
        else:
            body_r = [q for q in right if q[1] < sy - 0.02]
            body_l = [q for q in left if q[1] < sy - 0.02]
            sh_r, sh_l = [x0 + half_sh, sy + 0.01], [x0 - half_sh, sy + 0.01]
            yk_r = [x0 + 0.5 * (half_sh + neck["r_ring"]), top_y]
            yk_l = [x0 - 0.5 * (half_sh + neck["r_ring"]), top_y]
            # the body's top edge IS the neckline (the cloth ends there)
            add("body", "fill", body_r + [sh_r, yk_r] + neck["edge"] + [yk_l, sh_l] + body_l[::-1] + hem[::-1][1:-1])
            # the sleeves along the picture's arm axis (the picture is A-posed, the model T-posed)
            if spec["sleeve"]:
                _sleeves(p, m, reg, spec, add, mark)
            add("neck_edge", "line", neck["edge"])
            neck_mark()
            if spec["collar"] in ("stand", "lapel"):
                col = collar_geometry(neck, x0)
                for poly in col["front"]:
                    add("collar", "fill", poly)
                add("collar_edge", "dash", col["back"])
                mark(x0 - neck["r_ring"] - 0.02, neck["z_ring"] + col["height_m"],
                     f"{spec['collar']} collar {round(col['height_m'] * 100, 1)} cm" + (" · revers painted"
                                                                                         if spec["collar"] == "lapel"
                                                                                         else ""), "end")
            if spec["front_open"]:
                # the builder leaves the seam between the two front columns open (no gap): the fronts' edge
                add("front_edge", "line", [[x0, neck["bottom_y"]], [x0, hem_y - 0.004]])
                mark(x0 + 0.01, (neck["bottom_y"] + hem_y) / 2, "open front")
    # the slit (from the hem up)
    if kind in ("skirt", "dress") and p.get("slit", "none") != "none" and p.get("slit_m", 0) > 0:
        s = p["slit"]
        top_s = hem_y + p["slit_m"]
        if s in ("left", "right"):
            side = right if s == "left" else left
            edge = _at(side, top_s)
            hx = side[0][0]
            inward = -1.0 if s == "left" else 1.0
            # a V opening along the side seam: wide at the hem, closed at the slit's top
            add("slit", "cut", [[hx - inward * 0.04, hem_y - 0.03], [hx + inward * 0.06, hem_y - 0.03],
                                [edge[0] + inward * 0.004, top_s], [edge[0] - inward * 0.012, top_s + 0.004]])
            mark(hx + (0.02 if s == "left" else -0.02), top_s, f"slit {round(p['slit_m'] * 100)} cm",
                 "start" if s == "left" else "end")
        else:
            w = 0.035 if s == "front" else 0.0
            if s == "front":
                add("slit", "cut", [[x0 - w, hem_y - dip - 0.02], [x0 + w, hem_y - dip - 0.02], [x0, top_s]])
            else:
                add("slit", "dash", [[x0, hem_y - dip], [x0, top_s]])
            mark(x0 + 0.03, top_s, f"slit {s} {round(p['slit_m'] * 100)} cm")
    # the dimension: the length beside the piece, the hem height under it
    outer = max(q[0] for q in right) + 0.06
    dim_top = waist_y if kind in ("skirt", "dress") else top_y
    add("dim", "line", [[outer, dim_top], [outer, hem_y]])
    add("dim", "line", [[outer - 0.015, dim_top], [outer + 0.015, dim_top]])
    add("dim", "line", [[outer - 0.015, hem_y], [outer + 0.015, hem_y]])
    # bug round 2026-11-20 review: a hem moved off the underbust fold (``gt._clear_underbust``) is drawn where the drape
    # puts it, so the label gives the length draped and the length asked, and the hem mark says why it moved
    moved = shape.get("hem_moved")
    if moved:
        mark(outer + 0.012, (dim_top + hem_y) / 2,
             f"{round(moved['draped_length_m'] * 100)} cm (asked {round(moved['length_m'] * 100)})")
        mark(x0, hem_y - dip - 0.035, f"hem {hem_y:.2f} m · moved below the underbust fold", "middle")
    else:
        mark(outer + 0.012, (dim_top + hem_y) / 2, f"{round(p['length_m'] * 100)} cm")
        mark(x0, hem_y - dip - 0.035, f"hem {hem_y:.2f} m", "middle")
    mark(x0, hem_y - dip - 0.075, _fit_text(p, kind), "middle")
    return {"shapes": out, "marks": marks}


def _neck_name(n: str) -> str:
    return {"v": "V-neck", "crew": "crew", "scoop": "scoop", "boat": "boat"}.get(n, n)


def _fit_text(p: Dict[str, Any], kind: str) -> str:
    if kind in ("skirt",):
        return f"flare {p['flare']:.2f} · {p['fabric']}"
    if kind == "dress":
        return f"flare {p['flare']:.2f} · fit {p['fit']:.2f} · {p['fabric']}"
    return f"fit {p['fit']:.2f} · {p['fabric']}"


def _at(side: List[List[float]], y: float) -> List[float]:
    """The side contour's x at height ``y`` (linear between its points)."""
    for a, b in zip(side, side[1:]):
        if (a[1] - y) * (b[1] - y) <= 0 and a[1] != b[1]:
            t = (y - a[1]) / (b[1] - a[1])
            return [a[0] + t * (b[0] - a[0]), y]
    return [side[-1][0], y]


def _sleeves(p, m, reg: Registration, spec, add, mark) -> None:
    sleeve = spec["sleeve"]
    rings = sleeve["rings"]
    j = m.get("joints") or {}
    for side, key in ((1, "leftarm"), (-1, "rightarm")):
        if key not in j:
            continue
        axis = reg.joint_arm_axis(side) or reg.arm_axis(side, (j[key][0], m["shoulder_y"]))
        ja, u = axis if axis else ((j[key][0], m["shoulder_y"]), (float(side), 0.0))
        w0 = rings[0][1] / math.pi
        w1 = rings[-1][1] / math.pi
        length = sleeve["len_m"]
        # the upper side of the arm (the perpendicular that points up)
        up = (-u[1], u[0])
        if up[1] < 0:
            up = (-up[0], -up[1])
        end = (ja[0] + u[0] * length, ja[1] + u[1] * length)
        shoulder_pt = [reg.x0 + side * m.get("shoulder_w", 0.38) / 2.0, m["shoulder_y"] + 0.01]
        armpit = [ja[0] - up[0] * w0 / 2 - u[0] * SLEEVE_BACK_M, ja[1] - up[1] * w0 / 2 - u[1] * SLEEVE_BACK_M]
        add("sleeve", "fill", [shoulder_pt, [end[0] + up[0] * w1 / 2, end[1] + up[1] * w1 / 2],
                               [end[0] - up[0] * w1 / 2, end[1] - up[1] * w1 / 2], armpit])
        if side > 0:
            mark(end[0] + w1 / 2 + 0.015, end[1], f"{p['sleeves']} sleeve {round(length * 100)} cm · fit "
                                                   f"{p['sleeve_fit']:.2f}")


def _off_shoulder(p, m, reg: Registration, spec, right, left, hem, add, mark) -> None:
    """A229: an off-shoulder piece — the body cut at the band's top edge (``line_y``), the sleeves as a covered
    bodice's with the shoulder cap above the line taken away up to where the band crosses the arm, the band as a
    dashed guide ``band_m`` under the edge, and the front lacing as an opening from the band down."""
    off = spec["off_shoulder"]
    x0 = reg.x0
    line, band = off["line_y"], off["band_m"]
    half_sh = m.get("shoulder_w", 0.38) / 2.0
    r_cut = [q for q in right if q[1] <= line] + [_at(right, line)]
    l_cut = [q for q in left if q[1] <= line] + [_at(left, line)]
    add("body", "fill", r_cut + l_cut[::-1] + hem[::-1][1:-1])
    if spec["sleeve"]:
        _sleeves(p, m, reg, spec, add, mark)
    # the band crosses each upper arm ``arm_out_m`` out from its shoulder joint (``_off_arm_lat``)
    j = m.get("joints") or {}
    lat = {sgn: (abs(float(j[k][0]) - x0) if k in j else half_sh - 0.04) + off["arm_out_m"]
           for sgn, k in ((1, "leftarm"), (-1, "rightarm"))}
    # the shoulders above the band stay bare (an opening over the sleeves' caps)
    add("shoulders", "cut", [[x0 - lat[-1], line], [x0 + lat[1], line], [x0 + lat[1], line + 0.12],
                             [x0 - lat[-1], line + 0.12]])
    add("band_edge", "line", [[x0 - lat[-1], line], [x0 + lat[1], line]])
    add("band", "dash", [[x0 - lat[-1], line - band], [x0 + lat[1], line - band]])
    mark(x0 + lat[1] + 0.02, line, f"off-shoulder band {round(band * 100, 1)} cm")
    lace = off.get("lace")
    if lace:
        # the builder takes the centre front within gap / 2 from the band down ``depth_m`` (a straight opening)
        g = lace["gap_m"] / 2
        bottom = line - lace["depth_m"]
        add("lacing", "cut", [[x0 - g, line + 0.004], [x0 + g, line + 0.004], [x0 + g, bottom], [x0 - g, bottom]])
        mark(x0 + g + 0.02, bottom, f"lacing −{round(lace['depth_m'] * 100)} cm")


def briefs_back_line(p: Dict[str, Any], spec: Dict[str, Any], crotch: float, top: float,
                     hip: Tuple[float, float], x0: float) -> List[List[float]]:
    """The back panel's leg line seen through the body (metres, left hip -> right hip), ``briefs_region``'s back
    ``leg_line``: the back is ``w_back`` = g 0.4 + back_coverage x 0.9 (hip_half - g 0.4) wide at the crotch and
    climbs as t^power to the side's height — under full coverage within 3 cm past its width (a string / Brazilian)."""
    g = float(spec["gusset_half_m"])
    lc, bc = float(p["leg_cut"]), float(p["back_coverage"])
    hip_half = 0.5 * (hip[0] + hip[1])
    base = crotch - 0.005
    w_back = g * 0.4 + bc * 0.9 * (hip_half - g * 0.4)
    power = 1.6 - 1.2 * lc
    if spec.get("sides") == "string":
        side = top - float(spec["string_width_m"])
        reach = w_back + (hip_half - w_back) * float(spec["string_corner"][0])
    else:
        low = crotch - float(spec["boyshort_drop_m"])
        side = low + lc * (top - float(spec["side_width_m"]) - low)
        reach = hip_half
    pts = []
    for i in range(CURVE_N + 1):
        ax = hip_half * abs(1.0 - 2.0 * i / CURVE_N)
        t = min(1.0, max(0.0, (ax - w_back) / max(reach - w_back, 1e-3)))
        rise = t ** power
        if bc < 0.999:
            rise = max(rise, min(1.0, max(0.0, (ax - w_back) / 0.03)) * (1.0 - bc) ** 0.5)
        pts.append([x0 + (ax if i < CURVE_N / 2 else -ax), base + (side - base) * rise])
    return pts[::-1]


def _crotch_y(m: Dict[str, Any]) -> float:
    """A223: the crotch height for the drawing — 6 cm under the hip joints (the builder reads it off the mesh)."""
    j = m.get("joints") or {}
    if "leftupleg" in j:
        return float(j["leftupleg"][1]) - 0.06
    return float(m["hip_y"]) - 0.09


def _fitted(p, m, reg: Registration, cap_m: float, add, mark) -> None:
    """A223: the fitted kinds, drawn from the same numbers the builder cuts by (``garment_template.fitted_spec``):
    briefs from the waistband over the leg openings (``leg_cut`` shapes the curve, ``side_width_m`` the side) to the
    gusset; a bra's band, its two cups to their top edge and the straps; gloves along the arm to their reach."""
    from app.core import garment_template as gt
    x0 = reg.x0
    spec = gt.fitted_spec(p, m)["fitted"]
    kind = p["kind"]
    if kind == "briefs" and spec.get("leg_length_m"):
        _boxers(p, m, reg, spec, cap_m, add, mark)
        return
    if kind == "briefs":
        top = spec["top_y"]
        crotch = _crotch_y(m)
        bl, br = reg.body_half(top, cap_m)
        g = spec["gusset_half_m"]
        low = crotch - spec["boyshort_drop_m"]
        side = low + p["leg_cut"] * (top - p["side_width_m"] - low)
        power = 1.6 - 1.2 * p["leg_cut"]
        leg_r, leg_l = [], []
        for t in [i / 8 for i in range(9)]:
            y = crotch + (side - crotch) * t ** power
            leg_r.append([x0 + g + (br - g) * t, y])
            leg_l.append([x0 - g - (bl - g) * t, y])
        if spec.get("sides") == "string":
            # A235: the front panel to its top corners, then only the hip bands ``string_width_m`` high to the sides
            sw = spec["string_width_m"]
            c_min, c_span = spec["string_corner"]
            share = c_min + c_span * (1.0 - p["leg_cut"])
            leg_r, leg_l = [], []
            for t in [i / 8 for i in range(9)]:
                y = crotch + (top - sw - crotch) * t ** power
                leg_r.append([x0 + g + (br - g) * share * t, y])
                leg_l.append([x0 - g - (bl - g) * share * t, y])
            add("body", "fill", [[x0 - g - (bl - g) * share, top], [x0 + g + (br - g) * share, top]]
                + leg_r[::-1] + leg_l)
            add("band", "fill", [[x0 + g + (br - g) * share, top], [x0 + br, top], [x0 + br, top - sw],
                                 [x0 + g + (br - g) * share, top - sw]])
            add("band", "fill", [[x0 - g - (bl - g) * share, top], [x0 - bl, top], [x0 - bl, top - sw],
                                 [x0 - g - (bl - g) * share, top - sw]])
            add("back_edge", "dash", briefs_back_line(p, spec, crotch, top, reg.body_half(m["hip_y"], cap_m), x0))
            mark(x0 + br + 0.03, top, f"rise {p['rise']} · string {round(sw * 1000)} mm")
            mark(x0, crotch - 0.04, f"back {p['back_coverage']:.2f} · {p['fabric']}", "middle")
            return
        add("body", "fill", [[x0 - bl, top], [x0 + br, top]] + leg_r[::-1] + leg_l)
        add("back_edge", "dash", briefs_back_line(p, spec, crotch, top, reg.body_half(m["hip_y"], cap_m), x0))
        if spec["waistband_m"] > 0:
            add("waist", "dash", [[x0 - bl, top - spec["waistband_m"]], [x0 + br, top - spec["waistband_m"]]])
        mark(x0 + br + 0.03, top, f"rise {p['rise']}")
        mark(x0 + br + 0.03, side, f"leg cut {p['leg_cut']:.2f}")
        mark(x0, crotch - 0.04, f"back {p['back_coverage']:.2f} · {p['fabric']}", "middle")
        return
    if kind == "bra":
        _bra(p, m, reg, spec, cap_m, add, mark)
        return
    if kind == "tights":
        _tights(p, m, reg, spec, cap_m, add, mark)
        return
    _gloves(p, m, reg, spec, add, mark)


def _arm_width(m: Dict[str, Any], d: float) -> float:
    """The arm's front width ``d`` metres from the shoulder joint: its girth (``arm_c``, interpolated along the arm
    as the sleeves read it) / pi."""
    import numpy as np
    arm_len = float(m.get("arm_len") or 0.55)
    ac = m.get("arm_c") or [[0.25, m.get("upper_arm_c") or 0.28], [0.97, m.get("wrist_c") or 0.16]]
    return float(np.interp(d / arm_len, [a for a, _c in ac], [c for _a, c in ac])) / math.pi


def glove_geometry(p: Dict[str, Any], m: Dict[str, Any], spec: Dict[str, Any], hand_len: float) -> Dict[str, Any]:
    """One glove along its arm axis (metres from the shoulder joint, half widths across): the cuff edge at ``arm_len -
    reach_m``, the wrist at ``arm_len``; the arm's half width (``_arm_width``) + ``offset_m``; a flared cuff stands
    ``cuff_flare_m`` x near_edge^2 further out over its last ``cuff_m`` (a folded one ``cuff_fold_m``) — the builder's
    offsets; the hand to the tip (full), to the knuckles (fingerless, ``PALM_SHARE``) or none.
    -> ``{start, wrist, tip, stations: [(d, half width)], fold_at}``."""
    arm_len = float(m.get("arm_len") or 0.55)
    start = arm_len - float(spec["reach_m"])
    off = float(spec["offset_m"])
    stations = []
    n = 10
    for i in range(n + 1):
        d = start + (arm_len - start) * i / n
        extra = 0.0
        if spec["cuff"] != "none":
            near = min(1.0, max(0.0, 1.0 - (d - start) / float(spec["cuff_m"])))
            extra = float(spec["cuff_flare_m"]) * near ** 2 if spec["cuff"] == "flared" else \
                float(spec["cuff_fold_m"]) * (near > 0)
        stations.append((d, _arm_width(m, d) / 2 + off + extra))
    fingers = spec["fingers"]
    tip = arm_len + (hand_len if fingers == "full" else PALM_SHARE * hand_len if fingers == "fingerless" else 0.0)
    return {"start": start, "wrist": arm_len, "tip": tip, "stations": stations,
            "fold_at": start + float(spec["cuff_m"]) if spec["cuff"] == "folded" else None}


def _gloves(p, m, reg: Registration, spec: Dict[str, Any], add, mark) -> None:
    """A223 gloves on the picture from ``glove_geometry`` along each arm's axis; a folded cuff's fold and a flared
    cuff's edge as lines, a fingerless glove's knuckle edge."""
    j = m.get("joints") or {}
    for side, key, hand in ((1, "leftarm", "lefthand"), (-1, "rightarm", "righthand")):
        if key not in j or hand not in j:
            continue
        axis = reg.joint_arm_axis(side) or reg.arm_axis(side, (j[key][0], m["shoulder_y"]))
        ja, u = axis if axis else ((j[key][0], m["shoulder_y"]), (float(side), 0.0))
        tipm = reg.hand_tip(side) if hasattr(reg, "hand_tip") else None
        arm_len = float(m.get("arm_len") or 0.55)
        hand_len = HAND_LEN_M
        if tipm is not None:
            along = (tipm[0] - ja[0]) * u[0] + (tipm[1] - ja[1]) * u[1] - arm_len
            if 0.08 < along < 0.3:
                hand_len = along
        g = glove_geometry(p, m, spec, hand_len)
        nrm = (-u[1], u[0])

        def at(d, w):
            return [ja[0] + u[0] * d + nrm[0] * w, ja[1] + u[1] * d + nrm[1] * w]
        st = g["stations"]
        add("glove", "fill", [at(d, w) for d, w in st] + [at(d, -w) for d, w in st[::-1]])
        if g["tip"] > g["wrist"]:
            wr = st[-1][1]
            add("glove", "fill", [at(g["wrist"], wr * 1.25), at(g["tip"], wr * 1.1), at(g["tip"], -wr * 1.1),
                                  at(g["wrist"], -wr * 1.25)])
            if p["fingers"] == "fingerless":
                add("glove_edge", "line", [at(g["tip"], wr * 1.1), at(g["tip"], -wr * 1.1)])
        if g["fold_at"] is not None:
            w = min(st, key=lambda q: abs(q[0] - g["fold_at"]))[1]
            add("cuff_edge", "line", [at(g["fold_at"], w), at(g["fold_at"], -w)])
        if p["cuff"] == "flared":
            add("cuff_edge", "line", [at(st[0][0], st[0][1]), at(st[0][0], -st[0][1])])
        if side > 0:
            end = at(g["start"], 0.0)
            mark(end[0], end[1] + 0.05, f"{p['length']} · {p['fingers']} · cuff {p['cuff']} · fit {p['fit']:.2f}",
                 "middle")


def bra_geometry(p: Dict[str, Any], m: Dict[str, Any], spec: Dict[str, Any], x0: float) -> Dict[str, Any]:
    """A bra seen from the front (metres), as ``garment_template_fitted.bra_region`` cuts it — no picture involved:

    * ``under`` = the spec's underbust line, raised to the lowest breast fold the body shows (``bra_fold``);
    * per side the apex (``bra_apex``, else ``APEX_FALLBACK_X_M`` out on the bust line), H = max(3 cm, apex - under),
      zc = apex + (coverage - 0.5) x 2H; the cup runs from the gore (centre ± ``gore_half``, at most ``r_in`` = |apex
      - centre| - gore_half (>= 2 cm) inside the apex) to ``CUP_R_OUT_M`` outside it; its top over u = |x - apex| / r:
      molded zc - H/2 u^2 (a dome), triangle peak - (peak - (under + ``TRIANGLE_RIM_M``)) u with peak = zc + 0.8H,
      balconette zc (straight); never under under + ``CUP_TOP_MIN_M``; bandeau: one band from under to the higher zc;
    * the push-up moves every cup point ``push`` x (``PUSH_LIFT_M`` up, ``PUSH_IN_M`` to the centre; ``push_m`` of
      the spec, the builder's ``push`` weights) — the cup's lower edge stays joined to the band;
    * the gore: |x - centre| < gore_half + ``GORE_EXTRA_M`` from under to under + gore_h (none for a bandeau);
    * a strap starts ``STRAP_START_IN_M`` outward of the apex, ``STRAP_START_DROP_M`` under the cup top there (before
      the push) and runs to the shoulder at ``shoulder_x`` (halter: to ``HALTER_NECK_SHARE`` x the neck radius at
      ``neck_y``); on the back it runs down to the band at ``back_x`` (cross: the other side).

    -> ``{under, band_bottom, cups: {s: [[x, y]] top edge inner -> outer then the bottom}, tops: {s: [[x, y]]}, plain_tops
    (before the push), gore, straps: {s: {front, back}}, apex, zc}``."""
    from app.core import garment_template as gt
    under = float(spec["under_y"])
    folds = m.get("bra_fold") or []
    if folds:
        under = max(under, min(folds))
    band = max(float(spec["band_m"]), float(spec["back_strap_m"]))
    style = spec["style"]
    cov = float(spec["coverage"])
    gore_half, gore_h = float(spec["gore_half_m"]), float(spec["gore_h_m"])
    push = float(spec["push"])
    lift, pull = gt.PUSH_LIFT_M, gt.PUSH_IN_M
    apexes = m.get("bra_apex") or {}
    out: Dict[str, Any] = {"under": under, "band_bottom": under - band, "cups": {}, "tops": {}, "plain_tops": {},
                           "apex": {}, "zc": {}, "straps": {}, "gore": None}
    tops = {}
    for sgn in (1, -1):
        a = apexes.get(str(sgn))
        ax, ay = (float(a[0]), float(a[1])) if a else (x0 + sgn * APEX_FALLBACK_X_M, float(spec["bust_y"]))
        H = max(0.03, ay - under)
        zc = ay + (cov - 0.5) * 2.0 * H
        r_in = max(0.02, abs(ax - x0) - gore_half)
        tops[sgn] = (ax, ay, H, zc, r_in)
        out["apex"][sgn] = [ax, ay]
        out["zc"][sgn] = zc

    def cup_top(x: float, sgn: int) -> float:
        ax, _ay, H, zc, r_in = tops[sgn]
        dx = x - ax
        r = r_in if sgn * dx < 0 else CUP_R_OUT_M
        u = min(1.0, abs(dx) / r)
        if style == "molded":
            z = zc - 0.5 * H * u * u
        elif style == "triangle":
            peak = zc + 0.8 * H
            z = peak - (peak - (under + TRIANGLE_RIM_M)) * u
        else:
            z = zc
        return max(z, under + CUP_TOP_MIN_M)

    if style == "bandeau":
        out["band_top"] = max(t[3] for t in tops.values())
    else:
        for sgn in (1, -1):
            ax, _ay, H, zc, r_in = tops[sgn]
            inner = x0 + sgn * max(gore_half, abs(ax - x0) - r_in)
            outer = ax + sgn * CUP_R_OUT_M
            xs = [inner + (ax - inner) * i / (CURVE_N // 2) for i in range(CURVE_N // 2)] + \
                 [ax + (outer - ax) * i / (CURVE_N // 2) for i in range(CURVE_N // 2 + 1)]
            plain = [[x, cup_top(x, sgn)] for x in xs]
            moved = [[x - sgn * push * pull, y + push * lift] for x, y in plain]
            out["plain_tops"][sgn] = plain
            out["tops"][sgn] = moved
            # the cup's lower edge row is the band's top row too: it moves with the cup and the band's faces stretch
            # up to it — drawn closed down to the underbust line (no gap where the cloth stays one piece)
            out["cups"][sgn] = moved + [[outer - sgn * push * pull, under], [inner, under]]
        if gore_h > 0:
            g = gore_half + GORE_EXTRA_M
            out["gore"] = [[x0 - g, under], [x0 + g, under], [x0 + g, under + gore_h], [x0 - g, under + gore_h]]
    st = spec.get("straps")
    if st and "shoulder_y" in m:
        for sgn in (1, -1):
            ax = tops[sgn][0]
            z0 = (out["band_top"] if style == "bandeau" else cup_top(ax, sgn)) - STRAP_START_DROP_M
            start = [ax + sgn * STRAP_START_IN_M, z0]
            if st["style"] == "halter":
                end = [x0 + sgn * float(st["neck_r"]) * HALTER_NECK_SHARE, float(st["neck_y"])]
                back = None
            else:
                end = [x0 + sgn * float(st["shoulder_x"]), float(m["shoulder_y"]) + 0.04]
                back = [end, [x0 + sgn * float(st["back_x"]), under]]
            out["straps"][sgn] = {"front": [start, end], "back": back, "width": float(st["width_m"])}
    return out


def _bra(p, m, reg: Registration, spec: Dict[str, Any], cap_m: float, add, mark) -> None:
    """A223: the bra on the picture from ``bra_geometry`` — the band, the cups (a bandeau's band), the gore, the
    push-up's move (the cup's top before it as a dashed guide), the straps (front as cloth, the back run as a dashed
    guide — a cross shows as an X), the front closure."""
    x0 = reg.x0
    g = bra_geometry(p, m, spec, x0)
    under, bottom = g["under"], g["band_bottom"]
    bl, br = reg.body_half(under, cap_m)
    add("band", "fill", [[x0 - bl, bottom], [x0 + br, bottom], [x0 + br, under], [x0 - bl, under]])
    if p["cup_style"] == "bandeau":
        # a tube round the chest: as wide as the body at the underbust line (higher up the arm joins the outline)
        add("cup", "fill", [[x0 - bl, under], [x0 + br, under], [x0 + br, g["band_top"]], [x0 - bl, g["band_top"]]])
        add("cup_edge", "line", [[x0 - bl, g["band_top"]], [x0 + br, g["band_top"]]])
    else:
        # a cup wraps round the side of the chest: seen from the front it ends at the body's outline
        lim = {1: x0 + br, -1: x0 - bl}

        def onbody(pts, sgn):
            return [[min(x, lim[1]) if sgn > 0 else max(x, lim[-1]), y] for x, y in pts]
        for sgn in (1, -1):
            add("cup", "fill", onbody(g["cups"][sgn], sgn))
            add("cup_edge", "line", onbody(g["tops"][sgn], sgn))
            if p["push_up"] > 0:
                add("cup_before", "dash", onbody(g["plain_tops"][sgn], sgn))
        if g["gore"]:
            add("gore", "fill", g["gore"])
    for sgn, st in g["straps"].items():
        add("strap", "fill", _quad_along_pts(st["front"][0], st["front"][1], st["width"]))
        if st["back"]:
            add("strap_back", "dash", st["back"])
    if g["straps"]:
        s1 = g["straps"][1]["front"][1]
        mark(s1[0] + 0.03, s1[1], f"straps {spec['straps']['style']}")
    if p["closure"] == "front" and p["cup_style"] != "bandeau":
        c = spec["gore_half_m"] + GORE_EXTRA_M
        add("closure", "line", [[x0 - c, bottom], [x0 + c, bottom], [x0 + c, under + spec["gore_h_m"]],
                                [x0 - c, under + spec["gore_h_m"]], [x0 - c, bottom]])
        mark(x0, bottom - 0.02, "front closure", "middle")
    elif p["closure"] == "back_hook":
        # on the back (seen through): the hook's band ``CLOSURE_HALF_M`` either side of the spine
        c = CLOSURE_HALF_M
        add("closure", "dash", [[x0 - c, bottom], [x0 + c, bottom], [x0 + c, under], [x0 - c, under],
                                [x0 - c, bottom]])
        mark(x0, bottom - 0.02, "hook at the back", "middle")
    gore = {"none": "no gore", "narrow": "narrow gore", "wide": "wide gore"}[p["center_gore"]]
    mark(x0 + br + 0.03, under, f"{p['cup_style']} · cover {p['cup_coverage']:.2f} · {gore}")
    if p["push_up"] > 0:
        mark(x0 + br + 0.03, under - 0.04, f"push-up {p['push_up']:.2f} (dashed: without)")


def _quad_along_pts(a: List[float], b: List[float], w: float) -> List[List[float]]:
    """A band ``w`` wide from ``a`` to ``b``."""
    n = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return _quad_along((a[0], a[1]), ((b[0] - a[0]) / n, (b[1] - a[1]) / n), 0.0, n, w, w)


#: A223 tights drawing: the ankle this high over the floor, the knee this share of the height (without the joints).
TIGHTS_ANKLE_M = 0.08
TIGHTS_KNEE_SHARE = 0.28


def _foot_band(reg: Registration, m: Dict[str, Any], guess: float, ankle: float, add) -> None:
    """A stirrup's band round the middle of the foot (``STIRRUP_HALF_M`` either side of it along the foot), seen from
    the front: across the foot from the floor up to the instep (``INSTEP_SHARE`` of the way to the ankle joint)."""
    floor = float(m.get("floor_y", 0.0))
    top = floor + INSTEP_SHARE * (ankle - floor)
    run = reg.leg_run(floor + 0.3 * (top - floor), guess)
    a, b = run if run is not None else (guess - 0.045, guess + 0.045)
    add("stirrup", "fill", [[a, floor], [b, floor], [b, top], [a, top]])


def _ankle_y(m: Dict[str, Any], key: str) -> float:
    j = m.get("joints") or {}
    floor = float(m.get("floor_y", 0.0))
    return float(j[key][1]) if key in j else floor + TIGHTS_ANKLE_M


def _tights(p, m, reg: Registration, spec: Dict[str, Any], cap_m: float, add, mark) -> None:
    """A223: tights — the seat from the waist to the crotch (full tights), then each leg from its top (the waist,
    ``THIGH_TOP_DROP_M`` under the crotch, ``KNEE_TOP_DROP_M`` under the knee) down to the floor, or for an open foot
    to ``FOOT_CUT_M`` under the ankle joint (``tights_region``) with a stirrup's band round the middle of the foot; the
    top band (waistband / hold-up grip band / sock cuff, ``band_m``) as its lower edge; garter tabs as two strips."""
    import numpy as np
    from app.core import garment_template as gt
    j = m.get("joints") or {}
    x0 = reg.x0
    crotch = _crotch_y(m)
    floor = float(m.get("floor_y", 0.0))
    knee = float(j["leftleg"][1]) if "leftleg" in j else floor + TIGHTS_KNEE_SHARE * float(m["height"])
    style = spec["style"]
    band_h = float(spec["waistband_m"]) if style == "tights" else float(spec["band_m"])
    if style == "tights":
        top = spec["top_y"]
        bl, br = reg.body_half(top, cap_m)
        hl, hr = reg.body_half(m["hip_y"], cap_m)
        add("body", "fill", [[x0 - bl, top], [x0 + br, top], [x0 + hr, m["hip_y"]], [x0 + hr, crotch],
                             [x0 - hl, crotch], [x0 - hl, m["hip_y"]]])
        if band_h > 0:
            wl, wr = reg.body_half(top - band_h, cap_m)
            add("band_edge", "line", [[x0 - wl, top - band_h], [x0 + wr, top - band_h]])
        leg_top = crotch
    elif style == "knee_high":
        top = leg_top = knee - gt.KNEE_TOP_DROP_M
    else:
        top = leg_top = crotch - gt.THIGH_TOP_DROP_M
    for side, key, foot in ((1, "leftupleg", "leftfoot"), (-1, "rightupleg", "rightfoot")):
        guess = j[key][0] if key in j else x0 + side * 0.09
        foot_x = float(j[foot][0]) if foot in j else guess
        ankle = _ankle_y(m, foot)
        bottom = ankle - FOOT_CUT_M
        inner, outer = [], []
        leg_run = getattr(reg, "leg_run", None)
        for y in np.linspace(leg_top, bottom, 14):
            # the leg's centre runs from the hip joint's x to the foot joint's (the legs stand apart)
            gx = guess + (foot_x - guess) * min(1.0, max(0.0, (leg_top - y) / max(1e-6, leg_top - bottom)))
            run = leg_run(float(y), gx) if leg_run else None
            a, b = run if run is not None else (gx - 0.06, gx + 0.06)
            inner.append([a if side > 0 else b, float(y)])
            outer.append([b if side > 0 else a, float(y)])
        foot_pts = []
        if spec["feet"] == "closed":
            # the closed foot: the foot's own outline in the picture, from the ankle cut down to the floor
            run = leg_run(floor + 0.3 * (ankle - floor), foot_x) if leg_run else None
            a, b = run if run is not None else (foot_x - 0.05, foot_x + 0.05)
            foot_pts = [[a, floor], [b, floor]] if side > 0 else [[b, floor], [a, floor]]
        add("leg", "fill", inner + foot_pts + outer[::-1])
        if style != "tights" and band_h > 0:
            y = top - band_h
            run = reg.leg_run(y, guess)
            a, b = run if run is not None else (guess - 0.06, guess + 0.06)
            add("band_edge", "line", [[a, y], [b, y]])
        if spec["feet"] == "stirrup":
            _foot_band(reg, m, float(j[foot][0]) if foot in j else guess, ankle, add)
        if spec["garters"] == "tabs":
            w = spec["tab_half_m"]
            add("tab", "fill", [[guess - w, top], [guess + w, top], [guess + w, top + spec["tab_h_m"]],
                                [guess - w, top + spec["tab_h_m"]]])
    band = {"tights": "waistband", "hold_up": "grip band", "knee_high": "cuff"}.get(style)
    text = f"{style} · {spec['feet']}" + (f" · {band} {round(band_h * 100, 1)} cm" if band and band_h > 0 else "")
    mark(x0 + 0.2, leg_top, text)


def _boxers(p, m, reg: Registration, spec: Dict[str, Any], cap_m: float, add, mark) -> None:
    """A232: briefs with legs — the seat from the waistband to the crotch, then each leg straight down to the hem
    ``leg_length_m`` under the crotch (the leg's width in the picture plus the cloth's gap ``offset_m`` each side)."""
    import numpy as np
    j = m.get("joints") or {}
    x0 = reg.x0
    top = spec["top_y"]
    crotch = _crotch_y(m)
    hem = crotch - spec["leg_length_m"]
    bl, br = reg.body_half(top, cap_m)
    hl, hr = reg.body_half(m["hip_y"], cap_m)
    add("body", "fill", [[x0 - bl, top], [x0 + br, top], [x0 + hr, m["hip_y"]], [x0 + hr, crotch],
                         [x0 - hl, crotch], [x0 - hl, m["hip_y"]]])
    for side, key in ((1, "leftupleg"), (-1, "rightupleg")):
        guess = j[key][0] if key in j else x0 + side * 0.09
        inner, outer = [], []
        for y in np.linspace(crotch + 0.01, hem, 6):
            run = reg.leg_run(float(y), guess)
            a, b = run if run is not None else (guess - 0.08, guess + 0.08)
            if side > 0:
                a = max(a, x0)
            else:
                b = min(b, x0)
            c, w = (a + b) / 2, (b - a) / 2 + spec["offset_m"]
            inner.append([c - w if side > 0 else c + w, float(y)])
            outer.append([c + w if side > 0 else c - w, float(y)])
        add("leg", "fill", inner + outer[::-1])
    if spec["waistband_m"] > 0:
        add("waist", "dash", [[x0 - bl, top - spec["waistband_m"]], [x0 + br, top - spec["waistband_m"]]])
    add("hem", "dash", [[x0 - hl * 1.1, hem], [x0 + hr * 1.1, hem]])
    mark(x0 + br + 0.03, top, f"rise {p['rise']}")
    mark(x0 + hr + 0.05, hem, f"legs {round(spec['leg_length_m'] * 100)} cm")
    mark(x0, hem - 0.04, f"fit {p['fit']:.2f} · {p['fabric']}", "middle")


def trouser_anchors(m: Dict[str, Any]) -> Dict[str, float]:
    """A233: the hem anchors for the drawing (``garment_template.TROUSER_HEM``) — the crotch (``_crotch_y``), the knee
    and ankle joints (without the joints: the reference body's shares of the height)."""
    j = m.get("joints") or {}
    floor = float(m.get("floor_y", 0.0))
    knee = float(j["leftleg"][1]) if "leftleg" in j else floor + TIGHTS_KNEE_SHARE * float(m["height"])
    ankle = float(j["leftfoot"][1]) if "leftfoot" in j else floor + TIGHTS_ANKLE_M
    return {"crotch": _crotch_y(m), "knee": knee, "ankle": ankle}


def _trousers(p, m, reg: Registration, cap_m: float, add, mark) -> None:
    """A233: trousers, drawn from the numbers the builder cuts by (``garment_template.trouser_spec``): the seat from
    the waistband (``rise``) to the crotch, then each leg along the leg in the picture down to the hem
    (``trouser_hem``), as wide as the leg plus the cloth's gap and — not skinny — at least the leg shape's radius
    (``LEG_SHAPE_R`` of the thigh's half width, straight in height from the crotch to the knee to the ankle); the
    waist band, a cuff and the fly as guides. Bug round 2026-11-20: the seat's ease (``seat_spec``) widens the seat
    from 0 at the waistband's lower edge to full ``ramp_m`` under it, and fades out down the leg over ``fade_m`` under
    the crotch, as the builder's ``trouser_seat`` moves the cloth."""
    import numpy as np
    from app.core import garment_template as gt
    spec = gt.trouser_spec(p, m)
    anchors = trouser_anchors(m)
    j = m.get("joints") or {}
    x0 = reg.x0
    top = spec["top_y"]
    crotch = anchors["crotch"]
    stirrup = p["hem"] == "stirrup"
    # a stirrup has no hem plane: the leg runs to FOOT_CUT_M under the ankle joint, a band round the foot's middle
    hem = anchors["ankle"] - FOOT_CUT_M if stirrup else gt.trouser_hem(p["trouser_length"], anchors)
    off = spec["offset_m"]
    bl, br = reg.body_half(top, cap_m)
    hl, hr = reg.body_half(m["hip_y"], cap_m)
    seat_y = min(m["hip_y"], top)
    st = spec["seat"]
    band_lo = top - spec["band_m"]

    def ease(y):
        """The seat's ease at height ``y`` (0 over the band, full ``ramp_m`` under it, fading out under the crotch)."""
        e = float(st["ease_m"]) * min(1.0, max(0.0, (band_lo - y) / float(st["ramp_m"])))
        return e * min(1.0, max(0.0, 1.0 - (crotch - y) / float(st["fade_m"]))) if y < crotch else e
    add("body", "fill", [[x0 - bl - off, top], [x0 + br + off, top], [x0 + hr + off + ease(seat_y), seat_y],
                         [x0 + hr + off + ease(crotch), crotch], [x0 - hl - off - ease(crotch), crotch],
                         [x0 - hl - off - ease(seat_y), seat_y]])
    if spec["band_m"] > gt.MIN_PIN_BAND_M:
        add("waist", "dash", [[x0 - bl, top - spec["band_m"]], [x0 + br, top - spec["band_m"]]])
    if p["fly"] == "zip":
        add("fly", "line", [[x0, top - spec["band_m"]], [x0, crotch + 0.03]])
    elif p["fly"] == "buttons":
        # painted only (``TEXTURE_ONLY``): a button placket — the buttons as small squares down the centre
        ys = np.linspace(top - spec["band_m"] - 0.015, crotch + 0.04, 4)
        for y in ys:
            add("fly", "line", [[x0 - 0.005, y - 0.005], [x0 + 0.005, y - 0.005], [x0 + 0.005, y + 0.005],
                                [x0 - 0.005, y + 0.005], [x0 - 0.005, y - 0.005]])
    for side, key in ((1, "leftupleg"), (-1, "rightupleg")):
        guess = j[key][0] if key in j else x0 + side * 0.09
        rows = []
        for y in np.linspace(crotch, hem, 14):
            run = reg.leg_run(float(y), guess)
            if run is None:
                continue
            a, b = run
            if side > 0:
                a = max(a, x0)
            else:
                b = min(b, x0)
            if b - a < 0.02:
                continue
            guess = (a + b) / 2
            rows.append((float(y), guess, (b - a) / 2))
        if not rows:
            continue
        # the thigh radius as the builder reads it: 3 cm under the crotch (the median 2 .. 4 cm under it)
        r_t = float(np.interp(crotch - 0.03, [r[0] for r in rows[::-1]], [r[2] for r in rows[::-1]])) \
            * (1.0 + spec["radial_ease"])
        out_l, out_r = [], []
        for y, c, half in rows:
            w = half + off + ease(y)
            if spec["shape_r"]:
                k, h = spec["shape_r"]
                target = float(np.interp(y, [anchors["ankle"], anchors["knee"], crotch], [h * r_t, k * r_t, r_t]))
                ramp = min(1.0, max(0.0, (crotch - y) / spec["ramp_m"]))
                w = max(w, w + ramp * (target - w))
            lo, hi = c - w, c + w
            if side > 0:
                lo = max(lo, x0 + spec["centre_gap_m"])
            else:
                hi = min(hi, x0 - spec["centre_gap_m"])
            out_l.append([lo, y])
            out_r.append([hi, y])
        add("leg", "fill", out_l + out_r[::-1])
        add("leg", "fill", [out_l[0], out_r[0], [x0, crotch + 0.04]])
        if p["hem"] == "cuffed":
            yb = out_l[-1][1]
            add("cuff", "dash", [[out_l[-1][0], yb + spec["cuff_m"]], [out_r[-1][0], yb + spec["cuff_m"]]])
        if stirrup:
            fk = "leftfoot" if side > 0 else "rightfoot"
            _foot_band(reg, m, float(j[fk][0]) if fk in j else guess, anchors["ankle"], add)
    mark(x0 + hr + 0.05, top, f"rise {p['rise']}")
    mark(x0 + hr + 0.05, (crotch + hem) / 2, f"{p['leg_shape']} · fit {p['fit']:.2f}")
    mark(x0 + hr + 0.05, (seat_y + crotch) / 2, f"seat {p['seat']}")
    mark(x0, hem - 0.035, (f"stirrup · to {hem:.2f} m" if stirrup else f"{p['trouser_length']} · {p['hem']} hem "
                           f"{hem:.2f} m") + ("" if p["fly"] == "none" else f" · fly {p['fly']}"), "middle")
    add("dim", "line", [[x0 + hr + 0.04, top], [x0 + hr + 0.04, hem]])


# --- the route's helper ------------------------------------------------------------------------------------------

def fabric_colour(item_id: str) -> str:
    """The item picture's mean colour over its non-ground pixels (``#rrggbb``), "" without a picture."""
    try:
        import numpy as np
        from PIL import Image
        from app.models.inventory import get_item_image_path
        path = get_item_image_path(item_id)
        if not path:
            return ""
        with Image.open(path) as im:
            im.thumbnail((96, 96))
            mask = silhouette(im)
            rgb = np.asarray(im.convert("RGB")).reshape(-1, 3)[mask.reshape(-1)]
        if len(rgb) < 20:
            return ""
        r, g, b = (int(v) for v in np.median(rgb, axis=0))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return ""


NO_BASE_PICTURE = "No plain body front yet — build the plain body first (Figure tab)"
NO_BASE_MODEL = "No plain body model yet — the overlay needs its measurements (Figure tab → Build)"
NO_UPPER_JOINTS = "The plain body has no arm or neck joints to place the piece by"


def drapes_over_sleeves(character_name: str, item_id: str, params: Dict[str, Any],
                        base: Optional[Tuple[str, str]]) -> bool:
    """Bug round 2026-11-20: whether the drape cuts this piece (with the dialog's ``params``) with the jacket's layer
    allowance — the key's own test (``garment_template.collider_states`` + ``over_sleeved_layer``: a lower template
    layer with sleeves whose drape is ready) on the character's worn set without this piece. False without a base."""
    from app.core import figure
    from app.core import garment_template as gt
    if not base or not gt.layer_ease(params, True):
        return False
    lower = gt.lower_layers(figure.worn_sets(character_name).own, item_id)
    ready = [it for _o, it, st in gt.collider_states(character_name, item_id, params["kind"], lower,
                                                     base_sha=base[1]) if st["state"] == "ready"]
    return gt.over_sleeved_layer(params["kind"], ready)


def overlay(character_name: str, item_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """The dialog's picture with the piece on it: ``{ok, reason?, picture {url, w, h, dressed}, figure {state,
    reason?, error?}, px_per_m, landmarks, colour, shapes, marks, params}`` (``params`` validated). Nothing generated.

    A195: the picture is the character DRESSED without this piece (``garment_preview_front``, a local front render
    with a known camera — exact metres) once rendered; until then (``figure.state`` ``rendering``) and without a
    figure or after a failed render the plain base-body front of A188 stands in, registered by its silhouette."""
    from urllib.parse import quote
    from app.core import base_body, garment_preview_front
    from app.core import garment_template as gt
    from app.models.character import get_character_dir
    params, errors = gt.validate_params(params)
    out: Dict[str, Any] = {"ok": False, "params": params, "errors": errors}
    base = base_body.current_base(character_name)
    glb = get_character_dir(character_name) / "model3d" / f"{base[0]}.glb" if base else None
    dressed = garment_preview_front.state(character_name, item_id)
    out["figure"] = {k: v for k, v in dressed.items() if k in ("state", "reason", "error")}
    c, i = quote(character_name, safe=""), quote(item_id, safe="")
    if dressed["state"] == "ready" and glb is not None and glb.is_file():
        frame = dict(picture_frame(dressed["png"]), camera=dressed["record"]["camera"])
        url = f"/characters/{c}/figure/template/{i}/front/{dressed['key']}.png"
    else:
        path = base_body.base_image_path(character_name, "front")
        if path is None or not Path(path).is_file():
            out["reason"] = NO_BASE_PICTURE
            return out
        url = f"/characters/{c}/base-body/images/front"
        frame = picture_frame(Path(path))
    out["picture"] = {"url": url, "w": frame["w"], "h": frame["h"], "dressed": "camera" in frame}
    if glb is None or not glb.is_file():
        out["reason"] = NO_BASE_MODEL
        return out
    meas = body_measure(glb)
    if "shoulder_y" not in meas or "neck_y" not in meas:
        # A198 (review 06C #4): ``measure_body`` leaves the upper block out without the arm / neck joints — the
        # registration and the landmarks need it; say so instead of a 500 on every slider move
        out["reason"] = NO_UPPER_JOINTS
        return out
    reg = register(frame, meas)
    drawn = shapes(params, meas, reg, over_sleeves=drapes_over_sleeves(character_name, item_id, params, base))
    out.update(ok=True, px_per_m=round(reg.scale, 3), landmarks=reg.landmarks(), colour=fabric_colour(item_id),
               **drawn)
    return out
