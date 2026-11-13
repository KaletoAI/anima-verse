"""Usage: .venv/bin/python scripts/smoke_mesh_part_trigger.py

Hand-derived: off→on schedules exactly one worker, renders T-pose then mesh
(two ordered calls), despite auto_generate=false. on→on schedules zero.
A failed save schedules zero; disabled media logs once and never meshes.
The generation callback must run after the character profile lock is released.
All of that is the path OFF the figure pipeline (``base_body.is_base_pipeline`` False).

Ruling FR-I5 (final review of plan 2026-11-12-unified-worn-pieces): ON the figure
pipeline a switch change only saves and marks the figure due — off→on and on→off
each call ``figure.invalidate`` once and render, mesh, start or request NOTHING
(``generate_model_ref_images``, ``trigger_generation``, ``figure_build.start`` /
``request`` and the image service are recorders: 0 calls). Fails on the old code:
at commit 5eab1741 ``apply_body_slot_values`` scheduled the regeneration for every
character (no ``is_base_pipeline`` branch).
"""
import subprocess
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
                        mesh_part=MeshPartSpec('switch', 'flat slot', [], {'part': {'params': {}, 'attribute_params': {}}}))
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
    with patch.object(bs, 'slots_for_character', return_value=[slot]), patch('app.models.character.get_character_profile', side_effect=lambda _: copy.deepcopy(profile)), patch('app.models.character.save_character_profile', side_effect=save), patch.object(mr.threading, 'Thread', Worker), patch.object(mr, 'generate_model_ref_images', side_effect=render), patch.object(mr, 'current_outfit_state', return_value=({}, [], 'new')), patch.object(mr, 'find_ref_image', return_value=Path(tmp)/'input.png'), patch.object(m3, 'find_model3d', return_value=None), patch.object(m3, 'trigger_generation', side_effect=lambda *_: calls.append('mesh')), patch('app.core.base_body.is_base_pipeline', return_value=False):
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
    # Ruling FR-I5: on the figure pipeline a switch change only saves and marks the figure due.
    from app.core import base_body as bb, figure as fig, figure_build as fb
    from app.imagegen import service as image_service
    marks, hub = [], []
    profile.clear()
    profile.update({'body_slots': {'slot': {'switch': 'off'}}, 'model3d_opts': {'auto_generate': True}})
    with patch.object(bs, 'slots_for_character', return_value=[slot]), patch('app.models.character.get_character_profile', side_effect=lambda _: copy.deepcopy(profile)), patch('app.models.character.save_character_profile', side_effect=save), patch.object(mr.threading, 'Thread', Worker), patch.object(mr, 'generate_model_ref_images', side_effect=lambda *_a, **_k: hub.append('tpose')), patch.object(m3, 'trigger_generation', side_effect=lambda *_a, **_k: hub.append('mesh')), patch.object(bb, 'is_base_pipeline', return_value=True), patch.object(fig, 'invalidate', side_effect=lambda: marks.append('invalidate')), patch.object(fb, 'start', side_effect=lambda *_a, **_k: hub.append('build')), patch.object(fb, 'request', side_effect=lambda *_a, **_k: hub.append('request')), patch.object(image_service, 'get_image_service', side_effect=lambda *_a, **_k: hub.append('image service')):
        result = co.apply_body_slot_values('fixture', 'slot', {'switch': 'on'})
        assert result.get('status') == 'success', result
        assert profile['body_slots']['slot']['switch'] == 'on', profile
        assert (marks, hub) == (['invalidate'], []), (marks, hub)
        co.apply_body_slot_values('fixture', 'slot', {'switch': 'off'})
        assert (marks, hub) == (['invalidate'] * 2, []), (marks, hub)
    old = subprocess.run(['git', 'show', '5eab1741:app/core/character_ops.py'], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[1]).stdout
    tail = old[old.index('def apply_body_slot_values'):]
    tail = tail[:tail.index('\ndef ', 1)]
    assert 'is_base_pipeline' not in tail and '_schedule_mesh_part_regeneration(character_name)' in tail
print('PASS mesh_part trigger: ordered render/mesh, unchanged, disabled, failed save; FR-I5 pipeline: '
      'saved + marked due, 0 hub calls')
