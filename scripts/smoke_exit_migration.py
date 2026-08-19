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

Frames (contract v6 Nr. 2, the metric wave). ``layout.x/y/w/d`` are METRES in
the location-local frame, and the drawn ``outline`` is metres from the room's
min corner — so the nearest wall is measured in plain local metres and the
door's 1.0 m clear width IS the number compared against an edge length. Only
``layout.exit`` stays what it always was: a fraction of the room RECTANGLE.
That is the one legacy field this one-time migration reads, and a rect
fraction never was a world size.
The hull is the drawn ``outline`` or, when absent, the implicit rectangle with
the edge indices 0=N, 1=E, 2=S, 3=W. The result carries the edge INDEX, like
the editor writes it.

THIS FIXTURE IS THE OLD ONE, CONVERTED. Every case below described the same
geometry as fractions of an 8 m plate; each number is that fraction run once
through the retired mapping (x/y -> (f - 0.5) x 8, w/d and outline points ->
f x 8), so all expected results (edge indices and every ``at``) are the ones
the fraction fixture produced. Only case (9) is re-derived by hand, because
its subject — the plan width deciding what fits — does not exist any more.

Standard door: OPENING_DEFAULT in frontend/src/tabs/world/planGeometry.ts —
width_m 1.0, height_m 2.1, sill_m 0, type 'door'. ``to`` stays empty (the
migration does not know where the old exit led).

The cases, each with its hand-derived arithmetic:

  (1) Exit near an edge. Rect x=-4 y=-4 w=4 d=3.2, no outline, exit [0.5,0.05]
      -> absolute (-2, -3.84). Distances: N 0.16, W 2, E 2, S 3.04.
      N wins = edge 0, running (-4,-4)->(0,-4): at = 2/4 = 0.5.

  (2) Exit mid-room, the nearest wall wins. Same rect, exit [0.8,0.6]
      -> absolute (-0.8, -2.08). Distances: E 0.80, S 1.28, N 1.92, W 3.20.
      E wins = edge 1, running (0,-4)->(0,-0.8): at = 1.92/3.2 = 0.6.

  (3) That edge already has a walkable opening -> None. Case (1) plus a door
      on edge 0. A WINDOW is not walkable, and a door on ANOTHER edge is not
      in the way: both still yield the edge-0 door of case (1).

  (4) No hull -> None. A layout without a usable rectangle (x/y/w/d) has no
      geometry at all; letting it through would invent a wall.

  (5) Point outside the rectangle: clamp first, then project. Rect x=-2.4
      y=-3.2 w=3.2 d=3.2, exit [1.6, 0.7] -> clamped [1.0, 0.7] -> absolute
      (-2.4+3.2, -3.2+2.24) = (0.8, -0.96), which lies ON the east wall.
      Edge 1 runs (0.8,-3.2)->(0.8,0): at = (-0.96+3.2)/3.2 = 0.7.

  (6) A polygon hull, not the rectangle. L-shape (6 points, clockwise, y down)
      on rect x=-4 y=-4 w=8 d=8: [[0,0],[8,0],[8,4],[4,4],[4,8],[0,8]], i.e.
      absolute (-4,-4) (4,-4) (4,0) (0,0) (0,4) (-4,4). Exit [0.8,0.6] ->
      absolute (2.4, 0.8), in the NOTCH, outside the hull. Distances: edge 2
      ((4,0)->(0,0)) 0.80, edge 1 ((4,-4)->(4,0)) 1.60, edge 3 ((0,0)->(0,4))
      2.40. Edge 2 wins, and it runs right-to-left: at = (4-2.4)/4 = 0.4.

  (7) An edge without space -> None. Chamfered corner
      [[0,0],[7.6,0],[8,0.4],[8,8],[0,8]] on rect -4/-4/8/8, exit [0.96,0.04]
      -> absolute (3.68,-3.68). Perpendicular distance to the chamfer
      ((3.6,-4)->(4,-3.6), direction (1,1)/sqrt2): |0.08-0.32|/sqrt2 = 0.1697;
      to edge 0 the nearest point is its end (3.6,-4): sqrt(.08^2+.32^2) =
      0.3298; to edge 2 the nearest point is its start (4,-3.6): 0.3298. The
      chamfer wins — but it is sqrt(2)*0.4 = 0.5657 m long and the door needs
      1.0 m. It does not fit; nothing is invented on a neighbouring wall.

  (8) The door stays inside its wall. Same rect as (1), exit [0.02,0.02]
      -> absolute (-3.92,-3.936): N wins (0.064 < 0.08), at = 0.08/4 = 0.02,
      but half a door is 0.5 m = 0.125 of the 4 m north wall, so the centre is
      pushed to at = 0.125.

  (9) A LONG ENOUGH edge holds the door — the metric successor of the old
      "plan width decides what fits". Chamfer [[0,0],[7,0],[8,1],[8,8],[0,8]]
      on rect -4/-4/8/8, i.e. the chamfer runs (3,-4)->(4,-3), length
      sqrt(2) = 1.4142 m > 1.0 m. Exit [0.95,0.05] -> absolute (3.6,-3.6);
      its perpendicular foot is t = (0.6+0.4)/sqrt2 = 0.7071 along the edge,
      so at = 0.7071/1.4142 = 0.5, and half a door is 0.5/1.4142 = 0.3536,
      which leaves 0.5 untouched. The two neighbouring edges are 0.7211 m
      away against the chamfer's 0.1414 m, so the chamfer wins.
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


RECT = {"x": -4.0, "y": -4.0, "w": 4.0, "d": 3.2}
BIG = {"x": -4.0, "y": -4.0, "w": 8.0, "d": 8.0}
L_SHAPE = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]
CHAMFER = [[0, 0], [7.6, 0], [8, 0.4], [8, 8], [0, 8]]
CHAMFER_LONG = [[0, 0], [7, 0], [8, 1], [8, 8], [0, 8]]


def main():
    print("Part 1 — projection onto the nearest wall")
    op = project_exit_to_opening({**RECT, "exit": [0.5, 0.05]})
    check("an exit near the north wall lands on edge 0 at 0.5",
          door(op, 0, 0.5), str(op))

    op = project_exit_to_opening({**RECT, "exit": [0.8, 0.6]})
    check("an exit mid-room takes the nearest wall: edge 1 at 0.6",
          door(op, 1, 0.6), str(op))

    op = project_exit_to_opening({"x": -2.4, "y": -3.2, "w": 3.2, "d": 3.2,
                                  "exit": [1.6, 0.7]})
    check("a point outside the rectangle is clamped, then projected: "
          "edge 1 at 0.7", door(op, 1, 0.7), str(op))

    op = project_exit_to_opening({**BIG, "outline": L_SHAPE,
                                  "exit": [0.8, 0.6]})
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

    op = project_exit_to_opening({**BIG, "outline": CHAMFER,
                                  "exit": [0.96, 0.04]})
    check("a wall too short for a door yields nothing", op is None, str(op))

    print("Part 3 — the edge LENGTH decides what fits (metres, no plan width)")
    op = project_exit_to_opening({**BIG, "outline": CHAMFER_LONG,
                                  "exit": [0.95, 0.05]})
    check("a 1.414 m chamfer holds the 1.0 m door: edge 1 at 0.5",
          door(op, 1, 0.5), str(op))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
