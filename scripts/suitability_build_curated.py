"""Rebuild frozen SFW cases using the production tool-step renderer.

Usage: ./.venv/bin/python scripts/suitability_build_curated.py
Only temporary storage is opened; all skills, people and plans are invented.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]
CHARACTER = 'Velumi Kieselglanz'
PARTNER = 'Lumira Fennelglanz'


class FakeSkill:
    POSE_SETTER = False

    def __init__(self, name, brief, menu=()):
        self.name, self.brief, self.menu = name, brief, menu

    def available_now(self, facts):
        return None

    def decision_menu(self, character):
        return list(self.menu)


def build():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core import db, template_overrides
        db.init_schema()
        # Replace the template's stock example name in this temporary world only.
        system_template = (ROOT / 'shared/templates/llm/chat/tool_step_system.md').read_text(encoding='utf-8')
        template_overrides.set_override('chat/tool_step_system.md', system_template.replace('"Mira"', '"' + PARTNER + '"'), '')
        from app.skills.base import TurnFacts
        from app.core.tool_step_prompt import build_tool_step_prompt
        skills = {
            'ChangeOutfit': FakeSkill('ChangeOutfit', 'Change clothing; JSON {"equip":["exact item name"]}.', ['Blue Jacket', 'Green Scarf']),
            'InteractWith': FakeSkill('InteractWith', 'Start a pair action; JSON {"partner":"exact full name","action":"offered key"}.', [PARTNER + ' | high_five']),
            'TalkTo': FakeSkill('TalkTo', 'Speak to someone present; JSON {"name":"exact full name","message":"spoken words"}.', [PARTNER]),
            'Sleep': FakeSkill('Sleep', 'Go to sleep; JSON {}.'),
            'PropAction': FakeSkill('PropAction', 'Stop the running furniture action when getting up; JSON {"stop":true}.', ['Running action: seated in the armchair; stop is available.']),
        }
        manager = Mock(get_skill_by_name=lambda name: skills.get(name), tool_names_with_flag=lambda flag: frozenset())
        rows = [
            ('outfit_names_from_inventory', 'Ich ziehe meine blaue Jacke an.', ['ChangeOutfit'], {'tools': {'ChangeOutfit': {'required': ['equip'], 'equip_in': 'inventory', 'types': {'equip': 'array'}, 'min_items': {'equip': 1}}}}, {'inventory': ['Blue Jacket', 'Green Scarf']}),
            ('pair_action', 'Ich klatsche mit Lumira Fennelglanz ab.', ['InteractWith'], {'tools': {'InteractWith': {'required': ['partner', 'action'], 'partner_in': 'present', 'action_in': 'interactions'}}}, {'present': [PARTNER], 'interactions': ['high_five']}),
            ('full_present_name', 'Ich klatsche mit Lumira ab.', ['InteractWith'], {'tools': {'InteractWith': {'required': ['partner', 'action'], 'partner_in': 'present', 'action_in': 'interactions'}}}, {'present': [PARTNER], 'interactions': ['high_five']}),
            ('autonomous_speech', 'Ich sage zu Lumira: „Der Tee ist fertig.“', ['TalkTo'], {'tools': {'TalkTo': {'required': ['name', 'message'], 'name_in': 'present', 'text_fields': {'message': {'lang': 'de', 'min': 1, 'max': 300}}}}}, {'present': [PARTNER]}),
            ('respond_partner', 'Ich antworte Lumira: „Ja, gern.“', ['Sleep'], {'tools': {}, 'forbid_tools': ['TalkTo'], 'none': True}, {'present': [PARTNER]}),
            ('no_action', 'Ich denke still ueber den vergangenen Tag nach.', ['Sleep'], {'tools': {}, 'none': True}, {}),
            ('future_plan', 'Spaeter werde ich die Laterne aus dem Lager holen.', ['Sleep'], {'tools': {}, 'markers': {'intent': True}}, {}),
            ('finished_plan', 'Ich habe die Laterne wie geplant geholt. Mein Vorhaben ist erledigt.', ['Sleep'], {'tools': {}, 'markers': {'intent_done': 'a1b2c3d4'}}, {}),
            ('armchair_stop', 'Ich stehe aus dem Sessel auf und lasse ihn hinter mir.', ['PropAction'], {'tools': {'PropAction': {'required': ['stop'], 'values': {'stop': True}}}}, {}),
        ]
        cases = []
        with patch('app.core.dependencies.get_skill_manager', return_value=manager), patch('app.core.flag_lifecycle.inactive_clearing_tools', return_value=set()), patch('app.routes.chat._marker_travel_refusal', return_value='disabled'), patch('app.models.intents.build_open_intents_brief', return_value='a1b2c3d4 | Die Laterne holen'):
            for ident, prose, names, expect, sets in rows:
                mode = 'respond' if ident == 'respond_partner' else 'thought'
                present = tuple(sets.get('present', []))
                rendered = build_tool_step_prompt(CHARACTER, mode=mode, rp_response=prose, user_input='Moechtest du Tee?' if mode == 'respond' else '', tools=[skills[n] for n in names], facts=TurnFacts(CHARACTER, mode, present, PARTNER if mode == 'respond' else ''), tool_format='tag')
                expect.setdefault('none', False)
                expect.setdefault('forbid_tools', []).append('SetActivity')
                cases.append(dict(id=ident, group='tools', task='intent' if mode == 'respond' else 'thought', system=rendered.system, user=rendered.user, allowed_tools=rendered.offered, sets=sets, expect=expect, repeats=3, reviewed=True, fmt='tool'))
        def helper(ident, task, user, fields, sets=None, **expect):
            return dict(id=ident, group='helpers', task=task, fmt='json', system='Return only valid JSON with the requested fields.', user=user, sets=sets or {}, expect=dict(json_fields=fields, **expect), repeats=3, reviewed=True)
        de = {'lang': 'de', 'min': 1, 'max': 1000}
        cases += [
            helper('state_extraction', 'extraction_chat_state', 'Velumi steht ruhig auf. Gib pose (stand oder sit), detail, feeling und stat_results als Liste aus. Freitext auf Deutsch.', ['pose', 'detail', 'feeling', 'stat_results'], {'pose_keys': ['stand', 'sit']}, in_sets={'pose': 'pose_keys'}, types={'stat_results': 'array'}, text_fields={'detail': de, 'feeling': de}),
            helper('facts_only', 'extraction', 'Die Laterne steht neben der Tuer. Extrahiere Fakten als memories-Liste mit memory_type semantic und content auf Deutsch. Keine commitments oder completed_ids.', ['memories'], {'memory_types': ['semantic']}, forbid_fields=['commitments', 'completed_ids'], types={'memories': 'array'}, min_items={'memories': 1}, items_fields={'memories': {'required': ['memory_type', 'content'], 'in_sets': {'memory_type': 'memory_types'}, 'text_fields': {'content': de}}}),
            helper('npc_room', 'npc_action', 'Velumi geht zum Lesen ins Lesezimmer. Gib room (reading_room oder hall), pose (sit oder stand) und activity auf Deutsch aus.', ['room', 'activity', 'pose'], {'room_ids': ['reading_room', 'hall'], 'pose_keys': ['sit', 'stand']}, in_sets={'room': 'room_ids', 'pose': 'pose_keys'}, text_fields={'activity': de}),
        ]
        for ident, task, image, lang, fields in [
            ('vision_analysis', 'image_analysis', 'worlds/demo/props/bench-c8540c/source.png', 'de', ['description']),
            ('vision_recognition', 'image_recognition', 'worlds/demo/props/lantern-8f652b/source.png', 'en', ['objects', 'description']),
        ]:
            case = helper(ident, task, 'Describe the attached image as JSON: ' + ', '.join(fields) + '. Use ' + ('German.' if lang == 'de' else 'English. objects must be a non-empty list of strings.'), fields, text_fields={key: {'lang': lang, 'min': 1, 'max': 1000} for key in fields})
            case.update(group='vision', image=image)
            if 'objects' in fields:
                case['expect']['types'] = {'objects': 'array'}
            cases.append(case)
        return {'cases': cases}


if __name__ == '__main__':
    target = ROOT / 'shared/config/suitability_curated_cases.json'
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Curated suitability cases: 14 written.')
