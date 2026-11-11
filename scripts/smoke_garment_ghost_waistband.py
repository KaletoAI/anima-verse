#!/usr/bin/env python3
"""The waistband registration of a bottom's ghost BACK (ruling 13d of the
boots plan): the edit model turned the trousers' ghost back into a centred
product shot (×1.45..1.59 tall), so the ghost back of a piece whose top edge
is a waistband is laid onto the worn back's garment region by ONE uniform
scale (the waistband width) and a shift onto the waistband top, uncapped; the
length is the edit's and does not refuse (app/core/garment_gates.py
``waistband_piece`` / ``register_waistband`` / ``ghost_clothing_gate(
length_free=True)``, app/core/garment_clothing.py ``register_estimate`` /
``gate`` / ``pair_agree`` / ``pair_reason``, app/core/garment_images.py
``_register`` / ``_with_registration``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_ghost_waistband.py

No world, no hub, no server: a throwaway storage root, synthetic images, the
real gates and the real chain glue (``_register`` rewrites an attempt file in
a temp dir). Needs git for [8] (the pinned old code).

Geometry, W 600 x H 1000 on grey 128 (the frame of
smoke_garment_ghost_registration.py):
  BASE  skin (200, 160, 140) cols [120, 480) rows [100, 900): y0 100,
        Hb 899 - 100 = 799. Margin at H 1000: round(8 x 1000 / 1536) = 5.
  P     the trousers, legs apart: hip block cols [240, 360) rows [500, 600)
        + legs cols [200, 260) and [340, 400) rows [600, LEG_END) (LEG_END
        880 worn). WORN = BASE with P in green (40, 90, 50) -> the garment
        region G = P (opening 1 / closing 3 iterations only touch corners;
        the 80 px gap between the legs stays): bbox [200, 500, 399, 879].
  GHOST(shape, s, dy, dx) = grey + ``shape`` in green, scaled by s about
        c = (500, 299.5) (P's top row, hip centre column) and moved by
        (dy, dx): pixel q is green when c + (q − c − (dy, dx)) / s lies in
        the shape (pixel squares).

[1] waistband_piece: bottom / legs / underwear_bottom True; top + bottom,
    outer, feet, nothing False.
[2] register_waistband(G, GHOST(P, 1.5, −300, +10), Hb 799) by hand:
    region band rows 500 + round(0.01·799 = 7.99) .. 500 + round(31.96) =
    508 .. 532 (in the hip block): span 120 (cols 240..359), centre 299.5.
    Ghost: columns q with the preimage col in [239.5, 359.5): q − 309.5 in
    [−90, 90) -> hip cols 220..399 (span 180, centre 309.5); legs [199.5,
    399.5) -> cols 160..459 (bbox width 300); rows: preimage 500 + (q − 200)
    / 1.5 >= 499.5 -> first row 200, hip rows 200..349, legs end < 879.5 ->
    last row 769. Start scale = (399 − 200 + 1) / (459 − 160 + 1) = 0.6667;
    ghost band 200 + round(0.01·799 / 0.6667 = 11.985) .. 200 + round(47.94)
    = 212 .. 248, inside the hip rows -> span 180 -> scale 120 / 180 =
    0.66667 (the next steps give the same rows). centre [200, 309.5],
    shift_px [500 − 200, 299.5 − 309.5] = [300, −10], waist_px [120, 180],
    length_ratio (769 − 200 + 1)·0.66667 / (879 − 500 + 1) = 380 / 380 =
    1.0, within_caps True (uncapped), not negligible.
[3] The chain glue on that ghost (``_register`` with the clothing hook + the
    clothing gate, view back, an item with slots ["bottom"]):
    before (as rendered): top_dy (200 − 500) / 799 = −0.37547, w_ratio
    (459 − 160) / (399 − 200) = 299 / 199 = 1.503 -> refused.
    after: the file rewritten moved; |top_dy|, |centre_dx| <= 2 / 799,
    |w_ratio − 1| <= 0.02, outside <= 0.01 -> ok; ``registered`` = {scale
    0.66667, dx −10, dy 300, length_ratio 1.0}; no ``reg_scale`` /
    ``reg_shift`` chip keys (their chips show the outline caps);
    ``length_free`` True; the file's mask bbox = G within 2 px.
[4] Longer legs (the length is the edit's): GHOST(P with LEG_END 940, 1.5,
    −300, +10): the ghost legs end at preimage < 939.5 -> row 859, the same
    band -> the same scale; length_ratio (859 − 200 + 1)·0.66667 / 380 =
    440 / 380 = 1.1579. After registration the legs reach row 939: rows 880
    .. 884 lie in the 5 px margin, rows >= 879 + 1 + 5 = 885 are left out
    of ``outside`` (length_free) -> outside <= 0.01, ok; h_ratio
    (939 − 500) / (879 − 500) = 1.158 (± 0.01), reported.
[5] Legs drawn straight (the clone's failure, 2026-11-11: width 0.85 /
    0.844 after registration): GHOST(S, 1.5, −300, +10) with S = the hip
    block + one leg block cols [240, 360) rows [600, 880): the same
    waistband -> scale 0.66667, but after it the bbox is cols 240..359:
    w_ratio (359 − 240) / 199 = 0.598 -> refused "garment width changed";
    the width gate checks the fit.
[6] A top keeps the outline registration: the same 1.5× ghost of P with
    slots ["outer"] -> no ``method``, |shift| 0.375 Hb > 0.04 -> not
    applied ("beyond the correction caps — gated as rendered"), refused
    for top + width, no ``registered``, no ``length_free``.
    Negligible: GHOST(P, 1, 0, 0) on the back -> scale 1.0, shift 0 ->
    not applied, the file untouched, no ``registered``.
[7] Pair check: front hem_t 0.80 against a back hem_t 0.90 (|Δ| 0.10 >
    0.02): disagree / a reason; the same back with ``registered`` ->
    agree / None.
[8] Fails on the old code (garment_gates.py PINNED at f4c5dc6d0d, read with
    ``git show`` into a temp module): no ``register_waistband``; its
    ``register`` on the [2] ghost is not within the caps (|shift| > 0.04 Hb)
    -> the old chain gated it as rendered: refused for top and width; and
    its gate on the exactly registered [4] long-legs ghost counts the legs
    below the region: rows 885 .. 939 x 2 legs x 60 px = 6600 px over the
    region area 12000 + 2·60·280 = 45600 (+ the corners closing fills):
    outside 0.1447 (± 0.005) > 0.05 -> refused.
[9] The FRONT of a bottom (ruling 13f): the [2] ghost on the front view ->
    the same numbers as [3] (the fixture is view-agnostic): method
    "waistband", scale 0.66667, shift_px [300, −10], ok, ``registered``,
    ``length_free``. Fails on the old code: garment_clothing.py PINNED at
    e7bf1124 (``git show`` into a temp module) — its ``register_estimate``
    for the front gives the outline estimate (no ``method``, |shift| 0.375
    Hb > 0.04 -> not within the caps) and its gate is not length_free.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_ghost_waist_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import garment_clothing, garment_gates as gg, garment_images as gi  # noqa: E402

PINNED = "f4c5dc6d0d"
PINNED_FRONT = "e7bf1124"
FAILS = []
W, H = 600, 1000
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
GREEN = (40, 90, 50)
HB = 799
C = (500.0, 299.5)
BOTTOM = {"name": "Smoke Trousers", "outfit_piece": {"slots": ["bottom"]}}
TOP = {"name": "Smoke Jacket", "outfit_piece": {"slots": ["outer"]}}
TMP = Path(_TMP)


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


def box(r, c, c0, c1, r0, r1):
    return (c >= c0 - 0.5) & (c < c1 - 0.5) & (r >= r0 - 0.5) & (r < r1 - 0.5)


def trousers(leg_end=880):
    def shape(r, c):
        return (box(r, c, 240, 360, 500, 600) | box(r, c, 200, 260, 600, leg_end)
                | box(r, c, 340, 400, 600, leg_end))
    return shape


def straight(r, c):
    return box(r, c, 240, 360, 500, 600) | box(r, c, 240, 360, 600, 880)


def mask(shape, s=1.0, dy=0.0, dx=0.0):
    rr, cc = np.mgrid[0:H, 0:W].astype(np.float64)
    return shape(C[0] + (rr - C[0] - dy) / s, C[1] + (cc - C[1] - dx) / s)


def canvas():
    return np.full((H, W, 3), GREY, dtype=np.uint8)


def mask_of(rgb):
    return np.abs(rgb.astype(np.int16) - 128).max(2) > 2


def ghost(shape, s=1.0, dy=0.0, dx=0.0):
    img = canvas()
    img[mask(shape, s, dy, dx)] = GREEN
    return img


BASE = canvas()
BASE[100:900, 120:480] = SKIN
WORN = BASE.copy()
WORN[mask(trousers())] = GREEN
ARGS = {"base_rgb": BASE, "base_mask": mask_of(BASE), "source_rgb": WORN, "source_mask": mask_of(WORN)}
REGION = gg.garment_region(BASE, mask_of(BASE), WORN, mask_of(WORN))


def chain(name, rgb, item, view="back"):
    """``_register`` (with the kind hook) + the clothing gate on an attempt file, as run_edit_step."""
    path = TMP / f"{name}.png"
    Image.fromarray(rgb).save(path)
    ref = garment_clothing.position_reference("ghost", **ARGS)
    args = {**ARGS, "item_id": item}
    er, em, reg = gi._register(garment_clothing, "ghost", view, path, (W, H), ref, gate_args=args,
                               edit_rgb=rgb, edit_mask=mask_of(rgb))
    record = garment_clothing.gate("ghost", view, edit_rgb=er, edit_mask=em, **args)
    if reg is not None:
        record = gi._with_registration(record, reg)
    return path, record


def pinned_gates():
    """garment_gates.py at PINNED as a throwaway module."""
    return pinned(PINNED, "garment_gates")


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


def main() -> int:
    print("[0] fixture")
    check("base zones", gg._zones(mask_of(BASE)), (100, HB))
    check("region bbox", gg._bbox(REGION), [200, 500, 399, 879])

    print("[1] waistband_piece")
    for slots, want in ((["bottom"], True), (["legs"], True), (["underwear_bottom"], True),
                        (["top", "bottom"], False), (["outer"], False), (["feet"], False), ([], False)):
        check(f"{slots}", gg.waistband_piece(slots), want)

    print("[2] register_waistband")
    big = ghost(trousers(), 1.5, -300, 10)
    check("ghost bbox", gg._bbox(mask_of(big)), [160, 200, 459, 769])
    reg = gg.register_waistband(REGION, mask_of(big), body_h=HB)
    check("method", reg["method"], "waistband")
    near("scale", reg["scale"], 120 / 180, 0.0001)
    check("centre", reg["centre"], [200.0, 309.5])
    check("shift_px", reg["shift_px"], [300.0, -10.0])
    check("waist_px", reg["waist_px"], [120.0, 180.0])
    near("length_ratio", reg["length_ratio"], 1.0, 0.0001)
    check("uncapped, not negligible", (reg["within_caps"], reg["negligible"]), (True, False))
    check("empty -> None", gg.register_waistband(np.zeros_like(REGION), mask_of(big), body_h=HB), None)

    print("[3] chain glue: 1.5x, 300 px up, 10 px right")
    rendered = big.copy()
    path, rec = chain("big", big, BOTTOM)
    r = rec.get("registration") or {}
    before = r.get("before") or {}
    check("before", (before.get("top_dy"), before.get("w_ratio"), before.get("ok")), (-0.37547, 1.503, False))
    check("accepted after registration", (rec["ok"], rec["reasons"]), (True, []))
    check("applied", (r.get("method"), r.get("applied")), ("waistband", True))
    near("top_dy", rec["top_dy"], 0.0, 2 / HB)
    near("centre_dx", rec["centre_dx"], 0.0, 2 / HB)
    near("w_ratio", rec["w_ratio"], 1.0, 0.02)
    near("outside", rec["outside"], 0.0, 0.01)
    reg_rec = rec.get("registered") or {}
    near("registered scale", reg_rec.get("scale"), 0.66667, 0.0001)
    check("registered dx, dy", (reg_rec.get("dx"), reg_rec.get("dy")), (-10.0, 300.0))
    near("registered length_ratio", reg_rec.get("length_ratio"), 1.0, 0.0001)
    check("no outline chip keys", ("reg_scale" in rec, "reg_shift" in rec), (False, False))
    check("length_free", rec.get("length_free"), True)
    on_disk = np.asarray(Image.open(path).convert("RGB"))
    check("attempt file rewritten", bool(np.array_equal(on_disk, rendered)), False)
    got = gg._bbox(mask_of(on_disk))
    check("file mask bbox ≈ G (± 2 px)", all(abs(a - b) <= 2 for a, b in zip(got, [200, 500, 399, 879])), True)

    print("[4] longer legs: the length is free")
    long_legs = ghost(trousers(940), 1.5, -300, 10)
    reg = gg.register_waistband(REGION, mask_of(long_legs), body_h=HB)
    near("same scale", reg["scale"], 0.66667, 0.0001)
    near("length_ratio", reg["length_ratio"], 440 / 380, 0.0001)
    _, rec = chain("long", long_legs, BOTTOM)
    check("accepted", (rec["ok"], rec["reasons"]), (True, []))
    near("outside", rec["outside"], 0.0, 0.01)
    near("h_ratio reported", rec["h_ratio"], 439 / 379, 0.01)

    print("[5] legs drawn straight: the width gate checks the fit")
    _, rec = chain("straight", ghost(straight, 1.5, -300, 10), BOTTOM)
    near("scale", (rec.get("registered") or {}).get("scale"), 0.66667, 0.0001)
    near("w_ratio", rec["w_ratio"], 119 / 199, 0.01)
    check("refused for its width", (rec["ok"], any("garment width changed" in x for x in rec["reasons"])),
          (False, True))

    print("[6] a top / the front / negligible: the outline registration")
    _, rec = chain("top", big, TOP)
    r = rec.get("registration") or {}
    check("top: outline method, not applied", (r.get("method"), r.get("applied"), r.get("note")),
          (None, False, "beyond the correction caps — gated as rendered"))
    check("top: refused for top + width", (rec["ok"], any("garment top moved" in x for x in rec["reasons"]),
                                          any("garment width changed" in x for x in rec["reasons"])),
          (False, True, True))
    check("top: no registered, not length_free", ("registered" in rec, "length_free" in rec), (False, False))
    exact = ghost(trousers())
    path, rec = chain("exact", exact, BOTTOM)
    r = rec.get("registration") or {}
    check("exact: negligible, not applied", (r.get("scale"), r.get("shift_px"), r.get("applied"), r.get("note")),
          (1.0, [0.0, 0.0], False, "negligible"))
    path2 = TMP / "exact_ref.png"
    Image.fromarray(exact).save(path2)
    check("exact: file untouched", path.read_bytes() == path2.read_bytes(), True)
    check("exact: ok, no registered", (rec["ok"], "registered" in rec), (True, False))

    print("[7] pair check")
    front, back = {"hem_t": 0.80}, {"hem_t": 0.90}
    check("plain back: disagree", garment_clothing.pair_agree(front, back), False)
    check("plain back: a reason", garment_clothing.pair_reason(front, back) is not None, True)
    registered = {**back, "registered": {"scale": 0.66667, "dx": -10.0, "dy": 300.0, "length_ratio": 1.1}}
    check("registered back: agree", garment_clothing.pair_agree(front, registered), True)
    check("registered back: no reason", garment_clothing.pair_reason(front, registered), None)

    print(f"[8] fails on the old code ({PINNED})")
    old = pinned_gates()
    check("no register_waistband", hasattr(old, "register_waistband"), False)
    est = old.register(REGION, mask_of(big), body_h=HB)
    check("old register: not within the caps", est["within_caps"], False)
    g = old.ghost_clothing_gate(BASE, mask_of(BASE), REGION, big, mask_of(big), view="back")
    check("old: refused as rendered for top + width",
          (g["ok"], any("garment top moved" in x for x in g["reasons"]),
           any("garment width changed" in x for x in g["reasons"])), (False, True, True))
    registered_long = ghost(trousers(940))
    g = old.ghost_clothing_gate(BASE, mask_of(BASE), REGION, registered_long, mask_of(registered_long),
                                view="back")
    near("old: outside of the long legs", g["outside"], 6600 / 45600, 0.005)
    check("old: refused for it", (g["ok"], any("more than the garment" in x for x in g["reasons"])), (False, True))

    print("[9] the front of a bottom (ruling 13f)")
    _, rec = chain("front", big.copy(), BOTTOM, view="front")
    r = rec.get("registration") or {}
    check("front: waistband, applied", (r.get("method"), r.get("applied")), ("waistband", True))
    near("front: scale", r.get("scale"), 0.66667, 0.0001)
    check("front: shift_px", r.get("shift_px"), [300.0, -10.0])
    check("front: accepted", (rec["ok"], rec["reasons"]), (True, []))
    check("front: registered + length_free", (bool(rec.get("registered")), rec.get("length_free")), (True, True))
    old_cl = pinned(PINNED_FRONT, "garment_clothing")
    est = old_cl.register_estimate("ghost", "front", REGION, mask_of(big), body_h=HB, item_id=BOTTOM)
    check(f"old ({PINNED_FRONT}) front: outline estimate, beyond the caps",
          (est.get("method"), est["within_caps"]), (None, False))
    g = old_cl.gate("ghost", "front", edit_rgb=big, edit_mask=mask_of(big), item_id=BOTTOM, **ARGS)
    check(f"old ({PINNED_FRONT}) front gate: not length_free, refused", ("length_free" in g, g["ok"]),
          (False, False))

    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
