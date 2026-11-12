"""Grid kernels of the garment / footwear fits (``garment_fit.body_sdf``).

``fill_slices`` is the 2-D hole fill of every slice of a voxel mask along one axis, done as ONE labelling of the
whole grid instead of a Python loop over the slices (plan 2026-11-12 fit-sdf-speed-drape, Task 1).
"""
from __future__ import annotations

import numpy as np


def fill_slices(surf: np.ndarray, axis: int) -> np.ndarray:
    """``surf`` plus the holes of every 2-D slice perpendicular to ``axis`` — equal to
    ``ndimage.binary_fill_holes`` applied to each slice ``surf[..., j, ...]`` on its own.

    One ``ndimage.label(~surf, structure=s)`` call, where ``s`` is the 2-D cross in the plane perpendicular to
    ``axis`` (zero along ``axis``), so no component reaches across slices. A background component that touches
    one of the slice's four in-plane borders is outside (``binary_fill_holes`` seeds its outside from the border
    with the same cross connectivity); every other background component is a hole and is filled.
    """
    from scipy import ndimage
    surf = np.asarray(surf, bool)
    if surf.ndim != 3:
        raise ValueError("fill_slices needs a 3-D mask")
    axis = int(axis) % 3
    s = np.zeros((3, 3, 3), bool)
    centre = [slice(1, 2)] * 3
    for other in range(3):
        if other == axis:
            continue
        line = list(centre)
        line[other] = slice(None)
        s[tuple(line)] = True
    labels, n = ndimage.label(~surf, structure=s)
    if n == 0:
        return surf.copy()
    border = np.zeros(n + 1, bool)
    for other in range(3):
        if other == axis:
            continue
        for end in (0, -1):
            border[np.take(labels, end, axis=other)] = True
    border[0] = True                                            # label 0 = the surface itself
    return surf | ~border[labels]
