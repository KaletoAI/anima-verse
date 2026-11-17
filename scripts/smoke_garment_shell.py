"""Smoke: Ruling A48d — the mesh mode "Shell from the body" (``app/core/garment_shell.py``; its own mode since A168).

Usage: ./.venv/bin/python scripts/smoke_garment_shell.py   (no server, no world; pure functions + monkeypatched items)

Expected values, derived by hand:

[1] The old Auto rule, now only the migration's (``close_fitting``): slots ⊆ {underwear_top, underwear_bottom,
    legs}, no ``covers``, not closable → True. underwear_top / underwear_bottom / legs → True; [underwear_top, top],
    outer, bottom, underwear_top covering underwear_bottom, underwear_top closable, no slots → False.
    ``shape_of``: mode shell → shell; own_mesh, painted, in_body, template, no mode → as_generated.
[2] Region → shell faces: a region of n body faces, two midpoint subdivisions → 16·n faces (each split makes 4);
    clipped with a scalar >= 0 everywhere it keeps all 16·n. Here n = 2 (a unit square of two triangles) → 32.
[3] Clip by marching triangles: the triangle (0,0),(1,0),(0,1) with s = (1, -1, -1) keeps the corner triangle up
    to the zero crossings at t = 1/2 → area 0.5·0.5·0.5 = 0.125; with s = (-1, 1, 1) keeps the rest 0.5 − 0.125 =
    0.375 as two triangles.
[4] Outer wall only: a closed cube of side 1 (12 triangles) with a second closed cube of side 0.5 inside it (12
    triangles): from all 26 directions only the outer cube is front-most → 12 outer faces, the inner 12 never.
[5] Inside share 0: points 4 mm outside a unit sphere mesh → 0.0; points 0.1 inside → 1.0 (> 2 mm under).
[6] Due-ness (``garment_fit_settings.changed``): the underwear piece in mode shell, the outer piece in own_mesh.
    A fit made as generated (no ``inputs.mesh_shape``) with default settings: underwear → due (its mode makes a
    shell); outer → not due; a shell fit of the underwear piece → not due; a shell fit of the outer piece → due.
    ``mesh_shape`` is no setting any more: ``validate({"mesh_shape": "shell"})`` is refused as unknown.
[7] The chain of a shell piece (``garments.shell_order`` / ``run_estimate``): clothing order worn → ghost →
    cutout → mesh → fit; a shell piece drops cutout + mesh → worn → ghost → fit; an outer piece keeps all five.
    Costs (``HUB_JOBS``): worn 2, ghost 2, cutout 2, mesh 1, fit 0. Nothing done: shell piece 2 + 2 = 4 hub jobs,
    the outer piece 2 + 2 + 2 + 1 = 7. Shell piece with worn + ghost done and no generated mesh: first step fit →
    0 hub jobs; the outer piece in the same state: cutout 2 + mesh 1 = 3.
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


def item(slots, covers=(), closable=False, mode=None):
    piece = {"slots": list(slots), "covers": list(covers), "closable": closable}
    if mode:
        piece["mesh_mode"] = mode
    return {"category": "outfit_piece", "outfit_piece": piece}


# [1]
table = [
    (item(["underwear_top"]), True), (item(["underwear_bottom"]), True), (item(["legs"]), True),
    (item(["underwear_top", "top"]), False), (item(["outer"]), False), (item(["bottom"]), False),
    (item(["underwear_top"], covers=["underwear_bottom"]), False), (item(["underwear_top"], closable=True), False),
    (item([]), False),
]
for it, want in table:
    check(f"[1] close_fitting {it['outfit_piece']['slots']} {it['outfit_piece']['covers']} "
          f"closable={it['outfit_piece']['closable']} -> {want}", gsh.close_fitting(it) is want)
for mode, want in (("shell", "shell"), ("own_mesh", "as_generated"), ("painted", "as_generated"),
                   ("in_body", "as_generated"), ("template", "as_generated"), (None, "as_generated")):
    check(f"[1] shape_of mode {mode} -> {want}", gsh.shape_of(item(["underwear_top"], mode=mode)) == want)

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
ITEMS = {"item_under": item(["underwear_top"], mode="shell"), "item_outer": item(["outer"], mode="own_mesh")}
inv.get_item = lambda iid: ITEMS.get(iid)
generated = {"inputs": {"fit_settings": gfs.defaults()}}
shell_fit = {"inputs": {"fit_settings": gfs.defaults(), "mesh_shape": "shell"}}
check("[6] underwear (shell mode): as-generated fit → due", gfs.changed(generated, {}, "item_under"))
check("[6] outer (own mesh): as-generated fit → not due", not gfs.changed(generated, {}, "item_outer"))
check("[6] underwear shell fit → not due", not gfs.changed(shell_fit, {}, "item_under"))
check("[6] outer shell fit → due", gfs.changed(shell_fit, {}, "item_outer"))
try:
    gfs.validate({"mesh_shape": "shell"})
    check("[6] mesh_shape is no setting", False)
except ValueError:
    check("[6] mesh_shape is no setting", True)

# [7]
from app.core import garments, base_body, garment_images, garment_source  # noqa: E402
from app.core import garment_store as gstore  # noqa: E402
FULL = ("worn", "ghost", "cutout", "mesh", "fit")
check("[7] shell order", garments.shell_order(FULL, "clothing", "item_under", {}) == ("worn", "ghost", "fit"))
check("[7] outer order unchanged", garments.shell_order(FULL, "clothing", "item_outer", {}) == FULL)
DONE = set()
garments._item = lambda c, i: (ITEMS[i], "clothing")
gstore.kind_method = lambda *a, **k: "edit_chain"
base_body.current_base = lambda *a, **k: ("base00000000", "sha")
gstore.item_state = lambda *a, **k: None
gstore.garment_fsig = lambda *a, **k: "0123456789ab"
garments._done = lambda c, i, k, f, s, *a: s in DONE
garments._view_done = lambda c, i, f, s, v: s in DONE
garments._run_profile = lambda p, i, st: p
for name in ("rejudge_expected", "source_due", "cutout_reusable"):
    setattr(garment_images, name, lambda *a, **k: False)
garment_images.piece_source = lambda *a, **k: None
garment_source.has_own_images = lambda *a, **k: True
for done, under, outer in ((set(), 4, 7), ({"worn", "ghost"}, 0, 3)):
    DONE.clear(); DONE.update(done)
    eu = garments.run_estimate("Demo", "item_under", profile={})
    eo = garments.run_estimate("Demo", "item_outer", profile={})
    check(f"[7] done {sorted(done)}: shell piece {under} hub jobs ({eu.get('steps')})", eu.get("hub_jobs") == under,
          str(eu))
    check(f"[7] done {sorted(done)}: outer piece {outer} hub jobs", eo.get("hub_jobs") == outer, str(eo))

print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
sys.exit(1 if FAILS else 0)
