#!/usr/bin/env python3
"""Dedicated face reference contract, derived by hand from the brief.

Only humanoids get a face view; it is not a reconstruction camera. A face
photo is eligible only when its bytes match image_sha256 and its current
profile hash equals reference_sha256. Reads never wait for the render lock; mismatches get three attempts before being rejected.
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
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import db, face_retexture as face, model_refs as mr
        from app.core.outfit_cache_gc import REF_PREFIXES
        from app.models.character import save_character_profile
        from smoke_face_retexture_rollback import photo
        db.init_schema()
        assert 'face' not in mr.TPOSE_VIEWS_BY_BODY['humanoid']
        assert 'face' not in mr.TPOSE_VIEWS_BY_BODY['animal']
        assert 'tpose_face' not in mr.VIEW_KINDS
        assert 'tpose_face_' not in REF_PREFIXES
        assert not any('face_view.png'.startswith(prefix) for prefix in REF_PREFIXES)
        (Path(tmp) / 'characters' / 'demo').mkdir(parents=True)
        assert save_character_profile('demo', {'profile_image': 'profile.png',
            'appearance': 'UNWANTED_APPEARANCE medium blonde hair',
            'outfit_description': 'UNWANTED_OUTFIT',
            'outfit_imagegen': {'loras': [{'name': 'UNWANTED_BODY_LORA'}]}})
        from app.models.character import get_character_dir
        refs = get_character_dir('demo') / 'model_refs'
        refs.mkdir(exist_ok=True)
        images = refs.parent / 'images'
        images.mkdir(exist_ok=True)
        profile = images / 'profile.png'
        profile.write_bytes(photo())
        sig = '0123456789ab'
        front = refs / f'tpose_{sig}.png'
        front.write_bytes(photo())
        meta = {'source_image': front.name, 'source_image_sha256': 'unrelated mesh hash'}
        render_contract(refs, profile, sig, meta)
        scheduling_contract(sig)
        reference_slots_contract(profile)
        background_contract(refs, sig)
        integration(Path(tmp), refs, sig, front, meta)
    print('PASS: profile-based face view, bald bare prompt, square render, provenance, stale/missing profile, cache, source defaults and frozen operations')


def render_contract(refs, profile, sig, meta):
    """Hand expectations: only face text, 1024 square, profile byte hash;
    changing a profile makes the face stale, changing the outfit cannot.
    A cached T-pose pass adds a missing/stale face, never forces a fresh one.
    """
    from app.core import expression_regen as er, face_retexture as face, model_refs as mr
    from smoke_face_retexture_rollback import photo
    from PIL import Image
    import io
    target = refs / 'face_view.png'
    with patch('app.models.character.get_character_profile_image', return_value='../escape.png'):
        assert mr.current_profile_image('demo') is None
    outside = refs.parent.parent / 'outside.png'
    outside.write_bytes(photo())
    link = profile.parent / 'escape.png'
    link.symlink_to(outside)
    with patch('app.models.character.get_character_profile_image', return_value=link.name):
        assert mr.current_profile_image('demo') is None
    link.unlink()
    seen = []
    class Service:
        enabled = True
        last_image_meta = {'created_at': '2026-10-16T12:00:00Z'}
        suffix = '.png'
        def generate_from_input(self, raw):
            payload = json.loads(raw)
            assert payload['image_use_case'] == 'face_view'
            assert payload['occasion'] == 'tpose_view'
            assert payload['record_provenance'] is True
            assert payload['override_width'] == payload['override_height'] == 1024
            assert 'head only' in payload['prompt'] and 'completely bald' in payload['prompt']
            # Albedo-like light (user decision 2026-10-16): uniform neutral light in the
            # prompt, shadows AND highlights pushed away by the use-case negative.
            assert 'perfectly uniform' in payload['prompt'] and 'neutral white ambient light' in payload['prompt']
            assert 'no shadows' not in payload['prompt']
            from app.core.config import get_use_case_prompts
            for family in ('natural', 'keywords'):
                negative = get_use_case_prompts('face_view', family)['prompt_negative']
                assert all(w in negative for w in ('shadows', 'specular highlights', 'shiny skin', 'catchlights', 'rim light'))
            assert all(word not in raw for word in ('UNWANTED_APPEARANCE', 'UNWANTED_OUTFIT', 'medium blonde hair', 'UNWANTED_BODY_LORA'))
            assert not payload.get('loras')
            reference = Path(mr.checked_reference_override('demo', payload['reference_image_override']))
            seen.append(reference.read_bytes())
            output = profile.parent / ('render' + self.suffix)
            if self.suffix == '.jpg':
                Image.new('RGB', (32, 32), 'red').save(output, 'JPEG')
            else:
                output.write_bytes(photo())
            return '/images/' + output.name
    with (patch('app.imagegen.service.get_image_service', return_value=Service()),
          patch('app.models.character.postprocess_outfit_image', side_effect=lambda p: p),
          patch.object(mr, 'is_humanoid', return_value=True),
          patch.object(mr, 'enabled_tpose_views', return_value=('face',)),
          patch.object(mr, 'get_view_kinds', return_value={'face': True}),
          patch.object(mr, '_start_face_view', side_effect=lambda name, force: mr.generate_face_view(name, force))):
        def tpose_pass():
            mr.generate_model_ref_images('demo', kinds=('tpose',), force=False,
                pieces={}, items=[], signature=sig)
        assert face.reference_info('demo', sig, meta)['face_problem']['code'] == 'no_face_photo'
        tpose_pass()
        assert len(seen) == 1 and seen[-1] == profile.read_bytes()
        cert = face.read_meta(target)
        assert cert['profile_image'] == 'profile.png'
        assert cert['reference_sha256'] == hashlib.sha256(seen[-1]).hexdigest()
        assert cert['image_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert face.reference_info('demo', sig, meta)['reference'] == 'face'
        assert face.reference_info('demo', 'another-outfit', {})['reference'] == 'face'
        assert face.use_upscale('face', None) is False
        assert face.use_upscale('front', None) is True
        tpose_pass()
        assert len(seen) == 1
        certified_bytes = target.read_bytes()
        target.write_bytes(b'publication not self-verified')
        tpose_pass()
        assert len(seen) == 1  # automatic eligibility is missing or profile-stale only
        assert not face.reference_info('demo', sig, meta)['face_available']
        target.write_bytes(certified_bytes)
        buf = io.BytesIO()
        Image.new('RGB', (32, 32), 'blue').save(buf, 'PNG')
        profile.write_bytes(buf.getvalue())
        assert face.reference_info('demo', sig, meta)['reference'] == 'front'
        assert face.reference_info('demo', sig, meta)['face_problem']['code'] == 'face_stale'
        assert mr.face_view_info('demo')['stale'] is True
        tpose_pass()
        assert len(seen) == 2
        assert mr.generate_face_view('demo', True) == target
        assert len(seen) == 3
        held, release = threading.Event(), threading.Event()
        def hold_render():
            with mr._kind_lock(('demo', 'face_view')):
                held.set()
                release.wait(3)
        holder = threading.Thread(target=hold_render)
        holder.start()
        assert held.wait(2)
        try:
            assert face.reference_info('demo', sig, meta)['face_available']
            assert holder.is_alive()
        finally:
            release.set()
            holder.join(2)
        valid = face.read_meta(target)
        with patch.object(face, 'read_meta', side_effect=[
                {**valid, 'image_sha256': 'publishing'},
                {**valid, 'image_sha256': 'publishing'}, valid]) as reads:
            assert face.reference_info('demo', sig, meta)['face_available']
            assert reads.call_count == 3
        profile.unlink()
        assert mr.generate_face_view('demo', True) is None
        assert face.reference_info('demo', sig, meta)['face_problem']['code'] == 'no_profile_image'
        profile.write_bytes(photo())
        mr.generate_face_view('demo', True)
        Service.suffix = '.jpg'
        assert mr.generate_face_view('demo', True) == target
        assert target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        assert face.read_meta(target)['image_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert face.reference_info('demo', sig, meta)['face_available']
        with patch.object(mr, 'current_outfit_state', return_value=({}, [], 'different-outfit')):
            info = mr.get_model_refs_info('demo')
            assert info['views']['face']['info']['filename'] == 'face_view.png'
            assert info['face_view'] == {'exists': True, 'stale': False, 'rendering': False,
                'created_at': '2026-10-16T12:00:00Z', 'width': 32, 'height': 32,
                'url': '/characters/demo/model-refs/face_view'}
        from app.routes.characters import get_character_model_ref_image
        from starlette.requests import Request
        response = get_character_model_ref_image('demo', 'face_view', Request({'type': 'http', 'headers': []}))
        assert response.status_code == 200 and response.headers.get('etag')
        cached = get_character_model_ref_image('demo', 'face_view', Request({'type': 'http',
            'headers': [(b'if-none-match', response.headers['etag'].encode())]}))
        assert cached.status_code == 304
    # The fixed face pair is not an outfit entry and survives piece invalidation.
    assert mr.invalidate_refs_for_item('demo', 'shirt') == set()
    assert target.exists()


def scheduling_contract(sig):
    """Two automatic triggers queue one worker, including before it starts.
    Thread exhaustion must not abort T-pose or prevent the next retry.
    """
    from app.core import model_refs as mr
    queued = []
    class DeferredThread:
        def __init__(self, *, target, daemon):
            self.target = target
        def start(self):
            queued.append(self.target)
    def tpose_pass():
        return mr.generate_model_ref_images('demo', kinds=('tpose',),
            pieces={}, items=[], signature=sig)
    with (patch.object(mr, 'is_humanoid', return_value=True),
          patch.object(mr, 'get_view_kinds', return_value={'face': True}),
          patch.object(mr, 'enabled_tpose_views', return_value=('face',)),
          patch.object(mr.threading, 'Thread', DeferredThread)):
        tpose_pass()
        tpose_pass()
        assert len(queued) == 1, 'Duplicate automatic worker before first starts'
        def running_worker(*args):
            # The reservation also lasts throughout the target's execution.
            mr._start_face_view('demo', False)
            assert queued == []
            mr._start_face_view('demo', True)
            assert len(queued) == 1, 'Explicit force must still queue'
        with patch.object(mr, 'generate_face_view', side_effect=running_worker):
            queued.pop()()
        with patch.object(mr, 'generate_face_view'):
            queued.pop()()
        for failure in ('construction', 'start'):
            with patch.object(mr.threading, 'Thread') as thread:
                if failure == 'construction':
                    thread.side_effect = RuntimeError('thread exhaustion')
                else:
                    thread.return_value.start.side_effect = RuntimeError('thread exhaustion')
                assert tpose_pass() == {}
            tpose_pass()
            assert len(queued) == 1, 'Failed scheduling leaked worker reservation'
            with patch.object(mr, 'generate_face_view'):
                queued.pop()()
    print('PASS: automatic worker coalescing and scheduling failure isolation')


def reference_slots_contract(profile):
    """Zero slots, missing slots and a substituted ref cannot certify a face.
    A capable face render and an ordinary zero-slot T-pose still reach the GPU.
    """
    from app.imagegen import routing, service as svc
    from app.imagegen.base import ImageBackend, BackendNotApplicableError, BackendFailedError
    from app.imagegen.selection import BackendPool
    from app.core.prompt_builder import PromptBuilder
    class Backend(ImageBackend):
        def __init__(self):
            super().__init__('face-slot-smoke', 'http://unused', 0, 'fake', 'FACE_SMOKE_')
            self.ref_slot_count = 1
            self._available = True
        def check_availability(self):
            return True
        def _generate(self, *args):
            raise AssertionError('No external generation')
    backend = Backend()
    with patch.object(svc.ImageService, '_load_instances', return_value=[]):
        service = svc.ImageService()
    payload = {'prompt': 'head only', 'agent_name': 'demo', 'auto_enhance': False,
               'skip_gallery': True, 'profile_only': True, 'image_use_case': 'face_view',
               'appearances': [{'name': 'demo', 'appearance': ''}],
               'reference_image_override': str(profile), 'record_provenance': True}
    parsed = service._parse_input(json.dumps(payload))
    assert parsed.get('record_provenance') is True, 'Provenance flag lost at service boundary'
    published_before = {p: p.read_bytes() for p in profile.parent.iterdir() if p.is_file()}
    class ReachedBackend(Exception):
        pass
    def render(*args, **kwargs):
        raise ReachedBackend()
    with (patch.object(service, '_get_instance_config', return_value={}),
          patch.object(service, 'run_on_backend', side_effect=render)):
        for slots, resolved in ((0, None), (1, {}), (1, {'input_reference_image_1': 'wrong.png'})):
            backend.ref_slot_count = slots
            with ExitStack() as stack:
                if resolved is not None:
                    stack.enter_context(patch.object(PromptBuilder, 'resolve_reference_slots',
                        return_value={'reference_images': resolved, 'has_reference_slots': bool(resolved)}))
                try:
                    service.generate_on_backend(backend, dict(parsed), explicit=False)
                except BackendNotApplicableError as exc:
                    assert 'face view needs one' in str(exc)
                else:
                    raise AssertionError('Unconditioned face accepted')
        for provenance, slots in ((True, 1), (False, 0)):
            backend.ref_slot_count = slots
            try:
                service.generate_on_backend(backend, {**parsed, 'record_provenance': provenance}, explicit=False)
            except ReachedBackend:
                pass
            else:
                raise AssertionError('Valid face or ordinary T-pose did not reach backend')
        # Real routing must skip the incompatible character match and chain
        # entry, including when a failed backend causes a complete re-run.
        bad, good, failed = Backend(), Backend(), Backend()
        bad.name, good.name, failed.name = 'no-ref', 'with-ref', 'failed'
        bad.ref_slot_count = 0
        pool = BackendPool([bad, good, failed])
        attempts = []
        def routed_render(b):
            attempts.append(b.name)
            if b is failed:
                raise BackendFailedError(b, RuntimeError('GPU failure'))
            try:
                service.generate_on_backend(b, dict(parsed), explicit=False)
            except ReachedBackend:
                return b.name
        with (patch.object(routing, '_character_spec', return_value='no-ref'),
              patch.object(routing, '_rules', return_value=['with-ref'])):
            result, route = routing.run_routed('tpose_view', routed_render,
                character='demo', has_ref=True, pool=pool)
            assert result == 'with-ref' and attempts == ['no-ref', 'with-ref']
            assert route.chain[0]['status'] == 'no_match'
            assert not bad.in_cooldown()
        attempts.clear()
        with (patch.object(routing, '_character_spec', return_value='failed'),
              patch.object(routing, '_rules', return_value=['no-ref', 'with-ref'])):
            result, route = routing.run_routed('tpose_view', routed_render,
                character='demo', has_ref=True, pool=pool)
            assert result == 'with-ref' and attempts == ['failed', 'no-ref', 'with-ref']
            assert route.chain[1]['status'] == 'no_match'
    assert {p: p.read_bytes() for p in profile.parent.iterdir() if p.is_file()} == published_before
    print('PASS: provenance reference-slot enforcement, character/chain skips and re-runs; ordinary zero-slot renders preserved')


def background_contract(refs, sig):
    """A waiting face GPU call must not delay a cached T-pose pass."""
    from app.core import model_refs as mr, outfit_cache_gc as gc
    from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
    from app.core.head_twist import tpose_status
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow_face(*args):
        started.set()
        try:
            assert release.wait(3)
        finally:
            finished.set()
    with (patch.object(mr, 'generate_face_view', side_effect=slow_face),
          patch.object(mr, 'is_humanoid', return_value=True),
          patch.object(mr, 'get_view_kinds', return_value={'face': True}),
          patch.object(mr, 'enabled_tpose_views', return_value=('face',))):
        try:
            assert mr.generate_model_ref_images('demo', kinds=('tpose',),
                pieces={}, items=[], signature=sig) == {}
            assert started.wait(2) and not finished.is_set()
        finally:
            release.set()
            assert finished.wait(2)
    target = refs / 'face_view.png'
    # Real cache collection and purge must never enumerate the fixed pair.
    assert all(target not in files and target.with_suffix('.json') not in files
               for files in gc._ref_files('demo').values())
    front = refs / f'tpose_{sig}.png'
    front_bytes = front.read_bytes()
    with patch.object(gc, 'verify_cache', return_value={'stale_signatures': [sig]}):
        gc.purge_stale('demo', [sig])
    assert not front.exists()
    front.write_bytes(front_bytes)
    assert target.exists() and target.with_suffix('.json').exists()
    assert OpenAIMeshBackend._input_images({'reference_images': {'face': 'face.png'},
                                          'source_image_path': 'front.png'}) == {'front': 'front.png'}
    assert 'face.png' not in OpenAIMeshBackend.mesh_slot_views(
        'humanoid', 'front.png', {'face': 'face.png'}, ['input_image']).values()
    front = refs / f'tpose_{sig}.png'
    assert tpose_status('exact', {'source_image_sha256': hashlib.sha256(front.read_bytes()).hexdigest(),
        'view_images': {'face': 'missing.png'}, 'view_images_sha256': {'face': 'ignored'}}, front) == 'current'


def integration(tmp, refs, sig, front, meta):
    """Exercise the real render/orchestrator/stages with external services faked."""
    from app.core import db, expression_regen, face_retexture as face, hub_ops, model3d, model_refs as mr
    from app.models.character import save_character_profile
    from smoke_face_retexture_rollback import fixture, photo
    paths.init_instance(tmp / 'instance')
    db.init_schema()
    assert save_character_profile('demo', {'profile_image': 'profile.png'})
    face_path = refs / 'face_view.png'
    face_path.write_bytes(photo())
    profile = refs.parent / 'images' / 'profile.png'
    profile.write_bytes(photo())
    profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
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
    face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': profile_hash, 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
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
        face_path.with_suffix('.json').write_text(json.dumps({'reference_sha256': profile_hash, 'image_sha256': hashlib.sha256(face_path.read_bytes()).hexdigest()}))
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
    # Outfit invalidation must preserve the per-character face pair.
    face_path.write_bytes(photo())
    face_path.with_suffix('.json').write_text(json.dumps({'pieces': {'body': 'shirt'}, 'items': []}))
    mr.invalidate_refs_for_item('demo', 'shirt')
    assert face_path.exists() and face_path.with_suffix('.json').exists()
    print('PASS: mesh input/hash exclusion, publication-race snapshots (both paths), frozen resume, sidecar and face preservation')


if __name__ == '__main__':
    main()
