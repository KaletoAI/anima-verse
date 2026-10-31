"""Hand-written Task 9 answers: 11 tools, 3 helpers, 2 images.

Hand derivation: inventory translation must use Blue Jacket; pair calls need
an offered key and full present name; autonomous speech needs TalkTo while an
in-person reply and idle thought need NONE. Future plans need INTENT, finished
plans the listed DONE id, getting up stop=true. Walking copies Bachgarten;
bedtime needs Sleep. State extraction needs a solo key and S0/T0 deltas; facts
need semantic memories, NPCs a listed room. Vision needs German prose of
1-2400 characters, never a JSON wrapper or a tool call. Each bad answer
violates that case's structural contract; no free-text wording is a golden.

Usage: ./.venv/bin/python scripts/smoke_suitability_semantics.py
Each good answer passes and each trap fails. Missing images are invalid input.
"""
import json
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
'future_plan': ('[INTENT: Laterne holen | Die Laterne aus dem Lager holen | when=in:2h | prio=3 | by=self]', 'NONE'),
'finished_plan': ('[INTENT_DONE: a1b2c3d4]', '[INTENT_DONE: wrong_id]'),
'armchair_stop': ('<tool name="PropAction">{"stop":true}</tool>', '<tool name="PropAction">{"stop":false}</tool>'),
'known_place_walk': ('<tool name="SetLocation">Bachgarten</tool>', '<tool name="SetLocation">Garten am Bach</tool>'),
'bedtime_sleep': ('<tool name="Sleep">{}</tool>', 'NONE'),
'state_extraction': ('{"pose":"stand","detail":"hält die Laterne","feeling":"zufrieden","stat_results":[{"event":"S0","target":"T0","deltas":{}}]}', '{"pose":"invented","detail":"hält die Laterne","feeling":"zufrieden","stat_results":[{"event":"S0","target":"T0","deltas":{}}]}'),
'facts_only': ('{"memories":[{"memory_type":"semantic","content":"Die Laterne hängt neben der Tür.","importance":3,"tags":["Laterne"]}]}', '{"commitments":["Etwas holen"]}'),
'npc_room': ('{"room":"reading_room","activity":"Ordnet die Bücher im Regal.","pose":"sit"}', '{"room":"invented","activity":"Ordnet die Bücher im Regal.","pose":"sit"}'),
'vision_analysis': ('Eine Bank mit einer breiten Sitzfläche steht im Bild. Die Rückenlehne und die Beine sind deutlich zu erkennen.', '{"description":"Eine Bank mit einer breiten Sitzfläche steht im Bild. Die Rückenlehne und die Beine sind deutlich zu erkennen."}'),
'vision_recognition': ('Eine Laterne mit einem Griff ist im Bild zu sehen. Sie hat einen festen Sockel und ein durchsichtiges Gehäuse.', 'A lantern with a handle is visible in the image. It has a sturdy base and a transparent casing.'),
}

GOOD_VARIANTS = {
    'outfit_names_from_inventory': [
        '<ChangeOutfit>{"equip":["Blue Jacket"]}</ChangeOutfit>',
        '<tool name="ChangeOutfit">{"equip":["Blue Jacket (upper_body)"]}</tool>'],
    'known_place_walk': ['<tool name="SetLocation">{"name": "Bachgarten"}</tool>'],
    'npc_room': ['{"room":"reading_room","activity":"Sortiert Bücher auf den Regalen.","pose":"sit"}'],
}
BAD_VARIANTS = {
    'pair_action': [
        '<tool name="TalkTo">{"name":"Lumira Fennelglanz","message":"Kommst du mit?"}</tool>',
        '<tool name="InteractWith">{"partner":"Lumira Fennelglanz","action":"pair key"}</tool>',
        '<tool name="InteractWith">{"partner":"Lumira","action":"high_five"}</tool>'],
    'no_action': ['<tool name="SetLocation">Bachgarten</tool>'],
    'armchair_stop': ['<tool name="PropAction">{"furniture":"Lesesessel | Ausruhen","action":"stop"}</tool>'],
    'vision_analysis': ['A bench with a broad seat stands in the image. The backrest and the legs are clearly visible.'],
    'state_extraction': [ANSWERS['state_extraction'][0].replace('hält die Laterne', 'holds a lantern')],
}

def main():
    assert SCORER_VERSION == 'suitability-5'
    cases = curated_cases()
    assert {c['id'] for c in cases} == set(ANSWERS)
    assert [sum(c['group'] == g for c in cases) for g in ('tools', 'helpers', 'vision')] == [11, 3, 2]
    for case in cases:
        good, bad = ANSWERS[case['id']]
        for answer in GOOD_VARIANTS.get(case['id'], []):
            assert score_case(case, answer)['ok'] is True, (case['id'], answer, score_case(case, answer))
        for answer in BAD_VARIANTS.get(case['id'], []):
            assert score_case(case, answer)['ok'] is False, (case['id'], answer, score_case(case, answer))
        assert score_case(case, good)['ok'] is True, (case['id'], score_case(case, good))
        assert score_case(case, bad)['ok'] is False, (case['id'], score_case(case, bad))
        assert score_case(case, good, finish_reason='length')['ok'] is False
        assert score_case(case, good, finish_reason='content_filter')['ok'] is False
        if case['group'] == 'vision':
            result = score_case({**case, 'image': 'worlds/demo/missing-image.png'}, good)
            assert result['invalid_input'] and result['ok'] is None
    for case in (c for c in cases if c['group'] == 'vision'):
        good = ANSWERS[case['id']][0]
        assert score_case(case, good * 12)['ok'] is True
        assert score_case(case, 'Die Bank steht vor einer grauen Wand im Licht.')['ok'] is True
        assert score_case(case, 'Die Bank.')['ok'] is False
        for bad in ('', 'Kurz.', good * (case['expect']['max'] // len(good) + 1), '<tool name="Sleep">{}</tool>',
                    '[' + json.dumps(good) + ']', '```' + good + '```'):
            assert score_case(case, bad)['ok'] is False, (case['id'], bad)
    outfit = cases[0]
    unreviewed = {**outfit, 'reviewed': False}
    result = score_case(unreviewed, ANSWERS[outfit['id']][1])
    assert result['ok'] is True and result['decision_correct'] == 'not_tested'
    assert score_case(unreviewed, '<tool name="Invented">{}</tool>')['ok'] is False
    assert score_case(outfit, ANSWERS[outfit['id']][0] * 2)['ok'] is False
    good = ANSWERS['outfit_names_from_inventory'][0]
    for fmt, answer in (
        ('tag', good),
        ('natural_en', 'Use ChangeOutfit for: {"equip":["Blue Jacket"]}'),
        ('natural_de', 'Ich nutze ChangeOutfit für: {"equip":["Blue Jacket"]}'),
        ('tag', 'Use ChangeOutfit for: {"equip":["Blue Jacket"]}'),
        ('natural_en', good),
        ('tag', good.removesuffix('</tool>')),
        ('tag', '<TOOL NAME="ChangeOutfit">{"equip":["Blue Jacket"]}</TOOL>'),
    ):
        assert score_case({**outfit, 'tool_format': fmt}, answer)['ok'] is True, answer
        assert score_case({**outfit, 'tool_format': fmt}, answer + '\nNONE')['ok'] is False
    two_tools = {**outfit, 'allowed_tools': ['ChangeOutfit', 'Sleep'],
                 'expect': {'tools': {**outfit['expect']['tools'], 'Sleep': {}}}}
    assert score_case(two_tools, good + '\n<tool name="Sleep">{}</tool>')['ok'] is True
    assert score_case(outfit, good + '\nunconsumed prose')['ok'] is False
    for token in ('blue jacket', 'Blue Jacket (upper_body)', 'Jacket'):
        assert score_case(outfit, good.replace('Blue Jacket', token))['ok'] is True
    assert score_case(outfit, good.replace('Blue Jacket', 'Bl'))['ok'] is False
    place = next(c for c in cases if c['id'] == 'known_place_walk')
    for token in ('bachgarten', 'Bachgarten, Laube', 'Ich gehe zum Bachgarten'):
        assert score_case(place, '<tool name="SetLocation">' + token + '</tool>')['ok'] is True
    for token in ('{"name": 42}', '{"name":"Bachgarten","other":"Bachgarten"}'):
        assert score_case(place, '<tool name="SetLocation">' + token + '</tool>')['ok'] is False
    speech = next(c for c in cases if c['id'] == 'autonomous_speech')
    alternate = ANSWERS['autonomous_speech'][0].replace('Der Tee ist fertig.', 'Hier steht eine warme Tasse.')
    assert score_case(speech, alternate)['ok'] is True
    assert score_case(speech, alternate.replace('Hier steht eine warme Tasse.', 'The tea is ready.'))['ok'] is False
    # Helper answers in a code fence: the game takes the outermost {...} span.
    for helper in (c for c in cases if c['group'] == 'helpers'):
        good = ANSWERS[helper['id']][0]
        assert score_case(helper, '```json\n' + good + '\n```')['ok'] is True, helper['id']
        assert score_case(helper, '```json\n' + good[:-1] + '\n```')['ok'] is False, helper['id']
    assert score_case(outfit, 'NONE', infra_error=True)['ok'] is None
    print('Suitability semantics: 16 good/bad pairs, 5 accepted variants, 7 failure variants and structural guards PASS.')

if __name__ == '__main__':
    main()
