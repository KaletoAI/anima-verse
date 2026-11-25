#!/usr/bin/env python3
"""Prop-action access: the entry geometry of a slot's access point, and the relaxed final approach and
direct entry (using private path/run fixtures).

Usage: ./.venv/bin/python scripts/smoke_prop_action_access.py

Two sections: the old-code proof runs first, then every unittest case of both classes (unittest names each
failing case and still runs the rest); a failed proof is reported and the cases still run. Exit non-zero
on any failure, naming the failed section.

[E] ENTRY GEOMETRY (class Access). Hand-derived entry geometry: clip travel (0, -1) metres, reference height
1.70m and actor height 170cm give scale 1. At yaw 0 bridge_offset=(0,-1),
so bench slots (-.6,0),(0,0),(.6,0), capacity 3 spacing .6, need access
(-.6,1),(0,1),(.6,1). At yaw90 offset=(-1,0), bed marker (-.5,0)
needs (.5,0); yaw270 offset=(1,0), marker (.5,0) needs (-.5,0).
Yaw 270 normalises to -90. With turn 90, facing 0, travel (0,-1),
start yaw -90 gives offset (1,0), so slot (2,3) needs access (1,3).
Each access plus its entry travel ends exactly on its slot (<5cm).
An explicit override remains verbatim, so a displaced override must fail
entry checking rather than being silently corrected.

[R] RELAXED APPROACH (class Relax, formerly smoke_prop_action_access_relax): Relaxed final approach and direct entry, using private path/run fixtures.
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
avoid full .3m keepouts. Since plan E3 Task 7 the server walks no journey:
the client walks the plan, the run reaches its access at its estimated eta
(motion clock) and its checks (_validate) must accept the relaxed access
inside the own keepout there (d, j). (c) from (10,5) to (9.35,5):
L = .65, eta = issued + .65/1.4 + .5 = issued + .964286, a direct entry
lasts 0 s, so one second later the run is active on (8,5).
Additional hand-derived guards: wall margin is .35m; door growth remains
.30m. Step-out starts (8.3,5)->(8.85,5) as in the reused step-out smoke.
A new 1m table centred at access encloses that endpoint and the bridge to
the seat: at its arrival (eta) the run's entry check finds the bridge
blocked and fails it (entry_transition_blocked).
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

import math  # noqa: E402
from app.core.prop_action_access import slot_access  # noqa: E402
from app.core.scene_recipe import marker_slots  # noqa: E402
from app.core.room_stand import bridge_offset  # noqa: E402


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
        run = S.R.get(result['execution_id'])
        self.assertAlmostEqual(run['data']['eta_s'][name] - run['data']['issued_s'], .964286, places=3)
        F.elapse(1)
        A.advance(F.game_time())
        run = S.R.get(result['execution_id'])
        self.assertEqual(run['status'], 'active', run)
        profile = F.C.get_character_profile(name)
        self.assertFalse(profile.get('prop_action_entry'))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (8, 5))

    def arrive_at_eta(self, name, eid):
        """One full round just before the run's eta (still walking), then one
        at it: the arrival at the relaxed access must pass the run's checks."""
        eta = S.R.get(eid)['data']['eta_s'][name]
        F.MOTION[0] = eta - .05
        A.advance(F.game_time())
        self.assertEqual(S.R.get(eid)['phase'], '', S.R.get(eid)['reason'])
        F.MOTION[0] = eta
        A.advance(F.game_time())
        self.assertEqual(S.R.get(eid)['phase'], 'entry', S.R.get(eid)['reason'])
        self.assertIsNone(F.E.get_journey(name))

    def test_d_relaxed_access_arrival(self):
        name, target = scenario()
        result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        self.assertAlmostEqual(S.R.get(result['execution_id'])['data']['plans'][name]['access']['z'], 5.6)
        self.arrive_at_eta(name, result['execution_id'])

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
        self.assertEqual(A._entry_spec(name, plan, 'sitting')[0]['duration_s'], 0)

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
        result = S.request(name, target, members=[partner])
        self.assertEqual(result['status'], 'awaiting_consent', result)
        result = A.respond(partner, result['execution_id'], True)
        self.assertEqual(result['status'], 'approaching', result)
        run = S.R.get(result['execution_id'])
        self.assertEqual(run['data']['plans'][name]['entry_mode'], 'direct', run)
        self.assertEqual(run['data']['plans'][partner]['entry_mode'], 'bridge', run)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=30))
        A.advance(F.game_time())
        run = S.R.get(result['execution_id'])
        self.assertEqual(run['phase'], 'entry', run)
        # The entry each role plays (the profile no longer carries it, plan E3 Task 7).
        self.assertEqual(run['data']['entries'][name]['duration_s'], 0)
        self.assertEqual(run['data']['entries'][partner]['kind'], 'run-enter')
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
        result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        waypoints = S.R.get(result['execution_id'])['data']['plans'][name]['waypoints']
        self.assertEqual([p[:2] for p in waypoints[:2]], [[8.3, 5], [8.85, 5]])
        self.arrive_at_eta(name, result['execution_id'])

    def test_k_new_final_obstruction_cancels(self):
        name, target = scenario()
        result = S.request(name, target)
        table = F.furniture_prop('New obstruction', width=1, depth=1, height=1)
        loc = F.W.get_location_by_id(target['location_id'])
        loc['rooms'][0]['layout']['props'].append(dict(id='table', prop_id=table, at=[8, 5.6]))
        F.W.upsert_location(loc, sync_world=True)
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=30))
        A.advance(F.game_time())
        self.assertIsNone(F.E.get_journey(name))
        run = S.R.get(result['execution_id'])
        self.assertEqual((run['status'], run['reason']), ('failed', 'entry_transition_blocked'))


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
                    self.assertEqual(point['yaw'], -90 if facing == 270 else facing)
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

    def test_turning_entry(self):
        with patch('app.core.prop_action_engine._entry_capability', return_value=(('entry', {}), '')), \
             patch('app.core.animation_clips.clip_travel_m', return_value=(0, -1)), \
             patch('app.core.animation_clips.clip_ref_height_m', return_value=1.7), \
             patch('app.core.animation_clips.clip_turn_deg', return_value=90):
            point, reason = slot_access(dict(slots=[[2, 3]], facing=0, floor_y=2),
                                       0, 'actor', {'pose_key': 'sitting'}, {'height': 170})
            self.assertEqual(reason, '')
            self.assertAlmostEqual(point['x'], 1)
            self.assertAlmostEqual(point['z'], 3)
            self.assertEqual(point['yaw'], -90)


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
    failed = []
    try:
        old_code_proof()
    except Exception:  # noqa: BLE001 — a failed proof is reported, the cases still run
        import traceback
        traceback.print_exc()
        print('FAIL [R] old-code proof', flush=True)
        failed.append('[R] old-code proof')
    result = unittest.main(exit=False).result
    if not result.wasSuccessful():
        broken = {type(test).__name__ for test, _ in result.failures + result.errors}
        failed += [{'Access': '[E] entry geometry', 'Relax': '[R] relaxed approach'}.get(n, n) for n in sorted(broken)]
    F.assert_no_external_work()
    if failed:
        print('FAILED section(s): ' + ', '.join(failed))
    raise SystemExit(1 if failed else 0)
