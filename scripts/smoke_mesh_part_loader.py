"""Usage: .venv/bin/python scripts/smoke_mesh_part_loader.py

Hand-derived expectations: one slot switch selects one rig; two size choices
map to 1 and 1.5. A companion has exactly one link and zero parameters.
Invalid references, empty text and non-finite values must fail; zero is valid.
All declarations are synthetic; no plugin discovery or world reads occur.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.plugins.registry import MeshPartSpec, RigSpec
    from app.plugins.loader import _parse_package
    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']},
             'size': {'type': 'select', 'options': ['small', 'large']}}
    rig = RigSpec.parse({'id': 'part', 'op': 'appendage_chain', 'chains': [[
        {'bone': 'Part', 'parent': 'Hips'}, {'bone': 'Tip', 'parent': 'Part'}]], 'rigid_tail': 1})
    raw = dict(switch='switch', tpose_prompt='flat {size} slot', lora_patterns=['*fixture*'],
               rigs={'part': {'params': {}, 'attribute_params': {
                   'size_factor': {'attribute': 'size', 'values': {'small': 1, 'large': 1.5}}}}})
    assert MeshPartSpec.parse(raw, attrs, [rig]).rigs['part']['attribute_params']['size_factor']['values']['large'] == 1.5
    invalid = [{'switch': 'missing'}, {'tpose_prompt': ''}, {'lora_patterns': ['']},
               {'lora_patterns': 'fixture'}, {'rig': 'part'}, {'size_attribute': 'size'},
               {'size_factors': {}}, {'params': {}}, {'rigs': {'missing': {}}}]
    for mapping in ({'attribute': 'missing', 'values': {}},
                    {'attribute': 'size', 'values': {'other': 1}},
                    *({'attribute': 'size', 'values': {'small': n}} for n in (float('inf'), float('nan'), True))):
        invalid.append({'rigs': {'part': {'attribute_params': {'scale': mapping}}}})
    for change in invalid:
        try:
            MeshPartSpec.parse({**raw, **change}, attrs, [rig])
        except ValueError:
            pass
        else:
            raise AssertionError(change)
    RigSpec.parse(dict(id='inset', op='inset_part', chains=[]))
    for op in ('appendage_chain', 'attached_part', 'attached_part_bone'):
        try:
            RigSpec.parse(dict(id='empty', op=op, chains=[]))
        except ValueError:
            pass
        else:
            raise AssertionError(op)
    for bad in (None, [], {'type': 'str'}, {'type': 'select', 'options': ['off']}):
        try:
            MeshPartSpec.parse(raw, {**attrs, 'switch': bad}, [rig])
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    meta = dict(name='fixture', body_slots=[dict(id='slot', attributes=attrs,
                rigs=[dict(id='part', op='appendage_chain', chains=rig.chains)], mesh_part=raw)])
    pkg = _parse_package(Path(tmp)/'fixture', meta, register_tasks=False)
    assert set(pkg.body_slots[0].mesh_part.rigs) == {'part'}
    meta['body_slots'][0]['mesh_part'] = {**raw, 'rigs': {'missing': {}}}
    assert _parse_package(Path(tmp)/'fixture', meta, register_tasks=False) is None
    for tail in (-1, 2, 1.5, True):
        try:
            RigSpec.parse(dict(id='part', op='appendage_chain', chains=rig.chains, rigid_tail=tail))
        except ValueError:
            pass
        else:
            raise AssertionError(tail)
    companion = dict(id='pods', op='attached_part_bone', chains=[[{'bone': 'Pods', 'parent': 'Hips'}]])
    RigSpec.parse(companion)
    for change in ({'params': {'x': 1}}, {'chains': rig.chains}):
        try:
            RigSpec.parse({**companion, **change})
        except ValueError:
            pass
        else:
            raise AssertionError(change)
    # Global conflicts cannot leave a prompt variant without its declared rig.
    import yaml
    from app.plugins.loader import _collect_packages
    root = Path(tmp) / 'plugins'
    for name in ('first', 'second'):
        package_dir = root / name
        package_dir.mkdir(parents=True)
        declaration = dict(name=name, body_slots=[dict(id='slot', attributes=attrs,
            rigs=[dict(id='part', op='appendage_chain', chains=rig.chains)], mesh_part=raw)])
        (package_dir / 'plugin.yaml').write_text(yaml.safe_dump(declaration))
    assert _collect_packages(root) == []
print('PASS mesh_part loader: validation, companion, rigid_tail')
