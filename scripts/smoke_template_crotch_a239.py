"""A239 — the crotch of the fitted templates is where the body closes over the centre line, not the lowest
Hips-weighted vertex.

No server, no world DB, no Blender: ``_ray`` / ``_crotch`` and the ``CROTCH_*`` constants are read from
``app/blender/scripts/garment_template_fitted.py`` with ``ast`` and run on numpy points and a stub ray tree.
Usage: ./.venv/bin/python scripts/smoke_template_crotch_a239.py

Before A239 the crotch was the lowest vertex within 3 cm of the centre with Hips weight > 0.3. On a generated
female body the Hips weight reaches several cm down the inner thighs where they stand apart (Kira 0.742 m against
a closing point of 0.819 m), and the briefs' gusset (|x| < 3 cm, from the crotch less 5 mm up) was cut from that
inner-thigh skin: a tongue of cloth hanging between the legs.

Hand-derived expectations (Blender z-up metres, cx = 0, top = 1.0; ``CROTCH_SLIT_M`` 0.005, ``CROTCH_STEP_M``
0.001 -> 11 ray columns in x from -0.005 to 0.005; ``CROTCH_BELOW_M`` 0.03):

[C0] the constants are 0.005 / 0.001 / 0.03.
[C1] thighs apart: Hips-weighted (0.5) inner-thigh vertices at x = +-0.015 down to z 0.74; the body closes over the
     centre at z 0.82 (the stub tree answers every upward ray within |x| < 0.012 with a hit at 0.82). The rule
     height is 0.74, the rays start at 0.74 - 0.03 = 0.71 and hit at 0.82 -> crotch 0.82.
[C2] thighs touching: the same vertices, but the stub answers the upward rays at 0.73 (the thighs meet on the
     centre below the rule's height) -> max(0.74, 0.73) = 0.74, the rule's height (never lower than it).
[C3] a part hanging lower than the closing point (a bulge rigged to the hips at x 0, down to 0.70; the rays hit its
     bottom, 0.70): rule 0.70, rays from 0.67 hit 0.70 -> 0.70 — the part stays covered.
[C4] no ray hits (an open centre): the rule's height, 0.74.
[C5] no Hips-weighted vertex near the centre: top - 0.2 = 0.8 (unchanged fallback).
[C6] the rays: every column x in [-0.005, 0.005] (11 values, step 0.001) is cast straight up (direction (0, 0, 1))
     with reach top - start = 1.0 - 0.71 = 0.29 in C1.
[C7] every region that reads the crotch passes the body tree: briefs, boxers, tights, trousers.
[C8] one edge column grazes an inner thigh (Ylva: x = -0.005 hits 0.790, the other ten columns 0.857..0.859): the
     stub answers x <= -0.0045 at 0.79 and every other column at 0.858 -> the highest per-column lowest hit, 0.858,
     not the thigh's 0.79 (the min over all hits, the first A239 rule, gave 0.79).
[C9] a narrow gap off the centre (Rosi: open only from x -0.001 to +0.007; the columns -0.005..-0.002 hit the right
     inner thigh at 0.715 / 0.724 / 0.733 / 0.749): the stub answers x < -0.0015 at 0.72 and the rest at 0.789 ->
     0.789 (min over all hits: 0.72, i.e. the rule's 0.74 again).
[C10] within one column the lowest hit counts (a column that meets the crotch at 0.82 at one y and the buttock's
     underside at 0.86 at another): the stub answers y > 0.02 at 0.86, the rest at 0.82, in every column -> 0.82.
[V1] ``garment_template.TEMPLATE_VERSION`` is at least 9 (the same parameters drape differently).
"""
import ast
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="a239-"))

from app.core import garment_template as gt  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


SRC = (ROOT / "app/blender/scripts/garment_template_fitted.py").read_text()
tree_ast = ast.parse(SRC)
wanted = {"_ray", "_crotch", "CROTCH_SLIT_M", "CROTCH_STEP_M", "CROTCH_BELOW_M"}
nodes = [n for n in tree_ast.body
         if (isinstance(n, ast.FunctionDef) and n.name in wanted)
         or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in wanted for t in n.targets))]


class Vector(tuple):
    def __new__(cls, v):
        return super().__new__(cls, (float(x) for x in v))

    def normalized(self):
        n = sum(x * x for x in self) ** 0.5
        return Vector(x / n for x in self)


ns = {"np": np, "Vector": Vector}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "fitted", "exec"), ns)


class Tree:
    """Upward rays within |x| < half hit at ``z``; ``None`` = no hit at all."""

    def __init__(self, z, half=0.012):
        self.z, self.half, self.calls = z, half, []

    def ray_cast(self, origin, direction, reach):
        self.calls.append((origin, direction, reach))
        if self.z is None or abs(origin[0]) >= self.half or not origin[2] < self.z <= origin[2] + reach:
            return (None, None, None, None)
        return ((origin[0], origin[1], self.z), (0.0, 0.0, -1.0), 0, self.z - origin[2])


def thighs():
    zs = np.arange(0.74, 0.86, 0.01)
    co = np.array([(s * 0.015, y, z) for s in (1, -1) for y in (-0.03, 0.0, 0.03) for z in zs])
    return co, np.full(len(co), 0.5)


class ColumnTree(Tree):
    """Upward rays answer ``f(x, y)`` (a height, or ``None`` = no hit) within the reach."""

    def __init__(self, f):
        super().__init__(0.0)
        self.f = f

    def ray_cast(self, origin, direction, reach):
        self.calls.append((origin, direction, reach))
        z = self.f(origin[0], origin[1])
        if z is None or not origin[2] < z <= origin[2] + reach:
            return (None, None, None, None)
        return ((origin[0], origin[1], z), (0.0, 0.0, -1.0), 0, z - origin[2])


crotch = ns["_crotch"]
check("C0 constants", (ns["CROTCH_SLIT_M"], ns["CROTCH_STEP_M"], ns["CROTCH_BELOW_M"]) == (0.005, 0.001, 0.03),
      (ns["CROTCH_SLIT_M"], ns["CROTCH_STEP_M"], ns["CROTCH_BELOW_M"]))
co, w = thighs()
t1 = Tree(0.82)
got = crotch(co, w, 0.0, 1.0, t1)
check("C1 thighs apart -> the closing point 0.82", abs(got - 0.82) < 1e-9, got)
xs = sorted({round(o[0], 6) for o, _d, _r in t1.calls})
check("C6 11 columns -0.005..0.005", len(xs) == 11 and abs(xs[0] + 0.005) < 1e-9 and abs(xs[-1] - 0.005) < 1e-9, xs)
check("C6 straight up from 0.71, reach 0.29",
      all(d == (0.0, 0.0, 1.0) and abs(o[2] - 0.71) < 1e-9 and abs(r - 0.29) < 1e-9 for o, d, r in t1.calls))
got = crotch(co, w, 0.0, 1.0, Tree(0.73))
check("C2 thighs touching -> the rule's 0.74", abs(got - 0.74) < 1e-9, got)
bulge = np.array([(0.0, -0.04, z) for z in np.arange(0.70, 0.80, 0.01)])
co3 = np.vstack([co, bulge])
w3 = np.concatenate([w, np.full(len(bulge), 0.6)])
got = crotch(co3, w3, 0.0, 1.0, Tree(0.70))
check("C3 a hanging part stays covered -> 0.70", abs(got - 0.70) < 1e-9, got)
got = crotch(co, w, 0.0, 1.0, Tree(None))
check("C4 no hit -> the rule's 0.74", abs(got - 0.74) < 1e-9, got)
got = crotch(co, np.zeros(len(co)), 0.0, 1.0, Tree(0.82))
check("C5 no Hips weight -> top - 0.2", abs(got - 0.8) < 1e-9, got)
calls = [ln.strip() for ln in SRC.splitlines() if "_crotch(co" in ln and "def " not in ln]
check("C7 four regions pass the tree", len(calls) == 4 and all(c.endswith(", tree)") for c in calls), calls)
got = crotch(co, w, 0.0, 1.0, ColumnTree(lambda x, y: 0.79 if x <= -0.0045 else 0.858))
check("C8 one edge column on a thigh -> the gap's 0.858", abs(got - 0.858) < 1e-9, got)
got = crotch(co, w, 0.0, 1.0, ColumnTree(lambda x, y: 0.72 if x < -0.0015 else 0.789))
check("C9 narrow gap off the centre -> 0.789", abs(got - 0.789) < 1e-9, got)
got = crotch(co, w, 0.0, 1.0, ColumnTree(lambda x, y: 0.86 if y > 0.02 else 0.82))
check("C10 the lowest hit of a column counts -> 0.82", abs(got - 0.82) < 1e-9, got)
check("V1 TEMPLATE_VERSION >= 9", gt.TEMPLATE_VERSION >= 9, gt.TEMPLATE_VERSION)

print("ALL OK" if not FAILED else f"FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
