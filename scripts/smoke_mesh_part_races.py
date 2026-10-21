"""Usage: .venv/bin/python scripts/smoke_mesh_part_races.py

Hand-derived: a rejected busy mesh request retries once and succeeds on call 2.
An old signature that waited for the render lane produces zero renders.
A render snapshot retains switch=on after live switch becomes off.
Synthetic mocks only; all imported world modules use temporary storage.
"""
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core import character_ops as co, model_refs as mr, model3d as m3
    with patch.object(mr, 'current_outfit_state', return_value=({}, [], 'new')), patch.object(mr, 'trigger_now'), patch.object(mr, 'find_ref_image', return_value=Path(tmp)/'input.png'), patch.object(m3, 'find_model3d', return_value=None), patch.object(m3, 'trigger_generation', side_effect=[False, True]) as trigger:
        co._regenerate_mesh_part('fixture')
        assert trigger.call_count == 2, trigger.call_count
    with patch.object(mr, 'current_outfit_state', return_value=({}, [], 'new')), patch.object(mr, 'generate_model_ref_images') as render:
        mr.trigger_now('fixture', kinds=('tpose',), force=False, blocking=True, pieces={}, items=[], signature='old')
        assert not render.called
    from app.core import body_slots as bs
    from app.plugins.registry import BodySlotSpec, MeshPartSpec
    profile = {'body_slots': {'slot': {'switch': 'on'}}}
    slot = BodySlotSpec('slot', 'fixture', mesh_part=MeshPartSpec('switch', 'flat slot', [], {'part': {'params': {}, 'attribute_params': {}}}))
    captured = []
    def render(name, **kwargs):
        captured.append(kwargs['mesh_input_profile']['body_slots']['slot']['switch'])
        profile['body_slots']['slot']['switch'] = 'off'
        return Path(tmp) / 'input.png'
    signature = mr.mesh_signature({}, [], '', '|mesh:fixture.slot=on')
    with patch('app.models.character.get_character_profile', return_value=profile), patch.object(bs, 'slots_for_character', return_value=[slot]), patch.object(mr, 'get_model_refs_dir', return_value=Path(tmp)), patch.object(mr, 'is_humanoid', return_value=True), patch.object(mr, 'get_view_kinds', return_value={}), patch.object(mr, 'enabled_tpose_views', return_value=('back',)), patch.object(mr, 'find_ref_image', return_value=None), patch('app.core.expression_regen.generate_expression_image', side_effect=render), patch('app.core.prompt_filters.image_modifier_snapshot', return_value=nullcontext()):
        mr.generate_model_ref_images('', kinds=('tpose',), pieces={}, items=[], signature=signature)
    assert captured == ['on', 'on'], captured
print('PASS mesh_part races: busy request retried, superseded signature rejected, profile snapshot')
