"""Smoke: Ruling A118 / A216 — the item-wide accessory description (``app/core/accessory_spec.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_spec.py   (no server, no world; pure functions)

Expected values, derived by hand from spec § 5 and plan Task 3:

[1] ``normalize({"kind": "necklace"})`` fills the defaults: chain drop 4.0 cm, thickness 1.5 mm, style cable; metal
    gold; side both; sway off; pendant None; no buckle key (only a belt has one); band {height 0, width 4, auto,
    from_image}.
[2] Clamping to RANGES: drop 50 → 30.0 (max), drop -2 → 0.0, thickness 0.1 → 0.5, thickness "x" → 1.5 (the
    default), NaN → 1.5; style "zigzag" → cable; metal "platinum" → gold.
[3] An unknown or missing kind raises ValueError; ``of_item`` returns None for it (never raises).
[4] ``suggest_kind``: "Goldene Halskette" (slot neck) → necklace ("halskette"); "Copper Belt" (slot waist) → belt;
    "Silk Scarf" (slot neck) → None (no word); "Ring Scarf" on slot neck → None ("ring" matches the ring kind,
    which a neck-only piece is never proposed); "Leather choker" → choker (first rule).
[5] ``metal_material``: silver → ("#c0c0c0", 0.2, 1.0); custom with color "#112233" → ("#112233", 0.25, 1.0);
    custom without a colour → ("#d4af37", 0.25).
[G1] Part links (plan-anhaenger Task 1; D1 = migrate, so ``from_image`` is gone from the necklace and the belt):
    - ``normalize({"kind": "charm"})["charm"]`` = {size_mm 30.0, mount flat, flip False} (CHARM_DEFAULTS); size 200 →
      120.0 (RANGES["size_mm"] = 3–120); mount "x" → "flat".
    - belt ``buckle {"item": "item_p", "size_mm": 65}`` → {item item_p, size_mm 65.0}; ``{"item": "item_p"}`` →
      {item item_p} (no size: the part's own); ``{"from_image": True, "size_mm": 65}`` → None; ``{"item": "../x"}`` →
      None (safe_item_id refuses it).
    - ``normalize({"kind": "belt"})["buckle"]`` is None — no buckle by default any more.
    - charms: of 8 valid entries the first 6 stay (MAX_CHARMS); at 400 → 40.0 (((400 + 180) % 360) − 180 = 40);
      at "bogus" → "front"; drop_cm 50 → 30.0 (RANGES["drop_cm"] max); mount "x" is left out.
    - a necklace with charms carries no ``charms`` key.
    - ``links`` of a belt with buckle + charms [a at left_hip, b at right_hip hang drop 2]: three entries, at_deg
      0.0 / 90.0 / −90.0, drop_cm 0.0 / 0.0 / 2.0, index 0 / 0 / 1.
    - ``image_part_mm`` of a belt with a linked buckle is None.
    - earrings drop: ``pendant`` = {size_mm 18.0} (PENDANT_DEFAULTS) and image_part_mm 18.0; with pendant.size_mm 25 →
      {size_mm 25.0} and 25.0; with {item, size_mm 25, from_image} → {size_mm 25.0}; style stud with size 25 →
      image_part_mm None, the block kept as {size_mm 25.0}.
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
check("[1] no buckle on a necklace", "buckle" in n, False)
check("[1] band", n["band"], {"height_cm": 0.0, "width_cm": 4.0, "layer": "auto", "material": "from_image",
                           "at": "thigh"})

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

check("[5] silver", s.metal_material({"metal": "silver"}), ("#c0c0c0", 0.2, 1.0))
check("[5] custom", s.metal_material({"metal": "custom", "color": "#112233"}), ("#112233", 0.25, 1.0))
check("[5] custom no colour", s.metal_material({"metal": "custom"}), ("#d4af37", 0.25, 1.0))

lin = s.srgb_to_linear("#d4af37")
check("[6] #d4af37", all(abs(a - b) <= 0.001 for a, b in zip(lin, (0.6584, 0.4287, 0.0382))), True)

# --- [G1] part links ------------------------------------------------------------------------------------------------
check("[G1] charm defaults", s.normalize({"kind": "charm"}).get("charm"), {"size_mm": 30.0, "mount": "flat", "flip": False})
check("[G1] charm size clamp", s.normalize({"kind": "charm", "charm": {"size_mm": 200}})["charm"]["size_mm"], 120.0)
check("[G1] charm mount", s.normalize({"kind": "charm", "charm": {"mount": "x"}})["charm"]["mount"], "flat")
check("[G1] charm has no links", [k for k in ("buckle", "pendant", "charms") if k in s.normalize({"kind": "charm"})], [])


def belt(**kw):
    return s.normalize({"kind": "belt", **kw})


check("[G1] buckle link", belt(buckle={"item": "item_p", "size_mm": 65})["buckle"], {"item": "item_p", "size_mm": 65.0})
check("[G1] buckle link no size", belt(buckle={"item": "item_p"})["buckle"], {"item": "item_p"})
check("[G1] buckle from_image gone", belt(buckle={"from_image": True, "size_mm": 65})["buckle"], None)
check("[G1] buckle unsafe id", belt(buckle={"item": "../x"})["buckle"], None)
check("[G1] belt default no buckle", belt()["buckle"], None)
eight = [{"item": f"item_{i}"} for i in range(8)]
ch = belt(charms=eight)["charms"]
check("[G1] max 6 charms", [c["item"] for c in ch], [f"item_{i}" for i in range(6)])
check("[G1] at 400", belt(charms=[{"item": "a", "at": 400}])["charms"][0]["at"], 40.0)
check("[G1] at bogus", belt(charms=[{"item": "a", "at": "bogus"}])["charms"][0]["at"], "front")
check("[G1] drop clamp", belt(charms=[{"item": "a", "drop_cm": 50}])["charms"][0]["drop_cm"], 30.0)
check("[G1] mount dropped", "mount" in belt(charms=[{"item": "a", "mount": "x"}])["charms"][0], False)
check("[G1] necklace no charms", "charms" in s.normalize({"kind": "necklace", "charms": [{"item": "item_p"}]}), False)
lk = s.links(belt(buckle={"item": "p"}, charms=[{"item": "a", "at": "left_hip"},
                                                {"item": "b", "at": "right_hip", "mount": "hang", "drop_cm": 2}]))
check("[G1] links roles", [(x["role"], x["index"], x["item"]) for x in lk],
      [("buckle", 0, "p"), ("charm", 0, "a"), ("charm", 1, "b")])
check("[G1] links at_deg", [x["at_deg"] for x in lk], [0.0, 90.0, -90.0])
check("[G1] links drop_cm", [x["drop_cm"] for x in lk], [0.0, 0.0, 2.0])
check("[G1] image_part_mm linked buckle", s.image_part_mm(belt(buckle={"item": "p"})), None)
ear = s.normalize({"kind": "earrings", "earring": {"style": "drop"}})
check("[G1] earring drop default", (ear["pendant"], s.image_part_mm(ear)), ({"size_mm": 18.0}, 18.0))
ear = s.normalize({"kind": "earrings", "earring": {"style": "drop"}, "pendant": {"size_mm": 25}})
check("[G1] earring drop 25", (ear["pendant"], s.image_part_mm(ear)), ({"size_mm": 25.0}, 25.0))
ear = s.normalize({"kind": "earrings", "earring": {"style": "drop"},
                   "pendant": {"item": "item_p", "size_mm": 25, "from_image": True}})
check("[G1] earring drop no link", ear["pendant"], {"size_mm": 25.0})
ear = s.normalize({"kind": "earrings", "earring": {"style": "stud"}, "pendant": {"size_mm": 25}})
check("[G1] earring stud keeps size", (ear["pendant"], s.image_part_mm(ear)), ({"size_mm": 25.0}, None))

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
