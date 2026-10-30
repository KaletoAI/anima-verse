#!/usr/bin/env python3
"""Review regressions using the private run fixture (paths.init before DB imports).

Usage: python scripts/smoke_prop_action_review.py
Six identical actions need one route and one profile read per offer operation.
A 50 -> 55 -> 62 effect sequence must notify old=50,new=62. Planning must
permit an independent SQLite writer; restart failure must retain its old clock.
"""
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch
import smoke_prop_action_runs as S
F, A, R = S.F, S.A, S.R
from app.core import paths
# The imported fixture already initialized this private root; make the direct
# DB-import boundary explicit for the repository storage guard as well.
paths.init(F.ROOT / "world")
from app.core import places, prop_actions, prop_action_paths as P, effect_application as E
from app.core.game_time import GameDuration


class Review(unittest.TestCase):
    tearDown = S.Runs.tearDown
    def test_offer_routes_and_profiles_once(self):
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        first = doc['actions'][0]
        doc['actions'] = [dict(deepcopy(first), id=f'rest-{i}', name=f'Rest {i}') for i in range(6)]
        F.props._write_sidecar(pid, doc)
        # Uncached independent checks are the reference for every public field.
        expected = prop_actions.offers(name)
        with patch.object(P, 'visibility_path', wraps=P.visibility_path) as routes, \
                patch.object(F.C, 'get_character_profile', wraps=F.C.get_character_profile) as profiles:
            started = time.perf_counter()
            actual = prop_actions.offers(name)
            elapsed = time.perf_counter() - started
        self.assertEqual(actual, expected)
        print(f'offers: {elapsed:.6f}s routes={routes.call_count} profiles={profiles.call_count}')
        self.assertLessEqual(routes.call_count, 1)
        self.assertLessEqual(profiles.call_count, 1)

    def test_offer_profiles_once(self):
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        first = doc['actions'][0]
        doc['actions'] = [dict(deepcopy(first), id=f'rest-{i}') for i in range(6)]
        F.props._write_sidecar(pid, doc)
        with patch.object(F.C, 'get_character_profile', wraps=F.C.get_character_profile) as profiles:
            self.assertTrue(all(row['enabled'] for row in prop_actions.offers(name)))
        self.assertEqual(profiles.call_count, 1)

    def test_pair_offer_profiles_once_per_person(self):
        name, partner, target, pid = S.authored_pair()
        available = F.actor(target['location_id'], at=(3, 5))
        doc = F.props.read_sidecar(pid)
        first = doc['actions'][0]
        doc['actions'] = [dict(deepcopy(first), id=f'share-{i}') for i in range(3)]
        F.props._write_sidecar(pid, doc)
        with patch.object(F.C, 'get_character_profile', wraps=F.C.get_character_profile) as profiles:
            rows = prop_actions.offers(name)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(t['enabled'] for row in rows for t in row['available_targets']))
        self.assertEqual(sorted(call.args[0] for call in profiles.call_args_list), sorted([name, partner, available]))

    def test_visibility_graph_reuse_and_identical_offers(self):
        from app.core import room_stand
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        first = doc['actions'][0]
        doc['actions'] = [dict(deepcopy(first), id=f'rest-{i}') for i in range(6)]
        F.props._write_sidecar(pid, doc)
        original_geometry = room_stand.room_geometry(target['location_id'], target['room_id'])
        for count in (25, 35):
            blockers = list(original_geometry[1])
            blockers.append(dict(at=[4, 6], width_m=1, depth_m=2, yaw=0))
            blockers += [dict(at=[12 + (i % 7) * 4, 12 + (i // 7) * 4],
                              width_m=1, depth_m=1, yaw=0) for i in range(count - len(blockers))]
            geometry = ([[0, 0], [45, 0], [45, 40], [0, 40]], blockers, [])
            def uncached_route(query, start, goal, geometry):
                return P.visibility_path(start, goal, *geometry)
            with patch.object(room_stand, 'room_geometry', return_value=geometry):
                # The geometry is swapped under an unchanged world: drop the
                # short offers() cache so both legs really plan.
                prop_actions.invalidate_offers_cache()
                with patch.object(F.places._GeometryQuery, 'route', uncached_route), \
                        patch.object(P._VisibilityGraph, '_build_graph', autospec=True,
                                     side_effect=P._VisibilityGraph._build_graph) as builds:
                    started = time.perf_counter()
                    expected = prop_actions.offers(name)
                    before = time.perf_counter() - started
                    old_builds = builds.call_count
                # Measure a real planning pass, not the short offers() cache.
                prop_actions.invalidate_offers_cache()
                with patch.object(P._VisibilityGraph, '_build_graph', autospec=True,
                                  side_effect=P._VisibilityGraph._build_graph) as builds:
                    started = time.perf_counter()
                    actual = prop_actions.offers(name)
                    after = time.perf_counter() - started
                self.assertEqual(actual, expected)
                self.assertTrue(all(row['enabled'] for row in actual))
                # Patching _GeometryQuery.route no longer forces a build per
                # action: the planner keeps one graph per query itself.
                self.assertEqual(old_builds, 1)
                # At most one shared build; none at all when every access is in
                # straight sight (the graph is built lazily).
                self.assertLessEqual(builds.call_count, 1)
                print(f'{count} blockers, 6 offers: uncached={before:.4f}s/{old_builds} builds cached={after:.4f}s/{builds.call_count} builds')
                # Distinct endpoints must share the static graph as well.
                query = F.places._GeometryQuery()
                with patch.object(P._VisibilityGraph, '_build_graph', autospec=True,
                                  side_effect=P._VisibilityGraph._build_graph) as builds:
                    for goal in ((8, 7), (9, 7)):
                        self.assertEqual(query.route((1, 5), goal, geometry), P.visibility_path((1, 5), goal, *geometry))
                self.assertEqual(builds.call_count, 3, 'one shared build plus two standalone reference builds')

    def test_plan_does_not_hold_sqlite_writer(self):
        name, target, _ = S.setup_run()
        original = A._plan
        def checked_plan(*args, **kwargs):
            # A second writer can enter only if planning is outside BEGIN IMMEDIATE.
            import sqlite3
            conn = sqlite3.connect(str(F.db.get_db_path()), timeout=.05)
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.rollback()
            finally:
                conn.close()
            return original(*args, **kwargs)
        with patch.object(A, '_plan', side_effect=checked_plan):
            result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)
        A.cancel(name, result['execution_id'])
        name, partner, target, _ = S.authored_pair()
        result = S.request(name, target, partner=partner)
        with patch.object(A, '_plan', side_effect=checked_plan):
            accepted = A.respond(partner, result['execution_id'], True)
        self.assertEqual(accepted['status'], 'approaching', accepted)

    def test_admission_rechecks_slot_and_position_after_planning(self):
        for mutation in ('slot', 'position'):
            name, target, _ = S.setup_run()
            other = F.actor(target['location_id'], at=(2, 5))
            original = A._plan
            def changed_after_plan(*args, **kwargs):
                plans, reason = original(*args, **kwargs)
                self.assertFalse(reason)
                if mutation == 'slot':
                    anchor = plans['actor']['entry_anchor']
                    profile = F.C.get_character_profile(other)
                    profile['place'] = dict(id=anchor['place_id'], slot=anchor['slot'], room_id=target['room_id'])
                    F.C.save_character_profile(other, profile)
                else:
                    F.C.set_character_pos(name, 2, 4)
                return plans, reason
            with patch.object(A, '_plan', side_effect=changed_after_plan):
                result = S.request(name, target)
            self.assertEqual(result['status'], 'refused', result)
            self.assertEqual(result['reason'], 'no_free_slot' if mutation == 'slot' else 'approach_target_changed')
            self.assertFalse(R.claims())

    def test_effect_aggregation_across_phases_keeps_initial_old(self):
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [dict(id='one', type='stat_delta', target='actor', when='start', stat='run_energy', amount=5),
                                       dict(id='two', type='stat_delta', target='actor', when='active', stat='run_energy', amount=7)]
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props._document_revision(doc)
        result = S.request(name, target)
        run = R.get(result['execution_id'])
        run['data']['active_game_s'] = 60
        with patch.object(E, 'notify_effects') as notify:
            A._commit(run, ('start', 'active'))
        self.assertEqual(notify.call_args.args[0][name]['changes']['run_energy'], dict(old=50, new=62))

    def test_failed_restart_profile_save_preserves_clock(self):
        name, target, _ = S.setup_run()
        result = S.request(name, target)
        run = R.get(result['execution_id'])
        run['data']['process'] = 'previous-process'
        before = deepcopy(run['data'])
        with patch.object(F.C, 'save_character_profile', return_value=False):
            with self.assertRaises(RuntimeError):
                A._clock(run, F.game_time() + GameDuration.of(seconds=100))
        self.assertEqual(run['data'], before)

    def test_recent_state_skips_decoding_old_history(self):
        name, target, _ = S.setup_run()
        result = S.request(name, target)
        A.cancel(name, result['execution_id'])
        with R.transaction() as conn:
            conn.execute("UPDATE prop_action_runs SET updated_at='2000-01-01T00:00:00+00:00' WHERE execution_id=?", (result['execution_id'],))
        with patch.object(R, '_decode', wraps=R._decode) as decode:
            self.assertFalse(A.state_for(name)['recent_results'])
        self.assertEqual(decode.call_count, 0)

    def test_effect_aggregation_keeps_initial_old(self):
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [dict(id='one', type='stat_delta', target='actor', when='start', stat='run_energy', amount=5),
                                       dict(id='two', type='stat_delta', target='actor', when='start', stat='run_energy', amount=7)]
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props._document_revision(doc)
        result = S.request(name, target)
        with patch.object(E, 'notify_effects') as notify:
            S.tick(30)
            S.tick(2)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 62)
        self.assertEqual(notify.call_args.args[0][name]['changes']['run_energy'], dict(old=50, new=62))

    def test_room_marker_without_prop_shares_the_room(self):
        # A room-level marker (source "room") carries no prop_id; a request
        # for furniture in the same room must still plan (it used to 500).
        name, target, _ = S.setup_run()
        own = places._GeometryQuery.room_places

        def with_room_marker(query, location_id, room_id):
            return own(query, location_id, room_id) + [dict(
                id='room:rug', group='ground', label='rug', capacity=1, slots=[[9.0, 9.0]],
                facing=None, y_world=0.0, root_offset=0.0, source='room', room_id=room_id, floor_y=0.0)]
        with patch.object(places._GeometryQuery, 'room_places', with_room_marker):
            result = S.request(name, target)
        self.assertEqual(result['status'], 'approaching', result)

    def test_other_action_while_seated_stands_up_and_goes(self):
        # Seated in one action, choosing another one: the offer is open, the
        # request ends the first action and the new approach departs from the
        # seat through the exit clip (no stand-up jump before it).
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        doc['actions'].append(dict(deepcopy(doc['actions'][0]), id='rest-2', name='Rest 2'))
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        directory = F.ROOT / 'clips'
        (directory / 'run-exit.fbx').write_bytes(b'private deterministic asset fixture')
        (directory / 'run-exit.json').write_text(json.dumps(dict(
            kind='run-exit', duration_s=1, loop=False,
            geometry=dict(root_motion=dict(mode='foot_lock', travel_m=[0, 2], ref_height_m=1.7)))))
        S.clips._clear_entries_cache()
        S.clips._write_world_transitions([
            {'from': 'walking', 'to': 'sitting', 'kind': 'run-enter', 'accel': 0},
            {'from': 'sitting', 'to': 'walking', 'kind': 'run-exit', 'accel': 0}])
        first = S.request(name, target)
        S.tick(30)
        S.tick(2)
        self.assertEqual(R.get(first['execution_id'])['status'], 'active')
        seat = F.C.get_character_pos(name)
        prop_actions.invalidate_offers_cache()
        rows = {row['action_id']: row for row in prop_actions.offers(name)}
        self.assertEqual((rows['rest-2']['enabled'], rows['rest-2']['reason']), (True, ''), rows['rest-2'])
        self.assertEqual(rows[target['action_id']]['reason'], 'participant_claimed')
        other = dict(target, action_id='rest-2')
        second = S.request(name, other)
        self.assertEqual(second['status'], 'approaching', second)
        self.assertEqual(R.get(first['execution_id'])['status'], 'completed')
        profile = F.C.get_character_profile(name)
        self.assertFalse(profile.get('place'))
        self.assertEqual(F.C.get_character_pos(name), seat)
        self.assertEqual(profile['journey']['execution_ref'], second['execution_id'])
        self.assertEqual(profile['journey']['exit_clip'], 'run-exit')
        self.assertEqual(profile['journey']['waypoints'][0][:2], [seat['x'], seat['z']])
        self.assertEqual({c['execution_id'] for c in R.claims()}, {second['execution_id']})
        self.assertEqual(S.request(name, other)['reason'], 'participant_claimed')

    def test_failed_replacement_stands_the_actor_up(self):
        # The plan fails after the first action has ended (no exit clip to
        # leave the seat): the actor stands up instead of keeping a place
        # nobody owns any more.
        name, target, pid = S.setup_run()
        doc = F.props.read_sidecar(pid)
        doc['actions'].append(dict(deepcopy(doc['actions'][0]), id='rest-2', name='Rest 2'))
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        first = S.request(name, target)
        S.tick(30)
        S.tick(2)
        self.assertEqual(R.get(first['execution_id'])['status'], 'active')
        second = S.request(name, dict(target, action_id='rest-2'))
        self.assertEqual((second['status'], second['reason']), ('refused', 'missing_exit_transition'), second)
        self.assertEqual(R.get(first['execution_id'])['status'], 'completed')
        self.assertFalse(F.C.get_character_profile(name).get('place'))
        self.assertFalse(R.claims())


if __name__ == '__main__':
    unittest.main()
