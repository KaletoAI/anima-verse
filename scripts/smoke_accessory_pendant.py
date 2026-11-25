"""Smoke: A225 — the necklace pendant (``app/core/accessory_pendant.py``, the pendant parts of
``app/core/accessory_build.py`` and ``app/core/accessory_spec.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_pendant.py   (no server, no network — the mesh backend and the
cut-out are mocked, a temp storage dir)

Expected values, derived by hand:

[1] Cords (``accessory_spec``): ``normalize({kind: necklace, metal: leather})`` takes the cord thickness 2.5 mm; an
    explicit 1.5 mm stays 1.5; gold keeps 1.5. ``metal_material`` leather → ("#5b3a24", 0.75, 0.0), gold → (…, 1.0).
    ``pendant_on`` (only the earrings' own drop since part items, D1): earrings drop → True; a necklace with a
    size-only pendant → False (no linked item); on a ring → False.
[2] ``mesh_gates`` of a closed slab 20 × 40 × 5 with 8 × 16 × 2 cells: triangles = 2·2·(16·2 + 8·2 + 8·16) =
    2·2·176 = 704; one piece → component share 1.0; aspect 40 / 5 = 8 → passes. Two such slabs side by side 100
    apart → each half of the area, neither inside the other's box → share 0.5 → refused ("pieces"). A 1 × 1 × 40
    bar → aspect 40 > 20 → refused ("needle"). One triangle → refused ("only 1 triangles").
[3] ``normalise(slab, 45)``: scale 45 / 40 → extents (22.5, 45, 5.625) mm; top at y = 0, back at z = 0, x centred.
[4] ``place`` on a flat body: the closed box x ±0.5, y ±1, z −0.5..0 (front face z = 0, outward +z), pendant
    10 × 20 × 2 mm (normalised slab at size 20), hung at (0, 0, 0.004), gap 3 mm. Per tilt θ (positive: bottom
    away) the nearest point is the back-bottom edge (z = 0.004 + 0.020 sin θ) for θ < 0 and the back-top edge
    (z = 0.004) for θ ≥ 0, so no tilt ≥ −2.87° needs a push; θ = −4° needs 3 − (4 − 20 sin 4° = 2.605) = 0.395 mm,
    inside the 0.5 mm slack, so it competes too. The back face's median distance once pushed: θ = −2° runs 4.0 →
    3.30 mm (mid 3.65), θ = −4° 4.395 → 3.0 (mid 3.70), θ ≥ 0 at least 4.0 → θ = −2° lies flattest (sin −2° =
    −0.0349 → 0.004 − 0.0007 = 3.30 mm min). Expected: tilt −2, push 0, gap 3.30 mm.
    Hung at z = 0.001 instead: every tilt needs ≥ 2 mm push (the back-top edge stays at 1 mm); the least push,
    2.0 mm for θ ≥ 0, then the flattest θ = 0 → push 2.0 mm (+ the 0.1 mm step only if the first push falls short;
    here it does not), gap 3.00 mm.
[5] ``joint_transforms`` + ``skin``: joints root (head (0,1,0), rotated 90° about x) → child (no rotation). A point
    (0, 2, 0) on the root: relative (0, 1, 0) → R_x(90°) → (0, 0, 1) → (0, 1, 1). A point (0, 3, 0) on the child
    follows its parent: (0, 1, 2).
[6] ``pendant_state``: no item image → no_image; an image, nothing stored → missing (REASON_MISSING); a record
    accepted False failure "gate" error "x" → refused "Part mesh refused — x; …" (role-neutral: no "chain", no
    "pendant" in any state's reason); failure "backend" → failed;
    failure "load" → missing with the load reason; accepted with raw.glb → ready.
    ``drop_other_pendants(item, A)`` with folders A, B (12 hex) and "notes" deletes exactly B.
[7] ``run`` with the backend mocked: ONE ``generate_mesh`` call with occasion "jewellery_mesh"; the delivered slab
    passes → ready, record hub_jobs 1, backend + routing + fallback_from kept; a second ``run`` makes no call.
    A new item image → a new psig → missing again; a ``BackendBusyError`` → missing (load, hub_jobs 0); a
    ``BackendFailedError`` → failed; a two-piece delivery → refused (not retried by a further ``pendant_state``).
[7b] the outline gate: the mocked cut-out shows 24 × 44 px (``fake_rembg``) → width : height 24/44 = 0.545 (the square
    crop and the resize keep it within a pixel). A 40 × 40 × 40 cube delivered for a new image: every turn's front is
    1.0, |ln(1.0/0.545)| = 0.606 > ln 1.35 = 0.300 → refused, the reason names the outline. The slab of [7] (20 × 40,
    front 0.5: |ln(0.5/0.545)| = 0.087) passed there.
[8] ``accessory_build.asig`` of the earrings' drop: a ready drop psig changes the asig; with a psig the size changes it
    (18 → 30); without a psig the size does not (a drop that is not built is not part of the geometry).
[G3a] ``orient_thin_to_depth`` (plan-anhaenger Task 3), box extents (x, y, z) → after: (0.030, 0.040, 0.005) stays;
    (0.005, 0.040, 0.030) → (0.030, 0.040, 0.005) (x thinnest, turned −90° about +Y); (0.030, 0.005, 0.040) →
    (0.030, 0.040, 0.005) (y thinnest, +90° about +X).
[G3a-tie] the tie limit 1.10 · min: (0.0050, 0.040, 0.0054) stays (0.0054 ≤ 1.1 · 0.0050 = 0.0055);
    (0.0050, 0.040, 0.0056) → (0.0056, 0.040, 0.0050) (0.0056 > 0.0055) — a pure axis swap: every box corner keeps its
    magnitudes, x and z trade places with the old z's sign flipped; (0.0050, 0.0050, 0.040) → x wins the tie →
    (0.040, 0.0050, 0.0050).
[G3a-flip] box (0.030, 0.040, 0.005) centred, a marker vertex at x +0.015, z +0.0025: with ``flip`` it lies at
    x −0.015, z −0.0025.
[G3b] the measured extent of Lirien's old whole-belt buckle mesh (0.459, 0.115, 0.999) as a box: y is thinnest → after
    turning (0.459, 0.999, 0.115); ``normalise(…, 65)`` → 65 · 0.459/0.999 = 29.86 mm wide, 65.0 mm high,
    65 · 0.115/0.999 = 7.48 mm deep (before part items the 65 mm stood in z, the depth).
[G3c] ``orient`` by the image (review finding: a long prong made a front axis the thinnest). Frame + prong: a frame box
    50 (x) × 40 (y) × 6 (z) mm centred on the origin and a prong box 4 × 4 × 60 mm behind it (z −3 … −63) → extents
    (50, 40, 66). ``orient_thin_to_depth`` turns y (40, the thinnest) into the depth → (50, 66, 40): twisted. With the
    image's 50 : 40 = 1.25 the three turns' fronts are z-depth 50/40 = 1.25 (score 0), x-depth 66/40 = 1.65
    (|ln 1.32| = 0.278), y-depth 50/66 = 0.758 (|ln 0.606| = 0.500) → z stays → (50, 40, 66). ``normalise(…, 50,
    front_ratio=1.25)`` scales by the longer FRONT side (50 mm → factor 1) → (50.0, 40.0, 66.0) mm, not by the 66 mm
    depth. ``front_reason`` at 1.25 → ''; at 3.0 the best turn is x-depth (|ln(1.65/3)| = 0.598 > 0.300) → the
    reason names 1.65 on the mesh and 3.00 in the image. A 20 mm cube with ratio 1.0 → all three turns score 0 with
    equal depth → z stays (an exact copy of the input).
[G3d] ``image_front_ratio`` of a 100 × 60 transparent PNG with an opaque block x 10..60, y 5..45 → 50 / 40 = 1.25; a
    fully transparent one → None. ``load_mesh`` carries it from the stored ``cutout.png``.
"""
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path


def _blocked(*_a, **_k):
    raise OSError("network blocked in this smoke")


socket.socket.connect = _blocked
socket.create_connection = _blocked

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_accessory_pendant_")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
import numpy as np  # noqa: E402
from app.core import accessory_build as ab, accessory_pendant as ap, accessory_spec as s, glb_mesh  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def slab(w=20.0, h=40.0, d=5.0, nx=8, ny=16, nz=2):
    """A closed box mesh with outward winding, centred on the origin."""
    V, F, idx = [], [], {}
    sizes = np.array([w, h, d])
    cells = [nx, ny, nz]

    def vid(p):
        k = tuple(np.round(p, 6))
        if k not in idx:
            idx[k] = len(V)
            V.append(p)
        return idx[k]
    for axis in range(3):
        a, b = [i for i in range(3) if i != axis]
        for side in (0, 1):
            for i in range(cells[a]):
                for j in range(cells[b]):
                    def P(ii, jj):
                        p = np.zeros(3)
                        p[axis] = side * sizes[axis]
                        p[a] = ii / cells[a] * sizes[a]
                        p[b] = jj / cells[b] * sizes[b]
                        return p - sizes / 2
                    q = [vid(P(i, j)), vid(P(i + 1, j)), vid(P(i + 1, j + 1)), vid(P(i, j + 1))]
                    n = np.cross(P(i + 1, j) - P(i, j), P(i, j + 1) - P(i, j))
                    flip = (n[axis] > 0) != (side == 1)
                    for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
                        F.append((t[0], t[2], t[1]) if flip else t)
    return np.array(V, np.float64), np.array(F, np.int64)


# [1] cords
leather = s.normalize({"kind": "necklace", "metal": "leather"})
check("[1] cord default thickness", leather["chain"]["thickness_mm"], 2.5)
check("[1] cord explicit thickness", s.normalize({"kind": "necklace", "metal": "leather",
                                                  "chain": {"thickness_mm": 1.5}})["chain"]["thickness_mm"], 1.5)
check("[1] gold thickness", s.normalize({"kind": "necklace"})["chain"]["thickness_mm"], 1.5)
check("[1] leather material", s.metal_material(leather), ("#5b3a24", 0.75, 0.0))
check("[1] gold metalness", s.metal_material(s.normalize({"kind": "necklace"}))[2], 1.0)
check("[1] pendant on", s.pendant_on(s.normalize({"kind": "earrings", "earring": {"style": "drop"}})), True)
check("[1] pendant off", s.pendant_on(s.normalize({"kind": "necklace", "pendant": {"size_mm": 18}})), False)
check("[1] pendant on a ring", s.pendant_on(s.normalize({"kind": "ring", "pendant": {"size_mm": 18}})), False)

# [2] gates
V, F = slab()
ok, reasons, nums = ap.mesh_gates(V, F)
check("[2] slab", (ok, nums["triangles"], nums["component_share"], nums["aspect"]), (True, 704, 1.0, 8.0))
V2 = np.concatenate([V, V + [100, 0, 0]])
F2 = np.concatenate([F, F + len(V)])
ok, reasons, nums = ap.mesh_gates(V2, F2)
check("[2] two pieces", (ok, nums["component_share"], any("pieces" in r for r in reasons)), (False, 0.5, True))
Vb, Fb = slab(1, 1, 40, 1, 1, 4)
ok, reasons, _ = ap.mesh_gates(Vb, Fb)
check("[2] needle", (ok, any("needle" in r for r in reasons)), (False, True))
ok, reasons, _ = ap.mesh_gates(np.eye(3), np.array([[0, 1, 2]]))
check("[2] one triangle", (ok, "only 1 triangles" in reasons), (False, True))

# [3] normalise
Vn = ap.normalise(V, 45)
ext = (Vn.max(0) - Vn.min(0)) * 1000
check("[3] extents mm", [round(float(x), 3) for x in ext], [22.5, 45.0, 5.625])
check("[3] top, back, centre", (round(float(Vn[:, 1].max()), 9), round(float(Vn[:, 2].min()), 9),
                                round(float(Vn[:, 0].max() + Vn[:, 0].min()), 9)), (0.0, 0.0, 0.0))

# [4] place on a flat body
Bv, Bf = slab(1.0, 2.0, 0.5, 4, 4, 2)
Bv = Bv + [0, 0, -0.25]
Pn = ap.normalise(slab(10, 20, 2, 4, 8, 1)[0], 20)
Pf = slab(10, 20, 2, 4, 8, 1)[1]
placed, how = ap.place(Pn, np.array([0, 0, 0.004]), np.array([0, 0, 1.0]), Bv, Bf)
check("[4] tilt / push / gap", (how["tilt_deg"], how["push_mm"], how["gap_mm"]), (-2, 0.0, 3.3))
placed, how = ap.place(Pn, np.array([0, 0, 0.001]), np.array([0, 0, 1.0]), Bv, Bf)
check("[4] pushed", (how["tilt_deg"], how["push_mm"], how["gap_mm"]), (0, 2.0, 3.0))

# [5] posing
M = ap.joint_transforms(["root", "child"], {"child": "root"}, {"root": np.array([0, 1.0, 0])},
                        {"root": ("x", 90.0)})
X = ap.skin(np.array([[0, 2.0, 0], [0, 3.0, 0]]), np.array([[0, 0, 0, 0], [1, 0, 0, 0]]),
            np.array([[1.0, 0, 0, 0], [1.0, 0, 0, 0]]), M)
check("[5] root point", [round(float(x), 9) for x in X[0]], [0.0, 1.0, 1.0])
check("[5] child point", [round(float(x), 9) for x in X[1]], [0.0, 1.0, 2.0])

# [6] state
from app.models import inventory  # noqa: E402
IMAGE = {"path": None}
inventory.get_item_image_path = lambda _iid: str(IMAGE["path"]) if IMAGE["path"] else None
check("[6] no image", ap.pendant_state("item_p")["state"], "no_image")
img = Path(TMP) / "pendant.png"
img.write_bytes(b"image-1")
IMAGE["path"] = img
st = ap.pendant_state("item_p")
check("[6] missing", (st["state"], st["reason"]), ("missing", ap.REASON_MISSING))
d = ap.pendant_dir("item_p", st["psig"])
d.mkdir(parents=True)


def rec(**kw):
    (d / "record.json").write_text(json.dumps(kw))
    return ap.pendant_state("item_p")


st = rec(accepted=False, failure="gate", error="x")
check("[6] refused", (st["state"], st["reason"].startswith("Part mesh refused — x;")), ("refused", True))
NEUTRAL = [st["reason"]]
st = rec(accepted=False, failure="backend", error="y")
check("[6] failed", st["state"], "failed")
NEUTRAL.append(st["reason"])
st = rec(accepted=False, failure="load", error="busy")
check("[6] load", (st["state"], "try again later" in st["reason"]), ("missing", True))
NEUTRAL += [st["reason"], ap.REASON_MISSING, ap.REASON_RUNNING, ap.REASON_NO_IMAGE, ap.REASON_LEFT_OFF]
check("[6] no reason names a chain or a pendant",
      [r for r in NEUTRAL if "chain" in r.lower() or "pendant" in r.lower()], [])
(d / "raw.glb").write_bytes(b"x")
check("[6] ready", rec(accepted=True)["state"], "ready")
A, B = "a" * 12, "b" * 12
for name in (A, B, "notes"):
    (ap.item_dir("item_q") / name).mkdir(parents=True)
check("[6] drop others", ap.drop_other_pendants("item_q", A), [B])
check("[6] left", sorted(p.name for p in ap.item_dir("item_q").iterdir()), [A, "notes"])

# [7] run with the backend mocked
from app.models import character  # noqa: E402
from PIL import Image  # noqa: E402


def fake_rembg(_data, _model):
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    im.paste((200, 190, 160, 255), (20, 10, 44, 54))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


character.run_rembg = fake_rembg
CALLS = []
DELIVERY = {"mesh": (V, F), "raise": None}


class FakeService:
    def generate_mesh(self, source_image_path, output_path, **kw):
        CALLS.append(kw.get("occasion"))
        if DELIVERY["raise"] is not None:
            raise DELIVERY["raise"]
        P, Fm = DELIVERY["mesh"]
        Path(output_path).write_bytes(glb_mesh.static_glb(P, Fm, np.zeros((len(P), 2))))
        return {"ok": True, "path": output_path, "backend": "mesh-a", "routing": {"occasion": "jewellery_mesh"},
                "fallback_from": "mesh-b"}


from app.imagegen import service as service_mod  # noqa: E402
service_mod.get_image_service = lambda: FakeService()
from app.core import figure  # noqa: E402
figure.invalidate = lambda *a, **k: None
img.write_bytes(b"image-22")
st = ap.run("item_p")
r = st["record"] or {}
check("[7] ready after one call", (st["state"], CALLS), ("ready", ["jewellery_mesh"]))
check("[7] record", (r.get("hub_jobs"), r.get("backend"), r.get("fallback_from"), r.get("routing")),
      (1, "mesh-a", "mesh-b", {"occasion": "jewellery_mesh"}))
ap.run("item_p")
check("[7] second run: no call", len(CALLS), 1)
from app.imagegen.base import BackendBusyError, BackendFailedError  # noqa: E402
img.write_bytes(b"image-333")
check("[7] new image -> missing", ap.pendant_state("item_p")["state"], "missing")
DELIVERY["raise"] = BackendBusyError("busy")
st = ap.run("item_p")
check("[7] busy", (st["state"], st["record"].get("hub_jobs")), ("missing", 0))
DELIVERY["raise"] = BackendFailedError("mesh-a", RuntimeError("boom"))
check("[7] failed", ap.run("item_p")["state"], "failed")
img.write_bytes(b"image-4444")
DELIVERY["raise"] = None
DELIVERY["mesh"] = (V2, F2)
check("[7] two pieces refused", ap.run("item_p")["state"], "refused")
check("[7] refused stays refused", ap.pendant_state("item_p")["state"], "refused")
# [7b] the outline gate
img.write_bytes(b"image-55555")
DELIVERY["mesh"] = slab(40, 40, 40, 4, 4, 4)
st = ap.run("item_p")
check("[7b] a cube for a 24 x 44 image refused", (st["state"], "outline does not match the image" in st["reason"]),
      ("refused", True))
print("       " + st["reason"])

# [8] asig
pend18 = s.normalize({"kind": "earrings", "earring": {"style": "drop"}, "pendant": {"size_mm": 18}})
pend30 = s.normalize({"kind": "earrings", "earring": {"style": "drop"}, "pendant": {"size_mm": 30}})
check("[8] psig changes asig", ab.asig(pend18) != ab.asig(pend18, drop_psig="0123456789ab"), True)
check("[8] size with psig", ab.asig(pend18, drop_psig="0123456789ab") != ab.asig(pend30, drop_psig="0123456789ab"), True)
check("[8] size without psig", ab.asig(pend18), ab.asig(pend30))

# [G3] thinnest side as depth
def box(ex, ey, ez):
    return np.array([[sx * ex / 2, sy * ey / 2, sz * ez / 2] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])


def ext(V):
    return tuple(round(float(x), 5) for x in (V.max(0) - V.min(0)))


for src, want in (((0.030, 0.040, 0.005), (0.030, 0.040, 0.005)), ((0.005, 0.040, 0.030), (0.030, 0.040, 0.005)),
                  ((0.030, 0.005, 0.040), (0.030, 0.040, 0.005))):
    check(f"[G3a] {src}", ext(ap.orient_thin_to_depth(box(*src))), want)
check("[G3a-tie] z 0.0054 stays", ext(ap.orient_thin_to_depth(box(0.0050, 0.040, 0.0054))), (0.005, 0.04, 0.0054))
B = box(0.0050, 0.040, 0.0056)
Bt = ap.orient_thin_to_depth(B)
check("[G3a-tie] z 0.0056 turns", ext(Bt), (0.0056, 0.04, 0.005))
check("[G3a-tie] a pure axis swap", bool(np.allclose(Bt, np.c_[-B[:, 2], B[:, 1], B[:, 0]])), True)
check("[G3a-tie] x before y", ext(ap.orient_thin_to_depth(box(0.0050, 0.0050, 0.040))), (0.04, 0.005, 0.005))
M = np.vstack([box(0.030, 0.040, 0.005), [[0.015, 0.0, 0.0025]]])
Mf = ap.orient_thin_to_depth(M, flip=True)
check("[G3a-flip] marker", [round(float(x), 6) for x in Mf[-1]], [-0.015, 0.0, -0.0025])
L = ap.orient_thin_to_depth(box(0.459, 0.115, 0.999))
check("[G3b] turned", ext(L), (0.459, 0.999, 0.115))
Ln = ap.normalise(box(0.459, 0.115, 0.999), 65)
check("[G3b] normalised mm", tuple(round(float(x) * 1000, 2) for x in (Ln.max(0) - Ln.min(0))), (29.86, 65.0, 7.48))

# [G3c] orient by the image's outline
FP = np.vstack([box(0.050, 0.040, 0.006), box(0.004, 0.004, 0.060) + [0.0, 0.0, -0.033]])
check("[G3c] extents", ext(FP), (0.05, 0.04, 0.066))
check("[G3c] thinnest rule twists it", ext(ap.orient_thin_to_depth(FP)), (0.05, 0.066, 0.04))
check("[G3c] by the image: z stays", ext(ap.orient(FP, 1.25)), (0.05, 0.04, 0.066))
FPn = ap.normalise(FP, 50, front_ratio=1.25)
check("[G3c] normalised by the front", tuple(round(float(x) * 1000, 2) for x in (FPn.max(0) - FPn.min(0))),
      (50.0, 40.0, 66.0))
check("[G3c] front_reason at 1.25", ap.front_reason(FP, 1.25), "")
why = ap.front_reason(FP, 3.0)
check("[G3c] front_reason at 3.0", ("1.65 on the mesh" in why, "3.00 in the image" in why), (True, True))
C20 = box(0.020, 0.020, 0.020)
check("[G3c] a cube stays as it is", bool(np.array_equal(ap.orient(C20, 1.0), C20)), True)
# [G3d] the cut-out's ratio
im = Image.new("RGBA", (100, 60), (0, 0, 0, 0))
im.paste((10, 10, 10, 255), (10, 5, 60, 45))
buf = io.BytesIO()
im.save(buf, format="PNG")
check("[G3d] 50 / 40", ap.image_front_ratio(buf.getvalue()), 1.25)
buf = io.BytesIO()
Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buf, format="PNG")
check("[G3d] empty", ap.image_front_ratio(buf.getvalue()), None)
psig_b = ap.current_psig("item_p")
dd = ap.pendant_dir("item_p", psig_b)
check("[G3d] load_mesh carries the cut-out's ratio",
      round(ap.load_mesh("item_p", psig_b)["front_ratio"], 3) if (dd / "raw.glb").is_file() else "no mesh",
      round(ap.image_front_ratio((dd / "cutout.png").read_bytes()), 3) if (dd / "raw.glb").is_file() else "no mesh")

if FAIL:
    print(f"FAILED: {FAIL}")
    sys.exit(1)
print("All checks passed.")
