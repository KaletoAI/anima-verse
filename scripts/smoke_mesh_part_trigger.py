"""Usage: .venv/bin/python scripts/smoke_mesh_part_trigger.py

Hand-derived: off→on schedules exactly one worker, renders T-pose then mesh
(two ordered calls), despite auto_generate=false. on→on schedules zero.
A failed save schedules zero; disabled media logs once and never meshes.
The generation callback must run after the character profile lock is released.
"""
import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core import character_ops as co, model_refs as mr, model3d as m3, body_slots as bs
    from app.plugins.registry import BodySlotSpec, MeshPartSpec
    from app.imagegen.base import MediaGenerationDisabled
    slot = BodySlotSpec('slot', 'fixture', attributes={'switch': {'type': 'select', 'options': ['off', 'on']}},
                        mesh_part=MeshPartSpec('switch', 'part', 'flat slot', 'size', {}, {}))
    profile = {'body_slots': {'slot': {'switch': 'off'}}, 'model3d_opts': {'auto_generate': False}}
    calls = []
    class Worker:
        def __init__(self, target, args=(), kwargs=None, **_):
            self.run = lambda: target(*args, **(kwargs or {}))
        def start(self):
            self.run()
    def save(_, value):
        profile.clear()
        profile.update(copy.deepcopy(value))
        return True
    def render(*_, **kwargs):
        from app.core.keyed_lock import keyed_lock
        assert not keyed_lock('character_profile', 'fixture')._is_owned()
        assert kwargs['kinds'] == ('tpose',) and kwargs['force'] is False
        calls.append('tpose')
    with patch.object(bs, 'slots_for_character', return_value=[slot]), patch('app.models.character.get_character_profile', side_effect=lambda _: copy.deepcopy(profile)), patch('app.models.character.save_character_profile', side_effect=save), patch.object(mr.threading, 'Thread', Worker), patch.object(mr, 'generate_model_ref_images', side_effect=render), patch.object(mr, 'current_outfit_state', return_value=({}, [], 'new')), patch.object(mr, 'find_ref_image', return_value=Path(tmp)/'input.png'), patch.object(m3, 'find_model3d', return_value=None), patch.object(m3, 'trigger_generation', side_effect=lambda *_: calls.append('mesh')):
        co.apply_body_slot_values('fixture', 'slot', {'switch': 'on'})
        assert calls == ['tpose', 'mesh'], calls
        calls.clear()
        co.apply_body_slot_values('fixture', 'slot', {'switch': 'on'})
        assert calls == []
        with patch.object(mr, 'generate_model_ref_images', side_effect=MediaGenerationDisabled('disabled')), patch.object(co, 'logger') as log:
            co.apply_body_slot_values('fixture', 'slot', {'switch': 'off'})
            assert log.info.called and calls == []
        with patch('app.models.character.save_character_profile', return_value=False):
            try:
                co.apply_body_slot_values('fixture', 'slot', {'switch': 'on'})
            except Exception:
                pass
            else:
                raise AssertionError('failed save reported success')
            assert calls == []
print('PASS mesh_part trigger: ordered render/mesh, unchanged, disabled, failed save')
