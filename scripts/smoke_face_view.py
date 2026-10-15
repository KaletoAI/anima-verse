#!/usr/bin/env python3
"""Dedicated face reference contract, derived by hand from the brief.

Only humanoids get a face view; it is not a reconstruction camera. A face
photo is eligible only when its bytes match image_sha256 and its nonempty
front hash equals reference_sha256. Reads must finish while the render lock
is held; mismatches get three attempts before being rejected.
Missing, corrupt or stale face photos choose front automatically, while an
explicit face choice fails. Face defaults to no upscale; explicit True wins.
All storage is temporary and initialized before world modules are imported.
Usage: ./.venv/bin/python scripts/smoke_face_view.py
"""
import hashlib
import json
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(Path(tmp))
        from app.core import face_retexture as face, model_refs
        from app.core.outfit_cache_gc import REF_PREFIXES
        from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
        from smoke_face_retexture_rollback import photo
        assert 'face' in model_refs.TPOSE_VIEWS_BY_BODY['humanoid']
        assert 'face' not in model_refs.TPOSE_VIEWS_BY_BODY['animal']
        assert 'tpose_face' in model_refs.VIEW_KINDS
        for kind in ('tpose_face', 'tpose_back', 'tpose_left', 'tpose_right', 'tpose'):
            name = kind + '_0123456789ab'
            prefix = next(p for p in REF_PREFIXES if name.startswith(p))
            assert name[len(prefix):] == '0123456789ab', (name, prefix)
        prompt = model_refs.TPOSE_FACE_PROMPT_DEFAULT.lower()
        assert 'the same hairstyle as the reference' in prompt
        assert 'hair arranged exactly as in the reference' in prompt
        assert 'pull hair back' not in prompt
        refs = Path(tmp) / 'characters' / 'demo' / 'model_refs'
        refs.mkdir(parents=True)
        sig = '0123456789ab'
        front = refs / f'tpose_{sig}.png'
        front.write_bytes(photo())
        meta = {'source_image': front.name, 'source_image_sha256': hashlib.sha256(front.read_bytes()).hexdigest()}
        with patch('app.models.character.get_character_dir', return_value=refs.parent):
            assert face.reference_info('demo', sig, meta)['reference'] == 'front'
            face_path = refs / f'tpose_face_{sig}.png'
            face_path.write_bytes(photo())
            face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': meta['source_image_sha256'], 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
            held, release = threading.Event(), threading.Event()
            def hold_render_lock():
                with model_refs._kind_lock(('demo', 'tpose')):
                    held.set()
                    release.wait()
            holder = threading.Thread(target=hold_render_lock)
            holder.start()
            assert held.wait(2)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(face.reference_info, 'demo', sig, meta)
                try:
                    info = pending.result(timeout=2)
                finally:
                    release.set()
                    holder.join(timeout=2)
            assert info['reference'] == 'face'
            # A valid replacement image with the old sidecar is still unusable.
            original = face_path.read_bytes()
            from PIL import Image
            import io
            replacement = io.BytesIO()
            Image.new('RGB', (32, 32), 'red').save(replacement, 'PNG')
            face_path.write_bytes(replacement.getvalue())
            rejected = face.reference_info('demo', sig, meta, 'face')
            assert not rejected['face_available'] and rejected['problems']
            assert 're-rendered' in rejected['face_problem']['message']
            with patch.object(face, 'read_meta', wraps=face.read_meta) as reads:
                assert not face.reference_info('demo', sig, meta)['face_available']
                assert reads.call_count == 3
            face_path.write_bytes(original)
            valid_meta = face.read_meta(face_path)
            with patch.object(face, 'read_meta', side_effect=[
                    {**valid_meta, 'image_sha256': 'publication in progress'},
                    {**valid_meta, 'image_sha256': 'publication in progress'}, valid_meta]) as reads:
                assert face.reference_info('demo', sig, meta)['face_available']
                assert reads.call_count == 3
            sidecar = face_path.with_suffix('.json')
            certified = sidecar.read_text()
            sidecar.write_text(json.dumps({'reference_sha256': meta['source_image_sha256']}))
            missing = face.reference_info('demo', sig, meta, 'face')
            assert not missing['face_available'] and 'regenerate' in missing['face_problem']['fix'].lower()
            sidecar.write_text(certified)
            info = face.reference_info('demo', sig, meta)
            assert info['reference'] == 'face' and not info['problems']
            assert face.photo_path('demo', sig, meta, reference='face') == face_path
            jpg = face_path.with_suffix('.jpg')
            from PIL import Image
            with Image.open(face_path) as image:
                image.convert('RGB').save(jpg, 'JPEG')
            original_face = face_path.read_bytes()
            face_path.unlink()
            jpg.with_suffix('.json').write_text(json.dumps({'reference_sha256': meta['source_image_sha256'], 'image_sha256': hashlib.sha256(jpg.read_bytes()).hexdigest()}))
            assert face.photo_path('demo', sig, meta, reference='face') == jpg
            snapshot = {}
            assert face.reference_info('demo', sig, meta, _snapshot=snapshot)['reference'] == 'face'
            assert snapshot['image'] == face.flatten_photo(jpg.read_bytes())
            jpg.unlink()
            face_path.write_bytes(original_face)
            face_path.with_suffix('.json').write_text(certified)
            assert face.use_upscale('face', None) is False
            assert face.use_upscale('front', None) is True
            assert face.use_upscale('face', True) is True
            face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': 'old', 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
            assert face.reference_info('demo', sig, meta)['reference'] == 'front'
            assert face.reference_info('demo', sig, meta, 'face')['problems'][0]['code'] == 'face_stale'
            face_path.write_bytes(b'not an image')
            assert face.reference_info('demo', sig, meta)['reference'] == 'front'
        from app.core.head_twist import tpose_status
        assert tpose_status('exact', {**meta, 'view_images': {'face': 'missing.png'},
                            'view_images_sha256': {'face': 'ignored'}}, front) == 'current'
        assert OpenAIMeshBackend._input_images({'reference_images': {'face': 'face.png'},
                                               'source_image_path': 'front.png'}) == {'front': 'front.png'}
        views = {'face': 'face.png', 'back': 'back.png'}
        assert 'face.png' not in OpenAIMeshBackend.mesh_slot_views('humanoid', 'front.png', views, ['input_image']).values()
        assert 'face.png' not in OpenAIMeshBackend.select_slot_images(['face_image', 'input_image'], {**views, 'front': 'front.png'}).values()
        integration(Path(tmp), refs, sig, front, meta)
    print('PASS: face view registration, provenance, JPEG snapshot, nonblocking reads, image self-check, source defaults, upscale and mesh slots')



def publication_races(refs, sig, front, meta):
    """Backend swaps front A before reading; its input must still be A.

    A rename hook publishes B before A's certificate: the reader must reject
    B with A's certificate. A return hook publishes B after A returns: the
    orchestrator must preserve B's certificate. Processed B differs from the
    backend output, so hashing before postprocessing also fails this check.
    """
    from app.core import expression_regen as er, face_retexture as face, model_refs as mr
    from smoke_face_retexture_rollback import photo
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(buf, 'PNG')
    other, original = buf.getvalue(), photo()
    target = refs / f'tpose_face_{sig}.png'
    images = refs.parent / 'images'
    images.mkdir(exist_ok=True)
    seen = []
    class Service:
        enabled = True
        last_image_meta = {}
        def generate_from_input(self, raw):
            payload = json.loads(raw)
            front.write_bytes(other)
            reference = Path(mr.checked_reference_override('demo', payload['reference_image_override']))
            seen.append(reference.read_bytes())
            output = images / f'render-{len(seen)}.png'
            output.write_bytes(original)
            return f'/images/{output.name}'
    def postprocess(path):
        path.write_bytes(other if seen[-1] == other else original)
        return path
    render = er.generate_expression_image
    def call():
        return render('demo', '', '', equipped_pieces={}, equipped_items=[],
            output_stem=target.with_suffix(''), reference_image=front,
            apply_state_modifiers=False, record_provenance=True)
    with (patch('app.imagegen.service.get_image_service', return_value=Service()),
          patch('app.models.character.postprocess_outfit_image', side_effect=postprocess)):
        front.write_bytes(original)
        assert call() == target
        cert = face.read_meta(target)
        assert seen[-1] == original
        assert cert['reference_sha256'] == hashlib.sha256(seen[-1]).hexdigest()
        assert cert['image_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
        rename = Path.rename
        injected = False
        def overlap(path, dest):
            nonlocal injected
            result = rename(path, dest)
            if Path(dest) == target and not injected:
                injected = True
                assert call() == target
            return result
        front.write_bytes(original)
        with patch.object(Path, 'rename', overlap):
            assert call() == target
        assert injected and target.read_bytes() == other
        assert not face.reference_info('demo', sig, meta, 'face')['face_available']
        def publish_after_return(*args, **kw):
            result = render(*args, **kw)
            assert call() == target
            return result
        front.write_bytes(original)
        with (patch.object(mr, 'is_humanoid', return_value=True),
              patch.object(mr, 'enabled_tpose_views', return_value=('face',)),
              patch.object(er, 'generate_expression_image', side_effect=publish_after_return)):
            mr.generate_model_ref_images('demo', kinds=('tpose',), force=True,
                tpose_view='face', pieces={}, items=[], signature=sig)
        cert = face.read_meta(target)
        assert cert['reference_sha256'] == hashlib.sha256(other).hexdigest()
        assert cert['image_sha256'] == hashlib.sha256(other).hexdigest()
        assert not face.reference_info('demo', sig, meta, 'face')['face_available']
    front.write_bytes(original)
    print('PASS: writer reference snapshot, overlapping publication self-check, no post-return certification')

def integration(tmp, refs, sig, front, meta):
    """Exercise the real render/orchestrator/stages with external services faked."""
    from app.core import db, expression_regen, face_retexture as face, hub_ops, model3d, model_refs as mr
    from app.models.character import save_character_profile
    from smoke_face_retexture_rollback import fixture, photo
    paths.init_instance(tmp / 'instance')
    db.init_schema()
    assert save_character_profile('demo', {})
    face_path = refs / f'tpose_face_{sig}.png'
    publication_races(refs, sig, front, meta)
    def render(name, **kw):
        assert kw['record_provenance'] is True
        assert kw['reference_image'] == front
        assert kw['occasion'] == 'tpose_view' and kw['image_use_case'] == 'tpose_face'
        assert kw['expression_prompt_override'] == mr.REF_EXPRESSION_PROMPT
        target = Path(str(kw['output_stem']) + '.png')
        target.write_bytes(photo())
        target.with_suffix('.json').write_text(json.dumps({'pieces': {'body': 'shirt'}, 'items': [], 'reference_sha256': hashlib.sha256(front.read_bytes()).hexdigest(), 'image_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}))
        return target
    with (patch.object(mr, 'is_humanoid', return_value=True),
          patch.object(mr, 'enabled_tpose_views', return_value=('face',)),
          patch.object(expression_regen, 'generate_expression_image', side_effect=render)):
        result = mr.generate_model_ref_images('demo', kinds=('tpose',), force=True,
            tpose_view='face', pieces={'body': 'shirt'}, items=[], signature=sig)
    assert result['tpose_face'] == str(face_path)
    assert face.read_meta(face_path)['reference_sha256'] == meta['source_image_sha256']
    assert face.read_meta(face_path)['image_sha256'] == hashlib.sha256(face_path.read_bytes()).hexdigest()
    root = refs.parent / 'model3d'
    root.mkdir(exist_ok=True)
    (root / 'unrigged').mkdir(exist_ok=True)
    for target, raw in ((root / f'{sig}.glb', fixture(rigged=True)),
                        (root / 'unrigged' / f'{sig}.glb', fixture())):
        target.write_bytes(raw)
        target.with_suffix('.json').write_text(json.dumps(meta))
    face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': 'old', 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
    with patch.object(model3d, 'required_rig', return_value='mixamo'):
        verdict = face.check('demo', sig, 'face')
        assert not verdict['ok'] and 'face_stale' in {p['code'] for p in verdict['problems']}
    face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': meta['source_image_sha256'], 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
    operations = []
    create = hub_ops.create
    def capture(*args, **kw):
        op = create(*args, **kw)
        operations.append(op)
        return op
    class Service:
        def generate_face_retexture(self, original, image, target, *args, **kw):
            assert image == face.flatten_photo(photo())
            out = Path(target) / 'corrected.glb'
            out.write_bytes(fixture(corrected=True))
            return {'ok': True, 'path': str(out), 'backend': 'face-fixture'}
        def generate_rig(self, **kw):
            from app.core.model_validate import parse_glb
            from app.core.rig_contract import BASE_JOINT_NAMES
            from smoke_face_retexture_check import glb
            parsed = parse_glb(Path(kw['mesh_path']).read_bytes())
            doc = parsed['gltf']
            doc['nodes'] = [{'name': name} for name in BASE_JOINT_NAMES]
            doc['skins'] = [{'joints': list(range(52))}]
            Path(kw['output_path']).write_bytes(glb(doc, parsed['bin']))
            return {'ok': True, 'path': kw['output_path'], 'rig': 'mixamo', 'backend': 'rig-fixture'}
        def upscale_image(self, *args, **kw):
            raise AssertionError('Matching face view must skip upscale')
    flatten = face.flatten_photo
    swapped = False
    def swap_after_validation(raw):
        # A publication after validation must not change the frozen input.
        nonlocal swapped
        result = flatten(raw)
        if not swapped:
            swapped = True
            face_path.write_bytes(b'replacement image B, never validated')
            face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': 'other front'}))
        return result
    def interrupted(*args):
        raise SystemExit('restart boundary')
    with ExitStack() as stack:
        stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=Service()))
        stack.enter_context(patch.object(hub_ops, 'create', side_effect=capture))
        stack.enter_context(patch.object(model3d, 'required_rig', return_value='mixamo'))
        stack.enter_context(patch.object(face, 'runnable', return_value={'ok': True, 'problems': []}))
        stack.enter_context(patch.object(mr, 'enabled_tpose_views', return_value=('face',)))
        stack.enter_context(patch.object(model3d, '_ref_manifest', return_value={'pieces': {}, 'items': []}))
        for name in ('_auto_retexture', '_auto_normalize', '_attach_measurement', 'request_lod'):
            stack.enter_context(patch.object(model3d, name))
        stack.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}))
        stack.enter_context(patch.object(model3d, '_auto_lod_enabled', return_value=False))
        model3d.set_model3d_options('demo', {'face_before_rig': True})
        with (patch.object(face, 'flatten_photo', side_effect=swap_after_validation),
              patch.object(model3d, '_character_mesh_stages', side_effect=interrupted)):
            try:
                model3d.generate_for_current_outfit('demo', signature=sig, force=True, backend_glob='mesh-fixture')
            except SystemExit:
                pass
            else:
                raise AssertionError('Expected mesh interruption')
        generated = operations[-1]
        assert generated.inputs['view_images'] == generated.inputs['view_images_sha256'] == {}
        assert generated.inputs['reference'] == 'face' and generated.inputs['upscale'] is False
        assert 'face_retexture' not in generated.inputs, generated.inputs
        assert generated.abs('inputs/photo.png').read_bytes() == face.flatten_photo(photo())
        hub_ops.delete(generated)
        face_path.write_bytes(photo())
        face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': meta['source_image_sha256'], 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
        swapped = False
        with (patch.object(face, 'flatten_photo', side_effect=swap_after_validation),
              patch.object(model3d, '_face_source_stages', side_effect=interrupted)):
            try:
                model3d.face_retexture_model('demo', sig)
            except SystemExit:
                pass
            else:
                raise AssertionError('Expected interruption after frozen inputs')
        frozen = operations[-1]
        assert frozen.inputs['reference'] == 'face' and frozen.inputs['upscale'] is False
        assert frozen.abs('inputs/photo.png').read_bytes() == flatten(photo())
        # Delete the live close-up: resumed stages must still project frozen bytes.
        face_path.unlink()
        resumed = hub_ops.get(frozen.op_id)
        assert resumed.inputs['reference'] == 'face'
        result = hub_ops.resume(resumed, lambda: model3d._face_retexture_model(
            'demo', sig, _op_ctx={'op': resumed}))
        assert result['ok'], result
        published_meta = face.read_meta(root / f'{sig}.glb')['face_retexture']
        assert published_meta['reference'] == 'face'
        assert published_meta['upscale'] == {'status': 'off', 'reason': 'face view'}
        assert published_meta['status'] == 'applied'
    # Piece edits must also remove the close-up through the shared prefix parser.
    face_path.write_bytes(photo())
    face_path.with_suffix('.json').write_text(json.dumps({'pieces': {'body': 'shirt'}, 'items': []}))
    assert sig in mr.invalidate_refs_for_item('demo', 'shirt')
    assert not face_path.exists() and not face_path.with_suffix('.json').exists()
    print('PASS: face render provenance, mesh input/hash exclusion, publication-race snapshots (both paths), frozen resume, sidecar and piece purge')


if __name__ == '__main__':
    main()
