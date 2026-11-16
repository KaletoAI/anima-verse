"""numpy 2 compatibility of the vendored pygarment (added for Anima Verse): numpy 2 refuses
``np.cross`` of 2-D vectors, which pygarment uses for the z component of a planar cross product."""
import numpy as np


def cross(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape[-1] == 2 and b.shape[-1] == 2:
        return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    return np.cross(a, b)
