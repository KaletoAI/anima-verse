"""Insole and heel analysis of a shoe mesh (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.4).

Task 3 adds the shoe frame (``shoe_frame``), which the side-silhouette gate
projects on; the pure numpy insole analysis lands in Task 5, which also flips
the provisional heel end after tracking.
"""
from dataclasses import dataclass

import numpy as np

#: Bumped when the analysis changes what it measures (part of the footwear fsig).
INSOLE_VERSION = 1

#: Share of the length at each end whose height decides the provisional heel.
HEEL_END_SHARE = 0.15


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
