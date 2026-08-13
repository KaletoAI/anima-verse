#!/usr/bin/env python3
"""Smoke run for the FAR BACKDROP — settings, arc resolution, payload block
(Fernkulisse, task 1).

Needs no world and no server: the three getters read ``config._CONFIG``
directly (the ``relief.py`` pattern), and the arc resolution is a pure
function. What it verifies is the SERVER half of § A17 — the renderer half
(the ridge profile) is checked in ``client3d/scripts/smoke_backdrop_math.mjs``.

THE COMPASS, hand-derived. Degrees are this contract's figure compass
(§ A1.8): 0 = South, 90 = East, 180 = North, 270 = West, i.e. a ground
direction of ``(x, z) = (sin a, cos a)`` with x growing east and z growing
south. Check the four cardinals against that formula and nothing else:

    a =   0 -> (0, 1)   = +z = SOUTH
    a =  90 -> (1, 0)   = +x = EAST
    a = 180 -> (0, −1)  = NORTH
    a = 270 -> (−1, 0)  = WEST

so the eight segment centres are S 0, SE 45, E 90, NE 135, N 180, NW 225,
W 270, SW 315 — every diagonal lies halfway between its two cardinals
(NE is halfway from N 180 to E 90 = 135, and (sin 135, cos 135) =
(+0.707, −0.707) really is east-and-north).

Each segment covers 45° CENTRED on its direction, i.e. ±22.5°, and adjacent
selected segments merge. An arc never wraps: ``start`` lies in [0, 360) and
``end`` may run past 360, so a renderer sweeps increasing degrees and needs no
wrap case. Hand-derived expectations:

    "N"        -> N is centred at 180        -> [[157.5, 202.5]]
    "N,S"      -> N as above; S is centred at 0, and 0 − 22.5 = −22.5
                  normalises to 337.5, so the arc runs 337.5 → 382.5
                  -> [[157.5, 202.5], [337.5, 382.5]]  (sorted by start)
    "N,NE,NW"  -> NE 135, N 180, NW 225 are three neighbours in a row, so
                  ONE arc from 135 − 22.5 = 112.5 to 225 + 22.5 = 247.5
                  -> [[112.5, 247.5]]
    full ring  -> all eight (and the empty setting, and an all-junk one) are
                  the single arc [[0, 360]]
    "n , ne"   -> case and blanks do not matter -> [[112.5, 202.5]]

  [1] the compass itself, against the direction formula.
  [2] the arc resolution, the table above plus junk handling.
  [3] the RED COUNTER-PROBE: a mirrored degree convention (the other common
      one, 0 = North growing clockwise) must FAIL against the same table —
      otherwise the table would pass under either reading and prove nothing.
  [4] the three settings: clamps 20..300, seed uint32 with junk -> default,
      the enabled flag, and that all four fields are in the admin schema.
  [5] the payload block: off -> the key is absent, on -> the finished block.

Usage:  ./.venv/bin/python scripts/smoke_backdrop.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import backdrop, config  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def near(label, actual, expected, tol=1e-9):
    check_true(f"{label} = {expected}", abs(actual - expected) <= tol,
               f"{actual}")


def direction(deg):
    """The ground direction of a compass degree, INDEPENDENTLY written down
    (§ B5a: the smoke never trusts the source it verifies): x east, z south."""
    rad = math.radians(deg)
    return round(math.sin(rad), 6), round(math.cos(rad), 6)


def game():
    return config._CONFIG.setdefault("game", {})


def clear():
    for key in ("backdrop_enabled", "backdrop_arc", "backdrop_height_m",
                "backdrop_seed"):
        game().pop(key, None)
    backdrop._warned.clear()


def main() -> int:
    print("\n[1] the compass — 0 = South, 90 = East, 180 = North, 270 = West")
    check("0° points south (+z)", direction(0), (0.0, 1.0))
    check("90° points east (+x)", direction(90), (1.0, 0.0))
    check("180° points north (−z)", direction(180), (0.0, -1.0))
    check("270° points west (−x)", direction(270), (-1.0, 0.0))
    ne_x, ne_z = direction(135)
    check_true("135° is north-EAST (x > 0, z < 0)", ne_x > 0 > ne_z,
               f"({ne_x}, {ne_z})")
    near("...and it is exactly halfway between N 180 and E 90",
         (180 + 90) / 2, 135.0)
    check("the segment order walks the ring in 45° steps",
          backdrop._SEGMENTS,
          ("S", "SE", "E", "NE", "N", "NW", "W", "SW"))
    near("one segment is 45° wide", backdrop._SEGMENT_DEG, 45.0)

    print("\n[2] resolve_arcs — the hand-derived table")
    check("\"N\" -> 180 ± 22.5", backdrop.resolve_arcs("N"),
          [[157.5, 202.5]])
    check("\"N,S\" -> two arcs, the southern one past 360 instead of wrapping",
          backdrop.resolve_arcs("N,S"), [[157.5, 202.5], [337.5, 382.5]])
    check("\"S,N\" is the same, sorted by start",
          backdrop.resolve_arcs("S,N"), [[157.5, 202.5], [337.5, 382.5]])
    check("\"N,NE,NW\" -> ONE merged arc 112.5 → 247.5",
          backdrop.resolve_arcs("N,NE,NW"), [[112.5, 247.5]])
    check("the full ring is one arc",
          backdrop.resolve_arcs("N,NE,E,SE,S,SW,W,NW"), [[0.0, 360.0]])
    check("...and so is an empty setting", backdrop.resolve_arcs(""),
          [[0.0, 360.0]])
    check("...and None", backdrop.resolve_arcs(None), [[0.0, 360.0]])
    check("junk alone reads as the full ring too",
          backdrop.resolve_arcs("up,north-ish,42"), [[0.0, 360.0]])
    check("junk BESIDE a direction is dropped, the direction stands",
          backdrop.resolve_arcs("N,banana"), [[157.5, 202.5]])
    check("case and blanks do not matter",
          backdrop.resolve_arcs(" n , ne "), [[112.5, 202.5]])
    check("a repeated segment is still one segment",
          backdrop.resolve_arcs("N,N,N"), [[157.5, 202.5]])
    check("a run that CROSSES 0 stays one arc (SE,S,SW)",
          backdrop.resolve_arcs("SE,S,SW"), [[292.5, 427.5]])
    for arc in backdrop.resolve_arcs("N,S") + backdrop.resolve_arcs("SE,S,SW"):
        check_true(f"arc {arc} starts inside [0, 360)", 0 <= arc[0] < 360)
        check_true(f"arc {arc} sweeps forward, at most a full turn",
                   arc[0] < arc[1] <= arc[0] + 360)

    print("\n[3] RED COUNTER-PROBE — the mirrored convention must fail")

    def mirrored(word):
        """The OTHER common compass: 0 = North, growing clockwise (N 0, E 90,
        S 180, W 270). The table above must not survive it."""
        centres = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180,
                   "SW": 225, "W": 270, "NW": 315}
        start = (centres[word] - 22.5) % 360.0
        return [[start, start + 45.0]]

    check("mirrored, \"N\" would be [[337.5, 382.5]]", mirrored("N"),
          [[337.5, 382.5]])
    check_true("...which is NOT what resolve_arcs answers",
               mirrored("N") != backdrop.resolve_arcs("N"))
    check_true("...and mirrored \"S\" is not ours either",
               mirrored("S") != backdrop.resolve_arcs("S"))
    check("our \"S\" is the one that runs past 360",
          backdrop.resolve_arcs("S"), [[337.5, 382.5]])
    # The two conventions disagree by 180° on the N/S axis and AGREE on the
    # E/W one (east is 90 either way) — which is exactly why the table above
    # leans on N and S: they are the only cases that can tell them apart.
    check_true("N and S are 180° apart between the two conventions",
               all(abs(((mirrored(w)[0][0] - backdrop.resolve_arcs(w)[0][0])
                        % 360.0) - 180.0) < 1e-9 for w in ("N", "S")))
    check_true("...while E and W coincide, so they prove nothing",
               all(mirrored(w) == backdrop.resolve_arcs(w)
                   for w in ("E", "W")))

    print("\n[4] the world settings (the relief.py getter pattern)")
    clear()
    check("unset -> switched off", backdrop.get_backdrop_enabled(), False)
    near("unset height -> default", backdrop.get_backdrop_height_m(), 120.0)
    check("unset seed -> default", backdrop.get_backdrop_seed(), 1)
    for raw, expected in ((True, True), (False, False), (1, True), (0, False),
                          (None, False), ("yes", False)):
        game()["backdrop_enabled"] = raw
        check(f"enabled {raw!r}", backdrop.get_backdrop_enabled(), expected)
    for raw, expected in ((200, 200.0), (10, 20.0), (999, 300.0), (20, 20.0),
                          (300, 300.0), (0, 120.0), (-5, 120.0),
                          ("high", 120.0), (True, 120.0),
                          (float("nan"), 120.0), (None, 120.0)):
        game()["backdrop_height_m"] = raw
        near(f"height {raw!r}", backdrop.get_backdrop_height_m(), expected)
    for raw, expected in ((7, 7), (0, 0), (4294967295, 4294967295),
                          (4294967296, 0), (-1, 4294967295), ("12", 12),
                          (3.0, 3), (2.5, 1), ("seed", 1), (True, 1),
                          (float("nan"), 1), (None, 1)):
        game()["backdrop_seed"] = raw
        check(f"seed {raw!r}", backdrop.get_backdrop_seed(), expected)
    fields = SECTIONS["game"]["fields"]
    for name in ("backdrop_enabled", "backdrop_arc", "backdrop_height_m",
                 "backdrop_seed"):
        check_true(f"{name} is in the admin schema", name in fields)
    check("the schema default matches the getter's",
          fields["backdrop_height_m"]["default"], backdrop.DEFAULT_HEIGHT_M)
    check("...and so does the seed's", fields["backdrop_seed"]["default"],
          backdrop.DEFAULT_SEED)
    check("...and the enabled flag is off by default",
          fields["backdrop_enabled"]["default"], False)
    check("the schema clamps the height the same way",
          (fields["backdrop_height_m"]["min"],
           fields["backdrop_height_m"]["max"]), (20, 300))

    print("\n[5] the payload block")
    clear()
    check("off -> no block at all", backdrop.get_backdrop(), None)
    game()["backdrop_enabled"] = True
    game()["backdrop_arc"] = "N"
    game()["backdrop_height_m"] = 90
    game()["backdrop_seed"] = 5
    check("on -> the finished block", backdrop.get_backdrop(),
          {"height_m": 90.0, "seed": 5, "arcs": [[157.5, 202.5]]})
    game()["backdrop_arc"] = ""
    check("enabled without a direction is the full ring",
          backdrop.get_backdrop()["arcs"], [[0.0, 360.0]])
    game()["backdrop_enabled"] = False
    check("switching it off takes the block away again",
          backdrop.get_backdrop(), None)
    clear()

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
