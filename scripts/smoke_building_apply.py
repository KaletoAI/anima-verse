"""Task 4 without Blender: two adjacent 4x4 rooms yield an 8x4 contour.

A gap of 1 m exceeds the 0.3 m alignment tolerance and blocks all writes.
Stubbed furnishing reports one furnished room and one skipped room.
"""
import copy
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
paths.init(Path(tempfile.mkdtemp(prefix='building-apply-smoke-')))
from app.core import db
db.init_schema()
from app.core import building_assistant as ba
from app.core.location_model3d import claim_job, release_job
from app.core.layout_apply import _read_snapshot
from app.models import world
from app.core.world_ops import update_location_with_extras


def main():
    assert callable(getattr(ba, 'apply', None)), 'building_assistant.apply missing'
    draft = {'rooms': [dict(name='A', x=0, y=0, w=4, d=4),
                       dict(name='B', x=4, y=0, w=4, d=4)],
             'hull': {'style': 'steinhaus'}}
    real_thread = threading.Thread
    threads = []
    def launch(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread
    def join():
        threads[-1].join(5)
        assert not threads[-1].is_alive(), 'chain did not finish'
    def location():
        lid = world.add_location(f'House {len(threads)} {len(ba._statuses)}', 'Test', rooms=[])['id']
        update_location_with_extras(lid, {'entry_room': '', 'map3d': {'storey_height_m': 3.0}})
        return lid
    furnishings = {'rooms': [{'room_id': 'a', 'placed': 2}],
                   'skipped': [{'room_id': 'b', 'reason': 'has_furniture'}]}
    with patch.object(ba.threading, 'Thread', side_effect=launch), \
         patch.object(ba, 'generate_hull', return_value={'ok': True}) as build, \
         patch.object(ba, 'propose_hull', return_value={'description_json': {'style': 'steinhaus'}}) as proposal, \
         patch.object(ba, 'kit_for_location', return_value='kit') as kit, \
         patch.object(ba, 'furnish_location', return_value=furnishings) as furnish, \
         patch.object(ba, 'find_building_model', return_value=Path('/tmp/old.glb')), \
         patch.object(ba, 'select_model', return_value=True) as select:
        lid = location()
        before = copy.deepcopy(world.get_location_by_id(lid))
        result = ba.apply(lid, draft)
        assert result['ok'], result
        snapshot = _read_snapshot(result['snapshot_id'])
        join()
        state = ba.status(lid)
        assert state['state'] == 'done', state
        assert [s['state'] for s in state['steps']] == ['done'] * 3
        assert state['steps'][2]['counts'] == {'rooms': 1, 'skipped': 1, 'reasons': {'has_furniture': 1}}
        assert ba.undo(lid, result['snapshot_id'])['reselected'] == 'old.glb'
        select.assert_called_once_with(lid, 'old.glb')
        after = world.get_location_by_id(lid)
        for key in ('rooms', 'map3d', 'entry_room'):
            assert after.get(key) == snapshot[key] == before.get(key), (key, after.get(key), snapshot[key], before.get(key))
        assert ba.status(lid)['state'] == 'idle'
        assert ba.undo(lid, 'missing')['error'] == 'not_found'
        lid = location()
        before = world.get_location_by_id(lid)
        bad = copy.deepcopy(draft)
        bad['rooms'][1]['x'] = 5
        assert ba.apply(lid, bad)['error'] == 'contour'
        assert world.get_location_by_id(lid) == before
        assert claim_job(lid, kind='hull')
        try:
            assert ba.apply(lid, draft)['error'] == 'busy'
            assert world.get_location_by_id(lid) == before
        finally:
            release_job(lid, kind='hull')
        build.return_value = {'ok': False, 'error': 'build broke'}
        furnish.reset_mock()
        ba.apply(lid, draft)
        join()
        state = ba.status(lid)
        assert state['state'] == 'failed' and state['steps'][1]['message'] == 'build broke'
        assert state['steps'][2]['state'] == 'skipped'
        furnish.assert_not_called()
        build.return_value = {'ok': True}
        lid = location()
        ba.apply(lid, {**draft, 'hull': {'style': 'unknown'}})
        join()
        proposal.assert_called_once_with(lid)
        entered, proceed = threading.Event(), threading.Event()
        def blocking(*args):
            entered.set()
            assert proceed.wait(5)
            return {'ok': True}
        build.side_effect = blocking
        lid = location()
        result = ba.apply(lid, draft)
        try:
            assert entered.wait(5)
            assert ba.undo(lid, result['snapshot_id'])['error'] == 'busy'
            assert not claim_job(lid, kind='hull')
        finally:
            proceed.set()
            join()
        build.side_effect = None
        lid = location()
        with patch.object(ba, 'apply_layout', side_effect=RuntimeError('write failed')):
            try:
                ba.apply(lid, draft)
                raise AssertionError('write failure swallowed')
            except RuntimeError as exc:
                assert str(exc) == 'write failed'
        assert claim_job(lid, kind='hull')
        release_job(lid, kind='hull')
        kit.return_value = None
        result = ba.apply(lid, draft, {'style': 'steinhaus', 'seed': 17})
        join()
        assert build.call_args.args[1]['seed'] == 17
        assert ba.status(lid)['steps'][2]['message'] == 'no kit for this style'
        assert ba.status(lid)['state'] == 'done'
        kit.return_value = 'kit'
        furnish.side_effect = RuntimeError('furniture broke')
        lid = location()
        ba.apply(lid, draft)
        join()
        state = ba.status(lid)
        assert state['state'] == 'failed'
        assert state['steps'][2]['message'] == 'furniture broke'
        assert state['steps'][1]['state'] == 'done'
        furnish.side_effect = None
        entered.clear()
        proceed.clear()
        def blocking_furnish(*args, **kwargs):
            entered.set()
            assert proceed.wait(5)
            return furnishings
        furnish.side_effect = blocking_furnish
        lid = location()
        result = ba.apply(lid, draft)
        try:
            assert entered.wait(5)
            assert ba.status(lid)['steps'][1]['state'] == 'done'
            assert ba.apply(lid, draft)['error'] == 'busy'
            assert ba.undo(lid, result['snapshot_id'])['error'] == 'busy'
        finally:
            proceed.set()
            join()
        assert claim_job(lid, kind='hull')
        release_job(lid, kind='hull')
        other = location()
        before = world.get_location_by_id(other)
        assert ba.undo(other, result['snapshot_id'])['error'] == 'not_found'
        assert world.get_location_by_id(other) == before
        view = ba.status(lid)
        view['steps'].clear()
        assert len(ba.status(lid)['steps']) == 3
        from app.core.auth_dependency import is_admin_only_path
        for action in ('apply', 'undo'):
            assert is_admin_only_path(f'/world/locations/{lid}/building-assistant/{action}', 'POST')
    print('PASS apply chain, counts, hull failure, contour, guard, undo, running undo, fallback')


if __name__ == '__main__':
    main()
