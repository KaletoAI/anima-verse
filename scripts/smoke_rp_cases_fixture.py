"""The RP test fixture is well-formed and matches today's chat templates.

Usage: ./.venv/bin/python scripts/smoke_rp_cases_fixture.py

1. Shape: every case starts with a system prompt and ends with the player's
   line carrying the [SCENE STATE] block exactly once (the moment rides on the
   LAST user turn only); ids unique; every check has a known dimension, an
   expected yes/no and a finding text; facts present; the conversation case
   has turns and its brief_turns index `turns` (0 = the first follow-up line,
   answered by reply 1) and point at the passive lines.
2. Anchors name their character and player and only ask questions that exist
   (a common check or a case check); prose and character are calibrated too.
3. The prompts the cases froze carry no authoring comment (<!-- … -->), and
   the cat (template feature humanoid off) gets the non-verbal identity line,
   never "You ARE this person … Speak in the first person" (review 2026-11-09:
   that line is how an animal ended up talking).
4. Freshness: rebuilding with scripts/rp_test_build_cases.py gives the SAME
   cases — when a chat template changes, the stored prompts are stale and
   this fails until the builder is run again.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
data = json.loads((ROOT / 'shared/config/rp_test_cases.json').read_text(encoding='utf-8'))
DIMENSIONS = {'repetition', 'prose', 'character', 'logic', 'discipline'}
ids = [c['id'] for c in data['cases']]
assert len(ids) == len(set(ids)), ids
all_checks = {c['id'] for c in data['common_checks']}
for case in data['cases']:
    msgs = case['messages']
    assert msgs[0]['role'] == 'system' and msgs[0]['content'].strip(), case['id']
    assert msgs[-1]['role'] == 'user' and msgs[-1]['content'].startswith(case['incoming']), case['id']
    assert msgs[-1]['content'].count('[SCENE STATE') == 1 and '[END OF SCENE STATE]' in msgs[-1]['content'], case['id']
    assert all('[SCENE STATE' not in m['content'] for m in msgs[1:-1]), case['id']
    assert case['facts'] and case['repeats'] >= 1 and case['focus'], case['id']
    assert case['focus'] and set(case['focus']) <= DIMENSIONS, case['id']
    for check in case['checks']:
        assert check['dimension'] in DIMENSIONS and check['expect'] in ('yes', 'no'), (case['id'], check)
        assert check.get('finding') and check['question'].strip() and '{' not in check['question'], (case['id'], check)
        all_checks.add(check['id'])
    qids = [c['id'] for c in case['checks']]
    assert len(qids) == len(set(qids)), (case['id'], qids)
    if case.get('turns'):
        assert all(0 <= i < len(case['turns']) for i in case.get('brief_turns', [])), case['id']
        # The brief turns are the short passive lines ("Hm.", "Okay.").
        assert all(len(case['turns'][i].split()) <= 2 for i in case.get('brief_turns', [])), case['id']
assert any(c.get('turns') for c in data['cases']), 'no conversation case'
dimension_of = {c['id']: c['dimension'] for c in data['common_checks']}
dimension_of.update({c['id']: c['dimension'] for case in data['cases'] for c in case['checks']})
for anchor in data['anchors']:
    assert anchor.get('character') and anchor.get('player'), anchor['id']
    assert set(anchor['answers']) <= all_checks, anchor['id']
    assert set(anchor['answers'].values()) <= {'yes', 'no'}, anchor['id']
calibrated = {dimension_of[q] for a in data['anchors'] for q in a['answers']}
assert {'prose', 'character', 'logic', 'discipline'} <= calibrated, calibrated
for case in data['cases']:
    for m in case['messages']:
        assert '<!--' not in m['content'], (case['id'], m['role'])
    system = case['messages'][0]['content']
    if case.get('cat_voice'):
        assert 'you have no human speech' in system and 'You ARE this person' not in system, case['id']
    else:
        assert 'You ARE this person' in system and 'no human speech' not in system, case['id']
print(f"Shape OK: {len(ids)} cases, {len(data['anchors'])} anchors")

# Freshness: rebuild into memory and compare the cases.
code = ("import json, sys; sys.path.insert(0, %r); import importlib.util as u; "
        "s = u.spec_from_file_location('b', %r); m = u.module_from_spec(s); s.loader.exec_module(m); "
        "print('@@' + json.dumps(m.build(), ensure_ascii=False))") % (str(ROOT), str(ROOT / 'scripts/rp_test_build_cases.py'))
out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT, timeout=600)
assert out.returncode == 0, out.stderr[-2000:]
fresh = json.loads(out.stdout.split('@@', 1)[1])
if fresh != data:
    stale = [c['id'] for c, f in zip(data['cases'], fresh['cases']) if c != f] or ['(anchors/lists)']
    raise SystemExit('rp_test_cases.json is stale (' + ', '.join(stale) + ') — run scripts/rp_test_build_cases.py')
print('RP fixture matches the current chat templates')
