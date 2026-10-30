"""Pure house build/storage contract.

Usage: ./.venv/bin/python scripts/smoke_house_build.py
Units share materials with identical content. Asymmetric parts with
x [-3.4, 3.1], z [-4.9, 5.6] need symmetric extrema +/-3.4, +/-5.6.
Each keeper has two perpendicular 0.02 m edges pointing inward. A stub box
[-4,0,-6]..[4,11,6] measures 8 x 11 x 12 m, while the original footprint
remains 6 x 9 m. A first house resets an img2mesh orientation; house rebuilds preserve it. Only old
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


def final_fix_cases(root):
    """Hand-derived final review regressions (no Blender).

    [F1] img2mesh y=90 starts at zero; a house y=90 survives rebuild.
    [F2] Measured 8x12 is larger than authored 6x9; copied and seeded
         variants must retain 6x9, including when their house is absent.
    [F4] A blocked runner permits an artificial index shift: UID B moves
         from 1 to 0, so only B receives the file and measured 8x11x12 dims.
         Removing B entirely must produce variant_changed and no model.
    [F5] A runner failure belongs to its UID, is exposed by GET, and clears
         on the next start/success. A deleted style uses steinhaus geometry.
    [F6] Four identical unit specs need the same materials as one unit;
         four distinct facade tints plus an explicit shared white roof tint
         need four walls but one shared roof.
    """
    from app.core import props, house_props as hp, hull_model
    from app.core.model_store import read_sidecar, write_sidecar
    from app.blender import runner
    from app.routes.prop_variants import prop_variant_house
    failures = []
    def case(number, fn):
        try:
            fn()
            print(number, 'PASS')
        except Exception as exc:
            failures.append((number, repr(exc)))
            print(number, 'FAIL', repr(exc))
    def create():
        pid = props.create_prop(name='Final regression', width_m=6, depth_m=9, height_m=8)['id']
        hp.set_house_spec(pid, 0, {})
        return pid
    def rotation():
        pid = create(); g = props.model_gallery(pid, 0)
        old = g.new_path(); old.write_bytes(stub_glb())
        write_sidecar(old, {'source': 'img2mesh', 'rotation': {'x': 0, 'y': 90, 'z': 0}})
        g.select(old.name, 'full')
        blobs = dict(full=stub_glb(), low=stub_glb())
        props.save_house_models(pid, 0, blobs, {}, 'first')
        full = props.model_gallery(pid, 0).find('full'); assert read_sidecar(full)['rotation']['y'] == 0
        write_sidecar(full, {**read_sidecar(full), 'rotation': {'x': 0, 'y': 90, 'z': 0}})
        props.save_house_models(pid, 0, blobs, {}, 'second')
        assert read_sidecar(props.model_gallery(pid, 0).find('full'))['rotation']['y'] == 90
    case('F1', rotation)
    def inheritance():
        pid = create()
        props.set_variant_dims(pid, 0, dict(width_m=8, depth_m=12, height_m=11))
        other = props.add_variant(pid)
        entries = props._variant_list(props.read_sidecar(pid))
        assert entries[other].get('house', {}).get('footprint_m') == [6, 9]
        meta = props.read_sidecar(pid); meta[props.VARIANTS_KEY][other].pop('house')
        props._write_sidecar(pid, meta)
        assert hp.set_house_spec(pid, other, {})['footprint_m'] == [6, 9]
    case('F2', inheritance)
    def materials():
        pid = props.create_prop(name='Material row', width_m=16, depth_m=10, height_m=8)['id']
        hp.set_house_spec(pid, 0, {'units': 1})
        one = hp.house_job(pid, 0, tex_dir=root / 'one')
        hp.set_house_spec(pid, 0, {'units': 4})
        row = hp.house_job(pid, 0, tex_dir=root / 'four')
        assert len(row['materials']) == len(one['materials']), (len(row['materials']), len(one['materials']))
        hp.set_house_spec(pid, 0, {'units': 4, 'overrides': {'roof_tint': '#ffffff'}, 'unit_overrides': [
            {'tint': tint} for tint in ('#aa0000', '#00aa00', '#0000aa', '#aaaa00')]})
        row = hp.house_job(pid, 0, tex_dir=root / 'tints')
        assert sum(m['name'].endswith('/wall') for m in row['materials']) == 4, row['materials']
        assert sum(m['name'].endswith('/roof') for m in row['materials']) == 1, row['materials']
    case('F6', materials)
    def deleted_style():
        pid = create(); meta = props.read_sidecar(pid)
        meta[props.VARIANTS_KEY][0]['house']['spec']['style'] = 'deleted-style'
        props._write_sidecar(pid, meta)
        job = hp.house_job(pid, 0, tex_dir=root / 'deleted')
        assert job['description']['style'] == 'steinhaus'
    case('F5-style', deleted_style)
    def worker(remove=False, fail=False):
        pid = create(); other = props.add_variant(pid)
        hp.set_house_spec(pid, other, {})
        uid = props._variant_list(props.read_sidecar(pid))[other]['uid']
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        queue = Mock(); queue.track_finish.side_effect = lambda *a, **k: finished.set()
        def run(script, *, out_dir, **kwargs):
            entered.set(); assert release.wait(10)
            if fail: return {'ok': False, 'error': 'deliberate runner failure'}
            outputs = {}
            for tier in ('full', 'low'):
                path = out_dir / (tier + '.glb'); path.write_bytes(stub_glb()); outputs[tier] = str(path)
            return {'ok': True, 'outputs': outputs}
        with patch.object(runner, 'is_available', return_value=True), patch.object(runner, 'run', side_effect=run), \
                patch.object(props, '_store_bbox'), patch('app.core.task_queue.get_task_queue', return_value=queue):
            assert hp.trigger_house_build(pid, other); assert entered.wait(10)
            blocked = props.variant_delete_blocked(pid, 0)
            meta = props.read_sidecar(pid)
            meta[props.VARIANTS_KEY] = meta[props.VARIANTS_KEY][:1] if remove else meta[props.VARIANTS_KEY][1:]
            props._write_sidecar(pid, meta)
            release.set(); assert finished.wait(10)
        if fail:
            assert prop_variant_house(pid, 0).get('error') == 'deliberate runner failure'
            fail = False
            entered.clear(); release.clear(); finished.clear()
            with patch.object(runner, 'is_available', return_value=True), patch.object(runner, 'run', side_effect=run), \
                    patch.object(props, '_store_bbox'), patch('app.core.task_queue.get_task_queue', return_value=queue):
                assert hp.trigger_house_build(pid, 0); assert entered.wait(10)
                current = prop_variant_house(pid, 0)
                assert current['running'] and current['error'] == ''
                release.set(); assert finished.wait(10)
            assert prop_variant_house(pid, 0)['error'] == ''
            assert props.model_gallery(pid, 0).find('full')
        elif remove:
            assert queue.track_finish.call_args.kwargs['error'] == 'variant_changed'
            assert not props.model_gallery(pid, 0).files()
        else:
            assert blocked, 'house build does not block deletion'
            entry = props._variant_list(props.read_sidecar(pid))[0]
            assert entry['uid'] == uid and props.model_gallery(pid, 0).find('full')
            assert props.variant_dims(props.read_sidecar(pid), 0) == dict(width_m=8, height_m=11, depth_m=12)
    case('F4-shift', worker)
    case('F4-deleted', lambda: worker(remove=True))
    case('F5-error', lambda: worker(fail=True))
    assert not failures, failures


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='smoke-house-') as temp:
        root = Path(temp)
        paths.init(root)
        paths.init_instance(root / 'instance')
        from app.core import props, house_props as hp, hull_model
        from app.core.model_store import read_sidecar, write_sidecar
        from app.blender import runner
        final_fix_cases(root)
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
        assert all(n.startswith('row/') or n.startswith('u') for n in names)
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
