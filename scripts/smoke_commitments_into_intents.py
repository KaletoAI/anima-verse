#!/usr/bin/env python3
"""Promises use the intent store, against temporary storage only.

Usage: ./.venv/bin/python scripts/smoke_commitments_into_intents.py

Hand-derived expectations: at D001 09:00, 120 minutes means 11:00 and
one hour of grace means expiry 12:00. Standing expiry is D001 plus the
configured self TTL. Repeating a title adds zero rows. Seven equally ranked
standing plans at cap six expire the oldest one with reason cap. Participation
adds visibility but consumes no owned cap. Only an owner or participant may
complete an id. A missing title uses the last whole word within 60 characters.
Deleting two legacy rows returns two, preserves two fact/episode rows, then
returns zero. Reminder bumps once and creates no memory. Templates expose
hex plan ids and titles, with no old memory-based promise block.
A call-only monologue has zero prose, so it makes zero LLM calls, memories,
or intents and returns []. Prose plus a call makes exactly one LLM call,
whose prompt keeps the prose and removes the call. The rendered thought rule
requires a plan for later, rather than accepting a named person alone.
A monologue reply with later/now/ongoing/missing commitments and a semantic
fact returns exactly the later commitment and the fact, without storing when.
A dyadic commitment without when survives. Rendered thought JSON includes
"when": "later".
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="commitments-intents-") as tmp:
        os.environ['ANIMATION_CLIPS_DIR'] = str(Path(tmp) / 'clips')
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import config, db, memory_service as ms
        config.load(Path(tmp) / 'config.json')
        db.init_schema()
        with db.transaction() as conn:
            conn.executemany("INSERT INTO characters (name, created_at, updated_at) VALUES (?, '2026-01-01', '2026-01-01')", [("demo",), ("B",)])
        from app.core.game_time import GameTime
        from app.models import intents, memory
        from app.core.prompt_templates import render_task, render
        now = GameTime.parse('Y0001-D001T09:00:00')
        scheduler, loop = Mock(), Mock()
        with patch.object(ms, 'game_time', return_value=now), \
             patch.object(intents, 'game_time', return_value=now), \
             patch('app.scheduler.scheduler_manager.get_scheduler_manager', return_value=scheduler), \
             patch('app.core.agent_loop.get_agent_loop', return_value=loop), \
             patch('app.core.memory_situational.schedule_embedding'), \
             patch.dict(config._CONFIG, {'intents': {'max_active_self': 6, 'self_intent_ttl_days': 7}}):
            def apply(title=None, content='demo plans a task', delay=0, related='', owner='demo'):
                item = dict(memory_type='commitment', content=content, delay_minutes=delay,
                            related_character=related)
                if title is not None:
                    item['title'] = title
                return ms.apply_extracted_memories(owner, [item], {'is_background': True})

            call = 'SetActivity("going down to cellar", "mit Kisten hantierend")'
            empty_reply = SimpleNamespace(content='{"memories": [], "completed_ids": []}')
            with patch('app.models.character.get_character_config', return_value={}), \
                 patch('app.core.llm_router.llm_call', return_value=empty_reply) as llm:
                before_memories = memory.load_memories('demo')
                before_intents = intents.list_intents()
                assert ms.extract_memories_from_exchange('demo', '', '', call, None) == []
                for call_only in ["Name('one argument')", call + ' ... ;',
                                  '<tool name="SetActivity">{"detail": "cellar"}</tool>']:
                    assert ms.extract_memories_from_exchange('demo', '', '', call_only, None) == []
                llm.assert_not_called()
                assert memory.load_memories('demo') == before_memories
                assert intents.list_intents() == before_intents
                prose = 'demo learned that the cellar door is repaired.'
                assert ms.extract_memories_from_exchange('demo', '', '', prose + ' ' + call, None) == []
                llm.assert_called_once()
                prompt = llm.call_args.kwargs['user_prompt']
                assert prose in prompt and 'SetActivity(' not in prompt

            timing_items = [
                {'memory_type': 'commitment', 'title': 'Bake tomorrow', 'content': 'demo will bake tomorrow.', 'when': 'later'},
                {'memory_type': 'commitment', 'title': 'Walk now', 'content': 'demo walks to the cellar.', 'when': 'now'},
                {'memory_type': 'commitment', 'title': 'Keep company', 'content': 'demo keeps B company.', 'when': 'ongoing'},
                {'memory_type': 'commitment', 'title': 'Missing timing', 'content': 'demo plans a task.'},
                {'memory_type': 'semantic', 'content': 'The cellar door is repaired.'}]
            timing_reply = SimpleNamespace(content=json.dumps({'memories': timing_items, 'completed_ids': []}))
            with patch('app.models.character.get_character_config', return_value={}), \
                 patch('app.core.llm_router.llm_call', return_value=timing_reply):
                extracted = ms.extract_memories_from_exchange('demo', '', '', 'Plans and a learned fact.', None)
                assert [(e['memory_type'], e['content']) for e in extracted] == [
                    ('commitment', 'demo will bake tomorrow.'),
                    ('semantic', 'The cellar door is repaired.')], extracted
                assert all('when' not in e for e in extracted)
            dyadic_reply = SimpleNamespace(content=json.dumps({'memories': [
                {'memory_type': 'commitment', 'title': 'Help B', 'content': 'demo promises to help B.'}], 'completed_ids': []}))
            with patch('app.models.character.get_character_config', return_value={}), \
                 patch('app.core.llm_router.llm_call', return_value=dyadic_reply):
                extracted = ms.extract_memories_from_exchange('demo', 'B', 'Can you help?', 'I promise.', None)
                assert len(extracted) == 1 and extracted[0]['title'] == 'Help B'
                assert 'when' not in extracted[0]

            assert apply('Fass anzapfen', delay=120) == 1
            rows = intents.list_intents(owner='demo', status='active')
            assert len(rows) == 1
            timed = rows[0]
            assert timed['trigger'] == {'kind': 'at_time', 'run_date': 'Y0001-D001T11:00:00'}
            assert timed['expires_at'] == 'Y0001-D001T12:00:00'
            assert timed['source'] == 'character' and timed['meta']['origin'] == 'marker'
            scheduler.add_job.assert_called_once()
            job = scheduler.add_job.call_args.kwargs
            assert job['trigger']['run_date'] == 'Y0001-D001T11:00:00'
            assert job['action']['type'] == 'intent_bump'
            assert job['action']['intent_id'] == timed['id']
            assert not memory.load_memories('demo')
            assert apply('Skizzen versenden', related='B') == 1
            standing = next(r for r in intents.list_intents() if r['title'] == 'Skizzen versenden')
            assert standing['trigger'] == {'kind': 'standing'}
            assert standing['expires_at'] == 'Y0001-D008T09:00:00'
            assert standing['participants']['B'] == {'role': 'demo promised this to you', 'progress': []}
            assert standing['id'] in {r['id'] for r in intents.list_intents(owner='B')}
            assert intents.enforce_active_caps('B') == 0
            assert apply('Skizzen versenden') == 0
            assert apply('Brief austragen', related='Missing') == 1
            missing = next(r for r in intents.list_intents() if r['title'] == 'Brief austragen')
            assert set(missing['participants']) == {'demo'}
            text = 'One two three four five six seven eight nine ten eleven twelve thirteen fourteen'
            assert apply(content=text) == 1
            fallback = next(r for r in intents.list_intents() if r['description'] == text)
            assert fallback['title'] == 'One two three four five six seven eight nine ten eleven'
            assert len(fallback['title']) <= 60
            assert ms._plan_title('', 'x' * 55 + '\t' + 'y' * 10) == 'x' * 55
            assert ms._plan_title('', 'x' * 55 + '\n' + 'y' * 10) == 'x' * 55
            for r in intents.list_intents():
                intents.delete_intent(r['id'])
            titles = ['Bake bread', 'Repair roof', 'Water garden', 'Deliver letter', 'Paint fence', 'Clean cellar', 'Buy apples']
            first = None
            for i, title in enumerate(titles):
                with patch.object(intents, 'utc_now_iso', return_value=f'2026-01-01T00:00:{i:02d}+00:00'):
                    assert apply(title) == 1
                if i == 0:
                    first = intents.list_intents()[0]
            assert len(intents.list_intents(owner='demo', status='active')) == 6
            assert intents.get_intent(first['id'])['meta']['expired_reason'] == 'cap'
            assert intents.get_intent(first['id'])['status'] == 'expired'
            owned = intents.list_intents(owner='demo', status='active')[0]
            foreign = intents.create_intent(owner='B', title='Foreign task')
            reply = SimpleNamespace(content=json.dumps({'memories': [
                {'memory_type': 'commitment', 'title': 'Explicit label', 'content': 'A new plan', 'when': 'later', 'delay_minutes': 120},
                {'memory_type': 'commitment', 'title': '  ', 'content': text, 'when': 'later'}],
                'completed_ids': [' ' + owned['id'] + ' ', foreign['id']]}))
            with patch('app.models.character.get_character_config', return_value={}), \
                 patch('app.core.llm_router.llm_call', return_value=reply) as llm:
                extracted = ms.extract_memories_from_exchange('demo', '', '', 'Finished it', None)
                assert [e['title'] for e in extracted] == ['Explicit label', fallback['title']]
                assert extracted[0]['delay_minutes'] == 120
                prompt = llm.call_args.kwargs['user_prompt']
                assert 'Open plans (id | title)' in prompt
                assert owned['id'] in prompt and foreign['id'] not in prompt
            assert intents.get_intent(owned['id'])['status'] == 'done'
            assert intents.get_intent(foreign['id'])['status'] == 'active'
            participant = intents.create_own_intent('demo', 'Shared promise', extra_participants={'B': {'role': '', 'progress': []}})
            assert intents.complete_intent_as('B', participant['id'])
            for task in ['extraction_thought', 'extraction_memory']:
                _, user = render_task(task, presence_known=False, present_names="", absent_names="", speaker_a='B', speaker_b='demo', text_a='', text_b='', existing_summary='', open_plans_block='OPEN_PLANS_SENTINEL', lang_instruction='')
                if task == 'extraction_thought':
                    assert '"when": "later"' in user
                    assert 'means to do LATER and has not started in this thought' in user
                    assert 'needs either a concrete time hint or a named person' not in user
                assert 'OPEN_PLANS_SENTINEL' in user and '"title"' in user and '[ID:' not in user
            for template in ['chat/agent_thought.md', 'chat/agent_thought_in_chat.md', 'tasks/perceive_action.md']:
                from jinja2 import Environment, meta
                source = (Path(__file__).resolve().parents[1] / "shared/templates/llm" / template).read_text()
                variables = {key: "" for key in meta.find_undeclared_variables(Environment().parse(source))}
                variables["character_name"] = "demo"
                rendered = render(template, **variables)
                assert 'Open promises' not in rendered and 'open commitments' not in rendered.lower()
            assert 'Open commitments' not in memory.build_memory_prompt_section('demo')
            for kind, content in [('commitment', 'Legacy one'), ('commitment', 'Legacy two'), ('semantic', 'A fact'), ('episodic', 'An episode')]:
                memory.add_memory('demo', content, memory_type=kind)
            assert memory.delete_commitment_memories() == 2
            assert {r['memory_type'] for r in memory.load_memories('demo')} == {'semantic', 'episodic'}
            assert memory.delete_commitment_memories() == 0
            from app.core.intent_engine import _handle_remind
            before = memory.load_memories('demo')
            assert _handle_remind({'agent_name': 'demo', 'note': 'Check cellar'})['success']
            loop.bump.assert_called_once_with('demo', hint='Reminder: Check cellar')
            assert memory.load_memories('demo') == before
            assert _handle_remind({'agent_name': 'demo'})['error'] == 'missing_note'
        print('PASS commitments-into-intents scenarios including thought call stripping')


if __name__ == '__main__':
    main()
