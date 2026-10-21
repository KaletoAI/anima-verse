"""Usage: .venv/bin/python scripts/smoke_mesh_part_loader.py

Hand-derived expectations: one slot switch selects one rig; two size choices
map to 1 and 1.5. A companion has exactly one link and zero parameters.
Invalid references, empty text and non-positive/non-finite scales must fail.
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
    raw = dict(switch='switch', rig='part', tpose_prompt='flat {size} slot',
               size_attribute='size', size_factors={'small': 1, 'large': 1.5}, params={})
    assert MeshPartSpec.parse(raw, attrs, [rig]).size_factors['large'] == 1.5
    for change in ({'switch': 'missing'}, {'rig': 'missing'}, {'size_attribute': 'missing'},
                   {'tpose_prompt': ''}, {'params': []}, {'size_factors': {'other': 1}},
                   *({'size_factors': {'small': n}} for n in (0, -1, float('inf'), float('nan'), True))):
        try:
            MeshPartSpec.parse({**raw, **change}, attrs, [rig])
        except ValueError:
            pass
        else:
            raise AssertionError(change)
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
    assert pkg.body_slots[0].mesh_part.rig == 'part'
    meta['body_slots'][0]['mesh_part'] = {**raw, 'rig': 'missing'}
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
