#!/usr/bin/env python3
"""Smoke: the general footwear rules of 2026-11-25 (part c of the footwear sweep, ``~/claude-out/schuhe-generell``):
shaft by class, the open seed behind the opening, ``deep_outside`` reported only, the strap push limit from the
distribution, Auto length on what is seen (``visible_poke``, and since 2026-11-26 ``skin_seen_mm2``).

Usage:  ./.venv/bin/python scripts/smoke_footwear_general_rules.py

No storage, no world DB, no hub, no server: pure numpy on hand-built arrays; ``footwear_cut.cut_gates`` with its two
measuring helpers replaced by fixed numbers. The old-code proofs read the modules of main ``a72b14754`` (the sweep's
code, ``git show a72b14754:<path>``), never HEAD.

Expected, by hand:

[G1] ``footwear_insole.has_shaft_of(cls, upper)``: "ankle" / "knee" / "overknee" -> True whatever the higher side;
     class "none" -> True only when the higher side > ONE_WALL_SHAFT_M 0.10 m. The sweep's numbers: low shoes' higher
     side 3.7 – 8.8 cm (Kai's sneakers 8.8: a tongue), boots 11.5 – 32 cm; 0.10 lies between. Kai's sneakers ("none",
     0.088) -> False; a lone wall ("none", 0.17, the insole smoke's open-side boot) -> True (still refused);
     ("none", None) -> False. At a72b14754 the bound was 0.07: ("none", 0.088) -> True (the shaft gates read the tongue:
     shaft_closed_share 0.571 < 0.9, refused).
     ``INSOLE_VERSION`` 11 (the analysis changed: every stored insole is measured again, on the CPU).
[G2] ``footwear_insole._seed_open`` on 10 stations x 4 columns x 3 hits; air 0.01, tol 0.02; top = 0.05 at every
     station. Station 2 (behind 0.5 x 10 = 5): columns 0..2 have a candidate at z 0.022 with nothing above (open:
     0.022 <= 0.05 - 0.01, above NaN) -> 3 open cells. Station 7 (under the toe box): all 4 columns have the hollow
     sole's floor at z 0.002 with the next hit 0.045 above it (>= 0.05 - 0.01 = 0.04 -> open) -> 4 open cells.
     New rule: the stations behind 5 have 3 >= SEED_OPEN_MIN 3 open cells -> station 2, its columns 0..2 seeded at
     their hit 0 (z 0.022), column 3: no candidate -> -1. Old rule (a72b14754): the most open cells -> station 7 (the
     floor at 2 mm, Kai's sneakers' defect). With station 2 holding only 2 open cells (< 3) the new rule falls back to
     all stations -> station 7.
[G3] ``footwear_cut.cut_gates`` with ``conform_body`` / ``_side_gates`` replaced: both sides deep_outside 0.546
     (the sweep's fit that looks right), visible_poke 0, throat 0, toe conform 0.003 -> ok True, no reason,
     ``gates.deep_outside`` = {value 0.546, limit 0.02, ok False, gating False}, marks None (a reported gate marks
     nothing). With visible_poke 0.036 on the left (Dario's real hole) -> ok False, one reason
     "visible_poke 0.036 > 0.005 (...)", marks from the visible set only. At a72b14754 the first case refuses
     ("deep_outside 0.546 > 0.02").
[G4] ``footwear_fit.OPEN_GATES["strap_push_max_mm"]`` = ("max", 50.0). The distribution (Braided Leather Sandals on all
     eight bodies): 25.2 – 27.8 mm accepted at 30, 30.85 / 36.47 / 36.73 / 37.42 / 39.44 / 42.2 mm refused at 30 and
     looking right; 42.2 x 1.2 = 50.64 -> 50 (>= every right-looking value, < 50.64). Every listed value passes 50;
     at a72b14754 the limit was 30 and the six refused.
[G5] ``garment_footwear.AUTO_LENGTH_GATES`` = ("visible_poke", "skin_seen_mm2"): Auto adds heel room only for what
     is seen — the foot vertices under the rim outside the shoe (2026-11-25) and the skin seen through the shoe from
     front, back or a side (2026-11-26, ``footwear_cut.SKIN_SEEN_MAX_MM2``: mostly a heel through the counter).
     ``deep_outside`` (reported only) is in neither. At a72b14754 the tuple was ("visible_poke",).
"""
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

OLD = "a72b14754"
FAILS = []


def check(cond: bool, label: str) -> None:
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def old_module(path: str, name: str):
    """The module ``path`` as it was at ``OLD`` (its own imports resolve against today's package)."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True,
                         check=True).stdout
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / path)
    exec(compile(src, f"{OLD}:{path}", "exec"), mod.__dict__)
    return mod


def seed_arrays(heel_open: int):
    nx, nz, K = 10, 4, 3
    hz = np.full((nx, nz, K), np.nan)
    hn = np.zeros((nx, nz, K))
    for j in range(heel_open):
        hz[2, j, 0], hn[2, j, 0] = 0.022, 1.0
    for j in range(nz):
        hz[7, j, 0], hn[7, j, 0] = 0.002, 1.0
        hz[7, j, 1], hn[7, j, 1] = 0.047, -1.0      # the footbed's underside 45 mm above the floor
    above = np.full_like(hz, np.nan)
    above[..., :-1] = hz[..., 1:]
    air = 0.01
    with np.errstate(invalid="ignore"):
        cand = (hn > 0.3) & (np.isnan(above) | (above - hz > air))
    return cand, hz, above, np.full(nx, 0.05), air, 0.02


def main() -> int:
    from app.core import footwear_cut, footwear_fit, footwear_insole, garment_footwear
    old_ins = old_module("app/core/footwear_insole.py", "old_footwear_insole")

    # [G1]
    hs = footwear_insole.has_shaft_of
    check([hs("ankle", None), hs("knee", 0.05), hs("overknee", 0.3), hs("none", None), hs(None, None),
           hs("none", 0.17)] == [True, True, True, False, False, True]
          and footwear_insole.ONE_WALL_SHAFT_M == 0.10, "[G1] class or one wall above 0.10 m")
    check(hs("none", 0.088) is False and old_ins.has_shaft_of("none", 0.088) is True,
          "[G1] Kai's sneakers (none, higher side 8.8 cm): no shaft now; a shaft at a72b14754")
    check(footwear_insole.INSOLE_VERSION >= 11, "[G1] INSOLE_VERSION 11 or later")

    # [G2]
    cand, hz, above, top, air, tol = seed_arrays(3)
    new = footwear_insole._seed_open(cand, hz, above, top, air, tol)
    check(new is not None and new[0] == 2 and list(new[1]) == [0, 0, 0, -1],
          f"[G2] new seed: station 2, columns 0..2 at hit 0 ({new})")
    old = old_ins._seed_open(cand, hz, above, top, air, tol)
    check(old is not None and old[0] == 7, f"[G2] a72b14754: station 7, the hollow sole's floor ({old and old[0]})")
    cand2, hz2, above2, top2, _, _ = seed_arrays(2)
    fb = footwear_insole._seed_open(cand2, hz2, above2, top2, air, tol)
    check(fb is not None and fb[0] == 7, f"[G2] only 2 open cells behind 0.5 L: all stations -> 7 ({fb and fb[0]})")
    check(footwear_insole.SEED_BEHIND_SHARE == 0.5, "[G2] SEED_BEHIND_SHARE 0.5")

    # [G3]
    def run_cut(mod, left_visible: float):
        saved = (mod.conform_body, mod._side_gates)
        cinfo = {k: {"left": 0.0, "right": 0.0} for k in ("toe_conform", "toe_pull", "vslim_share",
                                                          "vslim_floor_stations", "collar_pull", "collar_squeeze")}
        cinfo["toe_conform"] = {"left": 0.003, "right": 0.003}
        mod.conform_body = lambda prim, cut, joints: (prim, cinfo)

        def side(desc, joints, before, after, shoe, body_before, shaft):
            vis = left_visible if desc.get("name") == "left" else 0.0
            return {"deep_outside": 0.546, "visible_poke": vis, "throat_ledge_p95_mm": 0.0,
                    "_marks": {"deep": [0, 1], "visible": [2] if vis else []}}
        mod._side_gates = side
        try:
            prim = types.SimpleNamespace(positions=np.zeros((3, 3)), joints=np.zeros((3, 4), np.int64),
                                         weights=np.zeros((3, 4)), joint_names=["a"])
            cut = {"sides": {"left": {"name": "left"}, "right": {"name": "right"}}}
            parts = {"left": {"foot": object()}, "right": {"foot": object()}}
            return mod.cut_gates(prim, parts, cut, joints={}, body_before=prim)
        finally:
            mod.conform_body, mod._side_gates = saved

    res = run_cut(footwear_cut, 0.0)
    g = res["gates"]["deep_outside"]
    check(res["ok"] is True and res["reasons"] == [] and g["value"] == 0.546 and g["limit"] == 0.02
          and g["ok"] is False and g["gating"] is False and res["marks"] is None,
          f"[G3] deep_outside 0.546 recorded, not refusing ({res['ok']}, {g})")
    res = run_cut(footwear_cut, 0.036)
    check(res["ok"] is False and len(res["reasons"]) == 1 and res["reasons"][0].startswith("visible_poke 0.036 > 0.005")
          and res["marks"] is not None and len(res["marks"]["positions"]) == 1,
          f"[G3] visible_poke 0.036 refuses, marks the visible vertex only ({res['reasons']})")
    check(footwear_cut.REPORTED_ONLY == ("deep_outside",), "[G3] REPORTED_ONLY")
    old_cut = old_module("app/core/footwear_cut.py", "old_footwear_cut")
    res = run_cut(old_cut, 0.0)
    check(res["ok"] is False and any(r.startswith("deep_outside 0.546 > 0.02") for r in res["reasons"]),
          "[G3] a72b14754 refused the right-looking fit at deep_outside 0.546")

    # [G4]
    kind, limit = footwear_fit.OPEN_GATES["strap_push_max_mm"]
    looking_right = [25.2, 27.8, 30.85, 36.47, 36.73, 37.42, 39.44, 42.2]
    check(kind == "max" and limit == 50.0 and max(looking_right) <= limit < max(looking_right) * 1.2,
          f"[G4] strap_push_max_mm ('max', {limit}): >= 42.2, < 42.2 x 1.2 = 50.64")
    old_fit = old_module("app/core/footwear_fit.py", "old_footwear_fit")
    check(old_fit.OPEN_GATES["strap_push_max_mm"] == ("max", 30.0)
          and sum(v > 30.0 for v in looking_right) == 6 and all(v <= limit for v in looking_right),
          "[G4] a72b14754 refused 6 of the 8 right-looking values; 50 accepts all")

    # [G5]
    check(garment_footwear.AUTO_LENGTH_GATES == ("visible_poke", "skin_seen_mm2"),
          "[G5] Auto length answers visible_poke and skin_seen_mm2")
    check("deep_outside" not in garment_footwear.AUTO_LENGTH_GATES, "[G5] deep_outside (reported only) is not in it")

    print()
    print(f"{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
