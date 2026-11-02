#!/usr/bin/env python3
"""Trip consent ends membership at the agreed terminal signal.

Usage: ./.venv/bin/python scripts/smoke_party_trip_lifetime.py

Hand-derived expectations: a temporary host and a regular host each propose
Home / Loft to a player avatar in Home / Kitchen. Each call creates exactly
one active travel_together intent and pending invite; the real play scene
projects the destination label and id. The existing player answer route joins
the avatar to the proposer and moves both to Loft, completing that intent.
Arrival must leave zero party members and restore independent movement.
With an activity, one party persists until its exact end; a pre-existing party
keeps both followers; cancellation after consent leaves zero members. Recovery
of a persisted done intent must also leave zero members, twice without effect.
An existing follower returns refusal text and emits no ERROR traceback.
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
        from app.core import hooks
        from app.core import party_engine as party
        from plugins.party import trip_intents as T, undertakings as U
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
                assert party.get_party_of(avatar) is None, 'trip-created party survived arrival'
                assert intents.get_intent(intent['id'])['status'] == 'done'
                assert not party.get_party_of(leader)
                assert not play_scene(user=user)['party']
                from app.core.movement_authority import movement_allowed
                assert movement_allowed(avatar, location, 'kitchen')[0]
                result2 = invite.execute(json.dumps({'agent_name': leader, 'target': avatar,
                    'destination': {'location_id': location, 'room_id': 'kitchen'}}))
                pending2 = party.find_pending_invite(leader, avatar)
                assert pending2 and pending2['invite_id'] != pending['invite_id'], result2
                second = intents.get_intent(pending2['intent_id'])
                assert any(i['invite_id'] == pending2['invite_id'] for i in play_scene(user=user)['party_invites'])
                assert intents.cancel_intent(second['id'])
                print(f'PASS {leader}: tool -> intent -> play Join chip -> consent -> both arrive')
            def reset_pair():
                for name in ('Demo Guide', avatar):
                    party.leave_party(name)
                    chars.save_character_current_room(name, 'kitchen')

            def propose(**kwargs):
                return T.propose_trip('Demo Guide', avatar,
                                      {'location_id': location, 'room_id': 'loft'}, **kwargs)

            def accept(plan):
                return T.respond(T._state(intents.get_intent(plan['id']))['invite_id'], True)

            reset_pair()
            hooks.register_provider('shared_activity_validate', lambda a, b, action: action)
            hooks.register_provider('shared_activity_status', lambda *args: {'status': 'running', 'interaction_id': 'demo-activity'})
            hooks.register_provider('shared_activity_request', lambda *args: {'status': 'running', 'interaction_id': 'demo-activity'})
            plan = propose(after_arrival={'type': 'pair', 'pose_key': 'demo-pair'})
            accept(plan)
            assert party.is_party_follower(avatar)
            assert intents.get_intent(plan['id'])['status'] == 'active'
            U.ended('Demo Guide', avatar, 'demo-activity')
            assert intents.get_intent(plan['id'])['status'] == 'done'
            assert party.get_party_of(avatar) is None
            print('PASS activity persists through arrival and releases on actual end')

            reset_pair()
            party.add_to_party('Demo Guide', 'Demo Host')
            chars.save_character_current_room('Demo Host', 'kitchen')
            plan = propose(scope='party')
            accept(plan)
            assert intents.get_intent(plan['id'])['status'] == 'done'
            assert set(party.party_followers('Demo Guide')) == {'Demo Host', avatar}
            with patch.object(invite.ctx.logger, 'exception') as errors:
                result = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': avatar,
                    'destination': {'location_id': location, 'room_id': 'kitchen'}}))
                assert 'already travelling with you' in result, result
                errors.assert_not_called()
            with patch.object(invite.ctx.logger, 'exception') as errors:
                result = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': 'Demo Host',
                    'destination': {'location_id': location, 'room_id': 'missing'}}))
                assert 'already travelling with you' in result
                errors.assert_not_called()
            print('PASS pre-existing party retained; existing follower refused without ERROR')

            reset_pair()
            world.set_world_setting('world_frozen', '1')
            plan = propose()
            accept(plan)
            assert party.is_party_follower(avatar)
            assert intents.cancel_intent(plan['id'])
            assert not party.get_party_of(avatar)
            world.set_world_setting('world_frozen', '0')
            print('PASS cancellation after consent releases party')
            with patch.object(invite.ctx.logger, 'exception') as errors:
                result = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': avatar,
                    'destination': {'location_id': location, 'room_id': 'missing'}}))
                assert 'Trip proposal refused:' in result, result
                errors.assert_not_called()
            print('PASS other proposal ValueErrors return a clean refusal')


            reset_pair()
            plan = propose()
            # Simulate process death after atomic settlement, before runtime receipt.
            iid = T._state(intents.get_intent(plan['id']))['invite_id']
            assert party.settle_pending_invite(iid, True)['status'] == 'accepted'
            assert intents.cancel_intent(plan['id'])
            assert not party.get_party_of(avatar)
            print('PASS cancellation recovers consent receipt after interrupted settlement')

            reset_pair()
            world.set_world_setting('world_frozen', '1')
            plan = propose()
            accept(plan)
            from app.core.timeutils import game_time
            from app.core.game_time import GameDuration
            intents.update_intent(plan['id'], expires_at=(game_time() - GameDuration.of(seconds=1)).canonical())
            assert intents.get_intent(plan['id'])['status'] == 'expired'
            assert not party.get_party_of(avatar)
            world.set_world_setting('world_frozen', '0')
            print('PASS expiry after consent releases party')


            reset_pair()
            plan = propose()
            with patch.object(T, '_release_party'):
                accept(plan)
            assert intents.get_intent(plan['id'])['status'] == 'done'
            assert party.is_party_follower(avatar)
            hooks.emit('startup')
            assert not party.get_party_of(avatar)
            T.world_tick()
            assert not party.get_party_of(avatar)
            print('PASS restart reconciliation releases a terminal trip idempotently')
            chars.save_character_current_room(avatar, 'loft')
            result = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': avatar}))
            pending = party.find_pending_invite('Demo Guide', avatar)
            assert pending and not pending.get('intent_id'), result
            assert _play_party_respond_sync(user, {'invite_id': pending['invite_id'], 'accept': True})['ok']
            print('PASS plain avatar invitation preserved')


if __name__ == '__main__':
    main()
