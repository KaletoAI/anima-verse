#!/usr/bin/env python3
"""Smoke: order shape and estimate (plan E3 Task 1, app/core/motion_orders.py).

Pure functions, no server, no world. The vector file
shared/test-vectors/order_estimate.json holds the cases O1-O3; this docstring
derives every number in it by hand.

Usage:  ./.venv/bin/python scripts/smoke_order_estimate.py

Geometry = the orders world (plan E3 Task 5): the nav world of
native/fixtures/README.md "Nav world" (location loc-nav at world (100, 0), yaw 0,
so local (lx, lz) -> world (100 + lx, lz)) plus one stool. Relevant parts:
rooms r-a (level 0, x 94...100), r-b (level 0, x 100...106), r-up (level 1);
door D0 at world (100, 2) between r-a and r-b; door D1 at (97, -4) leads
outside (rooms [r-a]); stairs id 1 with foot (101, 0, -3.3) and head
(104.5, 3, -3.3); bed box x 103.3...104.7, z 0.5...2.5.

Constants (plan E3 Task 1): START_SLACK_S 0.5, ORDER_TAIL_S 10, ARRIVE_TOL_M 0.5,
ROOM_DETOUR 1.3, DEADLINE_MIN_S 10.
  eta      = issued + exit_s + L / speed + START_SLACK_S
  flip     = eta + entry_s
  deadline = eta + max(DEADLINE_MIN_S, 0.5 * (eta - issued))

[O1] Seated NPC -> bed. Stool in r-b, anchor local (1.5, -1), 0.5 x 0.5 m ->
     box x 101.25...101.75, z -1.25...-0.75. Stand after the exit = the stool
     access (101.9, -1) (edge 101.75 + ACCESS_BODY_R_M 0.15). Bed access
     (103.15, 1.5) (bed edge x 103.3 - 0.15), yaw 90 deg. L = the straight line
     of sight (the bed is the goal and excluded, the stool lies behind the
     start) = sqrt(1.25^2 + 2.5^2) = 2.795085.
     issued 100, exit_s 1.2, entry_s 2.4, speed 1.4:
       L / speed = 2.795085 / 1.4 = 1.996489
       eta      = 100 + 1.2 + 1.996489 + 0.5 = 103.696489
       flip     = 103.696489 + 2.4          = 106.096489
       deadline = 103.696489 + max(10, 0.5 * 3.696489 = 1.848245) = 113.696489

[O2] Room change r-a (97, 0, -1) -> r-up (104, 3, 2). Chain r-a -D0 (100, 2)->
     r-b -stairs foot (101, 0, -3.3) / head (104.5, 3, -3.3)-> r-up
     (the flight carries rooms [r-b, r-up]; D1 leads outside and is no edge).
       horizontal: (97, -1) -> (100, 2)       sqrt(3^2 + 3^2)     = 4.2426407
                   (100, 2) -> (101, -3.3)    sqrt(1^2 + 5.3^2)   = 5.3935146
                   (104.5, -3.3) -> (104, 2)  sqrt(0.5^2 + 5.3^2) = 5.3235327
                   sum 14.9596880 * 1.3 = 19.4475944
       flight:     sqrt(3.5^2 + 3^2) = 4.6097722 (no factor)
       L = 19.4475944 + 4.6097722 = 24.0573666 -> 24.057367
       (The plan rounded each leg to 6 places first and summed to 24.057368;
       that is 1.4e-6 off, outside the 1e-6 tolerance, so the legs carry 7
       places here.)
     Cross-check (why decision 9): the bare straight line over D0 without the
     stairs, (4.242641 + 4) * 1.3 = 10.715433, against the client path
     P2 = 19.629751 is 8.914318 m short, 8.914318 / 1.4 = 6.37 s.
     issued 0, exit 0, entry 0: eta = flip = 24.0573666 / 1.4 + 0.5
       = 17.1838333 + 0.5 = 17.683833.
[O2b] (smoke only) The same flight WITHOUT "rooms" links every level-0 room
     with every level-1 room, so the BFS finds r-a -stairs-> r-up in one hop:
       (97, -1) -> (101, -3.3)  sqrt(4^2 + 2.3^2) = sqrt(21.29) = 4.614109
       (104.5, -3.3) -> (104, 2)                              5.323533
       (4.614109 + 5.323533) * 1.3 = 12.918935 + 4.609772 = 17.528707.
     That is why the caller names the flight's rooms when it knows them.

[O3] No chain (doorways [], stairs [], r-a and r-b both level 0):
     straight line (0, 0, 0) -> (3, 0, 4) = 5, * 1.3 = 6.5.

[O4] estimate(..., speed_m_s=0, ...) -> ValueError (also NaN input);
     new_order(..., awaits="reaction", flip_s=5) -> no key flip_motion_s;
     without awaits, flip_motion_s = 5; revision 1, seq 0; issued 1.23456 is
     published as 1.235 (3 decimals); an unknown kind raises ValueError.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# No world is touched, but the storage root goes to a temp dir before any app
# import anyway (project rule for check scripts).
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="order-estimate-storage-"))

from app.core import motion_orders as mo  # noqa: E402

VECTOR = ROOT / "shared" / "test-vectors" / "order_estimate.json"
FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILURES.append(msg)


def near(expect, actual, eps: float) -> bool:
    if isinstance(expect, (list, tuple)):
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expect)
                and all(near(e, a, eps) for e, a in zip(expect, actual)))
    return (isinstance(actual, (int, float)) and math.isfinite(actual)
            and abs(expect - actual) <= eps)


def resolve(arg, fixtures):
    if isinstance(arg, dict) and "$fixture" in arg:
        return json.loads(json.dumps(fixtures[arg["$fixture"]]))
    return arg


def run_vector() -> None:
    print("\n[vector] order_estimate.json")
    data = json.loads(VECTOR.read_text(encoding="utf-8"))
    check(data.get("source") == "scripts/smoke_order_estimate.py", "vector source names this smoke")
    dispatch = {"estimate": mo.estimate, "deadline": mo.deadline,
                "room_chain_length": mo.room_chain_length}
    fixtures = data.get("fixtures") or {}
    for case in data["cases"]:
        args = [resolve(a, fixtures) for a in case["args"]]
        got = dispatch[case["fn"]](*args)
        if isinstance(got, tuple):
            got = list(got)
        check(near(case["expect"], got, case.get("eps", 1e-9)),
              f"{case['label']}: expect {case['expect']}, got {got}")


def run_hand() -> None:
    print("\n[O1] geometry")
    check(near(2.795085, math.hypot(103.15 - 101.9, 1.5 - (-1)), 1e-6), "L = 2.795085")
    check(near(101.9, 101.75 + 0.15, 1e-9) and near(103.15, 103.3 - 0.15, 1e-9),
          "stool access 101.9, bed access 103.15")

    print("\n[O2] cross-check and fallback")
    data = json.loads(VECTOR.read_text(encoding="utf-8"))
    fx = data["fixtures"]
    straight = (math.hypot(3, 3) + 4) * mo.ROOM_DETOUR
    check(near(10.715433, straight, 1e-6), "straight line over D0 = 10.715433")
    check(near(8.914318, 19.629751 - straight, 1e-6), "8.914318 m short of P2")
    stairs = [{k: v for k, v in fx["NAV_STAIRS"][0].items() if k != "rooms"}]
    got = mo.room_chain_length(fx["NAV_ROOMS"], fx["NAV_DOORWAYS"], stairs,
                               (97, 0, -1), "r-a", (104, 3, 2), "r-up")
    check(near(17.528707, got, 1e-6), f"[O2b] flight without rooms -> 17.528707, got {got}")
    same = mo.room_chain_length(fx["NAV_ROOMS"], fx["NAV_DOORWAYS"], fx["NAV_STAIRS"],
                                (100, 0, 0), "r-b", (103, 0, 4), "r-b")
    check(near(6.5, same, 1e-9), f"same room -> straight line * 1.3 = 6.5, got {same}")

    print("\n[O4] errors and wire form")
    for bad in ((0, 0, 1, 0, 0), (0, 0, 1, -1, 0), (0, float("nan"), 1, 1.4, 0)):
        try:
            mo.estimate(*bad)
            check(False, f"estimate{bad} raises ValueError")
        except ValueError:
            check(True, f"estimate{bad} raises ValueError")
    actor = mo.actor_row("Ann", "solo", "", 170, {"x": 101.9, "y": 0, "z": -1, "yaw": 0,
                                                  "room_id": "r-b", "level": 0},
                         access={"x": 103.15, "y": 0, "z": 1.5, "yaw": 90},
                         sequence=[mo.step("exit", "seat", nominal_s=1.2), mo.step("walk"),
                                   mo.step("entry", "lie", nominal_s=2.4), mo.step("loop", "lie", "lie_idle")])
    common = dict(issued_s=1.23456, eta_s=3, deadline_s=13, actors=[actor],
                  target={"location_id": "loc-nav", "room_id": "r-b", "level": 0},
                  speed_m_s=1.4, gait="walk", status="waiting")
    waiting = mo.new_order("prop_action", flip_s=5, awaits="reaction", **common)
    check("flip_motion_s" not in waiting, "awaits set -> no flip_motion_s")
    plain = mo.new_order("prop_action", flip_s=5, **{**common, "status": "approaching"})
    check(plain.get("flip_motion_s") == 5, "no awaits -> flip_motion_s 5")
    check(plain["revision"] == 1 and plain["seq"] == 0, "revision 1, seq 0")
    check(plain["issued_motion_s"] == 1.235, f"issued rounded to 1.235, got {plain['issued_motion_s']}")
    check([s["step"] for s in plain["actors"][0]["sequence"]] == ["exit", "walk", "entry", "loop"],
          "actor sequence exit/walk/entry/loop")
    cancel = mo.new_order("cancel", flip_s=5, stand={"x": 1, "y": 0, "z": 2, "yaw": 0},
                          snap=True, **{**common, "status": "ended"})
    check(cancel["actors"][0].get("stand") == {"x": 1, "y": 0, "z": 2, "yaw": 0} and "stand" not in cancel,
          "stand lands per actor, not on top")
    try:
        mo.new_order("pair", flip_s=5, **common)
        check(False, "unknown kind raises ValueError")
    except ValueError:
        check(True, "unknown kind raises ValueError")
    check((mo.START_SLACK_S, mo.ORDER_TAIL_S, mo.ARRIVE_TOL_M, mo.ROOM_DETOUR, mo.DEADLINE_MIN_S)
          == (0.5, 10.0, 0.5, 1.3, 10.0), "constants")


def main() -> int:
    run_vector()
    run_hand()
    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} check(s)")
        return 1
    print("\nOK: order estimate O1-O4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
