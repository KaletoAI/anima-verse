#!/usr/bin/env python3
"""Real private HTTP, rendered prompts, streaming tools and executor acceptance.

Controller: ./.venv/bin/python scripts/smoke_prop_action_api.py
Non-test scenario: --api-scenario-dir /tmp/prop-api-unused-directory
The scenario starts only its private minimal loopback HTTP app, not app.server.
"""
import argparse
import asyncio
from contextlib import contextmanager, ExitStack
import shutil
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

OPTIONS = argparse.ArgumentParser(add_help=False)
OPTIONS.add_argument('--api-scenario-dir', type=Path)
OPTIONS.add_argument('--api-scenario-worker', action='store_true')
ARGS, REST = OPTIONS.parse_known_args()
sys.argv = [sys.argv[0], *REST]
if ARGS.api_scenario_dir:
    root = ARGS.api_scenario_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / '.prop-action-scenario').write_text('Task6 private HTTP/prompt scenario\n')
    subprocess.run([sys.executable, __file__, '--api-scenario-worker'], check=True,
                   env=dict(os.environ, PROP_ACTION_SMOKE_RESUME_ROOT=str(root)))
    print(root / 'api-prompt-scenario.json')
    raise SystemExit(0)

import smoke_prop_action_runs as S
F, A, R = S.F, S.A, S.R
from app.core import prop_actions as P, auth_dependency, sessions, users, config, llm_router
from app.core import prompt_templates as templates, template_overrides
from app.core.dependencies import get_skill_manager
from app.routes import prop_actions as routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

for folder in ('prompt_filters', 'stats', 'rules', 'languages'):
    destination = S.SHARED / folder
    if not destination.exists():
        shutil.copytree(S.ORIGINAL_SHARED / folder, destination)
from app.core import prompt_filters
prompt_filters._SHARED_FILE = S.SHARED / 'prompt_filters' / 'filters.json'
prompt_filters.invalidate_filter_snapshot()
# Entire shipped catalogs/templates were privately copied by S before imports.
# The real renderer/overlay loader now reads that private complete template tree.
templates._TEMPLATE_DIR = S.SHARED / 'templates' / 'llm'
templates._env = templates._build_env()
templates.clear_caches()
settings = json.loads(F.WORLD_CONFIG.read_text())
settings['packages'] = {'enabled': 'set_pose,interact'}
F.WORLD_CONFIG.write_text(json.dumps(settings))
config.load(F.WORLD_CONFIG)
from app.plugins import loader
loader._activation_enabled_ids = None
loader.discover_packages(force=True)
from app.core import agent_loop
RESPOND_REQUESTS = []
agent_loop.get_agent_loop = lambda: SimpleNamespace(
    bump_respond=lambda *args, **kwargs: RESPOND_REQUESTS.append((args, kwargs)))


def forbidden_model(*args, **kwargs):
    F.EXTERNAL_CALLS.append('unexpected external model')
    raise AssertionError('unexpected external model call')


llm_router.llm_call = forbidden_model


def app():
    instance = FastAPI()
    instance.middleware('http')(auth_dependency.auth_gate_middleware)
    instance.middleware('http')(auth_dependency.user_context_middleware)
    instance.include_router(routes.router)
    from app.routes.play import router as play_router
    instance.include_router(play_router)
    return instance


def login(name, role='user'):
    uid = users.create_user('api-' + os.urandom(6).hex(), 'private-fixture-only',
                            role=role, allowed_characters=[name])
    users.update_user(uid, settings={'active_character': name})
    return sessions.create_session(uid)


def client(name, role='user'):
    result = TestClient(app())
    result.cookies.set(sessions.SESSION_COOKIE_NAME, login(name, role))
    return result


def payload(target, **extra):
    return dict(target={k: target[k] for k in A._TARGET}, action_id=target['action_id'],
                revision=target['definition_revision'], **extra)


def snapshot():
    # SQLite logical snapshot plus every world/instance file except DB journals.
    database = tuple(F.db.get_connection().iterdump())
    files = {str(p.relative_to(F.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for folder in (F.ROOT / 'world', F.ROOT / 'instance') for p in folder.rglob('*')
             if p.is_file() and p.name not in ('world.db', 'world.db-wal', 'world.db-shm')}
    return database, files


@contextmanager
def pure_tripwires():
    # Unlike the old geometry fixture, NEVER mock a successful scene/no-op door.
    # These traps fail on the exact production laziness boundaries instead.
    def forbidden(*args, **kwargs):
        F.EXTERNAL_CALLS.append('read-only endpoint attempted media mutation')
        raise AssertionError('read-only endpoint attempted media mutation')
    from app.core import door_models, location_model3d
    with ExitStack() as stack:
        for owner, attr in ((F.props, '_ensure_bbox'), (F.props, 'request_low_tier'),
                            (door_models, 'ensure_door_model'), (door_models, 'ensure_window_model'),
                            (location_model3d, 'request_low_tier'), (location_model3d, 'request_surface')):
            stack.enter_context(patch.object(owner, attr, side_effect=forbidden))
        yield


def rendered(name):
    from app.core.thought_context import build_thought_context
    from app.routes.chat import _build_chat_prompt
    from app.core.npc_actions import prompt_vars
    context = build_thought_context(name)
    thought = templates.render('chat/agent_thought.md', **context)
    in_chat = templates.render('chat/agent_thought_in_chat.md', **context)
    chat = _build_chat_prompt(name, '', '', tools_enabled=True,
                              agent_config=F.C.get_character_config(name), skip_partner=True)
    system, user = templates.render_task('npc_action', **prompt_vars(name))
    return {'thought': thought, 'thought_in_chat': in_chat, 'chat': chat.system + '\n' + chat.moment,
            'npc_action': system + '\n' + user}


def offered_rows(prompt):
    section = prompt.split('<prop_actions_contract>', 1)[1].split('</prop_actions_contract>', 1)[0]
    return json.loads(section.split('offers=', 1)[1].split('\nown_state=', 1)[0])


async def streamed_tool(name, offered):
    """Captured external model output; actual parser, skill gate and execution."""
    from app.core.streaming import StreamingAgent
    from app.core.tool_formats import find_tool_calls
    manager = get_skill_manager()
    tools = {tool.name: tool.func for tool in manager.get_agent_tools(name)}
    skill = manager.get_skill('prop_action')
    if not skill or skill.name not in tools:
        raise AssertionError('real loader did not expose prop_action capability')
    request = dict(operation='request', action_id=offered['action_id'],
                   revision=offered['definition_revision'], target=offered['target'])
    captured = '<tool name="' + skill.name + '">' + json.dumps(request) + '</tool>'
    matches = find_tool_calls('tag', captured, tools)
    if len(matches) != 1:
        raise AssertionError(('captured actual tool output was not parsed', matches))
    agent = StreamingAgent(llm=None, tool_format='tag', tools_dict=tools, agent_name=name)
    results, deferred = [], []
    events = [event async for event in agent._execute_tools(matches, results, deferred)]
    if deferred or len(results) != 1:
        raise AssertionError((deferred, results))
    outcome = json.loads(results[0][1])
    if outcome['status'] != 'approaching':
        raise AssertionError(outcome)
    from app.routes.chat import _extract_activity, _extract_context_from_last_chat
    narrative = 'Walks toward the coffee station. **I do standing: waits for coffee**'
    _extract_activity(name, narrative)
    calls = []
    def captured_extraction(**kwargs):
        if kwargs.get('task') != 'extraction_chat_state':
            return forbidden_model(**kwargs)
        calls.append(kwargs)
        return SimpleNamespace(content='{"pose":"standing","detail":"waits for coffee","removed":[],"stats":{}}')
    with patch.object(llm_router, 'llm_call', side_effect=captured_extraction):
        _extract_context_from_last_chat(name, [{'role': 'assistant', 'content': narrative}],
                                        F.C.get_character_config(name))
    if not calls or R.get(outcome['execution_id'])['status'] != 'approaching':
        raise AssertionError('actual postprocessing lost the explicit semantic run')
    return dict(captured_model_output=captured, tool_result=outcome, narrative=narrative,
                actual_tool_events=[type(event).__name__ for event in events],
                extraction_prompts=[dict(system=c['system_prompt'], user=c['user_prompt']) for c in calls])


class ApiContracts(unittest.TestCase):
    def tearDown(self):
        F.W.set_world_frozen(False)
        for run in R.live_runs():
            A.cancel(run['actor'], run['execution_id'])
        F.assert_no_external_work()

    def test_offers_read_only_real_geometry_entry_and_pair_capability(self):
        name, target, pid = S.setup_run()
        S.clips._write_world_transitions([])
        before = snapshot()
        with pure_tripwires():
            row = next(o for o in P.offers(name) if o['action_id'] == target['action_id'])
        self.assertEqual(row['reason'], 'missing_entry_transition')
        self.assertFalse(row['enabled'])
        self.assertEqual(snapshot(), before)
        S.measured_entry()
        self.assertTrue(P.offers(name)[0]['enabled'])
        meta = F.ROOT / 'clips/run-enter.json'
        document = json.loads(meta.read_text())
        document['pair'] = True
        meta.write_text(json.dumps(document))
        self.assertEqual(P.offers(name)[0]['reason'], 'missing_entry_transition')
        self.assertEqual(S.request(name, target)['reason'], 'missing_entry_transition')
        document['pair'] = False
        meta.write_text(json.dumps(document))
        solo = F.ROOT / 'clips/run-enter.fbx'
        solo.rename(F.ROOT / 'clips/run-enter__a.fbx')
        (F.ROOT / 'clips/run-enter__b.fbx').write_bytes(b'pair-only-fixture')
        S.clips._clear_entries_cache()
        self.assertEqual(P.offers(name)[0]['reason'], 'missing_entry_transition')
        self.assertFalse(R.claims())

    def test_real_http_auth_actor_nonce_revision_and_private_state(self):
        name, partner, target, pid = S.authored_pair()
        stranger = F.actor(target['location_id'], at=(3, 5))
        one, two, foreign, admin = client(name), client(partner), client(stranger), client(name, 'admin')
        self.assertEqual(TestClient(app()).get('/play/prop-actions').status_code, 401)
        body = payload(target, partner=partner, request_id='private-nonce')
        forged = dict(body, target=dict(body['target'], location_id='unknown-secret-location'))
        with patch.object(F.places, '_compose', side_effect=AssertionError('foreign scene must not be composed')):
            blocked = one.post('/play/prop-actions/request', json=forged)
        self.assertEqual(blocked.json()['detail']['reason'], 'target_not_in_actor_room')
        self.assertEqual(one.post('/play/prop-actions/request', json=dict(body, actor=stranger)).status_code, 422)
        self.assertEqual(one.post('/world/props/' + pid + '/validate', json={'document': F.props.read_sidecar(pid)}).status_code, 403)
        bad = one.post('/play/prop-actions/request', json=dict(body, revision='stale'))
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(bad.json()['detail']['reason'], 'stale_definition')
        self.assertEqual(one.post('/play/prop-actions/request', json=dict(body, partner='missing')).status_code, 409)
        asked = one.post('/play/prop-actions/request', json=body)
        self.assertEqual(asked.status_code, 200, asked.text)
        ref = asked.json()['execution_id']
        self.assertEqual(one.post('/play/prop-actions/request', json=body).json(), asked.json())
        self.assertEqual(one.post('/play/prop-actions/request', json=dict(body, partner=stranger)).json()['detail']['reason'], 'request_id_conflict')
        self.assertFalse(one.get('/play/prop-actions/state?actor=' + partner).json()['incoming'])
        self.assertEqual(two.get('/play/prop-actions/state').json()['incoming'][0]['execution_id'], ref)
        self.assertTrue(all(not rows for rows in foreign.get('/play/prop-actions/state').json().values()))
        self.assertEqual(foreign.post('/play/prop-actions/respond', json={'execution_id': ref, 'accept': True}).status_code, 403)
        self.assertEqual(foreign.post('/play/prop-actions/cancel', json={'execution_id': ref}).status_code, 403)
        # Reload means a new HTTP client with the same actual server session.
        reload = TestClient(app())
        reload.cookies.update(two.cookies)
        self.assertEqual(reload.get('/play/prop-actions/state').json()['incoming'][0]['target'], body['target'])
        declined = two.post('/play/prop-actions/respond', json={'execution_id': ref, 'accept': False})
        self.assertEqual(declined.json()['reason'], 'consent_declined')
        self.assertEqual(one.get('/play/prop-actions/state').json()['recent_results'][0]['execution_id'], ref)
        again = one.post('/play/prop-actions/request', json=dict(body, request_id='second-question')).json()
        accepted = two.post('/play/prop-actions/respond', json={'execution_id': again['execution_id'], 'accept': True})
        self.assertEqual(accepted.json()['status'], 'approaching', accepted.text)
        for owner in (one, two):
            self.assertEqual(owner.get('/play/prop-actions/state').json()['current'][0]['execution_id'], again['execution_id'])
        self.assertTrue(all(not rows for rows in foreign.get('/play/prop-actions/state').json().values()))
        self.assertEqual(two.post('/play/prop-actions/cancel', json={'execution_id': again['execution_id']}).status_code, 200)
        from app.core.timeutils import utc_now
        with patch.object(A, 'utc_now', return_value=utc_now() + timedelta(minutes=31)):
            self.assertFalse(A.state_for(partner)['recent_results'])

    def test_admin_checks_are_read_only_and_execution_is_separate_confirmed(self):
        name, partner, target, pid = S.authored_pair()
        admin = client(name, 'admin')
        base = '/world/props/' + pid
        body = payload(target, actor=name, partner=partner)
        doc = F.props.read_sidecar(pid)
        before = snapshot()
        with pure_tripwires():
            self.assertTrue(admin.post(base + '/validate', json={'document': doc}).json()['valid'])
            self.assertTrue(admin.post(base + '/check-placement', json=body).json()['enabled'])
        self.assertEqual(snapshot(), before)
        denied = admin.post(base + '/execute-test', json=dict(body, confirmed=False))
        self.assertEqual(denied.status_code, 422)
        self.assertEqual(snapshot(), before)
        requested = admin.post(base + '/execute-test', json=dict(body, confirmed=True))
        self.assertEqual(requested.json()['status'], 'awaiting_consent')
        self.assertFalse(R.claims())

    def test_actual_renderers_available_blocked_empty_marker_switch_and_override(self):
        name, target, pid = S.setup_run()
        for marker in (False, True):
            template = S.character_template.get_template('run-person')
            template.setdefault('features', {})['activities_enabled'] = marker
            S.character_template.save_template('run-person', template)
            for mode in ('available', 'blocked', 'empty'):
                doc = F.props.read_sidecar(pid)
                doc['actions'] = [] if mode == 'empty' else [dict(id='rest', name='Rest', description='Real recovery',
                    enabled=True, ability='pose', pose_key='sitting', participants=1, presence='any',
                    interrupt_on_presence_change=False, phases=[], requirements=[], effects=[])]
                if mode == 'empty':
                    doc['model_variants'][0]['action_bindings'] = []
                else:
                    doc['model_variants'][0]['action_bindings'] = [dict(action_id='rest', variant_uid=target['variant_uid'],
                        supported=True, marker_ids=['body'], validation='local_valid',
                        access_points={'actor': {'x': 0, 'z': 2, 'yaw': 180}})]
                F.props._write_sidecar(pid, doc)
                S.clips._write_world_transitions([]) if mode == 'blocked' else S.measured_entry()
                for kind, prompt in rendered(name).items():
                    rows = offered_rows(prompt)
                    self.assertEqual(bool(rows), mode != 'empty', kind)
                    if rows:
                        self.assertEqual(rows[0]['enabled'], mode == 'available', (kind, rows))
                        if mode == 'blocked':
                            self.assertEqual(rows[0]['reason'], 'missing_entry_transition')
                        self.assertEqual(rows[0]['target']['placement_id'], target['placement_id'])
        # Genuine World override ignores the new variable: preserve its content
        # and visibly repair mandatory executable context, never silently omit.
        path = 'chat/agent_thought.md'
        template_overrides.set_override(path, 'WORLD OVERRIDE retained for {{ character_name }}', '')
        try:
            actual = rendered(name)['thought']
            self.assertIn('WORLD OVERRIDE retained for ' + name, actual)
            self.assertEqual(offered_rows(actual), [])
        finally:
            template_overrides.delete_override(path)

    def test_real_tool_stream_postprocessing_and_effectful_executor(self):
        name, target, pid = S.setup_run('combined')
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [dict(id='energy', type='stat_delta', target='actor',
                                            when='success', stat='run_energy', amount=15)]
        F.props._write_sidecar(pid, doc)
        offer = offered_rows(rendered(name)['thought'])[0]
        self.assertEqual(offer['effects'][0]['amount'], 15)
        self.assertEqual(offer['effects'][0]['when'], 'success')
        evidence = asyncio.run(streamed_tool(name, offer))
        ref = evidence['tool_result']['execution_id']
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50)
        S.tick(30)
        S.tick(2)
        S.tick(10)
        self.assertEqual(R.get(ref)['status'], 'completed')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 65)
        self.assertEqual(F.db.get_connection().execute('SELECT count(*) FROM prop_action_effect_receipts WHERE execution_id=?', (ref,)).fetchone()[0], 1)
        # Explicit pose/cancel remain authoritative, unlike narration.
        next_run = S.request(name, dict(target, definition_revision=F.props.get_prop(pid)['revision']))
        F.C.set_pose_key_detail(name, 'standing', 'explicit new action')
        self.assertEqual(R.get(next_run['execution_id'])['status'], 'cancelled')

    def test_presence_requirements_sleep_and_raw_pose_have_no_bypass(self):
        name, target, pid = S.setup_run()
        other = F.actor(target['location_id'], at=(2, 5))
        F.C.set_is_sleeping(other, True)
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['presence'] = 'alone'
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        before = F.C.get_character_profile(other), F.C.get_character_pos(other), F.C.get_character_pos(name)
        self.assertEqual(P.offers(name)[0]['reason'], 'presence_not_met')
        self.assertEqual(S.request(name, target)['reason'], 'presence_not_met')
        self.assertEqual((F.C.get_character_profile(other), F.C.get_character_pos(other), F.C.get_character_pos(name)), before)
        self.assertFalse(F.places.assign(name, 'sitting'))
        with self.assertRaises(F.places.PlaceUnavailable):
            F.C.set_pose_intent(name, 'sitting', prefer='device/body')
        self.assertFalse(F.C.get_character_profile(name).get('place'))
        F.C.set_is_sleeping(name, True)
        before = F.C.get_character_pos(name)
        refused = client(name).post('/play/self/activity', json={'place_id': 'device/body', 'pose': 'sitting'})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(F.C.get_character_pos(name), before)

    def test_http_requirement_reasons_and_ongoing_policy(self):
        for stat, value, wanted in (('unknown-private-stat', 0, 'unknown_requirement_reference'),
                                     ('run_energy', 'unreadable', 'missing_character_stat'),
                                     ('run_energy', 50, 'requirement_not_met')):
            name, target, pid = S.setup_run()
            doc = F.props.read_sidecar(pid)
            doc['actions'][0]['requirements'] = [dict(id='minimum', target='actor', type='stat',
                                                      stat=stat, op='ge', value=75)]
            F.props._write_sidecar(pid, doc)
            target['definition_revision'] = F.props.get_prop(pid)['revision']
            profile = F.C.get_character_profile(name)
            profile['status_effects']['run_energy'] = value
            F.C.save_character_profile(name, profile)
            before = F.C.get_character_pos(name), F.C.get_character_profile(name)
            answer = client(name).post('/play/prop-actions/request', json=payload(target))
            self.assertEqual(answer.status_code, 409, answer.text)
            self.assertEqual(answer.json()['detail']['reason'], wanted)
            self.assertEqual((F.C.get_character_pos(name), F.C.get_character_profile(name)), before)
            self.assertFalse(R.claims())

    def test_actual_npc_structured_action_uses_loaded_skill_and_executor(self):
        from app.core.npc_actions import run_action_for
        name, target, pid = S.setup_run('combined')
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [dict(id='npc-energy', type='stat_delta', target='actor',
                                            when='success', stat='run_energy', amount=15)]
        F.props._write_sidecar(pid, doc)
        offer = P.offers(name)[0]
        captured = json.dumps(dict(room=target['room_id'], prop_action=dict(operation='request',
            target=offer['target'], action_id=offer['action_id'], revision=offer['definition_revision'])))
        prompts = []
        def model(**kwargs):
            prompts.append(kwargs['system_prompt'] + '\n' + kwargs['user_prompt'])
            return SimpleNamespace(content=captured)
        result = run_action_for(name, llm=model)
        self.assertTrue(result, result)
        self.assertEqual(offered_rows(prompts[0])[0]['target'], offer['target'])
        ref = result['action_result']['execution_id']
        self.assertEqual(R.get(ref)['status'], 'approaching')
        S.tick(30)
        S.tick(2)
        S.tick(10)
        self.assertEqual(R.get(ref)['status'], 'completed')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 65)

    def test_requirement_loss_on_approach_and_configured_active_interrupt(self):
        for interrupt in (False, True):
            name, target, pid = S.setup_run()
            doc = F.props.read_sidecar(pid)
            doc['actions'][0].update(interrupt_on_presence_change=interrupt,
                requirements=[dict(id='minimum', target='actor', type='stat', stat='run_energy', op='ge', value=40)])
            F.props._write_sidecar(pid, doc)
            target['definition_revision'] = F.props.get_prop(pid)['revision']
            run = S.request(name, target)
            S.tick(30)
            S.tick(2)
            self.assertEqual(R.get(run['execution_id'])['status'], 'active')
            profile = F.C.get_character_profile(name)
            profile['status_effects']['run_energy'] = 0
            F.C.save_character_profile(name, profile)
            S.tick(1)
            self.assertEqual(R.get(run['execution_id'])['status'], 'failed' if interrupt else 'active')
            A.cancel(name, run['execution_id'])
            profile = F.C.get_character_profile(name)
            profile['status_effects']['run_energy'] = 50
            F.C.save_character_profile(name, profile)
            next_run = S.request(name, target)
            profile = F.C.get_character_profile(name)
            profile['status_effects']['run_energy'] = 0
            F.C.save_character_profile(name, profile)
            S.tick(1)
            self.assertEqual(R.get(next_run['execution_id'])['status'], 'failed')

    def test_local_motion_projection_withdraws_without_foreign_route_or_consent(self):
        from app.core.world_ops import _local_prop_approach
        name, target, _ = S.setup_run()
        observer = F.actor(target['location_id'], at=(2, 5))
        location = F.W.get_location_by_id(target['location_id'])
        furniture = next(room for room in location['rooms'] if room['id'] == 'hall')['layout']['props']
        for ident, x, z, depth in (('bend-one', 3, 4, 6), ('bend-two', 5, 7, 4)):
            pid = F.furniture_prop(ident, width=1, depth=depth, height=1)
            furniture.append(dict(id=ident, prop_id=pid, at=[x, z]))
        F.W.upsert_location(location, sync_world=True)
        asked = S.request(name, target)
        journey = F.E.get_journey(name)
        def view(visible=None, own=None, trip=None):
            return _local_prop_approach(name, observer, F.C.get_character_profile(name),
                own or F.C.get_character_profile(observer), trip or journey,
                {name} if visible is None else visible, F.game_time(), 0, 1)
        local = view()
        self.assertTrue(local['waypoints'])
        self.assertTrue(set(local) <= {'journey_id', 'room_id', 'waypoints', 'progress_m', 'walked_m', 'remaining_m', 'paces_m_s_real', 'starts_in_s'})
        self.assertIsNone(view(visible=set()))
        own = dict(F.C.get_character_profile(observer), current_room='adjacent')
        self.assertIsNone(view(own=own))
        self.assertIsNone(view(trip=dict(journey, execution_kind='party')))
        self.assertEqual(R.get(asked['execution_id'])['status'], 'approaching')
        viewer = client(observer)
        response = viewer.get('/play/worldmap')
        self.assertEqual(response.status_code, 200, response.text)
        public = next(row for row in response.json()['characters'] if row['name'] == name)
        self.assertGreaterEqual(len(public['local_approach']['waypoints']), 4)
        self.assertIsNone(public['travel']['waypoints'])
        self.assertTrue(all(not rows for rows in viewer.get('/play/prop-actions/state').json().values()))
        remote = F.actor(target['location_id'], room='adjacent', at=(14, 5))
        remote_journey, reason = F.E.start_journey_to_point(remote, 15, 5)
        self.assertIsNotNone(remote_journey, reason)
        distant = next((row for row in viewer.get('/play/worldmap').json()['characters'] if row['name'] == remote), None)
        if distant is not None:
            self.assertIsNone(distant['local_approach'])
            self.assertIsNone(distant['travel']['waypoints'])
        F.C.save_character_current_room(observer, 'adjacent')
        withdrawn = next(row for row in viewer.get('/play/worldmap').json()['characters'] if row['name'] == name)
        self.assertIsNone(withdrawn['local_approach'])
        self.assertIsNone(withdrawn['travel']['waypoints'])


def scenario():
    """Non-unittest scenario with a real loopback HTTP socket and prompts."""
    import requests
    import uvicorn
    name, target, pid = S.setup_run('combined')
    doc = F.props.read_sidecar(pid)
    doc['actions'][0]['effects'] = [dict(id='energy', type='stat_delta', target='actor',
                                        when='success', stat='run_energy', amount=15)]
    F.props._write_sidecar(pid, doc)
    target['definition_revision'] = F.props.get_prop(pid)['revision']
    prompts = rendered(name)
    offer = offered_rows(prompts['chat'])[0]
    token = login(name)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(app(), log_level='warning', lifespan='off'))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.02)
        base = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        http = requests.Session()
        http.cookies.set(sessions.SESSION_COOKIE_NAME, token)
        listed = http.get(base + '/play/prop-actions', timeout=10)
        listed.raise_for_status()
        assert listed.json()[0]['enabled'], listed.text
        spoof = http.post(base + '/play/prop-actions/request', json=dict(payload(target), actor='foreign'), timeout=10)
        assert spoof.status_code == 422, spoof.text
        requested = http.post(base + '/play/prop-actions/request',
                              json=payload(target, request_id='real-http-once'), timeout=10)
        requested.raise_for_status()
        replay = http.post(base + '/play/prop-actions/request',
                           json=payload(target, request_id='real-http-once'), timeout=10)
        assert replay.json() == requested.json(), (requested.text, replay.text)
        stopped = http.post(base + '/play/prop-actions/cancel',
                            json={'execution_id': requested.json()['execution_id']}, timeout=10)
        stopped.raise_for_status()
        proof = asyncio.run(streamed_tool(name, offer))
        state = http.get(base + '/play/prop-actions/state', timeout=10)
        state.raise_for_status()
        assert state.json()['current'][0]['execution_id'] == proof['tool_result']['execution_id']
        S.tick(30)
        S.tick(2)
        S.tick(10)
        final = http.get(base + '/play/prop-actions/state', timeout=10).json()
        value = F.C.get_character_profile(name)['status_effects']['run_energy']
        terminal = next(row for row in final['recent_results']
                        if row['execution_id'] == proof['tool_result']['execution_id'])
        assert value == 65 and terminal['status'] == 'completed', (value, final)
        (F.ROOT / 'api-prompt-scenario.json').write_text(json.dumps(dict(
            actual_http_base=base, http_offers=listed.json(), spoof_status=spoof.status_code,
            http_request=requested.json(), http_nonce_replay=replay.json(), http_cancel=stopped.json(),
            effect_receipts=[dict(row) for row in F.db.get_connection().execute(
                'SELECT * FROM prop_action_effect_receipts WHERE execution_id=?',
                (proof['tool_result']['execution_id'],))],
            prompts=prompts, streaming=proof, final_state=final, actual_energy=value,
            media_evidence='Deterministic fixture assets, not 3D playable-media proof.'), indent=2))
        F.assert_no_external_work()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


if __name__ == '__main__':
    scenario() if ARGS.api_scenario_worker else unittest.main()
