#!/usr/bin/env python3
"""Usage: .venv/bin/python scripts/smoke_face_photo_adjust.py

Hand expectations: the ellipse spans x=32..223, with linear light
Y=.25+.25*(x-32)/191. Cheek patches x=80..89 and 165..174 have
means .318717 and .429974, ratio 1.34907. Full sqrt(mirror/self)
gain equalizes the cheeks; half gain leaves sqrt(1.34907)=1.16150.
Brightness .5 halves linear luminance; identity preserves exact bytes.
Storage checks use temporary roots before importing DB modules. Frozen .5/.85
controls must survive changed resume arguments, reach sidecars and never join
the four hub controls in local mode. Tone match defaults to 1 and is unsupported locally. A front fallback must freeze 0/.85 with a reason.
Preview is PNG <=512 with no-store; front+balance is HTTP 409.
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.face_photo_adjust import adjust, validated_params

def linear(a):
    s = a[..., :3] / 255.
    return np.where(s <= .04045, s / 12.92, ((s + .055) / 1.055)**2.4)

def regressions():
    # Axis 20.25 maps columns to half-integers: expect 41,40,...,1,
    # each exactly once. Ties-to-even instead duplicates/skips samples.
    from app.core.face_photo_adjust import _mirror_columns
    from PIL import Image
    assert np.array_equal(_mirror_columns(20.25, 41), np.arange(41, 0, -1))
    y, x = np.mgrid[:64, :83]
    mask = (abs(x-30.5) < 25) & (abs(y-31.5) < 28)
    v = (100 + abs(x-30.5)*2).astype('uint8')
    a = np.stack([v,v,v,mask.astype('uint8')*255], -1)
    assert np.max(abs(adjust(a,balance=1,brightness=1).astype(int)-a)) <= 1
    oversized = Image.new('RGBA', (4097, 4096))
    try: adjust(oversized,balance=0,brightness=1)
    except ValueError as exc: assert 'pixel' in str(exc).lower()
    else: raise AssertionError('oversized photo accepted')
    import io
    from app.core.face_retexture import flatten_photo
    raw = io.BytesIO(); oversized.save(raw, 'PNG')
    try: flatten_photo(raw.getvalue())
    except ValueError as exc: assert 'pixel' in str(exc).lower()
    else: raise AssertionError('oversized decoded photo accepted')
    print('PASS: off-centre mirror uniqueness, symmetric no-gain, decoded pixel cap')


def main():
    y, x = np.mgrid[:256, :256]
    mask = ((x-127.5)/95)**2 + ((y-127.5)/115)**2 < 1
    light = .25 + .25 * np.clip((x-32)/191, 0, 1)
    rgb = np.round((1.055 * light**(1/2.4)-.055)*255).astype('uint8')
    a = np.stack([rgb, rgb, rgb, mask.astype('uint8')*255], -1)
    a[120:124, 77:81, :3] //= 2
    assert np.array_equal(adjust(a, balance=0, brightness=1), a)
    def ratio(v):
        l = linear(v).mean(-1)
        return l[105:115, 165:175].mean()/l[105:115, 80:90].mean()
    full = adjust(a, balance=1, brightness=1)
    half = adjust(a, balance=.5, brightness=1)
    assert abs(ratio(full)-1) < .05, ratio(full)
    assert abs(ratio(half)-1.16150) < .06
    assert np.array_equal(full[~mask], a[~mask])
    assert np.array_equal(full, adjust(a, balance=1, brightness=1))
    def contrast(v):
        l = linear(v).mean(-1)
        return l[120:124,77:81].mean()/l[120:124,83:87].mean()
    assert abs(contrast(full)/contrast(a)-1) < .1
    assert np.allclose(linear(adjust(a,balance=0,brightness=.5))[mask], linear(a)[mask]*.5, atol=.004)
    white = np.full((32,32,4),255,dtype='uint8')
    assert np.all(adjust(white,balance=0,brightness=1.5)==255)
    try: adjust(white,balance=1,brightness=1)
    except ValueError: pass
    else: raise AssertionError('opaque accepted')
    for params in ({'balance': True}, {'brightness': float('nan')}, {'balance': 1.1}, {'brightness': .4}):
        try: validated_params(params)
        except ValueError: pass
        else: raise AssertionError(params)
    print('PASS: linear balance, half strength, contrast, alpha, identity, brightness, determinism, validation')

def integration(a):
    import tempfile, os, io, hashlib, json
    from unittest.mock import patch
    from contextlib import ExitStack
    from PIL import Image
    from app.core import paths
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp + '/instance'
        paths.init(Path(tmp)); paths.init_instance(Path(tmp)/'instance')
        from app.core import db, model3d, face_retexture as face, hub_ops
        from app.models.character import save_character_profile
        from smoke_face_retexture_rollback import fixture, photo
        db.init_schema()
        root = Path(tmp)/'characters/demo/model3d'
        (root/'unrigged').mkdir(parents=True)
        refs = root.parent/'model_refs'; refs.mkdir()
        images = root.parent/'images'; images.mkdir()
        (images/'profile.png').write_bytes(photo())
        save_character_profile('demo', {'profile_image':'profile.png'})
        sig='0123456789ab'
        front=refs/f'tpose_{sig}.png'; front.write_bytes(photo())
        meta={'source_image':front.name,'source_image_sha256':hashlib.sha256(front.read_bytes()).hexdigest()}
        for target, raw in ((root/f'{sig}.glb',fixture(rigged=True)),(root/'unrigged'/f'{sig}.glb',fixture())):
            target.write_bytes(raw); target.with_suffix('.json').write_text(json.dumps(meta))
        buf=io.BytesIO(); Image.fromarray(a).save(buf,'PNG'); raw=buf.getvalue()
        face_path=refs/'face_view.png'; face_path.write_bytes(raw)
        face_path.with_suffix('.json').write_text(json.dumps({'image_sha256':hashlib.sha256(raw).hexdigest(),'reference_sha256':hashlib.sha256(photo()).hexdigest()}))
        captured=[]; create=hub_ops.create
        def capture(*args,**kw):
            op=create(*args,**kw); captured.append(op); return op
        class Stop(BaseException): pass
        with ExitStack() as stack:
            stack.enter_context(patch.object(model3d,'required_rig',return_value='mixamo'))
            stack.enter_context(patch.object(face,'runnable',return_value={'ok':True,'problems':[]}))
            stack.enter_context(patch.object(face,'photo_controls_supported',return_value=False))
            stack.enter_context(patch.object(hub_ops,'create',side_effect=capture))
            params={'balance':.5,'brightness':.85,'skin_recolor':1.,'tone_match':1.}
            with patch.object(model3d,'_face_source_stages',side_effect=Stop):
                try: model3d.face_retexture_model('demo',sig,photo=params)
                except Stop: pass
            op=captured[-1]
            assert op.inputs['photo']==params
            expected=face.flatten_photo(raw,params)
            assert op.abs('inputs/photo.png').read_bytes()==expected
            assert model3d.get_model3d_options('demo')['face_photo']=={'balance':.5,'brightness':.85}
            resumed=hub_ops.get(op.op_id)
            with patch.object(model3d,'_face_source_stages',side_effect=Stop) as stages:
                try: hub_ops.resume(resumed,lambda:model3d._face_retexture_model('demo',sig,photo={'balance':0,'brightness':1},_op_ctx={'op':resumed}))
                except Stop: pass
                assert stages.call_args.args[1].inputs['photo']==params
            class Service:
                def generate_face_retexture(self, original, image, target, *args, **kw):
                    assert image == expected
                    assert set(args[0]) == {'strength','feather','render_resolution','yaw'}
                    out = Path(target)/'corrected.glb'
                    out.write_bytes(fixture(corrected=True))
                    return {'ok':True,'path':str(out)}
            with patch('app.imagegen.service.get_image_service',return_value=Service()):
                result = model3d._face_source_stages('demo',resumed)
                assert result['ok'], result
                assert resumed.result('bake')['face_meta']['photo'] == {**params, 'skin_recolor': {'status':'unsupported', 'reason':'needs GLBFaceRetexture >= 1.3'}, 'applied_on':'local'}
                assert resumed.result('bake')['face_meta']['tone_match']['status'] == 'unsupported'
                assert face.read_meta(Path(result['source']))['face_retexture']['photo'] == {**params, 'skin_recolor': {'status':'unsupported', 'reason':'needs GLBFaceRetexture >= 1.3'}, 'applied_on':'local'}
            hub_ops.delete(op)
            from app.routes.characters import preview_character_face_photo
            # A 1024px certified cut-out must reach adjust at <=512px.
            big = io.BytesIO()
            Image.fromarray(a).resize((1024,1024)).save(big,'PNG')
            face_path.write_bytes(big.getvalue())
            face_path.with_suffix('.json').write_text(json.dumps({'image_sha256':hashlib.sha256(big.getvalue()).hexdigest(),'reference_sha256':hashlib.sha256(photo()).hexdigest()}))
            with patch('app.core.face_photo_adjust.adjust', wraps=adjust) as preview_adjust:
                response=preview_character_face_photo('demo',sig,'face',.5,.85)
                assert max(preview_adjust.call_args.args[0].size) <= 512
            face_path.write_bytes(raw)
            face_path.with_suffix('.json').write_text(json.dumps({'image_sha256':hashlib.sha256(raw).hexdigest(),'reference_sha256':hashlib.sha256(photo()).hexdigest()}))
            image=Image.open(io.BytesIO(response.body))
            assert image.format=='PNG' and max(image.size)<=512
            assert response.headers['cache-control']=='no-store'
            from fastapi import HTTPException
            try: preview_character_face_photo('demo',sig,'front',.5,1.)
            except HTTPException as exc: assert exc.status_code==409
            else: raise AssertionError('front balance preview accepted')
            with ExitStack() as generation:
                generation.enter_context(patch.object(model3d,'find_ref_image',return_value=front))
                generation.enter_context(patch('app.core.model_refs.enabled_tpose_views',return_value=[]))
                generation.enter_context(patch.object(model3d,'_ref_manifest',return_value={'pieces':{},'items':[]}))
                generation.enter_context(patch.object(model3d,'_character_mesh_stages',side_effect=Stop))
                model3d.set_model3d_options('demo',{'face_before_rig':True})
                for use_face in (True,False):
                    if not use_face: face_path.unlink()
                    try: model3d.generate_for_current_outfit('demo',signature=sig,force=True)
                    except Stop: pass
                    generated=captured[-1]
                    assert generated.inputs['photo']=={'balance':.5 if use_face else 0.,'brightness':.85,'skin_recolor':1.,'tone_match':1.}
                    assert bool(generated.inputs['photo_reason']) is (not use_face)
                    hub_ops.delete(generated)
            # Defaults are full balance (user decision 2026-10-16): only a deviation
            # from {balance 1, brightness 1} is remembered, so an explicit 0 stays.
            model3d.set_model3d_options('demo',{'face_photo':{'balance':0,'brightness':1}})
            assert model3d.get_model3d_options('demo')['face_photo']=={'balance':0.0}
            model3d.set_model3d_options('demo',{'face_photo':{'balance':1,'brightness':1}})
            assert model3d.get_model3d_options('demo')['face_photo']=={}
            assert validated_params(model3d.get_model3d_options('demo')['face_photo'])=={'balance':1.0,'brightness':1.0,'skin_recolor':1.,'skin_recolor':1.0,'tone_match':1.0}
            # Automatic correction (Improvements: photo=None) uses the remembered values.
            face_path.write_bytes(raw)
            face_path.with_suffix('.json').write_text(json.dumps({'image_sha256':hashlib.sha256(raw).hexdigest(),'reference_sha256':hashlib.sha256(photo()).hexdigest()}))
            model3d.set_model3d_options('demo',{'face_photo':{'balance':.7,'brightness':.9,'skin_recolor':1.,'tone_match':1.}})
            def run(**kw):
                with patch.object(model3d,'_face_source_stages',side_effect=Stop):
                    try: model3d.face_retexture_model('demo',sig,**kw)
                    except Stop: pass
                op=captured[-1]; hub_ops.delete(op); return op.inputs
            inputs=run()
            assert inputs['reference']=='face' and inputs['photo']=={'balance':.7,'brightness':.9,'skin_recolor':1.,'tone_match':1.} and 'photo_reason' not in inputs
            # Front source with a remembered balance: brightness only, reason recorded.
            inputs=run(reference='front')
            assert inputs['photo']=={'balance':0.,'brightness':.9,'skin_recolor':1.,'tone_match':1.} and inputs['photo_reason']
            # An explicit front run (dialog sends balance 0) keeps the remembered balance.
            run(reference='front',photo={'balance':0,'brightness':.8})
            assert model3d.get_model3d_options('demo')['face_photo']=={'balance':.7,'brightness':.8}
            # The dialog's explicit face run overwrites both.
            run(photo={'balance':.4,'brightness':.8})
            assert model3d.get_model3d_options('demo')['face_photo']=={'balance':.4,'brightness':.8}
            # A face view without a cut-out (opaque): remembered balance falls back to
            # brightness only with the reason; an explicit dialog balance is refused.
            opaque=io.BytesIO(); Image.new('RGB',(64,64),(150,120,100)).save(opaque,'PNG')
            face_path.write_bytes(opaque.getvalue())
            face_path.with_suffix('.json').write_text(json.dumps({'image_sha256':hashlib.sha256(opaque.getvalue()).hexdigest(),'reference_sha256':hashlib.sha256(photo()).hexdigest()}))
            inputs=run()
            assert inputs['reference']=='face' and inputs['photo']=={'balance':0.,'brightness':.8,'skin_recolor':1.,'tone_match':1.} and inputs['photo_reason']
            before=len(captured)
            refused=model3d.face_retexture_model('demo',sig,photo={'balance':.4,'brightness':.8})
            assert refused['ok'] is False and refused['problems'][0]['code']=='face_photo' and len(captured)==before
            with ExitStack() as generation:
                generation.enter_context(patch.object(model3d,'find_ref_image',return_value=front))
                generation.enter_context(patch('app.core.model_refs.enabled_tpose_views',return_value=[]))
                generation.enter_context(patch.object(model3d,'_ref_manifest',return_value={'pieces':{},'items':[]}))
                generation.enter_context(patch.object(model3d,'_character_mesh_stages',side_effect=Stop))
                try: model3d.generate_for_current_outfit('demo',signature=sig,force=True)
                except Stop: pass
                generated=captured[-1]
                assert generated.inputs['photo']=={'balance':0.,'brightness':.8,'skin_recolor':1.,'tone_match':1.} and generated.inputs['photo_reason']
                assert 'face_retexture' not in generated.inputs, generated.inputs
                hub_ops.delete(generated)
    print('PASS: default full balance, remembered controls (dialog, Improvements, front keeps balance), frozen photo/resume, sidecar and isolated hub controls, generation face/front fallback, PNG preview and 409')

if __name__ == '__main__':
    regressions()
    main()
    # Recreate the synthetic cut-out for storage integration.
    from PIL import Image, ImageDraw
    image=Image.new('RGBA',(256,256)); ImageDraw.Draw(image).ellipse((30,10,226,246),fill=(140,120,100,255))
    integration(np.asarray(image))
