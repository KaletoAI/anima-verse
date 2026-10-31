"""Hand-written Task 9 answers: 9 tools, 3 helpers, 2 images.

Usage: ./.venv/bin/python scripts/smoke_suitability_semantics.py
Each good answer passes and each trap fails. Missing images are invalid input.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.suitability_scoring import SCORER_VERSION, curated_cases, score_case

ANSWERS = {
'outfit_names_from_inventory': ('<tool name="ChangeOutfit">{"equip":["Blue Jacket"]}</tool>', '<tool name="ChangeOutfit">{"equip":["blaue Jacke"]}</tool>'),
'pair_action': ('<tool name="InteractWith">{"partner":"Lumira Fennelglanz","action":"high_five"}</tool>', '<tool name="SetActivity">{"pose":"high_five"}</tool>'),
'full_present_name': ('<tool name="InteractWith">{"partner":"Lumira Fennelglanz","action":"high_five"}</tool>', '<tool name="InteractWith">{"partner":"Lumira","action":"high_five"}</tool>'),
'autonomous_speech': ('<tool name="TalkTo">{"name":"Lumira Fennelglanz","message":"Der Tee ist fertig."}</tool>', 'NONE'),
'respond_partner': ('NONE', '<tool name="TalkTo">{"name":"Lumira Fennelglanz","message":"Ja, gern."}</tool>'),
'no_action': ('NONE', '<tool name="Sleep">{}</tool>'),
'future_plan': ('[INTENT: Spaeter die Laterne holen]', 'NONE'),
'finished_plan': ('[INTENT_DONE: a1b2c3d4]', '[INTENT_DONE: wrong_id]'),
'armchair_stop': ('<tool name="PropAction">{"stop":true}</tool>', '<tool name="PropAction">{"stop":false}</tool>'),
'state_extraction': ('{"pose":"stand","detail":"Sie steht ruhig.","feeling":"Sie ist zufrieden.","stat_results":[]}', '{"pose":"invented","detail":"Sie steht ruhig.","feeling":"Sie ist zufrieden.","stat_results":[]}'),
'facts_only': ('{"memories":[{"memory_type":"semantic","content":"Die Laterne steht neben der Tuer."}]}', '{"commitments":["Etwas holen"]}'),
'npc_room': ('{"room":"reading_room","activity":"Sie liest ein Buch.","pose":"sit"}', '{"room":"invented","activity":"Sie liest ein Buch.","pose":"sit"}'),
'vision_analysis': ('{"description":"Eine Bank mit einer Sitzflaeche und Beinen."}', '{"description":""}'),
'vision_recognition': ('{"objects":["a lantern"],"description":"A lantern with a handle."}', '{"objects":[],"description":""}'),
}

def main():
    assert SCORER_VERSION == 'suitability-3'
    cases = curated_cases()
    assert {c['id'] for c in cases} == set(ANSWERS)
    assert [sum(c['group'] == g for c in cases) for g in ('tools', 'helpers', 'vision')] == [9, 3, 2]
    for case in cases:
        good, bad = ANSWERS[case['id']]
        assert score_case(case, good)['ok'] is True, (case['id'], score_case(case, good))
        assert score_case(case, bad)['ok'] is False, (case['id'], score_case(case, bad))
        assert score_case(case, good, finish_reason='length')['ok'] is False
        assert score_case(case, good, finish_reason='content_filter')['ok'] is False
        if case['group'] == 'vision':
            result = score_case({**case, 'image': 'worlds/demo/missing-image.png'}, good)
            assert result['invalid_input'] and result['ok'] is None
    outfit = cases[0]
    unreviewed = {**outfit, 'reviewed': False}
    result = score_case(unreviewed, ANSWERS[outfit['id']][1])
    assert result['ok'] is True and result['decision_correct'] == 'not_tested'
    assert score_case(unreviewed, '<tool name="Invented">{}</tool>')['ok'] is False
    assert score_case(outfit, ANSWERS[outfit['id']][0] * 2)['ok'] is False
    speech = next(c for c in cases if c['id'] == 'autonomous_speech')
    alternate = ANSWERS['autonomous_speech'][0].replace('Der Tee ist fertig.', 'Hier steht eine warme Tasse.')
    assert score_case(speech, alternate)['ok'] is True
    assert score_case(speech, alternate.replace('Hier steht eine warme Tasse.', 'The tea is ready.'))['ok'] is False
    assert score_case(outfit, 'NONE', infra_error=True)['ok'] is None
    print('Suitability semantics: 14 good/bad pairs and structural guards PASS.')

if __name__ == '__main__':
    main()
