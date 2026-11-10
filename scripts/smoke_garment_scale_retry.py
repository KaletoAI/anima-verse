#!/usr/bin/env python3
"""The clothing fit's scale retry (app/core/garment_fit.py: ``widen``, ``too_small``, ``scale_retry``) on a
synthetic body — the REAL ``body_sdf`` / ``push_out`` / ``push_numbers`` / ``gate``, no world, no hub, no GLB.

Usage:
    ./.venv/bin/python scripts/smoke_garment_scale_retry.py

Expected numbers, derived by hand:

[1] widen, centre (x 0.01, z 0.02), half width 0.2, scale 1.04 (y never changes):
    (0.11, 0.5, 0.07):   dx 0.1 inside the half width -> x 0.01 + 1.04 * 0.1 = 0.114, z 0.02 + 1.04 * 0.05 = 0.072
    (0.61, -0.3, 0.02):  dx 0.6 beyond it -> x 0.61 + 0.04 * 0.2 = 0.618 (shifted, not scaled), z 0.02
    (-0.39, 0.0, -0.03): dx -0.4 -> x -0.39 - 0.04 * 0.2 = -0.398, z 0.02 - 1.04 * 0.05 = -0.032
    scale 1.0 -> the same positions.
[2] too_small on the reason strings of ``gate(m, CLOTHING_GATES)``: deep push alone -> True, max push alone -> True,
    deep push + largest component -> False, largest component alone -> False, no reasons -> False.
[3] Body = a capped cylinder of radius r = 0.25 m (256 sides: inradius 0.25 * cos(pi/256) = 0.24998), y -0.6..0.6,
    1 cm rings;
    garment = an open tube of radius rho = 0.2209 m around the same axis, y -0.2..0.2 (k = 1, metres). The tube
    lies inside the body; the push-out carries it radially to r + CLEAR_M = 0.2619, so the push of every vertex is
    0.2619 - rho * s after widening by s (half width 0.3 > rho * 1.08 = 0.2386: the tube is scaled whole):
        s     1.00     1.02     1.04     1.06     1.08
        push  0.0410   0.0366   0.0322   0.0277   0.0233   (m)
    DEEP_PUSH_M = 0.03: every vertex deep up to 1.04 (2.2 mm over), none at 1.06 (2.3 mm under) -> deep share
    1, 1, 1, 0; max push < 0.10. Expected: refused at 1.0, attempts 1.0 / 1.02 / 1.04 refused for
    deep_push_share, 1.06 passes -> factor 1.06, max tried 1.06, finish called twice (1.0 and 1.06: the push-only
    gate skips 1.02 / 1.04). Measured pushes within 1.5 mm of the table.
[4] A fitting tube (rho = 0.26 > r: outside, short of the clearance by 1.9 mm) passes at 1.0 -> factor 1.0, no
    attempts, push and finish called once each.
[5] The case of [3] with the finish also failing largest_component_share at every scale: not too_small -> not
    retried (push once, finish once), factor 1.0, max tried 1.0, the 1.0 reasons returned.
[6] rho = 0.20: push at 1.08 = 0.2619 - 0.216 = 0.0459 > 0.03 -> every step refused by the push gate ->
    the unwidened refusal returned (factor 1.0, deep share 1, max push >= 0.0619 — a 6 cm push overshoots up to
    3 cm on part of the tube: the inside field only starts the push-out), max tried 1.08, 5 attempts, finish
    called once.
[7] The case of [3] with the finish failing rigged_inside_share at 1.06 only: 1.06 refused (finished), 1.08 passes
    -> factor 1.08 (the smallest scale that passes EVERY gate), finish called 3 times.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.core import garment_fit as gf  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got:.5f} (want {want:.5f} +- {tol})")
    if not ok:
        FAILS.append(label)


def cylinder(radius, y0, y1, sides, rings, caps):
    """Vertices + triangles of a cylinder around the y axis, closed by two caps of concentric rings when ``caps``
    (``body_sdf`` samples 5 x 5 points per triangle: triangles stay ~1 cm so the voxelised wall has no gaps)."""
    a = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    ys = np.linspace(y0, y1, rings)
    loops = [[(radius, y) for y in ys]]
    if caps:
        radii = np.linspace(radius, 0, int(round(radius / 0.01)) + 1)[1:]
        loops = [[(r_, y0) for r_ in radii[::-1]] + [(radius, y) for y in ys] + [(r_, y1) for r_ in radii]]
    profile = loops[0]
    P = np.array([[r_ * math.cos(t), y, r_ * math.sin(t)] for r_, y in profile for t in a])
    F = []
    for j in range(len(profile) - 1):
        for i in range(sides):
            p, q = j * sides + i, j * sides + (i + 1) % sides
            F += [[p, q, p + sides], [q, q + sides, p + sides]]
    return P, np.array(F, np.int64)


BODY_R = 0.25
BODY_P, BODY_F = cylinder(BODY_R, -0.6, 0.6, 256, 121, caps=True)
R = BODY_R + gf.CLEAR_M


def tube(rho):
    return cylinder(rho, -0.2, 0.2, 128, 21, caps=False)


def run(rho, finish_extra=None):
    """scale_retry on the tube of radius ``rho``; ``finish_extra(scale) -> metrics`` adds metrics to the finish."""
    Q, F = tube(rho)
    calls = {"push": [], "finish": []}

    def push(Qs):
        sdf = gf.body_sdf(BODY_P, BODY_F, vox=gf.VOX_M, bounds=(Qs.min(0) - 0.05, Qs.max(0) + 0.05))
        Qp, disp = gf.push_out(Qs, F, sdf, clear=gf.CLEAR_M)
        numbers = gf.push_numbers(Qs, Qp)
        calls["push"].append(numbers)
        return Qp, disp, numbers

    def finish(Qs, Qp, disp):
        scale = round(float(np.linalg.norm(Qs[:, [0, 2]], axis=1).mean()) / rho, 2)
        m = {**gf.push_numbers(Qs, Qp), "largest_component_share": 1.0, "rigged_inside_share": 0.0}
        m.update((finish_extra or (lambda s: {}))(scale))
        calls["finish"].append(scale)
        ok, reasons = gf.gate(m, gf.CLOTHING_GATES)
        return gf.FitResult(garment=None, metrics=m, ok=ok, reasons=reasons)

    result, info = gf.scale_retry(Q, push, finish, centre_x=0.0, centre_z=0.0, half_width=0.3)
    return result, info, calls


def main() -> int:
    print("[1] widen")
    P = np.array([[0.11, 0.5, 0.07], [0.61, -0.3, 0.02], [-0.39, 0.0, -0.03]])
    W = gf.widen(P, 1.04, centre_x=0.01, centre_z=0.02, half_width=0.2)
    check("widened", np.round(W, 6).tolist(), [[0.114, 0.5, 0.072], [0.618, -0.3, 0.02], [-0.398, 0.0, -0.032]])
    check("scale 1.0 unchanged", gf.widen(P, 1.0, centre_x=0.01, centre_z=0.02, half_width=0.2).tolist(),
          P.tolist())

    print("[2] too_small")
    base = {"max_push_m": 0.05, "deep_push_share": 0.05, "largest_component_share": 0.99, "rigged_inside_share": 0.0}

    def reasons(**over):
        return gf.gate({**base, **over}, gf.CLOTHING_GATES)[1]
    check("deep push", gf.too_small(reasons(deep_push_share=0.133)), True)
    check("max push", gf.too_small(reasons(max_push_m=0.12)), True)
    check("deep push + component", gf.too_small(reasons(deep_push_share=0.133, largest_component_share=0.9)), False)
    check("component", gf.too_small(reasons(largest_component_share=0.9)), False)
    check("none", gf.too_small(reasons()), False)

    print("[3] tube rho 0.2209 inside r 0.25: widened until 1.06")
    result, info, calls = run(0.2209)
    check("ok", result.ok, True)
    check("factor", info["factor"], 1.06)
    check("max tried", info["max_tried"], 1.06)
    check("attempts", [(a["scale"], a["ok"], [r.split(" ")[0] for r in a["reasons"]]) for a in info["attempts"]],
          [(1.0, False, ["deep_push_share"]), (1.02, False, ["deep_push_share"]),
           (1.04, False, ["deep_push_share"]), (1.06, True, [])])
    check("deep shares", [a["deep_push_share"] for a in info["attempts"]], [1.0, 1.0, 1.0, 0.0])
    for scale, numbers in zip((1.0, 1.02, 1.04, 1.06), calls["push"]):
        near(f"push at {scale}", numbers["max_push_m"], R - 0.2209 * scale, 0.0015)
    check("finish calls", calls["finish"], [1.0, 1.06])

    print("[4] fitting tube keeps 1.0")
    result, info, calls = run(0.26)
    check("ok / factor / attempts", (result.ok, info["factor"], info["max_tried"], info["attempts"]),
          (True, 1.0, 1.0, []))
    check("calls", (len(calls["push"]), calls["finish"]), (1, [1.0]))

    print("[5] another gate fails too: not retried")
    result, info, calls = run(0.2209, lambda s: {"largest_component_share": 0.9})
    check("refused / factor / max", (result.ok, info["factor"], info["max_tried"], info["attempts"]),
          (False, 1.0, 1.0, []))
    check("reasons", [r.split(" ")[0] for r in result.reasons], ["deep_push_share", "largest_component_share"])
    check("calls", (len(calls["push"]), calls["finish"]), (1, [1.0]))

    print("[6] too small at every step")
    result, info, calls = run(0.20)
    check("refused / factor / max", (result.ok, info["factor"], info["max_tried"]), (False, 1.0, 1.08))
    check("attempt scales", [a["scale"] for a in info["attempts"]], [1.0, 1.02, 1.04, 1.06, 1.08])
    check("unwidened refusal returned", result.metrics["deep_push_share"], 1.0)
    check("its push >= 0.0619 - 1.5 mm", result.metrics["max_push_m"] >= R - 0.20 - 0.0015, True)
    check("finish calls", calls["finish"], [1.0])

    print("[7] a widened fit refused for another gate: the walk goes on")
    result, info, calls = run(0.2209, lambda s: {"rigged_inside_share": 0.05} if s == 1.06 else {})
    check("ok / factor", (result.ok, info["factor"]), (True, 1.08))
    check("finish calls", calls["finish"], [1.0, 1.06, 1.08])
    check("1.06 refused for", [r.split(" ")[0] for r in info["attempts"][3]["reasons"]], ["rigged_inside_share"])

    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
