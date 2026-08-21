#!/usr/bin/env python3
"""Smoke check: clone variants.

Usage:  ./.venv/bin/python scripts/smoke_relief_scatter.py

Pure functions, no server, no world.db. Expectations derived BY HAND from the
rules in development_instructions/plan-relief-und-scatter.md, never recorded
from output.

Part 1 — variant_mix. The rule: a clone carries ONE number, mixed into every
stored seed of the location, so all its scattered props differ from the
template's while staying FIXED for that clone.
    variant 0            -> the stored seed, unchanged (every location that
                            predates this change keeps its exact look)
    same (seed, variant) -> same result, always (a clone does not reshuffle
                            on every load)
    different variants   -> different results for the same stored seed
    different seeds      -> different results for the same variant

PART 2 IS GONE ("Ein Boden" E5a, user decision 1). It measured
``relief_cells``, the resolution of a location's OWN 17 x 17 height field over
its terrain frame. There is no such field any more: local relief is authored as
HEIGHT AREAS of the map, and ``relief_cells`` / ``terrain_grid`` /
``terrain_height`` are deleted from ``scatter_curves`` without a replacement.
What survives of that module is the curve tessellation, the PRNG and the
scatter — and ``variant_mix``, which Part 1 measures.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.scatter_curves import variant_mix  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main():
    print("Part 1 — variant_mix")
    check("no variant leaves the stored seed alone",
          variant_mix(12345, 0) == 12345)
    check("the same pair always gives the same number",
          variant_mix(12345, 777) == variant_mix(12345, 777))
    check("two clones of one template differ",
          variant_mix(12345, 777) != variant_mix(12345, 778))
    check("two seeds of one clone differ",
          variant_mix(12345, 777) != variant_mix(12346, 777))
    check("the result stays a 32-bit unsigned value",
          0 <= variant_mix(0xFFFFFFFF, 0xFFFFFFFF) <= 0xFFFFFFFF)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
