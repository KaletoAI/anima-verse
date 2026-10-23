"""Verify Task 12 rewards without external calls.

Usage: ./.venv/bin/python scripts/smoke_stat_rewards.py
Hand-derived: plan completion raises 50 by 2 to 52 once; a gift raises
its recipient by 3 to 55, leaving the giver at 50. Empty/zero settings
change nothing. Resolution dispatches exactly one asynchronous evaluation.
Concurrent attempt/image writers cannot undo resolution or permit a second reward.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction, get_connection
        init_schema()
        from app.models import character, intents, inventory, events
        for name in ('Recipient', 'Giver'):
            with transaction() as conn:
                conn.execute('INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (name, 'test', json.dumps({'status_effects': {'courage': 50}}), '{}', '', ''))
        from app.core import stat_rewards, stat_rules
        stat_rules.save_setting('rewards', {'intent_done': {'courage': 2}, 'gift_received': {'courage': 3}})
        stat_rewards.register_hooks()
        stat_rewards.register_hooks()
        intent = intents.create_intent(owner='Recipient', title='Finish task')
        intents.update_intent(intent['id'], status='done')
        intents.update_intent(intent['id'], status='done')
        assert character.get_character_profile('Recipient')['status_effects']['courage'] == 52
        # Upserts use the same status-transition contract.
        intents.create_intent(owner='Recipient', title='Finish task', status='done', intent_id=intent['id'])
        assert character.get_character_profile('Recipient')['status_effects']['courage'] == 52
        item = inventory.add_item('Present', item_id='reward_present')
        assert inventory.add_to_inventory('Giver', item['id'])
        assert inventory.gift_item('Giver', 'Recipient', item['id'])['success']
        assert character.get_character_profile('Recipient')['status_effects']['courage'] == 55
        assert character.get_character_profile('Giver')['status_effects']['courage'] == 50
        assert not inventory.gift_item('Giver', 'Recipient', item['id'])['success']
        assert character.get_character_profile('Recipient')['status_effects']['courage'] == 55
        rows = [json.loads(r[0]) for r in get_connection().execute('SELECT state_json FROM state_history')]
        sources = [r['metadata']['source'] for r in rows if r['type'] == 'effects']
        assert sources.count('intent_done') == sources.count('gift_received') == 1, sources
        for setting in ({}, {'intent_done': {'courage': 0}}):
            stat_rules.save_setting('rewards', setting)
            assert stat_rewards.apply_reward('Recipient', 'intent_done') == {}
        pending = []
        class DeferredThread:
            def __init__(self, target, args=(), kwargs=None, daemon=False, **unused):
                assert daemon
                self.run = lambda: target(*args, **(kwargs or {}))
            def start(self):
                pending.append(self.run)
        with patch('app.core.stat_rewards.threading.Thread', DeferredThread), patch(
                'app.core.stat_effects.evaluate_stat_effects') as evaluate, patch(
                'app.core.event_images.trigger_resolved_image_from_text'):
            event = events.add_event('A dangerous situation', category='danger')
            assert events.resolve_event(event['id'], 'Recipient')['resolved']
            events.resolve_event(event['id'], 'Recipient')
            assert len(pending) == 1 and not evaluate.called
            pending.pop()()
            evaluate.assert_called_once_with('Recipient',
                'Recipient just resolved this situation: A dangerous situation. Judge the immediate aftermath.', source='event_resolved')
            for unknown in ('', 'Nobody'):
                stat_rewards.on_event_resolved(event, unknown)
            assert not pending
            # A failing evaluator stays inside the worker.
            evaluate.side_effect = RuntimeError('offline')
            stat_rewards.on_event_resolved(event, 'Recipient')
            pending.pop()()
        # A stale attempt/image snapshot must not undo a concurrent resolution.
        for operation in ('attempt', 'image'):
            event = events.add_event('A concurrent danger', category='danger')
            snapshot_taken = threading.Event()
            resume_writer = threading.Event()
            resolved_finished = threading.Event()
            failures = []
            real_get = events.get_event
            def paused_get(event_id):
                result = real_get(event_id)
                if threading.current_thread().name == 'stale-writer':
                    snapshot_taken.set()
                    assert resume_writer.wait(5)
                return result
            def write():
                try:
                    if operation == 'attempt':
                        events.record_attempt(event['id'], 'Recipient', 'try', 'fail')
                    else:
                        events.update_event_fields(event['id'], image_path='after.png')
                except Exception as exc:
                    failures.append(exc)
            def resolve():
                try:
                    events.resolve_event(event['id'], 'Recipient')
                except Exception as exc:
                    failures.append(exc)
                finally:
                    resolved_finished.set()
            with patch('app.models.events.get_event', side_effect=paused_get), patch(
                    'app.core.stat_rewards.on_event_resolved') as reward, patch(
                    'app.core.event_images.trigger_resolved_image_from_text'):
                writer = threading.Thread(target=write, name='stale-writer')
                resolver = threading.Thread(target=resolve)
                writer.start()
                assert snapshot_taken.wait(5)
                resolver.start()
                resolved_finished.wait(0.2)
                resume_writer.set()
                writer.join(5)
                resolver.join(5)
                assert not writer.is_alive() and not resolver.is_alive() and not failures, failures
                assert real_get(event['id']).get('resolved'), operation
                events.resolve_event(event['id'], 'Recipient')
                assert reward.call_count == 1, (operation, reward.call_count)
        print('PASS rewards: transitions, gift recipient, disabled settings, history, background resolution')


if __name__ == '__main__':
    main()
