"""Smoke: A192 — layer stacks, a draped template as a fixed layer, hosiery under the shoe, limb rings of a shell.

Usage: ./.venv/bin/python scripts/smoke_a192_layers_rings.py   (no server; a temp storage dir, no world data)

Hand-derived:

[1] ``garment_set.layer_order`` (slot stacks ``LAYER_STACKS``: underwear_top < top < outer, underwear_bottom < legs <
    bottom < outer). Items: jacket J (own mesh, slots outer, covers underwear_top), T-shirt T (template, slots top),
    jeans B (own mesh, bottom, covers underwear_bottom), briefs U (shell, underwear_bottom), stockings S (shell,
    legs), pumps P (own mesh, feet = footwear, takes no part), painted scarf N (neck, painted: takes no part).
    * J's covers do not name ``top``; the stack does -> J over T. J over B (outer over bottom). B over U (covers AND
      stack) and over S (stack: bottom over legs). S over U (legs over underwear_bottom). T over nothing.
    * under: J = {B, S, T, U} (through B), B = {S, U}, S = {U}; order: every piece after the pieces under it.
    * No cycle (no pair is over each other).
    * Without the stacks (the commit before, e3e56a1ae) J was over nothing: its covers name underwear_top only and
      T, a template, took no part.
[2] ``garment_layers.plan`` with ``fixed`` = T's drape: T gets an entry (fixed, no lsig, not pending); J's ``inner``
    names T with the sha256 of the drape file's bytes (b"drape" -> its sha256) and J is pending (no layered file);
    J's ``without`` is empty although T has no fit record. Without ``fixed``, T is "without" and J has no inner.
[3] ``garment_set.under_footwear``: S (legs) yes; B, U, J no.
[4] ``garment_shell.ring_worn`` — a limb of 10 rings (RING_BIN_M 0.004, y = 0.002 + 0.004 i, the limb's lowest
    point at y = 0 so that every height lies mid-ring), per ring 4 front
    head-on points, 4 back head-on points and 2 side points (one facing front, one facing back):
    * rings 0-5 worn in both views -> both side points worn; rings 8-9 worn in neither -> neither;
    * rings 6-7 worn in the front view only (a top edge that is higher in front) -> the side point facing front is
      worn, the one facing back is not;
    * a point off the limb is never worn; a ring whose views have fewer than RING_MIN_POINTS head-on points is left.
    The median filter over 5 rings leaves these runs (each at least 2 long at the array's end, 6 and 2 inside) as
    they are: front worn 0-7, back worn 0-5.
[5] ``garment_shell.mirror_into`` over [10, 20]: 12 -> 12, 23 -> 17 (3 past the end, mirrored), 31 -> 11
    (11 past: 10 back to the start, 1 forward), 7 -> 13, 10 -> 10, 20 -> 20.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_a192_")
paths.init(TMP)

from app.core import body_slots, garment_layers, garment_set, garment_shell, garment_store  # noqa: E402
from app.models import inventory  # noqa: E402

FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got}" + ("" if ok else f" — expected {want}"))
    if not ok:
        FAILS.append(label)


def piece(name, slots, mode, covers=()):
    return {"id": name, "name": name, "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "covers": list(covers), "partially_covers": [], "mesh_mode": mode}}


ITEMS = {"J": piece("J", ["outer"], "own_mesh", ["underwear_top"]), "T": piece("T", ["top"], "template"),
         "B": piece("B", ["bottom"], "own_mesh", ["underwear_bottom"]), "U": piece("U", ["underwear_bottom"], "shell"),
         "S": piece("S", ["legs"], "shell"), "P": piece("P", ["feet"], "own_mesh"),
         "N": piece("N", ["neck"], "painted")}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(str(item_id))
body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)

# [1]
lo = garment_set.layer_order(list(ITEMS))
check("[1] takes part", sorted(lo["order"]), ["B", "J", "S", "T", "U"])
check("[1] under", {k: v for k, v in lo["under"].items() if v},
      {"J": ["B", "S", "T", "U"], "B": ["S", "U"], "S": ["U"]})
pos = {i: n for n, i in enumerate(lo["order"])}
check("[1] every piece after the pieces under it",
      all(pos[u] < pos[a] for a, under in lo["under"].items() for u in under), True)
check("[1] no cycle", lo["cycles"], [])
check("[1] stack rule", (garment_set._stacked_over({"outer"}, {"top"}), garment_set._stacked_over({"top"}, {"outer"}),
                         garment_set._stacked_over({"top"}, {"bottom"}), garment_set._stacked_over({"bottom"}, {"legs"})),
      (True, False, False, True))

# [2]
drape = Path(TMP) / "drape.glb"
drape.write_bytes(b"drape")
fit = Path(TMP) / "J_aaaaaaaaaaaa.glb"
fit.write_bytes(b"fit")
garment_store.parse_name = lambda p: ("J", "aaaaaaaaaaaa")
garment_store.garment_path = lambda c, item, fsig, what, **k: Path(TMP) / f"{item}_{fsig}_{what}_{k.get('lsig', '')}.glb"
plan = garment_layers.plan("demo", ["J"], base_sha="b" * 64, profile={}, intended=["J", "T"],
                           fits={"J": (fit, {})}, fixed={"T": {"source": drape, "fsig": "tttttttttttt"}})
check("[2] the drape is a fixed layer", (plan["T"].get("fixed"), plan["T"]["lsig"], plan["T"]["pending"]),
      (True, "", False))
check("[2] the jacket lies over it", plan["J"]["inner"], {"T": hashlib.sha256(b"drape").hexdigest()})
check("[2] pending, nothing missing", (plan["J"]["pending"], plan["J"]["without"]), (True, []))
bare = garment_layers.plan("demo", ["J"], base_sha="b" * 64, profile={}, intended=["J", "T"], fits={"J": (fit, {})})
check("[2] without fixed: no inner, the top is missing", (bare["J"]["inner"], bare["J"]["without"], "T" in bare),
      ({}, ["T"], False))

# [3]
check("[3] under the shoe", [garment_set.under_footwear(ITEMS[i]) for i in ("S", "B", "U", "J")],
      [True, False, False, False])

# [4]
rows = []
for i in range(10):
    y = 0.002 + 0.004 * i
    rows += [(y, "f", i <= 7)] * 4 + [(y, "b", i <= 5)] * 4 + [(y, "sf", False), (y, "sb", False)]
rows.append((0.0, "sb", False))            # the limb's lowest point: the rings count from it (0.002 is mid-ring)
y = np.array([r[0] for r in rows])
kind = np.array([r[1] for r in rows])
memb = np.array([r[2] for r in rows])
limb = np.ones(len(rows), bool)
worn = garment_shell.ring_worn(y, limb, kind == "f", memb & (kind == "f"), kind == "b", memb & (kind == "b"),
                               np.isin(kind, ("f", "sf")))
ring = np.floor(y / 0.004).astype(int)
check("[4] side facing front worn in rings", sorted(set(ring[worn & (kind == "sf")].tolist())), list(range(8)))
check("[4] side facing back worn in rings", sorted(set(ring[worn & (kind == "sb")].tolist())), list(range(6)))
off = limb.copy()
off[kind == "sf"] = False
check("[4] off the limb: never", bool(garment_shell.ring_worn(y, off, kind == "f", memb & (kind == "f"), kind == "b",
                                                               memb & (kind == "b"), np.isin(kind, ("f", "sf")))[~off].any()),
      False)
few = (kind == "f") & (np.arange(len(rows)) % 10 < 2)          # 2 head-on points per ring in each view
few_b = (kind == "b") & (np.arange(len(rows)) % 10 < 6)
check("[4] too few head-on points: left", bool(garment_shell.ring_worn(y, limb, few, memb & few, few_b, memb & few_b,
                                                                      np.isin(kind, ("f", "sf"))).any()), False)

# [5]
check("[5] mirror_into", [float(v) for v in garment_shell.mirror_into(np.array([12.0, 23.0, 31.0, 7.0, 10.0, 20.0]),
                                                                      10.0, 20.0)], [12.0, 17.0, 11.0, 13.0, 10.0, 20.0])

print("\nALL OK" if not FAILS else f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
