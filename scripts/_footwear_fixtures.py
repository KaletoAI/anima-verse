"""Synthetic shoe meshes shared by the footwear smoke scripts; no storage imports.

The wedge pump (plan docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 5 Step 1), in the
mesher's own coordinates (Y up, x heel -> toe, z lateral), length 0.26, width 0.08:

- sole solid over the full width: top h(x) = 0.09 on [0, 0.05], linear to 0.01 at 0.15, 0.01 on
  [0.15, 0.26]; bottom at 0 (facing down); end faces at x = 0 and x = 0.26;
- zero-thickness side walls at z = +-0.04 from the ground up to h(x) + 0.03, tessellated every 0.01;
- a vamp roof (facing up) at h(x) + 0.03 over x in [roof_from, 0.26] (0.18 = the closed pump,
  0.24 = the sandal variant);
- optionally a thin vertical fin at z = 0 over the toe end rising to 0.15 (vertical, so no ray hits it and
  the topline ignores it because it sits at z = 0) that makes the TOE end the taller one for the
  provisional heel rule;
- ``solid=True``: the closed solid wedge — the sole alone (side faces from the ground to h(x), no walls above
  it, no roof), i.e. a mesher result whose top surface would be read as the insole.

Every quad is two triangles over the 0.01 x-grid; each face is wound so its normal points outward
(up for the sole top and the roof, down for the bottom, +-z for the walls).
"""
import numpy as np

LENGTH = 0.26
HALF_W = 0.04
WALL = 0.03


def h(x: float) -> float:
    """Top of the sole (the insole) at ``x``."""
    if x <= 0.05:
        return 0.09
    if x <= 0.15:
        return 0.09 - 0.8 * (x - 0.05)
    return 0.01


def wedge(roof_from: float = 0.18, *, fin: bool = False, rotate_180: bool = False, solid: bool = False):
    """``(positions (N, 3), faces (M, 3))`` of the wedge pump (module docstring)."""
    P, F = [], []

    def tri(a, b, c, facing):
        a, b, c = (np.asarray(v, np.float64) for v in (a, b, c))
        n = np.cross(b - a, c - a)
        if np.dot(n, facing) < 0:
            b, c = c, b
        base = len(P)
        P.extend([a, b, c])
        F.append((base, base + 1, base + 2))

    def quad(p00, p10, p11, p01, facing):
        tri(p00, p10, p11, facing)
        tri(p00, p11, p01, facing)

    xs = [round(0.01 * i, 10) for i in range(27)]
    up, down = (0, 1, 0), (0, -1, 0)
    wall = 0.0 if solid else WALL
    for x0, x1 in zip(xs[:-1], xs[1:]):
        h0, h1 = h(x0), h(x1)
        # sole top and bottom over the full width
        quad((x0, h0, -HALF_W), (x1, h1, -HALF_W), (x1, h1, HALF_W), (x0, h0, HALF_W), up)
        quad((x0, 0, -HALF_W), (x1, 0, -HALF_W), (x1, 0, HALF_W), (x0, 0, HALF_W), down)
        # side walls from the ground to h + WALL (to h for the solid wedge)
        for z, facing in ((HALF_W, (0, 0, 1)), (-HALF_W, (0, 0, -1))):
            quad((x0, 0, z), (x1, 0, z), (x1, h1 + wall, z), (x0, h0 + wall, z), facing)
        if not solid and x0 >= roof_from - 1e-9:
            quad((x0, h0 + WALL, -HALF_W), (x1, h1 + WALL, -HALF_W), (x1, h1 + WALL, HALF_W),
                 (x0, h0 + WALL, HALF_W), up)
    # end faces of the sole
    quad((0, 0, -HALF_W), (0, h(0), -HALF_W), (0, h(0), HALF_W), (0, 0, HALF_W), (-1, 0, 0))
    quad((LENGTH, 0, -HALF_W), (LENGTH, h(LENGTH), -HALF_W), (LENGTH, h(LENGTH), HALF_W), (LENGTH, 0, HALF_W),
         (1, 0, 0))
    if fin:
        quad((0.24, 0.04, 0), (LENGTH, 0.04, 0), (LENGTH, 0.15, 0), (0.24, 0.15, 0), (0, 0, 1))
    positions = np.asarray(P, np.float64)
    if rotate_180:                        # 180 deg about Y: (x, y, z) -> (-x, y, -z), winding kept
        positions = positions * np.array([-1.0, 1.0, -1.0])
    return positions, np.asarray(F, np.int64)
