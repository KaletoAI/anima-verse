"""Pure house build/storage contract.

Usage: ./.venv/bin/python scripts/smoke_house_build.py
Two units need disjoint u0/ and u1/ materials. Asymmetric parts with
x [-3.4, 3.1], z [-4.9, 5.6] need symmetric extrema +/-3.4, +/-5.6.
Each keeper has two perpendicular 0.02 m edges pointing inward. A stub box
[-4,0,-6]..[4,11,6] measures 8 x 11 x 12 m, while the original footprint
remains 6 x 9 m. New files reset a previous 90 degree fix to zero. Only old
house files are pruned. A blocked worker holds the prop guard across variants.
A 16 x 10 m row splits into four 4 m units. All have the same depth and
storeys, so a common gable form and (30+45)/2 = 37.5 degree pitch must put
all four roof-part maxima at the same height within 0.01 m, in both tiers.
Chimneys and dormers are separate tags and do not define the roof ridge.
"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def stub_glb():
    """Use the JSON-only GLB helper pattern from smoke_props_slots."""
    doc = {'asset': {'version': '2.0'}, 'scene': 0,
           'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
           'accessors': [{'componentType': 5126, 'type': 'VEC3', 'count': 3,
                          'min': [-4, 0, -6], 'max': [4, 11, 6]}]}
    body = json.dumps(doc).encode()
    body += b' ' * (-len(body) % 4)
    chunk = struct.pack('<II', len(body), 0x4E4F534A) + body
    return struct.pack('<III', 0x46546C67, 2, 12 + len(chunk)) + chunk


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='smoke-house-') as temp:
        root = Path(temp)
        paths.init(root)
        paths.init_instance(root / 'instance')
        from app.core import props, house_props as hp, hull_model
        from app.core.model_store import read_sidecar, write_sidecar
        from app.blender import runner
        row_id = props.create_prop(name='Row roof smoke', width_m=16, depth_m=10, height_m=8)['id']
        hp.set_house_spec(row_id, 0, {'style': 'steinhaus', 'units': 4})
        roof_heights = {'full': [], 'low': []}
        build_hull = hull_model.build_hull
        def capture_roofs(*args, **kwargs):
            geometry = build_hull(*args, **kwargs)
            points = [v for part in geometry['parts'] if part['tag'] == 'roof'
                      for v in part['vertices']]
            assert points
            roof_heights[kwargs['tier']].append(max(v[1] for v in points))
            return geometry
        with patch.object(hull_model, 'build_hull', side_effect=capture_roofs):
            hp.house_job(row_id, 0, tex_dir=root / 'row-textures')
        for tier, heights in roof_heights.items():
            assert len(heights) == 4, (tier, heights)
            assert max(heights) - min(heights) <= .01, (tier, heights)
        print('Row roof maxima:', roof_heights)
        pid = props.create_prop(name='House smoke', width_m=6, depth_m=9, height_m=8)['id']
        missing = props.create_prop(name='Missing size')['id']
        meta = props.read_sidecar(missing)
        for key in ('width_m', 'depth_m'):
            meta[props.VARIANTS_KEY][0].pop(key, None)
        with patch.object(props, '_variant_list', return_value=meta[props.VARIANTS_KEY]):
            props._write_sidecar(missing, meta)
        try:
            hp.set_house_spec(missing, 0, {})
            raise AssertionError('missing dims accepted')
        except ValueError as error:
            assert str(error) == "set the prop's size first"
        hp.set_house_spec(pid, 0, {'units': 2, 'storeys': 3, 'overrides': {'shopfront': True}})
        real_build = hull_model.build_hull
        shells = {'full': [], 'low': []}
        def capture(*args, **kwargs):
            geometry = real_build(*args, **kwargs)
            shells[kwargs['tier']].extend(v for p in geometry['parts'] if p['tag'] == 'wall'
                                          for v in p['vertices'])
            assert any(p['tag'] == 'awning' for p in geometry['parts'])
            return geometry
        with patch.object(hull_model, 'build_hull', side_effect=capture), \
                patch('app.models.world.get_location_by_id', side_effect=AssertionError('synthetic DB lookup')):
            job = hp.house_job(pid, 0, tex_dir=root / 'textures')
        for points in shells.values():
            limits = [min(v[0] for v in points), max(v[0] for v in points),
                      min(v[2] for v in points), max(v[2] for v in points)]
            assert all(abs(a-b) <= .02 for a, b in zip(limits, [-3, 3, -4.5, 4.5])), limits
        names = [m['name'] for m in job['materials']]
        assert len(names) == len(set(names))
        assert any(n.startswith('u0/') for n in names) and any(n.startswith('u1/') for n in names)
        assert all('/' not in key for key in job['textures'])
        assert all(m['material'] in names for t in job['tiers'].values() for m in t['meshes'])
        part = {'name': 'fixture', 'material': 'wall', 'vertices': [[-3.4, 4.9, 0], [3.1, -5.6, 2], [0, 0, 1]],
                'faces': [[0, 1, 2]], 'uvs': [[[0, 0]] * 3], 'colors': [[1] * 3]}
        fake = {'tiers': {t: {'meshes': [part]} for t in ('full', 'low')},
                'materials': [{'name': 'wall', 'texture': None}], 'textures': {}}
        with patch.object(hull_model, 'build_job', return_value=fake):
            merged = hp.house_job(pid, 0, tex_dir=root / 'fake')
        for tier in merged['tiers'].values():
            keepers = tier['meshes'][-2:]
            assert keepers[0]['vertices'][0] == [3.4, -5.6, 0]
            assert keepers[1]['vertices'][0] == [-3.4, 5.6, 0]
            for mesh in keepers:
                for v in mesh['vertices']:
                    assert abs(v[0]) <= 3.4 and abs(v[1]) <= 5.6
        gallery = props.model_gallery(pid, 0)
        old = gallery.new_path(); old.write_bytes(stub_glb())
        write_sidecar(old, {'source': 'img2mesh', 'rotation': {'x': 0, 'y': 90, 'z': 0}})
        gallery.select(old.name, 'full')
        def run(script, *, inputs, out_dir, **kwargs):
            assert script == 'hull_build'
            payload = json.loads(inputs['job'].read_text())
            outputs = {}
            for tier, name in payload['export'].items():
                target = out_dir / name; target.write_bytes(stub_glb()); outputs[tier] = str(target)
            return {'ok': True, 'outputs': outputs}
        with patch.object(runner, 'is_available', return_value=True), patch.object(runner, 'run', side_effect=run), \
                patch.object(props, '_store_bbox') as landing:
            result = hp.build_house_variant(pid, 0)
            assert result['ok'], result
            landing.assert_called_once_with(pid, 0, landing=True)
            first = props.model_gallery(pid, 0).find('full')
            dims = props.variant_dims(props.read_sidecar(pid), 0)
            assert dims == {'width_m': 8.0, 'height_m': 11.0, 'depth_m': 12.0}, dims
            hp.set_house_spec(pid, 0, {'storeys': 3})
            assert props._variant_list(props.read_sidecar(pid))[0]['house']['footprint_m'] == [6, 9]
            assert hp.build_house_variant(pid, 0)['ok']
            assert not first.exists() and old.exists()
        gallery = props.model_gallery(pid, 0)
        for tier in ('full', 'low'):
            meta = read_sidecar(gallery.find(tier, fallback=False))
            assert meta['source'] == 'house_build' and meta['rotation'] == {'x': 0, 'y': 0, 'z': 0}
        entry = props._variant_list(props.read_sidecar(pid))[0]
        entry['house']['footprint_m'] = [99, 99]
        props.bulk_update(pid, variants={entry['uid']: {'house': entry['house']}},
                          base_revision=props.get_prop(pid)['revision'])
        assert props._variant_list(props.read_sidecar(pid))[0]['house']['footprint_m'] == [6, 9]
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def blocked(*args):
            started.set(); assert release.wait(5); return {'ok': True}
        queue = Mock()
        queue.track_finish.side_effect = lambda *a, **k: finished.set()
        with patch.object(hp, 'build_house_variant', side_effect=blocked), \
                patch('app.core.task_queue.get_task_queue', return_value=queue):
            assert hp.trigger_house_build(pid, 0)
            assert started.wait(5)
            assert not hp.trigger_house_build(pid, 1)
            release.set(); assert finished.wait(5)
        assert queue.track_start.call_args.args == ('model3d_generation', 'House: House smoke v0')
        print('smoke_house_build: PASS')


if __name__ == '__main__':
    main()
