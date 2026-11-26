#!/usr/bin/env python3
"""INSOLE_VERSION 10: a closed shaft tube gives a boot its collar when a sole WIDER than the shaft keeps the shaft's
walls out of the topline (``footwear_insole._shaft_block``, module docstring "Platform soles"; Ylva's Black Platform
Boots, 2026-11-25: collar 3.5 cm, class ``none``, no boot split, the fit refused).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_platform_collar.py

Pure numpy on the synthetic shoes of ``_footwear_fixtures`` — no storage, no world, no hub, no server.

Fixtures (mesher coordinates, Y up, x heel -> toe; length L = 0.26 so k = NOMINAL_LENGTH_M / L = 1.0):
    boot      ``fx.flat_boot()``: the flat clog (insole TOP = 0.01) whose side walls at |z| = 0.04 rise to 0.16 over
              x in [0, 0.10], closed by a back wall at x = 0 and a front wall at x = 0.10 — a tube 0.10 x 0.08.
    platform  the boot plus a welt over x in [0, 0.10] on both sides: an up-facing strip at y = 0.01 (the insole's
              height) from |z| = 0.04 out to 0.06, its outer face from 0 to 0.01 and its underside at y = 0.
    clog      ``fx.clog()``: the low closed clog (walls 0.035 / 0.04, no shaft).

Expected, derived by hand:

[1] boot: the topline keeps per side the cut points at |z| >= 0.75 x 0.04 = 0.03, i.e. the walls; behind the throat
    their top is the tube's 0.16; heel seat = the insole at HEEL_SEAT_M / k = 0.04 = TOP 0.01 -> topline collar
    0.15. Slabs from max(seat + 0.07, vamp top 0.04) = 0.08 up to 0.16 every 0.01 L = 0.0026:
    floor((0.16 - 0.08) / 0.0026) + 1 = 31, every one the tube's closed ring -> top_raw 0.16, closed_share 1.0;
    ring collar 0.16 - 0.01 = 0.15, not above the topline's -> ``collar_source`` "topline", collar 0.15 (class
    ``ankle``: 0.07 < 0.15 <= 0.22), ``shaft_h_raw`` = the topline's highest point 0.16. Gates ok.
[2] platform: at the shaft's stations each side's widest cut point is the welt's 0.06; 0.75 x 0.06 = 0.045 > the wall's
    0.04, so only the welt survives the filter and the topline there is its top, 0.01. In front of x = 0.10 the clog's
    walls (0.035, rising to 0.04 into the throat at 0.1825) are the topline; the highest behind the throat is the last
    station before it, x = 0.1817 on the wall quad 0.18 .. 0.1825 (0.035 -> 0.04): 0.035 + 0.005 x 0.0017 / 0.0025
    = 0.0384 -> collar 0.0284 under the old rule (class ``none``, ``shaft_h_raw`` 0.04 = the clog's W_HI).
    The slabs do not read the topline: the same 31 closed rings, top_raw 0.16, closed_share 1.0 >= 0.9 (the shaft
    gate), ring collar 0.15 > 0.0284 -> ``collar_source`` "slab_ring", collar 0.15, class ``ankle``, ``shaft_h_raw``
    0.16 (the ring's top) — what [1] reads on the same tube. Gates ok (the welt's top at the insole height is tracked
    as insole).
[3] clog: no slab reaches the floor (walls 0.04 < 0.08) -> top_raw None -> ``collar_source`` "topline", class
    ``none``.
[4] Fails on the old code (commit 9c73e57cf, ``git show``): the platform reads class ``none``, collar_h_raw 0.0284,
    shaft_h_raw 0.04 — the fit's boot test (``shaft_h_m`` > the ankle split + margin) never sees the 0.16 shaft.
"""
import subprocess
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _footwear_fixtures as fx  # noqa: E402
from app.core import footwear_insole as fi  # noqa: E402

OLD = "9c73e57cf"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'BAD'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'ok ' if ok else 'BAD'} {label}: {got!r}" + ("" if ok else f" (want {want} +- {tol})"))
    if not ok:
        FAILS.append(label)


def platform(P, F, out=0.06, top=0.01, x1=0.10):
    """The boot plus a welt over x in [0, x1] on both sides (module docstring)."""
    P, F = list(P), [tuple(f) for f in F]

    def quad(a, b, c, d, facing):
        for tri in ((a, b, c), (a, c, d)):
            t = [np.asarray(v, np.float64) for v in tri]
            if np.dot(np.cross(t[1] - t[0], t[2] - t[0]), facing) < 0:
                t = [t[0], t[2], t[1]]
            base = len(P)
            P.extend(t)
            F.append((base, base + 1, base + 2))

    xs = np.round(np.arange(0.0, x1 + 1e-9, 0.0025), 10)
    for s in (1.0, -1.0):
        for a, b in zip(xs[:-1], xs[1:]):
            quad((a, top, s * fx.HALF_W), (b, top, s * fx.HALF_W), (b, top, s * out), (a, top, s * out), (0, 1, 0))
            quad((a, 0, s * out), (b, 0, s * out), (b, top, s * out), (a, top, s * out), (0, 0, s))
            quad((a, 0, s * fx.HALF_W), (b, 0, s * fx.HALF_W), (b, 0, s * out), (a, 0, s * out), (0, -1, 0))
    return np.asarray(P, np.float64), np.asarray(F, np.int64)


def main() -> int:
    check("version >= 10", fi.INSOLE_VERSION >= 10, True)
    boot = fx.flat_boot()
    plat = platform(*boot)

    print("[1] boot")
    r = fi.analyse_arrays(*boot)
    s = r["shaft"]
    near("k", r["nominal"]["k"], 1.0, 1e-9)
    near("heel seat", r["nominal"]["heel_seat_h_m"], 0.01, 1e-6)
    check("slabs", len(s["slabs"]), 31)
    near("top_raw", s["top_raw"], 0.16, 1e-9)
    check("closed_share", s["closed_share"], 1.0)
    check("collar_source", s["collar_source"], "topline")
    near("collar", s["collar_h_raw"], 0.15, 1e-6)
    check("class", s["class"], "ankle")
    near("shaft_h_raw", r["shaft_h_raw"], 0.16, 1e-9)
    check("gates ok", r["gates"]["ok"], True)

    print("[2] platform")
    r = fi.analyse_arrays(*plat)
    s = r["shaft"]
    gx = np.linspace(0.0, r["length_raw"], fi.STATIONS)
    top = fi.topline_stations(fi.shoe_frame(*plat).to_frame(plat[0]), plat[1], gx)[0]
    near("topline at x = 0.05", float(top[int(round(0.05 / 0.26 * (fi.STATIONS - 1)))]), 0.01, 1e-9)
    check("slabs", len(s["slabs"]), 31)
    near("top_raw", s["top_raw"], 0.16, 1e-9)
    check("closed_share", s["closed_share"], 1.0)
    check("collar_source", s["collar_source"], "slab_ring")
    near("collar", s["collar_h_raw"], 0.15, 1e-6)
    check("class", s["class"], "ankle")
    near("shaft_h_raw", r["shaft_h_raw"], 0.16, 1e-9)
    check("gates ok", r["gates"]["ok"], True)

    print("[3] clog")
    r = fi.analyse_arrays(*fx.clog())
    check("top_raw", r["shaft"]["top_raw"], None)
    check("collar_source", r["shaft"]["collar_source"], "topline")
    check("class", r["shaft"]["class"], "none")

    print(f"[4] the old code ({OLD})")
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/footwear_insole.py"],
                         capture_output=True, text=True, check=True).stdout
    old = types.ModuleType("footwear_insole_old")
    exec(compile(src, "footwear_insole_old", "exec"), old.__dict__)
    r = old.analyse_arrays(*plat)
    check("old class", r["shaft"]["class"], "none")
    near("old collar", r["shaft"]["collar_h_raw"], 0.0284, 2e-4)
    near("old shaft_h_raw", r["shaft_h_raw"], 0.04, 1e-9)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
