#!/usr/bin/env python3
"""Explicit suitability settings. Usage: .venv/bin/python scripts/smoke_suitability_settings.py

Hand-derived: thinking_max accepts 0 and every 300-token step through 3000;
250, 3300, booleans, missing groups and both old keys are rejected. Three
passing cases only run off; their reasoning is three leaks, no budget hits.
Seven reasoning characters estimate two tokens; reported counts remain intact.
One provider creates three clients at 0.1/0.5/0.3, isolated from routing.
An unknown explicit provider never falls back to another provider.
A provider switched off in the config (not loaded, no channel) is still
reachable for the test: provider_for_test builds it from its entry (type
openai, base http://off/v1, key k, 2 lanes, timeout 60), probes it once and
registers nothing; routing (use_routing=True) still finds no provider. The
picker lists both providers and names the disabled one.
All world and capability storage lives in a temporary directory.
"""
import copy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as directory:
    paths.init(directory)
    paths.init_instance(Path(directory) / "instance")
    from app.core import model_suitability as suit, model_capabilities as caps
    from app.routes.admin_settings import _llm_suitability_test_start_sync as start
    from fastapi import HTTPException
    settings = dict(temperature=dict(tools=.1, helpers=.5, vision=.3),
                    repetition_penalty=1.03, max_tokens=900, chat_template='template',
                    thinking_max=dict(tools=600, helpers=0, vision=300), extra_params={'nested': {'test': True}})
    with patch.object(suit, 'enqueue_test', return_value={'job_id': 'fake'}) as enqueue:
        start(None, dict(provider='P', model='M', settings=settings, concurrency=3))
        assert enqueue.call_args.kwargs['settings'] == settings
        invalid = [dict(unknown=True), dict(temperature={'tools': .1, 'bogus': .2}),
                   dict(temperature={'tools': .1, 'helpers': .5, 'vision': 3}),
                   dict(repetition_penalty=2), dict(repetition_penalty=True),
                   dict(max_tokens=-1), dict(max_tokens=200001), dict(max_tokens=1.5),
                   dict(thinking=False), dict(thinking=True), dict(thinking='off'),
                   dict(thinking={'tools': True}), dict(thinking_budget=True),
                   dict(thinking_budget=dict(tools=True, helpers=None, vision=None)),
                   dict(thinking_budget=dict(tools=1.5, helpers=None, vision=None)),
                   dict(thinking_budget=dict(tools=0, helpers=None, vision=None)),
                   dict(thinking_budget=dict(tools=32001, helpers=None, vision=None)), dict(chat_template=[]), dict(extra_params=[]),
                   dict(extra_params='{}'), dict(extra_params={'x': float('nan')})]
        for change in invalid:
            try:
                start(None, dict(provider='P', model='M', settings={**settings, **change}))
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError(f'Accepted {change}')
        for key in ('entry_index', 'routing_entry', 'extra_params'):
            try:
                start(None, dict(provider='P', model='M', settings=settings, **{key: 0}))
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError(f'Accepted removed key {key}')
    defaults = suit.validate_settings({})
    assert defaults['thinking_max'] == dict(tools=0, helpers=0, vision=0)
    for budget in range(0, 3001, 300):
        assert suit.validate_settings({'thinking_max': dict.fromkeys(('tools', 'helpers', 'vision'), budget)})['thinking_max']['tools'] == budget
    for values in (dict(tools=250, helpers=0, vision=0), dict(tools=3300, helpers=0, vision=0),
                   dict(tools=True, helpers=0, vision=0), dict(tools=300)):
        try:
            suit.validate_settings({'thinking_max': values})
        except ValueError:
            pass
        else:
            raise AssertionError(values)
    image = Path(directory) / 'image.png'
    image.write_bytes(b'fake image')
    cases = [dict(id=g, group=g, task=t, system=g, user='ping', fmt='text',
                  repeats=1, allowed_tools=[], image=str(image)) for g, t in
             [('tools', 'thought'), ('helpers', 'extraction'), ('vision', 'image_analysis')]]
    invoked = []
    clients = []
    def factory(**kwargs):
        clients.append(copy.deepcopy(kwargs))
        def invoke(messages):
            invoked.append((messages[0]['content'], kwargs['temperature']))
            return SimpleNamespace(content='NONE' if kwargs['temperature'] == .1 else 'ok', reasoning='R', budget_hit=kwargs['thinking'],
                                   usage={} if kwargs['temperature'] == .3 else {'reasoning_tokens': 0 if kwargs['temperature'] == .5 else 200})
        return SimpleNamespace(invoke=invoke)
    from app.core import llm_router
    provider = SimpleNamespace(name='P', available=True)
    manager = SimpleNamespace(get_provider=lambda name: provider, provider_for_test=lambda name: provider)
    actual_create = llm_router.create_llm_instance
    def config_get(key, default=None):
        if key == 'llm_routing':
            return [dict(provider='P', model='M', temperature=.9)]
        return default
    with patch('app.core.config.get', side_effect=config_get), patch(
            'app.core.llm_router.create_llm_instance', wraps=actual_create) as create, patch.object(
            llm_router, 'get_provider_manager', return_value=manager), patch.object(
            llm_router, '_load_routing', side_effect=AssertionError('Routing must not be read')), patch.object(
            llm_router.LLMInstance, 'create_llm', side_effect=factory), patch.object(
            suit, 'load_cases', return_value={'cases': cases}), patch.object(
            suit, 'runnable_cases', return_value=cases), patch.object(
            caps, '_caps_path', return_value=Path(directory) / 'caps.json'), patch.object(
            caps, '_outputs_path', return_value=Path(directory) / 'outputs.json'):
        caps.invalidate_cache()
        events = list(suit.iter_suitability_results('P::M', settings=settings))
        summary = events[-1]['summary']
        assert summary['settings'] == settings
        assert summary['budget_hits'] == 0 and summary['thinking_runs'] == 3 and summary['thinking_leak_runs'] == 3
        assert summary['speed']['tools']['reasoning_tokens_median'] == 200
        assert summary['speed']['helpers']['reasoning_tokens_median'] == 0
        assert summary['speed']['vision']['reasoning_tokens_median'] == 0
        assert summary['speed']['vision']['reasoning_tokens_estimated'] is True
        assert all(run['budget_hit'] is False
                   for event in events if event['type'] == 'check' for run in event['runs'])
        assert sorted(invoked) == [('helpers', .5), ('tools', .1), ('vision', .3)], invoked
        assert len(clients) == 3 and all(c['temperature'] != .9 for c in clients)
        assert all(c['max_tokens'] == 900 and c['repetition_penalty'] == 1.03
                   and c['chat_template'] == 'template'
                   and c['extra_params'] == settings['extra_params'] for c in clients)
        for c in clients:
            group = next(g for g, temp in settings['temperature'].items() if temp == c['temperature'])
            assert c['thinking'] is False
            assert c['thinking_budget'] is None
        assert create.call_count == 1 and 'routing_entry' not in create.call_args.kwargs
        stored = caps.get_all_suitability()['p::m']['tested_suitability']
        assert stored['settings'] == settings
        assert stored['budget_hits'] == 0 and stored['thinking_leak_runs'] == 3 and stored['thinking_runs'] == 3
        assert stored['speed'] == summary['speed']
        assert sum(c['budget_hits'] for c in stored['checks']) == 0
        assert all('runs' not in c and 'reasoning' not in c for c in stored['checks'])
        caps.invalidate_cache()
    with patch.object(llm_router, 'get_provider_manager', return_value=SimpleNamespace(
            get_provider=lambda name: None, provider_for_test=lambda name: None,
            find_provider_for_model=lambda name: provider)):
        assert actual_create('suitability_test', 'missing::M', use_routing=False) is None
    from app.core import config as cfg
    from app.core.provider_manager import ProviderManager
    from app.routes.admin_settings import providers_list
    entries = [dict(name='On', type='openai', api_base='http://on/v1'),
               dict(name='Off', type='openai', api_base='http://off/v1', api_key='k',
                    max_concurrent=2, timeout=60, enabled=False)]
    manager = ProviderManager()
    real_get = cfg.get
    with patch.object(cfg, 'get', side_effect=lambda key, *a: entries if key == 'providers' else real_get(key, *a)), \
         patch('app.core.provider.Provider.check_availability', lambda self: setattr(self, 'available', True) or True):
        off = manager.provider_for_test('Off')
        assert (off.type, off.api_base, off.api_key, off.max_concurrent, off.timeout, off.available) == \
            ('openai', 'http://off/v1', 'k', 2, 60, True), off
        assert manager.providers == {} and manager.provider_for_test('Nope') is None
        with patch.object(llm_router, 'get_provider_manager', return_value=SimpleNamespace(
                get_provider=lambda name: None, provider_for_test=manager.provider_for_test,
                find_provider_for_model=lambda name: None)):
            assert actual_create('suitability_test', 'Off::M', use_routing=False).provider_name == 'Off'
            assert actual_create('suitability_test', 'Off::M') is None
        listed = providers_list(user=None)
        assert listed == {'providers': ['On', 'Off'], 'disabled': ['Off']}, listed
print('Explicit settings validation, group clients, routing isolation, disabled providers and persistence OK')
