#!/usr/bin/env python3
"""Ruling A79 (2026-11-15): the worn hem the ghost gate compares against
leaves out only the worn pixels that are SKIN in the same light, never the
piece in shadow (app/core/garment_gates.py ``worn_skin`` /
``ghost_clothing_gate``, ghost gate version 8; app/core/garment_clothing.py
``GATE_VERSIONS``; app/core/garment_images.py ``_regate_stored``).

The case (live 2026-11-15 00:19 / 00:22): Ylva's laced linen blouse, both
ghost fronts refused "garment ends at another height than the worn piece",
ghost 0.46146 / 0.46568 against a worn hem of 0.32788. The cream in the
shadow of the lacing lay within 30 of the thigh skin sample, the plain RGB
test took those thin rows out of the worn region, the columns fell apart and
their longest runs ended under the bust. Measured the A32 way (the pixel
against skin and piece, each scaled to the pixel's own brightness) the
shaded cream is the piece: the worn hem is 0.46146, attempt 1 |Δ| 0.0.

Usage:
    ./.venv/bin/python scripts/smoke_ghost_worn_skin_hem.py
    A79_FIXTURE_DIR=/path ./.venv/bin/python scripts/smoke_ghost_worn_skin_hem.py   # + [6]

A throwaway storage root, synthetic images, the real gates; no world, no hub,
no server, no outbound request. Needs git for [4] (the pinned old code).

Geometry (the frame of smoke_ghost_skin_vs_garment.py), W 600 x H 1000 on
grey 128: BASE = skin S2 (174, 122, 98), cols [120, 480) rows [100, 900) ->
y0 100, Hb = 899 - 100 = 799; the shoulder row 100 + int(0.19 x 799) = 251
spans cols 120..479 -> centre column round(299.5) = 300; the hem band is
± round(0.04 x 799) = ± 32 -> cols 268..332 (65 columns, half of them =
32.5 must give a run). The region G handed to the gate: cols [200, 400) rows
[300, 600) -> 300 rows; a run counts from 0.25 x 300 = 75 rows. A mask row r
gives hem (r - 100) / 799.

THE CASES, DERIVED BY HAND
[0] The pixel test (block "Skin or piece", A32's numbers): the shaded cream
    D2 (135, 114, 100) is |D2 - S2| = (39 + 8 + 2) / 3 = 16.33 from the skin
    (<= SKIN_DRGB 30: "skin" by the plain test); in its own light
    (brightness 116.33) the skin scaled by 116.33 / 131.33 is 12.751 away,
    the piece C2 (210, 195, 178) scaled by 116.33 / 194.33 only 6.192 ->
    the piece. The re-shaded skin R (196, 140, 112): |R - S2| = (22 + 18 +
    14) / 3 = 18.0 (<= 30); scaled skin 149.33 / 131.33 = 1.13706 ->
    (197.848, 138.721, 111.431), |Δ| (1.848 + 1.279 + 0.569) / 3 = 1.232; the
    black piece K (40, 40, 60) scaled by 149.33 / 46.67 = 3.2 -> (128, 128,
    192), |Δ| (68 + 12 + 80) / 3 = 53.333 -> skin.
[1] Ylva's case. WORN_Y = BASE with G in C2 and four thin shadow rows of the
    lacing in D2 across cols 250..349: rows 400-401, 450-451, 500-501,
    550-551. GHOST_Y = G in C2 alone (the blouse as worn).
    Old (plain test): the shadow rows leave G's band columns as runs
    300..399 (100), 402..449, 452..499, 502..549, 552..599 (48 each); the
    longest ends at row 399 -> worn hem 299 / 799 = 0.37422. The ghost's
    column runs 300..599 -> 499 / 799 = 0.62453; |Δ| 200 / 799 = 0.25031 >
    0.02 -> refused "garment ends at another height than the worn piece".
    New (``worn_skin``): D2 is nearer the piece -> nothing of G is left out
    -> the worn hem 0.62453, |Δ| 0.0 -> ok, no reason.
    ``worn_skin`` on WORN_Y: 0 pixels of G (the base skin outside G is
    skin: 360 x 800 - 300 x 200 = 228000 pixels).
[2] Length still matters (worn hem 0.62453, HEM_AGREE 0.02):
    GHOST_LONG rows 300..639 -> 539 / 799 = 0.67459, |Δ| 40 / 799 = 0.05006
    -> hem_refused; GHOST_SHORT rows 300..579 -> 479 / 799 = 0.59950,
    |Δ| 20 / 799 = 0.02503 -> hem_refused; GHOST_NEAR rows 300..589 ->
    489 / 799 = 0.61202, |Δ| 10 / 799 = 0.01252 -> not hem_refused.
[3] Lit skin stays out (Ruling A17, Kira's cutaway blazer: the crotch an edit
    re-shaded below a black piece). G_K = G plus a patch cols [260, 340)
    rows [600, 680) — the re-shaded skin the worn region holds. WORN_K = BASE
    with G in K and the patch in R. ``piece_colour`` = the median of 60000 K
    and 6400 R pixels = K. R is skin by both tests -> the patch is left out:
    worn hem 0.62453 (old and new). Without leaving it out the band columns
    (268..332, all inside the patch's 260..339) run 300..679 -> 579 / 799 =
    0.72466. GHOST_K = G in K -> |Δ| 0.0, ok; GHOST_K_LONG = G and the patch
    in K (the ghost hangs down to the crotch) -> 0.72466, |Δ| 80 / 799 =
    0.10013 -> hem_refused (new as old).
[4] Fails on the old code (garment_gates.py PINNED at 9312d5058, ghost gate
    version 7): [1] worn_hem_c 0.37422, refused for the hem; [3] the same
    numbers as new (0.62453, ok / refused).
[5] Re-judged before any render: GATE_VERSIONS["ghost"] = GHOST_GATE_VERSION
    = 8 (Ruling A79), a version 7 record is stale. ``_regate_stored`` on two
    stored attempts refused under 7: attempt 1 = GHOST_LONG (still refused,
    regated_from 7), attempt 2 = GHOST_Y (passes) -> attempt 2 published as
    the view's final, accepted, no render. The re-gate goes through
    ``garment_clothing.gate``, whose region is ``garment_region`` of base and
    worn: |C2 - S2| = 63 > GARMENT_DRGB marks G, the shadow rows (16.33) are
    holes the closing and the hole filling close -> G less the 4 corner
    pixels its opening cuts.
[6] Optional, A79_FIXTURE_DIR: copies of the live case (base_front,
    worn_front, ghost_front.try1 registered as the chain registers it,
    ghost_front.try2; each ``<name>.png`` + ``<name>.mask.png``, the masks
    BiRefNet-DIS as cached): worn hem 0.46146; try1 hem 0.46146 |Δ| 0.0,
    try2 0.46568 |Δ| 0.0042 — both pass the hem now.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_ghost_worn_skin_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_clothing, garment_gates as gg, garment_images as gi  # noqa: E402

PINNED = "9312d5058"
FAILS = []
W, H = 600, 1000
TMP = Path(_TMP)
S2, C2, D2 = (174, 122, 98), (210, 195, 178), (135, 114, 100)
K, R = (40, 40, 60), (196, 140, 112)
HEM = "garment ends at another height than the worn piece"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def canvas():
    return np.full((H, W, 3), 128, dtype=np.uint8)


def mask_of(rgb):
    return np.abs(rgb.astype(np.int16) - 128).max(2) > 2


G = np.zeros((H, W), dtype=bool)
G[300:600, 200:400] = True
PATCH = np.zeros((H, W), dtype=bool)
PATCH[600:680, 260:340] = True
G_K = G | PATCH
BASE = canvas()
BASE[100:900, 120:480] = S2


def ghost(rows_end, colour=C2, extra=None):
    img = canvas()
    img[300:rows_end, 200:400] = colour
    if extra is not None:
        img[extra] = colour
    return img


WORN_Y = BASE.copy()
WORN_Y[G] = C2
for r in (400, 450, 500, 550):
    WORN_Y[r:r + 2, 250:350] = D2
GHOST_Y = ghost(600)
GHOST_LONG, GHOST_SHORT, GHOST_NEAR = ghost(640), ghost(580), ghost(590)
WORN_K = BASE.copy()
WORN_K[G] = K
WORN_K[PATCH] = R
GHOST_K = ghost(600, K)
GHOST_K_LONG = ghost(600, K, PATCH)


def gate(module, img, worn=WORN_Y, region=G):
    return module.ghost_clothing_gate(BASE, mask_of(BASE), region, img, mask_of(img), view="front",
                                      worn_rgb=worn)


def hem_reasons(record):
    return [r for r in record.get("reasons") or [] if r.startswith(HEM)]


def pinned(commit, name):
    """app/core/<name>.py at ``commit`` as a throwaway module."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/{name}.py"],
                         check=True, capture_output=True, text=True).stdout
    path = TMP / f"{name}_{commit}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(f"{name}_{commit}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png(arr, path):
    from PIL import Image
    Image.fromarray(arr).save(path, format="PNG")


def regate_part():
    """[5] (module docstring)."""
    from app.core.garment_store import garment_path, read_record, write_record
    print("[5] re-judged before any render")
    check("GATE_VERSIONS ghost", (garment_clothing.GATE_VERSIONS.get("ghost"), gg.GHOST_GATE_VERSION), (8, 8))
    check("version 7 stale, 8 not (A79)",
          (gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 7}),
           gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 8})), (True, False))
    check("garment_region = G less 4 corners",
          int((gg.garment_region(BASE, mask_of(BASE), WORN_Y, mask_of(WORN_Y)) ^ G).sum()), 4)
    who, item, fsig = "Demo", "item_demo_blouse", "a1b2c3d4e5f6"
    old_gg = pinned(PINNED, "garment_gates")
    stored = {1: GHOST_LONG, 2: GHOST_Y}
    for n, img in stored.items():
        target = garment_path(who, item, fsig, "image", step="ghost", view="front", attempt=n)
        target.parent.mkdir(parents=True, exist_ok=True)
        png(img, target)
        old = gate(old_gg, img)
        check(f"attempt {n} refused under 7 for the hem", (old["ok"], bool(hem_reasons(old))), (False, True))
        write_record(target.with_suffix(".json"), {
            "garment": {"item_id": item, "fsig": fsig, "step": "ghost", "view": "front", "attempt": n},
            "gate": {**old, "attempt": n}})
    final = garment_path(who, item, fsig, "image", step="ghost", view="front")

    def regate(path, _old):
        from PIL import Image
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"))
        return garment_clothing.gate("ghost", "front", base_rgb=BASE, base_mask=mask_of(BASE), source_rgb=WORN_Y,
                                     source_mask=mask_of(WORN_Y), edit_rgb=rgb, edit_mask=mask_of(rgb))

    # Stubbed: dropping the later steps of the view (it reads the item from the world; not under test).
    drop_later, gi._drop_later = gi._drop_later, lambda *a, **k: None
    try:
        hit = gi._regate_stored(who, item, fsig, "ghost", "front", garment_clothing, final=final, regate=regate)
    finally:
        gi._drop_later = drop_later
    check("attempt 2 published", hit == final, True)
    rec = read_record(final.with_suffix(".json"))
    check("final: accepted, attempt 2", (rec.get("accepted"), rec.get("attempt")), (True, 2))
    t1 = read_record(garment_path(who, item, fsig, "image", step="ghost", view="front", attempt=1)
                     .with_suffix(".json")).get("gate") or {}
    check("attempt 1 judged again, still refused for the hem",
          (t1.get("ok"), t1.get("regated_from"), t1.get("gate_version"), bool(hem_reasons(t1))), (False, 7, 8, True))
    t2 = read_record(garment_path(who, item, fsig, "image", step="ghost", view="front", attempt=2)
                     .with_suffix(".json")).get("gate") or {}
    check("attempt 2 judged again, accepted", (t2.get("ok"), t2.get("regated_from"), t2.get("worn_hem_c")),
          (True, 7, 0.62453))


def fixture_part():
    """[6] copies of the live case (module docstring)."""
    folder = os.environ.get("A79_FIXTURE_DIR")
    names = ("base_front", "worn_front", "ghost_front.try1", "ghost_front.try2")
    files = {n: (Path(folder) / f"{n}.png", Path(folder) / f"{n}.mask.png") for n in names} if folder else {}
    if not folder or not all(p.is_file() and m.is_file() for p, m in files.values()):
        print("[6] SKIPPED — no copies of the live case (A79_FIXTURE_DIR)")
        return
    from PIL import Image
    print("[6] copies of the live case")

    def load(name):
        p, m = files[name]
        with Image.open(p) as im, Image.open(m) as mk:
            return np.asarray(im.convert("RGB")), np.asarray(mk.convert("L")) >= 128

    base_rgb, base_mask = load("base_front")
    worn_rgb, worn_mask = load("worn_front")
    for name, hem, delta in (("ghost_front.try1", 0.46146, 0.0), ("ghost_front.try2", 0.46568, 0.0042)):
        rgb, mask = load(name)
        record = garment_clothing.gate("ghost", "front", base_rgb=base_rgb, base_mask=base_mask,
                                       source_rgb=worn_rgb, source_mask=worn_mask, edit_rgb=rgb, edit_mask=mask)
        check(f"{name}: hems, no hem refusal",
              (record["worn_hem_c"], record["hem_c"], round(abs(record["hem_c"] - record["worn_hem_c"]), 4),
               record["hem_refused"]), (0.46146, hem, delta, False))


def main() -> int:
    print("[0] the pixel test (hand numbers)")
    px = lambda c: np.array([[c]], np.float32)  # noqa: E731
    near("|D2 - S2|", float(np.abs(px(D2) - np.array(S2, np.float32)).mean()), 16.333, 0.001)
    near("D2 vs S2 scaled", float(gg.shade_distance(px(D2), S2)[0, 0]), 12.751, 0.001)
    near("D2 vs C2 scaled", float(gg.shade_distance(px(D2), C2)[0, 0]), 6.192, 0.001)
    near("R vs S2 scaled", float(gg.shade_distance(px(R), S2)[0, 0]), 1.232, 0.001)
    near("R vs K scaled", float(gg.shade_distance(px(R), K)[0, 0]), 53.333, 0.001)
    check("centre column, y0, Hb", gg._centre_column(mask_of(BASE)), (300, 100, 799))

    print("[1] Ylva's case: the piece in shadow is no skin")
    skin = gg.skin_colour(BASE, mask_of(BASE))
    check("skin sample", tuple(skin), (174.0, 122.0, 98.0))
    ws = gg.worn_skin(WORN_Y, G, skin)
    check("worn_skin: none of G, the base skin outside", (int((ws & G).sum()), int((ws & ~G).sum())), (0, 228000))
    rec = gate(gg, GHOST_Y)
    check("GHOST_Y: hems, ok", (rec["worn_hem_c"], rec["hem_c"], rec["hem_refused"], rec["ok"], rec["reasons"]),
          (0.62453, 0.62453, False, True, []))

    print("[2] a longer or shorter ghost is still refused")
    for name, img, hem, refused in (("GHOST_LONG", GHOST_LONG, 0.67459, True),
                                    ("GHOST_SHORT", GHOST_SHORT, 0.5995, True),
                                    ("GHOST_NEAR", GHOST_NEAR, 0.61202, False)):
        rec = gate(gg, img)
        check(f"{name}: hems, refused by the hem", (rec["worn_hem_c"], rec["hem_c"], rec["hem_refused"],
                                                   bool(hem_reasons(rec))), (0.62453, hem, refused, refused))

    print("[3] lit skin below a black piece stays out (Ruling A17)")
    check("piece colour = K", tuple(gg.piece_colour(WORN_K, G_K)), (40.0, 40.0, 60.0))
    ws = gg.worn_skin(WORN_K, G_K, skin)
    check("worn_skin: the whole patch, none of the piece", (int((ws & PATCH).sum()), int((ws & G).sum())), (6400, 0))
    check("hem without leaving it out", round(gg.centre_hem(G_K, mask_of(BASE)), 5), 0.72466)
    rec = gate(gg, GHOST_K, WORN_K, G_K)
    check("GHOST_K: hems, ok", (rec["worn_hem_c"], rec["hem_c"], rec["hem_refused"]), (0.62453, 0.62453, False))
    rec = gate(gg, GHOST_K_LONG, WORN_K, G_K)
    check("GHOST_K_LONG: refused by the hem", (rec["worn_hem_c"], rec["hem_c"], rec["hem_refused"]),
          (0.62453, 0.72466, True))

    print(f"[4] fails on the old code ({PINNED})")
    old_gg = pinned(PINNED, "garment_gates")
    check("old gate version", old_gg.GHOST_GATE_VERSION, 7)
    rec = gate(old_gg, GHOST_Y)
    check("[1] old: worn hem under the bust, refused", (rec["worn_hem_c"], rec["hem_c"], rec["hem_refused"],
                                                        bool(hem_reasons(rec))), (0.37422, 0.62453, True, True))
    old_k = gate(old_gg, GHOST_K, WORN_K, G_K), gate(old_gg, GHOST_K_LONG, WORN_K, G_K)
    check("[3] old: the same", tuple((r["worn_hem_c"], r["hem_refused"]) for r in old_k),
          ((0.62453, False), (0.62453, True)))

    regate_part()
    fixture_part()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
