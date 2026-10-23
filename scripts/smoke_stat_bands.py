#!/usr/bin/env python3
"""Verify Task 6 bands, prompt notes and thought priorities without an LLM.

Usage: ./.venv/bin/python scripts/smoke_stat_bands.py

Hand-derived: [a] inclusive max 30 selects tired at 22 and 30, max 10
selects exhausted at 8, 31 matches neither; min 75 includes 75.
[b] The scene line contains 22/100 and the tired behavior text.
[c] At 8 the urgent need uses the field label and 8/100.
[d] Five baseline decisions plus one urgent and one felt need = seven;
sleep adds one more. Removing needs preserves all five original lines.
[e] Event hints contain only the selected label, with text as fallback.
Additional cases pin max-over-min precedence, world overrides, effective
boosts, absent stats, stable prompt exclusion and both thought templates.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="stat-bands-") as tmp:
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp))
        from app.core.db import init_schema, transaction
        init_schema()
        from app.core import stat_hints as hints, stat_rules
        from app.core.thought_context import build_thought_context
        from app.core.prompt_templates import render
        from app.models.character_template import build_prompt_section
        from app.models.character import get_character_profile
        template = json.loads((ROOT / "plugins/rp/templates/character/rp.json").read_text())
        fields = {f['key']: f for s in template['sections'] for f in s['fields']}
        rule = stat_rules.field_rule(fields['stamina'])
        for value, expected in [(22, 'tired'), (8, 'exhausted'), (30, 'tired'), (31, None)]:
            band = hints.active_band(rule, value)
            assert (band['label'] if band else None) == expected, (value, band)
        assert hints.active_band(stat_rules.field_rule(fields['attention']), 75)['label'] == 'alert'
        overlap = {'thresholds': [{'min': 0, 'label': 'high'}, {'max': 90, 'label': 'low'},
                                  {'max': 30, 'label': 'lowest'}, {'min': 20, 'label': 'higher'}]}
        assert hints.active_band(overlap, 22)['label'] == 'lowest'
        assert hints.active_band({'thresholds': [{'min': 20}, {'min': 70}]}, 80) == {'min': 70}
        print('PASS [a] inclusive bounds and selection precedence')

        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         ('Bands', 'band-test', json.dumps({'status_effects': {'stamina': 22}}), '{}', '', ''))
            conn.execute("INSERT INTO character_state (character_name) VALUES (?)", ('Bands',))
        with patch('app.models.character_template.get_template', return_value=template):
            profile = get_character_profile('Bands')
            lines = build_prompt_section(template, profile, character_name='Bands', volatile=True)
            expected = 'Stamina: 22/100 — tired: moves slowly, keeps sentences short, would like to sit down'
            assert expected in lines, lines
            assert not any('Stamina:' in line for line in build_prompt_section(
                template, profile, character_name='Bands', volatile=False))
            assert not any('Stamina:' in line for line in build_prompt_section(
                template, profile, character_name='Bands', is_partner=True, volatile=True))
            print('PASS [b] scene note and stable/self-only exclusion')
            urgent_profile = {**profile, 'status_effects': {'stamina': 8}}
            with patch('app.models.character.get_character_profile', return_value=urgent_profile):
                ctx = build_thought_context('Bands')
            assert ctx['needs_urgent'] == ['go home and sleep (Stamina 8/100)'], ctx['needs_urgent']
            assert ctx['needs_felt'] == []
            render('chat/agent_thought_in_chat.md', **ctx)
            print('PASS [c] shared thought context and sibling StrictUndefined render')
            ctx.update(rhythm_sleep_now=False, intent_tracking_enabled=False,
                       needs_felt=['seek company or a safe place (Courage 25/100)'])

            def decisions():
                output = render('chat/agent_thought.md', **ctx)
                return re.findall(r'^\d+\. .+$', output.split('=== What to do now ===')[1], re.M)

            rows = decisions()
            assert [int(row.split('.')[0]) for row in rows] == list(range(1, 8)), rows
            assert 'answer.' in rows[0] and ctx['needs_urgent'][0] in rows[1]
            assert 'A plan is due' in rows[2] and ctx['needs_felt'][0] in rows[3]
            assert 'Your rhythm' in rows[4] and 'Your general task' in rows[5] and 'Otherwise' in rows[6]
            ctx['rhythm_sleep_now'] = True
            assert [int(row.split('.')[0]) for row in decisions()] == list(range(1, 9))
            ctx.update(rhythm_sleep_now=False, needs_urgent=[], needs_felt=[])
            assert decisions() == [
                '1. Someone here speaks to you, or a message waits → answer.',
                '2. A plan is due or can be done here → do it now.',
                '3. Your rhythm puts you elsewhere or at another activity now → go there or start it.',
                '4. Your general task → one concrete step leaving a result (a post, message, finished piece, item used), not preparation or thought.',
                '5. Otherwise something new, different from where you left off — or SKIP.']
            print('PASS [d] priority order, consecutive numbering, unchanged baseline')
            assert hints.get_stat_hints('Bands') == ['tired']
            stat_rules.save_stat_override('stamina', {'thresholds': [
                {'max': 40, 'label': '', 'text': 'world note',
                 'need': {'text': 'world rest', 'urgency': 'felt'}}]})
            assert hints.get_stat_hints('Bands') == ['world note']
            assert 'Stamina: 22/100 — world note' in build_prompt_section(
                template, profile, character_name='Bands', volatile=True)
            ctx = build_thought_context('Bands')
            assert ctx['needs_felt'] == ['world rest (Stamina 22/100)']
            stat_rules.delete_stat_override('stamina')
            with patch('app.core.stat_boosts.active_boosts', return_value={
                    'stamina': [{'amount': 10}]}):
                assert hints.stat_bands('Bands', profile=profile) == []
            assert hints.stat_bands('Bands', profile={**profile, 'status_effects': {}}) == []
            print('PASS [e] labels, fallback, world overrides, effective and absent stats')
    print('smoke_stat_bands: PASS')


if __name__ == '__main__':
    main()
