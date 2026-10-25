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
                            'switch', 'flat {size} slot', [], {'part': {'params': {'radius': .02}, 'attribute_params': {'size_factor': {'attribute': 'size', 'values': {'large': 1.5}}}}}))
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
    # mesh_input_prompt (hand-derived): the line follows the stored value of
    # its attribute, case-insensitively; an unmapped value, an ordinary render
    # and a back view (slot without back: true) add nothing.
    hattrs = {'length': {'type': 'select', 'options': ['short', 'long']}}
    hair = BodySlotSpec('hair', 'fixture', attributes=hattrs, prompt={'always': '{length} hair'},
                        mesh_input_prompt={'attribute': 'length', 'values': {'long': 'hair behind the shoulders'}})
    hpkg = Package('fixture', Path(tmp), {}, body_slots=[hair])
    with patch.object(bs, '_species_packages_for', return_value=[hpkg]), patch('app.core.outfit_renderer.is_free_text_wardrobe', return_value=False):
        hp = lambda length: {'body_slots': {'hair': {'length': length}}, 'equipped_pieces': {}}
        assert bs.prompt_fragments('', profile=hp('long'), mesh_input=True) == {
            'general': ['long hair'], 'exposed': ['hair behind the shoulders']}
        assert bs.prompt_fragments('', profile=hp('Long'), mesh_input=True)['exposed'] == ['hair behind the shoulders']
        assert bs.prompt_fragments('', profile=hp('short'), mesh_input=True)['exposed'] == []
        assert bs.prompt_fragments('', profile=hp('long'))['exposed'] == []
        assert bs.prompt_fragments('', profile=hp('long'), mesh_input=True, back_view=True)['exposed'] == []
        hair.mesh_input_prompt['back_values'] = {'long': 'hair down the back'}
        assert bs.prompt_fragments('', profile=hp('long'), mesh_input=True, back_view=True)['exposed'] == ['hair down the back']
        assert bs.prompt_fragments('', profile=hp('long'), mesh_input=True)['exposed'] == ['hair behind the shoulders']
        assert bs.prompt_fragments('', profile=hp('short'), mesh_input=True, back_view=True)['exposed'] == []
    from app.plugins.loader import _parse_package
    good = {'attribute': 'length', 'values': {'Long': ' behind '}}
    meta = dict(name='fixture', body_slots=[dict(id='hair', attributes=hattrs, mesh_input_prompt=good)])
    parsed = _parse_package(Path(tmp)/'fixture', meta, register_tasks=False)
    assert parsed.body_slots[0].mesh_input_prompt == {'attribute': 'length', 'values': {'long': 'behind'}}
    meta['body_slots'][0]['mesh_input_prompt'] = {**good, 'back_values': {'LONG': 'down'}}
    parsed = _parse_package(Path(tmp)/'fixture', meta, register_tasks=False)
    assert parsed.body_slots[0].mesh_input_prompt['back_values'] == {'long': 'down'}
    for bad in ({'attribute': 'missing', 'values': {'long': 'x'}}, {'attribute': 'length', 'values': {}},
                {**good, 'back_values': {}}, {**good, 'back_values': {'long': ' '}}, {**good, 'other': {}},
                {'attribute': 'length', 'values': {'long': ''}}, {'attribute': 'length'}, 'text'):
        meta['body_slots'][0]['mesh_input_prompt'] = bad
        assert _parse_package(Path(tmp)/'fixture', meta, register_tasks=False) is None
print('PASS mesh_part prompt: mesh input, ordinary, off, covered; rig size 1.5; mesh_input_prompt')
