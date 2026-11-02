#!/usr/bin/env python3
"""Party tool decisions restore ids and consent without large prompts.

Usage: ./.venv/bin/python scripts/smoke_party_tool_step.py

Hand-derived expectations: Home's kitchen (level 0) is current, so only its
loft (level 1) is a local destination, labelled "upstairs" because Home has
two storeys; the reserved ground (`__ground__`) and corridor (`__floor__1`)
rooms are absent — they carry no flag in storage, only their reserved ids.
Park carries no room: the trip resolves its arrival room itself. Each destination is a JSON object, copied unchanged. A pending
party question includes its exact invitation id in both yes/no calls. Two
question providers contribute independently, including around a failing third.
Only a short available activity list permits an after_arrival descriptor.
All reads of storage use a disposable world initialized before model imports.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='party-tool-step-') as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        from app.core import db, hooks, streaming
        db.init_schema()
        from app.plugins.context import PluginContext
        from plugins.party.skill import PartySkill
        from plugins.party import trip_intents as trips
        invite = PartySkill({}, PluginContext('party'), 'invite')
        locations = [{'id': 'home', 'name': 'Home'}, {'id': 'park', 'name': 'Park'}]
        rooms = [{'id': 'kitchen', 'name': 'Kitchen', 'layout': {'level': 0}},
                 {'id': 'loft', 'name': 'Loft', 'layout': {'level': 1}},
                 {'id': '__ground__', 'name': ''}, {'id': '__floor__1', 'name': '', 'level': 1}]
        with patch.object(trips, 'list_locations_for_character', return_value=locations), \
             patch.object(trips, 'get_character_current_location', return_value='home'), \
             patch.object(trips, 'get_character_current_room', return_value='kitchen'), \
             patch.object(trips, 'get_location_by_id', return_value=locations[0]), \
             patch.object(trips, 'get_location_rooms', return_value=rooms):
            menu = invite.decision_menu('Demo Host')
            assert len(menu) == 2, menu
            objects = [json.loads(line.split(' = ', 1)[1]) for line in menu]
            assert objects == [{'location_id': 'home', 'room_id': 'loft'},
                               {'location_id': 'park'}], objects
            assert menu[0].startswith('Home / Loft (upstairs) = '), menu
            manager = Mock(get_skill_by_name=lambda name: invite)
            with patch('app.core.dependencies.get_skill_manager', return_value=manager):
                note = streaming.decision_menu_note('Demo Host', {'InviteToParty': None}, '')
                assert 'copy destination objects' in note and 'takes these names' not in note
                with patch.object(invite, 'tool_decision_context', side_effect=ValueError('scripted context failure')):
                    assert '"room_id":"loft"' in streaming.decision_menu_note('Demo Host', {'InviteToParty': None}, '')
        print('PASS destination objects, same-location room, reserved rooms, heading')
        with patch('app.core.hooks.get_provider', return_value=None):
            assert invite.tool_decision_context('Demo Host') == ''
        with patch('app.core.hooks.get_provider', return_value=lambda: ['embracing']):
            context = invite.tool_decision_context('Demo Host')
            assert 'after_arrival' in context and '"type":"pair"' in context and 'embracing' in context
        with patch('app.core.hooks.get_provider', return_value=lambda: ['key'] * 9):
            assert invite.tool_decision_context('Demo Host') == ''
        print('PASS optional activity keys only for a short available provider list')
        saved = dict(hooks._providers), dict(hooks._provider_owners)
        # The public registry must preserve several implementations of this capability.
        try:
            hooks.unregister_owned_providers('party-smoke')
            hooks.register_provider('tool_decision.open_questions', lambda *a: ['first question'], owner='party-smoke', multiple=True)
            def fail(*args):
                raise ValueError('scripted question failure')
            hooks.register_provider('tool_decision.open_questions', fail, owner='broken-smoke', multiple=True)
            hooks.register_provider('tool_decision.open_questions', lambda *a: ['second question'], owner='second-smoke', multiple=True)
            note = streaming.open_questions_note('Demo Host', {'JoinParty': None}, '')
            assert 'first question' in note and 'second question' in note, note
            hooks.unregister_owned_providers('second-smoke')
            assert 'second question' not in streaming.open_questions_note('Demo Host', {}, '')
        finally:
            for owner in ('party-smoke', 'second-smoke', 'broken-smoke'):
                hooks.unregister_owned_providers(owner)
            hooks._providers.clear()
            hooks._providers.update(saved[0])
            hooks._provider_owners.clear()
            hooks._provider_owners.update(saved[1])
        with patch('app.core.party_engine.get_pending_invites_for', return_value=[{
                'inviter': 'Demo Leader', 'invitee': 'Demo Host', 'invite_id': 'pinv_demo',
                'destination_label': 'Home / Loft'}]):
            lines = trips.open_questions('Demo Host', ['JoinParty'])
            assert len(lines) == 1 and 'Home / Loft' in lines[0]
            for answer in ('yes', 'no'):
                assert json.dumps({'leader': 'Demo Leader', 'answer': answer, 'invite_id': 'pinv_demo'}) in lines[0]
            assert trips.open_questions('Demo Host', []) == []
        print('PASS multiple question providers, failure isolation, exact party answers')
        with patch('app.models.character.get_character_profile', return_value={
                'outfit_description': 'blue coat', 'outfit_worn': True}):
            from plugins.undress.skill import UndressSkill
            clothing = UndressSkill({}, PluginContext('undress'), False)
            assert 'blue coat' in clothing.tool_decision_context('Demo Host')
        print('PASS skill-owned current clothing context')


if __name__ == '__main__':
    main()
