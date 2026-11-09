"""Fit the collision capsules of humanoid models that have none or an outdated set."""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


class CollisionCapsules(ImprovementType):
    id = 'collision_capsules'
    label = 'Collision capsules'

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField('character', 'Character', 'enum',
                           [{'value': '', 'label': 'All characters'}] +
                           [{'value': n, 'label': n} for n in subjects.characters()], required=False)]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get('character') and out['character'] not in subjects.characters():
            raise ValueError('Character not found')
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        out = []
        names = [params['character']] if params.get('character') else subjects.characters()
        for name in names:
            for signature in subjects.character_model_signatures(name):
                candidate = Candidate(f'character:{name}:{signature}', f'{name} · {signature[:8]}')
                if not self.is_done(candidate, params):
                    out.append(candidate)
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core import collision
        from app.core.model3d import get_model3d_dir
        from app.core.model_store import read_sidecar
        name, signature = candidate.key.removeprefix('character:').rsplit(':', 1)
        path = get_model3d_dir(name) / f'{signature}.glb'
        if not path.is_file():
            return True
        meta = read_sidecar(path)
        if not collision.applies(path, meta):
            return True
        _source, sha = collision.identity(path, meta)
        return collision.is_current(meta.get('collision'), sha, collision.character_scales(name))

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import collision, model3d
        name, signature = candidate.key.removeprefix('character:').rsplit(':', 1)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
        if self.is_done(candidate, params):
            return
        record = collision.ensure(name, signature)
        if record is None:
            raise CandidateBusy(f'{name}: model replaced while fitting')
        if record.get('error'):
            raise RuntimeError(record['error'])
