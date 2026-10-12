"""Correct eligible stored character meshes, once per source generation."""
import hashlib
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


def split_key(key: str) -> tuple[str, str, str]:
    name, signature, source = key.removeprefix('character:').rsplit(':', 2)
    return name, signature, source


def source_token(root, signature: str) -> str:
    from app.core.face_retexture import read_meta
    meta = read_meta(root / 'unrigged' / f'{signature}.glb')
    identity = str(meta.get('created_at') or '') + str(meta.get('job_id') or '')
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]


class FaceRetexture(ImprovementType):
    id = 'face_retexture'
    label = 'Face retexture'

    @property
    def params_schema(self) -> List[ParamField]:
        from app.imagegen.service import get_image_service
        backends = get_image_service().backends

        def options(category, media):
            # Availability is transient: keep configured picks selectable while
            # offline, and let apply defer them without losing candidates.
            return [{'value': '', 'label': 'Auto (routing)'}] + [
                {'value': b.name, 'label': b.name} for b in backends
                if b.instance_enabled and b.category == category
                and getattr(b, 'MEDIA_TYPE', 'image') == media]

        return [
            ParamField('character', 'Character', 'text', required=False),
            ParamField('backend', 'Face retexture backend', 'mesh_backend',
                       options('face_retexture', 'mesh'), required=False),
            ParamField('upscale', 'Upscale reference first', 'enum',
                       [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'}], default='yes'),
            ParamField('upscale_backend', 'Upscale backend', 'image_backend',
                       options('upscale', 'image'), required=False),
        ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        # An unknown name would scan to nothing and close a one_shot as done.
        if out.get('character') and out['character'] not in subjects.characters():
            raise ValueError('Character not found')
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        from app.core.face_retexture import check
        from app.core.model3d import get_model3d_dir
        out = []
        names = [params['character']] if params.get('character') else subjects.characters()
        for name in names:
            root = get_model3d_dir(name)
            for signature in subjects.character_model_signatures(name):
                candidate = Candidate(
                    f'character:{name}:{signature}:{source_token(root, signature)}',
                    f'{name} · {signature[:8]}')
                if not self.is_done(candidate, params) and check(name, signature)['ok']:
                    out.append(candidate)
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.face_retexture import read_meta
        from app.core.model3d import get_model3d_dir
        name, signature, _source = split_key(candidate.key)
        state = read_meta(get_model3d_dir(name) / f'{signature}.glb').get('face_retexture') or {}
        return state.get('status') in ('applied', 'reverted')

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import face_retexture, model3d
        from app.imagegen.base import BackendBusyError
        name, signature, source = split_key(candidate.key)
        if (self.is_done(candidate, params)
                or source_token(model3d.get_model3d_dir(name), signature) != source
                or not face_retexture.check(name, signature)['ok']):
            return
        # Match the manual producer's character-wide guard as well as the
        # core's publication lock; always release it, including on failure.
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
            model3d._generating.add(name)
        try:
            if (self.is_done(candidate, params)
                    or source_token(model3d.get_model3d_dir(name), signature) != source
                    or not face_retexture.check(name, signature)['ok']):
                return
            backend = params.get('backend', '')
            ready = face_retexture.runnable(name, backend)
            if not ready['ok']:
                raise BackendBusyError('; '.join(p['message'] for p in ready.get('problems', []))
                                       or 'Face retexture is not runnable')
            result = model3d.face_retexture_model(
                name, signature, backend_glob=backend,
                upscale=params.get('upscale', 'yes') != 'no',
                upscale_backend_glob=params.get('upscale_backend', ''))
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Face retexture failed')
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
