"""Apply stored recommendations, with no provider calls and temporary storage.

Hand-derived: tools updates entry 0's seven sampling fields; helpers creates one
entry with no tasks; skipped vision changes nothing. The mixed tool/helper entry
warns for tools. The original task chains and unrelated entries remain equal.
A stale revision refuses every write (409), and duplicate targets are rejected.
"""
import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    from app.core import config, config_admin, config_scope, model_capabilities as caps
    from app.routes import admin_settings as route
    from fastapi import HTTPException
    config.load(Path(tmp) / 'config.json')
    entries = [dict(name='Mixed', provider='fake', model='demo', enabled=True,
                    tasks=[{'task': 'intent', 'order': 1}, {'task': 'extraction', 'order': 2}],
                    max_concurrent=7), dict(name='Other', provider='fake', model='other', tasks=[])]
    config.save_part(config_scope.INSTANCE, {'llm_routing': entries})
    before = copy.deepcopy(config_admin.layer_view(config_scope.INSTANCE)['llm_routing'])
    settings = dict(temperature=dict(tools=.1, helpers=.5, vision=.3), max_tokens=900,
                    repetition_penalty=1.03, chat_template='template', extra_params={'nested': True})
    summary = {'settings': settings, 'vision': 'not_supported', 'thinking': {
        'tools': {'recommended': {'thinking': True, 'thinking_budget': 600}},
        'helpers': {'recommended': {'thinking': False, 'thinking_budget': None}}}}
    with patch.object(caps, 'get_all_suitability', return_value={'fake::demo': {'tested_suitability': summary}}), patch.object(config_admin, 'apply_section_reloads', return_value=['llm_routing']):
        assert hasattr(route, '_llm_suitability_apply_sync'), 'apply endpoint is missing'
        preview = route.llm_suitability_apply_preview('fake::demo', None)
        assert preview['entries'][0]['groups'] == ['tools', 'helpers']
        assert preview['entries'][0]['warnings']['tools']
        body = dict(model='fake::demo', base_revision=preview['revision'], groups={
            'tools': {'target': 'entry', 'index': 0}, 'helpers': {'target': 'new'}, 'vision': {'target': 'skip'}})
        result = route._llm_suitability_apply_sync(body)
        after = config_admin.layer_view(config_scope.INSTANCE)['llm_routing']
        expected = copy.deepcopy(before[0])
        expected.update(thinking='on', thinking_budget=600, temperature=.1,
                        **{k: settings[k] for k in ('max_tokens', 'repetition_penalty', 'chat_template', 'extra_params')})
        assert after[0] == expected and after[1] == before[1]
        assert after[2]['name'] == 'demo · Helpers' and after[2]['tasks'] == []
        assert after[2]['thinking'] == 'off' and after[2]['thinking_budget'] is None
        assert [e['index'] for e in result['entries']] == [0, 2]
        try:
            route._llm_suitability_apply_sync(body)
        except HTTPException as exc:
            assert exc.status_code == 409 and exc.detail['code'] == 'stale'
        else:
            raise AssertionError('stale revision accepted')
        body['base_revision'] = result['revision']
        body['groups']['helpers'] = {'target': 'entry', 'index': 0}
        try:
            route._llm_suitability_apply_sync(body)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError('duplicate target accepted')
print('Suitability apply: all expectations hold.')
