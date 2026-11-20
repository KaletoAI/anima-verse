"""Smoke: the template texture bake on the CPU (bug round 2026-11-20, "template textures are random").

Usage:
    ./.venv/bin/python scripts/smoke_bake_register.py

No server, no world DB (throwaway ``paths.init`` dirs), no Blender: the bake's math is ``app/blender/scripts/
bake_register.py`` (numpy only), the push-pull upsampler ``_up2`` is read out of ``garment_template_drape.py`` by its
AST, the rest is core code. Every expectation is derived by hand below.

[1] ``register``: the piece = the unit square x, z in [0, 1] (two triangles). The picture (100 x 100, row 0 = bottom)
    = a 40 x 60 px block, cols 30..69, rows 20..79, plus a 2 px "strap" the template does not have: cols 49..50,
    rows 80..97. Opaque: 2400 + 36 = 2436 px.
    Box fit (the old bake): the alpha box is cols 30..69 (40 px), rows 20..97 (78 px) -> u = 40 x + 30,
    v = 78 z + 20: the square covers 40 x 78 = 3120 px, all the opaque pixels lie inside it -> IoU 2436 / 3120 =
    0.781. Registered: the square on the block alone (u = 40 x + 30, v = 60 z + 20) -> IoU 2400 / 2436 = 0.985.
    Expected (grid cells of 124.8 / 128 = 0.975 px): box IoU 0.781 +- 0.02, registered IoU >= 0.95, sz = 60 +- 2,
    oz = 20 +- 1.5, sx = 40 +- 1.5, ox = 30 +- 1.5.
[2] ``sample_bilinear`` on a 1 x 2 picture: pixel 0 black, pixel 1 white (centres u 0.5 / 1.5). u = 1.0 -> 0.5,
    u = 0.75 -> 0.25 (3/4 black + 1/4 white), both valid. With pixel 1 unusable (an opening): u = 0.75 -> 0.0 (the
    usable pixel alone, renormalised), valid; u = 1.25 lies IN pixel 1 -> invalid.
[3] ``islands``: two unit squares at x 0..1 and 2..3 (a gap of 1 = 1/3 of the extent >= ``PART_GAP`` 0.05) ->
    two parts, two triangles each, left = x 0..1. One strip x 0..3 (no gap) -> None.
[4] ``alpha_parts``: a 40 x 100 picture, two blocks cols 5..44 and 55..94 (rows 5..34), joined by a 1-row bridge
    cols 45..54 at row 20 (two gloves touching at the thumbs). Column counts: 30 in a block, 1 on the bridge; the
    middle 40 % of the box (cols 5 + 36 = 41 .. 5 + 54 = 59) holds the bridge, its least column holds 1 <= 0.15 x 30
    -> cut at the first bridge column 45: left = 1200 px, right = 1200 + 9 = 1209 px. One solid block -> None.
[5] ``anisotropy``: the unit square in the XZ plane, mapped u = 10 x, v = 10 z -> 1.0; u = 40 x, v = 10 z -> 4.0
    (singular values 40 and 10).
[6] ``push_pull``'s ``_up2``: the 1 x 2 row [0, 1] doubled along both axes -> rows of [0, 0.25, 0.75, 1]
    (each fine cell 3/4 its own coarse cell + 1/4 the next, edges clamped).
[7] ``garment_template.opening_mask``: a 100 x 100 RGBA, the piece = cols 20..79, rows 10..89 (60 x 80 = 4800 px,
    row 0 = top as a file) of (150, 100, 60) (luminance 0.299 * 150 + 0.587 * 100 + 0.114 * 60 = 110.39).
    a) a slit: (10, 10, 10) at cols 60..66, rows 50..89 (7 x 40 = 280 px = 0.058 of the piece) — it reaches the hem
       (row 90 below it is outside); its rim = 2 x 40 + 2 x 7 - 4 = 90 px, the 7 of the bottom row border the outside
       (7 / 90 = 0.08 <= 0.35) -> the mask = exactly those 280 px, 1 region.
    b) black fabric: the piece (20, 20, 20), the same slit (5, 5, 5): 5 < 0.35 x 20 but the drop 15 < 40 -> no mask.
    c) a dark band along the top edge, rows 10..14 (60 x 5 = 300 px): its rim = 2 x 60 + 2 x 5 - 4 = 126 px, of which
       the top row (60) and the end columns' other 4 rows each (8) border the outside: 68 / 126 = 0.54 > 0.35 -> kept
       as fabric. A dark spot inside (rows 40..45, cols 30..35) reaches no edge -> kept.
[8] ``crop_back(native=True)``: a 2048 x 2048 answer to a 512 x 512 canvas, source 450 x 512 at offset (31, 0):
    ``crop_back_box`` -> scaled (512, 512), box (31, 0, 481, 512); native scale 2048 / 512 = 4 -> the output is
    (481 - 31) x 4 = 1800 x 2048 px; the default stays 450 x 512.
[9] ``template_lines``: gloves fingerless -> [GLOVES_LINE, the fingerless line]; a bra with straps "none" -> the
    strapless line only; a skirt with slit "left" -> the wearer's-left line (a skirt has no "straps" field, so its
    default "thin" says nothing).
[10] ``texture_warning`` (marks coverage 0.6, IoU 0.5): {coverage 0.43} -> low coverage (an old record without iou);
    {0.9, iou 0.2} -> low iou; {0.9, 0.9} -> None.
"""
import ast
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import bake_register as br  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="smoke_bake_register_"))
from app.core import paths  # noqa: E402
paths.init(str(TMP / "world"))
FAILS = []


def check(label, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILS.append(label)


SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
SQ_TRIS = np.array([[0, 1, 2], [0, 2, 3]])

# [1]
alpha = np.zeros((100, 100), bool)
alpha[20:80, 30:70] = True
alpha[80:98, 49:51] = True
m, iou, box = br.register(SQUARE, SQ_TRIS, alpha)
check("[1] box fit IoU 0.781", abs(box - 2436 / 3120) < 0.02, box)
check("[1] registered IoU >= 0.95", iou >= 0.95, iou)
sx, ox, sz, oz = m
check("[1] the map sits on the block (40, 30, 60, 20)",
      abs(sx - 40) < 1.5 and abs(ox - 30) < 1.5 and abs(sz - 60) < 2 and abs(oz - 20) < 1.5, m)

# [2]
rgb = np.zeros((1, 2, 3))
rgb[0, 1] = 1.0
both = np.ones((1, 2), bool)
col, ok = br.sample_bilinear(rgb, both, np.array([1.0, 0.75]), np.array([0.5, 0.5]))
check("[2] u 1.0 -> 0.5, u 0.75 -> 0.25, both valid",
      abs(col[0, 0] - 0.5) < 1e-9 and abs(col[1, 0] - 0.25) < 1e-9 and ok.all(), (col, ok))
one = np.array([[True, False]])
col, ok = br.sample_bilinear(rgb, one, np.array([0.75, 1.25]), np.array([0.5, 0.5]))
check("[2] an unusable neighbour drops out: 0.0 valid; inside it: invalid",
      abs(col[0, 0]) < 1e-9 and ok[0] and not ok[1], (col, ok))

# [3]
two = np.vstack([SQUARE, SQUARE + [2.0, 0.0]])
tris2 = np.vstack([SQ_TRIS, SQ_TRIS + 4])
parts = br.islands(tris2, two)
check("[3] two squares -> two parts, the left one first",
      parts is not None and parts[0].tolist() == [True, True, False, False]
      and parts[1].tolist() == [False, False, True, True], parts)
strip = np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 1.0], [0.0, 1.0]])
check("[3] one strip -> None", br.islands(SQ_TRIS, strip) is None)

# [4]
pair = np.zeros((40, 100), bool)
pair[5:35, 5:45] = True
pair[5:35, 55:95] = True
pair[20, 45:55] = True
sp = br.alpha_parts(pair)
check("[4] cut at the bridge: 1200 | 1209 px", sp is not None and sp[0].sum() == 1200 and sp[1].sum() == 1209,
      None if sp is None else (sp[0].sum(), sp[1].sum()))
solid = np.zeros((40, 100), bool)
solid[5:35, 5:95] = True
check("[4] one block -> None", br.alpha_parts(solid) is None)

# [5]
p3 = np.array([[[0, 0, 0], [1, 0, 0], [1, 0, 1]], [[0, 0, 0], [1, 0, 1], [0, 0, 1]]], float)
even = p3[..., [0, 2]] * 10
check("[5] an even map -> 1.0", abs(br.anisotropy(p3, even) - 1.0) < 1e-9, br.anisotropy(p3, even))
wide = p3[..., [0, 2]] * [40, 10]
check("[5] 40 / 10 -> 4.0", abs(br.anisotropy(p3, wide) - 4.0) < 1e-9, br.anisotropy(p3, wide))

# [6]
src = (ROOT / "app/blender/scripts/garment_template_drape.py").read_text()
node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_up2")
ns = {"np": np}
exec(compile(ast.Module([node], []), "_up2", "exec"), ns)
row = np.array([[[0.0] * 3, [1.0] * 3]])
up = ns["_up2"](row, (2, 4))[..., 0]
check("[6] _up2 [0, 1] -> [0, 0.25, 0.75, 1]", np.allclose(up, [[0, 0.25, 0.75, 1]] * 2), up)

# [7]
from app.core import garment_template as gt  # noqa: E402


def piece(fabric, extra):
    px = np.zeros((100, 100, 4), np.uint8)
    px[10:90, 20:80, :3] = fabric
    px[10:90, 20:80, 3] = 255
    for (r0, r1, c0, c1), colour in extra:
        px[r0:r1, c0:c1, :3] = colour
    return px


mask, info = gt.opening_mask(piece((150, 100, 60), [((50, 90, 60, 67), (10, 10, 10))]))
want = np.zeros((100, 100), bool)
want[50:90, 60:67] = True
check("[7a] the slit is the mask: 280 px, 1 region", np.array_equal(mask, want) and info == {"px": 280, "regions": 1},
      info)
mask, info = gt.opening_mask(piece((20, 20, 20), [((50, 90, 60, 67), (5, 5, 5))]))
check("[7b] black fabric: no mask", info["px"] == 0, info)
mask, info = gt.opening_mask(piece((150, 100, 60), [((10, 15, 20, 80), (10, 10, 10)), ((40, 46, 30, 36), (10, 10, 10))]))
check("[7c] a dark top band and an inner spot stay fabric", info["px"] == 0, info)

# [8]
from PIL import Image  # noqa: E402
from app.core import garment_images as gi  # noqa: E402
for native, size in ((True, (1800, 2048)), (False, (450, 512))):
    render = TMP / f"render_{native}.png"
    Image.new("RGB", (2048, 2048), (90, 120, 30)).save(render)
    out = gi.crop_back(render, TMP / f"cut_{native}.png", 512, (31, 0), (450, 512), native=native)
    with Image.open(out) as im:
        check(f"[8] native={native}: {size[0]} x {size[1]}", im.size == size, im.size)

# [9]
from app.core import garment_template_views as tv  # noqa: E402
lines = tv.template_lines(gt.validate_params({"kind": "gloves", "fingers": "fingerless"})[0])
check("[9] gloves fingerless", lines == [tv.GLOVES_LINE, tv.TEMPLATE_LINES["fingers"]["fingerless"]], lines)
lines = tv.template_lines(gt.validate_params({"kind": "bra", "straps": "none"})[0])
check("[9] strapless bra", lines == [tv.TEMPLATE_LINES["straps"]["none"]], lines)
lines = tv.template_lines(gt.validate_params({"kind": "skirt", "slit": "left", "slit_m": 0.3})[0])
check("[9] skirt slit left", lines == [tv.TEMPLATE_LINES["slit"]["left"]], lines)

# [10]
w = gt.texture_warning({"coverage": 0.43})
check("[10] an old record: low coverage", w == {"coverage": 0.43, "iou": None, "low_coverage": True, "low_iou": False}, w)
w = gt.texture_warning({"coverage": 0.9, "iou": 0.2})
check("[10] low iou", w is not None and w["low_iou"] and not w["low_coverage"], w)
check("[10] a good bake: None", gt.texture_warning({"coverage": 0.9, "iou": 0.9}) is None)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
