#!/usr/bin/env python3
"""Ruling A32 (2026-11-13): the ghost gate's ``skin_left`` counts a ghost
pixel as skin only when it is at least as near the skin as the piece's own
colour IN THE SAME LIGHT, and never on the ghost's own outline
(app/core/garment_gates.py ``piece_colour`` / ``shade_distance`` /
``skin_pixels`` / ``ghost_clothing_gate``, ghost gate version 6;
app/core/garment_clothing.py ``GATE_VERSIONS``; app/core/garment_images.py
``_regate_stored``).

The case (live 2026-11-13): a cream linen blouse, ghost backs that show the
blouse alone, refused "skin left in the image" 0.0151 / 0.0129 — the cream
in shadow (an inner sleeve, the underside of the peplum) lay within 30 of the
thigh skin sample, and the outermost pixel of the matte blends into the
background.

Usage:
    ./.venv/bin/python scripts/smoke_ghost_skin_vs_garment.py
    A32_FIXTURE_DIR=/path ./.venv/bin/python scripts/smoke_ghost_skin_vs_garment.py   # + [6]

A throwaway storage root, synthetic images, the real gates; no world, no
hub, no server. Needs git for [4] (the pinned old code).

Geometry, W 600 x H 1000 on grey 128 (the frame of
smoke_garment_ghost_gate_v2.py): BASE = the base skin, cols [120, 480) rows
[100, 900) -> y0 100, Hb 799; the skin sample (thigh rows 579..627) = the
base colour. The garment region G is handed to the gate as it is: cols
[200, 400) rows [300, 500), area 200 x 200 = 40000. WORN = BASE with G in
the piece colour -> ``piece_colour`` = that colour. At H 1000 the margin is
round(8 x 1000 / 1536) = 5 iterations (a pixel counts from Manhattan
distance 6 to G), the rim round(2 x 1000 / 1536) = 1 iteration (the ghost
pixels with a 4-neighbour outside the ghost). ``shade_distance(p, c)`` =
mean |p - (mean(p) / mean(c)) x c|.

[1] A cream garment on cream-ish skin. Skin S1 (200, 175, 155), cream C1
    (225, 205, 185): mean |ΔRGB| (25 + 30 + 30) / 3 = 28.33 <= 30, so every
    cream pixel is "near the skin". GHOST_1 = G + a wider left sleeve cols
    [185, 200) rows [300, 500), all cream. Beyond the margin: cols 185..194
    (200 - c >= 6) x 200 rows = 2000 px. Old: 2000 / 40000 = 0.05 > 0.005
    -> refused "skin left". New: a cream pixel is 0 from the piece; the
    skin scaled to its brightness: 205 / 176.667 = 1.160377 x S1 =
    (232.075, 203.066, 179.858) -> (7.075 + 1.934 + 5.142) / 3 = 4.717 > 0
    -> not skin, skin_left 0.0, ok (the sleeve stays within 15 px:
    ``outside`` 0.0; w_ratio (399 - 185) / (399 - 200) = 1.075).
[1b] The live colours, the cream in shadow. Skin S2 (174, 122, 98), piece
    C2 (210, 195, 178); GHOST_1B = G in C2 + the same sleeve in the shadow
    D2 (135, 114, 100): |D2 - S2| (39 + 8 + 2) / 3 = 16.33 <= 30 -> old
    0.05 refused. Lit, D2 is 78.33 from C2 ((75 + 81 + 78) / 3) — nearer the
    skin, the plain-RGB comparison fails. In the same light: mean(D2)
    116.333; S2 x 116.333 / 131.333 = (154.127, 108.066, 86.807) ->
    (19.127 + 5.934 + 13.193) / 3 = 12.751; C2 x 116.333 / 194.333 =
    (125.712, 116.732, 106.556) -> (9.288 + 2.732 + 6.556) / 3 = 6.192 <
    12.751 -> not skin, skin_left 0.0, ok.
[2] A dark garment with a real skin patch. Piece K (40, 40, 60), skin S2.
    GHOST_2 = G in K + an arm stub in S2, cols [400, 415) rows [300, 400).
    Beyond: cols 405..414 (c - 399 >= 6) x 100 rows = 1000 px; old 1000 /
    40000 = 0.025. New: S2 is 0 from the skin and (61.429 + 9.429 + 70.857)
    / 3 = 47.238 from K scaled by 131.333 / 46.667 = 2.81429 -> skin; the rim
    takes row 300 (row 299 is background), row 399 and col 414 -> cols
    405..413 x rows 301..398 = 9 x 98 = 882 px -> 882 / 40000 = 0.02205 >
    0.005 -> still refused "skin left in the image: 0.022".
    [2b] A piece in the skin's own hue (a tie counts as skin): piece T =
    (180, 132, 108) = 1.2 x skin S3 (150, 110, 90) (|T - S3| 23.33: within
    30), the same stub in S3 -> 0 to both in the same light -> skin: 882 px,
    0.02205, refused.
[3] A rim only. Skin S2, piece C2; GHOST_3 = GHOST_1's geometry in C2 with
    the sleeve's outline in S2: col 185 (rows 300..499) and rows 300 / 499
    (cols 186..199). Beyond: col 185 200 px + rows 300 / 499 at cols
    186..194 2 x 9 = 18 -> 218 px; old 218 / 40000 = 0.00545 > 0.005 ->
    refused. New: every one of them has a background 4-neighbour (col 184,
    row 299, row 500) -> the rim -> skin_left 0.0, ok.
[4] Fails on the old code (garment_gates.py PINNED at 9ca64d390, ghost gate
    version 5): [1] 0.05, [1b] 0.05, [3] 0.00545 refused "skin left"; [2]
    0.025 refused there too.
[5] Re-judged before any render: GATE_VERSIONS["ghost"] = GHOST_GATE_VERSION
    = 6, a version 5 record is stale, a version 6 one is not.
    ``_regate_stored`` on two stored attempts refused under 5 (attempt 1 =
    GHOST_2, attempt 2 = GHOST_1B): attempt 1 is gated again and still
    refused (regated_from 5), attempt 2 passes and is published as the
    view's final (attempt 2, accepted) — no render (the function never
    renders; ``_drop_later`` is stubbed: it reads the item from the world).
    The re-gate goes through ``garment_clothing.gate``, whose region is
    ``garment_region`` of base and worn: G less the 4 corner pixels the
    opening cuts.
[6] Optional, A32_FIXTURE_DIR: copies of the live case (base_back,
    worn_back, ghost_back.try1 / .try2 registered as the chain registers
    them, each ``<name>.png`` + ``<name>.mask.png``): try1 0.0151 -> 0.00287,
    try2 0.0129 -> 0.00107, both accepted.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_ghost_skin_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_clothing, garment_gates as gg, garment_images as gi  # noqa: E402

PINNED = "9ca64d390"
FAILS = []
W, H = 600, 1000
TMP = Path(_TMP)
S1, C1 = (200, 175, 155), (225, 205, 185)
S2, C2, D2 = (174, 122, 98), (210, 195, 178), (135, 114, 100)
K = (40, 40, 60)
S3, T = (150, 110, 90), (180, 132, 108)


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


REGION = np.zeros((H, W), dtype=bool)
REGION[300:500, 200:400] = True


def base(skin):
    img = canvas()
    img[100:900, 120:480] = skin
    return img


def worn(skin, piece):
    img = base(skin)
    img[REGION] = piece
    return img


def ghost(piece):
    img = canvas()
    img[REGION] = piece
    return img


def sleeve(img, colour):
    img[300:500, 185:200] = colour
    return img


GHOST_1 = sleeve(ghost(C1), C1)
GHOST_1B = sleeve(ghost(C2), D2)
GHOST_2 = ghost(K)
GHOST_2[300:400, 400:415] = S2
GHOST_2B = ghost(T)
GHOST_2B[300:400, 400:415] = S3
GHOST_3 = sleeve(ghost(C2), C2)
GHOST_3[300:500, 185] = S2
GHOST_3[300, 185:200] = S2
GHOST_3[499, 185:200] = S2
CASES = {"1": (S1, C1, GHOST_1), "1b": (S2, C2, GHOST_1B), "2": (S2, K, GHOST_2), "2b": (S3, T, GHOST_2B),
         "3": (S2, C2, GHOST_3)}


def gate(module, case):
    skin, piece, img = CASES[case]
    b = base(skin)
    return module.ghost_clothing_gate(b, mask_of(b), REGION, img, mask_of(img), view="back",
                                      worn_rgb=worn(skin, piece))


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


def skin_reason(record):
    return [r for r in record.get("reasons") or [] if r.startswith("skin left in the image")]


def png(arr, path):
    from PIL import Image
    Image.fromarray(arr).save(path, format="PNG")


def regate_part():
    """[5] (module docstring)."""
    from app.core.garment_store import garment_path, read_record, write_record
    print("[5] re-judged before any render")
    check("GATE_VERSIONS ghost", (garment_clothing.GATE_VERSIONS.get("ghost"), gg.GHOST_GATE_VERSION), (6, 6))
    check("version 5 stale, 6 not",
          (gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 5}),
           gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 6})), (True, False))
    who, item, fsig = "Demo", "item_demo_blouse", "a1b2c3d4e5f6"
    stored = {1: "2", 2: "1b"}
    for n, case in stored.items():
        target = garment_path(who, item, fsig, "image", step="ghost", view="back", attempt=n)
        target.parent.mkdir(parents=True, exist_ok=True)
        png(CASES[case][2], target)
        old = gate(pinned(PINNED, "garment_gates"), case)
        write_record(target.with_suffix(".json"), {
            "garment": {"item_id": item, "fsig": fsig, "step": "ghost", "view": "back", "attempt": n},
            "gate": {**old, "gate_version": 5, "attempt": n}})
    final = garment_path(who, item, fsig, "image", step="ghost", view="back")

    def regate(path, old):
        from PIL import Image
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"))
        case = stored[int(old["attempt"])]
        skin, piece, _img = CASES[case]
        b = base(skin)
        return garment_clothing.gate("ghost", "back", base_rgb=b, base_mask=mask_of(b),
                                     source_rgb=worn(skin, piece), source_mask=mask_of(worn(skin, piece)),
                                     edit_rgb=rgb, edit_mask=mask_of(rgb))

    # garment_clothing.gate derives G with garment_region from base and worn: the rectangle less the 4
    # corner pixels its opening cuts (the worn view differs from the base exactly on G, by more than
    # GARMENT_DRGB for both pieces used: |K - S2| 84.67, |C2 - S2| 63).
    for case in ("2", "1b"):
        skin, piece, _img = CASES[case]
        b, w = base(skin), worn(skin, piece)
        check(f"garment_region = G ({case})", int((gg.garment_region(b, mask_of(b), w, mask_of(w)) ^ REGION).sum()),
              4)
    # Stubbed: dropping the later steps of the view (it reads the item from the world; not under test).
    drop_later, gi._drop_later = gi._drop_later, lambda *a, **k: None
    try:
        hit = gi._regate_stored(who, item, fsig, "ghost", "back", garment_clothing, final=final, regate=regate)
    finally:
        gi._drop_later = drop_later
    check("attempt 2 published", hit == final, True)
    rec = read_record(final.with_suffix(".json"))
    check("final: accepted, attempt 2", (rec.get("accepted"), rec.get("attempt")), (True, 2))
    t1 = read_record(garment_path(who, item, fsig, "image", step="ghost", view="back", attempt=1)
                     .with_suffix(".json")).get("gate") or {}
    check("attempt 1 judged again, still refused for skin",
          (t1.get("ok"), t1.get("regated_from"), t1.get("gate_version"), bool(skin_reason(t1))), (False, 5, 6, True))
    t2 = read_record(garment_path(who, item, fsig, "image", step="ghost", view="back", attempt=2)
                     .with_suffix(".json")).get("gate") or {}
    check("attempt 2 judged again, accepted", (t2.get("ok"), t2.get("regated_from"), t2.get("skin_left")),
          (True, 5, 0.0))


def fixture_part():
    """[6] copies of the live case (module docstring)."""
    folder = os.environ.get("A32_FIXTURE_DIR")
    names = ("base_back", "worn_back", "ghost_back.try1", "ghost_back.try2")
    files = {n: (Path(folder) / f"{n}.png", Path(folder) / f"{n}.mask.png") for n in names} if folder else {}
    if not folder or not all(p.is_file() and m.is_file() for p, m in files.values()):
        print("[6] SKIPPED — no copies of the live case (A32_FIXTURE_DIR)")
        return
    from PIL import Image
    print("[6] copies of the live case")

    def load(name):
        p, m = files[name]
        with Image.open(p) as im, Image.open(m) as mk:
            return np.asarray(im.convert("RGB")), np.asarray(mk.convert("L")) >= 128

    base_rgb, base_mask = load("base_back")
    worn_rgb, worn_mask = load("worn_back")
    for name, old, new in (("ghost_back.try1", 0.01512, 0.00287), ("ghost_back.try2", 0.01292, 0.00107)):
        rgb, mask = load(name)
        record = garment_clothing.gate("ghost", "back", base_rgb=base_rgb, base_mask=base_mask,
                                       source_rgb=worn_rgb, source_mask=worn_mask, edit_rgb=rgb, edit_mask=mask)
        check(f"{name}: {old} -> {new}, accepted", (record["skin_left"], record["ok"]), (new, True))


def main() -> int:
    print("[0] the pixel test (hand numbers)")
    near("cream vs S1 scaled", float(gg.shade_distance(np.array([[C1]], np.float32), S1)[0, 0]), 4.717, 0.001)
    near("D2 vs S2 scaled", float(gg.shade_distance(np.array([[D2]], np.float32), S2)[0, 0]), 12.751, 0.001)
    near("D2 vs C2 scaled", float(gg.shade_distance(np.array([[D2]], np.float32), C2)[0, 0]), 6.192, 0.001)
    near("S2 vs K scaled", float(gg.shade_distance(np.array([[S2]], np.float32), K)[0, 0]), 47.238, 0.001)
    check("piece colour = the worn region's median", tuple(gg.piece_colour(worn(S2, C2), REGION)), (210.0, 195.0, 178.0))
    check("rim iterations at H 1000 / 1024", (gg._iterations(gg.GHOST_RIM, 1000), gg._iterations(gg.GHOST_RIM, 1024)),
          (1, 1))

    new = {case: gate(gg, case) for case in CASES}
    print("[1] a cream garment on cream-ish skin")
    check("[1] skin_left, ok, outside, w_ratio", (new["1"]["skin_left"], new["1"]["ok"], new["1"]["outside"],
                                                new["1"]["w_ratio"]), (0.0, True, 0.0, 1.075))
    check("[1b] the shadowed cream: skin_left, ok", (new["1b"]["skin_left"], new["1b"]["ok"]), (0.0, True))
    print("[2] a dark garment with a real skin patch")
    near("[2] skin_left", new["2"]["skin_left"], 882 / 40000, 1e-5)
    check("[2] refused for skin alone", (new["2"]["ok"], len(new["2"]["reasons"]), bool(skin_reason(new["2"]))),
          (False, 1, True))
    near("[2b] same hue: skin_left", new["2b"]["skin_left"], 882 / 40000, 1e-5)
    check("[2b] refused for skin", bool(skin_reason(new["2b"])), True)
    print("[3] a rim only")
    check("[3] skin_left, ok", (new["3"]["skin_left"], new["3"]["ok"]), (0.0, True))

    print(f"[4] fails on the old code ({PINNED})")
    old_gg = pinned(PINNED, "garment_gates")
    old = {case: gate(old_gg, case) for case in CASES}
    check("old gate version", old_gg.GHOST_GATE_VERSION, 5)
    near("[1] old skin_left", old["1"]["skin_left"], 0.05, 1e-6)
    near("[1b] old skin_left", old["1b"]["skin_left"], 0.05, 1e-6)
    near("[2] old skin_left", old["2"]["skin_left"], 0.025, 1e-6)
    near("[3] old skin_left", old["3"]["skin_left"], 218 / 40000, 1e-6)
    check("[1] / [1b] / [3] refused for skin there",
          tuple(bool(skin_reason(old[c])) for c in ("1", "1b", "3")), (True, True, True))

    regate_part()
    fixture_part()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
