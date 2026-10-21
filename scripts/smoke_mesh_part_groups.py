"""Usage: .venv/bin/python scripts/smoke_mesh_part_groups.py

Hand-derived: medium maps to 0.5, small to zero, unmapped custom omits the
parameter. An inset has zero links, hence zero bone names and motion entries.
Changing one mapped number or a build version must change the fingerprint.
All declarations and storage are synthetic temporary fixtures.
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
    from app.core import body_slots as bs, extension_rig as er
    from app.plugins.registry import BodySlotSpec, MeshPartSpec, RigSpec, Package
    from app.plugins.loader import _parse_package
    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']},
             'type': {'type': 'select', 'options': ['a', 'b']},
             'inner': {'type': 'select', 'options': ['small', 'medium'],
                       'applies_to': {'attributes.type': ['b', None]}}}
    raw_rig = dict(id='inset', op='inset_part', chains=[],
                   applies_to={'attributes.type': ['b'], 'attributes.switch': ['on']})
    rig = RigSpec.parse(raw_rig)
    part = dict(switch='switch', tpose_prompt='flat slot', rigs={'inset': {
        'params': {}, 'attribute_params': {'inner_scale': {
            'attribute': 'inner', 'values': {'small': 0, 'medium': .5}}}}})
    slot = BodySlotSpec('slot', 'fixture', attributes=attrs, rigs=[rig],
                        mesh_part=MeshPartSpec.parse(part, attrs, [rig]))
    pkg = Package('fixture', Path(tmp), {}, body_slots=[slot])
    profile = {'body_slots': {'slot': {'switch': 'on', 'type': 'b', 'inner': 'medium'}}}
    with patch.object(bs, '_species_packages_for', return_value=[pkg]), patch(
            'app.plugins.registry.packages', return_value=[pkg]):
        groups = er.rig_groups_for('', profile)
        assert groups[0]['op'] == 'inset_part' and groups[0]['params'] == {'inner_scale': .5}
        assert er.extension_bone_names('', profile) == {}
        assert er.declared_motion_groups() == []
        assert er.motion_payload('', profile)['groups'] == {}
        fingerprint = er.extension_rig_fingerprint(groups)
        with patch.dict(er.PART_BUILDS, inset_part=er.PART_BUILDS["inset_part"] + 1):
            assert fingerprint != er.extension_rig_fingerprint(groups)
        profile['body_slots']['slot']['inner'] = 'small'
        assert er.rig_groups_for('', profile)[0]['params'] == {'inner_scale': 0}
        assert fingerprint != er.extension_rig_fingerprint(er.rig_groups_for('', profile))
        profile['body_slots']['slot']['inner'] = 'custom'
        assert er.rig_groups_for('', profile)[0]['params'] == {}
        profile['body_slots']['slot']['switch'] = 'off'
        assert er.rig_groups_for('', profile) == []
    from app.core.character_ops import build_body_slots
    attrs['inner']['applies_to'] = {'attributes.type': ['b', None], 'category': ['neutral']}
    profile['category'] = 'neutral'
    profile['body_slots']['slot']['inner'] = 'medium'
    with patch('app.models.character.get_character_profile', return_value=profile), patch.object(
            bs, 'slots_for_character', return_value=[slot]), patch.object(
            bs, 'slot_values', return_value=profile['body_slots']), patch.object(
            bs, 'is_slot_exposed', return_value=True), patch.object(
            bs, 'silhouette_for_character', return_value=None), patch.object(
            bs, 'declared_piece_slots', return_value=None):
        payload = build_body_slots('fixture')['slots'][0]
        assert payload['condition_profile'] == {'category': 'neutral'}
        inner = next(attr for attr in payload['attributes'] if attr['key'] == 'inner')
        assert inner['applies_to'] == attrs['inner']['applies_to']
        assert inner['value'] == 'medium'
    # Rig conditions keep an empty value distinct from null (only the editor's visibility folds them).
    assert bs.normalize_condition_value('') == '' and bs.normalize_condition_value(None) is None
    for condition in ({'attributes.type': ['b', None]}, {'gender': ['sample']}):
        attrs['inner']['applies_to'] = condition
        meta = dict(name='fixture', body_slots=[dict(id='slot', attributes=attrs, rigs=[raw_rig], mesh_part=part)])
        assert _parse_package(Path(tmp)/'fixture', meta, register_tasks=False)
    for condition in ([], {'attributes.missing': ['b']}, {'gender': []}, {'gender': [{}]}):
        attrs['inner']['applies_to'] = condition
        assert _parse_package(Path(tmp)/'fixture', meta, register_tasks=False) is None
print('PASS inset declarations: mapped .5/0/default, empty motion, build identity, attribute conditions')
