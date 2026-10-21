"""Usage: .venv/bin/python scripts/smoke_mesh_part_prompt.py

Hand-derived: on + mesh input replaces the one exposed fragment and removes
its one LoRA; ordinary renders and off retain both. Covering removes both.
The active rig's size is exactly 1.5 and its explicit radius stays 0.02.
Synthetic registry only; storage is initialised before world modules import.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.db import init_schema
    init_schema()
    from app.plugins.registry import BodySlotSpec, MeshPartSpec, RigSpec, Package
    from app.core import body_slots as bs, extension_rig as er
    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']},
             'size': {'type': 'select', 'options': ['large']}, 'lora': {'type': 'lora_select'}}
    rig = RigSpec.parse(dict(id='part', op='appendage_chain', chains=[[dict(bone='Part', parent='Hips')]]))
    slot = BodySlotSpec('slot', 'fixture', attributes=attrs, prompt={'exposed': 'visible {size} part'},
                        covered_by=['cover'], back=True, rigs=[rig], mesh_part=MeshPartSpec(
                            'switch', 'part', 'flat {size} slot', 'size', {'large': 1.5}, {'radius': .02}))
    profile = {'body_slots': {'slot': {'switch': 'on', 'size': 'large', 'lora': 'fixture'}}, 'equipped_pieces': {}}
    pkg = Package('fixture', Path(tmp), {}, body_slots=[slot])
    with patch.object(bs, '_species_packages_for', return_value=[pkg]), patch('app.plugins.registry.packages', return_value=[pkg]), patch('app.core.outfit_renderer.is_free_text_wardrobe', return_value=False):
        assert bs.prompt_fragments('', profile=profile, mesh_input=True)['exposed'] == ['flat large slot']
        assert bs.exposed_slot_loras('', profile=profile, mesh_input=True) == []
        assert bs.prompt_fragments('', profile=profile)['exposed'] == ['visible large part']
        assert len(bs.exposed_slot_loras('', profile=profile)) == 1
        # Exercise the occasion handoff without image backends or real profiles.
        from app.core import expression_regen as expr, prompt_builder as pb
        from types import SimpleNamespace
        seen = []
        def detect(builder, *_args, **_kwargs):
            seen.append((builder.mesh_input, builder.body_profile))
            return []
        with patch('app.models.character.get_character_profile', return_value=profile), patch(
                'app.models.character.get_character_appearance', return_value='fixture'), patch.object(
                pb.PromptBuilder, 'detect_persons', detect), patch(
                'app.imagegen.service.get_image_service', return_value=SimpleNamespace(enabled=False)), patch.object(
                expr, '_cache_key', return_value='fixture'), patch(
                'app.models.character_template.is_feature_enabled', return_value=True), patch(
                'app.core.outfit_renderer.render_outfit', return_value={}) as outfit:
            for occasion in ('tpose', 'tpose_view', 'expression', 'outfit'):
                expr.generate_expression_image('fixture', '', '', occasion=occasion,
                    equipped_pieces={'cover': 'item'}, equipped_items=[],
                    expression_prompt_override='', pose_prompt_override='', apply_state_modifiers=False)
                assert seen[-1][0] == (occasion in ('tpose', 'tpose_view'))
                if occasion in ('tpose', 'tpose_view'):
                    assert outfit.call_args.kwargs['mesh_input'] == seen[-1][0]
                if seen[-1][0]:
                    assert seen[-1][1]['equipped_pieces'] == {'cover': 'item'}
                else:
                    assert seen[-1][1] is None
        group = er.rig_groups_for('', profile)[0]
        assert group['op'] == 'attached_part' and group['params'] == {'radius': .02, 'size_factor': 1.5}
        profile['body_slots']['slot']['switch'] = 'off'
        assert bs.prompt_fragments('', profile=profile, mesh_input=True)['exposed'] == ['visible large part']
        assert len(bs.exposed_slot_loras('', profile=profile, mesh_input=True)) == 1
        profile['equipped_pieces'] = {'cover': 'item'}
        assert bs.prompt_fragments('', profile=profile, mesh_input=True)['exposed'] == []
print('PASS mesh_part prompt: mesh input, ordinary, off, covered; rig size 1.5')
