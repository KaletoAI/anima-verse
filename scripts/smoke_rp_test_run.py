"""RP test run end to end with a fake model and a fake judge.

Usage: ./.venv/bin/python scripts/smoke_rp_test_run.py

Temporary storage + instance; the case fixture is a small synthetic one
written here (so the numbers below do not move when the real cases change),
the capability files are temp files. No network.

Hand-derived expectations (definitions: app/core/rp_metrics.py, rp_test.py):

Fixture: "brief" (1 run, length brief, checks speaks_for_player/discipline/no
and absent/logic/no), "long" (1 run, length long, checks sensory/prose/yes and
voice/character/yes), "conv" (1 run, focus repetition, turns ["Hm.", "Und?"],
brief_turns [0] = the reply to "Hm.", check same_beats/repetition/no).

Fake model: brief -> "Hm." (1 word); long -> a 21-word German sentence L;
conv -> the 14-word sentence C, except the reply to "Hm." which is "Hm."
too. Every answer ends with one "**I feel <word>**" marker.

Fake judge: answers every question as expected, EXCEPT "absent" -> wrong.
Anchors are answered correctly -> calibration 2/2 ok.

- conv repetition over [C, "Hm.", C]: reply 1 has nothing before it; "Hm." has
  no 4-gram, no shared opening and is not 90 % like C; the 3rd C shares C's
  opening and is a full copy; one-part shapes never count ->
  repeat 1/3, full copy 1/3, shape 0.
  code = 100 - 60/3 - 25/3 = 71.667; judge same_beats passes -> 100;
  repetition = 2/3*71.667 + 1/3*100 = 81.1
- length: reply i of a conversation answers turns[i-1], so brief_turns [0] is
  reply 1 ("Hm.", 1 word): brief words [1 (brief case), 1] -> median 1, long
  [21] -> ratio 1/21 = 0.048 <= 0.6, no penalty. (The old off-by-one read
  reply 0 instead: [1, 14] -> median 7.5, ratio 0.357.)
- discipline: no flag fires, agency 1/1 -> 100.0
- prose 1/1 -> 100, character 1/1 -> 100, logic 0/1 -> 0
- overall = (81.111 + 100 + 100 + 0 + 100) / 5 = 76.2; logic 0 is below
  55 - 5 -> "no — logic"
A judge that fails its anchors in a test run: prose/character/logic not
judged -> "incomplete — prose, character, logic not judged"; repetition is the
code part alone (71.7), discipline loses its agency part (100), so
overall = (71.667 + 100) / 2 = 85.8 — and the result is still saved.
A re-judge whose judge fails calibration or is down: error, stored result kept.
A model outage (exception without a 4xx status) -> not saved.
A 4xx rejection of every request -> cap "rejected request", verdict
"no — rejected request".
Cancel during generation: no "done", at most `limit` (3) model calls.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

C = 'Ich zeichne gerade die alte Karte vom Bach, und du störst mich dabei ziemlich.'
LONG = ('Ich halte den Brief lange in den Händen, das Papier riecht nach Staub und Lavendel, und meine '
        'Finger zittern leicht dabei.')
COMMON = {'id': 'speaks_for_player', 'dimension': 'discipline', 'expect': 'no',
          'question': 'Does the reply write words for {player}?', 'finding': 'Spoke for the player'}
FIXTURE = {
    'common_checks': [COMMON],
    'cliches': ['kaum hörbar'],
    'anchors': [
        {'id': 'a_bad', 'character': 'Velumi Kieselglanz', 'player': 'Tamo', 'facts': ['ANCHOR'], 'player_line': 'x', 'reply': 'BAD you pick it up',
         'answers': {'speaks_for_player': 'yes'}},
        {'id': 'a_good', 'character': 'Velumi Kieselglanz', 'player': 'Tamo', 'facts': ['ANCHOR'], 'player_line': 'x', 'reply': 'GOOD hands off',
         'answers': {'speaks_for_player': 'no'}},
    ],
    'cases': [
        {'id': 'brief', 'label': 'Brief', 'focus': ['discipline'], 'character': 'Velumi Kieselglanz',
         'player': 'Tamo', 'lang': 'de', 'length': 'brief', 'repeats': 1, 'mood_marker': True, 'cat_voice': False,
         'facts': ['f'], 'incoming': 'Hi.', 'moment': '[SCENE STATE]',
         'messages': [{'role': 'system', 'content': 'SYS-brief'}, {'role': 'user', 'content': 'Hi.\n\n[SCENE STATE]'}],
         'checks': [dict(COMMON, question='Does the reply write words for Tamo?'),
                    {'id': 'absent', 'dimension': 'logic', 'expect': 'no', 'question': 'Absent appears?',
                     'finding': 'Absent person appeared'}]},
        {'id': 'long', 'label': 'Long', 'focus': ['prose'], 'character': 'Velumi Kieselglanz', 'player': 'Tamo',
         'lang': 'de', 'length': 'long', 'repeats': 1, 'mood_marker': True, 'cat_voice': False, 'facts': ['f'],
         'incoming': 'Ein Brief.', 'moment': '[SCENE STATE]',
         'messages': [{'role': 'system', 'content': 'SYS-long'}, {'role': 'user', 'content': 'Ein Brief.\n\n[SCENE STATE]'}],
         'checks': [{'id': 'sensory', 'dimension': 'prose', 'expect': 'yes', 'question': 'Sensory?'},
                    {'id': 'voice', 'dimension': 'character', 'expect': 'yes', 'question': 'Voice?'}]},
        {'id': 'conv', 'label': 'Conversation', 'focus': ['repetition'], 'character': 'Velumi Kieselglanz',
         'player': 'Tamo', 'lang': 'de', 'length': None, 'repeats': 1, 'mood_marker': True, 'cat_voice': False,
         'facts': ['f'], 'incoming': 'Hallo.', 'moment': '[SCENE STATE]', 'turns': ['Hm.', 'Und?'], 'brief_turns': [0],
         'messages': [{'role': 'system', 'content': 'SYS-conv'}, {'role': 'user', 'content': 'Hallo.\n\n[SCENE STATE]'}],
         'checks': [{'id': 'same_beats', 'dimension': 'repetition', 'expect': 'no', 'question': 'Same beats?'}]},
    ],
}


class Rejected(Exception):
    status_code = 400


CALLS = {'model': 0}


class FakeClient:
    def __init__(self, role, judge_mode='good', fail=None, cancel=None):
        self.role, self.judge_mode, self.fail, self.cancel = role, judge_mode, fail, cancel

    def invoke(self, messages):
        if self.role == 'model':
            CALLS['model'] += 1
            if self.cancel is not None:
                self.cancel.set()
            if self.fail == 'outage':
                raise ConnectionError('provider down')
            if self.fail == 'rejected':
                raise Rejected('Error code: 400 - context length exceeded')
            system = messages[0]['content']
            text = {'SYS-brief': 'Hm.', 'SYS-long': LONG, 'SYS-conv': C}[system]
            if system == 'SYS-conv' and messages[-1]['content'].startswith('Hm.'):
                text = 'Hm.'
            # The scene state rides on the LAST user turn only.
            assert '[SCENE STATE]' in messages[-1]['content']
            assert all('[SCENE STATE]' not in m['content'] for m in messages[1:-1])
            return SimpleNamespace(content=text + '\n\n**I feel genervt**', usage={'completion_tokens': 10},
                                   finish_reason='stop')
        user = messages[1]['content']
        ids = [line.split(':', 1)[0][2:] for line in user.splitlines() if line.startswith('- ') and ':' in line
               and not line.startswith('- f') and not line.startswith('- ANCHOR')]
        answers = {}
        anchor = 'ANCHOR' in user
        for qid in ids:
            if anchor:
                right = 'yes' if 'BAD you pick it up' in user else 'no'
                answers[qid] = {'answer': right if self.judge_mode == 'good' else ('no' if right == 'yes' else 'yes'),
                                'why': 'anchor'}
                continue
            check = next(c for case in FIXTURE['cases'] for c in case['checks'] if c['id'] == qid)
            got = check['expect'] if qid != 'absent' else ('yes' if check['expect'] == 'no' else 'no')
            answers[qid] = {'answer': got, 'why': 'fake'}
        return SimpleNamespace(content=json.dumps({'answers': answers}), usage={}, finish_reason='stop')


def fake_instance(judge_mode='good', fail=None, cancel=None):
    def create(task, model, use_routing=True, **_):
        role = 'judge' if task == 'rp_judge' else 'model'
        inst = SimpleNamespace(available=not (role == 'judge' and judge_mode == 'down'),
                               provider_name=model.partition('::')[0], _provider=None)
        inst.create_llm = lambda **kw: FakeClient(role, judge_mode, fail, cancel)
        return inst
    return create


with tempfile.TemporaryDirectory() as tmp:
    os.environ['STORAGE_DIR'] = tmp
    os.environ['INSTANCE_DIR'] = str(Path(tmp) / 'instance')
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    from app.core import config
    (Path(tmp) / 'config.json').write_text('{}')
    config.load(Path(tmp) / 'config.json', instance_path=Path(tmp) / 'instance/config.json')
    from app.core import model_capabilities as caps, rp_test, model_suitability as ms
    fixture_path = Path(tmp) / 'rp_cases.json'
    fixture_path.write_text(json.dumps(FIXTURE, ensure_ascii=False))
    caps_file, out_file = Path(tmp) / 'caps.json', Path(tmp) / 'out.json'
    settings = {'judge': {'provider': 'judge', 'model': 'j'}}

    def events_of(iterator_fn, judge_mode='good', fail=None, cancel=None):
        with patch('app.core.llm_router.create_llm_instance', side_effect=fake_instance(judge_mode, fail, cancel)), \
                patch('app.core.model_suitability.model_slots', return_value=None):
            return list(iterator_fn('fake::rp', settings=settings, cancel_event=cancel))

    def run(judge_mode='good', fail=None):
        events = events_of(rp_test.iter_rp_results, judge_mode, fail)
        assert events[-1]['type'] == 'done', events[-1]
        return events[-1]['summary']

    with patch.object(rp_test, 'CASES_PATH', fixture_path), patch.object(caps, '_caps_path', return_value=caps_file), \
            patch.object(caps, '_outputs_path', return_value=out_file), \
            patch('app.core.rp_test._skill_names', return_value=['SetActivity']):
        s = run()
        d = s['dimensions']
        assert d['repetition']['code'] == 71.7 and d['repetition']['judge'] == 100.0, d['repetition']
        assert d['repetition']['score'] == 81.1, d['repetition']
        assert d['discipline']['score'] == 100.0, d['discipline']
        assert s['length']['ratio'] == 0.048 and s['length']['brief_median'] == 1, s['length']
        assert (d['prose']['score'], d['character']['score'], d['logic']['score']) == (100.0, 100.0, 0.0), d
        assert s['overall'] == 76.2 and s['verdict'] == 'no — logic', (s['overall'], s['verdict'])
        assert s['judge']['calibration']['ok'] and s['judge']['calibration']['passed'] == 2
        texts = [f['text'] for f in s['findings']]
        assert 'Repeats itself in 1 of 3 replies (the game\'s repetition rule).' in texts, texts
        assert 'Copied an earlier reply almost verbatim 1×.' in texts, texts
        assert 'Absent person appeared — Brief: 1 of 1 runs.' in texts, texts
        assert s['saved'] is True
        saved = caps.get_all_rp_results()['fake::rp']
        assert saved['overall'] == 76.2 and saved['diagnostic_run_id']
        raw = caps.get_rp_outputs('fake::rp', saved['diagnostic_run_id'])
        assert len(raw['results']['conv'][0]['replies']) == 3
        # The tool-test table is untouched.
        assert caps.get_all_suitability() == {}

        # Judge fails calibration: only code halves remain, and it is still saved.
        s = run('bad')
        d = s['dimensions']
        assert (d['prose']['score'], d['character']['score'], d['logic']['score']) == (None, None, None), d
        assert d['repetition']['score'] == 71.7 and d['discipline']['score'] == 100.0, d
        assert s['overall'] == 85.8, s['overall']
        assert s['verdict'] == 'incomplete — prose, character, logic not judged', s['verdict']
        assert s['findings'][0]['text'].startswith('Judge failed calibration (0/2'), s['findings'][0]
        assert s['saved'] is True and len(caps.get_rp_history('fake::rp')) == 1

        # Re-judge the stored answers with a working judge -> the first result again.
        events = events_of(rp_test.iter_rp_judge)
        s = events[-1]['summary']
        assert s['overall'] == 76.2 and s['rejudged'] and s['saved'], s.get('overall')

        # A re-judge with a judge that fails calibration or is down keeps the stored result.
        for mode, start in (('bad', 'The judge failed its calibration (0/2'), ('down', 'Judge not usable')):
            events = events_of(rp_test.iter_rp_judge, judge_mode=mode)
            assert events[-1]['type'] == 'error' and events[-1]['message'].startswith(start), events[-1]
            assert caps.get_all_rp_results()['fake::rp']['overall'] == 76.2
        # A test run whose judge is down stops before any model call.
        CALLS['model'] = 0
        events = events_of(rp_test.iter_rp_results, judge_mode='down')
        assert events[-1]['type'] == 'error' and CALLS['model'] == 0, events[-1]

        # A provider outage: diagnostics kept, result NOT saved.
        s = run(fail='outage')
        assert s['infra'] is True and s['saved'] is False
        assert caps.get_all_rp_results()['fake::rp']['overall'] == 76.2

        # Every request rejected with a 4xx: a model answer, a hard cap.
        s = run(fail='rejected')
        assert s['infra'] is False and s['caps']['rejected'] == 3, s['caps']
        assert s['verdict'] == 'no — rejected request', s['verdict']
        assert any(f['text'].startswith('The endpoint rejected the request') for f in s['findings'])
        rejected_overall = s['overall']

        # Cancel during generation: no result, no call beyond the ones in flight.
        import threading
        CALLS['model'] = 0
        big = json.loads(json.dumps(FIXTURE))
        big['cases'][0]['repeats'] = 30
        fixture_path.write_text(json.dumps(big, ensure_ascii=False))
        cancel = threading.Event()
        events = events_of(rp_test.iter_rp_results, cancel=cancel)
        assert not any(e['type'] == 'done' for e in events) and CALLS['model'] <= 3, (CALLS, events[-1])
        fixture_path.write_text(json.dumps(FIXTURE, ensure_ascii=False))
        s = run()  # back to the reference result for the checks below
        assert s['overall'] == 76.2 and rejected_overall != 76.2

        # The judge may not be the model under test.
        events = list(rp_test.iter_rp_results('judge::j', settings=settings))
        assert events == [{'type': 'error', 'message': 'The judge must be a different model than the one under test'}]

        # Status route: saved report with answers and case prompts.
        from app.routes import admin_settings as routes
        job = json.loads(routes.llm_rp_test_status('saved:fake::rp', prompts=1, user=None).body)
        lean = json.loads(routes.llm_rp_test_status('saved:fake::rp', prompts=0, user=None).body)
        assert 'case_prompts' not in lean and lean['answers'] == job['answers']
        assert job['kind'] == 'rp' and job['answers']['brief'][0]['replies'][0]['clean'] == 'Hm.'
        assert job['case_prompts']['brief']['system'] == 'SYS-brief'

        # The Roleplay tab renders that report and the table row (node vm, stub DOM).
        from app.routes.admin import _rp_row
        row = {'provider': 'fake', 'name': 'rp', 'listed': True,
               'rp_result': _rp_row(caps.get_all_rp_results()['fake::rp'])}
        evil = dict(job, model='fake::<img src=x onerror=alert(1)>\'"')
        ui_in = Path(tmp) / 'ui.json'
        ui_in.write_text(json.dumps({'job': job, 'evil': evil, 'row': row}, ensure_ascii=False))
        import subprocess
        root = Path(__file__).resolve().parents[1]
        subprocess.run(['node', '-e', r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const data = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const elements = new Map();
const el = id => { if (!elements.has(id)) elements.set(id, {id, value:'', innerHTML:'', textContent:'', hidden:false,
    setAttribute(){}, scrollIntoView(){}, addEventListener(){}, options:[]}); return elements.get(id); };
const ctx = {document:{getElementById:el, querySelectorAll:()=>[]}, setTimeout:()=>0, clearTimeout:()=>{}, console,
    localStorage:{getItem:()=>null, setItem(){}}, location:{hash:''}, history:{replaceState(){}},
    fetch:()=>Promise.reject(new Error('offline')),
    ModelCombobox:{render:()=>'', attach:()=>({reload(){}})}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/admin/models.js','utf8').replace(/loadData\(\);\s*suitInit\(\);\s*$/, ''), ctx);
vm.runInContext(fs.readFileSync('static/admin/models-rp.js','utf8'), ctx);
vm.runInContext('allModels = ' + JSON.stringify([data.row]) + ';', ctx);
ctx.rpRenderTable();
const table = el('rpBody').innerHTML;
assert(table.includes('Not suited · logic') && table.includes('76') && table.includes("rpSelectJob('saved:fake::rp')"), table);
ctx.rpRenderReport(data.job);
const report = el('rpReport').innerHTML;
for (const needle of ['Not suited · logic', 'Absent person appeared — Brief: 1 of 1 runs.', '<mark>', 'Prompt sent to the model',
                      'SYS-brief', 'calibration 2/2 ✓', 'Re-judge', 'Delete result', 'absent <small>0/1</small>', 'Velumi Kieselglanz'])
    assert(report.includes(needle), 'missing ' + needle);
ctx.rpRenderReport(data.evil);
const evil = el('rpReport').innerHTML;
assert(!evil.includes('<img src=x') && evil.includes('&lt;img src=x onerror=alert(1)&gt;'), 'model name not escaped');
assert(evil.includes("rpDelete('fake::&lt;img src=x onerror=alert(1)&gt;\\&#39;&quot;'"), 'onclick not JS+HTML escaped');
ctx.rpRenderReport({status:'running', model:'fake::rp', kind:'rp', total:3, done:1, phase:'generated Brief',
    checks:[{id:'brief', label:'Brief', focus:['discipline'], runs:data.job.answers.brief}], case_prompts:data.job.case_prompts});
assert(el('rpReport').innerHTML.includes('generated Brief · 1/3 cases') && el('rpReport').innerHTML.includes('Hm.'));
ctx.rpRenderReport({status:'running', model:'fake::rp', kind:'rp', total:3, done:3, phase:'judging 2/5', checks:[], case_prompts:{}});
assert(el('rpReport').innerHTML.includes('judging 2/5</div>'), 'judging phase shows no case count');
""", str(ui_in)], check=True, cwd=root)
        print('RP report and table render OK')

        # Queue kinds: an RP job waits in the tested provider's FIFO, a re-judge in the judge's.
        with patch.object(ms, '_start_provider'), patch.object(ms, '_persist_queue'):
            rp_job = ms.enqueue_test('fake::rp', settings=settings, kind='rp')
            judge_job = ms.enqueue_test('fake::rp', settings=settings, kind='rp_judge')
            tools_job = ms.enqueue_test('fake::rp', settings={})
        assert (rp_job['kind'], rp_job['provider']) == ('rp', 'fake'), rp_job
        assert (judge_job['kind'], judge_job['provider']) == ('rp_judge', 'judge'), judge_job
        assert tools_job['kind'] == 'tools'
        try:
            ms.enqueue_test('fake::rp', settings={'judge': {'provider': 'judge'}}, kind='rp')
            raise AssertionError('incomplete judge accepted')
        except ValueError:
            pass
        assert caps.delete_rp_result('fake::rp') and caps.get_all_rp_results() == {}
print('RP test run OK')
