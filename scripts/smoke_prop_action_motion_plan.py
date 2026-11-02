#!/usr/bin/env python3
"""The own avatar's motion plan in the prop-action answers (B1).

Usage: ./.venv/bin/python scripts/smoke_prop_action_motion_plan.py

Runs on the private HTTP fixture of smoke_prop_action_api (paths.init before
any DB import). The server decides and plans; the requesting client plays the
plan at once on its own clock. So the plan must be EXACTLY what the server
itself runs, and its end must be exactly where the server seats the figure.

Hand-derived expectations (contract docs/schnittstellen-3d.md, "Own motion"):
- waypoints = the persisted journey polyline (x, z), seat leg included;
- a walked segment's real pace = travel speed x game factor (factor 2 here:
  the baked t_cum is length / speed, so length / t x 2 = 2 x speed); the
  zero-time seat leg has no pace (null);
- access = the plan's floor access; anchor = the plan's entry anchor with
  y lowered by root_offset (the same convention as prop_action_entry);
- the entry kind/pose = what the server plays at arrival; duration_s = the
  clip's own length in real seconds;
- after activation the profile place is (anchor.place_id, anchor.slot) and
  the position is anchor (x, z) — one seat point, no second computation;
- a seat switch to another piece (a second placement "other-device" of the
  prop at (4, 5)) with exit clip run-exit (1 s, 2 m travel): departure =
  {seat: the held seat, stand: waypoint 2, exit_clip run-exit, exit_s 1.0};
  a switch on the SAME piece ("rest-2") begins in place: status active,
  motion null, no journey, the place on the same piece and the position its
  anchor (fails on a1c5af11: "approaching" with a departure);
- Server-side end: run-exit travels 2 m forward from seat (8,5), yaw 0,
  yielding stand (8,7); its duration is 1 second. The terminal state row and
  a later cancel answer both retain that exact departure.
- cancel while seated: motion = {seat: before, stand: where the server put
  the figure, exit_clip run-exit, exit_s 1.0}; cancel while walking: null.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest.mock import patch
from copy import deepcopy
import json
import math
import unittest

import smoke_prop_action_api as API
S, F, A, R = API.S, API.F, API.A, API.R
from app.core import paths
# The imported fixture already initialized this private root; make the direct
# DB-import boundary explicit for the repository storage guard as well.
paths.init(F.ROOT / "world")
from app.core import prop_actions, travel_engine as T


def exit_clip_fixture():
    directory = F.ROOT / 'clips'
    (directory / 'run-exit.fbx').write_bytes(b'private deterministic asset fixture')
    (directory / 'run-exit.json').write_text(json.dumps(dict(
        kind='run-exit', duration_s=1, loop=False,
        geometry=dict(root_motion=dict(mode='foot_lock', travel_m=[0, 2], ref_height_m=1.7)))))
    S.clips._clear_entries_cache()
    S.clips._write_world_transitions([
        {'from': 'walking', 'to': 'sitting', 'kind': 'run-enter', 'accel': 0},
        {'from': 'sitting', 'to': 'walking', 'kind': 'run-exit', 'accel': 0}])


def second_action(pid, target):
    doc = F.props.read_sidecar(pid)
    doc['actions'].append(dict(deepcopy(doc['actions'][0]), id='rest-2', name='Rest 2'))
    F.props._write_sidecar(pid, doc)
    target['definition_revision'] = F.props.get_prop(pid)['revision']


def until_active(execution_id, limit=12):
    for _ in range(limit):
        if R.get(execution_id)['status'] != 'approaching':
            break
        S.tick(5)
    return R.get(execution_id)


class MotionPlan(unittest.TestCase):
    tearDown = S.Runs.tearDown

    def test_request_answer_carries_the_plan_the_server_walks(self):
        name, target, _ = S.setup_run()
        F.set_game_factor(2)
        player = API.client(name)
        answer = player.post('/play/prop-actions/request', json=API.payload(target))
        self.assertEqual(answer.status_code, 200, answer.text)
        result = answer.json()
        self.assertEqual(result['status'], 'approaching', result)
        motion = result['motion']
        run = R.get(result['execution_id'])
        journey = F.C.get_character_profile(name)['journey']
        plan = run['data']['plans']['actor']
        self.assertEqual(motion['execution_id'], result['execution_id'])
        self.assertEqual(motion['journey_id'], journey['journey_id'])
        self.assertEqual(motion['room_id'], target['room_id'])
        self.assertEqual(motion['waypoints'], [[round(p[0], 3), round(p[1], 3)] for p in journey['waypoints']])
        self.assertIsNone(motion['departure'])
        speed = T.get_travel_speed_m_s()
        self.assertEqual(len(motion['paces_m_s_real']), len(motion['waypoints']) - 1)
        for pace, a, b in zip(motion['paces_m_s_real'], journey['waypoints'], journey['waypoints'][1:]):
            if math.dist(a[:2], b[:2]) > 0:
                self.assertAlmostEqual(pace, speed * 2, places=3)
        self.assertEqual(motion['access'], {k: float(plan['access'][k]) for k in ('x', 'y', 'z', 'yaw')})
        anchor = plan['entry_anchor']
        offset = float(anchor.get('root_offset', 0))
        self.assertEqual(motion['anchor'], dict(
            x=float(anchor['x']), y=float(anchor['y']) - offset, z=float(anchor['z']),
            yaw=float(anchor.get('yaw') or 0), root_offset=offset,
            place_id=anchor['place_id'], slot=anchor['slot']))
        # The own state row repeats it (a pair initiator learns its plan here).
        state = player.get('/play/prop-actions/state').json()
        self.assertEqual(state['current'][0]['motion'], motion)
        # The entry the server plays at arrival is the one announced.
        S.tick(30)
        run = R.get(result['execution_id'])
        self.assertEqual(run['phase'], 'entry', run)
        spec = run['data']['entries'][name]
        self.assertEqual((motion['entry']['kind'], motion['entry']['pose_key']), (spec['kind'], spec['pose_key']))
        self.assertTrue(spec['kind'])
        meta = S.clips.clip_meta(spec['kind'])
        self.assertEqual(motion['entry']['duration_s'], round(float(meta['duration_s']), 3))
        self.assertGreater(motion['entry']['duration_s'], 0)
        self.assertTrue(any(p is not None for p in motion['paces_m_s_real']))
        run = until_active(result['execution_id'])
        self.assertEqual(run['status'], 'active', run)
        # One seat point: the server seats the figure exactly on the anchor.
        profile = F.C.get_character_profile(name)
        self.assertEqual((profile['place']['id'], profile['place']['slot']),
                         (motion['anchor']['place_id'], motion['anchor']['slot']))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (motion['anchor']['x'], motion['anchor']['z']))
        self.assertIsNone(player.get('/play/prop-actions/state').json()['current'][0]['motion'])

    def test_seat_switch_plan_departs_from_the_seat(self):
        name, target, pid = S.setup_run()
        second_action(pid, target)
        exit_clip_fixture()
        player = API.client(name)
        first = player.post('/play/prop-actions/request', json=API.payload(target)).json()
        self.assertEqual(until_active(first['execution_id'])['status'], 'active')
        seat = F.C.get_character_pos(name)
        # Same piece: in place.
        prop_actions.invalidate_offers_cache()
        here = player.post('/play/prop-actions/request', json=API.payload(dict(target, action_id='rest-2'))).json()
        self.assertEqual((here['status'], here['motion']), ('active', None), here)
        profile = F.C.get_character_profile(name)
        self.assertIsNone(profile.get('journey'))
        self.assertEqual(profile['place']['execution_id'], here['execution_id'])
        anchor = R.get(here['execution_id'])['data']['plans']['actor']['entry_anchor']
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos['x'], pos['z']), (anchor['x'], anchor['z']))
        seat = pos
        # Another piece: stand up from the seat and walk.
        location = F.W.get_location_by_id(target['location_id'])
        room = next(room for room in location['rooms'] if room['id'] == target['room_id'])
        room['layout']['props'].append(dict(id='other-device', prop_id=pid, at=[4, 5], yaw=0))
        F.W.upsert_location(location, sync_world=True)
        F.places.invalidate()
        prop_actions.invalidate_offers_cache()
        second = player.post('/play/prop-actions/request',
                             json=API.payload(dict(target, placement_id='other-device'))).json()
        self.assertEqual(second['status'], 'approaching', second)
        motion = second['motion']
        journey = F.C.get_character_profile(name)['journey']
        self.assertEqual(motion['departure'], dict(
            seat=[seat['x'], seat['z']], stand=list(journey['waypoints'][1][:2]),
            exit_clip='run-exit', exit_s=1.0))
        self.assertEqual(motion['waypoints'][0], [round(seat['x'], 3), round(seat['z'], 3)])
        # An observer in the room sees the same departure: the seat leg and the
        # escape cross the furniture being left, which the travel engine allows
        # (fails on 9862d368: withdrawn, the figure stood up on the terrain).
        from app.core.world_ops import _local_prop_approach
        observer = F.actor(target['location_id'], at=(2, 5))
        local = _local_prop_approach(name, observer, F.C.get_character_profile(name),
                                     F.C.get_character_profile(observer), journey, {name},
                                     F.game_time(), 0, 1)
        self.assertIsNotNone(local)
        self.assertEqual(local['waypoints'][0], [seat['x'], seat['z']])
        self.assertEqual(local['floor_y'], journey['floor_y'])

    def test_terminal_motion_is_null_without_a_released_place(self):
        name, target, _ = S.setup_run()
        walking = S.request(name, target)
        self.assertIsNone(A.cancel_with_motion(name, walking['execution_id'])['motion'])
        row = next(r for r in A.state_for(name)['recent_results'] if r['execution_id'] == walking['execution_id'])
        self.assertIsNone(row['motion'])
        seated = S.request(name, target)
        run = until_active(seated['execution_id'])
        A._finish(run, 'completed', 'ended', keep_seated=name)
        row = next(r for r in A.state_for(name)['recent_results'] if r['execution_id'] == seated['execution_id'])
        self.assertIsNone(row['motion'])
        self.assertIsNotNone(F.C.get_character_profile(name).get('place'))
        self.assertIsNone(A.cancel_with_motion(name, seated['execution_id'])['motion'])

    def test_terminal_poll_waits_for_departure_cleanup(self):
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        # Keep a second participant row: an open multi-row SQLite cursor
        # would otherwise pin the pre-cleanup snapshot across the run lock.
        previous = S.request(name, target)
        A.cancel(name, previous['execution_id'])
        first = S.request(name, target)
        run = until_active(first['execution_id'])
        entered, proceed, reading = Event(), Event(), Event()
        cleanup = A._cleanup
        def delayed_cleanup(*args, **kwargs):
            entered.set()
            if not proceed.wait(5):
                raise AssertionError('cleanup was never released')
            return cleanup(*args, **kwargs)
        def read_state():
            reading.set()
            return A.state_for(name)
        with patch.object(A, '_cleanup', delayed_cleanup), ThreadPoolExecutor(max_workers=2) as pool:
            finish = pool.submit(A._finish, run, 'cancelled', 'interaction_avatar')
            try:
                self.assertTrue(entered.wait(5))
                state = pool.submit(read_state)
                self.assertTrue(reading.wait(5))
                with self.assertRaises(TimeoutError):
                    state.result(timeout=.05)
            finally:
                proceed.set()
            finish.result(timeout=5)
            row = next(r for r in state.result(timeout=5)['recent_results']
                       if r['execution_id'] == first['execution_id'])
        self.assertEqual(row['motion'], dict(seat=[8, 5], stand=[8, 7], exit_clip='run-exit', exit_s=1.0, stand_yaw_deg=0))

    def test_server_end_persists_departure(self):
        # By hand: the fixture exit travels 2 m forward from (8,5), yaw 0,
        # so stand is (8,7); run-exit lasts 1 second.
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        first = S.request(name, target)
        run = until_active(first['execution_id'])
        stale = deepcopy(run)
        S.A._finish(run, 'cancelled', 'interaction_avatar')
        expected = dict(seat=[8, 5], stand=[8, 7], exit_clip='run-exit', exit_s=1.0, stand_yaw_deg=0)
        stand = F.C.get_character_pos(name)
        self.assertEqual([stand['x'], stand['z']], expected['stand'])
        row = next(r for r in S.A.state_for(name)['recent_results'] if r['execution_id'] == first['execution_id'])
        self.assertEqual(row['motion'], expected)
        saved = R.get(first['execution_id'])
        self.assertFalse(saved['data']['cleanup_pending'])
        self.assertEqual(saved['data']['exit_motions'][name], expected)
        S.A._cleanup(saved)  # A retry cannot replace a released place's motion.
        S.A._cleanup(stale)  # Neither can a snapshot taken before the finish.
        self.assertEqual(S.A.cancel_with_motion(name, first['execution_id'])['motion'], expected)

    def test_turning_exit_persists_heading(self):
        # Facing 0 plus turn 90 -> stored pi/2 radians, motion heading 90.
        # Travel remains rotated by the initial facing: (8,5) -> (8,7).
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        first = S.request(name, target)
        until_active(first['execution_id'])
        with patch('app.core.animation_clips.clip_turn_deg', return_value=90):
            answer = A.cancel_with_motion(name, first['execution_id'])
        self.assertEqual(answer['motion']['stand'], [8, 7])
        self.assertAlmostEqual(answer['motion']['stand_yaw_deg'], 90)
        self.assertAlmostEqual(F.C.get_avatar_sync_snapshot(name)['yaw'], math.pi / 2)

    def test_cancel_while_seated_returns_the_stand_up(self):
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        player = API.client(name)
        first = player.post('/play/prop-actions/request', json=API.payload(target)).json()
        self.assertEqual(until_active(first['execution_id'])['status'], 'active')
        seat = F.C.get_character_pos(name)
        answer = player.post('/play/prop-actions/cancel', json={'execution_id': first['execution_id']})
        self.assertEqual(answer.status_code, 200, answer.text)
        stand = F.C.get_character_pos(name)
        self.assertNotEqual((stand['x'], stand['z']), (seat['x'], seat['z']))
        self.assertEqual(answer.json()['motion'], dict(
            seat=[seat['x'], seat['z']], stand=[stand['x'], stand['z']], exit_clip='run-exit', exit_s=1.0, stand_yaw_deg=0))
        # Cancelling a walk moves nobody: no stand-up to play.
        again = player.post('/play/prop-actions/request', json=API.payload(target)).json()
        self.assertEqual(again['status'], 'approaching', again)
        stopped = player.post('/play/prop-actions/cancel', json={'execution_id': again['execution_id']}).json()
        self.assertIsNone(stopped['motion'])


if __name__ == '__main__':
    unittest.main()
