"""Pure door-cache checks; Usage: ./.venv/bin/python scripts/smoke_door_models.py.

Spec 3.4: signatures round metres to centimetres, use 16 hex digits and include
piece/outside/texture identity. Panel 0.9 x 2.1: casing adds 2*.07 = 1.04 width,
top adds .07 = 2.17 height; leaf starts at .07+.005=.075, threshold+.005=.025.
Last-use retention: 7*86400 SYSTEM seconds, touches at most every 86400 seconds.
Only the external Blender boundary is replaced; storage is always temporary.
"""
import json
import os
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
        from app.core.door_styles import load_door_styles
        from app.core.timeutils import utc_now
        styles = load_door_styles()
        style = styles['panel']
        args = (style, .9, 2.1, .07, 'single', 1, None)
        sig = dm.door_signature(*args)
        assert dm.safe_signature(sig) == sig and not dm.safe_signature('../x')
        assert sig == dm.door_signature(style, .901, 2.1, .07, 'single', 1, None)
        for index, value in ((1,.91),(4,'double_a'),(5,-1),(6,'#123456')):
            changed = list(args); changed[index] = value
            assert sig != dm.door_signature(*changed)
        texture = Path(tmp) / 'texture.png'
        from PIL import Image
        Image.new('RGB', (2,2), (200,100,50)).save(texture)
        textured = {**style, 'leaf_material':'test_texture', 'leaf_tint':'#808080'}
        with patch.object(dm.surface_textures, 'base_texture_file', return_value=texture):
            old = dm.door_signature(textured, .9,2.1,.07,'single',1,None)
            os.utime(texture, ns=(texture.stat().st_atime_ns,texture.stat().st_mtime_ns+1000000))
            assert old != dm.door_signature(textured,.9,2.1,.07,'single',1,None)
            changed = dm.door_signature(textured,.9,2.1,.07,'single',1,None)
            texture.write_bytes(texture.read_bytes()+b'changed-size')
            assert changed != dm.door_signature(textured,.9,2.1,.07,'single',1,None)
            mats, inputs, sizes = dm._materials(textured,'#808080',Path(tmp))
            with Image.open(inputs['texture_door_leaf']) as tinted:
                assert tinted.getpixel((0,0)) == (50,25,13)
            assert sizes['door_leaf'] > 0
        from app.core.hull_util import tone_to_linear
        plain, _, _ = dm._materials(style,'#123456',Path(tmp))
        assert plain[0]['color'] == tone_to_linear('#123456')
        assert plain[1]['color'] == tone_to_linear(style['frame_material'])
        assert plain[2]['alpha'] == .35 and plain[2]['roughness'] == .06
        assert plain[3]['roughness'] == .3
        escape = Path(tmp)/'outside'; escape.mkdir()
        (escape/'model.glb').write_bytes(b'outside')
        root=Path(tmp)/'door_models'; root.mkdir()
        (root/('f'*16)).symlink_to(escape,target_is_directory=True)
        assert dm.model_path('f'*16) is None
        assert dm.sweep_cache()==0
        entered, release = threading.Event(), threading.Event()
        jobs = []
        def fake(script, *, inputs, out_dir, **kwargs):
            job = json.loads(Path(inputs['job']).read_text())
            jobs.append(job); entered.set()
            meshes={mesh['name']:mesh for mesh in job['meshes']}
            assert 'frame' in meshes and 'leaf' in meshes
            assert meshes['leaf']['node']=='leaf'
            assert 'leaf_hardware' in meshes
            # Model y-up becomes Blender z-up: leaf .025 floor clearance is z.
            assert min(v[2] for v in meshes['leaf']['vertices']) == .025
            assert release.wait(5)
            target = Path(out_dir) / 'model.glb'; target.write_bytes(b'fake-glb')
            outputs = {'model':str(target)}
            if job['mode'] == 'thumbnail':
                image = Path(out_dir) / 'thumbnail.png'; image.write_bytes(b'fake-png')
                outputs['thumbnail'] = str(image)
            return {'ok':True,'outputs':outputs}
        with patch.object(dm, '_run_blender', fake):
            assert dm.ensure_door_model('panel',.9,2.1,.07) is None
            assert entered.wait(5)
            assert dm.ensure_door_model('panel',.9,2.1,.07) is None
            release.set(); dm._queue.join()
            assert len(jobs)==1 and dm.generation()==1
            model = dm.ensure_door_model('panel',.9,2.1,.07)
            assert model['url']==f'/assets/doors/{sig}/model'
            assert model['size_m']==[1.04,2.17]
            assert model['leaf_bbox']['min']==[.075,.025,-.0225]
            meta = dm.model_path(sig).with_name('meta.json')
            before=meta.stat().st_mtime_ns
            assert dm.ensure_door_model('panel',.9,2.1,.07)==model
            assert meta.stat().st_mtime_ns==before
            now=utc_now().timestamp()
            os.utime(meta,(now-2*86400,now-2*86400))
            dm.ensure_door_model('panel',.9,2.1,.07)
            assert meta.stat().st_mtime>now-1
            assert dm.style_thumbnail('panel').is_file()
            assert len(jobs)==2
            dm.style_thumbnail('panel'); assert len(jobs)==2
            assert dm.sweep_cache()==0
            os.utime(meta,(now-8*86400,now-8*86400))
            assert dm.sweep_cache()==1 and dm.model_path(sig) is None
        failed = threading.Event()
        def bad(*args, **kwargs):
            failed.set(); return {'ok':False,'error':'expected smoke failure'}
        with patch.object(dm,'_run_blender',bad), patch.object(dm.logger,'exception') as logged:
            dm.ensure_door_model('panel',.92,2.1,.07)
            assert failed.wait(5); dm._queue.join()
            generation=dm.generation()
            dm.ensure_door_model('panel',.92,2.1,.07)
            assert dm._queue.empty() and dm.generation()==generation
            assert logged.call_count==1
        print('PASS door models: signature, texture identity, worker dedup, metadata, touch, thumbnail, sweep, failed-build suppression')

if __name__ == '__main__':
    main()
