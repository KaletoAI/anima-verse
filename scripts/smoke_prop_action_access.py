#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_access.py

Hand-derived entry geometry: clip travel (0, -1) metres, reference height
1.70m and actor height 170cm give scale 1. At yaw 0 bridge_offset=(0,-1),
so bench slots (-.6,0),(0,0),(.6,0), capacity 3 spacing .6, need access
(-.6,1),(0,1),(.6,1). At yaw90 offset=(-1,0), bed marker (-.5,0)
needs (.5,0); yaw270 offset=(1,0), marker (.5,0) needs (-.5,0).
Each access plus its entry travel ends exactly on its slot (<5cm).
An explicit override remains verbatim, so a displaced override must fail
entry checking rather than being silently corrected.
"""
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='prop-access-')
os.environ.update(STORAGE_DIR=TEMP.name, INSTANCE_DIR=TEMP.name,
                  ANIMATION_CLIPS_DIR=str(Path(TEMP.name) / 'clips'))
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core.prop_action_access import slot_access
from app.core.scene_recipe import marker_slots
from app.core.room_stand import bridge_offset

class Access(unittest.TestCase):
    def test_slots_and_opposite_facings(self):
        action = {'pose_key': 'sitting', 'ability': 'pose'}
        cases = [(marker_slots((0, 0), 0, 3, .6), 0,
                  [(-.6, 1), (0, 1), (.6, 1)]),
                 ([[-.5, 0]], 90, [(.5, 0)]),
                 ([[.5, 0]], 270, [(-.5, 0)])]
        with patch('app.core.prop_action_engine._entry_capability', return_value=(('entry', {}), '')), \
             patch('app.core.animation_clips.clip_travel_m', return_value=(0, -1)), \
             patch('app.core.animation_clips.clip_ref_height_m', return_value=1.7):
            for slots, facing, expected in cases:
                place = dict(slots=slots, facing=facing, floor_y=2)
                for i, want in enumerate(expected):
                    point, reason = slot_access(place, i, 'actor', action, {'height': 170})
                    self.assertEqual(reason, '')
                    self.assertAlmostEqual(point['x'], want[0])
                    self.assertAlmostEqual(point['z'], want[1])
                    self.assertEqual(point['yaw'], facing)
                    self.assertEqual(point['y'], 2)
                    dx, dz = bridge_offset((0, -1), point['yaw'], 1)
                    self.assertLess(math.dist((point['x']+dx, point['z']+dz), slots[i]), .05)
            override = dict(x=9, z=8, yaw=27, y=2)
            point, reason = slot_access(dict(slots=[[0, 0]], facing=0, floor_y=2,
                                             access={'actor': override}), 0, 'actor', action, {'height': 170})
            self.assertEqual(point, override)
            self.assertEqual(reason, '')
            point, _ = slot_access(dict(slots=[[0, 0]], facing=0, floor_y=2),
                                   0, 'actor', action, {'height': 85})
            self.assertAlmostEqual(point['z'], .5)

if __name__ == '__main__':
    unittest.main()
