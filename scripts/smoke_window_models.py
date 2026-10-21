"""Window cache smoke; run with ./.venv/bin/python scripts/smoke_window_models.py.

Hand-derived expectations: centimetre rounding maps 1.201 to 1.20, but 1.21
changes the key. Casing adds .16 width and .13 height: 1.2 x 1.4 yields
[1.36, 1.53]. Glass alpha .35 and roughness .06; trim roughness .8.
One blocked build plus repeated requests is one job and one generation tick.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import door_models as dm
        from app.core.window_styles import load_window_styles
        from app.core.door_styles import load_door_styles
        from app.core.hull_util import tone_to_linear
        style = load_window_styles()['plain']
        args = [style, 1.2, 1.4, .07, 1, True, None, None]
        sig = dm.window_signature(*args)
        assert dm.safe_signature(sig) == sig
        assert sig == dm.window_signature(style, 1.201, 1.4, .07, 1, True, None, None)
        for index, value in ((1,1.21),(4,-1),(5,False),(6,'#123456'),(7,'#654321')):
            changed = args.copy(); changed[index] = value
            assert sig != dm.window_signature(*changed)
        assert sig != dm.door_signature(load_door_styles()['panel'],1.2,1.4,.07,'single',1,None)
        from PIL import Image
        texture = Path(tmp)/'source.png'
        Image.new('RGB',(1024,256),(200,100,50)).save(texture)
        textured = {**style,'frame_material':'test_texture'}
        with patch.object(dm.surface_textures,'base_texture_file',return_value=texture):
            old = dm.window_signature(textured,*args[1:])
            materials, inputs, sizes = dm._window_materials(textured,None,None,Path(tmp))
            with Image.open(next(iter(inputs.values()))) as image:
                assert image.size == (512,128) and image.getpixel((0,0)) == (200,100,50)
            assert sizes['window_frame'] > 0
            texture.write_bytes(texture.read_bytes()+b'changed')
            assert old != dm.window_signature(textured,*args[1:])
            materials, inputs, _ = dm._window_materials(textured,'#123456','#654321',Path(tmp))
            assert not inputs and materials[0]['color'] == tone_to_linear('#123456')
            assert materials[2]['color'] == materials[0]['color']
            assert materials[1]['color'] == tone_to_linear('#654321')
        entered, release = threading.Event(), threading.Event()
        jobs = []
        def fake(script, *, inputs, out_dir, **kwargs):
            job = json.loads(Path(inputs['job']).read_text()); jobs.append(job)
            meshes = {m['name']:m for m in job['meshes']}
            assert meshes['frame']['material'] == 'window_frame'
            assert meshes['glass']['material'] == 'glass'
            assert meshes['frame_trim']['node'] == 'frame'
            mats = {m['name']:m for m in job['materials']}
            assert mats['glass']['alpha'] == .35 and mats['glass']['roughness'] == .06
            assert mats['glass']['color'] == tone_to_linear(style['glass_tint'])
            assert mats['trim']['roughness'] == .8
            entered.set(); assert release.wait(5)
            (Path(out_dir)/'model.glb').write_bytes(b'fake-glb')
            if job['mode'] == 'thumbnail':
                (Path(out_dir)/'thumbnail.png').write_bytes(b'fake-png')
            return {'ok':True}
        before = dm.generation()
        with patch.object(dm,'_run_blender',fake):
            assert dm.ensure_window_model(style,1.2,1.4,.07) is None
            assert entered.wait(5)
            assert dm.ensure_window_model('plain',1.2,1.4,.07) is None
            release.set(); dm._queue.join()
            assert len(jobs) == 1 and dm.generation() == before+1
            meta = dm.ensure_window_model('plain',1.2,1.4,.07)
            assert meta['url'] == f'/assets/doors/{sig}/model'
            assert meta['kind'] == 'window' and meta['style_id'] == 'plain'
            assert meta['size_m'] == [1.36,1.53]
            assert dm.model_path(sig).read_bytes() == b'fake-glb'
            assert dm.window_style_thumbnail('plain').is_file()
            assert jobs[-1]['mode'] == 'thumbnail'
            dm.window_style_thumbnail('plain'); assert len(jobs) == 2
        with patch.object(dm,'_run_blender',return_value={'ok':False,'error':'expected'}), patch.object(dm.logger,'exception') as logged:
            dm.ensure_window_model('plain',1.21,1.4,.07); dm._queue.join()
            generation = dm.generation()
            dm.ensure_window_model('plain',1.21,1.4,.07)
            assert dm._queue.empty() and dm.generation() == generation
            assert logged.call_count == 1
        from app.routes import assets
        from starlette.requests import Request
        with patch('app.core.glb_delivery.delivery_path',side_effect=lambda path:path):
            response = assets.get_door_model(sig,Request({'type':'http','headers':[]}))
            assert response.status_code == 200 and Path(response.path) == dm.model_path(sig)
        from app.routes import world
        from fastapi import HTTPException
        assert any(s['thumbnail_url']=='/world/window-styles/plain/thumbnail' for s in world.window_style_list()['styles'])
        for key, status in (('missing',404),('plain',503)):
            with patch.object(dm.runner,'is_available',return_value=False):
                try:
                    world.window_style_thumbnail(key)
                except HTTPException as error:
                    assert error.status_code == status
                else:
                    raise AssertionError('expected route error')
        if dm.runner.is_available():
            from app.core.model_validate import parse_glb
            real = dm.build_window_model('plain',1.23,1.4,.07)
            doc = parse_glb(dm.model_path(real['sig']).read_bytes())['gltf']
            assert {'frame','glass'} <= {n.get('name') for n in doc['nodes']}
            print('PASS real Blender: GLB frame/glass nodes')
        else:
            print('SKIP real Blender: unavailable')
        print('PASS window models: signatures, worker, metadata, model path, thumbnail, failure suppression, routes')


if __name__ == '__main__':
    main()
