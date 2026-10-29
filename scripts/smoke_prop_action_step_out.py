#!/usr/bin/env python3
"""Regression checks for standing keepout escape and truthful offer reasons.

Usage: ./.venv/bin/python scripts/smoke_prop_action_step_out.py

Expected values BY HAND: the fixture chair is 1 x 1 m at (8, 5). With
BODY_R_M=.3 its closed keepout is [7.2, 8.8] x [4.2, 5.8]. From (8.3, 5),
the first free .05 m ring is radius .55 (radius .50 touches the boundary).
Angle zero wins, so the sampled nearest free point is (8.85, 5). The route
must start (8.3, 5), (8.85, 5); its first leg is .55 m and contributes
.55 / speed seconds. At .1 m/s, one and two seconds give x=8.4 and
8.5 respectively, both still inside the keepout. A 6 x 6 m obstruction centred on the start extends
3.3 m in every axis, so no point within 1.5 m is free. A U room with a
.1 m notch has a free point across the wall within 1.5 m, but no legal
segment there; other reachable free points are more than 1.5 m away.
A seated actor still exits (8, 5) -> (8, 6), and plans from (8, 6).
For two markers (seat then incompatible lie), the giant obstruction makes
the compatible seat fail with start_not_walkable: the lie marker must not
replace it with incompatible_pose_marker. These are geometry expectations,
not recorded snapshots. All storage is private, initialized by the imported
path fixture before world modules. Old-code proofs pin commit 50aed47a.
"""
import ast
import math
import subprocess
import unittest
from unittest.mock import patch

import smoke_prop_action_runs as S
F, A = S.F, S.A
from app.core import prop_actions as P


def blocked_query(name, target):
    query = F.places._GeometryQuery()
    query.room_geometry = lambda *args: (F.SQUARE, [dict(at=[8, 5], width_m=6, depth_m=6)], [])
    return query


def two_markers():
    name, target, pid = S.setup_run()
    doc = F.props.read_sidecar(pid)
    doc['model_variants'][0]['markers'].append(dict(id='other', group='lie', at=[.5, .5, .5], facing=0))
    F.props._write_sidecar(pid, doc)
    target['definition_revision'] = F.props.get_prop(pid)['revision']
    F.C.set_character_pos(name, 8.3, 5)
    return name, target, pid


class StepOut(unittest.TestCase):
    def test_a_standing_step_out(self):
        name, target, _ = S.setup_run()
        F.C.set_character_pos(name, 8.3, 5)
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        self.assertEqual(plan['waypoints'][:2], [[8.3, 5], [8.85, 5]])
        self.assertTrue(all(a != b for a, b in zip(plan['waypoints'], plan['waypoints'][1:])))

    def test_b_no_escape_within_limit(self):
        name, target, _ = S.setup_run()
        F.C.set_character_pos(name, 8, 5)
        self.assertEqual(F.N.plan_approach(name, target, 'actor', _query=blocked_query(name, target))['reason'], 'start_not_walkable')

    def test_b_wall_prevents_escape(self):
        name, target, _ = S.setup_run()
        F.C.set_character_pos(name, 3.9, 2)
        # Left arm ends at x=4; right arm starts x=4.1; joined only at z>=4.
        poly = [(0, 0), (4, 0), (4, 4), (4.1, 4), (4.1, 0), (8, 0), (8, 8), (0, 8)]
        query = F.places._GeometryQuery()
        query.room_geometry = lambda *args: (poly, [dict(at=[2, 2], width_m=4, depth_m=4)], [])
        self.assertTrue(F.N._Space(*query.room_geometry()).free((4.5, 2)))
        self.assertEqual(F.N.plan_approach(name, target, 'actor', _query=query)['reason'], 'start_not_walkable')

    def test_c_seated_unchanged(self):
        name, target, _ = S.setup_run()
        F.Ownership.seat_actor(self, name)
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        self.assertEqual(plan['departure_seat'], [8, 5])
        self.assertEqual(plan['waypoints'][0], [8, 6])
        self.assertFalse(plan.get('step_out'))

    def test_d_specific_marker_reason_in_check_and_offers(self):
        name, target, _ = two_markers()
        query = blocked_query(name, target)
        identity = {k: target[k] for k in ('location_id', 'room_id', 'placement_id', 'variant_uid')}
        checked = A.check(name, identity, target['action_id'], target['definition_revision'], _query=query)
        self.assertEqual(checked, dict(enabled=False, reason='start_not_walkable'))
        with patch.object(F.places, '_GeometryQuery', return_value=query):
            self.assertEqual(P.offers(name)[0]['reason'], 'start_not_walkable')

    def test_journey_includes_step_out_and_arrives(self):
        name, target, _ = S.setup_run()
        F.C.set_character_pos(name, 8.3, 5)
        plan = F.N.plan_approach(name, target, 'actor')
        with patch.object(F.E, "get_travel_speed_m_s", return_value=.1):
            result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        journey = F.E.get_journey(name)
        self.assertEqual([p[:2] for p in journey['waypoints']], plan['waypoints'])
        self.assertAlmostEqual(journey['waypoints'][1][2], .55 / journey['speed_m_s'])
        length = sum(math.dist(a, b) for a, b in zip(plan['waypoints'], plan['waypoints'][1:]))
        self.assertAlmostEqual(journey['waypoints'][-1][2], length / journey['speed_m_s'])
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name), F.C.get_character_profile(name))
        self.assertEqual(F.C.get_character_pos(name)['x'], 8.4)
        # A fresh process/cache miss must revalidate from inside the first leg.
        F.E._approach_validation_cache.clear()
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertEqual(F.C.get_character_pos(name)['x'], 8.5)
        F.set_game_time(F.game_time() + F.GameDuration.of(minutes=1))
        F.E.advance_all_journeys()
        self.assertIsNone(F.E.get_journey(name))
        self.assertEqual(S.R.get(result['execution_id'])['phase'], 'entry')

    def test_offer_label(self):
        name, _, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        doc.update(name='Chair', name_de='Stuhl')
        F.props._write_sidecar(pid, doc)
        self.assertEqual(P.offers(name)[0]['prop_label'], 'Chair')
        self.assertEqual(P.offers(name, lang='de')[0]['prop_label'], 'Stuhl')
        from app.routes import prop_actions as routes
        with patch.object(routes, '_avatar', return_value=name):
            self.assertEqual(routes.offers(user={})[0]['prop_label'], 'Stuhl')
        doc['name'] = ''
        F.props._write_sidecar(pid, doc)
        self.assertEqual(P.offers(name)[0]['prop_label'], pid)


def old_function(path, name, namespace):
    source = subprocess.check_output(['git', 'show', '50aed47a:' + path], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
    return scope[name]


def old_code_proof():
    old_path = old_function('app/core/prop_action_paths.py', '_plan_approach', vars(F.N))
    old_plan = old_function('app/core/prop_action_engine.py', '_plan', vars(A))
    name, target, _ = S.setup_run()
    F.C.set_character_pos(name, 8.3, 5)
    with patch.object(F.N, '_plan_approach', old_path):
        observed = F.N.plan_approach(name, target, 'actor')
        assert observed['reason'] == 'start_not_walkable', observed
    name, target, _ = two_markers()
    with patch.object(A, '_plan', old_plan):
        observed = A.check(name, {k: target[k] for k in ('location_id', 'room_id', 'placement_id', 'variant_uid')},
                           target['action_id'], target['definition_revision'], _query=blocked_query(name, target))
        assert observed['reason'] == 'incompatible_pose_marker', observed
    print('50aed47a regression proof: (a) refuses start_not_walkable; (d) masks it with incompatible_pose_marker', flush=True)


if __name__ == '__main__':
    old_code_proof()
    result = unittest.main(exit=False).result
    F.assert_no_external_work()
    raise SystemExit(0 if result.wasSuccessful() else 1)
