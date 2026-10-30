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
A shorter exit clip (travel 0.5 m) sets the seated actor down at (8, 5.5),
INSIDE its own chair's keepout (z <= 5.8): with that chair exempt the point
is free, so it walks on to the point a plain stand-up picks there
(room_stand.pick_stand, 0.25 m grid, body radius .3 around the chair): the
grid points (8, 5.75) and (7.75/8.25, 5.75) lie in [7.2, 8.8] x [4.2, 5.8],
so the nearest free one is (8, 6.0), 0.5 m away ((7.75, 6.0) is .559 m).
Waypoints: seat (8, 5), stand (8, 5.5), escape (8, 6.0). At .1 m/s the
escape leg is 5 s; one and two seconds in the figure is at (8, 5.6) and
(8, 5.7), still inside the keepout, and the journey must go on. A
.4 x .4 m box at (8, 5.8) has the keepout [7.5, 8.5] x [5.3, 6.3], which
holds (8, 5.5) with the chair exempt too, so that seat still answers
start_not_walkable.
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
# The reused fixture has already initialized this private storage root.
F.paths.init(F.ROOT / "world")
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

    def short_exit(self, name):
        from app.core import animation_clips as clips
        before = clips.world_transitions()
        F.Ownership.seat_actor(self, name)
        # seat_actor's world layer holds only its exit; keep the entry rules.
        clips._write_world_transitions(before + clips.world_transitions())
        (F.ROOT / "clips" / "path-rise.json").write_text(S.json.dumps({
            "kind": "path-rise", "duration_s": 2, "loop": False,
            "geometry": {"root_motion": {"mode": "foot_lock", "travel_m": [0, .5], "ref_height_m": 1.7}}}))
        clips._clear_entries_cache()

    def test_c2_seated_stand_inside_own_keepout_steps_out(self):
        name, target, _ = S.setup_run()
        self.short_exit(name)
        plan = F.N.plan_approach(name, target, 'actor')
        self.assertEqual(plan['status'], 'ok', plan)
        self.assertEqual(plan['departure_seat'], [8, 5])
        self.assertEqual(plan['step_out'], [8, 6.0])
        self.assertEqual(plan['waypoints'][0], [8, 5.5])
        self.assertEqual(plan['waypoints'][1], plan['step_out'])

    def test_c3_seated_stand_inside_other_keepout_blocked(self):
        name, target, _ = S.setup_run()
        self.short_exit(name)
        query = F.places._GeometryQuery()
        real = query.room_geometry
        def geometry(*args):
            polygon, blockers, zones = real(*args)
            return polygon, blockers + [dict(at=[8, 5.8], width_m=.4, depth_m=.4)], zones
        query.room_geometry = geometry
        self.assertEqual(F.N.plan_approach(name, target, 'actor', _query=query)['reason'], 'start_not_walkable')

    def test_c4_seated_step_out_journey_survives_revalidation(self):
        # Legs: seat -> stand is the zero-time exit leg (seg 0), stand ->
        # escape the walk out of the chair's keepout (seg 1).
        name, target, _ = S.setup_run()
        self.short_exit(name)
        with patch.object(F.E, "get_travel_speed_m_s", return_value=.1):
            result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        journey = F.E.get_journey(name)
        self.assertEqual([p[:2] for p in journey['waypoints'][:2]], [[8, 5], [8, 5.5]])
        lead = (F.GameTime.parse(journey['started_at_game']) - F.game_time()).total_seconds
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=lead + 1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name), F.C.get_character_profile(name).get('last_journey_result'))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (8, 5.6))
        F.E._approach_validation_cache.clear()
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=1))
        F.E.advance_all_journeys()
        self.assertIsNotNone(F.E.get_journey(name), F.C.get_character_profile(name).get('last_journey_result'))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (8, 5.7))

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
        # The approach starts after a poll lead (travel_engine._approach_start);
        # the legs count from that start.
        lead = (F.GameTime.parse(journey['started_at_game']) - F.game_time()).total_seconds
        F.set_game_time(F.game_time() + F.GameDuration.of(seconds=lead + 1))
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
    # The old _plan predates the replaces argument check() now passes.
    with patch.object(A, '_plan', lambda run, *, replaces='', **kw: old_plan(run, **kw)):
        observed = A.check(name, {k: target[k] for k in ('location_id', 'room_id', 'placement_id', 'variant_uid')},
                           target['action_id'], target['definition_revision'], _query=blocked_query(name, target))
        assert observed['reason'] == 'incompatible_pose_marker', observed
    print('50aed47a regression proof: (a) refuses start_not_walkable; (d) masks it with incompatible_pose_marker', flush=True)


if __name__ == '__main__':
    old_code_proof()
    result = unittest.main(exit=False).result
    F.assert_no_external_work()
    raise SystemExit(0 if result.wasSuccessful() else 1)
