"""Accessory geometry (Ruling A118, plan Task 5): a closed tube swept along a curve, skinned with the weights of
the nearest body vertices, as a ``glb_mesh.GarmentMesh`` the garment assembly grafts like any garment node.

Pure numpy; positions in the body's bind space (metres).
"""
from typing import Any, Dict, List, Tuple

import numpy as np

#: Sides of the tube's cross-section (spec § 4: a thin chain needs no more at game distance).
TUBE_SIDES = 8
#: Body vertices whose weights are blended per accessory vertex (``skin_weights``, the shell's top-4 rule after).
WEIGHT_NEIGHBOURS = 8


def frames(curve: np.ndarray, outward: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(T, N, B)`` per point of the closed ``curve``: the central-difference tangent, ``outward`` made
    perpendicular to it (the surface normal side), and ``T × N``."""
    T = np.roll(curve, -1, 0) - np.roll(curve, 1, 0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    N = outward - np.einsum("ij,ij->i", outward, T)[:, None] * T
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    return T, N, np.cross(T, N)


def tube(curve: np.ndarray, radius_m: float, sides: int = TUBE_SIDES,
         outward: np.ndarray = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A closed tube of ``radius_m`` around the closed ``curve`` ``(k, 3)``: ``(V (k·sides, 3), F (2·k·sides, 3),
    vertex normals)``. ``outward`` (``(k, 3)``, default: away from the curve's centroid) orients the ring frames."""
    curve = np.asarray(curve, np.float64)
    k = len(curve)
    if outward is None:
        outward = curve - curve.mean(0)
    _T, N, B = frames(curve, np.asarray(outward, np.float64))
    ang = 2 * np.pi * np.arange(sides) / sides
    dirs = np.cos(ang)[None, :, None] * N[:, None, :] + np.sin(ang)[None, :, None] * B[:, None, :]
    V = (curve[:, None, :] + radius_m * dirs).reshape(-1, 3)
    i = np.arange(k)[:, None]
    j = np.arange(sides)[None, :]
    a = i * sides + j
    b = ((i + 1) % k) * sides + j
    c = ((i + 1) % k) * sides + (j + 1) % sides
    d = i * sides + (j + 1) % sides
    F = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([a, d, c], -1).reshape(-1, 3)])  # outward
    return V, F.astype(np.int64), dirs.reshape(-1, 3)


def skin_weights(X: np.ndarray, Pb: np.ndarray, Wb: np.ndarray,
                 k: int = WEIGHT_NEIGHBOURS) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The skin of the points ``X`` from the body vertices ``Pb`` with dense weights ``Wb`` ``(n, joints)``:
    inverse-distance blend of the ``k`` nearest body vertices (a coincident vertex takes that vertex's weights
    exactly), then ``garment_shell.top4_weights``. Returns ``(joints (m, 4) into the body skin, weights (m, 4))``."""
    from scipy.spatial import cKDTree
    from app.core.garment_shell import top4_weights
    d, idx = cKDTree(Pb).query(X, k=min(k, len(Pb)))
    d, idx = d.reshape(len(X), -1), idx.reshape(len(X), -1)
    w = 1.0 / np.maximum(d, 1e-9) ** 2
    exact = d[:, 0] < 1e-9
    w[exact] = 0.0
    w[exact, 0] = 1.0
    w /= w.sum(1, keepdims=True)
    Wc = np.einsum("mk,mkj->mj", w, Wb[idx])
    J, W, used = top4_weights(Wc)
    return used[J], W


def fold_to_base(J: np.ndarray, W: np.ndarray, joint_names: List[str], parents: Dict[str, str],
                 onto: Dict[str, str] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Every weight on a joint outside the base skeleton (``rig_contract.BASE_JOINT_KEYS``: an extension joint such
    as a breast tip) moved to its nearest base-skeleton ancestor (``parents``: joint name -> parent name), so the
    accessory grafts onto any skin of the same rig — an outfit body without the extension group included (A216
    review H1). Weights on one joint are summed; the result is renormalised. A weighted joint with no base ancestor
    raises ``ValueError``. ``onto`` (normalised base name -> normalised base name) then moves a base joint's weight
    to another one (the accessory's head -> neck)."""
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    index = {norm_bone_name(n): i for i, n in enumerate(joint_names)}

    def base_of(i: int) -> int:
        name, seen = str(joint_names[i]), set()
        while norm_bone_name(name) not in BASE_JOINT_KEYS:
            seen.add(name)
            name = parents.get(name, "")
            if not name or name in seen:
                raise ValueError(f"joint {joint_names[i]} has no base-skeleton ancestor")
        key = norm_bone_name(name)
        key = (onto or {}).get(key, key)
        at = index.get(key)
        if at is None:
            raise ValueError(f"the base joint {name} is not in the skin")
        return at

    J = np.asarray(J, np.int64)
    W = np.asarray(W, np.float64)
    mapped = {int(j): base_of(int(j)) for j in np.unique(J[W > 0])}
    J2 = np.zeros_like(J)
    W2 = np.zeros_like(W)
    for v in range(len(J)):
        acc: Dict[int, float] = {}
        for j, w in zip(J[v], W[v]):
            if w > 0:
                t = mapped[int(j)]
                acc[t] = acc.get(t, 0.0) + float(w)
        items = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        total = sum(w for _, w in items) or 1.0
        for k, (j, w) in enumerate(items):
            J2[v, k], W2[v, k] = j, w / total
    return J2, W2


def node_name(item_id: str, side: str = "c") -> str:
    """The grafted node of an accessory: ``garment_accessory_<item>_<side>`` (``c`` = centred; ``p`` = the
    necklace's pendant, A225; ``l`` / ``r`` for paired pieces later). The ``garment_`` prefix is what every reader keys a garment node by
    (``glb_mesh._is_garment_node``, scene-render ``isGarmentNode``) — never a body part."""
    return f"garment_accessory_{item_id}_{side}"


def garment_mesh(V: np.ndarray, F: np.ndarray, N: np.ndarray, joints: np.ndarray, weights: np.ndarray,
                 joint_names: List[str], *, color: str, roughness: float, metalness: float = 1.0):
    """The accessory as a ``glb_mesh.GarmentMesh``: ``metalness`` (1.0 a metal chain, 0.0 a cord — A225), the base
    colour ``color`` (sRGB hex) as a factor, no texture, single-sided."""
    from app.core.accessory_spec import srgb_to_linear
    from app.core.glb_mesh import GarmentMesh
    material: Dict[str, Any] = {"name": "accessory",
                                "pbrMetallicRoughness": {"baseColorFactor": [*srgb_to_linear(color), 1.0],
                                                         "metallicFactor": float(metalness), "roughnessFactor": float(roughness)}}
    return GarmentMesh(positions=np.asarray(V, np.float64), normals=np.asarray(N, np.float64),
                       uvs=np.zeros((len(V), 2)), indices=np.asarray(F, np.int64),
                       joints=np.asarray(joints, np.int64), weights=np.asarray(weights, np.float64),
                       joint_names=list(joint_names), material=material)
