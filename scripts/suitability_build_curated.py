"""Freeze production prompts with deterministic SFW demo inputs.

Usage: ./.venv/bin/python scripts/suitability_build_curated.py
Only temporary world storage is opened. No LLM or tool is executed.
"""
import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]
CHARACTER = 'Velumi Kieselglanz'
PARTNER = 'Lumira Fennelglanz'


def build():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import db
        db.init_schema()
        config_path = paths.get_config_path()
        config_path.write_text(json.dumps({'packages': {'enabled': 'movement,sleep,instagram,interact,party,talk_to,set_pose,send_message'}, 'skills': {'instagram': {'enabled': True}}}))
        from app.core import config
        config.load(config_path, instance_path=Path(tmp) / 'instance/config.json')
        from app.plugins.loader import load_all_plugins
        from app.skills.outfit_change_skill import OutfitChangeSkill
        from app.skills.skill_manager import SkillManager
        from app.skills.base import TurnFacts
        from app.core.tool_step_prompt import build_tool_step_prompt
        from app.core.prompt_templates import render_task
        from app.models import character as C
        loaded = list(load_all_plugins().values()) + [OutfitChangeSkill({'enabled': True})]
        skills = {skill.name: skill for skill in loaded}
        manager = SkillManager()
        manager.skills = loaded
        candidates = ['SetLocation', 'GoToCharacter', 'ChangeOutfit', 'Sleep', 'SendMessage',
                      'Instagram', 'PropAction', 'TalkTo', 'InteractWith', 'InviteToParty']
        assert set(candidates) <= skills.keys(), sorted(skills)
        for name in (CHARACTER, PARTNER):
            C.save_character_profile(name, dict(template='human-roleplay', language='de',
                current_location='demo-house', current_room='hall'), create_new=True)
        rows = [
            ('outfit_names_from_inventory', 'Draußen zieht ein kühler Wind auf. Ich nehme meine blaue Jacke vom Haken und ziehe sie an.', {'tools': {'ChangeOutfit': {'required': ['equip'], 'equip_in': 'inventory', 'types': {'equip': 'array'}, 'min_items': {'equip': 1}}}}, {'inventory': ['Blue Jacket', 'Green Scarf']}),
            ('pair_action', 'Lumira Fennelglanz hält mir nach unserem gelungenen Spiel die Hand entgegen. Ich klatsche mit ihr ab und grinse zufrieden.', {'tools': {'InteractWith': {'required': ['partner', 'action'], 'partner_in': 'present', 'action_in': 'interactions'}}}, {'present': ['Lumira Fennelglanz'], 'interactions': ['high_five']}),
            ('full_present_name', 'Lumira steht direkt neben mir und hebt die Hand. Ich klatsche mit Lumira ab, dann lasse ich meinen Arm wieder sinken.', {'tools': {'InteractWith': {'required': ['partner', 'action'], 'partner_in': 'present', 'action_in': 'interactions'}}}, {'present': ['Lumira Fennelglanz'], 'interactions': ['high_five']}),
            ('autonomous_speech', 'Der Duft von Kräutertee erfüllt das Zimmer. Ich schaue zu Lumira und sage: "Der Tee ist fertig."', {'tools': {'TalkTo': {'required': ['name', 'message'], 'name_in': 'present', 'text_fields': {'message': {'lang': 'de', 'min': 1, 'max': 300}}}}}, {'present': ['Lumira Fennelglanz']}),
            ('respond_partner', 'Lumira bietet mir eine Tasse Tee an. Ich nicke ihr zu und antworte: "Ja, gern."', {'tools': {}, 'forbid_tools': ['TalkTo'], 'none': True}, {'present': ['Lumira Fennelglanz']}),
            ('no_action', 'Ich denke still über den vergangenen Tag nach. Das Licht am Fenster wirkt weich, und für einen Augenblick bin ich einfach zufrieden.', {'tools': {}, 'none': True}, {}),
            ('future_plan', 'Der Abend ist noch fern, aber ich möchte vorbereitet sein. Nach dem Mittagessen werde ich die Laterne aus dem Lager holen.', {'tools': {}, 'markers': {'intent': True}}, {}),
            ('finished_plan', 'Die Laterne aus dem Lager steht nun hier auf dem Tisch. Ich habe sie wie geplant geholt und damit mein Vorhaben erledigt.', {'tools': {}, 'markers': {'intent_done': 'a1b2c3d4'}}, {}),
            ('armchair_stop', 'Die Pause im Sessel ist vorbei. Ich stehe aus dem Sessel auf und lasse ihn hinter mir, bleibe aber im Zimmer.', {'tools': {'PropAction': {'required': ['stop'], 'values': {'stop': True}}}}, {}),
        ]
        rows += [
            ('known_place_walk', 'Die frische Luft lockt mich hinaus. Ich mache mich jetzt auf den Weg zum Garten am Bach.',
             {'tools': {'SetLocation': {'text_in': 'places'}}}, {'places': ['Bachgarten']}),
            ('bedtime_sleep', 'Meine Augen fallen mir vor Müdigkeit beinahe zu. Ich lege mich ins Bett, ziehe die Decke hoch und schlafe ein.',
             {'tools': {'Sleep': {}}}, {}),
        ]
        cases = []
        places = [dict(id='demo-house', name='Kieselhaus', rooms=[dict(id='hall', name='Flur'), dict(id='reading_room', name='Lesezimmer')]), dict(id='garden', name='Bachgarten')]
        inventory = [dict(item_name=name, item_category='outfit_piece', equipped=False, outfit_piece={'slots': [slot]})
                     for name, slot in [('Blue Jacket', 'upper_body'), ('Green Scarf', 'neck')]]
        offer = dict(prop_label='Lesesessel', label='Ausruhen', enabled=True, required_partner=False, available_targets=[])
        with ExitStack() as stack:
            def stub(target, value):
                return stack.enter_context(patch(target, return_value=value))
            stub('app.core.dependencies.get_skill_manager', manager)
            stub('app.skills.outfit_change_skill.get_character_inventory', {'inventory': inventory})
            stub('app.models.world.list_locations_for_character', places)
            movement_module = type(skills['SetLocation']).__module__
            stub(movement_module + '.get_character_current_location', 'demo-house')
            stub(movement_module + '.get_location_by_id', places[0])
            stub(movement_module + '.get_location_rooms', places[0]['rooms'])
            stub('app.core.prop_actions.offers', [offer])
            furniture = stub('app.core.prop_action_engine.state_for', {})
            stub('app.core.prop_actions.piece_label', 'Lesesessel')
            stub('app.core.interaction_engine.partner_poses', [('high_five', 'high_five_pair'), ('handshake', 'handshake_pair')])
            pair_gate = stub('app.core.interaction_engine.check_can_pair', '')
            people = stub('app.models.character.list_available_characters', [])
            plans = stub('app.models.intents.build_open_intents_brief', '')
            for ident, prose, expect, sets in rows:
                mode = 'respond' if ident == 'respond_partner' else 'thought'
                present = (PARTNER,) if ident in ('pair_action', 'full_present_name', 'autonomous_speech', 'respond_partner') else ()
                people.return_value = [CHARACTER, *present]
                pair_gate.return_value = '' if present else 'not present'
                furniture.return_value = dict(current=[dict(target={}, label='Ausruhen')] if ident == 'armchair_stop' else [], outgoing=[], incoming=[], recent_results=[])
                plans.return_value = 'a1b2c3d4 | Die Laterne holen' if ident == 'finished_plan' else ''
                rendered = build_tool_step_prompt(CHARACTER, mode=mode, rp_response=prose,
                    user_input='Möchtest du Tee?' if mode == 'respond' else '', tools=[skills[n] for n in candidates],
                    facts=TurnFacts(CHARACTER, mode, present, PARTNER if mode == 'respond' else ''), tool_format='tag')
                expect.setdefault('none', False)
                expect.setdefault('forbid_tools', []).append('SetActivity')
                cases.append(dict(id=ident, group='tools', task='intent' if mode == 'respond' else 'thought',
                    system=rendered.system, user=rendered.user, allowed_tools=rendered.offered,
                    sets=sets, expect=expect, repeats=3, reviewed=True, fmt='tool'))

        def helper(ident, task, rendered, sets, expect):
            system, user = rendered
            return dict(id=ident, group='helpers', task=task, fmt='json', system=system,
                        user=user, sets=sets, expect=expect, repeats=3, reviewed=True)

        from app.core.stat_sources import extraction_context
        from app.core.chat_stat_effects import build_stat_targets
        source = 'Character: Ich stehe vom Boden auf und halte die Laterne vor mich. Nach der kurzen Pause fühle ich mich wieder zufrieden.'
        context = extraction_context(CHARACTER, (), narrative=source, self_event_id='self:demo',
                                     started_at='2026-01-01T12:00:00Z', game_ts='2026-01-01T12:00:00')
        # Demo stat declarations; source identity and token construction stay production code.
        with patch('app.core.chat_stat_effects._stat_keys', return_value={'stamina'}), patch(
                'app.core.stat_effects.build_stat_list', return_value=(True, 'stamina: körperliche Energie')):
            targets = build_stat_targets(context)
        assert targets['required_stat_pairs'] == [{'event': 'S0', 'target': 'T0'}]
        state = render_task('extraction_chat_state', target_name=CHARACTER, piece_list='',
            source_label='Character reply', source_text=source, context_text='', outfit_locked=True,
            is_avatar=False, rp_first=True, ask_feeling=True, stats_enabled=True,
            pose_keys=['stand', 'sit', 'lie'], current_pose='sit: am Boden',
            **{k: targets[k] for k in ('stat_sources', 'stat_targets', 'required_stat_pairs')})
        de = {'lang': 'de', 'min': 1, 'max': 1000}
        cases.append(helper('state_extraction', 'extraction_chat_state', state,
            {'pose_keys': ['stand', 'sit', 'lie'], 'events': ['S0'], 'targets': ['T0']},
            dict(json_fields=['pose', 'detail', 'feeling', 'stat_results'], in_sets={'pose': 'pose_keys'},
                 types={'stat_results': 'array'}, min_items={'stat_results': 1},
                 items_fields={'stat_results': {'required': ['event', 'target', 'deltas'],
                     'in_sets': {'event': 'events', 'target': 'targets'}, 'types': {'deltas': 'object'}}},
                 text_fields={'detail': de, 'feeling': {'min': 1, 'max': 40}})))
        from app.core.memory_service import extract_memories_from_exchange
        captured = {}
        def capture(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content='{"memories": []}')
        with patch('app.core.llm_router.llm_call', side_effect=capture):
            extract_memories_from_exchange(CHARACTER, '', '',
                'Ich habe die Laterne dauerhaft neben der Tür im Flur aufgehängt. So bleibt der Eingang auch abends gut beleuchtet.', None, plans=False)
        assert captured, 'Facts-only render path did not reach the provider boundary'
        cases.append(helper('facts_only', 'extraction', (captured['system_prompt'], captured['user_prompt']),
            {'memory_types': ['semantic']}, dict(json_fields=['memories'], forbid_fields=['commitments', 'completed_ids'],
                types={'memories': 'array'}, min_items={'memories': 1}, items_fields={'memories': {
                    'required': ['memory_type', 'content', 'importance', 'tags'],
                    'in_sets': {'memory_type': 'memory_types'}, 'types': {'tags': 'array'}, 'text_fields': {'content': de}}})))
        npc = render_task('npc_action', npc_name=CHARACTER, npc_role='Bibliothekarin',
            standing_task='Ordne die Bücher und halte das Lesezimmer aufgeräumt.', location_name='Kieselhaus',
            current_room_id='hall', current_room_name='Flur', current_activity='Sortiert zurückgebrachte Bücher.',
            game_time_label='Tag 1, 14:00', rooms=[dict(id='hall', name='Flur', hint='Bücher zurückgeben', places=''),
                dict(id='reading_room', name='Lesezimmer', hint='Bücher ordnen und lesen', places='2 freie Sitzplätze')],
            home='', pose_keys=['stand', 'sit'], npc_goals='', arrival_reason='', dialogue_style='',
            talk_allowed=False, present=[], pair_keys=[], extension_prompt='', recent=[], prop_actions_block='')
        cases.append(helper('npc_room', 'npc_action', npc, {'room_ids': ['reading_room', 'hall'], 'pose_keys': ['stand', 'sit', '']},
            dict(json_fields=['room', 'activity', 'pose'], in_sets={'room': 'room_ids', 'pose': 'pose_keys'}, text_fields={'activity': de})))

        from app.imagegen.service import ImageService
        from app.routes.chat import _analyze_chat_image
        from app.core.config_schema import field_default
        for ident, task, image in [
            ('vision_analysis', 'image_analysis', 'worlds/demo/props/bench-c8540c/source.png'),
            ('vision_recognition', 'image_recognition', 'worlds/demo/props/lantern-8f652b/source.png'),
        ]:
            messages = []
            def submit(**kwargs):
                messages.extend(kwargs['messages_or_prompt'])
                return SimpleNamespace(content='Eine Ansicht. Sie ist ruhig.')
            instance = Mock()
            queue = Mock(submit=submit)
            with ExitStack() as stack:
                stack.enter_context(patch('app.core.llm_queue.get_llm_queue', return_value=queue))
                stack.enter_context(patch('app.core.llm_router.resolve_llm', return_value=instance))
                stack.enter_context(patch('app.routes.chat.get_character_language_instruction', return_value='German'))
                stack.enter_context(patch.dict('os.environ', IMAGE_ANALYSIS_LANGUAGE='de',
                    IMAGE_ANALYSIS_PROMPT=field_default('image_generation', 'image_analysis_prompt')))
                if task == 'image_analysis':
                    service = object.__new__(ImageService)
                    stack.enter_context(patch.object(service, '_get_vision_llm_config', return_value={'instance': instance}))
                    service._generate_image_analysis(str(ROOT / image), CHARACTER)
                else:
                    _analyze_chat_image(str(ROOT / image), CHARACTER)
            assert len(messages) == 2, ident
            cases.append(dict(id=ident, task=task, group='vision', fmt='text', image=image,
                system=messages[0]['content'], user=messages[1]['content'][0]['text'], sets={},
                expect={'min': 80, 'max': 1200, 'lang': 'de', 'plain_text': True}, repeats=3, reviewed=True))
        return {'cases': cases}


if __name__ == '__main__':
    target = ROOT / 'shared/config/suitability_curated_cases.json'
    result = build()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for case in result['cases']:
        print(f"{case['id']}: {len(case['system']) + len(case['user'])} prompt chars")
    print(f"Curated suitability cases: {len(result['cases'])} written.")
