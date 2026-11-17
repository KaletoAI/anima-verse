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
  (what the drape uses); a girth becomes a front width through the body's own silhouette at that height (garment
  girth / body girth x the body's half width in the picture) — so a fit of 0 hugs the body in the picture and the
  flare widens the hem from the hip width. The neckline follows the builder's cut rule
  (``garment_template_build``: crew / scoop / boat = cos^1.4 of the angle from the front, V = 1 - |sin|).

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
#: A stand collar's height above the neck opening; a lapel reaches this far out past the opening.
COLLAR_H_M = 0.045
LAPEL_OUT_M = 0.07
#: An open jacket front: the gap at the hem (the fronts hang apart).
OPEN_GAP_M = 0.05
#: A trouser leg's ease over the leg in the picture (front width share).
TROUSER_EASE = 0.12
#: The crotch below the hip line (metres) where a trouser leg begins.
CROTCH_BELOW_HIP_M = 0.08

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
    extra = {k: [round(float(x), 4) for x in joints[k]] for k in ("hips", "leftupleg", "rightupleg", "leftfoot",
                                                                  "rightfoot", "head") if k in joints}
    meas = dict(meas, joints={**(meas.get("joints") or {}), **extra})
    with _lock:
        _measures.clear()
        _measures[key] = meas
    return meas


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


def _quad_along(a: Tuple[float, float], u: Tuple[float, float], start: float, end: float, w0: float,
                w1: float) -> List[List[float]]:
    """A band along the axis from ``a`` in direction ``u`` (unit), from ``start`` to ``end`` metres, ``w0`` / ``w1``
    wide at either end."""
    n = (-u[1], u[0])
    p0 = (a[0] + u[0] * start, a[1] + u[1] * start)
    p1 = (a[0] + u[0] * end, a[1] + u[1] * end)
    return [[p0[0] + n[0] * w0 / 2, p0[1] + n[1] * w0 / 2], [p1[0] + n[0] * w1 / 2, p1[1] + n[1] * w1 / 2],
            [p1[0] - n[0] * w1 / 2, p1[1] - n[1] * w1 / 2], [p0[0] - n[0] * w0 / 2, p0[1] - n[1] * w0 / 2]]


def shapes(params: Dict[str, Any], meas: Dict[str, Any], reg: Registration) -> Dict[str, Any]:
    """The piece on the picture: ``{shapes: [{role, kind (fill | cut | line | dash), points (px)}], marks: [{x, y,
    text, anchor}], landmarks}``. ``fill`` = cloth, ``cut`` = an opening in the cloth (neckline, open front, slit),
    ``line`` / ``dash`` = a guide (the waist line chosen, a dimension). Marks carry the numbers: hem height, length,
    sleeve length, neckline depth, slit depth."""
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
    if kind in ("skirt", "trousers", "dress"):
        bl, br = reg.body_half(waist_y, cap_m)
        add("waist", "dash", [[x0 - bl - 0.03, waist_y], [x0 + br + 0.03, waist_y]])
        mark(x0 + br + 0.04, waist_y, f"waist {p['waist_height']}")

    if kind == "trousers":
        _trousers(p, m, reg, waist_y, cap_m, add, mark)
        return {"shapes": out, "marks": marks}

    shape = gt.outline(p, m)
    knots = shape["knots"]
    top_y = shape["top_y"]
    hem_y = top_y - knots[-1][0]
    left, right = _side_points(reg, m, knots, hem_y, cap_m)
    bodice = gt.has_bodice(p)
    spec = gt.bodice_spec(p, m) if bodice and "shoulder_y" in m else None
    dip = 0.012 + 0.05 * float(p.get("flare", 0)) if kind in ("skirt", "dress") else 0.008
    hem = _hem_curve(left[0], right[0], dip)
    # the outline: up the right side, across the top, down the left side, along the hem
    if spec is None:
        add("body", "fill", right + left[::-1] + hem[::-1][1:-1])
    else:
        nr = spec["neck_r"]
        sy = m["shoulder_y"]
        if p["shoulders"] == "straps" and kind == "dress":
            # the bodice ends at the chest band; above it only the straps
            band = spec["band_y"]
            r_cut = [q for q in right if q[1] <= band] + [_at(right, band)]
            l_cut = [q for q in left if q[1] <= band] + [_at(left, band)]
            add("body", "fill", r_cut + l_cut[::-1] + hem[::-1][1:-1])
            for sgn in (1, -1):
                sx = x0 + sgn * spec["strap_x"]
                w = spec["strap_w"] / 2
                add("strap", "fill", [[sx - w, band], [sx + w, band], [sx + w, top_y], [sx - w, top_y]])
            mark(x0 + spec["strap_x"] + 0.03, top_y - 0.03, "straps")
        else:
            body_r = [q for q in right if q[1] < sy - 0.02]
            body_l = [q for q in left if q[1] < sy - 0.02]
            sh_r, sh_l = [x0 + half_sh, sy + 0.01], [x0 - half_sh, sy + 0.01]
            top_r, top_l = [x0 + nr, top_y], [x0 - nr, top_y]
            add("body", "fill", body_r + [sh_r, top_r, top_l, sh_l] + body_l[::-1] + hem[::-1][1:-1])
            # the sleeves along the picture's arm axis (the picture is A-posed, the model T-posed)
            if spec["sleeve"]:
                _sleeves(p, m, reg, spec, add, mark)
            # the neckline (an opening: the picture shows through)
            depth = spec["depth_m"]
            bottom = sy - depth
            half_w = nr if spec["neckline"] != "boat" else spec["neck_r"]
            curve = neckline_curve(spec["neckline"], x0, half_w, top_y + 0.004, bottom)
            add("neck", "cut", curve + [[x0 - half_w, top_y + 0.05], [x0 + half_w, top_y + 0.05]])
            add("neck_edge", "line", curve)
            mark(x0 + half_w + 0.02, bottom, f"{_neck_name(spec['neckline'])} −{round((top_y - bottom) * 100)} cm")
            if spec["collar"] == "stand":
                ring = [[x0 + nr + 0.012, top_y - 0.004], [x0 + nr * 0.8, top_y + COLLAR_H_M],
                        [x0 - nr * 0.8, top_y + COLLAR_H_M], [x0 - nr - 0.012, top_y - 0.004],
                        [x0 - nr, top_y - 0.004], [x0 + nr, top_y - 0.004]]
                add("collar", "fill", ring)
                add("collar_edge", "line", ring[:4])
                mark(x0 + nr + 0.02, top_y + COLLAR_H_M, "stand collar")
            elif spec["collar"] == "lapel":
                for sgn in (1, -1):
                    add("lapel", "fill", [[x0 + sgn * nr, top_y], [x0 + sgn * (nr + LAPEL_OUT_M), bottom + 0.06],
                                          [x0, bottom], [x0 + sgn * 0.01, bottom + 0.02]])
                    add("lapel_edge", "line", [[x0 + sgn * nr, top_y], [x0 + sgn * (nr + LAPEL_OUT_M), bottom + 0.06],
                                               [x0, bottom]])
                mark(x0 - nr - LAPEL_OUT_M - 0.01, bottom + 0.06, "lapel", "end")
            if spec["front_open"]:
                add("front", "cut", [[x0 - 0.003, bottom], [x0 + 0.003, bottom], [x0 + OPEN_GAP_M / 2, hem_y - 0.02],
                                     [x0 - OPEN_GAP_M / 2, hem_y - 0.02]])
                mark(x0 + OPEN_GAP_M / 2 + 0.01, hem_y + 0.05, "open front")
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


def _trousers(p, m, reg: Registration, waist_y: float, cap_m: float, add, mark) -> None:
    """Trousers (a kind the drape does not build yet; drawn so the length and the rise can be judged): the seat from
    the waist line to the crotch, then each leg along the leg in the picture to ``waist - length``."""
    import numpy as np
    j = m.get("joints") or {}
    crotch = m["hip_y"] - CROTCH_BELOW_HIP_M
    hem = max(m["floor_y"] + 0.01, waist_y - p["length_m"])
    bl, br = reg.body_half(waist_y, cap_m)
    hl, hr = reg.body_half(m["hip_y"], cap_m)
    k = 1.0 + TROUSER_EASE * 0.5
    add("body", "fill", [[reg.x0 - bl * k, waist_y], [reg.x0 + br * k, waist_y], [reg.x0 + hr * k, m["hip_y"]],
                         [reg.x0 + hr * k, crotch], [reg.x0 - hl * k, crotch], [reg.x0 - hl * k, m["hip_y"]]])
    for side, key in ((1, "leftupleg"), (-1, "rightupleg")):
        guess = j[key][0] if key in j else reg.x0 + side * 0.09
        inner, outer = [], []
        for y in np.linspace(crotch, hem, 14):
            run = reg.leg_run(float(y), guess)
            if run is None:
                continue
            a, b = run
            # a run across the centre (the hips above the crotch) is cut at the centre; a run on the other side
            # (the other leg) is never followed
            if side > 0:
                a = max(a, reg.x0)
            else:
                b = min(b, reg.x0)
            if b - a < 0.02:
                continue
            guess = (a + b) / 2
            w = (b - a) * (1 + TROUSER_EASE) / 2
            lo, hi = guess - w, guess + w
            (inner if side > 0 else outer).append([lo, float(y)])
            (outer if side > 0 else inner).append([hi, float(y)])
        if inner and outer:
            add("leg", "fill", outer + inner[::-1])
            add("leg", "fill", [outer[0], inner[0], [reg.x0, crotch + 0.04]])
    mark(reg.x0 + hr + 0.05, (waist_y + hem) / 2, f"{round(p['length_m'] * 100)} cm")
    mark(reg.x0, hem - 0.035, f"hem {hem:.2f} m", "middle")
    add("dim", "line", [[reg.x0 + hr + 0.04, waist_y], [reg.x0 + hr + 0.04, hem]])


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
    reg = register(frame, meas)
    drawn = shapes(params, meas, reg)
    out.update(ok=True, px_per_m=round(reg.scale, 3), landmarks=reg.landmarks(), colour=fabric_colour(item_id),
               **drawn)
    return out
