#!/usr/bin/env python3
"""Usage: .venv/bin/python scripts/smoke_face_photo_hub.py

Hand-derived contract: all three verified public names are required for hub
controls. Frozen .4/.65/.85 must map unchanged; an old or partial schema
gets none of the three. Tone match defaults to 1, accepts endpoints 0/1,
and rejects booleans, nonfinite numbers and values outside [0, 1].
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.face_photo_adjust import validated_params
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend


def main():
    assert validated_params({}) == {'balance': 1., 'tone_match': 1., 'brightness': 1.}
    for value in (False, float('nan'), -.01, 1.01):
        try:
            validated_params({'tone_match': value})
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid tone match accepted: {value}')
    for value in (0, 1):
        assert validated_params({'tone_match': value})['tone_match'] == value
    backend = OpenAIMeshBackend('face', 'http://gateway.invalid', 0, 'SMOKE_FACE_HUB_')
    backend.category = 'face_retexture'
    controls = {'light_balance': .4, 'tone_match': .65, 'brightness': .85}
    for verified, names, supported in (
        (True, set(controls), True), (False, set(controls), False),
        (True, {'light_balance', 'brightness'}, False), (True, set(), False),
    ):
        backend._face_schema = (verified, (), '', frozenset(names))
        assert backend.photo_controls_supported() is supported
        assert backend.build_alias_params(controls) == (controls if supported else {})
    print('PASS: tone match defaults/validation, verified all-or-none hub photo controls')

def integration():
    """Neutral bytes must survive .4/.65/.85 hub controls and an old fallback.

    A front source is deliberately opaque: local balance refuses it; hub
    balance must accept it without changing a byte. Old operations omit mode
    and tone_match: their already adjusted bytes must be used unchanged.
    """
    import hashlib
    import io
    import json
    import os
    import tempfile
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch
    from PIL import Image
    from app.core import paths

    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp + '/instance'
        paths.init(Path(tmp)); paths.init_instance(Path(tmp) / 'instance')
        from app.core import db, face_retexture as face, model3d, hub_ops
        from app.models.character import save_character_profile
        from app.imagegen.service import ImageService
        from app.routes.characters import (check_character_face_retexture,
                                          preview_character_face_photo,
                                          start_character_face_retexture)
        from smoke_face_retexture_rollback import fixture, photo
        db.init_schema()
        root = Path(tmp) / 'characters/demo/model3d'
        (root / 'unrigged').mkdir(parents=True)
        refs = root.parent / 'model_refs'; refs.mkdir()
        images = root.parent / 'images'; images.mkdir()
        raw = photo()
        (images / 'profile.png').write_bytes(raw)
        save_character_profile('demo', {'profile_image': 'profile.png'})
        sig = '0123456789ab'
        front = refs / f'tpose_{sig}.png'; front.write_bytes(raw)
        meta = {'source_image': front.name, 'source_image_sha256': hashlib.sha256(raw).hexdigest()}
        for target, blob in ((root / f'{sig}.glb', fixture(rigged=True)),
                             (root / 'unrigged' / f'{sig}.glb', fixture())):
            target.write_bytes(blob)
            target.with_suffix('.json').write_text(json.dumps(meta))
        photo_params = {'balance': .4, 'tone_match': .65, 'brightness': .85}
        public = {'light_balance': .4, 'tone_match': .65, 'brightness': .85}
        neutral = face.flatten_photo(raw)
        captured = []
        create = hub_ops.create
        class Stop(BaseException):
            pass
        def capture(*args, **kwargs):
            op = create(*args, **kwargs); captured.append(op); return op
        def new_op(**kwargs):
            with patch.object(model3d, '_face_source_stages', side_effect=Stop):
                try:
                    model3d.face_retexture_model('demo', sig, upscale=False, **kwargs)
                except Stop:
                    pass
            return captured[-1]
        # Real service orchestration, replacing only GPU/network boundaries.
        backend = OpenAIMeshBackend('actual', 'http://gateway.invalid', 0, 'SMOKE_FACE_HUB_')
        backend.category = 'face_retexture'
        sent = []
        def generate(_prompt, _negative, request, **kwargs):
            sent.append(dict(request))
            backend._tls.result_files = [{'name': 'corrected.glb', 'mime': 'model/gltf-binary'}]
            return [fixture(corrected=True)]
        service = ImageService.__new__(ImageService)
        service._pool = SimpleNamespace(backends=[backend])
        def routed(_occasion, render, **kwargs):
            return render(backend), None
        with (patch('app.imagegen.service.get_image_service', return_value=service),
              patch('app.imagegen.routing.resolve_image_route', return_value=SimpleNamespace(backend=backend)) as resolve,
              patch('app.imagegen.routing.resolve_spec', return_value=('', backend)) as explicit):
            backend._face_schema = (True, (), '', frozenset(public))
            assert face.photo_controls_supported('demo')
            assert resolve.call_args.kwargs == {'character': 'demo', 'probe': True, 'pool': service.pool}
            assert face.photo_controls_supported('demo', 'actual')
            assert explicit.call_args.args == ('face_retexture', 'actual')
            backend._face_schema = (True, (), '', frozenset())
            assert not face.photo_controls_supported('demo', 'actual')
        with ExitStack() as stack:
            stack.enter_context(patch.object(model3d, 'required_rig', return_value='mixamo'))
            stack.enter_context(patch.object(face, 'runnable', return_value={'ok': True, 'problems': []}))
            stack.enter_context(patch.object(face, 'photo_controls_supported', return_value=True))
            stack.enter_context(patch.object(hub_ops, 'create', side_effect=capture))
            stack.enter_context(patch.object(backend, 'generate', side_effect=generate))
            stack.enter_context(patch.object(service, 'run_on_backend', side_effect=lambda b, fn, **kw: (fn(b), b)))
            stack.enter_context(patch.object(service, 'run_on_backend_channel', side_effect=lambda b, fn, **kw: fn()))
            stack.enter_context(patch('app.imagegen.routing.run_routed', side_effect=routed))
            stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=service))
            # A certified face view is frozen neutrally, just like the front.
            face_path = refs / 'face_view.png'
            face_path.write_bytes(raw)
            face_path.with_suffix('.json').write_text(json.dumps({
                'image_sha256': hashlib.sha256(raw).hexdigest(),
                'reference_sha256': hashlib.sha256(raw).hexdigest()}))
            face_op = new_op(reference='face', photo=photo_params)
            assert face_op.inputs['photo_mode'] == 'hub'
            assert face_op.abs('inputs/photo.png').read_bytes() == neutral
            hub_ops.delete(face_op)
            face_path.unlink()
            for supported in (True, False):
                backend._face_schema = (True, (), '', frozenset(public if supported else ()))
                op = new_op(reference='front', photo=photo_params)
                assert op.inputs['photo_mode'] == 'hub'
                assert op.inputs['photo'] == photo_params
                assert op.abs('inputs/photo.png').read_bytes() == neutral
                assert model3d.get_model3d_options('demo')['face_photo'] == photo_params
                # Simulate restart, with different caller arguments and route capability.
                resumed = hub_ops.get(op.op_id)
                with patch.object(model3d, '_face_source_stages', side_effect=Stop) as stages:
                    try:
                        hub_ops.resume(resumed, lambda: model3d._face_retexture_model(
                            'demo', sig, photo={'balance': 0, 'tone_match': 0, 'brightness': 1},
                            _op_ctx={'op': resumed}))
                    except Stop:
                        pass
                    assert stages.call_args.args[1].inputs['photo'] == photo_params
                result = model3d._face_source_stages('demo', resumed)
                assert result['ok'], result
                assert sent[-1]['reference_image_bytes'] == neutral
                assert {k: sent[-1][k] for k in public if k in sent[-1]} == (public if supported else {})
                photo_meta = resumed.result('bake')['face_meta']['photo']
                assert {k: photo_meta[k] for k in photo_params} == photo_params
                assert photo_meta['applied_on'] == ('hub' if supported else 'none')
                assert bool(photo_meta.get('reason')) is (not supported)
                assert resumed.state['face_photo_application']['applied_on'] == photo_meta['applied_on']
                # Collection after restart uses the persisted payload verdict,
                # even when the alias now advertises a different capability.
                with patch.object(service, '_hub_attached', return_value={
                    'files': [{'name': 'corrected.glb', 'mime': 'model/gltf-binary'}],
                    'blobs': [fixture(corrected=True)], 'backend': backend.name, 'job_id': 'old-job'}):
                    attached = service.generate_face_retexture(
                        'unused', neutral, str(op.path('attach', 'x').parent),
                        public, hub_stage=hub_ops.get(op.op_id).stage('face'))
                assert attached['photo_application'] == resumed.state['face_photo_application']
                hub_ops.delete(op)
            # Availability can refresh the schema between service preflight
            # and backend execution. The exact payload must decide provenance.
            backend._face_schema = (True, (), '', frozenset(public))
            race_op = new_op(reference='front', photo=photo_params)
            payloads = []
            def downgrade(_prompt, _negative, request, **kwargs):
                backend._face_schema = (True, (), '', frozenset())
                return backend._generate('', '', request)
            def submit(_backend, _url, payload, _label, **kwargs):
                payloads.append(payload)
                return 'race-job'
            def collect(*args, **kwargs):
                backend._tls.result_files = [{'name': 'corrected.glb', 'mime': 'model/gltf-binary'}]
                return [fixture(corrected=True)]
            with (patch.object(backend, 'generate', side_effect=downgrade),
                  patch.object(backend, 'build_input_files', return_value={'mesh': 'encoded'}),
                  patch.object(backend, 'select_slot_images', return_value={'image': 'reference'}),
                  patch.object(backend, '_collect', side_effect=collect),
                  patch('app.imagegen.backends.openai_mesh.submit_job', side_effect=submit)):
                assert model3d._face_source_stages('demo', race_op)['ok']
            assert not public.keys() & payloads[-1]['params'].keys()
            assert race_op.result('bake')['face_meta']['photo']['applied_on'] == 'none'
            assert race_op.state['face_photo_application']['applied_on'] == 'none'
            hub_ops.delete(race_op)
            # Old operations: no mode and no tone_match, locally adjusted input.
            old_photo = {'balance': 0., 'brightness': .85}
            old = create(model3d._OP_FACE, model3d._op_subject('demo', sig), {
                'character': 'demo', 'signature': sig, 'controls': face.validated_params(),
                'photo': old_photo, 'upscale': False, 'reference': 'front', 'source_kind': 'facefix'})
            adjusted = face.flatten_photo(raw, old_photo)
            old.path('inputs', 'photo.png').write_bytes(adjusted)
            old.freeze_file(root / 'unrigged' / f'{sig}.glb', 'inputs', 'unrigged', f'{sig}.glb')
            backend._face_schema = (True, (), '', frozenset(public))
            result = model3d._face_source_stages('demo', old)
            assert result['ok']
            assert sent[-1]['reference_image_bytes'] == adjusted
            assert not public.keys() & sent[-1].keys()
            old_meta = old.result('bake')['face_meta']
            assert old_meta['photo'] == {**old_photo, 'tone_match': 0., 'applied_on': 'local'}
            assert old_meta['tone_match']['status'] == 'unsupported'
            hub_ops.delete(old)
            # Check and preview agree with selected capability, front hub preview
            # equals brightness-only output and explains the approximation.
            for hub in (True, False):
                with patch.object(face, 'photo_controls_supported', return_value=hub):
                    checked = check_character_face_retexture('demo', sig, reference='front')
                    assert checked['photo_controls'] == ('hub' if hub else 'local')
            response = preview_character_face_photo('demo', sig, 'front', .4, .85)
            assert response.status_code == 200
            assert 'Brightness-only' in response.headers['x-face-photo-preview']
            expected = face.flatten_photo(raw, {'balance': 0., 'brightness': .85}, max_size=512)
            assert Image.open(io.BytesIO(response.body)).tobytes() == Image.open(io.BytesIO(expected)).tobytes()
            with patch.object(model3d, 'trigger_face_retexture', return_value={'status': 'generating'}) as trigger:
                started = start_character_face_retexture(
                    'demo', sig, strength=1, feather=.18, render_resolution=768,
                    balance=.4, tone_match=.65, brightness=.85, yaw=0, reference='front', upscale=False)
                assert started['status'] == 'generating'
                assert trigger.call_args.kwargs['photo'] == photo_params
            # Remembered controls drive automatic face-before-rig hub mode, too.
            with ExitStack() as generation:
                generation.enter_context(patch.object(model3d, 'find_ref_image', return_value=front))
                generation.enter_context(patch('app.core.model_refs.enabled_tpose_views', return_value=[]))
                generation.enter_context(patch.object(model3d, '_ref_manifest', return_value={'pieces': {}, 'items': []}))
                generation.enter_context(patch.object(model3d, '_character_mesh_stages', side_effect=Stop))
                model3d.set_model3d_options('demo', {'face_before_rig': True})
                try:
                    model3d.generate_for_current_outfit('demo', signature=sig, force=True)
                except Stop:
                    pass
                generated = captured[-1]
                assert generated.inputs['reference'] == 'front'
                assert generated.inputs['photo_mode'] == 'hub'
                assert generated.inputs['photo'] == photo_params
                assert generated.abs('inputs/photo.png').read_bytes() == neutral
                hub_ops.delete(generated)
            model3d.set_model3d_options('demo', {'face_photo': {'tone_match': .25}})
            assert model3d.get_model3d_options('demo')['face_photo'] == {'tone_match': .25}
            model3d.set_model3d_options('demo', {'face_photo': {}})
            assert model3d.get_model3d_options('demo')['face_photo'] == {}
    print('PASS: neutral frozen hub inputs/front balance, remembered tone match, actual old-backend fallback + sidecar, old local resume, check/start/preview routes, face-before-rig')


if __name__ == '__main__':
    main()
    integration()
