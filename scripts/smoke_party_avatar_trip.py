#!/usr/bin/env python3
"""Avatar consent resumes the same-room-location trip proposed by either actor.

Usage: ./.venv/bin/python scripts/smoke_party_avatar_trip.py

Hand-derived expectations: a temporary host and a regular host each propose
Home / Loft to a player avatar in Home / Kitchen. Each call creates exactly
one active travel_together intent and pending invite; the real play scene
projects the destination label and id. The existing player answer route joins
the avatar to the proposer and moves both to Loft, completing that intent.
A plain avatar invitation still remains pending and accepts normally. No LLM
or live world is used; paths are initialized before all world model imports.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='party-avatar-trip-') as tmp:
        root = Path(tmp)
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import paths
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        (root / 'instance' / 'config.json').write_text(json.dumps({
            'providers': [], 'embedding': {'backend': 'external'}}))
        from app.core import config, db
        config.load(root / 'world' / 'config.json')
        db.init_schema()
        cfg = config.get_all()
        cfg['packages'] = {'enabled': 'party'}
        cfg.setdefault('image_generation', {})['enabled'] = False
        config.save(cfg)
        from app.core.dependencies import get_skill_manager
        from app.core import party_engine as party
        from app.core.users import create_user, update_user
        from app.models import character as chars, intents, world
        from app.plugins.context import PluginContext
        from app.routes.play import play_scene, _play_party_respond_sync
        from plugins.party.skill import PartySkill
        get_skill_manager()
        location = world.add_location('Home', 'Two rooms', rooms=[
            {'id': 'kitchen', 'name': 'Kitchen'}, {'id': 'loft', 'name': 'Loft'}])['id']
        avatar = 'Demo Avatar'
        for name, template in [(avatar, 'human-roleplay'), ('Demo Host', 'npc-temporary'),
                               ('Demo Guide', 'human-roleplay')]:
            assert chars.save_character_profile(name, {'character_name': name,
                'template': template, 'language': 'en', 'current_location': location,
                'current_room': 'kitchen', 'standing_task': 'welcomes visitors'}, create_new=True)
            chars.set_known_locations(name, [location])
        user = create_user('demo', 'smoke-password', allowed_characters=[avatar])
        assert update_user(user, settings={'active_character': avatar})
        invite = PartySkill({}, PluginContext('party'), 'invite')
        with patch('app.models.account.get_active_character', return_value=avatar):
            for leader in ('Demo Host', 'Demo Guide'):
                chars.save_character_current_room(avatar, 'kitchen')
                result = invite.execute(json.dumps({'agent_name': leader, 'target': avatar,
                    'destination': {'location_id': location, 'room_id': 'loft'}}))
                pending = party.find_pending_invite(leader, avatar)
                assert pending and pending.get('intent_id'), result
                intent = intents.get_intent(pending['intent_id'])
                assert intent['status'] == 'active' and intent['action']['type'] == 'travel_together'
                assert len(intents.list_intents(status='active')) == 1
                assert all(chars.get_character_current_room(n) == 'kitchen' for n in (leader, avatar))
                from app.core.streaming import open_questions_note
                question = open_questions_note(avatar, {'JoinParty': None}, '')
                assert 'OPEN QUESTIONS' in question and pending['invite_id'] in question
                scene = play_scene(user=user)
                projected = next(i for i in scene['party_invites'] if i['invite_id'] == pending['invite_id'])
                assert projected['destination_label'] == 'Home / Loft', projected
                answer = _play_party_respond_sync(user, {'invite_id': pending['invite_id'], 'accept': True})
                assert answer['ok'], answer
                assert all(chars.get_character_current_room(n) == 'loft' for n in (leader, avatar))
                assert party.get_party_of(avatar) is None
                assert intents.get_intent(intent['id'])['status'] == 'done'
                party.leave_party(leader)
                print(f'PASS {leader}: tool -> intent -> play Join chip -> consent -> both arrive')
            chars.save_character_current_room(avatar, 'loft')
            result = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': avatar}))
            pending = party.find_pending_invite('Demo Guide', avatar)
            assert pending and not pending.get('intent_id'), result
            assert _play_party_respond_sync(user, {'invite_id': pending['invite_id'], 'accept': True})['ok']
            print('PASS plain avatar invitation preserved')


if __name__ == '__main__':
    main()
