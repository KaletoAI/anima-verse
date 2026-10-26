"""Usage: .venv/bin/python scripts/smoke_mesh_part_loras.py

Hand-derived: two case-insensitive globs drop two of three character LoRAs
and one of two slot LoRAs, so mesh occasions retain exactly two names.
Ordinary occasions, switch off and a covered slot retain all five names.
No world data or pack imports: the one slot and service are synthetic.
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.db import init_schema
    init_schema()
    from app.plugins.registry import BodySlotSpec, MeshPartSpec
    from app.core import body_slots as bs, expression_regen as expr, prompt_builder as pb

    slot = BodySlotSpec('slot', 'fixture', covered_by=['cover'],
        attributes={'lora': {'type': 'lora_select'}}, mesh_part=MeshPartSpec(
        'switch', 'flat slot', ['*InsetShape*', '*AttachedShape*'], {}))
    character_loras = [{'name': name, 'strength': 1} for name in ('INSETSHAPE-v1', 'attachedshape-v2', 'pose')]
    profile = {'body_slots': {'slot': {'switch': 'on', 'lora': 'slot-insetshape'}}, 'equipped_pieces': {},
               'outfit_imagegen': {'tpose_loras': character_loras, 'loras': character_loras}}
    slot_loras = [{'name': name} for name in ('slot-insetshape', 'style')]
    captured = []

    def generate(payload):
        captured.append(json.loads(payload))
        return ''

    with patch.object(bs, 'slots_for_character', return_value=[slot]), patch(
            'app.models.character.get_character_profile', return_value=profile), patch(
            'app.models.character.get_character_appearance', return_value='fixture'), patch.object(
            pb.PromptBuilder, 'detect_persons', return_value=[]), patch(
            'app.imagegen.service.get_image_service', return_value=SimpleNamespace(enabled=True, generate_from_input=generate)), patch(
            'app.core.outfit_renderer.is_free_text_wardrobe', return_value=False), patch(
            'app.core.outfit_renderer.render_outfit', return_value={'loras': slot_loras}):
        assert bs.filter_mesh_input_loras(character_loras + slot_loras, profile) == [character_loras[2], slot_loras[1]]
        assert bs.exposed_slot_loras('', profile=profile, mesh_input=True) == []
        for active, covered in ((True, False), (False, False), (True, True)):
            profile['body_slots']['slot']['switch'] = 'on' if active else 'off'
            pieces = {'cover': 'fixture'} if covered else {}
            for occasion in ('tpose', 'tpose_view', 'expression', 'outfit'):
                expr.render_character_image('fixture', occasion=occasion, output_stem=Path(tmp) / 'fixture',
                    equipped_pieces=pieces, equipped_items=[], expression_prompt='',
                    pose_prompt='', apply_state_modifiers=False)
                names = [entry['name'] for entry in captured[-1]['loras']]
                expected = ['pose', 'style'] if active and not covered and occasion in ('tpose', 'tpose_view') else [entry['name'] for entry in character_loras + slot_loras]
                assert names == expected, (occasion, active, covered, names)
    print('PASS mesh_part LoRAs: 12 occasion/switch/coverage cases, two retained for active mesh inputs')
