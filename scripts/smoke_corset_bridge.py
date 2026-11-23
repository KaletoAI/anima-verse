"""Corset v9 (owner decision 2026-11-23 on the bridge over the cleavage, ``CORSET_VERSION`` 9): the disc that closes the
front's section between the cups (``garment_template_build.SHELL_CLOSE_M``) has a radius of 3 cm instead of 5, so the
top edge over the cleavage lies closer to the skin. ``_close_section`` / ``_section_dist`` / ``_close_radius`` are
taken out of the build script by ``ast`` and run on an analytic section. No server, no world DB, no Blender. Every
number below is derived by hand.

The section (``_close_section``'s input, anticlockwise round the centre (0, 0)): (0.2, 0), the right cup's top
(s, 0.10 + s), the dip D (0, 0.10), the left cup's top (-s, 0.10 + s), (-0.2, 0), (0, -0.2), s = 0.16 / sqrt 2 =
0.1131371. The two notch edges run 0.16 from D, each 45 degrees off the vertical (a 90-degree notch). Each edge is
sampled at (k + 0.5) / 8 of its length (``SHELL_CLOSE_SAMPLES`` 8), so on both notch edges at 0.01, 0.03, 0.05, ...
from D.

[1] ``SHELL_CLOSE_M`` is 0.03; ``CORSET_VERSION`` is 9.
[2] The disc of radius rho that touches both notch edges touches them rho / tan 45 = rho from D: a sample for rho 0.03
    (k = 1 from D) and for 0.05 (k = 2). Its centre C lies on the vertical through D at 0.10 + rho sqrt 2. A disc
    centred rho off a sample u < rho from D lies u from the other edge (u sin 90) — under rho, dropped; so no disc
    reaches deeper than C's.
    The five dip columns are rays from (0, 0): straight up, 4.5 degrees either side, and through the 0.05 sample on
    either edge, (+-0.0353553, 0.1353553), atan(0.0353553 / 0.1353553) = 14.639 degrees. The bridge gap of a column =
    ``_close_radius`` minus the radius where the ray meets the section.
    Straight up: the section at 0.10, the closed edge at C_y - rho, gap rho (sqrt 2 - 1):
        rho 0.03: 0.0124264 (12.426 mm); rho 0.05: 0.0207107 (20.711 mm).
    4.5 degrees: d = (sin, cos) = (0.0784591, 0.9969173); the edge y = 0.10 + |x| is met at
    t_e = 0.10 / (cos - sin) = 0.10 / 0.9184582 = 0.1088781; the disc's lower arc at
    t = d.C - sqrt((d.C)^2 - |C|^2 + rho^2), d.C = C_y cos:
        rho 0.03: C_y 0.1424264, d.C 0.1419874, (d.C)^2 0.0201604, |C|^2 - rho^2 0.0202853 - 0.0009 = 0.0193853,
                  sqrt(0.0007751) = 0.0278411, t 0.1141462 (x = t sin = 0.00896, inside the arc's 0.02121) ->
                  gap 0.0052681 (5.268 mm);
        rho 0.05: C_y 0.1707107, d.C 0.1701844, (d.C)^2 0.0289627, |C|^2 - rho^2 0.0291421 - 0.0025 = 0.0266421,
                  sqrt(0.0023206) = 0.0481727, t 0.1220118 (x 0.00957, inside 0.03536) -> gap 0.0131337 (13.134 mm).
    14.639 degrees: rho 0.03 — the ray meets the edge at a sample, whose disc's centre lies exactly rho off that
    point: gap 0; rho 0.05 — the ray meets the edge at the touching point itself, where the arc ends: gap 0.
    -> rho 0.03 [0, 5.268, 12.426, 5.268, 0] mm against rho 0.05 [0, 13.134, 20.711, 13.134, 0] mm (to 0.01 mm;
    the bisection halves 2 rho + 0.05 32 times, ~3e-11 m). The middle gap falls with rho itself (-40 %).
[3] Rosi's Red Corset Top (dry run, the live answer replayed, top edge's inner layer to the nearest body point per
    column 4.5 degrees apart, docs/garment-templates.md "Corset v9"): measured, not derived — they are recorded in the
    document, not checked here.
[4] Fails on the old code: at 32056ce9d (v8, ``SHELL_CLOSE_M`` 0.05) [1] fails and the build's own disc gives the 0.05
    gaps [0, 13.134, 20.711, 13.134, 0] (exit 1).

Usage: ./.venv/bin/python scripts/smoke_corset_bridge.py
"""
import ast
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUILD = ROOT / "app" / "blender" / "scripts" / "garment_template_build.py"
GT = ROOT / "app" / "core" / "garment_template.py"
WANT = {"_close_section", "_section_dist", "_close_radius"}
CONSTS = {"SHELL_CLOSE_M", "SHELL_CLOSE_SAMPLES"}

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


def const(path, name):
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    return None


tree = ast.parse(BUILD.read_text(encoding="utf-8"))
nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in WANT)
         or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in n.targets))]
ns = {"math": math, "np": np}
exec(compile(ast.Module(nodes, []), str(BUILD), "exec"), ns)

# [1]
check("[1] SHELL_CLOSE_M 0.03, SHELL_CLOSE_SAMPLES 8", (ns.get("SHELL_CLOSE_M"), ns.get("SHELL_CLOSE_SAMPLES"))
      == (0.03, 8), (ns.get("SHELL_CLOSE_M"), ns.get("SHELL_CLOSE_SAMPLES")))
check("[1] CORSET_VERSION 9", const(GT, "CORSET_VERSION") == 9, const(GT, "CORSET_VERSION"))

# [2]
s = 0.16 / math.sqrt(2)
pts = [(0.2, 0.0), (s, 0.10 + s), (0.0, 0.10), (-s, 0.10 + s), (-0.2, 0.0), (0.0, -0.2)]
angles = [math.atan2(y, x) for x, y in pts]
radii = [math.hypot(x, y) for x, y in pts]
phi_b = math.degrees(math.atan2(0.05 / math.sqrt(2), 0.10 + 0.05 / math.sqrt(2)))
check("[2] the outer columns 14.639 degrees off", round(phi_b, 3) == 14.639, phi_b)
COLS = (-phi_b, -4.5, 0.0, 4.5, phi_b)
WANT_MM = {0.03: [0.0, 5.268, 12.426, 5.268, 0.0], 0.05: [0.0, 13.134, 20.711, 13.134, 0.0]}


def gaps(rho):
    sec = ns["_close_section"](angles, radii, rho)
    out = []
    for phi in COLS:
        p = math.radians(abs(phi))
        body = 0.10 / (math.cos(p) - math.sin(p))
        out.append((ns["_close_radius"](sec, math.pi / 2 - math.radians(phi)) - body) * 1000.0)
    return out


for rho, want in WANT_MM.items():
    got = gaps(rho)
    check(f"[2] rho {rho}: the gaps at the five dip columns {want} mm",
          all(abs(g - w) <= 0.01 for g, w in zip(got, want)), [round(g, 4) for g in got])
now = gaps(ns["SHELL_CLOSE_M"])
check("[2] the build's own disc gives the 0.03 gaps", all(abs(g - w) <= 0.01 for g, w in zip(now, WANT_MM[0.03])),
      [round(g, 4) for g in now])
check("[2] the middle gap falls by 40 %", abs(now[2] / gaps(0.05)[2] - 0.6) < 1e-6, now[2])

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
