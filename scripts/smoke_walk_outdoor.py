#!/usr/bin/env python3
"""Walk orders in the open (plan E3 Task 9, decision 11): the route hint and
the passability gate.

Usage: ./.venv/bin/python scripts/smoke_walk_outdoor.py

The fixture is the one of ``smoke_walk_orders.py`` (temporary storage and
instance, no server, motion clock pinned at 100). The orders world's location
"Navhaus" sits at world (100, 0) with the outline x 94..106, z -7..4. Added
here: a deep-water area x 120..140, z -10..10 (impassable on foot).

[O1] A stroll from (110, 10) to (110, 20), both outside every outline and
     the water: ``hint_route`` starts at the start, ends at the target, every
     point of it is passable, its length is at least the straight 10 m, and
     eta - issued = length / 1.4 + 0.5 (3-decimal rounding). Until the flip
     the position stays (110, 10), the location stays "" throughout, after
     the flip the position is (110, 20).
[O2] A target inside the water (130, 0) -> (None, "unpassable"), no order.
[O3] A target inside the Navhaus outline (97, -1) from the open -> (None,
     "no_route"): entering a location is a journey, never a walk.
[O4] An NPC inside r-a asks for a target in the open (110, 10) -> (None,
     "no_route"): leaving a location is a journey as well.
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_walk_orders as WO                                           # noqa: E402

F, MO = WO.F, WO.MO
from app.core import paths                                               # noqa: E402
paths.init(F.ROOT / "world")    # the fixture's private world, named here once more
from app.core.terrain_query import passability_at                       # noqa: E402
from app.models import terrain                                           # noqa: E402


class Outdoor(unittest.TestCase):
    def setUp(self):
        F.MOTION[0] = 100.0
        MO.boot()
        self.loc = WO.nav_world()
        for area in terrain.list_areas():
            terrain.delete_area(area["id"])
        terrain.save_area({"kind": "deep_water", "polygon": [[120, -10], [140, -10], [140, 10], [120, 10]],
                           "z_order": 0})

    def test_o1_route_hint_in_the_open(self):
        name = WO.npc((110, 10))
        order, reason = MO.issue_walk(name, 110, 20)
        self.assertEqual(reason, "ok")
        route = order["hint_route"]
        self.assertEqual((route[0], route[-1]), ([110, 10], [110, 20]))
        self.assertTrue(all(passability_at(x, z)[0] for x, z in route))
        length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
        self.assertGreaterEqual(length, 10 - 1e-6)
        self.assertAlmostEqual(order["eta_motion_s"] - 100.0, length / 1.4 + 0.5, delta=6e-4)
        F.MOTION[0] = order["flip_motion_s"] - 0.05
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(WO.pos(name), (110.0, 10.0))
        F.MOTION[0] = order["flip_motion_s"]
        self.assertEqual(MO.settle_due(), 1)
        self.assertEqual(WO.pos(name), (110.0, 20.0))
        self.assertEqual(F.C.get_character_current_location(name), "")

    def test_o2_water_target_is_refused(self):
        name = WO.npc((110, 10))
        self.assertEqual(MO.issue_walk(name, 130, 0), (None, "unpassable"))
        self.assertIsNone(MO.index_get(name))

    def test_o3_entering_a_location_is_no_walk(self):
        name = WO.npc((110, 10))
        self.assertEqual(MO.issue_walk(name, 97, -1), (None, "no_route"))

    def test_o4_leaving_a_location_is_no_walk(self):
        name = WO.npc((97, -1), self.loc, "r-a")
        self.assertEqual(MO.issue_walk(name, 110, 10), (None, "no_route"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
