#!/usr/bin/env python3
"""P3 §4.6: stored/served FBX must equal the backend bytes after post-steps.

Hand-derived expected value: equality, because retexture/normalize/extensions,
LOD and meshopt only process GLB. The backend is stubbed; the service, mesh
channel handoff, validators and model3d re-rig store/publication path are real.
The PNG is 16x16 (> validation's 8px minimum) and must also stay unchanged.
Usage: ./.venv/bin/python scripts/smoke_quadruped_fbx_untouched.py
"""
import io
import json
import os
import struct
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='av-fbx-untouched-') as tmp:
        os.environ['STORAGE_DIR'] = tmp+'/world'
        os.environ['INSTANCE_DIR'] = tmp+'/instance'
        from app.core import paths
        paths.init(os.environ['STORAGE_DIR'])
        paths.init_instance(tmp+'/instance')
        from app.core import db, model3d
        db.init_schema()
        from PIL import Image
        from app.imagegen.base import ImageBackend
        from app.imagegen.selection import BackendPool
        from app.imagegen.service import ImageService
        from app.core.model_store import read_sidecar
        from app.blender import refine, runner
        out=Path(tmp)/'models'
        (out/'unrigged').mkdir(parents=True)
        png=io.BytesIO()
        Image.new('RGB',(16,16),'red').save(png,format='PNG')
        texture=png.getvalue()
        doc={'asset':{'version':'2.0'},'meshes':[{'primitives':[{'material':0}]}],
             'buffers':[{'byteLength':len(texture)}], 'bufferViews':[{'byteOffset':0,'byteLength':len(texture)}],
             'images':[{'bufferView':0,'mimeType':'image/png'}], 'textures':[{'source':0}],
             'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}]}
        raw=json.dumps(doc).encode()
        raw+=b' '*((-len(raw))%4)
        binary=texture+b'\0'*((-len(texture))%4)
        chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
        source=out/'unrigged/fixture.glb'
        source.write_bytes(b'glTF'+struct.pack('<II',2,len(chunks)+12)+chunks)
        source.with_suffix('.png').write_bytes(texture)
        fbx=b'Kaydara FBX Binary\x00\x1a\x00P3 byte preservation fixture'
        metrics={'takes':[],'fold_mean':1.05}
        class Stub(ImageBackend):
            MEDIA_TYPE='mesh'
            REQUIRES_URL=False
            def __init__(self):
                super().__init__('quadruped-local','',0,'local_quadruped_rig','P3_UNTOUCHED_')
                self.category='mesh2rig'
                self._available=True
                self.last_result_rig='generic'
                self.last_result_meta=metrics
                self.last_result_files=[{'name':'result_rigged.fbx','kind':'model'},
                                        {'name':'result_basecolor.png','kind':'image'}]
            def check_availability(self): return True
            def _generate(self,prompt,negative,params): return [fbx,texture]
        backend=Stub()
        svc=object.__new__(ImageService)
        svc._pool=BackendPool([backend])
        calls=[]
        def channel(b,fn,**kwargs):
            calls.append(b.name)
            return fn()
        with ExitStack() as stack:
            stack.enter_context(patch('app.imagegen.service.get_image_service',return_value=svc))
            stack.enter_context(patch.object(svc,'run_on_backend_channel',side_effect=channel))
            stack.enter_context(patch.object(model3d,'get_model3d_dir',return_value=out))
            stack.enter_context(patch.object(model3d,'find_model3d',return_value=None))
            stack.enter_context(patch.object(model3d,'required_rig',return_value='generic'))
            stack.enter_context(patch.object(refine,'auto_normalize_enabled',return_value=True))
            stack.enter_context(patch.object(refine,'auto_retexture_enabled',return_value=True))
            stack.enter_context(patch.object(model3d,'_auto_lod_enabled',return_value=True))
            # Measurement changes only meta. No Blender runner may rewrite FBX.
            stack.enter_context(patch.object(refine,'measure_file',return_value={'dims_m':[1,2,1]}))
            run=stack.enter_context(patch.object(runner,'run',side_effect=AssertionError('FBX post-step attempted Blender')))
            result=model3d._rig_from_source('demo','fixture',source,rig_backend_glob='quadruped-local')
            assert result['ok'],result
            stored=out/'fixture.fbx'
            assert stored.read_bytes()==fbx
            assert (out/'raw/fixture.fbx').read_bytes()==fbx
            assert stored.with_suffix('.png').read_bytes()==texture
            assert read_sidecar(stored)['rig_metrics']==metrics
            assert calls==['quadruped-local'] and not run.called
        print('PASS FBX backend bytes equal full/raw delivered bytes after real model3d post-steps')


if __name__=='__main__':
    main()
