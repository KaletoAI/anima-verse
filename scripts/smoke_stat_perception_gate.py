#!/usr/bin/env python3
"""Check deterministic, effective-stat hearing in temporary storage.

Usage: ./.venv/bin/python scripts/smoke_stat_perception_gate.py
Hand-derived: 15 < 20 loses content; 20 == 20 keeps it. A +5 boost
raises 15 to 20. Addressed listeners always hear; shouts and whispers keep
existing semantics. Missing stats and a disabled gate keep content.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import perception as p, stat_rules
        from app.models import perception_store
        from app.core.chat_engine import _messages_from_room_stream
        args = dict(speaker='A', addressees=['B'], room_members=['A', 'B', 'C'], location_others=[])
        targets = {t.perceiver: t for t in p.compute_earshot(**args, volume='normal', inattentive=['B', 'C'])}
        assert targets['B'].gets_content and targets['B'].kind == p.KIND_IN_ROOM
        assert not targets['C'].gets_content and targets['C'].kind == p.KIND_INATTENTIVE_META
        for volume, kind, content in [('normal', p.KIND_IN_ROOM, True), ('shout', p.KIND_IN_ROOM, True), ('whisper', p.KIND_WHISPER_META, False)]:
            t = {t.perceiver: t for t in p.compute_earshot(**args, volume=volume, inattentive=[] if volume == 'normal' else ['C'])}['C']
            assert (t.kind, t.gets_content) == (kind, content)
        assert _messages_from_room_stream('C', [{'speaker': 'A', 'kind': p.KIND_INATTENTIVE_META, 'content': 'must not leak'}]) == []
        print('PASS pure routing, addressed exception, volumes and transcript privacy')
        stat_rules.save_setting('perception_gate', {'enabled': True, 'stat': 'focus_test', 'below': 20})
        profile = {'status_effects': {'focus_test': 15}}
        with patch.object(p, '_resolve_presence', return_value=(['A', 'B', 'C'], [], [])), patch('app.models.character.get_character_profile', side_effect=lambda name: profile), patch('app.models.character.get_character_pos', return_value=None):
            for value, enabled, expected in [(15, True, 'inattentive_meta'), (20, True, 'in_room'), (15, False, 'in_room'), (None, True, 'in_room')]:
                profile['status_effects'] = {} if value is None else {'focus_test': value}
                stat_rules.save_setting('perception_gate', {'enabled': enabled, 'stat': 'focus_test', 'below': 20})
                uid = p.record_utterance(speaker='A', content='secret detail', location_id='room-test', room_id='r', addressees=['B'])
                assert uid
                rows = perception_store.get_character_room_stream('C', 'room-test', 'r', limit=50)
                row = next(r for r in rows if r['utterance_id'] == uid)
                assert row['kind'] == expected, row
                assert row['content'] == ('' if expected == 'inattentive_meta' else 'secret detail')
            # A player-controlled listener is never gated, even at 15 < 20.
            profile['status_effects'] = {'focus_test': 15}
            stat_rules.save_setting('perception_gate', {'enabled': True, 'stat': 'focus_test', 'below': 20})
            with patch('app.models.account.is_player_controlled', side_effect=lambda name: name == 'C'):
                assert p.inattentive_listeners(['B', 'C']) == ['B']
            print('PASS player-controlled listener is never gated')
            from app.core import prompt_filters
            shared = Path(tmp) / 'boost-filters.json'
            shared.write_text(json.dumps({'filters': [{'id': 'focus', 'enabled': True,
                                                       'stat_boosts': {'focus_test': 5}}]}))
            profile['status_effects'] = {'focus_test': 15}
            profile['active_conditions'] = [{'name': 'focus'}]
            with patch.object(prompt_filters, '_SHARED_FILE', shared):
                prompt_filters.invalidate_filter_snapshot()
                uid = p.record_utterance(speaker='A', content='boosted detail', location_id='room-test', room_id='r')
                row = next(r for r in perception_store.get_character_room_stream('C', 'room-test', 'r') if r['utterance_id'] == uid)
                assert row['kind'] == 'in_room' and row['content'] == 'boosted detail'
            prompt_filters.invalidate_filter_snapshot()
            profile['active_conditions'] = []
            from app.core.agent_loop import AgentLoop
            loop = AgentLoop()
            key = loop._room_key('room-test', 'r', 'A')
            loop._chime_backstop = 1
            loop._room_ai_turns[key] = 1
            with patch('app.core.room_entry.characters_in_room', return_value=['A', 'C']), patch.object(p, 'nearby_in_the_open', return_value=[]), patch('app.models.character.get_character_current_location', return_value='room-test'), patch('app.models.character.get_movement_target', return_value=''), patch.object(loop, '_avatar_holds_floor', return_value=False), patch('app.core.agent_loop._is_respond_eligible', return_value=True), patch.object(loop, 'bump_respond', return_value=True) as bump:
                out = loop.dispatch_room_reactions(speaker='A', content='private detail', volume='normal', location_id='room-test', room_id='r')
                assert out == {'obligatory': [], 'chime': []}, out
                bump.assert_not_called()
                loop._room_ai_turns[key] = 0
                out = loop.dispatch_room_reactions(speaker='A', content='normal detail', volume='normal', location_id='room-test', room_id='r', is_avatar=True)
                assert out == {'obligatory': [], 'chime': []}, out
                bump.assert_not_called()
                loop._room_ai_turns[key] = 1
                # Direct address still wakes the listener even on the winddown path.
                loop._room_winddown_done.clear()
                loop.dispatch_room_reactions(speaker='A', content='direct detail', volume='normal', location_id='room-test', room_id='r', addressees=['C'])
                assert bump.call_args.args[0] == 'C'
        print('PASS persisted threshold, disabled/missing stats, effective boosts and reaction gate')


if __name__ == '__main__':
    main()
