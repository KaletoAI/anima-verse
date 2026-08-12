#!/usr/bin/env python3
"""Smoke run for the mirrored openings (Block L1).

Pure geometry, no world, no DB: hand-built room dicts go straight into
``room_recipe.compose_recipe``. The interesting part is the projection —
two clockwise hulls traverse a shared wall in OPPOSITE directions, so the
mirrored ``at`` must come out flipped.

Layout used throughout (absolute plate fractions, y down):

    0.0        0.4        0.8
0.0 ┌──────────┬──────────┐
    │    A     │    B     │      shared wall at x = 0.4
0.5 └──────────┴──────────┘

Usage:  ./.venv/bin/python scripts/smoke_room_recipe_mirror.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import room_recipe  # noqa: E402

FAILURES = []
PLAN_W = 8.0  # metres for the whole 8×8 reference plate


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a: float, b: float, eps: float = 1e-3) -> bool:
    return abs(float(a) - float(b)) <= eps


def room(rid: str, x: float, y: float, w: float, d: float, **lay) -> dict:
    return {"id": rid, "layout": {"x": x, "y": y, "w": w, "d": d, **lay}}


# Rooms are plain rectangles → implicit unit square, clockwise:
# edge 0 = N (left→right), 1 = E (top→bottom), 2 = S (right→left), 3 = W (bottom→top)
def room_a(**lay) -> dict:
    return room("a", 0.0, 0.0, 0.4, 0.5, **lay)


def room_b(**lay) -> dict:
    return room("b", 0.4, 0.0, 0.4, 0.5, **lay)


def recipe(r: dict, siblings=(), plan_w: float = PLAN_W) -> dict:
    return room_recipe.compose_recipe(r, siblings, plan_w)


def test_mirror() -> None:
    print("\n[1] a door on the shared wall appears in both rooms")
    # A's E edge (index 1) runs top→bottom; the door sits at at=0.3 on it,
    # i.e. 0.3 * 0.5 = 0.15 down from the top → world y = 0.15.
    a = room_a(openings=[{"edge": 1, "at": 0.3, "type": "door",
                          "width_m": 1.0, "height_m": 2.1, "to": "b"}])
    b = room_b()
    rb = recipe(b, [a])
    mirrored = [op for op in rb["openings"] if op.get("mirrored")]
    check("the neighbour's door shows up once", len(mirrored) == 1,
          str(rb["openings"]))
    m = mirrored[0]
    # B's W edge (index 3) runs bottom→top — the opposite direction, so the
    # same world point lands at 1 - 0.3 = 0.7.
    check("it lands on B's facing edge (W = 3)", m["edge"] == 3, str(m["edge"]))
    check("at is flipped against the edge direction", near(m["at"], 0.7),
          str(m["at"]))
    check("to points back at the owning room", m["to"] == "a", str(m.get("to")))
    check("type/width/height are carried over unchanged",
          m["type"] == "door" and near(m["width_m"], 1.0)
          and near(m["height_m"], 2.1), str(m))

    print("\n[2] the same world point, both ways round")
    ra = recipe(a, [b])
    own = [op for op in ra["openings"] if not op.get("mirrored")]
    check("the owner keeps exactly its own opening", len(own) == 1
          and len(ra["openings"]) == 1, str(ra["openings"]))
    # World point of the door from A's side and from B's mirrored entry.
    pa = room_recipe._point_on_edge(ra["outline"], own[0]["edge"], own[0]["at"])
    pb = room_recipe._point_on_edge(rb["outline"], m["edge"], m["at"])
    check("both descriptions denote the same wall point",
          near(pa[0], pb[0]) and near(pa[1], pb[1]),
          f"{[round(v, 4) for v in pa]} vs {[round(v, 4) for v in pb]}")
    check("and that point is on the shared wall x=0.4 at y=0.15",
          near(pa[0], 0.4) and near(pa[1], 0.15),
          str([round(v, 4) for v in pa]))

    print("\n[3] what must NOT be mirrored")
    outside_win = room_a(openings=[{"edge": 3, "at": 0.5, "type": "window",
                                    "width_m": 1.2, "to": "outside"}])
    rb2 = recipe(room_b(), [outside_win])
    check("an opening on an EXTERIOR wall does not reach the neighbour",
          not [op for op in rb2["openings"] if op.get("mirrored")],
          str(rb2["openings"]))
    check("the owner's outside window keeps its to",
          recipe(outside_win, [room_b()])["openings"][0]["to"] == "outside")

    far = room("c", 0.9, 0.0, 0.4, 0.5)          # no touching wall
    rc = recipe(far, [a])
    check("a room that shares no wall gets nothing",
          not [op for op in rc["openings"] if op.get("mirrored")])

    other_level = room("d", 0.4, 0.0, 0.4, 0.5, level=1)
    rd = recipe(other_level, [a])
    check("a room on another level gets nothing",
          not [op for op in rd["openings"] if op.get("mirrored")])

    print("\n[4] a window on a shared wall is mirrored too")
    a_win = room_a(openings=[{"edge": 1, "at": 0.5, "type": "window",
                              "width_m": 1.2, "height_m": 1.2, "sill_m": 0.9}])
    mw = [op for op in recipe(room_b(), [a_win])["openings"] if op.get("mirrored")]
    check("windows share the wall like doors do", len(mw) == 1)
    check("sill_m survives", mw and near(mw[0].get("sill_m", -1), 0.9), str(mw))

    print("\n[5] an opening outside the shared stretch")
    # B only covers the upper half of A's E edge → a door low on that edge
    # pierces no shared wall.
    b_half = room("b", 0.4, 0.0, 0.4, 0.2)
    a_low = room_a(openings=[{"edge": 1, "at": 0.9, "type": "door",
                              "width_m": 1.0}])
    check("a door beyond the overlap is not mirrored",
          not [op for op in recipe(b_half, [a_low])["openings"]
               if op.get("mirrored")])
    a_high = room_a(openings=[{"edge": 1, "at": 0.2, "type": "door",
                               "width_m": 1.0}])
    check("a door inside the overlap still is",
          len([op for op in recipe(b_half, [a_high])["openings"]
               if op.get("mirrored")]) == 1)


def test_signature() -> None:
    print("\n[10] the signature follows the neighbours")
    b = room_b()
    base = recipe(b, [room_a()])["signature"]
    with_door = recipe(b, [room_a(openings=[{"edge": 1, "at": 0.3,
                                             "type": "door"}])])["signature"]
    check("a neighbour's new door moves B's signature", base != with_door,
          f"{base[:8]} vs {with_door[:8]}")
    check("the same input gives the same signature",
          recipe(b, [room_a()])["signature"] == base)
    moved = recipe(b, [room_a(openings=[{"edge": 1, "at": 0.6,
                                         "type": "door"}])])["signature"]
    check("moving that door moves it again", moved != with_door,
          f"{with_door[:8]} vs {moved[:8]}")

    print("\n[11] plan width only scales the tolerances")
    a = room_a(openings=[{"edge": 1, "at": 0.3, "type": "door"}])
    wide = recipe(room_b(), [a], 24.0)
    check("a 24 m plate still mirrors the door",
          len([op for op in wide["openings"] if op.get("mirrored")]) == 1)
    noscale = recipe(room_b(), [a], 0.0)
    check("no plan width falls back to the 8 m plate",
          len([op for op in noscale["openings"] if op.get("mirrored")]) == 1)


def test_unchanged() -> None:
    print("\n[12] nothing else moved")
    solo = recipe(room_a(openings=[{"edge": "S", "at": 0.25, "type": "door"}]))
    check("compose_recipe still works without siblings", solo is not None)
    check("legacy letter edges still normalize (S flips)",
          solo["openings"][0]["edge"] == 2
          and near(solo["openings"][0]["at"], 0.75), str(solo["openings"][0]))
    check("a room without layout is still None",
          room_recipe.compose_recipe({"id": "x"}, [room_a()]) is None)
    check("the payload keys are exactly these (no exit any more)",
          set(solo) == {"room_id", "level", "outline", "openings", "placements",
                        "prop_markers", "signature"},
          str(sorted(solo)))


def main() -> int:
    test_mirror()
    test_signature()
    test_unchanged()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
