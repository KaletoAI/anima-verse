#!/usr/bin/env python3
"""P4 expectations derived by hand from plan sections 7 and 13/13a.

Five stored combinations: eligible, applied, reverted, missing source, bad
source -> exactly one candidate, independent of backend availability. Its
source generation token is SHA256(created_at + job_id)[:12]; replacing that
sidecar changes the key even with the same outfit signature. Busy readiness
spends zero engine attempts and leaves pending; false core result raises and
spends two attempts before skipped. Done, reverted, now-ineligible and stale
source candidates are no-ops. Default upscale is auto (None: the core upscales
the front view only, never the face view); yes, no and an explicit
upscaler reach the synchronous core separately from its default face params.
A worked-off one_shot closes; standing stays open and rescans a regenerated
model. Own empty options must remain distinguishable from global options.
Fixtures and fake backends need no network, Blender or real world data.
Usage: ./.venv/bin/python scripts/smoke_face_retexture_improvement.py
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from smoke_face_retexture_check import fixture_doc, glb, photo


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(Path(tmp) / 'world')
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import db, model3d, face_retexture
        from app.core.improvements import engine, registry, store
        from app.core.improvements.base import ParamField
        from app.core.improvements.types.face_retexture import FaceRetexture
        from app.imagegen.base import BackendBusyError
        db.init_schema()
        root = Path(tmp) / 'world' / 'characters' / 'demo' / 'model3d'
        (root / 'unrigged').mkdir(parents=True)
        refs = root.parent / 'model_refs'
        refs.mkdir()
        source = glb(*fixture_doc())
        sigs = [f'{n:012x}' for n in range(1, 6)]
        stamp = '2026-01-01T00:00:00+00:00'

        def seed(sig, status='', job='source-1'):
            (root / f'{sig}.glb').write_bytes(source)
            (root / f'{sig}.json').write_text(json.dumps({'face_retexture': {'status': status}}))
            (root / 'unrigged' / f'{sig}.glb').write_bytes(source)
            (root / 'unrigged' / f'{sig}.json').write_text(json.dumps({'created_at': stamp, 'job_id': job}))
            (refs / f'tpose_{sig}.png').write_bytes(photo())

        for sig, status in zip(sigs, ['', 'applied', 'reverted', '', '']):
            seed(sig, status)
        (root / 'unrigged' / f'{sigs[3]}.glb').unlink()
        (root / 'unrigged' / f'{sigs[4]}.glb').write_bytes(b'invalid')
        service = SimpleNamespace(backends=[
            SimpleNamespace(name='face-fake', category='face_retexture', MEDIA_TYPE='mesh', instance_enabled=True),
            SimpleNamespace(name='up-fake', category='upscale', MEDIA_TYPE='image', instance_enabled=True),
            SimpleNamespace(name='mesh-fake', category='img2mesh', MEDIA_TYPE='mesh', instance_enabled=True)])
        with patch('app.core.improvements.types.subjects.characters', return_value=['demo']), \
             patch.object(model3d, 'required_rig', return_value='mixamo'), \
             patch('app.imagegen.service.get_image_service', return_value=service):
            typ = FaceRetexture()
            assert registry.get('face_retexture') is not None
            params = typ.validate({})
            assert params['upscale'] == 'auto' and params['character'] == ''
            assert typ.validate({'character': 'demo'})['character'] == 'demo'
            for bad in [{'upscale': 'maybe'}, {'backend': 'mesh-fake'},
                        {'upscale_backend': 'mesh-fake'}, {'character': 'nobody'}]:
                try:
                    typ.validate(bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError('invalid parameter accepted')
            fields = {f.key: f.to_dict() for f in typ.params_schema}
            assert [o['value'] for o in fields['backend']['options']] == ['', 'face-fake']
            assert [o['value'] for o in fields['upscale_backend']['options']] == ['', 'up-fake']
            assert ParamField('x', 'X', 'mesh_backend', []).to_dict()['own_options'] is True
            assert ParamField('x', 'X', 'mesh_backend').to_dict()['own_options'] is False
            candidate, = typ.find_candidates(params)
            token = hashlib.sha256((stamp + 'source-1').encode()).hexdigest()[:12]
            assert candidate.key == f'character:demo:{sigs[0]}:{token}'
            with patch.object(face_retexture, 'runnable', return_value={'ok': False, 'problems': []}), \
                 patch.object(model3d, 'face_retexture_model') as core:
                assert typ.find_candidates(params) == [candidate]
                try:
                    typ.apply(candidate, params, '')
                except BackendBusyError:
                    pass
                else:
                    raise AssertionError('readiness must raise busy')
                entry = store.create(typ.id, 'Smoke', params, 'one_shot')['id']
                engine.scan(entry)
                assert 'busy' in engine.handle_step({'improvement_id': entry, 'candidate_key': candidate.key})
                step, = store.list_steps(entry)
                assert (step['status'], step['attempts']) == ('pending', 0)
                core.assert_not_called()
            with patch.object(face_retexture, 'runnable', return_value={'ok': True}), \
                 patch.object(model3d, 'face_retexture_model', return_value={'ok': False, 'error': 'fake failure'}):
                try:
                    typ.apply(candidate, params, '')
                except RuntimeError as exc:
                    assert 'fake failure' in str(exc)
                else:
                    raise AssertionError('false core result must raise')
                for _ in range(2):
                    engine.handle_step({'improvement_id': entry, 'candidate_key': candidate.key})
                step, = store.list_steps(entry)
                assert (step['status'], step['attempts']) == ('skipped', 2)
                assert store.get(entry)['status'] == 'done'
            with patch.object(model3d, 'face_retexture_model') as core:
                for status in ['applied', 'reverted']:
                    seed(sigs[0], status)
                    typ.apply(candidate, params, '')
                seed(sigs[0])
                with patch.object(face_retexture, 'check', return_value={'ok': False}):
                    typ.apply(candidate, params, '')
                seed(sigs[0], job='source-2')
                typ.apply(candidate, params, '')
                core.assert_not_called()
            assert 'demo' not in model3d._generating
            regenerated, = typ.find_candidates(params)
            assert regenerated.key != candidate.key
            selected = typ.validate({'upscale': 'no', 'upscale_backend': 'up-fake', 'backend': 'face-fake'})
            with patch.object(face_retexture, 'runnable', return_value={'ok': True}), \
                 patch.object(model3d, 'face_retexture_model', return_value={'ok': True}) as core:
                typ.apply(regenerated, selected, '')
                core.assert_called_once_with('demo', sigs[0], backend_glob='face-fake', upscale=False, upscale_backend_glob='up-fake')
                core.reset_mock()
                typ.apply(regenerated, params, '')
                assert core.call_args.kwargs['upscale'] is None
                core.reset_mock()
                typ.apply(regenerated, typ.validate({'upscale': 'yes'}), '')
                assert core.call_args.kwargs['upscale'] is True
                once = store.create(typ.id, 'Smoke', params, 'one_shot')['id']
                engine.scan(once)
                engine.handle_step({'improvement_id': once, 'candidate_key': regenerated.key})
                assert store.get(once)['status'] == 'done'
                standing = store.create(typ.id, 'Smoke', params, 'standing')['id']
                engine.scan(standing)
                seed(sigs[0], 'applied', 'source-2')
                engine.scan(standing)
                seed(sigs[0], job='source-3')
                assert engine.scan(standing)['added'] == 1
                assert store.get(standing)['status'] == 'open'
                assert sum(s['status'] == 'pending' for s in store.list_steps(standing)) == 1
        print('face retexture improvement: all checks passed')


if __name__ == '__main__':
    main()
