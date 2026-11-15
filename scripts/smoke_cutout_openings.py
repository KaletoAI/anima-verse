#!/usr/bin/env python3
"""Ruling A60 (+ A81) — the cut-out opens where the worn view shows the body through an enclosed opening of the piece
(app/core/garment_openings.py; garment_images.cut_out, garments.cutout_openings_info / run_estimate, the setting
"Openings from the worn view" on the item).

Usage:
    ./.venv/bin/python scripts/smoke_cutout_openings.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no world, no
hub, no GPU, no server: the matte (``run_rembg``) and the upscale are stubs that count their calls. Every image is
synthetic (numpy), every number below derived by hand. The frame is 1536 x 1536 px (1536 = the reference height, so
every px constant is used as written; the cut-out record crops nothing: bbox [0, 0, 1536, 1536], side 1536, final
1536 -> ``crop_of`` (0, 0, 1536, 1536), scale 1).

THE SCENE (a blazer with a V-neck, as Kira's ``item_5bfe0cbc``, in rectangles):
  base figure  head rows 100..149 x 728..807 (80 wide), neck rows 150..259 x 748..787 (40), torso rows 260..1499 x
               618..917 (300); skin R = 170 + (x - 618) // 15, G = 120 + (y - 100) // 100, B = 90 on grey 128.
  garment G    (the piece-only view's mask) rows 170..259 x 728..807 (the collar behind the neck) + rows 260..899
               x 618..917 = 7 200 + 192 000 = 199 200 px.
  worn view    the base with G painted blue (40, 90, 160) except the OPENING O = rows 200..699 x 748..787 (the worn
               view shows the body there) and a HEM GAP rows 880..899 x 650..689 (body below an edge of the piece).
  piece-only   grey, G blue, the LINING rows 200..699 x 745..790 dark (20, 20, 20): 3 px wider on each side than
               the worn view's opening (the lapels of the two views never lie on the same pixels).

[1] Edge snap (``snap``, cut-out frame) of a straight seed rows 260..699 x 748..787 onto a lining L rows 260..699 x
    745..790. Reach = round(SNAP_REACH 0.02 x 300 garment columns) = 6. Per row the left window 742..754 holds the
    one step of the luminance (blue (40 + 90 + 160) / 3 = 96.7 -> 20) between 744 and 745: the border goes to 745;
    the right window 781..793 the step between 790 and 791: the border goes to 790 — 440 rows x 2 = 880 snapped.
    Straight borders: the running median and mean change nothing, a parallel pair does not converge (0 rows
    extended). The open/close by the cross (``SMOOTH_PX`` 1) takes the rectangle's 4 corner pixels (no cross fits
    them; the closing does not give them back): hole = L minus its 4 corners = 440 x 46 - 4 = 20 236 px. Lining
    beside (``lining_left``, ring 4, the inside 20 against the lapel 96.7): the seed leaves L's columns 745..747 and
    788..790 = 2 x 3 x 440 = 2 640 px, the hole only the 4 corners. A JAGGED seed — the left border alternating
    every 10 rows between 748 and 750 — snaps to the very same hole; its saw-tooth: a row's 31-row window holds at
    most 15 rows of its own value (own block 10, the same-valued blocks at ±20 at most 5), so the median is the
    other value and the residual 2 on every left row whose window does not reach past the 22 trimmed rows of an
    end: at least 396 - 30 rows of 396 -> mean >= 2 x 366 / 792 = 0.92, p95 2.0; after the snap mean 0, p95 0.
[2] The collar is kept. Seed rows 200..699, lining rows 200..699, collar line 260: the snap and smoothing work on
    rows 200..699 (the corners go at rows 200 and 699), then nothing above row 260 opens: hole = rows 260..699 x
    745..790 less the 2 bottom corners = 440 x 46 - 2 = 20 238 px; row 260 is the full 745..790. The cover
    (``feathered``) is 0 in the band (row 230) and 1 inside (row 400).
[3] The whole step (``opening``) on the scene. Framing: the worn view differs from the base only in the piece
    (199 200 - 20 000 - 800 = 178 400 px, under the 10 % the trimmed cost leaves out of 1536² / 4 sampled) -> cost 0.0,
    shift [0, 0]. Collar line (``neck_base_row``): height 1400, search rows 100 + 84 = 184 .. 100 + 308 = 408; the
    narrowest row there is 184 (40 wide, the neck), the first row from it at least 1.5 x 40 = 60 wide is 260. The
    shown body inside G: the opening O (500 x 40 = 20 000) and the hem gap (20 x 40 = 800); opened by
    ``garment_fit.OPEN_ERODE_PX`` 3 (a diamond: 6 pixels off each of the 4 corners) -> 19 976 and 776 px. Both differ
    between the worn view and the piece-only view in every pixel (Ruling A81, ``differs``: skin R >= 170 against the
    lining's 20 and the blue's 40, more than ``garment_fit.OPEN_DIFF`` 80) -> differs 1.0. The
    opening's ring (6) lies inside G (rows 170..199 above it are the collar) -> outline 0.0, an opening; the hem
    gap's ring reaches rows 900..905 below the piece (6 rows of a ring about 800 px: more than OPEN_SHOWN_OUTLINE_MAX
    0.25) -> no opening, it stays closed. The seed is cut at the collar line (rows 260..699), snapped as in [1]:
    rows 260..689 are exactly 745..790 (the corner pixels of row 260 aside); rows 690..699 lie inside the lining
    (the seed's corners are rounded there and the smoothing reaches 7 rows) — at most one pixel per side and row
    short: 20 236 - 20 <= px <= 20 236; nothing above row 260, nothing in the hem gap, nothing outside the lining;
    share = px / 199 200.
[4] Saw-tooth (``sawtooth``): a 100-row hole x 100..199 whose rows 50..59 start at 104: trimmed 5 rows each end ->
    90 + 90 residuals; the 31-row median is 100 everywhere -> 10 residuals of 4: mean 40 / 180 = 0.22, p95 = 4.0
    (the top 10 of 180 sorted values are 4, the 95th percentile index 170.05 falls among them).
[5] Framing vouched by the worn gate. A 400 x 1536 frame, the figure x 100..299, y 100..1499, a piece rows
    200..1299 x 100..299 in blue: the cost (every 2nd row/column: 200 x 768 = 153 600 samples, the best 138 240)
    keeps 138 240 - 98 600 unchanged = 39 640 piece samples, each at least (130 + 31 + 70) / 3 = 77 -> cost >=
    39 640 x 77 / 138 240 = 22.1 > 12: ``piece_mask`` refuses it; with ``framing_vouched`` it returns the mask and
    ``shown_body`` the figure outside it (280 000 - 219 996 = 60 004 px, the A46 mask of the piece rectangle less
    its 4 corners). ``vouched_by_worn_gate``: an accepted worn record whose final gate is ok with drift 0.57 <=
    VOUCH_DRIFT_PX 1.0 and xor 0.0076 <= its limit 0.0268 vouches; drift 1.2, xor above the limit, ok False or a
    record not accepted do not.
[6] In the chain, on a throwaway world (character Demo, an own-mesh clothing piece "Blazer", slot "outer"): base
    copy, accepted worn and piece-only views of [3] on both views (the back without an opening: worn = the piece
    over the whole of G; the records as the A46 smoke writes them: gate ok with ``hem_t``, the worn back a
    composite). ``cut_out`` front + back: one upscale each (side int(1.15 x 730) = 839 < 1024; the stub doubles ->
    final 1678); the front's record ``opening`` found + applied (Auto), the back's not found ("the worn view shows
    no body inside the piece"); the front's alpha is 0 in the middle of the V (row 450, column 767 -> cut-out frame
    ((767 - 768 + 419) x 2, (450 - 535 + 419) x 2) = (836, 668)) and 255 in the band behind the neck (row 230 ->
    (836, 228)). Off on the front (``set_choice``): stored ``{"front": "off"}``; an update that does not name it
    keeps it; the fingerprint is unchanged; ``cutout_openings_info`` front due [cutout front 0, mesh 1, fit 0]
    (reusable: same piece-only image, upscale applied), its options auto [] / off the same; the back's options both
    [] (no opening found: Off changes nothing). ``run_estimate`` with a prepared mesh accepted and the fit missing:
    before [fit] 0 jobs, after Off [cutout, mesh, fit] 1 job (the mesh; the cut-out reuses its colours). ``cut_out``
    again (not forced): due -> made again with 0 upscale calls, colours "reused", the opening found but not applied,
    alpha 255 at the V; nothing due. Auto again -> due, made again, alpha 0 at the V, 0 upscale calls. A record
    without ``opening`` (made before A60) is not due under either choice; one of another rule version is — a record
    of rule version 1 (before Ruling A81) reads due under either choice, so the chain makes it again.
[7] Fails on the old code (e36fbe9066922ddd62312b73bc4791d93db0debb): ``app/core/garment_openings.py`` does not
    exist there, its ``piece_mask`` has no ``framing_vouched`` (the 77c4 blazer group, cost 12.69, gave no evidence),
    its ``cut_out`` writes no ``opening`` and its item model keeps no ``cutout_openings``.
[8] Ruling A81 — a light, warm piece whose fold matches the skin is no opening. The scene of [3] with the piece
    CREAM (225, 215, 200) and a FOLD F = rows 400..499 x 700..799 inside the torso part where the worn view shows
    the base's own skin pixels (the strongest false evidence: the A46 mask matches it exactly), and the piece-only
    view = the worn view inside G, the fold included (Ylva's linen blouse: the same fabric in both views). Framing:
    the worn view differs from the base only in G minus F (199 200 - 10 000 = 189 200 px, fewer than the 10 % the
    trimmed cost leaves out) -> cost 0.0. The A46 mask: every cream pixel differs from every reference pixel in its
    5 px disc by more than GARMENT_DRGB 20 (mean |Δ| to the skin >= (36 + 81 + 110) / 3 = 75.7, to the grey
    (97 + 87 + 72) / 3 = 85.3), F not at all (worn = base); the piece's colour is the cream, no cream pixel is
    nearer the skin than the cream, so no skin is taken out; the closing (2) takes 3 px off each of F's 4 corners
    (9 988 px; a hole of more than 0.001 x 380 400 = 380 px stays). The shown body in G: that hole, opened by 3 ->
    the rectangle's own opening, 10 000 - 4 x 6 = 9 976 px (opening is increasing and idempotent), bbox
    [700, 400, 799, 499]; its ring lies inside G -> outline 0.0 (enclosed, as A51 wants an opening). But the worn
    view and the piece-only view are equal in every pixel of it -> differs 0.0 < ``DIFFERS_MIN_SHARE`` 0.5 -> no
    opening: found False, reason "no opening: inside the piece the piece-only view shows what the worn view shows
    (at most 0.0 of it differs)". The V of [3] still opens (differs 1.0) — the hand-derived V is [3] itself.
[9] Fails on the old code (ea25128b1f55d95a14875eb631cb244e70155d44, before Ruling A81): its ``seed`` takes no
    ``differ`` and its ``opening`` no piece-only colours, its ``VERSION`` is 1, and on the fold scene of [8] its
    rule finds an opening: the same 9 976 px component, outline 0.0, opening True — the fold is cut.
"""
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "e36fbe9066922ddd62312b73bc4791d93db0debb"
OLD_A81 = "ea25128b1f55d95a14875eb631cb244e70155d44"
CREAM = (225, 215, 200)
FAILS = []
N = 1536
GREY = 128
BLUE = (40, 90, 160)
DARK = (20, 20, 20)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def garment():
    g = np.zeros((N, N), bool)
    g[170:260, 728:808] = True
    g[260:900, 618:918] = True
    return g


def lining_cut(rows):
    rgb = np.full((N, N, 3), GREY, np.uint8)
    rgb[garment()] = BLUE
    rgb[rows[0]:rows[1] + 1, 745:791] = DARK
    return rgb


def rect(y0, y1, x0, x1, shape=(N, N)):
    m = np.zeros(shape, bool)
    m[y0:y1 + 1, x0:x1 + 1] = True
    return m


def without(m, pixels):
    out = m.copy()
    for y, x in pixels:
        out[y, x] = False
    return out


def scene():
    """(base rgb, figure, worn rgb, piece-only rgb, garment) of the module docstring."""
    base = np.full((N, N, 3), GREY, np.uint8)
    fig = rect(100, 149, 728, 807) | rect(150, 259, 748, 787) | rect(260, 1499, 618, 917)
    ys, xs = np.nonzero(fig)
    base[ys, xs, 0] = 170 + (xs - 618) // 15
    base[ys, xs, 1] = 120 + (ys - 100) // 100
    base[ys, xs, 2] = 90
    g = garment()
    worn = base.copy()
    worn[g & ~rect(200, 699, 748, 787) & ~rect(880, 899, 650, 689)] = BLUE
    ghost = lining_cut((200, 699))
    return base, fig, worn, ghost, g


def part_snap():
    from app.core import garment_openings as go
    print("[1] edge snap")
    g = garment()
    rgb = lining_cut((260, 699))
    lining = rect(260, 699, 745, 790)
    want = without(lining, ((260, 745), (260, 790), (699, 745), (699, 790)))
    hole, n = go.snap(rgb, g, rect(260, 699, 748, 787), collar_c=None, scale=1.0, height=N)
    check("snap numbers", n, {"components": 1, "snapped_rows": 880, "extended_rows": 0, "reach_px": 6})
    check("hole = the lining less its 4 corners", (bool((hole == want).all()), int(hole.sum())), (True, 20236))
    check("lining beside: seed -> hole", (go.lining_left(rgb, g, rect(260, 699, 748, 787), 20.0, 4),
                                          go.lining_left(rgb, g, hole, 20.0, 4)), (2640, 4))
    jag = np.zeros((N, N), bool)
    for y in range(260, 700):
        jag[y, (748 if ((y - 260) // 10) % 2 == 0 else 750):788] = True
    hole2, _n2 = go.snap(rgb, g, jag, collar_c=None, scale=1.0, height=N)
    seed_st, hole_st = go.sawtooth(jag), go.sawtooth(hole2)
    check("jagged seed: the same hole", bool((hole2 == want).all()), True)
    check("jagged seed: saw-tooth p95, mean >= 0.92", (seed_st["p95"], seed_st["mean"] >= 0.92), (2.0, True))
    check("after the snap: no saw-tooth", hole_st, {"mean": 0.0, "p95": 0.0})

    print("[2] the collar is kept")
    rgb3 = lining_cut((200, 699))
    hole3, _n3 = go.snap(rgb3, g, rect(200, 699, 748, 787), collar_c=260, scale=1.0, height=N)
    want3 = without(rect(260, 699, 745, 790), ((699, 745), (699, 790)))
    check("hole = rows 260..699 less 2 corners", (bool((hole3 == want3).all()), int(hole3.sum()),
                                                  bool(hole3[:260].any())), (True, 20238, False))
    cover = go.feathered(hole3, 1.0, N)
    check("cover: band 0, inside 1", (float(cover[230, 767]), float(cover[400, 767])), (0.0, 1.0))

    print("[4] saw-tooth")
    h = rect(0, 99, 100, 199, shape=(100, 300))
    h[50:60, 100:104] = False
    check("a 10-row notch of 4", go.sawtooth(h, rows=31), {"mean": 0.22, "p95": 4.0})


def part_opening():
    from app.core import garment_fit as gf
    from app.core import garment_openings as go
    print("[3] the whole step")
    base, fig, worn, ghost, g = scene()
    check("collar line", go.neck_base_row(fig), 260)
    record = {"bbox": [0, 0, N, N], "side": N, "size": [N, N]}
    check("crop", go.crop_of(record), ((0, 0, N, N), N, N))
    cover, n = go.opening(worn, base, fig, ghost, g, ghost, g.astype(np.float32) * 255, record)
    check("framing", (n["framing"]["shift"], n["framing"]["cost"], n["framing"]["ok"]), ([0, 0], 0.0, True))
    comps = n["components"]
    check("components: the opening, the hem gap",
          [(c["pixels"], c["bbox"], c["differs"], c["opening"]) for c in comps],
          [(19976, [748, 200, 787, 699], 1.0, True), (776, [650, 880, 689, 899], 1.0, False)])
    check("outlines", (comps[0]["outline"], comps[1]["outline"] > gf.OPEN_SHOWN_OUTLINE_MAX), (0.0, True))
    hole = cover > 0.5
    lining = rect(260, 699, 745, 790)
    want = without(lining, ((260, 745), (260, 790)))
    check("found, collar row", (n["found"], n["collar_row"]), (True, 260))
    check("rows 260..689 exactly the lining", bool((hole[260:690] == want[260:690]).all()), True)
    check("nothing above the collar, in the hem gap, outside the lining",
          (bool(hole[:260].any()), bool(hole[880:900, 650:690].any()), int((hole & ~lining).sum())), (False, False, 0))
    check("px", (20236 - 20 <= n["px"] <= 20236, n["px"] == int(hole.sum()), n["share"]),
          (True, True, round(n["px"] / 199200, 4)))
    check("saw-tooth after", n["sawtooth"], {"mean": 0.0, "p95": 0.0})


def part_vouch():
    from app.core import garment_from_worn as fw
    from app.core import garment_openings as go
    print("[5] framing vouched by the worn gate")
    h, w = 1536, 400
    base = np.full((h, w, 3), GREY, np.uint8)
    fig = rect(100, 1499, 100, 299, shape=(h, w))
    ys, xs = np.nonzero(fig)
    base[ys, xs, 0] = 170 + (xs - 100) // 10
    base[ys, xs, 1] = 120 + (ys - 100) // 100
    base[ys, xs, 2] = 90
    worn = base.copy()
    worn[200:1300, 100:300] = BLUE
    framing = fw.align(worn, base)
    check("cost above the limit", (framing["shift"], framing["cost"] >= 22.08, framing["ok"]), ([0, 0], True, False))
    try:
        fw.piece_mask(base, fig, worn)
        refused = False
    except fw.FromWornRefused:
        refused = True
    check("not vouched: refused", refused, True)
    mask, _a, _n = fw.piece_mask(base, fig, worn, framing_vouched=True)
    shown, numbers = go.shown_body(base, fig, worn, vouch={"outside_drift_px": 0.57})
    check("vouched: the mask, the body outside it", (int(mask.sum()), int(shown.sum()),
                                                      "vouched_by" in numbers["alignment"]), (219996, 60004, True))
    gate = {"ok": True, "outside_drift_px": 0.57, "outside_xor": 0.0076, "outside_xor_limit": 0.0268}

    def rec(accepted=True, **kw):
        return {"accepted": accepted, "attempt": 1, "gates": {"first": {**gate, **kw}}}
    check("the worn gate vouches", go.vouched_by_worn_gate(rec()),
          {"outside_drift_px": 0.57, "outside_xor": 0.0076, "outside_xor_limit": 0.0268})
    check("drift 1.2 / xor beyond / refused / not accepted: no",
          [go.vouched_by_worn_gate(r) for r in (rec(outside_drift_px=1.2), rec(outside_xor=0.03), rec(ok=False),
                                                rec(accepted=False))], [None, None, None, None])


def fold_scene():
    """(base rgb, figure, worn rgb, piece-only rgb, garment) of [8]: a cream piece with a skin-coloured fold."""
    base, fig, _worn, _ghost, g = scene()
    fold = rect(400, 499, 700, 799)
    worn = base.copy()
    worn[g & ~fold] = CREAM
    ghost = np.full((N, N, 3), GREY, np.uint8)
    ghost[g] = worn[g]
    return base, fig, worn, ghost, g


def part_fold():
    from app.core import garment_openings as go
    print("[8] a light, warm piece whose fold matches the skin (Ruling A81)")
    base, fig, worn, ghost, g = fold_scene()
    record = {"bbox": [0, 0, N, N], "side": N, "size": [N, N]}
    cover, n = go.opening(worn, base, fig, ghost, g, ghost, g.astype(np.float32) * 255, record)
    check("framing", (n["framing"]["shift"], n["framing"]["cost"]), ([0, 0], 0.0))
    check("the fold: enclosed, but nothing differs",
          [(c["pixels"], c["bbox"], c["outline"], c["differs"], c["opening"]) for c in n["components"]],
          [(9976, [700, 400, 799, 499], 0.0, 0.0, False)])
    check("no opening", (cover is None, n["found"], n["reason"]),
          (True, False, "no opening: inside the piece the piece-only view shows what the worn view shows "
                         "(at most 0.0 of it differs)"))
    check("the rule version", go.VERSION, 2)


def part_old_a81():
    import types
    print("[9] fails on the old code (" + OLD_A81[:9] + ", before Ruling A81)")
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_A81}:app/core/garment_openings.py"],
                         capture_output=True, text=True, check=True).stdout
    old = types.ModuleType("old_garment_openings")
    exec(compile(src, "old_garment_openings.py", "exec"), old.__dict__)
    check("old seed: no differ, old VERSION",
          ("differ" in inspect.signature(old.seed).parameters, old.VERSION), (False, 1))
    base, fig, worn, ghost, g = fold_scene()
    record = {"bbox": [0, 0, N, N], "side": N, "size": [N, N]}
    _cover, n = old.opening(worn, base, fig, g, ghost, g.astype(np.float32) * 255, record)
    check("old rule: the fold is cut",
          (n["found"], [(c["pixels"], c["outline"], c["opening"]) for c in n["components"]]),
          (True, [(9976, 0.0, True)]))


def png_bytes(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


MATTES = []
UPSCALES = []


def rembg_stub(data, model="u2net", **kwargs):
    """Every pixel more than 2 away from the grey is the figure (no model)."""
    from PIL import Image
    MATTES.append(1)
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = ((np.abs(rgb - GREY) > 2).any(2) * 255).astype(np.uint8)
    return png_bytes(mask) if kwargs.get("only_mask") else png_bytes(np.dstack([rgb.astype(np.uint8), mask]))


class UpscaleStub:
    def upscale_image(self, image_bytes, **kwargs):
        from PIL import Image
        UPSCALES.append(1)
        with Image.open(io.BytesIO(image_bytes)) as im:
            up = im.convert("RGB").resize((im.width * 2, im.height * 2), Image.Resampling.NEAREST)
        out = io.BytesIO()
        up.save(out, format="PNG")
        return {"bytes": out.getvalue(), "status": "applied", "backend": "stub"}


def setup() -> Path:
    """The throwaway storage + instance — first, before any app module is imported. Its root."""
    root = Path(tempfile.mkdtemp(prefix="cutout-openings-"))
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    from app.core import config
    config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
    from app.core import db
    db.init_schema()
    shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
    from app.plugins.loader import discover_packages
    discover_packages(root / "plugins", force=True)
    return root


def part_chain():
    from app.core import garment_assembly, garment_images, garment_openings as go, garment_source, garments
    from app.core import garment_store as gs
    from app.imagegen import service
    from app.models import character as charmod
    from app.models import inventory
    from app.models.character import save_character_profile
    print("[6] in the chain")
    garment_assembly.schedule = lambda *a, **k: False
    charmod.run_rembg = rembg_stub
    service.get_image_service = lambda: UpscaleStub()
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
             "character_appearance": "slender",
             "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"}, "build": {"type": "athletic"},
                            "hair": {"length": "medium", "color": "blonde"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)
    piece = {"slots": ["outer"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"}
    iid = inventory.add_item(name="Blazer", category="outfit_piece", prompt_fragment="a black blazer",
                             outfit_piece=piece)["id"]
    check("inventory", inventory.add_to_inventory("Demo", iid), True)
    check("equip", inventory.equip_piece("Demo", iid, source="smoke")["status"], "ok")
    fsig = gs.garment_fsig("Demo", iid)
    base, fig, worn, ghost, g = scene()
    from PIL import Image
    worn_back = base.copy()
    worn_back[g] = BLUE
    ghost_back = np.full((N, N, 3), GREY, np.uint8)
    ghost_back[g] = BLUE
    for view, w_img, gh in (("front", worn, ghost), ("back", worn_back, ghost_back)):
        copy = garment_source.base_copy("Demo", iid, fsig, view)
        copy.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.dstack([base, fig.astype(np.uint8) * 255])).save(copy)
        for step, arr in (("worn", w_img), ("ghost", gh)):
            path = gs.garment_path("Demo", iid, fsig, "image", step=step, view=view)
            path.write_bytes(png_bytes(arr))
            record = {"accepted": True, "attempt": 1, "created_at": "2026-11-14T10:00:00+00:00",
                      "gates": {"first": {"view": view, "ok": True, "reasons": [], "hem_t": 0.65,
                                          "gate_version": 7, "attempt": 1}}}
            if step == "worn" and view == "back":
                record["fit"] = "composite"
            gs.write_record(path.with_suffix(".json"), record)
    for view in gs.GARMENT_VIEWS:
        garment_images.cut_out("Demo", iid, fsig, view)
    check("one upscale per view", len(UPSCALES), 2)
    cut = {v: gs.garment_path("Demo", iid, fsig, "image", step="cutout", view=v) for v in gs.GARMENT_VIEWS}
    rec = {v: gs.read_record(cut[v].with_suffix(".json")) for v in gs.GARMENT_VIEWS}
    check("crop record", (rec["front"]["bbox"], rec["front"]["side"], rec["front"]["size"]),
          ([618, 170, 918, 900], 839, [1678, 1678]))
    fo, bo = rec["front"]["opening"], rec["back"]["opening"]
    check("front: found, applied (Auto)", (fo["version"], fo["choice"], fo["found"], fo["applied"]),
          (2, "auto", True, True))
    check("back: none", (bo["found"], bo["applied"], bo["reason"]),
          (False, False, "the worn view shows no body inside the piece"))

    def alpha_at(view, xy):
        with Image.open(cut[view]) as im:
            return im.getchannel("A").getpixel(xy)
    check("front alpha: V 0, band 255", (alpha_at("front", (836, 668)), alpha_at("front", (836, 228))), (0, 255))

    prepared = gs.garment_path("Demo", iid, fsig, "prepared")
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_bytes(b"glb")
    gs.write_record(prepared.with_suffix(".json"), {"accepted": True})

    def est():
        r = garments.run_estimate("Demo", iid)
        return (r["steps"], r["hub_jobs"])
    check("everything done but the fit", est(), (["fit"], 0))
    info = garments.cutout_openings_info("Demo", iid, fsig)
    check("info before", (info["front"]["choice"], info["front"]["due"], info["front"]["reusable"],
                          info["front"]["options"]["off"]["due"], info["back"]["options"]["off"]["due"]),
          ("auto", [], True, [{"step": "cutout", "view": "front", "jobs": 0}, {"step": "mesh", "jobs": 1},
                              {"step": "fit", "jobs": 0}], []))

    go.set_choice("Demo", iid, "front", "off")
    check("stored", inventory.get_item(iid)["outfit_piece"].get("cutout_openings"), {"front": "off"})
    inventory.update_item(iid, {"outfit_piece": {"slots": ["outer"], "mesh_mode": "own_mesh"}})
    check("an update that does not name it keeps it", inventory.get_item(iid)["outfit_piece"].get("cutout_openings"),
          {"front": "off"})
    check("the fingerprint is unchanged", gs.garment_fsig("Demo", iid), fsig)
    info = garments.cutout_openings_info("Demo", iid, fsig)
    check("info after Off: due, options",
          (info["front"]["choice"], info["front"]["due"], info["front"]["options"]["auto"]["due"]),
          ("off", [{"step": "cutout", "view": "front", "jobs": 0}, {"step": "mesh", "jobs": 1},
                   {"step": "fit", "jobs": 0}], []))
    check("estimate after Off", est(), (["cutout", "mesh", "fit"], 1))
    before = len(UPSCALES)
    garment_images.cut_out("Demo", iid, fsig, "front")
    fr = gs.read_record(cut["front"].with_suffix(".json"))
    check("made again: no upscale, colours reused, found not applied",
          (len(UPSCALES) - before, fr.get("colours"), fr["opening"]["found"], fr["opening"]["applied"]),
          (0, "reused", True, False))
    check("alpha at the V now 255", alpha_at("front", (836, 668)), 255)
    check("nothing due", garments.cutout_openings_info("Demo", iid, fsig)["front"]["due"], [])
    go.set_choice("Demo", iid, "front", "auto")
    check("Auto drops the key", "cutout_openings" in inventory.get_item(iid)["outfit_piece"], False)
    check("Auto: due again", garment_images.cutout_due("Demo", iid, fsig, "front"), True)
    garment_images.cut_out("Demo", iid, fsig, "front")
    check("Auto again: hole, no upscale", (alpha_at("front", (836, 668)), len(UPSCALES) - before), (0, 0))

    print("    the due rule")
    made = {"opening": {"version": go.VERSION, "found": True, "applied": True}}
    check("legacy / version / applied+auto / applied+off / none found",
          [go.due({}, "auto"), go.due({}, "off"), go.due({"opening": {"version": 0, "found": False}}, "auto"),
           go.due(made, "auto"), go.due(made, "off"),
           go.due({"opening": {"version": go.VERSION, "found": False, "applied": False}}, "auto")],
          [False, False, True, False, True, False])
    v1 = {"opening": {"version": 1, "found": False, "applied": False}}
    check("a record of rule version 1 (before A81): due under either choice", (go.due(v1, "auto"), go.due(v1, "off")),
          (True, True))


def part_old_code():
    print("[7] fails on the old code (" + OLD[:9] + ")")

    def show(path):
        return subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True)
    check("garment_openings.py at the old commit", show("app/core/garment_openings.py").returncode != 0, True)
    fw_src = show("app/core/garment_from_worn.py").stdout
    check("old piece_mask: no framing_vouched", ("def piece_mask(" in fw_src, "framing_vouched" in fw_src),
          (True, False))
    gi_src = show("app/core/garment_images.py").stdout
    cut_src = gi_src[gi_src.index("def cut_out("):]
    cut_src = cut_src[:cut_src.index("\ndef ", 1)]
    check("old cut_out: no opening", ('"opening"' in cut_src, "garment_openings" in cut_src), (False, False))
    check("old inventory: no cutout_openings", "cutout_openings" in show("app/models/inventory.py").stdout, False)
    from app.core import garment_from_worn as fw
    check("new piece_mask takes framing_vouched", "framing_vouched" in inspect.signature(fw.piece_mask).parameters,
          True)


def main() -> int:
    scratch = setup()
    try:
        part_snap()
        part_opening()
        part_vouch()
        part_chain()
        part_old_code()
        part_fold()
        part_old_a81()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
