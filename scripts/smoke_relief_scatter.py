#!/usr/bin/env python3
"""Smoke check: clone variants and relief wave width.

Usage:  ./.venv/bin/python scripts/smoke_relief_scatter.py

Pure functions, no server, no world.db. Expectations derived BY HAND from the
rules in development_instructions/plan-relief-und-scatter.md, never recorded
from output.

Part 1 — variant_mix. The rule: a clone carries ONE number, mixed into every
stored seed of the location, so all its scattered props and its relief differ
from the template's while staying FIXED for that clone.
    variant 0            -> the stored seed, unchanged (every location that
                            predates this change keeps its exact look)
    same (seed, variant) -> same result, always (a clone does not reshuffle
                            on every load)
    different variants   -> different results for the same stored seed
    different seeds      -> different results for the same variant

Part 2 — relief_cells. The rule: the author sets how WIDE one ground swell is,
in real metres, and the grid count follows from the reference square:
    cells = int(extent_m / wave_m + 0.5), clamped to [2, 22]
    no usable wave    -> TERRAIN_CELLS (16), i.e. exactly today's field
The upper bound is the renderer's, derived by hand at the check below.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.scatter_curves import relief_cells, variant_mix  # noqa: E402

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
    print("Part 2 — relief_cells")
    # The rule: wave_m is how wide ONE ground swell is, in real metres, over a
    # reference square of extent_m. cells = extent / wave, because a cell IS a
    # half-wave's support spacing — 16 cells over an 80 m square is exactly
    # today's 5 m wave, so the default must reproduce the current look.
    check("80 m square, 5 m waves = today's 16 cells",
          relief_cells(5.0, 80.0) == 16)
    check("wider waves mean fewer cells",
          relief_cells(20.0, 80.0) == 4)
    check("a wave as wide as the square is the coarsest useful field",
          relief_cells(80.0, 80.0) == 2)
    check("a wave wider than the square cannot go below 2",
          relief_cells(400.0, 80.0) == 2)
    # The cap is what the RENDERER can draw, not a matter of taste: a plate
    # over the reference square starts at its diagonal e·√2 and drapeGeometry
    # (packages/scene-render/src/terrain.ts) halves it at most MAX_SPLITS = 5
    # times, reaching e·√2 / 32 = e / 22.63. Cell e/22 is still resolved,
    # e/23 is not — so 22, floor of 32/√2, is the finest honest field.
    check("an absurdly fine wave is capped at what the drape can resolve",
          relief_cells(0.01, 80.0) == 22)
    # Both sides of the same rule must round alike: the admin caption tells
    # the author how many swells a setting yields and uses JS Math.round
    # (half-up). 80/32 = 2.5 must be 3 here too — Python's round() would say
    # 2 and the caption would promise a swell the server never builds.
    check("an exact half-cell quotient rounds up, like the caption",
          relief_cells(32.0, 80.0) == 3)
    check("nonsense input falls back to the default",
          relief_cells(0.0, 80.0) == 16 and relief_cells(-3.0, 80.0) == 16
          and relief_cells(5.0, 0.0) == 16)
    check("a location without a stored wave width keeps today's grid",
          relief_cells(None, 80.0) == 16)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
