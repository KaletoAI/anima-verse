#!/usr/bin/env python3
"""The own avatar's motion plan in the prop-action answers (B1).

Usage: ./.venv/bin/python scripts/smoke_prop_action_motion_plan.py

Runs on the private HTTP fixture of smoke_prop_action_api (paths.init before
any DB import). The server decides and plans; the requesting client plays the
plan at once on its own clock. So the plan must be EXACTLY what the server
itself runs, and its end must be exactly where the server seats the figure.

Hand-derived expectations (contract docs/schnittstellen-3d.md, "Own motion"):
- since plan E3 Task 7 an approach walks no journey: the answer's ``motion``
  is null while it approaches (the order carries the plan), and a player's
  figure reports its own arrival (``until_active`` does it for the player);
- a seat switch to another piece (a second placement "other-device" of the
  prop at (4, 5)) with exit clip run-exit (1 s, 2 m travel): the order's
  first step is the exit (kind seat, 1.0 s) and the plan's departure_seat
  names the held seat;
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
from app.core import motion_orders as MO, prop_actions


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
    """Tick until the run left its approach. A player-controlled member
    reports its own arrival at its access (plan E3 Task 7) — the figure's
    client would, the server never walks it."""
    for _ in range(limit):
        run = R.get(execution_id)
        if run['status'] != 'approaching':
            break
        if run['phase'] != 'entry':
            order_id = run['data']['order']['order_id']
            for name in run['data'].get('reports_arrival') or ():
                access = run['data']['plans'][name]['access']
                A.arrived(name, order_id, access['x'], access['z'], 0.0, run['target']['room_id'])
        S.tick(5)
    return R.get(execution_id)


class MotionPlan(unittest.TestCase):
    tearDown = S.Runs.tearDown

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
        self.assertEqual(here['status'], 'active', here)
        self.assertNotIn('motion', here)
        profile = F.C.get_character_profile(name)
        self.assertIsNone(profile.get('journey'))
        self.assertEqual(profile['place']['execution_id'], here['execution_id'])
        anchor = R.get(here['execution_id'])['data']['plans'][name]['entry_anchor']
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
        self.assertNotIn('motion', second)
        self.assertEqual(second['order']['target']['execution_id'], second['execution_id'])
        self.assertIsNone(F.C.get_character_profile(name).get('journey'))
        run = R.get(second['execution_id'])
        exit_step = run['data']['order']['actors'][0]['sequence'][0]
        self.assertEqual((exit_step['step'], exit_step['pose_kind'], exit_step['nominal_s']), ('exit', 'seat', 1.0))
        self.assertEqual(run['data']['plans'][name]['departure_seat']['seat'], [seat['x'], seat['z']])

    def test_no_stand_up_without_a_released_place(self):
        name, target, _ = S.setup_run()
        walking = S.request(name, target)
        A.cancel(name, walking['execution_id'])
        row = next(r for r in A.state_for(name)['recent_results'] if r['execution_id'] == walking['execution_id'])
        self.assertNotIn('motion', row)
        # The walker stands where it is: a cancel row without an exit step.
        order = MO.index_get(name) or {}
        self.assertEqual(order.get('kind'), 'cancel', order)
        self.assertEqual(order['actors'][0]['sequence'], [])
        pos = F.C.get_character_pos(name)
        self.assertEqual((order['actors'][0]['stand']['x'], order['actors'][0]['stand']['z']), (pos['x'], pos['z']))
        seated = S.request(name, target)
        run = until_active(seated['execution_id'])
        before = MO.index_get(name)
        A._finish(run, 'completed', 'ended', keep_seated=name)
        row = next(r for r in A.state_for(name)['recent_results'] if r['execution_id'] == seated['execution_id'])
        self.assertNotIn('motion', row)
        self.assertIsNotNone(F.C.get_character_profile(name).get('place'))
        # Kept seated: the end publishes no new order for this member — what it
        # carries (if anything) is still the order it had before the end.
        after = MO.index_get(name)
        if after is not None:
            self.assertIsNotNone(before)
            self.assertEqual(after['order_id'], before['order_id'])
            self.assertNotEqual(after.get('kind'), 'cancel')

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
        self.assertNotIn('motion', row)
        self.assertStandUp(name, seat=(8, 5), stand=(8, 7), yaw=0)

    def assertStandUp(self, name, *, seat, stand, yaw):
        """The end's cancel order for ``name``: from the seat, exit 1.0 s
        (run-exit), standing at ``stand`` with compass ``yaw``."""
        order = MO.index_get(name) or {}
        self.assertEqual(order.get('kind'), 'cancel', order)
        actor = next(a for a in order['actors'] if a['name'] == name)
        self.assertEqual((actor['start']['x'], actor['start']['z']), seat)
        self.assertEqual([(s['step'], s['pose_kind'], s['nominal_s']) for s in actor['sequence']],
                         [('exit', 'seat', 1.0)])
        self.assertEqual((actor['stand']['x'], actor['stand']['z']), stand)
        self.assertAlmostEqual(actor['stand']['yaw'], yaw)

    def test_server_end_persists_departure(self):
        # By hand: the fixture exit travels 2 m forward from (8,5), yaw 0,
        # so stand is (8,7); run-exit lasts 1 second.
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        first = S.request(name, target)
        run = until_active(first['execution_id'])
        stale = deepcopy(run)
        S.A._finish(run, 'cancelled', 'interaction_avatar')
        stand = F.C.get_character_pos(name)
        self.assertEqual([stand['x'], stand['z']], [8, 7])
        row = next(r for r in S.A.state_for(name)['recent_results'] if r['execution_id'] == first['execution_id'])
        self.assertNotIn('motion', row)
        saved = R.get(first['execution_id'])
        self.assertFalse(saved['data']['cleanup_pending'])
        self.assertNotIn('exit_motions', saved['data'])
        self.assertStandUp(name, seat=(8, 5), stand=(8, 7), yaw=0)
        cancel_id = MO.index_get(name)['order_id']
        S.A._cleanup(saved)  # A retry cannot stand a released place up again.
        S.A._cleanup(stale)  # Neither can a snapshot taken before the finish.
        stand = F.C.get_character_pos(name)
        self.assertEqual([stand['x'], stand['z']], [8, 7])
        self.assertEqual(MO.index_get(name)['order_id'], cancel_id)

    def test_turning_exit_persists_heading(self):
        # Facing 0 plus turn 90 -> stored pi/2 radians, cancel stand yaw 90.
        # Travel remains rotated by the initial facing: (8,5) -> (8,7).
        name, target, _ = S.setup_run()
        exit_clip_fixture()
        first = S.request(name, target)
        until_active(first['execution_id'])
        with patch('app.core.animation_clips.clip_turn_deg', return_value=90):
            A.cancel(name, first['execution_id'])
        self.assertStandUp(name, seat=(8, 5), stand=(8, 7), yaw=90)
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
        self.assertNotIn('motion', answer.json())
        self.assertStandUp(name, seat=(seat['x'], seat['z']), stand=(stand['x'], stand['z']), yaw=0)
        # Cancelling a walk stands the walker where it is: no exit to play.
        again = player.post('/play/prop-actions/request', json=API.payload(target)).json()
        self.assertEqual(again['status'], 'approaching', again)
        stopped = player.post('/play/prop-actions/cancel', json={'execution_id': again['execution_id']}).json()
        self.assertNotIn('motion', stopped)
        self.assertEqual((MO.index_get(name) or {})['actors'][0]['sequence'], [])


if __name__ == '__main__':
    unittest.main()
