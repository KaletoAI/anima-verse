"""A215: a group that holds copied images whose image step is not done is rendered, not refitted again.

Live case (Kai, the underwear shell piece): the group a88118847d08 held the copies of the source 068fac8f92c4
(``copied_from`` a plain string, garment_images line "copied_from": source_fsig). A190's ``variant_stale``
exempts only the dict form of ``copied_from``, so the copied worn views (made before A190, no ``base_variant``,
the piece now wants "bald") are stale: ``worn`` is the first step not done. ``run_garment`` took the
"refit before re-render" branch for every image step, ``_refit_from_source`` found the group materialized and
fitted the SAME copies again — "refitted from 068fac8f92c4 (made on base634402e5) onto base634402e5" on every
Build, ``worn`` still due afterwards, while ``run_estimate`` said 6 hub jobs and refit False.

Hand-derived truth table of ``refit_before_render(first, edit_chain, materialized)``:
  worn/ghost/cutout, not materialized -> True   (find_source copies a source from another base in, fits it)
  worn/ghost/cutout, materialized     -> False  (the copies are already fitted; their image is not done: render)
  fit, edit chain, materialized       -> True   (Ruling A162: the copies a refused refit kept are fitted again)
  fit, edit chain, not materialized   -> False
  fit, not edit chain, materialized   -> False
  mesh, any                           -> False
Pre-fix proof: the condition at commit e3c0d2171 answers True for (worn, edit chain, materialized) — the loop.

Usage: ./.venv/bin/python scripts/smoke_refit_materialized_render.py
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.garments import refit_before_render  # noqa: E402

fails = []
CASES = [
    (("worn", True, False), True), (("ghost", True, False), True), (("cutout", True, False), True),
    (("worn", True, True), False), (("ghost", True, True), False), (("cutout", True, True), False),
    (("fit", True, True), True), (("fit", True, False), False), (("fit", False, True), False),
    (("mesh", True, True), False), (("mesh", True, False), False),
]
for args, want in CASES:
    got = refit_before_render(*args)
    if got != want:
        fails.append(f"refit_before_render{args} = {got}, want {want}")

# Pre-fix proof: the old inline condition, evaluated for the live case.
OLD = "e3c0d2171"
try:
    src = subprocess.run(["git", "show", f"{OLD}:app/core/garments.py"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    line = next(l for l in src.splitlines() if "if first in gs.IMAGE_STEPS or (first == \"fit\"" in l)
    i = src.splitlines().index(line)
    cond = " ".join(s.strip() for s in src.splitlines()[i:i + 2]).removeprefix("if ").rstrip(":")
    expr = compile(ast.parse(cond, mode="eval"), "old", "eval")

    class GS:
        IMAGE_STEPS = ("worn", "ghost", "cutout")
        EDIT_CHAIN = "edit_chain"
    old = eval(expr, {"gs": GS, "garment_source_materialized": lambda *a: True,
                      "first": "worn", "method": "edit_chain", "character_name": "", "item_id": "", "fsig": ""})
    print(f"pre-fix ({OLD}): worn + materialized refits again = {old}")
    if old is not True:
        fails.append("pre-fix proof: the old condition did not refit the materialized group")
except (subprocess.CalledProcessError, StopIteration) as e:
    print(f"pre-fix proof skipped: {e!r}")

for f in fails:
    print("FAIL", f)
print("OK" if not fails else f"{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
