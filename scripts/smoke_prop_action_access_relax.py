#!/usr/bin/env python3
"""Relaxed final approach and direct entry, using private path/run fixtures.

Usage: ./.venv/bin/python scripts/smoke_prop_action_access_relax.py

Expected values BY HAND: chair at (8,5), width/depth 1, full grown bounds
[7.2,8.8] x [4.2,5.8]. Entry travel .6m at height 170cm and yaw 180
puts access at (8,5.6), inside that keepout. Own exemption admits it.
A 1m table centred at (8,6.3) has near edge z=5.8: access gap .2m
exceeds .15m. At z=6.2 the gap is .1m, so bridge fails. A 2m square
table centred (8,5) encloses access: full keepout [6.7,9.3] x [3.7,6.3].
From anchor (8,5), the 1.30m ring touches the closed keepout; 1.35m
is the first free ring. Angle zero wins: direct goal (9.35,5).
The old planner at explicit commit 5d34a4e5 refuses all three scenarios
(a), (b .2m), (c), with access_not_walkable. Earlier legs must still
avoid full .3m keepouts. Removing either final-space revalidation or its
split would cancel the exercised mid-final-leg journey.
Additional hand-derived guards: wall margin is .35m; door growth remains
.30m. Step-out starts (8.3,5)->(8.85,5) as in the reused step-out smoke.
A new 1m table centred at access encloses that endpoint and must cancel it.
The imported fixture calls paths.init(tempdir) before world-DB imports.
"""
import json
import hashlib
import sys
import subprocess
import unittest
from unittest.mock import patch

import smoke_prop_action_runs as S
F, A = S.F, S.A


def scenario(table=None):
    name, target, pid = S.setup_run()
    doc = F.props.read_sidecar(pid)
    doc['model_variants'][0]['markers'][0].update(access={}, facing=180)
    F.props._write_sidecar(pid, doc)
    clip = F.ROOT / 'clips/run-enter.json'
    meta = json.loads(clip.read_text())
    meta['geometry']['root_motion']['travel_m'] = [0, .6]
    clip.write_text(json.dumps(meta))
    S.clips._clear_entries_cache()
    if table:
        width, depth, at = table
        table_id = F.furniture_prop('Other table', width=width, depth=depth, height=1)
        loc = F.W.get_location_by_id(target['location_id'])
        loc['rooms'][0]['layout']['props'].append(dict(id='table', prop_id=table_id, at=at))
        F.W.upsert_location(loc, sync_world=True)
    target['definition_revision'] = F.props.get_prop(pid)['revision']
    F.C.set_character_pos(name, 10, 5)
    F.places.invalidate()
    return name, target


class Relax(unittest.TestCase):
    def test_a_own_footprint(self):
        name, target = scenario()
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        self.assertEqual(plan['entry_mode'], 'bridge')
        self.assertAlmostEqual(plan['access']['z'], 5.6)

    def test_b_other_clearance(self):
        for z, mode in ((6.3, 'bridge'), (6.2, 'direct')):
            name, target = scenario((1, 1, [8, z]))
            plan = F.N.plan_approach(name, target, 'actor')
            self.assertEqual(plan['status'], 'ok', plan)
            self.assertEqual(plan['entry_mode'], mode, plan)

    def test_c_direct_nearest_and_activation(self):
        name, target = scenario((2, 2, [8, 5]))
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        self.assertEqual(plan['entry_mode'], 'direct')
        self.assertEqual(plan['waypoints'][-1], [9.35, 5])
        result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=30))
        F.E.advance_all_journeys()
        run = S.R.get(result['execution_id'])
        self.assertEqual(run['status'], 'active', run)
        profile = F.C.get_character_profile(name)
        self.assertFalse(profile.get('prop_action_entry'))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (8, 5))

    def test_d_final_leg_revalidation(self):
        name, target = scenario()
        with patch.object(F.E, 'get_travel_speed_m_s', return_value=.1):
            result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        journey = F.E.get_journey(name)
        duration = journey['waypoints'][-1][2]
        # The approach starts after a poll lead (travel_engine._approach_start);
        # count the legs from that start, not from the request.
        lead = (F.GameTime.parse(journey['started_at_game']) - F.game_time()).total_seconds
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=lead + int(duration) - 1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name))
        F.E._approach_validation_cache.clear()
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name))
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertEqual(S.R.get(result['execution_id'])['phase'], 'entry')

    def test_e_earlier_legs_full_rules(self):
        name, target = scenario((1, 3, [10, 5]))
        F.C.set_character_pos(name, 11.5, 5)
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        full = F.N._Space(*F.S.room_geometry(target['location_id'], 'hall'))
        self.assertGreater(len(plan['waypoints']), 2)
        self.assertTrue(all(full.visible(tuple(a), tuple(b)) for a, b in zip(plan['waypoints'][:-2], plan['waypoints'][1:-1])))

    def test_f_bridge_blocked_but_access_free(self):
        name, target = scenario((.2, .2, [8, 5.2]))
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['entry_mode'], 'direct', plan)
        self.assertEqual(plan['bridge_reason'], 'entry_transition_blocked')
        self.assertEqual(A._entry_spec(name, plan, 'sitting')[0]['duration_game_s'], 0)

    def test_g_report_names_and_read_only_cli(self):
        import contextlib
        import io
        import report_prop_access as report
        import config_history
        name, target = scenario((2, 2, [8, 5]))
        location = F.W.get_location_by_id(target['location_id'])
        table_id = location['rooms'][0]['layout']['props'][-1]['prop_id']
        doc = F.props.read_sidecar(table_id)
        doc.update(name='Other table', name_de='Anderer Tisch')
        F.props._write_sidecar(table_id, doc)
        database = F.ROOT / 'world/world.db'
        def source_hashes():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in database.parent.glob('world.db*')}
        before = source_hashes()
        output = F.ROOT / 'access.md'
        # The real repository server may be running; only this PRIVATE fixture
        # bypasses its conservative PID guard. The CLI still opens SQLite RO.
        # Fresh process ensures all DB-function imports bind to the RO snapshot,
        # just like the standalone CLI (this fixture already imported writers).
        code = ("import sys; sys.path.insert(0, 'scripts'); import config_history; "
                "config_history._server_running=lambda _:False; "
                "from report_prop_access import main; main()")
        result = subprocess.run([sys.executable, '-c', code, '--storage', str(database.parent),
                                 '--out', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = output.read_text()
        self.assertIn('| direct | access_not_walkable |', text)
        self.assertIn('Anderer Tisch:', text)
        self.assertIn('170 cm', text)
        self.assertIn('| seat | 0 | 1 | 0 | 1 |', text)
        self.assertEqual(source_hashes(), before)
        with patch.object(config_history, '_server_running', return_value=True), patch.object(
                __import__('sys'), 'argv', ['report_prop_access.py', '--storage', str(database.parent)]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as refused:
                report.main()
            self.assertEqual(refused.exception.code, 2)

    def test_h_pair_direct_per_role(self):
        name, partner, target, pid = S.authored_pair()
        # Tiny table at actor access (7.7,7); partner access (8.3,7)
        # is .5m from its edge, so only the actor requires direct entry.
        table = F.furniture_prop('Role obstruction', width=.2, depth=.2, height=1)
        loc = F.W.get_location_by_id(target['location_id'])
        loc['rooms'][0]['layout']['props'].append(dict(id='table', prop_id=table, at=[7.7, 7]))
        F.W.upsert_location(loc, sync_world=True)
        result = S.request(name, target, partner=partner)
        self.assertEqual(result['status'], 'awaiting_consent', result)
        result = A.respond(partner, result['execution_id'], True)
        self.assertEqual(result['status'], 'approaching', result)
        run = S.R.get(result['execution_id'])
        self.assertEqual(run['data']['plans']['actor']['entry_mode'], 'direct', run)
        self.assertEqual(run['data']['plans']['partner']['entry_mode'], 'bridge', run)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=30))
        F.E.advance_all_journeys()
        self.assertFalse(F.C.get_character_profile(name).get('prop_action_entry'))
        self.assertTrue(F.C.get_character_profile(partner).get('prop_action_entry'))
        S.tick(3)
        self.assertEqual(S.R.get(result['execution_id'])['status'], 'active')

    def test_i_final_walls_and_door_zones_unchanged(self):
        # Wall margin .35m: x=.34 fails, .35 succeeds. A door ring ending
        # x=6 is still grown by .30: x=6.20 fails, x=6.31 succeeds.
        geometry = (F.SQUARE, [], [[(4, 4), (6, 4), (6, 6), (4, 6)]])
        final = F.N.access_space(geometry, 'device')
        self.assertFalse(final.free((.34, 5)))
        self.assertTrue(final.free((.35, 5)))
        self.assertFalse(final.free((6.20, 5)))
        self.assertTrue(final.free((6.31, 5)))
        self.assertFalse(final.visible((3, 5), (7, 5)))

    def test_j_step_out_then_relaxed_final_leg(self):
        name, target = scenario()
        F.C.set_character_pos(name, 8.3, 5)
        with patch.object(F.E, 'get_travel_speed_m_s', return_value=.1):
            result = S.request(name, target)
        journey = F.E.get_journey(name)
        self.assertEqual([p[:2] for p in journey['waypoints'][:2]], [[8.3, 5], [8.85, 5]])
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=int(journey['waypoints'][-1][2]) - 1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name))
        F.E._approach_validation_cache.clear()
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name))
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=2))
        F.E.advance_all_journeys()
        self.assertEqual(S.R.get(result['execution_id'])['phase'], 'entry')

    def test_k_new_final_obstruction_cancels(self):
        name, target = scenario()
        result = S.request(name, target)
        table = F.furniture_prop('New obstruction', width=1, depth=1, height=1)
        loc = F.W.get_location_by_id(target['location_id'])
        loc['rooms'][0]['layout']['props'].append(dict(id='table', prop_id=table, at=[8, 5.6]))
        F.W.upsert_location(loc, sync_world=True)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=30))
        F.E.advance_all_journeys()
        self.assertIsNone(F.E.get_journey(name))
        self.assertEqual(S.R.get(result['execution_id'])['reason'], 'approach_route_changed')


def old_code_proof():
    source = subprocess.check_output(['git', 'show', '5d34a4e5:app/core/prop_action_paths.py'], text=True)
    scope = dict(vars(F.N))
    exec(compile(source, '<5d34a4e5>', 'exec'), scope)
    for table in (None, (1, 1, [8, 6.3]), (2, 2, [8, 5])):
        name, target = scenario(table)
        plan = scope['_plan_approach'](name, target, 'actor')
        assert plan['reason'] == 'access_not_walkable', plan
    print('5d34a4e5: (a), (b .2m), (c) fail with access_not_walkable', flush=True)


if __name__ == '__main__':
    old_code_proof()
    result = unittest.main(exit=False).result
    F.assert_no_external_work()
    raise SystemExit(0 if result.wasSuccessful() else 1)
