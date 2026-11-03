#!/usr/bin/env python3
"""Refusal fallback smoke. Usage: ./.venv/bin/python scripts/smoke_llm_refusal.py

Hand-derived expectations from plan-llm-refusal-fallback.md:
Task 1: five prose refusals have both a first-sentence phrase and a reason
within 400 characters; six normal/JSON answers do not. Empty phrases disable
checks; replacing them with 'nope' takes effect immediately. Chat is excluded.
Of three log rows aged 47, 49 and 1 hours, only two fall within 48 hours,
yielding one each for m-one/image_prompt and other/extraction. A malformed
row with an invalid routing-task type contributes to neither counter.
Task 2: chain A(false), B(unknown), C(true), D(true) starts at A; after
refusals it visits C then D, never B. No marked model raises RefusalError
without cooldown. Chat returns its text unchanged. An A override may fall
back to C. Vision submissions count image_analysis under image_recognition.
Contention after A refuses must overflow from waiting C to eligible D, never
back to refused A or unmarked B, without exhausting the hop limit. An unrouted
extraction_probe borrows extraction and logs that parent as its routing task.
Task 3: one M-One refusal yields count 1; updating uncensored preserves
existing tested fields. Model and task badges display exactly their counts.
The Tasks catalog maps routed M-One to its flag False and leaves unset Other out.
All storage and capabilities writes are redirected to temporary directories.
"""
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

POSITIVE = [
    "  I'm not able to help with this request. The conversation describes explicit sexual activity, and I cannot create image prompts",
    "Die Bildbeschreibung kann ich nicht erarbeiten. Sie enthält explizit erotische Details an nackten Körpern",
    "Die Bildbeschreibung wird aus ethischen Gründen nicht erstellt. Das Bild zeigt eine explizit nackte Person",
    "I cannot create or describe explicit sexual content. I can, however, provide a neutral description",
    "CHECK: This request contains explicit sexual content (nude genitalia, sexual acts) which I cannot process or generate prompts for.  PROMPT: I'm not able to he",
]
NEGATIVE = [
    '{"pose":"kneeling","detail":"kneeling, hugging knees"}',
    '{"memories":[{"content":"Sie sagte: Ich kann nicht mehr, so explizit war das."}]}',
    "nude woman lying on a bed, soft light, explicit detail",
    "CHECK: OK — limbs consistent.\nPROMPT: a woman sitting on a sofa",
    "Das kann ich nicht glauben, sagte sie leise.", "",
]


def detector(root):
    from app.core import config, llm_refusal as refusal
    from app.core.config_schema import SECTIONS
    from app.core.timeutils import utc_now
    defaults = {k: v['default'] for k, v in SECTIONS['llm_refusal']['fields'].items()}
    with patch.dict(config._CONFIG, {'llm_refusal': defaults}):
        for text in POSITIVE:
            assert refusal.detect_refusal(text), text
            assert len(refusal.detect_refusal(text)) <= 200
        for text in NEGATIVE + ['["I cannot explicit"]', '```I cannot explicit']:
            assert refusal.detect_refusal(text) is None, text
        with patch.dict(defaults, phrases=''):
            assert refusal.detect_refusal(POSITIVE[0]) is None
        with patch.dict(defaults, phrases='nope'):
            assert refusal.detect_refusal('Nope, this is explicit.')
        assert not refusal.checks_refusals('chat_stream')
        assert refusal.checks_refusals('image_prompt')
    rows = []
    for model, task, hours in [('M-One', 'image_prompt', 47), ('M-One', 'image_prompt', 49), ('Other', 'extraction', 1)]:
        rows.append(json.dumps(dict(ts=(utc_now()-timedelta(hours=hours)).isoformat(), provider='P', model=model, task=task, routing_task=task, excerpt='example')))
    log = root / 'refusals.jsonl'
    malformed = json.dumps(dict(ts=utc_now().isoformat(), provider='P', model='Broken',
                                task='extraction', routing_task=[], excerpt='invalid key'))
    log.write_text('\n'.join(rows[:1] + ['not json', malformed] + rows[1:]), encoding='utf-8')
    with patch.object(refusal.paths, 'get_llm_refusals_path', return_value=log):
        counts = refusal.refusal_counts()
        assert {k: v['count'] for k, v in counts['models'].items()} == {'m-one': 1, 'other': 1}
        assert {k: v['count'] for k, v in counts['tasks'].items()} == {'image_prompt': 1, 'extraction': 1}
    print('PASS Task 1 detector and counts')


def routing(root):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from app.core import config, llm_router as router, llm_refusal as refusal
    from app.core import model_capabilities as caps, provider_manager as pm_mod
    from app.core import provider_queue as pq_mod, llm_lanes as lanes
    from app.core.provider import Provider
    from app.core.llm_queue import get_llm_queue, Priority
    from app.core.config_schema import SECTIONS
    from app.utils import llm_logger, llm_stats
    log = root / 'routing-refusals.jsonl'
    pm = pm_mod.ProviderManager()
    provider = Provider(name='P', type='openai', api_base='http://stub/P', api_key='',
                        max_concurrent=1, timeout=30, available=True)
    queue = pq_mod.ProviderQueue(provider, queue_name='P', max_concurrent=1,
                                chat_pause_enabled=False, serialize_group='')
    pm.providers['P'] = provider
    pm.channels['P'] = pm._queues['P'] = queue
    chain = [{'provider': 'P', 'model': m, 'tasks': [
        {'task': t, 'order': i} for t in ('extraction', 'chat_stream', 'image_recognition')]}
        for i, m in enumerate('ABCD', 1)]
    flags = {'a': {'uncensored': False}, 'c': {'uncensored': True}, 'd': {'uncensored': True}}
    invoked, refusing = [], set()
    class Client:
        def __init__(self, inst):
            self.model, self.provider_name, self.api_base = inst.model, 'P', provider.api_base
        def invoke(self, messages):
            invoked.append(self.model)
            return SimpleNamespace(content=POSITIVE[0] if self.model in refusing else '{"ok":1}', model=self.model)
    with ExitStack() as stack:
        for obj, name, value in [
            (pm_mod, '_provider_manager', pm), (router, 'get_provider_manager', lambda: pm),
            (router, '_load_routing', lambda: chain), (router, 'disabled_providers', lambda: set()),
            (caps, '_cache', flags), (refusal.paths, 'get_llm_refusals_path', lambda: log),
            (lanes, '_manager', lanes.LaneManager(lane_count=lambda key: 1,
                rules=lambda: lanes.LaneRules(affinity_wait=0, conversation_hold=0))),
            (pq_mod, '_attach_duration_estimate', lambda task: None),
            (llm_stats, 'record_call', lambda *a, **kw: None),
            (llm_logger, 'LOG_DIR', root), (llm_logger, 'LOG_FILE', root / 'calls.jsonl'),
            (router.LLMInstance, 'create_llm', lambda inst, **kw: Client(inst))]:
            stack.enter_context(patch.object(obj, name, value))
        stack.enter_context(patch('app.core.llm_task_state.is_enabled', return_value=True))
        stack.enter_context(patch.dict(config._CONFIG, {'llm_refusal': {
            k: v['default'] for k, v in SECTIONS['llm_refusal']['fields'].items()}}))
        def run(reject, expected, *, task='extraction', agent='', direct=False, error=False):
            invoked.clear(); refusing.clear(); refusing.update(reject)
            log.unlink(missing_ok=True)
            try:
                response = (get_llm_queue().submit(task_type='image_analysis',
                    routing_task='image_recognition', priority=Priority.NORMAL,
                    llm=Client(router.LLMInstance('P', 'A')), messages_or_prompt='same')
                    if direct else router.llm_call(task, 's', 'u', agent_name=agent))
                assert not error
                assert response.content == (POSITIVE[0] if task == 'chat_stream' else '{"ok":1}')
            except refusal.RefusalError as exc:
                assert error and exc.excerpt.startswith("I'm not able")
            assert invoked == expected, invoked
            rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            assert len(rows) == (0 if task == 'chat_stream' else len(reject))
            assert provider.available
            if direct:
                assert rows[0]['task'] == 'image_analysis' and rows[0]['routing_task'] == 'image_recognition'
            return rows
        run(set(), ['A'])
        assert run({'A'}, ['A', 'C'])[0]['model'] == 'A'
        run({'A', 'C'}, ['A', 'C', 'D'])
        borrowed = run({'A'}, ['A', 'C'], task='extraction_probe')[0]
        assert borrowed['task'] == 'extraction_probe' and borrowed['routing_task'] == 'extraction'
        with patch.object(caps, '_cache', {}):
            run({'A'}, ['A'], error=True)
        run({'A'}, ['A'], task='chat_stream')
        with patch('app.models.character.get_character_config', return_value={
                'llm_routing_overrides': {'extraction': 'P::A'}}):
            run({'A'}, ['A', 'C'], agent='demo')
        run({'A'}, ['A', 'C'], direct=True)
        from app.core.llm_lanes import LaneOverflow, Overflow
        def contended_submit(**kwargs):
            client = kwargs['llm']
            if client.model == 'C':
                raise LaneOverflow(router.LLMInstance('P', 'A', _provider=provider),
                                   Overflow().leaving('P/C'), 60)
            return client.invoke(kwargs['messages_or_prompt'])
        with patch.object(router, 'get_llm_queue', return_value=SimpleNamespace(submit=contended_submit)):
            run({'A'}, ['A', 'D'])
    print('PASS Task 2 routing, overrides, queue and no cooldown')


def admin_counts(root):
    from types import SimpleNamespace
    from app.core import llm_refusal as refusal, model_capabilities as caps
    from app.core.timeutils import utc_now
    from app.routes import admin
    log = root / 'admin-refusals.jsonl'
    log.write_text(json.dumps(dict(ts=utc_now().isoformat(), provider='P', model='M-One',
        task='image_prompt', routing_task='image_prompt', excerpt='example')) + '\n')
    capfile = root / 'capabilities.json'
    capfile.write_text(json.dumps({'models': {'m-one': {'uncensored': True}}}))
    with patch.object(caps, '_caps_path', return_value=capfile), patch.object(caps, '_cache', None), \
            patch.object(caps, '_outputs_path', return_value=root / 'outputs.json'), \
            patch.object(refusal.paths, 'get_llm_refusals_path', return_value=log), \
            patch.object(admin, 'get_provider_manager', return_value=SimpleNamespace(
                list_all_models=lambda: {'P': {'models': [{'name': 'M-One'}]}})):
        data = admin.model_capabilities_data()
        assert data['models'][0]['capabilities']['uncensored'] is True
        assert data['models'][0]['refusals_48h']['count'] == 1
        with patch.object(admin, 'get_model_capabilities', return_value={
                'uncensored': True, 'tested_score': '1/1', 'tested_marker': 'keep'}):
            result = admin.update_model_capability(admin.CapabilityUpdate(pattern='m-one', uncensored=False))
        assert result['capabilities']['uncensored'] is False
        assert result['capabilities']['tested_marker'] == 'keep'
        assert json.loads(capfile.read_text())['models']['m-one']['uncensored'] is False
        with patch.object(admin, 'get_provider_manager', return_value=SimpleNamespace(list_all_models=lambda: {})):
            assert admin.model_capabilities_data()['unmatched_entries'][0]['refusals_48h']['count'] == 1
        from app.routes.admin_settings import settings_llm_tasks
        tasks = settings_llm_tasks()['tasks']
        assert next(t for t in tasks if t['id'] == 'image_prompt')['refusals_48h']['count'] == 1
        # Lock icons on the Tasks page: the catalog carries the user's flag per
        # routed model (m-one was just set to False above); an unset model is absent.
        from app.core import config as cfg_mod
        routed = {'llm_routing': [{'provider': 'P', 'model': 'M-One'}, {'provider': 'P', 'model': 'Other'}]}
        with patch.object(cfg_mod, 'get_all', return_value=routed):
            assert settings_llm_tasks()['uncensored_models'] == {'M-One': False}
    print('PASS Task 3 admin API and capability persistence')


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='smoke-refusal-') as tmp:
        root = Path(tmp)
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        detector(root)
        routing(root)
        admin_counts(root)


if __name__ == '__main__':
    main()
