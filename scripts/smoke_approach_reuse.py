#!/usr/bin/env python3
"""Approach validation reuse: unchanged walking needs one plan, edits need another.

Usage: python scripts/smoke_approach_reuse.py
Reuses the private-storage, external-work-disabled indoor fixture. Two 1s
steps must move the actor but perform only one plan; an external position edit
must force a second plan. A new blocker must still cancel the promised route.
"""
import unittest
from unittest.mock import patch
import smoke_prop_action_paths as F


class Reuse(unittest.TestCase):
    setUpClass = classmethod(F.Ownership.setUpClass.__func__)
    start = F.Ownership.start
    tearDown = F.Ownership.tearDown

    def test_normal_steps_reuse_but_external_position_invalidates(self):
        name, target, plan, journey = self.start()
        with patch.object(F.N, '_plan_approach', wraps=F.N._plan_approach) as planner:
            for _ in range(2):
                F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
                F.E.advance_all_journeys()
            self.assertEqual(planner.call_count, 1, 'ordinary committed movement must reuse validation')
            pos = F.C.get_character_pos(name)
            with F.db.transaction() as conn:
                conn.execute('UPDATE character_state SET pos_x=? WHERE character_name=?',
                             (pos['x'] + .1, name))
            F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
            F.E.advance_all_journeys()
            self.assertEqual(planner.call_count, 2, 'external position change must invalidate')

    def test_nonround_speed_normal_ticks_reuse(self):
        name, _, _, journey = self.start()
        journey['speed_m_s'] = 1.234567
        journey['waypoints'] = [[x, z, t / 1.234567] for x, z, t in journey['waypoints']]
        profile = F.C.get_character_profile(name)
        profile['journey'] = journey
        F.C.save_character_profile(name, profile)
        before = F.C.get_character_pos(name)
        with patch.object(F.N, '_plan_approach', wraps=F.N._plan_approach) as planner:
            for _ in range(2):
                F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
                F.E.advance_all_journeys()
            self.assertEqual(planner.call_count, 1)
        self.assertNotEqual(F.C.get_character_pos(name), before)

    def test_subcentimetre_interpolation_uses_persisted_position_precision(self):
        name, _, _, journey = self.start()
        # Nonround speed on the persisted polyline; journey_state currently
        # projects this to centimetres. Exercise a future unrounded result too.
        journey['speed_m_s'] = 1.234567
        journey['waypoints'] = [[x, z, t / 1.234567] for x, z, t in journey['waypoints']]
        profile = F.C.get_character_profile(name)
        profile['journey'] = journey
        F.C.save_character_profile(name, profile)
        original = F.E.journey_state
        def precise(*args, **kwargs):
            state = original(*args, **kwargs)
            state['pos'] = (state['pos'][0] + .001, state['pos'][1] + .001)
            return state
        with patch.object(F.E, 'journey_state', side_effect=precise), patch.object(
                F.N, '_plan_approach', wraps=F.N._plan_approach) as planner:
            for _ in range(2):
                F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
                F.E.advance_all_journeys()
            self.assertEqual(planner.call_count, 1, 'cache position must use the database centimetre projection')

    def test_geometry_change_invalidates_warm_cache_before_crossing_blocker(self):
        name, target, _, journey = self.start()
        F.E.advance_all_journeys()
        before = F.C.get_character_pos(name)
        blocker = F.furniture_prop('New obstruction', width=1, depth=2, height=2)
        location = F.W.get_location_by_id(target['location_id'])
        next(r for r in location['rooms'] if r['id'] == 'hall')['layout']['props'].append(
            {'id': 'barrier', 'prop_id': blocker, 'at': [4, 5.86]})
        F.W.upsert_location(location, sync_world=True)
        F.set_game_time(F.game_time() + F.GameDuration.of(hours=1))
        F.E.advance_all_journeys()
        self.assertIsNone(F.E.get_journey(name))
        self.assertEqual(F.C.get_character_pos(name), before)
        self.assertEqual(self.owner.runs[journey['execution_ref']]['reason'], 'approach_route_changed')

    def test_definition_edit_invalidates_warm_cache(self):
        name, target, _, journey = self.start()
        F.E.advance_all_journeys()
        before = F.C.get_character_pos(name)
        place = next(p for p in F.places.room_places(target['location_id'], target['room_id'])
                     if p['placement_id'] == target['placement_id'])
        doc = F.props.read_sidecar(place['prop_id'])
        doc['actions'][0]['description'] = 'Changed definition'
        F.props._write_sidecar(place['prop_id'], doc)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertIsNone(F.E.get_journey(name))
        self.assertEqual(F.C.get_character_pos(name), before)
        self.assertEqual(self.owner.runs[journey['execution_ref']]['reason'], 'stale_definition')


if __name__ == '__main__':
    unittest.main()
