"""A230 smoke: the template source cut-out (app/core/garment_matte.py, garment_template.prepare_view) and the bake's
push-pull fill (app/blender/scripts/garment_template_drape.py ``push_pull``, loaded without bpy).

Usage: ./.venv/bin/python scripts/smoke_garment_matte.py [--birefnet]
  --birefnet  also runs [4] against the real BiRefNet-DIS session (CPU, a few seconds; needs the model file)

Synthetic pictures, numbers derived by hand:

[1] Anti-aliased red disc (255, 0, 0), radius 60 px at (100, 100) in 200 x 200, coverage per pixel = the share of
    its 8 x 8 sub-samples inside the disc, colour = cov * red + (1 - cov) * backdrop. Backdrop white (255, 255, 255).
    The matte stub returns the true coverage (an ideal BiRefNet). Distance red - white = sqrt(2 * 255^2) = 360.6:
    the key passes 0.5 at cov = (22 + 24) / 360.6 = 0.128 and the "sure" level (22 + 48 + 40 = 110) at cov = 0.305,
    so the piece = the pixels with cov >= 0.305 under the consensus (min(k, m) >= 0.5 needs m >= 0.5; the sure
    override takes cov >= 0.305) — its radius lies between 60 - 0.5 and 60 + 0.5 px.
    After the cut: every piece pixel is red — all channels within 1 of (255, 0, 0) (the rim un-mixed: c = bg + t
    (F - bg) with F = red gives back red exactly; the outer 2 px copy the red further in). So no piece pixel lies
    within 40 of white (backdrop_share rim = whole = 0), the old cut (flood fill within 24, hard alpha) leaves the
    rim pixels with 0.305 <= cov < 0.93 light (their G = B = (1 - cov) 255 > 17) — measured below as > 0.
    Every transparent pixel carries red too (the fill reaches the outside).
[2] The same disc on green (0, 255, 0). Distance red - green = 360.6 again: the same footprint. After the cut G <= 1 on
    every piece pixel (no green rim), R >= 254.
[3] A green-ish piece on the green screen: a disc of (40, 120, 60) (emerald-like) on (0, 255, 0): distance =
    sqrt(40^2 + 135^2 + 60^2) = 153.0 > 110: piece found; the despill must NOT grey it: the median of the piece
    within 2 of (40, 120, 60) (its G is the max channel — the backdrop's — so despill is skipped).
[4] A white piece on white: disc (246, 246, 246) on (255, 255, 255): distance = sqrt(3) * 9 = 15.6 < 22 — the key calls
    everything backdrop; the stub matte (true coverage) finds the disc: low-contrast share = 1 >= 0.25 -> the matte
    alone: the piece's area within 2 % of pi * 60^2 = 11310 px. Without a matte (key alone) nothing is left.
[5] An already cut picture (alpha kept): the [1] picture with the old flood-fill alpha and the backdrop under the
    alpha 0 pixels plus a black crop padding band; the ring estimate finds white (not black), the cut cleans the rim:
    rim backdrop share 0.
[6] push_pull: a 16 x 16 texture valid only in its left half (colour (1, 0, 0)) and one blue texel at (8, 3): valid
    texels keep their colour exactly; every empty texel gets a colour from the valid ones only — never the 0.5 grey
    and never black: R + B = 1 within 1e-9 on every texel (all fills are convex mixes of red and blue).
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_matte_")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import paths  # noqa: E402

paths.init(_tmp)
from app.core import garment_matte as gm  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

FAILED = []


def check(name, ok, info=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  {info}"))
    if not ok:
        FAILED.append(name)


def disc(colour, backdrop, r=60.0, n=200, ss=8):
    s = (np.arange(n * ss) + 0.5) / ss
    yy, xx = np.meshgrid(s, s, indexing="ij")
    inside = ((xx - 100) ** 2 + (yy - 100) ** 2 <= r * r).astype(np.float64)
    cov = inside.reshape(n, ss, n, ss).mean((1, 3))
    img = cov[..., None] * np.asarray(colour, float) + (1 - cov[..., None]) * np.asarray(backdrop, float)
    rgba = np.dstack([np.rint(img), np.full((n, n), 255.0)]).astype(np.uint8)
    return rgba, cov


def truth(cov):
    return lambda _rgb: cov


def old_cut(rgba, tol=24):
    """The pre-A230 prepare_view border flood fill (hard alpha)."""
    from scipy import ndimage
    rgb = rgba[..., :3].astype(np.int32)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    near = np.abs(rgb - np.median(border, 0)).max(2) <= tol
    lab, _n = ndimage.label(near)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    out = rgba.copy()
    out[..., 3] = np.where(np.isin(lab, edge[edge > 0]), 0, 255)
    return out


# [1] red on white
src, cov = disc((255, 0, 0), (255, 255, 255))
out, info = gm.cut(src, matte=truth(cov))
piece = out[..., 3] == 255
check("[1] consensus mode", info["mode"] == "consensus", info)
check("[1] footprint = cov >= ~0.305", bool(piece[cov >= 0.32].all()) and not piece[cov < 0.29].any(),
      (piece[cov >= 0.32].mean(), piece[cov < 0.29].sum()))
dev = np.abs(out[piece][:, :3].astype(int) - (255, 0, 0)).max()
check("[1] every piece pixel red within 1", dev <= 1, dev)
sh = gm.backdrop_share(out, (255, 255, 255))
check("[1] backdrop share rim = whole = 0", sh["rim"] == 0 and sh["whole"] == 0, sh)
sh_old = gm.backdrop_share(old_cut(src), (255, 255, 255))
check("[1] the old cut leaves a light rim (> 0)", sh_old["rim"] > 0, sh_old)
print(f"     red/white rim backdrop share: old {sh_old['rim']}  new {sh['rim']}")
check("[1] outside filled with red", np.abs(out[~piece][:, :3].astype(int) - (255, 0, 0)).max() <= 1)

# [2] red on green
src, cov = disc((255, 0, 0), (0, 255, 0))
out, info = gm.cut(src, matte=truth(cov))
piece = out[..., 3] == 255
check("[2] G <= 1 and R >= 254 on every piece pixel", out[piece][:, 1].max() <= 1 and out[piece][:, 0].min() >= 254,
      (out[piece][:, 1].max(), out[piece][:, 0].min()))
sh, sh_old = gm.backdrop_share(out, (0, 255, 0)), gm.backdrop_share(old_cut(src), (0, 255, 0))
check("[2] green rim share 0 (old > 0)", sh["rim"] == 0 and sh_old["rim"] > 0, (sh, sh_old))
print(f"     red/green rim backdrop share: old {sh_old['rim']}  new {sh['rim']}")

# [3] green-ish piece on green
src, cov = disc((40, 120, 60), (0, 255, 0))
out, info = gm.cut(src, matte=truth(cov))
piece = out[..., 3] == 255
med = np.median(out[piece][:, :3], 0)
check("[3] emerald piece keeps its colour (no despill)", np.abs(med - (40, 120, 60)).max() <= 2, med)
check("[3] emerald piece found", abs(piece.sum() - np.pi * 3600) < 0.03 * np.pi * 3600, piece.sum())

# [4] white on white
src, cov = disc((246, 246, 246), (255, 255, 255))
out, info = gm.cut(src, matte=truth(cov))
area = int((out[..., 3] == 255).sum())
check("[4] white on white: the matte decides", info["mode"] == "matte" and abs(area - np.pi * 3600) < 0.02 * np.pi * 3600,
      (info, area))
out_k, info_k = gm.cut(src, matte=None)
check("[4] the key alone finds nothing", int((out_k[..., 3] == 255).sum()) == 0, info_k)
if "--birefnet" in sys.argv:
    out_b, info_b = gm.cut(src)
    area_b = int((out_b[..., 3] == 255).sum())
    check("[4b] real BiRefNet: white disc within 10 %", abs(area_b - np.pi * 3600) < 0.1 * np.pi * 3600,
          (info_b, area_b))

# [5] an already cut picture with crop padding
src, cov = disc((255, 0, 0), (255, 255, 255))
old = old_cut(src)
old[:, :12] = 0                      # crop padding: exact black at alpha 0
out, info = gm.cut(old, matte=truth(cov))
check("[5] kept: ring backdrop is white", info["alpha"] == "kept" and min(info["bg"]) >= 250, info)
sh = gm.backdrop_share(out, (255, 255, 255))
check("[5] kept: rim cleaned", sh["rim"] == 0, sh)

# [6] push_pull (the Blender script's numpy helper; bpy stubbed)
sys.modules.setdefault("bpy", types.ModuleType("bpy"))
mu = types.ModuleType("mathutils")
mu.Vector = mu.Matrix = mu.Quaternion = mu.Euler = object
sys.modules.setdefault("mathutils", mu)
bm = types.ModuleType("bmesh")
sys.modules.setdefault("bmesh", bm)
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("gtd", ROOT / "app/blender/scripts/garment_template_drape.py")
gtd = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(gtd)
    push_pull = gtd.push_pull
except Exception as e:  # noqa: BLE001 — the helper is pure numpy: take its source alone
    import ast
    src_txt = (ROOT / "app/blender/scripts/garment_template_drape.py").read_text()
    nodes = [n for n in ast.parse(src_txt).body if isinstance(n, ast.FunctionDef) and n.name in ("_up2", "push_pull")]
    ns = {"np": np}
    exec(compile(ast.Module(nodes, []), "push_pull", "exec"), ns)
    push_pull = ns["push_pull"]
tex = np.zeros((16, 16, 3))
valid = np.zeros((16, 16), bool)
valid[:, :8] = True
tex[:, :8] = (1, 0, 0)
tex[3, 8] = (0, 0, 1)
valid[3, 8] = True
filled = push_pull(tex, valid)
check("[6] valid texels unchanged", np.array_equal(filled[valid], tex[valid]))
check("[6] fills are mixes of red and blue only", np.abs(filled[..., 0] + filled[..., 2] - 1).max() < 1e-9
      and np.abs(filled[..., 1]).max() < 1e-12)

print(f"\n{len(FAILED)} FAILED: {FAILED}" if FAILED else "\nALL OK")
sys.exit(1 if FAILED else 0)
