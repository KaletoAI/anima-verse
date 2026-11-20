"""The geometry of the accessories that go AROUND a part of the body or hang on a bone (A234; spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 4 / § 4b / § 11): belt, choker, strap (a flat band),
anklet, bracelet (a round tube) and earrings (rigid on the head). The ring (A238) is sized from the skeleton instead:
``accessory_ring``.

Every ring-shaped kind is made the same way: an AXIS through the body part (``frame``: a centre point, a direction
and the joints whose skin counts), a fan of rays from the axis in the plane across it (``section``), and on every ray
the OUTERMOST surface of the layer under the piece — the body's surface (``BODY_PICK``: in-body clothing included; round
the neck the innermost layer, never a hair shell farther out) or, for ``band.layer: auto``, a worn garment's fitted mesh when it lies farther out (``under``). The
piece is then laid ``GAP_M`` off that surface:

- a band (belt / choker / strap): ``BAND_ROWS`` rows across its width, each row hugging the surface under it, the
  section a flat rectangle ``band_thickness`` deep (``band_mesh``);
- a tube (anklet / bracelet): one row through the centre, swept into ``accessory_mesh.tube`` with the chain's
  thickness.

The axis per kind (all in the body's bind space, +Y up, +Z the front, +X the body's left):

- belt: vertical through the Hips bone head; height 0 = the waist (``WAIST_SHARE`` of the way from the Hips to the
  Spine bone head) — or, with a worn bottom under it, just below that garment's top edge (``belt_anchor``);
- choker: along Neck -> Head, ``CHOKER_SHARE`` of the way up;
- strap: ``band.at`` thigh (UpLeg -> Leg, ``STRAP_THIGH_SHARE``), upper_arm (Arm -> ForeArm, ``STRAP_ARM_SHARE``) or
  chest (vertical, the underbust: ``STRAP_CHEST_SHARE`` of Spine1 -> Spine2), per side for thigh / upper arm;
- anklet: along Leg -> Foot, ``ANKLET_ABOVE_M`` above the Foot bone head;
- bracelet: along ForeArm -> Hand, ``WRIST_ABOVE_M`` above the Hand bone head.

``band.height_cm`` moves the ring along its axis (up the body / up the limb toward the trunk). Earrings sit on the
ear (``ear_anchor``): stud = a small ball, hoop = a torus hanging beside the lobe, ``drop`` = the item-image mesh
(``accessory_pendant``) hung under it. Pure numpy/scipy; no I/O.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

#: Air between the surface under a piece and the piece's inner face (spec § 9 P3b: 1–4 mm).
GAP_M = 0.002
#: Rays per section (around the axis).
SECTION_RAYS = 96
#: Rows across a band's width.
BAND_ROWS = 5
#: How far from the axis a section looks for a surface (metres) — a waist is at most ~25 cm from its axis.
REACH_M = {"belt": 0.32, "strap": 0.32, "choker": 0.12, "anklet": 0.12, "bracelet": 0.10}
#: A garment surface counts for a ray only up to this far beyond the body's skin on that ray (a skirt's flare or a
#: coat's hem farther out is not the layer the band sits on).
UNDER_MAX_M = 0.06
#: Which body surface a section takes (``accessory_curve.ray_hits`` pick): the outermost — clothing worn "in the
#: body" is part of the body's surface, a belt goes over it — except round the neck, where a hair shell can lie
#: farther out (the innermost layer, as for the necklace).
BODY_PICK = {"choker": "layer"}
#: A worn garment counts as the layer under a piece when it lies round at least this share of its section.
UNDER_MIN_SHARE = 0.5
#: Rays that find no surface: up to this share is bridged around the section, more refuses the build.
MAX_MISSING_SHARE = 0.25

#: The axes (module docstring).
WAIST_SHARE = 0.5
CHOKER_SHARE = 0.45
STRAP_THIGH_SHARE = 0.5
STRAP_ARM_SHARE = 0.55
STRAP_CHEST_SHARE = 0.0
ANKLET_ABOVE_M = 0.035
WRIST_ABOVE_M = 0.025
#: Below a worn bottom's top edge, the belt's centre sits this far + half its width (the band covers the waistband).
BELT_BELOW_TOP_M = 0.004

#: The joints whose skin a section sees (normalised names, ``{side}`` = left / right).
REGION_JOINTS: Dict[str, Tuple[str, ...]] = {
    "belt": ("hips", "spine", "spine1", "leftupleg", "rightupleg"),
    "choker": ("neck", "spine2"),
    "strap:thigh": ("{side}upleg",),
    "strap:upper_arm": ("{side}arm",),
    "strap:chest": ("spine1", "spine2", "leftbreast", "rightbreast", "leftbreasttip", "rightbreasttip"),
    "anklet": ("{side}leg", "{side}foot"),
    "bracelet": ("{side}forearm", "{side}hand"),
}
#: The worn garment slots that may lie under a piece (``band.layer: auto``).
UNDER_SLOTS: Dict[str, Tuple[str, ...]] = {
    "belt": ("bottom", "legs", "underwear_bottom", "top", "outer"),
    "choker": ("top", "outer", "neck"),
    "strap:thigh": ("bottom", "legs", "underwear_bottom"),
    "strap:upper_arm": ("top", "outer"),
    "strap:chest": ("top", "outer", "underwear_top"),
    "anklet": ("legs", "bottom", "feet"),
    "bracelet": ("top", "outer", "hands"),
}
#: The band's depth by material (metres).
BAND_THICKNESS_M = {"leather": 0.003, "metal": 0.002, "fabric": 0.0015, "from_image": 0.003}
#: Earrings (``ear_anchor``): the box the ear is looked for in, relative to the Head bone head — (y from, y to),
#: (z from, z to) in metres (the ear stands above the head joint and behind the jaw).
EAR_BOX = ((0.0, 0.08), (-0.05, 0.01))
#: The ear's rim: head skin within this of the ear's farthest point to the side.
EAR_RIM_M = 0.012
#: The anchor sits this far above the rim's lowest point (inside the lobe, not under it).
LOBE_UP_M = 0.004


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _bone(bones: Dict[str, Any], key: str) -> np.ndarray:
    """The head of the bone ``key`` (normalised name); ``KeyError`` naming it when the rig has none."""
    norm = {str(k).split(":")[-1].lower(): v for k, v in bones.items()}
    if key not in norm:
        raise KeyError(key)
    return np.asarray(norm[key], np.float64)


def region_key(spec: Dict[str, Any]) -> str:
    """``belt`` / ``choker`` / ``strap:<at>`` / ``anklet`` / ``bracelet`` / ``earrings``."""
    kind = spec["kind"]
    return f"strap:{spec['band'].get('at') or 'thigh'}" if kind == "strap" else kind


def sides_of(spec: Dict[str, Any]) -> List[str]:
    """The body sides a piece is built on: ``left`` / ``right`` (both for ``side: both``) for the paired kinds, a
    strap on the thigh / upper arm; ``[""]`` (one centred piece) for belt, choker, chest strap."""
    key = region_key(spec)
    if key in ("belt", "choker", "strap:chest"):
        return [""]
    side = spec.get("side") or "both"
    return ["left", "right"] if side == "both" else [side]


def joints_for(spec: Dict[str, Any], side: str) -> Tuple[str, ...]:
    return tuple(j.format(side=side) for j in REGION_JOINTS[region_key(spec)])


def frame(spec: Dict[str, Any], bones: Dict[str, Any], side: str = "",
          belt_top_y: Optional[float] = None) -> Dict[str, Any]:
    """``{centre, axis, front}`` of the piece's section (module docstring): ``axis`` the unit direction the height
    moves along (toward the trunk / up), ``front`` a unit direction across it (the section's angle 0). ``belt_top_y``
    (a worn bottom's top edge at the front) places a belt under it."""
    key = region_key(spec)
    width = float(spec["band"]["width_cm"]) / 100.0
    up = np.array([0.0, 1.0, 0.0])
    front = np.array([0.0, 0.0, 1.0])
    if key == "belt":
        hips, spine = _bone(bones, "hips"), _bone(bones, "spine")
        y = hips[1] + WAIST_SHARE * (spine[1] - hips[1])
        if belt_top_y is not None and hips[1] - 0.05 < belt_top_y < _bone(bones, "spine1")[1]:
            y = belt_top_y - BELT_BELOW_TOP_M - width / 2
        centre, axis = np.array([hips[0], y, hips[2]]), up
    elif key == "choker":
        neck, head = _bone(bones, "neck"), _bone(bones, "head")
        centre, axis = neck + CHOKER_SHARE * (head - neck), _unit(head - neck)
    elif key == "strap:chest":
        s1, s2 = _bone(bones, "spine1"), _bone(bones, "spine2")
        centre, axis = s1 + STRAP_CHEST_SHARE * (s2 - s1), up
    elif key == "strap:thigh":
        a, b = _bone(bones, f"{side}upleg"), _bone(bones, f"{side}leg")
        centre, axis = a + STRAP_THIGH_SHARE * (b - a), _unit(a - b)
    elif key == "strap:upper_arm":
        a, b = _bone(bones, f"{side}arm"), _bone(bones, f"{side}forearm")
        centre, axis = a + STRAP_ARM_SHARE * (b - a), _unit(a - b)
    elif key == "anklet":
        leg, foot = _bone(bones, f"{side}leg"), _bone(bones, f"{side}foot")
        axis = _unit(leg - foot)
        centre = foot + ANKLET_ABOVE_M * axis
    elif key == "bracelet":
        fore, hand = _bone(bones, f"{side}forearm"), _bone(bones, f"{side}hand")
        axis = _unit(fore - hand)
        centre = hand + WRIST_ABOVE_M * axis
    else:
        raise ValueError(f"no section for {spec['kind']}")
    centre = centre + axis * float(spec["band"]["height_cm"]) / 100.0
    f = front - float(front @ axis) * axis
    if np.linalg.norm(f) < 1e-6:
        f = np.cross(axis, [1.0, 0.0, 0.0])
    return {"centre": centre, "axis": axis, "front": _unit(f), "key": key, "side": side}


def dominant_faces(F: np.ndarray, dense: np.ndarray, joint_names: Sequence[str], allowed: Sequence[str]) -> np.ndarray:
    """The faces of ``F`` whose three vertices' strongest joint (``dense`` ``(n, joints)``) is one of ``allowed``
    (normalised names) — the body part a section belongs to (never the other leg, an arm beside the hip)."""
    from app.core.rig_contract import norm_bone_name
    ok_joint = np.array([norm_bone_name(str(n)) in set(allowed) for n in joint_names])
    ok_vertex = ok_joint[np.asarray(dense).argmax(1)]
    return np.asarray(F)[ok_vertex[np.asarray(F)].sum(1) >= 2]


def _crop(P: np.ndarray, F: np.ndarray, centre: np.ndarray, reach: float) -> np.ndarray:
    lo, hi = centre - reach, centre + reach
    T = P[F]
    return F[np.all((T.min(1) <= hi) & (T.max(1) >= lo), axis=1)]


def section(P: np.ndarray, F: np.ndarray, fr: Dict[str, Any], offsets: Sequence[float], *, reach: float,
            pick: str, n: int = SECTION_RAYS) -> Tuple[np.ndarray, np.ndarray]:
    """``(t (rows, n), dirs (n, 3))``: per row (``offsets`` along the axis from the centre) and angle the distance
    from the axis to the surface ``(P, F)`` (``accessory_curve.ray_hits`` with ``pick``), NaN where a ray finds
    nothing. Angle 0 = ``fr['front']``, then toward ``axis × front``."""
    from app.core.accessory_curve import ray_hits
    axis, front = fr["axis"], fr["front"]
    side = np.cross(axis, front)
    phi = 2 * np.pi * np.arange(n) / n
    dirs = np.cos(phi)[:, None] * front[None] + np.sin(phi)[:, None] * side[None]
    out = np.full((len(offsets), n), np.nan)
    Fc = _crop(P, F, fr["centre"], reach + max(abs(float(o)) for o in offsets))
    if not len(Fc):
        return out, dirs
    for r, off in enumerate(offsets):
        origins = np.repeat((fr["centre"] + axis * float(off))[None], n, 0)
        t, _ = ray_hits(P, Fc, origins, dirs, reach, pick=pick)
        out[r] = t
    return out, dirs


def bridge(t: np.ndarray, what: str, max_missing: float = MAX_MISSING_SHARE) -> np.ndarray:
    """``t`` (rows, n) with the NaN rays filled around the section (linear over the angle, closed); ``ValueError``
    when more than ``max_missing`` of the rays found nothing."""
    t = np.array(t, np.float64)
    miss = np.isnan(t)
    if miss.mean() > max_missing:
        raise ValueError(f"The {what} was not found on this body ({miss.mean():.0%} of the section is missing)")
    n = t.shape[1]
    idx = np.arange(n)
    for r in range(len(t)):
        ok = ~np.isnan(t[r])
        if ok.all():
            continue
        if not ok.any():
            t[r] = np.nanmean(t)
            continue
        xs = np.r_[idx[ok] - n, idx[ok], idx[ok] + n]
        t[r] = np.interp(idx, xs, np.tile(t[r][ok], 3))
    return t


def smooth_up(t: np.ndarray, passes: int = 3) -> np.ndarray:
    """``t`` smoothed around the section and across the rows, never below the surface it was measured on (a smooth
    band bridges a hollow, it never cuts a bump)."""
    s = np.array(t, np.float64)
    for _ in range(passes):
        s = 0.5 * s + 0.25 * (np.roll(s, 1, 1) + np.roll(s, -1, 1))
        if len(s) > 2:
            s[1:-1] = 0.5 * s[1:-1] + 0.25 * (s[:-2] + s[2:])
        s = np.maximum(s, t)
    return s


def surface_radius(body_P, body_F, under: List[Tuple[np.ndarray, np.ndarray]], fr: Dict[str, Any],
                   offsets: Sequence[float], *, reach: float, what: str) -> Dict[str, Any]:
    """Per row and ray the radius of the layer a piece sits on: the body's skin, or a worn garment's surface when it
    lies farther out on that ray (at most ``UNDER_MAX_M`` beyond the skin). ``{t, skin, dirs, under_share}`` —
    ``under_share`` the share of rays that sit on a garment."""
    skin, dirs = section(body_P, body_F, fr, offsets, reach=reach, pick=BODY_PICK.get(fr["key"], "outer"))
    skin = bridge(skin, what)
    t = skin.copy()
    on_garment = np.zeros_like(t, bool)
    for P, F in under:
        g, _ = section(P, F, fr, offsets, reach=reach + UNDER_MAX_M, pick="outer")
        g = np.where(np.isfinite(g) & (g <= skin + UNDER_MAX_M), g, np.nan)
        if np.isfinite(g).mean() < UNDER_MIN_SHARE:
            continue          # it only touches the section (a shoe's lower back edge): the piece is not over it
        # over most of it: the piece goes round it, bridging where it ends lower (a shaft cut lower at the back)
        g = bridge(g, "garment", 1.0 - UNDER_MIN_SHARE)
        farther = g > t
        t = np.where(farther, g, t)
        on_garment |= farther
    return {"t": t, "skin": skin, "dirs": dirs, "on_garment": on_garment,
            "under_share": round(float(on_garment.mean()), 3)}


def band_rows(fr: Dict[str, Any], width_m: float) -> np.ndarray:
    return np.linspace(-width_m / 2, width_m / 2, BAND_ROWS)


def band_mesh(fr: Dict[str, Any], offsets: np.ndarray, radius: np.ndarray, dirs: np.ndarray,
              thickness: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The closed band: per angle a rectangle of the inner rows (``radius`` + nothing — the caller adds the gap)
    and the outer rows ``thickness`` farther out. ``(V (n·2·rows, 3), F, vertex normals)``."""
    from app.core.accessory_curve import vertex_normals
    rows, n = radius.shape
    axis = fr["axis"]
    inner = fr["centre"][None, None] + offsets[:, None, None] * axis[None, None] + radius[:, :, None] * dirs[None]
    outer = inner + thickness * dirs[None]
    # per angle: inner bottom -> top, then outer top -> bottom (a closed profile)
    prof = np.concatenate([inner, outer[::-1]], 0)            # (2·rows, n, 3)
    m = prof.shape[0]
    V = prof.transpose(1, 0, 2).reshape(-1, 3)               # angle-major
    i = np.arange(n)[:, None]
    j = np.arange(m)[None, :]
    a = i * m + j
    b = ((i + 1) % n) * m + j
    c = ((i + 1) % n) * m + (j + 1) % m
    d = i * m + (j + 1) % m
    F = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    F = orient_outward(V, F)
    return V, F, vertex_normals(V, F)


def orient_outward(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    """``F`` wound so the closed mesh's signed volume is positive (normals out)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum())
    return F[:, ::-1].copy() if vol < 0 else F


def ring_curve(fr: Dict[str, Any], radius: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    """The centre line of a tube at ``radius`` (n,) around the axis."""
    return fr["centre"][None] + radius[:, None] * dirs


def _nearest(X: np.ndarray, out_dirs: np.ndarray, surfaces: List[Tuple[np.ndarray, np.ndarray]]):
    """Per point of ``X`` the closest point on the nearest of ``surfaces`` and the signed distance to it: the first
    surface is the body (outward wound: signed by its face normal), the others garments (signed by ``out_dirs``)."""
    from scipy.spatial import cKDTree
    from app.core.accessory_curve import _closest
    best = np.full(len(X), np.inf)
    sign = np.ones(len(X))
    near = np.array(X, np.float64)
    for k, (P, F) in enumerate(surfaces):
        P = np.asarray(P, np.float64)
        Fc = _crop(P, np.asarray(F, np.int64), X.mean(0), float(np.ptp(X, 0).max()) / 2 + 0.05)
        if not len(Fc):
            continue
        cp, which = _closest(X, P, Fc, cKDTree(P[Fc].mean(1)), faces=True)
        d = np.linalg.norm(X - cp, axis=1)
        if k == 0:
            # the body (outward wound): the side by the closest face's own normal — exact on a slope (a trapezius
            # under a choker's edge), where the piece's outward direction is not the surface's
            f = Fc[which]
            n = np.cross(P[f[:, 1]] - P[f[:, 0]], P[f[:, 2]] - P[f[:, 0]])
            s = np.where(np.einsum("ij,ij->i", X - cp, n) < 0, -1.0, 1.0)
        else:
            # a garment (its winding not known): the piece's outward direction
            s = np.where(np.einsum("ij,ij->i", X - cp, out_dirs) < 0, -1.0, 1.0)
        closer = d < best
        best = np.where(closer, d, best)
        sign = np.where(closer, s, sign)
        near = np.where(closer[:, None], cp, near)
    return near, best * sign


def surface_gap(X: np.ndarray, out_dirs: np.ndarray, surfaces: List[Tuple[np.ndarray, np.ndarray]]
                ) -> np.ndarray:
    """Per point of ``X`` the signed distance to the nearest of ``surfaces`` (each ``(P, F)``), positive on the side
    of ``out_dirs`` (per point) — the air under a piece over the layer it sits on."""
    return _nearest(np.asarray(X, np.float64), out_dirs, surfaces)[1]


def push_out(X: np.ndarray, out_dirs: np.ndarray, surfaces: List[Tuple[np.ndarray, np.ndarray]],
             clearance: float, passes: int = 4) -> np.ndarray:
    """Every point of ``X`` closer than ``clearance`` to ``surfaces`` (or behind them) put ``clearance`` off its
    closest surface point, away from it (on the ``out_dirs`` side) — along the surface's normal, so a point over a
    slope (a trapezius beside a choker) clears it too; a point already farther out stays."""
    X = np.array(X, np.float64)
    for _ in range(passes):
        cp, g = _nearest(X, out_dirs, surfaces)
        short = g < clearance
        if not short.any():
            break
        away = X[short] - cp[short]
        n = np.linalg.norm(away, axis=1, keepdims=True)
        away = np.where(n > 1e-9, away / np.maximum(n, 1e-12), out_dirs[short])
        away = np.where((g[short] < 0)[:, None], -away, away)
        X[short] = cp[short] + away * clearance
    return X


# --- earrings -----------------------------------------------------------------------------------------------------

def ear_anchor(P: np.ndarray, dense: np.ndarray, joint_names: Sequence[str], bones: Dict[str, Any],
               side: str) -> Dict[str, Any]:
    """The ear lobe of ``side`` (module docstring): the ear is the head skin that stands out farthest to that side in
    the box ``EAR_BOX`` round the Head bone head (above it, at or behind its front); the lobe is the lowest point of
    the ear's rim (head skin within ``EAR_RIM_M`` of that farthest x), raised ``LOBE_UP_M``. ``{point, outward,
    lobe_y, top_y, front_z, back_z}`` — the rim's highest point and its front-most / back-most z (where a glasses
    temple goes over the ear); ``ValueError`` without head skin there."""
    from app.core.rig_contract import norm_bone_name
    head = _bone(bones, "head")
    P = np.asarray(P, np.float64)
    names = np.array([norm_bone_name(str(n)) for n in joint_names])
    on_head = names[np.asarray(dense).argmax(1)] == "head"
    sx = 1.0 if side == "left" else -1.0       # +X = the body's left
    (y0, y1), (z0, z1) = EAR_BOX
    box = on_head & (P[:, 1] >= head[1] + y0) & (P[:, 1] <= head[1] + y1) \
        & (P[:, 2] >= head[2] + z0) & (P[:, 2] <= head[2] + z1) & ((P[:, 0] - head[0]) * sx > 0)
    if not box.any():
        raise ValueError(f"The {side} ear was not found on this body")
    lateral = (P[:, 0] - head[0]) * sx
    far = float(lateral[box].max())
    rim = box & (lateral >= far - EAR_RIM_M)
    k = np.flatnonzero(rim)[int(np.argmin(P[rim, 1]))]
    point = P[k].copy()
    point[1] += LOBE_UP_M
    return {"point": point, "outward": np.array([sx, 0.0, 0.0]), "lobe_y": round(float(point[1]), 4),
            "top_y": float(P[rim, 1].max()), "front_z": float(P[rim, 2].max()), "back_z": float(P[rim, 2].min())}


def clear_lateral(P: np.ndarray, point: np.ndarray, side: str, below_m: float, half_width_m: float) -> float:
    """How far to the ``side`` (+x left, −x right, unsigned) the skin reaches in the window under ``point`` — from
    ``below_m`` under it to 2 mm above, ``half_width_m`` to the front and back — so a hoop or a drop hanging there
    is put beside the jaw, not into it. At least the point's own lateral offset."""
    sx = 1.0 if side == "left" else -1.0
    P = np.asarray(P, np.float64)
    win = (P[:, 1] <= point[1] + 0.002) & (P[:, 1] >= point[1] - below_m) & (np.abs(P[:, 2] - point[2]) <= half_width_m) \
        & ((P[:, 0] - point[0]) * sx > -0.03)
    reach = float((P[win, 0] * sx).max()) if win.any() else float(point[0] * sx)
    return max(reach, float(point[0] * sx))


def icosphere(radius: float, subdiv: int = 1) -> Tuple[np.ndarray, np.ndarray]:
    """A unit-ish sphere (outward faces) scaled to ``radius``."""
    t = (1 + 5 ** 0.5) / 2
    V = np.array([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
                  [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], np.float64)
    F = np.array([[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2],
                  [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5],
                  [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]], np.int64)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    for _ in range(subdiv):
        cache: Dict[Tuple[int, int], int] = {}
        verts = list(V)

        def mid(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = (verts[a] + verts[b]) / 2
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]
        newF = []
        for a, b, c in F:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            newF += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        V, F = np.array(verts), np.array(newF, np.int64)
    return V * radius, orient_outward(V * radius, F)


def torus(centre: np.ndarray, normal: np.ndarray, major: float, minor: float, n: int = 32,
          sides: int = 8) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A torus (``accessory_mesh.tube`` around a circle of ``major`` radius in the plane across ``normal``)."""
    from app.core.accessory_mesh import tube
    normal = _unit(normal)
    u = _unit(np.cross(normal, [0.0, 1.0, 0.0]) if abs(normal[1]) < 0.9 else np.cross(normal, [1.0, 0.0, 0.0]))
    v = np.cross(normal, u)
    phi = 2 * np.pi * np.arange(n) / n
    dirs = np.cos(phi)[:, None] * u + np.sin(phi)[:, None] * v
    return tube(centre[None] + major * dirs, minor, sides, outward=dirs)
