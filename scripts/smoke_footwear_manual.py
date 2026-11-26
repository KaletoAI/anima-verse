#!/usr/bin/env python3
"""Smoke: the manual shoe adjustment (2026-11-25, "Adjust shoe": ``footwear_fit.manual_matrix``,
``garment_footwear.validate_manual`` / ``fsig_inputs``, the viewer's ``footwearAllowanceModel.ts`` ``manualMap``).

Usage:  ./.venv/bin/python scripts/smoke_footwear_manual.py

No storage, no hub, no server: the synthetic fixtures of ``scripts/_footwear_fixtures.py`` (the wedge pump on the box
feet, left foot at z -0.10, facing +x) and pure functions; the TS mirror is bundled with the worktree's esbuild and
run in node.

Expected, by hand (the cut frame: x forward from the heel end of the sole, y up, z INWARD on both sides):

[M1] manual_matrix: MANUAL_NONE -> identity. offset [10, 20, 30] mm -> translation (0.010, 0.020, -0.030) (outward
     is -z). Toe out 90 deg: x (1,0,0) -> (0,0,-1) (outward), z -> (1,0,0). Toe up 90: x -> (0,1,0). Tilt in 90:
     y (0,1,0) -> (0,0,1) (inward). Size +10 %: the linear part 1.1 x I. Order: T = Translate . Ry(yaw) . Rz(pitch) .
     Rx(roll) . size, so yaw 90 + pitch 90 maps x -> Ry Rz x = Ry (0,1,0) = (0,1,0) and y -> Ry Rz y = Ry (-1,0,0)
     = (0,0,1).
[M2] is_manual: MANUAL_NONE, None, {} -> False; scale_pct 0.1 -> True.
[M3] validate_manual: {"offset_mm": [1.04, -2.06, 0], "rotate_deg": [0, 0, 0.35], "scale_pct": 3.333} ->
     offset [1.0, -2.1, 0.0], rotate [0.0, 0.0, 0.3 or 0.4 (round half even of 0.35 in binary: 0.3)], scale 3.3; a
     missing key is 0; ValueError for: offset 40.1 (> MANUAL_OFFSET_MM 40), rotate -25.1 (> 25), scale -20.1 and 25.1
     (outside (-20, 25)), two numbers, a string, an unknown key, a list instead of an object.
[M4] fsig_inputs (garment_footwear) with current_ssig fixed to "abc123def456": a profile without an adjustment ->
     no "manual" key (the fingerprint of before); a stored MANUAL_NONE -> no key; offset [5, 0, 0] -> "manual" =
     that adjustment (the fit becomes due, a Re-fit on the CPU).
[M5] fit_pair on the wedge pump and the box feet (scripts/smoke_footwear_fit.py: ok, root lift 0.0561392 m):
     - outward 10 mm: every foot vertex of the shod left foot moves by exactly (0, 0, -0.010) m, the right foot's by
       (0, 0, +0.010) (the cut frame's z is the body's horizontal across axis on the unpitched box feet; std 0);
       root lift unchanged (nothing vertical moved); record.scale.manual = the adjustment.
     - up 5 mm: the shoe rises 5 mm on the foot, the figure stands on the shoe again -> root lift 0.0561392 - 0.005
       = 0.0511392 (+-1e-7): the cut frame's +y is the body's +y here (``placed``'s R4 turns about y only).
     - MANUAL_NONE: byte-identical parts and root lift to the call without ``manual``, no scale.manual.
[M6] The TS mirror (``manualMap`` in footwearAllowanceModel.ts, 16 numbers row-major as every map there) equals
     manual_matrix for {offset [12, -7, 3], rotate [10, -5, 4], scale 6} to 1e-12.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(cond: bool, label: str) -> None:
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def adj(offset=(0, 0, 0), rotate=(0, 0, 0), scale=0.0):
    return {"offset_mm": list(offset), "rotate_deg": list(rotate), "scale_pct": scale}


def main() -> int:
    from app.core import footwear_fit as ff
    from app.core import footwear_insole, garment_footwear, glb_mesh

    # [M1]
    check(np.allclose(ff.manual_matrix(ff.MANUAL_NONE), np.eye(4)), "[M1] MANUAL_NONE -> identity")
    T = ff.manual_matrix(adj(offset=(10, 20, 30)))
    check(np.allclose(T[:3, 3], (0.010, 0.020, -0.030)) and np.allclose(T[:3, :3], np.eye(3)),
          "[M1] offset [10, 20, 30] mm -> (0.010, 0.020, -0.030)")
    R = ff.manual_matrix(adj(rotate=(90, 0, 0)))[:3, :3]
    check(np.allclose(R @ (1, 0, 0), (0, 0, -1)) and np.allclose(R @ (0, 0, 1), (1, 0, 0)), "[M1] toe out: x -> -z")
    R = ff.manual_matrix(adj(rotate=(0, 90, 0)))[:3, :3]
    check(np.allclose(R @ (1, 0, 0), (0, 1, 0)), "[M1] toe up: x -> +y")
    R = ff.manual_matrix(adj(rotate=(0, 0, 90)))[:3, :3]
    check(np.allclose(R @ (0, 1, 0), (0, 0, 1)), "[M1] tilt in: y -> +z (inward)")
    check(np.allclose(ff.manual_matrix(adj(scale=10))[:3, :3], 1.1 * np.eye(3)), "[M1] size +10 %")
    R = ff.manual_matrix(adj(rotate=(90, 90, 0)))[:3, :3]
    check(np.allclose(R @ (1, 0, 0), (0, 1, 0)) and np.allclose(R @ (0, 1, 0), (0, 0, 1)),
          "[M1] order Ry . Rz: x -> (0,1,0), y -> (0,0,1)")

    # [M2]
    check([ff.is_manual(ff.MANUAL_NONE), ff.is_manual(None), ff.is_manual({}), ff.is_manual(adj(scale=0.1))]
          == [False, False, False, True], "[M2] is_manual")

    # [M3]
    v = garment_footwear.validate_manual({"offset_mm": [1.04, -2.06, 0], "rotate_deg": [0, 0, 0.35],
                                          "scale_pct": 3.333})
    check(v["offset_mm"] == [1.0, -2.1, 0.0] and v["rotate_deg"][:2] == [0.0, 0.0]
          and v["rotate_deg"][2] in (0.3, 0.4) and v["scale_pct"] == 3.3, f"[M3] rounded to 0.1 ({v})")
    check(garment_footwear.validate_manual({"scale_pct": 2}) == adj(scale=2.0), "[M3] a missing key is 0")
    bad = [{"offset_mm": [40.1, 0, 0]}, {"rotate_deg": [0, -25.1, 0]}, {"scale_pct": -20.1}, {"scale_pct": 25.1},
           {"offset_mm": [1, 2]}, {"offset_mm": "1,2,3"}, {"shift": [0, 0, 0]}, [0, 0, 0]]
    refused = 0
    for b in bad:
        try:
            garment_footwear.validate_manual(b)
        except ValueError:
            refused += 1
    check(refused == len(bad), f"[M3] {refused} / {len(bad)} invalid values refused")

    # [M4]
    item = {"id": "shoe_x"}
    with patch("app.core.footwear_source.current_ssig", lambda iid: "abc123def456"):
        plain = garment_footwear.fsig_inputs("Demo", item, profile={})
        none = garment_footwear.fsig_inputs("Demo", item, profile={garment_footwear.MANUAL_KEY: {
            "shoe_x": dict(ff.MANUAL_NONE)}})
        moved = garment_footwear.fsig_inputs("Demo", item, profile={garment_footwear.MANUAL_KEY: {
            "shoe_x": adj(offset=(5, 0, 0))}})
    check("manual" not in plain and none == plain, "[M4] no adjustment / MANUAL_NONE: the fingerprint of before")
    check(moved.get("manual") == adj(offset=(5.0, 0.0, 0.0)) and {k: v for k, v in moved.items() if k != "manual"}
          == plain, "[M4] an adjustment enters the fingerprint")

    # [M5]
    glb = fx.foot_body_glb()
    body, joints = glb_mesh.body_arrays(glb), glb_mesh.joint_bind_matrices(glb)
    P, F = fx.wedge()
    ins, shoe = footwear_insole.analyse_arrays(P, F), fx.shoe_garment(P, F)
    base = ff.fit_pair(ins, shoe, body, joints)
    lift0 = base.record["root_lift_m"]
    check(base.ok and abs(lift0 - 0.0561392) <= 1e-7, f"[M5] the plain fit: ok, lift {lift0}")
    out = ff.fit_pair(ins, shoe, body, joints, manual=adj(offset=(0, 0, 10)))
    dl = out.parts["left"]["foot"].positions - base.parts["left"]["foot"].positions
    dr = out.parts["right"]["foot"].positions - base.parts["right"]["foot"].positions
    check(out.ok and np.allclose(dl, (0, 0, -0.010), atol=1e-9) and np.allclose(dr, (0, 0, 0.010), atol=1e-9)
          and out.record["root_lift_m"] == lift0 and out.record["scale"].get("manual") == adj(offset=(0.0, 0.0, 10.0)),
          f"[M5] outward 10 mm: left -z, right +z by 0.010 exactly ({dl.mean(0)}, {dr.mean(0)})")
    up = ff.fit_pair(ins, shoe, body, joints, manual=adj(offset=(0, 5, 0)))
    check(up.ok and abs(up.record["root_lift_m"] - (lift0 - 0.005)) <= 1e-7,
          f"[M5] up 5 mm: root lift {up.record['root_lift_m']} = {lift0} - 0.005")
    same = ff.fit_pair(ins, shoe, body, joints, manual=dict(ff.MANUAL_NONE))
    check(np.array_equal(same.parts["left"]["foot"].positions, base.parts["left"]["foot"].positions)
          and same.record["root_lift_m"] == lift0 and "manual" not in same.record["scale"],
          "[M5] MANUAL_NONE: identical to no adjustment")

    # [M6]
    esbuild = ROOT / "node_modules" / ".bin" / "esbuild"
    src = ROOT / "frontend" / "src" / "tabs" / "characters" / "footwearAllowanceModel.ts"
    m = {"offset_mm": [12, -7, 3], "rotate_deg": [10, -5, 4], "scale_pct": 6}
    with tempfile.TemporaryDirectory() as tmp:
        out_js = Path(tmp) / "model.mjs"
        run = subprocess.run([str(esbuild), str(src), "--bundle", "--format=esm", "--platform=node",
                              f"--outfile={out_js}", "--log-level=error"], capture_output=True, text=True)
        if run.returncode:
            check(False, f"[M6] esbuild: {run.stderr[:300]}")
        else:
            script = (f"import {{ manualMap }} from {json.dumps(out_js.as_uri())};"
                      f"console.log(JSON.stringify(manualMap({json.dumps(m)})))")
            node = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True)
            got = np.array(json.loads(node.stdout)).reshape(4, 4) if node.returncode == 0 else None
            check(got is not None and np.allclose(got, ff.manual_matrix(m), atol=1e-12),
                  f"[M6] TS manualMap == manual_matrix ({node.stderr[:200] if node.returncode else ''})")

    print()
    print(f"{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
