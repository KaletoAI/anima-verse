"""Smoke: the shell's body samples are the same points in less memory, and a region skinned to fewer than 4 joints
gives (n, 4) skin arrays (A198, review 06 #4 / #7, 06B #3).

Usage:
    ./.venv/bin/python scripts/smoke_shell_samples_joints.py

No server, no world DB, synthetic arrays. Derived by hand:
  [1] ``samples`` before A198 (the formula below, copied from e846d7d02) and now draw r1, r2 from the same seeded
      generator in the same order and evaluate X = A·a + B·b + C·c per element -> X, tri and bary equal BIT FOR BIT,
      also across a chunk border (``SAMPLE_CHUNK`` set to 7 so a 2-face mesh with ~40 samples spans several chunks).
  [2] ``_posed_samples`` == einsum over the whole gather.
  [3] two joint columns, weights per vertex (0.75, 0.25) and (0, 1): -> joints (n, 4), weights (n, 4):
      row 0 joints [0, 1, 0, 0] weights [0.75, 0.25, 0, 0]; row 1 joints [1, 0, 0, 0] weights [1, 0, 0, 0];
      used columns [0, 1]. Pre-fix (e846d7d02) the inline code gave (n, 2) arrays and ``glb_mesh`` refused them.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_shell as gsh  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


def old_samples(P, F, px, seed=1):
    rng = np.random.default_rng(seed)
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    N = np.cross(B - A, C - A)
    area = np.linalg.norm(N, axis=1) / 2
    n = np.clip(np.ceil(area / (px * px) * 4).astype(int), 1, 600)
    tri = np.repeat(np.arange(len(F)), n)
    r1, r2 = rng.random(len(tri)), rng.random(len(tri))
    s = np.sqrt(r1)
    a, b, c = 1 - s, s * (1 - r2), s * r2
    X = A[tri] * a[:, None] + B[tri] * b[:, None] + C[tri] * c[:, None]
    return X, tri, np.stack([a, b, c], 1)


P = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0.02], [0.1, 0.1, 0.05]], np.float32)
F = np.array([[0, 1, 2], [1, 3, 2]])
gsh.SAMPLE_CHUNK = 7
X0, t0, b0 = old_samples(P, F, 0.03)
X1, n1, t1, b1 = gsh.samples(P, F, 0.03)
check("[1] more samples than one chunk", len(t0) > 2 * gsh.SAMPLE_CHUNK, len(t0))
check("[1] X bit for bit", X0.dtype == X1.dtype and np.array_equal(X0, X1), (X0.dtype, X1.dtype))
check("[1] tri, bary equal; no normals", np.array_equal(t0, t1) and np.array_equal(b0, b1) and n1 is None)
Pp = P.astype(np.float64) + 0.5
check("[2] posed samples", np.allclose(gsh._posed_samples(b1, Pp, F, t1), np.einsum("nk,nkj->nj", b1, Pp[F[t1]]),
                                        rtol=0, atol=0))
Wc = np.array([[0.75, 0.25], [0.0, 1.0]])
J, W, used = gsh.top4_weights(Wc)
check("[3] shapes (2, 4)", J.shape == (2, 4) and W.shape == (2, 4), (J.shape, W.shape))
check("[3] row 0", J[0].tolist() == [0, 1, 0, 0] and np.allclose(W[0], [0.75, 0.25, 0, 0]), (J[0], W[0]))
check("[3] row 1", J[1].tolist() == [1, 0, 0, 0] and np.allclose(W[1], [1, 0, 0, 0]), (J[1], W[1]))
check("[3] used columns", used.tolist() == [0, 1], used)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
