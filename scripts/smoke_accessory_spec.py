"""Smoke: Ruling A118 / A216 — the item-wide accessory description (``app/core/accessory_spec.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_spec.py   (no server, no world; pure functions)

Expected values, derived by hand from spec § 5 and plan Task 3:

[1] ``normalize({"kind": "necklace"})`` fills the defaults: chain drop 4.0 cm, thickness 1.5 mm, style cable; metal
    gold; side both; sway off; pendant None; buckle {from_image True, size 50}; band {height 0, width 4, auto,
    from_image}.
[2] Clamping to RANGES: drop 50 → 30.0 (max), drop -2 → 0.0, thickness 0.1 → 0.5, thickness "x" → 1.5 (the
    default), NaN → 1.5; style "zigzag" → cable; metal "platinum" → gold.
[3] An unknown or missing kind raises ValueError; ``of_item`` returns None for it (never raises).
[4] ``suggest_kind``: "Goldene Halskette" (slot neck) → necklace ("halskette"); "Copper Belt" (slot waist) → belt;
    "Silk Scarf" (slot neck) → None (no word); "Ring Scarf" on slot neck → None ("ring" matches the ring kind,
    which a neck-only piece is never proposed); "Leather choker" → choker (first rule).
[5] ``metal_material``: silver → ("#c0c0c0", 0.2); custom with color "#112233" → ("#112233", 0.25);
    custom without a colour → ("#d4af37", 0.25).
[6] ``srgb_to_linear("#d4af37")``: 212/255 = 0.83137 → ((0.83137 + 0.055)/1.055)^2.4 = 0.84017^2.4 = 0.6584;
    175/255 = 0.68627 → 0.70262^2.4 = 0.4287; 55/255 = 0.21569 → 0.25658^2.4 = 0.0382 (each ±0.001).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.core import accessory_spec as s  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


n = s.normalize({"kind": "necklace"})
check("[1] chain", n["chain"], {"drop_cm": 4.0, "thickness_mm": 1.5, "style": "cable"})
check("[1] metal/side/sway/pendant", (n["metal"], n["side"], n["sway"], n["pendant"]), ("gold", "both", "off", None))
check("[1] buckle", n["buckle"], {"from_image": True, "size_mm": 50.0})
check("[1] band", n["band"], {"height_cm": 0.0, "width_cm": 4.0, "layer": "auto", "material": "from_image"})

def chain(**c):
    return s.normalize({"kind": "necklace", "chain": c})["chain"]

check("[2] drop 50", chain(drop_cm=50)["drop_cm"], 30.0)
check("[2] drop -2", chain(drop_cm=-2)["drop_cm"], 0.0)
check("[2] thickness 0.1", chain(thickness_mm=0.1)["thickness_mm"], 0.5)
check("[2] thickness x", chain(thickness_mm="x")["thickness_mm"], 1.5)
check("[2] thickness NaN", chain(thickness_mm=float("nan"))["thickness_mm"], 1.5)
check("[2] style", chain(style="zigzag")["style"], "cable")
check("[2] metal", s.normalize({"kind": "necklace", "metal": "platinum"})["metal"], "gold")

for raw in ({"kind": "tiara"}, {}):
    try:
        s.normalize(raw)
        check(f"[3] {raw} raises", False, True)
    except ValueError:
        check(f"[3] {raw} raises", True, True)
check("[3] of_item unknown", s.of_item({"outfit_piece": {"jewellery": {"kind": "tiara"}}}), None)


def item(name, slots):
    return {"name": name, "outfit_piece": {"slots": slots}}

check("[4] Goldene Halskette", s.suggest_kind(item("Goldene Halskette", ["neck"])), "necklace")
check("[4] Copper Belt", s.suggest_kind(item("Copper Belt", ["waist"])), "belt")
check("[4] Silk Scarf", s.suggest_kind(item("Silk Scarf", ["neck"])), None)
check("[4] Ring Scarf on neck", s.suggest_kind(item("Ring Scarf", ["neck"])), None)
check("[4] Leather choker", s.suggest_kind(item("Leather choker", ["neck"])), "choker")

check("[5] silver", s.metal_material({"metal": "silver"}), ("#c0c0c0", 0.2))
check("[5] custom", s.metal_material({"metal": "custom", "color": "#112233"}), ("#112233", 0.25))
check("[5] custom no colour", s.metal_material({"metal": "custom"}), ("#d4af37", 0.25))

lin = s.srgb_to_linear("#d4af37")
check("[6] #d4af37", all(abs(a - b) <= 0.001 for a, b in zip(lin, (0.6584, 0.4287, 0.0382))), True)

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
