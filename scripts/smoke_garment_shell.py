"""Smoke: Ruling A48d — the mesh shape "Shell from the body" (``app/core/garment_shell.py``).

Usage: ./.venv/bin/python scripts/smoke_garment_shell.py   (no server, no world; pure functions + monkeypatched items)

Expected values, derived by hand:

[1] Auto rule table (``auto_reason``): slots ⊆ {underwear_top, underwear_bottom, legs}, no ``covers``, not closable
    → shell. underwear_top → shell/close_slots; underwear_bottom → shell; legs → shell; [underwear_top, top] →
    as_generated/loose_slot ["top"]; outer (a blazer) → as_generated/loose_slot ["outer"]; bottom (a skirt) →
    as_generated; underwear_top covering underwear_bottom → as_generated/covers; underwear_top closable →
    as_generated/closable; no slots → as_generated/no_slots.
[2] Region → shell faces: a region of n body faces, two midpoint subdivisions → 16·n faces (each split makes 4);
    clipped with a scalar >= 0 everywhere it keeps all 16·n. Here n = 2 (a unit square of two triangles) → 32.
[3] Clip by marching triangles: the triangle (0,0),(1,0),(0,1) with s = (1, -1, -1) keeps the corner triangle up
    to the zero crossings at t = 1/2 → area 0.5·0.5·0.5 = 0.125; with s = (-1, 1, 1) keeps the rest 0.5 − 0.125 =
    0.375 as two triangles.
[4] Outer wall only: a closed cube of side 1 (12 triangles) with a second closed cube of side 0.5 inside it (12
    triangles): from all 26 directions only the outer cube is front-most → 12 outer faces, the inner 12 never.
[5] Inside share 0: points 4 mm outside a unit sphere mesh → 0.0; points 0.1 inside → 1.0 (> 2 mm under).
[6] Due-ness (``garment_fit_settings.changed``): a fit made as generated (no ``inputs.mesh_shape``) with default
    settings — for the underwear piece Auto now resolves to shell → due; for the outer piece → not due; the
    outer piece set explicitly to as_generated → still not due (same made shape); a shell fit of the underwear
    piece under Auto → not due; setting the underwear piece's shape leaves the other piece's verdict unchanged
    (settings are keyed per item).
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_garment_shell_")
os.environ.setdefault("STORAGE_DIR", TMP)
from app.core import paths  # noqa: E402

paths.init(TMP)
import numpy as np  # noqa: E402

from app.core import garment_shell as gsh  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def item(slots, covers=(), closable=False):
    return {"category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "covers": list(covers), "closable": closable}}


# [1]
table = [
    (item(["underwear_top"]), "shell", "close_slots"),
    (item(["underwear_bottom"]), "shell", "close_slots"),
    (item(["legs"]), "shell", "close_slots"),
    (item(["underwear_top", "top"]), "as_generated", "loose_slot"),
    (item(["outer"]), "as_generated", "loose_slot"),
    (item(["bottom"]), "as_generated", "loose_slot"),
    (item(["underwear_top"], covers=["underwear_bottom"]), "as_generated", "covers"),
    (item(["underwear_top"], closable=True), "as_generated", "closable"),
    (item([]), "as_generated", "no_slots"),
]
for it, shape, reason in table:
    got = gsh.auto_reason(it)
    check(f"[1] auto {it['outfit_piece']['slots']} {it['outfit_piece']['covers']} "
          f"closable={it['outfit_piece']['closable']}", got[:2] == (shape, reason), str(got))
check("[1] loose slots named", gsh.auto_reason(item(["underwear_top", "top"]))[2] == {"slots": ["top"]})

# [2]
V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
F = np.array([[0, 1, 2], [0, 2, 3]])
A = V[:, :2].copy()
for _ in range(2):
    V, F, A = gsh.subdivide(V, F, A)
check("[2] 2 faces → 32 after two subdivisions", len(F) == 32, str(len(F)))
Vc, Fc, _ = gsh.clip_triangles(V, F, np.ones(len(V)), A)
check("[2] positive scalar keeps all 32", len(Fc) == 32, str(len(Fc)))


def area(P, F):
    return float(0.5 * np.abs(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])).sum())


# [3]
T = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
TF = np.array([[0, 1, 2]])
P1, F1, _ = gsh.clip_triangles(T, TF, np.array([1.0, -1, -1]), T[:, :2])
check("[3] corner kept area 0.125", abs(area(P1, F1) - 0.125) < 1e-12, f"{area(P1, F1)}")
P2, F2, _ = gsh.clip_triangles(T, TF, np.array([-1.0, 1, 1]), T[:, :2])
check("[3] rest kept area 0.375 in 2 triangles", abs(area(P2, F2) - 0.375) < 1e-12 and len(F2) == 2,
      f"{area(P2, F2)} / {len(F2)}")


# [4]
def cube(s, c=0.0):
    v = np.array([[x, y, z] for x in (-s / 2, s / 2) for y in (-s / 2, s / 2) for z in (-s / 2, s / 2)]) + c
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return v, f


vo, fo = cube(1.0)
vi, fi = cube(0.5)
P = np.vstack([vo, vi])
Fb = np.vstack([fo, fi + 8])
outer = gsh.outer_faces(P, Fb, px=0.1, tol=0.01)   # ~12 samples per pixel (600 per face cap)
check("[4] outer faces = the 12 of the outer cube", outer[:12].all() and not outer[12:].any(),
      f"{int(outer[:12].sum())} / {int(outer[12:].sum())}")

# [5]
u = np.random.default_rng(3).normal(size=(2000, 3))
u /= np.linalg.norm(u, axis=1, keepdims=True)
from scipy.spatial import ConvexHull  # noqa: E402
hull = ConvexHull(u)
SF = hull.simplices.copy()
c = u[SF].mean(1)
n = np.cross(u[SF[:, 1]] - u[SF[:, 0]], u[SF[:, 2]] - u[SF[:, 0]])
flip = (n * c).sum(1) < 0
SF[flip] = SF[flip][:, ::-1]
probe = u[:300]
check("[5] 4 mm outside → inside share 0", gsh.inside_share(probe * 1.004 + 0.0, u, SF) == 0.0)
check("[5] 0.1 inside → inside share 1", gsh.inside_share(probe * 0.9, u, SF) == 1.0)

# [6]
from app.core import garment_fit_settings as gfs  # noqa: E402
import app.models.inventory as inv  # noqa: E402
ITEMS = {"item_under": item(["underwear_top"]), "item_outer": item(["outer"])}
inv.get_item = lambda iid: ITEMS.get(iid)
generated = {"inputs": {"fit_settings": gfs.defaults()}}
shell_fit = {"inputs": {"fit_settings": gfs.defaults(), "mesh_shape": "shell"}}
check("[6] underwear: as-generated fit, Auto → shell → due", gfs.changed(generated, {}, "item_under"))
check("[6] outer: as-generated fit, Auto → as generated → not due", not gfs.changed(generated, {}, "item_outer"))
prof = {gfs.SETTINGS_KEY: {"item_outer": {"mesh_shape": "as_generated"}}}
check("[6] outer set to as_generated explicitly → not due", not gfs.changed(generated, prof, "item_outer"))
check("[6] underwear shell fit under Auto → not due", not gfs.changed(shell_fit, {}, "item_under"))
prof2 = {gfs.SETTINGS_KEY: {"item_under": {"mesh_shape": "as_generated"}}}
check("[6] underwear set to as_generated → its shell fit due", gfs.changed(shell_fit, prof2, "item_under"))
check("[6] … the outer piece's verdict unchanged", not gfs.changed(generated, prof2, "item_outer"))
try:
    gfs.validate({"mesh_shape": "lifted"})
    check("[6] bad mesh_shape refused", False)
except ValueError:
    check("[6] bad mesh_shape refused", True)

print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
sys.exit(1 if FAILS else 0)
