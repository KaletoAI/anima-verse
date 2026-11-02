"""Usage: ./.venv/bin/python scripts/smoke_suitability_slots.py

Hand expectations: a llama-swap entry with meta.llamaswap.max_num_seqs=4
reports 4 slots; one with only "quant=q8-0 | slots=1 | context=8192" in its
description reports 1; one with neither reports None, and so does
max_num_seqs=0. A capability test with 3 parallel requests against a model
whose provider reports 1 slot runs with concurrency 1 (never two requests at
once, summary concurrency 1); with 2 slots it runs with 2; without a report,
or when the model list cannot be read, it keeps 3. Fake provider, no requests;
all storage is temporary.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    from app.core.provider import _reported_capabilities
    from app.core import model_suitability as suit

    assert _reported_capabilities({'meta': {'llamaswap': {'max_num_seqs': 4}}})['slots'] == 4
    assert _reported_capabilities({'description': 'quant=q8-0 | slots=1 | context=8192'})['slots'] == 1
    assert _reported_capabilities({'description': 'quant=q8-0'})['slots'] is None
    assert _reported_capabilities({'meta': {'llamaswap': {'max_num_seqs': 0}}})['slots'] is None

    cases = [dict(id=f'c{i}', group='helpers', task='extraction', system=f'c{i}', user='test',
                  fmt='text', expect={'min': 1}, repeats=3) for i in range(2)]

    def run(models):
        active, peak, lock = [0], [0], threading.Lock()

        def invoke(messages):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return NS(content='answer', usage={}, finish_reason='stop')

        def list_models():
            if models is None:
                raise OSError('unreachable')
            return models
        instance = NS(available=True, provider_name='fake', _provider=NS(list_models=list_models),
                      create_llm=lambda **kw: NS(invoke=invoke))
        with patch.object(suit, 'runnable_cases', return_value=cases), \
             patch.object(suit, 'load_cases', return_value={}), \
             patch.object(suit, '_persist', return_value=True), \
             patch('app.core.llm_router.create_llm_instance', return_value=instance), \
             patch('app.core.agent_loop.get_agent_loop', return_value=NS(status=lambda: {'running': False})), \
             patch('app.models.world.is_world_frozen', return_value=True):
            summary = list(suit.iter_suitability_results('fake::M', settings={}, concurrency=3))[-1]['summary']
        return summary['concurrency'], peak[0]

    assert run([{'name': 'M', 'slots': 1}]) == (1, 1)
    assert run([{'name': 'M', 'slots': 2}]) == (2, 2)
    assert run([{'name': 'M', 'slots': None}])[0] == 3
    assert run([{'name': 'other', 'slots': 1}])[0] == 3
    assert run(None)[0] == 3
print('Suitability slots: reported slots cap parallel test requests OK')
