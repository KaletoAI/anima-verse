#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_entry_group_rules.py

Hand-derived rules: walking -> @seat uses kindA, walking -> reading uses
kindB. Thus sitting (seat) uses kindA, reading (seat) uses kindB, cooking
(stand) has missing_entry_transition. Pair poses use their catalog group too.
Fixture kinds are stored as lowercase kinda/kindb, solo, non-loop, duration
2.0, root_motion keep, travel [0,-0.45], ref_height 2.011 metres.
For a 201.1cm actor scale = (201.1/100)/2.011 = 1. bridge_offset rotates
(tx,tz) to (tx*cos(yaw)+tz*sin(yaw), -tx*sin(yaw)+tz*cos(yaw)). At yaw 0,
sin=0, cos=1: delta=(0,-0.45), so slot (2,3) minus delta = (2,3.45).
Negative clip Z therefore requires access on the positive world Z side.
The exact-height case injects 201.1 at height_cm's boundary because profile
parsing rounds to integer cm. The unpatched profile case gives 201cm, hence
scale=201/201.1 and access z=3+0.45*201/201.1 = 3.4497762307309796.
standing -> @seat, walking -> @sofa and @seat -> sitting must be refused.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='entry-groups-')
ROOT = Path(TEMP.name)
os.environ.update(STORAGE_DIR=TEMP.name, INSTANCE_DIR=TEMP.name,
                  ANIMATION_CLIPS_DIR=str(ROOT / 'clips'))
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core import animation_clips as clips
from app.core.prop_action_engine import _entry_capability
from app.core.prop_action_access import slot_access

RULES = [{'from': 'walking', 'to': '@seat', 'kind': 'kinda'},
         {'from': 'walking', 'to': 'reading', 'kind': 'kindb'}]


class EntryGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / 'clips'
        directory.mkdir()
        for kind in ('kinda', 'kindb'):
            (directory / f'{kind}.fbx').write_bytes(b'isolated solo fixture')
            (directory / f'{kind}.json').write_text(json.dumps(dict(
                kind=kind, duration_s=2.0, loop=False,
                geometry=dict(root_motion=dict(mode='keep', travel_m=[0, -.45], ref_height_m=2.011)))))
        clips._clear_entries_cache()

    def setUp(self):
        self.table = patch.object(clips, 'load_transitions', return_value=RULES)
        self.table.start()
        self.addCleanup(self.table.stop)

    def test_resolution_and_access(self):
        for pose, expected in [('sitting', 'kinda'), ('reading', 'kindb')]:
            capability, reason = _entry_capability(pose)
            self.assertEqual(reason, '')
            self.assertEqual(capability[0], expected)
        self.assertEqual(_entry_capability('cooking'), (None, 'missing_entry_transition'))
        with patch('app.core.height.height_cm', return_value=201.1):
            point, reason = slot_access(dict(slots=[[2, 3]], facing=0, floor_y=0), 0,
                                        'actor', dict(pose_key='sitting', ability='pose'), {'height': 201.1})
        self.assertEqual(reason, '')
        self.assertAlmostEqual(point['x'], 2)
        self.assertAlmostEqual(point['z'], 3.45)
        self.assertEqual(point['yaw'], 0)
        point, reason = slot_access(dict(slots=[[2, 3]], facing=0, floor_y=0), 0,
                                    'actor', dict(pose_key='sitting', ability='pose'), {'height': 201.1})
        self.assertEqual(reason, '')
        self.assertAlmostEqual(point['z'], 3.4497762307309796)

    def test_pair_catalog_group(self):
        with patch('app.core.pose_catalog.get_catalog', return_value={
                'pair-seat': dict(group='seat', solo=False)}):
            self.assertEqual(_entry_capability('pair-seat')[0][0], 'kinda')

    def test_existing_wildcard_wins_before_group(self):
        with patch.object(clips, 'load_transitions', return_value=RULES + [
                {'from': '*', 'to': 'sitting', 'kind': 'kindb'}]):
            self.assertEqual(_entry_capability('sitting')[0][0], 'kindb')

    def test_existing_clip_guards_do_not_fall_back(self):
        # An explicit rule with an unusable clip must not select the group clip.
        for meta in (None, {'pair': True, 'duration_s': 2},
                     {'duration_s': 0}, {'duration_s': float('nan')},
                     {'duration_s': float('inf')}, {'duration_s': 'invalid'}):
            with self.subTest(meta=meta), patch.object(clips, 'clip_meta', return_value=meta):
                self.assertEqual(_entry_capability('reading'), (None, 'missing_entry_transition'))
        with patch.object(clips, '_solo_kinds', return_value={'kinda'}):
            self.assertEqual(_entry_capability('reading'), (None, 'missing_entry_transition'))

    def test_validation_and_shared_loading(self):
        self.assertEqual(len(clips._validate_transitions(RULES)), 2)
        for group in ('stand', 'seat', 'ground', 'lie'):
            self.assertEqual(clips._validate_transitions([
                {'from': 'walking', 'to': '@' + group, 'kind': 'kinda'}])[0]['to'], '@' + group)
        for src, dst, message in [('standing', '@seat', 'walking'),
                                  ('walking', '@sofa', 'unknown place group'),
                                  ('@seat', 'sitting', "only as 'to'")]:
            raw = dict(kind='kinda', **{'from': src, 'to': dst})
            with self.assertRaisesRegex(clips.ClipLibraryError, message):
                clips.save_transitions([raw])
            path = ROOT / 'invalid-transitions.json'
            path.write_text(json.dumps([raw]))
            self.assertEqual(clips.load_shared_transitions(path), [])
        path = ROOT / 'transitions.json'
        path.write_text(json.dumps(RULES))
        self.assertEqual(len(clips.load_shared_transitions(path)), 2)


if __name__ == '__main__':
    unittest.main()
