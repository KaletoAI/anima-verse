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
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

OPTIONS = argparse.ArgumentParser(add_help=False)
OPTIONS.add_argument('--api-scenario-dir', type=Path)
OPTIONS.add_argument('--api-scenario-worker', action='store_true')
OPTIONS.add_argument('--api-startup-worker', action='store_true')
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


def furniture_section(prompt):
    """What an LLM reads about furniture: the contract of a tool-calling
    reader, else the roleplay list, else nothing."""
    if '<prop_actions_contract>' in prompt:
        return prompt.split('<prop_actions_contract>', 1)[1].split('</prop_actions_contract>', 1)[0]
    marker = 'Furniture here (just describe what you do with it):'
    return prompt.split(marker, 1)[1].split('\n\n', 1)[0] if marker in prompt else ''


def offered_lines(prompt):
    """The furniture lines ("- <piece>: <action>, ...") of furniture_section."""
    return [line for line in furniture_section(prompt).split('\n') if line.startswith('- ')]


def own_run(name):
    """The execution id of ``name``'s one running action — an LLM's named
    request answers in names, without it."""
    rows = A.state_for(name)['current']
    if len(rows) != 1:
        raise AssertionError(('expected one own run', rows))
    return rows[0]['execution_id']


async def streamed_tool(name, offered):
    """Captured external model output; actual parser, skill gate and execution."""
    from app.core.streaming import StreamingAgent
    from app.core.tool_formats import find_tool_calls
    manager = get_skill_manager()
    tools = {tool.name: tool.func for tool in manager.get_agent_tools(name)}
    skill = manager.get_skill('prop_action')
    if not skill or skill.name not in tools:
        raise AssertionError('real loader did not expose prop_action capability')
    request = dict(furniture=offered['prop_label'], action=offered['label'])
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
        await asyncio.to_thread(
            _extract_context_from_last_chat, name,
            [{'role': 'assistant', 'content': narrative}], F.C.get_character_config(name))
    if 'execution_id' in outcome or outcome['status'] != 'approaching':
        raise AssertionError(('a named request answers in names', outcome))
    if not calls or R.get(own_run(name))['status'] != 'approaching':
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

    def test_existing_character_runtime_default_explicit_disable_and_rules(self):
        name, target, _ = S.setup_run()
        manager = get_skill_manager()
        skill = manager.get_skill('prop_action')
        override = F.C.get_character_skills_dir(name) / 'prop_action.json'
        override.unlink(missing_ok=True)
        self.assertIn(skill.name, {tool.name for tool in manager.get_agent_tools(name)})
        self.assertFalse(override.exists(), 'runtime default must not write activation overrides')
        F.C.save_character_skill_config(name, 'prop_action', {'enabled': False})
        self.assertNotIn(skill.name, {tool.name for tool in manager.get_agent_tools(name)})
        F.C.save_character_skill_config(name, 'prop_action', {'enabled': True})
        from app.models import rules
        rules.add_rule(dict(id='api-prop-block', name='Actual skill block', type='block',
                            target={'scope': 'skill', 'skills': ['prop_action']},
                            character=name, condition='', message='Blocked by fixture rule'))
        self.addCleanup(rules.delete_rule, 'api-prop-block', target_dir='world')
        self.assertNotIn(skill.name, {tool.name for tool in manager.get_agent_tools(name)})
        denied = client(name).post('/play/prop-actions/request', json=payload(target))
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertFalse(R.claims())
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50)

    def test_positive_cost_nonce_replay_survives_spent_funds_and_new_rules(self):
        from app.core import stat_rules
        from app.models import rules
        previous = stat_rules.get_setting('skill_costs')
        self.addCleanup(stat_rules.save_setting, 'skill_costs', previous)
        for cost in (5, 50):
            name, target, _ = S.setup_run()
            stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': cost}})
            player = client(name)
            body = payload(target, request_id='paid-once')
            created = player.post('/play/prop-actions/request', json=body)
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50 - cost)
            replay = player.post('/play/prop-actions/request', json=body)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), created.json())
            self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50 - cost)
            mismatch = player.post('/play/prop-actions/request', json=dict(body, revision='other-definition'))
            self.assertEqual(mismatch.status_code, 409, mismatch.text)
            self.assertEqual(mismatch.json()['detail']['reason'], 'request_id_conflict')
            self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50 - cost)
            rule_id = 'api-nonce-block-' + str(cost)
            rules.add_rule(dict(id=rule_id, name='Block new action requests', type='block',
                                target={'scope': 'skill', 'skills': ['prop_action']},
                                character=name, condition='', message='No new action'))
            self.addCleanup(rules.delete_rule, rule_id, target_dir='world')
            replay = player.post('/play/prop-actions/request', json=body)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), created.json())
            new_request = player.post('/play/prop-actions/request',
                                      json=dict(body, request_id='truly-new'))
            self.assertEqual(new_request.status_code, 403, new_request.text)
            self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50 - cost)
            self.assertEqual(F.db.get_connection().execute(
                'SELECT count(*) FROM prop_action_runs WHERE actor=? AND request_id=?',
                (name, 'paid-once')).fetchone()[0], 1)
            A.cancel(name, created.json()['execution_id'])

    def test_concurrent_duplicate_paid_http_request_creates_and_charges_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.core import stat_rules
        previous = stat_rules.get_setting('skill_costs')
        self.addCleanup(stat_rules.save_setting, 'skill_costs', previous)
        stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': 5}})
        name, target, _ = S.setup_run()
        token = login(name)
        barrier = Barrier(2)
        body = payload(target, request_id='concurrent-once')
        def send(_):
            with TestClient(app()) as http:
                http.cookies.set(sessions.SESSION_COOKIE_NAME, token)
                barrier.wait()
                return http.post('/play/prop-actions/request', json=body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.assertEqual([result.status_code for result in results], [200, 200])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)
        ref = results[0].json()['execution_id']
        self.assertEqual(F.db.get_connection().execute(
            'SELECT count(*) FROM prop_action_runs WHERE actor=? AND request_id=?',
            (name, 'concurrent-once')).fetchone()[0], 1)
        self.assertEqual(len(R.claims(ref)), 2)
        self.assertEqual(F.E.get_journey(name)['execution_ref'], ref)

    def test_player_request_costs_refusals_and_pair_consent(self):
        from app.core import stat_rules
        previous = stat_rules.get_setting('skill_costs')
        self.addCleanup(stat_rules.save_setting, 'skill_costs', previous)
        stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': 5}})
        name, target, _ = S.setup_run()
        player = client(name)
        refused = player.post('/play/prop-actions/request', json=dict(payload(target), revision='stale'))
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50)
        accepted = player.post('/play/prop-actions/request', json=payload(target))
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)
        stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': 46}})
        before = R.get(accepted.json()['execution_id'])
        denied = player.post('/play/prop-actions/request', json=payload(target))
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)
        self.assertEqual(R.get(accepted.json()['execution_id']), before)
        self.assertEqual(player.post('/play/prop-actions/cancel',
                                    json={'execution_id': before['execution_id']}).status_code, 200)
        name, partner, target, _ = S.authored_pair()
        player, recipient = client(name), client(partner)
        stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': 5}})
        asked = player.post('/play/prop-actions/request', json=payload(target, partner=partner))
        self.assertEqual(asked.json()['status'], 'awaiting_consent')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)
        self.assertFalse(R.claims(), 'paying for a request is not partner consent')
        responded = recipient.post('/play/prop-actions/respond',
                                   json={'execution_id': asked.json()['execution_id'], 'accept': True})
        self.assertEqual(responded.json()['status'], 'approaching', responded.text)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)

    def test_structured_tool_refusals_do_not_pay_success_cost(self):
        from app.core import stat_rules
        from app.core.streaming import StreamingAgent
        from app.core.tool_formats import find_tool_calls
        previous = stat_rules.get_setting('skill_costs')
        self.addCleanup(stat_rules.save_setting, 'skill_costs', previous)
        stat_rules.save_setting('skill_costs', {'prop_action': {'run_energy': 5}})
        name, target, _ = S.setup_run()
        manager = get_skill_manager()
        verb = manager.get_skill('prop_action').name
        tools = {tool.name: tool.func for tool in manager.get_agent_tools(name)}
        agent = StreamingAgent(llm=None, tool_format='tag', tools_dict=tools, agent_name=name)
        async def captured_call(data):
            captured = '<tool name="' + verb + '">' + json.dumps(data) + '</tool>'
            matches = find_tool_calls('tag', captured, tools)
            results = []
            events = [event async for event in agent._execute_tools(matches, results, [])]
            self.assertTrue(events)
            self.assertEqual(len(results), 1)
            return results[0][1]
        request = dict(operation='request', **payload(target))
        refused = json.loads(asyncio.run(captured_call(dict(request, revision='stale'))))
        self.assertEqual(refused['status'], 'refused')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 50)
        accepted = json.loads(asyncio.run(captured_call(request)))
        self.assertEqual(accepted['status'], 'approaching')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)
        refused = json.loads(asyncio.run(captured_call(request)))
        self.assertEqual(refused['reason'], 'participant_claimed')
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['run_energy'], 45)

    def test_startup_repairs_legacy_marker_prerequisites_before_actions(self):
        with tempfile.TemporaryDirectory(prefix='prop-action-startup-') as temporary:
            root = Path(temporary)
            (root / '.prop-action-scenario').write_text('Private legacy startup fixture\n')
            subprocess.run([sys.executable, __file__, '--api-startup-worker'], check=True,
                           env=dict(os.environ, PROP_ACTION_SMOKE_RESUME_ROOT=str(root)))
            actual = json.loads((root / 'startup.json').read_text())
            self.assertTrue(actual['marker_id'])
            self.assertEqual(actual['binding_marker_ids'], [actual['marker_id']])
            self.assertEqual(actual['repeat_changed'], 0)
            self.assertEqual(actual['before_pos'], actual['after_pos'])
            self.assertFalse(actual['claims'])

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

    def test_private_state_resolves_uuid_phases_from_immutable_authored_labels(self):
        name, target, pid = S.setup_run('combined')
        phase_ids = ('7dc8ebbc-cc6b-4a07-84b3-e65048dddf54', 'bb9e99c9-571b-4895-a163-9aef1b627d37')
        phase_labels = ('Preparing tea', 'Enjoying tea')
        document = F.props.read_sidecar(pid)
        for phase, ident, label in zip(document['actions'][0]['phases'], phase_ids, phase_labels):
            phase.update(id=ident, label=label)
        F.props._write_sidecar(pid, document)
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        owner = client(name)
        requested = owner.post('/play/prop-actions/request', json=payload(target))
        self.assertEqual(requested.status_code, 200, requested.text)
        ref = requested.json()['execution_id']

        def current():
            response = owner.get('/play/prop-actions/state')
            self.assertEqual(response.status_code, 200, response.text)
            return next(row for row in response.json()['current'] if row['execution_id'] == ref)

        self.assertEqual(current()['phase_label'], '')
        S.tick(30)
        self.assertEqual(current()['phase'], 'entry')
        self.assertEqual(current()['phase_label'], '')
        S.tick(2)
        self.assertEqual((current()['phase'], current()['phase_label']), (phase_ids[0], phase_labels[0]))
        S.tick(5)
        self.assertEqual((current()['phase'], current()['phase_label']), (phase_ids[1], phase_labels[1]))
        # State names the execution's admitted definition, not a later edit.
        document['actions'][0]['phases'][1]['label'] = 'Changed after admission'
        F.props._write_sidecar(pid, document)
        self.assertEqual(current()['phase_label'], phase_labels[1])

    def test_admin_checks_are_read_only(self):
        name, partner, target, pid = S.authored_pair()
        admin = client(name, 'admin')
        base = '/world/props/' + pid
        body = payload(target, actor=name, partner=partner)
        doc = F.props.read_sidecar(pid)
        before = snapshot()
        with pure_tripwires():
            validated = admin.post(base + '/validate', json={'document': doc}).json()
            self.assertTrue(validated['valid'])
            bindings = validated['derived_bindings'][target['variant_uid']]
            self.assertEqual([(b['action_id'], b['marker_ids']) for b in bindings],
                             [(body['action_id'], ['body'])])
            previews = validated['access_previews'][body['action_id']][target['variant_uid']]
            self.assertTrue(previews)
            for slots in previews.values():
                for roles in slots.values():
                    self.assertEqual(set(roles), {'actor', 'partner'})
                    self.assertTrue(all(point['source'] in ('auto', 'override')
                                        for point in roles.values()))
            checked = admin.post(base + '/check-placement', json=body).json()
            self.assertTrue(checked['enabled'])
            self.assertEqual(set(checked['plans']), {'actor', 'partner'})
            for role, plan in checked['plans'].items():
                person = name if role == 'actor' else partner
                position = F.C.get_character_pos(person)
                self.assertEqual(plan['waypoints'][0], [position['x'], position['z']])
                self.assertEqual(plan['waypoints'][-1], [plan['access']['x'], plan['access']['z']])
                self.assertEqual(plan['entry_anchor']['placement_id'], target['placement_id'])
            default_check = A.check(name, body['target'], body['action_id'], body['revision'], partner)
            self.assertNotIn('plans', default_check)
            offers_response = admin.get('/play/prop-actions')
            self.assertEqual(offers_response.status_code, 200, offers_response.text)
            self.assertNotIn('"plans"', offers_response.text)
        self.assertEqual(snapshot(), before)

    def test_admin_target_catalog_is_actual_private_read_only_census(self):
        name, partner, target, pid = S.authored_pair()
        bystander = F.actor(target['location_id'], at=(3, 5))
        F.C.set_is_sleeping(bystander, True)
        admin, ordinary = client(name, 'admin'), client(name)
        url = '/world/props/' + pid + '/check-targets'
        before = snapshot()
        with pure_tripwires():
            response = admin.get(url, params={'location_id': target['location_id']})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result['revision'], target['definition_revision'])
            room = next(row for row in result['rooms'] if row['id'] == target['room_id'])
            self.assertIn({'target': {key: target[key] for key in A._TARGET}}, room['placements'])
            census = {row['name']: row['sleeping'] for row in room['persons']}
            self.assertIn(name, census)
            self.assertIn(partner, census)
            self.assertTrue(census[bystander])
            self.assertEqual(ordinary.get(url, params={'location_id': target['location_id']}).status_code, 403)
        self.assertEqual(snapshot(), before)

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
                F.props._write_sidecar(pid, doc)
                S.clips._write_world_transitions([]) if mode == 'blocked' else S.measured_entry()
                rows = P.offers(name)
                self.assertEqual(bool(rows), mode != 'empty')
                if rows:
                    self.assertEqual(rows[0]['enabled'], mode == 'available', rows)
                    if mode == 'blocked':
                        self.assertEqual(rows[0]['reason'], 'missing_entry_transition')
                    self.assertEqual(rows[0]['target']['placement_id'], target['placement_id'])
                # Every LLM reads names only, and only what can be requested.
                expected = [f"- {rows[0]['prop_label']}: Rest"] if mode == 'available' else []
                for kind, prompt in rendered(name).items():
                    self.assertEqual(offered_lines(prompt), expected, kind)
                    for field in ('action_id', 'revision', 'placement_id', 'location_id', 'distance',
                                  target['placement_id']):
                        self.assertNotIn(field, furniture_section(prompt), (kind, field))
        # Genuine World override ignores the new variable: preserve its content
        # and visibly repair mandatory executable context, never silently omit.
        path = 'chat/agent_thought.md'
        template_overrides.set_override(path, 'WORLD OVERRIDE retained for {{ character_name }}', '')
        try:
            actual = rendered(name)['thought']
            self.assertIn('WORLD OVERRIDE retained for ' + name, actual)
            self.assertIn('<prop_actions_contract>', actual)
            self.assertEqual(offered_lines(actual), [])
        finally:
            template_overrides.delete_override(path)

    def test_real_tool_stream_postprocessing_and_effectful_executor(self):
        name, target, pid = S.setup_run('combined')
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [dict(id='energy', type='stat_delta', target='actor',
                                            when='success', stat='run_energy', amount=15)]
        F.props._write_sidecar(pid, doc)
        offer = P.offers(name)[0]
        self.assertIn(f"- {offer['prop_label']}: {offer['label']}", offered_lines(rendered(name)['thought']))
        self.assertEqual(offer['effects'][0]['amount'], 15)
        self.assertEqual(offer['effects'][0]['when'], 'success')
        evidence = asyncio.run(streamed_tool(name, offer))
        self.assertEqual(evidence['tool_result'], dict(status='approaching', furniture=offer['prop_label'],
                                                       action=offer['label']))
        ref = own_run(name)
        # The own run in words, the piece named like its offer.
        self.assertIn(f"You are doing: {offer['label']} on {offer['prop_label']}", P.prompt_block(name))
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
        captured = json.dumps(dict(room=target['room_id'], prop_action=dict(
            furniture=offer['prop_label'], action=offer['label'])))
        prompts = []
        def model(**kwargs):
            prompts.append(kwargs['system_prompt'] + '\n' + kwargs['user_prompt'])
            return SimpleNamespace(content=captured)
        override = 'tasks/npc_action.md'
        template_overrides.set_override(override, '## system\nKEEP_PRIVATE_WORLD_DIRECTOR\n## user\n{{ npc_name }}', '')
        try:
            result = run_action_for(name, llm=model)
        finally:
            template_overrides.delete_override(override)
        self.assertTrue(result, result)
        self.assertIn('{"prop_action": {"furniture": "<name>", "action": "<action>"', prompts[0])
        self.assertIn('KEEP_PRIVATE_WORLD_DIRECTOR', prompts[0])
        self.assertEqual(offered_lines(prompts[0]), [f"- {offer['prop_label']}: {offer['label']}"])
        ref = own_run(name)
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

    def test_worldmap_entry_uses_live_clock_freeze_and_stable_origin_for_self_and_observer(self):
        from app.core import timeutils
        clock = [timeutils.utc_now()]
        with patch.object(timeutils, 'utc_now', side_effect=lambda: clock[0]):
            try:
                F.set_game_factor(1)
                name, target, _ = S.setup_run()
                observer = F.actor(target['location_id'], at=(2, 5))
                owner, viewer = client(name), client(observer)
                requested = owner.post('/play/prop-actions/request', json=payload(target))
                self.assertEqual(requested.status_code, 200, requested.text)
                ref = requested.json()['execution_id']
                clock[0] += timedelta(seconds=30)
                F.E.advance_all_journeys()
                A.advance(F.game_time())
                self.assertEqual(R.get(ref)['phase'], 'entry')
                origin = F.game_time().total_seconds

                def row(session):
                    response = session.get('/play/worldmap')
                    self.assertEqual(response.status_code, 200, response.text)
                    return next(person for person in response.json()['characters'] if person['name'] == name)

                public = row(viewer)
                entry = public['prop_action_entry']
                self.assertEqual(entry, row(owner)['prop_action_entry'])
                self.assertEqual(set(entry), {'kind', 'pose_key', 'access', 'anchor', 'root_offset',
                    'duration_game_s', 'elapsed_game_s', 'game_seconds_per_real_second',
                    'height_cm', 'role', 'started_game_s'})
                self.assertEqual(entry['kind'], 'run-enter')
                self.assertEqual(entry['pose_key'], 'sitting')
                self.assertEqual(entry['access'], dict(x=8, y=0, z=7, yaw=180))
                self.assertEqual(set(entry['anchor']), {'x', 'y', 'z', 'yaw'})
                self.assertEqual((entry['anchor']['x'], entry['anchor']['z'], entry['anchor']['yaw']), (8, 5, 0))
                # The real stool-style half-metre cushion uses the catalog's
                # measured seat drop: root is .102 m, not floor or surface.
                self.assertAlmostEqual(entry['root_offset'], .398)
                self.assertAlmostEqual(entry['anchor']['y'], .102)
                self.assertAlmostEqual(entry['anchor']['y'] + entry['root_offset'], .5)
                self.assertEqual(entry['duration_game_s'], 2)
                self.assertEqual(entry['elapsed_game_s'], 0)
                self.assertEqual(entry['game_seconds_per_real_second'], 1)
                self.assertEqual(entry['height_cm'], 170)
                self.assertIsNone(entry['role'])
                self.assertEqual(entry['started_game_s'], origin)
                self.assertIsNone(public['place'])
                self.assertIsNone(public['local_approach'])
                self.assertTrue(all(not rows for rows in viewer.get('/play/prop-actions/state').json().values()))
                self.assertNotIn(ref, json.dumps(entry))
                for elapsed in (.25, .5):
                    clock[0] += timedelta(seconds=.25)
                    polled = row(viewer)['prop_action_entry']
                    self.assertAlmostEqual(polled['elapsed_game_s'], elapsed)
                    self.assertEqual(polled['started_game_s'], origin)
                clock[0] += timedelta(seconds=.5)
                A.advance(F.game_time())
                F.W.set_world_frozen(True)
                frozen = row(viewer)['prop_action_entry']
                self.assertEqual(frozen['elapsed_game_s'], 1)
                self.assertEqual(frozen['game_seconds_per_real_second'], 0)
                clock[0] += timedelta(hours=2)
                A.advance(F.game_time())
                self.assertEqual(row(viewer)['prop_action_entry'], frozen)
                F.W.set_world_frozen(False)
                F.set_game_factor(3)
                clock[0] += timedelta(seconds=.25)
                faster = row(viewer)['prop_action_entry']
                self.assertAlmostEqual(faster['elapsed_game_s'], 1.75)
                self.assertEqual(faster['game_seconds_per_real_second'], 3)
                self.assertEqual(faster['started_game_s'], origin)
                clock[0] += timedelta(seconds=.25)
                A.advance(F.game_time())
                self.assertEqual(R.get(ref)['status'], 'active')
                self.assertIsNone(row(viewer)['prop_action_entry'])
                self.assertIsNone(row(owner)['prop_action_entry'])
                self.assertIsNotNone(row(viewer)['place'])
            finally:
                F.W.set_world_frozen(False)
                F.set_game_factor(0)

    def test_worldmap_entry_withdraws_on_room_profile_claim_and_terminal_ownership_loss(self):
        name, target, _ = S.setup_run()
        observer = F.actor(target['location_id'], at=(2, 5))
        viewer = client(observer)
        requested = S.request(name, target)
        ref = requested['execution_id']
        S.tick(30)
        saved = F.C.get_character_profile(name)['prop_action_entry']

        def projection():
            response = viewer.get('/play/worldmap')
            self.assertEqual(response.status_code, 200, response.text)
            return next(person for person in response.json()['characters'] if person['name'] == name)['prop_action_entry']

        self.assertIsNotNone(projection())
        F.C.save_character_current_room(observer, 'adjacent')
        self.assertIsNone(projection())
        F.C.save_character_current_room(observer, 'hall')
        self.assertIsNotNone(projection())
        run = R.get(ref)
        run['phase'] = ''
        with R.transaction() as conn:
            R.save(conn, run)
        self.assertIsNone(projection(), 'an entry profile alone is not live entry authority')
        run['phase'] = 'entry'
        with R.transaction() as conn:
            R.save(conn, run)
        for corrupt in (None, dict(saved, execution_id='not-the-owned-run'),
                        dict(saved, access=dict(saved['access'], x=1000))):
            profile = F.C.get_character_profile(name)
            profile['prop_action_entry'] = corrupt
            F.C.save_character_profile(name, profile)
            self.assertIsNone(projection())
        profile['prop_action_entry'] = saved
        F.C.save_character_profile(name, profile)
        self.assertIsNotNone(projection())
        with R.transaction() as conn:
            conn.execute('DELETE FROM prop_action_claims WHERE claim_key=?', (R.person_key(name),))
        self.assertIsNone(projection())
        A.cancel(name, ref)
        # A durable stale profile cannot resurrect a cancelled entry.
        profile = F.C.get_character_profile(name)
        profile['prop_action_entry'] = saved
        F.C.save_character_profile(name, profile)
        self.assertIsNone(projection())

    def test_worldmap_pair_entry_reveals_physical_role_but_no_invitation_or_target_identity(self):
        name, partner, target, _ = S.authored_pair()
        for who, gender in ((name, 'female'), (partner, 'male')):
            profile = F.C.get_character_profile(who)
            profile['gender'] = gender
            F.C.save_character_profile(who, profile)
        path = F.ROOT / 'clips/run-pair.json'
        meta = json.loads(path.read_text())
        meta['role_gender'] = {'a': 'male', 'b': 'female'}
        path.write_text(json.dumps(meta))
        observer = F.actor(target['location_id'], at=(3, 5))
        viewer = client(observer)
        requested = S.request(name, target, partner=partner)
        ref = requested['execution_id']
        before = viewer.get('/play/worldmap').json()['characters']
        self.assertTrue(all(row['prop_action_entry'] is None for row in before))
        accepted = client(partner).post('/play/prop-actions/respond', json=dict(execution_id=ref, accept=True))
        self.assertEqual(accepted.status_code, 200, accepted.text)
        S.tick(30)
        response = viewer.get('/play/worldmap')
        self.assertEqual(response.status_code, 200, response.text)
        rows = {row['name']: row for row in response.json()['characters']}
        self.assertEqual(rows[name]['prop_action_entry']['role'], 'b')
        self.assertEqual(rows[partner]['prop_action_entry']['role'], 'a')
        for who, x in ((name, 8.3), (partner, 7.7)):
            entry = rows[who]['prop_action_entry']
            self.assertEqual(entry['access']['x'], x)
            self.assertEqual(entry['anchor']['x'], x)
            self.assertEqual(entry['height_cm'], 170)
            self.assertTrue(set(entry) <= {'kind', 'pose_key', 'access', 'anchor', 'root_offset',
                'duration_game_s', 'elapsed_game_s', 'game_seconds_per_real_second',
                'height_cm', 'role', 'started_game_s'})
            self.assertEqual(set(entry['access']), {'x', 'y', 'z', 'yaw'})
            self.assertEqual(set(entry['anchor']), {'x', 'y', 'z', 'yaw'})
            serialized = json.dumps(entry)
            for private in (ref, name, partner, target['location_id'], target['placement_id'], target['variant_uid']):
                self.assertNotIn(private, serialized)
        self.assertTrue(all(not rows for rows in viewer.get('/play/prop-actions/state').json().values()))
        S.tick(2)
        rows = {row['name']: row for row in viewer.get('/play/worldmap').json()['characters']}
        self.assertIsNone(rows[name]['prop_action_entry'])
        self.assertIsNone(rows[partner]['prop_action_entry'])

    def test_worldmap_entry_origin_and_progress_survive_process_reanchor(self):
        name, target, _ = S.setup_run()
        observer = F.actor(target['location_id'], at=(2, 5))
        viewer = client(observer)
        ref = S.request(name, target)['execution_id']
        S.tick(30)
        S.tick(1)

        def projection():
            response = viewer.get('/play/worldmap')
            self.assertEqual(response.status_code, 200, response.text)
            return next(row for row in response.json()['characters'] if row['name'] == name)['prop_action_entry']

        before = projection()
        self.assertEqual(before['elapsed_game_s'], 1)
        with patch.object(A, '_PROCESS', 'restarted-entry-owner'):
            F.set_game_time(F.game_time() + S.GameDuration.of(hours=4))
            paused = projection()
            self.assertEqual(paused['started_game_s'], before['started_game_s'])
            self.assertEqual(paused['elapsed_game_s'], 1)
            self.assertEqual(paused['game_seconds_per_real_second'], 0)
            A.advance(F.game_time())
            resumed = projection()
            self.assertEqual(resumed['started_game_s'], before['started_game_s'])
            self.assertEqual(resumed['elapsed_game_s'], 1)
            S.tick(1)
            self.assertEqual(R.get(ref)['status'], 'active')
            self.assertIsNone(projection())

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
        self.assertTrue(set(local) <= {'journey_id', 'room_id', 'floor_y', 'waypoints', 'progress_m', 'walked_m', 'remaining_m', 'paces_m_s_real', 'starts_in_s'})
        # The walked floor travels with the motion so a client never guesses the storey.
        self.assertEqual(local['floor_y'], journey['floor_y'])
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


def startup_scenario():
    """Exercise the exact production startup preparation against raw legacy data."""
    from app.core.prop_action_migration import prepare_runtime
    name, target, pid = F.fixture()
    document = F.props.read_sidecar(pid)
    document.pop('actions')
    variant = document['model_variants'][0]
    variant.pop('markers')
    for key in ('width_m', 'depth_m', 'height_m', 'dims_estimated'):
        variant.pop(key, None)
    document.update(width_m=1, depth_m=1, height_m=1, dims_estimated=False,
                    markers=[dict(animation='sit', at=[.5, .5, .5], facing=0)])
    # An authentic pre-migration sidecar must bypass current author normalization.
    (F.props._prop_dir(pid) / F.props.SIDECAR_NAME).write_text(json.dumps(document))
    before = F.C.get_character_pos(name)
    prepared = prepare_runtime()
    assert prepared['applied']['changed'] >= 1, prepared
    actual = F.props.read_sidecar(pid)
    marker = actual['model_variants'][0]['markers'][0]
    from app.core.prop_actions import derive_bindings
    binding = derive_bindings(actual, actual['model_variants'][0])[0]
    assert marker['group'] == 'seat' and 'animation' not in marker, marker
    assert 'markers' not in actual and actual['actions'], actual
    marker_id = marker['id']
    repeated = prepare_runtime()
    assert F.props.read_sidecar(pid)['model_variants'][0]['markers'][0]['id'] == marker_id
    (F.ROOT / 'startup.json').write_text(json.dumps(dict(
        marker_id=marker_id, binding_marker_ids=binding['marker_ids'],
        repeat_changed=repeated['applied']['changed'], before_pos=before,
        after_pos=F.C.get_character_pos(name), claims=R.claims())))
    F.assert_no_external_work()


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
    if ARGS.api_startup_worker:
        startup_scenario()
    elif ARGS.api_scenario_worker:
        scenario()
    else:
        unittest.main()
