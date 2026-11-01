#!/usr/bin/env python3
"""Explicit suitability settings. Usage: .venv/bin/python scripts/smoke_suitability_settings.py

Hand-derived: three cases in tools/helpers/vision invoke clients at 0.1/0.5/0.3.
A configured entry at 0.9 contributes nothing. One provider instance creates three
clients. The exact settings survive summary persistence. Unknown keys, non-finite
numbers, temperatures outside [0,2], penalties outside [0,1.5], token counts outside
[0,200000], non-integer budgets and non-object extra parameters yield HTTP 400.
An unknown explicit provider never falls back to another provider.
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
    from app.core import model_suitability as suit, model_capabilities as caps
    from app.routes.admin_settings import _llm_suitability_test_start_sync as start
    from fastapi import HTTPException
    settings = dict(temperature=dict(tools=.1, helpers=.5, vision=.3),
                    repetition_penalty=1.03, max_tokens=900, chat_template='template',
                    thinking=False, extra_params={'nested': {'test': True}})
    with patch.object(suit, 'enqueue_test', return_value={'job_id': 'fake'}) as enqueue:
        start(None, dict(provider='P', model='M', settings=settings, concurrency=3))
        assert enqueue.call_args.kwargs['settings'] == settings
        invalid = [dict(unknown=True), dict(temperature={'tools': .1, 'bogus': .2}),
                   dict(temperature={'tools': .1, 'helpers': .5, 'vision': 3}),
                   dict(repetition_penalty=2), dict(repetition_penalty=True),
                   dict(max_tokens=-1), dict(max_tokens=200001), dict(max_tokens=1.5),
                   dict(thinking='off'), dict(chat_template=[]), dict(extra_params=[]),
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
            return SimpleNamespace(content='ok')
        return SimpleNamespace(invoke=invoke)
    from app.core import llm_router
    provider = SimpleNamespace(name='P', available=True)
    manager = SimpleNamespace(get_provider=lambda name: provider)
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
        assert sorted(invoked) == [('helpers', .5), ('tools', .1), ('vision', .3)], invoked
        assert len(clients) == 3 and all(c['temperature'] != .9 for c in clients)
        assert all(c['max_tokens'] == 900 and c['repetition_penalty'] == 1.03
                   and c['chat_template'] == 'template' and c['thinking'] is False
                   and c['extra_params'] == settings['extra_params'] for c in clients)
        assert create.call_count == 1 and 'routing_entry' not in create.call_args.kwargs
        assert caps.get_all_suitability()['p::m']['tested_suitability']['settings'] == settings
        caps.invalidate_cache()
    with patch.object(llm_router, 'get_provider_manager', return_value=SimpleNamespace(
            get_provider=lambda name: None,
            find_provider_for_model=lambda name: provider)):
        assert actual_create('suitability_test', 'missing::M', use_routing=False) is None
print('Explicit settings validation, group clients, routing isolation and persistence OK')
