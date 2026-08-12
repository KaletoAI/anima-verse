#!/usr/bin/env python3
"""Smoke check: a stored exit point becomes a door opening (B4).

Usage:  ./.venv/bin/python scripts/smoke_exit_migration.py

Pure function, no server, no world.db. The migration itself writes rows and is
therefore not smoke-able; its DECISION is, and that is what this checks. Every
expected number below is derived BY HAND from the rule (§ B5a), never recorded
from output.

The rule (plan-betreten-und-tueren.md § 6), in one line: the stored
``layout.exit`` — a point in fractions of the room RECTANGLE — is projected
onto the NEAREST wall edge of the room hull and becomes a door opening there,
unless that edge already carries a walkable one.

Frames. ``layout.x/y/w/d`` are fractions of the location's reference SQUARE, so
a distance in that frame is proportional to real metres — the nearest wall is
therefore measured in ABSOLUTE plate fractions, never in the bbox-local frame
(which stretches u by w and v by d). The hull is the drawn ``outline`` (bbox
fractions, clockwise, y down) or, when absent, the implicit unit square with
the edge indices 0=N, 1=E, 2=S, 3=W. The result carries the edge INDEX, like
the editor writes it.

Standard door: OPENING_DEFAULT in frontend/src/tabs/world/planGeometry.ts —
width_m 1.0, height_m 2.1, sill_m 0, type 'door'. ``to`` stays empty (the
migration does not know where the old exit led).

The cases, each with its hand-derived arithmetic:

  (1) Exit near an edge. Rect x=0 y=0 w=0.5 d=0.4, no outline, exit [0.5,0.05]
      -> absolute (0.25, 0.02). Distances: N 0.02, W 0.25, E 0.25, S 0.38.
      N wins = edge 0, running (0,0)->(0.5,0): at = 0.25/0.5 = 0.5.

  (2) Exit mid-room, the nearest wall wins. Same rect, exit [0.8,0.6]
      -> absolute (0.4, 0.24). Distances: E 0.10, S 0.16, N 0.24, W 0.40.
      E wins = edge 1, running (0.5,0)->(0.5,0.4): at = 0.24/0.4 = 0.6.

  (3) That edge already has a walkable opening -> None. Case (1) plus a door
      on edge 0. A WINDOW is not walkable, and a door on ANOTHER edge is not
      in the way: both still yield the edge-0 door of case (1).

  (4) No hull -> None. A layout without a usable rectangle (x/y/w/d) has no
      geometry at all; letting it through would invent a wall.

  (5) Point outside the rectangle: clamp first, then project. Rect x=0.2 y=0.1
      w=0.4 d=0.4, exit [1.6, 0.7] -> clamped [1.0, 0.7] -> absolute
      (0.2+0.4, 0.1+0.28) = (0.6, 0.38), which lies ON the east wall.
      Edge 1 runs (0.6,0.1)->(0.6,0.5): at = (0.38-0.10)/0.4 = 0.7.

  (6) A polygon hull, not the rectangle. L-shape (6 points, clockwise, y down)
      on rect x=0 y=0 w=1 d=1, so bbox fractions ARE absolute ones:
      [[0,0],[1,0],[1,.5],[.5,.5],[.5,1],[0,1]]. Exit [0.8,0.6] sits in the
      NOTCH, outside the hull. Distances: edge 2 ((1,.5)->(.5,.5)) 0.10,
      edge 1 ((1,0)->(1,.5)) sqrt(.2^2+.1^2)=0.2236, edge 3 ((.5,.5)->(.5,1))
      0.30. Edge 2 wins, and it runs right-to-left: at = (1-0.8)/0.5 = 0.4.

  (7) An edge without space -> None. Chamfered corner
      [[0,0],[.95,0],[1,.05],[1,1],[0,1]] on rect 0/0/1/1, exit [0.96,0.04]
      -> absolute (0.96,0.04). Perpendicular distance to the chamfer
      ((.95,0)->(1,.05), direction (1,1)/sqrt2): |0.01-0.04|/sqrt2 = 0.0212;
      to edge 0 the nearest point is its end (0.95,0): sqrt(.01^2+.04^2) =
      0.0412; to edge 2 the nearest point is its start (1,.05): 0.0412. The
      chamfer wins — but it is sqrt(2)*0.05 = 0.0707 long, and a 1.0 m door in
      a location 8 m across needs 1.0/8 = 0.125. It does not fit; nothing is
      invented on a neighbouring wall.

  (8) The door stays inside its wall. Same rect as (1), exit [0.02,0.02]
      -> absolute (0.01,0.008): N wins (0.008 < 0.01), at = 0.01/0.5 = 0.02,
      but half a door is 0.125/2 = 0.0625 wide = 0.125 of the 0.5-long north
      wall, so the centre is pushed to at = 0.125.

  (9) Anchored plan width. Case (7)'s chamfer DOES fit when the location is
      only 4 m across: 1.0/4 = 0.25 > ... no — it needs to be SMALLER than the
      edge: with plan_width_m = 20 the door is 1.0/20 = 0.05 < 0.0707 and the
      chamfer holds it. at = 0.5 by hand: the foot of the perpendicular from
      (0.96,0.04) onto the chamfer is ((0.01+0.04)/2 = 0.025 along a direction
      of unit length in a 0.0707-long edge) -> 0.025*sqrt(2)/0.0707 = 0.5.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.world import project_exit_to_opening  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def door(op, edge, at):
    """A door on `edge` at `at` with the editor's standard dimensions."""
    return (isinstance(op, dict) and op.get("edge") == edge
            and abs(float(op.get("at", -9)) - at) < 1e-4
            and op.get("type") == "door"
            and abs(float(op.get("width_m", 0)) - 1.0) < 1e-9
            and abs(float(op.get("height_m", 0)) - 2.1) < 1e-9
            and float(op.get("sill_m", 0)) == 0.0
            and not op.get("to"))


RECT = {"x": 0.0, "y": 0.0, "w": 0.5, "d": 0.4}
L_SHAPE = [[0, 0], [1, 0], [1, 0.5], [0.5, 0.5], [0.5, 1], [0, 1]]
CHAMFER = [[0, 0], [0.95, 0], [1, 0.05], [1, 1], [0, 1]]


def main():
    print("Part 1 — projection onto the nearest wall")
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05]})
    check("an exit near the north wall lands on edge 0 at 0.5",
          door(op, 0, 0.5), str(op))

    op = project_exit_to_opening({**RECT, "exit": [0.8, 0.6]})
    check("an exit mid-room takes the nearest wall: edge 1 at 0.6",
          door(op, 1, 0.6), str(op))

    op = project_exit_to_opening({"x": 0.2, "y": 0.1, "w": 0.4, "d": 0.4,
                                  "exit": [1.6, 0.7]})
    check("a point outside the rectangle is clamped, then projected: "
          "edge 1 at 0.7", door(op, 1, 0.7), str(op))

    op = project_exit_to_opening({"x": 0, "y": 0, "w": 1, "d": 1,
                                  "outline": L_SHAPE, "exit": [0.8, 0.6]})
    check("a polygon hull wins over the rectangle: edge 2 at 0.4",
          door(op, 2, 0.4), str(op))

    op = project_exit_to_opening({**RECT, "exit": [0.02, 0.02]})
    check("a door near a corner is pushed in until it fits: at 0.125",
          door(op, 0, 0.125), str(op))

    print("Part 2 — when nothing is created")
    existing = [{"edge": 0, "at": 0.2, "type": "door",
                 "width_m": 1.0, "height_m": 2.1}]
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05],
                                  "openings": existing})
    check("a door already on that wall -> no second one", op is None, str(op))

    passage = [{"edge": 0, "at": 0.2, "type": "passage",
                "width_m": 1.6, "height_m": 2.1}]
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05],
                                  "openings": passage})
    check("a passage counts as walkable just the same",
          op is None, str(op))

    window = [{"edge": 0, "at": 0.2, "type": "window",
               "width_m": 1.2, "height_m": 1.2, "sill_m": 0.9}]
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05],
                                  "openings": window})
    check("a window is no way out — the door is still created",
          door(op, 0, 0.5), str(op))

    elsewhere = [{"edge": 2, "at": 0.5, "type": "door",
                  "width_m": 1.0, "height_m": 2.1}]
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05],
                                  "openings": elsewhere})
    check("a door on another wall is not in the way",
          door(op, 0, 0.5), str(op))

    # Letter edges are the legacy vocabulary: 'N' IS edge 0.
    letters = [{"edge": "N", "at": 0.2, "type": "door",
                "width_m": 1.0, "height_m": 2.1}]
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05],
                                  "openings": letters})
    check("a legacy letter edge blocks the same wall", op is None, str(op))

    op = project_exit_to_opening({"exit": [0.5, 0.5]})
    check("a room without a hull yields nothing", op is None, str(op))

    op = project_exit_to_opening({**RECT})
    check("a room without an exit yields nothing", op is None, str(op))

    op = project_exit_to_opening({"x": 0, "y": 0, "w": 1, "d": 1,
                                  "outline": CHAMFER, "exit": [0.96, 0.04]})
    check("a wall too short for a door yields nothing", op is None, str(op))

    print("Part 3 — the plan width decides what fits")
    op = project_exit_to_opening({"x": 0, "y": 0, "w": 1, "d": 1,
                                  "outline": CHAMFER, "exit": [0.96, 0.04]},
                                 plan_width_m=20.0)
    check("the same chamfer holds the door in a 20 m location: edge 1 at 0.5",
          door(op, 1, 0.5), str(op))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
