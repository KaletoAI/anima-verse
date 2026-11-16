"""A tall boot shaft fitted as a shoe part plus a leg part (Ruling A122).

A clothing piece whose slots hold both ``feet`` and ``legs`` (``applies``) — a boot whose shaft runs past the knee —
is fitted by ``garment_fit.fit_clothing`` as clothing (``garment_set.garment_kind_of``). This module splits the
fitted pair afterwards (``split``), on the CPU, from the same prepared mesh (a re-fit spends 0 hub jobs):

- **Sides.** Each connected component belongs to the side whose Foot joint its centroid x lies nearer to; a
  component is never cut in two by the side rule. Heights ``h`` per side are metres above that
  side's lowest vertex (the sole).
- **Shoe part** — every face whose centroid lies at ``h <= SHOE_TOP_M``. ``SHOE_TOP_M`` is the top of the footwear
  path's rigid region: the knee-high class limit ``footwear_insole.SHAFT_CLASS_M["knee"]`` (0.48 m), the highest
  collar the boots spec (2026-11-11 § 6) fits with a rigid foot part and a shaft on the shin. Weights as that
  path's boot split (spec § 6.2/6.3): below the wearer's ankle (the side's Foot joint height above the sole) minus
  ``footwear_fit.SPLIT_BAND_M`` the foot part on the side's Foot / ToeBase only, above the ankle plus the band the
  shaft on the side's Leg / UpLeg only (``garment_fit.clothing_weights`` with ``columns``), smoothstep across the
  band.
- **Leg part** (``split`` only) — every face whose centroid lies at ``h >= CUT_M`` = ``SHOE_TOP_M - OVERLAP_M``:
  the shaft above the cut, and the ``OVERLAP_M`` (0.20 m, the user's rule) below the shoe top a second time. It is
  skinned to its OWN leg only (Leg / UpLeg of its side) by the same call as the shoe's shaft, so in the overlap both
  parts carry the same weights at the same points and move together in every pose: no seam can open where they
  meet. The leg part stands ``LEG_OVER_M`` outward along its normals (turned away from the nearest body point) so
  the two surfaces do not fight for the same pixels.
- **cut** (``SHAFT_CHOICES``) — the shoe part only: everything above the shoe top is dropped.

The pair-aware component gate (``garment_fit.pair_share``) judges the fitted pair before the split; the split's
numbers go to ``report["shaft"]``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

#: The per-piece choice (fit setting ``shaft``): keep the shaft above the shoe as a leg part, or cut it off.
SPLIT = "split"
CUT = "cut"
SHAFT_CHOICES: Tuple[str, ...] = (SPLIT, CUT)
#: The overlap of leg part and shoe part (the user's rule: "mit 20 cm Überlappung").
OVERLAP_M = 0.20
#: How far the leg part stands outside the shoe part (along its normals).
LEG_OVER_M = 0.002

FEET, LEGS = "feet", "legs"


def shoe_top_m() -> float:
    """The top of the footwear path's rigid region: the knee-high shaft class limit (m above the heel seat)."""
    from app.core.footwear_insole import SHAFT_CLASS_M
    return float(SHAFT_CLASS_M["knee"])


def cut_m() -> float:
    """Where the leg part begins: the shoe top minus the overlap."""
    return shoe_top_m() - OVERLAP_M


def applies(slots: Optional[Sequence[str]]) -> bool:
    """A piece covering the feet AND the legs: a boot whose shaft goes past the shoe."""
    s = set(slots or [])
    return FEET in s and LEGS in s


def shaft_choice(settings: Optional[Dict[str, Any]]) -> str:
    """The piece's fit setting ``shaft`` (``SHAFT_CHOICES``); missing or unknown = ``split``."""
    value = (settings or {}).get("shaft")
    return value if isinstance(value, str) and value in SHAFT_CHOICES else SPLIT


def _smoothstep(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _index(body, key: str) -> int:
    from app.core.rig_contract import norm_bone_name
    for i, name in enumerate(body.joint_names):
        if norm_bone_name(name) == key:
            return i
    raise ValueError(f"The body has no joint '{key}'")


def sides_of(P: np.ndarray, F: np.ndarray, left_x: float, right_x: float) -> np.ndarray:
    """Per vertex ``"left"`` / ``"right"``: the side whose Foot joint x (``left_x`` / ``right_x``) its component's
    area centroid x lies nearer to."""
    from app.core.garment_fit import components, triangle_areas
    labels, _share = components(P, F)
    count = int(labels.max()) + 1 if len(labels) else 0
    area = triangle_areas(P, F)
    cx = (P[F[:, 0], 0] + P[F[:, 1], 0] + P[F[:, 2], 0]) / 3.0
    lab = labels[F[:, 0]]
    sx = np.bincount(lab, weights=area * cx, minlength=count)
    sa = np.bincount(lab, weights=area, minlength=count)
    comp_x = np.where(sa > 0, sx / np.maximum(sa, 1e-18), 0.5 * (left_x + right_x))
    return np.where(np.abs(comp_x[labels] - left_x) <= np.abs(comp_x[labels] - right_x), "left", "right")


def split(garment, body, joints: Dict[str, np.ndarray], mode: str) -> Tuple[Any, Dict[str, Any]]:
    """The fitted pair ``garment`` (``glb_mesh.GarmentMesh`` on the rigged ``body``; ``joints`` =
    ``glb_mesh.joint_bind_matrices`` of the rigged body) as shoe part + leg part (``SPLIT``) or shoe part alone
    (``CUT``) — module docstring. Returns ``(new GarmentMesh, report)``."""
    from app.core.footwear_fit import SPLIT_BAND_M
    from app.core.garment_fit import clothing_weights, vertex_normals
    from app.core.glb_mesh import GarmentMesh
    P = np.asarray(garment.positions, np.float64)
    F = np.asarray(garment.indices, np.int64).reshape(-1, 3)
    U = np.asarray(garment.uvs, np.float64)
    ankles = {s: np.asarray(joints[f"{s}foot"], np.float64)[:3, 3] for s in ("left", "right")}
    knees = {s: np.asarray(joints[f"{s}leg"], np.float64)[:3, 3] for s in ("left", "right")}
    side = sides_of(P, F, float(ankles["left"][0]), float(ankles["right"][0]))
    top, cut = shoe_top_m(), cut_m()
    h = np.zeros(len(P))
    floors: Dict[str, float] = {}
    for s in ("left", "right"):
        on = side == s
        floors[s] = float(P[on, 1].min()) if on.any() else float(P[:, 1].min())
        h[on] = P[on, 1] - floors[s]
    fh = h[F].mean(1)
    face_side = side[F[:, 0]]
    shoe_f = fh <= top
    leg_f = (fh >= cut) if mode == SPLIT else np.zeros(len(F), bool)

    # dense weights over the body's joints
    n_j = len(body.joint_names)

    def dense(points: np.ndarray, columns: List[int]) -> np.ndarray:
        out = np.zeros((len(points), n_j))
        if not len(points):
            return out
        J, W = clothing_weights(points, body, skirt=False, columns=columns)
        np.add.at(out, (np.repeat(np.arange(len(points)), 4), J.ravel()), W.ravel())
        return out

    def part(face_mask: np.ndarray, leg: bool):
        Fp = F[face_mask]
        used = np.unique(Fp)
        remap = np.full(len(P), -1, np.int64)
        remap[used] = np.arange(len(used))
        Wd = np.zeros((len(used), n_j))
        sides_used = side[used]
        for s in ("left", "right"):
            rows = np.nonzero(sides_used == s)[0]
            if not len(rows):
                continue
            X = P[used[rows]]
            shaft = dense(X, [_index(body, f"{s}leg"), _index(body, f"{s}upleg")])
            if leg:
                Wd[rows] = shaft
                continue
            y_ankle = float(ankles[s][1]) - floors[s]
            sb = _smoothstep((h[used[rows]] - (y_ankle - SPLIT_BAND_M)) / (2.0 * SPLIT_BAND_M))[:, None]
            foot = dense(X, [_index(body, f"{s}foot"), _index(body, f"{s}toebase")])
            Wd[rows] = (1.0 - sb) * foot + sb * shaft
        return used, remap[Fp], Wd

    parts = [part(shoe_f, False)]
    if leg_f.any():
        parts.append(part(leg_f, True))
    positions, uvs, faces, dense_w, is_leg = [], [], [], [], []
    base = 0
    for i, (used, Fp, Wd) in enumerate(parts):
        X = P[used].copy()
        if i == 1:
            # outward = away from the nearest body point (the mesh's winding is not trusted)
            from scipy.spatial import cKDTree
            N = vertex_normals(P, F[leg_f])[used]
            away = X - np.asarray(body.positions, np.float64)[cKDTree(body.positions).query(X)[1]]
            N = np.where(((N * away).sum(1) < 0)[:, None], -N, N)
            X = X + N * LEG_OVER_M
        positions.append(X)
        uvs.append(U[used])
        faces.append(Fp + base)
        dense_w.append(Wd)
        is_leg.append(np.full(len(used), i == 1))
        base += len(used)
    Xo = np.concatenate(positions)
    Fo = np.concatenate(faces)
    Wo = np.concatenate(dense_w)
    cols = np.nonzero(Wo.sum(0) > 0)[0]
    Wc = Wo[:, cols]
    J = np.argsort(-Wc, 1, kind="stable")[:, :4]
    top4 = np.take_along_axis(Wc, J, 1)
    top4 /= np.maximum(top4.sum(1, keepdims=True), 1e-12)
    J = np.where(top4 > 0, J, 0)
    names = [body.joint_names[c] for c in cols]
    out = GarmentMesh(positions=Xo, normals=vertex_normals(Xo, Fo), uvs=np.concatenate(uvs), indices=Fo,
                      joints=J.astype(np.int64), weights=top4, joint_names=names, image=garment.image,
                      mime=garment.mime, material=garment.material, mr_image=garment.mr_image,
                      mr_mime=garment.mr_mime)
    report: Dict[str, Any] = {
        "mode": mode, "shoe_top_mm": round(top * 1000.0), "cut_mm": round(cut * 1000.0) if mode == SPLIT else None,
        "overlap_mm": round(OVERLAP_M * 1000.0) if mode == SPLIT else 0,
        "faces": {"in": int(len(F)), "shoe": int(shoe_f.sum()), "leg": int(leg_f.sum()),
                  "overlap": int((shoe_f & leg_f).sum()), "dropped": int((~shoe_f & ~leg_f).sum())},
        "sides": {s: {"shoe_faces": int((shoe_f & (face_side == s)).sum()),
                      "leg_faces": int((leg_f & (face_side == s)).sum()),
                      "ankle_mm": round((float(ankles[s][1]) - floors[s]) * 1000.0),
                      "knee_mm": round((float(knees[s][1]) - floors[s]) * 1000.0),
                      "top_mm": round(float(h[side == s].max()) * 1000.0) if (side == s).any() else None}
                  for s in ("left", "right")},
        "leg_vertices": int(np.concatenate(is_leg).sum()),
        "dropped_above_mm": round(top * 1000.0) if mode == CUT else None,
    }
    return out, report
