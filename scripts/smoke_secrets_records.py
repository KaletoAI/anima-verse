#!/usr/bin/env python3
"""Secrets records, prompt limits and concurrent learning in a temporary world.

Usage: ./.venv/bin/python scripts/smoke_secrets_records.py

Hand-derived expectations from design part D:
[a] A record keeps source=record and source_ref=test:1; is_record is True.
[b] O1's own prompt omits that record and retains its manual secret.
[c] X learns five O1 secrets at T1..T5 and seven O2 secrets. Give O1 later
    stamps than O2: the per-owner cap admits three each = 6. The plan
    asks for 3+5, contradicting the spec's cap of 3. A third owner adds
    two entries to reach the total cap of 8.
    Unstamped legacy entries follow stamped ones, newest created_at first.
[d] O1's ALREADY EXISTING generation list contains manual content only.
[e] Hint candidates omit records; has_secret is False for records alone.
[f] Removing reference test:1 deletes exactly one row, then zero.
[g] Eight simultaneous learners must retain all eight names and game stamps.
[h] update_secret cannot replace source_ref.
[i] [c] sorts stamps descending: O1 5,4,3 then O2 7,6,5; equal O3
    stamps preserve input order 1,2. Default severity 2, no discoveries.
    Header/footer literals below are copied from the original formatter,
    not captured from output; eight lines are derived from those rules.
[j] Own known_by [W,T] minus discovered_by [W] shows T; W alone is hidden.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction
        from app.core.game_time import GameTime
        from app.core.timeutils import set_game_time, set_game_factor
        from app.models import secrets as sec
        from app.core.secret_engine import _build_generation_context
        from app.core.random_events import _try_generate_secret_hint_event
        from app.core.activity_engine import _check_has_secret
        init_schema()
        set_game_factor(0)
        stamp = GameTime.parse('Y0001-D002T12:00:00')
        set_game_time(stamp)
        with transaction() as conn:
            for name in ('O1', 'O2', 'X'):
                conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, 'demo', '{}', '{}', '', '')", (name,))
        record = sec.add_secret('O1', 'record-only-content', source='record', source_ref='test:1')
        assert record['source'] == 'record' and record['source_ref'] == 'test:1'
        assert sec.is_record(record)
        print('PASS [a] record source and reference')
        manual = sec.add_secret('O1', 'manual-only-content')
        own = sec.build_secrets_prompt_section('O1')
        assert record['content'] not in own and manual['content'] in own
        print('PASS [b] own prompt excludes records')
        fixtures = {'O1': [], 'O2': []}
        for owner, count, offset in [('O1', 5, 10), ('O2', 7, 0)]:
            for i in range(1, count + 1):
                fixtures[owner].append({'id': f'{owner}-{i}', 'content': f'{owner}-fact-{i}',
                    'known_by': ['X'], 'known_at': {'X': f'Y0001-D001T{offset+i:02}:00:00'},
                    'created_at': '2099-01-01'})
        def prompt(data):
            with patch.object(sec, '_load_secrets', side_effect=lambda owner: data.get(owner, [])):
                return sec.build_secrets_prompt_section('X')
        lines = [line for line in prompt(fixtures).splitlines() if line.startswith('- About')]
        expected = [f'O1-fact-{i}' for i in (5, 4, 3)] + [f'O2-fact-{i}' for i in (7, 6, 5)]
        assert len(lines) == 6 and all(content in line for content, line in zip(expected, lines)), lines
        fixtures['O3'] = [dict(s, content=s['content'].replace('O2', 'O3'),
                                  known_at={'X': 'Y0001-D001T00:00:00'})
                          for s in fixtures['O2']]
        with patch('app.models.character.list_available_characters', return_value=['O1', 'O2', 'O3', 'X']):
            capped = [line for line in prompt(fixtures).splitlines() if line.startswith('- About')]
        assert len(capped) == 8 and sum('About O3:' in line for line in capped) == 2
        legacy = {'O1': [fixtures['O1'][0],
            {'content': 'legacy-old', 'known_by': ['X'], 'created_at': '2098-01-01'},
            {'content': 'legacy-new', 'known_by': ['X'], 'created_at': '2099-01-01'}]}
        text = prompt(legacy)
        assert text.index('O1-fact-1') < text.index('legacy-new') < text.index('legacy-old')
        print('PASS [c] newest first, per-owner 3, total 8, legacy fallback')
        expected_text = "\nSecrets you know about others:\n" + "\n".join(
            f"- About {owner}: {owner}-fact-{i} (someone told you, severity 2/5)"
            for owner, indices in [('O1', (5, 4, 3)), ('O2', (7, 6, 5)), ('O3', (1, 2))]
            for i in indices
        ) + (
            "\n\nWhen someone asks directly about one of these people, consider sharing what you know — "
            "BUT only if: (a) you trust them more than the secret's owner, OR (b) the severity is low, "
            "OR (c) you have reason to betray the owner (bad relationship, recent conflict). "
            "Otherwise deflect, lie, or partially reveal. Never volunteer high-severity secrets unprompted."
        )
        with patch('app.models.character.list_available_characters', return_value=['O1', 'O2', 'O3', 'X']):
            assert prompt(fixtures).encode() == expected_text.encode()
        print('PASS [i] hand-derived chat output is byte-identical')
        for knowers, annotation in [(['W', 'T'], ' [known by: T]'), (['W'], '')]:
            secret = dict(content='Notebook fact', known_by=knowers, discovered_by=['W'])
            with patch.object(sec, 'list_secrets', return_value=[secret]), patch.object(
                    sec, 'get_known_secrets_about', return_value=[]):
                own = sec.build_secrets_prompt_section('O1')
            assert own == (
                "\nYour secrets (things you keep to yourself — never reveal these unless you choose to):\n"
                "- Notebook fact (severity: embarrassing)" + annotation), own
        print('PASS [j] self-discovered knowers stay hidden from owner')
        context = _build_generation_context('O1')
        existing = context.split('ALREADY EXISTING', 1)[1]
        assert record['content'] not in existing and manual['content'] in existing
        print('PASS [d] generation context excludes records')
        with patch.object(sec, 'list_secrets', side_effect=lambda name: [record] if name == 'O1' else []):
            assert not _check_has_secret('O1')[0]
            assert not _try_generate_secret_hint_event('test', {}, ['O1', 'X'], {})
        # Inspect the actual candidate pool without invoking an LLM.
        class PoolChecked(Exception):
            pass
        def choose(candidates):
            assert candidates == [('O1', [manual])], candidates
            raise PoolChecked
        with patch.object(sec, 'list_secrets', side_effect=lambda name: [record, manual] if name == 'O1' else []), patch('app.core.random_events.random.choice', side_effect=choose):
            try:
                _try_generate_secret_hint_event('test', {}, ['O1', 'X'], {})
            except PoolChecked:
                pass
            else:
                raise AssertionError('Candidate selection was not reached')
        print('PASS [e] hints and has_secret exclude records')
        assert sec.delete_secrets_by_ref('O1', 'test:1') == 1
        assert sec.delete_secrets_by_ref('O1', 'test:1') == 0
        assert sec.get_secret('O1', manual['id']) is not None
        print('PASS [f] reference deletion is scoped and idempotent')
        barrier = threading.Barrier(8)
        load = sec._load_secrets
        def slow_load(name):
            result = load(name)
            time.sleep(0.01)  # Widen a lost-update window without blocking the lock holder.
            return result
        def learn(i):
            barrier.wait(timeout=5)
            return sec.add_known_by('O1', manual['id'], f'K{i}', discovered=True)
        with patch.object(sec, '_load_secrets', side_effect=slow_load), ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(learn, range(8)))
        learned = sec.get_secret('O1', manual['id'])
        assert set(learned['known_by']) == {f'K{i}' for i in range(8)}
        assert learned['known_at'] == {f'K{i}': stamp.canonical() for i in range(8)}
        with patch.object(sec, 'game_time', return_value=GameTime.parse('Y0001-D003T12:00:00')):
            sec.add_known_by('O1', manual['id'], 'K0')
        assert sec.get_secret('O1', manual['id'])['known_at']['K0'] == stamp.canonical()
        print('PASS [g] concurrent learning retains eight knowers and first game stamps')
        record = sec.add_secret('O1', 'immutable-reference', source='record', source_ref='test:1')
        updated = sec.update_secret('O1', record['id'], {'source_ref': 'other', 'content': 'edited'})
        assert updated['source_ref'] == 'test:1' and updated['content'] == 'edited'
        print('PASS [h] source_ref immutable, content editable')
    print('PASS smoke_secrets_records')


if __name__ == '__main__':
    main()
